from __future__ import annotations

import json
import contextlib
import copy
import time
import asyncio
import functools
import inspect
import uuid
import hashlib
import types
import logging
import re
import threading

from enum import Enum
from typing import Any, Callable, Dict, List, Tuple, AsyncIterator, Awaitable, Optional, TYPE_CHECKING

from .cql_validation import (  # noqa: F401
    _enrich_cql_error,  # liegt seit 2026-09-01 dort, wird hier gebraucht
    validate as _validate_cqlf,
)
from . import budgets as _budgets
from . import empty_output
from .model_failure import ModellstoerungMixin
from .session_manager import SessionManager
from .interpretation_synthesis import DEUTUNG_LIEFERARTEN, deutungspfad_aktiv, fuehre_deutungs_synthese_aus

from .session_compaction import modellzeit_buchen, turn_usage_snapshot, usage_felder, zwischenstand as _zwischenstand, verdikt_bilanz, runde_lesbar as _runde_lesbar
from .policy_engine import PolicyEngine
from .observability import Observability
from .analysis_grounding import (
    ANALYSIS_CONTRACT_DOC,
    ANSWER_ENVELOPE_DOC,
    CONTRACT_VERIFIER_DOC,
    DEFAULT_GROUNDING_ROW_LIMIT,
    GROUNDING_TRIGGER_TOOLS,
    GROUNDING_VERIFIER_DOC,
    _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN,
    KWIC_RELATION_ADJUDICATOR_DOC,
    OBSERVED_FACTS_DOC,
    OPEN_RESEARCH_INCOMPATIBLE_EVIDENCE_KINDS,
    RESPONSE_REQUIREMENTS_DOC,
    AnalysisContract,
    AnswerEnvelope,
    ContractReview,
    EvidenceItem,
    GroundingVerdict,
    accepted_claims_match_deliverable,
    accepted_keyness_interpretation_is_substantive,
    accepted_ngram_interpretation_is_substantive,
    accepted_kwic_interpretation_is_substantive,
    accepted_semantic_pattern_interpretation_is_substantive,
    accepted_word_sketch_interpretation_is_substantive,
    accepted_followups_have_research_breadth,
    accepted_method_advice_addresses_quality_signals,
    analysis_contract_schema,
    answer_envelope_schema,
    blocked_claim_notes,
    build_claim_preserving_grounded_markdown,
    build_evidence_bundle,
    build_grounding_surface,
    build_grounded_markdown,
    build_verified_claim_markdown,
    deterministic_observed_facts,
    effective_analysis_contract,
    evidence_kinds_for_fact,
    evidence_kinds_for_item,
    evidence_manifest,
    exact_zero_lexical_search,
    envelope_matches_deliverable_kind,
    fallback_analysis_contract,
    extract_raw_surface,
    frequency_parameters_supply_content_rows,
    grounded_fact_notes,
    make_evidence_item,
    missing_word_sketch_profile_facts,
    werkzeugausgabe_ohne_betreiberpfad,
    word_sketch_metric_units_are_clear,
    normalise_response_requirements,
    normalise_observed_facts,
    observed_facts_schema,
    parse_structured_payload,
    contract_review_schema,
    heuristic_analysis_contract,
    required_evidence_fact_gaps,
    response_requirements_complete,
    response_requirements_schema,
    select_synthesis_window,
    same_corpus_collocation_method_requirements,
    same_corpus_collocation_terms,
    unique_observed_fact_id,
    validate_observed_facts,
    validate_answer_envelope,
    grounding_verdict_schema,
)
from .grounding_verifier import (
    GroundingVerifier,
    _fallback_hypothesis_from_clause_structure,
    _universal_hypothesis_clause,
)
# H10/G4: EIN Einstieg fuer alle Todespfad-Landungen (eigenes Modul,
# LOC-Budget-Dekomposition statt Anbau an grounding_markdown).
from .death_landings import death_landing_from_turn_state as _death_landing_from_turn_state
from .experiment_log import getragene_evidenz
from .version_distribution import mit_fassungsverteilung
from .sequence_scope import mit_folgenbereich
from .deterministic_landing import (
    SOFORTLANDUNG_GRUND, erlaubt_deterministische_landung,
    sofortlandungsentscheid)
from .recipe_runtime import (
    TOOL_ROUND_WRAPUP_LINE,
    VERIFIER_SKIPPED_NOTE, VERIFIER_UNBESTAETIGT_NOTE, VERIFIER_LAEUFT_NOTE,
    CONFIRMATION_KWIC_CONTEXT_MIN as _CONFIRMATION_KWIC_CONTEXT_MIN,
    CLARIFY_ZUSATZ_NOTE, PREPLAN_ABORT_RESULT, clarify_als_zusatz, strukturschritt_buchen,
    vorlaeufige_antwort_senden, bodentext_statt_absage, contract_evidence_note,
    final_polish_event, unanswered_tool_calls, preplan_with_contract,
    exact_cql_from_question as _exact_cql_from_question,
    question_sets_kwic_context as _question_sets_kwic_context,
    build_turn_system_prompt,
    capability_unavailable_reason,
    capability_unavailable_result,
    corpus_card_from_ui_context,
    drop_unresolved_sentences,
    embedding_unavailable_gate, free_mode_evidence_digest,
    word_similarity_unavailable_gate,
    tool_rounds_exhausted,
    precondition_unmet_answer,
    recipe_precondition_status,
    recipe_classifier_timeout_s,
    recipe_routing_annotation, route_turn_recipe,
    registry_tool_names, expand_tools_for_recipe,
    reference_hard_findings,
    resolve_reference_draft,
    session_briefing_state,
    strike_unbound_numbers,
    evidenz_belegzeilen,
    kontrollrahmen_bewacht,
    pending_required_evidence_tools,
    politur_mit_zitatwache,
    verifier_skipped_answer_text,
)
from .guard_emitter import WacheEmitterMixin
from candyconc.answer_language import choose as _t, enter_answer_language, is_english, resolve_answer_language
from candyconc.i18n import localize, lt
from .deutung_abgeben import merke_abgabe_text, schrittdecke_notiz, vermerke_abgabe
from . import prompts as _prompt_helpers
from candyconc.core import lineage
from candyconc.capabilities.product import visible_product_action_types, visible_product_copilot_tools
from candyconc.tooling.registry import get_tool_runtime_info
from candyconc.services.llm_client import LLMErrorKind, LLMRequestError

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from candyconc.project import Project

_ENGINE_RETRY_DELAYS = (2.0, 4.0, 8.0, 16.0, 24.0, 30.0, 30.0, 30.0)
#: Modellstoerungen je Turn, die der Turn uebersteht. Jede wartet auf
#: DASSELBE Modell (ohne Obergrenze innerhalb des Turn-Budgets) und
#: wiederholt denselben Aufruf; die gesammelte Evidenz bleibt. Runde 5,
#: 2026-09-13: das geteilte Transport-Budget (2) und 2 bis 4 Sekunden
#: Wartezeit liessen 41 Turns am Modellwechsel des Rechners sterben.
_ENGINE_STOERUNGEN_JE_TURN = 8
#: Als Literale, nicht ueber LLMErrorKind: die Testumgebung stubbt die Klasse
#: teils als SimpleNamespace, und ein Modulattribut darf den Import nicht
#: reissen (Nachher-Suite 2026-09-15: drei Sammelfehler).
_ENGINE_STOERUNG_KINDS = ("engine_unavailable", "stale_continuation")
def _ist_modellstoerung(error: Any) -> bool:
    kind = getattr(error, "kind", None)
    return kind in _ENGINE_STOERUNG_KINDS or (
        kind == "transport" and bool(getattr(error, "retryable", False)))

_STREAM_REPLAY_HINWEIS = lt("Der Modellstrom brach durch eine Modellstörung ab. Die "
                            "sichtbare Teilausgabe wird verworfen, die gesammelte "
                            "Evidenz bleibt, derselbe Aufruf wird wiederholt.",
                            "The model stream broke off because of a model failure. "
                            "The visible partial output is discarded, the collected "
                            "evidence is kept, the same call is repeated.")

_STREAM_ABBRUCH_HINWEIS = lt("Der LLM-Stream brach nach bereits sichtbarer "
                             "Ausgabe ab und wird nicht automatisch wiederholt.",
                             "The model stream broke off after visible output and "
                             "is not repeated automatically.")

_EVIDENCE_TO_TOOLS: Dict[str, Tuple[str, ...]] = {
    "kwic_rows": ("run_cqlf_query", "kwic_context"),
    "expanded_context": ("kwic_context",),
    "frequency_rows": ("frequency_list",),
    "lexical_frequency_rows": ("frequency_list",),
    "content_rows": (
        "frequency_list",
        "semantic_search",
        "semantic_cluster",
        "semantic_cluster_words",
        "document_search",
    ),
    "contextual_rows": (
        "run_cqlf_query",
        "kwic_context",
        "semantic_search",
        "semantic_cluster",
        "semantic_cluster_words",
        "document_search",
    ),
    "metric_rows": (
        "compare_collocates",
        "contrast_collocates",
        "keyness",
        "collocate_stats",
        "word_sketch",
        "ngram_frequency",
        "lexical_diversity",
        "trend_analysis",
    ),
    "dispersion_profile": ("dispersion_offsets",),
    "document_rows": ("document_search",),
    "documentation_rows": ("documentation_search",),
    "metadata_rows": ("metadata_values",),
    "semantic_rows": ("semantic_search",),
    "cluster_rows": ("semantic_cluster", "semantic_cluster_words"),
    "total_hits": (
        "query_count",
        "run_cqlf_query",
        "frequency_list",
        "dispersion_offsets",
    ),
}

_SEARCH_ANCHOR_TOOLS = frozenset(
    {"semantic_search", "document_search", "similar_words"}
)
_SEARCH_ANCHOR_STOPWORDS = frozenset(
    {
        "auch",
        "aber",
        "auf",
        "aus",
        "bei",
        "das",
        "der",
        "die",
        "dem",
        "den",
        "des",
        "durch",
        "ein",
        "eine",
        "er",
        "es",
        "für",
        "fuer",
        "hat",
        "ich",
        "im",
        "in",
        "ist",
        "mit",
        "nicht",
        "noch",
        "nur",
        "oder",
        "sich",
        "sie",
        "sind",
        "so",
        "über",
        "ueber",
        "um",
        "und",
        "von",
        "vom",
        "was",
        "war",
        "welche",
        "werden",
        "wird",
        "wir",
        "wie",
        "zu",
        "zum",
        "zur",
    }
)

# H10/G1 (LOC-Naht): _exact_cql_from_question und _question_sets_kwic_context
# leben jetzt wortgleich in recipe_runtime (Alias-Import oben).

def _search_anchor_tokens(text: Any) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[0-9a-zäöüß]{3,}",
            str(text or "").casefold(),
        )
        if token not in _SEARCH_ANCHOR_STOPWORDS
    }

def _tool_search_anchor(tool_call: Dict[str, Any]) -> str:
    raw_args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except (TypeError, ValueError, json.JSONDecodeError):
            args = {}
    else:
        args = raw_args
    if not isinstance(args, dict):
        return ""
    for key in ("term", "query", "word", "lemma"):
        value = str(args.get(key) or "").strip()
        if value:
            return value
    return ""


_LITERAL_CQL_SEARCH_ANCHOR = re.compile(
    r'^\[\s*(?:word|lemma)\s*=\s*"([^"\\]{1,80})"\s*\]$',
    re.IGNORECASE,
)
_PLAIN_SEARCH_ANCHOR = re.compile(
    r"^[0-9A-Za-zÄÖÜäöüß]+(?:[ '\u2011\u2013\u2014-][0-9A-Za-zÄÖÜäöüß]+){0,5}$"
)


def _literal_lexical_search_anchor(value: Any) -> str:
    """Recover a literal topic anchor from a simple word or lemma query."""

    query = " ".join(str(value or "").strip().split())
    if query.casefold().startswith("cql:"):
        query = query[4:].strip()
    match = _LITERAL_CQL_SEARCH_ANCHOR.fullmatch(query)
    candidate = match.group(1).strip() if match else query
    if not _PLAIN_SEARCH_ANCHOR.fullmatch(candidate):
        return ""
    return candidate


def _confirmation_retrieval_anchor(
    candidate_calls: List[Dict[str, Any]],
    evidence_items: List[Dict[str, Any]],
    semantic_term: str,
    *,
    target_topic: str = "",
    asserted_property: str = "",
) -> str:
    """Prefer a prior literal topic query over conclusion-loaded retrieval."""

    anchors: List[str] = []
    for tool_call in candidate_calls:
        if str(tool_call.get("function", {}).get("name", "")) != "run_cqlf_query":
            continue
        anchor = _literal_lexical_search_anchor(
            _tool_search_anchor(tool_call)
        )
        if anchor:
            anchors.append(anchor)
    for raw_item in evidence_items:
        if not isinstance(raw_item, dict) or raw_item.get("tool") != "run_cqlf_query":
            continue
        raw_surface = raw_item.get("raw_surface")
        query = (
            raw_surface.get("query")
            if isinstance(raw_surface, dict)
            else ""
        )
        anchor = _literal_lexical_search_anchor(query)
        if anchor:
            anchors.append(anchor)

    term_tokens = _search_anchor_tokens(semantic_term)
    topic_tokens = _search_anchor_tokens(target_topic)
    property_tokens = _search_anchor_tokens(asserted_property)
    term_uses_property = bool(term_tokens & property_tokens)
    for anchor in sorted(
        dict.fromkeys(anchors),
        key=lambda value: (-len(_search_anchor_tokens(value)), -len(value)),
    ):
        anchor_tokens = _search_anchor_tokens(anchor)
        anchor_tracks_topic = bool(
            anchor_tokens
            and topic_tokens
            and anchor_tokens <= topic_tokens
        )
        if (
            anchor_tokens
            and anchor.casefold() != semantic_term.casefold()
            and (
                anchor_tokens < term_tokens
                or (anchor_tracks_topic and term_uses_property)
            )
        ):
            return anchor
    return ""


def _grounded_search_anchor_candidates(
    question: str,
    evidence_items: List[Dict[str, Any]],
    *,
    limit: int = 6,
) -> List[str]:
    """Return concrete search terms the current evidence actually licenses."""
    frequency_items: List[EvidenceItem] = []
    for raw_item in evidence_items:
        if not isinstance(raw_item, dict):
            continue
        try:
            item = EvidenceItem(**dict(raw_item))
        except (TypeError, ValueError):
            continue
        if item.tool == "frequency_list":
            frequency_items.append(item)

    content_frequency_items = [
        item
        for item in frequency_items
        if "content_rows" in evidence_kinds_for_item(item)
    ]
    candidates: List[str] = []
    seen: set[str] = set()

    def _append(value: Any) -> None:
        candidate = " ".join(str(value or "").strip().split())
        folded = candidate.casefold()
        if (
            not candidate
            or candidate.startswith("@")
            or len(candidate) > 80
            or not _search_anchor_tokens(candidate)
            or folded in seen
        ):
            return
        seen.add(folded)
        candidates.append(candidate)

    for item in content_frequency_items or frequency_items:
        group_by = str(item.raw_surface.get("group_by") or "").strip().casefold()
        if group_by == "pos":
            continue
        rows = item.raw_surface.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                _append(row.get("word") or row.get("kw"))
                if len(candidates) >= limit:
                    return candidates

    # Terms copied from the question are also permitted by the guard. They are
    # only a fallback: visible corpus lexemes are more useful for an open prompt.
    for token in re.findall(r"[0-9A-Za-zÄÖÜäöüß]{3,}", str(question or "")):
        if token.casefold() not in _SEARCH_ANCHOR_STOPWORDS:
            _append(token)
        if len(candidates) >= limit:
            break
    return candidates


def _grounded_search_anchor_guidance(
    question: str,
    evidence_items: List[Dict[str, Any]],
) -> str:
    candidates = _grounded_search_anchor_candidates(question, evidence_items)
    if not candidates:
        return ""
    rendered = ", ".join(f"`{candidate}`" for candidate in candidates)
    return (
        " Aktuell zulässige, sichtbare Suchanker sind: "
        f"{rendered}. Wähle fachlich begründet einen davon; die Liste ist "
        "keine vorgegebene Interpretation."
    )


def _same_corpus_collocation_method(
    question: str,
    tool_spec: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Resolve one reproducible method for a lexical-form comparison.

    Defaults and allowed measures come from the actually exposed tool schema;
    explicitly requested values are then applied to that executable contract.
    """

    parameters = dict(
        (tool_spec or {}).get("function", {}).get("parameters", {}) or {}
    )
    properties = dict(parameters.get("properties", {}) or {})

    def _default(key: str, fallback: Any) -> Any:
        schema = properties.get(key)
        return schema.get("default", fallback) if isinstance(schema, dict) else fallback

    method: Dict[str, Any] = {
        "attribute": str(_default("attribute", "word") or "word").casefold(),
        "window": int(_default("window", 5)),
        "within_sentence": bool(_default("within_sentence", True)),
        "min_freq": int(_default("min_freq", 5)),
        "sort_by": str(_default("sort_by", "logdice") or "logdice").casefold(),
    }
    explicit = same_corpus_collocation_method_requirements(question)
    sort_schema = properties.get("sort_by")
    allowed_measures = {
        str(value).casefold()
        for value in (
            sort_schema.get("enum", []) if isinstance(sort_schema, dict) else []
        )
    }
    if "sort_by" in explicit and allowed_measures and explicit["sort_by"] not in allowed_measures:
        explicit.pop("sort_by")
    method.update(explicit)
    for key in ("window", "min_freq"):
        schema = properties.get(key)
        minimum = schema.get("minimum") if isinstance(schema, dict) else None
        if minimum is not None:
            method[key] = max(int(minimum), int(method[key]))
    return method


def _explicit_same_corpus_id(question: str) -> str:
    """Read only a corpus identifier explicitly attached to a corpus label."""

    match = re.search(
        r"\b(?:korpus|corpus)\s*(?:=|:)?\s*[\"'`„“‚‘]"
        r"([^\"'`„“‚‘]{1,120})[\"'`„“‚‘]",
        str(question or ""),
        re.IGNORECASE,
    )
    if match is not None and re.search(
        r"\b(?:selben|gleichen|gesamt)\s*$",
        str(question or "")[: match.start()],
        re.IGNORECASE,
    ):
        match = None
    if match is None:
        match = re.search(
            r"\b(?:korpus|corpus)\s*(?:=|:)\s*"
            r"([0-9A-Za-zÄÖÜäöüß_.-]{1,120})\b",
            str(question or ""),
            re.IGNORECASE,
        )
    return " ".join(match.group(1).split()) if match is not None else ""


def _lexical_count_node(value: Any) -> Tuple[str, str]:
    """Return ``(attribute, node)`` for a plain or one-token CQLF query."""

    node = " ".join(str(value or "").strip().split())
    match = re.fullmatch(
        r'(?:cql:)?\[\s*(word|lemma)\s*=\s*"([^"\\]+)"'
        r'(?:\s+%(?:c|d))?\s*\]',
        node,
        re.IGNORECASE,
    )
    if match is not None:
        return match.group(1).casefold(), " ".join(match.group(2).split())
    return ("word", node) if node and not re.search(r"\s", node) else ("", "")


def _collocation_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    folded = str(value or "").strip().casefold()
    if folded in {"1", "true", "yes", "ja"}:
        return True
    if folded in {"0", "false", "no", "nein"}:
        return False
    return None


def _plain_lexical_node(value: Any) -> str:
    """Read a plain node or a one-token word/lemma CQL expression."""

    return _lexical_count_node(value)[1]


def _search_anchor_is_grounded(
    anchor: str,
    *,
    question: str,
    evidence_items: List[Dict[str, Any]],
) -> bool:
    compact_anchor = " ".join(str(anchor or "").casefold().split())
    compact_question = " ".join(str(question or "").casefold().split())
    if compact_anchor and compact_anchor in compact_question:
        return True
    anchor_tokens = _search_anchor_tokens(anchor)
    if not anchor_tokens:
        return False
    grounded_tokens = _search_anchor_tokens(question)
    frequency_items: List[EvidenceItem] = []
    for raw_item in evidence_items:
        if not isinstance(raw_item, dict):
            continue
        item = EvidenceItem(**dict(raw_item))
        if item.tool != "frequency_list":
            continue
        frequency_items.append(item)
    content_frequency_items = [
        item
        for item in frequency_items
        if "content_rows" in evidence_kinds_for_item(item)
    ]
    for item in content_frequency_items or frequency_items:
        group_by = str(
            item.raw_surface.get("group_by") or ""
        ).strip().casefold()
        if group_by == "pos":
            continue
        rows = item.raw_surface.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                grounded_tokens.update(
                    _search_anchor_tokens(
                        row.get("word") or row.get("kw")
                    )
                )
    return bool(anchor_tokens & grounded_tokens)


get_system_prompt = getattr(_prompt_helpers, "get_system_prompt", lambda: "")
get_system_prompt_with_context = getattr(
    _prompt_helpers,
    "get_system_prompt_with_context",
    lambda _context=None: get_system_prompt(),
)
compact_runtime_system_prompt = getattr(
    _prompt_helpers,
    "compact_runtime_system_prompt",
    lambda prompt: prompt,
)
parse_control_frame = getattr(_prompt_helpers, "parse_control_frame", lambda _content: None)
extract_all_control_frames = getattr(_prompt_helpers, "extract_all_control_frames", lambda _content: [])
remove_control_frames = getattr(_prompt_helpers, "remove_control_frames", lambda content: content)

logger = logging.getLogger(__name__)

_PSEUDO_TOOL_CALL_RE = re.compile(r"<function_calls?\b|<invoke\s+name\s*=", re.IGNORECASE)
_PSEUDO_TOOL_NAME_RE = re.compile(r"<invoke\s+name\s*=\s*[\"']?([^\"'>\s/]+)", re.IGNORECASE)
_MODEL_TOOL_OUTPUT_CHAR_LIMIT = 12_000

def _guard_nachricht_fuer_modell(guard_message: str) -> Dict[str, str]:
    """Der Wächter/Gegenanker geht als Nutzer-Rolle mit [System note:]-
    Wrapper raus: Mistral-Vorlagen (z. B. mistral-small-4-119b) lehnen eine
    zweite System-Rolle ab (Jinja "got system", Live-Befund 2026-09-06).
    Das etablierte Muster fuer Modell-Hinweise in dieser Codebase."""
    if not guard_message:
        return {}
    return {"role": "user", "content": "[System note: " + guard_message + "]"}


def _tool_output_for_model(
    output: Any,
    *,
    char_limit: int = _MODEL_TOOL_OUTPUT_CHAR_LIMIT, werkzeug: str | None = None,
) -> Any:
    """Bound only the model-facing copy; full output remains product evidence."""

    if is_english():
        # A LocalizedText serialises as its German value. For an English
        # question the model reads the English value, as the interface does
        # (English probe, run a1, round 2: "Reihe ausgedünnt auf 60 von 61
        # Perioden" for the model, "Series thinned to 60 of 61 periods" in the
        # interface). German turns keep every byte.
        output = localize(output, "en")
    rendered = json.dumps(output, ensure_ascii=False)
    oversized_collection = False
    if isinstance(output, dict):
        rows = output.get("rows")
        clusters = output.get("clusters")
        tables = output.get("tables")
        oversized_collection = (
            (
                isinstance(rows, list)
                and len(rows) > DEFAULT_GROUNDING_ROW_LIMIT
            )
            or (isinstance(clusters, list) and len(clusters) > 4)
            or (
                isinstance(tables, dict)
                and any(
                    isinstance(entries, list) and len(entries) > 6
                    for entries in tables.values()
                )
            )
        )
    if len(rendered) <= char_limit and not oversized_collection:
        return output

    from .view_row_selection import perioden_mit_pfad

    # A thinned period series names each shown period's path (view_row_selection).
    raw_surface = perioden_mit_pfad(extract_raw_surface(output, werkzeug=werkzeug), output)
    compacted: Dict[str, Any] = {
        "status": output.get("status", "success") if isinstance(output, dict) else "success",
        "model_view_compacted": True,
        "original_size_chars": len(rendered),
        "scope_note": (
            "Begrenzte Evidenzsicht für den nächsten LLM-Schritt; nur die hier "
            "sichtbaren Werte zitieren. Das vollständige Tool-Ergebnis bleibt "
            "intern für Grounding und Produktoberfläche erhalten."
        ),
        "evidence": raw_surface,
    }
    # Scale the limit with the requested rows in groups of twenty.
    zeilen = len(raw_surface.get("rows") or []) if isinstance(raw_surface, dict) else 0
    char_limit = max(char_limit, char_limit * -(-zeilen // DEFAULT_GROUNDING_ROW_LIMIT))
    if len(json.dumps(compacted, ensure_ascii=False)) <= char_limit:
        return compacted

    bounded_lines: List[str] = []
    base = {key: value for key, value in compacted.items() if key != "evidence"}
    alle_zeilen = build_grounding_surface(raw_surface)
    for line in alle_zeilen:
        candidate = {**base, "evidence_lines": [*bounded_lines, line]}
        if len(json.dumps(candidate, ensure_ascii=False)) > char_limit:
            break
        bounded_lines.append(line)
    sicht = {**base, "evidence_lines": bounded_lines}
    # Die Sicht sagt, was ihr fehlt. Vorher brach sie still ab, und die
    # Zeile grounding_rows_visible=200 stand ueber 141 gezeigten Treffern
    # (Methodenbefund C7 der Session CandyConc Paper, 2026-09-26). Wer aus
    # einer Stichprobe Anteile zaehlt, zaehlte dann gegen den falschen Nenner.
    fehlend = len(alle_zeilen) - len(bounded_lines)
    if fehlend > 0:
        sicht["evidence_lines_omitted"] = fehlend
        sicht["scope_note"] = base["scope_note"] + (
            f" Diese Sicht zeigt {len(bounded_lines)} von {len(alle_zeilen)} "
            f"Belegzeilen, {fehlend} passen nicht in die Zeichengrenze. "
            "grounding_rows_visible zählt die Belegfläche, nicht diese Sicht."
        )
    return sicht


def _SALVAGE_NOTE() -> str:
    """Note under a salvaged answer, in the answer language of the turn."""
    return _t(
        "\n\nHinweis: Der Turn wurde vor der vollstaendigen "
        "Verifikation beendet. Berichtet werden ausschliesslich "
        "deterministisch belegte Tool-Fakten.",
        "\n\nNote: The turn ended before complete verification. Only "
        "deterministically supported tool facts are reported.",
    )


class CopilotTurnCancelled(RuntimeError):
    """Raised at a cooperative boundary after a user stopped a Copilot turn."""


class _VerifierTimeBudgetExceeded(RuntimeError):
    """Fix 3: der LLM-Verifier reisst das Restzeit-Budget.

    ``_ra_run_structured_step`` wirft dies VOR jedem Verifier-Struktur-Schritt,
    sobald ``verifier_time_remaining_ok`` in der Verifikationsphase kippt; der
    Finalisierungspfad finalisiert dann deterministisch
    (verifier_skipped_time_budget) statt mitten im Protokoll ins Zeitlimit zu
    laufen.
    """


def _pseudo_tool_calls_from_content(content: str) -> List[Dict[str, Any]]:
    if not isinstance(content, str) or not _PSEUDO_TOOL_CALL_RE.search(content):
        return []
    names: List[str] = []
    for match in _PSEUDO_TOOL_NAME_RE.finditer(content):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    if not names:
        names = [""]
    return [
        {
            "id": f"pseudo_tool_call_{idx}",
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }
        for idx, name in enumerate(names, start=1)
    ]


class State(Enum):
    WAITING_LLM = "waiting_llm"
    EXECUTING_TOOL = "executing_tool"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CLARIFICATION = "waiting_clarification"
    FINISHED = "finished"


class ControlFrameType(Enum):
    PLAN = "plan"
    CLARIFY = "clarify"
    ACTION = "action"
    RESEARCH_CONTEXT = "research_context"


class _RunTurnState:
    """Per-turn mutable recovery/grounding state for ``run_async``.

    One instance is created per ``run_async`` invocation and threaded as an
    explicit parameter into the lifted ``_ra_*`` helpers, replacing the
    ``nonlocal`` writer closures of the former god-method (Phase 2 of the
    decomposition).

    Deliberately a plain class (not a ``@dataclass``): several legacy tests
    exec this module via ``spec_from_file_location`` under module names whose
    ``sys.modules`` entries are stubs, which breaks the dataclass decorator's
    ``sys.modules[cls.__module__]`` lookup at import time.

    Field ownership:

    - ``fail_closed_grounding_kind`` / ``fail_closed_grounding_reason``:
      written by ``_ra_activate_fail_closed_grounding``; the *reason* is read
      by ``run_async`` after the contract preflight to short-circuit into the
      fail-closed markdown answer (the *kind* is retained for diagnostics).
    - ``context_recovery_count`` / ``microcompact_count``: read and written
      only by ``_ra_recover_llm_error`` (context-window recovery budget).
    - ``output_resume_count``: shared budget between the MAX_OUTPUT_TOKENS
      recovery and the length-resume path in the main loop.
    - ``empty_stop_retries``: leerer Modell-Output (stop/length/leere
      tool_calls-Liste), genau ein Retry je Vorfall — siehe empty_output.py.
    - ``engine_retry_count``: consecutive same-model engine interruptions;
      reset after the next successful LLM response.
    - ``active_allowed_tools`` / ``forced_next_tools`` (Phase 3): the per-turn
      tool-exposure state. ``active_allowed_tools`` is written once after the
      contract preflight; ``forced_next_tools`` is the mutable loop state the
      main ReAct loop reassigns (formerly a ``nonlocal`` of ``_run``). Read by
      ``_ra_active_tool_specs`` (forced wins over allowed) and the tool-call
      filter/anomaly paths.
    - ``question`` / ``normalized_question`` / ``role`` / ``principal`` / ``stream`` /
      ``system_prompt`` / ``accepts_stream`` / ``accepts_json_schema`` /
      ``accepts_tool_choice`` / ``llm_is_async`` (Phase 3): immutable per-turn invocation config,
      assigned once by ``run_async`` right after construction so the lifted
      LLM web (``_ra_invoke_llm`` and friends) does not need a wide
      parameter list.
    """

    __slots__ = (
        "fail_closed_grounding_kind",
        "fail_closed_grounding_reason",
        "context_recovery_count",
        "microcompact_count",
        "output_resume_count",
        "engine_retry_count",
        "active_allowed_tools",
        "forced_next_tools",
        "question",
        "normalized_question",
        "role",
        "principal",
        "stream",
        "system_prompt",
        "accepts_stream",
        "accepts_json_schema",
        "accepts_tool_choice",
        "llm_is_async",
        "llm_calls_used",
        "llm_seconds",
        "llm_seconds_je_stufe",
        "llm_calls_je_stufe",
        "retries_used",
        "started_at",
        "max_time",
        "recipe_id",
        "tool_rounds",
        "reference_repair_used",
        "wrapup_emitted",
        "in_verifier_phase",
        "empty_stop_retries",
        "schrittdecke_erreicht",
    )

    def __init__(self) -> None:
        self.fail_closed_grounding_kind: str = ""
        self.fail_closed_grounding_reason: str = ""
        self.context_recovery_count: int = 0
        self.microcompact_count: int = 0
        self.output_resume_count: int = 0
        self.engine_retry_count: int = 0
        self.active_allowed_tools: List[str] | None = None
        self.forced_next_tools: List[str] | None = None
        self.question: str = ""
        self.normalized_question: str = ""
        self.role: str = "user"
        self.principal: str = "user"
        self.stream: bool = False
        self.system_prompt: str = ""
        self.accepts_stream: bool = False
        self.accepts_json_schema: bool = False
        self.accepts_tool_choice: bool = False
        self.llm_is_async: bool = False
        # Usage is observable, but never used as an analytical stop condition.
        self.llm_calls_used: int = 0
        #: Summe der Wanduhrzeit IN LLM-Aufrufen dieses Turns. Der Rest der
        #: Werkzeugschleife ist damit Indexzeit, und beides ist zum ersten
        #: Mal getrennt lesbar.
        self.llm_seconds: float = 0.0
        #: A2: dieselbe Zeit, aufgeteilt nach der Stufe, die beim Aufruf
        #: gemeldet war. Erst damit ist der Topf "Werkzeuge" trennbar:
        #: Indexzeit ist phasen_s["Werkzeuge"] minus dieser Anteil. Ohne
        #: die Aufteilung stimmt die Rechnung nur bei einphasigen Turns.
        self.llm_seconds_je_stufe: dict[str, float] = {}
        self.retries_used: int = 0
        self.started_at: float = 0.0
        self.max_time: float | None = None
        # R2 Rezept-Harness: deterministisch gewaehltes Rezept dieses Turns
        # (leer = freier Modus), Zahl der abgeschlossenen Tool-Runden (der
        # Drift-Anker haengt nur an Fortsetzungsrunden) und das Ein-Aufruf-
        # Budget des gezielten Referenz-Repairs.
        self.recipe_id: str = ""
        self.tool_rounds: int = 0
        self.reference_repair_used: bool = False
        # Runden-Leitplanke: das copilot.recovery-Event zur weichen Landung
        # wird je Turn genau einmal emittiert.
        self.wrapup_emitted: bool = False
        # Fix 3: True nur waehrend der LLM-Verifikation (Zeit-Guard je Schritt).
        self.in_verifier_phase: bool = False
        self.empty_stop_retries: int = 0
        # After the step limit ends tool use, request a draft without tools,
        # following the same path as a voluntary handoff.
        self.schrittdecke_erreicht: bool = False


class ReActOrchestrator(ModellstoerungMixin, WacheEmitterMixin):
    """Orchestrator running a ReAct loop with control frame support.

    Supports structured communication via control frames:
    - PLAN: Multi-step analysis plans
    - CLARIFY: Questions requiring user input
    - ACTION: Action proposals requiring approval

    The orchestrator emits SSE events for each control frame type.
    """

    _CHAT_MESSAGE_ROLES = frozenset({"user", "assistant", "system", "tool"})

    def __init__(
        self,
        tools: List[Dict[str, Any]],
        call_llm: Callable[
            [List[Dict[str, str]], List[Dict[str, Any]]], Dict[str, Any]
        ],
        dispatch: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        session: SessionManager | None = None,
        policy: PolicyEngine | None = None,
        observability: Observability | None = None,
        project: Project | None = None,
        *,
        llm_retries: int = 0,
        tool_retries: int = 0,
        token: str | None = None,
        ui_context: Dict[str, Any] | None = None,
    ) -> None:
        self.tools = tools
        self.call_llm = call_llm
        self.dispatch = dispatch
        self.session = session or SessionManager()
        self.policy = policy or PolicyEngine()
        self.observability = observability
        self.project = project
        if self.policy and project and not getattr(self.policy, "project", None):
            self.policy.project = project
        self.state = State.WAITING_LLM
        self.llm_retries = llm_retries
        self.tool_retries = tool_retries
        self.token = token
        self.ui_context = ui_context or {}
        # Language of the answer (candyconc/answer_language.py), per user turn.
        # ``interface_language`` is the request language, set by the chat route.
        self._answer_language: str = "de"
        self.interface_language: str | None = None
        try:
            self._tool_runtime_info = get_tool_runtime_info()
        except Exception:
            self._tool_runtime_info = {}

        # Control frame state
        self._pending_action: Optional[Dict[str, Any]] = None
        self._pending_clarification: Optional[Dict[str, Any]] = None
        self._current_plan: Optional[Dict[str, Any]] = None
        # Low-autonomy plan gate (id 16): at autonomy levels 0/1 the orchestrator
        # pauses for explicit approval BEFORE the first tool batch — even for
        # read-only tools — so the autonomy control is observable. Per-turn flag;
        # reset on each fresh user turn in ``_reset_runtime_guards``.
        self._plan_gate_satisfied: bool = False
        self._failed_tool_attempts: Dict[str, Dict[str, Any]] = {}
        self._successful_read_only_tool_results: Dict[str, Any] = {}
        self._recent_tool_results: List[Dict[str, Any]] = []
        self._recent_recoveries: List[str] = []
        self._recent_research_findings: List[Dict[str, Any]] = []
        self._last_llm_route: str = ""
        self._last_llm_model: str = ""
        self._research_runs: List[Dict[str, Any]] = []
        self._active_research_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._research_prompt_window_sec: int = 10 * 60
        self._active_research_context_tags: List[str] = []
        self._current_turn_research_context_tags: List[str] = []
        self._active_analysis_contract: Dict[str, Any] = {}
        # K1: Klassifikator-Cache pro Session und Frage-Familie plus die
        # Budget-Bilanz des letzten Turns (fuer copilot.done).
        self._contract_classifier_cache: Dict[str, Dict[str, Any]] = {}
        self._last_turn_usage: Dict[str, Any] = {}
        self._turn_evidence_items: List[Dict[str, Any]] = []
        # R2 Rezept-Harness: aktives Rezept der Session (persistiert ueber
        # Fortsetzungslaeufe desselben Turns) und die Runden-Puffer fuer die
        # deterministische Evidenz-Reihenfolge gebuendelter Tool-Calls.
        self._active_recipe_id: str = ""
        # A2: Stufe vor dem ersten Statusframe. Der Anlauf ist eine
        # eigene Groesse und wird nicht der Werkzeugschleife zugeschlagen.
        self._aktuelle_stufe: str = "Vorlauf"
        self._active_recipe_family: str = ""
        # H9/C1: Routing-Stufe (trigger|llm|frei) fuer copilot.grounding.
        self._turn_recipe_routing: Dict[str, Any] = {}
        self._round_evidence_plan: Dict[int, Tuple[str, str]] = {}
        self._round_evidence_items: Dict[int, Dict[str, Any]] = {}
        # Capability-Fehlerklasse (recipe_runtime): Name -> Grund. Nach dem
        # ersten unavailable-Item ohne ``ausweg`` nicht mehr exponiert.
        self._turn_capability_unavailable_tools: Dict[str, str] = {}
        self._grounded_fact_notes: List[str] = []
        self._evidence_gaps: List[str] = []
        self._blocked_claims: List[str] = []
        self._last_grounding_verdict: Dict[str, Any] = {}
        self._tool_call_anomalies: List[Dict[str, Any]] = []
        # Identity of the principal driving this session. It is kept separately
        # from the ChatML turn role so internal ``role="system"`` continuations
        # retain the initiating user's policy/ACL identity.
        self._active_principal: str = "user"
        # The server can signal cancellation from a different request thread.
        # It cannot interrupt a blocking LLM HTTP call, but every subsequent
        # LLM retry, tool dispatch and continuation must become a no-op.
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Make this session terminal without fabricating a follow-up answer."""
        self._cancel_requested.set()
        self._pending_action = None
        self._pending_clarification = None
        self.state = State.FINISHED

    def turn_usage_report(self) -> Dict[str, Any]:
        """Return observational usage data for the ``copilot.done`` event."""
        return dict(self._last_turn_usage or {})

    def build_death_landing_markdown(self, *, reason: str = "") -> str | None:
        """H10/G4: rezept-/deliverable-bewusste Landung fuer Todespfade.

        ``None``, wenn kein rezeptbewusster Builder greift (der Aufrufer
        faellt dann auf seinen generischen Digest zurueck). Braucht keinen
        Kontrakt, nur Turn-Evidenz plus aktives Rezept.
        """
        return _death_landing_from_turn_state(
            list(self._turn_evidence_items or []),
            recipe_id=self._active_recipe_id,
            contract=self._active_analysis_contract,
            evidence_gaps=self._evidence_gaps,
            reason=reason,
        )

    def build_salvage_markdown(self) -> str | None:
        """Deterministische Fallback-Antwort aus bereits gesammelter Evidenz.

        Wird vom Server-Backstop genutzt, wenn der Turn hart abgebrochen
        wurde (Timeout, Zombie-Kette). Baut ausschliesslich aus den
        deterministischen Observed Facts der Turn-Evidenz eine formatierte
        Markdown-Antwort. Kein LLM-Call, kein Roh-JSON. ``None``, wenn kein
        Kontrakt oder keine Evidenz vorliegt. H10/G4: die rezeptbewusste
        Todespfad-Landung hat Vorrang vor dem Kontrakt-Dispatch.
        """
        landing = self.build_death_landing_markdown()
        if landing:
            return landing.rstrip() + _SALVAGE_NOTE()
        contract_raw = dict(self._active_analysis_contract or {})
        if not contract_raw or contract_raw.get("mode") != "tool_analysis":
            return None
        evidence_items = [
            EvidenceItem(**dict(item))
            for item in list(self._turn_evidence_items or [])
            if isinstance(item, dict)
        ]
        if not evidence_items:
            return None
        try:
            contract = AnalysisContract.from_raw(
                contract_raw,
                question_text=str(contract_raw.get("question_scope", "") or ""),
                available_tools=self._available_tool_names(),
                read_only_tools=self._read_only_tool_names(),
            )
            grounding_contract = effective_analysis_contract(
                contract, evidence_items
            )
            observed_facts = deterministic_observed_facts(
                grounding_contract, evidence_items
            )
            markdown = build_grounded_markdown(
                grounding_contract,
                observed_facts,
                evidence_items,
                evidence_gaps=self._evidence_gaps,
                accepted_claim_ids=[],
            )
        except Exception:
            logger.exception("build_salvage_markdown failed")
            return None
        if not (isinstance(markdown, str) and markdown.strip()):
            return None
        return markdown.rstrip() + _SALVAGE_NOTE()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested.is_set()

    def _raise_if_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            self.state = State.FINISHED
            raise CopilotTurnCancelled("Copilot turn cancelled by user")

    async def _ra_wait_with_cancellation(self, delay: float) -> None:
        """Wait for recovery while honoring an out-of-band turn cancel."""

        deadline = asyncio.get_running_loop().time() + max(0.0, delay)
        while True:
            self._raise_if_cancelled()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            await asyncio.sleep(min(0.25, remaining))

    def _ra_vergiss_fortsetzung(self) -> None:
        """Nach einem Neuladen kennt der Endpunkt keine previous_response_id
        mehr; die Wiederholung baut die Anfrage aus der flachen Historie."""
        for message in list(getattr(self.session, "history", None) or []):
            if isinstance(message, dict):
                message.pop("_cc_response_id", None)

    async def _ra_await_with_cancellation(self, awaitable: Awaitable[Any]) -> Any:
        """Await an unbounded async LLM call while polling the turn cancel."""

        task = asyncio.ensure_future(awaitable)
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.25)
                self._raise_if_cancelled()
            return task.result()
        except BaseException:
            if not task.done():
                task.cancel()
            try:
                await task
            except BaseException:
                pass
            raise

    def _resolve_turn_identity(
        self,
        role: str,
        principal: str | None,
    ) -> Tuple[str, str]:
        """Return a ChatML turn role and an independent policy principal.

        Before ``principal`` existed, production and evaluation callers passed
        the username as the second positional ``role`` argument. Preserve that
        API deliberately for non-ChatML values: ``run(question, "anon")`` is a
        user turn owned by principal ``anon``. New call sites must pass
        ``role="user", principal="anon"`` explicitly so grounding cannot be
        skipped merely because the authenticated username is not ``"user"``.
        """

        turn_role = str(role or "user").strip() or "user"
        effective_principal = str(principal or "").strip()
        if turn_role not in self._CHAT_MESSAGE_ROLES:
            if not effective_principal:
                effective_principal = turn_role
            turn_role = "user"
        if not effective_principal:
            effective_principal = turn_role
        if turn_role == "user":
            self._active_principal = effective_principal
        return turn_role, effective_principal

    def _emit_session_id(self) -> Optional[str]:
        """Session id used to route copilot SSE events to the owning session.

        Per-session routing keeps one user's streamed tokens and tool results
        out of another user's stream. Returns ``None`` when no session id is
        available (the bus then falls back to session-agnostic delivery).
        """
        session_id = getattr(self.session, "session_id", None)
        return str(session_id) if session_id else None

    def _emit_output(self, copilot_event_bus: Any, event: Dict[str, Any]) -> None:
        """Emit ``event`` to the SSE bus, scoped to this orchestrator's session."""
        session_id = self._emit_session_id()
        if not session_id:
            # Non-streaming programmatic callers have no SSE recipient.
            return
        copilot_event_bus.publish(event, session_id=session_id)

    def _get_autonomy_level(self) -> int:
        """Get the current autonomy level from UI context."""
        return self.ui_context.get("autonomy_level", 5)

    def _should_require_approval(self, action_data: Dict[str, Any]) -> bool:
        """Determine if an action requires user approval based on autonomy level."""
        autonomy = self._get_autonomy_level()

        # Explicit requiresApproval in action data
        if action_data.get("requiresApproval") is True:
            return autonomy < 9  # Only skip approval at max autonomy

        # Low autonomy (0-2): Always require approval
        if autonomy <= 2:
            return True

        # Medium autonomy (3-5): Require approval for non-reversible actions
        if autonomy <= 5:
            return not action_data.get("reversible", True)

        # High autonomy (6-8): Only require approval for destructive actions
        if autonomy <= 8:
            action_type = action_data.get("actionType", "")
            destructive_actions = {"delete", "remove", "clear", "reset", "drop"}
            return any(d in action_type.lower() for d in destructive_actions)

        # Max autonomy (9-10): Never require approval
        return False

    # Sentinel action type for the low-autonomy plan gate (id 16). It is NOT a
    # real tool — ``continue_after_approval`` recognises it and simply resumes
    # the loop rather than dispatching a tool by this name.
    _PLAN_GATE_ACTION_TYPE = "copilot.plan_gate"

    def _plan_gate_active(self) -> bool:
        """True when the first tool batch must wait for approval (id 16).

        At LOW autonomy (levels 0 and 1) the orchestrator emits a plan/approval
        step BEFORE the first tool batch even for read-only tools, so the
        autonomy control has an observable effect. Levels 2+ keep auto-execute.
        The gate fires at most once per turn (``_plan_gate_satisfied``).
        """
        if self._plan_gate_satisfied:
            return False
        return self._get_autonomy_level() <= 1

    def _emit_plan_gate(
        self,
        copilot_event_bus: Any,
        candidate_calls: List[Dict[str, Any]],
    ) -> None:
        """Pause before the first tool batch and request approval (id 16).

        Emits a ``copilot.plan`` event summarising the tools the copilot intends
        to run, plus a ``copilot.action_request`` event (``requiresApproval``)
        and pauses in ``WAITING_APPROVAL``. The pending action carries the
        plan-gate sentinel type so the existing ``approve_action`` /
        ``continue_after_approval`` machinery resumes the turn (it re-enters the
        loop with ``_plan_gate_satisfied`` set, so the tools then auto-execute).
        """
        planned_tools: List[str] = []
        for tc in candidate_calls or []:
            name = str(tc.get("function", {}).get("name", "") or "").strip()
            if name and name not in planned_tools:
                planned_tools.append(name)
        event_id = str(uuid.uuid4())
        autonomy = self._get_autonomy_level()
        plan_event = {
            "event": "copilot.plan",
            "id": event_id,
            "plan": {
                "id": event_id,
                "goal": "Toolausführung vor dem ersten Schritt bestätigen.",
                "steps": [{"tool": name} for name in planned_tools],
                "expectedOutcome": (
                    "Nach Freigabe führt der Copilot die geplanten Tools aus."
                ),
                "status": "proposed",
                "autonomyLevel": autonomy,
                "ts": int(time.time() * 1000),
            },
        }
        self._current_plan = plan_event["plan"]
        self._emit_output(copilot_event_bus, plan_event)

        request = {
            "requestId": event_id,
            "type": self._PLAN_GATE_ACTION_TYPE,
            "payload": {"tools": planned_tools},
            "autonomyHint": autonomy,
            "rationale": (
                "Niedrige Autonomiestufe: der erste Tool-Schritt benötigt eine "
                "ausdrückliche Freigabe."
            ),
        }
        action_event = {
            "event": "copilot.action_request",
            "id": event_id,
            "request": request,
            "meta": {
                "summary": (
                    "Geplante Tools ausführen: " + ", ".join(planned_tools)
                    if planned_tools
                    else "Geplante Toolausführung bestätigen."
                ),
                "reversible": True,
                "requiresApproval": True,
                "status": "pending",
                "ts": int(time.time() * 1000),
            },
        }
        self._pending_action = request
        self._plan_gate_satisfied = True
        self.state = State.WAITING_APPROVAL
        self._emit_output(copilot_event_bus, action_event)

    def _emit_control_frame_event(
        self,
        frame_type: str,
        data: Dict[str, Any],
        copilot_event_bus: Any
    ) -> None:
        """Emit a structured SSE event for a control frame."""
        event_id = str(uuid.uuid4())

        if frame_type == "PLAN":
            event = {
                "event": "copilot.plan",
                "id": event_id,
                "plan": {
                    "id": event_id,
                    "goal": data.get("goal", ""),
                    "steps": data.get("steps", []),
                    "expectedOutcome": data.get("expectedOutcome", ""),
                    "status": "proposed",
                    "ts": int(time.time() * 1000),
                }
            }
            self._current_plan = event["plan"]
            self._emit_output(copilot_event_bus, event)

        elif frame_type == "CLARIFY":
            event = {
                "event": "copilot.clarify",
                "id": event_id,
                "question": {
                    "questionId": event_id,
                    "prompt": data.get("question", ""),
                    "blocking": True,  # Clarifications block until answered
                    "options": data.get("options", []),
                    "rationale": data.get("reason", ""),
                    "timeout": data.get("timeout", 60),
                    "ts": int(time.time() * 1000),
                }
            }
            self._pending_clarification = event["question"]
            self.state = State.WAITING_CLARIFICATION
            self._emit_output(copilot_event_bus, event)

        elif frame_type == "ACTION":
            action_type = str(data.get("actionType", "") or "").strip()
            if not self._is_visible_control_action(action_type):
                event = {
                    "event": "copilot.action_blocked",
                    "id": event_id,
                    "request": {
                        "requestId": event_id,
                        "type": action_type,
                        "payload": data.get("payload", {}),
                        "autonomyHint": self._get_autonomy_level(),
                        "rationale": data.get("impact", ""),
                    },
                    "meta": {
                        "summary": data.get("summary", ""),
                        "status": "blocked",
                        "reason": "Action is not visible in Product-Capability-Contract",
                        "ts": int(time.time() * 1000),
                    },
                }
                self._emit_output(copilot_event_bus, event)
                return
            requires_approval = self._should_require_approval(data)
            event = {
                "event": "copilot.action_request",
                "id": event_id,
                "request": {
                    "requestId": event_id,
                    "type": action_type,
                    "payload": data.get("payload", {}),
                    "autonomyHint": self._get_autonomy_level(),
                    "rationale": data.get("impact", ""),
                },
                "meta": {
                    "summary": data.get("summary", ""),
                    "reversible": data.get("reversible", True),
                    "requiresApproval": requires_approval,
                    "status": "pending" if requires_approval else "auto_approved",
                    "ts": int(time.time() * 1000),
                }
            }
            if requires_approval:
                self._pending_action = event["request"]
                self.state = State.WAITING_APPROVAL
            self._emit_output(copilot_event_bus, event)

        elif frame_type == "RESEARCH_CONTEXT":
            keep = self._resolve_research_context_tags(data.get("keep", []))
            self._active_research_context_tags = keep
            event = {
                "event": "copilot.research_context",
                "id": event_id,
                "context": {
                    "keep": keep,
                    "ts": int(time.time() * 1000),
                },
            }
            self._emit_output(copilot_event_bus, event)

    def _extract_message_content(self, raw_content: str) -> str:
        """Extract actual message content from structured LLM responses.

        Some LLMs (like GPT-OSS) return structured JSON with 'reasoning' and 'message' blocks:
        [{'type': 'reasoning', 'content': '...'}, {'type': 'message', 'content': '...'}]

        This method extracts just the 'message' content for display to the user.
        """
        if not raw_content:
            return ""

        # Try to parse as structured response (list of blocks)
        try:
            # Handle Python-style dict representation
            import ast
            if raw_content.strip().startswith("[{") or raw_content.strip().startswith("[{'"):
                # Try to parse as JSON first
                try:
                    blocks = json.loads(raw_content)
                except json.JSONDecodeError:
                    # Try Python literal eval for single-quoted dicts
                    blocks = ast.literal_eval(raw_content)

                if isinstance(blocks, list):
                    message_parts = []
                    for block in blocks:
                        if isinstance(block, dict):
                            block_type = block.get("type", "")
                            block_content = block.get("content", "")
                            # Extract only 'message' or 'text' blocks, skip 'reasoning'
                            if block_type in ("message", "text", "response"):
                                message_parts.append(block_content)
                            # Also check if it has 'content' without type (fallback)
                            elif block_type == "" and block_content:
                                message_parts.append(block_content)
                    if message_parts:
                        return "\n".join(message_parts)
        except (json.JSONDecodeError, ValueError, SyntaxError):
            pass

        # Return as-is if not structured or parsing failed
        return raw_content

    def _process_llm_response(
        self,
        content: str,
        copilot_event_bus: Any
    ) -> Tuple[str, List[Tuple[str, Dict[str, Any]]]]:
        """Process LLM response and extract control frames.

        Returns:
            Tuple of (cleaned_content, list_of_control_frames)
        """
        # First, extract message content from structured responses (GPT-OSS etc.)
        content = self._extract_message_content(content)

        _b = list(self._turn_evidence_items or ())  # Rahmen sind Modelltext
        frames = [(f, kontrollrahmen_bewacht(d, _b, frage=getattr(self, "_turn_frage", ""))) for f, d in extract_all_control_frames(content)]

        # Emit events for each control frame
        for frame_type, frame_data in frames:
            self._emit_control_frame_event(frame_type, frame_data, copilot_event_bus)

        # Return cleaned content (without control frames)
        cleaned = remove_control_frames(content)
        return cleaned, frames

    def set_ui_context(self, context: Dict[str, Any]) -> None:
        """Update the UI context for autonomy-aware behavior."""
        self.ui_context = context

    def approve_action(self, action_id: str) -> bool:
        """Approve a pending action."""
        if self.cancel_requested:
            return False
        if self._pending_action and self._pending_action.get("requestId") == action_id:
            self.state = State.EXECUTING_TOOL
            return True
        return False

    def reject_action(self, action_id: str, reason: str = "") -> bool:
        """Reject a pending action."""
        if self.cancel_requested:
            return False
        if self._pending_action and self._pending_action.get("requestId") == action_id:
            self._pending_action = None
            self.state = State.WAITING_LLM
            return True
        return False

    def answer_clarification(
        self,
        clarification_id: str,
        answer: str | List[str]
    ) -> bool:
        """Provide an answer to a pending clarification.

        Adds the answer to the session history so the LLM can see it.
        """
        if self.cancel_requested:
            return False
        if (
            self._pending_clarification
            and self._pending_clarification.get("questionId") == clarification_id
        ):
            # Format the answer for the LLM
            question = self._pending_clarification.get("prompt", "")
            if isinstance(answer, list):
                answer_text = ", ".join(str(a) for a in answer)
            else:
                answer_text = str(answer)

            # Add as user message so LLM sees the clarification response
            self.session.append(
                {
                    "role": "user",
                    "content": f"[Clarification answer to '{question}']: {answer_text}",
                },
                project=self.project,
            )

            self._reset_runtime_guards()
            self._pending_clarification = None
            self.state = State.WAITING_LLM
            return True
        return False

    async def continue_after_approval(
        self,
        *,
        max_steps: int = 20,
        max_time: float | None = None,
    ) -> str:
        """Continue execution after an action has been approved.

        Returns the LLM's response after executing the approved action.
        Raises RuntimeError if not in EXECUTING_TOOL or WAITING_APPROVAL state.

        ``max_steps``/``max_time`` are forwarded to the resumed ``run_async`` loop
        so the server-side stream deadline (DT-SERVER) stays armed across the
        approval boundary instead of resetting to the default budget.
        """
        if self.cancel_requested:
            self.state = State.FINISHED
            return ""
        if self.state not in (State.EXECUTING_TOOL, State.WAITING_APPROVAL):
            raise RuntimeError(
                f"Cannot continue: state is {self.state.value}, "
                "expected EXECUTING_TOOL or WAITING_APPROVAL"
            )

        if not self._pending_action:
            raise RuntimeError("No pending action to execute")

        # Execute the approved action
        action = self._pending_action
        self._pending_action = None

        # Low-autonomy plan gate (id 16): the sentinel action is NOT a real tool.
        # Approving it just lifts the gate (``_plan_gate_satisfied`` stays True)
        # and re-enters the loop, where the planned tools now auto-execute. We do
        # NOT append a synthetic tool message — the assistant tool_calls were
        # never appended either, so the model simply proceeds from the same
        # history with the gate satisfied.
        if action.get("type") == self._PLAN_GATE_ACTION_TYPE:
            self.state = State.WAITING_LLM
            return await self.run_async(
                "",
                role="system",
                principal=self._active_principal,
                max_steps=max_steps,
                max_time=max_time,
            )

        # Add action result to session and continue LLM loop
        action_type = action.get("type", "unknown")
        payload = action.get("payload", {})
        if not self._is_visible_control_action(str(action_type)):
            self.session.append(
                {
                    "role": "tool",
                    "tool_call_id": action.get("requestId", str(uuid.uuid4())),
                    "content": json.dumps(
                        {
                            "status": "blocked",
                            "error": "Action is not visible in Product-Capability-Contract",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            self.state = State.WAITING_LLM
            return await self.run_async(
                "",
                role="system",
                principal=self._active_principal,
                max_steps=max_steps,
                max_time=max_time,
            )

        # Create a synthetic tool call for the action
        tool_call = {
            "id": action.get("requestId", str(uuid.uuid4())),
            "type": "function",
            "function": {
                "name": action_type,
                "arguments": json.dumps(payload),
            },
        }

        # Dispatch the action
        dispatch_is_async = asyncio.iscoroutinefunction(self.dispatch)
        self._raise_if_cancelled()
        if dispatch_is_async:
            result = await self.dispatch(tool_call, self.token)
        else:
            result = await asyncio.to_thread(self.dispatch, tool_call, self.token)
        result = werkzeugausgabe_ohne_betreiberpfad(mit_folgenbereich(action_type, mit_fassungsverteilung(action_type, result)))  # dritte Naht
        self._raise_if_cancelled()

        # Add result to session
        self.session.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(
                    _tool_output_for_model(result, werkzeug=action_type),
                    ensure_ascii=False,
                ),
            },
            project=self.project,
        )

        # Continue the LLM loop
        self.state = State.WAITING_LLM
        return await self.run_async(
            "",
            role="system",
            principal=self._active_principal,
            max_steps=max_steps,
            max_time=max_time,
        )

    async def continue_after_clarification(
        self,
        *,
        max_steps: int = 20,
        max_time: float | None = None,
    ) -> str:
        """Continue execution after a clarification has been answered.

        Returns the LLM's response after processing the clarification answer.
        Raises RuntimeError if not in WAITING_LLM state after answer.

        ``max_steps``/``max_time`` are forwarded to the resumed ``run_async`` loop
        so the server-side stream deadline (DT-SERVER) stays armed across the
        clarification boundary instead of resetting to the default budget.
        """
        if self.cancel_requested:
            self.state = State.FINISHED
            return ""
        if self.state != State.WAITING_LLM:
            raise RuntimeError(
                f"Cannot continue: state is {self.state.value}, expected WAITING_LLM"
            )

        # The answer should already be in session from answer_clarification
        # Just continue the LLM loop with the answer context
        return await self.run_async(
            "",
            role="system",
            principal=self._active_principal,
            max_steps=max_steps,
            max_time=max_time,
        )

    @property
    def messages(self) -> List[Dict[str, Any]]:
        return self.session.history

    def _is_tool_read_only(self, name: str) -> bool:
        if name in self._tool_runtime_info:
            return bool(self._tool_runtime_info.get(name, {}).get("read_only", False))
        # Missing runtime metadata is not evidence of read-only safety. The chat
        # endpoint now exposes only ProductOperation-bound, runtime-classified
        # tools; any other path must fail closed instead of relying on a name.
        return False

    def _is_visible_control_action(self, action_type: str) -> bool:
        if not action_type:
            return False
        if action_type == self._PLAN_GATE_ACTION_TYPE:
            return True
        return action_type in visible_product_action_types() or action_type in visible_product_copilot_tools()

    def _is_tool_known_write(self, name: str) -> bool:
        """True only for a tool *explicitly* registered as mutating.

        This is intentionally stricter than ``not _is_tool_read_only``: a tool
        with no runtime metadata at all (the general-assistant / bare-tool path)
        is NOT treated as a write tool, so the autonomy approval gate only fires
        for tools the registry has flagged ``read_only=False``. Otherwise every
        un-annotated tool would be force-gated behind approval.
        """
        info = self._tool_runtime_info.get(name)
        if not isinstance(info, dict) or "read_only" not in info:
            return False
        return not bool(info.get("read_only", True))

    def _is_tool_concurrency_safe(self, name: str) -> bool:
        info = self._tool_runtime_info.get(name, {})
        if "concurrency_safe" in info:
            return bool(info["concurrency_safe"])
        # R2 (gebuendelte Ausfuehrung): read-only-Tools laufen ohne explizite
        # Gegenannotation nebenlaeufig; Schreib-Tools und unklassifizierte
        # Tools bleiben seriell.
        return self._is_tool_read_only(name)

    def _reset_runtime_guards(self) -> None:
        self._failed_tool_attempts.clear()
        self._successful_read_only_tool_results.clear()
        self._current_turn_research_context_tags = []
        self._tool_call_anomalies = []
        # A new user turn re-arms the low-autonomy plan gate (id 16).
        self._plan_gate_satisfied = False

    def _reset_grounding_state(self) -> None:
        self._active_analysis_contract = {}
        self._turn_evidence_items, self._turn_frage = [], ""
        self._turn_ausgewertete_evidenz = None
        self._grounded_fact_notes = []
        self._evidence_gaps = []
        self._blocked_claims = []
        self._last_grounding_verdict = {}
        self._active_recipe_id = ""
        self._aktuelle_stufe = "Vorlauf"
        self._active_recipe_family = ""
        self._turn_recipe_routing = {}
        self._round_evidence_plan = {}
        self._round_evidence_items = {}
        self._turn_capability_unavailable_tools = {}
        self._turn_trailing_clarification = ""

    def _available_tool_names(self) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()
        for tool in list(self.tools or []):
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("function", {}).get("name", "") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
        return names

    def _read_only_tool_names(self) -> List[str]:
        return [
            name
            for name in self._available_tool_names()
            if self._is_tool_read_only(name)
        ]

    @staticmethod
    def _tool_signature(tool_call: Dict[str, Any]) -> str:
        function = tool_call.get("function", {})
        name = str(function.get("name", ""))
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except Exception:
                parsed = arguments
        else:
            parsed = arguments
        try:
            rendered = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        except Exception:
            rendered = str(parsed)
        return f"{name}:{rendered}"

    @staticmethod
    def _tool_args(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        arguments = tool_call.get("function", {}).get("arguments", "{}")
        if isinstance(arguments, dict):
            return arguments
        try:
            parsed = json.loads(arguments)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _stream_content_delta(chunk: Dict[str, Any]) -> str:
        try:
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta", {}) or {}
        except Exception:
            return ""

        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type", "")).lower()
                if item_type in {"text", "input_text", "output_text"}:
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return ""

    @staticmethod
    def _merge_stream_tool_call_deltas(
        tool_calls: List[Dict[str, Any]],
        chunk: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        try:
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta", {}) or {}
            delta_calls = list(delta.get("tool_calls", []) or [])
        except Exception:
            return tool_calls

        for raw_call in delta_calls:
            if not isinstance(raw_call, dict):
                continue
            try:
                index = int(raw_call.get("index", len(tool_calls)))
            except (TypeError, ValueError):
                index = len(tool_calls)
            while len(tool_calls) <= index:
                tool_calls.append(
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                )
            target = tool_calls[index]
            raw_id = raw_call.get("id")
            if raw_id:
                target["id"] = str(raw_id)
            raw_type = raw_call.get("type")
            if raw_type:
                target["type"] = str(raw_type)
            function = dict(raw_call.get("function", {}) or {})
            merged_function = dict(target.get("function", {}) or {})
            name_delta = function.get("name")
            if name_delta:
                merged_function["name"] = f"{merged_function.get('name', '')}{name_delta}"
            args_delta = function.get("arguments")
            if args_delta:
                merged_function["arguments"] = f"{merged_function.get('arguments', '')}{args_delta}"
            target["function"] = merged_function
        return tool_calls

    def _research_query(self, question: str) -> str:
        query_state = self.ui_context.get("query", {})
        current_query = self.ui_context.get("current_query")
        if not current_query and isinstance(query_state, dict):
            current_query = query_state.get("term") or query_state.get("cqlf") or ""
        return self._compact_runtime_text(current_query or question, limit=180)

    def _scope_preview(self, values: Any, *, limit: int = 2, item_limit: int = 48) -> List[str]:
        if not isinstance(values, list):
            return []
        preview: List[str] = []
        for item in values[:limit]:
            compact = self._compact_runtime_text(item, limit=item_limit)
            if compact:
                preview.append(compact)
        return preview

    def _scope_fingerprint(self, values: Any) -> str:
        if values in (None, "", [], {}):
            return ""
        try:
            raw = json.dumps(values, ensure_ascii=False, sort_keys=True)
        except Exception:
            raw = str(values)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    def _research_context_payload(self, question: str) -> Dict[str, Any]:
        corpus = self.ui_context.get("corpus", {})
        query_state = self.ui_context.get("query", {})
        kwic_state = self.ui_context.get("kwic", {})
        view_state = self.ui_context.get("view", {}) or {}
        filters = self.ui_context.get("active_filters")
        if filters is None and isinstance(corpus, dict):
            subcorpus = corpus.get("subcorpus", {}) or {}
            filters = subcorpus.get("filters", [])
        selected_rows = self.ui_context.get("selected_rows")
        if selected_rows is None and isinstance(kwic_state, dict):
            selection = kwic_state.get("selection", {}) or {}
            selected_rows = selection.get("rowIds", [])
        active_tab = self.ui_context.get("active_tab")
        if not active_tab:
            active_tab = view_state.get("activeTab", "")
        corpus_id = self.ui_context.get("corpus_id")
        if not corpus_id and isinstance(corpus, dict):
            corpus_id = corpus.get("corpusId", "")
        query_context = query_state.get("context", {}) if isinstance(query_state, dict) else {}
        result_set = kwic_state.get("resultSet", {}) if isinstance(kwic_state, dict) else {}
        visible_rows: List[str] = []
        if isinstance(kwic_state, dict):
            for row in list(kwic_state.get("preview", []) or [])[:4]:
                if not isinstance(row, dict):
                    continue
                marker = str(
                    row.get("rowId")
                    or row.get("docId")
                    or row.get("match")
                    or ""
                ).strip()
                if marker:
                    visible_rows.append(marker)
        view_scope = {}
        if isinstance(view_state, dict):
            for key, value in view_state.items():
                if key == "activeTab" or value in (None, "", [], {}):
                    continue
                view_scope[key] = value
        filter_preview = self._scope_preview(filters, limit=2, item_limit=56)
        selection_preview = self._scope_preview(selected_rows, limit=2, item_limit=40)
        return {
            "query": self._research_query(question),
            "corpus_id": corpus_id or "",
            "active_tab": active_tab or "",
            "query_mode": query_state.get("mode", "") if isinstance(query_state, dict) else "",
            "query_context": query_context,
            "query_context_fingerprint": self._scope_fingerprint(query_context),
            "view_scope_preview": self._compact_runtime_text(view_scope, limit=120) if view_scope else "",
            "view_scope_fingerprint": self._scope_fingerprint(view_scope),
            "filter_count": len(filters) if isinstance(filters, list) else (1 if filters else 0),
            "filter_preview": filter_preview,
            "filter_fingerprint": self._scope_fingerprint(filters),
            "selection_count": len(selected_rows) if isinstance(selected_rows, list) else (1 if selected_rows else 0),
            "selection_preview": selection_preview,
            "selection_fingerprint": self._scope_fingerprint(selected_rows),
            "result_total": int(result_set.get("rows", 0) or 0) if isinstance(result_set, dict) else 0,
            "visible_rows_fingerprint": self._scope_fingerprint(visible_rows),
        }

    def _structured_research_context(self, run: Dict[str, Any]) -> Dict[str, Any] | None:
        if not isinstance(run, dict):
            return None
        context = dict(run.get("context", {}) or {})
        dependencies = self._dedupe_ordered_strs(
            self._resolve_research_context_tags(run.get("dependencies", []))
        )
        findings = [
            self._compact_runtime_text(item, limit=180)
            for item in list(run.get("summaries", []) or [])[:3]
            if self._compact_runtime_text(item, limit=180)
        ]
        tools = [
            self._compact_runtime_text(item, limit=40)
            for item in list(run.get("tools", []) or [])[:3]
            if self._compact_runtime_text(item, limit=40)
        ]
        scope: Dict[str, Any] = {}
        if context.get("corpus_id"):
            scope["corpus"] = self._compact_runtime_text(context.get("corpus_id", ""), limit=40)
        if context.get("active_tab"):
            scope["tab"] = self._compact_runtime_text(context.get("active_tab", ""), limit=30)
        if context.get("query_mode"):
            scope["mode"] = self._compact_runtime_text(context.get("query_mode", ""), limit=30)
        if context.get("view_scope_preview"):
            scope["view"] = self._compact_runtime_text(context.get("view_scope_preview", ""), limit=120)
        if context.get("view_scope_fingerprint"):
            scope["view_fingerprint"] = self._compact_runtime_text(context.get("view_scope_fingerprint", ""), limit=12)
        query_context = context.get("query_context", {})
        if query_context not in (None, "", [], {}):
            scope["query_context"] = self._compact_runtime_text(query_context, limit=80)
        if context.get("query_context_fingerprint"):
            scope["query_context_fingerprint"] = self._compact_runtime_text(context.get("query_context_fingerprint", ""), limit=12)
        filter_count = int(context.get("filter_count", 0) or 0)
        if filter_count:
            filter_preview = [
                self._compact_runtime_text(item, limit=24)
                for item in list(context.get("filter_preview", []) or [])[:2]
                if self._compact_runtime_text(item, limit=24)
            ]
            filter_text = ", ".join(filter_preview) if filter_preview else str(filter_count)
            if filter_count > len(filter_preview) and filter_preview:
                filter_text = f"{filter_text} (+{filter_count - len(filter_preview)})"
            if context.get("filter_fingerprint"):
                filter_text = f"{filter_text} [F#{self._compact_runtime_text(context.get('filter_fingerprint', ''), limit=10)}]"
            scope["filters"] = filter_text
        selection_count = int(context.get("selection_count", 0) or 0)
        if selection_count:
            selection_preview = [
                self._compact_runtime_text(item, limit=20)
                for item in list(context.get("selection_preview", []) or [])[:2]
                if self._compact_runtime_text(item, limit=20)
            ]
            selection_text = ", ".join(selection_preview) if selection_preview else str(selection_count)
            if selection_count > len(selection_preview) and selection_preview:
                selection_text = f"{selection_text} (+{selection_count - len(selection_preview)})"
            if context.get("selection_fingerprint"):
                selection_text = f"{selection_text} [A#{self._compact_runtime_text(context.get('selection_fingerprint', ''), limit=10)}]"
            scope["selection"] = selection_text
        result_total = int(context.get("result_total", 0) or 0)
        if result_total:
            scope["results"] = str(result_total)
        if context.get("visible_rows_fingerprint"):
            scope["visible_rows"] = self._compact_runtime_text(context.get("visible_rows_fingerprint", ""), limit=12)

        payload = {
            "task": self._research_run_tag(run),
            "status": self._compact_runtime_text(run.get("status", ""), limit=24),
            "question": self._compact_runtime_text(run.get("query", ""), limit=160),
            "scope": scope,
            "dependencies": dependencies,
            "findings": findings,
            "tools": tools,
        }
        analysis_family = self._compact_runtime_text(run.get("analysis_family", ""), limit=40)
        if analysis_family:
            payload["analysis_family"] = analysis_family
        grounding_verdict = self._compact_runtime_text(run.get("grounding_verdict", ""), limit=80)
        if grounding_verdict:
            payload["grounding_verdict"] = grounding_verdict
        observed_fact_ids = self._dedupe_ordered_strs(
            [
                self._compact_runtime_text(item, limit=24)
                for item in list(run.get("observed_fact_ids", []) or [])
                if self._compact_runtime_text(item, limit=24)
            ]
        )
        if observed_fact_ids:
            payload["observed_fact_ids"] = observed_fact_ids[:6]
        manifests = [
            self._compact_runtime_text(item, limit=180)
            for item in list(run.get("evidence_manifest", []) or [])
            if self._compact_runtime_text(item, limit=180)
        ]
        if manifests:
            payload["evidence_manifest"] = manifests[:6]
        if (
            payload["question"]
            or findings
            or tools
            or scope
            or payload.get("analysis_family")
            or payload.get("grounding_verdict")
            or payload.get("observed_fact_ids")
            or payload.get("evidence_manifest")
        ):
            return payload
        return None

    def _should_run_research_worker(self, question: str, role: str) -> bool:
        if role != "user" or not question:
            return False
        if bool(self.ui_context.get("disable_background_research")):
            return False
        if self._pending_action or self._pending_clarification:
            return False
        self._harvest_research_tasks()

        # H9.1 (Befund 3): capability-unverfuegbare Werkzeuge zaehlen nicht
        # als Startgrund — sonst launcht der Worker und baut nur 409-Calls.
        selected = set(self._available_tool_names()) - set(
            self._turn_capability_unavailable_tools
        )
        available = {
            name
            for name in ("document_search", "semantic_search", "similar_words", "documentation_search")
            if name in selected and self._is_tool_read_only(name)
        }
        return bool(available)

    def _find_research_run_by_tag(self, tag: str) -> Dict[str, Any] | None:
        tag = (tag or "").strip()
        if not tag:
            return None
        for run in reversed(self._research_runs):
            if self._research_run_tag(run) == tag:
                return run
        return None

    def _find_research_run_by_id(self, run_id: str) -> Dict[str, Any] | None:
        target = (run_id or "").strip()
        if not target:
            return None
        for run in self._research_runs:
            if str(run.get("id", "")).strip() == target:
                return run
        return None

    def _find_recent_research_run(
        self,
        tags: List[str] | None = None,
    ) -> Dict[str, Any] | None:
        """Find the newest research run for a tag graph.

        The lookup is deterministic and tag-driven: no question/scope heuristics.
        """
        if tags is None:
            tags = self._get_explicit_research_context_tags()
        references = self._collect_research_context_closure(list(self._normalise_research_ref(tags)))
        if not references:
            return None
        index = self._research_run_index()
        for tag in references:
            if not tag:
                continue
            run = index.get(tag)
            if run:
                return run
        return None

    @staticmethod
    def _dedupe_ordered_strs(values: List[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for item in values:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _research_run_index(self) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for run in reversed(self._research_runs):
            tag = self._research_run_tag(run)
            if tag and tag not in index:
                index[tag] = run
        return index

    def _normalise_research_ref(self, refs: Any) -> List[str]:
        if refs is None:
            return []
        if isinstance(refs, str):
            return self._dedupe_ordered_strs([refs])
        if isinstance(refs, (list, tuple)):
            return self._dedupe_ordered_strs([str(item) for item in refs])
        return []

    def _get_explicit_research_context_tags(self) -> List[str]:
        return self._dedupe_ordered_strs(
            list(self._active_research_context_tags) + list(self._current_turn_research_context_tags)
        )

    def _collect_research_context_closure(self, tags: List[str]) -> List[str]:
        if not tags:
            return []
        index = self._research_run_index()
        visible: List[str] = []
        queue = list(self._dedupe_ordered_strs(tags))
        while queue:
            current = queue.pop(0)
            if current in visible:
                continue
            visible.append(current)
            run = index.get(current)
            if not isinstance(run, dict):
                continue
            dependencies = self._normalise_research_ref(run.get("dependencies"))
            for dep in dependencies:
                if dep and dep not in visible:
                    queue.append(dep)
        return visible

    def _get_visible_research_context_tags(self) -> List[str]:
        return self._collect_research_context_closure(
            self._get_explicit_research_context_tags()
        )

    def _find_research_run(self, tags: List[str]) -> Dict[str, Any] | None:
        return self._find_recent_research_run(tags)

    def _build_research_tool_calls(self, question: str) -> List[Dict[str, Any]]:
        term = self._research_query(question)
        if not term:
            return []

        requests: List[Dict[str, Any]] = []

        def _append(name: str, args: Dict[str, Any]) -> None:
            # Apply the capability gate here as well because research workers
            # dispatch outside the tool-space filter.
            if name in self._turn_capability_unavailable_tools:
                return
            if name not in set(self._available_tool_names()) or not self._is_tool_read_only(name):
                return
            requests.append(
                {
                    "id": f"research_{name}_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            )

        _append(
            "document_search",
            {"term": term, "top_n": 4, "snippet": 40},
        )
        _append(
            "semantic_search",
            {"term": term, "top_n": 4, "level": "doc", "min_score": 0.0},
        )
        if self._is_tool_read_only("similar_words"):
            _append(
                "similar_words",
                {"term": term, "k": 8},
            )
        if self._is_tool_read_only("documentation_search"):
            _append(
                "documentation_search",
                {"term": term, "top_n": 4, "snippet": 50},
            )

        return requests

    @staticmethod
    def _compact_runtime_text(value: Any, limit: int = 220) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            compact = " ".join(value.split())
        else:
            try:
                compact = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except Exception:
                compact = str(value)
            compact = " ".join(compact.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _research_run_tag(self, run: Dict[str, Any]) -> str:
        run_id = str(run.get("id", "") or "").strip()[:8]
        if run_id:
            return f"R{run_id}"
        context = dict(run.get("context", {}) or {})
        scope_seed = (
            self._compact_runtime_text(context.get("filter_fingerprint", ""), limit=6)
            or self._compact_runtime_text(context.get("selection_fingerprint", ""), limit=6)
            or self._compact_runtime_text(context.get("corpus_id", ""), limit=6)
        )
        return f"R{scope_seed}" if scope_seed else "Rtask"

    def _bind_research_run_to_current_turn(self, run: Dict[str, Any]) -> str:
        tag = self._research_run_tag(run)
        if not tag:
            return ""
        ordered = [existing for existing in self._current_turn_research_context_tags if existing != tag]
        ordered.append(tag)
        self._current_turn_research_context_tags = ordered[-8:]
        return tag

    def _resolve_research_context_tags(self, refs: Any) -> List[str]:
        valid_tags = {
            self._research_run_tag(run): str(run.get("id", "") or "").strip()
            for run in self._research_runs
            if self._research_run_tag(run)
        }
        resolved: List[str] = []
        for raw_ref in list(refs or []):
            ref = str(raw_ref or "").strip()
            if not ref:
                continue
            if ref.lower() == "current":
                for tag in self._current_turn_research_context_tags:
                    if tag and tag not in resolved:
                        resolved.append(tag)
                continue
            if ref in valid_tags and ref not in resolved:
                resolved.append(ref)
                continue
            for tag, run_id in valid_tags.items():
                if ref == run_id or (run_id and run_id.startswith(ref)) or tag == f"R{ref.strip().lstrip('R')}":
                    if tag not in resolved:
                        resolved.append(tag)
                    break
        return resolved

    def _visible_recent_research_findings(
        self,
        tags: List[str],
        *,
        max_items: int = 4,
    ) -> List[str]:
        visible = set(self._dedupe_ordered_strs(tags))
        if not visible:
            return []
        selected: List[str] = []
        seen: set[str] = set()
        for entry in reversed(self._recent_research_findings):
            if not isinstance(entry, dict):
                continue
            tag = str(entry.get("run_tag", "") or "").strip()
            summary = str(entry.get("summary", "") or "").strip()
            if not tag or not summary or tag not in visible or summary in seen:
                continue
            seen.add(summary)
            selected.append(summary)
            if len(selected) >= max_items:
                break
        selected.reverse()
        return selected

    def _remember_research_summaries(
        self,
        summaries: List[Any],
        *,
        run: Dict[str, Any] | None = None,
    ) -> None:
        prefix = ""
        if isinstance(run, dict):
            context = dict(run.get("context", {}) or {})
            scope_parts = [self._research_run_tag(run)]
            corpus_id = self._compact_runtime_text(context.get("corpus_id", ""), limit=32)
            filter_fingerprint = self._compact_runtime_text(context.get("filter_fingerprint", ""), limit=10)
            selection_fingerprint = self._compact_runtime_text(context.get("selection_fingerprint", ""), limit=10)
            if corpus_id:
                scope_parts.append(f"Korpus {corpus_id}")
            if filter_fingerprint:
                scope_parts.append(f"F#{filter_fingerprint}")
            if selection_fingerprint:
                scope_parts.append(f"A#{selection_fingerprint}")
            prefix = " | ".join(part for part in scope_parts if part)
        for item in list(summaries or []):
            compact = self._compact_runtime_text(item, limit=220)
            if not compact:
                continue
            if prefix:
                compact = self._compact_runtime_text(f"{prefix} | {compact}", limit=220)
            run_tag = self._research_run_tag(run or {})
            if not run_tag:
                continue
            self._recent_research_findings = [
                existing
                for existing in self._recent_research_findings
                if not (
                    isinstance(existing, dict)
                    and str(existing.get("run_tag", "") or "").strip() == run_tag
                    and str(existing.get("summary", "") or "").strip() == compact
                )
            ]
            self._recent_research_findings.append(
                {
                    "run_tag": run_tag,
                    "run_id": str((run or {}).get("id", "") or "").strip(),
                    "summary": compact,
                    "ts": int(time.time() * 1000),
                }
            )
        self._recent_research_findings = self._recent_research_findings[-12:]

    def _record_tool_outcome(
        self,
        tool_name: str,
        args: Dict[str, Any],
        output: Any,
        *,
        ok: bool,
        signature: str,
    ) -> None:
        rendered_args = self._compact_runtime_text(args, limit=180)
        rendered_output = self._compact_runtime_text(output, limit=220)
        summary = f"{tool_name}({rendered_args})"
        if rendered_output:
            summary = f"{summary} -> {rendered_output}"

        entry = {
            "tool": tool_name,
            "summary": summary,
            "ok": ok,
            "ts": int(time.time() * 1000),
        }
        self._recent_tool_results.append(entry)
        self._recent_tool_results = self._recent_tool_results[-8:]

        if ok:
            self._failed_tool_attempts.pop(signature, None)
            if self._is_tool_read_only(tool_name):
                self._successful_read_only_tool_results[signature] = copy.deepcopy(
                    output
                )
            return

        previous = self._failed_tool_attempts.get(signature, {})
        self._failed_tool_attempts[signature] = {
            "tool": tool_name,
            "args": rendered_args,
            "reason": rendered_output or "Tool-Fehler",
            "count": int(previous.get("count", 0)) + 1,
            "ts": entry["ts"],
        }

    def _build_runtime_state(self, active_question: str) -> Dict[str, Any]:
        self._harvest_research_tasks()
        current_query = self.ui_context.get("current_query")
        selected_rows = self.ui_context.get("selected_rows")
        active_filters = self.ui_context.get("active_filters")
        active_tab = self.ui_context.get("active_tab")
        if not active_tab and isinstance(self.ui_context.get("view"), dict):
            active_tab = self.ui_context.get("view", {}).get("activeTab")
        visible_research_tags = self._collect_research_context_closure(
            self._get_explicit_research_context_tags()
        )
        visible_research_tag_set = set(visible_research_tags)

        def _is_prompt_visible_research_run(run: Dict[str, Any]) -> bool:
            tag = self._research_run_tag(run)
            if not tag:
                return False
            return tag in visible_research_tag_set

        visible_research_runs = [
            run
            for run in self._research_runs
            if _is_prompt_visible_research_run(run)
        ]

        last_valid_results = [
            item["summary"]
            for item in self._recent_tool_results
            if item.get("ok")
        ][-4:]
        failed_attempts = [
            (
                f"{entry.get('tool')}({entry.get('args')}) -> {entry.get('reason')}"
                if entry.get("args")
                else f"{entry.get('tool')} -> {entry.get('reason')}"
            )
            for entry in self._failed_tool_attempts.values()
        ][-4:]

        next_step = ""
        if self._pending_clarification:
            next_step = "Warte auf die offene Rueckfrage des Nutzers."
        elif self._pending_action:
            next_step = "Warte auf Freigabe für die vorgeschlagene Aktion."
        elif self._current_plan:
            goal = self._current_plan.get("goal")
            if goal:
                next_step = f"Arbeite auf dieses Ziel hin: {self._compact_runtime_text(goal, 180)}"
        elif failed_attempts:
            next_step = "Nutze eine veränderte Strategie statt denselben Tool-Call zu wiederholen."

        current_plan = ""
        if self._current_plan:
            goal = self._compact_runtime_text(self._current_plan.get("goal", ""), 180)
            steps = self._current_plan.get("steps", [])
            first_step = ""
            if isinstance(steps, list) and steps:
                first_step = self._compact_runtime_text(steps[0], 120)
            if goal and first_step:
                current_plan = f"{goal} | nächster Planschritt: {first_step}"
            else:
                current_plan = goal or first_step

        ui_focus_parts: List[str] = []
        if active_tab:
            ui_focus_parts.append(f"Tab {active_tab}")
        if isinstance(selected_rows, list) and selected_rows:
            ui_focus_parts.append(f"{len(selected_rows)} Zeilen markiert")
        elif selected_rows:
            ui_focus_parts.append(self._compact_runtime_text(selected_rows, 120))
        ui_focus = " | ".join(ui_focus_parts)
        research_contexts = [
            record
            for record in (
                self._structured_research_context(item)
                for item in visible_research_runs
            )
            if record
        ][-4:]
        background_tasks = []
        if not research_contexts:
            background_tasks = [
                self._render_research_run(item)
                for item in visible_research_runs
                if self._render_research_run(item)
            ][-4:]
        visible_research_findings = self._visible_recent_research_findings(visible_research_tags)
        if research_contexts:
            visible_research_findings = []

        return {
            "user_goal": self._compact_runtime_text(
                self.ui_context.get("task_goal") or current_query or active_question,
                limit=220,
            ),
            "active_question": self._compact_runtime_text(
                active_question or current_query,
                limit=220,
            ),
            "active_filters": active_filters,
            "active_selection": selected_rows[:10] if isinstance(selected_rows, list) else selected_rows,
            "ui_focus": ui_focus,
            "open_clarification": self._pending_clarification.get("prompt", "")
            if self._pending_clarification
            else "",
            "open_approval": self._pending_action.get("type", "")
            if self._pending_action
            else "",
            "current_plan": current_plan,
            "active_analysis_contract": self._compact_runtime_text(
                self._active_analysis_contract,
                limit=220,
            ),
            "last_valid_tool_results": last_valid_results,
            "grounded_fact_notes": list(self._grounded_fact_notes[-5:]),
            "evidence_gaps": list(self._evidence_gaps[-5:]),
            "blocked_claims": list(self._blocked_claims[-5:]),
            "tool_call_anomalies": [
                self._compact_runtime_text(item, limit=240)
                for item in list(self._tool_call_anomalies[-4:])
            ],
            "last_grounding_verdict": self._compact_runtime_text(
                self._last_grounding_verdict,
                limit=220,
            ),
            "research_contexts": research_contexts,
            "recent_research_findings": visible_research_findings,
            "background_tasks": background_tasks,
            "failed_attempts": failed_attempts,
            "recent_recoveries": list(self._recent_recoveries[-4:]),
            "last_llm_route": self._compact_runtime_text(
                f"{self._last_llm_route} [{self._last_llm_model}]".strip(),
                limit=180,
            ),
            "next_step": next_step,
        }

    def _render_research_run(self, run: Dict[str, Any]) -> str:
        status = str(run.get("status", "") or "")
        query = self._compact_runtime_text(run.get("query", ""), limit=84)
        findings = int(run.get("findings", 0) or 0)
        tools = list(run.get("tools", []) or [])
        tool_text = ", ".join(str(item) for item in tools[:2] if item)
        context = dict(run.get("context", {}) or {})
        corpus_id = self._compact_runtime_text(context.get("corpus_id", ""), limit=40)
        active_tab = self._compact_runtime_text(context.get("active_tab", ""), limit=30)
        query_mode = self._compact_runtime_text(context.get("query_mode", ""), limit=30)
        filter_count = int(context.get("filter_count", 0) or 0)
        filter_preview = [self._compact_runtime_text(item, limit=18) for item in list(context.get("filter_preview", []) or []) if item]
        filter_fingerprint = self._compact_runtime_text(context.get("filter_fingerprint", ""), limit=10)
        selection_count = int(context.get("selection_count", 0) or 0)
        selection_preview = [self._compact_runtime_text(item, limit=16) for item in list(context.get("selection_preview", []) or []) if item]
        selection_fingerprint = self._compact_runtime_text(context.get("selection_fingerprint", ""), limit=10)
        view_scope_preview = self._compact_runtime_text(context.get("view_scope_preview", ""), limit=40)
        view_scope_fingerprint = self._compact_runtime_text(context.get("view_scope_fingerprint", ""), limit=10)
        query_context = context.get("query_context", {})
        query_context_text = self._compact_runtime_text(query_context, limit=28) if query_context not in (None, "", [], {}) else ""
        result_total = int(context.get("result_total", 0) or 0)
        visible_rows_fingerprint = self._compact_runtime_text(context.get("visible_rows_fingerprint", ""), limit=10)
        scope_parts = [self._research_run_tag(run)]
        if status:
            scope_parts.append(status)
        if corpus_id:
            scope_parts.append(f"Korpus {corpus_id}")
        if active_tab:
            scope_parts.append(f"Tab {active_tab}")
        if query_mode:
            scope_parts.append(f"Modus {query_mode}")
        if view_scope_preview:
            view_text = view_scope_preview
            if view_scope_fingerprint:
                view_text = f"{view_text} V#{view_scope_fingerprint}"
            scope_parts.append(f"Ansicht {view_text}".strip())
        elif view_scope_fingerprint:
            scope_parts.append(f"Ansicht V#{view_scope_fingerprint}")
        if query_context_text:
            scope_parts.append(f"Fenster {query_context_text}")
        if filter_count:
            filter_marker = f"#{filter_fingerprint}" if filter_fingerprint else ""
            if filter_preview:
                filter_text = ",".join(filter_preview)
                if filter_count > len(filter_preview):
                    filter_text = f"{filter_text} (+{filter_count - len(filter_preview)})"
                scope_parts.append(f"Filter {filter_text} {filter_marker}".strip())
            else:
                scope_parts.append(f"Filter {filter_count} {filter_marker}".strip())
        if selection_count:
            selection_marker = f"#{selection_fingerprint}" if selection_fingerprint else ""
            if selection_preview:
                selection_text = ",".join(selection_preview)
                if selection_count > len(selection_preview):
                    selection_text = f"{selection_text} (+{selection_count - len(selection_preview)})"
                scope_parts.append(f"Auswahl {selection_text} {selection_marker}".strip())
            else:
                scope_parts.append(f"Auswahl {selection_count} {selection_marker}".strip())
        if result_total:
            scope_parts.append(f"Treffer {result_total}")
        if visible_rows_fingerprint:
            scope_parts.append(f"Vorschau P#{visible_rows_fingerprint}")
        head = " | ".join(scope_parts)
        tail_parts = [part for part in (query,) if part]
        if findings:
            tail_parts.append(f"{findings} Befunde")
        if tool_text:
            tail_parts.append(tool_text)
        if not tail_parts:
            return self._compact_runtime_text(head, limit=220)
        if not head:
            return self._compact_runtime_text(" | ".join(tail_parts), limit=220)
        if len(head) >= 180:
            return self._compact_runtime_text(head, limit=220)
        remaining = max(24, 220 - len(head) - 3)
        tail = self._compact_runtime_text(" | ".join(tail_parts), limit=remaining)
        return f"{head} | {tail}".strip(" |")

    def _harvest_research_tasks(self) -> None:
        if not self._active_research_tasks:
            return
        finished: List[str] = []
        by_id = {str(run.get("id", "")): run for run in self._research_runs}
        for run_id, task in list(self._active_research_tasks.items()):
            if not task.done():
                continue
            finished.append(run_id)
            run = by_id.get(run_id)
            if run is None:
                continue
            if task.cancelled():
                run["status"] = "cancelled"
            else:
                try:
                    task.result()
                except Exception as exc:  # pragma: no cover - defensive
                    run["status"] = "error"
                    run["message"] = self._compact_runtime_text(str(exc), limit=180)
                else:
                    if run.get("status") not in {"complete", "error"}:
                        run["status"] = "complete"
            run["updated_at"] = int(time.time() * 1000)
        for run_id in finished:
            self._active_research_tasks.pop(run_id, None)
        if finished:
            self._research_runs = self._research_runs[-8:]

    def _partition_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Tuple[bool, List[Dict[str, Any]]]]:
        batches: List[Tuple[bool, List[Dict[str, Any]]]] = []
        for tc in tool_calls:
            name = tc.get("function", {}).get("name", "")
            is_safe = self._is_tool_concurrency_safe(str(name))
            if is_safe and batches and batches[-1][0]:
                batches[-1][1].append(tc)
            else:
                batches.append((is_safe, [tc]))
        return batches

    @staticmethod
    def _llm_retry_delay(error: LLMRequestError, attempt: int) -> float:
        if error.retry_after is not None:
            return max(0.25, min(30.0, float(error.retry_after)))
        return min(20.0, 0.5 * (2 ** max(0, attempt)))

    # ------------------------------------------------------------------
    # run_async helpers (``_ra_`` prefix)
    #
    # These methods are closure bodies extracted verbatim from
    # ``run_async`` during the god-method decomposition. They read only
    # ``self`` and explicit parameters; per-turn state from ``run_async``
    # (e.g. ``copilot_event_bus``, ``normalized_question``) is passed in explicitly.
    # ------------------------------------------------------------------

    def _ra_refresh_session_state(self, question: str) -> None:
        self.session.update_rehydration_state(
            self._build_runtime_state(question)
        )

    @staticmethod
    def _ra_runtime_system_prompt(system_prompt: str) -> str:
        """Remove the all-tools manual from the per-turn runtime prompt."""
        return compact_runtime_system_prompt(system_prompt)

    # ------------------------------------------------------------------
    # R2 Rezept-Harness: Prompt-Zusammenbau, Rezept-Auswahl, Referenzpfad
    # ------------------------------------------------------------------

    async def _ra_route_turn_recipe(
        self, question: str, max_time: float | None = None
    ) -> Dict[str, Any]:
        """Hybride Rezeptwahl (H9/C1): Stufe 1 Trigger, sonst EIN LLM-Call.

        Fehler/Timeout degradieren nie zu einer Ablehnung (H9.1: Timeout auf
        max_time/3 gekappt, EIN Wanduhr-Abzug, kein Doppelabzug)."""
        timeout_s = None
        if max_time is not None and max_time > 0:
            timeout_s = min(
                recipe_classifier_timeout_s(), float(max_time) / 3.0
            )
        # H9.2: LLM-Pick prueft gegen Registry minus Gates (Universum).
        gated = set(self._turn_capability_unavailable_tools)
        universe = [n for n in registry_tool_names() if n not in gated]
        return await route_turn_recipe(
            question,
            {
                "available_tools": self._available_tool_names(),
                "read_only_tools": self._read_only_tool_names(),
                "routing_tool_universe": universe,
            },
            self.call_llm,
            timeout_s=timeout_s,
            cancelled=lambda: bool(self.cancel_requested),
        )

    def _ra_tool_rounds_exhausted(self, state: _RunTurnState) -> bool:
        """Zu Ende, wenn das MODELL abgibt, sonst an der Reissleine."""
        if getattr(self, "_ra_deutung_abgegeben", False):
            return True
        if getattr(state, "schrittdecke_erreicht", False):
            return True
        return tool_rounds_exhausted(state.tool_rounds, self._active_recipe_id,
                                     state.started_at, state.max_time)

    def _ra_build_turn_system_prompt(self) -> str:
        """System-Nachricht: byte-stabiler Kern + Turn-Suffix strikt am Ende.

        Delegiert an ``recipe_runtime.build_turn_system_prompt``:
        ``build_static_core()`` ist der byte-identische Praefix aller Turns
        einer Session (LM-Studio-Prefix-Cache), alles Variable (ui_context,
        Korpus-Karte, Session-Stand, Rezept-Briefing) folgt DANACH, das
        ``<turn_briefing>`` steht als letzter Block am Ende.
        """
        return build_turn_system_prompt(
            self.ui_context,
            self._active_recipe_id,
            session_briefing_state(
                self.ui_context or {},
                self._recent_tool_results,
                self._failed_tool_attempts,
            ),
        )

    def _ra_plan_round_evidence(
        self,
        ordered_calls: List[Dict[str, Any]],
        active_contract: AnalysisContract | None,
    ) -> None:
        """Vergibt Evidenz-IDs in Anforderungsreihenfolge VOR der Ausfuehrung.

        Gebuendelte read-only-Calls laufen nebenlaeufig; die vorab geplanten
        IDs und der Flush in Anforderungsreihenfolge halten die
        Evidenz-Reihenfolge deterministisch (unabhaengig von der
        Fertigstellungsreihenfolge). Schluessel ist die Objekt-Identitaet des
        Tool-Calls: Provider-Call-IDs koennen leer oder doppelt sein.
        """
        family = (
            active_contract.analysis_family
            if active_contract is not None
            else (self._active_recipe_family or "")
        )
        used = {
            str(item.get("id", "") or "")
            for item in self._turn_evidence_items
            if isinstance(item, dict)
        }
        base = len(self._turn_evidence_items)
        self._round_evidence_plan = {}
        self._round_evidence_items = {}
        for offset, tc in enumerate(ordered_calls, start=1):
            name = str(tc.get("function", {}).get("name", "") or "tool")
            candidate = f"E_{name}_{base + offset}"
            duplicate_index = 2
            while candidate in used:
                candidate = f"E_{name}_{base + offset}_{duplicate_index}"
                duplicate_index += 1
            used.add(candidate)
            self._round_evidence_plan[id(tc)] = (candidate, family)

    def _ra_flush_round_evidence(
        self, ordered_calls: List[Dict[str, Any]]
    ) -> None:
        """Haengt die Runden-Evidenz in Anforderungsreihenfolge an den Turn."""
        for tc in ordered_calls:
            item = self._round_evidence_items.pop(id(tc), None)
            if item is not None:
                self._turn_evidence_items.append(item)
        self._round_evidence_plan = {}
        self._round_evidence_items = {}

    def _ra_resolve_reference_draft(
        self,
        turn_state: _RunTurnState,
        text: str,
        *,
        detect_bare_numbers: bool = True,
    ) -> Dict[str, Any]:
        """Referenz-Aufloesung gegen die Turn-Evidenz (recipe_runtime)."""
        return resolve_reference_draft(
            text,
            list(self._turn_evidence_items or []),
            turn_state.normalized_question,
            detect_bare_numbers=detect_bare_numbers,
        )

    async def _ra_reference_repair_call(
        self,
        turn_state: _RunTurnState,
        copilot_event_bus: Any,
        draft: str,
        findings: List[str],
    ) -> str:
        """Make one targeted repair call with concrete reference errors."""
        error_list = "; ".join(findings[:8])
        repair_messages = (
            [{"role": "system", "content": turn_state.system_prompt}]
            + self.session.get_history()
            + [
                {"role": "assistant", "content": draft},
                {
                    "role": "user",
                    "content": (
                        "[System note: Deine Antwort enthaelt unbelegte "
                        "Angaben: " + error_list + ". Korrigiere NUR diese "
                        "Stellen: ersetze jede Angabe durch eine gueltige "
                        "{{ev:...}}-Referenz auf vorhandene Evidenz oder "
                        "streiche den betroffenen Satz ersatzlos. Keine neuen "
                        "Zahlen, keine Tool-Calls. Gib die vollstaendige "
                        "korrigierte Antwort aus.]"
                    ),
                },
            ]
        )
        try:
            raw = await self._ra_call_llm_with_recovery(
                turn_state,
                copilot_event_bus,
                invoker=lambda: self._ra_invoke_llm(
                    turn_state,
                    request_messages=repair_messages,
                    tools_override=[],
                    use_stream=False,
                ),
            )
        except CopilotTurnCancelled:
            raise
        except Exception:
            logger.exception("Referenz-Repair-Call fehlgeschlagen")
            return ""
        if not isinstance(raw, dict):
            return ""
        try:
            message = raw.get("choices", [{}])[0].get("message", {}) or {}
        except (AttributeError, IndexError, TypeError):
            return ""
        content = str(message.get("content", "") or "")
        if not content.strip():
            return ""
        return remove_control_frames(self._extract_message_content(content))

    async def _ra_reference_answer(
        self,
        turn_state: _RunTurnState,
        copilot_event_bus: Any,
        draft: str,
    ) -> str:
        """Resolve references for the free-mode answer path.

        Unresolved references and unsupported numbers trigger one targeted repair
        call. Remaining errors become visible placeholders. The deterministic
        fact path completes before reaching this branch.

        Without turn evidence, resolve reference markers but treat conversational
        numbers as ordinary text, so they do not trigger evidence repair.
        """
        text = str(draft or "")
        if not text.strip():
            return text
        detect_bare_numbers = bool(self._turn_evidence_items)
        resolution = self._ra_resolve_reference_draft(
            turn_state,
            text,
            detect_bare_numbers=detect_bare_numbers,
        )
        findings = reference_hard_findings(resolution)
        if findings and not turn_state.reference_repair_used:
            turn_state.reference_repair_used = True
            self._ra_emit_recovery(
                copilot_event_bus,
                turn_state.normalized_question,
                "reference_repair",
                lt("Unbelegte Referenzen oder Zahlen in der Antwort: {}. Genau ein "
                   "gezielter Korrektur-Aufruf laeuft.",
                   "Unsupported references or numbers in the answer: {}. Exactly one "
                   "targeted correction call is running.").format("; ".join(findings[:4])),
            )
            repaired = await self._ra_reference_repair_call(
                turn_state,
                copilot_event_bus,
                text,
                findings,
            )
            if repaired.strip():
                resolution = self._ra_resolve_reference_draft(
                    turn_state,
                    repaired,
                    detect_bare_numbers=detect_bare_numbers,
                )
        final_text = str(resolution.get("text") or "")
        bare_numbers = list(resolution.get("bare_numbers") or [])
        if bare_numbers:
            final_text = strike_unbound_numbers(final_text, bare_numbers)
        # H6 (B5): Platzhalter-Saetze fallen mit Sammel-Annotation.
        final_text = drop_unresolved_sentences(final_text)
        return final_text if final_text.strip() else text

    def _ra_finish_turn(
        self,
        copilot_event_bus: Any,
        normalized_question: str,
        text: str,
        *,
        stream_emit: bool,
    ) -> str:
        """Chokepoint aller Antwort-Landungen (H9/C2, V6+V11).

        GENAU EIN Politur-Durchlauf fuer jeden fertigen Antworttext, egal
        ueber welche Landung er den Orchestrator verlaesst (normal,
        wrap-up, verifier-skip, fail-closed, max_steps, timeout,
        Vorbedingungs-Kurzschluss). Hier sitzt darum auch die Zitatwache
        (H11.7, Begruendung in recipe_runtime). Annotationen wandern in ein
        copilot.grounding-Event, nicht in den sichtbaren Text.
        """
        # Rueckfrage MIT hinein, sonst der einzige Absatz hinter der Wache.
        polished, annotations = politur_mit_zitatwache(
            text, list(self._turn_evidence_items or ()), frage=normalized_question,
            rueckfrage=getattr(self, "_turn_trailing_clarification", ""),
            ausgewertet=getattr(self, "_turn_ausgewertete_evidenz", None),
            eigene_zitate_bleiben=(self._active_analysis_contract or {}).get("grounding_output_mode") == "deutungs_synthese")
        self._turn_trailing_clarification = ""
        _zwischenstand("4_poliert", polished, sitzung=getattr(self.session, "session_id", ""))
        if annotations:
            self._emit_output(copilot_event_bus, final_polish_event(
                self._active_recipe_family or "", annotations))
        self.state = State.FINISHED
        self.session.append(
            {"role": "assistant", "content": polished},
            project=self.project,
        )
        self.session.summarise(
            project=self.project,
            runtime_state=self._build_runtime_state(normalized_question),
        )
        if stream_emit and polished:
            self._emit_output(
                copilot_event_bus,
                {"delta": {"role": "assistant", "content": polished}},
            )
        return polished

    def _ra_pause_turn(self, question: str, text: str, state: "State") -> str:
        """Pausierende Landung, mit derselben Wache wie eine fertige."""
        geprueft, _annotationen = politur_mit_zitatwache(
            text, list(self._turn_evidence_items or ()), frage=question)
        self.state = state
        self.session.append(
            {"role": "assistant", "content": geprueft}, project=self.project)
        self.session.summarise(
            project=self.project,
            runtime_state=self._build_runtime_state(question))
        return geprueft

    @staticmethod
    def _ra_tool_runtime_guard_message(
        tool_specs: List[Dict[str, Any]],
        *,
        confirmation_pressure: bool = False,
        structured_step: bool = False,
        evidenz_in_nachrichten: bool = False,
    ) -> str:
        names: List[str] = []
        for spec in tool_specs:
            if not isinstance(spec, dict):
                continue
            function = spec.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        if not names:
            if structured_step:
                return (
                    "RUNTIME-TOOL-SPACE:\n"
                    "- In diesem schema-gebundenen internen Schritt sind keine "
                    "Tools verfügbar oder erforderlich.\n"
                    "- Die zulässigen Forschungsdaten stehen bereits vollständig "
                    "in den übergebenen Nachrichten. Werte sie direkt gemäß "
                    "Aufgabe und Schema aus.\n"
                    "- Erzeuge keine function_call- oder Pseudo-Tool-Ausgaben; "
                    "verweigere die Auswertung aber nicht wegen des leeren "
                    "Tool-Space und stelle deshalb keine Rückfrage."
                )
            leer = (
                "RUNTIME-TOOL-SPACE:\n"
                "- In diesem Aufruf sind keine Tools verfügbar.\n"
                "- Erzeuge weder function_call-Ausgaben noch ausgeschriebene "
                "Pseudo-Tool-Calls."
            )
            # Vorbereitete Aufrufe (Deutungs-Synthese, Referenz-Reparatur) tragen ihre
            # Evidenz in den Nachrichten. Der Satz unten widersprach ihrem Auftrag.
            if evidenz_in_nachrichten:
                return leer
            return leer + (
                "\n- Beantworte nur, was ohne Tool-Evidenz verantwortbar ist; "
                "sonst benenne die Grenze oder stelle eine Rückfrage."
            )
        confirmation_guidance = (
            "\n- Bei einer gerichteten Universalhypothese operationalisiere "
            "zuerst den behaupteten Gegenstand und die zu prüfende Eigenschaft. "
            "Gewinne Kandidaten über den Gegenstand, nicht isoliert über das "
            "Bewertungsprädikat, und prüfe sie ergebnisoffen. "
            "\n- Die vertraglich geforderten Evidenzarten sind ein Mindestmaß, "
            "kein Signal zum vorzeitigen Finalisieren. Wähle selbst eine fachlich "
            "komplementäre Kombination der verfügbaren Tools: Exakte Wort- oder "
            "Lemmaabfragen und semantische beziehungsweise dokumentbasierte "
            "Retrievals beantworten unterschiedliche Fragen und ersetzen einander "
            "nicht. "
            "\n- Eine einzelne Wortform plus eine begrenzte Top-N-Rangliste ist "
            "keine korpusweite Polaritätsmessung. Wenn Suchfeld, Bewertungsobjekt, "
            "Kodierkriterium und Analysepopulation mit den verfügbaren Tools nicht "
            "systematisch abgedeckt werden können, kennzeichne den Lauf als "
            "begrenzten Falsifikations- oder Plausibilitätscheck; interpretiere die "
            "sichtbaren Belege gehaltvoll, aber ziehe daraus kein Prävalenzurteil."
            if confirmation_pressure and "semantic_search" in names
            else ""
        )
        cql_guidance = (
            "\n- CQLF: Benachbarte [...] [...] sind aufeinanderfolgende "
            "Token, keine zwei Bedingungen für dasselbe Token. Verbinde "
            "Same-Token-Bedingungen innerhalb EINER Zelle mit &: "
            "[lemma=\"gehen\" & pos=\"VERB\"]. Beginne einen "
            "Hypothesentest mit einer breiten Wort-/Lemma-Basisabfrage, bevor "
            "du begründete engere Sequenzen prüfst."
            if "run_cqlf_query" in names or "query_count" in names
            else ""
        )
        return (
            "RUNTIME-TOOL-SPACE:\n"
            f"- In diesem Aufruf sind nur diese Tool-Namen gültig: {', '.join(names)}\n"
            "- Jeder andere Tool-Name ist in diesem Schritt ungültig und darf nicht emittiert werden.\n"
            "- Wiederhole keinen identischen erfolgreichen Tool-Call; sein Ergebnis "
            "bleibt im Verlauf sichtbar.\n"
            "- Wenn keines dieser Tools passt, antworte ohne Tool-Call oder bleibe konservativ."
            f"{cql_guidance}"
            f"{confirmation_guidance}"
        )

    @staticmethod
    def _ra_tool_tokens(tc: Dict[str, Any]) -> int:
        raw_args = tc.get("function", {}).get("arguments", "{}")
        return len(json.dumps(raw_args))

    def _ra_record_tool_call_anomaly(
        self,
        kind: str,
        *,
        finish_reason: str | None = None,
        candidate_calls: List[Dict[str, Any]] | None = None,
        exposed_tools: List[str] | None = None,
        content_preview: str | None = None,
        note: str | None = None,
        analysis_family: str = "",
        allowed_tools: List[str] | None = None,
        forced_tools: List[str] | None = None,
    ) -> None:
        emitted_tools: List[str] = []
        for tc in list(candidate_calls or []):
            if not isinstance(tc, dict):
                continue
            name = str(tc.get("function", {}).get("name", "") or "").strip()
            if name:
                emitted_tools.append(name)
        record: Dict[str, Any] = {
            "kind": kind,
            "finish_reason": finish_reason or "",
            "exposed_tools": list(exposed_tools or []),
            "emitted_tools": emitted_tools,
            "route": self._last_llm_route,
            "model": self._last_llm_model,
            "analysis_family": analysis_family,
            "allowed_tools": list(allowed_tools or []),
            "forced_tools": list(forced_tools or []),
            "note": note or "",
        }
        preview = self._compact_runtime_text(content_preview or "", limit=180)
        if preview:
            record["content_preview"] = preview
        self._tool_call_anomalies.append(record)
        self._tool_call_anomalies = self._tool_call_anomalies[-12:]
        logger.warning(
            "LLM tool-call anomaly kind=%s route=%s model=%s finish=%s exposed=%s emitted=%s note=%s",
            kind,
            self._last_llm_route,
            self._last_llm_model,
            finish_reason or "",
            ",".join(record["exposed_tools"]) or "-",
            ",".join(emitted_tools) or "-",
            note or "",
        )
        if self.observability:
            self.observability.record(
                self.session.session_id,
                f"llm_tool_anomaly.{kind}",
                status="error",
            )

    def _ra_tool_specs_for_names(self, names: List[str] | None) -> List[Dict[str, Any]]:
        # Capability-unverfuegbare Werkzeuge verschwinden aus JEDER
        # Exposition (auch forced_next_tools): keine Retry-Kaskade.
        unavailable = set(self._turn_capability_unavailable_tools)
        if names is None:
            return [
                tool
                for tool in list(self.tools or [])
                if str(tool.get("function", {}).get("name", "") or "").strip()
                not in unavailable
            ]
        wanted = set(str(name or "").strip() for name in names if str(name or "").strip())
        wanted.add("deutung_abgeben")  # sonst beendet nur der Harnisch den Turn
        wanted -= unavailable
        return [
            tool
            for tool in list(self.tools or [])
            if str(tool.get("function", {}).get("name", "") or "").strip() in wanted
        ]

    def _ra_active_tool_specs(self, state: _RunTurnState) -> List[Dict[str, Any]]:
        """Tool specs exposed in the current LLM call (lifted from ``run_async``).

        ``state.forced_next_tools`` wins over ``state.active_allowed_tools``:
        when the main loop narrows the tool space to the remaining
        contract-evidence tools, only those are exposed.
        """
        if state.forced_next_tools is not None:
            return self._ra_tool_specs_for_names(state.forced_next_tools)
        return self._ra_tool_specs_for_names(state.active_allowed_tools)

    def _ra_requires_grounding_contract(self) -> bool:
        available_names = set(self._available_tool_names())
        return bool(available_names & set(GROUNDING_TRIGGER_TOOLS))

    def _ra_fallback_contract(self, question: str) -> AnalysisContract | None:
        return fallback_analysis_contract(
            question,
            available_tools=self._available_tool_names(),
            read_only_tools=self._read_only_tool_names(),
        )

    @staticmethod
    def _ra_evidence_query_args(raw_item: Dict[str, Any]) -> Dict[str, Any]:
        query = raw_item.get("query")
        if isinstance(query, dict):
            return dict(query)
        try:
            parsed = json.loads(str(query or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    @staticmethod
    def _ra_effective_evidence_scope(raw_item: Dict[str, Any]) -> Dict[str, Any]:
        if str(raw_item.get("status") or "").strip().casefold() not in {
            "",
            "success",
            "ok",
        }:
            return {}
        raw_surface = raw_item.get("raw_surface")
        raw_surface = raw_surface if isinstance(raw_surface, dict) else {}
        scope = raw_surface.get("scope")
        if not isinstance(scope, dict) or scope.get("corpus_id") in (None, ""):
            return {}
        effective = {"corpus": scope["corpus_id"]}
        if scope.get("docset_id") not in (None, ""):
            effective["docset_id"] = scope["docset_id"]
        return effective

    def _ra_normalize_same_corpus_collocation_call(
        self,
        tc: Dict[str, Any],
        *,
        contract: AnalysisContract,
        question: str,
        batch_terms: Dict[str, set[str]],
        scope_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Keep paired lexical-form calls on one method and corpus scope."""

        tool_name = str(
            tc.get("function", {}).get("name", "") or ""
        ).strip()
        if tool_name not in {"collocate_stats", "query_count"}:
            return tc
        terms = same_corpus_collocation_terms(question)
        if contract.analysis_family != "collocation" or not terms:
            return tc

        args = dict(self._tool_args(tc))
        if not scope_state.get("initialized"):
            source_args: Dict[str, Any] | None = None
            explicit_corpus = _explicit_same_corpus_id(question)
            if explicit_corpus:
                source_args = {"corpus": explicit_corpus}
            for raw_item in list(self._turn_evidence_items or []):
                if source_args is not None:
                    break
                if not isinstance(raw_item, dict) or raw_item.get("tool") not in {
                    "collocate_stats",
                    "query_count",
                }:
                    continue
                effective_scope = self._ra_effective_evidence_scope(raw_item)
                if effective_scope:
                    source_args = effective_scope
                    break
            if source_args is None:
                # A current call may seed only this batch. A failed execution is
                # never consulted by a later retry, which remains free to correct it.
                source_args = args
            scope_state.clear()
            scope_state["initialized"] = True
            for key in ("corpus", "docset_id"):
                if source_args.get(key) not in (None, ""):
                    scope_state[key] = source_args[key]

        for key in ("corpus", "docset_id"):
            if key in scope_state:
                args[key] = scope_state[key]
            else:
                args.pop(key, None)

        collocate_specs = self._ra_tool_specs_for_names(["collocate_stats"])
        method = _same_corpus_collocation_method(
            question,
            collocate_specs[0] if collocate_specs else None,
        )
        completed: set[str] = set()
        for raw_item in list(self._turn_evidence_items or []):
            if not isinstance(raw_item, dict) or raw_item.get("tool") != tool_name:
                continue
            if str(raw_item.get("status") or "").strip().casefold() == "error":
                continue
            raw_surface = raw_item.get("raw_surface")
            raw_surface = raw_surface if isinstance(raw_surface, dict) else {}
            prior_args = self._ra_evidence_query_args(raw_item)
            effective_scope = self._ra_effective_evidence_scope(raw_item)
            if any(
                effective_scope.get(key) != scope_state.get(key)
                for key in ("corpus", "docset_id")
                if effective_scope.get(key) not in (None, "")
                or scope_state.get(key) not in (None, "")
            ):
                continue
            if tool_name == "collocate_stats":
                rows_complete = isinstance(raw_surface.get("rows"), list)
                zero_complete = raw_surface.get("result_count") == 0
                if not rows_complete and not zero_complete:
                    continue
                raw_method = raw_surface.get("method")
                raw_method = raw_method if isinstance(raw_method, dict) else {}
                effective = {
                    "attribute": str(
                        raw_method.get("attribute")
                        or prior_args.get("attribute")
                        or "word"
                    ).casefold(),
                    "window": raw_surface.get(
                        "window", prior_args.get("window", 5)
                    ),
                    "within_sentence": raw_surface.get(
                        "within_sentence",
                        prior_args.get("within_sentence", True),
                    ),
                    "min_freq": raw_surface.get(
                        "min_freq", prior_args.get("min_freq", 5)
                    ),
                    "sort_by": str(
                        raw_surface.get("sort_by")
                        or prior_args.get("sort_by")
                        or "logdice"
                    ).casefold(),
                }
                try:
                    method_matches = (
                        effective["attribute"] == method["attribute"]
                        and int(effective["window"]) == method["window"]
                        and _collocation_bool_value(effective["within_sentence"])
                        is method["within_sentence"]
                        and int(effective["min_freq"]) == method["min_freq"]
                        and effective["sort_by"] == method["sort_by"]
                    )
                except (TypeError, ValueError):
                    method_matches = False
                if not method_matches:
                    continue
                node = _plain_lexical_node(
                    raw_surface.get("requested_term")
                    or prior_args.get("term")
                )
            else:
                if raw_surface.get("total") in (None, ""):
                    continue
                count_attribute, node = _lexical_count_node(
                    prior_args.get("query") or raw_surface.get("query")
                )
                if count_attribute != method["attribute"]:
                    continue
            if node:
                completed.add(node.lower())

        proposed = _plain_lexical_node(
            args.get("term") if tool_name == "collocate_stats" else args.get("query")
        )
        # Use str.lower like the counter so daß and dass remain separate nodes.
        requested_by_key = {term.lower(): term for term in terms}
        seen = completed | batch_terms[tool_name]
        proposed_key = proposed.lower()
        missing = [
            term for term in terms if term.lower() not in seen
        ]
        if proposed_key in requested_by_key and proposed_key not in seen:
            selected = requested_by_key[proposed_key]
        elif missing:
            selected = missing[0]
        elif proposed_key in requested_by_key:
            selected = requested_by_key[proposed_key]
        else:
            selected = terms[0]
        batch_terms[tool_name].add(selected.lower())

        if tool_name == "collocate_stats":
            args["term"] = selected
            args.update(method)
        else:
            if method["attribute"] == "lemma":
                escaped = selected.replace("\\", "\\\\").replace('"', '\\"')
                args["query"] = f'[lemma="{escaped}" %c]'
            else:
                args["query"] = selected
            args["case_insensitive"] = True

        return {
            **tc,
            "function": {
                **dict(tc.get("function", {}) or {}),
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        }

    def _ra_pending_required_evidence_tools(
        self, contract: AnalysisContract, allowed_tools: List[str] | None
    ) -> Tuple[List[str], List[str]]:
        """Delegiert an recipe_runtime; Deutungspfad s. F-66 dort."""
        # F-66: Deutungspfad ohne jede Evidenz -> Pflicht-Toolrunde erzwingen
        # (Lookups ausgenommen); der bestehende Retry-Flow deckelt sich selbst.
        if deutungspfad_aktiv() and not self._turn_evidence_items and getattr(contract, "deliverable_kind", "") in DEUTUNG_LIEFERARTEN:
            erlaubt = list(allowed_tools or [])
            sinnvoll = [tl for k in ("metric_rows", "content_rows", "frequency_rows", "kwic_rows") for tl in _EVIDENCE_TO_TOOLS.get(k, ()) if tl in erlaubt]
            return (sinnvoll or erlaubt)[:4], ["Werkzeug-Evidenz fuer die Deutung"]
        return pending_required_evidence_tools(
            contract, allowed_tools,
            turn_evidence_items=list(self._turn_evidence_items or []),
            capability_unavailable_tools=self._turn_capability_unavailable_tools,
            evidence_to_tools=_EVIDENCE_TO_TOOLS,
        )

    def _ra_append_blocked_tool_result(
        self,
        copilot_event_bus: Any,
        question: str,
        tc: Dict[str, Any],
        check: Dict[str, Any],
    ) -> None:
        name = str(tc["function"]["name"])
        args = self._tool_args(tc)
        signature = self._tool_signature(tc)
        self._record_tool_outcome(
            name,
            args,
            check,
            ok=False,
            signature=signature,
        )
        tool_result = {
            "toolName": name,
            "ok": False,
            "ts": int(time.time() * 1000),
            "input": args,
            "output": check,
        }
        self._emit_output(copilot_event_bus, {"event": "copilot.tool_result", "toolResult": tool_result})
        self.session.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(check),
            },
            project=self.project,
        )
        self._ra_refresh_session_state(question)
        self.session.summarise(
            project=self.project,
            runtime_state=self._build_runtime_state(question),
        )

    def _ra_append_reused_tool_result(
        self,
        copilot_event_bus: Any,
        question: str,
        tc: Dict[str, Any],
        output: Any,
    ) -> None:
        """Satisfy an identical read-only call without recomputing it."""

        name = str(tc["function"]["name"])
        args = self._tool_args(tc)
        cached_output = copy.deepcopy(output)
        tool_result = {
            "toolName": name,
            "ok": True,
            "reused": True,
            "ts": int(time.time() * 1000),
            "input": args,
            "output": cached_output,
        }
        self._emit_output(
            copilot_event_bus,
            {"event": "copilot.tool_result", "toolResult": tool_result},
        )
        self.session.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(
                    _tool_output_for_model(cached_output, werkzeug=name),
                    ensure_ascii=False,
                ),
            },
            project=self.project,
        )
        self._ra_refresh_session_state(question)
        self.session.summarise(
            project=self.project,
            runtime_state=self._build_runtime_state(question),
        )

    def _ra_append_skipped_tool_result(
        self,
        copilot_event_bus: Any,
        question: str,
        tc: Dict[str, Any],
        *,
        reason: str,
        message: str,
    ) -> None:
        """Close a redundant call ID without recording a failed computation."""

        name = str(tc["function"]["name"])
        output = {"status": "skipped", "reason": reason, "message": message}
        tool_result = {
            "toolName": name,
            "ok": True,
            "skipped": True,
            "ts": int(time.time() * 1000),
            "input": self._tool_args(tc),
            "output": output,
        }
        self._emit_output(
            copilot_event_bus,
            {"event": "copilot.tool_result", "toolResult": tool_result},
        )
        self.session.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(output, ensure_ascii=False),
            },
            project=self.project,
        )
        self._ra_refresh_session_state(question)
        if self.observability:
            self.observability.record(
                self.session.session_id,
                f"{name}.reused",
                status="ok",
            )

    def _ra_flush_research_updates(self, copilot_event_bus: Any, question: str) -> None:
        self._harvest_research_tasks()
        changed = False
        for run in self._research_runs:
            status = str(run.get("status", "") or "")
            if status not in {"complete", "error", "cancelled"}:
                continue
            if run.get("reported_at"):
                continue
            run["reported_at"] = int(time.time() * 1000)
            changed = True
            if status == "complete":
                self._remember_research_summaries(list(run.get("summaries", []) or [])[:3], run=run)
                self._ra_emit_research_event(
                    copilot_event_bus,
                    run,
                    "ready",
                    findings=int(run.get("findings", 0) or 0),
                    summaries=list(run.get("summaries", []) or [])[:3],
                    tools=list(run.get("tools", []) or [])[:4],
                )
            else:
                self._ra_emit_research_event(
                    copilot_event_bus,
                    run,
                    status,
                    message=self._compact_runtime_text(run.get("message", ""), limit=180),
                )
        if changed:
            self._ra_refresh_session_state(question)

    def _ra_attach_research_run(
        self,
        copilot_event_bus: Any,
        question: str,
        run: Dict[str, Any],
        *,
        phase: str = "resume",
        status_hint: str = "",
    ) -> bool:
        self._bind_research_run_to_current_turn(run)
        summaries = [
            self._compact_runtime_text(item, limit=220)
            for item in list(run.get("summaries", []) or [])[:3]
            if self._compact_runtime_text(item, limit=220)
        ]
        if not summaries and status_hint not in {"running", "queued"}:
            return False
        attached_at = int(time.time() * 1000)
        run["attached_at"] = attached_at
        run["attachments"] = int(run.get("attachments", 0) or 0) + 1
        run["updated_at"] = attached_at
        self._remember_research_summaries(summaries, run=run)
        self._ra_refresh_session_state(question)
        self._ra_emit_research_event(
            copilot_event_bus,
            run,
            phase,
            status=status_hint or str(run.get("status", "") or ""),
            findings=int(run.get("findings", 0) or 0),
            summaries=summaries,
            tools=list(run.get("tools", []) or [])[:4],
        )
        return True

    def _ra_reuse_recent_research_run(
        self, copilot_event_bus: Any, question: str, role: str
    ) -> bool:
        if not self._should_run_research_worker(question, role):
            return False
        existing = self._find_recent_research_run()
        if existing is None:
            return False

        status = str(existing.get("status", "") or "")
        if status in {"queued", "running"}:
            return self._ra_attach_research_run(
                copilot_event_bus, question, existing, phase="resume", status_hint=status
            )

        if status in {"complete", "attached"}:
            return self._ra_attach_research_run(
                copilot_event_bus, question, existing, phase="resume", status_hint="complete"
            )
        return False

    async def _ra_run_research_worker(
        self,
        run_id: str,
        *,
        copilot_event_bus: Any,
        question: str,
        role: str,
        principal: str,
        dispatch_is_async: bool,
    ) -> None:
        if self.cancel_requested:
            return
        if not self._should_run_research_worker(question, role):
            return

        tool_calls = self._build_research_tool_calls(question)
        if not tool_calls:
            return
        run = self._find_research_run_by_id(run_id)
        if run is None:
            return
        run["status"] = "running"
        run["tools"] = [tc["function"]["name"] for tc in tool_calls]
        run["updated_at"] = int(time.time() * 1000)
        self._ra_refresh_session_state(question)

        self._ra_emit_research_event(
            copilot_event_bus,
            run,
            "start",
            tools=[tc["function"]["name"] for tc in tool_calls],
        )

        async def _dispatch_research(tc: Dict[str, Any]) -> None:
            if self.cancel_requested:
                return
            name = str(tc["function"]["name"])
            args = self._tool_args(tc)
            signature = self._tool_signature(tc)
            tokens = self._ra_tool_tokens(tc)
            start = time.perf_counter()
            try:
                if self.policy:
                    check = self.policy.check(principal, name, tokens)
                    if check.get("status") != "ok":
                        out = check
                        raise PermissionError(str(check.get("message", "policy denied")))
                if dispatch_is_async:
                    out = await self.dispatch(tc, self.token)
                else:
                    out = await asyncio.to_thread(self.dispatch, tc, self.token)
                vermerke_abgabe(self, name, out)
            except Exception as exc:  # pragma: no cover - defensive fallback
                out = {"status": "error", "message": str(exc)}
            out = werkzeugausgabe_ohne_betreiberpfad(mit_folgenbereich(name, mit_fassungsverteilung(name, out)))

            if self.cancel_requested:
                return

            duration = (time.perf_counter() - start) * 1000
            ok = not (isinstance(out, dict) and out.get("status") == "error")
            self._record_tool_outcome(
                name,
                args,
                out,
                ok=ok,
                signature=signature,
            )
            if ok:
                finding = self._compact_runtime_text(
                    f"{name}: {out}",
                    limit=220,
                )
                if finding:
                    self._remember_research_summaries([finding], run=run)
                    run["findings"] = int(run.get("findings", 0) or 0) + 1
                    run.setdefault("summaries", []).append(finding)
                    run["summaries"] = list(run.get("summaries", []) or [])[-4:]
            self._ra_emit_research_event(
                copilot_event_bus,
                run,
                "result",
                tool=name,
                ok=ok,
                summary=self._compact_runtime_text(out, limit=240),
            )
            if self.observability:
                self.observability.record(
                    self.session.session_id,
                    f"research.{name}",
                    tokens=tokens,
                    duration_ms=duration,
                    status="ok" if ok else "error",
                )

        await asyncio.gather(*[_dispatch_research(tc) for tc in tool_calls])
        if self.cancel_requested:
            run["status"] = "cancelled"
            run["updated_at"] = int(time.time() * 1000)
            self._ra_refresh_session_state(question)
            return
        run["status"] = "complete"
        run["updated_at"] = int(time.time() * 1000)
        self._ra_refresh_session_state(question)
        self._ra_emit_research_event(
            copilot_event_bus,
            run,
            "complete",
            count=len(tool_calls),
            findings=int(run.get("findings", 0) or 0),
        )

    def _ra_launch_research_worker(
        self,
        copilot_event_bus: Any,
        question: str,
        role: str,
        principal: str,
        *,
        dispatch_is_async: bool,
    ) -> None:
        if not self._should_run_research_worker(question, role):
            return
        if self._ra_reuse_recent_research_run(copilot_event_bus, question, role):
            return
        context_payload = self._research_context_payload(question)
        run_id = f"research_{uuid.uuid4().hex[:8]}"
        dependencies = self._collect_research_context_closure(
            self._get_explicit_research_context_tags()
        )
        run = {
            "id": run_id,
            "query": context_payload.get("query", self._research_query(question)),
            "dependencies": dependencies,
            "context": context_payload,
            "status": "queued",
            "started_at": int(time.time() * 1000),
            "updated_at": int(time.time() * 1000),
            "findings": 0,
            "tools": [],
            "summaries": [],
        }
        self._research_runs.append(run)
        self._research_runs = self._research_runs[-8:]
        self._bind_research_run_to_current_turn(run)
        task = asyncio.create_task(
            self._ra_run_research_worker(
                run_id,
                copilot_event_bus=copilot_event_bus,
                question=question,
                role=role,
                principal=principal,
                dispatch_is_async=dispatch_is_async,
            )
        )
        self._active_research_tasks[run_id] = task
        self._ra_refresh_session_state(question)

    @staticmethod
    def _ra_build_fail_closed_grounding_markdown(reason: str) -> str:
        limitation = reason or (
            "Die evidenzgebundene Analyse konnte nicht sicher initialisiert werden."
        )
        return "\n".join(
            [
                "Ich kann diese Analyse gerade nicht sicher tool-gestützt beantworten.",
                "",
                "Limitationen:",
                f"- {limitation}",
                "- Es liegt keine belegbare Tool-Evidenz für eine Analyse vor.",
            ]
        ).strip()

    @staticmethod
    def _ra_build_grounding_messages(doc: str, payload: Dict[str, Any]) -> List[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    f"{doc}\n\n"
                    "Nutze nur die übergebene Evidenz. "
                    "Antworte ausschließlich als JSON gemäß Schema."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]

    def _ra_activate_fail_closed_grounding(
        self,
        state: _RunTurnState,
        copilot_event_bus: Any,
        question: str,
        kind: str,
        message: str,
    ) -> None:
        """Fail-closed grounding writer lifted from ``run_async``.

        Writes ``state.fail_closed_grounding_kind`` / ``..._reason`` (formerly
        ``nonlocal``); ``question`` is the normalized question of the turn.
        """
        # review.reason ist Modelltext und laeuft von hier in drei
        # Ereignisse und zurueck in den Prompt.
        message = kontrollrahmen_bewacht(
            {"note": message}, list(self._turn_evidence_items or ()), frage=getattr(self, "_turn_frage", ""))["note"]
        state.fail_closed_grounding_kind = kind
        state.fail_closed_grounding_reason = message
        self._evidence_gaps = self._dedupe_ordered_strs(
            list(self._evidence_gaps) + [message]
        )[-6:]
        self._last_grounding_verdict = {
            "verdict": "conservative_only",
            "accepted_claim_ids": [],
            "rejected_claim_ids": [],
            "reasons": [message],
            "needs_retry": False,
        }
        self._active_analysis_contract = {
            "mode": "tool_analysis",
            "analysis_family": "contract_failed_closed",
            "question_scope": question,
            "allowed_tools": [],
            "required_evidence": [],
            "forbidden_claims": [],
            "response_shape": "conservative_only",
            "needs_clarification": False,
            "clarification_question": "",
            "grounding_verdict": "conservative_only",
            "contract_status": "failed_closed",
            "contract_failure_kind": kind,
        }
        self._ra_refresh_session_state(question)
        self._ra_emit_recovery(copilot_event_bus, question, kind, message)
        self._ra_emit_grounding_event(
            copilot_event_bus,
            "conservative_only",
            analysis_family="contract_failed_closed",
            evidence_gaps=self._evidence_gaps,
        )

    @staticmethod
    def _ra_consume_retry_budget(state: _RunTurnState) -> bool:
        """Transport-Retry-Budget. Modellstoerungen laufen NICHT hierueber,
        sie haben ihr eigenes Zaehlwerk (_ENGINE_STOERUNGEN_JE_TURN)."""
        if state.retries_used >= _budgets.TRANSPORT_RETRY_LIMIT:
            return False
        if not _budgets.retry_time_remaining_ok(state.started_at, state.max_time):
            return False
        state.retries_used += 1
        return True

    def _ra_emit_status(
        self,
        copilot_event_bus: Any,
        stage: str,
        detail: str = "",
    ) -> None:
        """Sichtbarer Fortschritt (K1): ``copilot.status``-Event pro Stufe.

        Stufen: ``Werkzeuge`` (Tool-Batch laeuft), ``Verifikation``
        (Grounding-Verifikation), ``Antwort`` (finale Synthese). Der
        SSE-Vertrag ist in docs (candyconc-web SSE contract) dokumentiert.
        ``recipe_id`` nennt das aktive Analyse-Rezept (leer = freier Modus).
        """
        # A2: dieselbe Naht, die dem Frontend die Stufe meldet, merkt sie
        # sich auch. Zwei Quellen fuer "welche Stufe laeuft" wuerden frueher
        # oder spaeter auseinanderlaufen.
        self._aktuelle_stufe = str(stage or "")
        payload: Dict[str, Any] = {"event": "copilot.status", "stage": stage}
        if detail:
            payload["detail"] = detail
        payload["recipe_id"] = self._active_recipe_id or ""
        # Sekunden seit Turnbeginn. Eine Wanduhrzeit waere von der Uhr des
        # Browsers abhaengig, eine Dauer je Stufe koennte der Server nicht
        # liefern, weil er das Ende der Stufe erst beim naechsten Wechsel
        # kennt. Die Marke reicht: aufeinanderfolgende Marken ergeben die
        # Dauer, und ``elapsed_s`` aus copilot.done schliesst die letzte.
        beginn = getattr(self, "_turn_start_perf", 0.0)
        if beginn:
            payload["t_rel"] = round(time.perf_counter() - float(beginn), 3)
        # Fortschritt fuer den Balken, im selben Ereignis. Gezaehlt werden
        # erfolgreiche Werkzeuglaeufe gegen das Schrittbudget: der einzige
        # Takt, den ein Turn wirklich hat. Die Rechnung steht in
        # copilot_sessions.fortschrittsanteil, siehe dort.
        from candyconc.services.backend.copilot_sessions import (
            fortschrittsanteil as _anteil,
        )

        _fortschritt = _anteil(
            len(list(self._turn_evidence_items or [])),
            int(getattr(self, "_turn_max_steps", 0) or 0),
        )
        if _fortschritt:
            payload["fortschritt"] = _fortschritt
        self._emit_output(copilot_event_bus, payload)

    async def _ra_recover_llm_error(
        self,
        state: _RunTurnState,
        copilot_event_bus: Any,
        question: str,
        normalized_question: str,
        role: str,
        error: LLMRequestError,
        attempt: int,
    ) -> bool:
        """LLM-error recovery writer lifted from ``run_async``.

        Engine and generic retries consume the transport retry budget. Context
        repairs remain separate because they change the request instead of
        repeating an identical failed transport.

        Reads and writes the recovery budgets on ``state``
        (``microcompact_count``, ``context_recovery_count``,
        ``output_resume_count``), formerly ``nonlocal`` counters.  ``question``
        is the raw turn question (used for ``session.search``),
        ``normalized_question`` the stripped one (used for runtime state).
        """
        if error.kind == LLMErrorKind.CONTEXT_WINDOW_EXCEEDED:
            if state.microcompact_count < 2:
                compacted = self.session.microcompact(keep_last_messages=6)
                if compacted:
                    state.microcompact_count += 1
                    self._ra_refresh_session_state(normalized_question)
                    if normalized_question and role == "user":
                        self.session.search(question)
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        normalized_question,
                        "microcompact",
                        lt("Aeltere Tool-Ausgaben wurden lokal verdichtet und der LLM-Aufruf wird wiederholt.",
                           "Older tool outputs were compacted locally and the model call is repeated."),
                        error=error,
                    )
                    return True
            if state.context_recovery_count >= 2:
                return False
            compacted = self.session.force_compact(
                project=self.project,
                reason="Kontextfenster überschritten",
                keep_last_messages=6,
                runtime_state=self._build_runtime_state(normalized_question),
            )
            if not compacted:
                return False
            state.context_recovery_count += 1
            if normalized_question and role == "user":
                self.session.search(question)
            self._ra_emit_recovery(
                copilot_event_bus,
                normalized_question,
                "context_compact",
                lt("Der Verlauf wurde aggressiv komprimiert und der LLM-Aufruf wird wiederholt.",
                   "The history was compacted aggressively and the model call is repeated."),
                error=error,
            )
            return True

        if error.kind == LLMErrorKind.MAX_OUTPUT_TOKENS and state.output_resume_count < 2:
            self.session.append(
                {
                    "role": "user",
                    "content": (
                        "[System note: Die vorherige Anfrage ist am Ausgabelimit "
                        "gescheitert. Antworte kürzer, nenne zuerst das wichtigste "
                        "Ergebnis und führe nur fort, wenn unbedingt nötig.]"
                    ),
                },
                project=self.project,
            )
            state.output_resume_count += 1
            self._ra_refresh_session_state(normalized_question)
            self.session.summarise(
                project=self.project,
                runtime_state=self._build_runtime_state(normalized_question),
            )
            self._ra_emit_recovery(
                copilot_event_bus,
                normalized_question,
                "max_output_tokens",
                lt("Der LLM-Pfad hat das Ausgabelimit nicht akzeptiert. Der Aufruf wird mit kürzerer Anschlussanweisung wiederholt.",
                   "The model endpoint did not accept the output limit. The call is repeated with a shorter continuation instruction."),
                error=error,
            )
            return True

        if (
            _ist_modellstoerung(error)
            and state.engine_retry_count < _ENGINE_STOERUNGEN_JE_TURN
            and _budgets.engine_retry_time_ok(state.started_at, state.max_time)
        ):
            delay = _ENGINE_RETRY_DELAYS[
                min(state.engine_retry_count, len(_ENGINE_RETRY_DELAYS) - 1)]
            state.engine_retry_count += 1
            self._ra_vergiss_fortsetzung()
            self._ra_emit_recovery(
                copilot_event_bus,
                normalized_question,
                "engine_wait",
                lt(
                    "Die Modell-Engine ist nicht erreichbar oder das Modell "
                    "wurde neu geladen. Der Turn wartet auf dasselbe Modell "
                    "und wiederholt denselben Aufruf, die gesammelte Evidenz "
                    "bleibt. CandyConc lädt oder wechselt kein Modell.",
                    "The model engine is not reachable or the model was "
                    "reloaded. The turn waits for the same model and repeats "
                    "the same call, the collected evidence is kept. CandyConc "
                    "does not load or switch models.",
                ),
                error=error,
            )
            await self._ra_wait_with_cancellation(delay)
            await self._ra_warte_auf_modell(state)
            return True

        if (
            error.retryable
            and attempt < self.llm_retries
            and self._ra_consume_retry_budget(state)
        ):
            delay = self._llm_retry_delay(error, attempt)
            self._ra_emit_recovery(
                copilot_event_bus,
                normalized_question,
                "llm_retry",
                lt("{message} Neuer Versuch in {delay:.1f}s.",
                   "{message} Retrying in {delay:.1f}s.").format(message=error.message, delay=delay),
                error=error,
            )
            await self._ra_wait_with_cancellation(delay)
            return True

        return False

    def _ra_filter_tool_calls(
        self,
        candidate_calls: List[Dict[str, Any]],
        *,
        copilot_event_bus: Any,
        question: str,
        principal: str,
        active_contract: "AnalysisContract | None",
        active_allowed_tools: List[str] | None,
        forced_next_tools: List[str] | None,
    ) -> List[Tuple[Dict[str, Any], int]]:
        """Tool-call gate lifted from ``run_async``.

        Filters model-emitted tool calls against (in order): the tool space
        actually exposed in the current LLM call (``forced_next_tools`` wins
        over ``active_allowed_tools``), the active analysis contract's bundle,
        previously failed identical calls, and the policy engine.  Blocked
        calls get synthetic error tool-results appended; ``question`` is the
        normalized question of the turn.
        """
        allowed: List[Tuple[Dict[str, Any], int]] = []
        allowed_tool_set = set(active_allowed_tools or [])
        exposed_specs = self._ra_tool_specs_for_names(
            forced_next_tools if forced_next_tools is not None else active_allowed_tools
        )
        exposed_tool_set = {
            str(spec.get("function", {}).get("name", "") or "").strip()
            for spec in exposed_specs
            if isinstance(spec, dict)
        }
        confirmation_pressure = bool(
            active_contract is not None
            and "one-sided confirmation of a universal corpus claim"
            in {
                str(value or "").strip().casefold()
                for value in list(active_contract.forbidden_claims or [])
            }
        )
        comparison_batch_terms: Dict[str, set[str]] = {
            "collocate_stats": set(),
            "query_count": set(),
        }
        comparison_scope_state: Dict[str, Any] = {}
        lauf_signaturen: set[str] = set()
        for tc in candidate_calls:
            tool_name = str(tc.get("function", {}).get("name", "") or "").strip()
            if tool_name and tool_name not in exposed_tool_set:
                self._ra_record_tool_call_anomaly(
                    "tool_name_not_exposed",
                    finish_reason="tool_calls",
                    candidate_calls=[tc],
                    exposed_tools=sorted(exposed_tool_set),
                    note="Das Modell hat einen Tool-Namen emittiert, der im aktuellen Aufruf nicht exponiert war.",
                    analysis_family=str((active_contract.analysis_family if active_contract else "") or ""),
                    allowed_tools=active_allowed_tools,
                    forced_tools=forced_next_tools,
                )
                self._ra_append_blocked_tool_result(
                    copilot_event_bus,
                    question,
                    tc,
                    {
                        "status": "error",
                        "reason": "tool_not_exposed",
                        "message": (
                            "Dieser Tool-Name war im aktuellen LLM-Aufruf nicht exponiert "
                            "und wurde blockiert."
                        ),
                        "exposed_tools": sorted(exposed_tool_set),
                    },
                )
                continue
            if active_contract is not None:
                # Der Ausgang des MODELLS gehoert zu keinem Analyse-Bundle.
                if not tool_name or (tool_name not in allowed_tool_set
                                     and tool_name != "deutung_abgeben"):
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        question,
                        "tool_bundle_violation",
                        lt(
                            "Ein Tool-Call ausserhalb des Analysevertrags wurde blockiert. "
                            "Nutze nur das freigegebene Tool-Bundle.",
                            "A tool call outside the analysis contract was blocked. "
                            "Use only the released tool bundle.",
                        ),
                    )
                    self._ra_append_blocked_tool_result(
                        copilot_event_bus,
                        question,
                        tc,
                        {
                            "status": "error",
                            "reason": "tool_bundle_violation",
                            "message": (
                                "Dieser Tool-Call liegt ausserhalb des aktiven "
                                "Analysevertrags und wurde blockiert."
                            ),
                            "allowed_tools": list(active_allowed_tools or []),
                            "analysis_family": active_contract.analysis_family,
                        },
                    )
                    continue
                if (
                    active_contract.analysis_family == "open_research"
                    and tool_name in _SEARCH_ANCHOR_TOOLS
                ):
                    search_anchor = _tool_search_anchor(tc)
                    if not _search_anchor_is_grounded(
                        search_anchor,
                        question=question,
                        evidence_items=list(self._turn_evidence_items or []),
                    ):
                        self._ra_record_tool_call_anomaly(
                            "ungrounded_search_anchor",
                            finish_reason="tool_calls",
                            candidate_calls=[tc],
                            exposed_tools=sorted(exposed_tool_set),
                            note=(
                                "Ein explorativer Suchanker war weder in der "
                                "Nutzerfrage noch in sichtbarer lexikalischer "
                                "Evidenz verankert."
                            ),
                            analysis_family=active_contract.analysis_family,
                            allowed_tools=active_allowed_tools,
                            forced_tools=forced_next_tools,
                        )
                        self._ra_append_blocked_tool_result(
                            copilot_event_bus,
                            question,
                            tc,
                            {
                                "status": "error",
                                "reason": "ungrounded_search_anchor",
                                "message": (
                                    "Der Suchanker ist nicht durch die "
                                    "Nutzerfrage oder sichtbare lexikalische "
                                    "Evidenz motiviert. Nutze zuerst eine "
                                    "inhaltstragende Frequenzanalyse oder einen "
                                    "bereits sichtbaren Begriff."
                                ),
                                "allowed_search_anchors": (
                                    _grounded_search_anchor_candidates(
                                        question,
                                        list(self._turn_evidence_items or []),
                                    )
                                ),
                            },
                        )
                        continue
                if confirmation_pressure and tool_name == "semantic_search":
                    semantic_args = dict(self._tool_args(tc))
                    semantic_term = str(
                        semantic_args.get("term") or ""
                    ).strip()
                    parsed_question_hypothesis = (
                        _fallback_hypothesis_from_clause_structure(
                            _universal_hypothesis_clause(question)
                        )
                    )
                    question_topic = (
                        parsed_question_hypothesis[0]
                        if parsed_question_hypothesis is not None
                        else ""
                    )
                    asserted_property = (
                        parsed_question_hypothesis[1]
                        if parsed_question_hypothesis is not None
                        else ""
                    )
                    question_topic_tokens = _search_anchor_tokens(
                        question_topic
                    )
                    asserted_property_tokens = _search_anchor_tokens(
                        asserted_property
                    )
                    semantic_term_tokens = _search_anchor_tokens(
                        semantic_term
                    )
                    term_uses_asserted_property = bool(
                        semantic_term_tokens & asserted_property_tokens
                    )
                    prior_topic_anchor = _confirmation_retrieval_anchor(
                        candidate_calls,
                        list(self._turn_evidence_items or []),
                        semantic_term,
                        target_topic=question_topic,
                        asserted_property=asserted_property,
                    )
                    neutral_anchor = prior_topic_anchor
                    if not neutral_anchor and question_topic_tokens and (
                        question_topic_tokens < semantic_term_tokens
                        or term_uses_asserted_property
                    ):
                        neutral_anchor = question_topic
                    if neutral_anchor:
                        semantic_args["term"] = neutral_anchor
                        tc = {
                            **tc,
                            "function": {
                                **dict(tc.get("function", {}) or {}),
                                "arguments": json.dumps(
                                    semantic_args,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        self._ra_emit_recovery(
                            copilot_event_bus,
                            question,
                            "confirmation_retrieval_debiased",
                            lt(
                                "semantic_search: Der Suchtext wurde auf den "
                                "bereits wörtlich geprüften Gegenstandsanker "
                                "{anchor} begrenzt, damit das "
                                "gewünschte Ergebnis die Kandidatenauswahl "
                                "nicht vorselektiert.",
                                "semantic_search: The search text was limited to "
                                "the subject anchor {anchor}, already checked "
                                "verbatim, so that the desired result does not "
                                "preselect the candidates.",
                            ).format(anchor=repr(neutral_anchor)),
                        )
                if (
                    active_contract.analysis_family == "contrast_keyness"
                    and tool_name == "keyness"
                ):
                    successful_docset_ids = {
                        str(
                            dict(item.get("raw_surface") or {}).get("docset_id")
                            or ""
                        ).strip()
                        for item in list(self._turn_evidence_items or [])
                        if isinstance(item, dict)
                        and item.get("tool") == "create_docset"
                        and str(item.get("status") or "").strip().lower()
                        == "success"
                        and str(
                            dict(item.get("raw_surface") or {}).get("docset_id")
                            or ""
                        ).strip()
                    }
                    if len(successful_docset_ids) < 2:
                        self._ra_record_tool_call_anomaly(
                            "keyness_before_two_live_docsets",
                            finish_reason="tool_calls",
                            candidate_calls=[tc],
                            exposed_tools=sorted(exposed_tool_set),
                            note=(
                                "Keyness wurde blockiert, weil noch keine zwei "
                                "erfolgreich erzeugten Docsets mit konkreten IDs "
                                "vorlagen."
                            ),
                            analysis_family=active_contract.analysis_family,
                            allowed_tools=active_allowed_tools,
                            forced_tools=forced_next_tools,
                        )
                        self._ra_append_blocked_tool_result(
                            copilot_event_bus,
                            question,
                            tc,
                            {
                                "status": "error",
                                "reason": "keyness_before_two_live_docsets",
                                "message": (
                                    "Keyness benötigt zwei zuvor erfolgreich "
                                    "erzeugte Docsets mit konkreten IDs. Erzeuge "
                                    "zuerst beide Vergleichsscopes."
                                ),
                            },
                        )
                        continue
                if tool_name in {"collocate_stats", "query_count"}:
                    original_args = dict(self._tool_args(tc))
                    tc = self._ra_normalize_same_corpus_collocation_call(
                        tc,
                        contract=active_contract,
                        question=question,
                        batch_terms=comparison_batch_terms,
                        scope_state=comparison_scope_state,
                    )
                    normalized_args = dict(self._tool_args(tc))
                    if normalized_args != original_args:
                        self._ra_emit_recovery(
                            copilot_event_bus,
                            question,
                            "collocation_comparison_locked",
                            lt(
                                "{tool}: Die Vergleichsberechnung wurde "
                                "auf die angeforderten Wortformen, einen "
                                "gemeinsamen Korpus-Scope und identische "
                                "Methodenparameter festgelegt.",
                                "{tool}: The comparison was fixed to the "
                                "requested word forms, one shared corpus scope "
                                "and identical method parameters.",
                            ).format(tool=tool_name),
                        )
            if tool_name == "run_cqlf_query":
                exact_query = _exact_cql_from_question(question)
                query_args = dict(self._tool_args(tc))
                if exact_query and query_args.get("query") != exact_query:
                    # A verbatim query request is data, not a request for NL→CQL
                    # translation. Execute the literal so parser diagnostics
                    # cannot be replaced by hits from a silently repaired query.
                    query_args["query"] = exact_query
                    tc = {
                        **tc,
                        "function": {
                            **dict(tc.get("function", {}) or {}),
                            "arguments": json.dumps(
                                query_args,
                                ensure_ascii=False,
                            ),
                        },
                    }
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        question,
                        "exact_query_preserved",
                        lt(
                            "run_cqlf_query: Die ausdrücklich wörtlich "
                            "angegebene CQLF-Abfrage wurde unverändert an den "
                            "Parser weitergegeben.",
                            "run_cqlf_query: The query given verbatim was passed "
                            "to the parser unchanged.",
                        ),
                    )
                if (
                    confirmation_pressure
                    and active_contract is not None
                    and active_contract.analysis_family == "open_research"
                    and not _question_sets_kwic_context(question)
                ):
                    try:
                        current_context = int(query_args.get("ctx", 0) or 0)
                    except (TypeError, ValueError):
                        current_context = 0
                    if current_context < _CONFIRMATION_KWIC_CONTEXT_MIN:
                        # Confirmation-sensitive interpretation needs enough
                        # local syntax to keep participants and predicates
                        # attached. This changes only the evidence window, not
                        # the user's query or the set of returned matches.
                        query_args["ctx"] = _CONFIRMATION_KWIC_CONTEXT_MIN
                        tc = {
                            **tc,
                            "function": {
                                **dict(tc.get("function", {}) or {}),
                                "arguments": json.dumps(
                                    query_args,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        self._ra_emit_recovery(
                            copilot_event_bus,
                            question,
                            "confirmation_context_expanded",
                            lt(
                                "run_cqlf_query: Das lokale Belegfenster wurde "
                                "auf {n} Tokens "
                                "erweitert, damit Satzrollen und Anbindungen "
                                "für die kritische Hypothesenprüfung sichtbar "
                                "bleiben.",
                                "run_cqlf_query: The local context window was "
                                "widened to {n} tokens so that sentence roles "
                                "and attachments stay visible for the critical "
                                "test of the hypothesis.",
                            ).format(n=_CONFIRMATION_KWIC_CONTEXT_MIN),
                        )
            if tool_name == "frequency_list":
                frequency_args = dict(self._tool_args(tc))
                forced_content_repair = False
                if (
                    active_contract is not None
                    and forced_next_tools == ["frequency_list"]
                    and active_contract.analysis_family == "open_research"
                ):
                    evidence_items = [
                        EvidenceItem(**dict(item))
                        for item in list(self._turn_evidence_items or [])
                        if isinstance(item, dict)
                    ]
                    forced_content_repair = (
                        "content_rows"
                        in build_evidence_bundle(
                            active_contract,
                            evidence_items,
                        ).missing_required_evidence
                    )
                if (
                    forced_content_repair
                    and not frequency_parameters_supply_content_rows(
                        group_by=frequency_args.get("group_by", "word"),
                        pos=frequency_args.get("pos"),
                    )
                ):
                    # The model selected the right tool, but this argument
                    # shape cannot produce the evidence the forced step exists
                    # to collect. Preserve word/lemma where possible and repair
                    # only the missing content-word restriction.
                    group_by = str(
                        frequency_args.get("group_by", "word") or "word"
                    ).strip().casefold()
                    frequency_args["group_by"] = (
                        group_by
                        if group_by in {"word", "lemma"}
                        else "word"
                    )
                    frequency_args["pos"] = "NOUN"
                    tc = {
                        **tc,
                        "function": {
                            **dict(tc.get("function", {}) or {}),
                            "arguments": json.dumps(
                                frequency_args,
                                ensure_ascii=False,
                            ),
                        },
                    }
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        question,
                        "tool_argument_normalized",
                        lt(
                            "frequency_list: Der erzwungene Content-Evidenzschritt "
                            "wurde auf eine Wort-/Lemmaliste mit POS=NOUN "
                            "normalisiert; eine POS-Inventarliste kann diese "
                            "Evidenzart nicht liefern.",
                            "frequency_list: The forced content evidence step was "
                            "normalised to a word or lemma list with POS=NOUN. A "
                            "POS inventory cannot deliver this kind of evidence.",
                        ),
                    )
                if (
                    str(
                        frequency_args.get("group_by", "word")
                        or "word"
                    ).strip().casefold()
                    == "pos"
                    and str(
                        frequency_args.get("pos", "") or ""
                    ).strip()
                ):
                    # A POS filter has no meaning when POS itself is the
                    # grouping dimension. The backend intentionally ignores
                    # it; normalise the call before dispatch so provenance and
                    # method reporting describe the effective computation.
                    frequency_args.pop("pos", None)
                    tc = {
                        **tc,
                        "function": {
                            **dict(tc.get("function", {}) or {}),
                            "arguments": json.dumps(
                                frequency_args,
                                ensure_ascii=False,
                            ),
                        },
                    }
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        question,
                        "tool_argument_normalized",
                        lt(
                            "frequency_list: Der wirkungslose POS-Filter wurde "
                            "bei group_by=pos vor der Ausführung entfernt.",
                            "frequency_list: The ineffective POS filter was removed "
                            "before execution with group_by=pos.",
                        ),
                    )
            signature = self._tool_signature(tc)
            # Ein zweiter identischer Aufruf im selben nebenlaeufigen Lauf sieht
            # denselben Zustand und kann nichts Neues liefern. Ein serielles
            # Werkzeug trennt den Lauf, danach darf derselbe Aufruf legitim
            # etwas anderes sehen (frisches Docset), deshalb wird geleert.
            if not self._is_tool_concurrency_safe(tool_name):
                lauf_signaturen.clear()
            elif signature in lauf_signaturen:
                self._ra_append_skipped_tool_result(
                    copilot_event_bus,
                    question,
                    tc,
                    reason="duplicate_same_batch",
                    message=(
                        "Ein identischer Aufruf steht in diesem Block bereits an, "
                        "die redundante Berechnung wurde ausgelassen."
                    ),
                )
                continue
            else:
                lauf_signaturen.add(signature)
            previous_failure = self._failed_tool_attempts.get(signature)
            if previous_failure:
                self._ra_append_blocked_tool_result(
                    copilot_event_bus,
                    question,
                    tc,
                    {
                        "status": "error",
                        "reason": "repeated_failed_tool_call",
                        "message": (
                            "Dieser Tool-Call wurde nach einem identischen Fehlschlag "
                            "blockiert. Ändere die Strategie oder die Argumente."
                        ),
                        "previous_failure": previous_failure,
                    },
                )
                continue
            if (
                signature in self._successful_read_only_tool_results
                and self._is_tool_read_only(tool_name)
            ):
                self._ra_append_reused_tool_result(
                    copilot_event_bus,
                    question,
                    tc,
                    self._successful_read_only_tool_results[signature],
                )
                continue
            # Write-tool approval gate: a tool that is NOT read-only mutates state
            # (save subcorpus, write annotation, cluster_save, ...). It must not be
            # dispatched inline at low/medium autonomy — route it through the
            # autonomy-aware approval policy. When approval is required we pause the
            # turn (WAITING_APPROVAL), emit ``copilot.action_request`` and stash the
            # pending call so ``continue_after_approval`` can dispatch it after the
            # user approves; the call is excluded from the auto-dispatched batch.
            if self._is_tool_known_write(tool_name):
                action_data = {
                    "actionType": tool_name,
                    "payload": self._tool_args(tc),
                    "reversible": False,
                    "summary": f"Schreib-Tool {tool_name} ausführen",
                    "impact": f"Der Copilot moechte das schreibende Tool {tool_name} ausführen.",
                }
                if self._should_require_approval(action_data):
                    self._ra_request_write_tool_approval(copilot_event_bus, question, tc, action_data)
                    continue
            tokens = self._ra_tool_tokens(tc)
            if self.policy:
                check = self.policy.check(
                    principal,
                    tc["function"]["name"],
                    tokens,
                )
                if check["status"] != "ok":
                    self._ra_append_blocked_tool_result(copilot_event_bus, question, tc, check)
                    continue
            allowed.append((tc, tokens))
        return allowed

    def _ra_request_write_tool_approval(
        self,
        copilot_event_bus: Any,
        question: str,
        tc: Dict[str, Any],
        action_data: Dict[str, Any],
    ) -> None:
        """Pause the turn and ask the user to approve a write-tool call.

        Emits a ``copilot.action_request`` event mirroring the ACTION-frame path
        in ``_emit_control_frame_event`` and stores ``self._pending_action`` in the
        shape ``continue_after_approval`` consumes (``requestId`` / ``type`` /
        ``payload``). A synthetic blocked tool-result keeps the LLM history
        consistent so the model does not re-emit the same call before approval.
        """
        tool_name = str(tc.get("function", {}).get("name", "") or "")
        request_id = str(tc.get("id", "") or uuid.uuid4())
        request = {
            "requestId": request_id,
            "type": tool_name,
            "payload": action_data.get("payload", {}),
            "autonomyHint": self._get_autonomy_level(),
            "rationale": action_data.get("impact", ""),
        }
        event = {
            "event": "copilot.action_request",
            "id": request_id,
            "request": request,
            "meta": {
                "summary": action_data.get("summary", ""),
                "reversible": bool(action_data.get("reversible", False)),
                "requiresApproval": True,
                "status": "pending",
                "ts": int(time.time() * 1000),
            },
        }
        self._pending_action = request
        self.state = State.WAITING_APPROVAL
        self._emit_output(copilot_event_bus, event)
        self._ra_append_blocked_tool_result(
            copilot_event_bus,
            question,
            tc,
            {
                "status": "error",
                "reason": "write_tool_requires_approval",
                "message": (
                    "Dieser schreibende Tool-Call wurde nicht automatisch ausgeführt. "
                    "Er wartet auf eine ausdrückliche Nutzerfreigabe."
                ),
                "tool": tool_name,
            },
        )

    def run(
        self,
        question: str,
        role: str = "user",
        *,
        principal: str | None = None,
        stream: bool = False,
        max_steps: int = 20,
        max_time: float | None = None,
        chunks: Any | None = None,
    ) -> str:
        """Execute ``question`` synchronously using the configured tools.

        ``role`` is the conversational turn role. ``principal`` is the
        authenticated identity used for policy, ACL and LLM request scoping.
        """

        return asyncio.run(
            self.run_async(
                question,
                role=role,
                principal=principal,
                stream=stream,
                max_steps=max_steps,
                max_time=max_time,
                chunks=chunks,
            )
        )

    async def _ra_invoke_llm(
        self,
        turn_state: _RunTurnState,
        *,
        request_messages: List[Dict[str, Any]] | None = None,
        tools_override: List[Dict[str, Any]] | None = None,
        json_schema: Dict[str, Any] | None = None,
        use_stream: bool | None = None,
        temperature: float | None = None,
    ) -> Any:
        """Record model-call time for successful and failed calls.

        Use ``finally`` so time spent before a timeout or transport error remains
        in the turn's accounting.
        """
        _llm_start = time.perf_counter()
        # A2: die Stufe wird BEIM START festgehalten, nicht am Ende. Ein
        # Aufruf gehoert der Stufe, die ihn ausgeloest hat. Faende der
        # Stufenwechsel waehrend des Aufrufs statt, buchte ein Blick im
        # finally die gesamte Wartezeit der FOLGE-Stufe zu, und die
        # Verifikation truege die Kosten der Werkzeugschleife.
        _stufe = getattr(self, "_aktuelle_stufe", "") or "Vorlauf"
        # Jede Runde wird lesbar aufgeschrieben, Eingabe und Ausgabe
        # (Projektregel 2026-09-17: am gelesenen Prompt verbessern, nicht an
        # Kennzahlen). Einzige Naht, durch die jeder Aufruf laeuft.
        self._ra_runde_nr = int(getattr(self, "_ra_runde_nr", 0)) + 1
        _nr = self._ra_runde_nr
        _antwort: Any = None
        try:
            _antwort = await self._ra_invoke_llm_ungebucht(
                turn_state,
                request_messages=request_messages,
                tools_override=tools_override,
                json_schema=json_schema,
                use_stream=use_stream,
                temperature=temperature,
            )
            return _antwort
        finally:
            modellzeit_buchen(turn_state, _stufe, time.perf_counter() - _llm_start)
            with contextlib.suppress(Exception):
                _zwischenstand(
                    f"runde_{_nr:02d}_{_stufe}",
                    _runde_lesbar(
                        nr=_nr,
                        stufe=_stufe,
                        messages=getattr(self, "_ra_letzte_eingabe", (None, None))[0],
                        tools=getattr(self, "_ra_letzte_eingabe", (None, None))[1],
                        antwort=_antwort,
                        dauer=time.perf_counter() - _llm_start,
                    ),
                    sitzung=getattr(self.session, "session_id", ""),
                )

    async def _ra_invoke_llm_ungebucht(
        self,
        turn_state: _RunTurnState,
        *,
        request_messages: List[Dict[str, Any]] | None = None,
        tools_override: List[Dict[str, Any]] | None = None,
        json_schema: Dict[str, Any] | None = None,
        use_stream: bool | None = None,
        temperature: float | None = None,
    ) -> Any:
        """Single LLM invocation (lifted verbatim from ``run_async``).

        Reads the per-turn invocation config from ``turn_state``
        (``system_prompt``, ``role``, ``principal``, ``stream``, ``accepts_stream``,
        ``accepts_json_schema``, ``llm_is_async``) and resolves the exposed
        tool space via ``_ra_active_tool_specs`` unless ``tools_override``
        pins it explicitly (structured steps pass ``[]``).
        """
        self._raise_if_cancelled()
        # K1-Budget: jeder tatsaechliche LLM-Aufruf dieses Turns wird hier
        # gezaehlt (ReAct-Schritte, Struktur-Schritte, Verifikation). Die
        # harten Stopps pruefen den Zaehler VOR dem naechsten Aufruf.
        turn_state.llm_calls_used += 1
        self._ra_refresh_session_state(turn_state.normalized_question)
        effective_messages = request_messages or (
            [{"role": "system", "content": turn_state.system_prompt}]
            + self.session.get_history()
        )
        effective_tools = (
            self._ra_active_tool_specs(turn_state)
            if tools_override is None
            else list(tools_override)
        )
        # Runden-Leitplanke (weiche Landung): nach der letzten Werkzeug-Runde
        # keine Tools mehr in ReAct-Fortsetzungen. Struktur-Schritte und
        # explizite Overrides (Repair, Verifier) bleiben unberuehrt.
        rounds_exhausted = (
            tools_override is None
            and json_schema is None
            and self._ra_tool_rounds_exhausted(turn_state)
        )
        if rounds_exhausted:
            effective_tools = []
        confirmation_pressure = (
            "one-sided confirmation of a universal corpus claim"
            in {
                str(value or "").strip().casefold()
                for value in list(
                    self._active_analysis_contract.get(
                        "forbidden_claims",
                        [],
                    )
                    or []
                )
            }
        )
        guard_message = self._ra_tool_runtime_guard_message(
            effective_tools,
            confirmation_pressure=confirmation_pressure,
            structured_step=bool(
                json_schema is not None and request_messages is not None
            ),
            # Nach einer Werkzeugrunde steht die Evidenz im Verlauf.
            evidenz_in_nachrichten=request_messages is not None or turn_state.tool_rounds > 0,
        )
        # Drift-Anker (R2): nur in ReAct-Fortsetzungsrunden, nie im
        # statischen Kern. Zwei Zeilen: Ausgangsfrage-Echo + Abbruchsatz.
        if (
            request_messages is None
            and json_schema is None
            and turn_state.tool_rounds > 0
            and turn_state.normalized_question
            and effective_tools
        ):
            drift_anchor = (
                "AUSGANGSFRAGE: "
                + self._compact_runtime_text(
                    turn_state.normalized_question, limit=220
                )
                # Include scope changes so the model checks each group before concluding.
                + "\nNur fortsetzen, wenn das nächste Werkzeug die Antwort "
                "oder ihre Reichweite ändern könnte."
            )
            guard_message = f"{guard_message}\n{drift_anchor}" if guard_message else drift_anchor
        # Use the recipe-limit format only at that boundary. At the step limit,
        # follow the handoff path and state which condition ended tool use.
        if request_messages is None and rounds_exhausted and not getattr(self, "_ra_deutung_abgegeben", False):
            if getattr(turn_state, "schrittdecke_erreicht", False):
                notiz = schrittdecke_notiz(int(getattr(self, "_turn_max_steps", 0) or 0))
                guard_message = f"{guard_message}\n{notiz}" if guard_message else notiz
            else:
                guard_message = f"{guard_message}\n{TOOL_ROUND_WRAPUP_LINE}" if guard_message else TOOL_ROUND_WRAPUP_LINE
        if guard_message:
            # Strikt ans Ende: hinter dem KV-Praefix und der Historie.
            effective_messages = [
                *effective_messages,
                _guard_nachricht_fuer_modell(guard_message),
            ]
        # Aufgezeichnet wird, was das Modell WIRKLICH bekommt, also mit der
        # Waechternachricht. Bis zum 2026-09-25 fehlte sie in jeder Rundendatei.
        self._ra_letzte_eingabe = (effective_messages, effective_tools)
        llm_kwargs: Dict[str, Any] = {
            "user": turn_state.principal,
            "policy": self.policy,
        }
        if turn_state.accepts_stream:
            llm_kwargs["stream"] = (
                turn_state.stream if use_stream is None else use_stream
            )
        if turn_state.accepts_json_schema and json_schema is not None:
            llm_kwargs["json_schema"] = json_schema
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if (
            turn_state.accepts_tool_choice
            and turn_state.forced_next_tools
            and effective_tools
        ):
            # The evidence contract already narrowed the visible tool space.
            # Requiring a call here prevents a model from replacing a missing
            # measurement with plausible prose; it does not prescribe which
            # result or interpretation the model must produce.
            llm_kwargs["tool_choice"] = "required"
        if self.observability:
            with self.observability.span(self.session.session_id, "llm") as span:
                start_llm = time.perf_counter()
                if turn_state.llm_is_async:
                    result = await self._ra_await_with_cancellation(
                        self.call_llm(
                            effective_messages,
                            effective_tools,
                            **llm_kwargs,
                        )
                    )
                else:
                    result = await asyncio.to_thread(
                        self.call_llm,
                        effective_messages,
                        effective_tools,
                        **llm_kwargs,
                    )
                span.set_attribute(
                    "duration_ms", (time.perf_counter() - start_llm) * 1000
                )
                if isinstance(result, dict):
                    self._last_llm_route = str(result.get("_cc_route", "") or self._last_llm_route)
                    self._last_llm_model = str(result.get("_cc_model", "") or self._last_llm_model)
                    self._ra_refresh_session_state(turn_state.normalized_question)
                    if self.observability and self._last_llm_route:
                        safe_route = self._last_llm_route.replace(":", "_")
                        self.observability.record(
                            self.session.session_id,
                            f"llm.route.{safe_route}",
                            status="ok",
                        )
                self._raise_if_cancelled()
                return result

        if turn_state.llm_is_async:
            result = await self._ra_await_with_cancellation(
                self.call_llm(
                    effective_messages,
                    effective_tools,
                    **llm_kwargs,
                )
            )
        else:
            result = await asyncio.to_thread(
                self.call_llm,
                effective_messages,
                effective_tools,
                **llm_kwargs,
            )
        if isinstance(result, dict):
            self._last_llm_route = str(result.get("_cc_route", "") or self._last_llm_route)
            self._last_llm_model = str(result.get("_cc_model", "") or self._last_llm_model)
            self._ra_refresh_session_state(turn_state.normalized_question)
            if self.observability and self._last_llm_route:
                safe_route = self._last_llm_route.replace(":", "_")
                self.observability.record(
                    self.session.session_id,
                    f"llm.route.{safe_route}",
                    status="ok",
                )
        self._raise_if_cancelled()
        return result

    async def _ra_call_llm_with_recovery(
        self,
        turn_state: _RunTurnState,
        copilot_event_bus: Any,
        invoker: Callable[[], Awaitable[Any]] | None = None,
        consume: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> Any:
        """Retry/recovery wrapper around the LLM call (lifted from ``run_async``).

        Defaults to invoking ``_ra_invoke_llm`` with the plain per-turn
        config; structured steps pass a custom ``invoker``. Streaming callers
        pass ``consume`` so failures raised while iterating the returned stream
        remain inside this same recovery boundary. Typed
        ``LLMRequestError``s go through ``_ra_recover_llm_error`` (which owns
        the recovery budgets on ``turn_state``); untyped errors use the plain
        exponential-backoff retry budget.

        A SUCCESSFUL recovery always earns one more LLM invoke: the loop only
        exits by returning a real LLM result or raising. (The historical
        ``for attempt in range(...)`` boundary swallowed the re-call when a
        typed-error recovery succeeded on the last attempt and silently
        returned ``None`` — a wasted recovery. Termination stays bounded:
        every ``continue`` either consumed one of the capped recovery budgets
        on ``turn_state`` or one slot of the ``llm_retries`` budget.)
        """
        call = invoker or (lambda: self._ra_invoke_llm(turn_state))
        attempt = 0
        while True:
            self._raise_if_cancelled()
            try:
                result = await call()
                if consume is not None:
                    result = await consume(result)
                self._raise_if_cancelled()
                turn_state.engine_retry_count = 0
                return result
            except CopilotTurnCancelled:
                raise
            except LLMRequestError as exc:
                if not hasattr(exc, "kind"):
                    raise
                if bool(getattr(exc, "response_started", False)):
                    # Werkzeuge laufen erst nach dem vollstaendigen Strom, eine
                    # Modellstoerung erzeugt also kein Duplikat: Teilausgabe
                    # verwerfen, wiederholen. Alles andere bleibt ohne Replay.
                    stoerung = _ist_modellstoerung(exc)
                    self._ra_emit_recovery(
                        copilot_event_bus, turn_state.normalized_question,
                        "stream_replay" if stoerung else "stream_abort",
                        _STREAM_REPLAY_HINWEIS if stoerung else _STREAM_ABBRUCH_HINWEIS,
                        error=exc)
                    if not stoerung:
                        raise
                if self.observability:
                    self.observability.record(
                        self.session.session_id,
                        "llm",
                        status=exc.kind,
                    )
                if await self._ra_recover_llm_error(
                    turn_state,
                    copilot_event_bus,
                    turn_state.question,
                    turn_state.normalized_question,
                    turn_state.role,
                    exc,
                    attempt,
                ):
                    attempt += 1
                    continue
                raise
            except Exception:
                if self.observability:
                    self.observability.record(
                        self.session.session_id,
                        "llm",
                        status="error",
                    )
                if attempt < self.llm_retries and self._ra_consume_retry_budget(
                    turn_state
                ):
                    delay = 2**attempt * 0.1
                    self._ra_emit_recovery(
                        copilot_event_bus,
                        turn_state.normalized_question,
                        "llm_retry",
                        lt("Unerwarteter LLM-Fehler. Neuer Versuch in {delay:.1f}s.",
                           "Unexpected model error. Retrying in {delay:.1f}s.").format(delay=delay),
                    )
                    await self._ra_wait_with_cancellation(delay)
                    attempt += 1
                    continue
                raise

    async def _ra_run_structured_step(
        self,
        turn_state: _RunTurnState,
        copilot_event_bus: Any,
        *,
        doc: str,
        payload: Dict[str, Any],
        schema: Dict[str, Any],
        temperature: float | None = None,
    ) -> Any:
        """Schema-constrained side-channel LLM step (lifted from ``run_async``).

        Used by the contract preflight, observed-facts extraction and (via a
        ``functools.partial`` binding) the injected ``GroundingVerifier``.
        Returns ``None`` when the model path cannot do structured output.
        """
        self._raise_if_cancelled()
        # Fix 3: in der Verifikationsphase VOR JEDEM Struktur-Schritt die
        # Restzeit pruefen (nicht nur beim Betreten); kippt sie, sofort
        # abbrechen statt weitere Verifier-Runden zu verbrennen.
        if turn_state.in_verifier_phase and not _budgets.verifier_time_remaining_ok(
            turn_state.started_at, turn_state.max_time
        ):
            raise _VerifierTimeBudgetExceeded()
        if not turn_state.accepts_json_schema:
            return None
        result = await self._ra_call_llm_with_recovery(
            turn_state,
            copilot_event_bus,
            lambda: self._ra_invoke_llm(
                turn_state,
                request_messages=self._ra_build_grounding_messages(doc, payload),
                tools_override=[],
                json_schema=schema,
                use_stream=False,
                temperature=temperature,
            ),
        )
        self._raise_if_cancelled()
        return parse_structured_payload(strukturschritt_buchen(self, schema, payload, result))

    async def _ra_run_tool_batches(
        self,
        turn_state: _RunTurnState,
        copilot_event_bus: Any,
        candidate_calls: List[Dict[str, Any]],
        *,
        active_contract: AnalysisContract | None,
        dispatch: Callable[[Dict[str, Any], int], Awaitable[None]],
    ) -> None:
        """Filter and execute one round of tool calls (lifted from ``run_async``).

        ``dispatch`` is the per-turn ``_dispatch`` closure (still bound inside
        ``run_async``); safe batches run concurrently, unsafe ones serially.
        """
        self._raise_if_cancelled()
        if self._ra_tool_rounds_exhausted(turn_state):
            # Backstop der Runden-Leitplanke: Tool-Calls trotz leerem
            # Tool-Space werden ehrlich blockiert (Historie bleibt valide).
            for tc in candidate_calls:
                if not isinstance(tc, dict) or not tc.get("function"):
                    continue
                self._ra_append_blocked_tool_result(
                    copilot_event_bus,
                    turn_state.normalized_question,
                    tc,
                    {
                        "status": "error",
                        "reason": "tool_round_limit",
                        "message": (
                            schrittdecke_notiz(int(getattr(self, "_turn_max_steps", 0) or 0))
                            if turn_state.schrittdecke_erreicht
                            and not getattr(self, "_ra_deutung_abgegeben", False)
                            else TOOL_ROUND_WRAPUP_LINE
                        ),
                    },
                )
            return
        allowed_calls = self._ra_filter_tool_calls(
            candidate_calls,
            copilot_event_bus=copilot_event_bus,
            question=turn_state.normalized_question,
            principal=turn_state.principal,
            active_contract=active_contract,
            active_allowed_tools=turn_state.active_allowed_tools,
            forced_next_tools=turn_state.forced_next_tools,
        )
        if not allowed_calls:
            return

        token_map = {tc["id"]: tokens for tc, tokens in allowed_calls}
        ordered_calls = [tc for tc, _ in allowed_calls]
        # R2 (gebuendelte Ausfuehrung): Evidenz-IDs werden VOR der Ausfuehrung
        # in Anforderungsreihenfolge geplant und nach der Runde in genau
        # dieser Reihenfolge angehaengt. Read-only-Batches laufen nebenlaeufig
        # (asyncio.gather), Schreib-Tools seriell mit Approval wie bisher.
        self._ra_plan_round_evidence(ordered_calls, active_contract)
        try:
            for is_safe, batch in self._partition_tool_calls(ordered_calls):
                self._raise_if_cancelled()
                if is_safe:
                    await asyncio.gather(
                        *[
                            dispatch(tc, token_map[tc["id"]])
                            for tc in batch
                        ]
                    )
                else:
                    for tc in batch:
                        self._raise_if_cancelled()
                        await dispatch(tc, token_map[tc["id"]])
        finally:
            self._ra_flush_round_evidence(ordered_calls)

    async def run_async(
        self,
        question: str,
        role: str = "user",
        *,
        principal: str | None = None,
        stream: bool = False,
        max_steps: int = 20,
        max_time: float | None = None,
        chunks: Any | None = None,
    ) -> str:
        """Execute ``question`` asynchronously using the configured tools.

        Supports control frames for structured communication:
        - PLAN frames emit copilot.plan events
        - CLARIFY frames emit copilot.clarify events and pause execution
        - ACTION frames emit copilot.action_request events

        The behavior adapts to the autonomy level in ui_context. ``role`` is
        the conversational turn role; ``principal`` is the authenticated
        identity used by policy/ACL and the LLM request metadata.
        """

        try:
            from candyconc.services.backend import copilot_event_bus
        except Exception:  # pragma: no cover - isolated test environments
            copilot_event_bus = types.SimpleNamespace(publish=lambda *args, **kwargs: None)

        if self.cancel_requested:
            self.state = State.FINISHED
            return ""

        # Answer language (candyconc/answer_language.py): a new user question
        # decides it once, continuations of the turn keep it. The value is
        # set in the context of the task that runs this coroutine.
        turn_role = str(role or "user").strip() or "user"
        if question.strip() and (turn_role == "user" or turn_role not in self._CHAT_MESSAGE_ROLES):
            self._answer_language = resolve_answer_language(
                question, self.ui_context, getattr(self, "interface_language", None))
        enter_answer_language(getattr(self, "_answer_language", None))

        role, principal = self._resolve_turn_identity(role, principal)
        normalized_question = question.strip()
        if normalized_question and role == "user":
            self._reset_runtime_guards()
            self._reset_grounding_state()
        self.session.update_rehydration_state(
            self._build_runtime_state(normalized_question)
        )
        if normalized_question:
            # trim history before adding the new turn so that the conversation
            # stays within the configured token budget
            self.session.summarise(
                project=self.project,
                runtime_state=self._build_runtime_state(normalized_question),
            )
            # The stored message role MUST be the ChatML role "user". The
            # requester identity lives independently in ``principal`` and must
            # never leak into the message role.
            self.session.append(
                {"role": "user", "content": question},
                project=self.project,
            )
            # summarise after appending the new message to persist any trimmed
            # history notes into the project timeline
            self.session.summarise(
                project=self.project,
                runtime_state=self._build_runtime_state(normalized_question),
            )
            # retrieve relevant past summaries for context only for real user turns
            if role == "user":
                self.session.search(question)
        self.state = State.WAITING_LLM
        step = 0  # noqa: F841
        start_time = time.perf_counter()
        # Die Statusnaht hat kein turn_state und braucht den Turnbeginn
        # trotzdem, um jedem Stufenwechsel eine Zeit mitzugeben.
        self._turn_start_perf = start_time
        # Der Vorlauf muss VOR dem Rezept-Routing gemeldet werden, sonst
        # faellt genau der Klassifikator aus der Zeitleiste, der die Stufe
        # ausmacht. Eine erste Fassung stand 60 Zeilen tiefer und meldete
        # dadurch "0 s" fuer eine Stufe, die am 273M-Korpus 189,5 bis
        # 236,9 s gedauert hat.
        self._ra_emit_status(copilot_event_bus, "Vorlauf")
        sig = inspect.signature(self.call_llm)
        accepts_stream = "stream" in sig.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )
        accepts_json_schema = "json_schema" in sig.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )
        accepts_tool_choice = "tool_choice" in sig.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in sig.parameters.values()
        )
        llm_is_async = asyncio.iscoroutinefunction(self.call_llm)
        dispatch_is_async = asyncio.iscoroutinefunction(self.dispatch)
        if self.policy:
            max_steps = self.policy.get(principal, "max_steps", max_steps)
            max_time = self.policy.get(principal, "max_time_sec", max_time)
        # Das Schrittbudget des Turns, gemerkt fuer den Fortschrittsbalken.
        # Ohne es stuende dort ein getattr mit Vorgabe null, und der Balken
        # bliebe still leer: eine Anzeige, die nichts zeigt und niemandem
        # sagt, dass sie nichts zeigt.
        self._turn_max_steps = int(max_steps or 0)

        # R2: Rezeptwahl VOR dem ersten LLM-Call; Fortsetzungslaeufe
        # (role=system) behalten das Rezept des laufenden Turns.
        if normalized_question and role == "user":
            # H9.2: Gates VOR dem Routing (Universum = Registry minus Gates).
            registry_names = registry_tool_names()
            self._turn_capability_unavailable_tools.update(
                embedding_unavailable_gate(self.ui_context, registry_names))
            self._turn_capability_unavailable_tools.update(
                word_similarity_unavailable_gate(registry_names))
            routing = await self._ra_route_turn_recipe(normalized_question, max_time=max_time)
            self._turn_recipe_routing = dict(routing or {})
            self._active_recipe_id = str(routing.get("recipe_id") or "")
            self._active_recipe_family = str(routing.get("family") or "")
            self.tools = expand_tools_for_recipe(  # H9.2: Kernwerkzeuge sichern
                self.tools, self._active_recipe_id,
                self._turn_capability_unavailable_tools)

        # System-Nachricht = build_static_core() + Turn-Briefing (KV-Split):
        # byte-stabiler Praefix, alles Variable strikt ans Ende.
        system_prompt = self._ra_build_turn_system_prompt()
        turn_state = _RunTurnState()
        turn_state.question = question
        turn_state.normalized_question = self._turn_frage = normalized_question
        turn_state.role = role
        turn_state.principal = principal
        turn_state.stream = stream
        turn_state.system_prompt = system_prompt
        turn_state.accepts_stream = accepts_stream
        turn_state.accepts_json_schema = accepts_json_schema
        turn_state.accepts_tool_choice = accepts_tool_choice
        turn_state.llm_is_async = llm_is_async
        turn_state.started_at = start_time
        turn_state.max_time = max_time
        turn_state.recipe_id = self._active_recipe_id
        active_contract: AnalysisContract | None = None
        ground_analysis = False

        def _refresh_session_state() -> None:
            self._ra_refresh_session_state(normalized_question)

        def _record_tool_call_anomaly(
            kind: str,
            *,
            finish_reason: str | None = None,
            candidate_calls: List[Dict[str, Any]] | None = None,
            exposed_tools: List[str] | None = None,
            content_preview: str | None = None,
            note: str | None = None,
        ) -> None:
            self._ra_record_tool_call_anomaly(
                kind,
                finish_reason=finish_reason,
                candidate_calls=candidate_calls,
                exposed_tools=exposed_tools,
                content_preview=content_preview,
                note=note,
                analysis_family=str((active_contract.analysis_family if active_contract else "") or ""),
                allowed_tools=turn_state.active_allowed_tools,
                forced_tools=turn_state.forced_next_tools,
            )

        def _emit_recovery(
            kind: str,
            message: str,
            *,
            error: LLMRequestError | None = None,
        ) -> None:
            self._ra_emit_recovery(
                copilot_event_bus, normalized_question, kind, message, error=error
            )

        def _evidence_note(missing: List[str]) -> str:
            # List permitted anchors only where _ra_filter_tool_calls enforces them.
            # Otherwise words from the question could become artificial search constraints.
            riegel = bool(
                active_contract is not None
                and active_contract.analysis_family == "open_research"
                and set(turn_state.forced_next_tools or ()) & _SEARCH_ANCHOR_TOOLS
            )
            return contract_evidence_note(
                missing,
                turn_state.forced_next_tools,
                _grounded_search_anchor_guidance(
                    normalized_question,
                    list(self._turn_evidence_items or []),
                ) if riegel else "",
            )

        def _emit_grounding_event(
            verdict: str,
            *,
            analysis_family: str,
            rejected_claim_count: int = 0,
            evidence_gaps: List[str] | None = None,
        ) -> None:
            self._ra_emit_grounding_event(
                copilot_event_bus,
                verdict,
                analysis_family=analysis_family,
                rejected_claim_count=rejected_claim_count,
                evidence_gaps=evidence_gaps,
            )

        def _pending_required_evidence_tools(
            contract: AnalysisContract,
        ) -> Tuple[List[str], List[str]]:
            return self._ra_pending_required_evidence_tools(
                contract, turn_state.active_allowed_tools
            )

        def _activate_fail_closed_grounding(kind: str, message: str) -> None:
            self._ra_activate_fail_closed_grounding(
                turn_state, copilot_event_bus, normalized_question, kind, message
            )

        # Bound callable (not a closure): the structured-step seam shared by
        # the contract preflight, observed-facts extraction and the injected
        # GroundingVerifier below.
        _run_structured_step = functools.partial(
            self._ra_run_structured_step, turn_state, copilot_event_bus
        )

        async def _run_analysis_contract_preflight() -> AnalysisContract | None:
            if role != "user" or not normalized_question or not self._ra_requires_grounding_contract():
                return None

            async def _attach_response_requirements(
                contract: AnalysisContract | None,
            ) -> AnalysisContract | None:
                """Enrich the final routed contract exactly once with user slots."""

                if contract is None or contract.mode != "tool_analysis":
                    return contract
                literal_requirements = normalise_response_requirements(
                    [],
                    question_text=normalized_question,
                )
                if not (
                    literal_requirements
                    or list(contract.response_requirements or [])
                ):
                    # The deliverable already carries the ordinary answer shape.
                    # Spend a focused planning turn only when the question or the
                    # routed contract exposes an additional substantive duty.
                    contract.response_requirements = []
                    return contract
                if not accepts_json_schema:
                    contract.response_requirements = literal_requirements
                    return contract
                requirement_raw = await _run_structured_step(
                    doc=RESPONSE_REQUIREMENTS_DOC,
                    payload={
                        "question": normalized_question,
                        "deliverable_kind": contract.deliverable_kind,
                    },
                    schema=response_requirements_schema(),
                )
                if isinstance(requirement_raw, dict):
                    raw_requirements = requirement_raw.get(
                        "response_requirements",
                        [],
                    ) or []
                else:
                    # Recover only literal positive obligations that can be
                    # parsed without inventing answer content. Never retain a
                    # broad planner's unreviewed slot guesses.
                    raw_requirements = []
                    _record_tool_call_anomaly(
                        "response_requirements_invalid",
                        note=(
                            "Der fokussierte Antwortpflicht-Preflight war "
                            "nicht schema-konform; nur wörtlich erkennbare "
                            "Nutzerpflichten werden deterministisch erhalten."
                        ),
                    )
                contract.response_requirements = normalise_response_requirements(
                    raw_requirements,
                    question_text=normalized_question,
                )
                return contract

            heuristic_contract = heuristic_analysis_contract(
                normalized_question,
                available_tools=self._available_tool_names(),
                read_only_tools=self._read_only_tool_names(),
                rezept_id=self._active_recipe_id,
                # Ohne die Stufe kann der Kontrakt nicht wissen, ob das
                # Rezept aus einem Modellurteil oder aus einem Schlagwort
                # stammt, und behandelt beide gleich.
                rezept_stufe=str(
                    (self._turn_recipe_routing or {}).get("stage") or ""
                ),
            )
            if heuristic_contract is not None:
                return await _attach_response_requirements(heuristic_contract)
            # K1: Der Klassifikator laeuft nur, wenn WEDER die Cues NOCH das
            # gewaehlte Rezept die Familie bestimmen. Sein Ergebnis wird pro
            # (Session, Frage-Familie) gecacht.
            classifier_cache_key = normalized_question.casefold()
            cached_contract_raw = self._contract_classifier_cache.get(
                classifier_cache_key
            )
            if cached_contract_raw is not None:
                return await _attach_response_requirements(
                    AnalysisContract.from_raw(
                        dict(cached_contract_raw),
                        question_text=normalized_question,
                        available_tools=self._available_tool_names(),
                        read_only_tools=self._read_only_tool_names(),
                    )
                )
            if not accepts_json_schema:
                _activate_fail_closed_grounding(
                    "grounding_contract_unavailable",
                    "Der aktuelle Modellpfad unterstützt keinen strukturierten AnalysisContract. Tool-gestützte Analyse wird fail-closed blockiert.",
                )
                return None
            payload = {
                "question": normalized_question,
                "ui_context": self.ui_context,
                "available_tools": self._available_tool_names(),
                "read_only_tools": self._read_only_tool_names(),
            }
            raw = await _run_structured_step(
                doc=ANALYSIS_CONTRACT_DOC,
                payload=payload,
                schema=analysis_contract_schema(),
            )
            if raw is None:
                _activate_fail_closed_grounding(
                    "grounding_contract_invalid",
                    "Der AnalysisContract konnte nicht strukturiert erzeugt oder geparst werden. Tool-gestützte Analyse wird fail-closed blockiert.",
                )
                return None
            proposed_contract = AnalysisContract.from_raw(
                raw,
                question_text=normalized_question,
                available_tools=self._available_tool_names(),
                read_only_tools=self._read_only_tool_names(),
            )
            if proposed_contract.mode == "direct_answer":
                fallback_contract = self._ra_fallback_contract(normalized_question)
                if fallback_contract is not None:
                    return await _attach_response_requirements(fallback_contract)
                return proposed_contract
            if proposed_contract.mode != "tool_analysis":
                return proposed_contract
            review_raw = await _run_structured_step(
                doc=CONTRACT_VERIFIER_DOC,
                payload={
                    "question": normalized_question,
                    "available_tools": self._available_tool_names(),
                    "read_only_tools": self._read_only_tool_names(),
                    "proposed_contract": proposed_contract.to_dict(),
                },
                schema=contract_review_schema(),
            )
            if review_raw is None:
                _activate_fail_closed_grounding(
                    "grounding_contract_review_invalid",
                    "Der Contract-Verifier konnte den AnalysisContract nicht strukturiert prüfen. Tool-gestützte Analyse wird fail-closed blockiert.",
                )
                return None
            review = ContractReview.from_raw(review_raw, question_text=normalized_question)
            review_reason = review.reason or "Der AnalysisContract wurde vom Verifier als nicht hinreichend eng oder nicht hinreichend belegt eingestuft."
            if review.verdict == "clarify":
                fallback_contract = self._ra_fallback_contract(normalized_question)
                if (
                    fallback_contract is not None
                    and fallback_contract.mode == "tool_analysis"
                    and fallback_contract.track == "exploratory_research"
                    and fallback_contract.analysis_family == "open_research"
                    and proposed_contract.track == "exploratory_research"
                    and proposed_contract.analysis_family == "open_research"
                ):
                    # An explicitly delegated corpus exploration is answerable
                    # without asking which evidence family the user prefers.
                    # Keep the model's valid evidence strategy, but normalise
                    # the deliverable to the canonical exploratory overview.
                    autonomous_payload = proposed_contract.to_dict()
                    autonomous_payload["deliverable_kind"] = (
                        fallback_contract.deliverable_kind
                    )
                    autonomous_payload["response_shape"] = (
                        fallback_contract.response_shape
                    )
                    return await _attach_response_requirements(
                        AnalysisContract.from_raw(
                            autonomous_payload,
                            question_text=normalized_question,
                            available_tools=self._available_tool_names(),
                            read_only_tools=self._read_only_tool_names(),
                        )
                    )
                return AnalysisContract(
                    mode="clarify",
                    track=proposed_contract.track,
                    analysis_family=proposed_contract.analysis_family,
                    deliverable_kind=proposed_contract.deliverable_kind,
                    question_scope=proposed_contract.question_scope,
                    forbidden_claims=list(proposed_contract.forbidden_claims),
                    response_shape=proposed_contract.response_shape,
                    needs_clarification=True,
                    clarification_question=(
                        review.clarification_question or review_reason
                    ),
                )
            if review.verdict == "conservative_only":
                fallback_contract = self._ra_fallback_contract(normalized_question)
                if fallback_contract is not None:
                    return await _attach_response_requirements(fallback_contract)
                _activate_fail_closed_grounding(
                    "grounding_contract_rejected",
                    review_reason,
                )
                return None
            fallback_contract = self._ra_fallback_contract(normalized_question)
            preserve_open_scope = (
                fallback_contract is not None
                and fallback_contract.mode == "tool_analysis"
                and fallback_contract.track == "exploratory_research"
                and fallback_contract.analysis_family == "open_research"
                and proposed_contract.track == "exploratory_research"
                and proposed_contract.analysis_family == "open_research"
            )
            revised_payload = proposed_contract.to_dict()
            if review.track:
                revised_payload["track"] = review.track
            if review.analysis_family:
                revised_payload["analysis_family"] = review.analysis_family
            if review.deliverable_kind:
                revised_payload["deliverable_kind"] = review.deliverable_kind
            if review.required_evidence:
                revised_payload["required_evidence"] = list(review.required_evidence)
            if review.response_shape:
                revised_payload["response_shape"] = review.response_shape
            if preserve_open_scope:
                # A broad, explicitly delegated corpus exploration must not be
                # collapsed by the review pass into a metadata-only or lookup
                # answer. Review may refine the evidence plan, but the user's
                # requested research breadth and deliverable remain intact.
                revised_payload["track"] = "exploratory_research"
                revised_payload["analysis_family"] = "open_research"
                revised_payload["deliverable_kind"] = (
                    fallback_contract.deliverable_kind
                )
                revised_payload["response_shape"] = (
                    fallback_contract.response_shape
                )
            revised_contract = AnalysisContract.from_raw(
                revised_payload,
                question_text=normalized_question,
                available_tools=self._available_tool_names(),
                read_only_tools=self._read_only_tool_names(),
            )
            unsupported_evidence = [
                kind
                for kind in revised_contract.required_evidence
                if not any(
                    tool_name in set(revised_contract.allowed_tools)
                    for tool_name in _EVIDENCE_TO_TOOLS.get(kind, ())
                )
            ]
            if (
                unsupported_evidence
                and revised_contract.analysis_family == "open_research"
            ):
                # A model verifier can request an evidence kind that its own
                # selected tools cannot produce. Keep the executable parts of
                # the research design instead of failing an otherwise useful
                # open analysis or waiting forever for an impossible tool.
                revised_payload["required_evidence"] = [
                    kind
                    for kind in revised_contract.required_evidence
                    if kind not in set(unsupported_evidence)
                ]
                revised_contract = AnalysisContract.from_raw(
                    revised_payload,
                    question_text=normalized_question,
                    available_tools=self._available_tool_names(),
                    read_only_tools=self._read_only_tool_names(),
                )
            if revised_contract.mode == "tool_analysis" and not revised_contract.required_evidence:
                selected_tools = set(revised_contract.allowed_tools)
                inferred_evidence = [
                    kind
                    for kind in (
                        "metadata_rows",
                        "metric_rows",
                        "dispersion_profile",
                        "semantic_rows",
                        "cluster_rows",
                        "document_rows",
                        "frequency_rows",
                        "kwic_rows",
                        "total_hits",
                    )
                    if selected_tools.intersection(_EVIDENCE_TO_TOOLS.get(kind, ()))
                ][:3]
                if inferred_evidence:
                    revised_payload["required_evidence"] = inferred_evidence
                    revised_contract = AnalysisContract.from_raw(
                        revised_payload,
                        question_text=normalized_question,
                        available_tools=self._available_tool_names(),
                        read_only_tools=self._read_only_tool_names(),
                    )
            if revised_contract.mode == "tool_analysis" and not revised_contract.required_evidence:
                _activate_fail_closed_grounding(
                    "grounding_contract_missing_evidence",
                    "Der AnalysisContract enthält keine kanonischen required_evidence. Tool-gestützte Analyse wird fail-closed blockiert.",
                )
                return None
            if (
                revised_contract.mode == "tool_analysis"
                and revised_contract.analysis_family == "open_research"
                and any(
                    kind in OPEN_RESEARCH_INCOMPATIBLE_EVIDENCE_KINDS
                    for kind in revised_contract.required_evidence
                )
                and not any(
                    kind not in OPEN_RESEARCH_INCOMPATIBLE_EVIDENCE_KINDS
                    for kind in revised_contract.required_evidence
                )
            ):
                _activate_fail_closed_grounding(
                    "grounding_open_research_too_broad",
                    "Open research darf keine eng gebundene KWIC-, Metrik- "
                    "oder Dispersionspflicht fahren. Der Contract muss enger "
                    "werden oder in clarify gehen.",
                )
                return None
            if revised_contract.mode == "tool_analysis" and not revised_contract.allowed_tools:
                fallback_contract = self._ra_fallback_contract(normalized_question)
                if fallback_contract is not None:
                    return await _attach_response_requirements(fallback_contract)
                _activate_fail_closed_grounding(
                    "grounding_contract_empty_bundle",
                    "Der verifizierte AnalysisContract hat kein ausführbares Tool-Bundle. Tool-gestützte Analyse wird fail-closed blockiert.",
                )
                return None
            if revised_contract.mode == "tool_analysis":
                self._contract_classifier_cache[classifier_cache_key] = (
                    revised_contract.to_dict()
                )
            return await _attach_response_requirements(revised_contract)

        async def _extract_observed_facts(
            contract: AnalysisContract,
            evidence_items: List[EvidenceItem],
        ) -> List[Any]:
            def select_for_synthesis(facts: List[Any]) -> List[Any]:
                # Kappe, Auswahl und Verdichtungsmeldung liegen in
                # grounding_facts. Count, Sampling-Herkunft,
                # Sampling-Limitation und Query-Scope duerfen keine Zeile aus
                # einer ausdruecklich angeforderten reproduzierbaren
                # Stichprobe verdraengen, deshalb geht deren Groesse mit.
                requested_sample_rows = max(
                    (
                        int(sample.get("drawn") or sample.get("requested") or 0)
                        for item in evidence_items
                        for sample in [item.raw_surface.get("sample")]
                        if isinstance(sample, dict)
                    ),
                    default=0,
                )
                return select_synthesis_window(
                    facts,
                    analysis_family=contract.analysis_family,
                    requested_sample_rows=requested_sample_rows,
                )

            deterministic_facts = deterministic_observed_facts(
                contract,
                evidence_items,
            )
            covered_evidence_ids = {
                source_id
                for fact in deterministic_facts
                for source_id in fact.source_evidence_ids
            }
            uncovered_items = [
                item
                for item in evidence_items
                if item.id not in covered_evidence_ids
            ]
            if not uncovered_items:
                return select_for_synthesis(deterministic_facts)

            # Deterministic extractors remain authoritative. The LLM only fills
            # evidence sources for which no deterministic fact exists, so a
            # successful common-path extractor no longer suppresses a second,
            # otherwise invisible tool result.
            bundle = build_evidence_bundle(contract, uncovered_items)
            raw = await _run_structured_step(
                doc=OBSERVED_FACTS_DOC,
                payload={
                    "question": normalized_question,
                    "contract": contract.to_dict(),
                    "evidence_bundle": bundle.to_dict(),
                },
                schema=observed_facts_schema(),
            )
            supplemental_facts = validate_observed_facts(
                normalise_observed_facts(raw),
                evidence_items=uncovered_items,
            )
            merged_facts = list(deterministic_facts)
            seen_fact_ids = {fact.id for fact in merged_facts}
            for index, fact in enumerate(
                supplemental_facts,
                start=len(merged_facts) + 1,
            ):
                fact.id = unique_observed_fact_id(
                    fact,
                    seen_fact_ids,
                    ordinal=index,
                )
                seen_fact_ids.add(fact.id)
                merged_facts.append(fact)
            return select_for_synthesis(merged_facts)

        def _validate_answer_envelope_for_turn(
            envelope: AnswerEnvelope,
            observed_facts: List[Any],
            *,
            forbidden_claims: List[str] | None = None,
        ) -> Tuple[List[str], List[str], Dict[str, List[str]]]:
            return validate_answer_envelope(
                envelope,
                observed_facts,
                forbidden_claims=forbidden_claims,
                question_text=normalized_question,
                deliverable_kind=(
                    active_contract.deliverable_kind
                    if active_contract is not None
                    else ""
                ),
                analysis_family=(
                    active_contract.analysis_family
                    if active_contract is not None
                    else ""
                ),
                response_requirements=(
                    active_contract.response_requirements
                    if active_contract is not None
                    else []
                ),
            )

        def _envelope_matches_deliverable_for_turn(
            envelope: AnswerEnvelope,
            *,
            deliverable_kind: str,
        ) -> Tuple[bool, str]:
            return envelope_matches_deliverable_kind(
                envelope,
                deliverable_kind=deliverable_kind,
                question_text=normalized_question,
            )

        def _accepted_claim_evidence_coverage(
            envelope: AnswerEnvelope,
            accepted_claim_ids: List[str],
            rejected_claim_ids: List[str],
            observed_facts: List[Any],
            evidence_items: List[EvidenceItem],
            contract: AnalysisContract,
        ) -> Tuple[List[str], List[str]]:
            accepted = set(accepted_claim_ids) - set(rejected_claim_ids)
            fact_index = {fact.id: fact for fact in observed_facts}
            verified_fact_usage = dict(
                getattr(
                    envelope,
                    "_validated_used_fact_ids_by_claim",
                    {},
                )
                or {}
            )
            reporting_fact_ids: set[str] = set()
            for claim in envelope.claims:
                if claim.id not in accepted:
                    continue
                cited_fact_ids = list(claim.fact_ids or [])
                used_fact_ids = (
                    cited_fact_ids
                    if len(cited_fact_ids) <= 1
                    else list(verified_fact_usage.get(claim.id, []) or [])
                )
                for fact_id in used_fact_ids:
                    fact = fact_index.get(fact_id)
                    if fact is None:
                        continue
                    if contract.deliverable_kind == "followup_questions":
                        reports_fact = claim.claim_kind == "followup"
                    elif claim.claim_kind in {"observation", "interpretation"}:
                        reports_fact = True
                    else:
                        reports_fact = (
                            claim.claim_kind == "limitation"
                            and fact.fact_kind
                            in {"limitation", "negative_result"}
                        )
                    if reports_fact:
                        reporting_fact_ids.add(fact_id)
            item_index = {item.id: item for item in evidence_items}
            covered = sorted(
                {
                    kind
                    for fact_id in reporting_fact_ids
                    for fact in [fact_index.get(fact_id)]
                    if fact is not None
                    for source_id in fact.source_evidence_ids
                    for item in [item_index.get(source_id)]
                    if item is not None
                    for kind in evidence_kinds_for_fact(fact, item)
                }
            )
            present = {
                kind
                for item in evidence_items
                for kind in evidence_kinds_for_item(item)
            }
            if (
                contract.analysis_family == "contrast_keyness"
                and {"metric_rows", "metadata_rows"}.intersection(present)
            ):
                # The contrast renderer prints the deterministic metric table,
                # scope definitions and metadata axis independently of which
                # rows the model cites in its interpretation.
                covered = sorted(
                    {
                        *covered,
                        *(
                            {"metric_rows", "metadata_rows"}
                            & present
                        ),
                    }
                )
            confirmation_guarded = (
                "one-sided confirmation of a universal corpus claim"
                in {
                    str(value or "").strip().casefold()
                    for value in contract.forbidden_claims
                }
            )
            renders_direct_zero = any(
                bool(exact_zero_lexical_search(item)[1])
                for item in evidence_items
            )
            if confirmation_guarded and renders_direct_zero:
                # The confirmation renderer reports this exact result before
                # model prose, so synthesis need not paraphrase it again.
                covered = sorted({*covered, "total_hits"})
            missing = [
                kind
                for kind in contract.required_evidence
                if kind in present and kind not in set(covered)
            ]
            return covered, missing

        def _allows_deterministic_factual_fallback(
            contract: AnalysisContract,
        ) -> bool:
            # Politik, kein Orchestrieren: siehe deterministic_landing.
            # Die Huelle bindet den MASSSTAB, geurteilt wird auf der Frage
            # des Turns und nicht auf question_scope (auf dem Modellpfad
            # vom Modell geschriebene Prosa). Wer direkt aufruft, verliert
            # das Argument still.
            return erlaubt_deterministische_landung(
                contract, normalized_question
            )

        def _build_schema_unavailable_answer(
            evidence_items: List[EvidenceItem],
        ) -> str | None:
            """Fail closed when the model cannot return verifiable structures.

            Factual lookups may still render direct tool facts. Interpretative
            deliverables state that synthesis is unavailable rather than
            substituting a deterministic report for model reasoning.
            """
            assert active_contract is not None
            grounding_contract = effective_analysis_contract(
                active_contract,
                evidence_items,
            )
            observed_facts = deterministic_observed_facts(
                grounding_contract,
                evidence_items,
            )
            self._grounded_fact_notes = grounded_fact_notes(observed_facts)
            bundle = build_evidence_bundle(grounding_contract, evidence_items)
            fact_gaps = required_evidence_fact_gaps(
                grounding_contract,
                observed_facts,
                evidence_items,
            )
            if fact_gaps:
                bundle.missing_required_evidence = self._dedupe_ordered_strs(
                    list(bundle.missing_required_evidence) + list(fact_gaps)
                )
                self._evidence_gaps = self._dedupe_ordered_strs(
                    list(self._evidence_gaps)
                    + [
                        "Es fehlt vertraglich geforderte Evidenz: "
                        + ", ".join(bundle.missing_required_evidence[:4])
                    ]
                )[-6:]
            self._last_grounding_verdict = {
                "verdict": "conservative_only",
                "accepted_claim_ids": [],
                "rejected_claim_ids": [],
                "reasons": [
                    "Der aktuelle Modellpfad unterstützt keine strukturierte "
                    "Grounding-Verifikation; es wird ausschließlich die "
                    "deterministisch belegte Evidenz berichtet."
                ],
                "needs_retry": False,
            }
            self._active_analysis_contract = {
                **grounding_contract.to_dict(),
                "observed_fact_ids": [fact.id for fact in observed_facts][:8],
                "evidence_manifest": evidence_manifest(evidence_items),
                "present_evidence": list(bundle.present_evidence),
                "missing_required_evidence": list(bundle.missing_required_evidence),
                "grounding_verdict": "conservative_only",
                "accepted_claim_count": 0,
                "rejected_claim_count": 0,
                "grounding_diagnostics": {
                    "observed_fact_count": len(observed_facts),
                    "generated_claim_count": 0,
                    "claim_retention_rate": 0.0,
                    "accepted_claim_kinds": {},
                    "rejected_claim_kinds": {},
                    "accepted_fact_reference_count": 0,
                },
                "grounding_output_mode": (
                    "deterministic_factual"
                    if _allows_deterministic_factual_fallback(
                        grounding_contract
                    )
                    else "synthesis_unavailable"
                ),
            }
            _refresh_session_state()
            _emit_grounding_event(
                "conservative_only",
                analysis_family=grounding_contract.analysis_family,
                rejected_claim_count=0,
                evidence_gaps=self._evidence_gaps,
            )
            if _allows_deterministic_factual_fallback(grounding_contract):
                markdown = build_grounded_markdown(
                    grounding_contract,
                    observed_facts,
                    evidence_items,
                    evidence_gaps=self._evidence_gaps,
                    accepted_claim_ids=[],
                )
                return (
                    markdown.strip()
                    if isinstance(markdown, str) and markdown.strip()
                    else None
                )
            return (
                "Die Tool-Evidenz wurde erhoben, aber das geladene Modell "
                "unterstützt keine strukturierte Verifikation für eine "
                "interpretative Endantwort. Ich gebe deshalb keinen "
                "automatisch zusammengesetzten Ersatzbericht aus."
            )

        def _build_deterministic_factual_answer(
            grounding_contract: AnalysisContract,
            evidence_items: List[EvidenceItem],
        ) -> str | None:
            """Render direct lookup facts without replacing interpretation."""
            observed_facts = deterministic_observed_facts(
                grounding_contract,
                evidence_items,
            )
            self._grounded_fact_notes = grounded_fact_notes(observed_facts)
            bundle = build_evidence_bundle(grounding_contract, evidence_items)
            fact_gaps = required_evidence_fact_gaps(
                grounding_contract,
                observed_facts,
                evidence_items,
            )
            if fact_gaps:
                bundle.missing_required_evidence = self._dedupe_ordered_strs(
                    list(bundle.missing_required_evidence) + list(fact_gaps)
                )
                self._evidence_gaps = self._dedupe_ordered_strs(
                    list(self._evidence_gaps)
                    + [
                        "Es fehlt vertraglich geforderte Evidenz: "
                        + ", ".join(bundle.missing_required_evidence[:4])
                    ]
                )[-6:]
            if bundle.incomplete_reason == "truncated_evidence":
                # Ehrlichkeitssignal unveraendert zum Verifikationspfad.
                _emit_recovery(
                    "truncated_evidence",
                    lt("Die Tool-Rückgabe ist begrenzt; die Antwort wird auf "
                       "die sichtbaren Ergebnisse kalibriert.",
                       "The tool output is limited. The answer is calibrated to the visible results."),
                )
            self._last_grounding_verdict = {
                "verdict": "conservative_only",
                "accepted_claim_ids": [],
                "rejected_claim_ids": [],
                "reasons": [
                    "Direkte Faktantwort aus validierter Tool-Evidenz."
                ],
                "needs_retry": False,
            }
            self._active_analysis_contract = {
                **grounding_contract.to_dict(),
                "observed_fact_ids": [fact.id for fact in observed_facts][:8],
                "evidence_manifest": evidence_manifest(evidence_items),
                "present_evidence": list(bundle.present_evidence),
                "missing_required_evidence": list(
                    bundle.missing_required_evidence
                ),
                "grounding_verdict": "conservative_only",
                "accepted_claim_count": 0,
                "rejected_claim_count": 0,
                "grounding_diagnostics": {
                    "observed_fact_count": len(observed_facts),
                    "generated_claim_count": 0,
                    "claim_retention_rate": 0.0,
                    "accepted_claim_kinds": {},
                    "rejected_claim_kinds": {},
                    "accepted_fact_reference_count": 0,
                },
                "grounding_output_mode": "deterministic_factual",
                # Dieselbe Groesse wie im Usage-Bericht, aus derselben Naht.
                # Roh aus turn_state gelesen meldete der Vertrag auf dem
                # deterministischen Faktpfad weniger Modellaufrufe als der
                # Bericht, und der Vertrag geht ueber die Rehydrierung in die
                # Modellsicht.
                **usage_felder(turn_state, self.session),
            }
            _refresh_session_state()
            _emit_grounding_event(
                "conservative_only",
                analysis_family=grounding_contract.analysis_family,
                rejected_claim_count=0,
                evidence_gaps=self._evidence_gaps,
            )
            self._ra_emit_status(copilot_event_bus, "Antwort")
            markdown = build_grounded_markdown(
                grounding_contract,
                observed_facts,
                evidence_items,
                evidence_gaps=self._evidence_gaps,
                accepted_claim_ids=[],
            )
            if not (isinstance(markdown, str) and markdown.strip()):
                return None
            return markdown

        def _build_verifier_skipped_answer(
            grounding_contract: AnalysisContract,
            evidence_items: List[EvidenceItem],
            initial_draft: str,
        ) -> str:
            """Deterministischer Abschluss unter dem Verifier-Zeitbudget.

            K1-Muster (VERIFIER_MIN_TIME_FRACTION in budgets.py): der
            Referenz-Pfad laeuft immer, die Auslassung des LLM-Verifiers
            wird im copilot.grounding-Event annotiert.
            """
            self._last_grounding_verdict = {
                "verdict": "verifier_skipped_time_budget",
                "accepted_claim_ids": [],
                "rejected_claim_ids": [],
                "reasons": [VERIFIER_SKIPPED_NOTE],
                "needs_retry": False,
                "advisories": {"zeitbudget": [VERIFIER_SKIPPED_NOTE]},
            }
            self._active_analysis_contract = {
                **(self._active_analysis_contract or {}),
                "grounding_verdict": "verifier_skipped_time_budget",
                "grounding_output_mode": (
                    "deterministic_reference_time_budget"
                ),
            }
            _refresh_session_state()
            _emit_grounding_event(
                "verifier_skipped_time_budget",
                analysis_family=grounding_contract.analysis_family,
                rejected_claim_count=0,
                evidence_gaps=self._evidence_gaps,
            )
            self._ra_emit_status(copilot_event_bus, "Antwort")
            return _deterministisch_gedeckter_text(
                grounding_contract, evidence_items, initial_draft
            )

        def _deterministisch_gedeckter_text(
            grounding_contract: AnalysisContract,
            evidence_items: List[EvidenceItem],
            initial_draft: str, grund: str = VERIFIER_SKIPPED_NOTE,
        ) -> str:
            """Der Entwurf, soweit er OHNE Modellpruefung zu verantworten ist.

            Referenzen aufgeloest, Zitate gegen die Evidenzzeilen geprueft,
            unbelegte Zahlen gestrichen. Alles davon kostet null
            Modellaufrufe und kann nicht uebersprungen werden.

            DREI Verbraucher, nur einer hat ein Zeitproblem, also reicht
            jeder seinen eigenen ``grund`` durch. Nur der Zeitbudget-Pfad
            setzt den Grounding-Verdict. Zahlen: recipe_runtime.VERIFIER_HINWEISE.
            """

            def _deterministic_markdown() -> Any:
                # H10/G4: Verifier-Skip ohne Entwurf landet zuerst in der
                # rezeptbewussten Todespfad-Landung, nie im Zwei-Fragmente-
                # Digest, solange sichtbare Evidenz in Menge vorliegt.
                landing = self.build_death_landing_markdown()
                if landing:
                    return landing
                observed_facts = deterministic_observed_facts(
                    grounding_contract,
                    evidence_items,
                )
                self._grounded_fact_notes = grounded_fact_notes(
                    observed_facts
                )
                return build_grounded_markdown(
                    grounding_contract,
                    observed_facts,
                    evidence_items,
                    evidence_gaps=self._evidence_gaps,
                    accepted_claim_ids=[],
                )

            return verifier_skipped_answer_text(
                initial_draft,
                lambda draft: self._ra_resolve_reference_draft(
                    turn_state,
                    draft,
                    detect_bare_numbers=bool(self._turn_evidence_items),
                ),
                _deterministic_markdown,
                self._ra_build_fail_closed_grounding_markdown,
                quote_surfaces=evidenz_belegzeilen(evidence_items),
                grund=grund, frage=getattr(self, "_turn_frage", ""))

        async def _build_grounded_final_answer(
            *,
            initial_draft: str = "",
            deterministic_only: bool = False,
        ) -> str | None:
            if not ground_analysis or active_contract is None:
                return None

            evidence_items = [
                EvidenceItem(**dict(item))
                for item in list(self._turn_evidence_items or [])
                if isinstance(item, dict)
            ]
            grounding_contract = effective_analysis_contract(
                active_contract,
                evidence_items,
            )

            # Decoupled from json_schema: when the model path cannot do structured
            # output, never let the finalize path emit unverified raw prose.
            if not accepts_json_schema:
                return _build_schema_unavailable_answer(evidence_items)

            # Exact lookups can be rendered directly from tool facts. Complex
            # deliverables must keep the model-owned synthesis and verifier
            # path; a generic template is not an analytical substitute.
            if _allows_deterministic_factual_fallback(grounding_contract):
                return _build_deterministic_factual_answer(
                    grounding_contract, evidence_items)
            if deterministic_only:
                return None
            if deutungspfad_aktiv():
                if self._aktuelle_stufe != "Antwort":  # Also enter the answer phase without a voluntary handoff.
                    self._ra_emit_status(copilot_event_bus, "Antwort")
                return await fuehre_deutungs_synthese_aus(
                    self, turn_state, copilot_event_bus, evidence_items, entwurf=initial_draft or getattr(self, "_ra_abgabe_entwurf", ""))
            # VOR dem Zeittor (VERIFIER_MIN_TIME_FRACTION des Budgets).
            vorlaeufige_antwort_senden(
                lambda e: self._emit_output(copilot_event_bus, e),
                lambda: _deterministisch_gedeckter_text(
                    grounding_contract, evidence_items, initial_draft,
                    grund=VERIFIER_LAEUFT_NOTE))  # nicht uebersprungen

            # Zeitbewusste Verifikation (Fix 3): der LLM-Verifier startet nur
            # bei ausreichender Restzeit (VERIFIER_MIN_TIME_FRACTION in
            # budgets.py). Darunter finalisiert der deterministische
            # Referenz-Pfad und die Auslassung wird annotiert.
            if not _budgets.verifier_time_remaining_ok(
                start_time, max_time
            ):
                return _build_verifier_skipped_answer(
                    grounding_contract,
                    evidence_items,
                    initial_draft,
                )
            # Fix 3: ab hier LLM-Verifikation; jeder Struktur-Schritt prueft die
            # Restzeit vorab und finalisiert bei ``_VerifierTimeBudgetExceeded``
            # deterministisch (verifier_skipped_time_budget).
            turn_state.in_verifier_phase = True
            try:
                observed_facts = await _extract_observed_facts(
                    grounding_contract,
                    evidence_items,
                )
            except _VerifierTimeBudgetExceeded:
                return _build_verifier_skipped_answer(
                    grounding_contract,
                    evidence_items,
                    initial_draft,
                )
            if not observed_facts:
                self._evidence_gaps = self._dedupe_ordered_strs(
                    list(self._evidence_gaps)
                    + ["Aus den Tool-Ergebnissen ließen sich keine hinreichend geerdeten Observed Facts extrahieren."]
                )[-6:]
            self._grounded_fact_notes = grounded_fact_notes(observed_facts)
            bundle = build_evidence_bundle(grounding_contract, evidence_items)
            fact_gaps = required_evidence_fact_gaps(
                grounding_contract,
                observed_facts,
                evidence_items,
            )
            if fact_gaps:
                bundle.missing_required_evidence = self._dedupe_ordered_strs(
                    list(bundle.missing_required_evidence) + list(fact_gaps)
                )
                if not bundle.incomplete_reason:
                    bundle.incomplete_reason = "missing_required_evidence"
                bundle.supports_full_answer = False
            else:
                self._evidence_gaps = [
                    gap
                    for gap in list(self._evidence_gaps or [])
                    if not str(gap).startswith("Vorläufig fehlende Vertragsevidenz vor Finalisierung:")
                ]
            if bundle.incomplete_reason == "truncated_evidence":
                _emit_recovery(
                    "truncated_evidence",
                    lt("Die Tool-Rückgabe ist begrenzt; die Antwort wird auf die "
                       "sichtbaren Ergebnisse kalibriert.",
                       "The tool output is limited. The answer is calibrated to the visible results."),
                )
            elif bundle.incomplete_reason == "insufficient_evidence":
                self._evidence_gaps = self._dedupe_ordered_strs(
                    list(self._evidence_gaps)
                    + ["Die vorhandene Tool-Evidenz reicht nicht für eine vollständige Antwort."]
                )[-6:]
                _emit_recovery(
                    "insufficient_evidence",
                    lt("Die vorhandene Tool-Evidenz reicht nicht für eine vollständige Antwort.",
                       "The available tool evidence is not enough for a complete answer."),
                )
            elif bundle.incomplete_reason == "missing_required_evidence":
                self._evidence_gaps = self._dedupe_ordered_strs(
                    list(self._evidence_gaps)
                    + [
                        (
                            "Es fehlt vertraglich geforderte Evidenz: "
                            + ", ".join(bundle.missing_required_evidence[:4])
                        )
                    ]
                )[-6:]
                _emit_recovery(
                    "insufficient_evidence",
                    lt("Vertraglich geforderte Evidenz fehlt. Die Antwort wird fail-closed konservativ gehalten.",
                       "Evidence required by the contract is missing. The answer is kept conservative."),
                )

            def _accepted_claims_complete_for_turn(
                envelope: AnswerEnvelope,
                accepted_claim_ids: List[str],
                rejected_claim_ids: List[str],
                candidate_facts: List[Any],
                contract: AnalysisContract,
            ) -> Tuple[bool, str]:
                accepted = set(accepted_claim_ids) - set(
                    rejected_claim_ids
                )
                accepted_envelope = AnswerEnvelope(
                    claims=[
                        claim
                        for claim in envelope.claims
                        if claim.id in accepted
                    ]
                )
                deliverable_ok, deliverable_reason = (
                    _envelope_matches_deliverable_for_turn(
                        accepted_envelope,
                        deliverable_kind=contract.deliverable_kind,
                    )
                )
                if not deliverable_ok:
                    return False, deliverable_reason
                requirements_ok, requirements_reason = (
                    response_requirements_complete(
                        envelope,
                        accepted_claim_ids,
                        rejected_claim_ids,
                        contract.response_requirements,
                    )
                )
                if not requirements_ok:
                    return False, requirements_reason
                if (
                    contract.deliverable_kind == "followup_questions"
                    and not accepted_followups_have_research_breadth(
                        envelope,
                        accepted_claim_ids,
                        rejected_claim_ids,
                        question_text=normalized_question,
                    )
                ):
                    return (
                        False,
                        "Die Anschlussfragen brauchen mindestens zwei "
                        "eigenständige inhaltlich-linguistische Fragen; "
                        "höchstens eine darf primär Datenqualität, "
                        "Tokenisierung oder Annotation behandeln.",
                    )
                if (
                    contract.deliverable_kind == "method_advice"
                    and not accepted_method_advice_addresses_quality_signals(
                        envelope,
                        accepted_claim_ids,
                        rejected_claim_ids,
                        candidate_facts,
                    )
                ):
                    return (
                        False,
                        "Die sichtbare POS-/Tokenbilanz enthält ein "
                        "Qualitätssignal. Vor einer inhaltlichen Deutung muss "
                        "mindestens ein Analyseschritt dieses Signal mit einer "
                        "systematischen Tokenisierungs-, Annotations- oder "
                        "POS-Validierung prüfen.",
                    )
                if not accepted_semantic_pattern_interpretation_is_substantive(
                    accepted_envelope.claims,
                    candidate_facts,
                    question_text=normalized_question,
                    analysis_family=contract.analysis_family,
                    deliverable_kind=contract.deliverable_kind,
                ):
                    return (
                        False,
                        "Die angeforderte Mustersynthese braucht mindestens "
                        "eine eigenständige Interpretation, die mehrere "
                        "sichtbare semantische Passagen gemeinsam deutet, "
                        "statt nur einzelne Treffer oder Reichweitengrenzen "
                        "aufzulisten.",
                    )
                if contract.analysis_family == "word_sketch_profile":
                    missing_sketch_facts = missing_word_sketch_profile_facts(
                        accepted_envelope.claims,
                        candidate_facts,
                    )
                    if missing_sketch_facts:
                        return (
                            False,
                            "Das grammatische Profil lässt sichtbare "
                            "Word-Sketch-Evidenz aus. Berücksichtige diese "
                            "Relationen oder Partnerzeilen im vollständigen "
                            "neuen Profil: "
                            + " | ".join(
                                fact.statement
                                for fact in missing_sketch_facts[:8]
                            ),
                        )
                    if not word_sketch_metric_units_are_clear(
                        accepted_envelope.claims
                    ):
                        return (
                            False,
                            "Wenn das grammatische Profil f oder f2 ausgibt, "
                            "muss es die Zähleinheiten knapp erklären: f zählt "
                            "indexierte Dependenzereignisse; f2 ist die "
                            "marginale Tokenhäufigkeit des Partners auf der "
                            "ausgewiesenen Basis.",
                        )
                    if not accepted_word_sketch_interpretation_is_substantive(
                        accepted_envelope.claims,
                        candidate_facts,
                    ):
                        return (
                            False,
                            "Das grammatische Profil braucht zusätzlich eine "
                            "knappe Synthese über die sichtbaren Relationsarten: "
                            "Sie muss deren unterschiedliche grammatische "
                            "Anbindungen gemeinsam deuten, ohne Tabellenzeilen "
                            "nur umzubenennen oder unbelegte Phrasen zu bilden.",
                        )
                if not accepted_claims_match_deliverable(
                    envelope,
                    accepted_claim_ids,
                    rejected_claim_ids,
                    deliverable_kind=contract.deliverable_kind,
                    question_text=normalized_question,
                    observed_facts=candidate_facts,
                    analysis_family=contract.analysis_family,
                ):
                    return (
                        False,
                        "Die verifizierten Claims erfüllen den angeforderten "
                        "Antworttyp noch nicht vollständig.",
                    )
                _covered, missing = _accepted_claim_evidence_coverage(
                    envelope,
                    accepted_claim_ids,
                    rejected_claim_ids,
                    candidate_facts,
                    evidence_items,
                    contract,
                )
                if missing:
                    return (
                        False,
                        "Die Synthese lässt bereits vorhandene, angeforderte "
                        "Evidenz unberücksichtigt: " + ", ".join(missing[:4]),
                    )
                return True, ""

            confirmation_guarded = (
                "one-sided confirmation of a universal corpus claim"
                in {
                    str(value or "").strip().casefold()
                    for value in grounding_contract.forbidden_claims
                }
            )
            retrieval_candidate_count = sum(
                str(getattr(fact, "fact_kind", "") or "").casefold()
                in {"kwic_example", "ranked_row"}
                for fact in observed_facts
            )
            # Semantic repairs preserve accepted claims and are independent of
            # transport retries. Confirmation-pressure turns scale their bounded
            # allowance with the evidence the verifier must account for.
            grounding_retry_budget = _budgets.retry_budget_fuer_restzeit(
                turn_state.started_at, turn_state.max_time,
                confirmation_guarded=confirmation_guarded,
                retrieval_candidate_count=retrieval_candidate_count,
            )  # P3.3: aus der Restzeit, nie groesser als zuvor.
            grounding_verifier = GroundingVerifier(
                run_structured_step=_run_structured_step,
                answer_envelope_doc=ANSWER_ENVELOPE_DOC,
                grounding_verifier_doc=GROUNDING_VERIFIER_DOC,
                answer_envelope_schema=lambda: answer_envelope_schema(
                    deliverable_kind=grounding_contract.deliverable_kind,
                    question_text=normalized_question,
                    response_requirements=(
                        grounding_contract.response_requirements
                    ),
                ),
                grounding_verdict_schema=grounding_verdict_schema,
                answer_envelope_cls=AnswerEnvelope,
                grounding_verdict_cls=GroundingVerdict,
                validate_answer_envelope=_validate_answer_envelope_for_turn,
                envelope_matches_deliverable_kind=(
                    _envelope_matches_deliverable_for_turn
                ),
                accepted_claims_complete=(
                    _accepted_claims_complete_for_turn
                ),
                keyness_interpretation_complete=(
                    accepted_keyness_interpretation_is_substantive
                ),
                ngram_interpretation_complete=(
                    accepted_ngram_interpretation_is_substantive
                ),
                word_sketch_interpretation_complete=(
                    accepted_word_sketch_interpretation_is_substantive
                ),
                word_sketch_units_complete=(
                    word_sketch_metric_units_are_clear
                ),
                kwic_reading_complete=(
                    accepted_kwic_interpretation_is_substantive
                ),
                separate_hypothesis_layers=bool(
                    _HYPOTHESIS_STRUCTURE_CONDITION_PATTERN.search(
                        normalized_question
                    )
                ),
                kwic_relation_adjudicator_doc=(
                    KWIC_RELATION_ADJUDICATOR_DOC
                ),
                question_text=normalized_question,
                initial_draft=initial_draft,
                # Atomic repairs preserve accepted claims. Confirmation-pressure
                # turns scale their bounded budget with the evidence they must
                # actually account for instead of silently dropping later rows.
                max_retries=grounding_retry_budget,
            )
            self._ra_emit_status(copilot_event_bus, "Verifikation")
            try:
                envelope, verdict = await grounding_verifier.run(
                    grounding_contract,
                    observed_facts,
                )
            except _VerifierTimeBudgetExceeded:
                # Fix 3: die Restzeit kippte mitten im Verifier-Protokoll.
                return _build_verifier_skipped_answer(
                    grounding_contract,
                    evidence_items,
                    initial_draft,
                )
            if not bundle.supports_full_answer and verdict.verdict == "pass":
                verdict.verdict = "conservative_only"
                verdict.needs_retry = False
                reason = "Die Evidenz erfüllt die vertraglichen Vollständigkeitsanforderungen nicht."
                if reason not in verdict.reasons:
                    verdict.reasons.append(reason)

            self._blocked_claims = blocked_claim_notes(envelope, verdict)
            self._last_grounding_verdict = verdict.to_dict()
            verifier_protocol_anomalies = list(
                getattr(verdict, "_verifier_protocol_anomalies", []) or []
            )
            if verifier_protocol_anomalies:
                self._last_grounding_verdict[
                    "verifier_protocol_anomalies"
                ] = verifier_protocol_anomalies
                logger.warning(
                    "Grounding verifier protocol recovered with anomalies: %s",
                    verifier_protocol_anomalies,
                )
            retrieval_assessments = list(
                getattr(
                    verdict,
                    "_retrieval_candidate_assessments",
                    [],
                )
                or []
            )
            if retrieval_assessments:
                self._last_grounding_verdict[
                    "retrieval_candidate_assessments"
                ] = retrieval_assessments
            retrieval_audit_diagnostics = dict(
                getattr(
                    verdict,
                    "_retrieval_audit_diagnostics",
                    {},
                )
                or {}
            )
            if retrieval_audit_diagnostics.get("required"):
                self._last_grounding_verdict[
                    "retrieval_audit_diagnostics"
                ] = retrieval_audit_diagnostics
                if (
                    retrieval_audit_diagnostics.get("status")
                    == "failed_closed"
                ):
                    logger.warning(
                        "Confirmation-retrieval audit failed closed: %s",
                        retrieval_audit_diagnostics,
                    )
            accepted_id_set = set(verdict.accepted_claim_ids)
            rejected_id_set = set(verdict.rejected_claim_ids)
            accepted_claims = [
                claim
                for claim in envelope.claims
                if claim.id in accepted_id_set
                and claim.id not in rejected_id_set
            ]
            rejected_claims = [
                claim
                for claim in envelope.claims
                if claim.id in rejected_id_set
            ]
            accepted_fact_ids = {
                fact_id
                for claim in accepted_claims
                for fact_id in claim.fact_ids
            }
            (
                accepted_claim_evidence_kinds,
                uncovered_required_claim_evidence,
            ) = _accepted_claim_evidence_coverage(
                envelope,
                verdict.accepted_claim_ids,
                verdict.rejected_claim_ids,
                observed_facts,
                evidence_items,
                grounding_contract,
            )
            verified_claims_shape_complete = accepted_claims_match_deliverable(
                envelope,
                verdict.accepted_claim_ids,
                verdict.rejected_claim_ids,
                deliverable_kind=active_contract.deliverable_kind,
                question_text=normalized_question,
                observed_facts=observed_facts,
                analysis_family=active_contract.analysis_family,
            )
            verified_response_requirements_complete, _requirements_reason = (
                response_requirements_complete(
                    envelope,
                    verdict.accepted_claim_ids,
                    verdict.rejected_claim_ids,
                    active_contract.response_requirements,
                )
            )
            verified_claims_complete = (
                verified_claims_shape_complete
                and verified_response_requirements_complete
                and not uncovered_required_claim_evidence
            )

            def _claim_kind_counts(claims: List[Any]) -> Dict[str, int]:
                counts: Dict[str, int] = {}
                for claim in claims:
                    kind = str(getattr(claim, "claim_kind", "") or "unknown")
                    counts[kind] = counts.get(kind, 0) + 1
                return counts

            self._active_analysis_contract = {
                **grounding_contract.to_dict(),
                "observed_fact_ids": [fact.id for fact in observed_facts][:8],
                "evidence_manifest": evidence_manifest(evidence_items),
                "present_evidence": list(bundle.present_evidence),
                "missing_required_evidence": list(bundle.missing_required_evidence),
                "grounding_verdict": verdict.verdict,
                "accepted_claim_count": len(verdict.accepted_claim_ids),
                "rejected_claim_count": len(verdict.rejected_claim_ids),
                "grounding_diagnostics": {
                    "observed_fact_count": len(observed_facts),
                    "generated_claim_count": len(envelope.claims),
                    "claim_retention_rate": round(
                        len(accepted_claims) / len(envelope.claims),
                        4,
                    )
                    if envelope.claims
                    else 0.0,
                    "accepted_claim_kinds": _claim_kind_counts(
                        accepted_claims
                    ),
                    "rejected_claim_kinds": _claim_kind_counts(
                        rejected_claims
                    ),
                    "accepted_fact_reference_count": len(
                        accepted_fact_ids
                    ),
                    "fact_binding_repair_count": len(
                        list(
                            getattr(
                                envelope,
                                "_fact_binding_repairs",
                                [],
                            )
                            or []
                        )
                    ),
                    "projected_fact_citation_strip_count": int(
                        getattr(
                            envelope,
                            "_projected_fact_citation_strip_count",
                            0,
                        )
                        or 0
                    ),
                    "relation_protocol_recovery_count": int(
                        getattr(
                            envelope,
                            "_relation_protocol_recovery_count",
                            0,
                        )
                        or 0
                    ),
                    "relation_schema_aliases": list(
                        getattr(
                            envelope,
                            "_relation_schema_aliases",
                            [],
                        )
                        or []
                    ),
                    "visible_duplicate_merge_count": int(
                        getattr(
                            envelope,
                            "_visible_duplicate_merge_count",
                            0,
                        )
                        or 0
                    ),
                    "repeated_verified_claim_drop_count": int(
                        getattr(
                            envelope,
                            "_repeated_verified_claim_drop_count",
                            0,
                        )
                        or 0
                    ),
                    "accepted_claim_evidence_kinds": (
                        accepted_claim_evidence_kinds
                    ),
                    "uncovered_required_claim_evidence": (
                        uncovered_required_claim_evidence
                    ),
                    "retrieval_audit": (
                        retrieval_audit_diagnostics
                        if retrieval_audit_diagnostics.get("required")
                        else {}
                    ),
                },
                "model_reported_evidence_gap_count": len(
                    envelope.evidence_gaps
                ),
            }
            _refresh_session_state()
            _emit_grounding_event(
                verdict.verdict,
                analysis_family=active_contract.analysis_family,
                rejected_claim_count=len(verdict.rejected_claim_ids),
                evidence_gaps=self._evidence_gaps,
            )

            # Welches Experiment etwas getragen hat. Siehe Fachmodul.
            self._turn_ausgewertete_evidenz = getragene_evidenz(
                envelope.claims, verdict.accepted_claim_ids, observed_facts
            )

            self._ra_emit_status(copilot_event_bus, "Antwort")
            _zwischenstand("3a_entwurf_vor_claims", str(initial_draft or ""), sitzung=getattr(self.session, "session_id", ""))
            _zwischenstand("3b_verdikt", verdikt_bilanz(verdict, envelope), sitzung=getattr(self.session, "session_id", ""))
            if verdict.verdict == "pass" and verified_claims_complete:
                verified_claim_markdown = build_verified_claim_markdown(
                    envelope,
                    verdict.accepted_claim_ids,
                    observed_facts,
                    deliverable_kind=active_contract.deliverable_kind,
                    question_text=normalized_question,
                    evidence_items=evidence_items,
                    evidence_gaps=self._evidence_gaps,
                    retrieval_candidate_assessments=(
                        retrieval_assessments
                    ),
                    include_diagnostic_appendix=False,
                )
                if verified_claim_markdown:
                    self._active_analysis_contract[
                        "grounding_output_mode"
                    ] = "verified_claims"
                    _refresh_session_state()
                    _zwischenstand("3c_claims_rebuilt", verified_claim_markdown, sitzung=getattr(self.session, "session_id", ""))
                    return verified_claim_markdown

            if verdict.rejected_claim_ids:
                _emit_recovery(
                    "unsupported_claim",
                    lt("Unbelegte Claims wurden blockiert. Die Ausgabe bewahrt "
                       "die verifizierten Modellclaims; ein mechanischer "
                       "Ersatzbericht wird nicht erzeugt.",
                       "Unsupported claims were blocked. The output keeps the "
                       "verified model claims, no mechanical replacement "
                       "report is written."),
                )
            self._active_analysis_contract["grounding_output_mode"] = (
                "verified_claims_partial"
                if verdict.accepted_claim_ids
                else (
                    "deterministic_factual"
                    if _allows_deterministic_factual_fallback(
                        active_contract
                    )
                    else "synthesis_unavailable"
                )
            )
            _refresh_session_state()
            boden = bodentext_statt_absage(   # siehe recipe_runtime
                verdict.accepted_claim_ids,
                _allows_deterministic_factual_fallback(active_contract),
                lambda: _deterministisch_gedeckter_text(
                    grounding_contract, evidence_items, initial_draft,
                    grund=VERIFIER_UNBESTAETIGT_NOTE),  # Verdikt, nicht Zeit
                self._evidence_gaps)
            if boden:
                return boden
            return build_claim_preserving_grounded_markdown(
                active_contract,
                envelope,
                verdict.accepted_claim_ids,
                verdict.rejected_claim_ids,
                observed_facts,
                evidence_items,
                evidence_gaps=self._evidence_gaps,
                deliverable_complete=(
                    verified_claims_complete
                    and bundle.supports_full_answer
                ),
                question_text=normalized_question,
                retrieval_candidate_assessments=retrieval_assessments,
                include_diagnostic_appendix=False,
            )

        async def _sofortlandung(phase: str) -> str | None:
            """Landung ohne Modellaufruf. Politik: deterministic_landing.

            Gemessen am 2026-09-02: die Zaehlfrage hatte nach der
            deterministischen Vorplanrunde ihre Pflichtevidenz komplett und
            bekam trotzdem noch einen Modellaufruf von 67 s, der die schon
            feststehende Antwort nur wiederholte.
            """
            evidenz = list(self._turn_evidence_items or ())
            pending = (_pending_required_evidence_tools(active_contract)[0]
                       if ground_analysis and active_contract is not None
                       else ["kein_kontrakt"])
            kind, kopf = sofortlandungsentscheid(
                phase, normalized_question,
                corpus_card_from_ui_context(self.ui_context),
                active_contract, pending, evidenz)
            if not kind:
                return None
            rumpf = ""
            if evidenz and ground_analysis and active_contract is not None:
                rumpf = await _build_grounded_final_answer(
                    deterministic_only=True) or ""
            text = "\n\n".join(t for t in (kopf, rumpf) if t.strip())
            if not text.strip():
                return None
            # Gemessen am 2026-09-03: ohne dies endete die Kartenlandung
            # (kein Rumpf, kein Werkzeug) in der Stufe "Vorlauf".
            if self._aktuelle_stufe != "Antwort":
                self._ra_emit_status(copilot_event_bus, "Antwort")
            _emit_recovery(kind, SOFORTLANDUNG_GRUND)
            return self._ra_finish_turn(copilot_event_bus, normalized_question,
                                        text, stream_emit=stream)

        async def _finalize_grounded_answer(**kwargs: Any) -> str:
            """Fix 1+4: runden-/schritt-gekappte Landung als REGULAERER
            completed-Abschluss, nie als Server-Salvage. Reisst die
            Finalisierungs-Synthese (Transport/Zeit), finalisiert dieser Pfad
            deterministisch aus der Turn-Evidenz statt die Ausnahme bis zum
            Server (done_status='timeout', Zeitbanner) zu propagieren.
            """
            try:
                content = await _build_grounded_final_answer(**kwargs)
            except CopilotTurnCancelled:
                raise
            except LLMRequestError as exc:
                # P2 (Runde 4): der Engine-Tod in der Finalisierung darf die
                # Notkomposition nicht als "completed" ausgeben. Die
                # Ausnahme wird als copilot.error emittiert — die Route
                # klassifiziert die Notkomposition dann ehrlich als
                # partial_on_engine_error (Ausfall ist kein Ergebnis).
                logger.exception("Finalisierungs-Synthese warf (Engine)")
                self._emit_output(
                    copilot_event_bus,
                    {"event": "copilot.error", "error": str(exc)},
                )
                content = None
            except Exception:
                logger.exception("Finalisierungs-Synthese warf; deterministisch")
                content = None
            if content:
                return content
            # LLM-freier Abschluss aus denselben Observed Facts, ohne Zeitbanner.
            fallback: str | None = None
            try:
                fallback = self.build_salvage_markdown()
            except Exception:
                logger.exception("build_salvage_markdown-Fallback fehlgeschlagen")
            if fallback:
                return fallback
            return self._ra_build_fail_closed_grounding_markdown(
                "Die Antwort wurde deterministisch aus der sichtbaren "
                "Tool-Evidenz finalisiert; die vollständige LLM-Verifikation "
                "wurde nicht mehr abgeschlossen."
            )

        if normalized_question and role == "user":
            # Fix 2: fallback-lose Rezept-Vorbedingung deterministisch gegen die
            # Korpus-Karte pruefen, VOR dem ersten LLM-Call (0 Calls). Verletzt
            # (z.B. verlauf ohne Datumsfeld) -> ehrliche Kurzschluss-Antwort aus
            # dem Rezept-Feld ohne Tool-Schleife; das ist die Absage einer
            # methodisch unmoeglichen Analyse (kontrast/docset-Fallback laeuft
            # normal), kein Abwuergen der Interpretation.
            precondition = recipe_precondition_status(
                self._active_recipe_id,
                corpus_card_from_ui_context(self.ui_context),
                normalized_question,
            )
            briefing_note = str(precondition.get("briefing_note", "") or "")
            if briefing_note:
                # V7 (H9/C2): ausdrueckliche Split-QA-Nachfrage — der Kontrast
                # LAEUFT ueber die technische Achse; der Rahmungshinweis geht
                # als System note in den Turn (KV-Kern bleibt byte-stabil).
                self.session.append(
                    {
                        "role": "user",
                        "content": f"[System note: {briefing_note}]",
                    },
                    project=self.project,
                )
            if precondition.get("short_circuit"):
                short_answer = precondition_unmet_answer(
                    self._active_recipe_id,
                    str(precondition.get("alternative", "") or ""),
                )
                if short_answer:
                    self.state = State.FINISHED
                    # Kurzschluss kehrt vor dem ``_run()``-finally zurueck: den
                    # Usage-Report (0 Calls, recipe_id) hier selbst setzen.
                    self._last_turn_usage = turn_usage_snapshot(
                        turn_state,
                        start_time=start_time,
                        recipe_id=(
                            turn_state.recipe_id or self._active_recipe_id
                        ),
                        session=self.session,
                    )
                    self._active_analysis_contract = {
                        **(self._active_analysis_contract or {}),
                        "grounding_output_mode": "recipe_precondition_unmet",
                        "recipe_id": self._active_recipe_id,
                    }
                    _refresh_session_state()
                    _emit_recovery(
                        "recipe_precondition_unmet",
                        lt("Die Korpus-Karte erfüllt eine Rezept-Vorbedingung "
                           "nicht ({}); der Turn antwortet deterministisch und ehrlich, "
                           "ohne Werkzeug-Runden.",
                           "The corpus card does not meet a recipe precondition "
                           "({}). The turn answers deterministically, without "
                           "tool rounds.").format(str(precondition.get("reason", "") or "")),
                    )
                    self._ra_emit_status(copilot_event_bus, "Antwort")
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        short_answer,
                        stream_emit=stream,
                    )
            try:
                active_contract = await _run_analysis_contract_preflight()
            except CopilotTurnCancelled:
                return ""
            except LLMRequestError as exc:
                return self._ra_lande_nach_modellstoerung(
                    copilot_event_bus, normalized_question, turn_state,
                    start_time, exc, stream=stream)
            if self.cancel_requested:
                self.state = State.FINISHED
                return ""
            if active_contract is not None:
                # clarify ZUERST: der Kontrakt kann dabei auf tool_analysis
                # umschlagen, danach gilt die gemeinsame Uebernahme.
                if active_contract.mode == "clarify":
                    weiter, rueckfrage = clarify_als_zusatz(
                        active_contract, self._available_tool_names())
                    if not weiter:
                        self._active_analysis_contract = active_contract.to_dict()
                        return self._ra_finish_turn(
                            copilot_event_bus, normalized_question,
                            rueckfrage, stream_emit=stream)
                    self._turn_trailing_clarification = rueckfrage
                    _emit_recovery("clarify_als_zusatz", CLARIFY_ZUSATZ_NOTE)
                self._active_analysis_contract = active_contract.to_dict()
                turn_state.active_allowed_tools = list(active_contract.allowed_tools)
                ground_analysis = active_contract.mode == "tool_analysis"
                _refresh_session_state()
            elif turn_state.fail_closed_grounding_reason:
                if self._available_tool_names():
                    # R2: Freier Modus statt Kontrakt-Ablehnung. Solange
                    # Werkzeuge verfuegbar sind, laeuft der Turn ohne
                    # Kontrakt weiter (Rezept- bzw. Freier-Modus-Briefing);
                    # der Referenz-Antwortpfad blockiert weiterhin
                    # Fabrikation. Die ehrliche Notiz landet im Event.
                    self._active_analysis_contract = {
                        **(self._active_analysis_contract or {}),
                        "grounding_output_mode": "free_mode",
                    }
                    _refresh_session_state()
                    _emit_recovery(
                        "grounding_free_mode",
                        lt("Kein gültiger AnalysisContract ({}) Der Copilot arbeitet ohne Kontrakt im freien "
                           "Modus weiter; Zahlen und Zitate bleiben beleg- und "
                           "referenzpflichtig.",
                           "No valid analysis contract ({}). The Copilot continues "
                           "without a contract in free mode. Numbers and quotations "
                           "still need evidence and references.").format(
                            turn_state.fail_closed_grounding_reason),
                    )
                else:
                    final_content = self._ra_build_fail_closed_grounding_markdown(
                        turn_state.fail_closed_grounding_reason
                    )
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        final_content,
                        stream_emit=stream,
                    )
            if (
                active_contract is None
                or active_contract.mode != "tool_analysis"
            ):
                self._ra_launch_research_worker(
                    copilot_event_bus,
                    normalized_question,
                    role,
                    principal,
                    dispatch_is_async=dispatch_is_async,
                )

        async def _dispatch(tc: Dict[str, Any], tokens: int) -> None:
            self._raise_if_cancelled()
            name = tc["function"]["name"]
            args = self._tool_args(tc)
            signature = self._tool_signature(tc)
            start = time.perf_counter()
            _beginn = getattr(self, "_turn_start_perf", 0.0)
            self._emit_output(copilot_event_bus, {
                "event": "start",
                "tool": name,
                **({"t_rel": round(start - float(_beginn), 3)} if _beginn else {}),
            })
            out = None
            for i in range(self.tool_retries + 1):
                self._raise_if_cancelled()
                try:
                    if dispatch_is_async:
                        out = await self.dispatch(tc, self.token)
                    else:
                        out = await asyncio.to_thread(self.dispatch, tc, self.token)
                    if isinstance(out, dict) and out.get("status") == "retry":
                        delay = float(out.get("delay", 0))
                        _emit_recovery(
                            "tool_retry",
                            lt("Tool {name} meldete Retry. Neuer Versuch in {delay:.1f}s.",
                               "Tool {name} asked for a retry. Retrying in {delay:.1f}s.").format(
                                name=name, delay=delay),
                        )
                        await asyncio.sleep(delay)
                        continue
                    break
                except Exception as exc:  # pragma: no cover - tool failure
                    # NOTE: no observability.record here — the single
                    # post-loop record below reports the final status
                    # (a per-attempt record double-counted ``<tool>.errors``).
                    out = {"status": "error", "message": str(exc)}
                    if capability_unavailable_reason(out):
                        # Capability-Fehler sind deterministisch: ein
                        # identischer Retry kann nur identisch scheitern.
                        break
                    if i < self.tool_retries:
                        delay = 2**i * 0.1
                        _emit_recovery(
                            "tool_retry",
                            lt("Tool {name} fehlgeschlagen. Neuer Versuch in {delay:.1f}s.",
                               "Tool {name} failed. Retrying in {delay:.1f}s.").format(
                                name=name, delay=delay),
                        )
                        await asyncio.sleep(delay)
                        continue
                    break

            self._raise_if_cancelled()
            vermerke_abgabe(self, name, out)
            if isinstance(out, dict) and out.get("status") == "retry":
                # A2: the retry budget is exhausted but the tool still asked
                # for a retry. Without this coercion the lingering retry dict
                # was recorded as a SUCCESS (ok only flips on "error") and fed
                # downstream as evidence. Keep the original payload for
                # diagnostics.
                out = {
                    "status": "error",
                    "message": (
                        "retry budget exhausted "
                        f"({self.tool_retries + 1} attempts)"
                    ),
                    "retry_payload": out,
                }
            out = werkzeugausgabe_ohne_betreiberpfad(_enrich_cql_error(name, args, mit_folgenbereich(name, mit_fassungsverteilung(name, out))))
            capability_reason = capability_unavailable_reason(out)
            if capability_reason:
                # Fix 4 (Eval-Runde 1): Feature-Gate- und Semantic-Asset-Fehler
                # sind Korpus-Wahrheiten. GENAU EIN ehrliches unavailable-Item
                # statt einer Recovery-Kaskade.
                first_occurrence = (
                    name not in self._turn_capability_unavailable_tools
                )
                # Die Grenze mit einem AUSWEG. Der Harnisch kennt die
                # Attributebenen des Korpus aus dem UI-Kontext, und wenn
                # er sie kennt, muss er sie nennen. Live kostete das
                # Schweigen einen ganzen Turn: frequency_list mit
                # group_by='pos' auf einem Korpus ohne POS scheiterte, die
                # Meldung sagte "eine fachliche Alternative waehlen" ohne
                # eine zu nennen, und das Modell hoerte auf.
                out = capability_unavailable_result(
                    name,
                    out,
                    args=args,
                    vorhandene_ebenen=[
                        str(a) for a in
                        ((self.ui_context or {}).get("corpus_attributes") or ())
                    ],
                )
                # Nennt die Absage einen anderen Argumentwert DESSELBEN
                # Werkzeugs, bleibt es ungesperrt (Kandidat 3, Frage 1: die
                # Sperre nahm den Ausweg wieder weg, das Modell gab auf).
                ausweg = str(out.get("ausweg") or "")
                if not ausweg:
                    self._turn_capability_unavailable_tools[name] = capability_reason
                if first_occurrence:
                    _emit_recovery(
                        "argument_not_available" if ausweg else "tool_not_available",
                        lt("{name} wird nicht gesperrt. {ausweg}",
                           "{name} is not blocked. {ausweg}").format(name=name, ausweg=ausweg)
                        if ausweg else lt(
                            "{name} ist für dieses Korpus nicht verfügbar "
                            "(fehlende Capability). Das Werkzeug wird für "
                            "diesen Turn nicht erneut angeboten.",
                            "{name} is not available for this corpus (missing "
                            "capability). The tool is not offered again in this turn.",
                        ).format(name=name),
                    )

            duration = (time.perf_counter() - start) * 1000
            if self.observability:
                status = out.get("status", "ok") if isinstance(out, dict) else "ok"
                self.observability.record(
                    self.session.session_id,
                    name,
                    tokens=tokens,
                    duration_ms=duration,
                    status=status,
                )

            payload = {"tool": name, "data": out}
            ok = True
            if isinstance(out, dict) and out.get("status") == "error":
                ok = False
            self._record_tool_outcome(
                name,
                args,
                out,
                ok=ok,
                signature=signature,
            )
            if not ok:
                exposed_tools = [
                    str(spec.get("function", {}).get("name", "") or "").strip()
                    for spec in self._ra_active_tool_specs(turn_state)
                    if isinstance(spec, dict)
                ]
                _record_tool_call_anomaly(
                    "tool_result_error",
                    candidate_calls=[tc],
                    exposed_tools=exposed_tools,
                    note=self._compact_runtime_text(
                        f"{name}({args}) -> {out}",
                        limit=240,
                    ),
                )
            # R2: Evidenz wird in JEDEM Modus gesammelt (auch frei), damit der
            # Referenz-Antwortpfad Belege hat. Die IDs kommen aus dem vor der
            # Runde erstellten Plan (Anforderungsreihenfolge); der Flush nach
            # der Runde haelt die Reihenfolge auch bei nebenlaeufigen
            # read-only-Batches deterministisch. Model-generated provider call
            # IDs koennen lange Ziffernketten sein; Fact-IDs daraus waren fuer
            # lokale Modelle copy-feindlich, die Original-Call-ID bleibt als
            # tool_call_id erhalten.
            evidence_plan = self._round_evidence_plan.get(id(tc))
            evidence_id = ""
            if evidence_plan is not None:
                evidence_id, evidence_family = evidence_plan
                raw_tool_call_id = str(tc.get("id", "") or "").strip()
                evidence_item = make_evidence_item(
                    item_id=evidence_id,
                    tool=name,
                    tool_call_id=raw_tool_call_id,
                    query=args,
                    output=out,
                    analysis_family=evidence_family,
                )
                self._round_evidence_items[id(tc)] = evidence_item.to_dict()
            tool_result = {
                "toolName": name,
                "ok": ok,
                "ts": int(time.time() * 1000),
                "input": args,
                "output": out,
            }
            self._emit_output(copilot_event_bus, {"event": "copilot.tool_result", "toolResult": tool_result})
            # Die Dauer ist hier bereits gerechnet (Zeile darueber, in ms).
            # Sie verfiel bisher in ein OTEL-Attribut, das ohne
            # CANDYCONC_ENABLE_OTEL=1 in einen No-Op-Span faellt.
            self._emit_output(copilot_event_bus, {
                "event": "end",
                "tool": name,
                "duration_ms": round(float(duration), 1),
                **({"t_rel": round(time.perf_counter() - float(_beginn), 3)}
                   if _beginn else {}),
            })
            if self.project:
                self.project.add_ai_output(json.dumps(payload))
                lineage.log_tool(
                    self.project,
                    name,
                    args,
                    out,
                    started_at=start,
                    finished_at=start + duration / 1000,
                )
            model_payload = _tool_output_for_model(out, werkzeug=name)
            if isinstance(model_payload, dict):  # Ergebnisse kommen in Abschlussreihenfolge:
                model_payload = {"aufruf": {"werkzeug": name, "argumente": args}, **model_payload}
            if evidence_id and isinstance(model_payload, dict):
                # Die Evidenz-ID gehoert in die Modellsicht, damit die
                # Antwort sie als {{ev:ID.feld}} referenzieren kann.
                model_payload = {"evidence_id": evidence_id, **model_payload}
            self.session.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(
                        model_payload,
                        ensure_ascii=False,
                    ),
                },
                project=self.project,
            )
            _refresh_session_state()
            self.session.summarise(
                project=self.project,
                runtime_state=self._build_runtime_state(normalized_question),
            )

        async def _run_preplanned_first_round() -> None:
            # H10/G1+H11/B1: deterministische Schritt-1-Vorplanung (Rezept
            # ODER freier Modus, dort rezeptlos). Runde 1 plant und ruft der
            # Harness selbst (0 LLM-Planung); Fehler -> Modellplanung.
            if turn_state.tool_rounds:
                return
            auslassungen: List[str] = []
            try:
                planned, zusatz_tools = preplan_with_contract(
                    self._active_recipe_id, normalized_question, corpus_card_from_ui_context(self.ui_context),
                    available_tools=self._available_tool_names(),
                    gated_tools=self._turn_capability_unavailable_tools,
                    contract_tools=(list(active_contract.allowed_tools)
                                    if active_contract is not None else None), auslassungen=auslassungen)
                if zusatz_tools and active_contract is not None:
                    active_contract.allowed_tools = list(zusatz_tools)
                    turn_state.active_allowed_tools = list(zusatz_tools)
                    self._active_analysis_contract = active_contract.to_dict()
            except Exception:
                logger.exception("Schritt-1-Vorplanung uebersprungen")
                return
            if not planned:
                return
            self._ra_emit_status(copilot_event_bus, "Werkzeuge", "; ".join(auslassungen))
            self.session.append(
                {"role": "assistant", "tool_calls": planned},
                project=self.project)
            try:
                await self._ra_run_tool_batches(
                    turn_state, copilot_event_bus, planned,
                    active_contract=active_contract, dispatch=_dispatch)
                turn_state.tool_rounds += 1
            except CopilotTurnCancelled:
                raise
            except Exception:
                # Historie heilen: unbeantwortete geplante Calls bekommen
                # ein ehrliches Fehler-Result, danach plant das Modell.
                logger.exception("Vorgeplante Runde abgebrochen")
                for tc in unanswered_tool_calls(planned, self.session.history):
                    self._ra_append_blocked_tool_result(
                        copilot_event_bus, normalized_question, tc,
                        PREPLAN_ABORT_RESULT)

        async def _collect(chunks: Any) -> Tuple[Dict[str, Any], List[asyncio.Task]]:
            message: Dict[str, Any] = {"role": "assistant"}
            content_parts: List[str] = []
            tool_calls: List[Dict[str, Any]] = []
            last_choice: Dict[str, Any] | None = None
            emitted_semantic_or_tool = False
            async def _iterate() -> AsyncIterator[Any]:
                if hasattr(chunks, "__aiter__"):
                    async for c in chunks:
                        yield c
                else:
                    for c in chunks:
                        yield c

            try:
                async for chunk in _iterate():
                    self._raise_if_cancelled()
                    if isinstance(chunk, dict):
                        previous_route = self._last_llm_route
                        previous_model = self._last_llm_model
                        self._last_llm_route = str(chunk.get("_cc_route", "") or self._last_llm_route)
                        self._last_llm_model = str(chunk.get("_cc_model", "") or self._last_llm_model)
                        if (
                            self._last_llm_route != previous_route
                            or self._last_llm_model != previous_model
                        ):
                            _refresh_session_state()
                    last_choice = chunk.get("choices", [{}])[0]
                    delta = last_choice.get("delta")
                    if delta:
                        delta_payload = dict(delta)
                        if ground_analysis and "content" in delta_payload:
                            delta_payload.pop("content", None)
                        if delta_payload:
                            if set(delta_payload) - {"role"}:
                                emitted_semantic_or_tool = True
                            self._emit_output(copilot_event_bus, {"delta": delta_payload})
                        if delta.get("role"):
                            message["role"] = delta["role"]
                        content_delta = self._stream_content_delta(chunk)
                        if content_delta:
                            content_parts.append(content_delta)
                        self._merge_stream_tool_call_deltas(tool_calls, chunk)
                    elif last_choice.get("message"):
                        message = last_choice["message"]
                    await asyncio.sleep(0)
            except LLMRequestError as exc:
                exc.response_started = emitted_semantic_or_tool
                raise
            except Exception as exc:
                if emitted_semantic_or_tool:
                    from candyconc.services import llm_client as _lc
                    raise LLMRequestError(
                        kind=LLMErrorKind.TRANSPORT, message=_STREAM_ABBRUCH_HINWEIS,
                        retryable=bool(getattr(_lc, "_is_retryable_exception",
                                               lambda _e: False)(exc)),
                        original=exc, response_started=True,
                    ) from exc
                raise
            if content_parts:
                message["content"] = "".join(content_parts)
            if tool_calls:
                message["tool_calls"] = tool_calls
            return {
                "choices": [
                    {"message": message, **({"finish_reason": last_choice.get("finish_reason")} if last_choice else {})}
                ]
            }, []

        async def _run() -> str:
            nonlocal chunks, max_time
            step_i = 0
            forced_tool_retry_count = 0
            if normalized_question and role == "user" and chunks is None:
                gelandet = await _sofortlandung("vor_vorplan")
                if gelandet is None:
                    gelandet = await _sofortlandung("nach_vorplan")
                if gelandet is not None:
                    return gelandet
            elif normalized_question and role == "user":
                # F-66: streamend laeuft NUR die Vorplanrunde (Grundevidenz
                # fuer den Deutungs-Call); die Sofortlandung bleibt dem
                # nicht-streamenden Pfad vorbehalten.
                await _run_preplanned_first_round()

            async def _materialize_result(
                candidate: Any,
            ) -> Tuple[Dict[str, Any], List[asyncio.Task]]:
                if (
                    hasattr(candidate, "__iter__")
                    or hasattr(candidate, "__aiter__")
                ) and not isinstance(candidate, dict):
                    if stream:
                        return await _collect(candidate)
                    last = None
                    if hasattr(candidate, "__aiter__"):
                        async for chunk in candidate:
                            last = chunk
                    else:
                        for chunk in candidate:
                            last = chunk
                    return last or {}, []
                return candidate, []

            while True:
                self._raise_if_cancelled()
                if chunks is not None:
                    result, tasks = await _materialize_result(chunks)
                    chunks = None
                else:
                    # Nach der Werkzeugphase (Praedikat wie _ra_invoke_llm_ungebucht) schreibt der Aufruf die Antwort.
                    if self._ra_tool_rounds_exhausted(turn_state) and self._aktuelle_stufe != "Antwort":
                        self._ra_emit_status(copilot_event_bus, "Antwort")
                    result, tasks = await self._ra_call_llm_with_recovery(
                        turn_state,
                        copilot_event_bus,
                        consume=_materialize_result,
                    )
                self._raise_if_cancelled()
                choice = result["choices"][0]
                finish_reason = choice.get("finish_reason")
                msg = choice["message"]
                message_tool_calls = msg.get("tool_calls") if isinstance(msg.get("tool_calls"), list) else []
                current_exposed_tools = [
                    str(spec.get("function", {}).get("name", "") or "").strip()
                    for spec in self._ra_active_tool_specs(turn_state)
                    if isinstance(spec, dict)
                ]

                # Process control frames in the response
                raw_content = msg.get("content", "")
                if raw_content:
                    cleaned_content, frames = self._process_llm_response(
                        raw_content, copilot_event_bus
                    )

                    # Check if we need to wait for user interaction
                    has_clarify = any(ft == "CLARIFY" for ft, _ in frames)
                    has_action_requiring_approval = any(
                        ft == "ACTION" and self._should_require_approval(fd)
                        for ft, fd in frames
                    )

                    if has_clarify:
                        return self._ra_pause_turn(
                            normalized_question, cleaned_content, State.WAITING_CLARIFICATION)

                    if has_action_requiring_approval:
                        return self._ra_pause_turn(
                            normalized_question, cleaned_content, State.WAITING_APPROVAL)

                    # Update msg content with cleaned version (without control frames)
                    msg["content"] = cleaned_content
                else:
                    cleaned_content = ""

                pseudo_tool_calls = _pseudo_tool_calls_from_content(cleaned_content or raw_content)
                if pseudo_tool_calls and not message_tool_calls:
                    _record_tool_call_anomaly(
                        "pseudo_tool_calls_in_content",
                        finish_reason=finish_reason,
                        candidate_calls=pseudo_tool_calls,
                        exposed_tools=current_exposed_tools,
                        content_preview=cleaned_content or raw_content,
                        note=(
                            "Das Modell hat Tool-Calls als normalen Antworttext ausgegeben; "
                            "diese Pseudo-Calls wurden nicht als echte Tool-Ausführung gezählt."
                        ),
                    )

                if finish_reason == "tool_calls" and not message_tool_calls:
                    _record_tool_call_anomaly(
                        "empty_tool_calls_finish_reason",
                        finish_reason=finish_reason,
                        candidate_calls=[],
                        exposed_tools=current_exposed_tools,
                        content_preview=cleaned_content or raw_content,
                        note=(
                            "Der LLM-Endpunkt signalisierte tool_calls, aber es kam kein "
                            "gültiger Tool-Call im Response an."
                        ),
                    )

                # Der leere Modell-Output ist ein Ausfall (empty_output.py,
                # gelesen am Lauf 4, Runde 1): ein Retry je Turn, danach
                # ehrliche Klassifikation statt stillen Weiteraufrufs.
                _leer = empty_output.entscheidung(
                    finish_reason, cleaned_content, message_tool_calls,
                    turn_state.empty_stop_retries,
                    bool(self._turn_evidence_items), bool(current_exposed_tools))
                if (cleaned_content or "").strip() or message_tool_calls:
                    turn_state.empty_stop_retries = 0  # ein Retry je Vorfall
                if _leer == "wiederhole":
                    turn_state.empty_stop_retries += 1
                    _emit_recovery("empty_output_retry", empty_output.HINWEIS)
                    self.state = State.WAITING_LLM
                    continue
                if (_leer == "stoerung" and ground_analysis
                        and turn_state.schrittdecke_erreicht):
                    # If the step-limit draft is still empty after its retry,
                    # continue synthesis with the collected evidence.
                    final_content = await _finalize_grounded_answer()
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        final_content,
                        stream_emit=stream,
                    )
                if _leer == "stoerung" and not (
                        ground_analysis and finish_reason == "length"):
                    raise LLMRequestError(
                        kind=LLMErrorKind.INVALID_RESPONSE,
                        message="Leerer Modelloutput, auch nach einem Retry (finish_reason="
                                + str(finish_reason) + ").",
                        retryable=False)
                # "stoerung" mit length+Grounding faellt in den Zweig unten
                # und finalisiert deterministisch aus der Turn-Evidenz.

                if finish_reason == "length" and not msg.get("tool_calls"):
                    if ground_analysis:
                        # Fail-closed: abgeschnittener Prosa-Text ist per
                        # Konstruktion ungegroundet — deterministische
                        # Finalisierung wie bei max_steps/timeout, nie den
                        # rohen Truncat ausliefern.
                        final_content = await _finalize_grounded_answer()
                        return self._ra_finish_turn(
                            copilot_event_bus,
                            normalized_question,
                            final_content,
                            stream_emit=stream,
                        )
                    if turn_state.output_resume_count >= 2:
                        return self._ra_finish_turn(
                            copilot_event_bus,
                            normalized_question,
                            cleaned_content,
                            stream_emit=False,
                        )

                    self.session.append({"role": "assistant", "content": cleaned_content},
                                        project=self.project)
                    self.session.append(
                        {"role": "user", "content": (
                            "[System note: Deine letzte Antwort wurde am "
                            "Ausgabelimit abgeschnitten. Fahre exakt dort "
                            "fort, ohne den bisherigen Text zu wiederholen.]")},
                        project=self.project)
                    self.session.summarise(
                        project=self.project,
                        runtime_state=self._build_runtime_state(normalized_question),
                    )
                    turn_state.output_resume_count += 1
                    _emit_recovery(
                        "output_resume",
                        lt("Die letzte Modellantwort wurde abgeschnitten und wird fortgesetzt.",
                           "The last model reply was cut off and is continued."),
                    )
                    self.state = State.WAITING_LLM
                    continue

                if finish_reason == "stop" or "tool_calls" not in msg:
                    if (
                        ground_analysis
                        and active_contract is not None
                        and turn_state.forced_next_tools
                        and step_i + 1 < max_steps
                        and forced_tool_retry_count < 1
                        and not self._ra_tool_rounds_exhausted(turn_state)
                    ):
                        _record_tool_call_anomaly(
                            "required_tool_not_called",
                            finish_reason=finish_reason,
                            candidate_calls=message_tool_calls,
                            exposed_tools=current_exposed_tools,
                            content_preview=cleaned_content or raw_content,
                            note=(
                                "Der Copilot sollte fehlende Vertragsevidenz mit dem "
                                "erzwungenen Tool-Space einsammeln, hat aber ohne Tool-Call gestoppt."
                            ),
                        )
                        self.session.append(
                            {
                                "role": "assistant",
                                "content": cleaned_content or msg.get("content", ""),
                            },
                            project=self.project,
                        )
                        self.session.append(
                            {
                                "role": "user",
                                "content": (
                                    "[System note: Die Antwort darf noch nicht finalisiert werden. "
                                    "Es fehlt weiterhin vertraglich geforderte Evidenz. "
                                    "Nutze jetzt genau eines der aktuell exponierten Tools: "
                                    + ", ".join(turn_state.forced_next_tools[:4])
                                    + ". Wenn keines davon fachlich passt, erkläre danach explizit, "
                                    "dass die geforderte Evidenz mit dem aktuellen Tool-Bundle nicht erzeugbar ist.]"
                                ),
                            },
                            project=self.project,
                        )
                        forced_tool_retry_count += 1
                        step_i += 1
                        _emit_recovery(
                            "required_tool_retry",
                            lt("Ein erzwungener Evidenz-Toolschritt wurde ohne Tool-Call beendet; der Copilot bekommt genau einen weiteren Versuch.",
                               "A forced evidence tool step ended without a tool call. The Copilot gets exactly one more attempt."),
                        )
                        self.state = State.WAITING_LLM
                        continue
                    final_content = msg.get("content", "")
                    if ground_analysis:
                        if active_contract is not None:
                            pending_tools, missing_evidence = _pending_required_evidence_tools(active_contract)
                            if (
                                pending_tools
                                and step_i + 1 < max_steps
                                and not self._ra_tool_rounds_exhausted(
                                    turn_state
                                )
                            ):
                                if turn_state.forced_next_tools and forced_tool_retry_count >= 1:
                                    _record_tool_call_anomaly(
                                        "required_tool_refused_after_retry",
                                        finish_reason=finish_reason,
                                        candidate_calls=message_tool_calls,
                                        exposed_tools=current_exposed_tools,
                                        content_preview=cleaned_content or raw_content,
                                        note=(
                                            "Der Copilot hat auch nach einem expliziten Retry kein "
                                            "Tool für die verbliebene Vertragsevidenz aufgerufen; "
                                            "der Lauf wird konservativ mit Evidenzluecke finalisiert."
                                        ),
                                    )
                                    self._evidence_gaps = self._dedupe_ordered_strs(
                                        list(self._evidence_gaps)
                                        + [
                                            "Vertragsevidenz konnte nach einem erzwungenen Retry nicht "
                                            "eingesammelt werden: "
                                            + ", ".join(missing_evidence[:4])
                                        ]
                                    )[-6:]
                                    _emit_recovery(
                                        "required_tool_refused_after_retry",
                                        lt("Ein erzwungener Evidenz-Toolschritt wurde erneut ohne Tool-Call beendet; der Copilot finalisiert konservativ statt in weitere Tool-Retry-Schleifen zu gehen.",
                                           "A forced evidence tool step ended again without a tool call. The Copilot finishes conservatively instead of entering further tool retries."),
                                    )
                                    turn_state.forced_next_tools = None
                                    forced_tool_retry_count = 0
                                else:
                                    turn_state.forced_next_tools = list(pending_tools[:4])
                                    partial_content = cleaned_content or final_content
                                    if partial_content:
                                        self.session.append(
                                            {"role": "assistant", "content": partial_content},
                                            project=self.project)
                                    self.session.append(
                                        {
                                            "role": "user",
                                            "content": _evidence_note(
                                                missing_evidence,
                                            ),
                                        },
                                        project=self.project,
                                    )
                                    self._evidence_gaps = self._dedupe_ordered_strs(
                                        list(self._evidence_gaps)
                                        + [
                                            "Vorläufig fehlende Vertragsevidenz vor Finalisierung: "
                                            + ", ".join(missing_evidence[:4])
                                        ]
                                    )[-6:]
                                    step_i += 1
                                    _emit_recovery(
                                        "missing_required_evidence_retry",
                                        lt("Es fehlt noch Vertragsevidenz. Der Copilot sammelt vor der Finalisierung weitere passende Tool-Evidenz.",
                                           "Contract evidence is still missing. The Copilot collects more matching tool evidence before finishing."),
                                    )
                                    self.state = State.WAITING_LLM
                                    continue
                        # Fail-closed: when grounding is active, the raw model
                        # prose (``msg["content"]``) is never emitted as-is — it
                        # has not passed observed-facts/claim verification. Use the
                        # deterministic grounded answer; if that is empty, fall
                        # back to the conservative fail-closed grounding markdown,
                        # not the unverified model text.
                        grounded_content = await _finalize_grounded_answer(
                            initial_draft=cleaned_content or final_content,
                        )
                        final_content = grounded_content
                        msg["content"] = grounded_content
                    else:
                        # R2 Referenz-Antwortpfad (freier Modus): Referenzen
                        # deterministisch aufloesen, hard failures mit genau
                        # einem Repair-Call korrigieren, danach ehrliche
                        # Platzhalter. Der aufgeloeste Text ist die Antwort.
                        final_content = await self._ra_reference_answer(
                            turn_state,
                            copilot_event_bus,
                            cleaned_content,
                        )
                        msg["content"] = final_content
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        final_content,
                        stream_emit=stream and ground_analysis,
                    )

                # Low-autonomy plan gate (id 16): at autonomy 0/1 pause for an
                # explicit approval BEFORE the FIRST tool batch — even for
                # read-only tools — so the autonomy control is observable. We
                # pause WITHOUT appending the assistant tool_calls so the session
                # history stays valid (no dangling tool_calls); on resume the
                # loop re-enters with the gate satisfied and the tools execute.
                if msg.get("tool_calls") and self._plan_gate_active():
                    self._emit_plan_gate(copilot_event_bus, msg["tool_calls"])
                    self.session.summarise(
                        project=self.project,
                        runtime_state=self._build_runtime_state(normalized_question),
                    )
                    return politur_mit_zitatwache(  # Modelltext, bewacht.
                        cleaned_content or "", list(self._turn_evidence_items or ()),
                        frage=normalized_question)[0]

                self.state = State.EXECUTING_TOOL
                assistant_tool_message = {
                    "role": "assistant",
                    "tool_calls": msg["tool_calls"],
                }
                # Keep text accompanying tool calls in the history so a plan written
                # in message content remains available on the next round.
                text_neben_aufruf = str(cleaned_content or "").strip()
                if text_neben_aufruf:
                    assistant_tool_message["content"] = text_neben_aufruf
                response_id = str(result.get("id", "") or "").strip() if isinstance(result, dict) else ""
                if response_id:
                    assistant_tool_message["_cc_response_id"] = response_id
                self.session.append(assistant_tool_message, project=self.project)
                merke_abgabe_text(self, msg.get("tool_calls"), cleaned_content or msg.get("content"))

                if msg.get("tool_calls"):
                    self._ra_emit_status(copilot_event_bus, "Werkzeuge")
                    await self._ra_run_tool_batches(
                        turn_state,
                        copilot_event_bus,
                        msg["tool_calls"],
                        active_contract=active_contract,
                        dispatch=_dispatch,
                    )
                    # R2 Drift-Anker: ab der naechsten Runde traegt der
                    # Fortsetzungs-Guard das Ausgangsfrage-Echo.
                    turn_state.tool_rounds += 1
                    if self._ra_tool_rounds_exhausted(turn_state) \
                            and not turn_state.wrapup_emitted:
                        # WER das Ende erklaert, steht in der Meldung.
                        turn_state.wrapup_emitted = True
                        if getattr(self, "_ra_deutung_abgegeben", False):
                            _emit_recovery("deutung_abgegeben", lt(
                                "Das Modell hat die Abgabe selbst erklärt. Die Deutung "
                                "entsteht jetzt aus der vollen Evidenz.",
                                "The model declared its investigation finished. The "
                                "interpretation is now written from the full evidence."))
                        else:
                            _emit_recovery("tool_round_limit", lt(
                                "Die Runden-Leitplanke des Rezepts ist erreicht. Die "
                                "Antwort wird jetzt aus der vorhandenen Evidenz "
                                "synthetisiert, Ungeprüftes wird offen benannt.",
                                "The round limit of the recipe is reached. The answer "
                                "is now written from the available evidence, what was "
                                "not checked is named openly."))
                    gelandet = await _sofortlandung("werkzeugrunde")
                    if gelandet is not None:
                        return gelandet
                    # Keep the full contract tool set available after each tool step.
                    # Require missing evidence when the model tries to end the tool phase,
                    # so it can first refine subcorpora and correct its investigation plan.
                    turn_state.forced_next_tools = None
                    forced_tool_retry_count = 0

                step_i += 1
                if (
                    step_i >= max_steps
                    and ground_analysis
                    and not turn_state.schrittdecke_erreicht
                ):
                    # At the step limit, request the same draft as after deutung_abgeben.
                    # The tool-free call reads the full history and passes its draft to synthesis.
                    turn_state.schrittdecke_erreicht = True
                    _emit_recovery(
                        "max_steps_reached",
                        lt("Die maximale Werkzeugtiefe wurde erreicht. Das Modell "
                           "schreibt den Entwurf aus der gesammelten Evidenz, "
                           "danach wird synthetisiert und verifiziert.",
                           "The maximum tool depth was reached. The model writes "
                           "the draft from the collected evidence, then it is "
                           "synthesised and verified."),
                    )
                    self.state = State.WAITING_LLM
                    continue
                if step_i >= max_steps:
                    # Graceful finalize instead of raising HTTPException(409): a raise
                    # here propagates through the SSE stream, aborting it mid-flight
                    # and discarding all partial work. Mirror the timeout path —
                    # finalize the best partial answer and return it; the endpoint
                    # decides the HTTP status from a normal return value.
                    # ``max_steps`` bounds tool planning, not answer quality.
                    # Final synthesis and grounding verification are reserved
                    # protocol steps outside that tool-loop allowance.
                    if ground_analysis:
                        final_content = await _finalize_grounded_answer()
                    else:
                        final_content = free_mode_evidence_digest(self._recent_tool_results)
                    _emit_recovery(
                        "max_steps_reached",
                        lt("Die maximale Werkzeugtiefe wurde erreicht; die gesammelte "
                           "Evidenz wird jetzt synthetisiert und verifiziert.",
                           "The maximum tool depth was reached. The collected "
                           "evidence is now synthesised and verified."),
                    )
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        final_content,
                        stream_emit=stream,
                    )
                self.state = State.WAITING_LLM
                if (
                    max_time is not None
                    and time.perf_counter() - start_time > max_time
                ):
                    timeout = {"status": "error", "message": "timeout"}
                    self.session.append(
                        {
                            "role": "tool",
                            "tool_call_id": "timeout",
                            "content": json.dumps(timeout),
                        },
                        project=self.project,
                    )
                    if self.observability:
                        self.observability.record(
                            self.session.session_id,
                            "timeout",
                            status="error",
                        )
                    # Do NOT discard the evidence gathered so far: a timeout that
                    # appends an empty assistant message and returns "" hands the
                    # user a blank answer even though tool results are in hand.
                    # Mirror the max_steps exhaustion path and finalize the best
                    # grounded/partial answer from the collected evidence.
                    # K1: im Zeitlimit ausschliesslich deterministisch
                    # finalisieren, keine weiteren LLM-Calls. H6 (B1): die
                    # Landung probiert nach None zuerst den callfreien
                    # Salvage-Evidenzbericht, erst bei leerer Evidenz
                    # fail-closed (Kapitulation ist keine Antwort).
                    if ground_analysis:
                        final_content = await _finalize_grounded_answer(
                            deterministic_only=True
                        )
                    else:
                        final_content = free_mode_evidence_digest(self._recent_tool_results)
                    _emit_recovery(
                        "timeout",
                        lt("Das Zeitbudget wurde erreicht; die bisher gesammelte "
                           "Evidenz wird konservativ finalisiert.",
                           "The time budget was reached. The evidence collected so "
                           "far is finished conservatively."),
                    )
                    return self._ra_finish_turn(
                        copilot_event_bus,
                        normalized_question,
                        final_content,
                        stream_emit=stream,
                    )

            self.state = State.WAITING_LLM

            self.state = State.FINISHED
            self.session.summarise(
                project=self.project,
                runtime_state=self._build_runtime_state(normalized_question),
            )
            return ""

        if normalized_question and role == "user":
            self._ra_flush_research_updates(copilot_event_bus, normalized_question)

        try:
            result = await _run()
        except CopilotTurnCancelled:
            result = ""
        except LLMRequestError as exc:
            result = self._ra_lande_nach_modellstoerung(
                copilot_event_bus, normalized_question, turn_state, start_time,
                exc, stream=stream)
        finally:
            # Usage telemetry is observational and never stops analysis.
            self._last_turn_usage = turn_usage_snapshot(
                turn_state,
                start_time=start_time,
                recipe_id=turn_state.recipe_id or self._active_recipe_id,
                session=self.session,
            )
            self._harvest_research_tasks()
            self._ra_flush_research_updates(copilot_event_bus, normalized_question)
            if self.observability:
                self.observability.end_session(self.session.session_id)
        return result
