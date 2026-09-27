from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import heapq

import numpy as np

from candyconc.core.counting_kernels import (
    map_positions_to_doc_ids_i32_fast,
    position_to_doc_id_fast,
)
from candyconc.core.fast_index_backend import FastIndexBackend
from candyconc.core.token_store import TokenStore
from candyconc.core.fast_index_native import roaring_ops_available
from candyconc.core.index_format import MAX_I32 as _MAX_I32


def _as_i32_c_contig(values: np.ndarray) -> np.ndarray:
    if isinstance(values, np.ndarray) and values.dtype == np.int32 and values.flags.c_contiguous:
        return values
    return np.ascontiguousarray(values, dtype=np.int32)


def _u32_to_i32_safe(arr: np.ndarray) -> np.ndarray:
    """Reinterpret a uint32 postings/position array as int32, raising if any
    value exceeds ``MAX_I32`` (which would otherwise alias to a negative
    position and silently corrupt KWIC/collocation results).

    Postings positions are monotonically increasing, so checking the last
    element is sufficient (O(1) — no per-query full scan). For any corpus within
    the safe range the result is bit-identical to the previous
    ``.astype(np.int32, copy=False)`` cast.
    """
    if arr.size and int(arr[-1]) > _MAX_I32:
        raise RuntimeError(
            f"Token-Position {int(arr[-1]):,} überschreitet die int32-Grenze "
            f"({_MAX_I32:,}). Der Index überschreitet die sichere Korpusgröße."
        )
    # When all values fit in int31, .astype(int32) and .view(int32) are identical.
    return arr.astype(np.int32, copy=False)


@dataclass
class UnitIndex:
    offsets: np.ndarray
    ids: np.ndarray
    _counts: Optional[np.ndarray] = None

    def ids_for(self, type_id: int) -> np.ndarray:
        if type_id <= 0 or type_id + 1 >= self.offsets.shape[0]:
            return np.zeros(0, dtype=np.uint32)
        start = int(self.offsets[type_id])
        end = int(self.offsets[type_id + 1])
        if end <= start:
            return np.zeros(0, dtype=np.uint32)
        return self.ids[start:end]

    def count_for(self, type_id: int) -> int:
        if type_id <= 0 or type_id + 1 >= self.offsets.shape[0]:
            return 0
        start = int(self.offsets[type_id])
        end = int(self.offsets[type_id + 1])
        if end <= start:
            return 0
        return end - start

    def counts(self) -> np.ndarray:
        if self._counts is None:
            offs = self.offsets.astype(np.int64, copy=False)
            if offs.size <= 1:
                self._counts = np.zeros((0,), dtype=np.int64)
            else:
                self._counts = (offs[1:] - offs[:-1]).astype(np.int64, copy=False)
        return self._counts

    def count_in_mask(self, type_id: int, mask: np.ndarray) -> int:
        ids = self.ids_for(type_id)
        if ids.size == 0:
            return 0
        if mask.dtype != np.bool_:
            mask = mask.astype(np.bool_, copy=False)
        return int(mask[ids].sum())


class FastAttrAccessor:
    def __init__(self, token_store: TokenStore, attr: str):
        self._token_store = token_store
        self._attr = attr
        self._stream = None
        self._array = None
        if attr == "word":
            self._stream = token_store.word_stream
        elif attr == "lemma":
            self._stream = token_store.lemma_stream
        elif attr == "pos":
            self._array = token_store.pos_ids
        elif attr == "morph":
            self._array = token_store.morph_ids
        elif attr == "ent":
            self._array = token_store.ent_ids
        elif attr == "rel":
            self._array = token_store.rel_ids

    def _get_one(self, pos: int) -> int:
        if pos < 0 or pos >= self._token_store.token_count:
            return 0
        if self._stream is not None:
            return int(self._stream.get(pos))
        if self._array is not None:
            return int(self._array[pos])
        return 0

    def _get_many(self, positions: np.ndarray) -> np.ndarray:
        if positions.size == 0:
            return np.zeros(0, dtype=np.int32)
        if self._array is not None:
            return self._array[positions.astype(np.int64, copy=False)].astype(np.int32, copy=False)
        if self._stream is None:
            return np.zeros(positions.shape[0], dtype=np.int32)
        out = np.empty(positions.shape[0], dtype=np.int32)
        for i, p in enumerate(positions):
            out[i] = int(self._stream.get(int(p)))
        return out

    def get_ranges_packed_i32(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts_i32 = np.ascontiguousarray(starts, dtype=np.int32)
        ends_i32 = np.ascontiguousarray(ends, dtype=np.int32)
        if starts_i32.shape != ends_i32.shape:
            raise ValueError("starts und ends müssen gleich geformt sein")
        if starts_i32.size == 0:
            return np.zeros(0, dtype=np.int32)
        if self._stream is not None:
            return self._stream.get_ranges_packed_i32(starts_i32, ends_i32)
        if self._array is None:
            return np.zeros(0, dtype=np.int32)
        total = 0
        for start, end in zip(starts_i32.tolist(), ends_i32.tolist()):
            if start < 0:
                start = 0
            if end <= start:
                continue
            if end > self._array.shape[0]:
                end = self._array.shape[0]
            if end > start:
                total += end - start
        if total <= 0:
            return np.zeros(0, dtype=np.int32)
        out = np.empty(total, dtype=np.int32)
        cursor = 0
        for start, end in zip(starts_i32.tolist(), ends_i32.tolist()):
            if start < 0:
                start = 0
            if end <= start:
                continue
            if end > self._array.shape[0]:
                end = self._array.shape[0]
            if end <= start:
                continue
            take = end - start
            out[cursor : cursor + take] = self._array[start:end].astype(np.int32, copy=False)
            cursor += take
        return out

    def get_ranges_packed_sorted_i32(self, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
        starts_i32 = _as_i32_c_contig(starts)
        ends_i32 = _as_i32_c_contig(ends)
        if starts_i32.shape != ends_i32.shape:
            raise ValueError("starts und ends müssen gleich geformt sein")
        if starts_i32.size == 0:
            return np.zeros(0, dtype=np.int32)
        if self._stream is not None:
            return self._stream.get_ranges_packed_sorted_i32(starts_i32, ends_i32)
        if self._array is None:
            return np.zeros(0, dtype=np.int32)
        return self.get_ranges_packed_i32(starts_i32, ends_i32)

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
        if self._stream is not None:
            fast_getter = getattr(self._stream, "get_ranges_packed_sorted_known_i32_fast", None)
            if callable(fast_getter):
                return fast_getter(starts_i32, ends_i32, int(total_len))
            return self._stream.get_ranges_packed_sorted_known_i32(starts_i32, ends_i32, int(total_len))
        if self._array is None:
            return np.zeros(0, dtype=np.int32)
        return self.get_ranges_packed_i32(starts_i32, ends_i32)

    def __getitem__(self, pos):
        if isinstance(pos, np.ndarray):
            return self._get_many(pos)
        if isinstance(pos, slice):
            start = 0 if pos.start is None else int(pos.start)
            end = self._token_store.token_count if pos.stop is None else int(pos.stop)
            if start < 0:
                start = 0
            if end < start:
                return np.zeros(0, dtype=np.int32)
            if self._attr == "word":
                return self._token_store.get_word_ids_range_i32(start, end)
            if self._attr == "lemma":
                return self._token_store.get_lemma_ids_range_i32(start, end)
            if self._array is not None:
                return self._array[start:end].astype(np.int32, copy=False)
            return np.zeros(0, dtype=np.int32)
        return self._get_one(int(pos))


class FastPostingsIndex:
    def __init__(self, token_store: TokenStore, attr: str, lexicon):
        self._token_store = token_store
        self._attr = attr
        self._lexicon = lexicon

    def list(self, type_id: int) -> np.ndarray:
        if type_id <= 0:
            return np.zeros(0, dtype=np.int32)
        if self._attr == "word":
            return _u32_to_i32_safe(self._token_store.get_positions_for_word_id(type_id))
        if self._attr == "lemma":
            return _u32_to_i32_safe(self._token_store.get_positions_for_lemma_id(type_id))
        if self._attr == "pos":
            return _u32_to_i32_safe(self._token_store.get_positions_for_pos_id(type_id))
        if self._attr == "morph":
            return _u32_to_i32_safe(self._token_store.get_positions_for_morph_id(type_id))
        if self._attr == "ent":
            return _u32_to_i32_safe(self._token_store.get_positions_for_ent_id(type_id))
        if self._attr == "rel":
            return _u32_to_i32_safe(self._token_store.get_positions_for_rel_id(type_id))
        return np.zeros(0, dtype=np.int32)

    def length(self, type_id: int) -> int:
        if self._lexicon is None:
            return 0
        return int(self._lexicon.get_freq(int(type_id)))

    def supports_contains(self) -> bool:
        return self._attr in {"word", "lemma", "pos"} and roaring_ops_available()

    def contains(self, type_id: int, pos: int) -> bool:
        if type_id <= 0:
            return False
        if not self.supports_contains():
            raise RuntimeError("contains nicht verfügbar für dieses Attribut")
        if self._attr == "word":
            return self._token_store.contains_word_position(type_id, pos)
        if self._attr == "lemma":
            return self._token_store.contains_lemma_position(type_id, pos)
        if self._attr == "pos":
            return self._token_store.contains_pos_position(type_id, pos)
        return False

    def advance_to(self, type_id: int, pos: int) -> int:
        if type_id <= 0:
            return -1
        if self._attr == "word":
            return self._token_store.advance_word_position(type_id, pos)
        if self._attr == "lemma":
            return self._token_store.advance_lemma_position(type_id, pos)
        if self._attr == "pos":
            return self._token_store.advance_pos_position(type_id, pos)
        return -1


class FastLexiconAdapter:
    def __init__(self, lexicon, prefix_len: int = 3, top_k: int = 64, top_global: int = 2000):
        self._lexicon = lexicon
        self.prefix_len = int(prefix_len)
        self.top_k = int(top_k)
        self.top_global = int(top_global)
        self._prefix_top: Optional[Dict[str, np.ndarray]] = None
        self._top_global_ids: Optional[np.ndarray] = None
        if hasattr(lexicon, "prefix_top") and getattr(lexicon, "prefix_top") is not None:
            self._prefix_top = lexicon.prefix_top
            self._top_global_ids = lexicon.top_global_ids
            if getattr(lexicon, "prefix_len", 0):
                self.prefix_len = int(lexicon.prefix_len)
            if getattr(lexicon, "top_k", 0):
                self.top_k = int(lexicon.top_k)
            if getattr(lexicon, "top_global", 0):
                self.top_global = int(lexicon.top_global)

    @property
    def offsets(self):
        return self._lexicon.offsets

    @property
    def strings_view(self):
        return self._lexicon.strings_view

    @property
    def vocab_size(self) -> int:
        return int(getattr(self._lexicon, "vocab_size", 0))

    def get_id(self, value: str) -> int:
        return int(self._lexicon.get_id(value))

    def get_string(self, id_: int) -> str:
        return str(self._lexicon.get_string(id_))

    def get_freq(self, id_: int) -> int:
        return int(self._lexicon.get_freq(id_))

    def _build_prefix_top(self) -> None:
        buckets: Dict[str, List[int]] = {}
        top_heap: List[tuple[int, int]] = []
        vocab = self.vocab_size
        for tid in range(1, vocab + 1):
            s = self._lexicon.get_string(tid)
            if not s:
                continue
            key = s[: self.prefix_len] if len(s) >= self.prefix_len else s
            buckets.setdefault(key, []).append(tid)
            if self.top_global > 0:
                f = int(self._lexicon.get_freq(tid))
                if len(top_heap) < self.top_global:
                    heapq.heappush(top_heap, (f, tid))
                elif f > top_heap[0][0]:
                    heapq.heapreplace(top_heap, (f, tid))
        if top_heap:
            top_heap.sort(reverse=True)
            self._top_global_ids = np.asarray([tid for _f, tid in top_heap], dtype=np.int32)
        prefix_top: Dict[str, np.ndarray] = {}
        for key, ids in buckets.items():
            if not ids:
                continue
            if len(ids) > self.top_k:
                ids = heapq.nlargest(self.top_k, ids, key=self._lexicon.get_freq)
            ids_sorted = sorted(ids, key=self._lexicon.get_freq, reverse=True)
            prefix_top[key] = np.asarray(ids_sorted, dtype=np.int32)
        self._prefix_top = prefix_top

    def suggest(self, prefix: str, limit: int = 50):
        if self._prefix_top is None:
            raise RuntimeError("prefix_top fehlt. Bitte Index mit Prefix-Top Listen neu bauen.")
        prefix = prefix or ""
        out: List[tuple[str, int]] = []
        if prefix == "":
            if self._top_global_ids is None:
                return out
            for tid in self._top_global_ids[:limit]:
                out.append((self._lexicon.get_string(int(tid)), int(tid)))
            return out
        key = prefix[: self.prefix_len] if len(prefix) >= self.prefix_len else prefix
        cand = self._prefix_top.get(key) if self._prefix_top else None
        if cand is None:
            return out
        for tid in cand:
            s = self._lexicon.get_string(int(tid))
            if s.startswith(prefix):
                out.append((s, int(tid)))
                if len(out) >= limit:
                    break
        return out


@dataclass
class FastCorpus:
    backend: FastIndexBackend
    attrs: Dict[str, FastAttrAccessor]
    lex: Dict[str, object]
    postings: Dict[str, FastPostingsIndex]
    doc_starts: np.ndarray
    doc_ends: np.ndarray
    sent_starts: np.ndarray
    sent_ends: np.ndarray
    doc_meta: Optional[List[Dict[str, object]]] = None
    docsets: Optional[Dict[str, UnitIndex]] = None
    pos_sentence: Optional[UnitIndex] = None
    _token_to_sent_map: Optional["IndexMap"] = None
    _token_to_doc_map: Optional["IndexMap"] = None
    _sent_to_doc: Optional[np.ndarray] = None

    @property
    def n_tokens(self) -> int:
        return int(self.backend.token_store.token_count)

    @classmethod
    def from_backend(cls, backend: FastIndexBackend) -> "FastCorpus":
        token_store = backend.token_store
        total = int(token_store.token_count)
        if total > _MAX_I32:
            raise RuntimeError(
                f"Corpus hat {total:,} Tokens — überschreitet die int32-Grenze "
                f"({_MAX_I32:,}). Dieser Index kann nicht sicher abgefragt werden."
            )

        doc_starts, doc_ends = _bounds_from_starts(
            backend.boundaries.document._positions if backend.boundaries and backend.boundaries.document else np.zeros(0, dtype=np.uint32),
            total,
            "document",
        )
        sent_starts, sent_ends = _bounds_from_starts(
            backend.boundaries.sentence._positions if backend.boundaries and backend.boundaries.sentence else np.zeros(0, dtype=np.uint32),
            total,
            "sentence",
        )

        lex_raw = {
            "word": backend.lexicons.word,
            "lemma": backend.lexicons.lemma,
            "pos": backend.lexicons.pos,
            "morph": backend.lexicons.morph,
            "ent": backend.lexicons.ent,
            "rel": backend.lexicons.rel,
        }
        lex: Dict[str, FastLexiconAdapter] = {}
        for k, v in lex_raw.items():
            if v is not None:
                lex[k] = FastLexiconAdapter(v)
        attrs = {k: FastAttrAccessor(token_store, k) for k in lex.keys()}
        postings = {k: FastPostingsIndex(token_store, k, lex[k]) for k in lex.keys()}

        doc_meta = None
        if backend.doc_metadata and getattr(backend, "meta_index", None) is None:
            meta: List[Dict[str, object]] = []
            count = int(doc_starts.shape[0])
            for i in range(count):
                m = backend.doc_metadata.get(i)
                if m is None:
                    m = backend.doc_metadata.get(str(i), {})
                meta.append(m if isinstance(m, dict) else {})
            doc_meta = meta

        docsets: Dict[str, UnitIndex] = {}
        if hasattr(token_store, "word_docset_offsets") and token_store.word_docset_offsets is not None:
            docsets["word"] = UnitIndex(token_store.word_docset_offsets, token_store.word_docset_ids)
        if hasattr(token_store, "lemma_docset_offsets") and token_store.lemma_docset_offsets is not None:
            docsets["lemma"] = UnitIndex(token_store.lemma_docset_offsets, token_store.lemma_docset_ids)
        if hasattr(token_store, "pos_docset_offsets") and token_store.pos_docset_offsets is not None:
            docsets["pos"] = UnitIndex(token_store.pos_docset_offsets, token_store.pos_docset_ids)

        pos_sentence = None
        if hasattr(token_store, "pos_sentence_offsets") and token_store.pos_sentence_offsets is not None:
            pos_sentence = UnitIndex(token_store.pos_sentence_offsets, token_store.pos_sentence_ids)

        corpus = cls(
            backend=backend,
            attrs=attrs,
            lex=lex,
            postings=postings,
            doc_starts=doc_starts,
            doc_ends=doc_ends,
            sent_starts=sent_starts,
            sent_ends=sent_ends,
            doc_meta=doc_meta,
            docsets=docsets if docsets else None,
            pos_sentence=pos_sentence,
        )
        if sent_starts.size and doc_starts.size:
            corpus._sent_to_doc = map_positions_to_doc_ids_i32_fast(sent_starts, doc_starts)
        return corpus

    def has_attr(self, name: str) -> bool:
        return name in self.attrs

    def attr(self, name: str) -> FastAttrAccessor:
        return self.attrs[name]

    def lexicon(self, name: str):
        return self.lex[name]

    def postings_index(self, attr: str) -> FastPostingsIndex:
        return self.postings[attr]

    def docset_index(self, attr: str) -> Optional[UnitIndex]:
        if self.docsets is None:
            return None
        return self.docsets.get(attr)

    def pos_sentence_index(self) -> Optional[UnitIndex]:
        return self.pos_sentence

    def dense_bitset(self, attr: str, type_id: int) -> Optional[np.ndarray]:
        if hasattr(self.backend, "token_store") and hasattr(self.backend.token_store, "dense_bitset"):
            return self.backend.token_store.dense_bitset(attr, type_id)
        return None

    def dense_bitset_available(self, attr: str, type_id: int) -> bool:
        if hasattr(self.backend, "token_store") and hasattr(self.backend.token_store, "dense_bitset_available"):
            return bool(self.backend.token_store.dense_bitset_available(attr, type_id))
        return False

    def sentence_span(self, sid: int) -> tuple[int, int]:
        return int(self.sent_starts[sid]), int(self.sent_ends[sid])

    def doc_span(self, did: int) -> tuple[int, int]:
        return int(self.doc_starts[did]), int(self.doc_ends[did])

    def doc_id_of_position(self, pos: int) -> int:
        i = position_to_doc_id_fast(int(pos), self.doc_starts)
        if i < 0:
            return 0
        if i >= int(self.doc_starts.shape[0]):
            return int(self.doc_starts.shape[0]) - 1
        return i

    def token_to_sent(self):
        if self._token_to_sent_map is None:
            self._token_to_sent_map = IndexMap(self.sent_starts)
        return self._token_to_sent_map

    def token_to_doc(self):
        if self._token_to_doc_map is None:
            self._token_to_doc_map = IndexMap(self.doc_starts)
        return self._token_to_doc_map

    def sent_to_doc(self) -> np.ndarray:
        if self._sent_to_doc is None:
            self._sent_to_doc = map_positions_to_doc_ids_i32_fast(self.sent_starts, self.doc_starts)
        return self._sent_to_doc


class IndexMap:
    def __init__(self, starts: np.ndarray):
        self._starts_u32 = starts.astype(np.uint32, copy=False)

    def __getitem__(self, pos):
        if isinstance(pos, slice):
            start = 0 if pos.start is None else int(pos.start)
            stop = int(pos.stop) if pos.stop is not None else None
            step = 1 if pos.step is None else int(pos.step)
            if stop is None:
                raise ValueError("IndexMap slice requires stop")
            arr = np.arange(start, stop, step, dtype=np.uint32)
        else:
            if isinstance(pos, np.ndarray):
                if pos.dtype == np.uint32 and pos.flags.c_contiguous:
                    arr = pos
                elif pos.dtype == np.int32 and pos.flags.c_contiguous:
                    arr = pos.view(np.uint32)
                else:
                    arr = np.asarray(pos, dtype=np.uint32)
            else:
                arr = np.asarray(pos, dtype=np.uint32)
        if arr.ndim == 0:
            return np.int32(position_to_doc_id_fast(int(arr), self._starts_u32))
        return map_positions_to_doc_ids_i32_fast(arr, self._starts_u32)

    @property
    def n_tokens(self) -> int:
        return int(self.backend.token_store.token_count)


def _bounds_from_starts(starts: np.ndarray, total: int, label: str) -> tuple[np.ndarray, np.ndarray]:
    # Guard before any int32 narrowing: with total <= MAX_I32 the np.int32(total)
    # below can never wrap (or raise OverflowError on NumPy 2.x). Downstream
    # consumers (IndexMap, *_i32_fast kernels) re-cast to uint32 internally, so
    # the int32 dtype here is preserved exactly as before for any safe corpus.
    if total > _MAX_I32:
        raise RuntimeError(
            f"{label} bounds: token_count {total:,} überschreitet die sichere "
            f"int32-Grenze ({_MAX_I32:,}). Der Index ist zu gross."
        )
    if starts.size == 0:
        return (
            np.array([0], dtype=np.int32),
            np.array([total], dtype=np.int32),
        )
    starts_i32 = starts.astype(np.int32, copy=False)
    if int(starts_i32[0]) != 0:
        raise RuntimeError(f"{label} bounds fehlen Start 0. Bitte Index neu bauen.")
    ends = np.empty_like(starts_i32)
    ends[:-1] = starts_i32[1:]
    ends[-1] = np.int32(total)
    return starts_i32, ends
