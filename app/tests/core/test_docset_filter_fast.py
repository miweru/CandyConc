import numpy as np

from candyconc.core.counting_kernels import (
    filter_positions_and_values_by_docset_fast,
    filter_positions_by_docset_fast,
    map_positions_to_doc_ids_fast,
    position_to_doc_id_fast,
    unique_doc_ids_from_positions_fast,
)


def test_filter_positions_by_docset_fast_matches_expected_docs() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32)
    docset_mask = np.array([True, False, True, False], dtype=bool)

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    np.testing.assert_array_equal(
        filtered,
        np.array([0, 3, 10, 12, 19], dtype=np.uint32),
    )


def test_filter_positions_and_values_by_docset_fast_keeps_alignment() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32)
    spans = np.array([1, 1, 2, 2, 3, 3, 4], dtype=np.int64)
    docset_mask = np.array([False, True, True, False], dtype=bool)

    filtered_positions, filtered_spans = filter_positions_and_values_by_docset_fast(
        positions,
        spans,
        doc_bounds,
        docset_mask,
    )

    np.testing.assert_array_equal(
        filtered_positions,
        np.array([5, 7, 10, 12, 19], dtype=np.uint32),
    )
    np.testing.assert_array_equal(
        filtered_spans,
        np.array([2, 2, 3, 3, 4], dtype=np.int64),
    )


def test_unique_doc_ids_from_positions_fast_returns_sorted_doc_ids() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32)

    doc_ids = unique_doc_ids_from_positions_fast(positions, doc_bounds)

    np.testing.assert_array_equal(doc_ids, np.array([0, 1, 2], dtype=np.uint32))


def test_map_positions_to_doc_ids_fast_returns_aligned_doc_ids() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([0, 3, 5, 7, 10, 12, 19], dtype=np.uint32)

    doc_ids = map_positions_to_doc_ids_fast(positions, doc_bounds)

    np.testing.assert_array_equal(
        doc_ids,
        np.array([0, 0, 1, 1, 2, 2, 2], dtype=np.int64),
    )


def test_map_positions_to_doc_ids_fast_handles_unsorted_positions() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([10, 0, 12, 3, 5, 19, 7], dtype=np.uint32)

    doc_ids = map_positions_to_doc_ids_fast(positions, doc_bounds)

    np.testing.assert_array_equal(
        doc_ids,
        np.array([2, 0, 2, 0, 1, 2, 1], dtype=np.int64),
    )


def test_position_to_doc_id_fast_maps_single_position() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)

    assert position_to_doc_id_fast(12, doc_bounds) == 2
    assert position_to_doc_id_fast(7, doc_bounds) == 1


def test_filter_positions_by_docset_fast_handles_unsorted_positions() -> None:
    doc_bounds = np.array([0, 5, 10, 20], dtype=np.uint32)
    positions = np.array([10, 0, 12, 3, 5, 19, 7], dtype=np.uint32)
    docset_mask = np.array([True, False, True, False], dtype=bool)

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    np.testing.assert_array_equal(
        filtered,
        np.array([10, 0, 12, 3, 19], dtype=np.uint32),
    )


def test_filter_positions_by_docset_fast_reuses_input_when_everything_matches() -> None:
    doc_bounds = np.array([0, 5, 10], dtype=np.uint32)
    positions = np.array([0, 1, 5, 9], dtype=np.uint32)
    docset_mask = np.array([True, True, True], dtype=bool)

    filtered = filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)

    assert filtered is positions
