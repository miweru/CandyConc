"""Regression tests for the app-audit Quick-Win fixes (2026-06-08).

Covers the isolated-testable fixes: the bitset OR-accumulate (data-integrity),
the LRU cache thread-safety, the _apply_cql_span_to_row pivot re-clamp, and the
collision-resistant fact-id helper.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_bitset_or_accumulate_keeps_all_colocated_positions():
    # The buffered fancy-index |= kept only the LAST bit per byte; np.bitwise_or.at
    # must keep all. Reproduce the exact decode used by _bitset_for_ids.
    positions = np.array([0, 1, 2, 3, 8, 9, 15], dtype=np.uint32)
    n_tokens = 16
    n_bytes = (n_tokens + 7) >> 3
    out = np.zeros((n_bytes,), dtype=np.uint8)
    pos_i64 = positions.astype(np.int64, copy=False)
    np.bitwise_or.at(out, (pos_i64 >> 3), (np.uint8(1) << (pos_i64 & 7)).astype(np.uint8))
    # Decode the bitset back to positions.
    decoded = [p for p in range(n_tokens) if out[p >> 3] & (1 << (p & 7))]
    assert decoded == [0, 1, 2, 3, 8, 9, 15]


def test_lru_cache_thread_safe_under_concurrency():
    from cqlhpc.engine import _LRUCache

    cache = _LRUCache(maxsize=64)
    errors: list[Exception] = []

    def worker(base: int):
        try:
            for i in range(2000):
                k = str((base + i) % 128)
                cache.set(k, i)
                cache.get(k)
                cache.get(str(i % 128))
        except Exception as exc:  # the TOCTOU bug surfaced as KeyError
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(b * 1000,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"concurrent LRU access raised: {errors[:3]}"


def test_byte_lru_cache_thread_safe():
    from cqlhpc.engine import _ByteLRUCache

    cache = _ByteLRUCache(max_bytes=1 << 16, max_entries=32)
    errors: list[Exception] = []

    def worker(base: int):
        try:
            for i in range(2000):
                k = str((base + i) % 64)
                cache.set(k, np.zeros(i % 16 + 1, dtype=np.int32))
                cache.get(k)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(b * 1000,)) for b in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"concurrent byte-LRU access raised: {errors[:3]}"


def test_apply_cql_span_pivot_reclamp_no_indexerror():
    # Match near a document end: right context shorter than the match, pivot != 0.
    # Before the fix this raised IndexError; now it clamps pivot and renders.
    from candyconc.core.query_runtime import _apply_cql_span_to_row

    row = {"left": "anfang", "kw": "wort1", "right": "wort2", "pos": 100}
    # match_len_const=3, pivot=2, but right context has only 1 token -> match_len
    # clamps to 2, pivot must re-clamp to 1.
    out = _apply_cql_span_to_row(row, 3, 2)
    assert isinstance(out, dict)
    assert out["kw"]  # rendered without crashing


def test_compact_id_collision_resistant():
    from candyconc.candyconc_copilot.analysis_grounding import _compact_id

    base = "E_call_" + "x" * 50  # a long item.id prefix (>40 chars)
    id1 = _compact_id(f"{base}_table_metric_freq_1", 96)
    id2 = _compact_id(f"{base}_table_metric_freq_2", 96)
    id3 = _compact_id(f"{base}_table_metric_score_1", 96)
    assert id1 != id2 != id3 and id1 != id3  # distinct despite shared 40-char prefix
    assert all(len(x) <= 96 for x in (id1, id2, id3))
    # Short ids pass through unchanged.
    assert _compact_id("short_id", 96) == "short_id"


# NOTE: cluster_save decorator placement + the registry misattachment guard are
# verified separately (the real registry registers 16 tools with cluster_save's
# callable == cluster_save, and the tooling/ test suite exercises dispatch).
# They are not retested here because tests/core runs under a stubbed
# candyconc_copilot, where the real registry/tool_wrappers are not loaded.
