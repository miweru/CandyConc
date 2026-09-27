import unittest

import importlib.util
from pathlib import Path
import importlib
import sys
import types
import httpx
from fastapi.testclient import TestClient

_OBS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "candyconc"
    / "candyconc_copilot"
    / "observability.py"
)
_spec = importlib.util.spec_from_file_location("cc_obs", _OBS_PATH)
_obs_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_obs_mod)  # type: ignore[arg-type]
Observability = _obs_mod.Observability

# NOTE: kein sys.modules.pop("candyconc.services.backend") hier! Der Pop ersetzte
# das Paket-Objekt und brach mock.patch-Attributketten in tests/backend, sobald
# beide Verzeichnisse in EINEM pytest-Prozess liefen (Cross-Dir-Pollution-Klasse).
# Der conftest
# stubbt nur Leaf-Module, nie das backend-Paket — normaler Import genügt.
server = importlib.import_module("candyconc.services.backend.server")
app = server.app


_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


class TestObservability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # httpx-Shim nur für die Laufzeit dieser Klasse, MIT Restore — der alte
        # import-time-Patch ohne Restore war ein latenter Cross-Suite-Hazard.
        httpx.Client.__init__ = _patched_init  # type: ignore[method-assign]

    @classmethod
    def tearDownClass(cls):
        httpx.Client.__init__ = _orig_client_init  # type: ignore[method-assign]

    def test_metrics_logging(self):
        obs = Observability(service_name="test", enable_otel=False)
        obs.record("s", "dummy", tokens=3, duration_ms=1.2)
        data = obs.export_metrics()
        self.assertEqual(data["dummy.calls"], 1)
        self.assertIn("dummy.tokens", data)
        self.assertIn("dummy.latency_ms_sum", data)
        self.assertIn("dummy.latency_ms_count", data)
        self.assertIn("dummy.latency_ms", data)

    def test_metrics_api(self):
        client = TestClient(app)
        server._OBSERVABILITY = Observability(service_name="test", enable_otel=False)
        server._OBSERVABILITY.record("s", "dummy")
        text = client.get("/api/v1/metrics").text
        self.assertIn("candyconc_dummy_calls", text)

    def test_env_var_enables_otel(self):
        # Real contract: Observability reads the switch from
        # APP_CONFIG.CANDYCONC_ENABLE_OTEL at construction time
        # (observability.py:24-26). APP_CONFIG resolves the env var when the
        # config module is imported, so mutating os.environ here is too late;
        # patch the config attribute the module actually consults.
        records = []

        class DummyMeter:
            def create_counter(self, name):
                def add(val, attributes=None):
                    records.append(("counter", val))

                return types.SimpleNamespace(add=add)

            def create_histogram(self, name):
                def record(val, attributes=None):
                    records.append(("hist", val))

                return types.SimpleNamespace(record=record)

        dummy_metrics = types.SimpleNamespace(
            set_meter_provider=lambda provider: None,
            get_meter=lambda service: DummyMeter(),
        )
        dummy_export = types.SimpleNamespace(
            ConsoleMetricExporter=lambda: None,
            PeriodicExportingMetricReader=lambda exporter: None,
        )
        dummy_sdk_metrics = types.SimpleNamespace(MeterProvider=lambda metric_readers: None)

        # The OTEL init path also wires tracing (observability.py:27-54), so
        # the trace modules must be stubbed as well or the import fails and
        # enable_otel silently stays False.
        dummy_trace = types.SimpleNamespace(
            get_tracer=lambda svc: None,
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
            "opentelemetry.sdk.metrics.export": dummy_export,
            "opentelemetry.sdk.trace": dummy_sdk_trace,
            "opentelemetry.sdk.trace.export": dummy_trace_export,
        }

        from unittest.mock import patch

        with patch.dict(sys.modules, otel_modules), patch.object(
            _obs_mod,
            "APP_CONFIG",
            types.SimpleNamespace(CANDYCONC_ENABLE_OTEL=True),
        ):
            obs = Observability(service_name="test")
            obs.record("s", "dummy")

        self.assertTrue(obs.enable_otel)
        self.assertTrue(records)


if __name__ == "__main__":
    unittest.main()
