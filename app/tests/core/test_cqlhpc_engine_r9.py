"""Golden tests for the r9 CQLHPC engine fixes (track DT-CQLHPC-ENGINE).

Two confirmed query-correctness bugs, each proved against an independently
computed brute-force / positions reference:

1. **Bounded-repeat gap query with a wildcard ``[]`` endpoint silently returned
   0 matches.** ``[word="X"] []{1,3} []`` (or any bounded-repeat whose left,
   middle or right operand is the any-token ``[]``) wrongly yielded zero. Root
   cause: the bounded-repeat postings fast paths model each operand by its
   concrete positions / a dense bitset; an empty ``[]`` clause resolves to
   ``None`` from ``_simple_indexable_from_node`` and then to an *all-zeros*
   bitset, collapsing the whole match to nothing. The fix defers any pattern
   with a ``[]`` operand to the hybrid NFA path (zero-condition predicate is
   universally true). See ``_extract_bounded_repeat_pattern``.

2. **``within(<doc>)`` scope was broken** — it ran the NFA matcher per *sentence*
   and merely clamped span ends to the document end, so it returned a strict
   *subset* of ``within(<s>)`` and never matched a span crossing a sentence
   boundary inside one document. The fix runs the matcher over whole-document
   segments (``corpus.doc_starts/doc_ends``) for doc scope, in ``search_arrays``,
   ``_search_hybrid_iter`` and ``_count_hybrid``. Golden: a two-token sequence
   that spans a sentence boundary within one document matches under
   ``within(<doc>)`` but NOT under ``within(<s>)``; and ``within(<doc>)`` is a
   superset of ``within(<s>)`` for every query, with ``count == search``.

The bounded-gap golden's brute-force reference uses CQP/CWB *non-overlapping
leftmost-longest* semantics, matching the engine's
``find_nonoverlapping_matches``.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pytest

from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.engine import QueryEngine, SearchOptions
from cqlhpc.lexicon import Lexicon


# --------------------------------------------------------------------------- #
# In-memory corpus builder (deterministic; no dependency on the bench index    #
# data-model, whose sentence/document boundaries are not nested — that is a     #
# separate build-pipeline defect, DT-BUILD-INDEX).                             #
# --------------------------------------------------------------------------- #
def _make_lex(vals) -> Tuple[Lexicon, np.ndarray]:
    uniq = sorted(set(vals))
    str_to_id = {s: i for i, s in enumerate(uniq)}
    ids = np.asarray([str_to_id[v] for v in vals], dtype=np.int32)
    freqs = np.bincount(ids, minlength=len(uniq)).astype(np.int64)
    return Lexicon(id_to_str=uniq, str_to_id=str_to_id, freqs=freqs), ids


def _build_corpus(
    words: List[str],
    pos: List[str],
    sent_starts: List[int],
    sent_ends: List[int],
    doc_starts: List[int],
    doc_ends: List[int],
) -> Corpus:
    lex_word, ids_word = _make_lex(words)
    lex_pos, ids_pos = _make_lex(pos)
    return Corpus(
        attrs={"word": ids_word, "pos": ids_pos},
        lex={"word": lex_word, "pos": lex_pos},
        postings={
            "word": build_postings_from_tokens(ids_word, len(lex_word.id_to_str)),
            "pos": build_postings_from_tokens(ids_pos, len(lex_pos.id_to_str)),
        },
        doc_starts=np.asarray(doc_starts, dtype=np.int32),
        doc_ends=np.asarray(doc_ends, dtype=np.int32),
        sent_starts=np.asarray(sent_starts, dtype=np.int32),
        sent_ends=np.asarray(sent_ends, dtype=np.int32),
    )


def test_external_docset_mask_filters_before_match_limit() -> None:
    corpus = _build_corpus(
        ["x", ".", "x", "."],
        ["NOUN", "PUNCT", "NOUN", "PUNCT"],
        [0, 2],
        [2, 4],
        [0, 2],
        [2, 4],
    )
    engine = QueryEngine(corpus)

    starts, ends = engine.search_arrays(
        '[word="x"]',
        SearchOptions(max_matches=1, docset_mask=np.asarray([False, True], dtype=np.bool_)),
    )

    np.testing.assert_array_equal(starts, np.asarray([2], dtype=np.uint32))
    np.testing.assert_array_equal(ends, np.asarray([3], dtype=np.uint32))


def _build_random_nested_corpus(seed: int = 13, n_docs: int = 80) -> Corpus:
    """A corpus whose sentences are *properly nested* inside documents.

    Each document holds 1-4 sentences; each sentence is 2-6 content tokens plus a
    closing ``.``. This is the corrected fixture the within(<doc>) superset
    invariant requires (the bench index violates nesting; see DT-BUILD-INDEX).
    """
    rng = random.Random(seed)
    content = ["der", "die", "und", "Idee", "geht", "gehen", "Haus", "rot"]
    posmap = {
        "der": "DET", "die": "DET", "und": "CCONJ", "Idee": "NOUN",
        "geht": "VERB", "gehen": "VERB", "Haus": "NOUN", "rot": "ADJ", ".": "PUNCT",
    }
    words: List[str] = []
    pos: List[str] = []
    sent_starts: List[int] = []
    sent_ends: List[int] = []
    doc_starts: List[int] = []
    doc_ends: List[int] = []
    i = 0
    for _ in range(n_docs):
        doc_starts.append(i)
        for _s in range(rng.randint(1, 4)):
            sent_starts.append(i)
            for _ in range(rng.randint(2, 6)):
                w = rng.choice(content)
                words.append(w)
                pos.append(posmap[w])
                i += 1
            words.append(".")
            pos.append("PUNCT")
            i += 1
            sent_ends.append(i)
        doc_ends.append(i)
    return _build_corpus(words, pos, sent_starts, sent_ends, doc_starts, doc_ends)


def _spans(eng: QueryEngine, query: str, max_matches: int = 10_000_000):
    opt = SearchOptions(max_matches=max_matches)
    return sorted((int(m.start), int(m.end)) for m in eng.search(query, opt))


# --------------------------------------------------------------------------- #
# Bug 1: bounded-repeat gap query with a wildcard [] endpoint                  #
# --------------------------------------------------------------------------- #
def _engine_term_positions(eng: QueryEngine, attr: str, value: str) -> List[int]:
    """Start positions of a single-token query, via the engine itself.

    Works for both the in-memory ``Corpus`` and the bench ``FastCorpus`` (whose
    lexicon adapter exposes no ``str_to_id``). A single ``[attr="value"]`` match
    is one token wide, so ``start`` is the token position.
    """
    opt = SearchOptions(max_matches=10_000_000)
    return sorted(int(m.start) for m in eng.search(f'[{attr}="{value}"]', opt))


def _word_positions(corpus: Corpus, word: str) -> List[int]:
    return _engine_term_positions(QueryEngine(corpus), "word", word)


def _pos_positions(corpus: Corpus, tag: str) -> List[int]:
    return _engine_term_positions(QueryEngine(corpus), "pos", tag)


def _bruteforce_bounded_gap(
    corpus: Corpus,
    start_positions: List[int],
    mn: int,
    mx: int,
    *,
    end_ok=None,
) -> List[Tuple[int, int]]:
    """CQP-style non-overlapping leftmost-longest reference for ``L []{mn,mx} R``.

    ``start_positions`` are the candidate positions of the left operand ``L``.
    ``end_ok(tok)`` constrains the final (right) operand ``R``; ``None`` means the
    right operand is the any-token ``[]`` (matches every position). The middle is
    always ``[]`` here. The whole match span must lie within a single sentence
    (default scope ``within(<s>)``). Leftmost-longest: at each surviving start,
    take the *largest* gap; scanning left to right, skip starts that fall inside a
    previously accepted span (non-overlapping).
    """
    tok_to_sent = corpus.token_to_sent()
    sent_ends = corpus.sent_ends
    accepted: List[Tuple[int, int]] = []
    last_end = -1  # exclusive end of last accepted span
    for p in sorted(start_positions):
        if p < last_end:
            continue
        sid = int(tok_to_sent[p])
        se = int(sent_ends[sid])
        best_final: Optional[int] = None
        # offset = tokens from L start to the final token: 1 + rep, rep in [mn, mx].
        for off in range(mx + 1, mn, -1):
            final_tok = p + off
            if final_tok >= se:
                continue
            if int(tok_to_sent[final_tok]) != sid:
                continue
            if end_ok is not None and not end_ok(final_tok):
                continue
            best_final = final_tok
            break
        if best_final is not None:
            accepted.append((p, best_final + 1))
            last_end = best_final + 1
    return accepted


def _bench_engine() -> Optional[QueryEngine]:
    index_path = os.environ.get("CANDYCONC_INDEX_PATH")
    if not index_path or not Path(index_path).exists():
        return None
    from candyconc.core.fast_index_backend import FastIndexBackend
    from cqlhpc.fast_corpus import FastCorpus

    backend = FastIndexBackend(Path(index_path))
    return QueryEngine(FastCorpus.from_backend(backend))


# A small corpus that exercises the []-endpoint bounded repeat. Two sentences in
# one doc; a third sentence with no following token (boundary edge case).
#   sent0: die x y z          (idx 0..3)
#   sent1: die a die b c .    (idx 4..9) -> two 'die', overlapping windows
#   sent2: die                (idx 10)   -> trailing 'die' with no follower
_GAP_WORDS = ["die", "x", "y", "z", "die", "a", "die", "b", "c", ".", "die"]
_GAP_POS = ["DET", "X", "X", "X", "DET", "X", "DET", "X", "X", "PUNCT", "DET"]
_GAP_SENT_STARTS = [0, 4, 10]
_GAP_SENT_ENDS = [4, 10, 11]


@pytest.fixture
def gap_corpus() -> Corpus:
    return _build_corpus(
        _GAP_WORDS,
        _GAP_POS,
        _GAP_SENT_STARTS,
        _GAP_SENT_ENDS,
        doc_starts=[0],
        doc_ends=[len(_GAP_WORDS)],
    )


@pytest.mark.parametrize("mn,mx", [(0, 3), (1, 2), (0, 1), (1, 3)])
def test_bounded_repeat_right_empty_endpoint_matches(gap_corpus: Corpus, mn: int, mx: int) -> None:
    """``[word="die"] []{mn,mx} []`` must match (was a silent zero)."""
    eng = QueryEngine(gap_corpus)
    query = f'[word="die"] []{{{mn},{mx}}} []'
    got = _spans(eng, query)
    ref = _bruteforce_bounded_gap(gap_corpus, _word_positions(gap_corpus, "die"), mn, mx)
    assert got == ref, f"{query}: engine {got} != bruteforce {ref}"
    # The headline regression: the result is now non-empty where matches exist.
    assert got, f"{query}: expected non-zero matches"


def test_bounded_repeat_left_empty_endpoint_matches(gap_corpus: Corpus) -> None:
    """``[] []{0,2} [word="die"]`` — left ``[]`` endpoint with concrete right."""
    eng = QueryEngine(gap_corpus)
    mn, mx = 0, 2
    query = f'[] []{{{mn},{mx}}} [word="die"]'
    got = _spans(eng, query)
    die = set(_word_positions(gap_corpus, "die"))
    n = gap_corpus.n_tokens
    ref = _bruteforce_bounded_gap(
        gap_corpus, list(range(n)), mn, mx, end_ok=lambda t: t in die
    )
    assert got == ref, f"{query}: engine {got} != bruteforce {ref}"
    assert got


def test_bounded_repeat_all_empty_endpoints_matches(gap_corpus: Corpus) -> None:
    """``[] []{0,3} []`` — every operand is the any-token wildcard."""
    eng = QueryEngine(gap_corpus)
    mn, mx = 0, 3
    query = f'[] []{{{mn},{mx}}} []'
    got = _spans(eng, query)
    n = gap_corpus.n_tokens
    ref = _bruteforce_bounded_gap(gap_corpus, list(range(n)), mn, mx)
    assert got == ref, f"{query}: engine {got} != bruteforce {ref}"
    assert got


def test_bounded_repeat_pos_left_empty_right_matches(gap_corpus: Corpus) -> None:
    """``[pos="DET"] []{1,2} []`` — concrete pos left, ``[]`` right endpoint."""
    eng = QueryEngine(gap_corpus)
    mn, mx = 1, 2
    query = f'[pos="DET"] []{{{mn},{mx}}} []'
    got = _spans(eng, query)
    ref = _bruteforce_bounded_gap(gap_corpus, _pos_positions(gap_corpus, "DET"), mn, mx)
    assert got == ref, f"{query}: engine {got} != bruteforce {ref}"
    assert got


def test_bounded_repeat_concrete_endpoints_unchanged(gap_corpus: Corpus) -> None:
    """Regression guard: a bounded gap with *no* ``[]`` endpoint is unaffected."""
    eng = QueryEngine(gap_corpus)
    mn, mx = 1, 3
    query = f'[word="die"] []{{{mn},{mx}}} [word="die"]'
    got = _spans(eng, query)
    die = set(_word_positions(gap_corpus, "die"))
    ref = _bruteforce_bounded_gap(
        gap_corpus, _word_positions(gap_corpus, "die"), mn, mx, end_ok=lambda t: t in die
    )
    assert got == ref


def test_bench_bounded_repeat_empty_endpoint_nonoverlap_golden() -> None:
    """Golden on the real bench index: ``[word="die"] []{0,3} []`` matches the
    CQP non-overlapping leftmost-longest brute-force reference exactly (and is
    non-zero, where it previously returned 0)."""
    eng = _bench_engine()
    if eng is None:
        pytest.skip("CANDYCONC_INDEX_PATH must point at a real Fast Index")
    corpus = eng.corpus
    got = _spans(eng, '[word="die"] []{0,3} []')
    die_positions = _engine_term_positions(eng, "word", "die")
    ref = _bruteforce_bounded_gap(corpus, die_positions, 0, 3)
    assert got == ref
    assert got, "bounded-repeat []-endpoint must yield non-zero matches on bench index"


# --------------------------------------------------------------------------- #
# Bug 2: within(<doc>) scope must cross sentence boundaries within a document   #
# --------------------------------------------------------------------------- #
# Two documents with properly nested sentences:
#   doc0: sent0=[A x y]  sent1=[z B]   -> 'y'(2) ends sent0, 'z'(3) starts sent1:
#                                          the adjacent bigram 'y z' crosses the
#                                          sent0/sent1 boundary but stays in doc0;
#                                          'A'(0) ... 'B'(4) is a cross-sentence gap.
#   doc1: sent2=[A B]                  -> within-sentence A B (idx 5,6)
_DOC_WORDS = ["A", "x", "y", "z", "B", "A", "B"]
_DOC_POS = ["X", "X", "X", "X", "Y", "X", "Y"]
_DOC_SENT_STARTS = [0, 3, 5]
_DOC_SENT_ENDS = [3, 5, 7]
_DOC_DOC_STARTS = [0, 5]
_DOC_DOC_ENDS = [5, 7]


@pytest.fixture
def doc_corpus() -> Corpus:
    return _build_corpus(
        _DOC_WORDS, _DOC_POS, _DOC_SENT_STARTS, _DOC_SENT_ENDS, _DOC_DOC_STARTS, _DOC_DOC_ENDS
    )


def test_within_doc_matches_cross_sentence_bigram_postings(doc_corpus: Corpus) -> None:
    """Adjacent bigram across a sentence boundary (postings fast path)."""
    eng = QueryEngine(doc_corpus)
    # 'y z' is idx 2->3: y ends sent0 ([0,3)), z starts sent1 ([3,5)), both in doc0.
    s = _spans(eng, 'within(<s>, [word="y"] [word="z"])')
    d = _spans(eng, 'within(<doc>, [word="y"] [word="z"])')
    assert s == [], "cross-sentence bigram must NOT match within(<s>)"
    assert d == [(2, 4)], "cross-sentence bigram MUST match within(<doc>)"
    # within-sentence bigram 'A B' (idx 5,6, doc1) matches under both scopes.
    assert _spans(eng, 'within(<s>, [word="A"] [word="B"])') == [(5, 7)]
    assert _spans(eng, 'within(<doc>, [word="A"] [word="B"])') == [(5, 7)]


def test_within_doc_matches_cross_sentence_gap_nfa(doc_corpus: Corpus) -> None:
    """Bounded-gap query (hybrid NFA path) crossing a sentence boundary."""
    eng = QueryEngine(doc_corpus)
    opt = SearchOptions(max_matches=10_000_000)
    # 'A []{1,5} B': A(0) ... B(4) within doc0 but across the sent0/sent1 boundary.
    s = _spans(eng, 'within(<s>, [word="A"] []{1,5} [word="B"])')
    d = _spans(eng, 'within(<doc>, [word="A"] []{1,5} [word="B"])')
    assert s == [], "cross-sentence gap must NOT match within(<s>)"
    assert d == [(0, 5)], "cross-sentence gap MUST match within(<doc>)"
    # count() must agree with the iterator on both scopes.
    assert eng.count('within(<s>, [word="A"] []{1,5} [word="B"])', opt) == 0
    assert eng.count('within(<doc>, [word="A"] []{1,5} [word="B"])', opt) == 1
    # search_arrays() must agree with search().
    sa = eng.search_arrays('within(<doc>, [word="A"] []{1,5} [word="B"])', opt)
    assert list(zip(sa[0].tolist(), sa[1].tolist())) == [(0, 5)]


@pytest.mark.parametrize(
    "query",
    [
        '[word="der"] [word="die"]',                 # postings bigram
        '[word="der"] []{1,3} [word="Idee"]',        # bounded gap (NFA)
        '[pos="DET"] [pos="NOUN"]',                   # pos bigram
        '[word~"ge.*"] [pos="NOUN"]',                # regex + pos (NFA)
        '[word="der"] [word="die"] [word="Idee"]',   # trigram
    ],
)
def test_within_doc_is_superset_of_within_sentence(query: str) -> None:
    """``within(<doc>) ⊇ within(<s>)`` for every query type on a corpus whose
    sentences are properly nested in documents; ``count == search`` for both."""
    corpus = _build_random_nested_corpus()
    eng = QueryEngine(corpus)
    opt = SearchOptions(max_matches=10_000_000)
    s = set(_spans(eng, f"within(<s>, {query})"))
    d = set(_spans(eng, f"within(<doc>, {query})"))
    assert s.issubset(d), f"{query}: within(<s>) {len(s)} not subset of within(<doc>) {len(d)}"
    assert len(d) >= len(s)
    # count() agrees with the materialised match set on both scopes.
    assert eng.count(f"within(<s>, {query})", opt) == len(s)
    assert eng.count(f"within(<doc>, {query})", opt) == len(d)


def test_within_doc_finds_extra_cross_sentence_gap_matches() -> None:
    """On the nested fixture, a gap query finds strictly more matches under
    document scope than sentence scope (the cross-sentence matches)."""
    corpus = _build_random_nested_corpus()
    eng = QueryEngine(corpus)
    query = '[word="der"] []{1,3} [word="Idee"]'
    s = set(_spans(eng, f"within(<s>, {query})"))
    d = set(_spans(eng, f"within(<doc>, {query})"))
    assert s.issubset(d)
    assert d - s, "expected cross-sentence gap matches under within(<doc>)"


# --------------------------------------------------------------------------- #
# Bug 2 (cont.): search_profile() is the fourth public doc-scope path. It must  #
# agree with search_arrays() under within(<doc>). Before the fix it still ran   #
# the old per-sentence matcher + b>doc_end clamp and could not match a span     #
# crossing a sentence boundary inside a document.                               #
# --------------------------------------------------------------------------- #
def _profile_spans(eng: QueryEngine, query: str, max_matches: int = 10_000_000):
    opt = SearchOptions(max_matches=max_matches)
    matches, timings = eng.search_profile(query, opt)
    # search_profile returns (matches, timings); the timings dict is informational.
    assert isinstance(timings, dict)
    return sorted((int(m.start), int(m.end)) for m in matches)


def _arrays_spans(eng: QueryEngine, query: str, max_matches: int = 10_000_000):
    opt = SearchOptions(max_matches=max_matches)
    starts, ends = eng.search_arrays(query, opt)
    return sorted(zip(starts.tolist(), ends.tolist()))


def test_search_profile_within_doc_matches_cross_sentence_gap_nfa(doc_corpus: Corpus) -> None:
    """search_profile within(<doc>) finds the cross-sentence gap (hybrid NFA path).

    This is the headline regression for the fourth doc-scope path: before the fix
    search_profile used the per-sentence matcher with a b>doc_end clamp and
    returned [] here, diverging from search/search_arrays/count.
    """
    eng = QueryEngine(doc_corpus)
    query = 'within(<doc>, [word="A"] []{1,5} [word="B"])'
    # search_profile must agree with the already-fixed search_arrays path.
    assert _profile_spans(eng, query) == _arrays_spans(eng, query) == [(0, 5)]
    # and must NOT match under sentence scope.
    assert _profile_spans(eng, 'within(<s>, [word="A"] []{1,5} [word="B"])') == []


def test_search_profile_within_doc_matches_cross_sentence_bigram(doc_corpus: Corpus) -> None:
    """search_profile within(<doc>) finds an adjacent bigram crossing a sentence
    boundary (postings fast path) and agrees with search_arrays."""
    eng = QueryEngine(doc_corpus)
    query = 'within(<doc>, [word="y"] [word="z"])'
    assert _profile_spans(eng, query) == _arrays_spans(eng, query) == [(2, 4)]
    assert _profile_spans(eng, 'within(<s>, [word="y"] [word="z"])') == []


@pytest.mark.parametrize(
    "query",
    [
        '[word="der"] [word="die"]',                 # postings bigram
        '[word="der"] []{1,3} [word="Idee"]',        # bounded gap (NFA)
        '[pos="DET"] [pos="NOUN"]',                   # pos bigram
        '[word~"ge.*"] [pos="NOUN"]',                # regex + pos (NFA)
        '[word="der"] [word="die"] [word="Idee"]',   # trigram
    ],
)
def test_search_profile_doc_scope_equals_search_arrays(query: str) -> None:
    """search_profile within(<doc>) == search_arrays within(<doc>) for every query
    type, and within(<s>) is unchanged between the two paths."""
    corpus = _build_random_nested_corpus()
    eng = QueryEngine(corpus)
    doc_q = f"within(<doc>, {query})"
    sent_q = f"within(<s>, {query})"
    assert _profile_spans(eng, doc_q) == _arrays_spans(eng, doc_q)
    # within(<s>) behavior must remain identical (no drive-by change).
    assert _profile_spans(eng, sent_q) == _arrays_spans(eng, sent_q)


def test_bench_search_profile_doc_scope_equals_search_arrays_golden() -> None:
    """Golden on the real bench index: search_profile within(<doc>) results match
    search_arrays within(<doc>) results exactly — pinning the fourth public
    doc-scope path against the r9-fixed reference."""
    eng = _bench_engine()
    if eng is None:
        pytest.skip("CANDYCONC_INDEX_PATH must point at a real Fast Index")
    for query in (
        'within(<doc>, [word="die"] [word="und"])',
        'within(<doc>, [word="die"] []{1,3} [word="und"])',
        'within(<doc>, [pos="DET"] [pos="NOUN"])',
    ):
        prof = _profile_spans(eng, query)
        arr = _arrays_spans(eng, query)
        assert prof == arr, f"{query}: search_profile {len(prof)} != search_arrays {len(arr)}"
