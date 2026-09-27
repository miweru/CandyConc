"""query_count names where its hits lie and how precise its rate is (Regression and 119).

Muse cycle 10 on 0395a9317d: an answer estimated "about 440 independent
places" as 5,921 hits divided by 13 versions, while the hits lie in 5,374
documents and 3,096 source texts, and no tool had said so. Two answers put
Wilson and normal intervals on rates and shares that treat every hit as
independent although hits cluster in documents and source texts.

query_count now reports documents and source texts with hits and a
cluster-robust 95 % interval for per_million on the same denominator, and
per ``nach`` row also the share of the total with its interval. The method is
a ratio estimator with linearised cluster variance, deterministic.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
import pytest

import candyconc.core.query_runtime as qrt
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
from candyconc.candyconc_copilot.hit_spread import Z95, _verhaeltnis_ci, anteil_je_zeile
from candyconc.core.corpus_index import CorpusIndex
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_TW = _load_real_tool_wrappers()
NEW_FIELDS = ("docs_with_hits", "source_texts_with_hits", "per_million_ci", "ci_cluster")


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


def _hits_per_doc(idx, query):
    from candyconc.services.backend import server as _server

    positions = np.asarray(
        _server._dispersion_positions_for_term(idx, query, docset_mask=None), dtype=np.int64)
    starts = np.asarray(idx.fast_index.boundaries.document._positions, dtype=np.int64)
    docs = np.searchsorted(starts, positions, side="right") - 1
    return np.bincount(docs, minlength=starts.size).astype(float)


def test_count_reports_documents_with_hits_and_a_cluster_interval(index):
    result = _TW.query_count_tool("und")
    for field in NEW_FIELDS:
        assert field in result, field
    y = _hits_per_doc(index, "und")
    assert result["docs_with_hits"] == int((y > 0).sum())
    assert result["docs_with_hits"] < result["total"]
    # Independent recomputation with the bench index's clusters (one document
    # per source text there): ratio estimator, linearised variance.
    n = index.analysetoken_je_dokument().astype(float)
    clusters = int((n > 0).sum())
    rate = y.sum() / n.sum()
    var = clusters / (clusters - 1) * ((y - rate * n) ** 2).sum() / n.sum() ** 2
    half = Z95 * math.sqrt(var)
    assert result["per_million_ci"] == [round((rate - half) * 1e6, 1), round((rate + half) * 1e6, 1)]
    low, high = result["per_million_ci"]
    assert low < result["per_million"] < high


def test_breakdown_rows_report_hits_documents_and_shares(index):
    result = _TW.query_count_tool("und", nach="split")
    rows = result["rows"]
    assert sum(r["docs_with_hits"] for r in rows) == result["docs_with_hits"]
    assert sum(r["total"] for r in rows) == result["total"]
    assert sum(r["share"] for r in rows) == pytest.approx(1.0, abs=1e-3)
    for row in rows:
        assert row["docs_with_hits"] <= row["docs"]
        low, high = row["share_ci"]
        assert low <= row["share"] <= high
        low, high = row["per_million_ci"]
        assert low <= row["per_million"] <= high


def test_no_interval_when_the_positions_do_not_give_the_count(index):
    """Case-sensitive plain counting has no position twin, so nothing is claimed."""
    result = _TW.query_count_tool("Und", case_insensitive=False)
    for field in NEW_FIELDS:
        assert field not in result, field


def test_clustering_widens_the_interval_when_hits_share_a_source_text():
    # Six documents of 100 words, three source texts of two versions each.
    # The hits sit in the versions of one source text.
    y = np.array([10.0, 10.0, 0.0, 0.0, 0.0, 0.0])
    n = np.array([100.0] * 6)
    by_document = _verhaeltnis_ci(y, n, 6)
    by_source = _verhaeltnis_ci(np.array([20.0, 0.0, 0.0]), np.array([200.0] * 3), 3)
    assert by_document[0] == by_source[0] == pytest.approx(20 / 600)
    assert (by_source[2] - by_source[1]) > (by_document[2] - by_document[1])


def test_share_interval_is_the_ratio_estimator_over_clusters():
    whole = np.array([5.0, 3.0, 2.0, 0.0])
    row = np.array([5.0, 0.0, 2.0, 0.0])
    codes = np.array([0, 1, 2, 3])
    (result,) = anteil_je_zeile([row], codes, whole)
    p = 7 / 10
    var = 4 / 3 * ((row - p * whole) ** 2).sum() / 100
    half = Z95 * math.sqrt(var)
    assert result == {"share": 0.7,
                      "share_ci": [round(max(0.0, p - half), 4), round(min(1.0, p + half), 4)]}


def test_new_fields_reach_the_evidence_surface():
    output = {
        "status": "success", "query": "Herausforderung", "total": 5921,
        "corpus_tokens": 142044149, "denominator_tokens": 114695183,
        "denominator_tokens_raw": 142044149, "denominator_scope": "corpus",
        "denominator_source": "corpus_index.word_count", "per_million": 51.6,
        "query_mode": "cqlf", "attribute": "word", "case_insensitive": True,
        "scope": {"corpus_id": "ping", "level": "corpus"},
        "docs_with_hits": 5374, "source_texts_with_hits": 3096,
        "per_million_ci": [49.1, 54.2], "ci_cluster": "origin_id",
    }
    item = make_evidence_item(
        item_id="E_query_count_1", tool="query_count", tool_call_id="c1",
        query=json.dumps({"query": "Herausforderung"}), output=output,
        analysis_family="frequency",
    )
    for field in NEW_FIELDS:
        assert item.raw_surface.get(field) == output[field], field
        assert any(line.startswith(f"{field}=") for line in item.grounding_surface), field


def test_package_rows_keep_value_and_count_in_front():
    """Five new row fields pushed wert and total out of the cut at eight keys."""
    from candyconc.candyconc_copilot.interpretation_synthesis import evidenz_paket_text

    row = {"wert": "news", "total": 5325, "docs": 65000, "tokens": 26242270,
           "tokens_raw": 31267499, "per_million": 202.9, "docs_with_hits": 2754,
           "source_texts_with_hits": 496, "per_million_ci": [177.5, 228.4],
           "share": 0.7244, "share_ci": [0.6787, 0.7701]}
    output = {"status": "success", "query": "Fußball", "total": 7351,
              "denominator_tokens": 114695183, "per_million": 64.1, "nach": "register",
              "rows": [row]}
    item = make_evidence_item(
        item_id="E_query_count_1", tool="query_count", tool_call_id="c1",
        query=json.dumps({"query": "Fußball", "nach": "register"}), output=output,
        analysis_family="frequency",
    )
    text = evidenz_paket_text([item])
    # Die knappe Form (seit 107 Vorgabe) fuehrt die Zeile als „Zeile 0: wert=news
    # total=5325 …“, die ausfuehrliche als „rows[0] {'wert': 'news', …}“.
    zeile = next(line for line in text.splitlines() if "rows[0]" in line or "Zeile 0:" in line)
    assert zeile.index("wert") < zeile.index("5325") < zeile.index("per_million_ci")
    assert "share_ci" in zeile
