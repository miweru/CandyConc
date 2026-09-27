"""Eine Modellstoerung toetet den Turn nicht, und was entstanden ist, bleibt.

Runde 5 (2026-09-13 bis 15): 41 Turns endeten mit ``status None, calls
None`` und dem Text "Die Modell-Engine ist waehrend der Generierung
ausgefallen". Der geteilte Rechner hatte das Modell gewechselt, der Turn
warf die Ausnahme bis zum Server, und mit ihr verschwanden Evidenz,
Aufrufzahl und Laufzeit. CLAUDE.md, Zeitlimits Punkt 3, verlangt das
Gegenteil: Teilantwort, Evidenz und Bilanz bleiben erhalten.

Diese Probe laesst die Engine DAUERHAFT ausfallen und das Warten auf das
Modell sofort scheitern. Der Turn muss trotzdem mit einem Text landen und
seine Bilanz fuehren.
"""
from __future__ import annotations

import asyncio
import unittest

from tests.ai._real_copilot import make_orchestrator, orchestrator as orch_module

LLMErrorKind = orch_module.LLMErrorKind
LLMRequestError = orch_module.LLMRequestError


def _spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


class ModellstoerungLandetDenTurn(unittest.TestCase):
    def test_dauerhafter_engineausfall_landet_mit_text_und_bilanz(self):
        aufrufe = []

        async def _engine_tot(messages, tools, **kwargs):
            aufrufe.append(1)
            raise LLMRequestError(
                kind=LLMErrorKind.ENGINE_UNAVAILABLE,
                message="Die Modell-Engine ist während der Generierung ausgefallen.",
                retryable=True,
            )

        async def _dispatch(tool_call, _token=None):  # pragma: no cover
            raise AssertionError("kein Werkzeug erwartet")

        orch = make_orchestrator([_spec("query_count")], _engine_tot, _dispatch)

        async def _modell_kommt_nicht(turn_state):
            return False

        orch._ra_warte_auf_modell = _modell_kommt_nicht
        original = orch_module._ENGINE_RETRY_DELAYS
        orch_module._ENGINE_RETRY_DELAYS = (0.0,)
        try:
            result = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        finally:
            orch_module._ENGINE_RETRY_DELAYS = original

        self.assertIsInstance(result, str)
        self.assertTrue(result.strip(), "der Turn muss mit einem Text landen")
        self.assertGreaterEqual(len(aufrufe), 1)
        bilanz = orch.turn_usage_report()
        self.assertGreaterEqual(int(bilanz.get("llm_calls_used") or 0), 1)
        self.assertIsInstance(bilanz.get("elapsed_s"), float)


if __name__ == "__main__":
    unittest.main()
