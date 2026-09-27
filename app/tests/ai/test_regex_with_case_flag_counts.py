"""A regex value with %c counts consistently with the corresponding regex operator."""

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


def _zahl(abfrage: str) -> int:
    return int(_TW.query_count_tool(abfrage)["total"])


@pytest.mark.parametrize("regex, erwartet", [("und|oder", 1047), ("und.*", 925)])
def test_ein_regexwert_mit_faltung_zaehlt_wie_die_tilde(index, regex, erwartet):
    assert _zahl(f'[word~"{regex}"%c]') == erwartet
    assert _zahl(f'[word="{regex}"%c]') == erwartet


def test_die_menge_und_die_regexform_zaehlen_dasselbe(index):
    assert _zahl('[word="und|oder"%c]') == _zahl('[word in {"und","oder"}%c]') == 1047


def test_rest_zaehlt_dasselbe(index):
    from candyconc.services.backend.server import _compute_query_count

    gesamt, _ms, _teilweise = _compute_query_count(
        index, '[word="und|oder"%c]', 0, None, None, None, case_insensitive=True)
    assert gesamt == 1047


def test_ohne_faltung_und_als_literal_bleibt_es_wie_es_war(index):
    assert _zahl('[word="und|oder"]') == 913
    assert _zahl('[word="und"%c]') == 919
    assert _zahl('[word="Und"]') == 113
