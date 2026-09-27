"""A quoted word counts like the unquoted word in both tools."""

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


def _beide(abfrage: str, **wahl) -> tuple[int, int]:
    return (int(_TW.query_count_tool(abfrage, **wahl)["total"]),
            int(_TW.run_cqlf_query_tool(abfrage, limit=1, sort_by="position", **wahl)["total"]))


@pytest.mark.parametrize("abfrage, gefaltet, streng", [
    ('"und"', 919, 797), ("'und'", 919, 797), ("'und die'", 42, 34), ('"Und"', 919, 113),
])
def test_ein_wort_in_anfuehrungszeichen_zaehlt_wie_das_wort(index, abfrage, gefaltet, streng):
    assert _beide(abfrage) == (gefaltet, gefaltet)
    assert _beide(abfrage, case_insensitive=False) == (streng, streng)


@pytest.mark.parametrize("abfrage, erwartet", [("geht's", 2), ("''", 2), ('"und oder"', 0)])
def test_apostroph_im_wort_und_seltene_formen_bleiben(index, abfrage, erwartet):
    # geht's und '' sind Wortformen des Index, "und oder" kommt als Folge nicht vor.
    assert _beide(abfrage) == (erwartet, erwartet)
