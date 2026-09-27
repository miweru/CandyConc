"""Markdown rendering for the grounding pipeline: all builders and tables.

K3 Slice 2 (step 1): byte-verbatim extraction from ``analysis_grounding.py``
(the facade). Moved here: the fact-note and provenance line builders, the
requested-result-table renderers (frequency, KWIC, collocation, ngram,
keyness), the claim-repetition guards used by those tables, the retrieval
assessment lines, ``build_verified_claim_markdown``,
``build_claim_preserving_grounded_markdown``, ``evidence_manifest``, the
family-specific ``_build_*_markdown`` builders and their local text helpers,
``build_conservative_markdown`` and ``build_grounded_markdown``.

The facade re-exports every name below lazily (PEP 562 ``__getattr__`` at the
end of ``analysis_grounding``), so all existing imports keep working. This
module imports its dependencies FROM the facade at load time. That is safe in
both import orders because ``analysis_grounding`` never imports this module at
load time: importing this module first fully initialises the facade, and
importing the facade first defers this module until the first attribute
access.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t, format_int, is_english

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Sequence, Tuple

# Der Methodensteckbrief ist ein eigenes Anliegen und liegt seit dem
# 2026-09-01 in einem eigenen Modul: dieses hier sagt, WAS gefunden wurde,
# jenes, WOMIT gemessen wurde. Die drei Namen bleiben hier gebunden, weil
# die Fassade ``analysis_grounding`` sie ueber dieses Modul aufloest und
# neunzehn Stellen ``_safe_float`` brauchen.
from .method_sheet import (  # noqa: F401
    _PROVENANCE_LABELS,
    _analysis_provenance_lines,
    _safe_float,
)
from .analysis_grounding import (
    AnalysisContract,
    AnswerEnvelope,
    ClaimDraft,
    DEFAULT_GROUNDING_ROW_LIMIT,
    EvidenceItem,
    GroundingVerdict,
    MAX_ANSWER_CLAIMS,
    MAX_CLAIM_TEXT_CHARS,
    ObservedFact,
    _COMPARABLE_METADATA_FIELDS,
    _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN,
    _IDENTIFIER_METADATA_FIELD_RE,
    _METHOD_STEP_COUNTS,
    _NGRAM_EPISTEMIC_PATTERN,
    _NGRAM_HYPOTHESIS_PATTERN,
    _NGRAM_INTERPRETATION_REQUEST_PATTERN,
    _NGRAM_VALIDATION_PATTERN,
    _PARTITION_METADATA_FIELDS,
    _SEMANTIC_PATTERN_SYNTHESIS_REQUEST_PATTERN,
    _accepted_claims_reject_confirmation_pressure,
    _claim_is_hypothesis,
    _claimed_ngram_terms,
    _cluster_sample_values,
    _compact_text,
    _contains_literal_label,
    _dedupe_ordered_strs,
    _exact_lexical_search,
    _explicit_counted_response_groups,
    _extract_numeric_tokens,
    _format_log_ratio_metric,
    _frequency_group_by,
    _has_any_phrase,
    _informative_clusters,
    _is_confirmation_pressure_prompt,
    _is_negative_or_unknown_limitation,
    _joined_surface_text,
    _keyness_direction_contexts,
    _kwic_annotation_risk_rows,
    _looks_like_opaque_id,
    _matching_collocation_count_items,
    _ngram_surface_terms,
    _normalise_example_text,
    _normalise_claim_text,
    _normalise_field_value,
    _normalise_text_list,
    _normalised_question_text,
    _normalize_number_token,
    _numeric_token_is_supported,
    _observed_facts_supply_confirmation_boundary,
    _question_requests_kwic_table,
    _question_term,
    _requested_followup_question_count,
    _requested_frequency_result_count,
    _requested_method_step_count,
    _sample_items,
    _selected_collocation_profiles,
    _semantic_theme_tokens,
    _source_values_for_field,
    _strip_redundant_method_step_ordinal,
    _user_facing_evidence_gap,
    accepted_semantic_pattern_interpretation_is_substantive,
    compatible_deliverable_kind,
    missing_response_requirements,
    same_corpus_collocation_terms,
)
# Direktimport statt Fassade: die H6-Helfer liegen in grounding_schemas und
# werden von der analysis_grounding-Fassade (fremdes Paket) nicht re-exportiert.
from .grounding_evidence import (
    rangliste_ausdruecklich_bestellt,
)
from .grounding_schemas import (
    _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN,
    _compact_quote,
    _compact_sentences,
)



def grounded_fact_notes(observed_facts: Sequence[ObservedFact], *, max_items: int = 5) -> List[str]:
    candidates: List[tuple[ObservedFact, str]] = []
    seen: set[str] = set()
    for fact in observed_facts:
        if fact.exactness == "derived" and not fact.supports_claims and fact.fact_kind not in {"limitation"}:
            continue
        note = _compact_text(
            f"{fact.id} | {fact.fact_kind} | {fact.exactness} | {fact.statement}",
            220,
        )
        if not note or note in seen:
            continue
        seen.add(note)
        candidates.append((fact, note))
    notes: List[str] = []
    used_notes: set[str] = set()
    seen_kinds: set[str] = set()
    seen_sources: set[str] = set()
    for fact, note in candidates:
        source = fact.source_evidence_ids[0] if fact.source_evidence_ids else ""
        if fact.fact_kind in seen_kinds and source in seen_sources:
            continue
        notes.append(note)
        used_notes.add(note)
        seen_kinds.add(fact.fact_kind)
        if source:
            seen_sources.add(source)
        if len(notes) >= max_items:
            break
    for _fact, note in candidates:
        if len(notes) >= max_items:
            break
        if note in used_notes:
            continue
        notes.append(note)
        used_notes.add(note)
    return notes


def blocked_claim_notes(
    envelope: AnswerEnvelope,
    verdict: GroundingVerdict,
    *,
    max_items: int = 5,
) -> List[str]:
    rejected = set(verdict.rejected_claim_ids)
    notes: List[str] = []
    for claim in envelope.claims:
        if claim.id not in rejected:
            continue
        note = _compact_text(claim.text, 220)
        if note:
            notes.append(note)
        if len(notes) >= max_items:
            break
    for item in envelope.blocked_claims:
        if len(notes) >= max_items:
            break
        text = _compact_text(item, 220)
        if text and text not in notes:
            notes.append(text)
    return notes






def exact_zero_lexical_search(item: EvidenceItem) -> Tuple[str, str]:
    """Return ``(attribute, term)`` for an exact zero-hit lexical lookup."""

    if (
        item.tool != "run_cqlf_query"
        or str(item.status or "").strip().casefold() == "error"
        or _safe_float(item.raw_surface.get("total")) != 0.0
    ):
        return "", ""
    return _exact_lexical_search(item)


def _direct_lexical_search_summary(
    evidence_items: Sequence[EvidenceItem],
) -> str:
    """Report every exact lexical lookup together, without cherry-picking zeros."""

    searches: List[str] = []
    seen: set[Tuple[str, str]] = set()
    for item in evidence_items:
        if (
            item.tool != "run_cqlf_query"
            or str(item.status or "").strip().casefold() == "error"
        ):
            continue
        attribute, term = _exact_lexical_search(item)
        total = _safe_float(item.raw_surface.get("total"))
        signature = (attribute, term.casefold())
        if not attribute or not term or total is None or signature in seen:
            continue
        seen.add(signature)
        label = _t("Wortform", 'word form') if attribute == "word" else _t("Lemma", 'lemma')
        rendered_total = str(int(total)) if total.is_integer() else str(total)
        searches.append(
            _t(f"{label} `{term.replace('`', '´')}`: {rendered_total} Treffer", f"""{label} `{term.replace('`', '´')}`: {rendered_total} hits""")
        )
    if not searches:
        return ""
    if len(searches) == 1:
        return (
            _t("Der direkte lexikalische Suchlauf ergab ", 'The exact lexical search returned ')
            + searches[0]
            + _t(". Diese Trefferzahl gilt nur für die wörtlich ausgeführte "
            "Abfrage, nicht für das breitere thematische Feld.", '. This count applies to the exact query executed, rather than the broader topic.')
        )
    return (
        _t("Die direkten lexikalischen Suchläufe ergaben ", 'The exact lexical searches returned ')
        + "; ".join(searches)
        + _t(". Diese Trefferzahlen gelten nur für die wörtlich ausgeführten "
        "Abfragen, nicht für das breitere thematische Feld.", '. These counts apply to the exact queries executed, rather than the broader topic.')
    )


def _analysis_execution_limitation_lines(
    evidence_items: Sequence[EvidenceItem],
    *,
    selected_evidence_ids: Sequence[str] = (),
) -> List[str]:
    """Explain failures and only those narrow searches selected for reporting."""

    lines: List[str] = []
    selected = {str(value) for value in selected_evidence_ids if str(value)}
    failed_tools = {
        str(item.tool or "").strip()
        for item in evidence_items
        if str(item.status or "").strip().casefold() == "error"
        and item.id not in selected
        and str(item.tool or "").strip()
    }
    successful_tools = {
        str(item.tool or "").strip()
        for item in evidence_items
        if str(item.status or "").strip().casefold() != "error"
        and str(item.tool or "").strip()
    }
    if failed_tools - successful_tools:
        lines.append(
            _t("Nicht erfolgreich abgeschlossene Werkzeugaufrufe liefern keine "
            "Evidenz und wurden aus der inhaltlichen Auswertung ausgeschlossen.", 'Unsuccessful tool calls provide no evidence and were excluded from the analysis.')
        )

    zero_lexical_queries: List[Tuple[EvidenceItem, str]] = []
    zero_complex_queries: List[str] = []
    for item in evidence_items:
        if (
            item.id not in selected
            or item.tool != "run_cqlf_query"
            or str(item.status or "").strip().casefold() == "error"
            or _safe_float(item.raw_surface.get("total")) != 0.0
        ):
            continue
        try:
            parsed_args = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_args = {}
        query = _normalise_example_text(
            item.raw_surface.get("query")
            or (
                parsed_args.get("query")
                if isinstance(parsed_args, dict)
                else ""
            )
        )
        query_mode = _normalised_question_text(
            item.raw_surface.get("query_mode")
        )
        if not query:
            continue
        attribute, term = _exact_lexical_search(item)
        if attribute and term:
            zero_lexical_queries.append((item, query))
        elif "[" in query or query_mode == "cqlf":
            zero_complex_queries.append(query)
    seen_lexical: set[Tuple[str, str]] = set()
    for item, query in zero_lexical_queries:
        attribute, term = _exact_lexical_search(item)
        signature = (attribute, term.casefold())
        if signature in seen_lexical:
            continue
        seen_lexical.add(signature)
        escaped = query.replace("`", "´")
        if attribute == "word":
            lines.append(
                _t("Der Nulltreffer gilt nur für die wörtlich ausgeführte "
                f"Wortformenabfrage `{escaped}`; er belegt nicht das Fehlen "
                "anderer Flexions- oder Lemmaformen, von Komposita, Synonymen "
                "oder semantisch verwandten Formulierungen.", f"""The zero count applies to the exact word-form query `{escaped}`. Other inflections, lemma forms, compounds, synonyms and related expressions were not tested by this query.""")
            )
        else:
            lines.append(
                _t("Der Nulltreffer gilt nur für die wörtlich ausgeführte "
                f"Lemmaabfrage `{escaped}`; er belegt nicht das Fehlen von "
                "Komposita, anderen Lemmata oder Synonymen und semantisch "
                "verwandten Formulierungen.", f"""The zero count applies to the exact lemma query `{escaped}`. Compounds, other lemmas, synonyms and related expressions were not tested by this query.""")
            )
    zero_complex_queries = list(dict.fromkeys(zero_complex_queries))
    if zero_complex_queries:
        rendered_queries = "; ".join(
            f"`{query.replace('`', '´')}`" for query in zero_complex_queries[:4]
        )
        lines.append(
            _t("Die Nulltreffer gelten nur für die wörtlich ausgeführten "
            f"CQLF-Abfragen {rendered_queries}; sie belegen weder das Fehlen "
            "anderer Tokenfolgen oder Attributkombinationen noch semantisch "
            "verwandter Formulierungen.", f"""The zero counts apply to the exact CQLF queries {rendered_queries}. Other token sequences, attribute combinations and related expressions were not tested by these queries.""")
        )
    return lines


def _requested_ngram_result_count(question_text: str) -> int | None:
    text = _normalised_question_text(question_text)
    match = re.search(
        r"\b(?:(?:top|oberste[nr]?|häufigste[nr]?|haeufigste[nr]?)\s+)?"
        r"(?P<count>\d+|ein(?:e|en)?|zwei|drei|vier|fünf|fuenf|sechs|"
        r"sieben|acht|neun|zehn)\s+"
        r"(?:(?:oberste[nr]?|häufigste[nr]?|haeufigste[nr]?)\s+)?"
        r"(?:n[- ]?gramm\w*|zwei[- ]?\s*bis[- ]?\s*dreiwortfolg\w*|"
        r"wortfolg\w*)\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        match = re.search(
            r"\btop[- ]?(?P<count>\d+)\b[^.!?\n]{0,40}\bn[- ]?gramm",
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
    return value if 1 <= value <= 20 else None


def _display_number(value: Any, *, decimals: int | None = None) -> str:
    """Format a tool value for German research-facing tables."""

    number = _safe_float(value)
    if number is None:
        return str(value)
    if decimals is None and number.is_integer():
        return format_int(int(number))
    digits = 4 if decimals is None else max(0, decimals)
    rendered = f"{number:,.{digits}f}"
    if decimals is None:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered if is_english() else rendered.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _markdown_cell(value: Any, *, code: bool = False) -> str:
    text = _normalise_example_text(value).replace("|", "\\|")
    if not code:
        return text
    return f"`{text.replace('`', '´')}`"


def _requested_frequency_result_table(
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
    *,
    accepted_claims: Sequence[ClaimDraft] = (),
) -> str:
    requested = _requested_frequency_result_count(question_text)
    if requested is None:
        return ""
    item = next(
        (
            item
            for item in evidence_items
            if item.tool == "frequency_list" and item.status != "error"
        ),
        None,
    )
    if item is None:
        return ""
    raw_rows = item.raw_surface.get("rows")
    if not isinstance(raw_rows, list):
        return ""
    rows = [row for row in raw_rows if isinstance(row, dict)][:requested]
    if len(rows) < requested:
        return ""

    denominator = item.raw_surface.get("denominator_tokens")
    if denominator in (None, ""):
        denominator = item.raw_surface.get("corpus_tokens")
    grouping = _frequency_group_by(item)
    label_heading = {
        "word": _t("Wortform", 'word form'),
        "lemma": _t("Lemma", 'lemma'),
        "pos": "POS",
    }.get(grouping, _t("Eintrag", 'entry'))

    def row_is_already_reported(row: Dict[str, Any]) -> bool:
        label = row.get(grouping)
        if label in (None, ""):
            label = row.get("word", row.get("lemma", row.get("kw")))
        frequency = row.get("f", row.get("frequency", row.get("freq")))
        if label in (None, "") or frequency in (None, ""):
            return False
        label_pattern = re.compile(
            rf"(?<![\w@]){re.escape(_normalised_question_text(label))}(?!\w)",
            re.IGNORECASE,
        )
        expected_numbers = {_normalise_field_value(frequency, field="f")}
        rate = row.get("per_million")
        if rate not in (None, ""):
            expected_numbers.add(
                _normalise_field_value(rate, field="per_million")
            )
        return any(
            label_pattern.search(_normalised_question_text(claim.text))
            and expected_numbers.issubset(
                set(_extract_numeric_tokens(claim.text))
            )
            for claim in accepted_claims
            if claim.claim_kind == "observation"
        )

    rows_already_reported = bool(accepted_claims) and all(
        row_is_already_reported(row) for row in rows
    )
    if rows_already_reported:
        # The verified model prose already carries every requested row. Add
        # only the missing shared denominator instead of duplicating the whole
        # result as a second, mechanically generated list.
        if denominator not in (None, ""):
            return _t(f"Bezugsbasis: {_display_number(denominator)} Tokens.", f"""Denominator: {_display_number(denominator)} tokens.""")
        return ""

    lines = [
        _t("### Angeforderte Frequenzrangliste", '### Requested frequency ranking'),
        _t(f"| Rang | {label_heading} | Absolute Frequenz | Pro Million |", f"""| Rank | {label_heading} | Absolute frequency | Per million |"""),
        "|---:|---|---:|---:|",
    ]
    derived_rates = False
    for index, row in enumerate(rows, start=1):
        label = row.get(grouping)
        if label in (None, ""):
            label = row.get("word", row.get("lemma", row.get("kw")))
        frequency = row.get("f", row.get("frequency", row.get("freq")))
        if label in (None, "") or frequency in (None, ""):
            return ""
        rate = row.get("per_million")
        numeric_frequency = _safe_float(frequency)
        numeric_denominator = _safe_float(denominator)
        computed_rate = (
            numeric_frequency * 1_000_000.0 / numeric_denominator
            if (
                numeric_frequency is not None
                and numeric_denominator is not None
                and numeric_denominator > 0
            )
            else None
        )
        if rate in (None, ""):
            if computed_rate is not None:
                rate = computed_rate
                derived_rates = True
        elif computed_rate is not None:
            # H9/V3 (a): wo f und pmw derselben Zeile gemeinsam ausgegeben
            # werden, rechnet der Renderer die Normalisierung IMMER selbst
            # nach. Weicht der mitgelieferte per_million-Wert arithmetisch
            # ab (>0.5% + Rundungsschlupf), gewinnt der selbst gerechnete
            # Wert — nie eine zweite, unabhaengig gebundene Zahl.
            numeric_rate = _safe_float(rate)
            if numeric_rate is None or abs(numeric_rate - computed_rate) > max(
                computed_rate * 0.005, 0.055
            ):
                rate = computed_rate
                derived_rates = True
        rendered_rate = "–" if rate in (None, "") else _display_number(rate, decimals=1)
        lines.append(
            f"| {index} | {_markdown_cell(label, code=True)} | "
            f"{_display_number(frequency)} | {rendered_rate} |"
        )

    notes: List[str] = []
    if denominator not in (None, ""):
        notes.append(
            _t(f"Nenner: {_display_number(denominator)} Tokens", f"""Denominator: {_display_number(denominator)} tokens""")
            + (
                _t("; die Werte pro Million wurden als f / Nenner × 1.000.000 berechnet", '. Values per million were calculated as f / denominator × 1,000,000')
                if derived_rates
                else ""
            )
            + "."
        )
    else:
        notes.append(
            _t("Für eine Normalisierung war in der Toolausgabe kein Tokennenner sichtbar.", 'The tool output provides no token denominator for normalisation.')
        )
    notes.append(
        _t("Die Darstellung ist auf diese angeforderten Ränge begrenzt", 'This display contains the requested ranks')
        + (
            _t("; die zugrunde liegenden Frequenzen sind dadurch nicht partiell.", '. The underlying frequencies are complete.')
            if item.truncated
            else "."
        )
    )
    return "\n".join([*lines, "", " ".join(notes)])


def _claim_repeats_requested_kwic_row(
    claim: ClaimDraft,
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Let the requested KWIC table present an individual result row once."""

    if claim.claim_kind != "observation" or not _question_requests_kwic_table(
        question_text
    ):
        return False
    kwic_evidence_ids = {
        item.id
        for item in evidence_items
        if item.tool == "run_cqlf_query" and item.status != "error"
    }
    fact_index = {fact.id: fact for fact in observed_facts}
    linked_facts = [
        fact_index[fact_id]
        for fact_id in claim.fact_ids
        if fact_id in fact_index
    ]
    return bool(
        len(linked_facts) == 1
        and linked_facts[0].fact_kind == "kwic_example"
        and kwic_evidence_ids.intersection(
            linked_facts[0].source_evidence_ids
        )
    )


def _claim_repeats_semantic_candidate_row(
    claim: ClaimDraft,
    question_text: str,
    observed_facts: Sequence[ObservedFact],
    accepted_claims: Sequence[ClaimDraft],
) -> bool:
    """Prefer a substantive requested synthesis over one-row narration."""

    if (
        claim.claim_kind != "observation"
        or _SEMANTIC_PATTERN_SYNTHESIS_REQUEST_PATTERN.search(
            question_text or ""
        )
        is None
        or not accepted_semantic_pattern_interpretation_is_substantive(
            accepted_claims,
            observed_facts,
            question_text=question_text,
        )
    ):
        return False
    fact_index = {fact.id: fact for fact in observed_facts}
    linked_facts = [
        fact_index[fact_id]
        for fact_id in claim.fact_ids
        if fact_id in fact_index
    ]
    return bool(
        len(linked_facts) == 1
        and linked_facts[0].fact_kind == "kwic_example"
        and any(
            "semantic_search" in str(source_id or "").casefold()
            or "transformer_search" in str(source_id or "").casefold()
            for source_id in linked_facts[0].source_evidence_ids
        )
    )


def _requested_kwic_result_table(
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
    *,
    observed_facts: Sequence[ObservedFact] = (),
    accepted_claims: Sequence[ClaimDraft] = (),
) -> str:
    if not _question_requests_kwic_table(question_text):
        return ""
    item = next(
        (
            item
            for item in evidence_items
            if item.tool == "run_cqlf_query"
            and item.status != "error"
            and (
                (
                    isinstance(item.fact_surface.get("rows"), list)
                    and item.fact_surface.get("rows")
                )
                or (
                    isinstance(item.raw_surface.get("rows"), list)
                    and item.raw_surface.get("rows")
                )
            )
        ),
        None,
    )
    if item is None:
        return ""
    row_surface = (
        item.fact_surface
        if isinstance(item.fact_surface.get("rows"), list)
        and item.fact_surface.get("rows")
        else item.raw_surface
    )
    rows = [
        row
        for row in row_surface.get("rows", [])
        if isinstance(row, dict)
    ]
    sample = item.raw_surface.get("sample")
    sampled = isinstance(sample, dict)
    count_match = re.search(
        r"\b(?P<count>\d+)\s+(?:sichtbar\w*\s+)?"
        r"(?:kwic[- ]?)?(?:zeilen?|belege?|beispiele?|treffer)\b",
        question_text or "",
        re.IGNORECASE,
    )
    requested_display = (
        int(count_match.group("count"))
        if count_match is not None
        else DEFAULT_GROUNDING_ROW_LIMIT
    )

    fact_index = {fact.id: fact for fact in observed_facts}

    def row_number(fact: ObservedFact) -> int | None:
        if (
            fact.fact_kind != "kwic_example"
            or item.id not in set(fact.source_evidence_ids)
        ):
            return None
        for quote in fact.grounding_quotes:
            match = re.match(r"kwic\[(\d+)\]", str(quote or "").strip())
            if match is not None:
                return int(match.group(1))
        match = re.search(r"_kwic_(\d+)$", fact.id)
        return int(match.group(1)) if match is not None else None

    claimed_numbers: List[int] = []
    for claim in accepted_claims:
        for fact_id in claim.fact_ids:
            fact = fact_index.get(fact_id)
            number = row_number(fact) if fact is not None else None
            if number is not None and number not in claimed_numbers:
                claimed_numbers.append(number)
    available_numbers = list(claimed_numbers)
    for fact in observed_facts:
        number = row_number(fact)
        if number is not None and number not in available_numbers:
            available_numbers.append(number)

    display_limit = min(
        len(rows),
        max(1, requested_display, len(claimed_numbers)),
    )
    if available_numbers:
        selected_numbers = [
            number
            for number in available_numbers
            if 1 <= number <= len(rows)
        ][:display_limit]
        if len(selected_numbers) < display_limit:
            selected_numbers.extend(
                number
                for number in range(1, len(rows) + 1)
                if number not in selected_numbers
            )
            selected_numbers = selected_numbers[:display_limit]
    else:
        selected_numbers = list(range(1, display_limit + 1))
    visible_rows = [(number, rows[number - 1]) for number in selected_numbers]
    if not visible_rows:
        return ""

    heading = (
        _t("### Reproduzierbare KWIC-Stichprobe", '### Reproducible concordance sample')
        if sampled and sample.get("seed") not in (None, "")
        else _t("### Sichtbare KWIC-Evidenz", '### Visible concordance evidence')
    )
    provenance: List[str] = []
    total = item.raw_surface.get("total")
    population = sample.get("population") if sampled else None
    if total not in (None, ""):
        provenance.append(_t(f"Gesamttrefferzahl: {_display_number(total)}", f"""Total hits: {_display_number(total)}"""))
    if sampled:
        drawn = sample.get("drawn") or sample.get("requested") or len(rows)
        provenance.append(
            _t(f"gezogene Stichprobe: {_display_number(drawn)} Zeilen", f"""drawn sample: {_display_number(drawn)} lines""")
        )
        if str(drawn) != str(len(visible_rows)):
            provenance.append(
                _t(f"davon hier als Belegauswahl gezeigt: {len(visible_rows)}", f"""shown here as evidence: {len(visible_rows)}""")
            )
        if claimed_numbers:
            provenance.append(
                _t("alle in den Aussagen verwendeten Einzelbelege enthalten", 'includes every individual example used in the claims')
            )
        if population not in (None, "") and population != total:
            provenance.append(f"Sampling-Population: {_display_number(population)}")
        if sample.get("seed") not in (None, ""):
            provenance.append(f"Seed: {sample.get('seed')}")
        if sample.get("method") not in (None, ""):
            provenance.append(f"Verfahren: {sample.get('method')}")
    else:
        provenance.append(_t(f"sichtbare Auswahl: {len(visible_rows)}", f"""visible selection: {len(visible_rows)}"""))
    query = _normalise_example_text(item.raw_surface.get("query"))
    if query:
        provenance.append(f"Abfrage: `{query.replace('`', '´')}`")

    lines = [
        heading,
        "; ".join(provenance) + ".",
        _t("| Stichprobenzeile | Linkskontext | Treffer | Rechtskontext |", '| Sample line | Left context | Match | Right context |'),
        "|---:|---|---|---|",
    ]
    for number, row in visible_rows:
        lines.append(
            f"| {number} | {_markdown_cell(row.get('left'))} | "
            f"{_markdown_cell(row.get('match') or row.get('kw') or row.get('word'), code=True)} | "
            f"{_markdown_cell(row.get('right'))} |"
        )
    annotation_risks = _kwic_annotation_risk_rows(
        query,
        [row for _number, row in visible_rows],
    )
    if annotation_risks:
        lines.extend(
            [
                "",
                _t("Die Abfrage trifft die im Index gespeicherten Annotationen. "
                "Auffällige Handle-, Hashtag- oder Interpunktionsformen in den "
                "Matchspannen sind mögliche Tagging-/Tokenisierungsartefakte "
                "und keine unabhängig validierten grammatischen Belege.", 'The query matches annotations stored in the index. Unusual handles, hashtags or punctuation in matching spans may reflect tagging or tokenisation artefacts. These spans have not been independently validated as grammatical evidence.'),
            ]
        )
    if sampled and sample.get("population_partial") is True:
        lines.extend(
            [
                "",
                _t("Die ausgewiesene Sampling-Population ist partiell; die "
                "Stichprobe darf nicht als Stichprobe aller Korpustreffer gelten.", 'The reported sampling population is partial. The sample therefore represents that population rather than all corpus hits.'),
            ]
        )
    elif not sampled:
        lines.extend(
            [
                "",
                _t("Dies ist eine sichtbare Auswahl der zurückgegebenen KWIC-Zeilen, "
                "keine behauptete Zufallsstichprobe.", 'This is a visible selection of the returned concordance lines. No random sampling is claimed.'),
            ]
        )
    return "\n".join(lines)


def _requested_collocation_result_tables(
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
) -> str:
    if re.search(r"\bkollokat\w*\b", question_text or "", re.IGNORECASE) is None:
        return ""
    requested_terms = same_corpus_collocation_terms(question_text)
    items, comparable = _selected_collocation_profiles(
        question_text,
        evidence_items,
    )
    if not items:
        return ""

    count_items = _matching_collocation_count_items(
        requested_terms,
        items,
        evidence_items,
    )
    node_counts = {
        term: item.raw_surface.get("total")
        for term, item in count_items.items()
    }

    sections: List[str] = [_t("### Sichtbare Kollokationsprofile", '### Visible collocation profiles')]
    if requested_terms and not comparable:
        sections.append(
            _t("Die verfügbaren Profile wurden mit unterschiedlichen Parametern "
            "berechnet und sind daher nicht direkt vergleichbar.", 'The available profiles were calculated with different parameters, so they are not directly comparable.')
        )
    for item in items:
        try:
            args = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        term = _normalise_example_text(
            item.raw_surface.get("requested_term") or args.get("term")
        ) or _t("Suchterm", 'search term')
        sort_by = str(
            item.raw_surface.get("sort_by") or args.get("sort_by") or "logdice"
        ).strip()
        rows = [
            row for row in item.raw_surface.get("rows", []) if isinstance(row, dict)
        ][:10]
        metric_key = next(
            (
                key
                for key in (sort_by, "logdice", "mi3", "mi", "t", "ll")
                if any(row.get(key) not in (None, "") for row in rows)
            ),
            "",
        )
        method_bits = [
            _t(f"Attribut: {item.raw_surface.get('method', {}).get('attribute')}", f"""Attribute: {item.raw_surface.get('method', {}).get('attribute')}""")
            if isinstance(item.raw_surface.get("method"), dict)
            and item.raw_surface.get("method", {}).get("attribute")
            else "",
            _t(f"Fenster: ±{item.raw_surface.get('window')} Tokens", f"""Window: ±{item.raw_surface.get('window')} tokens""")
            if item.raw_surface.get("window") not in (None, "")
            else "",
            _t("satzbegrenzt: ", 'within sentence: ')
            + ("ja" if item.raw_surface.get("within_sentence") else "nein")
            if item.raw_surface.get("within_sentence") is not None
            else "",
            _t(f"Mindestfrequenz: {item.raw_surface.get('min_freq')}", f"""Minimum frequency: {item.raw_surface.get('min_freq')}""")
            if item.raw_surface.get("min_freq") not in (None, "")
            else "",
            _t(f"Sortierung: {sort_by}", f"""Sort order: {sort_by}"""),
        ]
        count = node_counts.get(term.casefold())
        if count not in (None, ""):
            method_bits.insert(0, _t(f"Knotenfrequenz: {_display_number(count)}", f"""Node frequency: {_display_number(count)}"""))
        sections.extend(
            [
                "",
                f"#### `{term.replace('`', '´')}`",
                "; ".join(bit for bit in method_bits if bit) + ".",
            ]
        )
        if not rows:
            min_freq = item.raw_surface.get("min_freq")
            threshold = (
                _display_number(min_freq)
                if min_freq not in (None, "")
                else _t("die ausgewiesene Mindestfrequenz", 'the reported minimum frequency')
            )
            # ZWEITE NAHT derselben Klasse, beim ersten Anlauf uebersehen.
            #
            # Dieser Text behauptete bei NULL TREFFERN, die Mindestfrequenz
            # habe gebunden, und empfahl eine niedrigere Schwelle fuer ein
            # Wort, das im Korpus nicht vorkommt. Ein adversarialer Pruefer
            # hat ihn gefunden, nachdem der Fix an der Schwesternaht
            # (grounding_facts) als erledigt gemeldet war: die Bedingung
            # hier prueft ausschliesslich "if not rows" und kennt weder
            # status noch node_frequency.
            knoten = item.raw_surface.get("node_frequency")
            try:
                ohne_treffer = knoten is not None and int(knoten) <= 0
            except (TypeError, ValueError):
                ohne_treffer = False
            if ohne_treffer:
                sections.append(
                    _t(f"Der Knoten kommt in diesem Korpus null Mal vor. Es "
                    f"wurde nichts gemessen, und die Aufnahmeschwelle "
                    f"({threshold}) hat nicht gebunden: die leere Tabelle "
                    "belegt keine Seltenheit. Eine niedrigere Schwelle "
                    "ändert daran nichts.", f"""The node occurs zero times in this corpus. There was nothing to measure, so the inclusion threshold ({threshold}) did not exclude any observations. Lowering it cannot add occurrences of this node.""")
                )
                continue
            sections.append(
                _t("Keine Kollokationszeile erfüllte unter diesen Parametern "
                "die ausgewiesene Mindestfrequenz. Die leere Tabelle ist auf "
                f"diese Aufnahmeschwelle ({threshold}) begrenzt. Ob darunter "
                "weitere gemeinsame Vorkommen existieren, bleibt unbekannt; "
                "das lässt sich nur mit einer niedrigeren Schwelle prüfen. "
                "Eine mögliche Verwendungsweise erfordert zusätzlich "
                "KWIC-Kontexte.", f"""No collocation row met the minimum frequency under these parameters. The empty table reflects the inclusion threshold ({threshold}). A lower threshold is needed to test for less frequent co-occurrences. Usage interpretation also requires concordance contexts.""")
            )
            continue
        # Include f2 when available so logDice can be reconstructed from its
        # pair count, node frequency and collocate frequency. Omit an empty column.
        zeigt_f2 = any(row.get("f2") not in (None, "") for row in rows)
        sections.extend(
            [
                _t("| Rang | Kollokat | Gemeinsames Auftreten f |", '| Rank | Collocate | Co-occurrence frequency f |')
                + (_t(" Korpusfrequenz f2 |", ' Corpus frequency f2 |') if zeigt_f2 else "")
                + (f" {metric_key} |" if metric_key else ""),
                "|---:|---|---:|"
                + ("---:|" if zeigt_f2 else "")
                + ("---:|" if metric_key else ""),
            ]
        )
        for index, row in enumerate(rows, start=1):
            label = row.get("word", row.get("kw"))
            frequency = row.get("f", row.get("observed", row.get("frequency")))
            if label in (None, "") or frequency in (None, ""):
                continue
            rank = row.get("rank", index)
            line = (
                f"| {_display_number(rank)} | {_markdown_cell(label, code=True)} | "
                f"{_display_number(frequency)} |"
            )
            if zeigt_f2:
                f2_wert = row.get("f2")
                line += " " + (
                    _display_number(f2_wert)
                    if f2_wert not in (None, "")
                    else "–"
                ) + " |"
            if metric_key:
                metric_value = row.get(metric_key)
                line += " " + (
                    _display_number(metric_value)
                    if metric_value not in (None, "")
                    else "–"
                ) + " |"
            sections.append(line)
    return "\n".join(sections) if len(sections) > 1 else ""


def _requested_ngram_result_table(
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
) -> str:
    """Render explicitly requested exact rows; interpretation stays model-owned."""

    requested = _requested_ngram_result_count(question_text)
    if requested is None:
        return ""
    rows: List[Dict[str, Any]] = []
    for item in evidence_items:
        if item.tool != "ngram_frequency" or item.status == "error":
            continue
        raw_rows = item.raw_surface.get("rows")
        if isinstance(raw_rows, list):
            rows = [row for row in raw_rows if isinstance(row, dict)][
                :requested
            ]
        if rows:
            break
    if len(rows) < requested:
        return ""

    lines = [
        _t("### Angeforderte Rangliste", '### Requested ranking'),
        _t("| Rang | N-Gramm | Frequenz | n |", '| Rank | N-gram | Frequency | n |'),
        "|---:|---|---:|---:|",
    ]
    previous_frequency: Any = object()
    frequency_rank = 0
    has_ties = False
    for row_index, row in enumerate(rows, start=1):
        label = _normalise_example_text(row.get("ngram")).replace("|", "\\|")
        frequency = row.get("freq", row.get("frequency"))
        n_value = row.get("n", "")
        if not label or frequency in (None, ""):
            return ""
        if frequency != previous_frequency:
            frequency_rank = row_index
        else:
            has_ties = True
        previous_frequency = frequency
        rendered_frequency = (
            f"{frequency:,}".replace(",", ".")
            if isinstance(frequency, int)
            else str(frequency)
        )
        lines.append(
            f"| {frequency_rank} | `{label}` | {rendered_frequency} | {n_value} |"
        )
    if has_ties:
        lines.extend(
            [
                "",
                _t("Gleiche Frequenzen teilen denselben Frequenzrang; die "
                "Reihenfolge innerhalb eines Gleichstands ist durch die "
                "Rohfrequenz nicht begründet. Am Rand des sichtbaren Fensters "
                "können weitere gleich häufige N-Gramme liegen.", 'Equal frequencies share a frequency rank. Raw frequency does not determine the order within a tie. Further equally frequent n-grams may fall beyond the visible window.'),
            ]
        )
    visible_lengths = {
        row.get("n") for row in rows if row.get("n") not in (None, "")
    }
    if len(visible_lengths) == 1:
        only_n = next(iter(visible_lengths))
        lines.extend(
            [
                "",
                _t(f"Im sichtbaren Fenster kommt nur n={only_n} vor; das ist "
                "keine Aussage über nicht sichtbare Ränge.", f"""The visible window contains only n={only_n}. Ranks outside this window are not shown."""),
            ]
        )
    return "\n".join(lines)


def _claim_repeats_requested_ngram_rows(
    claim: ClaimDraft,
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Hide a prose copy when the renderer already supplies the exact table."""

    requested = _requested_ngram_result_count(question_text)
    if requested is None or claim.claim_kind != "observation":
        return False
    rows: List[Dict[str, Any]] = []
    for item in evidence_items:
        if item.tool == "ngram_frequency" and item.status != "error":
            raw_rows = item.raw_surface.get("rows")
            if isinstance(raw_rows, list):
                rows = [row for row in raw_rows if isinstance(row, dict)][
                    :requested
                ]
            break
    if len(rows) < requested:
        return False
    surface = _normalised_question_text(claim.text)
    numeric_tokens = set(_extract_numeric_tokens(claim.text))
    fact_index = {fact.id: fact for fact in observed_facts}
    linked_terms = {
        term.casefold()
        for fact_id in claim.fact_ids
        for fact in [fact_index.get(fact_id)]
        if fact is not None and fact.fact_kind == "ranked_row"
        for term in _ngram_surface_terms(fact)
        if term.casefold() in surface
    }
    if (
        len(linked_terms) == 1
        and next(iter(linked_terms)) in surface
        and _NGRAM_HYPOTHESIS_PATTERN.search(claim.text or "") is None
        and _NGRAM_VALIDATION_PATTERN.search(claim.text or "") is None
    ):
        # The exact table is the canonical surface for an atomic row. Keep
        # comparisons and hypotheses, but do not let per-row prose introduce
        # a second, potentially inconsistent rank narration.
        return True
    all_labels_visible = all(
        _normalised_question_text(row.get("ngram")) in surface
        for row in rows
    )
    if not all_labels_visible:
        return False
    all_frequencies_visible = all(
        _normalize_number_token(
            str(row.get("freq", row.get("frequency"))),
            integer_grouping=True,
        )
        in numeric_tokens
        for row in rows
    )
    explicit_requested_list = re.search(
        r"\b(?:rangliste|top[- ]?\d+|oberst\w*|häufigst\w*|"
        r"haeufigst\w*|alle\s+(?:zehn|10))\b",
        claim.text or "",
        re.IGNORECASE,
    ) is not None
    return all_frequencies_visible or explicit_requested_list


def _claim_repeats_requested_frequency_rows(
    claim: ClaimDraft,
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
) -> bool:
    """Drop a list preamble or row copy when the exact table is rendered."""

    requested = _requested_frequency_result_count(question_text)
    if requested is None or claim.claim_kind != "observation":
        return False
    item = next(
        (
            item
            for item in evidence_items
            if item.tool == "frequency_list" and item.status != "error"
        ),
        None,
    )
    if item is None or not isinstance(item.raw_surface.get("rows"), list):
        return False
    rows = [
        row for row in item.raw_surface.get("rows", []) if isinstance(row, dict)
    ][:requested]
    if len(rows) < requested:
        return False
    surface = _normalised_question_text(claim.text)
    labels = [
        _normalised_question_text(
            row.get(_frequency_group_by(item))
            or row.get("word")
            or row.get("lemma")
            or row.get("kw")
        )
        for row in rows
    ]
    visible_labels = sum(bool(label and label in surface) for label in labels)
    if visible_labels >= max(2, len(labels) - 1):
        return True
    return bool(
        visible_labels == 0
        and re.search(
            r"\b(?:folgend\w*\s+(?:rangfolge|liste)|"
            r"haben\s+folgend\w*\s+(?:rangfolge|frequenz)|"
            r"die\s+(?:zehn|\d+)\s+häufigst\w*\s+wortformen?\b)",
            claim.text or "",
            re.IGNORECASE,
        )
    )


def _claim_repeats_requested_collocation_rows(
    claim: ClaimDraft,
    question_text: str,
    evidence_items: Sequence[EvidenceItem],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Hide exact row prose already represented by the result table."""

    if (
        claim.claim_kind != "observation"
        or re.search(
            r"\bkollokat\w*\b",
            question_text or "",
            re.IGNORECASE,
        )
        is None
    ):
        return False
    selected_items, _comparable = _selected_collocation_profiles(
        question_text,
        evidence_items,
    )
    rendered_rows_by_source: Dict[str, List[Tuple[str, str]]] = {}
    for item in selected_items:
        rows = [
            row
            for row in item.raw_surface.get("rows", [])
            if isinstance(row, dict)
        ][:10]
        rendered_rows_by_source[item.id] = [
            (
                _normalise_field_value(
                    row.get("rank", index),
                    field="rank",
                ),
                _normalise_example_text(
                    row.get("word", row.get("kw"))
                ),
            )
            for index, row in enumerate(rows, start=1)
            if row.get("word", row.get("kw")) not in (None, "")
        ]
    if not any(rendered_rows_by_source.values()):
        return False
    fact_index = {fact.id: fact for fact in observed_facts}
    linked_facts = [
        fact_index[fact_id]
        for fact_id in claim.fact_ids
        if fact_id in fact_index
    ]
    if not linked_facts or len(linked_facts) != len(set(claim.fact_ids)):
        return False

    def fact_is_rendered_row(fact: ObservedFact) -> bool:
        if fact.fact_kind != "ranked_row":
            return False
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        ranks = _source_values_for_field("rank", surface)
        for source_id in fact.source_evidence_ids:
            for rank, label in rendered_rows_by_source.get(
                str(source_id or ""),
                [],
            ):
                if rank in ranks and _contains_literal_label(surface, label):
                    return True
        return False

    return all(fact_is_rendered_row(fact) for fact in linked_facts)


def _claim_repeats_lexical_diversity_metrics(
    claim: ClaimDraft,
    evidence_items: Sequence[EvidenceItem],
) -> bool:
    """Hide pure metric restatements already rendered in the evidence block."""

    if claim.claim_kind != "observation":
        return False
    item = next(
        (
            item
            for item in evidence_items
            if item.tool == "lexical_diversity" and item.status != "error"
        ),
        None,
    )
    if item is None:
        return False
    text = str(claim.text or "")
    labels = {
        label
        for label in ("ttr", "sttr", "mattr")
        if re.search(rf"\b{label}\b", text, re.IGNORECASE)
        and item.raw_surface.get(label) not in (None, "")
    }
    if not labels:
        return False
    if re.search(
        r"\b(?:bedeutet|heißt|heisst|entspricht|zeigt|deutet|"
        r"längen|laengen|belastbar|zuverlässig|zuverlaessig|robust|"
        r"hoch|niedrig|typisch|divers|vielfalt|einzigartig)\w*\b",
        text,
        re.IGNORECASE,
    ):
        return False
    allowed_numbers = {
        _normalise_field_value(item.raw_surface[label], field=label)
        for label in labels
    }
    claimed_numbers = _extract_numeric_tokens(text)
    return bool(claimed_numbers) and all(
        _numeric_token_is_supported(number, allowed_numbers)
        for number in claimed_numbers
    )


def _directional_keyness_result_table(
    evidence_items: Sequence[EvidenceItem],
) -> str:
    """Show a small balanced result table; interpretation remains model-owned."""

    direction_contexts = _keyness_direction_contexts(evidence_items)
    docset_labels: Dict[str, str] = {}
    for item in evidence_items:
        if item.tool != "create_docset":
            continue
        docset_id = str(item.raw_surface.get("docset_id") or "").strip()
        label = _normalise_example_text(item.raw_surface.get("label"))
        if docset_id and label:
            docset_labels[docset_id] = label

    rows: List[Dict[str, Any]] = []
    direction_labels = {"target": _t("Zielseite", 'target'), "reference": _t("Referenzseite", 'reference')}
    frequency_labels = {"target": _t("Ziel-f", 'target f'), "reference": _t("Referenz-f", 'reference f')}
    for item in evidence_items:
        if item.tool != "keyness" or item.status == "error":
            continue
        raw_rows = item.raw_surface.get("rows")
        if isinstance(raw_rows, list):
            rows = [row for row in raw_rows if isinstance(row, dict)]
        try:
            query = json.loads(item.query) if item.query else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            query = {}
        if isinstance(query, dict):
            target_label = docset_labels.get(
                str(query.get("target_docset_id") or "").strip()
            )
            reference_label = docset_labels.get(
                str(query.get("reference_docset_id") or "").strip()
            )
            if target_label:
                direction_labels["target"] = target_label
            if reference_label:
                direction_labels["reference"] = reference_label
        context = direction_contexts.get(item.id, {})
        if context:
            for direction in ("target", "reference"):
                label = _normalise_example_text(
                    context.get(f"{direction}_label")
                ).replace("|", "\\|")
                if label:
                    direction_labels[direction] = label
                    frequency_labels[direction] = f"{label}-f"
        break
    if not rows:
        return ""

    selected: List[Dict[str, Any]] = []
    directional = {
        direction: [
            row
            for row in rows
            if str(row.get("direction") or "").strip().casefold()
            == direction
        ]
        for direction in ("target", "reference")
    }
    if all(directional.values()):
        selected = [
            *directional["target"][:3],
            *directional["reference"][:3],
        ]
    else:
        selected = rows[:6]

    def metric(value: Any) -> str:
        if isinstance(value, bool):
            return "ja" if value else "nein"
        if isinstance(value, int):
            return f"{value:,}".replace(",", ".")
        if isinstance(value, float):
            if value != 0.0 and abs(value) < 0.001:
                return f"{value:.3e}"
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value)

    lines = [
        _t("### Sichtbare gerichtete Keyness-Ergebnisse", '### Visible directional keyness results'),
        _t("| Ausdruck | Richtung | {} | {} | Δ pro Mio. | LL (signiert) | q |", '| Expression | Direction | {} | {} | Δ per million | LL (signed) | q |').format(
            frequency_labels["target"],
            frequency_labels["reference"],
        ),
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in selected:
        label = _normalise_example_text(
            row.get("word") or row.get("kw")
        ).replace("|", "\\|")
        direction = str(row.get("direction") or "").strip().casefold()
        required = (
            row.get("target_freq"),
            row.get("reference_freq"),
            row.get("diff_per_million"),
            row.get("ll_signed"),
            row.get("q_value"),
        )
        if not label or any(value in (None, "") for value in required):
            continue
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} | {} |".format(
                label,
                direction_labels.get(direction, direction or "–"),
                *(metric(value) for value in required),
            )
        )
    return "\n".join(lines) if len(lines) > 3 else ""


def _retrieval_assessment_excerpt_lines(
    assessments: Sequence[Dict[str, Any]],
    observed_facts: Sequence[ObservedFact],
    *,
    fact_ids: set[str] | None = None,
    neutral_labels: bool = False,
) -> List[str]:
    """Render validated excerpts without turning local labels into prevalence."""

    relation_labels = {
        "supports": _t("Ausschnitt mit lokaler Stützung", 'Excerpt with local support'),
        "related_support": _t("Ausschnitt mit verwandter negativer Rahmung", 'Excerpt with related negative framing'),
        "counterevidence": _t("Ausschnitt mit lokaler Gegenlesart", 'Excerpt with a local counter-reading'),
        "mixed_or_unclear": _t("Ausschnitt mit unklarer Richtung", 'Excerpt with unclear direction'),
    }
    object_labels = {
        "associated_group_or_actor": _t("bewertet Gruppe/Akteur", 'evaluates group or actor'),
        "associated_policy_or_practice": _t("bewertet Politik/Praxis", 'evaluates policy or practice'),
        "associated_effect_or_outcome": _t("bewertet Folge/Wirkung", 'evaluates consequence or effect'),
    }
    lines: List[str] = []
    seen_quotes: set[str] = set()
    fact_index = {fact.id: fact for fact in observed_facts}
    for assessment in assessments:
        fact_id = str(assessment.get("fact_id", "") or "")
        if fact_ids is not None and fact_id not in fact_ids:
            continue
        topic_relation = str(
            assessment.get("topic_relation", "") or ""
        ).strip()
        relation = str(
            assessment.get("relation_to_requested_conclusion", "") or ""
        ).strip()
        if topic_relation not in {"relevant", "marginal"}:
            continue
        evaluated_object_type = str(
            assessment.get("evaluated_object_type", "") or ""
        ).strip()
        label = relation_labels.get(relation)
        if relation == "counterevidence" and evaluated_object_type != "target_topic":
            label = (
                _t("Ausschnitt mit verwandtem Kontext ohne eindeutige Stützung "
                "der Zielbehauptung", 'Excerpt with related context that does not clearly support the target claim')
            )
        fact = fact_index.get(fact_id)
        source_quote = ""
        if fact is not None:
            source_quote = next(
                (
                    str(value).split("=", 1)[1]
                    for value in fact.grounding_quotes
                    if str(value or "").casefold().startswith("hit=")
                    and "=" in str(value)
                ),
                "",
            )
        quote = _normalise_example_text(
            source_quote or assessment.get("quote", "")
        )
        quote = quote.strip(" \t\n\r\"'„“‚‘«»‹›`")
        quote = _compact_text(quote, 560)
        signature = _normalised_question_text(quote)
        if (
            (not neutral_labels and not label)
            or not quote
            or signature in seen_quotes
        ):
            continue
        seen_quotes.add(signature)
        qualifier = _t(" · thematisch indirekt", ' · indirectly related to the topic') if topic_relation == "marginal" else ""
        object_qualifier = object_labels.get(
            evaluated_object_type,
            "",
        )
        if object_qualifier:
            qualifier += f" · {object_qualifier}"
        escaped_quote = quote.replace("|", "\\|")
        locator = ""
        if fact is not None:
            doc_id = next(
                (
                    str(value).split("=", 1)[1].strip()
                    for value in fact.grounding_quotes
                    if str(value or "").casefold().startswith("doc_id=")
                    and "=" in str(value)
                ),
                "",
            )
            if doc_id:
                locator = _t(f" · Dokument `{doc_id}`", f" · document `{doc_id}`")
        if neutral_labels:
            lines.append(_t(f"> **Beleg:** „{escaped_quote}“{locator}", f"""> **Evidence:** “{escaped_quote}”{locator}"""))
        else:
            lines.append(
                f"- **{label}{qualifier}:** „{escaped_quote}“{locator}"
            )
        if len(lines) >= 6:
            break
    return lines


def _retrieval_assessment_exclusion_lines(
    assessments: Sequence[Dict[str, Any]],
    observed_facts: Sequence[ObservedFact],
) -> List[str]:
    """Expose discarded retrieval rows so the answer cannot hide poor precision."""

    lines: List[str] = []
    seen_quotes: set[str] = set()
    fact_index = {fact.id: fact for fact in observed_facts}
    for assessment in assessments:
        topic_relation = str(
            assessment.get("topic_relation", "") or ""
        ).strip()
        if topic_relation != "off_topic":
            continue
        fact = fact_index.get(str(assessment.get("fact_id", "") or ""))
        source_quote = ""
        if fact is not None:
            source_quote = next(
                (
                    str(value).split("=", 1)[1]
                    for value in fact.grounding_quotes
                    if str(value or "").casefold().startswith("hit=")
                    and "=" in str(value)
                ),
                "",
            )
        quote = _normalise_example_text(
            source_quote or assessment.get("quote", "")
        ).strip(" \t\n\r\"'„“‚‘«»‹›`")
        quote = _compact_text(quote, 560)
        signature = _normalised_question_text(quote)
        if not quote or signature in seen_quotes:
            continue
        seen_quotes.add(signature)
        locator = ""
        if fact is not None:
            doc_id = next(
                (
                    str(value).split("=", 1)[1].strip()
                    for value in fact.grounding_quotes
                    if str(value or "").casefold().startswith("doc_id=")
                    and "=" in str(value)
                ),
                "",
            )
            if doc_id:
                locator = _t(f" · Dokument `{doc_id}`", f" · document `{doc_id}`")
        lines.append(
            _t(f"- **Nicht als Themenbeleg gewertet:** „{quote}“{locator}", f"""- **Excluded as topic evidence:** “{quote}”{locator}""")
        )
        if len(lines) >= 6:
            break
    return lines


def _retrieval_precision_note(
    assessments: Sequence[Dict[str, Any]],
    *,
    covered_fact_ids: set[str] | None = None,
) -> str:
    """State retrieval precision and accepted analytical coverage honestly."""

    by_fact_id = {
        str(assessment.get("fact_id", "") or ""): str(
            assessment.get("topic_relation", "") or ""
        ).strip()
        for assessment in assessments
        if str(assessment.get("fact_id", "") or "")
        and str(assessment.get("topic_relation", "") or "").strip()
        in {"relevant", "marginal", "off_topic"}
    }
    total = len(by_fact_id)
    excluded = sum(
        relation == "off_topic" for relation in by_fact_id.values()
    )
    retained_ids = {
        fact_id
        for fact_id, relation in by_fact_id.items()
        if relation in {"relevant", "marginal"}
    }
    retained = len(retained_ids)
    covered = (
        len(retained_ids.intersection(covered_fact_ids))
        if covered_fact_ids is not None
        else None
    )
    if not total or (
        not excluded
        and (covered is None or covered == retained)
    ):
        return ""

    sentences: List[str] = []
    if excluded:
        sentences.append(
            _t(f"{excluded} von {total} sichtbaren Retrieval-Kandidaten "
            "wurden nach Prüfung als themenfremd ausgeschlossen; "
            f"{retained} blieben als relevante oder randständige Kandidaten.", f"""After review, {excluded} of {total} visible retrieval candidates were excluded as off-topic. {retained} remained relevant or marginal candidates.""")
        )
    else:
        sentences.append(
            _t(f"Alle {retained} sichtbaren Retrieval-Kandidaten blieben "
            "als relevante oder randständige Kandidaten.", f"""All {retained} visible retrieval candidates remained relevant or marginal candidates.""")
        )
    if covered is not None and retained:
        uncovered = retained - covered
        if covered == retained:
            sentences.append(
                _t(f"Die verifizierte Interpretation bezieht alle {retained} ein.", f"""The verified interpretation covers all {retained}.""")
            )
        elif covered:
            noun = _t("Kandidat", 'candidate') if uncovered == 1 else _t("Kandidaten", 'candidates')
            verb = "bleibt" if uncovered == 1 else "bleiben"
            sentences.append(
                _t(f"Die verifizierte Interpretation bezieht {covered} von "
                f"{retained} ein; {uncovered} {noun} {verb} ohne akzeptierte "
                "Deutung.", f"""The verified interpretation covers {covered} of {retained}. {uncovered} candidate(s) have no accepted interpretation.""")
            )
        else:
            sentences.append(
                _t("Für keinen dieser Kandidaten liegt eine akzeptierte Deutung "
                "vor.", 'None of these candidates has an accepted interpretation.')
            )
    if excluded:
        sentences.append(
            _t("Damit enthält die sichtbare Retrieval-Menge in diesem Lauf "
            "konkrete "
            "Fehlretrievals; das ist keine allgemeine Präzisionsschätzung des "
            "Systems.", 'These exclusions document retrieval errors in this run. They do not estimate the overall precision of the system.')
        )
    sentences.append(
        _t("Diese Zuordnung ist weder ein Prävalenzurteil noch eine Zuschreibung "
        "von Autorintention.", 'This classification establishes neither prevalence nor authorial intention.')
    )
    return " ".join(sentences)


def _claim_dedup_signature(text: str) -> str:
    """Normalisierte Duplikat-Signatur: casefold, Whitespace kollabiert."""

    return " ".join(str(text or "").split()).casefold()


# Sichtbares Label eines Claims: fettes (**Label**:) oder Code-Label
# (`label`:) am Zeilenanfang, optional hinter einem Listenzeichen. Bewusst
# eng gefasst, damit gewoehnliche Prosa mit spaetem Doppelpunkt nicht als
# Label zaehlt (H6/B8-S5, deckt die B5-Duplikat-Labels ab).
_VISIBLE_CLAIM_LABEL_PATTERN = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*(?P<bold>[^*\n]{1,64})\*\*|`(?P<code>[^`\n]{1,64})`)\s*:"
)
_GENERIC_CLAIM_LABELS = frozenset(
    {
        "befund",
        "beobachtung",
        "beobachtungen",
        "interpretation",
        "deutung",
        "hypothese",
        "hypothesen",
        "limitation",
        "limitationen",
        "grenzen",
        "hinweis",
        "beispiel",
        "beispiele",
        "evidenz",
        "kernbefund",
    }
)


def _visible_claim_label(text: str) -> str:
    """Sichtbares Claim-Label fuer die Duplikat-Faltung, sonst ''."""

    match = _VISIBLE_CLAIM_LABEL_PATTERN.match(str(text or ""))
    if not match:
        return ""
    label = match.group("bold") or match.group("code") or ""
    label = " ".join(label.split()).casefold()
    if not label or label in _GENERIC_CLAIM_LABELS:
        return ""
    return label


#: Woerter, mit denen ein Satz auf etwas VORHER Gesagtes zeigt. Wird ein
#: solcher Satz nach vorn gezogen, verweist er ins Leere. Die Liste ist
#: keine Stichwortsuche nach Bedeutung, sondern die geschlossene Klasse der
#: satzinitialen Rueckverweise des Deutschen.
_RUECKVERWEIS = re.compile(
    r"^\W*(?:"
    r"da(?:r(?:aus|in|an|auf|ueber|über|unter))?|damit|dadurch|"
    r"deshalb|deswegen|daher|somit|folglich|also|"
    r"dies|diese[rsnm]?|jene[rsnm]?|"
    r"letztere[rsnm]?|ersterer|"
    r"beide[rsnm]?|solche[rsnm]?"
    r")\b",
    re.IGNORECASE,
)


def _deutung_zuerst(
    claims: Sequence["ClaimDraft"],
) -> List["ClaimDraft"]:
    """Move an eligible closing interpretation to the beginning.

    Move only the final claim, and only when it is interpretative, has no
    back-reference, follows other claims and the first claim is not already
    an interpretation. This preserves argument chains whose opening words
    depend on earlier observations. Selection uses position rather than an
    estimate of which interpretation is strongest.
    """
    if len(claims) < 2:
        return list(claims)
    # STEHT OBEN SCHON EINE DEUTUNG, ist nichts zu tun. Gemessen an der
    # Antwort auf die Druckreife-Frage vom 2026-09-01: sie beginnt mit
    # "Ein unbedingter Satz ueber einen allgemeinen Unterschied zwischen
    # menschlichen und maschinellen Texten ist aus dieser Analyse nicht
    # vertretbar." Das ist das Urteil, um das gebeten wurde. Den letzten,
    # schwaecheren Deutungssatz davor zu schieben wuerde diese Antwort
    # VERSCHLECHTERN. Das Ziel ist, dass der Leser zuerst auf Bedeutung
    # trifft, nicht dass irgendetwas umsortiert wird.
    if getattr(claims[0], "claim_kind", "") == "interpretation":
        return list(claims)
    letzter = claims[-1]
    if getattr(letzter, "claim_kind", "") != "interpretation":
        return list(claims)
    if _RUECKVERWEIS.match(getattr(letzter, "text", "") or ""):
        return list(claims)
    return [letzter, *claims[:-1]]


def build_verified_claim_markdown(
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    observed_facts: Sequence[ObservedFact],
    *,
    deliverable_kind: str = "",
    question_text: str = "",
    evidence_items: Sequence[EvidenceItem] = (),
    evidence_gaps: Sequence[str] = (),
    retrieval_candidate_assessments: Sequence[Dict[str, Any]] = (),
    include_diagnostic_appendix: bool = True,
) -> str:
    """Compose the answer directly from accepted model claims.

    The model owns wording, ordering, interpretation, and emphasis. This
    renderer only supplies light presentation and never replaces the accepted
    claims with a family-specific template.
    """
    accepted = set(accepted_claim_ids)
    claims = [claim for claim in envelope.claims if claim.id in accepted]
    confirmation_pressure = _is_confirmation_pressure_prompt(question_text)
    confirmation_boundary = bool(
        confirmation_pressure
        and _observed_facts_supply_confirmation_boundary(observed_facts)
    )
    if not claims and not confirmation_boundary:
        return ""

    interpretations = [
        claim.text for claim in claims if claim.claim_kind == "interpretation"
    ]
    promoted_lookup_result_ids = {
        claim.id
        for claim in claims
        if deliverable_kind == "lookup_answer"
        and claim.claim_kind == "limitation"
        and not _is_negative_or_unknown_limitation(
            claim.text,
            claim_kind=claim.claim_kind,
        )
    }
    primary_claims = [
        claim
        for claim in claims
        if claim.claim_kind in {"observation", "interpretation"}
        or claim.id in promoted_lookup_result_ids
    ]
    primary_claims = [
        claim
        for claim in primary_claims
        if not _claim_repeats_requested_ngram_rows(
            claim,
            question_text,
            evidence_items,
            observed_facts,
        )
        and not _claim_repeats_requested_frequency_rows(
            claim,
            question_text,
            evidence_items,
        )
        and not _claim_repeats_requested_collocation_rows(
            claim,
            question_text,
            evidence_items,
            observed_facts,
        )
        and not _claim_repeats_requested_kwic_row(
            claim,
            question_text,
            evidence_items,
            observed_facts,
        )
        and not _claim_repeats_semantic_candidate_row(
            claim,
            question_text,
            observed_facts,
            claims,
        )
        and not _claim_repeats_lexical_diversity_metrics(
            claim,
            evidence_items,
        )
    ]
    deduplicated_primary_claims: List[ClaimDraft] = []
    seen_primary_texts: set[str] = set()
    seen_primary_labels: set[str] = set()
    seen_ngram_candidate_terms: set[str] = set()
    fact_index = {fact.id: fact for fact in observed_facts}
    dedupe_ngram_candidates = bool(
        _NGRAM_INTERPRETATION_REQUEST_PATTERN.search(question_text or "")
    )
    for claim in primary_claims:
        # Duplikat-Faltung (H6/B8-S5): identischer normalisierter Text
        # (casefold, Whitespace kollabiert) oder identisches sichtbares Label
        # rendern nur einmal, die erste Instanz gewinnt. Nur exakte
        # Duplikate, keine Paraphrasen-Heuristik.
        signature = _claim_dedup_signature(claim.text)
        if signature and signature in seen_primary_texts:
            continue
        label = _visible_claim_label(claim.text)
        if label and label in seen_primary_labels:
            continue
        if dedupe_ngram_candidates:
            terms = _claimed_ngram_terms(claim, fact_index)
            is_candidate = bool(
                len(terms) == 1
                and _NGRAM_HYPOTHESIS_PATTERN.search(claim.text or "")
                and _NGRAM_EPISTEMIC_PATTERN.search(claim.text or "")
            )
            if is_candidate and terms.intersection(seen_ngram_candidate_terms):
                continue
            if is_candidate:
                seen_ngram_candidate_terms.update(terms)
        if signature:
            seen_primary_texts.add(signature)
        if label:
            seen_primary_labels.add(label)
        deduplicated_primary_claims.append(claim)
    primary_claims = deduplicated_primary_claims
    retrieval_fact_ids = {
        str(assessment.get("fact_id", "") or "")
        for assessment in retrieval_candidate_assessments
        if str(assessment.get("topic_relation", "") or "").strip()
        in {"relevant", "marginal"}
        and str(assessment.get("fact_id", "") or "")
    }
    covered_retrieval_fact_ids = {
        fact_id
        for claim in primary_claims
        for fact_id in claim.fact_ids
        if fact_id in retrieval_fact_ids
    }

    def render_primary_claim(claim: ClaimDraft) -> str:
        evidence_lines = _retrieval_assessment_excerpt_lines(
            retrieval_candidate_assessments,
            observed_facts,
            fact_ids=set(claim.fact_ids).intersection(retrieval_fact_ids),
            neutral_labels=True,
        )
        if not evidence_lines:
            return claim.text
        return claim.text + "\n" + "\n".join(evidence_lines)

    followup_claims = []
    seen_followup_texts: set[str] = set()
    for claim in claims:
        if claim.claim_kind != "followup":
            continue
        followup_signature = _claim_dedup_signature(claim.text)
        if followup_signature and followup_signature in seen_followup_texts:
            continue
        if followup_signature:
            seen_followup_texts.add(followup_signature)
        followup_claims.append(claim)
    if deliverable_kind == "followup_questions":
        if followup_claims:
            followup_fact_ids = {
                fact_id
                for claim in followup_claims
                for fact_id in claim.fact_ids
            }
            primary_claims = [
                claim
                for claim in primary_claims
                if set(claim.fact_ids).intersection(followup_fact_ids)
            ]
        else:
            # Never present declarative claims as a substitute for the
            # requested research questions after a failed provider response.
            primary_claims = []
    reported_fact_ids = {
        str(fact_id)
        for claim in claims
        for fact_id in claim.fact_ids
        if str(fact_id)
    }
    reported_evidence_ids = {
        str(source_id)
        for fact_id in reported_fact_ids
        for fact in [fact_index.get(fact_id)]
        if fact is not None
        for source_id in fact.source_evidence_ids
        if str(source_id)
    }
    primary = [claim.text for claim in primary_claims]
    followups = [claim.text for claim in followup_claims]
    if deliverable_kind == "followup_questions":
        requested_questions = _requested_followup_question_count(question_text)
        followups = followups[: requested_questions or 5]
    expanded_context_lines = _expanded_kwic_context_lines(
        [
            item
            for item in evidence_items
            if item.id in reported_evidence_ids
        ]
    )
    model_reports_direct_lexical_search = any(
        item.id in reported_evidence_ids and bool(_exact_lexical_search(item)[0])
        for item in evidence_items
    )
    direct_lexical_summary = (
        _direct_lexical_search_summary(evidence_items)
        if confirmation_boundary and not model_reports_direct_lexical_search
        else ""
    )
    limitation_candidates = [
        *([direct_lexical_summary] if direct_lexical_summary else []),
        *_analysis_execution_limitation_lines(
            evidence_items,
            selected_evidence_ids=reported_evidence_ids,
        ),
        *(
            [
                _t("Dieser Suchlauf kann die Universalbehauptung nicht bestätigen "
                "und misst keine korpusweite Polarität. Für eine solche Messung "
                "müssten das thematische Suchfeld "
                "(Wortformen, Lemmata, Komposita und begründete verwandte "
                "Ausdrücke), das jeweilige Bewertungsobjekt, das "
                "Polaritätskriterium und die untersuchte Dokumentmenge vorab "
                "festgelegt und alle einschlägigen Treffer systematisch kodiert "
                "werden.", 'This search does not confirm the universal claim or measure corpus-wide polarity. That measurement requires defining the topical search space (word forms, lemmas, compounds and justified related expressions), the object of evaluation, the polarity criterion and the document population, then systematically coding every relevant hit.')
            ]
            if confirmation_boundary
            else []
        ),
        *[
            line
            for line in (
                _user_facing_evidence_gap(gap)
                for gap in evidence_gaps
            )
            if line
        ],
        *[
            claim.text
            for claim in claims
            if claim.claim_kind == "limitation"
            and claim.id not in promoted_lookup_result_ids
        ],
        *[
            line
            for fact in observed_facts
            if (
                fact.fact_kind == "limitation"
                and (
                    fact.id
                    in {
                        fact_id
                        for claim in claims
                        for fact_id in claim.fact_ids
                    }
                    or _t("Tool-Ausgabe", 'tool output') in fact.statement
                    or _has_any_phrase(
                        _normalised_question_text(fact.statement),
                        (
                            "top-n",
                            "top n",
                            "partiell",
                            "abgeschnitten",
                            "teilmenge",
                        ),
                    )
                )
            )
            for line in [fact.statement, *fact.limitations]
        ],
        *(
            [
                _t("Ein einzelner Kontexttreffer belegt weder die Wahrheit der "
                "zitierten Aussage noch ein korpusweites Muster.", 'A single context match establishes neither the truth of the quoted statement nor a corpus-wide pattern.')
            ]
            if expanded_context_lines
            else []
        ),
    ]
    limitations: List[str] = []
    seen_limitation_kinds: set[str] = set()
    limitation_index_by_kind: Dict[str, int] = {}
    truncated_tool_domains = {
        domain
        for item in evidence_items
        if item.truncated
        for domain in [
            {
                "run_cqlf_query": "kwic",
                "semantic_search": "semantic",
                "similar_words": "semantic",
                "collocate_stats": "collocation",
                "compare_collocates": "collocation",
                "contrast_collocates": "collocation",
                "frequency_list": "frequency",
                "word_sketch": "word_sketch",
            }.get(item.tool, "")
        ]
        if domain
    }

    def limitation_precision(value: str) -> int:
        normalised = _normalised_question_text(value)
        return (
            4 * int("berechnung bleibt vollständig" in normalised)
            + 3 * int("truncated=true" in normalised)
            + 2 * int(
                _has_any_phrase(
                    normalised,
                    ("dargestellt", "angezeigt", "zurückgegeben", "zurueckgegeben"),
                )
            )
            - 2 * int(
                _has_any_phrase(
                    normalised,
                    ("keine aussagen", "nichts ableitbar"),
                )
            )
        )

    for line in _normalise_text_list(
        [
            normalised
            for candidate in limitation_candidates
            if (normalised := _normalise_claim_text(candidate))
        ],
        max_items=MAX_ANSWER_CLAIMS + 6,
        item_limit=MAX_CLAIM_TEXT_CHARS,
    ):
        lowered = _normalised_question_text(line)
        if any(
            _extract_numeric_tokens(lowered)
            == _extract_numeric_tokens(
                _normalised_question_text(existing)
            )
            and SequenceMatcher(
                None,
                lowered,
                _normalised_question_text(existing),
                autojunk=False,
            ).ratio()
            >= 0.92
            for existing in limitations
        ):
            continue
        if _has_any_phrase(
            lowered,
            (
                "synthesefenster",
                "für die synthese",
                "fuer die synthese",
            ),
        ):
            kind = "grounding_window"
        elif re.search(
            r"\b(?:technisch\w*\s+(?:daten)?aufteilung|"
            r"technisch\w*\s+partition|"
            r"(?:metadaten)?feld\s+['\"„“]?split|"
            r"zweck\s+der\s+technisch\w*\s+partition)\b",
            lowered,
        ):
            if re.search(r"\b(?:zweck|bedeutung|verwendungszweck)\w*\b", lowered):
                kind = "technical_partition:purpose"
            elif re.search(
                r"\b(?:nenner|tokennenner|tokenzahl|proportion|größe|groesse)\w*\b",
                lowered,
            ):
                kind = "technical_partition:denominator"
            elif re.search(
                r"\b(?:vergleichsachse|subkorpusachse|fachlich\w*\s+"
                r"(?:eignung|sinnvoll|begründet|begruendet))\b",
                lowered,
            ):
                kind = "technical_partition:comparison_axis"
            else:
                kind = lowered
        elif _has_any_phrase(lowered, ("fallback", "satzebene", "dokumentebene")):
            kind = "fallback"
        elif (
            _has_any_phrase(
                lowered,
                (
                    "partiell",
                    "abgeschnitten",
                    "teilmenge",
                    "begrenzt sichtbar",
                    "top-n",
                    "top n",
                    "nicht zurückgegeben",
                    "nicht zurueckgegeben",
                    "nicht dargestellt",
                    "vollständige rangfolge",
                    "vollstaendige rangfolge",
                ),
            )
            or re.search(
                r"\bkeine\s+vollständige\w*\s+"
                r"(?:themen)?verteilung\b",
                lowered,
            )
            is not None
        ):
            scope_domains = [
                domain
                for domain, pattern in (
                    ("kwic", r"\b(?:kwic|konkordanz)\w*\b"),
                    ("semantic", r"\bsemant\w*\b"),
                    ("collocation", r"\bkollokat\w*\b"),
                    ("frequency", r"\b(?:frequenz|häufigkeit|haeufigkeit)\w*\b"),
                    ("word_sketch", r"\bword[- ]?sketch\b"),
                )
                if re.search(pattern, lowered)
            ]
            if not scope_domains and len(truncated_tool_domains) == 1:
                scope_domains = list(truncated_tool_domains)
            kind = "tool_result_scope:" + (
                ",".join(scope_domains)
                if scope_domains
                else "generic"
            )
        else:
            kind = lowered
        if kind in seen_limitation_kinds:
            existing_index = limitation_index_by_kind[kind]
            if limitation_precision(line) > limitation_precision(
                limitations[existing_index]
            ):
                limitations[existing_index] = line
            continue
        seen_limitation_kinds.add(kind)
        limitation_index_by_kind[kind] = len(limitations)
        limitations.append(line)

    parts: List[str] = []
    if (
        confirmation_boundary
        and not _accepted_claims_reject_confirmation_pressure(claims)
    ):
        parts.append(
            _t("Nein. Die sichtbare Evidenz bestätigt die verlangte "
            "Universalbehauptung nicht.", 'No. The visible evidence does not confirm the requested universal claim.')
        )
    context_rendered = False
    explicitly_separated_hypotheses = bool(
        _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN.search(question_text or "")
    )
    if explicitly_separated_hypotheses and primary_claims:
        hypothesis_claims = [
            claim
            for claim in primary_claims
            if _claim_is_hypothesis(claim)
        ]
        hypothesis_ids = {claim.id for claim in hypothesis_claims}
        structured_groups = (
            (
                _t("Beobachtung", 'Observation'),
                [
                    claim
                    for claim in primary_claims
                    if claim.claim_kind == "observation"
                ],
            ),
            (
                "Interpretation",
                [
                    claim
                    for claim in primary_claims
                    if claim.claim_kind == "interpretation"
                    and claim.id not in hypothesis_ids
                ],
            ),
            (_t("Hypothesen", 'Hypotheses'), hypothesis_claims),
        )
        for heading, grouped_claims in structured_groups:
            if grouped_claims:
                parts.append(
                    f"### {heading}\n"
                    + "\n\n".join(
                        render_primary_claim(claim)
                        for claim in grouped_claims
                    )
                )
    elif expanded_context_lines and deliverable_kind == "analysis_report":
        observations_before_context = [
            render_primary_claim(claim)
            for claim in primary_claims
            if claim.claim_kind == "observation"
        ]
        interpretations_after_context = [
            render_primary_claim(claim)
            for claim in primary_claims
            if claim.claim_kind == "interpretation"
        ]
        if observations_before_context:
            parts.append("\n\n".join(observations_before_context))
        parts.append(
            _t("### Kontextbeleg\n", '### Context evidence\n')
            + "\n".join(f"- {line}" for line in expanded_context_lines)
        )
        context_rendered = True
        if interpretations_after_context:
            parts.append("\n\n".join(interpretations_after_context))
    elif deliverable_kind == "method_advice" and interpretations:
        requested_steps = _requested_method_step_count(question_text)
        rendered_steps = (
            interpretations[:requested_steps]
            if requested_steps
            else interpretations
        )
        rendered_steps = [
            _strip_redundant_method_step_ordinal(line)
            for line in rendered_steps
        ]
        parts.append(
            _t("### Empfohlene erste Analyseschritte\n", '### Recommended first analysis steps\n')
            + "\n".join(
                f"{index}. {line}"
                for index, line in enumerate(rendered_steps, start=1)
            )
        )
    elif (
        deliverable_kind == "overview"
        and primary_claims
        and any(
            claim_kind == "observation"
            for (
                _source_quote,
                _unit,
                claim_kind,
                _target_count,
                _description,
            ) in _explicit_counted_response_groups(question_text)
        )
    ):
        observation_claims = [
            claim
            for claim in primary_claims
            if claim.claim_kind == "observation"
        ]
        interpretation_claims = [
            claim
            for claim in primary_claims
            if claim.claim_kind == "interpretation"
        ]
        if observation_claims:
            parts.append(
                _t("### Beobachtungen\n", '### Observations\n')
                + "\n\n".join(
                    f"{index}. {render_primary_claim(claim)}"
                    for index, claim in enumerate(
                        observation_claims,
                        start=1,
                    )
                )
            )
        if interpretation_claims:
            parts.append(
                _t("### Einordnung\n", '### Interpretation\n')
                + "\n\n".join(
                    render_primary_claim(claim)
                    for claim in interpretation_claims
                )
            )
    elif (
        deliverable_kind
        in {"overview", "analysis_report", "contrast_report"}
        and primary
    ):
        parts.append(
            "\n\n".join(
                render_primary_claim(claim)
                for claim in _deutung_zuerst(primary_claims)
            )
        )
    elif primary and deliverable_kind != "followup_questions":
        parts.append(
            "\n\n".join(
                render_primary_claim(claim)
                for claim in _deutung_zuerst(primary_claims)
            )
        )

    requested_ngram_table = _requested_ngram_result_table(
        question_text,
        evidence_items,
    )
    requested_frequency_table = _requested_frequency_result_table(
        question_text,
        evidence_items,
        accepted_claims=primary_claims,
    )
    if requested_frequency_table:
        parts.append(requested_frequency_table)

    requested_kwic_table = _requested_kwic_result_table(
        question_text,
        evidence_items,
        observed_facts=observed_facts,
        accepted_claims=primary_claims,
    )
    if requested_kwic_table:
        parts.append(requested_kwic_table)

    requested_collocation_tables = _requested_collocation_result_tables(
        question_text,
        evidence_items,
    )
    if requested_collocation_tables:
        parts.append(requested_collocation_tables)

    if requested_ngram_table:
        parts.append(requested_ngram_table)

    if deliverable_kind == "contrast_report":
        keyness_table = _directional_keyness_result_table(evidence_items)
        if keyness_table:
            parts.append(keyness_table)

    if expanded_context_lines and not context_rendered:
        parts.append(
            _t("### Kontextbeleg\n", '### Context evidence\n')
            + "\n".join(f"- {line}" for line in expanded_context_lines)
        )

    # Coverage accounting is diagnostic provenance, not part of the research
    # answer. Internal deduplication and adjudication counts are not visible
    # evidence and would turn a natural analysis into a mechanical audit log.
    retrieval_precision_note = _retrieval_precision_note(
        retrieval_candidate_assessments,
        covered_fact_ids=covered_retrieval_fact_ids,
    )
    if (
        primary_claims
        and retrieval_precision_note
        and include_diagnostic_appendix
    ):
        parts.append(f"*Retrieval-Abdeckung:* {retrieval_precision_note}")

    retrieval_exclusion_lines = _retrieval_assessment_exclusion_lines(
        retrieval_candidate_assessments,
        observed_facts,
    )
    if retrieval_exclusion_lines and include_diagnostic_appendix:
        parts.append(
            _t("### Ausgeschlossene Retrieval-Kandidaten\n"
            "Diese Ausschnitte waren im Retrieval sichtbar, wurden wegen "
            "fehlenden Themenbezugs aber nicht als inhaltliche Belege genutzt.\n", '### Excluded retrieval candidates\nThese excerpts appeared in retrieval but were excluded as content evidence because they were off-topic.\n')
            + "\n".join(retrieval_exclusion_lines)
        )

    if followups:
        heading = (
            _t("Anschlussfragen", 'Follow-up questions')
            if deliverable_kind == "followup_questions"
            else _t("Weiterführende Fragen", 'Further questions')
        )
        parts.append(
            f"### {heading}\n"
            + "\n".join(f"- {line}" for line in followups)
        )

    provenance_lines = _analysis_provenance_lines(evidence_items)
    if deliverable_kind == "followup_questions" and primary:
        contextual_lines = [
            (
                f"- Arbeitshypothese: {claim.text}"
                if claim.claim_kind == "interpretation"
                else f"- {claim.text}"
            )
            for claim in primary_claims
        ]
        parts.append(
            _t("### Ausgangspunkte\n", '### Starting points\n') + "\n".join(contextual_lines)
        )
    if include_diagnostic_appendix and provenance_lines and not (
        deliverable_kind == "followup_questions" and primary
    ):
        parts.append(
            _t("### Evidenz\n", '### Evidence\n')
            + "\n".join(f"- {line}" for line in provenance_lines)
        )

    if limitations:
        rendered_limitations = (
            limitations[0]
            if len(limitations) == 1
            else "\n".join(f"- {line}" for line in limitations)
        )
        parts.append(_t(f"### Limitationen\n{rendered_limitations}", f"""### Limitations
{rendered_limitations}"""))

    return "\n\n".join(part for part in parts if part.strip()).strip()


def build_claim_preserving_grounded_markdown(
    contract: AnalysisContract,
    envelope: AnswerEnvelope,
    accepted_claim_ids: Sequence[str],
    rejected_claim_ids: Sequence[str],
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
    deliverable_complete: bool = True,
    question_text: str = "",
    retrieval_candidate_assessments: Sequence[Dict[str, Any]] = (),
    include_diagnostic_appendix: bool = True,
) -> str:
    """Return verified model insight without a mechanical substitute report."""

    accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
    claims = [claim for claim in envelope.claims if claim.id in accepted]
    render_question = question_text or contract.question_scope
    confirmation_boundary = bool(
        _is_confirmation_pressure_prompt(render_question)
        and _observed_facts_supply_confirmation_boundary(observed_facts)
    )
    if claims or confirmation_boundary:
        markdown = build_verified_claim_markdown(
            envelope,
            [claim.id for claim in claims],
            observed_facts,
            deliverable_kind=contract.deliverable_kind,
            question_text=render_question,
            evidence_items=evidence_items,
            evidence_gaps=evidence_gaps,
            retrieval_candidate_assessments=(
                retrieval_candidate_assessments
            ),
            include_diagnostic_appendix=include_diagnostic_appendix,
        )
        if not deliverable_complete:
            unfulfilled_ids = set(
                getattr(
                    envelope,
                    "_unfulfilled_response_requirement_ids",
                    [],
                )
                or []
            )
            if not unfulfilled_ids:
                unfulfilled_ids = {
                    requirement.id
                    for requirement in missing_response_requirements(
                        envelope,
                        [claim.id for claim in claims],
                        rejected_claim_ids,
                        contract.response_requirements,
                    )
                }
            open_components = _normalise_text_list(
                [
                    requirement.description
                    for requirement in contract.response_requirements
                    if requirement.id in unfulfilled_ids
                    and requirement.description
                ],
                max_items=3,
                item_limit=220,
            )
            if open_components:
                markdown = (
                    markdown.rstrip()
                    + _t("\n\n*Offen bleibt in diesem Lauf: ", '\n\n*Unresolved in this run: ')
                    + "; ".join(open_components)
                    + ".*"
                )
        # Internal slot IDs and counters remain trace-only; the optional line
        # above names only the user-requested component that is still missing.
        return markdown.strip()

    factual_deliverable = contract.deliverable_kind in {
        "lookup_answer",
        "capability_report",
    }
    family_allows_factual_deliverable = (
        compatible_deliverable_kind(
            contract.deliverable_kind,
            contract.analysis_family,
            # render_question, nicht contract.question_scope: der Scope ist
            # auf dem Modellpfad vom Modell geschriebene Prosa. Gemessen am
            # 2026-09-02 gab compatible_deliverable_kind fuer die Frage
            # "Gibt es das Wort Klimawandel im Korpus?" mit einem
            # 208-Zeichen-Scope analysis_report zurueck, der belegte
            # Presence-Zweig fiel weg, und aus einer belegten Antwort wurde
            # der Satz ueber die nicht verifizierbare Endantwort.
            question_text=render_question,
            track=contract.track,
        )
        == contract.deliverable_kind
    )
    if factual_deliverable and family_allows_factual_deliverable:
        return build_grounded_markdown(
            contract,
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
            accepted_claim_ids=[],
        )

    message = (
        _t("Die Tool-Evidenz wurde erhoben, aber in diesem Lauf ließ sich keine "
        "interpretative Endantwort verifizieren. Ich gebe deshalb keinen "
        "automatisch zusammengesetzten Ersatzbericht aus; die Evidenz bleibt "
        "im Analyseverlauf nachvollziehbar.", 'The tool evidence was collected, but an interpretative final answer could not be verified in this run. The evidence remains available in the analysis history.')
    )
    visible_gaps = [
        line
        for line in (
            _user_facing_evidence_gap(gap) for gap in evidence_gaps
        )
        if line
    ]
    if visible_gaps:
        message += "\n\n**Grund**\n" + "\n".join(
            f"- {line}" for line in visible_gaps[:2]
        )
    return message


def evidence_manifest(items: Sequence[EvidenceItem], *, max_items: int = 6) -> List[str]:
    manifest: List[str] = []
    for item in list(items)[:max_items]:
        parts = [item.id, item.tool, item.status]
        if item.truncated:
            parts.append("truncated")
        if item.grounding_truncated:
            parts.append("grounding-window")
        scope = _compact_text(item.result_scope, 80)
        if scope:
            parts.append(scope)
        manifest.append(_compact_text(" | ".join(parts), 220))
    return manifest


def _kwic_text_from_row(row: Dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            _normalise_example_text(row.get("left")),
            _normalise_example_text(row.get("kw") or row.get("word")),
            _normalise_example_text(row.get("right")),
        )
        if part
    ).strip()


def _expanded_kwic_context_lines(
    evidence_items: Sequence[EvidenceItem],
    *,
    max_items: int = 2,
) -> List[str]:
    """Render successful expanded contexts with stable corpus locators."""

    lines: List[str] = []
    for item in evidence_items:
        if item.tool != "kwic_context" or str(item.status).casefold() == "error":
            continue
        text = _kwic_text_from_row(item.raw_surface)
        if not text:
            continue
        locators: List[str] = []
        if item.raw_surface.get("pos") not in (None, ""):
            locators.append(f"Position {item.raw_surface.get('pos')}")
        if item.raw_surface.get("doc_id") not in (None, ""):
            locators.append(_t(f"Dokument-ID {item.raw_surface.get('doc_id')}", f"Document ID {item.raw_surface.get('doc_id')}"))
        locator_text = f" ({', '.join(locators)})" if locators else ""
        line = _t(f"Kontext{locator_text}: „{text}“", f"""Context{locator_text}: “{text}”""")
        if line not in lines:
            lines.append(line)
        if len(lines) >= max_items:
            break
    return lines


def _dominant_query_term(evidence_items: Sequence[EvidenceItem], *, fallback: str = "der Suchbegriff") -> str:
    for item in evidence_items:
        term = _question_term(item.query)
        if term:
            return term
    for item in evidence_items:
        rows = item.raw_surface.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            kw = _normalise_example_text(row.get("kw") or row.get("word"))
            if kw:
                return kw.strip("`")
    return _t(fallback, "the search term") if fallback == "der Suchbegriff" else fallback


def _word_like_token(token: str) -> bool:
    text = str(token or "").strip()
    if not text:
        return False
    if text.startswith(("@", "#")):
        return False
    return any(ch.isalpha() for ch in text)


def _term_profile_context_labels(examples: Sequence[str], *, query_term: str = "") -> List[str]:
    term = _normalise_example_text(query_term).lower()
    term_tokens = [token for token in re.findall(r"[\wÄÖÜäöüß]+", term) if token]
    term_head = term_tokens[0] if term_tokens else ""
    labels: List[str] = []
    windows: List[List[str]] = []
    adjacent_terms: List[str] = []
    repeated_term_use = False
    for example in examples:
        tokens = [token.lower() for token in re.findall(r"[\wÄÖÜäöüß]+|[.,;:!?]", example)]
        if not tokens:
            continue
        positions = [
            index
            for index, token in enumerate(tokens)
            if term_head and (token == term_head or token.startswith(term_head) or term_head.startswith(token))
        ]
        repeated_term_use = repeated_term_use or len(positions) >= 2
        if not positions:
            positions = [len(tokens) // 2]
        for index in positions[:1]:
            left = tokens[max(0, index - 4) : index]
            right = tokens[index + 1 : index + 5]
            window = left + right
            windows.append(window)
            if left:
                adjacent_terms.append(left[-1])
            if right:
                adjacent_terms.append(right[0])
    flat = [token for window in windows for token in window]
    if any(token in {"kein", "keine", "keinen", "keinem", "keiner", "keines", "nicht", "ohne", "nie", "kaum"} for token in flat):
        labels.append(_t("negierte oder limitierende Gebrauchskontexte", 'negated or limiting usage contexts'))
    if any(token in {"viel", "wenig", "mehr", "genug", "keine", "keinen", "keiner"} for token in adjacent_terms):
        labels.append(_t("quantifizierende Gebrauchskontexte", 'quantifying usage contexts'))
    if repeated_term_use:
        labels.append(_t("wiederholte oder formelhafte Verwendung", 'repeated or formulaic use'))
    if any(token in {"und", "oder"} for token in adjacent_terms):
        labels.append(_t("Koordinations- oder Aufzählungskontexte", 'coordination or enumeration contexts'))
    repeated_context = {
        token
        for token in adjacent_terms
        if token not in {"der", "die", "das", "ein", "eine", "und", "oder", ",", ";", ":"}
        and adjacent_terms.count(token) >= 2
    }
    if repeated_context:
        labels.append(_t("wiederkehrende lokale Kontextmuster", 'recurring local context patterns'))
    return labels[:3]


def _coerce_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _kwic_zaehlungen(
    evidence_items: Sequence[EvidenceItem],
) -> List[Tuple[str, Any, Any]]:
    """Collect query_count evidence as query, hit count and denominator.

    Concordance analyses can include scoped counts alongside displayed rows.
    Keep those counts available to deterministic landings even when a turn
    contains no run_cqlf_query item.
    """

    zaehlungen: List[Tuple[str, Any, Any]] = []
    for item in evidence_items:
        if item.tool != "query_count":
            continue
        if str(item.status).casefold() == "error":
            continue
        total = item.raw_surface.get("total")
        if total in (None, ""):
            continue
        abfrage = str(
            item.raw_surface.get("query") or item.query or ""
        ).strip()
        zaehlungen.append(
            (abfrage, total, item.raw_surface.get("denominator_tokens"))
        )
    return zaehlungen


def _zaehl_zeilen(
    zaehlungen: Sequence[Tuple[str, Any, Any]],
) -> List[str]:
    """Eine Zeile je Zaehlung, die Rate nur dort, wo ein Nenner steht.

    Die Rate wird aus Treffer und Nenner GERECHNET, nie aus einem Feld
    abgeschrieben, das ein Werkzeug schon fertig mitliefert: der
    Fenster-Sweep der Referenzantwort fuhr vier Weiten mit demselben
    Nenner, und eine Rate ohne ihren Nenner ist an dieser Stelle kein
    Vergleich. Ohne Nenner steht nur der Rohtreffer da, ausdruecklich
    ohne Rate.
    """

    zeilen: List[str] = []
    for abfrage, total, nenner in zaehlungen:
        name = f"`{abfrage}`" if abfrage else _t("Die gezählte Abfrage", 'The counted query')
        treffer = _coerce_number(total)
        nenner_wert = _coerce_number(nenner)
        satz = _t(f"- {name}: {total} Treffer", f"""- {name}: {total} hits""")
        if (
            treffer is not None
            and nenner_wert is not None
            and nenner_wert > 0
        ):
            rate = treffer * 1_000_000.0 / nenner_wert
            # Deutsche Schreibweise, getrennt gebildet. Ein
            # ``.replace`` auf dem ganzen Satz haette auch das Komma
            # nach "Treffer" getroffen: benachbarte Literale werden
            # verkettet, BEVOR die Methode laeuft.
            rate_text = f"{rate:.2f}".replace(".", ",")
            nenner_text = f"{nenner_wert:,.0f}".replace(",", ".")
            satz += (
                _t(f", das sind {rate_text} pro Million Token "
                f"(Nenner {nenner_text} Token)", f""", or {rate_text} per million tokens (denominator: {nenner_text} tokens)""")
            )
        zeilen.append(satz + ".")
    return list(dict.fromkeys(zeilen))


def _kwic_usage_report(
    *,
    query_term: str,
    total_hits: Any,
    rows_seen: Any,
    kwic_examples: Sequence[str],
    zaehlungen: Sequence[Tuple[str, Any, Any]] = (),
) -> str:
    """Gebrauchsbericht statt Presence-Zeile (H7/A1, R7-Befund kwic_zeit).

    Deterministische Landung fuer Gebrauchsfragen (deliverable_kind
    ``analysis_report``), wenn der Turn vor der Modell-Synthese endet:
    mehrere woertliche Kontextbelege plus eine an den sichtbaren Zeilen
    verankerte Muster-Beobachtung und die ehrliche Grenze, dass die
    vollstaendige Gebrauchsanalyse nicht mehr gelaufen ist. Kein
    Ja/Nein-Presence-Rahmen: die Frage war eine Analyse, keine
    Bestandspruefung.
    """
    shown = list(kwic_examples[:4])
    # Wie im Todespfad: ``total=105`` ist ein Variablenname, kein Deutsch.
    # Die fachliche Unterscheidung zwischen Gesamttrefferzahl und
    # angezeigten Zeilen bleibt, sie wird ausgesprochen statt codiert.
    if total_hits not in (None, ""):
        mal = "1 Mal" if str(total_hits) == "1" else f"{total_hits} Mal"
        head = _t(f"`{query_term}` kommt im durchsuchten Korpus {mal} vor.", f"""`{query_term}` occurs {total_hits} time(s) in the searched corpus.""")
    elif rows_seen not in (None, ""):
        head = (
            _t(f"Zu `{query_term}` liegen {rows_seen} Belegzeilen vor. Eine "
            "Gesamttrefferzahl für das Korpus wurde nicht mehr ermittelt.", f"""There are {rows_seen} concordance lines for `{query_term}`. The total number of corpus hits was not determined.""")
        )
    elif shown:
        head = _t(f"Belegzeilen zu `{query_term}` aus dem Suchlauf.", f"""Concordance lines for `{query_term}` from this search.""")
    else:
        # Nur gezaehlt, keine Zeile gesehen. Die Zahl steht im Block
        # "Gezaehlt" mit ihrer Abfrage, der Kopf greift ihr nicht vor.
        head = _t(f"Zählergebnisse zu `{query_term}` aus dem Suchlauf.", f"""Query counts for `{query_term}` from this search.""")
    lines = [head]
    if shown:
        lines.extend(["", _t("Belegzeilen:", 'Concordance lines:')])
        lines.extend(f"- „{example}“" for example in shown)
    # P6-NACHBESSERUNG: die gezaehlten Zahlen samt Nenner. Vorher fielen
    # sie hier heraus, siehe _kwic_zaehlungen.
    gezaehlt = _zaehl_zeilen(zaehlungen)
    if gezaehlt:
        lines.extend(["", _t("Gezählt:", 'Counts:')])
        lines.extend(gezaehlt)
    labels = _term_profile_context_labels(shown, query_term=query_term)
    lines.append("")
    lines.append(_t("Deutung", 'Interpretation'))
    if labels:
        lines.append(
            _t("Die sichtbaren Belegzeilen zeigen ", 'The visible concordance lines show ')
            + ", ".join(labels)
            + _t(". Diese Beobachtung beschreibt nur den zitierten Ausschnitt "
            "und ist keine Aussage über ein korpusweites Gebrauchsmuster.", '. This observation describes the quoted excerpt. The corpus-wide usage pattern has not been established.')
        )
    elif shown:
        lines.append(
            _t("Die sichtbaren Belegzeilen sind heterogen und zeigen kein "
            "einzelnes dominantes Gebrauchsmuster. Diese Beobachtung "
            "beschreibt nur den zitierten Ausschnitt und ist keine Aussage "
            "über das Gesamtkorpus.", 'The visible concordance lines are heterogeneous, with no single dominant usage pattern in this excerpt. The observation concerns this excerpt.')
        )
    else:
        lines.append(
            _t("Belegzeilen liegen aus diesem Turn nicht vor. Die Zahlen oben "
            "sagen, wie oft die Abfrage trifft, nicht wie sie gebraucht "
            "wird.", 'No concordance lines are available from this turn. The counts above measure matches for the query. Usage requires reading contexts.')
        )
    lines.append(
        _t("Eine weitergehende Gebrauchsanalyse ist nicht enthalten, der "
        "Turn endete vor der Modell-Synthese. Eine Fortsetzung liefert die "
        "Musterbeschreibung auf Basis der oben zitierten Belege.", 'The turn ended before model synthesis. Continuing the turn can produce a usage analysis from the quoted evidence above.')
        if shown
        else _t("Eine weitergehende Gebrauchsanalyse ist nicht enthalten, "
        "der Turn endete vor der Modell-Synthese. Eine Fortsetzung holt "
        "zuerst Belegzeilen zu den gezählten Abfragen.", 'The turn ended before model synthesis. Continuing the turn can retrieve concordance lines for the counted queries and analyse their usage.')
    )
    _teil = total_hits not in (None, "") and str(total_hits) != str(len(shown))
    lines.append("")  # keine erfundene Kappung, siehe death_landings
    if not shown:
        lines.append(
            _t("Grenzen: Zitiert ist keine Belegzeile, die Aussage beruht "
            "allein auf den Zählungen.", 'Scope: No concordance line is quoted. The statement is based on the counts.')
        )
    else:
        lines.append(
            _t(f"Grenzen: Zitiert sind {len(shown)} Belegzeilen, nicht alle "
            "Treffer.", f"""Scope: {len(shown)} concordance lines are quoted, rather than all hits.""")
            if _teil
            else _t("Grenzen: Die Einordnung ist eine Lesart, keine Messung.", 'Scope: The classification is a reading, rather than a measurement.')
        )
    return "\n".join(lines)


def _abfragerang(abfrage: str, genannter_begriff: str) -> int:
    """Welche von mehreren Abfragen eines Turns beantwortet die Frage?

    LIVE GESEHEN am 2026-08-31. Die Frage war die Konstruktion "nicht nur X
    sondern auch Y". Der Turn setzte zwei Abfragen ab:

        [word="nicht"] [word="nur"]                             129.441
        [word="nicht"] [word="nur"] [word="sondern"] [word="auch"]    0

    Ausgeliefert wurde "Ja. Fuer `[word="nicht"] [word="nur"]` ist im
    sichtbaren Suchlauf `total=129441` belegt." Eine NULL wurde zu einer
    Bestaetigung, weil der Verfasser den ERSTEN Wert nahm und nie
    aktualisierte.

    Zwei Regeln, in dieser Reihenfolge:

    1. Passt die Abfrage zum genannten Suchbegriff, gewinnt sie. Dann
       stehen Name und Zahl garantiert zusammen.
    2. Sonst gewinnt die SPEZIFISCHERE. Eine Abfrage mit vier Zellen sagt
       mehr als eine mit zwei, und wo die eine ein Praefix der anderen ist,
       ist die kuerzere die Vorbereitung und die laengere die Frage.

    Der Rang ist bewusst grob. Er soll nicht raten, welche Abfrage gemeint
    war, sondern nur verhindern, dass die Zahl der einen neben dem Namen
    der anderen steht.
    """
    text = str(abfrage or "").strip()
    if not text:
        return 0
    if text == str(genannter_begriff or "").strip():
        return 10_000
    # Zellen einer CQL-Abfrage, sonst Woerter.
    zellen = text.count("[")
    return (zellen or len(text.split())) * 10 + min(len(text), 9)


def _build_kwic_presence_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    question_scope: str = "",
    evidence_gaps: Sequence[str],
    deliverable_kind: str = "",
) -> str:
    expanded_context_lines = _expanded_kwic_context_lines(evidence_items)

    def with_validated_gaps(markdown: str) -> str:
        if expanded_context_lines:
            markdown += (
                _t("\n\nKontextbeleg:\n", '\n\nContext evidence:\n')
                + "\n".join(f"- {line}" for line in expanded_context_lines)
                + _t("\n- Ein einzelner Kontexttreffer belegt weder die Wahrheit "
                "der zitierten Aussage noch ein korpusweites Muster.", '\n- A single context match establishes neither the truth of the quoted statement nor a corpus-wide pattern.')
            )
        gaps = _normalise_text_list(
            [
                line
                for line in (
                    _user_facing_evidence_gap(gap)
                    for gap in evidence_gaps
                )
                if line
            ],
            max_items=6,
            item_limit=220,
        )
        if not gaps:
            return markdown
        return (
            _t(f"{markdown}\n\nLimitationen:\n", f"""{markdown}

Limitations:
""")
            + "\n".join(f"- {gap}" for gap in gaps)
        )

    query_term = _dominant_query_term(
        evidence_items,
        fallback=_question_term(question_scope) or _t("der Suchbegriff", 'the search term'),
    )
    total_hits: Any = None
    rows_seen: Any = None
    kwic_examples: List[str] = []
    saw_query_result = False
    #: Rang der bisher besten Abfrage, siehe _abfragerang.
    _bester_rang = -1
    #: Die Abfrage, aus der die genannte Zahl stammt. Sie wird das Etikett.
    _beste_abfrage = ""
    for item in evidence_items:
        # Read exact counts from both query_count and run_cqlf_query.
        # Apply the same ranking rule to both while concordance rows still come
        # from run_cqlf_query.
        if item.tool not in ("run_cqlf_query", "query_count"):
            continue
        saw_query_result = True
        # DIE ZAHL MUSS ZU DER ABFRAGE GEHOEREN, DIE GENANNT WIRD.
        #
        # Hier stand ``if total_hits in (None, "")``, also: nimm den ERSTEN
        # Wert und aktualisiere nie. Bei mehreren Abfragen eines Turns
        # gewann damit die erste, unabhaengig davon, welche die Frage
        # beantwortet.
        #
        # LIVE GESEHEN am 2026-08-31. Die Frage war die Konstruktion "nicht
        # nur X sondern auch Y" mit bis zu acht Token Abstand. Der Turn
        # setzte zwei Abfragen ab:
        #
        #   [word="nicht"] [word="nur"]                            129.441
        #   [word="nicht"] [word="nur"] [word="sondern"] [word="auch"]   0
        #
        # Ausgeliefert wurde: "Ja. Fuer `[word="nicht"] [word="nur"]` ist
        # im sichtbaren Suchlauf `total=129441` belegt." Eine Null wurde zu
        # einer Bestaetigung, weil der Name der einen Abfrage neben der
        # Zahl der anderen stand.
        #
        # Zwei Regeln, in dieser Reihenfolge. Passt die Abfrage dieses
        # Postens zum GENANNTEN Suchbegriff, gewinnt sie immer. Sonst
        # gewinnt die LETZTE Abfrage, denn eine Verfeinerungskette endet
        # bei der eigentlichen Frage, sie beginnt nicht dort.
        _diese_abfrage = str(item.raw_surface.get("query") or "").strip()
        _rang = _abfragerang(_diese_abfrage, query_term)
        if _rang >= _bester_rang and item.raw_surface.get("total") not in (None, ""):
            _bester_rang = _rang
            # DAS ETIKETT KOMMT AUS DERSELBEN QUELLE WIE DIE ZAHL.
            #
            # Bis zum 2026-09-01 stand hier nur die Zahl, und das Etikett
            # kam getrennt aus ``_dominant_query_term``: ein WORT aus der
            # ERSTEN Abfrage des Turns. Live stand deshalb "Ja. Fuer `[.*]`
            # ist im sichtbaren Suchlauf `total=129441` belegt" unter einer
            # Frage nach einer vierteiligen Konstruktion. Ein Platzhalter
            # als Name, und die Zahl gehoerte einer anderen Abfrage.
            #
            # Die Reparatur vom Vortag hat die ZAHL richtig gebunden. Sie
            # hat das Etikett nicht angefasst, und ein
            # test_der_verfasser_nennt_ein_wort_und_zaehlt_eine_abfrage
            # hielt genau diesen Rest fest. Jetzt faellt er.
            _beste_abfrage = _diese_abfrage
            total_hits = item.raw_surface.get("total")
            if item.raw_surface.get("rows_seen") not in (None, ""):
                rows_seen = item.raw_surface.get("rows_seen")
        elif rows_seen in (None, "") and item.raw_surface.get("rows_seen") not in (None, ""):
            rows_seen = item.raw_surface.get("rows_seen")
        rows = item.raw_surface.get("rows")
        if isinstance(rows, list):
            kwic_examples.extend(
                example
                for example in (_kwic_text_from_row(row) for row in rows[:5] if isinstance(row, dict))
                if example
            )
    kwic_examples = list(dict.fromkeys(kwic_examples))

    # Eine echte Abfrage schlaegt jedes abgeleitete Wort. Nur wenn keine
    # Abfrage die Zahl traegt, bleibt der bisherige Begriff stehen, etwa
    # weil die Landung ohne run_cqlf_query auskam.
    if _beste_abfrage:
        query_term = _beste_abfrage

    # H7/A1: Gebrauchsfragen (deliverable_kind analysis_report) bekommen in
    # den deterministischen Landungen (Salvage, Verifier-Skip ohne Entwurf,
    # conservative_only) einen Gebrauchsbericht mit mehreren Belegen und
    # Muster-Beobachtung statt der Ein-Satz-Presence-Antwort.
    # P6-NACHBESSERUNG: auch OHNE Belegzeile, sobald gezaehlt wurde. Der
    # Gebrauchsbericht traegt die Zahlen dann allein, statt sie in die
    # Presence-Zeile fallen zu lassen, die keinen Nenner kennt.
    gezaehlte = _kwic_zaehlungen(evidence_items)
    if deliverable_kind == "analysis_report" and (
        kwic_examples or gezaehlte
    ):
        return with_validated_gaps(
            _kwic_usage_report(
                query_term=query_term,
                total_hits=total_hits,
                rows_seen=rows_seen,
                kwic_examples=kwic_examples,
                zaehlungen=gezaehlte,
            )
        )

    def with_examples(answer: str) -> str:
        """Bis zu 3 Belege statt genau einem (H6/B3)."""

        if not kwic_examples:
            return answer
        if len(kwic_examples) == 1:
            return answer + _t(f" Beispiel: `{kwic_examples[0]}`.", f""" Example: `{kwic_examples[0]}`.""")
        return (
            answer
            + "\n\nBeispiele:\n"
            + "\n".join(f"- `{example}`" for example in kwic_examples[:3])
        )

    total_value = _coerce_number(total_hits)
    if total_value is not None and total_value <= 0:
        return with_validated_gaps(
            _t(f"Nein. Für `{query_term}` sind im sichtbaren Suchlauf keine Treffer belegt (`total=0`).", f"""No. The visible search returned no hits for `{query_term}` (`total=0`).""")
        )
    if total_hits not in (None, ""):
        answer = _t(f"Ja. Für `{query_term}` ist im sichtbaren Suchlauf `total={total_hits}` belegt.", f"""Yes. The visible search establishes `total={total_hits}` for `{query_term}`.""")
        return with_validated_gaps(with_examples(answer))
    rows_seen_value = _coerce_number(rows_seen)
    if rows_seen_value is not None and rows_seen_value <= 0:
        return with_validated_gaps(
            _t(f"Nein. Für `{query_term}` liegen im sichtbaren Suchlauf keine Trefferzeilen vor (`rows_seen=0`).", f"""No. The visible search returned no concordance lines for `{query_term}` (`rows_seen=0`).""")
        )
    if rows_seen not in (None, "") and rows_seen_value is not None and rows_seen_value > 0:
        answer = _t(f"Ja. Für `{query_term}` sind im sichtbaren Suchlauf `rows_seen={rows_seen}` belegt.", f"""Yes. The visible search establishes `rows_seen={rows_seen}` for `{query_term}`.""")
        return with_validated_gaps(with_examples(answer))
    if saw_query_result and not kwic_examples:
        return with_validated_gaps(
            _t(f"Nein. Für `{query_term}` liegen im sichtbaren Suchlauf keine Trefferzeilen vor.", f"""No. The visible search returned no concordance lines for `{query_term}`.""")
        )
    if kwic_examples:
        return with_validated_gaps(
            with_examples(_t(f"Ja. Für `{query_term}` liegen sichtbare KWIC-Belege vor.", f"""Yes. Visible concordance evidence is available for `{query_term}`."""))
        )
    return build_conservative_markdown([], evidence_gaps=evidence_gaps)


def _build_term_frequency_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    def with_validated_gaps(markdown: str) -> str:
        gaps = _normalise_text_list(
            [
                line
                for line in (
                    _user_facing_evidence_gap(gap)
                    for gap in evidence_gaps
                )
                if line
            ],
            max_items=6,
            item_limit=220,
        )
        if not gaps:
            return markdown
        return (
            _t(f"{markdown}\n\nLimitationen:\n", f"""{markdown}

Limitations:
""")
            + "\n".join(f"- {gap}" for gap in gaps)
        )

    # Q3 (FOKUS): ein query_count-Ergebnis ist die direkte Antwort auf die
    # Haeufigkeit EINES Wortes — exakte Trefferzahl (+ vorgerechnete pmw) zuerst.
    count_lines: List[str] = []
    for item in evidence_items:
        if item.tool != "query_count":
            continue
        total = item.raw_surface.get("total")
        if total in (None, ""):
            continue
        query = _normalise_example_text(item.raw_surface.get("query"))
        if not query and item.query:
            try:
                query_args = json.loads(item.query)
            except (TypeError, ValueError, json.JSONDecodeError):
                query_args = {}
            if isinstance(query_args, dict):
                query = _normalise_example_text(
                    query_args.get("query")
                )
        denominator_scope = _normalise_example_text(
            item.raw_surface.get("denominator_scope")
        ).casefold()
        scope_label = {
            "corpus": _t("im aktiven Korpus", 'in the active corpus'),
            "docset": _t("im aktiven Dokumentset", 'in the active document set'),
            "subcorpus": _t("im aktiven Subkorpus", 'in the active subcorpus'),
            "subkorpus": _t("im aktiven Subkorpus", 'in the active subcorpus'),
        }.get(
            denominator_scope,
            _t("im aktiven Auswertungsscope", 'in the active analysis scope'),
        )
        line = (
            _t(f"`{query}` kommt {scope_label} exakt {total}-mal vor", f"""`{query}` occurs exactly {total} times {scope_label}""")
            if query
            else _t(f"{scope_label} gilt total={total}", f"""{scope_label}: total={total}""")
        )
        pmw = item.raw_surface.get("per_million")
        if pmw not in (None, ""):
            denominator_tokens = item.raw_surface.get(
                "denominator_tokens"
            )
            if denominator_tokens in (None, ""):
                denominator_tokens = item.raw_surface.get(
                    "corpus_tokens"
                )
            from .word_denominator import ist_wortnenner

            einheit = (_t("Wortformen ohne Satzzeichen", 'word forms excluding punctuation')
                       if ist_wortnenner(item.raw_surface) else _t("Tokens", 'tokens'))
            provenance = [
                _t(f"Nenner={denominator_tokens} {einheit}", f"""Denominator={denominator_tokens} {einheit}""")
                if denominator_tokens not in (None, "")
                else "",
                f"Scope={denominator_scope}"
                if denominator_scope
                else "",
                (
                    _t("Quelle=", 'Source=')
                    + _normalise_example_text(
                        item.raw_surface.get("denominator_source")
                    )
                )
                if item.raw_surface.get("denominator_source")
                not in (None, "")
                else "",
            ]
            provenance = [entry for entry in provenance if entry]
            line += _t(f" ({pmw} pro Million Tokens", f""" ({pmw} per million tokens""")
            if provenance:
                line += "; " + ", ".join(provenance)
            line += ")"
        count_lines.append(line + ".")
    lexical_rows: List[Dict[str, Any]] = []
    returned_rows = 0
    for item in evidence_items:
        if item.tool != "frequency_list":
            continue
        rows_seen = _coerce_number(item.raw_surface.get("rows_seen"))
        if rows_seen is not None:
            returned_rows += max(0, int(rows_seen))
        rows = item.raw_surface.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = _normalise_example_text(row.get("word") or row.get("kw"))
                if not _word_like_token(label):
                    continue
                lexical_rows.append(row)
    if count_lines and not lexical_rows:
        return with_validated_gaps(" ".join(count_lines))
    if not lexical_rows:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)
    visible: List[str] = []
    seen: set[str] = set()
    for row in lexical_rows:
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        lowered = label.lower()
        if not label or lowered in seen:
            continue
        seen.add(lowered)
        metrics = [
            f"f={row.get('f')}" if row.get("f") not in (None, "") else "",
            (
                f"per_million={row.get('per_million')}"
                if row.get("per_million") not in (None, "")
                else ""
            ),
        ]
        metrics = [metric for metric in metrics if metric]
        if metrics:
            visible.append(f"`{label}` ({', '.join(metrics)})")
        else:
            visible.append(f"`{label}`")
    if not visible:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)
    displayed = visible[:10]
    ranking = (
        _t("In der sichtbaren Frequenzliste fallen vor allem ", 'The visible frequency list is headed by ')
        + ", ".join(displayed)
        + _t(" auf.", '.')
    )
    omitted = max(
        len(visible) - len(displayed),
        returned_rows - len(displayed),
    )
    if omitted:
        ranking += (
            _t(f" Weitere {omitted} zurückgegebene Evidenzzeilen werden hier "
            "nicht einzeln angezeigt.", f""" A further {omitted} returned evidence rows are not displayed individually here.""")
        )
    if count_lines:
        # Der gezaehlte Term IST die Antwort. Die Rangliste kommt nur dazu,
        # wenn sie ausdruecklich bestellt war (siehe grounding_evidence).
        if not rangliste_ausdruecklich_bestellt(evidence_items):
            return with_validated_gaps(" ".join(count_lines))
        return with_validated_gaps(" ".join(count_lines) + " " + ranking)
    return with_validated_gaps(ranking)


def _build_term_profile_markdown(
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    kwic_rows: List[Dict[str, Any]] = []
    kwic_runs: List[Dict[str, Any]] = []
    collocation_profiles: List[Dict[str, Any]] = []
    query_counts: List[Dict[str, Any]] = []
    total_hits: Any = None
    dispersion_bits: List[str] = []
    dispersion_metrics: Dict[str, Any] = {}
    for item in evidence_items:
        if item.tool == "run_cqlf_query":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                kwic_rows.extend(row for row in rows if isinstance(row, dict))
            try:
                args = json.loads(item.query) if item.query else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            kwic_runs.append(
                {
                    "query": item.raw_surface.get("query") or args.get("query") or "",
                    "total": item.raw_surface.get("total"),
                    "rows_returned": item.raw_surface.get("rows_seen"),
                    "rows_visible": len(rows) if isinstance(rows, list) else 0,
                    "truncated": bool(item.raw_surface.get("truncated")),
                    "query_mode": item.raw_surface.get("query_mode"),
                    "attribute": item.raw_surface.get("attribute"),
                    "case_insensitive": item.raw_surface.get("case_insensitive"),
                    "ctx": item.raw_surface.get("ctx") or args.get("ctx"),
                    "limit": item.raw_surface.get("limit") or args.get("limit"),
                    "scope": item.raw_surface.get("scope"),
                }
            )
            if total_hits in (None, "") and item.raw_surface.get("total") not in (None, ""):
                total_hits = item.raw_surface.get("total")
        elif item.tool == "collocate_stats":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                try:
                    args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                raw_method = item.raw_surface.get("method")
                raw_attribute = (
                    raw_method.get("attribute")
                    if isinstance(raw_method, dict)
                    else None
                )
                collocation_profiles.append(
                    {
                        "rows": [
                            row for row in rows if isinstance(row, dict)
                        ],
                        "attribute": args.get("attribute") or raw_attribute or "",
                        "term": (
                            args.get("term")
                            or item.raw_surface.get("requested_term")
                            or ""
                        ),
                        "window": args.get("window"),
                        "within_sentence": (
                            args.get("within_sentence")
                            if args.get("within_sentence") is not None
                            else item.raw_surface.get("within_sentence")
                        ),
                        "min_freq": (
                            args.get("min_freq")
                            or item.raw_surface.get("min_freq")
                        ),
                        "sort_by": (
                            args.get("sort_by")
                            or item.raw_surface.get("sort_by")
                        ),
                        "result_count": (
                            item.raw_surface.get("result_count")
                            or item.raw_surface.get("rows_seen")
                        ),
                        "scope": item.raw_surface.get("scope"),
                    }
                )
        elif item.tool == "query_count":
            total = item.raw_surface.get("total")
            if total not in (None, ""):
                try:
                    args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                query_counts.append(
                    {
                        "query": (
                            item.raw_surface.get("query")
                            or args.get("query")
                            or ""
                        ),
                        "total": total,
                        "per_million": item.raw_surface.get("per_million"),
                        "denominator_tokens": item.raw_surface.get(
                            "denominator_tokens"
                        ),
                        "denominator_scope": item.raw_surface.get(
                            "denominator_scope"
                        ),
                        "query_mode": item.raw_surface.get("query_mode"),
                        "attribute": item.raw_surface.get("attribute"),
                        "case_insensitive": item.raw_surface.get(
                            "case_insensitive"
                        ),
                        "scope": item.raw_surface.get("scope"),
                    }
                )
        elif item.tool == "dispersion_offsets":
            for key in (
                "unit",
                "profile",
                "dp",
                "dpnorm",
                # Interpret DP against its reference band because its lower bound
                # depends on partition sizes. A fixed label can otherwise misstate
                # clustering relative to the expected distribution.
                "dp_min",
                "dp_erwartet",
                "dp_max",
                "total_hits",
                "n_documents",
                "coverage_ratio",
                "nonzero_partitions",
            ):
                value = item.raw_surface.get(key)
                if value not in (None, ""):
                    dispersion_metrics[key] = value
                    dispersion_bits.append(f"{key}={value}")

    kwic_examples = [_kwic_text_from_row(row) for row in kwic_rows[:3]]
    kwic_examples = [example for example in kwic_examples if example]
    query_term = _dominant_query_term(evidence_items)
    context_labels = _term_profile_context_labels(kwic_examples, query_term=query_term)

    punctuation_seen = False
    for profile in collocation_profiles:
        lexical_rows: List[Dict[str, Any]] = []
        seen_words: set[str] = set()
        for row in profile["rows"]:
            label = _normalise_example_text(row.get("word") or row.get("kw"))
            lowered = label.lower()
            if not label or lowered in seen_words:
                continue
            seen_words.add(lowered)
            if _word_like_token(label):
                lexical_rows.append(row)
            else:
                punctuation_seen = True
        profile["lexical_rows"] = lexical_rows[:4]

    observation_lines: List[str] = []
    interpretation_lines: List[str] = []
    limitation_lines: List[str] = []
    for count in query_counts:
        query = _normalise_example_text(count.get("query"))
        total = count.get("total")
        pmw = count.get("per_million")
        scope = (
            _t("explizite Lemma-Abfrage", 'explicit lemma query')
            if re.search(r"\blemma\s*(?:=|in\b)", query, re.IGNORECASE)
            else _t("Klartext- oder CQLF-Abfrage", 'plain-text or CQLF query')
        )
        pmw_suffix = (
            f", per_million={pmw}"
            if pmw not in (None, "")
            else ""
        )
        denominator_bits = [
            (
                f"denominator_tokens={count.get('denominator_tokens')}"
                if count.get("denominator_tokens") not in (None, "")
                else ""
            ),
            (
                f"denominator_scope={count.get('denominator_scope')}"
                if count.get("denominator_scope") not in (None, "")
                else ""
            ),
        ]
        denominator_bits = [bit for bit in denominator_bits if bit]
        denominator_suffix = (
            _t(f" bei {', '.join(denominator_bits)}", f""" with {', '.join(denominator_bits)}""")
            if denominator_bits
            else ""
        )
        observation_lines.append(
            f"Die {scope} `{query}` ergibt `total={total}`{pmw_suffix}"
            f"{denominator_suffix}."
        )
    if total_hits not in (None, "") and not query_counts:
        observation_lines.append(
            _t(f"Im sichtbaren KWIC-Output liegt für `{query_term}` `total={total_hits}` vor.", f"""The visible concordance output reports `total={total_hits}` for `{query_term}`.""")
        )
    elif kwic_examples:
        observation_lines.append(
            _t(f"Es liegen sichtbare KWIC-Belege für `{query_term}` vor "
            f"({len(kwic_examples)} Beispielzeilen im aktuellen Ausschnitt).", f"""Visible concordance evidence is available for `{query_term}` ({len(kwic_examples)} example lines in the current excerpt).""")
        )
    if kwic_runs:
        run = kwic_runs[0]
        population = run.get("total")
        returned = run.get("rows_returned")
        visible = run.get("rows_visible")
        population_bits = [
            f"`total={population}`" if population not in (None, "") else "",
            (
                f"`rows_returned={returned}`"
                if returned not in (None, "")
                else ""
            ),
            (
                f"`grounding_rows_visible={visible}`"
                if visible not in (None, "")
                else ""
            ),
            f"`examples_shown={len(kwic_examples)}`",
        ]
        observation_lines.append(
            _t("Der KWIC-Scope trennt Trefferpopulation, Rückgabe und Bericht: ", 'The concordance scope distinguishes the hit population, returned rows and this report: ')
            + ", ".join(bit for bit in population_bits if bit)
            + "."
        )

    if context_labels:
        label_text = ", ".join(context_labels[:-1]) + (_t(" und ", ' and ') + context_labels[-1] if len(context_labels) > 1 else context_labels[0])
        interpretation_lines.append(
            _t("Die sichtbaren KWIC-Zeilen decken mindestens folgende "
            f"Nutzungstypen ab: {label_text}.", f"""The visible concordance lines include these usage types: {label_text}.""")
        )
    elif kwic_examples:
        interpretation_lines.append(
            _t("Die sichtbaren KWIC-Zeilen zeigen mehrere konkrete "
            "Gebrauchskontexte, aber kein einziges dominantes Muster im "
            "kleinen Ausschnitt.", 'The visible concordance lines show several concrete usage contexts, with no single dominant pattern in the small excerpt.')
        )

    generic_profile_count = 0
    visible_profile_count = 0
    min_freq_values: set[str] = set()
    for profile in collocation_profiles:
        collocation_lines: List[str] = []
        lexical_rows = profile.get("lexical_rows") or []
        for row in lexical_rows:
            label = _normalise_example_text(row.get("word") or row.get("kw"))
            metrics = [
                f"f={row.get('f')}" if row.get("f") not in (None, "") else "",
                f"mi={row.get('mi')}" if row.get("mi") not in (None, "") else "",
                f"t={row.get('t')}" if row.get("t") not in (None, "") else "",
                f"ll={row.get('ll')}" if row.get("ll") not in (None, "") else "",
            ]
            metrics = [metric for metric in metrics if metric]
            if label and metrics:
                collocation_lines.append(f"`{label}` ({', '.join(metrics)})")
        if not collocation_lines:
            continue
        visible_profile_count += 1
        attribute = _normalise_example_text(profile.get("attribute"))
        term = _normalise_example_text(profile.get("term")) or query_term
        scope_label = (
            _t("Lemmaebene", 'lemma level')
            if attribute == "lemma"
            else _t("Wortformenebene", 'word-form level') if attribute == "word" else ""
        )
        method_bits = [
            f"attribute={attribute}" if attribute else "",
            f"term={term}" if term else "",
            (
                f"window={profile.get('window')}"
                if profile.get("window") not in (None, "")
                else ""
            ),
            (
                f"within_sentence={str(bool(profile.get('within_sentence'))).lower()}"
                if profile.get("within_sentence") is not None
                else ""
            ),
            (
                f"min_freq={profile.get('min_freq')}"
                if profile.get("min_freq") not in (None, "")
                else ""
            ),
            (
                f"sort_by={profile.get('sort_by')}"
                if profile.get("sort_by") not in (None, "")
                else ""
            ),
            (
                f"rows_returned={profile.get('result_count')}"
                if profile.get("result_count") not in (None, "")
                else ""
            ),
            f"rows_reported={len(collocation_lines)}",
        ]
        method_bits = [bit for bit in method_bits if bit]
        if len(collocation_profiles) == 1:
            prefix = _t("Die sichtbare Kollokationsspitze ist", 'The visible collocation ranking is headed by')
            if method_bits:
                prefix += f" ({', '.join(method_bits)})"
        elif not scope_label:
            prefix = _t("Die sichtbare Kollokationsspitze ist", 'The visible collocation ranking is headed by')
            if method_bits:
                prefix += f" ({', '.join(method_bits)})"
        else:
            prefix = (
                _t(f"Die sichtbare Kollokationsspitze auf der {scope_label} "
                f"({', '.join(method_bits)}) ist", f"""The visible collocation ranking for {scope_label} ({', '.join(method_bits)}) is headed by""")
            )
        observation_lines.append(
            prefix + ": " + ", ".join(collocation_lines[:4]) + "."
        )
        generic_focus = {
            _normalise_example_text(row.get("word") or row.get("kw")).lower()
            for row in lexical_rows[:4]
        }
        if generic_focus & {"wird", "werden", "ist", "sein", "es"}:
            generic_profile_count += 1
        if profile.get("min_freq") not in (None, ""):
            min_freq_values.add(str(profile["min_freq"]))
    if generic_profile_count:
        scope_text = (
            _t("in den getrennten sichtbaren Spitzen", 'in the separate visible rankings')
            if visible_profile_count > 1
            else _t("in der sichtbaren Spitze", 'in the visible ranking')
        )
        interpretation_lines.append(
            _t(f"{scope_text[:1].upper()}{scope_text[1:]} stehen mehrere häufige grammatische "
            "Formen. Das beschreibt sichtbare Fensterkookkurrenz; eine "
            "syntaktische Relation folgt daraus nicht.", f"""{scope_text[:1].upper()}{scope_text[1:]} there are several frequent grammatical forms. These establish co-occurrence in the window. A syntactic relation requires further evidence.""")
        )
        explicit_attributes = {
            _normalise_example_text(profile.get("attribute"))
            for profile in collocation_profiles
            if _normalise_example_text(profile.get("attribute"))
        }
        if {"word", "lemma"} <= explicit_attributes:
            interpretation_lines.append(
                _t("Die explizit getrennten Wortform- und Lemmaprofile sind "
                "separate Ranglisten und werden nicht zusammengeführt.", 'The word-form and lemma profiles are separate rankings and are not merged.')
            )
    if min_freq_values:
        limitation_lines.append(
            _t("- Die sichtbaren Kollokationsranglisten berücksichtigen nur "
            "Kandidaten mit gemeinsamer Häufigkeit "
            f"f >= min_freq={', '.join(sorted(min_freq_values))}.", f"""- The visible collocation rankings include candidates with co-occurrence frequency f >= min_freq={', '.join(sorted(min_freq_values))}.""")
        )
    if punctuation_seen:
        limitation_lines.append(
            _t("- Im sichtbaren Kollokationsoutput erscheinen auch "
            "Interpunktions-Treffer; diese sind methodisch weniger "
            "aussagekräftig als lexikalische Kollokate.", '- The visible collocation output includes punctuation matches. These offer less lexical information than word collocates.')
        )
    if dispersion_bits:
        unit = _normalise_example_text(dispersion_metrics.get("unit")).lower()
        display_bits = [
            (
                f"documents_with_hits={value}"
                if key == "nonzero_partitions" and unit == "documents"
                else f"{key}={value}"
            )
            for key, value in dispersion_metrics.items()
        ]
        observation_lines.append(
            _t("Zum sichtbaren Dispersionsprofil liegen folgende Kennwerte vor: ", 'The visible dispersion profile provides these metrics: ')
            + ", ".join(display_bits)
            + "."
        )
        profile = _normalise_example_text(dispersion_metrics.get("profile")).lower()
        dp_value = _safe_float(dispersion_metrics.get("dp"))
        coverage = _safe_float(dispersion_metrics.get("coverage_ratio"))
        nonzero = dispersion_metrics.get("nonzero_partitions")
        n_documents = dispersion_metrics.get("n_documents")
        total = dispersion_metrics.get("total_hits")
        total_float = _safe_float(total)
        coverage_text = ""
        if unit == "documents" and nonzero not in (None, "") and n_documents not in (None, ""):
            coverage_text = (
                _t(f"{nonzero} von {n_documents} Dokumenten enthalten mindestens "
                f"einen Treffer; coverage_ratio={coverage:g}", f"""{nonzero} of {n_documents} documents contain at least one hit, coverage_ratio={coverage:g}""")
                if coverage is not None
                else _t(f"{nonzero} von {n_documents} Dokumenten enthalten mindestens einen Treffer", f"""{nonzero} of {n_documents} documents contain at least one hit""")
            )
        elif unit == "documents" and nonzero not in (None, ""):
            coverage_text = (
                _t(f"{nonzero} Dokumente enthalten mindestens einen Treffer "
                f"(coverage_ratio={coverage:g})", f"""{nonzero} documents contain at least one hit (coverage_ratio={coverage:g})""")
                if coverage is not None
                else _t(f"{nonzero} Dokumente enthalten mindestens einen Treffer", f"""{nonzero} documents contain at least one hit""")
            )
        elif coverage is not None and nonzero not in (None, ""):
            coverage_text = _t(f"{nonzero} Partitionen sind belegt (coverage_ratio={coverage:g})", f"""{nonzero} partitions have hits (coverage_ratio={coverage:g})""")
        elif coverage is not None:
            coverage_text = f"coverage_ratio={coverage:g}"
        elif nonzero not in (None, ""):
            coverage_text = _t(f"{nonzero} Partitionen sind belegt", f"""{nonzero} partitions have hits""")
        dp_text = f"dp={dp_value:g}" if dp_value is not None else ""
        from candyconc.analysis_defaults import dispersion_lagesatz  # Vergleich vor Etikett
        if (_lage := dispersion_lagesatz(dispersion_metrics)):
            interpretation_lines.append(_lage)
        if profile == "fairly_even":
            details = ", ".join(part for part in (coverage_text, dp_text) if part)
            interpretation_lines.append(
                _t("Methodisch spricht das Profil `fairly_even` im sichtbaren Output eher für eine relativ breite Streuung", 'The `fairly_even` profile indicates relatively broad dispersion in the visible output')
                + (f" ({details})." if details else ".")
            )
        elif profile == "moderately_clustered":
            details = ", ".join(part for part in (coverage_text, dp_text) if part)
            interpretation_lines.append(
                _t("Methodisch spricht das Profil `moderately_clustered` im sichtbaren Output für eine erkennbare Bündelung", 'The `moderately_clustered` profile indicates noticeable clustering in the visible output')
                + (f" ({details})." if details else ".")
            )
        elif profile == "strongly_clustered":
            details = ", ".join(part for part in (coverage_text, dp_text) if part)
            if (
                unit == "documents"
                and total_float is not None
                and total_float > 0
                and nonzero not in (None, "")
            ):
                try:
                    repeated_hits = max(
                        0,
                        int(total_float) - int(nonzero),
                    )
                except (TypeError, ValueError):
                    repeated_hits = None
                repetition = (
                    _t(f"; nur {repeated_hits} Treffer liegen über den ersten "
                    "Treffer je belegtem Dokument hinaus", f""", only {repeated_hits} hits remain after the first hit in each document with a match""")
                    if repeated_hits is not None
                    else ""
                )
                interpretation_lines.append(
                    _t("Das Profil `strongly_clustered` folgt festen "
                    "Schnittpunkten (0,2/0,5/0,8) und nicht der Verteilung "
                    "dieses Korpus. Es darf nicht als wiederholte Häufung "
                    "gelesen werden", 'The `strongly_clustered` profile follows fixed cut-offs (0.2/0.5/0.8), rather than this corpus distribution. It does not establish repeated local concentration')
                    + (f" ({details}{repetition})." if details else ".")
                )
            else:
                target = (
                    _t("Dokumente", 'documents')
                    if unit == "documents"
                    else _t("Korpusabschnitte", 'corpus sections')
                )
                interpretation_lines.append(
                    _t("Methodisch spricht das Profil `strongly_clustered` im "
                    f"sichtbaren Output für eine starke Konzentration auf wenige {target}", f"""The `strongly_clustered` profile indicates strong concentration in a few {target} in the visible output""")
                    + (f" ({details})." if details else ".")
                )
        elif profile == "absent":
            interpretation_lines.append(
                _t("Das Dispersionsprofil `absent` bedeutet, dass im sichtbaren Dispersionslauf keine Treffer für den Ausdruck vorliegen.", 'The `absent` dispersion profile means the visible dispersion run found no hits for the expression.')
            )
        if (
            total not in (None, "")
            and not (total_float is not None and 0 < total_float < 30)
        ):
            limitation_lines.append(
                _t("- Die Belastbarkeit des Verteilungsurteils hängt sichtbar an "
                f"der Trefferbasis: total_hits={total}.", f"""- The distribution assessment depends on the hit count: total_hits={total}.""")
            )

    for gap in evidence_gaps:
        if (
            visible_profile_count
            and re.search(
                r"kollokation.*top[- ]?\d+",
                str(gap),
                re.IGNORECASE,
            )
        ):
            continue
        line = _user_facing_evidence_gap(gap)
        if line:
            limitation_lines.append(f"- {line}")
    dispersion_total = _safe_float(dispersion_metrics.get("total_hits"))
    if dispersion_total is not None and 0 < dispersion_total < 30:
        limitation_lines.append(
            _t(f"- Das Verteilungsurteil ist nur grob belastbar, weil die sichtbare Trefferbasis mit total_hits={dispersion_metrics.get('total_hits')} klein ist.", f"""- The small visible hit count, total_hits={dispersion_metrics.get('total_hits')}, limits the distribution assessment.""")
        )
    if not dispersion_bits:
        limitation_lines.append(_t("- Ein belastbares Verteilungsurteil fehlt, wenn kein Dispersions-Output vorliegt.", '- No distribution assessment is available without dispersion output.'))
    if (
        collocation_profiles
        and not any(profile.get("lexical_rows") for profile in collocation_profiles)
    ):
        limitation_lines.append(_t("- Der sichtbare Kollokationsausschnitt ist methodisch dünn oder von nicht-lexikalischen Treffern dominiert.", '- The visible collocation excerpt contains little lexical evidence or is dominated by non-lexical matches.'))

    provenance_lines = _analysis_provenance_lines(evidence_items)

    if not observation_lines and not interpretation_lines:
        return build_conservative_markdown(
            observed_facts,
            evidence_gaps=evidence_gaps,
        )

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        _t("Beobachtungen:", 'Observations:'),
        *[f"- {line}" for line in observation_lines],
    ]
    if provenance_lines:
        parts.extend(
            [
                "",
                _t("Methoden- und Scope-Provenienz:", 'Method and scope provenance:'),
                *[f"- {line}" for line in provenance_lines],
            ]
        )
    if kwic_examples:
        example_lines = [f"- `{example}`" for example in kwic_examples[:3]]
        parts.extend(["", _t("Sichtbare KWIC-Beispiele:", 'Visible concordance examples:'), *example_lines])
    if interpretation_lines:
        parts.extend(
            ["", "Interpretation:", *[f"- {line}" for line in interpretation_lines]]
        )
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def _build_contrast_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    compare_rows: List[Dict[str, Any]] = []
    contrast_rows: List[Dict[str, Any]] = []
    keyness_rows: List[Dict[str, Any]] = []
    frequency_rows: List[Dict[str, Any]] = []
    metadata_values: Dict[str, List[str]] = {}
    returned_compare_rows = 0
    returned_contrast_rows = 0
    for item in evidence_items:
        if item.tool == "contrast_collocates":
            rows_seen = _coerce_number(item.raw_surface.get("rows_seen"))
            if rows_seen is not None:
                returned_contrast_rows += max(0, int(rows_seen))
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                contrast_rows.extend(row for row in rows if isinstance(row, dict))
        elif item.tool == "compare_collocates":
            rows_seen = _coerce_number(item.raw_surface.get("rows_seen"))
            if rows_seen is not None:
                returned_compare_rows += max(0, int(rows_seen))
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                compare_rows.extend(row for row in rows if isinstance(row, dict))
            diagnostics = item.raw_surface.get("diagnostics")
            if isinstance(diagnostics, dict):
                for field, key in (("model", "model_values"), ("text_type", "text_type_values")):
                    entries = diagnostics.get(key)
                    if isinstance(entries, list):
                        values = [
                            _normalise_example_text(entry)
                            for entry in entries
                            if _normalise_example_text(entry)
                        ]
                        if values and field not in metadata_values:
                            metadata_values[field] = values
        elif item.tool == "keyness":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                keyness_rows.extend(row for row in rows if isinstance(row, dict))
        elif item.tool == "frequency_list":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                frequency_rows.extend(row for row in rows if isinstance(row, dict))
        elif item.tool == "metadata_values":
            values = item.raw_surface.get("values")
            if isinstance(values, dict):
                for field, entries in values.items():
                    if isinstance(entries, list):
                        metadata_values[str(field)] = [
                            _normalise_example_text(entry)
                            for entry in entries
                            if _normalise_example_text(entry)
                        ]
    if (
        not compare_rows
        and not contrast_rows
        and not keyness_rows
        and not frequency_rows
        and not metadata_values
    ):
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)

    human_rows = [
        row for row in compare_rows
        if (_safe_float(row.get("log_ratio")) or 0.0) > 0
    ][:3]
    ai_rows = [
        row for row in compare_rows
        if (_safe_float(row.get("log_ratio")) or 0.0) < 0
    ][:3]

    def _fmt(row: Dict[str, Any]) -> str:
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        bits = [
            f"freq_human={row.get('freq_human')}" if row.get("freq_human") not in (None, "") else "",
            f"freq_ai={row.get('freq_ai')}" if row.get("freq_ai") not in (None, "") else "",
            f"chi2_cell_human={row.get('chi2_cell_human')}" if row.get("chi2_cell_human") not in (None, "") else "",
            f"chi2_cell_ai={row.get('chi2_cell_ai')}" if row.get("chi2_cell_ai") not in (None, "") else "",
            _format_log_ratio_metric(row),
        ]
        bits = [bit for bit in bits if bit]
        return f"`{label}` ({', '.join(bits)})" if label and bits else ""

    target_rows = [
        row for row in contrast_rows
        if (_safe_float(row.get("log_ratio")) or 0.0) > 0
    ][:3]
    reference_rows = [
        row for row in contrast_rows
        if (_safe_float(row.get("log_ratio")) or 0.0) < 0
    ][:3]

    def _fmt_contrast(row: Dict[str, Any]) -> str:
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        bits = [
            f"freq_target={row.get('freq_target')}" if row.get("freq_target") not in (None, "") else "",
            f"freq_reference={row.get('freq_reference')}" if row.get("freq_reference") not in (None, "") else "",
            f"chi2_cell_target={row.get('chi2_cell_target')}" if row.get("chi2_cell_target") not in (None, "") else "",
            f"chi2_cell_reference={row.get('chi2_cell_reference')}" if row.get("chi2_cell_reference") not in (None, "") else "",
            _format_log_ratio_metric(row),
        ]
        bits = [bit for bit in bits if bit]
        return f"`{label}` ({', '.join(bits)})" if label and bits else ""

    def _fmt_keyness(row: Dict[str, Any]) -> str:
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        bits = [
            f"chi2_cell={row.get('chi2_cell')}" if row.get("chi2_cell") not in (None, "") else "",
            f"ll={row.get('ll')}" if row.get("ll") not in (None, "") else "",
        ]
        bits = [bit for bit in bits if bit]
        return f"`{label}` ({', '.join(bits)})" if label and bits else ""

    def _fmt_freq(row: Dict[str, Any]) -> str:
        label = _normalise_example_text(row.get("word") or row.get("kw"))
        bits = [
            f"f={row.get('f')}" if row.get("f") not in (None, "") else "",
            (
                f"per_million={row.get('per_million')}"
                if row.get("per_million") not in (None, "")
                else ""
            ),
        ]
        bits = [bit for bit in bits if bit]
        if label and bits:
            return f"`{label}` ({', '.join(bits)})"
        if label:
            return f"`{label}`"
        return ""

    summary_lines: List[str] = []
    model_values = metadata_values.get("model") or []
    lowered_model_values = {value.lower() for value in model_values}
    # Use this explanation only when model contains exclusively human values.
    # Other model names can identify generated versions without an explicit AI label.
    metadata_blocks_global_contrast = bool(
        lowered_model_values
        and lowered_model_values <= {"human", "mensch", "menschen"}
        and "ai" not in {v.lower() for v in metadata_values.get("text_type") or []}
    )
    if metadata_blocks_global_contrast:
        summary_lines.append(
            _t("Der sichtbare Metadatenausschnitt belegt keine AI-Partition: für `model` erscheint nur ", 'The visible metadata excerpt does not establish an AI partition. The only visible `model` value is ')
            + _t(f"`{model_values[0]}`. Ein globaler Human-vs-AI-Vergleich ist damit auf diesem Index nicht belastbar.", f"""`{model_values[0]}`. This index therefore does not support a global human versus AI comparison.""")
        )
    if human_rows:
        summary_lines.append(
            _t("Im sichtbaren Vergleich fallen auf der Human-Seite vor allem ", 'On the human side, the visible comparison highlights ')
            + ", ".join(filter(None, (_fmt(row) for row in human_rows)))
            + _t(" auf.", '.')
        )
    if ai_rows:
        summary_lines.append(
            _t("Auf der AI-Seite fallen im sichtbaren Vergleich vor allem ", 'On the AI side, the visible comparison highlights ')
            + ", ".join(filter(None, (_fmt(row) for row in ai_rows)))
            + _t(" auf.", '.')
        )
    elif human_rows:
        summary_lines.append(
            _t("Im sichtbaren Ausschnitt erscheinen die deutlichsten Unterschiede damit einseitig auf der Human-Seite; ein gleich starker AI-seitiger Gegenpol ist hier nicht sichtbar.", 'The strongest visible differences are on the human side. No equally strong AI-side counterpart is visible in this excerpt.')
        )
    from candyconc.candyconc_copilot.grounding_contrast import (
        kontrastnenner_satz, kontrastseiten_benennen)
    ziel_name, referenz_name = kontrastseiten_benennen(
        evidence_items, _normalise_example_text)
    _nenner = kontrastnenner_satz(evidence_items)
    if target_rows:
        summary_lines.append(
            _t(f"Im sichtbaren Teilkorpus-Kontrast fällt auf {ziel_name} vor allem ", f"""On {ziel_name}, the visible subcorpus contrast highlights """)
            + ", ".join(filter(None, (_fmt_contrast(row) for row in target_rows)))
            + _t(" auf.", '.')
        )
    if reference_rows:
        summary_lines.append(
            _t(f"Auf {referenz_name} fällt im sichtbaren Teilkorpus-Kontrast vor allem ", f"""On {referenz_name}, the visible subcorpus contrast highlights """)
            + ", ".join(filter(None, (_fmt_contrast(row) for row in reference_rows)))
            + _t(" auf.", '.')
        )
    if _nenner and (target_rows or reference_rows):
        summary_lines.append(_nenner)
    keyness_examples = [entry for entry in (_fmt_keyness(row) for row in keyness_rows[:4]) if entry]
    if keyness_examples:
        summary_lines.append(
            _t("Der sichtbare Keyness-Ausschnitt liefert weitere Kontrastkandidaten wie ", 'The visible keyness excerpt provides further contrast candidates such as ')
            + ", ".join(keyness_examples[:3])
            + "."
        )
    freq_examples = [entry for entry in (_fmt_freq(row) for row in frequency_rows[:5]) if entry]
    if freq_examples:
        summary_lines.append(
            _t("Die sichtbare Frequenzspitze wird insgesamt von ", 'The visible frequency ranking is headed by ')
            + ", ".join(freq_examples[:4])
            + _t(" getragen; das liefert den Hintergrund, vor dem die Kontraste zu lesen sind.", '. This provides context for reading the contrasts.')
        )
    if model_values:
        if metadata_blocks_global_contrast:
            pass
        elif len(model_values) > 1:
            summary_lines.append(
                _t("Der sichtbare Metadatenausschnitt stützt den Human-vs-AI-Split explizit über `model`-Werte wie ", 'The visible metadata excerpt establishes the human versus AI split through `model` values such as ')
                + ", ".join(f"`{value}`" for value in model_values[:3])
                + "."
            )
        else:
            summary_lines.append(
                _t("Im aktuell sichtbaren Metadatenausschnitt ist der Human-vs-AI-Split nicht breit belegt; für `model` erscheint nur ", 'The current metadata excerpt provides limited evidence for a human versus AI split. The only visible `model` value is ')
                + f"`{model_values[0]}`."
            )

    low_support = [
        row for row in compare_rows[:6]
        if max(_safe_float(row.get("freq_human")) or 0.0, _safe_float(row.get("freq_ai")) or 0.0) <= 2.0
    ]
    limitation_lines: List[str] = [
        f"- {_user_facing_evidence_gap(gap)}"
        for gap in evidence_gaps
        if _user_facing_evidence_gap(gap)
    ]
    if low_support:
        limitation_lines.append(
            _t("- Mehrere sichtbare Unterschiede beruhen nur auf sehr kleinen Frequenzen (maximal f=2) und sind daher nur als duenne Evidenz zu lesen.", '- Several visible differences rely on frequencies of at most f=2, so their evidence consists of very few occurrences.')
        )
    if metadata_blocks_global_contrast and compare_rows:
        limitation_lines.append(
            _t("- Die sichtbaren Kollokationsvergleichszeilen dürfen hier nicht als globaler Human-vs-AI-Befund gelesen werden, weil die sichtbaren Metadaten keine AI-Partition belegen.", '- These collocation comparisons do not establish a global human versus AI finding because the visible metadata does not establish an AI partition.')
        )
    if compare_rows:
        limitation_lines.append(
            _t("- Der Vergleich stützt sich hier nur auf die sichtbaren Vergleichszeilen, nicht auf einen vollständigen Effektbericht ausserhalb des aktuellen Outputs.", '- This comparison is based on the visible comparison rows. A complete effect report beyond this output is not available.')
        )
    elif metadata_blocks_global_contrast:
        limitation_lines.append(
            _t("- Es wurden keine global belastbaren Human-vs-AI-Metriken berichtet, weil die sichtbare Metadatenbasis keine AI-Partition ausweist.", '- Global human versus AI metrics were not reported because the visible metadata does not identify an AI partition.')
        )
    else:
        limitation_lines.append(
            _t("- Der Vergleich stützt sich hier nur auf die sichtbaren Tool-Ausschnitte, nicht auf einen vollständigen Effektbericht ausserhalb des aktuellen Outputs.", '- This comparison is based on the visible tool excerpts. A complete effect report beyond this output is not available.')
        )

    if not summary_lines:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        *summary_lines,
    ]
    example_lines = [
        f"- {_fmt(row)}"
        for row in compare_rows[:6]
        if _fmt(row)
    ]
    if example_lines:
        parts.extend(["", _t("Sichtbare Vergleichszeilen:", 'Visible comparison rows:'), *example_lines])
    omitted_compare_rows = max(
        len(compare_rows),
        returned_compare_rows,
    ) - len(example_lines)
    if omitted_compare_rows > 0:
        parts.extend(
            [
                "",
                (
                    _t(f"Weitere {omitted_compare_rows} zurückgegebene "
                    "Vergleichszeilen werden hier nicht einzeln angezeigt.", f"""A further {omitted_compare_rows} returned comparison rows are not displayed individually here.""")
                ),
            ]
        )
    contrast_lines = [
        f"- {_fmt_contrast(row)}"
        for row in contrast_rows[:6]
        if _fmt_contrast(row)
    ]
    if contrast_lines:
        parts.extend(
            [
                "",
                _t("Sichtbare Teilkorpus-Kontrastzeilen:", 'Visible subcorpus contrast rows:'),
                *contrast_lines,
            ]
        )
    omitted_contrast_rows = max(
        len(contrast_rows),
        returned_contrast_rows,
    ) - len(contrast_lines)
    if omitted_contrast_rows > 0:
        parts.extend(
            [
                "",
                (
                    _t(f"Weitere {omitted_contrast_rows} zurückgegebene "
                    "Kontrastzeilen werden hier nicht einzeln angezeigt.", f"""A further {omitted_contrast_rows} returned contrast rows are not displayed individually here.""")
                ),
            ]
        )
    keyness_lines = [f"- {_fmt_keyness(row)}" for row in keyness_rows[:4] if _fmt_keyness(row)]
    if keyness_lines:
        parts.extend(["", _t("Sichtbare Keyness-Kandidaten:", 'Visible keyness candidates:'), *keyness_lines[:4]])
    freq_lines = [f"- {_fmt_freq(row)}" for row in frequency_rows[:4] if _fmt_freq(row)]
    if freq_lines:
        parts.extend(["", _t("Sichtbare Frequenzspitze:", 'Visible frequency ranking:'), *freq_lines[:4]])
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def _semantic_text_from_row(row: Dict[str, Any]) -> str:
    return _normalise_example_text(
        row.get("hit")
        or row.get("snippet")
        or row.get("kw")
        or row.get("text")
        or row.get("label")
    )


def _semantic_theme_terms_from_texts(
    texts: Sequence[str],
    *,
    max_terms: int = 3,
    min_document_hits: int = 1,
) -> List[str]:
    counts: Dict[str, int] = {}
    document_counts: Dict[str, int] = {}
    first_order: Dict[str, int] = {}
    surfaces: Dict[str, str] = {}
    order = 0
    for text in texts:
        seen_in_text: set[str] = set()
        for token in _semantic_theme_tokens(text):
            if token not in counts:
                first_order[token] = order
                surfaces[token] = token
                order += 1
            counts[token] = counts.get(token, 0) + 1
            seen_in_text.add(token)
        for token in seen_in_text:
            document_counts[token] = document_counts.get(token, 0) + 1
    candidates = [
        token
        for token in counts
        if document_counts.get(token, 0) >= min_document_hits
    ]
    candidates.sort(
        key=lambda token: (
            -document_counts.get(token, 0),
            -counts.get(token, 0),
            first_order.get(token, 0),
        )
    )
    return [surfaces[token] for token in candidates[:max_terms]]


def _semantic_theme_labels_from_texts(
    texts: Sequence[str],
    *,
    max_labels: int = 3,
    min_document_hits: int = 2,
) -> List[str]:
    tokenised = [_semantic_theme_tokens(text) for text in texts if _normalise_example_text(text)]
    counts: Dict[str, int] = {}
    document_counts: Dict[str, int] = {}
    co_counts: Dict[str, Dict[str, int]] = {}
    first_order: Dict[str, int] = {}
    order = 0
    for tokens in tokenised:
        seen = list(dict.fromkeys(tokens))
        for token in tokens:
            if token not in counts:
                first_order[token] = order
                order += 1
            counts[token] = counts.get(token, 0) + 1
        for token in seen:
            document_counts[token] = document_counts.get(token, 0) + 1
        for token in seen:
            related = co_counts.setdefault(token, {})
            for other in seen:
                if other != token:
                    related[other] = related.get(other, 0) + 1

    candidates = [
        token
        for token in counts
        if document_counts.get(token, 0) >= min_document_hits
    ]
    candidates.sort(
        key=lambda token: (
            -document_counts.get(token, 0),
            -counts.get(token, 0),
            first_order.get(token, 0),
        )
    )

    labels: List[str] = []
    used: set[str] = set()
    for token in candidates:
        if token in used:
            continue
        related = [
            other
            for other, co_count in co_counts.get(token, {}).items()
            if other not in used and co_count >= 1
        ]
        related.sort(
            key=lambda other: (
                -co_counts.get(token, {}).get(other, 0),
                -document_counts.get(other, 0),
                -counts.get(other, 0),
                first_order.get(other, 0),
            )
        )
        parts = [token] + related[:1]
        labels.append(" / ".join(parts))
        used.update(parts)
        if len(labels) >= max_labels:
            break
    return labels


def _semantic_theme_terms_from_rows(
    rows: Sequence[Any],
    *,
    max_terms: int = 3,
    min_document_hits: int = 1,
) -> List[str]:
    texts = [
        text
        for text in (_semantic_text_from_row(row) for row in rows if isinstance(row, dict))
        if text
    ]
    return _semantic_theme_terms_from_texts(
        texts,
        max_terms=max_terms,
        min_document_hits=min_document_hits,
    )


def _semantic_theme_labels_from_rows(
    rows: Sequence[Any],
    *,
    max_labels: int = 3,
    min_document_hits: int = 2,
) -> List[str]:
    texts = [
        text
        for text in (_semantic_text_from_row(row) for row in rows if isinstance(row, dict))
        if text
    ]
    return _semantic_theme_labels_from_texts(
        texts,
        max_labels=max_labels,
        min_document_hits=min_document_hits,
    )


def _build_semantic_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    snippets: List[str] = []
    cluster_error = False
    for item in evidence_items:
        if item.tool == "semantic_search" and item.status == "success":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                for row in rows[:6]:
                    if not isinstance(row, dict):
                        continue
                    snippet = _semantic_text_from_row(row)
                    if snippet:
                        snippets.append(snippet)
        elif item.tool in {"semantic_cluster", "semantic_cluster_words"} and item.status == "error":
            cluster_error = True

    snippets = [snippet for index, snippet in enumerate(snippets) if snippet and snippet not in snippets[:index]]
    if not snippets:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)

    recurring_labels = _semantic_theme_labels_from_texts(
        snippets,
        max_labels=3,
        min_document_hits=2,
    )
    theme_labels = recurring_labels or _semantic_theme_labels_from_texts(
        snippets,
        max_labels=3,
        min_document_hits=1,
    )

    summary_lines: List[str] = []
    if recurring_labels:
        summary_lines.append(
            _t("In den sichtbaren semantischen Treffern wiederholen sich lexikalische Themenachsen wie ", 'The visible semantic matches repeatedly include lexical themes such as ')
            + ", ".join(f"`{label}`" for label in recurring_labels[:3])
            + "."
        )
    elif theme_labels:
        summary_lines.append(
            _t("Die sichtbaren semantischen Treffer liefern lexikalische Themenachsen wie ", 'The visible semantic matches include lexical themes such as ')
            + ", ".join(f"`{label}`" for label in theme_labels[:3])
            + _t(", aber im kleinen Ausschnitt noch kein stabil wiederkehrendes Obermuster.", ', with no stable recurring broader pattern in this small excerpt.')
        )
    else:
        summary_lines.append(
            _t("Die sichtbaren semantischen Treffer zeigen mehrere thematisch passende Passagen, aber im kleinen Ausschnitt noch kein stabil wiederkehrendes Obermuster.", 'The visible semantic matches include several relevant passages, with no stable recurring broader pattern in this small excerpt.')
        )
    if cluster_error:
        summary_lines.append(
            _t("Der Cluster-Schritt hat hier keinen belastbaren Zusatzoutput geliefert; die Zusammenfassung basiert daher nur auf den sichtbaren semantic_search-Treffern.", 'The clustering step provided no usable additional output. The summary is based on the visible semantic_search matches.')
        )

    limitation_lines: List[str] = [
        f"- {_user_facing_evidence_gap(gap)}"
        for gap in evidence_gaps
        if _user_facing_evidence_gap(gap)
    ]
    limitation_lines.append(
        _t("- Die Musterzusammenfassung bleibt auf die sichtbaren Top-Treffer begrenzt und darf nicht als Vollverteilung des Themas gelesen werden.", '- The pattern summary covers the visible top matches. It does not establish the full distribution of this topic.')
    )

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        *summary_lines,
        "",
        _t("Sichtbare semantische Passagen:", 'Visible semantic passages:'),
        *[f"- `{snippet}`" for snippet in snippets[:4]],
    ]
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


_TECHNICAL_METADATA_FIELDS = ("origin_doc_id", "origin_id", "paired_with")


def _metadata_field_is_technical(field: str) -> bool:
    lowered = str(field or "").strip().lower()
    return (
        lowered in _TECHNICAL_METADATA_FIELDS
        or lowered in _PARTITION_METADATA_FIELDS
        or bool(_IDENTIFIER_METADATA_FIELD_RE.search(lowered))
    )


def _metadata_value_list(entries: Any, *, max_items: int = 8) -> List[str]:
    if isinstance(entries, list):
        raw_items = entries
    elif isinstance(entries, (str, int, float, bool)):
        raw_items = [entries]
    else:
        raw_items = _sample_items(entries)
    values = [
        _normalise_example_text(entry)
        for entry in raw_items[:max_items]
        if _normalise_example_text(entry)
    ]
    return list(dict.fromkeys(values))


def _metadata_field_is_analytical(field: str, values: Sequence[str]) -> bool:
    if _metadata_field_is_technical(field):
        return False
    if not values:
        return False
    if values and all(_looks_like_opaque_id(value) for value in values):
        return False
    return True


def _build_metadata_capability_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    question_scope: str = "",
    evidence_gaps: Sequence[str],
) -> str:
    """Render an exact metadata inventory, never an inferred analysis report."""

    _ = question_scope
    metadata_values: Dict[str, List[str]] = {}
    available_metadata_fields: List[str] = []
    # B4-Surface-Kontrakt (H6): value_counts zaehlt ALLE Felder des
    # metadata_values-Outputs, identifier_value_fields nennt die aus der
    # bounded Surface gefilterten ID-/Pfad-Felder mit count>0. Beide werden
    # defensiv gelesen: fehlen sie noch, bleibt das Alt-Verhalten.
    metadata_value_counts: Dict[str, int] = {}
    identifier_value_fields: set[str] = set()
    for item in evidence_items:
        if item.tool != "metadata_values":
            continue
        available_fields = item.raw_surface.get("available_fields")
        if isinstance(available_fields, list):
            available_metadata_fields.extend(
                field_name
                for field_name in (
                    _normalise_example_text(field)
                    for field in available_fields
                )
                if field_name
            )
        raw_counts = item.raw_surface.get("value_counts")
        if isinstance(raw_counts, dict):
            for field, count in raw_counts.items():
                field_name = _normalise_example_text(field)
                if not field_name:
                    continue
                try:
                    count_value = int(count)
                except (TypeError, ValueError):
                    continue
                metadata_value_counts[field_name] = max(
                    metadata_value_counts.get(field_name, 0),
                    count_value,
                )
        raw_identifier_fields = item.raw_surface.get("identifier_value_fields")
        if isinstance(raw_identifier_fields, list):
            identifier_value_fields.update(
                field_name
                for field_name in (
                    _normalise_example_text(field)
                    for field in raw_identifier_fields
                )
                if field_name
            )
        values = item.raw_surface.get("values")
        if not isinstance(values, dict):
            continue
        for field, entries in values.items():
            field_name = _normalise_example_text(field)
            if not field_name:
                continue
            metadata_values[field_name] = _metadata_value_list(
                entries,
                max_items=8,
            )

    field_order = list(
        dict.fromkeys(
            [*available_metadata_fields, *metadata_values.keys()]
        )
    )
    if not field_order:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)

    field_lines = []
    for field in field_order:
        values = metadata_values.get(field, [])
        if values:
            field_lines.append(
                f"- `{field}`: "
                + ", ".join(f"`{value}`" for value in values)
            )
            continue
        # Feld ohne sichtbare Einzelwerte, aber belegter Kardinalitaet:
        # niemals "keine Werte" behaupten (H6/B4, Evidenz-Widerspruch).
        count_value = metadata_value_counts.get(field)
        if isinstance(count_value, int) and count_value > 0:
            if field in identifier_value_fields:
                field_lines.append(
                    _t(f"- `{field}`: {count_value} distinkte Werte "
                    "(dokumentspezifisches ID-/Pfad-Feld, Einzelwerte für "
                    "den Kontext nicht aufgelistet)", f"""- `{field}`: {count_value} distinct values (document-specific ID or path field, individual values omitted from this context)""")
                )
            else:
                field_lines.append(
                    _t(f"- `{field}`: {count_value} distinkte Werte "
                    "(Einzelwerte für den Kontext nicht aufgelistet)", f"""- `{field}`: {count_value} distinct values (individual values omitted from this context)""")
                )
        else:
            field_lines.append(
                _t(f"- `{field}`: keine Werte im sichtbaren Tool-Output", f"""- `{field}`: no values in the visible tool output""")
            )
    notes: List[str] = [
        _t("- Diese Auflistung gibt ausschließlich den sichtbaren "
        "`metadata_values`-Output wieder; sie bewertet weder Homogenität noch "
        "analytische Eignung der Felder.", '- This inventory reproduces the visible `metadata_values` output. It makes no assessment of field homogeneity or analytical suitability.')
    ]
    notes.extend(
        f"- {_user_facing_evidence_gap(gap)}"
        for gap in evidence_gaps
        if _user_facing_evidence_gap(gap)
    )
    return "\n".join(
        [
            _t("Sichtbare Metadatenfelder:", 'Visible metadata fields:'),
            *field_lines,
            "",
            _t("Methodischer Hinweis:", 'Method note:'),
            *notes,
        ]
    ).strip()


def _build_word_sketch_markdown(
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    query_term = _dominant_query_term(evidence_items)
    tables: Dict[str, List[Dict[str, Any]]] = {}
    relation_labels: Dict[str, str] = {}
    relation_bases: Dict[str, str] = {}
    kwic_examples: List[str] = []
    for item in evidence_items:
        if item.tool == "word_sketch":
            raw_tables = item.raw_surface.get("tables")
            if isinstance(raw_tables, dict):
                for name, rows in raw_tables.items():
                    if isinstance(rows, list):
                        tables[str(name)] = [row for row in rows if isinstance(row, dict)]
            raw_relations = item.raw_surface.get("relations")
            if isinstance(raw_relations, dict):
                for name, metadata in raw_relations.items():
                    if not isinstance(metadata, dict):
                        continue
                    label = _normalise_example_text(metadata.get("label"))
                    if label:
                        relation_labels[str(name)] = label
                    basis = _normalise_example_text(metadata.get("basis"))
                    if basis:
                        relation_bases[str(name)] = basis
        elif item.tool == "run_cqlf_query":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                kwic_examples.extend(
                    example
                    for example in (_kwic_text_from_row(row) for row in rows[:3] if isinstance(row, dict))
                    if example
                )

    if not tables:
        return build_conservative_markdown([], evidence_gaps=evidence_gaps)

    relation_lines: List[str] = []
    visible_relations = list(tables.items())[:3]
    interpretation_lines: List[str] = []
    for relation, rows in visible_relations:
        if not rows:
            continue
        top_rows = []
        top_labels: List[str] = []
        for row in rows[:3]:
            label = _normalise_example_text(row.get("word") or row.get("kw"))
            if not label:
                continue
            top_labels.append(label)
            bits = [
                f"f={row.get('f')}" if row.get("f") not in (None, "") else "",
                f"chi2_cell={row.get('chi2_cell')}" if row.get("chi2_cell") not in (None, "") else "",
                f"ll={row.get('ll')}" if row.get("ll") not in (None, "") else "",
            ]
            bits = [bit for bit in bits if bit]
            top_rows.append(f"`{label}` ({', '.join(bits)})" if bits else f"`{label}`")
        if top_rows:
            relation_label = relation_labels.get(relation, "")
            label_suffix = f" – {relation_label}" if relation_label else ""
            relation_lines.append(
                f"- `{relation}`{label_suffix}: " + ", ".join(top_rows[:3])
            )
        relation_label = relation_labels.get(relation, "")
        if relation_label and top_labels:
            dependency_scope = (
                _t("Die Zeilen beruhen auf indexierten Abhängigkeitsrelationen. ", 'The rows are based on indexed dependency relations. ')
                if relation_bases.get(relation) == "indexed_dependency_relations"
                else ""
            )
            interpretation_lines.append(
                dependency_scope
                + _t("Das Tool beschreibt `", 'The tool defines `')
                + relation
                + _t("` als „", '` as “')
                + relation_label
                + _t("“. Im sichtbaren Ausschnitt sind dort ", '”. The visible excerpt contains ')
                + ", ".join(f"`{label}`" for label in top_labels[:3])
                + _t(" belegt; weitergehende syntaktische Deutungen brauchen "
                "Relationsdefinition oder KWIC-Belege.", '. Further syntactic interpretation requires a relation definition or concordance evidence.')
            )
        elif top_labels:
            interpretation_lines.append(
                _t("Für den sichtbaren Relationscode `", 'For the visible relation code `')
                + relation
                + _t("` fehlt im Tool-Output eine ausformulierte Definition; "
                "belegt sind dort lediglich ", '`, the tool output provides no written definition. It establishes only ')
                + ", ".join(f"`{label}`" for label in top_labels[:3])
                + "."
            )

    summary_lines = [
        _t(f"Für `{query_term}` sind im sichtbaren Word-Sketch-Output grammatische Relationen wie ", f"""The visible word-sketch output for `{query_term}` includes grammatical relations such as """)
        + ", ".join(f"`{name}`" for name, _rows in visible_relations if _rows)
        + _t(" belegt.", '.')
    ]
    summary_lines.extend(interpretation_lines[:3])
    if kwic_examples:
        summary_lines.append(
            _t("Die sichtbaren KWIC-Belege zeigen den konkreten Gebrauch im aktuellen Korpus; der Word Sketch macht dazu die lokalen grammatischen Nachbarschaften sichtbar.", 'The visible concordance evidence shows usage in the current corpus. The word sketch shows local grammatical neighbours.')
        )

    limitation_lines: List[str] = [
        f"- {_user_facing_evidence_gap(gap)}"
        for gap in evidence_gaps
        if _user_facing_evidence_gap(gap)
    ]
    limitation_lines.append(
        _t("- Gelistet sind Partnerzeilen mit f >= der ausgewiesenen "
        "min_freq-Schwelle; die Schwelle filtert Partner, nicht Relationen. "
        "Ohne Anteilsnenner über alle Termvorkommen belegen sie keine "
        "vorwiegende oder typische Relation.", '- Partner rows meet the reported f >= min_freq threshold. The threshold filters partners, rather than relations. Establishing a predominant or typical relation requires a denominator covering all node occurrences.')
    )

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        *summary_lines,
        "",
        _t("Sichtbare Word-Sketch-Relationen:", 'Visible word-sketch relations:'),
        *relation_lines[:4],
    ]
    if kwic_examples:
        parts.extend(["", _t("Sichtbare KWIC-Beispiele:", 'Visible concordance examples:'), *[f"- `{example}`" for example in kwic_examples[:2]]])
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def _build_exploratory_markdown(
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
    contract: "AnalysisContract | None" = None,
) -> str:
    observation_lines: List[str] = []
    semantic_observations: List[str] = []
    cluster_observations: List[str] = []
    metadata_observations: List[str] = []
    frequency_observations: List[str] = []
    document_observations: List[str] = []
    corpus_scope_observations: List[str] = []
    seen_corpus_token_counts: set[int] = set()
    saw_unfiltered_frequency = False
    saw_pos_distribution = False
    saw_pos_filtered_frequency = False
    saw_recurring_semantic_theme = False
    for item in evidence_items:
        if item.tool == "semantic_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                theme_labels = _semantic_theme_labels_from_rows(rows[:6], max_labels=3)
                if theme_labels:
                    saw_recurring_semantic_theme = True
                    semantic_observations.append(
                        _t("- Befund: In mehreren sichtbaren semantischen Treffern wiederholen sich lexikalische Themenhinweise wie ", '- Finding: Several visible semantic matches share lexical topic cues such as ')
                        + ", ".join(f"`{label}`" for label in theme_labels[:3])
                        + _t(". Evidenz: `semantic_search` liefert die entsprechenden Top-Treffer im aktuellen Ausschnitt. Limitation: Die Achsen sind aus sichtbaren Treffern abgeleitet und keine vollständige Themenklassifikation.", '. Evidence: `semantic_search` provides the corresponding top matches in this excerpt. Limitation: These themes come from visible matches and do not form a complete topic classification.')
                    )
                example_bits: List[str] = []
                for row in rows[:4]:
                    if not isinstance(row, dict):
                        continue
                    hit = _semantic_text_from_row(row)
                    if hit:
                        example_bits.append(hit)
                    if len(example_bits) >= 2:
                        break
                if example_bits:
                    semantic_observations.append(
                        _t("- Befund: Die sichtbaren semantischen Treffer liefern konkrete Passagen statt nur abstrakter Ähnlichkeitswerte. Evidenz: sichtbare Treffer wie ", '- Finding: The visible semantic matches provide concrete passages. Evidence: matches such as ')
                        + ", ".join(f"`{_compact_quote(bit, 70)}`" for bit in example_bits[:2])
                        + _t(". Limitation: Einzelne Treffer belegen lokale Passagen, nicht die Verteilung im Gesamtkorpus.", '. Limitation: Individual matches establish local passages, rather than the distribution across the corpus.')
                    )
        if item.tool in {"semantic_cluster", "semantic_cluster_words"}:
            clusters = _informative_clusters(item.raw_surface)
            if clusters:
                cluster_bits: List[str] = []
                for cluster in clusters[:3]:
                    label = _normalise_example_text(cluster.get("label"))
                    samples = _cluster_sample_values(cluster)
                    if label and samples:
                        cluster_bits.append(f"`{label}` (" + ", ".join(f"`{sample}`" for sample in samples[:3]) + ")")
                    elif label:
                        cluster_bits.append(f"`{label}`")
                if cluster_bits:
                    cluster_observations.append(
                        _t("- Befund: Der sichtbare Cluster-Schritt bündelt die explorativen Suchbegriffe in mehrere Themennaehen. Evidenz: `semantic_cluster_words` zeigt ", '- Finding: The visible clustering step groups the exploratory search terms into related themes. Evidence: `semantic_cluster_words` shows ')
                        + ", ".join(cluster_bits[:3])
                        + _t(". Limitation: Clusterlabels sind Hilfslabels für die sichtbaren Eingabetokens, keine manuell validierten Kategorien.", '. Limitation: Cluster labels describe the visible input tokens and are not manually validated categories.')
                    )
        if item.tool == "document_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list) and rows:
                try:
                    query_args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    query_args = {}
                if not isinstance(query_args, dict):
                    query_args = {}
                term = _normalise_example_text(
                    query_args.get("term") or query_args.get("query")
                )
                examples = [
                    _normalise_example_text(
                        row.get("snippet") or row.get("text") or row.get("content")
                    )
                    for row in rows[:2]
                    if isinstance(row, dict)
                    and _normalise_example_text(
                        row.get("snippet") or row.get("text") or row.get("content")
                    )
                ]
                if term and examples:
                    document_observations.append(
                        _t("- Befund: Für den explorativen Suchanker "
                        f"`{term}` ist ein konkreter Dokumentbeleg sichtbar. "
                        "Evidenz: `document_search` liefert ", f"""- Finding: The exploratory search anchor `{term}` has visible document evidence. Evidence: `document_search` returns """)
                        + ", ".join(
                            f"`{_compact_quote(example, 100)}`"
                            for example in examples
                        )
                        + _t(". Limitation: Der gezielt gewählte Suchanker und "
                        "einzelne Dokumenttreffer belegen weder Häufigkeit noch "
                        "Repräsentativität im Gesamtkorpus.", '. Limitation: The selected anchor and individual document matches establish neither frequency nor representativeness across the corpus.')
                    )
        if item.tool == "metadata_values":
            values = item.raw_surface.get("values")
            if isinstance(values, dict):
                compact_fields: List[str] = []
                varying_fields: List[str] = []
                for field in ("source", "register", "model", "text_type", "variant", "reference_kind"):
                    entries = values.get(field)
                    if not isinstance(entries, list):
                        continue
                    cleaned = [
                        _normalise_example_text(entry)
                        for entry in entries[:4]
                        if _normalise_example_text(entry)
                    ]
                    cleaned = list(dict.fromkeys(cleaned))
                    if not cleaned:
                        continue
                    if len(cleaned) == 1:
                        compact_fields.append(f"`{field}={cleaned[0]}`")
                    else:
                        varying_fields.append(_t(f"`{field}` mit ", f"""`{field}` with """) + " / ".join(f"`{value}`" for value in cleaned[:3]))
                if varying_fields:
                    metadata_observations.append(
                        _t("- Befund: Im sichtbaren Metadatenausschnitt gibt es tatsächlich Vergleichsachsen. Evidenz: `metadata_values` zeigt ", '- Finding: The visible metadata excerpt provides comparison axes. Evidence: `metadata_values` shows ')
                        + ", ".join(varying_fields[:3])
                        + _t(". Limitation: Sichtbar sind nur die vom Tool gelieferten Feldwerte, nicht automatisch alle extern möglichen Subkorpora.", '. Limitation: The visible field values are those returned by the tool. They do not automatically cover every possible subcorpus.')
                    )
                elif compact_fields:
                    metadata_observations.append(
                        _t("- Befund: Im sichtbaren Metadatenausschnitt wirkt das Korpus stark homogen. Evidenz: `metadata_values` zeigt ", '- Finding: The corpus appears homogeneous in the visible metadata excerpt. Evidence: `metadata_values` shows ')
                        + ", ".join(compact_fields[:4])
                        + _t(". Limitation: Das belegt Homogenität nur für die sichtbaren Metadatenfelder.", '. Limitation: This establishes homogeneity for the visible metadata fields only.')
                    )
        if item.tool == "frequency_list":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                try:
                    query_args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    query_args = {}
                scope_bits = [
                    f"{key}={query_args.get(key)}"
                    for key in ("group_by", "pos")
                    if isinstance(query_args, dict)
                    and query_args.get(key) not in (None, "")
                ]
                evidence_label = "`frequency_list`"
                if scope_bits:
                    evidence_label += " (" + ", ".join(scope_bits) + ")"
                try:
                    corpus_tokens = int(item.raw_surface.get("corpus_tokens"))
                except (TypeError, ValueError):
                    corpus_tokens = 0
                denominator_scope = str(
                    item.raw_surface.get("denominator_scope", "") or ""
                ).strip().lower()
                if (
                    corpus_tokens > 0
                    and corpus_tokens not in seen_corpus_token_counts
                    and denominator_scope in {"", "corpus"}
                ):
                    seen_corpus_token_counts.add(corpus_tokens)
                    formatted_tokens = format_int(corpus_tokens)
                    corpus_scope_observations.append(
                        _t("- Befund: Der aktive Korpusscope umfasst "
                        f"{formatted_tokens} Tokens. Evidenz: `frequency_list` "
                        f"weist `corpus_tokens={corpus_tokens}`", f"""- Finding: The active corpus scope contains {formatted_tokens} tokens. Evidence: `frequency_list` reports `corpus_tokens={corpus_tokens}`""")
                        + (
                            _t(" und `denominator_scope=corpus`", ' and `denominator_scope=corpus`')
                            if denominator_scope == "corpus"
                            else ""
                        )
                        + _t(" aus. Limitation: Die Tokenzahl beschreibt den "
                        "Umfang, nicht die thematische oder dokumentbezogene "
                        "Vielfalt des Korpus.", '. Limitation: The token count measures size, rather than thematic or document diversity.')
                    )
                top_words: List[str] = []
                top_word_bits: List[str] = []
                for row in rows[:8]:
                    if not isinstance(row, dict):
                        continue
                    word = _normalise_example_text(row.get("word"))
                    if not _word_like_token(word):
                        continue
                    top_words.append(word)
                    if row.get("f") not in (None, ""):
                        top_word_bits.append(f"`{word}` (f={row.get('f')})")
                    else:
                        top_word_bits.append(f"`{word}`")
                    if len(top_words) >= 4:
                        break
                if top_words:
                    group_by = str(query_args.get("group_by", "") or "").strip()
                    pos = str(query_args.get("pos", "") or "").strip().upper()
                    unit_label = group_by or "word"
                    if pos:
                        saw_pos_filtered_frequency = True
                        finding = (
                            _t(f"Im sichtbaren POS={pos}-Profil der "
                            f"`{unit_label}`-Frequenzen stehen ", f"""The visible POS={pos} profile of `{unit_label}` frequencies is headed by """)
                            + ", ".join(top_word_bits[:4])
                            + _t(" an der Spitze.", '.')
                        )
                        limitation = (
                            _t(f"Das gilt nur für die sichtbare Top-N-Liste der "
                            f"getrennten POS={pos}-Auswertung.", f"""This applies to the visible top-N list of the separate POS={pos} analysis.""")
                        )
                    elif group_by.lower() == "pos":
                        saw_pos_distribution = True
                        finding = (
                            _t("Die sichtbare POS-Kategorienverteilung beginnt mit ", 'The visible POS category distribution starts with ')
                            + ", ".join(top_word_bits[:4])
                            + "."
                        )
                        limitation = (
                            _t("Diese Auswertung beschreibt grammatische "
                            "Kategorien, nicht einzelne Lexeme oder Themen.", 'This analysis describes grammatical categories, rather than individual lexemes or topics.')
                        )
                    else:
                        saw_unfiltered_frequency = True
                        finding = (
                            _t(f"Die sichtbare unfiltrierte `{unit_label}`-"
                            "Frequenzliste beginnt mit ", f"""The visible unfiltered `{unit_label}` frequency list starts with """)
                            + ", ".join(top_word_bits[:4])
                            + "."
                        )
                        limitation = (
                            _t("Die unfiltrierte Top-N-Liste mischt grammatische "
                            "und lexikalische Einheiten und ist keine "
                            "Themenrangliste.", 'The unfiltered top-N list mixes grammatical and lexical units. It is not a topic ranking.')
                        )
                    frequency_observations.append(
                        _t("- Befund: ", '- Finding: ')
                        + finding
                        + _t(" Evidenz: ", ' Evidence: ')
                        + evidence_label
                        + _t(" liefert die genannten f-Werte. Limitation: ", ' provides the reported f values. Limitation: ')
                        + limitation
                    )
    observation_groups = [
        group
        for group in (
            semantic_observations,
            cluster_observations,
            frequency_observations,
            document_observations,
            corpus_scope_observations,
            metadata_observations,
        )
        if group
    ]
    group_offset = 0
    while len(observation_lines) < 10:
        added = False
        for group in observation_groups:
            if group_offset >= len(group):
                continue
            candidate = group[group_offset]
            if candidate not in observation_lines:
                observation_lines.append(candidate)
                added = True
            if len(observation_lines) >= 10:
                break
        if not added:
            break
        group_offset += 1
    if len(observation_lines) < 3:
        seen_statements: set[str] = set()
        seen_fact_kinds: set[str] = set()
        fact_priority = {
            "kwic_example": 0,
            "ranked_row": 1,
            "count": 2,
            "distribution": 3,
            "metadata": 4,
            "limitation": 9,
        }
        ranked_facts = sorted(
            observed_facts,
            key=lambda fact: (
                fact_priority.get(fact.fact_kind, 5),
                len(fact.statement or ""),
            ),
        )
        evidence_tool_by_id = {
            item.id: str(item.tool or "").strip() for item in evidence_items
        }
        for fact in ranked_facts:
            if fact.fact_kind == "limitation":
                continue
            statement = _compact_sentences(fact.statement, 260)
            if (
                not statement
                or statement in seen_statements
                or statement
                in {
                    line[2:]
                    for line in observation_lines
                    if line.startswith("- ")
                }
            ):
                continue
            priority_bonus = 1 if fact.fact_kind not in seen_fact_kinds else 0
            if priority_bonus or len(observation_lines) < 2:
                # Interne Fakt-/Evidenz-IDs bleiben trace-only: sichtbar ist
                # nur das liefernde Werkzeug (H6/B2).
                source_tools = list(
                    dict.fromkeys(
                        tool
                        for tool in (
                            evidence_tool_by_id.get(source, "")
                            for source in fact.source_evidence_ids
                        )
                        if tool
                    )
                )
                if source_tools:
                    tool_word = (
                        _t("Werkzeug", 'tool') if len(source_tools) == 1 else _t("Werkzeuge", 'tools')
                    )
                    evidence_label = tool_word + " " + ", ".join(
                        f"`{tool}`" for tool in source_tools[:2]
                    )
                else:
                    evidence_label = _t("sichtbare Tool-Evidenz", 'visible tool evidence')
                observation_lines.append(
                    _t(f"- Befund: {statement} Evidenz: {evidence_label}."
                    " Limitation: Belegt ist nur dieser sichtbare Tool-Fakt.", f"""- Finding: {statement} Evidence: {evidence_label}. Limitation: Only this visible tool fact is established.""")
                )
                seen_statements.add(statement)
                seen_fact_kinds.add(fact.fact_kind)
            if len(observation_lines) >= 3:
                break
    limitation_lines: List[str] = []
    for fact in observed_facts:
        if fact.fact_kind != "limitation":
            continue
        statement = _compact_sentences(fact.statement, 220)
        if statement:
            limitation_lines.append(f"- {statement}")
    limitation_lines = _dedupe_ordered_strs(limitation_lines)
    for gap in evidence_gaps:
        line = _user_facing_evidence_gap(gap)
        duplicates_partial_scope = (
            ("partiell" in line.lower() or "abgeschnitten" in line.lower())
            and any(
                "partiell" in existing.lower()
                or "abgeschnitten" in existing.lower()
                for existing in limitation_lines
            )
        )
        if line and not duplicates_partial_scope:
            limitation_lines.append(f"- {line}")
    if not limitation_lines:
        limitation_lines.append(
            _t("- Der Überblick stützt sich nur auf die aktuell sichtbaren Tool-Ausschnitte. Ohne weitere Suchläufe oder zusätzliche Evidenz bleibt er ein begrenzter Teilblick.", '- The overview is based on the currently visible tool excerpts. Further queries or evidence are needed for a broader characterisation.')
        )
    hypothesis_requested = bool(
        contract is not None
        and (
            _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(
                contract.question_scope or ""
            )
            or any(
                _RESPONSE_REQUIREMENT_HYPOTHESIS_PATTERN.search(
                    " ".join(
                        part
                        for part in (
                            getattr(requirement, "description", ""),
                            getattr(requirement, "source_quote", ""),
                        )
                        if str(part or "").strip()
                    )
                )
                for requirement in contract.response_requirements
            )
        )
    )
    if not observation_lines:
        if not evidence_items:
            parts = [
                _t("Ich kann diese Analyse gerade nicht sicher tool-gestützt beantworten.", 'This run has not produced an evidence-backed analysis.'),
            ]
            capitulation_limitations = _dedupe_ordered_strs(
                [
                    _t("- Es liegt keine belegbare Tool-Evidenz für eine Analyse vor.", '- No verifiable tool evidence for an analysis is available.'),
                    *limitation_lines,
                ]
            )
            parts.extend(
                ["", _t("Limitationen:", 'Limitations:'), *capitulation_limitations[:6]]
            )
            return "\n".join(parts).strip()
        return build_conservative_markdown(
            observed_facts,
            evidence_gaps=evidence_gaps,
        )
    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        _t("Beobachtungen:", 'Observations:'),
        *observation_lines,
    ]
    if saw_recurring_semantic_theme:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Die wiederkehrenden Themen im sichtbaren semantischen "
                "Retrieval sind plausible Ausgangspunkte für Folgeabfragen, "
                "aber ohne Verteilungsanalyse keine Aussage über zentrale oder "
                "dominante Themen des Gesamtkorpus.", '- Recurring themes in the visible semantic retrieval suggest follow-up queries. Identifying central or dominant topics across the corpus requires a distribution analysis.'),
            ]
        )
    elif semantic_observations:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Die konkreten semantischen Treffer liefern Suchhypothesen "
                "für Folgeabfragen. Ohne ein wiederkehrendes Muster über "
                "mehrere Treffer hinweg belegen sie jedoch keine Themenachse "
                "des Korpus.", '- Concrete semantic matches suggest hypotheses for follow-up queries. A corpus theme requires a recurring pattern across multiple matches.'),
            ]
        )
    elif saw_pos_distribution and saw_pos_filtered_frequency:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Die POS-Kategorienverteilung und die getrennten "
                "POS-gefilterten Lexemprofile beantworten verschiedene "
                "Fragen. Kategorienhäufigkeiten und Lexemranglisten werden "
                "deshalb nicht zu einer gemeinsamen Rangfolge verschmolzen.", '- POS category distributions and separate POS-filtered lexeme profiles answer different questions. Category frequencies and lexeme rankings remain separate.'),
            ]
        )
    elif saw_unfiltered_frequency and saw_pos_filtered_frequency:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Die getrennten unfiltrierten und POS-gefilterten "
                "Frequenzprofile beantworten verschiedene Fragen: Das erste "
                "zeigt die häufigsten Einheiten insgesamt, das zweite macht "
                "die sichtbare lexikalische Spitze einer Wortart zugänglich. "
                "Die beiden Ergebnisräume dürfen nicht zu einer gemeinsamen "
                "Rangfolge verschmolzen werden.", '- Unfiltered and POS-filtered frequency profiles answer different questions. The former shows the most frequent units overall. The latter shows the lexical ranking within a part of speech. Their rankings remain separate.'),
            ]
        )
    elif frequency_observations and metadata_observations:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Metadatenprofil und Frequenzspitze beschreiben gemeinsam "
                "den verfügbaren Vergleichsscope und die Form der sichtbaren "
                "Lexik; belastbare Themenhypothesen erfordern anschließend "
                "Kontext- oder semantische Evidenz.", '- The metadata profile and frequency ranking describe the available comparison scope and visible vocabulary. Topic hypotheses then require contextual or semantic evidence.'),
            ]
        )
    else:
        parts.extend(
            [
                "",
                "Interpretation:",
                _t("- Die sichtbaren Befunde liefern überprüfbare Ausgangspunkte "
                "für weitere Analysen, reichen aber allein nicht für eine "
                "Vollcharakterisierung des Korpus.", '- The visible findings provide testable starting points for further analysis. A full corpus characterisation requires additional evidence.'),
            ]
        )
    if hypothesis_requested:
        # Ehrlichkeit statt deterministischer Hypothesen-Fabrikation (H6/B2):
        # der deterministische Renderer erfindet keine Hypothesen.
        parts.extend(
            [
                "",
                _t("Angefragte Hypothesen: nicht enthalten, der Turn endete "
                "vor der Modell-Synthese. Eine Fortsetzung liefert sie auf Basis "
                "der obigen Belege.", 'Requested hypotheses are not included because the turn ended before model synthesis. Continuing the turn can produce them from the evidence above.'),
            ]
        )
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def _build_method_advice_markdown(
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    steps: List[tuple[str, str]] = []
    frequency_signals: List[tuple[str, List[str]]] = []
    saw_inventory_like_signal = False
    for item in evidence_items:
        if item.tool == "metadata_values":
            saw_inventory_like_signal = True
            values = item.raw_surface.get("values")
            if isinstance(values, dict):
                analytical_fields: List[tuple[str, List[str]]] = []
                homogeneous_fields: List[str] = []
                varying_fields: List[str] = []
                for field, entries in values.items():
                    field_name = str(field)
                    cleaned = _metadata_value_list(entries, max_items=5)
                    if not _metadata_field_is_analytical(field_name, cleaned):
                        continue
                    analytical_fields.append((field_name, cleaned))
                field_order = {field: index for index, field in enumerate(_COMPARABLE_METADATA_FIELDS)}
                analytical_fields.sort(key=lambda item: field_order.get(item[0], len(field_order)))
                for field_name, cleaned in analytical_fields:
                    if len(cleaned) == 1:
                        homogeneous_fields.append(f"`{field_name}={cleaned[0]}`")
                    else:
                        varying_fields.append(_t(f"`{field_name}` ({len(cleaned)} sichtbare Werte)", f"""`{field_name}` ({len(cleaned)} visible values)"""))
                if analytical_fields:
                    if varying_fields:
                        evidence_reason = (
                            _t("Fachlich naheliegende Metadatenfelder mit mehreren sichtbaren Werten sind ", 'Potentially relevant metadata fields with several visible values include ')
                            + ", ".join(varying_fields[:4])
                            + _t("; diese Achsen sollte man zuerst auf Fallzahlen und Vergleichbarkeit prüfen.", '. First check group sizes and comparability along these axes.')
                        )
                    elif homogeneous_fields:
                        evidence_reason = (
                            _t("Fachlich naheliegende Metadatenfelder wirken im aktuellen Ausschnitt homogen: ", 'Potentially relevant metadata fields appear homogeneous in the current excerpt: ')
                            + ", ".join(homogeneous_fields[:4])
                            + _t("; daher zuerst Vergleichsgrenzen klären.", '. First establish the available comparison scope.')
                        )
                    else:
                        evidence_reason = (
                            _t("Fachlich naheliegende Metadatenfelder sind sichtbar; ihre Eignung als Vergleichsachsen muss vor inhaltlichen Vergleichen geprüft werden.", 'Potentially relevant metadata fields are visible. Check their suitability as comparison axes before comparing content.')
                        )
                    steps.append(
                        (
                            _t("Die sichtbaren Metadatenfelder und Vergleichsgrenzen kartieren.", 'Map the visible metadata fields and comparison scope.'),
                            evidence_reason,
                        )
                    )
        elif item.tool == "frequency_list":
            saw_inventory_like_signal = True
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                top_word_bits: List[str] = []
                for row in rows[:8]:
                    if not isinstance(row, dict):
                        continue
                    word = _normalise_example_text(row.get("word"))
                    if not _word_like_token(word):
                        continue
                    if row.get("f") not in (None, ""):
                        top_word_bits.append(f"`{word}` (f={row.get('f')})")
                    else:
                        top_word_bits.append(f"`{word}`")
                    if len(top_word_bits) >= 4:
                        break
                if top_word_bits:
                    try:
                        query_args = json.loads(item.query)
                    except (TypeError, ValueError):
                        query_args = {}
                    group_by = (
                        str(query_args.get("group_by", "") or "").strip().lower()
                        if isinstance(query_args, dict)
                        else ""
                    )
                    frequency_signals.append((group_by, top_word_bits))
        elif item.tool == "semantic_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                theme_labels = _semantic_theme_labels_from_rows(rows[:5], max_labels=3)
                if not theme_labels:
                    theme_labels = _semantic_theme_labels_from_rows(
                        rows[:5],
                        max_labels=2,
                        min_document_hits=1,
                    )
                if theme_labels:
                    steps.append(
                        (
                            _t("Ein thematisches Mapping der zentralen Diskursfelder aufsetzen.", 'Map the main discourse topics.'),
                            _t("Die sichtbaren semantischen Treffer deuten bereits auf lexikalische Themenachsen wie ", 'The visible semantic matches already suggest lexical themes such as ')
                            + ", ".join(f"`{label}`" for label in theme_labels[:3])
                            + _t(" hin; daraus lassen sich gezielte Folgeabfragen ableiten.", '. These suggest targeted follow-up queries.'),
                        )
                    )
        elif item.tool == "document_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list) and rows:
                steps.append(
                    (
                        _t("Dokument- bzw. Passageproben qualitativ lesen und als Kontrollstichprobe gegen automatische Muster nutzen.", 'Read document or passage samples as a qualitative check on automatic patterns.'),
                        _t("Es liegen bereits sichtbare Dokumenttreffer vor; damit lassen sich automatische Signale früh manuell plausibilisieren.", 'Visible document matches are already available for an early manual check of automatic signals.'),
                    )
                )
        elif item.tool == "documentation_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list) and rows:
                steps.append(
                    (
                        _t("Die verfügbaren Analysepfade gegen die Dokumentation spiegeln, bevor komplexere Vergleiche geplant werden.", 'Check the available analysis paths against the documentation before planning complex comparisons.'),
                        _t("Es liegen sichtbare Dokumentationshinweise vor; damit kann man die ersten Schritte methodisch sauber am Toolbestand ausrichten.", 'Visible documentation references are available to guide initial steps using the tools at hand.'),
                    )
                    )

    if frequency_signals:
        lexical_signal = next(
            (
                signal
                for signal in frequency_signals
                if signal[0] in {"word", "lemma", "token", ""}
            ),
            None,
        )
        pos_signal = next(
            (signal for signal in frequency_signals if signal[0] == "pos"),
            None,
        )
        if lexical_signal is not None and pos_signal is not None:
            group_by, lexical_bits = lexical_signal
            _pos_group, pos_bits = pos_signal
            steps.append(
                (
                    _t("Grammatische Struktur und inhaltstragende Lexik getrennt profilieren.", 'Profile grammatical structure and content-bearing vocabulary separately.'),
                    _t("Die sichtbare POS-Verteilung beginnt mit ", 'The visible POS distribution starts with ')
                    + ", ".join(pos_bits[:3])
                    + _t(", während die ", ', while the ')
                    + (group_by or "word")
                    + _t("-basierte Liste mit ", '-based list starts with ')
                    + ", ".join(lexical_bits[:3])
                    + _t(" beginnt; beide Ebenen sollten getrennt beschrieben "
                    "und erst anschließend an Kontextbelegen interpretiert werden.", '. Describe both levels separately before interpreting them against contextual evidence.'),
                )
            )
        elif pos_signal is not None:
            _group_by, top_bits = pos_signal
            steps.append(
                (
                    _t("Die Wortartenverteilung als Strukturdiagnose prüfen.", 'Examine the POS distribution as a structural diagnostic.'),
                    _t("Die sichtbare POS-Verteilung enthält Kategorien wie ", 'The visible POS distribution includes categories such as ')
                    + ", ".join(top_bits[:4])
                    + _t("; sie beschreibt die grammatische Zusammensetzung, noch nicht die inhaltstragende Lexik.", '. It describes grammatical composition. Content-bearing vocabulary requires a separate view.'),
                )
            )
        elif lexical_signal is not None:
            _group_by, top_bits = lexical_signal
            steps.append(
                (
                    _t("Eine bereinigte Frequenzanalyse der inhaltstragenden Lexik fahren.", 'Run a filtered frequency analysis of content-bearing vocabulary.'),
                    _t("Die sichtbare Wort- oder Lemmaliste wird aktuell stark von häufigen Formen wie ", 'The visible word or lemma list is dominated by frequent forms such as ')
                    + ", ".join(top_bits[:4])
                    + _t(" dominiert; genau das motiviert einen zweiten, inhaltsbezogenen Frequenzblick.", '. This motivates a second frequency analysis focused on content.'),
                )
            )

    unique_steps: List[tuple[str, str]] = []
    seen_titles: set[str] = set()
    for title, reason in steps:
        compact_title = _compact_text(title, 220)
        compact_reason = _compact_text(reason, 320)
        if not compact_title or compact_title in seen_titles:
            continue
        seen_titles.add(compact_title)
        unique_steps.append((compact_title, compact_reason))
        if len(unique_steps) >= 3:
            break

    if len(unique_steps) < 3 and saw_inventory_like_signal:
        fallback_step = (
            _t("Eine kleine qualitative Kontrollstichprobe der ersten auffälligen Muster lesen.", 'Read a small qualitative control sample of the first striking patterns.'),
            _t("Die bisher sichtbaren Signale stammen vor allem aus Metadaten- und Frequenzsicht; eine kurze Nahlektüre verhindert, dass frühe automatische Muster überinterpretiert werden.", 'The visible signals mainly come from metadata and frequencies. Close reading helps evaluate the initial automatic patterns.'),
        )
        if fallback_step[0] not in seen_titles:
            unique_steps.append(fallback_step)
            seen_titles.add(fallback_step[0])

    limitation_lines: List[str] = []
    for gap in evidence_gaps:
        line = _user_facing_evidence_gap(gap)
        if line:
            limitation_lines.append(f"- {line}")
    if not limitation_lines:
        limitation_lines.append(
            _t("- Die Empfehlungen stützen sich nur auf die aktuell sichtbaren Evidenz-Ausschnitte; weitere Suchläufe können die Priorisierung noch verschieben.", '- The recommendations are based on the currently visible evidence excerpts. Further queries may change their priority.')
        )

    if not unique_steps:
        return build_conservative_markdown(observed_facts, evidence_gaps=evidence_gaps)

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        _t("Empfohlene erste Analyseschritte:", 'Recommended first analysis steps:'),
    ]
    for idx, (title, reason) in enumerate(unique_steps, start=1):
        parts.append(f"{idx}. {title}")
        parts.append(_t(f"   Evidenzmotiv: {reason}", f"""   Evidence basis: {reason}"""))
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def _build_followup_markdown(
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
) -> str:
    metadata_values: Dict[str, List[str]] = {}
    metadata_value_counts: Dict[str, int] = {}
    frequency_profiles: List[tuple[str, str, List[str]]] = []
    semantic_searches: List[Dict[str, Any]] = []
    document_searches: List[Dict[str, Any]] = []

    for item in evidence_items:
        if item.tool == "metadata_values":
            values = item.raw_surface.get("values")
            if isinstance(values, dict):
                raw_counts = item.raw_surface.get("value_counts")
                if not isinstance(raw_counts, dict):
                    raw_counts = {}
                for field, entries in values.items():
                    if not isinstance(entries, list):
                        continue
                    cleaned = [
                        _normalise_example_text(entry)
                        for entry in entries[:4]
                        if _normalise_example_text(entry)
                    ]
                    if cleaned:
                        field_name = str(field)
                        metadata_values[field_name] = cleaned
                        try:
                            metadata_value_counts[field_name] = int(
                                raw_counts.get(field_name, len(cleaned))
                            )
                        except (TypeError, ValueError):
                            metadata_value_counts[field_name] = len(cleaned)
        elif item.tool == "frequency_list":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                visible_words: List[str] = []
                for row in rows[:DEFAULT_GROUNDING_ROW_LIMIT]:
                    if not isinstance(row, dict):
                        continue
                    word = _normalise_example_text(row.get("word"))
                    if not _word_like_token(word):
                        continue
                    visible_words.append(word)
                    if len(visible_words) >= 5:
                        break
                if visible_words:
                    try:
                        query_args = json.loads(item.query)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        query_args = {}
                    if not isinstance(query_args, dict):
                        query_args = {}
                    group_by = str(
                        query_args.get("group_by", "") or ""
                    ).strip().lower()
                    pos = str(query_args.get("pos", "") or "").strip().upper()
                    frequency_profiles.append(
                        (group_by, pos, visible_words)
                    )
        elif item.tool == "semantic_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                try:
                    query_args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    query_args = {}
                if not isinstance(query_args, dict):
                    query_args = {}
                term = _normalise_example_text(
                    query_args.get("term") or query_args.get("query")
                )
                if not term:
                    continue
                doc_ids = {
                    str(row.get("doc_id"))
                    for row in rows
                    if isinstance(row, dict)
                    and row.get("doc_id") not in (None, "")
                }
                semantic_searches.append(
                    {
                        "term": term.replace("`", "'"),
                        "visible_rows": len(rows),
                        "visible_docs": len(doc_ids),
                        "top_n": query_args.get("top_n"),
                        "min_score": query_args.get("min_score"),
                    }
                )
        elif item.tool == "document_search":
            rows = item.raw_surface.get("rows")
            if isinstance(rows, list):
                try:
                    query_args = json.loads(item.query) if item.query else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    query_args = {}
                if not isinstance(query_args, dict):
                    query_args = {}
                term = _normalise_example_text(
                    query_args.get("term") or query_args.get("query")
                )
                if term:
                    document_searches.append(
                        {
                            "term": term.replace("`", "'"),
                            "visible_rows": len(rows),
                        }
                    )

    followups: List[tuple[str, str]] = []
    unfiltered_lexical_profile = next(
        (
            profile
            for profile in frequency_profiles
            if profile[0] in {"", "word", "lemma", "token"}
            and not profile[1]
        ),
        None,
    )
    pos_filtered_profiles = [
        profile
        for profile in frequency_profiles
        if profile[0] in {"", "word", "lemma", "token"}
        and profile[1]
    ]
    pos_distribution = next(
        (profile for profile in frequency_profiles if profile[0] == "pos"),
        None,
    )
    if len(pos_filtered_profiles) >= 2:
        profile_bits = [
            f"POS={pos}: " + ", ".join(f"`{word}`" for word in words[:2])
            for _group_by, pos, words in pos_filtered_profiles[:2]
        ]
        followups.append(
            (
                _t("Welche Kontexte erklären die unterschiedlichen lexikalischen Spitzen der getrennten Wortartenprofile?", 'Which contexts explain the different lexical rankings of the separate POS profiles?'),
                _t("Getrennte sichtbare Auswertungen zeigen ", 'Separate visible analyses show ')
                + "; ".join(profile_bits)
                + _t("; KWIC oder Kollokationen können sie erklären, sie bilden aber keine gemeinsame Rangliste.", '. Concordance lines or collocations can explain them, but they do not form a joint ranking.'),
            )
        )
    elif pos_filtered_profiles:
        _group_by, pos, words = pos_filtered_profiles[0]
        followups.append(
            (
                _t(f"In welchen Kontexten treten die sichtbaren Spitzen des {pos}-Profils auf?", f"""In which contexts do the leading words of the {pos} profile occur?"""),
                f"Die getrennte {pos}-Auswertung zeigt "
                + ", ".join(f"`{word}`" for word in words[:4])
                + _t("; ihre Funktion lässt sich erst an KWIC- oder Kollokationsevidenz beurteilen.", '. Their function requires concordance or collocation evidence.'),
            )
        )
    elif unfiltered_lexical_profile is not None:
        group_by, _pos, words = unfiltered_lexical_profile
        scope_label = group_by or "word"
        followups.append(
            (
                _t("Welche inhaltstragenden Lexeme werden sichtbar, wenn die häufigsten Formen nach Wortart und Kontext differenziert werden?", 'Which content-bearing lexemes appear when the most frequent forms are broken down by part of speech and context?'),
                _t("Die sichtbare, unfiltrierte Frequenzauswertung "
                f"(group_by={scope_label}) beginnt mit ", f"""The visible unfiltered frequency analysis (group_by={scope_label}) starts with """)
                + ", ".join(f"`{word}`" for word in words[:4])
                + _t("; eine POS- und Kontextaufschlüsselung trennt Strukturwörter von fachlich interessanter Lexik.", '. A breakdown by part of speech and context separates function words from relevant content vocabulary.'),
            )
        )
    elif pos_distribution is not None:
        _group_by, _pos, words = pos_distribution
        followups.append(
            (
                _t("Wie stark variiert die sichtbare Wortartenstruktur zwischen Dokumenten oder inhaltlich begründeten Teilmengen?", 'How much does the visible POS structure vary between documents or substantively defined subsets?'),
                _t("Die sichtbare POS-Auswertung beginnt mit ", 'The visible POS analysis starts with ')
                + ", ".join(f"`{word}`" for word in words[:4])
                + _t("; eine Verteilungsanalyse würde zeigen, ob diese Gesamtstruktur lokal stabil ist.", '. A distribution analysis would show whether this overall structure is locally stable.'),
            )
        )

    if semantic_searches:
        search = semantic_searches[0]
        term = search["term"]
        visible_rows = search["visible_rows"]
        term_phrase = (
            _t("das Lexem", 'the lexeme') if len(term.split()) == 1 else _t("die Suchformulierung", 'the search expression')
        )
        followups.append(
            (
                _t(f"Wie lässt sich {term_phrase} `{term}` als exakte "
                "CQLF-Abfrage operationalisieren, und welche KWIC- oder "
                "Kollokationsmuster zeigen deren Belege?", f"""How can {term_phrase} `{term}` be operationalised as an exact CQLF query, and which concordance or collocation patterns do its matches show?"""),
                _t(f"Die semantische Suche zu `{term}` liefert {visible_rows} sichtbare Treffer; "
                "ein semantisches Ranking belegt jedoch weder exakte Wortvorkommen noch lokale Kookkurrenz, weshalb der lexikalische Gegencheck nötig ist.", f"""Semantic search for `{term}` returns {visible_rows} visible matches. An exact lexical check is needed to establish word occurrences and local co-occurrence."""),
            )
        )
        followups.append(
            (
                _t(f"Wie verteilen sich die nach einer expliziten CQLF-"
                f"Operationalisierung gefundenen Belege für `{term}` über die "
                "Dokumente des aktuellen Korpus?", f"""After an explicit CQLF operationalisation, how are the matches for `{term}` distributed across documents in the current corpus?"""),
                (
                    _t(f"Die sichtbare semantische Ergebnisliste umfasst {search['visible_docs']} Dokumente; ", f"""The visible semantic result list covers {search['visible_docs']} documents. """)
                    if search["visible_docs"]
                    else _t("Die sichtbare semantische Ergebnisliste benennt Dokumenttreffer; ", 'The visible semantic result list identifies matching documents. ')
                )
                + _t("erst eine getrennt definierte lexikalische Abfrage mit "
                "anschließender Dispersion zeigt, ob deren exakte Belege breit "
                "verteilt oder lokal konzentriert sind.", 'A separately defined lexical query followed by dispersion analysis can establish whether exact matches are broadly distributed or locally concentrated.'),
            )
        )

    if document_searches:
        search = document_searches[0]
        term = search["term"]
        followups.append(
            (
                _t(f"Wie häufig ist `{term}` im Korpus exakt belegt, und welche wiederkehrenden KWIC- oder Kollokationskontexte zeigen seine Treffer?", f"""How often is `{term}` exactly attested in the corpus, and which recurring concordance or collocation contexts do its hits show?"""),
                _t(f"`document_search` liefert für `{term}` {search['visible_rows']} sichtbare Dokumenttreffer; "
                "eine Dokumentfundstelle ist weder eine exakte Gesamttrefferzahl noch bereits eine Analyse wiederkehrender lokaler Kontexte.", f"""`document_search` returns {search['visible_rows']} visible document matches for `{term}`. A document match alone gives neither an exact total hit count nor an analysis of recurring local contexts."""),
            )
        )

    ignored_metadata_axes = {"paired_with", "reference_kind", "source_license"}
    varying_axes = [
        (field, values, metadata_value_counts.get(field, len(values)))
        for field, values in metadata_values.items()
        if field not in ignored_metadata_axes
        and not _IDENTIFIER_METADATA_FIELD_RE.search(field)
        and 2 <= metadata_value_counts.get(field, len(values)) <= 16
        and len(set(values)) >= 2
    ]
    if varying_axes:
        field, values, value_count = sorted(
            varying_axes,
            key=lambda axis: (
                axis[0] not in _PARTITION_METADATA_FIELDS,
                axis[2],
                axis[0],
            ),
        )[0]
        value_text = "`, `".join(values[:4])
        if field in _PARTITION_METADATA_FIELDS:
            question = (
                _t(f"Welche fachliche Bedeutung hat die technische Metadatenachse `{field}` "
                f"mit den sichtbaren Werten `{value_text}`, und ist sie für einen "
                "korpuslinguistischen Kontrast interpretierbar?", f"""What does the technical metadata axis `{field}` with visible values `{value_text}` mean, and is it interpretable as a corpus-linguistic contrast?""")
            )
            reason = (
                _t(f"`metadata_values` belegt für `{field}` {value_count} Werte; "
                "die Feldbezeichnung allein erklärt aber weder den Zweck der Partition "
                "noch eine fachliche Vergleichshypothese.", f"""`metadata_values` establishes {value_count} values for `{field}`. The field name alone explains neither the partition purpose nor a substantive comparison hypothesis.""")
            )
        else:
            question = (
                _t(f"Welche lexikalischen oder kontextuellen Unterschiede zeigen die "
                f"dokumentierten Gruppen der Metadatenachse `{field}`?", f"""Which lexical or contextual differences do the documented groups of metadata axis `{field}` show?""")
            )
            reason = (
                _t(f"`metadata_values` belegt für `{field}` {value_count} Werte "
                f"(sichtbar: `{value_text}`); damit liegt eine konkrete, noch "
                "inhaltlich zu prüfende Vergleichsachse vor.", f"""`metadata_values` establishes {value_count} values for `{field}` (visible: `{value_text}`). This provides a concrete comparison axis whose meaning remains to be examined.""")
            )
        followups.append(
            (question, reason)
        )

    if semantic_searches:
        search = semantic_searches[0]
        term = search["term"]
        settings = []
        if search["top_n"] not in (None, ""):
            settings.append(f"Top-N={search['top_n']}")
        if search["min_score"] not in (None, ""):
            settings.append(_t(f"Mindestähnlichkeit={search['min_score']}", f"Minimum similarity={search['min_score']}"))
        followups.append(
            (
                _t(f"Welche Treffer für `{term}` bleiben stabil, wenn Top-N und Mindestähnlichkeit der semantischen Suche systematisch variiert werden?", f"""Which matches for `{term}` remain stable when top-N and minimum similarity are varied systematically in semantic search?"""),
                _t("Bisher liegt genau ein sichtbarer Retrieval-Lauf", 'There is currently one visible retrieval run')
                + (f" ({', '.join(settings)})" if settings else "")
                + _t(" vor; eine Sensitivitätsanalyse prüft die Robustheit der Ergebnisliste, ohne aus einzelnen Snippet-Wörtern Themenachsen abzuleiten.", '. A sensitivity analysis tests the robustness of the result list. Individual snippet words alone do not establish topic dimensions.'),
            )
        )

    if unfiltered_lexical_profile is not None:
        group_by, _pos, _words = unfiltered_lexical_profile
        current_unit = group_by or "word"
        target_unit = "lemma" if current_unit != "lemma" else "word"
        followups.append(
            (
                _t(f"Wie verändert sich die sichtbare Rangfolge bei gleicher Auswahl, wenn statt `{current_unit}` nach `{target_unit}` gruppiert wird?", f"""How does the visible ranking change within the same selection when grouping by `{target_unit}` instead of `{current_unit}`?"""),
                _t(f"Die vorliegende Frequenzliste verwendet `group_by={current_unit}`; "
                "der kontrollierte Wechsel der Zähleinheit trennt Flexionsvariation von lexikalischer Häufigkeit.", f"""The frequency list uses `group_by={current_unit}`. A controlled change of counting unit separates inflectional variation from lexical frequency."""),
            )
        )
    if pos_distribution is not None and unfiltered_lexical_profile is not None:
        _group_by, _pos, words = pos_distribution
        followups.append(
            (
                _t("Wie stark schwankt die sichtbare Wortartenverteilung zwischen Dokumenten?", 'How much does the visible POS distribution vary across documents?'),
                _t("Die aggregierte POS-Liste beginnt mit ", 'The aggregate POS list starts with ')
                + ", ".join(f"`{word}`" for word in words[:4])
                + _t("; Gesamtwerte allein zeigen nicht, ob einzelne Dokumente diese Verteilung tragen.", '. Aggregate values alone do not show which documents contribute to this distribution.'),
            )
        )
    if len(pos_filtered_profiles) >= 2:
        profile_seeds = [
            (pos, words[0])
            for _group_by, pos, words in pos_filtered_profiles[:2]
            if words
        ]
        if len(profile_seeds) >= 2:
            seed_text = _t(" und ", ' and ').join(
                f"`{word}` ({pos})"
                for pos, word in profile_seeds
            )
            followups.append(
                (
                    _t(f"Wie sind {seed_text} jeweils über die Dokumente des Korpus verteilt?", f"""How are {seed_text} individually distributed across the documents in the corpus?"""),
                    _t("Die getrennten POS-Profile liefern aggregierte Häufigkeiten; "
                    "eine je Term separat berechnete Dispersion prüft, ob die "
                    "sichtbaren Spitzen breit belegt oder auf wenige Dokumente konzentriert sind.", 'The separate POS profiles provide aggregate frequencies. Dispersion calculated separately for each term tests whether the leading words are broadly distributed or concentrated in a few documents.'),
                )
            )
        grouping_units = {
            group_by or "word"
            for group_by, _pos, _words in pos_filtered_profiles[:2]
        }
        if len(grouping_units) == 1:
            current_unit = next(iter(grouping_units))
            target_unit = "lemma" if current_unit != "lemma" else "word"
            pos_text = "/".join(
                pos
                for _group_by, pos, _words in pos_filtered_profiles[:2]
            )
            followups.append(
                (
                    _t(f"Wie verändern sich die getrennten {pos_text}-Ranglisten, wenn bei denselben POS-Filtern statt `{current_unit}` nach `{target_unit}` gruppiert wird?", f"""How do the separate {pos_text} rankings change under the same POS filters when grouping by `{target_unit}` instead of `{current_unit}`?"""),
                    _t(f"Die sichtbaren Profile verwenden jeweils `group_by={current_unit}`; "
                    "der kontrollierte Wechsel der Zähleinheit zeigt Flexionsvariation, "
                    "ohne die getrennten Ergebnisräume zu einer Rangliste zu verschmelzen.", f"""The visible profiles each use `group_by={current_unit}`. A controlled change of counting unit shows inflectional variation while keeping the separate result spaces apart."""),
                )
            )

    unique_followups: List[tuple[str, str]] = []
    seen_questions: set[str] = set()
    for question, reason in followups:
        compact_question = _compact_text(question, 220)
        compact_reason = _compact_text(reason, 360)
        if not compact_question or compact_question in seen_questions:
            continue
        seen_questions.add(compact_question)
        unique_followups.append((compact_question, compact_reason))
        if len(unique_followups) >= 4:
            break

    limitation_lines: List[str] = []
    for gap in evidence_gaps:
        line = _user_facing_evidence_gap(gap)
        if line:
            limitation_lines.append(f"- {line}")
    if not limitation_lines:
        limitation_lines.append(
            _t("- Die Anschlussfragen leiten sich nur aus den aktuell sichtbaren Evidenz-Ausschnitten ab. Ohne weitere Suchläufe bleiben sie vorläufig.", '- The follow-up questions come from the currently visible evidence excerpts. Further queries are needed to test them.')
        )

    if not unique_followups:
        return build_conservative_markdown(observed_facts, evidence_gaps=evidence_gaps)

    parts: List[str] = [
        _t("Analysebericht (sichtbare Evidenz)", 'Analysis report (visible evidence)'),
        "",
        _t("Naheliegende Anschlussfragen:", 'Suggested follow-up questions:'),
    ]
    for question, reason in unique_followups:
        parts.append(f"- {question}")
        parts.append(_t(f"  Evidenzmotiv: {reason}", f"""  Evidence basis: {reason}"""))
    if limitation_lines:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *limitation_lines[:6]])
    return "\n".join(parts).strip()


def build_conservative_markdown(
    observed_facts: Sequence[ObservedFact],
    *,
    evidence_gaps: Sequence[str],
    accepted_claim_ids: Sequence[str] | None = None,
) -> str:
    observation_lines: List[str] = []
    fact_limitation_lines: List[str] = []
    for fact in observed_facts:
        line = _compact_sentences(fact.statement, 280)
        if not line:
            continue
        if fact.fact_kind == "limitation":
            fact_limitation_lines.append(f"- {line}")
            continue
        observation_lines.append(f"- {line}")
    system_gap_lines: List[str] = []
    for gap in evidence_gaps:
        line = _user_facing_evidence_gap(gap)
        if line:
            system_gap_lines.append(f"- {line}")
    if not observation_lines:
        observation_lines.append(_t("- Es liegen noch keine hinreichend belegten Beobachtungen für eine belastbare Antwort vor.", '- No sufficiently supported observations are available for an answer.'))
    visible_observations = observation_lines[:24]
    if len(observation_lines) > len(visible_observations):
        visible_observations.append(
            _t(f"- Weitere {len(observation_lines) - len(visible_observations)} "
            "direkt belegte Beobachtungen sind im Evidenzpaket enthalten.", f"""- A further {len(observation_lines) - len(visible_observations)} directly supported observations are included in the evidence package.""")
        )
    limitation_lines = list(dict.fromkeys([*system_gap_lines, *fact_limitation_lines]))
    visible_limitations = limitation_lines[:24]
    if len(limitation_lines) > len(visible_limitations):
        visible_limitations.append(
            _t(f"- Weitere {len(limitation_lines) - len(visible_limitations)} "
            "Limitationen sind im Evidenzpaket enthalten.", f"""- A further {len(limitation_lines) - len(visible_limitations)} limitations are included in the evidence package.""")
        )
    parts = [
        _t("Ich kann hier nur die direkt belegten Beobachtungen sicher berichten.", 'Here are the directly supported observations.'),
        "",
        _t("Beobachtungen:", 'Observations:'),
        *visible_observations,
    ]
    if visible_limitations:
        parts.extend(["", _t("Limitationen:", 'Limitations:'), *visible_limitations])
    return "\n".join(parts).strip()


def build_grounded_markdown(
    contract: AnalysisContract,
    observed_facts: Sequence[ObservedFact],
    evidence_items: Sequence[EvidenceItem],
    *,
    evidence_gaps: Sequence[str],
    accepted_claim_ids: Sequence[str] | None = None,
) -> str:
    if contract.analysis_family == "kwic_context" and contract.response_shape == "grounded_kwic_presence":
        return _build_kwic_presence_markdown(
            evidence_items,
            question_scope=contract.question_scope,
            evidence_gaps=evidence_gaps,
            deliverable_kind=contract.deliverable_kind,
        )
    if contract.analysis_family == "term_frequency" and contract.response_shape == "grounded_term_frequency":
        return _build_term_frequency_markdown(
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    # 'collocation' war gueltiger Familienname mit Werkzeugbuendel, aber
    # ohne Verfasser, und fiel damit still in den konservativen Rueckfall.
    # Derselbe Verfasser bedient sie: er liest collocate_stats bereits
    # vollstaendig, nennt Knoten, Fenster, Schwelle und Sortierung und
    # rechnet f nicht gegen die Knotenfrequenz auf.
    if contract.analysis_family in ("term_profile", "collocation"):
        return _build_term_profile_markdown(
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "word_sketch_profile":
        return _build_word_sketch_markdown(
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "contrast_keyness":
        return _build_contrast_markdown(
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "metadata_capability":
        return _build_metadata_capability_markdown(
            evidence_items,
            question_scope=contract.question_scope,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "semantic_retrieval":
        return _build_semantic_markdown(
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "open_research" and contract.deliverable_kind == "method_advice":
        return _build_method_advice_markdown(
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "open_research" and contract.deliverable_kind == "followup_questions":
        return _build_followup_markdown(
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
        )
    if contract.analysis_family == "open_research":
        return _build_exploratory_markdown(
            observed_facts,
            evidence_items,
            evidence_gaps=evidence_gaps,
            contract=contract,
        )
    return build_conservative_markdown(
        observed_facts,
        evidence_gaps=evidence_gaps,
        accepted_claim_ids=accepted_claim_ids,
    )
