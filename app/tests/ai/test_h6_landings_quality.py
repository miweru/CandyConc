"""H6 (Qualitaetsrunde), Paket P1: Landungen & Budget-Schalter.

Offline, ohne LLM/Index. Gepinnt werden:

1. B8-S1: ``tool_rounds_exhausted`` als pure Runden-/Zeit-Leitplanke
   (ANSWER_SWITCH_FRACTION=0.55, Floor: mindestens 1 Runde gelaufen,
   ``max_time=None`` zaehlt nur Runden).
2. B8-S2: ``TOOL_ROUND_WRAPUP_LINE`` traegt die Pflichtstruktur
   (Kernbefund/Belege/Deutung/Grenzen, jede Zahl genau einmal).
3. B8-S4: Confirmation-Pressure-Obergrenze min(8, ...), Basis 6.
4. B5(2): ``drop_unresolved_sentences`` (Satz-Drop + genau eine
   Sammel-Annotation, 50%-Wachposten) und die Integration in
   ``verifier_skipped_answer_text``.
5. B2(3): ``trim_incomplete_tail_sentence`` und die Server-Backstop-
   Politur ``_salvage_resolve_partial_text`` (Marker aufgeloest, kein
   Leak roher ``{{ev:...}}``-IDs, angebrochener Schlusssatz gekappt).
6. B7(1): technische Partitionsfelder (split/fold/...) sind
   ``kind='technical'`` und nie kontrastierbar; echte Achsen
   (model/register/...) werden NIE geblockt.
7. B1: der fail-closed-Text behaelt Zeile 1 byte-identisch und traegt
   die neue Limitationszeile statt der AnalysisContract-Floskel.
"""

import unittest
from pathlib import Path

from candyconc.candyconc_copilot.grounding_refs import (
    MISSING_EVIDENCE_PLACEHOLDER,
)
from candyconc.candyconc_copilot.recipe_runtime import (
    ANSWER_SWITCH_FRACTION,
    TOOL_ROUND_WRAPUP_LINE,
    _classify_meta_axes,
    corpus_card_from_context,
    drop_unresolved_sentences,
    max_tool_rounds_for_recipe,
    precondition_unmet_answer,
    recipe_precondition_status,
    resolve_reference_draft,
    tool_rounds_exhausted,
    trim_incomplete_tail_sentence,
    verifier_skipped_answer_text,
)

_ROOT = Path(__file__).resolve().parents[2]
_ORCH_SRC = (
    _ROOT / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
).read_text(encoding="utf-8-sig")

CAPITULATION_LINE = (
    "Ich kann diese Analyse gerade nicht sicher tool-gestützt beantworten."
)
NEW_LIMITATION_LINE = (
    "- Es liegt keine belegbare Tool-Evidenz für eine Analyse vor."
)


# --------------------------------------------------------------------------- #
# B8-S1: Runden-/Zeit-Leitplanke                                               #
# --------------------------------------------------------------------------- #
class TestToolRoundsExhausted(unittest.TestCase):
    def test_answer_switch_fraction_is_pinned(self):
        self.assertEqual(ANSWER_SWITCH_FRACTION, 0.55)

    def test_round_limit_still_counts(self):
        limit = max_tool_rounds_for_recipe("frequenz")
        self.assertTrue(tool_rounds_exhausted(limit, "frequenz"))
        self.assertFalse(tool_rounds_exhausted(limit - 1, "frequenz"))

    def test_time_switch_fires_after_fraction(self):
        # 100s Budget: Schalter bei >55s, mit injizierter Uhr.
        self.assertTrue(
            tool_rounds_exhausted(
                1, "kontrast", started_at=1000.0, max_time=100.0,
                now=1000.0 + 56.0,
            )
        )
        self.assertFalse(
            tool_rounds_exhausted(
                1, "kontrast", started_at=1000.0, max_time=100.0,
                now=1000.0 + 54.0,
            )
        )

    def test_time_switch_never_fires_before_round_one(self):
        # Floor: mindestens 1 Runde gelaufen — die laufende Rezept-Sequenz
        # wird nie vor Runde 1 gekappt, egal wie knapp die Zeit ist.
        self.assertFalse(
            tool_rounds_exhausted(
                0, "kontrast", started_at=1000.0, max_time=100.0,
                now=1000.0 + 99.0,
            )
        )

    def test_no_max_time_counts_only_rounds(self):
        # Timeout-freier Modus (max_time=None): nur die Rundenzahl zaehlt.
        self.assertFalse(
            tool_rounds_exhausted(
                1, "kontrast", started_at=0.0, max_time=None,
                now=10_000_000.0,
            )
        )

    def test_kontrast_behaelt_seine_runden_bei_grosszuegiger_zeit(self):
        # Wechselwirkung H5 Fix 3: kontrast braucht mindestens 4 Runden fuer
        # den blossen Aufbau. Bei normalem Tempo kappt der Zeit-Schalter die
        # Sequenz nicht.
        #
        # Die Zahl kommt aus der Funktion, nicht aus dieser Probe. Was hier
        # geprueft wird, ist die WECHSELWIRKUNG von Runden und Zeit, nicht
        # der Wert. Die Werte pinnt test_max_tool_runden_pinned_per_recipe.
        limit = max_tool_rounds_for_recipe("kontrast")
        self.assertGreaterEqual(limit, 4)
        for rounds in range(1, limit):
            self.assertFalse(
                tool_rounds_exhausted(
                    rounds, "kontrast", started_at=1000.0, max_time=120.0,
                    now=1000.0 + 40.0,
                ),
                f"Runde {rounds} darf bei 40s/120s nicht kappen",
            )


# --------------------------------------------------------------------------- #
# B8-S2: Wrap-up-Pflichtstruktur                                               #
# --------------------------------------------------------------------------- #
class TestWrapupLine(unittest.TestCase):
    def test_wrapup_line_carries_mandatory_structure(self):
        for token in (
            "Kernbefund",
            "Belege",
            "Deutung",
            "Grenzen",
            "genau einmal",
            "{{ev:",
        ):
            self.assertIn(token, TOOL_ROUND_WRAPUP_LINE)


# --------------------------------------------------------------------------- #
# B8-S4: Confirmation-Pressure-Deckel                                          #
# --------------------------------------------------------------------------- #
class TestConfirmationPressureCap(unittest.TestCase):
    """Deckel 8, Basis 6. Unveraendert, nur nicht mehr im Orchestrator.

    P3.3 hat die Rechnung nach budgets.retry_budget_fuer_restzeit
    verschoben, weil der Orchestrator auf seinem LOC-Budget steht. Die
    Zusicherung wird deshalb am VERHALTEN geprueft statt am Quelltext des
    Orchestrators, das ist ohnehin die staerkere Form.
    """

    def test_cap_is_eight_base_stays_six(self):
        from candyconc.candyconc_copilot import budgets

        def budget(guarded, kandidaten):
            # now=0 heisst: nichts verbraucht, die Zeitschranke bindet nicht.
            return budgets.retry_budget_fuer_restzeit(
                started_at=0.0, max_time=None,
                confirmation_guarded=guarded,
                retrieval_candidate_count=kandidaten,
            )

        self.assertEqual(budget(False, 0), 6, "Basis bleibt 6")
        self.assertEqual(budget(True, 0), 6, "kein Kandidat, kein Aufschlag")
        self.assertEqual(budget(True, 4), 6)
        self.assertEqual(budget(True, 6), 8, "Deckel greift bei 8")
        self.assertEqual(budget(True, 99), 8, "und nie darueber")


# --------------------------------------------------------------------------- #
# B5(2): Satz-Drop-Policy                                                      #
# --------------------------------------------------------------------------- #
class TestDropUnresolvedSentences(unittest.TestCase):
    def test_text_without_placeholder_is_unchanged(self):
        text = "Alles belegt. Nichts fehlt."
        self.assertEqual(drop_unresolved_sentences(text), text)

    def test_drops_placeholder_sentence_with_single_annotation(self):
        text = (
            "Die Suche liefert 40 Treffer. Der Nebenwert ist "
            f"{MISSING_EVIDENCE_PLACEHOLDER} geblieben. "
            "Das Muster ist konsistent. Die Provenienz ist der Suchlauf."
        )
        out = drop_unresolved_sentences(text)
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, out)
        self.assertIn("Die Suche liefert 40 Treffer.", out)
        self.assertIn("Das Muster ist konsistent.", out)
        self.assertIn(
            "1 Aussage(n) entfernt: Referenz auf Evidenz nicht auflösbar.",
            out,
        )
        self.assertEqual(out.count("Aussage(n) entfernt"), 1)

    def test_drops_whole_list_line(self):
        text = (
            "Befunde:\n"
            "- total=40 aus dem Suchlauf.\n"
            f"- Nebenwert {MISSING_EVIDENCE_PLACEHOLDER} ohne Beleg.\n"
            "- Provenienz: frequency_list.\n"
        )
        out = drop_unresolved_sentences(text)
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, out)
        self.assertIn("- total=40 aus dem Suchlauf.", out)
        self.assertIn("- Provenienz: frequency_list.", out)
        self.assertIn("1 Aussage(n) entfernt", out)

    def test_guard_keeps_original_when_majority_would_fall(self):
        text = f"Einziger Satz mit {MISSING_EVIDENCE_PLACEHOLDER} darin."
        out = drop_unresolved_sentences(text)
        self.assertEqual(out, text)
        self.assertNotIn("Aussage(n) entfernt", out)


# --------------------------------------------------------------------------- #
# B2(3): Schlusssatz-Kappung                                                   #
# --------------------------------------------------------------------------- #
class TestTrimIncompleteTailSentence(unittest.TestCase):
    def test_cuts_broken_tail_at_last_sentence_end(self):
        self.assertEqual(
            trim_incomplete_tail_sentence(
                "Satz eins steht. Satz zwei bricht mitten im"
            ),
            "Satz eins steht.",
        )

    def test_complete_text_is_unchanged(self):
        self.assertEqual(
            trim_incomplete_tail_sentence("Alles gut. Wirklich alles."),
            "Alles gut. Wirklich alles.",
        )

    def test_text_without_sentence_end_is_kept(self):
        # Kein Satzende -> Text bleibt (angebrochen ist ehrlicher als leer).
        self.assertEqual(
            trim_incomplete_tail_sentence("nur ein fragment ohne ende"),
            "nur ein fragment ohne ende",
        )

    def test_empty_text_stays_empty(self):
        self.assertEqual(trim_incomplete_tail_sentence(""), "")


# --------------------------------------------------------------------------- #
# B5(2) Integration: verifier_skipped_answer_text droppt Platzhalter-Saetze    #
# --------------------------------------------------------------------------- #
_EV_ITEMS = [
    {
        "id": "ev1",
        "tool": "frequency_list",
        "raw_surface": {"total": 40},
        "grounding_surface": ["total=40"],
    }
]


class TestVerifierSkippedDropsPlaceholders(unittest.TestCase):
    def test_unresolved_sentence_falls_with_annotation(self):
        draft = (
            "Es gibt {{ev:ev1.total}} Treffer im sichtbaren Suchlauf. "
            "Der Nebenwert {{ev:ev1.gibtsnicht}} bleibt hier offen stehen. "
            "Die Provenienz ist der Suchlauf selbst. "
            "Das Muster wirkt dabei konsistent."
        )
        out = verifier_skipped_answer_text(
            draft,
            lambda text: resolve_reference_draft(text, list(_EV_ITEMS), ""),
            lambda: "",
            lambda reason: f"fail-closed: {reason}",
        )
        self.assertIn("40", out)
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, out)
        self.assertNotIn("{{ev:", out)
        self.assertIn("1 Aussage(n) entfernt", out)
        self.assertIn("LLM-Verifikation übersprungen", out)


# --------------------------------------------------------------------------- #
# B2(3): Server-Backstop-Politur                                               #
# --------------------------------------------------------------------------- #
class TestServerSalvagePolish(unittest.TestCase):
    def _salvage(self, partial_text, orch, **kwargs):
        from candyconc.services.backend import server as _server

        return _server._copilot_timeout_salvage_text(
            partial_text, None, orch, **kwargs
        )

    def test_partial_text_markers_resolved_and_tail_trimmed(self):
        class _Orch:
            _turn_evidence_items = list(_EV_ITEMS)

        partial = (
            "Die Suche liefert {{ev:ev1.total}} Treffer im Korpus. "
            "Unbelegt bleibt {{ev:ev9.x}} hier als Angabe. "
            "Dieser Schlusssatz bricht mitten im"
        )
        out = self._salvage(partial, _Orch(), timed_out=True, annotate=False)
        self.assertIsNotNone(out)
        self.assertNotIn("{{", out)
        self.assertNotIn("ev9", out)
        self.assertIn("40", out)
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, out)
        self.assertNotIn("bricht mitten im", out)
        # H9.2: Die Drop-Statistik ist ein V6-Artefakt und wandert am
        # finalen Politur-Chokepoint aus dem sichtbaren Text in die
        # copilot.grounding-Annotationen — sichtbar bleibt nur der Inhalt.
        self.assertNotIn("Aussage(n) entfernt", out)

    def test_clean_partial_text_passes_through(self):
        out = self._salvage(
            "Teilbefund.", object(), timed_out=False, annotate=False
        )
        self.assertEqual(out, "Teilbefund.")

    def test_no_work_still_returns_none(self):
        class _EmptyOrch:
            def build_salvage_markdown(self):
                return None

        self.assertIsNone(
            self._salvage("", _EmptyOrch(), timed_out=True, annotate=False)
        )


# --------------------------------------------------------------------------- #
# B7(1): technische Achsen-Klassifikation                                      #
# --------------------------------------------------------------------------- #
class TestTechnicalAxisClassification(unittest.TestCase):
    @staticmethod
    def _kinds(fields, cardinality, docs=100):
        return {
            a["field"]: a["kind"]
            for a in _classify_meta_axes(fields, cardinality, docs)
        }

    def test_split_is_technical_never_axis(self):
        kinds = self._kinds(
            ["split", "register", "model"],
            {"split": 2, "register": 3, "model": 2},
        )
        self.assertEqual(kinds["split"], "technical")
        self.assertEqual(kinds["register"], "axis")
        self.assertEqual(kinds["model"], "axis")

    def test_blocklist_covers_partition_names_casefold(self):
        fields = ["Split", "fold", "SHARD", "partition", "batch", "seed"]
        kinds = self._kinds(fields, {f: 2 for f in fields})
        for field in fields:
            self.assertEqual(kinds[field], "technical", field)

    def test_linguistic_axes_are_never_blocked(self):
        fields = ["model", "register", "source", "variant", "text_type"]
        kinds = self._kinds(fields, {f: 2 for f in fields})
        for field in fields:
            self.assertEqual(kinds[field], "axis", field)

    def test_kontrast_short_circuit_names_technical_partition(self):
        ctx = {
            "corpus_docs": 2000,
            "corpus_meta_fields": ["split", "register"],
            "corpus_date_fields": [],
            "corpus_meta_field_cardinality": {"split": 2, "register": 1},
        }
        card = corpus_card_from_context(ctx)
        status = recipe_precondition_status("kontrast", card)
        self.assertTrue(status["short_circuit"])
        answer = precondition_unmet_answer(
            "kontrast", status["alternative"]
        )
        self.assertIn("technische Partition", answer)
        self.assertIn("split", answer)
        self.assertIn("Split-QA", answer)


# --------------------------------------------------------------------------- #
# B1: fail-closed-Text (Zeile 1 byte-identisch, neue Limitationszeile)         #
# --------------------------------------------------------------------------- #
class TestFailClosedText(unittest.TestCase):
    def test_capitulation_first_line_and_new_limitation(self):
        from tests.ai._real_copilot import ReActOrchestrator

        md = ReActOrchestrator._ra_build_fail_closed_grounding_markdown(
            "Grund X"
        )
        lines = md.split("\n")
        self.assertEqual(lines[0], CAPITULATION_LINE)
        self.assertIn("- Grund X", md)
        self.assertIn(NEW_LIMITATION_LINE, md)
        self.assertNotIn("AnalysisContract", md)


if __name__ == "__main__":
    unittest.main()
