"""Regression tests for D3 — case-insensitive plain search + NFKC canonicalization.

Two correctness properties on the REAL bench Fast Index:

1. CASE-INSENSITIVE plain term (German convention, default True):
   ``term_positions('geht')`` must return the union of every case variant
   ('geht' + 'Geht' + 'GEHT' ...), i.e. exactly the casefold id-set, and equal
   the lower-cased and capitalised lookups merged.

2. NFKC canonicalization in the count path:
   an NFD-decomposed umlaut query (e.g. 'schön' written as 's c h o + combining
   diaeresis n') must canonicalize to the NFC form stored in the index, so the
   parsed-query position count equals the count for the composed term — and the
   number of matched positions equals the number of rendered KWIC rows.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import numpy as np
import pytest

from candyconc.core.corpus_index import CorpusIndex, _with_ignorecase
from candyconc.domain.query_parser import canonicalize_term, parse_query, Term
from candyconc.domain import query_eval

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

_real_index = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)


@pytest.fixture(scope="module")
def index() -> CorpusIndex:
    return CorpusIndex(Path(INDEX_PATH))


# --------------------------------------------------------------------------- #
# Pure unit tests (no index)
# --------------------------------------------------------------------------- #


def test_canonicalize_term_nfkc_composes_umlaut() -> None:
    nfd = "sch" + "o" + "̈" + "n"  # schön, decomposed
    nfc = unicodedata.normalize("NFC", "schön")
    assert nfd != nfc  # genuinely different byte sequences
    assert canonicalize_term(nfd) == nfc
    # Idempotent.
    assert canonicalize_term(canonicalize_term(nfd)) == nfc


def test_parser_canonicalizes_term_value() -> None:
    nfd = "Caf" + "e" + "́"  # Café decomposed
    node = parse_query(nfd)
    assert isinstance(node, Term)
    assert node.value == unicodedata.normalize("NFC", "Café")


def test_with_ignorecase_is_idempotent_and_valid() -> None:
    import re

    for pat in ["abc", "(?i)abc", "(?s)abc", "(?ms)abc"]:
        out = _with_ignorecase(pat)
        compiled = re.compile(out)  # must not raise
        assert compiled.flags & re.IGNORECASE
    # Already-ignorecase patterns are returned unchanged.
    assert _with_ignorecase("(?i)abc") == "(?i)abc"


# --------------------------------------------------------------------------- #
# Case-insensitive plain search on the real index
# --------------------------------------------------------------------------- #


@_real_index
def test_case_insensitive_term_unions_all_variants(index: CorpusIndex) -> None:
    fast = index.fast_index
    n_lower = int(fast.term_positions("geht", attr="word").size)
    n_title = int(fast.term_positions("Geht", attr="word").size)
    n_upper = int(fast.term_positions("GEHT", attr="word").size)
    assert n_lower > 0 and n_title > 0  # the index must actually have variants

    ci = index.term_positions("geht", case_insensitive=True)
    assert int(ci.size) == n_lower + n_title + n_upper
    # CI search is case-symmetric: querying any casing gives the same set.
    ci_from_title = index.term_positions("Geht", case_insensitive=True)
    np.testing.assert_array_equal(np.sort(ci), np.sort(ci_from_title))


@_real_index
def test_case_insensitive_is_superset_of_exact(index: CorpusIndex) -> None:
    exact = index.term_positions("geht", case_insensitive=False)
    ci = index.term_positions("geht", case_insensitive=True)
    assert int(ci.size) >= int(exact.size)
    assert set(exact.tolist()).issubset(set(ci.tolist()))


@_real_index
def test_case_insensitive_default_is_true(index: CorpusIndex) -> None:
    default = index.term_positions("die")
    ci = index.term_positions("die", case_insensitive=True)
    np.testing.assert_array_equal(np.sort(default), np.sort(ci))


# --------------------------------------------------------------------------- #
# NFKC canonicalization: count == rows, and NFD == NFC
# --------------------------------------------------------------------------- #


@_real_index
def test_nfd_query_matches_nfc_count(index: CorpusIndex) -> None:
    nfc = "schön"
    nfd = "sch" + "o" + "̈" + "n"
    pos_nfc = query_eval._eval(parse_query(nfc), index)
    pos_nfd = query_eval._eval(parse_query(nfd), index)
    assert int(pos_nfc.size) > 0
    np.testing.assert_array_equal(np.sort(pos_nfc), np.sort(pos_nfd))


@_real_index
def test_nfkc_count_equals_rendered_row_count(index: CorpusIndex) -> None:
    """The matched-position count must equal the number of KWIC rows produced —
    no positions silently dropped or duplicated by a normalization mismatch
    between the count path and the row path."""
    nfd = "sch" + "o" + "̈" + "n"
    node = parse_query(nfd)
    positions = query_eval._eval(node, index)
    n_positions = int(positions.size)
    assert n_positions > 0

    rows = list(query_eval.evaluate(node, index, ctx=5, query=nfd, use_cache=False))
    assert len(rows) == n_positions
