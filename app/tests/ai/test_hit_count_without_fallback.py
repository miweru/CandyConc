"""Report an unavailable exact hit count instead of substituting the returned row count.

Lower the NOT counting threshold within the test process to exercise a
count failure while the bounded row query still returns hits."""

from __future__ import annotations

import os

import pytest

from candyconc.core import query_runtime as qrt
from candyconc.core.corpus_index import CorpusIndex
from candyconc.domain import query_eval
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


def test_ein_zu_grosses_not_meldet_sich_statt_einer_zahl(index, monkeypatch):
    monkeypatch.setattr(query_eval, "_NOT_MAX_TOKENS", 1000)
    for aufruf in (lambda: _TW.run_cqlf_query_tool("NOT und", limit=5, sort_by="position"),
                   lambda: _TW.query_count_tool("NOT und")):
        with pytest.raises(_TW.ToolInputError) as fehler:
            aufruf()
        assert "NOT Query zu gross" in str(fehler.value)


def test_eine_gescheiterte_zaehlung_wird_keine_zeilenzahl(index, monkeypatch):
    from candyconc.services.backend import server

    def _scheitert(*_args, **_kwargs):
        raise RuntimeError("Index nicht erreichbar")

    monkeypatch.setattr(server, "_compute_query_count", _scheitert)
    with pytest.raises(RuntimeError, match="Index nicht erreichbar"):
        _TW.run_cqlf_query_tool("[pos=NOUN]", limit=5, sort_by="position")


def test_eine_zaehlbare_abfrage_bleibt_wie_sie_war(index):
    ergebnis = _TW.run_cqlf_query_tool("[pos=NOUN]", limit=5, sort_by="position")
    assert (ergebnis["total"], ergebnis["truncated"], len(ergebnis["rows"])) == (9740, True, 5)
