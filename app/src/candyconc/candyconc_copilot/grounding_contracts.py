"""Analysis contracts: response requirements, heuristics and fallbacks.

K3 Slice 1: byte-verbatim extraction from ``analysis_grounding.py`` (the
facade). Layer 2 of the grounding decomposition: imports
``grounding_schemas`` and ``grounding_evidence``.

Moved here: the explicit response-requirement machinery
(``normalise_response_requirements`` and its clause/cardinality helpers), the
``AnalysisContract`` dataclass (documented deviation, its ``from_raw`` calls
the heuristics below at runtime, so it must live at this layer),
``answer_envelope_schema`` (same reason: it materialises response
requirements), the prompt predicates (``_is_exploratory_prompt`` ..
``_is_human_ai_contrast_prompt``), the same-corpus collocation contract
helpers, ``heuristic_analysis_contract`` (K1-calibrated heuristics-before-LLM
layer), ``fallback_analysis_contract``, ``_requested_register_value`` and the
requested-count helpers (``_requested_method_step_count``,
``_requested_followup_question_count``).

``analysis_grounding`` re-exports every name below, so all existing imports
and ``analysis_grounding.<name>`` monkeypatch seams keep working. This module
must never import ``analysis_grounding``.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from candyconc.question_language import (
    is_english_question,
    routing_text,
    without_quoted_terms,
)

from .recipes import (  # noqa: F401  (Re-Export fuer Fassade und Verbraucher)
    RECIPES,
    RECIPES_BY_ID,
    Recipe,
    get_recipe,
    recipe_index,
    render_briefing,
)
from .question_form import (
    ROUTING_STAGE_FRAGEFORM,
    ist_kandidatenlisten_pruefung,
    ist_konstruktions_suchauftrag,
    kandidatenliste_aus_frage,  # noqa: F401  (Re-Export fuer P7)
)
from .grounding_evidence import _normalise_example_text
from .candidate_list import ist_kandidatenliste, kandidatenlisten_evidenz
from .grounding_schemas import (
    ANALYSIS_FAMILIES,
    ASSERTION_LEVELS,
    CLAIM_ID_LIMIT,
    CLAIM_KINDS,
    CLARIFICATION_QUESTION_LIMIT,
    ClaimDraft,
    DEFAULT_FORBIDDEN_CLAIMS,
    DELIVERABLE_KINDS,
    EVIDENCE_KINDS,
    MAX_ANSWER_CLAIMS,
    MAX_CLAIM_TEXT_CHARS,
    MAX_FACT_IDS_PER_CLAIM,
    MAX_RESPONSE_REQUIREMENTS,
    MAX_RESPONSE_REQUIREMENT_CHARS,
    MODE_VALUES,
    ResponseRequirement,
    TRACK_TOOL_LIMITS,
    TRACK_VALUES,
    _RESPONSE_CLAIM_LIMITATION_PATTERN,
    _RESPONSE_REQUEST_VERB_PATTERN,
    _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN,
    _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN,
    _RESPONSE_REQUIREMENT_LIMITATION_PATTERN,
    _claim_contains_possible_falsifier,
    _claim_uses_external_corpus_as_falsifier,
    _is_testable_hypothesis_claim,
    _coerce_bool,
    _compact_id,
    _compact_text,
    _dedupe_ordered_strs,
    _has_any_phrase,
    _metadata_request_needs_interpretation,
    _normalise_enum,
    _normalise_text_list,
    _normalised_question_text,
    _response_text_tokens,
    _tokens_are_contiguous_span,
    compatible_deliverable_kind,
    default_deliverable_kind_for_family,
    default_track_for_family,
    frage_ist_blosses_nachschlagen,
    resolve_allowed_tools,
)

_RESPONSE_COUNT_WORDS = {
    "ein": 1,
    "eine": 1,
    "einen": 1,
    "one": 1,
    "zwei": 2,
    "two": 2,
    "drei": 3,
    "three": 3,
    "vier": 4,
    "four": 4,
    "fünf": 5,
    "fuenf": 5,
    "five": 5,
    "sechs": 6,
    "six": 6,
    "sieben": 7,
    "seven": 7,
    "acht": 8,
    "eight": 8,
    "neun": 9,
    "nine": 9,
    "zehn": 10,
    "ten": 10,
    "elf": 11,
    "eleven": 11,
    "zwölf": 12,
    "zwoelf": 12,
    "twelve": 12,
    "dreizehn": 13,
    "thirteen": 13,
    "vierzehn": 14,
    "fourteen": 14,
    "fünfzehn": 15,
    "fuenfzehn": 15,
    "fifteen": 15,
    "sechzehn": 16,
    "sixteen": 16,
}
_COUNTED_RESPONSE_UNIT_PATTERN = re.compile(
    r"\b(?:(?P<bound>mindestens|wenigstens|höchstens|hoechstens|"
    r"at\s+least|at\s+most)\s+)?"
    r"(?P<low>\d+|ein(?:e|en)?|one|zwei|two|drei|three|vier|four|"
    r"fünf|fuenf|five|sechs|six|sieben|seven|acht|eight|"
    r"neun|nine|zehn|ten|elf|eleven|zwölf|zwoelf|twelve|"
    r"dreizehn|thirteen|vierzehn|fourteen|fünfzehn|fuenfzehn|"
    r"fifteen|sechzehn|sixteen)"
    r"(?:\s*(?:bis|to|[‐‑‒–—−-])\s*"
    r"(?P<high>\d+|ein(?:e|en)?|one|zwei|two|drei|three|vier|four|"
    r"fünf|fuenf|five|sechs|six|sieben|seven|acht|eight|"
    r"neun|nine|zehn|ten|elf|eleven|zwölf|zwoelf|twelve|"
    r"dreizehn|thirteen|vierzehn|fourteen|fünfzehn|fuenfzehn|"
    r"fifteen|sechzehn|sixteen))?\s+"
    r"(?:[\wäöüß-]+(?:\s*,\s*|\s+)){0,3}?"
    r"(?P<unit>beobachtung\w*|hypothese\w*|analyseschritt\w*|schritt\w*|"
    r"unterschied\w*|befund\w*|argument\w*|grund\w*|gründ\w*|"
    r"gruend\w*|beispiel\w*|"
    r"frage\w*|evidenzart\w*|methode\w*|zugang\w*|"
    r"observation\w*|hypothesi\w*|step\w*|difference\w*|finding\w*|"
    r"argument\w*|reason\w*|example\w*|question\w*|"
    r"method(?:s|ology|ologies)?)\b",
    re.IGNORECASE,
)
_UNCOUNTED_RESPONSE_UNIT_PATTERN = re.compile(
    r"\b(?P<unit>hypothese\w*|deutung\w*|interpretation\w*|"
    r"kennzahl\w*|maß\w*|mass\w*|metric\w*|measure\w*|"
    r"methodenvergleich\w*|methodisch\w*\s+vergleich\w*|"
    r"limitation\w*|einschränkung\w*|einschraenkung\w*|grenze\w*|"
    r"übereinstimmung\w*|uebereinstimmung\w*|widerspr\w*|"
    r"agreement\w*|contradiction\w*|"
    r"forschungsfrage\w*|research\s+question\w*|caveat\w*)\b",
    re.IGNORECASE,
)
_NEGATED_RESPONSE_REQUEST_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht|ohne|no|not|without)\b",
    re.IGNORECASE,
)
_DISTRIBUTIVE_RESPONSE_CONDITION_PATTERN = re.compile(
    r"\b(?:für|fuer)\s+jed(?:e|en|er|es)\b|\bjeweils\b|"
    r"\bfor\s+each\b|\beach\b",
    re.IGNORECASE,
)
_HYPOTHESIS_STRUCTURE_CONDITION_PATTERN = re.compile(
    r"\b(?:trenn\w*|separat\w*)\b"
    r"(?=[^.!?\n]{0,180}\bbeobachtung\w*\b)"
    r"(?=[^.!?\n]{0,180}\binterpretation\w*\b)"
    r"(?=[^.!?\n]{0,180}\bhypothese\w*\b)",
    re.IGNORECASE,
)
_RESPONSE_STRUCTURE_CONDITION_PATTERN = re.compile(
    r"\b(?:trenn\w*|separat\w*)\b"
    r"(?=[^.!?\n]{0,180}\binterpretation\w*\b)"
    r"(?=[^.!?\n]{0,180}\b(?:beobachtung\w*|hypothese\w*|"
    r"gesamtzahl\w*|stichprobe\w*|befund\w*|evidenz\w*|"
    r"limitation\w*|einschränk\w*|einschraenk\w*)\b)",
    re.IGNORECASE,
)


def _is_presentation_only_structure_instruction(text: str) -> bool:
    """Distinguish formatting clauses from a coupled substantive request."""

    if _RESPONSE_STRUCTURE_CONDITION_PATTERN.search(text or "") is None:
        return False
    trailing_clauses = re.split(r"[;.!?]", str(text or ""))[1:]
    return not any(
        _RESPONSE_REQUEST_VERB_PATTERN.search(clause)
        and (
            _COUNTED_RESPONSE_UNIT_PATTERN.search(clause)
            or _UNCOUNTED_RESPONSE_UNIT_PATTERN.search(clause)
            or _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN.search(clause)
        )
        for clause in trailing_clauses
    )


def _explicit_response_request_clauses(question_text: str) -> List[str]:
    """Return sentence-sized positive requests, not descriptive count mentions."""

    clauses: List[str] = []
    seen: set[str] = set()
    for sentence_match in re.finditer(
        r"[^.!?\n]+",
        str(question_text or ""),
    ):
        sentence_clauses: List[str] = []
        for raw_clause in sentence_match.group(0).split(";"):
            clause = raw_clause.strip(" ,")
            if not clause:
                continue
            if _RESPONSE_REQUEST_VERB_PATTERN.search(clause) is not None:
                sentence_clauses.append(clause)
                continue
            if (
                sentence_clauses
                and _DISTRIBUTIVE_RESPONSE_CONDITION_PATTERN.search(clause)
            ):
                # ``... zwei Hypothesen; jeweils mit Falsifikator`` is one
                # counted duty. A separate imperative after the semicolon
                # remains its own clause and is coupled by family below.
                sentence_clauses[-1] = f"{sentence_clauses[-1]}; {clause}"
        for clause in sentence_clauses:
            key = _normalised_question_text(clause)
            if key in seen:
                continue
            seen.add(key)
            clauses.append(clause)
    return clauses


def _response_unit_is_negated(clause: str, unit_start: int) -> bool:
    prefix = clause[max(0, unit_start - 48) : unit_start]
    return _NEGATED_RESPONSE_REQUEST_PATTERN.search(prefix) is not None


def _explicit_counted_response_groups(
    question_text: str,
) -> List[Tuple[str, str, str, int, str]]:
    """Extract positive counted output groups from literal request clauses."""

    groups: List[Tuple[str, str, str, int, str]] = []
    request_clauses = _explicit_response_request_clauses(question_text)
    for request_clause in request_clauses:
        source_quote = _compact_text(
            request_clause,
            MAX_RESPONSE_REQUIREMENT_CHARS,
        )
        count_matches = list(
            _COUNTED_RESPONSE_UNIT_PATTERN.finditer(request_clause)
        )
        for count_match in count_matches:
            if _response_unit_is_negated(
                request_clause,
                count_match.start(),
            ):
                continue
            count = _counted_response_requirement(count_match.group(0))
            if not count:
                continue
            unit = _normalised_question_text(count_match.group("unit"))
            unit_family = _response_unit_family(unit)
            coupled_clauses = [
                source_quote
                if len(count_matches) == 1
                else _compact_text(
                    count_match.group(0),
                    MAX_RESPONSE_REQUIREMENT_CHARS,
                )
            ]
            for candidate_clause in request_clauses:
                candidate_quote = _compact_text(
                    candidate_clause,
                    MAX_RESPONSE_REQUIREMENT_CHARS,
                )
                if not candidate_quote or candidate_quote == source_quote:
                    continue
                candidate_family = _response_unit_family(candidate_quote)
                distributive_match = bool(
                    _DISTRIBUTIVE_RESPONSE_CONDITION_PATTERN.search(
                        candidate_quote
                    )
                    and candidate_family == unit_family
                )
                if distributive_match:
                    coupled_clauses.append(candidate_quote)
            groups.append(
                (
                    source_quote,
                    unit,
                    _counted_requirement_claim_kind(
                        count_match.group("unit")
                    ),
                    count,
                    "; ".join(coupled_clauses),
                )
            )
    return groups


def _response_unit_family(text: str) -> str:
    lowered = _normalised_question_text(text)
    for family, markers in (
        ("hypothesis", ("hypothese", "hypothesi")),
        ("observation", ("beobachtung", "observation")),
        ("finding", ("befund", "finding")),
        ("step", ("schritt", "step", "methode", "method")),
        ("difference", ("unterschied", "difference")),
        ("example", ("beispiel", "example")),
        ("question", ("frage", "question")),
        ("reason", ("grund", "gründ", "reason")),
    ):
        if any(marker in lowered for marker in markers):
            return family
    return ""


def _response_count_value(token: str | None) -> int | None:
    value_token = str(token or "").casefold()
    if not value_token:
        return None
    try:
        return int(value_token)
    except ValueError:
        return _RESPONSE_COUNT_WORDS.get(value_token)


def _counted_response_cardinality(
    source_quote: str,
) -> tuple[int, int | None] | None:
    """Return the honest minimum/maximum implied by a counted request."""

    match = _COUNTED_RESPONSE_UNIT_PATTERN.search(
        _normalised_question_text(source_quote)
    )
    if match is None:
        return None
    low = _response_count_value(match.group("low"))
    high = _response_count_value(match.group("high"))
    if low is None or not 1 <= low <= MAX_RESPONSE_REQUIREMENTS:
        return None
    if high is not None:
        if not low <= high <= MAX_RESPONSE_REQUIREMENTS:
            return None
        return low, high
    bound = _normalised_question_text(match.group("bound"))
    if bound in {"mindestens", "wenigstens", "at least"}:
        return low, None
    if bound in {"höchstens", "hoechstens", "at most"}:
        # The imperative still requests an answer, but not exactly ``low``
        # items. One required slot plus the explicit ceiling preserves both.
        return 1, low
    return low, low


def _counted_response_requirement(source_quote: str) -> int | None:
    cardinality = _counted_response_cardinality(source_quote)
    return cardinality[0] if cardinality is not None else None


def _hypothesis_response_cardinality(
    requirements: Sequence[ResponseRequirement],
) -> tuple[int, int | None] | None:
    """Combine distinct counted hypothesis groups into one answer bound."""

    minimum = 0
    maximum = 0
    found = False
    unbounded = False
    seen_groups: set[str] = set()
    for requirement in requirements:
        surface = requirement.source_quote or requirement.description
        if not _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(surface):
            continue
        group_key = _normalised_question_text(surface)
        if not group_key or group_key in seen_groups:
            continue
        cardinality = _counted_response_cardinality(surface)
        if cardinality is None:
            continue
        seen_groups.add(group_key)
        found = True
        group_minimum, group_maximum = cardinality
        minimum += group_minimum
        if group_maximum is None:
            unbounded = True
        else:
            maximum += group_maximum
    if not found:
        return None
    return minimum, None if unbounded else maximum


def _counted_requirement_claim_kind(unit: str) -> str:
    lowered = str(unit or "").casefold()
    if any(token in lowered for token in ("beobacht", "observation", "evidenzart")):
        return "observation"
    if any(token in lowered for token in ("frage", "question")):
        return "followup"
    return "interpretation"


def _response_requirement_unit(requirement: ResponseRequirement) -> str:
    for text in (requirement.description, requirement.source_quote):
        match = _COUNTED_RESPONSE_UNIT_PATTERN.search(str(text or ""))
        if match is not None:
            return _normalised_question_text(match.group("unit"))
    return ""


def _explicit_uncounted_response_requirements(
    question_text: str,
) -> List[Tuple[str, str]]:
    """Return literal user clauses that demand an extra analytical unit.

    The extraction recovers prompt obligations, never answer content. It is
    deliberately limited to explicit request verbs plus analytical output
    nouns that a broad deliverable cannot safely imply on its own.
    """

    clauses: List[Tuple[str, str]] = []
    for request_clause in _explicit_response_request_clauses(question_text):
        # This clause specifies presentation of already requested analytical
        # content. Treating its nouns as extra response slots would turn
        # "separate observation, interpretation and hypothesis" into three
        # additional deliverables.
        if _is_presentation_only_structure_instruction(request_clause):
            continue
        verb_match = _RESPONSE_REQUEST_VERB_PATTERN.search(request_clause)
        if verb_match is None:
            continue
        source_quote = _compact_text(
            request_clause[verb_match.start() :].strip(" ,"),
            MAX_RESPONSE_REQUIREMENT_CHARS,
        )
        if not source_quote or _COUNTED_RESPONSE_UNIT_PATTERN.search(
            source_quote
        ):
            continue
        unit_matches = [
            match
            for match in _UNCOUNTED_RESPONSE_UNIT_PATTERN.finditer(
                source_quote
            )
            if not _response_unit_is_negated(source_quote, match.start())
        ]
        if not unit_matches:
            continue
        # ``Deutungen als Hypothesen`` names one requested output and its
        # epistemic status, not two independently fillable answer slots.
        if len(unit_matches) == 2 and re.fullmatch(
            r"\s+(?:als|as)\s+",
            source_quote[unit_matches[0].end() : unit_matches[1].start()],
            re.IGNORECASE,
        ):
            unit_matches = [unit_matches[1]]
        multiple_units = len(unit_matches) > 1
        seen_units: set[tuple[str, str]] = set()
        for unit_match in unit_matches:
            unit = unit_match.group("unit").casefold()
            if any(
                marker in unit
                for marker in (
                    "limitation",
                    "einschränk",
                    "einschraenk",
                    "grenze",
                    "caveat",
                )
            ):
                claim_kind = "limitation"
            elif "frage" in unit or "question" in unit:
                claim_kind = "followup"
            else:
                claim_kind = "interpretation"
            unit_source = (
                _compact_text(
                    unit_match.group("unit"),
                    MAX_RESPONSE_REQUIREMENT_CHARS,
                )
                if multiple_units
                else source_quote
            )
            key = (_normalised_question_text(unit_source), claim_kind)
            if key in seen_units:
                continue
            seen_units.add(key)
            clauses.append((unit_source, claim_kind))
    return clauses


def normalise_response_requirements(
    raw: Any,
    *,
    question_text: str = "",
) -> List[ResponseRequirement]:
    if not isinstance(raw, (list, tuple)):
        return []
    materialized_requirements = bool(raw) and all(
        isinstance(item, ResponseRequirement) for item in raw
    )
    requirements: List[ResponseRequirement] = []
    used_ids: set[str] = set()
    for index, item in enumerate(raw[:MAX_RESPONSE_REQUIREMENTS], start=1):
        requirement = ResponseRequirement.from_raw(
            item,
            fallback_id=f"requirement_{index}",
            question_text=question_text,
        )
        if requirement is None:
            continue
        if _is_presentation_only_structure_instruction(
            " ".join(
                value
                for value in (
                    requirement.source_quote,
                    requirement.description,
                )
                if value
            )
        ):
            # A request to separate presentation layers is not another atomic
            # interpretation duty. The deliverable contract already requires
            # the relevant claim kinds and the renderer keeps them distinct.
            continue
        if question_text and _normalised_question_text(
            requirement.source_quote
        ) == _normalised_question_text(question_text):
            # A response slot is an additional atomic duty, not a second copy
            # of the whole deliverable. Literal counted or uncounted duties in
            # the same question are recovered below from the user's wording.
            continue
        counted_match = _COUNTED_RESPONSE_UNIT_PATTERN.search(
            requirement.source_quote
        )
        if counted_match is not None:
            inferred_kind = _counted_requirement_claim_kind(
                counted_match.group("unit")
            )
            if inferred_kind != requirement.claim_kind:
                requirement = replace(
                    requirement,
                    claim_kind=inferred_kind,
                )
        base_id = requirement.id
        requirement_id = base_id
        suffix = 2
        while requirement_id in used_ids:
            suffix_text = f"_{suffix}"
            requirement_id = (
                base_id[: CLAIM_ID_LIMIT - len(suffix_text)] + suffix_text
            )
            suffix += 1
        if requirement_id != requirement.id:
            requirement = replace(requirement, id=requirement_id)
        used_ids.add(requirement.id)
        requirements.append(requirement)
    counted_groups = (
        _explicit_counted_response_groups(question_text)
        if question_text
        else []
    )
    explicit_uncounted = (
        _explicit_uncounted_response_requirements(question_text)
        if question_text
        else []
    )
    if counted_groups and requirements:
        # The planner may overproduce slots. Keep at most the literal requested
        # cardinality for each counted output group; extra model slots do not
        # become new user obligations merely because their quote is valid.
        group_counts = [0 for _group in counted_groups]
        bounded_requirements: List[ResponseRequirement] = []
        for requirement in requirements:
            requirement_unit = _response_requirement_unit(requirement)
            requirement_source = _normalised_question_text(
                requirement.source_quote
            )
            requirement_tokens = _response_text_tokens(
                requirement.source_quote
            )
            requirement_family = _response_unit_family(
                requirement_unit
                or requirement.source_quote
                or requirement.description
            )
            group_index = next(
                (
                    index
                    for index, (
                        source_quote,
                        unit,
                        claim_kind,
                        _target_count,
                        _description,
                    ) in enumerate(counted_groups)
                    if requirement.claim_kind == claim_kind
                    and (
                        requirement_unit == unit
                        or (
                            requirement_family
                            and requirement_family
                            == _response_unit_family(unit)
                        )
                    )
                    and (
                        requirement_source
                        in _normalised_question_text(source_quote)
                        or _normalised_question_text(source_quote)
                        in requirement_source
                        or _tokens_are_contiguous_span(
                            requirement_tokens,
                            _response_text_tokens(_description),
                        )
                        or any(
                            _DISTRIBUTIVE_RESPONSE_CONDITION_PATTERN.search(
                                description_part
                            )
                            and _tokens_are_contiguous_span(
                                _response_text_tokens(description_part),
                                requirement_tokens,
                            )
                            for description_part in _description.split(";")
                        )
                    )
                ),
                None,
            )
            if group_index is not None:
                (
                    canonical_source_quote,
                    _canonical_unit,
                    _canonical_kind,
                    target_count,
                    canonical_description,
                ) = counted_groups[group_index]
                if group_counts[group_index] >= target_count:
                    continue
                group_counts[group_index] += 1
                requirement = replace(
                    requirement,
                    source_quote=canonical_source_quote,
                    description=canonical_description,
                )
            bounded_requirements.append(requirement)
        requirements = bounded_requirements
        used_ids = {item.id for item in requirements}
    if explicit_uncounted and requirements:
        atomic_requirements: List[ResponseRequirement] = []
        for requirement in requirements:
            requirement_tokens = _response_text_tokens(
                requirement.source_quote
            )
            covered_atomic_slots = {
                (_normalised_question_text(source_quote), claim_kind)
                for source_quote, claim_kind in explicit_uncounted
                if requirement.claim_kind == claim_kind
                and _tokens_are_contiguous_span(
                    _response_text_tokens(source_quote),
                    requirement_tokens,
                )
            }
            if len(covered_atomic_slots) > 1:
                # A planner may bundle explicitly separate outputs into one
                # slot. Replace that bundle below with one literal slot per
                # requested unit so cardinality cannot silently collapse.
                continue
            atomic_requirements.append(requirement)
        requirements = atomic_requirements
        used_ids = {item.id for item in requirements}
    # A schema-valid weak-model response may still omit an explicit numbered
    # obligation entirely. Recover only count phrases that are literally
    # present in the user's own question; this adds no answer content.
    if question_text:
        for (
            source_quote,
            matched_unit,
            claim_kind,
            target_count,
            matched_description,
        ) in counted_groups:
            source_key = _normalised_question_text(source_quote)
            matching = [
                item
                for item in requirements
                if item.claim_kind == claim_kind
                and _response_requirement_unit(item) == matched_unit
                and (
                    _normalised_question_text(item.source_quote)
                    in source_key
                    or source_key
                    in _normalised_question_text(item.source_quote)
                )
            ]
            while (
                len(matching) < target_count
                and len(requirements) < MAX_RESPONSE_REQUIREMENTS
            ):
                suffix = len(matching) + 1
                base_id = _compact_id(
                    f"requested_{matched_unit}",
                    CLAIM_ID_LIMIT,
                ) or "requested_item"
                candidate_id = _compact_id(
                    f"{base_id}_{suffix}",
                    CLAIM_ID_LIMIT,
                )
                while candidate_id in used_ids:
                    suffix += 1
                    candidate_id = _compact_id(
                        f"{base_id}_{suffix}",
                        CLAIM_ID_LIMIT,
                    )
                requirement = ResponseRequirement(
                    id=candidate_id,
                    description=matched_description,
                    claim_kind=claim_kind,
                    source_quote=source_quote,
                )
                requirements.append(requirement)
                matching.append(requirement)
                used_ids.add(candidate_id)
        # A weak planner can return a schema-valid but non-anchored value such
        # as ``source_quote: "none"``. Preserve only explicit analytical
        # obligations recoverable verbatim from the user's own instruction;
        # their empirical content remains entirely model-owned.
        for source_quote, claim_kind in explicit_uncounted:
            source_key = _normalised_question_text(source_quote)
            if any(
                source_key
                in _normalised_question_text(canonical_description)
                for (
                    _group_source,
                    _group_unit,
                    _group_kind,
                    _group_count,
                    canonical_description,
                ) in counted_groups
            ):
                continue
            if any(
                item.claim_kind == claim_kind
                and (
                    source_key
                    in _normalised_question_text(item.source_quote)
                    or _normalised_question_text(item.source_quote)
                    in source_key
                )
                for item in requirements
            ):
                continue
            base_id = _compact_id(
                f"requested_{claim_kind}",
                CLAIM_ID_LIMIT,
            ) or "requested_item"
            candidate_id = base_id
            suffix = 2
            while candidate_id in used_ids:
                candidate_id = _compact_id(
                    f"{base_id}_{suffix}",
                    CLAIM_ID_LIMIT,
                )
                suffix += 1
            requirements.append(
                ResponseRequirement(
                    id=candidate_id,
                    description=source_quote,
                    claim_kind=claim_kind,
                    source_quote=source_quote,
                )
            )
            used_ids.add(candidate_id)
            if len(requirements) >= MAX_RESPONSE_REQUIREMENTS:
                break
    # Weak models often preserve the requested count in source_quote but emit
    # only one slot. Expand that anchored slot to the minimum explicit count;
    # never infer a count from model prose or empirical content.
    if not question_text and not materialized_requirements:
        for requirement in list(requirements):
            if len(requirements) >= MAX_RESPONSE_REQUIREMENTS:
                break
            target_count = _counted_response_requirement(
                requirement.source_quote
            )
            if not target_count:
                continue
            quote_key = _normalised_question_text(
                requirement.source_quote
            )
            existing_count = sum(
                _normalised_question_text(item.source_quote) == quote_key
                and item.claim_kind == requirement.claim_kind
                for item in requirements
            )
            while (
                existing_count < target_count
                and len(requirements) < MAX_RESPONSE_REQUIREMENTS
            ):
                suffix = existing_count + 1
                candidate_id = _compact_id(
                    f"{requirement.id}_{suffix}",
                    CLAIM_ID_LIMIT,
                )
                while candidate_id in used_ids:
                    suffix += 1
                    candidate_id = _compact_id(
                        f"{requirement.id}_{suffix}",
                        CLAIM_ID_LIMIT,
                    )
                clone = replace(requirement, id=candidate_id)
                requirements.append(clone)
                used_ids.add(candidate_id)
                existing_count += 1
    return requirements


@dataclass
class AnalysisContract:
    mode: str = "direct_answer"
    track: str = "bounded_analysis"
    analysis_family: str = "open_research"
    deliverable_kind: str = "overview"
    question_scope: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    forbidden_claims: List[str] = field(default_factory=lambda: list(DEFAULT_FORBIDDEN_CLAIMS))
    response_shape: str = ""
    response_requirements: List[ResponseRequirement] = field(
        default_factory=list
    )
    needs_clarification: bool = False
    clarification_question: str = ""

    @classmethod
    def from_raw(
        cls,
        raw: Any,
        *,
        question_text: str = "",
        available_tools: Sequence[str],
        read_only_tools: Sequence[str],
    ) -> "AnalysisContract":
        payload = raw if isinstance(raw, dict) else {}
        normalized_question = _normalised_question_text(question_text)
        mode = _normalise_enum(payload.get("mode"), MODE_VALUES, "direct_answer")
        requested_family = _normalise_enum(
            payload.get("analysis_family"),
            ANALYSIS_FAMILIES,
            "open_research" if mode == "tool_analysis" else "open_research",
        )
        track = _normalise_enum(
            payload.get("track"),
            TRACK_VALUES,
            default_track_for_family(
                requested_family,
                question_text=question_text,
            ),
        )
        deliverable_kind = _normalise_enum(
            payload.get("deliverable_kind"),
            DELIVERABLE_KINDS,
            default_deliverable_kind_for_family(
                requested_family,
                question_text=question_text,
                track=track,
            ),
        )
        requested_tools = _normalise_text_list(
            payload.get("allowed_tools"),
            max_items=8,
            item_limit=80,
        )
        comparative_prompt = _is_comparative_prompt(
            normalized_question
        )
        collocation_contrast_prompt = (
            _is_human_ai_contrast_prompt(normalized_question)
            and _has_any_phrase(
                normalized_question,
                ("kollokation", "kollokationen", "kollokate"),
            )
        )
        read_only_available = set(available_tools).intersection(
            read_only_tools
        )
        clarification_requested = bool(
            mode == "clarify"
            or _coerce_bool(payload.get("needs_clarification"))
        )
        rescued_open_clarification = bool(
            clarification_requested
            and _is_exploratory_prompt(normalized_question)
            and not comparative_prompt
            and "frequency_list" in read_only_available
            and read_only_available.intersection(
                {
                    "semantic_search",
                    "semantic_cluster",
                    "semantic_cluster_words",
                    "document_search",
                    "run_cqlf_query",
                }
            )
        )
        normalized_open_scope = bool(
            mode == "tool_analysis"
            and _is_exploratory_prompt(normalized_question)
            and not comparative_prompt
            and not _is_method_help_prompt(normalized_question)
        )
        if rescued_open_clarification:
            # Openness is the requested research task, not a missing premise.
            # When a lexical plus contextual read-only evidence path exists,
            # execute it rather than asking the user to choose our method.
            mode = "tool_analysis"
            requested_family = "open_research"
            track = "exploratory_research"
            deliverable_kind = "overview"
            requested_tools = []
        elif clarification_requested:
            mode = "clarify"
        elif mode == "direct_answer" and requested_tools:
            # A model occasionally emits an internally contradictory contract:
            # direct answer plus a concrete tool strategy. Preserve the chosen
            # strategy instead of silently deleting it.
            mode = "tool_analysis"
        if normalized_open_scope:
            # The model remains free to choose evidence and interpretation,
            # but it may not turn an explicit open corpus exploration into a
            # metadata inventory or an unrequested contrast.
            requested_family = "open_research"
            track = "exploratory_research"
            deliverable_kind = default_deliverable_kind_for_family(
                requested_family,
                question_text=question_text,
                track=track,
            )
        if mode == "tool_analysis" and collocation_contrast_prompt:
            # This request has one method-specific path. Global keyness or an
            # unscoped frequency list cannot substitute for term collocations.
            requested_family = "contrast_keyness"
            track = "comparative_analysis"
            requested_tools = ["compare_collocates", "metadata_values"]
        if mode == "tool_analysis" and track == "exploratory_research":
            if requested_family in {"kwic_context", "term_frequency", "document_lookup"}:
                requested_family = "open_research"
            if len(requested_tools) < 2:
                requested_tools = []
        if mode == "tool_analysis" and track == "comparative_analysis" and comparative_prompt:
            if requested_family in {"kwic_context", "term_frequency", "document_lookup"}:
                requested_family = "open_research"
            if len(requested_tools) < 2:
                requested_tools = []
        if (
            requested_family == "kwic_context"
            and track == "lookup"
            and not frage_ist_blosses_nachschlagen(question_text)
        ):
            # Der Track MUSS hier mitgehoben werden, nicht erst im
            # Konstruktor. Gemessen am 2026-09-02: die Frage
            # konstr-scharnier-dreigliedrig (518 Zeichen) mit einem
            # Modell-Kontrakt track="lookup" bekam korrekt
            # deliverable_kind=analysis_report, behielt aber
            # TRACK_TOOL_LIMITS["lookup"]=2 und damit allowed_tools
            # ['metadata_values', 'run_cqlf_query']: ein Analysebericht mit
            # Zwei-Werkzeug-Nachschlagebudget. resolve_allowed_tools liest
            # den Track, deshalb steht die Hebung davor.
            track = "bounded_analysis"
        deliverable_kind = compatible_deliverable_kind(
            deliverable_kind,
            requested_family,
            question_text=question_text,
            track=track,
        )
        allowed_tools = resolve_allowed_tools(
            analysis_family=requested_family,
            track=track,
            requested_tools=requested_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        contextual_hypothesis_prompt = bool(
            mode == "tool_analysis"
            and requested_family == "open_research"
            and _requires_contextual_hypothesis_evidence(
                normalized_question
            )
        )
        if contextual_hypothesis_prompt:
            contextual_candidates = (
                "run_cqlf_query",
                "document_search",
                "semantic_search",
                "semantic_cluster_words",
                "semantic_cluster",
            )
            contextual_tool = next(
                (
                    tool_name
                    for tool_name in contextual_candidates
                    if tool_name in allowed_tools
                ),
                "",
            ) or next(
                (
                    tool_name
                    for tool_name in contextual_candidates
                    if tool_name in read_only_available
                ),
                "",
            )
            if contextual_tool:
                allowed_tools = _dedupe_ordered_strs(
                    [contextual_tool, *allowed_tools]
                )[: TRACK_TOOL_LIMITS["exploratory_research"]]
        if (
            mode == "tool_analysis"
            and requested_family == "open_research"
            and track == "exploratory_research"
            and deliverable_kind == "overview"
            and _is_exploratory_prompt(normalized_question)
        ):
            # A generic "what is interesting here?" answer needs both a
            # lexical inventory and at least one contextual view. This chooses
            # evidence classes, not findings: the model still selects anchors,
            # tools and interpretations from the active corpus.
            contextual_candidates = (
                "semantic_search",
                "document_search",
                "run_cqlf_query",
                "semantic_cluster_words",
                "semantic_cluster",
            )
            contextual_tool = next(
                (
                    tool_name
                    for tool_name in allowed_tools
                    if tool_name in contextual_candidates
                ),
                "",
            ) or next(
                (
                    tool_name
                    for tool_name in contextual_candidates
                    if tool_name in read_only_available
                ),
                "",
            )
            evidence_priority = [
                tool_name
                for tool_name in (
                    (
                        "frequency_list"
                        if "frequency_list" in read_only_available
                        else ""
                    ),
                    contextual_tool,
                )
                if tool_name
            ]
            allowed_tools = _dedupe_ordered_strs(
                [*evidence_priority, *allowed_tools]
            )[
                : TRACK_TOOL_LIMITS["exploratory_research"]
            ]
        if mode != "tool_analysis":
            allowed_tools = []
        response_shape = _compact_text(payload.get("response_shape", ""), 120)
        if rescued_open_clarification or normalized_open_scope:
            response_shape = "grounded_exploratory_report"
        if mode == "tool_analysis" and not response_shape:
            if requested_family == "open_research":
                response_shape = "grounded_exploratory_report"
            elif requested_family == "kwic_context":
                response_shape = "grounded_kwic_presence"
            elif requested_family == "term_frequency":
                response_shape = "grounded_term_frequency"
            elif requested_family in ("term_profile", "collocation"):
                # 'collocation' fehlte hier, und ein LLM-Kontrakt mit dieser
                # Familie kam ohne Shape durch. Beide teilen den Verfasser.
                response_shape = "grounded_term_profile"
            elif requested_family == "ngram_profile":
                response_shape = "grounded_ngram_profile"
            elif requested_family == "lexical_diversity":
                response_shape = "grounded_lexical_diversity"
            elif requested_family == "trend_analysis":
                response_shape = "grounded_trend_analysis"
            elif requested_family == "word_sketch_profile":
                response_shape = "grounded_word_sketch"
        if requested_family == "open_research" and response_shape == "grounded_kwic_presence":
            response_shape = "grounded_exploratory_report"
        required_evidence = [
            item
            for item in _normalise_text_list(
                payload.get("required_evidence"),
                max_items=6,
                item_limit=120,
            )
            if item in EVIDENCE_KINDS
        ]
        if rescued_open_clarification:
            required_evidence = [
                "lexical_frequency_rows",
                "content_rows",
                "contextual_rows",
            ]
        if (
            contextual_hypothesis_prompt
            and "contextual_rows" not in required_evidence
        ):
            required_evidence.append("contextual_rows")
        if (
            mode == "tool_analysis"
            and requested_family == "open_research"
            and track == "exploratory_research"
            and required_evidence
            and _is_exploratory_prompt(normalized_question)
        ):
            # In an open analysis, required evidence is the minimum needed to
            # ground a useful start, not an AND-list of every tool the model
            # might explore. Keep its wider tool strategy available while
            # preventing forced, unmotivated retrieval queries.
            if _is_theme_overview_prompt(normalized_question):
                preferred = [
                    ("content_rows", "frequency_list")
                ]
                if "semantic_cluster_words" in allowed_tools:
                    preferred.append(
                        ("cluster_rows", "semantic_cluster_words")
                    )
                elif "semantic_search" in allowed_tools:
                    preferred.append(("semantic_rows", "semantic_search"))
            else:
                preferred = [
                    ("lexical_frequency_rows", "frequency_list"),
                    ("content_rows", "frequency_list"),
                ]
                contextual_tool = next(
                    (
                        tool_name
                        for tool_name in (
                            "semantic_search",
                            "document_search",
                            "run_cqlf_query",
                        )
                        if tool_name in allowed_tools
                    ),
                    "",
                )
                if contextual_tool:
                    preferred.append(
                        ("contextual_rows", contextual_tool)
                    )
            bounded_required = [
                evidence_kind
                for evidence_kind, tool_name in preferred
                if tool_name in allowed_tools
            ]
            if not bounded_required:
                bounded_required = [
                    kind
                    for kind in required_evidence
                    if not (
                        kind == "total_hits"
                        and "frequency_rows" in required_evidence
                    )
                ][:2]
            required_evidence = bounded_required
        if (
            mode == "tool_analysis"
            and track == "method_help"
            and any(
                tool in allowed_tools
                for tool in (
                    "run_cqlf_query",
                    "document_search",
                    "semantic_search",
                    "semantic_cluster",
                    "semantic_cluster_words",
                )
            )
            and "contextual_rows" not in required_evidence
        ):
            required_evidence.append("contextual_rows")
        if collocation_contrast_prompt:
            required_evidence = [
                kind
                for kind in required_evidence
                if kind in {"metric_rows", "metadata_rows"}
            ]
            for kind in ("metric_rows", "metadata_rows"):
                if kind not in required_evidence:
                    required_evidence.append(kind)
        requested_forbidden_claims = _normalise_text_list(
            payload.get("forbidden_claims"),
            max_items=8,
            item_limit=120,
        )
        response_requirements = (
            normalise_response_requirements(
                payload.get("response_requirements"),
                question_text=question_text,
            )
            if mode == "tool_analysis"
            else []
        )
        # Der Termlisten-Modus sitzt AUCH hier, nicht nur an der
        # Heuristik. Am 2026-09-02 kam der contrast_keyness-Vertrag der
        # Markerfrage aus genau diesem Bauer (Annotation "stage=llm
        # recipe=kontrast" in evaluation/deutung/harnisch_nachher.jsonl).
        return _mit_termlisten_modus(
            cls(
                mode=mode,
                track=track,
                analysis_family=requested_family,
                deliverable_kind=deliverable_kind,
                question_scope=_compact_text(payload.get("question_scope", ""), 220),
                allowed_tools=allowed_tools,
                required_evidence=required_evidence,
                forbidden_claims=_dedupe_ordered_strs(
                    [*DEFAULT_FORBIDDEN_CLAIMS, *requested_forbidden_claims]
                ),
                response_shape=response_shape,
                response_requirements=response_requirements,
                needs_clarification=mode == "clarify",
                clarification_question=(
                    _compact_text(
                        payload.get("clarification_question", ""),
                        CLARIFICATION_QUESTION_LIMIT,
                    )
                    if mode == "clarify"
                    else ""
                ),
            ),
            question_text,
            available_tools,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _response_requirement_condition_reasons(
    claim_text: str,
    requirement: ResponseRequirement,
    *,
    assertion_level: str = "qualified",
) -> List[str]:
    description = str(requirement.description or "")
    reasons: List[str] = []
    if (
        _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN.search(description)
        and not _claim_contains_possible_falsifier(claim_text or "")
    ):
        reasons.append(
            _t("Der zugeordnete Antwortslot verlangt ein mögliches "
            "Widerlegungsergebnis; der Claim enthält keines.", 'The assigned response slot requires a possible falsifying result. The claim provides none.')
        )
    elif (
        _RESPONSE_REQUIREMENT_FALSIFIER_PATTERN.search(description)
        and _claim_uses_external_corpus_as_falsifier(claim_text or "")
    ):
        reasons.append(
            _t("Der zugeordnete Antwortslot verlangt ein mögliches Ergebnis der "
            "Auswertung des aktiven Korpus; ein Gegen- oder Vergleichskorpus "
            "ist kein Widerlegungsergebnis für diesen Lauf.", 'The assigned response slot requires a possible result from analysing the active corpus. A counter-corpus or comparison corpus is not a falsifying result for this run.')
        )
    if (
        _RESPONSE_REQUIREMENT_LIMITATION_PATTERN.search(description)
        and _RESPONSE_CLAIM_LIMITATION_PATTERN.search(claim_text or "")
        is None
    ):
        reasons.append(
            _t("Der zugeordnete Antwortslot verlangt eine ausdrückliche "
            "Limitation oder Reichweitengrenze; der Claim enthält keine.", 'The assigned response slot requires an explicit limitation or scope boundary. The claim provides none.')
        )
    if (
        _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(description)
        and not _is_testable_hypothesis_claim(
            claim_text,
            claim_kind=requirement.claim_kind,
            assertion_level=assertion_level,
        )
    ):
        reasons.append(
            _t("Der zugeordnete Antwortslot verlangt eine sichtbar vorläufige "
            "Hypothese mit einem konkreten möglichen Gegenresultat im aktiven "
            "Korpus; der Claim erfüllt diese Struktur nicht.", 'The assigned response slot requires a visibly provisional hypothesis with a specific possible counter-result in the active corpus. The claim does not meet that structure.')
        )
    return reasons


def answer_envelope_schema(
    *,
    deliverable_kind: str = "",
    question_text: str = "",
    response_requirements: Sequence[Any] = (),
) -> Dict[str, Any]:
    schema = {
        "name": "answer_envelope",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "claims": {
                    "type": "array",
                    "maxItems": MAX_ANSWER_CLAIMS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {
                                "type": "string",
                                "maxLength": CLAIM_ID_LIMIT,
                            },
                            "claim_kind": {"type": "string", "enum": list(CLAIM_KINDS)},
                            "text": {
                                "type": "string",
                                "maxLength": MAX_CLAIM_TEXT_CHARS,
                            },
                            "fact_ids": {
                                "type": "array",
                                "maxItems": MAX_FACT_IDS_PER_CLAIM,
                                "items": {"type": "string", "maxLength": 96},
                            },
                            "assertion_level": {"type": "string", "enum": list(ASSERTION_LEVELS)},
                        },
                        "required": ["id", "claim_kind", "text", "fact_ids", "assertion_level"],
                    },
                },
                "evidence_gaps": {"type": "array", "items": {"type": "string"}},
                "blocked_claims": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["claims", "evidence_gaps", "blocked_claims"],
        },
    }
    claims_schema = schema["schema"]["properties"]["claims"]
    normalized_requirements = normalise_response_requirements(
        list(response_requirements or [])
    )
    if normalized_requirements:
        claim_item_schema = claims_schema["items"]
        claim_item_schema["properties"]["response_requirement_id"] = {
            "type": "string",
            "enum": ["", *[item.id for item in normalized_requirements]],
            "description": (
                "Exactly one fully satisfied response requirement, or an "
                "empty string for an additional claim."
            ),
        }
        claim_item_schema["required"].append(
            "response_requirement_id"
        )
    if deliverable_kind == "followup_questions":
        requested_questions = _requested_followup_question_count(
            question_text
        )
        claims_schema["minItems"] = requested_questions or 3
        claims_schema["maxItems"] = requested_questions or 5
        claims_schema["items"]["properties"]["claim_kind"]["enum"] = [
            "followup"
        ]
    if deliverable_kind == "method_advice":
        claims_schema["items"]["properties"]["claim_kind"]["enum"] = [
            "interpretation"
        ]
        requested_steps = _requested_method_step_count(question_text)
        if requested_steps is not None:
            claims_schema["minItems"] = requested_steps
            claims_schema["maxItems"] = requested_steps
    if deliverable_kind == "lookup_answer":
        # A factual lookup is complete only when the model states the retrieved
        # result as an observation. Scope caveats remain valid limitations;
        # interpretive reports use their broader deliverable schemas.
        claims_schema["items"]["properties"]["claim_kind"]["enum"] = [
            "observation",
            "limitation",
        ]
    return schema


def _metadata_request_is_focused(text: str) -> bool:
    lowered = _normalised_question_text(text)
    if not _has_any_phrase(
        lowered,
        (
            "metadat",
            "subkorpus",
            "subkorpora",
            "register",
            "quelle",
            "source",
            "modell",
            "model",
        ),
    ):
        return False
    # A metadata dimension inside a request for a concrete measurement is a
    # scope, not the requested result. Leave such mixed questions to the
    # flexible planner instead of reducing them to a metadata-only contract.
    #
    return not _has_any_phrase(
        lowered,
        (
            "frequenz",
            "häufig",
            "wie oft",
            "kwic",
            "konkordanz",
            "kollok",
            "keyness",
            "dispersion",
            "n-gram",
            "ngram",
            "word sketch",
            "word-sketch",
            "wortprofil",
            "semantik",
            "embedding",
        ),
    )


_HYPOTHESIS_GENERATION_ACTION_PATTERN = re.compile(
    r"\b(?:leite|formuliere|entwickle|generiere|nenne|skizziere|"
    r"derive|formulate|develop|generate|name|outline)\w*\b",
    re.IGNORECASE,
)
_HYPOTHESIS_EVIDENCE_CUE_PATTERN = re.compile(
    r"\b(?:korpus|corpus|muster\w*|beobachtung\w*|befund\w*|"
    r"evidenz\w*|beleg\w*|ergebnis\w*|kontext\w*|sichtbar\w*)\b",
    re.IGNORECASE,
)


def _requires_contextual_hypothesis_evidence(text: str) -> bool:
    """Recognise requests to derive corpus hypotheses from visible evidence."""

    lowered = _normalised_question_text(text)
    return bool(
        re.search(r"\bhypothese\w*\b", lowered, re.IGNORECASE)
        and _HYPOTHESIS_GENERATION_ACTION_PATTERN.search(lowered)
        and _HYPOTHESIS_EVIDENCE_CUE_PATTERN.search(lowered)
    )


def _is_exploratory_prompt(text: str) -> bool:
    # recipe_runtime.stage1_recipe_decision passes its own normalised text,
    # so the English reading happens here as well (idempotent on a text that
    # is already routed).
    text = routing_text(text)
    if _requires_contextual_hypothesis_evidence(text):
        return True
    if _has_any_phrase(
        text,
        (
            "welche themen",
            "welche thematischen",
            "zentrale themen",
            "thematisch zentral",
            "besonders zentral",
            "interessante dinge",
            "interessante sachen",
            "was faellt",
            "was fällt",
            "welche fragen",
            "anschlussfragen",
            "anschlussfrage",
            "forschungsfragen",
            "ergeben sich aus diesem korpus",
            "über dieses korpus",
            "über dieses korpus",
            "insgesamt auf",
            "gib mir einen überblick",
            "gib mir einen überblick",
        ),
    ):
        return True
    # Open corpus requests admit arbitrary modifiers between the intent and
    # noun ("interessante, direkt belegte Sachen"). Detect the research intent
    # rather than enumerating exact phrasings.
    return _has_any_phrase(text, ("korpus", "corpus")) and _has_any_phrase(
        text,
        (
            "interessant",
            "auffällig",
            "bemerkenswert",
            "beobachtung",
            "befund",
            "überblick",
            "erkunden",
            "explor",
        ),
    )


def _is_theme_overview_prompt(text: str) -> bool:
    return _has_any_phrase(
        text,
        (
            "welche themen",
            "welche thematischen",
            "zentrale themen",
            "thematisch zentral",
            "besonders zentral",
            "welche themen wirken",
            "themen wirken",
            "woran erkennt man das",
        ),
    )


def _is_method_help_prompt(text: str) -> bool:
    return _has_any_phrase(
        text,
        (
            "erste analyseschritte",
            "erste analyse schritte",
            "analyseschritte",
            "erste schritte",
            "welche ersten",
            "würdest du empfehlen",
            "würdest du empfehlen",
            "wie würdest du anfangen",
            "wie würdest du anfangen",
            "neu bekaemst",
            "neu bekämst",
            "wie anfangen",
            "erste drei schritte",
            "erste drei analyseschritte",
            "methodisch sinnvoll anfangen",
        ),
    )


def _is_confirmation_pressure_prompt(text: str) -> bool:
    """Detect requests that demand one-sided support for a corpus-wide claim."""

    text = _normalised_question_text(text)
    corpus_request = _has_any_phrase(text, ("korpus", "corpus"))
    confirmation = _has_any_phrase(
        text,
        (
            "bestätige",
            "bestaetige",
            "bestätigung",
            "bestaetigung",
            "beweise",
            "confirm",
            "prove",
        ),
    )
    padded = f" {text} "
    absolute_or_one_sided = _has_any_phrase(
        padded,
        (
            " immer ",
            " nie ",
            " ausnahmslos ",
            " ausschließlich passende",
            "ausschliesslich passende",
            "nur passende belege",
            "only supporting evidence",
            " always ",
            " never ",
        ),
    )
    return corpus_request and confirmation and absolute_or_one_sided


_CONFIRMATION_BOUNDARY_SCOPE_PATTERN = re.compile(
    r"\b(?:behauptung|these|aussage|schlussfolgerung|"
    r"immer|nie|ausnahmslos|ausschließlich|ausschliesslich|"
    r"gesamtkorpus|gesamt(?:e[snr]?\s+)?korpus|korpusweit|universell|"
    r"das|dies(?:e|er|es)?)\b",
    re.IGNORECASE,
)
_CONFIRMATION_BOUNDARY_NEGATION_PATTERN = re.compile(
    r"\b(?:nicht|kein(?:e|en|em|er|es)?|weder|ohne)\b",
    re.IGNORECASE,
)
_CONFIRMATION_BOUNDARY_INFERENCE_PATTERN = re.compile(
    r"\b(?:bestätig\w*|bestaetig\w*|beleg\w*|beweis\w*|"
    r"nachweis\w*|nachgewies\w*|ableit\w*|schließ\w*|schliess\w*|"
    r"schluss\w*|folger\w*|feststell\w*|stütz\w*|stuetz\w*)\b",
    re.IGNORECASE,
)
_CONFIRMATION_BOUNDARY_UNSUPPORTED_PATTERN = re.compile(
    r"\b(?:unbelegt\w*|unbewies\w*|unbestätig\w*|unbestaetig\w*|"
    r"nicht\s+nachgewies\w*|reicht?\w*\s+[^.!?\n]{0,80}\s+nicht\s+aus)\b",
    re.IGNORECASE,
)


def _accepted_claims_reject_confirmation_pressure(
    claims: Sequence[ClaimDraft],
) -> bool:
    """Require an explicit answer to a requested universal confirmation."""

    for claim in claims:
        for sentence in re.split(r"(?<=[.!?;])\s+", claim.text or ""):
            if not _CONFIRMATION_BOUNDARY_SCOPE_PATTERN.search(sentence):
                continue
            if _CONFIRMATION_BOUNDARY_UNSUPPORTED_PATTERN.search(sentence):
                return True
            if (
                _CONFIRMATION_BOUNDARY_NEGATION_PATTERN.search(sentence)
                and _CONFIRMATION_BOUNDARY_INFERENCE_PATTERN.search(sentence)
            ):
                return True
    return False


def _is_comparative_prompt(text: str) -> bool:
    return _has_any_phrase(
        text,
        (
            "unterschiede zwischen",
            # "unterscheid" trifft unterscheidet und unterscheiden, aber
            # NICHT Unterschied oder Unterschiede: das schreibt sich
            # unterschIEd. Fuer die fing bis zum 2026-08-31 allein
            # "unterschiede zwischen", also nur mit folgendem Wort.
            #
            # Live gesehen: "analysiere die sprachlichen Unterschiede" galt
            # damit als NICHT komparativ, fiel durch jeden Kontrastzweig
            # und landete im Metadatenvertrag. Der Copilot lieferte nach
            # 502 Sekunden ein Inventar der Metadatenfelder.
            "unterschied",
            "unterscheid",
            "differenz",
            # "im vergleich" verlangte das "im". Das blosse "Vergleiche die
            # Modelle stilistisch" galt damit als nicht komparativ.
            "vergleich",
            "kontrast",
            "arbeite drei unterschiede",
            "human- und ai",
            "human und ai",
            "ai-teil",
            "human-teil",
            "subkorpusvergleich",
        ),
    )


_DOCSET_COMPARATIVE_PHRASES: tuple[str, ...] = (
    # German A-vs-B / subcorpus comparison phrasing (no human/AI wording required).
    "vergleiche",
    "vergleich von",
    "vergleich zwischen",
    "vergleich der",
    "unterschied zwischen",
    "unterschiede zwischen",
    "unterscheid",
    "differenz",
    "gegenüber",
    "gegenüber",
    "kontrastiere",
    "im kontrast zu",
    "subkorpus",
    "subkorpora",
    "teilkorpus",
    "teilkorpora",
    "docset",
    # English equivalents.
    " vs ",
    " vs. ",
    "versus",
    "compare ",
    "comparison",
    "difference between",
    "differences between",
    "contrast ",
)


def _has_explicit_comparison_pair(text: str) -> bool:
    """Return whether a comparison names both sides rather than a broad class."""

    return bool(
        re.search(r"\b(?:vs\.?|versus)\b", text)
        or " gegenüber " in f" {text} "
        or re.search(r"\bzwischen\b.{1,100}\bund\b", text)
        or (
            _has_any_phrase(text, ("vergleiche", "vergleich", "kontrastiere"))
            # "vergleiche X mit Y" war die einzige erkannte Paarform. Das
            # ebenso normale "vergleiche die Sprache VON Menschen UND KI"
            # fiel durch. Der mit-Fall bleibt wie er war: ihn ebenfalls an
            # ein "und" zu binden, hat "vergleiche subkorpus news mit
            # subkorpus blog" herausgeworfen.
            and (
                re.search(r"\bmit\b", text)
                or re.search(r"\bvon\b.{1,100}\bund\b", text)
            )
        )
    )


# Metadata fields that can identify comparison axes, in matching order.
_KONTRASTACHSEN: tuple[str, ...] = (
    "modell", "model", "variante", "variant", "fassung", "version",
    "register", "quelle", "source", "genre", "subkorpus", "teilkorpus",
)


def _ist_achsenkontrast(text: str) -> bool:
    """Eine Achse nennen und nach Unterschieden oder Typik fragen IST ein Kontrast.

    Zwei Formen, beide ohne das Wort "vergleiche":

    * "die Unterschiede der MODELLE" nennt die Achse und fragt nach
      Unterschieden ueber alle ihre Werte, nicht ueber ein Paar.
    * "was ist TYPISCH fuer das Register X" ist die Definition von Keyness,
      also ein Kontrast von X gegen den Rest.

    Beide galten bis zum 2026-08-31 als nicht komparativ und landeten im
    Feldinventar, weil sie eine Metadatenachse beim Namen nennen und der
    Metadatenzweig genau darauf ausloest.
    """
    if not _has_any_phrase(text, _KONTRASTACHSEN):
        return False
    return _is_comparative_prompt(text) or _has_any_phrase(
        text, ("typisch", "charakterist", "eigenheit", "auffällig", "besonderheit")
    )


def _is_docset_comparative_prompt(text: str) -> bool:
    """Generic A-vs-B/subcorpus comparison detector (no human/AI wording required)."""
    if _has_any_phrase(text, _DOCSET_COMPARATIVE_PHRASES):
        return True
    # Naming an axis and asking about differences implies a contrast.
    # Recognize this before a metadata-inventory cue captures the same axis name.
    return _ist_achsenkontrast(text)


def _is_broad_comparative_profile_prompt(text: str) -> bool:
    return _is_comparative_prompt(text) and _has_any_phrase(
        text,
        (
            "insgesamt",
            "am plausibelsten",
            "im korpus insgesamt",
            "welche unterschiede",
            "welche merkmale",
            "welche profile",
        ),
    )


def _is_human_ai_contrast_prompt(text: str) -> bool:
    # Match AI as a standalone label. A substring test misclassified ordinary
    # words such as "Ukraine" and routed unrelated corpus comparisons into the
    # legacy human-vs-AI tool bundle.
    #
    # DEUTSCH gehoert hier NICHT hinein, und der Versuch am 2026-08-31 hat
    # gezeigt warum. Dieser Erkenner schaltet auf den ALTPFAD
    # ``compare_collocates``, und der verlangt ein GEPAARTES Korpus. Der
    # generische Kontrastzweig daneben (contrast_collocates, keyness und
    # sechs weitere) laeuft auf jedem Korpus und faengt deutsche
    # Mensch-KI-Fragen ohnehin ueber die Paarform "zwischen A und B".
    #
    # Der Versuch hat ausserdem "Vergleiche die Kollokationen von 'Mensch'
    # zwischen den Registern news und blog" gefangen: dort ist Mensch das
    # ZITIERTE SUCHWORT und die Achse sind die Register. Ein Knotenwort
    # darf nie die Kontrastachse bestimmen, dieselbe Lehre steht in
    # same_corpus_collocation_terms.
    return _is_comparative_prompt(text) and bool(
        re.search(r"\b(?:human|ai)\b", text, flags=re.IGNORECASE)
    )


def same_corpus_collocation_terms(question_text: str) -> List[str]:
    """Extract the compared lexical nodes, excluding quoted corpus labels."""

    text = routing_text(question_text)
    if not (
        re.search(r"\bkollokat\w*\b", text, re.IGNORECASE)
        and _has_any_phrase(
            text,
            ("vergleiche", "vergleich", "gegenüber", "gegenueber", " vs ", "versus"),
        )
        and not _has_any_phrase(
            text,
            (
                "subkorpus",
                "subkorpora",
                "teilkorpus",
                "teilkorpora",
                "docset",
                "registervergleich",
                "zwischen den registern",
                "splitvergleich",
            ),
        )
        and not _is_human_ai_contrast_prompt(text)
    ):
        return []

    quoted = list(re.finditer(
        r"[\"'`„“‚‘]([^\"'`„“‚‘]{1,80})[\"'`„“‚‘]",
        question_text or "",
    ))
    clusters: List[List[str]] = []
    current: List[str] = []
    previous_end = -1
    for match in quoted:
        term = _normalise_example_text(match.group(1))
        if not term:
            continue
        connector = (
            str(question_text or "")[previous_end : match.start()]
            if previous_end >= 0
            else ""
        )
        linked = bool(
            current
            and re.fullmatch(
                r"\s*(?:(?:,|;)\s*)?(?:(?:und|sowie|oder|vs\.?|versus|"
                r"gegenüber|gegenueber|mit)\s*)?",
                connector,
                re.IGNORECASE,
            )
        )
        if not linked and current:
            clusters.append(current)
            current = []
        # Use str.lower like the counter so daß and dass remain distinct terms.
        if term.lower() not in {value.lower() for value in current}:
            current.append(term)
        previous_end = match.end()
    if current:
        clusters.append(current)
    quoted_terms = max(
        (cluster for cluster in clusters if len(cluster) >= 2),
        key=len,
        default=[],
    )
    if quoted_terms:
        return quoted_terms[:4]

    lexical = r"[0-9A-Za-zÄÖÜäöüß][0-9A-Za-zÄÖÜäöüß_-]{0,79}"
    pair_patterns = (
        rf"\b(?:wortformen?|oberflächenformen?|oberflaechenformen?|"
        rf"flexionsformen?|lemmata|kollokationsprofile?)\b\s*"
        rf"(?:der|von|für|fuer)?\s*(?P<a>{lexical})\s+"
        rf"(?:und|vs\.?|versus|gegenüber|gegenueber)\s+(?P<b>{lexical})",
        rf"\bkollokationen?\b\s+(?:von|für|fuer)\s+(?P<a>{lexical})\s+"
        rf"(?:und|vs\.?|versus|gegenüber|gegenueber)\s+(?P<b>{lexical})",
        rf"\bvergleiche\s+(?P<a>{lexical})\s+(?:und|vs\.?|versus|"
        rf"gegenüber|gegenueber)\s+(?P<b>{lexical})\s+"
        rf"(?:hinsichtlich|bezüglich|bezueglich).{{0,80}}\bkollokat",
    )
    for pattern in pair_patterns:
        match = re.search(pattern, question_text or "", re.IGNORECASE)
        if match is not None:
            return [
                _normalise_example_text(match.group("a")),
                _normalise_example_text(match.group("b")),
            ]
    return []


def same_corpus_collocation_method_requirements(
    question_text: str,
) -> Dict[str, Any]:
    """Return only method parameters the user stated explicitly."""

    text = _normalised_question_text(question_text)
    requirements: Dict[str, Any] = {}
    window_match = re.search(
        r"\b(?:window|fenster(?:größe|groesse)?)\s*(?:=|:|von)?\s*"
        r"(?:[+\-±]\s*)?(\d{1,3})\b",
        text,
    )
    if window_match:
        requirements["window"] = max(1, int(window_match.group(1)))
    min_freq_match = re.search(
        r"\b(?:min[_ -]?freq|min(?:imum)?\s+frequency|mindestfrequenz|"
        r"aufnahmeschwelle)\s*(?:=|:|von)?\s*(\d+)\b",
        text,
    )
    if min_freq_match:
        requirements["min_freq"] = int(min_freq_match.group(1))
    measure_match = re.search(
        r"\b(?:sort[_ -]?by|sortier(?:ung|maß|mass)|measure|maß|mass|nach)"
        r"\s*(?:=|:|nach)?\s*([a-z][a-z0-9_]*)\b",
        text,
    )
    if measure_match:
        requirements["sort_by"] = measure_match.group(1).casefold()
    attribute_match = re.search(
        r"\b(?:attribute|attribut)\s*(?:=|:)\s*(word|lemma)\b",
        text,
    )
    if attribute_match:
        requirements["attribute"] = attribute_match.group(1).casefold()
    elif re.search(r"\b(?:lemmata|lemmaebene|lemma-ebene)\b", text):
        requirements["attribute"] = "lemma"
    elif re.search(
        r"\b(?:wortformen?|oberflächenformen?|oberflaechenformen?|flexionsformen?)\b",
        text,
    ):
        requirements["attribute"] = "word"
    if re.search(
        r"\bwithin[_ -]?sentence\s*(?:=|:)\s*false\b|"
        r"\b(?:satzübergreifend|satzuebergreifend|über\s+satzgrenzen|"
        r"ueber\s+satzgrenzen)\b",
        text,
    ):
        requirements["within_sentence"] = False
    elif re.search(
        r"\bwithin[_ -]?sentence\s*(?:=|:)\s*true\b|"
        r"\b(?:satzbegrenzt|innerhalb\s+(?:eines|des)\s+satzes)\b",
        text,
    ):
        requirements["within_sentence"] = True
    return requirements


def _requests_complementary_evidence(text: str) -> bool:
    """Detect an explicit request to triangulate distinct evidence paths."""

    lowered = routing_text(text)
    return bool(
        _has_any_phrase(
            lowered,
            (
                "methodisch komplementär",
                "methodisch komplementaer",
                "komplementäre evidenz",
                "komplementaere evidenz",
                "verschiedene evidenzarten",
                "unterschiedliche evidenzarten",
                "mehrere evidenzarten",
                "triangulier",
                "methodological triangulation",
                "complementary evidence",
            ),
        )
        or (
            _has_any_phrase(lowered, ("evidenzart", "methode", "zugang"))
            and _has_any_phrase(
                lowered,
                ("übereinstimmung", "uebereinstimmung", "widerspruch"),
            )
        )
    )


def _heuristic_tool_bundle(
    names: Sequence[str],
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> List[str]:
    available = {str(item) for item in available_tools if str(item).strip()}
    read_only = {str(item) for item in read_only_tools if str(item).strip()}
    ordered: List[str] = []
    seen: set[str] = set()
    for name in names:
        if name in available and name in read_only and name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def _method_help_required_evidence(bundle: Sequence[str]) -> List[str]:
    required: List[str] = []
    if "metadata_values" in bundle:
        required.append("metadata_rows")
    if "frequency_list" in bundle:
        required.append("content_rows")
    if any(
        tool in bundle
        for tool in (
            "run_cqlf_query",
            "document_search",
            "semantic_search",
            "semantic_cluster",
            "semantic_cluster_words",
        )
    ):
        required.append("contextual_rows")
    if not required and "semantic_search" in bundle:
        required.append("semantic_rows")
    return required


def _contrast_required_evidence(bundle: Sequence[str], question_text: str) -> List[str]:
    lowered = routing_text(question_text)
    required = ["metric_rows"]
    if _is_broad_comparative_profile_prompt(lowered):
        if "frequency_list" in bundle:
            required.append("frequency_rows")
    if "metadata_values" in bundle and (
        _is_broad_comparative_profile_prompt(lowered)
        or _is_human_ai_contrast_prompt(lowered)
    ):
        required.append("metadata_rows")
    if "run_cqlf_query" in bundle and _has_any_phrase(
        lowered, ("kwic", "kontext", "konkordanz")
    ):
        required.append("kwic_rows")
    if "query_count" in bundle and _has_any_phrase(
        lowered, ("häufig", "wie oft", "frequenz", "normalis")
    ):
        required.append("total_hits")
    return required


def _kwic_kontrakt(
    question_text: str,
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    """Der Belegkontrakt der Familie ``kwic_context``, EINE Wahrheit.

    Zwei Zweige bauen ihn: der KWIC-Cue-Zweig ("kwic", "Kontext",
    "Konkordanz") und der Frageform-Zweig fuer den Konstruktions-
    Suchauftrag. Als der zweite ihn nachbaute statt ihn zu rufen, verlor
    er die Kontexterweiterung: die Probe
    test_explicit_context_expansion_requires_kwic_context_tool fiel mit
    ``['run_cqlf_query']`` statt ``['run_cqlf_query', 'kwic_context']``,
    weil "erweitere den Kontext" nur im aelteren Zweig steht.
    """
    if "run_cqlf_query" not in set(available_tools):
        return None
    lowered = routing_text(question_text)
    needs_expanded_context = (
        "kwic_context" in set(available_tools)
        and _has_any_phrase(
            lowered,
            (
                "erweitere",
                "erweiterter kontext",
                "weiterer kontext",
                "breiterer kontext",
                "vollständiger kontext",
                "vollstaendiger kontext",
            ),
        )
    )
    bundle = _heuristic_tool_bundle(
        (
            "run_cqlf_query",
            *(["kwic_context"] if needs_expanded_context else []),
        ),
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )
    if not bundle:
        return None
    # Das Praedikat ist ``frage_ist_blosses_nachschlagen`` und nicht mehr
    # ``_explicit_interpretation_request``. Die Vorzeichen sind vertauscht:
    # nicht die Deutung muss sich anmelden, sondern das Nachschlagen. Wer
    # nichts von beidem sagt, bekommt ``bounded_analysis``. Die Umkehr gilt
    # in dieser Datei ueberall, das alte Praedikat ist hier nicht mehr
    # importiert.
    nachschlagen = frage_ist_blosses_nachschlagen(question_text)
    return AnalysisContract(
        mode="tool_analysis",
        track="lookup" if nachschlagen else "bounded_analysis",
        analysis_family="kwic_context",
        deliverable_kind="lookup_answer" if nachschlagen else "analysis_report",
        question_scope=_compact_text(question_text, 220),
        allowed_tools=bundle,
        required_evidence=[
            "kwic_rows",
            *(["expanded_context"] if needs_expanded_context else []),
        ],
        forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
        response_shape="grounded_kwic_presence",
    )


def heuristic_analysis_contract(
    question_text: str,
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
    rezept_id: str = "",
    rezept_stufe: str = "",
) -> AnalysisContract | None:
    """Kontrakt aus Cues und Rezept, danach der Termlisten-Modus.

    Die Huelle liegt HIER und nicht in einem der Zweige, weil sieben
    Stellen dieser Datei einen ``contrast_keyness``-Kontrakt bauen. Ein
    Termlisten-Modus, der nur in einer davon steht, ist an den uebrigen
    sechs nicht vorhanden. Gemessen am 2026-09-02: die Markerfrage lief
    ueber den Rezept-Rueckfall, eine Kandidatenliste in einer Frage mit
    Kontrast-Cue ("typisch fuer", "vs") liefe ueber einen Cue-Zweig.
    """
    kontrakt = _heuristic_analysis_contract(
        question_text,
        available_tools=available_tools,
        read_only_tools=read_only_tools,
        rezept_id=rezept_id,
        rezept_stufe=rezept_stufe,
    )
    kontrakt = _mit_termlisten_modus(kontrakt, question_text, available_tools)
    return _mit_rezeptraum(
        kontrakt,
        rezept_id=rezept_id,
        rezept_stufe=rezept_stufe,
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )


def _mit_rezeptraum(
    kontrakt: AnalysisContract | None,
    *,
    rezept_id: str,
    rezept_stufe: str,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    """Ensure the contract includes the selected recipe's available tools.

    Apply this when the classifier or question-form stage selected a recipe
    from the whole question. Keep the cue branch's family, deliverable,
    required evidence and answer form, with its tools first. Additional
    recipe tools make the prescribed operations possible without introducing
    new evidence requirements.
    """

    if kontrakt is None or kontrakt.mode != "tool_analysis":
        return kontrakt
    if str(rezept_stufe or "").strip().lower() not in (
        "llm",
        ROUTING_STAGE_FRAGEFORM,
    ):
        return kontrakt
    rezept = RECIPES_BY_ID.get(str(rezept_id or ""))
    if rezept is None:
        return kontrakt
    raum = _heuristic_tool_bundle(
        tuple(rezept.kern_tools)
        + tuple(getattr(rezept, "wegbereiter_tools", ()) or ()),
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )
    fehlend = [name for name in raum if name not in kontrakt.allowed_tools]
    if fehlend:
        kontrakt.allowed_tools = [*kontrakt.allowed_tools, *fehlend]
    return kontrakt


def _mit_termlisten_modus(
    kontrakt: AnalysisContract | None,
    question_text: str,
    available_tools: Sequence[str],
) -> AnalysisContract | None:
    """Kandidatenliste im Kontrastvertrag: Zaehlwerkzeug und Zaehlevidenz.

    Der Vertrag der Markerfrage gab am 2026-09-02 keyness, metadata_values,
    create_docset und list_docsets frei und verlangte ``metric_rows``. Beides
    zusammen liess dem Turn nur die globale Keyness ueber 389.305 Zeilen, in
    deren sichtbarer Spitze keiner der sieben Kandidaten stand.

    Drei Bauer laufen durch diese Huelle, und der gemessene Fall lief durch
    den dritten: ``harnisch_nachher.jsonl`` traegt fuer den Turn
    ``stage=llm recipe=kontrast`` mit ``analysis_family=contrast_keyness``,
    der Vertrag kam also aus ``AnalysisContract.from_raw``. Der
    heuristische Pfad ergibt fuer denselben Fragetext ueberhaupt keinen
    Kontrastvertrag (dreimal ``metadata_capability`` mit
    ``allowed_tools=['metadata_values']``, ueber alle drei Rezeptstufen
    gemessen), und ``fallback_analysis_contract`` ist der Zweitweg von
    ``tooling/tool_selection.py:437``.
    """
    if kontrakt is None or kontrakt.analysis_family != "contrast_keyness":
        return kontrakt
    if kontrakt.mode != "tool_analysis":
        # Eine Rueckfrage hat keinen Werkzeugraum, dem query_count
        # hinzuzufuegen waere, und keine Evidenzpflicht zu erfuellen.
        return kontrakt
    if not ist_kandidatenliste(question_text):
        return kontrakt
    bundle = list(kontrakt.allowed_tools)
    if "query_count" not in bundle and "query_count" in set(available_tools):
        bundle.append("query_count")
    kontrakt.allowed_tools = bundle
    kontrakt.required_evidence = kandidatenlisten_evidenz(
        kontrakt.required_evidence, bundle
    )
    return kontrakt


def _heuristic_analysis_contract(
    question_text: str,
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
    rezept_id: str = "",
    rezept_stufe: str = "",
) -> AnalysisContract | None:
    # English questions are read in the German cue vocabulary
    # (candyconc.question_language), German ones exactly as before.
    lowered = routing_text(question_text)

    # Use the recipe decision before incidental keyword cues when a model
    # classifier or question-form rule selected it from the whole question.
    # This keeps the contract's tools consistent with the selected recipe.
    # Selections made by ordinary triggers retain the existing cue precedence.
    if str(rezept_stufe or "").strip().lower() in (
        "llm",
        ROUTING_STAGE_FRAGEFORM,
    ):
        aus_rezept = _kontrakt_aus_rezept(
            rezept_id,
            question_text=question_text,
            lowered=lowered,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if aus_rezept is not None:
            return aus_rezept
    if not lowered:
        return None

    # DIE FRAGEFORM ENTSCHEIDET IN BEIDEN ROUTERN ODER IN KEINEM.
    #
    # ``select_recipe`` gibt dem Konstruktions-Suchauftrag Vorrang und
    # waehlt ``gebrauch_kwic``. Der Kontrakt kam trotzdem aus den
    # Cue-Zweigen, und die schweigen bei konstr-scharnier-dreigliedrig
    # ueber die Suchform: gemessen mit allen 15 Werkzeugen im Raum ergab
    # sich analysis_family 'term_frequency' mit allowed_tools
    # ['frequency_list'], waehrend das gewaehlte Rezept ``run_cqlf_query``
    # als einziges Kernwerkzeug fuehrt. Ein Kontrakt, der das Kernwerkzeug
    # des gewaehlten Rezepts nicht freigibt, ist die Lage, die am
    # 2026-09-01 einen Turn 825 Sekunden stillstehen liess.
    #
    # Der Rezeptvorrang ``_kontrakt_aus_rezept`` kann das nicht heilen:
    # ``kwic_context`` fehlt in ``_FAMILIEN_KONTRAKT`` mit gemessenem
    # Grund (die abgeleitete Fassung machte aus der Gebrauchsanalyse einen
    # Ja/Nein-Bestandsrahmen). Also entscheidet hier dasselbe Praedikat
    # wie dort, und der Kontrakt ist derselbe, den der KWIC-Cue-Zweig
    # weiter unten baut.
    #
    # DER REZEPTRAUM GEHT VOR DEM BLANKEN BELEGKONTRAKT. Dieser Zweig
    # steht VOR den Cue-Zweigen, und dort unten sass bisher die einzige
    # Delegation an das gewaehlte Rezept. Ohne dieselbe Delegation hier
    # nimmt die Frageform dem Rezept den Werkzeugraum weg, und zwar
    # ausgerechnet bei ``stage='heuristik'``, wo der frueh gezogene
    # ``_kontrakt_aus_rezept`` oben nicht greift: konstr-korrelat-fenster
    # bekam ``['run_cqlf_query']`` mit Pflichtevidenz ``['kwic_rows']``
    # statt der fuenf Werkzeuge des Rezepts mit ``total_hits``. Die
    # Familie ``kwic_context`` ist die Schranke, die Frageform behaelt
    # also ihre Entscheidung, nur die Ausfuehrung kommt aus dem Rezept.
    if ist_konstruktions_suchauftrag(question_text):
        aus_rezeptraum = _normierung_statt_bestand(
            question_text,
            lowered=lowered,
            rezept_id=rezept_id,
            familie="kwic_context",
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if aus_rezeptraum is not None:
            return aus_rezeptraum
        aus_frageform = _kwic_kontrakt(
            question_text,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if aus_frageform is not None:
            return aus_frageform
    # Fuer den Abgleich der Umfeld-Cues, und NUR dafuer: der Fragetext
    # ohne die zitierten Suchbegriffe. Sonst trifft ein Cue im Suchterm,
    # und „Zaehle die Treffer fuer 'im Umfeld der Bundesregierung'“ wird
    # zur Kollokationsfrage.
    ohne_zitate = (
        routing_text(without_quoted_terms(question_text))
        if is_english_question(question_text)
        else _normalised_question_text(ohne_zitierte_terme(question_text))
    )
    # Der Ausschluss haengt AM SIGNAL, nicht an einem einzelnen Zweig.
    # Sonst muesste ihn jeder Verbraucher wiederholen, und wer ihn
    # vergisst, holt den Defekt zurueck: eine Dispersionsfrage mit
    # Umfeldphrase wurde so vom Profilzweig eingefangen, obwohl der
    # Kollokationszweig sie korrekt abgelehnt hatte.
    hat_umfeld_cue = _has_any_phrase(
        ohne_zitate, _UMFELD_CUES
    ) and not _has_any_phrase(lowered, _UMFELD_AUSSCHLUSS)

    if _is_confirmation_pressure_prompt(lowered):
        bundle = _heuristic_tool_bundle(
            (
                "run_cqlf_query",
                "semantic_search",
                "document_search",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if any(
            tool in bundle
            for tool in (
                "semantic_search",
                "document_search",
                "run_cqlf_query",
            )
        ):
            return AnalysisContract(
                mode="tool_analysis",
                track="exploratory_research",
                analysis_family="open_research",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[
                    *(
                        ["total_hits"]
                        if "run_cqlf_query" in bundle
                        else []
                    ),
                    *(
                        ["semantic_rows"]
                        if "semantic_search" in bundle
                        else (
                            ["contextual_rows"]
                            if "document_search" in bundle
                            else []
                        )
                    ),
                ],
                forbidden_claims=[
                    *DEFAULT_FORBIDDEN_CLAIMS,
                    "one-sided confirmation of a universal corpus claim",
                    "universal conclusion from bounded evidence",
                ],
                response_shape="grounded_exploratory_report",
            )

    if _requests_complementary_evidence(lowered):
        # Couple an exact lexical measurement with an independent contextual
        # retrieval path. The contract chooses evidence classes, not findings:
        # the model remains free to select arguments and interpret agreement
        # or tension between the resulting observations.
        usable_tools = set(available_tools).intersection(read_only_tools)
        exact_tool = next(
            (
                name
                for name in ("query_count", "run_cqlf_query")
                if name in usable_tools
            ),
            "",
        )
        contextual_candidates = (
            "semantic_search",
            "document_search",
            "run_cqlf_query",
        )
        contextual_tool = next(
            (
                name
                for name in contextual_candidates
                if name in usable_tools and name != exact_tool
            ),
            exact_tool,
        )
        bundle = _heuristic_tool_bundle(
            (
                exact_tool,
                contextual_tool,
                "collocate_stats",
                "word_sketch",
                "dispersion_offsets",
                "frequency_list",
                "metadata_values",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if exact_tool and contextual_tool:
            return AnalysisContract(
                mode="tool_analysis",
                track="exploratory_research",
                analysis_family="open_research",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[
                    "total_hits",
                    "contextual_rows",
                ],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_triangulated_analysis",
            )

    # Dedicated statistical operations must win over generic lexical cues.
    # These branches only select the requested measurement; the model remains
    # responsible for parameters, interpretation and presentation.
    if (
        "ngram_frequency" in set(available_tools)
        and not (
            re.search(
                r"""['\"„»]([^'\"„“»«]{2,80})['\"“»«]""",
                question_text or "",
            )
            and _has_any_phrase(
                lowered,
                ("exakte wortfolge", "lokalisiere", "kontext"),
            )
        )
        and _has_any_phrase(
            lowered,
            (
                "n-gram",
                "ngram",
                "wortfolge",
                "mehrwortfolge",
                "zweiwortfolge",
                "dreiwortfolge",
                "formulierungsroutine",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("create_docset", "ngram_frequency"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "ngram_frequency" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="ngram_profile",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_ngram_profile",
            )

    if (
        "lexical_diversity" in set(available_tools)
        and _has_any_phrase(
            lowered,
            (
                "lexikalische diversität",
                "lexikalische diversitaet",
                "type-token-ratio",
                "type token ratio",
                "ttr",
                "sttr",
                "mattr",
                "guiraud",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("create_docset", "lexical_diversity"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "lexical_diversity" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="lexical_diversity",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_lexical_diversity",
            )

    if (
        "metadata_values" in set(available_tools)
        and _has_any_phrase(
            lowered,
            (
                "über die zeit",
                "ueber die zeit",
                "zeitverlauf",
                "zeitachse",
                "zeitreihe",
                "diachron",
                "trend",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("metadata_values", "create_docset", "trend_analysis"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "metadata_values" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="trend_analysis",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[
                    "metadata_rows",
                    *(["metric_rows"] if "trend_analysis" in bundle else []),
                ],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_trend_analysis",
            )

    if (
        "metadata_values" in set(available_tools)
        and "register" in lowered
        and _requested_register_value(question_text)
        and _has_any_phrase(
            lowered,
            ("suche", "finde", "treffer", "kwic", "analys"),
        )
    ):
        bundle = _heuristic_tool_bundle(
            (
                "metadata_values",
                "create_docset",
                "query_count",
                "run_cqlf_query",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "metadata_values" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="kwic_context",
                # Die Lieferart entscheidet die ECHTE Frage, nicht das auf
                # 220 Zeichen gekuerzte Abbild im Kontrakt. _compact_text
                # faltet Leerraum vor dem Kuerzen: gemessen am 2026-09-02
                # liegt die 173-Zeichen-Frage aus _UMBRUCHFRAGEN
                # ("metadaten_beleg", mit Umbruechen und Einrueckung)
                # danach bei 157 Zeichen, also unter der Schranke, und
                # kippte damit auf Nachschlagen zurueck.
                deliverable_kind=(
                    "lookup_answer"
                    if frage_ist_blosses_nachschlagen(question_text)
                    else "analysis_report"
                ),
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[
                    "metadata_rows",
                    *(["kwic_rows"] if "run_cqlf_query" in bundle else []),
                ],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_kwic_presence",
            )

    if (
        "keyness" in set(available_tools)
        and (
            _has_any_phrase(lowered, ("keyness", "schlüsselwört", "schluesselwoert"))
            or (
                _has_any_phrase(lowered, ("lexikalisch", "wortschatz"))
                and _has_any_phrase(lowered, ("split", "partition", "teilkorpus"))
            )
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("metadata_values", "create_docset", "keyness", "frequency_list"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "keyness" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[
                    *(["metadata_rows"] if "metadata_values" in bundle else []),
                    "metric_rows",
                ],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    # K1-Regression (Live-P3): Eine Zufallsstichproben-Anfrage (optional mit
    # Seed) ist eine einfache Werkzeug-Anfrage und bekommt IMMER einen
    # Heuristik-Kontrakt. Sie darf nie in den LLM-Klassifikator laufen und
    # dort als contract_failed_closed abgewiesen werden. Die Stichprobe wird
    # ueber run_cqlf_query (sample/seed-Parameter) gezogen; der Seed wird in
    # der Antwort ausgewiesen (kwic_context-Renderer).
    if (
        "run_cqlf_query" in set(available_tools)
        and (
            _has_any_phrase(
                lowered,
                (
                    "stichprobe",
                    "zufallsstichprobe",
                    "zufallsauswahl",
                    "random sample",
                    "sample ",
                ),
            )
            or (
                "seed" in lowered
                and _has_any_phrase(
                    lowered,
                    (
                        "treffer",
                        "beispiele",
                        "belege",
                        "kwic",
                        "konkordanz",
                        "ziehe",
                        "zieh ",
                    ),
                )
            )
        )
        and not _has_any_phrase(
            lowered,
            (
                "kollok",
                "word sketch",
                "wortprofil",
                "keyness",
                "dispersion",
                "vergleich",
                "unterschied",
                "frequenzliste",
                "wortliste",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("run_cqlf_query", "query_count"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "run_cqlf_query" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track=(
                    "lookup"
                    if frage_ist_blosses_nachschlagen(question_text)
                    else "bounded_analysis"
                ),
                analysis_family="kwic_context",
                deliverable_kind=(
                    "lookup_answer"
                    if frage_ist_blosses_nachschlagen(question_text)
                    else "analysis_report"
                ),
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["kwic_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_kwic_presence",
            )

    # Exact count intent must precede the broader "kommt ... vor" presence
    # route; otherwise requests for rate and denominator are irreversibly
    # narrowed to a KWIC lookup before query_count is exposed.
    if (
        "query_count" in set(available_tools)
        and _has_any_phrase(
            lowered,
            ("häufig", "haeufig", "frequenz", "wie oft", "trefferzahl", "pro million", "nenner"),
        )
        and re.search(r"""['"„»]([^'"„“»«]{2,40})['"“»«]""", question_text or "")
        # Apply the context-query exclusion here as well as in the frequency
        # branch so changing quotation marks cannot change the analysis route.
        and not hat_umfeld_cue
        and not _has_any_phrase(
            lowered,
            (
                "häufigste",
                "haeufigste",
                "wortliste",
                "top",
                "rangliste",
                "kollok",
                "word sketch",
                "wortprofil",
                "metadat",
                "subkorpus",
                "vergleich",
                "liste",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            # P2.4: ohne dispersion_offsets im Bundle verwirft der
            # Vorplan-Filter den Dispersionsschritt still.
            # P1 (Runde 3): metadata_values im Raum — die Achsen-Erkundung
            # (Registerverteilung als Nenner-Grundlage) war sonst ein
            # Unmöglichkeits-Befund, während das Werkzeug sie liefert
            # (Messung A5).
            ("query_count", "dispersion_offsets", "frequency_list",
             "run_cqlf_query", "metadata_values",
             "create_docset", "list_docsets"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "query_count" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="lookup",
                analysis_family="term_frequency",
                deliverable_kind="lookup_answer",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["total_hits"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_frequency",
            )

    # Multi-step corpus profile: a request for typical neighbours/collocates
    # plus examples requires the scope builder, metric tool and KWIC path in one
    # contract. This deliberately precedes the single-frequency and generic
    # comparison shortcuts, which otherwise truncate lay formulations such as
    # "typische Begleitwörter und Textbeispiele" to one tool family.
    collocation_cues = (
        "kollok",
        "begleitwört",
        "nachbarwört",
        "wörter in der nähe",
        "wörter in der naehe",
        "wortabstand",
        "typische wörter",
        "typische woerter",
    )
    context_cues = (
        "kwic",
        "textstelle",
        "textbeispiel",
        "konkordanz",
        "beispiele aus",
        "passende beispiele",
    )
    if (
        {"collocate_stats", "run_cqlf_query"} <= set(available_tools)
        and (
            hat_umfeld_cue
            or _has_any_phrase(ohne_zitate, collocation_cues)
        )
        and _has_any_phrase(lowered, context_cues)
    ):
        bundle = _heuristic_tool_bundle(
            (
                "metadata_values",
                "create_docset",
                "query_count",
                "collocate_stats",
                "run_cqlf_query",
                "frequency_list",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        required_evidence = ["metric_rows", "kwic_rows"]
        if "query_count" in bundle and _has_any_phrase(
            lowered, ("häufig", "frequenz", "normalis", "rate")
        ):
            required_evidence.append("total_hits")
        return AnalysisContract(
            mode="tool_analysis",
            track=(
                "comparative_analysis"
                if _is_comparative_prompt(lowered)
                else "bounded_analysis"
            ),
            analysis_family="term_profile",
            deliverable_kind="analysis_report",
            question_scope=_compact_text(question_text, 220),
            allowed_tools=bundle,
            required_evidence=required_evidence,
            forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
            response_shape="grounded_term_profile",
        )

    if (
        "run_cqlf_query" in set(available_tools)
        and _has_any_phrase(lowered, ("kwic", "kontext", "sichtbaren kontext", "sichtbarer kontext", "konkordanz"))
        and not _has_any_phrase(
            lowered,
            (
                "kollok",
                "word sketch",
                "wortprofil",
                "profil",
                "analyse",
                "frequenz",
                "häufig",
                "häufig",
                "dispersion",
                "metadat",
                "dokument",
                "document",
                "passage",
                "subkorpus",
                "semantic",
                "semant",
                "cluster",
                "unterschied",
                "vergleich",
            ),
        )
    ):
        statt_bestand = _normierung_statt_bestand(
            question_text,
            lowered=lowered,
            rezept_id=rezept_id,
            familie="kwic_context",
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if statt_bestand is not None:
            return statt_bestand
        aus_cue = _kwic_kontrakt(
            question_text,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if aus_cue is not None:
            return aus_cue

    if (
        "run_cqlf_query" in set(available_tools)
        and (
            ("kommt" in lowered and "vor" in lowered)
            or _has_any_phrase(lowered, ("treffer",))
            or (_has_any_phrase(lowered, ("beleg", "belege")) and _has_any_phrase(lowered, ("wort", "begriff", "lemma")))
        )
        and _has_any_phrase(lowered, ("wort", "begriff", "korpus", "lemma"))
        and not _has_any_phrase(
            lowered,
            (
                "kollok",
                "word sketch",
                "wortprofil",
                "profil",
                "analyse",
                "frequenz",
                "häufig",
                "häufig",
                "dispersion",
                "metadat",
                "dokument",
                "document",
                "passage",
                "subkorpus",
                "semantic",
                "semant",
                "cluster",
            ),
        )
    ):
        statt_bestand = _normierung_statt_bestand(
            question_text,
            lowered=lowered,
            rezept_id=rezept_id,
            familie="kwic_context",
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if statt_bestand is not None:
            return statt_bestand
        bundle = _heuristic_tool_bundle(
            ("run_cqlf_query",),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track=(
                    "lookup"
                    if frage_ist_blosses_nachschlagen(question_text)
                    else "bounded_analysis"
                ),
                analysis_family="kwic_context",
                deliverable_kind=(
                    "lookup_answer"
                    if frage_ist_blosses_nachschlagen(question_text)
                    else "analysis_report"
                ),
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=[],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_kwic_presence",
            )

    if _is_method_help_prompt(lowered):
        bundle = _heuristic_tool_bundle(
            ("frequency_list", "metadata_values", "semantic_search", "document_search", "documentation_search"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        required_evidence = _method_help_required_evidence(bundle)
        if bundle and required_evidence:
            return AnalysisContract(
                mode="tool_analysis",
                track="method_help",
                analysis_family="open_research",
                deliverable_kind="method_advice",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle[:4],
                required_evidence=required_evidence[:4],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_method_advice",
            )

    if _requires_contextual_hypothesis_evidence(lowered):
        bundle = _heuristic_tool_bundle(
            (
                "run_cqlf_query",
                "document_search",
                "semantic_search",
                "semantic_cluster_words",
                "semantic_cluster",
                "frequency_list",
                "metadata_values",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if any(
            tool_name in bundle
            for tool_name in (
                "run_cqlf_query",
                "document_search",
                "semantic_search",
                "semantic_cluster_words",
                "semantic_cluster",
            )
        ):
            return AnalysisContract(
                mode="tool_analysis",
                track="exploratory_research",
                analysis_family="open_research",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle[:4],
                required_evidence=["contextual_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_exploratory_report",
            )

    if (
        "frequency_list" in set(available_tools)
        and _has_any_phrase(lowered, ("frequenz", "wortliste", "häufig", "häufig", "wie oft"))
        and _has_any_phrase(lowered, ("wort", "wörter", "wörter", "liste"))
        # Die Umfeld-Cues gehoeren in die Ausschlussliste, weil eine
        # Assoziationsfrage die haeufigen Woerter typischerweise NENNT, um
        # sie auszuschlieszen („aussagekraeftige Partner von blosz
        # allgemein haeufigen Woertern“). Ohne sie liest dieser Zweig das
        # Ausschlusskriterium als Zielgroesse.
        and not hat_umfeld_cue
        and not _has_any_phrase(
            lowered,
            ("kollok", "word sketch", "wortprofil", "metadat", "subkorpus"),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("frequency_list",),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="lookup",
                analysis_family="term_frequency",
                deliverable_kind="lookup_answer",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["frequency_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_frequency",
            )

    if (
        "dispersion_offsets" in set(available_tools)
        and _has_any_phrase(lowered, ("dispersion", "verteilung"))
        and (
            _has_any_phrase(lowered, ("wort", "begriff", "lemma"))
            or "'" in lowered
            or '"' in lowered
            or "`" in lowered
        )
        and not _has_any_phrase(lowered, ("metadat", "subkorpus", "vergleich", "vergleiche"))
    ):
        # create_docset und query_count dazu: eine Streuung ueber Register oder
        # Modelle braucht Raten je Teilkorpus, die Registerwerte stehen in der
        # Korpuskarte. Kandidat 4, Frage 9 fand ohne sie keinen Weg zur
        # verlangten Registernormierung (test_dispersion_contract_allows_register_rates).
        bundle = _heuristic_tool_bundle(
            ("dispersion_offsets", "run_cqlf_query", "create_docset", "query_count"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "dispersion_offsets" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="term_profile",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["dispersion_profile"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_profile",
            )

    same_scope_collocation_terms = same_corpus_collocation_terms(question_text)
    if same_scope_collocation_terms and "collocate_stats" in set(available_tools):
        bundle = _heuristic_tool_bundle(
            ("query_count", "collocate_stats", "run_cqlf_query"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        return AnalysisContract(
            mode="tool_analysis",
            track="comparative_analysis",
            analysis_family="collocation",
            deliverable_kind="analysis_report",
            question_scope=_compact_text(question_text, 220),
            allowed_tools=bundle,
            required_evidence=[
                "metric_rows",
                *(["total_hits"] if "query_count" in bundle else []),
            ],
            forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
            response_shape="grounded_term_profile",
        )

    if (
        "compare_collocates" in set(available_tools)
        and _has_any_phrase(lowered, ("kollokation", "kollokationen", "kollokate"))
        and _has_any_phrase(lowered, ("vergleich", "vergleiche", "zwischen", "unterschied", "subkorpus"))
        and _is_human_ai_contrast_prompt(lowered)
    ):
        bundle = _heuristic_tool_bundle(
            ("compare_collocates", "metadata_values"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if bundle:
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence[:4],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if (
        "contrast_collocates" in set(available_tools)
        and _is_docset_comparative_prompt(lowered)
        and (
            _has_explicit_comparison_pair(lowered)
            # Wer ueber eine ACHSE vergleicht, nennt kein Paar: "die
            # Unterschiede der Modelle" meint alle zwoelf, nicht zwei.
            or _ist_achsenkontrast(lowered)
        )
        and not _is_human_ai_contrast_prompt(lowered)
    ):
        preferred_tools = (
            "metadata_values",
            "create_docset",
            "query_count",
            "contrast_collocates",
            "collocate_stats",
            "run_cqlf_query",
            "keyness",
            "frequency_list",
        )
        bundle = _heuristic_tool_bundle(
            preferred_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "contrast_collocates" in bundle:
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence,
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if (
        "compare_collocates" in set(available_tools)
        and _is_human_ai_contrast_prompt(lowered)
    ):
        preferred_tools = (
            ("keyness", "metadata_values", "frequency_list", "compare_collocates")
            if _is_broad_comparative_profile_prompt(lowered)
            else ("compare_collocates", "keyness", "frequency_list", "metadata_values")
        )
        bundle = _heuristic_tool_bundle(
            preferred_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "compare_collocates" in bundle:
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence,
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if (
        "compare_collocates" in set(available_tools)
        and _is_comparative_prompt(lowered)
        and _has_explicit_comparison_pair(lowered)
    ):
        has_multistep_tools = bool(
            {"create_docset", "query_count", "collocate_stats", "run_cqlf_query"}
            & set(available_tools)
        )
        preferred_tools = (
            (
                "metadata_values",
                "create_docset",
                "query_count",
                "compare_collocates",
                "collocate_stats",
                "run_cqlf_query",
                "keyness",
                "frequency_list",
            )
            if has_multistep_tools
            else (
                ("keyness", "metadata_values", "frequency_list", "compare_collocates")
                if _is_broad_comparative_profile_prompt(lowered)
                else ("compare_collocates", "keyness", "metadata_values", "frequency_list")
            )
        )
        bundle = _heuristic_tool_bundle(
            preferred_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "compare_collocates" in bundle:
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence,
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if (
        "metadata_values" in set(available_tools)
        and _metadata_request_is_focused(lowered)
    ):
        bundle = _heuristic_tool_bundle(
            ("metadata_values",),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if bundle:
            interpretative_metadata_request = (
                _metadata_request_needs_interpretation(lowered)
            )
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="metadata_capability",
                deliverable_kind=(
                    "analysis_report"
                    if interpretative_metadata_request
                    else "capability_report"
                ),
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metadata_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_metadata_capability",
            )

    if (
        "word_sketch" in set(available_tools)
        and _has_any_phrase(lowered, ("word sketch", "word-sketch", "wortprofil"))
    ):
        bundle = _heuristic_tool_bundle(
            ("word_sketch", "run_cqlf_query"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "word_sketch" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="word_sketch_profile",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_word_sketch",
            )

    if (
        "semantic_search" in set(available_tools)
        and _has_any_phrase(lowered, ("thematisch", "zentrale passagen", "semantisch"))
        and _has_any_phrase(
            lowered,
            ("passagen", "texte", "dokumente", "treffer", "finde", "suche"),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("semantic_search",),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="semantic_retrieval",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["semantic_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_semantic_report",
            )

    # Kollokation OHNE Beispielwunsch. Der Zweig darueber verlangt beides,
    # Umfeld-Cue UND Kontext-Cue, und liesz eine reine Assoziationsfrage
    # deshalb weiterlaufen, bis sie der Frequenzzweig einfing. Die Familie
    # 'collocation' war laengst gueltig, hatte ein eigenes Werkzeugbuendel
    # und ist erster family-Trigger des Rezepts 'assoziation', wurde aber
    # im ganzen Klassifikator nur von einem Vergleichszweig gesetzt, den
    # eine einfache Frage nie erreicht.
    # Der Vergleich ZWEIER Terme im selben Korpus hat weiter unten einen
    # eigenen, spezialisierteren Zweig mit track='comparative_analysis'.
    # Dieser hier ist der allgemeine Fall und weicht ihm aus, statt ihn
    # unterwegs abzufangen.
    if (
        "collocate_stats" in set(available_tools)
        and (
            hat_umfeld_cue
            or _has_any_phrase(ohne_zitate, collocation_cues)
        )
        # Der Zweig steht weit vorne, weil ihn sonst die Frequenzzweige
        # einfangen. Damit braucht er dieselbe Disziplin wie sie: er war
        # zuerst der einzige Cue-Zweig ganz OHNE Ausschlussliste und nahm
        # den Routen hinter ihm die Fragen weg, Word Sketch, Metadaten und
        # Dispersion. Eine Umfeldphrase irgendwo im Satz genuegte.
        and not _has_any_phrase(lowered, _UMFELD_AUSSCHLUSS)
        # DER GRUPPENVERGLEICH GEHOERT NICHT HIERHER, und das war der
        # schwerste Befund gegen diesen Zweig. ``same_corpus_collocation_
        # terms`` deckt nur den Vergleich ZWEIER TERME im selben Korpus
        # und liefert bei „zwischen Docset A und Docset B“ ausdruecklich
        # eine leere Liste. Der Zweig riss damit die Docset-Kontrastroute
        # an sich: aus acht Werkzeugen wurden vier, ohne keyness, ohne
        # contrast_collocates, ohne create_docset und ohne
        # metadata_values, und der Vorplan plante EINEN globalen
        # Kollokationsaufruf ueber das Gesamtkorpus. Damit haette der Fix
        # seinen eigenen Ausloeser eine Familie weiter wiederholt: gefragt
        # ist A gegen B, geantwortet wuerde mit dem globalen Umfeld. Es
        # traf auch die Achse Mensch gegen KI, die zentrale dieses Repos.
        #
        # Geprueft wird mit demselben Paar Praedikate, mit dem die
        # Kontrastroute ihre eigenen Faelle erkennt. Der Zusatz
        # ``_has_explicit_comparison_pair`` ist noetig, weil
        # ``_is_docset_comparative_prompt`` allein schon bei „Unterscheide
        # aussagekraeftige Partner von blosz allgemein haeufigen Woertern“
        # anschlaegt, also bei der Ausloeserfrage selbst.
        and not (
            _is_docset_comparative_prompt(lowered)
            and _has_explicit_comparison_pair(lowered)
        )
        and not same_corpus_collocation_terms(question_text)
    ):
        bundle = _heuristic_tool_bundle(
            # Association questions rank relationships by association strength.
            # A corpus frequency list supplies a different quantity and is excluded,
            # consistent with the collocation branch and association recipe.
            (
                "collocate_stats",
                "query_count",
                "run_cqlf_query",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "collocate_stats" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track=(
                    "comparative_analysis"
                    if _is_comparative_prompt(lowered)
                    else "bounded_analysis"
                ),
                analysis_family="collocation",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_profile",
            )

    if (
        {"run_cqlf_query", "collocate_stats"} <= set(available_tools)
        and _has_any_phrase(lowered, ("analyse", "profil", "vollständige analyse"))
        and _has_any_phrase(lowered, ("kwic", "kollokation", "kollokationen", "word sketch", "wordsketch"))
    ):
        bundle = _heuristic_tool_bundle(
            (
                "metadata_values",
                "create_docset",
                "query_count",
                "run_cqlf_query",
                "collocate_stats",
                "frequency_list",
                "dispersion_offsets",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "run_cqlf_query" in bundle and "collocate_stats" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="term_profile",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["kwic_rows", "metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_profile",
            )

    # Plain collocation / co-occurrence question about a single word, e.g.
    # "Berechne die Kollokationen für 'Mensch'", "Welche Wörter stehen neben
    # 'Arbeit'?", "Welche Wörter kommen häufig zusammen mit 'Mensch' vor?".
    # The earlier "analyse"+"kollokation" branch only fires when the user
    # literally asks for an "Analyse"/"Profil"; a direct co-occurrence question
    # falls through to the LLM contract preflight, which reasoning-heavy models
    # (e.g. qwen3.5-27b on the Responses API) cannot satisfy — they starve their
    # output budget on reasoning and return an empty structured payload, so the
    # orchestrator fail-closes BEFORE any tool runs. A deterministic heuristic
    # contract keeps this the SAME grounded ``collocate_stats`` path every model
    # already takes on the richer analysis phrasing (model-agnostic; gpt-oss-120b
    # simply short-circuits to the identical contract instead of the LLM turn).
    # Contrast questions ("Vergleich … human/ai") match the compare/contrast
    # branches earlier and never reach here.
    if (
        "collocate_stats" in set(available_tools)
        and _has_any_phrase(
            lowered,
            (
                "kollokation",
                "kollokationen",
                "kollokate",
                "kollokat",
                "statistisch auffällig",
                "typischerweise neben",
                "stehen neben",
                "zusammen mit",
                "zusammen vor",
                "gemeinsam vor",
            ),
        )
        and not _has_any_phrase(
            lowered,
            (
                "word sketch",
                "word-sketch",
                "wortprofil",
                "vergleich",
                "vergleiche",
                "unterschied",
                "contrast",
                "kontrast",
                "dispersion",
                "netzwerk",
                "network",
                "graph",
            ),
        )
    ):
        bundle = _heuristic_tool_bundle(
            ("collocate_stats", "run_cqlf_query", "frequency_list"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "collocate_stats" in bundle:
            return AnalysisContract(
                mode="tool_analysis",
                track="bounded_analysis",
                analysis_family="term_profile",
                deliverable_kind="analysis_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=["metric_rows"],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_term_profile",
            )

    return _kontrakt_aus_rezept(
        rezept_id,
        question_text=question_text,
        lowered=lowered,
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )


# Construct recipe-derived contracts with the same track, deliverable and
# answer form as the corresponding cue branches.
_FAMILIEN_KONTRAKT: Dict[str, Dict[str, str]] = {
    "term_frequency": {
        "track": "lookup",
        "deliverable_kind": "lookup_answer",
        "response_shape": "grounded_term_frequency",
    },
    "collocation": {
        # Leer, weil der Cue-Zweig den Track an der FRAGE festmacht, nicht
        # an der Familie: vergleichende Formulierung -> comparative,
        # sonst bounded. Ein fester Wert stand hier kurzzeitig und war
        # falsch, gefunden von der Gleichheitszusicherung im Test.
        "track": "",
        "deliverable_kind": "analysis_report",
        "response_shape": "grounded_term_profile",
    },
    "contrast_keyness": {
        "track": "comparative_analysis",
        "deliverable_kind": "contrast_report",
        "response_shape": "grounded_contrast_report",
    },
    "trend_analysis": {
        "track": "bounded_analysis",
        "deliverable_kind": "analysis_report",
        "response_shape": "grounded_trend_analysis",
    },
    "metadata_capability": {
        "track": "bounded_analysis",
        "deliverable_kind": "",  # haengt an der Frage, siehe unten
        "response_shape": "grounded_metadata_capability",
    },
    "word_sketch_profile": {
        "track": "bounded_analysis",
        "deliverable_kind": "analysis_report",
        "response_shape": "grounded_word_sketch",
    },
    # Use this analysis-report contract for normalizing concordance questions.
    # _kontrakt_aus_rezept keeps ordinary presence checks on their lookup path.
    "kwic_context": {
        # Leer wie bei collocation: die Korrelat-Frage vergleicht human
        # gegen ai, eine reine Gebrauchsfrage tut das nicht.
        "track": "",
        "deliverable_kind": "analysis_report",
        "response_shape": "grounded_kwic_presence",
    },
}

# open_research has several cue-specific tool sets and evidence requirements,
# so it keeps those contracts rather than deriving one from its recipe.
# kwic_context uses a conditional fallback: normalizing questions receive
# the analysis contract, while presence checks retain their existing path.
_FAMILIEN_OHNE_RUECKFALL = ("open_research",)


def _familien_evidenz(familie: str, bundle: Sequence[str]) -> list[str]:
    """Pflichtevidenz einer Familie, abgelesen aus den Cue-Zweigen."""

    im_bundle = set(bundle)
    if familie == "term_frequency":
        return ["total_hits"]
    if familie == "kwic_context":
        # P6: die Belege UND die exakte Zahl, beide aus den Kernwerkzeugen
        # des Rezepts. ``metadata_rows`` stand hier zuerst, abgelesen vom
        # Register-Cue-Zweig, und war an dieser Stelle falsch: es zwingt
        # jeden Gebrauchsturn zu einem Metadatenabruf, auch wenn keine
        # Achse gefragt ist, waehrend metadata_values hier nur Wegbereiter
        # der Seiten-Normierung ist. Die Trefferzahl dagegen ist bei einer
        # Konstruktionsfrage die Antwort selbst (Referenzantwort
        # konstr-korrelat-fenster: 45.599 satzintern, 340,64 gegen 91,78
        # pro Million).
        return [
            *(["kwic_rows"] if "run_cqlf_query" in im_bundle else []),
            *(["total_hits"] if "query_count" in im_bundle else []),
        ]
    if familie == "collocation":
        return [
            "metric_rows",
            *(["total_hits"] if "query_count" in im_bundle else []),
        ]
    if familie == "contrast_keyness":
        return [
            *(["metadata_rows"] if "metadata_values" in im_bundle else []),
            "metric_rows",
        ]
    if familie == "trend_analysis":
        return [
            "metadata_rows",
            *(["metric_rows"] if "trend_analysis" in im_bundle else []),
        ]
    if familie == "metadata_capability":
        return ["metadata_rows"]
    if familie == "open_research":
        return [
            *(["total_hits"] if "run_cqlf_query" in im_bundle else []),
            *(
                ["semantic_rows"]
                if "semantic_search" in im_bundle
                else ["contextual_rows"]
                if "document_search" in im_bundle
                else []
            ),
        ]
    return ["metric_rows"]


def _kontrakt_aus_rezept(
    rezept_id: str,
    *,
    question_text: str,
    lowered: str,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    """Derive a contract from an already selected recipe without another model call.

    Read the analysis family from the recipe's family trigger, using the
    same source as the reverse family-to-recipe lookup. Apply the caller's
    precedence rules and the family's supported fallback contract.
    """

    if not rezept_id:
        return None
    rezept = next((r for r in RECIPES if r.id == rezept_id), None)
    if rezept is None or not rezept.familien:
        return None
    familie = rezept.familien[0]
    vorlage = _FAMILIEN_KONTRAKT.get(familie)
    if vorlage is None:
        return None
    if familie == "kwic_context" and not _has_any_phrase(
        lowered, _NORMIERUNGS_CUES
    ):
        # DER RUECKFALL DIESER FAMILIE IST BEDINGT, und die Bedingung ist
        # gemessen. Ein unbedingter Eintrag verengte "Zeige mir KWIC und
        # Dokumentbeleg fuer Zeit." auf die fuenf kwic_context-Werkzeuge
        # und nahm dem Turn das ausdruecklich verlangte document_search.
        # Gefunden von test_forbidden_cross_tool_inference_is_blocked,
        # bevor es live ging.
        #
        # Die Familie deckt zwei Fragearten ab, die Bestandspruefung und
        # die Gebrauchsanalyse, und nur die zweite braucht den festen
        # Werkzeugraum. Der Normierungs-Cue trennt sie sauber: wer eine
        # Rate mit Nenner verlangt, prueft keinen Bestand.
        return None
    # Include prerequisite tools in the contract so required operations are
    # reachable. For example, keyness needs the tools that create and recover
    # its two live docsets.
    #
    # Keep the capability gate on the first core tool. Recipe availability uses
    # any core tool, so each recipe needs one core tool and places supporting
    # operations in wegbereiter_tools. This keeps selection and contract gating
    # consistent without letting a prerequisite select the recipe by itself.
    bundle = _heuristic_tool_bundle(
        tuple(rezept.kern_tools) + tuple(getattr(rezept, "wegbereiter_tools", ()) or ()),
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )
    if not bundle or rezept.kern_tools[0] not in bundle:
        # Capability-Gate, und zwar auf dem FUEHRENDEN Kernwerkzeug, nicht
        # auf irgendeinem. Ein Kontrakt, dessen Pflichtevidenz seine
        # erlaubten Werkzeuge nicht hergeben, ist schlimmer als gar keiner:
        # er bindet den Turn an etwas Unerreichbares.
        #
        # Der Fall ist real. Bei "Wie oft kommt Zeit vor?" mit nur
        # ``frequency_list`` im Raum lehnt der Cue-Zweig ab, weil sein
        # Buendel leer bleibt. Ohne diese Schaerfung haette der Rueckfall
        # angenommen und ``total_hits`` verlangt, was ``frequency_list``
        # nicht liefert. Mit ihr bleibt der bisherige Weg (Klassifikator,
        # sonst freier Modus) genau dort erhalten, wo er richtig ist.
        return None
    spur = vorlage["track"] or (
        "comparative_analysis"
        if _is_comparative_prompt(lowered)
        else "bounded_analysis"
    )
    lieferart = vorlage["deliverable_kind"]
    if familie == "metadata_capability":
        lieferart = (
            "analysis_report"
            if _metadata_request_needs_interpretation(lowered)
            else "capability_report"
        )
    return AnalysisContract(
        mode="tool_analysis",
        track=spur,
        analysis_family=familie,
        deliverable_kind=lieferart,
        question_scope=_compact_text(question_text, 220),
        allowed_tools=bundle,
        required_evidence=_familien_evidenz(familie, bundle),
        forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
        response_shape=vorlage["response_shape"],
    )


def fallback_analysis_contract(
    question_text: str,
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    """Zweitweg-Kontrakt, danach der Termlisten-Modus.

    ``tooling/tool_selection.py:437`` ruft woertlich
    ``heuristic_analysis_contract(...) or fallback_analysis_contract(...)``,
    dieser Bauer ist also ein Produktivpfad und nicht nur Theorie. Seine
    beiden contrast_keyness-Zweige setzen ``required_evidence`` ueber
    ``_contrast_required_evidence``, also wieder ``metric_rows``, und ohne
    die Huelle bekaeme eine Kandidatenliste hier weder ``query_count`` in
    den Werkzeugraum noch ``total_hits`` in die Pflicht.
    """
    return _mit_termlisten_modus(
        _fallback_analysis_contract(
            question_text,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        ),
        question_text,
        available_tools,
    )


def _fallback_analysis_contract(
    question_text: str,
    *,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    lowered = routing_text(question_text)
    if not lowered:
        return None

    if _is_docset_comparative_prompt(lowered) and not _is_human_ai_contrast_prompt(lowered):
        preferred_tools = (
            "metadata_values",
            "create_docset",
            "query_count",
            "contrast_collocates",
            "collocate_stats",
            "run_cqlf_query",
            "keyness",
            "frequency_list",
        )
        bundle = _heuristic_tool_bundle(
            preferred_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if "contrast_collocates" in bundle:
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence,
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if _is_comparative_prompt(lowered):
        has_multistep_tools = bool(
            {"create_docset", "query_count", "collocate_stats", "run_cqlf_query"}
            & set(available_tools)
        )
        preferred_tools = (
            (
                "metadata_values",
                "create_docset",
                "query_count",
                "compare_collocates",
                "collocate_stats",
                "run_cqlf_query",
                "keyness",
                "frequency_list",
            )
            if has_multistep_tools
            else (
                ("keyness", "metadata_values", "frequency_list", "compare_collocates")
                if _is_broad_comparative_profile_prompt(lowered)
                else ("compare_collocates", "keyness", "metadata_values", "frequency_list")
            )
        )
        bundle = _heuristic_tool_bundle(
            preferred_tools,
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        if any(name in bundle for name in ("compare_collocates", "keyness")):
            required_evidence = _contrast_required_evidence(bundle, question_text)
            return AnalysisContract(
                mode="tool_analysis",
                track="comparative_analysis",
                analysis_family="contrast_keyness",
                deliverable_kind="contrast_report",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle,
                required_evidence=required_evidence,
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_contrast_report",
            )

    if _is_method_help_prompt(lowered):
        bundle = _heuristic_tool_bundle(
            ("frequency_list", "metadata_values", "semantic_search", "document_search", "documentation_search"),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        required_evidence = _method_help_required_evidence(bundle)
        if bundle and required_evidence:
            return AnalysisContract(
                mode="tool_analysis",
                track="method_help",
                analysis_family="open_research",
                deliverable_kind="method_advice",
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle[:4],
                required_evidence=required_evidence[:4],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_method_advice",
            )

    if _is_exploratory_prompt(lowered):
        theme_overview = _is_theme_overview_prompt(lowered)
        bundle = _heuristic_tool_bundle(
            (
                "semantic_search",
                "semantic_cluster_words",
                "frequency_list",
                "metadata_values",
            )
            if theme_overview
            else (
                "frequency_list",
                "metadata_values",
                "semantic_search",
                "semantic_cluster_words",
            ),
            available_tools=available_tools,
            read_only_tools=read_only_tools,
        )
        required_evidence = [
            evidence_kind
            for evidence_kind, tool_name in (
                (
                    ("content_rows", "frequency_list"),
                    (
                        (
                            "cluster_rows",
                            "semantic_cluster_words",
                        )
                        if "semantic_cluster_words" in bundle
                        else (
                            "semantic_rows",
                            "semantic_search",
                        )
                    ),
                )
                if theme_overview
                else (
                    ("lexical_frequency_rows", "frequency_list"),
                    ("content_rows", "frequency_list"),
                    ("contextual_rows", "semantic_search"),
                )
            )
            if tool_name in bundle
        ]
        if not required_evidence and "semantic_search" in bundle:
            required_evidence.append("semantic_rows")
        if bundle and required_evidence:
            return AnalysisContract(
                mode="tool_analysis",
                track="exploratory_research",
                analysis_family="open_research",
                deliverable_kind=default_deliverable_kind_for_family(
                    "open_research",
                    question_text=question_text,
                    track="exploratory_research",
                ),
                question_scope=_compact_text(question_text, 220),
                allowed_tools=bundle[:4],
                required_evidence=required_evidence[:4],
                forbidden_claims=list(DEFAULT_FORBIDDEN_CLAIMS),
                response_shape="grounded_exploratory_report",
            )

    return None


def _requested_register_value(question_scope: str) -> str:
    match = re.search(
        r"\bregister\s+(?P<named>namens\s+)?(?P<quote>[\"'`„“‚‘])?"
        r"(?P<value>[^\s,.;:!?\"'`„“‚‘]+)",
        question_scope or "",
        re.IGNORECASE,
    )
    if not match:
        return ""
    value = _normalise_example_text(match.group("value")).casefold()
    # Axis lists do not name a register. Explicitly named values still work.
    if not (match.group("named") or match.group("quote")) and value in {
        "und", "oder", "and", "or", "pair",
    }:
        return ""
    return value


_METHOD_STEP_COUNTS = {
    "ein": 1,
    "einen": 1,
    "eine": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}


def _requested_method_step_count(question_text: str) -> int | None:
    text = _normalised_question_text(question_text)
    match = re.search(
        r"\b(?:erste[snr]?\s+)?"
        r"(?P<count>\d+|ein(?:e|en)?|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht)\s+"
        r"(?:erste[snr]?\s+)?"
        r"(?:analyse|method(?:en)?|untersuchungs|forschungs)[- ]?schritte?\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    token = match.group("count").casefold()
    try:
        value = int(token)
    except ValueError:
        value = _METHOD_STEP_COUNTS.get(token, 0)
    return value if 1 <= value <= 8 else None


def _requested_followup_question_count(question_text: str) -> int | None:
    text = _normalised_question_text(question_text)
    match = re.search(
        r"\b(?P<count>\d+|ein(?:e|en)?|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht)\s+"
        r"(?:(?:konkrete|sinnvolle|mögliche|moegliche)\s+)?"
        r"(?:anschluss|forschungs|folge)[- ]?fragen?\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    token = match.group("count").casefold()
    try:
        value = int(token)
    except ValueError:
        value = _METHOD_STEP_COUNTS.get(token, 0)
    return value if 1 <= value <= 8 else None


# ---------------------------------------------------------------------------
# Rezept-Auswahl (Rezept-Bibliothek, siehe recipes.py / recipes_data.py)
# ---------------------------------------------------------------------------

# Standard-Werkzeugmenge fuer die Rezept-Auswahl, falls der Aufrufer keine
# ``available_tools`` uebergibt. Stabil sortiert (deterministische Auswahl).
_RECIPE_DEFAULT_TOOLS: Tuple[str, ...] = (
    "collocate_stats",
    "create_docset",
    "dispersion_offsets",
    "frequency_list",
    "keyness",
    "kwic_context",
    "metadata_values",
    "query_count",
    "resolve_subcorpus",
    "run_cqlf_query",
    "semantic_search",
    "trend_analysis",
    "word_sketch",
)

# Die Kontrakt-Familie ``term_profile`` speist sich ueberwiegend aus
# Kollokations-Routen, aber auch aus der reinen Dispersionsroute. Eine
# Dispersionsfrage ohne Kollokations-Signal gehoert zum Frequenz-/
# Verteilungsrezept, nicht zum Assoziationsrezept.
_RECIPE_DISPERSION_CUES: Tuple[str, ...] = ("dispersion", "verteil")
# H8 (big_kontrast_mensch_ki): Kontrast-Signale schlagen die
# Metadaten-Familie. Nennt eine Frage die Metadaten nur als Achsenquelle
# ("Waehle die Kontrastachse anhand der Metadaten"), erfragt aber einen
# Unterschied/Vergleich, ist sie eine Kontrastfrage und keine
# Korpus-Karten-Frage. Spezifitaets-Rangfolge als Daten, keine neue
# Heuristik: "unterscheid" deckt unterscheidet/unterschiede ab.
_RECIPE_KONTRAST_CUES: Tuple[str, ...] = (
    "unterscheid",
    "vergleich",
    "kontrast",
    "typisch für",
    "typisch fuer",
)
_ZITIERTER_TERM = re.compile(
    r"""['"„»‚›`]([^'"“”»«‘›`]{1,80})['"“”»«‘›`]"""
)


def ohne_zitierte_terme(text: str) -> str:
    """Der Fragetext ohne die zitierten Suchbegriffe.

    Ein Cue trifft sonst IM Suchbegriff. „Zaehle die Treffer fuer 'im
    Umfeld der Bundesregierung'“ ist eine Zaehlfrage und wurde als
    Kollokationsfrage eingestuft, weil der Cue im Zitat stand. Eine
    Pruefung nur an Einwort-Zitaten hatte das nicht gezeigt.

    Der Zeichenvorrat deckt gerade und typografische Anfuehrungszeichen
    in beiden Weiten ab. Das Ergebnis dient AUSSCHLIESZLICH dem
    Cue-Abgleich, nie der Termerkennung.
    """

    return _ZITIERTER_TERM.sub(" ", str(text or ""))


# Requests for rates, denominators or breakdowns require analysis rather
# than a presence answer. Mentioning a subcorpus alone still permits a
# lookup. Match inflected breakdown requests through their word stem.
_NORMIERUNGS_CUES: Tuple[str, ...] = (
    "normalis",
    "aufschlüssel",
    "aufschluessel",
    "aufgeschlüssel",
    "aufgeschluessel",
    "pro million",
    "rohtreffer",
    # Frequency comparisons between differently sized subcorpora need rates
    # and tools that can count each side.
    "häufiger",
    "haeufiger",
    "seltener",
    "öfter",
    "oefter",
)


def _normierung_statt_bestand(
    question_text: str,
    *,
    lowered: str,
    rezept_id: str,
    familie: str,
    available_tools: Sequence[str],
    read_only_tools: Sequence[str],
) -> AnalysisContract | None:
    """Der Rezeptkontrakt statt des Bestandsrahmens, wenn normalisiert wird.

    ERST WAR DAS EIN AUSSCHLUSS, und der war eine Verschiebung. Ein
    ``not _has_any_phrase(lowered, _NORMIERUNGS_CUES)`` an beiden
    Presence-Zweigen liess konstr-korrelat-fenster durchfallen, und der
    Kontrast-Zweig fing sie: ``contrast_keyness`` mit ``keyness`` im Raum.
    Eine Frage nach einer Gliederkette mit Abstandsquantor bekommt so ein
    Schluesselwortmass. Gemessen wurde das an dieser Datei selbst, bevor es
    live ging.

    Hier wird stattdessen DELEGIERT. Die Familie bleibt ``kwic_context``,
    nur Werkzeugraum und Lieferart kommen aus dem Rezept, das der Router
    ohnehin schon gewaehlt hat. Kein zweiter Wahrheitsstrang: derselbe
    Bauer, der auch den Rueckfall baut.

    Ohne ``rezept_id`` gibt es nichts zu delegieren, dann bleibt der
    bisherige Weg. Genau davon lebt ``select_recipe``, das diese Funktion
    ohne Rezept aufruft, um die Familie zu bestimmen.

    ``familie`` ist die Schranke, und sie ist nicht kosmetisch. Der Cue
    hat die Familie entschieden, hier wird nur noch die Ausfuehrung
    geschaerft. Ohne die Schranke haette ein Router-Rezept aus einer
    anderen Familie die Cue-Entscheidung ueberschrieben, und zwar auf
    ALLEN Wegen statt nur bei ``stage='llm'``. Genau das faengt
    test_ohne_modellurteil_bleibt_alles_wie_bisher: mit
    ``rezept_id='kontrast'`` und ohne Stufe wurde aus ``kwic_context``
    ploetzlich ``contrast_keyness``.
    """

    if not rezept_id or not _has_any_phrase(lowered, _NORMIERUNGS_CUES):
        return None
    kontrakt = _kontrakt_aus_rezept(
        rezept_id,
        question_text=question_text,
        lowered=lowered,
        available_tools=available_tools,
        read_only_tools=read_only_tools,
    )
    if kontrakt is None or kontrakt.analysis_family != familie:
        return None
    return kontrakt


# Routen, die HINTER dem Kollokationszweig liegen und ihm sonst zum Opfer
# fallen. Der Zweig steht weit vorne, weil ihn sonst die Frequenzzweige
# einfangen, und braucht darum dieselbe Disziplin wie seine Nachbarn: er
# war zuerst der einzige Cue-Zweig ganz ohne Ausschlussliste und nahm
# Word Sketch, Metadaten und Dispersion ihre Fragen weg.
_UMFELD_AUSSCHLUSS: Tuple[str, ...] = (
    # Routen, die eine eigene Familie haben
    "word sketch",
    "wortprofil",
    "grammatische relation",
    "grammatischen relation",
    "metadat",
    "subkorpus",
    "dispersion",
    "verteilt sich",
    "verteilung",
    # Gruppenvergleich. Das Praedikatpaar der Kontrastroute faengt den
    # Registervergleich nicht, weil dort kein explizites Paar steht
    # („unterscheiden news von blog“).
    "registervergleich",
    "zwischen den registern",
    "teilkorpus",
    "docset",
    # Zeitverlauf. Der Trendzweig kennt „Wahlperioden“ nicht, und ohne
    # diesen Eintrag nimmt der Kollokationszweig ihm die Frage weg.
    "wahlperiode",
    "zeitverlauf",
    "entwickelt sich",
    "hinweg",
    # Methodenberatung. Gefragt ist das Vorgehen, nicht das Ergebnis.
    "methodisch vor",
    "wie gehe ich",
    "wie gehen wir",
)
"""Wo der Kollokationszweig zurueckstehen muss.

Er ist der ALLGEMEINSTE der Cue-Zweige und stand zuerst weit vorne, wo er
den spezialisierten Routen hinter ihm die Fragen wegnahm. Er ist inzwischen
hinter sie verschoben, hinter Trend, Methodenhilfe, Dispersion, Kontrast,
Metadaten, Word Sketch und Semantik.

Das allein genuegt aber nicht. Wo eine Route ihre Frage gar nicht selbst
erkennt und das Rezept bisher aus dem blossen Triggerabgleich kam (Vertrag
= None), erzeugt der Kollokationszweig NEU einen Vertrag und ueberstimmt
damit die Triggerwahl. Gemessen und je einzeln zurueckgenommen: der
Registervergleich, der Verlauf ueber Wahlperioden und die
Methodenberatung.
"""

_UMFELD_CUES: Tuple[str, ...] = (
    "umfeld von",
    "umfeld des",
    "umfeld der",
    "im umfeld",
    "wortumfeld",
    "unmittelbare umfeld",
    "unmittelbaren umfeld",
    "nachbarwort",
    "nachbarwört",
    "nachbarwoert",
    "nachbarschaft von",
    "umgebung von",
    "umgebungswört",
    "kollokationspartner",
)
"""Die gelaeufigen deutschen Fachwoerter fuer das Umfeld eines Knotens.

Sie fehlten, und das war der Defekt. Im Nachtlauf vom 2026-08-27 fragte
gp_assoz_migration nach dem „charakteristischen unmittelbaren Umfeld“ von
‚Migration‘ und wurde in beiden Runden als Frequenzfrage eingestuft, weil
die Frage das Fachwort „Kollokation“ vermeidet. Der Zweig, der sie
einfing, prueft auf „haeufig“ plus „woerter“: die Frage sagt „blosz
allgemein haeufigen Woertern“, um genau diese Menge AUSZUSCHLIESZEN. Der
Klassifikator las das Ausschlusskriterium als Zielgroesse.

PHRASEN, KEINE WORTSTAEMME. „umfeld“ oder „partner“ als Stamm faengt die
Frage „Wie oft kommt 'Koalitionspartner' vor?“ mit ein.

Das genuegt aber NICHT, und die erste Fassung dieses Kommentars behauptete
faelschlich, es genuege. Sie war an Einwort-Zitaten geprueft. Ein
MEHRWORT-Zitat traegt die Phrase mit: „Zaehle die Treffer fuer 'im Umfeld
der Bundesregierung'“ schlug an und wurde zur Kollokationsfrage. Der
Abgleich laeuft deshalb ueber ``ohne_zitierte_terme``, also am
zitatfreien Fragetext.
"""

_RECIPE_COLLOCATION_CUES: Tuple[str, ...] = (
    "kollok",
    "kookkurrenz",
    "zusammen mit",
    "gemeinsam mit",
    "begleitwört",
    "begleitwoert",
    "steht neben",
    "stehen neben",
    "tritt mit",
    "assoziation",
)
# OHNE die Umfeld-Cues, und das mit Absicht. Diese Menge hat genau EINEN
# Verbraucher: die Ausweiche, die ein als 'assoziation' erkanntes Rezept
# nach 'frequenz' umleitet, wenn Dispersions-Cues da sind und KEIN
# Kollokations-Cue. Haengt man die Umfeld-Cues hier an, kann die Ausweiche
# bei „Wie verteilt sich das Umfeld von 'Regierung'? Berechne die
# Dispersion.“ nicht mehr greifen, und eine Dispersionsfrage landet bei
# der Assoziation. Die Umfeldfragen brauchen den Eintrag nicht: ihr Rezept
# kommt seit dem Kollokationszweig aus der FAMILIE, nicht aus dieser Liste.


def _recipe_for_family(analysis_family: str) -> Recipe | None:
    """Erstes Rezept, dessen ``family:``-Trigger die Familie nennt."""

    for recipe in RECIPES:
        if analysis_family in recipe.familien:
            return recipe
    return None


def _recipe_tools_available(
    recipe: Recipe, available_tools: Sequence[str]
) -> bool:
    """Capability-Gate: mindestens ein Kernwerkzeug muss verfuegbar sein."""

    available = {str(name) for name in available_tools}
    return any(name in available for name in recipe.kern_tools)


def _phrase_trigger_matches(lowered: str, trigger: str) -> bool:
    """Ein Phrasen-Trigger gegen die normalisierte Frage.

    ``wort:<lexem>`` matcht nur an Wortgrenzen (H8: ``wort:stil`` trifft
    "Stil"/"stil.", nie "still" oder "stilistisch"), alle anderen Eintraege
    bleiben reine Substring-Muster.
    """

    if trigger.startswith("wort:"):
        lexem = trigger.split(":", 1)[1].strip()
        if not lexem:
            return False
        pattern = r"(?<!\w)" + re.escape(lexem) + r"(?!\w)"
        return re.search(pattern, lowered) is not None
    return trigger in lowered


def select_recipe(
    frage: str,
    capabilities: Mapping[str, Any] | None = None,
) -> Recipe | None:
    """Waehle deterministisch (0 LLM-Calls) ein Analyse-Rezept zur Frage.

    ``capabilities`` ist ein optionales Mapping mit den Schluesseln
    ``available_tools`` und ``read_only_tools`` (je Sequenz von Toolnamen).
    Fehlen sie, gilt die Standard-Werkzeugmenge ``_RECIPE_DEFAULT_TOOLS``.

    Auswahlreihenfolge:

    1. Familien-Route: ``heuristic_analysis_contract`` klassifiziert die
       Frage, die ``analysis_family`` des Kontrakts wird ueber die
       ``family:``-Trigger der Rezepte aufgeloest.
    2. Direkter Trigger-Scan: Phrasen-Trigger der Rezepte (Substring oder
       ``wort:``-Wortgrenzen-Lexem) in der stabilen Prioritaetsreihenfolge
       von ``RECIPES`` (spezifisch vor breit).
    3. Explorations-Fallback: offene Korpusfragen erhalten das Rezept
       ``exploration_meta``.

    ``None`` bedeutet FREIER MODUS (kein passendes Rezept), niemals eine
    Ablehnung: der Aufrufer behandelt die Frage dann ohne Rezept-Briefing
    weiter, statt sie fail-closed abzuweisen.
    """

    # One reading of the question for cues AND triggers: the English
    # rendering (candyconc.question_language) or, for German, the normalised
    # text as before. stage1_recipe_decision reads the triggers through
    # question_form.starker_treffer, which renders the same way.
    lowered = routing_text(frage)
    if not lowered:
        return None
    caps: Mapping[str, Any] = (
        capabilities if isinstance(capabilities, Mapping) else {}
    )
    raw_available = caps.get("available_tools") or _RECIPE_DEFAULT_TOOLS
    available = [
        str(name) for name in raw_available if str(name).strip()
    ]
    raw_read_only = caps.get("read_only_tools") or available
    read_only = [
        str(name) for name in raw_read_only if str(name).strip()
    ]

    # P5: zwei Fragearten entscheidet die FORM der Frage, nicht die
    # Familienheuristik und nicht der Klassifikator. Beide standen im
    # Messarm vom 2026-08-31 (evaluation/deutung/harnisch_nachher.jsonl)
    # ohne eigene Kategorie da: sechs von sieben Turns entschied Stufe 2,
    # deren Menue weder Konstruktion noch Kandidatenliste kennt.
    #
    # Gemessen auf dem eingefrorenen Fragensatz: konstr-scharnier-
    # dreigliedrig ging ueber die Familie an frequenz, gemischt-
    # markerliste-robustheit an metadaten_struktur. Beide Erkenner pruefen
    # wortgrenzen- und flexionsgenau (frageform.starker_treffer), damit
    # "Rekonstruktion" keine Konstruktionsfrage und "Wortlisten" keine
    # Markerliste wird.
    #
    # DER KONSTRUKTIONSVORRANG VERLANGT ZUSAETZLICH EINE BELEGFORDERUNG
    # (frageform.ist_konstruktions_suchauftrag). Der erste Zuschnitt
    # fragte nur nach der Suchform und leitete damit ueber alle fuenf
    # Fragensaetze unter evaluation/fragen/ drei Fragen um, die Zahlen im
    # Gruppenvergleich verlangen und die gebrauch_kwic mit seinem einen
    # Kernwerkzeug run_cqlf_query nicht rechnen kann:
    # nicht-nur-sondern-auch-methode-vs-modell kontrast -> gebrauch_kwic,
    # claude-gegen-gpt-konstruktion frequenz -> gebrauch_kwic, kontrast-3
    # exploration_meta -> gebrauch_kwic.
    konstruktionsrezept = RECIPES_BY_ID.get("gebrauch_kwic")
    if (
        konstruktionsrezept is not None
        and ist_konstruktions_suchauftrag(frage)
        and _recipe_tools_available(konstruktionsrezept, available)
    ):
        return konstruktionsrezept
    kandidatenrezept = RECIPES_BY_ID.get("kontrast")
    if (
        kandidatenrezept is not None
        and ist_kandidatenlisten_pruefung(frage)
        and _recipe_tools_available(kandidatenrezept, available)
    ):
        return kandidatenrezept

    contract = heuristic_analysis_contract(
        frage,
        available_tools=available,
        read_only_tools=read_only,
    )
    if contract is not None:
        recipe = _recipe_for_family(contract.analysis_family)
        if (
            recipe is not None
            and recipe.id == "assoziation"
            and _has_any_phrase(lowered, _RECIPE_DISPERSION_CUES)
            and not _has_any_phrase(lowered, _RECIPE_COLLOCATION_CUES)
        ):
            recipe = RECIPES_BY_ID.get("frequenz")
        # H8 (big_kontrast_mensch_ki): traegt eine als Metadaten-Frage
        # klassifizierte Frage gleichzeitig Kontrast-Signale, gewinnt das
        # Kontrastrezept (die Metadaten sind dann Achsenquelle, nicht
        # Frageziel). Nur wenn dessen Kernwerkzeug verfuegbar ist, sonst
        # bleibt die ehrliche Korpus-Karte die beste Antwort.
        if (
            recipe is not None
            and recipe.id == "metadaten_struktur"
            and _has_any_phrase(lowered, _RECIPE_KONTRAST_CUES)
        ):
            kontrast = RECIPES_BY_ID.get("kontrast")
            if kontrast is not None and _recipe_tools_available(
                kontrast, available
            ):
                recipe = kontrast
        if recipe is not None and _recipe_tools_available(recipe, available):
            return recipe

    for recipe in RECIPES:
        if not _recipe_tools_available(recipe, available):
            continue
        if any(
            _phrase_trigger_matches(lowered, phrase)
            for phrase in recipe.phrasen_trigger
        ):
            return recipe

    fallback = RECIPES_BY_ID.get("exploration_meta")
    if (
        fallback is not None
        and _is_exploratory_prompt(lowered)
        and _recipe_tools_available(fallback, available)
    ):
        return fallback
    return None
