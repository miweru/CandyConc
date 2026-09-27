"""Every word rate shares one denominator: the analyst tokens.

keyness always normalised on ``analysierbare_groesse`` (tokens that pass
``is_analyst_token``), query_count, frequency_list, trend_analysis and the
``nach`` breakdown on all tokens including punctuation, markdown symbols and
line breaks. On the PING index that put the same 126 hits at 13.61 and 11.2
per million in one answer. These probes pin the shared denominator on the
real bench index and the honest fallback for index doubles without it.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import candyconc.core.query_runtime as qrt
from candyconc.analysis_defaults import analysierbare_groesse, is_analyst_token
from candyconc.candyconc_copilot.word_denominator import nenner, rate_je_million
from candyconc.core.corpus_index import CorpusIndex
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_TW = _load_real_tool_wrappers()


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH does not point to an index")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    from candyconc.services.backend import server as _server

    before = getattr(_server, "_INDEX", None)
    _server.set_default_index(idx)
    yield idx
    qrt._CORPUS_INDEX = None
    _server.set_default_index(before)
    idx.close()


def test_corpus_word_count_equals_analysable_size_of_the_frequency_list(index):
    frame = index.frequency_list(stopwords=None)
    rows = frame.to_dicts() if hasattr(frame, "to_dicts") else frame.to_dict("records")
    freq = {str(r["word"]): int(r["f"]) for r in rows if is_analyst_token(r["word"])}
    assert index.word_count() == analysierbare_groesse(freq)
    assert 0 < index.word_count() < index.token_count()


def test_docset_word_count_equals_keyness_target_tokens(index):
    a = _TW.create_docset_tool(filters={"split": "train"}, label="A")
    b = _TW.create_docset_tool(filters={"split": "test"}, label="B")
    result = _TW.keyness_tool(
        target_docset_id=a["docset_id"], reference_docset_id=b["docset_id"], min_freq=5
    )
    diagnostics = result["diagnostics"]
    assert a["word_count"] == diagnostics["target_tokens"]
    assert b["word_count"] == diagnostics["reference_tokens"]
    assert a["token_count"] == diagnostics["target_tokens_roh"]


def test_per_document_counts_add_up_to_the_word_count(index):
    per_doc = index.analysetoken_je_dokument()
    ids = np.arange(per_doc.size, dtype=np.uint32)
    assert int(per_doc.sum()) == index.word_count()
    assert index.docset_word_count(ids) == index.word_count()
    assert index.docset_word_count(np.zeros(0, dtype=np.uint32)) == 0
    assert bool((per_doc >= 0).all())


def test_breakdown_rows_and_their_dispersion_use_the_word_denominator(index):
    result = _TW.query_count_tool("und", nach="split")
    assert len(result["rows"]) >= 2
    for row in result["rows"]:
        from candyconc.services.backend import server as _server

        ids = np.asarray(_server._doc_ids_from_meta(index, {"split": row["wert"]}), dtype=np.uint32)
        assert row["tokens"] == index.docset_word_count(ids)
        assert row["tokens_raw"] == index.docset_token_count(ids)
        assert row["per_million"] == rate_je_million(row["total"], row["tokens"])
    t = [r["tokens"] for r in result["rows"]]
    n = [r["total"] for r in result["rows"]]
    dp = 0.5 * sum(abs(ti / sum(t) - ni / sum(n)) for ti, ni in zip(t, n))
    assert result["dp_nach"] == round(dp, 4)


def test_query_count_names_both_sizes_and_uses_the_words(index):
    result = _TW.query_count_tool("und")
    assert result["denominator_tokens"] == index.word_count()
    assert result["denominator_tokens_raw"] == index.token_count()
    assert result["per_million"] == rate_je_million(result["total"], index.word_count())


class _IndexWithoutWordCounts:
    """An index double that only knows raw sizes, as many test doubles do."""

    def token_count(self):
        return 1000

    def docset_token_count(self, doc_ids):
        return 10 * len(doc_ids)


def test_an_index_without_word_counts_says_it_rates_on_raw_tokens():
    corpus = nenner(_IndexWithoutWordCounts(), None)
    assert corpus == {"woerter": 1000, "roh": 1000, "quelle": "corpus_index.token_count"}
    docset = nenner(_IndexWithoutWordCounts(), [1, 2])
    assert docset["quelle"] == "corpus_index.docset_token_count"
    assert docset["woerter"] == docset["roh"] == 20


def test_rate_keeps_two_significant_digits_below_one():
    assert rate_je_million(3, 130_843_366) == 0.023
    assert rate_je_million(0, 100) == 0.0
    assert rate_je_million(5, 0) is None
