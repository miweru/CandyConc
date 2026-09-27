"""A8 fix: network posture — loopback-default bind + release TrustedHost guard.

1. ``candy`` CLI now binds 127.0.0.1 by default; exposing the backend on the
   network requires an explicit ``--host 0.0.0.0`` opt-in.
2. In release security mode the backend rejects requests whose ``Host`` header
   is not on the ``CANDYCONC_TRUSTED_HOSTS`` allowlist (DNS-rebinding guard).
   Dev modes are untouched.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from candyconc.config import APP_CONFIG, set as set_config
from candyconc.services.backend import app, auth, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


# --------------------------------------------------------------------------- #
# CLI default bind                                                             #
# --------------------------------------------------------------------------- #


def _run_cli(monkeypatch, tmp_path, argv):
    from candyconc.entrypoints import cli

    captured = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr(cli, "has_index", lambda _p: True)
    # Keep the temp-index guard away from pytest's tmp tree (which lives under
    # the real system temp dir on macOS).
    monkeypatch.setattr(cli.tempfile, "gettempdir", lambda: str(tmp_path / "faketmp"))
    index_dir = tmp_path / "idx"
    index_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(index_dir))
    monkeypatch.setattr(cli.sys, "argv", argv)
    cli.main()
    return captured


def test_cli_defaults_to_loopback_bind(monkeypatch, tmp_path):
    captured = _run_cli(monkeypatch, tmp_path, ["candy"])
    assert captured["host"] == "127.0.0.1"


def test_cli_blocks_network_bind_in_unsafe_dev_mode(security_state, monkeypatch, tmp_path):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    with pytest.raises(SystemExit, match="Unsafe network start blocked"):
        _run_cli(monkeypatch, tmp_path, ["candy", "--host", "0.0.0.0"])


def test_cli_network_bind_allows_release_mode(security_state, monkeypatch, tmp_path):
    set_config("CANDYCONC_SECURITY_MODE", "release")
    captured = _run_cli(monkeypatch, tmp_path, ["candy", "--host", "0.0.0.0"])
    assert captured["host"] == "0.0.0.0"


def test_cli_network_bind_allows_explicit_unsafe_override(security_state, monkeypatch, tmp_path, capsys):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    monkeypatch.setenv("CANDYCONC_ALLOW_UNSAFE_NETWORK_DEV", "1")

    captured = _run_cli(monkeypatch, tmp_path, ["candy", "--host", "0.0.0.0"])
    streams = capsys.readouterr()

    assert captured["host"] == "0.0.0.0"
    assert "UNSAFE local development mode" in streams.err


# --------------------------------------------------------------------------- #
# TrustedHost guard (release mode only)                                        #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def security_state():
    mode = APP_CONFIG.CANDYCONC_SECURITY_MODE
    rbac_enabled = auth.RBAC_ENABLED
    users = dict(auth._USERS)
    tokens = dict(auth._tokens)
    default_admin_token = auth.DEFAULT_ADMIN_TOKEN
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


def _enter_release_mode():
    set_config("CANDYCONC_SECURITY_MODE", "release")
    auth.RBAC_ENABLED = True
    auth.DEFAULT_ADMIN_TOKEN = None
    auth._USERS.clear()
    auth._tokens.clear()
    auth.create_user("admin", "pw", "admin")


def test_release_mode_blocks_untrusted_host_header(security_state):
    _enter_release_mode()
    client = TestClient(app)

    blocked = client.get("/api/v1/health", headers={"Host": "evil.example.com"})
    assert blocked.status_code == 400
    assert "Untrusted Host" in str(blocked.json().get("detail"))

    # The default allowlist covers the TestClient host, so normal traffic flows.
    allowed = client.get("/api/v1/health")
    assert allowed.status_code == 200


def test_release_mode_honors_configured_allowlist(security_state, monkeypatch):
    _enter_release_mode()
    monkeypatch.setenv("CANDYCONC_TRUSTED_HOSTS", "testserver,corpus.example.org")
    client = TestClient(app)

    allowed = client.get("/api/v1/health", headers={"Host": "corpus.example.org:8765"})
    assert allowed.status_code == 200

    blocked = client.get("/api/v1/health", headers={"Host": "other.example.org"})
    assert blocked.status_code == 400


def test_dev_mode_does_not_enforce_trusted_hosts(security_state):
    set_config("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
    client = TestClient(app)

    resp = client.get("/api/v1/health", headers={"Host": "evil.example.com"})
    assert resp.status_code == 200


def test_host_header_normalization():
    assert server._host_is_trusted("localhost")
    assert server._host_is_trusted("LOCALHOST:8765")
    assert server._host_is_trusted("127.0.0.1:8000")
    assert server._host_is_trusted("[::1]:8000")
    assert server._host_is_trusted("::1")
    assert not server._host_is_trusted("evil.example.com")
    assert not server._host_is_trusted("evil.example.com:80")
    assert not server._host_is_trusted("")
