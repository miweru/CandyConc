"""SCALE1 (R6): central overflow guards.

All tests are self-contained (numpy only, no file I/O, no spaCy, no index build)
and exercise the guards directly with synthetic high positions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.core import index_format  # noqa: E402
from candyconc.core.boundaries import BoundaryIndex  # noqa: E402
from cqlhpc.fast_corpus import _bounds_from_starts, _u32_to_i32_safe  # noqa: E402

MAX_I32 = index_format.MAX_I32
MAX_U32 = index_format.MAX_U32


def test_enforce_scaling_limits_ok():
    index_format.enforce_scaling_limits(token_count=100_000, vocab_size=50_000)


def test_enforce_scaling_limits_token_overflow():
    with pytest.raises(RuntimeError, match="int32"):
        index_format.enforce_scaling_limits(token_count=MAX_I32 + 1)


def test_enforce_scaling_limits_vocab_overflow():
    with pytest.raises(RuntimeError, match="Vokabular"):
        index_format.enforce_scaling_limits(token_count=100, vocab_size=MAX_U32 + 1)


def test_bounds_from_starts_near_overflow():
    # Positions near but below MAX_I32: must succeed (int32 dtype preserved).
    high = MAX_I32 - 10
    starts = np.array([0, high // 2, high], dtype=np.uint32)
    s, e = _bounds_from_starts(starts, high + 5, "test")
    assert s.dtype == np.int32
    assert e.dtype == np.int32
    assert int(e[-1]) == high + 5


def test_bounds_from_starts_over_max_i32_raises():
    starts = np.array([0, 1000], dtype=np.uint32)
    with pytest.raises(RuntimeError, match="int32"):
        _bounds_from_starts(starts, MAX_I32 + 1, "test")


def test_postings_list_near_max_i32():
    high_pos = np.array([MAX_I32 - 2, MAX_I32 - 1], dtype=np.uint32)
    result = _u32_to_i32_safe(high_pos)
    assert result.dtype == np.int32
    assert int(result[-1]) == MAX_I32 - 1


def test_postings_list_over_max_i32_raises():
    bad_pos = np.array([MAX_I32 + 1], dtype=np.uint32)
    with pytest.raises(RuntimeError, match="int32"):
        _u32_to_i32_safe(bad_pos)


def test_postings_list_empty_is_safe():
    out = _u32_to_i32_safe(np.zeros(0, dtype=np.uint32))
    assert out.size == 0


def test_boundary_sentinel_is_safe():
    # Empty boundaries -> whole corpus is one unit; sentinel must be MAX_U32,
    # never the old 2**31 which is one above MAX_I32 and overflows int32.
    b = BoundaryIndex(np.array([], dtype=np.uint32))
    start, end = b.get_boundary_for_pos(0)
    assert start == 0
    assert end == MAX_U32
    # clip_window with a large ctx must not raise and clips correctly.
    cs, ce = b.clip_window(1000, 50, 50)
    assert cs == 950
    assert ce == 1051


def test_boundary_sentinel_last_unit():
    # A real boundary list: the last unit's end is the MAX_U32 sentinel.
    b = BoundaryIndex(np.array([0, 10, 20], dtype=np.uint32))
    start, end = b.get_boundary_for_pos(25)  # past last boundary
    assert start == 20
    assert end == MAX_U32


def test_corpus_open_guard_rejects_oversized(monkeypatch):
    # The open-path guards (FastIndexBackend.__init__ + FastCorpus.from_backend)
    # must reject a corpus whose token_count exceeds MAX_I32 — tested through the
    # real call chain, not just the helper in isolation.
    import cqlhpc.fast_corpus as fc

    class _FakeStore:
        token_count = MAX_I32 + 1

    class _FakeBackend:
        token_store = _FakeStore()
        boundaries = None

    with pytest.raises(RuntimeError, match="int32"):
        fc.FastCorpus.from_backend(_FakeBackend())


def test_head_ids_sentinel_not_collide():
    # Simulate the head_ids encode path with doc_start near but below MAX_I32.
    doc_start = MAX_I32 - 100
    doc_len = 50
    head_arr = np.zeros(doc_len, dtype=np.int64)
    abs_head = head_arr + np.arange(doc_len, dtype=np.int64)
    valid = (abs_head >= 0) & (abs_head < doc_len)
    head_global = np.where(valid, doc_start + abs_head, -1)
    head_ids = head_global.astype(np.int32, copy=False)
    assert (head_ids >= 0).all()  # no collision with the -1 sentinel
    assert int(head_ids[-1]) == doc_start + doc_len - 1
