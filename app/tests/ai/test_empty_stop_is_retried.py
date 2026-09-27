# -*- coding: utf-8 -*-
"""An empty stop is retried when the available evidence or tools permit recovery.

Exercise evidence-present and tool-available cases as well as exhausted
recovery. An empty generation must not be accepted as a completed answer."""

import asyncio
import types
import unittest

from tests.ai._real_copilot import make_orchestrator


def _spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def _leerer_stop():
    return {"choices": [{"message": {"role": "assistant", "content": ""},
                         "finish_reason": "stop"}]}


def _antwort(text):
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}]}


def _skript_llm(skript, protokoll):
    """Async-CallLLM-Funktion (kein Instanz-__call__: der Orchestrator
    prueft asyncio.iscoroutinefunction(call_llm) und wuerde eine Instanz
    als synchron einstufen)."""
    zustaand = {"skript": list(skript), "i": 0}

    async def call_llm(messages, tools, **kwargs):
        protokoll.append({"messages": list(messages), "tools": list(tools)})
        i = zustaand["i"]
        zustaand["i"] = i + 1
        item = zustaand["skript"][min(i, len(zustaand["skript"]) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return call_llm


class LeererStopMitEvidenz(unittest.TestCase):
    """Klasse A: ein Retry, dann ist Schluss."""

    def _orch(self, skript):
        async def _dispatch(tool_call, _token=None):
            return {"status": "success", "total": 42}
        rufe = []
        llm = _skript_llm(skript, rufe)
        return make_orchestrator([_spec("query_count")], llm, _dispatch), rufe

    def test_leerer_stop_nach_evidenz_wird_einmal_wiederholt(self):
        # Evidenz_item vorhanden, erster Endcall leer, zweiter liefert Text.
        orch, rufe = self._orch([
            {"choices": [{"message": {"role": "assistant", "content": "",
                                      "tool_calls": [
                                          {"id": "c1", "type": "function",
                                           "function": {"name": "query_count",
                                                         "arguments": "{}"}}]},
                          "finish_reason": "tool_calls"}]},
            _leerer_stop(),
            _antwort("Die Antwort aus demRetry."),
        ])
        orch._turn_evidence_items = [{"id": "E1", "tool": "query_count"}]
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        self.assertIn("Retry", text)
        # Drei LLM-Rufe: Werkzeugrunde, leerer Stop, Wiederholung.
        self.assertEqual(len(rufe), 3)

    def test_zweiter_leerer_stop_gilt_als_ende(self):
        # The second empty stop exhausts recovery. Return a partial fallback
        # from the collected evidence without issuing a third call.
        orch, rufe = self._orch([
            {"choices": [{"message": {"role": "assistant", "content": "",
                                      "tool_calls": [
                                          {"id": "c1", "type": "function",
                                           "function": {"name": "query_count",
                                                         "arguments": "{}"}}]},
                          "finish_reason": "tool_calls"}]},
            _leerer_stop(),
            _leerer_stop(),
        ])
        orch._turn_evidence_items = [{"id": "E1", "tool": "query_count"}]
        asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        # Two preliminary calls consume the first scripted responses. The loop
        # then sees two empty stops and uses one retry, with no fifth call.
        self.assertEqual(len(rufe), 4)


    def test_spaeterer_leerer_stop_bekommt_seinen_eigenen_retry(self):
        # Reset retry availability after successful work. The scripted sequence
        # contains a tool call, an empty stop, another tool call, another empty
        # stop and an answer. Both independent empty generations need recovery.
        def ruf(nr):
            return {"choices": [{"message": {"role": "assistant", "content": "",
                                             "tool_calls": [
                                                 {"id": f"c{nr}", "type": "function",
                                                  "function": {"name": "query_count",
                                                               "arguments": '{"q": %d}' % nr}}]},
                                 "finish_reason": "tool_calls"}]}
        orch, rufe = self._orch([
            ruf(0), _leerer_stop(),
            ruf(1), _leerer_stop(), ruf(2), _leerer_stop(),
            _antwort("Die Antwort nach dem zweiten Retry."),
        ])
        orch._turn_evidence_items = [{"id": "E1", "tool": "query_count"}]
        text = asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        self.assertEqual(len(rufe), 7)
        self.assertIn("zweiten Retry", text)


class LeererStopOhneEvidenz(unittest.TestCase):
    """Retry an empty stop without evidence when tools are still available.

An empty generation does not express a decision to answer and must not
narrow the available tools to only the required subset."""

    def test_ohne_evidenz_mit_werkzeugen_ein_retry(self):
        async def _dispatch(tool_call, _token=None):
            return {"status": "success", "total": 42}
        rufe = []
        llm = _skript_llm([_leerer_stop(), _leerer_stop()], rufe)
        orch = make_orchestrator([_spec("query_count")], llm, _dispatch)
        asyncio.run(orch.run_async("Wie oft kommt Zeit vor?"))
        # Zwei Voraufrufe, der leere Stop der Schleife, genau eine
        # Wiederholung, dann das Ende.
        werkzeugrufe = [r for r in rufe if r["tools"]]
        self.assertEqual(len(werkzeugrufe), 2)
        self.assertEqual(len(rufe), 4)

    def test_ohne_werkzeuge_bleibt_der_leere_stop_ein_ende(self):
        from candyconc.candyconc_copilot import empty_output

        self.assertEqual(empty_output.entscheidung("stop", "", [], 0, False, False), "normal")
        self.assertEqual(empty_output.entscheidung("stop", "", [], 0, False, True), "wiederhole")
        # An empty stop after the retry is a failure, as checked separately by
        # test_exhausted_empty_stop_is_failure.py.
        self.assertEqual(empty_output.entscheidung("stop", "", [], 1, False, True), "stoerung")


if __name__ == "__main__":
    unittest.main()
