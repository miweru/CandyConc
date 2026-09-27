"""Dispersion claim rules: concentration and evenness direction predicates.

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
    _source_values_for_field,
)


_DISPERSION_SEMANTIC_SCOPE_PATTERN = re.compile(
    r"\b(?:thema|themen|thematisch\w*|inhaltlich\w*\s+nische\w*|"
    r"diskurs(?:feld|bereich|schwerpunkt)\w*|semantisch\w*)\b",
    re.IGNORECASE,
)


_JUILLAND_CONCENTRATION_DIRECTION_PATTERN = re.compile(
    r"\b(?:juilland(?:[’']s)?\s*d|juilland_d)\b"
    r"[^.!?\n]{0,120}\b(?:und|sowie|wie)\b"
    r"[^.!?\n]{0,80}\b(?:hoh\w*|stark\w*)\s+"
    r"(?:konzentration\w*|cluster\w*|bündelung\w*|buendelung\w*)\b|"
    r"\b(?:hoh\w*|groß\w*|gross\w*)\s+"
    r"(?:juilland(?:[’']s)?\s*d|juilland_d)(?:[- ]?wert\w*)?\b"
    r"[^.!?\n]{0,100}\b(?:konzentr\w*|cluster\w*|bündel\w*|buendel\w*)\b",
    re.IGNORECASE,
)
_DP_EVENNESS_DIRECTION_PATTERN = re.compile(
    r"\b(?:hoh\w*|groß\w*|gross\w*)\s+"
    r"(?:dp|dpnorm)(?:[- ]?wert\w*)?\b"
    r"[^.!?\n]{0,100}\b"
    r"(?:gleichmäßig|gleichmaessig|gleichförmig|gleichfoermig)\b",
    re.IGNORECASE,
)
_LOW_CONCENTRATION_PATTERN = re.compile(
    r"\b(?:gering\w*|schwach\w*|niedrig\w*|minimal\w*)\s+"
    r"(?:cluster\w*|konzentr\w*|lokalis\w*|bündel\w*|buendel\w*)\b|"
    r"\b(?:kaum|wenig)\s+(?:geclustert|konzentriert|lokalisiert|"
    r"gebündelt|gebuendelt)\b",
    re.IGNORECASE,
)
_UNSOURCED_DISPERSION_THRESHOLD_PATTERN = re.compile(
    r"\b(?:typisch\w*|üblich\w*|ueblich\w*|etabliert\w*|"
    r"konventionell\w*)\s+(?:grenzwert\w*|schwellenwert\w*)\b|"
    r"\b(?:grenzwert\w*|schwellenwert\w*)\b[^.!?\n]{0,60}"
    r"\b(?:typisch\w*|üblich\w*|ueblich\w*|etabliert\w*|"
    r"konventionell\w*)\b",
    re.IGNORECASE,
)
_MAXIMUM_DOCUMENT_RANGE_PATTERN = re.compile(
    r"\b(?P<found>\d+)\s+(?:"
    r"von\s+(?:(?:höchstens|maximal\w*)\s+)?|"
    r"der\s+(?:höchstens|maximal\w*)\s+(?:möglichen?\s+)?"
    r")(?P<maximum>\d+)\s+(?:möglichen?\s+)?"
    r"(?:treffer[- ]?)?dokument\w*\b",
    re.IGNORECASE,
)
_CONCENTRATION_INTERPRETATION_PATTERN = re.compile(
    r"\b(?:stark\w*\s+|hoh\w*\s+)?(?:konzentr\w*|cluster\w*|"
    r"bündel\w*|buendel\w*)\b",
    re.IGNORECASE,
)
_CAUSAL_EVIDENCE_LINK_PATTERN = re.compile(
    r"\b(?:da|weil|daher|deshalb|weshalb|somit|folglich|aufgrund|"
    r"angesichts|beleg\w*|zeig\w*|deut\w*|"
    r"spr(?:icht|echen)\s+für|weis\w*\s+[^.!?\n]{0,24}\s+hin)\b",
    re.IGNORECASE,
)
_FEW_DOCUMENT_CONCENTRATION_PATTERN = re.compile(
    r"\b(?:konzentrier\w*|cluster\w*|gebündelt\w*|gebuendelt\w*|"
    r"bündelung\w*|buendelung\w*)\b"
    r"[^.!?\n]{0,90}\bwenig\w*\s+dokument\w*\b|"
    r"\b(?:stark\w*|hoh\w*)\s+konzentration\w*\b"
    r"[^.!?\n]{0,90}\b(?:in|auf)\s+wenig\w*\s+dokument\w*\b|"
    r"\b(?:stark\w*\s+)?(?:in|auf)\s+wenig\w*\s+dokument\w*\b"
    r"[^.!?\n]{0,70}\bkonzentrier\w*\b|"
    r"\bwenig\w*\s+dokument\w*\b"
    r"[^.!?\n]{0,70}\b(?:konzentrier\w*|cluster\w*|gebündelt\w*|"
    r"gebuendelt\w*)\b",
    re.IGNORECASE,
)
_LOCAL_REPEAT_CONCENTRATION_PATTERN = re.compile(
    r"\b(?:dicht\w*\s+(?:passage|stelle|cluster)\w*|"
    r"lokal\w*\s+(?:wiederhol\w*|häuf\w*|haeuf\w*)|"
    r"mehrfach\w*\s+(?:im|innerhalb)\s+(?:selben|gleichen)\s+dokument)\b",
    re.IGNORECASE,
)


def _erste_zahl(muster: str, text: str) -> float | None:
    """Erste Zahl zu ``muster`` in der Evidenzflaeche, sonst None."""

    treffer = re.search(muster, text or "", re.IGNORECASE)
    if not treffer:
        return None
    try:
        return float(treffer.group(1))
    except (TypeError, ValueError):
        return None


def _unsupported_dispersion_interpretations(
    claim_text: str,
    facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact] = (),
) -> List[str]:
    """Reject only directional or document-local readings contradicted by DP."""

    unsupported: List[str] = []
    if _JUILLAND_CONCENTRATION_DIRECTION_PATTERN.search(claim_text or ""):
        unsupported.append("Juilland-D als Konzentrationsmaß")
    if _DP_EVENNESS_DIRECTION_PATTERN.search(claim_text or ""):
        unsupported.append("DP als Gleichmäßigkeitsmaß")

    source_ids = {
        source_id
        for fact in facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    scope_facts = list(facts)
    scope_facts.extend(
        fact
        for fact in observed_facts
        if fact not in scope_facts
        and (
            not source_ids
            or source_ids.intersection(fact.source_evidence_ids)
        )
    )
    source_surface = _joined_surface_text(
        [fact.statement for fact in scope_facts]
        + [
            quote
            for fact in scope_facts
            for quote in fact.grounding_quotes
        ]
    )
    profile_values = {
        value.casefold()
        for value in _source_values_for_field("profile", source_surface)
    }
    strongly_clustered = bool(
        profile_values.intersection(
            {
                "strongly_clustered",
                "strongly-clustered",
                "stark_geclustert",
                "stark-geclustert",
            }
        )
    )
    has_dispersion_evidence = re.search(
        r"\b(?:dp|dpnorm|juilland_d|carroll_d2)\s*=",
        source_surface,
        re.IGNORECASE,
    ) is not None
    if not has_dispersion_evidence:
        return []
    # Compare dispersion with its length-proportional reference when available.
    # Fixed labels can classify the null distribution itself as strongly clustered.
    # For example, an observed DP of 0.88 is below an expected DP of 0.90 even
    # though both exceed a fixed cutoff of 0.8. Without a reference, the label
    # remains the available basis for checking the claim.
    dp_beobachtet = _erste_zahl(r"\bdp\s*=\s*([0-9]*\.?[0-9]+)", source_surface)
    dp_erwartet = _erste_zahl(
        r"\bdp_erwartet\s*=\s*([0-9]*\.?[0-9]+)", source_surface
    )
    unter_der_nullverteilung = (
        dp_beobachtet is not None
        and dp_erwartet is not None
        and dp_beobachtet <= dp_erwartet
    )
    if (
        strongly_clustered
        and not unter_der_nullverteilung
        and _LOW_CONCENTRATION_PATTERN.search(claim_text or "")
    ):
        unsupported.append(
            "geringe Clusterung entgegen dem ausgewiesenen "
            "strongly_clustered-Profil"
        )
    if (
        _UNSOURCED_DISPERSION_THRESHOLD_PATTERN.search(claim_text or "")
        and re.search(
            r"\b(?:threshold|schwellenwert|grenzwert|cut[- ]?off)\s*=",
            source_surface,
            re.IGNORECASE,
        )
        is None
    ):
        unsupported.append("unbelegter typischer Dispersions-Schwellenwert")

    def numeric_value(field: str) -> float | None:
        values = _source_values_for_field(field, source_surface)
        if len(values) != 1:
            return None
        try:
            return float(next(iter(values)))
        except (TypeError, ValueError):
            return None

    range_saturation = numeric_value("range_saturation")
    repeat_hit_share = numeric_value("repeat_hit_share")
    near_maximum_document_range = bool(
        range_saturation is not None
        and range_saturation >= 0.8
    )
    little_within_document_repetition = bool(
        repeat_hit_share is not None
        and repeat_hit_share <= 0.2
    )
    def positive_matches(
        pattern: re.Pattern[str],
    ) -> List[re.Match[str]]:
        matches: List[re.Match[str]] = []
        for match in pattern.finditer(claim_text or ""):
            prefix = str(claim_text or "")[
                max(0, match.start() - 36) : match.start()
            ]
            if re.search(
                r"\b(?:nicht|ohne|kein(?:e|en|er|es)?)\b"
                r"[^.!?\n]{0,28}$",
                prefix,
                re.IGNORECASE,
            ):
                continue
            matches.append(match)
        return matches

    def has_positive_match(pattern: re.Pattern[str]) -> bool:
        return bool(positive_matches(pattern))

    range_used_as_concentration_evidence = False
    if near_maximum_document_range:
        concentration_matches = positive_matches(
            _CONCENTRATION_INTERPRETATION_PATTERN
        )
        for range_match in _MAXIMUM_DOCUMENT_RANGE_PATTERN.finditer(
            claim_text or ""
        ):
            try:
                stated_ratio = int(range_match.group("found")) / int(
                    range_match.group("maximum")
                )
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if stated_ratio < 0.8:
                continue
            for concentration_match in concentration_matches:
                left = min(range_match.end(), concentration_match.end())
                right = max(range_match.start(), concentration_match.start())
                bridge = str(claim_text or "")[left:right]
                if _CAUSAL_EVIDENCE_LINK_PATTERN.search(bridge):
                    range_used_as_concentration_evidence = True
                    break
            if range_used_as_concentration_evidence:
                break

    if (
        near_maximum_document_range
        and little_within_document_repetition
        and (
            has_positive_match(_FEW_DOCUMENT_CONCENTRATION_PATTERN)
            or has_positive_match(_LOCAL_REPEAT_CONCENTRATION_PATTERN)
        )
    ):
        unsupported.append(
            "lokale Dokumenthäufung trotz nahezu maximaler Trefferstreuung"
        )
    if range_used_as_concentration_evidence:
        unsupported.append(
            "nahezu maximale Trefferdokument-Reichweite als "
            "Konzentrationsbeleg"
        )
    return list(dict.fromkeys(unsupported))


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_negative_or_unknown_limitation_3(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6087-6101)."""
    if "_DISPERSION_SEMANTIC_SCOPE_PATTERN" in _vae_ctx:
        _DISPERSION_SEMANTIC_SCOPE_PATTERN = _vae_ctx["_DISPERSION_SEMANTIC_SCOPE_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and any(fact.fact_kind == "distribution" for fact in facts)
        and not any(
            fact.fact_kind == "kwic_example"
            for fact in facts
        )
        and _DISPERSION_SEMANTIC_SCOPE_PATTERN.search(claim.text)
    ):
        claim_reasons.append(
            "Dispersion und Dokumentabdeckung messen die Verteilung "
            "einer Wortform, aber ohne Kontextevidenz weder Thema noch "
            "inhaltliche oder semantische Nische."
        )
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_dispersion_interpretations(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6545-6560)."""
    if "_unsupported_dispersion_interpretations" in _vae_ctx:
        _unsupported_dispersion_interpretations = _vae_ctx["_unsupported_dispersion_interpretations"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if "unsupported_dispersion_interpretations" in _vae_ctx:
        unsupported_dispersion_interpretations = _vae_ctx["unsupported_dispersion_interpretations"]
    unsupported_dispersion_interpretations = (
        _unsupported_dispersion_interpretations(
            analytical_prose,
            facts,
            observed_facts,
        )
    )
    if unsupported_dispersion_interpretations:
        claim_reasons.append(
            "Die Dispersionskennwerte werden methodisch in der falschen "
            "Richtung oder als unbelegte lokale Häufung interpretiert: "
            + ", ".join(
                unsupported_dispersion_interpretations[:3]
            )
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_dispersion_interpretations",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]
