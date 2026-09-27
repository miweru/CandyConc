from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Callable
from collections import OrderedDict
import hashlib
import threading
import time

import numpy as np

from .ast import Alt, MetaCond, MetaExpr, Node, Quant, Seq, Tok, Within, Where, TokenClause
from .ast import meta_cond_menge
from .normalize import normalize
from .parser import parse_cql
from .corpus import Corpus
from .postings import (
    merge_postings_many,
    intersect_sorted_unique,
    sentence_ids_for_positions,
    filter_positions_to_sentence_ids,
    sentence_ids_for_shifted_range,
    sentence_ids_for_min_shift_same_sentence,
    intersect_shifted,
    intersect_shifted_gallop,
    intersect_shifted_many,
    union_positions_many,
    positions_to_bitset,
    filter_positions_by_bitset_no_bounds,
    bounded_repeat_sentence_matches,
    bounded_repeat_sentence_matches_from_right,
    unbounded_repeat_sentence_matches,
    unbounded_repeat_sentence_matches_from_right,
    bounded_repeat_sentence_ids,
    postings_to_bitset,
)
from .predicates import (
    compile_clause,
    best_indexable,
    Indexable,
    CompiledClause,
    _value_to_type_ids,
    _check_closed_class_value,
)
from .errors import (
    BRANCH_LOCAL_WHERE,
    NO_HITS as _NO_HITS,
    UNKNOWN_ATTRIBUTE,
    UNRESOLVABLE as _UNRESOLVABLE,
    EmptyMatchError,
    UnresolvableConditionError,
    lt,
)
from .planner import plan_sequence, explain_plan, validate_plan, ClausePlan
from .config import get_int, get_float, get_bool
from .nfa import _cy_nfa_find_matches, _cy_nfa_find_matches_many, compile_nfa, find_nonoverlapping_matches


@dataclass(frozen=True, slots=True)
class SearchOptions:
    max_matches: int = 20000
    within_sentences_by_default: bool = True
    progress_cb: Callable | None = None
    docset_mask: Optional[np.ndarray] = None


@dataclass(frozen=True, slots=True)
class Match:
    start: int
    end: int
    sentence_id: Optional[int] = None
    doc_id: Optional[int] = None


@dataclass(frozen=True, slots=True)
class CountResult:
    total: int
    partial: bool = False
    limit: Optional[int] = None


_CACHE_MISSING = object()
_MAX_I32 = 2_147_483_647

# Returned by ``_simple_indexable_from_clause(allow_empty=True)`` for an
# out-of-vocabulary operand. It signals "this operand contributes no postings"
# so an alternation can absorb it (union over the remaining operands) instead of
# the whole query raising. Distinct object identity keeps it unambiguous against
# a genuine ``(attr, ids, est)`` result.
_EMPTY_OPERAND = ("", np.empty((0,), dtype=np.int32), 0)


def _u32_to_i32_safe(arr: np.ndarray) -> np.ndarray:
    """Convert backend uint32 positions to int32 without silent wraparound."""
    arr = np.asarray(arr)
    if arr.size and int(arr[-1]) > _MAX_I32:
        raise RuntimeError(
            f"Token-Position {int(arr[-1]):,} überschreitet die int32-Grenze "
            f"({_MAX_I32:,}). Der Index überschreitet die sichere Korpusgröße."
        )
    return arr.astype(np.int32, copy=False)


def _as_nonnegative_uint32(arr: np.ndarray) -> np.ndarray:
    if isinstance(arr, np.ndarray) and arr.dtype == np.uint32:
        return arr
    if isinstance(arr, np.ndarray) and arr.dtype == np.int32 and arr.flags.c_contiguous:
        return arr.view(np.uint32)
    return np.asarray(arr, dtype=np.uint32)


def _ids_cache_key(ids: np.ndarray) -> object:
    ids_i32 = np.asarray(ids, dtype=np.int32, order="C")
    if ids_i32.size == 1:
        return int(ids_i32[0])
    return ids_i32.tobytes()


class _LRUCache:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._data: OrderedDict[str, Any] = OrderedDict()
        # These caches are shared across the asyncio.to_thread threadpool; without
        # a lock a concurrent check-then-pop races into KeyError and the move-to-end
        # corrupts the OrderedDict.
        self._lock = threading.RLock()

    def get(self, key: str):
        if self.maxsize <= 0:
            return _CACHE_MISSING
        with self._lock:
            if key not in self._data:
                return _CACHE_MISSING
            val = self._data.pop(key)
            self._data[key] = val
            return val

    def set(self, key: str, value: Any) -> None:
        if self.maxsize <= 0:
            return
        with self._lock:
            if key in self._data:
                self._data.pop(key)
            self._data[key] = value
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)


class _ByteLRUCache:
    def __init__(self, max_bytes: int, max_entries: int = 0):
        self.max_bytes = max_bytes
        self.max_entries = max_entries if max_entries > 0 else 0
        self._data: OrderedDict[Any, Tuple[Any, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def _estimate_bytes(self, value: Any) -> int:
        if value is None:
            return 0
        if hasattr(value, "nbytes"):
            try:
                return int(value.nbytes)  # type: ignore[attr-defined]
            except Exception:
                return 0
        if isinstance(value, (bytes, bytearray, memoryview)):
            return len(value)
        return 0

    def get(self, key: str):
        if self.max_bytes <= 0 and self.max_entries <= 0:
            return _CACHE_MISSING
        with self._lock:
            if key not in self._data:
                return _CACHE_MISSING
            val, size = self._data.pop(key)
            self._data[key] = (val, size)
            return val

    def set(self, key: str, value: Any) -> None:
        if self.max_bytes <= 0 and self.max_entries <= 0:
            return
        size = self._estimate_bytes(value)
        if self.max_bytes > 0 and size > self.max_bytes:
            return
        with self._lock:
            if key in self._data:
                old_val, old_size = self._data.pop(key)
                self._bytes -= old_size
            self._data[key] = (value, size)
            self._bytes += size
            self._evict()

    def _evict(self) -> None:
        # Caller holds self._lock.
        while True:
            if self.max_entries > 0 and len(self._data) > self.max_entries:
                _, (_, size) = self._data.popitem(last=False)
                self._bytes -= size
                continue
            if self.max_bytes > 0 and self._bytes > self.max_bytes and self._data:
                _, (_, size) = self._data.popitem(last=False)
                self._bytes -= size
                continue
            break


class _PreparedSentenceMatcher:
    def __init__(
        self,
        nfa,
        corpus: Corpus,
        cand_sids: np.ndarray,
        *,
        seg_starts: Optional[np.ndarray] = None,
        seg_ends: Optional[np.ndarray] = None,
    ):
        # ``cand_sids`` are *segment* ids. By default a segment is a sentence
        # (``corpus.sent_starts/sent_ends``); pass ``seg_starts``/``seg_ends`` =
        # ``corpus.doc_starts/doc_ends`` (with ``cand_sids`` being document ids)
        # to verify NFA matches over whole-document spans. The matcher only ever
        # reads the segment-bound arrays it is given, so the same batching /
        # packed-decode machinery scopes correctly to either granularity. This
        # is what makes ``within(<doc>)`` match spans that cross a sentence
        # boundary inside one document rather than collapsing to per-sentence
        # (a strict subset of ``within(<s>)``).
        self.nfa = nfa
        self.corpus = corpus
        self.sid_array = cand_sids
        self.sid_view = memoryview(cand_sids)
        if seg_starts is None:
            seg_starts = corpus.sent_starts
        if seg_ends is None:
            seg_ends = corpus.sent_ends
        self.sent_starts_arr = seg_starts
        self.sent_ends_arr = seg_ends
        self.sent_starts = memoryview(seg_starts)
        self.sent_ends = memoryview(seg_ends)
        cond_attr = getattr(nfa, "cond_attr", None)
        self.need_lemma = cond_attr is not None and bool(np.any(cond_attr == 0))
        self.need_pos = cond_attr is not None and bool(np.any(cond_attr == 1))
        self.need_word = cond_attr is not None and bool(np.any(cond_attr == 2))
        self._dummy_attr = np.zeros((1,), dtype=np.int32)
        self.lemma = corpus.attr("lemma") if self.need_lemma else None
        self.pos = corpus.attr("pos") if self.need_pos else None
        self.word = corpus.attr("word") if self.need_word else None
        self.use_direct = (
            _cy_nfa_find_matches is not None
            and (self.lemma is None or isinstance(self.lemma, np.ndarray))
            and (self.pos is None or isinstance(self.pos, np.ndarray))
            and (self.word is None or isinstance(self.word, np.ndarray))
        )
        self.use_batched = _cy_nfa_find_matches is not None and not self.use_direct
        needed_attrs = int(self.need_lemma) + int(self.need_pos) + int(self.need_word)
        self.enable_packed_batches = get_bool("CANDYCONC_CQLHPC_VERIFY_PACKED_BATCHES", True)
        if self.use_batched and self.enable_packed_batches:
            if needed_attrs <= 1:
                default_batch_sents = 512
                default_token_budget = 655360
            elif needed_attrs == 2:
                default_batch_sents = 512
                default_token_budget = 655360
            else:
                default_batch_sents = 192
                default_token_budget = 49152
        else:
            default_batch_sents = 256 if needed_attrs <= 1 else 128
            default_token_budget = 8192
        self.batch_size = max(1, get_int("CANDYCONC_CQLHPC_VERIFY_BATCH_SENTS", default_batch_sents))
        self.token_budget = max(1, get_int("CANDYCONC_CQLHPC_VERIFY_BATCH_TOKENS", default_token_budget))
        self.packed_gap_ratio = max(1.0, get_float("CANDYCONC_CQLHPC_VERIFY_PACKED_GAP_RATIO", 8.0))
        self.packed_min_sentences = max(2, get_int("CANDYCONC_CQLHPC_VERIFY_PACKED_MIN_SENTS", 16))
        self.packed_fuse_gap = max(0, get_int("CANDYCONC_CQLHPC_VERIFY_PACKED_FUSE_GAP", 32))
        self.packed_fuse_overhead = max(1.0, get_float("CANDYCONC_CQLHPC_VERIFY_PACKED_FUSE_OVERHEAD", 1.05))
        self._batch_lo = 0
        self._batch_hi = 0
        self._batch_start = 0
        self._batch_lemma: Optional[np.ndarray] = None
        self._batch_pos: Optional[np.ndarray] = None
        self._batch_word: Optional[np.ndarray] = None
        self._batch_results: Optional[List[Tuple[int, List[Tuple[int, int]]]]] = None
        self._batch_deltas: Optional[np.ndarray] = None
        self._batch_sids = np.empty((0,), dtype=np.int32)
        self._batch_starts = np.empty((0,), dtype=np.int32)
        self._batch_ends = np.empty((0,), dtype=np.int32)
        self._batch_starts_buf = np.empty(self.batch_size, dtype=np.int32)
        self._batch_ends_buf = np.empty(self.batch_size, dtype=np.int32)
        self._batch_lengths_buf = np.empty(self.batch_size, dtype=np.int32)
        self._packed_starts_buf = np.empty(self.batch_size, dtype=np.int32)
        self._packed_ends_buf = np.empty(self.batch_size, dtype=np.int32)
        self._decode_starts_buf = np.empty(self.batch_size, dtype=np.int32)
        self._decode_ends_buf = np.empty(self.batch_size, dtype=np.int32)
        self._batch_deltas_buf = np.empty(self.batch_size, dtype=np.int32)
        self._rel_starts_buf = np.empty(self.batch_size, dtype=np.int32)
        self._rel_ends_buf = np.empty(self.batch_size, dtype=np.int32)

    def __len__(self) -> int:
        return len(self.sid_view)

    def _can_pack_attr(self, accessor) -> bool:
        return accessor is None or callable(getattr(accessor, "get_ranges_packed_i32", None))

    def _get_packed_attr(self, accessor, starts: np.ndarray, ends: np.ndarray, total_len: int) -> np.ndarray:
        if accessor is None:
            return self._dummy_attr
        getter_fast = getattr(accessor, "get_ranges_packed_sorted_known_i32_fast", None)
        if callable(getter_fast):
            return getter_fast(starts, ends, int(total_len))
        getter_known = getattr(accessor, "get_ranges_packed_sorted_known_i32", None)
        if callable(getter_known):
            return getter_known(starts, ends, int(total_len))
        getter = getattr(accessor, "get_ranges_packed_sorted_i32", None)
        if callable(getter):
            return getter(starts, ends)
        return accessor.get_ranges_packed_i32(starts, ends)

    def _translate_batch_spans(self, batch_idx: int, spans, *, absolute_batch_results: bool = False):
        if not spans:
            return spans
        if absolute_batch_results:
            return spans
        if self._batch_deltas is not None:
            delta = int(self._batch_deltas[batch_idx])
            if delta:
                return [(a + delta, b + delta) for a, b in spans]
            return spans
        if self._batch_start:
            return [(a + self._batch_start, b + self._batch_start) for a, b in spans]
        return spans

    def _find_batch_spans(self, batch_idx: int):
        assert self._batch_results is not None
        for off, spans in self._batch_results:
            if off == batch_idx:
                return spans
            if off > batch_idx:
                break
        return []

    def _run_direct(
        self,
        lemma: np.ndarray,
        pos: np.ndarray,
        word: np.ndarray,
        start: int,
        end: int,
        max_matches: int,
    ):
        if _cy_nfa_find_matches is None:
            return find_nonoverlapping_matches(self.nfa, self.corpus, start, end, max_matches=max_matches)
        return _cy_nfa_find_matches(
            lemma,
            pos,
            word,
            int(start),
            int(end),
            self.nfa.start_bits,
            self.nfa.accept_bits,
            self.nfa.state_edge_off,
            self.nfa.edge_pred,
            self.nfa.edge_tgt,
            self.nfa.start_pred_ids,
            self.nfa.pred_cond_off,
            self.nfa.cond_attr,
            self.nfa.cond_op,
            self.nfa.cond_val_off,
            self.nfa.cond_val_len,
            self.nfa.values,
            int(max_matches),
        )

    def _ensure_batch(self, idx: int) -> None:
        if idx >= self._batch_lo and idx < self._batch_hi:
            return
        sid = int(self.sid_view[idx])
        block_start = int(self.sent_starts[sid])
        limit = len(self.sid_view)
        max_hi = min(limit, idx + self.batch_size)
        batch_sids_window = self.sid_array[idx:max_hi]
        batch_ends = self._batch_ends_buf[: batch_sids_window.shape[0]]
        np.take(self.sent_ends_arr, batch_sids_window, out=batch_ends)
        n_batch = int(np.searchsorted(batch_ends, block_start + self.token_budget, side="right"))
        if n_batch <= 0:
            n_batch = 1
        hi = idx + n_batch
        batch_sids = batch_sids_window[:n_batch]
        batch_ends = batch_ends[:n_batch]
        block_end = int(batch_ends[-1])
        batch_starts = self._batch_starts_buf[:n_batch]
        np.take(self.sent_starts_arr, batch_sids, out=batch_starts)
        batch_lengths = self._batch_lengths_buf[:n_batch]
        np.subtract(batch_ends, batch_starts, out=batch_lengths)
        block_end = int(batch_ends[-1])
        batch_token_count = int(batch_lengths.sum(dtype=np.int64))
        packed_gap_ratio = float(block_end - block_start) / float(max(batch_token_count, 1))
        use_packed = (
            self.use_batched
            and self.enable_packed_batches
            and (hi - idx) >= self.packed_min_sentences
            and batch_token_count > 0
            and packed_gap_ratio >= self.packed_gap_ratio
            and self._can_pack_attr(self.lemma if self.need_lemma else None)
            and self._can_pack_attr(self.pos if self.need_pos else None)
            and self._can_pack_attr(self.word if self.need_word else None)
        )
        self._batch_lo = idx
        self._batch_hi = hi
        self._batch_start = 0 if use_packed else block_start
        self._batch_sids = batch_sids
        self._batch_starts = batch_starts
        self._batch_ends = batch_ends
        if use_packed:
            packed_ends = self._packed_ends_buf[:n_batch]
            packed_starts = self._packed_starts_buf[:n_batch]
            decode_starts = self._decode_starts_buf[:n_batch]
            decode_ends = self._decode_ends_buf[:n_batch]
            extra_budget = int(batch_token_count * (self.packed_fuse_overhead - 1.0))
            fused_extra = 0
            decode_count = 0
            run_start = int(batch_starts[0])
            run_end = int(batch_ends[0])
            run_offset = 0
            packed_starts[0] = 0
            packed_ends[0] = int(batch_lengths[0])
            for off in range(1, n_batch):
                start_i = int(batch_starts[off])
                end_i = int(batch_ends[off])
                gap_i = start_i - run_end
                if (
                    gap_i >= 0
                    and gap_i <= self.packed_fuse_gap
                    and fused_extra + gap_i <= extra_budget
                ):
                    fused_extra += gap_i
                    packed_starts[off] = run_offset + (start_i - run_start)
                    packed_ends[off] = run_offset + (end_i - run_start)
                    run_end = end_i
                    continue
                decode_starts[decode_count] = run_start
                decode_ends[decode_count] = run_end
                decode_count += 1
                run_offset += run_end - run_start
                run_start = start_i
                run_end = end_i
                packed_starts[off] = run_offset
                packed_ends[off] = run_offset + int(batch_lengths[off])
            decode_starts[decode_count] = run_start
            decode_ends[decode_count] = run_end
            decode_count += 1
            decode_starts = decode_starts[:decode_count]
            decode_ends = decode_ends[:decode_count]
            packed_total_len = run_offset + (run_end - run_start)
            self._batch_deltas = self._batch_deltas_buf[:n_batch]
            np.subtract(batch_starts, packed_starts, out=self._batch_deltas)
            if self.need_lemma and self.lemma is not None:
                self._batch_lemma = self._get_packed_attr(self.lemma, decode_starts, decode_ends, packed_total_len)
            else:
                self._batch_lemma = self._dummy_attr
            if self.need_pos and self.pos is not None:
                self._batch_pos = self._get_packed_attr(self.pos, decode_starts, decode_ends, packed_total_len)
            else:
                self._batch_pos = self._dummy_attr
            if self.need_word and self.word is not None:
                self._batch_word = self._get_packed_attr(self.word, decode_starts, decode_ends, packed_total_len)
            else:
                self._batch_word = self._dummy_attr
        else:
            self._batch_deltas = None
            if self.need_lemma and self.lemma is not None:
                self._batch_lemma = np.asarray(self.lemma[block_start:block_end], dtype=np.int32)
            else:
                self._batch_lemma = self._dummy_attr
            if self.need_pos and self.pos is not None:
                self._batch_pos = np.asarray(self.pos[block_start:block_end], dtype=np.int32)
            else:
                self._batch_pos = self._dummy_attr
            if self.need_word and self.word is not None:
                self._batch_word = np.asarray(self.word[block_start:block_end], dtype=np.int32)
            else:
                self._batch_word = self._dummy_attr
        self._batch_results = None
        if _cy_nfa_find_matches_many is None:
            return
        if use_packed:
            starts = packed_starts
            ends = packed_ends
            base_offset = 0
        else:
            starts = self._rel_starts_buf[:n_batch]
            ends = self._rel_ends_buf[:n_batch]
            np.subtract(batch_starts, block_start, out=starts)
            np.subtract(batch_ends, block_start, out=ends)
            base_offset = int(block_start)
        results = _cy_nfa_find_matches_many(
            self._batch_lemma,
            self._batch_pos,
            self._batch_word,
            starts,
            ends,
            self.nfa.start_bits,
            self.nfa.accept_bits,
            self.nfa.state_edge_off,
            self.nfa.edge_pred,
            self.nfa.edge_tgt,
            self.nfa.start_pred_ids,
            self.nfa.pred_cond_off,
            self.nfa.cond_attr,
            self.nfa.cond_op,
            self.nfa.cond_val_off,
            self.nfa.cond_val_len,
            self.nfa.values,
            2147483647,
            base_offset,
            self._batch_deltas,
        )
        self._batch_results = results

    def spans_for_index(self, idx: int, max_matches: int):
        sid = int(self.sid_view[idx])
        start = int(self.sent_starts[sid])
        end = int(self.sent_ends[sid])
        if self.use_direct:
            lemma = self.lemma if isinstance(self.lemma, np.ndarray) else self._dummy_attr
            pos = self.pos if isinstance(self.pos, np.ndarray) else self._dummy_attr
            word = self.word if isinstance(self.word, np.ndarray) else self._dummy_attr
            spans = self._run_direct(lemma, pos, word, start, end, max_matches)
            return sid, spans
        if self.use_batched:
            self._ensure_batch(idx)
            batch_off = idx - self._batch_lo
            if self._batch_results is not None:
                spans = self._translate_batch_spans(batch_off, self._find_batch_spans(batch_off), absolute_batch_results=True)
                return sid, spans
            assert self._batch_lemma is not None
            assert self._batch_pos is not None
            assert self._batch_word is not None
            start = int(self._batch_starts[batch_off])
            end = int(self._batch_ends[batch_off])
            local_start = start - self._batch_start
            local_end = end - self._batch_start
            spans = self._run_direct(
                self._batch_lemma,
                self._batch_pos,
                self._batch_word,
                local_start,
                local_end,
                max_matches,
            )
            spans = self._translate_batch_spans(batch_off, spans)
            return sid, spans
        spans = find_nonoverlapping_matches(self.nfa, self.corpus, start, end, max_matches=max_matches)
        return sid, spans

    def iter_sentence_spans(self, max_matches: int):
        if self.use_batched:
            idx = 0
            limit = len(self.sid_view)
            while idx < limit:
                self._ensure_batch(idx)
                hi = self._batch_hi
                batch_sids = self._batch_sids
                if self._batch_results is not None:
                    result_idx = 0
                    result_len = len(self._batch_results)
                    for off in range(hi - idx):
                        if result_idx < result_len:
                            cur_off, cur_spans = self._batch_results[result_idx]
                            if cur_off == off:
                                yield int(batch_sids[off]), self._translate_batch_spans(
                                    off,
                                    cur_spans,
                                    absolute_batch_results=True,
                                )
                                result_idx += 1
                                continue
                        yield int(batch_sids[off]), []
                    idx = hi
                    continue
                assert self._batch_lemma is not None
                assert self._batch_pos is not None
                assert self._batch_word is not None
                batch_starts = self._batch_starts
                batch_ends = self._batch_ends
                for off in range(hi - idx):
                    sid = int(batch_sids[off])
                    start = int(batch_starts[off])
                    end = int(batch_ends[off])
                    local_start = start - self._batch_start
                    local_end = end - self._batch_start
                    spans = self._run_direct(
                        self._batch_lemma,
                        self._batch_pos,
                        self._batch_word,
                        local_start,
                        local_end,
                        max_matches,
                    )
                    spans = self._translate_batch_spans(off, spans)
                    yield sid, spans
                idx = hi
            return

        for idx in range(len(self.sid_view)):
            yield self.spans_for_index(idx, max_matches)

    def iter_nonempty_sentence_spans(self, max_matches: int):
        if self.use_batched:
            idx = 0
            limit = len(self.sid_view)
            while idx < limit:
                self._ensure_batch(idx)
                hi = self._batch_hi
                batch_sids = self._batch_sids
                if self._batch_results is not None:
                    for off, spans in self._batch_results:
                        yield int(batch_sids[off]), self._translate_batch_spans(
                            off,
                            spans,
                            absolute_batch_results=True,
                        )
                    idx = hi
                    continue
                assert self._batch_lemma is not None
                assert self._batch_pos is not None
                assert self._batch_word is not None
                batch_starts = self._batch_starts
                batch_ends = self._batch_ends
                for off in range(hi - idx):
                    sid = int(batch_sids[off])
                    start = int(batch_starts[off])
                    end = int(batch_ends[off])
                    local_start = start - self._batch_start
                    local_end = end - self._batch_start
                    spans = self._run_direct(
                        self._batch_lemma,
                        self._batch_pos,
                        self._batch_word,
                        local_start,
                        local_end,
                        max_matches,
                    )
                    spans = self._translate_batch_spans(off, spans)
                    if spans:
                        yield sid, spans
                idx = hi
            return

        for sid, spans in self.iter_sentence_spans(max_matches):
            if spans:
                yield sid, spans


def _docset_signature(mask: np.ndarray) -> str:
    try:
        h = hashlib.blake2b(digest_size=8)
        try:
            view = memoryview(mask)
        except TypeError:
            view = memoryview(np.ascontiguousarray(mask))
        h.update(view)
        h.update(str(mask.shape).encode("utf-8"))
        h.update(str(mask.dtype).encode("utf-8"))
        return h.hexdigest()
    except Exception:
        try:
            return f"{mask.size}:{int(mask.sum())}"
        except Exception:
            return "mask"


def _eval_meta_cond(c: MetaCond, value: Any) -> bool:
    try:
        menge = meta_cond_menge(c)
        if menge is not None:
            # Mitgliedschaft, nicht Gleichheit gegen eine Liste. Ohne
            # diesen Zweig war ``value == ['test']`` fuer jedes Dokument
            # falsch und ``!=`` fuer jedes wahr.
            if c.op not in {'=', '!='}:
                return False
            # ODER ueber den SKALARZWEIG, nicht ein Nachbau davon. Die
            # erste Fassung verglich hier mit str()-Toleranz, waehrend der
            # Skalarzweig zwei Zeilen tiefer schlicht == benutzt: derselbe
            # Wert haette als Menge getroffen und als Skalar nicht.
            drin = any(
                _eval_meta_cond(MetaCond(field=c.field, op='=', value=v), value)
                for v in menge
            )
            return drin if c.op == '=' else not drin
        if c.op == '=':
            return value == c.value
        if c.op == '!=':
            return value != c.value
        if c.op == '>=':
            return value >= c.value
        if c.op == '<=':
            return value <= c.value
        if c.op == '>':
            return value > c.value
        if c.op == '<':
            return value < c.value
    except Exception:
        return False
    return False


def _eval_meta_expr(expr: MetaExpr, meta: Dict[str, Any]) -> bool:
    if expr.kind == 'cond':
        c0 = expr.parts[0]
        assert isinstance(c0, MetaCond)
        return _eval_meta_cond(c0, meta.get(c0.field))
    if expr.kind == 'and':
        for p in expr.parts:
            if isinstance(p, MetaExpr):
                if not _eval_meta_expr(p, meta):
                    return False
            else:
                assert isinstance(p, MetaCond)
                if not _eval_meta_cond(p, meta.get(p.field)):
                    return False
        return True
    if expr.kind == 'or':
        for p in expr.parts:
            if isinstance(p, MetaExpr):
                if _eval_meta_expr(p, meta):
                    return True
            else:
                assert isinstance(p, MetaCond)
                if _eval_meta_cond(p, meta.get(p.field)):
                    return True
        return False
    return False


def _filter_positions_to_sentence_ids(
    positions: np.ndarray,
    sent_ids: np.ndarray,
    sent_starts: np.ndarray,
    sent_ends: np.ndarray,
) -> np.ndarray:
    return filter_positions_to_sentence_ids(positions, sent_ids, sent_starts, sent_ends)


def _saetze_im_docset(corpus, cand_sids: np.ndarray, docset_mask: np.ndarray) -> np.ndarray:
    """Saetze, die MINDESTENS EIN Dokument der Maske beruehren.

    ``sent_to_doc`` liefert das Dokument des ERSTEN Satztokens. Der
    Vorfilter des NFA-Zweigs hat einen Satz damit ganz verworfen, sobald
    dieses erste Dokument ausserhalb der Maske lag, und ALLE Treffer in
    seinem zweiten Dokument fielen mit aus. Dieselbe Klasse wie in
    ``_finalize_candidates``: dort verlor ``[word="und"]`` 115 von 797
    Treffern zwischen den Haelften einer Partition.

    Der Vorfilter ist bewusst konservativ. Er haelt einen Satz, sobald
    irgendein von ihm beruehrtes Dokument in der Maske liegt, und darf
    dabei zu viel halten. Die genaue Entscheidung faellt danach je
    TREFFERPOSITION. Ein Vorfilter, der zu wenig haelt, verliert Treffer
    unwiederbringlich, ein Vorfilter, der zu viel haelt, kostet nur Zeit.
    """
    if cand_sids.size == 0:
        return cand_sids
    sids = cand_sids.astype(np.int64, copy=False)
    anfang = corpus.sent_starts[sids].astype(np.int64, copy=False)
    ende = np.maximum(corpus.sent_ends[sids].astype(np.int64, copy=False) - 1, anfang)
    t2d = corpus.token_to_doc()
    n = int(docset_mask.shape[0])
    d0 = np.clip(t2d[anfang], 0, n - 1)
    d1 = np.clip(t2d[ende], 0, n - 1)
    lo = np.minimum(d0, d1)
    hi = np.maximum(d0, d1)
    kum = np.concatenate((
        np.zeros(1, dtype=np.int64),
        np.cumsum(np.asarray(docset_mask).astype(np.int64)),
    ))
    return cand_sids[(kum[hi + 1] - kum[lo]) > 0]


def _position_im_docset(t2d, docset_mask, pos: int) -> int:
    """Das Dokument der Trefferposition, oder -1, wenn es nicht zaehlt."""
    d = int(t2d[pos])
    if d < 0 or d >= docset_mask.shape[0] or not docset_mask[d]:
        return -1
    return d


class QueryEngine:
    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        def _shared_cache(attr: str, factory):
            shared = getattr(corpus, attr, None)
            if shared is not None:
                return shared
            shared = factory()
            try:
                setattr(corpus, attr, shared)
            except Exception:
                pass
            return shared
        self._parse_cache = _shared_cache(
            "_cqlhpc_parse_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_PARSE_CACHE", 128)),
        )
        self._nfa_cache = _shared_cache(
            "_cqlhpc_nfa_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_NFA_CACHE", 64)),
        )
        self._docset_cache = _shared_cache(
            "_cqlhpc_docset_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_DOCSET_CACHE", 64)),
        )
        self._anchor_sent_cache = _shared_cache(
            "_cqlhpc_anchor_sent_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_ANCHOR_SENT_CACHE", 64)),
        )
        self._anchor_doc_cache = _shared_cache(
            "_cqlhpc_anchor_doc_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_ANCHOR_DOC_CACHE", 64)),
        )
        self._pos_sent_cache = _shared_cache(
            "_cqlhpc_pos_sent_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_POS_SENT_CACHE", 64)),
        )
        sent_filter_entries = get_int("CANDYCONC_CQLHPC_SENT_FILTER_CACHE", 64)
        sent_filter_bytes = get_int("CANDYCONC_CQLHPC_SENT_FILTER_CACHE_MAX_BYTES", 128 * 1024 * 1024)
        if sent_filter_bytes > 0:
            self._sent_filter_cache = _shared_cache(
                "_cqlhpc_sent_filter_cache",
                lambda: _ByteLRUCache(sent_filter_bytes, sent_filter_entries),
            )
        else:
            self._sent_filter_cache = _shared_cache(
                "_cqlhpc_sent_filter_cache",
                lambda: _LRUCache(sent_filter_entries),
            )
        sent_node_entries = get_int("CANDYCONC_CQLHPC_SENT_FILTER_NODE_CACHE", 256)
        sent_node_bytes = get_int("CANDYCONC_CQLHPC_SENT_FILTER_NODE_CACHE_MAX_BYTES", 128 * 1024 * 1024)
        if sent_node_bytes > 0:
            self._sent_filter_node_cache = _ByteLRUCache(sent_node_bytes, sent_node_entries)
        else:
            self._sent_filter_node_cache = _LRUCache(sent_node_entries)
        shift_sent_entries = get_int("CANDYCONC_CQLHPC_SHIFT_SENT_CACHE", 128)
        shift_sent_bytes = get_int("CANDYCONC_CQLHPC_SHIFT_SENT_CACHE_MAX_BYTES", 128 * 1024 * 1024)
        if shift_sent_bytes > 0:
            self._shift_sentence_ids_cache = _shared_cache(
                "_cqlhpc_shift_sentence_ids_cache",
                lambda: _ByteLRUCache(shift_sent_bytes, shift_sent_entries),
            )
        else:
            self._shift_sentence_ids_cache = _shared_cache(
                "_cqlhpc_shift_sentence_ids_cache",
                lambda: _LRUCache(shift_sent_entries),
            )
        bitset_cache_entries = get_int("CANDYCONC_CQLHPC_BITSET_CACHE", 64)
        bitset_cache_bytes = get_int("CANDYCONC_CQLHPC_BITSET_CACHE_MAX_BYTES", 512 * 1024 * 1024)
        dense_cache_entries = get_int("CANDYCONC_CQLHPC_DENSE_BITSET_CACHE", 64)
        dense_cache_bytes = get_int("CANDYCONC_CQLHPC_DENSE_BITSET_CACHE_MAX_BYTES", 512 * 1024 * 1024)
        if bitset_cache_bytes > 0:
            self._bitset_cache = _ByteLRUCache(bitset_cache_bytes, bitset_cache_entries)
        else:
            self._bitset_cache = _LRUCache(bitset_cache_entries)
        if dense_cache_bytes > 0:
            self._dense_bitset_cache = _ByteLRUCache(dense_cache_bytes, dense_cache_entries)
        else:
            self._dense_bitset_cache = _LRUCache(dense_cache_entries)
        self._plan_cache = _shared_cache(
            "_cqlhpc_plan_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_PLAN_CACHE", 64)),
        )
        self._compiled_clause_cache = _shared_cache(
            "_cqlhpc_compiled_clause_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_COMPILE_CACHE", 256)),
        )
        self._indexable_cache = _shared_cache(
            "_cqlhpc_indexable_cache",
            lambda: _LRUCache(get_int("CANDYCONC_CQLHPC_INDEXABLE_CACHE", 256)),
        )
        clause_pos_entries = get_int("CANDYCONC_CQLHPC_CLAUSE_POS_CACHE", 128)
        clause_pos_bytes = get_int("CANDYCONC_CQLHPC_CLAUSE_POS_CACHE_MAX_BYTES", 256 * 1024 * 1024)
        if clause_pos_bytes > 0:
            self._clause_positions_cache = _shared_cache(
                "_cqlhpc_clause_positions_cache",
                lambda: _ByteLRUCache(clause_pos_bytes, clause_pos_entries),
            )
        else:
            self._clause_positions_cache = _shared_cache(
                "_cqlhpc_clause_positions_cache",
                lambda: _LRUCache(clause_pos_entries),
            )
        clause_sent_entries = get_int("CANDYCONC_CQLHPC_CLAUSE_SENT_CACHE", 128)
        clause_sent_bytes = get_int("CANDYCONC_CQLHPC_CLAUSE_SENT_CACHE_MAX_BYTES", 256 * 1024 * 1024)
        if clause_sent_bytes > 0:
            self._clause_sentence_ids_cache = _shared_cache(
                "_cqlhpc_clause_sentence_ids_cache",
                lambda: _ByteLRUCache(clause_sent_bytes, clause_sent_entries),
            )
        else:
            self._clause_sentence_ids_cache = _shared_cache(
                "_cqlhpc_clause_sentence_ids_cache",
                lambda: _LRUCache(clause_sent_entries),
            )

    def _planner_cache_key(
        self,
        query: str,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
    ):
        docset_count = -1
        if docset_mask is not None:
            docset_count = int(np.count_nonzero(docset_mask))
        env_key = (
            str(get_int("CANDYCONC_CQLHPC_DP_MAX", 8)),
            str(get_float("CANDYCONC_CQLHPC_DP_MIN_RATIO", 4.0)),
            str(get_float("CANDYCONC_CQLHPC_BITSET_DENSITY", 0.02)),
            str(get_float("CANDYCONC_CQLHPC_BITSET_BUILD_WEIGHT", 1.0)),
            str(get_float("CANDYCONC_CQLHPC_BITSET_FILTER_WEIGHT", 1.0)),
            str(get_int("CANDYCONC_CQLHPC_PARTITION_MAX_LEN", 400)),
            str(get_float("CANDYCONC_CQLHPC_PARTITION_DOCSET", 0.2)),
            str(get_float("CANDYCONC_CQLHPC_PARTITION_DENSITY", 0.01)),
            str(1 if get_bool("CANDYCONC_CQLHPC_HYBRID_PLAN", True) else 0),
            str(get_float("CANDYCONC_CQLHPC_HYBRID_MARGIN", 0.6)),
            str(get_int("CANDYCONC_CQLHPC_PLANNER_MIN_TOKENS", 200000)),
        )
        return (query, scope, docset_count, int(self.corpus.n_tokens), env_key)

    def search(self, query: str, options: SearchOptions = SearchOptions()) -> List[Match]:
        return list(self.search_iter(query, options))

    def search_arrays(
        self,
        query: str,
        options: SearchOptions = SearchOptions(),
    ) -> tuple[np.ndarray, np.ndarray]:
        ast = self._get_ast(query)
        docset = self._effective_docset(query, ast, options)
        inner, forced_scope = self._unwrap_scopes(ast)
        scope = forced_scope or ('s' if options.within_sentences_by_default else None)
        seq = _as_postings_sequence(inner)
        if seq is not None:
            cand = self._sequence_postings_candidates(
                seq,
                scope,
                docset,
                options,
                query=query,
                include_ids=False,
            )
            if cand is not None:
                starts, ends, _sent_ids, _dids = cand
                return (
                    _as_nonnegative_uint32(starts),
                    _as_nonnegative_uint32(ends),
                )

        expanded_arrays = self._expanded_sequence_arrays(inner, scope, docset, options)
        if expanded_arrays is not None:
            return expanded_arrays

        expanded = self._expanded_sequence_matches(query, inner, scope, docset, options)
        if expanded is not None:
            if not expanded:
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            starts = np.empty(len(expanded), dtype=np.uint32)
            ends = np.empty(len(expanded), dtype=np.uint32)
            for i, match in enumerate(expanded):
                starts[i] = int(match.start)
                ends[i] = int(match.end)
            return starts, ends

        corpus = self.corpus
        nfa = self._get_nfa(query, inner, options)
        starts_list: list[int] = []
        ends_list: list[int] = []
        append_start = starts_list.append
        append_end = ends_list.append
        total = 0
        if scope == 'doc':
            # Document scope: verify the NFA over whole-document spans so matches
            # that cross sentence boundaries inside one document are found. The
            # per-sentence filters (_pos_sentence_ids / _hybrid_sentence_filter_ids)
            # are sentence-keyed and do not apply to document segments.
            cand_dids = self._anchor_document_ids(query, inner, options)
            if docset is not None and cand_dids.size:
                ok = (cand_dids >= 0) & (cand_dids < docset.shape[0]) & docset[cand_dids]
                cand_dids = cand_dids[ok]
            matcher = _PreparedSentenceMatcher(
                nfa,
                corpus,
                cand_dids,
                seg_starts=corpus.doc_starts,
                seg_ends=corpus.doc_ends,
            )
            for _did, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
                for a, b in spans:
                    append_start(int(a))
                    append_end(int(b))
                    total += 1
                    if total >= options.max_matches:
                        break
                if total >= options.max_matches:
                    break
        else:
            cand_sids = self._anchor_sentence_ids(query, inner, options)
            if docset is not None and cand_sids.size:
                # Verlustfrei vorfiltern, genau entscheiden je Position.
                cand_sids = _saetze_im_docset(corpus, cand_sids, docset)
            pos_sents = self._pos_sentence_ids(query, inner, options)
            if pos_sents is not None and pos_sents.size:
                cand_sids = intersect_sorted_unique(cand_sids, pos_sents)
            sent_filter = self._hybrid_sentence_filter_ids(query, inner, options)
            if sent_filter is not None and sent_filter.size:
                cand_sids = intersect_sorted_unique(cand_sids, sent_filter)

            matcher = _PreparedSentenceMatcher(nfa, corpus, cand_sids)
            _t2d = corpus.token_to_doc() if docset is not None else None
            for _sid, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
                for a, b in spans:
                    if _t2d is not None and _position_im_docset(_t2d, docset, int(a)) < 0:
                        continue
                    append_start(int(a))
                    append_end(int(b))
                    total += 1
                    if total >= options.max_matches:
                        break
                if total >= options.max_matches:
                    break
        if not starts_list:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        return (
            np.asarray(starts_list, dtype=np.uint32),
            np.asarray(ends_list, dtype=np.uint32),
        )

    def search_iter(self, query: str, options: SearchOptions = SearchOptions()):
        ast = self._get_ast(query)
        docset = self._effective_docset(query, ast, options)
        inner, forced_scope = self._unwrap_scopes(ast)
        scope = forced_scope or ('s' if options.within_sentences_by_default else None)
        seq = _as_postings_sequence(inner)
        if seq is not None:
            cand = self._sequence_postings_candidates(seq, scope, docset, options, query=query)
            if cand is not None:
                starts, ends, sent_ids, dids = cand
                n = int(starts.shape[0])
                if scope == 's':
                    assert sent_ids is not None
                    for i in range(n):
                        yield Match(
                            start=int(starts[i]),
                            end=int(ends[i]),
                            sentence_id=int(sent_ids[i]),
                            doc_id=int(dids[i]),
                        )
                else:
                    for i in range(n):
                        yield Match(
                            start=int(starts[i]),
                            end=int(ends[i]),
                            sentence_id=None,
                            doc_id=int(dids[i]),
                        )
                return
        yield from self._search_hybrid_iter(query, inner, scope, docset, options)

    def search_profile(
        self, query: str, options: SearchOptions = SearchOptions()
    ) -> Tuple[List[Match], Dict[str, float]]:
        timings: Dict[str, float] = {"parse": 0.0, "compile": 0.0, "plan": 0.0, "exec": 0.0}

        t_parse = time.perf_counter()
        ast = self._get_ast(query)
        timings["parse"] += time.perf_counter() - t_parse

        t_compile = time.perf_counter()
        docset = self._effective_docset(query, ast, options)
        inner, forced_scope = self._unwrap_scopes(ast)
        scope = forced_scope or ('s' if options.within_sentences_by_default else None)
        seq = _as_postings_sequence(inner)
        timings["compile"] += time.perf_counter() - t_compile

        if seq is not None:
            cand = self._sequence_postings_candidates(
                seq, scope, docset, options, query=query, timings=timings
            )
            if cand is not None:
                t_exec = time.perf_counter()
                starts, ends, sent_ids, dids = cand
                n = int(starts.shape[0])
                matches: List[Match] = []
                if scope == 's':
                    assert sent_ids is not None
                    for i in range(n):
                        matches.append(
                            Match(
                                start=int(starts[i]),
                                end=int(ends[i]),
                                sentence_id=int(sent_ids[i]),
                                doc_id=int(dids[i]),
                            )
                        )
                else:
                    for i in range(n):
                        matches.append(
                            Match(
                                start=int(starts[i]),
                                end=int(ends[i]),
                                sentence_id=None,
                                doc_id=int(dids[i]),
                            )
                        )
                timings["exec"] += time.perf_counter() - t_exec
                timings["total"] = timings["parse"] + timings["compile"] + timings["plan"] + timings["exec"]
                return matches, timings

        t_exec = time.perf_counter()
        expanded = self._expanded_sequence_matches(query, inner, scope, docset, options)
        if expanded is not None:
            timings["exec"] += time.perf_counter() - t_exec
            timings["total"] = timings["parse"] + timings["compile"] + timings["plan"] + timings["exec"]
            return expanded, timings

        corpus = self.corpus
        t_compile = time.perf_counter()
        nfa = self._get_nfa(query, inner, options)
        matches: List[Match] = []
        total = 0

        if scope == 'doc':
            # Document scope: verify the NFA over whole-document spans so matches
            # that cross sentence boundaries inside one document are found. This
            # mirrors the search_arrays scope=='doc' branch; the old per-sentence
            # path with a b>doc_end clamp could not match cross-sentence spans.
            cand_dids = self._anchor_document_ids(query, inner, options)
            if docset is not None and cand_dids.size:
                ok = (cand_dids >= 0) & (cand_dids < docset.shape[0]) & docset[cand_dids]
                cand_dids = cand_dids[ok]
            matcher = _PreparedSentenceMatcher(
                nfa,
                corpus,
                cand_dids,
                seg_starts=corpus.doc_starts,
                seg_ends=corpus.doc_ends,
            )
            timings["compile"] += time.perf_counter() - t_compile

            t_exec = time.perf_counter()
            for did, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
                for a, b in spans:
                    matches.append(
                        Match(
                            start=int(a),
                            end=int(b),
                            sentence_id=None,
                            doc_id=int(did),
                        )
                    )
                    total += 1
                    if total >= options.max_matches:
                        break
                if total >= options.max_matches:
                    break
            timings["exec"] += time.perf_counter() - t_exec
            timings["total"] = timings["parse"] + timings["compile"] + timings["plan"] + timings["exec"]
            return matches, timings

        cand_sids = self._anchor_sentence_ids(query, inner, options)
        if docset is not None and cand_sids.size:
            # Verlustfrei vorfiltern, genau entscheiden je Position.
            cand_sids = _saetze_im_docset(corpus, cand_sids, docset)
        pos_sents = self._pos_sentence_ids(query, inner, options)
        if pos_sents is not None and pos_sents.size:
            cand_sids = intersect_sorted_unique(cand_sids, pos_sents)
        sent_filter = self._hybrid_sentence_filter_ids(query, inner, options)
        if sent_filter is not None and sent_filter.size:
            cand_sids = intersect_sorted_unique(cand_sids, sent_filter)
        timings["compile"] += time.perf_counter() - t_compile

        t_exec = time.perf_counter()
        matcher = _PreparedSentenceMatcher(nfa, corpus, cand_sids)
        # doc_id je TREFFERPOSITION, nicht je Satz: sent_to_doc gab einem
        # Treffer jenseits einer Dokumentgrenze die ID des VORIGEN Dokuments.
        _t2d = corpus.token_to_doc()
        for sid, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
            for a, b in spans:
                did = int(_t2d[int(a)])
                if docset is not None and _position_im_docset(_t2d, docset, int(a)) < 0:
                    continue
                matches.append(
                    Match(
                        start=int(a),
                        end=int(b),
                        sentence_id=int(sid) if scope == 's' else None,
                        doc_id=did,
                    )
                )
                total += 1
                if total >= options.max_matches:
                    break
            if total >= options.max_matches:
                break
        timings["exec"] += time.perf_counter() - t_exec
        timings["total"] = timings["parse"] + timings["compile"] + timings["plan"] + timings["exec"]
        return matches, timings

    def count(self, query: str, options: SearchOptions = SearchOptions()) -> int:
        ast = self._get_ast(query)
        docset = self._effective_docset(query, ast, options)
        inner, forced_scope = self._unwrap_scopes(ast)
        scope = forced_scope or ('s' if options.within_sentences_by_default else None)
        seq = _as_postings_sequence(inner)
        if seq is not None:
            res = self._count_sequence_postings(seq, scope, docset, options, query=query)
            if res is not None:
                return res
        return self._count_hybrid(query, inner, scope, docset, options)

    def count_result(self, query: str, options: SearchOptions = SearchOptions()) -> CountResult:
        """Return a count with explicit capped-count semantics.

        ``count()`` is kept as the historical integer API and returns a value capped
        by ``options.max_matches``. This method probes one past that limit when
        possible so callers can distinguish an exact count equal to the limit from
        a partial lower bound.
        """
        count_limit = max(0, int(options.max_matches))
        probe_limit = count_limit + 1 if count_limit < _MAX_I32 else count_limit
        if probe_limit <= 0:
            probe_limit = 1
        observed = int(
            self.count(
                query,
                SearchOptions(
                    max_matches=probe_limit,
                    within_sentences_by_default=options.within_sentences_by_default,
                    progress_cb=options.progress_cb,
                    docset_mask=options.docset_mask,
                ),
            )
        )
        partial = observed >= probe_limit if probe_limit == count_limit else observed > count_limit
        return CountResult(total=min(observed, count_limit), partial=bool(partial), limit=count_limit)

    def _anchor_sentence_ids(
        self,
        query: str,
        inner: Node,
        options: SearchOptions,
    ) -> np.ndarray:
        cached = self._anchor_sent_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        corpus = self.corpus
        anchor_tok, anchor = _choose_anchor(inner, corpus, progress_cb=options.progress_cb)
        if anchor is None:
            cand_sids = np.arange(corpus.sent_starts.shape[0], dtype=np.int32)
        else:
            cand_sids = None
            if anchor_tok is not None:
                cand_sids = _sentence_ids_for_tok_clause(
                    anchor_tok,
                    corpus,
                    progress_cb=options.progress_cb,
                    compiled_cache=self._compiled_clause_cache,
                    indexable_cache=self._indexable_cache,
                    positions_cache=self._clause_positions_cache,
                    sentence_ids_cache=self._clause_sentence_ids_cache,
                )
            if cand_sids is None:
                pos = _materialize_attr_positions(anchor.attr, anchor.type_ids, corpus)
                cand_sids = sentence_ids_for_positions(pos, corpus.sent_ends)
        self._anchor_sent_cache.set(query, cand_sids)
        return cand_sids

    def _anchor_document_ids(
        self,
        query: str,
        inner: Node,
        options: SearchOptions,
    ) -> np.ndarray:
        """Candidate *document* ids for ``within(<doc>)`` verification.

        Mirrors :meth:`_anchor_sentence_ids` but maps the cheapest anchor's token
        positions onto document segments (``corpus.doc_ends``) rather than
        sentences. Going through token positions — not sentence ids — keeps this
        correct even when the index's sentence and document boundaries are not
        nested (a sentence may straddle a document boundary in some builds): each
        anchor token is attributed to exactly the document that physically
        contains it.
        """
        cached = self._anchor_doc_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        corpus = self.corpus
        doc_ends = corpus.doc_ends
        anchor_tok, anchor = _choose_anchor(inner, corpus, progress_cb=options.progress_cb)
        if anchor is None:
            cand_dids = np.arange(corpus.doc_starts.shape[0], dtype=np.int32)
        else:
            pos: Optional[np.ndarray] = None
            if anchor_tok is not None:
                pos = _positions_for_node(
                    anchor_tok,
                    corpus,
                    progress_cb=options.progress_cb,
                    compiled_cache=self._compiled_clause_cache,
                    indexable_cache=self._indexable_cache,
                    positions_cache=self._clause_positions_cache,
                )
            if pos is None:
                pos = _materialize_attr_positions(anchor.attr, anchor.type_ids, corpus)
            cand_dids = sentence_ids_for_positions(pos, doc_ends)
        self._anchor_doc_cache.set(query, cand_dids)
        return cand_dids

    def _pos_sentence_ids(
        self,
        query: str,
        inner: Node,
        options: SearchOptions,
    ) -> Optional[np.ndarray]:
        cached = self._pos_sent_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        corpus = self.corpus
        pos_ids = _collect_pos_ids(inner, corpus, progress_cb=options.progress_cb)
        if pos_ids and hasattr(corpus, "pos_sentence_index"):
            idx = corpus.pos_sentence_index()
            if idx is not None:
                pos_sents = _union_sentence_ids(idx, pos_ids)
                self._pos_sent_cache.set(query, pos_sents)
                return pos_sents
        self._pos_sent_cache.set(query, None)
        return None

    def _hybrid_sentence_filter_ids(
        self,
        query: str,
        inner: Node,
        options: SearchOptions,
    ) -> Optional[np.ndarray]:
        cache_key = _sent_filter_query_cache_key(query)
        cached = self._sent_filter_cache.get(cache_key)
        if cached is not _CACHE_MISSING:
            return cached
        bounded = self._bounded_repeat_sentence_filter_ids(inner, options)
        if bounded is not None:
            self._sent_filter_cache.set(cache_key, bounded)
            return bounded
        arr = _sentence_filter_ids_for_node(
            inner,
            self.corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
            positions_cache=self._clause_positions_cache,
            sentence_ids_cache=self._clause_sentence_ids_cache,
            shift_sentence_cache=self._shift_sentence_ids_cache,
            subtree_cache=self._sent_filter_node_cache,
        )
        self._sent_filter_cache.set(cache_key, arr)
        return arr

    def _bounded_repeat_sentence_filter_ids(
        self,
        inner: Node,
        options: SearchOptions,
    ) -> Optional[np.ndarray]:
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_SENT_FILTER", True):
            return None
        pattern = _extract_bounded_repeat_pattern(
            inner,
            self.corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
        )
        if pattern is None:
            return None
        left_node, middle_node, right_node, min_rep, max_rep = pattern
        max_exact = max(0, get_int("CANDYCONC_CQLHPC_BOUNDED_REPEAT_SENT_FILTER_MAX", 64))
        if max_rep > max_exact:
            return None
        corpus = self.corpus
        try:
            left = _positions_for_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            if left is None or left.size == 0:
                return np.empty((0,), dtype=np.int32)
        except ValueError:
            return None
        n_tokens = int(corpus.n_tokens)
        try:
            middle_simple = _simple_indexable_from_node(
                middle_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            right_simple = _simple_indexable_from_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
        except ValueError:
            return None
        if middle_simple is None or right_simple is None:
            return None
        empty = np.empty((0,), dtype=np.int32)
        middle_bitset = self._bitset_for_simple_node(middle_simple, empty, n_tokens)
        right_bitset = self._bitset_for_simple_node(right_simple, empty, n_tokens)
        return bounded_repeat_sentence_ids(
            left,
            middle_bitset,
            right_bitset,
            min_rep,
            max_rep,
            corpus.sent_ends,
        )

    def _get_ast(self, query: str) -> Node:
        cached = self._parse_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        ast = normalize(parse_cql(query))
        self._parse_cache.set(query, ast)
        return ast

    def _get_docset(self, query: str, ast: Node) -> Optional[np.ndarray]:
        cached = self._docset_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        docset = self._docset_from_where(ast)
        self._docset_cache.set(query, docset)
        return docset

    def _effective_docset(self, query: str, ast: Node, options: SearchOptions) -> Optional[np.ndarray]:
        where_mask = self._get_docset(query, ast)
        external = options.docset_mask
        if external is None:
            return where_mask
        external_mask = np.asarray(external, dtype=np.bool_)
        if external_mask.ndim != 1:
            raise ValueError("docset_mask muss eindimensional sein")
        if int(external_mask.shape[0]) != int(self.corpus.doc_starts.shape[0]):
            raise ValueError("docset_mask passt nicht zur Dokumentanzahl")
        if where_mask is None:
            return external_mask
        if int(where_mask.shape[0]) != int(external_mask.shape[0]):
            raise ValueError("docset_mask passt nicht zur Dokumentanzahl")
        return np.asarray(where_mask, dtype=np.bool_) & external_mask

    def _intersect_shifted_adaptive(
        self, anchor: np.ndarray, other: np.ndarray, shift: int, gallop_ratio: float
    ) -> np.ndarray:
        if anchor.size == 0 or other.size == 0:
            return np.empty((0,), dtype=np.int32)
        la = int(anchor.size)
        lb = int(other.size)
        small = min(la, lb)
        large = max(la, lb)
        ratio = (large / small) if small > 0 else large
        if ratio >= gallop_ratio:
            return intersect_shifted_gallop(anchor, other, int(shift))
        return intersect_shifted(anchor, other, int(shift))

    def _sequence_postings_partitioned(
        self,
        cand: np.ndarray,
        anchor_i: int,
        clauses: List[Node],
        node_simple: List[Optional[Tuple[str, np.ndarray, int]]],
        pos_lists: List[Optional[np.ndarray]],
        order_steps: Tuple[ClausePlan, ...],
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], np.ndarray]]:
        corpus = self.corpus
        if scope not in {"s", "doc"}:
            return None
        if cand.size == 0:
            empty = np.empty((0,), dtype=np.int32)
            return empty, empty, empty, empty
        seq_len = len(pos_lists)
        n_tokens = corpus.n_tokens
        starts = cand - anchor_i

        if scope == "s":
            seg_starts = corpus.sent_starts
            seg_ends = corpus.sent_ends
            seg_ids = corpus.token_to_sent()[starts]
        else:
            seg_starts = corpus.doc_starts
            seg_ends = corpus.doc_ends
            seg_ids = corpus.token_to_doc()[starts]

        # Sort by segment id + position for stable concatenation.
        order = np.lexsort((cand, seg_ids))
        cand = cand[order]
        starts = starts[order]
        seg_ids = seg_ids[order]

        out_parts: List[np.ndarray] = []
        adaptive = get_bool("CANDYCONC_CQLHPC_ADAPTIVE_INTERSECT", True)
        gallop_ratio = get_float("CANDYCONC_CQLHPC_GALLOP_RATIO", 4.0)

        def _slice_positions(arr: np.ndarray, lo: int, hi: int) -> np.ndarray:
            if arr.size == 0:
                return arr
            a = int(np.searchsorted(arr, lo, side="left"))
            b = int(np.searchsorted(arr, hi, side="left"))
            if b <= a:
                return np.empty((0,), dtype=np.int32)
            return arr[a:b]

        i = 0
        total = int(seg_ids.shape[0])
        while i < total:
            seg_id = int(seg_ids[i])
            j = i + 1
            while j < total and int(seg_ids[j]) == seg_id:
                j += 1
            seg_start = int(seg_starts[seg_id])
            seg_end = int(seg_ends[seg_id])
            if seg_end - seg_start < seq_len:
                i = j
                continue
            if docset_mask is not None:
                if scope == "doc":
                    # Das Segment IST das Dokument, die Pruefung ist exakt.
                    if (seg_id < 0 or seg_id >= docset_mask.shape[0]
                            or not bool(docset_mask[seg_id])):
                        i = j
                        continue
                else:
                    # Ein Satz kann eine Dokumentgrenze ueberlaufen. Ueber
                    # sent_to_doc gehoerte er ganz dem ERSTEN Dokument, und
                    # jeder Treffer in seiner zweiten Haelfte fiel mit dem
                    # GANZEN Segment aus. Hier wird nur noch vorgefiltert:
                    # das Segment bleibt, sobald es irgendein Dokument der
                    # Maske beruehrt. Die genaue Entscheidung faellt unten
                    # je Trefferposition.
                    _t2d = corpus.token_to_doc()
                    _d0 = int(_t2d[seg_start])
                    _d1 = int(_t2d[max(seg_end - 1, seg_start)])
                    _lo = max(min(_d0, _d1), 0)
                    _hi = min(max(_d0, _d1), int(docset_mask.shape[0]) - 1)
                    if _hi < _lo or not bool(np.any(docset_mask[_lo:_hi + 1])):
                        i = j
                        continue

            seg_cand = cand[i:j]
            seg_starts_arr = starts[i:j]
            # Filter by bounds within segment.
            ok = (seg_starts_arr >= seg_start) & (seg_starts_arr + seq_len <= seg_end)
            if not np.any(ok):
                i = j
                continue
            if not np.all(ok):
                seg_cand = seg_cand[ok]
            if seg_cand.size == 0:
                i = j
                continue

            # Apply constraints within this segment.
            local = seg_cand
            for step in order_steps:
                k = step.idx
                shift = k - anchor_i
                simple = node_simple[k]
                if step.method == "bitset":
                    if pos_lists[k] is not None:
                        bitset = positions_to_bitset(pos_lists[k], n_tokens)
                    else:
                        if simple is None:
                            return None
                        attr, tids, _ = simple
                        if len(tids) == 1:
                            bitset = self._dense_bitset_for_type(attr, int(tids[0]))
                            if bitset is None:
                                bitset = self._postings_bitset(attr, tids, n_tokens)
                        else:
                            bitset = self._postings_bitset(attr, tids, n_tokens)
                    local = filter_positions_by_bitset_no_bounds(local, bitset, shift)
                else:
                    if pos_lists[k] is not None:
                        arr = pos_lists[k]  # type: ignore[assignment]
                    else:
                        simple = node_simple[k]
                        if simple is None:
                            return None
                        attr, tids, _ = simple
                        arr = _materialize_attr_positions(attr, tids, corpus)
                        pos_lists[k] = arr
                    arr = _slice_positions(arr, seg_start, seg_end)
                    if arr.size == 0:
                        local = np.empty((0,), dtype=np.int32)
                    else:
                        if adaptive:
                            local = self._intersect_shifted_adaptive(local, arr, shift, gallop_ratio)
                        else:
                            local = intersect_shifted(local, arr, shift)
                if local.size == 0:
                    break

            if local.size:
                out_parts.append(local)
            i = j

        if not out_parts:
            empty = np.empty((0,), dtype=np.int32)
            return empty, empty, empty, empty
        cand = np.concatenate(out_parts)
        starts = cand - anchor_i
        ends = starts + seq_len
        sent_ids: Optional[np.ndarray] = None
        dids: Optional[np.ndarray] = None
        if scope == "s":
            sent_ids = corpus.token_to_sent()[starts]
        # Die Dokumentzuschreibung haengt an der TREFFERPOSITION, nicht am
        # Satz, und zwar in BEIDEN Scopes gleich. sent_to_doc ordnet einen
        # Satz ueber einer Dokumentgrenze ganz dem ersten Dokument zu, also
        # bekam ein Treffer im zweiten die doc_id des ersten -- und doc_id
        # traegt Dokumentfrequenz, Dispersion und die Maskenpruefung der
        # Aufrufer. Der Scope entschied damit ueber die Zuschreibung.
        dids = corpus.token_to_doc()[starts]
        # Und die Maske ebenso. Der Vorfilter oben haelt bewusst zu viel,
        # damit kein Treffer verloren geht, deshalb faellt hier die genaue
        # Entscheidung.
        if docset_mask is not None and starts.size:
            ok = ((dids >= 0) & (dids < docset_mask.shape[0])
                  & (np.asarray(docset_mask)[dids] != 0))
            starts, ends, dids = starts[ok], ends[ok], dids[ok]
            if sent_ids is not None:
                sent_ids = sent_ids[ok]
        return starts, ends, sent_ids, dids

    def _bitset_for_simple_node(
        self,
        simple: Optional[Tuple[str, np.ndarray, int]],
        pos: np.ndarray,
        n_tokens: int,
    ) -> np.ndarray:
        if simple is None:
            return positions_to_bitset(pos, n_tokens)
        attr, tids, _ = simple
        key = ("bitset", "simple-node", attr, _ids_cache_key(tids), None)
        cached = self._bitset_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
        bitset = None
        if len(tids) == 1:
            bitset = self._dense_bitset_for_type(attr, int(tids[0]))
        else:
            bitset = self._dense_bitset_for_types(attr, tids)
        if bitset is None:
            bitset = self._postings_bitset(attr, tids, n_tokens)
        self._bitset_cache.set(key, bitset)
        return bitset

    def _dense_bitset_for_type(self, attr: str, tid: int) -> Optional[np.ndarray]:
        key = ("dense", attr, int(tid))
        cached = self._dense_bitset_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
        # Prefer persisted dense bitsets if available
        if hasattr(self.corpus, "dense_bitset"):
            try:
                bitset = self.corpus.dense_bitset(attr, int(tid))
            except Exception:
                bitset = None
            if bitset is not None:
                self._dense_bitset_cache.set(key, bitset)
                return bitset
        idx = self.corpus.postings_index(attr)
        n_tokens = self.corpus.n_tokens
        if n_tokens <= 0:
            self._dense_bitset_cache.set(key, None)
            return None
        length = idx.length(int(tid))
        dens_thresh = get_float("CANDYCONC_CQLHPC_DENSE_TYPE_DENSITY", 0.05)
        min_len = get_int("CANDYCONC_CQLHPC_DENSE_TYPE_MIN_LEN", 500000)
        density = length / float(n_tokens)
        if length >= min_len or density >= dens_thresh:
            bitset = self._postings_bitset(attr, np.asarray([tid], dtype=np.int32), n_tokens)
            self._dense_bitset_cache.set(key, bitset)
            return bitset
        self._dense_bitset_cache.set(key, None)
        return None

    def _dense_bitset_for_types(self, attr: str, tids: np.ndarray) -> Optional[np.ndarray]:
        max_types = get_int("CANDYCONC_CQLHPC_DENSE_BITSET_MAX_TYPES", 8)
        if tids.size == 0 or tids.size > max_types:
            return None
        key = ("dense_union", attr, _ids_cache_key(tids))
        cached = self._dense_bitset_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
        direct_max_types = get_int("CANDYCONC_CQLHPC_DENSE_UNION_DIRECT_MAX_TYPES", 4)
        if tids.size <= direct_max_types:
            bitset = self._postings_bitset(attr, tids, int(self.corpus.n_tokens))
            self._dense_bitset_cache.set(key, bitset)
            return bitset
        bitset = None
        for tid in tids.tolist():
            bs = self._dense_bitset_for_type(attr, int(tid))
            if bs is None:
                self._dense_bitset_cache.set(key, None)
                return None
            if bitset is None:
                bitset = bs.copy()
            else:
                bitset |= bs
        self._dense_bitset_cache.set(key, bitset)
        return bitset

    def _postings_positions(self, attr: str, tids: np.ndarray) -> np.ndarray:
        return _materialize_attr_positions(attr, tids, self.corpus)

    def _postings_bitset(self, attr: str, tids: np.ndarray, n_tokens: int) -> np.ndarray:
        backend = getattr(self.corpus, "backend", None)
        if backend is not None and hasattr(backend, "_bitset_for_ids"):
            try:
                return backend._bitset_for_ids(attr, tids.astype(np.int32, copy=False), n_tokens)
            except Exception:
                pass
        idx = self.corpus.postings_index(attr)
        if hasattr(idx, "offsets"):
            return postings_to_bitset(idx, tids, n_tokens)
        arr = _materialize_attr_positions(attr, tids, self.corpus)
        return positions_to_bitset(arr, n_tokens)

    def _get_nfa(self, query: str, inner: Node, options: SearchOptions) -> Any:
        cached = self._nfa_cache.get(query)
        if cached is not _CACHE_MISSING:
            return cached
        nfa = compile_nfa(inner, self.corpus, progress_cb=options.progress_cb)
        self._nfa_cache.set(query, nfa)
        return nfa

    # ----------------- where/docset ---------------------------------

    def _docset_from_where(self, ast: Node) -> Optional[np.ndarray]:
        exprs: List[MetaExpr] = []
        n = ast
        while isinstance(n, (Where, Within)):
            if isinstance(n, Where):
                exprs.append(n.expr)
                n = n.node
                continue
            n = n.node
        if _contains_where(n):
            raise RuntimeError(BRANCH_LOCAL_WHERE)
        if not exprs:
            return None

        backend = getattr(self.corpus, "backend", None)
        meta_index = getattr(backend, "meta_index", None) if backend is not None else None
        if meta_index is None:
            raise RuntimeError(lt(
                "Meta Index fehlt für where(). Bitte Fast Index neu bauen.",
                "Metadata index missing for where(). Rebuild the index.",
            ))
        if meta_index.doc_count and meta_index.doc_count != int(self.corpus.doc_starts.shape[0]):
            raise RuntimeError(lt(
                "Meta Index doc_count passt nicht zum Korpus. Bitte Index neu bauen.",
                "Metadata index doc_count does not match the corpus. Rebuild the index.",
            ))

        mask: Optional[np.ndarray] = None
        for expr in exprs:
            cur = meta_index.mask_for_expr(expr)
            mask = cur if mask is None else (mask & cur)
        return mask

    def _unwrap_scopes(self, ast: Node) -> Tuple[Node, Optional[str]]:
        scope: Optional[str] = None
        n = ast
        while True:
            if isinstance(n, Where):
                n = n.node
                continue
            if isinstance(n, Within):
                scope = n.scope
                n = n.node
                continue
            break
        return n, scope

    # ----------------- Plan B: hybrid anchor -> sentence verification -

    def _search_hybrid(self, inner: Node, scope: Optional[str], docset_mask: Optional[np.ndarray], options: SearchOptions) -> List[Match]:
        return list(self._search_hybrid_iter("<inline>", inner, scope, docset_mask, options))

    def _expanded_sequence_matches(
        self,
        query: str,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[List[Match]]:
        unbounded = self._unbounded_repeat_sequence_matches(
            inner,
            scope,
            docset_mask,
            options,
        )
        if unbounded is not None:
            return unbounded
        bounded = self._bounded_repeat_sequence_matches(
            inner,
            scope,
            docset_mask,
            options,
        )
        if bounded is not None:
            return bounded
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_EXPANDED_SEQUENCE_FASTPATH", False):
            return None
        if scope != "s":
            return None
        variants = _expand_simple_sequence_variants(
            inner,
            self.corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
        )
        if not variants:
            return None
        variant_limit = options.max_matches
        if variant_limit > 0:
            variant_limit = max(variant_limit, options.max_matches * max(2, len(variants)))
        variant_options = SearchOptions(
            max_matches=variant_limit,
            within_sentences_by_default=options.within_sentences_by_default,
            progress_cb=options.progress_cb,
        )
        candidates = []
        for idx, variant in enumerate(variants):
            cand = self._sequence_postings_candidates(
                list(variant),
                scope,
                docset_mask,
                variant_options,
                query=f"{query}#exp{idx}",
            )
            if cand is not None:
                candidates.append(cand)
        return _merge_expanded_sequence_candidates(candidates, scope, options.max_matches)

    def _expanded_sequence_arrays(
        self,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        unbounded = self._unbounded_repeat_sequence_arrays(inner, scope, docset_mask, options)
        if unbounded is not None:
            return unbounded
        bounded = self._bounded_repeat_sequence_arrays(inner, scope, docset_mask, options)
        if bounded is not None:
            return bounded
        return None

    def _unbounded_repeat_sequence_arrays(
        self,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH", True):
            return None
        if scope != "s":
            return None
        while isinstance(inner, (Within, Where)):
            inner = inner.node
        if not isinstance(inner, Seq) or len(inner.parts) != 2:
            return None
        head, right_node = inner.parts
        if not isinstance(head, Quant) or head.n is not None or head.m < 1:
            return None
        left_node = head.node
        if _token_length_bounds(left_node) != (1, 1) or _token_length_bounds(right_node) != (1, 1):
            return None
        corpus = self.corpus
        try:
            right = _positions_for_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            right_simple = _simple_indexable_from_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            left_simple = _simple_indexable_from_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
        except ValueError:
            return None
        if right is None:
            return None
        if right.size == 0:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        empty_i32 = np.empty((0,), dtype=np.int32)
        if left_simple is not None and right_simple is not None and int(right_simple[2]) <= int(left_simple[2]):
            left_bitset = self._bitset_for_simple_node(left_simple, empty_i32, int(corpus.n_tokens))
            starts, ends, sids = unbounded_repeat_sentence_matches_from_right(
                right,
                left_bitset,
                int(head.m),
                corpus.sent_ends,
                options.max_matches,
                include_sids=docset_mask is not None,
            )
        else:
            left = _positions_for_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            if left is None:
                return None
            if left.size == 0:
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            right_bitset = self._bitset_for_simple_node(
                right_simple,
                right if right_simple is None else empty_i32,
                int(corpus.n_tokens),
            )
            starts, ends, sids = unbounded_repeat_sentence_matches(
                left,
                right_bitset,
                int(head.m),
                corpus.sent_ends,
                options.max_matches,
                include_sids=docset_mask is not None,
            )
        if starts.size == 0:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        if docset_mask is not None:
            # Maske ueber das Dokument der TREFFERPOSITION, nicht des
            # Satzes: ein Satz ueber einer Dokumentgrenze gehoert bei
            # sent_to_doc ganz dem ersten Dokument, und ein Treffer im
            # zweiten faellt aus beiden Haelften einer Partition.
            dids = corpus.token_to_doc()[starts]
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            if not np.all(ok):
                starts = starts[ok]
                ends = ends[ok]
        return _as_nonnegative_uint32(starts), _as_nonnegative_uint32(ends)

    def _bounded_repeat_sequence_arrays(
        self,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH", True):
            return None
        if scope != "s":
            return None
        pattern = _extract_bounded_repeat_pattern(
            inner,
            self.corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
        )
        if pattern is None:
            return None
        left_node, middle_node, right_node, min_rep, max_rep = pattern
        if max_rep < min_rep or max_rep < 0:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        max_fast = max(0, get_int("CANDYCONC_CQLHPC_BOUNDED_REPEAT_FAST_MAX", 64))
        if max_rep > max_fast:
            return None
        corpus = self.corpus
        try:
            right_simple = _simple_indexable_from_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            middle_simple = _simple_indexable_from_node(
                middle_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            left_simple = _simple_indexable_from_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
        except ValueError:
            return None
        if middle_simple is None or right_simple is None:
            return None
        empty_i32 = np.empty((0,), dtype=np.int32)
        right = _positions_for_node(
            right_node,
            corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
            positions_cache=self._clause_positions_cache,
        )
        if right is None:
            return None
        if right.size == 0:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        right_bitset = self._bitset_for_simple_node(right_simple, empty_i32, int(corpus.n_tokens))
        middle_bitset = self._bitset_for_simple_node(middle_simple, empty_i32, int(corpus.n_tokens))
        if left_simple is not None and int(right_simple[2]) <= int(left_simple[2]):
            left_bitset = self._bitset_for_simple_node(left_simple, empty_i32, int(corpus.n_tokens))
            starts, ends, sids = bounded_repeat_sentence_matches_from_right(
                right,
                left_bitset,
                middle_bitset,
                min_rep,
                max_rep,
                corpus.sent_ends,
                options.max_matches,
                include_sids=docset_mask is not None,
            )
        else:
            left = _positions_for_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            if left is None:
                return None
            if left.size == 0:
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            starts, ends, sids = bounded_repeat_sentence_matches(
                left,
                middle_bitset,
                right_bitset,
                min_rep,
                max_rep,
                corpus.sent_ends,
                options.max_matches,
                include_sids=docset_mask is not None,
            )
        if starts.size == 0:
            empty = np.zeros(0, dtype=np.uint32)
            return empty, empty
        if docset_mask is not None:
            # Maske ueber das Dokument der TREFFERPOSITION, nicht des
            # Satzes: ein Satz ueber einer Dokumentgrenze gehoert bei
            # sent_to_doc ganz dem ersten Dokument, und ein Treffer im
            # zweiten faellt aus beiden Haelften einer Partition.
            dids = corpus.token_to_doc()[starts]
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            if not np.all(ok):
                starts = starts[ok]
                ends = ends[ok]
        return _as_nonnegative_uint32(starts), _as_nonnegative_uint32(ends)

    def _unbounded_repeat_sequence_matches(
        self,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[List[Match]]:
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_UNBOUNDED_REPEAT_FASTPATH", True):
            return None
        if scope != "s":
            return None
        while isinstance(inner, (Within, Where)):
            inner = inner.node
        if not isinstance(inner, Seq) or len(inner.parts) != 2:
            return None
        head, right_node = inner.parts
        if not isinstance(head, Quant) or head.n is not None or head.m < 1:
            return None
        left_node = head.node
        if _token_length_bounds(left_node) != (1, 1) or _token_length_bounds(right_node) != (1, 1):
            return None
        corpus = self.corpus
        try:
            right = _positions_for_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            right_simple = _simple_indexable_from_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            left_simple = _simple_indexable_from_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
        except ValueError:
            return None
        if right is None:
            return None
        if right.size == 0:
            return []
        n_tokens = int(corpus.n_tokens)
        empty = np.empty((0,), dtype=np.int32)
        if left_simple is not None and right_simple is not None and int(right_simple[2]) <= int(left_simple[2]):
            left_bitset = self._bitset_for_simple_node(left_simple, empty, n_tokens)
            starts, ends, sids = unbounded_repeat_sentence_matches_from_right(
                right,
                left_bitset,
                int(head.m),
                corpus.sent_ends,
                options.max_matches,
            )
        else:
            left = _positions_for_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            if left is None:
                return None
            if left.size == 0:
                return []
            right_bitset = self._bitset_for_simple_node(
                right_simple,
                right if right_simple is None else empty,
                n_tokens,
            )
            starts, ends, sids = unbounded_repeat_sentence_matches(
                left,
                right_bitset,
                int(head.m),
                corpus.sent_ends,
                options.max_matches,
            )
        if starts.size == 0:
            return []
        # Maske und Dokumentzuschreibung ueber die TREFFERPOSITION, siehe
        # oben: sent_to_doc verliert Treffer an Dokumentgrenzen.
        dids = corpus.token_to_doc()[starts]
        if docset_mask is not None:
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                return []
            if not np.all(ok):
                starts = starts[ok]
                ends = ends[ok]
                sids = sids[ok]
                dids = dids[ok]
        out: List[Match] = []
        for idx in range(int(starts.shape[0])):
            out.append(
                Match(
                    start=int(starts[idx]),
                    end=int(ends[idx]),
                    sentence_id=int(sids[idx]),
                    doc_id=int(dids[idx]),
                )
            )
            if len(out) >= options.max_matches:
                break
        return out

    def _bounded_repeat_sequence_matches(
        self,
        inner: Node,
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[List[Match]]:
        if not get_bool("CANDYCONC_CQLHPC_ENABLE_BOUNDED_REPEAT_FASTPATH", True):
            return None
        if scope != "s":
            return None
        pattern = _extract_bounded_repeat_pattern(
            inner,
            self.corpus,
            progress_cb=options.progress_cb,
            compiled_cache=self._compiled_clause_cache,
            indexable_cache=self._indexable_cache,
        )
        if pattern is None:
            return None
        left_node, middle_node, right_node, min_rep, max_rep = pattern
        if max_rep < min_rep or max_rep < 0:
            return []
        max_fast = max(0, get_int("CANDYCONC_CQLHPC_BOUNDED_REPEAT_FAST_MAX", 64))
        if max_rep > max_fast:
            return None

        corpus = self.corpus
        n_tokens = int(corpus.n_tokens)
        try:
            right = _positions_for_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            right_simple = _simple_indexable_from_node(
                right_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            middle_simple = _simple_indexable_from_node(
                middle_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
            left_simple = _simple_indexable_from_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
            )
        except ValueError:
            return None
        if right is None:
            return None
        if right.size == 0:
            return []
        if middle_simple is None or right_simple is None:
            return None
        empty = np.empty((0,), dtype=np.int32)
        right_bitset = self._bitset_for_simple_node(right_simple, empty, n_tokens)
        middle_bitset = self._bitset_for_simple_node(middle_simple, empty, n_tokens)
        if left_simple is not None and int(right_simple[2]) <= int(left_simple[2]):
            left_bitset = self._bitset_for_simple_node(left_simple, empty, n_tokens)
            starts, ends, sids = bounded_repeat_sentence_matches_from_right(
                right,
                left_bitset,
                middle_bitset,
                min_rep,
                max_rep,
                corpus.sent_ends,
                options.max_matches,
            )
        else:
            left = _positions_for_node(
                left_node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=self._compiled_clause_cache,
                indexable_cache=self._indexable_cache,
                positions_cache=self._clause_positions_cache,
            )
            if left is None:
                return None
            if left.size == 0:
                return []
            starts, ends, sids = bounded_repeat_sentence_matches(
                left,
                middle_bitset,
                right_bitset,
                min_rep,
                max_rep,
                corpus.sent_ends,
                options.max_matches,
            )
        if starts.size == 0:
            return []
        # Maske und Dokumentzuschreibung ueber die TREFFERPOSITION, siehe
        # oben: sent_to_doc verliert Treffer an Dokumentgrenzen.
        dids = corpus.token_to_doc()[starts]
        if docset_mask is not None:
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                return []
            starts = starts[ok]
            ends = ends[ok]
            sids = sids[ok]
            dids = dids[ok]
        out: List[Match] = []
        for idx in range(int(starts.shape[0])):
            sid = int(sids[idx])
            start = int(starts[idx])
            end = int(ends[idx])
            out.append(
                Match(
                    start=start,
                    end=end,
                    sentence_id=sid,
                    doc_id=int(dids[idx]),
                )
            )
            if len(out) >= options.max_matches:
                break
        return out

    def _search_hybrid_iter(
        self, query: str, inner: Node, scope: Optional[str], docset_mask: Optional[np.ndarray], options: SearchOptions
    ):
        corpus = self.corpus

        expanded = self._expanded_sequence_matches(query, inner, scope, docset_mask, options)
        if expanded is not None:
            yield from expanded
            return

        nfa = self._get_nfa(query, inner, options)
        total = 0

        if scope == 'doc':
            # Verify the NFA over whole-document spans (see _anchor_document_ids):
            # this finds matches crossing sentence boundaries inside a document.
            cand_dids = self._anchor_document_ids(query, inner, options)
            if docset_mask is not None and cand_dids.size:
                ok = (cand_dids >= 0) & (cand_dids < docset_mask.shape[0]) & docset_mask[cand_dids]
                cand_dids = cand_dids[ok]
            matcher = _PreparedSentenceMatcher(
                nfa,
                corpus,
                cand_dids,
                seg_starts=corpus.doc_starts,
                seg_ends=corpus.doc_ends,
            )
            for did, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
                for a, b in spans:
                    yield Match(
                        start=int(a),
                        end=int(b),
                        sentence_id=None,
                        doc_id=int(did),
                    )
                    total += 1
                    if total >= options.max_matches:
                        return
            return

        sent_filter = self._hybrid_sentence_filter_ids(query, inner, options)
        if sent_filter is not None and sent_filter.size:
            cand_sids = sent_filter
        else:
            cand_sids = self._anchor_sentence_ids(query, inner, options)

        # docset filter in vectorized form
        if docset_mask is not None and cand_sids.size:
            # Verlustfrei vorfiltern, genau entscheiden je Position.
            cand_sids = _saetze_im_docset(corpus, cand_sids, docset_mask)

        pos_sents = self._pos_sentence_ids(query, inner, options)
        if pos_sents is not None and pos_sents.size:
            cand_sids = intersect_sorted_unique(cand_sids, pos_sents)
        if sent_filter is not None and sent_filter.size and cand_sids is not sent_filter:
            cand_sids = intersect_sorted_unique(cand_sids, sent_filter)

        matcher = _PreparedSentenceMatcher(nfa, corpus, cand_sids)
        # Siehe search_profile: Dokument der Position, nicht des Satzes.
        _t2d = corpus.token_to_doc()
        for sid, spans in matcher.iter_nonempty_sentence_spans(options.max_matches):
            for a, b in spans:
                did = int(_t2d[int(a)])
                if docset_mask is not None and _position_im_docset(_t2d, docset_mask, int(a)) < 0:
                    continue
                yield Match(
                    start=int(a),
                    end=int(b),
                    sentence_id=int(sid) if scope == 's' else None,
                    doc_id=did,
                )
                total += 1
                if total >= options.max_matches:
                    return

    def _count_hybrid(self, query: str, inner: Node, scope: Optional[str], docset_mask: Optional[np.ndarray], options: SearchOptions) -> int:
        corpus = self.corpus

        expanded = self._expanded_sequence_matches(query, inner, scope, docset_mask, options)
        if expanded is not None:
            return len(expanded)

        nfa = self._get_nfa(query, inner, options)
        total = 0
        progress_cb = options.progress_cb
        if progress_cb is not None:
            progress_cb("count:start")

        if scope == 'doc':
            # Count NFA matches over whole-document spans so the count agrees with
            # the document-scoped iterator (which finds cross-sentence matches).
            cand_dids = self._anchor_document_ids(query, inner, options)
            if docset_mask is not None and cand_dids.size:
                ok = (cand_dids >= 0) & (cand_dids < docset_mask.shape[0]) & docset_mask[cand_dids]
                cand_dids = cand_dids[ok]
            matcher = _PreparedSentenceMatcher(
                nfa,
                corpus,
                cand_dids,
                seg_starts=corpus.doc_starts,
                seg_ends=corpus.doc_ends,
            )
            for idx, (_, spans) in enumerate(matcher.iter_nonempty_sentence_spans(options.max_matches), start=1):
                if progress_cb is not None and (idx & 0x3FF) == 0:
                    progress_cb("count:scan")
                total += len(spans)
                if total >= options.max_matches:
                    return total
            return total

        sent_filter = self._hybrid_sentence_filter_ids(query, inner, options)
        if sent_filter is not None and sent_filter.size:
            cand_sids = sent_filter
        else:
            cand_sids = self._anchor_sentence_ids(query, inner, options)

        if docset_mask is not None and cand_sids.size:
            # Verlustfrei vorfiltern, genau entscheiden je Position.
            cand_sids = _saetze_im_docset(corpus, cand_sids, docset_mask)

        pos_sents = self._pos_sentence_ids(query, inner, options)
        if pos_sents is not None and pos_sents.size:
            cand_sids = intersect_sorted_unique(cand_sids, pos_sents)
        if sent_filter is not None and sent_filter.size and cand_sids is not sent_filter:
            cand_sids = intersect_sorted_unique(cand_sids, sent_filter)

        matcher = _PreparedSentenceMatcher(nfa, corpus, cand_sids)
        _t2d = corpus.token_to_doc() if docset_mask is not None else None
        for idx, (_, spans) in enumerate(matcher.iter_nonempty_sentence_spans(options.max_matches), start=1):
            if progress_cb is not None and (idx & 0x3FF) == 0:
                progress_cb("count:scan")
            if _t2d is not None:
                # Zaehlen, was die Maske je Position wirklich haelt. Sonst
                # zaehlt der Count Treffer mit, die search verwirft.
                total += sum(
                    1 for a, _b in spans
                    if _position_im_docset(_t2d, docset_mask, int(a)) >= 0
                )
            else:
                total += len(spans)
            if total >= options.max_matches:
                return total
        return total

    def _search_sequence_postings(
        self,
        clauses: List[Node],
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
    ) -> Optional[List[Match]]:
        cand = self._sequence_postings_candidates(clauses, scope, docset_mask, options)
        if cand is None:
            return None
        starts, ends, sent_ids, dids = cand
        n = int(starts.shape[0])
        out: List[Match] = []
        if scope == 's':
            assert sent_ids is not None
            for i in range(n):
                out.append(
                    Match(
                        start=int(starts[i]),
                        end=int(ends[i]),
                        sentence_id=int(sent_ids[i]),
                        doc_id=int(dids[i]),
                    )
                )
            return out
        for i in range(n):
            out.append(
                Match(
                    start=int(starts[i]),
                    end=int(ends[i]),
                    sentence_id=None,
                    doc_id=int(dids[i]),
                )
            )
        return out

    def _sequence_postings_candidates(
        self,
        clauses: List[Node],
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
        query: Optional[str] = None,
        timings: Optional[Dict[str, float]] = None,
        include_ids: bool = True,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], np.ndarray]]:
        corpus = self.corpus
        compiled_cache = self._compiled_clause_cache
        indexable_cache = self._indexable_cache
        positions_cache = self._clause_positions_cache
        node_simple: List[Optional[Tuple[str, np.ndarray, int]]] = []
        pos_lists: List[Optional[np.ndarray]] = [None] * len(clauses)
        est_sizes: List[int] = []

        t_compile = None
        if timings is not None:
            t_compile = time.perf_counter()

        for i, node in enumerate(clauses):
            simple = _simple_indexable_from_node(
                node,
                corpus,
                progress_cb=options.progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
            )
            node_simple.append(simple)
            if simple is None:
                base = _positions_for_node(
                    node,
                    corpus,
                    progress_cb=options.progress_cb,
                    compiled_cache=compiled_cache,
                    indexable_cache=indexable_cache,
                    positions_cache=positions_cache,
                )
                if base is None:
                    return None
                pos_lists[i] = base
                est_sizes.append(int(base.size))
            else:
                est_sizes.append(int(simple[2]))

        if not clauses:
            empty = np.empty((0,), dtype=np.int32)
            return empty, empty, empty, empty

        if timings is not None and t_compile is not None:
            timings["compile"] = timings.get("compile", 0.0) + (time.perf_counter() - t_compile)

        use_planner = get_bool("CANDYCONC_CQLHPC_PLANNER", True)
        if len(clauses) <= 2:
            use_planner = False
        if use_planner:
            min_tokens = get_int("CANDYCONC_CQLHPC_PLANNER_MIN_TOKENS", 200000)
            min_total = get_int("CANDYCONC_CQLHPC_PLANNER_MIN_TOTAL", 0)
            if min_tokens > 0 and corpus.n_tokens < min_tokens:
                use_planner = False
            elif min_total > 0 and sum(est_sizes) < min_total:
                use_planner = False
        plan = None
        t_plan = None
        if use_planner:
            if timings is not None:
                t_plan = time.perf_counter()
            cache_key = None
            if query is not None:
                cache_key = self._planner_cache_key(query, scope, docset_mask)
                cached = self._plan_cache.get(cache_key)
                if cached is not _CACHE_MISSING:
                    plan = cached
            if plan is None:
                try:
                    plan = plan_sequence(corpus, node_simple, pos_lists, docset_mask, scope)
                    if plan is not None and not validate_plan(plan, len(clauses)):
                        plan = None
                    if plan is not None and cache_key is not None:
                        self._plan_cache.set(cache_key, plan)
                    if plan is not None and options.progress_cb and get_bool("CANDYCONC_CQLHPC_PLANNER_EXPLAIN", False):
                        options.progress_cb(f"[planner] {explain_plan(plan)}")
                except Exception:
                    plan = None
            if timings is not None and t_plan is not None:
                timings["plan"] = timings.get("plan", 0.0) + (time.perf_counter() - t_plan)

        if plan is not None and plan.strategy == "hybrid":
            return None

        docset_ratio = None
        tok_to_doc = None
        docset_sig = None
        if docset_mask is not None:
            total_docs = int(corpus.doc_starts.shape[0])
            if total_docs > 0:
                docset_count = int(np.count_nonzero(docset_mask))
                docset_ratio = docset_count / total_docs
            max_ratio = get_float("CANDYCONC_CQLHPC_DOCSET_FILTER_RATIO", 0.2)
            if docset_ratio is not None and docset_ratio <= max_ratio:
                tok_to_doc = corpus.token_to_doc()
                docset_sig = _docset_signature(docset_mask)

        def _filter_positions_docset(pos: np.ndarray) -> np.ndarray:
            if tok_to_doc is None or docset_mask is None or pos.size == 0:
                return pos
            dids = tok_to_doc[pos]
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                return np.empty((0,), dtype=np.int32)
            if not np.all(ok):
                return pos[ok]
            return pos

        t_exec = None
        if timings is not None:
            t_exec = time.perf_counter()

        def _return_exec(value):
            if timings is not None and t_exec is not None:
                timings["exec"] = timings.get("exec", 0.0) + (time.perf_counter() - t_exec)
            return value

        allow_finalize_probe = _can_probe_finalize_sequence(clauses)

        def _finalize_candidates(candidates: np.ndarray):
            starts = candidates - anchor_i
            seq_len = len(pos_lists)
            ends = starts + seq_len

            sent_ids: Optional[np.ndarray] = None
            dids: Optional[np.ndarray] = None
            sent_ids_tmp: Optional[np.ndarray] = None
            dids_tmp: Optional[np.ndarray] = None
            if scope == 's':
                probe_finalized = False
                # Most sequence queries only need the first max_matches hits and only
                # a small fraction of anchors sit on sentence boundaries. Probe a
                # bounded prefix first and fall back to the full pass only if it does
                # not yield enough valid matches.
                probe_extra = get_int("CANDYCONC_CQLHPC_FINALIZE_PROBE_EXTRA", 512)
                probe_max_matches = get_int("CANDYCONC_CQLHPC_FINALIZE_PROBE_MAX_MATCHES", 1024)
                if (
                    probe_extra > 0
                    and options.max_matches > 0
                    and options.max_matches <= probe_max_matches
                    and allow_finalize_probe
                    and docset_mask is None
                    and starts.shape[0] > options.max_matches
                ):
                    probe_n = int(min(starts.shape[0], options.max_matches + probe_extra))
                    probe_starts = starts[:probe_n]
                    tok_to_sent = corpus.token_to_sent()
                    probe_sids = tok_to_sent[probe_starts]
                    probe_ok = (probe_starts + seq_len - 1) < corpus.sent_ends[probe_sids]
                    if int(np.count_nonzero(probe_ok)) >= int(options.max_matches):
                        starts = probe_starts[probe_ok][: int(options.max_matches)]
                        ends = starts + seq_len
                        if include_ids:
                            sent_ids = probe_sids[probe_ok][: int(options.max_matches)]
                        probe_finalized = True
                if not probe_finalized:
                    tok_to_sent = corpus.token_to_sent()
                    sids = tok_to_sent[starts]
                    ok = (ends - 1) < corpus.sent_ends[sids]
                    starts = starts[ok]
                    ends = ends[ok]
                    if include_ids:
                        sent_ids = sids[ok]
                    elif docset_mask is not None:
                        sent_ids_tmp = sids[ok]
            elif scope == 'doc':
                tok_to_doc = corpus.token_to_doc()
                dids_tmp = tok_to_doc[starts]
                ok = (ends - 1) < corpus.doc_ends[dids_tmp]
                starts = starts[ok]
                ends = ends[ok]
                if include_ids or docset_mask is not None:
                    dids_tmp = dids_tmp[ok]
                    if include_ids:
                        dids = dids_tmp
            if docset_mask is not None:
                if dids_tmp is None:
                    # Die Maske entscheidet ueber das Dokument der
                    # TREFFERPOSITION, nicht ueber das des Satzes.
                    #
                    # Vorher wurde ``sent_to_doc()[sent_ids]`` benutzt, also
                    # EIN Dokument fuer den ganzen Satz. Ein Satz, der eine
                    # Dokumentgrenze ueberlappt, gehoert dort ganz dem ersten
                    # Dokument, und ein Treffer im zweiten faellt aus BEIDEN
                    # Haelften einer Partition: aus der eigenen, weil die
                    # Maske das falsche Dokument prueft, und aus der anderen,
                    # weil er dort nicht liegt.
                    #
                    # On a small test index, [word="und"], masks split=test
                    # and split=train partition exactly (683 + 1317 = 2000):
                    #     unfiltered             797
                    #     test 197 + train 485 = 682, 115 lost (14 %)
                    #     [pos="NOUN"]  9,741 -> 2,416 + 5,821, 1,504 lost
                    # A mask over ALL documents loses nothing, which hides
                    # the effect. ALL 115 lost hits had
                    # sent_to_doc[sentence] != document(position): position
                    # 50 lies in document 2, its sentence points to 1.
                    #
                    # The consequence would be a silently too small
                    # per-million denominator on EVERY docset, and sentence
                    # bounding is the default. ``token_to_doc`` answers the
                    # question exactly.
                    dids_tmp = corpus.token_to_doc()[starts]
                ok = (dids_tmp >= 0) & (dids_tmp < docset_mask.shape[0]) & docset_mask[dids_tmp]
                starts = starts[ok]
                ends = ends[ok]
                dids_tmp = dids_tmp[ok]
                if include_ids:
                    dids = dids_tmp
                if sent_ids is not None:
                    sent_ids = sent_ids[ok]
                elif sent_ids_tmp is not None and include_ids:
                    sent_ids = sent_ids_tmp[ok]

            n = int(min(options.max_matches, starts.shape[0]))
            if n == 0:
                empty = np.empty((0,), dtype=np.int32)
                return _return_exec((empty, empty, empty, empty))
            starts = starts[:n]
            ends = ends[:n]
            if sent_ids is not None:
                sent_ids = sent_ids[:n]
            if include_ids:
                if dids is None and sent_ids is not None:
                    # DIESELBE Konvention wie im Maskenzweig. Eine
                    # Vorfassung hat nur den Zweig 'if docset_mask is not
                    # None' auf token_to_doc umgestellt, nicht die
                    # Ausgabe: damit hing die doc_id eines Treffers davon
                    # ab, OB eine Maske mitgeschickt wurde. Vorher waren
                    # beide Zweige einheitlich falsch, danach
                    # widersprachen sie einander -- und doc_id ist der
                    # Schluessel fuer Dokumentfrequenz, Dispersion und
                    # Dokumentzuschreibung.
                    dids = corpus.token_to_doc()[starts]
                if dids is None:
                    if dids_tmp is not None:
                        dids = dids_tmp[:n]
                    else:
                        dids = corpus.token_to_doc()[starts]
                dids = np.clip(dids, 0, int(corpus.doc_starts.shape[0]) - 1)
            else:
                dids = np.empty((0,), dtype=np.int32)
            return _return_exec((starts, ends, sent_ids, dids))

        anchor_i = int(plan.anchor_idx) if plan is not None else int(np.argmin(est_sizes))
        # Materialize anchor postings
        if pos_lists[anchor_i] is None:
            simple = node_simple[anchor_i]
            if simple is None:
                return _return_exec(None)
            cand = _materialize_simple_node_positions(
                clauses[anchor_i],
                simple,
                corpus,
                positions_cache,
            )
            pos_lists[anchor_i] = cand
        else:
            cand = pos_lists[anchor_i]  # type: ignore[assignment]
        if cand.size == 0:
            empty = np.empty((0,), dtype=np.int32)
            return _return_exec((empty, empty, empty, empty))

        # Pushdown: filter anchor candidates by sequence bounds + scope + docset.
        seq_len = len(pos_lists)
        n_tokens = corpus.n_tokens
        starts = cand - anchor_i
        ok = (starts >= 0) & (starts + seq_len <= n_tokens)
        if not np.any(ok):
            empty = np.empty((0,), dtype=np.int32)
            return _return_exec((empty, empty, empty, empty))
        if not np.all(ok):
            cand = cand[ok]
            starts = starts[ok]
        if docset_mask is not None:
            dids = corpus.token_to_doc()[starts]
            ok = (dids >= 0) & (dids < docset_mask.shape[0]) & docset_mask[dids]
            if not np.any(ok):
                empty = np.empty((0,), dtype=np.int32)
                return _return_exec((empty, empty, empty, empty))
            if not np.all(ok):
                cand = cand[ok]
                starts = starts[ok]

        if plan is not None:
            order_steps = plan.ordered
        else:
            order = sorted(
                ((est_sizes[j], j) for j in range(len(clauses)) if j != anchor_i),
                key=lambda x: x[0],
            )
            order_steps_list: List[ClausePlan] = []
            for size, j in order:
                simple = node_simple[j]
                method = "bitset" if _prefer_sequence_bitset(simple, int(size), int(corpus.n_tokens)) else "merge"
                order_steps_list.append(ClausePlan(idx=j, method=method, est_cost=float(size)))
            order_steps = tuple(order_steps_list)

        if plan is not None and plan.strategy == "partitioned":
            res = self._sequence_postings_partitioned(
                cand,
                anchor_i,
                clauses,
                node_simple,
                pos_lists,
                order_steps,
                scope,
                docset_mask,
                options,
            )
            if res is not None:
                return _return_exec(res)

        if order_steps:
            n_tokens = corpus.n_tokens
            others: List[np.ndarray] = []
            shifts: List[int] = []
            for step in order_steps:
                j = step.idx
                shift = j - anchor_i
                simple = node_simple[j]
                if step.method == "bitset":
                    if pos_lists[j] is not None:
                        pos = _filter_positions_docset(pos_lists[j])
                        pos_lists[j] = pos
                        bitset = positions_to_bitset(pos, n_tokens)
                    else:
                        if simple is None:
                            return _return_exec(None)
                        attr, tids, _ = simple
                        key = ("bitset", attr, _ids_cache_key(tids), docset_sig)
                        cached = self._bitset_cache.get(key)
                        if cached is _CACHE_MISSING:
                            bitset = None
                            if len(tids) == 1:
                                bitset = self._dense_bitset_for_type(attr, int(tids[0]))
                            else:
                                bitset = self._dense_bitset_for_types(attr, tids)
                            if bitset is None:
                                if tok_to_doc is None:
                                    bitset = self._postings_bitset(attr, tids, n_tokens)
                                else:
                                    pos = self._postings_positions(attr, tids)
                                    pos = _filter_positions_docset(pos)
                                    bitset = positions_to_bitset(pos, n_tokens)
                            self._bitset_cache.set(key, bitset)
                        else:
                            bitset = cached
                    cand = filter_positions_by_bitset_no_bounds(cand, bitset, shift)
                    if cand.size == 0:
                        empty = np.empty((0,), dtype=np.int32)
                        return _return_exec((empty, empty, empty, empty))
                    continue

                if pos_lists[j] is not None:
                    arr = pos_lists[j]  # type: ignore[assignment]
                else:
                    if simple is None:
                        return _return_exec(None)
                    arr = _materialize_simple_node_positions(
                        clauses[j],
                        simple,
                        corpus,
                        positions_cache,
                    )
                    pos_lists[j] = arr
                arr = _filter_positions_docset(arr)
                pos_lists[j] = arr
                if arr.size == 0:
                    empty = np.empty((0,), dtype=np.int32)
                    return _return_exec((empty, empty, empty, empty))
                others.append(arr)
                shifts.append(shift)

            if others:
                adaptive = get_bool("CANDYCONC_CQLHPC_ADAPTIVE_INTERSECT", True)
                gallop_ratio = get_float("CANDYCONC_CQLHPC_GALLOP_RATIO", 4.0)
                if adaptive:
                    for arr, sh in zip(others, shifts):
                        cand = self._intersect_shifted_adaptive(cand, arr, sh, gallop_ratio)
                        if cand.size == 0:
                            empty = np.empty((0,), dtype=np.int32)
                            return _return_exec((empty, empty, empty, empty))
                else:
                    cand = intersect_shifted_many(cand, others, shifts)
                    if cand.size == 0:
                        empty = np.empty((0,), dtype=np.int32)
                        return _return_exec((empty, empty, empty, empty))
        return _finalize_candidates(cand)

    def _count_sequence_postings(
        self,
        clauses: List[Node],
        scope: Optional[str],
        docset_mask: Optional[np.ndarray],
        options: SearchOptions,
        query: str,
    ) -> Optional[int]:
        cand = self._sequence_postings_candidates(
            clauses,
            scope,
            docset_mask,
            options,
            query=query,
            include_ids=False,
        )
        if cand is None:
            return None
        starts, _, _, _ = cand
        total = int(starts.shape[0])
        if total <= 0:
            return 0
        if total > options.max_matches:
            return int(options.max_matches)
        return total


# ----------------- helpers --------------------------------------------------


def _collect_sequence_parts(node: Node, out: List[Node]) -> bool:
    if isinstance(node, Seq):
        for p in node.parts:
            if not _collect_sequence_parts(p, out):
                return False
        return True
    if isinstance(node, Quant):
        if node.m == 1 and node.n == 1:
            return _collect_sequence_parts(node.node, out)
        if node.n is not None and node.m == node.n and node.m > 1:
            max_expand = get_int("CANDYCONC_CQLHPC_MAX_QUANT_EXPAND", 4)
            if node.m <= max_expand:
                for _ in range(node.m):
                    if not _collect_sequence_parts(node.node, out):
                        return False
                return True
        return False
    if isinstance(node, Within):
        return _collect_sequence_parts(node.node, out)
    if isinstance(node, Where):
        return _collect_sequence_parts(node.node, out)
    out.append(node)
    return True


def _contains_where(node: Node) -> bool:
    if isinstance(node, Where):
        return True
    if isinstance(node, Seq):
        return any(_contains_where(part) for part in node.parts)
    if isinstance(node, Alt):
        return any(_contains_where(option) for option in node.options)
    if isinstance(node, Quant):
        return _contains_where(node.node)
    if isinstance(node, Within):
        return _contains_where(node.node)
    return False


def _clause_cache_key(clause: TokenClause) -> Tuple[Tuple[str, str, object, str], ...]:
    parts: List[Tuple[str, str, object, str]] = []
    for c in clause.conds:
        v = c.value
        if isinstance(v, list):
            v = tuple(v)
        # ``flags`` (e.g. ``%c``) must be part of the key: a case-insensitive
        # condition resolves to a different id set than its case-sensitive twin,
        # so they must not share compiled-clause / positions cache entries.
        parts.append((c.attr, c.op, v, getattr(c, "flags", "")))
    return tuple(parts)


def _node_sentence_shift_key(node: Node):
    if isinstance(node, Tok):
        return ("tok", _clause_cache_key(node.clause))
    if isinstance(node, Quant):
        inner = _node_sentence_shift_key(node.node)
        if inner is None:
            return None
        return ("quant", inner, int(node.m), None if node.n is None else int(node.n))
    if isinstance(node, Alt):
        parts = []
        for part in node.options:
            key = _node_sentence_shift_key(part)
            if key is None:
                return None
            parts.append(key)
        return ("alt", tuple(parts))
    if isinstance(node, Seq):
        parts = []
        for part in node.parts:
            key = _node_sentence_shift_key(part)
            if key is None:
                return None
            parts.append(key)
        return ("seq", tuple(parts))
    if isinstance(node, Within):
        inner = _node_sentence_shift_key(node.node)
        if inner is None:
            return None
        return ("within", node.scope, inner)
    if isinstance(node, Where):
        inner = _node_sentence_shift_key(node.node)
        if inner is None:
            return None
        return ("where", inner, repr(node.expr))
    return None


def _is_exact_tok_node(node: Node) -> bool:
    if not isinstance(node, Tok):
        return False
    conds = getattr(node.clause, "conds", ())
    return bool(conds) and all(cond.op in {"=", "in"} for cond in conds)


def _can_probe_finalize_sequence(clauses: List[Node]) -> bool:
    return 0 < len(clauses) <= 2 and all(_is_exact_tok_node(node) for node in clauses)


def _sent_filter_query_cache_key(query: str):
    return (
        query,
        float(get_float("CANDYCONC_CQLHPC_SENT_FILTER_MAX_RATIO", 0.95)),
        int(get_int("CANDYCONC_CQLHPC_SENT_SHIFT_PREFILTER_MAX_EXTRA", 32)),
    )


def _positions_cache_get(positions_cache, key):
    if hasattr(positions_cache, "get"):
        cached = positions_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
        return None
    return positions_cache.get(key)


def _positions_cache_set(positions_cache, key, value: np.ndarray) -> None:
    if hasattr(positions_cache, "set"):
        positions_cache.set(key, value)
    else:
        positions_cache[key] = value


def _sentence_ids_cache_get(sentence_ids_cache, key):
    if hasattr(sentence_ids_cache, "get"):
        cached = sentence_ids_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
        return None
    return sentence_ids_cache.get(key)


def _sentence_ids_cache_set(sentence_ids_cache, key, value: np.ndarray) -> None:
    if hasattr(sentence_ids_cache, "set"):
        sentence_ids_cache.set(key, value)
    else:
        sentence_ids_cache[key] = value


def _sentence_ids_for_tok_clause(
    node: Tok,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
    positions_cache,
    sentence_ids_cache,
) -> Optional[np.ndarray]:
    key = _clause_cache_key(node.clause)
    cached = _sentence_ids_cache_get(sentence_ids_cache, key)
    if cached is not None:
        return cached
    pos = _positions_for_node(
        node,
        corpus,
        progress_cb=progress_cb,
        compiled_cache=compiled_cache,
        indexable_cache=indexable_cache,
        positions_cache=positions_cache,
    )
    if pos is None:
        return None
    sent_ids = sentence_ids_for_positions(pos, corpus.sent_ends)
    _sentence_ids_cache_set(sentence_ids_cache, key, sent_ids)
    return sent_ids


def _token_length_range(node: Node) -> Optional[Tuple[int, int]]:
    while isinstance(node, (Within, Where)):
        node = node.node
    if isinstance(node, Tok):
        return (1, 1)
    if isinstance(node, Alt):
        mins: List[int] = []
        maxs: List[int] = []
        for opt in node.options:
            rng = _token_length_range(opt)
            if rng is None:
                return None
            mins.append(rng[0])
            maxs.append(rng[1])
        if not mins:
            return (0, 0)
        return (min(mins), max(maxs))
    if isinstance(node, Quant):
        inner = _token_length_range(node.node)
        if inner is None or node.n is None:
            return None
        return (inner[0] * node.m, inner[1] * node.n)
    if isinstance(node, Seq):
        min_total = 0
        max_total = 0
        for part in node.parts:
            rng = _token_length_range(part)
            if rng is None:
                return None
            min_total += rng[0]
            max_total += rng[1]
        return (min_total, max_total)
    return None


def _token_length_bounds(node: Node) -> Optional[Tuple[int, Optional[int]]]:
    while isinstance(node, (Within, Where)):
        node = node.node
    if isinstance(node, Tok):
        return (1, 1)
    if isinstance(node, Alt):
        mins: List[int] = []
        maxs: List[Optional[int]] = []
        for opt in node.options:
            rng = _token_length_bounds(opt)
            if rng is None:
                return None
            mins.append(rng[0])
            maxs.append(rng[1])
        if not mins:
            return (0, 0)
        if any(m is None for m in maxs):
            return (min(mins), None)
        return (min(mins), max(int(m) for m in maxs if m is not None))
    if isinstance(node, Quant):
        inner = _token_length_bounds(node.node)
        if inner is None:
            return None
        min_total = inner[0] * node.m
        if node.n is None or inner[1] is None:
            return (min_total, None)
        return (min_total, inner[1] * node.n)
    if isinstance(node, Seq):
        min_total = 0
        max_total: Optional[int] = 0
        for part in node.parts:
            rng = _token_length_bounds(part)
            if rng is None:
                return None
            min_total += rng[0]
            if max_total is None or rng[1] is None:
                max_total = None
            else:
                max_total += rng[1]
        return (min_total, max_total)
    return None


def _sequence_shift_sentence_ids(
    node: Seq,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
    positions_cache,
    sentence_ids_cache,
    shift_sentence_cache=None,
) -> Optional[np.ndarray]:
    parts = node.parts
    if len(parts) < 2:
        return None
    left_node: Node = parts[0]
    right_node: Node = parts[-1]
    while isinstance(left_node, (Within, Where)):
        left_node = left_node.node
    while isinstance(right_node, (Within, Where)):
        right_node = right_node.node
    if isinstance(left_node, Quant) and left_node.m > 0:
        left_node = left_node.node
    if isinstance(right_node, Quant) and right_node.m > 0:
        right_node = right_node.node
    max_extra = max(0, get_int("CANDYCONC_CQLHPC_SENT_SHIFT_PREFILTER_MAX_EXTRA", 32))
    mid_min = 0
    mid_max = 0
    unbounded = False
    for part in parts[1:-1]:
        bounds = _token_length_bounds(part)
        if bounds is None:
            return None
        mid_min += bounds[0]
        if bounds[1] is None:
            unbounded = True
            continue
        mid_max += bounds[1]
        if mid_max > max_extra:
            return None
    start_shift = 1 + mid_min
    end_shift = 1 + mid_max
    if not unbounded and start_shift > end_shift:
        return None
    cache_key = None
    if shift_sentence_cache is not None:
        left_key = _node_sentence_shift_key(left_node)
        right_key = _node_sentence_shift_key(right_node)
        if left_key is not None and right_key is not None:
            if unbounded:
                cache_key = ("shift-min", left_key, right_key, int(start_shift))
            else:
                cache_key = ("shift-range", left_key, right_key, int(start_shift), int(end_shift), int(max_extra))
            cached = shift_sentence_cache.get(cache_key)
            if cached is not _CACHE_MISSING:
                return cached
    left = _positions_for_node(
        left_node,
        corpus,
        progress_cb=progress_cb,
        compiled_cache=compiled_cache,
        indexable_cache=indexable_cache,
        positions_cache=positions_cache,
    )
    if left is None or left.size == 0:
        empty = np.empty((0,), dtype=np.int32)
        if cache_key is not None:
            shift_sentence_cache.set(cache_key, empty)
        return empty
    right = _positions_for_node(
        right_node,
        corpus,
        progress_cb=progress_cb,
        compiled_cache=compiled_cache,
        indexable_cache=indexable_cache,
        positions_cache=positions_cache,
    )
    if right is None or right.size == 0:
        empty = np.empty((0,), dtype=np.int32)
        if cache_key is not None:
            shift_sentence_cache.set(cache_key, empty)
        return empty
    if unbounded:
        result = sentence_ids_for_min_shift_same_sentence(
            left,
            right,
            start_shift,
            corpus.sent_ends,
        )
    else:
        result = sentence_ids_for_shifted_range(
            left,
            right,
            start_shift,
            end_shift,
            corpus.sent_ends,
        )
    if cache_key is not None:
        shift_sentence_cache.set(cache_key, result)
    return result


def _materialize_simple_node_positions(
    node: Node,
    simple: Tuple[str, np.ndarray, int],
    corpus: Corpus,
    positions_cache,
) -> np.ndarray:
    attr, tids, _ = simple
    if isinstance(node, Tok):
        key = _clause_cache_key(node.clause)
        cached = _positions_cache_get(positions_cache, key)
        if cached is not None:
            return cached
        pos = _materialize_attr_positions(attr, tids, corpus)
        _positions_cache_set(positions_cache, key, pos)
        return pos
    return _materialize_attr_positions(attr, tids, corpus)


def _materialize_attr_positions(attr: str, tids: np.ndarray, corpus: Corpus) -> np.ndarray:
    # Route position narrowing through the checked uint32->int32 helper so this
    # path matches FastPostingsIndex.list (SCALE1). Unreachable for corpora
    # > MAX_I32 today (open-time guards reject them), kept consistent so a future
    # open path can never silently alias a >2^31 position to a negative int32.
    backend = getattr(corpus, "backend", None)
    if tids.size == 1 and backend is not None and hasattr(backend, "_positions_for_id"):
        try:
            out = backend._positions_for_id(attr, int(tids[0]))
            return _u32_to_i32_safe(out)
        except Exception:
            pass
    if backend is not None and hasattr(backend, "_union_positions_for_ids"):
        try:
            out = backend._union_positions_for_ids(attr, tids.astype(np.int32, copy=False))
            return _u32_to_i32_safe(out)
        except Exception:
            pass
    return merge_postings_many(corpus.postings_index(attr), tids)


def _is_empty_token_clause(node: Node) -> bool:
    """True for the ``[]`` "any token" wildcard (a zero-condition token clause)."""
    return isinstance(node, Tok) and len(node.clause.conds) == 0


def _as_postings_sequence(node: Node) -> Optional[List[Node]]:
    parts: List[Node] = []
    if not _collect_sequence_parts(node, parts):
        return None
    # The postings-intersection fast path models each clause by its concrete
    # token positions. An empty ``[]`` clause matches *every* position, which
    # that model cannot represent (an empty indexable would wrongly intersect
    # the sequence down to zero hits). Defer any sequence containing ``[]`` to
    # the hybrid NFA path, where a zero-condition predicate is universally true.
    if any(_is_empty_token_clause(p) for p in parts):
        return None
    return parts


def _prefer_sequence_bitset(
    simple: Optional[Tuple[str, np.ndarray, int]],
    est_size: int,
    n_tokens: int,
) -> bool:
    if simple is None or n_tokens <= 0 or est_size <= 0:
        return False
    density = est_size / float(n_tokens)
    threshold = get_float("CANDYCONC_CQLHPC_SEQUENCE_BITSET_DENSITY", 0.01)
    return density >= threshold


def _compile_clause_cached(
    clause: TokenClause,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache,
) -> CompiledClause:
    key = _clause_cache_key(clause)
    cc = None
    if hasattr(compiled_cache, "get"):
        cc = compiled_cache.get(key)
        if cc is _CACHE_MISSING:
            cc = None
    else:
        cc = compiled_cache.get(key)
    if cc is None:
        cc = compile_clause(clause, corpus, progress_cb=progress_cb)
        if hasattr(compiled_cache, "set"):
            compiled_cache.set(key, cc)
        else:
            compiled_cache[key] = cc
    return cc


def _best_indexable_cached(
    clause: TokenClause,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    indexable_cache,
) -> Optional[Indexable]:
    key = _clause_cache_key(clause)
    if hasattr(indexable_cache, "get"):
        try:
            cached = indexable_cache.get(key, _CACHE_MISSING)
        except TypeError:
            cached = indexable_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
    else:
        if key in indexable_cache:
            return indexable_cache[key]
    idx = best_indexable(clause, corpus, progress_cb=progress_cb)
    if hasattr(indexable_cache, "set"):
        indexable_cache.set(key, idx)
    else:
        indexable_cache[key] = idx
    return idx


def _best_indexable_from_compiled_clause(
    clause: TokenClause,
    compiled: CompiledClause,
    corpus: Corpus,
    *,
    indexable_cache,
) -> Optional[Indexable]:
    key = _clause_cache_key(clause)
    if hasattr(indexable_cache, "get"):
        try:
            cached = indexable_cache.get(key, _CACHE_MISSING)
        except TypeError:
            cached = indexable_cache.get(key)
        if cached is not _CACHE_MISSING:
            return cached
    else:
        if key in indexable_cache:
            return indexable_cache[key]

    best: Optional[Indexable] = None
    postings_by_attr: Dict[str, Any] = {}
    lexicons_by_attr: Dict[str, Any] = {}
    for attr, op, vals in compiled.conds:
        if op not in {"=", "in"}:
            continue
        vals_i32 = vals.astype(np.int32, copy=False)
        lex = lexicons_by_attr.get(attr)
        if lex is None:
            lex = corpus.lexicon(attr)
            lexicons_by_attr[attr] = lex
        freq_many = getattr(lex, "get_freqs_for_ids", None)
        if not callable(freq_many):
            base_lex = getattr(lex, "_lexicon", None)
            freq_many = getattr(base_lex, "get_freqs_for_ids", None)
        if callable(freq_many):
            est = int(freq_many(vals_i32).sum(dtype=np.int64))
        else:
            postings = postings_by_attr.get(attr)
            if postings is None:
                postings = corpus.postings_index(attr)
                postings_by_attr[attr] = postings
            est = 0
            for tid in vals_i32:
                est += postings.length(int(tid))
        cand = Indexable(attr=attr, type_ids=vals_i32, est_len=int(est))
        if best is None or cand.est_len < best.est_len:
            best = cand

    if hasattr(indexable_cache, "set"):
        indexable_cache.set(key, best)
    else:
        indexable_cache[key] = best
    return best


def _estimate_indexable_len(attr: str, vals_i32: np.ndarray, corpus: Corpus) -> int:
    lex = corpus.lexicon(attr)
    freq_many = getattr(lex, "get_freqs_for_ids", None)
    if not callable(freq_many):
        base_lex = getattr(lex, "_lexicon", None)
        freq_many = getattr(base_lex, "get_freqs_for_ids", None)
    if callable(freq_many):
        return int(freq_many(vals_i32).sum(dtype=np.int64))
    postings = corpus.postings_index(attr)
    est = 0
    for tid in vals_i32:
        est += postings.length(int(tid))
    return int(est)


def _cache_set(cache, key, value) -> None:
    if hasattr(cache, "set"):
        cache.set(key, value)
    else:
        cache[key] = value


def _simple_indexable_from_clause(
    clause: TokenClause,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache,
    indexable_cache,
    allow_empty: bool = False,
) -> Optional[Tuple[str, np.ndarray, int]]:
    """Resolve a single-condition token clause to its postings indexable.

    ``allow_empty`` changes how an out-of-vocabulary operand is handled. By
    default (``False``) an OOV literal raises the recognised "liefert keine
    Treffer" empty-match error so the bare-term / sequence fast path surfaces an
    empty result. Alternation callers pass ``allow_empty=True``: an OOV operand
    then returns the ``_EMPTY_OPERAND`` marker instead of raising, so the union
    can absorb it and still match the other branches. An all-OOV alternation
    therefore collapses to an empty indexable rather than re-raising.
    """
    key = _clause_cache_key(clause)
    if hasattr(indexable_cache, "get"):
        try:
            cached = indexable_cache.get(key, _CACHE_MISSING)
        except TypeError:
            cached = indexable_cache.get(key)
        if cached is not _CACHE_MISSING:
            if cached is None:
                return None
            return cached.attr, cached.type_ids, int(cached.est_len)
    else:
        if key in indexable_cache:
            cached = indexable_cache[key]
            if cached is None:
                return None
            return cached.attr, cached.type_ids, int(cached.est_len)

    if len(clause.conds) != 1:
        _cache_set(indexable_cache, key, None)
        return None

    cond = clause.conds[0]
    if cond.op not in {"=", "in", "~"}:
        _cache_set(indexable_cache, key, None)
        return None
    if not corpus.has_attr(cond.attr):
        raise ValueError(UNKNOWN_ATTRIBUTE.format(attr=cond.attr))
    # Closed-class (pos) out-of-tagset value: fail loudly with the valid
    # inventory instead of the silent "liefert keine Treffer" empty path below
    # (release finding 35). Scoped to pos inside the helper; open-class word/lemma
    # zero-results are unaffected and still flow to the empty-match path. In an
    # alternation (``allow_empty``) we keep the absorb-OOV-branch contract and do
    # NOT raise, so ``[pos="NOUN"] | [pos="NN"]`` still returns the NOUN hits.
    if not allow_empty:
        _check_closed_class_value(cond, corpus)

    vals = _value_to_type_ids(cond, corpus, progress_cb=progress_cb)
    if vals is None:
        # An out-of-vocabulary ``=`` literal is a zero-result, not an
        # unresolvable query (see compile_clause for the full rationale). In an
        # alternation (``allow_empty``) the operand is absorbed; otherwise raise
        # the *recognised* empty-match error so the caller surfaces zero hits
        # instead of a 500 on this single-clause postings fast path.
        if cond.op == "=" and isinstance(cond.value, str):
            if allow_empty:
                return _EMPTY_OPERAND
            raise EmptyMatchError(
                _NO_HITS.format(attr=cond.attr, op=cond.op, value=cond.value)
            )
        raise UnresolvableConditionError(
            _UNRESOLVABLE.format(attr=cond.attr, op=cond.op, value=cond.value)
        )
    if vals.size == 0:
        if allow_empty:
            return _EMPTY_OPERAND
        raise EmptyMatchError(
            _NO_HITS.format(attr=cond.attr, op=cond.op, value=cond.value)
        )

    vals_i32 = vals.astype(np.int32, copy=False)
    idx = Indexable(
        attr=cond.attr,
        type_ids=vals_i32,
        est_len=_estimate_indexable_len(cond.attr, vals_i32, corpus),
    )
    _cache_set(indexable_cache, key, idx)
    # Lower the NFA op the same way ``compile_clause`` does: ``~`` (regex), a
    # ``%c`` case-insensitive ``=``, and a CWB-style double-quoted regex ``=``
    # all resolve to a *set* of lexicon ids and must use the membership op
    # (``=`` reads only ``vals[0]`` and would silently match a single id).
    if cond.op == "~":
        nfa_op = "in"
    elif cond.op == "=" and (cond.flags == "c" or vals_i32.size > 1):
        nfa_op = "in"
    else:
        nfa_op = cond.op
    _cache_set(
        compiled_cache,
        key,
        CompiledClause(conds=((cond.attr, nfa_op, vals_i32),)),
    )
    return idx.attr, idx.type_ids, int(idx.est_len)


def _positions_for_alt_simple(
    node: Alt,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
) -> Optional[np.ndarray]:
    attr: Optional[str] = None
    vals_parts: List[np.ndarray] = []
    local_indexable_cache: Dict[TokenClause, Optional[Indexable]] = {}
    for opt in node.options:
        if not isinstance(opt, Tok):
            return None
        simple = _simple_indexable_from_clause(
            opt.clause,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
            indexable_cache=local_indexable_cache,
            allow_empty=True,
        )
        if simple is None:
            return None
        if simple is _EMPTY_OPERAND:
            # OOV branch contributes no postings -> absorb it into the union.
            continue
        attr2, vals, _ = simple
        if attr is None:
            attr = attr2
        elif attr2 != attr:
            return None
        vals_parts.append(vals)
    if attr is None or not vals_parts:
        # Every branch was OOV (or empty) -> the alternation matches nothing.
        return np.empty((0,), dtype=np.int32)
    if len(vals_parts) == 1:
        merged = vals_parts[0].astype(np.int32, copy=False)
    else:
        merged = np.unique(np.concatenate(vals_parts)).astype(np.int32, copy=False)
    if merged.size == 0:
        return np.empty((0,), dtype=np.int32)
    return _materialize_attr_positions(attr, merged, corpus)


def _simple_indexable_from_node(
    node: Node,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
) -> Optional[Tuple[str, np.ndarray, int]]:
    if isinstance(node, Quant):
        if node.m == 1 and node.n == 1:
            return _simple_indexable_from_node(
                node.node,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
            )
        return None
    if isinstance(node, Tok):
        return _simple_indexable_from_clause(
            node.clause,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
            indexable_cache=indexable_cache,
        )
    if isinstance(node, Alt):
        attr: Optional[str] = None
        merged: List[np.ndarray] = []
        all_empty = True
        for opt in node.options:
            if not isinstance(opt, Tok):
                return None
            simple = _simple_indexable_from_clause(
                opt.clause,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                allow_empty=True,
            )
            if simple is None:
                return None
            if simple is _EMPTY_OPERAND:
                # OOV branch contributes no postings -> absorb it.
                continue
            all_empty = False
            a2, vals, _ = simple
            if attr is None:
                attr = a2
            elif a2 != attr:
                return None
            merged.append(vals)
        if all_empty:
            # Every branch was OOV: defer to the NFA path, which materialises an
            # empty result without the postings fast path. Returning None here
            # (not a fabricated empty indexable) keeps the attr/postings contract
            # of this helper intact for its callers.
            return None
        if attr is None:
            return None
        if len(merged) == 1:
            tids = merged[0].astype(np.int32, copy=False)
        else:
            tids = np.unique(np.concatenate(merged)).astype(np.int32, copy=False)
        if tids.size == 0:
            return None
        return attr, tids, _estimate_indexable_len(attr, tids, corpus)
    return None


def _extract_bounded_repeat_pattern(
    node: Node,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
) -> Optional[Tuple[Node, Node, Node, int, int]]:
    while isinstance(node, (Within, Where)):
        node = node.node
    if not isinstance(node, Seq) or len(node.parts) != 3:
        return None
    left, middle, right = node.parts
    if not isinstance(middle, Quant) or middle.n is None:
        return None
    if middle.m < 0 or middle.n < middle.m:
        return None
    if _token_length_bounds(left) != (1, 1):
        return None
    if _token_length_bounds(middle.node) != (1, 1):
        return None
    if _token_length_bounds(right) != (1, 1):
        return None
    # The bounded-repeat postings fast paths model each of the three operands by
    # its concrete token positions / a dense bitset. An empty ``[]`` ("any token")
    # clause matches *every* position, which that model cannot represent: it
    # resolves to ``None`` from ``_simple_indexable_from_node`` and then to an
    # all-zeros bitset (``positions_to_bitset(<empty>, n)``), silently collapsing
    # the whole query to zero matches. Defer any pattern with a ``[]`` operand
    # (left, middle, or right endpoint) to the hybrid NFA path, where a
    # zero-condition predicate is universally true. This fixes all three
    # consumers (sentence filter, sequence arrays, sequence matches).
    if any(_is_empty_token_clause(x) for x in (left, middle.node, right)):
        return None
    return left, middle.node, right, int(middle.m), int(middle.n)


def _positions_for_node(
    node: Node,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
    positions_cache,
) -> Optional[np.ndarray]:
    if isinstance(node, Tok):
        clause = node.clause
        key = _clause_cache_key(clause)
        cached = _positions_cache_get(positions_cache, key)
        if cached is not None:
            return cached
        cc = _compile_clause_cached(
            clause,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
        )
        exact = _positions_for_exact_clause(cc, corpus)
        if exact is not None:
            _positions_cache_set(positions_cache, key, exact)
            return exact
        idx = _best_indexable_cached(
            clause,
            corpus,
            progress_cb=progress_cb,
            indexable_cache=indexable_cache,
        )
        if idx is None:
            return None
        base = _materialize_attr_positions(idx.attr, idx.type_ids, corpus)
        out = _filter_positions(cc, base, corpus)
        _positions_cache_set(positions_cache, key, out)
        return out
    if isinstance(node, Quant):
        if node.m == 1 and node.n == 1:
            return _positions_for_node(
                node.node,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
            )
        return None
    if isinstance(node, Alt):
        simple = _positions_for_alt_simple(
            node,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
        )
        if simple is not None:
            return simple
        parts: List[np.ndarray] = []
        for opt in node.options:
            try:
                arr = _positions_for_node(
                    opt,
                    corpus,
                    progress_cb=progress_cb,
                    compiled_cache=compiled_cache,
                    indexable_cache=indexable_cache,
                    positions_cache=positions_cache,
                )
            except ValueError as exc:
                # An out-of-vocabulary branch must not abort the whole
                # alternation: a recognised empty-match (EmptyMatchError)
                # contributes nothing to the union; the other branches still
                # match. Any other ValueError (e.g. unknown attribute) propagates.
                if _is_recognised_empty_match(exc):
                    parts.append(np.empty((0,), dtype=np.int32))
                    continue
                raise
            if arr is None:
                return None
            parts.append(arr)
        return union_positions_many(parts)
    return None


def _is_recognised_empty_match(exc: ValueError) -> bool:
    """True for the recognised "this condition matches nothing" error, which an
    alternation branch may absorb rather than propagate.

    Entschieden wird am Typ, nicht am Meldungstext (siehe ``cqlhpc.errors``).
    """
    return isinstance(exc, EmptyMatchError)


def _positions_for_exact_clause(
    clause: CompiledClause,
    corpus: Corpus,
) -> Optional[np.ndarray]:
    grouped: Dict[str, np.ndarray] = {}
    for attr, op, vals in clause.conds:
        if op not in {"=", "in"}:
            return None
        vals_i32 = vals.astype(np.int32, copy=False)
        current = grouped.get(attr)
        if current is None:
            grouped[attr] = vals_i32
        else:
            merged_vals = intersect_sorted_unique(current, vals_i32)
            if merged_vals.size == 0:
                return np.empty((0,), dtype=np.int32)
            grouped[attr] = merged_vals.astype(np.int32, copy=False)
    if not grouped:
        return np.empty((0,), dtype=np.int32)

    postings_lists: List[np.ndarray] = []
    for attr, vals in grouped.items():
        arr = _materialize_attr_positions(attr, vals, corpus).astype(np.int32, copy=False)
        if arr.size == 0:
            return np.empty((0,), dtype=np.int32)
        postings_lists.append(arr)

    if len(postings_lists) == 1:
        return postings_lists[0]

    postings_lists.sort(key=lambda arr: int(arr.size))
    out = postings_lists[0]
    for arr in postings_lists[1:]:
        out = intersect_sorted_unique(out, arr)
        if out.size == 0:
            return out
    return out


def _expand_simple_sequence_variants(
    node: Node,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
) -> Optional[List[Tuple[Node, ...]]]:
    max_repeat = max(0, get_int("CANDYCONC_CQLHPC_EXPAND_MAX_REPEAT", 3))
    max_variants = max(0, get_int("CANDYCONC_CQLHPC_EXPAND_MAX_VARIANTS", 64))

    def _expand(n: Node) -> Optional[List[Tuple[Node, ...]]]:
        if isinstance(n, Tok):
            simple = _simple_indexable_from_node(
                n,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
            )
            if simple is None:
                return None
            return [(n,)]
        if isinstance(n, Alt):
            out: List[Tuple[Node, ...]] = []
            for opt in n.options:
                expanded = _expand(opt)
                if expanded is None:
                    return None
                out.extend(expanded)
                if max_variants > 0 and len(out) > max_variants:
                    return None
            return out
        if isinstance(n, Quant):
            if n.n is None or n.n > max_repeat:
                return None
            child_variants = _expand(n.node)
            if child_variants is None:
                return None
            out: List[Tuple[Node, ...]] = []
            for rep in range(n.m, n.n + 1):
                repeated: List[Tuple[Node, ...]] = [tuple()]
                for _ in range(rep):
                    next_repeated: List[Tuple[Node, ...]] = []
                    for prefix in repeated:
                        for child in child_variants:
                            next_repeated.append(prefix + child)
                            if max_variants > 0 and len(next_repeated) > max_variants:
                                return None
                    repeated = next_repeated
                out.extend(repeated)
                if max_variants > 0 and len(out) > max_variants:
                    return None
            return out
        if isinstance(n, Seq):
            variants: List[Tuple[Node, ...]] = [tuple()]
            for part in n.parts:
                expanded = _expand(part)
                if expanded is None:
                    return None
                next_variants: List[Tuple[Node, ...]] = []
                for prefix in variants:
                    for suffix in expanded:
                        next_variants.append(prefix + suffix)
                        if max_variants > 0 and len(next_variants) > max_variants:
                            return None
                variants = next_variants
            return variants
        if isinstance(n, Within):
            return _expand(n.node)
        if isinstance(n, Where):
            return _expand(n.node)
        return None

    variants = _expand(node)
    if not variants:
        return None
    if max_variants > 0 and len(variants) > max_variants:
        return None
    return variants


def _merge_expanded_sequence_candidates(
    candidates: List[Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], np.ndarray]],
    scope: Optional[str],
    max_matches: int,
) -> List[Match]:
    if not candidates or max_matches <= 0:
        return []
    starts = np.concatenate([c[0] for c in candidates]).astype(np.int64, copy=False)
    ends = np.concatenate([c[1] for c in candidates]).astype(np.int64, copy=False)
    sent_ids = np.concatenate([c[2] for c in candidates if c[2] is not None]).astype(np.int64, copy=False)
    dids = np.concatenate([c[3] for c in candidates]).astype(np.int64, copy=False)
    if starts.size == 0:
        return []

    order = np.lexsort((-ends, starts, sent_ids))
    out: List[Match] = []
    current_sid = -1
    current_end = -1
    for idx in order.tolist():
        sid = int(sent_ids[idx])
        start = int(starts[idx])
        end = int(ends[idx])
        if sid != current_sid:
            current_sid = sid
            current_end = -1
        if start < current_end:
            continue
        out.append(
            Match(
                start=start,
                end=end,
                sentence_id=sid if scope == "s" else None,
                doc_id=int(dids[idx]),
            )
        )
        current_end = end
        if len(out) >= max_matches:
            break
    return out


def _sentence_filter_ids_for_node(
    node: Node,
    corpus: Corpus,
    *,
    progress_cb: Callable | None,
    compiled_cache: Dict[TokenClause, CompiledClause],
    indexable_cache: Dict[TokenClause, Optional[Indexable]],
    positions_cache,
    sentence_ids_cache,
    shift_sentence_cache=None,
    subtree_cache=None,
    memo: Optional[Dict[Node, Optional[np.ndarray]]] = None,
) -> Optional[np.ndarray]:
    if memo is None:
        memo = {}
    cached = memo.get(node, _CACHE_MISSING)
    if cached is not _CACHE_MISSING:
        return cached
    if subtree_cache is not None:
        cached = subtree_cache.get(node)
        if cached is not _CACHE_MISSING:
            memo[node] = cached
            return cached

    total_sents = int(corpus.sent_starts.shape[0])
    max_ratio = get_float("CANDYCONC_CQLHPC_SENT_FILTER_MAX_RATIO", 0.95)

    def _finalize(value: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if value is None:
            memo[node] = None
            if subtree_cache is not None:
                subtree_cache.set(node, None)
            return None
        arr = value.astype(np.int32, copy=False)
        if total_sents > 0 and arr.size >= total_sents:
            memo[node] = None
            if subtree_cache is not None:
                subtree_cache.set(node, None)
            return None
        if total_sents > 0 and max_ratio > 0.0 and arr.size >= int(total_sents * max_ratio):
            memo[node] = None
            if subtree_cache is not None:
                subtree_cache.set(node, None)
            return None
        memo[node] = arr
        if subtree_cache is not None:
            subtree_cache.set(node, arr)
        return arr

    if isinstance(node, Tok):
        sent_ids = _sentence_ids_for_tok_clause(
            node,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
            indexable_cache=indexable_cache,
            positions_cache=positions_cache,
            sentence_ids_cache=sentence_ids_cache,
        )
        if sent_ids is None:
            return _finalize(None)
        return _finalize(sent_ids)

    if isinstance(node, Quant):
        if node.m <= 0:
            return _finalize(None)
        return _finalize(
            _sentence_filter_ids_for_node(
                node.node,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
                sentence_ids_cache=sentence_ids_cache,
                shift_sentence_cache=shift_sentence_cache,
                subtree_cache=subtree_cache,
                memo=memo,
            )
        )

    if isinstance(node, Seq):
        shifted = _sequence_shift_sentence_ids(
            node,
            corpus,
            progress_cb=progress_cb,
            compiled_cache=compiled_cache,
            indexable_cache=indexable_cache,
            positions_cache=positions_cache,
            sentence_ids_cache=sentence_ids_cache,
            shift_sentence_cache=shift_sentence_cache,
        )
        current: Optional[np.ndarray] = None
        start_idx = 0
        end_idx = len(node.parts)
        if shifted is not None:
            current = shifted
            # Die Shift-Prüfung garantiert die Endpunktklauseln bereits.
            if len(node.parts) >= 2:
                start_idx = 1
                end_idx = len(node.parts) - 1
        for part in node.parts[start_idx:end_idx]:
            part_ids = _sentence_filter_ids_for_node(
                part,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
                sentence_ids_cache=sentence_ids_cache,
                shift_sentence_cache=shift_sentence_cache,
                subtree_cache=subtree_cache,
                memo=memo,
            )
            if part_ids is None:
                continue
            current = part_ids if current is None else intersect_sorted_unique(current, part_ids)
            if current.size == 0:
                break
        return _finalize(current)

    if isinstance(node, Alt):
        parts: List[np.ndarray] = []
        for opt in node.options:
            opt_ids = _sentence_filter_ids_for_node(
                opt,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
                sentence_ids_cache=sentence_ids_cache,
                shift_sentence_cache=shift_sentence_cache,
                subtree_cache=subtree_cache,
                memo=memo,
            )
            if opt_ids is None:
                return _finalize(None)
            parts.append(opt_ids)
        if not parts:
            return _finalize(np.empty((0,), dtype=np.int32))
        if len(parts) == 1:
            return _finalize(parts[0])
        return _finalize(union_positions_many(parts))

    if isinstance(node, Within):
        return _finalize(
            _sentence_filter_ids_for_node(
                node.node,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
                sentence_ids_cache=sentence_ids_cache,
                shift_sentence_cache=shift_sentence_cache,
                subtree_cache=subtree_cache,
                memo=memo,
            )
        )

    if isinstance(node, Where):
        return _finalize(
            _sentence_filter_ids_for_node(
                node.node,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
                indexable_cache=indexable_cache,
                positions_cache=positions_cache,
                sentence_ids_cache=sentence_ids_cache,
                shift_sentence_cache=shift_sentence_cache,
                subtree_cache=subtree_cache,
                memo=memo,
            )
        )

    memo[node] = None
    return None


def _collect_token_clauses(node: Node, out: List[Tok]) -> None:
    if isinstance(node, Tok):
        out.append(node)
        return
    if isinstance(node, Seq):
        for p in node.parts:
            _collect_token_clauses(p, out)
        return
    if isinstance(node, Alt):
        for o in node.options:
            _collect_token_clauses(o, out)
        return
    if isinstance(node, Quant):
        _collect_token_clauses(node.node, out)
        return
    if isinstance(node, Within):
        _collect_token_clauses(node.node, out)
        return
    if isinstance(node, Where):
        _collect_token_clauses(node.node, out)
        return


def _collect_pos_ids(
    node: Node, corpus: Corpus, *, progress_cb: Callable | None = None
) -> List[int]:
    ids: List[int] = []
    compiled_cache: Dict[TokenClause, CompiledClause] = {}
    def visit(n: Node) -> None:
        if isinstance(n, Tok):
            cc = _compile_clause_cached(
                n.clause,
                corpus,
                progress_cb=progress_cb,
                compiled_cache=compiled_cache,
            )
            for attr, op, vals in cc.conds:
                if attr != "pos":
                    continue
                if op == '=' and vals.size:
                    ids.append(int(vals[0]))
                elif op == 'in':
                    for v in vals:
                        ids.append(int(v))
            return
        if isinstance(n, Seq):
            for p in n.parts:
                visit(p)
            return
        if isinstance(n, Alt):
            for o in n.options:
                visit(o)
            return
        if isinstance(n, Quant):
            visit(n.node)
            return
        if isinstance(n, Within):
            visit(n.node)
            return
        if isinstance(n, Where):
            visit(n.node)
            return
    visit(node)
    if not ids:
        return []
    return sorted(set(ids))


def _union_sentence_ids(idx, pos_ids: List[int]) -> np.ndarray:
    parts: List[np.ndarray] = []
    for pid in pos_ids:
        arr = idx.ids_for(int(pid))
        if arr.size:
            parts.append(arr.astype(np.int32, copy=False))
    if not parts:
        return np.empty((0,), dtype=np.int32)
    if len(parts) == 1:
        return parts[0].astype(np.int32, copy=False)
    return union_positions_many(parts)


def _choose_anchor(
    node: Node, corpus: Corpus, *, progress_cb: Callable | None = None
) -> Tuple[Optional[Tok], Optional[Indexable]]:
    toks: List[Tok] = []
    _collect_token_clauses(node, toks)
    best_tok: Optional[Tok] = None
    best: Optional[Indexable] = None
    indexable_cache: Dict[TokenClause, Optional[Indexable]] = {}
    for t in toks:
        idx = _best_indexable_cached(
            t.clause,
            corpus,
            progress_cb=progress_cb,
            indexable_cache=indexable_cache,
        )
        if idx is None:
            continue
        if best is None or idx.est_len < best.est_len:
            best_tok = t
            best = idx
    return best_tok, best


def _filter_positions(clause, positions: np.ndarray, corpus: Corpus) -> np.ndarray:
    if positions.size == 0:
        return positions
    pos = positions
    for attr, op, vals in clause.conds:
        tv = corpus.attr(attr)[pos]
        if op == '=':
            pos = pos[tv == int(vals[0])]
        elif op == '!=':
            pos = pos[tv != int(vals[0])]
        elif op == 'in':
            if vals.size == 0:
                return np.empty((0,), dtype=np.int32)
            isin_thresh = get_int("CANDYCONC_CQLHPC_IN_SET_ISIN_THRESHOLD", 128)
            if vals.size >= isin_thresh and tv.size >= isin_thresh:
                # NOTE: tv can contain duplicates; assume_unique=True risks false negatives.
                ok = np.isin(tv, vals)
                if not np.any(ok):
                    return np.empty((0,), dtype=np.int32)
                pos = pos[ok]
            else:
                idx = np.searchsorted(vals, tv)
                ok = idx < vals.size
                if not np.any(ok):
                    return np.empty((0,), dtype=np.int32)
                idx_ok = idx[ok]
                tv_ok = tv[ok]
                ok_vals = vals[idx_ok] == tv_ok
                if not np.any(ok_vals):
                    return np.empty((0,), dtype=np.int32)
                pos = pos[ok][ok_vals]
        else:
            return np.empty((0,), dtype=np.int32)
        if pos.size == 0:
            return pos
    return pos
