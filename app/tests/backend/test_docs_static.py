"""The bundled user documentation under ``/docs/`` (erprobung B17).

The help button only showed keyboard shortcuts. The server now serves a
packaged Sphinx build under ``/docs/``, found like the interface
(``frontend_static``), and ``/api/v1/help`` tells the menu whether one exists.
``/docs`` without a slash stays the API page of FastAPI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import docs_static, frontend_static
from candyconc.services.backend.server import app


@pytest.fixture
def no_docs():
    removed = docs_static.uninstall_docs(app)
    try:
        yield
    finally:
        docs_static.uninstall_docs(app)
        for route in removed:
            app.router.routes.append(route)


@pytest.fixture
def tmp_docs(tmp_path, no_docs):
    dist = tmp_path / "html"
    (dist / "guides").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>CandyConc docs</title>docs-marker", encoding="utf-8")
    (dist / "guides" / "index.html").write_text("<!doctype html>guide-marker", encoding="utf-8")
    assert docs_static.install_docs(app, dist) == dist
    yield dist


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_docs_index_and_subpages_are_served(tmp_docs):
    client = _client()
    index = client.get("/docs/")
    assert index.status_code == 200
    assert "docs-marker" in index.text
    assert "guide-marker" in client.get("/docs/guides/").text


def test_docs_without_slash_stays_the_api_page(tmp_docs):
    response = _client().get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_help_route_reports_the_documentation(tmp_docs):
    body = _client().get("/api/v1/help").json()
    assert body == {"docsAvailable": True, "docsUrl": "/docs/"}


def test_help_route_without_documentation(no_docs):
    body = _client().get("/api/v1/help").json()
    assert body == {"docsAvailable": False, "docsUrl": None}
    # Starlette redirects /docs/ to the API page /docs when no manual is mounted.
    response = _client().get("/docs/", follow_redirects=False)
    assert response.status_code in (307, 404)


def test_docs_mount_goes_before_the_interface(tmp_path, no_docs):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text("spa-marker", encoding="utf-8")
    removed = frontend_static.uninstall_frontend(app)
    try:
        frontend_static.install_frontend(app, spa)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "index.html").write_text("docs-marker", encoding="utf-8")
        docs_static.install_docs(app, docs)
        assert "docs-marker" in _client().get("/docs/").text
        assert "spa-marker" in _client().get("/anything").text
    finally:
        frontend_static.uninstall_frontend(app)
        for route in removed:
            app.router.routes.append(route)


def test_search_order(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    monkeypatch.setenv(docs_static.DOCS_DIST_ENV, str(explicit))
    assert docs_static.docs_dist_dir() is None  # set but empty: no fallback
    explicit.mkdir()
    (explicit / "index.html").write_text("x", encoding="utf-8")
    assert docs_static.docs_dist_dir() == explicit
    monkeypatch.delenv(docs_static.DOCS_DIST_ENV)
    packaged = docs_static.packaged_docs_dir()
    found = docs_static.docs_dist_dir()
    if (packaged / "index.html").is_file():
        assert found == packaged
    elif found is not None:
        assert found.parts[-3:] == ("docs", "_build", "html")


def test_help_route_is_public():
    from candyconc.services.backend.route_matrix import AccessLevel, policy_for_path

    policy = policy_for_path("/api/v1/help")
    assert policy is not None and policy.access == AccessLevel.PUBLIC


def test_docs_pages_and_files_are_revalidated(tmp_docs):
    """Sphinx output has unhashed names (searchindex.js, _images/...).

    After an update the browser must not show pages or search data of the
    previous version, so every file under /docs/ is revalidated.
    """
    (tmp_docs / "searchindex.js").write_text("Search.setIndex({})", encoding="utf-8")
    client = _client()
    for path in ("/docs/", "/docs/guides/", "/docs/index.html", "/docs/searchindex.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path
    first = client.get("/docs/")
    again = client.get("/docs/", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers.get("cache-control") == "no-cache"
