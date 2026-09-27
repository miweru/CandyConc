"""Word attributes count consistently, and unknown attributes are input errors."""

from __future__ import annotations

import os

import pytest

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


def _beide(abfrage: str) -> tuple[int, int]:
    return (int(_TW.query_count_tool(abfrage)["total"]),
            int(_TW.run_cqlf_query_tool(abfrage, limit=1, sort_by="position")["total"]))


def test_word_zaehlt_wie_die_cql_zelle(index):
    assert _beide("[word=und]") == (797, 797)
    assert _TW.query_count_tool('[word="und"]')["total"] == 797


def test_die_uebrigen_attribute_bleiben(index):
    assert _beide("[pos=NOUN]") == (9740, 9740)


def test_ein_unbekanntes_attribut_ist_ein_aufruferfehler(index):
    for aufruf in (lambda: _TW.query_count_tool("[farbe=rot]"),
                   lambda: _TW.run_cqlf_query_tool("[farbe=rot]", limit=1, sort_by="position")):
        with pytest.raises(_TW.ToolInputError) as fehler:
            aufruf()
        assert "farbe" in str(fehler.value)
