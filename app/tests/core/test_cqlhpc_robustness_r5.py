"""Robustness + product-gap fixes for the CQLHPC query engine (r5).

Each test documents a before/after for one of four confirmed defects from the
2026-06-14 fresh-eyes product audit (report since removed from the repo;
sections 3 and 5):

1. OOV exact-match (``[word="zzz"]``) raised the *unrecognised* "nicht
   auflösbar" error and 500'd instead of yielding zero hits. It must now raise
   the recognised empty-match contract ("liefert keine Treffer"), which callers
   convert to an empty result set -- mirroring the OOV ``in {...}`` / ``!=``
   sentinel discipline already in place.
2. Malformed CQL 500'd on the sync path because ``ParseError`` was not a
   ``ValueError`` subclass, so ``except (RuntimeError, ValueError)`` missed it.
   ``ParseError`` now subclasses ``ValueError`` and renders a "Parse"-tagged
   message so user-error classifiers route it to a 400.
3. The empty token clause ``[]`` ("any token") did not parse, breaking the
   idiomatic gap query ``[word="x"] []{1,3} [word="y"]``. It now parses to a
   zero-condition clause that the NFA runner treats as universally true.
4. No case-insensitive matching. ``%c`` (IMS-CWB style) now folds ``=``/``in``/
   ``~`` via casefold; default behavior is unchanged.

No mocks: tests run against a real in-memory Fast-Index-shaped corpus built with
the same helper the existing P0 regression suite uses.
"""

from __future__ import annotations

import numpy as np
import pytest

from cqlhpc import QueryEngine
from cqlhpc.ast import Cond, TokenClause
from cqlhpc.builder import from_builder_json, to_builder_json, to_cql
from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.lexer import lex
from cqlhpc.lexicon import Lexicon
from cqlhpc.normalize import normalize
from cqlhpc.parser import ParseError, parse_cql
from cqlhpc.predicates import _value_to_type_ids, compile_clause


def _make_corpus(words: list[str]) -> Corpus:
    """Single-doc, single-sentence corpus over a literal word stream."""
    uniq = list(dict.fromkeys(words))
    str_to_id = {s: i for i, s in enumerate(uniq)}
    ids_word = np.asarray([str_to_id[w] for w in words], dtype=np.int32)
    zeros = np.zeros(len(words), dtype=np.int32)
    n = len(words)
    return Corpus(
        attrs={"word": ids_word, "pos": zeros, "lemma": zeros},
        lex={
            "word": Lexicon(
                id_to_str=uniq,
                str_to_id=str_to_id,
                freqs=np.ones(len(uniq), dtype=np.int64),
            ),
            "pos": Lexicon(id_to_str=["X"], str_to_id={"X": 0}, freqs=np.asarray([n])),
            "lemma": Lexicon(id_to_str=["l"], str_to_id={"l": 0}, freqs=np.asarray([n])),
        },
        postings={
            "word": build_postings_from_tokens(ids_word, len(uniq)),
            "pos": build_postings_from_tokens(zeros, 1),
            "lemma": build_postings_from_tokens(zeros, 1),
        },
        doc_starts=np.asarray([0], dtype=np.int32),
        doc_ends=np.asarray([n], dtype=np.int32),
        sent_starts=np.asarray([0], dtype=np.int32),
        sent_ends=np.asarray([n], dtype=np.int32),
    )


def _starts(engine: QueryEngine, query: str) -> list[int]:
    return sorted(m.start for m in engine.search(query))


# --------------------------------------------------------------------------
# Fix 1: OOV exact-match -> recognised empty-match (no 500)
# --------------------------------------------------------------------------


def test_oov_equals_compiles_to_never_matching_sentinel() -> None:
    """``compile_clause`` for an OOV ``=`` now emits a *never-matching sentinel*
    predicate (``attr = -1``) instead of raising (r7 D1c).

    The NFA build calls ``compile_clause`` for every token, including operands
    inside an alternation or a quantifier. Raising there aborted the whole query
    even when another branch matched. The sentinel keeps the predicate valid but
    unsatisfiable so ``X?/X*/X{0,n}`` take the empty path and ``X+/X{1,n}`` /
    bare ``X`` yield zero hits. The *recognised* "liefert keine Treffer" empty
    contract is now enforced one level up by the engine fast path (see the
    engine-level tests below), not by ``compile_clause`` itself.
    """
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    clause = TokenClause(conds=(Cond(attr="word", op="=", value="zzzabsent"),))
    cc = compile_clause(clause, corpus)  # must NOT raise
    assert len(cc.conds) == 1
    attr, op, vals = cc.conds[0]
    assert attr == "word"
    assert op == "="
    assert list(vals) == [-1]  # no real lexicon id can equal -1
    # The sentinel never matches any real token in the corpus.
    assert not any(cc.match_at(corpus, p) for p in range(3))


def test_oov_in_set_compiles_to_never_matching_sentinel() -> None:
    """An all-OOV ``in {...}`` set likewise compiles to the never-matching
    sentinel instead of raising, so it can sit inside an alternation/quantifier.
    """
    corpus = _make_corpus(["alpha", "beta"])
    clause = TokenClause(
        conds=(Cond(attr="word", op="in", value=["zzz1", "zzz2"]),)
    )
    cc = compile_clause(clause, corpus)  # must NOT raise
    assert list(cc.conds[0][2]) == [-1]
    assert not any(cc.match_at(corpus, p) for p in range(2))


def test_oov_equals_yields_zero_hits_via_engine() -> None:
    """End-to-end: an OOV ``=`` query resolves to zero hits without crashing.

    ``search`` raises the empty-match contract; the boundary (cql_engine) maps
    it to ``[]``. We assert the engine raises the *recognised* error so that
    mapping fires, and that a present value still returns hits.
    """
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    # present value still works
    assert _starts(engine, '[word="alpha"]') == [0, 2]
    # absent value -> recognised empty-match error
    with pytest.raises(ValueError, match="liefert keine Treffer"):
        engine.search('[word="zzzabsent"]')


def test_oov_equals_in_sequence_is_recognised_empty_match() -> None:
    """A multi-clause sequence with one OOV ``=`` clause also fails cleanly."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    with pytest.raises(ValueError, match="liefert keine Treffer"):
        engine.search('[word="alpha"] [word="zzzabsent"]')


def test_value_to_type_ids_oov_equals_still_returns_none() -> None:
    """Low-level contract is unchanged: OOV ``=`` resolves to ``None`` (the
    "absent value" signal); ``compile_clause`` is what reclassifies it as an
    empty match. This pins the boundary so the P0 sentinel test stays valid.
    """
    corpus = _make_corpus(["alpha", "beta"])
    assert _value_to_type_ids(Cond(attr="word", op="=", value="absent"), corpus) is None
    # ``!=`` still emits the match-all sentinel (-1).
    neq = _value_to_type_ids(Cond(attr="word", op="!=", value="absent"), corpus)
    assert neq is not None and neq.size == 1 and int(neq[0]) == -1


# --------------------------------------------------------------------------
# Fix 2: ParseError is a ValueError subclass and reads as a user error
# --------------------------------------------------------------------------


def test_parse_error_is_valueerror_subclass() -> None:
    """The class identity itself is the fix: ``except ValueError`` must catch it."""
    assert issubclass(ParseError, ValueError)
    err = ParseError("boom", 3, 4)
    assert isinstance(err, ValueError)
    # diagnostic spans preserved
    assert (err.start, err.end) == (3, 4)


@pytest.mark.parametrize(
    "query",
    [
        '[word="die"][',     # dangling open bracket (the audit's repro)
        '[',                  # bare open bracket
        '[word=',             # missing value
        '[word="a" &]',      # trailing conjunction
    ],
)
def test_malformed_cql_raises_valueerror_with_parse_marker(query: str) -> None:
    """Malformed CQL must raise a ``ValueError`` (so the sync server handler
    catches it) whose message contains "Parse" (so the user-error classifier
    routes it to a 400 instead of letting it 500).
    """
    with pytest.raises(ValueError) as exc:
        parse_cql(query)
    assert isinstance(exc.value, ParseError)
    assert "Parse" in str(exc.value)


def test_valid_cql_still_parses() -> None:
    """Guard against over-eager rejection: well-formed queries must still parse."""
    for query in ['[word="a"]', '[word="a"] [pos="X"]', '[word="a"] | [word="b"]']:
        parse_cql(query)  # must not raise


# --------------------------------------------------------------------------
# Fix 3: empty token clause [] ("any token") and gap queries
# --------------------------------------------------------------------------


def test_empty_token_clause_parses() -> None:
    """``[]`` must parse to a zero-condition token clause (pre-fix: ParseError)."""
    node = parse_cql("[]")
    # normalize/builder round-trip survives the empty clause.
    assert to_cql(normalize(node)) == "[]"


def test_empty_token_matches_any_single_token() -> None:
    corpus = _make_corpus(["a", "b", "c"])
    engine = QueryEngine(corpus)
    # default within-sentence scope; one sentence of 3 tokens.
    assert _starts(engine, "[]") == [0, 1, 2]


def test_gap_query_with_bounded_empty_token() -> None:
    """The idiomatic gap query ``[word="x"] []{1,3} [word="y"]`` must work."""
    # x _ _ y : exactly two tokens between x and y -> matched by {1,3}.
    corpus = _make_corpus(["x", "m", "n", "y", "z", "x", "y"])
    engine = QueryEngine(corpus)
    starts = _starts(engine, '[word="x"] []{1,3} [word="y"]')
    # the x at 0 reaches y at 3 (gap 2); x at 5 -> y at 6 is gap 0 (not >=1).
    assert starts == [0]


def test_empty_token_then_concrete_clause() -> None:
    """``[word="x"] []`` matches x followed by any token (pre-fix: 0 hits)."""
    corpus = _make_corpus(["x", "a", "x", "b"])
    engine = QueryEngine(corpus)
    # x at 0 has follower a; x at 2 has follower b -> both match.
    starts = _starts(engine, '[word="x"] []')
    assert starts == [0, 2]


def test_empty_token_builder_roundtrip() -> None:
    """Empty clause survives the builder JSON contract (capabilities depend on it)."""
    node = normalize(parse_cql('[word="x"] [] [word="y"]'))
    rebuilt = from_builder_json(to_builder_json(node))
    assert to_cql(normalize(rebuilt)) == '[word="x"] [] [word="y"]'


# --------------------------------------------------------------------------
# Fix 4: case-insensitive %c flag
# --------------------------------------------------------------------------


def test_percent_c_lexes_as_flag_token() -> None:
    toks = [t for t in lex('[word="merkel"%c]') if t.kind == "FLAG"]
    assert len(toks) == 1
    assert toks[0].value == "c"


def test_percent_c_parses_onto_cond_flags() -> None:
    node = parse_cql('[word="merkel"%c]')
    cond = node.clause.conds[0]
    assert cond.flags == "c"
    # default (no flag) leaves flags empty -> behavior unchanged.
    assert parse_cql('[word="merkel"]').clause.conds[0].flags == ""


def test_percent_c_equals_is_case_insensitive() -> None:
    """``[word="merkel"%c]`` folds case (the audit's German capitalisation trap)."""
    corpus = _make_corpus(["Merkel", "merkel", "MERKEL", "Scholz"])
    engine = QueryEngine(corpus)
    # case-sensitive default: only the exact-case token.
    assert _starts(engine, '[word="merkel"]') == [1]
    # case-insensitive: all three casings of merkel.
    assert _starts(engine, '[word="merkel"%c]') == [0, 1, 2]
    # the requested casing does not matter when folding.
    assert _starts(engine, '[word="MERKEL"%c]') == [0, 1, 2]


def test_percent_c_in_set_is_case_insensitive() -> None:
    corpus = _make_corpus(["Merkel", "merkel", "Scholz", "scholz"])
    engine = QueryEngine(corpus)
    assert _starts(engine, '[word in {"merkel","scholz"}%c]') == [0, 1, 2, 3]


def test_percent_c_regex_is_case_insensitive() -> None:
    corpus = _make_corpus(["Merkel", "merkel", "Scholz"])
    engine = QueryEngine(corpus)
    assert _starts(engine, '[word~"^merk.*"%c]') == [0, 1]


def test_percent_c_oov_yields_recognised_empty_match() -> None:
    """An OOV case-insensitive ``=`` still resolves to the empty-match contract."""
    corpus = _make_corpus(["Merkel", "Scholz"])
    engine = QueryEngine(corpus)
    with pytest.raises(ValueError, match="liefert keine Treffer"):
        engine.search('[word="zzzabsent"%c]')


def test_percent_c_not_equals_fails_loudly_not_silently() -> None:
    """``!=``%c needs a negated-set test the NFA lacks; it must fail loudly as a
    user error rather than silently matching the wrong tokens.
    """
    corpus = _make_corpus(["Merkel", "merkel"])
    cond = Cond(attr="word", op="!=", value="merkel", flags="c")
    with pytest.raises(ValueError, match="nicht unterstützt"):
        _value_to_type_ids(cond, corpus)


def test_percent_c_builder_roundtrip_preserves_flag() -> None:
    node = normalize(parse_cql('[word="merkel"%c]'))
    assert to_cql(node) == '[word="merkel" %c]'
    rebuilt = from_builder_json(to_builder_json(node))
    assert rebuilt.clause.conds[0].flags == "c"


def test_percent_c_and_plain_do_not_share_cache_entries() -> None:
    """The flag participates in cache keys: the same engine must return distinct
    results for the case-sensitive and case-insensitive forms of one word.
    """
    corpus = _make_corpus(["Merkel", "merkel", "MERKEL"])
    engine = QueryEngine(corpus)
    assert _starts(engine, '[word="merkel"]') == [1]
    assert _starts(engine, '[word="merkel"%c]') == [0, 1, 2]
    # query again in the other order to exercise the populated caches.
    assert _starts(engine, '[word="merkel"]') == [1]
    assert _starts(engine, '[word="merkel"%c]') == [0, 1, 2]


# --------------------------------------------------------------------------
# r7 D1 (b): out-of-vocabulary alternation operands are absorbed, not fatal
# --------------------------------------------------------------------------


def test_oov_alternation_present_branch_still_matches() -> None:
    """``[word="x"] | [word="OOV"]`` must match every ``x`` instead of aborting
    the whole alternation because one branch is out-of-vocabulary (r7 D1b)."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    # control: both branches present.
    assert _starts(engine, '[word="alpha"] | [word="beta"]') == [0, 1, 2]
    # one OOV branch in either position must not change the present branch.
    assert _starts(engine, '[word="alpha"] | [word="zzzabsent"]') == [0, 2]
    assert _starts(engine, '[word="zzzabsent"] | [word="alpha"]') == [0, 2]


def test_oov_alternation_all_branches_oov_is_empty_not_error() -> None:
    """An alternation where *every* branch is OOV resolves to an empty result,
    not a re-raised error (r7 D1b)."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    assert _starts(engine, '[word="zzz1"] | [word="zzz2"]') == []


def test_oov_alternation_three_way_mixed() -> None:
    """A three-way alternation keeps only the present branches' positions."""
    corpus = _make_corpus(["alpha", "beta", "gamma", "alpha"])
    engine = QueryEngine(corpus)
    starts = _starts(
        engine, '[word="alpha"] | [word="zzz"] | [word="gamma"]'
    )
    assert starts == [0, 2, 3]


# --------------------------------------------------------------------------
# r7 D1 (c): out-of-vocabulary quantified operands behave per quantifier
# --------------------------------------------------------------------------


def test_oov_optional_quantifier_takes_empty_path() -> None:
    """``X Y?`` with an OOV ``Y`` must still match ``X`` (the optional operand is
    simply absent), for ``?``, ``*`` and ``{0,n}`` (r7 D1c)."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    for q in (
        '[word="alpha"] [word="zzz"]?',
        '[word="alpha"] [word="zzz"]*',
        '[word="alpha"] [word="zzz"]{0,3}',
    ):
        assert _starts(engine, q) == [0, 2], q


def test_oov_mandatory_unbounded_quantifier_yields_zero_hits() -> None:
    """``X Y+`` / ``X Y{1,n}`` with an OOV ``Y`` must yield zero hits via the NFA
    sentinel path -- the mandatory operand can never match, but it must not crash
    (r7 D1c)."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    for q in (
        '[word="alpha"] [word="zzz"]+',
        '[word="alpha"] [word="zzz"]{1,3}',
    ):
        assert _starts(engine, q) == [], q


def test_oov_exact_repeat_in_sequence_is_recognised_empty_match() -> None:
    """``X Y{2}`` expands to a literal sequence on the postings fast path, so an
    OOV ``Y`` surfaces the recognised "liefert keine Treffer" empty contract
    (which the boundary maps to ``[]``) -- the same discipline as a plain
    OOV-in-sequence. Either way it is an empty result, never a 500."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    with pytest.raises(ValueError, match="liefert keine Treffer"):
        engine.search('[word="alpha"] [word="zzz"]{2}')


def test_bare_oov_quantified_term_is_empty() -> None:
    """A bare quantified OOV term yields an empty result without raising
    (zero-width optional matches are not reported)."""
    corpus = _make_corpus(["alpha", "beta"])
    engine = QueryEngine(corpus)
    assert _starts(engine, '[word="zzz"]?') == []
    assert _starts(engine, '[word="zzz"]+') == []


# --------------------------------------------------------------------------
# r7 D1 (d): ``{,n}`` shorthand parses as ``{0,n}``
# --------------------------------------------------------------------------


def test_comma_n_shorthand_parses_as_zero_lower_bound() -> None:
    """``{,n}`` (comma right after ``{``) means a lower bound of 0 (r7 D1d)."""
    from cqlhpc.ast import Quant

    node = parse_cql('[word="a"]{,5}')
    assert isinstance(node, Quant)
    assert (node.m, node.n) == (0, 5)
    # ``{,}`` is the unbounded form (equivalent to ``*``).
    node2 = parse_cql('[word="a"]{,}')
    assert isinstance(node2, Quant)
    assert (node2.m, node2.n) == (0, None)


def test_comma_n_shorthand_matches_like_zero_n() -> None:
    """``X{,n}`` behaves exactly like ``X{0,n}`` end-to-end."""
    corpus = _make_corpus(["x", "m", "n", "y", "z", "x", "y"])
    engine = QueryEngine(corpus)
    expected = _starts(engine, '[word="x"] []{0,3} [word="y"]')
    assert _starts(engine, '[word="x"] []{,3} [word="y"]') == expected
    # the {,3} form reaches the y at 3 from x at 0 (gap 2) and x at 5 -> y at 6.
    assert _starts(engine, '[word="x"] []{,3} [word="y"]') == [0, 5]
