#!/usr/bin/env python3
from __future__ import annotations

import heapq
import logging
import math
import os
import struct
import json
import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Optional, Sequence

import numpy as np

# The on-disk index format lives in ``candyconc.core.index_format`` so writers
# and readers share one definition.

from candyconc.core import index_format  # noqa: E402

LOGGER = logging.getLogger(__name__)

# Tunables (defaults can be overridden via env)
SVB_BLOCK_SIZE = int(os.environ.get("CANDYCONC_SVB_BLOCK_SIZE", "4096"))
BLOCK_TOP_SIZE = int(os.environ.get("CANDYCONC_BLOCK_TOP_SIZE", "4096"))
BLOCK_TOP_K = int(os.environ.get("CANDYCONC_BLOCK_TOP_K", "32"))
PREFIX_LEN = int(os.environ.get("CANDYCONC_PREFIX_LEN", "3"))
PREFIX_TOP_K = int(os.environ.get("CANDYCONC_PREFIX_TOP_K", "32"))
PREFIX_TOP_GLOBAL = int(os.environ.get("CANDYCONC_PREFIX_TOP_GLOBAL", "128"))
PREFIX_ALL_LEN = int(os.environ.get("CANDYCONC_PREFIX_ALL_LEN", str(PREFIX_LEN)))
BUILD_PREFIX_ALL = os.environ.get("CANDYCONC_BUILD_PREFIX_ALL", "1") != "0"
NGRAM_LEN = int(os.environ.get("CANDYCONC_NGRAM_LEN", "3"))
NGRAM_MAX_TOKEN_LEN = int(os.environ.get("CANDYCONC_NGRAM_MAX_TOKEN_LEN", "64"))
BUILD_NGRAM_INDEX = os.environ.get("CANDYCONC_BUILD_NGRAM_INDEX", "1") != "0"
DENSE_BITSET_ATTRS = [
    s.strip() for s in os.environ.get("CANDYCONC_DENSE_BITSET_ATTRS", "word,lemma").split(",") if s.strip()
]
BUILD_DENSE_BITSETS = os.environ.get("CANDYCONC_BUILD_DENSE_BITSETS", "1") != "0"
DENSE_BITSET_TOP = int(os.environ.get("CANDYCONC_DENSE_BITSET_TOP", "64"))
DENSE_BITSET_MIN_FREQ = int(os.environ.get("CANDYCONC_DENSE_BITSET_MIN_FREQ", "0"))
DENSE_BITSET_MIN_DENSITY = float(os.environ.get("CANDYCONC_DENSE_BITSET_MIN_DENSITY", "0.02"))
DENSE_BITSET_MAX_MB = int(os.environ.get("CANDYCONC_DENSE_BITSET_MAX_MB", "2048"))


def _available_memory_bytes() -> Optional[int]:
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().available)
    except Exception:
        return None


def _fmix64(x: int) -> int:
    x ^= x >> 33
    x = (x * 0xff51afd7ed558ccd) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    x = (x * 0xc4ceb9fe1a85ec53) & 0xFFFFFFFFFFFFFFFF
    x ^= x >> 33
    return x & 0xFFFFFFFFFFFFFFFF


def _hash64(text: str) -> int:
    h = 14695981039346656037
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return _fmix64(h)


def _write_array(path: Path, arr: np.ndarray) -> None:
    # Count-prefixed array format is defined once in candyconc.core.index_format.
    index_format.write_count_prefixed_array(path, arr)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), "utf-8")


def _svb_encode_block(values: np.ndarray) -> bytes:
    vals = np.asarray(values, dtype=np.uint32)
    n = int(vals.size)
    if n == 0:
        return b""
    groups = (n + 3) // 4
    controls = bytearray()
    data = bytearray()
    idx = 0
    for _ in range(groups):
        ctrl = 0
        for j in range(4):
            if idx >= n:
                break
            v = int(vals[idx])
            nbytes = max(1, (v.bit_length() + 7) // 8)
            ctrl |= (nbytes - 1) << (2 * j)
            data.extend(v.to_bytes(nbytes, "little", signed=False))
            idx += 1
        controls.append(ctrl & 0xFF)
    return bytes(controls) + bytes(data)


def _write_svb_stream(path_base: Path, ids: np.ndarray, block_size: int) -> None:
    path_base = Path(path_base)
    ids = np.asarray(ids, dtype=np.uint32)
    token_count = int(ids.size)
    if token_count == 0:
        raise RuntimeError("SVB stream: keine Daten")
    n_blocks = int(math.ceil(token_count / float(block_size)))
    offsets: List[int] = [0]
    cursor = 0
    ptr_path = path_base.with_suffix(".svb.ptr.bin")
    data_path = path_base.with_suffix(".svb.data.bin")
    with open(data_path, "wb") as f:
        for b in range(n_blocks):
            start = b * block_size
            end = min(token_count, (b + 1) * block_size)
            block = ids[start:end]
            enc = _svb_encode_block(block)
            f.write(enc)
            cursor += len(enc)
            offsets.append(cursor)
    # The SVB header's third field is uint32. enforce_scaling_limits() caps
    # token_count at MAX_I32 < MAX_U32 before this writer is reached, so the
    # field is always sufficient; the former &0xFFFFFFFF mask was a no-op for
    # every in-range count and is dropped (the assert makes the contract loud
    # if the writer is ever called standalone without the build-time guard).
    assert token_count <= index_format.MAX_U32, (
        f"token_count {token_count} ueberschreitet das SVB-Header uint32-Feld; "
        "enforce_scaling_limits() haette dies vorher abgefangen."
    )
    with open(ptr_path, "wb") as f:
        f.write(struct.pack(
            index_format.SVB_PTR_HEADER_STRUCT,
            n_blocks, int(block_size), int(token_count),
        ))
        f.write(np.asarray(offsets, dtype=np.uint64).tobytes())


def _write_lexicon_bin(path: Path, str_to_id: Dict[str, int], freqs: Dict[int, int]) -> None:
    path = Path(path)
    if not str_to_id:
        raise RuntimeError("Lexikon leer")
    max_id = max(int(i) for i in str_to_id.values())
    vocab_size = int(max_id)
    id_to_str = [""] * (vocab_size + 1)
    for s, i in str_to_id.items():
        if i <= 0 or i > vocab_size:
            continue
        id_to_str[int(i)] = str(s)
    offsets = np.zeros((vocab_size + 1,), dtype=np.uint64)
    freqs_arr = np.zeros((vocab_size + 1,), dtype=np.uint64)
    tmp_blob = path.with_suffix(".blob.tmp")
    blob_size = 0
    with open(tmp_blob, "wb") as blob_f:
        for i in range(vocab_size + 1):
            offsets[i] = blob_size
            s = id_to_str[i]
            if s:
                b = s.encode("utf-8")
                blob_f.write(b)
                blob_size += len(b)
            if i in freqs:
                freqs_arr[i] = int(freqs[i])
    total_tokens = int(freqs_arr.sum())
    header = struct.pack(
        index_format.LEXICON_HEADER_STRUCT,
        index_format.LEXICON_MAGIC,
        index_format.LEXICON_VERSION,
        int(vocab_size),
        0,
        int(total_tokens),
        int(blob_size),
    )
    with open(path, "wb") as f, open(tmp_blob, "rb") as blob_f:
        f.write(header)
        f.write(offsets.tobytes())
        f.write(freqs_arr.tobytes())
        while True:
            chunk = blob_f.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp_blob.unlink(missing_ok=True)


def _write_hash_index(lex_path: Path, str_to_id: Dict[str, int]) -> None:
    lex_path = Path(lex_path)
    if not str_to_id:
        raise RuntimeError("Hash Index: leeres Lexikon")
    count = 0
    for tid in str_to_id.values():
        if int(tid) > 0:
            count += 1
    if count <= 0:
        raise RuntimeError("Hash Index: leeres Lexikon")
    hashes = np.empty((count,), dtype=np.uint64)
    tids = np.empty((count,), dtype=np.uint32)
    idx = 0
    for s, tid in str_to_id.items():
        if tid <= 0:
            continue
        hashes[idx] = _hash64(str(s))
        tids[idx] = int(tid)
        idx += 1
    if idx != count:
        hashes = hashes[:idx]
        tids = tids[:idx]
        count = idx
    order = np.argsort(hashes, kind="quicksort")
    hashes = hashes[order]
    tids = tids[order]
    # bucket bits: aim for ~4 entries per bucket
    if count <= 1:
        bucket_bits = 1
    else:
        target = max(1, count // 4)
        bucket_bits = max(1, min(24, int(math.ceil(math.log2(target)))))
    bucket_count = 1 << bucket_bits
    if bucket_bits:
        bucket_ids = (hashes >> (64 - bucket_bits)).astype(np.uint32, copy=False)
    else:
        bucket_ids = np.zeros((count,), dtype=np.uint32)
    counts = np.bincount(bucket_ids, minlength=bucket_count).astype(np.uint64, copy=False)
    buckets = np.zeros((bucket_count + 1,), dtype=np.uint64)
    buckets[1:] = np.cumsum(counts, dtype=np.uint64)
    bucket_path = lex_path.with_suffix(".bucket.bin")
    with open(bucket_path, "wb") as f:
        f.write(struct.pack("<IIQ", int(bucket_bits), 0, int(bucket_count)))
        buckets.tofile(f)
    hash_path = lex_path.with_suffix(".hash.bin")
    entry_dtype = np.dtype([("h", "<u8"), ("tid", "<u4"), ("pad", "<u4")])
    entries = np.empty((count,), dtype=entry_dtype)
    entries["h"] = hashes
    entries["tid"] = tids
    entries["pad"] = 0
    with open(hash_path, "wb") as f:
        f.write(struct.pack("<Q", int(count)))
        entries.tofile(f)


def _write_prefix_top(
    path: Path,
    id_to_str: List[str],
    freqs: Dict[int, int],
    prefix_len: int,
    top_k: int,
    top_global: int,
) -> None:
    path = Path(path)
    prefix_len = max(1, int(prefix_len))
    top_k = max(1, int(top_k))
    top_global = max(0, int(top_global))
    by_prefix: Dict[str, List[Tuple[int, int]]] = {}
    for tid, s in enumerate(id_to_str):
        if tid <= 0 or not s:
            continue
        if len(s) < prefix_len:
            continue
        prefix = s[:prefix_len]
        freq = int(freqs.get(tid, 0))
        by_prefix.setdefault(prefix, []).append((freq, tid))
    # compute global top ids
    all_items = [(int(freqs.get(tid, 0)), tid) for tid in range(1, len(id_to_str))]
    all_items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top_global_ids = [tid for _, tid in all_items[:top_global]] if top_global else []
    # sort and trim per prefix
    for key, items in by_prefix.items():
        items.sort(key=lambda x: (x[0], x[1]), reverse=True)
        by_prefix[key] = items[:top_k]
    with open(path, "wb") as f:
        header = struct.pack(
            index_format.PREFIX_TOP_HEADER_STRUCT,
            index_format.PREFIX_TOP_MAGIC,
            index_format.PREFIX_TOP_VERSION,
            int(prefix_len),
            int(top_k),
            int(top_global),
            int(len(by_prefix)),
            int(len(top_global_ids)),
        )
        f.write(header)
        if top_global_ids:
            f.write(np.asarray(top_global_ids, dtype=np.uint32).tobytes())
        for prefix, items in by_prefix.items():
            key = prefix.encode("utf-8")
            plen = len(key)
            cnt = len(items)
            f.write(struct.pack("<HH", int(plen), int(cnt)))
            f.write(key)
            if cnt:
                ids = [tid for _, tid in items]
                f.write(np.asarray(ids, dtype=np.uint32).tobytes())


def _build_prefix_all_map(id_to_str: List[str], prefix_len: int) -> Dict[str, List[int]]:
    prefix_len = max(1, int(prefix_len))
    out: Dict[str, List[int]] = {}
    for tid, s in enumerate(id_to_str):
        if tid <= 0 or not s:
            continue
        if len(s) < prefix_len:
            continue
        key = s[:prefix_len]
        out.setdefault(key, []).append(tid)
    return out


def _build_ngram_map(id_to_str: List[str], ngram_len: int, max_token_len: int) -> Dict[str, List[int]]:
    ngram_len = max(1, int(ngram_len))
    max_token_len = max(1, int(max_token_len))
    out: Dict[str, List[int]] = {}
    for tid, s in enumerate(id_to_str):
        if tid <= 0 or not s:
            continue
        if len(s) < ngram_len:
            continue
        if len(s) > max_token_len:
            continue
        seen = set()
        for i in range(0, len(s) - ngram_len + 1):
            gram = s[i : i + ngram_len]
            if gram in seen:
                continue
            seen.add(gram)
            out.setdefault(gram, []).append(tid)
    return out


def _write_string_postings_index(base_path: Path, key_to_ids: Dict[str, List[int]], meta: dict) -> None:
    base_path = Path(base_path)
    if not key_to_ids:
        return
    keys = sorted(key_to_ids.keys())
    str_to_id = {k: i + 1 for i, k in enumerate(keys)}
    freqs = {i + 1: len(key_to_ids[k]) for i, k in enumerate(keys)}
    lex_path = Path(f"{base_path}.bin")
    _write_lexicon_bin(lex_path, str_to_id, freqs)
    _write_hash_index(lex_path, str_to_id)
    vocab_size = len(keys)
    offsets = np.zeros((vocab_size + 2,), dtype=np.uint64)
    ids_blob: List[int] = []
    cursor = 0
    for i, key in enumerate(keys, start=1):
        offsets[i] = cursor
        ids = sorted(set(key_to_ids[key]))
        ids_blob.extend(ids)
        cursor += len(ids)
    offsets[vocab_size + 1] = cursor
    _write_array(Path(f"{base_path}.postings.ptr.bin"), offsets)
    _write_array(Path(f"{base_path}.postings.bin"), np.asarray(ids_blob, dtype=np.uint32))
    _write_json(Path(f"{base_path}.meta.json"), meta)


def _write_prefix_all_index(output_path: Path, name: str, id_to_str: List[str], prefix_len: int) -> None:
    if not BUILD_PREFIX_ALL:
        return
    mapping = _build_prefix_all_map(id_to_str, prefix_len)
    base = Path(output_path) / f"{name}_lexicon.prefix_all"
    meta = {"kind": "prefix_all", "prefix_len": int(prefix_len), "items": int(len(mapping))}
    _write_string_postings_index(base, mapping, meta)


def _write_ngram_index(output_path: Path, name: str, id_to_str: List[str], ngram_len: int) -> None:
    if not BUILD_NGRAM_INDEX:
        return
    if ngram_len <= 0:
        return
    mapping = _build_ngram_map(id_to_str, ngram_len, NGRAM_MAX_TOKEN_LEN)
    base = Path(output_path) / f"{name}_lexicon.ngram{int(ngram_len)}"
    meta = {"kind": "ngram", "ngram_len": int(ngram_len), "items": int(len(mapping))}
    _write_string_postings_index(base, mapping, meta)


def _write_dense_bitsets(
    output_path: Path,
    name: str,
    token_ids: np.ndarray,
    freqs: Sequence[int],
    n_tokens: int,
) -> None:
    if not BUILD_DENSE_BITSETS:
        return
    if name not in DENSE_BITSET_ATTRS:
        return
    if n_tokens <= 0:
        return
    if not freqs:
        return
    # choose dense types by frequency/density
    vocab_size = len(freqs) - 1
    if vocab_size <= 0:
        return
    candidates: List[Tuple[int, int]] = []
    for tid in range(1, vocab_size + 1):
        f = int(freqs[tid])
        if f <= 0:
            continue
        if f < DENSE_BITSET_MIN_FREQ:
            continue
        density = f / float(n_tokens)
        if density < DENSE_BITSET_MIN_DENSITY:
            continue
        candidates.append((f, tid))
    if not candidates:
        return
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    dense = [tid for _f, tid in candidates[: max(1, DENSE_BITSET_TOP)]]

    bitset_bytes = (int(n_tokens) + 7) // 8
    total_bytes = int(bitset_bytes) * len(dense)
    if total_bytes > DENSE_BITSET_MAX_MB * 1024 * 1024:
        # shrink to fit budget
        max_dense = max(1, (DENSE_BITSET_MAX_MB * 1024 * 1024) // bitset_bytes)
        dense = dense[: int(max_dense)]
        total_bytes = int(bitset_bytes) * len(dense)
    if not dense:
        return

    dense_map = {tid: i for i, tid in enumerate(dense)}
    bitsets = np.zeros((len(dense), bitset_bytes), dtype=np.uint8)

    # Single pass over token ids (fast in numpy, but still O(n_tokens)).
    token_ids = np.asarray(token_ids, dtype=np.uint32)
    for pos, tid in enumerate(token_ids):
        idx = dense_map.get(int(tid))
        if idx is None:
            continue
        b = pos >> 3
        bit = 1 << (pos & 7)
        bitsets[idx, b] |= np.uint8(bit)

    base = Path(output_path)
    ids_path = base / f"{name}_dense_bitset.ids.bin"
    data_path = base / f"{name}_dense_bitset.data.bin"
    meta_path = base / f"{name}_dense_bitset.meta.json"

    _write_array(ids_path, np.asarray(dense, dtype=np.uint32))
    _write_array(data_path, bitsets.reshape(-1))
    _write_json(
        meta_path,
        {
            "attr": name,
            "n_tokens": int(n_tokens),
            "bitset_bytes": int(bitset_bytes),
            "n_types": int(len(dense)),
            "bytes_total": int(total_bytes),
        },
    )


def _build_unit_sets_from_bounds(
    ids: np.ndarray,
    bounds: np.ndarray,
    token_count: int,
    vocab_size: int,
    *,
    skip_zero: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    ids = np.asarray(ids, dtype=np.uint32)
    bounds = np.asarray(bounds, dtype=np.uint32)
    if token_count <= 0:
        token_count = int(ids.size)
    if bounds.size == 0:
        bounds = np.asarray([0], dtype=np.uint32)
    starts = bounds
    ends = np.empty_like(starts)
    ends[:-1] = starts[1:]
    ends[-1] = token_count
    counts = np.zeros((vocab_size + 1,), dtype=np.uint32)
    for unit_id, (s, e) in enumerate(zip(starts, ends)):
        if e <= s:
            continue
        block = ids[int(s): int(e)]
        if block.size == 0:
            continue
        uniq = np.unique(block)
        if skip_zero:
            uniq = uniq[uniq != 0]
        if uniq.size == 0:
            continue
        uniq = uniq[uniq <= vocab_size]
        if uniq.size == 0:
            continue
        counts[uniq] += 1
    # Docset pointer array follows the postings sentinel convention: length
    # vocab_size + 2 with a terminal sentinel at index vocab_size + 1, so the
    # reader can take offsets[tid + 1] for the highest term id. Without the
    # terminal the highest word/lemma/pos docset was silently unreachable.
    offsets = np.zeros((index_format.postings_ptr_len(vocab_size),), dtype=np.uint64)
    if vocab_size > 0:
        offsets[1:] = np.cumsum(counts, dtype=np.uint64)
    total = int(counts.sum())
    out_arr = np.empty((total,), dtype=np.uint32)
    cursor = offsets.copy()
    for unit_id, (s, e) in enumerate(zip(starts, ends)):
        if e <= s:
            continue
        block = ids[int(s): int(e)]
        if block.size == 0:
            continue
        uniq = np.unique(block)
        if skip_zero:
            uniq = uniq[uniq != 0]
        if uniq.size == 0:
            continue
        uniq = uniq[uniq <= vocab_size]
        if uniq.size == 0:
            continue
        for tid in uniq:
            itid = int(tid)
            pos = int(cursor[itid])
            out_arr[pos] = int(unit_id)
            cursor[itid] = pos + 1
    return offsets.astype(np.uint64, copy=False), out_arr


def _build_block_top(
    ids: np.ndarray,
    block_size: int,
    top_k: int,
    *,
    skip_zero: bool = True,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ids = np.asarray(ids, dtype=np.uint32)
    token_count = int(ids.size)
    n_blocks = int(math.ceil(token_count / float(block_size)))
    offsets = np.zeros((n_blocks + 1,), dtype=np.uint64)
    out_ids: List[int] = []
    out_cnt: List[int] = []
    out_tot: List[int] = []
    cursor = 0
    for b in range(n_blocks):
        start = b * block_size
        end = min(token_count, (b + 1) * block_size)
        block = ids[start:end]
        counts: Dict[int, int] = {}
        for v in block:
            iv = int(v)
            if skip_zero and iv == 0:
                continue
            counts[iv] = counts.get(iv, 0) + 1
        total = int(block.size)
        out_tot.append(total)
        items = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)[:top_k]
        offsets[b] = cursor
        for tid, cnt in items:
            out_ids.append(int(tid))
            out_cnt.append(int(cnt))
            cursor += 1
    offsets[n_blocks] = cursor
    return (
        offsets.astype(np.uint64, copy=False),
        np.asarray(out_ids, dtype=np.uint32),
        np.asarray(out_cnt, dtype=np.uint32),
        np.asarray(out_tot, dtype=np.uint32),
    )


def _write_block_top(
    output_dir: Path,
    name: str,
    offsets: np.ndarray,
    ids: np.ndarray,
    cnt: np.ndarray,
    tot: np.ndarray,
    block_size: int,
    top_k: int,
) -> None:
    output_dir = Path(output_dir)
    n_blocks = int(len(offsets) - 1)
    ptr_path = output_dir / f"{name}_block_top.ptr.bin"
    with open(ptr_path, "wb") as f:
        f.write(struct.pack(
            index_format.BLOCK_TOP_HEADER_STRUCT,
            index_format.BLOCK_TOP_MAGIC,
            index_format.BLOCK_TOP_VERSION,
            int(block_size), int(top_k), int(n_blocks),
        ))
        f.write(np.asarray(offsets, dtype=np.uint64).tobytes())
    _write_array(output_dir / f"{name}_block_top.ids.bin", ids.astype(np.uint32, copy=False))
    _write_array(output_dir / f"{name}_block_top.cnt.bin", cnt.astype(np.uint32, copy=False))
    _write_array(output_dir / f"{name}_block_top.tot.bin", tot.astype(np.uint32, copy=False))


def _write_roaring_postings(
    output_dir: Path,
    ids: np.ndarray,
    vocab_size: int,
    *,
    name: str,
    skip_zero: bool = False,
) -> None:
    output_dir = Path(output_dir)
    ids = np.asarray(ids, dtype=np.uint32)
    token_count = int(ids.size)
    if token_count == 0:
        raise RuntimeError("Roaring postings: keine Daten")

    bucket_size = int(os.environ.get("CANDYCONC_POSTINGS_BUCKET_SIZE", "4096"))
    chunk_size = int(os.environ.get("CANDYCONC_POSTINGS_CHUNK_SIZE", "2000000"))
    run_pairs = int(os.environ.get("CANDYCONC_POSTINGS_RUN_PAIRS", "1000000"))
    disk_mode = str(os.environ.get("CANDYCONC_POSTINGS_DISK_MODE", "auto")).lower()
    prefer_ram = os.environ.get("CANDYCONC_POSTINGS_PREFER_RAM", "0") == "1"
    ram_budget_mb = int(os.environ.get("CANDYCONC_POSTINGS_RAM_BUDGET_MB", "32768"))
    if bucket_size <= 0:
        bucket_size = 8192
    if chunk_size <= 0:
        chunk_size = 5_000_000
    if run_pairs <= 0:
        run_pairs = 1_000_000
    default_read_pairs = min(200_000, run_pairs)
    read_pairs = int(os.environ.get("CANDYCONC_POSTINGS_RUN_READ", str(default_read_pairs)))
    if read_pairs <= 0:
        read_pairs = default_read_pairs
    if read_pairs > run_pairs:
        read_pairs = run_pairs

    if ram_budget_mb <= 0:
        ram_budget_mb = 32768
    ram_budget_bytes = int(ram_budget_mb) * 1024 * 1024

    n_buckets = int((vocab_size + bucket_size) // bucket_size)
    tmp_dir = output_dir / f".{name}_postings_tmp"
    if tmp_dir.exists() and not tmp_dir.is_dir():
        tmp_dir.unlink(missing_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    bucket_paths = [tmp_dir / f"bucket_{i:04d}.bin" for i in range(n_buckets)]
    run_dir = tmp_dir / "runs"
    if run_dir.exists() and not run_dir.is_dir():
        run_dir.unlink(missing_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Clean stale tmp artifacts from previous failed runs.
    try:
        for path in tmp_dir.glob("bucket_*.bin"):
            path.unlink(missing_ok=True)
        if run_dir.exists():
            for path in run_dir.glob("*.bin"):
                path.unlink(missing_ok=True)
    except OSError:
        pass

    class _RunCursor:
        def __init__(self, path: Path, read_pairs: int) -> None:
            self.path = path
            self._fh = path.open("rb")
            self._read_pairs = int(read_pairs)
            self._buf = np.zeros((0, 2), dtype=np.uint32)
            self._tids = self._buf[:, 0]
            self._poss = self._buf[:, 1]
            self._idx = 0
            self._eof = False
            self._fill()

        def _fill(self) -> None:
            raw = np.fromfile(self._fh, dtype=np.uint32, count=self._read_pairs * 2)
            if raw.size == 0:
                self._buf = np.zeros((0, 2), dtype=np.uint32)
                self._tids = self._buf[:, 0]
                self._poss = self._buf[:, 1]
                self._idx = 0
                self._eof = True
                return
            if raw.size % 2 != 0:
                raise RuntimeError(f"Postings run korrupt: {self.path}")
            self._buf = raw.reshape(-1, 2)
            self._tids = self._buf[:, 0]
            self._poss = self._buf[:, 1]
            self._idx = 0

        def _ensure_buf(self) -> bool:
            if self._eof:
                return False
            if self._idx >= self._buf.shape[0]:
                self._fill()
            return not self._eof

        def current_tid(self) -> int | None:
            if not self._ensure_buf():
                return None
            return int(self._tids[self._idx])

        def consume_tid(self, tid: int, write_chunk) -> None:
            while True:
                if not self._ensure_buf():
                    return
                if int(self._tids[self._idx]) != tid:
                    return
                end = int(np.searchsorted(self._tids, tid, side="right"))
                if end <= self._idx:
                    return
                write_chunk(self._poss[self._idx:end])
                self._idx = end

        def close(self) -> None:
            try:
                self._fh.close()
            except Exception:
                pass
    try:
        for start in range(0, token_count, chunk_size):
            end = min(token_count, start + chunk_size)
            ids_chunk = ids[start:end]
            if skip_zero:
                mask = ids_chunk != 0
                if not np.any(mask):
                    continue
                ids_chunk = ids_chunk[mask]
                pos_chunk = (np.arange(start, end, dtype=np.uint32))[mask]
            else:
                pos_chunk = np.arange(start, end, dtype=np.uint32)
            if ids_chunk.size == 0:
                continue
            bucket_ids = (ids_chunk // bucket_size).astype(np.uint32, copy=False)
            order = np.argsort(bucket_ids, kind="stable")
            bucket_sorted = bucket_ids[order]
            ids_sorted = ids_chunk[order]
            pos_sorted = pos_chunk[order]
            seg_start = 0
            total = int(bucket_sorted.size)
            while seg_start < total:
                b = int(bucket_sorted[seg_start])
                seg_end = seg_start + 1
                while seg_end < total and int(bucket_sorted[seg_end]) == b:
                    seg_end += 1
                segment_len = seg_end - seg_start
                if segment_len > 0:
                    data = np.empty((segment_len, 2), dtype=np.uint32)
                    data[:, 0] = ids_sorted[seg_start:seg_end]
                    data[:, 1] = pos_sorted[seg_start:seg_end]
                    with bucket_paths[b].open("ab") as fh:
                        data.tofile(fh)
                seg_start = seg_end

        offsets = np.zeros((vocab_size + 2,), dtype=np.uint64)
        ptr_path = output_dir / f"{name}_postings.r32.ptr.bin"
        data_path = output_dir / f"{name}_postings.r32.data.bin"
        cursor = 0
        current_tid = 0
        with open(data_path, "wb") as out_f:
            for bucket_id, path in enumerate(bucket_paths):
                if not path.exists() or path.stat().st_size == 0:
                    continue
                bucket_bytes = int(path.stat().st_size)
                if bucket_bytes % 8 != 0:
                    raise RuntimeError(f"Postings bucket korrupt: {path}")

                def _emit_sorted_pairs(tids: np.ndarray, poss: np.ndarray) -> None:
                    nonlocal cursor, current_tid
                    idx = 0
                    total = int(tids.size)
                    while idx < total:
                        tid = int(tids[idx])
                        while current_tid < tid:
                            offsets[current_tid] = cursor
                            current_tid += 1
                        if skip_zero and tid == 0:
                            offsets[tid] = cursor
                            current_tid = max(current_tid, tid + 1)
                            while idx < total and int(tids[idx]) == tid:
                                idx += 1
                            continue
                        start_idx = idx
                        while idx < total and int(tids[idx]) == tid:
                            idx += 1
                        offsets[tid] = cursor
                        pos_list = poss[start_idx:idx]
                        if pos_list.size:
                            highs = (pos_list >> 16).astype(np.uint16, copy=False)
                            lows = (pos_list & 0xFFFF).astype(np.uint16, copy=False)
                            change = np.flatnonzero(highs[1:] != highs[:-1]) + 1
                            starts = np.concatenate(([0], change))
                            ends = np.concatenate((change, [len(pos_list)]))
                            out_f.write(struct.pack("<I", int(len(starts))))
                            cursor += 4
                            for s, e in zip(starts, ends):
                                high = int(highs[s])
                                block_lows = lows[s:e]
                                out_f.write(struct.pack("<HHI", high, 0, int(len(block_lows))))
                                cursor += 8
                                out_f.write(block_lows.tobytes())
                                cursor += int(len(block_lows) * 2)
                                pad = (-cursor) % 8
                                if pad:
                                    out_f.write(b"\x00" * pad)
                                    cursor += pad
                        current_tid = max(current_tid, tid + 1)

                inmem_bytes_est = bucket_bytes * 3
                low_disk = disk_mode in ("low", "nodisk") or prefer_ram
                if low_disk and inmem_bytes_est <= ram_budget_bytes:
                    raw = np.fromfile(path, dtype=np.uint32)
                    if raw.size == 0:
                        path.unlink(missing_ok=True)
                        continue
                    if raw.size % 2 != 0:
                        raise RuntimeError(f"Postings bucket korrupt: {path}")
                    pairs = raw.reshape(-1, 2)
                    order = np.argsort(pairs[:, 0], kind="stable")
                    pairs = pairs[order]
                    _emit_sorted_pairs(pairs[:, 0], pairs[:, 1])
                    path.unlink(missing_ok=True)
                    continue
                if disk_mode == "nodisk":
                    raise RuntimeError(
                        f"Postings bucket {bucket_id} zu gross fuer RAM-Budget "
                        f"({bucket_bytes / (1024**2):.1f} MB). "
                        "Erhoehe CANDYCONC_POSTINGS_RAM_BUDGET_MB oder erlaube Disk-Mode."
                    )
                run_paths: List[Path] = []
                try:
                    with path.open("rb") as fh:
                        run_idx = 0
                        while True:
                            raw = np.fromfile(fh, dtype=np.uint32, count=run_pairs * 2)
                            if raw.size == 0:
                                break
                            if raw.size % 2 != 0:
                                raise RuntimeError(f"Postings bucket korrupt: {path}")
                            pairs = raw.reshape(-1, 2)
                            order = np.argsort(pairs[:, 0], kind="stable")
                            pairs = pairs[order]
                            run_path = run_dir / f"bucket_{bucket_id:04d}.run{run_idx:03d}.bin"
                            pairs.tofile(run_path)
                            run_paths.append(run_path)
                            run_idx += 1
                    path.unlink(missing_ok=True)
                    if not run_paths:
                        continue
                    runs = [_RunCursor(rp, read_pairs) for rp in run_paths]
                    heap: List[Tuple[int, int]] = []
                    for run_id, run in enumerate(runs):
                        tid = run.current_tid()
                        if tid is not None:
                            heapq.heappush(heap, (int(tid), int(run_id)))
                    while heap:
                        tid, run_id = heapq.heappop(heap)
                        same_runs = [int(run_id)]
                        while heap and heap[0][0] == tid:
                            same_runs.append(int(heapq.heappop(heap)[1]))
                        same_runs.sort()
                        while current_tid < tid:
                            offsets[current_tid] = cursor
                            current_tid += 1
                        if current_tid != tid:
                            continue
                        if skip_zero and tid == 0:
                            offsets[tid] = cursor
                            current_tid = tid + 1
                            for rid in same_runs:
                                runs[rid].consume_tid(int(tid), lambda _chunk: None)
                            for rid in same_runs:
                                next_tid = runs[rid].current_tid()
                                if next_tid is not None:
                                    heapq.heappush(heap, (int(next_tid), int(rid)))
                            continue
                        offsets[tid] = cursor
                        tid_header_pos = cursor
                        out_f.write(struct.pack("<I", 0))
                        cursor += 4
                        container_count = 0
                        current_high: int | None = None
                        cont_header_pos: int | None = None
                        low_count = 0

                        def _finish_container() -> None:
                            nonlocal container_count, cont_header_pos, current_high, low_count, cursor
                            if cont_header_pos is None:
                                return
                            out_f.seek(cont_header_pos + 4)
                            out_f.write(struct.pack("<I", int(low_count)))
                            out_f.seek(cursor)
                            pad = (-cursor) % 8
                            if pad:
                                out_f.write(b"\x00" * pad)
                                cursor += pad
                            container_count += 1
                            cont_header_pos = None
                            current_high = None
                            low_count = 0

                        def _start_container(high: int) -> None:
                            nonlocal cont_header_pos, current_high, low_count, cursor
                            current_high = int(high)
                            cont_header_pos = cursor
                            out_f.write(struct.pack("<HHI", int(high), 0, 0))
                            cursor += 8
                            low_count = 0

                        def _write_positions_chunk(pos_arr: np.ndarray) -> None:
                            nonlocal low_count, cursor, current_high
                            if pos_arr.size == 0:
                                return
                            highs = (pos_arr >> 16).astype(np.uint16, copy=False)
                            lows = (pos_arr & 0xFFFF).astype(np.uint16, copy=False)
                            if highs.size == 0:
                                return
                            change = np.flatnonzero(highs[1:] != highs[:-1]) + 1
                            starts = np.concatenate(([0], change))
                            ends = np.concatenate((change, [len(highs)]))
                            for s, e in zip(starts, ends):
                                high = int(highs[s])
                                if current_high is None:
                                    _start_container(high)
                                elif high != current_high:
                                    _finish_container()
                                    _start_container(high)
                                block_lows = lows[s:e]
                                if block_lows.size:
                                    block_lows.tofile(out_f)
                                    cursor += int(block_lows.size * 2)
                                    low_count += int(block_lows.size)

                        for rid in same_runs:
                            runs[rid].consume_tid(int(tid), _write_positions_chunk)
                        _finish_container()
                        out_f.seek(tid_header_pos)
                        out_f.write(struct.pack("<I", int(container_count)))
                        out_f.seek(cursor)
                        current_tid = tid + 1
                        for rid in same_runs:
                            next_tid = runs[rid].current_tid()
                            if next_tid is not None:
                                heapq.heappush(heap, (int(next_tid), int(rid)))
                    for run in runs:
                        run.close()
                finally:
                    for run_path in run_paths:
                        run_path.unlink(missing_ok=True)
            while current_tid <= vocab_size + 1:
                offsets[current_tid] = cursor
                current_tid += 1
        _write_array(ptr_path, offsets.astype(np.uint64, copy=False))
    finally:
        if tmp_dir.exists():
            for path in bucket_paths:
                if path.exists():
                    path.unlink(missing_ok=True)
            try:
                if run_dir.exists():
                    for path in run_dir.glob("*.bin"):
                        path.unlink(missing_ok=True)
                    run_dir.rmdir()
                tmp_dir.rmdir()
            except OSError:
                pass


def _build_meta_index(meta_doc: Dict[int, dict], output_path: Path, doc_count: int) -> None:
    output_path = Path(output_path)
    meta_dir = output_path / "meta_index"
    meta_dir.mkdir(parents=True, exist_ok=True)

    def _prefix(name: str) -> str:
        h = hashlib.blake2s(name.encode("utf-8"), digest_size=4).hexdigest()
        return f"{name}_{h}"

    max_unique = int(os.environ.get("CANDYCONC_META_MAX_UNIQUE", "250000"))
    fields = []
    for name in sorted({k for meta in meta_doc.values() if isinstance(meta, dict) for k in meta.keys()}):
        values_str: Dict[str, List[int]] = {}
        values_num: List[Tuple[float, int]] = []
        for doc_id, meta in meta_doc.items():
            if not isinstance(meta, dict):
                continue
            val = meta.get(name)
            if val is None:
                continue
            if isinstance(val, list):
                items = val
            else:
                items = [val]
            for item in items:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    values_num.append((float(item), int(doc_id)))
                else:
                    s = str(item)
                    if max_unique > 0 and len(values_str) >= max_unique and s not in values_str:
                        continue
                    values_str.setdefault(s, []).append(int(doc_id))
        prefix = _prefix(name)
        has_str = bool(values_str)
        has_num = bool(values_num)
        if has_str:
            if max_unique > 0 and len(values_str) >= max_unique:
                LOGGER.warning(
                    "Metadata index field %s exceeds max unique values (%d). The index is capped.",
                    name,
                    max_unique,
                )
            str_to_id = {s: i + 1 for i, s in enumerate(sorted(values_str))}
            freqs = {str_to_id[s]: len(values_str[s]) for s in values_str}
            lex_path = meta_dir / f"{prefix}.lex.bin"
            _write_lexicon_bin(lex_path, str_to_id, freqs)
            _write_hash_index(lex_path, str_to_id)
            # postings
            offsets = np.zeros((len(str_to_id) + 2,), dtype=np.uint64)
            doc_ids: List[int] = []
            cursor = 0
            for s, tid in sorted(str_to_id.items(), key=lambda x: x[1]):
                offsets[tid] = cursor
                ids = sorted(set(values_str.get(s, [])))
                doc_ids.extend(ids)
                cursor += len(ids)
            offsets[len(str_to_id) + 1] = cursor
            _write_array(meta_dir / f"{prefix}.postings.ptr.bin", offsets.astype(np.uint64, copy=False))
            _write_array(meta_dir / f"{prefix}.postings.bin", np.asarray(doc_ids, dtype=np.uint32))
        if has_num:
            values_num.sort(key=lambda x: x[0])
            vals = np.asarray([v for v, _ in values_num], dtype=np.float64)
            docs = np.asarray([d for _, d in values_num], dtype=np.uint32)
            _write_array(meta_dir / f"{prefix}.num_values.bin", vals)
            _write_array(meta_dir / f"{prefix}.num_docs.bin", docs)
        fields.append(
            {
                "name": name,
                "prefix": prefix,
                "has_str": has_str,
                "has_num": has_num,
                "str_values": len(values_str),
                "num_values": len(values_num),
            }
        )
    manifest = {
        "version": 1,
        "doc_count": int(doc_count),
        "fields": fields,
    }
    (meta_dir / "meta_index.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


def _iter_meta_jsonl(meta_jsonl: Path) -> Iterable[Tuple[int, dict]]:
    with meta_jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            doc_id = obj.get("doc_idx")
            meta = obj.get("meta")
            if not isinstance(doc_id, int):
                try:
                    doc_id = int(doc_id)
                except Exception:
                    continue
            if not isinstance(meta, dict):
                continue
            yield int(doc_id), meta


def _build_meta_index_from_jsonl(meta_jsonl: Path, output_path: Path, doc_count: int) -> None:
    output_path = Path(output_path)
    meta_dir = output_path / "meta_index"
    meta_dir.mkdir(parents=True, exist_ok=True)

    def _prefix(name: str) -> str:
        h = hashlib.blake2s(name.encode("utf-8"), digest_size=4).hexdigest()
        return f"{name}_{h}"

    max_unique = int(os.environ.get("CANDYCONC_META_MAX_UNIQUE", "250000"))
    inmem_max_mb = int(os.environ.get("CANDYCONC_META_INDEX_MAX_INMEM_MB", "512"))
    force_inmem = os.environ.get("CANDYCONC_META_INDEX_INMEM", "0") == "1"
    cache: List[Tuple[int, dict]] | None = None
    if force_inmem or inmem_max_mb > 0:
        try:
            file_size = meta_jsonl.stat().st_size
        except OSError:
            file_size = 0
        if force_inmem or (file_size and file_size <= inmem_max_mb * 1024 * 1024):
            avail = _available_memory_bytes()
            if force_inmem or (avail is None or avail > file_size * 3):
                try:
                    cache = list(_iter_meta_jsonl(meta_jsonl))
                    LOGGER.info(
                        "Metadata index uses an in-memory cache (%d entries).",
                        len(cache),
                    )
                except Exception:
                    cache = None

    field_names: set[str] = set()
    if cache is not None:
        for _doc_id, meta in cache:
            for key in meta.keys():
                field_names.add(str(key))
    else:
        for _doc_id, meta in _iter_meta_jsonl(meta_jsonl):
            for key in meta.keys():
                field_names.add(str(key))

    fields = []
    for name in sorted(field_names):
        values_str: Dict[str, List[int]] = {}
        values_num: List[Tuple[float, int]] = []
        source = cache if cache is not None else _iter_meta_jsonl(meta_jsonl)
        for doc_id, meta in source:
            if not isinstance(meta, dict):
                continue
            val = meta.get(name)
            if val is None:
                continue
            if isinstance(val, list):
                items = val
            else:
                items = [val]
            for item in items:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    values_num.append((float(item), int(doc_id)))
                else:
                    s = str(item)
                    if max_unique > 0 and len(values_str) >= max_unique and s not in values_str:
                        continue
                    values_str.setdefault(s, []).append(int(doc_id))
        prefix = _prefix(name)
        has_str = bool(values_str)
        has_num = bool(values_num)
        if has_str:
            if max_unique > 0 and len(values_str) >= max_unique:
                LOGGER.warning(
                    "Metadata index field %s exceeds max unique values (%d). The index is capped.",
                    name,
                    max_unique,
                )
            str_to_id = {s: i + 1 for i, s in enumerate(sorted(values_str))}
            freqs = {str_to_id[s]: len(values_str[s]) for s in values_str}
            lex_path = meta_dir / f"{prefix}.lex.bin"
            _write_lexicon_bin(lex_path, str_to_id, freqs)
            _write_hash_index(lex_path, str_to_id)
            offsets = np.zeros((len(str_to_id) + 2,), dtype=np.uint64)
            doc_ids: List[int] = []
            cursor = 0
            for s, tid in sorted(str_to_id.items(), key=lambda x: x[1]):
                offsets[tid] = cursor
                ids = sorted(set(values_str.get(s, [])))
                doc_ids.extend(ids)
                cursor += len(ids)
            offsets[len(str_to_id) + 1] = cursor
            _write_array(meta_dir / f"{prefix}.postings.ptr.bin", offsets.astype(np.uint64, copy=False))
            _write_array(meta_dir / f"{prefix}.postings.bin", np.asarray(doc_ids, dtype=np.uint32))
        if has_num:
            values_num.sort(key=lambda x: x[0])
            vals = np.asarray([v for v, _ in values_num], dtype=np.float64)
            docs = np.asarray([d for _, d in values_num], dtype=np.uint32)
            _write_array(meta_dir / f"{prefix}.num_values.bin", vals)
            _write_array(meta_dir / f"{prefix}.num_docs.bin", docs)
        fields.append(
            {
                "name": name,
                "prefix": prefix,
                "has_str": has_str,
                "has_num": has_num,
                "str_values": len(values_str),
                "num_values": len(values_num),
            }
        )
    manifest = {
        "version": 1,
        "doc_count": int(doc_count),
        "fields": fields,
    }
    (meta_dir / "meta_index.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    from candyconc.ingest.build_fast_index_from_parquet import main

    raise SystemExit(main())
