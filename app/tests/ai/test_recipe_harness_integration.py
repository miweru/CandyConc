"""R2 Orchestrator-Integration des Rezept-Harness (offline, Fake-LLM).

Gepinnt werden die sieben Integrationen:

1. Prompt-Zusammenbau: build_static_core() ist der byte-identische
   Nachrichten-Praefix ueber alle Turns einer Session; alles Variable
   (ui_context, Korpus-Karte, Session-Stand, Rezept-Briefing) folgt strikt
   danach, das <turn_briefing> steht am Ende der System-Nachricht.
2. Rezept-Injektion: select_recipe laeuft ohne LLM-Call vor dem ersten
   Aufruf; recipe_id erscheint in copilot.status und in der done-Bilanz;
   ein strukturell gescheiterter Contract endet im freien Modus, nie in
   einer Ablehnung.
3. Referenz-Antwortpfad: Modellantworten laufen durch resolve_references;
   unaufloesbare Referenzen und ungebundene Zahlen loesen GENAU EINEN
   gezielten Repair-Call aus, danach ehrliche Platzhalter.
4. Severity-Durchleitung: advisories erscheinen als annotations im
   copilot.grounding-Event und blockieren nichts.
5. Gebuendelte Tool-Ausfuehrung: mehrere read-only-Calls eines Schritts
   laufen nebenlaeufig, die Evidenz-Reihenfolge bleibt deterministisch
   nach Anforderungsreihenfolge.
6. Drift-Anker: Fortsetzungsrunden tragen Ausgangsfrage-Echo + Abbruchsatz,
   der statische Kern nicht.
7. K1-Invarianten: done-Bilanz enthaelt weiterhin llm_calls_used,
   transport_retries_used, elapsed_s und NEU recipe_id.
"""

import asyncio
import json
import unittest

from tests.ai._real_copilot import ReActOrchestrator

from candyconc.candyconc_copilot.prompt_layout import build_static_core


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }

def _rumpf(text: str) -> str:
    """Die Antwort ohne ihre Anhaenge.

    Seit dem 2026-08-31 haengt an jeder Landung ein Experimentprotokoll
    ("### Experimente"), auf ausdrueckliche Anforderung: erst die Deutung,
    dann welche Experimente liefen und was herauskam. Diese Proben pruefen
    den ANTWORTTEXT, nicht die Anhaenge, und der Rumpf wird weiterhin auf
    Gleichheit geprueft, nicht auf ``startswith``. Eine Probe, die nur noch
    den Anfang vergleicht, laesst jede Verschmutzung dahinter durch.
    """
    return text.split("\n\n### ")[0]


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _orchestrator(tool_names, call_llm, dispatch, **kwargs) -> "ReActOrchestrator":
    orch = ReActOrchestrator([_tool(n) for n in tool_names], call_llm, dispatch, **kwargs)
    orch._tool_runtime_info = {
        name: {"read_only": True, "concurrency_safe": True}
        for name in tool_names
    }
    return orch


def _capture_events(orch: "ReActOrchestrator") -> list:
    events: list = []
    orch._emit_output = lambda bus, event: events.append(event)
    return events


def _classifier_bypass(messages):
    """H9/C1: Stufe-2-Router-Call (Mini-Prompt) mit 'frei' beantworten.

    Haelt die gescripteten Fakes dieser Datei call-stabil; das
    Router-Verhalten selbst pinnt tests/ai/test_recipe_router_hybrid_h9.py.
    """
    if messages and str(messages[0].get("content", "")).startswith(
        "Ordne die folgende korpuslinguistische Nutzerfrage"
    ):
        return {
            "choices": [
                {"message": {"role": "assistant", "content": "frei"}}
            ]
        }
    return None


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


_COUNT_OUTPUT = {
    "status": "success",
    "total": 797,
    "query": "und",
    "mode": "plain",
    "partial": False,
    "corpus_tokens": 55550,
    "per_million": 14347.4,
}


#: Die Vehikelfrage der Prompt-Proben.
#:
#: Sie hiess bis P11 "Wie oft kommt das Wort 'und' im Korpus vor?". Seit
#: der Sofortlandung (deterministic_landing.sofortlandungsentscheid)
#: endet eine reine Zaehlfrage nach der deterministischen Vorplanrunde
#: OHNE Modellaufruf, und dann wird auch kein System-Prompt mehr gebaut.
#: Diese drei Proben pruefen den PROMPT-Zusammenbau, nicht die Landung.
#: Sie brauchen also eine Frage, die das Modell erreicht.
#:
#: Die Deutungsbitte am Ende ist genau die Schranke, die der Harnisch
#: selbst zieht (_explicit_interpretation_request). Gekuerzt wurde nichts:
#: geprueft wird weiter derselbe Kern, dieselbe Suffix-Struktur und
#: dasselbe Rezept frequenz.
def _zaehlfrage_mit_deutung(wort: str) -> str:
    return (
        f"Wie oft kommt das Wort '{wort}' im Korpus vor? "
        "Sag mir bitte auch, wie du das einordnest."
    )


# Interpretation synthesis is a separate call with its own system text.
# These assertions inspect the tool-phase KV prefix.
_DEUTUNGSAUFRUF = "Du schreibst jetzt die FINALE ANTWORT"
_FERTIG = {"choices": [{"message": {"role": "assistant", "content": "Fertig."},
                        "finish_reason": "stop"}]}


class TestPromptAssembly(unittest.IsolatedAsyncioTestCase):
    """Integration 1: KV-Split mit byte-identischem Praefix."""

    async def test_two_turns_share_byte_identical_static_prefix(self):
        system_prompts: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                if json_schema.get("name") == "response_requirements":
                    return _empty_requirements_response()
                raise AssertionError(json_schema.get("name"))
            if messages[0]["content"].startswith(_DEUTUNGSAUFRUF):
                return _FERTIG
            system_prompts.append(messages[0]["content"])
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call(
                                        "c1", "query_count", {"query": "und"}
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
                        "message": {"role": "assistant", "content": "Fertig."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return dict(_COUNT_OUTPUT)

        orch = _orchestrator(["query_count"], _call_llm, _dispatch)
        await orch.run_async(_zaehlfrage_mit_deutung("und"))
        await orch.run_async(_zaehlfrage_mit_deutung("oder"))

        self.assertGreaterEqual(len(system_prompts), 2)
        core = build_static_core()
        first, last = system_prompts[0], system_prompts[-1]
        # Byte-identischer statischer Praefix, Turn-Variablen strikt danach.
        self.assertTrue(first.startswith(core))
        self.assertTrue(last.startswith(core))
        self.assertNotEqual(first, last)
        self.assertTrue(first.rstrip().endswith("</turn_briefing>"))
        self.assertTrue(last.rstrip().endswith("</turn_briefing>"))
        # Der Suffix des zweiten Turns traegt den Session-Stand des ersten.
        second_suffix = last[len(core):]
        self.assertIn("letzte_analysen", second_suffix)
        self.assertIn("query_count", second_suffix)
        # Keine Zeitstempel im statischen Kern (KV-Anker).
        self.assertEqual(first[: len(core)], last[: len(core)])

    async def test_system_prompt_stays_stable_within_one_turn(self):
        system_prompts: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                if json_schema.get("name") == "response_requirements":
                    return _empty_requirements_response()
                raise AssertionError(json_schema.get("name"))
            if messages[0]["content"].startswith(_DEUTUNGSAUFRUF):
                return _FERTIG
            system_prompts.append(messages[0]["content"])
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
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
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Fertig."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return dict(_COUNT_OUTPUT)

        orch = _orchestrator(["query_count"], _call_llm, _dispatch)
        await orch.run_async(_zaehlfrage_mit_deutung("und"))

        # Innerhalb EINES Turns bleibt die System-Nachricht byte-identisch
        # (der Prefill-Cache traegt ueber alle ReAct-Runden).
        self.assertGreaterEqual(len(system_prompts), 1)
        self.assertEqual(len(set(system_prompts)), 1)


class TestRecipeInjection(unittest.IsolatedAsyncioTestCase):
    """Integration 2 + 7: Rezept-Briefing, recipe_id in Events und Bilanz."""

    async def test_recipe_briefing_and_recipe_id_in_events_and_done(self):
        system_prompts: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                if json_schema.get("name") == "response_requirements":
                    return _empty_requirements_response()
                raise AssertionError(json_schema.get("name"))
            system_prompts.append(messages[0]["content"])
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Fertig.",
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call(
                                    "c1",
                                    "query_count",
                                    {"query": "Klimawandel"},
                                )
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return dict(_COUNT_OUTPUT)

        orch = _orchestrator(
            ["query_count", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        events = _capture_events(orch)
        result = await orch.run_async(
            "Wie häufig kommt 'Klimawandel' im Korpus vor, pro Million "
            "Tokens? Sag mir bitte auch, wie du das einordnest."
        )

        self.assertTrue(result)
        # Rezept-Briefing im Turn-Suffix, nicht im statischen Kern.
        core = build_static_core()
        self.assertIn("REZEPT frequenz", system_prompts[0])
        self.assertNotIn("REZEPT frequenz", core)
        # done-Bilanz: K1-Felder + NEU recipe_id.
        report = orch.turn_usage_report()
        self.assertEqual(report.get("recipe_id"), "frequenz")
        self.assertIn("llm_calls_used", report)
        self.assertIn("transport_retries_used", report)
        self.assertIsInstance(report.get("elapsed_s"), float)
        # copilot.status-Events tragen recipe_id, SOBALD es eines gibt.
        #
        # Die erste Marke ist "Vorlauf" und wird VOR dem Rezept-Routing
        # gesetzt. Dort ist noch keines gewaehlt, und ein leeres Feld ist
        # dort die Wahrheit. Stuende der Frame nach dem Routing, fiele
        # genau der Klassifikator aus der Zeitleiste, der die Stufe
        # ausmacht: am 273M-Korpus 189,5 bis 236,9 s, sechs bis zwoelf
        # Prozent des Turns, die eine Fassung mit "0 s" auswies.
        status_events = [
            event for event in events if event.get("event") == "copilot.status"
        ]
        self.assertTrue(status_events)
        self.assertEqual(status_events[0].get("stage"), "Vorlauf")
        self.assertEqual(status_events[0].get("recipe_id"), "")
        spaetere = status_events[1:]
        self.assertTrue(spaetere, "nach dem Vorlauf kam keine weitere Stufe")
        for event in spaetere:
            self.assertEqual(event.get("recipe_id"), "frequenz")

    async def test_free_mode_turn_reports_empty_recipe_id(self):
        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = messages, exposed_tools, stream, kwargs
            if json_schema is not None:
                raise AssertionError("kein Struktur-Schritt erwartet")
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Gern."},
                        "finish_reason": "stop",
                    }
                ]
            }

        orch = _orchestrator([], _call_llm, lambda call, token=None: {})
        result = await orch.run_async("Danke, das war alles!")

        self.assertEqual(result, "Gern.")
        self.assertEqual(orch.turn_usage_report().get("recipe_id"), "")


class TestFreeModeInsteadOfRefusal(unittest.IsolatedAsyncioTestCase):
    """Integration 2: contract_failed_closed -> Freier Modus, nie Ablehnung."""

    async def test_unparseable_contract_runs_free_with_honest_note(self):
        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                if json_schema.get("name") == "analysis_contract":
                    return {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "kein parsebares json",
                                },
                                "finish_reason": "stop",
                            }
                        ]
                    }
                return _empty_requirements_response()
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Im freien Modus: ohne Werkzeuglauf nenne "
                                "ich keine Trefferzahl."
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        orch = _orchestrator(
            ["frequency_list"],
            _call_llm,
            lambda call, token=None: {"status": "success", "rows": []},
        )
        result = await orch.run_async("Wie oft kommt Zeit vor?")

        self.assertNotIn("nicht sicher tool-gestützt", result)
        self.assertIn("freien Modus", result)
        self.assertTrue(
            any("grounding_free_mode" in item for item in orch._recent_recoveries)
        )
        self.assertEqual(
            orch._active_analysis_contract.get("grounding_output_mode"),
            "free_mode",
        )

    async def test_live_p3_seed_sample_question_never_refused(self):
        """Live-P3-Regression: die Stichprobenfrage endet nie in Ablehnung."""
        from candyconc.candyconc_copilot import recipe_runtime as _rr

        _classifier_prompt = _rr.build_recipe_classifier_prompt()

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            # H9.1: der Stufe-1-Pick ist hier rein familien-gestuetzt (kein
            # rezeptspezifisches Lexem, 'stichprobe' nur als Kompositum-
            # Innentreffer) und damit NICHT eindeutig -> Stufe 2 entscheidet.
            # Der Fake beantwortet den Klassifikator wie das Live-Modell.
            if messages and messages[0].get("content") == _classifier_prompt:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "gebrauch_kwic",
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            if json_schema is not None:
                if json_schema.get("name") == "response_requirements":
                    return _empty_requirements_response()
                # Selbst wenn ein Struktur-Schritt strukturell scheitert,
                # darf daraus keine Ablehnung werden.
                return {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "kaputt"},
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
                                        "run_cqlf_query",
                                        {"query": "und", "sample": 5, "seed": 7},
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
                        "message": {
                            "role": "assistant",
                            "content": "Stichprobe gezogen, Belege siehe KWIC.",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
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

        self.assertTrue(result)
        self.assertNotIn("nicht sicher tool-gestützt", result)
        self.assertEqual(orch.turn_usage_report().get("recipe_id"), "gebrauch_kwic")


class TestBundledToolExecution(unittest.IsolatedAsyncioTestCase):
    """Integration 5: ein LLM-Schritt, drei Tools, deterministische Evidenz."""

    async def test_three_tools_one_call_parallel_stable_order(self):
        llm_calls = 0
        max_concurrent = 0
        active = 0

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            bypass = _classifier_bypass(messages)
            if bypass is not None:
                return bypass
            nonlocal llm_calls
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                raise AssertionError("kein Struktur-Schritt erwartet")
            llm_calls += 1
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call("c1", "alpha_probe", {"n": 1}),
                                    _tool_call("c2", "beta_probe", {"n": 2}),
                                    _tool_call("c3", "gamma_probe", {"n": 3}),
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Fertig."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            nonlocal max_concurrent, active
            active += 1
            max_concurrent = max(max_concurrent, active)
            name = tool_call["function"]["name"]
            # Umgekehrte Laufzeiten: alpha am langsamsten, gamma sofort.
            delay = {"alpha_probe": 0.06, "beta_probe": 0.03}.get(name, 0.0)
            await asyncio.sleep(delay)
            active -= 1
            return {"status": "success", "total": 7, "tool": name}

        orch = _orchestrator(
            ["alpha_probe", "beta_probe", "gamma_probe"],
            _call_llm,
            _dispatch,
        )
        result = await orch.run_async("Prüfe kurz drei interne Sonden.")

        self.assertEqual(_rumpf(result), "Fertig.")
        # Und der Anhang ist da. Ohne diese Zeile pruefen die drei Proben
        # nur noch den Rumpf, und das Experimentprotokoll koennte spurlos
        # verschwinden, waehrend sie gruen bleiben. Alle drei Sonden stehen
        # darin, auch die, die sofort zurueckkam.
        self.assertIn("### Experimente", result)
        for name in ("alpha_probe", "beta_probe", "gamma_probe"):
            self.assertIn(name, result)
        # Ein LLM-Call fuer den Tool-Schritt, einer fuer die Antwort.
        self.assertEqual(llm_calls, 2)
        # Read-only-Tools laufen nebenlaeufig.
        self.assertEqual(max_concurrent, 3)
        # Drei Evidenzen, deterministisch in Anforderungsreihenfolge.
        evidence_ids = [item["id"] for item in orch._turn_evidence_items]
        self.assertEqual(
            evidence_ids,
            ["E_alpha_probe_1", "E_beta_probe_2", "E_gamma_probe_3"],
        )


class TestReferenceAnswerPath(unittest.IsolatedAsyncioTestCase):
    """Integration 3: resolve_references + genau ein Repair-Call."""

    def _make_orch(self, answers: list, dispatched: list | None = None):
        llm_call_counter = {"count": 0}

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            bypass = _classifier_bypass(messages)
            if bypass is not None:
                return bypass
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                raise AssertionError("kein Struktur-Schritt erwartet")
            llm_call_counter["count"] += 1
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call("c1", "alpha_probe", {"q": "und"})
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            content = answers.pop(0)
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            if dispatched is not None:
                dispatched.append(tool_call["function"]["name"])
            return {"status": "success", "total": 797, "per_million": 31.0}

        orch = _orchestrator(["alpha_probe"], _call_llm, _dispatch)
        return orch, llm_call_counter

    async def test_references_resolved_deterministically(self):
        orch, counter = self._make_orch(
            ["Es gibt {{ev:E_alpha_probe_1.total}} Treffer."]
        )
        result = await orch.run_async("Prüfe die interne Sonde für 'und'.")

        self.assertEqual(_rumpf(result), "Es gibt 797 Treffer.")
        self.assertEqual(counter["count"], 2)

    async def test_bare_number_triggers_exactly_one_repair_call(self):
        orch, counter = self._make_orch(
            [
                "Es gibt {{ev:E_alpha_probe_1.total}} Treffer und 4242 Phantome.",
                "Es gibt {{ev:E_alpha_probe_1.total}} Treffer.",
            ]
        )
        events = _capture_events(orch)
        result = await orch.run_async("Prüfe die interne Sonde für 'und'.")

        self.assertEqual(_rumpf(result), "Es gibt 797 Treffer.")
        self.assertNotIn("4242", result)
        # 1 Tool-Schritt + 1 Antwort + GENAU 1 Repair.
        self.assertEqual(counter["count"], 3)
        repair_events = [
            event
            for event in events
            if event.get("event") == "copilot.recovery"
            and event.get("recovery", {}).get("kind") == "reference_repair"
        ]
        self.assertEqual(len(repair_events), 1)
        self.assertIn("4242", repair_events[0]["recovery"]["message"])

    async def test_failed_repair_falls_back_to_honest_placeholders(self):
        bad = (
            "Es gibt {{ev:E_alpha_probe_1.gibtesnicht}} Treffer "
            "und 4242 Phantome."
        )
        orch, counter = self._make_orch([bad, bad])
        result = await orch.run_async("Prüfe die interne Sonde für 'und'.")

        # Genau ein Repair, danach ehrliche Platzhalter statt weiterer Calls.
        self.assertEqual(counter["count"], 3)
        self.assertIn("[Beleg fehlt]", result)
        self.assertNotIn("4242 Phantome", result)
        self.assertNotIn("{{ev:", result)

    async def test_user_supplied_numbers_are_not_fabrication(self):
        orch, counter = self._make_orch(
            ["Du fragst nach 5 Beispielen, die Sonde liefert Kontexte."]
        )
        result = await orch.run_async(
            "Prüfe die interne Sonde und zeig mir 5 Beispiele."
        )

        self.assertIn("5 Beispielen", result)
        self.assertEqual(counter["count"], 2)


class TestDriftAnchor(unittest.IsolatedAsyncioTestCase):
    """Integration 6: Ausgangsfrage-Echo nur in Fortsetzungsrunden."""

    async def test_continuation_round_carries_drift_anchor(self):
        rounds: list[list] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            bypass = _classifier_bypass(messages)
            if bypass is not None:
                return bypass
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                raise AssertionError("kein Struktur-Schritt erwartet")
            rounds.append(messages)
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call("c1", "alpha_probe", {"q": "x"})
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Fertig."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return {"status": "success", "total": 1}

        orch = _orchestrator(["alpha_probe"], _call_llm, _dispatch)
        question = "Prüfe die interne Sonde für den Drift-Anker."
        await orch.run_async(question)

        self.assertEqual(len(rounds), 2)
        anchor_line = (
            "Nur fortsetzen, wenn das nächste Werkzeug die Antwort oder "
            "ihre Reichweite ändern könnte."
        )
        first_round = json.dumps(rounds[0], ensure_ascii=False)
        second_round = json.dumps(rounds[1], ensure_ascii=False)
        self.assertNotIn(anchor_line, first_round)
        self.assertIn(anchor_line, second_round)
        self.assertIn("AUSGANGSFRAGE: " + question, second_round)
        # Nicht im statischen Kern.
        self.assertNotIn(anchor_line, build_static_core())


class TestSeverityAnnotations(unittest.TestCase):
    """Integration 4: advisories als annotations im copilot.grounding-Event."""

    def test_advisories_flow_into_grounding_event_annotations(self):
        orch = _orchestrator([], lambda m, t, **k: {}, lambda c, t=None: {})
        events = _capture_events(orch)
        orch._last_grounding_verdict = {
            "verdict": "pass",
            "advisories": {"claim_1": ["Hinweis A", "Hinweis B"]},
        }
        orch._ra_emit_grounding_event(
            None,
            "pass",
            analysis_family="term_frequency",
        )

        grounding_events = [
            event for event in events if event.get("event") == "copilot.grounding"
        ]
        self.assertEqual(len(grounding_events), 1)
        payload = grounding_events[0]["grounding"]
        self.assertEqual(
            payload["annotations"],
            [
                {"claim_id": "claim_1", "note": "Hinweis A"},
                {"claim_id": "claim_1", "note": "Hinweis B"},
            ],
        )
        # Annotationen blockieren nichts: Verdikt bleibt pass.
        self.assertEqual(payload["verdict"], "pass")

    def test_no_advisories_yield_empty_annotations_list(self):
        orch = _orchestrator([], lambda m, t, **k: {}, lambda c, t=None: {})
        events = _capture_events(orch)
        orch._last_grounding_verdict = {"verdict": "conservative_only"}
        orch._ra_emit_grounding_event(
            None,
            "conservative_only",
            analysis_family="open_research",
        )
        payload = events[0]["grounding"]
        self.assertEqual(payload["annotations"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
