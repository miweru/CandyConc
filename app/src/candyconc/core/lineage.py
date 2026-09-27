from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

Project = Any


def _hash(data: Any) -> str:
    """Return SHA256 hash for JSON-serialisable ``data``."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def log_tool(
    project: Project | None,
    name: str,
    params: Dict[str, Any],
    result: Any,
    *,
    started_at: float | None = None,
    finished_at: float | None = None,
) -> Dict[str, Any]:
    """Record a tool execution in ``project`` and return the logged entry."""
    record: Dict[str, Any] = {"tool": name, "params": params}
    if started_at is not None:
        record["started_at"] = started_at
    if finished_at is not None:
        record["finished_at"] = finished_at
    record["sha256"] = _hash(result)
    if project is not None:
        project.log_op(json.dumps(record))
    return record


def log_task(
    project: Project | None,
    name: str,
    result: Any,
    **params: Any,
) -> Dict[str, Any]:
    """Record a task execution in ``project`` and return the logged entry."""
    record: Dict[str, Any] = {"task": name, **params}
    record["sha256"] = _hash(result)
    if project is not None:
        project.log_op(json.dumps(record))
    return record


def to_jsonld(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a JSON-LD representation for the given lineage ``records``."""
    graph = []
    for i, step in enumerate(records, 1):
        graph.append(
            {
                "@id": f"step{i}",
                "name": step.get("tool") or step.get("task"),
                "sha256": step.get("sha256"),
                "params": step.get("params")
                or {k: v for k, v in step.items() if k not in {"sha256", "tool", "task"}},
            }
        )
    return {"@context": {"sha256": "http://www.w3.org/2001/04/xmlenc#sha256"}, "@graph": graph}
