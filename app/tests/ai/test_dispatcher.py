"""Real dispatcher contract tests.

The real dispatcher (``src/candyconc/candyconc_copilot/dispatcher.py``) is
``async def dispatch(call, token=None)``: it validates the tool-call arguments
against the registry schema map and executes the call. K1: the DEFAULT
transport is in-process (``_call_tool_in_process`` -> the mcp_server gate
chain); the HTTP transport (``candyconc.services.mcp_client.call_tool``) is
used only when ``CANDYCONC_MCP_URL`` explicitly points at a remote. Both
transports are mocked here; the parity of the two paths is pinned in
``tests/ai/test_inprocess_dispatch_parity.py``.

Error contract (characterized, identical for both transports):
* invalid arguments  -> ``ValueError("Invalid arguments: ...")``
* failing tool       -> ``RuntimeError(str(exc))``
* unknown tool       -> model-visible error envelope
  ``{"status": "error", "message": "Unbekanntes Tool: <name>. Verfügbar: ..."}``
  instead of a bare ``KeyError`` (hallucinated tool names must not abort the
  orchestrator turn; the envelope lands in the session as a tool message so
  the model can self-correct).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tests.ai._real_copilot import real_dispatcher

_dispatcher = real_dispatcher()

_SCHEMA_MAP = {
    "run_cqlf_query": {
        "type": "object",
        "properties": {"query": {"type": "string"}, "ctx": {"type": "integer"}},
        "required": ["query"],
    }
}


def _call(name: str, arguments: str) -> dict:
    return {"id": "1", "type": "function", "function": {"name": name, "arguments": arguments}}


def _remote_pin():
    """Pin the legacy HTTP transport (explicit CANDYCONC_MCP_URL remote)."""
    return patch.object(
        _dispatcher, "_remote_mcp_url", return_value="http://remote:9/mcp"
    )


class TestDispatcherInProcessDefault(unittest.TestCase):
    """Without CANDYCONC_MCP_URL the dispatcher never opens an HTTP client."""

    def test_default_is_in_process(self):
        in_process = AsyncMock(return_value={"status": "success", "rows": []})
        http_tool = AsyncMock()
        with patch.object(
            _dispatcher, "get_schema_map", return_value=_SCHEMA_MAP
        ), patch.object(
            _dispatcher, "_call_tool_in_process", in_process
        ), patch.object(
            _dispatcher, "call_tool", http_tool
        ), patch.object(
            _dispatcher, "_remote_mcp_url", return_value=None
        ):
            res = asyncio.run(
                _dispatcher.dispatch(_call("run_cqlf_query", '{"query": "fox"}'))
            )
        self.assertEqual(res["status"], "success")
        in_process.assert_awaited_once()
        http_tool.assert_not_awaited()

    def test_explicit_remote_uses_http_transport(self):
        in_process = AsyncMock()
        http_tool = AsyncMock(return_value={"status": "success"})
        with patch.object(
            _dispatcher, "get_schema_map", return_value=_SCHEMA_MAP
        ), patch.object(
            _dispatcher, "_call_tool_in_process", in_process
        ), patch.object(
            _dispatcher, "call_tool", http_tool
        ), _remote_pin():
            res = asyncio.run(
                _dispatcher.dispatch(_call("run_cqlf_query", '{"query": "fox"}'))
            )
        self.assertEqual(res["status"], "success")
        http_tool.assert_awaited_once()
        in_process.assert_not_awaited()


class TestDispatcher(unittest.TestCase):
    def test_known_tool(self):
        call_tool = AsyncMock(return_value={"status": "success", "rows": [{"kw": "fox"}]})
        with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
            _dispatcher, "call_tool", call_tool
        ), _remote_pin():
            res = asyncio.run(_dispatcher.dispatch(_call("run_cqlf_query", '{"query": "fox"}')))
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["rows"])
        call_tool.assert_awaited_once()

    def test_unknown_tool(self):
        call_tool = AsyncMock()
        with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
            _dispatcher, "call_tool", call_tool
        ):
            res = asyncio.run(_dispatcher.dispatch(_call("nope", "{}")))
        self.assertEqual(res["status"], "error")
        self.assertIn("Unbekanntes Tool: nope", res["message"])
        # The error names the available tools so the model can self-correct.
        self.assertIn("run_cqlf_query", res["message"])
        call_tool.assert_not_awaited()

    def test_retired_cqp_tool_name_is_not_an_alias(self):
        call_tool = AsyncMock()
        with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
            _dispatcher, "call_tool", call_tool
        ):
            res = asyncio.run(_dispatcher.dispatch(_call("run_cqp_query", '{"query": "fox"}')))
        self.assertEqual(res["status"], "error")
        self.assertIn("Unbekanntes Tool: run_cqp_query", res["message"])
        self.assertIn("run_cqlf_query", res["message"])
        call_tool.assert_not_awaited()

    def test_invalid_arguments(self):
        call_tool = AsyncMock()
        with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
            _dispatcher, "call_tool", call_tool
        ):
            with self.assertRaisesRegex(ValueError, "Invalid arguments"):
                asyncio.run(
                    _dispatcher.dispatch(_call("run_cqlf_query", '{"query": "fox", "ctx": "bad"}'))
                )
        call_tool.assert_not_awaited()

    def test_tool_exception(self):
        call_tool = AsyncMock(side_effect=ValueError("boom"))
        with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
            _dispatcher, "call_tool", call_tool
        ), _remote_pin():
            with self.assertRaisesRegex(RuntimeError, "boom"):
                asyncio.run(_dispatcher.dispatch(_call("run_cqlf_query", '{"query": "fox"}')))


if __name__ == "__main__":
    unittest.main()
