from __future__ import annotations

import unittest
from unittest.mock import patch

from candyconc.services import mcp_client


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"status": "success"}


class TestMcpClientAuth(unittest.IsolatedAsyncioTestCase):
    async def test_token_is_sent_as_authorization_header_not_json_body(self):
        recorded: dict[str, object] = {}

        class _Client:
            def __init__(self, *, timeout):
                recorded["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, *, json, headers=None):
                recorded["url"] = url
                recorded["json"] = json
                recorded["headers"] = headers
                return _Response()

        with patch.object(mcp_client.APP_CONFIG, "CANDYCONC_MCP_URL", "http://mcp"):
            with patch.object(mcp_client.httpx, "AsyncClient", _Client):
                result = await mcp_client.call_tool(
                    "run_cqlf_query",
                    {"query": "Hase"},
                    token="usertok",
                )

        self.assertEqual(result, {"status": "success"})
        self.assertEqual(recorded["url"], "http://mcp/call")
        self.assertEqual(
            recorded["json"],
            {"name": "run_cqlf_query", "arguments": {"query": "Hase"}},
        )
        self.assertEqual(recorded["headers"], {"Authorization": "Bearer usertok"})


if __name__ == "__main__":
    unittest.main()
