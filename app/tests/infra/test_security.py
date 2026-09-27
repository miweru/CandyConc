import unittest
import httpx
from fastapi.testclient import TestClient

import os
import sys
from importlib import reload
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CANDYCONC_ENABLE_RBAC"] = "1"

import candyconc.services.backend as backend  # noqa: E402

backend = reload(backend)
app = backend.app

_orig_client_init = httpx.Client.__init__

def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)

httpx.Client.__init__ = _patched_init  # type: ignore


class TestSecurity(unittest.TestCase):
    def setUp(self):
        # RBAC_ENABLED is computed once at auth-module import from the
        # APP_CONFIG snapshot (src/candyconc/services/backend/auth.py:21);
        # setting the env var afterwards has no effect. Flip the module flag
        # directly and restore it afterwards.
        from candyconc.services.backend import auth as _auth

        self._auth = _auth
        self._old_rbac = _auth.RBAC_ENABLED
        _auth.RBAC_ENABLED = True
        self.client = TestClient(app)

    def tearDown(self):
        self._auth.RBAC_ENABLED = self._old_rbac

    def test_admin_route_requires_authentication(self):
        # /api/v1/metrics is admin-classified in the route matrix; anonymous
        # access must be rejected as problem+json by the middleware gate.
        resp = self.client.get("/api/v1/metrics")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/metrics")

    def test_sql_injection_login(self):
        payload = {"username": "alice' OR '1'='1", "password": "pw"}
        resp = self.client.post("/api/v1/login", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/login")


if __name__ == "__main__":
    unittest.main()
