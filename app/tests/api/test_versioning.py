from fastapi.testclient import TestClient
import importlib

# use real backend server
server = importlib.import_module("candyconc.services.backend.server")
app = server.app
client = TestClient(app)

def test_health_endpoint() -> None:
    """Ensure the health check returns an OK status."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "engine" in data

def test_api_redirect():
    resp = client.get("/api/foo", follow_redirects=False)
    assert resp.status_code == 404
    assert resp.json().get("detail") == "Not Found"

def test_problem_response():
    resp = client.post("/api/v1/semantic/outline", json={"clusters": "oops"})
    assert resp.status_code == 400
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body.get("title") == "Bad Request"
    assert body.get("status") == 400
    assert body.get("instance") == "/api/v1/semantic/outline"

def test_legacy_path_redirect_and_404() -> None:
    resp = client.get("/api/health", follow_redirects=False)
    assert resp.status_code == 404
    assert resp.json().get("detail") == "Not Found"

    not_found = client.get("/api/unknown")
    assert not_found.status_code == 404
    assert not_found.json().get("detail") == "Not Found"

def test_empty_term_error() -> None:
    resp = client.get("/api/v1/query")
    assert resp.status_code == 400
    assert resp.headers["content-type"] == "application/problem+json"
    data = resp.json()
    assert data.get("status") == 400
    assert data.get("instance") == "/api/v1/query"
