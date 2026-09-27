from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from candyconc.config import APP_CONFIG, set as set_config
from candyconc.services.backend import app, auth
from candyconc.services.backend.operation_runs import operation_run_registry
from candyconc.services.backend.routes import semantic as semantic_routes


@pytest.fixture()
def admin_client():
    mode = APP_CONFIG.CANDYCONC_SECURITY_MODE
    rbac_enabled = auth.RBAC_ENABLED
    users = dict(auth._USERS)
    tokens = dict(auth._tokens)
    default_admin_token = auth.DEFAULT_ADMIN_TOKEN
    try:
        set_config("CANDYCONC_SECURITY_MODE", "release")
        auth.RBAC_ENABLED = True
        auth.DEFAULT_ADMIN_TOKEN = None
        auth._USERS.clear()
        auth._tokens.clear()
        auth._USERS["admin"] = auth.User("admin", "unused", "admin")
        auth._tokens["admintok"] = "admin"
        operation_run_registry.clear()
        yield TestClient(app)
    finally:
        operation_run_registry.clear()
        set_config("CANDYCONC_SECURITY_MODE", mode)
        auth.RBAC_ENABLED = rbac_enabled
        auth._USERS.clear()
        auth._USERS.update(users)
        auth._tokens.clear()
        auth._tokens.update(tokens)
        auth.DEFAULT_ADMIN_TOKEN = default_admin_token


def test_operation_run_status_route_reports_registry_snapshot(admin_client):
    run = operation_run_registry.create(
        operation_id="settings.embedding_management.download",
        source_id="fasttext-de",
        label="Embedding-Download: fasttext-de",
    )
    operation_run_registry.mark_running(
        run.run_id,
        phase="download",
        progress=40,
        message="Embedding-Paket wird heruntergeladen.",
    )

    response = admin_client.get(
        f"/api/v1/operation-runs/{run.run_id}",
        headers={"Authorization": "Bearer admintok"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run.run_id
    assert body["job_id"] == run.run_id
    assert body["operation_id"] == "settings.embedding_management.download"
    assert body["source_id"] == "fasttext-de"
    assert body["kind"] == "operation"
    assert body["phase"] == "download"
    assert body["status"] == "running"
    assert body["progress"] == 40
    assert body["readiness"] == "pending"
    assert body["warnings"] == []
    assert isinstance(body["evidence"], dict)
    assert body["created_at"]
    assert body["updated_at"]


def test_embedding_download_returns_observable_run_and_verifies_terminal_state(
    admin_client,
    monkeypatch,
    tmp_path: Path,
):
    created: list[object] = []

    def capture_task(coro):
        created.append(coro)
        return object()

    async def fake_download_embedding(name: str, _url: str, _sha: str):
        target = tmp_path / f"{name}.txt"
        target.write_text("hase 0.1 0.2\n", encoding="utf-8")
        return target

    monkeypatch.setattr(
        semantic_routes.embeddings,
        "list_packages",
        lambda: {
            "fasttext-de": {
                "url": "https://example.invalid/fasttext-de.txt",
                "sha256": "expected-sha",
            }
        },
    )
    monkeypatch.setattr(semantic_routes.asyncio, "create_task", capture_task)
    monkeypatch.setattr(semantic_routes, "download_embedding", fake_download_embedding)

    response = admin_client.post(
        "/api/v1/embeddings/download",
        json={
            "name": "fasttext-de",
            "url": "https://example.invalid/fasttext-de.txt",
            "sha256": "ignored-in-test",
        },
        headers={"Authorization": "Bearer admintok"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["run_id"]
    assert body["job_id"] == body["run_id"]
    assert body["status_url"] == f"/api/v1/operation-runs/{body['run_id']}"
    assert body["operation_id"] == "settings.embedding_management.download"
    assert created, "download must schedule exactly one backend-owned run"

    queued = admin_client.get(
        body["status_url"],
        headers={"Authorization": "Bearer admintok"},
    )
    assert queued.json()["status"] == "queued"

    asyncio.run(created.pop())

    finished = admin_client.get(
        body["status_url"],
        headers={"Authorization": "Bearer admintok"},
    )
    assert finished.status_code == 200
    snapshot = finished.json()
    assert snapshot["status"] == "succeeded"
    assert snapshot["progress"] == 100
    assert snapshot["readiness"] == "verified"
    assert snapshot["warnings"] == []
    assert snapshot["evidence"]["installed"] is True
    assert snapshot["evidence"]["package"] == "fasttext-de"


def test_embedding_download_rejects_non_catalogued_package(admin_client, monkeypatch):
    monkeypatch.setattr(semantic_routes.embeddings, "list_packages", lambda: {})

    response = admin_client.post(
        "/api/v1/embeddings/download",
        json={"name": "unknown", "url": "https://example.invalid/unknown.txt"},
        headers={"Authorization": "Bearer admintok"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown embedding package"


def test_embedding_download_reuses_active_run_for_same_package(admin_client, monkeypatch):
    scheduled: list[object] = []

    def capture_task(coro):
        scheduled.append(coro)
        return object()

    async def fake_download_embedding(_name: str, _url: str, _sha: str):
        await asyncio.sleep(0)
        return Path(__file__)

    monkeypatch.setattr(
        semantic_routes.embeddings,
        "list_packages",
        lambda: {
            "fasttext-de": {
                "url": "https://example.invalid/fasttext-de.txt",
                "sha256": "expected-sha",
            }
        },
    )
    monkeypatch.setattr(semantic_routes.asyncio, "create_task", capture_task)
    monkeypatch.setattr(semantic_routes, "download_embedding", fake_download_embedding)

    first = admin_client.post(
        "/api/v1/embeddings/download",
        json={"name": "fasttext-de", "url": "https://example.invalid/fasttext-de.txt"},
        headers={"Authorization": "Bearer admintok"},
    )
    second = admin_client.post(
        "/api/v1/embeddings/download",
        json={"name": "fasttext-de", "url": "https://example.invalid/fasttext-de.txt"},
        headers={"Authorization": "Bearer admintok"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
    assert len(scheduled) == 1
    scheduled.pop().close()


def test_embedding_download_marks_run_cancelled_when_backend_task_is_cancelled(
    admin_client,
    monkeypatch,
):
    created: list[object] = []

    def capture_task(coro):
        created.append(coro)
        return object()

    async def cancelled_download(_name: str, _url: str, _sha: str):
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        semantic_routes.embeddings,
        "list_packages",
        lambda: {
            "fasttext-de": {
                "url": "https://example.invalid/fasttext-de.txt",
                "sha256": "expected-sha",
            }
        },
    )
    monkeypatch.setattr(semantic_routes.asyncio, "create_task", capture_task)
    monkeypatch.setattr(semantic_routes, "download_embedding", cancelled_download)

    response = admin_client.post(
        "/api/v1/embeddings/download",
        json={"name": "fasttext-de", "url": "https://example.invalid/fasttext-de.txt"},
        headers={"Authorization": "Bearer admintok"},
    )

    assert response.status_code == 200
    body = response.json()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(created.pop())

    cancelled = admin_client.get(
        body["status_url"],
        headers={"Authorization": "Bearer admintok"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["readiness"] == "cancelled"
