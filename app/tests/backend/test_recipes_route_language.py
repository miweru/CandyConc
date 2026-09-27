"""GET /copilot/recipes answers in the interface language.

The route showed recipe names, purposes, example questions and step goals in
German only, also for ``Accept-Language: en``. The recipe ids stay the same in
both languages, the German texts stay the default.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candyconc.candyconc_copilot.recipes_data import RECIPES_DATA, RECIPES_UI_EN
from candyconc.services.backend import auth
from candyconc.services.backend.server import app

EN = {"Accept-Language": "en, de;q=0.5"}
DE = {"Accept-Language": "de, en;q=0.5"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def token() -> dict[str, str]:
    return {"Authorization": "Bearer " + auth._issue_token("recipes_language")}


def _recipes(client, headers):
    response = client.get("/api/v1/copilot/recipes", headers=headers)
    assert response.status_code == 200, response.text
    return {entry["id"]: entry for entry in response.json()["recipes"]}


def test_every_recipe_has_english_interface_texts():
    for raw in RECIPES_DATA:
        english = RECIPES_UI_EN.get(raw["id"])
        assert english, raw["id"]
        for field in ("name", "einsatz", "beispiel_frage"):
            assert str(english.get(field) or "").strip(), (raw["id"], field)
        assert len(english["schritte"]) == len(raw["schritte"]), raw["id"]


def test_english_request_gets_english_texts_with_the_same_ids(client, token):
    english = _recipes(client, {**token, **EN})
    german = _recipes(client, {**token, **DE})
    default = _recipes(client, dict(token))
    assert list(english) == list(german) == [raw["id"] for raw in RECIPES_DATA]
    for raw in RECIPES_DATA:
        rid = raw["id"]
        expected = RECIPES_UI_EN[rid]
        assert english[rid]["name"] == expected["name"]
        assert english[rid]["einsatz"] == expected["einsatz"]
        assert english[rid]["beispiel_frage"] == expected["beispiel_frage"]
        assert english[rid]["schritte"] == list(expected["schritte"])
        assert german[rid]["name"] == raw["name"]
        assert german[rid]["einsatz"] == raw["einsatz"]
        assert german[rid]["beispiel_frage"] == raw["beispiel_frage"]
        assert german[rid]["schritte"] == [step["ziel"] for step in raw["schritte"]]
        assert default[rid] == german[rid]
