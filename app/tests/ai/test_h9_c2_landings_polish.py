"""H9 Paket C2: Landungen, Gates und Artefakt-Chokepoint (offline, Fake-LLM).

Pinnt die fuenf Befund-Fixes des zweiten Gutachter-Verdikts:

* V6: ``final_answer_polish`` — EIN finaler Politur-Durchlauf je Landung.
  Fixtures sind woertliche Artefakte aus den Gutachter-Rohlaeufen
  (/tmp/candyconc-muse-eval-20260812-product-h8-r2 und
  .../-h9-fresh-transfer, Feld ``antwort_text``).
* V7: ausdrueckliche Split-QA-Nachfrage loest den kontrast-Kurzschluss ein
  (technische Achse wird kontrastierbar, Briefing-Hinweis).
* V9: ``similar_words`` haengt am praeemptiven Capability-Gate
  (``word_similarity_unavailable_gate``, Kontrakt aus Paket B).
* V11: Timeout-/Skip-Landungen geben unverifizierte Modell-Prosa nicht
  unmarkiert aus; Meta-Hinweise wandern in Event-Annotationen, im Text
  steht genau EIN ehrlicher Satz.
* V5: exploration_meta schaltet frueher auf die Antwort-Synthese
  (``answer_switch_fraction`` 0.4, Default 0.55).
"""

import unittest

from tests.ai._real_copilot import ReActOrchestrator

from candyconc.candyconc_copilot.recipe_runtime import (
    ANSWER_SWITCH_FRACTION,
    FINAL_POLISH_HONESTY_LINE,
    answer_switch_fraction_for_recipe,
    final_answer_polish,
    is_explicit_split_qa_request,
    recipe_precondition_status,
    split_qa_briefing_note,
    tool_rounds_exhausted,
    verifier_skipped_answer_text,
    word_similarity_unavailable_gate,
)
from candyconc.candyconc_copilot.recipes import RECIPES_BY_ID


# Wortlaut der frischen Transfer-Frage (Dossier-Rohlauf
# candyconc-muse-eval-20260812-h9-fresh-transfer, fresh_split_qa).
FRESH_SPLIT_QA_FRAGE = (
    "Ist die Trainingspartition lexikalisch anders als die Testpartition? "
    "Prüfe ausdrücklich diese technische Aufteilung."
)

# Test corpus card with single-valued fields, document IDs and a
# technical split axis.
_CARD_SPLIT_ONLY = {
    "meta_fields": ["split", "register", "source", "doc_id"],
    "date_fields": [],
    "meta_axes": [
        {"field": "split", "count": 2, "kind": "technical"},
        {"field": "register", "count": 1, "kind": "single"},
        {"field": "source", "count": 1, "kind": "single"},
        {"field": "doc_id", "count": 2000, "kind": "doc_id"},
    ],
}


# --------------------------------------------------------------------------- #
# V6: final_answer_polish je Artefakt-Klasse                                   #
# --------------------------------------------------------------------------- #


class TestFinalAnswerPolishArtifacts(unittest.TestCase):
    def test_inline_label_double_from_assoziation_arbeit(self):
        # Woertlich aus product-h8-r2 / assoziation_arbeit.
        text = (
            "Deutung: Deutung: Bei nur 5 Knotentreffern ist die Rangliste "
            "nicht stabil; das auffälligste Muster ist die Kombination "
            "*Menschen … Arbeit* in Formulierungen wie „Menschen in Arbeit "
            "bringen“ / „Menschen bei Arbeit“."
        )
        out, annotations = final_answer_polish(text)
        self.assertNotIn("Deutung: Deutung:", out)
        self.assertIn("Deutung: Bei nur 5 Knotentreffern", out)
        self.assertEqual(annotations, [])

    def test_newline_label_double_from_fresh_profil_machen(self):
        # Woertlich aus h9-fresh-transfer / fresh_profil_machen: die
        # Landung lief NICHT durch den Skip-Pfad, darum stand die Doppelung
        # im sichtbaren Text. Der Chokepoint faltet sie jetzt ueberall.
        text = (
            "Deutung\n"
            "Deutung: Die sichtbaren Partner sind sehr allgemein – "
            "Pronomen-Subjekt *wir* und die Akkusativpronomen *es/sich/das* "
            "sowie die Negation *nicht*."
        )
        out, _ = final_answer_polish(text)
        self.assertEqual(out.count("Deutung"), 1)
        self.assertIn("Deutung\nDie sichtbaren Partner", out)

    def test_drop_stat_and_skip_note_move_to_annotations(self):
        # Woertlich aus h9-fresh-transfer / fresh_open_hypothesen (Schluss).
        text = (
            "Grenzen: Es liegen keine Datumsfelder und keine "
            "kontrastierbaren Metadatenachsen vor.\n\n"
            "2 Aussage(n) entfernt: Referenz auf Evidenz nicht auflösbar.\n\n"
            "Hinweis: LLM-Verifikation übersprungen (Zeitbudget). Zahlen "
            "und Zitate sind deterministisch gegen die sichtbare "
            "Tool-Evidenz aufgelöst."
        )
        out, annotations = final_answer_polish(text)
        self.assertNotIn("Aussage(n) entfernt", out)
        self.assertNotIn("LLM-Verifikation übersprungen", out)
        self.assertIn(FINAL_POLISH_HONESTY_LINE, out)
        notes = [a["note"] for a in annotations]
        self.assertTrue(any("2 Aussage(n) entfernt" in n for n in notes))
        self.assertTrue(
            any("LLM-Verifikation übersprungen (Zeitbudget)" in n for n in notes)
        )
        self.assertTrue(
            all(a["claim_id"] == "final_polish" for a in annotations)
        )

    def test_naked_query_line_becomes_provenance(self):
        # Query woertlich aus product-h8-r2 / assoziation_arbeit
        # (Gegenprobe), hier als nackte sichtbare Zeile.
        text = (
            "Gegenprobe zur Kollokation:\n"
            '[lemma="Mensch"] []{0,5} [lemma="Arbeit"]\n'
            "Ergebnis: total 2 Treffer."
        )
        out, _ = final_answer_polish(text)
        self.assertIn(
            'Query: `[lemma="Mensch"] []{0,5} [lemma="Arbeit"]`', out
        )
        self.assertNotIn('\n[lemma="Mensch"]', out)

    def test_prose_line_with_brackets_stays(self):
        text = "Der Befund [siehe oben] bleibt bestehen."
        out, _ = final_answer_polish(text)
        self.assertEqual(out, text)

    def test_leftover_ev_marker_drops_sentence(self):
        text = (
            "Kernbefund: Das Lemma ist selten.\n"
            "- Knotenfrequenz: {{ev:E_frequency_list_1.rows[0].f}} Treffer.\n"
            "- Fenster 5 Token, within_sentence=true."
        )
        out, annotations = final_answer_polish(text)
        self.assertNotIn("{{ev:", out)
        self.assertNotIn("Knotenfrequenz", out)
        self.assertIn("Fenster 5 Token", out)
        self.assertTrue(
            any("Aussage(n) entfernt" in a["note"] for a in annotations)
        )

    def test_internal_id_tokens_are_scrubbed(self):
        text = (
            "Das Kollokat *Mensch* (E_collocate_stats_2) erreicht logDice "
            "7,37 laut ev3 und bleibt der stärkste Partner."
        )
        out, _ = final_answer_polish(text)
        self.assertNotIn("E_collocate_stats_2", out)
        self.assertNotIn("ev3", out)
        self.assertIn("logDice 7,37", out)
        self.assertIn("stärkste Partner", out)

    def test_truncation_never_ends_inside_quote_span(self):
        # KWIC-Zitat woertlich aus product-h8-r2 / assoziation_arbeit,
        # hier mitten in der „...“-Spanne abgeschnitten (Stream-Abbruch).
        text = (
            "Match im Kontext „Menschen in Arbeit bringen \"??? Sie u."
        )
        out, _ = final_answer_polish(text)
        self.assertNotIn("„Menschen in Arbeit bringen", out)
        self.assertIn("Match im Kontext", out)

    def test_dangling_backtick_span_is_cut_before_span(self):
        text = "Provenienz: `[word=\"Islam\"] und dann bricht es ab"
        out, _ = final_answer_polish(text)
        self.assertNotIn("`", out)
        self.assertIn("Provenienz:", out)

    def test_clean_text_is_untouched_without_annotations(self):
        text = (
            "Kernbefund: *Liebe* hat 12 Treffer (213,6 pmw).\n\n"
            "Deutung: Der Befund ist als Hinweis zu lesen.\n\n"
            "Grenzen: Nur die exakte Wortform wurde gezählt."
        )
        out, annotations = final_answer_polish(text)
        self.assertEqual(out, text.rstrip())
        self.assertEqual(annotations, [])

    def test_empty_text_stays_empty(self):
        out, annotations = final_answer_polish("")
        self.assertEqual(out, "")
        self.assertEqual(annotations, [])


# --------------------------------------------------------------------------- #
# V11: Skip-/Salvage-Texte — Politur auf dem Skip-Pfad-Ergebnis                #
# --------------------------------------------------------------------------- #


class TestVerifierSkipPolish(unittest.TestCase):
    def test_skip_text_polished_to_single_honest_sentence(self):
        raw = verifier_skipped_answer_text(
            "Kernbefund: 5 Treffer für *Arbeit* {{ev:E_x_1}}.",
            lambda draft: {
                "text": "Kernbefund: 5 Treffer für *Arbeit*.",
                "bare_numbers": [],
            },
            lambda: "",
            lambda reason: reason,
        )
        self.assertIn("LLM-Verifikation übersprungen (Zeitbudget)", raw)
        out, annotations = final_answer_polish(raw)
        self.assertNotIn("LLM-Verifikation übersprungen", out)
        self.assertIn(FINAL_POLISH_HONESTY_LINE, out)
        self.assertIn("Kernbefund: 5 Treffer", out)
        self.assertTrue(
            any(
                "LLM-Verifikation übersprungen (Zeitbudget)" in a["note"]
                for a in annotations
            )
        )

    def test_salvage_hard_fabrication_rules_run_on_partial_text(self):
        # V11a: der Server-Salvage-Pfad strikt jetzt unbelegte Zahlen
        # (claim_rules-HARD-Klasse a) statt Modell-Prosa verbatim zu landen.
        from candyconc.services.backend import server as _server

        class _Orch:
            _turn_evidence_items = [
                {
                    "id": "E_frequency_list_1",
                    "tool": "frequency_list",
                    "compact": "Liebe: f=12",
                }
            ]

        partial = (
            "Die Liste zeigt 999 Treffer für *Liebe* im Gesamtkorpus. "
            "Das Register ist social."
        )
        out = _server._salvage_resolve_partial_text(partial, _Orch())
        self.assertNotIn("999", out)

    def test_salvage_without_evidence_keeps_conversational_numbers(self):
        from candyconc.services.backend import server as _server

        class _Orch:
            _turn_evidence_items = []

        partial = "Gerne, ich kann bis zu 3 Analysen parallel planen."
        out = _server._salvage_resolve_partial_text(partial, _Orch())
        self.assertIn("3", out)

    def test_terminal_events_carry_polish_annotations(self):
        from candyconc.services.backend.routes.copilot import (
            _copilot_terminal_events,
        )

        events = _copilot_terminal_events(
            session_id="s1",
            reply=None,
            salvage_text="Bericht.",
            timed_out=True,
            error_text=None,
            usage_report={},
            extra_annotations=[
                {
                    "claim_id": "final_polish",
                    "note": "2 Aussage(n) entfernt: Referenz auf Evidenz "
                    "nicht auflösbar.",
                }
            ],
        )
        grounding = [p for n, p in events if n == "copilot.grounding"]
        self.assertEqual(len(grounding), 1)
        annotations = grounding[0]["grounding"]["annotations"]
        self.assertEqual(
            grounding[0]["grounding"]["verdict"],
            "completed_on_collected_evidence",
        )
        notes = [a["note"] for a in annotations]
        self.assertTrue(any("Zeitbudget erreicht" in n for n in notes))
        self.assertTrue(any("Aussage(n) entfernt" in n for n in notes))


# --------------------------------------------------------------------------- #
# V7: Split-QA-Einloesung                                                      #
# --------------------------------------------------------------------------- #


class TestSplitQaRedemption(unittest.TestCase):
    def test_fresh_split_qa_is_explicit_request(self):
        self.assertTrue(is_explicit_split_qa_request(FRESH_SPLIT_QA_FRAGE))

    def test_generic_contrast_questions_are_not_explicit(self):
        # Woertliche Gegenbeispiele aus der frischen Transfer-Suite.
        self.assertFalse(
            is_explicit_split_qa_request(
                "Vergleiche, wie Frauen und Männer sprachlich dargestellt "
                "werden, ohne eine Geschlechts-Achse zu unterstellen."
            )
        )
        self.assertFalse(
            is_explicit_split_qa_request("Was ist typisch für A gegenüber B?")
        )
        self.assertFalse(is_explicit_split_qa_request(""))

    def test_explicit_split_request_runs_contrast_over_technical_axis(self):
        status = recipe_precondition_status(
            "kontrast", _CARD_SPLIT_ONLY, FRESH_SPLIT_QA_FRAGE
        )
        self.assertFalse(status["short_circuit"])
        self.assertIn("Split-QA", status.get("briefing_note", ""))
        self.assertIn("split", status.get("briefing_note", ""))
        self.assertIn("Datenaufteilungs-QA", status.get("briefing_note", ""))

    def test_implicit_contrast_still_short_circuits(self):
        # Regression: ohne ausdrueckliche Partitions-Nachfrage bleibt der
        # ehrliche Kurzschluss (anerkannter Fortschritt, darf nicht kippen).
        status = recipe_precondition_status(
            "kontrast",
            _CARD_SPLIT_ONLY,
            "Was ist typisch für dieses Korpus gegenüber einem anderen?",
        )
        self.assertTrue(status["short_circuit"])
        self.assertIn("Split-QA", status["alternative"])

    def test_contrastable_axis_never_produces_briefing_note(self):
        card = {
            "meta_fields": ["variant"],
            "date_fields": [],
            "meta_axes": [{"field": "variant", "count": 2, "kind": "axis"}],
        }
        status = recipe_precondition_status(
            "kontrast", card, FRESH_SPLIT_QA_FRAGE
        )
        self.assertFalse(status["short_circuit"])
        self.assertNotIn("briefing_note", status)

    def test_briefing_note_wording(self):
        note = split_qa_briefing_note(["split"])
        self.assertEqual(
            note,
            "Split-QA: Achse split ist technisch, Befunde als "
            "Datenaufteilungs-QA rahmen, nicht als Sprachbefund.",
        )


# --------------------------------------------------------------------------- #
# V9: similar_words im praeemptiven Capability-Gate                            #
# --------------------------------------------------------------------------- #


class TestWordSimilarityGate(unittest.TestCase):
    def _tool_wrappers_stub(self):
        import candyconc.candyconc_copilot.tool_wrappers as tw

        return tw

    def test_gate_blocks_similar_words_when_artifacts_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tw = self._tool_wrappers_stub()
            original = getattr(tw, "word_similarity_available", None)
            tw.word_similarity_available = (
                lambda index_path: False  # Artefakte fehlen
            )
            try:
                gate = word_similarity_unavailable_gate(
                    ["similar_words", "frequency_list"], index_path=tmp
                )
            finally:
                if original is None:
                    del tw.word_similarity_available
                else:
                    tw.word_similarity_available = original
        self.assertIn("similar_words", gate)
        self.assertIn("word_similarity", gate["similar_words"])

    def test_gate_open_when_artifacts_present(self):
        tw = self._tool_wrappers_stub()
        original = getattr(tw, "word_similarity_available", None)
        tw.word_similarity_available = lambda index_path: True
        try:
            gate = word_similarity_unavailable_gate(
                ["similar_words"], index_path="/irgendwo"
            )
        finally:
            if original is None:
                del tw.word_similarity_available
            else:
                tw.word_similarity_available = original
        self.assertEqual(gate, {})

    def test_gate_fails_open_without_paket_b_export(self):
        tw = self._tool_wrappers_stub()
        original = getattr(tw, "word_similarity_available", None)
        if original is not None:
            del tw.word_similarity_available
        try:
            gate = word_similarity_unavailable_gate(
                ["similar_words"], index_path="/irgendwo"
            )
        finally:
            if original is not None:
                tw.word_similarity_available = original
        self.assertEqual(gate, {})

    def test_gate_noop_when_tool_not_exposed(self):
        self.assertEqual(
            word_similarity_unavailable_gate(
                ["frequency_list"], index_path="/irgendwo"
            ),
            {},
        )


# --------------------------------------------------------------------------- #
# V5: frueherer Antwort-Schalter der Exploration                               #
# --------------------------------------------------------------------------- #


class TestExplorationAnswerSwitch(unittest.TestCase):
    def test_fraction_values(self):
        self.assertEqual(ANSWER_SWITCH_FRACTION, 0.55)
        self.assertEqual(
            answer_switch_fraction_for_recipe("exploration_meta"), 0.4
        )
        self.assertEqual(
            answer_switch_fraction_for_recipe("frequenz"),
            ANSWER_SWITCH_FRACTION,
        )
        self.assertEqual(
            answer_switch_fraction_for_recipe(""), ANSWER_SWITCH_FRACTION
        )
        self.assertEqual(
            RECIPES_BY_ID["exploration_meta"].answer_switch_fraction, 0.4
        )

    def test_exploration_switches_before_default(self):
        # 45% des Budgets verbraucht, 1 Runde gelaufen: exploration_meta
        # schaltet auf die Antwort, das Default-Rezept noch nicht.
        self.assertTrue(
            tool_rounds_exhausted(
                1, "exploration_meta", started_at=0.0, max_time=100.0, now=45.0
            )
        )
        self.assertFalse(
            tool_rounds_exhausted(
                1, "kontrast", started_at=0.0, max_time=100.0, now=45.0
            )
        )
        # Unter 40% laeuft auch die Exploration weiter.
        self.assertFalse(
            tool_rounds_exhausted(
                1, "exploration_meta", started_at=0.0, max_time=100.0, now=30.0
            )
        )
        # Floor bleibt: vor Runde 1 schaltet nie der Zeit-Schalter.
        self.assertFalse(
            tool_rounds_exhausted(
                0, "exploration_meta", started_at=0.0, max_time=100.0, now=90.0
            )
        )


# --------------------------------------------------------------------------- #
# V6 Integration: der Chokepoint laeuft im Orchestrator genau einmal           #
# --------------------------------------------------------------------------- #


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }


class TestOrchestratorChokepoint(unittest.IsolatedAsyncioTestCase):
    async def test_finish_turn_polishes_and_annotates(self):
        async def _call_llm(messages, exposed_tools, **kwargs):
            raise AssertionError("kein LLM-Call erwartet")

        async def _dispatch(tool_call, _token=None):
            raise AssertionError("kein Tool-Call erwartet")

        orch = ReActOrchestrator([_tool("frequency_list")], _call_llm, _dispatch)
        events: list = []
        orch._emit_output = lambda bus, event: events.append(event)

        text = (
            "Deutung: Deutung: Bei nur 5 Knotentreffern ist die Rangliste "
            "nicht stabil.\n\n"
            "2 Aussage(n) entfernt: Referenz auf Evidenz nicht auflösbar.\n\n"
            "Hinweis: LLM-Verifikation übersprungen (Zeitbudget). Zahlen "
            "und Zitate sind deterministisch gegen die sichtbare "
            "Tool-Evidenz aufgelöst."
        )
        polished = orch._ra_finish_turn(
            object(), "Frage?", text, stream_emit=True
        )
        self.assertNotIn("Deutung: Deutung:", polished)
        self.assertNotIn("Aussage(n) entfernt", polished)
        self.assertNotIn("LLM-Verifikation übersprungen", polished)
        self.assertIn(FINAL_POLISH_HONESTY_LINE, polished)
        # Session-Historie traegt denselben polierten Text.
        history = orch.session.get_history()
        assistant = [m for m in history if m.get("role") == "assistant"]
        self.assertTrue(assistant)
        self.assertEqual(assistant[-1]["content"], polished)
        # Politur-Annotationen im copilot.grounding-Event (final_polish).
        polish_events = [
            e
            for e in events
            if e.get("event") == "copilot.grounding"
            and e.get("grounding", {}).get("verdict") == "final_polish"
        ]
        self.assertEqual(len(polish_events), 1)
        notes = [
            a["note"]
            for a in polish_events[0]["grounding"]["annotations"]
        ]
        self.assertTrue(any("Aussage(n) entfernt" in n for n in notes))
        # Der gestreamte Delta-Text ist ebenfalls der polierte Text.
        deltas = [
            e["delta"]["content"]
            for e in events
            if isinstance(e.get("delta"), dict)
        ]
        self.assertEqual(deltas, [polished])

    async def test_finish_turn_clean_text_emits_no_polish_event(self):
        async def _call_llm(messages, exposed_tools, **kwargs):
            raise AssertionError("kein LLM-Call erwartet")

        async def _dispatch(tool_call, _token=None):
            raise AssertionError("kein Tool-Call erwartet")

        orch = ReActOrchestrator([_tool("frequency_list")], _call_llm, _dispatch)
        events: list = []
        orch._emit_output = lambda bus, event: events.append(event)
        text = "Kernbefund: 12 Treffer (213,6 pmw)."
        polished = orch._ra_finish_turn(
            object(), "Frage?", text, stream_emit=False
        )
        self.assertEqual(polished, text)
        self.assertEqual(
            [e for e in events if e.get("event") == "copilot.grounding"], []
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestToolTraceDropH92:
    def test_raw_tool_trace_lines_fall_from_visible_text(self) -> None:
        # H9.2: Engine-Ausfall-Salvage kippte rohe Tool-Traces in den Text
        # (final_transfer2/fresh_kwic_gut). Das Muster faellt am Chokepoint.
        from candyconc.candyconc_copilot.recipe_runtime import (
            final_answer_polish,
        )

        text = (
            "Analysebericht\n\n"
            '- document_search({"snippet": 40, "term": "gut"}) -> '
            '{"rows": [], "status": "success"}\n'
            '- run_cqlf_query({"query": "gut"}) -> {"total": 52}\n\n'
            "Befund: gut ist 52-mal belegt."
        )
        polished, _ = final_answer_polish(text)
        assert "document_search({" not in polished
        assert "-> {" not in polished
        assert "Befund: gut ist 52-mal belegt." in polished

    def test_legitimate_prose_with_arrows_survives(self) -> None:
        from candyconc.candyconc_copilot.recipe_runtime import (
            final_answer_polish,
        )

        text = "Die Kette metadata_values -> create_docset ist der Standardweg."
        polished, _ = final_answer_polish(text)
        assert "Standardweg" in polished
