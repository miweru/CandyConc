"""Concurrency safety for FastIndexBackend lazy caches.

Confirmed gap (100-agent review): ``FastIndexBackend`` lazily (re)builds the
KWIC string cache on first hot-path access with no lock. Two concurrent
first-accesses could each see ``_kwic_string_cache is None`` and build+assign a
fresh container, so one thread's partially populated cache gets discarded
mid-flight -> lost text / corruption under multi-user load. The ``_LRUCache``
regex cache is likewise mutated on every access.

These tests hammer a *fresh* backend from many threads doing concurrent
first-access against the real bench index and assert:
  (a) no exception escapes any worker, and
  (b) a single, consistent built cache (stable identity, correct contents).

Run against the real bench index:
    CANDYCONC_INDEX_PATH=<bench> \
    python -m pytest tests/core/test_fast_index_backend_concurrency.py \
        -o "addopts=" -p no:cacheprovider -q
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
import pytest

from candyconc.core.fast_index_backend import FastIndexBackend


def _bench_index_path() -> Path:
    raw = os.environ.get("CANDYCONC_INDEX_PATH")
    if not raw:
        pytest.skip("CANDYCONC_INDEX_PATH not set; needs the real bench index")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"bench index missing: {path}")
    return path


def _fresh_backend() -> FastIndexBackend:
    return FastIndexBackend(_bench_index_path())


def _some_positions(backend: FastIndexBackend) -> np.ndarray:
    """A non-empty position array to exercise the KWIC hot path."""
    token_count = int(backend.token_store.token_count)
    n = min(64, max(1, token_count))
    return np.arange(n, dtype=np.uint32)


def test_concurrent_first_access_kwic_cache_single_consistent_build() -> None:
    """16 threads concurrently trigger the lazy KWIC-cache build on a fresh
    backend. Repeated across many fresh instances to make the race likely.

    Asserts: no worker raises, the cache is built exactly once (identity is
    stable across all observers within an instance), and the produced KWIC rows
    are non-empty and identical in count across threads.
    """
    n_threads = 16
    iterations = 40

    for _ in range(iterations):
        backend = _fresh_backend()
        positions = _some_positions(backend)

        barrier = threading.Barrier(n_threads)
        errors: list[BaseException] = []
        cache_ids: list[int] = []
        row_counts: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                # Maximise the first-access overlap window.
                barrier.wait()
                rows = backend.kwic_rows_for_positions(
                    positions, ctx=5, include_arcs=False
                )
                cache = backend._kwic_string_cache
                with lock:
                    cache_ids.append(id(cache))
                    row_counts.append(len(rows))
            except BaseException as exc:  # noqa: BLE001 - record for the assert
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"workers raised: {errors!r}"
        # Single consistent built object: every thread observed the SAME cache.
        assert len(set(cache_ids)) == 1, (
            f"cache was rebuilt concurrently: {set(cache_ids)}"
        )
        # All threads computed the same, non-empty result.
        assert row_counts, "no worker produced rows"
        assert all(rc == row_counts[0] for rc in row_counts), row_counts
        assert row_counts[0] > 0


def test_concurrent_regex_cache_no_corruption() -> None:
    """Hammer the per-access-mutated _LRUCache (regex_positions) from many
    threads on a shared backend and assert no exception and stable results."""
    n_threads = 16
    backend = _fresh_backend()

    # A mix of patterns so get/set/eviction all fire concurrently.
    patterns = [r"^un.*", r"^ge.*", r".*ung$", r"^ver.*", r".*lich$", r"^be.*"]

    errors: list[BaseException] = []
    results: dict[str, int] = {}
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(tid: int) -> None:
        try:
            barrier.wait()
            for _ in range(50):
                for pat in patterns:
                    out = backend.regex_positions(pat, attr="word", limit=1000)
                    with lock:
                        prev = results.get(pat)
                        cur = int(out.size)
                        if prev is None:
                            results[pat] = cur
                        else:
                            # Same pattern must yield a stable size every time.
                            assert prev == cur, (pat, prev, cur)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"workers raised: {errors!r}"
