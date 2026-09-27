"""A KWIC call without sampling arguments reports its default random sample.

The default must not return only the beginning of the index."""

from __future__ import annotations

import os

import pytest
from jsonschema import validate

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


def _positionen(ergebnis):
    return [zeile["pos"] for zeile in ergebnis["rows"]]


def test_ohne_angaben_kommt_eine_gemeldete_stichprobe_statt_des_kopfs(index):
    kopf = _TW.run_cqlf_query_tool("und", limit=5, sort_by="position")
    vorgabe = _TW.run_cqlf_query_tool("und", limit=5)
    assert "sample" not in kopf
    stichprobe = vorgabe["sample"]
    assert (stichprobe["requested"], stichprobe["drawn"], stichprobe["population"]) == (5, 5, 919)
    assert stichprobe["population_partial"] is False
    # total bleibt die volle Trefferzahl, die Vorschau aendert sie nicht.
    assert vorgabe["total"] == kopf["total"] == 919
    assert vorgabe["truncated"] is True
    assert _positionen(vorgabe) != _positionen(kopf), "wieder der Indexkopf"
    # Dieselbe Naht wie das ausdrueckliche sample: der gemeldete Seed zieht dieselben Zeilen.
    wiederholt = _TW.run_cqlf_query_tool("und", limit=5, sample=5, seed=stichprobe["seed"])
    assert _positionen(vorgabe) == _positionen(wiederholt)
    validate(vorgabe, _TW.RUN_CQLF_RESPONSE)


def test_verschiedene_abfragen_ziehen_nicht_dieselben_quantile(index):
    # A fixed seed would select the same quantiles in every hit list.
    # Query-specific seeds vary the selected positions.
    seeds = {q: _TW.run_cqlf_query_tool(q, limit=5)["sample"]["seed"] for q in ("und", "die", '[pos="NOUN"]')}
    assert len(set(seeds.values())) == 3, seeds
    assert seeds["und"] == _TW.run_cqlf_query_tool("und", limit=5)["sample"]["seed"]


@pytest.mark.parametrize("wahl", [{"seed": 42}, {"sort_by": "position"}])
def test_eine_ausdrueckliche_wahl_bleibt_wie_sie_war(index, wahl):
    ergebnis = _TW.run_cqlf_query_tool("und", limit=5, **wahl)
    assert "sample" not in ergebnis
    assert ergebnis["total"] == 919


def test_sort_by_sortiert_eine_ziehung(index):
    """Hier stand sort_by="node" unter den Wahlen, die den Kopf behalten. Genau
    das war Regression: sortiert wurden die ersten limit Treffer nach
    Korpusposition. Jetzt wird gezogen und die Ziehung sortiert."""
    ergebnis = _TW.run_cqlf_query_tool("und", limit=5, sort_by="node")
    assert "sample" in ergebnis
    assert ergebnis["total"] == 919


def test_bis_limit_treffer_kommen_alle_in_indexreihenfolge(index):
    ergebnis = _TW.run_cqlf_query_tool("Invasoren")
    assert "sample" not in ergebnis
    assert ergebnis["total"] == len(ergebnis["rows"]) == 9
    assert _positionen(ergebnis) == sorted(_positionen(ergebnis))


def test_ohne_ziehbare_stichprobe_bleibt_der_kopf_ohne_sample_block():
    # Ein Korpus ohne Fast-Index-Pfad: die REST-Naht lehnt die Ziehung ab. Dann
    # bleibt der Kopf, und ohne sample-Block ist er als Kopf erkennbar.
    from candyconc.candyconc_copilot.analysis import stichprobe_statt_indexkopf
    from candyconc.candyconc_copilot.tool_errors import ToolInputError

    kopf = {"status": "success", "rows": [{"pos": 1}], "total": 9, "truncated": True, "limit": 1}

    def _nicht_ziehbar(**_wahl):
        raise ToolInputError("Zufallsstichprobe (sample/seed) erfordert den Fast-Index-Pfad")

    assert stichprobe_statt_indexkopf(
        kopf, sample=None, seed=None, sort_by=None, ziehen=_nicht_ziehbar, seed_vorgabe=7) is kopf


def test_der_steckbrief_nennt_die_stichprobe(index):
    from candyconc.candyconc_copilot.analysis_grounding import _analysis_provenance_lines
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    ergebnis = _TW.run_cqlf_query_tool("und", limit=5)
    posten = make_evidence_item(item_id="ev1", tool="run_cqlf_query", tool_call_id="c",
                                query={"query": "und", "limit": 5}, output=ergebnis,
                                analysis_family="gebrauch_kwic")
    zeile = _analysis_provenance_lines([posten])[0]
    assert f"Zufallsstichprobe von 5 aus 919 Treffern, Seed {ergebnis['sample']['seed']}" in zeile, zeile
    assert "begrenzter KWIC-Ausschnitt" not in zeile
