from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional
import json

import numpy as np

from cqlhpc.ast import MetaCond, MetaExpr, meta_cond_menge
from .lexicon import Lexicon
from .fast_index_native import docset_mask_from_ids
from . import index_format
from candyconc.i18n import lt

_MISSING_FIELD = lt("Meta Index Feld fehlt: {field}", "Metadata index field missing: {field}")

#: Fields that repeat the document label (generic imports set both to the ID).
DOCUMENT_LABEL_FIELDS = frozenset({"doc_id", "path"})


def descriptive_fields(value_counts: Mapping[str, int]) -> list[str]:
    """Metadata fields that tell documents apart, the most general first.

    ``value_counts`` maps a field to its number of distinct values. A field
    with one value is the same in every document, and ``doc_id`` and ``path``
    repeat the document label. The remaining fields are ordered by their
    number of distinct values, fewest first, then by name.
    """
    fields = [
        name
        for name, count in value_counts.items()
        if name not in DOCUMENT_LABEL_FIELDS and int(count or 0) > 1
    ]
    return sorted(fields, key=lambda name: (int(value_counts[name]), name))


def _load_array(path: Path, dtype: np.dtype) -> np.ndarray:
    # Count-prefixed array format is defined once in core.index_format.
    return index_format.read_count_prefixed_array(path, dtype, label="Meta Index")


class MetaFieldIndex:
    def __init__(self, name: str, prefix: str, base_dir: Path, has_str: bool, has_num: bool):
        self.name = name
        self.prefix = prefix
        self.base_dir = base_dir
        self.has_str = bool(has_str)
        self.has_num = bool(has_num)
        self._lex: Optional[Lexicon] = None
        self._str_offsets: Optional[np.ndarray] = None
        self._str_doc_ids: Optional[np.ndarray] = None
        self._num_values: Optional[np.ndarray] = None
        self._num_doc_ids: Optional[np.ndarray] = None

    def load(self) -> None:
        if self.has_str:
            lex_path = self.base_dir / f"{self.prefix}.lex.bin"
            self._lex = Lexicon.load(lex_path)
            self._str_offsets = _load_array(self.base_dir / f"{self.prefix}.postings.ptr.bin", np.uint64)
            self._str_doc_ids = _load_array(self.base_dir / f"{self.prefix}.postings.bin", np.uint32)
            expected = index_format.postings_ptr_len(self._lex.vocab_size)
            if self._str_offsets.shape[0] < expected:
                raise RuntimeError(
                    f"Meta Index Posting Pointer Contract ungültig: {self.name} hat "
                    f"{self._str_offsets.shape[0]} Pointer für vocab_size={self._lex.vocab_size}; "
                    "bitte Fast Index neu bauen."
                )
        if self.has_num:
            self._num_values = _load_array(self.base_dir / f"{self.prefix}.num_values.bin", np.float64)
            self._num_doc_ids = _load_array(self.base_dir / f"{self.prefix}.num_docs.bin", np.uint32)

    def distinct_value_count(self) -> int:
        """Number of distinct values of this field (string lexicon, else numbers)."""
        if self._lex is not None:
            return int(self._lex.vocab_size)
        if self._num_values is not None:
            return int(np.unique(self._num_values).size)
        return 0

    def sample_str_values(self, max_scan: int = 256) -> list[tuple[str, int]]:
        """Return (value, count) samples for string fields."""
        if not self.has_str:
            return []
        if self._lex is None or self._str_offsets is None:
            raise RuntimeError(f"Meta Index Stringdaten fehlen: {self.name}")
        values: list[tuple[str, int]] = []
        max_id = min(int(self._lex.vocab_size), max_scan)
        for vid in range(1, max_id + 1):
            s = self._lex.get_string(vid)
            if not s:
                continue
            start = int(self._str_offsets[vid])
            end = int(self._str_offsets[vid + 1])
            count = max(0, end - start)
            if count <= 0:
                continue
            values.append((s, count))
        return values

    def _mask_from_doc_ids(self, doc_ids: np.ndarray, doc_count: int) -> np.ndarray:
        if doc_ids.size == 0:
            return np.zeros(doc_count, dtype=np.bool_)
        ids = doc_ids.astype(np.uint32, copy=False)
        return docset_mask_from_ids(ids, int(doc_count))

    def _mask_str_eq(self, value: str, doc_count: int) -> np.ndarray:
        if self._lex is None or self._str_offsets is None or self._str_doc_ids is None:
            raise RuntimeError(f"Meta Index Stringdaten fehlen: {self.name}")
        vid = int(self._lex.get_id(value))
        if vid <= 0 or vid + 1 >= self._str_offsets.shape[0]:
            return np.zeros(doc_count, dtype=np.bool_)
        start = int(self._str_offsets[vid])
        end = int(self._str_offsets[vid + 1])
        if end <= start:
            return np.zeros(doc_count, dtype=np.bool_)
        return self._mask_from_doc_ids(self._str_doc_ids[start:end], doc_count)

    def _mask_num_range(self, value: float, op: str, doc_count: int) -> np.ndarray:
        if self._num_values is None or self._num_doc_ids is None:
            # Dritter Zweig derselben Sorte. Die beiden anderen sind
            # bereits EingabeFormFehler, dieser blieb ein RuntimeError:
            # {'split': {'op':'>=','value':'test'}} ergab HTTP 400,
            # dieselbe Frage mit {'op':'>=','value':5} HTTP 500, bei
            # docset_intersection sogar mit verschluckter Meldung. Ein
            # Ordnungsvergleich auf einem Feld ohne Zahlendaten ist eine
            # Frage der Aufruferin, keine Stoerung des Servers.
            from candyconc.core.meta_filters import EingabeFormFehler

            raise EingabeFormFehler(
                f"Feld {self.name} fuehrt keine Zahlenwerte, ein "
                f"Ordnungsvergleich ({op}) ist darauf nicht moeglich."
            )
        vals = self._num_values
        if vals.size == 0:
            return np.zeros(doc_count, dtype=np.bool_)
        if op == "=":
            left = int(np.searchsorted(vals, value, side="left"))
            right = int(np.searchsorted(vals, value, side="right"))
        elif op == ">":
            left = int(np.searchsorted(vals, value, side="right"))
            right = vals.size
        elif op == ">=":
            left = int(np.searchsorted(vals, value, side="left"))
            right = vals.size
        elif op == "<":
            left = 0
            right = int(np.searchsorted(vals, value, side="left"))
        elif op == "<=":
            left = 0
            right = int(np.searchsorted(vals, value, side="right"))
        else:
            raise RuntimeError(f"Meta Index Operator ungültig: {op}")
        if right <= left:
            return np.zeros(doc_count, dtype=np.bool_)
        return self._mask_from_doc_ids(self._num_doc_ids[left:right], doc_count)

    def mask_for_cond(self, cond: MetaCond, doc_count: int) -> np.ndarray:
        menge = meta_cond_menge(cond)
        if menge is not None:
            # Mitgliedschaft. Ohne diesen Zweig lief die Liste in das
            # ``str(val)`` weiter unten und wurde zu "['test']" verglichen,
            # was kein Dokument je traegt.
            if cond.op not in {"=", "!="}:
                # EingabeFormFehler, nicht RuntimeError: die eine ist eine
                # Frage der Aufruferin und wird von einer vorhandenen
                # Ausnahmebehandlung zu HTTP 400, die andere sieht wie ein
                # Serverfehler aus.
                from candyconc.core.meta_filters import EingabeFormFehler

                raise EingabeFormFehler(
                    "Eine Wertmenge vergleicht sich nur mit = oder != "
                    f"(Feld {self.name}, Operator {cond.op})."
                )
            eq = np.zeros(doc_count, dtype=np.bool_)
            for wert in menge:
                eq |= self.mask_for_cond(
                    MetaCond(field=cond.field, op="=", value=wert), doc_count
                )
            return np.logical_not(eq) if cond.op == "!=" else eq
        val = cond.value
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if cond.op == "!=":
                eq = self._mask_num_range(float(val), "=", doc_count)
                return np.logical_not(eq)
            return self._mask_num_range(float(val), cond.op, doc_count)
        if cond.op not in {"=", "!="}:
            # Dieselbe Sorte wie im Mengenzweig zwanzig Zeilen hoeher, und
            # dort schon auf EingabeFormFehler umgestellt. Als RuntimeError
            # wurde aus derselben Frage der Aufruferin ein HTTP 500,
            # waehrend die Menge 400 lieferte.
            from candyconc.core.meta_filters import EingabeFormFehler

            raise EingabeFormFehler(
                "Ein Stringvergleich geht nur mit = oder != "
                f"(Feld {self.name}, Operator {cond.op})."
            )
        eq = self._mask_str_eq(str(val), doc_count)
        if cond.op == "!=":
            return np.logical_not(eq)
        return eq


class MetaIndex:
    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        self.meta_dir = self.index_path / "meta_index"
        self.doc_count: int = 0
        self.fields: Dict[str, MetaFieldIndex] = {}

    def available(self) -> bool:
        return (self.meta_dir / "meta_index.json").exists()

    def load(self) -> None:
        manifest_path = self.meta_dir / "meta_index.json"
        if not manifest_path.exists():
            raise RuntimeError(f"Meta Index fehlt: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.doc_count = int(manifest.get("doc_count", 0))
        fields = manifest.get("fields", [])
        if not isinstance(fields, list):
            raise RuntimeError("Meta Index Manifest ungültig")
        for item in fields:
            name = str(item.get("name", ""))
            prefix = str(item.get("prefix", ""))
            if not name or not prefix:
                continue
            idx = MetaFieldIndex(
                name=name,
                prefix=prefix,
                base_dir=self.meta_dir,
                has_str=bool(item.get("has_str", False)),
                has_num=bool(item.get("has_num", False)),
            )
            idx.load()
            self.fields[name] = idx
        if not self.fields:
            raise RuntimeError("Meta Index ist leer")

    def value_counts(self) -> dict[str, int]:
        """Number of distinct values per field."""
        return {name: field.distinct_value_count() for name, field in self.fields.items()}

    def sample_str_values(self, max_scan: int = 256) -> list[tuple[str, str, int]]:
        """Return (field, value, count) samples for string metadata."""
        values: list[tuple[str, str, int]] = []
        for name, field in self.fields.items():
            if not field.has_str:
                continue
            for value, count in field.sample_str_values(max_scan=max_scan):
                values.append((name, value, count))
        return values

    def mask_for_expr(self, expr: MetaExpr) -> np.ndarray:
        if self.doc_count <= 0:
            raise RuntimeError("Meta Index doc_count fehlt")

        def eval_expr(e: MetaExpr) -> np.ndarray:
            if e.kind == "cond":
                c0 = e.parts[0]
                assert isinstance(c0, MetaCond)
                field = c0.field
                idx = self.fields.get(field)
                if idx is None:
                    raise RuntimeError(_MISSING_FIELD.format(field=field))
                return idx.mask_for_cond(c0, self.doc_count)
            if e.kind == "and":
                cur = None
                for part in e.parts:
                    if isinstance(part, MetaExpr):
                        m = eval_expr(part)
                    else:
                        idx = self.fields.get(part.field)
                        if idx is None:
                            raise RuntimeError(_MISSING_FIELD.format(field=part.field))
                        m = idx.mask_for_cond(part, self.doc_count)
                    cur = m if cur is None else (cur & m)
                if cur is None:
                    return np.zeros(self.doc_count, dtype=np.bool_)
                return cur
            if e.kind == "or":
                cur = None
                for part in e.parts:
                    if isinstance(part, MetaExpr):
                        m = eval_expr(part)
                    else:
                        idx = self.fields.get(part.field)
                        if idx is None:
                            raise RuntimeError(_MISSING_FIELD.format(field=part.field))
                        m = idx.mask_for_cond(part, self.doc_count)
                    cur = m if cur is None else (cur | m)
                if cur is None:
                    return np.zeros(self.doc_count, dtype=np.bool_)
                return cur
            return np.zeros(self.doc_count, dtype=np.bool_)

        return eval_expr(expr)
