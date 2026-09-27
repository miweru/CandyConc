# A2: der Test haelt den ZUSTAND fest, nicht den Wortlaut.
import pytest
import contextlib
import sys

from unittest import mock

from candyconc.candyconc_copilot import (
    recipe_runtime as recipe_runtime_mod,
)
from candyconc.candyconc_copilot.recipe_runtime import (  # noqa: E402
    FINAL_POLISH_HONESTY_LINE,
)
"""Härtungs-Runde 2 aus den Live-Befunden der Eval-Runde 2 (offline, Fake-LLM).

Runde 1 (Commit 775076bafd) schloss die Runden-Leitplanke und die Korpus-Karte.
Runde 2 diagnostizierte zwei verbliebene Integrationslücken; diese Datei pinnt
die vier Fixes dagegen:

1. WRAP-UP-LANDUNG = COMPLETED, NICHT TIMEOUT (Bug A): wenn die
   Runden-Leitplanke einen Turn zur Antwort zwingt und die Finalisierungs-
   Synthese danach einen Fehler wirft, finalisiert der Turn deterministisch
   aus der Turn-Evidenz und landet als regulaerer completed-Abschluss ohne
   Warnbanner (statt eines Server-Salvage mit done_status='timeout').
2. REZEPT-VORBEDINGUNGEN DETERMINISTISCH KURZSCHLIESSEN (Bug B): verlauf ohne
   Datumsfeld antwortet ehrlich aus dem Rezept-Feld, 0 Tool-Runden, 0
   LLM-Calls; mit Datumsfeld laeuft es normal. kontrast hat einen
   docset-Fallback und schliesst nie hart kurz.
3. VERIFIER-SKIP LIVE REPARIEREN (Bug B, zweite Ebene): der LLM-Verifier
   prueft die Restzeit VOR JEDEM Struktur-Schritt; kippt sie mitten im
   Protokoll, bricht er ab und der deterministische Referenz-Pfad finalisiert
   (verifier_skipped_time_budget).
4. SALVAGE-BANNER NUR BEI ECHTEM TIMEOUT: der '⚠️ Zeitlimit erreicht'-Text und
   der done_status='timeout' erscheinen ausschliesslich beim echten
   Wall-Clock-Backstop, nicht bei Runden-/Schritt-Kappung oder einem
   Nicht-Zeit-Fehler.
"""

import json
import unittest

from tests.ai._real_copilot import ReActOrchestrator
from tests.ai._real_copilot import orchestrator as orch_mod

from candyconc.candyconc_copilot.recipe_runtime import (
    corpus_card_from_ui_context,
    max_tool_rounds_for_recipe,
    precondition_unmet_answer,
    recipe_precondition_status,
)
from candyconc.candyconc_copilot.recipes import RECIPES_BY_ID


_BANNER = "Zeitlimit erreicht"
_VERIFIER_STEP_SCHEMAS = {"observed_facts", "answer_envelope", "grounding_verdict"}


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _orchestrator(tool_names, call_llm, dispatch, **kwargs) -> "ReActOrchestrator":
    orch = ReActOrchestrator(
        [_tool(n) for n in tool_names], call_llm, dispatch, **kwargs
    )
    orch._tool_runtime_info = {
        name: {"read_only": True, "concurrency_safe": True}
        for name in tool_names
    }
    return orch


def _capture_events(orch: "ReActOrchestrator") -> list:
    events: list = []
    orch._emit_output = lambda bus, event: events.append(event)
    return events


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


def _structured_step_response(name: str) -> dict:
    if name == "answer_envelope":
        content = json.dumps(
            {
                "claims": [],
                "answer_markdown": "",
                "evidence_gaps": [],
                "blocked_claims": [],
            }
        )
    elif name == "grounding_verdict":
        content = json.dumps(
            {
                "verdict": "conservative_only",
                "accepted_claim_ids": [],
                "rejected_claim_ids": [],
                "reasons": [],
                "needs_retry": False,
            }
        )
    else:
        content = "{}"
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ]
    }


_COLLOCATE_OUTPUT = {
    "status": "success",
    "rows": [
        {"collocate": "Würde", "f": 12, "logdice": 9.1},
        {"collocate": "Recht", "f": 8, "logdice": 8.2},
    ],
}


# --------------------------------------------------------------------------- #
# Fix 2: Rezept-Vorbedingungen                                                 #
# --------------------------------------------------------------------------- #


class TestPreconditionSchema(unittest.TestCase):
    def test_verlauf_has_hard_date_precondition(self):
        recipe = RECIPES_BY_ID["verlauf"]
        self.assertEqual(dict(recipe.precondition), {"requires": "date_field"})
        self.assertIn("{alternative}", recipe.precondition_unmet_text)
        self.assertTrue(recipe.precondition_alternative.strip())

    def test_kontrast_has_meta_axis_precondition(self):
        # Haertung r4, Fix 2: kontrast braucht eine Achse mit >=2 Werten. Ohne
        # eine solche schliesst der Turn deterministisch kurz (kein Fallback,
        # der Docset-ueber-Suche-Ausweg steht im Kurzschluss-Text).
        recipe = RECIPES_BY_ID["kontrast"]
        self.assertEqual(dict(recipe.precondition), {"requires": "meta_axis"})
        self.assertIn("{alternative}", recipe.precondition_unmet_text)
        self.assertTrue(recipe.precondition_alternative.strip())

    def test_other_recipes_have_no_precondition(self):
        for rid in ("assoziation", "frequenz", "gebrauch_kwic", "profil"):
            self.assertFalse(dict(RECIPES_BY_ID[rid].precondition), rid)


class TestPreconditionStatus(unittest.TestCase):
    def test_verlauf_short_circuits_without_date_field(self):
        card = {"meta_fields": ["source", "model"], "date_fields": []}
        status = recipe_precondition_status("verlauf", card)
        self.assertTrue(status["short_circuit"])
        self.assertEqual(status["reason"], "date_field")
        self.assertEqual(status["alternative"], "Frequenz nach Register/Quelle.")

    def test_verlauf_runs_normally_with_date_field(self):
        card = {"meta_fields": ["jahr", "source"], "date_fields": ["jahr"]}
        self.assertFalse(
            recipe_precondition_status("verlauf", card)["short_circuit"]
        )

    def test_unknown_meta_inventory_never_short_circuits(self):
        # Karte weist ihr Meta-Inventar NICHT aus -> kein False-Negative.
        self.assertFalse(
            recipe_precondition_status("verlauf", {})["short_circuit"]
        )
        self.assertFalse(
            recipe_precondition_status(
                "verlauf", {"date_fields": []}
            )["short_circuit"]
        )

    def test_kontrast_without_cardinality_never_short_circuits(self):
        # Ohne ausgewiesene Kardinalitaet (kein meta_axes) keine Achsen-
        # Entscheidung -> kein Kurzschluss (kein False-Negative).
        card = {"meta_fields": ["register"], "date_fields": []}
        self.assertFalse(
            recipe_precondition_status("kontrast", card)["short_circuit"]
        )

    def test_precondition_answer_fills_alternative(self):
        text = precondition_unmet_answer("verlauf", "Frequenz nach Register.")
        self.assertIn("kein Datumsfeld", text)
        self.assertIn("Frequenz nach Register.", text)
        self.assertNotIn("{alternative}", text)


class TestPreconditionShortCircuit(unittest.IsolatedAsyncioTestCase):
    async def test_verlauf_without_date_field_short_circuits(self):
        dispatched: list[str] = []
        llm_schemas: list = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = messages, exposed_tools, stream, kwargs
            llm_schemas.append(json_schema.get("name") if json_schema else "plain")
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "x"},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return {"status": "success", "rows": []}

        orch = _orchestrator(
            ["trend_analysis", "metadata_values", "frequency_list"],
            _call_llm,
            _dispatch,
            ui_context={
                "corpus_meta_fields": ["source", "model"],
                "corpus_date_fields": [],
            },
        )
        events = _capture_events(orch)
        result = await orch.run_async(
            "Zeige den Zeitverlauf von 'Arbeit' im Korpus."
        )

        self.assertEqual(orch._active_recipe_id, "verlauf")
        # 0 Tool-Runden, 0 LLM-Calls -> deterministischer Kurzschluss.
        self.assertEqual(dispatched, [])
        self.assertEqual(llm_schemas, [])
        self.assertEqual(orch.turn_usage_report().get("llm_calls_used"), 0)
        self.assertEqual(orch.turn_usage_report().get("recipe_id"), "verlauf")
        # Ehrliche Antwort aus dem Rezept-Feld, kein Warnbanner.
        self.assertIn("kein Datumsfeld", result)
        self.assertIn("Frequenz nach Register/Quelle", result)
        self.assertNotIn(_BANNER, result)
        recovery_kinds = [
            event.get("recovery", {}).get("kind")
            for event in events
            if event.get("event") == "copilot.recovery"
        ]
        self.assertIn("recipe_precondition_unmet", recovery_kinds)

    async def test_verlauf_with_date_field_runs_normally(self):
        dispatched: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = messages, exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                return _structured_step_response(name)
            # Sofort final antworten (keine Tool-Runde) -> der Turn laeuft den
            # normalen Kontrakt-Pfad, NICHT den Vorbedingungs-Kurzschluss.
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Verlauf."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return {"status": "success", "rows": []}

        orch = _orchestrator(
            ["trend_analysis", "metadata_values", "frequency_list"],
            _call_llm,
            _dispatch,
            ui_context={
                "corpus_meta_fields": ["jahr", "source"],
                "corpus_date_fields": ["jahr"],
            },
        )
        _capture_events(orch)
        result = await orch.run_async(
            "Zeige den Zeitverlauf von 'Arbeit' im Korpus."
        )

        self.assertEqual(orch._active_recipe_id, "verlauf")
        self.assertNotIn("kein Datumsfeld", result)
        # Der Kontrakt-Preflight lief -> mindestens ein LLM-Call.
        self.assertGreaterEqual(
            orch.turn_usage_report().get("llm_calls_used", 0), 1
        )


# --------------------------------------------------------------------------- #
# Fix 1: Wrap-up-Landung = completed, nicht timeout                            #
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def _rundenschranke(wert: int):
    """Setzt die Rundenschranke, egal unter welchem Namen das Modul liegt.

    DIE ERSTE FASSUNG PATCHTE EIN MODULOBJEKT und war einzeln gruen, im
    vollen Verzeichnislauf aber rot. Der Grund ist die Doppelablage dieses
    Baums: ``recipe_runtime`` steht in ``sys.modules`` sowohl als
    ``candyconc.candyconc_copilot.recipe_runtime`` als auch als
    ``candyconc_copilot.recipe_runtime``. Welche Fassung der Orchestrator
    benutzt, haengt an der Importreihenfolge, und die haengt daran, welche
    anderen Proben vorher liefen.

    Deshalb wird hier JEDE Fassung gesetzt und danach jede
    zurueckgestellt.
    """
    ziele = [
        m for name, m in list(sys.modules.items())
        if name.endswith("recipe_runtime")
        and hasattr(m, "max_tool_rounds_for_recipe")
    ]
    assert ziele, "kein recipe_runtime in sys.modules"
    alt = [(m, m.max_tool_rounds_for_recipe) for m in ziele]
    for m in ziele:
        m.max_tool_rounds_for_recipe = lambda _rid, _w=wert: _w
    try:
        yield
    finally:
        for m, f in alt:
            m.max_tool_rounds_for_recipe = f


class TestWrapupLandsCompleted(unittest.IsolatedAsyncioTestCase):
    async def test_finalize_error_after_round_cap_degrades_to_completed(self):
        """assoziation: 3 Tool-Runden, dann wirft die Verifier-Synthese.

        Frueher propagierte diese Ausnahme bis zum Server (done_status=
        'timeout', Salvage-Banner). Jetzt finalisiert der Turn deterministisch
        aus der Turn-Evidenz und liefert eine nicht-leere geerdete Antwort
        OHNE Warnbanner.
        """
        dispatched: list[str] = []
        plain_rounds = 0

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            nonlocal plain_rounds
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                if name in _VERIFIER_STEP_SCHEMAS:
                    # Transport-/Zeitfehler mitten in der Finalisierung.
                    raise RuntimeError("simulierter Verifier-Transportfehler")
                return _structured_step_response(name)
            has_wrapup = any(
                orch_mod.TOOL_ROUND_WRAPUP_LINE in str(m.get("content") or "")
                for m in messages
            )
            if has_wrapup:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Analysebericht aus der Evidenz.",
                            },
                            "finish_reason": "stop",
                        }
                    ]
                }
            plain_rounds += 1
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call(
                                    f"c{plain_rounds}",
                                    "collocate_stats",
                                    {"term": f"Arbeit{plain_rounds}"},
                                )
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return dict(_COLLOCATE_OUTPUT)

        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        _capture_events(orch)
        # Die Schranke setzt diese Probe selbst. Ihr Gegenstand ist die
        # LANDUNG nach der Schranke (completed statt Timeout-Salvage),
        # nicht der Produktionswert der Schranke.
        with _rundenschranke(3):
            result = await orch.run_async(
                "Welche Kollokationen hat 'Arbeit' im Korpus?"
            )

        self.assertEqual(orch.turn_usage_report().get("recipe_id"), "assoziation")
        # Runden-Leitplanke: genau 3 Dispatches, gegen die oben in dieser
        # Probe gesetzte Schranke.
        self.assertEqual(len(dispatched), 3, dispatched)
        # Nicht-leere, geerdete Antwort trotz Verifier-Fehler -> reply != None
        # am Server -> completed. Der Server-Timeout-Banner taucht NIE im
        # Orchestrator-Ergebnis auf.
        self.assertTrue(result.strip())
        self.assertNotIn(_BANNER, result)
        # Ehrlicher, geerdeter Befund aus den sichtbaren Tool-Ergebnissen
        # (rows_seen bleibt), NICHT der Timeout-Salvage-Text.
        self.assertIn("rows_seen", result)
        self.assertIn("direkt belegten Beobachtungen", result)
        # Ehrlicher Hinweis auf die abgebrochene Verifikation, kein Zeitbanner.
        self.assertIn("vor der vollstaendigen Verifikation beendet", result)

    async def test_max_steps_without_time_overrun_returns_completed(self):
        """max_steps ohne Zeitueberschreitung -> nicht-leere Antwort, kein Banner."""
        plain_calls = 0

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            nonlocal plain_calls
            _ = messages, exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                if name == "response_requirements":
                    return _empty_requirements_response()
                return _structured_step_response(name)
            plain_calls += 1
            # Immer weiter Tools anfordern -> die max_steps-Grenze greift.
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                _tool_call(
                                    f"c{plain_calls}",
                                    "collocate_stats",
                                    {"term": f"Arbeit{plain_calls}"},
                                )
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return dict(_COLLOCATE_OUTPUT)

        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        _capture_events(orch)
        # Grosszuegiges Zeitbudget: die Kappung ist max_steps, NICHT die Zeit.
        result = await orch.run_async(
            "Welche Kollokationen hat 'Arbeit' im Korpus?",
            max_steps=4,
            max_time=600.0,
        )
        self.assertTrue(result.strip())
        self.assertNotIn(_BANNER, result)


# --------------------------------------------------------------------------- #
# Fix 3: Verifier-Skip greift auch mitten im Protokoll                         #
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("earlier_answer_path")  # prueft die Verifikation
class TestVerifierSkipMidProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_skip_fires_when_budget_flips_during_verification(self):
        """Restzeit ist beim Betreten der Finalisierung noch ok, kippt aber vor
        dem ersten Verifier-Struktur-Schritt. Der Skip MUSS trotzdem greifen."""
        structured_names: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                structured_names.append(name)
                if name == "response_requirements":
                    return _empty_requirements_response()
                return _structured_step_response(name)
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call("c1", "collocate_stats", {"term": "Mensch"})
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
                            "content": (
                                "Top-Kollokat ist "
                                "{{ev:E_collocate_stats_1.rows[0].collocate}}. "
                                "Deutung: das Umfeld ist wertend."
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            return dict(_COLLOCATE_OUTPUT)

        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        events = _capture_events(orch)

        # Restzeit-Orakel: der erste Aufruf (Betreten der Finalisierung) meldet
        # ok, JEDER weitere (vor einem Struktur-Schritt) meldet zu knapp.
        real_budgets = orch_mod._budgets
        original = real_budgets.verifier_time_remaining_ok
        calls = {"n": 0}

        def _flipping_ok(*a, **k):
            calls["n"] += 1
            return calls["n"] <= 1

        real_budgets.verifier_time_remaining_ok = _flipping_ok
        try:
            result = await orch.run_async(
                "Berechne die Kollokationen für 'Mensch'."
            )
        finally:
            real_budgets.verifier_time_remaining_ok = original

        # Mind. zweimal geprueft (Betreten + vor einem Struktur-Schritt).
        self.assertGreaterEqual(calls["n"], 2)
        # Der LLM-Verifier lief NICHT durch: kein answer_envelope/-verdict.
        self.assertNotIn("answer_envelope", structured_names)
        self.assertNotIn("grounding_verdict", structured_names)
        # Referenz-Pfad hat den Entwurf deterministisch aufgeloest.
        self.assertIn("Würde", result)
        self.assertNotIn("{{ev:", result)
        # H9/C2 (V11b): Skip-Hinweis nur noch als Event-Annotation, im Text
        # steht der eine ehrliche Satz.
        self.assertNotIn("LLM-Verifikation übersprungen (Zeitbudget)", result)
        self.assertIn(
            FINAL_POLISH_HONESTY_LINE,
            result,
        )
        self.assertNotIn(_BANNER, result)
        skipped = [
            event.get("grounding", {})
            for event in events
            if event.get("event") == "copilot.grounding"
            and event.get("grounding", {}).get("verdict")
            == "verifier_skipped_time_budget"
        ]
        self.assertTrue(skipped)

    async def test_verifier_phase_flag_does_not_gate_preflight_or_tools(self):
        """Der Zeit-Guard darf NUR in der Verifikationsphase greifen, nie beim
        Kontrakt-Preflight oder in der Tool-Schleife (beide laufen frueher)."""
        dispatched: list[str] = []
        structured_names: list[str] = []

        async def _call_llm(messages, exposed_tools, json_schema=None, stream=False, **kwargs):
            _ = exposed_tools, stream, kwargs
            if json_schema is not None:
                name = json_schema.get("name", "")
                structured_names.append(name)
                if name == "response_requirements":
                    return _empty_requirements_response()
                return _structured_step_response(name)
            has_tool_result = any(m.get("role") == "tool" for m in messages)
            if not has_tool_result:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    _tool_call("c1", "collocate_stats", {"term": "Mensch"})
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Bericht."},
                        "finish_reason": "stop",
                    }
                ]
            }

        async def _dispatch(tool_call, _token=None):
            dispatched.append(tool_call["function"]["name"])
            return dict(_COLLOCATE_OUTPUT)

        orch = _orchestrator(
            ["collocate_stats", "run_cqlf_query", "frequency_list"],
            _call_llm,
            _dispatch,
        )
        _capture_events(orch)

        real_budgets = orch_mod._budgets
        original = real_budgets.verifier_time_remaining_ok
        # Restzeit immer zu knapp: Preflight und Tool-Schleife laufen dennoch
        # (NICHT in der Verifikationsphase), nur der Verifier wird ausgelassen.
        real_budgets.verifier_time_remaining_ok = lambda *a, **k: False
        try:
            result = await orch.run_async(
                "Berechne die Kollokationen für 'Mensch'."
            )
        finally:
            real_budgets.verifier_time_remaining_ok = original

        # Der Guard hat weder den Preflight (structured steps) noch die
        # Tool-Runde blockiert.
        self.assertEqual(dispatched, ["collocate_stats"])
        # Verifikation ausgelassen -> der deterministische Referenz-Pfad landet.
        self.assertNotIn("answer_envelope", structured_names)
        self.assertNotIn("grounding_verdict", structured_names)
        # H9/C2 (V11b): Skip-Hinweis wandert in die Event-Annotationen.
        self.assertNotIn("LLM-Verifikation übersprungen (Zeitbudget)", result)
        self.assertIn(
            FINAL_POLISH_HONESTY_LINE,
            result,
        )
        self.assertNotIn(_BANNER, result)


# --------------------------------------------------------------------------- #
# Fix 4: Salvage-Banner nur bei echtem Timeout                                 #
# --------------------------------------------------------------------------- #


class TestSalvageBannerGating(unittest.TestCase):
    def _salvage(self, timed_out: bool):
        from candyconc.services.backend import server as _server

        class _Orch:
            def build_salvage_markdown(self):
                return "## Befund\n- rows_seen=0"

        return _server._copilot_timeout_salvage_text(
            "",
            None,
            _Orch(),
            timed_out=timed_out,
        )

    def test_real_timeout_keeps_banner(self):
        text = self._salvage(timed_out=True)
        self.assertIsNotNone(text)
        self.assertIn(_BANNER, text)
        self.assertIn("rows_seen=0", text)

    def test_non_time_error_salvage_has_no_timeout_banner(self):
        text = self._salvage(timed_out=False)
        self.assertIsNotNone(text)
        self.assertNotIn(_BANNER, text)
        # Die belegten Ergebnisse werden dennoch geliefert.
        self.assertIn("rows_seen=0", text)

    def test_partial_text_banner_gated_on_timeout(self):
        from candyconc.services.backend import server as _server

        timed = _server._copilot_timeout_salvage_text(
            "Teilbefund.", None, object(), timed_out=True
        )
        untimed = _server._copilot_timeout_salvage_text(
            "Teilbefund.", None, object(), timed_out=False
        )
        self.assertIn(_BANNER, timed)
        self.assertNotIn(_BANNER, untimed)
        self.assertIn("Teilbefund.", untimed)


class TestCorpusCardSharedSeam(unittest.TestCase):
    def test_card_from_ui_context_carries_meta_and_date_fields(self):
        card = corpus_card_from_ui_context(
            {
                "corpus_meta_fields": ["source", "model"],
                "corpus_date_fields": [],
            }
        )
        self.assertIn("meta_fields", card)
        self.assertEqual(card["meta_fields"], ["source", "model"])
        self.assertEqual(card["date_fields"], [])


if __name__ == "__main__":
    unittest.main()
