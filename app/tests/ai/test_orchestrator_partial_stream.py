import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import make_orchestrator

# A non-grounding tool name: grounding-trigger tools (analysis_grounding.py:
# GROUNDING_TRIGGER_TOOLS) force the AnalysisContract preflight, which
# fail-closes without a json_schema-capable LLM fake.
TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_tool", "parameters": {"type": "object"}},
    }
]


def _call_llm_partial(messages, tools, stream=False, **kwargs):
    if not any(m.get("role") == "tool" for m in messages):
        msg = {
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "lookup_tool", "arguments": "{}"},
                }
            ]
        }
        if stream:
            def gen():
                yield {"choices": [{"message": msg}]}
            return gen()
        return {"choices": [{"message": msg}]}
    if stream:
        def gen():
            yield {"choices": [{"delta": {"role": "assistant"}}]}
            yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}
        return gen()
    return {"choices": [{"message": {"content": "done"}}]}


def _dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "ok"}


class TestPartialStream(unittest.TestCase):
    def test_partial_chunks(self):
        orch = make_orchestrator(TOOLS, _call_llm_partial, _dispatch)
        result = orch.run("hi", stream=True)
        self.assertEqual(result, "done")
        self.assertEqual(orch.state.name, "FINISHED")


if __name__ == "__main__":
    unittest.main()
