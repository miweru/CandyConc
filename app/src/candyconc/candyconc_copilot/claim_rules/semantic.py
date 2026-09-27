"""Semantic-retrieval claim rules: co-occurrence, prevalence and centrality mislabeling predicates plus theme tokenisation.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..grounding_schemas import (
    ObservedFact,
    _RESPONSE_CLAIM_HYPOTHESIS_PATTERN,
    _claim_contains_possible_falsifier,
)
from ._shared import (
    _COLLOCATION_METHOD_MENTION_PATTERN,
    _COLLOCATION_PROFILE_COMPARISON_PATTERN,
    _joined_surface_text,
)


_SEMANTIC_COOCCURRENCE_CLAIM_PATTERN = re.compile(
    r"(?:"
    r"\bsemantisch\w*\s+(?:treffer\w*|such\w*|retrieval\w*)\b"
    r"[^.!?]{0,180}\b(?:beleg|zeig|liefer|ergeb|deut)\w*"
    r"[^.!?]{0,100}\b(?:kookkurrenz\w*|co-?occurr\w*|kollokation\w*)\b"
    r"|"
    r"\b(?:kookkurrenz\w*|co-?occurr\w*|kollokation\w*)\b"
    r"[^.!?]{0,100}\b(?:beleg|zeig|liefer|ergeb|deut)\w*"
    r"[^.!?]{0,180}\bsemantisch\w*\s+(?:treffer\w*|such\w*|retrieval\w*)\b"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_COOCCURRENCE_NEGATION_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht|ohne|weder)\b",
    re.IGNORECASE,
)
_SEMANTIC_RETRIEVAL_FREQUENCY_RANK_PATTERN = re.compile(
    r"\b(?:am\s+häufigsten|am\s+haeufigsten|häufigst\w*|"
    r"haeufigst\w*|most\s+frequent)\b"
    r"[^.!?\n]{0,180}\b(?:kontext\w*|vorkomm\w*|treffer\w*|"
    r"passage\w*|darstellung\w*|context\w*|occurrence\w*|hit\w*)\b",
    re.IGNORECASE,
)
_SEMANTIC_RETRIEVAL_CORPUS_PREVALENCE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:korpus|corpus|datensatz|dataset|korpusdaten|corpus data)\b"
    r"[^.!?\n]{0,180}\b(?:vorherrsch\w*|überwieg\w*|ueberwieg\w*|"
    r"mehrheitlich\w*|dominier\w*|typisch\w*)\b"
    r"|"
    r"\b(?:korpus|corpus|datensatz|dataset|korpusdaten|corpus data)\b"
    r"[^.!?\n]{0,180}\bherrsch\w*\b[^.!?\n]{0,80}\bvor\b"
    r"|"
    r"\b(?:vorherrsch\w*|überwieg\w*|ueberwieg\w*|mehrheitlich\w*|"
    r"dominier\w*|typisch\w*)\b[^.!?\n]{0,180}"
    r"\b(?:korpus|corpus|datensatz|dataset|korpusdaten|corpus data)\b"
    r")",
    re.IGNORECASE,
)
_SEMANTIC_RETRIEVAL_PREVALENCE_TERM_PATTERN = re.compile(
    r"\b(?:häufig\w*|haeufig\w*|oft\w*|überwiegend\w*|"
    r"ueberwiegend\w*|mehrheitlich\w*|dominier\w*|typisch\w*|"
    r"vorherrsch\w*|tendenz\w*|frequent(?:ly)?|often|mostly|"
    r"predominant\w*|typically)\b",
    re.IGNORECASE,
)
_SEMANTIC_RETRIEVAL_CENTRALITY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:zentralst\w*|zentral\w*|central(?:ity|ly)?|core)\b"
    r"[^.!?\n]{0,100}\b(?:passage\w*|treffer\w*|thema\w*|muster\w*|"
    r"diskurs\w*|rahmung\w*|befund\w*)\b"
    r"|"
    r"\b(?:passage\w*|treffer\w*|thema\w*|muster\w*|diskurs\w*|"
    r"rahmung\w*|befund\w*)\b[^.!?\n]{0,100}"
    r"\b(?:zentralst\w*|zentral\w*|central(?:ity|ly)?|core)\b"
    r")",
    re.IGNORECASE,
)
_SOURCE_ATTRIBUTED_CENTRALITY_MENTION_PATTERN = re.compile(
    r"\b(?:passage|wortlaut|quelle|text|treffer)\w*\b"
    r"[^.!?\n]{0,80}\b(?:nenn|bezeichn|verwend|enth(?:a|ä)lt|"
    r"spricht\s+von|formuliert)\w*\b[^.!?\n]{0,100}"
    r"\b(?:zentralst\w*|zentral\w*|central(?:ity|ly)?|core)\b",
    re.IGNORECASE,
)
_NEGATED_PREVALENCE_PREFIX_PATTERN = re.compile(
    r"\b(?:nicht|kein(?:e|en|er|es)?|unbelegt|unklar|offen)\b"
    r"[^.!?;]{0,80}$|"
    r"\b(?:lässt|laesst)\s+sich\b[^.!?;]{0,80}$|"
    r"\b(?:cannot|can't|does\s+not|do\s+not|unclear)\b"
    r"[^.!?;]{0,80}$",
    re.IGNORECASE,
)


_SEMANTIC_SIMILARITY_GOAL_PATTERN = re.compile(
    r"\bsemantisch\w*\b[^?!\n]{0,100}"
    r"\b(?:näh\w*|naeh\w*|ähnlich\w*|aehnlich\w*|distanz\w*)\b"
    r"|"
    r"\b(?:näh\w*|naeh\w*|ähnlich\w*|aehnlich\w*|distanz\w*)\b"
    r"[^?!\n]{0,100}\bsemantisch\w*\b",
    re.IGNORECASE,
)


def _uses_single_collocation_as_semantic_similarity(
    claim_text: str,
) -> bool:
    return bool(
        _SEMANTIC_SIMILARITY_GOAL_PATTERN.search(claim_text or "")
        and _COLLOCATION_METHOD_MENTION_PATTERN.search(claim_text or "")
        and _COLLOCATION_PROFILE_COMPARISON_PATTERN.search(
            claim_text or ""
        )
        is None
    )


def _has_positive_semantic_cooccurrence_claim(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?;])\s+", str(text or "")):
        if (
            _SEMANTIC_COOCCURRENCE_CLAIM_PATTERN.search(sentence)
            and not _SEMANTIC_COOCCURRENCE_NEGATION_PATTERN.search(sentence)
        ):
            return True
    return False


def _semantic_retrieval_is_mislabeled_as_frequency(
    text: str,
    facts: Sequence[ObservedFact],
    *,
    claim_kind: str = "",
    assertion_level: str = "",
) -> bool:
    """A similarity ranking does not rank corpus-context prevalence."""

    explicit_prevalence = bool(
        _SEMANTIC_RETRIEVAL_FREQUENCY_RANK_PATTERN.search(text or "")
        or _SEMANTIC_RETRIEVAL_CORPUS_PREVALENCE_PATTERN.search(text or "")
    )
    if not explicit_prevalence:
        for match in _SEMANTIC_RETRIEVAL_PREVALENCE_TERM_PATTERN.finditer(
            text or ""
        ):
            prefix = str(text or "")[max(0, match.start() - 100) : match.start()]
            if _NEGATED_PREVALENCE_PREFIX_PATTERN.search(prefix):
                continue
            explicit_prevalence = True
            break
    if not explicit_prevalence:
        return False
    has_semantic_retrieval = any(
        any(
            "semantic_search" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in facts
    )
    if not has_semantic_retrieval:
        return False
    prospective_hypothesis = bool(
        claim_kind == "interpretation"
        and assertion_level == "tentative"
        and any(
            "interpretation_anchor" in fact.supports_claims
            for fact in facts
        )
        and _RESPONSE_CLAIM_HYPOTHESIS_PATTERN.search(text or "")
        and _claim_contains_possible_falsifier(text or "")
        # A hypothesis may predict a future full-corpus distribution. It may
        # not redefine an observed similarity rank as a frequency rank.
        and _SEMANTIC_RETRIEVAL_FREQUENCY_RANK_PATTERN.search(text or "")
        is None
    )
    if prospective_hypothesis:
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return re.search(
        r"\b(?:context_count|context_frequency|coded_contexts|"
        r"sentiment_count)\s*=",
        source_surface,
        re.IGNORECASE,
    ) is None


def _semantic_retrieval_is_mislabeled_as_centrality(
    text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """A similarity rank identifies candidates, not thematic centrality."""

    has_semantic_retrieval = any(
        any(
            "semantic_search" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in facts
    )
    if not has_semantic_retrieval:
        return False
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", str(text or "")):
        centrality_match = _SEMANTIC_RETRIEVAL_CENTRALITY_PATTERN.search(
            sentence
        )
        if centrality_match is None:
            continue
        prefix = sentence[max(0, centrality_match.start() - 100) : centrality_match.start()]
        if _NEGATED_PREVALENCE_PREFIX_PATTERN.search(prefix):
            continue
        if _SOURCE_ATTRIBUTED_CENTRALITY_MENTION_PATTERN.search(sentence):
            continue
        return True
    return False


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_has_positive_semantic_cooccurrence_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6745-6756)."""
    if "_has_positive_semantic_cooccurrence_claim" in _vae_ctx:
        _has_positive_semantic_cooccurrence_claim = _vae_ctx["_has_positive_semantic_cooccurrence_claim"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if (
        _has_positive_semantic_cooccurrence_claim(claim.text)
        and any(
            "semantische Treffer" in fact.statement
            for fact in facts
        )
    ):
        claim_reasons.append(
            "Semantische Top-N-Treffer belegen Ähnlichkeit im Retrieval, "
            "aber keine lokale Kookkurrenz oder Kollokation; dafür ist "
            "KWIC- oder Kollokationsevidenz nötig."
        )
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_semantic_retrieval_is_mislabeled_as_frequency(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6757-6767)."""
    if "_semantic_retrieval_is_mislabeled_as_frequency" in _vae_ctx:
        _semantic_retrieval_is_mislabeled_as_frequency = _vae_ctx["_semantic_retrieval_is_mislabeled_as_frequency"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _semantic_retrieval_is_mislabeled_as_frequency(
        claim.text,
        facts,
        claim_kind=claim.claim_kind,
        assertion_level=claim.assertion_level,
    ):
        claim_reasons.append(
            "Die Rangfolge einer semantischen Suche misst "
            "Retrieval-Ähnlichkeit, nicht die Häufigkeit oder Prävalenz "
            "von Kontexten im Korpus."
        )


def _vae_rule_semantic_retrieval_is_mislabeled_as_centrality(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6768-6777)."""
    if "_semantic_retrieval_is_mislabeled_as_centrality" in _vae_ctx:
        _semantic_retrieval_is_mislabeled_as_centrality = _vae_ctx["_semantic_retrieval_is_mislabeled_as_centrality"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _semantic_retrieval_is_mislabeled_as_centrality(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Die Rangfolge einer semantischen Suche misst "
            "Retrieval-Ähnlichkeit zur Suchanfrage, nicht thematische "
            "Zentralität im Korpus. Nenne Rangposition und "
            "Ähnlichkeitswert der Zeile, statt sie als "
            "Häufigkeits- oder Zentralitätsbefund auszugeben."
        )


def _vae_rule_uses_single_collocation_as_semantic_similarity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6875-6888)."""
    if "_uses_single_collocation_as_semantic_similarity" in _vae_ctx:
        _uses_single_collocation_as_semantic_similarity = _vae_ctx["_uses_single_collocation_as_semantic_similarity"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind in {"followup_questions", "method_advice"}
        and claim.claim_kind in {"followup", "interpretation"}
        and _uses_single_collocation_as_semantic_similarity(
            claim.text
        )
    ):
        claim_reasons.append(
            "Eine einzelne Kollokationsanalyse misst lokale "
            "distributionelle Assoziation, aber noch keine semantische "
            "Nähe zwischen Lexemen. Dafür müssen Kollokationsprofile mit "
            "einem benannten Ähnlichkeits- oder Distanzmaß verglichen "
            "werden; alternativ frage direkt nach den Kollokaten."
        )
