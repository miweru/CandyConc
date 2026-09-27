"""
Counting Kernels for Collocation Engine.

Single optimized hashmap path (native extension required).
"""
from __future__ import annotations

from typing import Dict, Optional, Set, List
from datetime import datetime
from pathlib import Path
import logging

import numpy as np

from .token_store import TokenStore

LOGGER = logging.getLogger(__name__)


def _write_build_log_path() -> Path:
    from candyconc.paths import data_dir

    log_dir = data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "fastcount_build.log"


def _write_build_log(path: Path, label: str, stdout: str, stderr: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {label}\n")
        if stdout:
            fh.write("-- stdout --\n")
            fh.write(stdout.rstrip() + "\n")
        if stderr:
            fh.write("-- stderr --\n")
            fh.write(stderr.rstrip() + "\n")
        fh.write("\n")


def _load_fast_count():
    try:
        from ._fast_count import (  # type: ignore
            count_segments_svb,
            count_segments_svb_dense,
            count_segments_svb_pos,
            count_ngrams_svb,
            keyness_scores,
            coverage_sweep_arrays_cy,
            match_arrays_from_positions,
        )
        try:
            from ._fast_count import (  # type: ignore
                levenshtein_tokens_fast,
                co_kwic_offset_map,
                intersect_sorted_limit,
                union_sorted_limit,
                count_block_top_svb,
                count_segments_svb_dual,
                build_dual_basis_arrays,
                count_segments_svb_dual_dense,
                gather_u64_to_f64,
                subtract_and_compact_dual_counts_u64,
                filter_sorted_positions_by_docset_mask_u32,
                filter_sorted_positions_and_values_i64_by_docset_mask_u32,
                unique_doc_ids_from_sorted_positions_u32,
                map_positions_to_doc_ids_i64,
                map_positions_to_doc_ids_i32,
                position_to_doc_id_i64,
            )
        except Exception:
            levenshtein_tokens_fast = None
            co_kwic_offset_map = None
            intersect_sorted_limit = None
            union_sorted_limit = None
            count_block_top_svb = None
            count_segments_svb_dual = None
            build_dual_basis_arrays = None
            count_segments_svb_dual_dense = None
            gather_u64_to_f64 = None
            subtract_and_compact_dual_counts_u64 = None
            filter_sorted_positions_by_docset_mask_u32 = None
            filter_sorted_positions_and_values_i64_by_docset_mask_u32 = None
            unique_doc_ids_from_sorted_positions_u32 = None
            map_positions_to_doc_ids_i64 = None
            map_positions_to_doc_ids_i32 = None
            position_to_doc_id_i64 = None
        return (
            count_segments_svb,
            count_segments_svb_dense,
            count_segments_svb_pos,
            count_ngrams_svb,
            keyness_scores,
            coverage_sweep_arrays_cy,
            match_arrays_from_positions,
            levenshtein_tokens_fast,
            co_kwic_offset_map,
            intersect_sorted_limit,
            union_sorted_limit,
            count_block_top_svb,
            count_segments_svb_dual,
            build_dual_basis_arrays,
            count_segments_svb_dual_dense,
            gather_u64_to_f64,
            subtract_and_compact_dual_counts_u64,
            filter_sorted_positions_by_docset_mask_u32,
            filter_sorted_positions_and_values_i64_by_docset_mask_u32,
            unique_doc_ids_from_sorted_positions_u32,
            map_positions_to_doc_ids_i64,
            map_positions_to_doc_ids_i32,
            position_to_doc_id_i64,
        )
    except Exception as exc:
        log_path = _write_build_log_path()
        raise RuntimeError(
            f"Fast Count Extension fehlt. Bitte build_ext ausführen. Log: {log_path}"
        ) from exc


count_segments_svb, count_segments_svb_dense, count_segments_svb_pos, count_ngrams_svb, keyness_scores, coverage_sweep_arrays_cy, match_arrays_from_positions, levenshtein_tokens_fast, co_kwic_offset_map, intersect_sorted_limit, union_sorted_limit, count_block_top_svb, count_segments_svb_dual, build_dual_basis_arrays, count_segments_svb_dual_dense, gather_u64_to_f64, subtract_and_compact_dual_counts_u64, filter_sorted_positions_by_docset_mask_u32, filter_sorted_positions_and_values_i64_by_docset_mask_u32, unique_doc_ids_from_sorted_positions_u32, map_positions_to_doc_ids_i64, map_positions_to_doc_ids_i32, position_to_doc_id_i64 = _load_fast_count()


def count_hashmap_svb(
    token_store: TokenStore,
    stream_name: str,
    seg_starts: np.ndarray,
    seg_ends: np.ndarray,
    seg_weights: np.ndarray,
    stoplist: Optional[Set[int]] = None,
) -> Dict[int, int]:
    if count_segments_svb is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    if stream_name == "word":
        stream = token_store.word_stream
    elif stream_name == "lemma":
        stream = token_store.lemma_stream
    else:
        raise ValueError("stream_name muss word oder lemma sein")
    return count_segments_svb(
        stream.offsets,
        stream.data,
        int(stream.block_size),
        int(token_store.token_count),
        seg_starts.astype(np.uint32, copy=False),
        seg_ends.astype(np.uint32, copy=False),
        seg_weights.astype(np.uint32, copy=False),
        stoplist,
    )


def count_hashmap_svb_dense(
    token_store: TokenStore,
    stream_name: str,
    seg_starts: np.ndarray,
    seg_ends: np.ndarray,
    seg_weights: np.ndarray,
    vocab_size: int,
    stoplist: Optional[Set[int]] = None,
) -> np.ndarray:
    if count_segments_svb_dense is None:
        counts = count_hashmap_svb(token_store, stream_name, seg_starts, seg_ends, seg_weights, stoplist)
        out = np.zeros(int(vocab_size) + 1, dtype=np.uint64)
        for tid, count in counts.items():
            if 0 <= int(tid) <= int(vocab_size):
                out[int(tid)] = int(count)
        return out
    if stream_name == "word":
        stream = token_store.word_stream
    elif stream_name == "lemma":
        stream = token_store.lemma_stream
    else:
        raise ValueError("stream_name muss word oder lemma sein")
    return np.asarray(
        count_segments_svb_dense(
            stream.offsets,
            stream.data,
            int(stream.block_size),
            int(token_store.token_count),
            np.asarray(seg_starts, dtype=np.uint32),
            np.asarray(seg_ends, dtype=np.uint32),
            np.asarray(seg_weights, dtype=np.uint32),
            int(vocab_size),
            stoplist,
        ),
        dtype=np.uint64,
    )


def count_hashmap_svb_dual(
    token_store: TokenStore,
    stream_name: str,
    seg_starts_a: np.ndarray,
    seg_ends_a: np.ndarray,
    seg_weights_a: np.ndarray,
    seg_starts_b: np.ndarray,
    seg_ends_b: np.ndarray,
    seg_weights_b: np.ndarray,
    stoplist: Optional[Set[int]] = None,
) -> tuple[Dict[int, int], Dict[int, int]]:
    if stream_name == "word":
        stream = token_store.word_stream
    elif stream_name == "lemma":
        stream = token_store.lemma_stream
    else:
        raise ValueError("stream_name muss word oder lemma sein")
    if count_segments_svb_dual is None:
        return (
            count_hashmap_svb(token_store, stream_name, seg_starts_a, seg_ends_a, seg_weights_a, stoplist),
            count_hashmap_svb(token_store, stream_name, seg_starts_b, seg_ends_b, seg_weights_b, stoplist),
        )
    return count_segments_svb_dual(
        stream.offsets,
        stream.data,
        int(stream.block_size),
        int(token_store.token_count),
        np.asarray(seg_starts_a, dtype=np.uint32),
        np.asarray(seg_ends_a, dtype=np.uint32),
        np.asarray(seg_weights_a, dtype=np.uint32),
        np.asarray(seg_starts_b, dtype=np.uint32),
        np.asarray(seg_ends_b, dtype=np.uint32),
        np.asarray(seg_weights_b, dtype=np.uint32),
        stoplist,
    )


def count_hashmap_svb_dual_dense(
    token_store: TokenStore,
    stream_name: str,
    seg_starts_a: np.ndarray,
    seg_ends_a: np.ndarray,
    seg_weights_a: np.ndarray,
    seg_starts_b: np.ndarray,
    seg_ends_b: np.ndarray,
    seg_weights_b: np.ndarray,
    vocab_size: int,
    stoplist: Optional[Set[int]] = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if stream_name == "word":
        stream = token_store.word_stream
    elif stream_name == "lemma":
        stream = token_store.lemma_stream
    else:
        raise ValueError("stream_name muss word oder lemma sein")
    if count_segments_svb_dual_dense is None:
        counts_a, counts_b = count_hashmap_svb_dual(
            token_store,
            stream_name,
            seg_starts_a,
            seg_ends_a,
            seg_weights_a,
            seg_starts_b,
            seg_ends_b,
            seg_weights_b,
            stoplist,
        )
        ids, obs_a, obs_b, _freq_a, _freq_b = build_dual_basis_arrays_fast(
            counts_a,
            counts_b,
            {},
            {},
        )
        return ids, obs_a.astype(np.uint64, copy=False), obs_b.astype(np.uint64, copy=False)
    ids, counts_a_arr, counts_b_arr = count_segments_svb_dual_dense(
        stream.offsets,
        stream.data,
        int(stream.block_size),
        int(token_store.token_count),
        np.asarray(seg_starts_a, dtype=np.uint32),
        np.asarray(seg_ends_a, dtype=np.uint32),
        np.asarray(seg_weights_a, dtype=np.uint32),
        np.asarray(seg_starts_b, dtype=np.uint32),
        np.asarray(seg_ends_b, dtype=np.uint32),
        np.asarray(seg_weights_b, dtype=np.uint32),
        int(vocab_size),
        stoplist,
    )
    return (
        np.asarray(ids, dtype=np.uint32),
        np.asarray(counts_a_arr, dtype=np.uint64),
        np.asarray(counts_b_arr, dtype=np.uint64),
    )


def build_dual_basis_arrays_fast(
    counts_a: Dict[int, int],
    counts_b: Dict[int, int],
    freqs_a: Dict[int, int],
    freqs_b: Dict[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if build_dual_basis_arrays is not None:
        return build_dual_basis_arrays(counts_a, counts_b, freqs_a, freqs_b)

    ids_a = np.fromiter(counts_a.keys(), dtype=np.uint32) if counts_a else np.zeros(0, dtype=np.uint32)
    ids_b = np.fromiter(counts_b.keys(), dtype=np.uint32) if counts_b else np.zeros(0, dtype=np.uint32)
    if ids_a.size == 0 and ids_b.size == 0:
        empty_u32 = np.zeros(0, dtype=np.uint32)
        empty_f64 = np.zeros(0, dtype=np.float64)
        return empty_u32, empty_f64, empty_f64, empty_f64, empty_f64
    union_ids = np.union1d(ids_a, ids_b).astype(np.uint32, copy=False)
    return (
        union_ids,
        np.fromiter((float(counts_a.get(int(tid), 0)) for tid in union_ids), dtype=np.float64),
        np.fromiter((float(counts_b.get(int(tid), 0)) for tid in union_ids), dtype=np.float64),
        np.fromiter((float(freqs_a.get(int(tid), 0)) for tid in union_ids), dtype=np.float64),
        np.fromiter((float(freqs_b.get(int(tid), 0)) for tid in union_ids), dtype=np.float64),
    )


def gather_u64_to_f64_fast(src: np.ndarray, ids: np.ndarray) -> np.ndarray:
    ids_u32 = np.asarray(ids, dtype=np.uint32)
    src_u64 = np.asarray(src, dtype=np.uint64)
    if gather_u64_to_f64 is not None:
        return np.asarray(gather_u64_to_f64(src_u64, ids_u32), dtype=np.float64)
    return src_u64[ids_u32].astype(np.float64, copy=False)


def subtract_and_compact_dual_counts_fast(
    union_ids: np.ndarray,
    counts_a: np.ndarray,
    counts_b: np.ndarray,
    anchor_ids: np.ndarray,
    anchor_counts_a: np.ndarray,
    anchor_counts_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    union_ids_u32 = np.asarray(union_ids, dtype=np.uint32)
    counts_a_u64 = np.asarray(counts_a, dtype=np.uint64)
    counts_b_u64 = np.asarray(counts_b, dtype=np.uint64)
    anchor_ids_u32 = np.asarray(anchor_ids, dtype=np.uint32)
    anchor_a_u64 = np.asarray(anchor_counts_a, dtype=np.uint64)
    anchor_b_u64 = np.asarray(anchor_counts_b, dtype=np.uint64)
    if subtract_and_compact_dual_counts_u64 is not None:
        ids, out_a, out_b = subtract_and_compact_dual_counts_u64(
            union_ids_u32,
            counts_a_u64,
            counts_b_u64,
            anchor_ids_u32,
            anchor_a_u64,
            anchor_b_u64,
        )
        return (
            np.asarray(ids, dtype=np.uint32),
            np.asarray(out_a, dtype=np.uint64),
            np.asarray(out_b, dtype=np.uint64),
        )

    if anchor_ids_u32.size:
        idx = np.searchsorted(union_ids_u32, anchor_ids_u32)
        valid_idx = idx < union_ids_u32.size
        if np.any(valid_idx):
            idx = idx[valid_idx]
            anchor_ids_u32 = anchor_ids_u32[valid_idx]
            exact = union_ids_u32[idx] == anchor_ids_u32
            if np.any(exact):
                counts_a_u64 = counts_a_u64.copy()
                counts_b_u64 = counts_b_u64.copy()
                idx = idx[exact]
                sub_a = anchor_a_u64[valid_idx][exact]
                sub_b = anchor_b_u64[valid_idx][exact]
                for pos, left_idx in enumerate(idx):
                    a_val = int(counts_a_u64[left_idx])
                    b_val = int(counts_b_u64[left_idx])
                    counts_a_u64[left_idx] = max(a_val - int(sub_a[pos]), 0)
                    counts_b_u64[left_idx] = max(b_val - int(sub_b[pos]), 0)
    keep = (counts_a_u64 > 0) | (counts_b_u64 > 0)
    return union_ids_u32[keep], counts_a_u64[keep], counts_b_u64[keep]


def count_hashmap_svb_pos(
    token_store: TokenStore,
    seg_starts: np.ndarray,
    seg_ends: np.ndarray,
    seg_weights: np.ndarray,
    pos_allow: np.ndarray,
    stoplist: Optional[Set[int]] = None,
    stream_name: str = "word",
) -> Dict[int, int]:
    if count_segments_svb_pos is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    if stream_name == "word":
        stream = token_store.word_stream
    elif stream_name == "lemma":
        stream = token_store.lemma_stream
    else:
        raise ValueError("stream_name muss word oder lemma sein")
    pos_ids = token_store.pos_ids
    return count_segments_svb_pos(
        stream.offsets,
        stream.data,
        int(stream.block_size),
        int(token_store.token_count),
        pos_ids,
        seg_starts,
        seg_ends,
        seg_weights,
        pos_allow,
        stoplist,
    )


def count_ngrams_svb_fast(
    token_store: TokenStore,
    doc_starts: np.ndarray,
    doc_ends: np.ndarray,
    min_n: int,
    max_n: int,
) -> Dict[tuple[int, ...], int]:
    if count_ngrams_svb is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    stream = token_store.word_stream
    return count_ngrams_svb(
        stream.offsets,
        stream.data,
        int(stream.block_size),
        int(token_store.token_count),
        doc_starts,
        doc_ends,
        int(min_n),
        int(max_n),
    )


def keyness_scores_fast(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
) -> tuple[np.ndarray, np.ndarray]:
    if keyness_scores is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    _, ll = keyness_scores(
        counts_t.astype(np.uint64, copy=False),
        counts_r.astype(np.uint64, copy=False),
        int(total_t),
        int(total_r),
    )
    return keyness_chi2_cell_pooled(counts_t, counts_r, total_t, total_r), ll


def keyness_chi2_cell_pooled(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
) -> np.ndarray:
    """Single target-cell chi-square contribution ``(O - E)^2 / E``.

    This is the Pearson chi-square contribution of the *target* cell only,
    computed against the pooled 2x2 expectation used for the LL/G^2 statistic.
    It is exposed downstream as ``chi2_cell`` and is not a
    mutual-information-squared association measure. The value is
    unsigned, so over- and under-represented items both score positive; use
    ``ll_signed`` for directed keyness ranking.
    """
    target = np.asarray(counts_t, dtype=np.float64)
    reference = np.asarray(counts_r, dtype=np.float64)
    if target.shape != reference.shape:
        raise ValueError("counts_t und counts_r müssen gleich lang sein")
    total = float(int(total_t) + int(total_r))
    if total <= 0.0:
        return np.zeros(target.shape, dtype=np.float64)
    expected_target = float(int(total_t)) * (target + reference) / total
    out = np.zeros(target.shape, dtype=np.float64)
    mask = expected_target > 0.0
    out[mask] = ((target[mask] - expected_target[mask]) ** 2) / expected_target[mask]
    return out


def coverage_sweep_arrays_fast(
    anchors: np.ndarray,
    spans: np.ndarray,
    window_left: int,
    window_right: int,
    sentence_bounds: Optional[np.ndarray],
    within_sentence: bool,
    pair_semantics: bool,
    total_tokens: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if coverage_sweep_arrays_cy is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    def _ensure_contiguous(arr: np.ndarray, dtype: np.dtype) -> np.ndarray:
        out = np.asarray(arr, dtype=dtype)
        if not out.flags.c_contiguous:
            out = np.ascontiguousarray(out, dtype=dtype)
        return out

    if sentence_bounds is None:
        sentence_bounds = np.zeros(0, dtype=np.uint32)
    return coverage_sweep_arrays_cy(
        _ensure_contiguous(anchors, np.int64),
        _ensure_contiguous(spans, np.int64),
        int(window_left),
        int(window_right),
        _ensure_contiguous(sentence_bounds, np.uint32),
        bool(within_sentence),
        bool(pair_semantics),
        int(total_tokens),
    )


def match_arrays_from_positions_fast(
    positions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if match_arrays_from_positions is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    out = np.asarray(positions, dtype=np.uint32)
    if not out.flags.writeable:
        out = np.array(out, copy=True)
    return match_arrays_from_positions(out)


def filter_positions_by_docset_fast(
    positions: np.ndarray,
    doc_bounds: np.ndarray,
    docset_mask: np.ndarray,
) -> np.ndarray:
    pos_u32 = np.asarray(positions, dtype=np.uint32)
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    mask_u8 = np.asarray(docset_mask, dtype=np.uint8)
    if filter_sorted_positions_by_docset_mask_u32 is not None:
        result = filter_sorted_positions_by_docset_mask_u32(pos_u32, bounds_u32, mask_u8)
        # ``None`` means every position matched; hand back the original array
        # zero-copy. The kernel takes read-only memoryviews, so it cannot return
        # the caller's ndarray object itself.
        if result is None:
            return pos_u32
        return np.asarray(result, dtype=np.uint32)
    if pos_u32.size == 0:
        return pos_u32
    doc_ids = np.searchsorted(bounds_u32, pos_u32, side="right") - 1
    keep = mask_u8[doc_ids.astype(np.int64, copy=False)] != 0
    if np.all(keep):
        return pos_u32
    return pos_u32[keep]


def filter_positions_and_values_by_docset_fast(
    positions: np.ndarray,
    values: np.ndarray,
    doc_bounds: np.ndarray,
    docset_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    pos_u32 = np.asarray(positions, dtype=np.uint32)
    vals_i64 = np.asarray(values, dtype=np.int64)
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    mask_u8 = np.asarray(docset_mask, dtype=np.uint8)
    if filter_sorted_positions_and_values_i64_by_docset_mask_u32 is not None:
        result = filter_sorted_positions_and_values_i64_by_docset_mask_u32(
            pos_u32,
            vals_i64,
            bounds_u32,
            mask_u8,
        )
        # ``None`` means every position matched; return the originals zero-copy.
        if result is None:
            return pos_u32, vals_i64
        out_pos, out_vals = result
        return (
            np.asarray(out_pos, dtype=np.uint32),
            np.asarray(out_vals, dtype=np.int64),
        )
    if pos_u32.size == 0:
        return pos_u32, vals_i64
    doc_ids = np.searchsorted(bounds_u32, pos_u32, side="right") - 1
    keep = mask_u8[doc_ids.astype(np.int64, copy=False)] != 0
    if np.all(keep):
        return pos_u32, vals_i64
    return pos_u32[keep], vals_i64[keep]


def unique_doc_ids_from_positions_fast(
    positions: np.ndarray,
    doc_bounds: np.ndarray,
) -> np.ndarray:
    pos_u32 = np.asarray(positions, dtype=np.uint32)
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    if unique_doc_ids_from_sorted_positions_u32 is not None:
        return np.asarray(
            unique_doc_ids_from_sorted_positions_u32(pos_u32, bounds_u32),
            dtype=np.uint32,
        )
    if pos_u32.size == 0:
        return np.zeros(0, dtype=np.uint32)
    doc_ids = np.searchsorted(bounds_u32, pos_u32, side="right") - 1
    if doc_ids.size > 1:
        doc_ids = np.unique(doc_ids)
    return doc_ids.astype(np.uint32, copy=False)


def map_positions_to_doc_ids_fast(
    positions: np.ndarray,
    doc_bounds: np.ndarray,
) -> np.ndarray:
    pos_u32 = np.asarray(positions, dtype=np.uint32)
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    if map_positions_to_doc_ids_i64 is not None:
        return np.asarray(map_positions_to_doc_ids_i64(pos_u32, bounds_u32), dtype=np.int64)
    if pos_u32.size == 0:
        return np.zeros(0, dtype=np.int64)
    return (np.searchsorted(bounds_u32, pos_u32, side="right") - 1).astype(np.int64, copy=False)


def map_positions_to_doc_ids_i32_fast(
    positions: np.ndarray,
    doc_bounds: np.ndarray,
) -> np.ndarray:
    pos_u32 = np.asarray(positions, dtype=np.uint32)
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    if map_positions_to_doc_ids_i32 is not None:
        return np.asarray(map_positions_to_doc_ids_i32(pos_u32, bounds_u32), dtype=np.int32)
    if pos_u32.size == 0:
        return np.zeros(0, dtype=np.int32)
    return (np.searchsorted(bounds_u32, pos_u32, side="right") - 1).astype(np.int32, copy=False)


def position_to_doc_id_fast(
    position: int,
    doc_bounds: np.ndarray,
) -> int:
    bounds_u32 = np.asarray(doc_bounds, dtype=np.uint32)
    pos_u32 = np.uint32(position)
    if position_to_doc_id_i64 is not None:
        return int(position_to_doc_id_i64(pos_u32, bounds_u32))
    return int(np.searchsorted(bounds_u32, pos_u32, side="right") - 1)


def levenshtein_tokens_fast_safe(a: list[str], b: list[str]) -> int:
    if levenshtein_tokens_fast is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    return int(levenshtein_tokens_fast(a, b))


def co_kwic_offset_map_fast(
    term_positions: np.ndarray,
    coll_positions_list: list[np.ndarray],
    left_indices_list: list[np.ndarray],
    right_indices_list: list[np.ndarray],
) -> dict[int, list[int]]:
    if co_kwic_offset_map is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    term_positions = np.asarray(term_positions, dtype=np.int64)
    coll_positions_list = [np.asarray(arr, dtype=np.uint32) for arr in coll_positions_list]
    left_indices_list = [np.asarray(arr, dtype=np.int64) for arr in left_indices_list]
    right_indices_list = [np.asarray(arr, dtype=np.int64) for arr in right_indices_list]
    return co_kwic_offset_map(term_positions, coll_positions_list, left_indices_list, right_indices_list)


def intersect_sorted_limit_fast(a: np.ndarray, b: np.ndarray, limit: int) -> np.ndarray:
    if intersect_sorted_limit is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    return intersect_sorted_limit(
        np.asarray(a, dtype=np.uint32),
        np.asarray(b, dtype=np.uint32),
        int(limit),
    )


def union_sorted_limit_fast(a: np.ndarray, b: np.ndarray, limit: int) -> np.ndarray:
    if union_sorted_limit is None:
        log_path = _write_build_log_path()
        LOGGER.error("Fast Count Extension fehlt. Details: %s", log_path)
        raise RuntimeError("Fast Count Extension fehlt oder konnte nicht gebaut werden")
    return union_sorted_limit(
        np.asarray(a, dtype=np.uint32),
        np.asarray(b, dtype=np.uint32),
        int(limit),
    )


def count_collocates(
    token_store: TokenStore,
    seg_starts: np.ndarray,
    seg_ends: np.ndarray,
    seg_weights: np.ndarray,
    stoplist: Optional[Set[int]] = None,
    attr: str = "word",
    top_n: Optional[int] = None,
    *,
    frequency_top_k: bool = False,
) -> Dict[int, int]:
    """Count collocate candidates.

    ``top_n`` is only safe as a block-top shortcut for raw frequency ranking.
    Association measures (MI, chi2_cell, t, LL, Dice, etc.) are not monotonic in raw
    frequency, so callers must count the full candidate space before scoring.
    """
    if stoplist is None:
        stoplist = {0}
    else:
        stoplist = set(stoplist)
        stoplist.add(0)
    if attr not in {"word", "lemma"}:
        raise ValueError("attr muss word oder lemma sein")
    if top_n is None or top_n <= 0 or not frequency_top_k:
        # Vollzählung für wissenschaftliche Auswertungen (kein Limit).
        return count_hashmap_svb(
            token_store,
            attr,
            seg_starts,
            seg_ends,
            seg_weights,
            stoplist,
        )
    counts = _count_with_block_top(
        token_store,
        attr,
        seg_starts,
        seg_ends,
        seg_weights,
        stoplist,
        int(top_n),
    )
    if counts is None:
        raise RuntimeError("Block-Top Zähler nicht verfügbar. Bitte Index neu bauen.")
    return counts


def _count_with_block_top(
    token_store: TokenStore,
    attr: str,
    seg_starts: np.ndarray,
    seg_ends: np.ndarray,
    seg_weights: np.ndarray,
    stoplist: Set[int],
    top_n: int,
) -> Optional[Dict[int, int]]:
    if count_block_top_svb is not None:
        if attr == "word":
            stream = token_store.word_stream
        elif attr == "lemma":
            stream = token_store.lemma_stream
        else:
            raise ValueError("attr muss word oder lemma sein")
        block = token_store.get_block_top(attr)
        if block is None:
            raise RuntimeError("Block-Top Daten fehlen. Bitte Index neu bauen.")
        offsets, ids, cnts, totals, block_size, _top_k = block
        return count_block_top_svb(
            np.asarray(offsets, dtype=np.uint64),
            np.asarray(ids, dtype=np.uint32),
            np.asarray(cnts, dtype=np.uint32),
            np.asarray(totals, dtype=np.uint32),
            int(block_size),
            int(token_store.token_count),
            np.asarray(stream.offsets, dtype=np.uint64),
            stream.data,
            int(stream.block_size),
            np.asarray(seg_starts, dtype=np.uint32),
            np.asarray(seg_ends, dtype=np.uint32),
            np.asarray(seg_weights, dtype=np.uint32),
            stoplist,
            int(top_n),
        )
    block = token_store.get_block_top(attr)
    if block is None:
        raise RuntimeError("Block-Top Daten fehlen. Bitte Index neu bauen.")
    offsets, ids, cnts, totals, block_size, _top_k = block
    if offsets is None or ids is None or cnts is None or totals is None or block_size <= 0:
        raise RuntimeError("Block-Top Daten ungültig. Bitte Index neu bauen.")
    total_tokens = int(token_store.token_count)

    partial_starts: List[int] = []
    partial_ends: List[int] = []
    partial_weights: List[int] = []
    counts: Dict[int, int] = {}
    other_mass = 0

    for start, end, weight in zip(seg_starts, seg_ends, seg_weights):
        s = int(start)
        e = int(end)
        if e <= s:
            continue
        w = int(weight)
        b_first = (s + block_size - 1) // block_size
        b_last = e // block_size
        if b_first >= b_last:
            partial_starts.append(s)
            partial_ends.append(e)
            partial_weights.append(w)
            continue
        left_end = min(e, b_first * block_size)
        if s < left_end:
            partial_starts.append(s)
            partial_ends.append(left_end)
            partial_weights.append(w)
        right_start = b_last * block_size
        if right_start < e:
            partial_starts.append(right_start)
            partial_ends.append(e)
            partial_weights.append(w)
        for b in range(b_first, b_last):
            off_a = int(offsets[b])
            off_b = int(offsets[b + 1])
            block_len = int(totals[b]) if b < totals.shape[0] else (min((b + 1) * block_size, total_tokens) - b * block_size)
            if off_b <= off_a:
                other_mass += block_len * w
                continue
            blk_ids = ids[off_a:off_b]
            blk_cnts = cnts[off_a:off_b]
            sum_top = int(blk_cnts.sum())
            other_mass += (block_len - sum_top) * w
            for tid, c in zip(blk_ids, blk_cnts):
                t = int(tid)
                if t in stoplist:
                    continue
                counts[t] = counts.get(t, 0) + int(c) * w

    if partial_starts:
        p_starts = np.asarray(partial_starts, dtype=np.int64)
        p_ends = np.asarray(partial_ends, dtype=np.int64)
        p_weights = np.asarray(partial_weights, dtype=np.int64)
        partial = count_hashmap_svb(token_store, attr, p_starts, p_ends, p_weights, stoplist)
        for tid, val in partial.items():
            counts[tid] = counts.get(tid, 0) + int(val)

    if not counts:
        return counts

    if other_mass > 0:
        values = list(counts.values())
        if len(values) > top_n:
            import heapq
            min_top = heapq.nlargest(top_n, values)[-1]
        else:
            min_top = min(values)
        if min_top <= other_mass:
            raise RuntimeError("Block-Top Kandidaten unsicher. Bitte Index neu bauen oder top_n anpassen.")

    return counts
