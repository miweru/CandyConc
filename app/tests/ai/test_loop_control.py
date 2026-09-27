import unittest
import json
from unittest.mock import patch

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai import _real_copilot as _rc
from tests.ai._real_copilot import MetricsObservability, State, make_orchestrator


def dummy_dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "ok"}


TOOLS = [
    {"type": "function", "function": {"name": "dummy", "parameters": {"type": "object"}}}
]


def call_loop(messages, tools_, **kwargs):
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


class TestLoopControl(unittest.TestCase):
    def test_finish_reason_stop(self):
        def call_stop(messages, tools, **kwargs):
            return {"choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}

        orch = make_orchestrator([], call_stop, dummy_dispatch)
        result = orch.run("hi")
        self.assertEqual(result, "done")
        self.assertEqual(orch.state, State.FINISHED)
        self.assertEqual(len(orch.messages), 2)  # user + assistant

    def test_max_steps(self):
        # H5, Fix 5: exhausting max_steps finalizes gracefully, never raising
        # HTTPException(409). In free mode (no tool_analysis contract) the
        # collected tool evidence is synthesised into a deterministic interim
        # digest instead of the former empty non-answer.
        orch = make_orchestrator(TOOLS, call_loop, dummy_dispatch)
        result = orch.run("hi", max_steps=3)
        self.assertIn("Zwischenstand", result)
        self.assertIn("dummy()", result)
        self.assertEqual(orch.state, State.FINISHED)
        # final assistant message records the finalized digest
        self.assertEqual(orch.messages[-1]["role"], "assistant")
        self.assertEqual(orch.messages[-1]["content"], result)

    def test_max_time(self):
        class Counter:
            def __init__(self) -> None:
                self.t = 0.0

            def __call__(self) -> float:
                self.t += 0.1
                return self.t

        obs = MetricsObservability(enable_otel=False)
        with patch.object(_rc.orchestrator.time, "perf_counter", side_effect=Counter()):
            orch = make_orchestrator(TOOLS, call_loop, dummy_dispatch, observability=obs)
            result = orch.run("hi", max_steps=5, max_time=0.25)

        # H5, Fix 5: the timeout branch appends a timeout tool message, records
        # the metric, then finalizes from the collected evidence. In free mode
        # that is now a deterministic interim digest, not the former empty
        # non-answer (orchestrator.py timeout path; see
        # test_orchestrator_timeout_evidence for the grounded path).
        self.assertIn("Zwischenstand", result)
        self.assertEqual(orch.state, State.FINISHED)
        tool_msgs = [
            json.loads(m["content"])
            for m in orch.messages
            if m.get("role") == "tool" and m.get("tool_call_id") == "timeout"
        ]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["status"], "error")
        self.assertIn("timeout", tool_msgs[0]["message"])
        metrics = obs.export_metrics()
        self.assertEqual(metrics["timeout.errors"], 1)


if __name__ == "__main__":
    unittest.main()
