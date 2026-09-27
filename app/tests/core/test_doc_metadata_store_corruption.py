"""B8: doc_metadata corruption must raise, not silently return {}.

Fail-before/pass-after: prior to the fix, CRC mismatch, truncated payload and
JSON-decode failure in DocMetadataMMap._read_one all silently yielded {},
corrupting downstream frequencies/contrast without any signal.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from candyconc.core import index_format
from candyconc.core.doc_metadata_store import DocMetadataMMap

METAS: list[dict] = [
    {"path": "src:abc::orig::na", "doc_id": "0", "source": "src", "register": "news"},
    {"path": "src:def::orig::na", "doc_id": "1", "source": "src", "register": "chat"},
    {"path": "src:ghi::orig::na", "doc_id": "2", "source": "src", "register": "drama"},
]


def _write_array_with_count(path: Path, arr: np.ndarray) -> None:
    with path.open("wb") as f:
        f.write(struct.pack("<Q", int(arr.size)))
        f.write(arr.tobytes())


def _build_store(base: Path, metas: list[dict], *, empty_last: bool = False) -> None:
    """Write a doc_metadata store in the same frame format as the index builder."""
    import json

    blob = bytearray()
    offsets = [0]
    crcs = []
    for meta in metas:
        payload = json.dumps(meta, ensure_ascii=False).encode("utf-8")
        crc = zlib.crc32(payload)
        blob += index_format.DOC_META_FRAME_MAGIC
        blob += struct.pack("<II", len(payload), crc)
        blob += payload
        offsets.append(len(blob))
        crcs.append(crc)
    if empty_last:
        offsets.append(len(blob))  # zero-length entry (legitimately empty)
        crcs.append(0)
    (base / "doc_metadata.mmap").write_bytes(bytes(blob))
    _write_array_with_count(base / "doc_metadata.idx.bin", np.asarray(offsets, dtype=np.uint64))
    _write_array_with_count(base / "doc_metadata.crc.bin", np.asarray(crcs, dtype=np.uint32))


def _frame_bounds(base: Path, idx: int) -> tuple[int, int]:
    raw = (base / "doc_metadata.idx.bin").read_bytes()
    (count,) = struct.unpack_from("<Q", raw, 0)
    offsets = np.frombuffer(raw[8:], dtype=np.uint64, count=int(count))
    return int(offsets[idx]), int(offsets[idx + 1])


def _flip_payload_byte(base: Path, idx: int) -> None:
    """Flip one payload byte of entry `idx` so its CRC no longer matches."""
    blob_path = base / "doc_metadata.mmap"
    blob = bytearray(blob_path.read_bytes())
    start, _end = _frame_bounds(base, idx)
    pos = start + 12  # first payload byte after MAGIC(4)+len(4)+crc(4)
    blob[pos] ^= 0xFF
    blob_path.write_bytes(bytes(blob))


def test_uncorrupted_store_loads_identically(tmp_path: Path) -> None:
    """Golden: a valid store behaves exactly as before the fix."""
    _build_store(tmp_path, METAS, empty_last=True)
    store = DocMetadataMMap(tmp_path)
    assert len(store) == len(METAS) + 1
    for i, expected in enumerate(METAS):
        assert store[i] == expected
    # zero-length entry stays a legitimate empty dict (no raise)
    assert store[len(METAS)] == {}
    # Mapping surface unchanged
    assert store.get(0) == METAS[0]
    assert store.get(999) is None
    assert dict(store.items())[1] == METAS[1]
    assert 0 in store
    label, prepared = store.prepared_entry(0)
    assert label == METAS[0]["path"]
    assert prepared["register"] == "news"
    store.close()


def test_crc_mismatch_raises(tmp_path: Path) -> None:
    _build_store(tmp_path, METAS)
    _flip_payload_byte(tmp_path, 1)
    store = DocMetadataMMap(tmp_path)
    # intact neighbours still readable
    assert store[0] == METAS[0]
    assert store[2] == METAS[2]
    with pytest.raises(RuntimeError, match="doc_metadata korrupt.*CRC mismatch.*doc 1"):
        store[1]
    # .get() must not mask corruption as a missing entry either
    with pytest.raises(RuntimeError, match="CRC mismatch"):
        store.get(1)
    store.close()


def test_truncated_payload_raises(tmp_path: Path) -> None:
    _build_store(tmp_path, METAS)
    # Inflate the declared payload length of entry 2 beyond the frame end.
    blob_path = tmp_path / "doc_metadata.mmap"
    blob = bytearray(blob_path.read_bytes())
    start, end = _frame_bounds(tmp_path, 2)
    struct.pack_into("<I", blob, start + 4, (end - start - 12) + 1000)
    blob_path.write_bytes(bytes(blob))
    store = DocMetadataMMap(tmp_path)
    assert store[0] == METAS[0]
    with pytest.raises(RuntimeError, match="doc_metadata korrupt.*abgeschnitten.*doc 2"):
        store[2]
    store.close()


def test_json_decode_failure_raises(tmp_path: Path) -> None:
    # Garbage payload with a *valid* CRC: only JSON decoding can fail.
    garbage = b"\xff\xfenot json at all"
    crc = zlib.crc32(garbage)
    blob = bytearray()
    blob += index_format.DOC_META_FRAME_MAGIC
    blob += struct.pack("<II", len(garbage), crc)
    blob += garbage
    (tmp_path / "doc_metadata.mmap").write_bytes(bytes(blob))
    _write_array_with_count(
        tmp_path / "doc_metadata.idx.bin", np.asarray([0, len(blob)], dtype=np.uint64)
    )
    _write_array_with_count(tmp_path / "doc_metadata.crc.bin", np.asarray([crc], dtype=np.uint32))
    store = DocMetadataMMap(tmp_path)
    with pytest.raises(RuntimeError, match="doc_metadata korrupt.*JSON nicht dekodierbar.*doc 0"):
        store[0]
    store.close()


def test_legacy_unframed_garbage_raises(tmp_path: Path) -> None:
    # Entry without frame magic that is not valid JSON -> corruption, raise.
    garbage = b"\x00\x01\x02 definitely not json"
    (tmp_path / "doc_metadata.mmap").write_bytes(garbage)
    _write_array_with_count(
        tmp_path / "doc_metadata.idx.bin", np.asarray([0, len(garbage)], dtype=np.uint64)
    )
    store = DocMetadataMMap(tmp_path)
    with pytest.raises(RuntimeError, match="doc_metadata korrupt.*JSON nicht dekodierbar"):
        store[0]
    store.close()
