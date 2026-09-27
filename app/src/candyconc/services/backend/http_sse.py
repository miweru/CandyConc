"""HTTP and SSE serialization using json and optional orjson.

The helpers have no configuration or mutable module state and remain
independent of server and route imports."""

import json
from typing import Any

from candyconc.i18n import localize

try:
    import orjson as _orjson
except Exception:  # pragma: no cover - optional acceleration
    _orjson = None


def _copilot_sse_frame(item: Any) -> str:
    """Serialize one Copilot queue item with an explicit SSE event when possible.

    Bilingual server texts in the item are resolved to the request language.
    """
    item = localize(item)
    if isinstance(item, dict):
        event = item.get("event")
        if not event and isinstance(item.get("delta"), dict):
            event = "copilot.delta"
        if isinstance(event, str) and event:
            return f"event: {event}\ndata: {json.dumps(item)}\n\n"
    return f"data: {json.dumps(item)}\n\n"


def _json_dumps_fast_bytes(payload: Any) -> bytes:
    if _orjson is not None:
        return _orjson.dumps(payload)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _sse_event_bytes(event: str, payload: bytes) -> bytes:
    return b"event: " + event.encode("utf-8") + b"\ndata: " + payload + b"\n\n"
