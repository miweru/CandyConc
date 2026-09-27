"""An unsupported plain word sequence suggests an executable CQL form."""

from __future__ import annotations

import os
import re

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from candyconc.domain.query_parser import parse_query
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_FOLGE = re.compile(r'\[word="[^"]+" %c\](?: \[word="[^"]+" %c\])+')


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


def _meldungen(abfrage: str) -> tuple[str, str]:
    with pytest.raises(_TW.ToolInputError) as zaehlung:
        _TW.query_count_tool(abfrage)
    with pytest.raises(_TW.ToolInputError) as zeilen:
        _TW.run_cqlf_query_tool(abfrage, limit=5)
    return str(zaehlung.value), str(zeilen.value)


def test_beide_werkzeuge_nennen_dieselbe_zaehlende_folge(index):
    zaehlung, zeilen = _meldungen("es ist wichtig")
    assert zaehlung.startswith("Unexpected token: ist"), zaehlung
    form = '[word="es" %c] [word="ist" %c] [word="wichtig" %c]'
    assert form in zaehlung, zaehlung
    # run_cqlf_query stellt nur "Query Parser Fehler: " voran.
    assert zeilen == "Query Parser Fehler: " + zaehlung


def test_die_genannte_form_zaehlt(index):
    zaehlung, _ = _meldungen("es ist")
    formen = _FOLGE.findall(zaehlung)
    assert len(formen) == 1, zaehlung
    form = formen[0]
    assert _TW.query_count_tool(form)["total"] == 29
    assert _TW.run_cqlf_query_tool(form, limit=1)["total"] == 29
    # Die Meldung sagt: ohne %c mit Gross- und Kleinschreibung.
    assert _TW.query_count_tool(form.replace(" %c]", "]"))["total"] == 6


@pytest.mark.parametrize("abfrage", [
    "Merkel (CDU)",   # Klammer, keine reine Wortfolge
    "es ist*",        # Muster, die Zelle traefe nicht dieselbe Form
    "word=es ist",    # Attributschreibweise
    "Dr. Merkel",     # Punkt ist in CQL ein Metazeichen
])
def test_ohne_reine_wortfolge_bleibt_die_meldung(abfrage):
    with pytest.raises(ValueError) as fehler:
        parse_query(abfrage)
    assert "Wortfolge" not in str(fehler.value), str(fehler.value)


def test_der_senkrechte_strich_behaelt_seinen_hinweis():
    with pytest.raises(ValueError) as fehler:
        parse_query("und | oder")
    meldung = str(fehler.value)
    assert meldung.startswith('Unexpected token: |. "|" verbindet CQL-Zellen'), meldung
    assert "Wortfolge" not in meldung
