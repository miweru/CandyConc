"""Regression tests for D2(c) — token_count provenance in token_store.

``_load_svb_stream`` previously discarded the SVB ptr-header's third field (the
exact ``token_count``) and, when ``meta.bin`` was missing, fell back to
``n_blocks * block_size`` — which over-counts by up to ``block_size - 1`` tokens
in the final (partial) block and corrupts every position-dependent computation.

The fix:
  * captures the header ``token_count``;
  * uses it (not ``n_blocks * block_size``) when ``meta.bin`` is absent, and
    propagates it onto the store;
  * raises a RuntimeError when ``meta.bin`` and the header disagree.

These are pure-unit tests: a tiny hand-built SVB stream is written to a temp dir
and ``_load_svb_stream`` is exercised directly (no real index required).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from candyconc.core import index_format
from candyconc.core.token_store import TokenStore


def _write_svb_stream(
    base_dir: Path,
    name: str,
    *,
    n_blocks: int,
    block_size: int,
    header_token_count: int,
    data_payload: bytes = b"\x00\x00\x00\x00",
) -> None:
    """Write a minimal, structurally-valid SVB ptr/data pair.

    ``_load_svb_stream`` only reads the header + (n_blocks+1) offsets from the
    ptr file and mmaps the data file (it does not decode during load), so a
    trivial data payload is sufficient to exercise the token_count logic.
    """
    ptr_path = base_dir / f"{name}_ids.svb.ptr.bin"
    data_path = base_dir / f"{name}_ids.svb.data.bin"
    with open(ptr_path, "wb") as f:
        f.write(
            struct.pack(
                index_format.SVB_PTR_HEADER_STRUCT,
                int(n_blocks),
                int(block_size),
                int(header_token_count),
            )
        )
        # (n_blocks + 1) uint64 offsets; all zero is fine for load.
        offsets = np.zeros((n_blocks + 1,), dtype=np.uint64)
        f.write(offsets.tobytes())
    with open(data_path, "wb") as f:
        f.write(data_payload)


def test_header_token_count_used_when_meta_absent(tmp_path: Path) -> None:
    # block_size=8, n_blocks=2 -> n_blocks*block_size = 16, but the true
    # token_count is 13 (partial last block). The fix must report 13, not 16.
    _write_svb_stream(
        tmp_path, "word", n_blocks=2, block_size=8, header_token_count=13
    )
    store = TokenStore(tmp_path)
    assert store._token_count == 0  # no meta.bin loaded yet

    stream = store._load_svb_stream("word")
    assert stream is not None
    assert stream.token_count == 13, "must use SVB-header count, not n_blocks*block_size"
    # The header count must also be propagated onto the store.
    assert store._token_count == 13


def test_meta_count_is_authoritative_when_consistent(tmp_path: Path) -> None:
    _write_svb_stream(
        tmp_path, "word", n_blocks=2, block_size=8, header_token_count=13
    )
    store = TokenStore(tmp_path)
    store._token_count = 13  # simulate a consistent meta.bin

    stream = store._load_svb_stream("word")
    assert stream is not None
    assert stream.token_count == 13


def test_meta_header_mismatch_raises(tmp_path: Path) -> None:
    _write_svb_stream(
        tmp_path, "word", n_blocks=2, block_size=8, header_token_count=13
    )
    store = TokenStore(tmp_path)
    store._token_count = 16  # stale / wrong meta.bin (the old bad fallback value)

    with pytest.raises(RuntimeError, match="inkonsistent"):
        store._load_svb_stream("word")


def test_legacy_zero_header_falls_back_to_block_product(tmp_path: Path) -> None:
    """A legacy stream that wrote 0 into the header token_count field (pre-fix
    writers) must still load, falling back to n_blocks*block_size."""
    _write_svb_stream(
        tmp_path, "word", n_blocks=2, block_size=8, header_token_count=0
    )
    store = TokenStore(tmp_path)
    stream = store._load_svb_stream("word")
    assert stream is not None
    assert stream.token_count == 16
