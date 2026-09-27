"""H6 Paket P2: Renderer-Familie (Befunde B2/B3/B4/B5/B8-S5).

Alle Tests laufen offline gegen reine Funktionen und Fixture-Objekte
(kein LLM, kein Index, keine Live-Calls). Geprueft werden:

- B3(1): Gebrauchsfragen ("Wie wird X verwendet?") klassifizieren als
  analysis_report/bounded_analysis, echte Presence-Fragen bleiben Lookup.
- B3(2): Der Presence-Renderer zeigt bei >=3 Trefferzeilen >=3 Beispiele.
- B4(2): Der Metadaten-Renderer behauptet nie "keine Werte", wenn der
  B4-Surface-Kontrakt (value_counts) count>0 ausweist; defensiv ohne Surface.
- B2(2): Kein internes ID-Leak (Observed Fact/ev-IDs) im Explorations-
  Renderer; Kapitulationszeile 1 byte-identisch plus Kontrakt-Limitation;
  Hypothesen-Ehrlichkeitszeile bei angeforderten Hypothesen.
- B2(4): _compact_sentences schneidet satz-schonend, _compact_quote auf
  Wortgrenze.
- B5(1): Referenz-Renderer dedupliziert casefold-tolerant und gegen den
  gerenderten Praefix ("40 40").
- B8-S5: Duplikat-Faltung im Claim-Renderer (identischer normalisierter
  Text oder identisches sichtbares Label rendert nur einmal).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from candyconc.candyconc_copilot.grounding_contracts import (  # noqa: E402
    AnalysisContract,
    heuristic_analysis_contract,
)
from candyconc.candyconc_copilot.grounding_markdown import (  # noqa: E402
    _build_exploratory_markdown,
    _build_kwic_presence_markdown,
    _build_metadata_capability_markdown,
    _claim_dedup_signature,
    _visible_claim_label,
    build_grounded_markdown,
    build_verified_claim_markdown,
)
from candyconc.candyconc_copilot.grounding_refs import (  # noqa: E402
    resolve_references,
)
from candyconc.candyconc_copilot.grounding_schemas import (  # noqa: E402
    AnswerEnvelope,
    ClaimDraft,
    EvidenceItem,
    ObservedFact,
    ResponseRequirement,
    _compact_quote,
    _compact_sentences,
)

_TOOLS = ["run_cqlf_query", "kwic_context", "metadata_values", "frequency_list"]


def _evidence_item(item_id: str, tool: str, raw_surface: dict) -> EvidenceItem:
    return EvidenceItem(
        id=item_id,
        tool=tool,
        tool_call_id=f"call_{item_id}",
        query="{}",
        status="success",
        truncated=False,
        raw_surface=raw_surface,
    )


class TestGebrauchsfrageKlassifikation:
    """B3(1): Gebrauchsfragen sind Analysen, keine Presence-Lookups."""

    def test_usage_question_yields_analysis_report(self):
        contract = heuristic_analysis_contract(
            "Wie wird 'Zeit' verwendet? Zeige KWIC-Belege im Kontext.",
            available_tools=_TOOLS,
            read_only_tools=_TOOLS,
        )
        assert contract is not None
        assert contract.analysis_family == "kwic_context"
        assert contract.deliverable_kind == "analysis_report"
        assert contract.track == "bounded_analysis"

    def test_presence_question_keeps_lookup_shortcut(self):
        contract = heuristic_analysis_contract(
            "Kommt das Wort 'Zeit' im Korpus vor? Zeige den Kontext.",
            available_tools=_TOOLS,
            read_only_tools=_TOOLS,
        )
        assert contract is not None
        assert contract.analysis_family == "kwic_context"
        assert contract.deliverable_kind == "lookup_answer"
        assert contract.track == "lookup"
        assert contract.response_shape == "grounded_kwic_presence"


class TestPresenceRendererBeispiele:
    """B3(2): Nie wieder genau EIN Beleg bei mehrstelliger Trefferzahl."""

    def _kwic_item(self, n_rows: int) -> EvidenceItem:
        rows = [
            {
                "left": f"linker Kontext {i}",
                "kw": "Zeit",
                "right": f"rechter Kontext {i}",
            }
            for i in range(n_rows)
        ]
        return _evidence_item(
            "ev1",
            "run_cqlf_query",
            {"total": 80882, "rows_seen": n_rows, "rows": rows},
        )

    def test_three_rows_render_three_examples(self):
        markdown = _build_kwic_presence_markdown(
            [self._kwic_item(5)],
            question_scope="Kommt 'Zeit' vor?",
            evidence_gaps=[],
        )
        assert "total=80882" in markdown
        assert markdown.count("- `linker Kontext") >= 3

    def test_single_row_keeps_single_example_sentence(self):
        markdown = _build_kwic_presence_markdown(
            [self._kwic_item(1)],
            question_scope="Kommt 'Zeit' vor?",
            evidence_gaps=[],
        )
        assert "Beispiel: `linker Kontext 0 Zeit rechter Kontext 0`." in markdown


class TestMetadatenRendererValueCounts:
    """B4(2): count>0 wird nie als 'keine Werte' umformuliert."""

    def test_identifier_field_with_count_renders_cardinality(self):
        item = _evidence_item(
            "ev1",
            "metadata_values",
            {
                "available_fields": ["register", "doc_id"],
                "values": {"register": ["social"]},
                "value_counts": {"register": 1, "doc_id": 2000},
                "identifier_value_fields": ["doc_id"],
            },
        )
        markdown = _build_metadata_capability_markdown(
            [item],
            evidence_gaps=[],
        )
        assert (
            "- `doc_id`: 2000 distinkte Werte (dokumentspezifisches "
            "ID-/Pfad-Feld, Einzelwerte für den Kontext nicht aufgelistet)"
        ) in markdown
        assert "`doc_id`: keine Werte" not in markdown
        assert "- `register`: `social`" in markdown

    def test_nonidentifier_field_with_count_renders_neutral_cardinality(self):
        item = _evidence_item(
            "ev1",
            "metadata_values",
            {
                "available_fields": ["hash_bucket"],
                "values": {},
                "value_counts": {"hash_bucket": 7},
            },
        )
        markdown = _build_metadata_capability_markdown(
            [item],
            evidence_gaps=[],
        )
        assert (
            "- `hash_bucket`: 7 distinkte Werte "
            "(Einzelwerte für den Kontext nicht aufgelistet)"
        ) in markdown
        assert "keine Werte im sichtbaren Tool-Output" not in markdown

    def test_count_zero_or_missing_keeps_honest_empty_line(self):
        item = _evidence_item(
            "ev1",
            "metadata_values",
            {
                "available_fields": ["leer", "unbekannt"],
                "values": {},
                "value_counts": {"leer": 0},
            },
        )
        markdown = _build_metadata_capability_markdown(
            [item],
            evidence_gaps=[],
        )
        assert "- `leer`: keine Werte im sichtbaren Tool-Output" in markdown
        assert "- `unbekannt`: keine Werte im sichtbaren Tool-Output" in markdown

    def test_defensive_without_surface_contract_fields(self):
        # Solange das andere Paket value_counts noch nicht liefert, bleibt
        # das Alt-Verhalten unveraendert (kein KeyError, keine neue Zeile).
        item = _evidence_item(
            "ev1",
            "metadata_values",
            {
                "available_fields": ["doc_id", "register"],
                "values": {"register": ["social"]},
            },
        )
        markdown = _build_metadata_capability_markdown(
            [item],
            evidence_gaps=[],
        )
        assert "- `doc_id`: keine Werte im sichtbaren Tool-Output" in markdown
        assert "- `register`: `social`" in markdown


class TestExplorationsRendererIdFrei:
    """B2(2): Keine internen Fakt-/Evidenz-IDs im sichtbaren Text."""

    def _fact(self, fact_id: str, statement: str, kind: str = "count") -> ObservedFact:
        return ObservedFact(
            id=fact_id,
            statement=statement,
            fact_kind=kind,
            source_evidence_ids=["ev1"],
        )

    def test_fallback_bullets_render_tool_names_not_ids(self):
        item = _evidence_item(
            "ev1",
            "frequency_list",
            {"rows": []},
        )
        markdown = _build_exploratory_markdown(
            [
                self._fact("f001", "Der sichtbare Suchlauf weist total=42 aus."),
                self._fact(
                    "f002",
                    "Die Frequenzliste beginnt mit dem Token und.",
                    kind="ranked_row",
                ),
            ],
            [item],
            evidence_gaps=[],
        )
        assert "Werkzeug `frequency_list`" in markdown
        assert "Observed Fact" not in markdown
        assert re.search(r"\bev\d+\b", markdown) is None
        assert re.search(r"\bf\d{3}\b", markdown) is None

    def test_capitulation_keeps_line_one_and_contract_limitation(self):
        markdown = _build_exploratory_markdown(
            [],
            [],
            evidence_gaps=[],
        )
        lines = markdown.splitlines()
        assert lines[0] == (
            "Ich kann diese Analyse gerade nicht sicher "
            "tool-gestützt beantworten."
        )
        assert (
            "- Es liegt keine belegbare Tool-Evidenz für eine Analyse vor."
            in lines
        )
        assert "AnalysisContract" not in markdown

    def test_hypothesis_request_adds_honesty_line(self):
        contract = AnalysisContract(
            mode="tool_analysis",
            track="exploratory_research",
            analysis_family="open_research",
            deliverable_kind="analysis_report",
            question_scope=(
                "Formuliere 2-3 Sprachhypothesen zum Korpus."
            ),
            response_requirements=[
                ResponseRequirement(
                    id="req1",
                    description="2-3 pruefbare Hypothesen",
                    source_quote="Formuliere 2-3 Sprachhypothesen",
                )
            ],
        )
        item = _evidence_item(
            "ev1",
            "frequency_list",
            {
                "rows": [
                    {"word": "Zeit", "f": 812},
                    {"word": "Arbeit", "f": 511},
                ],
                "corpus_tokens": 56191,
            },
        )
        markdown = build_grounded_markdown(
            contract,
            [],
            [item],
            evidence_gaps=[],
        )
        # Verhalten statt Wortlaut: die Zeile sagt, dass die angefragten
        # Hypothesen fehlen, und nennt den Grund. Der genaue Satz gehoert
        # dem Verfasser (Hausregel: kein Gedankenstrich, kein Semikolon).
        assert "Angefragte Hypothesen: nicht enthalten" in markdown
        assert "vor der Modell-Synthese" in markdown
        assert "—" not in markdown and ";" not in markdown

    def test_without_hypothesis_request_no_honesty_line(self):
        contract = AnalysisContract(
            mode="tool_analysis",
            track="exploratory_research",
            analysis_family="open_research",
            deliverable_kind="analysis_report",
            question_scope="Was faellt im Korpus auf?",
        )
        item = _evidence_item(
            "ev1",
            "frequency_list",
            {
                "rows": [{"word": "Zeit", "f": 812}],
                "corpus_tokens": 56191,
            },
        )
        markdown = build_grounded_markdown(
            contract,
            [],
            [item],
            evidence_gaps=[],
        )
        assert "Angefragte Hypothesen" not in markdown


class TestSatzSchonendeKompaktion:
    """B2(4): Limitations-/Statement-Zeilen enden nie mitten im Wort."""

    def test_cuts_at_last_sentence_end_before_limit(self):
        text = (
            "Der erste Satz ist kurz. Der zweite Satz ist auch noch gut "
            "lesbar. " + "Der dritte Satz ist deutlich zu lang " * 8
        )
        result = _compact_sentences(text, 80)
        assert result == (
            "Der erste Satz ist kurz. Der zweite Satz ist auch noch gut "
            "lesbar."
        )
        assert not result.endswith("...")

    def test_first_sentence_survives_even_over_limit(self):
        text = (
            "Dieser allererste Satz ist laenger als das gesetzte Limit "
            "und bleibt trotzdem vollstaendig erhalten. Zweiter Satz."
        )
        result = _compact_sentences(text, 40)
        assert result.endswith("erhalten.")
        assert "Zweiter Satz" not in result

    def test_no_sentence_boundary_falls_back_to_word_boundary(self):
        text = "wortkette " * 40
        result = _compact_sentences(text.strip(), 50)
        assert result.endswith("...")
        assert "wortket..." not in result

    def test_short_text_unchanged(self):
        assert _compact_sentences("Kurzer Satz.", 220) == "Kurzer Satz."

    def test_compact_quote_rounds_to_word_boundary(self):
        text = (
            "Die sichtbaren semantischen Treffer liefern konkrete "
            "Passagen statt abstrakter Werte"
        )
        result = _compact_quote(text, 70)
        assert len(result) <= 70
        assert result.endswith("...")
        stem = result[:-3]
        assert stem == stem.rstrip()
        # Kein angebrochenes Wort: der Stamm endet auf einem vollen Wort
        # des Originals.
        assert stem.split()[-1] in text.split()

    def test_exploratory_limitations_end_on_sentence(self):
        long_limitation = (
            "Diese Limitation beschreibt den sichtbaren Ausschnitt sehr "
            "ausfuehrlich und erklaert die Grenzen der Stichprobe. Danach "
            "folgt ein zweiter Satz, der bei einem Zeichenlimit von "
            "zweihundertzwanzig nicht mehr vollstaendig hineinpasst und "
            "deshalb komplett entfallen muss statt mitten im Wort zu enden."
        )
        markdown = _build_exploratory_markdown(
            [
                ObservedFact(
                    id="f001",
                    statement="Der Suchlauf weist total=42 aus.",
                    fact_kind="count",
                    source_evidence_ids=["ev1"],
                ),
                ObservedFact(
                    id="f009",
                    statement=long_limitation,
                    fact_kind="limitation",
                    source_evidence_ids=["ev1"],
                ),
            ],
            [_evidence_item("ev1", "frequency_list", {"rows": []})],
            evidence_gaps=[],
        )
        for line in markdown.splitlines():
            assert not line.rstrip().endswith("...")


class TestClaimDuplikatFaltung:
    """B8-S5: Exakte Text-/Label-Duplikate rendern nur einmal."""

    def _fact(self) -> ObservedFact:
        return ObservedFact(
            id="f001",
            statement="total=40",
            fact_kind="count",
            source_evidence_ids=["ev1"],
        )

    def _render(self, claims: list[ClaimDraft]) -> str:
        envelope = AnswerEnvelope(claims=claims)
        return build_verified_claim_markdown(
            envelope,
            [claim.id for claim in claims],
            [self._fact()],
            deliverable_kind="analysis_report",
            question_text="Analysiere den Befund.",
            evidence_items=[
                _evidence_item("ev1", "run_cqlf_query", {"total": 40})
            ],
            evidence_gaps=[],
        )

    def test_identical_normalised_text_renders_once(self):
        claims = [
            ClaimDraft(
                id="c1",
                claim_kind="observation",
                text="Der Suchlauf weist total=40 Treffer aus.",
                fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2",
                claim_kind="observation",
                text="Der  Suchlauf   weist total=40 Treffer AUS.",
                fact_ids=["f001"],
            ),
        ]
        markdown = self._render(claims)
        assert markdown.lower().count("weist total=40 treffer aus") == 1

    def test_identical_visible_label_renders_once(self):
        claims = [
            ClaimDraft(
                id="c1",
                claim_kind="observation",
                text="**Kern/Attribut**: alte Zeit dominiert die Relation.",
                fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2",
                claim_kind="observation",
                text="**Kern/Attribut**: alte Zeit dominiert diese Relation.",
                fact_ids=["f001"],
            ),
        ]
        markdown = self._render(claims)
        assert markdown.count("**Kern/Attribut**") == 1
        assert "dominiert die Relation" in markdown

    def test_distinct_claims_survive(self):
        claims = [
            ClaimDraft(
                id="c1",
                claim_kind="observation",
                text="Der Suchlauf weist total=40 Treffer aus.",
                fact_ids=["f001"],
            ),
            ClaimDraft(
                id="c2",
                claim_kind="interpretation",
                text="Die Trefferzahl deutet auf haeufigen Gebrauch hin.",
                fact_ids=["f001"],
            ),
        ]
        markdown = self._render(claims)
        assert "weist total=40 Treffer aus" in markdown
        assert "haeufigen Gebrauch" in markdown

    def test_signature_and_label_helpers(self):
        assert _claim_dedup_signature("  A   b\tC ") == "a b c"
        assert _visible_claim_label("**logDice**: 9,1") == "logdice"
        assert _visible_claim_label("- `Kern/Attribut`: X") == "kern/attribut"
        # Generische Struktur-Labels falten nicht.
        assert _visible_claim_label("**Befund**: X") == ""
        # Gewoehnliche Prosa mit Doppelpunkt ist kein Label.
        assert _visible_claim_label("Die Verteilung zeigt: viel Zeit.") == ""


class TestReferenzRendererDedup:
    """B5(1): casefold-Dedup und Dedup gegen den gerenderten Praefix."""

    @pytest.fixture()
    def bundle(self) -> dict:
        return {
            "contract": {},
            "grounding_surface": [
                "total=40",
                "score_key=logdice",
            ],
            "items": [
                {
                    "id": "ev1",
                    "tool": "run_cqlf_query",
                    "grounding_surface": ["total=40"],
                    "raw_surface": {"total": 40},
                },
                {
                    "id": "ev2",
                    "tool": "query_count",
                    "grounding_surface": ["total=40"],
                    "raw_surface": {"total": 40},
                },
                {
                    "id": "ev3",
                    "tool": "collocate_stats",
                    "grounding_surface": ["score_key=logdice"],
                    "raw_surface": {"score_key": "logdice"},
                },
            ],
        }

    def test_casefold_variant_is_not_duplicated(self, bundle):
        result = resolve_references(
            "Ranking je Relation nach logDice {{ev:ev3.score_key}}.",
            bundle,
        )
        assert result["text"] == "Ranking je Relation nach logDice."
        assert result["resolved"][0]["value"] == "logdice"

    def test_adjacent_markers_with_same_value_render_once(self, bundle):
        result = resolve_references(
            "Gesamttreffer im Korpus: {{ev:ev1.total}} {{ev:ev2.total}}",
            bundle,
        )
        assert result["text"] == "Gesamttreffer im Korpus: 40"
        assert "40 40" not in result["text"]
        # Beide Referenzen bleiben als Provenienz erhalten.
        assert {entry["source_id"] for entry in result["resolved"]} == {
            "ev1",
            "ev2",
        }

    def test_different_values_still_both_render(self, bundle):
        bundle["items"][1]["raw_surface"] = {"total": 41}
        bundle["items"][1]["grounding_surface"] = ["total=41"]
        result = resolve_references(
            "Werte: {{ev:ev1.total}} und {{ev:ev2.total}}.",
            bundle,
        )
        assert result["text"] == "Werte: 40 und 41."
