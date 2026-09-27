"""Regression tests for RFC 7807 error-envelope consistency.

Covers two release-audit findings against ``candyconc.entrypoints.errors``:

* id 29: Starlette routing errors (404 Not Found, 405 Method Not Allowed) must
  render as ``application/problem+json``, not Starlette's default bare
  ``{"detail": "..."}`` body. ``register_exception_handlers`` now wires the
  problem+json handler for ``starlette.exceptions.HTTPException`` too.
* id 36: ``validation_to_problem`` must keep ``detail`` a stable, always-string
  human-readable summary while exposing the structured per-field list under a
  stable sibling key ``errors`` (additive normalization).

The test builds a tiny self-contained FastAPI app and registers the real
handlers, so it needs no corpus index (mirrors ``tests/test_api_redirect.py``).
"""

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from candyconc.entrypoints.errors import register_exception_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/needs-term")
    async def _needs_term(term: str = Query(...)) -> dict:  # noqa: B008
        return {"term": term}

    @app.get("/only-get")
    async def _only_get() -> dict:
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


# --- id 29: routing errors render as problem+json -----------------------------


def test_unknown_route_renders_problem_json():
    """A 404 for an unknown route uses the problem+json envelope, not bare detail."""
    client = _client()
    resp = client.get("/totally/unknown/route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    # Full RFC 7807 envelope, not Starlette's bare {"detail": "Not Found"}.
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert "type" in body
    assert isinstance(body["detail"], str)


def test_method_not_allowed_renders_problem_json():
    """A 405 (wrong method) also uses the problem+json envelope."""
    client = _client()
    resp = client.post("/only-get")
    assert resp.status_code == 405
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 405
    assert body["title"] == "Method Not Allowed"
    assert isinstance(body["detail"], str)


# --- id 36: validation detail is a string + sibling errors list ---------------


def test_validation_error_detail_is_string_with_errors_list():
    """Validation errors keep ``detail`` a string and put rows under ``errors``."""
    client = _client()
    resp = client.get("/needs-term")  # missing required ``term``
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()

    # ``detail`` must reliably be a human-readable string (was an object before).
    assert isinstance(body["detail"], str)
    assert body["detail"]  # non-empty summary

    # Structured per-field detail lives under a stable sibling key ``errors``.
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) >= 1
    first = body["errors"][0]
    assert first["loc"][-1] == "term"
    assert first["type"] == "missing"

    # Standard envelope fields remain present.
    assert body["status"] == 400
    assert body["title"] == "Bad Request"
