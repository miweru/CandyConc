"""H10/G2: gepaarte Claim-Evidenz-Bindung (harte Regel term_result_mismatch).

Gutachter-Realfall (H10-Dossier, h10_meta_variablen): die Antwort behauptete
"Fuer `der` sind keine Treffer belegt (total=0)", waehrend der sichtbare
Tool-Output der=917 zeigte — die 0 stammte aus einer ANDEREN Abfrage
desselben Turns. Die Set-Membership-Bindung (Zahl irgendwo in der zitierten
Evidenz) akzeptierte den Claim, weil die andere Abfrage die 0 lieferte.

Gepinnt wird hier:
1. Die Evidenzseite traegt Term-Provenienz: query_count-/KWIC-Total-Fakten
   zitieren das Paar total=/query= (synthetisiert, wenn die Surface die
   query=-Zeile nicht woertlich fuehrt), Frequenzzeilen tragen den Term im
   Statement.
2. Die neue HARTE Regel term_result_mismatch (Klasse (d): exakter
   Evidenz-Widerspruch) weist den Dossier-Claim zurueck.
3. Konservativitaet: konsistente Paare, mehrdeutige Saetze (zwei gebundene
   Terme) und mehrdeutige Evidenz (mehrere Ergebnisse fuer T) feuern NICHT.

Offline, kein LLM, kein Index.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import analysis_grounding
from candyconc.candyconc_copilot.claim_rules import (
    HARD_RULE_NAMES,
    rule_severity,
)
from candyconc.candyconc_copilot.claim_rules.term_binding import (
    _claim_term_result_mismatches,
    _term_result_bindings,
)
from candyconc.candyconc_copilot.grounding_contracts import AnalysisContract
from candyconc.candyconc_copilot.grounding_schemas import (
    AnswerEnvelope,
    ClaimDraft,
    ObservedFact,
)
from candyconc.candyconc_copilot.grounding_validation import (
    validate_answer_envelope,
)

# Woertlich aus dem Dossier-Realfall.
_DOSSIER_CLAIM_TEXT = "Für `der` sind keine Treffer belegt (total=0)."


def _contract(family: str = "metadata_capability") -> AnalysisContract:
    return AnalysisContract(
        mode="tool_analysis",
        track="bounded_analysis",
        analysis_family=family,
        required_evidence=[],
    )


def _frequency_evidence_with_der():
    """frequency_list-Evidenz, deren sichtbare Zeile der=917 zeigt."""
    return analysis_grounding.make_evidence_item(
        item_id="e_freq",
        tool="frequency_list",
        tool_call_id="call_freq",
        query={"group_by": "word"},
        output={
            "status": "success",
            "rows": [
                {"word": "Die", "f": 1023, "rank": 1},
                {"word": "der", "f": 917, "rank": 2},
                {"word": "und", "f": 797, "rank": 3},
            ],
        },
        analysis_family="frequency_analysis",
    )


def _other_query_zero_evidence():
    """query_count-Evidenz einer ANDEREN Abfrage mit total=0."""
    return analysis_grounding.make_evidence_item(
        item_id="e_count_other",
        tool="query_count",
        tool_call_id="call_count_other",
        query={"query": "Metadatenvariable"},
        output={"status": "success", "query": "Metadatenvariable", "total": 0},
        analysis_family="frequency_analysis",
    )


def _dossier_facts():
    contract = _contract()
    return analysis_grounding.deterministic_observed_facts(
        contract,
        [_frequency_evidence_with_der(), _other_query_zero_evidence()],
    )


# --------------------------------------------------------------------------- #
# 1. Severity: die Regel ist bewusst hart gepinnt.
# --------------------------------------------------------------------------- #
def test_term_result_mismatch_is_a_pinned_hard_rule() -> None:
    assert "term_result_mismatch" in HARD_RULE_NAMES
    assert rule_severity("term_result_mismatch") == "hard"


# --------------------------------------------------------------------------- #
# 2. Evidenzseite: Term-Provenienz an den deterministischen Fakten.
# --------------------------------------------------------------------------- #
def test_query_count_fact_carries_paired_query_provenance() -> None:
    facts = _dossier_facts()
    count_fact = next(fact for fact in facts if fact.id.endswith("_total"))
    assert "total=0" in count_fact.grounding_quotes
    assert any(
        quote == "query=Metadatenvariable"
        for quote in count_fact.grounding_quotes
    ), count_fact.grounding_quotes


def test_bindings_pair_terms_with_their_own_results() -> None:
    bindings = _term_result_bindings(_dossier_facts())
    assert bindings.get("der") == {917}
    assert bindings.get("Metadatenvariable") == {0}
    # Die 0 der anderen Abfrage darf NICHT am Term 'der' haengen.
    assert 0 not in bindings.get("der", set())


def test_bindings_resolve_simple_cql_literals() -> None:
    fact = ObservedFact(
        id="cql_total",
        statement=(
            "Die exakte Trefferzahl für die Klartext- oder CQLF-Suchanfrage "
            "'[word=\"Frau\"]' (query_count) ist total=13."
        ),
        fact_kind="count",
        source_evidence_ids=["e1"],
        grounding_quotes=["total=13", 'query=[word="Frau"]'],
        exactness="exact",
        supports_claims=["counts"],
    )
    bindings = _term_result_bindings([fact])
    assert bindings.get('[word="Frau"]') == {13}
    assert bindings.get("Frau") == {13}


# --------------------------------------------------------------------------- #
# 3. Claim-Seite: der Dossier-Fall wird als Widerspruch erkannt.
# --------------------------------------------------------------------------- #
def test_dossier_claim_is_a_mismatch() -> None:
    bindings = _term_result_bindings(_dossier_facts())
    mismatches = _claim_term_result_mismatches(_DOSSIER_CLAIM_TEXT, bindings)
    assert mismatches == [("der", 0, 917)]


def test_consistent_pairing_does_not_fire() -> None:
    bindings = _term_result_bindings(_dossier_facts())
    assert _claim_term_result_mismatches(
        "Für `Metadatenvariable` sind keine Treffer belegt (total=0).",
        bindings,
    ) == []
    assert _claim_term_result_mismatches(
        "Die Frequenzzeile zeigt `der` mit 917 Treffern.",
        bindings,
    ) == []


def test_two_bound_terms_in_one_sentence_are_ambiguous() -> None:
    bindings = _term_result_bindings(_dossier_facts())
    assert _claim_term_result_mismatches(
        "Für `der` und `Metadatenvariable` sind zusammen 0 Treffer belegt.",
        bindings,
    ) == []


def test_conflicting_evidence_values_for_a_term_do_not_fire() -> None:
    bindings = {"der": {917, 3}}
    assert _claim_term_result_mismatches(_DOSSIER_CLAIM_TEXT, bindings) == []


def test_unmarked_terms_or_missing_result_lexeme_do_not_fire() -> None:
    bindings = _term_result_bindings(_dossier_facts())
    # Term ohne Markierung: keine Paarung (konservativ per Bauart).
    assert _claim_term_result_mismatches(
        "Für der sind keine Treffer belegt (total=0).",
        bindings,
    ) == []
    # Zahl ohne total/Treffer-Lexem: keine Paarung.
    assert _claim_term_result_mismatches(
        "`der` erscheint 3 Mal in der Tabelle.",
        bindings,
    ) == []


# --------------------------------------------------------------------------- #
# 4. Ende-zu-Ende: validate_answer_envelope weist den Dossier-Claim hart ab.
# --------------------------------------------------------------------------- #
def test_envelope_rejects_dossier_claim_hard() -> None:
    facts = _dossier_facts()
    zero_fact_id = next(
        fact.id for fact in facts if fact.id.endswith("_total")
    )
    der_fact_id = next(
        fact.id
        for fact in facts
        if "'der'" in fact.statement and "f=917" in fact.statement
    )
    envelope = AnswerEnvelope(
        claims=[
            ClaimDraft(
                id="dossier_claim",
                claim_kind="observation",
                text=_DOSSIER_CLAIM_TEXT,
                # Der Realfall zitiert die Evidenz der ANDEREN Abfrage: die 0
                # ist damit set-membership-gedeckt — genau die G2-Luecke.
                fact_ids=[zero_fact_id],
                assertion_level="exact",
            ),
            ClaimDraft(
                id="consistent_claim",
                claim_kind="observation",
                text="Die Frequenzzeile zeigt `der` mit 917 Treffern.",
                fact_ids=[der_fact_id],
                assertion_level="exact",
            ),
        ]
    )
    accepted, rejected, reasons = validate_answer_envelope(
        envelope,
        facts,
        question_text="Welche Metadatenvariablen gibt es?",
        deliverable_kind="analysis_report",
        analysis_family="metadata_capability",
    )
    assert "dossier_claim" in rejected, (accepted, reasons)
    assert any(
        "widersprechen" in reason and "'der'" in reason
        for reason in reasons.get("dossier_claim", [])
    ), reasons
    # Der konsistente Claim wird von der neuen Regel nicht angefasst.
    assert not any(
        "verheiratet" in reason
        for reason in reasons.get("consistent_claim", [])
    ), reasons
