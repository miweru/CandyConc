"""Regression tests for F3 — directional delta-P collocation columns.

Two layers:

1. A PURE unit test of the vectorised ``_delta_p_arrays`` helper against a
   hand-computed 2x2 contingency table (no index needed). This pins the exact
   arithmetic of both directional measures.

2. Integration tests on the REAL bench Fast Index (skipped if
   ``CANDYCONC_INDEX_PATH`` is unset) confirming that:
     * ``collocate_stats`` surfaces ``delta_p_nc`` / ``delta_p_cn`` columns,
     * the values stay within the theoretical [-1, 1] range,
     * the values reproduce a from-scratch 2x2 recomputation using the SAME
       anchor×token event-space marginal the engine uses,
     * the legacy cache round-trip reconstructs delta-P byte-identically.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

from candyconc.core.collocation_engine import CollocationEngine, _delta_p_arrays


# --------------------------------------------------------------------------- #
# Layer 1 — pure 2x2 unit test (no index)
# --------------------------------------------------------------------------- #


def test_delta_p_matches_hand_computed_2x2() -> None:
    # Hand-built contingency table:
    #   O11 = 10  (co-occurrence)
    #   R1  = 100 (node window slots)
    #   C1  = 40  (collocate marginal in the selected event space)
    #   N   = 1000
    o11, r1, c1, n = 10.0, 100.0, 40.0, 1000.0

    # deltaP(node -> collocate) = O11/R1 - (C1-O11)/(N-R1)
    #   = 10/100 - 30/900 = 0.1 - 0.033333... = 0.0666666...
    hand_nc = o11 / r1 - (c1 - o11) / (n - r1)
    # deltaP(collocate -> node) = O11/C1 - (R1-O11)/(N-C1)
    #   = 10/40 - 90/960 = 0.25 - 0.09375 = 0.15625
    hand_cn = o11 / c1 - (r1 - o11) / (n - c1)

    nc, cn = _delta_p_arrays(np.array([o11]), r1, np.array([c1]), n)

    assert nc.shape == (1,)
    assert cn.shape == (1,)
    np.testing.assert_allclose(nc[0], hand_nc, rtol=0, atol=1e-12)
    np.testing.assert_allclose(cn[0], hand_cn, rtol=0, atol=1e-12)
    # Spot-check the exact decimal values too.
    np.testing.assert_allclose(nc[0], 0.06666666666666668, atol=1e-12)
    np.testing.assert_allclose(cn[0], 0.15625, atol=1e-12)


def test_delta_p_vectorised_matches_scalar_loop() -> None:
    rng = np.random.default_rng(7)
    n = 5000.0
    r1 = 250.0
    o11 = rng.integers(1, 50, size=64).astype(np.float64)
    # A valid 2x2 table requires C1 >= O11; keep it well below N.
    c1 = o11 + rng.integers(0, 200, size=64).astype(np.float64)

    nc, cn = _delta_p_arrays(o11, r1, c1, n)

    for i in range(o11.size):
        exp_nc = o11[i] / r1 - (c1[i] - o11[i]) / (n - r1)
        exp_cn = o11[i] / c1[i] - (r1 - o11[i]) / (n - c1[i])
        np.testing.assert_allclose(nc[i], exp_nc, atol=1e-12)
        np.testing.assert_allclose(cn[i], exp_cn, atol=1e-12)


def test_delta_p_rejects_mixed_event_space() -> None:
    """A pair-context mass cannot be combined with corpus-token marginals."""
    o11 = np.array([200.0, 5.0, 199.0])
    c1 = np.array([800.0, 800.0, 56000.0])
    u = 200600.0  # >> N: many overlapping node windows
    n = 56191.0

    with pytest.raises(ValueError, match="Ungültige Kollokationskontingenz"):
        _delta_p_arrays(o11, u, c1, n)


def test_delta_p_degenerate_denominators_are_finite() -> None:
    # N == R1 and N == C1 -> the "not-row"/"not-column" denominators vanish.
    nc, cn = _delta_p_arrays(np.array([1000.0]), 1000.0, np.array([1000.0]), 1000.0)
    assert np.isfinite(nc).all()
    assert np.isfinite(cn).all()
    np.testing.assert_allclose(nc[0], 1.0, atol=1e-12)
    np.testing.assert_allclose(cn[0], 1.0, atol=1e-12)

    # C1 == 0 (no column mass) -> P(.|C) terms drop, no division by zero.
    nc0, cn0 = _delta_p_arrays(np.array([0.0]), 100.0, np.array([0.0]), 1000.0)
    assert np.isfinite(nc0).all()
    assert np.isfinite(cn0).all()


# --------------------------------------------------------------------------- #
# Layer 2 — integration on the real bench index
# --------------------------------------------------------------------------- #

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

_real_index = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)


@pytest.fixture(scope="module")
def engine() -> CollocationEngine:
    eng = CollocationEngine(Path(INDEX_PATH))
    eng.load()
    return eng


@_real_index
def test_collocate_stats_exposes_delta_p_columns(engine: CollocationEngine) -> None:
    df = engine.collocate_stats("die", top_n=20, min_count=1, cache_mode="off")
    assert not df.empty
    assert "delta_p_nc" in df.columns
    assert "delta_p_cn" in df.columns
    # Both directional measures are proper conditional-probability differences
    # in [-1, 1].
    assert df["delta_p_nc"].between(-1.0, 1.0).all()
    assert df["delta_p_cn"].between(-1.0, 1.0).all()


@_real_index
def test_collocate_stats_delta_p_matches_recomputed_2x2(engine: CollocationEngine) -> None:
    """The published delta-P columns must equal a from-scratch 2x2 computation
    over the engine's own (O11, R1=u, C1, N_Omega) marginals.

    We drive the exact same internal pipeline collocate_stats uses (coverage
    sweep -> count_collocates -> _calculate_statistics_arrays) so the marginals
    are the real ones, then compare against the rounded published frame."""
    from candyconc.core.coverage_sweep import (
        coverage_sweep_arrays,
        total_context_mass_arrays,
    )
    from candyconc.core.counting_kernels import count_collocates

    term = "und"
    lex = engine._get_lexicon("word")
    term_id = engine._resolve_term_id(term, lex)
    positions = engine._get_term_positions(term, attr="word", term_id=term_id, lexicon=lex)
    assert positions.size > 0
    m = int(positions.size)

    anchors = positions.astype(np.int64, copy=False)
    spans = np.ones_like(anchors, dtype=np.int64)
    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors=anchors,
        spans=spans,
        window_left=5,
        window_right=5,
        boundaries=engine.boundaries,
        within_sentence=False,
        total_tokens=engine.token_store.token_count if engine.token_store else 0,
    )
    u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
    counts = count_collocates(engine.token_store, seg_starts, seg_ends, seg_weights)
    self_ids = set(engine._resolve_term_ids(term, lex))
    counts = {word_id: count for word_id, count in counts.items() if word_id not in self_ids}

    arrays = engine._calculate_statistics_arrays(counts, m, u, lex)
    word_ids = arrays[0]
    observed = arrays[1]
    # expected = R1*C1/N_event -> recover the event-space column marginal.
    n_total = float(engine.lexicons.total_tokens)
    # Seit dem 2026-08-29 ist der Ereignisraum das KORPUS, nicht das
    # Anker-mal-Token-Produkt. Der Faktor m kuerzt sich in E = R1*C1/N,
    # deshalb blieben MI, MI3, t, z und LMI unter beiden Tafeln gleich,
    # delta-P aber nicht. Dieser Harnisch fuhr den alten Ereignisraum
    # und verglich damit zwei verschiedene Tabellen miteinander.
    n_event = n_total
    expected = arrays[2]
    c1 = expected * n_event / float(u)
    eng_nc = arrays[11]
    eng_cn = arrays[12]

    # Independent 2x2 recomputation.
    hand_nc = observed / float(u) - (c1 - observed) / (n_event - float(u))
    hand_cn = observed / c1 - (float(u) - observed) / (n_event - c1)
    np.testing.assert_allclose(eng_nc, hand_nc, atol=1e-9)
    np.testing.assert_allclose(eng_cn, hand_cn, atol=1e-9)

    # And the published (rounded) frame must agree with the engine arrays.
    df = engine.collocate_stats(term, min_count=1, cache_mode="off")
    words = lex.get_strings_for_ids(word_ids)
    by_word_nc = dict(zip(words, np.round(eng_nc, 4)))
    by_word_cn = dict(zip(words, np.round(eng_cn, 4)))
    for _, row in df.head(50).iterrows():
        w = row["word"]
        if w in by_word_nc:
            np.testing.assert_allclose(row["delta_p_nc"], by_word_nc[w], atol=1e-9)
            np.testing.assert_allclose(row["delta_p_cn"], by_word_cn[w], atol=1e-9)


@_real_index
def test_delta_p_columns_bounded_on_real_index_high_freq_node(
    engine: CollocationEngine,
) -> None:
    """A very high-frequency node ('die'/'der'/'und') produces a large context
    mass u under pair semantics; both delta-P columns must still be in [-1, 1]
    in the published frame (the clamp/clip on the real index)."""
    for node in ("die", "der", "und"):
        df = engine.collocate_stats(node, top_n=None, min_count=1, cache_mode="off")
        if df.empty:
            continue
        assert df["delta_p_nc"].between(-1.0, 1.0).all(), node
        assert df["delta_p_cn"].between(-1.0, 1.0).all(), node


@_real_index
def test_case_insensitive_resolution_matches_plain_search_count(
    engine: CollocationEngine,
) -> None:
    """T6(a): the engine's CI term resolution must mirror
    ``CorpusIndex.term_positions(case_insensitive=True)``.

    A lowercase query of a capitalized-only noun ('menschen') must resolve to the
    SAME positions as the capitalized form ('Menschen') and as the CI plain
    search, and a multi-variant term ('ich' -> ich/Ich/ICH) must union to the
    full CI count. Proven by an exact position-count equality against the
    core CorpusIndex CI search.
    """
    from candyconc.core.corpus_index import CorpusIndex

    idx = CorpusIndex(str(INDEX_PATH), read_only=True)
    try:
        for lower, upper in (("menschen", "Menschen"), ("ich", "Ich")):
            ci_count = int(idx.term_positions(lower, case_insensitive=True).size)
            # Engine resolves the lowercase query...
            pos_lower = engine._get_term_positions(lower, attr="word")
            # ...and the capitalized form, to the SAME union.
            pos_upper = engine._get_term_positions(upper, attr="word")
            assert pos_lower.size == ci_count, (
                f"{lower}: engine CI count {pos_lower.size} != plain CI {ci_count}"
            )
            assert pos_upper.size == ci_count, (
                f"{upper}: engine CI count {pos_upper.size} != plain CI {ci_count}"
            )
            np.testing.assert_array_equal(np.sort(pos_lower), np.sort(pos_upper))
    finally:
        idx.close()


@_real_index
def test_capitalized_only_noun_queried_lowercase_has_collocates(
    engine: CollocationEngine,
) -> None:
    """B3 fix: a lowercase query of a capitalized-only noun must yield a
    non-empty collocation frame (previously resolved to id 0 -> empty)."""
    df = engine.collocate_stats("menschen", top_n=20, min_count=1, cache_mode="off")
    assert not df.empty, "lowercase 'menschen' must resolve to 'Menschen' collocates"
    df_cap = engine.collocate_stats("Menschen", top_n=20, min_count=1, cache_mode="off")
    # Same node positions -> identical collocate frames.
    assert df["word"].to_list() == df_cap["word"].to_list()


@_real_index
def test_delta_p_cache_round_trip_is_consistent(engine: CollocationEngine) -> None:
    """Fresh-computed and cache-read frames must carry byte-identical delta-P."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        df_write = engine.collocate_stats(
            "die", top_n=15, min_count=1, cache_dir=cache_dir, cache_mode="write"
        )
        df_read = engine.collocate_stats(
            "die", top_n=15, min_count=1, cache_dir=cache_dir, cache_mode="read"
        )
    assert "delta_p_nc" in df_read.columns
    assert "delta_p_cn" in df_read.columns
    merged = df_write.merge(df_read, on="word", suffixes=("_w", "_r"))
    assert not merged.empty
    np.testing.assert_array_equal(
        merged["delta_p_nc_w"].to_numpy(), merged["delta_p_nc_r"].to_numpy()
    )
    np.testing.assert_array_equal(
        merged["delta_p_cn_w"].to_numpy(), merged["delta_p_cn_r"].to_numpy()
    )
