"""H10 Paket W3 (G3): suchdefinierte Kontraste (offline, Fake-LLM).

Gutachter-Befund (drittes Verdikt, h10_query_contrast): 'Vergleiche
Aeusserungen mit zwei zitierten Termen als suchdefinierte Teilmengen' wurde
in 0 Calls deterministisch abgewiesen (keine Metadaten-Achse), obwohl
create_docset(query=...) den Weg docsetA + docsetB -> keyness laengst kann
und der Kurzschluss-Text ihn selbst anbietet.

Der generische Fix:

1. ``recipe_precondition_status`` (kontrast): nennt die Frage ZWEI Terme in
   Anfuehrungszeichen in einer Vergleichskonstruktion, gilt die
   meta_axis-Vorbedingung als ueber den Docset-per-Suche-Pfad ERFUELLT
   (KEIN Kurzschluss), das Briefing broadcastet den keyness-Folgeweg.
2. Vorplanung (W1-Mechanik): Runde 1 sind die beiden
   create_docset(query=Term, label=Term)-Calls, deterministisch geplant.
   Das Gate (``_search_contrast_preplan_active``) laesst Achsen-Kontraste
   und Split-QA unveraendert (Modellplanung wie heute).
3. Ein Term ohne Achse -> heutiger ehrlicher Kurzschluss bleibt.
"""

import json
import unittest

from tests.ai._real_copilot import ReActOrchestrator

from candyconc.candyconc_copilot.recipe_runtime import (
    _search_contrast_preplan_active,
    extract_primary_terms,
    is_search_defined_contrast,
    plan_recipe_first_round,
    precondition_unmet_answer,
    preplanned_tool_calls,
    recipe_precondition_status,
    search_contrast_briefing_note,
)

# Frageform des Dossier-Realfalls (typografische Anfuehrungszeichen).
_SEARCH_CONTRAST_FRAGE = (
    "Vergleiche Äußerungen mit ‚Frau‘ und Äußerungen mit ‚Mann‘ "
    "als suchdefinierte Teilmengen."
)

# Bench-artige Karte: technische Partition, aber KEINE kontrastierbare Achse.
_CARD_NO_AXIS = {
    "meta_fields": ["model", "register", "split", "doc_id"],
    "date_fields": [],
    "meta_axes": [
        {"field": "model", "count": 1, "kind": "single"},
        {"field": "register", "count": 1, "kind": "single"},
        {"field": "split", "count": 2, "kind": "technical"},
        {"field": "doc_id", "count": 2000, "kind": "doc_id"},
    ],
}

# 142M-artige Karte: echte kontrastierbare Achse vorhanden.
_CARD_WITH_AXIS = {
    "meta_fields": ["register"],
    "date_fields": [],
    "meta_axes": [{"field": "register", "count": 6, "kind": "axis"}],
}

# Karte ohne Kardinalitaet: Achsenlage unbekannt.
_CARD_NO_CARDINALITY = {"meta_fields": ["register"], "date_fields": []}


# --------------------------------------------------------------------------- #
# 0) Slot-Extraktion: gemischt getippte Anfuehrungspaare (Dossier: ‚Frau')     #
# --------------------------------------------------------------------------- #


async def _antwort_chunks(antwort: str):
    """Chunk-Quelle für den Streaming-Pfad (F-66: der Vorplan läuft nur
    streamend; der Dispatch selbst ist deterministisch)."""
    yield {"choices": [{"delta": {"role": "assistant", "content": antwort}}],
          "finish_reason": "stop"}


class TestMixedQuotePairs(unittest.TestCase):
    def test_typographic_opener_with_straight_closer(self):
        self.assertEqual(
            extract_primary_terms("Vergleiche ‚Frau' und ‚Mann' als Teilmengen."),
            ["Frau", "Mann"],
        )
        self.assertEqual(extract_primary_terms('Wie oft kommt „Frau" vor?'), ["Frau"])

    def test_strict_pair_wins_over_mixed_at_same_opener(self):
        # ‚geht's um Geld‘ darf nicht am inneren Apostroph zu 'geht' zerfallen.
        self.assertEqual(
            extract_primary_terms("Suche ‚geht's um Geld‘ im Korpus."),
            ["geht's um Geld"],
        )

    def test_w1_behaviour_unchanged_for_strict_pairs(self):
        self.assertEqual(
            extract_primary_terms("Vergleiche ‚Frau‘ mit ‚Mann‘ und ‚Frau‘."),
            ["Frau", "Mann"],
        )
        self.assertEqual(extract_primary_terms("Wie oft geht's ums Geld?"), [])


# --------------------------------------------------------------------------- #
# 1) Erkennung des suchdefinierten Kontrasts                                   #
# --------------------------------------------------------------------------- #


class TestIsSearchDefinedContrast(unittest.TestCase):
    def test_dossier_case_is_detected(self):
        self.assertTrue(is_search_defined_contrast(_SEARCH_CONTRAST_FRAGE))

    def test_comparison_marker_variants(self):
        self.assertTrue(is_search_defined_contrast("‚Frau‘ vs ‚Mann‘"))
        self.assertTrue(is_search_defined_contrast("‚Frau‘ gegen ‚Mann‘"))
        self.assertTrue(
            is_search_defined_contrast(
                "Was ist typisch für ‚Frau‘ gegenüber ‚Mann‘?"
            )
        )
        self.assertTrue(
            is_search_defined_contrast(
                "Wie unterscheiden sich Belege mit ‚Frau‘ und mit ‚Mann‘?"
            )
        )
        self.assertTrue(
            is_search_defined_contrast(
                "Betrachte ‚Frau‘ und ‚Mann‘ als Teilmengen."
            )
        )

    def test_one_term_is_never_search_defined(self):
        self.assertFalse(
            is_search_defined_contrast(
                "Was ist typisch für ‚Frau‘ im Vergleich zum Rest?"
            )
        )

    def test_two_terms_without_comparison_are_not_detected(self):
        self.assertFalse(
            is_search_defined_contrast(
                "Zeige Belege für ‚Frau‘ und ‚Mann‘ im Korpus."
            )
        )

    def test_no_quotes_and_empty(self):
        self.assertFalse(
            is_search_defined_contrast("Vergleiche Frauen und Männer.")
        )
        self.assertFalse(is_search_defined_contrast(""))


# --------------------------------------------------------------------------- #
# 2) Vorbedingung: erfuellt ueber den Docset-per-Suche-Pfad                    #
# --------------------------------------------------------------------------- #


class TestPreconditionSearchDefined(unittest.TestCase):
    def test_two_term_comparison_lifts_short_circuit(self):
        status = recipe_precondition_status(
            "kontrast", _CARD_NO_AXIS, _SEARCH_CONTRAST_FRAGE
        )
        self.assertFalse(status["short_circuit"])
        note = status.get("briefing_note", "")
        self.assertIn("Suchdefinierter Kontrast", note)
        self.assertIn("'Frau' vs 'Mann'", note)
        self.assertIn("create_docset(query=Term, label=Term)", note)
        self.assertIn("keyness(target_docset_id=A, reference_docset_id=B)", note)
        self.assertIn("log_ratio", note)
        self.assertIn("Dokumentstreuung", note)

    def test_one_term_without_axis_keeps_honest_short_circuit(self):
        status = recipe_precondition_status(
            "kontrast",
            _CARD_NO_AXIS,
            "Was ist typisch für ‚Frau‘ im Vergleich zum Rest?",
        )
        self.assertTrue(status["short_circuit"])
        self.assertEqual(status["reason"], "meta_axis")
        answer = precondition_unmet_answer("kontrast", status["alternative"])
        self.assertIn("keine mehrwertige Metadaten-Achse", answer)

    def test_no_quotes_without_axis_keeps_short_circuit(self):
        status = recipe_precondition_status(
            "kontrast",
            _CARD_NO_AXIS,
            "Was ist typisch für dieses Korpus gegenüber einem anderen?",
        )
        self.assertTrue(status["short_circuit"])

    def test_axis_card_stays_on_axis_path_without_note(self):
        # 142M-artige Karte: Achsenweg wie heute, auch wenn Werte zitiert sind.
        status = recipe_precondition_status(
            "kontrast",
            _CARD_WITH_AXIS,
            "Welche Schlüsselwörter sind typisch für das Teilkorpus 'news' "
            "im Vergleich zum Teilkorpus 'chat'?",
        )
        self.assertFalse(status["short_circuit"])
        self.assertNotIn("briefing_note", status)

    def test_split_qa_wins_over_search_defined_reading(self):
        # Zitierte Partitionsnamen plus ausdrueckliche Aufteilungs-Nachfrage:
        # der V7-Detektor bleibt unveraendert und gewinnt (Split-QA-Rahmung,
        # keine Such-Docsets ueber Partitionsnamen).
        status = recipe_precondition_status(
            "kontrast",
            _CARD_NO_AXIS,
            "Vergleiche die Teilmengen ‚train‘ und ‚test‘ der Aufteilung.",
        )
        self.assertFalse(status["short_circuit"])
        self.assertIn("Split-QA", status.get("briefing_note", ""))
        self.assertNotIn("Suchdefinierter Kontrast", status.get("briefing_note", ""))

    def test_unknown_cardinality_stays_undecided(self):
        status = recipe_precondition_status(
            "kontrast", _CARD_NO_CARDINALITY, _SEARCH_CONTRAST_FRAGE
        )
        self.assertFalse(status["short_circuit"])
        self.assertNotIn("briefing_note", status)

    def test_note_wording_uses_first_two_terms_only(self):
        note = search_contrast_briefing_note(["Frau", "Mann", "Kind"])
        self.assertIn("'Frau' vs 'Mann'", note)
        self.assertNotIn("Kind", note)


# --------------------------------------------------------------------------- #
# 3) Vorplanung: zwei create_docset-Seiten, streng gegated                     #
# --------------------------------------------------------------------------- #


class TestSearchContrastPreplan(unittest.TestCase):
    def test_two_sides_are_planned_on_axisless_card(self):
        self.assertEqual(
            plan_recipe_first_round(
                "kontrast", _SEARCH_CONTRAST_FRAGE, _CARD_NO_AXIS
            ),
            [
                {
                    "tool": "create_docset",
                    "args": {"query": "Frau", "label": "Frau"},
                },
                {
                    "tool": "create_docset",
                    "args": {"query": "Mann", "label": "Mann"},
                },
            ],
        )

    def test_axis_card_keeps_model_planning(self):
        self.assertEqual(
            plan_recipe_first_round(
                "kontrast", _SEARCH_CONTRAST_FRAGE, _CARD_WITH_AXIS
            ),
            [],
        )

    def test_missing_or_undecided_card_keeps_model_planning(self):
        self.assertEqual(
            plan_recipe_first_round("kontrast", _SEARCH_CONTRAST_FRAGE, None),
            [],
        )
        self.assertEqual(
            plan_recipe_first_round(
                "kontrast", _SEARCH_CONTRAST_FRAGE, _CARD_NO_CARDINALITY
            ),
            [],
        )

    def test_one_term_keeps_model_planning(self):
        self.assertEqual(
            plan_recipe_first_round(
                "kontrast",
                "Was ist typisch für ‚Frau‘ im Vergleich zum Rest?",
                _CARD_NO_AXIS,
            ),
            [],
        )

    def test_split_qa_request_keeps_model_planning(self):
        self.assertEqual(
            plan_recipe_first_round(
                "kontrast",
                "Vergleiche die Teilmengen ‚train‘ und ‚test‘ der Aufteilung.",
                _CARD_NO_AXIS,
            ),
            [],
        )

    def test_gate_predicate_direct(self):
        self.assertTrue(
            _search_contrast_preplan_active(
                _SEARCH_CONTRAST_FRAGE, _CARD_NO_AXIS
            )
        )
        self.assertFalse(
            _search_contrast_preplan_active(
                _SEARCH_CONTRAST_FRAGE, _CARD_WITH_AXIS
            )
        )
        self.assertFalse(
            _search_contrast_preplan_active(_SEARCH_CONTRAST_FRAGE, None)
        )

    def test_dispatch_ready_calls_and_contract_filter(self):
        calls = preplanned_tool_calls(
            "kontrast",
            _SEARCH_CONTRAST_FRAGE,
            _CARD_NO_AXIS,
            available_tools=["create_docset", "keyness", "query_count"],
            allowed_tools=["create_docset", "keyness", "query_count"],
        )
        self.assertEqual([c["id"] for c in calls], ["preplan_1", "preplan_2"])
        self.assertEqual(
            [json.loads(c["function"]["arguments"]) for c in calls],
            [
                {"query": "Frau", "label": "Frau"},
                {"query": "Mann", "label": "Mann"},
            ],
        )

    def test_contract_without_create_docset_blocks_plan(self):
        self.assertEqual(
            preplanned_tool_calls(
                "kontrast",
                _SEARCH_CONTRAST_FRAGE,
                _CARD_NO_AXIS,
                available_tools=["create_docset", "keyness"],
                allowed_tools=["keyness"],
            ),
            [],
        )


# --------------------------------------------------------------------------- #
# 4) Effekt-Anker im Orchestrator (offline, Fake-LLM)                          #
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
    orch._ra_requires_grounding_contract = lambda: False


def _bench_ui_context() -> dict:
    # Bench-artiger Index: technische split-Partition, keine kontrastierbare
    # Achse (genau die Karte, auf der der Dossier-Fall abgewiesen wurde).
    return {
        "corpus_id": "bench",
        "corpus_tokens": 56191,
        "corpus_docs": 2000,
        "corpus_meta_fields": ["model", "register", "split", "doc_id"],
        "corpus_date_fields": [],
        "corpus_meta_field_cardinality": {
            "model": 1,
            "register": 1,
            "split": 2,
            "doc_id": 2000,
        },
    }


def _axis_ui_context() -> dict:
    # 142M-artige Karte: register ist eine echte kontrastierbare Achse.
    return {
        "corpus_id": "large",
        "corpus_tokens": 142_000_000,
        "corpus_docs": 100_000,
        "corpus_meta_fields": ["register"],
        "corpus_date_fields": [],
        "corpus_meta_field_cardinality": {"register": 6},
    }


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

    def plain_llm_calls(self) -> int:
        return sum(1 for e in self.events if e == ("llm", "plain"))


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

    docset_counter = {"n": 0}

    async def _dispatch(tool_call, _token=None):
        name = tool_call["function"]["name"]
        args = json.loads(tool_call["function"]["arguments"] or "{}")
        timeline.tool(name, args)
        if name == "create_docset":
            docset_counter["n"] += 1
            return {
                "status": "success",
                "docset_id": f"ds_{docset_counter['n']}",
                "doc_count": 10,
                "token_count": 500,
                "label": args.get("label", ""),
                "source": "query",
            }
        return tool_outputs.get(name, {"status": "success", "rows": []})

    return _call_llm, _dispatch


def _history_texts(orch: "ReActOrchestrator") -> list:
    texts = []
    for message in list(orch.session.history):
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            texts.append(content)
    return texts


class TestSearchContrastEffectAnchors(unittest.IsolatedAsyncioTestCase):
    async def test_dossier_case_runs_docsets_instead_of_rejection(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["create_docset", "keyness", "run_cqlf_query", "metadata_values"],
            call_llm,
            dispatch,
        )
        orch.ui_context = _bench_ui_context()
        _disable_contract_preflight(orch)
        result = await orch.run_async(_SEARCH_CONTRAST_FRAGE, stream=True, chunks=_antwort_chunks("Es liegen keine Daten vor."))

        self.assertEqual(orch._active_recipe_id, "kontrast")
        # KEIN deterministischer Kurzschluss mehr.
        self.assertNotIn("keine mehrwertige Metadaten-Achse", str(result or ""))
        # Runde 1 sind die beiden vorgeplanten create_docset-Seiten, VOR
        # jedem freien LLM-Planungscall.
        first_tools = timeline.tools_before_first_plain_llm()
        self.assertEqual(
            [event[1] for event in first_tools],
            ["create_docset", "create_docset"],
            timeline.events,
        )
        self.assertEqual(
            sorted(
                (event[2]["query"], event[2]["label"]) for event in first_tools
            ),
            [("Frau", "Frau"), ("Mann", "Mann")],
        )
        # Das Briefing broadcastet den Folgeweg als System note.
        notes = [
            t
            for t in _history_texts(orch)
            if "Suchdefinierter Kontrast" in t
        ]
        self.assertTrue(notes, _history_texts(orch))
        self.assertIn("keyness(target_docset_id=A, reference_docset_id=B)", notes[0])
        self.assertTrue(str(result or "").strip())

    async def test_no_term_question_keeps_honest_short_circuit(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["create_docset", "keyness", "metadata_values"],
            call_llm,
            dispatch,
        )
        orch.ui_context = _bench_ui_context()
        _disable_contract_preflight(orch)
        result = await orch.run_async(
            "Was ist typisch für dieses Korpus gegenüber einem anderen?"
        )

        self.assertEqual(orch._active_recipe_id, "kontrast")
        # Heutiges Verhalten: ehrlicher Kurzschluss ohne Werkzeug-Runden
        # und ohne freie LLM-Calls.
        self.assertIn("keine mehrwertige Metadaten-Achse", str(result or ""))
        self.assertEqual(
            [e for e in timeline.events if e[0] == "tool"], []
        )
        self.assertEqual(timeline.plain_llm_calls(), 0)

    async def test_axis_question_on_large_card_keeps_model_planning(self):
        timeline = _Timeline()
        call_llm, dispatch = _make_fakes(timeline, {})
        orch = _orchestrator(
            ["create_docset", "keyness", "metadata_values", "run_cqlf_query"],
            call_llm,
            dispatch,
        )
        orch.ui_context = _axis_ui_context()
        _disable_contract_preflight(orch)
        result = await orch.run_async(
            "Welche Schlüsselwörter sind typisch für das Teilkorpus 'news' "
            "im Vergleich zum Teilkorpus 'chat'?"
        )

        self.assertEqual(orch._active_recipe_id, "kontrast")
        # Achsenweg wie heute: keine Vorplanung, keine Such-Docsets aus den
        # zitierten Achsenwerten, keine Suchkontrast-Note.
        self.assertEqual(timeline.tools_before_first_plain_llm(), [])
        self.assertFalse(
            [
                t
                for t in _history_texts(orch)
                if "Suchdefinierter Kontrast" in t
            ]
        )
        self.assertTrue(str(result or "").strip())


if __name__ == "__main__":
    unittest.main()
