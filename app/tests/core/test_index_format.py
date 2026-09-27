from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.core import index_format


def test_count_prefixed_array_roundtrip(tmp_path: Path) -> None:
    arr = np.array([1, 2, 3, 65535], dtype=np.uint32)
    path = tmp_path / "arr.bin"
    index_format.write_count_prefixed_array(path, arr)

    back = index_format.read_count_prefixed_array(path, np.uint32)
    np.testing.assert_array_equal(back, arr)


def test_count_prefixed_array_on_disk_layout(tmp_path: Path) -> None:
    # The on-disk bytes must be exactly: <Q count> followed by the raw payload.
    arr = np.array([7, 8, 9], dtype=np.uint64)
    path = tmp_path / "arr.bin"
    index_format.write_count_prefixed_array(path, arr)

    raw = path.read_bytes()
    assert raw[: index_format.COUNT_HEADER_SIZE] == struct.pack(
        index_format.COUNT_HEADER_STRUCT, arr.size
    )
    assert raw[index_format.COUNT_HEADER_SIZE :] == arr.tobytes()


def test_empty_array_writes_header_only(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    index_format.write_count_prefixed_array(path, np.array([], dtype=np.uint32))

    raw = path.read_bytes()
    assert raw == struct.pack(index_format.COUNT_HEADER_STRUCT, 0)
    back = index_format.read_count_prefixed_array(path, np.uint32)
    assert back.size == 0


def test_missing_file_raises_or_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "nope.bin"
    assert index_format.read_count_prefixed_array(missing, np.uint32, missing_ok=True) is None
    with pytest.raises(RuntimeError):
        index_format.read_count_prefixed_array(missing, np.uint32)


def test_postings_ptr_len_convention() -> None:
    assert index_format.postings_ptr_len(0) == 2
    assert index_format.postings_ptr_len(5) == 7
    assert index_format.POSTINGS_PTR_EXTRA == 2
    assert index_format.LEXICON_OFFSETS_EXTRA == 1


def test_header_sizes_match_struct_formats() -> None:
    assert index_format.LEXICON_HEADER_SIZE == struct.calcsize(index_format.LEXICON_HEADER_STRUCT)
    assert index_format.PREFIX_TOP_HEADER_SIZE == struct.calcsize(index_format.PREFIX_TOP_HEADER_STRUCT)
    assert index_format.BLOCK_TOP_HEADER_SIZE == struct.calcsize(index_format.BLOCK_TOP_HEADER_STRUCT)
    assert index_format.SVB_PTR_HEADER_SIZE == struct.calcsize(index_format.SVB_PTR_HEADER_STRUCT)
