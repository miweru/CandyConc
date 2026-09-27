"""K1 In-Process-Dispatch: Fehler-Paritaet gegen die bisherige HTTP-Semantik.

Der Dispatcher ruft die Gate-Kette von ``mcp_server.execute_tool_call``
in-process auf. Diese Tests pinnen, dass Policy-Deny, Schema-Fehler und
unbekannte Tools EXAKT die bisherige Transport-Fehlersemantik behalten:
der In-Process-Fehlertext ist byte-identisch zu ``"MCP Fehler: " + <HTTP-
problem+json-Body>``, wobei der HTTP-Body von einer echten FastAPI-App mit
den Produktions-Exception-Handlern erzeugt wird (POST /mcp/call).
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candyconc.entrypoints.errors import register_exception_handlers
from candyconc.services import mcp_server
from candyconc.services.backend.policy_state import POLICY_ACLS
from tests.ai._real_copilot import real_dispatcher

_dispatcher = real_dispatcher()

_SCHEMA_MAP = {
    "query_count": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
}


def _make_http_app() -> TestClient:
    app = FastAPI()
    app.include_router(mcp_server.router, prefix="/mcp")
    register_exception_handlers(app)
    return TestClient(app, raise_server_exceptions=False)


def _call(name: str, arguments: dict) -> dict:
    return {
        "id": "1",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _in_process_error_text(name: str, arguments: dict) -> str:
    with patch.object(_dispatcher, "get_schema_map", return_value=_SCHEMA_MAP), patch.object(
        _dispatcher, "_remote_mcp_url", return_value=None
    ):
        try:
            asyncio.run(_dispatcher.dispatch(_call(name, arguments)))
        except RuntimeError as exc:
            return str(exc)
    raise AssertionError("dispatch haette fehlschlagen muessen")


class TestInProcessDispatchParity(unittest.TestCase):
    def test_policy_deny_matches_http_semantics(self):
        client = _make_http_app()
        POLICY_ACLS["parity_user"] = ["some_other_tool"]
        try:
            with patch.object(
                mcp_server.auth, "username_for_token", return_value="parity_user"
            ):
                resp = client.post(
                    "/mcp/call",
                    json={"name": "query_count", "arguments": {"query": "und"}},
                )
                self.assertEqual(resp.status_code, 403)
                http_body = resp.text
                in_process = _in_process_error_text(
                    "query_count", {"query": "und"}
                )
        finally:
            POLICY_ACLS.pop("parity_user", None)
        self.assertEqual(in_process, f"MCP Fehler: {http_body}")
        self.assertIn("Permission denied", in_process)

    def test_unknown_tool_error_text_is_unchanged(self):
        # Unbekannte Tools werden VOR jedem Transport im Dispatcher als
        # model-sichtbare Fehlerhuelle beantwortet: identisch fuer beide Wege.
        with patch.object(
            _dispatcher, "get_schema_map", return_value=_SCHEMA_MAP
        ), patch.object(_dispatcher, "_remote_mcp_url", return_value=None):
            res = asyncio.run(_dispatcher.dispatch(_call("nope", {})))
        self.assertEqual(res["status"], "error")
        self.assertEqual(
            res["message"],
            "Unbekanntes Tool: nope. Verfügbar: query_count",
        )

    def test_unknown_tool_beyond_dispatcher_matches_http_404(self):
        # Kennt der Dispatcher das Tool (Schema vorhanden), der Server aber
        # nicht, muss der 404-Fehlertext dem HTTP-Weg entsprechen.
        client = _make_http_app()
        schema_map = {
            "ghost_tool": {"type": "object", "properties": {}, "required": []}
        }
        resp = client.post("/mcp/call", json={"name": "ghost_tool", "arguments": {}})
        self.assertEqual(resp.status_code, 404)
        http_body = resp.text
        with patch.object(
            _dispatcher, "get_schema_map", return_value=schema_map
        ), patch.object(_dispatcher, "_remote_mcp_url", return_value=None):
            try:
                asyncio.run(_dispatcher.dispatch(_call("ghost_tool", {})))
                raise AssertionError("dispatch haette fehlschlagen muessen")
            except RuntimeError as exc:
                in_process = str(exc)
        self.assertEqual(in_process, f"MCP Fehler: {http_body}")
        self.assertIn("Unknown tool ghost_tool", in_process)

    def test_schema_error_stray_argument_matches_http_400(self):
        # Der Streuner-Arg passiert die Roh-Schema-Validierung des
        # Dispatchers und muss vom additionalProperties-Gate des Servers mit
        # exakt der bisherigen 400-Semantik abgewiesen werden. Dafuer wird
        # ein Tool mit Server-Schema simuliert.
        client = _make_http_app()

        def _tables():
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "query_count",
                        "parameters": _SCHEMA_MAP["query_count"],
                    },
                }
            ]
            return tools, dict(_SCHEMA_MAP), {
                "funcs": {"query_count": lambda **kw: {"status": "success"}},
                "responses": {"query_count": None},
                "runtime": {
                    "query_count": {"read_only": True, "concurrency_safe": True}
                },
            }

        bindings = mcp_server.product_tool_bindings_by_name(visible_only=True)
        if "query_count" not in bindings:
            self.skipTest(
                "query_count ist in diesem Test-Env nicht ProductOperation-"
                "gebunden; Paritaet wird ueber den Policy-Deny-Fall gepinnt."
            )
        with patch.object(mcp_server, "_tool_tables", _tables), patch.object(
            mcp_server, "_enforce_corpus_feature_gates", lambda *a, **k: None
        ):
            resp = client.post(
                "/mcp/call",
                json={
                    "name": "query_count",
                    "arguments": {"query": "und", "bogus": 1},
                },
            )
            self.assertEqual(resp.status_code, 400)
            http_body = resp.text
            in_process = _in_process_error_text(
                "query_count", {"query": "und", "bogus": 1}
            )
        self.assertEqual(in_process, f"MCP Fehler: {http_body}")
        self.assertIn("Invalid arguments", in_process)


if __name__ == "__main__":
    unittest.main()
