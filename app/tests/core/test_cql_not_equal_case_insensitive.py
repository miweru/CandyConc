"""``[attr!="x"%c]``: a token whose case-folded form differs from ``x``.

Before this fix the engine raised a plain ``ValueError`` ("Case-insensitive
'!=' ... wird noch nicht unterstützt") that no HTTP classifier knew, so
``cql:[word!="freedom"%c]`` ended at ``/api/v1/query`` with HTTP 500. A
case-insensitive inequality is the conjunction of one inequality per lexicon
entry whose case-folded form matches, which the clause compiler can express
with the existing ``!=`` operator.

A negated regular expression stays unsupported (its id set can be the whole
lexicon). It must fail with the classified "Regex mit '!='" message, which the
query routes answer with 400, also when ``%c`` is set.
"""

from __future__ import annotations

import numpy as np
import pytest

from cqlhpc import QueryEngine
from cqlhpc.corpus import Corpus, build_postings_from_tokens
from cqlhpc.lexicon import Lexicon

from candyconc.services.backend.query_count import _classify_query_runtime_error


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


WORDS = ["Freedom", "of", "freedom", "and", "FREEDOM", "peace", "of", "free"]


def _starts(query: str) -> list[int]:
    engine = QueryEngine(_make_corpus(WORDS))
    return sorted(m.start for m in engine.search(query))


def test_not_equal_case_insensitive_excludes_every_casing() -> None:
    assert _starts('[word!="freedom"%c]') == [1, 3, 5, 6, 7]


def test_not_equal_case_sensitive_keeps_other_casings() -> None:
    assert _starts('[word!="freedom"]') == [0, 1, 3, 4, 5, 6, 7]


def test_not_equal_case_insensitive_in_a_sequence() -> None:
    # "X of" where X is not any casing of freedom: only "peace of".
    assert _starts('[word!="FREEDOM"%c] [word="of"]') == [5]


def test_not_equal_case_insensitive_with_absent_value_matches_all() -> None:
    assert _starts('[word!="liberty"%c]') == list(range(len(WORDS)))


def test_not_equal_case_insensitive_combined_with_positive_condition() -> None:
    assert _starts('[word="of" & word!="OF"%c]') == []
    assert _starts('[word="free" & word!="freedom"%c]') == [7]


@pytest.mark.parametrize("query", ['[word!="free.*"%c]', '[word!="free.*"]'])
def test_negated_regex_is_a_classified_user_error(query: str) -> None:
    engine = QueryEngine(_make_corpus(WORDS))
    with pytest.raises(ValueError) as excinfo:
        engine.search(query)
    mapped = _classify_query_runtime_error(excinfo.value)
    assert mapped is not None and mapped.status_code == 400
