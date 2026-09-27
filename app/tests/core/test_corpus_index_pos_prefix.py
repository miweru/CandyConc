"""Regression test: ``pos_prefix`` that matches no POS tag must yield empty.

Previously, when a requested ``pos_prefix`` matched no tag in the POS lexicon,
``frequency_counts_docset`` fell through to the UNFILTERED count -- so keyness
and contrast would show the entire vocabulary mislabeled as that one POS class.
The fix returns an empty result for a no-match prefix while still running the
unfiltered branch only when no prefix was requested.

Uses the real bench index (CANDYCONC_INDEX_PATH); no mocks.
"""

from __future__ import annotations

import os

import pytest

from candyconc.core.corpus_index import CorpusIndex

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def corpus_index() -> CorpusIndex:
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    return CorpusIndex(_INDEX_PATH)


def test_pos_prefix_no_match_returns_empty_not_full(corpus_index: CorpusIndex) -> None:
    n_docs = len(corpus_index.fast_index.doc_metadata)
    doc_ids = list(range(min(50, n_docs)))

    full_ids, full_counts = corpus_index.frequency_counts_docset(doc_ids)
    assert full_ids.size > 0, "fixture corpus is empty"

    # A real UD POS prefix yields a non-empty *subset* of the full vocabulary.
    noun_ids, noun_counts = corpus_index.frequency_counts_docset(
        doc_ids, pos_prefix="NOUN"
    )
    assert noun_ids.size > 0
    assert noun_ids.size < full_ids.size

    # A bogus prefix matches no POS tag -> result MUST be empty (not the full
    # vocabulary mislabeled as this class).
    bogus_ids, bogus_counts = corpus_index.frequency_counts_docset(
        doc_ids, pos_prefix="ZZZ_NOT_A_TAG"
    )
    assert bogus_ids.size == 0
    assert bogus_counts.size == 0


def _pos_count(df, tag: str) -> int:
    row = df.filter(df["word"] == tag)
    return int(row["f"][0]) if row.height else 0


def test_pos_frequency_excludes_lbr_sentinel(corpus_index: CorpusIndex) -> None:
    """FIX-C: the index-only ``|LBR|`` sentinel must not be counted as a POS tag.

    On the frozen bench index ``[pos="NOUN"]`` is canonically 9740 and
    ``[pos="VERB"]`` 4781 everywhere (query/count, dispersion). The POS-frequency
    surface used to leak the sentinel's per-tag occurrences (9741 NOUN, 4796 VERB).
    Both the whole-corpus path (``frequency_list(attr="pos")``) and the docset path
    (``frequency_list_docset(attr="pos")``) must now drop it through the shared
    sentinel seam.
    """
    import numpy as np

    whole = corpus_index.frequency_list(attr="pos")
    assert _pos_count(whole, "NOUN") == 9740
    assert _pos_count(whole, "VERB") == 4781

    n_docs = len(corpus_index.fast_index.doc_metadata)
    all_ids = np.arange(n_docs, dtype=np.uint32)
    docset = corpus_index.frequency_list_docset(all_ids, attr="pos")
    # The whole-corpus and all-docs paths must agree, both sentinel-free.
    assert _pos_count(docset, "NOUN") == 9740
    assert _pos_count(docset, "VERB") == 4781
