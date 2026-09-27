"""Golden tests for core.significance (R6 keyness statistics)."""

import math

import numpy as np
import pytest
from scipy.stats import chi2 as scipy_chi2

from candyconc.core.significance import (
    bh_fdr,
    bonferroni,
    ll_to_p,
    log_ratio_ci,
    low_freq_flag,
)


def test_ll_to_p_matches_scipy_critical_values():
    # 3.84 is the chi-square(df=1) 0.05 critical value; 10.83 the 0.001 one.
    assert ll_to_p(3.84) == pytest.approx(0.05, abs=2e-3)
    assert ll_to_p(10.83) == pytest.approx(0.001, abs=2e-4)
    # Exact agreement with scipy.
    for x in (0.0, 1.0, 3.84, 6.63, 10.83, 25.0):
        assert ll_to_p(x) == pytest.approx(float(scipy_chi2.sf(x, df=1)), rel=1e-12)


def test_ll_to_p_array_and_sign_clamp():
    out = ll_to_p(np.array([3.84, 10.83]))
    assert isinstance(out, np.ndarray)
    assert out[0] == pytest.approx(0.05, abs=2e-3)
    # Negative (signed) input is clamped via abs -> same magnitude p-value.
    assert ll_to_p(-10.83) == pytest.approx(ll_to_p(10.83))


def test_bonferroni_basic():
    p = np.array([0.01, 0.04, 0.5, 0.9])
    out = bonferroni(p)
    assert out[0] == pytest.approx(0.04)
    assert out[1] == pytest.approx(0.16)
    assert out[2] == pytest.approx(1.0)  # capped
    assert out[3] == pytest.approx(1.0)
    assert bonferroni(np.array([])).size == 0


def test_bh_fdr_monotonic_and_bounded():
    p = np.array([0.001, 0.008, 0.039, 0.041, 0.9])
    q = bh_fdr(p)
    # q-values bracket [0, 1] and follow rank-monotonicity of the inputs.
    assert np.all(q >= 0.0)
    assert np.all(q <= 1.0)
    order = np.argsort(p)
    q_sorted = q[order]
    assert np.all(np.diff(q_sorted) >= -1e-12)
    # Largest p maps to its raw value (rank m): m/m * p = p.
    assert q[np.argmax(p)] == pytest.approx(0.9)


def test_bh_fdr_against_manual_step_up():
    p = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    m = p.size
    q = bh_fdr(p)
    # For evenly spaced p_i = i*0.01 with rank i, raw = p_i*m/i = 0.05 for all,
    # so every q-value equals 0.05.
    assert np.allclose(q, 0.05)
    assert m == 5


def test_log_ratio_ci_brackets_point_estimate():
    # Hand-verified point estimate with +0.5 smoothing.
    a, b, n1, n2 = 100, 10, 1_000_000, 1_000_000
    point = math.log2(((a + 0.5) / n1) / ((b + 0.5) / n2))
    lo, hi = log_ratio_ci(a, b, n1, n2)
    assert lo < point < hi
    # Hand check: ~log2(100.5/10.5) = log2(9.571) ~= 3.259
    assert point == pytest.approx(3.2589, abs=1e-3)


def test_log_ratio_ci_narrows_with_frequency():
    # Same relative rate (10:1), higher absolute counts -> tighter interval.
    lo_small, hi_small = log_ratio_ci(10, 1, 100_000, 100_000)
    lo_big, hi_big = log_ratio_ci(1000, 100, 100_000, 100_000)
    assert (hi_small - lo_small) > (hi_big - lo_big)


def test_log_ratio_ci_symmetric_in_log2_space():
    lo, hi = log_ratio_ci(50, 5, 500_000, 500_000)
    point = math.log2(((50 + 0.5) / 500_000) / ((5 + 0.5) / 500_000))
    assert (point - lo) == pytest.approx(hi - point, rel=1e-9)


def test_low_freq_flag():
    assert low_freq_flag(0) is True
    assert low_freq_flag(4) is True
    assert low_freq_flag(5) is False
    assert low_freq_flag(100) is False
    assert low_freq_flag(2, threshold=3) is True
    assert low_freq_flag(3, threshold=3) is False
