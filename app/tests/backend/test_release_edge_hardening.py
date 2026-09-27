"""Release-edge hardening regression tests (re-audit 2026-06-10, section 2/4).

Covers three Medium release edges from the re-audit:

1. Security-mode unification: ``production`` / ``prod`` must activate the same
   fail-closed release hardening as ``release`` (gate + trusted host).
2. Rate-limit overruns raised inside the HTTP middleware must surface as a
   429 problem+json response, not a naked exception (= 500 at the ASGI edge),
   and routes with an explicit ``rate_limit.dependency`` must not double-count
   against the budget (middleware + dependency previously halved the limit).
3. Swagger/OpenAPI endpoints (``/docs``, ``/redoc``, ``/openapi.json``) must be
   blocked in release mode while staying reachable in local dev.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from candyconc.config import APP_CONFIG, set as set_config
from candyconc.services.backend import app, auth, rate_limit

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


@pytest.fixture()
def security_state():
    mode = APP_CONFIG.CANDYCONC_SECURITY_MODE
    rbac_enabled = auth.RBAC_ENABLED
    users = dict(auth._USERS)
    tokens = dict(auth._tokens)
    default_admin_token = auth.DEFAULT_ADMIN_TOKEN
    rate_limit.reset()
    try:
        yield
    finally:
        set_config("CANDYCONC_SECURITY_MODE", mode)
        auth.RBAC_ENABLED = rbac_enabled
        auth._USERS.clear()
        auth._USERS.update(users)
        auth._tokens.clear()
        auth._tokens.update(tokens)
        auth.DEFAULT_ADMIN_TOKEN = default_admin_token
        rate_limit.reset()


def _configure_valid_release_users() -> None:
    """RBAC on, explicit admin user, no implicit dev admin token."""
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("opadmin", "pw", "admin")


# --------------------------------------------------------------------------- #
# Fix 1: production/prod aliases activate release hardening
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("alias", ["production", "prod", "Production", "PROD"])
def test_security_mode_normalizes_production_aliases_to_release(security_state, alias):
    set_config("CANDYCONC_SECURITY_MODE", alias)
    assert auth.security_mode() == auth.SECURITY_MODE_RELEASE
    assert auth.is_release_mode() is True
    assert auth.allow_unsafe_token_transport() is False


@pytest.mark.parametrize("alias", ["dev", "local", "local_dev", "unsafe"])
def test_security_mode_normalizes_dev_aliases_to_local_dev_unsafe(security_state, alias):
    set_config("CANDYCONC_SECURITY_MODE", alias)
    assert auth.security_mode() == auth.SECURITY_MODE_LOCAL_DEV_UNSAFE
    assert auth.is_release_mode() is False


def test_unknown_security_mode_is_not_release_and_not_unsafe(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "something_else")
    assert auth.is_release_mode() is False
    assert auth.allow_unsafe_token_transport() is False


def test_production_mode_activates_fail_closed_gate(security_state):
    """mode=production with fail-open config must 503 like mode=release."""
    set_config("CANDYCONC_SECURITY_MODE", "production")
    auth.RBAC_ENABLED = False
    auth._USERS.clear()
    auth._tokens.clear()
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert "Unsafe CandyConc release security configuration" in response.json()["detail"]


def test_production_mode_activates_trusted_host_check(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "production")
    _configure_valid_release_users()
    client = TestClient(app)

    foreign = client.get("/api/v1/health", headers={"host": "evil.example.com"})
    assert foreign.status_code == 400
    assert foreign.json()["detail"] == "Untrusted Host header"

    trusted = client.get("/api/v1/health")
    assert trusted.status_code == 200


# --------------------------------------------------------------------------- #
# Fix 2a: middleware rate-limit overrun -> 429 problem+json, not 500
# --------------------------------------------------------------------------- #
def test_middleware_rate_limit_overrun_returns_429_problem_json(security_state):
    rate_limit.set_limit("anon", 1)
    client = TestClient(app, raise_server_exceptions=True)

    first = client.get("/api/v1/health")
    assert first.status_code == 200

    # Before the fix the HTTPException(429) escaped the middleware and blew up
    # as a server error; now it must serialize as problem+json with status 429.
    second = client.get("/api/v1/health")
    assert second.status_code == 429
    assert second.headers["content-type"].startswith("application/problem+json")
    body = second.json()
    assert body["status"] == 429
    assert body["detail"] == "Rate limit exceeded"
    assert body["instance"] == "/api/v1/health"


# --------------------------------------------------------------------------- #
# Fix 2b: explicit rate_limit.dependency must not double-count
# --------------------------------------------------------------------------- #
def test_route_with_explicit_dependency_counts_request_once(security_state):
    """/api/v1/document declares Depends(rate_limit.dependency); the middleware
    already counted the request, so the dependency must not count it again."""
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/api/v1/document/0")

    total = sum(len(dq) for dq in rate_limit._USAGE.values())
    assert total == 1, f"request was rate-counted {total} times (double-count)"


def test_route_with_explicit_dependency_gets_full_budget(security_state):
    rate_limit.set_limit("anon", 2)
    client = TestClient(app, raise_server_exceptions=False)

    first = client.get("/api/v1/document/0")
    second = client.get("/api/v1/document/0")
    assert first.status_code != 429
    assert second.status_code != 429

    third = client.get("/api/v1/document/0")
    assert third.status_code == 429


def test_direct_dependency_call_still_enforces_limit(security_state):
    """Outside the middleware (no state flag) the dependency keeps enforcing."""

    class _FakeState:
        pass

    class _FakeRequest:
        state = _FakeState()
        client = None

    rate_limit.set_limit("anon", 1)
    rate_limit.dependency(_FakeRequest(), token=None)  # type: ignore[arg-type]
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        rate_limit.dependency(_FakeRequest(), token=None)  # type: ignore[arg-type]
    assert exc.value.status_code == 429


# --------------------------------------------------------------------------- #
# Fix 3: Swagger/OpenAPI gating in release mode
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_endpoints_blocked_in_release_mode(security_state, path):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    _configure_valid_release_users()
    client = TestClient(app)

    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_endpoints_blocked_in_production_alias_mode(security_state, path):
    set_config("CANDYCONC_SECURITY_MODE", "production")
    _configure_valid_release_users()
    client = TestClient(app)

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_endpoints_reachable_in_local_dev(security_state, path):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    client = TestClient(app)

    assert client.get(path).status_code == 200
