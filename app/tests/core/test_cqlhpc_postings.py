import numpy as np
import pytest

import cqlhpc.engine as engine_mod
from cqlhpc.corpus import Corpus, build_postings_from_tokens, build_toy_corpus
from cqlhpc.config import clear_config, set_config
from cqlhpc.engine import (
    _CACHE_MISSING,
    QueryEngine,
    SearchOptions,
    _PreparedSentenceMatcher,
    _best_indexable_cached,
    _merge_expanded_sequence_candidates,
    _node_sentence_shift_key,
    _can_probe_finalize_sequence,
    _simple_indexable_from_node,
    _sent_filter_query_cache_key,
    _union_sentence_ids,
)
from cqlhpc.lexicon import Lexicon
from cqlhpc.normalize import normalize
from cqlhpc.parser import parse_cql
from cqlhpc.postings import (
    filter_positions_to_sentence_ids,
    filter_positions_by_bitset,
    filter_positions_by_bitset_no_bounds,
    intersect_sorted_unique,
    intersect_shifted,
    sentence_ids_for_min_shift_same_sentence,
    sentence_ids_for_positions,
    sentence_ids_for_shifted_range,
    union_positions_many,
)


def _build_repeated_boundary_corpus(repeats: int = 256) -> Corpus:
    words = ["und", "die", ".", "und", ".", "die", "."] * repeats
    pos = ["KON", "ART", "$.", "KON", "$.", "ART", "$."] * repeats
    lemma = list(words)

    def make_lex(vals):
        uniq = sorted(set(vals))
        str_to_id = {s: i for i, s in enumerate(uniq)}
        ids = np.asarray([str_to_id[v] for v in vals], dtype=np.int32)
        freqs = np.bincount(ids, minlength=len(uniq)).astype(np.int64)
        return Lexicon(id_to_str=uniq, str_to_id=str_to_id, freqs=freqs), ids

    lex_word, ids_word = make_lex(words)
    lex_pos, ids_pos = make_lex(pos)
    lex_lemma, ids_lemma = make_lex(lemma)

    attrs = {"word": ids_word, "pos": ids_pos, "lemma": ids_lemma}
    lex = {"word": lex_word, "pos": lex_pos, "lemma": lex_lemma}
    postings = {
        "word": build_postings_from_tokens(ids_word, len(lex_word.id_to_str)),
        "pos": build_postings_from_tokens(ids_pos, len(lex_pos.id_to_str)),
        "lemma": build_postings_from_tokens(ids_lemma, len(lex_lemma.id_to_str)),
    }
    sent_starts = np.asarray([i for i, w in enumerate(words) if i == 0 or words[i - 1] == "."], dtype=np.int32)
    sent_ends = np.asarray([i + 1 for i, w in enumerate(words) if w == "."], dtype=np.int32)

    return Corpus(
        attrs=attrs,
        lex=lex,
        postings=postings,
        doc_starts=np.asarray([0], dtype=np.int32),
        doc_ends=np.asarray([len(words)], dtype=np.int32),
        sent_starts=sent_starts,
        sent_ends=sent_ends,
        doc_meta=[{"genre": "toy"}],
    )


def test_corpus_doc_id_of_position_uses_cached_token_to_doc() -> None:
    corpus = build_toy_corpus()
    token_to_doc = corpus.token_to_doc()
    assert token_to_doc.shape[0] == corpus.n_tokens

    assert corpus.doc_id_of_position(0) == 0
    assert corpus.doc_id_of_position(corpus.n_tokens - 1) == 0


def test_corpus_sent_to_doc_uses_existing_token_cache() -> None:
    corpus = build_toy_corpus()
    corpus.token_to_doc()

    sent_to_doc = corpus.sent_to_doc()

    np.testing.assert_array_equal(
        sent_to_doc,
        np.zeros(corpus.sent_starts.shape[0], dtype=np.int32),
    )


def test_intersect_sorted_unique_matches_numpy_on_balanced_inputs() -> None:
    a = np.array([1, 3, 5, 7, 9, 11], dtype=np.int32)
    b = np.array([0, 3, 4, 7, 10, 11], dtype=np.int32)

    out = intersect_sorted_unique(a, b)

    np.testing.assert_array_equal(out, np.array([3, 7, 11], dtype=np.int32))


def test_intersect_sorted_unique_matches_numpy_on_skewed_inputs() -> None:
    a = np.arange(0, 1_000, 97, dtype=np.int32)
    b = np.arange(0, 200_000, 3, dtype=np.int32)

    out = intersect_sorted_unique(a, b)
    expected = np.intersect1d(a, b, assume_unique=True).astype(np.int32, copy=False)

    np.testing.assert_array_equal(out, expected)


def test_filter_positions_by_bitset_no_bounds_matches_checked_variant() -> None:
    anchor = np.array([3, 5, 8, 10, 13], dtype=np.int32)
    n_tokens = 32
    bitset = np.zeros(((n_tokens + 7) >> 3,), dtype=np.uint8)
    for pos in (4, 6, 9, 14):
        bitset[pos >> 3] |= np.uint8(1 << (pos & 7))

    checked = filter_positions_by_bitset(anchor, bitset, 1, n_tokens)
    unchecked = filter_positions_by_bitset_no_bounds(anchor, bitset, 1)

    np.testing.assert_array_equal(unchecked, checked)


def test_sentence_ids_for_shifted_range_matches_legacy_shift_loop() -> None:
    anchor = np.array([1, 6, 10, 14], dtype=np.int32)
    other = np.array([3, 8, 11, 16], dtype=np.int32)
    sent_ends = np.array([5, 12, 20], dtype=np.int32)

    fast = sentence_ids_for_shifted_range(anchor, other, 1, 2, sent_ends)

    hits = []
    for shift in range(1, 3):
        arr = intersect_shifted(anchor, other, shift)
        if arr.size:
            hits.append(arr)
    legacy = sentence_ids_for_positions(union_positions_many(hits), sent_ends)

    np.testing.assert_array_equal(fast, legacy)


def test_sentence_ids_for_shifted_range_matches_legacy_when_right_side_is_smaller() -> None:
    anchor = np.array([1, 2, 6, 7, 10, 14, 18], dtype=np.int32)
    other = np.array([3, 8, 16], dtype=np.int32)
    sent_ends = np.array([5, 12, 20], dtype=np.int32)

    fast = sentence_ids_for_shifted_range(anchor, other, 1, 2, sent_ends)

    hits = []
    for shift in range(1, 3):
        arr = intersect_shifted(anchor, other, shift)
        if arr.size:
            hits.append(arr)
    legacy = sentence_ids_for_positions(union_positions_many(hits), sent_ends)

    np.testing.assert_array_equal(fast, legacy)


def test_sentence_ids_for_min_shift_same_sentence_matches_expected_pairs() -> None:
    anchor = np.array([1, 6, 10, 14], dtype=np.int32)
    other = np.array([3, 8, 11, 16], dtype=np.int32)
    sent_ends = np.array([5, 12, 20], dtype=np.int32)

    out = sentence_ids_for_min_shift_same_sentence(anchor, other, 2, sent_ends)

    np.testing.assert_array_equal(out, np.array([0, 1, 2], dtype=np.int32))


def test_filter_positions_to_sentence_ids_matches_legacy_searchsorted_path() -> None:
    positions = np.array([1, 3, 4, 6, 7, 10, 11, 14, 18], dtype=np.int32)
    sent_ids = np.array([0, 2, 4], dtype=np.int32)
    sent_starts = np.array([0, 5, 10, 15, 18], dtype=np.int32)
    sent_ends = np.array([5, 10, 15, 18, 22], dtype=np.int32)

    fast = filter_positions_to_sentence_ids(positions, sent_ids, sent_starts, sent_ends)

    starts = sent_starts[sent_ids]
    ends = sent_ends[sent_ids]
    lo = np.searchsorted(positions, starts, side="left")
    hi = np.searchsorted(positions, ends, side="left")
    parts = [positions[a:b] for a, b in zip(lo.tolist(), hi.tolist()) if b > a]
    legacy = np.concatenate(parts).astype(np.int32, copy=False) if parts else np.empty((0,), dtype=np.int32)

    np.testing.assert_array_equal(fast, legacy)


def test_simple_indexable_from_node_matches_cached_best_for_single_exact_clause() -> None:
    corpus = build_toy_corpus()
    node = normalize(parse_cql('[word="gehst"]'))

    simple = _simple_indexable_from_node(
        node,
        corpus,
        progress_cb=None,
        compiled_cache={},
        indexable_cache={},
    )
    best = _best_indexable_cached(
        node.clause,
        corpus,
        progress_cb=None,
        indexable_cache={},
    )

    assert simple is not None
    assert best is not None
    attr, tids, est = simple
    assert attr == best.attr
    np.testing.assert_array_equal(tids, best.type_ids)
    assert est == best.est_len


def test_simple_indexable_from_node_single_exact_clause_skips_compile_clause(monkeypatch) -> None:
    corpus = build_toy_corpus()
    node = normalize(parse_cql('[word="gehst"]'))

    def _boom(*args, **kwargs):
        raise AssertionError("compile_clause should not run for simple exact token clauses")

    monkeypatch.setattr(engine_mod, "compile_clause", _boom)

    simple = _simple_indexable_from_node(
        node,
        corpus,
        progress_cb=None,
        compiled_cache={},
        indexable_cache={},
    )

    assert simple is not None
    assert simple[0] == "word"


def test_simple_indexable_from_node_single_regex_clause_skips_compile_clause(monkeypatch) -> None:
    corpus = build_toy_corpus()
    node = normalize(parse_cql('[word~"^geh.*"]'))

    def _boom(*args, **kwargs):
        raise AssertionError("compile_clause should not run for simple regex token clauses")

    def _fake_value_to_type_ids(cond, corpus, *, progress_cb=None):
        assert cond.op == "~"
        return np.asarray([5, 6, 7], dtype=np.int32)

    monkeypatch.setattr(engine_mod, "compile_clause", _boom)
    monkeypatch.setattr(engine_mod, "_value_to_type_ids", _fake_value_to_type_ids)

    simple = _simple_indexable_from_node(
        node,
        corpus,
        progress_cb=None,
        compiled_cache={},
        indexable_cache={},
    )

    assert simple is not None
    assert simple[0] == "word"


class _FakeUnitIndex:
    def __init__(self, mapping: dict[int, np.ndarray]) -> None:
        self._mapping = mapping

    def ids_for(self, type_id: int) -> np.ndarray:
        return self._mapping.get(type_id, np.zeros(0, dtype=np.uint32))


class _SliceAccessor:
    def __init__(self, arr: np.ndarray) -> None:
        self._arr = arr

    def __getitem__(self, key):
        return self._arr[key]


class _PackedSliceAccessor(_SliceAccessor):
    def get_ranges_packed_i32(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts_i32 = np.ascontiguousarray(starts, dtype=np.int32)
        ends_i32 = np.ascontiguousarray(ends, dtype=np.int32)
        total = 0
        for start, end in zip(starts_i32.tolist(), ends_i32.tolist()):
            start = max(0, int(start))
            end = min(int(end), self._arr.shape[0])
            if end > start:
                total += end - start
        out = np.empty(total, dtype=np.int32)
        cursor = 0
        for start, end in zip(starts_i32.tolist(), ends_i32.tolist()):
            start = max(0, int(start))
            end = min(int(end), self._arr.shape[0])
            if end <= start:
                continue
            take = end - start
            out[cursor : cursor + take] = self._arr[start:end].astype(np.int32, copy=False)
            cursor += take
        return out


class _WrappedToyCorpus:
    def __init__(self, base) -> None:
        self._base = base
        self.doc_starts = base.doc_starts
        self.doc_ends = base.doc_ends
        self.sent_starts = base.sent_starts
        self.sent_ends = base.sent_ends
        self.n_tokens = base.n_tokens

    def has_attr(self, name: str) -> bool:
        return self._base.has_attr(name)

    def attr(self, name: str):
        return _SliceAccessor(self._base.attr(name))

    def lexicon(self, name: str):
        return self._base.lexicon(name)

    def postings_index(self, attr: str):
        return self._base.postings_index(attr)

    def pos_sentence_index(self):
        return None

    def sentence_span(self, sid: int):
        return self._base.sentence_span(sid)

    def doc_span(self, did: int):
        return self._base.doc_span(did)

    def doc_id_of_position(self, pos: int) -> int:
        return self._base.doc_id_of_position(pos)

    def sent_to_doc(self) -> np.ndarray:
        return self._base.sent_to_doc()

    def token_to_doc(self) -> np.ndarray:
        return self._base.token_to_doc()

    def token_to_sent(self) -> np.ndarray:
        return self._base.token_to_sent()


class _PackedWrappedToyCorpus(_WrappedToyCorpus):
    def attr(self, name: str):
        return _PackedSliceAccessor(self._base.attr(name))


class _NoSentToDocWrappedToyCorpus(_WrappedToyCorpus):
    def sent_to_doc(self) -> np.ndarray:
        raise AssertionError("search_arrays should not materialize sent_to_doc here")


def test_union_sentence_ids_matches_numpy_union_for_multiple_ids() -> None:
    idx = _FakeUnitIndex(
        {
            1: np.array([1, 3, 7, 9], dtype=np.uint32),
            2: np.array([2, 3, 8, 10], dtype=np.uint32),
            3: np.array([1, 4, 8, 12], dtype=np.uint32),
        }
    )

    out = _union_sentence_ids(idx, [1, 2, 3])
    expected = np.unique(
        np.concatenate(
            [
                idx.ids_for(1),
                idx.ids_for(2),
                idx.ids_for(3),
            ]
        )
    ).astype(np.int32, copy=False)

    np.testing.assert_array_equal(out, expected)


def test_query_engine_hybrid_search_and_count_still_work() -> None:
    engine = QueryEngine(build_toy_corpus())

    matches = engine.search('[lemma="gehen"] [pos="APPR"]')
    count = engine.count('[lemma="gehen"] [pos="APPR"]')

    assert count == 2
    assert len(matches) == 2
    assert [(m.start, m.end) for m in matches] == [(1, 3), (6, 8)]


def test_query_engine_rejects_branch_local_where_in_release_mode() -> None:
    engine = QueryEngine(build_toy_corpus())

    with pytest.raises(RuntimeError, match="Branch-lokales where"):
        engine.search('where(genre="toy", [word="gehe"]) | where(genre="other", [word="gehst"])')


def test_query_engine_count_result_marks_capped_counts_partial() -> None:
    engine = QueryEngine(build_toy_corpus())

    result = engine.count_result('[lemma="gehen"]', SearchOptions(max_matches=2))

    assert result.total == 2
    assert result.partial is True
    assert result.limit == 2


def test_query_engine_count_result_treats_exact_limit_as_exact() -> None:
    engine = QueryEngine(build_toy_corpus())

    result = engine.count_result('[lemma="gehen"]', SearchOptions(max_matches=4))

    assert result.total == 4
    assert result.partial is False
    assert result.limit == 4


def test_query_engine_hybrid_search_and_count_work_with_slice_accessors() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))

    matches = engine.search('[lemma="gehen"] [pos="APPR"]')
    count = engine.count('[lemma="gehen"] [pos="APPR"]')

    assert count == 2
    assert len(matches) == 2
    assert [(m.start, m.end) for m in matches] == [(1, 3), (6, 8)]


def test_query_engine_hybrid_multi_cond_clause_works_with_slice_accessors() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))

    matches = engine.search('[lemma="gehen" & pos="VVFIN"] [word="nach"]')
    count = engine.count('[lemma="gehen" & pos="VVFIN"] [word="nach"]')

    assert count == 2
    assert len(matches) == 2
    assert [(m.start, m.end) for m in matches] == [(1, 3), (6, 8)]


def test_query_engine_hybrid_triple_cond_clause_works_with_slice_accessors() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))

    matches = engine.search('[lemma="gehen" & pos="VVFIN" & word="gehst"] [word="nach"]')
    count = engine.count('[lemma="gehen" & pos="VVFIN" & word="gehst"] [word="nach"]')

    assert count == 1
    assert len(matches) == 1
    assert [(m.start, m.end) for m in matches] == [(6, 8)]



def test_query_engine_hybrid_optional_alt_clause_still_matches() -> None:
    engine = QueryEngine(build_toy_corpus())

    matches = engine.search('[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]')
    count = engine.count('[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]')

    assert count == 1
    assert len(matches) == 1
    assert [(m.start, m.end) for m in matches] == [(6, 9)]


def test_query_engine_hybrid_word_only_optional_alt_works_with_slice_accessors() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))

    matches = engine.search('[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]')
    count = engine.count('[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]')

    assert count == 1
    assert len(matches) == 1
    assert [(m.start, m.end) for m in matches] == [(6, 9)]


def test_query_engine_hybrid_search_profile_matches_search_for_optional_alt() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))
    query = '[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'

    matches = engine.search(query)
    profiled, timings = engine.search_profile(query)

    assert [(m.start, m.end, m.sentence_id, m.doc_id) for m in profiled] == [
        (m.start, m.end, m.sentence_id, m.doc_id) for m in matches
    ]
    assert timings["exec"] >= 0.0
    assert timings["total"] >= timings["exec"]


def test_query_engine_search_arrays_matches_search_for_sequence() -> None:
    engine = QueryEngine(build_toy_corpus())
    query = '[lemma="gehen"] [pos="APPR"]'

    matches = engine.search(query)
    starts, ends = engine.search_arrays(query)

    assert [(m.start, m.end) for m in matches] == list(zip(starts.tolist(), ends.tolist()))


def test_query_engine_search_arrays_sequence_avoids_sent_to_doc_materialization() -> None:
    engine = QueryEngine(_NoSentToDocWrappedToyCorpus(build_toy_corpus()))

    starts, ends = engine.search_arrays('[lemma="gehen"] [pos="APPR"]')

    np.testing.assert_array_equal(starts, np.array([1, 6], dtype=np.uint32))
    np.testing.assert_array_equal(ends, np.array([3, 8], dtype=np.uint32))


def test_query_engine_search_arrays_unbounded_repeat_avoids_sent_to_doc_materialization() -> None:
    query = 'within(<s>, [word="du"]+ [word="gehst"])'
    reference_engine = QueryEngine(build_toy_corpus())
    expected_starts, expected_ends = reference_engine.search_arrays(query)

    engine = QueryEngine(_NoSentToDocWrappedToyCorpus(build_toy_corpus()))
    starts, ends = engine.search_arrays(query)

    np.testing.assert_array_equal(starts, expected_starts)
    np.testing.assert_array_equal(ends, expected_ends)


def test_query_engine_search_arrays_bounded_repeat_avoids_sent_to_doc_materialization() -> None:
    query = '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,3} [word="berlin"]'
    reference_engine = QueryEngine(build_toy_corpus())
    expected_starts, expected_ends = reference_engine.search_arrays(query)

    engine = QueryEngine(_NoSentToDocWrappedToyCorpus(build_toy_corpus()))
    starts, ends = engine.search_arrays(query)

    np.testing.assert_array_equal(starts, expected_starts)
    np.testing.assert_array_equal(ends, expected_ends)


def test_query_engine_search_arrays_finalize_probe_matches_baseline_with_boundary_fallback() -> None:
    corpus = _build_repeated_boundary_corpus()
    query = '[word="und"] [word="die"]'
    opts = SearchOptions(max_matches=20)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_FINALIZE_PROBE_EXTRA": 0})
    reference_engine = QueryEngine(corpus)
    expected_starts, expected_ends = reference_engine.search_arrays(query, opts)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_FINALIZE_PROBE_EXTRA": 1})
    engine = QueryEngine(corpus)
    starts, ends = engine.search_arrays(query, opts)

    np.testing.assert_array_equal(starts, expected_starts)
    np.testing.assert_array_equal(ends, expected_ends)
    clear_config()


def test_finalize_probe_only_applies_to_small_exact_sequences() -> None:
    exact = normalize(parse_cql('[word="und"] [word="die"]'))
    regex = normalize(parse_cql('[word~"^un.*"] [word="ist"]'))
    wide = normalize(parse_cql('[word="und"] ([word="der"]|[word="die"]){0,30} [word="ist"]'))

    assert _can_probe_finalize_sequence(list(exact.parts))
    assert not _can_probe_finalize_sequence(list(regex.parts))
    assert not _can_probe_finalize_sequence(list(wide.parts))


def test_query_engine_search_arrays_matches_search_for_hybrid() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))
    query = '[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'

    matches = engine.search(query)
    starts, ends = engine.search_arrays(query)

    assert [(m.start, m.end) for m in matches] == list(zip(starts.tolist(), ends.tolist()))


def test_hybrid_sentence_filter_ids_prefilter_mandatory_parts_only() -> None:
    engine = QueryEngine(build_toy_corpus())
    ast = normalize(parse_cql('[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'))
    inner, _ = engine._unwrap_scopes(ast)

    sent_ids = engine._hybrid_sentence_filter_ids(
        '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]',
        inner,
        SearchOptions(),
    )

    np.testing.assert_array_equal(sent_ids, np.array([1], dtype=np.int32))


def test_hybrid_sentence_filter_ids_handles_unbounded_middle_by_endpoint_order() -> None:
    engine = QueryEngine(build_toy_corpus())
    q = 'within(<s>, [word="du"] ([word="gehst"]|[word="nach"])+ [word="berlin"])'
    ast = normalize(parse_cql(q))
    inner, _ = engine._unwrap_scopes(ast)

    sent_ids = engine._hybrid_sentence_filter_ids(q, inner, SearchOptions())

    np.testing.assert_array_equal(sent_ids, np.array([1], dtype=np.int32))


def test_hybrid_sentence_filter_ids_handles_mandatory_quantified_endpoint() -> None:
    engine = QueryEngine(build_toy_corpus())
    q = 'within(<s>, [word="du"]+ [word="gehst"])'
    ast = normalize(parse_cql(q))
    inner, _ = engine._unwrap_scopes(ast)

    sent_ids = engine._hybrid_sentence_filter_ids(q, inner, SearchOptions())

    np.testing.assert_array_equal(sent_ids, np.array([1], dtype=np.int32))


def test_hybrid_sentence_filter_subtree_cache_reuses_structural_subtrees() -> None:
    engine = QueryEngine(build_toy_corpus())
    q1 = '[lemma="gehen"] ([word="heute"]|[word="berlin"]) [word="nicht"]'
    q2 = '[word="wir"] ([word="heute"]|[word="berlin"]) [pos="PTKNEG"]'

    ast1 = normalize(parse_cql(q1))
    inner1, _ = engine._unwrap_scopes(ast1)
    engine._hybrid_sentence_filter_ids(q1, inner1, SearchOptions())

    ast2 = normalize(parse_cql(q2))
    inner2, _ = engine._unwrap_scopes(ast2)
    shared_subtree = inner2.parts[1]

    cached = engine._sent_filter_node_cache.get(shared_subtree)
    assert cached is not _CACHE_MISSING
    np.testing.assert_array_equal(cached, np.array([1, 2], dtype=np.int32))


def test_hybrid_sentence_filter_shift_cache_reuses_same_endpoints() -> None:
    engine = QueryEngine(build_toy_corpus())
    q1 = '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'
    q2 = '[lemma="gehen"] ([word="gestern"]|[word="morgen"]){0,1} [word="berlin"]'

    ast1 = normalize(parse_cql(q1))
    inner1, _ = engine._unwrap_scopes(ast1)
    engine._hybrid_sentence_filter_ids(q1, inner1, SearchOptions())

    ast2 = normalize(parse_cql(q2))
    inner2, _ = engine._unwrap_scopes(ast2)
    engine._hybrid_sentence_filter_ids(q2, inner2, SearchOptions())
    assert engine._sent_filter_cache.get(_sent_filter_query_cache_key(q1)) is not _CACHE_MISSING
    assert engine._sent_filter_cache.get(_sent_filter_query_cache_key(q2)) is not _CACHE_MISSING


def test_query_engines_share_clause_and_shift_caches_on_same_corpus() -> None:
    corpus = build_toy_corpus()
    engine1 = QueryEngine(corpus)
    q1 = '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'
    ast1 = normalize(parse_cql(q1))
    inner1, _ = engine1._unwrap_scopes(ast1)
    engine1._hybrid_sentence_filter_ids(q1, inner1, SearchOptions())

    engine2 = QueryEngine(corpus)
    assert engine2._shift_sentence_ids_cache is engine1._shift_sentence_ids_cache
    assert engine2._clause_positions_cache is engine1._clause_positions_cache
    assert engine2._clause_sentence_ids_cache is engine1._clause_sentence_ids_cache

    assert engine2._parse_cache is engine1._parse_cache
    assert engine2._nfa_cache is engine1._nfa_cache
    assert engine2._docset_cache is engine1._docset_cache
    assert engine2._sent_filter_cache is engine1._sent_filter_cache
    assert engine2._compiled_clause_cache is engine1._compiled_clause_cache
    assert engine2._indexable_cache is engine1._indexable_cache
    assert engine2._sent_filter_cache.get(_sent_filter_query_cache_key(q1)) is not _CACHE_MISSING


def test_bounded_repeat_fastpath_matches_hybrid_reference_results() -> None:
    corpus = build_toy_corpus()
    query = '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,3} [word="berlin"]'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH": 0})
    reference = QueryEngine(corpus).search(query, opts)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH": 1})
    fast = QueryEngine(corpus).search(query, opts)

    assert fast == reference
    clear_config()


def test_bounded_repeat_fastpath_matches_multi_attr_reference_results() -> None:
    corpus = build_toy_corpus()
    query = '[word="gehen" & lemma="gehen"] ([word="nach"]|[word="heute"]){0,3} [word="berlin"]'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH": 0})
    reference = QueryEngine(corpus).search(query, opts)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH": 1})
    fast = QueryEngine(corpus).search(query, opts)

    assert fast == reference
    clear_config()


def test_bounded_repeat_fastpath_search_arrays_matches_search() -> None:
    corpus = build_toy_corpus()
    query = '[lemma="gehen"] ([word="nach"]|[word="heute"]){0,3} [word="berlin"]'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH": 1})
    engine = QueryEngine(corpus)
    matches = engine.search(query, opts)
    starts, ends = engine.search_arrays(query, opts)

    assert [(m.start, m.end) for m in matches] == list(zip(starts.tolist(), ends.tolist()))
    clear_config()


def test_unbounded_repeat_fastpath_matches_hybrid_reference_results() -> None:
    corpus = build_toy_corpus()
    query = 'within(<s>, [word="du"]+ [word="gehst"])'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH": 0})
    reference = QueryEngine(corpus).search(query, opts)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH": 1})
    fast = QueryEngine(corpus).search(query, opts)

    assert fast == reference
    clear_config()


def test_unbounded_repeat_fastpath_search_arrays_matches_search() -> None:
    corpus = build_toy_corpus()
    query = 'within(<s>, [word="du"]+ [word="gehst"])'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH": 1})
    engine = QueryEngine(corpus)
    matches = engine.search(query, opts)
    starts, ends = engine.search_arrays(query, opts)

    assert [(m.start, m.end) for m in matches] == list(zip(starts.tolist(), ends.tolist()))
    clear_config()


def test_unbounded_repeat_fastpath_matches_multi_attr_reference_results() -> None:
    corpus = build_toy_corpus()
    query = 'within(<s>, [word="du" & lemma="du"]+ [word="gehst"])'
    opts = SearchOptions(max_matches=1000)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH": 0})
    reference = QueryEngine(corpus).search(query, opts)

    clear_config()
    set_config({"CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH": 1})
    fast = QueryEngine(corpus).search(query, opts)

    assert fast == reference
    clear_config()


def test_prepared_sentence_matcher_batch_iterator_matches_per_index_results() -> None:
    engine = QueryEngine(_WrappedToyCorpus(build_toy_corpus()))
    query = '[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'
    ast = normalize(parse_cql(query))
    inner, _ = engine._unwrap_scopes(ast)
    cand_sids = engine._anchor_sentence_ids(query, inner, SearchOptions())
    nfa = engine._get_nfa(query, inner, SearchOptions())
    matcher = _PreparedSentenceMatcher(nfa, engine.corpus, cand_sids)

    per_index = [matcher.spans_for_index(i, 100) for i in range(len(matcher))]
    batched = list(matcher.iter_sentence_spans(100))

    assert batched == per_index


def test_prepared_sentence_matcher_packed_batches_match_per_index_results() -> None:
    clear_config()
    set_config(
        {
            "CANDYCONC_CQLHPC_VERIFY_PACKED_BATCHES": 1,
            "CANDYCONC_CQLHPC_VERIFY_PACKED_GAP_RATIO": 1.0,
            "CANDYCONC_CQLHPC_VERIFY_PACKED_MIN_SENTS": 1,
            "CANDYCONC_CQLHPC_VERIFY_BATCH_SENTS": 16,
            "CANDYCONC_CQLHPC_VERIFY_BATCH_TOKENS": 64,
        }
    )
    try:
        engine = QueryEngine(_PackedWrappedToyCorpus(build_toy_corpus()))
        query = '[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'
        ast = normalize(parse_cql(query))
        inner, _ = engine._unwrap_scopes(ast)
        cand_sids = np.arange(engine.corpus.sent_starts.shape[0], dtype=np.int32)
        nfa = engine._get_nfa(query, inner, SearchOptions())
        matcher = _PreparedSentenceMatcher(nfa, engine.corpus, cand_sids)

        matcher._ensure_batch(0)
        assert matcher._batch_deltas is not None

        per_index = [matcher.spans_for_index(i, 100) for i in range(len(matcher))]
        batched = list(matcher.iter_sentence_spans(100))

        assert batched == per_index
    finally:
        clear_config()


def test_prepared_sentence_matcher_packed_batches_repeat_stably_with_cache() -> None:
    clear_config()
    set_config(
        {
            "CANDYCONC_CQLHPC_VERIFY_PACKED_BATCHES": 1,
            "CANDYCONC_CQLHPC_VERIFY_PACKED_GAP_RATIO": 1.0,
            "CANDYCONC_CQLHPC_VERIFY_PACKED_MIN_SENTS": 1,
            "CANDYCONC_CQLHPC_VERIFY_BATCH_SENTS": 16,
            "CANDYCONC_CQLHPC_VERIFY_BATCH_TOKENS": 64,
            "CANDYCONC_PACKED_RANGE_CACHE_MAX_BYTES": 1048576,
            "CANDYCONC_PACKED_RANGE_CACHE_MIN_BYTES": 1,
        }
    )
    try:
        engine = QueryEngine(_PackedWrappedToyCorpus(build_toy_corpus()))
        query = '[word="gehst"] ([word="nach"]|[word="heute"]){0,1} [word="berlin"]'

        first = [(m.start, m.end) for m in engine.search(query)]
        second = [(m.start, m.end) for m in engine.search(query)]

        assert second == first
    finally:
        clear_config()


def test_merge_expanded_sequence_candidates_keeps_leftmost_longest() -> None:
    candidates = [
        (
            np.array([0, 4], dtype=np.int32),
            np.array([2, 6], dtype=np.int32),
            np.array([0, 0], dtype=np.int32),
            np.array([0, 0], dtype=np.int32),
        ),
        (
            np.array([0], dtype=np.int32),
            np.array([3], dtype=np.int32),
            np.array([0], dtype=np.int32),
            np.array([0], dtype=np.int32),
        ),
    ]

    out = _merge_expanded_sequence_candidates(candidates, "s", 10)

    assert [(m.start, m.end, m.sentence_id) for m in out] == [(0, 3, 0), (4, 6, 0)]
