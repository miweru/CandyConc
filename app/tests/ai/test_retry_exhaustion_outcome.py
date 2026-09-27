"""A2: a tool that exhausts its retry budget must be recorded as an ERROR.

Defect (HIGH-triage A2, corroborated twice): in ``orchestrator.py``
``_dispatch`` the retry loop leaves ``out`` as the tool's ``{"status":
"retry"}`` dict when every attempt asks for a retry.  ``ok`` only flips on
``status == "error"``, so the exhausted call was recorded as a SUCCESS and the
retry payload was fed downstream (session tool message -> LLM/grounding
evidence, ``_recent_tool_results`` -> runtime state).

Fixed contract: after the retry loop a lingering ``retry`` status is coerced
to ``{"status": "error", "message": "retry budget exhausted (<n> attempts)",
"retry_payload": <original>}``; the outcome is recorded with ``ok=False`` and
observability counts one error.
"""

import json
import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import MetricsObservability, make_orchestrator

# Non-grounding tool name: grounding-trigger tools force the AnalysisContract
# preflight which fail-closes without a json_schema-capable LLM fake (see
# test_error_propagation.py).
TOOLS = [
    {
        "type": "function",
        "function": {"name": "lookup_tool", "parameters": {"type": "object"}},
    }
]


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
                                    "name": "lookup_tool",
                                    "arguments": json.dumps({"query": "fox"}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    return {"choices": [{"message": {"content": "done"}}]}


def _always_retry_dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "retry", "delay": 0, "hint": "busy"}


class TestRetryExhaustionOutcome(unittest.TestCase):
    def _run(self, tool_retries: int):
        obs = MetricsObservability(enable_otel=False)
        orch = make_orchestrator(
            TOOLS,
            _call_llm,
            _always_retry_dispatch,
            observability=obs,
            tool_retries=tool_retries,
        )
        result = orch.run("hi")
        # Der Rumpf exakt, ohne den Experimentprotokoll-Anhang.
        # Seit dem 2026-09-01 nennt das Protokoll gescheiterte Aufrufe MIT
        # Grund. Genau darum geht es in dieser Probe: das Werkzeug ist
        # gescheitert, und das steht jetzt in der Antwort.
        self.assertEqual(result.split("\n\n### ")[0], "done")
        self.assertIn("gescheitert", result)
        return orch, obs

    def test_default_retries_zero_records_error(self):
        orch, obs = self._run(tool_retries=0)

        tool_msgs = [m for m in orch.messages if m.get("role") == "tool"]
        self.assertTrue(tool_msgs)
        tool_msg = json.loads(tool_msgs[-1]["content"])
        # The LLM/grounding-facing record must NOT be the raw retry dict.
        self.assertEqual(tool_msg["status"], "error")
        self.assertIn("retry budget exhausted (1 attempts)", tool_msg["message"])
        # Original payload preserved for diagnostics.
        self.assertEqual(tool_msg["retry_payload"]["status"], "retry")
        self.assertEqual(tool_msg["retry_payload"]["hint"], "busy")

        # Outcome recorder (feeds runtime state / recovery hints): not ok.
        outcomes = [e for e in orch._recent_tool_results if e["tool"] == "lookup_tool"]
        self.assertTrue(outcomes)
        self.assertFalse(outcomes[-1]["ok"])
        # Failure bookkeeping engaged (was skipped when recorded as success).
        self.assertTrue(orch._failed_tool_attempts)

        metrics = obs.export_metrics()
        self.assertEqual(metrics["lookup_tool.errors"], 1)

    def test_exhausted_budget_with_retries_records_error(self):
        orch, obs = self._run(tool_retries=2)

        tool_msg = json.loads(
            [m for m in orch.messages if m.get("role") == "tool"][-1]["content"]
        )
        self.assertEqual(tool_msg["status"], "error")
        self.assertIn("retry budget exhausted (3 attempts)", tool_msg["message"])

        outcomes = [e for e in orch._recent_tool_results if e["tool"] == "lookup_tool"]
        self.assertFalse(outcomes[-1]["ok"])
        # Exactly one final record for the dispatch (no per-attempt double count).
        metrics = obs.export_metrics()
        self.assertEqual(metrics["lookup_tool.errors"], 1)
        self.assertEqual(metrics["lookup_tool.calls"], 1)


if __name__ == "__main__":
    unittest.main()
