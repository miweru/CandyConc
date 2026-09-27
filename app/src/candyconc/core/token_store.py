"""
High-Performance Token Store for Collocation Engine.

Provides mmap-backed token attributes with SVB-compressed streams and roaring postings:
- No string operations in hot path
- Sequential memory access patterns
"""
from __future__ import annotations

import mmap
import struct
import logging
import json
import os
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Iterator, Tuple, Optional, Dict
import numpy as np
import threading

from .fast_index_native import make_svb_range_decoder, decode_svb_block, decode_roar_positions, roar_advance_to, roar_contains
from . import index_format

LOGGER = logging.getLogger(__name__)


def _as_i32_c_contig(values: np.ndarray) -> np.ndarray:
    if isinstance(values, np.ndarray) and values.dtype == np.int32 and values.flags.c_contiguous:
        return values
    return np.ascontiguousarray(values, dtype=np.int32)


def _check_offsets_within(
    offsets: np.ndarray, capacity: int, *, label: str
) -> None:
    """Fail-closed bounds guard for a CSR-style offsets array (DT-CORE-LIFECYCLE).

    The decoders index a separate mmapped/array payload using these offsets.
    A truncated or corrupt payload would otherwise be read OUT OF BOUNDS by the
    Cython decoders. We require, before any decode:

    * ``offsets[0] == 0`` (the first block/type starts at the payload origin),
    * non-decreasing offsets (monotone CSR contract), and
    * ``offsets[-1] <= capacity`` (the last offset fits inside the payload).

    ``capacity`` is the payload size in the offsets' own unit (bytes for an
    mmap, element count for an array). Raises ``RuntimeError`` ("Daten
    unvollständig", with a rebuild hint) on any violation.
    """
    if offsets is None or offsets.size == 0:
        return
    first = int(offsets[0])
    last = int(offsets[-1])
    if first != 0:
        raise RuntimeError(
            f"{label}: Daten unvollständig (Offset-Start {first} != 0). "
            "Bitte Index neu bauen."
        )
    if last > int(capacity):
        raise RuntimeError(
            f"{label}: Daten unvollständig (Offset-Ende {last} > Größe "
            f"{int(capacity)}). Bitte Index neu bauen."
        )
    # Monotonicity: a single np.diff pass; any negative step is corruption.
    if offsets.size > 1:
        diffs = np.diff(offsets.astype(np.int64, copy=False))
        if np.any(diffs < 0):
            raise RuntimeError(
                f"{label}: Daten unvollständig (Offsets nicht monoton). "
                "Bitte Index neu bauen."
            )


class SvbStream:
    def __init__(
        self,
        offsets: np.ndarray,
        data: memoryview,
        block_size: int,
        token_count: int,
    ):
        self.offsets = offsets
        self.data = data
        self.block_size = int(block_size)
        self.token_count = int(token_count)
        self._local = threading.local()
        self._packed_cache: "OrderedDict[tuple[int, int, int, int, bytes], np.ndarray]" = OrderedDict()
        self._packed_cache_bytes = 0
        self._packed_cache_max_bytes = int(os.environ.get("CANDYCONC_PACKED_RANGE_CACHE_MAX_BYTES", str(64 * 1024 * 1024)))
        self._packed_cache_max_entries = int(os.environ.get("CANDYCONC_PACKED_RANGE_CACHE_MAX_ENTRIES", "64"))
        self._packed_cache_min_bytes = int(os.environ.get("CANDYCONC_PACKED_RANGE_CACHE_MIN_BYTES", "4096"))
        self._packed_cache_lock = threading.Lock()

    def _get_local_cache(self):
        if not hasattr(self._local, "cache"):
            self._local.cache = None
            self._local.cache_block = -1
            self._local.range_decoder = make_svb_range_decoder()
            self._local.decode_reuse = getattr(
                self._local.range_decoder,
                "decode_ranges_packed_sorted_known_reuse_i32",
                None,
            )
        return self._local

    def _load_block(self, block_idx: int) -> np.ndarray:
        block = decode_svb_block(
            self.offsets,
            self.data,
            int(block_idx),
            int(self.block_size),
            int(self.token_count),
        )
        loc = self._get_local_cache()
        loc.cache_block = int(block_idx)
        loc.cache = block
        return block

    def _packed_cache_key(self, starts_i32: np.ndarray, ends_i32: np.ndarray, total_len: int) -> tuple[int, int, int, int, bytes]:
        digest = hashlib.blake2b(digest_size=8)
        digest.update(memoryview(starts_i32).cast("B"))
        digest.update(memoryview(ends_i32).cast("B"))
        return (
            int(starts_i32.shape[0]),
            int(total_len),
            int(starts_i32[0]),
            int(ends_i32[-1]),
            digest.digest(),
        )

    def _packed_cache_get(self, key: tuple[int, int, int, int, bytes]) -> Optional[np.ndarray]:
        if self._packed_cache_max_bytes <= 0 or self._packed_cache_max_entries <= 0:
            return None
        with self._packed_cache_lock:
            cached = self._packed_cache.pop(key, None)
            if cached is None:
                return None
            self._packed_cache[key] = cached
            return cached

    def _packed_cache_set(self, key: tuple[int, int, int, int, bytes], values: np.ndarray) -> np.ndarray:
        if self._packed_cache_max_bytes <= 0 or self._packed_cache_max_entries <= 0:
            return values
        size = int(getattr(values, "nbytes", 0))
        if size < self._packed_cache_min_bytes or size > self._packed_cache_max_bytes:
            return values
        with self._packed_cache_lock:
            prev = self._packed_cache.pop(key, None)
            if prev is not None:
                self._packed_cache_bytes -= int(prev.nbytes)
            self._packed_cache[key] = values
            self._packed_cache_bytes += size
            while self._packed_cache and (
                self._packed_cache_bytes > self._packed_cache_max_bytes
                or len(self._packed_cache) > self._packed_cache_max_entries
            ):
                _, evicted = self._packed_cache.popitem(last=False)
                self._packed_cache_bytes -= int(evicted.nbytes)
        return values

    def get(self, pos: int) -> int:
        if pos < 0 or pos >= self.token_count:
            return 0
        block_idx = pos // self.block_size
        loc = self._get_local_cache()
        if loc.cache is None or loc.cache_block != block_idx:
            block = self._load_block(block_idx)
        else:
            block = loc.cache
        local = pos - block_idx * self.block_size
        if local >= block.shape[0]:
            return 0
        return int(block[local])

    def get_range(self, start: int, end: int) -> np.ndarray:
        if end <= start:
            return np.zeros(0, dtype=np.uint32)
        if start < 0:
            start = 0
        if end > self.token_count:
            end = self.token_count
        length = end - start
        out = np.empty(length, dtype=np.uint32)
        cursor = 0
        pos = start
        while pos < end:
            block_idx = pos // self.block_size
            block_start = block_idx * self.block_size
            loc = self._get_local_cache()
            if loc.cache is None or loc.cache_block != block_idx:
                block = self._load_block(block_idx)
            else:
                block = loc.cache
            block_end = min(block_start + block.shape[0], self.token_count)
            take_end = min(end, block_end)
            take = take_end - pos
            out[cursor : cursor + take] = block[pos - block_start : pos - block_start + take]
            cursor += take
            pos = take_end
        return out

    def get_range_i32(self, start: int, end: int) -> np.ndarray:
        if end <= start:
            return np.zeros(0, dtype=np.int32)
        if start < 0:
            start = 0
        if end > self.token_count:
            end = self.token_count
        loc = self._get_local_cache()
        return loc.range_decoder.decode_range_i32(
            self.offsets,
            self.data,
            int(self.block_size),
            int(self.token_count),
            int(start),
            int(end),
        )

    def get_ranges_packed_i32(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts_i32 = _as_i32_c_contig(starts)
        ends_i32 = _as_i32_c_contig(ends)
        if starts_i32.shape != ends_i32.shape:
            raise ValueError("starts und ends müssen gleich geformt sein")
        if starts_i32.size == 0:
            return np.zeros(0, dtype=np.int32)
        loc = self._get_local_cache()
        return loc.range_decoder.decode_ranges_packed_i32(
            self.offsets,
            self.data,
            int(self.block_size),
            int(self.token_count),
            starts_i32,
            ends_i32,
        )


    def get_ranges_packed_sorted_i32(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts_i32 = _as_i32_c_contig(starts)
        ends_i32 = _as_i32_c_contig(ends)
        if starts_i32.shape != ends_i32.shape:
            raise ValueError("starts und ends müssen gleich geformt sein")
        if starts_i32.size == 0:
            return np.zeros(0, dtype=np.int32)
        loc = self._get_local_cache()
        return loc.range_decoder.decode_ranges_packed_sorted_i32(
            self.offsets,
            self.data,
            int(self.block_size),
            int(self.token_count),
            starts_i32,
            ends_i32,
        )

    def get_ranges_packed_sorted_known_i32(self, starts: np.ndarray, ends: np.ndarray, total_len: int) -> np.ndarray:
        starts_i32 = _as_i32_c_contig(starts)
        ends_i32 = _as_i32_c_contig(ends)
        if starts_i32.shape != ends_i32.shape:
            raise ValueError("starts und ends müssen gleich geformt sein")
        if starts_i32.size == 0 or total_len <= 0:
            return np.zeros(0, dtype=np.int32)
        return self.get_ranges_packed_sorted_known_i32_fast(starts_i32, ends_i32, int(total_len))

    def get_ranges_packed_sorted_known_i32_fast(self, starts_i32: np.ndarray, ends_i32: np.ndarray, total_len: int) -> np.ndarray:
        if starts_i32.size == 0 or total_len <= 0:
            return np.zeros(0, dtype=np.int32)
        use_cache = (
            self._packed_cache_max_bytes > 0
            and self._packed_cache_max_entries > 0
            and int(total_len) * 4 >= self._packed_cache_min_bytes
            and int(total_len) * 4 <= self._packed_cache_max_bytes
        )
        cache_key = None
        if use_cache:
            cache_key = self._packed_cache_key(starts_i32, ends_i32, int(total_len))
            cached = self._packed_cache_get(cache_key)
            if cached is not None:
                return cached
        loc = self._get_local_cache()
        decode_reuse = loc.decode_reuse
        if use_cache:
            out = loc.range_decoder.decode_ranges_packed_sorted_known_i32(
                self.offsets,
                self.data,
                int(self.block_size),
                int(self.token_count),
                starts_i32,
                ends_i32,
                int(total_len),
            )
            return self._packed_cache_set(cache_key, out)
        if callable(decode_reuse):
            out = decode_reuse(
                self.offsets,
                self.data,
                int(self.block_size),
                int(self.token_count),
                starts_i32,
                ends_i32,
                int(total_len),
            )
            return out
        return loc.range_decoder.decode_ranges_packed_sorted_known_i32(
            self.offsets,
            self.data,
            int(self.block_size),
            int(self.token_count),
            starts_i32,
            ends_i32,
            int(total_len),
        )

    def iter_range(self, start: int, end: int) -> Iterator[np.ndarray]:
        if end <= start:
            return
        if start < 0:
            start = 0
        if end > self.token_count:
            end = self.token_count
        pos = start
        while pos < end:
            block_idx = pos // self.block_size
            block_start = block_idx * self.block_size
            loc = self._get_local_cache()
            if loc.cache is None or loc.cache_block != block_idx:
                block = self._load_block(block_idx)
            else:
                block = loc.cache
            block_end = min(block_start + block.shape[0], self.token_count)
            take_end = min(end, block_end)
            yield block[pos - block_start : take_end - block_start]
            pos = take_end


class TokenStore:
    """
    Memory-mapped token attribute arrays.
    
    Word and lemma streams are stored as SVB-compressed blocks, other
    positional attributes remain flat u32 arrays. Tokens are referenced
    by position (0-indexed).
    """
    
    BLOCK_SIZE = 4096  # Tokens per block for cache-friendly access
    
    def __init__(self, base_path: Path):
        """
        Initialize TokenStore from a directory containing binary files.
        
        Expected files:
        - word_ids.svb.ptr.bin / word_ids.svb.data.bin
        - lemma_ids.svb.ptr.bin / lemma_ids.svb.data.bin (optional)
        - pos_ids.bin (optional)
        - meta.bin (token count, segment info)
        """
        self.base_path = Path(base_path)
        self._pos_ids: Optional[np.ndarray] = None
        self._morph_ids: Optional[np.ndarray] = None
        self._ent_ids: Optional[np.ndarray] = None
        self._rel_ids: Optional[np.ndarray] = None
        self._head_ids: Optional[np.ndarray] = None
        self._word_stream: Optional[SvbStream] = None
        self._lemma_stream: Optional[SvbStream] = None
        self._token_count: int = 0
        self._mmap_handles: list = []
        self._postings_offsets: Optional[np.ndarray] = None
        self._postings_positions: Optional[np.ndarray] = None
        self._lemma_postings_offsets: Optional[np.ndarray] = None
        self._lemma_postings_positions: Optional[np.ndarray] = None
        self._pos_postings_offsets: Optional[np.ndarray] = None
        self._pos_postings_positions: Optional[np.ndarray] = None
        self._morph_postings_offsets: Optional[np.ndarray] = None
        self._morph_postings_positions: Optional[np.ndarray] = None
        self._ent_postings_offsets: Optional[np.ndarray] = None
        self._ent_postings_positions: Optional[np.ndarray] = None
        self._rel_postings_offsets: Optional[np.ndarray] = None
        self._rel_postings_positions: Optional[np.ndarray] = None
        self._word_postings_roar_offsets: Optional[np.ndarray] = None
        self._word_postings_roar_data: Optional[mmap.mmap] = None
        self._lemma_postings_roar_offsets: Optional[np.ndarray] = None
        self._lemma_postings_roar_data: Optional[mmap.mmap] = None
        self._pos_postings_roar_offsets: Optional[np.ndarray] = None
        self._pos_postings_roar_data: Optional[mmap.mmap] = None
        self._morph_postings_roar_offsets: Optional[np.ndarray] = None
        self._morph_postings_roar_data: Optional[mmap.mmap] = None
        self._ent_postings_roar_offsets: Optional[np.ndarray] = None
        self._ent_postings_roar_data: Optional[mmap.mmap] = None
        self._rel_postings_roar_offsets: Optional[np.ndarray] = None
        self._rel_postings_roar_data: Optional[mmap.mmap] = None
        self._word_docset_offsets: Optional[np.ndarray] = None
        self._word_docset_ids: Optional[np.ndarray] = None
        self._lemma_docset_offsets: Optional[np.ndarray] = None
        self._lemma_docset_ids: Optional[np.ndarray] = None
        self._pos_docset_offsets: Optional[np.ndarray] = None
        self._pos_docset_ids: Optional[np.ndarray] = None
        self._pos_sentence_offsets: Optional[np.ndarray] = None
        self._pos_sentence_ids: Optional[np.ndarray] = None
        self._word_block_top_offsets: Optional[np.ndarray] = None
        self._word_block_top_ids: Optional[np.ndarray] = None
        self._word_block_top_counts: Optional[np.ndarray] = None
        self._word_block_top_totals: Optional[np.ndarray] = None
        self._word_block_top_size: int = 0
        self._word_block_top_k: int = 0
        self._lemma_block_top_offsets: Optional[np.ndarray] = None
        self._lemma_block_top_ids: Optional[np.ndarray] = None
        self._lemma_block_top_counts: Optional[np.ndarray] = None
        self._lemma_block_top_totals: Optional[np.ndarray] = None
        self._lemma_block_top_size: int = 0
        self._lemma_block_top_k: int = 0
        self._dense_bitsets: Dict[str, Tuple[np.ndarray, np.ndarray, int, Dict[int, int]]] = {}
        self._postings_cache: "OrderedDict[tuple[str, int], np.ndarray]" = OrderedDict()
        self._postings_cache_bytes: int = 0
        self._postings_cache_max_bytes: int = int(os.environ.get("CANDYCONC_POSTINGS_CACHE_MAX_BYTES", str(128 * 1024 * 1024)))
        self._postings_cache_max_entries: int = int(os.environ.get("CANDYCONC_POSTINGS_CACHE_MAX_ENTRIES", "256"))
        self._postings_cache_lock = threading.Lock()
        
    @staticmethod
    def _madvise(mm: mmap.mmap, advice: int) -> None:
        if hasattr(mm, "madvise"):
            try:
                mm.madvise(advice)
            except (ValueError, OSError):
                LOGGER.exception("madvise fehlgeschlagen für TokenStore mmap")
                raise RuntimeError("madvise fehlgeschlagen für TokenStore mmap")

    def _guard_offsets_or_release(
        self,
        offsets: np.ndarray,
        capacity: int,
        *,
        label: str,
        mm: Optional[mmap.mmap] = None,
        view: Optional[memoryview] = None,
    ) -> None:
        """Run the bounds guard; on violation release the just-opened mapping.

        Keeps the fail-closed load from LEAKING the fd it opened to size-check
        the payload: any view is released and the mmap closed + removed from
        ``_mmap_handles`` before the guard's ``RuntimeError`` propagates.
        """
        try:
            _check_offsets_within(offsets, capacity, label=label)
        except RuntimeError:
            if view is not None:
                try:
                    view.release()
                except Exception:
                    pass
            if mm is not None:
                try:
                    self._mmap_handles.remove(mm)
                except ValueError:
                    pass
                try:
                    mm.close()
                except Exception:
                    pass
            raise
        
    def load(self) -> None:
        """Load all attribute arrays via mmap."""
        meta_path = self.base_path / "meta.bin"
        if meta_path.exists():
            with open(meta_path, "rb") as f:
                self._token_count = struct.unpack(
                    index_format.COUNT_HEADER_STRUCT, f.read(index_format.COUNT_HEADER_SIZE)
                )[0]

        self._word_stream = self._load_svb_stream("word")
        if self._word_stream is None:
            raise RuntimeError("word_ids.svb fehlt oder ist ungültig. Bitte Index neu bauen.")
        self._lemma_stream = self._load_svb_stream("lemma")
        self._pos_ids = self._load_array("pos_ids.bin", mmap.MADV_SEQUENTIAL)
        self._morph_ids = self._load_array("morph_ids.bin", mmap.MADV_SEQUENTIAL)
        self._ent_ids = self._load_array("ent_ids.bin", mmap.MADV_SEQUENTIAL)
        self._rel_ids = self._load_array("rel_ids.bin", mmap.MADV_SEQUENTIAL)
        self._head_ids = self._load_array_typed("head_ids.bin", np.int32, mmap.MADV_SEQUENTIAL)
        self._word_postings_roar_offsets, self._word_postings_roar_data = self._load_roaring_postings("word")
        self._lemma_postings_roar_offsets, self._lemma_postings_roar_data = self._load_roaring_postings("lemma")
        self._pos_postings_roar_offsets, self._pos_postings_roar_data = self._load_roaring_postings("pos")
        self._morph_postings_roar_offsets, self._morph_postings_roar_data = self._load_roaring_postings("morph")
        self._ent_postings_roar_offsets, self._ent_postings_roar_data = self._load_roaring_postings("ent")
        self._rel_postings_roar_offsets, self._rel_postings_roar_data = self._load_roaring_postings("rel")
        self._word_docset_offsets, self._word_docset_ids = self._load_unit_index(
            "word_docset.ptr.bin", "word_docset.bin"
        )
        self._lemma_docset_offsets, self._lemma_docset_ids = self._load_unit_index(
            "lemma_docset.ptr.bin", "lemma_docset.bin"
        )
        self._pos_docset_offsets, self._pos_docset_ids = self._load_unit_index(
            "pos_docset.ptr.bin", "pos_docset.bin"
        )
        self._pos_sentence_offsets, self._pos_sentence_ids = self._load_unit_index(
            "pos_sentence.ptr.bin", "pos_sentence.bin"
        )
        (
            self._word_block_top_offsets,
            self._word_block_top_ids,
            self._word_block_top_counts,
            self._word_block_top_totals,
            self._word_block_top_size,
            self._word_block_top_k,
        ) = self._load_block_top("word")
        (
            self._lemma_block_top_offsets,
            self._lemma_block_top_ids,
            self._lemma_block_top_counts,
            self._lemma_block_top_totals,
            self._lemma_block_top_size,
            self._lemma_block_top_k,
        ) = self._load_block_top("lemma")
        # Dense bitsets (optional)
        for attr in ("word", "lemma", "pos", "ent", "rel"):
            self._load_dense_bitset(attr)
        
    def _load_array(self, filename: str, advice: Optional[int] = None) -> Optional[np.ndarray]:
        """Load a single attribute array via mmap (u32)."""
        return self._load_array_typed(filename, np.uint32, advice)

    def _load_array_typed(
        self, filename: str, dtype: np.dtype, advice: Optional[int] = None
    ) -> Optional[np.ndarray]:
        """Load a single attribute array via mmap."""
        path = self.base_path / filename
        if not path.exists():
            return None
            
        with open(path, "rb") as f:
            # Read header (count-prefixed array; format in core.index_format)
            header = f.read(index_format.COUNT_HEADER_SIZE)
            if len(header) < index_format.COUNT_HEADER_SIZE:
                return None
            count = struct.unpack(index_format.COUNT_HEADER_STRUCT, header)[0]

            # mmap the data portion
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            if advice is not None:
                self._madvise(mm, advice)
            self._mmap_handles.append(mm)

            # Create numpy array view (zero-copy)
            arr = np.frombuffer(mm, dtype=dtype, offset=index_format.COUNT_HEADER_SIZE, count=count)
        return arr

    def _load_dense_bitset(self, attr: str) -> None:
        meta_path = self.base_path / f"{attr}_dense_bitset.meta.json"
        ids_path = self.base_path / f"{attr}_dense_bitset.ids.bin"
        data_path = self.base_path / f"{attr}_dense_bitset.data.bin"
        if not (meta_path.exists() and ids_path.exists() and data_path.exists()):
            return
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            bitset_bytes = int(meta.get("bitset_bytes", 0))
        except Exception:
            return
        if bitset_bytes <= 0:
            return
        ids = self._load_array_typed(ids_path.name, np.uint32, mmap.MADV_RANDOM)
        data = self._load_array_typed(data_path.name, np.uint8, mmap.MADV_RANDOM)
        if ids is None or data is None:
            return
        expected = int(ids.size) * int(bitset_bytes)
        if int(data.size) < expected:
            return
        id_to_idx = {int(tid): i for i, tid in enumerate(ids.tolist())}
        self._dense_bitsets[attr] = (ids, data, bitset_bytes, id_to_idx)

    def _load_svb_stream(self, name: str) -> Optional[SvbStream]:
        ptr_path = self.base_path / f"{name}_ids.svb.ptr.bin"
        data_path = self.base_path / f"{name}_ids.svb.data.bin"
        if not (ptr_path.exists() and data_path.exists()):
            return None
        with open(ptr_path, "rb") as f:
            header = f.read(index_format.SVB_PTR_HEADER_SIZE)
            if len(header) != index_format.SVB_PTR_HEADER_SIZE:
                return None
            n_blocks, block_size, hdr_token_count = struct.unpack(
                index_format.SVB_PTR_HEADER_STRUCT, header
            )
            offsets_bytes = f.read((n_blocks + 1) * 8)
            if len(offsets_bytes) != (n_blocks + 1) * 8:
                return None
            offsets = np.frombuffer(offsets_bytes, dtype=np.uint64)
        with open(data_path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self._madvise(mm, mmap.MADV_RANDOM)
            self._mmap_handles.append(mm)
            data_view = memoryview(mm)
        # Fail-closed bounds guard (DT-CORE-LIFECYCLE): the SVB block decoder
        # indexes ``data`` using ``offsets``; a truncated data file would be read
        # out of bounds. Require offsets[0]==0, monotone, offsets[-1]<=data size.
        self._guard_offsets_or_release(
            offsets, mm.size(), label=f"{name}_ids.svb", mm=mm, view=data_view
        )
        # Token-count provenance (D2). The SVB ptr header carries the exact
        # token_count (3rd field). meta.bin, when present, is authoritative;
        # a disagreement between meta.bin and the stream header means the
        # index is inconsistent and must be rebuilt. When meta.bin is absent
        # we trust the header's token_count rather than n_blocks*block_size,
        # which would over-count by up to (block_size - 1) tokens in the last
        # block and corrupt every position-dependent computation.
        hdr_token_count = int(hdr_token_count)
        if self._token_count > 0:
            if hdr_token_count > 0 and hdr_token_count != self._token_count:
                raise RuntimeError(
                    f"TokenStore inkonsistent: {name}_ids.svb meldet "
                    f"token_count {hdr_token_count}, meta.bin meldet "
                    f"{self._token_count}. Bitte Index neu bauen."
                )
            token_count = self._token_count
        elif hdr_token_count > 0:
            token_count = hdr_token_count
            # Propagate the stream header's token_count when meta.bin is
            # absent so downstream consumers see a consistent value.
            self._token_count = hdr_token_count
        else:
            token_count = int(n_blocks * block_size)
        return SvbStream(offsets, data_view, int(block_size), token_count)

    def _load_roaring_postings(
        self, name: str
    ) -> tuple[Optional[np.ndarray], Optional[mmap.mmap]]:
        ptr_path = self.base_path / f"{name}_postings.r32.ptr.bin"
        data_path = self.base_path / f"{name}_postings.r32.data.bin"
        if not (ptr_path.exists() and data_path.exists()):
            return (None, None)
        offsets = self._load_array_typed(ptr_path.name, np.uint64, mmap.MADV_RANDOM)
        if offsets is None:
            return (None, None)
        with open(data_path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self._madvise(mm, mmap.MADV_RANDOM)
            self._mmap_handles.append(mm)
        # Fail-closed bounds guard (DT-CORE-LIFECYCLE): roaring decoders index
        # ``mm`` via per-type byte offsets; guard against a truncated data file.
        self._guard_offsets_or_release(
            offsets, mm.size(), label=f"{name}_postings.r32", mm=mm
        )
        return (offsets, mm)

    def _load_unit_index(
        self, ptr_name: str, data_name: str
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        ptr_path = self.base_path / ptr_name
        data_path = self.base_path / data_name
        if not (ptr_path.exists() and data_path.exists()):
            return (None, None)
        offsets = self._load_array_typed(ptr_name, np.uint64, mmap.MADV_RANDOM)
        ids = self._load_array_typed(data_name, np.uint32, mmap.MADV_RANDOM)
        if offsets is None or ids is None:
            return (None, None)
        # Fail-closed bounds guard (DT-CORE-LIFECYCLE): offsets index into the
        # ``ids`` array; a truncated ids file would be sliced out of bounds.
        _check_offsets_within(offsets, int(ids.size), label=ptr_name)
        return (offsets, ids)

    def _load_block_top(
        self, name: str
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray], int, int]:
        ptr_path = self.base_path / f"{name}_block_top.ptr.bin"
        ids_path = self.base_path / f"{name}_block_top.ids.bin"
        cnt_path = self.base_path / f"{name}_block_top.cnt.bin"
        tot_path = self.base_path / f"{name}_block_top.tot.bin"
        if not (ptr_path.exists() and ids_path.exists() and cnt_path.exists() and tot_path.exists()):
            return (None, None, None, None, 0, 0)
        try:
            with open(ptr_path, "rb") as f:
                header = f.read(index_format.BLOCK_TOP_HEADER_SIZE)
                if len(header) != index_format.BLOCK_TOP_HEADER_SIZE:
                    return (None, None, None, None, 0, 0)
                magic, version, block_size, top_k, n_blocks = struct.unpack(
                    index_format.BLOCK_TOP_HEADER_STRUCT, header
                )
                if magic != index_format.BLOCK_TOP_MAGIC or version != index_format.BLOCK_TOP_VERSION:
                    return (None, None, None, None, 0, 0)
                offsets_bytes = f.read((n_blocks + 1) * 8)
                if len(offsets_bytes) != (n_blocks + 1) * 8:
                    return (None, None, None, None, 0, 0)
                offsets = np.frombuffer(offsets_bytes, dtype=np.uint64)
            ids = self._load_array_typed(ids_path.name, np.uint32, mmap.MADV_RANDOM)
            cnt = self._load_array_typed(cnt_path.name, np.uint32, mmap.MADV_RANDOM)
            tot = self._load_array_typed(tot_path.name, np.uint32, mmap.MADV_RANDOM)
            if ids is None or cnt is None or tot is None:
                return (None, None, None, None, 0, 0)
        except Exception:
            return (None, None, None, None, 0, 0)
        # Fail-closed bounds guard (DT-CORE-LIFECYCLE): block-top offsets index
        # into the ``ids``/``cnt`` arrays. Validate AFTER the broad try/except so
        # a genuine truncation raises (rebuild) rather than being silently
        # swallowed into a "no block-top" downgrade.
        _check_offsets_within(offsets, int(ids.size), label=f"{name}_block_top.ptr")
        return (offsets, ids, cnt, tot, int(block_size), int(top_k))
            
    def close(self) -> None:
        """Close all mmap handles, best-effort (DT-CORE-LIFECYCLE).

        Every numpy view / ``memoryview`` that aliases a mmap must be dropped
        BEFORE the underlying ``mmap`` is closed, otherwise CPython raises
        ``BufferError`` ("cannot close exported pointers exist"). We therefore
        release the SVB stream data views, the postings/array views and the
        decode caches first, then close each handle. Idempotent; never raises.
        """
        # 1) Release SVB stream data memoryviews (they alias the data mmaps).
        for stream in (self._word_stream, self._lemma_stream):
            if stream is not None:
                try:
                    stream.data = None  # type: ignore[assignment]
                except Exception:
                    pass
                try:
                    stream._packed_cache.clear()
                except Exception:
                    pass
        self._word_stream = None
        self._lemma_stream = None
        # 2) Drop every numpy array / mmap reference that aliases a mapping.
        for attr in (
            "_pos_ids", "_morph_ids", "_ent_ids", "_rel_ids", "_head_ids",
            "_postings_offsets", "_postings_positions",
            "_lemma_postings_offsets", "_lemma_postings_positions",
            "_pos_postings_offsets", "_pos_postings_positions",
            "_morph_postings_offsets", "_morph_postings_positions",
            "_ent_postings_offsets", "_ent_postings_positions",
            "_rel_postings_offsets", "_rel_postings_positions",
            "_word_postings_roar_offsets", "_word_postings_roar_data",
            "_lemma_postings_roar_offsets", "_lemma_postings_roar_data",
            "_pos_postings_roar_offsets", "_pos_postings_roar_data",
            "_morph_postings_roar_offsets", "_morph_postings_roar_data",
            "_ent_postings_roar_offsets", "_ent_postings_roar_data",
            "_rel_postings_roar_offsets", "_rel_postings_roar_data",
            "_word_docset_offsets", "_word_docset_ids",
            "_lemma_docset_offsets", "_lemma_docset_ids",
            "_pos_docset_offsets", "_pos_docset_ids",
            "_pos_sentence_offsets", "_pos_sentence_ids",
            "_word_block_top_offsets", "_word_block_top_ids",
            "_word_block_top_counts", "_word_block_top_totals",
            "_lemma_block_top_offsets", "_lemma_block_top_ids",
            "_lemma_block_top_counts", "_lemma_block_top_totals",
        ):
            try:
                setattr(self, attr, None)
            except Exception:
                pass
        try:
            self._dense_bitsets.clear()
        except Exception:
            pass
        with self._postings_cache_lock:
            self._postings_cache.clear()
            self._postings_cache_bytes = 0
        # 3) Now close the handles. Any lingering export is swallowed so close
        # stays best-effort (a leaked fd is preferable to a raised teardown).
        for mm in self._mmap_handles:
            try:
                mm.close()
            except Exception:
                pass
        self._mmap_handles.clear()
        
    @property
    def token_count(self) -> int:
        if self._token_count:
            return self._token_count
        if self._word_stream is not None:
            return self._word_stream.token_count
        return 0

    @property
    def word_stream(self) -> SvbStream:
        if self._word_stream is None:
            raise RuntimeError("word_ids.svb fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._word_stream

    @property
    def lemma_stream(self) -> SvbStream:
        if self._lemma_stream is None:
            raise RuntimeError("lemma_ids.svb fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._lemma_stream

    @property
    def pos_ids(self) -> np.ndarray:
        if self._pos_ids is None:
            raise RuntimeError("pos_ids.bin fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._pos_ids

    @property
    def morph_ids(self) -> np.ndarray:
        if self._morph_ids is None:
            raise RuntimeError("morph_ids.bin fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._morph_ids

    @property
    def ent_ids(self) -> np.ndarray:
        if self._ent_ids is None:
            raise RuntimeError("ent_ids.bin fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._ent_ids

    @property
    def rel_ids(self) -> np.ndarray:
        if self._rel_ids is None:
            raise RuntimeError("rel_ids.bin fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._rel_ids

    @property
    def head_ids(self) -> np.ndarray:
        if self._head_ids is None:
            raise RuntimeError("head_ids.bin fehlt oder ist ungültig. Bitte Index neu bauen.")
        return self._head_ids
        
    def get_word_id(self, pos: int) -> int:
        """Get word ID at position (O(1))."""
        if self._word_stream is None:
            return 0
        return self._word_stream.get(pos)
        
    def get_lemma_id(self, pos: int) -> int:
        """Get lemma ID at position (O(1))."""
        if self._lemma_stream is None:
            return 0
        return self._lemma_stream.get(pos)
        
    def get_pos_id(self, pos: int) -> int:
        """Get POS ID at position (O(1))."""
        if self._pos_ids is None or pos >= len(self._pos_ids):
            return 0
        return int(self._pos_ids[pos])
        
    def get_word_ids_range(self, start: int, end: int) -> np.ndarray:
        """
        Get word IDs for a range [start, end) as numpy array.
        This is the hot path - decoded from SVB stream.
        """
        if self._word_stream is None:
            return np.array([], dtype=np.uint32)
        return self._word_stream.get_range(start, end)

    def get_word_ids_range_i32(self, start: int, end: int) -> np.ndarray:
        if self._word_stream is None:
            return np.array([], dtype=np.int32)
        return self._word_stream.get_range_i32(start, end)

    def get_lemma_ids_range(self, start: int, end: int) -> np.ndarray:
        if self._lemma_stream is None:
            return np.array([], dtype=np.uint32)
        return self._lemma_stream.get_range(start, end)

    def get_lemma_ids_range_i32(self, start: int, end: int) -> np.ndarray:
        if self._lemma_stream is None:
            return np.array([], dtype=np.int32)
        return self._lemma_stream.get_range_i32(start, end)

    def iter_word_ids_range(self, start: int, end: int) -> Iterator[np.ndarray]:
        if end <= start:
            return
        if self._word_stream is None:
            return
        for block in self._word_stream.iter_range(start, end):
            yield block
        
    def iter_blocks(self, start: int = 0, end: Optional[int] = None) -> Iterator[Tuple[int, np.ndarray]]:
        """
        Iterate over blocks of word IDs for cache-efficient processing.
        Yields (block_start, word_ids_array) tuples.
        """
        if self._word_stream is None:
            return
        end = end or self.token_count
        pos = start
        while pos < end:
            block_end = min(pos + self.BLOCK_SIZE, end)
            yield pos, self._word_stream.get_range(pos, block_end)
            pos = block_end

    def _postings_cache_get(self, attr: str, type_id: int) -> Optional[np.ndarray]:
        key = (attr, int(type_id))
        with self._postings_cache_lock:
            cached = self._postings_cache.pop(key, None)
            if cached is None:
                return None
            self._postings_cache[key] = cached
            return cached

    def _postings_cache_set(self, attr: str, type_id: int, positions: np.ndarray) -> np.ndarray:
        if self._postings_cache_max_bytes <= 0 or self._postings_cache_max_entries <= 0:
            return positions
        size = int(positions.nbytes)
        if size <= 0 or size > self._postings_cache_max_bytes:
            return positions
        key = (attr, int(type_id))
        with self._postings_cache_lock:
            prev = self._postings_cache.pop(key, None)
            if prev is not None:
                self._postings_cache_bytes -= int(prev.nbytes)
            self._postings_cache[key] = positions
            self._postings_cache_bytes += size
            while self._postings_cache and (
                self._postings_cache_bytes > self._postings_cache_max_bytes
                or len(self._postings_cache) > self._postings_cache_max_entries
            ):
                _, evicted = self._postings_cache.popitem(last=False)
                self._postings_cache_bytes -= int(evicted.nbytes)
        return positions

    def _decode_positions_cached(
        self,
        attr: str,
        type_id: int,
        offsets: Optional[np.ndarray],
        data: Optional[mmap.mmap],
        missing_msg: str,
    ) -> np.ndarray:
        if type_id <= 0:
            return np.array([], dtype=np.uint32)
        cached = self._postings_cache_get(attr, type_id)
        if cached is not None:
            return cached
        if offsets is None or data is None:
            raise RuntimeError(missing_msg)
        decoded = decode_roar_positions(offsets, data, int(type_id))
        return self._postings_cache_set(attr, type_id, decoded)

    def get_positions_for_word_id(self, word_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "word",
            word_id,
            self._word_postings_roar_offsets,
            self._word_postings_roar_data,
            "Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def get_positions_for_lemma_id(self, lemma_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "lemma",
            lemma_id,
            self._lemma_postings_roar_offsets,
            self._lemma_postings_roar_data,
            "Lemma Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def get_positions_for_pos_id(self, pos_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "pos",
            pos_id,
            self._pos_postings_roar_offsets,
            self._pos_postings_roar_data,
            "POS Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def get_positions_for_morph_id(self, morph_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "morph",
            morph_id,
            self._morph_postings_roar_offsets,
            self._morph_postings_roar_data,
            "Morph Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def get_positions_for_ent_id(self, ent_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "ent",
            ent_id,
            self._ent_postings_roar_offsets,
            self._ent_postings_roar_data,
            "Ent Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def get_positions_for_rel_id(self, rel_id: int) -> np.ndarray:
        return self._decode_positions_cached(
            "rel",
            rel_id,
            self._rel_postings_roar_offsets,
            self._rel_postings_roar_data,
            "Rel Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.",
        )

    def advance_word_position(self, word_id: int, target: int) -> int:
        if word_id <= 0:
            return -1
        if self._word_postings_roar_offsets is None or self._word_postings_roar_data is None:
            raise RuntimeError("Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return int(roar_advance_to(self._word_postings_roar_offsets, self._word_postings_roar_data, int(word_id), int(target)))

    def advance_lemma_position(self, lemma_id: int, target: int) -> int:
        if lemma_id <= 0:
            return -1
        if self._lemma_postings_roar_offsets is None or self._lemma_postings_roar_data is None:
            raise RuntimeError("Lemma Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return int(roar_advance_to(self._lemma_postings_roar_offsets, self._lemma_postings_roar_data, int(lemma_id), int(target)))

    def advance_pos_position(self, pos_id: int, target: int) -> int:
        if pos_id <= 0:
            return -1
        if self._pos_postings_roar_offsets is None or self._pos_postings_roar_data is None:
            raise RuntimeError("POS Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return int(roar_advance_to(self._pos_postings_roar_offsets, self._pos_postings_roar_data, int(pos_id), int(target)))

    def contains_word_position(self, word_id: int, pos: int) -> bool:
        if word_id <= 0:
            return False
        if self._word_postings_roar_offsets is None or self._word_postings_roar_data is None:
            raise RuntimeError("Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return bool(roar_contains(self._word_postings_roar_offsets, self._word_postings_roar_data, int(word_id), int(pos)))

    def contains_lemma_position(self, lemma_id: int, pos: int) -> bool:
        if lemma_id <= 0:
            return False
        if self._lemma_postings_roar_offsets is None or self._lemma_postings_roar_data is None:
            raise RuntimeError("Lemma Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return bool(roar_contains(self._lemma_postings_roar_offsets, self._lemma_postings_roar_data, int(lemma_id), int(pos)))

    def contains_pos_position(self, pos_id: int, pos: int) -> bool:
        if pos_id <= 0:
            return False
        if self._pos_postings_roar_offsets is None or self._pos_postings_roar_data is None:
            raise RuntimeError("POS Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
        return bool(roar_contains(self._pos_postings_roar_offsets, self._pos_postings_roar_data, int(pos_id), int(pos)))

    def get_roaring_postings(self, attr: str) -> tuple[np.ndarray, mmap.mmap]:
        if attr == "word":
            if self._word_postings_roar_offsets is None or self._word_postings_roar_data is None:
                raise RuntimeError("Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._word_postings_roar_offsets, self._word_postings_roar_data
        if attr == "lemma":
            if self._lemma_postings_roar_offsets is None or self._lemma_postings_roar_data is None:
                raise RuntimeError("Lemma Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._lemma_postings_roar_offsets, self._lemma_postings_roar_data
        if attr == "pos":
            if self._pos_postings_roar_offsets is None or self._pos_postings_roar_data is None:
                raise RuntimeError("POS Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._pos_postings_roar_offsets, self._pos_postings_roar_data
        if attr == "morph":
            if self._morph_postings_roar_offsets is None or self._morph_postings_roar_data is None:
                raise RuntimeError("Morph Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._morph_postings_roar_offsets, self._morph_postings_roar_data
        if attr == "ent":
            if self._ent_postings_roar_offsets is None or self._ent_postings_roar_data is None:
                raise RuntimeError("Ent Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._ent_postings_roar_offsets, self._ent_postings_roar_data
        if attr == "rel":
            if self._rel_postings_roar_offsets is None or self._rel_postings_roar_data is None:
                raise RuntimeError("Rel Postings Index fehlt oder ist ungültig. Bitte Index neu bauen.")
            return self._rel_postings_roar_offsets, self._rel_postings_roar_data
        raise RuntimeError(f"Unbekanntes Attribut: {attr}")

    def has_lemma_postings(self) -> bool:
        return self._lemma_postings_roar_offsets is not None and self._lemma_postings_roar_data is not None

    def has_pos_postings(self) -> bool:
        return self._pos_postings_roar_offsets is not None and self._pos_postings_roar_data is not None

    def has_morph_postings(self) -> bool:
        return self._morph_postings_roar_offsets is not None and self._morph_postings_roar_data is not None

    def has_ent_postings(self) -> bool:
        return self._ent_postings_roar_offsets is not None and self._ent_postings_roar_data is not None

    def has_rel_postings(self) -> bool:
        return self._rel_postings_roar_offsets is not None and self._rel_postings_roar_data is not None

    @property
    def word_docset_offsets(self) -> Optional[np.ndarray]:
        return self._word_docset_offsets

    @property
    def word_docset_ids(self) -> Optional[np.ndarray]:
        return self._word_docset_ids

    @property
    def lemma_docset_offsets(self) -> Optional[np.ndarray]:
        return self._lemma_docset_offsets

    @property
    def lemma_docset_ids(self) -> Optional[np.ndarray]:
        return self._lemma_docset_ids

    @property
    def pos_docset_offsets(self) -> Optional[np.ndarray]:
        return self._pos_docset_offsets

    @property
    def pos_docset_ids(self) -> Optional[np.ndarray]:
        return self._pos_docset_ids

    @property
    def pos_sentence_offsets(self) -> Optional[np.ndarray]:
        return self._pos_sentence_offsets

    @property
    def pos_sentence_ids(self) -> Optional[np.ndarray]:
        return self._pos_sentence_ids

    def dense_bitset(self, attr: str, type_id: int) -> Optional[np.ndarray]:
        entry = self._dense_bitsets.get(attr)
        if entry is None:
            return None
        _ids, data, bitset_bytes, id_to_idx = entry
        idx = id_to_idx.get(int(type_id))
        if idx is None:
            return None
        start = int(idx) * int(bitset_bytes)
        end = start + int(bitset_bytes)
        if end > data.size:
            return None
        return data[start:end]

    def dense_bitset_available(self, attr: str, type_id: int) -> bool:
        entry = self._dense_bitsets.get(attr)
        if entry is None:
            return False
        _ids, _data, _bitset_bytes, id_to_idx = entry
        return int(type_id) in id_to_idx

    def get_block_top(self, attr: str) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, int]]:
        if attr == "word" and self._word_block_top_offsets is not None:
            return (
                self._word_block_top_offsets,
                self._word_block_top_ids,
                self._word_block_top_counts,
                self._word_block_top_totals,
                self._word_block_top_size,
                self._word_block_top_k,
            )
        if attr == "lemma" and self._lemma_block_top_offsets is not None:
            return (
                self._lemma_block_top_offsets,
                self._lemma_block_top_ids,
                self._lemma_block_top_counts,
                self._lemma_block_top_totals,
                self._lemma_block_top_size,
                self._lemma_block_top_k,
            )
        return None
