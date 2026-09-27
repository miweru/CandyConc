"""Invalid tool arguments must surface as an error tool message.

Real contract: argument validation lives in the real dispatcher
(``dispatcher.py:28`` ``async def dispatch(call, token=None)`` -> jsonschema
``json_validate`` -> ``ValueError("Invalid arguments: ...")``); the
orchestrator catches the exception and wraps it into a ``status: error`` tool
message.  The dispatcher's MCP transport (``call_tool``) is mocked out, so a
validation failure is the only error source.
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import make_orchestrator, real_dispatcher

_dispatcher = real_dispatcher()

RUN_CQLF_TOOL = {
    "type": "function",
    "function": {
        "name": "validated_query",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "ctx": {"type": "integer"}},
            "required": ["query"],
        },
    },
}


def _call_llm(messages, tools, **kwargs):
    if not any(m.get("role") == "tool" for m in messages):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "1",
                                "type": "function",
                                "function": {
                                    "name": "validated_query",
                                    "arguments": json.dumps({"query": "fox", "ctx": "bad"}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    return {"choices": [{"message": {"content": "done"}}]}


class TestToolValidation(unittest.TestCase):
    def test_invalid_arguments(self):
        schema_map = {
            "validated_query": RUN_CQLF_TOOL["function"]["parameters"],
        }
        call_tool = AsyncMock(return_value={"status": "ok"})
        with patch.object(_dispatcher, "get_schema_map", return_value=schema_map), patch.object(
            _dispatcher, "call_tool", call_tool
        ):
            orch = make_orchestrator([RUN_CQLF_TOOL], _call_llm, _dispatcher.dispatch)
            result = orch.run("hi")

        # Der Rumpf exakt, ohne den Experimentprotokoll-Anhang.
        # Seit dem 2026-09-01 nennt das Protokoll gescheiterte Aufrufe MIT
        # Grund. Genau darum geht es in dieser Probe: das Werkzeug ist
        # gescheitert, und das steht jetzt in der Antwort.
        self.assertEqual(result.split("\n\n### ")[0], "done")
        self.assertIn("gescheitert", result)
        tool_msgs = [m for m in orch.messages if m.get("role") == "tool"]
        tool_msg = json.loads(tool_msgs[-1]["content"])
        self.assertEqual(tool_msg["status"], "error")
        self.assertIn("Invalid arguments", tool_msg["message"])
        # validation failed, so the MCP transport must never have been hit
        call_tool.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
