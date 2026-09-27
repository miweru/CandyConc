"""Declarative pattern-rule table for mechanical claim rules (K3 Slice 3).

A ``PatternRule`` captures the standard three-step shape that the majority
of the migrated ``_unsupported_*`` predicates share:

1. **Claim trigger**: one or more compiled regexes that must all match the
   claim text (or, for scanning rules, the pattern whose matches are
   collected).
2. **Evidence counter-check**: named standard checks from the small
   vocabulary in ``EVIDENCE_CHECKS`` below (fact-surface regexes,
   fact-kind gates, field-value lookups). Every listed check must pass for
   the rule to fire.
3. **Exception patterns**: conjunctive groups of claim-level regexes (any
   fully-matching group suppresses the rule), plus named claim-level,
   sentence-level and per-match exception checks for the recurring
   suppression idioms (explicitly bounded claims, proposed-test sentences,
   qualifier prefixes).

``run_pattern_rule`` is the single generic executor. The migrated family
modules keep a thin ``def`` per rule (same name, same signature) so that
facade re-exports, ``_vae_ctx`` seeding and monkeypatch seams are
unchanged. The behaviour of each migrated rule is now data, and NEW
mechanical rules should be added as ``PatternRule`` rows, not as
functions.

Layering: this module is imported by ``_shared`` and by the family
modules, so it must not import ``_shared`` at module level. The helper
functions the check vocabulary delegates to (``_joined_surface_text``,
``_source_values_for_field``, ...) are imported lazily inside the checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence, Tuple


_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class RuleInputs:
    """Everything a rule evaluation may look at."""

    claim_text: str = ""
    facts: Sequence[Any] = ()
    source_surface: str | None = None
    question_text: str = ""
    method_advice: bool = False
    claim_kind: str = "interpretation"


def _standard_surface(inputs: RuleInputs) -> str:
    """Statements-then-quotes surface, the construction the migrated rules use.

    Rules that already receive a prebuilt ``source_surface`` argument keep
    it verbatim, while fact-based rules join all statements followed by all
    grounding quotes, exactly like the original function bodies.
    """

    if inputs.source_surface is not None:
        return inputs.source_surface
    from ._shared import _joined_surface_text

    facts = inputs.facts
    return _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )


def _per_fact_surface(fact: Any) -> str:
    from ._shared import _joined_surface_text

    return _joined_surface_text([fact.statement, *fact.grounding_quotes])


# --------------------------------------------------------------------------- #
# Evidence-check vocabulary (step 2). Each check returns True when the rule
# may fire. Every check listed on a rule must pass.
# --------------------------------------------------------------------------- #
def _check_surface_matches(inputs: RuleInputs, *, pattern: re.Pattern[str]) -> bool:
    return pattern.search(_standard_surface(inputs)) is not None


def _check_surface_lacks(inputs: RuleInputs, *, pattern: re.Pattern[str]) -> bool:
    return pattern.search(_standard_surface(inputs)) is None


def _check_any_fact_kind(inputs: RuleInputs, *, kind: str) -> bool:
    return any(fact.fact_kind == kind for fact in inputs.facts)


def _check_any_fact(
    inputs: RuleInputs, *, kind: str, pattern: re.Pattern[str]
) -> bool:
    """Any fact of ``kind`` whose OWN surface matches ``pattern``."""

    return any(
        fact.fact_kind == kind and pattern.search(_per_fact_surface(fact))
        for fact in inputs.facts
    )


def _check_any_fact_exactness(
    inputs: RuleInputs, *, values: frozenset[str]
) -> bool:
    return any(fact.exactness in values for fact in inputs.facts)


def _check_no_fact_support(
    inputs: RuleInputs,
    *,
    fact_kinds: frozenset[str] = frozenset(),
    supports: frozenset[str] = frozenset(),
    pattern: re.Pattern[str] | None = None,
) -> bool:
    """True when NO fact supplies independent counter-evidence.

    A fact counts as support when its kind is in ``fact_kinds``, when any
    of ``supports`` appears in ``fact.supports_claims``, or when
    ``pattern`` matches its newline-joined statement+quotes surface (the
    exact per-fact construction of the original bodies).
    """

    for fact in inputs.facts:
        if fact.fact_kind in fact_kinds:
            return False
        if any(marker in fact.supports_claims for marker in supports):
            return False
        if pattern is not None and pattern.search(
            "\n".join([fact.statement, *fact.grounding_quotes])
        ):
            return False
    return True


def _check_lacks_counter_evidence(
    inputs: RuleInputs,
    *,
    fact_kinds: frozenset[str] = frozenset(),
    pattern: re.Pattern[str] | None = None,
) -> bool:
    """No fact of the given kinds AND the joined surface lacks ``pattern``."""

    if any(fact.fact_kind in fact_kinds for fact in inputs.facts):
        return False
    if pattern is not None and pattern.search(_standard_surface(inputs)):
        return False
    return True


def _field_values(inputs: RuleInputs, fields: Sequence[str]) -> set[str]:
    from ._shared import _source_values_for_field

    surface = _standard_surface(inputs)
    return {
        value
        for field_name in fields
        for value in _source_values_for_field(field_name, surface)
    }


def _check_field_values_lack(
    inputs: RuleInputs,
    *,
    fields: Tuple[str, ...],
    values: frozenset[str],
    casefold: bool = True,
) -> bool:
    visible = _field_values(inputs, fields)
    if casefold:
        visible = {value.casefold() for value in visible}
    return not visible.intersection(values)


def _check_fields_lack_conjunction(
    inputs: RuleInputs, *, specs: Tuple[Tuple[str, frozenset[str]], ...]
) -> bool:
    """Fires unless EVERY (field, values) spec is confirmed in the surface."""

    return not all(
        _field_values(inputs, (field_name,)).intersection(values)
        for field_name, values in specs
    )


def _check_fields_lack_disjunction(
    inputs: RuleInputs, *, specs: Tuple[Tuple[str, frozenset[str]], ...]
) -> bool:
    """Fires when NONE of the (field, values) specs is confirmed."""

    return not any(
        _field_values(inputs, (field_name,)).intersection(values)
        for field_name, values in specs
    )


def _check_no_row_label_prefixed(inputs: RuleInputs, *, prefix: str) -> bool:
    """Row labels exist, and none of them starts with ``prefix``."""

    from ._shared import _source_row_label_lookup

    labels = _source_row_label_lookup(inputs.facts).values()
    return bool(labels) and not any(label.startswith(prefix) for label in labels)


def _check_question_lacks(inputs: RuleInputs, *, pattern: re.Pattern[str]) -> bool:
    return pattern.search(inputs.question_text or "") is None


EVIDENCE_CHECKS: Dict[str, Callable[..., bool]] = {
    "surface_matches": _check_surface_matches,
    "surface_lacks": _check_surface_lacks,
    "any_fact_kind": _check_any_fact_kind,
    "any_fact": _check_any_fact,
    "any_fact_exactness": _check_any_fact_exactness,
    "no_fact_support": _check_no_fact_support,
    "lacks_counter_evidence": _check_lacks_counter_evidence,
    "field_values_lack": _check_field_values_lack,
    "fields_lack_conjunction": _check_fields_lack_conjunction,
    "fields_lack_disjunction": _check_fields_lack_disjunction,
    "no_row_label_prefixed": _check_no_row_label_prefixed,
    "question_lacks": _check_question_lacks,
}


# --------------------------------------------------------------------------- #
# Exception-check vocabulary (step 3).
# --------------------------------------------------------------------------- #
def _exception_explicitly_bounded(inputs: RuleInputs) -> bool:
    from ._shared import _is_explicitly_bounded_claim

    return _is_explicitly_bounded_claim(inputs.claim_text)


EXCEPTION_CHECKS: Dict[str, Callable[[RuleInputs], bool]] = {
    "explicitly_bounded": _exception_explicitly_bounded,
}


def _sentence_exception_negative_or_unknown_limitation(
    inputs: RuleInputs, sentence: str
) -> bool:
    from ._shared import _is_negative_or_unknown_limitation

    return _is_negative_or_unknown_limitation(
        sentence, claim_kind=inputs.claim_kind
    )


SENTENCE_EXCEPTION_CHECKS: Dict[str, Callable[[RuleInputs, str], bool]] = {
    "negative_or_unknown_limitation": (
        _sentence_exception_negative_or_unknown_limitation
    ),
}


def _per_match_proposed_test(
    text: str, match: re.Match[str], **_kwargs: Any
) -> bool:
    from ._shared import _match_is_part_of_proposed_test

    return _match_is_part_of_proposed_test(text, match)


def _per_match_prefix_qualifier(
    text: str,
    match: re.Match[str],
    *,
    pattern: re.Pattern[str],
    window: int = 120,
) -> bool:
    prefix = text[max(0, match.start() - window) : match.start()]
    return pattern.search(prefix) is not None


PER_MATCH_EXCEPTIONS: Dict[str, Callable[..., bool]] = {
    "proposed_test": _per_match_proposed_test,
    "prefix_qualifier": _per_match_prefix_qualifier,
}


@dataclass(frozen=True)
class PatternRule:
    """One mechanical claim rule as data. See the module docstring."""

    name: str
    scan: str = "search"
    # search          -> bool: all claim_patterns match, checks pass, no exception
    # search_constant -> List[str]: first claim_patterns[0] match (with optional
    #                    per-match exception), checks pass -> constant_result
    # findall         -> List[str]: match.group(0) per claim_patterns[0] match
    # sentences       -> List[str]: sentence_patterns[0].search(sentence).group(0)
    #                    per sentence where ALL sentence_patterns match
    # sentences_finditer -> List[str]: claim_patterns[0] matches inside each
    #                    sentence, filtered by the per-match exception
    claim_patterns: Tuple[re.Pattern[str], ...] = ()
    evidence_checks: Tuple[Tuple[str, Mapping[str, Any]], ...] = ()
    exception_groups: Tuple[Tuple[re.Pattern[str], ...], ...] = ()
    method_advice_exception_groups: Tuple[Tuple[re.Pattern[str], ...], ...] = ()
    exception_checks: Tuple[str, ...] = ()
    per_match_exception: str = ""
    per_match_exception_kwargs: Mapping[str, Any] = field(default_factory=dict)
    sentence_patterns: Tuple[re.Pattern[str], ...] = ()
    sentence_exception_patterns: Tuple[re.Pattern[str], ...] = ()
    sentence_exception_checks: Tuple[str, ...] = ()
    dedupe: bool = False
    constant_result: Tuple[str, ...] = ()
    families: Tuple[str, ...] = ()
    reason: str = ""
    # Severity metadata (Produktentscheid 2026-08): default advisory. Ob eine
    # Regel den Claim BLOCKIERT, entscheidet allein die Registry-Severity in
    # ``claim_rules.__init__`` (abgeleitet aus HARD_RULE_NAMES); dieses Feld
    # spiegelt die Politik auf Zeilenebene und kann nie default-hart sein.
    severity: str = "advisory"


def _evidence_ok(rule: PatternRule, inputs: RuleInputs) -> bool:
    return all(
        EVIDENCE_CHECKS[check_name](inputs, **check_kwargs)
        for check_name, check_kwargs in rule.evidence_checks
    )


def _exception_hit(rule: PatternRule, inputs: RuleInputs) -> bool:
    text = inputs.claim_text
    groups: Tuple[Tuple[re.Pattern[str], ...], ...] = rule.exception_groups
    if inputs.method_advice:
        groups = groups + rule.method_advice_exception_groups
    if any(
        all(pattern.search(text) for pattern in group) for group in groups
    ):
        return True
    return any(
        EXCEPTION_CHECKS[check_name](inputs)
        for check_name in rule.exception_checks
    )


def _per_match_hit(
    rule: PatternRule, text: str, match: re.Match[str]
) -> bool:
    if not rule.per_match_exception:
        return False
    return PER_MATCH_EXCEPTIONS[rule.per_match_exception](
        text, match, **rule.per_match_exception_kwargs
    )


def _sentence_hits(rule: PatternRule, inputs: RuleInputs) -> List[str]:
    out: List[str] = []
    for sentence in _SENTENCE_SPLIT_PATTERN.split(inputs.claim_text or ""):
        first = rule.sentence_patterns[0].search(sentence)
        if first is None:
            continue
        if any(
            pattern.search(sentence) is None
            for pattern in rule.sentence_patterns[1:]
        ):
            continue
        if any(
            pattern.search(sentence)
            for pattern in rule.sentence_exception_patterns
        ):
            continue
        if any(
            SENTENCE_EXCEPTION_CHECKS[check_name](inputs, sentence)
            for check_name in rule.sentence_exception_checks
        ):
            continue
        out.append(first.group(0))
    return out


def _sentence_finditer_hits(rule: PatternRule, inputs: RuleInputs) -> List[str]:
    out: List[str] = []
    for sentence in _SENTENCE_SPLIT_PATTERN.split(inputs.claim_text or ""):
        for match in rule.claim_patterns[0].finditer(sentence):
            if _per_match_hit(rule, sentence, match):
                continue
            out.append(match.group(0))
    return out


def run_pattern_rule(
    rule: PatternRule,
    claim_text: str,
    *,
    facts: Sequence[Any] = (),
    source_surface: str | None = None,
    question_text: str = "",
    method_advice: bool = False,
    claim_kind: str = "interpretation",
) -> bool | List[str]:
    """The ONE generic executor for every ``PatternRule`` row."""

    inputs = RuleInputs(
        claim_text=claim_text or "",
        facts=facts,
        source_surface=source_surface,
        question_text=question_text,
        method_advice=method_advice,
        claim_kind=claim_kind,
    )
    text = inputs.claim_text
    if rule.scan == "search":
        if not all(pattern.search(text) for pattern in rule.claim_patterns):
            return False
        if not _evidence_ok(rule, inputs):
            return False
        return not _exception_hit(rule, inputs)
    if rule.scan == "search_constant":
        match = rule.claim_patterns[0].search(text)
        if match is None:
            return []
        if _per_match_hit(rule, text, match):
            return []
        if not _evidence_ok(rule, inputs) or _exception_hit(rule, inputs):
            return []
        return list(rule.constant_result)
    if not _evidence_ok(rule, inputs) or _exception_hit(rule, inputs):
        return []
    if rule.scan == "findall":
        hits = [
            match.group(0)
            for match in rule.claim_patterns[0].finditer(text)
            if not _per_match_hit(rule, text, match)
        ]
    elif rule.scan == "sentences":
        hits = _sentence_hits(rule, inputs)
    elif rule.scan == "sentences_finditer":
        hits = _sentence_finditer_hits(rule, inputs)
    else:  # pragma: no cover - defensive: unknown scan mode is a coding error
        raise ValueError(f"unknown PatternRule scan mode: {rule.scan!r}")
    if rule.dedupe:
        return list(dict.fromkeys(hits))
    return hits
