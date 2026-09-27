"""H11 Bausteine B1+B2: generische Evidenz-Vorplanung und Split-QA-Breite.

Beides GENERISCHE Mechanik (kein Prompt-Tuning), offline mit Fake-LLM.

B1 — Evidenz-Vorplanung fuer exploration_meta UND den freien Modus:
Die H10-Vorplanung deckte frequenz/kwic/assoziation/profil/metadaten;
Exploration und der freie Modus planten Runde 1 weiter per LLM. Starb die
Engine frueh oder fragte das Modell zurueck, stand der Turn ohne jede
Evidenz da. Jetzt:

* exploration_meta traegt eine TERMLOSE Vorplanung als Rezept-DATEN
  (recipes_data): metadata_values(fields=['*']) plus
  frequency_list(group_by='pos') — beide immer ausfuehrbar.
* FREIER MODUS (kein Rezept): enthaelt die Frage GENAU EINEN
  Anfuehrungs-Term, laeuft query_count(query=TERM) deterministisch als
  Runde 1 (gleicher Orchestrator-Hook, rezeptlos:
  recipe_runtime.plan_free_mode_first_round). Kein Term oder mehrere
  Terme -> heutiges Verhalten. Damit hat JEDER Turn mit benanntem
  Gegenstand Grundevidenz, bevor das Modell spricht.

B2 — Split-QA-Detektor generisch verbreitert (Gutachter-Mandat
"deutlicher Generalisierungsrest"): is_explicit_split_qa_request feuert,
wenn (i) train UND test als eigenstaendige Tokens ODER ein
Partitions-Lexem (split/partition/aufteilung; teilmenge nur
datentechnisch) vorkommen UND (ii) ein Untersuchungs-/QA-Kontext
(untersuch/pruef/vergleich/unterschied/drift/auseinander/qa/technisch).
Konservativ: 'trainieren' und 'Der Test war schwer' feuern NIE
(Wortgrenzen); suchdefinierte Teilmengen (H10/G3) bleiben unberuehrt.
"""

import json
import unittest

from tests.ai._real_copilot import ReActOrchestrator
from tests.ai._real_copilot import orchestrator as orch_mod

from candyconc.candyconc_copilot.recipe_runtime import (
    _search_contrast_preplan_active,
    is_explicit_split_qa_request,
    plan_free_mode_first_round,
    plan_recipe_first_round,
    preplanned_tool_calls,
    recipe_precondition_status,
)
from candyconc.candyconc_copilot.recipes import RECIPES_BY_ID

# Freie Fragen (kein Rezept-Trigger, Stufe-2-Fake antwortet 'frei').
_FREE_ONE_TERM = "Sag mir etwas über ‚Solidarität‘ in diesem Material."
_FREE_TWO_TERMS = (
    "Sag mir etwas über ‚Angst‘ und ‚Hoffnung‘ in diesem Material."
)
_FREE_NO_TERM = "Sag mir etwas über Solidarität in diesem Material."

# Explorationsfrage (Stufe 1 eindeutig: Trigger + exploratorisch).
_EXPLORATION_FRAGE = "Untersuche das Korpus offen: Was fällt thematisch auf?"

# Karte mit NUR technischer split-Achse (Bench-artig, wie in H9/H10 gepinnt).
_CARD_SPLIT_ONLY = {
    "meta_fields": ["split", "register", "doc_id"],
    "date_fields": [],
    "meta_axes": [
        {"field": "split", "count": 2, "kind": "technical"},
        {"field": "register", "count": 1, "kind": "single"},
        {"field": "doc_id", "count": 2000, "kind": "doc_id"},
    ],
}


# --------------------------------------------------------------------------- #
# B1.1) Vorplan-Daten und reine Planungsfunktionen                             #
# --------------------------------------------------------------------------- #


class TestExplorationVorplanData(unittest.TestCase):
    def test_exploration_vorplan_schema_pin(self):
        # Schema-Pin: exakt die realen Parameternamen aus tool_wrappers.py
        # (metadata_values_tool(fields=...), frequency_list_tool(group_by=...)).
        self.assertEqual(
            tuple(RECIPES_BY_ID["exploration_meta"].vorplan),
            (
                {"tool": "metadata_values", "args": {"fields": ["*"]}},
                {"tool": "frequency_list", "args": {"group_by": "pos"}},
            ),
        )

    def test_exploration_plans_without_any_quote_slot(self):
        # Termlos: die Vorplanung braucht keine Anfuehrungszeichen.
        self.assertEqual(
            plan_recipe_first_round("exploration_meta", _EXPLORATION_FRAGE),
            [
                {"tool": "metadata_values", "args": {"fields": ["*"]}},
                {"tool": "frequency_list", "args": {"group_by": "pos"}},
            ],
        )

    def test_unavailable_tool_filters_not_blocks(self):
        calls = preplanned_tool_calls(
            "exploration_meta",
            _EXPLORATION_FRAGE,
            None,
            available_tools=["metadata_values", "run_cqlf_query"],
        )
        self.assertEqual(
            [c["function"]["name"] for c in calls], ["metadata_values"]
        )


class TestPlanFreeModeFirstRound(unittest.TestCase):
    def test_exactly_one_term_plans_query_count(self):
        self.assertEqual(
            plan_free_mode_first_round(_FREE_ONE_TERM),
            [{"tool": "query_count", "args": {"query": "Solidarität"}}],
        )

    def test_no_term_and_two_terms_plan_nothing(self):
        self.assertEqual(plan_free_mode_first_round(_FREE_NO_TERM), [])
        self.assertEqual(plan_free_mode_first_round(_FREE_TWO_TERMS), [])
        self.assertEqual(plan_free_mode_first_round(""), [])

    def test_dispatch_ready_free_mode_call(self):
        calls = preplanned_tool_calls(
            "",
            _FREE_ONE_TERM,
            None,
            available_tools=["query_count", "frequency_list"],
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "preplan_1")
        self.assertEqual(calls[0]["function"]["name"], "query_count")
        self.assertEqual(
            json.loads(calls[0]["function"]["arguments"]),
            {"query": "Solidarität"},
        )

    def test_free_mode_respects_gates_and_contract_bundle(self):
        self.assertEqual(
            preplanned_tool_calls(
                "",
                _FREE_ONE_TERM,
                None,
                available_tools=["query_count"],
                gated_tools={"query_count": "capability fehlt"},
            ),
            [],
        )
        self.assertEqual(
            preplanned_tool_calls(
                "",
                _FREE_ONE_TERM,
                None,
                available_tools=["query_count"],
                allowed_tools=["run_cqlf_query"],
            ),
            [],
        )

    def test_unknown_recipe_id_stays_recipe_path_not_free_mode(self):
        # Nur der rezeptLOSE Turn plant frei; eine unbekannte Rezept-id
        # degradiert wie bisher zu KEINER Vorplanung.
        self.assertEqual(
            preplanned_tool_calls(
                "gibtsnicht",
                _FREE_ONE_TERM,
                None,
                available_tools=["query_count"],
            ),
            [],
        )


# --------------------------------------------------------------------------- #
# B1.2) Effekt-Anker im Orchestrator (offline, Fake-LLM)                       #
# --------------------------------------------------------------------------- #


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
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


def _disable_contract_preflight(orch: "ReActOrchestrator") -> None:
    # Wie in test_h10_w1_preplan: der Offline-Fake degradiert den Kontrakt
    # zu einem leeren direct_answer-Bundle, darunter steht die Vorplanung
    # korrekt zurueck. Den Kontrakt-Bundle-Fall pinnt
    # TestPlanFreeModeFirstRound direkt.
    orch._ra_requires_grounding_contract = lambda: False


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


def _stop_response(text: str = "Fertige Antwort.") -> dict:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ]
    }


def _is_classifier_call(messages) -> bool:
    try:
        first = str((messages or [{}])[0].get("content", "") or "")
    except (AttributeError, IndexError, TypeError):
        return False
    return first.startswith(
        "Ordne die folgende korpuslinguistische Nutzerfrage"
    )


class _Timeline:
    def __init__(self) -> None:
        self.events: list = []

    def plain_llm(self) -> None:
        self.events.append(("llm", "plain"))

    def classifier_llm(self) -> None:
        self.events.append(("llm", "classifier"))

    def tool(self, name: str, args: dict) -> None:
        self.events.append(("tool", name, args))

    def tools_before_first_plain_llm(self) -> list:
        out = []
        for event in self.events:
            if event[0] == "llm" and event[1] == "plain":
                break
            if event[0] == "tool":
                out.append(event)
        return out


def _make_fakes(timeline: "_Timeline", tool_outputs: dict):
    async def _call_llm(
        messages, exposed_tools, json_schema=None, stream=False, **kwargs
    ):
        _ = exposed_tools, stream, kwargs
        if json_schema is not None:
            name = json_schema.get("name", "")
            if name == "response_requirements":
                return _empty_requirements_response()
            return _structured_step_response(name)
        if _is_classifier_call(messages):
            timeline.classifier_llm()
            return _stop_response("frei")
        timeline.plain_llm()
        return _stop_response()

    async def _dispatch(tool_call, _token=None):
        name = tool_call["function"]["name"]
        args = json.loads(tool_call["function"]["arguments"] or "{}")
        timeline.tool(name, args)
        return tool_outputs.get(name, {"status": "success", "rows": []})

    return _call_llm, _dispatch


async def _antwort_chunks(antwort: str):
    """Chunk-Quelle für den Streaming-Pfad (F-66: der Vorplan läuft nur
    streamend; der Dispatch selbst ist deterministisch)."""
    yield {"choices": [{"delta": {"role": "assistant", "content": antwort}}],
          "finish_reason": "stop"}


class TestPreplanEffectAnchorsH11(unittest.IsolatedAsyncioTestCase):
    async def test_exploration_round_one_runs_without_llm_planning(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(
            timeline,
            {
                "metadata_values": {
                    "status": "success",
                    "available_fields": ["register"],
                    "values": {"register": ["social"]},
                },
                "frequency_list": {
                    "status": "success",
                    "rows": [{"pos": "NOUN", "f": 9740}],
                },
            },
        )
        orch = _orchestrator(
            ["metadata_values", "frequency_list", "run_cqlf_query"],
            call_llm,
            dispatch,
        )
        _disable_contract_preflight(orch)
        result = await orch.run_async(_EXPLORATION_FRAGE, stream=True, chunks=_antwort_chunks("Es liegen keine Daten vor."))

        self.assertEqual(orch._active_recipe_id, "exploration_meta")
        first_tools = timeline.tools_before_first_plain_llm()
        # Runde 1 dispatcht beide termlosen Calls VOR jedem freien
        # LLM-Planungscall (0 LLM-Planung).
        self.assertEqual(
            [(event[1], event[2]) for event in first_tools],
            [
                ("metadata_values", {"fields": ["*"]}),
                ("frequency_list", {"group_by": "pos"}),
            ],
            timeline.events,
        )
        self.assertTrue(str(result or "").strip())

    async def test_free_mode_one_term_preplans_query_count(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(
            timeline,
            {
                "query_count": {
                    "status": "success",
                    "total": 42,
                    "per_million": 747.4,
                    "denominator_tokens": 56191,
                }
            },
        )
        orch = _orchestrator(
            ["query_count", "frequency_list", "run_cqlf_query"],
            call_llm,
            dispatch,
        )
        _disable_contract_preflight(orch)
        result = await orch.run_async(_FREE_ONE_TERM, stream=True, chunks=_antwort_chunks("Freie Antwort."))

        # Freier Modus (kein Rezept), trotzdem Grundevidenz in Runde 1.
        self.assertEqual(orch._active_recipe_id, "")
        first_tools = timeline.tools_before_first_plain_llm()
        self.assertEqual(
            first_tools,
            [("tool", "query_count", {"query": "Solidarität"})],
            timeline.events,
        )
        self.assertTrue(str(result or "").strip())

    async def test_free_mode_without_quotes_keeps_model_planning(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["query_count", "frequency_list"], call_llm, dispatch
        )
        _disable_contract_preflight(orch)
        await orch.run_async(_FREE_NO_TERM)

        self.assertEqual(orch._active_recipe_id, "")
        # Kein Anfuehrungs-Term -> KEINE Vorplanung (heutiges Verhalten).
        self.assertEqual(timeline.tools_before_first_plain_llm(), [])

    async def test_free_mode_two_terms_keep_model_planning(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["query_count", "frequency_list"], call_llm, dispatch
        )
        _disable_contract_preflight(orch)
        await orch.run_async(_FREE_TWO_TERMS)

        self.assertEqual(orch._active_recipe_id, "")
        # Mehrere Terme: Gegenstand nicht eindeutig -> nie raten.
        self.assertEqual(timeline.tools_before_first_plain_llm(), [])

    async def test_free_mode_preplan_failure_degrades_to_model_planning(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["query_count", "frequency_list"], call_llm, dispatch
        )
        _disable_contract_preflight(orch)
        original = orch_mod.preplan_with_contract  # H11.4: Naht umbenannt

        def _boom(*args, **kwargs):
            raise RuntimeError("kaputt")

        orch_mod.preplan_with_contract = _boom
        try:
            result = await orch.run_async(_FREE_ONE_TERM, stream=True, chunks=_antwort_chunks("Freie Antwort."))
        finally:
            orch_mod.preplan_with_contract = original

        # Nie hart scheitern wegen der Vorplanung.
        self.assertTrue(str(result or "").strip())
        self.assertEqual(timeline.tools_before_first_plain_llm(), [])


# --------------------------------------------------------------------------- #
# B2) Split-QA-Detektor: generische Breite, konservative Wortgrenzen           #
# --------------------------------------------------------------------------- #


class TestSplitQaDetectorBreadth(unittest.TestCase):
    def test_generic_positive_anchors(self):
        # Generisch formulierte Umschreibungen (NICHT aus der gefrorenen
        # Akzeptanz-Datei).
        self.assertTrue(
            is_explicit_split_qa_request(
                "Driften train und test lexikalisch auseinander?"
            )
        )
        self.assertTrue(
            is_explicit_split_qa_request(
                "Prüfe die Datenaufteilung als technische QA-Achse."
            )
        )
        self.assertTrue(
            is_explicit_split_qa_request(
                "Unterscheiden sich die Partitionen train/test in den "
                "Wortformen?"
            )
        )

    def test_h9_wording_still_fires(self):
        # Der H9-Realfall (Komposita: Trainingspartition/Datenaufteilung).
        self.assertTrue(
            is_explicit_split_qa_request(
                "Ist die Trainingspartition lexikalisch anders als die "
                "Testpartition? Prüfe ausdrücklich diese technische "
                "Aufteilung."
            )
        )

    def test_teilmenge_counts_only_data_technically(self):
        self.assertTrue(
            is_explicit_split_qa_request(
                "Prüfe die Teilmengen der Daten auf Drift."
            )
        )
        # Suchdefinierte Teilmengen (H10/G3) sind KEINE Split-QA.
        self.assertFalse(
            is_explicit_split_qa_request(
                "Vergleiche Äußerungen mit ‚Frau‘ und Äußerungen mit "
                "‚Mann‘ als suchdefinierte Teilmengen."
            )
        )

    def test_word_boundary_negative_anchors(self):
        # 'train' in anderem Sinn feuert NIE (Wortgrenzen), 'test' ebenso.
        self.assertFalse(
            is_explicit_split_qa_request("Wie trainiere ich ein Modell?")
        )
        self.assertFalse(
            is_explicit_split_qa_request("Der Test war schwer.")
        )
        self.assertFalse(
            is_explicit_split_qa_request(
                "Untersuche, wie man ein Modell trainiert."
            )
        )
        self.assertFalse(
            is_explicit_split_qa_request(
                "Der Test war schwer, bitte prüfe das."
            )
        )

    def test_partition_naming_without_qa_context_does_not_fire(self):
        self.assertFalse(
            is_explicit_split_qa_request(
                "Das Korpus enthält eine Aufteilung in train und test."
            )
        )
        self.assertFalse(is_explicit_split_qa_request(""))

    def test_broadened_wording_redeems_split_qa_precondition(self):
        # Integrationspin: die neue Umschreibung loest den
        # kontrast-Kurzschluss auf der split-only-Karte ein (Split-QA-
        # Rahmung), wie es die H9-Formulierung schon tat.
        status = recipe_precondition_status(
            "kontrast",
            _CARD_SPLIT_ONLY,
            "Driften train und test lexikalisch auseinander?",
        )
        self.assertFalse(status["short_circuit"])
        self.assertIn("Split-QA", status.get("briefing_note", ""))

    def test_search_defined_contrast_gate_unaffected(self):
        # H10/G3 bleibt unberuehrt: der suchdefinierte Kontrast plant
        # weiter vor, obwohl 'Teilmengen' und 'vergleich' in der Frage
        # stehen und die Karte eine technische Achse traegt.
        self.assertTrue(
            _search_contrast_preplan_active(
                "Vergleiche Äußerungen mit ‚Frau‘ und Äußerungen mit "
                "‚Mann‘ als suchdefinierte Teilmengen.",
                _CARD_SPLIT_ONLY,
            )
        )


if __name__ == "__main__":
    unittest.main()
