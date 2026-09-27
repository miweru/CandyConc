import os
import unittest
from unittest.mock import patch

import candyconc.services.llm_client as llm_client


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("error")


class TestPayloadContainsTools(unittest.IsolatedAsyncioTestCase):
    async def test_payload_contains_tools(self):
        sent_payloads = []
        fake_tools = [
            {
                "type": "function",
                "function": {
                    "name": "frequency_list",
                    "description": "Build a frequency list",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        async def fake_post(self, url, json, timeout, headers=None, **kwargs):
            # llm_client passes headers= (src/candyconc/services/llm_client.py)
            sent_payloads.append(dict(json))
            return FakeResponse({"choices": []})

        with patch.dict(os.environ, {"COPILOT_ENDPOINT": "http://test"}), patch.object(
            llm_client.APP_CONFIG,
            "COPILOT_ENDPOINT",
            "http://test/v1/chat/completions",
        ), patch.object(llm_client.APP_CONFIG, "COPILOT_MODEL", "test-model"), patch.object(
            llm_client,
            "get_tools",
            lambda: fake_tools,
        ):
            with patch("httpx.AsyncClient.post", fake_post):
                await llm_client.chat([{"role": "user", "content": "hi"}])

        self.assertTrue(sent_payloads, "No request was sent")
        self.assertIn("tools", sent_payloads[-1])
        self.assertEqual(sent_payloads[-1]["tools"], fake_tools)
