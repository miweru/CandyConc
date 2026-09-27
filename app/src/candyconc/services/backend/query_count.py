"""Shared query-count cache, cancellation state and error classification.

Asynchronous callers acquire the asyncio lock before the thread RLock.
Keep watcher, cancellation grace, TTL and cache trimming state together.
Callers supply the cache key and computation function so they retain
control over server-owned query dependencies and overrides."""

import re
import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict

from fastapi import HTTPException

from candyconc.config import get as get_config
from candyconc.core.word_vectors import SERVICE_ERROR_MESSAGE, UNAVAILABLE_MESSAGE
from candyconc.entrypoints.errors import ApiError
from candyconc.i18n import LocalizedText, exception_text, lt

from .textnorm import _normalize_query_key

_QUERY_COUNT_TTL_SEC = int(get_config("CANDYCONC_QUERY_COUNT_TTL", "900"))
_QUERY_COUNT_MAX = int(get_config("CANDYCONC_QUERY_COUNT_MAX", "256"))
_QUERY_COUNT_CANCEL_GRACE_SEC = float(
    get_config("CANDYCONC_QUERY_COUNT_CANCEL_GRACE", "6")
)
_CQL_COUNT_PROBE_HARD_MAX = 2_147_483_647


@dataclass(slots=True)
class _QueryCountState:
    task: asyncio.Task | None
    result: tuple[int, float, bool] | None
    error: str | None
    started_at: float
    last_access: float
    watchers: int
    cancel_task: asyncio.Task | None


# Count-cache key carries an extra build-signature + case-insensitivity flag, so
# the tuple is 7 wide: (corpus, term, date, genre, docset_id, build_sig, ci).
_QueryCountKey = tuple[str, str, str, str, str, str, str]
_QUERY_COUNT_CACHE: dict[_QueryCountKey, _QueryCountState] = {}
_QUERY_COUNT_LOCK = asyncio.Lock()
_QUERY_COUNT_THREAD_LOCK = threading.RLock()


def _query_count_key(
    term: str,
    corpus: str,
    date: str | None,
    genre: str | None,
    docset_id: str | None,
    *,
    build_sig: str = "",
    case_insensitive: bool = True,
) -> _QueryCountKey:
    return (
        str(corpus),
        _normalize_query_key(term),
        str((date or "").strip()),
        str((genre or "").strip()),
        str((docset_id or "").strip()),
        # Build signature changes on in-place rebuild so a stale count for the
        # same corpus name is never served (D8 #3).
        str(build_sig or ""),
        # Case-insensitivity is part of the result identity (D8 #5).
        "ci" if case_insensitive else "cs",
    )


def _cql_count_probe_limit(count_limit: int) -> int:
    count_limit = max(1, int(count_limit))
    if count_limit >= _CQL_COUNT_PROBE_HARD_MAX:
        return count_limit
    return count_limit + 1


#: ``Expected "]"``, ``Expected ")"`` und Verwandte aus dem Parser.
_ERWARTETES_ZEICHEN = re.compile(r'^Expected ["\'\)\]\}>,]')


def _is_query_user_error(message: str) -> bool:
    return (
        "Query Parser Fehler" in message
        or "Unexpected token" in message
        # Classify parser diagnostics as input errors so malformed queries return
        # ToolInputError rather than HTTP 500. New parser messages need matching
        # classification here until the parser exposes a dedicated error type.
        or "Unexpected end of input" in message
        or "Expected relation name" in message
        or "Invalid attribute filter" in message
        # domain/query_parser.wortsuche_hinweis: eine Oder- oder
        # Attributschreibweise in der Wortsuche, die als Wortform leer bleibt.
        or message.startswith("Wortsuche: ")
        # Attributfilter der Wortsuche ([farbe=rot]), Gegenstueck zur
        # CQL-Meldung "Unbekanntes Attribut in CQL" weiter unten.
        or message.startswith("Unbekanntes Attribut: ")
        # NICHT startswith("Expected "): das wuerde auch einen echten
        # Serverfehler dieser Form zum Aufruferfehler erklaeren. Der
        # Parser erwartet an dieser Stelle immer ein Satzzeichen.
        or bool(_ERWARTETES_ZEICHEN.match(message))
        or "Parse" in message
        or "Keine ähnlichen Korpuswörter" in message
        or "Keine ähnlichen Wörter" in message
        # Malformed CQL / regex / wildcard input is the caller's fault → 400, not
        # a 500 server error (D8 #7). "Muster zu komplex" is Track D1's new regex
        # ParseError message.
        or "Unbekanntes Attribut in CQL" in message
        # Finding 35: an out-of-tagset pos value (e.g. STTS "NN" on a UPOS corpus)
        # is a caller mistake → clean 400 with the valid-tag hint, not a 500.
        or "Unbekanntes pos-Tag in CQL" in message
        # Finding 17: negated-regex is rejected loudly (engine limitation) → 400.
        or "Regex mit '!='" in message
        or "Ungültiges Regex Muster" in message
        # An expression that matches only the empty string is an input error.
        or "trifft nur die leere Zeichenfolge" in message
        or "Regex Treffer zu gross" in message
        # Dieselbe Absage aus dem Wildcard-Pfad. Sie fehlte hier, und ein
        # zu weites Wildcard-Muster kam damit als 500 zurueck, also als
        # Serverfehler, obwohl der Aufrufer das Muster gewaehlt hat.
        or "Wildcard Treffer zu gross" in message
        # Dieselbe Art Absage fuer NOT ueber einem grossen Korpus (domain/
        # query_eval, CANDYCONC_NOT_MAX_TOKENS). Die Meldung nennt den Ausweg.
        or "NOT Query zu gross" in message
        or "Muster zu komplex" in message
        # A ReDoS-rejected pattern (nested unbounded quantifiers, e.g. (a+)+) is a
        # caller mistake the DoS guard correctly refuses → 400, not a leaked 500
        # (COPILOT-REDOS-CLASSIFY-500). The guard itself works; only the status was wrong.
        or "verschachtelten unbeschraenkten Quantoren" in message
        # An unknown KWIC sort field (e.g. sort_by="99X") is caller input → 400, not 500
        # (COPILOT-BADSORT-500). kwic_renderer raises this with the valid-field hint.
        or "Unbekanntes Sortierfeld" in message
    )


# Genuine server-state RuntimeErrors (missing / not-yet-built index artefacts,
# in-flight rebuild, registry corpus not ready). These are NOT the caller's
# fault: the request is well-formed but the server cannot serve it right now.
# They must surface as 503 (Service Unavailable), never as a 400 (which blames
# the client) or a leaked 500 (which hides the "rebuild the index" remedy).
# Detected by the stable German operator-facing phrases the index/meta/docset
# paths raise (e.g. server.py:854/883/2177/2202/2514/9141 ...).
_SERVER_STATE_ERROR_MARKERS = (
    "Bitte Index neu bauen",  # missing word/meta/sentence/doc artefacts
    "Indexpfad existiert nicht",  # _resolve_index_path / _validate_index_path
    "Aktives Registry-Korpus ist nicht bereit",
    "Kein Index konfiguriert",  # _resolve_index_path no-config fallthrough
    "Dokumentgrenzen fehlen",
    "Dokumentgrenzen leer",
    "Meta Index fehlt",
    "Satzgrenzen fehlen",
    "Satzgrenzen leer",
    "Word Lexikon fehlt",
    "Wortlexikon fehlt",
    "Word Stream fehlt",
    "Word Lexikon Strom fehlt",
)


def _is_server_state_error(message: str) -> bool:
    """True when a RuntimeError reflects unserveable server state, not bad input.

    Used to map index-not-ready / rebuild-needed RuntimeErrors to HTTP 503 rather
    than letting them leak as a 500 (god-module finding D) or be miscategorised as
    a client 400. ``get_index()`` keeps raising the raw RuntimeError; the HTTP
    boundary classifies it here.
    """
    if not message:
        return False
    return any(marker in message for marker in _SERVER_STATE_ERROR_MARKERS)


def _is_word_vectors_unavailable(message: str) -> bool:
    """True for a request that needs word vectors on a corpus without them (core.word_vectors).

    The request is well-formed but does not fit the corpus, so the routes
    answer 422, like a document set of another corpus. The German text of
    UNAVAILABLE_MESSAGE is part of every such message (``str`` of the pair).
    """
    return str(UNAVAILABLE_MESSAGE) in message


def _is_word_vectors_service_error(message: str) -> bool:
    """True when the server cannot load the word vectors of the corpus (503)."""
    return str(SERVICE_ERROR_MESSAGE) in message


def _localized(text: str) -> LocalizedText:
    return text if isinstance(text, LocalizedText) else lt(text, text)


def _word_vectors_error(exc: BaseException) -> ApiError | None:
    """The API error for missing word vectors, or None.

    422 ``word_vectors.unavailable`` when the corpus has no word vectors, 503
    ``word_vectors.service_error`` when the server cannot load them (pipeline
    not installed or failing to load). For every route that needs word
    vectors: sim() in queries, the thesaurus, word clusters.
    """
    message = str(exc)
    if _is_word_vectors_unavailable(message):
        return ApiError(422, "word_vectors.unavailable", _localized(exception_text(exc)))
    if _is_word_vectors_service_error(message):
        return ApiError(503, "word_vectors.service_error", _localized(exception_text(exc)))
    return None


def _classify_query_runtime_error(exc: BaseException) -> HTTPException | None:
    """Map a caught query-path RuntimeError/ValueError to an HTTPException, or None.

    Returns a 422 ``word_vectors.unavailable`` for sim() on a corpus without
    word vectors, a 503 ``word_vectors.service_error`` when the server cannot
    load them, a 503 for genuine server-state errors (index not
    ready / rebuild needed), a 400 for caller-fault parse/regex errors, and
    ``None`` when the
    error is neither — in which case the caller should re-raise so it surfaces
    honestly (as a 500 via the registered exception handlers). Centralising this
    means the dozens of query call-sites classify identically instead of each
    inventing a status code.
    """
    msg = str(exc)
    word_vectors_error = _word_vectors_error(exc)
    if word_vectors_error is not None:
        return word_vectors_error
    if _is_server_state_error(msg):
        return HTTPException(status_code=503, detail=exception_text(exc))
    if _is_query_user_error(msg):
        return HTTPException(status_code=400, detail=exception_text(exc))
    return None


def _cleanup_query_count_cache(now: float) -> None:
    if not _QUERY_COUNT_CACHE:
        return
    expired: list[_QueryCountKey] = []
    for key, state in _QUERY_COUNT_CACHE.items():
        if state.watchers > 0:
            continue
        if state.task is not None and not state.task.done():
            continue
        if now - state.last_access > _QUERY_COUNT_TTL_SEC:
            expired.append(key)
    for key in expired:
        _QUERY_COUNT_CACHE.pop(key, None)


def _trim_query_count_cache() -> None:
    if len(_QUERY_COUNT_CACHE) <= _QUERY_COUNT_MAX:
        return
    items = sorted(
        _QUERY_COUNT_CACHE.items(),
        key=lambda kv: ((kv[1].task is not None and not kv[1].task.done()), kv[1].last_access),
    )
    for key, state in items:
        if len(_QUERY_COUNT_CACHE) <= _QUERY_COUNT_MAX:
            break
        if state.watchers > 0:
            continue
        if state.task is not None and not state.task.done():
            continue
        _QUERY_COUNT_CACHE.pop(key, None)
    if len(_QUERY_COUNT_CACHE) > _QUERY_COUNT_MAX:
        items = sorted(_QUERY_COUNT_CACHE.items(), key=lambda kv: kv[1].last_access)
        for key, _ in items:
            if len(_QUERY_COUNT_CACHE) <= _QUERY_COUNT_MAX:
                break
            state = _QUERY_COUNT_CACHE.get(key)
            if state is None:
                continue
            if state.watchers > 0:
                continue
            _QUERY_COUNT_CACHE.pop(key, None)


async def _get_or_create_query_count(
    key: _QueryCountKey,
    *,
    create: bool,
    compute_fn: Callable[[], tuple[int, float, bool]],
    attach: bool,
) -> _QueryCountState | None:
    now = time.monotonic()
    async with _QUERY_COUNT_LOCK:
        with _QUERY_COUNT_THREAD_LOCK:
            _cleanup_query_count_cache(now)
            state = _QUERY_COUNT_CACHE.get(key)
            if state is not None:
                state.last_access = now
                if attach:
                    state.watchers += 1
                    if state.cancel_task is not None and not state.cancel_task.done():
                        state.cancel_task.cancel()
                        state.cancel_task = None
                if state.task is not None and state.task.done() and state.result is None and state.error is None:
                    try:
                        state.result = state.task.result()
                    except asyncio.CancelledError:
                        state.error = "cancelled"
                    except Exception as exc:
                        state.error = exception_text(exc)
                return state
            if not create:
                return None
            task = asyncio.create_task(asyncio.to_thread(compute_fn))
            task.add_done_callback(_record_query_count_outcome)
            state = _QueryCountState(
                task=task,
                result=None,
                error=None,
                started_at=now,
                last_access=now,
                watchers=1 if attach else 0,
                cancel_task=None,
            )
            _QUERY_COUNT_CACHE[key] = state
            _trim_query_count_cache()
            return state


def _record_query_count_outcome(task: asyncio.Task) -> None:
    """Store a finished count on its state, also when no request is waiting.

    Without this a failed count kept its exception inside the task until the
    next poll, and a count nobody polled again logged "Task exception was
    never retrieved".
    """
    with _QUERY_COUNT_THREAD_LOCK:
        for state in _QUERY_COUNT_CACHE.values():
            if state.task is not task:
                continue
            if state.result is not None or state.error is not None:
                return
            if task.cancelled():
                state.error = "cancelled"
                return
            exc = task.exception()
            if exc is not None:
                logging.getLogger(__name__).warning("Query count failed: %s", exc)
                state.error = exception_text(exc)
            else:
                state.result = task.result()
            return
        # Evicted before it finished: still consume the outcome.
        if not task.cancelled():
            task.exception()


async def _release_query_count(key: _QueryCountKey) -> None:
    now = time.monotonic()
    async with _QUERY_COUNT_LOCK:
        with _QUERY_COUNT_THREAD_LOCK:
            state = _QUERY_COUNT_CACHE.get(key)
            if state is None:
                return
            state.last_access = now
            state.watchers = max(0, state.watchers - 1)
            if state.watchers > 0:
                return
            if state.cancel_task is not None and not state.cancel_task.done():
                return
            if state.task is not None and not state.task.done():
                state.cancel_task = asyncio.create_task(_cancel_query_count_after_grace(key))


async def _cancel_query_count_after_grace(key: _QueryCountKey) -> None:
    try:
        await asyncio.sleep(_QUERY_COUNT_CANCEL_GRACE_SEC)
    except asyncio.CancelledError:
        return
    async with _QUERY_COUNT_LOCK:
        with _QUERY_COUNT_THREAD_LOCK:
            state = _QUERY_COUNT_CACHE.get(key)
            if state is None:
                return
            if state.watchers > 0:
                return
            if state.task is not None and not state.task.done():
                state.task.cancel()
            state.cancel_task = None


async def _complete_query_count(
    key: _QueryCountKey,
    *,
    total: int,
    elapsed_ms: float,
    partial: bool,
) -> None:
    now = time.monotonic()
    async with _QUERY_COUNT_LOCK:
        with _QUERY_COUNT_THREAD_LOCK:
            state = _QUERY_COUNT_CACHE.get(key)
            if state is None:
                state = _QueryCountState(
                    task=None,
                    result=(total, elapsed_ms, partial),
                    error=None,
                    started_at=now,
                    last_access=now,
                    watchers=0,
                    cancel_task=None,
                )
                _QUERY_COUNT_CACHE[key] = state
            else:
                state.last_access = now
                state.result = (total, elapsed_ms, partial)
                state.error = None
                if state.task is not None and not state.task.done():
                    state.task.cancel()
                state.task = None
                if state.cancel_task is not None and not state.cancel_task.done():
                    state.cancel_task.cancel()
                    state.cancel_task = None
            _trim_query_count_cache()


def _query_count_error_envelope(error: str) -> Dict[str, Any]:
    """Map a stored count error to an honest status envelope.

    A genuine ``asyncio`` cancellation is reported as ``cancelled`` so callers
    can distinguish it from a real computation failure (``error``). Everything
    else surfaces as ``error`` with the underlying message.
    """
    if error == "cancelled":
        return {"status": "cancelled"}
    return {"status": "error", "message": error}


def _query_count_error_response(error: str) -> Dict[str, Any]:
    """Surface a stored count error with the SAME transport the rows path uses.

    A malformed CQL / regex parse error is the caller's fault: the GET /query
    rows path and the copilot query_count / run_cqlf_query tools all answer a true
    4xx for it (via ``_classify_query_runtime_error`` / ``_reraise_query_user_error``).
    /query/count previously returned the same honest German message inside a 200
    ``{"status":"error"}`` envelope, so the same bad input read 200 here but 4xx on
    the sibling surfaces. Classify here too — raise the matching 4xx (or 503 for a
    server-state error) — keeping the message identical. A genuine cancellation and
    any unclassified failure keep the existing 200 envelope.
    """
    mapped = _classify_query_runtime_error(ValueError(error))
    if mapped is not None:
        raise mapped
    return _query_count_error_envelope(error)


def _resolve_query_count_result(state: _QueryCountState) -> tuple[int, float, bool] | None:
    if state.result is not None:
        return state.result
    if state.task is None or not state.task.done():
        return None
    try:
        state.result = state.task.result()
        return state.result
    except asyncio.CancelledError:
        state.error = "cancelled"
        return None
    except Exception as exc:
        if state.error is None:
            logging.exception("Query count failed")
        state.error = exception_text(exc)
        return None
