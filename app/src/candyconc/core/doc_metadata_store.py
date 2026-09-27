from __future__ import annotations

import mmap
import os
import struct
import zlib
from pathlib import Path
from typing import Dict, Iterable, Iterator, Mapping, Tuple

import numpy as np

from . import index_format

try:
    import orjson as _orjson
except Exception:  # pragma: no cover - optional dependency
    _orjson = None
    import json as _json
else:
    _json = None


def _json_loads(raw: bytes):
    if _orjson is not None:
        return _orjson.loads(raw)
    assert _json is not None
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    return _json.loads(raw.decode("utf-8"))


_DOC_METADATA_CACHE_LIMIT = max(
    0,
    int(os.getenv("CANDYCONC_DOC_METADATA_CACHE_LIMIT", "65536")),
)
_DOC_METADATA_LIST_CACHE_MAX_SIZE = max(
    0,
    int(os.getenv("CANDYCONC_DOC_METADATA_LIST_CACHE_MAX_SIZE", "500000")),
)


def _load_array_with_count(path: Path, dtype: np.dtype) -> np.ndarray:
    with path.open("rb") as f:
        header = f.read(index_format.COUNT_HEADER_SIZE)
        if len(header) != index_format.COUNT_HEADER_SIZE:
            raise RuntimeError(f"doc_metadata offsets corrupt: {path}")
        (count,) = np.frombuffer(header, dtype=np.uint64, count=1)
        if int(count) <= 0:
            return np.zeros(0, dtype=dtype)
        data = np.fromfile(f, dtype=dtype, count=int(count))
    return data


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


def _stringify_meta(meta: Dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in meta.items():
        if raw is None:
            continue
        key_str = key if isinstance(key, str) else str(key)
        if isinstance(raw, str):
            if raw:
                out[key_str] = raw
            continue
        if isinstance(raw, int):
            out[key_str] = str(raw)
            continue
        if isinstance(raw, (list, tuple, set)):
            vals: list[str] = []
            for value in raw:
                if value is None:
                    continue
                if isinstance(value, str):
                    if value:
                        vals.append(value)
                    continue
                value_str = str(value)
                if value_str:
                    vals.append(value_str)
            if not vals:
                continue
            out[key_str] = ", ".join(vals)
            continue
        out[key_str] = str(raw)
    return out


def _prepared_meta_entry_from_raw_common(meta_raw: Dict[str, object], idx: int) -> Tuple[str, Dict[str, str]] | None:
    path = meta_raw.get("path")
    source = meta_raw.get("source")
    variant = meta_raw.get("variant")
    model = meta_raw.get("model")
    doc_id = meta_raw.get("doc_id")
    if not (
        isinstance(path, str)
        and path
        and isinstance(source, str)
        and source
        and isinstance(variant, str)
        and variant
        and isinstance(model, str)
        and model
        and isinstance(doc_id, (str, int))
    ):
        return None
    merged: dict[str, str] = {}
    for key, raw in meta_raw.items():
        if raw is None:
            continue
        if isinstance(raw, str):
            if raw:
                merged[key] = raw
            continue
        if isinstance(raw, int):
            merged[key] = str(raw)
            continue
        if isinstance(raw, list):
            if not raw:
                continue
            if len(raw) == 1:
                value = raw[0]
                if value is None:
                    continue
                if isinstance(value, str):
                    if value:
                        merged[key] = value
                    continue
                value_str = str(value)
                if value_str:
                    merged[key] = value_str
                continue
            vals: list[str] = []
            for value in raw:
                if value is None:
                    continue
                if isinstance(value, str):
                    if value:
                        vals.append(value)
                    continue
                value_str = str(value)
                if value_str:
                    vals.append(value_str)
            if vals:
                merged[key] = ", ".join(vals)
            continue
        return None
    if "doc_id" not in merged:
        merged["doc_id"] = str(int(idx))
    if "path" not in merged:
        merged["path"] = path
    return path, merged


def _prepared_meta_entry_from_raw(meta_raw: Dict, idx: int) -> Tuple[str, Dict[str, str]]:
    if meta_raw and all(isinstance(key, str) for key in meta_raw.keys()):
        fast_entry = _prepared_meta_entry_from_raw_common(meta_raw, idx)  # type: ignore[arg-type]
        if fast_entry is not None:
            return fast_entry
    merged: dict[str, str] = {}
    doc_label = ""
    has_source = False
    has_variant = False
    has_model = False
    has_doc_id = False
    has_path = False
    for key, raw in meta_raw.items():
        if raw is None:
            continue
        key_str = key if isinstance(key, str) else str(key)
        if key_str == "source":
            has_source = True
        elif key_str == "variant":
            has_variant = True
        elif key_str == "model":
            has_model = True
        elif key_str == "doc_id":
            has_doc_id = True
        elif key_str == "path":
            has_path = True
        if isinstance(raw, str):
            if not raw:
                continue
            merged[key_str] = raw
            if key_str == "path":
                doc_label = raw
            continue
        if isinstance(raw, int):
            value = str(raw)
            merged[key_str] = value
            if key_str == "path":
                doc_label = value
            continue
        if isinstance(raw, (list, tuple, set)):
            vals: list[str] = []
            for value in raw:
                if value is None:
                    continue
                if isinstance(value, str):
                    if value:
                        vals.append(value)
                    continue
                value_str = str(value)
                if value_str:
                    vals.append(value_str)
            if not vals:
                continue
            merged[key_str] = ", ".join(vals)
            continue
        value = str(raw)
        if not value:
            continue
        merged[key_str] = value
        if key_str == "path":
            doc_label = value
    if doc_label and not (has_source and has_variant and has_model):
        parsed = _parse_file_label(doc_label)
        if not has_source:
            source = parsed.get("source")
            if source:
                merged.setdefault("source", source)
        if not has_variant:
            variant = parsed.get("variant")
            if variant:
                merged.setdefault("variant", variant)
        if not has_model:
            model = parsed.get("model")
            if model:
                merged.setdefault("model", model)
    if not has_doc_id:
        merged["doc_id"] = str(int(idx))
    if doc_label and not has_path:
        merged["path"] = doc_label
    return doc_label, merged


def _query_meta_entry_from_raw(meta_raw: Dict, idx: int) -> Tuple[str, Dict[str, object]]:
    if not isinstance(meta_raw, dict):
        return "", {}
    doc_label_raw = meta_raw.get("path")
    doc_label = doc_label_raw if isinstance(doc_label_raw, str) else (str(doc_label_raw) if doc_label_raw else "")
    doc_id = meta_raw.get("doc_id")
    has_source = "source" in meta_raw
    has_variant = "variant" in meta_raw
    has_model = "model" in meta_raw
    if doc_label and isinstance(doc_id, str) and has_source and has_variant and has_model:
        return doc_label, meta_raw
    merged = dict(meta_raw)
    if doc_label and not (has_source and has_variant and has_model):
        parsed = _parse_file_label(doc_label)
        if not has_source and parsed.get("source"):
            merged["source"] = parsed["source"]
        if not has_variant and parsed.get("variant"):
            merged["variant"] = parsed["variant"]
        if not has_model and parsed.get("model"):
            merged["model"] = parsed["model"]
    if not isinstance(doc_id, str):
        merged["doc_id"] = str(int(idx) if doc_id is None else int(doc_id))
    if doc_label and "path" not in merged:
        merged["path"] = doc_label
    return doc_label, merged


class DocMetadataMMap(Mapping[int, Dict]):
    def __init__(self, base_path: Path) -> None:
        self._base_path = Path(base_path)
        idx_path = self._base_path / "doc_metadata.idx.bin"
        blob_path = self._base_path / "doc_metadata.mmap"
        crc_path = self._base_path / "doc_metadata.crc.bin"
        if not (idx_path.exists() and blob_path.exists()):
            raise RuntimeError("doc_metadata mmap fehlt.")
        self._offsets = _load_array_with_count(idx_path, np.uint64)
        if self._offsets.size < 2:
            raise RuntimeError("doc_metadata offsets ungültig.")
        self._doc_count = int(self._offsets.size - 1)
        self._blob_fh = blob_path.open("rb")
        self._blob = mmap.mmap(self._blob_fh.fileno(), 0, access=mmap.ACCESS_READ)
        self._blob_view = memoryview(self._blob)
        self._crc = None
        if crc_path.exists():
            self._crc = _load_array_with_count(crc_path, np.uint32)
        if 0 < self._doc_count <= _DOC_METADATA_LIST_CACHE_MAX_SIZE:
            self._cache = [None] * self._doc_count
            self._prepared_cache = [None] * self._doc_count
            self._query_cache = [None] * self._doc_count
        else:
            self._cache = {}
            self._prepared_cache = {}
            self._query_cache = {}
        self._query_cache_complete = False

    def __len__(self) -> int:
        return self._doc_count

    def __iter__(self) -> Iterator[int]:
        return iter(range(self._doc_count))

    def _corrupt(self, idx: int, reason: str) -> RuntimeError:
        return RuntimeError(
            f"doc_metadata korrupt ({reason}, doc {idx}) in {self._base_path}. "
            "Bitte Fast Index neu bauen."
        )

    def _read_one(self, idx: int) -> Dict:
        if idx < 0 or idx >= self._doc_count:
            return {}
        if isinstance(self._cache, list):
            cached = self._cache[idx]
            if cached is not None:
                return cached
        else:
            cached = self._cache.get(idx)
            if cached is not None:
                return cached
        start = int(self._offsets[idx])
        end = int(self._offsets[idx + 1])
        if end <= start:
            meta: Dict = {}
        else:
            raw = self._blob_view[start:end]
            if bytes(raw[:4]) == index_format.DOC_META_FRAME_MAGIC:
                if len(raw) < 12:
                    raise self._corrupt(idx, "Frame-Header abgeschnitten")
                length = struct.unpack("<I", raw[4:8])[0]
                crc = struct.unpack("<I", raw[8:12])[0]
                payload = raw[12:12 + length]
                if len(payload) != length:
                    raise self._corrupt(idx, "Payload abgeschnitten")
                if self._crc is not None:
                    try:
                        stored = int(self._crc[idx])
                    except Exception:
                        stored = 0
                else:
                    stored = int(crc)
                if stored != 0 and zlib.crc32(payload) != stored:
                    raise self._corrupt(idx, "CRC mismatch")
                try:
                    meta = _json_loads(payload)
                except Exception as exc:
                    raise self._corrupt(idx, "JSON nicht dekodierbar") from exc
            else:
                try:
                    meta = _json_loads(raw)
                except Exception as exc:
                    raise self._corrupt(idx, "JSON nicht dekodierbar") from exc
        if isinstance(self._cache, list):
            self._cache[idx] = meta
        elif len(self._cache) < _DOC_METADATA_CACHE_LIMIT:
            self._cache[idx] = meta
        return meta

    def prepared_entry(self, idx: int) -> Tuple[str, Dict[str, str]]:
        if idx < 0 or idx >= self._doc_count:
            return "", {}
        if isinstance(self._prepared_cache, list):
            cached = self._prepared_cache[idx]
            if cached is not None:
                return cached
        else:
            cached = self._prepared_cache.get(idx)
            if cached is not None:
                return cached
        meta_raw = self._read_one(idx)
        if not isinstance(meta_raw, dict):
            entry = "", {}
        else:
            entry = _prepared_meta_entry_from_raw(meta_raw, idx)
        if isinstance(self._prepared_cache, list):
            self._prepared_cache[idx] = entry
        elif len(self._prepared_cache) < _DOC_METADATA_CACHE_LIMIT:
            self._prepared_cache[idx] = entry
        return entry

    def prepared_entries_many(self, doc_ids: Iterable[int]) -> list[Tuple[str, Dict[str, str]]]:
        prepared = self._prepared_cache
        read_one = self._read_one
        prepare = _prepared_meta_entry_from_raw
        append = list.append
        out: list[Tuple[str, Dict[str, object]] | None] = []
        missing_pos: list[int] = []
        missing_ids: list[int] = []
        for raw_doc_id in doc_ids:
            idx = int(raw_doc_id)
            if isinstance(prepared, list):
                cached = prepared[idx] if 0 <= idx < self._doc_count else None
            else:
                cached = prepared.get(idx)
            if cached is not None:
                append(out, cached)
                continue
            append(out, None)
            append(missing_pos, len(out) - 1)
            append(missing_ids, idx)
        if missing_ids:
            can_cache = not isinstance(prepared, list) and len(prepared) < _DOC_METADATA_CACHE_LIMIT
            for pos, idx in zip(missing_pos, missing_ids):
                meta_raw = read_one(idx)
                if not isinstance(meta_raw, dict):
                    entry = ("", {})
                else:
                    entry = prepare(meta_raw, idx)
                if isinstance(prepared, list):
                    prepared[idx] = entry
                elif can_cache and len(prepared) < _DOC_METADATA_CACHE_LIMIT:
                    prepared[idx] = entry
                out[pos] = entry
        return out  # type: ignore[return-value]

    def query_entries_many(self, doc_ids: Iterable[int]) -> list[Tuple[str, Dict[str, object]]]:
        query_cache = self._query_cache
        read_one = self._read_one
        prepare = _query_meta_entry_from_raw
        append = list.append
        out: list[Tuple[str, Dict[str, object]] | None] = []
        missing_pos: list[int] = []
        missing_ids: list[int] = []
        for raw_doc_id in doc_ids:
            idx = int(raw_doc_id)
            if isinstance(query_cache, list):
                cached = query_cache[idx] if 0 <= idx < self._doc_count else None
            else:
                cached = query_cache.get(idx)
            if cached is not None:
                append(out, cached)
                continue
            append(out, None)
            append(missing_pos, len(out) - 1)
            append(missing_ids, idx)
        if missing_ids:
            can_cache = not isinstance(query_cache, list) and len(query_cache) < _DOC_METADATA_CACHE_LIMIT
            for pos, idx in zip(missing_pos, missing_ids):
                meta_raw = read_one(idx)
                entry = prepare(meta_raw, idx) if isinstance(meta_raw, dict) else ("", {})
                if isinstance(query_cache, list):
                    query_cache[idx] = entry
                elif can_cache and len(query_cache) < _DOC_METADATA_CACHE_LIMIT:
                    query_cache[idx] = entry
                out[pos] = entry
        return out  # type: ignore[return-value]

    def __getitem__(self, key: int) -> Dict:
        try:
            idx = int(key)
        except Exception:
            raise KeyError(key)
        if idx < 0 or idx >= self._doc_count:
            raise KeyError(key)
        return self._read_one(idx)

    def get(self, key: int, default=None):  # type: ignore[override]
        try:
            idx = int(key)
        except Exception:
            return default
        meta = self._read_one(idx)
        return meta if meta else default

    def items(self) -> Iterable[Tuple[int, Dict]]:
        for i in range(self._doc_count):
            yield i, self._read_one(i)

    def values(self) -> Iterable[Dict]:
        for i in range(self._doc_count):
            yield self._read_one(i)

    def keys(self) -> Iterable[int]:
        return iter(range(self._doc_count))

    def close(self) -> None:
        try:
            self._blob.close()
        except Exception:
            pass
        try:
            self._blob_fh.close()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        self.close()
