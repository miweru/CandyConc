"""Every preference the settings dialog stores must pass the server allowlist.

``backgroundResearch`` was missing from ``ALLOWED_PREF_KEYS``. The switch
"Background research" and "Reset settings" (which sends every preference at
once) then failed with 400 "unsupported preference key", and the web store
kept the old value because it only applies a preference after the server
accepted it.

UI_PREFERENCE_KEYS mirrors ``UserPreferences`` in
``candyconc-web/src/stores/settings.ts``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

UI_PREFERENCE_KEYS = {
    "language": "en",
    "defaultCorpus": "sotu_en",
    "resultsPerPage": "100",
    "highlightColor": "yellow",
    "fontFamily": "system",
    "fontSize": "medium",
    "confirmDelete": "true",
    "enableShortcuts": "true",
    "backgroundResearch": "false",
}


def test_every_ui_preference_key_is_allowed():
    from candyconc.services.backend import prefs

    assert prefs._validated_pref_update(UI_PREFERENCE_KEYS) == UI_PREFERENCE_KEYS


@pytest.fixture
def client(tmp_path, monkeypatch):
    from candyconc.services.backend import prefs, server

    monkeypatch.setattr(prefs, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(prefs, "_LOADED", False)
    for name in ("_PREFS", "_BOOKMARKS", "_LISTENERS"):
        monkeypatch.setattr(prefs, name, {})
    return TestClient(server.app)


def test_reset_payload_is_stored_and_read_back(client):
    response = client.post("/api/v1/prefs/update", json={"project": "default", **UI_PREFERENCE_KEYS})
    assert response.status_code == 200, response.text
    stored = client.get("/api/v1/prefs", params={"project": "default"}).json()["prefs"]
    for key, value in UI_PREFERENCE_KEYS.items():
        assert stored.get(key) == value, key


def test_background_research_switch_is_stored(client):
    response = client.post(
        "/api/v1/prefs/update", json={"project": "default", "backgroundResearch": "false"}
    )
    assert response.status_code == 200, response.text
    stored = client.get("/api/v1/prefs", params={"project": "default"}).json()["prefs"]
    assert stored["backgroundResearch"] == "false"
