import json
import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import MetricsObservability, make_orchestrator

# A non-grounding tool name: grounding-trigger tools (analysis_grounding.py:
# GROUNDING_TRIGGER_TOOLS) force the AnalysisContract preflight, which
# fail-closes without a json_schema-capable LLM fake. Error propagation is
# tool-name agnostic, so a neutral name keeps this test focused.
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


class TestErrorPropagation(unittest.TestCase):
    def test_orchestrator_tool_error(self):
        obs = MetricsObservability(enable_otel=False)

        def error_dispatch(call, token=None):
            # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
            return {"status": "error", "message": "boom"}

        orch = make_orchestrator(TOOLS, _call_llm, error_dispatch, observability=obs)
        result = orch.run("hi")
        # Der Antwortrumpf, ohne den Experimentprotokoll-Anhang. Seit dem
        # 2026-09-01 nennt das Protokoll gescheiterte Aufrufe MIT Grund.
        # Vorher fielen sie stumm heraus, und live standen deshalb vier
        # Zeilen "Suche -> ohne Ergebnis" in einer Antwort, zwei davon die
        # Abfragen, um die es der Nutzerin ging.
        self.assertEqual(result.split("\n\n### ")[0], "done")
        # Und der Fehler steht wirklich da, mit seinem Grund.
        self.assertIn("### Experimente", result)
        self.assertIn("gescheitert", result)
        self.assertIn("boom", result)
        tool_msgs = [m for m in orch.messages if m.get("role") == "tool"]
        tool_msg = json.loads(tool_msgs[-1]["content"])
        self.assertEqual(tool_msg["status"], "error")
        self.assertIn("boom", tool_msg["message"])
        metrics = obs.export_metrics()
        self.assertEqual(metrics["lookup_tool.errors"], 1)

    def test_orchestrator_exception_error(self):
        obs = MetricsObservability(enable_otel=False)

        def raising_dispatch(call, token=None):
            raise ValueError("kaboom")

        orch = make_orchestrator(TOOLS, _call_llm, raising_dispatch, observability=obs)
        result = orch.run("hi")
        self.assertEqual(result.split("\n\n### ")[0], "done")
        self.assertIn("gescheitert", result)
        self.assertIn("kaboom", result)
        tool_msgs = [m for m in orch.messages if m.get("role") == "tool"]
        tool_msg = json.loads(tool_msgs[-1]["content"])
        self.assertEqual(tool_msg["status"], "error")
        self.assertIn("kaboom", tool_msg["message"])
        # Fixed contract (TD-2): a raising tool is recorded exactly ONCE, by
        # the post-loop ``record(..., status=out["status"])`` in
        # ``orchestrator.py _dispatch``.  The former in-exception-handler
        # ``record(..., status="error")`` double-counted every failure.
        metrics = obs.export_metrics()
        self.assertEqual(metrics["lookup_tool.errors"], 1)
        self.assertEqual(metrics["lookup_tool.calls"], 1)


if __name__ == "__main__":
    unittest.main()
