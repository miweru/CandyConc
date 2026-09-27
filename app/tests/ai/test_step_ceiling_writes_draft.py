# -*- coding: utf-8 -*-
"""An der Schrittdecke entsteht ein Entwurf wie nach der Abgabe.

Muse, zyklus8_teil4, r3b-spiegel-1: 20 Werkzeugrunden, dann ``max_steps``,
und die Synthese lief ohne Entwurf ("Werkzeugphase selbst beendet: nein /
LEER"). zyklus5_teil2, r5a-wort-gegen-lemma: die Abgabe fiel auf Runde 20,
der Zweig ``step_i >= max_steps`` griff vor dem Entwurfsaufruf ("ja / LEER").
Jetzt folgt an der Decke ein Aufruf ohne Werkzeuge mit einer Tatsachennotiz,
und sein Text geht als Entwurf in die Synthese.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest import mock

from candyconc.candyconc_copilot.deutung_abgeben import deutung_abgeben_tool
from tests.ai._real_copilot import make_orchestrator
from tests.ai._real_copilot import orchestrator as orch_mod
from tests.ai.test_empty_stop_is_retried import _spec
from tests.ai.test_harden_r2_live_findings import (
    _COLLOCATE_OUTPUT,
    _capture_events,
    _empty_requirements_response,
    _orchestrator,
    _structured_step_response,
    _tool_call,
)

ENTWURF = (
    "Entwurf aus der Werkzeugphase: 'Arbeit' steht mit 'Würde' und 'Recht', "
    "die Kollokationen tragen den Befund, die Deutung folgt aus ihnen."
)
_REISSLEINE = "Letzte Werkzeug-Runde ist vorbei"


def _abgabe(call_id: str) -> dict:
    return _tool_call(call_id, "deutung_abgeben", {
        "beantwortet": "Die Kollokationen von 'Arbeit'.",
        "belege": ["E_collocate_stats_1"],
        "offen": "",
    })


class _Lauf:
    """Ein Turn gegen ein Fake-Modell, das Werkzeuge ruft, solange es darf."""

    def __init__(self, *, abgabe_in_runde: int | None = None):
        self.abgabe_in_runde = abgabe_in_runde
        self.werkzeugrunden = 0
        self.entwurfsaufrufe: list[list] = []
        self.synthese_entwurf: list[str] = []

    async def call_llm(self, messages, exposed_tools, json_schema=None, stream=False, **kwargs):
        if json_schema is not None:
            name = json_schema.get("name", "")
            if name == "response_requirements":
                return _empty_requirements_response()
            return _structured_step_response(name)
        if not exposed_tools:
            self.entwurfsaufrufe.append(list(messages))
            return {"choices": [{"message": {"role": "assistant", "content": ENTWURF},
                                 "finish_reason": "stop"}]}
        self.werkzeugrunden += 1
        if self.abgabe_in_runde is not None and self.werkzeugrunden == self.abgabe_in_runde:
            aufruf = _abgabe(f"a{self.werkzeugrunden}")
        else:
            aufruf = _tool_call(f"c{self.werkzeugrunden}", "collocate_stats",
                                {"term": f"Arbeit{self.werkzeugrunden}"})
        return {"choices": [{"message": {"role": "assistant", "tool_calls": [aufruf]},
                             "finish_reason": "tool_calls"}]}

    async def dispatch(self, tool_call, _token=None):
        fn = tool_call.get("function", {})
        if fn.get("name") == "deutung_abgeben":
            return deutung_abgeben_tool(**json.loads(fn.get("arguments") or "{}"))
        return dict(_COLLOCATE_OUTPUT)

    async def synthese(self, orchestrator, turn_state, bus, evidence_items, entwurf=""):
        self.synthese_entwurf.append(entwurf)
        return "Synthese mit Entwurf."

    def run(self, max_steps: int):
        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list", "deutung_abgeben"],
            self.call_llm, self.dispatch,
        )
        events = _capture_events(orch)
        with mock.patch.dict(os.environ, {"CANDYCONC_DEUTUNGSPFAD": "1"}), \
                mock.patch.object(orch_mod, "fuehre_deutungs_synthese_aus", self.synthese):
            ergebnis = asyncio.run(orch.run_async(
                "Welche Kollokationen hat 'Arbeit' im Korpus?",
                max_steps=max_steps, max_time=600.0,
            ))
        return ergebnis, events


def _recovery_kinds(events) -> list[str]:
    return [
        (e.get("recovery") or {}).get("kind")
        for e in events
        if isinstance(e, dict) and e.get("event") == "copilot.recovery"
    ]


class TestTheCeilingWritesADraft(unittest.TestCase):
    def test_draft_call_follows_the_ceiling_and_reaches_the_synthesis(self):
        lauf = _Lauf()
        ergebnis, events = lauf.run(max_steps=3)
        self.assertEqual(len(lauf.entwurfsaufrufe), 1, "kein Entwurfsaufruf an der Decke")
        letzte = str(lauf.entwurfsaufrufe[0][-1].get("content", ""))
        self.assertIn("Schrittdecke von 3 Modellrunden", letzte)
        self.assertNotIn(_REISSLEINE, letzte)
        self.assertEqual(lauf.synthese_entwurf, [ENTWURF])
        self.assertIn("max_steps_reached", _recovery_kinds(events))
        self.assertTrue(ergebnis.strip())

    def test_an_abgabe_in_the_last_round_keeps_its_draft(self):
        lauf = _Lauf(abgabe_in_runde=3)
        lauf.run(max_steps=3)
        self.assertEqual(len(lauf.entwurfsaufrufe), 1, "die Abgabe in der letzten Runde verlor ihren Entwurf")
        letzte = str(lauf.entwurfsaufrufe[0][-1].get("content", ""))
        self.assertNotIn("Schrittdecke", letzte, "nach der Abgabe endete das Modell selbst")
        self.assertNotIn(_REISSLEINE, letzte)
        self.assertEqual(lauf.synthese_entwurf, [ENTWURF])


class TestTheCeilingGuard(unittest.TestCase):
    def _waechter(self, *, decke: bool, abgegeben: bool) -> str:
        gesehen = []

        async def _llm(messages, tools, **kw):
            gesehen.append(list(messages))
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

        async def _dispatch(tool_call, _token=None):
            return {"status": "success"}

        orch = make_orchestrator([_spec("query_count")], _llm, _dispatch)
        orch._ra_deutung_abgegeben = abgegeben
        orch._turn_max_steps = 240
        zustand = type(orch).__init__.__globals__["_RunTurnState"]()
        zustand.principal, zustand.llm_is_async = "probe", True
        zustand.normalized_question, zustand.system_prompt, zustand.tool_rounds = "F", "S", 4
        zustand.schrittdecke_erreicht = decke
        asyncio.run(orch._ra_invoke_llm_ungebucht(zustand))
        return str(gesehen[-1][-1]["content"])

    def test_the_ceiling_says_who_ended_the_tool_phase(self):
        waechter = self._waechter(decke=True, abgegeben=False)
        self.assertIn("keine Tools verfügbar", waechter)
        self.assertIn("Schrittdecke von 240 Modellrunden", waechter)
        self.assertNotIn(_REISSLEINE, waechter)

    def test_the_rounds_predicate_counts_the_ceiling(self):
        orch = make_orchestrator([_spec("query_count")], None, None)
        zustand = type(orch).__init__.__globals__["_RunTurnState"]()
        self.assertFalse(orch._ra_tool_rounds_exhausted(zustand))
        zustand.schrittdecke_erreicht = True
        self.assertTrue(orch._ra_tool_rounds_exhausted(zustand))


if __name__ == "__main__":
    unittest.main()
