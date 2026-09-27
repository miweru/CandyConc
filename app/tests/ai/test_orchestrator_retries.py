import json
import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import MetricsObservability, make_orchestrator


def dummy_dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "ok"}


class TestOrchestratorRetries(unittest.TestCase):
    def test_llm_retry_success(self):
        attempts = {"n": 0}

        def failing_llm(messages, tools, **kwargs):
            if messages and str(messages[0].get("content", "")).startswith(
                "Ordne die folgende korpuslinguistische Nutzerfrage"
            ):
                # H9/C1 Router-Klassifikator (Stufe 2): 'frei' antworten,
                # ohne den Retry-Zaehler zu beruehren.
                return {"choices": [{"message": {"content": "frei"}}]}
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("llm boom")
            return {"choices": [{"message": {"content": "done"}}]}

        obs = MetricsObservability(enable_otel=False)
        orch = make_orchestrator(
            [],
            failing_llm,
            dummy_dispatch,
            observability=obs,
            llm_retries=2,
        )
        result = orch.run("hi")
        # Hier ist NICHTS gescheitert, der Wiederholungsversuch gelang.
        # Der Rumpfvergleich bleibt trotzdem, weil ein gelungener Lauf
        # sehr wohl ein Experimentprotokoll anhaengt.
        self.assertEqual(result.split("\n\n### ")[0], "done")
        self.assertEqual(attempts["n"], 3)
        metrics = obs.export_metrics()
        self.assertEqual(metrics.get("llm.errors"), 2)

    def test_tool_retry_limit(self):
        def call_llm(messages, tools, **kwargs):
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

        attempts = {"n": 0}

        def failing_dispatch(call, token=None):
            attempts["n"] += 1
            raise RuntimeError("boom")

        obs = MetricsObservability(enable_otel=False)
        orch = make_orchestrator(
            [
                {
                    "type": "function",
                    "function": {"name": "dummy", "parameters": {"type": "object"}},
                }
            ],
            call_llm,
            failing_dispatch,
            observability=obs,
            tool_retries=1,
        )
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
        self.assertEqual(attempts["n"], 2)
        # Fixed contract (TD-2): exactly ONE record per dispatch — the final
        # post-loop status record in orchestrator _dispatch.  The former
        # per-attempt in-loop records multi-counted failures (2 attempts used
        # to yield 3 errors).
        metrics = obs.export_metrics()
        self.assertEqual(metrics.get("dummy.errors"), 1)
        self.assertEqual(metrics.get("dummy.calls"), 1)


if __name__ == "__main__":
    unittest.main()
