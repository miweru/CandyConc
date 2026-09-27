"""Co-occurrence windows of a node and one or more collocates.

One definition serves the collocation back path (``/analysis/collocates/kwic``),
``co(...)`` terms in dispersion and the other analyses, and the collocate job
that is anchored on a co-occurrence. It is the window the collocation engine
unions into W(u):

* A node hit covers ``[s, e)``. Its window is ``[l, s)`` and ``[e, r)`` with
  ``l = max(s - w, unit start)`` and ``r = min(e + w, unit end)``. The unit is
  the document, with ``within_sentence`` the sentence inside the document
  (``BoundarySet.clip_bounds_array``, the bounds the coverage sweep clips at).
* The node resolves like the collocation table: a plain term as the case-folded
  class on the counting attribute (``word`` or ``lemma``), a ``cql:`` term as
  the match spans.
* A collocate resolves like a collocation row: the exact value on the counting
  attribute (the table keeps surface forms apart, ``collocate_case_policy:
  surface_form``).

``collocate_tokens`` counts the distinct collocate tokens inside the union of
all node windows. For a collocate that the engine ranks this is the row's O11.
The node hits whose own window holds the collocate are the concordance rows.
The two numbers differ when one collocate token lies in the windows of two
node hits, or two collocate tokens lie in the window of one node hit.

This module must not import ``candyconc.services.backend.server``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from candyconc.core.corpus_index import CorpusIndex
from candyconc.i18n import lt
from candyconc.core.counting_kernels import (
    filter_positions_and_values_by_docset_fast,
    filter_positions_by_docset_fast,
)

ATTRIBUTES = ("word", "lemma")


@dataclass
class CoOccurrence:
    node_positions: np.ndarray
    node_spans: np.ndarray
    left: np.ndarray
    right: np.ndarray
    collocates: list[str]
    collocate_positions: list[np.ndarray]
    co_mask: np.ndarray
    collocate_tokens: dict[str, int] = field(default_factory=dict)

    @property
    def node_hits(self) -> int:
        return int(self.node_positions.size)

    @property
    def rows(self) -> np.ndarray:
        return self.node_positions[self.co_mask]

    @property
    def row_spans(self) -> np.ndarray:
        return self.node_spans[self.co_mask]


def _empty(collocates: list[str]) -> CoOccurrence:
    z32 = np.zeros(0, dtype=np.uint32)
    z64 = np.zeros(0, dtype=np.int64)
    return CoOccurrence(
        node_positions=z32,
        node_spans=z64,
        left=z64,
        right=z64,
        collocates=list(collocates),
        collocate_positions=[z32 for _ in collocates],
        co_mask=np.zeros(0, dtype=bool),
        collocate_tokens={c: 0 for c in collocates},
    )


def _lexicon(idx: CorpusIndex, attribute: str):
    lexicons = getattr(idx.fast_index, "lexicons", None)
    return getattr(lexicons, attribute, None) if lexicons is not None else None


def node_positions(
    idx: CorpusIndex,
    term: str,
    *,
    attribute: str = "word",
    within_sentence: bool = True,
    match_limit: int = 2_147_483_647,
) -> tuple[np.ndarray, np.ndarray]:
    """Sorted node hits ``(starts, spans)`` for ``term``."""
    from candyconc.core.cql_macros import normalize_query_input

    term = normalize_query_input((term or "").strip())
    if not term:
        return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64)
    if term.lower().startswith("cql:"):
        q = term[4:].strip()
        if not q:
            return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64)
        from candyconc.core.cql_engine import search_cql_matches_backend

        matches = search_cql_matches_backend(
            idx.fast_index,
            q,
            limit=int(match_limit),
            within_sentences_by_default=within_sentence,
        )
        if not matches:
            return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64)
        starts = np.array([m.start for m in matches], dtype=np.uint32)
        spans = np.array(
            [max(1, int(getattr(m, "end", int(m.start) + 1)) - int(m.start)) for m in matches],
            dtype=np.int64,
        )
        if starts.size > 1:
            order = np.argsort(starts, kind="mergesort")
            starts = starts[order]
            spans = spans[order]
        return starts, spans
    if attribute == "lemma":
        ids = idx._casefold_ids(term, attr="lemma")
        if ids.size == 0:
            return np.zeros(0, dtype=np.uint32), np.zeros(0, dtype=np.int64)
        starts = idx.fast_index._union_positions_for_ids("lemma", ids).astype(np.uint32, copy=False)
    else:
        lookup = getattr(idx, "term_positions", None)
        try:
            starts = lookup(term, case_insensitive=True).astype(np.uint32, copy=False)
        except TypeError:
            starts = idx.fast_index.term_positions(term, attr="word").astype(np.uint32, copy=False)
    return starts, np.ones(starts.shape[0], dtype=np.int64)


def collocate_positions(idx: CorpusIndex, value: str, *, attribute: str = "word") -> np.ndarray:
    """Positions of the exact ``value`` on the counting attribute."""
    value = (value or "").strip()
    if not value:
        return np.zeros(0, dtype=np.uint32)
    if _lexicon(idx, attribute) is None:
        return np.zeros(0, dtype=np.uint32)
    return np.asarray(
        idx.fast_index.term_positions(value, attr=attribute), dtype=np.uint32
    )


_SENTENCE_BOUNDS_MISSING = lt(
    "Satzgrenzen fehlen. Bitte Index mit Satzgrenzen bauen.",
    "Sentence boundaries are missing. Build the index with sentence boundaries.",
)


def _clip_bounds(idx: CorpusIndex, within_sentence: bool) -> np.ndarray | None:
    boundaries = idx.fast_index.boundaries
    if boundaries is None:
        if within_sentence:
            raise RuntimeError(_SENTENCE_BOUNDS_MISSING)
        return None
    bounds = boundaries.clip_bounds_array(bool(within_sentence))
    if bounds is None or bounds.size == 0:
        if within_sentence:
            raise RuntimeError(_SENTENCE_BOUNDS_MISSING)
        return None
    return np.asarray(bounds, dtype=np.int64)


def node_windows(
    idx: CorpusIndex,
    starts: np.ndarray,
    spans: np.ndarray,
    *,
    window: int,
    within_sentence: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Window limits ``(l, r)`` per node hit, clipped like the coverage sweep."""
    total = int(idx.fast_index.token_store.token_count)
    s = starts.astype(np.int64, copy=False)
    e = s + spans.astype(np.int64, copy=False)
    left = s - int(window)
    right = e + int(window)
    bounds = _clip_bounds(idx, within_sentence)
    if bounds is not None and s.size:
        unit = np.searchsorted(bounds, s, side="right")
        unit_start = np.where(unit > 0, bounds[np.clip(unit - 1, 0, bounds.size - 1)], 0)
        unit_end = np.where(unit < bounds.size, bounds[np.clip(unit, 0, bounds.size - 1)], total)
        left = np.maximum(left, unit_start)
        right = np.minimum(right, unit_end)
    left = np.maximum(left, 0)
    right = np.minimum(right, total)
    return left.astype(np.int64, copy=False), right.astype(np.int64, copy=False)


def _in_window_counts(
    coll: np.ndarray, starts: np.ndarray, ends: np.ndarray, left: np.ndarray, right: np.ndarray
) -> np.ndarray:
    """Collocate tokens in ``[l, s)`` plus ``[e, r)`` per node hit."""
    left_part = np.searchsorted(coll, starts, side="left") - np.searchsorted(coll, left, side="left")
    right_part = np.searchsorted(coll, right, side="left") - np.searchsorted(coll, ends, side="left")
    return np.maximum(left_part, 0) + np.maximum(right_part, 0)


def _union_count(coll: np.ndarray, starts: np.ndarray, ends: np.ndarray, left: np.ndarray, right: np.ndarray) -> int:
    """Distinct collocate positions inside the union W(u) of all node windows.

    Same union as the coverage sweep: every ``[l, s)`` and ``[e, r)``
    interval, overlapping intervals merged, each position counted once.
    """
    if coll.size == 0 or starts.size == 0:
        return 0
    delta = np.zeros(coll.size + 1, dtype=np.int64)
    for lo_arr, hi_arr in ((left, starts), (ends, right)):
        lo = np.searchsorted(coll, lo_arr, side="left")
        hi = np.searchsorted(coll, hi_arr, side="left")
        keep = hi > lo
        if np.any(keep):
            np.add.at(delta, lo[keep], 1)
            np.add.at(delta, hi[keep], -1)
    return int(np.count_nonzero(np.cumsum(delta[:-1]) > 0))


def co_occurrence(
    idx: CorpusIndex,
    term: str,
    collocates: list[str],
    *,
    window: int,
    within_sentence: bool,
    attribute: str = "word",
    docset_mask: np.ndarray | None = None,
    doc_bounds: np.ndarray | None = None,
    match_limit: int = 2_147_483_647,
) -> CoOccurrence:
    """Node hits of ``term`` with every collocate inside the node window."""
    attribute = attribute if attribute in ATTRIBUTES else "word"
    collocates = [c for c in (collocates or []) if str(c).strip()]
    if not collocates:
        return _empty([])
    starts, spans = node_positions(
        idx, term, attribute=attribute, within_sentence=within_sentence, match_limit=match_limit
    )
    coll_list = [collocate_positions(idx, c, attribute=attribute) for c in collocates]
    if docset_mask is not None:
        if doc_bounds is None:
            doc_bounds = idx.fast_index.boundaries.document._positions
        if starts.size:
            starts, spans = filter_positions_and_values_by_docset_fast(
                starts.astype(np.uint32, copy=False), spans, doc_bounds, docset_mask
            )
        coll_list = [
            filter_positions_by_docset_fast(c, doc_bounds, docset_mask) if c.size else c
            for c in coll_list
        ]
    if starts.size == 0:
        out = _empty(collocates)
        out.collocate_positions = coll_list
        return out
    left, right = node_windows(idx, starts, spans, window=window, within_sentence=within_sentence)
    s64 = starts.astype(np.int64, copy=False)
    e64 = s64 + spans.astype(np.int64, copy=False)
    co_mask = np.ones(starts.shape[0], dtype=bool)
    tokens: dict[str, int] = {}
    for name, coll in zip(collocates, coll_list):
        coll64 = coll.astype(np.int64, copy=False)
        co_mask &= _in_window_counts(coll64, s64, e64, left, right) > 0
        tokens[name] = _union_count(coll64, s64, e64, left, right)
    return CoOccurrence(
        node_positions=starts.astype(np.uint32, copy=False),
        node_spans=spans.astype(np.int64, copy=False),
        left=left,
        right=right,
        collocates=collocates,
        collocate_positions=coll_list,
        co_mask=co_mask,
        collocate_tokens=tokens,
    )


def node_match_offsets(result: CoOccurrence, rows: np.ndarray) -> dict[int, list[int]]:
    """Offsets of the other tokens of each row's node hit, relative to the row start.

    A row starts at the first token of its node hit. A hit of ``n`` tokens has
    the offsets ``1 .. n-1``, the ``match_offsets`` of a ``/query`` row.
    """
    if rows.size == 0:
        return {}
    span_of = {int(p): int(n) for p, n in zip(result.node_positions.tolist(), result.node_spans.tolist())}
    return {int(pos): list(range(1, span_of.get(int(pos), 1))) for pos in rows.tolist()}


def collocate_offsets(result: CoOccurrence, rows: np.ndarray) -> dict[int, list[int]]:
    """Offsets of the collocate tokens in each row's window, relative to the row start."""
    if rows.size == 0:
        return {}
    idx_of = {int(p): i for i, p in enumerate(result.node_positions.tolist())}
    out: dict[int, list[int]] = {}
    for pos in rows.tolist():
        i = idx_of.get(int(pos))
        if i is None:
            continue
        s = int(result.node_positions[i])
        e = s + int(result.node_spans[i])
        lo = int(result.left[i])
        hi = int(result.right[i])
        offs: list[int] = []
        for coll in result.collocate_positions:
            a = int(np.searchsorted(coll, lo, side="left"))
            b = int(np.searchsorted(coll, hi, side="left"))
            for p in coll[a:b].tolist():
                if s <= int(p) < e:
                    continue
                offs.append(int(p) - s)
        out[int(pos)] = sorted(set(offs))
    return out
