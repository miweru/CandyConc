"""The embedding setting accepts the backends the server has.

``POST /settings/embeddings`` set ``jina`` when the body named no backend
and stored any other value as well. ``embed`` serves only ``spacy`` and
``none``, so semantic features then failed with "Nur spaCy Embeddings sind
erlaubt". The route now rejects other values with 422 and a code, and
``GET /settings/embeddings`` reports the backend, the accepted values and
the spaCy pipeline. The capability contract says that no package catalogue
ships and that no analysis reads an installed package.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import candyconc.config as cc_config
from candyconc.capabilities.product import build_product_capability_contract
from candyconc.services.backend import auth
from candyconc.services.backend.server import app


@pytest.fixture()
def admin():
    previous_env = os.environ.get("CANDYCONC_EMB_BACKEND")
    previous_cfg = cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND
    auth._USERS["emb_admin"] = auth.User("emb_admin", auth.hash_password("pw"), "admin")
    yield TestClient(app), {"Authorization": f"Bearer {auth._issue_token('emb_admin')}"}
    if previous_env is None:
        os.environ.pop("CANDYCONC_EMB_BACKEND", None)
    else:
        os.environ["CANDYCONC_EMB_BACKEND"] = previous_env
    cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND = previous_cfg


@pytest.mark.parametrize(
    "body,code",
    [
        ({}, "embeddings.backend_missing"),
        ({"backend": "jina"}, "embeddings.backend_unsupported"),
        ({"backend": "openai"}, "embeddings.backend_unsupported"),
    ],
)
def test_an_unknown_or_missing_backend_is_rejected(admin, body, code):
    client, headers = admin
    before = cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND
    response = client.post(
        "/api/v1/settings/embeddings", json=body, headers={**headers, "Accept-Language": "en"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == code
    assert response.json()["detail"].endswith("Supported: spacy, none.")
    assert cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND == before


def test_a_supported_backend_is_set_and_reported(admin):
    client, headers = admin
    response = client.post("/api/v1/settings/embeddings", json={"backend": "none"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["backend"] == "none"
    state = client.get("/api/v1/settings/embeddings", headers=headers).json()
    assert state["backend"] == "none"
    assert state["supported_backends"] == ["spacy", "none"]
    assert state["spacy_model"] == cc_config.APP_CONFIG.CANDYCONC_EMB_SPACY_MODEL


def test_the_contract_states_the_empty_catalogue():
    contract = build_product_capability_contract()
    capability = next(c for c in contract["capabilities"] if c["id"] == "settings.embedding_management")
    limits = " ".join(str(limit) for limit in capability["limits"])
    assert "vendor/embedding_packages.json" in limits
    operations = {op["id"]: op for op in capability["operations"]}
    assert operations["settings.embedding_management.backend"]["route"]["path"] == "/api/v1/settings/embeddings"
