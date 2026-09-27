import json
import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import PolicyEngine, make_orchestrator


def dummy_call(messages, tools, **kwargs):
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
    return {"status": "ok"}


class TestPolicyEngine(unittest.TestCase):
    def test_budget_exhaustion(self):
        policy = PolicyEngine(token_budget=0, acl={"user": ["dummy"]})
        orch = make_orchestrator(
            [
                {
                    "type": "function",
                    "function": {"name": "dummy", "parameters": {"type": "object"}},
                }
            ],
            dummy_call,
            dummy_dispatch,
            policy=policy,
        )
        orch.run("hi", role="user")
        tool_msgs = [m for m in orch.messages if m.get("role") == "tool"]
        self.assertTrue(tool_msgs, "blocked tool call must leave a tool message")
        blocked = json.loads(tool_msgs[-1]["content"])
        self.assertEqual(blocked["status"], "error")
        self.assertIn("budget", json.dumps(blocked).lower())

    def test_acl(self):
        policy = PolicyEngine(token_budget=5, acl={"user": ["dummy"]})
        res = policy.check("user", "forbidden", 1)
        self.assertEqual(res["status"], "error")
        self.assertIn("Permission", res["message"])


if __name__ == "__main__":
    unittest.main()
