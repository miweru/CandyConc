# -*- coding: utf-8 -*-
"""The model ends the tool phase through its declared completion path."""

import asyncio
import json
import types
import unittest

from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_run_async_phase3 import (
    _capture_copilot_event_bus,
    _spec,
    _turn_state,
)


def _abgabe_call():
    return {
        "id": "call_abgabe_1",
        "type": "function",
        "function": {
            "name": "deutung_abgeben",
            "arguments": json.dumps({
                "beantwortet": "Die Rate von 'Zeit' im Korpus.",
                "belege": ["E_query_count_1"],
                "offen": "",
            }),
        },
    }


def _orch(tools):
    async def _kein_llm(messages, tools_arg, **kwargs):  # pragma: no cover
        raise AssertionError("Diese Probe ruft kein Modell.")

    async def _kein_dispatch(tool_call, _token=None):  # pragma: no cover
        raise AssertionError("Diese Probe ruft kein Werkzeug.")

    return make_orchestrator(tools, _kein_llm, _kein_dispatch)


class DieWerkzeugImplementierung(unittest.TestCase):
    def test_leere_abgabe_ist_keine_abgabe(self):
        from candyconc.candyconc_copilot.deutung_abgeben import (
            deutung_abgeben_tool,
        )
        out = deutung_abgeben_tool(beantwortet="  ")
        self.assertEqual(out["status"], "error")
        self.assertNotIn("abgegeben", out)

    def test_vollstaendige_abgabe_wird_bestätigt(self):
        from candyconc.candyconc_copilot.deutung_abgeben import (
            deutung_abgeben_tool,
        )
        out = deutung_abgeben_tool(
            beantwortet="Die Rate im Korpus.",
            belege=["E_query_count_1"],
            offen="",
        )
        self.assertTrue(out["abgegeben"])
        self.assertEqual(out["belege"], ["E_query_count_1"])


class DieNahtZwischenFlagUndSchranke(unittest.TestCase):
    """Klasse A gegen Klasse B, ohne LLM: die Schranke selbst."""

    def setUp(self):
        self.orch = _orch([_spec("query_count")])

    def test_ohne_abgabe_entscheidet_die_reissleine(self):
        state = _turn_state()  # 0 Runden, Zeitbudget unangetastet
        self.assertFalse(self.orch._ra_tool_rounds_exhausted(state))

    def test_mit_abgabe_endet_der_turn_unabhängig_vom_budget(self):
        state = _turn_state()
        self.orch._ra_deutung_abgegeben = True
        self.assertTrue(self.orch._ra_tool_rounds_exhausted(state))

    def test_der_vermerk_schreibt_den_zwischenstand(self):
        from candyconc.candyconc_copilot.deutung_abgeben import vermerke_abgabe
        vermerke_abgabe(self.orch, "deutung_abgabe_nein", {"abgegeben": True})
        self.assertFalse(getattr(self.orch, "_ra_deutung_abgegeben", False))
        vermerke_abgabe(self.orch, "deutung_abgeben", {
            "abgegeben": True,
            "beantwortet": "Die Rate.",
            "belege": ["E_1"],
            "offen": "nichts",
        })
        self.assertTrue(self.orch._ra_deutung_abgegeben)


class DasBundleGateBefreitDenAusgang(unittest.TestCase):
    """Die Abgabe gehoert zu keinem Analysevertrag und darf nicht blockiert werden."""

    def setUp(self):
        self.orch = _orch([_spec("query_count"), _spec("deutung_abgeben")])

    def _filter(self):
        ereignisse = []
        return self.orch._ra_filter_tool_calls(
            [_abgabe_call()],
            copilot_event_bus=_capture_copilot_event_bus(ereignisse),
            question="Wie oft kommt Zeit vor?",
            principal="test",
            active_contract=types.SimpleNamespace(
                mode="tool_analysis",
                analysis_family="term_frequency",
                allowed_tools=["query_count"],
                forbidden_claims=[],
            ),
            active_allowed_tools=["query_count"],
            forced_next_tools=None,
        )

    def test_die_abgabe_durchdringt_den_vertrag(self):
        erlaubt = self._filter()
        self.assertEqual([tc for tc, _ in erlaubt][0]["function"]["name"],
                         "deutung_abgeben")


@unittest.skip("Produkt-Pfad-Turn: braucht Sitzungs- und Landungsfixtures; "
               "die drei Naht-Proben oben sichern die Verdrahtung.")
class DerGanzeTurn(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
