"""Regression tests for confirmed P0 bugs in the CQLHPC query engine.

Each test fails on the pre-fix code and passes afterwards:

* int16 overflow of ``cond_val_len`` for large ``in``/regex clauses.
* ``!=`` against an out-of-vocabulary value must match every token.
* lexer must preserve backslashes in string literals so regex values survive.
"""

from __future__ import annotations

import builtins
import numpy as np
import pytest

from cqlhpc.ast import Cond, Seq, Tok, TokenClause
from cqlhpc.engine import QueryEngine
from cqlhpc.lexer import lex
from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.lexicon import Lexicon
from cqlhpc.nfa import compile_nfa, find_nonoverlapping_matches
from cqlhpc import predicates
from cqlhpc.predicates import _value_to_type_ids


def _make_corpus(words: list[str]) -> Corpus:
    """Build a tiny single-doc, single-sentence corpus from a word stream."""
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


def test_in_clause_above_int16_does_not_overflow() -> None:
    """An ``in``-clause carrying >32767 distinct value ids must not overflow.

    ``cond_val_len`` used to be stored as int16 (max 32767). With numpy 2.x a
    length of 40000 raises OverflowError during lowering; with numpy 1.x it
    silently wrapped to a negative length and matched garbage. The widened
    int32 dtype handles it.
    """
    vocab = 40000  # > 32767
    words = [f"w{i}" for i in range(vocab)]
    corpus = _make_corpus(words)

    clause = TokenClause(conds=(Cond(attr="word", op="in", value=words),))
    nfa = compile_nfa(Seq(parts=(Tok(clause=clause),)), corpus)

    # The length array must be wide enough to hold the value count.
    assert nfa.cond_val_len.dtype == np.int32
    assert int(nfa.cond_val_len.max()) == vocab

    matches = find_nonoverlapping_matches(nfa, corpus, 0, vocab, max_matches=100000)
    # Every token's id is in the value set -> every token matches.
    assert len(matches) == vocab
    assert matches[0] == (0, 1)
    assert matches[-1] == (vocab - 1, vocab)


def test_not_equal_oov_value_matches_all_tokens() -> None:
    """``[word!="absent"]`` must match every token when the value is OOV."""
    words = ["alpha", "beta", "gamma", "alpha"]
    corpus = _make_corpus(words)

    clause = TokenClause(conds=(Cond(attr="word", op="!=", value="nonexistentword"),))
    nfa = compile_nfa(Seq(parts=(Tok(clause=clause),)), corpus)
    matches = find_nonoverlapping_matches(nfa, corpus, 0, len(words), max_matches=100)
    assert len(matches) == len(words)

    # And a present value is still correctly excluded.
    clause2 = TokenClause(conds=(Cond(attr="word", op="!=", value="alpha"),))
    nfa2 = compile_nfa(Seq(parts=(Tok(clause=clause2),)), corpus)
    matches2 = find_nonoverlapping_matches(nfa2, corpus, 0, len(words), max_matches=100)
    # positions 1 (beta) and 2 (gamma) survive, positions 0 and 3 (alpha) excluded
    assert sorted(s for s, _ in matches2) == [1, 2]


def test_value_to_type_ids_oov_neq_returns_sentinel() -> None:
    """The OOV ``!=`` path returns a sentinel (-1), never None and never empty."""
    corpus = _make_corpus(["alpha", "beta"])
    cond = Cond(attr="word", op="!=", value="absent")
    ids = _value_to_type_ids(cond, corpus)
    assert ids is not None
    assert ids.size == 1
    assert int(ids[0]) == -1  # no real token id is negative -> matches all

    # ``=`` against an OOV value still resolves to "no match" (None).
    cond_eq = Cond(attr="word", op="=", value="absent")
    assert _value_to_type_ids(cond_eq, corpus) is None


def _match_starts(corpus: Corpus, clause: TokenClause, n: int) -> list[int]:
    nfa = compile_nfa(Seq(parts=(Tok(clause=clause),)), corpus)
    return sorted(s for s, _ in find_nonoverlapping_matches(nfa, corpus, 0, n, max_matches=1000))


def test_escaped_literal_eq_matches_period_tokens() -> None:
    r"""``[word="\."]`` must match exactly the period tokens.

    Regression (release re-audit 2026-06-10, finding 1): the lexer preserves
    ``\.`` in the literal, the lexicon stores the token as ``.``, so the raw
    lookup missed and ``=`` resolved to "no match". The unescape fallback
    retries with ``.`` and finds the stored token.
    """
    words = ["Hallo", ".", "Welt", "."]
    corpus = _make_corpus(words)
    clause = TokenClause(conds=(Cond(attr="word", op="=", value=r"\."),))
    assert _match_starts(corpus, clause, len(words)) == [1, 3]


def test_escaped_literal_neq_excludes_period_tokens() -> None:
    r"""``[word!="\."]`` must exclude periods — and never silently match all.

    Pre-fix the escaped lookup missed, the OOV rule kicked in, and the
    match-all sentinel made ``!=`` match every token including the periods.
    """
    words = ["Hallo", ".", "Welt", "."]
    corpus = _make_corpus(words)
    clause = TokenClause(conds=(Cond(attr="word", op="!=", value=r"\."),))
    starts = _match_starts(corpus, clause, len(words))
    assert starts == [0, 2]
    assert len(starts) < len(words)  # the silent match-all is the P0 bug


def test_escaped_literal_means_the_character_even_if_the_raw_token_exists() -> None:
    r"""``[word="\."]`` ist der Punkt, auch wenn das Lexikon ``\.`` kennt.

    Hier stand bis 2026-09-26 das Gegenteil ("the raw lookup wins"). Am
    Testindex gibt es die Token ``\|`` (10) und ``\.`` (6) aus maskiertem
    Markdown, und [word="\|"] zaehlte 10 statt 272.832 Pipes. In CQL maskiert
    der Backslash das Zeichen. Die rohe Form bleibt Rueckfall, wenn die
    entmaskierte im Lexikon fehlt.
    """
    words = ["Hallo", r"\.", ".", "|", r"\|", "|", r"\q"]
    corpus = _make_corpus(words)
    punkt = TokenClause(conds=(Cond(attr="word", op="=", value=r"\."),))
    assert _match_starts(corpus, punkt, len(words)) == [2]
    pipe = TokenClause(conds=(Cond(attr="word", op="=", value=r"\|"),))
    assert _match_starts(corpus, pipe, len(words)) == [3, 5]
    rueckfall = TokenClause(conds=(Cond(attr="word", op="=", value=r"\q"),))
    assert _match_starts(corpus, rueckfall, len(words)) == [6]
    menge = TokenClause(conds=(Cond(attr="word", op="in", value=[r"\|", "Hallo"]),))
    assert _match_starts(corpus, menge, len(words)) == [0, 3, 5]


def test_escaped_literal_with_c_means_the_character() -> None:
    r"""Mit %c galt dasselbe nicht einmal als Rueckfall: ``\|`` verglich
    kleingeschrieben mit ``\|`` und fand die Pipe nie."""
    words = ["Hallo", r"\|", "|"]
    corpus = _make_corpus(words)
    clause = TokenClause(conds=(Cond(attr="word", op="=", value=r"\|", flags="c"),))
    assert _match_starts(corpus, clause, len(words)) == [2]


def test_escaped_literal_oov_both_forms_still_applies_oov_rules() -> None:
    r"""When raw AND unescaped lookups miss, the OOV contract still holds."""
    corpus = _make_corpus(["alpha", "beta"])
    # ``=`` against a doubly-absent value -> no match (None).
    assert _value_to_type_ids(Cond(attr="word", op="=", value=r"\zzz"), corpus) is None
    # ``!=`` against a doubly-absent value -> match-all sentinel.
    ids = _value_to_type_ids(Cond(attr="word", op="!=", value=r"\zzz"), corpus)
    assert ids is not None and ids.size == 1 and int(ids[0]) == -1


def test_in_clause_resolves_escaped_values() -> None:
    r"""``in`` is a literal op too: ``\.`` in a value set finds the ``.`` token."""
    words = ["Hallo", ".", "Welt", "."]
    corpus = _make_corpus(words)
    clause = TokenClause(conds=(Cond(attr="word", op="in", value=[r"\.", "Hallo"]),))
    assert _match_starts(corpus, clause, len(words)) == [0, 1, 3]


def test_regex_op_values_are_not_unescaped(monkeypatch) -> None:
    r"""``~`` values must keep their backslashes (``\d+`` stays ``\d+``)."""
    corpus = _make_corpus(["a", "12"])
    seen: list[str] = []

    def _capture(pattern, lex, **kwargs):
        seen.append(pattern)
        return np.asarray([1], dtype=np.int32)

    monkeypatch.setattr(predicates, "_regex_to_type_ids", _capture)
    ids = _value_to_type_ids(Cond(attr="word", op="~", value=r"\d+"), corpus)
    assert ids is not None
    assert seen == [r"\d+"]  # backslash preserved, no unescaping


def test_regex_op_falls_back_without_native_lexicon_match(monkeypatch) -> None:
    """Clean wheels can import cqlhpc without compiled fast-index regex helpers."""
    corpus = _make_corpus(["alpha", "beta", "gamma", "alphabet"])
    monkeypatch.setattr(predicates, "lexicon_match_regex", None)
    monkeypatch.setattr(predicates, "lexicon_match_regex_ids", None)

    ids = _value_to_type_ids(Cond(attr="word", op="~", value=r"alpha.*"), corpus)
    assert ids is not None
    matched = {corpus.lex["word"].id_to_str[int(tid)] for tid in ids}
    assert matched == {"alpha", "alphabet"}


def test_regex_op_does_not_import_fast_index_backend(monkeypatch) -> None:
    """The clean-wheel regex path must not re-require native fast-index modules."""
    corpus = _make_corpus(["alpha", "alphabet", "beta"])
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "candyconc.core.fast_index_backend":
            raise AssertionError("cqlhpc regex fallback imported fast_index_backend")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    ids = _value_to_type_ids(Cond(attr="word", op="~", value=r"alpha.*"), corpus)
    assert ids is not None
    matched = {corpus.lex["word"].id_to_str[int(tid)] for tid in ids}
    assert matched == {"alpha", "alphabet"}


def test_python_lexicon_regex_ignores_native_helpers(monkeypatch) -> None:
    """Native helpers require offsets/strings_view; pure Python lexicons must scan."""
    corpus = _make_corpus(["alpha", "alphabet", "beta"])

    def fail_native(*_args, **_kwargs):
        raise AssertionError("native regex helper should not run for Python Lexicon")

    monkeypatch.setattr(predicates, "lexicon_match_regex", fail_native)
    monkeypatch.setattr(predicates, "lexicon_match_regex_ids", fail_native)
    ids = _value_to_type_ids(Cond(attr="word", op="~", value=r"alpha.*"), corpus)
    assert ids is not None
    matched = {corpus.lex["word"].id_to_str[int(tid)] for tid in ids}
    assert matched == {"alpha", "alphabet"}


def test_query_engine_regex_fallback_does_not_import_fast_corpus(monkeypatch) -> None:
    """End-to-end regex search must work when native fast-corpus modules are absent."""
    corpus = _make_corpus(["gehen", "geht", "bleibt", "gegangen"])
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "cqlhpc.fast_corpus":
            raise AssertionError("QueryEngine imported cqlhpc.fast_corpus")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    matches = QueryEngine(corpus).search('[word~"geh.*"]')
    assert [m.start for m in matches] == [0, 1]


@pytest.mark.parametrize(
    "src,expected",
    [
        (r'"\d+ung"', r"\d+ung"),
        (r'"\w+"', r"\w+"),
        (r'"a\.b"', r"a\.b"),
        (r'"a\\b"', "a\\b"),          # \\ collapses to a single backslash
        (r'"say \"hi\""', 'say "hi"'),  # \" embeds a literal quote
    ],
)
def test_lexer_preserves_regex_backslashes(src: str, expected: str) -> None:
    """String literals must keep backslashes for regex metacharacters.

    Previously the escape branch dropped the backslash, so ``"\\d+ung"`` lexed
    to ``d+ung`` and every regex/escaped query was silently wrong.
    """
    toks = lex(src)
    strings = [t for t in toks if t.kind == "STRING"]
    assert len(strings) == 1
    assert strings[0].value == expected


def test_fast_lex_arrays_densifies_structured_hash_fields() -> None:
    """Cython lexicon lookup receives dense arrays, never strided field views.

    ``Lexicon._hash_entries`` is a structured array. Its ``hash``/``lexid``
    fields are strided views, but the native lookup reads via raw ``.data``
    pointers for speed. Passing the strided views silently reads record padding
    and produces wrong lookups.
    """

    class DummyLexicon:
        pass

    lex = DummyLexicon()
    lex._hash_buckets = np.asarray([0, 2], dtype=np.uint64)
    lex._hash_entries = np.asarray(
        [(10, 1, 0), (20, 2, 0)],
        dtype=[("hash", np.uint64), ("lexid", np.uint32), ("pad", np.uint32)],
    )
    lex._offsets = np.asarray([0, 1, 2], dtype=np.uint64)
    lex._strings_view = memoryview(b"ab")
    lex._bucket_bits = 0

    assert not lex._hash_entries["hash"].flags.c_contiguous
    assert not lex._hash_entries["lexid"].flags.c_contiguous

    buckets, hashes, lexids, offsets, view, bucket_bits = predicates._fast_lex_arrays(lex)
    assert buckets.flags.c_contiguous
    assert hashes.flags.c_contiguous
    assert lexids.flags.c_contiguous
    assert offsets.flags.c_contiguous
    assert hashes.dtype == np.uint64
    assert lexids.dtype == np.uint32
    assert view is lex._strings_view
    assert bucket_bits == 0

    # Same lexicon returns cached dense arrays, avoiding per-query allocations.
    _, hashes2, lexids2, _, _, _ = predicates._fast_lex_arrays(lex)
    assert hashes2 is hashes
    assert lexids2 is lexids
