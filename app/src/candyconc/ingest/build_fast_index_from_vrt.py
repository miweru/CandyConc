from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from candyconc.core.pairing import STANDALONE

#: The Parquet builder that indexes the VRT text when spaCy annotates it.
FAST_INDEX_BUILDER = Path(__file__).with_name("build_fast_index_from_parquet.py")
_FAST_INDEX_BUILDER_MODULE = "candyconc.ingest.build_fast_index_from_parquet"
logger = logging.getLogger(__name__)

WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"^\s*<\s*(/?)\s*([A-Za-z_][\w:.-]*)(.*?)\s*(/?)\s*>\s*$")

DEFAULT_ID_ATTRS = ("id", "xml:id", "num", "n", "sid", "sent_id", "segment_id", "chunk_id")
DEFAULT_DATE_ATTRS = ("date", "timestamp", "time", "created", "published")
DEFAULT_REGISTER_ATTRS = ("register", "textclass", "domain", "subtype")
DEFAULT_GENRE_ATTRS = ("genre", "register", "textclass", "domain", "subtype")
DEFAULT_SOURCE_ATTRS = ("source", "source_id", "corpus", "name")
DEFAULT_COLUMNS = ("word", "lemma", "pos", "morph")

NO_SPACE_BEFORE = set(".,;:!?)]}%")
NO_SPACE_AFTER = set("([{")
QUOTE_CHARS = {"'", '"', "\u00bb", "\u00ab", "\u201e", "\u201c", "\u201d"}


@dataclass
class TagEvent:
    name: str
    attrs: dict[str, str]
    closing: bool = False
    self_closing: bool = False


@dataclass
class VrtToken:
    values: dict[str, str]
    line_no: int
    sent_start: bool = False


@dataclass
class VrtDocument:
    row: dict[str, str]
    annotations: list[dict[str, str]]
    start_line: int
    end_line: int
    warnings: list[str] = field(default_factory=list)
    # Token indices (into ``annotations``) that open a sentence, derived from the
    # configured sentence tag (default ``<s>``). Empty when the input carries no
    # sentence tags; consumers treat the document start as an implicit sentence
    # start either way.
    sent_starts: list[int] = field(default_factory=list)


@dataclass
class VrtParseConfig:
    segment_tag: str
    text_tag: str
    sentence_tag: str
    token_columns: list[str]
    token_separator: str
    word_column: str
    source_default: str
    register_default: str
    min_text_chars: int
    variant: str
    model: str
    id_attrs: tuple[str, ...]
    source_attrs: tuple[str, ...]
    register_attrs: tuple[str, ...]
    date_attrs: tuple[str, ...]
    genre_attrs: tuple[str, ...]
    strict_columns: bool
    join_mode: str
    # Structure attributes to preserve as document metadata. Empty keeps only
    # the mapped id/source/register/date/genre roles. ("*",) preserves all
    # attributes of the segment or text tag.
    carry_attrs: tuple[str, ...] = ()


@dataclass
class VrtParseStats:
    documents: int = 0
    tokens: int = 0
    tag_lines: int = 0
    token_lines: int = 0
    skipped_short_docs: int = 0
    skipped_outside_docs: int = 0
    inconsistent_column_lines: int = 0
    inferred_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Bookkeeping of EVERY structural attribute seen and of what reaches the
    # index. A data loss must be countable, otherwise nobody notices it (five
    # speaker attributes of a parliamentary corpus can disappear without any
    # message).
    seen_attrs: dict[str, int] = field(default_factory=dict)
    kept_attrs: set[str] = field(default_factory=set)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def note_attrs(self, attrs: dict[str, str], kept: dict[str, str]) -> None:
        for name in attrs:
            self.seen_attrs[name] = self.seen_attrs.get(name, 0) + 1
        self.kept_attrs.update(kept)

    def dropped_attrs(self, cfg: "VrtParseConfig") -> dict[str, int]:
        """Attribute, die gesehen, aber NIRGENDS im Index gelandet sind."""
        gemappt = set()
        for rolle in (
            cfg.id_attrs,
            cfg.source_attrs,
            cfg.register_attrs,
            cfg.date_attrs,
            cfg.genre_attrs,
        ):
            gemappt.update(name.lower() for name in rolle)
        return {
            name: anzahl
            for name, anzahl in sorted(self.seen_attrs.items())
            if name not in gemappt and name not in self.kept_attrs
        }


def _clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value.strip())


def _split_csv(value: str, default: Iterable[str] = ()) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in value.split(",") if part.strip())
    return parts or tuple(default)


_XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"


def _normalize_attrs(attrs: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in attrs.items():
        text = str(value).strip()
        if not text:
            continue
        lowered = key.strip().lower()
        if lowered.startswith("{") and "}" in lowered:
            # ElementTree writes xml:id as {http://www.w3.org/XML/1998/namespace}id.
            namespace, local = lowered[1:].split("}", 1)
            normalized[local] = text
            if namespace == _XML_NAMESPACE.lower():
                normalized[f"xml:{local}"] = text
            continue
        normalized[lowered] = text
        if ":" in lowered:
            normalized[lowered.split(":", 1)[1]] = text
    return normalized


def _pick_attr(attrs: dict[str, str], keys: Iterable[str]) -> str:
    normalized = _normalize_attrs(attrs)
    for key in keys:
        value = normalized.get(key.lower())
        if value:
            return value
    return ""


def _parse_attrs(tag_name: str, raw_attrs: str) -> dict[str, str]:
    raw_attrs = raw_attrs.strip()
    if not raw_attrs:
        return {}
    try:
        elem = ET.fromstring(f"<{tag_name} {raw_attrs} />")
        return {str(k): str(v) for k, v in elem.attrib.items()}
    except ET.ParseError:
        # VRT attributes are usually XML-ish. Keep parsing tolerant for legacy files.
        attrs: dict[str, str] = {}
        for match in re.finditer(r"""([\w:.-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""", raw_attrs):
            attrs[match.group(1)] = match.group(3) or match.group(4) or match.group(5) or ""
        return attrs


def _parse_tag_line(line: str) -> TagEvent | None:
    match = TAG_RE.match(line)
    if not match:
        return None
    closing = bool(match.group(1))
    name = match.group(2).lower()
    raw_attrs = match.group(3).strip()
    self_closing = bool(match.group(4)) or raw_attrs.endswith("/")
    if raw_attrs.endswith("/"):
        raw_attrs = raw_attrs[:-1].strip()
    attrs = {} if closing else _parse_attrs(name, raw_attrs)
    return TagEvent(name=name, attrs=attrs, closing=closing, self_closing=self_closing)


def _split_token_line(line: str, separator: str) -> list[str]:
    stripped = line.rstrip("\n\r")
    if separator == "tab":
        return stripped.split("\t")
    if separator == "whitespace":
        return stripped.split()
    if "\t" in stripped:
        return stripped.split("\t")
    return stripped.split()


def _infer_columns(width: int) -> list[str]:
    if width <= len(DEFAULT_COLUMNS):
        return list(DEFAULT_COLUMNS[:width])
    return list(DEFAULT_COLUMNS) + [f"extra_{idx}" for idx in range(len(DEFAULT_COLUMNS), width)]


def _resolve_column(columns: list[str], selector: str, *, default: int = 0) -> int:
    selector = selector.strip()
    if selector in columns:
        return columns.index(selector)
    if selector.isdigit():
        idx = int(selector)
        if 0 <= idx < len(columns):
            return idx
        if 1 <= idx <= len(columns):
            return idx - 1
    return default


def _token_values(
    line: str,
    line_no: int,
    columns: list[str],
    separator: str,
    stats: VrtParseStats,
    strict_columns: bool,
) -> dict[str, str]:
    parts = _split_token_line(line, separator)
    if not parts:
        return {}
    if not columns:
        columns.extend(_infer_columns(len(parts)))
        stats.inferred_columns = list(columns)
    if len(parts) != len(columns):
        stats.inconsistent_column_lines += 1
        message = f"line {line_no}: expected {len(columns)} columns, got {len(parts)}"
        if strict_columns:
            raise SystemExit(message)
        if len(parts) > len(columns):
            for idx in range(len(columns), len(parts)):
                columns.append(f"extra_{idx}")
        else:
            parts.extend([""] * (len(columns) - len(parts)))
    return {name: parts[idx].strip() for idx, name in enumerate(columns)}


def _join_tokens(tokens: list[str], mode: str) -> str:
    cleaned = [tok for tok in (_clean_text(token) for token in tokens) if tok]
    if mode == "space":
        return " ".join(cleaned)
    out: list[str] = []
    prev = ""
    open_quote = False
    for token in cleaned:
        if not out:
            out.append(token)
        elif token in QUOTE_CHARS:
            if open_quote:
                out[-1] = out[-1] + token
            else:
                out.append(token)
            open_quote = not open_quote
        elif token[0] in NO_SPACE_BEFORE or prev[-1:] in NO_SPACE_AFTER:
            out[-1] = out[-1] + token
        else:
            out.append(token)
        prev = token
    return " ".join(out)


#: Feldnamen, die der Importer selbst belegt. Ein durchgereichtes
#: Struktur-Attribut darf sie nie ueberschreiben, sonst zerbricht die
#: Dokument-Identitaet.
RESERVIERTE_META_FELDER = frozenset(
    {
        "origin_id",
        "origin_doc_id",
        "doc_id",
        "path",
        "source",
        "register",
        "date",
        "genre",
        "variant",
        "model",
        "text_type",
        "reference_hash",
        "reference_kind",
        "paired_with",
    }
)


def _carried_attrs(
    attrs: dict[str, str], carry: tuple[str, ...]
) -> dict[str, str]:
    """Preserve selected structural attributes as document metadata.

Segment tags can contain analysis variables beyond the mapped id, source,
register, date and genre roles. Keep requested attributes while protecting
reserved field names."""
    if not carry:
        return {}
    normalisiert = _normalize_attrs(attrs)
    alle = "*" in carry
    ergebnis: dict[str, str] = {}
    for name, wert in normalisiert.items():
        if not alle and name not in carry:
            continue
        if name in RESERVIERTE_META_FELDER:
            continue
        wert = str(wert or "").strip()
        if wert:
            ergebnis[name] = wert
    return ergebnis


def _current_attrs(stack: list[TagEvent], cfg: VrtParseConfig) -> dict[str, str]:
    merged: dict[str, str] = {}
    for event in stack:
        if event.name == cfg.text_tag or event.name == cfg.segment_tag:
            merged.update(event.attrs)
    return merged


def _normalize_tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1].lower()
    return tag.lower()


def _inline_xml_documents(
    line: str,
    path: Path,
    cfg: VrtParseConfig,
    stats: VrtParseStats,
    line_no: int,
    doc_count: int,
) -> list[VrtDocument]:
    try:
        root = ET.fromstring(line)
    except ET.ParseError:
        return []
    matches = [elem for elem in root.iter() if _normalize_tag_name(elem.tag) == cfg.segment_tag]
    if not matches:
        return []
    docs: list[VrtDocument] = []
    for offset, elem in enumerate(matches, start=1):
        text = _clean_text(" ".join(elem.itertext()))
        if not text:
            continue
        attrs = {str(k): str(v) for k, v in root.attrib.items()}
        attrs.update({str(k): str(v) for k, v in elem.attrib.items()})
        tokens = [
            VrtToken(values={"word": token}, line_no=line_no)
            for token in text.split()
        ]
        doc = _row_for_doc(
            path,
            tokens,
            attrs,
            doc_count + offset,
            line_no,
            line_no,
            cfg,
            ["word"],
            stats,
        )
        if doc and doc.row:
            docs.append(doc)
        elif doc and "short_document" in doc.warnings:
            stats.skipped_short_docs += 1
    return docs


def _doc_id_for(path: Path, attrs: dict[str, str], count: int, cfg: VrtParseConfig) -> str:
    picked = _pick_attr(attrs, cfg.id_attrs)
    return picked or f"{path.stem}_{count}"


def _row_for_doc(
    path: Path,
    tokens: list[VrtToken],
    attrs: dict[str, str],
    doc_count: int,
    start_line: int,
    end_line: int,
    cfg: VrtParseConfig,
    columns: list[str],
    stats: VrtParseStats,
) -> VrtDocument | None:
    if not tokens:
        return None
    word_idx = _resolve_column(columns, cfg.word_column, default=0)
    word_col = columns[word_idx] if columns else cfg.word_column
    surface_tokens = [tok.values.get(word_col, "") for tok in tokens]
    text = _join_tokens(surface_tokens, cfg.join_mode)
    if not text or len(text) < cfg.min_text_chars:
        return VrtDocument(
            row={},
            annotations=[],
            start_line=start_line,
            end_line=end_line,
            warnings=["short_document"],
        )

    doc_id = _doc_id_for(path, attrs, doc_count, cfg)
    source = _pick_attr(attrs, cfg.source_attrs) or cfg.source_default
    register = _pick_attr(attrs, cfg.register_attrs) or cfg.register_default
    date = _pick_attr(attrs, cfg.date_attrs)
    genre = _pick_attr(attrs, cfg.genre_attrs)
    annotation_columns = [col for col in columns if col != word_col]
    source_meta = {
        "vrt_source_file": path.name,
        "vrt_line_start": str(start_line),
        "vrt_line_end": str(end_line),
        "vrt_unit_tag": cfg.segment_tag,
        "vrt_text_tag": cfg.text_tag,
        "vrt_word_column": word_col,
        "vrt_token_columns": ",".join(columns),
        "vrt_annotation_columns": ",".join(annotation_columns),
        "vrt_token_count": str(len(tokens)),
    }
    getragen = _carried_attrs(attrs, cfg.carry_attrs)
    source_meta.update(getragen)
    stats.note_attrs(_normalize_attrs(attrs), getragen)
    row = {
        "doc_id": doc_id,
        "source": source,
        "input_text": text,
        "source_text": text,
        "target_text": text,
        "variant": cfg.variant,
        "model": cfg.model,
        # VRT documents are unpaired. "human" would claim the anchor side of a
        # human/AI pair (core.pairing), as the research layout records it.
        "text_type": STANDALONE,
        "register": register,
        "genre": genre,
        "date": date,
        "pair_id": doc_id,
        "origin_id": doc_id,
        "source_meta": json.dumps(source_meta, ensure_ascii=False),
    }
    annotations = [dict(token.values) | {"_line": str(token.line_no)} for token in tokens]
    sent_starts = [idx for idx, token in enumerate(tokens) if token.sent_start]
    return VrtDocument(
        row=row,
        annotations=annotations,
        start_line=start_line,
        end_line=end_line,
        sent_starts=sent_starts,
    )


def iter_vrt_documents(path: Path, cfg: VrtParseConfig, stats: VrtParseStats | None = None) -> Iterator[VrtDocument]:
    stats = stats or VrtParseStats()
    tag_stack: list[TagEvent] = []
    columns = list(cfg.token_columns)
    active_tokens: list[VrtToken] | None = None
    active_attrs: dict[str, str] = {}
    active_start_line = 0
    doc_count = 0
    # An opening sentence tag (default <s>) marks the NEXT token line as a
    # sentence start. The flag survives a lazily started document so the first
    # token after "<s>" is flagged even when the doc opens on that token line.
    pending_sentence_start = False

    def start_doc(line_no: int, attrs: dict[str, str]) -> None:
        nonlocal active_tokens, active_attrs, active_start_line
        active_tokens = []
        active_attrs = attrs
        active_start_line = line_no

    def finish_doc(line_no: int) -> VrtDocument | None:
        nonlocal active_tokens, active_attrs, active_start_line, doc_count
        if active_tokens is None:
            return None
        doc_count += 1
        doc = _row_for_doc(path, active_tokens, active_attrs, doc_count, active_start_line, line_no, cfg, columns, stats)
        active_tokens = None
        active_attrs = {}
        active_start_line = 0
        if doc and doc.row:
            stats.documents += 1
            stats.tokens += len(doc.annotations)
        elif doc and "short_document" in doc.warnings:
            stats.skipped_short_docs += 1
        return doc

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            if "><" in stripped or ("</" in stripped and not stripped.startswith("</")):
                inline_docs = _inline_xml_documents(stripped, path, cfg, stats, line_no, doc_count)
                if inline_docs:
                    stats.tag_lines += 1
                    for doc in inline_docs:
                        doc_count += 1
                        stats.documents += 1
                        stats.tokens += len(doc.annotations)
                        yield doc
                    continue

            tag = _parse_tag_line(stripped)
            if tag:
                stats.tag_lines += 1
                if tag.closing:
                    if tag.name == cfg.segment_tag and active_tokens is not None:
                        doc = finish_doc(line_no)
                        if doc:
                            yield doc
                    elif tag.name == cfg.text_tag and active_tokens is not None:
                        doc = finish_doc(line_no)
                        if doc:
                            yield doc
                    for idx in range(len(tag_stack) - 1, -1, -1):
                        if tag_stack[idx].name == tag.name:
                            del tag_stack[idx:]
                            break
                    continue

                tag_stack.append(tag)
                if tag.name == cfg.sentence_tag:
                    pending_sentence_start = True
                if tag.name == cfg.segment_tag:
                    if active_tokens is not None:
                        stats.warn(f"line {line_no}: nested segment started before previous segment closed")
                        doc = finish_doc(line_no - 1)
                        if doc:
                            yield doc
                    start_doc(line_no, _current_attrs(tag_stack, cfg))
                if tag.self_closing and tag_stack and tag_stack[-1].name == tag.name:
                    tag_stack.pop()
                continue

            stats.token_lines += 1
            if active_tokens is None:
                attrs = _current_attrs(tag_stack, cfg)
                if attrs or not cfg.segment_tag:
                    start_doc(line_no, attrs)
                else:
                    stats.skipped_outside_docs += 1
                    continue
            values = _token_values(
                stripped,
                line_no,
                columns,
                cfg.token_separator,
                stats,
                cfg.strict_columns,
            )
            if values:
                active_tokens.append(
                    VrtToken(
                        values=values,
                        line_no=line_no,
                        sent_start=pending_sentence_start or not active_tokens,
                    )
                )
                pending_sentence_start = False

    if active_tokens is not None:
        doc = finish_doc(line_no if "line_no" in locals() else 0)
        if doc:
            yield doc
    if not columns and stats.documents == 0:
        stats.warn("no token columns detected")


def _write_parquet_and_sidecar(
    docs: Iterable[VrtDocument],
    parquet_path: Path,
    annotation_sidecar: Path | None,
) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise SystemExit(f"pyarrow is missing: {exc}") from exc

    schema = pa.schema(
        [
            ("doc_id", pa.string()),
            ("source", pa.string()),
            ("input_text", pa.string()),
            ("source_text", pa.string()),
            ("target_text", pa.string()),
            ("variant", pa.string()),
            ("model", pa.string()),
            ("text_type", pa.string()),
            ("register", pa.string()),
            ("genre", pa.string()),
            ("date", pa.string()),
            ("pair_id", pa.string()),
            ("origin_id", pa.string()),
            ("source_meta", pa.string()),
        ]
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(parquet_path, schema=schema)
    sidecar_fh = annotation_sidecar.open("w", encoding="utf-8") if annotation_sidecar else None
    count = 0
    batch: list[dict[str, str]] = []
    try:
        for doc in docs:
            if not doc.row:
                continue
            row = {key: str(value or "") for key, value in doc.row.items()}
            batch.append(row)
            if sidecar_fh is not None:
                sidecar_fh.write(
                    json.dumps(
                        {
                            "doc_id": row["doc_id"],
                            "origin_id": row["origin_id"],
                            "start_line": doc.start_line,
                            "end_line": doc.end_line,
                            "tokens": doc.annotations,
                        },
                        ensure_ascii=False,
                    )
                )
                sidecar_fh.write("\n")
            if len(batch) >= 2048:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                count += len(batch)
                batch = []
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
            count += len(batch)
    finally:
        writer.close()
        if sidecar_fh is not None:
            sidecar_fh.close()
    return count


# ---------------------------------------------------------------------------
# annotation_mode=adopt: mitgelieferte VRT-Gold-Spalten (lemma/pos, optional
# morph) werden ROH in die abfragbaren Index-Token-Spalten uebernommen — kein
# spaCy-Tagging, kein Mapping auf das UD-Inventar. Leere Gold-Werte ("" oder
# das CoNLL-Platzhalterzeichen "_") bleiben leer (Lexikon-ID 0); es wird NIE
# still spaCy beigemischt. Die Tokenisierung ist die VRT-Tokenisierung
# (token-per-line), Satzgrenzen kommen aus dem konfigurierten Satz-Tag.
# ---------------------------------------------------------------------------

GOLD_MISSING_VALUES = {"", "_"}
ADOPTABLE_COLUMNS = ("lemma", "pos", "morph")
_INDEX_BACKEND_MODULE = _FAST_INDEX_BUILDER_MODULE


def _load_index_backend():
    """Import the parquet index backend module (owns ``build_index_from_token_docs``).

    Reuses an already-imported module instance when present so logger/config
    state is shared; falls back to a file-location load for stripped layouts.
    """
    existing = sys.modules.get(_INDEX_BACKEND_MODULE)
    if existing is not None:
        return existing
    try:
        import importlib

        return importlib.import_module(_INDEX_BACKEND_MODULE)
    except Exception:
        import importlib.util

        builder_path = _resolve_builder()
        spec = importlib.util.spec_from_file_location(_INDEX_BACKEND_MODULE, builder_path)
        if spec is None or spec.loader is None:
            raise SystemExit("Index backend (build_fast_index_from_parquet.py) cannot be loaded.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[_INDEX_BACKEND_MODULE] = module
        spec.loader.exec_module(module)
        return module


class _GoldStringStore:
    """Minimal StringStore-Ersatz: bijektive value<->key-Abbildung, Key 0 = leer.

    Das Index-Backend loest rohe to_array-Werte ueber ``strings[key]`` in
    Lexikon-Strings auf; hier sind die Keys einfach fortlaufende positive ints,
    also keine Hash-Kollisions- oder Truncation-Risiken wie beim Umweg ueber
    echte spaCy-Attribute (deren POS-Feld nur UD-Tags akzeptiert).
    """

    def __init__(self) -> None:
        self._value_by_key: dict[int, str] = {}
        self._key_by_value: dict[str, int] = {}

    def add(self, value: str) -> int:
        if not value:
            return 0
        key = self._key_by_value.get(value)
        if key is None:
            key = len(self._key_by_value) + 1
            self._key_by_value[value] = key
            self._value_by_key[key] = value
        return key

    def __getitem__(self, key):  # int -> str (Backend-Richtung)
        if isinstance(key, str):
            return self._key_by_value[key]
        idx = int(key)
        if idx == 0:
            return ""
        return self._value_by_key[idx]


class _GoldVocab:
    __slots__ = ("strings", "vectors_length")

    def __init__(self, strings: _GoldStringStore) -> None:
        self.strings = strings
        self.vectors_length = 0


class _GoldDoc:
    """Vorgebaute Token-Matrix im to_array-Kontrakt des Index-Backends.

    Spaltenordnung: ORTH, LEMMA, POS, MORPH, SENT_START (das Backend fordert
    genau diese Liste an, solange NER/Deps/Whitespace-Capture deaktiviert
    sind — ``to_array`` verifiziert das und schlaegt sonst laut fehl).
    """

    __slots__ = ("_array",)

    def __init__(self, array) -> None:
        self._array = array

    def __len__(self) -> int:
        return int(self._array.shape[0])

    def to_array(self, attr_list):
        from spacy import attrs  # noqa: PLC0415 - nur Konstanten, kein Modell

        expected = [attrs.ORTH, attrs.LEMMA, attrs.POS, attrs.MORPH, attrs.SENT_START]
        if list(attr_list) != expected:
            raise RuntimeError(
                "Gold-Adopt: Index-Backend fordert eine unerwartete Attributliste an "
                f"({attr_list!r}); der Adopt-Pfad unterstuetzt nur ORTH/LEMMA/POS/MORPH/SENT_START."
            )
        return self._array


class _GoldPipeline:
    """nlp-Fassade fuer build_index_from_token_docs: reiner Pass-through-Pipe.

    ``pipe_names`` bleibt leer (kein Sentencizer -> keine Seam-Heuristik) und
    ``vectors_length`` 0 (Embeddings sind im Adopt-Pfad deaktiviert).
    """

    def __init__(self) -> None:
        self.vocab = _GoldVocab(_GoldStringStore())
        self.pipe_names: list[str] = []

    def pipe(self, docs, as_tuples: bool = False, batch_size: int = 0, n_process: int = 0):
        yield from docs


def _adopt_meta_for_row(backend, row: dict[str, str], source_meta: dict, origin_id: str, ref_hash: str) -> dict:
    """Doc metadata of an unpaired VRT document, as ``_build_doc_stream`` writes it.

    The document keeps its VRT ID and claims no pair fields, like a document
    of a CSV or JSON Lines import. ``ref_hash`` stays part of the dedup key
    only.
    """

    def _s(value: object) -> str | None:
        text = str(value or "")
        return text if text.strip() else None

    meta: dict = {
        "source": _s(row.get("source")),
        "register": _s(row.get("register")),
    }
    date = _s(row.get("date"))
    if date:
        meta["date"] = date
    genre = _s(row.get("genre"))
    if genre:
        meta["genre"] = genre
    backend._merge_scalar_meta(meta, source_meta)
    doc_id = _s(row.get("doc_id")) or origin_id
    meta.update(
        {
            "doc_id": doc_id,
            "path": doc_id,
            "variant": _s(row.get("variant")) or "document",
            "model": _s(row.get("model")) or "none",
            "text_type": STANDALONE,
        }
    )
    return meta


def _adopt_doc_stream(backend, docs: Iterable[VrtDocument], cfg: VrtParseConfig, nlp: _GoldPipeline, pair_sink, adopt_stats: dict):
    """VRT-Dokumente in (GoldDoc, meta)-Tupel fuer das Index-Backend uebersetzen."""
    import numpy as np

    normalize = backend.normalize_text_basic
    strings = nlp.vocab.strings
    seen_keys: set = set()
    columns_checked = False

    for doc in docs:
        if not doc.row:
            continue
        row = doc.row
        try:
            source_meta = json.loads(row.get("source_meta") or "{}")
        except Exception:
            source_meta = {}
        if not isinstance(source_meta, dict):
            source_meta = {}
        word_col = str(source_meta.get("vrt_word_column") or cfg.word_column or "word")

        if not columns_checked:
            columns_checked = True
            available = sorted(
                {key for token in doc.annotations for key in token if key in ADOPTABLE_COLUMNS}
            )
            if not available:
                raise SystemExit(
                    "annotation_mode=adopt: the VRT column configuration has no adoptable "
                    "token columns (lemma/pos/morph). Check --token-columns "
                    "(for example word,lemma,pos,morph)."
                )

        origin_id = str(row.get("origin_id") or row.get("doc_id") or "")
        norm_text = normalize(str(row.get("target_text") or ""))
        ref_hash = backend._text_hash(norm_text)
        dedup_key = (origin_id, ref_hash, "source")
        if dedup_key in seen_keys:
            # Gleiche Kollaps-Semantik wie der Standardpfad (_build_doc_stream):
            # identische (origin_id, Texthash)-Dokumente werden nur einmal indexiert.
            adopt_stats["duplicate_docs_collapsed"] += 1
            continue
        seen_keys.add(dedup_key)

        sent_flags = set(doc.sent_starts)
        arr_rows: list[tuple[int, int, int, int, int]] = []
        for idx, token in enumerate(doc.annotations):
            word = normalize(str(token.get(word_col, ""))).strip()
            if not word:
                adopt_stats["skipped_empty_surface_tokens"] += 1
                continue

            def _gold_key(column: str, *, normalize_value: bool) -> int:
                if column not in token:
                    return 0
                adopt_stats["adopted_columns"].add(column)
                value = str(token.get(column, "")).strip()
                if normalize_value and value:
                    value = normalize(value).strip()
                if value in GOLD_MISSING_VALUES:
                    # Dokumentiertes Fallback: leer lassen (ID 0), NIE spaCy mischen.
                    empties = adopt_stats["empty_gold_values"]
                    empties[column] = int(empties.get(column, 0)) + 1
                    return 0
                return strings.add(value)

            lemma_key = _gold_key("lemma", normalize_value=True)
            pos_key = _gold_key("pos", normalize_value=False)
            morph_key = _gold_key("morph", normalize_value=False)
            sent_start = 1 if (idx in sent_flags or not arr_rows) else 0
            arr_rows.append((strings.add(word), lemma_key, pos_key, morph_key, sent_start))

        if not arr_rows:
            adopt_stats["skipped_empty_docs"] += 1
            continue

        meta = _adopt_meta_for_row(backend, row, source_meta, origin_id, ref_hash)
        meta["_anchor"] = dedup_key
        pair_sink.assign(dedup_key)
        adopt_stats["index_tokens"] += len(arr_rows)
        adopt_stats["index_documents"] += 1
        yield (_GoldDoc(np.asarray(arr_rows, dtype=np.int64)), meta)


def _run_adopt_build(input_path: Path, output_path: Path, cfg: VrtParseConfig, args: argparse.Namespace) -> int:
    backend = _load_index_backend()
    output_path.mkdir(parents=True, exist_ok=True)
    ctx = backend.BuildContext()
    pair_sink = backend.PairSink()
    nlp = _GoldPipeline()
    stats = VrtParseStats()
    adopt_stats: dict = {
        "adopted_columns": set(),
        "empty_gold_values": {},
        "skipped_empty_surface_tokens": 0,
        "skipped_empty_docs": 0,
        "duplicate_docs_collapsed": 0,
        "index_tokens": 0,
        "index_documents": 0,
    }
    meta_index_fields = [part.strip() for part in str(args.meta_index_fields or "").split(",") if part.strip()]

    docs = iter_vrt_documents(input_path, cfg, stats)
    doc_iter = _adopt_doc_stream(backend, docs, cfg, nlp, pair_sink, adopt_stats)

    build_info = {
        "source_parquet": None,
        "source_vrt": str(input_path),
        "spacy_model": None,
        "split_long_texts": False,
        "max_doc_chars": int(args.max_doc_chars),
        "include_prompts": False,
        "require_input_text": False,
        "import_mode": "vrt",
        "pair_axes": [],
        "annotation_source": "gold_vrt",
        # The VRT columns hold tokens without their spacing. The index keeps
        # no whitespace_after.bin and shows tokens separated by spaces.
        "whitespace": "pretokenized",
    }
    try:
        backend.build_index_from_token_docs(
            doc_iter,
            output_path,
            nlp=nlp,
            ner_enabled=False,
            deps_enabled=False,
            batch_size=max(int(args.batch_size or 0), 1),
            n_process=1,
            pair_sink=pair_sink,
            meta_index_fields=meta_index_fields or None,
            capture_whitespace=False,
            build_info=build_info,
            ctx=ctx,
        )
        backend._write_build_report(output_path, status="completed", ctx=ctx)
    except Exception as exc:
        backend._write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise

    # Provenienz sichtbar machen: index_build_meta.json traegt Annotationsquelle
    # und Tagset-Ehrlichkeit (roh, KEIN UD-Mapping); das Manifest traegt
    # annotation_source='gold_vrt' bereits ueber build_info.
    build_meta_path = output_path / "index_build_meta.json"
    if build_meta_path.exists():
        try:
            build_meta = json.loads(build_meta_path.read_text("utf-8"))
        except Exception:
            build_meta = {}
        build_meta["source_vrt"] = str(input_path)
        build_meta["annotation_mode"] = "adopt"
        build_meta["annotation_source"] = "gold_vrt"
        build_meta["tagset"] = "raw"
        # Record the source archive hash so index provenance can be checked
        # against the archive used for import.
        archiv = _archiv_sha256(args)
        if archiv:
            build_meta["source_archive_sha256"] = archiv
        build_meta_path.write_text(json.dumps(build_meta), "utf-8")

    parse_report = {
        "source_vrt": str(input_path),
        "documents": stats.documents,
        "tokens": stats.tokens,
        "tag_lines": stats.tag_lines,
        "token_lines": stats.token_lines,
        "skipped_short_docs": stats.skipped_short_docs,
        "skipped_outside_docs": stats.skipped_outside_docs,
        "inconsistent_column_lines": stats.inconsistent_column_lines,
        "inferred_columns": stats.inferred_columns,
        "annotation_mode": "adopt",
        "annotation_source": "gold_vrt",
        "tagset": "raw",
        "whitespace": "pretokenized",
        "whitespace_note": (
            "The VRT file holds tokens without their original spacing. "
            "Concordance lines and texts show the tokens separated by spaces."
        ),
        "index_annotations": (
            "VRT-Gold-Spalten (lemma/pos, optional morph) wurden roh in die "
            "Index-Token-Spalten uebernommen; leere Gold-Werte ('' oder '_') "
            "bleiben leer, ohne spaCy-Backfill. Kein Mapping auf das UD-Inventar."
        ),
        "adopt": {
            "adopted_columns": sorted(adopt_stats["adopted_columns"]),
            "empty_gold_values": dict(adopt_stats["empty_gold_values"]),
            "skipped_empty_surface_tokens": int(adopt_stats["skipped_empty_surface_tokens"]),
            "skipped_empty_docs": int(adopt_stats["skipped_empty_docs"]),
            "duplicate_docs_collapsed": int(adopt_stats["duplicate_docs_collapsed"]),
            "index_documents": int(adopt_stats["index_documents"]),
            "index_tokens": int(adopt_stats["index_tokens"]),
        },
        "warnings": stats.warnings,
    }
    verworfen = stats.dropped_attrs(cfg)
    parse_report["attrs"] = {
        "seen": dict(sorted(stats.seen_attrs.items())),
        "carried": sorted(stats.kept_attrs),
        "dropped": verworfen,
    }
    (output_path / "vrt_import_report.json").write_text(
        json.dumps(parse_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _melde_verworfene_attribute(
        verworfen, strict=bool(getattr(args, "strict_attrs", False))
    )

    print(
        f"OK: {input_path.name} -> {output_path} "
        f"(records={adopt_stats['index_documents']}, tokens={adopt_stats['index_tokens']}, "
        "annotation_mode=adopt, annotation_source=gold_vrt"
        + (f", dropped_attributes={len(verworfen)}" if verworfen else "")
        + ")"
    )
    return 0


SHA256_MUSTER = re.compile(r"^[0-9a-f]{64}$")


def _archiv_sha256(args: argparse.Namespace) -> str:
    """Return the SHA-256 provenance value for the source archive.

Use an explicitly supplied hash or calculate it from the source archive.
Reject malformed values rather than recording invalid provenance."""
    direkt = str(getattr(args, "source_archive_sha256", "") or "").strip()
    direkt = direkt.removeprefix("sha256:").lower()
    if direkt:
        if not SHA256_MUSTER.match(direkt):
            raise SystemExit(
                "--source-archive-sha256 is not a lowercase "
                f"SHA-256 digest: {direkt!r}"
            )
        return direkt
    datei = str(getattr(args, "source_archive", "") or "").strip()
    if not datei:
        return ""
    pfad = Path(datei)
    if not pfad.is_file():
        raise SystemExit(f"--source-archive not found: {pfad}")
    import hashlib

    digest = hashlib.sha256()
    with pfad.open("rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _melde_verworfene_attribute(
    verworfen: dict[str, int], *, strict: bool
) -> None:
    """Name dropped structural attributes loudly.

    An import that loses information must say so. Example: a parliamentary
    corpus in VRT format contains ``speaker_party``, ``party_status``,
    ``speaker_gender``, ``speaker_role`` and ``term``. Without this report
    the index can contain none of them while neither log nor report says so,
    and the loss only shows when an analysis compares government and
    opposition.
    """
    if not verworfen:
        return
    zeilen = ", ".join(
        f"{name} ({anzahl} documents)" for name, anzahl in verworfen.items()
    )
    text = (
        f"{len(verworfen)} structural attribute(s) were in the VRT but are "
        f"NOT in the index: {zeilen}. Carry them over with --carry-attrs "
        "(comma-separated list or '*'), otherwise they are lost for every "
        "analysis."
    )
    if strict:
        raise SystemExit("Stopped (--strict-attrs): " + text)
    logger.warning(text)


def _builder_env() -> dict[str, str]:
    """Environment for the builder subprocess: ``candyconc`` stays importable."""
    import candyconc

    package_root = str(Path(candyconc.__file__).resolve().parents[1])
    env = dict(os.environ)
    current = env.get("PYTHONPATH", "")
    if package_root not in current.split(os.pathsep):
        env["PYTHONPATH"] = os.pathsep.join(p for p in (package_root, current) if p)
    return env


def _run_builder(input_path: Path, output_path: Path, args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        _FAST_INDEX_BUILDER_MODULE,
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--spacy-model",
        args.spacy_model,
        "--max-doc-chars",
        str(args.max_doc_chars),
        # The manifest names the VRT source, not the intermediate Parquet file.
        "--import-mode",
        "vrt",
    ]
    if args.batch_size:
        cmd.extend(["--batch-size", str(args.batch_size)])
    if args.n_process:
        cmd.extend(["--n-process", str(args.n_process)])
    if args.include_prompts:
        cmd.append("--include-prompts")
    if args.enable_ner:
        cmd.append("--enable-ner")
    if args.enable_deps:
        cmd.append("--enable-deps")
    if args.allow_missing_input_text:
        cmd.append("--allow-missing-input-text")
    if args.meta_index_fields:
        cmd.extend(["--meta-index-fields", args.meta_index_fields])
    if args.split_long_texts is False:
        cmd.append("--no-split-long-texts")
    if not getattr(args, "capture_whitespace", True):
        cmd.append("--no-capture-whitespace")
    return subprocess.run(cmd, check=False, env=_builder_env()).returncode


def _resolve_builder() -> Path:
    if not FAST_INDEX_BUILDER.exists():
        raise SystemExit("build_fast_index_from_parquet.py was not found.")
    return FAST_INDEX_BUILDER


def _build_config(args: argparse.Namespace, input_path: Path) -> VrtParseConfig:
    columns = [part.strip() for part in args.token_columns.split(",") if part.strip()]
    return VrtParseConfig(
        segment_tag=args.segment_tag.lower(),
        text_tag=args.text_tag.lower(),
        sentence_tag=args.sentence_tag.lower(),
        token_columns=columns,
        token_separator=args.token_separator,
        word_column=args.word_column,
        source_default=args.source or input_path.stem,
        register_default=args.register,
        min_text_chars=args.min_text_chars,
        variant=args.variant,
        model=args.model,
        id_attrs=_split_csv(args.id_attrs, DEFAULT_ID_ATTRS),
        source_attrs=_split_csv(args.source_attrs, DEFAULT_SOURCE_ATTRS),
        register_attrs=_split_csv(args.register_attrs, DEFAULT_REGISTER_ATTRS),
        date_attrs=_split_csv(args.date_attrs, DEFAULT_DATE_ATTRS),
        genre_attrs=_split_csv(args.genre_attrs, DEFAULT_GENRE_ATTRS),
        strict_columns=args.strict_columns,
        join_mode=args.join_mode,
        carry_attrs=tuple(
            part.strip().lower()
            for part in str(args.carry_attrs or "").split(",")
            if part.strip()
        ),
    )


def _inspect(path: Path, cfg: VrtParseConfig, limit: int) -> int:
    stats = VrtParseStats()
    examples = []
    for doc in iter_vrt_documents(path, cfg, stats):
        if doc.row and len(examples) < limit:
            examples.append(
                {
                    "doc_id": doc.row["doc_id"],
                    "source": doc.row.get("source", ""),
                    "register": doc.row.get("register", ""),
                    "text_preview": doc.row["target_text"][:240],
                    "token_count": len(doc.annotations),
                    "start_line": doc.start_line,
                    "end_line": doc.end_line,
                    "sample_token": doc.annotations[0] if doc.annotations else {},
                }
            )
    payload = {
        "documents": stats.documents,
        "tokens": stats.tokens,
        "tag_lines": stats.tag_lines,
        "token_lines": stats.token_lines,
        "skipped_short_docs": stats.skipped_short_docs,
        "skipped_outside_docs": stats.skipped_outside_docs,
        "inconsistent_column_lines": stats.inconsistent_column_lines,
        "inferred_columns": stats.inferred_columns,
        "warnings": stats.warnings,
        "examples": examples,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build fast index from line-oriented VRT / XML-ish input.")
    parser.add_argument("--input", required=True, type=Path, help="VRT / XML-ish file")
    parser.add_argument("--output", required=True, type=Path, help="Output index directory")
    parser.add_argument("--spacy-model", default="de_core_news_md")
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--n-process", type=int, default=0)
    parser.add_argument("--include-prompts", action="store_true", default=False)
    parser.add_argument("--enable-ner", action="store_true", default=False)
    parser.add_argument("--enable-deps", action="store_true", default=False)
    parser.add_argument("--no-split-long-texts", dest="split_long_texts", action="store_false")
    parser.add_argument("--allow-missing-input-text", action="store_true", default=False)
    parser.add_argument("--max-doc-chars", type=int, default=1_000_000)
    parser.add_argument("--meta-index-fields", default="")
    parser.add_argument(
        "--source-archive",
        default="",
        help=(
            "Source archive this VRT comes from. Its SHA-256 is "
            "computed and written into the index as source_archive_sha256 "
            "(provenance chain archive -> index)."
        ),
    )
    parser.add_argument(
        "--source-archive-sha256",
        default="",
        help=(
            "Give the SHA-256 of the source archive directly instead of "
            "computing it from --source-archive."
        ),
    )
    parser.add_argument(
        "--strict-attrs",
        action="store_true",
        default=False,
        help=(
            "Stop when the VRT contains structural attributes that are neither "
            "mapped nor carried over with --carry-attrs. Recommended for "
            "replication runs: otherwise a silent loss of information only "
            "shows up during the analysis."
        ),
    )
    parser.add_argument(
        "--carry-attrs",
        default="",
        help=(
            "Comma-separated list of structural attributes of the segment or text "
            "tag that are carried over unchanged as document metadata "
            "(for example speaker_party,party_status,speaker_gender). '*' takes "
            "all. Empty = only the mapped roles id/source/register/date/"
            "genre, as before. Reserved field names are never overwritten."
        ),
    )
    parser.add_argument("--segment-tag", default="text", help="VRT tag emitted as one document")
    parser.add_argument("--text-tag", default="text", help="Parent tag used for text-level metadata")
    parser.add_argument("--sentence-tag", default="s", help="Sentence tag name, kept for VRT inspection metadata")
    parser.add_argument("--source", default="", help="Fallback source field")
    parser.add_argument("--register", default="", help="Fallback register field")
    parser.add_argument("--min-text-chars", type=int, default=1)
    # Unpaired documents carry the placeholders of a CSV or JSON Lines import.
    parser.add_argument("--variant", default="document")
    parser.add_argument("--model", default="none")
    parser.add_argument("--token-columns", "--columns", default="", help="Comma-separated VRT token columns, e.g. word,lemma,pos,morph")
    parser.add_argument("--token-separator", choices=("auto", "tab", "whitespace"), default="auto")
    parser.add_argument("--word-column", default="word", help="Column name or index used as surface token")
    parser.add_argument("--strict-columns", action="store_true", default=False)
    parser.add_argument("--join-mode", choices=("smart", "space"), default="smart")
    parser.add_argument(
        "--capture-whitespace",
        dest="capture_whitespace",
        action="store_true",
        default=True,
        help=(
            "none/sidecar: write whitespace_after.bin with the spacing of the text rebuilt "
            "from the VRT tokens (--join-mode). adopt keeps the VRT tokenization and has "
            "no spacing to record (default: on)"
        ),
    )
    parser.add_argument(
        "--no-capture-whitespace",
        dest="capture_whitespace",
        action="store_false",
        help="do not write whitespace_after.bin",
    )
    parser.add_argument("--id-attrs", default=",".join(DEFAULT_ID_ATTRS))
    parser.add_argument("--source-attrs", default=",".join(DEFAULT_SOURCE_ATTRS))
    parser.add_argument("--register-attrs", default=",".join(DEFAULT_REGISTER_ATTRS))
    parser.add_argument("--date-attrs", default=",".join(DEFAULT_DATE_ATTRS))
    parser.add_argument("--genre-attrs", default=",".join(DEFAULT_GENRE_ATTRS))
    parser.add_argument(
        "--annotation-mode",
        choices=("none", "sidecar", "adopt"),
        default="sidecar",
        help=(
            "none/sidecar: index columns come from spaCy, VRT annotations are "
            "discarded (none) or kept as a sidecar file (sidecar). adopt: supplied lemma/pos/"
            "morph columns are adopted unchanged as searchable index columns "
            "(no spaCy tagging, no UD mapping)."
        ),
    )
    parser.add_argument("--inspect", action="store_true", default=False, help="Parse and print VRT diagnostics without building an index")
    parser.add_argument("--inspect-docs", type=int, default=3)
    args = parser.parse_args(argv)

    input_path = args.input.expanduser()
    if not input_path.is_file():
        raise SystemExit(f"missing input: {input_path}")

    cfg = _build_config(args, input_path)
    if args.inspect:
        return _inspect(input_path, cfg, args.inspect_docs)
    if args.annotation_mode == "adopt":
        if args.enable_ner or args.enable_deps:
            raise SystemExit(
                "annotation_mode=adopt copies the VRT gold columns without spaCy. "
                "--enable-ner and --enable-deps are not available in this mode."
            )
        return _run_adopt_build(input_path, args.output.expanduser(), cfg, args)
    _resolve_builder()

    with tempfile.TemporaryDirectory(prefix="candyconc_vrt_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        parquet_path = tmp_root / f"{input_path.stem}.parquet"
        sidecar_tmp = tmp_root / "vrt_token_annotations.jsonl" if args.annotation_mode == "sidecar" else None
        stats = VrtParseStats()
        docs = iter_vrt_documents(input_path, cfg, stats)
        count = _write_parquet_and_sidecar(docs, parquet_path, sidecar_tmp)
        if count == 0:
            raise SystemExit(f"no records parsed from {input_path}")

        output_path = args.output.expanduser()
        builder_code = _run_builder(parquet_path, output_path, args)
        if builder_code != 0:
            raise SystemExit(builder_code)
        if sidecar_tmp is not None and sidecar_tmp.exists():
            output_path.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sidecar_tmp, output_path / "vrt_token_annotations.jsonl")
        parse_report = {
            "source_vrt": str(input_path),
            "documents": stats.documents,
            "tokens": stats.tokens,
            "tag_lines": stats.tag_lines,
            "token_lines": stats.token_lines,
            "skipped_short_docs": stats.skipped_short_docs,
            "skipped_outside_docs": stats.skipped_outside_docs,
            "inconsistent_column_lines": stats.inconsistent_column_lines,
            "inferred_columns": stats.inferred_columns,
            "annotation_mode": args.annotation_mode,
            "index_annotations": "spaCy-generated; VRT token annotations are preserved only in sidecar/source metadata",
            "whitespace": "vrt_join" if getattr(args, "capture_whitespace", True) else "disabled",
            "join_mode": args.join_mode,
            "warnings": stats.warnings,
        }
        (output_path / "vrt_import_report.json").write_text(
            json.dumps(parse_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"OK: {input_path.name} -> {output_path} (records={count}, tokens={stats.tokens})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
