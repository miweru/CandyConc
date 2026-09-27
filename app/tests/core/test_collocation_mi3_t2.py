"""T2a — MI3 (Oakes 1998) in the collocation engine.

Golden checks against INDEPENDENTLY computed values (plain-Python ``math``
arithmetic on constructed counts, no engine code) plus edge cases:

    mi3 = log2(O11^3 / E11)

computed over EXACTLY the same observed/expected pair as MI, so the identity
``mi3 == mi + 2*log2(O11)`` must hold to float precision. O11 = 0 (or E = 0)
yields 0.0, the same convention as MI.
"""

from __future__ import annotations

import math
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.core.collocation_engine import CollocationEngine  # noqa: E402


class _StubLexicon:
    vocab_size = 8

    def __init__(self, freqs: dict[int, float]) -> None:
        self._freqs = freqs

    def get_freqs_for_ids(self, ids: np.ndarray) -> np.ndarray:
        return np.array([self._freqs.get(int(i), 0.0) for i in ids], dtype=np.float64)

    def get_strings_for_ids(self, ids: np.ndarray) -> list[str]:
        return [f"w{int(i)}" for i in ids]


def _engine(total_tokens: int) -> CollocationEngine:
    engine = CollocationEngine.__new__(CollocationEngine)
    engine.lexicons = SimpleNamespace(total_tokens=total_tokens)
    engine._lock = threading.RLock()
    engine._docset_dense_stats_cache = OrderedDict()
    return engine


# Constructed counting scenario (same shape as the selected-scores pin test):
# m = 23 anchors, context mass u = 180, scope total 4000 tokens.
_COUNTS = {1: 14, 2: 7, 3: 2}
_FREQS = {1: 120.0, 2: 80.0, 3: 30.0}
_M = 23
_U = 180
_TOTAL = 4000


def _hand_expected(freq: float) -> float:
    # E11 = u * C1 / N_event with C1 = freq*m and N_event = total*m  ==>  u*freq/total
    return _U * freq / _TOTAL


def test_mi3_matches_hand_computation():
    engine = _engine(_TOTAL)
    arrays = engine._calculate_statistics_arrays(_COUNTS, _M, _U, _StubLexicon(_FREQS))
    assert len(arrays) == 14  # word_ids + 13 statistics, mi3 appended last
    by_id = {int(word_id): i for i, word_id in enumerate(arrays[0])}
    observed, expected, mi, mi3 = arrays[1], arrays[2], arrays[3], arrays[13]

    for word_id, obs in _COUNTS.items():
        i = by_id[word_id]
        e_hand = _hand_expected(_FREQS[word_id])
        mi3_hand = math.log2(obs**3 / e_hand)
        assert expected[i] == pytest.approx(e_hand, rel=1e-12)
        assert mi3[i] == pytest.approx(mi3_hand, rel=1e-12)
        # Same-O/E identity: mi3 = mi + 2*log2(O11).
        assert mi3[i] == pytest.approx(mi[i] + 2.0 * math.log2(obs), rel=1e-12)

    # Fixed literal anchor (hand-derived): O=14, E = 180*120/4000 = 5.4
    #   mi3 = log2(14^3 / 5.4) = log2(2744/5.4) = 8.98910536...
    assert mi3[by_id[1]] == pytest.approx(math.log2(2744.0 / 5.4), rel=1e-12)
    assert round(float(mi3[by_id[1]]), 4) == 8.9891

    # observed[i] stays the raw count (mi3 must not mutate shared arrays).
    assert observed[by_id[1]] == 14.0


def test_mi3_zero_observed_is_zero():
    engine = _engine(_TOTAL)
    zero = np.array([0.0, 3.0])
    expected = np.array([1.5, 1.5])
    score = engine._calculate_selected_score_array(
        zero,
        expected,
        np.array([10.0, 10.0]),
        context_mass=float(_U),
        event_total=float(_TOTAL * _M),
        score_key="mi3",
    )
    assert score[0] == 0.0
    assert score[1] == pytest.approx(math.log2(3.0**3 / 1.5), rel=1e-12)


def test_selected_score_mi3_parity_with_full_arrays():
    engine = _engine(_TOTAL)
    lex = _StubLexicon(_FREQS)
    arrays = engine._calculate_statistics_arrays(_COUNTS, _M, _U, lex)
    ids_sel, observed_sel, score_sel = engine._calculate_selected_statistics_arrays(
        _COUNTS, _M, _U, lex, score_key="mi3"
    )
    full_by_id = {int(w): float(arrays[13][i]) for i, w in enumerate(arrays[0])}
    for word_id, score in zip(ids_sel, score_sel):
        assert score == pytest.approx(full_by_id[int(word_id)], rel=1e-12)


def test_frame_carries_rounded_mi3_column_and_sort_shape():
    engine = _engine(_TOTAL)
    lex = _StubLexicon(_FREQS)
    arrays = engine._calculate_statistics_arrays(_COUNTS, _M, _U, lex)
    sorted_arrays = engine._sort_statistics_arrays(*arrays, top_n=None)
    # Legacy cache tuple shape preserved: ranks at index 11, 15 arrays total.
    assert len(sorted_arrays) == 15
    assert list(sorted_arrays[11]) == [1, 2, 3]
    # node_frequency ist seit dem 2026-08-29 pflichtig: logdice nach
    # Rychly hat f(u) im Nenner, und ein Vorgabewert machte drei
    # Produktivpfade still falsch.
    df = engine._statistics_frame_from_sorted(
        *sorted_arrays, lex=lex, node_frequency=10,
        # R1 und N sind seit dem 2026-08-29 pflichtig: der LRC rechnet auf
        # Everts Distanztafel und braucht beide Randsummen. Ein
        # Vorgabewert waere still falsch.
        context_mass=100.0, scope_tokens=10000.0)
    assert "mi3" in df.columns
    by_word = dict(zip(df["word"], df["mi3"]))
    assert by_word["w1"] == pytest.approx(round(math.log2(2744.0 / 5.4), 4))


def test_cached_frame_reconstruction_attaches_mi3():
    """A frame loaded from the legacy on-disk cache (no mi3 column) gets mi3
    reconstructed losslessly from the raw cached observed/expected pair."""
    engine = _engine(_TOTAL)
    cached = pd.DataFrame(
        {
            "word": ["w1", "w3"],
            "observed": [14.0, 2.0],
            "expected": [5.4, 1.35],
            "dice": [0.02, 0.005],
        }
    )
    out = engine._attach_delta_p_to_cached(
        cached, u=float(_U), event_total=float(_TOTAL * _M)
    )
    assert "mi3" in out.columns
    assert out["mi3"].iloc[0] == pytest.approx(round(math.log2(14.0**3 / 5.4), 4))
    assert out["mi3"].iloc[1] == pytest.approx(round(math.log2(2.0**3 / 1.35), 4))
    # delta-P columns are still attached as before (additive change).
    assert "delta_p_nc" in out.columns and "delta_p_cn" in out.columns
    # The input frame is not mutated.
    assert "mi3" not in cached.columns
