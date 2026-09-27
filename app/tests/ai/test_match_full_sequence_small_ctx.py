"""The match field preserves the full token sequence when ctx is shorter than the hit."""

from __future__ import annotations

import os

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_TW = _load_real_tool_wrappers()
_ABFRAGE = '[word="nicht"] [word="nur"] []{0,8} [word="sondern"] [word="auch"]'


@pytest.fixture(scope="module")
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


def _pruefe(zeilen):
    assert zeilen, "Die Probe braucht Treffer im Testindex."
    for zeile in zeilen:
        treffer = str(zeile.get("match") or "")
        assert treffer.startswith("nicht nur ") and treffer.endswith(" sondern auch"), zeile
        assert len(str(zeile.get("left") or "").split()) <= 1, "left bleibt, wie bestellt."
        rechts = str(zeile.get("right") or "").split()
        fortsetzung = treffer.split()[1:]
        assert rechts[: len(fortsetzung)] == fortsetzung, zeile
        assert len(rechts) - len(fortsetzung) <= 1, "hinter dem Treffer ctx Token, nicht mehr."


def test_seite_mit_kleinem_ctx_traegt_die_volle_folge(index):
    _pruefe(_TW.run_cqlf_query_tool(_ABFRAGE, ctx=1, limit=5)["rows"])


def test_stichprobe_mit_kleinem_ctx_traegt_die_volle_folge(index):
    _pruefe(_TW.run_cqlf_query_tool(_ABFRAGE, ctx=1, sample=3, seed=42)["rows"])
