"""In-process lifecycle snapshots for backend-owned product operations.

The registry is intentionally small and dependency-free. It gives long-running
operations a durable-enough status object for the current backend process,
without pretending that a queued acknowledgement is already a completed result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from candyconc.i18n import localize, lt


OperationRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "stale"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class OperationRun:
    run_id: str
    operation_id: str
    source_id: str
    status: OperationRunStatus
    kind: str = "operation"
    label: str = ""
    phase: str = ""
    progress: int | None = None
    message: str = ""
    error: str = ""
    result_ref: str = ""
    readiness: str = "pending"
    warnings: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Status in the language of the current request (texts may be bilingual pairs)."""
        return localize({
            "run_id": self.run_id,
            "job_id": self.run_id,
            "operation_id": self.operation_id,
            "source_id": self.source_id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "error": self.error or None,
            "result_ref": self.result_ref or None,
            "readiness": self.readiness,
            "warnings": list(self.warnings),
            "evidence": dict(self.evidence),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
        })


class OperationRunRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runs: dict[str, OperationRun] = {}

    def create(
        self,
        *,
        operation_id: str,
        source_id: str,
        kind: str = "operation",
        label: str = "",
        message: str = lt("Operation wurde eingereiht.", "Operation queued."),
        progress: int | None = 0,
    ) -> OperationRun:
        run = OperationRun(
            run_id=uuid4().hex,
            operation_id=operation_id,
            source_id=source_id,
            kind=kind,
            label=label,
            status="queued",
            phase="queued",
            progress=progress,
            message=message,
            readiness="pending",
        )
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> OperationRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()

    def find_active(self, *, operation_id: str, source_id: str) -> OperationRun | None:
        with self._lock:
            for run in self._runs.values():
                if (
                    run.operation_id == operation_id
                    and run.source_id == source_id
                    and run.status in {"queued", "running"}
                ):
                    return run
        return None

    def update(self, run_id: str, **patch: Any) -> OperationRun | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            for key, value in patch.items():
                if not hasattr(run, key):
                    continue
                setattr(run, key, value)
            run.updated_at = _now_iso()
            if run.status in {"succeeded", "failed", "cancelled", "stale"} and not run.finished_at:
                run.finished_at = run.updated_at
            return run

    def mark_running(self, run_id: str, *, phase: str, message: str, progress: int | None = None) -> OperationRun | None:
        return self.update(
            run_id,
            status="running",
            phase=phase,
            message=message,
            progress=progress,
            error="",
            readiness="pending",
        )

    def mark_succeeded(
        self,
        run_id: str,
        *,
        message: str,
        result_ref: str = "",
        readiness: str = "verified",
        warnings: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> OperationRun | None:
        return self.update(
            run_id,
            status="succeeded",
            phase="verified",
            progress=100,
            message=message,
            error="",
            result_ref=result_ref,
            readiness=readiness,
            warnings=warnings or [],
            evidence=evidence or {},
        )

    def mark_failed(self, run_id: str, *, error: str, phase: str = "failed") -> OperationRun | None:
        return self.update(
            run_id,
            status="failed",
            phase=phase,
            message=error,
            error=error,
            readiness="failed",
        )

    def mark_cancelled(
        self,
        run_id: str,
        *,
        message: str = lt("Operation wurde abgebrochen.", "Operation cancelled."),
    ) -> OperationRun | None:
        return self.update(
            run_id,
            status="cancelled",
            phase="cancelled",
            message=message,
            error="",
            readiness="cancelled",
        )

    def mark_stale(
        self,
        run_id: str,
        *,
        message: str = lt("Operation-Status ist nicht mehr verlässlich.", "Operation status is no longer reliable."),
    ) -> OperationRun | None:
        return self.update(
            run_id,
            status="stale",
            phase="stale",
            message=message,
            error=message,
            readiness="stale",
            warnings=[message],
        )


operation_run_registry = OperationRunRegistry()


__all__ = ["OperationRun", "OperationRunRegistry", "operation_run_registry"]
