# -*- coding: utf-8 -*-
"""Empty model output is a generation failure across supported response forms."""

import asyncio
import unittest

from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_empty_stop_is_retried import (
    _antwort,
    _skript_llm,
    _spec,
)

#: Die LM-Studio-Form des leeren Outputs: content fehlt/leer, tool_calls
#: ist ein leeres Array MIT Schluessel, finish_reason length.
def _leerer_length_output():
    return {"choices": [{"message": {"role": "assistant", "content": "",
                                     "tool_calls": []},
                         "finish_reason": "length"}]}


def _leere_tool_calls():
    return {"choices": [{"message": {"role": "assistant", "content": "",
                                     "tool_calls": []},
                         "finish_reason": "tool_calls"}]}


def _skript_llm_hauptloop(skript, protokoll):
    """Wie _skript_llm, aber nur der HAUPT-Loop verbraucht das Skript.

    Vor dem Haupt-Loop laufen schema-gebundene Vorbereitungs-Schritte
    (Fragenormalisierung, Klassifikator) durch denselben call_llm; sie
    sehen keine Werkzeuge und bekommen eine unbehandelte JSON-Leerantwort.
    """
    zustand = {"i": 0}

    async def call_llm(messages, tools, **kwargs):
        protokoll.append({"messages": list(messages), "tools": list(tools)})
        if not tools:
            # Vorbereitungs-Schritt: leerer Inhalt strukturiert nicht,
            # der Schritt faellt auf seinen deterministischen Weg zurueck.
            return _antwort("")
        i = zustand["i"]
        zustand["i"] = i + 1
        item = skript[min(i, len(skript) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return call_llm


def _orch(skript, **kwargs):
    async def _dispatch(tool_call, _token=None):
        return {"status": "success", "total": 42}
    rufe = []
    llm = _skript_llm_hauptloop(skript, rufe)
    return make_orchestrator([_spec("query_count")], llm, _dispatch,
                             **kwargs), rufe


def _hauptrufe(rufe):
    return [r for r in rufe if r["tools"]]


def _leere_assistant_in(historie):
    return [m for m in historie
            if m.get("role") == "assistant"
            and not (m.get("content") or "").strip()
            and not (m.get("tool_calls") or [])]


class LeererOutputBeiLength(unittest.TestCase):
    """Klasse A: ein Retry, keine leere Assistant-Nachricht."""

    def test_lm_studio_form_wird_einmal_wiederholt(self):
        orch, rufe = _orch([_leerer_length_output(), _antwort("Die Antwort.")])
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        self.assertIn("Antwort", text)
        self.assertEqual(len(_hauptrufe(rufe)), 2)
        # Genau die Modell-Sicht aus runde_02 darf nie wieder entstehen:
        # keine Anfrage traegt eine eigene leere Assistant-Nachricht.
        for ruf in _hauptrufe(rufe):
            self.assertEqual(_leere_assistant_in(ruf["messages"]), [],
                             ruf["messages"][-2:])
        self.assertEqual(_leere_assistant_in(orch.session.history), [])

    def test_leere_tool_calls_liste_ist_derselbe_ausfall(self):
        orch, rufe = _orch([_leere_tool_calls(), _antwort("Die Antwort.")])
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        self.assertIn("Antwort", text)
        self.assertEqual(len(_hauptrufe(rufe)), 2)
        for ruf in _hauptrufe(rufe):
            self.assertEqual(_leere_assistant_in(ruf["messages"]), [])


class ErschoepfterLeererOutput(unittest.TestCase):
    """Klasse B: nach dem verbrauchten Retry ehrliche Notlandung, kein
    dritter blinder Aufruf."""

    def test_zweiter_leerer_output_landet_ehrlich_nach_zwei_rufen(self):
        orch, rufe = _orch([_leerer_length_output(), _leerer_length_output()])
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        # Vor der Reparatur lief der stille Weiteraufruf bis zur
        # Schranke; jetzt genau zwei Hauptaufrufe und die Notlandung,
        # die den Ausfall als copilot.error benennt statt ihn als
        # Antwort zu buchen.
        self.assertEqual(len(_hauptrufe(rufe)), 2)
        self.assertIn("Evidenz", text)
        for ruf in _hauptrufe(rufe):
            self.assertEqual(_leere_assistant_in(ruf["messages"]), [])


class Kontrollen(unittest.TestCase):
    """Die Nachbarfaelle bleiben, wie sie sind."""

    def test_stop_ohne_evidenz_bleibt_normales_ende(self):
        from tests.ai.test_empty_stop_is_retried import _leerer_stop
        orch, rufe = _orch([_leerer_stop(), _leerer_stop()])
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        self.assertNotIn("empty_output_retry", text)
        self.assertLessEqual(len(_hauptrufe(rufe)), 3)

    def test_length_mit_text_faehrt_mit_notiz_fort(self):
        abgeschnitten = {"choices": [{"message": {
            "role": "assistant", "content": "Ergebnis: 42 Treffer,",
            "tool_calls": []}, "finish_reason": "length"}]}
        orch, rufe = _orch([abgeschnitten, _antwort("Fortsetzung.")])
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        haupt = _hauptrufe(rufe)
        self.assertEqual(len(haupt), 2)
        notizen = [m for m in haupt[1]["messages"]
                   if "Ausgabelimit abgeschnitten" in str(m.get("content", ""))]
        self.assertTrue(notizen, "Die Fortsetzungs-Notiz fehlt.")
        self.assertIn("Fortsetzung", text)


if __name__ == "__main__":
    unittest.main()
