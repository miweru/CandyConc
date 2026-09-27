import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class TestDryRun(unittest.TestCase):
    """DRY_RUN must suppress project persistence.

    server.DRY_RUN is an import-time snapshot of APP_CONFIG.DRY_RUN
    (src/candyconc/services/backend/server.py:987) and _PROJECTS_DIR is an
    import-time get_config snapshot (server.py:4345); config.get reads the
    APP_CONFIG pydantic snapshot, not live os.environ. The old test set
    os.environ["DRY_RUN"]="1" + importlib.reload(server), which silently ran
    with DRY_RUN=False and WROTE config/projects/dryrun.json into the repo —
    the stale artifact that then broke later runs with 400 "Project exists".
    Patch the module globals directly and restore them afterwards.
    """

    def setUp(self):
        import candyconc.services.backend.server as server

        self.server = server
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dry_run = server.DRY_RUN
        self._old_projects_dir = server._PROJECTS_DIR
        self._old_project_users = {
            k: set(v) for k, v in server._PROJECT_USERS.items()
        }
        server.DRY_RUN = True
        server._PROJECTS_DIR = Path(self._tmp.name)
        server._PROJECT_USERS.pop("dryrun", None)
        self.client = TestClient(server.app)

    def tearDown(self):
        server = self.server
        server.DRY_RUN = self._old_dry_run
        server._PROJECTS_DIR = self._old_projects_dir
        server._PROJECT_USERS.clear()
        server._PROJECT_USERS.update(self._old_project_users)
        self._tmp.cleanup()

    def test_project_create_no_file(self):
        proj_path = self.server._PROJECTS_DIR / "dryrun.json"
        self.assertFalse(proj_path.exists())
        admin_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        resp = self.client.post(
            "/api/v1/projects/create",
            json={"name": "dryrun", "owner": "alice", "token": admin_token},
        )
        self.assertEqual(resp.json()["status"], "ok")
        self.assertFalse(proj_path.exists())

    def test_removed_corpus_upload_endpoint(self):
        resp = self.client.post("/api/v1/corpus/upload")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
