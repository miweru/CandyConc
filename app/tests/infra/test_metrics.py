import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from candyconc.services.backend import app, metrics
from candyconc.services.backend import server as backend_server
from candyconc.services.backend.routes import system as system_routes


class _FakeObservability:
    def __init__(self, values: dict[str, float]) -> None:
        self._values = values

    def export_metrics(self) -> dict[str, float]:
        return dict(self._values)


class TestMetricsEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self._telemetry_enabled = metrics.TELEMETRY_ENABLED
        self._observability = backend_server._OBSERVABILITY
        self._system_server = system_routes._server
        system_routes._server = lambda: backend_server
        metrics.TELEMETRY_ENABLED = True
        metrics.reset()

    def tearDown(self) -> None:
        metrics.reset()
        metrics.TELEMETRY_ENABLED = self._telemetry_enabled
        backend_server._OBSERVABILITY = self._observability
        system_routes._server = self._system_server

    def test_metrics_endpoint_exposes_runtime_and_cost_counters(self) -> None:
        backend_server._OBSERVABILITY = _FakeObservability(
            {
                "analysis.jobs.running": 2.0,
                "copilot.tool.calls": 5.0,
            }
        )
        with patch(
            "candyconc.services.backend.metrics.time.perf_counter",
            side_effect=[10.0, 10.25, 10.5, 20.0, 21.0],
        ):
            query_start = metrics.start_timer()
            metrics.inc_queries()
            metrics.observe_latency(query_start)
            metrics.observe_throughput(10, query_start)
            index_start = metrics.start_timer()
            metrics.inc_index_update()
            metrics.observe_index_latency(index_start)
        metrics.inc_task()
        metrics.inc_tokens(128)

        with patch(
            "candyconc.services.backend.metrics._get_runtime_metrics",
            return_value=(1.5, 2048),
        ):
            resp = self.client.get("/api/v1/metrics")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/plain"))
        text = resp.text
        self.assertIn("candyconc_queries_total 1", text)
        self.assertIn("candyconc_query_latency_seconds_sum 0.25", text)
        self.assertIn("candyconc_query_latency_seconds_count 1", text)
        self.assertIn("candyconc_index_updates_total 1", text)
        self.assertIn("candyconc_index_latency_seconds_sum 1.0", text)
        self.assertIn("candyconc_index_latency_seconds_count 1", text)
        self.assertIn("candyconc_tasks_total 1", text)
        self.assertIn("candyconc_query_throughput_rows_per_second 20.0", text)
        self.assertIn("candyconc_cpu_load 1.5", text)
        self.assertIn("candyconc_memory_usage_bytes 2048", text)
        self.assertIn("candyconc_token_requests_total 1", text)
        self.assertIn("candyconc_tokens_consumed_total 128", text)
        self.assertIn("candyconc_analysis_jobs_running 2.0", text)
        self.assertIn("candyconc_copilot_tool_calls 5.0", text)

    def test_metrics_endpoint_can_export_observability_without_base_telemetry(self) -> None:
        metrics.TELEMETRY_ENABLED = False
        backend_server._OBSERVABILITY = _FakeObservability({"copilot.tool.calls": 3.0})

        resp = self.client.get("/api/v1/metrics")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "candyconc_copilot_tool_calls 3.0\n")


if __name__ == "__main__":
    unittest.main()
