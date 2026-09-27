from __future__ import annotations

from typing import Any, Dict
import httpx

from candyconc.config import APP_CONFIG


def resolve_mcp_url() -> str:
    raw = APP_CONFIG.CANDYCONC_MCP_URL
    if raw:
        return raw.rstrip("/")
    backend = APP_CONFIG.CANDYCONC_BACKEND_URL.rstrip("/")
    if backend.endswith("/api/v1"):
        backend = backend[:-7]
    return backend + "/mcp"


async def call_tool(
    name: str, arguments: Dict[str, Any], *, token: str | None = None
) -> Dict[str, Any]:
    base = resolve_mcp_url().rstrip("/")
    url = base + "/call"
    timeout = APP_CONFIG.HTTP_TIMEOUT
    payload = {"name": name, "arguments": arguments}
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers or None)
    except httpx.HTTPError as exc:
        # K1: Transportfehler nennen die Ziel-URL, damit ein falsch gesetzter
        # Remote (CANDYCONC_MCP_URL / CANDYCONC_BACKEND_URL) nicht als opakes
        # "All connection attempts failed" endet.
        raise RuntimeError(
            f"MCP nicht erreichbar unter {url}: {exc}"
        ) from exc
    if resp.status_code >= 400:
        detail = resp.text.strip() or f"status {resp.status_code}"
        raise RuntimeError(f"MCP Fehler: {detail}")
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError("MCP Antwort ist kein Objekt")
    return data
