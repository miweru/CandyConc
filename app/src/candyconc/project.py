from __future__ import annotations

import json
import hashlib
import logging
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

import httpx
import pandas as pd

from candyconc.config import APP_CONFIG
from candyconc.core.fast_concordance import Concordance
from candyconc.i18n import lt

from candyconc.row_keys import row_id as kwic_row_id
from candyconc.row_keys import text_id as kwic_text_id

logger = logging.getLogger(__name__)


_SQLITE_MAGIC = b"SQLite format 3\x00"
_LEGACY_SQLITE_TABLES = frozenset(
    {
        "ai_outputs",
        "analysis_tree",
        "annotation_progress",
        "annotations",
        "bookmarks",
        "comments",
        "filter_state",
        "jobs",
        "macros",
        "metrics",
        "project",
        "settings",
        "span_annotations",
        "subcorpora",
        "timeline",
    }
)


class ProjectMigrationError(RuntimeError):
    """A legacy project cannot be converted without an explicit user action."""


class ProjectMigrationRequired(ProjectMigrationError):
    """Opening a legacy project is read-only; migration is an explicit CLI step."""

    def __init__(self, path: Path, reason: str) -> None:
        suggested = path.with_name(f"{path.stem}.migrated{path.suffix}")
        super().__init__(
            lt(
                "Projektdatei verwendet {reason} und wurde nicht verändert. "
                "Migriere sie explizit mit: candy migrate-project {path} "
                "--output {suggested}",
                "The project file uses {reason} and was not changed. "
                "Migrate it explicitly with: candy migrate-project {path} "
                "--output {suggested}",
            ).format(reason=reason, path=path, suggested=suggested)
        )

# F7 KWIC annotations are scoped by corpus (a doc_id-derived row_id restarts at 0
# per corpus, so the same row_id aliases across corpora). A request with no corpus
# falls back to ``DEFAULT_CORPUS``; legacy flat ``{row_id: ann}`` project files are
# migrated into ``LEGACY_CORPUS`` so pre-scoping codings are preserved.
DEFAULT_CORPUS = "default"
LEGACY_CORPUS = "__legacy__"

# FT-ANNOTATION-RESEARCH (r9): the annotation store is now multi-coder. The
# on-disk shape is ``{corpus: {row_id: {annotator: ann}}}`` — each row can hold
# one coding per annotator (inter-annotator agreement needs >=2 coders per row).
# A coding with no named annotator (single-coder / RBAC-off dev) is stored under
# ``DEFAULT_ANNOTATOR`` so the r8 single-coder API stays byte-identical: a row with
# only the default slot behaves exactly like the old single-coder store.
DEFAULT_ANNOTATOR = "__default__"

# An annotation entry is recognised by these fields; used to tell a legacy flat
# ``{row_id: ann}`` map apart from a nested ``{corpus: {row_id: ann}}`` map.
_ANNOTATION_FIELDS = frozenset({"row_id", "category_id", "note", "annotator", "updated_at"})


def _default_data() -> dict:
    return {
        "version": 2,
        "bookmarks": {},
        "annotations": {},
        "comments": {},
        "timeline": [],
        "metrics": [],
        "subcorpora": {},
        "filter_state": {},
        "settings": {},
        "ai_outputs": [],
        "analysis_tree": None,
        "macros": {},
        "jobs": [],
        "project": {"description": ""},
        "span_annotations": [],
        "annotation_progress": {},
        # F7 KWIC annotation layer: per-row codings keyed by stable row_id, plus
        # coding schemes (named categories). ``coding_schemes`` holds the scheme
        # of each corpus that has one. ``coding_scheme`` is the project scheme,
        # which applies to every corpus without its own. Distinct from the
        # legacy free-text ``annotations`` map above (KWIC bookmarks-with-note).
        "row_annotations": {},
        "coding_scheme": {"categories": [], "revision": 0},
        "coding_schemes": {},
    }


def _write_project_json(path: Path, data: dict) -> None:
    """Persist one already-validated project atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)


class Project:
    """JSON backed store for project state."""

    def __init__(
        self,
        path: str | Path,
        *,
        rotation_ops: int = 10_000,
        rotation_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.rotation_ops = rotation_ops
        self.rotation_bytes = rotation_bytes
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return _default_data()
        raw = self.path.read_bytes()
        if raw.startswith(_SQLITE_MAGIC):
            raise ProjectMigrationRequired(
                self.path, lt("das ältere SQLite-Format", "the older SQLite format")
            )
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(lt("Projektdatei unlesbar", "Project file unreadable")) from exc
        if not isinstance(data, dict) or data.get("version") != 2:
            raise ProjectMigrationRequired(
                self.path,
                lt(
                    "eine ältere oder unbekannte JSON-Projektversion",
                    "an older or unknown JSON project version",
                ),
            )
        if self._requires_annotation_migration(data.get("row_annotations")):
            raise ProjectMigrationRequired(
                self.path, lt("eine ältere Annotationenstruktur", "an older annotation structure")
            )
        return self._ensure_schema(data)

    @classmethod
    def _read_legacy_sqlite(cls, path: Path) -> dict:
        """Read a legacy SQLite ``.ccproj`` for the explicit migration command.

        This reader is intentionally fail-closed: a present but unreadable or
        unknown table aborts the conversion instead of writing a project with
        silently missing research data. Missing known tables are valid for old,
        partial project files.
        """
        import sqlite3

        raw: dict[str, Any] = {}
        path = path.expanduser().resolve()
        try:
            conn = sqlite3.connect(
                f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False
            )
        except sqlite3.Error as exc:
            raise ProjectMigrationError(
                lt(
                    "SQLite-Projekt kann nicht schreibgeschuetzt gelesen werden: {path}",
                    "The SQLite project cannot be read in read-only mode: {path}",
                ).format(path=path)
            ) from exc

        try:
            conn.row_factory = sqlite3.Row
            existing = cls._sqlite_tables(conn)
            unexpected = {
                table
                for table in existing
                if table not in _LEGACY_SQLITE_TABLES and not table.startswith("sqlite_")
            }
            if unexpected:
                tables = ", ".join(sorted(unexpected))
                raise ProjectMigrationError(
                    lt(
                        "SQLite-Projekt enthält unbekannte Tabellen ({tables}); "
                        "Migration wurde ohne Schreiben abgebrochen.",
                        "The SQLite project contains unknown tables ({tables}). "
                        "The migration was aborted without writing.",
                    ).format(tables=tables)
                )

            def _rows(
                table: str, columns: str, *, order_by: str | None = None
            ) -> list[sqlite3.Row]:
                if table not in existing:
                    return []
                query = f"SELECT {columns} FROM {table}"
                if order_by is not None:
                    query += f" ORDER BY {order_by}"
                try:
                    return list(conn.execute(query).fetchall())
                except sqlite3.Error as exc:
                    raise ProjectMigrationError(
                        lt(
                            "Legacy-Tabelle {table!r} kann nicht verlustfrei gelesen werden.",
                            "Legacy table {table!r} cannot be read without loss.",
                        ).format(table=table)
                    ) from exc

            # KWIC tables -> list[dict] (left/kw/right/note|comment); _ensure_schema
            # coerces them into the stable {row_id: {...}} maps the JSON store uses.
            raw["bookmarks"] = [
                {"left": r["left"], "kw": r["kw"], "right": r["right"], "note": r["note"]}
                for r in _rows("bookmarks", "left, kw, right, note")
            ]
            raw["annotations"] = [
                {"left": r["left"], "kw": r["kw"], "right": r["right"], "note": r["note"]}
                for r in _rows("annotations", "left, kw, right, note")
            ]
            raw["comments"] = [
                {"left": r["left"], "kw": r["kw"], "right": r["right"], "comment": r["comment"]}
                for r in _rows("comments", "left, kw, right, comment")
            ]

            # Timeline: ordered op strings.
            raw["timeline"] = [
                r["op"]
                for r in _rows("timeline", "op", order_by="id")
                if r["op"] is not None
            ]

            raw["metrics"] = [
                {"query": r["query"], "hits": r["hits"]}
                for r in _rows("metrics", "query, hits")
            ]

            # Subcorpora: legacy schema is (name, query, filter, created_at, creator).
            # _ensure_schema keys a list of these dicts by ``name`` but does NOT
            # synthesise the newer fields, so emit the full current shape here
            # (corpus/filter_spec/include_*/ai_filters/metadata_schema_hash) with the
            # same defaults ``save_subcorpus`` uses — the legacy store predates them.
            raw["subcorpora"] = [
                {
                    "name": r["name"],
                    "corpus": "default",
                    "query": r["query"] or "",
                    "filter_spec": {},
                    "filter": r["filter"] or "",
                    "include_ai": True,
                    "include_human": True,
                    "ai_filters": {},
                    "metadata_schema_hash": "",
                    "created_at": r["created_at"] or "",
                    "creator": r["creator"] or "unknown",
                }
                for r in _rows("subcorpora", "name, query, filter, created_at, creator")
                if r["name"] is not None
            ]

            # filter_state: the legacy ``state`` column held a JSON object.
            filter_state: dict[str, Any] = {}
            for r in _rows("filter_state", "corpus, state"):
                if r["corpus"] is None:
                    continue
                try:
                    parsed = json.loads(r["state"]) if r["state"] else {}
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ProjectMigrationError(
                        lt(
                            "Legacy-Filterzustand ist kein JSON-Objekt; Migration wurde abgebrochen.",
                            "The legacy filter state is not a JSON object. The migration was aborted.",
                        )
                    ) from exc
                if not isinstance(parsed, dict):
                    raise ProjectMigrationError(
                        lt(
                            "Legacy-Filterzustand ist kein JSON-Objekt; Migration wurde abgebrochen.",
                            "The legacy filter state is not a JSON object. The migration was aborted.",
                        )
                    )
                filter_state[str(r["corpus"])] = parsed
            raw["filter_state"] = filter_state

            raw["settings"] = {
                str(r["key"]): r["value"]
                for r in _rows("settings", "key, value")
                if r["key"] is not None
            }

            raw["ai_outputs"] = [
                r["data"]
                for r in _rows("ai_outputs", "data", order_by="id")
                if r["data"] is not None
            ]

            tree_rows = _rows("analysis_tree", "data")
            if tree_rows and tree_rows[0]["data"] is not None:
                raw["analysis_tree"] = tree_rows[0]["data"]

            raw["macros"] = {
                str(r["name"]): r["template"]
                for r in _rows("macros", "name, template")
                if r["name"] is not None
            }

            raw["jobs"] = [
                {
                    "id": r["id"],
                    "term": r["term"],
                    "ctx": r["ctx"],
                    "status": r["status"],
                    "result": r["result"],
                }
                for r in _rows("jobs", "id, term, ctx, status, result")
            ]

            proj_rows = _rows("project", "description")
            if proj_rows:
                raw["project"] = {"description": proj_rows[0]["description"] or ""}

            raw["span_annotations"] = [
                {
                    "line_id": r["line_id"],
                    "start": r["start"],
                    "end": r["end"],
                    "tag": r["tag"],
                    "annotator": r["annotator"],
                }
                for r in _rows(
                    "span_annotations", "line_id, start, end, tag, annotator"
                )
            ]

            raw["annotation_progress"] = {
                str(r["annotator"]): r["progress"]
                for r in _rows("annotation_progress", "annotator, progress")
                if r["annotator"] is not None
            }
        finally:
            conn.close()

        return cls._ensure_schema(raw)

    @staticmethod
    def _sqlite_tables(conn) -> set[str]:
        """Return the set of table names present in the legacy database."""
        try:
            return {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        except Exception as exc:
            raise ProjectMigrationError(
                lt(
                    "SQLite-Projekt konnte nicht inventarisiert werden.",
                    "The SQLite project could not be inventoried.",
                )
            ) from exc

    @classmethod
    def _requires_annotation_migration(cls, raw: Any) -> bool:
        """Return whether ``row_annotations`` still uses a retired disk shape."""
        if not isinstance(raw, dict):
            return False
        if any(cls._looks_like_annotation(value) for value in raw.values()):
            return True
        return any(
            isinstance(rows, dict)
            and any(cls._looks_like_annotation(value) for value in rows.values())
            for rows in raw.values()
        )

    @classmethod
    def _ensure_schema(cls, data: Any) -> dict:
        base = _default_data()
        if not isinstance(data, dict):
            return base

        def _coerce_kwic(value: Any, value_key: str) -> dict[str, dict]:
            out: dict[str, dict] = {}
            if isinstance(value, dict):
                items = value.values()
            elif isinstance(value, list):
                items = value
            else:
                return out
            for row in items:
                if not isinstance(row, dict):
                    continue
                rid = row.get("row_id") or kwic_text_id(row)
                out[str(rid)] = {
                    "row_id": str(rid),
                    "left": row.get("left", ""),
                    "kw": row.get("kw", ""),
                    "right": row.get("right", ""),
                    value_key: row.get(value_key, ""),
                    "file": row.get("file"),
                    "pos": cls._int_or_none(row.get("pos")),
                    "line_id": cls._int_or_none(row.get("line_id")),
                }
            return out

        base["bookmarks"] = _coerce_kwic(data.get("bookmarks"), "note")
        base["annotations"] = _coerce_kwic(data.get("annotations"), "note")
        base["comments"] = _coerce_kwic(data.get("comments"), "comment")

        timeline = data.get("timeline")
        if isinstance(timeline, list):
            base["timeline"] = [
                row["op"] if isinstance(row, dict) and "op" in row else row
                for row in timeline
                if isinstance(row, (dict, str))
            ]
        metrics = data.get("metrics")
        if isinstance(metrics, list):
            base["metrics"] = [
                {"query": str(m.get("query", "")), "hits": int(m.get("hits", 0))}
                for m in metrics
                if isinstance(m, dict)
            ]
        subcorpora = data.get("subcorpora")
        if isinstance(subcorpora, dict):
            base["subcorpora"] = {
                str(k): v for k, v in subcorpora.items() if isinstance(v, dict)
            }
        elif isinstance(subcorpora, list):
            base["subcorpora"] = {
                str(row.get("name")): row for row in subcorpora if isinstance(row, dict)
            }
        filter_state = data.get("filter_state")
        if isinstance(filter_state, dict):
            base["filter_state"] = {
                str(k): v for k, v in filter_state.items() if isinstance(v, dict)
            }
        settings = data.get("settings")
        if isinstance(settings, dict):
            base["settings"] = {str(k): str(v) for k, v in settings.items()}
        ai_outputs = data.get("ai_outputs")
        if isinstance(ai_outputs, list):
            base["ai_outputs"] = [
                row.get("data") if isinstance(row, dict) else row
                for row in ai_outputs
                if isinstance(row, (dict, str))
            ]
        if isinstance(data.get("analysis_tree"), str) or data.get("analysis_tree") is None:
            base["analysis_tree"] = data.get("analysis_tree")
        macros = data.get("macros")
        if isinstance(macros, dict):
            base["macros"] = {str(k): str(v) for k, v in macros.items()}
        jobs = data.get("jobs")
        if isinstance(jobs, list):
            base["jobs"] = [row for row in jobs if isinstance(row, dict)]
        project = data.get("project")
        if isinstance(project, dict):
            base["project"] = {"description": str(project.get("description", ""))}
        span_annotations = data.get("span_annotations")
        if isinstance(span_annotations, list):
            base["span_annotations"] = [
                row for row in span_annotations if isinstance(row, dict)
            ]
        annotation_progress = data.get("annotation_progress")
        if isinstance(annotation_progress, dict):
            base["annotation_progress"] = {
                str(k): int(v) for k, v in annotation_progress.items()
            }
        # F7 KWIC row annotations — back-compat: absent keys default to empty via
        # ``base``. The store is nested by corpus: ``{corpus: {row_id: ann}}``.
        # A doc_id-derived row_id (``file:pos``) restarts at 0 per corpus, so the
        # SAME row_id aliases across corpora; the corpus namespace keeps them
        # independent. Legacy flat ``{row_id: ann}`` files are migrated wholesale
        # into the ``LEGACY_CORPUS`` namespace so existing codings are never lost.
        row_annotations = data.get("row_annotations")
        if isinstance(row_annotations, dict):
            base["row_annotations"] = cls._coerce_row_annotations(row_annotations)
        coding_scheme = data.get("coding_scheme")
        if isinstance(coding_scheme, dict):
            base["coding_scheme"] = cls._coerce_scheme(coding_scheme)
        coding_schemes = data.get("coding_schemes")
        if isinstance(coding_schemes, dict):
            base["coding_schemes"] = {
                str(corpus): cls._coerce_scheme(scheme)
                for corpus, scheme in coding_schemes.items()
                if str(corpus).strip() and isinstance(scheme, dict)
            }
        return base

    @classmethod
    def _coerce_scheme(cls, scheme: dict) -> dict:
        return {
            "categories": cls._coerce_categories(scheme.get("categories")),
            "revision": max(0, cls._int_or_none(scheme.get("revision")) or 0),
        }

    @classmethod
    def _looks_like_annotation(cls, value: Any) -> bool:
        """True when ``value`` is a single annotation dict (not a map of them)."""
        return isinstance(value, dict) and bool(_ANNOTATION_FIELDS & set(value.keys()))

    @classmethod
    def _coerce_row_annotations(cls, raw: dict) -> dict[str, dict]:
        """Coerce on-disk ``row_annotations`` into ``{corpus: {row_id: {annotator: ann}}}``.

        Three historical on-disk layouts are accepted and migrated forward:

        * **legacy flat** ``{row_id: ann}`` — a top-level value that *is* a single
          annotation dict. Migrated wholesale into ``LEGACY_CORPUS`` and the
          ``DEFAULT_ANNOTATOR`` slot so pre-scoping codings survive.
        * **r8 corpus-scoped** ``{corpus: {row_id: ann}}`` — each ``row_id`` maps to
          a single annotation dict. Lifted into the per-annotator slot
          (``DEFAULT_ANNOTATOR``, or the entry's own ``annotator`` when present) so
          existing single-coder data keeps working unchanged.
        * **r9 multi-coder** ``{corpus: {row_id: {annotator: ann}}}`` — passed
          through, normalising each leaf.
        """
        is_legacy_flat = any(cls._looks_like_annotation(v) for v in raw.values())
        if is_legacy_flat:
            flat: dict[str, dict] = {}
            for rid, ann in raw.items():
                if isinstance(ann, dict):
                    flat[str(rid)] = {DEFAULT_ANNOTATOR: cls._coerce_row_annotation(str(rid), ann)}
            return {LEGACY_CORPUS: flat} if flat else {}
        out: dict[str, dict] = {}
        for corpus, rows in raw.items():
            if not isinstance(rows, dict):
                continue
            scoped: dict[str, dict] = {}
            for rid, value in rows.items():
                rid_s = str(rid)
                coders = cls._coerce_row_coders(rid_s, value)
                if coders:
                    scoped[rid_s] = coders
            if scoped:
                out[str(corpus)] = scoped
        return out

    @classmethod
    def _coerce_row_coders(cls, row_id: str, value: Any) -> dict[str, dict]:
        """Return the ``{annotator: ann}`` map for one row, accepting r8 or r9 shapes."""
        if not isinstance(value, dict):
            return {}
        # r8 single-coder leaf (the value IS an annotation) -> lift into its slot.
        if cls._looks_like_annotation(value):
            ann = cls._coerce_row_annotation(row_id, value)
            slot = ann["annotator"] or DEFAULT_ANNOTATOR
            return {slot: ann}
        # r9 multi-coder leaf: ``{annotator: ann}``.
        out: dict[str, dict] = {}
        for annotator, ann in value.items():
            if isinstance(ann, dict):
                out[str(annotator)] = cls._coerce_row_annotation(row_id, ann)
        return out

    @staticmethod
    def _coerce_row_annotation(row_id: str, value: Any) -> dict:
        cat = value.get("category_id")
        note = value.get("note")
        return {
            "row_id": row_id,
            "category_id": str(cat) if cat is not None else None,
            "note": str(note) if note is not None else None,
            "annotator": str(value.get("annotator", "") or ""),
            "updated_at": str(value.get("updated_at", "") or ""),
        }

    @staticmethod
    def _coerce_categories(cats: Any) -> List[dict]:
        out: List[dict] = []
        if not isinstance(cats, list):
            return out
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            cid = cat.get("id")
            label = cat.get("label")
            if cid is None or label is None:
                continue
            entry = {"id": str(cid), "label": str(label), "color": str(cat.get("color", "") or "")}
            shortcut = cat.get("shortcut")
            if shortcut is not None and str(shortcut):
                entry["shortcut"] = str(shortcut)
            out.append(entry)
        return out

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def _save(self) -> None:
        with self._lock:
            _write_project_json(self.path, self._data)

    def close(self) -> None:
        return

    def save(self) -> None:
        self._save()

    def add_bookmark(self, row: Dict[str, str], note: str | None = None) -> None:
        note = (note if note is not None else row.get("note", "")).strip()
        rid = kwic_row_id(row)
        with self._lock:
            self._data["bookmarks"][rid] = {
                "row_id": rid,
                "left": row.get("left", ""),
                "kw": row.get("kw", ""),
                "right": row.get("right", ""),
                "note": note,
                "file": row.get("file"),
                "pos": self._int_or_none(row.get("pos")),
                "line_id": self._int_or_none(row.get("line_id")),
            }
            self._save()

    def remove_bookmark(self, row: Dict[str, str]) -> None:
        rid = kwic_row_id(row)
        with self._lock:
            if rid in self._data["bookmarks"]:
                self._data["bookmarks"].pop(rid, None)
            else:
                left = row.get("left", "")
                kw = row.get("kw", "")
                right = row.get("right", "")
                for key, entry in list(self._data["bookmarks"].items()):
                    if (
                        entry.get("left") == left
                        and entry.get("kw") == kw
                        and entry.get("right") == right
                    ):
                        self._data["bookmarks"].pop(key, None)
            self._save()

    def bookmarks(self) -> List[Dict[str, str]]:
        return list(self._data["bookmarks"].values())

    # Comments ---------------------------------------------------------

    def add_comment(self, row: Dict[str, str], comment: str) -> None:
        comment = (comment or "").strip()
        rid = kwic_row_id(row)
        with self._lock:
            if comment:
                self._data["comments"][rid] = {
                    "row_id": rid,
                    "left": row.get("left", ""),
                    "kw": row.get("kw", ""),
                    "right": row.get("right", ""),
                    "comment": comment,
                    "file": row.get("file"),
                    "pos": self._int_or_none(row.get("pos")),
                    "line_id": self._int_or_none(row.get("line_id")),
                }
            else:
                self._data["comments"].pop(rid, None)
            self._save()

    def comments(self) -> List[Dict[str, str]]:
        return list(self._data["comments"].values())

    # Annotations -------------------------------------------------------

    def add_annotation(self, row: Dict[str, str], note: str) -> None:
        rid = kwic_row_id(row)
        with self._lock:
            self._data["annotations"][rid] = {
                "row_id": rid,
                "left": row.get("left", ""),
                "kw": row.get("kw", ""),
                "right": row.get("right", ""),
                "note": note,
                "file": row.get("file"),
                "pos": self._int_or_none(row.get("pos")),
                "line_id": self._int_or_none(row.get("line_id")),
            }
            self._save()

    def annotations(self) -> List[Dict[str, str]]:
        return list(self._data["annotations"].values())

    # F7 KWIC row annotations + coding scheme -----------------------------
    #
    # First-class KWIC annotation layer (Track F7). A *row annotation* couples a
    # stable ``row_id`` (``f"{file}:{pos}"`` / text-hash fallback, computed by the
    # caller) with an optional ``category_id`` (must exist in the coding scheme)
    # and/or an optional free-text ``note``. The *coding scheme* is the set of
    # named categories (id/label/color/optional shortcut) of a corpus, with the
    # project scheme for corpora without one. Both live in the ``.ccproj`` data
    # dict and are thread-safe via the shared ``_lock``.

    @staticmethod
    def _corpus_key(corpus: str | None) -> str:
        """Normalise a request's corpus into a non-empty namespace key."""
        key = str(corpus).strip() if corpus is not None else ""
        return key or DEFAULT_CORPUS

    # Project-level multi-coder toggle. Default OFF preserves the r8 single-coder
    # contract byte-for-byte: every coding of a row collapses into one slot, so a
    # second annotator silently overwrites (the documented r8 behaviour). When ON,
    # each annotator keys an independent slot (the FT-ANNOTATION-RESEARCH model that
    # IAA needs). Persisted in the existing ``settings`` map.
    _MULTI_CODER_SETTING = "annotations.multi_coder"

    def multi_coder_enabled(self) -> bool:
        return str(self.get_setting(self._MULTI_CODER_SETTING) or "").strip().lower() in (
            "1",
            "true",
            "on",
            "yes",
        )

    def set_multi_coder_enabled(self, enabled: bool) -> None:
        self.set_setting(self._MULTI_CODER_SETTING, "1" if enabled else "0")

    def _annotator_slot(self, annotator: str | None) -> str:
        """Map a request annotator to a store slot key.

        In single-coder mode (default) every coding collapses into one slot so a row
        holds exactly one coding (r8 contract). In multi-coder mode the annotator
        name keys an independent slot; an empty annotator falls back to the default
        slot so unnamed/dev codings still have a home.
        """
        slot = str(annotator).strip() if annotator is not None else ""
        if not self.multi_coder_enabled():
            return DEFAULT_ANNOTATOR
        return slot or DEFAULT_ANNOTATOR

    @classmethod
    def _representative_coding(cls, coders: dict[str, dict]) -> dict | None:
        """Pick the single coding a single-coder reader should see for a row.

        Back-compat with the r8 single-coder API: prefer the ``DEFAULT_ANNOTATOR``
        slot (where unnamed/dev codings land), otherwise the most-recently-updated
        named coder, so a row that only ever had one coder reads identically.
        """
        if not coders:
            return None
        if DEFAULT_ANNOTATOR in coders:
            return coders[DEFAULT_ANNOTATOR]
        return max(coders.values(), key=lambda a: str(a.get("updated_at") or ""))

    def row_annotations(self, corpus: str | None = None, annotator: str | None = None) -> Dict[str, dict]:
        """Return the ``{row_id: annotation}`` map for one corpus (copy).

        Single-coder view (back-compat with r8): one representative coding per row.
        Pass ``annotator`` to read only that coder's rows. For the full multi-coder
        view use :meth:`row_annotations_multi`. Annotations are scoped by corpus; a
        missing ``corpus`` reads the ``DEFAULT_CORPUS`` namespace.
        """
        ck = self._corpus_key(corpus)
        scoped = self._data["row_annotations"].get(ck, {})
        out: Dict[str, dict] = {}
        if annotator is not None:
            slot = self._annotator_slot(annotator)
            for rid, coders in scoped.items():
                if isinstance(coders, dict) and slot in coders:
                    out[rid] = dict(coders[slot])
            return out
        for rid, coders in scoped.items():
            rep = self._representative_coding(coders) if isinstance(coders, dict) else None
            if rep is not None:
                out[rid] = dict(rep)
        return out

    def row_annotations_multi(self, corpus: str | None = None) -> Dict[str, Dict[str, dict]]:
        """Return the full multi-coder ``{row_id: {annotator: ann}}`` map (copy).

        ``annotator`` keys are the request-facing annotator names; the internal
        ``DEFAULT_ANNOTATOR`` slot (unnamed/dev codings) is surfaced as ``""`` so
        clients never see the sentinel.
        """
        ck = self._corpus_key(corpus)
        scoped = self._data["row_annotations"].get(ck, {})
        out: Dict[str, Dict[str, dict]] = {}
        for rid, coders in scoped.items():
            if not isinstance(coders, dict):
                continue
            out[rid] = {
                ("" if slot == DEFAULT_ANNOTATOR else slot): dict(ann)
                for slot, ann in coders.items()
            }
        return out

    def get_row_annotation(
        self, row_id: str, corpus: str | None = None, annotator: str | None = None
    ) -> dict | None:
        """Return one coding for ``row_id``.

        Without ``annotator`` this returns the representative coding (r8 contract).
        With ``annotator`` it returns that specific coder's coding (or ``None``).
        """
        ck = self._corpus_key(corpus)
        scoped = self._data["row_annotations"].get(ck, {})
        coders = scoped.get(str(row_id))
        if not isinstance(coders, dict):
            return None
        if annotator is not None:
            ann = coders.get(self._annotator_slot(annotator))
            return dict(ann) if isinstance(ann, dict) else None
        rep = self._representative_coding(coders)
        return dict(rep) if isinstance(rep, dict) else None

    def set_row_annotation(
        self,
        row_id: str,
        *,
        corpus: str | None = None,
        category_id: str | None = None,
        note: str | None = None,
        annotator: str = "",
    ) -> dict:
        """Upsert the annotation for ``row_id``/``annotator`` within ``corpus``.

        ``category_id``/``note`` are replaced wholesale (a ``None`` clears that
        facet). The caller (route layer) is responsible for validating that
        ``category_id`` exists in the coding scheme and for capping note length.
        Scoping by corpus keeps row_ids that collide across corpora independent;
        scoping by annotator keeps multiple coders' codings of the same row
        independent (a coder only ever overwrites their OWN coding).
        """
        rid = str(row_id)
        ck = self._corpus_key(corpus)
        slot = self._annotator_slot(annotator)
        entry = {
            "row_id": rid,
            "category_id": str(category_id) if category_id is not None else None,
            "note": str(note) if note is not None else None,
            # Provenance: always record the caller's annotator name verbatim, even
            # in single-coder mode where the storage slot is the default sentinel.
            # The slot is storage; ``annotator`` is the attribution IAA reads.
            "annotator": str(annotator or ""),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            self._data["row_annotations"].setdefault(ck, {}).setdefault(rid, {})[slot] = entry
            self._save()
        return dict(entry)

    def delete_row_annotation(
        self, row_id: str, corpus: str | None = None, annotator: str | None = None
    ) -> bool:
        """Remove a coding for ``row_id`` in ``corpus``; True if one existed.

        Without ``annotator`` this removes the representative coding's slot (r8
        contract: a single-coder DELETE clears the row). With ``annotator`` it
        removes only that coder's coding, leaving others intact.
        """
        rid = str(row_id)
        ck = self._corpus_key(corpus)
        with self._lock:
            scoped = self._data["row_annotations"].get(ck, {})
            coders = scoped.get(rid)
            if not isinstance(coders, dict) or not coders:
                return False
            if annotator is not None:
                slot = self._annotator_slot(annotator)
            else:
                rep = self._representative_coding(coders)
                slot = (rep or {}).get("annotator") or "" if rep else ""
                slot = self._annotator_slot(slot)
            existed = slot in coders
            coders.pop(slot, None)
            if not coders:
                scoped.pop(rid, None)
            if not scoped:
                self._data["row_annotations"].pop(ck, None)
            if existed:
                self._save()
        return existed

    @staticmethod
    def _validated_categories(categories: List[dict]) -> List[dict]:
        """Coerce categories and reject duplicate ids before any mutation."""
        coerced = Project._coerce_categories(categories)
        seen: set[str] = set()
        for cat in coerced:
            if cat["id"] in seen:
                raise ValueError(
                    lt("doppelte Kategorie-id: {id}", "duplicate category id: {id}").format(id=cat["id"])
                )
            seen.add(cat["id"])
        return coerced

    # Coding schemes belong to a corpus. A call with ``corpus`` reads and
    # writes the scheme of that corpus. A corpus without a scheme of its own
    # reads the project scheme, and its first write stores its own. A call
    # without ``corpus`` works on the project scheme, which older project files
    # used for every corpus.

    def _scheme_record_locked(self, corpus: str | None = None) -> dict:
        if corpus is not None:
            own = self._data["coding_schemes"].get(self._corpus_key(corpus))
            if own is not None:
                return own
        return self._data["coding_scheme"]

    def _scheme_corpora_locked(self, corpus: str | None) -> List[str]:
        """Corpus namespaces whose codings refer to the scheme of ``corpus``."""
        if corpus is not None:
            return [self._corpus_key(corpus)]
        own = self._data["coding_schemes"]
        return [key for key in self._data["row_annotations"] if key not in own]

    def _coding_scheme_revision_locked(self, corpus: str | None = None) -> int:
        scheme = self._scheme_record_locked(corpus)
        return max(0, self._int_or_none(scheme.get("revision")) or 0)

    def coding_scheme_snapshot(self, corpus: str | None = None) -> dict:
        """Return the scheme of ``corpus`` and its optimistic-concurrency revision."""
        with self._lock:
            return {
                "categories": self.coding_scheme(corpus),
                "revision": self._coding_scheme_revision_locked(corpus),
            }

    def coding_scheme(self, corpus: str | None = None) -> List[dict]:
        """Return the categories of the scheme of ``corpus`` (copy)."""
        with self._lock:
            cats = self._scheme_record_locked(corpus).get("categories", [])
            return [dict(c) for c in cats]

    def _scheme_removal_impact_locked(
        self,
        current: List[dict],
        replacement_ids: set[str],
        corpus: str | None = None,
    ) -> List[dict]:
        """Count every coding that would lose its category in a schema replacement."""
        dropped = [cat for cat in current if cat["id"] not in replacement_ids]
        if not dropped:
            return []
        impact = {
            cat["id"]: {
                "category_id": cat["id"],
                "label": cat["label"],
                "annotation_count": 0,
                "corpora": set(),
                "annotator_slots": set(),
            }
            for cat in dropped
        }
        scope = self._scheme_corpora_locked(corpus)
        for namespace, scoped in self._data["row_annotations"].items():
            if namespace not in scope or not isinstance(scoped, dict):
                continue
            for coders in scoped.values():
                if not isinstance(coders, dict):
                    continue
                for slot, entry in coders.items():
                    if not isinstance(entry, dict):
                        continue
                    category_id = entry.get("category_id")
                    if category_id not in impact:
                        continue
                    item = impact[category_id]
                    item["annotation_count"] += 1
                    item["corpora"].add(str(namespace))
                    item["annotator_slots"].add(str(slot))
        return [
            {
                "category_id": item["category_id"],
                "label": item["label"],
                "annotation_count": item["annotation_count"],
                "corpus_count": len(item["corpora"]),
                "annotator_count": len(item["annotator_slots"]),
            }
            for item in impact.values()
            if item["annotation_count"] > 0
        ]

    @staticmethod
    def _scheme_confirmation_token(
        revision: int,
        current: List[dict],
        replacement: List[dict],
        removals: List[dict],
    ) -> str:
        # Stateless token: it becomes invalid when the schema, proposed edit, or
        # affected coding counts change before the manager confirms deletion.
        payload = json.dumps(
            {
                "revision": revision,
                "current": current,
                "replacement": replacement,
                "removals": removals,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _preview_coding_scheme_update_locked(
        self,
        replacement: List[dict],
        expected_revision: int,
        corpus: str | None = None,
    ) -> dict:
        current = [dict(cat) for cat in self._scheme_record_locked(corpus).get("categories", [])]
        revision = self._coding_scheme_revision_locked(corpus)
        if expected_revision != revision:
            return {
                "status": "stale",
                "categories": current,
                "revision": revision,
                "removals": [],
                "confirmation_token": None,
            }
        removals = self._scheme_removal_impact_locked(
            current,
            {cat["id"] for cat in replacement},
            corpus,
        )
        return {
            "status": "ready",
            "categories": current,
            "revision": revision,
            "removals": removals,
            "confirmation_token": (
                self._scheme_confirmation_token(revision, current, replacement, removals)
                if removals
                else None
            ),
        }

    def preview_coding_scheme_update(
        self,
        categories: List[dict],
        expected_revision: int,
        corpus: str | None = None,
    ) -> dict:
        replacement = self._validated_categories(categories)
        with self._lock:
            return self._preview_coding_scheme_update_locked(replacement, expected_revision, corpus)

    def _apply_coding_scheme_locked(self, replacement: List[dict], corpus: str | None = None) -> List[dict]:
        surviving_ids = {cat["id"] for cat in replacement}
        scope = self._scheme_corpora_locked(corpus)
        # Referential integrity is retained, but category-only codings no longer
        # survive as phantom "annotated" rows after their category is removed.
        # Only the codings of the corpora that use this scheme are touched.
        for namespace, scoped in list(self._data["row_annotations"].items()):
            if namespace not in scope or not isinstance(scoped, dict):
                continue
            for row_id, coders in list(scoped.items()):
                if not isinstance(coders, dict):
                    continue
                for slot, entry in list(coders.items()):
                    if (
                        isinstance(entry, dict)
                        and entry.get("category_id") is not None
                        and entry["category_id"] not in surviving_ids
                    ):
                        entry["category_id"] = None
                        if not str(entry.get("note") or "").strip():
                            coders.pop(slot, None)
                if not coders:
                    scoped.pop(row_id, None)
            if not scoped:
                self._data["row_annotations"].pop(namespace, None)

        record = {
            "categories": replacement,
            "revision": self._coding_scheme_revision_locked(corpus) + 1,
        }
        if corpus is None:
            self._data["coding_scheme"] = record
        else:
            self._data["coding_schemes"][self._corpus_key(corpus)] = record
        self._save()
        return [dict(cat) for cat in replacement]

    def apply_coding_scheme_update(
        self,
        categories: List[dict],
        expected_revision: int,
        confirmation_token: str | None = None,
        corpus: str | None = None,
    ) -> dict:
        """Apply a reviewed schema change or return a non-mutating conflict state."""
        replacement = self._validated_categories(categories)
        with self._lock:
            preview = self._preview_coding_scheme_update_locked(replacement, expected_revision, corpus)
            if preview["status"] != "ready":
                return preview
            if preview["removals"] and confirmation_token != preview["confirmation_token"]:
                return {**preview, "status": "confirmation_required"}

            current = self._scheme_record_locked(corpus).get("categories", [])
            if current == replacement:
                return {
                    "status": "ok",
                    "categories": [dict(cat) for cat in current],
                    "revision": self._coding_scheme_revision_locked(corpus),
                }
            stored = self._apply_coding_scheme_locked(replacement, corpus)
            return {
                "status": "ok",
                "categories": stored,
                "revision": self._coding_scheme_revision_locked(corpus),
            }

    def set_coding_scheme(self, categories: List[dict], corpus: str | None = None) -> List[dict]:
        """Low-level replacement used by migrations and direct Project callers.

        HTTP callers use :meth:`preview_coding_scheme_update` and
        :meth:`apply_coding_scheme_update` so destructive removals are reviewed.
        """
        replacement = self._validated_categories(categories)
        with self._lock:
            if self._scheme_record_locked(corpus).get("categories", []) == replacement:
                return [dict(cat) for cat in replacement]
            return self._apply_coding_scheme_locked(replacement, corpus)

    # FT-ANNOTATION-RESEARCH: inter-annotator agreement (IAA) ---------------
    #
    # Agreement is computed over the *category* assigned by each coder (the unit of
    # coding for IAA — free-text notes are not comparable). Only rows that ≥2 named
    # coders have assigned a category to count toward agreement; the unnamed
    # ``DEFAULT_ANNOTATOR`` slot is excluded (a single-coder dev coding has no peer
    # to agree with). Returns percent agreement plus Cohen's kappa (exactly two
    # coders) or Fleiss' kappa (three or more), both implemented in pure Python so
    # the annotation layer keeps its no-scipy footprint.

    def annotation_agreement(self, corpus: str | None = None) -> dict:
        """Return inter-annotator agreement statistics for one corpus.

        Shape::

            {
              "corpus": str,
              "annotators": [name, ...],          # named coders that assigned categories
              "n_rows_total": int,                # rows with >=1 category coding
              "n_rows_overlap": int,              # rows >=2 coders both assigned a category
              "percent_agreement": float | None, # over overlap rows (pairwise-averaged)
              "kappa": float | None,              # Cohen (2 coders) / Fleiss (>=3)
              "kappa_method": "cohen" | "fleiss" | None,
              "per_category_agreement": {cat_id: float, ...},
            }

        ``kappa``/``percent_agreement`` are ``None`` when there is no overlap (fewer
        than two coders, or no row that two coders both categorised).
        """
        multi = self.row_annotations_multi(corpus)
        # row_id -> {annotator: category_id} for NAMED coders with a category set.
        coded: dict[str, dict[str, str]] = {}
        annotators: set[str] = set()
        categories: set[str] = set()
        for rid, coders in multi.items():
            row_map: dict[str, str] = {}
            for annotator, ann in coders.items():
                if not annotator:  # skip the unnamed default/dev slot
                    continue
                cat = ann.get("category_id")
                if cat is None:
                    continue
                row_map[annotator] = str(cat)
                annotators.add(annotator)
                categories.add(str(cat))
            if row_map:
                coded[rid] = row_map

        sorted_annotators = sorted(annotators)
        result: dict = {
            "corpus": self._corpus_key(corpus),
            "annotators": sorted_annotators,
            "n_rows_total": len(coded),
            "n_rows_overlap": 0,
            "percent_agreement": None,
            "kappa": None,
            "kappa_method": None,
            "per_category_agreement": {},
        }

        # Overlap = rows where >=2 named coders both assigned a category.
        overlap = {rid: m for rid, m in coded.items() if len(m) >= 2}
        result["n_rows_overlap"] = len(overlap)
        if not overlap:
            return result

        result["percent_agreement"] = self._percent_agreement(overlap)
        result["per_category_agreement"] = self._per_category_agreement(overlap, sorted(categories))

        if len(sorted_annotators) == 2:
            a, b = sorted_annotators
            paired = [
                (m[a], m[b]) for m in overlap.values() if a in m and b in m
            ]
            kappa = self._cohen_kappa(paired)
            if kappa is not None:
                result["kappa"] = kappa
                result["kappa_method"] = "cohen"
        elif len(sorted_annotators) >= 3:
            kappa = self._fleiss_kappa(overlap, sorted(categories))
            if kappa is not None:
                result["kappa"] = kappa
                result["kappa_method"] = "fleiss"
        return result

    @staticmethod
    def _percent_agreement(overlap: dict[str, dict[str, str]]) -> float:
        """Mean pairwise observed agreement across overlap rows."""
        total_pairs = 0
        agree_pairs = 0
        for row in overlap.values():
            labels = list(row.values())
            n = len(labels)
            for i in range(n):
                for j in range(i + 1, n):
                    total_pairs += 1
                    if labels[i] == labels[j]:
                        agree_pairs += 1
        return (agree_pairs / total_pairs) if total_pairs else 0.0

    @staticmethod
    def _per_category_agreement(
        overlap: dict[str, dict[str, str]], categories: List[str]
    ) -> dict[str, float]:
        """Per-category pairwise agreement (share of pairs that both chose the category)."""
        out: dict[str, float] = {}
        for cat in categories:
            total = 0
            both = 0
            for row in overlap.values():
                labels = list(row.values())
                n = len(labels)
                for i in range(n):
                    for j in range(i + 1, n):
                        if labels[i] == cat or labels[j] == cat:
                            total += 1
                            if labels[i] == cat and labels[j] == cat:
                                both += 1
            if total:
                out[cat] = both / total
        return out

    @staticmethod
    def _clamp_kappa_zero(kappa: float) -> float:
        """Snap a kappa that is mathematically chance-level (0) to exactly 0.0.

        ``po - pe`` can be a chance-level 0 that float rounding turns into a tiny
        residual (e.g. ``-5.5e-17`` when ``pe`` is a repeating fraction). The UI
        then renders ``-0.000`` labelled "schlechter als Zufall". Clamp only that
        epsilon band; a genuinely negative or positive kappa passes through.
        """
        return 0.0 if abs(kappa) < 1e-9 else kappa

    @staticmethod
    def _cohen_kappa(paired: List[tuple]) -> float | None:
        """Cohen's kappa for two coders over ``[(label_a, label_b), ...]``.

        ``None`` when there is nothing to score. When the coders are in perfect
        agreement on a single category (expected agreement == 1) kappa is defined
        as 1.0 (no disagreement to discount).
        """
        n = len(paired)
        if n == 0:
            return None
        labels = sorted({lab for pair in paired for lab in pair})
        po = sum(1 for a, b in paired if a == b) / n
        marg_a = {lab: 0 for lab in labels}
        marg_b = {lab: 0 for lab in labels}
        for a, b in paired:
            marg_a[a] += 1
            marg_b[b] += 1
        pe = sum((marg_a[lab] / n) * (marg_b[lab] / n) for lab in labels)
        if pe >= 1.0:
            return 1.0 if po >= 1.0 else (po - pe) / (1e-12)
        return Project._clamp_kappa_zero((po - pe) / (1.0 - pe))

    @staticmethod
    def _fleiss_kappa(
        overlap: dict[str, dict[str, str]], categories: List[str]
    ) -> float | None:
        """Fleiss' kappa over rows rated by a variable number of coders (>=2).

        Uses the standard Fleiss formulation generalised to a per-item rater count
        (items may have different numbers of coders). Items rated by fewer than two
        coders are skipped. Returns ``None`` when no item qualifies.
        """
        cat_index = {c: i for i, c in enumerate(categories)}
        k = len(categories)
        if k == 0:
            return None
        # Build the count matrix n_ij (item i, category j).
        rows = []
        for row in overlap.values():
            counts = [0] * k
            n_i = 0
            for cat in row.values():
                idx = cat_index.get(cat)
                if idx is not None:
                    counts[idx] += 1
                    n_i += 1
            if n_i >= 2:
                rows.append((counts, n_i))
        if not rows:
            return None
        N = len(rows)
        # Per-item agreement P_i = (sum_j n_ij^2 - n_i) / (n_i (n_i - 1)).
        p_bar = 0.0
        for counts, n_i in rows:
            agree = sum(c * c for c in counts) - n_i
            p_bar += agree / (n_i * (n_i - 1))
        p_bar /= N
        # Category marginals p_j = (sum_i n_ij) / (sum_i n_i).
        total_ratings = sum(n_i for _, n_i in rows)
        p_j = [
            sum(counts[j] for counts, _ in rows) / total_ratings for j in range(k)
        ]
        p_e = sum(p * p for p in p_j)
        if p_e >= 1.0:
            return 1.0 if p_bar >= 1.0 else (p_bar - p_e) / (1e-12)
        return Project._clamp_kappa_zero((p_bar - p_e) / (1.0 - p_e))

    def import_row_annotations(
        self,
        records: List[dict],
        *,
        corpus: str | None = None,
        valid_category_ids: set[str] | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Bulk-import row annotations (multi-coder aware).

        ``records`` are dicts in the exporter shape: ``row_id`` (required) plus any
        of ``category_id``/``note``/``annotator``. A record whose ``category_id`` is
        not in ``valid_category_ids`` (when supplied) is rejected (not imported).
        With ``dry_run`` nothing is written — the return is a preview of what WOULD
        be imported. Returns ``{imported, skipped, errors:[...], previews:[...]}``.
        """
        ck = self._corpus_key(corpus)
        imported = 0
        skipped = 0
        errors: List[dict] = []
        previews: List[dict] = []
        to_write: List[tuple[str, str, dict]] = []  # (row_id, slot, entry)
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                errors.append({"index": i, "error": "record must be an object"})
                skipped += 1
                continue
            rid = str(rec.get("row_id") or "").strip()
            if not rid:
                errors.append({"index": i, "error": lt("row_id fehlt", "row_id is missing")})
                skipped += 1
                continue
            category_id = rec.get("category_id")
            note = rec.get("note")
            if category_id is None and (note is None or not str(note).strip()):
                errors.append(
                    {
                        "index": i,
                        "row_id": rid,
                        "error": lt("category_id oder note erforderlich", "category_id or note required"),
                    }
                )
                skipped += 1
                continue
            if (
                category_id is not None
                and valid_category_ids is not None
                and str(category_id) not in valid_category_ids
            ):
                errors.append(
                    {
                        "index": i,
                        "row_id": rid,
                        "error": lt(
                            "unbekannte category_id: {category_id}", "unknown category_id: {category_id}"
                        ).format(category_id=category_id),
                    }
                )
                skipped += 1
                continue
            annotator = str(rec.get("annotator") or "").strip()
            slot = self._annotator_slot(annotator)
            entry = {
                "row_id": rid,
                "category_id": str(category_id) if category_id is not None else None,
                "note": str(note) if note is not None else None,
                "annotator": annotator,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
            previews.append({"row_id": rid, "annotator": entry["annotator"], "category_id": entry["category_id"]})
            to_write.append((rid, slot, entry))
            imported += 1
        if not dry_run and to_write:
            with self._lock:
                scoped = self._data["row_annotations"].setdefault(ck, {})
                for rid, slot, entry in to_write:
                    scoped.setdefault(rid, {})[slot] = entry
                self._save()
        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "previews": previews,
            "dry_run": bool(dry_run),
        }

    def log_op(self, op: str) -> None:
        with self._lock:
            self._data["timeline"].append(op)
            self._save()
        self._maybe_rotate()

    def timeline(self) -> List[str]:
        ops: List[str] = []
        for row in self._data["timeline"]:
            if not isinstance(row, str):
                continue
            if row.startswith("SNAPSHOT:"):
                data = row[len("SNAPSHOT:") :]
                if data.strip().startswith("{"):
                    try:
                        snap = json.loads(data)
                        ops.extend(snap.get("ops", []))
                        tree = snap.get("analysis_tree")
                        if tree is not None:
                            self.set_analysis_tree(tree)
                    except Exception:
                        logger.exception("Failed to parse snapshot entry in timeline")
                        raise
                elif data:
                    ops.extend(data.split("\n"))
            else:
                ops.append(row)
        return ops

    def replay(
        self,
        *,
        stop_event: threading.Event | None = None,
        callback: Callable[[int, int], None] | None = None,
        token: str | None = None,
    ) -> None:
        ops = self.timeline()
        total = len(ops)
        for i, op in enumerate(ops, 1):
            if stop_event is not None and stop_event.is_set():
                break
            self._apply_op(op, token=token)
            if callback:
                callback(i, total)

    def _apply_op(self, op: str, *, token: str | None = None) -> None:
        try:
            data = json.loads(op)
        except Exception:
            data = None
        if isinstance(data, dict) and data.get("tool"):
            import hashlib

            name = data.get("tool")
            params = data.get("params", {})
            expected = data.get("sha256")
            result: Any | None = None
            try:
                from candyconc.services.mcp_client import resolve_mcp_url

                mcp_url = resolve_mcp_url().rstrip("/") + "/call"
                payload = {"name": name, "arguments": params}
                if token:
                    payload["token"] = token
                resp = httpx.post(mcp_url, json=payload, timeout=30.0)
                resp.raise_for_status()
                result = resp.json()
            except httpx.HTTPError as exc:
                logger.error("Tool dispatch failed: %s", exc)
                raise RuntimeError("tool dispatch failed") from exc
            digest = hashlib.sha256(
                json.dumps(result, sort_keys=True).encode()
            ).hexdigest()
            if expected and digest != expected:
                raise ValueError("hash mismatch")
        elif isinstance(data, dict) and data.get("task"):
            name = data.get("task")
            expected = data.get("sha256")
            result: Any | None = None
            if name == "run_query":
                term = data.get("term")
                ctx = int(data.get("ctx", 5))
                try:
                    resp = httpx.get(
                        f"{APP_CONFIG.CANDYCONC_BACKEND_URL}/query",
                        params={"term": term, "ctx": ctx},
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    result = resp.json()
                except httpx.HTTPError:
                    result = None
            elif name == "collocate_stats":
                term = data.get("term")
                window = int(data.get("window", 5))
                try:
                    resp = httpx.get(
                        f"{APP_CONFIG.CANDYCONC_BACKEND_URL}/analysis/collocates",
                        params={"term": term, "window": window},
                        timeout=30.0,
                    )
                    resp.raise_for_status()
                    res_json = resp.json()
                    result = res_json.get("rows", res_json)
                except httpx.HTTPError:
                    result = None
            if expected:
                import hashlib

                digest = hashlib.sha256(
                    json.dumps(result, sort_keys=True).encode()
                ).hexdigest()
                if digest != expected:
                    raise ValueError("hash mismatch")
        elif op.startswith("search "):
            term = op.split(" ", 1)[1]
            try:
                resp = httpx.get(
                    f"{APP_CONFIG.CANDYCONC_BACKEND_URL}/query",
                    params={"term": term, "ctx": 5},
                    timeout=30.0,
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.exception("Failed to replay query operation")
                raise

    def record_metric(self, query: str, hits: int) -> None:
        with self._lock:
            self._data["metrics"].append({"query": query, "hits": int(hits)})
            self._save()

    def metrics(self) -> pd.DataFrame:
        return pd.DataFrame(self._data["metrics"], columns=["query", "hits"])

    def recent_queries(self, limit: int) -> List[str]:
        queries = [row.get("query") for row in self._data["metrics"] if row.get("query")]
        queries = list(reversed(queries))[:limit]
        if len(queries) < limit:
            ops = reversed(self.timeline())
            for op in ops:
                term = None
                try:
                    data = json.loads(op)
                    if isinstance(data, dict) and data.get("task") == "run_query":
                        term = data.get("term")
                except Exception:
                    if op.startswith("search "):
                        term = op.split(" ", 1)[1]
                if term:
                    queries.append(term)
                    if len(queries) >= limit:
                        break
        seen = set()
        deduped: List[str] = []
        for q in queries:
            if q and q not in seen:
                deduped.append(q)
                seen.add(q)
            if len(deduped) >= limit:
                break
        return deduped

    # Subcorpus handling -------------------------------------------------

    def save_subcorpus(
        self,
        name: str,
        query: str | None = None,
        *,
        corpus: str = "default",
        filter_spec: Dict[str, Any] | None = None,
        filter: str | None = None,
        include_ai: bool = True,
        include_human: bool = True,
        ai_filters: Dict[str, Any] | None = None,
        metadata_schema_hash: str = "",
        creator: str = "unknown",
        familien: bool = True,
    ) -> None:
        """Persist a durable named SubcorpusDefinition.

        ``filter_spec`` is the canonical (raw, pre-translate) meta_filters mapping —
        the basis for lazy re-resolution to the same doc set. The legacy
        ``query``/``filter`` fields are kept for back-compat; new callers pass
        ``filter_spec`` (+ ``corpus``/``ai_filters``/``include_*``).

        ``familien`` hält fest, ob eine Suchdefinition die Fassungsfamilien
        ihrer Trefferdokumente einschließt, wie docset_from_search sie baut.
        """
        created = datetime.utcnow().isoformat()
        with self._lock:
            # Subcorpus names are unique per project. Refuse to silently overwrite a
            # subcorpus that belongs to a DIFFERENT corpus (cross-corpus clobber / data
            # loss); the caller must pick a distinct name or delete the old one first.
            existing = self._data["subcorpora"].get(name)
            if isinstance(existing, dict) and str(existing.get("corpus") or "default") != str(corpus):
                raise ValueError(
                    lt(
                        "Subkorpus-Name '{name}' existiert bereits für Korpus "
                        "'{corpus}'; Namen müssen pro Projekt eindeutig sein.",
                        "Subcorpus name '{name}' already exists for corpus "
                        "'{corpus}'. Names must be unique within a project.",
                    ).format(name=name, corpus=existing.get("corpus"))
                )
            self._data["subcorpora"][name] = {
                "name": name,
                "corpus": corpus,
                "query": query or "",
                "filter_spec": filter_spec if isinstance(filter_spec, dict) else {},
                "filter": filter or "",
                "include_ai": bool(include_ai),
                "include_human": bool(include_human),
                "familien": bool(familien),
                "ai_filters": ai_filters if isinstance(ai_filters, dict) else {},
                "metadata_schema_hash": str(metadata_schema_hash or ""),
                "created_at": created,
                "creator": creator,
            }
            self._save()

    def subcorpora(self) -> List[Dict[str, str]]:
        return sorted(
            (row for row in self._data["subcorpora"].values()),
            key=lambda r: r.get("name", ""),
        )

    def get_subcorpus(self, name: str) -> Dict[str, str] | None:
        row = self._data["subcorpora"].get(name)
        return dict(row) if isinstance(row, dict) else None

    def delete_subcorpus(self, name: str) -> Dict[str, Any] | None:
        """Delete the named subcorpus; return the removed definition (or ``None``).

        Returning the removed row lets the route layer enforce ownership without a
        check-then-act TOCTOU race: the caller can assert the removed definition's
        ``creator`` under the same lock-protected pop.
        """
        with self._lock:
            removed = self._data["subcorpora"].pop(name, None)
            if removed is not None:
                self._save()
        return dict(removed) if isinstance(removed, dict) else None

    # Macro handling ----------------------------------------------------

    def save_macro(self, name: str, template: str) -> None:
        with self._lock:
            self._data["macros"][name] = template
            self._save()

    def delete_macro(self, name: str) -> None:
        with self._lock:
            self._data["macros"].pop(name, None)
            self._save()

    def macros(self) -> Dict[str, str]:
        return dict(self._data["macros"])

    # Filter state -----------------------------------------------------

    def set_filter_state(self, corpus: str, state: Dict[str, str | None]) -> None:
        with self._lock:
            self._data["filter_state"][corpus] = dict(state)
            self._save()

    def get_filter_state(self, corpus: str) -> Dict[str, str | None]:
        data = self._data["filter_state"].get(corpus)
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
        return {}

    # Settings -----------------------------------------------------------

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._data["settings"][key] = value
            self._save()

    def get_setting(self, key: str) -> str | None:
        val = self._data["settings"].get(key)
        return str(val) if val is not None else None

    def set_active_node(self, node_id: int) -> None:
        self.set_setting("active_node", str(node_id))

    def get_active_node(self) -> int | None:
        val = self.get_setting("active_node")
        if val is None:
            return None
        try:
            return int(val)
        except Exception:
            return None

    # Project metadata ---------------------------------------------------

    def set_description(self, description: str) -> None:
        with self._lock:
            self._data["project"]["description"] = description
            self._save()

    def get_description(self) -> str:
        return str(self._data["project"].get("description", ""))

    # AI Outputs ---------------------------------------------------------

    def add_ai_output(self, data: str) -> None:
        with self._lock:
            self._data["ai_outputs"].append(data)
            self._save()

    def remove_ai_output(self, data: str) -> None:
        with self._lock:
            self._data["ai_outputs"] = [
                row for row in self._data["ai_outputs"] if row != data
            ]
            self._save()

    def ai_outputs(self) -> List[str]:
        return list(self._data["ai_outputs"])

    # Span annotations ---------------------------------------------------

    def add_span_annotation(
        self, line_id: int, start: int, end: int, tag: str, annotator: str
    ) -> None:
        with self._lock:
            self._data["span_annotations"].append(
                {
                    "line_id": int(line_id),
                    "start": int(start),
                    "end": int(end),
                    "tag": tag,
                    "annotator": annotator,
                }
            )
            current = int(self._data["annotation_progress"].get(annotator, 0))
            self._data["annotation_progress"][annotator] = current + 1
            self._save()

    def span_annotations(self, annotator: str | None = None) -> List[dict]:
        if annotator:
            return [
                row
                for row in self._data["span_annotations"]
                if row.get("annotator") == annotator
            ]
        return list(self._data["span_annotations"])

    def annotator_progress(self, annotator: str) -> int:
        return int(self._data["annotation_progress"].get(annotator, 0))

    def set_annotator_progress(self, annotator: str, progress: int) -> None:
        with self._lock:
            self._data["annotation_progress"][annotator] = int(progress)
            self._save()

    # Jobs ---------------------------------------------------------------

    def _next_job_id(self) -> int:
        max_id = 0
        for row in self._data["jobs"]:
            try:
                max_id = max(max_id, int(row.get("id", 0)))
            except Exception:
                continue
        return max_id + 1

    def add_job(self, term: str, ctx: int = 5) -> int:
        with self._lock:
            job_id = self._next_job_id()
            self._data["jobs"].append(
                {
                    "id": job_id,
                    "term": term,
                    "ctx": int(ctx),
                    "status": "queued",
                    "result": 0,
                }
            )
            self._save()
        return int(job_id)

    def update_job(self, job_id: int, status: str, result: int) -> None:
        with self._lock:
            for row in self._data["jobs"]:
                if int(row.get("id", -1)) == int(job_id):
                    row["status"] = status
                    row["result"] = int(result)
                    break
            self._save()

    def job_status(self) -> Dict[int, str]:
        return {
            int(row.get("id")): str(row.get("status"))
            for row in self._data["jobs"]
        }

    # Analysis tree ------------------------------------------------------

    def set_analysis_tree(self, data: str | None) -> None:
        with self._lock:
            self._data["analysis_tree"] = data
            self._save()

    def get_analysis_tree(self) -> str | None:
        val = self._data.get("analysis_tree")
        return str(val) if val is not None else None

    # Snapshot rotation --------------------------------------------------

    def _rotate_snapshot(self, ops: List[str]) -> None:
        tree = self.get_analysis_tree() or ""
        payload = json.dumps({"ops": ops, "analysis_tree": tree})
        snapshot = "SNAPSHOT:" + payload
        with self._lock:
            self._data["timeline"] = [snapshot]
            self._save()

    def _maybe_rotate(self) -> None:
        count = len(self._data["timeline"])
        size = self.path.stat().st_size if self.path.exists() else 0
        if count >= self.rotation_ops or size >= self.rotation_bytes:
            ops = self.timeline()
            if ops:
                self._rotate_snapshot(ops)

    def undo_last(self) -> None:
        with self._lock:
            if not self._data["timeline"]:
                return
            self._data["timeline"].pop()
            self._save()
        self.replay()

    def export_project(self, zip_path: str | Path) -> None:
        self._save()
        root = Path(self.path).resolve().parent
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in root.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(root))

    def import_project(self, zip_path: str | Path) -> None:
        root = Path(self.path).resolve().parent
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Zip-Slip guard: every member must resolve to a path INSIDE root, else a
            # crafted entry ("../../etc/x" or an absolute path) could write outside the
            # project dir during extractall.
            for member in zf.namelist():
                dest = (root / member).resolve()
                if dest != root and root not in dest.parents:
                    raise ValueError(
                        lt(
                            "Unsicherer Pfad im Projekt-Zip: {member!r}",
                            "Unsafe path in the project ZIP: {member!r}",
                        ).format(member=member)
                    )
            zf.extractall(root)
        self._data = self._load()
        self._save()


def prepare_project_migration(path: str | Path) -> dict:
    """Read and normalize a legacy project without writing any file."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ProjectMigrationError(
            lt("Projektdatei nicht gefunden: {path}", "Project file not found: {path}").format(path=source)
        )
    raw = source.read_bytes()
    if raw.startswith(_SQLITE_MAGIC):
        return Project._read_legacy_sqlite(source)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProjectMigrationError(
            lt("Projektdatei ist kein lesbares JSON: {path}", "Project file is not readable JSON: {path}").format(
                path=source
            )
        ) from exc
    if not isinstance(data, dict):
        raise ProjectMigrationError(
            lt("Projektdatei enthält kein JSON-Objekt: {path}", "Project file contains no JSON object: {path}").format(
                path=source
            )
        )
    return Project._ensure_schema(data)


def project_inventory(data: dict) -> dict[str, int]:
    """Return the user-data counts that must survive an explicit migration."""
    row_annotations = data.get("row_annotations", {})
    row_annotation_count = sum(
        len(coders)
        for rows in row_annotations.values()
        if isinstance(rows, dict)
        for coders in rows.values()
        if isinstance(coders, dict)
    ) if isinstance(row_annotations, dict) else 0
    coding_scheme = data.get("coding_scheme", {})
    categories = coding_scheme.get("categories", []) if isinstance(coding_scheme, dict) else []
    category_count = len(categories) if isinstance(categories, list) else 0
    coding_schemes = data.get("coding_schemes", {})
    if isinstance(coding_schemes, dict):
        for scheme in coding_schemes.values():
            own = scheme.get("categories", []) if isinstance(scheme, dict) else []
            category_count += len(own) if isinstance(own, list) else 0
    return {
        "bookmarks": len(data.get("bookmarks", {})),
        "annotations": len(data.get("annotations", {})),
        "comments": len(data.get("comments", {})),
        "timeline": len(data.get("timeline", [])),
        "metrics": len(data.get("metrics", [])),
        "subcorpora": len(data.get("subcorpora", {})),
        "filter_state": len(data.get("filter_state", {})),
        "settings": len(data.get("settings", {})),
        "ai_outputs": len(data.get("ai_outputs", [])),
        "macros": len(data.get("macros", {})),
        "jobs": len(data.get("jobs", [])),
        "span_annotations": len(data.get("span_annotations", [])),
        "annotation_progress": len(data.get("annotation_progress", {})),
        "row_annotations": row_annotation_count,
        "coding_categories": category_count,
    }


def write_migrated_project(
    path: str | Path, data: dict, *, overwrite: bool = False
) -> None:
    """Write an explicitly approved migration target, never an implicit one."""
    target = Path(path).expanduser().resolve()
    if target.exists() and not overwrite:
        raise ProjectMigrationError(
            lt("Migrationsziel existiert bereits: {path}", "Migration target already exists: {path}").format(
                path=target
            )
        )
    _write_project_json(target, data)


# Project-wide export helper

def export_project(conc: Concordance, path: str) -> None:
    """Export the current concordance to *path* as folder or ZIP."""
    as_zip = str(path).lower().endswith(".zip")

    refs: list[tuple[object, object]] = []

    def _strip(node) -> None:
        refs.append((node, getattr(node, "concordance", None)))
        if hasattr(node, "concordance"):
            node.concordance = None
        for child in getattr(node, "children", []):
            _strip(child)

    _strip(conc.root)
    conc.export(path, as_zip=as_zip)

    html_path = conc.info.get("html_export")
    if html_path and Path(html_path).exists():
        if as_zip:
            zip_dest = Path(path)
            if zip_dest.suffix != ".zip":
                zip_dest = zip_dest.with_suffix(".zip")
            with zipfile.ZipFile(zip_dest, "a", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(html_path, Path(html_path).name)
        else:
            dest_dir = Path(path)
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(html_path, dest_dir / Path(html_path).name)

    for node, ref in refs:
        setattr(node, "concordance", ref)
