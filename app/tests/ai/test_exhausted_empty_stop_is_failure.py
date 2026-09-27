# -*- coding: utf-8 -*-
"""Two empty responses with available tools exhaust recovery and report failure."""

import asyncio

from candyconc.candyconc_copilot import empty_output
from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_empty_stop_is_retried import _leerer_stop, _skript_llm, _spec


def test_zweiter_leerer_stop_bei_angebotenen_werkzeugen_ist_stoerung():
    assert empty_output.entscheidung("stop", "", [], 1, True, True) == "stoerung"
    assert empty_output.entscheidung("stop", "", [], 1, False, True) == "stoerung"


def test_nachbarfaelle_bleiben():
    assert empty_output.entscheidung("stop", "", [], 0, True, True) == "wiederhole"
    assert empty_output.entscheidung("stop", "", [], 1, True, False) == "normal", (
        "Ohne angebotene Werkzeuge ist ein stop der Entschluss zu antworten.")
    assert empty_output.entscheidung("stop", "Text", [], 1, True, True) == "normal"


def test_der_turn_landet_ehrlich_mit_dem_wirklichen_grund():
    async def _dispatch(tool_call, _token=None):
        return {"status": "success", "total": 42}

    rufe = []
    werkzeug = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "query_count", "arguments": "{}"}}]},
        "finish_reason": "tool_calls"}]}
    orch = make_orchestrator([_spec("query_count")],
                             _skript_llm([werkzeug, _leerer_stop(), _leerer_stop()], rufe), _dispatch)
    orch._turn_evidence_items = [{"id": "E1", "tool": "query_count"}]
    text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
    assert len(rufe) == 4, "Ein Retry, kein dritter blinder Aufruf."
    assert "keine verwertbare Ausgabe" in text
    assert "unerreichbar" not in text, "Das Modell war erreichbar und lieferte nichts."
