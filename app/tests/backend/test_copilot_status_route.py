"""``GET /api/v1/copilot/status`` tells the interface whether a model is set up.

Without a configured model the chat answered 424 ``copilot_not_configured``
only after a question was sent, and the panel looked ready (erprobung B13).
The route is read at call time, so a change of the model route applies at
once. It sends nothing to the model server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candyconc import config


@pytest.fixture
def client():
    from candyconc.services.backend.server import app

    return TestClient(app)


@pytest.fixture
def restore_model_route():
    endpoint = config.get("COPILOT_ENDPOINT")
    model = config.get("COPILOT_MODEL")
    yield
    config.set("COPILOT_ENDPOINT", endpoint)
    config.set("COPILOT_MODEL", model)


def test_status_without_endpoint(client, restore_model_route):
    config.set("COPILOT_ENDPOINT", "")
    response = client.get("/api/v1/copilot/status")
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is False


def test_status_follows_a_changed_model_route(client, restore_model_route):
    config.set("COPILOT_ENDPOINT", "http://127.0.0.1:9/v1/responses")
    config.set("COPILOT_MODEL", "example-model")
    body = client.get("/api/v1/copilot/status").json()
    assert body == {"configured": True, "model": "example-model"}


def test_status_route_is_classified():
    from candyconc.services.backend.route_matrix import policy_for_path

    assert policy_for_path("/api/v1/copilot/status") is not None
