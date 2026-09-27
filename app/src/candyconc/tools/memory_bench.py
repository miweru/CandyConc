from __future__ import annotations

from typing import Any, Callable
import tracemalloc


def benchmark_memory(func: Callable[..., Any], *args: Any, **kwargs: Any) -> float:
    """Return peak memory usage in kilobytes for ``func``."""
    tracemalloc.start()
    func(*args, **kwargs)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024


__all__ = ["benchmark_memory"]
