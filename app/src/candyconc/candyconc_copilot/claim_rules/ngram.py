"""N-gram claim rules: unit classification, context diversity, function-frequency and semantic-validation predicates.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import List, Sequence

from ..grounding_schemas import (
    ObservedFact,
)
from ._shared import (
    _joined_surface_text,
)
from ._table import PatternRule, run_pattern_rule


_NGRAM_GRAMMATICAL_UNIT_PATTERN = re.compile(
    r"\b(?:präpositionalphras\w*|praepositionalphras\w*|"
    r"nominalphras\w*|verbphras\w*|konnektor(?:en)?|satzglied(?:er)?|"
    r"prepositional\s+phrases?|noun\s+phrases?|verb\s+phrases?|"
    r"connectives?|connectors?)\b",
    re.IGNORECASE,
)
_NGRAM_CONTEXT_DIVERSITY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:in|über|ueber)\s+(?:sehr\s+)?(?:"
    r"(?:vielen|zahlreichen|mehreren)(?:\s+(?:unterschiedlichen|"
    r"verschiedenen|diversen))?|unterschiedlichen|verschiedenen|diversen)\s+"
    r"(?:kontext\w*|dokument\w*|sätz\w*|saetz\w*)\b"
    r"|"
    r"\b(?:breit|gleichmäßig|gleichmaessig)\s+"
    r"(?:über|ueber|in)\s+(?:kontext\w*|dokument\w*|sätz\w*|saetz\w*)\b"
    r"|"
    r"\b(?:kontextuell|dokumentübergreifend|dokumentuebergreifend)\s+"
    r"(?:breit|gestreut|verteilt)\b"
    r")",
    re.IGNORECASE,
)
_NGRAM_FUNCTION_FREQUENCY_PATTERN = re.compile(
    r"\b(?:häufig|haeufig|meist(?:ens)?|typischerweise|regelmäßig|"
    r"regelmaessig|überwiegend|ueberwiegend)\b[^.!?\n]{0,120}"
    r"\b(?:einleit\w*|verbind\w*|markier\w*|lokalisier\w*|"
    r"modifizier\w*|fungier\w*|dient\w*|drück\w*\s+aus|"
    r"drueck\w*\s+aus)\b|"
    r"\b(?:einleit\w*|verbind\w*|markier\w*|lokalisier\w*|"
    r"modifizier\w*|fungier\w*|dient\w*|drück\w*\s+aus|"
    r"drueck\w*\s+aus)\b[^.!?\n]{0,120}"
    r"\b(?:häufig|haeufig|meist(?:ens)?|typischerweise|regelmäßig|"
    r"regelmaessig|überwiegend|ueberwiegend)\b",
    re.IGNORECASE,
)
_NGRAM_DISPERSION_SEMANTIC_TEST_PATTERN = re.compile(
    r"\bdispersion\w*\b[^.!?\n]{0,100}"
    r"\b(?:prüf\w*|pruef\w*|zeig\w*|bestimm\w*|beleg\w*)\b"
    r"[^.!?\n]{0,120}\b(?:bedeut\w*|funktion\w*|lesart\w*|"
    r"semant\w*|pragmat\w*|\w+(?:sätzen|saetzen)\s+vorkomm\w*)\b|"
    r"\b(?:bedeut\w*|funktion\w*|lesart\w*|semant\w*|pragmat\w*|"
    r"\w+(?:sätzen|saetzen)\s+vorkomm\w*)\b[^.!?\n]{0,120}"
    r"\b(?:durch|mittels|mit)\s+(?:einer\s+)?dispersion\w*\b",
    re.IGNORECASE,
)


def _unsupported_ngram_unit_classifications(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    assertion_level: str = "",
) -> List[str]:
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    has_ngram_rows = any(
        fact.fact_kind == "ranked_row"
        and re.search(r"\bngram\s*=", source_surface, re.IGNORECASE)
        for fact in facts
    )
    has_grammar_or_context_evidence = bool(
        any(fact.fact_kind == "kwic_example" for fact in facts)
        or re.search(
            r"\b(?:pos|upos|dependency|relation|constituent)\s*=",
            source_surface,
            re.IGNORECASE,
        )
    )
    if not has_ngram_rows or has_grammar_or_context_evidence:
        return []
    visible_terms = [
        term.casefold()
        for fact in facts
        for term in _ngram_surface_terms(fact)
    ]
    unsupported: List[str] = []
    for match in _NGRAM_GRAMMATICAL_UNIT_PATTERN.finditer(claim_text or ""):
        sentence_start = max(
            (claim_text or "").rfind(mark, 0, match.start())
            for mark in ".!?\n"
        ) + 1
        following_boundaries = [
            position
            for mark in ".!?\n"
            for position in [(claim_text or "").find(mark, match.end())]
            if position >= 0
        ]
        sentence_end = min(following_boundaries, default=len(claim_text or ""))
        sentence = (claim_text or "")[sentence_start:sentence_end]
        is_surface_hypothesis = bool(
            assertion_level in {"tentative", "qualified"}
            and _NGRAM_HYPOTHESIS_PATTERN.search(sentence)
            and _NGRAM_EPISTEMIC_PATTERN.search(sentence)
            and _NGRAM_VALIDATION_PATTERN.search(claim_text or "")
            and any(term in sentence.casefold() for term in visible_terms)
        )
        if not is_surface_hypothesis:
            unsupported.append(match.group(0))
    return unsupported


# --------------------------------------------------------------------------- #
# K3 Slice 3: mechanical rules as PatternRule rows (one generic executor in
# ``_table``). The thin defs below keep name/signature for the facade
# re-exports and the ``_vae_ctx`` seams.
# --------------------------------------------------------------------------- #
_NGRAM_ROW_SURFACE_PATTERN = re.compile(r"\bngram\s*=", re.IGNORECASE)
_NGRAM_DISTRIBUTION_EVIDENCE_PATTERN = re.compile(
    r"\b(?:doc(?:ument)?_coverage|document_count|dispersion)\s*=",
    re.IGNORECASE,
)
_NGRAM_CONTEXT_EVIDENCE_PATTERN = re.compile(
    r"\b(?:syntactic_function|dependency|relation|constituent)\s*=",
    re.IGNORECASE,
)
_NGRAM_KWIC_CONTEXT_SENTENCE_PATTERN = re.compile(
    r"\b(?:kwic|kontext\w*)\b",
    re.IGNORECASE,
)
_NGRAM_DISPERSION_NEGATION_SENTENCE_PATTERN = re.compile(
    r"\bdispersion\w*\b[^.!?\n]{0,60}\b(?:nicht|keine\w*)\b",
    re.IGNORECASE,
)

_RULE_NGRAM_CONTEXT_DIVERSITY = PatternRule(
    name="unsupported_ngram_context_diversity_claims",
    scan="findall",
    claim_patterns=(_NGRAM_CONTEXT_DIVERSITY_PATTERN,),
    evidence_checks=(
        ("any_fact_kind", {"kind": "ranked_row"}),
        ("surface_matches", {"pattern": _NGRAM_ROW_SURFACE_PATTERN}),
        (
            "lacks_counter_evidence",
            {
                "fact_kinds": frozenset({"kwic_example", "distribution"}),
                "pattern": _NGRAM_DISTRIBUTION_EVIDENCE_PATTERN,
            },
        ),
    ),
    per_match_exception="proposed_test",
    families=("ngram_profile",),
    reason="Raw n-gram counts do not measure distinct contexts or documents.",
)

_RULE_NGRAM_FUNCTION_FREQUENCY = PatternRule(
    name="unsupported_ngram_function_frequency_claims",
    scan="findall",
    claim_patterns=(_NGRAM_FUNCTION_FREQUENCY_PATTERN,),
    evidence_checks=(
        ("any_fact_kind", {"kind": "ranked_row"}),
        ("surface_matches", {"pattern": _NGRAM_ROW_SURFACE_PATTERN}),
        (
            "lacks_counter_evidence",
            {
                "fact_kinds": frozenset({"kwic_example"}),
                "pattern": _NGRAM_CONTEXT_EVIDENCE_PATTERN,
            },
        ),
    ),
    per_match_exception="proposed_test",
    families=("ngram_profile",),
    reason="A recurrent contextual function needs context evidence.",
)

_RULE_NGRAM_SEMANTIC_VALIDATION = PatternRule(
    name="unsupported_ngram_semantic_validation_claims",
    scan="sentences",
    sentence_patterns=(_NGRAM_DISPERSION_SEMANTIC_TEST_PATTERN,),
    sentence_exception_patterns=(
        _NGRAM_KWIC_CONTEXT_SENTENCE_PATTERN,
        _NGRAM_DISPERSION_NEGATION_SENTENCE_PATTERN,
    ),
    dedupe=True,
    families=("ngram_profile",),
    reason="Dispersion measures spread, not a use or sentence type.",
)


def _unsupported_ngram_context_diversity_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Raw n-gram counts do not measure distinct contexts or documents."""

    return list(
        run_pattern_rule(
            _RULE_NGRAM_CONTEXT_DIVERSITY, claim_text, facts=facts
        )
    )


def _unsupported_ngram_function_frequency_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Do not infer a recurrent contextual function from a raw n-gram count."""

    return list(
        run_pattern_rule(
            _RULE_NGRAM_FUNCTION_FREQUENCY, claim_text, facts=facts
        )
    )


def _unsupported_ngram_semantic_validation_claims(
    claim_text: str,
) -> List[str]:
    """Dispersion measures spread; it cannot identify a use or sentence type."""

    return list(
        run_pattern_rule(_RULE_NGRAM_SEMANTIC_VALIDATION, claim_text)
    )


_NGRAM_HYPOTHESIS_PATTERN = re.compile(
    r"\b(?:kandidat\w*|routinenkandidat\w*|formulierungsroutine\w*|"
    r"routine\w*|formelhaft\w*|"
    r"formulierungsrahmen\w*|phraseolog\w*|hypothese\w*|muster\w*)\b",
    re.IGNORECASE,
)
_NGRAM_VALIDATION_PATTERN = re.compile(
    r"\b(?:kwic|kontext\w*|dispersion\w*|dokumentstreuung\w*)\b",
    re.IGNORECASE,
)
_NGRAM_EPISTEMIC_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|plausib\w*|"
    r"prüfenswert\w*|pruefenswert\w*|prüfbar\w*|pruefbar\w*|"
    r"kandidat\w*|routinenkandidat\w*|hypothese\w*|eher)\b",
    re.IGNORECASE,
)


def _ngram_surface_terms(fact: ObservedFact) -> List[str]:
    terms: List[str] = []
    surfaces = [fact.statement, *fact.grounding_quotes]
    for surface in surfaces:
        for pattern in (
            r"\bzeigt\s+['\"„](?P<term>[^'\"“]+)['\"“]\s+mit\b",
            r"\bngram\s*=\s*['\"]?(?P<term>[^;|\n'\"]+)",
        ):
            for match in re.finditer(pattern, str(surface or ""), re.IGNORECASE):
                term = " ".join(match.group("term").split()).strip()
                if term and term not in terms:
                    terms.append(term)
    return terms


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_unsupported_ngram_units(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6441-6452)."""
    if "_unsupported_ngram_unit_classifications" in _vae_ctx:
        _unsupported_ngram_unit_classifications = _vae_ctx["_unsupported_ngram_unit_classifications"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_ngram_units" in _vae_ctx:
        unsupported_ngram_units = _vae_ctx["unsupported_ngram_units"]
    unsupported_ngram_units = _unsupported_ngram_unit_classifications(
        analytical_prose,
        facts,
        assertion_level=claim.assertion_level,
    )
    if unsupported_ngram_units:
        claim_reasons.append(
            "Eine N-Gramm-Frequenzzeile belegt ohne Kontext- oder "
            "Grammatikevidenz keine vollständige syntaktische Einheit: "
            + ", ".join(unsupported_ngram_units[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_ngram_units",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_ngram_contexts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6453-6466)."""
    if "_unsupported_ngram_context_diversity_claims" in _vae_ctx:
        _unsupported_ngram_context_diversity_claims = _vae_ctx["_unsupported_ngram_context_diversity_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_ngram_contexts" in _vae_ctx:
        unsupported_ngram_contexts = _vae_ctx["unsupported_ngram_contexts"]
    unsupported_ngram_contexts = (
        _unsupported_ngram_context_diversity_claims(
            analytical_prose,
            facts,
        )
    )
    if unsupported_ngram_contexts:
        claim_reasons.append(
            "N-Gramm-Frequenz zählt Vorkommen, aber belegt ohne KWIC- "
            "oder Dispersionsevidenz keine Vielfalt von Kontexten oder "
            "Dokumenten: "
            + ", ".join(unsupported_ngram_contexts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_ngram_contexts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_multi_ngram_candidate_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6467-6481)."""
    if "_unsupported_multi_ngram_candidate_claim" in _vae_ctx:
        _unsupported_multi_ngram_candidate_claim = _vae_ctx["_unsupported_multi_ngram_candidate_claim"]
    if "_unsupported_ngram_function_frequency_claims" in _vae_ctx:
        _unsupported_ngram_function_frequency_claims = _vae_ctx["_unsupported_ngram_function_frequency_claims"]
    if "analysis_family" in _vae_ctx:
        analysis_family = _vae_ctx["analysis_family"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    unsupported_ngram_function_frequency = (
        _unsupported_ngram_function_frequency_claims(
            analytical_prose,
            facts,
        )
    )
    if (
        analysis_family == "ngram_profile"
        and _unsupported_multi_ngram_candidate_claim(claim, facts)
    ):
        claim_reasons.append(
            "Eine atomare N-Gramm-Kandidatenhypothese darf genau eine "
            "sichtbare Folge deuten; getrennte Kandidaten brauchen "
            "getrennte Claims."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_ngram_function_frequency",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_ngram_semantic_validation(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6490-6502)."""
    if "_unsupported_ngram_semantic_validation_claims" in _vae_ctx:
        _unsupported_ngram_semantic_validation_claims = _vae_ctx["_unsupported_ngram_semantic_validation_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "unsupported_ngram_semantic_validation" in _vae_ctx:
        unsupported_ngram_semantic_validation = _vae_ctx["unsupported_ngram_semantic_validation"]
    unsupported_ngram_semantic_validation = (
        _unsupported_ngram_semantic_validation_claims(
            analytical_prose,
        )
    )
    if unsupported_ngram_semantic_validation:
        claim_reasons.append(
            "Dokumentdispersion prüft Streuung oder Konzentration, aber "
            "keine semantische Funktion oder Satzklasse; dafür braucht "
            "es KWIC-Kontexte beziehungsweise eine Kontextkodierung: "
            + ", ".join(unsupported_ngram_semantic_validation[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_ngram_semantic_validation",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


# K3 Slice 3: declarative rows of this module (see claim_rules._table).
PATTERN_RULES = (
    _RULE_NGRAM_CONTEXT_DIVERSITY,
    _RULE_NGRAM_FUNCTION_FREQUENCY,
    _RULE_NGRAM_SEMANTIC_VALIDATION,
)
