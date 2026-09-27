import unittest
import httpx
import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import app

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestPrefSync(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def isolated_storage(self, tmp_path, monkeypatch):
        from candyconc.services.backend import prefs, server

        monkeypatch.setattr(prefs, "_PREFS_PATH", tmp_path / "prefs.json")
        monkeypatch.setattr(prefs, "_LOADED", False)
        for name in ("_PREFS", "_BOOKMARKS", "_LISTENERS"):
            monkeypatch.setattr(prefs, name, {})
        monkeypatch.setattr(server, "_PROJECTS_DIR", tmp_path / "projects")
        monkeypatch.setattr(server, "_PROJECT_USERS", {})
        monkeypatch.setattr(server, "PROJECT_QUOTAS", {})
        monkeypatch.setenv("CANDYCONC_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    def setUp(self):
        self.client = TestClient(app)
        resp = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        )
        self.token = resp.json()["token"]
        self.admin_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        # Ensure project exists and bob can access project-scoped prefs.
        self.client.post(
            "/api/v1/projects/create",
            json={"name": "alpha", "owner": "bob", "token": self.admin_token},
        )

    def test_sync_preferences(self):
        self.client.post(
            "/api/v1/prefs/update", json={"token": self.token, "theme": "dark"}
        )
        state = self.client.get(f"/api/v1/prefs?token={self.token}").json()
        self.assertEqual(state["prefs"].get("theme"), "dark")

    def test_project_scoped_preferences(self):
        self.client.post(
            "/api/v1/prefs/update",
            json={"token": self.token, "project": "alpha", "theme": "blue"},
        )
        alpha = self.client.get(f"/api/v1/prefs?token={self.token}&project=alpha").json()
        default = self.client.get(f"/api/v1/prefs?token={self.token}").json()
        self.assertEqual(alpha["prefs"].get("theme"), "blue")
        self.assertNotEqual(default["prefs"].get("theme"), "blue")

    def test_update_preferences_rejects_unsupported_keys_atomically(self):
        before = self.client.get(f"/api/v1/prefs?token={self.token}").json()["prefs"]
        resp = self.client.post(
            "/api/v1/prefs/update",
            json={"token": self.token, "theme": "dark", "rawSecret": "token"},
        )

        self.assertEqual(resp.status_code, 400)
        after = self.client.get(f"/api/v1/prefs?token={self.token}").json()["prefs"]
        self.assertEqual(after, before)
