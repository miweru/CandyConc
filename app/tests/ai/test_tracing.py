import sys
import types
import unittest
from unittest.mock import patch

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai import _real_copilot as _rc
from tests.ai._real_copilot import make_orchestrator


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
                                "function": {"name": "dummy", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    return {"choices": [{"message": {"content": "done"}}]}


def _dispatch(call, token=None):
    # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
    return {"status": "ok"}


class TestTracing(unittest.TestCase):
    def test_spans(self):
        spans = []

        class DummySpan:
            def __init__(self, name, attributes=None):
                self.name = name
                self.attributes = dict(attributes or {})
                self.ended = False
                spans.append(self)

            def set_attribute(self, k, v):
                self.attributes[k] = v

            def end(self):
                self.ended = True

        class DummyTracer:
            def start_span(self, name, attributes=None):
                return DummySpan(name, attributes)

            def start_as_current_span(self, name, context=None):
                span = DummySpan(name)

                class CM:
                    def __enter__(self):
                        return span

                    def __exit__(self, exc_type, exc, tb):
                        span.end()

                return CM()

        dummy_metrics = types.SimpleNamespace(
            set_meter_provider=lambda provider: None,
            get_meter=lambda service: types.SimpleNamespace(
                create_counter=lambda name: types.SimpleNamespace(add=lambda v, attributes=None: None),
                create_histogram=lambda name: types.SimpleNamespace(record=lambda v, attributes=None: None),
            ),
        )
        dummy_export_metrics = types.SimpleNamespace(
            ConsoleMetricExporter=lambda: None,
            PeriodicExportingMetricReader=lambda exporter: None,
        )
        dummy_sdk_metrics = types.SimpleNamespace(MeterProvider=lambda metric_readers: None)

        dummy_trace = types.SimpleNamespace(
            get_tracer=lambda svc: DummyTracer(),
            set_tracer_provider=lambda provider: None,
            set_span_in_context=lambda span: None,
        )
        dummy_sdk_trace = types.SimpleNamespace(
            TracerProvider=lambda: types.SimpleNamespace(add_span_processor=lambda proc: None)
        )
        dummy_trace_export = types.SimpleNamespace(
            SimpleSpanProcessor=lambda exporter: None, ConsoleSpanExporter=lambda: None
        )

        otel_modules = {
            "opentelemetry": types.SimpleNamespace(metrics=dummy_metrics, trace=dummy_trace),
            "opentelemetry.trace": dummy_trace,
            "opentelemetry.sdk.metrics": dummy_sdk_metrics,
            "opentelemetry.sdk.metrics.export": dummy_export_metrics,
            "opentelemetry.sdk.trace": dummy_sdk_trace,
            "opentelemetry.sdk.trace.export": dummy_trace_export,
        }

        # Observability reads the OTEL switch from APP_CONFIG, not the
        # environment, at construction time (observability.py:24-26).
        with patch.dict(sys.modules, otel_modules), patch.object(
            _rc.observability,
            "APP_CONFIG",
            types.SimpleNamespace(CANDYCONC_ENABLE_OTEL=True),
        ):
            obs = _rc.Observability(service_name="test")
            self.assertTrue(obs.enable_otel)
            orch = make_orchestrator(
                [{"type": "function", "function": {"name": "dummy", "parameters": {"type": "object"}}}],
                _call_llm,
                _dispatch,
                observability=obs,
            )
            orch.session.session_id = "s"
            result = orch.run("hi")

        self.assertEqual(result, "done")
        names = [s.name for s in spans]
        self.assertIn("session", names)
        self.assertIn("llm", names)


if __name__ == "__main__":
    unittest.main()
