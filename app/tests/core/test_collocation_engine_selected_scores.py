from types import SimpleNamespace
from collections import OrderedDict
import threading

import numpy as np
import pytest

import candyconc.core.collocation_engine as ce
import candyconc.core.counting_kernels as ck
from candyconc.core.collocation_engine import CollocationEngine
from candyconc.core.counting_kernels import (
    build_dual_basis_arrays_fast,
    count_hashmap_svb_dense,
    count_hashmap_svb_dual,
    count_hashmap_svb_dual_dense,
    gather_u64_to_f64_fast,
    subtract_and_compact_dual_counts_fast,
)


class _StubLexicon:
    vocab_size = 8

    def __init__(
        self,
        freqs: dict[int, float],
        strings: dict[int, str] | None = None,
    ) -> None:
        self._freqs = freqs
        self._strings = strings or {}

    def get_freqs_for_ids(self, ids: np.ndarray) -> np.ndarray:
        return np.array(
            [self._freqs.get(int(word_id), 0.0) for word_id in ids],
            dtype=np.float64,
        )

    def get_strings_for_ids(self, ids: np.ndarray) -> list[str]:
        return [self._strings.get(int(word_id), str(int(word_id))) for word_id in ids]


def _engine_with_total_tokens(total_tokens: int) -> CollocationEngine:
    engine = CollocationEngine.__new__(CollocationEngine)
    engine.lexicons = SimpleNamespace(total_tokens=total_tokens)
    return engine


def _engine_with_dense_cache(max_bytes: int) -> CollocationEngine:
    engine = CollocationEngine.__new__(CollocationEngine)
    engine._lock = threading.RLock()
    engine._docset_dense_stats_cache = OrderedDict()
    engine._docset_dense_stats_cache_max = 6
    engine._docset_dense_stats_cache_bytes = 0
    engine._docset_dense_stats_cache_max_bytes = max_bytes
    return engine


def _svb_encode(values: list[int]) -> bytes:
    groups = (len(values) + 3) // 4
    controls = bytearray(groups)
    payload = bytearray()
    for g in range(groups):
        ctrl = 0
        for i in range(4):
            idx = g * 4 + i
            if idx >= len(values):
                break
            value = int(values[idx])
            ctrl |= ((1 - 1) & 0x3) << (2 * i)
            payload.append(value & 0xFF)
        controls[g] = ctrl
    return bytes(controls + payload)


def _fake_token_store(values: list[int]):
    block_size = len(values)
    blob = _svb_encode(values)
    stream = SimpleNamespace(
        offsets=np.array([0, len(blob)], dtype=np.uint64),
        data=blob,
        block_size=block_size,
    )
    return SimpleNamespace(word_stream=stream, lemma_stream=stream, token_count=len(values))


def test_selected_statistics_arrays_match_full_statistics_for_all_scores() -> None:
    engine = _engine_with_total_tokens(10_000)
    lexicon = _StubLexicon({1: 120, 2: 80, 3: 30, 4: 5})
    counts = {1: 14, 2: 7, 3: 2, 4: 1}
    freqs_override = {1: 90, 2: 70, 3: 25, 4: 4}
    total_tokens_override = 4_000
    m = 23
    u = 180

    full = engine._calculate_statistics_arrays(
        counts,
        m,
        u,
        lexicon,
        freqs_override=freqs_override,
        total_tokens_override=total_tokens_override,
    )

    score_columns = {
        "f": 1,
        "mi": 3,
        "lmi": 4,
        "npmi": 5,
        "z": 6,
        "chi2_cell": 7,
        "t": 8,
        "ll": 9,
        "dice": 10,
    }

    for score_key, full_idx in score_columns.items():
        ids_sel, observed_sel, score_sel = engine._calculate_selected_statistics_arrays(
            counts,
            m,
            u,
            lexicon,
            score_key=score_key,
            freqs_override=freqs_override,
            total_tokens_override=total_tokens_override,
        )
        np.testing.assert_array_equal(ids_sel, full[0])
        np.testing.assert_allclose(observed_sel, full[1])
        np.testing.assert_allclose(score_sel, full[full_idx], rtol=1e-10, atol=1e-10)


def test_selected_score_array_handles_zero_observed_and_expected_without_runtime_warnings() -> None:
    observed = np.array([0.0, 2.0, 4.0, 0.0], dtype=np.float64)
    expected = np.array([0.0, 0.0, 2.0, 1.0], dtype=np.float64)
    event_mass = np.array([0.0, 3.0, 5.0, 7.0], dtype=np.float64)

    with np.errstate(all="raise"):
        for score_key in ("mi", "lmi", "npmi", "z", "chi2_cell", "t", "ll", "dice", "logdice"):
            scores = CollocationEngine._calculate_selected_score_array(
                observed,
                expected,
                event_mass,
                context_mass=10,
                event_total=100,
                score_key=score_key,
            )
            assert scores.shape == observed.shape
            assert np.all(np.isfinite(scores))


def _score(schluessel, **kw):
    return CollocationEngine._calculate_selected_score_array(
        np.array([2.0], dtype=np.float64),
        np.array([1.0], dtype=np.float64),
        np.array([8.0], dtype=np.float64),
        context_mass=20,
        event_total=120,
        score_key=schluessel,
        **kw,
    )


def test_logdice_window_rechnet_die_fensterformel() -> None:
    """14 + log2(2*O11/(R1+C1)) = 14 + log2(4/28) = 11,1926."""
    assert _score("logdice_window")[0] == pytest.approx(11.1926450779)


def test_logdice_rechnet_rychly_wenn_die_knotenfrequenz_vorliegt() -> None:
    """14 + log2(2*O11/(f(u)+f(v))) = 14 + log2(4/18) = 11,8301.

    Bis zum 2026-08-29 lieferte diese Funktion unter dem Schluessel
    "logdice" die FENSTERFORMEL an /analysis/contrast und
    /analysis/collocates_diff. Ein adversarialer Pruefer hat es
    nachgerechnet: fuer Knoten "der" im Testsplit stand 8,0564 in der
    Spalte, Rychlys Wert waere 10,8688 gewesen, ein Unterschied von 2,8
    Punkten auf einer Skala, auf der ein Punkt die doppelte Haeufigkeit bedeutet.
    """
    assert _score("logdice", node_frequency=10.0)[0] == pytest.approx(
        11.8300749986)
    # AUSDRUECKLICH NICHT die Fensterformel.
    assert _score("logdice", node_frequency=10.0)[0] != pytest.approx(
        11.1926450779)


def test_ohne_knotenfrequenz_liefert_logdice_keine_falsch_benannte_zahl() -> None:
    """Der Kern der Reparatur.

    Frueher fiel die Funktion ohne f(u) still auf die Fensterformel
    zurueck und lieferte sie unter Rychlys Namen. Eine FEHLENDE Zahl ist
    ehrlicher als eine falsch benannte: wer die Spalte liest, kann eine
    Null als "nicht berechenbar" erkennen, eine plausible falsche Zahl
    nicht.
    """
    ohne = _score("logdice")
    assert ohne[0] == 0.0, ohne[0]
    assert ohne[0] != pytest.approx(11.1926450779)
    # Die Fensterformel bleibt unter ihrem eigenen Namen erreichbar.
    assert _score("logdice_window")[0] == pytest.approx(11.1926450779)


def test_docset_collocate_stats_uses_document_boundaries_when_not_within_sentence(monkeypatch) -> None:
    engine = CollocationEngine.__new__(CollocationEngine)
    engine._loaded = True
    engine.token_store = SimpleNamespace(token_count=8)
    engine.boundaries = object()
    engine.index_path = SimpleNamespace(name='idx')
    engine._very_frequent_min = 1_000_000
    engine._very_frequent_ratio = 1.0

    lexicon = _StubLexicon({1: 2}, strings={1: 'term'})
    monkeypatch.setattr(engine, '_get_lexicon', lambda _attr: lexicon)
    monkeypatch.setattr(engine, '_resolve_term_id', lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        engine,
        '_get_term_positions',
        lambda *_args, **_kwargs: np.array([1], dtype=np.uint32),
    )
    monkeypatch.setattr(
        engine,
        '_filter_positions_by_docset',
        lambda positions, _mask: positions,
    )
    monkeypatch.setattr(
        engine,
        '_docset_word_counts_dense',
        lambda *_args, **_kwargs: (np.zeros(lexicon.vocab_size + 1, dtype=np.uint64), 2),
    )

    calls = []

    def fake_coverage_sweep_arrays(**kwargs):
        calls.append(kwargs)
        return (
            np.array([0], dtype=np.uint32),
            np.array([2], dtype=np.uint32),
            np.array([1], dtype=np.uint32),
        )

    monkeypatch.setattr(ce, 'coverage_sweep_arrays', fake_coverage_sweep_arrays)
    monkeypatch.setattr(ce, 'count_collocates', lambda *_args, **_kwargs: {})

    result = engine.collocate_stats(
        'term',
        window_left=3,
        window_right=3,
        within_sentence=False,
        docset_mask=np.array([True, False], dtype=bool),
        cache_mode='off',
    )

    assert result.empty
    assert calls
    assert calls[0]['boundaries'] is engine.boundaries
    assert calls[0]['within_sentence'] is False


def test_collocate_stats_top_n_scores_full_candidate_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CollocationEngine.__new__(CollocationEngine)
    lexicon = _StubLexicon({1: 5000, 2: 1}, {1: "common", 2: "rare"})
    engine._loaded = True
    engine.lexicons = SimpleNamespace(word=lexicon, lemma=lexicon, total_tokens=10_000)
    engine.boundaries = None
    engine._very_frequent_ratio = 1.0
    engine._very_frequent_min = 10_000
    engine.token_store = SimpleNamespace(
        token_count=10_000,
        get_positions_for_word_id=lambda _term_id: np.array([50], dtype=np.uint32),
    )

    seen_top_n: list[int | None] = []

    def fake_count_collocates(*_args, top_n=None, **_kwargs):
        seen_top_n.append(top_n)
        if top_n is not None:
            return {1: 1}
        return {1: 1, 2: 1}

    monkeypatch.setattr(ce, "count_collocates", fake_count_collocates)

    df = engine.collocate_stats(
        "node",
        window_left=1,
        window_right=1,
        top_n=1,
        term_id=99,
        cache_mode="off",
        # This test probes top_n/candidate-space + default ranking using O=1
        # collocates; disable the new min_count floor so they survive to ranking.
        min_count=1,
    )

    assert seen_top_n == [None]
    # Default ranking is now logDice (monotonic in dice): "rare" (freq 1) beats
    # "common" (freq 5000) because dice rewards exclusive association.
    assert df["word"].to_list() == ["rare"]


def test_count_collocates_top_n_hint_is_full_count_unless_frequency_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = np.array([0], dtype=np.uint32)
    ends = np.array([1], dtype=np.uint32)
    weights = np.array([1], dtype=np.uint32)
    calls: list[tuple[str, int | None]] = []

    def fake_full_count(*_args):
        calls.append(("full", None))
        return {1: 1, 2: 1}

    def fake_block_top(*_args):
        calls.append(("block", int(_args[-1])))
        return {1: 1}

    monkeypatch.setattr(ck, "count_hashmap_svb", fake_full_count)
    monkeypatch.setattr(ck, "_count_with_block_top", fake_block_top)

    assert ck.count_collocates(object(), starts, ends, weights, top_n=1) == {
        1: 1,
        2: 1,
    }
    assert calls == [("full", None)]

    calls.clear()
    assert ck.count_collocates(
        object(),
        starts,
        ends,
        weights,
        top_n=1,
        frequency_top_k=True,
    ) == {1: 1}
    assert calls == [("block", 1)]


def test_build_dual_basis_arrays_fast_aligns_union_and_frequencies() -> None:
    word_ids, obs_a, obs_b, freq_a, freq_b = build_dual_basis_arrays_fast(
        {7: 3, 2: 5},
        {3: 11, 7: 13},
        {2: 20, 3: 30, 7: 70},
        {3: 33, 7: 77},
    )

    np.testing.assert_array_equal(word_ids, np.array([2, 3, 7], dtype=np.uint32))
    np.testing.assert_allclose(obs_a, np.array([5.0, 0.0, 3.0]))
    np.testing.assert_allclose(obs_b, np.array([0.0, 11.0, 13.0]))
    np.testing.assert_allclose(freq_a, np.array([20.0, 30.0, 70.0]))
    np.testing.assert_allclose(freq_b, np.array([0.0, 33.0, 77.0]))


def test_calculate_statistics_arrays_accepts_dense_frequency_override() -> None:
    engine = _engine_with_total_tokens(10_000)
    lexicon = _StubLexicon({1: 120, 2: 80, 3: 30, 4: 5})
    counts = {1: 14, 2: 7, 3: 2, 4: 1}
    freqs_override = {1: 90, 2: 70, 3: 25, 4: 4}
    freqs_override_arr = np.zeros(8, dtype=np.uint64)
    for key, value in freqs_override.items():
        freqs_override_arr[key] = value

    by_dict = engine._calculate_statistics_arrays(
        counts,
        23,
        180,
        lexicon,
        freqs_override=freqs_override,
        total_tokens_override=4_000,
    )
    by_dense = engine._calculate_statistics_arrays(
        counts,
        23,
        180,
        lexicon,
        freqs_override_arr=freqs_override_arr,
        total_tokens_override=4_000,
    )

    for left, right in zip(by_dict, by_dense):
        np.testing.assert_allclose(left, right, rtol=1e-10, atol=1e-10)


def test_count_hashmap_svb_dual_dense_counts_both_segment_sets() -> None:
    token_store = _fake_token_store([1, 2, 3, 2, 4, 1, 3, 2])
    legacy_a, legacy_b = count_hashmap_svb_dual(
        token_store,
        "word",
        np.array([0, 4], dtype=np.uint32),
        np.array([3, 8], dtype=np.uint32),
        np.array([1, 1], dtype=np.uint32),
        np.array([2], dtype=np.uint32),
        np.array([6], dtype=np.uint32),
        np.array([1], dtype=np.uint32),
        {0},
    )
    word_ids, obs_a, obs_b = count_hashmap_svb_dual_dense(
        token_store,
        "word",
        np.array([0, 4], dtype=np.uint32),
        np.array([3, 8], dtype=np.uint32),
        np.array([1, 1], dtype=np.uint32),
        np.array([2], dtype=np.uint32),
        np.array([6], dtype=np.uint32),
        np.array([1], dtype=np.uint32),
        vocab_size=4,
        stoplist={0},
    )

    np.testing.assert_array_equal(word_ids, np.array([1, 2, 3, 4], dtype=np.uint32))
    np.testing.assert_allclose(obs_a, np.array([float(legacy_a.get(i, 0)) for i in word_ids]))
    np.testing.assert_allclose(obs_b, np.array([float(legacy_b.get(i, 0)) for i in word_ids]))


def test_count_hashmap_svb_dense_and_native_gather_match_expected_counts() -> None:
    token_store = _fake_token_store([1, 2, 3, 2, 4, 1, 3, 2])
    dense = count_hashmap_svb_dense(
        token_store,
        "word",
        np.array([0, 4], dtype=np.uint32),
        np.array([3, 8], dtype=np.uint32),
        np.array([1, 1], dtype=np.uint32),
        vocab_size=4,
        stoplist={0},
    )
    np.testing.assert_array_equal(dense[:5], np.array([0, 2, 2, 2, 1], dtype=np.uint64))
    gathered = gather_u64_to_f64_fast(dense, np.array([4, 1, 3], dtype=np.uint32))
    np.testing.assert_allclose(gathered, np.array([1.0, 2.0, 2.0]))


def test_subtract_and_compact_dual_counts_fast_removes_anchor_only_hits() -> None:
    union_ids = np.array([2, 3, 7, 11], dtype=np.uint32)
    counts_a = np.array([5, 1, 3, 2], dtype=np.uint64)
    counts_b = np.array([0, 4, 2, 1], dtype=np.uint64)
    anchor_ids = np.array([3, 11], dtype=np.uint32)
    anchor_a = np.array([1, 5], dtype=np.uint64)
    anchor_b = np.array([2, 1], dtype=np.uint64)

    out_ids, out_a, out_b = subtract_and_compact_dual_counts_fast(
        union_ids,
        counts_a,
        counts_b,
        anchor_ids,
        anchor_a,
        anchor_b,
    )

    np.testing.assert_array_equal(out_ids, np.array([2, 3, 7], dtype=np.uint32))
    np.testing.assert_array_equal(out_a, np.array([5, 0, 3], dtype=np.uint64))
    np.testing.assert_array_equal(out_b, np.array([0, 2, 2], dtype=np.uint64))


def test_dense_docset_cache_evicts_by_byte_budget() -> None:
    engine = _engine_with_dense_cache(max_bytes=48)
    first = (np.zeros(4, dtype=np.uint64), 10)
    second = (np.zeros(4, dtype=np.uint64), 20)

    engine._dense_cache_set("word:first", first)
    engine._dense_cache_set("word:second", second)

    assert engine._dense_cache_get("word:first") is None
    cached = engine._dense_cache_get("word:second")
    assert cached is not None
    np.testing.assert_array_equal(cached[0], second[0])
