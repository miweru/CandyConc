"""C2 fix: client-supplied ``budget``/``acl`` chat overrides are admin-only.

``/chat`` and ``/chat/stream`` previously applied ``budget`` and ``acl`` from
the request body to the caller's OWN policy, so any user-role caller could
lift their own ACL/budget restrictions per request. The fields are now ignored
unless the caller's token resolves to the ``admin`` role.
"""

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from candyconc.services.backend import app, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestChatPolicyOverrideHardening(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        self.admin_token = self.client.post(
            "/api/v1/login", json={"username": "alice", "password": "alice"}
        ).json()["token"]
        self.user_name = server.auth.username_for_token(self.user_token)
        self.admin_name = server.auth.username_for_token(self.admin_token)
        self._reset_policy_state()

    def tearDown(self):
        self._reset_policy_state()

    def _reset_policy_state(self):
        server.POLICY_BUDGETS.clear()
        server.POLICY_BUDGETS["default"] = 1000
        server.POLICY_ACLS.clear()

    @staticmethod
    def _payload():
        return {
            "messages": [{"role": "user", "content": "hello"}],
            "budget": 7,
            "acl": ["dummy_tool"],
        }

    def _captured_policy(self, mock_orch):
        return mock_orch.call_args.kwargs["policy"]

    def test_chat_ignores_override_for_user_role(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "ok"
            resp = self.client.post(
                "/api/v1/chat",
                params={"token": self.user_token},
                json=self._payload(),
            )
        self.assertEqual(resp.status_code, 200)
        policy = self._captured_policy(mock_orch)
        self.assertEqual(policy.token_budget, 1000)
        self.assertIsNone(policy.acl)

    def test_chat_honors_override_for_admin_role(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "ok"
            resp = self.client.post(
                "/api/v1/chat",
                params={"token": self.admin_token},
                json=self._payload(),
            )
        self.assertEqual(resp.status_code, 200)
        policy = self._captured_policy(mock_orch)
        self.assertEqual(policy.token_budget, 7)
        self.assertEqual(policy.acl, {self.admin_name: ["dummy_tool"]})

    def _stream(self, token):
        with self.client.stream(
            "POST",
            "/api/v1/chat/stream",
            params={"token": token},
            json=self._payload(),
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]
        return resp, lines

    def test_chat_stream_ignores_override_for_user_role(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "stream-ok"
            resp, lines = self._stream(self.user_token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(lines[-1], "data: [DONE]")
        policy = self._captured_policy(mock_orch)
        self.assertEqual(policy.token_budget, 1000)
        self.assertIsNone(policy.acl)

    def test_chat_stream_honors_override_for_admin_role(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "stream-ok"
            resp, lines = self._stream(self.admin_token)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(lines[-1], "data: [DONE]")
        policy = self._captured_policy(mock_orch)
        self.assertEqual(policy.token_budget, 7)
        self.assertEqual(policy.acl, {self.admin_name: ["dummy_tool"]})


if __name__ == "__main__":
    unittest.main()
