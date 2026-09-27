# -*- coding: utf-8 -*-
"""Ein identischer Aufruf im selben nebenlaeufigen Block laeuft einmal.

Am 2026-08-30 auf dem echten Produktpfad gemessen: auf die Frage
"Kollokationsprofil fuer den Knoten Rolle bei Fenster 5" hat der Copilot in
EINEM Block drei bis vier identische Aufrufe
``collocate_stats(term="Rolle", window=5, ...)`` abgesetzt. Jeder davon
rechnet auf einem 142-Millionen-Token-Index. Mit ``qwen3.8-flash-next``
(11 Tokens/s) lief der Turn dadurch in den Verbindungsabbruch der Bruecke
nach 15 Minuten, mit ``qwen3.8-27b`` reproduzierte sich die Wiederholung
ebenfalls. Der Defekt haengt also nicht am Modell.

Die Sperre GAB es bereits, sie hing aber an drei Bedingungen. Die dritte
verlangte ueber ``same_corpus_collocation_terms`` ein Vergleichswort in der
Frage ("vergleiche", "gegenueber", "vs", "versus"). Bei einer schlichten
Profilfrage fiel sie aus. Nachgewiesen wurde ausserdem, dass die Aufrufe im
selben Block lagen und nicht ueber Runden verteilt: die Laufzeitangaben sind
vollstaendig (``collocate_stats`` traegt ``read_only: True,
concurrency_safe: True``), also haette die rundenuebergreifende
Wiederverwendung sie sonst gefangen.

Was die Sperre NICHT treffen darf, steht in den Tests weiter unten: ein
identischer Aufruf nach einem seriellen Werkzeug ist legitim, weil dieses
den Zustand geaendert haben kann, und verschiedene Argumente sind
verschiedene Aufrufe.
"""

from __future__ import annotations

import types
import unittest

from tests.ai._real_copilot import make_orchestrator


def _spec(name):
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def _tc(call_id, name, argumente="{}"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": argumente}}


def _bus(ereignisse):
    return types.SimpleNamespace(
        publish=lambda event, session_id=None: ereignisse.append(event))


class DoppelterAufrufImBlock(unittest.TestCase):
    def _orchestrator(self, laufzeit):
        async def _kein_dispatch(tool_call, _token=None):  # pragma: no cover
            raise AssertionError("dispatch darf hier nicht laufen")

        async def _kein_llm(messages, tools_arg, **kwargs):  # pragma: no cover
            raise AssertionError("LLM darf hier nicht laufen")

        orch = make_orchestrator(
            [_spec(n) for n in laufzeit], _kein_llm, _kein_dispatch)
        orch._tool_runtime_info = dict(laufzeit)
        return orch

    def _filtern(self, orch, aufrufe, frage="Kollokationsprofil fuer Rolle bei Fenster 5"):
        ereignisse = []
        durch = orch._ra_filter_tool_calls(
            aufrufe,
            copilot_event_bus=_bus(ereignisse),
            question=frage,
            principal="user",
            active_contract=None,
            active_allowed_tools=None,
            forced_next_tools=None,
        )
        return [tc for tc, _ in durch], ereignisse

    def test_vier_identische_kollokationsaufrufe_laufen_einmal(self):
        """Der gemessene Fall. Ohne Vergleichswort in der Frage."""
        orch = self._orchestrator({
            "collocate_stats": {"read_only": True, "concurrency_safe": True}})
        args = '{"term": "Rolle", "window": 5}'
        durch, _ = self._filtern(orch, [
            _tc("a", "collocate_stats", args),
            _tc("b", "collocate_stats", args),
            _tc("c", "collocate_stats", args),
            _tc("d", "collocate_stats", args),
        ])
        self.assertEqual(len(durch), 1, [t["id"] for t in durch])
        self.assertEqual(durch[0]["id"], "a")

    def test_verschiedene_argumente_sind_verschiedene_aufrufe(self):
        """Positive Klasse. Ohne sie bestuende der Test auch auf einer Sperre,
        die einfach alles ausser dem ersten Aufruf wegwirft."""
        orch = self._orchestrator({
            "collocate_stats": {"read_only": True, "concurrency_safe": True}})
        durch, _ = self._filtern(orch, [
            _tc("a", "collocate_stats", '{"term": "Rolle", "window": 1}'),
            _tc("b", "collocate_stats", '{"term": "Rolle", "window": 5}'),
            _tc("c", "collocate_stats", '{"term": "Rolle", "window": 10}'),
        ])
        self.assertEqual(len(durch), 3, [t["id"] for t in durch])

    def test_nach_einem_seriellen_werkzeug_ist_die_wiederholung_legitim(self):
        """Ein serielles Werkzeug kann den Zustand geaendert haben.

        list_docsets vor und nach einem create_docset sind zwei verschiedene
        Fragen an die Welt, auch bei identischen Argumenten.
        """
        orch = self._orchestrator({
            "list_docsets": {"read_only": True, "concurrency_safe": True},
            "create_docset": {"read_only": True, "concurrency_safe": False},
        })
        durch, _ = self._filtern(orch, [
            _tc("a", "list_docsets", "{}"),
            _tc("b", "create_docset", '{"name": "X"}'),
            _tc("c", "list_docsets", "{}"),
        ])
        self.assertEqual([t["id"] for t in durch], ["a", "b", "c"])

    def test_der_ausgelassene_aufruf_vergiftet_die_fehlschlagsperre_nicht(self):
        """Ausgelassen ist nicht fehlgeschlagen.

        Wuerde der Doppelaufruf ueber die Fehlschlaghuelle laufen, landete er
        in _failed_tool_attempts und der Aufruf waere fuer den REST des Turns
        gesperrt, auch nach einer Zustandsaenderung.
        """
        orch = self._orchestrator({
            "collocate_stats": {"read_only": True, "concurrency_safe": True}})
        args = '{"term": "Rolle", "window": 5}'
        self._filtern(orch, [
            _tc("a", "collocate_stats", args),
            _tc("b", "collocate_stats", args),
        ])
        self.assertEqual(orch._failed_tool_attempts, {})

    def test_das_ereignis_nennt_den_grund(self):
        """Die Arbeitsspur soll zeigen, WARUM ein Aufruf entfiel."""
        orch = self._orchestrator({
            "collocate_stats": {"read_only": True, "concurrency_safe": True}})
        args = '{"term": "Rolle", "window": 5}'
        _, ereignisse = self._filtern(orch, [
            _tc("a", "collocate_stats", args),
            _tc("b", "collocate_stats", args),
        ])
        text = str(ereignisse)
        self.assertIn("duplicate_same_batch", text)
        self.assertNotIn(";", "Ein identischer Aufruf steht in diesem Block "
                              "bereits an, die redundante Berechnung wurde "
                              "ausgelassen.")


if __name__ == "__main__":
    unittest.main()
