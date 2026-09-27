"""S5b Single-Command-Start: SPA-Auslieferung des gebauten Frontends.

Mit Dist-Verzeichnis liefert '/' die index.html, Assets kommen mit korrektem
Content-Type, Deep-Links fallen auf index.html zurück und die API-Familie
(inkl. unbekannter /api-Pfade) bleibt unverändert. Ohne Dist ist das
Verhalten byte-gleich zum Zustand vor dem Feature (Regressionsanker).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import frontend_static
from candyconc.services.backend.server import app


@pytest.fixture
def no_frontend():
    """Etwaige (lokal auto-erkannte) SPA-Mounts entfernen und restaurieren."""
    removed = frontend_static.uninstall_frontend(app)
    try:
        yield
    finally:
        for route in removed:
            app.router.routes.append(route)


@pytest.fixture
def tmp_frontend(tmp_path, no_frontend):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>CandyConc</title><div id=\"spa-marker\"></div>",
        encoding="utf-8",
    )
    (dist / "assets" / "x.js").write_text("console.log('ok')", encoding="utf-8")
    installed = frontend_static.install_frontend(app, dist)
    assert installed == dist
    try:
        yield dist
    finally:
        frontend_static.uninstall_frontend(app)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# --- mit Dist -----------------------------------------------------------------


def test_root_serves_index_html(tmp_frontend):
    resp = _client().get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "spa-marker" in resp.text


def test_asset_is_served_with_correct_content_type(tmp_frontend):
    resp = _client().get("/assets/x.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert resp.text == "console.log('ok')"


def test_deep_link_falls_back_to_index_html(tmp_frontend):
    resp = _client().get("/subcorpora/irgendwas/tiefer")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "spa-marker" in resp.text


def test_missing_asset_with_extension_is_404_not_index_html(tmp_frontend):
    """Stale-Chunk-Schutz: ein fehlender Asset-Pfad mit Dateiendung bleibt 404.

    Ein Client mit veralteter Chunk-Liste (z. B. offener Tab über ein Deploy
    hinweg) darf für /assets/alt.js kein 200/index.html bekommen, das der
    Browser dann als Skript zu parsen versucht.
    """
    client = _client()
    for path in ("/assets/alt-chunk.js", "/assets/fehlt.css", "/veraltet.js"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert resp.headers["content-type"].startswith(
            "application/problem+json"
        ), path


def test_deep_link_with_dot_in_middle_segment_still_falls_back(tmp_frontend):
    # Nur die Dateiendung des LETZTEN Segments zählt: /subcorpora/v1.2/tiefer
    # ist ein Deep-Link, keine Datei-Anfrage.
    resp = _client().get("/subcorpora/v1.2/tiefer")
    assert resp.status_code == 200
    assert "spa-marker" in resp.text


def test_existing_asset_with_extension_is_still_served(tmp_frontend):
    resp = _client().get("/assets/x.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('ok')"


def test_health_endpoint_is_unchanged_by_the_mount(tmp_frontend):
    resp = _client().get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_unknown_api_path_keeps_problem_json_404(tmp_frontend):
    resp = _client().get("/api/v1/definitiv-nicht-vorhanden")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["title"] == "Not Found"


def test_unknown_mcp_and_ws_paths_keep_404(tmp_frontend):
    client = _client()
    for path in ("/mcp/nicht-da", "/ws/nicht-da", "/healthz/nicht-da"):
        resp = client.get(path)
        assert resp.status_code == 404, path
        assert resp.headers["content-type"].startswith(
            "application/problem+json"
        ), path


def test_non_get_on_unknown_path_stays_404_not_405(tmp_frontend):
    resp = _client().post("/irgendwas")
    assert resp.status_code == 404


# --- ohne Dist (Regressionsanker: Verhalten wie vor dem Feature) ---------------


def test_without_dist_root_keeps_todays_404_problem_json(no_frontend):
    resp = _client().get("/")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/"


def test_without_dist_unknown_path_keeps_404(no_frontend):
    resp = _client().get("/irgendwas")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


# --- Dist-Aufloesung ----------------------------------------------------------


def test_env_dist_without_index_html_counts_as_missing(tmp_path, monkeypatch):
    empty = tmp_path / "leer"
    empty.mkdir()
    monkeypatch.setenv(frontend_static.FRONTEND_DIST_ENV, str(empty))
    assert frontend_static.frontend_dist_dir() is None


def test_env_dist_with_index_html_wins(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv(frontend_static.FRONTEND_DIST_ENV, str(dist))
    assert frontend_static.frontend_dist_dir() == dist


def test_install_without_dist_is_a_noop(tmp_path, monkeypatch, no_frontend):
    monkeypatch.setenv(frontend_static.FRONTEND_DIST_ENV, str(tmp_path / "fehlt"))
    routes_before = list(app.router.routes)
    assert frontend_static.install_frontend(app) is None
    assert app.router.routes == routes_before


def test_packaged_interface_is_found_without_env(tmp_path, monkeypatch):
    """An installed wheel serves the interface shipped in candyconc/web_dist."""
    packaged = tmp_path / "web_dist"
    packaged.mkdir()
    (packaged / "index.html").write_text("<div id=\"app\"></div>", encoding="utf-8")
    monkeypatch.delenv(frontend_static.FRONTEND_DIST_ENV, raising=False)
    monkeypatch.setattr(frontend_static, "packaged_dist_dir", lambda: packaged)
    assert frontend_static.frontend_dist_dir() == packaged


def test_env_dist_beats_the_packaged_interface(tmp_path, monkeypatch):
    packaged = tmp_path / "web_dist"
    packaged.mkdir()
    (packaged / "index.html").write_text("packaged", encoding="utf-8")
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    (explicit / "index.html").write_text("explicit", encoding="utf-8")
    monkeypatch.setattr(frontend_static, "packaged_dist_dir", lambda: packaged)
    monkeypatch.setenv(frontend_static.FRONTEND_DIST_ENV, str(explicit))
    assert frontend_static.frontend_dist_dir() == explicit


def test_packaged_dist_dir_is_inside_the_package():
    import candyconc

    assert frontend_static.packaged_dist_dir() == Path(candyconc.__file__).resolve().parent / "web_dist"


# --- Cache-Control (update to a new wheel must not leave a blank page) ---------


@pytest.fixture
def hashed_frontend(tmp_path, no_frontend):
    """A dist laid out like a Vite build: hashed chunks under assets/."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><script type=\"module\" src=\"/assets/index-Ab3dE_9z.js\"></script>",
        encoding="utf-8",
    )
    (dist / "assets" / "index-Ab3dE_9z.js").write_text("console.log('v2')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    frontend_static.install_frontend(app, dist)
    try:
        yield dist
    finally:
        frontend_static.uninstall_frontend(app)


def test_index_html_is_revalidated_on_every_load(hashed_frontend):
    """After an update the browser must fetch the new index.html.

    Without Cache-Control the browser may reuse the old index.html from its
    heuristic cache. Its chunk names no longer exist and the page stays blank.
    """
    client = _client()
    for path in ("/", "/index.html", "/subcorpora/tief"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.headers.get("cache-control") == "no-cache", path


def test_not_modified_index_html_keeps_no_cache(hashed_frontend):
    client = _client()
    first = client.get("/")
    resp = client.get("/", headers={"if-none-match": first.headers["etag"]})
    assert resp.status_code == 304
    assert resp.headers.get("cache-control") == "no-cache"


def test_hashed_assets_may_be_cached_long(hashed_frontend):
    resp = _client().get("/assets/index-Ab3dE_9z.js")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "public, max-age=31536000, immutable"


def test_unhashed_files_are_revalidated(hashed_frontend):
    resp = _client().get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-cache"


def test_asset_without_content_hash_is_not_immutable(tmp_frontend):
    resp = _client().get("/assets/x.js")
    assert resp.headers.get("cache-control") == "no-cache"
