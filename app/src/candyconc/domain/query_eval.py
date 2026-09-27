from __future__ import annotations
from typing import Any, Optional, Dict, Generator, Set, Callable, Iterator, Iterable
from collections import OrderedDict
from pathlib import Path
import hashlib
import logging
import re
import tempfile
import threading
from candyconc.config import get as get_config
from .query_parser import parse_query


import numpy as np

from .query_parser import (
    Node,
    Term,
    Attr,
    Not,
    And,
    Or,
    Near,
    Regex,
    Wildcard,
    Dependency,
    canonicalize_term,
    wortsuche_hinweis,
)
from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.counting_kernels import filter_positions_by_docset_fast
from candyconc.i18n import LocalizedText, lt

# User-visible runtime messages (HTTP 503 detail, /query/stream error frame).
# The German text stays the marker of query_count._SERVER_STATE_ERROR_MARKERS.
_DOC_BOUNDS_MISSING = lt(
    "Dokumentgrenzen fehlen. Bitte Index neu bauen.",
    "Document boundaries are missing. Rebuild the index.",
)
_DOC_BOUNDS_EMPTY = lt(
    "Dokumentgrenzen leer. Bitte Index neu bauen.",
    "Document boundaries are empty. Rebuild the index.",
)
_DOCSET_MASK_MISMATCH = lt(
    "Docset Maske passt nicht zur Dokumentanzahl.",
    "Document set mask does not match the number of documents.",
)


def _native_path_missing(operator: str) -> LocalizedText:
    return lt(
        "Fast {operator} Pfad fehlt. Bitte native Extension bauen.",
        "The native {operator} path is missing. Build the native extension.",
    ).format(operator=operator)

try:
    from candyconc.core import _fast_index as _fast_index_mod  # type: ignore
    _near_positions_fast = getattr(_fast_index_mod, "near_positions", None)
    _intersect_sorted_fast = getattr(_fast_index_mod, "intersect_sorted", None)
    _union_sorted_fast = getattr(_fast_index_mod, "union_sorted", None)
    _setdiff_sorted_fast = getattr(_fast_index_mod, "setdiff_sorted", None)
    _complement_sorted_fast = getattr(_fast_index_mod, "complement_sorted", None)
except Exception:  # pragma: no cover - optional fast path
    _near_positions_fast = None
    _intersect_sorted_fast = None
    _union_sorted_fast = None
    _setdiff_sorted_fast = None
    _complement_sorted_fast = None
try:  # optional limit-aware fast path
    from candyconc.core.counting_kernels import (
        intersect_sorted_limit_fast as _intersect_sorted_limit_fast,
        union_sorted_limit_fast as _union_sorted_limit_fast,
    )
except Exception:  # pragma: no cover - optional fast path
    _intersect_sorted_limit_fast = None
    _union_sorted_limit_fast = None


_CACHE_ENABLED: bool = get_config("CANDYCONC_ENABLE_QUERY_CACHE", "0") == "1"
_CACHE_SIZE = int(get_config("CANDYCONC_QUERY_CACHE_SIZE", "128"))
_NOT_MAX_TOKENS = int(get_config("CANDYCONC_NOT_MAX_TOKENS", "50000000"))
_INCLUDE_ARCS: bool = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
# Cache key = (normalized_query, index_path, case_insensitive). The
# case_insensitive flag MUST participate so a case-sensitive query and a
# case-insensitive query for the same surface string never collide
# (DT-CORE-CASE-FREQ).
_CacheKey = "tuple[str, str, bool]"
_INDEX_MAP: dict[str, CorpusIndex] = {}
_POSITIONS_CACHE: "OrderedDict[tuple[str, str, bool], np.ndarray]" = OrderedDict()
_POSITIONS_CACHE_LOCK = threading.Lock()
_CACHE_WARM_ENABLED: bool = get_config("CANDYCONC_QUERY_CACHE_WARM", "1") == "1"
_CACHE_WARM_INFLIGHT: set[tuple[str, str, bool]] = set()
_CACHE_WARM_LOCK = threading.Lock()
_SPILL_MAX = int(get_config("CANDYCONC_QUERY_SPILL_MAX", "5000000"))
_SPILL_DIR = Path(get_config("CANDYCONC_QUERY_SPILL_DIR", tempfile.gettempdir()))
_SPILL_FILES: dict[tuple[str, str, bool], Path] = {}
_LOG_QUERIES = get_config("CANDYCONC_LOG_QUERIES", "0") == "1"
_LOGGER = logging.getLogger(__name__)


def _cache_key(query: str, index_path: str, case_insensitive: bool) -> tuple[str, str, bool]:
    return (_normalize_cache_query(query), str(index_path), bool(case_insensitive))


def _query_fingerprint(query: str) -> str:
    if not query:
        return "empty"
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def _normalize_cache_query(query: str) -> str:
    return query.strip()


def _positions_cache_get(key: tuple[str, str, bool]) -> np.ndarray | None:
    with _POSITIONS_CACHE_LOCK:
        cached = _POSITIONS_CACHE.get(key)
        if cached is None:
            return None
        _POSITIONS_CACHE.move_to_end(key)
        return cached


def _positions_cache_set(key: tuple[str, str, bool], positions: np.ndarray) -> np.ndarray:
    if _SPILL_MAX > 0 and positions.size >= _SPILL_MAX:
        try:
            _SPILL_DIR.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(prefix="candyconc_pos_", suffix=".mmap", dir=str(_SPILL_DIR))
            try:
                file_path = Path(path)
            finally:
                try:
                    import os
                    os.close(fd)
                except Exception:
                    pass
            mmap_arr = np.memmap(file_path, dtype=positions.dtype, mode="w+", shape=positions.shape)
            mmap_arr[:] = positions
            mmap_arr.flush()
            positions = mmap_arr
            _SPILL_FILES[key] = file_path
        except Exception:
            _SPILL_FILES.pop(key, None)
            positions = positions.copy()
    positions.setflags(write=False)
    with _POSITIONS_CACHE_LOCK:
        previous = _POSITIONS_CACHE.get(key)
        if previous is not None:
            _cleanup_spill_entry(key, previous)
        _POSITIONS_CACHE[key] = positions
        _POSITIONS_CACHE.move_to_end(key)
        while len(_POSITIONS_CACHE) > _CACHE_SIZE:
            old_key, old_val = _POSITIONS_CACHE.popitem(last=False)
            _cleanup_spill_entry(old_key, old_val)
    return positions


def _positions_cache_clear() -> None:
    with _POSITIONS_CACHE_LOCK:
        for old_key, old_val in list(_POSITIONS_CACHE.items()):
            _cleanup_spill_entry(old_key, old_val)
        _POSITIONS_CACHE.clear()
        _SPILL_FILES.clear()


def _cleanup_spill_entry(key: tuple[str, str, bool], value: np.ndarray) -> None:
    file_path = _SPILL_FILES.pop(key, None)
    if file_path is None:
        return
    try:
        if isinstance(value, np.memmap) and getattr(value, "_mmap", None) is not None:
            value._mmap.close()
    except Exception:
        pass
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception:
        pass


def _warm_cache_async(
    query: str, index: CorpusIndex, node: Node, *, case_insensitive: bool = True
) -> None:
    if not _CACHE_WARM_ENABLED or not _CACHE_ENABLED:
        return
    if _node_has_not(node):
        return
    key = _cache_key(query, str(index.path), case_insensitive)
    with _CACHE_WARM_LOCK:
        if key in _CACHE_WARM_INFLIGHT:
            return
        _CACHE_WARM_INFLIGHT.add(key)

    def _runner() -> None:
        try:
            prefetch_positions(query, index, case_insensitive=case_insensitive)
        except Exception:
            pass
        finally:
            with _CACHE_WARM_LOCK:
                _CACHE_WARM_INFLIGHT.discard(key)

    threading.Thread(target=_runner, daemon=True).start()


def _filter_positions_by_docset_mask(
    index: CorpusIndex, positions: np.ndarray, docset_mask: np.ndarray
) -> np.ndarray:
    if positions.size == 0:
        return positions
    if not (index.fast_index.boundaries and index.fast_index.boundaries.document):
        raise RuntimeError(_DOC_BOUNDS_MISSING)
    doc_bounds = index.fast_index.boundaries.document._positions
    if doc_bounds.size == 0:
        raise RuntimeError(_DOC_BOUNDS_EMPTY)
    if docset_mask.size < doc_bounds.size:
        raise RuntimeError(_DOCSET_MASK_MISMATCH)
    return filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)


def _node_has_not(node: Node) -> bool:
    if isinstance(node, Not):
        return True
    for attr in ("node", "left", "right", "head", "dep"):
        child = getattr(node, attr, None)
        if child is not None and _node_has_not(child):
            return True
    return False


def evaluate_tokens(node: Node, tokens: Iterable[str]) -> Set[int]:
    """Evaluate a query AST against an in-memory token sequence.

    This helper keeps parser-level unit tests on the canonical domain module
    without depending on the Fast Index runtime.
    """
    token_list = [str(token) for token in tokens]

    if isinstance(node, Term):
        parts = node.value.split()
        if not parts:
            return set()
        if len(parts) == 1:
            return {idx for idx, token in enumerate(token_list) if token == parts[0]}
        width = len(parts)
        return {
            idx
            for idx in range(0, max(0, len(token_list) - width + 1))
            if token_list[idx : idx + width] == parts
        }
    if isinstance(node, Regex):
        pattern = re.compile(node.pattern)
        return {idx for idx, token in enumerate(token_list) if pattern.fullmatch(token)}
    if isinstance(node, Wildcard):
        pattern = "^" + re.escape(node.value).replace(r"\*", ".*").replace(r"\?", ".") + "$"
        regex = re.compile(pattern)
        return {idx for idx, token in enumerate(token_list) if regex.fullmatch(token)}
    if isinstance(node, Attr):
        return {idx for idx, token in enumerate(token_list) if node.key == "word" and token == node.value}
    if isinstance(node, Not):
        return set(range(len(token_list))) - evaluate_tokens(node.node, token_list)
    if isinstance(node, And):
        return evaluate_tokens(node.left, token_list) & evaluate_tokens(node.right, token_list)
    if isinstance(node, Or):
        return evaluate_tokens(node.left, token_list) | evaluate_tokens(node.right, token_list)
    if isinstance(node, Near):
        left = evaluate_tokens(node.left, token_list)
        right = evaluate_tokens(node.right, token_list)
        return {
            pos
            for pos in left
            if any(abs(pos - other) <= int(node.distance) for other in right)
        }
    if isinstance(node, Dependency):
        return set()
    raise TypeError(f"Unsupported node type: {type(node)}")


def _positions_cached(
    query: str, index_path: str, *, case_insensitive: bool = True
) -> np.ndarray:
    key = _cache_key(query, index_path, case_insensitive)
    cached = _positions_cache_get(key)
    if cached is not None:
        return cached
    index = _INDEX_MAP[index_path]
    node = parse_query(_normalize_cache_query(query))
    positions = _eval(
        node, index, limit=None, allow_limit=False, case_insensitive=case_insensitive
    )
    return _positions_cache_set(key, positions)


def _iter_array(values: Iterable[int] | np.ndarray) -> Iterator[int]:
    if isinstance(values, np.ndarray):
        for val in values:
            yield int(val)
    else:
        for val in values:
            yield int(val)


def _iter_union_sorted(a_iter: Iterator[int], b_iter: Iterator[int]) -> Iterator[int]:
    a_val = next(a_iter, None)
    b_val = next(b_iter, None)
    while a_val is not None or b_val is not None:
        if b_val is None or (a_val is not None and a_val < b_val):
            yield int(a_val)
            a_val = next(a_iter, None)
        elif a_val is None or b_val < a_val:
            yield int(b_val)
            b_val = next(b_iter, None)
        else:
            yield int(a_val)
            a_val = next(a_iter, None)
            b_val = next(b_iter, None)


def _iter_intersect_sorted(a_iter: Iterator[int], b_iter: Iterator[int]) -> Iterator[int]:
    a_val = next(a_iter, None)
    b_val = next(b_iter, None)
    while a_val is not None and b_val is not None:
        if a_val == b_val:
            yield int(a_val)
            a_val = next(a_iter, None)
            b_val = next(b_iter, None)
        elif a_val < b_val:
            a_val = next(a_iter, None)
        else:
            b_val = next(b_iter, None)


def _iter_positions(
    node: Node,
    index: CorpusIndex,
    *,
    limit: int | None = None,
    allow_limit: bool = False,
    case_insensitive: bool = True,
) -> Iterator[int]:
    ci = bool(case_insensitive)

    def _simple_positions(n: Node) -> np.ndarray | None:
        if isinstance(n, Term):
            value = canonicalize_term(n.value)
            if " " in value:
                return _as_positions(
                    index.sequence_positions(value.split(), case_insensitive=ci)
                )
            return _as_positions(index.term_positions(value, case_insensitive=ci))
        if isinstance(n, Regex):
            return _as_positions(index.regex_positions(n.pattern, case_insensitive=ci))
        if isinstance(n, Wildcard):
            return _as_positions(
                index.wildcard_positions(canonicalize_term(n.value), case_insensitive=ci)
            )
        if isinstance(n, Attr):
            if n.key == "ent":
                return _as_positions(index.entity_positions(n.value))
            if n.key == "rel":
                return _as_positions(index.rel_positions(n.value))
            return _as_positions(index.attr_positions(n.key, n.value))
        return None
    if isinstance(node, Term):
        value = canonicalize_term(node.value)
        if " " in value:
            return _iter_array(index.sequence_positions(value.split(), case_insensitive=ci))
        return _iter_array(_wortform_positionen(index, value, ci))
    if isinstance(node, Regex):
        return _iter_array(index.regex_positions(node.pattern, case_insensitive=ci))
    if isinstance(node, Wildcard):
        return _iter_array(
            index.wildcard_positions(canonicalize_term(node.value), case_insensitive=ci)
        )
    if isinstance(node, Attr):
        if node.key == "ent":
            return _iter_array(index.entity_positions(node.value))
        if node.key == "rel":
            return _iter_array(index.rel_positions(node.value))
        return _iter_array(index.attr_positions(node.key, node.value))
    if isinstance(node, Not):
        base = _eval(node.node, index, limit=limit, allow_limit=False, case_insensitive=ci)
        complement = _complement_positions(index, base, limit, allow_limit)
        return _iter_array(complement)
    if isinstance(node, And):
        if allow_limit and limit is not None and _intersect_sorted_limit_fast is not None:
            left_arr = _simple_positions(node.left)
            right_arr = _simple_positions(node.right)
            if left_arr is not None and right_arr is not None:
                out = _intersect_sorted_limit_fast(_beschreibbar(left_arr), _beschreibbar(right_arr), int(limit))
                return _iter_array(out)
        left = _iter_positions(
            node.left, index, limit=limit, allow_limit=allow_limit, case_insensitive=ci
        )
        right = _iter_positions(
            node.right, index, limit=limit, allow_limit=allow_limit, case_insensitive=ci
        )
        return _iter_intersect_sorted(left, right)
    if isinstance(node, Or):
        if allow_limit and limit is not None and _union_sorted_limit_fast is not None:
            left_arr = _simple_positions(node.left)
            right_arr = _simple_positions(node.right)
            if left_arr is not None and right_arr is not None:
                out = _union_sorted_limit_fast(_beschreibbar(left_arr), _beschreibbar(right_arr), int(limit))
                return _iter_array(out)
        left = _iter_positions(
            node.left, index, limit=limit, allow_limit=allow_limit, case_insensitive=ci
        )
        right = _iter_positions(
            node.right, index, limit=limit, allow_limit=allow_limit, case_insensitive=ci
        )
        return _iter_union_sorted(left, right)
    if isinstance(node, Near):
        left_pos = _eval(node.left, index, allow_limit=False, case_insensitive=ci)
        right_pos = _eval(node.right, index, allow_limit=False, case_insensitive=ci)
        return _iter_array(_near_positions(left_pos, right_pos, node.distance, index))
    if isinstance(node, Dependency):
        head_pos = _eval(node.head, index, allow_limit=False, case_insensitive=ci)
        dep_pos = _eval(node.dep, index, allow_limit=False, case_insensitive=ci)
        # A side without a match leaves no pair. Passing None would drop the
        # condition of that side.
        if head_pos.size == 0 or dep_pos.size == 0:
            return _iter_array(np.zeros(0, dtype=np.uint32))
        positions = index.dependency_positions(node.rel, head_pos.tolist(), dep_pos.tolist())
        return _iter_array(_as_positions(positions))
    raise TypeError(f"Unsupported node type: {type(node)}")


def _iter_positions_filtered(
    positions_iter: Iterator[int],
    index: CorpusIndex,
    docset_mask: np.ndarray,
    *,
    chunk_size: int = 4096,
) -> Iterator[int]:
    if not (index.fast_index.boundaries and index.fast_index.boundaries.document):
        raise RuntimeError(_DOC_BOUNDS_MISSING)
    doc_bounds = index.fast_index.boundaries.document._positions
    if doc_bounds.size == 0:
        raise RuntimeError(_DOC_BOUNDS_EMPTY)
    if docset_mask.size < doc_bounds.size:
        raise RuntimeError(_DOCSET_MASK_MISMATCH)

    buf: list[int] = []
    for pos in positions_iter:
        buf.append(int(pos))
        if len(buf) >= chunk_size:
            arr = np.array(buf, dtype=np.uint32)
            for val in filter_positions_by_docset_fast(arr, doc_bounds, docset_mask):
                yield int(val)
            buf.clear()
    if buf:
        arr = np.array(buf, dtype=np.uint32)
        for val in filter_positions_by_docset_fast(arr, doc_bounds, docset_mask):
            yield int(val)


def _kwic_rows_from_positions_iter(
    index: CorpusIndex,
    positions_iter: Iterator[int],
    ctx: int,
    limit: int | None,
    *,
    chunk_size: int = 2048,
) -> Iterator[Dict[str, str | int]]:
    buf: list[int] = []
    yielded = 0
    for pos in positions_iter:
        buf.append(int(pos))
        if limit is not None and yielded + len(buf) >= limit:
            remaining = limit - yielded
            if remaining <= 0:
                return
            chunk = np.array(buf[:remaining], dtype=np.uint32)
            for row in _kwic_rows_fast_iter(index, chunk, ctx, None):
                yield row
            return
        if len(buf) >= chunk_size:
            chunk = np.array(buf, dtype=np.uint32)
            for row in _kwic_rows_fast_iter(index, chunk, ctx, None):
                yield row
            yielded += len(buf)
            buf.clear()
    if buf:
        chunk = np.array(buf, dtype=np.uint32)
        for row in _kwic_rows_fast_iter(index, chunk, ctx, None):
            yield row


def _skip_positions_iter(positions_iter: Iterator[int], offset: int) -> Iterator[int]:
    if offset <= 0:
        return positions_iter

    def _gen() -> Iterator[int]:
        skipped = 0
        for pos in positions_iter:
            if skipped < offset:
                skipped += 1
                continue
            yield pos

    return _gen()


def evaluate(
    node: Node,
    index: CorpusIndex,
    ctx: int,
    *,
    query: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    docset_mask: np.ndarray | None = None,
    case_insensitive: bool = True,
) -> Generator[Dict[str, str | int], None, None]:
    """Yield KWIC rows matching ``node`` from ``index``.

    ``case_insensitive`` (default True) is threaded to every leaf lookup AND
    participates in the positions-cache key, so an exact-case query and a
    case-insensitive query for the same surface string never share a cache
    entry (DT-CORE-CASE-FREQ).

    A row sits at the first token of its match. When every match spans the
    same tokens (a phrase), the row lists the others in ``match_offsets``,
    like the rows of a CQL sequence.
    """
    rows = _evaluate_rows(
        node,
        index,
        ctx,
        query=query,
        limit=limit,
        offset=offset,
        use_cache=use_cache,
        allow_cache_fallback=allow_cache_fallback,
        count_cb=count_cb,
        docset_mask=docset_mask,
        case_insensitive=case_insensitive,
    )
    offsets = fixed_match_offsets(node)
    if offsets is None:
        yield from rows
        return
    for row in rows:
        if isinstance(row, dict) and "match_offsets" not in row:
            row["match_offsets"] = offsets
        yield row


def plain_query_match_offsets(query: str) -> list[int] | None:
    """:func:`fixed_match_offsets` of a plain query text, None when it does not parse."""
    try:
        node = parse_query(_normalize_cache_query(query))
    except Exception:
        return None
    return fixed_match_offsets(node)


def _evaluate_rows(
    node: Node,
    index: CorpusIndex,
    ctx: int,
    *,
    query: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    docset_mask: np.ndarray | None = None,
    case_insensitive: bool = True,
) -> Generator[Dict[str, str | int], None, None]:
    """Rows of :func:`evaluate` without ``match_offsets``."""
    if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("evaluate query hash=%s node=%s", _query_fingerprint(query or ""), type(node).__name__)

    ci = bool(case_insensitive)
    if use_cache is None:
        use_cache = _CACHE_ENABLED

    offset = max(0, int(offset))
    limit_total = None if limit is None else int(offset) + int(limit)
    positions_are_full = False

    if use_cache and query is not None:
        _INDEX_MAP[str(index.path)] = index
        if allow_cache_fallback:
            normalized_query = _normalize_cache_query(query)
            cached = get_cached_positions(normalized_query, index, case_insensitive=ci)
            if cached is not None:
                positions = cached
                positions_are_full = True
            else:
                if limit_total is not None and count_cb is None:
                    _warm_cache_async(query, index, node, case_insensitive=ci)
                    positions_iter = _iter_positions(
                        node, index, limit=limit_total, allow_limit=True, case_insensitive=ci
                    )
                    if docset_mask is not None:
                        positions_iter = _iter_positions_filtered(
                            positions_iter, index, docset_mask
                        )
                    positions_iter = _skip_positions_iter(positions_iter, offset)
                    for row in _kwic_rows_from_positions_iter(
                        index,
                        positions_iter,
                        ctx,
                        limit,
                    ):
                        yield row
                    return
                can_full_eval = not _node_has_not(node)
                want_full_eval = can_full_eval and (count_cb is not None or limit_total is None)
                eval_limit = None if want_full_eval else limit_total
                positions = _eval(  # noqa: F821
                    node,
                    index,
                    limit=eval_limit,
                    allow_limit=eval_limit is not None,
                    case_insensitive=ci,
                )
                positions_are_full = eval_limit is None
                if positions_are_full and can_full_eval and _CACHE_ENABLED:
                    _positions_cache_set(
                        _cache_key(normalized_query, str(index.path), ci), positions
                    )
        else:
            positions = _positions_cached(query, str(index.path), case_insensitive=ci)
            positions_are_full = True
    else:
        if limit_total is not None and count_cb is None:
            positions_iter = _iter_positions(
                node, index, limit=limit_total, allow_limit=True, case_insensitive=ci
            )
            if docset_mask is not None:
                positions_iter = _iter_positions_filtered(
                    positions_iter, index, docset_mask
                )
            positions_iter = _skip_positions_iter(positions_iter, offset)
            for row in _kwic_rows_from_positions_iter(
                index,
                positions_iter,
                ctx,
                limit,
            ):
                yield row
            return
        positions = _eval(  # noqa: F821
            node, index, limit=limit_total, allow_limit=True, case_insensitive=ci
        )
        positions_are_full = limit_total is None
    if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("evaluate positions=%d", int(positions.size))
    if docset_mask is not None and positions.size:
        positions = _filter_positions_by_docset_mask(index, positions, docset_mask)
    if count_cb is not None and positions_are_full:
        try:
            count_cb(int(positions.size))
        except Exception:
            _LOGGER.exception("count callback failed")
    if offset:
        positions = positions[int(offset):]
    rows_iter = _kwic_rows_fast_iter(index, positions, ctx, limit)
    # best-effort count for logging without materializing all rows
    count = 0
    for row in rows_iter:
        count += 1
        yield row
    if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("evaluate rows=%d", count)
    return


def prefetch_positions(
    query: str, index: CorpusIndex, *, case_insensitive: bool = True
) -> np.ndarray:
    """Return all matching positions and populate the cache when enabled."""
    positions, _positions_are_full = prefetch_positions_window(
        query,
        index,
        limit=None,
        offset=0,
        use_cache=None,
        allow_cache_fallback=True,
        case_insensitive=case_insensitive,
    )
    return positions


def prefetch_positions_window(
    query: str,
    index: CorpusIndex,
    *,
    limit: int | None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = True,
    case_insensitive: bool = True,
) -> tuple[np.ndarray, bool]:
    """Return query positions, optionally limited, and whether they are complete.

    ``case_insensitive`` (default True) threads down to the leaf lookups and
    participates in the positions-cache key (DT-CORE-CASE-FREQ).
    """
    ci = bool(case_insensitive)
    normalized = _normalize_cache_query(query)
    node = parse_query(normalized)
    if use_cache is None:
        use_cache = _CACHE_ENABLED
    offset = max(0, int(offset))
    limit_total = None if limit is None else int(offset) + int(limit)
    positions_are_full = False

    if use_cache:
        _INDEX_MAP[str(index.path)] = index
        if allow_cache_fallback:
            cached = get_cached_positions(normalized, index, case_insensitive=ci)
            if cached is not None:
                positions = cached
                positions_are_full = True
            else:
                can_full_eval = not _node_has_not(node)
                want_full_eval = can_full_eval and limit_total is None
                eval_limit = None if want_full_eval else limit_total
                positions = _eval(
                    node,
                    index,
                    limit=eval_limit,
                    allow_limit=eval_limit is not None,
                    case_insensitive=ci,
                )
                # A bounded eval still covers the WHOLE match set when it returned
                # fewer positions than the cap — the scan exhausted naturally and
                # never truncated (KWIC-PLAIN-02 over-claim). Only a result that hit
                # exactly ``eval_limit`` may have more behind it. Term/Attr leaves
                # ignore the limit and return everything, so a sorted scan over
                # ``und`` is genuinely complete while a capped ``[word=".*"]`` (size
                # == eval_limit) stays bounded → still flagged sort-approximate.
                positions_are_full = eval_limit is None or int(positions.size) < int(eval_limit)
                if positions_are_full and can_full_eval and eval_limit is None and _CACHE_ENABLED:
                    positions = _positions_cache_set(
                        _cache_key(normalized, str(index.path), ci), positions
                    )
        else:
            positions = _positions_cached(normalized, str(index.path), case_insensitive=ci)
            positions_are_full = True
    else:
        positions = _eval(
            node,
            index,
            limit=limit_total,
            allow_limit=limit_total is not None,
            case_insensitive=ci,
        )
        # Same KWIC-PLAIN-02 completeness rule on the cache-disabled path: a bounded
        # scan that returned fewer than the cap covered the whole match set.
        positions_are_full = limit_total is None or int(positions.size) < int(limit_total)

    if offset:
        positions = positions[int(offset):]
    if limit is not None:
        positions = positions[: int(limit)]
    positions.setflags(write=False)
    return positions, positions_are_full


def get_cached_positions(
    query: str, index: CorpusIndex, *, case_insensitive: bool = True
) -> np.ndarray | None:
    """Return cached positions if available, without triggering evaluation."""
    if not _CACHE_ENABLED:
        return None
    key = _cache_key(query, str(index.path), case_insensitive)
    return _positions_cache_get(key)


def clear_positions_cache() -> None:
    _positions_cache_clear()


def count_positions(
    query: str, index: CorpusIndex, *, case_insensitive: bool = True
) -> int:
    """Return the total number of matches for a query."""
    positions = prefetch_positions(query, index, case_insensitive=case_insensitive)
    return int(positions.size)


def _kwic_rows_fast_iter(
    index: CorpusIndex,
    positions: np.ndarray | list[int],
    ctx: int,
    limit: int | None,
    *,
    chunk_size: int = 10000,
):
    if isinstance(positions, np.ndarray):
        pos_arr = positions
    else:
        pos_arr = np.array(positions, dtype=np.uint32)
    if pos_arr.size == 0:
        return
    if limit is not None:
        pos_arr = pos_arr[:limit]
    for i in range(0, pos_arr.size, chunk_size):
        chunk = pos_arr[i : i + chunk_size]
        rows = index.fast_index.kwic_rows_for_positions(
            chunk, ctx, include_arcs=_INCLUDE_ARCS
        )
        for row in rows:
            yield row


def _kwic_rows_fast(
    index: CorpusIndex, positions: np.ndarray | list[int], ctx: int, limit: int | None
) -> list[Dict[str, str | int]]:
    return list(_kwic_rows_fast_iter(index, positions, ctx, limit))


def _kwic_row(index: CorpusIndex, pos: int, ctx: int) -> Dict[str, str | int] | None:  # noqa: F821
    rows = _kwic_rows_fast(index, np.array([pos], dtype=np.uint32), ctx, 1)
    return rows[0] if rows else None


def _empty_positions() -> np.ndarray:
    return np.zeros(0, dtype=np.uint32)


def _as_positions(values: Set[int] | list[int] | np.ndarray) -> np.ndarray:
    if isinstance(values, np.ndarray):
        return values.astype(np.uint32, copy=False)
    if not values:
        return _empty_positions()
    arr = np.array(list(values), dtype=np.uint32)
    if arr.size > 1:
        arr = np.unique(arr)
    return arr


def _wortform_positionen(index: CorpusIndex, value: str, ci: bool) -> np.ndarray:
    """Die Positionen einer Wortform. Bleibt eine Oder- oder Attributschreibweise
    leer, meldet die Wortsuche die Form, die zaehlt, statt still 0 (wortsuche_hinweis)."""
    positions = _as_positions(index.term_positions(value, case_insensitive=ci))
    if positions.size == 0:
        hinweis = wortsuche_hinweis(value)
        if hinweis:
            raise ValueError(hinweis)
    return positions


def _beschreibbar(values: np.ndarray) -> np.ndarray:
    """Eine beschreibbare uint32-Fassung fuer die Cython-Mengenoperationen.

    They require writable buffers. prefetch_positions puts results into the
    cache read-only, and for a single word that is the same array the index
    holds for this word. Without a copy "Und OR Oder" with
    case_insensitive=False ends with "buffer source array is read-only".
    fast_index_backend._intersect_sorted takes the same precaution.
    """
    arr = np.asarray(values, dtype=np.uint32)
    return arr if arr.flags.writeable else arr.copy()


def _complement_positions(
    index: CorpusIndex, positions: np.ndarray, limit: int | None, allow_limit: bool
) -> np.ndarray:
    total = index.num_tokens()
    if total <= 0:
        return _empty_positions()
    if _complement_sorted_fast is None:
        raise RuntimeError(_native_path_missing("NOT"))
    if allow_limit and limit is not None:
        return _complement_sorted_fast(int(total), _beschreibbar(positions), int(limit))
    if total > _NOT_MAX_TOKENS:
        raise RuntimeError(
            lt(
                "NOT Query zu gross. Bitte AND mit einem positiven Term nutzen oder limit setzen.",
                "NOT query too large. Combine it with a positive term (AND) or set a limit.",
            )
        )
    return _complement_sorted_fast(int(total), _beschreibbar(positions), -1)


def _near_positions(left: np.ndarray, right: np.ndarray, distance: int, index: Any = None) -> np.ndarray:
    if left.size == 0 or right.size == 0:
        return _empty_positions()
    im_dokument = _near_im_dokument(left, right, int(distance), index)
    if im_dokument is not None:
        return im_dokument
    if _near_positions_fast is None:
        raise RuntimeError(_native_path_missing("NEAR"))
    return _near_positions_fast(_beschreibbar(left), _beschreibbar(right), int(distance))


def _near_im_dokument(left: np.ndarray, right: np.ndarray, d: int, index: Any) -> Optional[np.ndarray]:
    """NEAR within one document, otherwise the same rule as near_positions.

    Plain search must not count across document boundaries. Word sequences
    are bound to their document, and so is NEAR here. As in
    _fast_index.near_positions, a hit on either side counts if the window
    [p-d, p+d] contains a partner of the other side that is not only itself,
    sorted and without duplicates. The only difference is that the window
    ends at its own document. None without document boundaries."""
    grenzen = getattr(getattr(getattr(index, "fast_index", None), "boundaries", None), "document", None)
    if not grenzen:
        return None
    anf = np.asarray(grenzen._positions, dtype=np.int64)
    if anf.size == 0:
        return None
    n_tok = int(index.fast_index.token_store.token_count)

    def _treffer(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        a = np.asarray(a, dtype=np.int64)
        b = np.asarray(b, dtype=np.int64)
        doc = np.searchsorted(anf, a, side="right") - 1
        ende = np.where(doc + 1 < anf.size, anf[np.minimum(doc + 1, anf.size - 1)], n_tok)
        lo = np.searchsorted(b, np.maximum(a - d, anf[doc]), side="left")
        hi = np.searchsorted(b, np.minimum(a + d, ende - 1), side="right")
        anzahl = hi - lo
        nur_selbst = (anzahl == 1) & (b[np.minimum(lo, b.size - 1)] == a)
        return a[(anzahl > 0) & ~nur_selbst]

    return np.unique(np.concatenate([_treffer(left, right), _treffer(right, left)])).astype(np.uint32)


def fixed_match_length(node: Node) -> int | None:
    """Number of tokens every match of ``node`` spans from its position, or None.

    ``_eval`` returns the first position of each match. A phrase term spans
    its words, the other leaves one token. AND keeps positions where both
    sides start (the longer side sets the span), AND NOT keeps the span of the
    positive side. OR and NEAR mix positions of both sides, so they have one
    span only when both sides agree.
    """
    if isinstance(node, Term):
        return max(1, len(canonicalize_term(node.value).split()))
    if isinstance(node, (Attr, Regex, Wildcard, Not, Dependency)):
        return 1
    if isinstance(node, And):
        if isinstance(node.left, Not):
            return fixed_match_length(node.right)
        if isinstance(node.right, Not):
            return fixed_match_length(node.left)
        left, right = fixed_match_length(node.left), fixed_match_length(node.right)
        if left is None or right is None:
            return None
        return max(left, right)
    if isinstance(node, (Or, Near)):
        left, right = fixed_match_length(node.left), fixed_match_length(node.right)
        return left if left == right else None
    return None


def fixed_match_offsets(node: Node) -> list[int] | None:
    """``match_offsets`` of a row at a match of ``node`` (the tokens after its position).

    None when a match is one token long or the span varies.
    """
    length = fixed_match_length(node)
    if length is None or length <= 1:
        return None
    return list(range(1, length))


def _eval(
    node: Node,
    index: CorpusIndex,
    *,
    limit: int | None = None,
    allow_limit: bool = False,
    case_insensitive: bool = True,
) -> np.ndarray:
    """Return sorted positions matching ``node`` in ``index``.

    ``case_insensitive`` (default True, the German plain-search convention) is
    threaded down to every leaf position lookup so an exact-case query
    (``case_insensitive=False``) honours the literal casing of terms, phrases,
    wildcards and regexes. It is the single switch that makes the whole AST
    case-sensitive. The leaf helpers share ONE case contract
    (``str.lower``, ß und ss getrennt) when it is True (DT-CORE-CASE-FREQ).
    """
    ci = bool(case_insensitive)

    if isinstance(node, Term):
        value = canonicalize_term(node.value)
        if " " in value:
            return _as_positions(index.sequence_positions(value.split(), case_insensitive=ci))
        positions = _wortform_positionen(index, value, ci)
        if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("term positions=%d", int(positions.size))
        return positions
    if isinstance(node, Regex):
        return _as_positions(
            index.regex_positions(
                node.pattern,
                limit=limit if allow_limit else None,
                case_insensitive=ci,
            )
        )
    if isinstance(node, Wildcard):
        return _as_positions(
            index.wildcard_positions(
                canonicalize_term(node.value),
                limit=limit if allow_limit else None,
                case_insensitive=ci,
            )
        )
    if isinstance(node, Attr):
        if node.key == "ent":
            return _as_positions(index.entity_positions(node.value))
        if node.key == "rel":
            return _as_positions(index.rel_positions(node.value))
        return _as_positions(index.attr_positions(node.key, node.value))
    if isinstance(node, Not):
        return _complement_positions(
            index,
            _eval(node.node, index, limit=limit, allow_limit=False, case_insensitive=ci),
            limit,
            allow_limit,
        )
    if isinstance(node, And):
        if isinstance(node.left, Not):
            left = _eval(node.right, index, allow_limit=False, case_insensitive=ci)
            right = _eval(node.left.node, index, allow_limit=False, case_insensitive=ci)
            if _setdiff_sorted_fast is None:
                raise RuntimeError(_native_path_missing("AND/NOT"))
            return _setdiff_sorted_fast(_beschreibbar(left), _beschreibbar(right))
        if isinstance(node.right, Not):
            left = _eval(node.left, index, allow_limit=False, case_insensitive=ci)
            right = _eval(node.right.node, index, allow_limit=False, case_insensitive=ci)
            if _setdiff_sorted_fast is None:
                raise RuntimeError(_native_path_missing("AND/NOT"))
            return _setdiff_sorted_fast(_beschreibbar(left), _beschreibbar(right))
        left = _eval(node.left, index, allow_limit=False, case_insensitive=ci)
        right = _eval(node.right, index, allow_limit=False, case_insensitive=ci)
        if _intersect_sorted_fast is None:
            raise RuntimeError(_native_path_missing("AND"))
        return _intersect_sorted_fast(_beschreibbar(left), _beschreibbar(right))
    if isinstance(node, Or):
        left = _eval(node.left, index, allow_limit=False, case_insensitive=ci)
        right = _eval(node.right, index, allow_limit=False, case_insensitive=ci)
        if _union_sorted_fast is None:
            raise RuntimeError(_native_path_missing("OR"))
        return _union_sorted_fast(_beschreibbar(left), _beschreibbar(right))
    if isinstance(node, Near):
        left_pos = _eval(node.left, index, allow_limit=False, case_insensitive=ci)
        right_pos = _eval(node.right, index, allow_limit=False, case_insensitive=ci)
        return _near_positions(left_pos, right_pos, node.distance, index)
    if isinstance(node, Dependency):
        head_pos = _eval(node.head, index, allow_limit=False, case_insensitive=ci)
        dep_pos = _eval(node.dep, index, allow_limit=False, case_insensitive=ci)
        # A side without a match leaves no pair (see _iter_positions).
        if head_pos.size == 0 or dep_pos.size == 0:
            return np.zeros(0, dtype=np.uint32)
        positions = index.dependency_positions(node.rel, head_pos.tolist(), dep_pos.tolist())
        return _as_positions(positions)
    raise TypeError(f"Unsupported node type: {type(node)}")


__all__ = [
    "evaluate",
    "fixed_match_length",
    "fixed_match_offsets",
    "plain_query_match_offsets",
    "prefetch_positions",
    "count_positions",
    "get_cached_positions",
    "clear_positions_cache",
]
