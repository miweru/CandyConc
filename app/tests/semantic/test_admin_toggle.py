import unittest
from fastapi.testclient import TestClient

import importlib
import sys
import os

sys.modules["fastapi"] = importlib.import_module("fastapi")
# NOTE: do NOT pop "candyconc.services.backend" here.  pytest imports every
# test module during collection, so a module-level pop replaces the cached
# backend module AFTER other test modules already bound references to it —
# their monkeypatches then target a different module object than the one
# exercised (same class of bug as the cured tests/ai/test_observability.py).
# A plain import works: the conftest only stubs leaf modules.
backend = importlib.import_module("candyconc.services.backend")


class TestAdminToggle(unittest.TestCase):
    def setUp(self):
        # /settings/embeddings mutates process-global state (os.environ AND
        # candyconc.config.APP_CONFIG via set_config). Save both and restore
        # them in tearDown so later tests are not poisoned with backend=none.
        import candyconc.config as cc_config

        self._cc_config = cc_config
        self._old_env = os.environ.get("CANDYCONC_EMB_BACKEND")
        self._old_cfg = cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND
        self.client = TestClient(backend.app)
        self.admin_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        self.client.post(
            "/api/v1/settings/embeddings",
            json={"backend": "none", "token": self.admin_token},
        )
        assert os.environ.get("CANDYCONC_EMB_BACKEND") == "none"

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("CANDYCONC_EMB_BACKEND", None)
        else:
            os.environ["CANDYCONC_EMB_BACKEND"] = self._old_env
        self._cc_config.APP_CONFIG.CANDYCONC_EMB_BACKEND = self._old_cfg

    def test_disabled(self):
        self.assertEqual(os.environ.get("CANDYCONC_EMB_BACKEND"), "none")

if __name__ == "__main__":
    unittest.main()
