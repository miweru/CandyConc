"""R5 product gap P0-3: corpus activation + deletion lifecycle endpoints.

Fresh-eyes product audit (§3/§6) found the web "switch corpus" never reached an
activation endpoint (no single server-side source of truth for "active corpus")
and that there was no way to delete a registered corpus. These tests cover, with
NO MOCKS for the registry itself (only the runtime-reload side effect and corpus
dir are redirected to a tmp_path):

* ``POST /api/v1/corpora/{name}/activate`` switches what ``GET /corpora`` reports
  as active, and is reachable as a USER (switching is a read-side action).
* ``DELETE /api/v1/corpora/{name}`` unregisters a corpus and guards the active and
  the last remaining corpus with a 409.
* The underlying :meth:`CorpusRegistry.delete` guard logic directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import candyconc.domain.corpus as corpus
from candyconc.domain.corpus import CorpusRegistry
from candyconc.services.backend.corpus_import_outcome import write_import_outcome


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
                "created_at": "2026-06-12T00:00:00Z",
                "complete": True,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lifecycle_env(tmp_path, monkeypatch):
    """Isolate the registry + corpus dir and stub the runtime reload side effect."""
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    # Keep the managed corpus_dir empty so the catalogue is driven purely by the
    # registry: registered corpora live outside corpus_dir (the real "register an
    # existing index directory" flow), so unregistering them truly hides them.
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir()
    monkeypatch.setattr(server, "_CORPUS_DIR", corpus_dir)
    monkeypatch.setattr(server, "_INDEX_PATH", None)

    async def _noop_reload() -> None:
        return None

    monkeypatch.setattr(server, "reload_default_corpus_runtime_state", _noop_reload)
    # _corpus_dir_and_default() calls _configured_default_index_path on miss; keep
    # the catalogue free of a configured default so only our fixtures show up.
    monkeypatch.setattr(server, "_configured_default_index_path", lambda: None)

    registered = tmp_path / "registered"
    registered.mkdir()
    alpha = _index_dir(registered / "alpha")
    beta = _index_dir(registered / "beta")
    CorpusRegistry.load().register(alpha, activate=True)
    CorpusRegistry.load().register(beta, activate=False)

    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    return client, alpha, beta


# --- CorpusRegistry.delete guard (domain layer) -------------------------------


def test_registry_delete_removes_inactive_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    a = _index_dir(tmp_path / "a")
    b = _index_dir(tmp_path / "b")
    reg = CorpusRegistry.load()
    reg.register(a, activate=True)
    reg.register(b, activate=False)

    CorpusRegistry.load().delete(b)
    reloaded = CorpusRegistry.load()
    assert str(b.resolve(strict=False)) not in reloaded.indices
    assert reloaded.active == str(a.resolve(strict=False))


def test_registry_delete_refuses_active(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    a = _index_dir(tmp_path / "a")
    b = _index_dir(tmp_path / "b")
    reg = CorpusRegistry.load()
    reg.register(a, activate=True)
    reg.register(b, activate=False)

    with pytest.raises(ValueError):
        CorpusRegistry.load().delete(a)
    # Untouched: still registered + still active.
    reloaded = CorpusRegistry.load()
    assert str(a.resolve(strict=False)) in reloaded.indices
    assert reloaded.active == str(a.resolve(strict=False))


def test_registry_delete_refuses_last(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    a = _index_dir(tmp_path / "a")
    reg = CorpusRegistry.load()
    reg.register(a, activate=False)
    # Manually clear active so the "last" guard (not the "active" guard) fires.
    reg = CorpusRegistry.load()
    reg.active = None
    reg.save()

    with pytest.raises(ValueError):
        CorpusRegistry.load().delete(a)
    assert str(a.resolve(strict=False)) in CorpusRegistry.load().indices


def test_registry_delete_unknown_raises_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    a = _index_dir(tmp_path / "a")
    CorpusRegistry.load().register(a, activate=True)
    with pytest.raises(FileNotFoundError):
        CorpusRegistry.load().delete(tmp_path / "never_registered")


# --- Activation route ---------------------------------------------------------


def test_activate_switches_reported_active(lifecycle_env):
    client, _alpha, _beta = lifecycle_env

    before = {c["name"]: c for c in client.get("/api/v1/corpora").json()["corpora"]}
    assert before["alpha"]["active"] is True
    assert before["beta"]["active"] is False

    r = client.post("/api/v1/corpora/beta/activate")
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True

    after = {c["name"]: c for c in client.get("/api/v1/corpora").json()["corpora"]}
    assert after["beta"]["active"] is True
    assert after["alpha"]["active"] is False


def test_activate_unknown_corpus_404(lifecycle_env):
    client, _alpha, _beta = lifecycle_env
    r = client.post("/api/v1/corpora/does_not_exist/activate")
    assert r.status_code == 404, r.text


def test_activate_partial_import_requires_explicit_acknowledgement(lifecycle_env):
    client, _alpha, beta = lifecycle_env
    write_import_outcome(
        beta,
        {
            "partial_input": True,
            "rejected_rows": 2,
            "import_warnings": ["2 Eingabezeilen wurden verworfen."],
        },
    )

    blocked = client.post("/api/v1/corpora/beta/activate")

    assert blocked.status_code == 409, blocked.text
    assert "Teilimport" in blocked.json()["detail"]

    report = client.get("/api/v1/corpora/beta/build-report")
    assert report.status_code == 200, report.text
    assert report.json()["reports"]["import_outcome"]["partial_input"] is True

    confirmed = client.post(
        "/api/v1/corpora/beta/activate",
        json={"acknowledge_partial_input": True},
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["active"] is True


def test_overlong_corpus_name_400_across_lifecycle_routes(lifecycle_env):
    """CORPUS-LIFECYCLE-01: a crafted >255-byte path component must read as a
    clean 400 (invalid name), not a 500 from an unguarded OSError(ENAMETOOLONG)
    raised by ``Path.exists`` inside ``inspect_corpus_status``.

    Verifies the fix on every sibling lifecycle endpoint that funnels through
    ``CorpusRegistryService.inspect`` — activate, capabilities, build-report.
    """
    client, _alpha, _beta = lifecycle_env
    long_name = "x" * 500

    activate = client.post(f"/api/v1/corpora/{long_name}/activate")
    assert activate.status_code == 400, activate.text

    capabilities = client.get(f"/api/v1/corpora/{long_name}/capabilities")
    assert capabilities.status_code == 400, capabilities.text

    build_report = client.get(f"/api/v1/corpora/{long_name}/build-report")
    assert build_report.status_code == 400, build_report.text


# --- Delete route -------------------------------------------------------------


def test_delete_removes_inactive_corpus(lifecycle_env):
    client, _alpha, _beta = lifecycle_env

    r = client.delete("/api/v1/corpora/beta")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"

    names = {c["name"] for c in client.get("/api/v1/corpora").json()["corpora"]}
    assert "beta" not in names
    assert "alpha" in names


def test_delete_refuses_active_corpus_409(lifecycle_env):
    client, _alpha, _beta = lifecycle_env
    r = client.delete("/api/v1/corpora/alpha")
    assert r.status_code == 409, r.text
    # Still present after the refusal.
    names = {c["name"] for c in client.get("/api/v1/corpora").json()["corpora"]}
    assert "alpha" in names


def test_delete_refuses_last_corpus_409(lifecycle_env):
    client, _alpha, _beta = lifecycle_env
    # Remove beta first (allowed), then activating beta would be gone; instead
    # delete beta, switch active to alpha-only, then deleting the sole remaining
    # corpus must 409.
    assert client.delete("/api/v1/corpora/beta").status_code == 200
    # Now only alpha remains and it is active -> active guard already 409s; assert it.
    r = client.delete("/api/v1/corpora/alpha")
    assert r.status_code == 409, r.text


def test_delete_unknown_corpus_404(lifecycle_env):
    client, _alpha, _beta = lifecycle_env
    r = client.delete("/api/v1/corpora/does_not_exist")
    assert r.status_code == 404, r.text


def test_delete_default_refused_409(lifecycle_env):
    client, _alpha, _beta = lifecycle_env
    r = client.delete("/api/v1/corpora/default")
    assert r.status_code == 409, r.text
