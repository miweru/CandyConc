"""The recipe example folds case so it also matches a sentence-initial construction."""

from __future__ import annotations

import os
import re

import pytest

from candyconc.candyconc_copilot.recipes import RECIPES

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


def _beispiel() -> str:
    for rezept in RECIPES:
        m = re.search(r"etwa (\[word=.*?\[word=\"auch\"\])", str(getattr(rezept, "briefing", "") or ""), re.S)
        if m:
            return " ".join(m.group(1).split())
    raise AssertionError("Kein Kettenbeispiel im Rezepttext gefunden.")


def test_das_beispiel_faltet_das_erste_glied():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    from candyconc.core import query_runtime as qrt
    from candyconc.services.backend import server as srv
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    qrt._CORPUS_INDEX = srv.get_index()
    tw = _load_real_tool_wrappers()
    kopf = " ".join(_beispiel().split()[:2])
    ungefaltet = re.sub(r"\s*%c", "", kopf)
    assert tw.query_count_tool(kopf)["total"] > tw.query_count_tool(ungefaltet)["total"], kopf
