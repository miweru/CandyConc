"""Anker-Tests der Severity-Politik (Produktentscheid 2026-08).

Hart blockiert wird NUR Fabrikation. Die harten Regeln sind eine kleine,
explizit gepinnte Liste (vier Klassen: erfundene Referenzen/ungebundene
Zahlen, Negativ-Claims ohne Such-Anker, Forbidden-Claims-Liste, direkte
Widersprueche zur Evidenz). Alle uebrigen Regeln sind beratend: ihre
Befunde erscheinen als Annotationen in ``envelope.advisories`` und
blockieren den Claim nicht.

Diese Datei ist der Anker des Produktentscheids: wer eine Regel hart
machen will, muss sowohl ``HARD_RULE_NAMES`` als auch die hier gepinnte
Erwartung ausdruecklich aendern.
"""

from candyconc.candyconc_copilot.claim_rules import (
    CLAIM_RULE_REGISTRY,
    DEFAULT_RULE_SEVERITY,
    HARD_RULE_NAMES,
    RULE_SEVERITY_ADVISORY,
    RULE_SEVERITY_HARD,
    rule_severity,
)
from candyconc.candyconc_copilot.claim_rules._table import PatternRule
from candyconc.candyconc_copilot.grounding_schemas import (
    AnswerEnvelope,
    ClaimDraft,
    DEFAULT_FORBIDDEN_CLAIMS,
    ObservedFact,
)
from candyconc.candyconc_copilot.grounding_validation import (
    validate_answer_envelope,
)


# Der Produktentscheid als Daten: genau diese Regeln blockieren.
EXPECTED_HARD_RULE_NAMES = frozenset({
    # (a) ungebundene/falsch gebundene Zahlen + erfundene Zitate
    "numeric_tokens",
    "unsupported_count_bindings",
    "unsupported_ratio_bindings",
    "unsupported_rate_bindings",
    "unsupported_percent_bindings",
    "unsupported_elliptical_counts",
    "unsupported_postposed_counts",
    "unsupported_unit_free_counts",
    "unsupported_word_percent_bindings",
    "unsupported_natural_metrics",
    "unsupported_metric_maxima",
    "unsupported_metric_ranges",
    "unsupported_rate_denominators",
    "unsupported_assignments",
    "row_field_assignments_are_atomic",
    "unsupported_quoted_segments",
    # (b) Negativ-/Praesenz-Claims ohne Such-Anker in der Evidenz
    "unsupported_presence",
    # (c) Forbidden-Claims-Liste (DEFAULT_FORBIDDEN_CLAIMS)
    "item",
    # (d) direkte, exakt gepruefte Widersprueche zur Evidenz
    "unsupported_directional_presence",
    "unsupported_frequency_directions",
    # H9 (V3): ein f/pmw-Paar derselben Entitaet, das dem eindeutigen
    # Tokennenner arithmetisch widerspricht (pmw != f/token_count*1e6,
    # Toleranz 0.5% + Rundungsschlupf), ist ein exakter Evidenz-Widerspruch.
    "pmw_inconsistent_with_count",
    "normalised_time_trend_status",
    "declared_sample_cardinality_is_wrong",
    "word_sketch_evidence_is_falsely_absent",
    # H6 (B4): faelschlich behauptete Metadaten-Leere trotz value_count>0.
    "metadata_values_are_falsely_absent",
    # H10/G2: gepaarte Term<->Ergebnis-Bindung (Claim schreibt Term T ein
    # Ergebnis zu, das der Evidenz FUER T widerspricht).
    "term_result_mismatch",
    "claim_corpus_token_basis_is_visible",
    "claim_total_hits_basis_is_visible",
})


def test_hard_rules_are_exactly_the_pinned_fabrication_classes():
    assert HARD_RULE_NAMES == EXPECTED_HARD_RULE_NAMES
    hard_in_registry = {
        entry[0]
        for entry in CLAIM_RULE_REGISTRY
        if entry[3] == RULE_SEVERITY_HARD
    }
    assert hard_in_registry == EXPECTED_HARD_RULE_NAMES


def test_every_registry_entry_carries_a_derived_severity():
    for name, rule, families, severity in CLAIM_RULE_REGISTRY:
        assert severity in {RULE_SEVERITY_HARD, RULE_SEVERITY_ADVISORY}
        # Severity ist abgeleitet, nie inline gesetzt: Mitgliedschaft in
        # HARD_RULE_NAMES ist die einzige Quelle.
        assert severity == rule_severity(name)
        assert (severity == RULE_SEVERITY_HARD) == (name in HARD_RULE_NAMES)


def test_default_severity_is_advisory():
    assert DEFAULT_RULE_SEVERITY == RULE_SEVERITY_ADVISORY
    # Eine Regel, die nicht ausdruecklich gepinnt wurde, kann nie hart sein.
    assert rule_severity("brandneue_ungepinnte_regel") == RULE_SEVERITY_ADVISORY
    # Auch deklarative Tabellenzeilen sind default-beratend.
    assert PatternRule(name="neu").severity == RULE_SEVERITY_ADVISORY


def test_hard_rules_stay_a_small_minority():
    total = len(CLAIM_RULE_REGISTRY)
    hard = sum(
        1 for entry in CLAIM_RULE_REGISTRY if entry[3] == RULE_SEVERITY_HARD
    )
    assert hard == len(EXPECTED_HARD_RULE_NAMES)
    assert hard < total * 0.3, (hard, total)


# --------------------------------------------------------------------------- #
# Verhaltensanker: advisory annotiert, hard blockiert.
# --------------------------------------------------------------------------- #
def _frequency_fact(fact_id: str = "row_die") -> ObservedFact:
    return ObservedFact(
        id=fact_id,
        statement="Die sichtbare Frequenzzeile zeigt 'die' mit f=12.",
        fact_kind="ranked_row",
        source_evidence_ids=["frequency_list"],
        grounding_quotes=["row=die; f=12"],
        exactness="top_n_only",
        supports_claims=["counts", "examples", "ranks", "interpretation_anchor"],
    )


def test_advisory_finding_annotates_but_does_not_block():
    # Schluesselwort-Behauptung auf reiner Frequenzevidenz: klassische
    # Methodenkritik (advisory), keine Fabrikation.
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="keyness_overread",
                claim_kind="interpretation",
                text=(
                    "Das Wort die ist ein Schlüsselwort des Korpus und "
                    "besonders charakteristisch für diesen Textbestand."
                ),
                fact_ids=["row_die"],
                assertion_level="qualified",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [_frequency_fact()],
        question_text="Welche Wörter sind besonders häufig?",
        deliverable_kind="analysis_report",
        analysis_family="term_frequency",
    )

    assert accepted == ["keyness_overread"], reasons
    assert rejected == []
    assert reasons == {}
    advisory_notes = envelope.advisories.get("keyness_overread", [])
    assert advisory_notes, envelope.advisories
    assert any("Schlüssel" in note for note in advisory_notes)


def test_unbound_number_still_blocks_hard():
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="fabricated_count",
                claim_kind="observation",
                text="Im Korpus gibt es genau 999 Belege für das Wort die.",
                fact_ids=["row_die"],
                assertion_level="exact",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [_frequency_fact()],
        forbidden_claims=DEFAULT_FORBIDDEN_CLAIMS,
        question_text="Wie häufig ist das Wort die?",
        deliverable_kind="lookup_answer",
        analysis_family="term_frequency",
    )

    assert accepted == []
    assert rejected == ["fabricated_count"]
    assert any("999" in reason for reason in reasons["fabricated_count"])


def test_negative_claim_without_search_anchor_still_blocks_hard():
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="unanchored_absence",
                claim_kind="observation",
                text="Solidarität kommt im Korpus nicht vor.",
                fact_ids=["row_die"],
                assertion_level="exact",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [_frequency_fact()],
        question_text="Kommt Solidarität im Korpus vor?",
        deliverable_kind="lookup_answer",
        analysis_family="term_frequency",
    )

    assert accepted == []
    assert rejected == ["unanchored_absence"]
    assert any(
        "Präsenz- und Abwesenheitsclaims" in reason
        for reason in reasons["unanchored_absence"]
    )


def test_forbidden_claims_list_still_blocks_hard():
    # Die Zahlen 2-5 sind in der Evidenz sichtbar (year_range), aber es gibt
    # keine Rank-Evidenz: der Rangbereichs-Claim faellt genau unter die
    # Forbidden-Claims-Liste.
    fact = ObservedFact(
        id="period",
        statement="Der sichtbare Zeitraum ist year_range=2-5.",
        fact_kind="metadata",
        source_evidence_ids=["metadata_values"],
        grounding_quotes=["year_range=2-5"],
        exactness="exact",
        supports_claims=["examples"],
    )
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="rank_fabrication",
                claim_kind="observation",
                text="Das Wort die liegt auf den Rängen 2-5.",
                fact_ids=["period"],
                assertion_level="exact",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [fact],
        forbidden_claims=DEFAULT_FORBIDDEN_CLAIMS,
        question_text="Wo liegt das Wort die?",
        deliverable_kind="lookup_answer",
        analysis_family="term_frequency",
    )

    assert accepted == []
    assert rejected == ["rank_fabrication"]
    assert any(
        "Rangbereichs-Claims" in reason
        for reason in reasons["rank_fabrication"]
    )


def test_unresolvable_fact_ids_still_block_hard():
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="dangling_reference",
                claim_kind="observation",
                text="Die Frequenzliste zeigt das Wort die.",
                fact_ids=["nicht_existent"],
                assertion_level="qualified",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [_frequency_fact()],
    )

    assert accepted == []
    assert rejected == ["dangling_reference"]
    assert reasons["dangling_reference"] == ["Claim ohne gültige fact_ids."]


def test_advisories_survive_alongside_hard_rejection():
    # Ein Claim kann harte und beratende Befunde zugleich haben: die
    # harten blockieren, die beratenden bleiben als Annotation sichtbar.
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="mixed_findings",
                claim_kind="interpretation",
                text=(
                    "Das Wort die ist mit genau 999 Belegen ein "
                    "Schlüsselwort des Korpus."
                ),
                fact_ids=["row_die"],
                assertion_level="exact",
            )
        ]
    )

    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        [_frequency_fact()],
        question_text="Welche Wörter sind besonders häufig?",
        deliverable_kind="analysis_report",
        analysis_family="term_frequency",
    )

    assert rejected == ["mixed_findings"]
    assert any("999" in reason for reason in reasons["mixed_findings"])
    assert all(
        "Schlüssel" not in reason for reason in reasons["mixed_findings"]
    )
    assert any(
        "Schlüssel" in note
        for note in envelope.advisories.get("mixed_findings", [])
    )


def test_envelope_to_dict_exposes_advisories():
    envelope = AnswerEnvelope(
        claims=[],
        advisories={"claim_x": ["Hinweis"]},
    )
    assert envelope.to_dict()["advisories"] == {"claim_x": ["Hinweis"]}
