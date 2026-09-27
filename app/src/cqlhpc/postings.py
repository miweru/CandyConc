from __future__ import annotations

from dataclasses import dataclass
import os
from typing import List, Optional, Sequence

import numpy as np


try:
    from .cython._postings import merge_postings_many as _cy_merge_postings_many  # type: ignore
    from .cython._postings import intersect_sorted_unique as _cy_intersect_sorted_unique  # type: ignore
    from .cython._postings import intersect_shifted as _cy_intersect_shifted  # type: ignore
    from .cython._postings import intersect_shifted_gallop as _cy_intersect_shifted_gallop  # type: ignore
    from .cython._postings import intersect_shifted_many as _cy_intersect_shifted_many  # type: ignore
    from .cython._postings import sentence_ids_for_positions as _cy_sentence_ids_for_positions  # type: ignore
    from .cython._postings import filter_positions_to_sentence_ids as _cy_filter_positions_to_sentence_ids  # type: ignore
    from .cython._postings import sentence_ids_for_min_shift_same_sentence as _cy_sentence_ids_for_min_shift_same_sentence  # type: ignore
    from .cython._postings import sentence_ids_for_shifted_range as _cy_sentence_ids_for_shifted_range  # type: ignore
    from .cython._postings import union_positions_many as _cy_union_positions_many  # type: ignore
    from .cython._postings import positions_to_bitset as _cy_positions_to_bitset  # type: ignore
    from .cython._postings import filter_positions_by_bitset as _cy_filter_positions_by_bitset  # type: ignore
    from .cython._postings import filter_positions_by_bitset_no_bounds as _cy_filter_positions_by_bitset_no_bounds  # type: ignore
    from .cython._postings import bounded_repeat_sentence_matches as _cy_bounded_repeat_sentence_matches  # type: ignore
    from .cython._postings import bounded_repeat_sentence_matches_from_right as _cy_bounded_repeat_sentence_matches_from_right  # type: ignore
    from .cython._postings import unbounded_repeat_sentence_matches as _cy_unbounded_repeat_sentence_matches  # type: ignore
    from .cython._postings import unbounded_repeat_sentence_matches_from_right as _cy_unbounded_repeat_sentence_matches_from_right  # type: ignore
    from .cython._postings import bounded_repeat_sentence_ids as _cy_bounded_repeat_sentence_ids  # type: ignore
    from .cython._postings import postings_to_bitset as _cy_postings_to_bitset  # type: ignore
except Exception:  # pragma: no cover
    _cy_merge_postings_many = None
    _cy_intersect_sorted_unique = None
    _cy_intersect_shifted = None
    _cy_intersect_shifted_gallop = None
    _cy_intersect_shifted_many = None
    _cy_sentence_ids_for_positions = None
    _cy_filter_positions_to_sentence_ids = None
    _cy_sentence_ids_for_min_shift_same_sentence = None
    _cy_sentence_ids_for_shifted_range = None
    _cy_union_positions_many = None
    _cy_positions_to_bitset = None
    _cy_filter_positions_by_bitset = None
    _cy_filter_positions_by_bitset_no_bounds = None
    _cy_bounded_repeat_sentence_matches = None
    _cy_bounded_repeat_sentence_matches_from_right = None
    _cy_unbounded_repeat_sentence_matches = None
    _cy_unbounded_repeat_sentence_matches_from_right = None
    _cy_bounded_repeat_sentence_ids = None
    _cy_postings_to_bitset = None


@dataclass(frozen=True, slots=True)
class PostingsIndex:
    """Adjacency-list style postings storage.

    offsets: int64 array of length (V+1)
    positions: int32 array of length (#postings)
    """

    offsets: np.ndarray  # int64
    positions: np.ndarray  # int32

    def span(self, type_id: int) -> tuple[int, int]:
        a = int(self.offsets[type_id])
        b = int(self.offsets[type_id + 1])
        return a, b

    def list(self, type_id: int) -> np.ndarray:
        a, b = self.span(type_id)
        return self.positions[a:b]

    def length(self, type_id: int) -> int:
        a, b = self.span(type_id)
        return b - a


def _as_i32_array(arr: np.ndarray | Sequence[int]) -> np.ndarray:
    if isinstance(arr, np.ndarray):
        if arr.dtype == np.int32 and arr.flags.c_contiguous:
            return arr
        if arr.dtype == np.uint32 and arr.flags.c_contiguous:
            return arr.view(np.int32)
    return np.asarray(arr, dtype=np.int32)


def merge_postings_many(index: PostingsIndex, type_ids: Sequence[int]) -> np.ndarray:
    """Union merge of postings lists (sorted unique positions)."""
    if len(type_ids) == 0:
        return np.empty((0,), dtype=np.int32)
    if len(type_ids) == 1:
        return index.list(int(type_ids[0]))
    tids = np.asarray(type_ids, dtype=np.int32)
    # The guard sits only on the first branch, which calls the extension.
    # The second branch has a complete fallback (union via heapq, pure
    # numpy), so on an installation without the built extension a guard in
    # front of all branches would make the function raise instead of taking
    # the available path, and every multi-word query would end with HTTP
    # 500. The shipped product has the extension built, so this is about
    # robustness.
    if (
        _cy_merge_postings_many is not None
        and hasattr(index, "offsets")
        and hasattr(index, "positions")
    ):
        return _cy_merge_postings_many(index.offsets, index.positions, tids)
    if hasattr(index, "list"):
        # FastPostingsIndex-style access: materialize member postings, then union natively.
        arrs = [_as_i32_array(index.list(int(tid))) for tid in tids.tolist()]
        arrs = [arr for arr in arrs if arr.size]
        if not arrs:
            return np.empty((0,), dtype=np.int32)
        if len(arrs) == 1:
            return arrs[0].astype(np.int32, copy=False)
        if _cy_union_positions_many is not None:
            return _cy_union_positions_many(arrs)
        import heapq

        heap = []
        for li, arr in enumerate(arrs):
            heap.append((int(arr[0]), li, 0))
        heapq.heapify(heap)
        out: List[int] = []
        last: Optional[int] = None
        while heap:
            val, li, idx = heapq.heappop(heap)
            if last is None or val != last:
                out.append(val)
                last = val
            nxt = idx + 1
            arr = arrs[li]
            if nxt < arr.size:
                heapq.heappush(heap, (int(arr[nxt]), li, nxt))
        return np.asarray(out, dtype=np.int32)
    if _cy_merge_postings_many is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    raise RuntimeError("Postings Index ungültig. Bitte Index neu bauen.")


def intersect_shifted(a: np.ndarray, b: np.ndarray, shift: int) -> np.ndarray:
    """Return positions p in a such that p+shift is in b.

    a and b must be sorted int32 arrays.
    """
    if a.size == 0 or b.size == 0:
        return np.empty((0,), dtype=np.int32)
    if _cy_intersect_shifted is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    return _cy_intersect_shifted(_as_i32_array(a), _as_i32_array(b), int(shift))


def intersect_sorted_unique(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Intersect two sorted unique int32 arrays."""
    if a.size == 0 or b.size == 0:
        return np.empty((0,), dtype=np.int32)
    if _cy_intersect_sorted_unique is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    return _cy_intersect_sorted_unique(_as_i32_array(a), _as_i32_array(b))


def intersect_shifted_gallop(a: np.ndarray, b: np.ndarray, shift: int) -> np.ndarray:
    if a.size == 0 or b.size == 0:
        return np.empty((0,), dtype=np.int32)
    if _cy_intersect_shifted_gallop is not None:
        return _cy_intersect_shifted_gallop(_as_i32_array(a), _as_i32_array(b), int(shift))
    # Fallback: vectorized binary search
    a_i32 = _as_i32_array(a)
    b_i32 = _as_i32_array(b)
    target = a_i32.astype(np.int32, copy=False) + int(shift)
    idx = np.searchsorted(b_i32, target, side="left")
    ok = (idx < b_i32.size) & (b_i32[idx] == target)
    return a_i32[ok].astype(np.int32, copy=False)


def intersect_shifted_many(anchor: np.ndarray, others: Sequence[np.ndarray], shifts: Sequence[int]) -> np.ndarray:
    """Intersect anchor positions with multiple shifted lists."""
    if anchor.size == 0:
        return np.empty((0,), dtype=np.int32)
    if not others:
        return anchor.astype(np.int32, copy=False)
    if len(others) != len(shifts):
        raise ValueError("others/shifts length mismatch")
    if _cy_intersect_shifted_many is not None:
        arrs = [_as_i32_array(a) for a in others]
        return _cy_intersect_shifted_many(_as_i32_array(anchor), arrs, list(shifts))
    # Fallback: sequential intersects in Python
    cand = _as_i32_array(anchor)
    for arr, sh in zip(others, shifts):
        cand = intersect_shifted(cand, _as_i32_array(arr), int(sh))
        if cand.size == 0:
            break
    return cand


def sentence_ids_for_positions(positions: np.ndarray, sent_ends: np.ndarray) -> np.ndarray:
    """Map sorted token positions to sorted unique sentence IDs via linear sweep."""
    if positions.size == 0:
        return np.empty((0,), dtype=np.int32)
    if _cy_sentence_ids_for_positions is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    pos_i32 = positions if isinstance(positions, np.ndarray) and positions.dtype == np.int32 and positions.flags.c_contiguous else np.asarray(positions, dtype=np.int32)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_sentence_ids_for_positions(pos_i32, ends_i32)


def filter_positions_to_sentence_ids(
    positions: np.ndarray,
    sent_ids: np.ndarray,
    sent_starts: np.ndarray,
    sent_ends: np.ndarray,
) -> np.ndarray:
    pos_i32 = positions if isinstance(positions, np.ndarray) and positions.dtype == np.int32 and positions.flags.c_contiguous else np.asarray(positions, dtype=np.int32)
    sent_ids_i32 = sent_ids if isinstance(sent_ids, np.ndarray) and sent_ids.dtype == np.int32 and sent_ids.flags.c_contiguous else np.asarray(sent_ids, dtype=np.int32)
    starts_i32 = sent_starts if isinstance(sent_starts, np.ndarray) and sent_starts.dtype == np.int32 and sent_starts.flags.c_contiguous else np.asarray(sent_starts, dtype=np.int32)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    if pos_i32.size == 0 or sent_ids_i32.size == 0:
        return np.empty((0,), dtype=np.int32)
    if _cy_filter_positions_to_sentence_ids is None:
        starts = starts_i32[sent_ids_i32]
        ends = ends_i32[sent_ids_i32]
        lo = np.searchsorted(pos_i32, starts, side="left")
        hi = np.searchsorted(pos_i32, ends, side="left")
        counts = hi - lo
        total = int(counts.sum(dtype=np.int64))
        if total <= 0:
            return np.empty((0,), dtype=np.int32)
        out = np.empty((total,), dtype=np.int32)
        k = 0
        for a, b in zip(lo.tolist(), hi.tolist()):
            if b <= a:
                continue
            n = int(b - a)
            out[k : k + n] = pos_i32[a:b]
            k += n
        return out if k == total else out[:k]
    return _cy_filter_positions_to_sentence_ids(pos_i32, sent_ids_i32, starts_i32, ends_i32)


def _sentence_ids_for_shifted_range_legacy(
    anchor_i32: np.ndarray,
    other_i32: np.ndarray,
    min_shift: int,
    max_shift: int,
    ends_i32: np.ndarray,
) -> np.ndarray:
    hits = []
    for shift in range(int(min_shift), int(max_shift) + 1):
        arr = intersect_shifted(anchor_i32, other_i32, shift)
        if arr.size:
            hits.append(arr)
    if not hits:
        return np.empty((0,), dtype=np.int32)
    merged = union_positions_many(hits)
    return sentence_ids_for_positions(merged, ends_i32)


def sentence_ids_for_min_shift_same_sentence(
    anchor: np.ndarray,
    other: np.ndarray,
    min_shift: int,
    sent_ends: np.ndarray,
) -> np.ndarray:
    if _cy_sentence_ids_for_min_shift_same_sentence is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    if anchor.size == 0 or other.size == 0:
        return np.empty((0,), dtype=np.int32)
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    other_i32 = other if isinstance(other, np.ndarray) and other.dtype == np.int32 and other.flags.c_contiguous else np.asarray(other, dtype=np.int32)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_sentence_ids_for_min_shift_same_sentence(anchor_i32, other_i32, int(min_shift), ends_i32)


def sentence_ids_for_shifted_range(
    anchor: np.ndarray,
    other: np.ndarray,
    min_shift: int,
    max_shift: int,
    sent_ends: np.ndarray,
) -> np.ndarray:
    if anchor.size == 0 or other.size == 0:
        return np.empty((0,), dtype=np.int32)
    if min_shift > max_shift:
        return np.empty((0,), dtype=np.int32)
    if _cy_sentence_ids_for_shifted_range is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    other_i32 = other if isinstance(other, np.ndarray) and other.dtype == np.int32 and other.flags.c_contiguous else np.asarray(other, dtype=np.int32)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    # Der Satz-Prefilter darf false positives liefern, aber keine false negatives.
    # Der exakte Legacy-Pfad ist auf dem Vollindex bis mittlere Fensterbreiten klar besser.
    legacy_width = max(1, int(os.environ.get("CANDYCONC_CQLHPC_SHIFT_SENT_LEGACY_MAX_WIDTH", "24")))
    if int(max_shift) - int(min_shift) + 1 <= legacy_width:
        return _sentence_ids_for_shifted_range_legacy(anchor_i32, other_i32, int(min_shift), int(max_shift), ends_i32)
    return _cy_sentence_ids_for_shifted_range(anchor_i32, other_i32, int(min_shift), int(max_shift), ends_i32)

def union_positions_many(arrays: Sequence[np.ndarray]) -> np.ndarray:
    """Union-merge multiple sorted int32 arrays."""
    if not arrays:
        return np.empty((0,), dtype=np.int32)
    arrs = [_as_i32_array(a) for a in arrays if a is not None]
    if not arrs:
        return np.empty((0,), dtype=np.int32)
    if len(arrs) == 1:
        return arrs[0]
    if _cy_union_positions_many is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    return _cy_union_positions_many(arrs)


def positions_to_bitset(positions: np.ndarray, n_tokens: int) -> np.ndarray:
    if _cy_positions_to_bitset is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    pos_i32 = positions if isinstance(positions, np.ndarray) and positions.dtype == np.int32 and positions.flags.c_contiguous else np.asarray(positions, dtype=np.int32)
    return _cy_positions_to_bitset(pos_i32, int(n_tokens))


def filter_positions_by_bitset(anchor: np.ndarray, bitset: np.ndarray, shift: int, n_tokens: int) -> np.ndarray:
    if _cy_filter_positions_by_bitset is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    bitset_u8 = bitset if isinstance(bitset, np.ndarray) and bitset.dtype == np.uint8 and bitset.flags.c_contiguous else np.asarray(bitset, dtype=np.uint8)
    return _cy_filter_positions_by_bitset(
        anchor_i32,
        bitset_u8,
        int(shift),
        int(n_tokens),
    )


def filter_positions_by_bitset_no_bounds(anchor: np.ndarray, bitset: np.ndarray, shift: int) -> np.ndarray:
    if _cy_filter_positions_by_bitset_no_bounds is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    bitset_u8 = bitset if isinstance(bitset, np.ndarray) and bitset.dtype == np.uint8 and bitset.flags.c_contiguous else np.asarray(bitset, dtype=np.uint8)
    return _cy_filter_positions_by_bitset_no_bounds(anchor_i32, bitset_u8, int(shift))


def bounded_repeat_sentence_matches(
    anchor: np.ndarray,
    middle_bitset: np.ndarray,
    right_bitset: np.ndarray,
    min_rep: int,
    max_rep: int,
    sent_ends: np.ndarray,
    max_matches: int,
    *,
    include_sids: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _cy_bounded_repeat_sentence_matches is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    middle_u8 = middle_bitset if isinstance(middle_bitset, np.ndarray) and middle_bitset.dtype == np.uint8 and middle_bitset.flags.c_contiguous else np.asarray(middle_bitset, dtype=np.uint8)
    right_u8 = right_bitset if isinstance(right_bitset, np.ndarray) and right_bitset.dtype == np.uint8 and right_bitset.flags.c_contiguous else np.asarray(right_bitset, dtype=np.uint8)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_bounded_repeat_sentence_matches(
        anchor_i32,
        middle_u8,
        right_u8,
        int(min_rep),
        int(max_rep),
        ends_i32,
        int(max_matches),
        bool(include_sids),
    )


def unbounded_repeat_sentence_matches(
    anchor: np.ndarray,
    right_bitset: np.ndarray,
    min_count: int,
    sent_ends: np.ndarray,
    max_matches: int,
    *,
    include_sids: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _cy_unbounded_repeat_sentence_matches is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    right_u8 = right_bitset if isinstance(right_bitset, np.ndarray) and right_bitset.dtype == np.uint8 and right_bitset.flags.c_contiguous else np.asarray(right_bitset, dtype=np.uint8)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_unbounded_repeat_sentence_matches(
        anchor_i32,
        right_u8,
        int(min_count),
        ends_i32,
        int(max_matches),
        bool(include_sids),
    )


def bounded_repeat_sentence_matches_from_right(
    right: np.ndarray,
    left_bitset: np.ndarray,
    middle_bitset: np.ndarray,
    min_rep: int,
    max_rep: int,
    sent_ends: np.ndarray,
    max_matches: int,
    *,
    include_sids: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _cy_bounded_repeat_sentence_matches_from_right is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    right_i32 = right if isinstance(right, np.ndarray) and right.dtype == np.int32 and right.flags.c_contiguous else np.asarray(right, dtype=np.int32)
    left_u8 = left_bitset if isinstance(left_bitset, np.ndarray) and left_bitset.dtype == np.uint8 and left_bitset.flags.c_contiguous else np.asarray(left_bitset, dtype=np.uint8)
    middle_u8 = middle_bitset if isinstance(middle_bitset, np.ndarray) and middle_bitset.dtype == np.uint8 and middle_bitset.flags.c_contiguous else np.asarray(middle_bitset, dtype=np.uint8)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_bounded_repeat_sentence_matches_from_right(
        right_i32,
        left_u8,
        middle_u8,
        int(min_rep),
        int(max_rep),
        ends_i32,
        int(max_matches),
        bool(include_sids),
    )


def unbounded_repeat_sentence_matches_from_right(
    right: np.ndarray,
    left_bitset: np.ndarray,
    min_count: int,
    sent_ends: np.ndarray,
    max_matches: int,
    *,
    include_sids: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if _cy_unbounded_repeat_sentence_matches_from_right is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    right_i32 = right if isinstance(right, np.ndarray) and right.dtype == np.int32 and right.flags.c_contiguous else np.asarray(right, dtype=np.int32)
    left_u8 = left_bitset if isinstance(left_bitset, np.ndarray) and left_bitset.dtype == np.uint8 and left_bitset.flags.c_contiguous else np.asarray(left_bitset, dtype=np.uint8)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_unbounded_repeat_sentence_matches_from_right(
        right_i32,
        left_u8,
        int(min_count),
        ends_i32,
        int(max_matches),
        bool(include_sids),
    )


def bounded_repeat_sentence_ids(
    anchor: np.ndarray,
    middle_bitset: np.ndarray,
    right_bitset: np.ndarray,
    min_rep: int,
    max_rep: int,
    sent_ends: np.ndarray,
) -> np.ndarray:
    if _cy_bounded_repeat_sentence_ids is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    anchor_i32 = anchor if isinstance(anchor, np.ndarray) and anchor.dtype == np.int32 and anchor.flags.c_contiguous else np.asarray(anchor, dtype=np.int32)
    middle_u8 = middle_bitset if isinstance(middle_bitset, np.ndarray) and middle_bitset.dtype == np.uint8 and middle_bitset.flags.c_contiguous else np.asarray(middle_bitset, dtype=np.uint8)
    right_u8 = right_bitset if isinstance(right_bitset, np.ndarray) and right_bitset.dtype == np.uint8 and right_bitset.flags.c_contiguous else np.asarray(right_bitset, dtype=np.uint8)
    ends_i32 = sent_ends if isinstance(sent_ends, np.ndarray) and sent_ends.dtype == np.int32 and sent_ends.flags.c_contiguous else np.asarray(sent_ends, dtype=np.int32)
    return _cy_bounded_repeat_sentence_ids(
        anchor_i32,
        middle_u8,
        right_u8,
        int(min_rep),
        int(max_rep),
        ends_i32,
    )


def postings_to_bitset(index: PostingsIndex, type_ids: np.ndarray, n_tokens: int) -> np.ndarray:
    if _cy_postings_to_bitset is None:
        raise RuntimeError("CQLHPC Postings Extension fehlt. Bitte Extension bauen.")
    tids = type_ids if isinstance(type_ids, np.ndarray) and type_ids.dtype == np.int32 and type_ids.flags.c_contiguous else np.asarray(type_ids, dtype=np.int32)
    return _cy_postings_to_bitset(index.offsets, index.positions, tids, int(n_tokens))


def _merge_two_sorted(a: List[int], b: List[int]) -> List[int]:
    i = j = 0
    out: List[int] = []
    last: Optional[int] = None
    while i < len(a) and j < len(b):
        va = a[i]
        vb = b[j]
        if va == vb:
            v = va
            i += 1
            j += 1
        elif va < vb:
            v = va
            i += 1
        else:
            v = vb
            j += 1
        if last != v:
            out.append(v)
            last = v
    while i < len(a):
        v = a[i]
        i += 1
        if last != v:
            out.append(v)
            last = v
    while j < len(b):
        v = b[j]
        j += 1
        if last != v:
            out.append(v)
            last = v
    return out
