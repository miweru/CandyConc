"""Materialize document metadata with a cache owned by each index.

Normalize document labels and enrich rows without importing server or
routes. Server-owned compact-row builders resolve their metadata lookup
through the server namespace so existing overrides remain effective."""

import threading
from collections import OrderedDict
from typing import Any, Dict

import numpy as np

from candyconc.core.corpus_index import CorpusIndex
from candyconc.i18n import lt
from candyconc.core.counting_kernels import map_positions_to_doc_ids_fast


def _parse_file_label(file_label: str | None) -> dict[str, str]:
    if not file_label:
        return {}
    label = str(file_label)
    parts = label.split("::")
    head = parts[0]
    out: dict[str, str] = {"path": label}
    if ":" in head:
        source, _hash = head.split(":", 1)
        if source:
            out["source"] = source
    elif head:
        out["source"] = head
    if len(parts) > 1 and parts[1] and parts[1].lower() not in {"source", "na"}:
        out["variant"] = parts[1]
    if len(parts) > 2 and parts[2] and parts[2].lower() != "na":
        out["model"] = parts[2]
    return out


def _stringify_meta(meta: Dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in meta.items():
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            vals: list[str] = []
            for value in raw:
                if value is None:
                    continue
                value_str = str(value)
                if value_str:
                    vals.append(value_str)
            if not vals:
                continue
            out[str(key)] = ", ".join(vals)
            continue
        out[str(key)] = str(raw)
    return out


_DOC_META_SHARED_CACHE_ATTR = "_doc_meta_string_cache"
_DOC_META_SHARED_CACHE_LIMIT = 65536
_MetadataFilterMaskKey = tuple[int, str, str, str]
_METADATA_FILTER_MASK_CACHE: "OrderedDict[_MetadataFilterMaskKey, np.ndarray]" = OrderedDict()
_METADATA_FILTER_MASK_CACHE_LIMIT = 64
_METADATA_FILTER_MASK_CACHE_LOCK = threading.RLock()


def _metadata_filter_mask_cache_get(key: _MetadataFilterMaskKey) -> np.ndarray | None:
    with _METADATA_FILTER_MASK_CACHE_LOCK:
        cached = _METADATA_FILTER_MASK_CACHE.get(key)
        if cached is not None:
            _METADATA_FILTER_MASK_CACHE.move_to_end(key)
        return cached


def _metadata_filter_mask_cache_set(
    key: _MetadataFilterMaskKey,
    mask: np.ndarray,
) -> np.ndarray:
    mask.setflags(write=False)
    with _METADATA_FILTER_MASK_CACHE_LOCK:
        _METADATA_FILTER_MASK_CACHE[key] = mask
        _METADATA_FILTER_MASK_CACHE.move_to_end(key)
        while len(_METADATA_FILTER_MASK_CACHE) > _METADATA_FILTER_MASK_CACHE_LIMIT:
            _METADATA_FILTER_MASK_CACHE.popitem(last=False)
    return mask


def _metadata_filter_mask_cache_clear() -> None:
    with _METADATA_FILTER_MASK_CACHE_LOCK:
        _METADATA_FILTER_MASK_CACHE.clear()


def _shared_doc_meta_cache(
    idx: CorpusIndex,
) -> dict[int, tuple[str, dict[str, str]]]:
    fast = idx.fast_index
    cache = getattr(fast, _DOC_META_SHARED_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(fast, _DOC_META_SHARED_CACHE_ATTR, cache)
    return cache


def _build_doc_meta_entry(
    idx: CorpusIndex,
    doc_id: int,
    *,
    file_label: str | None = None,
) -> tuple[str, dict[str, str]]:
    fast = idx.fast_index
    if not file_label:
        prepared = getattr(fast.doc_metadata, "prepared_entry", None)
        if callable(prepared):
            doc_label, merged = prepared(int(doc_id))
            if doc_label:
                return doc_label, merged
    meta_raw = fast.doc_metadata.get(int(doc_id), {}) if fast.doc_metadata else {}
    if isinstance(meta_raw, dict) and not file_label:
        doc_label = str(meta_raw.get("path") or "")
        merged = _stringify_meta(meta_raw)
        if doc_label and not any(key in merged for key in ("source", "variant", "model")):
            parsed = _parse_file_label(doc_label)
            for key, value in parsed.items():
                merged.setdefault(key, value)
        if "doc_id" not in merged:
            merged["doc_id"] = str(int(doc_id))
        if doc_label:
            if "path" not in merged:
                merged["path"] = doc_label
            return doc_label, merged
        doc_label = str(fast.doc_path_for_idx(int(doc_id)))
        if doc_label:
            merged.setdefault("path", doc_label)
        return doc_label, merged
    parsed = _parse_file_label(file_label or (meta_raw.get("path") if isinstance(meta_raw, dict) else None))
    merged: dict[str, Any] = {}
    merged.update(parsed)
    if isinstance(meta_raw, dict):
        merged.update({k: v for k, v in meta_raw.items() if v is not None})
    merged.setdefault("doc_id", int(doc_id))
    doc_label = ""
    if isinstance(meta_raw, dict):
        doc_label = str(meta_raw.get("path") or "")
    if not doc_label:
        doc_label = str(file_label or fast.doc_path_for_idx(int(doc_id)))
    merged.setdefault("path", doc_label)
    return doc_label, _stringify_meta(merged)


def _shared_doc_meta_for_doc_id(
    idx: CorpusIndex,
    doc_id: int,
) -> tuple[str, dict[str, str]]:
    cache = _shared_doc_meta_cache(idx)
    cached = cache.get(int(doc_id))
    if cached is not None:
        return cached
    entry = _build_doc_meta_entry(idx, int(doc_id))
    if len(cache) < _DOC_META_SHARED_CACHE_LIMIT:
        cache[int(doc_id)] = entry
    return entry


def _doc_meta_for_doc_id(
    idx: CorpusIndex,
    doc_id: int,
    *,
    file_label: str | None = None,
) -> tuple[str, dict[str, str]]:
    file_label = str(file_label or "") or None
    shared = _shared_doc_meta_for_doc_id(idx, int(doc_id))
    if file_label is None or file_label == shared[0]:
        return shared
    return _build_doc_meta_entry(idx, int(doc_id), file_label=file_label)


def _resolve_query_meta_lookup(
    idx: CorpusIndex,
    doc_ids: list[int],
    *,
    already_unique: bool = False,
) -> tuple[list[Any] | None, dict[int, tuple[str, dict[str, Any]]] | None]:
    doc_metadata = idx.fast_index.doc_metadata
    query_many = getattr(doc_metadata, "query_entries_many", None)
    query_cache = getattr(doc_metadata, "_query_cache", None)
    unique_doc_ids = doc_ids if already_unique else list(dict.fromkeys(doc_ids))
    if callable(query_many) and isinstance(query_cache, list):
        if getattr(doc_metadata, "_query_cache_complete", False):
            return query_cache, None
        missing_doc_ids = [
            doc_id
            for doc_id in unique_doc_ids
            if not (0 <= doc_id < len(query_cache) and query_cache[doc_id] is not None)
        ]
        if missing_doc_ids:
            resolved_missing = query_many(missing_doc_ids)
            for doc_id, prepared in zip(missing_doc_ids, resolved_missing):
                if 0 <= doc_id < len(query_cache):
                    query_cache[doc_id] = prepared
        return query_cache, None
    if callable(query_many) and isinstance(query_cache, dict):
        missing_doc_ids = [doc_id for doc_id in unique_doc_ids if doc_id not in query_cache]
        if missing_doc_ids:
            resolved_missing = query_many(missing_doc_ids)
            for doc_id, prepared in zip(missing_doc_ids, resolved_missing):
                query_cache[doc_id] = prepared
        return None, query_cache

    prepared_cache: dict[int, tuple[str, dict[str, Any]]] = {}
    prepared_many = getattr(doc_metadata, "prepared_entries_many", None)
    if callable(query_many):
        resolved_missing = query_many(unique_doc_ids)
    elif callable(prepared_many):
        resolved_missing = prepared_many(unique_doc_ids)
    else:
        resolved_missing = [_shared_doc_meta_for_doc_id(idx, int(doc_id)) for doc_id in unique_doc_ids]
    for doc_id, prepared in zip(unique_doc_ids, resolved_missing):
        prepared_cache[doc_id] = prepared
    return None, prepared_cache


def _enrich_rows_with_doc_meta(
    idx: CorpusIndex,
    rows: list[Any],
    *,
    doc_bounds: np.ndarray | None,
    token_count: int,
    cache: dict[tuple[int, str | None], tuple[str, dict[str, str]]],
    include_file: bool = True,
) -> None:
    if not rows or doc_bounds is None or doc_bounds.size == 0 or token_count <= 0:
        return
    positions = np.empty(len(rows), dtype=np.uint32)
    row_doc_ids = np.empty(len(rows), dtype=np.int32)
    valid_row_indices: list[int] = []
    valid_count = 0
    have_row_doc_ids = True
    for idx_row, row in enumerate(rows):
        if isinstance(row, tuple):
            pos = row[3] if len(row) > 3 else None
            if len(row) > 4 and isinstance(row[4], (int, np.integer)):
                row_doc_ids[valid_count] = np.int32(int(row[4]))
            else:
                have_row_doc_ids = False
        else:
            pos = row.get("pos")
            have_row_doc_ids = False
        if pos is None:
            continue
        pos_i = int(pos)
        if pos_i < 0 or pos_i >= token_count:
            continue
        positions[valid_count] = np.uint32(pos_i)
        valid_row_indices.append(idx_row)
        valid_count += 1
    if valid_count == 0:
        return
    valid_positions = positions[:valid_count]
    if have_row_doc_ids:
        doc_ids = row_doc_ids[:valid_count].astype(np.int32, copy=False)
    else:
        doc_ids = map_positions_to_doc_ids_fast(valid_positions, doc_bounds)
    if valid_count >= 64 and all(
        isinstance(rows[row_idx], tuple) or not rows[row_idx].get("file")
        for row_idx in valid_row_indices
    ):
        unique_doc_ids, inverse = np.unique(doc_ids, return_inverse=True)
        unique_doc_ids_list = unique_doc_ids.tolist()
        inverse_list = inverse.tolist()
        resolved: list[tuple[str, dict[str, str]]]
        query_many = getattr(idx.fast_index.doc_metadata, "query_entries_many", None)
        prepared_many = getattr(idx.fast_index.doc_metadata, "prepared_entries_many", None)
        if callable(query_many):
            resolved = query_many(unique_doc_ids_list)
        elif callable(prepared_many):
            resolved = prepared_many(unique_doc_ids_list)
        else:
            resolved = []
            for doc_id in unique_doc_ids_list:
                cache_key = (doc_id, None)
                cached = cache.get(cache_key)
                if cached is None:
                    cached = _shared_doc_meta_for_doc_id(idx, doc_id)
                    cache[cache_key] = cached
                resolved.append(cached)
        for idx_pos in range(valid_count):
            row_idx = valid_row_indices[idx_pos]
            row = rows[row_idx]
            doc_id = int(doc_ids[idx_pos])
            doc_label, meta = resolved[inverse_list[idx_pos]]
            if isinstance(row, tuple):
                enriched = {
                    "left": row[0],
                    "kw": row[1],
                    "right": row[2],
                    "pos": int(row[3]),
                    "doc_id": doc_id,
                    "doc": doc_label,
                    "meta": meta,
                }
                if len(row) > 5:
                    enriched["match_offsets"] = row[5]
                if include_file:
                    enriched["file"] = doc_label
                rows[row_idx] = enriched
            else:
                row["doc_id"] = doc_id
                row["doc"] = doc_label
                if include_file:
                    row["file"] = doc_label
                row["meta"] = meta
        return
    for idx_pos in range(valid_count):
        row_idx = valid_row_indices[idx_pos]
        row = rows[row_idx]
        doc_id = int(doc_ids[idx_pos])
        file_value = None if isinstance(row, tuple) else row.get("file")
        file_label = str(file_value) if file_value else None
        cache_key = (int(doc_id), file_label)
        cached = cache.get(cache_key)
        if cached is None:
            cached = _doc_meta_for_doc_id(idx, int(doc_id), file_label=file_label)
            cache[cache_key] = cached
        doc_label, meta = cached
        if isinstance(row, tuple):
            enriched = {
                "left": row[0],
                "kw": row[1],
                "right": row[2],
                "pos": int(row[3]),
                "doc_id": int(doc_id),
                "doc": doc_label,
                "meta": meta,
            }
            if len(row) > 5:
                enriched["match_offsets"] = row[5]
            if include_file:
                enriched["file"] = doc_label
            rows[row_idx] = enriched
        else:
            row["doc_id"] = int(doc_id)
            row["doc"] = doc_label
            if include_file and not row.get("file"):
                row["file"] = doc_label
            row["meta"] = meta


def _doc_count_for_index(idx: CorpusIndex) -> int:
    doc_bounds = (
        idx.fast_index.boundaries.document._positions
        if idx.fast_index.boundaries and idx.fast_index.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    if doc_bounds.size == 0:
        raise RuntimeError(
            lt("Dokumentgrenzen fehlen. Bitte Index neu bauen.", "Document boundaries are missing. Rebuild the index.")
        )
    return int(doc_bounds.size)
