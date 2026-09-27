import os
import sys
import importlib.util
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _load_backend():
    spec = importlib.util.spec_from_file_location(
        "candyconc.services.backend.server", ROOT / "src" / "candyconc" / "services" / "backend" / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[arg-type]
    pkg = types.ModuleType("candyconc.services.backend")
    pkg.__path__ = [str(ROOT / "src" / "candyconc" / "services" / "backend")]
    pkg.server = module
    pkg.app = module.app
    sys.modules["candyconc.services.backend"] = pkg
    sys.modules["candyconc.services.backend.server"] = module
    return module


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("error")


class TestResponseFormat(unittest.IsolatedAsyncioTestCase):
    # sys.modules entries _load_backend overwrites; snapshot in asyncSetUp and
    # restore in asyncTearDown so the fresh server module does not shadow the
    # canonical cached modules for tests that RUN later (importlib.reload in
    # tests/services would fail with "module ... not in sys.modules").
    _TOUCHED_MODULES = (
        "candyconc.services.backend",
        "candyconc.services.backend.server",
    )

    async def asyncSetUp(self):
        self._saved_modules = {
            k: sys.modules.get(k) for k in self._TOUCHED_MODULES
        }

    async def asyncTearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    async def test_fallback_on_invalid_json(self):
        async def fake_post(self, url, json, timeout, headers=None, **kwargs):
            # llm_client passes headers= and may add kwargs (src/candyconc/services/llm_client.py)
            return FakeResponse({"choices": [{"message": {"content": "{oops}"}}]})

        module = _load_backend()
        import candyconc.config as cc_config

        with patch.dict(os.environ, {"COPILOT_ENDPOINT": "http://test"}), patch.object(
            cc_config.APP_CONFIG,
            "COPILOT_ENDPOINT",
            "http://test/v1/chat/completions",
        ), patch.object(cc_config.APP_CONFIG, "COPILOT_MODEL", "test-model"):
            with patch("httpx.AsyncClient.post", fake_post):
                client = TestClient(module.app)
                resp = client.post("/api/v1/semantic/recluster", json={"clusters": []})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"merges": [], "splits": [], "renames": {}})

    async def test_response_format_passed(self):
        sent_payloads = []

        async def fake_post(self, url, json=None, timeout=5, headers=None, **kwargs):
            sent_payloads.append(dict(json or {}))
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": __import__("json").dumps(
                                    {"merges": [[1, 2]], "splits": [], "renames": {}}
                                )
                            }
                        }
                    ]
                }
            )

        module = _load_backend()
        # Config is loaded once at import (candyconc/config.py: APP_CONFIG);
        # patching os.environ afterwards has no effect. A chat-completions
        # endpoint is required for response_format: the responses route uses
        # a prompt hint instead (llm_client._build_route_candidates).
        import candyconc.config as cc_config

        with patch.object(
            cc_config.APP_CONFIG, "COPILOT_ENDPOINT", "http://test/v1/chat/completions"
        ), patch.object(cc_config.APP_CONFIG, "COPILOT_MODEL", "test-model"), patch.object(
            cc_config.APP_CONFIG, "USE_STRUCTURED_OUTPUT", True
        ):
            with patch("httpx.AsyncClient.post", fake_post):
                client = TestClient(module.app)
                resp = client.post("/api/v1/semantic/recluster", json={"clusters": []})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["merges"], [[1, 2]])
        self.assertTrue(sent_payloads, "No request was sent")
        self.assertIn("response_format", sent_payloads[-1])
