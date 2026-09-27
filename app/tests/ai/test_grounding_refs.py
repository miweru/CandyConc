"""Tests fuer den deterministischen Referenz-Renderer (grounding_refs).

Alle Tests laufen offline gegen ein Fixture-Bundle (kein LLM, kein Index).
Geprueft werden: Aufloesung aller Referenz-Formen, der unresolved-Pfad mit
ehrlichem Platzhalter, die Bare-Number-Klassen (gebunden/ungebunden/harmlos),
Formatierungs-Paritaet mit dem Markdown-Builder und ein Performance-Smoke.
"""

from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from candyconc.candyconc_copilot import grounding_markdown  # noqa: E402
from candyconc.candyconc_copilot.grounding_refs import (  # noqa: E402
    EVIDENCE_REFERENCE_PATTERN,
    MISSING_EVIDENCE_PLACEHOLDER,
    format_evidence_value,
    reference_syntax_help,
    resolve_references,
)
from candyconc.candyconc_copilot.grounding_schemas import (  # noqa: E402
    EvidenceBundle,
    ObservedFact,
    _strip_internal_fact_references,
)


@pytest.fixture()
def bundle() -> EvidenceBundle:
    return EvidenceBundle(
        contract={},
        items=[
            {
                "id": "ev_count",
                "tool": "run_cqp_query",
                "tool_call_id": "call_1",
                "query": '{"query": "und"}',
                "status": "success",
                "truncated": False,
                "raw_surface": {
                    "total": 919,
                    "corpus_tokens": 56191,
                    # Bewusst NICHT in grounding_surface: prueft, dass vom
                    # Renderer eingesetzte Werte nie als bare number gelten.
                    "secret_offset": 4711,
                },
                "grounding_surface": [
                    "total=919",
                    "corpus_tokens=56191",
                    "query=und",
                ],
                "result_scope": {"corpus_id": "bench"},
            },
            {
                "id": "ev_kwic",
                "tool": "kwic",
                "raw_surface": {
                    "total": 12,
                    "rows": [
                        {
                            "left": "die kleinen",
                            "kw": "Kinder",
                            "right": "spielen draußen",
                        },
                        {
                            "left": "wenn die",
                            "kw": "Kinder",
                            "right": "schlafen",
                        },
                    ],
                },
                "grounding_surface": [
                    'kwic[0] "die kleinen Kinder spielen draußen"',
                    'kwic[1] "wenn die Kinder schlafen"',
                    "total=12",
                ],
            },
            {
                "id": "ev_freq",
                "tool": "frequency_list",
                "raw_surface": {
                    "total": 797,
                    "rows": [
                        {
                            "word": "und",
                            "frequency": 797,
                            "per_million": 14342.1,
                        },
                    ],
                },
                "grounding_surface": [
                    "metric[0] word=und frequency=797 per_million=14342.1",
                    "total=797",
                ],
            },
        ],
        grounding_surface=["date_field=date", "granularity=year"],
    )


@pytest.fixture()
def facts() -> list:
    return [
        ObservedFact(
            id="f001",
            statement="Die Abfrage und ergab 919 Treffer.",
            fact_kind="metadata",
            grounding_quotes=["total=919"],
        ),
    ]


class TestReferenceResolution:
    def test_scalar_refs_resolve_with_builder_formatting(self, bundle):
        result = resolve_references(
            "Insgesamt {{ev:ev_count.corpus_tokens}} Tokens, davon "
            "{{ev:ev_count.total}} Treffer.",
            bundle,
        )
        assert result["text"] == (
            "Insgesamt 56.191 Tokens, davon 919 Treffer."
        )
        assert [entry["kind"] for entry in result["resolved"]] == [
            "value",
            "value",
        ]
        assert result["resolved"][0]["source_id"] == "ev_count"
        assert result["resolved"][0]["value"] == "56.191"
        assert result["unresolved"] == []
        # Eingesetzte Werte sind per Konstruktion belegt: kein Befund.
        assert result["bare_numbers"] == []

    def test_kwic_ref_renders_quote_with_line_id(self, bundle):
        result = resolve_references(
            "Beleg: {{ev:ev_kwic.rows[0]}}",
            bundle,
        )
        assert result["text"] == (
            "Beleg: „die kleinen Kinder spielen draußen“ (ev_kwic, Zeile 0)"
        )

    def test_table_cell_refs_resolve_to_cell_value(self, bundle):
        result = resolve_references(
            "Das Wort {{ev:ev_freq.rows[0].word}} erscheint "
            "{{ev:ev_freq.rows[0].frequency}} Mal "
            "({{ev:ev_freq.rows[0].per_million}} pro Million); Kontextzelle: "
            "{{ev:ev_kwic.rows[1].kw}}.",
            bundle,
        )
        assert result["text"] == (
            "Das Wort und erscheint 797 Mal (14342.1 pro Million); "
            "Kontextzelle: Kinder."
        )
        assert result["unresolved"] == []

    def test_bare_item_ref_uses_primary_scalar(self, bundle):
        result = resolve_references(
            "Die Suche liefert {{ev:ev_count}} Treffer.",
            bundle,
        )
        assert result["text"] == "Die Suche liefert 919 Treffer."

    def test_fact_marker_is_citation_and_stripped(self, bundle, facts):
        result = resolve_references(
            "Der Anstieg ist deutlich {{ev:f001}}.",
            bundle,
            facts,
        )
        assert result["text"] == "Der Anstieg ist deutlich."
        assert result["resolved"] == [
            {
                "ref": "{{ev:f001}}",
                "value": "",
                "source_id": "f001",
                "kind": "citation",
            },
        ]

    def test_fact_field_path_resolves(self, bundle, facts):
        result = resolve_references(
            "Wortlaut: {{ev:f001.grounding_quotes[0]}}",
            bundle,
            facts,
        )
        assert result["text"] == "Wortlaut: total=919"


class TestValueAlreadyStatedDedup:
    """Ein Wert, den das Modell direkt vor dem Marker schon nennt, wird nicht
    verdoppelt (Live-Befund R5: '683 683', '18.761 18 761', 'test, train
    test, train'). Der Marker rendert dann als Zitation."""

    def test_adjacent_value_marker_renders_once(self, bundle):
        result = resolve_references(
            "Die Suche liefert 919 {{ev:ev_count.total}} Treffer.",
            bundle,
        )
        assert result["text"] == "Die Suche liefert 919 Treffer."
        # Referenz bleibt aufgeloest (Provenienz erhalten), nur nicht doppelt.
        assert result["resolved"][0]["source_id"] == "ev_count"
        assert result["resolved"][0]["value"] == "919"
        assert result["bare_numbers"] == []

    def test_grouped_number_dedup_is_format_tolerant(self, bundle):
        # Modell schreibt schmales/anderes Tausendertrennzeichen, der Renderer
        # setzt den Punkt-gruppierten Wert ein: dieselbe Ziffernfolge, keine
        # zweite Kopie.
        for authored in ("56.191", "56 191", "56191"):
            result = resolve_references(
                f"Das Korpus hat {authored} {{{{ev:ev_count.corpus_tokens}}}} "
                "Tokens.",
                bundle,
            )
            assert result["text"] == f"Das Korpus hat {authored} Tokens."

    def test_text_value_dedup(self):
        text_bundle = {
            "contract": {},
            "grounding_surface": ["splits=test, train"],
            "items": [
                {
                    "id": "ev_meta",
                    "tool": "metadata_values",
                    "grounding_surface": ["splits=test, train"],
                    "raw_surface": {"splits": "test, train"},
                }
            ],
        }
        result = resolve_references(
            "Splits: test, train {{ev:ev_meta.splits}}.",
            text_bundle,
        )
        assert result["text"] == "Splits: test, train."

    def test_different_preceding_number_is_not_deduped(self, bundle):
        # 1240 ist NICHT 919: der eingesetzte Wert bleibt (keine False Positive).
        result = resolve_references(
            "Vorher 1240, jetzt {{ev:ev_count.total}} Treffer.",
            bundle,
        )
        assert result["text"] == "Vorher 1240, jetzt 919 Treffer."

    def test_clean_insert_still_works_without_prestated_value(self, bundle):
        # Regressionsanker: ohne vorangestellten Wert setzt der Renderer ein.
        result = resolve_references(
            "Insgesamt {{ev:ev_count.corpus_tokens}} Tokens, davon "
            "{{ev:ev_count.total}} Treffer.",
            bundle,
        )
        assert result["text"] == "Insgesamt 56.191 Tokens, davon 919 Treffer."

    # --- R7/A2 (a): schliessende Zeichen zwischen Wert und Marker ---------

    @staticmethod
    def _word_sketch_bundle():
        return {
            "contract": {},
            "items": [
                {
                    "id": "ev_ws",
                    "tool": "word_sketch",
                    "grounding_surface": ["score_key=logdice", "total=32"],
                    "raw_surface": {"score_key": "logdice", "total": 32},
                }
            ],
        }

    def test_closing_backtick_before_marker_dedups(self):
        # Live-Befund R7 profil_zeit: 'nach `score_key = logdice` logdice.'
        # Der schliessende Backtick verhinderte den endswith-Treffer.
        result = resolve_references(
            "Ranking je Relation nach `score_key = logdice` "
            "{{ev:ev_ws.score_key}}.",
            self._word_sketch_bundle(),
        )
        assert result["text"] == (
            "Ranking je Relation nach `score_key = logdice`."
        )
        # Referenz bleibt aufgeloest (Provenienz erhalten).
        assert result["resolved"][0]["value"] == "logdice"

    def test_typographic_quotes_before_marker_dedup_number(self, bundle):
        # Deckt die Klasse '...„32“ {{ev:...}}' ab: deutsches schliessendes
        # Anfuehrungszeichen vor dem Marker.
        result = resolve_references(
            "Insgesamt „919“ {{ev:ev_count.total}} Treffer.",
            bundle,
        )
        assert result["text"] == "Insgesamt „919“ Treffer."
        assert result["bare_numbers"] == []

    def test_closing_paren_before_marker_dedups(self, bundle):
        result = resolve_references(
            "Der Suchlauf (total 919) {{ev:ev_count.total}} bestätigt das.",
            bundle,
        )
        assert result["text"] == "Der Suchlauf (total 919) bestätigt das."

    def test_word_boundary_guard_survives_closing_strip(self):
        # 'xlogdice`' endet zwar nach dem Strip auf 'logdice', aber an einer
        # Alnum-Grenze: KEIN Dedup, der Wert wird regulaer eingesetzt.
        result = resolve_references(
            "Ranking nach `xlogdice` {{ev:ev_ws.score_key}}.",
            self._word_sketch_bundle(),
        )
        assert result["text"] == "Ranking nach `xlogdice` logdice."

    # --- H8: Satzzeichen zwischen Wert und Marker (Sichtung '98, 98') ------

    def test_comma_between_value_and_marker_dedups(self, bundle):
        # Live-Befund H8 hold_assoz_merkel: 'Treffer: 98, 98 zurueckgegebene
        # Ergebniszeilen' (Wert + Komma + Marker). Das Komma verhinderte den
        # endswith-Treffer des A2-Strips.
        result = resolve_references(
            "Treffer: 919, {{ev:ev_count.total}} zurückgegebene "
            "Ergebniszeilen.",
            bundle,
        )
        assert result["text"] == (
            "Treffer: 919, zurückgegebene Ergebniszeilen."
        )
        # Referenz bleibt aufgeloest (Provenienz erhalten), nur nicht doppelt.
        assert result["resolved"][0]["value"] == "919"
        assert result["bare_numbers"] == []

    def test_semicolon_and_colon_between_value_and_marker_dedup(self, bundle):
        for separator in (";", ":"):
            result = resolve_references(
                f"Gesamt 919{separator} {{{{ev:ev_count.total}}}} Treffer.",
                bundle,
            )
            assert result["text"] == f"Gesamt 919{separator} Treffer."

    def test_comma_after_different_number_is_not_deduped(self, bundle):
        # Safe-Check: '12, 919' darf NICHT dedupen, der gestrippte Tail endet
        # auf '12' und nicht auf dem Markerwert 919.
        result = resolve_references(
            "Zeilen 12, {{ev:ev_count.total}} Treffer insgesamt.",
            bundle,
        )
        assert result["text"] == "Zeilen 12, 919 Treffer insgesamt."


class TestLegacyCitationCompatibility:
    def test_legacy_citation_byte_parity_with_internal_stripper(
        self,
        bundle,
        facts,
    ):
        for raw in (
            "Der Wert ist hoch (f001).",
            "Beide Register zeigen das Muster [f001, f002].",
            "Das belegt f001 und f002 im Detail.",
        ):
            result = resolve_references(raw, bundle, facts)
            assert result["text"] == _strip_internal_fact_references(raw)

    def test_known_legacy_citation_is_recorded_as_resolved(
        self,
        bundle,
        facts,
    ):
        result = resolve_references(
            "Der Wert ist hoch (f001).",
            bundle,
            facts,
        )
        citations = [
            entry
            for entry in result["resolved"]
            if entry["kind"] == "citation"
        ]
        assert [entry["source_id"] for entry in citations] == ["f001"]
        assert result["unresolved"] == []

    def test_unknown_legacy_citation_lands_in_unresolved(self, bundle, facts):
        result = resolve_references(
            "Der Wert ist hoch (f999).",
            bundle,
            facts,
        )
        # Legacy-Verhalten: Zitat wird trotzdem entfernt ...
        assert result["text"] == "Der Wert ist hoch."
        # ... aber der fehlende Beleg wird ehrlich gemeldet.
        assert "f999" in result["unresolved"]
        assert any("f999" in message for message in result["messages"])


class TestUnresolvedReferences:
    def test_unknown_id_yields_honest_placeholder(self, bundle):
        result = resolve_references(
            "Es gibt {{ev:ev_missing.total}} Treffer.",
            bundle,
        )
        assert result["text"] == (
            f"Es gibt {MISSING_EVIDENCE_PLACEHOLDER} Treffer."
        )
        assert result["unresolved"] == ["{{ev:ev_missing.total}}"]
        assert len(result["messages"]) == 1

    def test_unknown_path_yields_honest_placeholder(self, bundle):
        result = resolve_references(
            "Der Wert ist {{ev:ev_count.nope}}.",
            bundle,
        )
        assert MISSING_EVIDENCE_PLACEHOLDER in result["text"]
        assert result["unresolved"] == ["{{ev:ev_count.nope}}"]
        assert any("Pfad" in message for message in result["messages"])

    def test_out_of_range_index_is_unresolved(self, bundle):
        result = resolve_references(
            "Zeile: {{ev:ev_kwic.rows[7]}}",
            bundle,
        )
        assert MISSING_EVIDENCE_PLACEHOLDER in result["text"]
        assert result["unresolved"] == ["{{ev:ev_kwic.rows[7]}}"]


class TestBareNumberDetection:
    def test_bound_numbers_stay_silent(self, bundle):
        result = resolve_references(
            "Die Suche ergab 919 Treffer bei 56.191 Tokens.",
            bundle,
        )
        assert result["bare_numbers"] == []

    def test_unbound_number_is_reported_with_context(self, bundle):
        result = resolve_references(
            "Es finden sich 42 Belege im Material.",
            bundle,
        )
        assert len(result["bare_numbers"]) == 1
        finding = result["bare_numbers"][0]
        assert finding["number"] == "42"
        assert "42 Belege" in finding["context"]

    def test_year_with_date_metadata_is_harmless(self, bundle):
        result = resolve_references(
            "Im Jahr 2020 dominieren kurze Beiträge.",
            bundle,
        )
        assert result["bare_numbers"] == []

    def test_year_without_date_metadata_binds_hard(self):
        bare_bundle = {
            "contract": {},
            "items": [],
            "grounding_surface": ["total=919"],
        }
        result = resolve_references(
            "Im Jahr 2020 dominieren kurze Beiträge.",
            bare_bundle,
        )
        assert [finding["number"] for finding in result["bare_numbers"]] == [
            "2020",
        ]

    def test_markdown_list_ordinals_are_harmless(self, bundle):
        result = resolve_references(
            "1. Schritt eins\n2. Schritt zwei",
            bundle,
        )
        assert result["bare_numbers"] == []

    def test_inserted_values_are_never_flagged(self, bundle):
        # secret_offset=4711 steht NUR in raw_surface, nicht in der
        # grounding_surface: als freie Zahl waere es ungebunden, als
        # eingesetzter Referenzwert ist es per Konstruktion belegt.
        result = resolve_references(
            "Der Versatz liegt bei {{ev:ev_count.secret_offset}} Positionen.",
            bundle,
        )
        assert result["text"] == "Der Versatz liegt bei 4.711 Positionen."
        assert result["bare_numbers"] == []

    def test_authored_copy_of_unlisted_value_is_flagged(self, bundle):
        result = resolve_references(
            "Der Versatz liegt bei 4711 Positionen.",
            bundle,
        )
        assert [finding["number"] for finding in result["bare_numbers"]] == [
            "4711",
        ]

    def test_unbound_percent_is_flagged(self, bundle):
        result = resolve_references(
            "Rund 37 % der Treffer stammen aus einem Dokument.",
            bundle,
        )
        assert [finding["number"] for finding in result["bare_numbers"]] == [
            "37",
        ]

    def test_detection_can_be_disabled(self, bundle):
        result = resolve_references(
            "Es finden sich 42 Belege.",
            bundle,
            detect_bare_numbers=False,
        )
        assert result["bare_numbers"] == []


class TestFormattingParity:
    def test_integer_format_matches_markdown_builder(self):
        # Anker: grounding_markdown._analysis_provenance_lines._number
        # formatiert Ganzzahlen als f"{value:,}".replace(",", ".").
        source = inspect.getsource(grounding_markdown)
        assert 'f"{value:,}".replace(",", ".")' in source
        for value in (0, 919, 4711, 56191, 1234567):
            assert format_evidence_value(value) == (
                f"{value:,}".replace(",", ".")
            )

    def test_scalar_formatting_rules(self):
        assert format_evidence_value(0.5946) == "0.5946"
        assert format_evidence_value(797.0) == "797"
        assert format_evidence_value(True) == "ja"
        assert format_evidence_value(False) == "nein"
        assert format_evidence_value("  und   dann ") == "und dann"

    def test_reference_pattern_and_help_are_consistent(self):
        assert EVIDENCE_REFERENCE_PATTERN.search("x {{ev:ev1.total}} y")
        assert "{{ev:ID}}" in reference_syntax_help()


class TestPerformance:
    def test_smoke_under_5ms_on_2k_word_text(self, bundle, facts):
        sentence = (
            "Die Analyse zeigt {{ev:ev_count.total}} Treffer im Korpus "
            "und die Verteilung bleibt über die Register hinweg stabil, "
            "was die Beobachtung aus der Stichprobe stützt (f001). "
        )
        text = sentence * 90  # >2000 Woerter, 90 Referenzen + 90 Zitationen
        assert len(text.split()) >= 2000
        # Rechenzeit DIESES Threads, nicht Wanduhr und nicht
        # Prozessorzeit. Gemeint ist der Aufwand der Referenzaufloesung.
        #
        # Wanduhr misst jede Verdraengung durch fremde Prozesse mit:
        # gemessen am 2026-08-24 unter Last 10 fiel diese Fassung in 1 von
        # 25 vollen Suitenlaeufen um, Maximum ueber 30 Messreihen 5,10 ms
        # gegen einen Median von 3,42.
        #
        # ``process_time`` summiert ueber ALLE Threads des Prozesses. Im
        # vollen Suitenlauf laufen daneben fremde Threads, und der Test
        # fiel damit weiter um, obwohl er allein 30 von 30 gruen war.
        # ``thread_time`` zaehlt nur diesen Thread und misst damit genau
        # die Arbeit, um die es geht.
        #
        # Die Schwelle bleibt bei 5 ms. Der Test wird nicht lockerer, er
        # misst die richtige Groesse.
        timings = []
        for _ in range(5):
            start = time.thread_time()
            result = resolve_references(text, bundle, facts)
            timings.append(time.thread_time() - start)
        assert result["unresolved"] == []
        assert result["bare_numbers"] == []
        assert min(timings) < 0.005
