from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple, Dict, List
import re
import os
import threading
import numpy as np
import sre_parse
from collections import OrderedDict
import json

from .token_store import TokenStore
from candyconc.i18n import lt
from .lexicon import Lexicon, LexiconSet
from .boundaries import BoundarySet
from .fast_index_native import (
    kwic_rows_svb,
    kwic_rows_svb_compact_buffers,
    kwic_compact_buffer_rows,
    dependency_heads,
    lexicon_match_contains,
    lexicon_match_contains_ids,
    lexicon_match_prefix,
    lexicon_match_prefix_ids,
    lexicon_match_regex,
    lexicon_match_regex_ids,
    lexicon_match_suffix,
    lexicon_match_suffix_ids,
    bitset_positions_limit,
    roaring_postings_to_bitset,
    union_roar_positions_limited,
    union_sorted,
    intersect_shifted,
    union_roar_positions,
)
from .meta_index import MetaIndex
from .doc_metadata_store import DocMetadataMMap
from . import index_format

_MISSING_LEXICON = lt(
    "Lexikon fehlt für {attr}. Bitte Index neu bauen.",
    "The lexicon for {attr} is missing. Rebuild the index.",
)

try:
    from candyconc.core import _fast_index as _fast_index_mod  # type: ignore
    _intersect_sorted_fast = getattr(_fast_index_mod, "intersect_sorted", None)
    _dependency_arcs_fast = getattr(_fast_index_mod, "dependency_arcs_window", None)
except Exception:  # pragma: no cover - missing extension
    _intersect_sorted_fast = None
    _dependency_arcs_fast = None


_KWIC_LIST_CACHE_MAX_SIZE = max(
    0,
    int(os.getenv("CANDYCONC_KWIC_LIST_CACHE_MAX_SIZE", "2000000")),
)
_LIMITED_UNION_BITSET_MIN_IDS = max(
    2,
    int(os.getenv("CANDYCONC_LIMITED_UNION_BITSET_MIN_IDS", "256")),
)

DependencyAttrFilter = Tuple[str, str] | str


def _wildcard_to_regex(pattern: str) -> str:
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return f"^{regex}$"


def _merge_sorted_positions(arrays: Sequence[np.ndarray]) -> np.ndarray:
    """Merge multiple sorted uint32 arrays without full concat+sort."""
    total = int(sum(int(a.size) for a in arrays))
    if total == 0:
        return np.array([], dtype=np.uint32)
    out = np.empty(total, dtype=np.uint32)
    import heapq

    heap: list[tuple[int, int, int]] = []
    for idx, arr in enumerate(arrays):
        if arr.size:
            heap.append((int(arr[0]), idx, 0))
    heapq.heapify(heap)
    out_idx = 0
    while heap:
        val, arr_idx, pos_idx = heapq.heappop(heap)
        out[out_idx] = np.uint32(val)
        out_idx += 1
        next_idx = pos_idx + 1
        arr = arrays[arr_idx]
        if next_idx < arr.size:
            heapq.heappush(heap, (int(arr[next_idx]), arr_idx, next_idx))
    if out_idx != total:
        return out[:out_idx]
    return out


def _intersect_positions(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if a.size == 0 or b.size == 0:
        return np.array([], dtype=np.uint32)
    a_u32 = a.astype(np.uint32, copy=False)
    b_u32 = b.astype(np.uint32, copy=False)
    if _intersect_sorted_fast is not None:
        return _intersect_sorted_fast(a_u32, b_u32).astype(np.uint32, copy=False)
    return np.intersect1d(a_u32, b_u32, assume_unique=True).astype(np.uint32, copy=False)


def _contains_position(sorted_positions: np.ndarray | None, pos: int) -> bool:
    if sorted_positions is None:
        return True
    idx = int(np.searchsorted(sorted_positions, np.uint32(pos)))
    return idx < int(sorted_positions.size) and int(sorted_positions[idx]) == int(pos)


class _LRUCache:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._data: OrderedDict[Tuple[str, str], np.ndarray] = OrderedDict()
        # The OrderedDict is mutated on EVERY access (get re-inserts for LRU
        # recency, set evicts) — not just on first use — so concurrent callers
        # can corrupt it / raise. Guard all mutations with a tiny critical
        # section. The lock is private to this cache (never held across other
        # locks) so it cannot participate in a lock-ordering deadlock.
        self._lock = threading.Lock()

    def get(self, key: Tuple[str, str]) -> Optional[np.ndarray]:
        if self.maxsize <= 0:
            return None
        with self._lock:
            try:
                val = self._data.pop(key)
            except KeyError:
                return None
            self._data[key] = val
            return val

    def set(self, key: Tuple[str, str], value: np.ndarray) -> None:
        if self.maxsize <= 0:
            return
        with self._lock:
            if key in self._data:
                self._data.pop(key)
            self._data[key] = value
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)


class _DocPathLookup:
    """Lazy, cached document label lookup to avoid eager metadata decoding."""

    def __init__(self, doc_count: int, doc_metadata):
        self._doc_count = max(0, int(doc_count))
        self._doc_metadata = doc_metadata
        self._cache: dict[int, str] = {}

    def __len__(self) -> int:
        return self._doc_count

    def __getitem__(self, idx: int) -> str:
        doc_idx = int(idx)
        if doc_idx < 0 or doc_idx >= self._doc_count:
            raise IndexError(doc_idx)
        cached = self._cache.get(doc_idx)
        if cached is not None:
            return cached
        meta = self._doc_metadata.get(doc_idx, {}) if self._doc_metadata else {}
        if isinstance(meta, dict):
            value = str(meta.get("path") or meta.get("doc_id") or meta.get("name") or "")
        else:
            value = ""
        if len(self._cache) < 8192:
            self._cache[doc_idx] = value
        return value


def _load_array(path: Path, dtype: np.dtype) -> np.ndarray:
    # Count-prefixed array format is defined once in core.index_format.
    return index_format.read_count_prefixed_array(path, dtype, label="Index")


class _LexiconPostingIndex:
    def __init__(self, base_path: Path):
        self.lex = Lexicon.load(base_path)
        self.ptr = _load_array(base_path.with_suffix(".postings.ptr.bin"), np.uint64)
        self.ids = _load_array(base_path.with_suffix(".postings.bin"), np.uint32)
        expected = index_format.postings_ptr_len(self.lex.vocab_size)
        if self.ptr.shape[0] < expected:
            raise RuntimeError(
                f"Posting Pointer Contract ungültig: {base_path} hat "
                f"{self.ptr.shape[0]} Pointer für vocab_size={self.lex.vocab_size}; "
                "bitte Fast Index neu bauen."
            )

    def ids_for(self, key: str) -> np.ndarray:
        tid = int(self.lex.get_id(key))
        if tid <= 0 or tid + 1 >= self.ptr.shape[0]:
            return np.array([], dtype=np.uint32)
        start = int(self.ptr[tid])
        end = int(self.ptr[tid + 1])
        if end <= start:
            return np.array([], dtype=np.uint32)
        return self.ids[start:end]


def _regex_width(pattern: str) -> Tuple[int, Optional[int]]:
    try:
        parsed = sre_parse.parse(pattern)
        min_len, max_len = parsed.getwidth()
        if max_len == sre_parse.MAXREPEAT:
            return int(min_len), None
        return int(min_len), int(max_len)
    except Exception:
        return 0, None


def _regex_literal_prefix(pattern: str) -> str:
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return ""
    prefix: List[str] = []
    anchored = False
    for op, val in parsed:
        if op == sre_parse.AT and val in (sre_parse.AT_BEGINNING, sre_parse.AT_BEGINNING_STRING):
            anchored = True
            continue
        if op == sre_parse.LITERAL:
            prefix.append(chr(val))
            continue
        break
    if anchored and prefix:
        return "".join(prefix)
    return ""


def _regex_mandatory_literal_runs(pattern: str) -> List[str]:
    """Return literal runs that must appear in any match (conservative)."""
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return []
    runs: List[str] = []

    def walk(sub) -> None:
        cur: List[str] = []

        def flush() -> None:
            if cur:
                runs.append("".join(cur))
                cur.clear()

        for op, val in sub:
            if op == sre_parse.LITERAL:
                cur.append(chr(val))
                continue
            if op == sre_parse.SUBPATTERN:
                flush()
                try:
                    walk(val[-1])
                except Exception:
                    pass
                continue
            if op == sre_parse.MAX_REPEAT:
                try:
                    min_rep, _max_rep, inner = val
                except Exception:
                    flush()
                    continue
                if int(min_rep) <= 0:
                    flush()
                    continue
                flush()
                walk(inner)
                continue
            if op == sre_parse.BRANCH:
                flush()
                continue
            flush()
        flush()

    walk(parsed)
    return [r for r in runs if r]


def _regex_uses_unsupported(pattern: str) -> bool:
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return True

    def walk(sub) -> bool:
        for op, val in sub:
            if op in (sre_parse.ASSERT, sre_parse.ASSERT_NOT, sre_parse.GROUPREF, sre_parse.GROUPREF_EXISTS):
                return True
            if op == sre_parse.SUBPATTERN:
                try:
                    subp = val[-1]
                except Exception:
                    continue
                if walk(subp):
                    return True
                continue
            if op == sre_parse.BRANCH:
                try:
                    _none, branches = val
                except Exception:
                    continue
                for b in branches:
                    if walk(b):
                        return True
                continue
            if op == sre_parse.MAX_REPEAT:
                try:
                    subp = val[-1]
                except Exception:
                    continue
                if walk(subp):
                    return True
        return False

    return walk(parsed)


def _regex_redos_risk(pattern: str) -> bool:
    """True if ``pattern`` has a nested unbounded quantifier ((X+)+, (X*)*, (.*)+ …)
    — the classic catastrophic-backtracking shape that hangs Python's ``re`` on a
    non-matching long string. Such patterns are only safe under a backtracking-
    immune engine (re2)."""
    try:
        parsed = sre_parse.parse(pattern)
    except Exception:
        return False  # uncompilable; re.compile rejects it cleanly downstream
    unb = sre_parse.MAXREPEAT

    def _contains_unbounded(sub) -> bool:
        for op, val in sub:
            if op == sre_parse.MAX_REPEAT:
                if val[1] == unb or _contains_unbounded(val[-1]):
                    return True
            elif op == sre_parse.SUBPATTERN:
                if _contains_unbounded(val[-1]):
                    return True
            elif op == sre_parse.BRANCH:
                if any(_contains_unbounded(b) for b in val[1]):
                    return True
        return False

    def _walk(sub) -> bool:
        for op, val in sub:
            if op == sre_parse.MAX_REPEAT:
                if val[1] == unb and _contains_unbounded(val[-1]):
                    return True
                if _walk(val[-1]):
                    return True
            elif op == sre_parse.SUBPATTERN:
                if _walk(val[-1]):
                    return True
            elif op == sre_parse.BRANCH:
                if any(_walk(b) for b in val[1]):
                    return True
        return False

    return _walk(parsed)


def _re2_available_for(pattern: str) -> bool:
    """Whether a backtracking-immune re2 engine would actually handle ``pattern``."""
    backend = os.environ.get("CANDYCONC_REGEX_BACKEND", "auto").lower()
    if backend == "re":
        return False
    if _regex_uses_unsupported(pattern):
        return False  # re2 declines lookahead/backref -> would fall back to re
    try:
        import re2 as _re2  # type: ignore  # noqa: F401
    except Exception:
        return False
    try:
        import re2 as _re2b  # type: ignore
        _re2b.compile(pattern)
    except Exception:
        return False
    return True


def _compile_regex(pattern: str) -> tuple[object, bool, str]:
    # ReDoS guard: reject catastrophic-backtracking patterns unless a
    # backtracking-immune engine (re2) will actually run them. The post-scan
    # type/freq caps run too late — the cost is incurred during the lexicon scan.
    if _regex_redos_risk(pattern) and not _re2_available_for(pattern):
        raise ValueError(
            "Regex mit verschachtelten unbeschraenkten Quantoren (z.B. (a+)+) ist "
            "nicht erlaubt (Gefahr katastrophalen Backtrackings). Bitte das Muster "
            "vereinfachen."
        )
    return _compile_regex_impl(pattern)


def _compile_regex_impl(pattern: str) -> tuple[object, bool, str]:
    pat_re = re.compile(pattern)
    ignorecase = bool(pat_re.flags & re.IGNORECASE)
    backend = os.environ.get("CANDYCONC_REGEX_BACKEND", "auto").lower()
    if backend not in {"auto", "re2", "re"}:
        backend = "auto"
    if backend in {"auto", "re2"} and not _regex_uses_unsupported(pattern):
        try:
            import re2 as _re2  # type: ignore
        except Exception:
            return pat_re, ignorecase, "re"
        try:
            compiled = _re2.compile(pattern)
        except Exception:
            return pat_re, ignorecase, "re"
        if hasattr(compiled, "fullmatch"):
            return compiled, ignorecase, "re2"

        def _fullmatch(text: str, _c=compiled):
            m = _c.match(text)
            if m and m.end() == len(text):
                return m
            return None

        class _Wrapper:
            __slots__ = ("fullmatch",)

            def __init__(self, fn):
                self.fullmatch = fn

        return _Wrapper(_fullmatch), ignorecase, "re2"
    return pat_re, ignorecase, "re"


def _regex_longest_literal(pattern: str) -> str:
    runs = _regex_mandatory_literal_runs(pattern)
    if not runs:
        return ""
    return max(runs, key=len)


def _regex_is_literal(pattern: str) -> bool:
    return re.search(r"[.^$*+?{}\[\]|()\\]", pattern) is None


_SIMPLE_REGEX_LITERAL = re.compile(r"^[^.^$*+?{}\[\]|()\\]+$")


def _simple_regex_literal(pattern: str) -> tuple[str, str] | None:
    anchored_start = pattern.startswith("^")
    anchored_end = pattern.endswith("$")
    core = pattern
    if anchored_start and len(core) > 1:
        core = core[1:]
    if anchored_end and core:
        core = core[:-1]
    if core.endswith(".*") and not core.startswith(".*") and len(core) > 2:
        literal = core[:-2]
        if _SIMPLE_REGEX_LITERAL.fullmatch(literal):
            return ("prefix", literal)
    if core.startswith(".*") and not core.endswith(".*") and len(core) > 2:
        literal = core[2:]
        if _SIMPLE_REGEX_LITERAL.fullmatch(literal):
            return ("suffix", literal)
    if core.startswith(".*") and core.endswith(".*") and len(core) > 4:
        literal = core[2:-2]
        if _SIMPLE_REGEX_LITERAL.fullmatch(literal):
            return ("contains", literal)
    if anchored_start and anchored_end and _SIMPLE_REGEX_LITERAL.fullmatch(core):
        return ("literal", core)
    return None


def _intersect_sorted(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if _intersect_sorted_fast is not None:
        a_arr = np.asarray(a, dtype=np.uint32)
        b_arr = np.asarray(b, dtype=np.uint32)
        if not a_arr.flags.writeable:
            a_arr = a_arr.copy()
        if not b_arr.flags.writeable:
            b_arr = b_arr.copy()
        return _intersect_sorted_fast(a_arr, b_arr)
    return np.intersect1d(a, b, assume_unique=True)


class FastIndexBackend:
    _MAX_REGEX_POSITIONS = int(os.environ.get("CANDYCONC_MAX_REGEX_POSITIONS", "5000000"))
    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        if not self.index_path.exists():
            raise RuntimeError(f"Fast index fehlt: {self.index_path}")
        # Guards per-instance lazy-init of mutable caches (currently the
        # KWIC string cache, which can be re-built on first hot-path access).
        # Re-entrant because guarded methods may call other guarded methods.
        self._cache_lock = threading.RLock()
        self.token_store = TokenStore(self.index_path)
        self.token_store.load()
        # Scaling guard (R6): refuse to open a corpus whose token_count exceeds
        # the safe int32 query ceiling rather than returning silently-wrong KWIC.
        from candyconc.core import index_format as _ifmt
        _ifmt.enforce_scaling_limits(
            token_count=int(self.token_store.token_count),
            context=str(self.index_path),
        )
        self.lexicons = LexiconSet(self.index_path)
        self.lexicons.load()
        self.boundaries = BoundarySet(self.index_path)
        self.boundaries.load()
        self.doc_metadata = self._load_doc_metadata()
        self._validate_doc_metadata()
        self.doc_paths = self._build_doc_paths()
        word_lex = self.lexicons.word
        if word_lex is not None:
            lex_size = int(word_lex.offsets.shape[0]) if word_lex.offsets.size else 0
            if 0 < lex_size <= _KWIC_LIST_CACHE_MAX_SIZE:
                self._kwic_string_cache = [None] * lex_size
            else:
                self._kwic_string_cache = {}
        else:
            self._kwic_string_cache = {}
        self.meta_index = None
        self._regex_cache = _LRUCache(int(os.environ.get("CANDYCONC_REGEX_CACHE", "64")))
        self._prefix_all: Dict[str, Tuple[_LexiconPostingIndex, int]] = {}
        self._ngram_idx: Dict[str, Tuple[_LexiconPostingIndex, int]] = {}
        meta = MetaIndex(self.index_path)
        if meta.available():
            meta.load()
            if self.boundaries and self.boundaries.document:
                doc_count = int(self.boundaries.document._positions.size)
                if meta.doc_count and doc_count and meta.doc_count != doc_count:
                    raise RuntimeError("Meta Index doc_count passt nicht zu doc_bounds. Bitte Index neu bauen.")
            self.meta_index = meta
        self._load_regex_indices()

    def close(self) -> None:
        """Release every mmap-backed resource this backend owns (DT-CORE-LIFECYCLE).

        Best-effort close chain consumed by the server's ``_LANG_INDICES``
        eviction (DT-SERVER): closing the backend closes the token store, every
        lexicon mmap (main + prefix/ngram posting indices) and the doc-metadata
        mmap, then drops the KWIC/regex caches so an evicted corpus frees its
        file descriptors instead of leaking them. Idempotent; never raises.
        """
        ts = getattr(self, "token_store", None)
        if ts is not None:
            try:
                ts.close()
            except Exception:
                pass
        lexicons = getattr(self, "lexicons", None)
        if lexicons is not None:
            try:
                lexicons.close()
            except Exception:
                pass
        # Prefix/ngram regex posting indices each wrap their own Lexicon mmap.
        for store in (getattr(self, "_prefix_all", {}), getattr(self, "_ngram_idx", {})):
            for entry in list(store.values()):
                lex = getattr(entry[0], "lex", None) if entry else None
                if lex is not None:
                    try:
                        lex.close()
                    except Exception:
                        pass
        try:
            self._prefix_all = {}
            self._ngram_idx = {}
        except Exception:
            pass
        doc_meta = getattr(self, "doc_metadata", None)
        if doc_meta is not None and hasattr(doc_meta, "close"):
            try:
                doc_meta.close()
            except Exception:
                pass
        # Drop derived caches (no external fds, but free the memory promptly).
        try:
            self._kwic_string_cache = {}
        except Exception:
            pass
        regex_cache = getattr(self, "_regex_cache", None)
        if regex_cache is not None:
            try:
                with regex_cache._lock:
                    regex_cache._data.clear()
            except Exception:
                pass

    def __enter__(self) -> "FastIndexBackend":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _load_regex_indices(self) -> None:
        for attr in ("word", "lemma"):
            prefix_meta = self.index_path / f"{attr}_lexicon.prefix_all.meta.json"
            prefix_lex = self.index_path / f"{attr}_lexicon.prefix_all.bin"
            if prefix_meta.exists() and prefix_lex.exists():
                try:
                    meta = json.loads(prefix_meta.read_text("utf-8"))
                    plen = int(meta.get("prefix_len", 0))
                    if plen > 0:
                        self._prefix_all[attr] = (_LexiconPostingIndex(prefix_lex), plen)
                except Exception:
                    pass
            ngram_meta_list = sorted(self.index_path.glob(f"{attr}_lexicon.ngram*.meta.json"))
            for ngram_meta in ngram_meta_list:
                ngram_lex = ngram_meta.with_suffix("").with_suffix(".bin")
                if not ngram_lex.exists():
                    continue
                try:
                    meta = json.loads(ngram_meta.read_text("utf-8"))
                    nlen = int(meta.get("ngram_len", 0))
                    if nlen > 0:
                        self._ngram_idx[attr] = (_LexiconPostingIndex(ngram_lex), nlen)
                        break
                except Exception:
                    continue

    def _load_doc_metadata(self):
        mmap_idx = self.index_path / "doc_metadata.idx.bin"
        mmap_blob = self.index_path / "doc_metadata.mmap"
        if mmap_idx.exists() and mmap_blob.exists():
            return DocMetadataMMap(self.index_path)
        raise RuntimeError("doc_metadata mmap fehlt. Bitte Index neu bauen.")

    def _build_doc_paths(self) -> Sequence[str]:
        doc_count = 0
        if self.boundaries and self.boundaries.document:
            doc_count = int(self.boundaries.document._positions.size)
        if doc_count <= 0 and isinstance(self.doc_metadata, DocMetadataMMap):
            doc_count = len(self.doc_metadata)
        if doc_count <= 0 and self.doc_metadata:
            doc_count = max(int(k) for k in self.doc_metadata.keys()) + 1
        if doc_count <= 0:
            return []
        if isinstance(self.doc_metadata, DocMetadataMMap):
            return _DocPathLookup(doc_count, self.doc_metadata)  # type: ignore[return-value]
        doc_paths = [""] * doc_count
        for idx, meta in self.doc_metadata.items():
            if isinstance(meta, dict):
                if 0 <= int(idx) < doc_count:
                    doc_paths[int(idx)] = str(meta.get("path") or meta.get("doc_id") or "")
        return doc_paths

    def _doc_meta_for_idx(self, doc_idx: int) -> dict:
        meta = self.doc_metadata.get(doc_idx)
        return meta if isinstance(meta, dict) else {}

    def _validate_doc_metadata(self) -> None:
        if not self.doc_metadata:
            return
        if not (self.boundaries and self.boundaries.document):
            return
        doc_count = int(self.boundaries.document._positions.size)
        if doc_count <= 0:
            return
        if isinstance(self.doc_metadata, DocMetadataMMap):
            min_key = 0
            max_key = len(self.doc_metadata) - 1
            if max_key < 0:
                return
        else:
            min_key = None
            max_key = None
            for key in self.doc_metadata.keys():
                ik = int(key)
                if min_key is None or ik < min_key:
                    min_key = ik
                if max_key is None or ik > max_key:
                    max_key = ik
            if min_key is None or max_key is None:
                return
        if min_key < 0:
            raise RuntimeError("doc_metadata Index ungültig. Bitte Fast Index neu bauen.")
        if 0 not in self.doc_metadata:
            if min_key == 1 and max_key == doc_count:
                raise RuntimeError("doc_metadata ist 1-basiert. Bitte Fast Index neu bauen.")
            if max_key >= doc_count:
                raise RuntimeError("doc_metadata Index überschreitet doc_bounds. Bitte Fast Index neu bauen.")
        else:
            if max_key >= doc_count:
                raise RuntimeError("doc_metadata Index überschreitet doc_bounds. Bitte Fast Index neu bauen.")

    def doc_path_for_idx(self, doc_idx: int) -> str:
        if doc_idx >= 0 and doc_idx < len(self.doc_paths):
            path = self.doc_paths[doc_idx]
            if path:
                return path
        meta = self._doc_meta_for_idx(doc_idx)
        return str(meta.get("path") or meta.get("doc_id") or meta.get("name") or "")

    def _lexicon_for_attr(self, attr: str) -> Optional[Lexicon]:
        if attr == "word":
            return self.lexicons.word
        if attr == "lemma":
            return self.lexicons.lemma
        if attr == "pos":
            return self.lexicons.pos
        if attr == "morph":
            return self.lexicons.morph
        if attr == "ent":
            return self.lexicons.ent
        if attr == "rel":
            return self.lexicons.rel
        return None

    def _positions_for_id(self, attr: str, term_id: int) -> np.ndarray:
        if term_id <= 0:
            return np.array([], dtype=np.uint32)
        if attr == "word":
            return self.token_store.get_positions_for_word_id(term_id)
        if attr == "lemma":
            return self.token_store.get_positions_for_lemma_id(term_id)
        if attr == "pos":
            return self.token_store.get_positions_for_pos_id(term_id)
        if attr == "morph":
            return self.token_store.get_positions_for_morph_id(term_id)
        if attr == "ent":
            return self.token_store.get_positions_for_ent_id(term_id)
        if attr == "rel":
            return self.token_store.get_positions_for_rel_id(term_id)
        return np.array([], dtype=np.uint32)

    def _union_positions_for_ids(self, attr: str, ids: np.ndarray) -> np.ndarray:
        if ids.size == 0:
            return np.array([], dtype=np.uint32)
        if ids.size == 1:
            return self._positions_for_id(attr, int(ids[0])).astype(np.uint32, copy=False)
        try:
            offsets, data = self.token_store.get_roaring_postings(attr)
            return union_roar_positions(offsets, data, ids.astype(np.uint32, copy=False))
        except Exception:
            parts = [self._positions_for_id(attr, int(tid)) for tid in ids.tolist()]
            parts = [p for p in parts if p.size]
            if not parts:
                return np.array([], dtype=np.uint32)
            if len(parts) == 1:
                return parts[0]
            try:
                merged = parts[0]
                for arr in parts[1:]:
                    merged = union_sorted(
                        merged.astype(np.uint32, copy=False),
                        arr.astype(np.uint32, copy=False),
                    )
                return merged
            except Exception:
                return _merge_sorted_positions(parts)

    def _union_positions_for_ids_limited(self, attr: str, ids: np.ndarray, limit: int) -> np.ndarray:
        limit = int(limit)
        if limit <= 0 or ids.size == 0:
            return np.array([], dtype=np.uint32)
        if ids.size == 1:
            return self._positions_for_id(attr, int(ids[0])).astype(np.uint32, copy=False)[:limit]
        try:
            offsets, data = self.token_store.get_roaring_postings(attr)
            return union_roar_positions_limited(
                offsets,
                data,
                ids.astype(np.uint32, copy=False),
                limit,
            )
        except Exception:
            if ids.size >= _LIMITED_UNION_BITSET_MIN_IDS:
                bitset = self._bitset_for_ids(attr, ids, int(self.token_store.token_count))
                return bitset_positions_limit(bitset, int(self.token_store.token_count), limit)
            return self._union_positions_for_ids(attr, ids)[:limit]

    def _bitset_for_ids(self, attr: str, ids: np.ndarray, n_tokens: int) -> np.ndarray:
        ids_u32 = ids.astype(np.uint32, copy=False)
        try:
            offsets, data = self.token_store.get_roaring_postings(attr)
            return roaring_postings_to_bitset(offsets, data, ids_u32, int(n_tokens))
        except Exception:
            positions = self._union_positions_for_ids(attr, ids_u32)
            n_bytes = (int(n_tokens) + 7) >> 3
            out = np.zeros((n_bytes,), dtype=np.uint8)
            if positions.size == 0:
                return out
            pos_i64 = positions.astype(np.int64, copy=False)
            # Unbuffered OR-accumulate: buffered fancy-index |= keeps only the LAST
            # write per byte, silently dropping up to 7 of every 8 co-located
            # positions. np.bitwise_or.at applies every bit.
            np.bitwise_or.at(out, (pos_i64 >> 3), (np.uint8(1) << (pos_i64 & 7)).astype(np.uint8))
            return out

    def term_positions(self, term: str, attr: str = "word") -> np.ndarray:
        lex = self._lexicon_for_attr(attr)
        if lex is None:
            raise RuntimeError(_MISSING_LEXICON.format(attr=attr))
        term_id = lex.get_id(term)
        return self._positions_for_id(attr, term_id)

    def regex_positions(self, pattern: str, attr: str = "word", *, limit: int | None = None) -> np.ndarray:
        lex = self._lexicon_for_attr(attr)
        if lex is None:
            raise RuntimeError(_MISSING_LEXICON.format(attr=attr))
        ids = self._regex_ids(attr, pattern)
        if ids.size == 0:
            return np.array([], dtype=np.uint32)
        est = int(lex.get_freqs_for_ids(ids).sum())
        if est > self._MAX_REGEX_POSITIONS:
            from cqlhpc.predicates import regex_zu_gross

            raise regex_zu_gross(
                gemessen=est, grenze=int(self._MAX_REGEX_POSITIONS),
                dimension="Tokens", muster=str(pattern),
            )
        if limit is not None:
            return self._union_positions_for_ids_limited(attr, ids, int(limit))
        return self._union_positions_for_ids(attr, ids)

    def wildcard_positions(self, pattern: str, attr: str = "word", *, limit: int | None = None) -> np.ndarray:
        lex = self._lexicon_for_attr(attr)
        if lex is None:
            raise RuntimeError(_MISSING_LEXICON.format(attr=attr))
        regex = _wildcard_to_regex(pattern)
        ids = self._regex_ids(attr, regex, cache_key=(attr, f"__wc__:{regex}"))
        if ids.size == 0:
            return np.array([], dtype=np.uint32)
        est = int(lex.get_freqs_for_ids(ids).sum())
        if est > self._MAX_REGEX_POSITIONS:
            from cqlhpc.predicates import regex_zu_gross

            raise regex_zu_gross(
                gemessen=est, grenze=int(self._MAX_REGEX_POSITIONS),
                dimension="Tokens", muster=str(pattern), art="Wildcard",
            )
        if limit is not None:
            return self._union_positions_for_ids_limited(attr, ids, int(limit))
        return self._union_positions_for_ids(attr, ids)

    def _regex_ids(self, attr: str, pattern: str, *, cache_key: tuple[str, str] | None = None) -> np.ndarray:
        lex = self._lexicon_for_attr(attr)
        if lex is None:
            raise RuntimeError(_MISSING_LEXICON.format(attr=attr))
        if _regex_is_literal(pattern):
            term_id = int(lex.get_id(pattern))
            if term_id <= 0:
                return np.zeros(0, dtype=np.uint32)
            return np.asarray([term_id], dtype=np.uint32)
        key = (attr, pattern) if cache_key is None else cache_key
        cached = self._regex_cache.get(key)
        if cached is not None:
            return cached
        simple = _simple_regex_literal(pattern)
        if simple is not None:
            kind, literal = simple
            min_len = len(literal)
            max_len = min_len if kind == "literal" else None
            if kind == "literal":
                term_id = int(lex.get_id(literal))
                if term_id <= 0:
                    ids = np.zeros(0, dtype=np.uint32)
                else:
                    ids = np.asarray([term_id], dtype=np.uint32)
                self._regex_cache.set(key, ids)
                return ids
            ids = self._regex_candidates(
                attr,
                pattern,
                min_len,
                max_len,
                literal_prefix=literal if kind == "prefix" else "",
                literal_runs=[literal],
            )
            if ids is None:
                if kind == "prefix":
                    ids = lexicon_match_prefix(lex.offsets, lex.strings_view, literal, min_len, max_len)
                elif kind == "suffix":
                    ids = lexicon_match_suffix(lex.offsets, lex.strings_view, literal, min_len, max_len)
                else:
                    ids = lexicon_match_contains(lex.offsets, lex.strings_view, literal, min_len, max_len)
            else:
                if kind == "prefix":
                    ids = lexicon_match_prefix_ids(lex.offsets, lex.strings_view, ids, literal, min_len, max_len)
                elif kind == "suffix":
                    ids = lexicon_match_suffix_ids(lex.offsets, lex.strings_view, ids, literal, min_len, max_len)
                else:
                    ids = lexicon_match_contains_ids(lex.offsets, lex.strings_view, ids, literal, min_len, max_len)
            self._regex_cache.set(key, ids)
            return ids

        pat, ignorecase, _backend = _compile_regex(pattern)
        min_len, max_len = _regex_width(pattern)
        ids = None
        if not ignorecase:
            ids = self._regex_candidates(attr, pattern, min_len, max_len)
        if ids is None:
            ids = lexicon_match_regex(lex.offsets, lex.strings_view, pat, min_len, max_len)
        else:
            ids = lexicon_match_regex_ids(lex.offsets, lex.strings_view, ids, pat, min_len, max_len)
        self._regex_cache.set(key, ids)
        return ids

    def _regex_candidates(
        self,
        attr: str,
        pattern: str,
        min_len: int,
        max_len: Optional[int],
        *,
        literal_prefix: str = "",
        literal_runs: Sequence[str] | None = None,
    ) -> Optional[np.ndarray]:
        cand: Optional[np.ndarray] = None
        if attr in self._prefix_all:
            idx, plen = self._prefix_all[attr]
            prefix = literal_prefix or _regex_literal_prefix(pattern)
            if prefix and len(prefix) >= plen:
                key = prefix[:plen]
                ids = idx.ids_for(key)
                if ids.size == 0:
                    return ids
                cand = ids
        if attr in self._ngram_idx:
            idx, nlen = self._ngram_idx[attr]
            max_runs = int(os.environ.get("CANDYCONC_REGEX_MAX_RUNS", "4"))
            runs = list(literal_runs) if literal_runs is not None else _regex_mandatory_literal_runs(pattern)
            runs = [r for r in runs if len(r) >= nlen]
            if not runs:
                literal = _regex_longest_literal(pattern)
                if literal and len(literal) >= nlen:
                    runs = [literal]
            if runs:
                runs.sort(key=len, reverse=True)
                for run in runs[:max_runs]:
                    grams = {run[i : i + nlen] for i in range(0, len(run) - nlen + 1)}
                    for gram in grams:
                        ids = idx.ids_for(gram)
                        if ids.size == 0:
                            return ids
                        cand = ids if cand is None else _intersect_sorted(cand, ids)
                        if cand.size == 0:
                            return cand
        return cand

    def attr_positions(self, key: str, value: str) -> np.ndarray:
        # word belongs here: otherwise [word=und] ends with "Unbekanntes
        # Attribut: word" while [pos=NOUN] counts. Exactly like [word="und"]
        # in CQL.
        if key in {"word", "lemma", "pos", "morph", "ent", "rel"}:
            return self.term_positions(value, attr=key)
        raise RuntimeError(lt("Unbekanntes Attribut: {key}", "Unknown attribute: {key}").format(key=key))

    def entity_positions(self, ent_type: str) -> np.ndarray:
        return self.term_positions(ent_type, attr="ent")

    def rel_positions(self, rel: str) -> np.ndarray:
        return self.term_positions(rel, attr="rel")

    def dependency_positions(
        self, rel: str, head_pos: Sequence[int] | None, dep_pos: Sequence[int] | None
    ) -> np.ndarray:
        rel_positions = self.rel_positions(rel)
        if rel_positions.size == 0:
            return np.array([], dtype=np.uint32)
        head_ids = self.token_store.head_ids
        head_allow = None
        dep_allow = None
        if head_pos:
            head_allow = np.array(sorted(head_pos), dtype=np.uint32)
        if dep_pos:
            dep_allow = np.array(sorted(dep_pos), dtype=np.uint32)
        heads = dependency_heads(
            rel_positions.astype(np.uint32, copy=False),
            head_ids.astype(np.int64, copy=False),
            head_allow,
            dep_allow,
        )
        return heads.astype(np.uint32, copy=False)

    def dependency_arcs(self, start: int, end: int) -> list[tuple[int, int, str]]:
        rel_lex = self._lexicon_for_attr("rel")
        if rel_lex is None:
            return []
        if _dependency_arcs_fast is None:
            raise RuntimeError("Fast Dependency Arc Pfad fehlt. Bitte native Extension bauen.")
        head_ids = self.token_store.head_ids
        rel_ids = self.token_store.rel_ids
        total = self.token_store.token_count
        if start < 0:
            start = 0
        if end >= total:
            end = total - 1
        return _dependency_arcs_fast(
            head_ids.astype(np.int64, copy=False),
            rel_ids.astype(np.uint32, copy=False),
            rel_lex.offsets,
            rel_lex.strings_view,
            int(start),
            int(end),
        )

    def sequence_positions(self, tokens: Sequence[str]) -> np.ndarray:
        if not tokens:
            return np.array([], dtype=np.uint32)
        word_lex = self.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
        ids = [word_lex.get_id(tok) for tok in tokens]
        if any(term_id <= 0 for term_id in ids):
            return np.array([], dtype=np.uint32)
        positions_u32 = self.token_store.get_positions_for_word_id(ids[0]).astype(np.uint32, copy=False)
        if positions_u32.size == 0:
            return positions_u32
        if len(ids) == 1:
            return positions_u32
        if _intersect_sorted_fast is None:
            raise RuntimeError("Fast Sequenzpfad fehlt. Bitte native Extension bauen.")
        max_pos = self.token_store.token_count - len(ids)
        if max_pos < 0:
            return np.array([], dtype=np.uint32)
        base_u32 = positions_u32[positions_u32 <= np.uint32(max_pos)]
        if base_u32.size == 0:
            return np.array([], dtype=np.uint32)
        for offset, term_id in enumerate(ids[1:], start=1):
            other_u32 = self.token_store.get_positions_for_word_id(term_id).astype(np.uint32, copy=False)
            if other_u32.size == 0:
                return np.array([], dtype=np.uint32)
            base_u32 = intersect_shifted(
                base_u32,
                other_u32,
                offset,
                max_pos,
            )
            if base_u32.size == 0:
                return np.array([], dtype=np.uint32)
        return base_u32.astype(np.uint32, copy=False)

    def _get_kwic_string_cache(self, word_lex):
        """Return the shared KWIC string cache, building it once if absent.

        Double-checked locking: the common case (cache already present) takes no
        lock; only the rare first-build path serializes. The build allocates an
        empty container — it is NOT the heavy Cython KWIC compute, which runs on
        the returned object outside this critical section. The cache identity is
        stable once built, so concurrent first-access can never discard a
        partially-populated cache.
        """
        cache = getattr(self, "_kwic_string_cache", None)
        if cache is not None:
            return cache
        with self._cache_lock:
            cache = getattr(self, "_kwic_string_cache", None)
            if cache is not None:
                return cache
            lex_size = int(word_lex.offsets.shape[0]) if word_lex.offsets.size else 0
            if 0 < lex_size <= _KWIC_LIST_CACHE_MAX_SIZE:
                cache = [None] * lex_size
            else:
                cache = {}
            self._kwic_string_cache = cache
            return cache

    def kwic_rows_for_positions(
        self,
        positions: np.ndarray,
        ctx: int,
        include_arcs: bool = True,
        include_file: bool = True,
        compact: bool = False,
    ) -> list[dict[str, object]]:
        if positions.size == 0:
            return []
        word_lex = self.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
        positions_u32 = positions.astype(np.uint32, copy=False)
        
        doc_bounds = (
            self.boundaries.document._positions
            if self.boundaries and self.boundaries.document
            else np.array([], dtype=np.uint32)
        )

        word_stream = self.token_store.word_stream
        text_cache = self._get_kwic_string_cache(word_lex)
        rows = kwic_rows_svb(
            positions_u32,
            word_stream.offsets,
            word_stream.data,
            int(word_stream.block_size),
            int(self.token_store.token_count),
            int(ctx),
            doc_bounds,
            self.doc_paths,
            word_lex.offsets,
            word_lex.strings_view,
            text_cache,
            include_file=include_file,
            compact=compact,
        )
        if include_arcs:
            for row_idx, row in enumerate(rows):
                if isinstance(row, tuple):
                    pos = int(row[3]) if len(row) > 3 else 0
                else:
                    pos = int(row.get("pos", 0))
                left_start = max(0, pos - ctx)
                right_end = min(self.token_store.token_count - 1, pos + ctx)
                arcs = self.dependency_arcs(left_start, right_end)
                if isinstance(row, tuple):
                    rows[row_idx] = row + (arcs,)
                else:
                    row["arcs"] = arcs
        return rows

    def kwic_compact_buffers_for_positions(
        self,
        positions: np.ndarray,
        ctx: int,
        *,
        two_token_pivot_one: bool = False,
    ) -> dict[str, object] | None:
        if positions.size == 0:
            return None
        word_lex = self.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
        positions_u32 = positions.astype(np.uint32, copy=False)
        doc_bounds = (
            self.boundaries.document._positions
            if self.boundaries and self.boundaries.document
            else np.array([], dtype=np.uint32)
        )
        word_stream = self.token_store.word_stream
        text_cache = self._get_kwic_string_cache(word_lex)
        return kwic_rows_svb_compact_buffers(
            positions_u32,
            word_stream.offsets,
            word_stream.data,
            int(word_stream.block_size),
            int(self.token_store.token_count),
            int(ctx),
            doc_bounds,
            word_lex.offsets,
            word_lex.strings_view,
            text_cache,
            two_token_pivot_one=two_token_pivot_one,
        )

    def kwic_compact_rows_for_positions(
        self,
        positions: np.ndarray,
        ctx: int,
        *,
        two_token_pivot_one: bool = False,
    ) -> list[tuple[object, ...]] | None:
        if positions.size == 0:
            return None
        word_lex = self.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
        positions_u32 = positions.astype(np.uint32, copy=False)
        doc_bounds = (
            self.boundaries.document._positions
            if self.boundaries and self.boundaries.document
            else np.array([], dtype=np.uint32)
        )
        word_stream = self.token_store.word_stream
        text_cache = self._get_kwic_string_cache(word_lex)
        try:
            rows = kwic_rows_svb_compact_buffers(
                positions_u32,
                word_stream.offsets,
                word_stream.data,
                int(word_stream.block_size),
                int(self.token_store.token_count),
                int(ctx),
                doc_bounds,
                word_lex.offsets,
                word_lex.strings_view,
                text_cache,
                two_token_pivot_one=two_token_pivot_one,
                return_rows=True,
            )
            if rows is not None:
                return rows
        except TypeError:
            pass
        buffers = self.kwic_compact_buffers_for_positions(
            positions,
            ctx,
            two_token_pivot_one=two_token_pivot_one,
        )
        if buffers is None:
            return None
        return kwic_compact_buffer_rows(buffers, two_token_pivot_one=two_token_pivot_one)

    def kwic_rows(
        self,
        term: str,
        ctx: int = 5,
        *,
        attr: str = "word",
        limit: int | None = None,
        include_arcs: bool = True,
    ) -> list[dict[str, object]]:
        positions = self.term_positions(term, attr=attr)
        if positions.size == 0:
            return []
        if limit is not None:
            positions = positions[:limit]
        return self.kwic_rows_for_positions(positions, ctx, include_arcs=include_arcs)

    def query_dependency(
        self,
        *,
        rel: str,
        head_word: str | None = None,
        dep_word: str | None = None,
        head_attr: DependencyAttrFilter | None = None,
        dep_attr: DependencyAttrFilter | None = None,
        ctx: int = 5,
    ) -> list[dict[str, object]]:
        rel_positions = self.rel_positions(rel)
        if rel_positions.size == 0:
            return []
        dep_positions = rel_positions
        if dep_word:
            dep_positions = _intersect_positions(
                dep_positions,
                self.term_positions(dep_word, attr="word"),
            )
        if dep_attr:
            dep_positions = _intersect_positions(
                dep_positions,
                self._dependency_attr_positions(dep_attr),
            )
        if dep_positions.size == 0:
            return []
        head_ids = self.token_store.head_ids
        word_lex = self.lexicons.word
        head_attr_positions = (
            self._dependency_attr_positions(head_attr) if head_attr else None
        )
        head_dep_pairs: list[tuple[int, int]] = []
        for dep in dep_positions:
            head = int(head_ids[dep])
            if head < 0:
                continue
            if head_word:
                head_token_id = int(self.token_store.get_word_id(head))
                if word_lex is None or word_lex.get_string(head_token_id) != head_word:
                    continue
            if not _contains_position(head_attr_positions, head):
                continue
            head_dep_pairs.append((head, int(dep)))
        if not head_dep_pairs:
            return []
        unique_heads = np.array(sorted({h for h, _ in head_dep_pairs}), dtype=np.uint32)
        kwic_rows = self.kwic_rows_for_positions(unique_heads, ctx)
        if not kwic_rows:
            return []
        row_map = {int(r.get("pos", -1)): r for r in kwic_rows}
        rows: list[dict[str, object]] = []
        for head, dep in head_dep_pairs:
            row = row_map.get(head)
            if not row:
                continue
            out_row = dict(row)
            out_row["dep_pos"] = int(dep)
            out_row["dep"] = (
                word_lex.get_string(int(self.token_store.get_word_id(dep))) if word_lex else ""
            )
            rows.append(out_row)
        return rows

    def _dependency_attr_positions(self, attr_filter: DependencyAttrFilter) -> np.ndarray:
        if isinstance(attr_filter, tuple):
            key, value = attr_filter
        else:
            # Backward-compatible internal API: a bare value is an exact morph filter,
            # not a substring heuristic. Parser calls pass (key, value).
            key, value = "morph", attr_filter
        attr = str(key).strip().lower()
        if attr == "ner":
            attr = "ent"
        if attr == "word":
            return self.term_positions(str(value), attr="word").astype(np.uint32, copy=False)
        if attr in {"lemma", "pos", "morph", "ent", "rel"}:
            return self.term_positions(str(value), attr=attr).astype(np.uint32, copy=False)
        raise RuntimeError(f"Unbekanntes Dependency-Attribut: {attr}")

    def query_metadata(
        self,
        term: str,
        *,
        date: str | None = None,
        genre: str | None = None,
        ctx: int = 5,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        positions = self.term_positions(term, attr="word")
        if positions.size == 0:
            return []
        if date is None and genre is None:
            if limit is not None:
                positions = positions[:limit]
            return self.kwic_rows_for_positions(positions, ctx)

        doc_bounds = (
            self.boundaries.document._positions
            if self.boundaries and self.boundaries.document
            else np.array([], dtype=np.uint32)
        )
        if doc_bounds.size == 0:
            return []
        keep: list[int] = []
        doc_idx = 0
        next_boundary = (
            int(doc_bounds[1]) if doc_bounds.size > 1 else self.token_store.token_count
        )
        for pos in positions.tolist():
            pos_i = int(pos)
            while doc_idx + 1 < doc_bounds.size and pos_i >= next_boundary:
                doc_idx += 1
                next_boundary = (
                    int(doc_bounds[doc_idx + 1])
                    if doc_idx + 1 < doc_bounds.size
                    else self.token_store.token_count
                )
            meta = self._doc_meta_for_idx(int(doc_idx))
            if date and meta.get("date") != date:
                continue
            if genre and meta.get("genre") != genre:
                continue
            keep.append(pos_i)
            if limit is not None and len(keep) >= limit:
                break
        if not keep:
            return []
        return self.kwic_rows_for_positions(np.array(keep, dtype=np.uint32), ctx)
