"""Voluntary submission does not give the draft the form of an emergency-stop answer."""

import asyncio

import unittest

from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_empty_stop_is_retried import _spec

_REISSLEINE = "Letzte Werkzeug-Runde ist vorbei"
_DRIFT = "AUSGANGSFRAGE"
_WIDERSPRUCH = "ohne Tool-Evidenz verantwortbar"


class EntwurfNachDerAbgabe(unittest.TestCase):
    def _waechter(self, *, abgegeben: bool, erschoepft: bool) -> str:
        gesehen = []

        async def _llm(messages, tools, **kw):
            gesehen.append(list(messages))
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

        async def _dispatch(tool_call, _token=None):
            return {"status": "success"}

        orch = make_orchestrator([_spec("query_count")], _llm, _dispatch)
        orch._ra_deutung_abgegeben = abgegeben
        orch._ra_tool_rounds_exhausted = lambda _zustand: abgegeben or erschoepft
        # Aus dem Namensraum der echten Klasse, conftest ersetzt Module durch Stubs.
        zustand = type(orch).__init__.__globals__["_RunTurnState"]()
        zustand.principal, zustand.llm_is_async = "probe", True
        zustand.normalized_question, zustand.system_prompt, zustand.tool_rounds = "F", "S", 4
        asyncio.run(orch._ra_invoke_llm_ungebucht(zustand))
        letzte = gesehen[-1][-1]
        self.assertEqual(letzte["role"], "user")
        return str(letzte["content"])

    def test_nach_der_abgabe_nur_die_erklaerung_des_leeren_raums(self):
        waechter = self._waechter(abgegeben=True, erschoepft=False)
        self.assertIn("keine Tools verfügbar", waechter)
        for fremd in (_REISSLEINE, _DRIFT, _WIDERSPRUCH):
            self.assertNotIn(fremd, waechter)

    def test_an_der_reissleine_bleibt_ihre_gestalt(self):
        waechter = self._waechter(abgegeben=False, erschoepft=True)
        self.assertIn(_REISSLEINE, waechter)
        self.assertNotIn(_WIDERSPRUCH, waechter)

    def test_mit_werkzeugen_bleibt_der_driftanker(self):
        self.assertIn(_DRIFT, self._waechter(abgegeben=False, erschoepft=False))
