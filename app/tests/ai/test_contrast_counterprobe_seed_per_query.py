"""The contrast counterprobe uses the query-specific sampling behavior.

Run the prescribed KWIC call for two words and require a reported sample
with a distinct seed for each query. Fixed quantiles would repeatedly
select the same positions from each hit list."""

from __future__ import annotations

import os
import re

import pytest

from candyconc.candyconc_copilot.recipes import RECIPES_BY_ID
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


def _hinweis() -> str:
    return next(
        schritt.tool_hinweis
        for schritt in RECIPES_BY_ID["kontrast"].schritte
        if schritt.ziel == "Streuungs-Gegenprobe plus Beleg"
    )


def _vorgeschriebene_argumente() -> dict:
    treffer = re.search(r"run_cqlf_query\(top_keyword, ([^)]*)\)", _hinweis())
    assert treffer, _hinweis()
    argumente = dict(teil.split("=", 1) for teil in treffer.group(1).split(", "))
    # Das Ziel-Docset A entsteht erst im Turn, die Probe zieht aus dem ganzen Korpus.
    argumente.pop("docset_id")
    return {name: int(wert) for name, wert in argumente.items()}


def test_jede_gegenprobe_zieht_mit_eigenem_seed(index):
    argumente = _vorgeschriebene_argumente()
    seeds = set()
    for wort in ("und", "die"):
        ergebnis = _TW.run_cqlf_query_tool(wort, **argumente)
        assert ergebnis["total"] > len(ergebnis["rows"]), "Die Probe braucht mehr Treffer als Zeilen."
        assert ergebnis["sample"]["population"] == ergebnis["total"]
        seeds.add(ergebnis["sample"]["seed"])
    assert len(seeds) == 2, f"Beide Gegenproben ziehen mit demselben Seed {seeds} (argumente={argumente})"


def test_was_der_schritt_ueber_den_aufruf_ohne_sample_sagt_stimmt(index):
    ohne_sample = _TW.run_cqlf_query_tool("und", limit=50)
    zieht_stichprobe = "sample" in ohne_sample
    behauptet_indexreihenfolge = bool(
        re.search(r"ohne sample[^)]*Indexreihenfolge", _hinweis())
    )
    assert zieht_stichprobe and not behauptet_indexreihenfolge, _hinweis()
