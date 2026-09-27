"""Session-scoped in-process event stream for Copilot SSE responses.

Copilot output is transient and confidential to one session. It is never
persisted or broadcast to unscoped listeners.
The synchronous SSE generators own their own event loops, while the
orchestrator emits from worker threads; delivery consequently schedules puts on
the listener's registered loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any


_session_listeners: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
_listener_session: dict[int, str] = {}
_listener_loop: dict[int, asyncio.AbstractEventLoop | None] = {}

# Listener registry mutations and delivery-target snapshots share one lock.
# Delivery itself happens after the snapshot, so a slow event loop cannot block
# concurrent stream connects or disconnects.
_BUS_LOCK = threading.Lock()


def _require_session_id(session_id: str | None) -> str:
    value = str(session_id or "").strip()
    if not value:
        raise ValueError("Copilot event stream requires a session_id")
    return value


def _deliver(
    queue: asyncio.Queue[dict[str, Any]],
    loop: asyncio.AbstractEventLoop | None,
    data: dict[str, Any],
) -> None:
    """Feed a listener queue on its owner loop, including from worker threads."""
    if loop is not None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, data)
            return
        except RuntimeError:
            # The response closed while an orchestrator worker was emitting.
            return
    queue.put_nowait(data)


def publish(data: dict[str, Any], session_id: str) -> None:
    """Deliver one Copilot event to listeners for exactly ``session_id``."""
    session_id = _require_session_id(session_id)
    with _BUS_LOCK:
        targets = tuple(
            (queue, _listener_loop.get(id(queue)))
            for queue in _session_listeners.get(session_id, ())
        )
    for queue, loop in targets:
        _deliver(queue, loop, data)


def subscribe(
    session_id: str,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> asyncio.Queue[dict[str, Any]]:
    """Subscribe an SSE listener to one Copilot session."""
    session_id = _require_session_id(session_id)
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    with _BUS_LOCK:
        _session_listeners.setdefault(session_id, []).append(queue)
        _listener_session[id(queue)] = session_id
        _listener_loop[id(queue)] = loop
    return queue


def unsubscribe(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Stop delivering to ``queue`` and release its loop/session bookkeeping."""
    with _BUS_LOCK:
        _listener_loop.pop(id(queue), None)
        session_id = _listener_session.pop(id(queue), None)
        if session_id is None:
            return
        listeners = _session_listeners.get(session_id)
        if listeners is None:
            return
        try:
            listeners.remove(queue)
        except ValueError:
            return
        if not listeners:
            _session_listeners.pop(session_id, None)
