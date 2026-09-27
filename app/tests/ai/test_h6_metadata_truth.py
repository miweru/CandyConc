"""H6-Paket P3: Metadaten-Wahrheit + die eine neue harte Regel (B4) und
adaptiver Kollokations-Floor an den Grounding-Fakten (B6, Teil 6).

Offline, ohne LLM/Index. Gepinnt werden drei Kontrakte:

1. Surface-Kontrakt (B4/1): extract_raw_surface liefert value_counts fuer
   ALLE Felder des metadata_values-Outputs (VOR dem Analytik-Filter) und
   weist die gefilterten Identifier-Felder mit count>0 als
   identifier_value_fields aus. Nur Zaehler, keine Wertelisten - die
   Surface bleibt bounded.
2. Facts- und Regel-Kontrakt (B4/3): count-only-Fact mit grounding_quote
   'value_count[<feld>]=<n>' fuer Identifier-Felder, plus harte Regel
   metadata_values_are_falsely_absent (Klasse d: exakter
   Evidenz-Widerspruch), konservativ ohne False-Positives.
3. Floor-Fakten (B6/6): Limitation-Text folgt der adaptiven Kalibrierung,
   wenn der Tool-Output node_frequency/min_freq traegt (defensiv, sonst
   Alt-Verhalten); nicht-leere Ergebnisse mit Floor<5 tragen die
   Limitation 'Explorativ, n klein' am Kollokations-Methodenfakt.
"""

import json
import unittest

from candyconc.candyconc_copilot.claim_rules import (
    CLAIM_RULE_REGISTRY,
    HARD_RULE_NAMES,
)
from candyconc.candyconc_copilot.claim_rules._shared import (
    _metadata_value_counts,
)
from candyconc.candyconc_copilot.claim_rules.metadata import (
    _metadata_values_falsely_absent_fields,
)
from candyconc.candyconc_copilot.grounding_contracts import AnalysisContract
from candyconc.candyconc_copilot.grounding_evidence import (
    build_grounding_surface,
    extract_raw_surface,
)
from candyconc.candyconc_copilot.grounding_facts import (
    _collocation_floor_facts,
    _collocation_method_facts,
    _metadata_value_facts,
    deterministic_observed_facts,
    validate_observed_facts,
)
from candyconc.candyconc_copilot.grounding_schemas import (
    AnswerEnvelope,
    ClaimDraft,
    EvidenceItem,
    ObservedFact,
)
from candyconc.candyconc_copilot.grounding_validation import (
    validate_answer_envelope,
)


# --------------------------------------------------------------------------- #
# Baumaterial: bench-nahe metadata_values-Ausgabe (2000 Docs).                 #
# --------------------------------------------------------------------------- #
def _metadata_output():
    return {
        "status": "success",
        "available_fields": [
            "doc_id", "register", "split", "paired_with", "path",
        ],
        "values": {
            "doc_id": [f"doc-{i:04d}" for i in range(2000)],
            "register": ["social"],
            "split": ["train", "test"],
            "paired_with": [],
            "path": [f"/data/{i:04d}.txt" for i in range(2000)],
        },
    }


def _metadata_item(item_id="ev_meta"):
    raw = extract_raw_surface(_metadata_output())
    return EvidenceItem(
        id=item_id, tool="metadata_values", tool_call_id="m1",
        query=json.dumps({"fields": "all"}), status="success",
        truncated=False, raw_surface=raw,
        grounding_surface=build_grounding_surface(raw),
        analysis_family="metadata",
    )


def _collocate_raw(term, *, min_freq, rows=None, node_frequency=None):
    rows = list(rows or [])
    raw = {
        "status": "success", "rows": rows, "requested_term": term,
        "effective_term": term, "term_mode": "surface_or_cql", "window": 5,
        "within_sentence": True, "min_freq": min_freq, "sort_by": "logdice",
        "result_count": len(rows), "method": {"attribute": "word"},
        "scope": {"corpus_id": "bench", "docset_id": None, "level": "corpus"},
    }
    if node_frequency is not None:
        raw["node_frequency"] = node_frequency
    return raw


def _collocate_item(term, *, min_freq, rows=None, node_frequency=None,
                    item_id="ev1"):
    raw = extract_raw_surface(
        _collocate_raw(
            term, min_freq=min_freq, rows=rows, node_frequency=node_frequency,
        )
    )
    return EvidenceItem(
        id=item_id, tool="collocate_stats", tool_call_id="c1",
        query=json.dumps({"term": term, "window": 5, "min_freq": min_freq,
                          "attribute": "word"}),
        status="success", truncated=False, raw_surface=raw,
        grounding_surface=build_grounding_surface(raw),
        analysis_family="collocation",
    )


def _id_count_fact(field_name="doc_id", count=2000, fact_id="fact_idcount"):
    return ObservedFact(
        id=fact_id,
        statement=(
            f"Das Metadatenfeld '{field_name}' ist belegt und weist "
            f"{count} distinkte Werte aus (ID-/Pfadfeld, Einzelwerte "
            "werden fuer den Kontext nicht aufgelistet)."
        ),
        fact_kind="metadata",
        source_evidence_ids=["metadata_values"],
        grounding_quotes=[
            f"field={field_name}",
            f"value_count[{field_name}]={count}",
        ],
        exactness="exact",
        supports_claims=["counts", "interpretation_anchor"],
    )


# --------------------------------------------------------------------------- #
# B4 (1): Surface-Kontrakt                                                     #
# --------------------------------------------------------------------------- #
class TestRawSurfaceValueCounts(unittest.TestCase):
    def test_value_counts_cover_all_fields_before_filter(self):
        surface = extract_raw_surface(_metadata_output())
        self.assertEqual(surface["value_counts"], {
            "doc_id": 2000,
            "register": 1,
            "split": 2,
            "paired_with": 0,
            "path": 2000,
        })

    def test_identifier_value_fields_only_filtered_with_positive_count(self):
        surface = extract_raw_surface(_metadata_output())
        self.assertEqual(
            set(surface["identifier_value_fields"]), {"doc_id", "path"}
        )
        # register/split sind analytisch, paired_with hat count 0.
        self.assertNotIn("register", surface["identifier_value_fields"])
        self.assertNotIn("split", surface["identifier_value_fields"])
        self.assertNotIn("paired_with", surface["identifier_value_fields"])

    def test_surface_stays_bounded_no_value_lists_for_id_fields(self):
        surface = extract_raw_surface(_metadata_output())
        visible_values = surface.get("values", {})
        self.assertNotIn("doc_id", visible_values)
        self.assertNotIn("path", visible_values)
        self.assertIn("register", visible_values)
        for field_name, entries in visible_values.items():
            if isinstance(entries, list):
                self.assertLessEqual(len(entries), 8, field_name)

    def test_no_identifier_key_when_output_has_no_id_fields(self):
        surface = extract_raw_surface({
            "status": "success",
            "values": {"register": ["social", "news"]},
        })
        self.assertNotIn("identifier_value_fields", surface)
        self.assertEqual(surface["value_counts"], {"register": 2})


# --------------------------------------------------------------------------- #
# B4 (3): count-only-Facts fuer Identifier-Felder                              #
# --------------------------------------------------------------------------- #
class TestIdentifierCountFacts(unittest.TestCase):
    def test_count_only_fact_emitted_with_pinned_quote_format(self):
        item = _metadata_item()
        facts = _metadata_value_facts(item)
        by_quote = {
            quote: fact
            for fact in facts
            for quote in fact.grounding_quotes
        }
        self.assertIn("value_count[doc_id]=2000", by_quote)
        self.assertIn("value_count[path]=2000", by_quote)
        fact = by_quote["value_count[doc_id]=2000"]
        self.assertIn("2000 distinkte Werte", fact.statement)
        self.assertIn("doc_id", fact.statement)
        self.assertEqual(fact.exactness, "exact")

    def test_count_facts_feed_metadata_value_counts(self):
        facts = _metadata_value_facts(_metadata_item())
        counts = _metadata_value_counts(facts)
        self.assertEqual(counts.get("doc_id"), 2000)
        self.assertEqual(counts.get("path"), 2000)

    def test_count_facts_survive_deterministic_validation(self):
        item = _metadata_item()
        facts = deterministic_observed_facts(
            AnalysisContract(analysis_family="metadata"), [item]
        )
        doc_id_counts = [
            fact
            for fact in facts
            if "value_count[doc_id]=2000" in fact.grounding_quotes
        ]
        self.assertEqual(len(doc_id_counts), 1)

    def test_id_only_output_still_yields_count_facts(self):
        raw = extract_raw_surface({
            "status": "success",
            "values": {"doc_id": [f"doc-{i}" for i in range(50)]},
        })
        item = EvidenceItem(
            id="ev_ids", tool="metadata_values", tool_call_id="m2",
            query=json.dumps({}), status="success", truncated=False,
            raw_surface=raw, grounding_surface=build_grounding_surface(raw),
            analysis_family="metadata",
        )
        facts = _metadata_value_facts(item)
        self.assertTrue(any(
            "value_count[doc_id]=50" in fact.grounding_quotes
            for fact in facts
        ))


# --------------------------------------------------------------------------- #
# B4 (3): harte Regel metadata_values_are_falsely_absent                       #
# --------------------------------------------------------------------------- #
class TestFalseAbsenceRule(unittest.TestCase):
    def test_rule_is_pinned_hard_and_registered(self):
        self.assertIn("metadata_values_are_falsely_absent", HARD_RULE_NAMES)
        registered = {entry[0] for entry in CLAIM_RULE_REGISTRY}
        self.assertIn("metadata_values_are_falsely_absent", registered)

    def test_predicate_fires_on_clear_emptiness_claims(self):
        counts = {"doc_id": 2000, "path": 2000}
        for text in (
            "Das Metadatenfeld doc_id ist leer.",
            "Das Feld doc_id enthält keine Werte.",
            "doc_id ist wertlos und traegt nichts bei.",
            "Das Feld doc_id ist nicht belegt.",
            "doc_id liefert keine belegten Werte.",
        ):
            self.assertEqual(
                _metadata_values_falsely_absent_fields(text, counts),
                ["doc_id"],
                text,
            )

    def test_predicate_stays_silent_on_legitimate_claims(self):
        counts = {"doc_id": 2000}
        for text in (
            # Quantifizierte, korrekte Aussage.
            "Das Feld doc_id hat 2000 distinkte Werte.",
            # 'wenige Werte' ist kein Leerheits-Praedikat.
            "Das Feld doc_id hat wenige Werte.",
            # Negierter Treffer.
            "Das Feld doc_id ist nicht leer.",
            "doc_id ist keineswegs wertlos.",
            # Feld ohne value_count-Fact.
            "Das Feld field_xyz ist leer.",
            # Leerheit und Feldname in verschiedenen Saetzen.
            "Das Feld paired_with ist leer. doc_id hat viele Werte.",
            # Kontrast-Klausel trennt die Aussagen.
            "paired_with ist leer, während doc_id belegt ist.",
        ):
            self.assertEqual(
                _metadata_values_falsely_absent_fields(text, counts),
                [],
                text,
            )

    def test_predicate_ignores_zero_count_fields(self):
        self.assertEqual(
            _metadata_values_falsely_absent_fields(
                "Das Feld paired_with ist leer.",
                {"paired_with": 0},
            ),
            [],
        )

    def test_envelope_rejects_false_absence_hard(self):
        envelope = AnswerEnvelope(claims=[
            ClaimDraft(
                id="false_absence",
                claim_kind="observation",
                text=(
                    "Das Metadatenfeld doc_id ist leer und enthält "
                    "keine belegten Werte."
                ),
                fact_ids=["fact_idcount"],
                assertion_level="exact",
            )
        ])
        accepted, rejected, reasons = validate_answer_envelope(
            envelope,
            [_id_count_fact()],
            question_text="Welche Metadatenfelder sind nutzbar?",
            deliverable_kind="analysis_report",
            analysis_family="metadata",
        )
        self.assertIn("false_absence", rejected)
        self.assertTrue(any(
            "leer oder wertlos" in reason
            for reason in reasons["false_absence"]
        ), reasons)

    def test_envelope_accepts_correct_cardinality_claim(self):
        envelope = AnswerEnvelope(claims=[
            ClaimDraft(
                id="honest_cardinality",
                claim_kind="observation",
                text=(
                    "Das Metadatenfeld doc_id ist belegt und weist "
                    "2000 distinkte Werte aus."
                ),
                fact_ids=["fact_idcount"],
                assertion_level="exact",
            )
        ])
        accepted, rejected, reasons = validate_answer_envelope(
            envelope,
            [_id_count_fact()],
            question_text="Welche Metadatenfelder sind nutzbar?",
            deliverable_kind="analysis_report",
            analysis_family="metadata",
        )
        self.assertEqual(rejected, [], reasons)
        self.assertIn("honest_cardinality", accepted)


# --------------------------------------------------------------------------- #
# B6 (6): Floor-Fakten folgen der adaptiven Kalibrierung                       #
# --------------------------------------------------------------------------- #
class TestAdaptiveFloorFacts(unittest.TestCase):
    def test_empty_result_without_node_frequency_keeps_old_text(self):
        item = _collocate_item("Arbeit", min_freq=5)
        facts = _collocation_floor_facts(None, [item])
        self.assertEqual(len(facts), 1)
        limitations = " ".join(facts[0].limitations)
        self.assertIn("min_freq bewusst zu senken", limitations)
        self.assertNotIn("adaptiv", limitations)

    def test_empty_result_with_adaptive_floor_names_calibration(self):
        item = _collocate_item("Arbeit", min_freq=2, node_frequency=5)
        facts = _collocation_floor_facts(None, [item])
        self.assertEqual(len(facts), 1)
        limitations = " ".join(facts[0].limitations)
        self.assertIn("adaptiv auf 2 gesenkt", limitations)
        self.assertIn("Knotenfrequenz 5", limitations)
        self.assertIn("haeufigeres Zielwort", limitations)
        # Keine erneute Senkungs-Verhandlung im neuen Text.
        self.assertNotIn("min_freq bewusst zu senken", limitations)

    def test_adaptive_floor_fact_survives_validation(self):
        item = _collocate_item("Arbeit", min_freq=2, node_frequency=5)
        facts = _collocation_floor_facts(None, [item])
        valid = validate_observed_facts(facts, evidence_items=[item])
        self.assertEqual(len(valid), 1)

    def test_frequent_node_with_default_floor_keeps_old_text(self):
        # Floor 5 wurde NICHT gesenkt: der adaptive Satz waere falsch.
        item = _collocate_item("und", min_freq=5, node_frequency=500)
        facts = _collocation_floor_facts(None, [item])
        self.assertEqual(len(facts), 1)
        limitations = " ".join(facts[0].limitations)
        self.assertNotIn("adaptiv", limitations)
        self.assertIn("min_freq bewusst zu senken", limitations)


class TestExploratoryMethodLimitation(unittest.TestCase):
    _ROWS = [{"word": "Wandel", "f": 3, "logdice": 9.1}]

    def _method_fact(self, item):
        facts = _collocation_method_facts(item)
        method_facts = [
            fact for fact in facts if fact.id.endswith("_method")
        ]
        self.assertEqual(len(method_facts), 1)
        return method_facts[0]

    def test_nonempty_low_floor_result_is_marked_exploratory(self):
        item = _collocate_item(
            "Arbeit", min_freq=2, rows=self._ROWS, node_frequency=5,
        )
        fact = self._method_fact(item)
        limitations = " ".join(fact.limitations)
        self.assertIn("Explorativ, n klein", limitations)
        self.assertIn("KWIC-Beleg", limitations)

    def test_nonempty_default_floor_result_has_no_exploratory_flag(self):
        item = _collocate_item("Arbeit", min_freq=5, rows=self._ROWS)
        fact = self._method_fact(item)
        self.assertEqual(fact.limitations, [])

    def test_low_floor_without_node_frequency_still_marks_exploratory(self):
        # Defensiv: die Kennzeichnung haengt nur an min_freq + Nicht-Leere.
        item = _collocate_item("Arbeit", min_freq=2, rows=self._ROWS)
        fact = self._method_fact(item)
        self.assertIn("Explorativ, n klein", " ".join(fact.limitations))

    def test_empty_low_floor_result_yields_no_method_fact(self):
        # Leere Ergebnisse gehen weiter den Floor-Fakt-Weg (kein Methodenfakt).
        item = _collocate_item("Arbeit", min_freq=2, node_frequency=5)
        self.assertEqual(_collocation_method_facts(item), [])


if __name__ == "__main__":
    unittest.main()
