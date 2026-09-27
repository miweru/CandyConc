"""KWIC row transforms with core-only dependencies.

Resolve line-break sentinels through core.query_runtime. Query and
rendering chains that depend on server-owned state remain with their
callers so server-namespace overrides continue to apply."""

from typing import Any

import numpy as np

from candyconc.core.corpus_index import CorpusIndex
from candyconc.i18n import lt
# Import the shared line-break sentinel rule from core.query_runtime so
# KWIC rendering agrees with query evaluation.
from candyconc.core.query_runtime import (
    drop_linebreak_sentinel_positions as _drop_linebreak_sentinel_positions,
)


def _doc_bounds_for_index(idx: CorpusIndex) -> np.ndarray:
    if not (idx.fast_index.boundaries and idx.fast_index.boundaries.document):
        raise RuntimeError(
            lt("Dokumentgrenzen fehlen. Bitte Index neu bauen.", "Document boundaries are missing. Rebuild the index.")
        )
    doc_bounds = idx.fast_index.boundaries.document._positions
    if doc_bounds.size == 0:
        raise RuntimeError(
            lt("Dokumentgrenzen leer. Bitte Index neu bauen.", "Document boundaries are empty. Rebuild the index.")
        )
    return doc_bounds.astype(np.uint32, copy=False)


def _apply_cql_two_token_pivot_one_rows(rows: list[dict[str, Any]]) -> None:
    shared_offsets = [-1]
    for row in rows:
        row["match_offsets"] = shared_offsets
        right = row["right"]
        if right:
            split_at = right.find(" ")
            if split_at < 0:
                next_kw = right
                rest = ""
            else:
                next_kw = right[:split_at]
                rest = right[split_at + 1 :]
            left = row["left"]
            cur_kw = row["kw"]
            if cur_kw:
                row["left"] = f"{left} {cur_kw}" if left else cur_kw
            row["kw"] = next_kw
            row["right"] = rest
        row["pos"] += 1


def _prepare_cql_rows_fast(
    idx: CorpusIndex,
    term: str,
    *,
    offset: int = 0,
    limit: int | None = None,
    docset_mask: np.ndarray | None = None,
) -> tuple[str, np.ndarray, int | None, np.ndarray | None, int, int, bool] | None:
    from candyconc.core.cql_macros import normalize_query_input
    from candyconc.core.cql_engine import normalize_cql_aliases
    from candyconc.core.query_runtime import (
        _CQL_RESULTS_MAX,
        _cql_pivot_index,
        _resolve_cql_match_arrays,
    )
    from candyconc.utils.text_normalize import normalize_text_basic

    term_str = normalize_query_input(normalize_text_basic(term or ""))
    if not term_str.lower().startswith("cql:"):
        return None
    query = normalize_cql_aliases(term_str[4:].strip())
    if not query:
        empty = np.empty(0, dtype=np.uint32)
        return query, empty, None, None, 0, 0, True
    pivot_index = _cql_pivot_index(query)

    limit_total = None if limit is None else int(offset) + int(limit)
    max_matches = _CQL_RESULTS_MAX if limit_total is None else limit_total
    positions, match_len_const, match_lengths, positions_are_full = _resolve_cql_match_arrays(
        idx,
        query,
        max_matches=max_matches,
        use_cache=True,
        allow_cache_fallback=True,
        exhaustive=limit_total is None,
        docset_mask=docset_mask,
    )
    # Exclude the index-only '|LBR|' line-break sentinel from word-matching, so
    # [word="|LBR|"] -> 0 hits and [word=".*"] yields no blank-node rows. Applied
    # to the FULL match set before total_matches/offset/limit so the count is
    # honest. Real words (and real punctuation) are untouched.
    positions, match_lengths = _drop_linebreak_sentinel_positions(
        idx, positions, match_lengths=match_lengths
    )
    total_matches = int(positions.size)
    if positions.size == 0:
        return query, positions, match_len_const, match_lengths, pivot_index, total_matches, positions_are_full
    if offset:
        positions = positions[int(offset):]
        if match_lengths is not None:
            match_lengths = match_lengths[int(offset):]
    if limit is not None:
        positions = positions[: int(limit)]
        if match_lengths is not None:
            match_lengths = match_lengths[: int(limit)]
    return query, positions, match_len_const, match_lengths, pivot_index, total_matches, positions_are_full
