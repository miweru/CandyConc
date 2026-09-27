from pathlib import Path

import numpy as np

from candyconc.core.boundaries import BoundaryIndex, BoundarySet, merge_sorted_unique_u32
from candyconc.core.coverage_sweep import coverage_sweep_arrays, total_context_mass_arrays


def _boundary_set(sentence_bounds: np.ndarray, document_bounds: np.ndarray) -> BoundarySet:
    bounds = BoundarySet(Path("/tmp/candyconc-test-bounds"))
    bounds.sentence = BoundaryIndex(sentence_bounds)
    bounds.document = BoundaryIndex(document_bounds)
    return bounds


def test_merge_sorted_unique_u32_merges_without_resort() -> None:
    left = np.array([0, 4, 8, 12], dtype=np.uint32)
    right = np.array([0, 6, 8, 10], dtype=np.uint32)
    merged = merge_sorted_unique_u32(left, right)
    np.testing.assert_array_equal(merged, np.array([0, 4, 6, 8, 10, 12], dtype=np.uint32))


def test_boundary_set_caches_sentence_document_union() -> None:
    bounds = _boundary_set(
        np.array([0, 4, 8, 12], dtype=np.uint32),
        np.array([0, 12], dtype=np.uint32),
    )
    first = bounds.clip_bounds_array(True)
    second = bounds.clip_bounds_array(True)
    assert first is second
    np.testing.assert_array_equal(first, np.array([0, 4, 8, 12], dtype=np.uint32))


def test_coverage_sweep_arrays_accepts_read_only_inputs() -> None:
    bounds = _boundary_set(
        np.array([0, 4, 8], dtype=np.uint32),
        np.array([0, 8], dtype=np.uint32),
    )
    anchors = np.array([2, 5], dtype=np.int64)
    spans = np.array([1, 1], dtype=np.int64)
    anchors.setflags(write=False)
    spans.setflags(write=False)
    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors,
        spans,
        window_left=1,
        window_right=1,
        boundaries=bounds,
        within_sentence=True,
        pair_semantics=True,
        total_tokens=8,
    )
    np.testing.assert_array_equal(seg_starts, np.array([1, 3, 4, 6], dtype=np.uint32))
    np.testing.assert_array_equal(seg_ends, np.array([2, 4, 5, 7], dtype=np.uint32))
    np.testing.assert_array_equal(seg_weights, np.array([1, 1, 1, 1], dtype=np.uint32))


def test_coverage_sweep_arrays_variable_spans_uses_generic_path() -> None:
    anchors = np.array([2, 5], dtype=np.int64)
    spans = np.array([2, 1], dtype=np.int64)
    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors,
        spans,
        window_left=1,
        window_right=1,
        boundaries=None,
        within_sentence=False,
        pair_semantics=True,
        total_tokens=8,
    )
    np.testing.assert_array_equal(seg_starts, np.array([1, 4, 6], dtype=np.uint32))
    np.testing.assert_array_equal(seg_ends, np.array([2, 5, 7], dtype=np.uint32))
    np.testing.assert_array_equal(seg_weights, np.array([1, 2, 1], dtype=np.uint32))


def test_coverage_sweep_keeps_cross_anchor_context_pairs() -> None:
    starts, ends, weights = coverage_sweep_arrays(
        np.array([2, 3], dtype=np.int64),
        np.array([1, 1], dtype=np.int64),
        window_left=2,
        window_right=2,
        pair_semantics=True,
        total_tokens=6,
    )

    # Each node's own span is absent, while the other adjacent node remains a
    # legitimate context token. Removing all anchor positions would erase the
    # cross-anchor pairs and incorrectly reduce this mass from eight to six.
    np.testing.assert_array_equal(starts, np.arange(6, dtype=np.uint32))
    np.testing.assert_array_equal(ends, np.arange(1, 7, dtype=np.uint32))
    np.testing.assert_array_equal(weights, np.array([1, 2, 1, 1, 2, 1], dtype=np.uint32))
    assert total_context_mass_arrays(starts, ends, weights) == 8
