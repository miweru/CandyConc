"""WebSocket routes for vector search and analysis jobs.

Server-owned helpers bind the event buses and cross-thread queues."""

from __future__ import annotations

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

# A normal socket close can arrive as WebSocketDisconnect or, while the
# server is sending, as ConnectionClosedOK from the websockets library.
# Handle both to avoid logging an expected disconnect as an ASGI error.
try:  # pragma: no cover - haengt an der installierten websockets-Fassung
    from websockets.exceptions import ConnectionClosed as _ConnectionClosed

    _ABBRUCH: tuple[type[BaseException], ...] = (_ConnectionClosed,)
except Exception:  # pragma: no cover
    _ABBRUCH = ()

from candyconc.entrypoints.errors import CandyAPIRouter
from candyconc.i18n import localize

from .. import auth

router = CandyAPIRouter()


@router.websocket("/ws/faiss/{job_id}")
async def ws_faiss(websocket: WebSocket, job_id: str) -> None:
    from .. import server as _server
    token: str | None = await auth.get_user_token(websocket)
    ticket_user = _server._ws_ticket_username(websocket, token)
    try:
        if ticket_user is not None:
            auth.require_role_for_username("admin", ticket_user)
        else:
            auth.require_role("admin")(token)
    except HTTPException as exc:
        await _server._ws_deny(websocket, exc)
        return
    q = _server.jobs.get(job_id)
    if q is None:
        await websocket.close()
        return
    await websocket.accept()
    try:
        while True:
            item = await q.get()
            await websocket.send_json(localize(item))
            if item.get("progress", 0) >= 100:
                break
    except (WebSocketDisconnect, *_ABBRUCH):
        _server.logger.info("WebSocket disconnected: /ws/faiss/%s", job_id)
    finally:
        _server.jobs.remove(job_id)


@router.websocket("/ws/analysis/{job_id}")
async def ws_analysis(websocket: WebSocket, job_id: str) -> None:
    from .. import server as _server
    token: str | None = await auth.get_user_token(websocket)
    ticket_user = _server._ws_ticket_username(websocket, token)
    try:
        if ticket_user is not None:
            auth.require_role_for_username("user", ticket_user)
        else:
            _server._require_user_access(token)
        _server.rate_limit.check(token)
    except HTTPException as exc:
        await _server._ws_deny(websocket, exc)
        return
    try:
        _ = _server.analysis_jobs.get(job_id)
    except KeyError:
        await websocket.close()
        return
    await websocket.accept()
    try:
        async for item in _server.analysis_jobs.stream(job_id):
            await websocket.send_json(localize(item))
            if item.get("status") in {"done", "error", "cancelled"}:
                break
    except (WebSocketDisconnect, *_ABBRUCH):
        _server.logger.info("WebSocket disconnected: /ws/analysis/%s", job_id)
