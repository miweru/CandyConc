import unittest
import importlib.util
import types
import sys
import os
from pathlib import Path
from unittest.mock import patch
import tempfile

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


class TestOutline(unittest.TestCase):
    def setUp(self):
        self._saved_modules = {k: sys.modules.get(k) for k in _TOUCHED_MODULES}
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CANDYCONC_PROJECTS_DIR"] = self.tmp.name
        self.server = _load_backend()
        self.client = TestClient(self.server.app)
        self.token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]

    def tearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        self.tmp.cleanup()
        os.environ.pop("CANDYCONC_PROJECTS_DIR", None)

    def test_export_md(self):
        clusters = [
            {"id": 1, "label": "a", "samples": ["x"]},
            {"id": 2, "label": "b", "samples": ["y"]},
            {"id": 3, "label": "c", "samples": ["z"]},
        ]
        resp = self.client.post(
            "/api/v1/semantic/outline", json={"clusters": clusters}
        )
        self.assertEqual(resp.status_code, 200)
        url = resp.json().get("url", "")
        # Contract (routes/semantic.py semantic_outline): the URL carries the
        # /api/v1 prefix of the download route (routes/exports.py) so the
        # link resolves as-is; the file is written to server._EXPORT_DIR.
        self.assertTrue(url.startswith("/api/v1/download/"), url)
        path = Path(self.server._EXPORT_DIR) / url.split("/")[-1]
        self.assertTrue(path.exists())

    def test_split_persist(self):
        clusters = [
            {
                "id": 1,
                "label": "x",
                "tokens": [1, 2, 3, 4],
                "centroid": [0.0, 0.0],
            }
        ]
        self.client.put(
            f"/api/v1/projects/default/clusters?token={self.token}", json=clusters
        )

        async def fake_llm(
            messages,
            tools,
            stream=False,
            user="cluster",
            policy=None,
            json_schema=None,
        ):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"splits":[{"id":1,"subsets":[[0,1],[2,3]]}],"merges":[],"renames":{}}'
                        }
                    }
                ]
            }

        with patch.object(self.server, "call_llm_async", fake_llm):
            plan = self.client.post(
                "/api/v1/semantic/recluster", json={"clusters": clusters}
            ).json()

        # The endpoint remaps LLM subset *positions* to the cluster's token
        # ids (routes/semantic.py: remap_split_idxs) — tokens [1,2,3,4] with
        # positions [[0,1],[2,3]] become [[1,2],[3,4]].
        self.assertEqual(plan.get("splits"), [{"id": 1, "subsets": [[1, 2], [3, 4]]}])
        # Current contract: applying splits is disabled because embedding
        # centroids are no longer persisted (server.apply_plan raises).
        with self.assertRaisesRegex(RuntimeError, "Cluster Splits sind deaktiviert"):
            self.server.apply_plan(clusters, plan)


if __name__ == "__main__":
    unittest.main()
