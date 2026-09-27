import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from candyconc.services.backend import app, auth

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestChatAuthentication(unittest.TestCase):
    def setUp(self):
        # The 401 contract only exists when RBAC is enforced: with RBAC
        # disabled (default local-dev mode) ``require_role`` is a no-op and
        # the chat endpoints are intentionally open. Pin RBAC on so this test
        # is order-independent instead of depending on an earlier test having
        # left RBAC enabled.
        rbac_patch = mock.patch.object(auth, "RBAC_ENABLED", True)
        rbac_patch.start()
        self.addCleanup(rbac_patch.stop)
        self.client = TestClient(app)

    def test_chat_requires_auth(self):
        payload = {"messages": [{"role": "user", "content": "hi"}]}
        resp = self.client.post("/api/v1/chat", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/chat")

    def test_chat_stream_requires_auth(self):
        payload = {"messages": [{"role": "user", "content": "hi"}]}
        resp = self.client.post("/api/v1/chat/stream", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.headers["content-type"], "application/problem+json")
        self.assertEqual(resp.json().get("instance"), "/api/v1/chat/stream")


if __name__ == "__main__":
    unittest.main()
