from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List
import threading

from candyconc.config import get as get_config

from candyconc.paths import data_dir  # noqa: E402

_TRACES_PATH = data_dir() / "traces.jsonl"
#: Size cap for the trace file; one rotated generation is kept
#: (``traces.jsonl`` -> ``traces.jsonl.1``).
_TRACES_MAX_BYTES = 50 * 1024 * 1024
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.utcnow().isoformat()


def trace_enabled() -> bool:
    raw = get_config("CANDYCONC_ENABLE_LLM_TRACE")
    if raw is not None:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    mode = str(get_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe") or "")
    normalized_mode = mode.strip().lower().replace("-", "_")
    return normalized_mode not in {"release", "production", "prod"}


def trace_debug_enabled() -> bool:
    raw = os.environ.get("CANDYCONC_LLM_TRACE_DEBUG_MESSAGES")
    if raw is None:
        raw = os.environ.get("CANDYCONC_LLM_TRACE_DEBUG")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _content_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8", errors="replace")
    try:
        return json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    except Exception:
        return repr(content).encode("utf-8", errors="replace")


def _redact_message(message: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(message, dict):
        return {"redacted": True, "type": type(message).__name__}
    redacted: Dict[str, Any] = {
        key: value
        for key, value in message.items()
        if key in {"role", "name", "tool_call_id"}
    }
    if "content" in message:
        content = _content_bytes(message.get("content"))
        redacted["content"] = "[redacted]"
        redacted["content_bytes"] = len(content)
    for key in ("tool_calls", "function_call", "arguments"):
        if key in message:
            redacted[key] = "[redacted]"
    return redacted


def _redact_messages(messages: Any) -> list[dict]:
    if not isinstance(messages, list):
        return []
    return [_redact_message(message) for message in messages]


def _messages_are_redacted(row: dict) -> bool:
    return row.get("messages_redacted") is True


def _tool_names(tools: Any) -> List[str]:
    """Reduce full tool specifications to their names (size and data hygiene)."""
    if not isinstance(tools, list):
        return []
    names: List[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else tool.get("name")
        if name:
            names.append(str(name))
    return names


def _rotate_locked() -> None:
    """Rotate the trace file once it exceeds the size cap (one generation)."""
    try:
        if _TRACES_PATH.stat().st_size < _TRACES_MAX_BYTES:
            return
    except OSError:
        return
    rotated = _TRACES_PATH.with_name(_TRACES_PATH.name + ".1")
    try:
        _TRACES_PATH.replace(rotated)
    except OSError:
        pass


def _append(row: dict) -> None:
    if not trace_enabled():
        return
    line = json.dumps(row, ensure_ascii=True)
    with _LOCK:
        _TRACES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_locked()
        with _TRACES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _iter_rows() -> Iterable[dict]:
    if not _TRACES_PATH.exists():
        return []
    rows: List[dict] = []
    for line in _TRACES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def record_pre(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    user: str,
    model: str,
    *,
    stream: bool = False,
) -> str:
    if not trace_enabled():
        return ""
    trace_id = uuid.uuid4().hex
    debug = trace_debug_enabled()
    _append(
        {
            "id": trace_id,
            "event": "pre",
            "ts": _now(),
            "user": user,
            "model": model,
            "messages": messages if debug else _redact_messages(messages),
            "messages_redacted": not debug,
            "tools": _tool_names(tools),
            "stream": bool(stream),
        }
    )
    return trace_id


def record_post(trace_id: str, *, tokens: int = 0) -> None:
    if not trace_id or not trace_enabled():
        return
    _append(
        {
            "id": trace_id,
            "event": "post",
            "ts": _now(),
            "tokens": int(tokens),
        }
    )


def _merge_rows(rows: Iterable[dict]) -> Dict[str, dict]:
    merged: Dict[str, dict] = {}
    for row in rows:
        trace_id = str(row.get("id", ""))
        if not trace_id:
            continue
        event = row.get("event")
        current = merged.get(trace_id, {})
        if event == "pre":
            current.update(
                {
                    "id": trace_id,
                    "created_at": row.get("ts"),
                    "user": row.get("user"),
                    "model": row.get("model"),
                    "messages": row.get("messages"),
                    "messages_redacted": row.get("messages_redacted", False),
                    "tools": row.get("tools"),
                    "stream": row.get("stream", False),
                }
            )
        elif event == "post":
            current.update(
                {
                    "updated_at": row.get("ts"),
                    "tokens": row.get("tokens", 0),
                }
            )
        merged[trace_id] = current
    return merged


def query(
    *,
    user: str | None = None,
    start: str | None = None,
    end: str | None = None,
    offset: int = 0,
    limit: int = 50,
    include_raw_messages: bool = False,
) -> list[dict]:
    merged = _merge_rows(_iter_rows())
    items = list(merged.values())
    if user:
        items = [row for row in items if row.get("user") == user]
    if start:
        items = [row for row in items if str(row.get("created_at", "")) >= start]
    if end:
        items = [row for row in items if str(row.get("created_at", "")) <= end]
    items.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    page = items[int(offset) : int(offset) + int(limit)]
    if include_raw_messages and trace_debug_enabled():
        return page
    redacted_page: list[dict] = []
    for row in page:
        copy = dict(row)
        if not _messages_are_redacted(copy):
            copy["messages"] = _redact_messages(copy.get("messages"))
            copy["messages_redacted"] = True
        redacted_page.append(copy)
    return redacted_page


__all__ = [
    "record_pre",
    "record_post",
    "query",
    "trace_enabled",
    "trace_debug_enabled",
]
