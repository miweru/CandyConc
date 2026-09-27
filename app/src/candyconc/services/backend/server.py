import asyncio
import contextlib
import contextvars
from datetime import date as calendar_date, timedelta
import hashlib
import json
import struct
import os
import uuid
import logging
import time
import re
import math
import sys
import threading
from pathlib import Path
import tempfile
import heapq
from collections import Counter, OrderedDict

if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from typing import Any, Dict, List, Set, Callable, Annotated, Mapping, Optional, Sequence
from functools import lru_cache


from fastapi import (
    FastAPI,
    WebSocket,
    HTTPException,
    Request,
    Depends,
    Body,
)
from candyconc.entrypoints.errors import (
    ApiError,
    problem,
    register_exception_handlers,
    CandyAPIRouter,
)
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
)
from .routes import (
    auth as auth_routes,
    capabilities as capabilities_routes,
    system as system_routes,
    exports as exports_routes,
    corpora as corpora_routes,
    projects as projects_routes,
    subcorpora as subcorpora_routes,
    operation_runs as operation_runs_routes,
    semantic as semantic_routes,
    analysis as analysis_routes,
    annotations as annotations_routes,
    documents as documents_routes,
    query as query_routes,
    copilot as copilot_routes,
    copilot_ws as copilot_ws_routes,
)


from .routes.query import (  # noqa: F401 - compatibility export for srv.query_endpoint callers
    _resolve_case_insensitive,  # Depends-Target der bleibenden /query/count-Signatur
    query_analyse_post,
    query_endpoint,
    query_stream_endpoint,
)
from .lru_maps import close_quietly, mark_lru_used, trim_lru_cache
from .routes.copilot import (  # noqa: F401 - compatibility export preserving handler names
    answer_clarification,
    approve_action,
    cancel_copilot_turn,
    chat_endpoint,
    chat_stream_endpoint,
    continue_copilot_execution,
    reject_action,
    update_copilot_context,
)
from .routes.copilot_ws import (  # noqa: F401 - compatibility export
    ws_analysis,
    ws_faiss,
)

try:
    import orjson as _orjson
except Exception:  # pragma: no cover - optional acceleration
    _orjson = None
from .startup import StartupManager, start_without_corpus, stop_without_corpus

if __package__:
    from . import metrics as metrics
    from . import trace as trace
    from . import rate_limit as rate_limit
    from . import jobs, copilot_event_bus, analysis_jobs
else:  # pragma: no cover - direct module execution
    from importlib import import_module
    metrics = import_module("candyconc.services.backend.metrics")
    trace = import_module("candyconc.services.backend.trace")
    rate_limit = import_module("candyconc.services.backend.rate_limit")
    jobs = import_module("candyconc.services.backend.jobs")
    copilot_event_bus = import_module("candyconc.services.backend.copilot_event_bus")
    analysis_jobs = import_module("candyconc.services.backend.analysis_jobs")
from candyconc import paths as _user_paths
from candyconc.i18n import LocalizedText, exception_text, lt
from candyconc.version import package_version
from .request_language import LanguageMiddleware
from candyconc.config import APP_CONFIG, load_settings
from candyconc.config import get as get_config
from candyconc.services.semantic import index_utils
from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.counting_kernels import (
    filter_positions_and_values_by_docset_fast,
    filter_positions_by_docset_fast,
    keyness_scores_fast,
    position_to_doc_id_fast,
    unique_doc_ids_from_positions_fast,
)
from candyconc.core.fast_index_native import docset_mask_from_ids, strings_for_ids
from candyconc.core.query_runtime import set_corpus
from cqlhpc.errors import EmptyMatchError, UnresolvableConditionError
from . import kwic as kwic_adapter

from . import auth, prefs
from .route_matrix import (
    policy_for_path,
    required_role_for_access,
    requires_policy_for_path,
)
from candyconc.tooling import get_tool_runtime_info as _get_tool_runtime_info
from candyconc.tooling import get_tools as _get_tools
from candyconc.tooling import (
    filter_dispatchable_tools_for_principal,
    product_tool_bindings_by_name as _product_tool_bindings_by_name,
    response_contract_for_prompt,  # noqa: F401 - compatibility facade for routes/copilot.py
    select_tools_for_prompt,
)
from candyconc.services.moderation import moderate  # noqa: F401 - compatibility facade for routes/copilot.py
try:  # optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover - faiss missing
    faiss = None  # type: ignore
import numpy as np
from candyconc.analysis_defaults import (
    CASE_POLICY_GEFALTET,
    LABEL_POLICY_GEFALTET,
    adaptive_collocate_min_freq,
    collocate_floor_mode,
    build_method_block,
    collocation_frame_provenance,
    collocation_method_extra,
    filter_collocate_frame_by_min_freq,
    is_analyst_token,
    # Der Indexstand verlaesst den Prozess GEHASHT, an jeder Naht. Die
    # sechs Job-Runner unter dieser Datei setzten ihn roh, waehrend jede
    # synchrone Schwesterroute (routes/analysis._index_fingerprint) bereits
    # hashte: derselbe Index, zwei Werte, und im Job-Weg stand das
    # Heimatverzeichnis des Betreibers. Der Job-Weg ist genau der, den die
    # Oberflaeche fuer NgramsTab, KeynessTab, CollocationsTab und
    # WordSketchTab nimmt, und deren Export schreibt "# indexFingerprint:"
    # in die Datei.
    kurzer_indexstand,
    normalize_default_collocate_frame,
    normalize_word_sketch_tables,
)
from candyconc.candyconc_copilot.prompt_cleaner import clean_prompt  # noqa: F401 - compatibility facade for routes/copilot.py
from candyconc.candyconc_copilot.orchestrator import ReActOrchestrator
from candyconc.candyconc_copilot.dispatcher import dispatch as _dispatch
from candyconc.candyconc_copilot.session_manager import SessionManager  # noqa: F401 - compatibility facade for routes/copilot.py
from candyconc.candyconc_copilot.observability import Observability
from candyconc.candyconc_copilot.policy_engine import PolicyEngine
from candyconc.candyconc_copilot.word_denominator import nenner as _word_denominator
from candyconc.candyconc_copilot.analysis import (
    frequency_list as _frequency_list,  # noqa: F401 - routes/analysis.py and tests
    # Plain-text dispersion uses _positions_from_query, matching the count
    # path. Keep this re-export for tests and external callers.
    dispersion_offsets as _dispersion_offsets,  # noqa: F401
)
from candyconc.tools.collocate_stats import collocate_stats as _collocate_stats
from candyconc.services.tools.keyness import (
    RELIABILITY_EXPECTED_MIN,
    schreibungen_anhaengen,
    chi2_2x2_pooled,
    compute_keyness as _compute_keyness,  # noqa: F401 — kept: routes/analysis.py uses server._compute_keyness
    compute_keyness_counts as _compute_keyness_counts,  # noqa: F401 — kept: routes/analysis.py uses server._compute_keyness_counts
    expected_min_cell,
    keyness_full_stats,
    normalize_disjoint_docsets,
)
from candyconc.services.backend.policy_state import (
    POLICY_ACLS,
    POLICY_BUDGETS,
    PROJECT_QUOTAS,
)
from candyconc.services.llm_client import (
    LLMErrorKind,
    LLMRequestError,
    call_llm_async,  # noqa: F401 — kept: routes/semantic.py + tests use server.call_llm_async
    call_llm,  # noqa: F401 - compatibility facade for routes/copilot.py
    ensure_copilot_runtime_available,  # noqa: F401 - compatibility facade for routes/copilot.py
    token_len as llm_token_len,
)
from candyconc.domain.query_parser import parse_query
from candyconc.domain.query_eval import _eval as _eval_query

from candyconc.services.mcp_server import router as mcp_router

# Transitional compatibility facade for remaining route and test seams.
# Remove a name only with every one of its consumers.
from .limits import (  # noqa: F401
    _query_hard_limit,
    _reject_non_positive_limit,
)
from .http_sse import (  # noqa: F401, E402
    _copilot_sse_frame,
    _json_dumps_fast_bytes,
    _sse_event_bytes,
)
from .textnorm import (  # noqa: F401, E402
    _canonicalize_term,
    _is_simple_single_token,
    _normalize_meta_value,
    _normalize_query_key,
)
from .executors import (  # noqa: F401, E402
    _HEAVY_SCAN_EXECUTOR,
    _HEAVY_SCAN_WORKERS,
    _heavy_scan_worker_count,
    _run_heavy_scan,
    _run_heavy_scan_sync,
)
from .docsets import (  # noqa: F401, E402
    _DOCSET_CACHE,
    _DOCSET_CACHE_LIMIT,
    _build_meta_expr,
    _combine_docset_masks,
    _get_docset,
    _store_docset,
    drop_docsets_for_corpora,
)
from candyconc.core.meta_filters import clear_document_fields_cache  # noqa: E402
from candyconc.core.pairing import is_anchor, is_version  # noqa: E402
from .kwic_render import (  # noqa: F401
    _apply_cql_two_token_pivot_one_rows,
    _doc_bounds_for_index,
    _prepare_cql_rows_fast,
)
from .doc_meta import (  # noqa: F401, E402
    _DOC_META_SHARED_CACHE_ATTR,
    _DOC_META_SHARED_CACHE_LIMIT,
    _build_doc_meta_entry,
    _doc_count_for_index,
    _doc_meta_for_doc_id,
    _enrich_rows_with_doc_meta,
    _metadata_filter_mask_cache_clear,
    _metadata_filter_mask_cache_get,
    _metadata_filter_mask_cache_set,
    _parse_file_label,
    _resolve_query_meta_lookup,
    _shared_doc_meta_cache,
    _shared_doc_meta_for_doc_id,
    _stringify_meta,
)
from .alignment import (  # noqa: F401, E402
    _ALIGNMENT_METHODS,
    _ALIGNMENT_MIN_CONFIDENT_SIMILARITY,
    _REFDOC_INDEX_CACHE,
    _REFDOC_INDEX_DOC_COUNT,
    SentenceData,
    _align_sentence_lists,
    _alignment_budget_not_applicable,
    _alignment_edit_cell_count,
    _alignment_edit_cell_limit,
    _alignment_not_applicable,
    _alignment_summary_from_pairs,
    _conservative_alignment_pairs,
    _edit_similarity_with_overlap,
    _embed_pair_cost,
    _levenshtein_tokens_norm,
    _load_sentence_vectors,
    _normalize_tokens,
    _normalized_med,
    _normalized_med_norm,
    _refdoc_index_for_corpus,
    _sentence_embeddings_available,
    resolve_pair_groups,
)
from .analysis_runners import (  # noqa: F401, E402
    _CollocateSegments,
    _analysetoken_pruefer,
    _collocate_segments_for_anchors,
    _collocate_stats_from_positions,
    _extract_simple_cql_token,
    _g2_2x2,
    _gries_dp,
    _gries_dp_documents,
    _keyness_signed_direction,
    _ngram_counts,
    _ngram_populations,
    _ngram_vereinigung,
    _normalize_collocate_frame,
    _per_million,
)
from .copilot_sessions import (  # noqa: F401, E402
    _ACTIVE_ORCH_LOCK,
    _COPILOT_SESSION_TTL_SEC,
    _ActiveOrchestratorSession,
    _active_orchestrators,
    _cancel_active_session,
    _cancel_running_turns_for_owner,
    _get_active_session,
    _prune_active_orchestrators,
    _register_active_orchestrator,
)
from .copilot_helpers import (  # noqa: F401, E402
    _COPILOT_BACKSTOP_GRACE_SEC_DEFAULT,
    _COPILOT_MAX_HISTORY_CHARS_DEFAULT,
    _COPILOT_MAX_MESSAGES_DEFAULT,
    _COPILOT_MAX_QUESTION_CHARS_DEFAULT,
    _COPILOT_MAX_STEPS_HARD_DEFAULT,
    _COPILOT_MAX_TIME_SEC_DEFAULT,
    _clamp_copilot_max_steps,
    _copilot_backstop_grace_sec,
    _copilot_max_steps_ceiling,
    _copilot_max_time_sec,
    _copilot_payload_ceiling,
    _enforce_copilot_payload_caps,
)
from .query_count import (  # noqa: F401, E402
    _CQL_COUNT_PROBE_HARD_MAX,
    _QUERY_COUNT_CACHE,
    _QUERY_COUNT_CANCEL_GRACE_SEC,
    _QUERY_COUNT_LOCK,
    _QUERY_COUNT_MAX,
    _QUERY_COUNT_THREAD_LOCK,
    _QUERY_COUNT_TTL_SEC,
    _SERVER_STATE_ERROR_MARKERS,
    _QueryCountKey,
    _QueryCountState,
    _cancel_query_count_after_grace,
    _classify_query_runtime_error,
    _cleanup_query_count_cache,
    _complete_query_count,
    _cql_count_probe_limit,
    _get_or_create_query_count,
    _is_query_user_error,
    _is_server_state_error,
    _query_count_error_envelope,
    _query_count_error_response,
    _query_count_key,
    _release_query_count,
    _resolve_query_count_result,
    _trim_query_count_cache,
)

token_len = llm_token_len

logger = logging.getLogger(__name__)
_START_TIME = time.time()

_ANCHOR_POS_CACHE: "OrderedDict[tuple[str, str, bool], tuple[np.ndarray, np.ndarray, int]]" = OrderedDict()
_ANCHOR_POS_CACHE_LIMIT = 48
_ANCHOR_POS_CACHE_MAX_BYTES = 256 * 1024 * 1024
_ANCHOR_POS_CACHE_BYTES = 0
_ANCHOR_POS_CACHE_LOCK = threading.RLock()
_QUERY_ROWS_RESPONSE_CACHE: "OrderedDict[tuple[str, str, int, str, str, int], tuple[bytes, int, dict[str, str]]]" = OrderedDict()
_QUERY_ROWS_RESPONSE_CACHE_LOCK = threading.RLock()
_QUERY_ROWS_RESPONSE_CACHE_MAX_BYTES = int(
    get_config("CANDYCONC_QUERY_ROWS_RESPONSE_CACHE_MAX_BYTES", str(64 * 1024 * 1024))
)
_QUERY_ROWS_RESPONSE_CACHE_MAX_ENTRY_BYTES = int(
    get_config("CANDYCONC_QUERY_ROWS_RESPONSE_CACHE_MAX_ENTRY_BYTES", str(16 * 1024 * 1024))
)
_QUERY_ROWS_RESPONSE_CACHE_BYTES = 0
_QUERY_STREAM_BATCH_CACHE: "OrderedDict[tuple[str, str, int, str, str, str, int, int, int], tuple[list[tuple[bytes, int]], int, bool, int | None, bool, int]]" = OrderedDict()
_QUERY_STREAM_BATCH_CACHE_LOCK = threading.RLock()
_QUERY_STREAM_BATCH_CACHE_MAX_BYTES = int(
    get_config("CANDYCONC_QUERY_STREAM_BATCH_CACHE_MAX_BYTES", str(64 * 1024 * 1024))
)
_QUERY_STREAM_BATCH_CACHE_MAX_ENTRY_BYTES = int(
    get_config("CANDYCONC_QUERY_STREAM_BATCH_CACHE_MAX_ENTRY_BYTES", str(16 * 1024 * 1024))
)
_QUERY_STREAM_BATCH_CACHE_BYTES = 0
def _anchor_positions_cache_get(key: tuple[str, str, bool]) -> tuple[np.ndarray, np.ndarray] | None:
    with _ANCHOR_POS_CACHE_LOCK:
        cached = _ANCHOR_POS_CACHE.get(key)
        if cached is None:
            return None
        _ANCHOR_POS_CACHE.move_to_end(key)
        positions, spans, _entry_bytes = cached
        return positions, spans


def _anchor_positions_cache_set(
    key: tuple[str, str, bool],
    positions: np.ndarray,
    spans: np.ndarray,
) -> None:
    global _ANCHOR_POS_CACHE_BYTES
    entry_bytes = int(getattr(positions, "nbytes", 0)) + int(getattr(spans, "nbytes", 0))
    with _ANCHOR_POS_CACHE_LOCK:
        old = _ANCHOR_POS_CACHE.pop(key, None)
        if old is not None:
            _ANCHOR_POS_CACHE_BYTES -= int(old[2])
        _ANCHOR_POS_CACHE[key] = (positions, spans, entry_bytes)
        _ANCHOR_POS_CACHE.move_to_end(key)
        _ANCHOR_POS_CACHE_BYTES += entry_bytes
        while len(_ANCHOR_POS_CACHE) > _ANCHOR_POS_CACHE_LIMIT:
            _old_key, _old_val = _ANCHOR_POS_CACHE.popitem(last=False)
            _ANCHOR_POS_CACHE_BYTES -= int(_old_val[2])
        while _ANCHOR_POS_CACHE and _ANCHOR_POS_CACHE_BYTES > _ANCHOR_POS_CACHE_MAX_BYTES:
            _old_key, _old_val = _ANCHOR_POS_CACHE.popitem(last=False)
            _ANCHOR_POS_CACHE_BYTES -= int(_old_val[2])


def _query_rows_response_cache_get(
    key: tuple[Any, ...],
) -> tuple[bytes, dict[str, str]] | None:
    with _QUERY_ROWS_RESPONSE_CACHE_LOCK:
        cached = _QUERY_ROWS_RESPONSE_CACHE.get(key)
        if cached is None:
            return None
        _QUERY_ROWS_RESPONSE_CACHE.move_to_end(key)
        return cached[0], dict(cached[2])


def _query_rows_response_cache_set(
    key: tuple[Any, ...],
    payload: bytes,
    headers: dict[str, str] | None = None,
) -> None:
    global _QUERY_ROWS_RESPONSE_CACHE_BYTES
    entry_bytes = int(len(payload))
    if entry_bytes <= 0 or entry_bytes > _QUERY_ROWS_RESPONSE_CACHE_MAX_ENTRY_BYTES:
        return
    with _QUERY_ROWS_RESPONSE_CACHE_LOCK:
        old = _QUERY_ROWS_RESPONSE_CACHE.pop(key, None)
        if old is not None:
            _QUERY_ROWS_RESPONSE_CACHE_BYTES -= int(old[1])
        _QUERY_ROWS_RESPONSE_CACHE[key] = (payload, entry_bytes, dict(headers or {}))
        _QUERY_ROWS_RESPONSE_CACHE.move_to_end(key)
        _QUERY_ROWS_RESPONSE_CACHE_BYTES += entry_bytes
        while _QUERY_ROWS_RESPONSE_CACHE and _QUERY_ROWS_RESPONSE_CACHE_BYTES > _QUERY_ROWS_RESPONSE_CACHE_MAX_BYTES:
            _old_key, _old_val = _QUERY_ROWS_RESPONSE_CACHE.popitem(last=False)
            _QUERY_ROWS_RESPONSE_CACHE_BYTES -= int(_old_val[1])


def _query_config_int(name: str, default: int) -> int:
    try:
        return int(get_config(name, str(default)) or default)
    except (TypeError, ValueError):
        return int(default)


def _query_default_limit() -> int:
    hard_max = _query_hard_limit()
    return max(1, min(_query_config_int("CANDYCONC_QUERY_DEFAULT_LIMIT", 1000), hard_max))


def _kwic_sort_scan_cap() -> int:
    """How many positional hits to scan before sorting a KWIC query.

    Sorting only the first page would yield A-Z of the first ``limit`` *positional*
    hits, not of all matches (a silently-wrong result). For a sorted query we scan
    up to this cap, sort, then truncate; if the match set exceeds the cap the
    response carries ``X-CandyConc-Sort-Approximate: true`` so the client knows the
    ordering is over a bounded prefix rather than the whole result set.
    """
    return max(_query_hard_limit(), _query_config_int("CANDYCONC_KWIC_SORT_SCAN_CAP", 5000))


def _query_stream_hard_limit() -> int:
    return 50000


def _query_context_max() -> int:
    # The interface exposes a 600-token context window. Keep the backend's
    # effective context aligned with that visible contract.
    return max(0, _query_config_int("CANDYCONC_QUERY_MAX_CONTEXT", 600))


def _bounded_query_context(ctx: int) -> int:
    max_ctx = _query_context_max()
    return max(0, min(int(ctx), max_ctx))


def _reject_negative_offset(value: int) -> None:
    """Raise HTTP 422 for an explicitly-supplied negative ``offset``."""
    if value < 0:
        raise ApiError(
            422,
            "request.offset_negative",
            lt(
                "offset muss >= 0 sein (erhalten: {value})",
                "offset must be >= 0 (received: {value})",
            ),
            value=value,
        )


def _bounded_query_limit(
    limit: int | None, *, hard_max: int, strict: bool = False
) -> tuple[int, bool, bool]:
    """Return ``(effective_limit, defaulted, clamped)``.

    ``strict`` (user-facing routes) rejects a non-positive explicit limit with
    HTTP 422 instead of coercing it to the default. ``clamped`` reports that an
    oversized request was capped to ``hard_max`` so the route can echo a flag /
    header and the user knows the result is bounded (finding 34).
    """
    defaulted = limit is None
    if defaulted:
        raw_limit = _query_default_limit()
    else:
        raw_limit = int(limit)
        if strict:
            _reject_non_positive_limit(raw_limit)
    effective = max(1, min(raw_limit, int(hard_max)))
    clamped = (not defaulted) and raw_limit > int(hard_max)
    return effective, defaulted, clamped


def _query_limit_cache_marker(effective_limit: int, defaulted: bool) -> int:
    if defaulted:
        return -(int(effective_limit) + 1)
    return int(effective_limit)


def _query_bound_headers(
    *,
    effective_limit: int,
    limit_defaulted: bool,
    effective_ctx: int,
    truncated: bool,
    next_offset: int | None = None,
) -> dict[str, str]:
    headers = {
        "X-CandyConc-Limit": str(int(effective_limit)),
        "X-CandyConc-Limit-Defaulted": "true" if limit_defaulted else "false",
        "X-CandyConc-Context": str(int(effective_ctx)),
        "X-CandyConc-Max-Context": str(_query_context_max()),
        "X-CandyConc-Truncated": "true" if truncated else "false",
    }
    if next_offset is not None:
        headers["X-CandyConc-Next-Offset"] = str(int(next_offset))
    return headers


def _new_query_trace_id() -> str:
    return f"qtr_{uuid.uuid4().hex}"


def _query_stream_batch_cache_get(
    key: tuple[str, str, int, str, str, str, int, int, int],
) -> tuple[list[tuple[bytes, int]], int, bool, int | None, bool] | None:
    with _QUERY_STREAM_BATCH_CACHE_LOCK:
        cached = _QUERY_STREAM_BATCH_CACHE.get(key)
        if cached is None:
            return None
        _QUERY_STREAM_BATCH_CACHE.move_to_end(key)
        return cached[0], cached[1], cached[2], cached[3], cached[4]


def _query_stream_batch_cache_set(
    key: tuple[str, str, int, str, str, str, int, int, int],
    batches: list[tuple[bytes, int]],
    *,
    total: int,
    partial: bool,
    next_offset: int | None,
    truncated: bool,
) -> None:
    global _QUERY_STREAM_BATCH_CACHE_BYTES
    entry_bytes = sum(len(payload) for payload, _row_count in batches)
    if entry_bytes <= 0 or entry_bytes > _QUERY_STREAM_BATCH_CACHE_MAX_ENTRY_BYTES:
        return
    with _QUERY_STREAM_BATCH_CACHE_LOCK:
        old = _QUERY_STREAM_BATCH_CACHE.pop(key, None)
        if old is not None:
            _QUERY_STREAM_BATCH_CACHE_BYTES -= int(old[5])
        _QUERY_STREAM_BATCH_CACHE[key] = (
            batches,
            int(total),
            bool(partial),
            next_offset,
            bool(truncated),
            int(entry_bytes),
        )
        _QUERY_STREAM_BATCH_CACHE.move_to_end(key)
        _QUERY_STREAM_BATCH_CACHE_BYTES += int(entry_bytes)
        while _QUERY_STREAM_BATCH_CACHE and _QUERY_STREAM_BATCH_CACHE_BYTES > _QUERY_STREAM_BATCH_CACHE_MAX_BYTES:
            _old_key, _old_val = _QUERY_STREAM_BATCH_CACHE.popitem(last=False)
            _QUERY_STREAM_BATCH_CACHE_BYTES -= int(_old_val[5])


API_DESCRIPTION = """
CandyConc server API for corpus queries, analyses and export.

Basics
- All endpoints live under `/api/v1/...`.
- Errors are returned as problem JSON: `status`, `title`, `detail`, `instance`.
  Errors with a stable message code also carry `code` and `params`.
- `detail` is written in the language of the request (`Accept-Language`,
  German or English). German is the default.
- Queries in the query language use the prefix `cql:`, for example `cql:[lemma="gehen"]`.
- Document sets (`docset_id`) are resolved document lists that further analyses can be restricted to.

Authentication and tokens
- If authentication is active, send `Authorization: Bearer <token>`.
- Tokens in the query string or request body are only accepted in the explicit `local_dev_unsafe` mode.

Response formats
- Analysis endpoints usually return `rows` or structured JSON objects.
- Streaming responses are sent as server-sent events.
"""

API_TAGS = [
    {"name": "Auth", "description": "Login, users and permissions."},
    {"name": "Jobs", "description": "Job status and background tasks."},
    {"name": "System", "description": "Health, metrics, runtime data and system information."},
    {"name": "Documents", "description": "Document search and document excerpts."},
    {"name": "Query", "description": "KWIC and query analysis."},
    {"name": "Analysis", "description": "Frequencies, n-grams, keyness, collocations, dispersion."},
    {"name": "Search", "description": "Advanced search and ranking."},
    {"name": "Semantic", "description": "Semantic search and clustering."},
    {"name": "Embeddings", "description": "Embedding packages and index management."},
    {"name": "Corpora", "description": "Corpus results and outputs."},
    {"name": "Export", "description": "Export to PDF and DOCX, and downloads."},
    {"name": "Projects", "description": "Project management and cluster persistence."},
    {"name": "Chat", "description": "Copilot chat endpoints."},
    {"name": "Admin", "description": "Administration and configuration."},
    {"name": "Tasks", "description": "Background tasks and pipeline."},
]

# NaN/Inf-safe default response class (finding D, items g+h).
#
# Default FastAPI JSONResponse emits literal ``NaN``/``Infinity`` — valid for
# Python's json but INVALID JSON that breaks strict clients. We want valid JSON
# everywhere. orjson is the right serializer (fast, numpy-native, RFC-strict) but
# orjson RAISES on non-finite floats, so flipping the global default naively would
# turn any not-yet-sanitized route into a 500. To get "always valid JSON, never
# 500" without editing routes we don't own, ``_SafeJSONResponse`` recursively
# replaces non-finite floats with null at render time, then serializes via orjson
# when available (else the stdlib encoder with allow_nan disabled). This is the
# defensive serializer the DT-SERVER brief calls for; declaring orjson as a hard
# dependency is the B-buildpkg track's pyproject change.
def _strip_non_finite(value: Any) -> Any:
    # Convert numpy scalars/arrays to native Python BEFORE the plain-``float``
    # branch. ``np.float64`` IS a subclass of ``float`` (and ``np.bool_`` of
    # ``int``-like), so the bare ``isinstance(value, float)`` check below would
    # return the numpy scalar *unchanged* — and orjson then 500s on a *finite*
    # numpy scalar because it cannot serialize ``numpy.float64``/``numpy.int64``.
    # Running the numpy branch first guarantees both finite and non-finite numpy
    # values leave here as native ``float``/``int``/``list`` (C-server-degrade-2).
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_strip_non_finite(v) for v in value.tolist()]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, LocalizedText):
        # Bilingual server text: resolved to the interface language of the
        # request being rendered (candyconc.i18n).
        return value.resolve()
    if isinstance(value, dict):
        return {k: _strip_non_finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strip_non_finite(v) for v in value]
    return value


class _SafeJSONResponse(JSONResponse):
    """JSONResponse that never emits NaN/Inf, resolves bilingual texts to the
    request language and prefers orjson when available."""

    def render(self, content: Any) -> bytes:
        safe = _strip_non_finite(content)
        if _orjson is not None:
            # OPT_SERIALIZE_NUMPY is a belt-and-suspenders backstop: ``safe`` is
            # already native after ``_strip_non_finite``, but any numpy value that
            # slipped through (e.g. nested in a custom container) is serialized
            # natively instead of raising a TypeError -> 500.
            return _orjson.dumps(
                safe,
                option=_orjson.OPT_NON_STR_KEYS | _orjson.OPT_SERIALIZE_NUMPY,
            )
        return json.dumps(
            safe,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")


app = FastAPI(
    title="CandyConc Backend API",
    description=API_DESCRIPTION.strip(),
    version=package_version(),
    openapi_tags=API_TAGS,
    default_response_class=_SafeJSONResponse,
)
# Seam E: register the HTTPException / validation / generic-Exception handlers
# via the single entry point so unhandled errors become RFC 7807 problem+json
# (500) instead of leaking a text/plain stack trace. The generic catch-all is
# registered last (most general); Starlette still dispatches the specific
# HTTPException / RequestValidationError handlers first.
register_exception_handlers(app)
api_router = CandyAPIRouter()

api_router.include_router(auth_routes.router)
api_router.include_router(capabilities_routes.router)
api_router.include_router(system_routes.router)
api_router.include_router(exports_routes.router)
api_router.include_router(corpora_routes.router)
api_router.include_router(projects_routes.router)
api_router.include_router(subcorpora_routes.router)
api_router.include_router(operation_runs_routes.router)
api_router.include_router(semantic_routes.router)
api_router.include_router(analysis_routes.router)
api_router.include_router(annotations_routes.router)
api_router.include_router(documents_routes.router)

# /analysis route handlers live in routes/analysis.py (route-extraction slice 4).
# Re-exported here because existing tests resolve them as server.<handler>
# attributes; the handlers late-import this module for shared state
# (analysis_jobs, _run_* job runners, docset store, limits), which stays here.
analysis_meta_schema = analysis_routes.analysis_meta_schema
analysis_meta_values = analysis_routes.analysis_meta_values
analysis_meta_counts = analysis_routes.analysis_meta_counts
analysis_frequency_list_job = analysis_routes.analysis_frequency_list_job
analysis_frequency_diff_job = analysis_routes.analysis_frequency_diff_job
analysis_job_status = analysis_routes.analysis_job_status
analysis_job_cancel = analysis_routes.analysis_job_cancel
analysis_job_rows = analysis_routes.analysis_job_rows
analysis_frequency_list = analysis_routes.analysis_frequency_list
analysis_docset_from_meta = analysis_routes.analysis_docset_from_meta
analysis_docset_intersection = analysis_routes.analysis_docset_intersection
analysis_parallel_groups = analysis_routes.analysis_parallel_groups
analysis_alignment_ref_doc = analysis_routes.analysis_alignment_ref_doc
analysis_docset_from_search = analysis_routes.analysis_docset_from_search
analysis_ngrams = analysis_routes.analysis_ngrams
analysis_ngrams_job = analysis_routes.analysis_ngrams_job
analysis_ngrams_diff_job = analysis_routes.analysis_ngrams_diff_job
embedding_search_endpoint = analysis_routes.embedding_search_endpoint
analysis_collocates = analysis_routes.analysis_collocates
analysis_collocates_kwic = analysis_routes.analysis_collocates_kwic
analysis_kwic_parallel = analysis_routes.analysis_kwic_parallel
analysis_collocates_job = analysis_routes.analysis_collocates_job
analysis_collocates_diff_job = analysis_routes.analysis_collocates_diff_job
analysis_contrast = analysis_routes.analysis_contrast
analysis_dispersion_offsets = analysis_routes.analysis_dispersion_offsets
analysis_dispersion = analysis_routes.analysis_dispersion
analysis_keyness_job = analysis_routes.analysis_keyness_job
analysis_keyness = analysis_routes.analysis_keyness
word_sketch_endpoint = analysis_routes.word_sketch_endpoint
# R7 feature additions (collocation-network slice, lexical diversity, full export).
analysis_collocation_network_get = analysis_routes.analysis_collocation_network_get
analysis_lexical_diversity = analysis_routes.analysis_lexical_diversity
export_concordance_post = analysis_routes.export_concordance_post
export_evidence_package_post = analysis_routes.export_evidence_package_post


@app.get("/api", include_in_schema=False)
async def _api_redirect_root() -> RedirectResponse:
    """Redirect unversioned API root to the latest version."""
    return RedirectResponse("/api/v1", status_code=308)

_TRUSTED_HOSTS_DEFAULT = "localhost,127.0.0.1,::1,testserver"


def _trusted_hosts() -> set[str]:
    """Host-header allowlist for release mode (DNS-rebinding guard).

    Configurable via the ``CANDYCONC_TRUSTED_HOSTS`` environment variable
    (comma-separated; ``*`` disables the check explicitly). The default covers
    loopback deployments plus Starlette's TestClient host. ``get_config`` is
    consulted as a fallback for a future AppConfig field of the same name.
    """
    raw = os.environ.get("CANDYCONC_TRUSTED_HOSTS") or get_config(
        "CANDYCONC_TRUSTED_HOSTS", _TRUSTED_HOSTS_DEFAULT
    )
    return {h.strip().lower() for h in str(raw).split(",") if h.strip()}


def _host_is_trusted(host_header: str) -> bool:
    """Check a raw ``Host`` header (optionally with port) against the allowlist."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        # Bracketed IPv6 literal, e.g. "[::1]:8765"
        host = host.partition("]")[0].lstrip("[")
    elif host.count(":") == 1:
        # "name:port" — bare IPv6 (multiple colons) is left untouched
        host = host.rsplit(":", 1)[0]
    allowed = _trusted_hosts()
    return "*" in allowed or host in allowed


def _docs_paths() -> set[str]:
    """Interactive API doc paths that must not be public in release mode.

    Derived from the live app config so the gate follows any constructor
    changes; gating happens in middleware (not via ``docs_url=None``) so the
    OpenAPI schema/shape stays identical between dev and release builds.
    """
    return {
        path
        for path in (
            app.docs_url,
            app.redoc_url,
            app.openapi_url,
            app.swagger_ui_oauth2_redirect_url,
        )
        if path
    }


# Maximum request body size (bytes) accepted before the route runs. Without a
# cap, a client can post an arbitrarily large JSON body and force the server to
# buffer/parse it (memory + CPU amplification) — DoS finding (B). 8 MiB is well
# above any legitimate query/chat/annotation payload (chat history is separately
# capped below) yet small enough to bound a single request. Override via
# CANDYCONC_MAX_REQUEST_BYTES (0 disables the guard).
_MAX_REQUEST_BYTES_DEFAULT = 8 * 1024 * 1024


def _max_request_bytes() -> int:
    raw = os.environ.get("CANDYCONC_MAX_REQUEST_BYTES") or get_config(
        "CANDYCONC_MAX_REQUEST_BYTES", str(_MAX_REQUEST_BYTES_DEFAULT)
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return _MAX_REQUEST_BYTES_DEFAULT
    return max(0, value)


def _content_length_exceeds_limit(request: Request) -> int | None:
    """Return the declared Content-Length when it exceeds the body-size cap.

    Returns ``None`` when within the limit, the guard is disabled, or the header
    is absent/unparseable (a missing/lying header is handled by the per-route
    payload caps; this is the cheap early reject for honestly-declared giants).
    """
    limit = _max_request_bytes()
    if limit <= 0:
        return None
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        declared = int(raw)
    except (TypeError, ValueError):
        return None
    return declared if declared > limit else None


# Content-Types accepted as JSON request bodies. ``application/json`` plus the
# RFC-6839 ``+json`` structured-suffix family (e.g. application/merge-patch+json)
# and an optional charset/boundary parameter (handled by splitting on ``;``).
_JSON_BODY_MEDIA_TYPES = frozenset({"application/json"})


def _is_json_media_type(content_type: str) -> bool:
    base = content_type.split(";", 1)[0].strip().lower()
    if not base:
        return False
    return base in _JSON_BODY_MEDIA_TYPES or base.endswith("+json")


async def _reject_non_json_body(request: Request):
    """Reject a body-bearing request whose Content-Type is set but not JSON.

    Returns a 415 ``problem`` response when the request is a POST/PUT/PATCH that
    carries a non-empty body AND declares a Content-Type that is present but not
    an accepted JSON media type. Returns ``None`` (let it through) when the
    method is bodyless, the Content-Type header is absent, the Content-Type is
    JSON, or the body is empty. Reading ``request.body()`` here is safe: Starlette
    caches the bytes so the downstream route parser re-reads the same buffer.
    """
    method = request.method.upper()
    if method not in ("POST", "PUT", "PATCH"):
        return None
    content_type = request.headers.get("content-type")
    if content_type is None:
        # No declared type: FastAPI parses such bodies as JSON; leave untouched.
        return None
    if _is_json_media_type(content_type):
        return None
    # Content-Type is present and non-JSON — only reject when a body is actually
    # present (an empty-body POST with a stray type is harmless and some routes
    # accept empty bodies). Prefer the declared length; fall back to reading the
    # (already size-capped) cached body when the header is absent.
    declared_len = request.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) <= 0:
                return None
        except (TypeError, ValueError):
            pass
    else:
        body = await request.body()
        if not body:
            return None
    received = content_type.split(";", 1)[0].strip() or lt("unbekannt", "unknown")
    return problem(
        status=415,
        detail=lt(
            "Unsupported Media Type: erwartet wird 'application/json'. "
            "Empfangen: {content_type}.",
            "Unsupported Media Type: expected 'application/json'. "
            "Received: {content_type}.",
        ).format(content_type=received),
        instance=request.url.path,
        code="request.unsupported_media_type",
        params={"content_type": received},
    )


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    # Body-size early reject (DoS finding B): refuse an oversized declared body
    # before auth / rate-limit / route work so a flood of giant payloads cannot
    # amplify cost. Applies in every mode (not just release): it is a pure
    # resource guard, never a correctness gate.
    oversized = _content_length_exceeds_limit(request)
    if oversized is not None:
        return problem(
            status=413,
            detail=(
                f"Request body too large ({oversized} bytes > "
                f"{_max_request_bytes()} bytes limit)"
            ),
            instance=request.url.path,
        )
    # Content-Type guard (finding 31): a POST/PUT/PATCH carrying a non-empty body
    # with a Content-Type that is set but is not JSON (e.g. text/plain,
    # application/x-www-form-urlencoded from a bare ``curl -d``) used to reach the
    # route's JSON body parser and surface as an unhandled HTTP 500. Reject it
    # here with a clear 415 BEFORE route parsing. A missing Content-Type is left
    # alone (many clients omit it and FastAPI parses such bodies as JSON fine),
    # and an empty body is left alone (empty-body POSTs are valid for some
    # endpoints). All JSON POST/PUT/PATCH routes in this service consume
    # application/json (no form/multipart consumers), so this is safe globally.
    media_rejection = await _reject_non_json_body(request)
    if media_rejection is not None:
        return media_rejection
    if auth.is_release_mode():
        try:
            auth.validate_release_security()
        except RuntimeError as exc:
            return problem(
                status=503,
                detail=exception_text(exc),
                instance=request.url.path,
            )
        # TrustedHost enforcement (A8): only in release mode so local dev
        # flows are untouched. Blocks DNS-rebinding style requests that carry
        # a foreign Host header.
        if not _host_is_trusted(request.headers.get("host", "")):
            return problem(
                status=400,
                detail="Untrusted Host header",
                instance=request.url.path,
            )
        # Swagger/OpenAPI gating: the interactive docs and the schema dump
        # are dev conveniences and must not be exposed on a hardened
        # deployment. 404 (not 403) so the surface is not advertised.
        if request.url.path in _docs_paths():
            return problem(
                status=404,
                detail="Not Found",
                instance=request.url.path,
            )

    token = await auth.get_user_token(request)
    policy = policy_for_path(request.url.path)
    if policy is not None:
        request.state.candyconc_route_policy = policy
        role = required_role_for_access(policy.access)
        if role is not None:
            try:
                auth.require_role(role)(token)
            except HTTPException as exc:
                return problem(
                    status=exc.status_code,
                    detail=exc.detail,
                    instance=request.url.path,
                )
    elif auth.is_release_mode() and requires_policy_for_path(request.url.path):
        logger.error("Blocked unclassified release route: %s", request.url.path)
        return problem(
            status=403,
            detail={"error": "route is not classified in release route matrix"},
            instance=request.url.path,
        )

    try:
        rate_limit.check(token, client_host=getattr(request.client, "host", None))
    except HTTPException as exc:
        # An HTTPException raised inside middleware bypasses FastAPI's
        # exception handlers and would surface as a 500 at the ASGI edge —
        # serialize the 429 (or any other limit error) as problem+json here.
        return problem(
            status=exc.status_code,
            detail=exc.detail,
            instance=request.url.path,
        )
    # Mark the request as already rate-counted so routes that also declare an
    # explicit Depends(rate_limit.dependency) do not double-count it (which
    # silently halved the effective limit for those routes).
    request.state.candyconc_rate_limit_checked = True
    return await call_next(request)


# Outermost middleware (added last): every response, including the problem+json
# answers of the guard middleware above, is rendered in the request language.
app.add_middleware(LanguageMiddleware)


# ---------------------------------------------------------------------------
# Real-time index service setup
# Both live in the user data directory (CANDYCONC_HOME or ~/.candyconc), never
# in the working directory the server was started from.
_REALTIME_DIR = _user_paths.tmp_dir() / "realtime"
_CORPUS_DIR = _user_paths.corpora_dir()
_REALTIME_DIR.mkdir(parents=True, exist_ok=True)
_CORPUS_DIR.mkdir(parents=True, exist_ok=True)
tmp_dir = Path(tempfile.gettempdir())

_INDEX_PATH: Path | None = None
_INDEX: CorpusIndex | None = None
_CORPUS_INDEX: CorpusIndex | None = None
_LANG_INDICES: Dict[str, CorpusIndex] = OrderedDict()
_LANG_INDICES_LOCK = threading.RLock()
_LANG_INDICES_LIMIT = max(1, _query_config_int("CANDYCONC_LANG_INDEX_CACHE_SIZE", 4))
_META_SCHEMA_VERSION = 1

_OBSERVABILITY: Observability | None = None


def _sync_observability_from_manager() -> None:
    """Übernimmt die vom StartupManager erzeugte Observability-Instanz.

    Bei aktivem ``CANDYCONC_ENABLE_OTEL`` liefert ``_obs_metrics_text()`` damit
    echte Metriken statt eines leeren Strings; ohne Flag bleibt
    ``_OBSERVABILITY`` unangetastet (Tests setzen es direkt per Monkeypatch).
    Die Instanz wird vom StartupManager wiederverwendet, nicht doppelt erzeugt.
    """
    global _OBSERVABILITY
    if get_config("CANDYCONC_ENABLE_OTEL", "0") == "1":
        _OBSERVABILITY = manager.observability


def _trim_lang_indices_locked() -> None:
    protected_ids = {id(idx) for idx in (_INDEX, _CORPUS_INDEX) if idx is not None}
    trim_lru_cache(
        _LANG_INDICES,
        _LANG_INDICES_LIMIT,
        protected_ids=protected_ids,
        on_evict=lambda _key, idx: close_quietly(idx),
    )


def _make_once_releaser(lock: threading.Lock) -> Callable[[], None]:
    """Return an idempotent releaser for ``lock``.

    Used by the SSE generators: the generator ``finally`` releases the
    busy-lock on a normal end-of-stream, but on a mid-stream client disconnect
    Starlette only cancels the streaming task — the suspended sync generator
    is finalized by GC *eventually* (flaky, and its ``finally`` then runs
    ``loop.run_until_complete`` during finalization). The StreamingResponse
    ``background`` hook therefore also calls the releaser, which Starlette
    runs even after a disconnect. The once-guard makes the two call sites safe
    against double-release (which would unlock a *new* holder's acquisition).
    """
    released = False
    guard = threading.Lock()

    def _release_once() -> None:
        nonlocal released
        with guard:
            if released:
                return
            released = True
        with contextlib.suppress(RuntimeError):
            lock.release()

    return _release_once


def _make_policy(token_budget: int, acl: Dict[str, List[str]] | None):
    """Create a policy object while tolerating smoke-test copilot stubs."""
    try:
        policy = PolicyEngine(token_budget=token_budget, acl=acl)
    except TypeError:
        policy = PolicyEngine()

    policy.token_budget = token_budget
    policy.remaining = getattr(policy, "remaining", token_budget)
    policy.acl = acl
    if not callable(getattr(policy, "get", None)):
        policy.get = lambda _user, _key, default=None: default
    if not callable(getattr(policy, "moderate", None)):
        policy.moderate = lambda _text: True
    return policy

def _get_active_orchestrator(
    session_id: str | None,
    token: str | None,
) -> "ReActOrchestrator":
    return _get_active_session(session_id, token).orchestrator


def _reject_temp_index_path(path: Path, *, label: str = "Index") -> None:
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if tmp_root in path.parents or path == tmp_root:
        raise RuntimeError(
            lt("{label} ist nicht erlaubt: {path}", "{label} is not allowed: {path}").format(
                label=label, path=path
            )
        )


_WORD_LEXICON_MISSING = lt(
    "Word Lexikon fehlt. Bitte Index neu bauen.",
    "Word lexicon is missing. Rebuild the index.",
)
_WORD_SKETCH_TOO_MANY_HITS = lt(
    "Word Sketch: zu viele Treffer für die Analyse ({hits} > {max_positions}). "
    "Bitte Query einschränken oder CANDYCONC_WORD_SKETCH_MAX_POSITIONS erhöhen.",
    "Word sketch: too many hits for the analysis ({hits} > {max_positions}). "
    "Narrow the query or raise CANDYCONC_WORD_SKETCH_MAX_POSITIONS.",
)
_TEMP_INDEX_LABEL = lt("Temp Index", "Temporary index")
_INDEX_PATH_MISSING = lt("Indexpfad existiert nicht: {path}", "Index path does not exist: {path}")


def _resolve_env_index_path() -> Path | None:
    env_index = os.environ.get("CANDYCONC_INDEX_PATH")
    if not env_index:
        return None
    path = Path(env_index).expanduser().resolve()
    _reject_temp_index_path(path, label=_TEMP_INDEX_LABEL)
    if not path.exists():
        raise RuntimeError(_INDEX_PATH_MISSING.format(path=path))
    return path


def _resolve_config_index_path() -> Path | None:
    cfg_index = load_settings().index_dir
    if not cfg_index:
        return None
    path = Path(cfg_index).expanduser().resolve()
    _reject_temp_index_path(path, label=_TEMP_INDEX_LABEL)
    if not path.exists():
        raise RuntimeError(_INDEX_PATH_MISSING.format(path=path))
    return path


def _configured_default_index_path() -> Path | None:
    """Return the env/config default without considering registry activation."""
    return _resolve_env_index_path() or _resolve_config_index_path()


def _active_registry_index_path() -> Path | None:
    from candyconc.domain.corpus import CorpusRegistry, has_index

    active = CorpusRegistry.load().active
    if not active:
        return None
    path = Path(active).expanduser().resolve(strict=False)
    _reject_temp_index_path(
        path,
        label=lt(
            "Aktives Registry-Korpus im Temp-Verzeichnis",
            "Active catalog corpus in the temporary directory",
        ),
    )
    if not has_index(path):
        raise RuntimeError(
            lt(
                "Aktives Registry-Korpus ist nicht bereit: {path}",
                "Active catalog corpus is not ready: {path}",
            ).format(path=path)
        )
    return path


def _startup_index_path() -> Path | None:
    """The corpus the server opens at start, or ``None`` for an empty start.

    A configured pin (``CANDYCONC_INDEX_PATH`` or ``index_dir``) must be valid,
    a broken pin stops the start with its error. Without a pin the active
    catalogue entry is used. When there is none, or it is not ready (for
    example deleted from disk), the server starts with an empty catalogue so
    that the interface can import a corpus.
    """
    pinned = _configured_default_index_path()
    if pinned is not None:
        return pinned
    try:
        active = _active_registry_index_path()
    except RuntimeError as exc:
        logger.warning("Active catalog corpus not usable: %s", exc)
        active = None
    if active is not None:
        return active
    return _activate_newest_managed_corpus()


def _activate_newest_managed_corpus() -> Path | None:
    """No corpus is active: activate the most recent ready one in the corpora dir.

    ``candy import --output ~/.candyconc/corpora/<name>`` followed by ``candy``
    then opens that corpus. Activation goes through the registry service, so a
    partial import that needs an explicit acknowledgement is not picked.
    """
    from candyconc.domain.corpus import ready_corpora_newest_first
    from candyconc.services.backend.corpus_registry_service import CorpusRegistryService

    for candidate in ready_corpora_newest_first(_CORPUS_DIR):
        try:
            CorpusRegistryService(_CORPUS_DIR, None).activate(candidate.name)
        except Exception as exc:  # partial import, name clash, unreadable manifest
            logger.info("Not activating %s at start: %s", candidate, exc)
            continue
        logger.info(
            "No corpus was active. Activated %s, the most recent corpus in %s.",
            candidate.name,
            _CORPUS_DIR,
        )
        return candidate.resolve()
    return None


def _resolve_index_path() -> Path:
    env_index = _resolve_env_index_path()
    if env_index is not None:
        return env_index
    cfg_index = _resolve_config_index_path()
    if cfg_index is not None:
        return cfg_index
    registry_index = _active_registry_index_path()
    if registry_index is not None:
        return registry_index
    raise RuntimeError(
        "No corpus is active yet. Import a corpus (web interface: Corpora, or "
        "candy import) or set CANDYCONC_INDEX_PATH."
    )


def _index_rebuilt(idx: Any) -> bool:
    """True when the folder of an open index now holds a different build."""
    check = getattr(idx, "rebuilt_on_disk", None)
    if not callable(check):
        return False
    try:
        return bool(check())
    except Exception:
        logger.debug("rebuild check failed for %r", idx, exc_info=True)
        return False


def _forget_rebuilt_index(stale: Any) -> None:
    """Drop the server's handles on an index whose folder holds a new build.

    ``candy import`` into the folder of a loaded corpus swaps in a new
    directory. The old object is not closed: requests still running on it keep
    reading intact files until their last reference goes. Caches keyed by the
    build signature invalidate themselves. The ones keyed by corpus name or
    object id are cleared here. No lock is held while the caches are cleared.
    """
    global _INDEX, _INDEX_PATH, _CORPUS_INDEX
    names: list[str] = []
    was_default = False
    with _LANG_INDICES_LOCK:
        for name, idx in list(_LANG_INDICES.items()):
            if idx is stale:
                del _LANG_INDICES[name]
                names.append(name)
        if _INDEX is stale or _CORPUS_INDEX is stale:
            _INDEX = None
            _INDEX_PATH = None
            _CORPUS_INDEX = None
            was_default = True
    if was_default:
        names.append("default")
        if "manager" in globals():
            # The background services hold the default index and its passage
            # index, both of the old build.
            manager._manager = None
    stale_path = getattr(stale, "path", None)
    logger.info("The index in %s was rebuilt. It is reopened for the next request.", stale_path)
    with contextlib.suppress(Exception):
        from candyconc.core.cql_engine import clear_engine_cache as _clear_cql_engine_cache

        if stale_path is not None:
            _clear_cql_engine_cache(stale_path)
    for name in names:
        _REFDOC_INDEX_CACHE.pop(name, None)
        _REFDOC_INDEX_DOC_COUNT.pop(name, None)
    drop_docsets_for_corpora(names)
    clear_document_fields_cache()
    with contextlib.suppress(Exception):
        from candyconc.domain import query_eval as _query_eval_mod

        # Keyed by path alone (opt-in CANDYCONC_ENABLE_QUERY_CACHE).
        _query_eval_mod.clear_positions_cache()


def get_index() -> CorpusIndex:
    global _INDEX, _INDEX_PATH, _CORPUS_INDEX
    current = _INDEX
    if current is not None:
        if not _index_rebuilt(current):
            return current
        _forget_rebuilt_index(current)
    # Double-checked locking: concurrent first accesses must share one index.
    with _LANG_INDICES_LOCK:
        if _INDEX is None:
            _INDEX_PATH = _resolve_index_path()
            idx = CorpusIndex(_INDEX_PATH)
            set_corpus(idx)
            _CORPUS_INDEX = idx
            _LANG_INDICES["en"] = idx
            mark_lru_used(_LANG_INDICES, "en")
            _trim_lang_indices_locked()
            _INDEX = idx
        return _INDEX


def set_default_index(
    idx: CorpusIndex | None,
    *,
    path: Path | None = None,
    corpus_index: CorpusIndex | None = None,
) -> None:
    """Test seam for replacing the default index without touching query_runtime."""
    global _INDEX, _INDEX_PATH, _CORPUS_INDEX
    with _LANG_INDICES_LOCK:
        _INDEX = idx
        if path is not None:
            _INDEX_PATH = path
        if corpus_index is not None:
            _CORPUS_INDEX = corpus_index


def reset_default_corpus_runtime_state() -> None:
    """Drop cached default corpus handles after registry activation changes."""
    global _INDEX, _INDEX_PATH, _CORPUS_INDEX
    global _QUERY_ROWS_RESPONSE_CACHE_BYTES, _QUERY_STREAM_BATCH_CACHE_BYTES
    global _ANCHOR_POS_CACHE_BYTES
    with _LANG_INDICES_LOCK:
        _INDEX = None
        _INDEX_PATH = None
        _CORPUS_INDEX = None
        _LANG_INDICES.clear()
    set_corpus(None)
    # Engine caches include artifact signatures, but reset must be conservative.
    try:
        from candyconc.core.cql_engine import clear_engine_cache as _clear_cql_engine_cache
        from candyconc.core.collocation_engine import clear_engine_cache as _clear_colloc_engine_cache

        _clear_cql_engine_cache()
        _clear_colloc_engine_cache()
    except Exception:  # pragma: no cover - defensive; cache-clear must never break reset
        logger.debug("engine cache clear skipped during corpus reset", exc_info=True)
    with _QUERY_ROWS_RESPONSE_CACHE_LOCK:
        _QUERY_ROWS_RESPONSE_CACHE.clear()
        _QUERY_ROWS_RESPONSE_CACHE_BYTES = 0
    with _QUERY_STREAM_BATCH_CACHE_LOCK:
        _QUERY_STREAM_BATCH_CACHE.clear()
        _QUERY_STREAM_BATCH_CACHE_BYTES = 0
    _metadata_filter_mask_cache_clear()
    with _ANCHOR_POS_CACHE_LOCK:
        _ANCHOR_POS_CACHE.clear()
        _ANCHOR_POS_CACHE_BYTES = 0
    _REFDOC_INDEX_CACHE.clear()
    _REFDOC_INDEX_DOC_COUNT.clear()
    _DOCSET_CACHE.clear()
    with _QUERY_COUNT_THREAD_LOCK:
        for state in list(_QUERY_COUNT_CACHE.values()):
            if state.task is not None and not state.task.done():
                state.task.cancel()
            if state.cancel_task is not None and not state.cancel_task.done():
                state.cancel_task.cancel()
        _QUERY_COUNT_CACHE.clear()
    try:
        from candyconc.domain import query_eval as _query_eval_mod
    except Exception:
        _query_eval_mod = None
    if _query_eval_mod is not None and hasattr(_query_eval_mod, "clear_positions_cache"):
        with contextlib.suppress(Exception):
            _query_eval_mod.clear_positions_cache()
    try:
        from candyconc.core import query_runtime as _query_runtime_mod
    except Exception:
        _query_runtime_mod = None
    if _query_runtime_mod is not None and hasattr(_query_runtime_mod, "clear_cql_positions_cache"):
        with contextlib.suppress(Exception):
            _query_runtime_mod.clear_cql_positions_cache()
    if "manager" in globals():
        with contextlib.suppress(Exception):
            manager._manager = None


def aktivierung_wirkungslos(erwarteter_pfad: str | None) -> str | None:
    """Does env or config pin the index so that activation does nothing?

    ``POST /corpora/{name}/activate`` can answer 200 and the registry can list
    the corpus as ``active: true`` while ``get_index()`` stays on the pinned
    index, because its precedence is env > config > registry.

    The copilot tools resolve a missing ``corpus`` parameter via
    ``get_index()``, so questions about the NEW corpus would be answered with
    numbers from the old one. Example: a Danish frequency question with
    ``kunne`` = 1 instead of 98,086 and a reference size of 273,550,093
    instead of 47,058,875 tokens. Formally clean, entirely wrong in
    substance, and without any error message.

    An activation that reports 200 and changes nothing is worse than an
    error: it creates trust in a switch that did not happen. Returns the
    reason if the activation stays without effect, otherwise ``None``.
    """
    if not erwarteter_pfad:
        return None
    try:
        gepinnt = _configured_default_index_path()
    except RuntimeError:
        # Ein unbrauchbarer Pin ist ein eigenes Problem und wird an
        # anderer Stelle gemeldet; hier zaehlt nur, ob er die Aktivierung
        # uebersteuert.
        return None
    if gepinnt is None:
        return None
    ziel = Path(str(erwarteter_pfad)).expanduser().resolve(strict=False)
    if gepinnt == ziel:
        return None
    quelle = (
        lt(
            "die Umgebungsvariable CANDYCONC_INDEX_PATH",
            "the environment variable CANDYCONC_INDEX_PATH",
        )
        if os.environ.get("CANDYCONC_INDEX_PATH")
        else lt("index_dir in der Konfiguration", "index_dir in the configuration")
    )
    return lt(
        "Aktivierung waere wirkungslos: {quelle} nagelt den Index auf "
        "{gepinnt} fest, waehrend {ziel} aktiviert werden soll. Die "
        "Praezedenz lautet env > config > registry, der Copilot wuerde "
        "also weiter auf dem gepinnten Index rechnen. Pin entfernen oder "
        "auf den Zielkorpus setzen.",
        "Activation would have no effect: {quelle} pins the index to "
        "{gepinnt}, while {ziel} is to be activated. The precedence is "
        "env > config > registry, so the copilot would keep working on the "
        "pinned index. Remove the pin or point it to the target corpus.",
    ).format(quelle=quelle, gepinnt=gepinnt, ziel=ziel)


async def reload_default_corpus_runtime_state() -> None:
    """Reset default-corpus state and reload running background services."""
    global _STARTED_WITHOUT_CORPUS
    old_manager = manager._manager if "manager" in globals() else None
    if old_manager is not None:
        try:
            await old_manager.stop()
        except Exception:
            logger.exception("Failed to stop old default-corpus manager during reload")
    reset_default_corpus_runtime_state()
    if old_manager is not None or _STARTED_WITHOUT_CORPUS:
        if old_manager is None and _startup_index_path() is None:
            # Still no usable corpus (e.g. a corpus was registered without
            # activation): stay in the empty state.
            return
        faiss_index, faiss_vecs, faiss_texts = _faiss_paths()
        await manager.start(faiss_index, faiss_vecs, faiss_texts)
        _sync_observability_from_manager()
        _STARTED_WITHOUT_CORPUS = False


class _ManagerProxy:
    def __init__(self) -> None:
        self._manager: StartupManager | None = None

    def _get(self) -> StartupManager:
        if self._manager is None:
            idx = get_index()
            self._manager = StartupManager(idx, _REALTIME_DIR)
        return self._manager

    def __getattr__(self, name: str):
        return getattr(self._get(), name)

    def __setattr__(self, name: str, value):
        if name == "_manager":
            super().__setattr__(name, value)
        else:
            setattr(self._get(), name, value)


manager = _ManagerProxy()


def _is_cql_oov_zero_hits(exc: ValueError) -> bool:
    """Return True if a CQL ValueError means "no such hits", not a real failure.

    The CQL engine raises a ValueError when an exact-match condition resolves to
    a word/lemma/pos that is simply not in the corpus vocabulary (out-of-vocab).
    Semantically that is an empty result, identical to the plain-term path which
    returns 0. Treating it as an error would make ``/query/count`` claim a
    failure for a perfectly valid query whose term happens to be absent.

    Genuine failures (parse errors, timeouts, unknown attributes) are NOT
    matched here and keep propagating so the endpoint reports them honestly.
    Entschieden wird am Typ der Ausnahme, nicht an ihrem Meldungstext (siehe
    ``cqlhpc.errors``).
    """
    return isinstance(exc, (EmptyMatchError, UnresolvableConditionError))


def _compute_query_count(
    idx: CorpusIndex,
    term: str,
    ctx: int,
    date: str | None,
    genre: str | None,
    docset_mask: np.ndarray | None = None,
    *,
    case_insensitive: bool = True,
) -> tuple[int, float, bool]:
    from candyconc.domain.query_eval import prefetch_positions
    from candyconc.core.cql_engine import count_cql_matches_backend

    started = time.perf_counter()
    from candyconc.core.cql_macros import normalize_query_input

    # NFKC-canonicalize before query-input normalization so a codepoint variant
    # counts the same as the row path.
    term_str = normalize_query_input(_canonicalize_term(term.strip()))
    metadata_mask = _metadata_filter_docset_mask(idx, date=date, genre=genre)
    effective_docset_mask = _combine_docset_masks(docset_mask, metadata_mask)
    if term_str.lower().startswith("cql:"):
        query = term_str[4:].strip()
        if not query:
            return 0, (time.perf_counter() - started) * 1000, False
        # Counts are evidence, not previews.  A result that only covers a
        # prefix of a CQL match set is not a usable count, so calculations scan
        # the complete index domain (the index itself rejects larger domains).
        cql_count_limit = _CQL_COUNT_PROBE_HARD_MAX
        cql_count_timeout = float(get_config("CANDYCONC_CQL_COUNT_TIMEOUT", "0"))

        def progress_cb(_msg: str) -> None:
            if cql_count_timeout <= 0:
                return
            if (time.perf_counter() - started) > cql_count_timeout:
                raise TimeoutError("CQL count timed out")

        if effective_docset_mask is None:
            try:
                if _linebreak_sentinel_word_id(idx) > 0:
                    # Route through the SAME |LBR| sentinel-drop seam the rows path
                    # uses so the count equals the rendered rows ([word="|LBR|"] ->
                    # 0, [word=".*"] excludes the line-break marker). Materialises
                    # positions (capped at the probe limit) and drops the one
                    # sentinel word-id. Only when this index HAS the sentinel — a
                    # sentinel-free index keeps the cheap pure-count probe below.
                    count, _capped = _exact_cql_count_sentinel_dropped(
                        idx, query, probe_limit=cql_count_limit, progress_cb=progress_cb
                    )
                else:
                    from candyconc.core.cql_engine import count_cql_matches_backend

                    raw = int(
                        count_cql_matches_backend(
                            idx.fast_index,
                            query,
                            max_matches=cql_count_limit,
                            progress_cb=progress_cb,
                        )
                    )
                    count = raw
            except ValueError as exc:
                # Out-of-vocab exact match is an empty result, not a failure:
                # mirror the plain-term path which returns 0 for unknown words.
                if _is_cql_oov_zero_hits(exc):
                    return 0, (time.perf_counter() - started) * 1000, False
                raise
            except RuntimeError as exc:
                # A pure corpus count of a regex cell needs no positions
                # (regex_type_count).
                from .regex_type_count import zaehlen as _regex_zaehlen

                count = _regex_zaehlen(idx, query, _linebreak_sentinel_word_id) if "Treffer zu gross" in str(exc) else None
                if count is None:
                    raise
            elapsed_ms = (time.perf_counter() - started) * 1000
            return int(count), elapsed_ms, False
        try:
            if _linebreak_sentinel_word_id(idx) > 0:
                from candyconc.core.cql_engine import search_cql_match_arrays_backend

                starts, _ends = search_cql_match_arrays_backend(
                    idx.fast_index,
                    query,
                    limit=cql_count_limit,
                    progress_cb=progress_cb,
                    docset_mask=effective_docset_mask,
                )
                positions = np.asarray(starts, dtype=np.uint32)
                positions, _ = _drop_linebreak_sentinel_positions(idx, positions)
                count = int(positions.size)
                elapsed_ms = (time.perf_counter() - started) * 1000
                return count, elapsed_ms, False

            raw = int(
                count_cql_matches_backend(
                    idx.fast_index,
                    query,
                    max_matches=cql_count_limit,
                    progress_cb=progress_cb,
                    docset_mask=effective_docset_mask,
                )
            )
        except ValueError as exc:
            if _is_cql_oov_zero_hits(exc):
                return 0, (time.perf_counter() - started) * 1000, False
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        return raw, elapsed_ms, False

    if not term_str:
        return 0, (time.perf_counter() - started) * 1000, False

    # Use the single-token override only for case-sensitive queries. The
    # default path counts case-insensitively through count_positions,
    # query_eval and term_positions. Mirror _prepare_plain_rows_fast so
    # the streamed count equals the rendered row count.
    use_cs_fast = (
        not case_insensitive
        and _term_positions_supports_case_insensitive()
        and _is_simple_single_token(term_str)
    )
    # Every plain branch drops the |LBR| sentinel through the SAME seam as
    # _prepare_plain_rows_fast, so a literal "|LBR|" in the search box counts 0
    # (matching its 0 rendered rows). The no-mask branch resolves positions
    # (instead of the count-only count_positions) because the sentinel can only be
    # excluded by inspecting per-match node tokens.
    if use_cs_fast:
        positions = _plain_term_positions_cs(idx, term_str)
        if effective_docset_mask is not None:
            positions = _filter_positions_by_docset(idx, positions, effective_docset_mask)
    elif effective_docset_mask is None:
        positions = prefetch_positions(
            term_str,
            idx,
            **({"case_insensitive": False} if not case_insensitive else {}),
        )
    else:
        positions = prefetch_positions(
            term_str,
            idx,
            **({"case_insensitive": False} if not case_insensitive else {}),
        )
        positions = _filter_positions_by_docset(idx, positions, effective_docset_mask)
    positions, _ = _drop_linebreak_sentinel_positions(idx, np.asarray(positions))
    count = int(positions.size)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return count, elapsed_ms, False


_DEFAULT_USERS = Path(__file__).resolve().parents[4] / "config" / "users.json"

# Global dry-run mode flag
DRY_RUN = APP_CONFIG.DRY_RUN

def _load_tools() -> None:
    """Import tool modules to populate the registry."""
    __import__("candyconc.tooling")


async def reset_faiss_build() -> None:
    """Cancel running FAISS build task and clear the global handle."""

    if manager.faiss_build_task is not None:
        if not manager.faiss_build_task.done():
            manager.faiss_build_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await manager.faiss_build_task
        manager.faiss_build_task = None


def _prewarm_query_path(idx: CorpusIndex) -> None:
    from candyconc.core.cql_engine import _get_engine

    prewarm_shape_queries = get_config("CANDYCONC_PREWARM_SHAPE_QUERIES", "1") == "1"
    shape_limit = max(1, int(get_config("CANDYCONC_PREWARM_SHAPE_LIMIT", "200")))
    prewarm_shape_responses = get_config("CANDYCONC_PREWARM_SHAPE_RESPONSES", "1") == "1"
    _corpus, query_engine = _get_engine(idx.fast_index)
    if _corpus is not None:
        token_to_sent = getattr(_corpus, "token_to_sent", None)
        if callable(token_to_sent):
            try:
                token_to_sent()
            except Exception:
                pass
        sent_to_doc = getattr(_corpus, "sent_to_doc", None)
        if callable(sent_to_doc):
            try:
                sent_to_doc()
            except Exception:
                pass
    fast = idx.fast_index
    word_lex = getattr(fast.lexicons, "word", None)
    if word_lex is not None:
        text_cache = getattr(fast, "_kwic_string_cache", None)
        top_ids = getattr(word_lex, "top_global_ids", None)
        warm_limit = max(
            0,
            int(get_config("CANDYCONC_PREWARM_KWIC_STRINGS", "4096")),
        )
        if text_cache is not None and top_ids is not None and warm_limit > 0:
            for raw_tid in top_ids[:warm_limit]:
                tid = int(raw_tid)
                if tid <= 0:
                    continue
                if isinstance(text_cache, list):
                    if tid >= len(text_cache) or text_cache[tid] is not None:
                        continue
                    text_cache[tid] = word_lex.get_string(tid)
                else:
                    if tid in text_cache:
                        continue
                    text_cache[tid] = word_lex.get_string(tid)
        dense_bitset_warm_limit = max(
            0,
            int(get_config("CANDYCONC_PREWARM_DENSE_WORD_BITSETS", "8")),
        )
        dense_bitset_for_type = getattr(query_engine, "_dense_bitset_for_type", None)
        if callable(dense_bitset_for_type) and top_ids is not None and dense_bitset_warm_limit > 0:
            warmed = 0
            for raw_tid in top_ids:
                if warmed >= dense_bitset_warm_limit:
                    break
                tid = int(raw_tid)
                if tid <= 0:
                    continue
                try:
                    bitset = dense_bitset_for_type("word", tid)
                except Exception:
                    continue
                if bitset is not None:
                    warmed += 1
        positions_warm_limit = max(
            0,
            int(get_config("CANDYCONC_PREWARM_WORD_POSITIONS", "4")),
        )
        get_word_positions = getattr(getattr(fast, "token_store", None), "get_positions_for_word_id", None)
        if callable(get_word_positions) and top_ids is not None and positions_warm_limit > 0:
            warmed = 0
            for raw_tid in top_ids:
                if warmed >= positions_warm_limit:
                    break
                tid = int(raw_tid)
                if tid <= 0:
                    continue
                try:
                    get_word_positions(tid)
                except Exception:
                    continue
                warmed += 1
    doc_bounds = _doc_bounds_for_index(idx)
    meta_store = getattr(idx.fast_index, "doc_metadata", None)
    prepared_many = getattr(meta_store, "prepared_entries_many", None)
    query_many = getattr(meta_store, "query_entries_many", None)
    doc_count = int(doc_bounds.shape[0])
    prewarm_query_meta_max_docs = max(
        0,
        int(get_config("CANDYCONC_PREWARM_QUERY_META_MAX_DOCS", "250000")),
    )
    prewarm_query_meta_batch = max(
        1,
        int(get_config("CANDYCONC_PREWARM_QUERY_META_BATCH", "4096")),
    )
    if callable(query_many) and doc_count and doc_count <= prewarm_query_meta_max_docs:
        for start in range(0, doc_count, prewarm_query_meta_batch):
            stop = min(doc_count, start + prewarm_query_meta_batch)
            query_many(range(start, stop))
        if isinstance(getattr(meta_store, "_query_cache", None), list):
            setattr(meta_store, "_query_cache_complete", True)
    if callable(prepared_many):
        warm_ids = list(
            range(
                min(
                    doc_count,
                    max(0, int(get_config("CANDYCONC_PREWARM_DOC_META", "1024"))),
                )
            )
        )
        if warm_ids:
            prepared_many(warm_ids)
    if prewarm_shape_queries:
        cache_index_key = _corpus_cache_signature(fast, "default")
        cql_cases = (
            'cql:[word~"^un.*"] [word="ist"]',
            'cql:within(<s>, [word="und"]+ [word="ist"])',
            'cql:[word="und"] ([word="der"]|[word="die"]){0,30} [word="ist"]',
        )
        plain_cases = (
            ("*ung", shape_limit),
            ("*lich*", shape_limit),
            ("un*", shape_limit),
        )

        for term in cql_cases:
            try:
                rows = _query_rows_cql_fast(idx, term, ctx=5, limit=None)
                if prewarm_shape_responses and rows:
                    if isinstance(rows[0], tuple):
                        rows = _enrich_compact_tuple_rows_with_doc_meta(
                            idx,
                            rows,
                            row_has_offsets=(len(rows[0]) > 5),
                        )
                    payload = _json_dumps_fast_bytes(rows)
                    _query_rows_response_cache_set(
                        (cache_index_key, str(term), 5, "", "", -1),
                        payload,
                    )
            except Exception:
                pass
        for term, limit in plain_cases:
            try:
                rows = _query_rows_plain_fast(idx, term, ctx=5, limit=limit)
                if prewarm_shape_responses and rows:
                    if isinstance(rows[0], tuple):
                        rows = _enrich_compact_tuple_rows_with_doc_meta(
                            idx,
                            rows,
                            row_has_offsets=(len(rows[0]) > 5),
                        )
                    payload = _json_dumps_fast_bytes(rows)
                    _query_rows_response_cache_set(
                        (cache_index_key, str(term), 5, "", "", int(limit)),
                        payload,
                    )
            except Exception:
                pass


#: True while the server runs without any corpus (first start, empty catalogue).
_STARTED_WITHOUT_CORPUS = False


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    global _STARTED_WITHOUT_CORPUS
    APP_CONFIG.validate()
    _load_tools()
    if _INDEX is None and _startup_index_path() is None:
        _STARTED_WITHOUT_CORPUS = True
        await start_without_corpus()
        logger.info(
            "No corpus yet: the catalog is empty. Import a corpus in the web "
            "interface (Corpora) or with 'candy import'."
        )
    else:
        faiss_index, faiss_vecs, faiss_texts = _faiss_paths()
        await manager.start(faiss_index, faiss_vecs, faiss_texts)
        _sync_observability_from_manager()
        if get_config("CANDYCONC_PREWARM_QUERY_PATH", "1") == "1":
            try:
                await asyncio.to_thread(_prewarm_query_path, get_index())
            except Exception:
                logger.exception("Query prewarm failed")
    if not APP_CONFIG.copilot_configured:
        logger.info(
            "Copilot: no language model configured (COPILOT_ENDPOINT). Everything "
            "else works, the chat reports that no model is set up."
        )
    logger.info("KWIC engine: %s", kwic_adapter.engine)
    logger.info("Startup complete")
    try:
        yield
    finally:
        if manager._manager is not None:
            await manager.stop()
        else:
            await stop_without_corpus()
        # Close the shared HTTP clients during application shutdown.
        try:
            from candyconc.services.llm_client import aclose_http_clients

            await aclose_http_clients()
        except Exception:  # pragma: no cover - Abbau darf nie werfen
            logger.exception("HTTP-Clients konnten nicht geschlossen werden")


app.router.lifespan_context = lifespan


def _faiss_paths() -> tuple[Path, Path, Path]:
    idx = get_index()
    base = Path(idx.fast_index.index_path)
    return (
        base / "faiss_passage.index",
        base / "passage_vecs.npy",
        base / "passage_texts.json",
    )


# Strong references to the fire-and-forget FAISS reset tasks: a bare
# ``asyncio.create_task`` inside a done-callback is only weakly referenced by
# the loop, so it can be garbage-collected mid-flight and any exception it
# raises is silently swallowed. Hold a reference until completion and log
# failures explicitly.
_FAISS_RESET_TASKS: set["asyncio.Task[None]"] = set()


def _on_faiss_reset_done(task: "asyncio.Task[None]") -> None:
    _FAISS_RESET_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("reset_faiss_build failed: %s", exc, exc_info=exc)


def _schedule_faiss_reset(_build_task: "asyncio.Task[None]") -> None:
    task = asyncio.create_task(reset_faiss_build())
    _FAISS_RESET_TASKS.add(task)
    task.add_done_callback(_on_faiss_reset_done)


async def start_faiss_build(corpus_path: str) -> str:
    """Start background FAISS index build."""

    if manager.faiss_build_task is not None and not manager.faiss_build_task.done():
        raise RuntimeError("build running")
    if faiss is None:
        manager.faiss_status = "error"
        reason = lt(
            "FAISS fehlt, aber ein Index-Rebuild wurde angefordert.",
            "FAISS is missing, but an index rebuild was requested.",
        )
        if hasattr(manager, "faiss_status_detail"):
            manager.faiss_status_detail = reason
        raise RuntimeError(reason)

    def resolve_index_dir(value: str) -> Path:
        raw = (value or "default").strip() or "default"
        if raw.lower() == "default":
            return Path(get_index().fast_index.index_path).expanduser().resolve()
        path = Path(raw).expanduser()
        if path.exists():
            return path.resolve()
        try:
            return Path(get_corpus(raw).fast_index.index_path).expanduser().resolve()
        except HTTPException as exc:
            detail = exc.detail
            raise RuntimeError(detail if isinstance(detail, LocalizedText) else str(detail)) from exc

    index_dir = resolve_index_dir(corpus_path)
    if not ((index_dir / "passage_vecs.npy").exists() and (index_dir / "passage_texts.json").exists()):
        # The build embeds the passages with the corpus pipeline. Report a
        # corpus without word vectors now instead of in a failed job.
        from candyconc.core.word_vectors import vector_pipeline

        vector_pipeline(index_dir)
    job_id = uuid.uuid4().hex
    queue = jobs.create(job_id)
    loop = asyncio.get_running_loop()

    def report(progress: int, msg: str) -> None:
        asyncio.run_coroutine_threadsafe(
            queue.put({"progress": progress, "msg": msg}), loop
        )

    async def runner() -> None:
        try:
            manager.faiss_status = "building"
            if hasattr(manager, "faiss_status_detail"):
                manager.faiss_status_detail = None
            faiss_index = index_dir / "faiss_passage.index"
            faiss_vecs = index_dir / "passage_vecs.npy"
            faiss_texts = index_dir / "passage_texts.json"
            has_passage_embeddings = faiss_vecs.exists() and faiss_texts.exists()
            build_func = (
                index_utils.build_faiss_index
                if has_passage_embeddings
                else index_utils.build_faiss_index_from_fast_index
            )
            await asyncio.to_thread(
                build_func,
                index_dir,
                index_dir,
                progress_cb=report,
                confirm=None,
            )
            await manager._load_faiss(faiss_index, faiss_vecs, faiss_texts)
            await queue.put({"progress": 100, "msg": "saved"})
            manager.faiss_status = "ready"
        except Exception as exc:  # pragma: no cover - build failure
            await queue.put({"progress": 100, "msg": f"error: {exc}"})
            manager.faiss_status = "error"
            if hasattr(manager, "faiss_status_detail"):
                manager.faiss_status_detail = exception_text(exc)

    manager.faiss_build_task = asyncio.create_task(runner())
    manager.faiss_build_task.add_done_callback(_schedule_faiss_reset)
    return job_id



def _configured_default_index_path_for_catalogue() -> Path | None:
    try:
        return _configured_default_index_path()
    except RuntimeError:
        return None


def _resolve_catalogue_corpus_index_path(name: str) -> tuple[str, Path]:
    from candyconc.services.backend.corpus_registry_service import CorpusRegistryService

    try:
        service = CorpusRegistryService(_CORPUS_DIR, _configured_default_index_path_for_catalogue())
        summary = service.inspect(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc

    status = str(summary.get("status") or "")
    if status != "ready":
        code = 404 if status == "missing" else 409
        raise HTTPException(
            status_code=code,
            detail={
                "status": status or "missing",
                "reason": summary.get("status_reason") or lt("Korpus ist nicht bereit", "Corpus is not ready"),
                "corpus": summary.get("name") or name,
            },
        )
    raw_path = str(summary.get("path") or "").strip()
    if not raw_path:
        raise ApiError(
            404,
            "corpus.not_found",
            lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"),
            name=name,
        )
    path = Path(raw_path).expanduser().resolve(strict=False)
    return str(summary.get("name") or name), path


def get_corpus(name: str | None) -> CorpusIndex:
    """Return CorpusIndex for the given name or the default index."""
    if not name or str(name).strip().lower() == "default":
        # get_index() raises a RuntimeError when no index is configured / the
        # path is missing / the active registry corpus is not ready. That is an
        # unserveable-server-state condition, not a bad request — map it to 503
        # here so the ~25 routes that resolve the default corpus via get_corpus()
        # stop leaking a 500 (god-module finding D). get_index() keeps raising the
        # raw RuntimeError for internal callers.
        try:
            return get_index()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
    corpus_name, corpus_path = _resolve_catalogue_corpus_index_path(str(name))

    with _LANG_INDICES_LOCK:
        cached = _LANG_INDICES.get(corpus_name)
        if cached is not None:
            mark_lru_used(_LANG_INDICES, corpus_name)
    if cached is not None:
        moved = Path(str(getattr(cached, "path", corpus_path))) != corpus_path
        if not moved and not _index_rebuilt(cached):
            return cached
        _forget_rebuilt_index(cached)

    # Double-checked locking: concurrent first accesses must share one index.
    with _LANG_INDICES_LOCK:
        existing = _LANG_INDICES.get(corpus_name)
        if existing is not None:
            mark_lru_used(_LANG_INDICES, corpus_name)
            return existing
        try:
            idx = CorpusIndex(corpus_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
        _LANG_INDICES[corpus_name] = idx
        mark_lru_used(_LANG_INDICES, corpus_name)
        _trim_lang_indices_locked()
        return idx


_CACHE_SIG_ARTIFACTS = ("meta.bin", "document_bounds.bin", "index_build_meta.json", "index_manifest.json")


def _corpus_cache_signature(fast_index: Any, fallback: str) -> str:
    """Cache-key component that changes when the index is rebuilt in place.

    Keying corpus response/stream caches on the index path string ALONE serves stale
    results after an in-place rebuild (same path, new content). Mix in the newest
    mtime of a few representative index artifacts so a rebuild invalidates the
    dependent caches. Falls back to the path (or ``fallback``) when nothing stat-able.
    """
    index_path = getattr(fast_index, "index_path", None)
    if not index_path:
        return str(fallback)
    base = Path(str(index_path))
    newest = 0
    for name in _CACHE_SIG_ARTIFACTS:
        try:
            mtime = (base / name).stat().st_mtime_ns
        except OSError:
            continue
        if mtime > newest:
            newest = mtime
    return f"{index_path}@{newest}" if newest else str(index_path)


def _canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read_count_header(path: Path) -> int | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(8)
    except OSError:
        return None
    if len(raw) != 8:
        return None
    return int.from_bytes(raw, byteorder="little", signed=False)


def _read_lexicon_vocab_size(path: Path) -> int | None:
    try:
        with path.open("rb") as fh:
            raw = fh.read(12)
    except OSError:
        return None
    if len(raw) != 12 or raw[:4] != b"LEX2":
        return None
    version = int.from_bytes(raw[4:8], byteorder="little", signed=False)
    if version != 1:
        return None
    return int.from_bytes(raw[8:12], byteorder="little", signed=False)


def _read_lexicon_single_value(path: Path) -> str | None:
    """Return the only string of a LEX2 lexicon with one entry, else None.

    Layout (core/index_format.py): a 32 byte header, offsets[vocab+1] and
    freqs[vocab+1] as u64, then the blob. Term ids start at 1, term ``i``
    starts at ``offsets[i]`` and the last one ends at the end of the blob.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) < 32 or raw[:4] != b"LEX2":
        return None
    version, vocab = struct.unpack_from("<II", raw, 4)
    if version != 1 or vocab != 1:
        return None
    blob_size = struct.unpack_from("<Q", raw, 24)[0]
    start = struct.unpack_from("<Q", raw, 32 + 8)[0]
    blob_offset = 32 + 16 * (vocab + 1)
    blob = raw[blob_offset: blob_offset + blob_size]
    if start > len(blob):
        return None
    try:
        return blob[start:].decode("utf-8")
    except UnicodeDecodeError:
        return None


#: Values the builder writes into ``model``, ``text_type`` and ``variant`` of
#: every document of an unpaired corpus (build_fast_index_from_parquet).
#: A field that holds only its placeholder says nothing about the texts and
#: is marked, so that interfaces do not offer it as a filter.
_BUILDER_PLACEHOLDER_VALUES = {
    "model": "none",
    "text_type": "standalone",
    "variant": "document",
}


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_meta_schema_index_path(corpus: str | None) -> tuple[str, Path]:
    """Resolve an index path without constructing a CorpusIndex."""
    corpus_name = str(corpus or "default").strip() or "default"
    if corpus_name.lower() == "default":
        try:
            index_path = _resolve_index_path()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
        from candyconc.domain.corpus import has_index

        if not has_index(index_path):
            raise ApiError(
                503,
                "corpus.default_index_invalid",
                lt("Default-Index ist kein CandyConc Index", "The default index is not a CandyConc index"),
            )
        return "default", index_path

    return _resolve_catalogue_corpus_index_path(corpus_name)


def _meta_schema_doc_metadata_store(index_path: Path) -> dict[str, Any]:
    idx_path = index_path / "doc_metadata.idx.bin"
    blob_path = index_path / "doc_metadata.mmap"
    crc_path = index_path / "doc_metadata.crc.bin"
    offsets_count = _read_count_header(idx_path)
    document_count = max(0, int(offsets_count) - 1) if offsets_count is not None else None
    return {
        "available": bool(idx_path.exists() and blob_path.exists()),
        "format": "mmap" if idx_path.exists() and blob_path.exists() else None,
        "documentCount": document_count,
        "crcAvailable": bool(crc_path.exists()),
    }


def _meta_schema_meta_index(index_path: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    meta_dir = index_path / "meta_index"
    manifest_path = meta_dir / "meta_index.json"
    if not manifest_path.exists():
        warnings.append("meta_index manifest missing")
        return {
            "available": False,
            "version": None,
            "documentCount": None,
            "fieldCount": 0,
            "fields": [],
        }, warnings

    try:
        manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        warnings.append("meta_index manifest unreadable")
        return {
            "available": False,
            "version": None,
            "documentCount": None,
            "fieldCount": 0,
            "fields": [],
            "error": "unreadable_manifest",
        }, warnings

    if not isinstance(manifest_raw, dict):
        warnings.append("meta_index manifest has invalid shape")
        return {
            "available": False,
            "version": None,
            "documentCount": None,
            "fieldCount": 0,
            "fields": [],
            "error": "invalid_manifest",
        }, warnings

    fields: list[dict[str, Any]] = []
    raw_fields = manifest_raw.get("fields", [])
    if not isinstance(raw_fields, list):
        raw_fields = []
        warnings.append("meta_index fields list missing")

    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name") or "").strip()
        prefix = str(raw_field.get("prefix") or "").strip()
        if not name or not prefix:
            continue
        has_string = bool(raw_field.get("has_str", raw_field.get("hasString", False)))
        has_number = bool(raw_field.get("has_num", raw_field.get("hasNumber", False)))
        if has_string and has_number:
            kind = "mixed"
        elif has_string:
            kind = "string"
        elif has_number:
            kind = "number"
        else:
            kind = "unknown"

        string_count = _read_lexicon_vocab_size(meta_dir / f"{prefix}.lex.bin") if has_string else 0
        numeric_count = _read_count_header(meta_dir / f"{prefix}.num_values.bin") if has_number else 0
        fields.append(
            {
                "name": name,
                "kind": kind,
                "hasString": has_string,
                "hasNumber": has_number,
                "stringValueCount": string_count,
                "numericValueCount": numeric_count,
            }
        )

    fields.sort(key=lambda item: str(item["name"]))
    return {
        "available": True,
        "version": _safe_int(manifest_raw.get("version"), 1),
        "documentCount": _safe_int(manifest_raw.get("doc_count"), 0),
        "fieldCount": len(fields),
        "fields": fields,
    }, warnings


def _meta_schema_placeholder_fields(index_path: Path) -> set[str]:
    """Names of metadata fields that hold only the builder placeholder."""
    meta_dir = index_path / "meta_index"
    try:
        manifest = json.loads((meta_dir / "meta_index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names: set[str] = set()
    for raw_field in manifest.get("fields", []) if isinstance(manifest, dict) else []:
        if not isinstance(raw_field, dict):
            continue
        name = str(raw_field.get("name") or "").strip()
        prefix = str(raw_field.get("prefix") or "").strip()
        placeholder = _BUILDER_PLACEHOLDER_VALUES.get(name)
        if placeholder is None or not prefix or raw_field.get("has_num"):
            continue
        if _read_lexicon_single_value(meta_dir / f"{prefix}.lex.bin") == placeholder:
            names.add(name)
    return names


def _build_meta_schema_fingerprint(index_path: Path, corpus_name: str) -> dict[str, Any]:
    meta_index, warnings = _meta_schema_meta_index(index_path)
    doc_metadata_store = _meta_schema_doc_metadata_store(index_path)
    document_bounds_count = _read_count_header(index_path / "document_bounds.bin")
    count_candidates = [
        document_bounds_count,
        meta_index.get("documentCount"),
        doc_metadata_store.get("documentCount"),
    ]
    non_null_counts = [int(v) for v in count_candidates if isinstance(v, int)]
    document_count = non_null_counts[0] if non_null_counts else 0
    if len(set(non_null_counts)) > 1:
        warnings.append("document count mismatch across index artifacts")

    metadata_fields = list(meta_index.get("fields") or [])
    signature = {
        "schemaVersion": _META_SCHEMA_VERSION,
        "documentCount": document_count,
        "documentBoundsCount": document_bounds_count,
        "metaIndex": meta_index,
        "docMetadataStore": doc_metadata_store,
    }
    metadata_signature = {
        "schemaVersion": _META_SCHEMA_VERSION,
        "metaIndex": meta_index,
    }
    index_fingerprint = _canonical_sha256(signature)
    metadata_schema_hash = _canonical_sha256(metadata_signature)
    # Marked after hashing: the fingerprints describe the index artifacts and
    # stay the same as before the mark existed.
    placeholders = _meta_schema_placeholder_fields(index_path)
    metadata_fields = [
        {**field, "placeholder": True} if field.get("name") in placeholders else field
        for field in metadata_fields
    ]
    return {
        "schemaVersion": _META_SCHEMA_VERSION,
        "corpus": corpus_name,
        "documentCount": document_count,
        "indexFingerprint": index_fingerprint,
        "metadataSchemaHash": metadata_schema_hash,
        "fingerprint": index_fingerprint,
        "fingerprintStrength": "structural_index_artifacts",
        "metadataFields": metadata_fields,
        "metaIndex": meta_index,
        "docMetadataStore": doc_metadata_store,
        "warnings": warnings,
    }


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                with contextlib.suppress(OSError):
                    total += entry.stat().st_size
    except Exception:
        return 0
    return total


def _format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _dispersion_classification(
    dp: float,
    *,
    total_hits: int | None = None,
    dp_erwartet: float | None = None,
    dp_min: float | None = None,
    dp_max: float | None = None,
) -> str:
    """Map a raw Gries DP value to a coarse qualitative label.

    Lower DP means a more even spread; higher DP means clustered.
    """
    # Eine Weiterleitung: die Schnittpunkte liegen in analysis_defaults,
    # damit die Copilot-Naht dieselben benutzt. Zwei eigene Leitern haben
    # sich das Wort "fairly_even" bei verschiedenen Grenzen geteilt.
    from candyconc.analysis_defaults import dispersion_classification

    return dispersion_classification(
        dp, total_hits=total_hits, dp_erwartet=dp_erwartet,
        dp_min=dp_min, dp_max=dp_max)


def _doc_ids_from_meta(idx: CorpusIndex, filters: Dict[str, Any]) -> np.ndarray:
    meta = idx.fast_index.meta_index
    if meta is None:
        raise RuntimeError(
            lt("Meta Index fehlt. Bitte Index neu bauen.", "Metadata index is missing. Rebuild the index.")
        )
    # VOR dem Bau des Ausdrucks, nicht in seinem None-Zweig. Die
    # Vorfassung prueft erst, wenn der GANZE Filter zu nichts normalisiert,
    # und erreichte damit den haeufigen Fall nie: bei
    # {"split": "", "source": "tweets"} traegt `source` einen
    # Ausdruck, `split` faellt still weg, und die Antwort lieferte 2000
    # Dokumente statt 683, byte-gleich zum Aufruf ganz ohne `split`.
    from candyconc.core.meta_filters import (
        pruefe_filter_traegt_bedingung,
        unbekannte_felder,
    )

    # The same contract as ``metadata_mask``, which answers an unknown field
    # with the EMPTY set, in every direction. Without these checks this
    # function would answer on a test index with 2,000 documents::
    #
    #     {"gibtsnichtxyz": "x"}                        RuntimeError -> 500
    #     {"gibtsnichtxyz": ""}                         2000 = whole corpus
    #     {"gibtsnichtxyz": {"op":"!=","value":"x"}}    RuntimeError -> 500
    #     {"gibtsnichtxyz": "x", "split": "test"}       RuntimeError -> 500
    #
    # One of the four answers is the unfiltered corpus with a success
    # message, three are a server error on a user input. None of them is
    # "matches nothing".
    if filters and unbekannte_felder(idx.fast_index, filters):
        return np.zeros(0, dtype=np.uint32)
    pruefe_filter_traegt_bedingung(filters, fast_index=idx.fast_index)
    expr = _build_meta_expr(filters)
    doc_count = int(meta.doc_count) if meta.doc_count else _doc_count_for_index(idx)
    if expr is None:
        # NO filter means the whole corpus. A filter that normalizes to
        # nothing does NOT mean that: the caller meant a restriction and
        # would get everything. On a test index with 2,000 documents:
        #     {}                  2000   correct
        #     {"split": "test"}    683
        #     {"split": "   "}    2000   the whole corpus
        #     {"split": ""}       2000
        #     {"split": None}     2000
        # The LIST forms of the same input already raise
        # ({"split": []} and {"split": [""]} -> EingabeFormFehler). Two
        # shapes of the same intent, two answers.
        return np.arange(doc_count, dtype=np.uint32)
    mask = meta.mask_for_expr(expr)
    return np.nonzero(mask)[0].astype(np.uint32, copy=False)


# Ein ausdruecklicher Wert fuer "alle Treffer, kein Deckel". ``limit=None``
# leistet das NICHT: search_cql_matches_backend uebersetzt None zu
# max_matches=20000 (cql_engine.py:258/:289), waehrend die Zaehlroutine
# count_cql_matches_backend fuer None 2_000_000_000 setzt (:321). Die beiden
# Bedeutungen von None stehen dreissig Zeilen auseinander in derselben Datei.
# Wer scannt statt zaehlt, muss den Deckel deshalb selbst aufheben.
SCAN_ALLE_TREFFER = 2_000_000_000

# Sicherheitsgrenze fuer den ungedeckelten Docset-Scan, mit SIGNAL statt
# stiller Kappung. Der Punkt heisst "stille Kappungen sichtbar machen", nicht
# "unbegrenzt scannen": ein Deckel darf sein, er darf nur nicht schweigen.
#
# Selbst gemessen am 142M-Korpus (250.535 Dokumente):
#   cql:[]              142.044.149 Positionen, 233,6 s, 16,33 GB RSS
#   cql:[word="der"]      2.988.554 Positionen,   3,4 s,  2,86 GB RSS
#   cql:[word="Zeit"]        80.572 Positionen,   0,1 s
# Ein ungedeckelter Vollscan der degenerierten Abfrage ist also eine echte
# Speichergefahr, waehrend die haeufigste Wortform des Korpus 47-fache Luft
# unter der Grenze hat. Vorgezaehlt wird ueber count_cql_matches_backend,
# und das ist fast gratis: 0,06 s fuer [word="der"] gegen 3,4 s fuers
# Materialisieren. Nur die degenerierte Abfrage zahlt die 45 s des Zaehlens,
# und sie zahlt sie STATT 233 s und 16 GB.
DOCSET_SCAN_POSITIONEN_MAX = 20_000_000


def _positions_from_query(
    idx: CorpusIndex,
    query: str,
    *,
    limit: int | None = None,
    ungedeckelt: bool = False,
) -> np.ndarray:
    """Positionen einer Abfrage.

    ``ungedeckelt=True`` heisst: KEIN Deckel, und zwar in dem Idiom, das
    der jeweilige Zweig versteht. Das ist nicht dasselbe wie ein sehr
    grosses ``limit``, und der Unterschied hat einen Waechter gekostet:

    * Der CQL-Zweig braucht eine grosse Zahl, weil ``limit=None`` dort
      ``max_matches=20000`` bedeutet (cql_engine).
    * Der Klartext-Zweig braucht ``limit=None``, weil
      ``_complement_positions`` seinen lauten NOT-Waechter
      (``_NOT_MAX_TOKENS``, 50 Mio.) NUR im Zweig ``limit is None``
      prueft. Eine grosse Zahl schaltet ihn STILL AB und materialisiert
      das volle Komplement.

    Die Vorfassung reichte ueberall ``SCAN_ALLE_TREFFER`` durch und hat
    damit genau diesen Waechter abgeschaltet, waehrend sie einen anderen
    Deckel aufhob.
    """
    query = (query or "").strip()
    if not query:
        return np.zeros(0, dtype=np.uint32)
    co_query = _parse_co_kwic_query(query)
    if co_query:
        positions = _co_occurrence_positions(
            idx,
            term=co_query["term"],
            collocates=co_query["collocates"],
            window=co_query["window"],
            within_sentence=co_query["within_sentence"],
            docset_mask=None,
            attribute=co_query.get("attribute", "word"),
        )
        if limit is not None and not ungedeckelt:
            try:
                lim = int(limit)
                if lim > 0:
                    positions = positions[:lim]
            except Exception:
                pass
        return positions.astype(np.uint32, copy=False)
    from candyconc.core.cql_macros import normalize_query_input

    raw = normalize_query_input(query)
    if raw.lower().startswith("cql:"):
        q = raw[4:].strip()
        if not q:
            return np.zeros(0, dtype=np.uint32)
        from candyconc.core.cql_engine import search_cql_matches_backend

        matches = search_cql_matches_backend(
            idx.fast_index, q,
            limit=SCAN_ALLE_TREFFER if ungedeckelt else limit,
            within_sentences_by_default=True,
        )
        return np.array([m.start for m in matches], dtype=np.uint32)
    node = parse_query(raw)
    # limit=None erhaelt den NOT-Waechter (_NOT_MAX_TOKENS) und ist hier
    # zugleich die ungedeckelte Auswertung.
    return _eval_query(
        node, idx, limit=None if ungedeckelt else limit, allow_limit=True
    )


def _doc_ids_from_positions(idx: CorpusIndex, positions: np.ndarray) -> np.ndarray:
    if positions.size == 0:
        return np.zeros(0, dtype=np.uint32)
    doc_bounds = (
        idx.fast_index.boundaries.document._positions
        if idx.fast_index.boundaries and idx.fast_index.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    if doc_bounds.size == 0:
        raise RuntimeError(
            lt("Dokumentgrenzen fehlen. Bitte Index neu bauen.", "Document boundaries are missing. Rebuild the index.")
        )
    return unique_doc_ids_from_positions_fast(positions, doc_bounds)


def _filter_positions_by_docset(
    idx: CorpusIndex,
    positions: np.ndarray,
    docset_mask: np.ndarray,
) -> np.ndarray:
    if positions.size == 0:
        return positions
    doc_bounds = _doc_bounds_for_index(idx)
    if docset_mask.size < doc_bounds.size:
        raise RuntimeError(
            lt(
                "Docset Maske passt nicht zu Dokumentanzahl.",
                "Document set mask does not match the number of documents.",
            )
        )
    return filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)


def _metadata_filter_docset_mask(
    idx: CorpusIndex,
    *,
    date: str | None = None,
    genre: str | None = None,
) -> np.ndarray | None:
    """Build a document mask for legacy date/genre filters.

    Date/genre are document metadata filters, not token literals. Routing them
    through a docset mask lets CQL and legacy queries share one exact filtering
    path instead of degrading complex queries to ``word == query_string``.
    """

    # Checked STRIPPED, as the cache key does (query_count._query_count_key
    # strips date and genre). A whitespace genre is truthy: checking the RAW
    # value would give the call the key of the UNFILTERED result together
    # with a mask that matches no document. On a small test index, term=und:
    #     unfiltered first, then genre="   "  -> 919 (byte-identical)
    #     genre="   " first, then unfiltered  -> 0 of 919
    # The second case poisons the process-wide count cache, and
    # /query/stream would deliver 50 KWIC rows together with count 0.
    # test_meta_filters_golden.test_anchor5 pinnt denselben Vertrag fuer
    # den Dikt-Eingang: Leerraum heisst "dieses Feld ist nicht gefiltert".
    if not (str(date or "").strip() or str(genre or "").strip()):
        return None
    fast_index = getattr(idx, "fast_index", None)
    fallback = str(getattr(fast_index, "index_path", getattr(idx, "path", "")) or "")
    cache_key = (
        id(idx),
        _corpus_cache_signature(fast_index, fallback),
        str(date) if date is not None else "",
        str(genre) if genre is not None else "",
    )
    cached = _metadata_filter_mask_cache_get(cache_key)
    if cached is not None:
        return cached

    date_range: tuple[calendar_date | None, calendar_date | None] | None = None
    date_value = str(date).strip() if date is not None else None
    if date_value and ".." in date_value:
        start_text, end_text = (part.strip() for part in date_value.split("..", 1))
        try:
            start = calendar_date.fromisoformat(start_text) if start_text else None
            end = calendar_date.fromisoformat(end_text) if end_text else None
        except ValueError as exc:
            raise ValueError(
                lt(
                    "Ungültiger Datumsbereich. Bitte YYYY-MM-DD oder YYYY-MM-DD..YYYY-MM-DD verwenden.",
                    "Invalid date range. Use YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD.",
                )
            ) from exc
        if start is None and end is None:
            raise ValueError(
                lt(
                    "Ungültiger Datumsbereich. Mindestens eine Grenze ist erforderlich.",
                    "Invalid date range. At least one bound is required.",
                )
            )
        if start is not None and end is not None and start > end:
            raise ValueError(
                lt(
                    "Ungültiger Datumsbereich: Beginn liegt nach dem Ende.",
                    "Invalid date range: the start is after the end.",
                )
            )
        date_range = (start, end)

    def _metadata_date_interval(value: object) -> tuple[calendar_date, calendar_date] | None:
        """Return the full interval represented by ISO day/month/year metadata."""
        raw = str(value or "").strip()
        try:
            if re.fullmatch(r"\d{4}", raw):
                year = int(raw)
                return calendar_date(year, 1, 1), calendar_date(year, 12, 31)
            if re.fullmatch(r"\d{4}-\d{2}", raw):
                year, month = (int(part) for part in raw.split("-"))
                start = calendar_date(year, month, 1)
                if month == 12:
                    end = calendar_date(year, 12, 31)
                else:
                    end = calendar_date(year, month + 1, 1) - timedelta(days=1)
                return start, end
            parsed = calendar_date.fromisoformat(raw[:10])
        except ValueError:
            return None
        return parsed, parsed

    doc_bounds = _doc_bounds_for_index(idx)
    doc_count = int(doc_bounds.size)
    mask = np.zeros(doc_count, dtype=np.bool_)
    # Gestrippt, wie der Cache-Schluessel. Ungestrippt verglich ein
    # Genre mit Randleerraum gegen den bereits gestrippten Metadatenwert
    # und traf nie.
    _genre_roh = str(genre).strip() if genre is not None else None
    genre_value = _genre_roh or None
    for doc_id in range(doc_count):
        _label, meta = _shared_doc_meta_for_doc_id(idx, doc_id)
        if date_range is not None:
            value_interval = _metadata_date_interval(meta.get("date", ""))
            if value_interval is None:
                continue
            value_start, value_end = value_interval
            range_start, range_end = date_range
            if (range_start is not None and value_end < range_start) or (
                range_end is not None and value_start > range_end
            ):
                continue
        elif date_value is not None and str(meta.get("date", "")) != date_value:
            continue
        if genre_value is not None and str(meta.get("genre", "")) != genre_value:
            continue
        mask[doc_id] = True
    return _metadata_filter_mask_cache_set(cache_key, mask)


def _word_sketch_counts_safe(
    positions: np.ndarray,
    head_ids: np.ndarray,
    rel_ids: np.ndarray,
    word_stream: Any,
    token_count: int,
) -> tuple[dict[int, dict[int, int]], dict[int, dict[int, int]]]:
    """Memory-safe word sketch counts without allocating a full token mask."""
    from candyconc.core.fast_index_native import decode_svb_block

    dep_counts: dict[int, dict[int, int]] = {}
    head_counts: dict[int, dict[int, int]] = {}

    if positions.size == 0 or token_count <= 0:
        return dep_counts, head_counts

    pos_sorted = np.asarray(positions, dtype=np.uint32)
    if pos_sorted.size > 1:
        pos_sorted = np.unique(pos_sorted)

    offsets = word_stream.offsets
    data = word_stream.data
    block_size = int(word_stream.block_size)

    # term as dependent -> count heads
    cached_block_idx: int | None = None
    cached_block: np.ndarray | None = None
    for pos in pos_sorted:
        if pos >= token_count:
            continue
        head = head_ids[int(pos)]
        if head < 0 or head >= token_count:
            continue
        rel_id = int(rel_ids[int(pos)])
        block_idx = int(head // block_size)
        if cached_block_idx != block_idx or cached_block is None:
            cached_block = decode_svb_block(offsets, data, block_idx, block_size, int(token_count))
            cached_block_idx = block_idx
        local = int(head - block_idx * block_size)
        if local < 0 or local >= cached_block.shape[0]:
            continue
        word_id = int(cached_block[local])
        if word_id == 0:
            continue
        inner = dep_counts.get(rel_id)
        if inner is None:
            inner = {}
            dep_counts[rel_id] = inner
        inner[word_id] = inner.get(word_id, 0) + 1

    # term as head -> scan heads for dependents
    total = int(token_count)
    if total <= 0:
        return dep_counts, head_counts
    n_blocks = (total + block_size - 1) // block_size
    for block_idx in range(n_blocks):
        block_start = block_idx * block_size
        block_ids = decode_svb_block(offsets, data, block_idx, block_size, int(token_count))
        if block_ids.size == 0:
            continue
        block_len = int(block_ids.size)
        end = block_start + block_len
        head_block = head_ids[block_start:end]
        rel_block = rel_ids[block_start:end]
        valid_mask = (head_block >= 0) & (head_block < total)
        if not np.any(valid_mask):
            continue
        valid_idx = np.nonzero(valid_mask)[0]
        head_valid = head_block[valid_idx].astype(np.uint32, copy=False)
        idx = np.searchsorted(pos_sorted, head_valid)
        hit_mask = (idx < pos_sorted.size) & (pos_sorted[idx] == head_valid)
        if not np.any(hit_mask):
            continue
        hit_idx = valid_idx[hit_mask]
        for i in hit_idx:
            word_id = int(block_ids[int(i)])
            if word_id == 0:
                continue
            rel_id = int(rel_block[int(i)])
            inner = head_counts.get(rel_id)
            if inner is None:
                inner = {}
                head_counts[rel_id] = inner
            inner[word_id] = inner.get(word_id, 0) + 1

    return dep_counts, head_counts


def _word_sketch_cql_anchor_positions(matches: Sequence[Any]) -> np.ndarray:
    """Return one dependency anchor per non-empty CQL match, using match.start."""
    anchors: list[int] = []
    for match in matches:
        start = int(getattr(match, "start", -1))
        end = int(getattr(match, "end", start + 1))
        if start < 0 or end <= start:
            continue
        anchors.append(start)
    if not anchors:
        return np.zeros(0, dtype=np.uint32)
    return np.unique(np.asarray(anchors, dtype=np.uint32))


def _word_sketch_docset_frequency_map(
    idx: CorpusIndex,
    docset_ids: Sequence[int] | np.ndarray,
) -> dict[int, int]:
    """Exact docset-local f2 frequencies for WordSketch association scores."""
    ids = np.asarray(docset_ids, dtype=np.uint32)
    if ids.size == 0:
        return {}
    # TODO(native-csr): replace this full docset frequency pass with sparse
    # f2 lookups from a native dependency/word CSR once that index exists.
    term_ids, counts = idx.frequency_counts_docset(ids, stopwords=None, pos_prefix=None)
    return {int(term_id): int(count) for term_id, count in zip(term_ids, counts)}


def _word_sketch_node_id(word_lex: Any, raw_term: str) -> int:
    """Lexicon id of a plain word sketch node: the exact form, else lower case."""
    return int(word_lex.get_id(raw_term) or word_lex.get_id(raw_term.lower()) or 0)


def _word_sketch_node_form(idx: CorpusIndex, term: str) -> str | None:
    """The word form a plain-term word sketch counts, None for a CQL node.

    A client builds the concordance query behind a sketch row from it, so it
    needs the form the sketch resolved, not the form that was typed.
    """
    from candyconc.core.cql_macros import normalize_query_input

    raw_term = (term or "").strip()
    co_query = _parse_co_kwic_query(raw_term)
    if co_query:
        raw_term = co_query["term"]
    if not raw_term or normalize_query_input(raw_term).lower().startswith("cql:"):
        return None
    try:
        word_lex = idx.fast_index.lexicons.word
        term_id = _word_sketch_node_id(word_lex, raw_term)
        return str(word_lex.get_string(term_id)) if term_id > 0 else None
    except (AttributeError, TypeError):
        return None


def _word_sketch_for_query(
    idx: CorpusIndex,
    term: str,
    *,
    docset_mask: np.ndarray | None = None,
    docset_ids: np.ndarray | None = None,
    relation_limit: int | None = None,
) -> Dict[str, Any]:
    """Compute word sketch for term or CQL query, optionally restricted to docset."""
    from candyconc.core.fast_index_native import word_sketch_counts
    import pandas as pd

    raw_term = (term or "").strip()
    if not raw_term:
        return {}
    docset_ids_arr = np.asarray(docset_ids, dtype=np.uint32) if docset_ids is not None else None
    max_positions = int(get_config("CANDYCONC_WORD_SKETCH_MAX_POSITIONS", "5000000"))
    co_query = _parse_co_kwic_query(raw_term)
    if co_query:
        raw_term = co_query["term"]

    from candyconc.core.cql_macros import normalize_query_input

    normalized = normalize_query_input(raw_term)

    fast = idx.fast_index
    store = fast.token_store
    lex = fast.lexicons
    rel_lex = lex.rel if lex else None
    word_lex = lex.word if lex else None
    if word_lex is None:
        raise RuntimeError(
            lt("Wortlexikon fehlt. Bitte Index neu bauen.", "Word lexicon is missing. Rebuild the index.")
        )

    is_cql = normalized.lower().startswith("cql:")
    term_id = 0
    positions: np.ndarray
    if is_cql:
        q = normalized[4:].strip()
        if not q:
            return {}
        from candyconc.core.cql_engine import search_cql_matches_backend

        limit = max_positions + 1 if max_positions > 0 else 2_000_000_000
        matches = search_cql_matches_backend(
            fast,
            q,
            limit=limit,
            within_sentences_by_default=True,
        )
        if not matches:
            return {}
        if max_positions > 0 and len(matches) > max_positions:
            raise RuntimeError(
                _WORD_SKETCH_TOO_MANY_HITS.format(hits=len(matches), max_positions=max_positions)
            )
        # CQL WordSketch is token-anchored: every match contributes its start
        # token exactly once. Multi-token CQL spans are not expanded.
        positions = _word_sketch_cql_anchor_positions(matches)
    else:
        term_id = _word_sketch_node_id(word_lex, raw_term)
        if term_id <= 0:
            return {}
        positions = store.get_positions_for_word_id(term_id)
    if positions.size == 0:
        return {}
    if docset_ids_arr is not None and docset_ids_arr.size == 0:
        return {}
    if docset_ids_arr is not None and docset_mask is None:
        raise RuntimeError(
            "Word Sketch docset analysis requires docset_mask for exact docset-local counts."
        )
    if docset_mask is not None:
        positions = _filter_positions_by_docset(idx, positions, docset_mask)
    if positions.size == 0:
        return {}
    if docset_mask is not None and docset_ids_arr is None:
        raise RuntimeError(
            "Word Sketch docset analysis requires doc_ids for exact docset-local f2."
        )

    head_ids = store.head_ids
    rel_ids = store.rel_ids
    word_stream = store.word_stream
    if word_stream is None:
        raise RuntimeError(
            lt("Word Stream fehlt. Bitte Index neu bauen.", "Word stream is missing. Rebuild the index.")
        )
    token_count = int(store.token_count)
    if max_positions > 0 and int(positions.size) > max_positions:
        raise RuntimeError(
            _WORD_SKETCH_TOO_MANY_HITS.format(hits=int(positions.size), max_positions=max_positions)
        )

    def _ensure_writeable(arr: np.ndarray, dtype: np.dtype) -> np.ndarray:
        out = np.asarray(arr, dtype=dtype)
        base = out.base
        if (
            not out.flags.writeable
            or (base is not None and isinstance(base, np.memmap) and getattr(base, "mode", "r") == "r")
        ):
            out = np.array(out, copy=True)
        return out

    mask_limit = int(get_config("CANDYCONC_WORD_SKETCH_MASK_MAX_TOKENS", "10000000"))
    if token_count > 0 and token_count <= mask_limit:
        dep_counts, head_counts = word_sketch_counts(
            _ensure_writeable(positions, np.uint32),
            _ensure_writeable(head_ids, np.int64),
            _ensure_writeable(rel_ids, np.uint32),
            word_stream.offsets,
            word_stream.data,
            int(word_stream.block_size),
            token_count,
        )
    else:
        dep_counts, head_counts = _word_sketch_counts_safe(
            positions,
            head_ids,
            rel_ids,
            word_stream,
            token_count,
        )

    docset_freqs: dict[int, int] | None = None
    if docset_ids_arr is not None and docset_ids_arr.size > 0:
        term_count = int(positions.size)
        total = int(idx.docset_token_count(docset_ids_arr))
        docset_freqs = _word_sketch_docset_frequency_map(idx, docset_ids_arr)
        f2_basis = "docset_local"
    else:
        term_count = int(positions.size) if is_cql else word_lex.get_freq(term_id)
        total = int(word_lex.total_tokens)
        f2_basis = "global"

    coll_counts: dict[str, Counter[int]] = {}

    for rel_id, counter in dep_counts.items():
        rel_name = rel_lex.get_string(int(rel_id)) if rel_lex else str(rel_id)
        label = f"{rel_name}_rev"
        coll_counts[label] = Counter({int(k): int(v) for k, v in counter.items()})

    for rel_id, counter in head_counts.items():
        rel_name = rel_lex.get_string(int(rel_id)) if rel_lex else str(rel_id)
        coll_counts[rel_name] = Counter({int(k): int(v) for k, v in counter.items()})

    results: dict[str, Any] = {}
    for label, counter in coll_counts.items():
        rows = []
        for word_id, obs in counter.items():
            f2 = (
                int(docset_freqs.get(int(word_id), 0))
                if docset_freqs is not None
                else int(word_lex.get_freq(word_id))
            )
            if docset_freqs is not None and f2 <= 0:
                raise RuntimeError(
                    lt(
                        "Word Sketch docset-local f2 missing for observed collocate "
                        "word_id={word_id}. Bitte Index/Docset prüfen.",
                        "Word Sketch docset-local f2 missing for observed collocate "
                        "word_id={word_id}. Check the index and the document set.",
                    ).format(word_id=int(word_id))
                )
            word = word_lex.get_string(word_id)
            exp = term_count * f2 / total if total else 0
            chi2_cell = ((obs - exp) ** 2) / exp if exp else 0.0
            t = (obs - exp) / math.sqrt(obs) if obs else 0.0
            # Full 2x2 Dunning G^2 (not the single-cell 2*O*ln(O/E), which goes
            # negative and is not chi-square distributed). Cells from the
            # marginals term_count (node) x f2 (collocate) over N=total; each
            # term contributes 0 when its observed cell is <= 0.
            ll = _g2_2x2(obs, term_count, f2, total)
            ll_signed = ll if obs >= exp else -ll
            # logDice (Rychlý 2008): the Dice coefficient on a log2 scale, shifted
            # by 14. Unlike chi2_cell/ll it does NOT depend on the corpus size N — it
            # uses only the joint count and the two marginals (node f1=term_count,
            # collocate f2) — so it is comparable across corpora and not inflated
            # by hapaxes. It is the default ranking for word sketches, matching
            # the collocations default and Sketch Engine practice. Computed from
            # the SAME marginals as chi2_cell/ll here, so the measures stay consistent.
            dice = (2.0 * obs / (term_count + f2)) if (term_count + f2) > 0 else 0.0
            logdice = 14.0 + math.log2(dice) if dice > 0 else 0.0
            rows.append(
                {
                    "word": word,
                    "f": int(obs),
                    "f2": int(f2),
                    "f2_basis": f2_basis,
                    "chi2_cell": chi2_cell,
                    "t": t,
                    "ll": ll,
                    "ll_signed": ll_signed,
                    "dice": dice,
                    "logdice": logdice,
                }
            )
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        # Default ranking: logDice (frequency-robust, corpus-size-comparable),
        # consistent with the collocations default; the route re-ranks survivors
        # by the same key after the min-frequency floor.
        df = df.sort_values("logdice", ascending=False).reset_index(drop=True)
        df.index += 1
        df["rank"] = df.index
        results[label] = df

    try:
        top_rows = int(relation_limit) if relation_limit is not None else 8
    except (TypeError, ValueError):
        top_rows = 8
    # Internal REST callers use relation_limit=0 to keep all normalized rows so
    # the public route can report honest per-relation completeness before it
    # displays only the requested page.
    top_rows = max(0, top_rows)
    return normalize_word_sketch_tables(results, raw_term, top_rows=top_rows)


def _doc_id_for_position(idx: CorpusIndex, pos: int, doc_bounds: np.ndarray | None = None) -> int:
    bounds = doc_bounds if doc_bounds is not None else _doc_bounds_for_index(idx)
    if pos < 0:
        raise ApiError(400, "position.negative", lt("pos muss >= 0 sein", "pos must be >= 0"))
    token_count = int(idx.fast_index.token_store.token_count)
    if pos >= token_count:
        raise ApiError(400, "position.out_of_corpus", lt("pos ausserhalb des Korpus", "pos is outside the corpus"))
    doc_id = position_to_doc_id_fast(pos, bounds)
    if doc_id < 0 or doc_id >= int(bounds.size):
        raise ApiError(
            400,
            "position.no_document",
            lt("pos konnte keinem Dokument zugeordnet werden", "pos could not be assigned to a document"),
        )
    return doc_id


def _docset_local_offsets(
    offsets: np.ndarray,
    doc_bounds: np.ndarray,
    doc_ids: Any,
    *,
    token_count: int,
) -> np.ndarray:
    """Map global token offsets into the concatenated coordinate space of doc_ids."""
    offsets_i64 = np.atleast_1d(np.asarray(offsets, dtype=np.int64))
    if offsets_i64.size == 0:
        return offsets_i64
    bounds = np.asarray(doc_bounds, dtype=np.int64)
    ids = _docset_local_doc_ids(doc_ids, bounds)
    if bounds.size == 0 or ids.size == 0:
        return np.zeros(0, dtype=np.int64)
    safe_token_count = max(0, int(token_count))
    pieces: list[np.ndarray] = []
    cursor = 0
    for raw_doc_id in ids.tolist():
        start = int(bounds[raw_doc_id])
        end = int(bounds[raw_doc_id + 1]) if raw_doc_id + 1 < int(bounds.size) else safe_token_count
        if end <= start:
            continue
        mask = (offsets_i64 >= start) & (offsets_i64 < end)
        if np.any(mask):
            pieces.append((offsets_i64[mask] - start + cursor).astype(np.int64, copy=False))
        cursor += end - start
    if not pieces:
        return np.zeros(0, dtype=np.int64)
    return np.concatenate(pieces).astype(np.int64, copy=False)


def _docset_local_doc_ids(doc_ids: Any, doc_bounds: np.ndarray) -> np.ndarray:
    """Return valid doc ids in the canonical sorted/unique docset-local order."""
    bounds = np.asarray(doc_bounds)
    if bounds.size == 0 or doc_ids is None:
        return np.zeros(0, dtype=np.uint32)
    ids = np.atleast_1d(np.asarray(doc_ids, dtype=np.int64))
    if ids.size == 0:
        return np.zeros(0, dtype=np.uint32)
    ids = ids[(ids >= 0) & (ids < int(bounds.size))]
    if ids.size == 0:
        return np.zeros(0, dtype=np.uint32)
    return np.unique(ids).astype(np.uint32, copy=False)


def _json_dumps_fast(payload: Any) -> str:
    if _orjson is not None:
        return _orjson.dumps(payload).decode("utf-8")
    return json.dumps(payload)


def _enrich_compact_tuple_rows_with_doc_meta(
    idx: CorpusIndex,
    rows: list[tuple[Any, ...]],
    *,
    fixed_match_offsets: list[int] | None = None,
    match_lengths: np.ndarray | None = None,
    two_token_pivot_one: bool = False,
    row_has_offsets: bool | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    doc_metadata = idx.fast_index.doc_metadata
    query_cache = getattr(doc_metadata, "_query_cache", None)
    if isinstance(query_cache, list) and getattr(doc_metadata, "_query_cache_complete", False):
        prepared_cache_list, prepared_cache_dict = query_cache, None
    else:
        unique_doc_ids: list[int] = []
        last_unique_doc_id = -1
        have_last_unique_doc_id = False
        for row in rows:
            doc_id = int(row[4])
            if not have_last_unique_doc_id or doc_id != last_unique_doc_id:
                unique_doc_ids.append(doc_id)
                last_unique_doc_id = doc_id
                have_last_unique_doc_id = True
        prepared_cache_list, prepared_cache_dict = _resolve_query_meta_lookup(
            idx,
            unique_doc_ids,
            already_unique=True,
        )
    enriched_rows: list[dict[str, Any]] = [None] * len(rows)  # type: ignore[list-item]
    last_doc_id = -1
    last_prepared = ("", {})
    offsets_cache: dict[int, list[int]] = {}
    if row_has_offsets is None:
        rows_all_have_offsets = len(rows[0]) > 5 and all(len(row) > 5 for row in rows[1:])
        rows_all_no_offsets = len(rows[0]) <= 5 and all(len(row) <= 5 for row in rows[1:])
    else:
        rows_all_have_offsets = bool(row_has_offsets)
        rows_all_no_offsets = not rows_all_have_offsets
    if two_token_pivot_one:
        shared_offsets = [-1]
        if prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                pos = pos + 1
                if right:
                    split_at = right.find(" ")
                    if split_at < 0:
                        next_kw = right
                        right = ""
                    else:
                        next_kw = right[:split_at]
                        right = right[split_at + 1 :]
                    if kw:
                        left = f"{left} {kw}" if left else kw
                    kw = next_kw
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": shared_offsets,
                }
        else:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                pos = pos + 1
                if right:
                    split_at = right.find(" ")
                    if split_at < 0:
                        next_kw = right
                        right = ""
                    else:
                        next_kw = right[:split_at]
                        right = right[split_at + 1 :]
                    if kw:
                        left = f"{left} {kw}" if left else kw
                    kw = next_kw
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": shared_offsets,
                }
        return enriched_rows

    if fixed_match_offsets is None and match_lengths is None:
        if rows_all_no_offsets:
            if prepared_cache_list is not None:
                for row_idx, row in enumerate(rows):
                    left = row[0]
                    kw = row[1]
                    right = row[2]
                    pos = row[3]
                    doc_id = row[4]
                    if doc_id != last_doc_id:
                        last_prepared = prepared_cache_list[doc_id]
                        last_doc_id = doc_id
                    doc_label, meta = last_prepared
                    enriched_rows[row_idx] = {
                        "left": left,
                        "kw": kw,
                        "right": right,
                        "pos": pos,
                        "doc_id": doc_id,
                        "doc": doc_label,
                        "meta": meta,
                    }
            else:
                assert prepared_cache_dict is not None
                for row_idx, row in enumerate(rows):
                    left = row[0]
                    kw = row[1]
                    right = row[2]
                    pos = row[3]
                    doc_id = row[4]
                    if doc_id != last_doc_id:
                        last_prepared = prepared_cache_dict[doc_id]
                        last_doc_id = doc_id
                    doc_label, meta = last_prepared
                    enriched_rows[row_idx] = {
                        "left": left,
                        "kw": kw,
                        "right": right,
                        "pos": pos,
                        "doc_id": doc_id,
                        "doc": doc_label,
                        "meta": meta,
                    }
        elif rows_all_have_offsets and prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": row[5],
                }
        elif rows_all_have_offsets:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": row[5],
                }
        elif prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                }
                if len(row) > 5:
                    enriched["match_offsets"] = row[5]
                enriched_rows[row_idx] = enriched
        else:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                }
                if len(row) > 5:
                    enriched["match_offsets"] = row[5]
                enriched_rows[row_idx] = enriched
        return enriched_rows

    if fixed_match_offsets is not None and match_lengths is None:
        if rows_all_no_offsets:
            if prepared_cache_list is not None:
                for row_idx, row in enumerate(rows):
                    left = row[0]
                    kw = row[1]
                    right = row[2]
                    pos = row[3]
                    doc_id = row[4]
                    if doc_id != last_doc_id:
                        last_prepared = prepared_cache_list[doc_id]
                        last_doc_id = doc_id
                    doc_label, meta = last_prepared
                    enriched_rows[row_idx] = {
                        "left": left,
                        "kw": kw,
                        "right": right,
                        "pos": pos,
                        "doc_id": doc_id,
                        "doc": doc_label,
                        "meta": meta,
                        "match_offsets": fixed_match_offsets,
                    }
            else:
                assert prepared_cache_dict is not None
                for row_idx, row in enumerate(rows):
                    left = row[0]
                    kw = row[1]
                    right = row[2]
                    pos = row[3]
                    doc_id = row[4]
                    if doc_id != last_doc_id:
                        last_prepared = prepared_cache_dict[doc_id]
                        last_doc_id = doc_id
                    doc_label, meta = last_prepared
                    enriched_rows[row_idx] = {
                        "left": left,
                        "kw": kw,
                        "right": right,
                        "pos": pos,
                        "doc_id": doc_id,
                        "doc": doc_label,
                        "meta": meta,
                        "match_offsets": fixed_match_offsets,
                    }
        elif rows_all_have_offsets and prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": row[5],
                }
        elif rows_all_have_offsets:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched_rows[row_idx] = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": row[5],
                }
        elif prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": fixed_match_offsets,
                }
                if len(row) > 5:
                    enriched["match_offsets"] = row[5]
                enriched_rows[row_idx] = enriched
        else:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                    "match_offsets": fixed_match_offsets,
                }
                if len(row) > 5:
                    enriched["match_offsets"] = row[5]
                enriched_rows[row_idx] = enriched
        return enriched_rows

    if match_lengths is not None and fixed_match_offsets is None and rows_all_no_offsets:
        match_len_list = match_lengths.tolist()
        if prepared_cache_list is not None:
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_list[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                }
                match_len_i = int(match_len_list[row_idx])
                if match_len_i > 1:
                    row_offsets = offsets_cache.get(match_len_i)
                    if row_offsets is None:
                        row_offsets = [idx_off for idx_off in range(1, match_len_i)]
                        offsets_cache[match_len_i] = row_offsets
                    enriched["match_offsets"] = row_offsets
                enriched_rows[row_idx] = enriched
        else:
            assert prepared_cache_dict is not None
            for row_idx, row in enumerate(rows):
                left = row[0]
                kw = row[1]
                right = row[2]
                pos = row[3]
                doc_id = row[4]
                if doc_id != last_doc_id:
                    last_prepared = prepared_cache_dict[doc_id]
                    last_doc_id = doc_id
                doc_label, meta = last_prepared
                enriched = {
                    "left": left,
                    "kw": kw,
                    "right": right,
                    "pos": pos,
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                }
                match_len_i = int(match_len_list[row_idx])
                if match_len_i > 1:
                    row_offsets = offsets_cache.get(match_len_i)
                    if row_offsets is None:
                        row_offsets = [idx_off for idx_off in range(1, match_len_i)]
                        offsets_cache[match_len_i] = row_offsets
                    enriched["match_offsets"] = row_offsets
                enriched_rows[row_idx] = enriched
        return enriched_rows

    match_len_list = match_lengths.tolist() if match_lengths is not None else None

    for row_idx, row in enumerate(rows):
        doc_id = row[4]
        if doc_id != last_doc_id:
            if prepared_cache_list is not None:
                last_prepared = prepared_cache_list[doc_id]
            else:
                assert prepared_cache_dict is not None
                last_prepared = prepared_cache_dict[doc_id]
            last_doc_id = doc_id
        doc_label, meta = last_prepared
        enriched: dict[str, Any] = {
            "left": row[0],
            "kw": row[1],
            "right": row[2],
            "pos": row[3],
            "doc_id": doc_id,
            "doc": doc_label,
            "meta": meta,
        }
        if len(row) > 5:
            enriched["match_offsets"] = row[5]
        elif fixed_match_offsets is not None:
            enriched["match_offsets"] = fixed_match_offsets
        elif match_len_list is not None:
            match_len_i = int(match_len_list[row_idx])
            if match_len_i > 1:
                row_offsets = offsets_cache.get(match_len_i)
                if row_offsets is None:
                    row_offsets = [idx_off for idx_off in range(1, match_len_i)]
                    offsets_cache[match_len_i] = row_offsets
                enriched["match_offsets"] = row_offsets
        enriched_rows[row_idx] = enriched
    return enriched_rows


def _materialize_compact_buffer_rows_with_doc_meta(
    idx: CorpusIndex,
    buffers: dict[str, Any],
    *,
    prepared_cache: dict[int, tuple[str, dict[str, str]]] | None = None,
    fixed_match_offsets: list[int] | None = None,
    match_lengths: np.ndarray | None = None,
    two_token_pivot_one: bool = False,
) -> list[dict[str, Any]]:
    merged_texts = buffers.get("merged_texts") or []
    positions = np.asarray(buffers.get("positions"), dtype=np.uint32)
    if positions.size == 0:
        return []
    row_merged_idx = np.asarray(buffers.get("row_merged_idx"), dtype=np.int32)
    left_lo = np.asarray(buffers.get("left_lo"), dtype=np.int32)
    left_hi = np.asarray(buffers.get("left_hi"), dtype=np.int32)
    kw_lo = np.asarray(buffers.get("kw_lo"), dtype=np.int32)
    kw_hi = np.asarray(buffers.get("kw_hi"), dtype=np.int32)
    right_lo = np.asarray(buffers.get("right_lo"), dtype=np.int32)
    right_hi = np.asarray(buffers.get("right_hi"), dtype=np.int32)
    doc_ids = np.asarray(buffers.get("doc_ids"), dtype=np.int32)
    doc_id_list = doc_ids.tolist()
    doc_metadata = idx.fast_index.doc_metadata
    query_cache = getattr(doc_metadata, "_query_cache", None)
    prepared_cache_list = None
    if prepared_cache is None and isinstance(query_cache, list) and getattr(doc_metadata, "_query_cache_complete", False):
        prepared_cache_list = query_cache
        prepared_cache_dict = None
    else:
        if prepared_cache is None:
            prepared_cache = {}
        unique_doc_ids: list[int] = []
        last_unique_doc_id = -1
        have_last_unique_doc_id = False
        for doc_id in doc_id_list:
            if not have_last_unique_doc_id or doc_id != last_unique_doc_id:
                unique_doc_ids.append(doc_id)
                last_unique_doc_id = doc_id
                have_last_unique_doc_id = True
        prepared_cache_dict = prepared_cache
        if not prepared_cache:
            prepared_cache_list, resolved_cache_dict = _resolve_query_meta_lookup(
                idx,
                unique_doc_ids,
                already_unique=True,
            )
            if resolved_cache_dict is not None:
                prepared_cache_dict = resolved_cache_dict
        elif doc_id_list:
            missing_doc_ids = [doc_id for doc_id in unique_doc_ids if doc_id not in prepared_cache]
            if missing_doc_ids:
                query_many = getattr(idx.fast_index.doc_metadata, "query_entries_many", None)
                prepared_many = getattr(idx.fast_index.doc_metadata, "prepared_entries_many", None)
                if callable(query_many):
                    resolved_missing = query_many(missing_doc_ids)
                elif callable(prepared_many):
                    resolved_missing = prepared_many(missing_doc_ids)
                else:
                    resolved_missing = [_shared_doc_meta_for_doc_id(idx, int(doc_id)) for doc_id in missing_doc_ids]
                for doc_id, prepared in zip(missing_doc_ids, resolved_missing):
                    prepared_cache_dict[int(doc_id)] = prepared
    merged_idx_list = row_merged_idx.tolist()
    left_lo_list = left_lo.tolist()
    left_hi_list = left_hi.tolist()
    kw_lo_list = kw_lo.tolist()
    kw_hi_list = kw_hi.tolist()
    right_lo_list = right_lo.tolist()
    right_hi_list = right_hi.tolist()
    pos_list = positions.tolist()
    rows: list[dict[str, Any]] = [None] * int(len(pos_list))  # type: ignore[list-item]
    merged_texts_local = merged_texts
    merged_texts_len = len(merged_texts_local)
    last_doc_id = -1
    last_prepared = ("", {})
    match_len_list = match_lengths.tolist() if match_lengths is not None else None
    offsets_cache: dict[int, list[int]] = {}
    shared_offsets = [-1] if two_token_pivot_one else None
    for row_idx, (
        merged_idx,
        left_start,
        left_end,
        kw_start,
        kw_end,
        right_start,
        right_end,
        pos_value,
        doc_id,
    ) in enumerate(
        zip(
            merged_idx_list,
            left_lo_list,
            left_hi_list,
            kw_lo_list,
            kw_hi_list,
            right_lo_list,
            right_hi_list,
            pos_list,
            doc_id_list,
        )
    ):
        merged_txt = merged_texts_local[merged_idx] if 0 <= merged_idx < merged_texts_len else ""
        left = merged_txt[left_start:left_end] if left_start >= 0 else ""
        kw = merged_txt[kw_start:kw_end] if kw_start >= 0 else ""
        right = merged_txt[right_start:right_end] if right_start >= 0 else ""
        pos_int = int(pos_value)
        if two_token_pivot_one:
            if right:
                split_at = right.find(" ")
                if split_at < 0:
                    next_kw = right
                    right = ""
                else:
                    next_kw = right[:split_at]
                    right = right[split_at + 1 :]
                if kw:
                    left = f"{left} {kw}" if left else kw
                kw = next_kw
            pos_int += 1
        if doc_id != last_doc_id:
            if prepared_cache_list is not None:
                last_prepared = prepared_cache_list[int(doc_id)]
            else:
                last_prepared = prepared_cache_dict[int(doc_id)]
            last_doc_id = int(doc_id)
        doc_label, meta = last_prepared
        rows[row_idx] = {
            "left": left,
            "kw": kw,
            "right": right,
            "pos": pos_int,
            "doc_id": doc_id,
            "doc": doc_label,
            "meta": meta,
        }
        if shared_offsets is not None:
            rows[row_idx]["match_offsets"] = shared_offsets
        elif fixed_match_offsets is not None:
            rows[row_idx]["match_offsets"] = fixed_match_offsets
        elif match_len_list is not None:
            match_len_i = int(match_len_list[row_idx])
            if match_len_i > 1:
                row_offsets = offsets_cache.get(match_len_i)
                if row_offsets is None:
                    row_offsets = [idx_off for idx_off in range(1, match_len_i)]
                    offsets_cache[match_len_i] = row_offsets
                rows[row_idx]["match_offsets"] = row_offsets
    return rows


def _render_fast_rows_for_positions(
    idx: CorpusIndex,
    *,
    positions: np.ndarray,
    ctx: int,
    prepared_cache: dict[int, tuple[str, dict[str, str]]] | None = None,
    fixed_match_offsets: list[int] | None = None,
    match_lengths: np.ndarray | None = None,
    two_token_pivot_one: bool = False,
) -> list[dict[str, Any]]:
    if positions.size == 0:
        return []
    include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
    compact_rows = None
    compact_rows_handle_pivot = False
    compact_rows_fn = getattr(idx.fast_index, "kwic_compact_rows_for_positions", None)
    if not include_arcs and callable(compact_rows_fn):
        if two_token_pivot_one:
            try:
                compact_rows = compact_rows_fn(
                    positions,
                    int(ctx),
                    two_token_pivot_one=True,
                )
                compact_rows_handle_pivot = compact_rows is not None
            except TypeError:
                compact_rows = compact_rows_fn(
                    positions,
                    int(ctx),
                )
        else:
            compact_rows = compact_rows_fn(
                positions,
                int(ctx),
            )
    if compact_rows is not None:
        return _enrich_compact_tuple_rows_with_doc_meta(
            idx,
            compact_rows,
            fixed_match_offsets=fixed_match_offsets,
            match_lengths=match_lengths,
            two_token_pivot_one=(two_token_pivot_one and not compact_rows_handle_pivot),
            row_has_offsets=(len(compact_rows[0]) > 5),
        )

    compact_buffers = None
    compact_buffers_fn = getattr(idx.fast_index, "kwic_compact_buffers_for_positions", None)
    if not include_arcs and callable(compact_buffers_fn):
        compact_buffers = compact_buffers_fn(
            positions,
            int(ctx),
        )
    if compact_buffers is not None:
        return _materialize_compact_buffer_rows_with_doc_meta(
            idx,
            compact_buffers,
            prepared_cache=prepared_cache,
            fixed_match_offsets=fixed_match_offsets,
            match_lengths=match_lengths,
            two_token_pivot_one=two_token_pivot_one,
        )

    rows = idx.fast_index.kwic_rows_for_positions(
        positions,
        int(ctx),
        include_arcs=include_arcs,
        include_file=False,
        compact=True,
    )
    if not rows:
        return []
    if isinstance(rows[0], tuple) and len(rows[0]) > 4:
        return _enrich_compact_tuple_rows_with_doc_meta(
            idx,
            rows,
            fixed_match_offsets=fixed_match_offsets,
            match_lengths=match_lengths,
            row_has_offsets=(len(rows[0]) > 5),
        )
    doc_bounds = _doc_bounds_for_index(idx)
    token_count = int(idx.fast_index.token_store.token_count)
    enriched_rows = list(rows)
    _enrich_rows_with_doc_meta(
        idx,
        enriched_rows,
        doc_bounds=doc_bounds,
        token_count=token_count,
        cache={},
        include_file=False,
    )
    if fixed_match_offsets is not None:
        for row in enriched_rows:
            if isinstance(row, dict) and "match_offsets" not in row:
                row["match_offsets"] = fixed_match_offsets
    return enriched_rows


def _plain_match_offsets(term_text: str) -> list[int] | None:
    """``match_offsets`` for rows of a plain query whose matches span several tokens.

    The plain path renders a row at the first token of each match. A phrase
    ("the American people") marks the tokens after it, like a CQL sequence,
    so the node column can show the whole phrase.
    """
    from candyconc.domain.query_eval import plain_query_match_offsets

    return plain_query_match_offsets(term_text)


def _plain_render_kwargs(term_text: str) -> dict[str, Any]:
    """Keyword arguments for ``_render_fast_rows_for_positions`` of plain rows."""
    offsets = _plain_match_offsets(term_text)
    return {} if offsets is None else {"fixed_match_offsets": offsets}


def _render_fast_rows_for_positions_chunked(
    idx: CorpusIndex,
    *,
    positions: np.ndarray,
    ctx: int,
    chunk_size: int,
    fixed_match_offsets: list[int] | None = None,
) -> list[dict[str, Any]]:
    if positions.size == 0:
        return []
    prepared_cache: dict[int, tuple[str, dict[str, str]]] = {}
    rows: list[dict[str, Any]] = []
    for start in range(0, int(positions.size), int(chunk_size)):
        chunk = positions[start : start + int(chunk_size)]
        chunk_rows = _render_fast_rows_for_positions(
            idx,
            positions=chunk,
            ctx=ctx,
            prepared_cache=prepared_cache,
            fixed_match_offsets=fixed_match_offsets,
        )
        if chunk_rows:
            rows.extend(chunk_rows)
    return rows


# The |LBR| sentinel-drop is defined ONCE in core/query_runtime so the rows
# builders, every count surface, and the copilot query primitive share the same
# filter (a count can never contradict the rows beneath it). These module-level
# aliases keep the existing in-file call-sites readable.
from candyconc.core.query_runtime import (  # noqa: E402
    drop_linebreak_sentinel_positions as _drop_linebreak_sentinel_positions,
    linebreak_sentinel_word_id as _linebreak_sentinel_word_id,
    exact_cql_count_sentinel_dropped as _exact_cql_count_sentinel_dropped,
)


@lru_cache(maxsize=1)
def _term_positions_supports_case_insensitive() -> bool:
    """True if ``CorpusIndex.term_positions`` accepts ``case_insensitive``.

    The case-insensitive lookup is a Track B2 contract on the core index. We
    introspect once so the server keeps working (case-sensitive only) on cores
    that predate the contract instead of crashing on an unexpected kwarg.
    """
    try:
        import inspect

        sig = inspect.signature(CorpusIndex.term_positions)
        return "case_insensitive" in sig.parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic descriptors
        return False


def _plain_term_positions_cs(idx: CorpusIndex, term: str) -> np.ndarray:
    """Case-SENSITIVE positions for a simple single token via the B2 contract.

    The default plain path already resolves case-INSENSITIVELY (query_eval calls
    ``term_positions`` whose Track-B2 default is ``case_insensitive=True``), so a
    server-side override is only needed when the caller explicitly asks for a
    case-sensitive search.
    """
    return np.asarray(
        idx.term_positions(term, case_insensitive=False), dtype=np.uint32
    )


def _prepare_plain_rows_fast(
    idx: CorpusIndex,
    term: str,
    *,
    offset: int = 0,
    limit: int | None = None,
    docset_mask: np.ndarray | None = None,
    case_insensitive: bool = True,
) -> tuple[str, np.ndarray, int, bool] | None:
    from candyconc.core.cql_macros import normalize_query_input
    from candyconc.domain.query_eval import prefetch_positions_window
    from candyconc.utils.text_normalize import normalize_text_basic

    term_str = normalize_query_input(normalize_text_basic(term or ""))
    if not term_str or term_str.lower().startswith("cql:"):
        return None

    # Case-SENSITIVE single-token override: the default (case_insensitive=True)
    # path already folds case via the core term_positions default, so we only
    # divert when the caller explicitly opted OUT. Only a simple single token is
    # eligible — phrases/boolean/regex keep the parser path. This leaves the
    # default behavior byte-identical to before (no routing change for the common
    # case), which is why existing plain-path tests are unaffected.
    if (
        not case_insensitive
        and _term_positions_supports_case_insensitive()
        and _is_simple_single_token(term_str)
    ):
        positions = _plain_term_positions_cs(idx, term_str)
        if positions.size and docset_mask is not None:
            positions = _filter_positions_by_docset(idx, positions, docset_mask)
        positions, _ = _drop_linebreak_sentinel_positions(idx, positions)
        total_matches = int(positions.size)
        if offset:
            positions = positions[int(offset):]
        if limit is not None:
            positions = positions[: int(limit)]
        return term_str, positions, total_matches, True

    prefetch_limit = None if docset_mask is not None else limit
    prefetch_offset = 0 if docset_mask is not None else offset
    case_kwargs = {"case_insensitive": False} if not case_insensitive else {}
    positions, positions_are_full = prefetch_positions_window(
        term_str,
        idx,
        limit=prefetch_limit,
        offset=prefetch_offset,
        use_cache=None,
        allow_cache_fallback=True,
        **case_kwargs,
    )
    if positions.size and docset_mask is not None:
        positions = _filter_positions_by_docset(idx, positions, docset_mask)
    # Same '|LBR|' sentinel exclusion as the CQL path so a literal '|LBR|' typed
    # in the plain box never matches the structural marker. Real words untouched.
    positions, _ = _drop_linebreak_sentinel_positions(idx, positions)
    total_matches = int(positions.size) if positions_are_full else int(offset) + int(positions.size)
    if docset_mask is not None:
        if offset:
            positions = positions[int(offset):]
        if limit is not None:
            positions = positions[: int(limit)]
    return term_str, positions, total_matches, positions_are_full


def _render_cql_fast_rows(
    idx: CorpusIndex,
    *,
    positions: np.ndarray,
    match_len_const: int | None,
    match_lengths: np.ndarray | None,
    pivot_index: int,
    ctx: int,
) -> list[dict[str, Any]]:
    from candyconc.core.query_runtime import _apply_cql_span_to_row

    if positions.size == 0:
        return []
    # Fixed-length matches: render each row at its pivot token (match start +
    # pivot_index), exactly like the canonical run_query path. The renderer's
    # ``two_token_pivot_one`` mode expects UNshifted match starts, so it must
    # not be combined with this shift (the row would land one token behind
    # the match and lose its match_offsets).
    kwic_positions = positions
    if match_len_const is not None and pivot_index:
        kwic_positions = (positions.astype(np.int64, copy=False) + int(pivot_index)).astype(
            np.uint32, copy=False
        )
    fixed_match_offsets = None
    inline_match_lengths = None
    if match_len_const is not None and match_len_const > 1:
        fixed_match_offsets = [
            i - int(pivot_index) for i in range(int(match_len_const)) if i != int(pivot_index)
        ]
    elif match_lengths is not None and pivot_index == 0:
        inline_match_lengths = match_lengths
    enriched_rows = _render_fast_rows_for_positions(
        idx,
        positions=kwic_positions,
        ctx=ctx,
        fixed_match_offsets=fixed_match_offsets,
        match_lengths=inline_match_lengths,
    )
    if not enriched_rows:
        return []

    if fixed_match_offsets is not None:
        # The dict-row fallback of the renderer does not annotate offsets.
        for row in enriched_rows:
            if "match_offsets" not in row:
                row["match_offsets"] = fixed_match_offsets
    elif match_lengths is not None and pivot_index != 0:
        # Variable-length branch: positions are NOT pre-shifted, so the helper's
        # first-token-shift is correct here.
        for row, match_len in zip(enriched_rows, match_lengths.tolist()):
            _apply_cql_span_to_row(row, int(match_len), pivot_index)
    return enriched_rows


# Scan-completeness of the most recent fast-row build, published by
# _query_rows_cql_fast / _query_rows_plain_fast for the sorted /query path
# (KWIC-PLAIN-02). A ContextVar keeps the signal out of the call signature so
# existing direct callers and test mocks are unaffected; defaults to True so a
# missing publish never falsely flags a result as sort-approximate.
_LAST_SCAN_FULL: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_candyconc_last_scan_full", default=True
)


def _query_rows_cql_fast(
    idx: CorpusIndex,
    term: str,
    *,
    ctx: int,
    limit: int | None,
) -> list[dict[str, Any]] | None:
    prepared = _prepare_cql_rows_fast(
        idx,
        term,
        offset=0,
        limit=limit,
        docset_mask=None,
    )
    if prepared is None:
        return None
    _query, positions, match_len_const, match_lengths, pivot_index, _total_matches, positions_are_full = prepared
    # KWIC-PLAIN-02: record whether the position scan was exhaustive so a sorted
    # view over a bounded subset is flagged sort-approximate even when the
    # post-sentinel-drop row count is below the sort scan cap. Published via a
    # ContextVar (not a new arg) so existing direct callers / mocks are unaffected.
    _LAST_SCAN_FULL.set(bool(positions_are_full))
    return _render_cql_fast_rows(
        idx,
        positions=positions,
        match_len_const=match_len_const,
        match_lengths=match_lengths,
        pivot_index=pivot_index,
        ctx=ctx,
    )


def _query_rows_plain_fast(
    idx: CorpusIndex,
    term: str,
    *,
    ctx: int,
    limit: int | None,
    case_insensitive: bool = True,
) -> list[dict[str, Any]] | None:
    prepared = _prepare_plain_rows_fast(
        idx,
        term,
        offset=0,
        limit=limit,
        docset_mask=None,
        case_insensitive=case_insensitive,
    )
    if prepared is None:
        return None
    term_text, positions, _total_matches, positions_are_full = prepared
    # KWIC-PLAIN-02: see _query_rows_cql_fast — publish scan completeness via the
    # ContextVar so a sorted view over a bounded subset is honestly flagged.
    _LAST_SCAN_FULL.set(bool(positions_are_full))
    render_kwargs = _plain_render_kwargs(term_text)
    chunk_threshold = max(1, int(get_config("CANDYCONC_QUERY_FAST_CHUNK_THRESHOLD", "20000")))
    chunk_size = max(1000, int(get_config("CANDYCONC_QUERY_FAST_CHUNK_SIZE", "20000")))
    if limit is None and int(positions.size) > chunk_threshold:
        return _render_fast_rows_for_positions_chunked(
            idx,
            positions=positions,
            ctx=ctx,
            chunk_size=chunk_size,
            **render_kwargs,
        )
    return _render_fast_rows_for_positions(
        idx,
        positions=positions,
        ctx=ctx,
        **render_kwargs,
    )


def _sentence_bounds_for_index(idx: CorpusIndex) -> np.ndarray:
    boundaries = idx.fast_index.boundaries
    if not (boundaries and getattr(boundaries, "sentence", None)):
        raise RuntimeError(
            lt(
                "Satzgrenzen fehlen. Bitte Index mit Satzgrenzen bauen.",
                "Sentence boundaries are missing. Build the index with sentence boundaries.",
            )
        )
    sent_bounds = boundaries.sentence._positions
    if sent_bounds.size == 0:
        raise RuntimeError(
            lt("Satzgrenzen leer. Bitte Index neu bauen.", "Sentence boundaries are empty. Rebuild the index.")
        )
    return sent_bounds.astype(np.uint32, copy=False)


def _doc_range_for_id(idx: CorpusIndex, doc_id: int, doc_bounds: np.ndarray) -> tuple[int, int]:
    token_count = int(idx.fast_index.token_store.token_count)
    doc_start = int(doc_bounds[int(doc_id)])
    doc_end = int(doc_bounds[int(doc_id) + 1]) if (int(doc_id) + 1) < int(doc_bounds.size) else token_count
    return doc_start, doc_end


def _sentence_bounds_for_doc(
    idx: CorpusIndex,
    doc_id: int,
    *,
    doc_bounds: np.ndarray,
    sentence_bounds: np.ndarray,
) -> list[tuple[int, int]]:
    doc_start, doc_end = _doc_range_for_id(idx, int(doc_id), doc_bounds)
    within = sentence_bounds[(sentence_bounds >= doc_start) & (sentence_bounds < doc_end)]
    if within.size == 0 or int(within[0]) > doc_start:
        within = np.insert(within, 0, np.uint32(doc_start))
    starts = np.unique(within.astype(np.uint32, copy=False))
    bounds: list[tuple[int, int]] = []
    for i, start in enumerate(starts):
        s = int(start)
        e = int(starts[i + 1]) if (i + 1) < int(starts.size) else int(doc_end)
        if e <= s:
            continue
        bounds.append((s, e))
    return bounds


def _sentence_index_for_pos(bounds: Sequence[tuple[int, int]], pos: int) -> Optional[int]:
    if not bounds:
        return None
    p = int(pos)
    for i, (start, end) in enumerate(bounds):
        if start <= p < end:
            return int(i)
    return None


def _slice_window(total: int, focus_idx: Optional[int], window: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    w = max(1, min(int(window), total))
    if focus_idx is None:
        return 0, w
    half = w // 2
    start = max(0, int(focus_idx) - half)
    end = min(total, start + w)
    start = max(0, end - w)
    return int(start), int(end)


def _alignment_pairs_for_reference_window(
    pairs: Sequence[Mapping[str, Any]],
    *,
    ref_start: int,
    ref_end: int,
) -> list[dict[str, Any]]:
    """Return one reference-centred display slice without losing adjacent gaps."""
    next_references: list[Optional[int]] = [None] * len(pairs)
    next_reference: Optional[int] = None
    for offset in range(len(pairs) - 1, -1, -1):
        ref_index = pairs[offset].get("ref_index")
        if isinstance(ref_index, int):
            next_reference = int(ref_index)
        next_references[offset] = next_reference

    def is_visible(reference_index: Optional[int]) -> bool:
        return reference_index is not None and int(ref_start) <= reference_index < int(ref_end)

    visible: list[dict[str, Any]] = []
    previous_reference: Optional[int] = None
    for offset, raw_pair in enumerate(pairs):
        pair = dict(raw_pair)
        ref_index = pair.get("ref_index")
        if isinstance(ref_index, int):
            if is_visible(int(ref_index)):
                visible.append(pair)
            previous_reference = int(ref_index)
            continue
        if is_visible(previous_reference) or is_visible(next_references[offset]):
            visible.append(pair)
    return visible


def _variant_window_bounds(pairs: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    indices = [
        int(pair["var_index"])
        for pair in pairs
        if isinstance(pair.get("var_index"), int)
    ]
    if not indices:
        return 0, 0
    return min(indices), max(indices) + 1


def _words_for_range(idx: CorpusIndex, start_pos: int, end_pos: int) -> list[str]:
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(_WORD_LEXICON_MISSING)
    ids = idx.fast_index.token_store.word_stream.get_range(int(start_pos), int(end_pos))
    if ids.size == 0:
        return []
    words = strings_for_ids(
        lex.offsets,
        lex.strings_view,
        ids.astype(np.uint32, copy=False),
        True,
    )
    return [str(w) for w in words if str(w)]


def _sentence_data_for_indices(
    idx: CorpusIndex,
    doc_id: int,
    bounds: Sequence[tuple[int, int]],
    indices: Sequence[int],
) -> list[SentenceData]:
    from candyconc.services.backend.pii_filter import mask_pii

    out: list[SentenceData] = []
    for i in indices:
        if i < 0 or i >= len(bounds):
            continue
        start_pos, end_pos = bounds[int(i)]
        tokens = _words_for_range(idx, start_pos, end_pos)
        raw_text = " ".join(tokens).strip()
        text = (
            mask_pii(raw_text, start_pos=int(start_pos), index=idx, tokens=list(tokens))
            if raw_text
            else raw_text
        )
        out.append(
            SentenceData(
                index=int(i),
                start_pos=int(start_pos),
                end_pos=int(end_pos),
                text=text,
                tokens=tokens,
            )
        )
    return out


try:  # optional fast path
    from candyconc.core.counting_kernels import co_kwic_offset_map_fast as _CO_KWIC_OFFSETS_FAST  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _CO_KWIC_OFFSETS_FAST = None


def _paired_guard(idx: CorpusIndex, feature: str) -> Optional[dict[str, Any]]:
    """Capability gate for paired-only analyses (W2 STEP 6).

    Parallel groups, ref-doc alignment and parallel KWIC are only meaningful on a
    corpus that declares pairing (``manifest.paired``). On a flat / unpaired corpus
    they would otherwise produce degenerate self-mapped groups. Return a graceful
    ``not_applicable`` envelope (HTTP 200) so the frontend can hide the feature
    instead of surfacing an error; return ``None`` when the corpus is paired and
    the caller should proceed unchanged.
    """
    manifest = getattr(idx, "manifest", None)
    if manifest is not None and bool(getattr(manifest, "paired", False)):
        return None
    return {
        "status": "not_applicable",
        "reason": "corpus_not_paired",
        "feature": feature,
        "detail": lt(
            "'{feature}' benötigt einen gepaarten Korpus (paired=False). "
            "Nutze /analysis/contrast für einen pairing-freien Kontrast.",
            "'{feature}' needs a paired corpus (paired=False). "
            "Use /analysis/contrast for a contrast without pairing.",
        ).format(feature=feature),
    }


def _coerce_doc_ids(raw: Any) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, np.ndarray):
        return [int(v) for v in raw.tolist()]
    if isinstance(raw, (list, tuple, set)):
        return [int(v) for v in raw if v is not None]
    return []


def _parse_ref_doc_from_meta(raw_meta: Any, doc_id: int) -> Optional[int]:
    if not isinstance(raw_meta, dict):
        return int(doc_id)
    ref_doc = raw_meta.get("ref_doc")
    if isinstance(ref_doc, str) and ref_doc.isdigit():
        return int(ref_doc)
    if isinstance(ref_doc, int):
        return int(ref_doc)
    if is_anchor(raw_meta.get("text_type")):
        return int(doc_id)
    return None


def _alignment_variant_axis_fields(idx: CorpusIndex) -> list[str]:
    manifest = getattr(idx, "manifest", None)
    axes = list(getattr(manifest, "pair_axes", []) or [])
    return [str(axis) for axis in axes if str(axis).strip()] or ["model"]


def _alignment_variant_axis(raw_meta: dict[str, Any], axes: Sequence[str]) -> tuple[str, str] | None:
    for axis in axes:
        value = str(raw_meta.get(str(axis)) or "").strip()
        if value:
            return str(axis), value
    model = str(raw_meta.get("model") or "").strip()
    if model:
        return "model", model
    return None


def _anchor_matcher(anchor_role: Optional[str]) -> Callable[[Any], bool]:
    """Test for the ``text_type`` of the anchor document of a pair group."""
    if anchor_role:
        wanted = str(anchor_role).lower()
        return lambda text_type: str(text_type or "").lower() == wanted
    return is_anchor


def _parallel_group_summary(
    idx: CorpusIndex,
    ref_doc: int,
    doc_ids: Sequence[int],
    *,
    anchor_role: Optional[str] = None,
) -> dict[str, Any]:
    # anchor_role=None: the anchor side of a pair, ``anchor`` or (older
    # indexes and the human/AI research layout) ``human``.
    anchor = _anchor_matcher(anchor_role)
    meta = idx.fast_index.doc_metadata or {}
    text_type_counts: dict[str, int] = {}
    sources: set[str] = set()
    human_doc_id: Optional[int] = None
    human_label = ""
    axis_fields = _alignment_variant_axis_fields(idx)

    for doc_id in doc_ids:
        raw = meta.get(int(doc_id), {})
        raw_meta = raw if isinstance(raw, dict) else {}
        text_type = str(raw_meta.get("text_type") or "").lower()
        if text_type:
            text_type_counts[text_type] = text_type_counts.get(text_type, 0) + 1
        source = str(raw_meta.get("source") or "")
        if source:
            sources.add(source)
        if human_doc_id is None and anchor(text_type):
            human_doc_id = int(doc_id)
            human_label = str(raw_meta.get("path") or raw_meta.get("title") or "")

    if human_doc_id is None and doc_ids:
        human_doc_id = int(doc_ids[0])
        raw = meta.get(int(human_doc_id), {})
        raw_meta = raw if isinstance(raw, dict) else {}
        human_label = str(raw_meta.get("path") or raw_meta.get("title") or "")

    variant_doc_ids = [int(doc_id) for doc_id in doc_ids if human_doc_id is None or int(doc_id) != human_doc_id]
    variant_counts: dict[tuple[str, str], int] = {}
    variants: list[dict[str, Any]] = []
    for doc_id in variant_doc_ids:
        raw = meta.get(int(doc_id), {})
        raw_meta = raw if isinstance(raw, dict) else {}
        axis_value = _alignment_variant_axis(raw_meta, axis_fields)
        if axis_value is not None:
            variant_counts[axis_value] = variant_counts.get(axis_value, 0) + 1
        label = str(
            raw_meta.get("profile_name")
            or raw_meta.get("variant")
            or raw_meta.get("model")
            or f"Dokument {doc_id}"
        )
        provenance = " · ".join(
            str(raw_meta.get(key) or "").strip()
            for key in ("source", "origin_id")
            if str(raw_meta.get(key) or "").strip()
        )
        variants.append({"doc_id": int(doc_id), "label": label, "provenance": provenance})
    models = [
        {
            "model": value,
            "axis": axis,
            "axis_value": value,
            "label": value,
            "count": int(count),
        }
        for (axis, value), count in sorted(variant_counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    ]

    return {
        "ref_doc": int(ref_doc),
        "doc_count": int(len(doc_ids)),
        "doc_ids": [int(doc_id) for doc_id in doc_ids],
        "human_doc_id": int(human_doc_id) if human_doc_id is not None else None,
        "variant_doc_ids": variant_doc_ids,
        "variants": variants,
        "models": models,
        "text_types": text_type_counts,
        "sources": sorted(sources),
        "label": human_label,
    }


def _alignment_for_ref_doc_sync(
    *,
    idx: CorpusIndex,
    corpus: str,
    ref_doc: int,
    focus_pos: Optional[int],
    window_sentences: int,
    variant_margin: int,
    include_models: Optional[Sequence[str]],
    max_variants: int,
    max_tokens: int,
    include_doc_ids: Optional[Sequence[int]] = None,
    anchor_role: Optional[str] = None,
    method: str = "edit",
) -> dict[str, Any]:
    # anchor_role=None: the anchor side of a pair (see _parallel_group_summary).
    anchor = _anchor_matcher(anchor_role)
    # STEP 9: validate/dispatch the alignment method before doing any work. An
    # unknown method is a 400; an embedding-backed method on an index without
    # sentence embeddings short-circuits to a graceful not_applicable envelope so
    # the whole endpoint response stays HTTP 200 and self-describing.
    method = (method or "edit").lower()
    if method not in _ALIGNMENT_METHODS:
        raise ApiError(
            400,
            "alignment.method_unknown",
            lt("Unbekannte Alignment-Methode: {method!r}", "Unknown alignment method: {method!r}"),
            method=method,
        )
    if method in ("embed", "hybrid") and not _sentence_embeddings_available(idx):
        return _alignment_not_applicable(method)
    doc_bounds = _doc_bounds_for_index(idx)
    sentence_bounds = _sentence_bounds_for_index(idx)
    mapping = resolve_pair_groups(idx, corpus, axis=None, anchor_role=anchor_role)
    variant_ids = mapping.get(int(ref_doc), [])
    if not variant_ids:
        raise ApiError(
            404,
            "alignment.variants_not_found",
            lt("Keine Varianten für ref_doc gefunden", "No variants found for ref_doc"),
        )

    meta = idx.fast_index.doc_metadata or {}

    def _meta(doc_id: int) -> dict[str, Any]:
        raw = meta.get(int(doc_id), {})
        return raw if isinstance(raw, dict) else {}

    human_doc_id = int(ref_doc)
    human_meta = _meta(human_doc_id)
    axis_fields = _alignment_variant_axis_fields(idx)
    if not anchor(human_meta.get("text_type")):
        for doc_id in variant_ids:
            m = _meta(doc_id)
            if anchor(m.get("text_type")):
                human_doc_id = int(doc_id)
                human_meta = m
                break

    requested_doc_ids = {int(doc_id) for doc_id in include_doc_ids or []}
    ai_variant_ids: list[int] = []
    for doc_id in variant_ids:
        if int(doc_id) == int(human_doc_id):
            continue
        m = _meta(int(doc_id))
        if requested_doc_ids and int(doc_id) not in requested_doc_ids:
            continue
        if include_models:
            model = str(m.get("model") or "")
            if model not in include_models:
                continue
        ai_variant_ids.append(int(doc_id))

    ai_variant_ids.sort(key=lambda d: (str(_meta(d).get("model") or ""), int(d)))
    if max_variants > 0:
        ai_variant_ids = ai_variant_ids[: int(max_variants)]
    if not ai_variant_ids:
        return {
            "status": "not_applicable",
            "reason": "requested_variant_unavailable",
            "detail": lt(
                "Die gewählte Dokumentvariante gehört nicht zur Referenzgruppe.",
                "The selected document variant does not belong to the reference group.",
            ),
        }

    ref_bounds = _sentence_bounds_for_doc(
        idx,
        int(human_doc_id),
        doc_bounds=doc_bounds,
        sentence_bounds=sentence_bounds,
    )

    # The legacy endpoint accepted ``variant_margin`` for ordinal candidate
    # windows. A complete document alignment makes that heuristic unnecessary.
    _ = variant_margin

    focus_sentence_index: Optional[int] = None
    variant_focus_sentence_index: Optional[int] = None
    focus_doc_id: Optional[int] = None
    focus_resolution = "not_requested"
    if focus_pos is not None:
        focus_doc_id = _doc_id_for_position(idx, int(focus_pos), doc_bounds)
        focus_bounds = _sentence_bounds_for_doc(
            idx,
            int(focus_doc_id),
            doc_bounds=doc_bounds,
            sentence_bounds=sentence_bounds,
        )
        focus_idx = _sentence_index_for_pos(focus_bounds, int(focus_pos))
        if focus_idx is not None:
            if int(focus_doc_id) == int(human_doc_id):
                focus_sentence_index = int(focus_idx)
                focus_resolution = "reference_sentence"
            else:
                variant_focus_sentence_index = int(focus_idx)

    # Derive every visible sentence pair from a complete document alignment. A
    # local ordinal window can silently drift after a single insertion and is
    # therefore never evidence for a research-facing correspondence.
    full_ref_sents = _sentence_data_for_indices(
        idx,
        int(human_doc_id),
        ref_bounds,
        list(range(len(ref_bounds))),
    )
    variant_documents: list[tuple[int, list[tuple[int, int]], list[SentenceData]]] = []
    for doc_id in ai_variant_ids:
        var_bounds = _sentence_bounds_for_doc(
            idx,
            int(doc_id),
            doc_bounds=doc_bounds,
            sentence_bounds=sentence_bounds,
        )
        var_sents = _sentence_data_for_indices(
            idx,
            int(doc_id),
            var_bounds,
            list(range(len(var_bounds))),
        )
        variant_documents.append((int(doc_id), var_bounds, var_sents))

    max_edit_cells = _alignment_edit_cell_limit()
    total_edit_cells = sum(
        _alignment_edit_cell_count(full_ref_sents, var_sents)
        for _doc_id, _var_bounds, var_sents in variant_documents
    )
    if total_edit_cells > max_edit_cells:
        return _alignment_budget_not_applicable(
            edit_cells=total_edit_cells,
            max_edit_cells=max_edit_cells,
            variant_count=len(variant_documents),
        )

    full_alignments: dict[int, tuple[list[dict[str, Any]], dict[str, Any], list[tuple[int, int]]]] = {}
    for doc_id, var_bounds, var_sents in variant_documents:
        raw_pairs, raw_summary = _align_sentence_lists(
            full_ref_sents,
            var_sents,
            max_tokens=int(max_tokens),
            method=method,
            idx=idx,
            max_edit_cells=max_edit_cells,
        )
        if raw_summary.get("status") == "not_applicable":
            # Do not embed an unavailable/partial result inside a payload that
            # the frontend could mistake for a comparable variant.
            return raw_summary
        pairs = _conservative_alignment_pairs(raw_pairs)
        summary = _alignment_summary_from_pairs(
            pairs,
            alignment_cost=float(raw_summary["alignment_cost"]),
        )
        full_alignments[int(doc_id)] = (pairs, summary, var_bounds)

    if variant_focus_sentence_index is not None:
        focus_alignment = full_alignments.get(int(focus_doc_id or -1))
        if focus_alignment is None:
            return {
                "status": "not_applicable",
                "reason": "focus_variant_not_selected",
                "detail": lt(
                    "Der geöffnete Variantenbeleg ist nicht in der aktuellen Vergleichsauswahl.",
                    "The opened variant line is not in the current comparison selection.",
                ),
            }
        focus_pairs = focus_alignment[0]
        resolved = next(
            (
                int(pair["ref_index"])
                for pair in focus_pairs
                if pair.get("var_index") == variant_focus_sentence_index
                and isinstance(pair.get("ref_index"), int)
            ),
            None,
        )
        if resolved is None:
            return {
                "status": "not_applicable",
                "reason": "focus_sentence_unresolved",
                "detail": lt(
                    "Für den geöffneten Varianten-Satz wurde keine ausreichend "
                    "belegte Referenzentsprechung gefunden. Es wird kein "
                    "irreführender Vergleich an einer anderen Textstelle gezeigt.",
                    "No sufficiently supported reference counterpart was found for "
                    "the opened variant sentence. No misleading comparison at a "
                    "different text position is shown.",
                ),
            }
        focus_sentence_index = resolved
        focus_resolution = "variant_sentence_resolved"

    ref_start, ref_end = _slice_window(
        len(ref_bounds),
        focus_sentence_index,
        int(window_sentences),
    )
    ref_sents = full_ref_sents[ref_start:ref_end]
    ref_doc_label, ref_meta_str = _doc_meta_for_doc_id(idx, int(human_doc_id))
    reference_payload = {
        "doc_id": int(human_doc_id),
        "doc": ref_doc_label,
        "meta": ref_meta_str,
        "sentence_count": int(len(ref_bounds)),
        "window_start": int(ref_start),
        "window_end": int(ref_end),
        "focus_sentence_index": focus_sentence_index,
        "sentences": [
            {
                "index": s.index,
                "start_pos": s.start_pos,
                "end_pos": s.end_pos,
                "text": s.text,
                "token_count": int(len(s.tokens)),
            }
            for s in ref_sents
        ],
    }

    variants_payload: list[dict[str, Any]] = []
    for doc_id, _var_bounds, _var_sents in variant_documents:
        pairs, summary, var_bounds = full_alignments[int(doc_id)]
        display_pairs = _alignment_pairs_for_reference_window(
            pairs,
            ref_start=ref_start,
            ref_end=ref_end,
        )
        var_start, var_end = _variant_window_bounds(display_pairs)
        var_doc_label, var_meta_str = _doc_meta_for_doc_id(idx, int(doc_id))
        axis_value = _alignment_variant_axis(_meta(doc_id), axis_fields)
        variants_payload.append(
            {
                "doc_id": int(doc_id),
                "doc": var_doc_label,
                "meta": var_meta_str,
                "model": str(_meta(doc_id).get("model") or ""),
                **(
                    {
                        "axis": axis_value[0],
                        "axis_value": axis_value[1],
                        "label": axis_value[1],
                    }
                    if axis_value is not None
                    else {}
                ),
                "text_type": str(_meta(doc_id).get("text_type") or ""),
                "sentence_count": int(len(var_bounds)),
                "window_start": int(var_start),
                "window_end": int(var_end),
                "summary": summary,
                "pairs": display_pairs,
            }
        )

    result: dict[str, Any] = {
        "ref_doc": int(ref_doc),
        "corpus": corpus,
        "focus_pos": focus_pos,
        "focus_doc_id": focus_doc_id,
        "focus_resolution": focus_resolution,
        "alignment_scope": "complete_document",
        "confidence_threshold": _ALIGNMENT_MIN_CONFIDENT_SIMILARITY,
        "reference": reference_payload,
        "variants": variants_payload,
        "variant_count": int(len(variants_payload)),
    }
    # ``edit`` remains the default calculation method.  The response now always
    # records its complete-document scope and evidence threshold so the UI never
    # upgrades a local heuristic to a scientific correspondence.
    if method != "edit":
        result["alignment_method"] = method
    return result


def _tokenize_kw(text: str) -> list[str]:
    if not text:
        return []
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    return tokens


def _find_kw_span(tokens: Sequence[str], kw_tokens: Sequence[str]) -> tuple[int, int] | None:
    if not tokens or not kw_tokens:
        return None
    lower_tokens = [t.lower() for t in tokens]
    lower_kw = [t.lower() for t in kw_tokens]
    n = len(lower_tokens)
    k = len(lower_kw)
    if k == 0:
        return None
    if k <= n:
        for i in range(n - k + 1):
            if lower_tokens[i : i + k] == lower_kw:
                return i, i + k
    if k == 1:
        for i, tok in enumerate(lower_tokens):
            if tok == lower_kw[0]:
                return i, i + 1
    return None


def _kwic_from_sentence(
    idx: CorpusIndex,
    sentence: SentenceData | None,
    *,
    kw_tokens: Sequence[str],
    ctx: int,
) -> dict[str, Any]:
    # Ohne Gegenstueck-Satz (sentence None) bleibt die Zeile leer.
    tokens = (sentence.tokens if sentence is not None else None) or []
    if not tokens:
        return {"left": "", "kw": "", "right": "", "matched": False, "kw_index": None}

    span = _find_kw_span(tokens, kw_tokens)
    matched = True
    if span is None:
        # Without the keyword the bracket stays empty and the sentence is
        # centred on its middle. The middle token in the bracket would look
        # like the keyword.
        matched = False
        kw_start = kw_end = len(tokens) // 2
    else:
        kw_start, kw_end = span

    ctx = max(1, _bounded_query_context(ctx))
    left_tokens = tokens[max(0, kw_start - ctx) : kw_start]
    kw_slice = tokens[kw_start:kw_end]
    right_tokens = tokens[kw_end : kw_end + ctx]

    left_raw = " ".join(left_tokens).strip()
    kw_raw = " ".join(kw_slice).strip()
    right_raw = " ".join(right_tokens).strip()

    from candyconc.services.backend.pii_filter import mask_pii

    left = (
        mask_pii(left_raw, start_pos=sentence.start_pos, index=idx, tokens=list(left_tokens))
        if left_raw
        else left_raw
    )
    kw = (
        mask_pii(
            kw_raw,
            start_pos=sentence.start_pos + kw_start,
            index=idx,
            tokens=list(kw_slice),
        )
        if kw_raw
        else kw_raw
    )
    right = (
        mask_pii(
            right_raw,
            start_pos=sentence.start_pos + kw_end,
            index=idx,
            tokens=list(right_tokens),
        )
        if right_raw
        else right_raw
    )

    return {
        "left": left,
        "kw": kw,
        "right": right,
        "matched": matched,
        "kw_index": int(kw_start),
    }


def _best_matching_sentence(
    idx: CorpusIndex,
    *,
    ref_sentence: SentenceData,
    ref_index: int,
    doc_id: int,
    doc_bounds: np.ndarray,
    sentence_bounds: np.ndarray,
    margin: int,
    max_tokens: int = 512,
) -> tuple[SentenceData | None, int | None, float | None, float | None]:
    bounds = _sentence_bounds_for_doc(idx, int(doc_id), doc_bounds=doc_bounds, sentence_bounds=sentence_bounds)
    if not bounds:
        return None, None, None, None
    ref_index = max(0, min(int(ref_index), len(bounds) - 1))
    margin = max(0, min(int(margin), 12))
    start = max(0, ref_index - margin)
    end = min(len(bounds), ref_index + margin + 1)
    indices = list(range(start, end))
    candidates = _sentence_data_for_indices(idx, int(doc_id), bounds, indices)
    if not candidates:
        return None, None, None, None

    best: SentenceData | None = None
    best_med: int | None = None
    best_norm: float | None = None
    best_sim: float | None = None
    if len(ref_sentence.tokens or []) > max(1, int(max_tokens)):
        return None, None, None, None
    # The same pair scoring and the same threshold as the alignment of whole
    # documents (_conservative_alignment_pairs). Without the threshold,
    # parallel KWIC showed the most similar sentence for 54 versions on a
    # corpus of 250,535 documents, median similarity 0.15, only 3 above 0.5.
    ref_norm = _normalize_tokens(ref_sentence.tokens)
    for cand in candidates:
        if len(cand.tokens or []) > max(1, int(max_tokens)):
            continue
        cand_norm = _normalize_tokens(cand.tokens)
        med, norm, sim = _normalized_med_norm(ref_norm, cand_norm, len(ref_norm), len(cand_norm))
        sim = _edit_similarity_with_overlap(ref_norm, cand_norm, sim)
        if best is None or sim > best_sim or (sim == best_sim and norm < best_norm):
            best = cand
            best_med = med
            best_norm = norm
            best_sim = sim
    if best is None or best_sim < _ALIGNMENT_MIN_CONFIDENT_SIMILARITY:
        # Kein Gegenstueck: nicht ausgerichtet, statt eines schwachen Vorschlags.
        return None, None, None, None
    return best, best_med, best_norm, best_sim


def _match_meta_filters(meta: dict, filters: Dict[str, Any]) -> bool:
    # Delegates to the canonical core matcher (single source of truth). No transform
    # translation here: these callers pass native frontend filters (prompting_method).
    from candyconc.core.meta_filters import match_meta_filters

    return match_meta_filters(meta, filters)


# ---------------------------------------------------------------------------
# Export directory
#
# (The cluster JSON schema moved to routes/projects.py with the
# /projects/{proj}/clusters route family; the recluster schema +
# _validate_recluster moved to routes/semantic.py with the /semantic routes.)
_EXPORT_DIR = tmp_dir / "exports"
_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


_PANDOC_TIMEOUT_SEC = 60
_PANDOC_SANDBOX_SUPPORTED: bool | None = None


def apply_plan(
    clusters: List[Dict[str, Any]], plan: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Apply merge/split/rename plan to ``clusters``."""

    mapping: Dict[str, Dict[str, Any]] = {}
    for c in clusters:
        cid = str(c.get("id", c.get("cluster_id")))
        item = dict(c)
        item["id"] = cid
        mapping[cid] = item

    for cid, label in plan.get("renames", {}).items():
        if cid in mapping:
            mapping[cid]["label"] = label

    for keep, drop in plan.get("merges", []):
        keep = str(keep)
        drop = str(drop)
        if keep in mapping and drop in mapping:
            mapping[keep]["tokens"] = mapping[keep].get("tokens", []) + mapping[
                drop
            ].get("tokens", [])
            mapping.pop(drop, None)

    if plan.get("splits"):
        raise RuntimeError(
            lt(
                "Cluster Splits sind deaktiviert, da Embedding Centroids fehlen.",
                "Cluster splits are disabled because embedding centroids are missing.",
            )
        )

    return list(mapping.values())


# ---------------------------------------------------------------------------
# Multi-tenant project state
_PROJECT_USERS: Dict[str, Set[str]] = {}
_PROJECTS_DIR = _user_paths.projects_dir(get_config("CANDYCONC_PROJECTS_DIR", "") or None)
def _load_projects() -> None:
    """Load project definitions from ``_PROJECTS_DIR``."""
    if not _PROJECTS_DIR.is_dir():
        return
    for file in _PROJECTS_DIR.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = data.get("name") or file.stem
        users = set(data.get("users", []))
        owner = data.get("owner")
        if owner:
            users.add(owner)
        if users:
            _PROJECT_USERS[name] = users
        quota = data.get("quota")
        if quota is not None:
            with contextlib.suppress(Exception):
                PROJECT_QUOTAS[name] = int(quota)


def _safe_project_segment(name: str) -> str:
    """Validate ``name`` as a single safe path segment (no traversal/absolute),
    so a project name can never escape ``_PROJECTS_DIR`` on write/read."""
    from candyconc.domain.corpus import normalize_corpus_name
    return normalize_corpus_name(name)


def _persist_project(name: str) -> None:
    """Write project ``name`` back to ``_PROJECTS_DIR``."""
    if DRY_RUN:
        return
    safe = _safe_project_segment(name)
    if not _PROJECTS_DIR.is_dir():
        _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "users": sorted(_PROJECT_USERS.get(name, set())),
        "quota": PROJECT_QUOTAS.get(name, 0),
    }
    path = _PROJECTS_DIR / f"{safe}.json"
    path.resolve().relative_to(_PROJECTS_DIR.resolve())  # defense-in-depth containment
    if not DRY_RUN:
        path.write_text(json.dumps(data), encoding="utf-8")


_load_projects()


def _user_key(token: str | None, project: str) -> str:
    """Return unique key for ``token`` in ``project`` ensuring access rights."""
    if token is None and not auth.RBAC_ENABLED:
        return f"{project}:guest"
    username = auth.username_for_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if project == "default":
        _PROJECT_USERS.setdefault("default", set()).add(username)
    elif project not in _PROJECT_USERS or username not in _PROJECT_USERS[project]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return f"{project}:{username}"


def _require_admin_access(token: str | None) -> None:
    if auth.RBAC_ENABLED:
        auth.require_role("admin")(token)
        return
    if token is None:
        raise HTTPException(status_code=401, detail="Admin token required.")
    if auth.username_for_token(token) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if auth.role_for_token(token) != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")


def _require_user_access(token: str | None) -> None:
    if auth.RBAC_ENABLED:
        auth.require_role("user")(token)
        return
    # User endpoints require a token even when RBAC is disabled. Keep this
    # authorization contract consistent with tests/server/test_server_login.py
    # and test_analysis_meta_schema.
    if token is None:
        raise HTTPException(status_code=401, detail="User token required.")
    if auth.username_for_token(token) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _obs_metrics_text() -> str:
    if _OBSERVABILITY is None:
        return ""
    lines = [
        f"candyconc_{k.replace('.', '_')} {v}"
        for k, v in _OBSERVABILITY.export_metrics().items()
    ]
    return "\n".join(lines) + ("\n" if lines else "")


_DEV_TOKEN: str | None = None

# Operational/admin routes live in routes/system.py.


api_router.include_router(query_routes.router)


@api_router.get(
    "/query/count",
    responses={200: {"content": {"application/json": {"example": {"status": "ready", "total": 123, "partial": False}}}}},
)
async def query_count_endpoint(
    term: str,
    ctx: int = 5,
    corpus: str = "default",
    date: str | None = None,
    genre: str | None = None,
    docset_id: str | None = None,
    start: bool = True,
    wait_ms: int = 0,
    case_insensitive: Annotated[bool, Depends(_resolve_case_insensitive)] = True,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    user: str | None = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> Dict[str, Any]:
    """Return total hit count for a query. Uses shared coordinator to avoid redundant work."""
    idx = get_corpus(corpus)
    term_str = term.strip()
    if not term_str:
        return {"status": "ready", "total": 0, "partial": False, "elapsed_ms": 0}

    docset_mask = None
    if docset_id:
        docset = _get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(
                422,
                "docset.other_corpus",
                lt("docset_id gehört zu anderem Korpus", "docset_id belongs to a different corpus"),
            )
        docset_mask = docset.get("docset_mask")

    # A caller error in a CQL query (parse error, unknown attribute, a pos
    # value outside the tagset) is raised by the first step of the count. Check
    # it before the background task starts, so the first answer is the 400 and
    # not "running".
    if start:
        from candyconc.core.cql_engine import check_cql_conditions
        from candyconc.core.cql_macros import normalize_query_input

        normalized_term = normalize_query_input(_canonicalize_term(term_str))
        if normalized_term.lower().startswith("cql:") and normalized_term[4:].strip():
            try:
                await asyncio.to_thread(
                    check_cql_conditions, idx.fast_index, normalized_term[4:].strip()
                )
            except (RuntimeError, ValueError) as exc:
                mapped = _classify_query_runtime_error(exc)
                if mapped is not None:
                    raise mapped from exc
                raise

    # Build signature so an in-place rebuild of the same corpus name never serves
    # a stale count. Include case_insensitive in the result identity.
    build_sig = _corpus_cache_signature(getattr(idx, "fast_index", None), corpus or "default")
    count_key = _query_count_key(
        term, corpus, date, genre, docset_id,
        build_sig=build_sig, case_insensitive=case_insensitive,
    )
    count_state = await _get_or_create_query_count(
        count_key,
        create=bool(start),
        compute_fn=lambda: _compute_query_count(
            idx, term, int(ctx), date, genre, docset_mask,
            case_insensitive=case_insensitive,
        ),
        attach=False,
    )
    if count_state is None:
        return {"status": "missing"}

    result = _resolve_query_count_result(count_state)
    if result is not None:
        total, elapsed_ms, partial = result
        return {"status": "ready", "total": total, "partial": partial, "elapsed_ms": elapsed_ms}
    if count_state.error:
        return _query_count_error_response(count_state.error)

    if wait_ms > 0:
        deadline = time.monotonic() + max(0, wait_ms) / 1000.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            result = _resolve_query_count_result(count_state)
            if result is not None:
                total, elapsed_ms, partial = result
                return {"status": "ready", "total": total, "partial": partial, "elapsed_ms": elapsed_ms}
            if count_state.error:
                return _query_count_error_response(count_state.error)

    return {"status": "running"}


def _analysis_config_int(name: str, default: int) -> int:
    try:
        return int(get_config(name, str(default)) or default)
    except (TypeError, ValueError):
        return int(default)


_PAGE_LIMIT_DEFAULT = max(1, _analysis_config_int("CANDYCONC_ANALYSIS_PAGE_LIMIT_DEFAULT", 200))
_PAGE_LIMIT_MAX = max(_PAGE_LIMIT_DEFAULT, _analysis_config_int("CANDYCONC_ANALYSIS_PAGE_LIMIT_MAX", 5000))
_ANALYSIS_SYNC_LIMIT_DEFAULT = max(
    1,
    min(
        _analysis_config_int("CANDYCONC_ANALYSIS_SYNC_LIMIT_DEFAULT", 500),
        _PAGE_LIMIT_MAX,
    ),
)
_ANALYSIS_SYNC_LIMIT_MAX = max(
    _ANALYSIS_SYNC_LIMIT_DEFAULT,
    _analysis_config_int("CANDYCONC_ANALYSIS_SYNC_LIMIT_MAX", _PAGE_LIMIT_MAX),
)
_ANALYSIS_JOB_TOP_N_DEFAULT = max(1, _analysis_config_int("CANDYCONC_ANALYSIS_JOB_TOP_N_DEFAULT", 5000))
_ANALYSIS_JOB_TOP_N_MAX = max(
    _ANALYSIS_JOB_TOP_N_DEFAULT,
    _analysis_config_int("CANDYCONC_ANALYSIS_JOB_TOP_N_MAX", 50000),
)
_ANALYSIS_NGRAM_MAX_N = max(1, _analysis_config_int("CANDYCONC_ANALYSIS_NGRAM_MAX_N", 5))
_ANALYSIS_COLLOCATE_MAX_WINDOW = max(
    1,
    _analysis_config_int("CANDYCONC_ANALYSIS_COLLOCATE_MAX_WINDOW", 50),
)
# Scientific analysis must consume the complete CQL result, never the first
# configurable prefix.  The index's signed-position guard is the physical
# upper bound and an impossible full run fails instead of returning partial data.
_ANALYSIS_MATCH_LIMIT = _CQL_COUNT_PROBE_HARD_MAX


def _bounded_positive_limit(value: Any, *, default: int, maximum: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = int(default)
    if limit <= 0:
        limit = int(default)
    return max(1, min(limit, int(maximum)))


def _bounded_analysis_sync_limit(value: Any, *, default: int | None = None) -> int:
    """Bound a user-supplied analysis ``limit`` for the synchronous routes.

    Uniform limit policy (findings 4 + 34): an explicitly-supplied non-positive
    limit is rejected with HTTP 422 (consistent with the ``group_by`` enum and
    ``window`` range checks on the same endpoints) instead of being silently
    coerced to the default. A missing limit (None / "") still falls back to the
    default; an oversized limit is clamped to the max and the route echoes the
    capped ``row_limit`` (and ``truncated``) so the bound is visible. This lives
    here so the analysis routes inherit it without editing the route module.
    """
    effective_default = _ANALYSIS_SYNC_LIMIT_DEFAULT if default is None else int(default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return _bounded_positive_limit(
            None, default=effective_default, maximum=_ANALYSIS_SYNC_LIMIT_MAX
        )
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        # Non-integer payload value: preserve the prior lenient fallback to the
        # default (query-string ints are already type-validated by FastAPI).
        return _bounded_positive_limit(
            value, default=effective_default, maximum=_ANALYSIS_SYNC_LIMIT_MAX
        )
    _reject_non_positive_limit(as_int)
    return _bounded_positive_limit(
        as_int, default=effective_default, maximum=_ANALYSIS_SYNC_LIMIT_MAX
    )


def _bounded_analysis_job_limit(value: Any) -> int:
    return _bounded_positive_limit(
        value,
        default=_ANALYSIS_JOB_TOP_N_DEFAULT,
        maximum=_ANALYSIS_JOB_TOP_N_MAX,
    )


def _bounded_result_meta(
    *,
    row_limit: int,
    total_candidates: int,
    offset: int = 0,
) -> dict[str, Any]:
    safe_limit = max(1, int(row_limit))
    safe_total = max(0, int(total_candidates))
    safe_offset = _bounded_offset(offset)
    return {
        "row_limit": int(safe_limit),
        "total_candidates": int(safe_total),
        "truncated": bool(safe_total > safe_offset + safe_limit),
    }


def _bounded_page_limit(value: Any) -> int:
    return _bounded_positive_limit(value, default=_PAGE_LIMIT_DEFAULT, maximum=_PAGE_LIMIT_MAX)


def _bounded_offset(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _validate_ngram_bounds(min_n: int, max_n: int) -> tuple[int, int]:
    if min_n < 1 or max_n < 1:
        raise ApiError(
            400,
            "ngram.bounds_invalid",
            lt("min_n und max_n müssen >= 1 sein", "min_n and max_n must be >= 1"),
        )
    if max_n < min_n:
        min_n, max_n = max_n, min_n
    if max_n > _ANALYSIS_NGRAM_MAX_N:
        raise ApiError(
            400,
            "ngram.max_n_too_large",
            lt("max_n darf hoechstens {max_n} sein", "max_n must be at most {max_n}"),
            max_n=_ANALYSIS_NGRAM_MAX_N,
        )
    return int(min_n), int(max_n)


def _validate_collocate_window(window: int) -> int:
    window = int(window)
    if window < 1:
        raise ApiError(
            400,
            "collocation.window_invalid",
            lt("window muss >= 1 sein", "window must be >= 1"),
        )
    if window > _ANALYSIS_COLLOCATE_MAX_WINDOW:
        raise ApiError(
            400,
            "collocation.window_too_large",
            lt("window darf hoechstens {max_window} sein", "window must be at most {max_window}"),
            max_window=_ANALYSIS_COLLOCATE_MAX_WINDOW,
        )
    return window


def _parse_stopwords(stopwords: str | list[str] | tuple[str, ...] | None) -> list[str] | None:
    if not stopwords:
        return None
    if isinstance(stopwords, (list, tuple)):
        words = [str(w).strip() for w in stopwords]
        words = [w for w in words if w]
        return words or None
    if not isinstance(stopwords, str):
        raise ApiError(
            400,
            "analysis.stopwords_invalid",
            lt("stopwords müssen String oder Liste sein", "stopwords must be a string or a list"),
        )
    words = [w.strip() for w in stopwords.split(",")]
    words = [w for w in words if w]
    return words or None


def _resolve_doc_ids_for_job(
    idx: CorpusIndex,
    corpus: str | None,
    docset_id: str | None,
) -> np.ndarray:
    if not docset_id:
        doc_count = _doc_count_for_index(idx)
        return np.arange(doc_count, dtype=np.uint32)
    docset = _get_docset(docset_id)
    if docset.get("corpus") != (corpus or "default"):
        raise ApiError(
            422,
            "docset.corpus_mismatch",
            lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"),
        )
    doc_ids = docset.get("doc_ids")
    if doc_ids is None:
        raise ApiError(
            422,
            "docset.doc_ids_missing",
            lt("Docset ohne doc_ids", "Document set without doc_ids"),
        )
    return np.asarray(doc_ids, dtype=np.uint32)


def _top_count_arrays(
    ids: np.ndarray,
    counts: np.ndarray,
    *,
    limit: int,
) -> tuple[np.ndarray, np.ndarray, int, bool]:
    total = int(ids.size)
    if total == 0:
        return ids, counts, 0, False
    safe_limit = _bounded_analysis_job_limit(limit)
    ids_u = ids.astype(np.uint64, copy=False)
    counts_u = counts.astype(np.uint64, copy=False)
    if total > safe_limit:
        # ``argpartition`` alone makes a tie at the display boundary arbitrary:
        # a saved frequency analysis can then replay with different words. Pick
        # the entire global threshold first and resolve ties by stable term id.
        cutoff_index = total - safe_limit
        cutoff = np.partition(counts_u, cutoff_index)[cutoff_index]
        greater = np.flatnonzero(counts_u > cutoff)
        equal = np.flatnonzero(counts_u == cutoff)
        remaining = safe_limit - int(greater.size)
        if equal.size > remaining:
            equal = equal[np.argsort(ids_u[equal], kind="stable")[:remaining]]
        selected = np.concatenate((greater, equal))
    else:
        selected = np.arange(total, dtype=np.int64)
    # Count descending, then stable canonical id ascending: exact and replayable
    # whether the complete population fits on screen or not.
    order = selected[
        np.lexsort((ids_u[selected], -counts_u[selected].astype(np.int64, copy=False)))
    ]
    return ids[order], counts[order], total, total > safe_limit


async def _run_frequency_job(
    job_id: str,
    *,
    corpus: str | None,
    doc_ids: np.ndarray,
    stopwords: list[str] | None,
    pos_prefix: str | None,
    limit: int,
) -> None:
    try:
        analysis_jobs.update(job_id, progress=5, message=lt("Dokumentmenge wird vorbereitet", "Preparing document set"), status="running")
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=15, message=lt("Tokenfrequenzen werden gezählt", "Counting token frequencies"))
        # case_fold=True keeps this background frequency-list job consistent with
        # the synchronous CorpusIndex.frequency_list_docset (which folds by
        # default): one row per str.casefold class, labelled by its stable
        # representative surface form (C-casefold-counting-01).
        term_ids, counts = await _run_heavy_scan(
            idx.frequency_counts_docset,
            doc_ids,
            stopwords=stopwords,
            pos_prefix=pos_prefix,
            case_fold=True,
        )
        if term_ids.size:
            lex = idx.fast_index.lexicons.word
            if lex is None:
                raise RuntimeError(_WORD_LEXICON_MISSING)
            words = strings_for_ids(
                lex.offsets,
                lex.strings_view,
                term_ids.astype(np.uint32, copy=False),
                True,
            )
            keep = np.fromiter(
                (is_analyst_token(word) for word in words),
                dtype=np.bool_,
                count=int(term_ids.size),
            )
            term_ids = term_ids[keep]
            counts = counts[keep]
        analysis_jobs.update(
            job_id,
            progress=85,
            message=lt("Fertig gezählt: {types} Typen", "Counting done: {types} types").format(types=int(term_ids.size)),
        )
        term_ids, counts, total_candidates, truncated = _top_count_arrays(
            term_ids.astype(np.uint32, copy=False),
            counts.astype(np.uint64, copy=False),
            limit=limit,
        )
        result = {
            "term_ids": term_ids.astype(np.uint32, copy=False),
            "counts": counts.astype(np.uint64, copy=False),
            "pos_prefix": pos_prefix or "",
            "row_limit": int(limit),
            "total_candidates": int(total_candidates),
            "truncated": bool(truncated),
            "case_policy": CASE_POLICY_GEFALTET,
            "label_policy": LABEL_POLICY_GEFALTET,
        }
        analysis_jobs.set_result(job_id, result=result, total_rows=int(term_ids.size))
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Frequency Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


async def _run_frequency_diff_job(
    job_id: str,
    *,
    corpus: str | None,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    min_freq: int,
    limit: int,
) -> None:
    """Rank an exact, analyst-token filtered frequency contrast.

    The ranking is deliberately built from the complete union of both docset
    vocabularies. Fetching two bounded frequency lists and joining them in the
    UI can silently omit a word with the largest normalized difference.
    """
    try:
        target_doc_ids, reference_doc_ids = normalize_disjoint_docsets(
            target_doc_ids, reference_doc_ids
        )
        idx = get_corpus(corpus)
        safe_limit = _bounded_analysis_job_limit(limit)
        effective_min_freq = max(1, int(min_freq))
        analysis_jobs.update(
            job_id,
            progress=5,
            message=lt("Dokumentmengen werden vorbereitet", "Preparing document sets"),
            status="running",
        )
        analysis_jobs.update(job_id, progress=18, message=lt("Zielfrequenzen werden gezählt", "Counting target frequencies"))
        # The rows are word tokens (analyst-token mask below), so each side's
        # rate divides by its word tokens, the denominator keyness uses for
        # the same docsets. The raw token count stays in the method block.
        target_data, reference_data, basis_t, basis_r = await asyncio.gather(
            _run_heavy_scan(
                idx.frequency_counts_docset,
                target_doc_ids,
                stopwords=None,
                pos_prefix=None,
                case_fold=True,
            ),
            _run_heavy_scan(
                idx.frequency_counts_docset,
                reference_doc_ids,
                stopwords=None,
                pos_prefix=None,
                case_fold=True,
            ),
            asyncio.to_thread(_word_denominator, idx, target_doc_ids),
            asyncio.to_thread(_word_denominator, idx, reference_doc_ids),
        )
        target_ids, target_counts = target_data
        reference_ids, reference_counts = reference_data
        total_t = int(basis_t["woerter"])
        total_r = int(basis_r["woerter"])
        total_t_raw = int(basis_t["roh"])
        total_r_raw = int(basis_r["roh"])
        if total_t <= 0 or total_r <= 0:
            raise ValueError(
                lt(
                    "Frequenzdifferenzen benötigen zwei nichtleere Tokenpopulationen",
                    "Frequency differences need two non-empty token populations",
                )
            )

        method = build_method_block(
            "frequency_diff",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=total_t,
            reference_total=total_r,
            sort_key="diff_abs",
            counting_attribute="word",
            extra={
                "min_freq": effective_min_freq,
                "candidate_policy": "complete_union_before_ranking",
                "filtered_token_policy": KEYNESS_ANALYST_TOKEN_POLICY,
                "target_tokens_roh": total_t_raw,
                "reference_tokens_roh": total_r_raw,
                "denominator_source": basis_t["quelle"],
            },
        )

        analysis_jobs.update(job_id, progress=56, message=lt("Vokabularunion wird gebildet", "Building vocabulary union"))
        union_ids = np.union1d(
            np.asarray(target_ids, dtype=np.uint32),
            np.asarray(reference_ids, dtype=np.uint32),
        )
        rows: list[dict[str, Any]] = []
        total_candidates = 0
        if union_ids.size:
            target_aligned = _align_counts_to_union(union_ids, target_ids, target_counts)
            reference_aligned = _align_counts_to_union(
                union_ids, reference_ids, reference_counts
            )
            analyst_keep = _analyst_token_mask_for_term_ids(idx, union_ids)
            floor_keep = np.maximum(target_aligned, reference_aligned) >= effective_min_freq
            keep = analyst_keep & floor_keep
            union_ids = union_ids[keep]
            target_aligned = target_aligned[keep]
            reference_aligned = reference_aligned[keep]
            total_candidates = int(union_ids.size)

            if total_candidates:
                analysis_jobs.update(
                    job_id,
                    progress=74,
                    message=lt("Vollständige Frequenzdifferenzen werden sortiert", "Sorting full frequency differences"),
                )
                target_per_million = (
                    target_aligned.astype(np.float64, copy=False) * 1_000_000.0
                ) / float(total_t)
                reference_per_million = (
                    reference_aligned.astype(np.float64, copy=False) * 1_000_000.0
                ) / float(total_r)
                diff_per_million = target_per_million - reference_per_million
                diff_abs = np.abs(diff_per_million)
                # A full lexsort is intentional: the displayed top-N is exact,
                # and the stable term-id tie break makes saved/replayed results
                # reproducible rather than dependent on an argpartition boundary.
                order = np.lexsort((union_ids.astype(np.uint64, copy=False), -diff_abs))
                selected = order[:safe_limit]
                selected_ids = union_ids[selected].astype(np.uint32, copy=False)
                lex = idx.fast_index.lexicons.word
                if lex is None:
                    raise RuntimeError(_WORD_LEXICON_MISSING)
                words = strings_for_ids(lex.offsets, lex.strings_view, selected_ids, True)
                for word, target_freq, reference_freq, target_pm, reference_pm, diff_pm, absolute in zip(
                    words,
                    target_aligned[selected],
                    reference_aligned[selected],
                    target_per_million[selected],
                    reference_per_million[selected],
                    diff_per_million[selected],
                    diff_abs[selected],
                ):
                    clean_word = str(word).strip()
                    if not clean_word:
                        continue
                    rows.append(
                        {
                            "word": clean_word,
                            "target_freq": int(target_freq),
                            "reference_freq": int(reference_freq),
                            "target_per_million": float(target_pm),
                            "reference_per_million": float(reference_pm),
                            "diff_per_million": float(diff_pm),
                            "diff_abs": float(absolute),
                        }
                    )

        analysis_jobs.update(job_id, progress=92, message=lt("Fertig: {rows} Reihen", "Done: {rows} rows").format(rows=len(rows)))
        analysis_jobs.set_result(
            job_id,
            result={
                "rows": rows,
                "min_freq": effective_min_freq,
                "target_token_count": total_t_raw,
                "reference_token_count": total_r_raw,
                "target_word_count": total_t,
                "reference_word_count": total_r,
                "method": method,
                **_bounded_result_meta(
                    row_limit=safe_limit,
                    total_candidates=total_candidates,
                ),
            },
            total_rows=len(rows),
        )
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Frequency-Diff-Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


KEYNESS_ANALYST_TOKEN_POLICY = lt(
    "Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen "
    "(gleiche Analyst-Token-Politik wie frequency_list)",
    "Empty values, values without alphanumeric characters and |marker| values "
    "are excluded (same word-token policy as frequency_list)",
)


def _analyst_token_mask_for_term_ids(idx: CorpusIndex, term_ids: np.ndarray) -> np.ndarray:
    term_ids = np.asarray(term_ids, dtype=np.uint32)
    if term_ids.size == 0:
        return np.zeros(0, dtype=np.bool_)
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(_WORD_LEXICON_MISSING)
    words = strings_for_ids(lex.offsets, lex.strings_view, term_ids, True)
    return np.fromiter(
        (is_analyst_token(word) for word in words),
        dtype=np.bool_,
        count=int(term_ids.size),
    )


def _empty_keyness_docset_result(total_t: int, total_r: int, method: dict[str, Any]) -> dict[str, Any]:
    return {
        "term_ids": np.zeros(0, dtype=np.uint32),
        "target_counts": np.zeros(0, dtype=np.uint64),
        "reference_counts": np.zeros(0, dtype=np.uint64),
        "chi2_cell": np.zeros(0),
        "chi2": np.zeros(0),
        "ll": np.zeros(0),
        "log_ratio": np.zeros(0),
        "log_ratio_ci_low": np.zeros(0),
        "log_ratio_ci_high": np.zeros(0),
        "lrc": np.zeros(0),
        "p_value": np.zeros(0),
        "q_value": np.zeros(0),
        "expected_min": np.zeros(0),
        "low_reliability": np.zeros(0, dtype=bool),
        "bic": np.zeros(0),
        "total_t": int(total_t),
        "total_r": int(total_r),
        "method": method,
        "filtered_token_policy": KEYNESS_ANALYST_TOKEN_POLICY,
    }


async def _run_keyness_docset_job(
    job_id: str,
    *,
    corpus: str | None,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    pos: str | None,
    limit: int,
    min_freq: int = 0,
    reference_source: str = "docset",
) -> None:
    try:
        if reference_source not in {"docset", "whole"}:
            raise ValueError(lt("Ungültige Keyness-Referenz", "Invalid keyness reference"))
        target_doc_ids, reference_doc_ids = normalize_disjoint_docsets(
            target_doc_ids, reference_doc_ids
        )
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=5, message=lt("Dokumentmengen werden vorbereitet", "Preparing document sets"), status="running")
        analysis_jobs.update(job_id, progress=15, message=lt("Target Frequenzen werden gezählt", "Counting target frequencies"))
        # case_fold=True folds each str.casefold class to a single, globally-stable
        # representative id so the union1d(target, reference) alignment below treats
        # die/Die/DIE as ONE keyness candidate in BOTH docsets, not separate rows
        # that re-split the class and inflate the BH-FDR test count
        # (C-casefold-counting-01).
        # Welche Schreibung welchen Anteil traegt. Dritte der drei Flaechen,
        # ueber die der Befund den Leser erreicht (Copilot-Werkzeug, REST-Route,
        # dieser Job). Zwei zu reparieren und die dritte stehen zu lassen waere
        # eine Verschiebung, kein Fix.
        schreibungen_t: dict[int, dict[int, int]] = {}
        schreibungen_r: dict[int, dict[int, int]] = {}
        t_ids, t_counts = await _run_heavy_scan(
            idx.frequency_counts_docset,
            target_doc_ids,
            stopwords=None,
            pos_prefix=pos,
            case_fold=True,
            variants_out=schreibungen_t,
        )
        analysis_jobs.update(job_id, progress=40, message=lt("Reference Frequenzen werden gezählt", "Counting reference frequencies"))
        r_ids, r_counts = await _run_heavy_scan(
            idx.frequency_counts_docset,
            reference_doc_ids,
            stopwords=None,
            pos_prefix=pos,
            case_fold=True,
            variants_out=schreibungen_r,
        )
        if pos:
            total_t = int(t_counts.sum(dtype=np.uint64))
            total_r = int(r_counts.sum(dtype=np.uint64))
        else:
            analysis_jobs.update(job_id, progress=55, message=lt("Tokenmengen werden summiert", "Summing token counts"))
            total_t = int(await asyncio.to_thread(idx.docset_token_count, target_doc_ids))
            total_r = int(await asyncio.to_thread(idx.docset_token_count, reference_doc_ids))
        # F1 statistical provenance (Track T5 #C1): the docset keyness job carries
        # the same `method` block as the synchronous keyness route — identical
        # family string, totals and default sort — so the job-backed path the UI
        # drives is reproducible. Built before the union check so the empty-union
        # early-return also surfaces provenance.
        min_freq = int(min_freq) if min_freq and int(min_freq) > 0 else 0
        keyness_method = build_method_block(
            "keyness",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=int(total_t),
            reference_total=int(total_r),
            sort_key="ll_signed",
            counting_attribute="word",
            extra={"min_freq": int(min_freq), "reference_source": reference_source},
        )
        analysis_jobs.update(job_id, progress=60, message=lt("Vokabularschnittmenge wird gebildet", "Building vocabulary intersection"))
        union_ids = np.union1d(t_ids.astype(np.uint32, copy=False), r_ids.astype(np.uint32, copy=False))
        if union_ids.size == 0:
            analysis_jobs.set_result(
                job_id,
                result=_empty_keyness_docset_result(total_t, total_r, keyness_method),
                total_rows=0,
            )
            return
        analysis_jobs.update(job_id, progress=70, message=lt("Zähler werden ausgerichtet", "Aligning counts"))
        aligned_t = _align_counts_to_union(union_ids, t_ids, t_counts)
        aligned_r = _align_counts_to_union(union_ids, r_ids, r_counts)
        analyst_keep = _analyst_token_mask_for_term_ids(idx, union_ids)
        if not bool(np.all(analyst_keep)):
            union_ids = union_ids[analyst_keep]
            aligned_t = aligned_t[analyst_keep]
            aligned_r = aligned_r[analyst_keep]
        # Use the document-set token totals as denominators for the filtered
        # counts in the UI contrast job.
            if union_ids.size == 0:
                analysis_jobs.set_result(
                    job_id,
                    result=_empty_keyness_docset_result(total_t, total_r, keyness_method),
                    total_rows=0,
                )
                return
        total_t_roh, total_r_roh = int(total_t), int(total_r)
        total_t = int(aligned_t.sum(dtype=np.uint64))
        total_r = int(aligned_r.sum(dtype=np.uint64))
        # Der Methodenblock steht weiter oben, also VOR dieser Korrektur.
        # Er wird nachgezogen, sonst nennt die Antwort eine andere Zahl als
        # die, auf der gerechnet wurde. Genau diese Spaltung ist die
        # Fehlerklasse, die dieses Projekt als hart fuehrt.
        # build_method_block mischt ``extra`` FLACH ein, es gibt kein
        # extra-Feld. Ein extra-Diktat anzulegen haette einen
        # Fremdschluessel erzeugt, den kein Leser erwartet.
        keyness_method["target_total"] = total_t
        keyness_method["reference_total"] = total_r
        keyness_method["target_tokens_roh"] = total_t_roh
        keyness_method["reference_tokens_roh"] = total_r_roh
        # C-keyness-references-02 / C-contract-drift-4 (server half): apply the
        # min_freq reliability floor on the combined target+reference frequency
        # BEFORE the keyness statistics, mirroring the synchronous keyness route
        # and services.tools.keyness.compute_keyness_counts. Dropping untestable
        # singletons here means BH-FDR ``m`` (computed inside keyness_full_stats)
        # counts only candidates that survive the floor — keeping rare singletons
        # would inflate ``m`` and silently shrink every q-value.
        if min_freq > 0:
            keep = (
                aligned_t.astype(np.int64) + aligned_r.astype(np.int64)
            ) >= int(min_freq)
            union_ids = union_ids[keep]
            aligned_t = aligned_t[keep]
            aligned_r = aligned_r[keep]
            if union_ids.size == 0:
                analysis_jobs.set_result(
                    job_id,
                    result=_empty_keyness_docset_result(total_t, total_r, keyness_method),
                    total_rows=0,
                )
                return
        analysis_jobs.update(job_id, progress=80, message=lt("Keyness Scores werden berechnet", "Computing keyness scores"))
        chi2_cell_u, ll_u = await _run_heavy_scan(
            keyness_scores_fast,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
        )
        # Inferential stats (log_ratio + CI, p, BH-FDR q) over the FULL candidate
        # set BEFORE any safe_limit truncation. q depends on the number of tests
        # m: computing it after truncation would shrink m and inflate
        # significance. Shared helper = single source of truth with the
        # synchronous compute_keyness_counts path.
        full_stats = await _run_heavy_scan(
            keyness_full_stats,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
            ll=ll_u,
        )
        # Full 2x2 Pearson chi-square (all four cells), no Yates correction — the
        # proper test statistic (df=1) emitted beside the single-cell chi2_cell.
        # Computed over the FULL candidate set so it can be sliced by `order` like
        # the other arrays. Identical kwargs to the synchronous keyness routes.
        chi2_u = await _run_heavy_scan(
            chi2_2x2_pooled,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
            correction=False,
        )
        # C-keyness-references-03: reliability columns over the FULL candidate
        # union, mirroring services.tools.keyness.compute_keyness_counts so the
        # job-backed docset path carries the same schema as the synchronous and
        # Copilot keyness paths. expected_min = smallest 2x2 expected cell count
        # (pooled marginals); low_reliability flags rows below the E>=5 rule;
        # bic = Wilson's size-robust G^2 - ln(N).
        expected_min_full = expected_min_cell(aligned_t, aligned_r, total_t, total_r)
        low_reliability_full = expected_min_full < RELIABILITY_EXPECTED_MIN
        n_total = float(total_t) + float(total_r)
        bic_full = ll_u - (np.log(n_total) if n_total > 0 else 0.0)
        # Default order: signed log-likelihood descending (over-represented first),
        # with a canonical id tie-break so replay is independent of array order.
        sign_u = _keyness_signed_direction(aligned_t, aligned_r, total_t, total_r)
        order = np.lexsort((union_ids.astype(np.uint64, copy=False), -(ll_u * sign_u)))
        total_candidates = int(order.size)
        safe_limit = _bounded_analysis_job_limit(limit)
        if order.size > safe_limit:
            order = order[:safe_limit]
        term_ids = union_ids[order].astype(np.uint32, copy=False)
        target_counts_u = aligned_t[order]
        reference_counts_u = aligned_r[order]
        chi2_cell_u = chi2_cell_u[order]
        chi2_u = chi2_u[order]
        ll_u = ll_u[order]
        # Slice the full-set stats with the SAME order so each surviving row keeps
        # its q-value computed against the full candidate set.
        log_ratio_u = full_stats["log_ratio"][order]
        log_ratio_ci_low_u = full_stats["log_ratio_ci_low"][order]
        log_ratio_ci_high_u = full_stats["log_ratio_ci_high"][order]
        lrc_u = full_stats["lrc"][order]
        p_value_u = full_stats["p_value"][order]
        q_value_u = full_stats["q_value"][order]
        expected_min_u = expected_min_full[order]
        low_reliability_u = low_reliability_full[order]
        bic_u = bic_full[order]
        analysis_jobs.update(job_id, progress=92, message=lt("Sortiert: {types} Typen", "Sorted: {types} types").format(types=int(term_ids.size)))
        # Nur fuer die Zeilen, die es in die Ausgabe schaffen. Die volle
        # Aufschluesselung ueber alle Kandidaten waere Speicher ohne Leser.
        ueberlebende = set(term_ids.tolist())
        result = {
            "term_ids": term_ids.astype(np.uint32, copy=False),
            "surface_variants_target": {
                k: v for k, v in schreibungen_t.items() if k in ueberlebende
            },
            "surface_variants_reference": {
                k: v for k, v in schreibungen_r.items() if k in ueberlebende
            },
            "target_counts": target_counts_u.astype(np.uint64, copy=False),
            "reference_counts": reference_counts_u.astype(np.uint64, copy=False),
            "chi2_cell": chi2_cell_u.astype(np.float64, copy=False),
            "chi2": chi2_u.astype(np.float64, copy=False),
            "ll": ll_u.astype(np.float64, copy=False),
            "log_ratio": log_ratio_u.astype(np.float64, copy=False),
            "log_ratio_ci_low": log_ratio_ci_low_u.astype(np.float64, copy=False),
            "log_ratio_ci_high": log_ratio_ci_high_u.astype(np.float64, copy=False),
            "lrc": lrc_u.astype(np.float64, copy=False),
            "p_value": p_value_u.astype(np.float64, copy=False),
            "q_value": q_value_u.astype(np.float64, copy=False),
            "expected_min": expected_min_u.astype(np.float64, copy=False),
            "low_reliability": low_reliability_u.astype(bool, copy=False),
            "bic": bic_u.astype(np.float64, copy=False),
            "total_t": total_t,
            "total_r": total_r,
            "pos": pos or "",
            "method": keyness_method,
            "filtered_token_policy": KEYNESS_ANALYST_TOKEN_POLICY,
            "row_limit": int(safe_limit),
            "total_candidates": int(total_candidates),
            "truncated": bool(total_candidates > safe_limit),
        }
        analysis_jobs.set_result(job_id, result=result, total_rows=int(term_ids.size))
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Keyness Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


def _sanitize_float(value: Any) -> Any:
    """Map a non-finite float to None so JSON serialization never emits NaN/Inf.

    Covers Python ``float`` AND numpy floating scalars (np.float32 is NOT a
    subclass of ``float``, so the bare ``isinstance(value, float)`` check missed
    it). Default JSONResponse emits ``NaN``/``Infinity`` — invalid JSON that
    breaks strict clients; even orjson raises on non-finite. Sanitizing at the
    cell level keeps the analysis surface from 500-ing on a non-finite stat.
    """
    if isinstance(value, (float, np.floating)):
        try:
            if not math.isfinite(float(value)):
                return None
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
    return value


def _split_collocate_terms(raw: str) -> list[str]:
    value = (raw or "").strip()
    if not value:
        return []
    parts: list[str] = []
    current = ""
    escaped = False
    for ch in value:
        if escaped:
            current += ch
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            trimmed = current.strip()
            if trimmed:
                parts.append(trimmed)
            current = ""
            continue
        current += ch
    trimmed = current.strip()
    if trimmed:
        parts.append(trimmed)
    uniq: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = part.replace("\\|", "|").replace("\\\\", "\\")
        if part in seen:
            continue
        seen.add(part)
        uniq.append(part)
    return uniq


def _split_outside_quotes(text: str) -> list[str]:
    parts: list[str] = []
    current = ""
    in_quotes = False
    escaped = False
    for ch in text:
        if escaped:
            current += ch
            escaped = False
            continue
        if ch == "\\":
            current += ch
            escaped = True
            continue
        if ch == "\"":
            current += ch
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            parts.append(current)
            current = ""
            continue
        current += ch
    if current:
        parts.append(current)
    return parts


def _unescape_value(value: str) -> str:
    out = ""
    escaped = False
    for ch in value:
        if escaped:
            out += ch
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        out += ch
    return out


def _parse_co_kwic_query(raw: str) -> dict[str, Any] | None:
    trimmed = (raw or "").strip()
    if not trimmed.lower().startswith("co(") or not trimmed.endswith(")"):
        return None
    inside = trimmed[trimmed.find("(") + 1 : -1].strip()
    if not inside:
        return None
    parts = _split_outside_quotes(inside)
    values: dict[str, str] = {}
    for part in parts:
        idx = part.find("=")
        if idx == -1:
            continue
        key = part[:idx].strip().lower()
        val = part[idx + 1 :].strip()
        if not key or not val:
            continue
        values[key] = val

    term_raw = values.get("term")
    collocate_raw = values.get("collocate") or values.get("collocates")
    if not term_raw or not collocate_raw:
        return None

    term = term_raw
    if term.startswith("\"") and term.endswith("\""):
        term = _unescape_value(term[1:-1])

    collocate_value = collocate_raw
    if collocate_value.startswith("\"") and collocate_value.endswith("\""):
        collocate_value = collocate_value[1:-1]

    collocates: list[str] = []
    current = ""
    escaped = False
    for ch in collocate_value:
        if escaped:
            current += ch
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "|":
            trimmed = _unescape_value(current).strip()
            if trimmed:
                collocates.append(trimmed)
            current = ""
            continue
        current += ch
    last = _unescape_value(current).strip()
    if last:
        collocates.append(last)

    window_raw = values.get("window") or values.get("w") or ""
    try:
        window_num = int(window_raw)
    except Exception:
        window_num = 5
    window = window_num if window_num > 0 else 5

    within_raw = values.get("within_sentence") or values.get("within") or values.get("withinsentence") or ""
    if within_raw == "":
        within_sentence = True
    else:
        within_sentence = within_raw.strip().lower() in {"1", "true", "yes"}

    attribute_raw = (values.get("attribute") or values.get("attr") or "").strip().strip("\"").lower()
    attribute = "lemma" if attribute_raw == "lemma" else "word"

    uniq = list(dict.fromkeys([c for c in collocates if c.strip()]))
    if not term.strip() or not uniq:
        return None
    return {
        "term": term.strip(),
        "collocates": uniq,
        "window": window,
        "within_sentence": within_sentence,
        "attribute": attribute,
    }


def _co_occurrence_positions(
    idx: CorpusIndex,
    *,
    term: str,
    collocates: list[str],
    window: int,
    within_sentence: bool,
    docset_mask: np.ndarray | None = None,
    attribute: str = "word",
) -> np.ndarray:
    """Node hits of a ``co(...)`` term, the same rows as the collocation back path."""
    from candyconc.services.backend.co_occurrence import co_occurrence

    if int(idx.fast_index.token_store.token_count) <= 0:
        return np.zeros(0, dtype=np.uint32)
    window = max(1, min(int(window), 50))
    doc_bounds = _doc_bounds_for_index(idx) if docset_mask is not None else None
    co = co_occurrence(
        idx,
        term,
        list(collocates),
        window=window,
        within_sentence=bool(within_sentence),
        attribute=attribute,
        docset_mask=docset_mask,
        doc_bounds=doc_bounds,
        match_limit=_ANALYSIS_MATCH_LIMIT,
    )
    return co.rows.astype(np.uint32, copy=False)


def _resolve_term_anchor_positions(
    idx: CorpusIndex,
    term: str,
    *,
    within_sentence: bool,
) -> tuple[np.ndarray, np.ndarray]:
    term_str = (term or "").strip()
    # Key on the rebuild-aware corpus signature, not the raw path string: an
    # in-place rebuild (same path, new content) must invalidate cached anchors.
    cache_key = (
        _corpus_cache_signature(idx.fast_index, str(idx.fast_index.index_path)),
        term_str,
        bool(within_sentence),
    )
    cached = _anchor_positions_cache_get(cache_key)
    if cached is not None:
        return cached
    if not term_str:
        empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64))
        _anchor_positions_cache_set(cache_key, empty[0], empty[1])
        return empty
    if term_str.lower().startswith("cql:"):
        q = term_str[4:].strip()
        if not q:
            empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64))
            _anchor_positions_cache_set(cache_key, empty[0], empty[1])
            return empty
        from candyconc.core.query_runtime import _resolve_cql_match_arrays

        positions, fixed_match_len, spans, _positions_are_full = _resolve_cql_match_arrays(
            idx,
            q,
            max_matches=2_000_000_000,
            use_cache=True,
            allow_cache_fallback=False,
            exhaustive=True,
            progress_cb=None,
        )
        if positions.size == 0:
            empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64))
            _anchor_positions_cache_set(cache_key, empty[0], empty[1])
            return empty
        if fixed_match_len is not None:
            spans = np.full(positions.shape[0], int(fixed_match_len), dtype=np.int64)
        elif spans is None:
            spans = np.ones(positions.shape[0], dtype=np.int64)
        out = (positions.astype(np.uint32, copy=False), spans.astype(np.int64, copy=False))
        _anchor_positions_cache_set(cache_key, out[0], out[1])
        return out
    # The contrast node resolves like the collocation table: the lower-case
    # class of the word. The exact form would miss every capitalised hit,
    # while the method block states lowercase_class.
    positions = _plain_term_positions_casefolded(idx, term_str)
    if positions.size == 0:
        empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64))
        _anchor_positions_cache_set(cache_key, empty[0], empty[1])
        return empty
    spans = np.ones(positions.shape[0], dtype=np.int64)
    out = (positions.astype(np.uint32, copy=False), spans)
    _anchor_positions_cache_set(cache_key, out[0], out[1])
    return out




def _collocate_counts_for_anchors(
    engine: Any,
    anchors: np.ndarray,
    spans: np.ndarray,
    *,
    window: int,
    within_sentence: bool,
) -> tuple[dict[int, int], int, int]:
    from candyconc.core.counting_kernels import count_collocates

    segments = _collocate_segments_for_anchors(
        engine,
        anchors,
        spans,
        window=window,
        within_sentence=within_sentence,
    )
    if segments.match_count == 0 or segments.context_mass <= 0 or engine.token_store is None:
        return {}, segments.match_count, segments.context_mass

    counts = count_collocates(
        engine.token_store,
        segments.seg_starts,
        segments.seg_ends,
        segments.seg_weights,
        stoplist=None,
        attr="word",
        top_n=None,
    )
    return counts, segments.match_count, segments.context_mass


def _collocation_score_spec(sort_by: str | None) -> tuple[str, int]:
    key = (sort_by or "").strip().lower()
    if key == "mi2":
        raise ValueError(
            lt("Sortiermaß 'mi2' wurde durch 'chi2_cell' ersetzt.", "Sort measure 'mi2' has been replaced by 'chi2_cell'.")
        )
    mapping = {
        "f": ("f", 1),
        "mi": ("mi", 3),
        "lmi": ("lmi", 4),
        "npmi": ("npmi", 5),
        "z": ("z", 6),
        "chi2_cell": ("chi2_cell", 7),
        "t": ("t", 8),
        "ll": ("ll", 9),
        "dice": ("dice", 10),
        "logdice": ("logdice", 10),
    }
    return mapping.get(key, ("dice", 10))


def _use_dense_collocate_diff_counter(vocab_size: int) -> bool:
    if vocab_size <= 0:
        return False
    # Zwei uint64-Zähler + Seen-Byte + Touched-IDs pro Typ.
    estimated_bytes = (int(vocab_size) + 1) * (8 + 8 + 1 + 4)
    return estimated_bytes <= (64 * 1024 * 1024)


def _collocates_diff_basis_cache_key(
    idx: CorpusIndex,
    term: str,
    *,
    window: int,
    within_sentence: bool,
    target_docset_key: str,
    reference_docset_key: str,
) -> str:
    term_digest = hashlib.sha1((term or "").encode("utf-8")).hexdigest()[:16]
    return (
        f"{idx.fast_index.index_path.name}:term={term_digest}:w={int(window)}:"
        f"s={int(within_sentence)}:t={target_docset_key}:r={reference_docset_key}:v3"
    )


def _collocates_diff_rows_from_basis(
    engine: Any,
    lex: Any,
    basis: Any,
    *,
    term: str,
    sort_by: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    safe_limit = _bounded_analysis_job_limit(limit)
    score_name, _ = _collocation_score_spec(sort_by)
    if basis.word_ids.size == 0:
        return [], _bounded_result_meta(row_limit=safe_limit, total_candidates=0)

    # With pair_semantics=False, O11 counts the union of token positions.
    # Use corpus frequency f(v) and corpus token count N as the column
    # marginal and total, following Evert 2004, Fig. 2.13. Multiplying either
    # by the anchor count m would mix token counts with token-pair counts.
    #
    # Normalize target and reference rates per million corpus tokens so
    # diff_per_million compares quantities with the same unit.
    target_event_total = int(basis.target_token_total)
    reference_event_total = int(basis.reference_token_total)
    target_event_mass = np.asarray(basis.target_freqs, dtype=np.float64)
    reference_event_mass = np.asarray(basis.reference_freqs, dtype=np.float64)

    if target_event_total > 0 and basis.target_context_mass > 0:
        target_expected = (basis.target_context_mass * target_event_mass) / float(target_event_total)
    else:
        target_expected = np.zeros(basis.word_ids.size, dtype=np.float64)
    if reference_event_total > 0 and basis.reference_context_mass > 0:
        reference_expected = (basis.reference_context_mass * reference_event_mass) / float(reference_event_total)
    else:
        reference_expected = np.zeros(basis.word_ids.size, dtype=np.float64)

    target_scores = engine._calculate_selected_score_array(
        basis.target_observed,
        target_expected,
        target_event_mass,
        context_mass=basis.target_context_mass,
        event_total=target_event_total,
        score_key=score_name,
        # f(u) je Seite: die Trefferzahl des Knotens IN DIESEM Teilkorpus.
        # Ohne sie kann die Spalte logdice Rychly nicht rechnen und faellt
        # nicht mehr still auf die Fensterformel zurueck.
        node_frequency=float(basis.target_match_count),
    ).astype(np.float64, copy=False)
    reference_scores = engine._calculate_selected_score_array(
        basis.reference_observed,
        reference_expected,
        reference_event_mass,
        context_mass=basis.reference_context_mass,
        event_total=reference_event_total,
        score_key=score_name,
        node_frequency=float(basis.reference_match_count),
    ).astype(np.float64, copy=False)

    if target_event_total > 0:
        target_per_million = (basis.target_observed * 1_000_000.0) / float(target_event_total)
    else:
        target_per_million = np.zeros(basis.word_ids.size, dtype=np.float64)
    if reference_event_total > 0:
        reference_per_million = (basis.reference_observed * 1_000_000.0) / float(reference_event_total)
    else:
        reference_per_million = np.zeros(basis.word_ids.size, dtype=np.float64)

    diff_per_million = target_per_million - reference_per_million
    diff_score = target_scores - reference_scores
    diff_abs = np.abs(diff_per_million)
    # Log ratio of the two co-occurrence rates with +0.5 in both cells, the
    # effect size the contrast table shows next to the per-million columns
    # (without it in the rows the column stays empty).
    t_obs = np.asarray(basis.target_observed, dtype=np.float64)
    r_obs = np.asarray(basis.reference_observed, dtype=np.float64)
    if target_event_total > 0 and reference_event_total > 0:
        log_ratio = np.log2(
            ((t_obs + 0.5) / float(target_event_total))
            / ((r_obs + 0.5) / float(reference_event_total))
        )
    else:
        log_ratio = np.zeros(basis.word_ids.size, dtype=np.float64)
    one_sided = (t_obs == 0) != (r_obs == 0)

    # The node is excluded via str.lower, the same comparison as its
    # resolution. With casefold, "daß" would also exclude the collocate
    # "dass".
    excluded_words: set[str] = set()
    term_str = (term or "").strip()
    if term_str.lower().startswith("cql:"):
        simple = _extract_simple_cql_token(term_str)
        if simple:
            excluded_words.add(simple.lower())
    elif term_str:
        excluded_words.add(term_str.lower())

    # The analyst-token and node-term filters define the candidate population.
    # Apply them to the COMPLETE union before selecting the top-N. A former
    # ``top_n * 2`` shortcut filtered only a preselected window; enough
    # punctuation/markup rows could therefore hide valid collocates altogether.
    # Decode in bounded chunks so a large vocabulary never requires a second
    # full string array in memory, while the ranking remains exact.
    word_ids = np.asarray(basis.word_ids, dtype=np.uint32)
    eligible_parts: list[np.ndarray] = []
    chunk_size = 65_536
    for start in range(0, int(word_ids.size), chunk_size):
        stop = min(int(word_ids.size), start + chunk_size)
        chunk_ids = word_ids[start:stop]
        chunk_words = lex.get_strings_for_ids(chunk_ids)
        keep = np.fromiter(
            (
                bool(clean := str(word or "").strip())
                and clean.lower() not in excluded_words
                and is_analyst_token(clean)
                for word in chunk_words
            ),
            dtype=np.bool_,
            count=int(chunk_ids.size),
        )
        if np.any(keep):
            eligible_parts.append(np.flatnonzero(keep).astype(np.int64, copy=False) + start)
    if not eligible_parts:
        return [], _bounded_result_meta(row_limit=safe_limit, total_candidates=0)
    eligible = np.concatenate(eligible_parts)
    meta = _bounded_result_meta(
        row_limit=safe_limit,
        total_candidates=int(eligible.size),
    )

    # Select exactly by absolute normalized difference. ``argpartition`` finds
    # the global threshold in O(V); ties at the threshold are broken by stable
    # term id, then only the selected top-N is ordered for output.
    eligible_abs = diff_abs[eligible]
    if eligible.size > safe_limit:
        cutoff_index = int(eligible_abs.size) - safe_limit
        cutoff = float(np.partition(eligible_abs, cutoff_index)[cutoff_index])
        greater = eligible[eligible_abs > cutoff]
        equal = eligible[eligible_abs == cutoff]
        remaining = safe_limit - int(greater.size)
        if equal.size > remaining:
            equal_ids = word_ids[equal]
            equal = equal[np.argpartition(equal_ids, remaining - 1)[:remaining]]
        selected = np.concatenate((greater, equal))
    else:
        selected = eligible
    order = selected[np.lexsort((word_ids[selected], -diff_abs[selected]))]

    candidate_ids = word_ids[order].astype(np.uint32, copy=False)
    candidate_words = lex.get_strings_for_ids(candidate_ids)
    rows: list[dict[str, Any]] = []
    for local_idx, word in enumerate(candidate_words):
        clean_word = str(word or "").strip()
        idx_pos = int(order[local_idx])
        rows.append(
            {
                "word": clean_word,
                "target_freq": int(basis.target_observed[idx_pos]),
                "reference_freq": int(basis.reference_observed[idx_pos]),
                "target_score": float(target_scores[idx_pos]),
                "reference_score": float(reference_scores[idx_pos]),
                "target_per_million": float(target_per_million[idx_pos]),
                "reference_per_million": float(reference_per_million[idx_pos]),
                "diff_score": float(diff_score[idx_pos]),
                "diff_per_million": float(diff_per_million[idx_pos]),
                "diff_abs": float(diff_abs[idx_pos]),
                "log_ratio": float(log_ratio[idx_pos]),
                "one_sided": bool(one_sided[idx_pos]),
                "score_key": score_name,
            }
        )
    return rows, meta


def _collocates_diff_rows_for_term(
    idx: CorpusIndex,
    term: str,
    *,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    target_docset_key: str,
    reference_docset_key: str,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    limit: int,
    return_meta: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
    from candyconc.core.collocation_engine import (
        CollocationDiffBasis,
        CollocationEngine,
        get_engine,
    )
    from candyconc.core.counting_kernels import (
        count_hashmap_svb_dual,
        count_hashmap_svb_dual_dense,
        build_dual_basis_arrays_fast,
        gather_u64_to_f64_fast,
    )
    from candyconc.core.fast_index_native import docset_mask_from_ids

    safe_limit = _bounded_analysis_job_limit(limit)
    empty_meta = _bounded_result_meta(row_limit=safe_limit, total_candidates=0)

    def _empty_result() -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        return ([], empty_meta) if return_meta else []

    anchors, spans = _resolve_term_anchor_positions(idx, term, within_sentence=within_sentence)
    if anchors.size == 0:
        return _empty_result()

    engine = get_engine(idx.fast_index.index_path)
    engine.load()
    lex = engine._get_lexicon("word")
    if engine.token_store is None or lex is None:
        return _empty_result()

    doc_bounds = _doc_bounds_for_index(idx)
    total_docs = int(doc_bounds.size)
    if total_docs <= 0:
        return _empty_result()

    target_ids = np.asarray(target_doc_ids, dtype=np.uint32)
    reference_ids = np.asarray(reference_doc_ids, dtype=np.uint32)
    target_docset_mask = docset_mask_from_ids(target_ids, total_docs)
    reference_docset_mask = docset_mask_from_ids(reference_ids, total_docs)
    basis_cache_key = _collocates_diff_basis_cache_key(
        idx,
        term,
        window=window,
        within_sentence=within_sentence,
        target_docset_key=target_docset_key,
        reference_docset_key=reference_docset_key,
    )
    basis = engine.get_diff_basis(basis_cache_key)
    if basis is not None:
        rows, meta = _collocates_diff_rows_from_basis(
            engine,
            lex,
            basis,
            term=term,
            sort_by=sort_by,
            limit=safe_limit,
        )
        return (rows, meta) if return_meta else rows

    # Shared contrast substrate (same front-end as compare_by_docset_masks).
    valid_anchor_mask, target_anchor_mask, reference_anchor_mask = (
        CollocationEngine.split_anchor_positions_by_doc_masks(
            anchors, doc_bounds, target_docset_mask, reference_docset_mask
        )
    )
    if not np.any(valid_anchor_mask):
        return _empty_result()
    anchors = anchors[valid_anchor_mask]
    spans = spans[valid_anchor_mask]
    target_anchors = anchors[target_anchor_mask]
    target_spans = spans[target_anchor_mask]
    reference_anchors = anchors[reference_anchor_mask]
    reference_spans = spans[reference_anchor_mask]

    target_segments = _collocate_segments_for_anchors(
        engine,
        target_anchors,
        target_spans,
        window=window,
        within_sentence=within_sentence,
        clip_to_document=True,
    )
    reference_segments = _collocate_segments_for_anchors(
        engine,
        reference_anchors,
        reference_spans,
        window=window,
        within_sentence=within_sentence,
        clip_to_document=True,
    )
    if target_segments.match_count == 0 and reference_segments.match_count == 0:
        return _empty_result()

    use_dense_counter = _use_dense_collocate_diff_counter(int(lex.vocab_size))
    if use_dense_counter:
        union_ids, target_observed, reference_observed = count_hashmap_svb_dual_dense(
            engine.token_store,
            "word",
            target_segments.seg_starts,
            target_segments.seg_ends,
            target_segments.seg_weights,
            reference_segments.seg_starts,
            reference_segments.seg_ends,
            reference_segments.seg_weights,
            int(lex.vocab_size),
            {0},
        )
    else:
        target_counts, reference_counts = count_hashmap_svb_dual(
            engine.token_store,
            "word",
            target_segments.seg_starts,
            target_segments.seg_ends,
            target_segments.seg_weights,
            reference_segments.seg_starts,
            reference_segments.seg_ends,
            reference_segments.seg_weights,
            {0},
        )
    target_freqs_dense, target_token_total = engine._docset_word_counts_dense(
        target_docset_mask,
        attr="word",
        cache_key=target_docset_key,
    )
    reference_freqs_dense, reference_token_total = engine._docset_word_counts_dense(
        reference_docset_mask,
        attr="word",
        cache_key=reference_docset_key,
    )

    if use_dense_counter:
        if union_ids.size == 0:
            return _empty_result()
    else:
        union_ids, target_observed, reference_observed, _, _ = build_dual_basis_arrays_fast(
            target_counts,
            reference_counts,
            {},
            {},
        )
        if union_ids.size == 0:
            return _empty_result()
    target_freq_arr = gather_u64_to_f64_fast(target_freqs_dense, union_ids)
    reference_freq_arr = gather_u64_to_f64_fast(reference_freqs_dense, union_ids)

    basis = CollocationDiffBasis(
        word_ids=union_ids.astype(np.uint32, copy=False),
        target_observed=np.asarray(target_observed, dtype=np.float64),
        reference_observed=np.asarray(reference_observed, dtype=np.float64),
        target_freqs=target_freq_arr,
        reference_freqs=reference_freq_arr,
        target_match_count=target_segments.match_count,
        reference_match_count=reference_segments.match_count,
        target_context_mass=target_segments.context_mass,
        reference_context_mass=reference_segments.context_mass,
        target_token_total=target_token_total,
        reference_token_total=reference_token_total,
    )
    engine.set_diff_basis(basis_cache_key, basis)
    rows, meta = _collocates_diff_rows_from_basis(
        engine,
        lex,
        basis,
        term=term,
        sort_by=sort_by,
        limit=safe_limit,
    )
    return (rows, meta) if return_meta else rows


def _collocate_stats_for_term(
    idx: CorpusIndex,
    term: str,
    *,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    doc_ids: np.ndarray | None,
    min_count: int | None = None,
) -> Any:
    """Collocate frame for ``term`` — the ONE server-side builder seam.

    ``min_count`` (H9/V10) is handed down to the shared tools builder on the
    plain-word path, so an explicit REST ``min_freq`` reaches the candidate
    builder itself (byte-identical to the copilot tool) instead of only acting
    as a post-filter. The ``cql:`` path (H10/H6) runs through the SAME
    adaptive resolver: the node frequency is the (docset-scoped) anchor count
    and ``min_count`` reaches ``_collocate_stats_from_positions`` unclamped,
    so REST and copilot agree on explicit floors AND on auto calibration.
    """
    import pandas as pd

    term_str = (term or "").strip()
    if not term_str:
        return pd.DataFrame()

    if term_str.lower().startswith("cql:"):
        q = term_str[4:].strip()
        if not q:
            return pd.DataFrame()
        from candyconc.analysis_defaults import adaptive_collocate_min_freq
        from candyconc.core.cql_engine import search_cql_matches_backend

        def _empty_cql_frame() -> Any:
            # For zero anchors, disclose the floor calibration as the tools cql:
            # branch does for empty matches.
            frame = pd.DataFrame()
            frame.attrs["node_frequency"] = 0
            frame.attrs["effective_min_count"] = int(
                adaptive_collocate_min_freq(0, min_count or None)
            )
            frame.attrs["min_count_mode"] = (
                "requested" if (min_count or 0) > 0 else "adaptive"
            )
            return frame

        matches = search_cql_matches_backend(
            idx.fast_index,
            q,
            limit=_ANALYSIS_MATCH_LIMIT,
            within_sentences_by_default=within_sentence,
        )
        if not matches:
            return _empty_cql_frame()
        positions = np.array([m.start for m in matches], dtype=np.uint32)
        spans = np.array(
            [
                max(1, int(getattr(m, "end", int(m.start) + 1)) - int(m.start))
                for m in matches
            ],
            dtype=np.int64,
        )
        if positions.size > 1:
            order = np.argsort(positions, kind="mergesort")
            positions = positions[order]
            spans = spans[order]
        if doc_ids is not None:
            doc_bounds = _doc_bounds_for_index(idx)
            doc_ids = np.asarray(doc_ids, dtype=np.uint32)
            if doc_ids.size == 0:
                return pd.DataFrame()
            docset_mask = docset_mask_from_ids(doc_ids, int(doc_bounds.size))
            positions, spans = filter_positions_and_values_by_docset_fast(
                positions,
                spans,
                doc_bounds,
                docset_mask,
            )
        if positions.size == 0:
            return _empty_cql_frame()
        df = _collocate_stats_from_positions(
            idx,
            positions,
            spans,
            window=window,
            within_sentence=within_sentence,
            sort_by=sort_by,
            doc_ids=doc_ids,
            # Pass the explicit floor through. None selects automatic calibration
            # from the anchor count in the shared adaptive resolver.
            min_count=min_count,
        )
        normalized = _normalize_collocate_frame(df, term_str, None, sort_by)
        # Preserve the builder's floor disclosure (node_frequency /
        # effective_min_count / min_count_mode) across the normalizer, exactly
        # like the plain-word branch below.
        try:
            normalized.attrs.update(dict(getattr(df, "attrs", {}) or {}))
        except Exception:
            pass
        return normalized

    df = _collocate_stats(
        term_str,
        window=window,
        corpus=idx,
        doc_ids=doc_ids,
        within_sentence=within_sentence,
        sort_by=sort_by,
        min_count=min_count,
    )
    if df is None or df.empty:
        return df
    normalized = _normalize_collocate_frame(df, term_str, None, sort_by)
    # Preserve the builder's floor disclosure (node_frequency /
    # effective_min_count / min_count_mode): the routes read it AFTER this
    # seam, and pandas ops inside the normalizer may drop ``attrs``.
    try:
        normalized.attrs.update(dict(getattr(df, "attrs", {}) or {}))
    except Exception:
        pass
    return normalized


def _plain_term_positions_casefolded(idx: CorpusIndex, term: str) -> np.ndarray:
    """Use the public plain-search casefold contract for co-occurrence paths."""
    lookup = getattr(idx, "term_positions", None)
    if callable(lookup):
        try:
            return lookup(term, case_insensitive=True).astype(np.uint32, copy=False)
        except TypeError:
            # Narrow index doubles from older tests may only implement the
            # underlying exact lookup. Production CorpusIndex always takes the
            # explicit case-insensitive argument above.
            pass
    return idx.fast_index.term_positions(term, attr="word").astype(np.uint32, copy=False)


def _co_anchor_positions(
    idx: CorpusIndex,
    term: str,
    collocate: str,
    *,
    window: int,
    within_sentence: bool,
    doc_ids: np.ndarray | None,
    attribute: str = "word",
) -> tuple[np.ndarray, np.ndarray]:
    """Node hits (starts, spans) with ``collocate`` in their window.

    Shares the window and resolution rules of the collocation back path
    (``co_occurrence``), so an anchored collocate job, the Co-KWIC and a
    ``co(...)`` term select the same node hits.
    """
    from candyconc.services.backend.co_occurrence import co_occurrence

    term = (term or "").strip()
    collocates = _split_collocate_terms(collocate or "")
    empty = (np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64))
    if not term or not collocates:
        return empty
    if int(idx.fast_index.token_store.token_count) <= 0:
        return empty
    window = max(1, min(int(window), 50))
    docset_mask = None
    doc_bounds = None
    if doc_ids is not None:
        doc_ids = np.asarray(doc_ids, dtype=np.uint32)
        if doc_ids.size == 0:
            return empty
        doc_bounds = _doc_bounds_for_index(idx)
        docset_mask = docset_mask_from_ids(doc_ids, int(doc_bounds.size))
    co = co_occurrence(
        idx,
        term,
        collocates,
        window=window,
        within_sentence=bool(within_sentence),
        attribute=attribute,
        docset_mask=docset_mask,
        doc_bounds=doc_bounds,
        match_limit=_ANALYSIS_MATCH_LIMIT,
    )
    return co.rows.astype(np.uint32, copy=False), co.row_spans.astype(np.int64, copy=False)


def _collocate_stats_from_co_anchors(
    idx: CorpusIndex,
    term: str,
    collocate: str,
    *,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    doc_ids: np.ndarray | None,
) -> Any:
    from candyconc.core.collocation_engine import get_engine
    from candyconc.core.coverage_sweep import coverage_sweep_arrays, total_context_mass_arrays
    from candyconc.core.counting_kernels import count_collocates
    from candyconc.core.fast_index_native import docset_mask_from_ids
    import pandas as pd

    anchors, spans = _co_anchor_positions(
        idx,
        term,
        collocate,
        window=window,
        within_sentence=within_sentence,
        doc_ids=doc_ids,
    )
    if anchors.size == 0:
        return pd.DataFrame()

    engine = get_engine(idx.fast_index.index_path)
    engine.load()
    lex = engine._get_lexicon("word")
    if engine.token_store is None:
        return pd.DataFrame()

    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors=anchors.astype(np.int64, copy=False),
        spans=spans.astype(np.int64, copy=False),
        window_left=int(window),
        window_right=int(window),
        # ALWAYS pass document boundaries (mirrors the engine collocate_stats
        # fix): otherwise the REST cql collocation path bled collocates across
        # document edges when within_sentence=False and no docset was set.
        boundaries=engine.boundaries,
        within_sentence=within_sentence,
        total_tokens=int(engine.token_store.token_count),
    )
    u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
    counts = count_collocates(
        engine.token_store,
        seg_starts,
        seg_ends,
        seg_weights,
        stoplist=None,
        attr="word",
        top_n=None,
    )
    if u <= 0:
        return pd.DataFrame()
    freqs_override = None
    freqs_override_arr = None
    total_tokens_override = None
    if doc_ids is not None:
        try:
            doc_bounds = (
                engine.boundaries.document._positions
                if engine.boundaries and engine.boundaries.document
                else None
            )
            if doc_bounds is None or doc_bounds.size <= 0:
                raise RuntimeError(
                    lt(
                        "Dokumentgrenzen fehlen für docset-lokale Kollokationsfrequenzen.",
                        "Document boundaries are missing for collocation frequencies local to the document set.",
                    )
                )
            ids = np.asarray(doc_ids, dtype=np.uint32)
            docset_mask = docset_mask_from_ids(ids, int(doc_bounds.size))
            freqs_override_arr, total_tokens_override = engine._docset_word_counts_dense(
                docset_mask, attr="word"
            )
        except Exception as exc:
            logger.exception(
                "Docset-Frequenzen konnten nicht berechnet werden; "
                "Kollokationen brechen fail-closed ab."
            )
            raise RuntimeError(
                lt(
                    "Docset-Frequenzen konnten nicht berechnet werden. "
                    "Kollokationswerte werden nicht mit globalen Korpusfrequenzen "
                    "als scheinbar docset-lokale Evidenz ausgegeben.",
                    "Document set frequencies could not be computed. "
                    "Collocation values are not reported with global corpus frequencies "
                    "as if they were evidence local to the document set.",
                )
            ) from exc
    arrays = engine._calculate_statistics_arrays(
        counts,
        int(anchors.size),
        int(u),
        lex,
        freqs_override=freqs_override,
        freqs_override_arr=freqs_override_arr,
        total_tokens_override=total_tokens_override,
    )
    if arrays[0].size == 0:
        return pd.DataFrame()
    sorted_arrays = engine._sort_statistics_arrays(*arrays, top_n=None)
    df = engine._statistics_frame_from_sorted(
        *sorted_arrays, lex=lex, node_frequency=int(anchors.size),
        context_mass=float(u),
        scope_tokens=float(total_tokens_override or engine.lexicons.total_tokens),
        freqs_override=freqs_override,
        freqs_override_arr=freqs_override_arr)
    if df.empty:
        return df
    # Canonical collocate-frame normalization preserves delta_p_nc,
    # delta_p_cn, lmi, npmi, z, logdice and chi2_cell for co-anchor results
    # and keeps those columns available for rendering and sorting.
    collocate_terms = _split_collocate_terms(collocate or "")
    return _normalize_collocate_frame(df, term, collocate_terms, sort_by)


async def _run_collocates_job(
    job_id: str,
    *,
    corpus: str | None,
    term: str,
    collocate: str | None,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    doc_ids: np.ndarray,
    limit: int,
    min_freq: int = 0,
) -> None:
    try:
        analysis_jobs.update(
            job_id,
            progress=5,
            message=lt("Dokumentmenge wird vorbereitet", "Preparing document set"),
            status="running",
        )
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=25, message=lt("Kollokationen werden berechnet", "Computing collocations"))
        min_freq_value = int(min_freq) if min_freq and int(min_freq) > 0 else 0
        if collocate:
            df = await _run_heavy_scan(
                _collocate_stats_from_co_anchors,
                idx,
                term,
                collocate,
                window=window,
                within_sentence=within_sentence,
                sort_by=sort_by,
                doc_ids=doc_ids,
            )
        else:
            # Pass explicit min_freq to the candidate builder as in the synchronous
            # route, so the UI job returns the same row set.
            df = await _run_heavy_scan(
                _collocate_stats_for_term,
                idx,
                term,
                window=window,
                within_sentence=within_sentence,
                sort_by=sort_by,
                doc_ids=doc_ids,
                min_count=(min_freq_value or None),
            )
        # Read the adaptive-floor disclosure before normalization can rebuild
        # the frame and drop its attrs. Preserve the same node-frequency
        # calibration as the synchronous collocates route.
        frame_attrs = dict(getattr(df, "attrs", {}) or {})
        node_freq = frame_attrs.get("node_frequency")
        builder_floor = frame_attrs.get("effective_min_count")
        df = normalize_default_collocate_frame(df, sort_by)
        desired_floor = adaptive_collocate_min_freq(node_freq, min_freq_value or None)
        if builder_floor is None:
            builder_floor = (
                int(analysis_routes.COLLOCATE_COOCCURRENCE_FLOOR)
                if node_freq is None
                else int(desired_floor)
            )
        effective_min_freq = max(int(desired_floor), int(builder_floor))
        # Use analysis_defaults.collocate_floor_mode for all three producers.
        floor_mode = collocate_floor_mode(
            min_freq_value, effective_min_freq, node_freq
        )
        df = filter_collocate_frame_by_min_freq(df, effective_min_freq)
        safe_limit = _bounded_analysis_job_limit(limit)
        try:
            total_candidates = int(len(df))
        except TypeError:
            total_candidates = 0
        rows = _rows_from_frame_page(df, offset=0, limit=safe_limit)
        if total_candidates <= 0:
            total_candidates = len(rows)
        rows = [{k: _sanitize_float(v) for k, v in row.items()} for row in rows]
        # F1 statistical provenance (Track T5 #C1): the plain collocates job mirrors
        # the contrast/ngrams-diff runners so the job-backed path the UI drives carries
        # the same `method` block as the synchronous collocates route.
        try:
            scope_total = int(await asyncio.to_thread(idx.docset_token_count, doc_ids))
        except Exception:
            scope_total = 0
        floor = int(analysis_routes.COLLOCATE_COOCCURRENCE_FLOOR)
        method = build_method_block(
            "collocates",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=scope_total or None,
            window=int(window),
            within_sentence=bool(within_sentence),
            sort_key=(sort_by or "").strip().lower() or None,
            extra=collocation_method_extra({
                "cooccurrence_floor": floor,
                "min_freq": int(min_freq_value),
                "effective_min_cooccurrence": int(effective_min_freq),
                "floor_mode": floor_mode,
                **(
                    {"node_frequency": int(node_freq)}
                    if node_freq is not None
                    else {}
                ),
                **collocation_frame_provenance(frame_attrs),
            }),
        )
        analysis_jobs.update(job_id, progress=90, message=lt("Fertig: {rows} Reihen", "Done: {rows} rows").format(rows=len(rows)))
        analysis_jobs.set_result(
            job_id,
            result={
                "rows": rows,
                "term": term,
                "collocate": collocate or "",
                "window": int(window),
                "within_sentence": bool(within_sentence),
                "method": method,
                "row_limit": int(safe_limit),
                "total_candidates": int(total_candidates),
                "truncated": bool(total_candidates > safe_limit),
            },
            total_rows=len(rows),
        )
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Collocates Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


async def _run_collocates_diff_job(
    job_id: str,
    *,
    corpus: str | None,
    term: str,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    limit: int,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    target_docset_key: str,
    reference_docset_key: str,
) -> None:
    try:
        analysis_jobs.update(
            job_id,
            progress=5,
            message=lt("Dokumentmengen werden vorbereitet", "Preparing document sets"),
            status="running",
        )
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=18, message=lt("Kollokationsanker werden aufgelöst", "Resolving collocation nodes"))
        rows, result_meta = await _run_heavy_scan(
            _collocates_diff_rows_for_term,
            idx,
            term,
            target_doc_ids=target_doc_ids,
            reference_doc_ids=reference_doc_ids,
            target_docset_key=target_docset_key,
            reference_docset_key=reference_docset_key,
            window=window,
            within_sentence=within_sentence,
            sort_by=sort_by,
            limit=limit,
            return_meta=True,
        )
        rows = [{k: _sanitize_float(v) for k, v in row.items()} for row in rows]
        # Job-based contrast carries
        # the same `method` block as the synchronous analysis routes so non-frontend
        # consumers (scripts, Copilot trace) get reproducible formulas/totals.
        try:
            target_total = int(idx.docset_token_count(target_doc_ids)) or None
            reference_total = int(idx.docset_token_count(reference_doc_ids)) or None
        except Exception:  # pragma: no cover - totals are best-effort provenance
            target_total = None
            reference_total = None
        # Rows are ranked by |diff_per_million|. sort_by only chooses the
        # association measure in target_score/reference_score.
        score_name, _score_col = _collocation_score_spec(sort_by)
        method = build_method_block(
            "contrast",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=target_total,
            reference_total=reference_total,
            window=int(window),
            within_sentence=bool(within_sentence),
            sort_key="diff_abs",
            statistics=(score_name, "diff_per_million", "log_ratio"),
            extra=collocation_method_extra({
                "candidate_policy": "complete_eligible_union_before_ranking",
                "score_key": score_name,
                "rank_definition": "abs(diff_per_million) descending",
            }),
        )
        analysis_jobs.update(job_id, progress=92, message=lt("Fertig: {rows} Reihen", "Done: {rows} rows").format(rows=len(rows)))
        analysis_jobs.set_result(
            job_id,
            result={
                "rows": rows,
                "term": term,
                "window": int(window),
                "within_sentence": bool(within_sentence),
                "sort_by": (sort_by or "").strip().lower(),
                "method": method,
                **result_meta,
            },
            total_rows=len(rows),
        )
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Collocates-Diff-Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


async def _run_ngrams_job(
    job_id: str,
    *,
    corpus: str | None,
    doc_ids: np.ndarray,
    min_n: int,
    max_n: int,
    limit: int,
    min_freq: int = 1,
) -> None:
    try:
        analysis_jobs.update(
            job_id,
            progress=5,
            message=lt("Dokumentmenge wird vorbereitet", "Preparing document set"),
            status="running",
        )
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=20, message=lt("Ngram Zähler werden aufgebaut", "Building n-gram counts"))
        # ABSCHNITTSWEISE, siehe analysis_runners.ngram_abschnitte. Ein
        # Aufruf ueber das ganze Korpus haelt die GIL minutenlang und macht
        # das Backend fuer seine Dauer unerreichbar. Zwischen zwei
        # Abschnitten kehrt die Kontrolle nach Python zurueck.
        from candyconc.services.backend.analysis_runners import ngram_abschnitte

        abschnitte = ngram_abschnitte(doc_ids, idx)
        counts: dict[tuple[int, ...], int] = {}
        for nummer, abschnitt in enumerate(abschnitte, start=1):
            teil = await _run_heavy_scan(
                _ngram_counts, idx, abschnitt, int(min_n), int(max_n)
            )
            for schluessel, wert in teil.items():
                counts[schluessel] = counts.get(schluessel, 0) + wert
            analysis_jobs.update(
                job_id,
                progress=20 + int(45 * nummer / len(abschnitte)),
                message=lt(
                    "Ngram Zähler werden aufgebaut ({part} von {parts})",
                    "Building n-gram counts ({part} of {parts})",
                ).format(part=nummer, parts=len(abschnitte)),
            )
        lex = idx.fast_index.lexicons.word
        if lex is None:
            raise RuntimeError(_WORD_LEXICON_MISSING)
        analysis_jobs.update(job_id, progress=70, message=lt("Ngram Ergebnisse werden sortiert", "Sorting n-gram results"))
        rows: list[dict[str, Any]] = []
        safe_limit = _bounded_analysis_job_limit(limit)
        # Same analyst-token policy as the synchronous route (routes/analysis.py):
        # keep an n-gram only when EVERY constituent token is an analyst token, so
        # punctuation, |LBR|/marker tokens and emoji never headline the ranking. We
        # filter the WHOLE candidate set before taking the top-N so the limit and
        # total_candidates describe the analyst-token basis, not the raw stream.
        analyst_candidates: list[tuple[tuple[int, ...], tuple[str, ...], int]] = []
        for ngram_ids, freq in counts.items():
            # The floor belongs before top-N selection.  Filtering it in the
            # frontend would let low-frequency rows consume the bounded result
            # and silently hide eligible N-grams.
            if int(freq) < int(min_freq):
                continue
            tokens: list[str] = []
            for i in ngram_ids:
                word = lex.get_string(int(i)) or ""
                if not is_analyst_token(word):
                    tokens = []
                    break
                tokens.append(word)
            if not tokens:
                continue
            analyst_candidates.append(
                (tuple(int(token_id) for token_id in ngram_ids), tuple(tokens), int(freq))
            )
        total_candidates = len(analyst_candidates)
        top_items = heapq.nsmallest(
            safe_limit,
            analyst_candidates,
            key=lambda item: (-item[2], item[0]),
        )
        for _token_ids, tokens, freq in top_items:
            rows.append(
                {
                    "ngram": " ".join(tokens).strip(),
                    "freq": int(freq),
                    "n": len(tokens),
                }
            )
        rows.sort(key=lambda r: r["freq"], reverse=True)
        # F1 statistical provenance (Track T5 #C1): the plain n-grams job carries the
        # same `method` block as the n-grams-diff runner / synchronous routes.
        # NGRAMS target_total: the scoped token count is the per-million denominator.
        # The sync route (routes/analysis.py) passes target_total=scope_total; the
        # job MUST too, else a metadata subcorpus job reports per-million against a
        # missing/zero denominator (count/per-million parity).
        try:
            scope_total = int(await asyncio.to_thread(idx.docset_token_count, doc_ids))
        except Exception:
            scope_total = 0
        method = build_method_block(
            "ngrams",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=scope_total or None,
            extra={
                "min_n": int(min_n),
                "max_n": int(max_n),
                "min_freq": int(min_freq),
                "candidate_policy": "complete_analyst_token_universe_before_ranking",
                "tie_break": "token_id_ascending",
            },
        )
        analysis_jobs.update(job_id, progress=92, message=lt("Fertig: {rows} Reihen", "Done: {rows} rows").format(rows=len(rows)))
        analysis_jobs.set_result(
            job_id,
            result={
                "rows": rows,
                "min_n": int(min_n),
                "max_n": int(max_n),
                "min_freq": int(min_freq),
                "method": method,
                "row_limit": int(safe_limit),
                "total_candidates": int(total_candidates),
                "truncated": bool(total_candidates > safe_limit),
            },
            total_rows=len(rows),
        )
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Ngrams Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


async def _run_ngrams_diff_job(
    job_id: str,
    *,
    corpus: str | None,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    min_n: int,
    max_n: int,
    limit: int,
    min_freq: int = 1,
) -> None:
    try:
        analysis_jobs.update(
            job_id,
            progress=5,
            message=lt("Dokumentmengen werden vorbereitet", "Preparing document sets"),
            status="running",
        )
        idx = get_corpus(corpus)
        analysis_jobs.update(job_id, progress=20, message=lt("N-Gramm-Zähler werden berechnet", "Computing n-gram counts"))
        (
            target_counts,
            reference_counts,
            total_t,
            total_r,
            stellen_t,
            stellen_r,
        ) = await asyncio.gather(
            _run_heavy_scan(_ngram_counts, idx, target_doc_ids, int(min_n), int(max_n)),
            _run_heavy_scan(_ngram_counts, idx, reference_doc_ids, int(min_n), int(max_n)),
            asyncio.to_thread(idx.docset_token_count, target_doc_ids),
            asyncio.to_thread(idx.docset_token_count, reference_doc_ids),
            # Die Bezugsgroesse der Rate ist NICHT die Tokenzahl: ein Dokument
            # der Laenge L traegt L - n + 1 Positionen der Ordnung n. Die
            # Tokenzahl bleibt daneben stehen, sie beschreibt die
            # Teilkorpusgroesse und wird weiterhin ausgewiesen.
            _run_heavy_scan(
                _ngram_populations, idx, target_doc_ids, int(min_n), int(max_n)
            ),
            _run_heavy_scan(
                _ngram_populations, idx, reference_doc_ids, int(min_n), int(max_n)
            ),
        )
        lex = idx.fast_index.lexicons.word
        if lex is None:
            raise RuntimeError(_WORD_LEXICON_MISSING)
        analysis_jobs.update(job_id, progress=68, message=lt("N-Gramm-Differenzen werden bewertet", "Scoring n-gram differences"))
        safe_limit = _bounded_analysis_job_limit(limit)
        alle_analysetoken = _analysetoken_pruefer(lex)
        total_candidates = 0
        def _eligible_items():
            nonlocal total_candidates
            # Die Vereinigung ohne eigene Menge, siehe _ngram_vereinigung.
            for raw_key, target_freq, reference_freq in _ngram_vereinigung(
                target_counts, reference_counts
            ):
                target_freq = int(target_freq)
                reference_freq = int(reference_freq)
                if target_freq <= 0 and reference_freq <= 0:
                    continue
                # Preserve the UI's documented contrast semantics: an N-gram is
                # eligible when it reaches the minimum on either side.  Apply that
                # rule before the bounded ranking, not after it.
                if max(target_freq, reference_freq) < int(min_freq):
                    continue
                # Same analyst-token policy as the synchronous n-gram route and
                # frequency_list: keep an n-gram only when EVERY constituent token is
                # an analyst token, so punctuation, |LBR|/marker tokens and emoji never
                # headline the contrast. We filter the WHOLE union before taking the
                # top-N (and count total_candidates over the filtered union), so the
                # limit and total_candidates describe the analyst-token basis.
                # Die N-Gramm-Zeichenkette entsteht erst für die ausgegebenen
                # Zeilen. Ihre frühere Prüfung auf leer schloss nur den leeren
                # Schlüssel aus, denn jedes Analyse-Token enthält ein Zeichen,
                # das strip stehen lässt.
                if not raw_key or not alle_analysetoken(raw_key):
                    continue
                total_candidates += 1
                key = tuple(map(int, raw_key))
                # Je Zeile nach IHRER Ordnung: ein Aufruf liefert min_n bis
                # max_n zugleich, und der Nenner unterscheidet sich je Ordnung.
                target_per_million = _per_million(
                    target_freq, int(stellen_t.get(len(key), 0))
                )
                reference_per_million = _per_million(
                    reference_freq, int(stellen_r.get(len(key), 0))
                )
                diff_per_million = target_per_million - reference_per_million
                yield (
                    abs(diff_per_million),
                    key,
                    target_freq,
                    reference_freq,
                    target_per_million,
                    reference_per_million,
                    diff_per_million,
                )

        # The union's iteration order is not a research result.
        # Select the full eligible population with an explicit score/id order.
        top_items = heapq.nsmallest(
            safe_limit,
            _eligible_items(),
            key=lambda item: (-item[0], item[1]),
        )
        analysis_jobs.update(job_id, progress=84, message=lt("Top-N-Gramme werden dekodiert", "Decoding top n-grams"))
        rows: list[dict[str, Any]] = []
        for diff_abs, key, target_freq, reference_freq, target_per_million, reference_per_million, diff_per_million in top_items:
            ngram = " ".join(
                (lex.get_string(token_id) or "").strip() for token_id in key
            ).strip()
            rows.append(
                {
                    "ngram": ngram,
                    "n": len(key),
                    "target_freq": int(target_freq),
                    "reference_freq": int(reference_freq),
                    "target_per_million": float(target_per_million),
                    "reference_per_million": float(reference_per_million),
                    "diff_per_million": float(diff_per_million),
                    "diff_abs": float(diff_abs),
                }
            )
        # Job-based n-gram diff
        # carries the same `method` block as the synchronous routes.
        method = build_method_block(
            "ngrams_diff",
            index_fingerprint=kurzer_indexstand(_corpus_cache_signature(
                getattr(idx, "fast_index", None), corpus or "default"
            )),
            target_total=int(total_t) or None,
            reference_total=int(total_r) or None,
            extra={
                "min_n": int(min_n),
                "max_n": int(max_n),
                "min_freq": int(min_freq),
                "candidate_policy": "complete_analyst_token_union_before_ranking",
                "tie_break": "token_id_ascending",
                # Woraus die Rate gerechnet ist, gehoert neben die Rate.
                "rate_basis": "ngram_positions_per_order",
                "ngram_positions_target": {
                    str(n): int(v) for n, v in sorted(stellen_t.items())
                },
                "ngram_positions_reference": {
                    str(n): int(v) for n, v in sorted(stellen_r.items())
                },
            },
        )
        analysis_jobs.update(job_id, progress=92, message=lt("Fertig: {rows} Reihen", "Done: {rows} rows").format(rows=len(rows)))
        analysis_jobs.set_result(
            job_id,
            result={
                "rows": rows,
                "min_n": int(min_n),
                "max_n": int(max_n),
                "min_freq": int(min_freq),
                "target_token_count": int(total_t),
                "reference_token_count": int(total_r),
                "method": method,
                **_bounded_result_meta(
                    row_limit=safe_limit,
                    total_candidates=total_candidates,
                ),
            },
            total_rows=len(rows),
        )
    except Exception as exc:  # pragma: no cover - background errors
        logger.exception("Ngrams-Diff-Job fehlgeschlagen: %s", exc)
        analysis_jobs.set_error(job_id, exc)


def _page_bounds(total: int, offset: int, limit: int) -> tuple[int, int]:
    start = _bounded_offset(offset)
    if start >= total:
        return total, total
    lim = _bounded_page_limit(limit)
    stop = min(total, start + lim)
    return start, stop


def _page_rows_list(rows: list[dict[str, Any]], offset: int, limit: int) -> list[dict[str, Any]]:
    total = len(rows)
    if total == 0:
        return []
    start, stop = _page_bounds(total, offset, limit)
    if start >= stop:
        return []
    return rows[start:stop]


def _rows_from_frame_page(frame: Any, *, offset: int, limit: int) -> list[dict[str, Any]]:
    safe_offset = _bounded_offset(offset)
    safe_limit = _bounded_page_limit(limit)
    page = frame
    if hasattr(page, "slice"):
        try:
            page = page.slice(safe_offset, safe_limit)
        except TypeError:
            pass
    elif hasattr(page, "iloc"):
        page = page.iloc[safe_offset : safe_offset + safe_limit]
    if hasattr(page, "to_dicts"):
        rows = page.to_dicts()
    elif hasattr(page, "to_dict"):
        rows = page.to_dict("records")
    else:
        rows = []
    if len(rows) > safe_limit:
        rows = rows[:safe_limit]
    # Sanitize per cell so a non-finite stat (e.g. a divide-by-zero salience in a
    # word-sketch frame) can never reach JSON serialization as NaN/Inf and 500
    # the route. Done here so every caller (word-sketch route, collocates job) is
    # covered without each remembering to wrap — finding D NaN/Inf sanitization.
    return [{k: _sanitize_float(v) for k, v in row.items()} for row in rows]


def _align_counts_to_union(
    union_ids: np.ndarray,
    ids: np.ndarray,
    counts: np.ndarray,
) -> np.ndarray:
    if union_ids.size == 0 or ids.size == 0:
        return np.zeros(union_ids.size, dtype=np.uint64)
    order = np.argsort(ids.astype(np.uint32, copy=False))
    ids_sorted = ids[order].astype(np.uint32, copy=False)
    counts_sorted = counts[order].astype(np.uint64, copy=False)
    idxs = np.searchsorted(ids_sorted, union_ids)
    out = np.zeros(union_ids.size, dtype=np.uint64)
    valid = idxs < ids_sorted.size
    if not np.any(valid):
        return out
    valid_pos = np.nonzero(valid)[0]
    idxs_valid = idxs[valid]
    union_valid = union_ids[valid]
    exact = ids_sorted[idxs_valid] == union_valid
    if np.any(exact):
        out[valid_pos[exact]] = counts_sorted[idxs_valid[exact]]
    return out


def _frequency_rows_from_result(
    idx: CorpusIndex,
    result: Dict[str, Any],
    *,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    term_ids = np.asarray(result.get("term_ids"), dtype=np.uint32)
    counts = np.asarray(result.get("counts"), dtype=np.uint64)
    total = int(term_ids.size)
    if total == 0:
        return []
    start, stop = _page_bounds(total, offset, limit)
    slice_ids = term_ids[start:stop]
    if slice_ids.size == 0:
        return []
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(_WORD_LEXICON_MISSING)
    # The job stores folded rows keyed by the class representative. The label is
    # the class's most frequent spelling, like the synchronous list.
    label_fn = getattr(idx, "casefold_labels", None)
    if callable(label_fn):
        words = label_fn(slice_ids, "word")
    else:
        words = strings_for_ids(lex.offsets, lex.strings_view, slice_ids, True)
    slice_counts = counts[start:stop]
    rows: list[dict[str, Any]] = []
    for word, freq in zip(words, slice_counts):
        rows.append({"word": str(word), "f": int(freq)})
    return rows


def _keyness_rows_from_result(
    idx: CorpusIndex,
    result: Dict[str, Any],
    *,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    term_ids = np.asarray(result.get("term_ids"), dtype=np.uint32)
    chi2_cell = np.asarray(result.get("chi2_cell"), dtype=np.float64)
    ll = np.asarray(result.get("ll"), dtype=np.float64)
    target_counts = np.asarray(result.get("target_counts", np.zeros(term_ids.size)), dtype=np.uint64)
    reference_counts = np.asarray(result.get("reference_counts", np.zeros(term_ids.size)), dtype=np.uint64)
    total_t = int(result.get("total_t") or 0)
    total_r = int(result.get("total_r") or 0)
    total = int(term_ids.size)
    if total == 0:
        return []
    # Inferential stats are precomputed by _run_keyness_docset_job over the FULL
    # candidate set (q-FDR before truncation). Fall back to NaN-filled arrays for
    # legacy results that predate these fields so paging never raises.
    def _stat_array(key: str) -> np.ndarray:
        arr = result.get(key)
        if arr is None:
            return np.full(total, np.nan, dtype=np.float64)
        arr = np.asarray(arr, dtype=np.float64)
        if arr.size != total:
            return np.full(total, np.nan, dtype=np.float64)
        return arr

    log_ratio = _stat_array("log_ratio")
    log_ratio_ci_low = _stat_array("log_ratio_ci_low")
    log_ratio_ci_high = _stat_array("log_ratio_ci_high")
    # NaN-gefuellt fuer Altergebnisse, die die Spalte noch nicht kennen: die
    # Seitenausgabe darf daran nicht scheitern.
    lrc = _stat_array("lrc")
    p_value = _stat_array("p_value")
    q_value = _stat_array("q_value")
    # Full 2x2 Pearson chi-square (proper test statistic, df=1) precomputed by
    # _run_keyness_docset_job over the FULL candidate set. NaN-filled for legacy
    # results that predate the field so paging never raises (Track T5 #C3).
    chi2 = _stat_array("chi2")
    # Reliability columns precomputed by _run_keyness_docset_job over the FULL
    # candidate set (C-keyness-references-03), mirroring keyness.compute_keyness_counts.
    # NaN/False-filled for legacy results that predate these fields so paging never
    # raises and the schema stays stable across versions.
    expected_min = _stat_array("expected_min")
    bic = _stat_array("bic")

    def _bool_array(key: str) -> np.ndarray:
        arr = result.get(key)
        if arr is None:
            return np.zeros(total, dtype=bool)
        arr = np.asarray(arr, dtype=bool)
        if arr.size != total:
            return np.zeros(total, dtype=bool)
        return arr

    low_reliability = _bool_array("low_reliability")
    start, stop = _page_bounds(total, offset, limit)
    slice_ids = term_ids[start:stop]
    if slice_ids.size == 0:
        return []
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(_WORD_LEXICON_MISSING)
    words = strings_for_ids(lex.offsets, lex.strings_view, slice_ids, True)
    slice_chi2_cell = chi2_cell[start:stop]
    slice_ll = ll[start:stop]
    slice_target_counts = target_counts[start:stop]
    slice_reference_counts = reference_counts[start:stop]
    slice_log_ratio = log_ratio[start:stop]
    slice_lr_low = log_ratio_ci_low[start:stop]
    slice_lr_high = log_ratio_ci_high[start:stop]
    slice_lrc = lrc[start:stop]
    slice_p = p_value[start:stop]
    slice_q = q_value[start:stop]
    slice_chi2 = chi2[start:stop]
    slice_expected_min = expected_min[start:stop]
    slice_bic = bic[start:stop]
    slice_low_reliability = low_reliability[start:stop]
    rows: list[dict[str, Any]] = []
    for (
        word,
        target_freq,
        reference_freq,
        score_chi2_cell,
        score_ll,
        lr,
        lr_lo,
        lr_hi,
        lrc_wert,
        p_val,
        q_val,
        score_chi2,
        e_min,
        score_bic,
        low_rel,
    ) in zip(
        words,
        slice_target_counts,
        slice_reference_counts,
        slice_chi2_cell,
        slice_ll,
        slice_log_ratio,
        slice_lr_low,
        slice_lr_high,
        slice_lrc,
        slice_p,
        slice_q,
        slice_chi2,
        slice_expected_min,
        slice_bic,
        slice_low_reliability,
    ):
        target_pm = (float(target_freq) / float(total_t) * 1_000_000.0) if total_t > 0 else 0.0
        reference_pm = (float(reference_freq) / float(total_r) * 1_000_000.0) if total_r > 0 else 0.0
        diff_pm = target_pm - reference_pm
        sign = 1.0 if diff_pm >= 0.0 else -1.0
        direction = "target" if diff_pm >= 0.0 else "reference"
        rows.append(
            {
                "word": str(word),
                "target_freq": int(target_freq),
                "reference_freq": int(reference_freq),
                # All raw-float fields are NaN/Inf-sanitized: chi2_cell/ll can be
                # non-finite for zero-frequency edge cases, and per-million ratios
                # for empty partitions, which would otherwise serialize as invalid
                # JSON and 500 the keyness route (finding D NaN/Inf sanitization).
                "target_per_million": _sanitize_float(target_pm),
                "reference_per_million": _sanitize_float(reference_pm),
                "diff_per_million": _sanitize_float(diff_pm),
                "direction": direction,
                "chi2_cell": _sanitize_float(float(score_chi2_cell)),
                # Full 2x2 Pearson chi-square (df=1) beside the single-cell chi2_cell
                # so the REST docset path matches keyness.py / the Copilot path.
                "chi2": _sanitize_float(float(score_chi2)),
                "chi2_signed": _sanitize_float(float(score_chi2) * sign),
                "ll": _sanitize_float(float(score_ll)),
                "chi2_cell_signed": _sanitize_float(float(score_chi2_cell) * sign),
                "ll_signed": _sanitize_float(float(score_ll) * sign),
                "log_ratio": _sanitize_float(float(lr)),
                "log_ratio_ci_low": _sanitize_float(float(lr_lo)),
                "log_ratio_ci_high": _sanitize_float(float(lr_hi)),
                "lrc": _sanitize_float(float(lrc_wert)),
                "p_value": _sanitize_float(float(p_val)),
                "q_value": _sanitize_float(float(q_val)),
                # Reliability columns (C-keyness-references-03): E_min, the E>=5
                # rule flag, and Wilson's size-robust BIC — same schema as
                # services.tools.keyness.compute_keyness_counts.
                "expected_min": _sanitize_float(float(e_min)),
                "low_reliability": bool(low_rel),
                "bic": _sanitize_float(float(score_bic)),
            }
        )
    # Dieselbe Aufschluesselung wie am Copilot-Werkzeug und an der
    # REST-Route. Ohne sie liest sich eine Zeile als Aussage ueber ihr
    # gedrucktes Etikett, waehrend sie eine Aussage ueber die Faltklasse ist.
    schreibungen_anhaengen(
        rows,
        lambda ids: strings_for_ids(
            lex.offsets, lex.strings_view, np.asarray(ids, dtype=np.uint32), True
        ),
        (slice_ids, words, result.get("surface_variants_target") or {}),
        (slice_ids, words, result.get("surface_variants_reference") or {}),
    )
    return rows


def _rows_from_result_list(
    result: Dict[str, Any],
    *,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    rows = result.get("rows")
    if not isinstance(rows, list):
        return []
    return _page_rows_list(rows, offset, limit)


def _result_limit_meta(result: Dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    meta: dict[str, Any] = {}
    # `method` carries the F1 statistical-provenance block for job-based analyses
    # (contrast / ngrams_diff); surface it alongside the paging meta so paged job
    # rows expose the same provenance contract as the synchronous routes.
    for key in (
        "row_limit", "total_candidates", "truncated", "method", "filtered_token_policy",
        "case_policy", "label_policy",
    ):
        if key in result:
            meta[key] = result[key]
    return meta


def _pruefe_scan_umfang(idx: CorpusIndex, query: str) -> None:
    """Vor dem ungedeckelten Scan zaehlen und laut abbrechen statt zu kappen.

    B5/P2.8: eine Kappung darf sein, sie darf nur nicht schweigen. Vorher
    kappte der Scan bei 5.000 (Rankingdeckel als Scanpraefix missbraucht),
    danach bei 20.000 (Engine-Default fuer ``limit=None``), beide Male ohne
    Signal, und jeder pro-Million-Nenner auf so einem Docset war still zu
    klein. Ohne Deckel ist die Zahl richtig, aber ``cql:[]`` kostet am
    142M-Korpus 233 s und 16,3 GB. Deshalb: zaehlen, und oberhalb der Grenze
    eine Fehlermeldung, die den Umfang NENNT.

    Gezaehlt wird nur der CQL-Zweig, und das ist eine Einschraenkung, keine
    Vollstaendigkeit. Eine frueher hier stehende Begruendung ('Klartext-
    Abfragen sind durch die Frequenz EINES Terms begrenzt') war sachlich
    falsch: ein Wildcard-Term wie ``Mensch*`` expandiert ueber viele
    Lexikoneintraege, und ``NOT`` erreicht die Korpusgroesse.

    Der Klartext-Zweig ist stattdessen durch den EIGENEN, lauten Waechter
    der Auswertung gedeckt: ``_complement_positions`` wirft ueber
    ``_NOT_MAX_TOKENS`` (50 Mio.), und ``_positions_from_query`` reicht ihm
    fuer den ungedeckelten Scan ausdruecklich ``limit=None`` durch, weil
    genau dieser Zweig den Waechter prueft. Eine Vorfassung reichte
    ueberall ``SCAN_ALLE_TREFFER`` durch und hat ihn damit STILL
    ABGESCHALTET, waehrend sie einen anderen Deckel aufhob. Am 142M-Korpus
    nachgemessen: ``NOT Flucht`` ungedeckelt wirft jetzt wieder
    'NOT Query zu gross', mit ``limit=5000`` liefert es 78 Dokumente.
    """
    from candyconc.core.cql_macros import normalize_query_input

    roh = normalize_query_input((query or "").strip())
    if not roh.lower().startswith("cql:"):
        return
    ausdruck = roh[4:].strip()
    if not ausdruck:
        return
    from candyconc.core.cql_engine import count_cql_matches_backend

    try:
        treffer = int(count_cql_matches_backend(
            idx.fast_index, ausdruck, within_sentences_by_default=True
        ))
    except Exception:
        # Zaehlen ist eine Schutzmassnahme, kein Ergebnis. Scheitert es,
        # laeuft der Scan wie bisher: lieber teuer als still falsch.
        return
    if treffer > DOCSET_SCAN_POSITIONEN_MAX:
        from candyconc.core.meta_filters import EingabeFormFehler

        raise EingabeFormFehler(
            lt(
                "Die Abfrage trifft {hits} Positionen und ueberschreitet die Grenze "
                "von {limit} fuer einen ungedeckelten Teilkorpus-Scan. Fruehere "
                "Fassungen haben hier STILL auf 5.000 beziehungsweise 20.000 "
                "gekappt, und jede pro-Million-Rechnung auf dem Ergebnis war "
                "damit gegen einen zu kleinen Nenner. Schraenke die Abfrage ein "
                "oder baue das Teilkorpus ueber Metadatenfilter.",
                "The query matches {hits} positions and exceeds the limit "
                "of {limit} for an uncapped subcorpus scan. Earlier "
                "versions SILENTLY capped at 5,000 or 20,000 here, so every "
                "per-million calculation on the result used a denominator that "
                "was too small. Narrow the query or build the subcorpus from "
                "metadata filters.",
            ).format(
                hits=f"{treffer:,}".replace(",", "."),
                limit=f"{DOCSET_SCAN_POSITIONEN_MAX:,}".replace(",", "."),
            )
        )


def _search_docset_doc_ids(
    idx: CorpusIndex,
    query: str,
    *,
    meta_filters: Dict[str, Any],
    ai_filters: Dict[str, Any],
    include_ai: bool,
    include_human: bool,
    limit: int | None,
    bericht: Dict[str, Any] | None = None,
    familien: bool = False,
) -> tuple[np.ndarray, int, int]:
    """Docset aus Suchtreffern: (sortierte doc_ids, hit_doc_count, ref_doc_count).

    Gemeinsame Quelle für analysis_docset_from_search, create_docset und die
    Wiederherstellung gespeicherter Subkorpora. Jedes Dokument im Ergebnis
    erfüllt jeden Filter: ``include_ai``/``include_human`` lassen seine Seite
    zu, es erfüllt ``meta_filters``, ein KI-Dokument zusätzlich
    ``ai_filters``. ``hit_doc_count`` zählt die Dokumente des Ergebnisses mit
    eigenem Treffer.

    ``familien=False`` liefert genau diese Trefferdokumente. ``familien=True``
    ergänzt zu jedem Trefferdokument, das ``meta_filters`` erfüllt, sein
    Referenzdokument (``ref_doc``, sonst das Dokument selbst) und alle
    KI-Fassungen dazu, auch ohne eigenen Treffer, sofern sie die Filter
    erfüllen. ``ref_doc_count`` zählt diese Referenzdokumente und ist ohne
    Familien 0. Die REST-Route fordert Familien für den Paarbaum der
    Oberfläche an und benennt sie in der Antwort.

    Every added document is checked against the filters. An unconditional
    expansion that adds the original without checking ``meta_filters`` and
    hit documents without checking ``ai_filters`` inflates the docset: on a
    corpus of 250,535 documents, ``[word="darüber" %c] [word="hinaus" %c]``
    with ``{"text_type": "ai"}`` then yields 40,391 documents with 8.4
    percent human tokens, 3,107 families of 13 documents each, for only
    4,714 hits on the AI side.

    ``limit=None`` heisst hier WIRKLICH ungedeckelt. Es muss ausdruecklich
    uebersetzt werden, denn eine Ebene tiefer bedeutet ``limit=None`` das
    Gegenteil: ``search_cql_matches_backend`` setzt dort
    ``max_matches=20000`` (cql_engine.py:258). Wer None durchreicht, tauscht
    also nur den 5.000er-Deckel gegen einen 20.000er und bekommt weiterhin
    ein Korpus-PRAEFIX statt eines Korpusschnitts.

    ``bericht`` is an optional output slot for the question WHETHER the scan
    was capped. A set ``limit`` caps the hit scan, and the return value
    alone does not show it: ``hit_doc_count`` always equals the document
    count. On a 56,000-token test index, ``cql:[pos="NOUN"]``:

        limit=None   1995 documents,  56,080 tokens, hit_doc_count 1995
        limit=5000   1051 documents,  28,995 tokens, hit_doc_count 1051
        limit=100      24 documents,     632 tokens, hit_doc_count   24

    All three look equally complete. The restore path
    ``_resolve_subcorpus_doc_ids``, by contrast, ALWAYS resolves uncapped,
    because a subcorpus definition stores no ``limit``. The same query
    would give 1051 documents on creation and 1995 on restore, without
    either answer saying so.

    An output slot instead of a fourth return value, because ten call sites
    unpack the three-tuple. Callers that do not need the report notice
    nothing."""
    if not include_ai and not include_human:
        return np.zeros(0, dtype=np.uint32), 0, 0
    # This function calls _match_meta_filters RAW per document. Without the
    # checks below a filter on an unknown field with the operator != would
    # return the WHOLE corpus: 741 documents on a small test index,
    # byte-identical to the control WITHOUT a filter, and 162,694 documents
    # and 120,541,515 tokens on a 142M-token corpus. An unknown field
    # matches nothing, in EVERY direction.
    from candyconc.core.meta_filters import (
        pruefe_filter_traegt_bedingung,
        unbekannte_felder,
    )

    # The second gap of the same class: a filter of empty values would
    # silently disappear here. On a small test index {"split": ""} would
    # return 658 documents, byte-identical to the control WITHOUT a filter,
    # while {"split": "test"} restricts to 214.
    for _spec in (meta_filters, ai_filters):
        pruefe_filter_traegt_bedingung(_spec, fast_index=idx.fast_index)
    for _spec in (meta_filters, ai_filters):
        if _spec and unbekannte_felder(idx.fast_index, _spec):
            return np.zeros(0, dtype=np.uint32), 0, 0
    if limit is None:
        _pruefe_scan_umfang(idx, query)
    positions = _positions_from_query(
        idx, query, limit=limit, ungedeckelt=limit is None
    )
    if bericht is not None:
        # "Der Scan hat seine Decke erreicht", nicht "es gibt genau so
        # viele". Trifft die Abfrage exakt ``limit`` mal, meldet das
        # konservativ eine Kappung. Diese Richtung ist die richtige: eine
        # zu vorsichtige Warnung kostet eine Nachfrage, ein verschwiegenes
        # Praefix kostet jeden pro-Million-Nenner darauf.
        gescannt = int(np.asarray(positions).size)
        bericht["deckel"] = limit
        bericht["gescannte_treffer"] = gescannt
        # GLEICH, nicht groesser-gleich. Der Klartext-Zweig wendet den
        # Deckel nicht auf den Scan an und liefert mehr als limit: "und"
        # mit limit=100 ergab 919 gescannte Treffer und dieselben 741
        # Dokumente wie ungedeckelt, und ">=" behauptete dort eine
        # Kappung, die nicht stattgefunden hat. Ein Scan, der wirklich an
        # seiner Decke endet, hoert bei GENAU limit auf.
        #
        # Grenze dieser Aussage: trifft die Abfrage exakt limit mal, meldet
        # das konservativ eine Kappung. Diese Richtung ist die richtige,
        # eine zu vorsichtige Warnung kostet eine Nachfrage.
        bericht["gekappt"] = bool(limit is not None and gescannt == int(limit))
    hit_docs = set(int(i) for i in _doc_ids_from_positions(idx, positions))
    doc_meta = idx.fast_index.doc_metadata

    def _meta(doc_id: int) -> dict[str, Any]:
        meta = doc_meta.get(int(doc_id), {})
        return meta if isinstance(meta, dict) else {}

    def _is_ai_doc(meta: dict[str, Any]) -> bool:
        # The compared side of a pair: ``version``, or ``ai`` in older indexes
        # and in the human/AI research layout.
        return is_version(meta.get("text_type"))

    def _ref_doc(meta: dict[str, Any]) -> int | None:
        ref_doc = meta.get("ref_doc")
        if isinstance(ref_doc, str) and ref_doc.isdigit():
            ref_doc = int(ref_doc)
        return int(ref_doc) if isinstance(ref_doc, int) else None

    def _erfuellt_jeden_filter(meta: dict[str, Any]) -> bool:
        ki = _is_ai_doc(meta)
        if not (include_ai if ki else include_human):
            return False
        if meta_filters and not _match_meta_filters(meta, meta_filters):
            return False
        return not (ki and ai_filters and not _match_meta_filters(meta, ai_filters))

    result_docs = {d for d in hit_docs if _erfuellt_jeden_filter(_meta(d))}
    hit_doc_count = len(result_docs)
    if not familien:
        return np.asarray(sorted(result_docs), dtype=np.uint32), hit_doc_count, 0

    # Die Familien gehen von allen Trefferdokumenten aus, die meta_filters
    # erfüllen, auf jeder Seite. Aufgenommen wird aber nur, was die
    # Filter oben erfüllt.
    ref_docs: set[int] = set()
    for doc_id in hit_docs:
        meta = _meta(doc_id)
        if meta_filters and not _match_meta_filters(meta, meta_filters):
            continue
        ref_doc = _ref_doc(meta)
        ref_docs.add(int(doc_id) if ref_doc is None else ref_doc)
    result_docs.update(r for r in ref_docs if _erfuellt_jeden_filter(_meta(r)))
    if include_ai and ref_docs:
        for doc_id, meta in doc_meta.items():
            if (isinstance(meta, dict) and _is_ai_doc(meta)
                    and _ref_doc(meta) in ref_docs and _erfuellt_jeden_filter(meta)):
                result_docs.add(int(doc_id))

    return np.asarray(sorted(result_docs), dtype=np.uint32), hit_doc_count, len(ref_docs)


# --------------------------------------------------------------------------- #
# Persistent named subcorpora (P0 #3)
#
# A SubcorpusDefinition (durable, in the Project store) is the identity; docset_id
# stays an opaque ephemeral cache hint. /subcorpora/{name}/resolve re-hydrates a
# definition into a fresh live docset_id via the canonical resolve path, so
# creation == restore reproduces the same doc set on an unchanged index, as
# long as no ``limit`` was set on creation. A definition stores none, so the
# resolve path always resolves uncapped, and a docset created with a cap is a
# PREFIX of the same query (1051 against 1995 documents on a small test
# index). /analysis/docset_from_search therefore reports the cap explicitly
# instead of hiding it under a complete looking number.
# --------------------------------------------------------------------------- #
_PROJECT_STORE: "Any | None" = None
_PROJECT_STORE_LOCK = threading.Lock()


def _get_project():
    """Lazily open the single process-level Project store (CANDYCONC_PROJECT_FILE)."""
    global _PROJECT_STORE
    if _PROJECT_STORE is None:
        with _PROJECT_STORE_LOCK:
            if _PROJECT_STORE is None:
                from candyconc.project import Project, ProjectMigrationRequired

                try:
                    _PROJECT_STORE = Project(
                        _user_paths.project_file(get_config("CANDYCONC_PROJECT_FILE", "") or None)
                    )
                except ProjectMigrationRequired as exc:
                    raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
    return _PROJECT_STORE


def _resolve_subcorpus_doc_ids(idx: CorpusIndex, definition: dict) -> np.ndarray:
    """Re-resolve a SubcorpusDefinition to sorted doc_ids via the canonical path
    (search replay if a query is stored, else metadata-only)."""
    query = str(definition.get("query") or "").strip()
    filter_spec = definition.get("filter_spec") if isinstance(definition.get("filter_spec"), dict) else {}
    if query:
        doc_ids, _hits, _refs = _search_docset_doc_ids(
            idx, query,
            meta_filters=filter_spec,
            ai_filters=definition.get("ai_filters") if isinstance(definition.get("ai_filters"), dict) else {},
            include_ai=bool(definition.get("include_ai", True)),
            include_human=bool(definition.get("include_human", True)),
            # Wiederhergestellt wird, was beim Anlegen galt. Definitionen
            # von vor diesem Feld stammen aus dem Paarbaum der Oberfläche,
            # und dort baut die Route mit Familien.
            familien=bool(definition.get("familien", True)),
            # _bounded_analysis_job_limit(None) returns the top-N RANKING
            # cap (default 5000) and would cap the HIT SCAN. A docset built
            # from a search would then be a corpus PREFIX instead of a
            # corpus slice, and every per-million denominator on it silently
            # too small. On a small test index [pos="NOUN"] capped gives
            # 1051 documents and 28,995 tokens, uncapped 1995 and 56,080.
            limit=None,
        )
        return doc_ids
    if not filter_spec:
        return np.zeros(0, dtype=np.uint32)
    return _doc_ids_from_meta(idx, filter_spec)


# The /subcorpora route handlers (+ only-consumer helper _corpus_schema_hash) live in
# routes/subcorpora.py (route-extraction slice 2); they late-import _get_project /
# _resolve_subcorpus_doc_ids / get_corpus / _doc_count_for_index / _store_docset from
# this module so the _PROJECT_STORE singleton (monkeypatched in tests) stays authoritative.


def _lightweight_cql_analysis(
    query: str,
    normalized: str,
) -> Dict[str, Any] | None:
    """Return corpus-independent CQLF diagnostics when they already explain the issue."""

    if not normalized.lower().startswith("cql:"):
        return None
    from candyconc.candyconc_copilot import validate as validate_cqlf_query

    raw = query.strip()
    has_explicit_prefix = raw.lower().startswith("cql:")
    cql_text = normalized[4:]
    diagnostics = validate_cqlf_query(cql_text)
    errors = diagnostics.get("errors") or []
    if not errors:
        return None

    suggestions: list[str] = []
    hints: list[str] = []
    for suggestion in diagnostics.get("suggestions", []):
        if isinstance(suggestion, dict):
            text = str(suggestion.get("text", ""))
            hint = str(suggestion.get("hint", ""))
        else:
            text = str(suggestion)
            hint = ""
        if has_explicit_prefix and text:
            text = f"cql:{text}"
        suggestions.append(text)
        hints.append(hint)

    offset = 4 if has_explicit_prefix else 0
    spans = [
        [int(start) + offset, int(end) + offset]
        for start, end in diagnostics.get("spans", [])
    ]
    return {
        "errors": list(errors),
        "suggestions": suggestions,
        "hints": hints,
        "kinds": ["fix"] * len(suggestions),
        "spans": spans,
        "builder": None,
    }


async def _analyse_query_text(query: str, corpus: str | None = None) -> Dict[str, Any]:
    """Return validation result for ``query``."""
    from candyconc.core.cql_macros import normalize_query_input

    normalized = normalize_query_input(query)
    if normalized.lower().startswith("cql:"):
        lightweight = _lightweight_cql_analysis(query, normalized)
        if lightweight is not None:
            return lightweight
        try:
            idx = get_corpus(corpus)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
        from candyconc.core.cql_engine import analyse_cql_backend

        return await asyncio.to_thread(analyse_cql_backend, idx.fast_index, normalized)

    if not query.strip():
        return {
            "errors": [lt("Query ist leer.", "The query is empty.")],
            "suggestions": [],
            "hints": [],
            "spans": [],
        }
    try:
        parse_query(query)
    except Exception as exc:
        return {"errors": [exception_text(exc)], "suggestions": [], "hints": [], "spans": []}
    return {"errors": [], "suggestions": [], "hints": [], "spans": []}


def _launch_collocates_diff(
    corpus: str | None,
    term: str,
    *,
    window: int,
    within_sentence: bool,
    sort_by: str,
    limit: int,
    target_doc_ids: np.ndarray,
    reference_doc_ids: np.ndarray,
    target_key: str,
    reference_key: str,
) -> Dict[str, Any]:
    """Create + launch a collocates-diff background job and return its envelope.

    Shared by /analysis/collocates_diff/job and /analysis/contrast — one source for
    the job wiring so the free-contrast endpoint reuses the (pairing-free) diff path."""
    params = {
        "term": term,
        "window": int(window),
        "within_sentence": bool(within_sentence),
        "sort_by": sort_by,
        "limit": int(limit),
        "row_limit": int(limit),
        "target_docset_id": target_key,
        "reference_docset_id": reference_key,
        "target_doc_count": int(target_doc_ids.size),
        "reference_doc_count": int(reference_doc_ids.size),
    }
    try:
        job = analysis_jobs.create("collocates_diff", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _run_collocates_diff_job(
            job.job_id,
            corpus=corpus,
            term=term,
            window=window,
            within_sentence=within_sentence,
            sort_by=sort_by or None,
            limit=limit,
            target_doc_ids=target_doc_ids,
            reference_doc_ids=reference_doc_ids,
            target_docset_key=target_key,
            reference_docset_key=reference_key,
        )
    )
    analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


def _is_legacy_bracket_attr_query(raw: str) -> bool:
    if not (raw.startswith("[") and raw.endswith("]")):
        return False
    try:
        from candyconc.domain.query_parser import Attr, parse_query

        node = parse_query(raw)
        return isinstance(node, Attr) and node.key in {"lemma", "pos", "morph", "ent", "rel"}
    except Exception:
        return False


def _dispersion_positions_for_term(
    idx: CorpusIndex,
    term: str,
    *,
    docset_mask: np.ndarray | None,
) -> np.ndarray:
    raw_term = (term or "").strip()
    if not raw_term:
        return np.zeros(0, dtype=np.uint32)

    co_query = _parse_co_kwic_query(raw_term)
    if co_query:
        positions = _co_occurrence_positions(
            idx,
            term=co_query["term"],
            collocates=co_query["collocates"],
            window=co_query["window"],
            within_sentence=co_query["within_sentence"],
            docset_mask=docset_mask,
            attribute=co_query.get("attribute", "word"),
        )
        return positions.astype(np.uint32, copy=False)

    from candyconc.core.cql_macros import normalize_query_input

    normalized = normalize_query_input(raw_term)

    if normalized.lower().startswith("cql:") or _is_legacy_bracket_attr_query(raw_term):
        positions = _positions_from_query(
            idx,
            normalized if normalized.lower().startswith("cql:") else raw_term,
            limit=_ANALYSIS_MATCH_LIMIT,
        )
        offsets_np = np.asarray(positions, dtype=np.uint32)
    else:
        # THE SAME query evaluation as the count.
        #
        # A second implementation of the phrase split on the RAW user string
        # (splitting the plain term itself) would treat quotes, wildcards and
        # operators as letters of a token and invent a corpus-wide zero. On
        # a small test index, /query/count against dispersion:
        #     '"nicht mehr"'   36 against 0
        #     '"und"'         919 against 0
        #     'Mensch*'        95 against 0
        #     'nicht OR mehr' 753 against 0
        # all on the DEFAULT path, because the frequency recipe binds the
        # same string to both calls.
        #
        # _positions_from_query is the evaluation query_count uses as well
        # (parse_query + _eval_query). Both calls fed with the same string
        # get the same reading.
        positions = _positions_from_query(
            idx, normalized, limit=_ANALYSIS_MATCH_LIMIT
        )
        offsets_np = np.asarray(positions, dtype=np.uint32)

    if docset_mask is not None:
        offsets_np = _filter_positions_by_docset(idx, offsets_np, docset_mask)
    # Drop the index-only '|LBR|' line-break sentinel through the SAME seam every
    # count surface uses (see _compute_query_count), so dispersion's
    # observed_frequency + DP equal the canonical /query/count: [word="|LBR|"]=0,
    # [word=".*"]=55550, [pos="NOUN"]=9740 — not the raw 609/56159/9741 the
    # unfiltered position scan returns.
    offsets_np, _ = _drop_linebreak_sentinel_positions(idx, offsets_np)
    return offsets_np


def _dispersion_document_profile(
    offsets: np.ndarray,
    doc_bounds: np.ndarray,
    *,
    token_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (per-document hit counts, per-document token sizes).

    Hits are bucketed by the document that contains each global token offset,
    using the real ``doc_bounds`` (document start positions). Document sizes are
    derived from consecutive boundary gaps, with the final document extending to
    ``token_count``.
    """
    bounds = np.asarray(doc_bounds, dtype=np.int64).ravel()
    n_docs = int(bounds.size)
    if n_docs == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    safe_token_count = max(int(token_count), int(bounds[-1]))
    ends = np.empty(n_docs, dtype=np.int64)
    ends[: n_docs - 1] = bounds[1:]
    ends[n_docs - 1] = safe_token_count
    doc_sizes = np.clip(ends - bounds, 0, None).astype(np.int64, copy=False)

    counts = np.zeros(n_docs, dtype=np.int64)
    off = np.asarray(offsets, dtype=np.int64).ravel()
    off = off[(off >= 0) & (off < safe_token_count)]
    if off.size:
        doc_idx = np.searchsorted(bounds, off, side="right") - 1
        doc_idx = np.clip(doc_idx, 0, n_docs - 1)
        counts = np.bincount(doc_idx, minlength=n_docs).astype(np.int64, copy=False)
    return counts, doc_sizes


# /projects/{proj}/clusters and /projects/{proj}/analysis-presets routes moved to
# routes/projects.py (route-extraction slice 1). Re-export for tests/back-compat:
_safe_project_dir = projects_routes._safe_project_dir


async def _dispatch_with_record(call: Dict[str, Any], token: str | None = None) -> Dict[str, Any]:
    name = call.get("function", {}).get("name")
    args_raw = call.get("function", {}).get("arguments", "{}")
    try:
        args = json.loads(args_raw)
    except Exception:
        args = {}
    if name == "run_cqlf_query" and "query" not in args:
        args["query"] = ""
    if name == "collocate_stats" and "term" not in args:
        args["term"] = ""
    patched = dict(call)
    patched["function"] = dict(call.get("function", {}))
    patched["function"]["arguments"] = json.dumps(args)
    return await _dispatch(patched, token)


def _resolve_chat_policy(
    payload: Dict[str, Any],
    *,
    username: str,
    project: str,
    user_token: str | None,
):
    """Build the copilot policy for a chat request from server-side state.

    Security (C2): ``budget``/``acl`` payload overrides are honored only when
    the caller's token resolves to the ``admin`` role. Previously any caller
    could lift their own ACL/budget restrictions per request by echoing the
    fields in the request body.
    """
    is_admin = auth.role_for_token(user_token) == "admin"

    override_budget = payload.get("budget") if is_admin else None
    if override_budget is not None:
        budget = int(override_budget)
    else:
        budget = PROJECT_QUOTAS.get(
            project,
            POLICY_BUDGETS.get(
                username,
                POLICY_BUDGETS.get("default", 1000),
            ),
        )

    override_acl = payload.get("acl") if is_admin else None
    if override_acl is not None:
        if isinstance(override_acl, str):
            allowed = [t.strip() for t in override_acl.split(",") if t.strip()]
        else:
            allowed = list(override_acl)
    else:
        allowed = POLICY_ACLS.get(username)
    acl = {username: allowed} if allowed is not None else None

    return _make_policy(token_budget=budget, acl=acl)


def _allowed_copilot_tools_for_user(username: str) -> list[str] | None:
    return POLICY_ACLS.get(username)


def _select_chat_tools_for_principal(
    question: str,
    *,
    ui_context: dict[str, Any] | None,
    username: str,
) -> list[dict[str, Any]]:
    prompt_tools = select_tools_for_prompt(
        question,
        _get_tools(),
        ui_context=ui_context,
    )
    return filter_dispatchable_tools_for_principal(
        prompt_tools,
        runtime_info=_get_tool_runtime_info(),
        allowed_tools=_allowed_copilot_tools_for_user(username),
        release_mode=auth.is_release_mode(),
        bindings_by_tool=_product_tool_bindings_by_name(),
    )


def _validate_chat_messages(payload: Dict[str, Any]) -> None:
    """Validate the chat ``messages`` array BEFORE any work / SSE stream opens.

    Finding 22: the endpoints used to read ``payload.get("messages", [])`` with
    no shape validation. A singular ``{"message": ...}`` (or any payload without
    a usable user turn) yielded an empty question and a generic greeting, while
    an empty body / ``{"messages": []}`` opened a never-completing SSE stream.
    This rejects those with HTTP 422 and a clear hint about the expected shape,
    so a misformed request fails fast instead of silently dropping the question
    or dangling a stream.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        # Braces are doubled because the hint is a format template.
        hint = lt(
            "Erwartet wird ein nicht-leeres 'messages'-Array, dessen letzter "
            "Eintrag eine User-Nachricht mit nicht-leerem 'content' ist, z.B. "
            '{{"messages": [{{"role": "user", "content": "..."}}]}}.',
            "Expected a non-empty 'messages' array whose last entry is a user "
            "message with non-empty 'content', for example "
            '{{"messages": [{{"role": "user", "content": "..."}}]}}.',
        ).format()
        # A stray singular top-level 'message' is the classic mistake — call it out.
        if "message" in payload and "messages" not in payload:
            raise HTTPException(
                status_code=422,
                detail=(
                    lt("Unbekanntes Feld 'message' (Singular). ", "Unknown field 'message' (singular). ") + hint
                ),
            )
        raise HTTPException(
            status_code=422,
            detail=lt("Fehlendes oder leeres 'messages'-Array. ", "Missing or empty 'messages' array. ") + hint,
        )
    dict_messages = [m for m in messages if isinstance(m, dict)]
    last = dict_messages[-1] if dict_messages else None
    if last is None or str(last.get("role", "")).lower() != "user":
        raise HTTPException(
            status_code=422,
            detail=lt(
                "Der letzte 'messages'-Eintrag muss eine User-Nachricht "
                "(role='user') sein.",
                "The last 'messages' entry must be a user message (role='user').",
            ),
        )
    if not str(last.get("content", "")).strip():
        raise HTTPException(
            status_code=422,
            detail=lt(
                "Die letzte User-Nachricht hat einen leeren 'content'.",
                "The last user message has an empty 'content'.",
            ),
        )


def _raise_llm_http_error(error: LLMRequestError) -> None:
    status = 503
    if error.kind in {LLMErrorKind.MODEL_NOT_LOADED, LLMErrorKind.NOT_CONFIGURED}:
        # Not retryable: a setting is missing, the service is not overloaded.
        status = 424
    elif error.kind == LLMErrorKind.CONTEXT_WINDOW_EXCEEDED:
        status = 413
    elif error.kind in {
        LLMErrorKind.BAD_REQUEST,
        LLMErrorKind.CAPABILITY_MISMATCH,
        LLMErrorKind.MAX_OUTPUT_TOKENS,
        LLMErrorKind.MEDIA_UNSUPPORTED,
    }:
        status = 422
    elif error.kind == LLMErrorKind.TIMEOUT:
        status = 504
    detail: Dict[str, Any] = {
        "code": error.kind,
        "message": error.message,
    }
    if error.model:
        detail["model"] = error.model
    raise HTTPException(status_code=status, detail=detail)


def _clamp_autonomy_level(ui_context: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp a client-supplied ``autonomy_level`` into [0, 10] server-side.

    Autonomy gates whether risky actions require human approval; the server must
    never trust an out-of-range value the client could use to skip approval.
    Returns the (possibly new) dict; only writes when an autonomy_level is set.
    """
    if not isinstance(ui_context, dict) or "autonomy_level" not in ui_context:
        return ui_context
    try:
        level = int(ui_context.get("autonomy_level"))
    except (TypeError, ValueError):
        # Finding (frontend audit): a non-numeric autonomy_level (e.g. "bogus")
        # must be rejected, not silently defaulted to 5 — the value gates
        # whether mutating actions need approval, so garbage is a client error.
        raise ApiError(
            422,
            "chat.autonomy_level_invalid",
            lt(
                "autonomy_level muss eine Ganzzahl in [0,10] sein.",
                "autonomy_level must be an integer in [0,10].",
            ),
        ) from None
    clamped = max(0, min(level, 10))
    if clamped == ui_context.get("autonomy_level"):
        return ui_context
    return {**ui_context, "autonomy_level": clamped}


def _salvage_resolve_partial_text(text: str, orch: Any) -> str:
    """Deterministische Politur des gestreamten Teiltexts vor dem Salvage.

    H6 (B2, Teil 3): der Backstop gab Modell-Teiltext verbatim aus —
    inklusive roher ``{{ev:...}}``-Marker und eines angebrochenen
    Schlusssatzes. Callfreie Schritte: (1) Marker deterministisch
    gegen die Turn-Evidenz aufloesen (unaufloesbare werden Platzhalter),
    (2) H9/C2 (V11a): die harten Fabrikationsregeln der Klasse (a)
    (claim_rules-HARD-Subset: ungebundene Zahlen, unaufloesbare
    Referenzen) laufen IMMER auch auf Salvage-Text — unbelegte Zahlen
    werden Platzhalter, (3) den angebrochenen Schlusssatz am letzten
    Satzende kappen, (4) Platzhalter-Saetze/-Zeilen fallen mit genau
    einer Sammel-Annotation (50%-Wachposten in
    ``drop_unresolved_sentences``). Zahlendetektion nur bei vorhandener
    Turn-Evidenz (rein konversationale Zahlen sind keine
    Fabrikationskandidaten, gleiche Regel wie im Referenz-Antwortpfad).
    Bei jedem Fehler bleibt der Originaltext erhalten (Salvage darf nie
    leerer werden als der Rohtext).
    """
    from candyconc.candyconc_copilot import recipe_runtime as _recipe_runtime

    try:
        evidence = [
            item
            for item in list(getattr(orch, "_turn_evidence_items", None) or [])
            if isinstance(item, dict)
        ]
        resolution = _recipe_runtime.resolve_reference_draft(
            text, evidence, "", detect_bare_numbers=bool(evidence)
        )
        resolved = str(resolution.get("text") or "") or text
        bare_numbers = list(resolution.get("bare_numbers") or [])
        if bare_numbers:
            # annotate=False: die Platzhalter-Saetze fallen gleich darunter,
            # die Drop-Statistik uebernimmt die Sammel-Annotation.
            resolved = _recipe_runtime.strike_unbound_numbers(
                resolved, bare_numbers, annotate=False
            )
        resolved = _recipe_runtime.trim_incomplete_tail_sentence(resolved)
        resolved = _recipe_runtime.drop_unresolved_sentences(resolved)
        # Engine failures bypass the orchestrator finishing step and may leave
        # raw tool traces in the backstop text. Apply only text polishing here.
        # The caller in routes/copilot.py applies politur_mit_zitatwache once.
        polished, _polish_notes = _recipe_runtime.final_answer_polish(resolved)
        resolved = polished or resolved
        return resolved.strip() or text
    except Exception:
        logger.exception("Salvage-Referenzaufloesung fehlgeschlagen")
        return text


_SALVAGE_FRAGMENT_MIN_CHARS = 240

_SALVAGE_ENGINE_ERROR_NOTE = lt(
    "Hinweis: Ein Engine-Fehler hat die Analyse unterbrochen, berichtet "
    "wird nur die bereits gesicherte Tool-Evidenz.",
    "Note: an engine error interrupted the analysis. Only the tool "
    "evidence already secured is reported.",
)

#: Message for a language model timeout after the corpus query succeeds.
_SALVAGE_MODELL_TIMEOUT_NOTE = lt(
    "Hinweis: Das Sprachmodell hat nicht rechtzeitig geantwortet. Die "
    "Korpusabfragen selbst sind vollständig durchgelaufen, die "
    "berichteten Zahlen und Belegzeilen stammen aus ihnen.",
    "Note: the language model did not answer in time. The corpus "
    "queries themselves ran to completion, and the reported numbers and "
    "concordance lines come from them.",
)

#: Woran ein Modell-Timeout im Fehlertext zu erkennen ist. Bewusst eng:
#: was hier nicht passt, bleibt beim allgemeinen Engine-Satz, denn eine
#: falsche Entwarnung waere schlimmer als eine zu vorsichtige Meldung.
_MODELL_TIMEOUT_MARKER = (
    "llm-endpunkt",
    "llm endpunkt",
    "nicht rechtzeitig geantwortet",
    "zeitlimit",
    "timeout",
    "readtimeout",
    # Der Wortlaut der Wanduhr-Wache im Strom-Helfer. Er fehlte hier, und
    # der eigene Test hat es gefunden: ein Aufruf, der das Per-Call-Limit
    # reisst, ist per Definition ein nicht zurueckgekehrtes Modell.
    "per-call-limit",
)


def _salvage_abbruch_hinweis(error_text: str | None) -> str:
    """Der Satz, der den Grund des Abbruchs benennt, statt ihn zu raten."""

    gesenkt = str(error_text or "").casefold()
    if any(marker in gesenkt for marker in _MODELL_TIMEOUT_MARKER):
        return _SALVAGE_MODELL_TIMEOUT_NOTE
    return _SALVAGE_ENGINE_ERROR_NOTE


def _copilot_timeout_salvage_text(
    partial_text: str,
    last_tool_result: dict[str, Any] | None,
    orch: Any,
    *,
    timed_out: bool = True,
    annotate: bool = True,
    engine_error: bool = False,
    error_text: str | None = None,
) -> str | None:
    """Build a grounded partial reply from work already computed at timeout.

    Finding 14: when the wall-clock backstop fires before the LLM produced its
    final natural-language summary, the underlying tool result is often already
    in hand. Prefer any streamed assistant text; otherwise fall back to the last
    tool result frame, then to the orchestrator's recent tool-result summaries.
    Returns ``None`` when there is genuinely nothing to salvage (so the caller
    keeps the plain timeout error) — a non-``None`` return therefore reliably
    means real, evidence-backed work is in hand.

    Haertung r2, Fix 4: the ``⚠️ Zeitlimit erreicht`` banner is prepended ONLY
    when ``timed_out`` (a genuine wall-clock backstop). A non-time terminal
    error that still has computed work in hand is salvaged WITHOUT the timeout
    banner, so a round/step-capped or transport-failed turn is never mislabeled
    as a timeout.

    Haertung r3, Fix 1/2: with ``annotate=False`` the salvage text carries NO
    in-band banner at all. The caller uses this when it will land the answer as
    a clean ``completed`` (evidence-backed) with a single honest annotation in a
    separate ``copilot.grounding`` event, so the reader never sees a
    ``vorzeitig beendet``/``Zeitlimit`` prefix on what is the complete, bounded
    answer for that turn. The default keeps the banner for backward compatible
    callers (and the deterministic salvage markdown already carries its own
    honest "vor der vollstaendigen Verifikation beendet" note either way).

    H10/G4: ``engine_error=True`` haengt genau EINEN Satz an, der den Grund
    (Engine-Ausfall statt Zeit) ehrlich nennt. Zusaetzlich landet ein zu
    kurzer gestreamter Teiltext (Fragment-Underclaiming) bevorzugt in der
    rezept-/deliverable-bewussten Todespfad-Landung des Orchestrators,
    wenn eine existiert.
    """
    notice = (
        lt(
            "⚠️ Zeitlimit erreicht, bevor die vollständige Antwort fertig "
            "war. Hier sind die bereits berechneten Ergebnisse:",
            "⚠️ Time limit reached before the full answer was ready. "
            "These are the results computed so far:",
        )
        if timed_out
        else lt(
            "Die Antwort wurde vorzeitig beendet. Hier sind die bereits "
            "berechneten, belegten Ergebnisse:",
            "The answer ended early. These are the results computed so far, "
            "with their evidence:",
        )
    )

    abbruch_hinweis = _salvage_abbruch_hinweis(error_text)

    def _wrap(body: str) -> str:
        # ``+`` (not an f-string) keeps both languages of the notices.
        if engine_error and abbruch_hinweis not in body:
            body = body.rstrip() + "\n\n" + abbruch_hinweis
        return notice + "\n\n" + body if annotate else body

    def _death_landing() -> str | None:
        build_landing = getattr(orch, "build_death_landing_markdown", None)
        if not callable(build_landing):
            return None
        try:
            landing = build_landing()
        except Exception:
            logger.exception("Todespfad-Landung fehlgeschlagen")
            return None
        if isinstance(landing, str) and landing.strip():
            return landing.strip()
        return None

    text = (partial_text or "").strip()
    if text:
        # Resolve {{ev:}} markers, drop placeholder sentences and trim an
        # unfinished final sentence without another model call.
        resolved = _salvage_resolve_partial_text(text, orch)
        # Use a recipe-aware answer when sufficient visible evidence is
        # available instead of returning a short fragment.
        if len(resolved.strip()) < _SALVAGE_FRAGMENT_MIN_CHARS:
            landing = _death_landing()
            if landing:
                return _wrap(landing)
        return _wrap(resolved)

    # K1 (Umbau 4): Vor jedem Roh-JSON-Fallback zuerst die deterministische
    # Markdown-Antwort aus den gesammelten ObservedFacts bauen. Zahlen
    # stammen damit per Konstruktion aus dem Tool-Output, und der Text
    # benennt ehrlich, dass die Verifikation nicht mehr abgeschlossen wurde.
    build_salvage = getattr(orch, "build_salvage_markdown", None)
    if callable(build_salvage):
        try:
            salvage_markdown = build_salvage()
        except Exception:
            salvage_markdown = None
        if isinstance(salvage_markdown, str) and salvage_markdown.strip():
            return _wrap(salvage_markdown.strip())

    def _format_tool_result(tr: dict[str, Any]) -> str | None:
        name = str(tr.get("toolName") or tr.get("tool") or "Tool").strip()
        output = tr.get("output")
        if output is None:
            output = tr.get("summary")
        if output is None:
            return None
        # Results with error, empty or unavailable status provide no content
        # for a recovered answer. Return None so the caller tries other tool
        # summaries and then the timeout or failure message. Keep diagnostics
        # in tool messages rather than emitting raw error JSON in the answer.
        if isinstance(output, Mapping) and str(
            output.get("status") or ""
        ).strip().casefold() in (
            "error", "failed", "failure", "empty", "unavailable",
        ):
            return None
        rendered = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        rendered = rendered.strip()
        if not rendered:
            return None
        if len(rendered) > 1200:
            rendered = rendered[:1200] + " ..."
        return f"{name}: {rendered}"

    if isinstance(last_tool_result, dict):
        rendered = _format_tool_result(last_tool_result)
        if rendered:
            return _wrap(rendered)

    recent = getattr(orch, "_recent_tool_results", None)
    if isinstance(recent, list):
        summaries: list[str] = []
        for entry in reversed(recent):
            if not isinstance(entry, dict):
                continue
            summary = str(entry.get("summary") or "").strip()
            if summary:
                summaries.append(summary)
            if len(summaries) >= 3:
                break
        if summaries:
            summaries.reverse()
            return _wrap("\n".join(f"- {s}" for s in summaries))

    return None


api_router.include_router(copilot_routes.router)


# --------------------------------------------------------------------------- #
# Copilot Control Frame Endpoints                                              #
# --------------------------------------------------------------------------- #


@api_router.post(
    "/prefs/update",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def update_pref(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {"summary": "Prefs", "value": {"theme": "light", "project": "default"}},
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    user_token = token or payload.get("token")
    project = payload.get("project", "default")
    key = _user_key(user_token, project)
    updates: Dict[str, str] = {}
    for k, v in payload.items():
        if k in {"token", "project"}:
            continue
        updates[k] = v
    try:
        prefs.set_prefs(key, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    return {"status": "ok"}


@api_router.get(
    "/prefs",
    responses={
        200: {"content": {"application/json": {"example": {"theme": "light", "project": "default"}}}}
    },
)
async def get_prefs(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
    project: str = "default",
) -> Dict[str, object]:
    key = _user_key(token, project)
    return prefs.get_state(key)


def _ws_ticket_username(websocket: WebSocket, token: str | None) -> str | None:
    """A7: resolve a one-time ``?ticket=`` principal for a WS handshake.

    Browsers cannot set an Authorization header on ``new WebSocket()`` and
    release mode refuses query/body tokens, so WS clients mint a short-TTL
    one-time ticket via POST /api/v1/ws-ticket and pass it on the handshake.
    The header-token path stays primary; the ticket is only consulted when no
    token authenticates the connection.
    """
    if token is not None:
        return None
    ticket = None
    with contextlib.suppress(Exception):
        ticket = websocket.query_params.get("ticket")
    return auth.redeem_ws_ticket(ticket)


async def _ws_deny(websocket: WebSocket, exc: HTTPException) -> None:
    """Reject a WS handshake with a policy-violation close (1008).

    Raising HTTPException out of a websocket route has no handler in the
    websocket scope — the handshake neither completes nor fails cleanly.
    A close frame is the correct WS-level denial.
    """
    with contextlib.suppress(Exception):
        await websocket.close(code=1008, reason=str(exc.detail)[:120])


api_router.include_router(copilot_ws_routes.router)

# Keep the document router independent from the server module while preserving
# the existing runtime and monkeypatch seams through call-time lookups.
documents_routes.bind_document_runtime(
    get_index=lambda: get_index(),
    get_corpus=lambda name: get_corpus(name),
    doc_id_for_position=lambda idx, pos, bounds: _doc_id_for_position(idx, pos, bounds),
)


app.include_router(api_router, prefix="/api/v1")
app.include_router(mcp_router, prefix="/mcp")

# S5b Single-Command-Start: gebautes Vue-Frontend (candyconc-web/dist) als SPA
# auf '/' ausliefern, falls vorhanden. Bewusst NACH allen API-/MCP-/WS-Routen
# registriert, damit jede echte Route Vorrang behält; ohne Dist bleibt das
# Verhalten byte-gleich (GET / und unbekannte Pfade -> 404 problem+json).
from . import frontend_static as _frontend_static  # noqa: E402
from . import docs_static as _docs_static  # noqa: E402

# The bundled user documentation (help menu) under /docs/, before the SPA.
DOCS_DIST = _docs_static.install_docs(app)
FRONTEND_DIST = _frontend_static.install_frontend(app)
