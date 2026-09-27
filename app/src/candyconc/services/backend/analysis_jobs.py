from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, AsyncGenerator, Dict

from candyconc.config import APP_CONFIG
from candyconc.i18n import LocalizedText, exception_text, localize, lt


_JOB_LIMIT = 256
_DEFAULT_RESULT_MAX_BYTES = 128 * 1024 * 1024
_TERMINAL_STATUSES = {"done", "error", "cancelled"}
_RESULT_DISCARD_MESSAGES = {
    "result_size_exceeds_storage_cap": lt(
        "Analyse abgeschlossen, aber das Ergebnis wurde wegen der "
        "Speichergrenze nicht im Job gespeichert.",
        "Analysis finished, but the result was not stored in the job "
        "because of the storage limit.",
    ),
}

# Test/runtime override: when set to an int it wins over config (tests
# monkeypatch this). ``None`` means "read the cap from config at call time".
_RESULT_MAX_BYTES: int | None = None


def _load_result_max_bytes() -> int:
    """Read the result-size cap at call time.

    Precedence: an explicit module-level ``_RESULT_MAX_BYTES`` override (tests),
    then ``APP_CONFIG`` (single source) so ``config.set()`` overrides and proper
    env>pyproject precedence are honored instead of reading ``os.environ``.
    """

    if _RESULT_MAX_BYTES is not None:
        return _RESULT_MAX_BYTES
    raw = getattr(APP_CONFIG, "CANDYCONC_ANALYSIS_RESULT_MAX_BYTES", None)
    if raw is None:
        return _DEFAULT_RESULT_MAX_BYTES
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RESULT_MAX_BYTES


def _estimate_result_bytes(value: Any, *, _seen: set[int] | None = None) -> int:
    if _seen is None:
        _seen = set()
    value_id = id(value)
    if value_id in _seen:
        return 0
    _seen.add(value_id)

    if value is None:
        return 4
    if isinstance(value, bool):
        return 4 if value else 5
    if isinstance(value, (int, float)):
        return len(str(value).encode("utf-8"))
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return len(value)

    nbytes = getattr(value, "nbytes", None)
    if nbytes is not None:
        try:
            return int(nbytes)
        except (TypeError, ValueError):
            pass

    if isinstance(value, Mapping):
        return sum(
            _estimate_result_bytes(key, _seen=_seen)
            + _estimate_result_bytes(item, _seen=_seen)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return sum(_estimate_result_bytes(item, _seen=_seen) for item in value)

    return len(repr(value).encode("utf-8"))


def result_readiness(job: "AnalysisJob") -> str:
    """Classify whether a terminal analysis job has loadable row results."""

    if job.result_available:
        return "available"
    if job.result_discarded:
        return "discarded"
    if job.status == "done":
        return "unavailable"
    if job.status == "error":
        return "error"
    if job.status == "cancelled":
        return "cancelled"
    return "pending"


def rows_state(job: "AnalysisJob") -> str:
    """Canonical rows endpoint state exposed to API consumers."""

    readiness = result_readiness(job)
    if readiness == "unavailable":
        return "not_stored"
    return readiness


def result_warnings(job: "AnalysisJob") -> list[str]:
    readiness = result_readiness(job)
    if readiness == "discarded":
        reason = job.result_discard_reason or ""
        return [
            _RESULT_DISCARD_MESSAGES.get(
                reason,
                lt(
                    "Analyse abgeschlossen, aber das Ergebnis wurde nicht im Job gespeichert.",
                    "Analysis finished, but the result was not stored in the job.",
                ),
            )
        ]
    if readiness == "unavailable":
        return [
            lt(
                "Analyse abgeschlossen, aber im Job-Speicher liegen keine Ergebniszeilen vor.",
                "Analysis finished, but the job store holds no result rows.",
            )
        ]
    return []


@dataclass
class AnalysisJob:
    job_id: str
    kind: str
    corpus: str
    params: Dict[str, Any]
    status: str = "queued"
    progress: int = 0
    message: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    total_rows: int | None = None
    error: str | None = None
    result: Dict[str, Any] | None = None
    result_bytes: int | None = None
    result_max_bytes: int = field(default_factory=_load_result_max_bytes)
    result_available: bool = False
    result_discarded: bool = False
    result_discard_reason: str | None = None
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task | None = None


_JOBS: "OrderedDict[str, AnalysisJob]" = OrderedDict()


def _evict_if_needed() -> None:
    if len(_JOBS) <= _JOB_LIMIT:
        return
    # Nur fertige Jobs duerfen rausfliegen.
    for job_id, job in list(_JOBS.items()):
        if job.status in _TERMINAL_STATUSES:
            _JOBS.pop(job_id, None)
            if len(_JOBS) <= _JOB_LIMIT:
                return
    # Wenn wir hier landen, sind zu viele laufende Jobs aktiv.
    raise RuntimeError(
        lt(
            "Zu viele laufende Analysejobs. Bitte Jobs abschließen.",
            "Too many running analysis jobs. Finish some jobs first.",
        )
    )


def create(kind: str, corpus: str, params: Dict[str, Any]) -> AnalysisJob:
    job_id = uuid.uuid4().hex
    job = AnalysisJob(job_id=job_id, kind=kind, corpus=corpus, params=params)
    _JOBS[job_id] = job
    _JOBS.move_to_end(job_id)
    _evict_if_needed()
    return job


def _exception_repr(exc: BaseException) -> str:
    """``repr(exc)`` that keeps both languages of a bilingual message."""
    text = exception_text(exc)
    if isinstance(text, LocalizedText) and len(exc.args) == 1:
        return lt("{name}({text!r})", "{name}({text!r})").format(name=type(exc).__name__, text=text)
    return repr(exc)


def _task_endete(job_id: str, task: "asyncio.Task") -> None:
    """Record a terminal job state when its task finishes without a result.

CancelledError is not caught by Exception, and loop shutdown can cancel
tasks outside the runner. The completion callback records cancellation
after the task has ended while preserving its last progress and message."""

    job = _JOBS.get(job_id)
    if job is None or job.status in _TERMINAL_STATUSES:
        return
    if task.cancelled():
        grund = lt("Der Job-Task wurde abgebrochen", "The job task was cancelled")
    else:
        fehler = task.exception()
        if fehler is None:
            grund = lt("Der Job-Task endete ohne Ergebnis", "The job task ended without a result")
        else:
            grund = lt("Der Job-Task endete an {error}", "The job task ended with {error}").format(
                error=_exception_repr(fehler)
            )
    # Preserve the last progress and message so cancellation records how far
    # the job ran.
    job.error = lt(
        "{reason}. Zuletzt: progress={progress} message={message!r}",
        "{reason}. Last state: progress={progress} message={message!r}",
    ).format(reason=grund, progress=job.progress, message=job.message)
    job.result = None
    job.result_bytes = None
    job.result_available = False
    job.result_discarded = False
    job.result_discard_reason = None
    update(job_id, progress=job.progress, message="error: " + job.error, status="error")


def attach_task(job_id: str, task: asyncio.Task) -> None:
    job = get(job_id)
    job.task = task
    # EINE Naht fuer alle acht Job-Runner. Sie einzeln um ein
    # ``except asyncio.CancelledError`` zu erweitern liesse jede neue
    # Runner-Naht wieder offen, und beim Schleifenabbau kommt der Runner
    # ohnehin nicht mehr zum Zug.
    task.add_done_callback(partial(_task_endete, job_id))


def get(job_id: str) -> AnalysisJob:
    job = _JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    _JOBS.move_to_end(job_id)
    return job


def update(job_id: str, *, progress: int, message: str, status: str | None = None) -> None:
    job = get(job_id)
    if job.status == "cancelled":
        return
    job.progress = int(max(0, min(100, progress)))
    # A bilingual message stays a pair until a snapshot or stream renders it.
    job.message = message if isinstance(message, LocalizedText) else str(message)
    if status is not None:
        job.status = str(status)
    job.updated_at = time.time()
    event = {
        "job_id": job.job_id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "total_rows": job.total_rows,
        "error": job.error,
        "result_bytes": job.result_bytes,
        "result_max_bytes": job.result_max_bytes,
        "result_available": job.result_available,
        "result_discarded": job.result_discarded,
        "result_discard_reason": job.result_discard_reason,
        "result_readiness": result_readiness(job),
        "rows_state": rows_state(job),
        "result_warnings": result_warnings(job),
    }
    for subscriber in tuple(job.subscribers):
        if subscriber.full():
            subscriber.get_nowait()
        subscriber.put_nowait(event)


def set_result(job_id: str, *, result: Dict[str, Any], total_rows: int) -> None:
    job = get(job_id)
    if job.status == "cancelled":
        return
    result_bytes = _estimate_result_bytes(result)
    job.result_bytes = result_bytes
    result_max_bytes = _load_result_max_bytes()
    job.result_max_bytes = result_max_bytes
    if result_max_bytes >= 0 and result_bytes > result_max_bytes:
        job.result = None
        job.result_available = False
        job.result_discarded = True
        job.result_discard_reason = "result_size_exceeds_storage_cap"
        message = "done (result discarded: storage cap exceeded)"
    else:
        job.result = result
        job.result_available = True
        job.result_discarded = False
        job.result_discard_reason = None
        message = "done"
    job.total_rows = int(total_rows)
    job.error = None
    update(job_id, progress=100, message=message, status="done")


def set_error(job_id: str, exc: Exception) -> None:
    job = get(job_id)
    if job.status == "cancelled":
        return
    job.error = exception_text(exc)
    job.result = None
    job.result_bytes = None
    job.result_available = False
    job.result_discarded = False
    job.result_discard_reason = None
    update(job_id, progress=100, message="error: " + job.error, status="error")


def cancel(job_id: str, reason: str = "cancelled") -> None:
    job = get(job_id)
    if job.status in _TERMINAL_STATUSES:
        return
    if job.task and not job.task.done():
        job.task.cancel()
    job.error = reason
    job.result = None
    job.result_bytes = None
    job.result_available = False
    job.result_discarded = False
    job.result_discard_reason = None
    update(job_id, progress=job.progress, message=reason, status="cancelled")


def snapshot(job_id: str) -> Dict[str, Any]:
    """Current job state with its texts in the language of the current request."""
    job = get(job_id)
    return localize({
        "job_id": job.job_id,
        "kind": job.kind,
        "corpus": job.corpus,
        "params": job.params,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "total_rows": job.total_rows,
        "error": job.error,
        "result_bytes": job.result_bytes,
        "result_max_bytes": job.result_max_bytes,
        "result_available": job.result_available,
        "result_discarded": job.result_discarded,
        "result_discard_reason": job.result_discard_reason,
        "result_readiness": result_readiness(job),
        "rows_state": rows_state(job),
        "result_warnings": result_warnings(job),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    })


async def stream(job_id: str) -> AsyncGenerator[dict[str, Any], None]:
    job = get(job_id)
    subscriber: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    job.subscribers.add(subscriber)
    try:
        # Every subscriber starts from the current state, then receives its own
        # coalesced updates. One browser must never consume another's progress.
        initial = snapshot(job_id)
        yield initial
        if initial["status"] in _TERMINAL_STATUSES:
            return
        while True:
            item = await subscriber.get()
            # Rendered in the language of the subscribing connection.
            yield localize(item)
            if item.get("status") in _TERMINAL_STATUSES:
                return
    finally:
        job.subscribers.discard(subscriber)


__all__ = [
    "AnalysisJob",
    "attach_task",
    "cancel",
    "create",
    "get",
    "result_readiness",
    "result_warnings",
    "rows_state",
    "set_error",
    "set_result",
    "snapshot",
    "stream",
    "update",
]
