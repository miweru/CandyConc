import os
import sys
import importlib
import tempfile
import unittest
from fastapi.testclient import TestClient

sys.modules["fastapi"] = importlib.import_module("fastapi")
# NOTE: no module-level sys.modules.pop here — pytest imports all test
# modules at collection time, and popping the cached backend module breaks
# references bound earlier by other test modules (tests/ai/test_observability
# pattern).  A plain import works: the conftest only stubs leaf modules.
backend = importlib.import_module("candyconc.services.backend")


class TestClusterPersist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CANDYCONC_PROJECTS_DIR"] = self.tmp.name
        self.client = TestClient(backend.app)
        self.token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("CANDYCONC_PROJECTS_DIR", None)

    def test_put_get(self):
        clusters = [{"id": 1, "label": "a", "tokens": ["x"], "centroid": [0.0, 1.0]}]
        resp = self.client.put(
            f"/api/v1/projects/default/clusters?token={self.token}", json=clusters
        )
        self.assertEqual(resp.status_code, 200)
        data = self.client.get(
            f"/api/v1/projects/default/clusters?token={self.token}"
        )
        self.assertEqual(data.status_code, 200)
        self.assertEqual(data.json(), clusters)

    def test_duplicate_rename(self):
        clusters = [
            {"id": 1, "label": "a", "tokens": [], "centroid": [0]},
            {"id": 2, "label": "b", "tokens": [], "centroid": [0]},
        ]
        self.client.put(
            f"/api/v1/projects/default/clusters?token={self.token}", json=clusters
        )
        resp = self.client.patch(
            f"/api/v1/projects/default/clusters/rename?token={self.token}",
            json={"id": 2, "label": "a"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/projects/default/clusters/rename")

    def test_duplicate_put(self):
        clusters = [
            {"id": 1, "label": "dup", "tokens": [], "centroid": [0]},
            {"id": 2, "label": "dup", "tokens": [], "centroid": [0]},
        ]
        resp = self.client.put(
            f"/api/v1/projects/default/clusters?token={self.token}", json=clusters
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/projects/default/clusters")


