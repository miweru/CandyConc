"""Partially folded CQL reports how many values use case-insensitive matching."""

from __future__ import annotations

import os

import pytest
from jsonschema import validate

from candyconc.candyconc_copilot.analysis_grounding import _analysis_provenance_lines
from candyconc.candyconc_copilot.grounding_evidence import build_grounding_surface
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_KETTE = '[word="nicht"%c] [word="nur"] []{0,8} [word="sondern"%c] [word="auch"]'


def test_die_kette_des_laufs_meldet_zwei_von_vier():
    herkunft = _TW._query_method_provenance(_KETTE, case_insensitive=True)
    assert herkunft["case_insensitive"] is False
    assert herkunft["faltung_teilweise"] == "%c an 2 von 4 Werten"


@pytest.mark.parametrize("abfrage, gefaltet", [
    ('[word="und"%c] [word="auch"%c]', True),
    ('within(<doc>, [word="und"%c] [word="auch"%c])', True),
    ('[word="und"] [word="auch"]', False),
    ("und", True),
])
def test_ganz_oder_gar_nicht_gefaltet_braucht_kein_zusatzfeld(abfrage, gefaltet):
    herkunft = _TW._query_method_provenance(abfrage, case_insensitive=True)
    assert herkunft["case_insensitive"] is gefaltet
    assert "faltung_teilweise" not in herkunft


@pytest.mark.parametrize("abfrage", [
    'where(model="gpt-5.4-mini", [word="nicht"%c] [word="nur"%c])',
    '[lemma in {"nicht","auch"}%c]',
])
def test_gezaehlt_wird_was_die_suchmaschine_faltet(abfrage):
    # Der Metadatenwert in where() ist keine Tokenbedingung, eine Wertmenge
    # traegt %c hinter der Klammer. Die Textregel sah beides als ungefaltet.
    herkunft = _TW._query_method_provenance(abfrage, case_insensitive=False)
    assert herkunft["case_insensitive"] is True
    assert "faltung_teilweise" not in herkunft


def _posten(werkzeug: str, ausgabe: dict):
    return make_evidence_item(
        item_id="ev1", tool=werkzeug, tool_call_id="c", query={"query": _KETTE},
        output=ausgabe, analysis_family="gebrauch_kwic",
    )


def test_steckbrief_und_belegflaeche_sagen_teilweise():
    ausgabe = {
        "status": "success", "query": _KETTE, "total": 46399,
        "corpus_tokens": 142044149, "denominator_tokens": 142044149,
        "denominator_scope": "corpus", "per_million": 326.7,
        "scope": {"corpus_id": "ping", "level": "corpus"},
        **_TW._query_method_provenance(_KETTE, case_insensitive=True),
    }
    posten = _posten("query_count", ausgabe)
    zeile = _analysis_provenance_lines([posten])[0]
    assert "Groß-/Kleinschreibung ignoriert: teilweise (%c an 2 von 4 Werten)" in zeile, zeile
    assert "ignoriert: nein" not in zeile
    assert "faltung_teilweise=%c an 2 von 4 Werten" in build_grounding_surface(posten.raw_surface)


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


def test_das_feld_steht_im_antwortschema_beider_werkzeuge(index):
    # Die MCP-Naht prueft jede Antwort gegen ihr Schema (additionalProperties
    # false). Ein undeklariertes Feld war dort schon einmal HTTP 500.
    abfrage = '[word="und"%c] [word="die"]'
    zaehlung = _TW.query_count_tool(abfrage)
    zeilen = _TW.run_cqlf_query_tool(abfrage, limit=3)
    for ergebnis, schema in ((zaehlung, _TW.QUERY_COUNT_RESPONSE), (zeilen, _TW.RUN_CQLF_RESPONSE)):
        assert ergebnis["faltung_teilweise"] == "%c an 1 von 2 Werten"
        validate(ergebnis, schema)
