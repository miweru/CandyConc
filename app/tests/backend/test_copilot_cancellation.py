"""The stop endpoint is owner-scoped and makes a Copilot session terminal."""

from __future__ import annotations

import types
import uuid
import unittest

import httpx
from fastapi.testclient import TestClient

from candyconc.services.backend import app, server


_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _CancelableOrchestrator:
    def __init__(self, session_id: str):
        self.session = types.SimpleNamespace(session_id=session_id)
        self.cancelled = False

    def request_cancel(self) -> None:
        self.cancelled = True


class TestCopilotCancellation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.alice_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        self.bob_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        self.alice = server.auth.username_for_token(self.alice_token)

    def test_only_owner_may_cancel_by_client_turn_id(self):
        session_id = f"cancel-{uuid.uuid4().hex}"
        turn_id = uuid.uuid4().hex
        orch = _CancelableOrchestrator(session_id)
        entry = server._register_active_orchestrator(
            session_id,
            orch,
            self.alice,
            turn_id=turn_id,
        )
        try:
            denied = self.client.post(
                "/api/v1/copilot/cancel",
                params={"token": self.bob_token},
                json={"turnId": turn_id},
            )
            self.assertEqual(denied.status_code, 403)
            self.assertFalse(entry.cancel_requested.is_set())
            self.assertFalse(orch.cancelled)

            allowed = self.client.post(
                "/api/v1/copilot/cancel",
                params={"token": self.alice_token},
                json={"turnId": turn_id},
            )
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.json()["status"], "cancellation_requested")
            self.assertTrue(entry.cancel_requested.is_set())
            self.assertTrue(orch.cancelled)

            continuation = self.client.post(
                "/api/v1/copilot/continue",
                params={"token": self.alice_token},
                json={"sessionId": session_id},
            )
            self.assertEqual(continuation.status_code, 409)
            self.assertIn("abgebrochen", continuation.json()["detail"])
        finally:
            with server._ACTIVE_ORCH_LOCK:
                server._active_orchestrators.pop(session_id, None)


if __name__ == "__main__":
    unittest.main()
