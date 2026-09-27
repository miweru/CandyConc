from __future__ import annotations

from typing import Dict

from ..schemas import (
    AuthSessionResponse,
    LoginRequest,
)

from typing import Annotated
from fastapi import HTTPException, Depends, Body
from candyconc.entrypoints.errors import CandyAPIRouter

from .. import auth

router = CandyAPIRouter()


@router.post(
    "/login",
    responses={200: {"content": {"application/json": {"example": {"token": "token123"}}}}},
)
async def login(
    payload: LoginRequest = Body(
        ...,
        examples={"basic": {"summary": "Login", "value": {"username": "admin", "password": "secret"}}},
    ),
):
    """Sign in with user name and password and receive a token.

    \f
    Login und Token Ausgabe."""
    token = auth.authenticate(payload.username, payload.password)
    if not token:
        auth.audit_event("auth.login_failed", actor=payload.username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    auth.audit_event("auth.login", actor=payload.username)
    return {"token": token}


@router.post(
    "/logout",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def logout(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
):
    """Revoke the caller's bearer token."""
    # Resolve the actor BEFORE revoking — afterwards the token is unknown.
    actor = auth.username_for_token(token)
    if auth.revoke_token(token):
        auth.audit_event("auth.logout", actor=actor)
    return {"status": "ok"}


@router.get("/auth/session", response_model=AuthSessionResponse)
async def auth_session(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> AuthSessionResponse:
    """Return the caller's effective session context for UI capability gates."""
    username = auth.username_for_token(token)
    role = auth.role_for_token(token)
    local_dev_all_roles = (
        bool(token)
        and username == auth.LOCAL_DEV_USERNAME
        and role == auth.LOCAL_DEV_ROLE
        and not auth.RBAC_ENABLED
        and auth.is_local_dev_unsafe_mode()
    )
    effective_role = "admin" if local_dev_all_roles else role
    authenticated = bool(token and username)
    return AuthSessionResponse(
        authenticated=authenticated,
        token_present=bool(token),
        username=username,
        role=role,
        effective_role=effective_role,
        rbac_enabled=auth.RBAC_ENABLED,
        security_mode=auth.security_mode(),
        release_mode=auth.is_release_mode(),
        unsafe_token_transport=auth.allow_unsafe_token_transport(),
        dev_token_available=not auth.RBAC_ENABLED and auth.is_local_dev_unsafe_mode(),
        can_access_all_roles=local_dev_all_roles,
    )


@router.post(
    "/ws-ticket",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"ticket": "abc123", "expires_in": 30}
                }
            }
        }
    },
)
async def mint_ws_ticket(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, object]:
    """Mint a short-TTL one-time WebSocket ticket (A7).

    Browsers cannot set an Authorization header on ``new WebSocket()`` and
    release mode refuses query/body tokens. Clients call this endpoint over
    authenticated REST and pass the returned ticket as ``?ticket=`` on the WS
    handshake; the ticket is single-use and expires after ``expires_in``
    seconds.
    """
    username = auth.username_for_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    ticket, ttl = auth.mint_ws_ticket(username)
    auth.audit_event("auth.ws_ticket_minted", actor=username)
    return {"ticket": ticket, "expires_in": int(ttl)}
