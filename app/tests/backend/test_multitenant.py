import unittest
import httpx
import pytest
from fastapi.testclient import TestClient

import importlib

# NOTE: do NOT pop "candyconc.services.backend" from sys.modules here. This
# module is imported at collection time; popping the package replaces it with a
# fresh module object that lacks attributes for already-imported submodules
# (e.g. .kwic), which breaks mock.patch dotted lookups in sibling test modules
# (test_kwic_rows, test_ws_query) for the rest of the run.
backend = importlib.import_module("candyconc.services.backend")
importlib.import_module("candyconc.services.backend.server")
app = backend.app

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestMultiTenant(unittest.TestCase):
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
        self.admin_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        # Users are provisioned via the auth module API (the former admin REST
        # endpoint was removed); create_user overwrites idempotently.
        auth = importlib.import_module("candyconc.services.backend.auth")
        auth.add_user("charlie", "charlie", "user")
        self.client.post(
            "/api/v1/projects/create",
            json={"name": "p1", "owner": "bob", "token": self.admin_token},
        )
        self.client.post(
            "/api/v1/projects/create",
            json={"name": "p2", "owner": "charlie", "token": self.admin_token},
        )
        self.bob_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        self.charlie_token = self.client.post(
            "/api/v1/login", json={"username": "charlie", "password": "charlie"}
        ).json()["token"]

    def test_isolated_project_preferences(self):
        self.client.post(
            "/api/v1/prefs/update",
            json={"token": self.bob_token, "project": "p1", "theme": "forest"},
        )
        state = self.client.get(f"/api/v1/prefs?token={self.bob_token}&project=p1").json()
        self.assertEqual(state["prefs"].get("theme"), "forest")

        resp = self.client.get(f"/api/v1/prefs?token={self.bob_token}&project=p2")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/prefs")

        self.client.post(
            "/api/v1/prefs/update",
            json={"token": self.charlie_token, "project": "p2", "theme": "amber"},
        )
        state2 = self.client.get(
            f"/api/v1/prefs?token={self.charlie_token}&project=p2"
        ).json()
        self.assertEqual(state2["prefs"].get("theme"), "amber")
        self.assertNotEqual(state2["prefs"].get("theme"), "forest")

        resp = self.client.get(f"/api/v1/prefs?token={self.charlie_token}&project=p1")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/prefs")


if __name__ == "__main__":
    unittest.main()
