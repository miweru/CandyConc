import unittest
import httpx
import time
from fastapi.testclient import TestClient

import importlib

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestRateLimit(unittest.TestCase):
    def setUp(self):
        # NOTE: do NOT pop "candyconc.services.backend" from sys.modules here:
        # that replaces the package object mid-run and strips submodule
        # attributes that later tests patch via dotted names (test_subcorpora_p0,
        # test_ws_query, ...). Rate-limit state is reset explicitly via
        # rate_limit.reset() below instead.
        backend = importlib.import_module("candyconc.services.backend")
        rate_limit_mod = importlib.import_module("candyconc.services.backend.rate_limit")
        self.rate_limit = rate_limit_mod
        self.client = TestClient(backend.app)
        self.rate_limit.reset()
        self.rate_limit.set_window(1.0)
        self.user_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        # Per-user limits are configured via the rate_limit module API (the
        # former admin REST endpoint was removed).
        self.rate_limit.set_limit("bob", 2)

    def tearDown(self):
        self.rate_limit.reset()

    def test_rate_limit_enforced(self):
        for _ in range(2):
            resp = self.client.get(f"/api/v1/prefs?token={self.user_token}")
            self.assertIsInstance(resp.json(), dict)
        # The middleware serializes the overrun as a 429 problem+json response
        # (previously the HTTPException leaked through as a server error).
        resp = self.client.get(f"/api/v1/prefs?token={self.user_token}")
        self.assertEqual(resp.status_code, 429)
        self.assertTrue(resp.headers["content-type"].startswith("application/problem+json"))

    def test_limit_resets_after_window(self):
        for _ in range(2):
            self.client.get(f"/api/v1/prefs?token={self.user_token}")
        time.sleep(1.1)
        for _ in range(2):
            resp = self.client.get(f"/api/v1/prefs?token={self.user_token}")
            self.assertIsInstance(resp.json(), dict)

    def test_higher_burst_limit(self):
        self.rate_limit.set_limit("bob", 3)
        for _ in range(3):
            resp = self.client.get(f"/api/v1/prefs?token={self.user_token}")
            self.assertEqual(resp.status_code, 200)
        resp = self.client.get(f"/api/v1/prefs?token={self.user_token}")
        self.assertEqual(resp.status_code, 429)


if __name__ == "__main__":
    unittest.main()
