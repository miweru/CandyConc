"""Copilot runtime controls: depth, factual lookup, cancellation, heuristics.

Alle Tests laufen OHNE LLM: der Fake-Client zaehlt jeden Aufruf. Gepinnt wird
die Produktinvarianten der Orchestrierung:

- Eine Faktfrage darf direkt aus validierter Tool-Evidenz antworten.
- Eine interpretative Analyse wird nicht durch ein globales LLM-Call-Limit
  vor Synthese und Verifikation abgeschnitten.
- Cancel stoppt die Call-Kette (kein weiterer LLM-Call, kein Tool-Dispatch).
- Ein neuer Turn desselben Owners cancelt noch laufende alte Turns.
- Stichproben-Anfragen (Seed) bekommen IMMER einen Heuristik-Kontrakt und
  laufen nie in contract_failed_closed (Live-P3-Regression).
"""

import pytest
import json
import unittest

# WICHTIG: NICHT aus test_orchestrator_grounding_runtime importieren. Dessen
# modul-globaler Loader ist reihenfolge-fragil (frueher Import bricht zwei
# seiner Tests). _real_copilot laedt die echten Module isoliert und stellt
# sys.modules wieder her.
from tests.ai._real_copilot import ReActOrchestrator


def _empty_requirements_response() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"response_requirements": []}),
                },
                "finish_reason": "stop",
            }
        ]
    }


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def _orchestrator(tool_names: list[str], call_llm, dispatch) -> "ReActOrchestrator":
    """Orchestrator mit deterministischer read-only-Klassifikation.

    Die Heuristik-Kontrakte filtern auf read-only-Tools. Im Test-Env haengt
    ``get_tool_runtime_info`` von Registry-Stubs ab, darum wird die
    Klassifikation hier explizit gesetzt (alle Test-Tools read-only).
    """
    orch = ReActOrchestrator([_tool(n) for n in tool_names], call_llm, dispatch)
    orch._tool_runtime_info = {
        name: {"read_only": True, "concurrency_safe": True}
        for name in tool_names
    }
    return orch


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


_COUNT_OUTPUT = {
    "status": "success",
    "total": 797,
    "query": "und",
    "mode": "plain",
    "partial": False,
    "corpus_tokens": 55550,
    "per_million": 14347.4,
}


class TestFactualLookup(unittest.IsolatedAsyncioTestCase):
    async def test_simple_count_turn_uses_direct_grounded_answer(self):
        llm_calls = 0
        dispatched: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            nonlocal llm_calls
            _ = exposed_tools, stream, kwargs
            llm_calls += 1
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                raise AssertionError(
                    "Ein simple-Turn mit Heuristik-Kontrakt darf keinen "
                    f"Grounding-Struktur-Schritt brauchen: {name}"
                )
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call("c1", "query_count", {"query": "und"})
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return dict(_COUNT_OUTPUT)

        orch = _orchestrator(
            ["query_count", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        result = await orch.run_async("Wie oft kommt das Wort 'und' im Korpus vor?")

        self.assertEqual(dispatched, ["query_count"])
        self.assertLessEqual(llm_calls, 2)
        # Formulierte Antwort mit der korrekten Zahl aus dem Tool-Output.
        self.assertIn("797", result)
        self.assertIn("und", result)
        self.assertNotIn('"status"', result)
        report = orch.turn_usage_report()
        self.assertNotIn("budget_class", report)
        self.assertLessEqual(report.get("llm_calls_used"), 2)
        self.assertEqual(report.get("transport_retries_used"), 0)
        self.assertIsInstance(report.get("elapsed_s"), float)


@pytest.mark.usefixtures("earlier_answer_path")  # prueft die Verifikation
class TestInterpretiveDepth(unittest.IsolatedAsyncioTestCase):
    async def test_interpretive_turn_reaches_verifier_beyond_four_calls(self):
        llm_calls = 0
        structured_names: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            nonlocal llm_calls
            _ = exposed_tools, stream, kwargs
            llm_calls += 1
            if json_schema is not None:
                name = json_schema.get("name", "")
                structured_names.append(name)
                if name == "answer_envelope":
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(
                                        {
                                            "claims": [],
                                            "answer_markdown": "",
                                            "evidence_gaps": [],
                                            "blocked_claims": [],
                                        }
                                    ),
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    }
                if name == "grounding_verdict":
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": json.dumps(
                                        {
                                            "verdict": "conservative_only",
                                            "accepted_claim_ids": [],
                                            "rejected_claim_ids": [],
                                            "reasons": [],
                                            "needs_retry": False,
                                        }
                                    ),
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    }
                # Alle uebrigen Struktur-Schritte antworten leer-konservativ.
                return {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "{}"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call(
                                        "c1",
                                        "collocate_stats",
                                        {"term": "Mensch"},
                                    )
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Prosa."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return {
                "status": "success",
                "rows": [
                    {"collocate": "Würde", "f": 12, "logdice": 9.1},
                    {"collocate": "Recht", "f": 8, "logdice": 8.2},
                ],
            }

        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        result = await orch.run_async("Berechne die Kollokationen für 'Mensch'.")

        report = orch.turn_usage_report()
        self.assertNotIn("budget_class", report)
        self.assertGreater(report.get("llm_calls_used"), 4)
        self.assertIn("answer_envelope", structured_names)
        self.assertIn("grounding_verdict", structured_names)
        self.assertTrue(result)
        self.assertNotIn('"status"', result)


class TestCooperativeCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_stops_llm_and_tool_chain(self):
        llm_calls = 0
        dispatched = 0

        orch_holder: dict = {}

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            nonlocal llm_calls
            _ = messages, exposed_tools, json_schema, stream, kwargs
            llm_calls += 1
            # Cancel trifft ein, WAEHREND der erste Call laeuft: danach darf
            # weder ein Tool-Dispatch noch ein weiterer LLM-Call passieren.
            orch_holder["orch"].request_cancel()
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call("c1", "query_count", {"query": "und"})
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            nonlocal dispatched
            dispatched += 1
            return dict(_COUNT_OUTPUT)

        orch = _orchestrator(
            ["query_count"],
            _call_llm,
            _dispatch,
        )
        orch_holder["orch"] = orch
        # H10/G1: bewusst OHNE Anfuehrungszeichen um das Wort, sonst
        # dispatcht die deterministische Schritt-1-Vorplanung query_count
        # legitim VOR dem ersten LLM-Call (und damit vor dem Cancel).
        # Getestet wird hier: nach dem Cancel passiert NICHTS mehr.
        result = await orch.run_async("Wie oft kommt das Wort und im Korpus vor?")

        self.assertEqual(llm_calls, 1)
        self.assertEqual(dispatched, 0)
        self.assertEqual(result, "")

    async def test_new_turn_cancels_running_turn_of_same_owner(self):
        from candyconc.services.backend import copilot_sessions

        class _FakeOrch:
            def __init__(self) -> None:
                self.cancelled = False

            def request_cancel(self) -> None:
                self.cancelled = True

        running = _FakeOrch()
        waiting = _FakeOrch()
        other_owner = _FakeOrch()

        s_running = copilot_sessions._register_active_orchestrator(
            "sess_running", running, "alice"
        )
        s_waiting = copilot_sessions._register_active_orchestrator(
            "sess_waiting", waiting, "alice"
        )
        s_other = copilot_sessions._register_active_orchestrator(
            "sess_other", other_owner, "bob"
        )
        try:
            # Nur der AKTIV laufende Turn (run_lock gehalten) wird gecancelt.
            self.assertTrue(s_running.run_lock.acquire(blocking=False))
            self.assertTrue(s_other.run_lock.acquire(blocking=False))
            cancelled = copilot_sessions._cancel_running_turns_for_owner("alice")
            self.assertEqual(cancelled, ["sess_running"])
            self.assertTrue(running.cancelled)
            self.assertTrue(s_running.cancel_requested.is_set())
            # Auf Approval wartende Session desselben Owners bleibt unberuehrt.
            self.assertFalse(waiting.cancelled)
            self.assertFalse(s_waiting.cancel_requested.is_set())
            # Fremder Owner bleibt unberuehrt, auch wenn er aktiv laeuft.
            self.assertFalse(other_owner.cancelled)
        finally:
            for sid in ("sess_running", "sess_waiting", "sess_other"):
                with copilot_sessions._ACTIVE_ORCH_LOCK:
                    copilot_sessions._active_orchestrators.pop(sid, None)


class TestSeedSampleHeuristicContract(unittest.IsolatedAsyncioTestCase):
    """Live-P3-Regression: Stichprobe mit Seed 7 -> nie contract_failed_closed."""

    def test_heuristic_contract_for_seed_sample_request(self):
        from candyconc.candyconc_copilot.analysis_grounding import (
            heuristic_analysis_contract,
        )

        contract = heuristic_analysis_contract(
            "Zieh eine Zufallsstichprobe von 5 Treffern für 'und' mit Seed 7.",
            available_tools=["run_cqlf_query", "query_count", "frequency_list"],
            read_only_tools=["run_cqlf_query", "query_count", "frequency_list"],
        )
        self.assertIsNotNone(contract)
        self.assertEqual(contract.mode, "tool_analysis")
        self.assertIn("run_cqlf_query", contract.allowed_tools)
        self.assertEqual(contract.analysis_family, "kwic_context")

    async def test_seed_sample_turn_never_calls_llm_classifier(self):
        structured_names: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = messages, exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                structured_names.append(name)
                raise AssertionError(
                    "Stichproben-Anfragen muessen den Heuristik-Kontrakt "
                    f"nehmen, nicht den LLM-Klassifikator: {name}"
                )
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call(
                                    "c1",
                                    "run_cqlf_query",
                                    {"query": "und", "sample": 5, "seed": 7},
                                )
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        sample_args: list[dict] = []

        async def _dispatch(tool_call, _token=None):
            args = json.loads(tool_call["function"]["arguments"])
            sample_args.append(args)
            return {
                "status": "success",
                "rows": [
                    {"left": "a", "kw": "und", "right": "b"},
                    {"left": "c", "kw": "und", "right": "d"},
                ],
                "total": 797,
                "sample": {"requested": 5, "drawn": 2, "seed": 7},
            }

        orch = _orchestrator(
            ["run_cqlf_query", "query_count"],
            _call_llm,
            _dispatch,
        )
        result = await orch.run_async(
            "Zieh eine Zufallsstichprobe von 5 Treffern für 'und' mit Seed 7."
        )

        self.assertEqual(structured_names, [])
        self.assertTrue(sample_args)
        # H11/B1: der freie Modus zieht fuer den einen Anfuehrungs-Term
        # ('und') query_count als vorgeplante Grundevidenz vor; der Seed
        # erreicht weiterhin die modellgeplante Stichprobe.
        self.assertEqual(
            sample_args[0],
            {"query": "und", "sample": 5, "seed": 7},
            "Der Vorplan emittiert die Stichproben-Parameter mit.",
        )
        seeded = [args for args in sample_args if "seed" in args]
        self.assertTrue(seeded, sample_args)
        self.assertEqual(seeded[0].get("seed"), 7)
        self.assertTrue(result)
        self.assertNotIn("contract_failed_closed", json.dumps(
            orch._active_analysis_contract, ensure_ascii=False
        ))


if __name__ == "__main__":
    unittest.main()


class TestEngineRetryTimeGateH11:
    def test_engine_retry_allowed_late_in_budget(self) -> None:
        # H10-Akzeptanz: Engine-Tode bei 65-80% Budgetverbrauch starben, weil
        # das 40%-Anteilstor Retries verbot. Engine-Ausfaelle pruefen jetzt
        # die absolute Restzeit (>=12s).
        from candyconc.candyconc_copilot import budgets

        # 120s-Budget, 95s verbraucht -> 25s Rest: Anteilstor saeht nein,
        # Engine-Tor sagt ja.
        assert not budgets.retry_time_remaining_ok(0.0, 120.0, now=95.0)
        assert budgets.engine_retry_time_ok(0.0, 120.0, now=95.0)

    def test_engine_retry_blocked_when_nearly_out_of_time(self) -> None:
        from candyconc.candyconc_copilot import budgets

        assert not budgets.engine_retry_time_ok(0.0, 120.0, now=110.0)

    def test_engine_retry_unlimited_without_deadline(self) -> None:
        from candyconc.candyconc_copilot import budgets

        assert budgets.engine_retry_time_ok(0.0, None, now=10_000.0)

    def test_orchestrator_gate_dispatch_pinned_in_source(self) -> None:
        # Quelltext-Pin (conftest-Alias exportiert die Klasse nur teilweise):
        # der Engine-Zweig prueft das absolute Engine-Zeittor DIREKT und
        # verbraucht das geteilte Transport-Budget nicht (Runde 5: dessen
        # Deckel von 2 liess 41 Turns am Modellwechsel sterben).
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2]
            / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        assert "_budgets.engine_retry_time_ok(state.started_at, state.max_time)" in src
        assert "_ra_consume_retry_budget(state, engine_recovery=True)" not in src
