"""TD-2: ``Observability.span`` must be usable when OTEL is off.

Defect: ``orchestrator.py`` wraps the LLM call in ``with
self.observability.span(...) as span`` and calls ``span.set_attribute(...)``
unconditionally, but ``Observability.span`` used to yield ``None`` when
``enable_otel`` is False — so wiring a REAL ``Observability(enable_otel=
False)`` into the orchestrator crashed every LLM call with
``AttributeError: 'NoneType' object has no attribute 'set_attribute'``.
(Production was only masked because ``server._OBSERVABILITY`` is never
assigned.)

Fixed contract: with OTEL disabled, ``span`` yields an inert no-op span
object whose ``set_attribute`` / ``record_exception`` / ``add_event`` /
``set_status`` / ``end`` do nothing, fixing every call site at once.
"""

import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import Observability, make_orchestrator


def _call_llm(messages, tools, **kwargs):
    return {"choices": [{"message": {"content": "done"}}]}


def _dummy_dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "ok"}


class TestNoopSpanDirect(unittest.TestCase):
    def test_span_yields_usable_object_when_otel_off(self):
        obs = Observability(enable_otel=False)
        with obs.span("sess", "llm") as span:
            self.assertIsNotNone(span)
            # The orchestrator call-site contract:
            span.set_attribute("duration_ms", 1.0)
            # Common OTEL span surface, kept inert:
            span.record_exception(ValueError("boom"))
            span.add_event("evt")
            span.set_status("ok")
            span.end()
            self.assertFalse(span.is_recording())

    def test_record_and_export_unchanged(self):
        obs = Observability(enable_otel=False)
        obs.record("sess", "tool_x", tokens=3, duration_ms=2.0, status="ok")
        metrics = obs.export_metrics()
        self.assertEqual(metrics["tool_x.calls"], 1)
        self.assertEqual(metrics["tool_x.errors"], 0)


class TestOrchestratorWithRealObservability(unittest.TestCase):
    def test_llm_span_path_does_not_crash(self):
        # Plain real Observability — NOT the MetricsObservability shim that
        # used to paper over the None span.
        obs = Observability(enable_otel=False)
        orch = make_orchestrator([], _call_llm, _dummy_dispatch, observability=obs)
        result = orch.run("hi")
        self.assertEqual(result, "done")


if __name__ == "__main__":
    unittest.main()
