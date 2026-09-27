"""Unit tests for PairSink (R3.1): the backend-owned doc_idx authority."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.jobs.build_fast_index_from_parquet import PairSink  # noqa: E402


def test_assign_is_monotonic_and_idempotent():
    s = PairSink()
    assert s.assign("h") == 0
    assert s.assign("a") == 1
    assert s.assign("h") == 0  # same anchor -> same seq
    assert s.n_assigned == 2


def test_bind_in_assign_order_then_resolve():
    s = PairSink()
    s.assign("h")
    s.assign("a1")
    s.assign("a2")
    s.on_pair("h", "a1")
    s.on_pair("h", "a2")
    s.bind("h", 0)
    s.bind("a1", 1)
    s.bind("a2", 2)
    assert s.n_bound == 3
    assert list(s.resolve_pairs()) == [(0, 1), (0, 2)]  # on_pair order preserved


def test_bind_out_of_order_raises():
    s = PairSink()
    s.assign("h")   # seq 0
    s.assign("a")   # seq 1
    with pytest.raises(RuntimeError, match="Desync"):
        s.bind("a", 0)  # engine doc_idx 0 != assign seq 1


def test_bind_unknown_anchor_raises():
    s = PairSink()
    with pytest.raises(RuntimeError, match="nicht zugewiesener Anchor"):
        s.bind("ghost", 0)


def test_resolve_pairs_requires_bound_anchor():
    s = PairSink()
    s.assign("h")
    s.assign("a")
    s.on_pair("h", "a")
    s.bind("h", 0)  # 'a' never bound
    with pytest.raises(RuntimeError, match="resolve_pairs"):
        list(s.resolve_pairs())


def test_resolve_duplicates_maps_to_bound_idx():
    s = PairSink()
    # Five earlier docs so the AI doc 'a' is assigned (and bound to) seq 5.
    for i in range(5):
        s.assign(f"d{i}")
        s.bind(f"d{i}", i)
    s.assign("a")  # seq 5
    s.on_duplicate("a", "job-1")
    s.on_duplicate("a", "job-2")
    s.bind("a", 5)
    assert s.resolve_duplicates() == {5: 2}
