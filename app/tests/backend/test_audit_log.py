"""B10c: audit-log-lite — structured JSONL for auth events.

Covered events: ``auth.login`` / ``auth.login_failed`` / ``auth.logout`` /
``auth.ws_ticket_minted``.

The log is best-effort (never breaks the request path), path-configurable via
``CANDYCONC_AUDIT_LOG_PATH`` and size-bounded by a single rotation once it
exceeds ``CANDYCONC_AUDIT_LOG_MAX_BYTES``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import app, auth

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


@pytest.fixture()
def audit_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("CANDYCONC_AUDIT_LOG_PATH", str(path))
    return path


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _events(path: Path) -> list[tuple[str, str | None]]:
    return [(r["event"], r.get("actor")) for r in _records(path)]


def test_login_success_is_audited(audit_path, client):
    resp = client.post("/api/v1/login", json={"username": "bob", "password": "bob"})
    assert resp.status_code == 200
    assert ("auth.login", "bob") in _events(audit_path)


def test_failed_login_is_audited(audit_path, client):
    resp = client.post(
        "/api/v1/login", json={"username": "bob", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert ("auth.login_failed", "bob") in _events(audit_path)


def test_logout_is_audited_with_resolved_actor(audit_path, client):
    token = client.post(
        "/api/v1/login", json={"username": "bob", "password": "bob"}
    ).json()["token"]
    resp = client.post("/api/v1/logout", params={"token": token})
    assert resp.status_code == 200
    # Actor must be resolved BEFORE revocation, so it is "bob", not None.
    assert ("auth.logout", "bob") in _events(audit_path)


def test_ws_ticket_mint_is_audited(audit_path, client):
    token = client.post(
        "/api/v1/login", json={"username": "bob", "password": "bob"}
    ).json()["token"]
    resp = client.post("/api/v1/ws-ticket", params={"token": token})
    assert resp.status_code == 200
    assert ("auth.ws_ticket_minted", "bob") in _events(audit_path)


def test_records_are_structured_with_timestamp(audit_path, client):
    client.post("/api/v1/login", json={"username": "bob", "password": "bob"})
    records = _records(audit_path)
    assert records
    for rec in records:
        assert set(rec) >= {"ts", "event", "actor"}
        assert rec["ts"]  # ISO timestamp present


def test_rotation_keeps_log_size_bounded(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("CANDYCONC_AUDIT_LOG_PATH", str(path))
    monkeypatch.setenv("CANDYCONC_AUDIT_LOG_MAX_BYTES", "300")
    for i in range(50):
        auth.audit_event("test.rotation", actor="tester", seq=i)
    rotated = path.with_name(path.name + ".1")
    assert rotated.exists(), "rotation file missing after exceeding max bytes"
    # The active file was restarted at least once: it holds only a tail of
    # the events, and the pair of files is the entire retention.
    assert path.stat().st_size < 50 * 40
    # No data corruption: every retained line is valid JSON.
    for p in (path, rotated):
        for line in p.read_text(encoding="utf-8").splitlines():
            json.loads(line)


def test_audit_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDYCONC_AUDIT_LOG_PATH", "off")
    assert auth.audit_log_path() is None
    auth.audit_event("test.disabled", actor="tester")  # must be a no-op


def test_audit_event_never_raises(monkeypatch):
    # Point the log at an unwritable location — auditing must swallow it.
    monkeypatch.setenv("CANDYCONC_AUDIT_LOG_PATH", "/dev/null/impossible/audit.jsonl")
    auth.audit_event("test.unwritable", actor="tester")
