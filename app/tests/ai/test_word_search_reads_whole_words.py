"""Boolean keywords inside longer words remain literal word content."""

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


@pytest.mark.parametrize("wort, erwartet", [
    ("Ordnung", 2), ("Organisation", 3), ("andere", 32), ("anders", 11),
    ("notwendig", 5), ("Notfall", 0), ("Ort", 4),
])
def test_zaehlung_und_zeilen_nennen_dieselbe_zahl(index, wort, erwartet):
    from candyconc.services.backend.server import _compute_query_count

    assert _TW.run_cqlf_query_tool(wort, limit=1)["total"] == erwartet
    assert _TW.query_count_tool(wort)["total"] == erwartet
    rest, _ms, _teilweise = _compute_query_count(index, wort, 0, None, None, None, case_insensitive=True)
    assert rest == erwartet


def test_die_operatoren_der_wortsuche_bleiben(index):
    assert _TW.query_count_tool("und OR oder")["total"] == 1047
    assert _TW.query_count_tool("(und OR oder)")["total"] == 1047
    assert _TW.query_count_tool("und AND NOT oder")["total"] == 919
