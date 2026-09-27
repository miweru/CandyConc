"""Tool dispatcher mapping function names to wrapper implementations.

K1 (In-Process-Dispatch): Der Standardweg ruft die Gate-Kette von
``candyconc.services.mcp_server.execute_tool_call`` DIREKT in-process auf
(Schema-Validierung inkl. additionalProperties-Enforcement, PolicyEngine/ACL,
Release-Default-Deny, Feature-Gates, Registry-Callable). Damit faellt der
HTTP-Selbstaufruf gegen CANDYCONC_BACKEND_URL weg: Tool-Roundtrips kosten
Millisekunden statt Sekunden und es gibt keine Port-Kopplung mehr. Der
HTTP-Weg bleibt NUR, wenn ``CANDYCONC_MCP_URL`` explizit auf einen Remote
zeigt. Die Fehlersemantik beider Wege ist identisch gepinnt
(tests/ai/test_inprocess_dispatch_parity.py).
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict
import logging
import json
from candyconc.tooling.registry import get_schema_map
from candyconc.services.mcp_client import call_tool
from jsonschema import validate as json_validate, ValidationError
try:
    from prometheus_client import Counter
except Exception:  # pragma: no cover - prometheus missing
    class Counter:  # type: ignore
        def __init__(self, *args: Any, **kw: Any) -> None:
            self.value = 0

        def labels(self, *args: Any, **kw: Any) -> "Counter":
            return self

        def inc(self, amount: int = 1) -> None:
            self.value += amount



_TOOL_CALLS = Counter("tool_calls_total", "LLM tool calls", ["tool", "status"])


def _remote_mcp_url() -> str | None:
    """Explizit konfigurierter Remote-MCP, sonst ``None`` (in-process)."""
    from candyconc.config import APP_CONFIG

    raw = APP_CONFIG.CANDYCONC_MCP_URL
    if raw and str(raw).strip():
        return str(raw).rstrip("/")
    return None


def _problem_json_text(status_code: int, detail: Any) -> str:
    """RFC-7807-Body, byte-identisch zur bisherigen HTTP-Fehlerantwort.

    Die HTTP-Route rendert HTTPExceptions ueber ``entrypoints.errors``
    als problem+json mit ``instance=/mcp/call``. Der In-Process-Weg pinnt
    exakt dieses Format, damit Fehlertexte fuer Modell und Logs identisch
    bleiben (Paritaetstest).
    """
    body: Dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status_code).phrase,
        "status": status_code,
    }
    if detail is not None:
        body["detail"] = detail
    body["instance"] = "/mcp/call"
    return json.dumps(
        body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


async def _call_tool_in_process(
    name: str, args: Dict[str, Any], *, token: str | None = None
) -> Dict[str, Any]:
    """Selbe Gates wie POST /mcp/call, ohne HTTP-Selbstaufruf."""
    from fastapi import HTTPException
    from candyconc.services import mcp_server

    try:
        return await mcp_server.execute_tool_call(
            {"name": name, "arguments": args}, token
        )
    except HTTPException as exc:
        detail = _problem_json_text(exc.status_code, exc.detail)
        raise RuntimeError(f"MCP Fehler: {detail}") from exc


async def dispatch(call: Dict[str, Any], token: str | None = None) -> Dict[str, Any]:
    """Execute ``call`` after validating its arguments."""

    name = call["function"]["name"]
    args = json.loads(call["function"].get("arguments", "{}"))
    schema_map = get_schema_map()

    schema = schema_map.get(name)
    if schema is None:
        # The LLM hallucinated a tool name. A bare KeyError here aborts the
        # orchestrator turn; instead return the established error envelope so
        # the result lands in the session as a model-visible tool message and
        # the model can self-correct.
        _TOOL_CALLS.labels(name, "error").inc()
        available = ", ".join(sorted(schema_map))
        return {
            "status": "error",
            "message": f"Unbekanntes Tool: {name}. Verfügbar: {available}",
        }

    try:
        json_validate(args, schema)
    except ValidationError as exc:  # pragma: no cover - invalid args
        _TOOL_CALLS.labels(name, "error").inc()
        raise ValueError(f"Invalid arguments: {exc.message}") from exc

    remote_url = _remote_mcp_url()
    try:
        if remote_url is None:
            result = await _call_tool_in_process(name, args, token=token)
        else:
            result = await call_tool(name, args, token=token)
    except Exception as exc:
        target = remote_url if remote_url is not None else "in-process"
        logging.getLogger(__name__).error(
            "%s failed (dispatch target %s): %s", name, target, exc
        )
        _TOOL_CALLS.labels(name, "error").inc()
        raise RuntimeError(str(exc)) from exc

    _TOOL_CALLS.labels(name, "success").inc()
    return result
