from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from candyconc.config import APP_CONFIG


class _NoopSpan:
    """Inert span yielded by :meth:`Observability.span` when OTEL is off.

    Call sites (e.g. ``orchestrator.py``: ``with observability.span(...) as
    span: span.set_attribute(...)``) use the span unconditionally; yielding
    ``None`` crashed every such site with ``AttributeError``. This object
    keeps the OTEL span surface as no-ops so all call sites work unchanged.
    """

    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add_event(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        return None

    def end(self, *args: Any, **kwargs: Any) -> None:
        return None

    def is_recording(self) -> bool:
        return False


_NOOP_SPAN = _NoopSpan()


class Observability:
    """Collect metrics and structured logs for tool execution."""

    def __init__(
        self, service_name: str = "candyconc", enable_otel: bool | None = None
    ) -> None:
        self.service_name = service_name
        self.enable_otel = False
        self.metrics: Dict[str, Any] = defaultdict(int)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(session)s %(tool)s %(message)s",
        )
        if enable_otel is None:
            enable_otel = APP_CONFIG.CANDYCONC_ENABLE_OTEL if hasattr(APP_CONFIG, "CANDYCONC_ENABLE_OTEL") else False
        if enable_otel:
            try:  # optional dependency
                from opentelemetry import metrics, trace
                from opentelemetry.sdk.metrics import MeterProvider
                from opentelemetry.sdk.metrics.export import (
                    ConsoleMetricExporter,
                    PeriodicExportingMetricReader,
                )
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import (
                    ConsoleSpanExporter,
                    SimpleSpanProcessor,
                )

                reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
                provider = MeterProvider(metric_readers=[reader])
                metrics.set_meter_provider(provider)
                meter = metrics.get_meter(service_name)
                self._call_counter = meter.create_counter("tool_calls")
                self._token_hist = meter.create_histogram("tool_tokens")
                self._latency_hist = meter.create_histogram("tool_latency_ms")

                trace_provider = TracerProvider()
                trace_provider.add_span_processor(
                    SimpleSpanProcessor(ConsoleSpanExporter())
                )
                trace.set_tracer_provider(trace_provider)
                self._tracer = trace.get_tracer(service_name)
                self._session_spans: Dict[str, Any] = {}

                self.enable_otel = True
            except Exception:  # pragma: no cover - opentelemetry missing
                logging.getLogger(__name__).exception("OpenTelemetry not available")

    def record(
        self,
        session_id: str,
        tool: str,
        *,
        tokens: int = 0,
        duration_ms: float = 0.0,
        status: str = "ok",
    ) -> None:
        """Record metrics and log a structured event."""
        logging.getLogger("candyconc").info(
            status, extra={"session": session_id, "tool": tool}
        )
        key_pref = f"{tool}."
        self.metrics[f"{key_pref}calls"] += 1
        self.metrics[f"{key_pref}tokens"] += tokens
        self.metrics[f"{key_pref}errors"] += 0 if status == "ok" else 1
        self.metrics[f"{key_pref}latency_ms_sum"] += duration_ms
        self.metrics[f"{key_pref}latency_ms_count"] += 1
        if self.enable_otel:
            attrs = {"tool": tool, "status": status}
            self._call_counter.add(1, attributes=attrs)
            self._token_hist.record(tokens, attributes=attrs)
            self._latency_hist.record(duration_ms, attributes=attrs)

    @contextmanager
    def span(self, session_id: str, name: str, **attrs: Any) -> Iterator[Any]:
        """Context manager emitting an OpenTelemetry span if enabled.

        With OTEL disabled it yields an inert :class:`_NoopSpan` (never
        ``None``) so call sites may use the span unconditionally.
        """
        if not self.enable_otel:
            yield _NOOP_SPAN
            return

        import opentelemetry.trace as trace

        parent = self._session_spans.get(session_id)
        if parent is None:
            parent = self._tracer.start_span(
                "session", attributes={"session_id": session_id}
            )
            self._session_spans[session_id] = parent
        ctx = trace.set_span_in_context(parent)
        with self._tracer.start_as_current_span(name, context=ctx) as span:
            yield span
            for key, val in attrs.items():
                span.set_attribute(key, val)

    def end_session(self, session_id: str) -> None:
        """Finish the root span for ``session_id`` if tracing enabled."""
        if not self.enable_otel:
            return
        span = self._session_spans.pop(session_id, None)
        if span is not None:
            span.end()

    def export_metrics(self) -> Dict[str, Any]:
        """Return collected metrics including average latency."""
        data = dict(self.metrics)
        for key in list(self.metrics.keys()):
            if key.endswith(".latency_ms_sum"):
                prefix = key[: -len("latency_ms_sum")]
                count_key = f"{prefix}latency_ms_count"
                count = self.metrics.get(count_key, 0)
                if count:
                    data[f"{prefix}latency_ms"] = self.metrics[key] / count
        return data
