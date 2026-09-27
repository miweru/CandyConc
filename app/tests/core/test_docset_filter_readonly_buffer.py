"""Regression: docset kernels must accept read-only (mmap-backed) inputs.

The Fast Index keeps its hot arrays as zero-copy ``np.frombuffer`` / mmap views,
which are *read-only*. Metadata-filtered queries (``?genre=``/``?date=``) and
docset-scoped analysis route those read-only ``positions``/``doc_bounds``/
``docset_mask`` arrays into the Cython docset kernels.

Before the fix the kernels declared their inputs as writable ``np.ndarray[...]``
buffer parameters, so Cython tried to acquire a *writable* buffer and raised
``ValueError: buffer source array is read-only`` — 500'ing every metadata-filtered
query. The kernels now take ``const`` typed memoryviews, accepting read-only
buffers zero-copy. These tests pin that contract by flipping the input arrays'
``writeable`` flag off (the same state an mmap view exposes).
"""

import numpy as np
import pytest

from candyconc.core.counting_kernels import (
    filter_positions_and_values_by_docset_fast,
    filter_positions_by_docset_fast,
    map_positions_to_doc_ids_fast,
    position_to_doc_id_fast,
    unique_doc_ids_from_positions_fast,
)


def _readonly(arr: np.ndarray) -> np.ndarray:
    """Return ``arr`` with its writeable flag cleared, mimicking an mmap view."""
    arr.flags.writeable = False
    return arr


def test_filter_positions_by_docset_fast_accepts_readonly_inputs() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))
    positions = _readonly(np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32))
    docset_mask = _readonly(np.array([1, 0, 1, 0], dtype=np.uint8))

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    np.testing.assert_array_equal(
        filtered,
        np.array([0, 3, 10, 12, 19], dtype=np.uint32),
    )


def test_filter_positions_by_docset_fast_readonly_all_match() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10], dtype=np.uint32))
    positions = _readonly(np.array([0, 1, 5, 9], dtype=np.uint32))
    docset_mask = _readonly(np.array([1, 1, 1], dtype=np.uint8))

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    # All-match fast path returns the original array zero-copy.
    assert filtered is positions


def test_filter_positions_and_values_readonly_inputs() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))
    positions = _readonly(np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32))
    spans = _readonly(np.array([1, 1, 2, 2, 3, 3, 4], dtype=np.int64))
    docset_mask = _readonly(np.array([0, 1, 1, 0], dtype=np.uint8))

    out_pos, out_spans = filter_positions_and_values_by_docset_fast(
        positions, spans, doc_bounds, docset_mask
    )

    np.testing.assert_array_equal(out_pos, np.array([5, 7, 10, 12, 19], dtype=np.uint32))
    np.testing.assert_array_equal(out_spans, np.array([2, 2, 3, 3, 4], dtype=np.int64))


def test_filter_positions_and_values_readonly_all_match() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10], dtype=np.uint32))
    positions = _readonly(np.array([0, 1, 5, 9], dtype=np.uint32))
    spans = _readonly(np.array([7, 8, 9, 10], dtype=np.int64))
    docset_mask = _readonly(np.array([1, 1, 1], dtype=np.uint8))

    out_pos, out_spans = filter_positions_and_values_by_docset_fast(
        positions, spans, doc_bounds, docset_mask
    )

    assert out_pos is positions
    assert out_spans is spans


def test_unique_doc_ids_from_positions_fast_readonly_inputs() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))
    positions = _readonly(np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32))

    doc_ids = unique_doc_ids_from_positions_fast(positions, doc_bounds)

    np.testing.assert_array_equal(doc_ids, np.array([0, 1, 2], dtype=np.uint32))


def test_map_positions_to_doc_ids_fast_readonly_inputs() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))
    positions = _readonly(np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32))

    doc_ids = map_positions_to_doc_ids_fast(positions, doc_bounds)

    np.testing.assert_array_equal(
        doc_ids, np.array([0, 0, 1, 1, 2, 2, 2], dtype=np.int64)
    )


def test_position_to_doc_id_fast_readonly_bounds() -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))

    assert position_to_doc_id_fast(12, doc_bounds) == 2
    assert position_to_doc_id_fast(7, doc_bounds) == 1


@pytest.mark.parametrize("mask_dtype", [np.uint8, bool])
def test_filter_readonly_bool_and_uint8_masks_agree(mask_dtype) -> None:
    doc_bounds = _readonly(np.array([0, 5, 10, 20], dtype=np.uint32))
    positions = _readonly(np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32))
    docset_mask = _readonly(np.array([1, 0, 1, 0], dtype=mask_dtype))

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    np.testing.assert_array_equal(
        filtered, np.array([0, 3, 10, 12, 19], dtype=np.uint32)
    )
