"""The chat routes hand the request language to the orchestrator.

It is the last fallback of the answer language when a question does not show
its own (a single word, a query). Before, the interface language decided
nothing: an API client with ``Accept-Language: en`` and no ``locale`` got
German harness texts.
"""

import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from candyconc.services.backend import app

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore

SEEN = []


class _RecordingOrch:
    def __init__(self, *args, **kwargs):
        self.session = kwargs.get("session")

    def run(self, question, role="user", *, principal=None, max_steps=20, max_time=None):
        SEEN.append(getattr(self, "interface_language", None))
        return "ok"


class TestChatRoutePassesInterfaceLanguage(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        self.client = TestClient(app)
        self.token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]

    def _ask(self, url, language):
        headers = {"Accept-Language": language}
        payload = {"messages": [{"role": "user", "content": "economy"}]}
        async def _endpoint_ready(*_args, **_kwargs):
            return None

        # The route checks the model endpoint before the turn. The test only
        # observes the language handed to the orchestrator, so the check must
        # not depend on a model server being reachable.
        with patch("candyconc.services.backend.server.ReActOrchestrator", _RecordingOrch), \
                patch("candyconc.services.backend.server.ensure_copilot_runtime_available", _endpoint_ready):
            if url.endswith("/stream"):
                with self.client.stream("POST", url, params={"token": self.token},
                                        json=payload, headers=headers) as resp:
                    list(resp.iter_lines())
            else:
                resp = self.client.post(url, params={"token": self.token}, json=payload,
                                        headers=headers)
        self.assertEqual(resp.status_code, 200)

    def test_the_stream_route_passes_english(self):
        self._ask("/api/v1/chat/stream", "en, de;q=0.5")
        self.assertEqual(SEEN, ["en"])

    def test_the_stream_route_passes_german(self):
        self._ask("/api/v1/chat/stream", "de, en;q=0.5")
        self.assertEqual(SEEN, ["de"])

    def test_the_plain_route_passes_english(self):
        self._ask("/api/v1/chat", "en")
        self.assertEqual(SEEN, ["en"])
