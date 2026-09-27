"""NFA DoS-budget regression tests for the CQLHPC engine (r7 D1a).

The live abuse repro ``([]{200}){164}`` (and its smaller siblings) used to do
one of two bad things during NFA construction:

* hang the worker for many seconds while the Thompson build expanded ~32 000
  token instances into an O(states^2) epsilon-closure pass, or
* crash with a raw ``OverflowError`` when the predicate count overflowed the
  int16 edge tables.

Both are now rejected *fast* (well under 100 ms) as a ``ParseError`` -- a
``ValueError`` subclass whose German "Muster zu komplex" message classifies as
an HTTP 400 user error, never a 500. The cheap parse-time nested-quantifier
expansion estimate catches the explosive patterns before any NFA work starts; a
``compile_nfa`` state/predicate budget backstops any AST that bypasses the
parser. ``edge_pred``/``start_pred_ids`` are int32, so the int16 overflow class
is gone entirely.

No mocks: tests run against a small real Fast-Index-shaped corpus.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from cqlhpc import QueryEngine
from cqlhpc.ast import Seq, Tok, TokenClause
from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.lexicon import Lexicon
from cqlhpc.nfa import compile_nfa
from cqlhpc.parser import ParseError, parse_cql

# Anything above this wall-clock budget means the DoS guard failed to short the
# expensive build. The guards reject in well under a millisecond; the old
# unguarded hangs were multi-second to 24 s. A 1 s ceiling keeps that signal
# (anything anywhere near the regressed behaviour is orders of magnitude over it)
# while staying robust to load spikes / GC pauses when the full suite runs under
# heavy parallelism in CI — a 100 ms ceiling false-reds purely on machine load.
_FAST_LIMIT_SEC = 1.0


def _make_corpus(words: list[str]) -> Corpus:
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


@pytest.mark.parametrize(
    "query",
    [
        "([]{200}){164}",  # the live repro (would OverflowError on int16)
        "([]{150}){150}",  # would hang ~9 s
        "([]{50}){50}",    # 2500 > 2000 budget
        '([word="alpha"]{200}){164}',  # concrete inner clause, same blow-up
    ],
)
def test_nested_quantifier_dos_rejected_fast(query: str) -> None:
    """Explosive nested quantifiers raise ParseError fast, never hang/overflow."""
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    t0 = time.perf_counter()
    with pytest.raises(ParseError) as exc:
        engine.search(query)
    elapsed = time.perf_counter() - t0
    assert elapsed < _FAST_LIMIT_SEC, f"{query} took {elapsed:.3f}s (DoS guard slow)"
    # ParseError subclasses ValueError so the sync /query handler catches it.
    assert isinstance(exc.value, ValueError)
    # German message that the user-error classifier routes to HTTP 400.
    assert "Muster zu komplex" in str(exc.value)


def test_parse_level_rejection_is_independent_of_corpus() -> None:
    """The nested-quantifier estimate fires at parse time, before any corpus or
    NFA work -- ``parse_cql`` alone rejects the explosive pattern."""
    t0 = time.perf_counter()
    with pytest.raises(ParseError, match="Muster zu komplex"):
        parse_cql("([]{200}){164}")
    assert time.perf_counter() - t0 < _FAST_LIMIT_SEC


def test_no_overflow_error_class() -> None:
    """The old int16 edge-table OverflowError must be gone: the repro raises a
    ValueError (ParseError), not an OverflowError."""
    corpus = _make_corpus(["alpha", "beta"])
    engine = QueryEngine(corpus)
    with pytest.raises(ParseError):
        engine.search("([]{200}){164}")
    # And explicitly: it is NOT an OverflowError.
    try:
        engine.search("([]{200}){164}")
    except OverflowError:  # pragma: no cover - would mean the fix regressed
        pytest.fail("raw OverflowError leaked (int16 edge table not widened)")
    except ParseError:
        pass


def test_legitimate_large_patterns_still_compile() -> None:
    """Patterns within the budget must still work -- the guard is not over-eager.

    A single ``{256}`` (the max single-quantifier repeat) and a modest nested
    product stay under the expansion ceiling and execute normally.
    """
    corpus = _make_corpus(["alpha", "beta", "alpha"])
    engine = QueryEngine(corpus)
    # single large quantifier: 256 instances, well under the 2000 budget.
    engine.search("[]{256}")  # must not raise
    # modest nesting: 50 * 10 = 500 instances.
    engine.search("([]{50}){10}")  # must not raise


def test_compile_nfa_state_budget_backstops_handbuilt_ast() -> None:
    """A hand-built AST that bypasses the parser still hits the compile_nfa
    state/predicate budget and raises ParseError fast (defence in depth)."""
    corpus = _make_corpus(["alpha", "beta"])
    # 3000 empty tokens -> 6000 states / 3000 preds, both over the default caps.
    node = Seq(parts=tuple(Tok(clause=TokenClause(conds=())) for _ in range(3000)))
    t0 = time.perf_counter()
    with pytest.raises(ParseError, match="Muster zu komplex") as exc:
        compile_nfa(node, corpus)
    assert time.perf_counter() - t0 < _FAST_LIMIT_SEC
    assert isinstance(exc.value, ValueError)
