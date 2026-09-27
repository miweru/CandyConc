from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from candyconc.config import APP_CONFIG, set as set_config
from candyconc.services.backend import app, auth, server


@pytest.fixture()
def security_state():
    mode = APP_CONFIG.CANDYCONC_SECURITY_MODE
    rbac_enabled = auth.RBAC_ENABLED
    users = dict(auth._USERS)
    tokens = dict(auth._tokens)
    default_admin_token = auth.DEFAULT_ADMIN_TOKEN
    dev_token = server._DEV_TOKEN
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
        server._DEV_TOKEN = dev_token


def test_release_mode_never_turns_require_role_into_noop(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = False

    with pytest.raises(HTTPException) as exc_info:
        auth.require_role("admin")(None)

    assert exc_info.value.status_code == 503


def test_release_mode_keeps_public_routes_available_without_auth(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200

    login = client.post(
        "/api/v1/login",
        json={"username": "admin", "password": "pw"},
    )
    assert login.status_code == 200
    assert isinstance(login.json().get("token"), str)


def test_release_mode_accepts_header_token_but_not_query_token(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["admin"] = auth.User("admin", "unused", "admin")
    auth._tokens["admintok"] = "admin"
    client = TestClient(app)

    query_token = client.get("/api/v1/metrics", params={"token": "admintok"})
    assert query_token.status_code == 401

    header_token = client.get(
        "/api/v1/metrics",
        headers={"Authorization": "Bearer admintok"},
    )
    assert header_token.status_code == 200


def test_local_dev_unsafe_keeps_legacy_query_token_transport(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = True
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["admin"] = auth.User("admin", "unused", "admin")
    auth._tokens["admintok"] = "admin"
    client = TestClient(app)

    response = client.get("/api/v1/metrics", params={"token": "admintok"})

    assert response.status_code == 200


def test_auth_session_reports_authenticated_user_role(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["analyst"] = auth.User("analyst", "unused", "user")
    auth._tokens["usertok"] = "analyst"
    client = TestClient(app)

    response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": "Bearer usertok"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "auth-session-v1"
    assert body["authenticated"] is True
    assert body["token_present"] is True
    assert body["username"] == "analyst"
    assert body["role"] == "user"
    assert body["effective_role"] == "user"
    assert body["rbac_enabled"] is True
    assert body["can_access_all_roles"] is False


def test_auth_session_is_public_but_empty_without_token_in_release(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")
    client = TestClient(app)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["token_present"] is False
    assert body["username"] is None
    assert body["role"] is None
    assert body["effective_role"] is None
    assert body["release_mode"] is True
    assert body["dev_token_available"] is False


def test_auth_session_reports_local_dev_without_token_but_no_admin_role(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = False
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    client = TestClient(app)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["token_present"] is False
    assert body["username"] == "guest"
    assert body["role"] is None
    assert body["effective_role"] is None
    assert body["rbac_enabled"] is False
    assert body["can_access_all_roles"] is False
    assert body["dev_token_available"] is True


def test_local_dev_admin_helper_requires_real_admin_token(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = False
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()

    with pytest.raises(HTTPException) as missing:
        server._require_admin_access(None)
    assert missing.value.status_code == 401

    auth.create_user("bob", "bob", role="user")
    user_token = auth.authenticate("bob", "bob")
    with pytest.raises(HTTPException) as forbidden:
        server._require_admin_access(user_token)
    assert forbidden.value.status_code == 403

    auth.create_user("alice", "alice", role="admin")
    admin_token = auth.authenticate("alice", "alice")
    server._require_admin_access(admin_token)


def test_auth_session_fails_safe_for_unknown_mode_with_rbac_disabled(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "something_else")
    auth.RBAC_ENABLED = False
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    client = TestClient(app)

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["username"] is None
    assert body["effective_role"] is None
    assert body["can_access_all_roles"] is False
    assert body["dev_token_available"] is False


def test_unknown_mode_with_rbac_disabled_does_not_bypass_protected_routes(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "something_else")
    auth.RBAC_ENABLED = False

    with pytest.raises(HTTPException) as exc_info:
        auth.require_role("user")(None)

    assert exc_info.value.status_code == 503
    assert "local_dev_unsafe" in exc_info.value.detail


def test_dev_token_is_only_available_in_explicit_local_dev_mode(security_state):
    from candyconc.services.backend import server

    server._DEV_TOKEN = None
    client = TestClient(app)

    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")
    assert client.get("/api/v1/auth/dev-token").status_code == 404

    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = True
    assert client.get("/api/v1/auth/dev-token").status_code == 404

    set_config("CANDYCONC_SECURITY_MODE", "something_else")
    auth.RBAC_ENABLED = False
    assert client.get("/api/v1/auth/dev-token").status_code == 404

    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = False
    response = client.get("/api/v1/auth/dev-token")
    assert response.status_code == 200
    assert isinstance(response.json().get("token"), str)


def test_local_dev_dev_token_matches_admin_session_and_routes(security_state):
    server._DEV_TOKEN = None
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = False
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    client = TestClient(app)

    token_response = client.get("/api/v1/auth/dev-token")
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    session = client.get("/api/v1/auth/session", headers=headers)
    assert session.status_code == 200
    body = session.json()
    assert body["authenticated"] is True
    assert body["token_present"] is True
    assert body["username"] == auth.LOCAL_DEV_USERNAME
    assert body["role"] == auth.LOCAL_DEV_ROLE
    assert body["effective_role"] == auth.LOCAL_DEV_ROLE
    assert body["can_access_all_roles"] is True

    assert client.get("/api/v1/system/info", headers=headers).status_code == 200
    assert client.post("/api/v1/system/clear-cache", headers=headers).status_code == 200
    assert client.post(
        "/api/v1/embeddings/download",
        headers=headers,
        json={"name": "unknown"},
    ).status_code == 400
    assert client.post(
        "/api/v1/embeddings/remove",
        headers=headers,
        json={"name": ""},
    ).status_code == 400


def test_release_mode_ignores_query_token_even_when_header_is_invalid(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["admin"] = auth.User("admin", "unused", "admin")
    auth._tokens["admintok"] = "admin"
    client = TestClient(app)

    response = client.get(
        "/api/v1/metrics",
        params={"token": "admintok"},
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401


def test_release_route_policy_enforces_admin_routes(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["analyst"] = auth.User("analyst", "unused", "user")
    auth._USERS["admin"] = auth.User("admin", "unused", "admin")
    auth._tokens["usertok"] = "analyst"
    auth._tokens["admintok"] = "admin"
    client = TestClient(app)

    missing = client.get("/api/v1/metrics")
    assert missing.status_code == 401

    user = client.get("/api/v1/metrics", headers={"Authorization": "Bearer usertok"})
    assert user.status_code == 403

    admin = client.get("/api/v1/metrics", headers={"Authorization": "Bearer admintok"})
    assert admin.status_code == 200


def test_release_route_policy_enforces_user_routes_without_breaking_dev(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth._USERS["analyst"] = auth.User("analyst", "unused", "user")
    auth._tokens["usertok"] = "analyst"
    client = TestClient(app)

    missing = client.get("/api/v1/embeddings/list")
    assert missing.status_code == 401

    query_token = client.get("/api/v1/embeddings/list", params={"token": "usertok"})
    assert query_token.status_code == 401

    header_token = client.get(
        "/api/v1/embeddings/list",
        headers={"Authorization": "Bearer usertok"},
    )
    assert header_token.status_code == 200

    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    auth.RBAC_ENABLED = False
    local_dev = client.get("/api/v1/embeddings/list")
    assert local_dev.status_code == 200


def test_release_route_policy_fails_closed_for_unclassified_backend_routes(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")
    client = TestClient(app)

    response = client.get("/api/v1/not-classified-yet")

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "route is not classified in release route matrix"


def test_release_route_policy_fails_closed_for_future_api_versions(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")
    client = TestClient(app)

    response = client.get("/api/v2/not-classified-yet")

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "route is not classified in release route matrix"


def test_release_mode_revalidates_fail_closed_config_per_request(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = False
    auth._USERS.clear()
    auth._tokens.clear()
    client = TestClient(app)

    response = client.post("/api/v1/login", json={"username": "alice", "password": "alice"})

    assert response.status_code == 503
    assert "Unsafe CandyConc release security configuration" in response.json()["detail"]


def test_release_security_issues_flag_fail_open_config(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = False

    issues = auth.release_security_issues()

    assert any("RBAC" in issue for issue in issues)
