"""Frequency claim rules: relative/absolute magnitude, trend and theme-inference predicates.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence

from ..grounding_schemas import (
    ObservedFact,
)
from ._shared import (
    _ANALYSIS_OPERATION_PATTERN,
    _CONTEXTUAL_MEANING_PATTERN,
    _EXPLICIT_CONTEXT_METHOD_PATTERN,
    _METHODOLOGICAL_TEST_INTENT_PATTERN,
    _METHOD_PROPOSAL_MODALITY_PATTERN,
    _SEMANTIC_CLASS_ASSIGNMENT_PATTERN,
    _TENTATIVE_THEME_PATTERN,
    _THEME_INFERENCE_PATTERN,
    _THEME_VALIDATION_PATTERN,
    _followup_changes_analysis_scope,
    _joined_surface_text,
    _row_count_for_label,
    _source_row_label_lookup,
)
from ._table import PatternRule, run_pattern_rule


_FOLLOWUP_SETTLED_FREQUENCY_NORMALIZATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:absolute[nr]?\s+)?frequenz\w*\b[^?\n]{0,140}"
    r"\b(?:im\s+verh[aä]ltnis|bezogen|normalisier\w*)\b[^?\n]{0,120}"
    r"\b(?:gesamtkorpus|korpusgr(?:ö|oe)ße|tokenzahl|tokens?|pro\s+million)\b"
    r"|"
    r"\b(?:relative\s+frequenz|per[_ -]?million|pro\s+million)\b"
    r"[^?\n]{0,100}\b(?:berechn|ermittel|normalisier)\w*"
    r")",
    re.IGNORECASE,
)


_ASSERTED_FREQUENCY_THEME_PREMISE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:top[- ]?(?:wörter|woerter|nomen|lemmata|lexeme)|"
    r"frequenz(?:liste|spitze|zeilen)?)\b"
    r"[^.!?\n]{0,180}\b(?:thema\w*|kernthem\w*|thematisch\w*|diskursfeld\w*|"
    r"spannungsfeld\w*)\b"
    r"[^.!?\n]{0,100}\b(?:abbild\w*|zeig\w*|beleg\w*|"
    r"repräsentier\w*|repraesentier\w*)\b"
    r"|"
    r"\b(?:top[- ]?(?:wörter|woerter|nomen|lemmata|lexeme)|"
    r"frequenz(?:liste|spitze|zeilen)?)\b"
    r"[^.!?\n]{0,100}\b(?:abbild\w*|zeig\w*|beleg\w*|"
    r"repräsentier\w*|repraesentier\w*)\b"
    r"[^.!?\n]{0,180}\b(?:thema\w*|kernthem\w*|thematisch\w*|diskursfeld\w*|"
    r"spannungsfeld\w*)\b"
    r")",
    re.IGNORECASE,
)


_FREQUENCY_COPRESENCE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:gleichzeitig\w*|gemeinsam\w*)\s+auftret\w*\b|"
    r"\b(?:gleichzeitig\w*|gemeinsam\w*)\s+vorkomm\w*\b|"
    r"\b(?:gleichzeitig\w*|gemeinsam\w*)\s+(?:auftreten|vorkommen)\b|"
    r"\b(?:treten|kommen)\b[^.!?\n]{0,80}\b(?:gemeinsam|zusammen)\b|"
    r"\b(?:ko[- ]?okkur\w*|kookkur\w*|co-?occurr\w*)\b"
    r")",
    re.IGNORECASE,
)
_EXPLICIT_LIST_COPRESENCE_PATTERN = re.compile(
    r"\b(?:gemeinsame?\s+präsenz|gemeinsam\s+vertreten|"
    r"in\s+derselben|in\s+der|unter\s+den\s+sichtbaren)\b"
    r"[^.!?\n]{0,100}\b(?:frequenz|top[- ]?n|rang)?liste\b",
    re.IGNORECASE,
)


_ABSOLUTE_FREQUENCY_MAGNITUDE_PATTERN = re.compile(
    r"\b(?:(?:sehr|besonders|auffällig|auffaellig|außergewöhnlich|"
    r"aussergewöhnlich|extrem)\s+)?"
    r"(?:hoh(?:e|en|er|es)|niedrig(?:e|en|er|es))\s+"
    r"(?:frequenz|häufigkeit|haeufigkeit|rate|dichte)\w*\b|"
    r"\b(?:sehr|besonders|auffällig|auffaellig|außergewöhnlich|"
    r"aussergewöhnlich|extrem)\s+(?:häufig|haeufig|selten)\b",
    re.IGNORECASE,
)


_EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN = re.compile(
    r"\b(?:im\s+vergleich|verglichen\s+mit|gegenüber|gegenueber|"
    r"höher\s+als|hoeher\s+als|niedriger\s+als|"
    r"häufiger\s+als|haeufiger\s+als|seltener\s+als|"
    r"unter\s+den\s+sichtbaren|rang\w*|top[- ]?(?:n|\d+))\b",
    re.IGNORECASE,
)


_RAW_FREQUENCY_LENGTH_RELATION_PATTERN = re.compile(
    r"(?=[^?!\n]{0,500}\b(?:frequenz\w*|häufigkeit\w*|"
    r"haeufigkeit\w*|f\s*=\s*\d+)\b)"
    r"(?=[^?!\n]{0,500}\bsatzläng\w*\b)"
    r"(?=[^?!\n]{0,500}(?:\b(?:zusammenhang\w*|korrel\w*)\b|"
    r"\bhäng\w*[^?!\n]{0,120}\bzusammen\b))"
    r"[^?!\n]+",
    re.IGNORECASE,
)
_LENGTH_NORMALISATION_PATTERN = re.compile(
    r"\b(?:dichte\w*|rate\w*|anteil\w*|pro\s+(?:token|wort|satz)|"
    r"normalisier\w*|exposure|offset)\b",
    re.IGNORECASE,
)


_FREQUENCY_METHOD_PATTERN = re.compile(
    r"\b(?:frequenz(?:analyse|auswertung|liste)?|häufigkeits?(?:analyse|liste)?)\w*\b",
    re.IGNORECASE,
)


_MORPHOLOGICAL_CATEGORY_PATTERN = re.compile(
    r"\b(?:singular|plural|numerus|kasus|genus|flexion\w*|"
    r"morpholog\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_MORPHOLOGY_METHOD_PATTERN = re.compile(
    r"\b(?:morph(?:olog\w*)?[- ]?(?:annotation|merkmal|tag|analyse)\w*|"
    r"kontextkodier\w*|annotationsstichprobe\w*)\b",
    re.IGNORECASE,
)


_FREQUENCY_DIRECTION_PATTERN = re.compile(
    r"\b(?P<left>[A-ZÄÖÜ][\wÄÖÜäöüß-]{1,80})\s+"
    r"(?:ist|erscheint|kommt)\s+"
    r"(?P<direction>häufiger|haeufiger|seltener)\s+als\s+"
    r"(?P<right>[A-ZÄÖÜ][\wÄÖÜäöüß-]{1,80})\b",
    re.IGNORECASE,
)


def _unsupported_frequency_directions(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    labels = _source_row_label_lookup(facts)
    unsupported: List[str] = []
    for match in _FREQUENCY_DIRECTION_PATTERN.finditer(claim_text or ""):
        left_label = labels.get(match.group("left").casefold())
        right_label = labels.get(match.group("right").casefold())
        left = _row_count_for_label(left_label, facts) if left_label else None
        right = (
            _row_count_for_label(right_label, facts)
            if right_label
            else None
        )
        direction = match.group("direction").casefold()
        supported = (
            left is not None
            and right is not None
            and (
                left > right
                if direction in {"häufiger", "haeufiger"}
                else left < right
            )
        )
        if not supported:
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _unsupported_frequency_theme_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    method_advice: bool = False,
) -> bool:
    has_theme_inference = (
        _THEME_INFERENCE_PATTERN.search(claim_text or "") is not None
    )
    has_semantic_class_assignment = (
        _SEMANTIC_CLASS_ASSIGNMENT_PATTERN.search(claim_text or "")
        is not None
    )
    if not (has_theme_inference or has_semantic_class_assignment):
        return False
    if method_advice and any(
        (
            _THEME_INFERENCE_PATTERN.search(clause)
            or _SEMANTIC_CLASS_ASSIGNMENT_PATTERN.search(clause)
        )
        and _METHOD_PROPOSAL_MODALITY_PATTERN.search(clause)
        and _ANALYSIS_OPERATION_PATTERN.search(clause)
        and _ASSERTED_FREQUENCY_THEME_PREMISE_PATTERN.search(clause)
        is None
        for clause in re.split(r"[.!?\n]+", claim_text or "")
    ):
        # In a method step the theme can be the explicitly future target of
        # an analysis. That proposes a test; it does not report its outcome.
        return False
    if (
        "?" in (claim_text or "")
        and _EXPLICIT_CONTEXT_METHOD_PATTERN.search(claim_text or "")
    ):
        # An open question may use frequency rows to choose candidates and
        # propose a context analysis; it does not claim that a theme exists.
        return False
    if (
        _METHODOLOGICAL_TEST_INTENT_PATTERN.search(claim_text or "")
        and _THEME_VALIDATION_PATTERN.search(claim_text or "")
    ):
        # A declarative follow-up can likewise formulate a future test without
        # asserting that the proposed theme is already present.
        return False
    surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    has_lexical_frequency = re.search(
        r"\bgroup_by\s*=\s*(?:word|lemma)\b",
        surface,
        re.IGNORECASE,
    ) is not None or any(
        fact.fact_kind == "count"
        and any(
            "query_count" in source_id.casefold()
            for source_id in fact.source_evidence_ids
        )
        for fact in facts
    )
    if not has_lexical_frequency:
        return False
    if _ASSERTED_FREQUENCY_THEME_PREMISE_PATTERN.search(
        claim_text or ""
    ):
        return True
    has_contextual_support = any(
        fact.fact_kind == "kwic_example"
        or "comparisons" in fact.supports_claims
        or re.search(
            r"\b(?:semantisch\w*\s+(?:treffer|cluster)|kollokat\w*|"
            r"keyness|log_ratio|dispersion)\b",
            "\n".join([fact.statement, *fact.grounding_quotes]),
            re.IGNORECASE,
        )
        is not None
        for fact in facts
    )
    if has_contextual_support:
        return False
    return not (
        _TENTATIVE_THEME_PATTERN.search(claim_text or "")
        and _THEME_VALIDATION_PATTERN.search(claim_text or "")
    )


# --------------------------------------------------------------------------- #
# H9/V3: pmw-Arithmetik-Wahrheit. Ein Claim, der fuer DIESELBE Entitaet eine
# absolute Frequenz f UND einen pmw-Wert nennt, muss arithmetisch konsistent
# sein: pmw == f / token_count * 1e6 (Toleranz 0.5% plus Rundungsschlupf).
# Klasse (d) der Severity-Politik: exakter Evidenz-Widerspruch, deterministisch
# nachrechenbar. Konservativ: gefeuert wird NUR, wenn f, pmw und token_count
# eindeutig bestimmbar sind (ein einziger Tokennenner in der Evidenz; die
# Label-Zahl-Zahl-Form zusaetzlich nur mit Evidenzzeilen-Bestaetigung von f).
# --------------------------------------------------------------------------- #
_PMW_UNIT = (
    r"(?:pmw|pro\s+Million(?:\s+(?:Korpus)?(?:Tokens?|W(?:ö|oe)rter[n]?))?|"
    r"per[\s_-]?million)"
)

# Ohne Einheit im Text kann keines der drei Muster treffen.
#
# ABGELEITET, NICHT ABGESCHRIEBEN. Alle drei enden auf ``_PMW_UNIT``, also
# ist ein Text ohne diese Einheit fuer alle drei leer. Die Wache benutzt
# DIESELBE Konstante, damit sie nicht auseinanderlaufen kann. Eine von Hand
# gepflegte Wortliste waere genau die blinde Wache, die dieses Projekt
# wiederholt gebaut hat.
#
# WARUM UEBERHAUPT. Ohne sie laeuft Muster 1 auf jedem "797 Treffer" an und
# durchsucht bis zu 80 Zeichen nach einer pmw-Zahl, die es nicht gibt. Auf
# einem Text mit 2.000 Woertern und 90 Treffernennungen waren das gemessen
# 0,8 ms je Aufruf, 17 Prozent der ganzen Referenzaufloesung, fuer ein
# garantiert leeres Ergebnis.
_PMW_EINHEIT_IRGENDWO = re.compile(_PMW_UNIT, re.IGNORECASE)

# Form 1 (eindeutig): "<f> Treffer ... <pmw> pmw" — f traegt eine eigene
# Zaehleinheit, die Bindung ist explizit.
_PMW_PAIR_WITH_COUNT_UNIT_PATTERN = re.compile(
    rf"(?P<f>\d{{1,7}})\s*"
    rf"(?:Treffer|Beleg(?:e|en)?|Vorkommen|Fundstellen|Mal|mal|Tokens?)\b"
    rf"[^.;:!?\n]{{0,80}}?"
    rf"(?P<pmw>\d{{1,7}}(?:[.,]\d{{1,3}})?)\s*{_PMW_UNIT}",
    re.IGNORECASE,
)

# Form 2 (technisch, eindeutig): "f=<f> ... per_million=<pmw>".
_PMW_PAIR_TECHNICAL_PATTERN = re.compile(
    r"\bf\s*=\s*(?P<f>\d{1,7})\b"
    r"[^.;:!?\n]{0,80}?"
    r"\bper_million\s*=\s*(?P<pmw>\d{1,7}(?:[.,]\d{1,3})?)",
    re.IGNORECASE,
)

# Form 3 (Label-Zahl-Zahl, V3-Rohfall "Flüchtlinge 30 498.3 pmw"): wegen der
# moeglichen Tausender-Lesart ("30 498.3" als EINE Zahl) nur mit Bestaetigung
# der f-Lesart durch eine sichtbare Evidenzzeile (Label -> f) auswertbar.
_PMW_PAIR_LABELLED_PATTERN = re.compile(
    rf"(?P<label>[A-Za-zÄÖÜäöüß@#][\wÄÖÜäöüß@#’'-]*)\s+"
    rf"(?P<f>\d{{1,6}})\s+"
    rf"(?P<pmw>\d{{1,7}}[.,]\d{{1,3}})\s*{_PMW_UNIT}",
)

_TOKEN_DENOMINATOR_FIELD_PATTERN = re.compile(
    r"\b(?:denominator_tokens|corpus_tokens|token_count|n_tokens)\s*=\s*"
    r"(\d(?:[\d.\s  ]{0,14}\d)?)",
    re.IGNORECASE,
)


def _pmw_candidate_values(raw: str) -> List[float]:
    """Alle plausiblen Lesarten eines pmw-Zahltokens (Dezimal vs. Gruppierung).

    Konservativ: der Claim gilt nur dann als widerspruechlich, wenn KEINE
    Lesart zur Arithmetik passt.
    """

    token = str(raw or "").strip()
    if not token:
        return []
    values: List[float] = []

    def _add(text: str) -> None:
        try:
            value = float(text)
        except ValueError:
            return
        if value > 0 and value not in values:
            values.append(value)

    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            _add(token.replace(".", "").replace(",", "."))
        else:
            _add(token.replace(",", ""))
    elif "," in token:
        head, _, tail = token.rpartition(",")
        _add(f"{head}.{tail}")
        if len(tail) == 3:
            _add(token.replace(",", ""))
    elif "." in token:
        _add(token)
        head, _, tail = token.rpartition(".")
        if len(tail) == 3:
            _add(token.replace(".", ""))
    else:
        _add(token)
    return values


def _unique_token_denominator(surfaces: Sequence[str]) -> int | None:
    """Der EINE Tokennenner aus der Evidenz, sonst None (nicht eindeutig)."""

    values: set[int] = set()
    for surface in surfaces:
        for match in _TOKEN_DENOMINATOR_FIELD_PATTERN.finditer(surface or ""):
            digits = re.sub(r"[.\s  ]", "", match.group(1))
            if digits.isdigit():
                values.add(int(digits))
    if len(values) != 1:
        return None
    value = values.pop()
    return value if value > 0 else None


def _pmw_pair_is_consistent(
    f_value: int,
    pmw_candidates: Sequence[float],
    token_count: int,
) -> bool:
    if f_value <= 0 or token_count <= 0 or f_value > token_count:
        # Ausserhalb des sinnvollen Bereichs: keine Aussage, nie feuern.
        return True
    if not pmw_candidates:
        return True
    expected = f_value * 1_000_000.0 / token_count
    for candidate in pmw_candidates:
        is_integer_claim = float(candidate).is_integer()
        tolerance = max(
            expected * 0.005,
            0.51 if is_integer_claim else 0.055,
        )
        if abs(candidate - expected) <= tolerance:
            return True
    return False


def _pmw_pair_findings(
    text: str,
    token_count: int | None,
    row_counts: Mapping[str, int] | None = None,
) -> List[Dict[str, Any]]:
    """Deterministische pmw-Widersprueche in ``text`` (reine Textanalyse).

    ``row_counts`` (casefold-Label -> f aus sichtbaren Evidenzzeilen) schaltet
    die Label-Zahl-Zahl-Form frei; ohne Bestaetigung bleibt diese Form stumm.
    """

    if token_count is None or token_count <= 0:
        return []
    body = str(text or "")
    if not _PMW_EINHEIT_IRGENDWO.search(body):
        return []
    findings: List[Dict[str, Any]] = []
    seen_spans: List[tuple[int, int]] = []

    def _record(match: re.Match[str], f_value: int) -> None:
        span = match.span()
        if any(a <= span[0] and span[1] <= b for a, b in seen_spans):
            return
        candidates = _pmw_candidate_values(match.group("pmw"))
        if _pmw_pair_is_consistent(f_value, candidates, token_count):
            seen_spans.append(span)
            return
        expected = f_value * 1_000_000.0 / token_count
        findings.append(
            {
                "fragment": " ".join(match.group(0).split()),
                "f": f_value,
                "pmw": match.group("pmw"),
                "expected_pmw": round(expected, 1),
                "token_count": token_count,
            }
        )
        seen_spans.append(span)

    for pattern in (
        _PMW_PAIR_WITH_COUNT_UNIT_PATTERN,
        _PMW_PAIR_TECHNICAL_PATTERN,
    ):
        for match in pattern.finditer(body):
            try:
                f_value = int(match.group("f"))
            except (TypeError, ValueError):
                continue
            _record(match, f_value)

    if row_counts:
        for match in _PMW_PAIR_LABELLED_PATTERN.finditer(body):
            try:
                f_value = int(match.group("f"))
            except (TypeError, ValueError):
                continue
            label_key = str(match.group("label") or "").casefold()
            confirmed = row_counts.get(label_key)
            if confirmed is None or int(confirmed) != f_value:
                # f-Lesart nicht durch eine Evidenzzeile bestaetigt ->
                # nicht eindeutig bestimmbar -> stumm.
                continue
            _record(match, f_value)
    return findings


def _row_counts_from_facts(
    facts: Sequence[ObservedFact],
) -> Dict[str, int]:
    """Casefold-Label -> Zeilen-f aus den sichtbaren Evidenzzeilen der Fakten."""

    labels = _source_row_label_lookup(facts)
    row_counts: Dict[str, int] = {}
    for key, label in labels.items():
        count = _row_count_for_label(label, facts)
        if count is None:
            continue
        try:
            row_counts[key] = int(count)
        except (TypeError, ValueError):
            continue
    return row_counts


def _pmw_inconsistent_with_count(
    claim_text: str,
    facts: Sequence[ObservedFact],
    all_facts: Sequence[ObservedFact] | None = None,
) -> List[str]:
    """Fragmente, deren f/pmw-Paar dem eindeutigen Tokennenner widerspricht."""

    fact_pool: List[ObservedFact] = list(facts or ())
    for fact in all_facts or ():
        if fact not in fact_pool:
            fact_pool.append(fact)
    surfaces = [
        line
        for fact in fact_pool
        for line in [fact.statement, *fact.grounding_quotes]
        if str(line or "").strip()
    ]
    token_count = _unique_token_denominator(surfaces)
    if token_count is None:
        return []
    row_counts = _row_counts_from_facts(fact_pool)
    findings = _pmw_pair_findings(
        claim_text,
        token_count,
        row_counts=row_counts,
    )
    return [finding["fragment"] for finding in findings]


# --------------------------------------------------------------------------- #
# K3 Slice 3: mechanical rules as PatternRule rows (one generic executor in
# ``_table``). The thin defs below keep name/signature for the facade
# re-exports and the ``_vae_ctx`` seams.
# --------------------------------------------------------------------------- #
_LEXICAL_GROUP_BY_PATTERN = re.compile(
    r"\bgroup_by\s*=\s*(?:word|lemma)\b",
    re.IGNORECASE,
)
_RELATIONAL_EVIDENCE_FACT_PATTERN = re.compile(
    r"\b(?:kollokat\w*|co-?occurr\w*|kookkurr\w*|"
    r"doc(?:ument)?_coverage|document_count|dispersion)\b",
    re.IGNORECASE,
)

_RULE_ABSOLUTE_FREQUENCY_MAGNITUDE = PatternRule(
    name="unsupported_absolute_frequency_magnitude",
    scan="search",
    claim_patterns=(_ABSOLUTE_FREQUENCY_MAGNITUDE_PATTERN,),
    exception_groups=((_EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN,),),
    families=("frequency_analysis",),
    reason="High/low frequency labels need an explicit comparison anchor.",
)

_RULE_FREQUENCY_COPRESENCE_INFERENCE = PatternRule(
    name="unsupported_frequency_copresence_inference",
    scan="search",
    claim_patterns=(_FREQUENCY_COPRESENCE_PATTERN,),
    exception_groups=((_EXPLICIT_LIST_COPRESENCE_PATTERN,),),
    evidence_checks=(
        ("surface_matches", {"pattern": _LEXICAL_GROUP_BY_PATTERN}),
        (
            "no_fact_support",
            {
                "fact_kinds": frozenset({"kwic_example"}),
                "supports": frozenset({"comparisons"}),
                "pattern": _RELATIONAL_EVIDENCE_FACT_PATTERN,
            },
        ),
    ),
    families=("frequency_analysis",),
    reason="A frequency list shows no co-presence without relational evidence.",
)


def _unsupported_absolute_frequency_magnitude(claim_text: str) -> bool:
    """Reject unevaluated high/low labels while preserving explicit comparisons."""

    return bool(
        run_pattern_rule(_RULE_ABSOLUTE_FREQUENCY_MAGNITUDE, claim_text)
    )


def _unsupported_frequency_copresence_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(
            _RULE_FREQUENCY_COPRESENCE_INFERENCE, claim_text, facts=facts
        )
    )


def _followup_confounds_raw_frequency_with_length(
    claim_text: str,
) -> bool:
    return bool(
        _RAW_FREQUENCY_LENGTH_RELATION_PATTERN.search(claim_text or "")
        and _LENGTH_NORMALISATION_PATTERN.search(claim_text or "") is None
    )


def _frequency_substitutes_for_contextual_meaning(claim_text: str) -> bool:
    return bool(
        _FREQUENCY_METHOD_PATTERN.search(claim_text or "")
        and _CONTEXTUAL_MEANING_PATTERN.search(claim_text or "")
        and not _EXPLICIT_CONTEXT_METHOD_PATTERN.search(claim_text or "")
    )


def _followup_infers_morphology_from_surface_frequency(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if (
        _MORPHOLOGICAL_CATEGORY_PATTERN.search(claim_text or "") is None
        or _EXPLICIT_MORPHOLOGY_METHOD_PATTERN.search(claim_text or "")
    ):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    has_surface_only_evidence = re.search(
        r"\bgroup_by\s*=\s*word\b",
        source_surface,
        re.IGNORECASE,
    ) or any(
        str(getattr(fact, "fact_kind", "") or "").casefold()
        in {"kwic_example", "ranked_row"}
        for fact in facts
    )
    category_patterns = []
    lowered_claim = str(claim_text or "").casefold()
    if re.search(r"\b(?:singular|plural|numerus)\b", lowered_claim):
        category_patterns.append(r"(?:number|numerus)\s*=")
    if re.search(r"\b(?:kasus|case)\b", lowered_claim):
        category_patterns.append(r"(?:case|kasus)\s*=")
    if re.search(r"\b(?:genus|gender)\b", lowered_claim):
        category_patterns.append(r"(?:gender|genus)\s*=")
    if re.search(r"\b(?:flexion\w*|morpholog\w*)\b", lowered_claim):
        category_patterns.append(r"morph\s*=")
    has_category_evidence = bool(category_patterns) and any(
        re.search(pattern, source_surface, re.IGNORECASE)
        for pattern in category_patterns
    )
    return bool(has_surface_only_evidence and not has_category_evidence)


def _followup_reasks_settled_frequency_normalization(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _followup_changes_analysis_scope(claim_text):
        return False
    if not _FOLLOWUP_SETTLED_FREQUENCY_NORMALIZATION_PATTERN.search(
        claim_text or ""
    ):
        return False
    surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return (
        "per_million=" in surface
        and "denominator_tokens=" in surface
        and re.search(
            r"denominator_scope=(?:corpus|docset)",
            surface,
            re.IGNORECASE,
        )
        is not None
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
def _vae_rule_unsupported_absolute_frequency_magnitude(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5971-5979)."""
    if "_unsupported_absolute_frequency_magnitude" in _vae_ctx:
        _unsupported_absolute_frequency_magnitude = _vae_ctx["_unsupported_absolute_frequency_magnitude"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_absolute_frequency_magnitude(claim.text)
    ):
        claim_reasons.append(
            "Eine absolute Häufigkeit ist ohne sichtbaren Rang oder "
            "explizite Vergleichsbasis weder hoch noch niedrig."
        )


def _vae_rule_unsupported_frequency_theme_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6102-6122)."""
    if "_unsupported_frequency_theme_inference" in _vae_ctx:
        _unsupported_frequency_theme_inference = _vae_ctx["_unsupported_frequency_theme_inference"]
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
        claim.claim_kind in {
            "observation",
            "interpretation",
            "followup",
        }
        and not negative_or_unknown_limitation
        and _unsupported_frequency_theme_inference(
            claim.text,
            facts,
            method_advice=(
                deliverable_kind == "method_advice"
                and claim.claim_kind == "interpretation"
            ),
        )
    ):
        claim_reasons.append(
            "Lexikalische Einzel-, Wort- oder Lemmafrequenzen markieren mögliche "
            "Untersuchungskandidaten, belegen aber ohne Kontext-, "
            "Dispersions- oder Vergleichsschritt noch kein Thema."
        )


def _vae_rule_unsupported_frequency_copresence_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6123-6135)."""
    if "_unsupported_frequency_copresence_inference" in _vae_ctx:
        _unsupported_frequency_copresence_inference = _vae_ctx["_unsupported_frequency_copresence_inference"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_frequency_copresence_inference(
            claim.text,
            facts,
        )
    ):
        claim_reasons.append(
            "Die gemeinsame Präsenz mehrerer Formen in einer "
            "Frequenzliste belegt kein gemeinsames Auftreten in "
            "Dokumenten, Sätzen oder lokalen Kontexten."
        )


def _vae_rule_followup_infers_morphology_from_surface_frequency(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6170-6182)."""
    if "_followup_infers_morphology_from_surface_frequency" in _vae_ctx:
        _followup_infers_morphology_from_surface_frequency = _vae_ctx["_followup_infers_morphology_from_surface_frequency"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _followup_infers_morphology_from_surface_frequency(
            claim.text,
            facts,
        )
    ):
        claim_reasons.append(
            "Wortformfrequenzen wählen Kandidaten aus, belegen aber "
            "ohne Morphologie- oder Kontextanalyse noch keine Singular-, "
            "Plural- oder andere Flexionskategorie."
        )


def _vae_rule_unsupported_frequency_directions(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6703-6715)."""
    if "_unsupported_frequency_directions" in _vae_ctx:
        _unsupported_frequency_directions = _vae_ctx["_unsupported_frequency_directions"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_frequency_directions" in _vae_ctx:
        unsupported_frequency_directions = _vae_ctx["unsupported_frequency_directions"]
    unsupported_frequency_directions = (
        _unsupported_frequency_directions(
            analytical_prose,
            facts,
        )
    )
    if unsupported_frequency_directions:
        claim_reasons.append(
            "Die natürlich formulierte Häufigkeitsrichtung stimmt "
            "nicht mit den Zeilen-Counts überein: "
            + ", ".join(unsupported_frequency_directions[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_frequency_directions",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_followup_confounds_raw_frequency_with_length(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7198-7208)."""
    if "_followup_confounds_raw_frequency_with_length" in _vae_ctx:
        _followup_confounds_raw_frequency_with_length = _vae_ctx["_followup_confounds_raw_frequency_with_length"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and _followup_confounds_raw_frequency_with_length(claim.text)
    ):
        claim_reasons.append(
            "Eine rohe Häufigkeit ist mit Satzlänge bereits durch die "
            "Zahl möglicher Tokenpositionen gekoppelt. Verwende für die "
            "Beziehungsfrage eine Rate, Dichte, Exposition oder einen "
            "Offset auf derselben Beobachtungseinheit."
        )


def _vae_rule_pmw_inconsistent_with_count(_vae_ctx):
    """H9/V3: exakter pmw-Arithmetik-Widerspruch (Severity-Klasse d, hart).

    Feuert NUR bei eindeutig bestimmbarem (f, pmw, token_count)-Tripel; die
    Bestimmung ist vollstaendig deterministisch (Regex + Arithmetik).
    """
    # Ctx-Seeding gewinnt (Facade-Monkeypatch-Naht), sonst die Modulfunktion.
    # Bewusst ein EIGENER Lokalname: das Prolog-Muster der aelteren Regeln
    # setzt voraus, dass grounding_validation den Helfer in seine Globals
    # importiert; dieser Fallback braucht diese Kopplung nicht.
    _pmw_checker = (
        _vae_ctx.get("_pmw_inconsistent_with_count")
        or _pmw_inconsistent_with_count
    )
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    observed_facts = _vae_ctx.get("observed_facts") or ()
    if claim.claim_kind in {"observation", "interpretation", "followup"}:
        pmw_offending_fragments = _pmw_checker(
            claim.text,
            facts,
            observed_facts,
        )
        if pmw_offending_fragments:
            claim_reasons.append(
                "Die pmw-Angabe widerspricht der eigenen Trefferzahl "
                "(pmw = f / Tokenzahl × 1.000.000 ergibt einen anderen Wert): "
                + "; ".join(pmw_offending_fragments[:3])
                + "."
            )


# K3 Slice 3: declarative rows of this module (see claim_rules._table).
PATTERN_RULES = (
    _RULE_ABSOLUTE_FREQUENCY_MAGNITUDE,
    _RULE_FREQUENCY_COPRESENCE_INFERENCE,
)
