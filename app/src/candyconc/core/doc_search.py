from __future__ import annotations

from typing import List, Dict
import numpy as np

from .corpus_index import CorpusIndex
from .fast_index_native import doc_search_scores
from .meta_filters import metadata_mask
from candyconc.utils.text_normalize import normalize_index_display_text


def _u32_writeable(arr: np.ndarray) -> np.ndarray:
    out = np.asarray(arr, dtype=np.uint32)
    if not out.flags.writeable:
        out = np.array(out, copy=True)
    return out


def document_search(
    index: CorpusIndex,
    term: str,
    *,
    top_n: int = 5,
    snippet: int = 30,
    metric: str | None = None,
    date: str | None = None,
    genre: str | None = None,
    metadata_filters: dict[str, object] | None = None,
) -> List[Dict[str, object]]:
    """Return ranked documents containing ``term`` with short snippets.

    Each result dictionary has the keys ``"doc_id"``, ``"file"``, ``"score"``,
    ``"snippet"`` and ``"pos"`` (the position of the first match).

    Parameters
    ----------
    index:
        Open :class:`CorpusIndex` to search.
    term:
        Term or phrase to look for (case-sensitive). Multiple words are
        treated as an ``AND`` query.
    top_n:
        Number of documents to return.
    snippet:
        Number of surrounding tokens to include in the snippet.
    metric:
        Ranking metric, ``"tf"``, ``"tf-idf"`` or ``"bm25"``. Defaults to
        ``index.ranking_metric`` when ``None``.
    date:
        Optional date metadata filter.
    genre:
        Optional genre metadata filter.
    metadata_filters:
        Optional generic metadata filters. ``date`` and ``genre`` are merged
        into this mapping for backwards compatibility.
    """
    metric = metric or getattr(index, "ranking_metric", "tf")

    tokens = [t for t in term.split() if t]
    if not tokens:
        return []

    fast = index.fast_index
    positions_list: list[np.ndarray] = []
    for tok in tokens:
        positions = fast.term_positions(tok, attr="word")
        if positions.size == 0:
            return []
        positions_list.append(_u32_writeable(positions))

    doc_bounds = (
        fast.boundaries.document._positions
        if fast.boundaries and fast.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    token_count = fast.token_store.token_count
    if doc_bounds.size == 0:
        doc_count = 1
    else:
        doc_count = int(doc_bounds.size)

    # Der ROHE Filter entscheidet, OB eine Maske gebaut wird, nicht der
    # kanonisierte. Die Vorfassung kanonisierte zuerst und rief die Maske
    # nur, wenn danach noch etwas uebrig war: ein Filter, der zu nichts
    # normalisiert (unbekanntes Feld, Leerraumwert), verschwand damit
    # VOR dem Waechter in metadata_mask, und die Suche lief ungefiltert
    # ueber den ganzen Korpus. Genau die Klasse, gegen die der Waechter
    # gebaut ist, an einem Eingang, der ihn nie erreichte.
    #
    # metadata_mask kanonisiert selbst und prueft in der Reihenfolge
    # Form, Feld, Kurzschluss.
    roh: dict = dict(metadata_filters or {})
    if str(date or "").strip():
        roh.setdefault("date", date)
    if str(genre or "").strip():
        roh.setdefault("genre", genre)
    meta_mask = metadata_mask(fast, roh, doc_count=doc_count) if roh else None

    doc_bounds_u32 = _u32_writeable(doc_bounds)
    doc_ids, scores, first_pos = doc_search_scores(
        positions_list,
        doc_bounds_u32,
        int(token_count),
        metric,
        meta_mask,
    )

    if doc_ids.size == 0:
        return []

    results = []
    half = snippet // 2
    positions_u32 = np.asarray(first_pos, dtype=np.uint32)
    snippet_rows = fast.kwic_rows_for_positions(
        positions_u32,
        half,
        include_arcs=False,
    )
    row_by_pos = {int(r.get("pos", -1)): r for r in snippet_rows}
    for doc_id, score, pos in zip(doc_ids, scores, first_pos):
        row = row_by_pos.get(int(pos))
        if row is not None:
            snippet_text = " ".join(
                [str(row.get("left", "")), str(row.get("kw", "")), str(row.get("right", ""))]
            ).strip()
            snippet_text = normalize_index_display_text(snippet_text)
        else:
            snippet_text = ""
        path = fast.doc_path_for_idx(int(doc_id))
        results.append(
            {
                "doc_id": int(doc_id),
                "file": path,
                "score": float(score),
                "snippet": snippet_text,
                "pos": int(pos),
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n]


__all__ = ["document_search"]


def document_search_native(*args, **kwargs):
    return document_search(*args, **kwargs)


__all__.append("document_search_native")
