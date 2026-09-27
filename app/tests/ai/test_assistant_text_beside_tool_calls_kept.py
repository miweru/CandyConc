# -*- coding: utf-8 -*-
"""Preserve assistant text emitted alongside tool calls in the conversation history."""

from __future__ import annotations

import asyncio
import unittest

from tests.ai._real_copilot import _MODULES as _REAL_MODULES
from tests.ai.test_harden_r2_live_findings import (
    _COLLOCATE_OUTPUT,
    _capture_events,
    _empty_requirements_response,
    _orchestrator,
    _structured_step_response,
    _tool_call,
)

sv = _REAL_MODULES["candyconc_copilot.session_compaction"]

PLAN = "Plan: erst die Kollokate von Arbeit, dann die Gegenprobe im Teilkorpus."


class TestPlanTextStaysInTheHistory(unittest.TestCase):
    def test_the_next_round_sees_the_text_beside_the_calls(self):
        gesehen: list[list] = []
        runde = {"n": 0}

        async def _llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                return _structured_step_response(name)
            gesehen.append(list(messages))
            runde["n"] += 1
            if runde["n"] == 1:
                return {"choices": [{"message": {
                    "role": "assistant", "content": PLAN,
                    "tool_calls": [_tool_call("c1", "collocate_stats", {"term": "Arbeit"})],
                }, "finish_reason": "tool_calls"}]}
            return {"choices": [{"message": {"role": "assistant", "content": "Fertig."},
                                 "finish_reason": "stop"}]}

        async def _dispatch(tool_call, _token=None):
            return dict(_COLLOCATE_OUTPUT)

        orch = _orchestrator(["collocate_stats", "run_cqlf_query", "frequency_list"], _llm, _dispatch)
        _capture_events(orch)
        asyncio.run(orch.run_async("Welche Kollokationen hat 'Arbeit' im Korpus?",
                                   max_steps=4, max_time=600.0))
        self.assertGreaterEqual(len(gesehen), 2)
        zuege = [m for m in gesehen[1] if m.get("role") == "assistant" and m.get("tool_calls")]
        self.assertTrue(zuege, "kein Assistenzzug mit Aufruf in der Folgerunde")
        self.assertEqual(zuege[-1].get("content"), PLAN)

    def test_the_budget_counts_the_measured_text(self):
        """Die gemessene Turnform traegt den Assistenztext und hat eine Runde Luft."""
        self.assertGreaterEqual(sv._WOERTER_JE_ASSISTENZZUG, 55)
        je_runde = 652 + sv._WOERTER_JE_ASSISTENZZUG + sv._WOERTER_JE_RUNDENNOTIZ
        form = (sv._RUNDEN_DER_GEMESSENEN_TURNFORM * je_runde
                + sv._WOERTER_FUER_FRAGE_UND_ANTWORT + sv._WOERTER_FUER_RAHMUNG)
        self.assertGreaterEqual(sv.schwelle_aus_dem_fenster() - form, je_runde)


if __name__ == "__main__":
    unittest.main()
