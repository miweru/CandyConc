from __future__ import annotations
import os
import resource
import time
from candyconc.config import get as get_config

TELEMETRY_ENABLED = get_config("CANDYCONC_ENABLE_TELEMETRY", "1") != "0"

_queries_total = 0
_query_latency_sum = 0.0
_query_latency_count = 0
_index_updates_total = 0
_index_latency_sum = 0.0
_index_latency_count = 0
_tasks_total = 0
_throughput_sum = 0.0
_throughput_count = 0
_token_usage_total = 0
_token_requests_total = 0


def _get_runtime_metrics() -> tuple[float, int]:
    """Return (cpu_load, memory_usage_bytes)."""
    try:
        cpu_load = os.getloadavg()[0]
    except OSError:
        cpu_load = 0.0
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if usage and usage < 10**8:  # likely KB on Unix
            usage *= 1024
    except Exception:
        usage = 0
    return cpu_load, int(usage)


def inc_queries() -> None:
    global _queries_total
    if TELEMETRY_ENABLED:
        _queries_total += 1


def inc_index_update() -> None:
    global _index_updates_total
    if TELEMETRY_ENABLED:
        _index_updates_total += 1


def inc_task() -> None:
    global _tasks_total
    if TELEMETRY_ENABLED:
        _tasks_total += 1


def inc_tokens(tokens: int) -> None:
    """Increment consumed token counters."""
    global _token_usage_total, _token_requests_total
    if TELEMETRY_ENABLED:
        _token_usage_total += tokens
        _token_requests_total += 1


def get_token_usage() -> int:
    """Return total consumed tokens."""
    return _token_usage_total


def start_timer() -> float:
    return time.perf_counter()


def observe_latency(start: float) -> None:
    global _query_latency_sum, _query_latency_count
    if TELEMETRY_ENABLED:
        _query_latency_sum += time.perf_counter() - start
        _query_latency_count += 1


def observe_index_latency(start: float) -> None:
    global _index_latency_sum, _index_latency_count
    if TELEMETRY_ENABLED:
        _index_latency_sum += time.perf_counter() - start
        _index_latency_count += 1


def observe_throughput(count: int, start: float) -> None:
    """Record processed row throughput for a query."""
    global _throughput_sum, _throughput_count
    if TELEMETRY_ENABLED and count > 0:
        duration = time.perf_counter() - start
        if duration > 0:
            _throughput_sum += count / duration
            _throughput_count += 1


def reset() -> None:
    """Reset all counters (for tests)."""
    global _queries_total, _query_latency_sum, _query_latency_count
    global _index_updates_total, _index_latency_sum, _index_latency_count
    global _tasks_total, _throughput_sum, _throughput_count
    global _token_usage_total, _token_requests_total

    _queries_total = 0
    _query_latency_sum = 0.0
    _query_latency_count = 0
    _index_updates_total = 0
    _index_latency_sum = 0.0
    _index_latency_count = 0
    _tasks_total = 0
    _throughput_sum = 0.0
    _throughput_count = 0
    _token_usage_total = 0
    _token_requests_total = 0


def metrics_text() -> str:
    if not TELEMETRY_ENABLED:
        return ""
    cpu_load, mem_usage = _get_runtime_metrics()
    lines = [
        "# HELP candyconc_queries_total Total query requests",
        "# TYPE candyconc_queries_total counter",
        f"candyconc_queries_total {_queries_total}",
        "# HELP candyconc_query_latency_seconds Query processing latency",
        "# TYPE candyconc_query_latency_seconds histogram",
        f"candyconc_query_latency_seconds_sum {_query_latency_sum}",
        f"candyconc_query_latency_seconds_count {_query_latency_count}",
        "# HELP candyconc_index_updates_total Files ingested into the index",
        "# TYPE candyconc_index_updates_total counter",
        f"candyconc_index_updates_total {_index_updates_total}",
        "# HELP candyconc_index_latency_seconds Indexing latency",
        "# TYPE candyconc_index_latency_seconds histogram",
        f"candyconc_index_latency_seconds_sum {_index_latency_sum}",
        f"candyconc_index_latency_seconds_count {_index_latency_count}",
        "# HELP candyconc_tasks_total Analysis tasks executed",
        "# TYPE candyconc_tasks_total counter",
        f"candyconc_tasks_total {_tasks_total}",
        "# HELP candyconc_query_throughput_rows_per_second Query result throughput",
        "# TYPE candyconc_query_throughput_rows_per_second gauge",
        f"candyconc_query_throughput_rows_per_second {_throughput_sum / max(_throughput_count, 1)}",
        "# HELP candyconc_cpu_load System load (1m average)",
        "# TYPE candyconc_cpu_load gauge",
        f"candyconc_cpu_load {cpu_load}",
        "# HELP candyconc_memory_usage_bytes Process memory usage",
        "# TYPE candyconc_memory_usage_bytes gauge",
        f"candyconc_memory_usage_bytes {mem_usage}",
        "# HELP candyconc_token_requests_total Policy checks performed",
        "# TYPE candyconc_token_requests_total counter",
        f"candyconc_token_requests_total {_token_requests_total}",
        "# HELP candyconc_tokens_consumed_total Tokens consumed by tools",
        "# TYPE candyconc_tokens_consumed_total counter",
        f"candyconc_tokens_consumed_total {_token_usage_total}",
    ]
    return "\n".join(lines) + "\n"
