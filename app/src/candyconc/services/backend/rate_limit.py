import os
import time
from collections import deque
from typing import Deque, Dict, Optional, Annotated

from fastapi import HTTPException, Depends, Request

from . import auth

_WINDOW = 60.0


def _env_int(name: str, fallback: int) -> int:
    """Read a non-negative integer limit from the environment."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return fallback
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


# Sane non-zero defaults so the backend is never unlimited out of the box
# (the prior default of 0 meant unbounded login / LLM / regex traffic).
# ``default`` covers authenticated users; ``anon`` is a stricter throttle for
# unauthenticated / login traffic (brute-force and LLM/regex abuse guard).
# Both are configurable via environment variables. Anonymous traffic is
# bucketed per client IP (``anon:<ip>``) when the caller provides one, so a
# single attacker can no longer exhaust the shared anon budget and DoS all
# anonymous/login traffic; without a client address the global ``anon``
# bucket is the fallback. Operators wanting a hard brute-force lock can lower
# CANDYCONC_RATE_LIMIT_ANON.
_DEFAULT_LIMIT = _env_int("CANDYCONC_RATE_LIMIT_DEFAULT", 600)
_DEFAULT_ANON_LIMIT = _env_int("CANDYCONC_RATE_LIMIT_ANON", 300)

_RATE_LIMITS: Dict[str, int] = {
    "default": _DEFAULT_LIMIT,
    "anon": _DEFAULT_ANON_LIMIT,
}
_USAGE: Dict[str, Deque[float]] = {}
_MAX_USAGE_BUCKETS = _env_int("CANDYCONC_RATE_LIMIT_MAX_BUCKETS", 10000)
_PRUNE_INTERVAL = 30.0
_LAST_PRUNE = 0.0


def set_limit(user: str, limit: int) -> None:
    """Set the allowed requests per window for ``user``."""
    _RATE_LIMITS[user] = limit


def set_window(seconds: float) -> None:
    """Update the window size in seconds."""
    global _WINDOW
    _WINDOW = seconds


def reset() -> None:
    """Reset usage statistics and limits (for tests)."""
    global _WINDOW, _LAST_PRUNE
    _USAGE.clear()
    _RATE_LIMITS.clear()
    _RATE_LIMITS["default"] = _DEFAULT_LIMIT
    _RATE_LIMITS["anon"] = _DEFAULT_ANON_LIMIT
    _WINDOW = 60.0
    _LAST_PRUNE = 0.0


def _limit_for(user: str) -> int:
    """Return the configured limit for ``user`` with a safe fallback chain."""
    if user in _RATE_LIMITS:
        return _RATE_LIMITS[user]
    # Per-IP anon buckets ("anon:<ip>") share the configured "anon" limit.
    if user == "anon" or user.startswith("anon:"):
        return _RATE_LIMITS.get("anon", _DEFAULT_ANON_LIMIT)
    return _RATE_LIMITS.get("default", _DEFAULT_LIMIT)


def _prune_usage(now: float) -> None:
    """Drop expired/old rate-limit buckets so hostile IP churn cannot grow memory forever."""
    for key, dq in list(_USAGE.items()):
        while dq and now - dq[0] > _WINDOW:
            dq.popleft()
        if not dq:
            _USAGE.pop(key, None)

    if _MAX_USAGE_BUCKETS <= 0 or len(_USAGE) <= _MAX_USAGE_BUCKETS:
        return
    ordered = sorted(_USAGE, key=lambda item: _USAGE[item][0] if _USAGE[item] else now)
    for key in ordered[: len(_USAGE) - _MAX_USAGE_BUCKETS]:
        _USAGE.pop(key, None)


def _maybe_prune_usage(now: float) -> None:
    global _LAST_PRUNE
    if now - _LAST_PRUNE < _PRUNE_INTERVAL and len(_USAGE) <= _MAX_USAGE_BUCKETS:
        return
    _prune_usage(now)
    _LAST_PRUNE = now


def check(token: Optional[str], client_host: Optional[str] = None) -> None:
    """Enforce the rate limit for the user identified by ``token``.

    Anonymous (or unresolved-token) callers are bucketed per ``client_host``
    so one abusive IP cannot exhaust the anon budget for everyone; when no
    client address is known the global ``anon`` bucket applies.
    """
    user = auth.username_for_token(token) if token else "anon"
    # Unknown / unresolved tokens fall back to the stricter anon bucket so an
    # attacker cannot dodge throttling by sending a bogus bearer token.
    if not user:
        user = "anon"
    if user == "anon" and client_host:
        user = f"anon:{client_host}"
    limit = _limit_for(user)
    if limit <= 0:
        return
    now = time.time()
    _maybe_prune_usage(now)
    dq = _USAGE.setdefault(user, deque())
    while dq and now - dq[0] > _WINDOW:
        dq.popleft()
    if len(dq) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    dq.append(now)


def _client_host(request: Optional[Request]) -> Optional[str]:
    """Best-effort client address for anon bucketing (None when unknown)."""
    client = getattr(request, "client", None) if request is not None else None
    return getattr(client, "host", None)


def dependency(
    request: Request,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> None:
    """FastAPI dependency enforcing rate limits.

    The backend's HTTP middleware already rate-counts every request and sets
    ``request.state.candyconc_rate_limit_checked``; in that case this
    dependency is a no-op so routes declaring it explicitly are not counted
    twice (double-counting silently halved their effective limit). When called
    outside the middleware (unit use, custom mounts) it enforces normally.
    """
    state = getattr(request, "state", None)
    if state is not None and getattr(state, "candyconc_rate_limit_checked", False):
        return
    check(token, client_host=_client_host(request))
