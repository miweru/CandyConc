"""Golden tests for the dispersion family (Track FT-DISPERSION-FAMILY).

Each measure is checked against an independently hand-computed value on a small
example, and against the existing Gries DP path so the family shares one
distribution. Contract: dispersion_family(counts, sizes) ->
{dp, dpnorm, juilland_d, carroll_d2, range, range_prop, vc}.
"""

import math

import numpy as np
import pytest

from candyconc.services.tools.dispersion_family import (
    carroll_d2,
    dispersion_family,
    juilland_d,
    range_count,
    range_proportion,
    variation_coefficient,
)


# Hand example: 4 EQUAL-sized parts (100 tokens each), counts [10, 0, 5, 5].
# F = 20, N = 400, n = 4.
#   Range      = 3 nonzero parts -> range_prop = 0.75
#   v_i        = o_i/s_i = [0.10, 0.0, 0.05, 0.05]; mean = 0.05
#   sigma(pop) = sqrt(mean((v-mean)^2)) = 0.05 -> VC = 1.0? recompute below
_COUNTS = [10, 0, 5, 5]
_SIZES = [100, 100, 100, 100]


def _hand_vc(counts, sizes):
    v = np.asarray(counts, float) / np.asarray(sizes, float)
    mean = v.mean()
    sd = v.std(ddof=0)
    return sd / mean


def _hand_juilland(counts, sizes):
    n = len(counts)
    return 1.0 - _hand_vc(counts, sizes) / math.sqrt(n - 1)


def _hand_carroll(counts):
    o = np.asarray(counts, float)
    F = o.sum()
    p = o[o > 0] / F
    H = -np.sum(p * np.log(p))
    return H / math.log(len(counts))


def test_range_count_and_proportion():
    assert range_count(_COUNTS) == 3
    assert range_proportion(_COUNTS) == pytest.approx(0.75)


def test_variation_coefficient_matches_hand():
    expected = _hand_vc(_COUNTS, _SIZES)
    assert variation_coefficient(_COUNTS, _SIZES) == pytest.approx(expected)
    # Concrete value: sd(pop)/mean of [0.10,0,0.05,0.05] = 0.0353553/0.05.
    assert variation_coefficient(_COUNTS, _SIZES) == pytest.approx(0.70710678, abs=1e-7)


def test_juilland_d_matches_hand():
    expected = _hand_juilland(_COUNTS, _SIZES)
    assert juilland_d(_COUNTS, _SIZES) == pytest.approx(expected)
    assert juilland_d(_COUNTS, _SIZES) == pytest.approx(0.59175171, abs=1e-7)


def test_carroll_d2_matches_hand():
    expected = _hand_carroll(_COUNTS)
    assert carroll_d2(_COUNTS) == pytest.approx(expected)
    # H = -(0.5 ln0.5 + 0.25 ln0.25 + 0.25 ln0.25) = 1.0397208; /ln(4)=1.386294.
    assert carroll_d2(_COUNTS) == pytest.approx(0.75, abs=1e-7)


def test_dispersion_family_full_block_keys_and_values():
    block = dispersion_family(_COUNTS, _SIZES)
    assert set(block) == {
        "dp",
        "dpnorm",
        "juilland_d",
        "carroll_d2",
        "range",
        "range_prop",
        "vc",
    }
    # DP over real part sizes (equal here): expected_i = 0.25 each;
    # observed = [0.5, 0, 0.25, 0.25]; DP = 0.5*(0.25+0.25+0+0) = 0.25.
    assert block["dp"] == pytest.approx(0.25)
    # DPnorm = DP / (1 - min_i expected_i) = 0.25 / (1 - 0.25) = 0.3333...
    assert block["dpnorm"] == pytest.approx(1.0 / 3.0)
    assert block["juilland_d"] == pytest.approx(0.59175171, abs=1e-7)
    assert block["carroll_d2"] == pytest.approx(0.75, abs=1e-7)
    assert block["range"] == 3
    assert block["range_prop"] == pytest.approx(0.75)
    assert block["vc"] == pytest.approx(0.70710678, abs=1e-7)


def test_dispersion_family_unequal_part_sizes():
    # Unequal sizes exercise the s_i in v_i = o_i/s_i and DP expected = s_i/N.
    counts = [6, 2, 0]
    sizes = [60, 20, 20]
    block = dispersion_family(counts, sizes)
    # v = [0.10, 0.10, 0.0]; mean=0.066667; sd(pop)=0.047140; VC=0.707107.
    assert block["vc"] == pytest.approx(0.70710678, abs=1e-7)
    # Juilland D = 1 - VC/sqrt(2) = 1 - 0.5 = 0.5.
    assert block["juilland_d"] == pytest.approx(0.5, abs=1e-7)
    assert block["range"] == 2
    assert block["range_prop"] == pytest.approx(2.0 / 3.0)
    # Carroll: p = [0.75, 0.25, 0]; H = -(0.75 ln0.75 + 0.25 ln0.25) = 0.5623351;
    # /ln(3) = 1.0986123 -> 0.5118595.
    assert block["carroll_d2"] == pytest.approx(0.51185951, abs=1e-7)


def test_perfectly_even_distribution_scores_one():
    counts = [5, 5, 5, 5]
    sizes = [100, 100, 100, 100]
    block = dispersion_family(counts, sizes)
    assert block["juilland_d"] == pytest.approx(1.0)
    assert block["carroll_d2"] == pytest.approx(1.0)
    assert block["vc"] == pytest.approx(0.0)
    assert block["range_prop"] == pytest.approx(1.0)
    assert block["dp"] == pytest.approx(0.0)


def test_maximally_clustered_scores_low():
    counts = [20, 0, 0, 0]
    sizes = [100, 100, 100, 100]
    block = dispersion_family(counts, sizes)
    # All mass in one part: Carroll H=0 -> D2=0; range_prop=0.25.
    assert block["carroll_d2"] == pytest.approx(0.0)
    assert block["range_prop"] == pytest.approx(0.25)
    assert block["range"] == 1


def test_degenerate_inputs_return_zero_not_nan():
    for block in (
        dispersion_family([], []),
        dispersion_family([0, 0, 0], [10, 10, 10]),
        dispersion_family([5], [100]),
    ):
        for key in ("dp", "dpnorm", "juilland_d", "carroll_d2", "vc"):
            assert math.isfinite(block[key])


def test_absent_term_juilland_d_is_zero_not_one():
    # Regression (C-dispersion-family-001): an absent term (0 hits / total
    # frequency 0) must NOT score juilland_d == 1.0 ("perfectly even"). With no
    # occurrences VC collapses to 0, which would otherwise yield D = 1.0 for a
    # word that does not occur at all. It must collapse to 0.0 like the rest of
    # the family and match the frontend hint "1 = sehr gleichmäßig · 0 = stark
    # geklumpt".
    counts = [0, 0, 0, 0]
    sizes = [100, 100, 100, 100]

    # Direct function: the VALUE, not just isfinite.
    assert juilland_d(counts, sizes) == 0.0

    # Full family block: every member collapses to 0 for an absent term, so
    # juilland_d must be consistent with the rest (no lone 1.0 outlier).
    block = dispersion_family(counts, sizes)
    assert block["juilland_d"] == 0.0
    assert block["carroll_d2"] == 0.0
    assert block["range"] == 0
    assert block["range_prop"] == 0.0
    assert block["vc"] == 0.0
    assert block["dp"] == 0.0
    assert block["dpnorm"] == 0.0

    # Unequal part sizes hit the same absent-term path.
    assert juilland_d([0, 0, 0], [60, 20, 20]) == 0.0


def test_family_dp_matches_gries_dp_documents_callable():
    # When wired with server._gries_dp_documents the dp/dpnorm fields are the
    # SAME values the dispersion route already emits (single source of truth).
    from candyconc.services.backend import server

    block = dispersion_family(_COUNTS, _SIZES, gries_dp=server._gries_dp_documents)
    ref = server._gries_dp_documents(np.asarray(_COUNTS), np.asarray(_SIZES))
    assert block["dp"] == pytest.approx(ref["dp"])
    assert block["dpnorm"] == pytest.approx(ref["dpnorm"])
