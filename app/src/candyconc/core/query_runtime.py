"""Fast Index query runtime wrapper."""

from typing import Any, Dict, Generator, Optional, Callable
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path as SysPath
import hashlib
import logging
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from .corpus_index import CorpusIndex
from .fast_index_backend import FastIndexBackend
from .counting_kernels import (
    filter_positions_and_values_by_docset_fast,
    filter_positions_by_docset_fast,
    position_to_doc_id_fast,
)
from candyconc.domain.query_parser import Dependency, Attr, Term, parse_query
from cqlhpc.ast import Tok, Seq, Alt, Quant, Within, Where
from cqlhpc.normalize import normalize
from cqlhpc.parser import parse_cql
from candyconc.config import get as get_config
from candyconc.domain.query_eval import evaluate, prefetch_positions
from .cql_macros import normalize_query_input
from candyconc.utils.text_normalize import normalize_text_basic
from candyconc.i18n import exception_text, lt
from .source_spacing import apply_source_spacing, apply_source_spacing_rows, display_flags

_DOC_BOUNDS_MISSING = lt(
    "Dokumentgrenzen fehlen. Bitte Index neu bauen.",
    "Document boundaries missing. Rebuild the index.",
)
_DOC_BOUNDS_EMPTY = lt(
    "Dokumentgrenzen leer. Bitte Index neu bauen.",
    "Document boundaries empty. Rebuild the index.",
)
_DOCSET_MASK_MISMATCH = lt(
    "Docset Maske passt nicht zur Dokumentanzahl.",
    "Document set mask does not match the document count.",
)

_CORPUS_INDEX: Optional[CorpusIndex] = None

_CQL_CACHE_ENABLED = get_config("CANDYCONC_ENABLE_QUERY_CACHE", "0") == "1"
_CQL_CACHE_SIZE = int(get_config("CANDYCONC_CQL_CACHE_SIZE", "64"))
_CQL_CACHE_WARM = get_config("CANDYCONC_CQL_CACHE_WARM", "1") == "1"
_CQL_RESULTS_MAX = int(get_config("CANDYCONC_CQL_RESULTS_MAX", "2000000000"))
_CQL_COUNT_MAX = int(get_config("CANDYCONC_CQL_COUNT_MAX", str(_CQL_RESULTS_MAX)))
_CQL_POSITIONS_CACHE: "OrderedDict[tuple[str, str], np.ndarray]" = OrderedDict()
_CQL_SPANS_CACHE: "OrderedDict[tuple[str, str], np.ndarray]" = OrderedDict()
_CQL_SPANS_CACHE_BYTES = 0
_CQL_SPANS_CACHE_MAX_BYTES = int(
    get_config("CANDYCONC_CQL_SPANS_CACHE_MAX_BYTES", str(256 * 1024 * 1024))
)
_CQL_CACHE_LOCK = threading.RLock()
_CQL_CACHE_INFLIGHT: set[tuple[str, str]] = set()
_CQL_SPILL_MAX = int(get_config("CANDYCONC_CQL_SPILL_MAX", "5000000"))
_CQL_SPILL_DIR = SysPath(get_config("CANDYCONC_CQL_SPILL_DIR", tempfile.gettempdir()))
_CQL_SPILL_TTL_SEC = int(get_config("CANDYCONC_CQL_SPILL_TTL_SEC", "86400"))
_CQL_SPILL_FILES: dict[tuple[str, str], SysPath] = {}
_LOG_QUERIES = get_config("CANDYCONC_LOG_QUERIES", "0") == "1"
_LOGGER = logging.getLogger(__name__)
_CQL_COUNT_PROBE_HARD_MAX = 2_147_483_647
_INDEX_CACHE_SIG_ARTIFACTS = ("meta.bin", "document_bounds.bin", "index_build_meta.json", "index_manifest.json")


def _cleanup_orphan_cql_spills() -> None:
    if _CQL_SPILL_TTL_SEC <= 0:
        return
    try:
        if not _CQL_SPILL_DIR.exists():
            return
        now = time.time()
        for entry in _CQL_SPILL_DIR.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if not name.startswith("candyconc_cql_") or not name.endswith(".mmap"):
                continue
            try:
                age = now - entry.stat().st_mtime
            except Exception:
                continue
            if age >= _CQL_SPILL_TTL_SEC:
                try:
                    entry.unlink()
                except Exception:
                    _LOGGER.debug("Failed to remove CQL spill file: %s", entry)
    except Exception:
        _LOGGER.debug("Failed to cleanup CQL spill directory", exc_info=True)


_cleanup_orphan_cql_spills()


def _index_cache_path(index: CorpusIndex) -> str:
    path = getattr(index, "path", None)
    fingerprint = ""
    manifest = getattr(index, "manifest", None)
    if manifest is not None:
        fingerprint = str(getattr(manifest, "build_fingerprint", "") or "")
    if path is not None:
        base_path = SysPath(path)
        base = str(base_path)
    else:
        base_path = None
        base = ""
    fast_index = getattr(index, "fast_index", None)
    if not base and fast_index is not None:
        fast_path = getattr(fast_index, "index_path", None)
        if fast_path is not None:
            base_path = SysPath(fast_path)
            base = str(base_path)
    newest = 0
    if base_path is not None:
        for name in _INDEX_CACHE_SIG_ARTIFACTS:
            try:
                mtime = (base_path / name).stat().st_mtime_ns
            except OSError:
                continue
            if mtime > newest:
                newest = mtime
    if fingerprint or newest:
        return f"{base}@{fingerprint}@{newest}"
    return base


def _query_fingerprint(query: str) -> str:
    if not query:
        return "empty"
    return hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]


def _cql_sequence_tokens(node) -> list[Tok] | None:
    if isinstance(node, Where):
        return _cql_sequence_tokens(node.node)
    if isinstance(node, Within):
        return _cql_sequence_tokens(node.node)
    if isinstance(node, Tok):
        return [node]
    if isinstance(node, Seq):
        tokens: list[Tok] = []
        for part in node.parts:
            sub = _cql_sequence_tokens(part)
            if sub is None:
                return None
            tokens.extend(sub)
        return tokens
    if isinstance(node, Quant):
        if node.n is None or node.m != node.n:
            return None
        sub = _cql_sequence_tokens(node.node)
        if sub is None:
            return None
        return sub * max(0, int(node.m))
    if isinstance(node, Alt):
        return None
    return None


def _token_has_fixed_word(tok: Tok) -> bool:
    for cond in tok.clause.conds:
        attr = str(cond.attr).lower()
        if attr not in ("word", "lemma", "form", "orth", "text"):
            continue
        if cond.op == "=" and isinstance(cond.value, str) and cond.value:
            return True
        if cond.op == "in":
            values = cond.value
            if isinstance(values, (list, tuple, set)) and len(values) == 1:
                return True
    return False


@lru_cache(maxsize=4096)
def _cql_render_hints(query: str) -> tuple[int, int | None]:
    try:
        query = normalize_text_basic(query or "")
        ast = normalize(parse_cql(query))
    except Exception:
        return 0, None
    tokens = _cql_sequence_tokens(ast)
    if not tokens:
        return 0, None
    pivot_index = 0
    for idx, tok in enumerate(tokens):
        if _token_has_fixed_word(tok):
            pivot_index = idx
            break
    return pivot_index, len(tokens)


def _cql_pivot_index(query: str) -> int:
    return _cql_render_hints(query)[0]


def _cql_fixed_token_count(query: str) -> int | None:
    return _cql_render_hints(query)[1]


def _cql_count_probe_limit(count_limit: int) -> int:
    count_limit = max(1, int(count_limit))
    if count_limit >= _CQL_COUNT_PROBE_HARD_MAX:
        return count_limit
    return count_limit + 1


def exact_cql_count_sentinel_dropped(
    idx: CorpusIndex,
    query: str,
    *,
    probe_limit: int,
    progress_cb: Callable | None = None,
) -> tuple[int, bool]:
    """Exact CQL match count with the ``|LBR|`` sentinel removed.

    Materialises match-start positions (capped at ``probe_limit``) and routes
    them through :func:`drop_linebreak_sentinel_positions` — the SAME seam the
    rows builders use — so the count can never exceed the rows. Returns
    ``(count, capped)`` where ``capped`` means the probe limit was hit and the
    count is therefore a floor, not exact.
    """
    from .cql_engine import search_cql_match_arrays_backend

    positions, _spans = search_cql_match_arrays_backend(
        idx.fast_index, query, limit=int(probe_limit), progress_cb=progress_cb
    )
    capped = int(positions.size) >= int(probe_limit)
    positions, _ = drop_linebreak_sentinel_positions(idx, np.asarray(positions))
    return int(positions.size), capped


def _report_exact_cql_count(
    count_cb: Callable[[int], None] | None,
    idx: CorpusIndex,
    query: str,
    *,
    progress_cb: Callable | None,
    log_context: str,
) -> bool:
    if count_cb is None:
        return False
    count_limit = max(1, int(_CQL_COUNT_MAX))
    probe_limit = _cql_count_probe_limit(count_limit)
    if linebreak_sentinel_word_id(idx) > 0:
        # Sentinel present on this index: materialise positions and drop it through
        # the shared seam so the reported count equals the rows.
        total_count, capped = exact_cql_count_sentinel_dropped(
            idx, query, probe_limit=probe_limit, progress_cb=progress_cb
        )
    else:
        # Sentinel-free index: keep the cheap pure-count probe (no positions).
        from .cql_engine import count_cql_matches_backend

        total_count = int(
            count_cql_matches_backend(
                idx.fast_index,
                query,
                max_matches=probe_limit,
                progress_cb=progress_cb,
            )
        )
        capped = total_count >= probe_limit
    if capped:
        _LOGGER.info(
            "%s: omitted capped CQL count callback at count_limit=%s",
            log_context,
            count_limit,
        )
        return False
    count_cb(int(total_count))
    return True


def _apply_cql_span_to_row(row: Dict[str, str], match_len: int, pivot_index: int) -> Dict[str, str]:
    if match_len <= 1:
        return row
    pivot = max(0, min(int(pivot_index), match_len - 1))
    if pivot == 0:
        row["match_offsets"] = [idx for idx in range(1, match_len)]
        return row
    if match_len == 2 and pivot == 1:
        row["match_offsets"] = [-1]
        right = str(row.get("right", ""))
        if right:
            split_at = right.find(" ")
            if split_at < 0:
                next_kw = right
                rest = ""
            else:
                next_kw = right[:split_at]
                rest = right[split_at + 1 :]
            left = str(row.get("left", ""))
            cur_kw = str(row.get("kw", ""))
            row["left"] = f"{left} {cur_kw}".strip() if cur_kw else left
            row["kw"] = next_kw
            row["right"] = rest
        if "pos" in row and isinstance(row.get("pos"), (int, np.integer)):
            row["pos"] = int(row["pos"]) + 1
        return row
    right_tokens = str(row.get("right", "")).split()
    max_len = 1 + len(right_tokens)
    if match_len > max_len:
        match_len = max_len
    if match_len <= 1:
        return row
    # Re-clamp pivot: when the right context is shorter than the match (a match
    # near a document/corpus end), match_len shrinks and an un-clamped pivot would
    # index past match_tokens -> IndexError aborting the whole result render.
    if pivot > match_len - 1:
        pivot = match_len - 1
    row["match_offsets"] = [idx - pivot for idx in range(match_len) if idx != pivot]
    left_tokens = str(row.get("left", "")).split()
    kw = str(row.get("kw", ""))
    match_tokens = [kw] + right_tokens[: match_len - 1]
    before = match_tokens[:pivot]
    after = match_tokens[pivot + 1 :]
    row["left"] = " ".join(left_tokens + before)
    row["kw"] = match_tokens[pivot]
    row["right"] = " ".join(after + right_tokens[match_len - 1 :])
    if "pos" in row and isinstance(row.get("pos"), (int, np.integer)):
        row["pos"] = int(row["pos"]) + int(pivot)
    return row


def _cql_cache_get(key: tuple[str, str]) -> np.ndarray | None:
    with _CQL_CACHE_LOCK:
        cached = _CQL_POSITIONS_CACHE.get(key)
        if cached is None:
            return None
        _CQL_POSITIONS_CACHE.move_to_end(key)
        return cached


def _cql_spans_cache_get(key: tuple[str, str]) -> np.ndarray | None:
    with _CQL_CACHE_LOCK:
        cached = _CQL_SPANS_CACHE.get(key)
        if cached is None:
            return None
        _CQL_SPANS_CACHE.move_to_end(key)
        return cached


def _cql_spans_cache_drop(key: tuple[str, str]) -> None:
    global _CQL_SPANS_CACHE_BYTES
    with _CQL_CACHE_LOCK:
        cached = _CQL_SPANS_CACHE.pop(key, None)
        if cached is not None:
            _CQL_SPANS_CACHE_BYTES -= int(getattr(cached, "nbytes", 0))


def _cql_spans_cache_set(key: tuple[str, str], spans: np.ndarray) -> np.ndarray:
    global _CQL_SPANS_CACHE_BYTES
    spans = np.asarray(spans, dtype=np.int64)
    spans.setflags(write=False)
    entry_bytes = int(getattr(spans, "nbytes", 0))
    with _CQL_CACHE_LOCK:
        previous = _CQL_SPANS_CACHE.pop(key, None)
        if previous is not None:
            _CQL_SPANS_CACHE_BYTES -= int(getattr(previous, "nbytes", 0))
        _CQL_SPANS_CACHE[key] = spans
        _CQL_SPANS_CACHE.move_to_end(key)
        _CQL_SPANS_CACHE_BYTES += entry_bytes
        while len(_CQL_SPANS_CACHE) > _CQL_CACHE_SIZE:
            _old_key, _old_val = _CQL_SPANS_CACHE.popitem(last=False)
            _CQL_SPANS_CACHE_BYTES -= int(getattr(_old_val, "nbytes", 0))
        while _CQL_SPANS_CACHE and _CQL_SPANS_CACHE_BYTES > _CQL_SPANS_CACHE_MAX_BYTES:
            _old_key, _old_val = _CQL_SPANS_CACHE.popitem(last=False)
            _CQL_SPANS_CACHE_BYTES -= int(getattr(_old_val, "nbytes", 0))
    return spans


def _cql_cache_set(key: tuple[str, str], positions: np.ndarray) -> np.ndarray:
    if _CQL_SPILL_MAX > 0 and positions.size >= _CQL_SPILL_MAX:
        try:
            _CQL_SPILL_DIR.mkdir(parents=True, exist_ok=True)
            fd, path = tempfile.mkstemp(prefix="candyconc_cql_", suffix=".mmap", dir=str(_CQL_SPILL_DIR))
            try:
                file_path = SysPath(path)
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
            _CQL_SPILL_FILES[key] = file_path
        except Exception:
            _CQL_SPILL_FILES.pop(key, None)
            positions = positions.copy()
    positions.setflags(write=False)
    with _CQL_CACHE_LOCK:
        previous = _CQL_POSITIONS_CACHE.get(key)
        if previous is not None:
            _cleanup_cql_spill_entry(key, previous)
        _CQL_POSITIONS_CACHE[key] = positions
        _CQL_POSITIONS_CACHE.move_to_end(key)
        while len(_CQL_POSITIONS_CACHE) > _CQL_CACHE_SIZE:
            old_key, old_val = _CQL_POSITIONS_CACHE.popitem(last=False)
            _cleanup_cql_spill_entry(old_key, old_val)
            _cql_spans_cache_drop(old_key)
    return positions


def clear_cql_positions_cache() -> None:
    global _CQL_SPANS_CACHE_BYTES
    with _CQL_CACHE_LOCK:
        for old_key, old_val in list(_CQL_POSITIONS_CACHE.items()):
            _cleanup_cql_spill_entry(old_key, old_val)
        _CQL_POSITIONS_CACHE.clear()
        _CQL_SPILL_FILES.clear()
        _CQL_SPANS_CACHE.clear()
        _CQL_SPANS_CACHE_BYTES = 0


def _resolve_cql_match_arrays(
    index: CorpusIndex,
    query: str,
    *,
    max_matches: int,
    use_cache: bool,
    allow_cache_fallback: bool = False,
    exhaustive: bool = False,
    progress_cb: Callable | None = None,
    docset_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, int | None, np.ndarray | None, bool]:
    from .cql_engine import search_cql_match_arrays_backend

    cache_key = (query, _index_cache_path(index))
    fixed_match_len = _cql_fixed_token_count(query)
    cache_allowed = bool(use_cache) and docset_mask is None
    cached_positions = _cql_cache_get(cache_key) if cache_allowed else None
    cached_spans = None
    if fixed_match_len is None and cache_allowed:
        cached_spans = _cql_spans_cache_get(cache_key)
    if cached_positions is not None:
        if fixed_match_len is not None:
            return cached_positions, fixed_match_len, None, True
        if cached_spans is not None and cached_spans.shape[0] == cached_positions.shape[0]:
            return cached_positions, None, cached_spans, True

    starts, ends = search_cql_match_arrays_backend(
        index.fast_index,
        query,
        limit=max_matches,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    n_matches = int(starts.shape[0])
    # A scan that returns fewer rows than its budget is complete regardless of
    # whether the caller asked for a full materialization or a page-sized window.
    positions_are_full = bool(int(max_matches) > 0 and n_matches < int(max_matches))
    if n_matches == 0:
        positions = np.zeros(0, dtype=np.uint32)
        spans = None if fixed_match_len is not None else np.zeros(0, dtype=np.int64)
    else:
        if fixed_match_len is not None:
            positions = starts.astype(np.uint32, copy=False)
            spans = None
        else:
            positions = starts.astype(np.uint32, copy=False)
            spans = np.maximum(
                1,
                ends.astype(np.int64, copy=False) - starts.astype(np.int64, copy=False),
            )
        if positions.size > 1 and np.any(positions[1:] < positions[:-1]):
            order = np.argsort(positions, kind="mergesort")
            positions = positions[order]
            if spans is not None:
                spans = spans[order]
    if cache_allowed and positions_are_full:
        positions = _cql_cache_set(cache_key, positions)
        if spans is not None:
            spans = _cql_spans_cache_set(cache_key, spans)
        else:
            _cql_spans_cache_drop(cache_key)
    elif cache_allowed and allow_cache_fallback:
        _warm_cql_cache_async(query, index)
    return positions, fixed_match_len, spans, positions_are_full


def _cleanup_cql_spill_entry(key: tuple[str, str], value: np.ndarray) -> None:
    file_path = _CQL_SPILL_FILES.pop(key, None)
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


def _warm_cql_cache_async(query: str, index: CorpusIndex) -> None:
    if not _CQL_CACHE_ENABLED or not _CQL_CACHE_WARM:
        return
    key = (query, _index_cache_path(index))
    with _CQL_CACHE_LOCK:
        if key in _CQL_CACHE_INFLIGHT:
            return
        _CQL_CACHE_INFLIGHT.add(key)

    def _runner() -> None:
        try:
            _resolve_cql_match_arrays(
                index,
                query,
                max_matches=_CQL_RESULTS_MAX,
                use_cache=True,
                allow_cache_fallback=False,
                exhaustive=True,
                progress_cb=None,
            )
        except Exception:
            pass
        finally:
            with _CQL_CACHE_LOCK:
                _CQL_CACHE_INFLIGHT.discard(key)

    threading.Thread(target=_runner, daemon=True).start()


# The index-only line-break sentinel: a normalised newline stored as a first-class
# word-id in the frozen lexicon, NOT a searchable word. Defined here (the core
# query seam) rather than imported from the backend kwic_renderer so that rows,
# count, and the copilot primitive all share ONE drop filter without core
# depending on the service layer. Kept byte-identical to
# ``kwic_renderer._LINEBREAK_MARKER``.
_LINEBREAK_MARKER = "|LBR|"


def linebreak_sentinel_word_id(idx: CorpusIndex) -> int:
    """Resolve the ``|LBR|`` line-break sentinel's word-id once per index.

    The sentinel is an index-only structural marker (a normalised newline), not a
    searchable word: the ranking paths already drop it via ``is_analyst_token``.
    Returns ``0`` when this corpus has no such lexicon entry, which makes the
    drop below a no-op (real word-ids start at 1).
    """
    cached = getattr(idx, "_lbr_sentinel_word_id", None)
    if cached is not None:
        return int(cached)
    word_id = 0
    lex = getattr(getattr(idx.fast_index, "lexicons", None), "word", None)
    if lex is not None:
        try:
            word_id = int(lex.get_id(_LINEBREAK_MARKER) or 0)
        except Exception:  # pragma: no cover - lexicon shape guard
            word_id = 0
    try:
        idx._lbr_sentinel_word_id = word_id
    except Exception:  # pragma: no cover - read-only/exotic index objects
        pass
    return word_id


def drop_linebreak_sentinel_positions(
    idx: CorpusIndex,
    positions: np.ndarray,
    *,
    match_lengths: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Drop match-start positions whose NODE token is the ``|LBR|`` sentinel.

    KWIC word-matching (``[word="|LBR|"]`` literal, ``[word=".*"]`` regex, the
    legacy plain path) resolves against the frozen lexicon, which holds ``|LBR|``
    as a first-class word-id — so the structural line-break marker leaks into raw
    results as bogus matches that render with a BLANK node. We exclude ONLY that
    one specific sentinel (real punctuation stays searchable) by checking the
    NODE (match-start) token's word-id, so counts for every real word are
    unchanged. Parallel per-match arrays (``match_lengths``) are filtered with the
    same mask.

    This is the SINGLE seam shared by the rows builders, every count surface, and
    the copilot query primitive so the displayed count can never contradict the
    rows beneath it.
    """
    if positions.size == 0:
        return positions, match_lengths
    sentinel_id = linebreak_sentinel_word_id(idx)
    if sentinel_id <= 0:
        return positions, match_lengths
    word_stream = getattr(
        getattr(idx.fast_index, "token_store", None), "word_stream", None
    )
    gather = getattr(word_stream, "get_ranges_packed_i32", None)
    if not callable(gather):  # exotic/partial index -> degrade to no-op
        return positions, match_lengths
    starts = positions.astype(np.int64, copy=False)
    node_ids = gather(starts, starts + 1)
    if int(node_ids.size) != int(positions.size):
        # Shape guard: never silently drop real hits if the gather is unexpected.
        return positions, match_lengths
    keep = node_ids != np.int32(sentinel_id)
    if bool(keep.all()):
        return positions, match_lengths
    filtered_positions = positions[keep]
    filtered_lengths = match_lengths[keep] if match_lengths is not None else None
    return filtered_positions, filtered_lengths


def _kwic_rows_for_positions_fast(
    fast_index: Any,
    positions: np.ndarray,
    ctx: int,
    *,
    include_arcs: bool,
    include_file: bool,
    compact_rows: bool = False,
):
    if compact_rows:
        try:
            return fast_index.kwic_rows_for_positions(
                positions,
                ctx,
                include_arcs=include_arcs,
                include_file=include_file,
                compact=True,
            )
        except TypeError as exc:
            if "compact" not in str(exc):
                raise
    return fast_index.kwic_rows_for_positions(
        positions,
        ctx,
        include_arcs=include_arcs,
        include_file=include_file,
    )


def set_corpus(index: Optional[CorpusIndex]) -> None:
    """Set a global :class:`CorpusIndex` used by :func:`run_query`."""
    global _CORPUS_INDEX
    _CORPUS_INDEX = index



def run_query(
    term: str | None,
    ctx: int = 5,
    *,
    corpus: Optional[CorpusIndex] = None,
    lang: str = "en",
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    docset_mask: np.ndarray | None = None,
    include_file: bool = True,
) -> Generator[Dict[str, str], None, None]:
    """Yield context rows for ``term`` using :func:`evaluate`.

    When the corpus has ``whitespace_after.bin``, ``left``, ``kw`` and
    ``right`` show the original spacing and each row carries ``token_starts``
    (see :mod:`candyconc.core.source_spacing`). Positions and offsets are the
    same either way.
    """
    rows = _run_query_rows(
        term,
        ctx,
        corpus=corpus,
        lang=lang,
        limit=limit,
        offset=offset,
        use_cache=use_cache,
        allow_cache_fallback=allow_cache_fallback,
        count_cb=count_cb,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
        include_file=include_file,
    )
    ws = display_flags(corpus or _CORPUS_INDEX)
    if ws is None:
        yield from rows
        return
    for row in rows:
        yield apply_source_spacing(row, ws)


def _run_query_rows(
    term: str | None,
    ctx: int = 5,
    *,
    corpus: Optional[CorpusIndex] = None,
    lang: str = "en",
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    docset_mask: np.ndarray | None = None,
    include_file: bool = True,
) -> Generator[Dict[str, str], None, None]:
    """The rows of :func:`run_query` in the legacy space-joined form."""

    if term is None:
        return

    if _LOG_QUERIES and _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug(
            "run_query term_hash=%s corpus=%s",
            _query_fingerprint(term or ""),
            str(corpus or _CORPUS_INDEX),
        )

    offset = max(0, int(offset))
    idx = corpus or _CORPUS_INDEX
    if idx is None:
        raise RuntimeError(
            "Kein Korpus gesetzt. Bitte set_corpus nutzen oder corpus übergeben."
        )

    term_str = normalize_query_input(normalize_text_basic(term or ""))
    if term_str.lower().startswith("cql:"):
        query = term_str[4:].strip()
        if not query:
            return
        from .cql_engine import normalize_cql_aliases
        query = normalize_cql_aliases(query)
        pivot_index = _cql_pivot_index(query)
        if use_cache is None:
            use_cache = _CQL_CACHE_ENABLED
        count_reported = False
        limit_total = None if limit is None else int(offset) + int(limit)
        max_matches = _CQL_RESULTS_MAX if limit_total is None else limit_total
        if count_cb is not None and limit_total is not None and docset_mask is None:
            try:
                count_reported = _report_exact_cql_count(
                    count_cb,
                    idx,
                    query,
                    progress_cb=progress_cb,
                    log_context="run_query",
                )
            except Exception:
                _LOGGER.exception("run_query: count callback failed")
        positions, match_len_const, match_lengths, positions_are_full = _resolve_cql_match_arrays(
            idx,
            query,
            max_matches=max_matches,
            use_cache=bool(use_cache),
            allow_cache_fallback=allow_cache_fallback,
            exhaustive=limit_total is None,
            progress_cb=progress_cb,
            docset_mask=docset_mask,
        )
        # Drop the index-only |LBR| sentinel from the FULL match set (shared seam)
        # so the yielded rows AND the count_cb below agree with the REST rows path
        # ([word="|LBR|"] -> 0, [word=".*"] -> no blank-node rows). Real words and
        # real punctuation are untouched.
        positions, match_lengths = drop_linebreak_sentinel_positions(
            idx, positions, match_lengths=match_lengths
        )
        if positions.size == 0:
            if count_cb is not None and positions_are_full and not count_reported:
                try:
                    count_cb(0)
                except Exception:
                    _LOGGER.exception("run_query: count callback failed")
            return
        if docset_mask is not None and positions.size:
            if not (idx.fast_index.boundaries and idx.fast_index.boundaries.document):
                raise RuntimeError(_DOC_BOUNDS_MISSING)
            doc_bounds = idx.fast_index.boundaries.document._positions
            if doc_bounds.size == 0:
                raise RuntimeError(_DOC_BOUNDS_EMPTY)
            if docset_mask.size < doc_bounds.size:
                raise RuntimeError(_DOCSET_MASK_MISMATCH)
            if match_lengths is not None:
                positions, match_lengths = filter_positions_and_values_by_docset_fast(
                    positions,
                    match_lengths,
                    doc_bounds,
                    docset_mask,
                )
            else:
                positions = filter_positions_by_docset_fast(
                    positions,
                    doc_bounds,
                    docset_mask,
                )
        if count_cb is not None and positions_are_full and not count_reported:
            try:
                count_cb(int(positions.size))
            except Exception:
                _LOGGER.exception("run_query: count callback failed")
        if offset:
            positions = positions[int(offset):]
            if match_lengths is not None:
                match_lengths = match_lengths[int(offset):]
        if limit is not None:
            positions = positions[: int(limit)]
            if match_lengths is not None:
                match_lengths = match_lengths[: int(limit)]
        if match_len_const is not None:
            kwic_positions = positions
            if pivot_index:
                kwic_positions = (positions.astype(np.int64, copy=False) + int(pivot_index)).astype(
                    np.uint32, copy=False
                )
            include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
            rows = idx.fast_index.kwic_rows_for_positions(
                kwic_positions, ctx, include_arcs=include_arcs, include_file=include_file
            )
            if match_len_const > 1:
                fixed_offsets = [
                    idx_off - int(pivot_index)
                    for idx_off in range(int(match_len_const))
                    if idx_off != int(pivot_index)
                ]
                for row in rows:
                    row["match_offsets"] = fixed_offsets
                    yield row
            else:
                for row in rows:
                    yield row
        elif match_lengths is not None:
            include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
            rows = idx.fast_index.kwic_rows_for_positions(
                positions, ctx, include_arcs=include_arcs, include_file=include_file
            )
            if pivot_index == 0:
                offsets_cache: dict[int, list[int]] = {}
                for row, match_len in zip(rows, match_lengths.tolist()):
                    match_len_i = int(match_len)
                    if match_len_i <= 1:
                        yield row
                        continue
                    fixed_offsets = offsets_cache.get(match_len_i)
                    if fixed_offsets is None:
                        fixed_offsets = [idx for idx in range(1, match_len_i)]
                        offsets_cache[match_len_i] = fixed_offsets
                    row["match_offsets"] = fixed_offsets
                    yield row
            else:
                for row, match_len in zip(rows, match_lengths.tolist()):
                    yield _apply_cql_span_to_row(row, int(match_len), pivot_index)
        else:
            include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
            rows = idx.fast_index.kwic_rows_for_positions(
                positions, ctx, include_arcs=include_arcs, include_file=include_file
            )
            for row in rows:
                yield row
        return

    try:
        node = parse_query(term_str)
    except Exception as exc:
        raise RuntimeError(
            lt("Query Parser Fehler: {error}", "Query parser error: {error}").format(
                error=exception_text(exc)
            )
        ) from exc

    if isinstance(node, Dependency):
        head_word = None
        dep_word = None
        head_attr = None
        dep_attr = None
        if isinstance(node.head, Term):
            head_word = node.head.value
        elif isinstance(node.head, Attr):
            head_attr = (node.head.key, node.head.value)
        if isinstance(node.dep, Term):
            dep_word = node.dep.value
        elif isinstance(node.dep, Attr):
            dep_attr = (node.dep.key, node.dep.value)
        rows = idx.query_dependency(
            rel=node.rel,
            head_word=head_word,
            dep_word=dep_word,
            head_attr=head_attr,
            dep_attr=dep_attr,
            ctx=ctx,
        )
        if docset_mask is None:
            if offset:
                rows = rows[int(offset):]
            if limit is not None:
                rows = rows[: int(limit)]
            for row in rows:
                yield row
            return
        if not (idx.fast_index.boundaries and idx.fast_index.boundaries.document):
            raise RuntimeError(_DOC_BOUNDS_MISSING)
        doc_bounds = idx.fast_index.boundaries.document._positions
        if doc_bounds.size == 0:
            raise RuntimeError(_DOC_BOUNDS_EMPTY)
        if docset_mask.size < doc_bounds.size:
            raise RuntimeError(_DOCSET_MASK_MISMATCH)
        skipped = 0
        yielded = 0
        for row in rows:
            pos = row.get("pos")
            if pos is None:
                continue
            doc_id = position_to_doc_id_fast(pos, doc_bounds)
            if doc_id < 0 or doc_id >= int(docset_mask.size) or not docset_mask[doc_id]:
                continue
            if offset and skipped < offset:
                skipped += 1
                continue
            yield row
            yielded += 1
            if limit is not None and yielded >= limit:
                break
        return

    # COPILOT-LBR-COUNT-01 (plain path): only the literal structural marker needs
    # the expensive prefetch/drop seam. Real simple tokens cannot resolve to the
    # line-break sentinel, so they stay on evaluate's bounded generator path.
    sentinel_id = linebreak_sentinel_word_id(idx)
    sentinel_pos: set[int] | None = None
    if sentinel_id > 0 and term_str == _LINEBREAK_MARKER:
        try:
            raw_positions = np.asarray(prefetch_positions(term_str, idx))
        except Exception:
            raw_positions = np.empty(0, dtype=np.uint32)
        if raw_positions.size:
            kept, _ = drop_linebreak_sentinel_positions(idx, raw_positions)
            if int(kept.size) != int(raw_positions.size):
                dropped = np.setdiff1d(raw_positions, kept, assume_unique=False)
                sentinel_pos = {int(p) for p in dropped.tolist()}

    if sentinel_pos is None:
        # No sentinel hit for this term -> nothing to filter; preserve the exact
        # prior generator (including evaluate's own count_cb wiring).
        yield from evaluate(
            node,
            idx,
            ctx,
            query=term,
            limit=limit,
            offset=offset,
            use_cache=use_cache,
            allow_cache_fallback=allow_cache_fallback,
            count_cb=count_cb,
            docset_mask=docset_mask,
        )
        return

    # Sentinel present: report the drop-corrected exact count via our own callback
    # (so the count equals the rows), then yield only non-sentinel rows. evaluate is
    # driven with offset=0/limit=None so OUR filter applies offset/limit AFTER the
    # drop, matching _prepare_plain_rows_fast.
    if count_cb is not None:
        try:
            count_cb(int(kept.size))
        except Exception:
            _LOGGER.exception("run_query: count callback failed")
    skipped = 0
    yielded = 0
    for row in evaluate(
        node,
        idx,
        ctx,
        query=term,
        limit=None,
        offset=0,
        use_cache=use_cache,
        allow_cache_fallback=allow_cache_fallback,
        count_cb=None,
        docset_mask=docset_mask,
    ):
        pos = row.get("pos")
        if pos is not None and int(pos) in sentinel_pos:
            continue
        if offset and skipped < offset:
            skipped += 1
            continue
        yield row
        yielded += 1
        if limit is not None and yielded >= limit:
            break


def run_query_list(
    term: str | None,
    ctx: int = 5,
    *,
    corpus: Optional[CorpusIndex] = None,
    lang: str = "en",
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    docset_mask: np.ndarray | None = None,
    include_file: bool = True,
    compact_rows: bool = False,
) -> list[Dict[str, str]]:
    """Return query rows eagerly for hot API paths.

    Dict rows carry the original spacing like :func:`run_query`. Compact tuple
    rows stay space-joined, the endpoints render them after enrichment.
    """
    rows = _run_query_list_rows(
        term,
        ctx,
        corpus=corpus,
        lang=lang,
        limit=limit,
        offset=offset,
        use_cache=use_cache,
        allow_cache_fallback=allow_cache_fallback,
        count_cb=count_cb,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
        include_file=include_file,
        compact_rows=compact_rows,
    )
    if not compact_rows and rows:
        apply_source_spacing_rows(rows, corpus or _CORPUS_INDEX)
    return rows


def _run_query_list_rows(
    term: str | None,
    ctx: int = 5,
    *,
    corpus: Optional[CorpusIndex] = None,
    lang: str = "en",
    limit: int | None = None,
    offset: int = 0,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    docset_mask: np.ndarray | None = None,
    include_file: bool = True,
    compact_rows: bool = False,
) -> list[Dict[str, str]]:
    """The rows of :func:`run_query_list` in the legacy space-joined form."""

    if term is None:
        return []

    offset = max(0, int(offset))
    idx = corpus or _CORPUS_INDEX
    if idx is None:
        raise RuntimeError(
            "Kein Korpus gesetzt. Bitte set_corpus nutzen oder corpus übergeben."
        )

    term_str = normalize_query_input(normalize_text_basic(term or ""))
    if not term_str.lower().startswith("cql:"):
        return list(
            run_query(
                term,
                ctx=ctx,
                corpus=idx,
                lang=lang,
                limit=limit,
                offset=offset,
                use_cache=use_cache,
                allow_cache_fallback=allow_cache_fallback,
                count_cb=count_cb,
                progress_cb=progress_cb,
                docset_mask=docset_mask,
                include_file=include_file,
            )
        )

    query = term_str[4:].strip()
    if not query:
        return []
    from .cql_engine import normalize_cql_aliases

    query = normalize_cql_aliases(query)
    pivot_index = _cql_pivot_index(query)
    if use_cache is None:
        use_cache = _CQL_CACHE_ENABLED
    count_reported = False
    limit_total = None if limit is None else int(offset) + int(limit)
    max_matches = _CQL_RESULTS_MAX if limit_total is None else limit_total
    if count_cb is not None and limit_total is not None and docset_mask is None:
        try:
            count_reported = _report_exact_cql_count(
                count_cb,
                idx,
                query,
                progress_cb=progress_cb,
                log_context="run_query_list",
            )
        except Exception:
            _LOGGER.exception("run_query_list: count callback failed")
    positions, match_len_const, match_lengths, positions_are_full = _resolve_cql_match_arrays(
        idx,
        query,
        max_matches=max_matches,
        use_cache=bool(use_cache),
        allow_cache_fallback=allow_cache_fallback,
        exhaustive=limit_total is None,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    # Drop the |LBR| sentinel from the FULL match set (shared seam) so the eager
    # row list and the count_cb below agree with the REST/streaming rows path.
    positions, match_lengths = drop_linebreak_sentinel_positions(
        idx, positions, match_lengths=match_lengths
    )
    if positions.size == 0:
        if count_cb is not None and positions_are_full and not count_reported:
            try:
                count_cb(0)
            except Exception:
                _LOGGER.exception("run_query_list: count callback failed")
        return []
    if docset_mask is not None and positions.size:
        if not (idx.fast_index.boundaries and idx.fast_index.boundaries.document):
            raise RuntimeError(_DOC_BOUNDS_MISSING)
        doc_bounds = idx.fast_index.boundaries.document._positions
        if doc_bounds.size == 0:
            raise RuntimeError(_DOC_BOUNDS_EMPTY)
        if docset_mask.size < doc_bounds.size:
            raise RuntimeError(_DOCSET_MASK_MISMATCH)
        if match_lengths is not None:
            positions, match_lengths = filter_positions_and_values_by_docset_fast(
                positions,
                match_lengths,
                doc_bounds,
                docset_mask,
            )
        else:
            positions = filter_positions_by_docset_fast(
                positions,
                doc_bounds,
                docset_mask,
            )
    if count_cb is not None and positions_are_full and not count_reported:
        try:
            count_cb(int(positions.size))
        except Exception:
            _LOGGER.exception("run_query_list: count callback failed")
    if offset:
        positions = positions[int(offset):]
        if match_lengths is not None:
            match_lengths = match_lengths[int(offset):]
    if limit is not None:
        positions = positions[: int(limit)]
        if match_lengths is not None:
            match_lengths = match_lengths[: int(limit)]
    if match_len_const is not None:
        kwic_positions = positions
        if pivot_index:
            kwic_positions = (positions.astype(np.int64, copy=False) + int(pivot_index)).astype(
                np.uint32, copy=False
            )
        include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
        rows = _kwic_rows_for_positions_fast(
            idx.fast_index,
            kwic_positions,
            ctx,
            include_arcs=include_arcs,
            include_file=include_file,
            compact_rows=compact_rows,
        )
        if match_len_const > 1:
            fixed_offsets = [
                idx_off - int(pivot_index)
                for idx_off in range(int(match_len_const))
                if idx_off != int(pivot_index)
            ]
            for idx_row, row in enumerate(rows):
                if compact_rows and isinstance(row, tuple):
                    rows[idx_row] = row + (fixed_offsets,)
                else:
                    row["match_offsets"] = fixed_offsets
        return rows
    if match_lengths is not None:
        include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
        rows = _kwic_rows_for_positions_fast(
            idx.fast_index,
            positions,
            ctx,
            include_arcs=include_arcs,
            include_file=include_file,
            compact_rows=compact_rows,
        )
        if pivot_index == 0:
            offsets_cache: dict[int, list[int]] = {}
            for idx_row, (row, match_len) in enumerate(zip(rows, match_lengths.tolist())):
                match_len_i = int(match_len)
                if match_len_i <= 1:
                    continue
                fixed_offsets = offsets_cache.get(match_len_i)
                if fixed_offsets is None:
                    fixed_offsets = [idx for idx in range(1, match_len_i)]
                    offsets_cache[match_len_i] = fixed_offsets
                if compact_rows and isinstance(row, tuple):
                    rows[idx_row] = row + (fixed_offsets,)
                else:
                    row["match_offsets"] = fixed_offsets
            return rows
        return [
            _apply_cql_span_to_row(row, int(match_len), pivot_index)
            for row, match_len in zip(rows, match_lengths.tolist())
        ]
    include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
    rows = _kwic_rows_for_positions_fast(
        idx.fast_index,
        positions,
        ctx,
        include_arcs=include_arcs,
        include_file=include_file,
        compact_rows=compact_rows,
    )
    return rows


def kwic(index_path: str, term: str, ctx: int = 5) -> list[Dict[str, str | int]]:
    """Return KWIC rows from a binary index created by the Fast Index builder."""
    backend = FastIndexBackend(Path(index_path))
    return backend.kwic_rows(term, ctx)
