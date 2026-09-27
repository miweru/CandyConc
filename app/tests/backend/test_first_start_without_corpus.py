"""First start of a fresh installation: no corpus, no model endpoint.

Before: ``candy`` refused to start without an index ("Kein gültiger
Indexpfad gefunden: runtime"), the server lifespan failed without
COPILOT_ENDPOINT, and the web interface that offers the import could not be
reached (paketierung B9, inventar 4.3).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import candyconc.domain.corpus as corpus
from candyconc.config import set as set_config
from candyconc.services.backend import server


def _index_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "meta.bin").write_bytes((0).to_bytes(8, "little"))
    (path / "index_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "import_mode": "test",
                "paired": False,
                "pair_axes": [],
                "annotation_source": "test",
                "capabilities": {},
                "dtypes": {},
                "build_fingerprint": "fixture",
                "created_at": "2026-09-27T00:00:00Z",
                "complete": True,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def empty_catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "corpora.json")
    monkeypatch.setattr(server, "_CORPUS_DIR", tmp_path / "corpora")
    monkeypatch.setenv("CANDYCONC_HOME", str(tmp_path))
    (tmp_path / "corpora").mkdir()
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    monkeypatch.delenv("CANDYCONC_INDEX_PATH", raising=False)
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))
    server.reset_default_corpus_runtime_state()
    yield tmp_path
    server.reset_default_corpus_runtime_state()
    server._STARTED_WITHOUT_CORPUS = False


def test_no_pin_and_empty_catalogue_means_empty_start(empty_catalogue):
    assert server._startup_index_path() is None


def test_broken_pin_still_stops_the_start(empty_catalogue, monkeypatch):
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(empty_catalogue / "missing"))
    with pytest.raises(RuntimeError, match="existiert nicht"):
        server._startup_index_path()


def test_deleted_active_corpus_falls_back_to_empty_start(empty_catalogue):
    active = _index_dir(empty_catalogue / "gone")
    corpus.CorpusRegistry.load().register(active, activate=True)
    (active / "index_manifest.json").unlink()
    (active / "meta.bin").unlink()
    assert server._startup_index_path() is None


def test_active_catalogue_corpus_is_opened(empty_catalogue):
    active = _index_dir(empty_catalogue / "active")
    corpus.CorpusRegistry.load().register(active, activate=True)
    assert server._startup_index_path() == active.resolve()


def test_newest_managed_corpus_is_activated_when_none_is_active(empty_catalogue):
    older = _index_dir(empty_catalogue / "corpora" / "older")
    newer = _index_dir(empty_catalogue / "corpora" / "newer")
    import os

    os.utime(older / "index_manifest.json", (1, 1))
    assert server._startup_index_path() == newer.resolve()
    assert corpus.CorpusRegistry.load().active == str(newer.resolve())


def test_staging_and_incomplete_indexes_are_not_activated(empty_catalogue):
    staging = _index_dir(empty_catalogue / "corpora" / ".imports")
    assert staging.exists()
    incomplete = _index_dir(empty_catalogue / "corpora" / "half")
    manifest = json.loads((incomplete / "index_manifest.json").read_text())
    manifest["complete"] = False
    (incomplete / "index_manifest.json").write_text(json.dumps(manifest))
    assert server._startup_index_path() is None


def test_server_starts_without_corpus_and_model(empty_catalogue):
    previous = server.APP_CONFIG.COPILOT_ENDPOINT
    set_config("COPILOT_ENDPOINT", None)
    try:
        with TestClient(server.app) as client:
            assert server._STARTED_WITHOUT_CORPUS is True
            assert client.get("/api/v1/health").status_code == 200
            catalogue = client.get("/api/v1/corpora")
            assert catalogue.status_code == 200, catalogue.text
            token = client.get("/api/v1/auth/dev-token").json()["token"]
            info = client.get("/api/v1/system/info", headers={"Authorization": f"Bearer {token}"}).json()
            assert info["source"] == "no_corpus"
            assert info["copilotConfigured"] is False
            assert info["version"] != "unknown"
    finally:
        if previous is not None:
            set_config("COPILOT_ENDPOINT", previous)


def test_chat_without_model_says_so(monkeypatch):
    previous = server.APP_CONFIG.COPILOT_ENDPOINT
    set_config("COPILOT_ENDPOINT", None)
    try:
        client = TestClient(server.app)
        token = client.post("/api/v1/login", json={"username": "bob", "password": "bob"}).json()["token"]
        response = client.post(
            "/api/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        if previous is not None:
            set_config("COPILOT_ENDPOINT", previous)
    assert response.status_code == 424, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "copilot_not_configured"
    assert "No language model is configured" in detail["message"]


def test_cli_starts_without_index(empty_catalogue, monkeypatch, capsys):
    from candyconc.entrypoints import cli

    captured = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr(cli, "load_settings", lambda: SimpleNamespace(index_dir=""))
    monkeypatch.setattr(cli.sys, "argv", ["candy"])
    cli.main()
    out = capsys.readouterr().out
    assert captured["host"] == "127.0.0.1"
    assert "Corpus: none yet" in out
    assert f":{captured['port']}/" in out


def test_cli_version(monkeypatch, capsys):
    from candyconc.entrypoints import cli
    from candyconc.version import package_version

    monkeypatch.setattr(cli.sys, "argv", ["candy", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    assert package_version() in capsys.readouterr().out


def test_cli_help_lists_the_commands(monkeypatch, capsys):
    from candyconc.entrypoints import cli

    monkeypatch.setattr(cli.sys, "argv", ["candy", "--help"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    for command in ("import", "pipeline", "paths", "migrate-project"):
        assert command in out


def test_cli_explicit_busy_port_is_a_clear_error(monkeypatch):
    import socket

    from candyconc.entrypoints import cli

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        with pytest.raises(SystemExit, match=f"Port {port}"):
            cli._choose_port("127.0.0.1", port)


def test_version_comes_from_the_package_metadata():
    from candyconc.version import package_version

    version = package_version()
    assert version != "unknown"
    assert server.app.version == version
