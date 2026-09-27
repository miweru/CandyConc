"""Interpretation synthesis receives no guard instruction contradicting its task."""

import asyncio

import unittest

from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_empty_stop_is_retried import _spec

_WIDERSPRUCH = "ohne Tool-Evidenz verantwortbar"


class SyntheseOhneWiderspruch(unittest.TestCase):
    def _orch(self):
        gesehen = []

        async def _llm(messages, tools, **kw):
            gesehen.append(list(messages))
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

        async def _dispatch(tool_call, _token=None):
            return {"status": "success"}

        orch = make_orchestrator([_spec("query_count")], _llm, _dispatch)
        # Aus dem Namensraum der echten Klasse, conftest ersetzt Module durch Stubs.
        zustand = type(orch).__init__.__globals__["_RunTurnState"]()
        zustand.principal, zustand.llm_is_async, zustand.normalized_question = "probe", True, "F"
        return orch, zustand, gesehen

    def test_vorbereiteter_aufruf_erklaert_den_leeren_raum_ohne_widerspruch(self):
        orch, zustand, gesehen = self._orch()
        nachrichten = [{"role": "system", "content": "Du schreibst jetzt die FINALE ANTWORT."},
                       {"role": "user", "content": "FRAGE: F"}]
        asyncio.run(orch._ra_invoke_llm_ungebucht(zustand, request_messages=nachrichten, tools_override=[]))
        gesendet = gesehen[-1]
        self.assertEqual(gesendet[:-1], nachrichten)
        self.assertIn("keine Tools verfügbar", gesendet[-1]["content"])
        self.assertFalse(any(_WIDERSPRUCH in str(m.get("content")) for m in gesendet))
        self.assertNotIn("Rückfrage", gesendet[-1]["content"])

    def test_der_waechterbauer_behaelt_den_satz_ohne_vorbereitete_evidenz(self):
        orch, _zustand, _gesehen = self._orch()
        self.assertIn(_WIDERSPRUCH, orch._ra_tool_runtime_guard_message([]))
        self.assertNotIn(_WIDERSPRUCH, orch._ra_tool_runtime_guard_message([], evidenz_in_nachrichten=True))
