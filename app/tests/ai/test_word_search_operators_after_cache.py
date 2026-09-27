"""Word-search Boolean and proximity operators work when a component is cached."""

from __future__ import annotations

import os

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from candyconc.domain.query_eval import prefetch_positions
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()
_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture
def index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    yield idx
    qrt._CORPUS_INDEX = None
    idx.close()


@pytest.mark.parametrize("abfrage", ["Und OR Oder", "Und AND NOT Oder", "Und NEAR/3 Oder", "NOT Und"])
def test_verknuepfung_nach_einem_gecachten_teilwort(index, abfrage):
    ohne_cache = int(prefetch_positions(abfrage, CorpusIndex(_INDEX_PATH), case_insensitive=False).size)
    prefetch_positions("Und", index, case_insensitive=False)
    prefetch_positions("Oder", index, case_insensitive=False)
    assert int(prefetch_positions(abfrage, index, case_insensitive=False).size) == ohne_cache


def test_werkzeuge_zaehlen_die_verknuepfung_nach_dem_cache(index):
    prefetch_positions("Und", index, case_insensitive=False)
    assert _TW.query_count_tool("Und OR Oder", case_insensitive=False)["total"] == 125
    assert _TW.run_cqlf_query_tool("Und OR Oder", case_insensitive=False, limit=1, sort_by="position")["total"] == 125
