"""Bounded executor shared by heavy corpus scans.

Create one pool with the worker count resolved from environment then
configuration at import time. Server re-exports preserve its identity
and the same concurrency bound across all callers."""

import asyncio
import concurrent.futures
import contextvars
import os
from functools import partial
from typing import Any, Callable

from candyconc.config import get as get_config

# Run full corpus scans on a bounded pool so they cannot occupy every
# default-executor worker and starve small metadata or count lookups.
# CANDYCONC_HEAVY_WORKERS limits concurrent scans. Excess work queues in
# the executor without blocking the event loop.


def _heavy_scan_worker_count() -> int:
    raw = os.environ.get("CANDYCONC_HEAVY_WORKERS") or get_config(
        "CANDYCONC_HEAVY_WORKERS", "4"
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 4
    return max(1, value)


_HEAVY_SCAN_WORKERS = _heavy_scan_worker_count()
_HEAVY_SCAN_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_HEAVY_SCAN_WORKERS, thread_name_prefix="cc-heavy-scan"
)


def _run_heavy_scan_sync(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Submit a synchronous heavy scan to the shared bounded pool.

Only heavy work enters this pool so small tools retain default-executor
capacity. Run inline when already on one of its threads, since submitting
back into a saturated pool could deadlock."""
    import threading

    if threading.current_thread().name.startswith("cc-heavy-scan"):
        return fn(*args, **kwargs)
    return _HEAVY_SCAN_EXECUTOR.submit(partial(fn, *args, **kwargs)).result()


async def _run_heavy_scan(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """Run a HEAVY synchronous scan on the bounded heavy-scan pool.

    Drop-in replacement for ``asyncio.to_thread`` (propagates contextvars and
    exceptions identically) that targets ``_HEAVY_SCAN_EXECUTOR`` instead of
    the shared default executor.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    call = partial(ctx.run, fn, *args, **kwargs)
    return await loop.run_in_executor(_HEAVY_SCAN_EXECUTOR, call)
