"""Usage KWIC sampling derives a distinct seed for each query."""

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


def _vorgeschriebene_argumente(treffer: int) -> dict:
    """Der Aufruf des Schritts, die Slots mit ihren Vorgaben belegt."""
    rezept = RECIPES_BY_ID["gebrauch_kwic"]
    hinweis = next(
        schritt.tool_hinweis
        for schritt in rezept.schritte
        if schritt.ziel == "KWIC-Stichprobe fuer die Belege"
    )
    for name, beschreibung in rezept.slots.items():
        vorgabe = re.search(r"Default (\d+)", beschreibung)
        if vorgabe:
            hinweis = hinweis.replace("{" + name + "}", vorgabe.group(1))
    argumente = {"limit": int(re.search(r"limit=(\d+)", hinweis).group(1))}
    eigene = re.search(r"ab (\d+) Treffern sample=(\d+), seed=(\d+)", hinweis)
    if eigene and treffer > int(eigene.group(1)):
        argumente.update(sample=int(eigene.group(2)), seed=int(eigene.group(3)))
    return argumente


def test_die_beleg_stichprobe_zieht_je_abfrage_mit_eigenem_seed(index):
    seeds = {}
    for wort in ("und", "die"):
        treffer = _TW.query_count_tool(wort)["total"]
        assert treffer > 200, (wort, treffer)
        argumente = _vorgeschriebene_argumente(treffer)
        ergebnis = _TW.run_cqlf_query_tool(wort, **argumente)
        assert ergebnis["sample"]["population"] == treffer
        seeds[wort] = ergebnis["sample"]["seed"]
    assert len(set(seeds.values())) == 2, f"Beide Stichproben mit demselben Seed {seeds} ({argumente})"
