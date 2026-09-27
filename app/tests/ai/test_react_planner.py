import json
import unittest

# Real-module contract; tests/conftest.py stubs the copilot package, so the
# real orchestrator is loaded via tests/ai/_real_copilot.py.
from tests.ai._real_copilot import State, make_orchestrator


def dummy_call(messages, tools, **kwargs):
    # Real contract: call_llm(messages, tools, user=..., policy=..., stream=...)
    if not any(m.get("role") == "tool" for m in messages):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "1",
                                "type": "function",
                                "function": {"name": "dummy", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    return {"choices": [{"message": {"content": "done"}}]}


def dummy_dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    assert call["function"]["name"] == "dummy"
    return {"status": "ok"}


class TestReActPlanner(unittest.TestCase):
    def test_orchestrator_loop(self):
        tools = [
            {
                "type": "function",
                "function": {"name": "dummy", "parameters": {"type": "object"}},
            }
        ]
        orch = make_orchestrator(tools, dummy_call, dummy_dispatch)
        result = orch.run("hello")
        self.assertEqual(result, "done")
        self.assertEqual(orch.state, State.FINISHED)
        # ensure tool result inserted
        self.assertEqual(orch.messages[1]["role"], "assistant")
        self.assertEqual(orch.messages[2]["role"], "tool")
        data = json.loads(orch.messages[2]["content"])
        self.assertEqual(data["status"], "ok")


if __name__ == "__main__":
    unittest.main()
