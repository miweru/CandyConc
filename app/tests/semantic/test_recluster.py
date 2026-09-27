import unittest
import importlib.util
import types
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.modules["fastapi"] = importlib.import_module("fastapi")
ROOT = Path(__file__).resolve().parents[2]

# sys.modules entries that _load_backend overwrites; snapshot in setUp and
# restore in tearDown so the fresh server module / fake backend package do
# not leak into tests that RUN later (they would shadow the canonical cached
# modules other test modules bound references to at collection time).
_TOUCHED_MODULES = (
    "candyconc.services.backend",
    "candyconc.services.backend.server",
)


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


class TestRecluster(unittest.TestCase):
    def setUp(self):
        # The recluster endpoint resolves the LLM via the server module
        # (routes/semantic.py: `from .. import server as _server`), so the
        # fake must be patched onto the loaded server module object.
        self._saved_modules = {k: sys.modules.get(k) for k in _TOUCHED_MODULES}
        self.server = _load_backend()
        self.client = TestClient(self.server.app)

    def tearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_merge_plan(self):
        clusters = [
            {"id": 1, "label": "a", "size": 2, "centroid": [1.0, 0.0], "samples": ["x"]},
            {"id": 2, "label": "b", "size": 2, "centroid": [1.0, 0.01], "samples": ["y"]},
        ]

        async def fake_llm(messages, tools, stream=False, user="cluster", policy=None, json_schema=None):
            return {"choices": [{"message": {"content": '{"merges": [[1,2]]}'}}]}

        with patch.object(self.server, "call_llm_async", fake_llm):
            resp = self.client.post("/api/v1/semantic/recluster", json={"clusters": clusters})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("merges"), [[1, 2]])

    def test_rename(self):
        clusters = [
            {"id": 2, "label": "old", "size": 2, "centroid": [1.0, 0.0], "samples": ["x"]}
        ]

        async def fake_llm(messages, tools, stream=False, user="cluster", policy=None, json_schema=None):
            return {"choices": [{"message": {"content": '{"renames": {"2": "energy"}}'}}]}

        with patch.object(self.server, "call_llm_async", fake_llm):
            resp = self.client.post("/api/v1/semantic/recluster", json={"clusters": clusters})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("renames", {}).get("2"), "energy")

    def test_duplicate_label_error(self):
        clusters = [
            {"id": 1, "label": "a", "size": 1, "centroid": [1.0, 0.0], "samples": ["x"]},
            {"id": 2, "label": "b", "size": 1, "centroid": [1.0, 0.01], "samples": ["y"]},
        ]

        async def fake_llm(messages, tools, stream=False, user="cluster", policy=None, json_schema=None):
            return {"choices": [{"message": {"content": '{"renames": {"1": "dup", "2": "dup"}}'}}]}

        with patch.object(self.server, "call_llm_async", fake_llm):
            resp = self.client.post("/api/v1/semantic/recluster", json={"clusters": clusters})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/semantic/recluster")

    def test_apply_endpoint(self):
        plan = {"merges": [[1, 2]], "splits": [], "renames": {"1": "x"}}
        resp = self.client.put("/api/v1/semantic/clusters/apply", json=plan)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")


if __name__ == "__main__":
    unittest.main()
