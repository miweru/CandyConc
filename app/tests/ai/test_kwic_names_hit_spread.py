"""KWIC results report hit-bearing documents and source texts consistently with counts."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def tw():
    from candyconc.core import query_runtime as qrt
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.services.backend import server as _server
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    pfad = os.environ.get("CANDYCONC_INDEX_PATH")
    if not pfad or not os.path.isdir(pfad):
        pytest.skip("CANDYCONC_INDEX_PATH zeigt nicht auf einen Index")
    idx = CorpusIndex(pfad)
    vorher_qrt, vorher_server = qrt._CORPUS_INDEX, getattr(_server, "_INDEX", None)
    qrt._CORPUS_INDEX = idx
    _server.set_default_index(idx)
    try:
        yield _load_real_tool_wrappers()
    finally:
        qrt._CORPUS_INDEX = vorher_qrt
        _server.set_default_index(vorher_server)


FELDER = ("docs_with_hits", "source_texts_with_hits")


@pytest.mark.parametrize("abfrage", ["und", '[word="die"%c] [word="Menschen"%c]'])
def test_kwic_nennt_dieselbe_streuung_wie_die_zaehlung(tw, abfrage):
    kwic = tw.run_cqlf_query_tool(query=abfrage, limit=5)
    zaehlung = tw.query_count_tool(abfrage)
    assert kwic["total"] == zaehlung["total"] > 0
    for feld in FELDER:
        assert feld in kwic, kwic.keys()
        assert kwic[feld] == zaehlung[feld], (feld, kwic[feld], zaehlung[feld])
    assert kwic["source_texts_with_hits"] <= kwic["docs_with_hits"] <= kwic["total"]


def test_auch_die_gezogene_stichprobe_nennt_die_streuung(tw):
    kwic = tw.run_cqlf_query_tool(query="und", limit=5, sample=5, seed=7)
    zaehlung = tw.query_count_tool("und")
    assert [kwic.get(f) for f in FELDER] == [zaehlung[f] for f in FELDER]


def test_im_teilkorpus_gilt_die_streuung_des_teilkorpus(tw):
    ds = tw.create_docset_tool(filters={"split": "test"}, label="test-split")
    kwic = tw.run_cqlf_query_tool(query="und", docset_id=ds["docset_id"], limit=5)
    zaehlung = tw.query_count_tool("und", docset_id=ds["docset_id"])
    assert [kwic.get(f) for f in FELDER] == [zaehlung[f] for f in FELDER]
    assert kwic["docs_with_hits"] <= ds["doc_count"]


def test_schema_und_kern_fuehren_die_felder(tw):
    from candyconc.candyconc_copilot.prompt_layout import build_static_core

    oben = tw.RUN_CQLF_RESPONSE["properties"]
    for feld in FELDER:
        assert "integer" in oben[feld]["type"], oben[feld]
    assert "total, docs_with_hits?, source_texts_with_hits?, truncated" in " ".join(build_static_core().split())
