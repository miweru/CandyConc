"""Keyness claim rules: direction, magnitude, label and causal attribution predicates.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence

from ..grounding_schemas import (
    ObservedFact,
)
from ._shared import (
    _EXPLICIT_CONTEXT_METHOD_PATTERN,
    _ROW_LABEL_FIELD_NAMES,
    _joined_surface_text,
    _source_values_for_field,
)
from ._table import PatternRule, run_pattern_rule


_KEYNESS_LABEL_PATTERN = re.compile(
    r"\b(?:schlüssel(?:w[öo]rt|lemm|nom|term|begriff)\w*|"
    r"key(?:word|term)s?)\b",
    re.IGNORECASE,
)
_KEYNESS_SCOPE_REFERENCE_PATTERN = re.compile(
    r"\b(?:von|für|fuer|zu)\s+(?:den\s+)?"
    r"(?:schlüssel(?:w[öo]rt|lemm|nom|term|begriff)\w*|"
    r"key(?:word|term)s?)\b",
    re.IGNORECASE,
)
_KEYNESS_METHOD_TARGET_PATTERN = re.compile(
    r"\b(?:analysier\w*|untersuch\w*|prüf\w*|pruef\w*|betracht\w*)\b"
    r"[^.!?\n]{0,140}\b(?:schlüssel(?:w[öo]rt|lemm|nom|term|begriff)\w*|"
    r"key(?:word|term)s?)\b|"
    r"\b(?:schlüssel(?:w[öo]rt|lemm|nom|term|begriff)\w*|"
    r"key(?:word|term)s?)\b[^.!?\n]{0,140}"
    r"\b(?:analysier\w*|untersuch\w*|prüf\w*|pruef\w*|betracht\w*)\b",
    re.IGNORECASE,
)
_KEYNESS_SAME_ITEMS_PATTERN = re.compile(
    r"\b(?:dieselben|die\s+gleichen|identisch\w*|same)\s+"
    r"(?:tokens?|ausdrücke|ausdruecke|formen?|items?)\b",
    re.IGNORECASE,
)
_KEYNESS_GLOBAL_TOP_PATTERN = re.compile(
    r"\b(?:alle\s+)?top[- ]?\d+[- ]?(?:wörter|woerter|tokens?|"
    r"ausdrücke|ausdruecke|formen)?\b|"
    r"\b(?:die\s+)?(?:obersten|höchsten|hoechsten)\s+\d+\b",
    re.IGNORECASE,
)
_KEYNESS_LEXICAL_CORE_PATTERN = re.compile(
    r"\b(?:lexikalisch\w*\s+kern|wortschatzkern|kernwortschatz|"
    r"vocabulary\s+core)\b",
    re.IGNORECASE,
)
_KEYNESS_DIRECTION_GROUP_PATTERN = re.compile(
    r"\b(?:zeilen|tokens?|ausdrücke|ausdruecke|formen)\b"
    r"[^.!?\n]{0,100}\brichtung\s*['\"„“]?"
    r"(?P<direction>target|reference)['\"„“]?",
    re.IGNORECASE,
)


_ABSOLUTE_KEYNESS_MAGNITUDE_PATTERN = re.compile(
    r"\b(?:stark|sehr\s+stark|extrem|ausgeprägt|ausgepraegt)\w*\s+"
    r"(?:positiv\w*|negativ\w*)\s+keyness(?:[- ]?wert\w*)?\b|"
    r"\b(?:keyness(?:[- ]?wert\w*)?|diff[_ -]?per[_ -]?million|"
    r"ll[_ -]?signed|log[- ]?likelihood|statistikwert\w*)\b"
    r"[^.!?\n]{0,80}\b(?:stark|extrem|ausgeprägt|ausgepraegt)\w*\b|"
    r"\b(?:stark|extrem|ausgeprägt|ausgepraegt)\w*\b"
    r"[^.!?\n]{0,80}\bkeyness(?:[- ]?(?:abweichung|signal)\w*)?\b",
    re.IGNORECASE,
)
_EXPLICIT_KEYNESS_MAGNITUDE_CRITERION_PATTERN = re.compile(
    r"\b(?:schwellenwert|grenzwert|cut[- ]?off|effektkriterium|"
    r"im\s+vergleich|verglichen\s+mit|stärker\s+als|staerker\s+als)\b",
    re.IGNORECASE,
)
_KEYNESS_CAUSAL_ATTRIBUTION_PATTERN = re.compile(
    r"\b(?:zurückzuführen|zurueckzufuehren|verursach\w*|"
    r"(?:technisch\w*\s+)?bedingt\w*|resultier\w*\s+aus|"
    r"aufgrund|wegen)\b",
    re.IGNORECASE,
)
_KEYNESS_CAUSAL_QUALIFIER_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|"
    r"vereinbar\w*|hypothese\w*|denkbar\w*|plausib\w*)\b",
    re.IGNORECASE,
)


def _unsupported_keyness_same_items_claim(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Reject claims that conflate different rows across keyness directions."""

    if _KEYNESS_SAME_ITEMS_PATTERN.search(claim_text or "") is None:
        return False
    labels_by_direction: Dict[str, set[str]] = {
        "target": set(),
        "reference": set(),
    }
    for fact in facts:
        if fact.fact_kind != "ranked_row":
            continue
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        directions = _source_values_for_field("direction", surface)
        labels = {
            value.casefold()
            for field in _ROW_LABEL_FIELD_NAMES
            for value in _source_values_for_field(field, surface)
        }
        if len(directions) != 1 or not labels:
            continue
        direction = next(iter(directions)).casefold()
        if direction in labels_by_direction:
            labels_by_direction[direction].update(labels)
    target = labels_by_direction["target"]
    reference = labels_by_direction["reference"]
    return bool(target and reference and target.isdisjoint(reference))


def _facts_use_balanced_keyness_selection(
    facts: Sequence[ObservedFact],
) -> bool:
    return any(
        "grounding_selection=balanced_by_direction"
        in _joined_surface_text([fact.statement, *fact.grounding_quotes])
        for fact in facts
    )


# --------------------------------------------------------------------------- #
# K3 Slice 3: mechanical rules as PatternRule rows (one generic executor in
# ``_table``). The thin defs below keep name/signature for the facade
# re-exports and the ``_vae_ctx`` seams.
# --------------------------------------------------------------------------- #
_KEYNESS_ROW_FIELD_PATTERN = re.compile(
    r"\b(?:ll_signed|diff_per_million|direction)\s*=",
    re.IGNORECASE,
)
_BALANCED_KEYNESS_SELECTION_PATTERN = re.compile(
    re.escape("grounding_selection=balanced_by_direction"),
)
_KEYNESS_METRIC_EVIDENCE_PATTERN = re.compile(
    r"\b(?:log_ratio|keyness)\s*=|"
    r"\bfreq_target\s*=.*\bfreq_reference\s*=",
    re.IGNORECASE | re.DOTALL,
)

_RULE_BALANCED_KEYNESS_GLOBAL_RANK = PatternRule(
    name="unsupported_balanced_keyness_global_rank_claim",
    scan="search",
    claim_patterns=(_KEYNESS_GLOBAL_TOP_PATTERN,),
    evidence_checks=(
        ("surface_matches", {"pattern": _BALANCED_KEYNESS_SELECTION_PATTERN}),
    ),
    families=("keyness_analysis",),
    reason="Balanced per-direction selection supports no global Top-N rank.",
)

_RULE_KEYNESS_LEXICAL_CORE = PatternRule(
    name="unsupported_keyness_lexical_core_claim",
    scan="search",
    claim_patterns=(_KEYNESS_LEXICAL_CORE_PATTERN,),
    evidence_checks=(
        ("any_fact", {"kind": "ranked_row", "pattern": _KEYNESS_ROW_FIELD_PATTERN}),
    ),
    families=("keyness_analysis",),
    reason="A keyness table ranks differences, not a lexical core.",
)

_RULE_ABSOLUTE_KEYNESS_MAGNITUDE = PatternRule(
    name="unsupported_absolute_keyness_magnitude",
    scan="search",
    claim_patterns=(_ABSOLUTE_KEYNESS_MAGNITUDE_PATTERN,),
    exception_groups=((_EXPLICIT_KEYNESS_MAGNITUDE_CRITERION_PATTERN,),),
    families=("keyness_analysis",),
    reason="Strong/extreme keyness labels need an explicit criterion.",
)

_RULE_KEYNESS_CAUSAL_ATTRIBUTIONS = PatternRule(
    name="unsupported_keyness_causal_attributions",
    scan="sentences_finditer",
    claim_patterns=(_KEYNESS_CAUSAL_ATTRIBUTION_PATTERN,),
    evidence_checks=(
        ("any_fact", {"kind": "ranked_row", "pattern": _KEYNESS_ROW_FIELD_PATTERN}),
    ),
    # The uncertainty marker must scope the causal predicate itself; a later
    # "kann interpretiert werden" does not weaken an already categorical
    # cause assertion in the same sentence.
    per_match_exception="prefix_qualifier",
    per_match_exception_kwargs={
        "pattern": _KEYNESS_CAUSAL_QUALIFIER_PATTERN,
        "window": 120,
    },
    dedupe=True,
    families=("keyness_analysis",),
    reason="A bounded keyness table supports hypotheses, not causes.",
)

_RULE_KEYNESS_LABEL = PatternRule(
    name="unsupported_keyness_label",
    scan="search",
    claim_patterns=(_KEYNESS_LABEL_PATTERN,),
    evidence_checks=(
        ("surface_lacks", {"pattern": _KEYNESS_METRIC_EVIDENCE_PATTERN}),
    ),
    # "Schlüsselbegriff" can name a researcher-selected target of a proposed
    # context analysis without asserting statistical keyness.
    method_advice_exception_groups=(
        (_KEYNESS_SCOPE_REFERENCE_PATTERN, _EXPLICIT_CONTEXT_METHOD_PATTERN),
        (_KEYNESS_METHOD_TARGET_PATTERN, _EXPLICIT_CONTEXT_METHOD_PATTERN),
    ),
    families=("keyness_analysis",),
    reason="Keyword labels need visible keyness metrics as evidence.",
)


def _unsupported_balanced_keyness_global_rank_claim(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(
            _RULE_BALANCED_KEYNESS_GLOBAL_RANK, claim_text, facts=facts
        )
    )


def _unsupported_keyness_lexical_core_claim(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(_RULE_KEYNESS_LEXICAL_CORE, claim_text, facts=facts)
    )


def _unsupported_absolute_keyness_magnitude(claim_text: str) -> bool:
    return bool(run_pattern_rule(_RULE_ABSOLUTE_KEYNESS_MAGNITUDE, claim_text))


def _unsupported_keyness_causal_attributions(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """A bounded keyness table supports hypotheses, not an established cause."""

    return list(
        run_pattern_rule(
            _RULE_KEYNESS_CAUSAL_ATTRIBUTIONS, claim_text, facts=facts
        )
    )


def _unsupported_keyness_label(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    method_advice: bool = False,
) -> bool:
    return bool(
        run_pattern_rule(
            _RULE_KEYNESS_LABEL,
            claim_text,
            facts=facts,
            method_advice=method_advice,
        )
    )


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_unsupported_keyness_label(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6235-6250)."""
    if "_unsupported_keyness_label" in _vae_ctx:
        _unsupported_keyness_label = _vae_ctx["_unsupported_keyness_label"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        not negative_or_unknown_limitation
        and _unsupported_keyness_label(
            claim.text,
            facts,
            method_advice=(
                deliverable_kind == "method_advice"
                and claim.claim_kind == "interpretation"
            ),
        )
    ):
        claim_reasons.append(
            "Häufigkeit allein belegt keine Schlüsselhaftigkeit; dafür "
            "braucht der Claim eine ausgewiesene Keyness- oder "
            "Vergleichsevidenz."
        )


def _vae_rule_unsupported_keyness_same_items_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6367-6375)."""
    if "_unsupported_keyness_same_items_claim" in _vae_ctx:
        _unsupported_keyness_same_items_claim = _vae_ctx["_unsupported_keyness_same_items_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if _unsupported_keyness_same_items_claim(
        analytical_prose,
        observed_facts,
    ):
        claim_reasons.append(
            "Die sichtbaren positiven und negativen Keyness-Richtungen "
            "enthalten unterschiedliche Ausdrücke; sie dürfen nicht als "
            "dieselben Tokens beschrieben werden."
        )


def _vae_rule_unsupported_balanced_keyness_global_rank_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6376-6384)."""
    if "_unsupported_balanced_keyness_global_rank_claim" in _vae_ctx:
        _unsupported_balanced_keyness_global_rank_claim = _vae_ctx["_unsupported_balanced_keyness_global_rank_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if _unsupported_balanced_keyness_global_rank_claim(
        analytical_prose,
        observed_facts,
    ):
        claim_reasons.append(
            "Ein richtungsbalanciert ausgewähltes Keyness-Fenster ist keine "
            "globale Top-N-Rangliste. Nenne die Zeilen je Richtung mit "
            "ihren Messwerten."
        )


def _vae_rule_unsupported_keyness_lexical_core_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6385-6392)."""
    if "_unsupported_keyness_lexical_core_claim" in _vae_ctx:
        _unsupported_keyness_lexical_core_claim = _vae_ctx["_unsupported_keyness_lexical_core_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if _unsupported_keyness_lexical_core_claim(
        analytical_prose,
        observed_facts,
    ):
        claim_reasons.append(
            "Keyness weist distinktive Ausdrücke aus, aber keinen "
            "lexikalischen Kern oder Grundwortschatz."
        )


def _vae_rule_unsupported_absolute_keyness_magnitude(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6393-6397)."""
    if "_unsupported_absolute_keyness_magnitude" in _vae_ctx:
        _unsupported_absolute_keyness_magnitude = _vae_ctx["_unsupported_absolute_keyness_magnitude"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if _unsupported_absolute_keyness_magnitude(analytical_prose):
        claim_reasons.append(
            "Ein starker positiver oder negativer Keyness-Wert braucht "
            "ein explizites Effekt- oder Schwellenkriterium."
        )


def _vae_rule_unsupported_keyness_causes(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6398-6411)."""
    if "_unsupported_keyness_causal_attributions" in _vae_ctx:
        _unsupported_keyness_causal_attributions = _vae_ctx["_unsupported_keyness_causal_attributions"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_keyness_causes" in _vae_ctx:
        unsupported_keyness_causes = _vae_ctx["unsupported_keyness_causes"]
    unsupported_keyness_causes = (
        _unsupported_keyness_causal_attributions(
            analytical_prose,
            facts,
        )
    )
    if unsupported_keyness_causes:
        claim_reasons.append(
            "Gerichtete Keyness-Zeilen belegen einen Unterschied, aber "
            "keine feststehende Ursache; Ursachen bleiben qualifizierte "
            "Prüfhypothesen: "
            + ", ".join(unsupported_keyness_causes[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_keyness_causes",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


# K3 Slice 3: declarative rows of this module (see claim_rules._table).
PATTERN_RULES = (
    _RULE_BALANCED_KEYNESS_GLOBAL_RANK,
    _RULE_KEYNESS_LEXICAL_CORE,
    _RULE_ABSOLUTE_KEYNESS_MAGNITUDE,
    _RULE_KEYNESS_CAUSAL_ATTRIBUTIONS,
    _RULE_KEYNESS_LABEL,
)
