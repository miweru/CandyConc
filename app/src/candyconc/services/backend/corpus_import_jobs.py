from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import csv
import importlib.util
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from candyconc.core.index_format import MANIFEST_FILENAME, normalize_manifest_payload
from candyconc.i18n import LocalizedText, exception_text, join_texts, lt
from candyconc.paths import corpora_dir
from candyconc.utils.import_builders import (
    find_builder_script,
    import_builder_spec,
    normalize_import_method,
    supported_import_methods as _builder_supported_import_methods,
)
from candyconc.services.backend.corpus_import_outcome import (
    IMPORT_OUTCOME_FILENAME,
    write_import_outcome,
)


ImportJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

_DEFAULT_JOB_LIMIT = 128
_DEFAULT_TAIL_MAX_BYTES = 64 * 1024
_DEFAULT_REPORT_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_PREFLIGHT_TEXT_BYTES = 128 * 1024
_DEFAULT_PREFLIGHT_JSONL_BYTES = 128 * 1024
_DEFAULT_PREFLIGHT_JSONL_ROWS = 100
_DEFAULT_PREFLIGHT_PAIR_ROWS = 200
IMPORT_REPORTS_SCHEMA_VERSION = "corpus-import-reports-v1"
_TERMINAL_STATUSES: set[str] = {"succeeded", "failed", "cancelled"}
_REPORT_NAMES: tuple[str, ...] = (
    "build_report.json",
    "build-report.json",
    "build_report.md",
    "build-report.md",
    "index_manifest.json",
    "index_build_meta.json",
    "vrt_import_report.json",
    "vrt-import-report.json",
    "import_report.json",
    "import-report.json",
    IMPORT_OUTCOME_FILENAME,
    "reject_report.json",
    "reject-report.json",
    "report.json",
    "summary.json",
)
_PROGRESS_RE = re.compile(r"(?:progress\s*[:=]\s*)?(100|[1-9]?\d)\s*%", re.IGNORECASE)
# Single source of truth for the import spaCy model: the preflight advertises and
# validates this default, and ``iter_method_options`` emits it on the build argv
# when the payload does not override it. Builders carry their own argparse default
# (the prealigned ingest path even defaults to de_core_news_sm), so passing this
# explicitly is what keeps "green preflight" == "the model the build runs".
_DEFAULT_SPACY_MODEL = "de_core_news_md"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _now() -> float:
    return time.time()


@dataclass
class BoundedTextTail:
    max_bytes: int = _DEFAULT_TAIL_MAX_BYTES
    _buffer: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: str | bytes | bytearray | None) -> None:
        if not chunk or self.max_bytes == 0:
            return
        data = (
            bytes(chunk)
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk).encode("utf-8", "replace")
        )
        if self.max_bytes < 0:
            self._buffer.extend(data)
            return
        if len(data) >= self.max_bytes:
            self._buffer[:] = data[-self.max_bytes :]
            self.truncated = True
            return
        self._buffer.extend(data)
        overflow = len(self._buffer) - self.max_bytes
        if overflow > 0:
            del self._buffer[:overflow]
            self.truncated = True

    def text(self) -> str:
        return bytes(self._buffer).decode("utf-8", "replace")


@dataclass
class ImportJob:
    job_id: str
    method: str
    input: str
    target: str
    staging: str | None = None
    activate: bool = False
    status: ImportJobStatus = "queued"
    progress: int = 0
    stage: str = "queued"
    message: str = "queued"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    started_at: float | None = None
    finished_at: float | None = None
    command: list[str] | None = None
    returncode: int | None = None
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    stdout: BoundedTextTail = field(default_factory=BoundedTextTail)
    stderr: BoundedTextTail = field(default_factory=BoundedTextTail)
    process: subprocess.Popen[Any] | None = field(default=None, repr=False, compare=False)
    worker: threading.Thread | None = field(default=None, repr=False, compare=False)
    cancel_requested: bool = False
    # Cancellation is meaningful only until the completed staging directory is
    # committed.  Once finalisation begins, reporting "cancelled" would leave a
    # visible corpus behind while telling the researcher the opposite.
    finalization_started: bool = False
    partial_input: bool = False
    rejected_rows: int = 0
    import_warnings: list[str] = field(default_factory=list)
    activation_skipped_reason: str | None = None

    @property
    def output_dir(self) -> str:
        return self.staging or self.target


def _path_value(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _default_target(input_path: Path) -> Path:
    return corpora_dir() / input_path.stem


def _safe_target_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError(lt("target_name fehlt", "target_name is missing"))
    path = Path(name)
    if path.is_absolute() or path.name != name or name in {".", ".."}:
        raise ValueError(lt("target_name ist kein sicherer Korpusname: {name!r}", "target_name is not a safe corpus name: {name!r}").format(name=name))
    if "/" in name or "\\" in name or any(part == ".." for part in path.parts):
        raise ValueError(lt("target_name ist kein sicherer Korpusname: {name!r}", "target_name is not a safe corpus name: {name!r}").format(name=name))
    # POSIX NAME_MAX: a component over 255 bytes makes the kernel raise
    # OSError(ENAMETOOLONG) from the later ``target_path.exists()`` probe in
    # preflight; reject it here so the route returns 400 (CORPUS-LIFECYCLE-01).
    if len(name.encode("utf-8", "surrogatepass")) > 255:
        raise ValueError(lt("target_name ist kein sicherer Korpusname: {name!r}", "target_name is not a safe corpus name: {name!r}").format(name=name))
    return name


def _coerce_job_fields(
    method: str,
    payload: Mapping[str, Any] | None,
    *,
    target: str | os.PathLike[str] | None = None,
    staging: str | os.PathLike[str] | None = None,
    activate: bool | None = None,
) -> dict[str, Any]:
    raw_payload = dict(payload or {})
    method_key = normalize_import_method(method)
    input_text = _path_value(raw_payload.get("input") or raw_payload.get("path"))
    if input_text is None:
        raise ValueError(lt("input fehlt", "input is missing"))
    if method_key == "hf":
        # HF: der Input ist eine Dataset-ID, kein Pfad — niemals auflösen,
        # sonst wird z. B. "org/dataset" zu einem absoluten Serverpfad.
        input_path = Path(input_text)
        input_value = input_text
    else:
        input_path = Path(input_text).expanduser().resolve(strict=False)
        input_value = str(input_path)
    target_text = _path_value(
        target
        or raw_payload.get("target")
        or raw_payload.get("output")
        or raw_payload.get("output_dir")
    )
    target_path = (
        Path(target_text).expanduser().resolve(strict=False)
        if target_text is not None
        else _default_target(input_path).resolve(strict=False)
    )
    staging_text = _path_value(
        staging
        or raw_payload.get("staging")
        or raw_payload.get("staging_dir")
        or raw_payload.get("staging-dir")
    )
    staging_path = (
        Path(staging_text).expanduser().resolve(strict=False)
        if staging_text is not None
        else None
    )
    return {
        "method": method_key,
        "input": input_value,
        "target": str(target_path),
        "staging": str(staging_path) if staging_path is not None else None,
        "activate": bool(raw_payload.get("activate") if activate is None else activate),
        "payload": raw_payload,
    }


def _add_option(
    options: list[list[str]],
    flag: str,
    value: object | None,
    *,
    bool_flag: bool = False,
) -> None:
    if bool_flag:
        if value:
            options.append([flag])
        return
    if value is None:
        return
    if isinstance(value, str) and not value:
        return
    if isinstance(value, bool):
        if value:
            options.append([flag])
        return
    options.append([flag, str(value)])


def _csv_option_value(value: object | None) -> object | None:
    if isinstance(value, (list, tuple)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return value


def _list_option_values(value: object | None) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _import_pipeline(payload: Mapping[str, Any]) -> str:
    """Pipeline of the import: ``spacy_model``, else the one of ``language``.

    Same rule as ``candy import``. A contradiction raises ``ValueError``,
    which the preflight reports before any job starts.
    """
    from candyconc.ingest.pipelines import resolve_import_pipeline

    model = str(payload.get("spacy_model") or payload.get("spacy-model") or "").strip()
    language = str(payload.get("language") or "").strip()
    if not model and not language:
        return _DEFAULT_SPACY_MODEL
    return resolve_import_pipeline(language or None, model or None)


def _deps_enabled(method: str, payload: Mapping[str, Any]) -> bool:
    """Dependency parsing: as requested, without a request when the pipeline has a parser.

    VRT adoption keeps its supplied annotations, as in ``candy import``.
    """
    value = payload.get("enable_deps")
    if value is None:
        if method == "vrt" and (payload.get("annotation_mode") or payload.get("annotation-mode")) == "adopt":
            return False
        from candyconc.ingest.pipelines import pipeline_has_parser

        try:
            return pipeline_has_parser(_import_pipeline(payload))
        except ValueError:
            return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _language_choices() -> tuple[dict[str, Any], ...]:
    from candyconc.ingest.pipelines import DEFAULT_PIPELINES

    return (
        {"value": "", "label": ""},
        *({"value": code, "label": code, "pipeline": pipeline} for code, pipeline in DEFAULT_PIPELINES.items()),
    )


def iter_method_options(method: str, payload: Mapping[str, Any] | None) -> list[list[str]]:
    """Return builder CLI options derived from UI/API payload keys."""
    raw = dict(payload or {})
    method_key = normalize_import_method(method)
    options: list[list[str]] = []

    _add_option(options, "--spacy-model", _import_pipeline(raw))
    _add_option(options, "--batch-size", raw.get("batch_size") or raw.get("batch-size"))
    _add_option(options, "--n-process", raw.get("n_process") or raw.get("n-process"))
    _add_option(
        options,
        "--max-doc-chars",
        raw.get("max_doc_chars") or raw.get("max-doc-chars"),
    )
    _add_option(
        options,
        "--meta-index-fields",
        _csv_option_value(raw.get("meta_index_fields") or raw.get("meta-index-fields")),
    )
    _add_option(options, "--enable-ner", raw.get("enable_ner"), bool_flag=True)
    _add_option(options, "--enable-deps", _deps_enabled(method_key, raw), bool_flag=True)
    if method_key == "parquet":
        options.append(["--generic"])
        _add_option(options, "--text-column", raw.get("text_column") or raw.get("text-column") or "input_text")
        _add_option(options, "--id-column", raw.get("id_column") or raw.get("id-column") or "id")
        meta_columns = _list_option_values(raw.get("meta_columns") or raw.get("meta-columns"))
        if meta_columns:
            options.append(["--meta-columns", *meta_columns])
        _add_option(options, "--source", raw.get("source") or "parquet-import")
    elif method_key == "vrt":
        _add_option(options, "--include-prompts", raw.get("include_prompts"), bool_flag=True)
        _add_option(
            options,
            "--allow-missing-input-text",
            raw.get("allow_missing_input_text"),
            bool_flag=True,
        )

    if method_key == "vrt":
        _add_option(options, "--segment-tag", raw.get("segment_tag") or raw.get("segment-tag", "text"))
        _add_option(options, "--text-tag", raw.get("text_tag") or raw.get("text-tag", "text"))
        _add_option(
            options,
            "--sentence-tag",
            raw.get("sentence_tag") or raw.get("sentence-tag", "s"),
        )
        _add_option(options, "--source", raw.get("source", ""))
        _add_option(options, "--register", raw.get("register", ""))
        _add_option(
            options,
            "--min-text-chars",
            raw.get("min_text_chars") or raw.get("min-text-chars", 1),
        )
        _add_option(options, "--variant", raw.get("variant", "document"))
        _add_option(options, "--model", raw.get("model", "none"))
        _add_option(options, "--token-columns", _csv_option_value(raw.get("token_columns") or raw.get("token-columns")))
        _add_option(
            options,
            "--token-separator",
            raw.get("token_separator") or raw.get("token-separator", "auto"),
        )
        _add_option(options, "--word-column", raw.get("word_column") or raw.get("word-column", "word"))
        _add_option(options, "--join-mode", raw.get("join_mode") or raw.get("join-mode", "smart"))
        _add_option(
            options,
            "--annotation-mode",
            raw.get("annotation_mode") or raw.get("annotation-mode", "sidecar"),
        )
        _add_option(options, "--id-attrs", _csv_option_value(raw.get("id_attrs") or raw.get("id-attrs")))
        _add_option(options, "--source-attrs", _csv_option_value(raw.get("source_attrs") or raw.get("source-attrs")))
        _add_option(options, "--register-attrs", _csv_option_value(raw.get("register_attrs") or raw.get("register-attrs")))
        _add_option(options, "--date-attrs", _csv_option_value(raw.get("date_attrs") or raw.get("date-attrs")))
        _add_option(options, "--genre-attrs", _csv_option_value(raw.get("genre_attrs") or raw.get("genre-attrs")))
        _add_option(
            options,
            "--strict-columns",
            raw.get("strict_columns") or raw.get("strict-columns"),
            bool_flag=True,
        )
        if _bool_option(raw.get("inspect") or raw.get("inspect-only")):
            options.append(["--inspect"])
            _add_option(options, "--inspect-docs", raw.get("inspect_docs") or raw.get("inspect-docs"))
    elif method_key in {"prealigned_parquet", "prealigned_csv", "prealigned_jsonl"}:
        _add_option(options, "--text-column", raw.get("text_column") or raw.get("text-column"))
        _add_option(options, "--id-column", raw.get("id_column") or raw.get("id-column"))
        _add_option(options, "--pair-key-column", raw.get("pair_key_column") or raw.get("pair-key-column"))
        _add_option(
            options,
            "--pair-role-column",
            raw.get("pair_role_column") or raw.get("pair-role-column"),
        )
        _add_option(options, "--anchor-role", raw.get("anchor_role") or raw.get("anchor-role"))
        _add_option(options, "--pair-axis", raw.get("pair_axis") or raw.get("pair-axis"))
        _add_option(options, "--pair-order", raw.get("pair_order") or raw.get("pair-order"))
        meta_columns = _list_option_values(raw.get("meta_columns") or raw.get("meta-columns"))
        if meta_columns:
            options.append(["--meta-columns", *meta_columns])
        _add_option(options, "--source", raw.get("source"))
        _add_option(options, "--variant-column", raw.get("variant_column") or raw.get("variant-column"))
        _add_option(options, "--model-column", raw.get("model_column") or raw.get("model-column"))
        _add_option(options, "--reject-policy", raw.get("reject_policy") or raw.get("reject-policy"))
        _add_option(options, "--reject-report", raw.get("reject_report") or raw.get("reject-report"))
        if method_key == "prealigned_csv":
            _add_option(options, "--delimiter", raw.get("delimiter"))
    elif method_key in {"csv", "jsonl", "hf"}:
        _add_option(options, "--text-column", raw.get("text_column") or raw.get("text-column") or "text")
        _add_option(options, "--id-column", raw.get("id_column") or raw.get("id-column"))
        meta_columns = _list_option_values(raw.get("meta_columns") or raw.get("meta-columns"))
        if meta_columns:
            options.append(["--meta-columns", *meta_columns])
        _add_option(options, "--source", raw.get("source"))
        _add_option(options, "--reject-policy", raw.get("reject_policy") or raw.get("reject-policy"))
        _add_option(options, "--reject-report", raw.get("reject_report") or raw.get("reject-report"))
        if method_key == "csv":
            _add_option(options, "--delimiter", raw.get("delimiter"))
        elif method_key == "hf":
            _add_option(options, "--config", raw.get("config") or raw.get("hf_config"))
            _add_option(options, "--split", raw.get("split") or raw.get("hf_split") or "train")
            limit_raw = raw.get("limit") or raw.get("hf_limit")
            try:
                limit_value = int(str(limit_raw)) if limit_raw not in (None, "", 0, False) else 0
            except (TypeError, ValueError):
                limit_value = 0
            if limit_value > 0:
                options.append(["--limit", str(limit_value)])
            # Sicherheitsgrenze: --trust-remote-code wird hier NIE emittiert.
    elif method_key == "plaintext":
        _add_option(options, "--pattern", raw.get("pattern") or "*.txt")
        _add_option(
            options,
            "--split-paragraphs",
            raw.get("split_paragraphs") or raw.get("split-paragraphs"),
            bool_flag=True,
        )
        _add_option(options, "--source", raw.get("source"))
        _add_option(options, "--reject-policy", raw.get("reject_policy") or raw.get("reject-policy"))
        _add_option(options, "--reject-report", raw.get("reject_report") or raw.get("reject-report"))

    if raw.get("split_long_texts") is False:
        options.append(["--no-split-long-texts"])
    capture = raw.get("capture_whitespace", raw.get("capture-whitespace"))
    if capture is not None and not _bool_option(capture):
        options.append(["--no-capture-whitespace"])
    return options


_MISSING = object()
_IMPORT_METHOD_SCHEMA_VERSION = "corpus-import-method-v1"


def _choice(value: str, label: str | None = None, description: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"value": value, "label": label or value}
    if description:
        item["description"] = description
    return item


def _option_spec(
    key: str,
    label: str,
    option_type: str = "string",
    *,
    description: str = "",
    required: bool = False,
    default: Any = _MISSING,
    choices: Iterable[dict[str, Any] | str] = (),
    aliases: Iterable[str] = (),
    placeholder: str = "",
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": option_type,
        "required": bool(required),
        "description": description,
        "aliases": list(aliases),
    }
    if default is not _MISSING:
        spec["default"] = default
    choice_list = list(choices)
    if choice_list:
        spec["choices"] = choice_list
    if placeholder:
        spec["placeholder"] = placeholder
    return spec


def _column_spec(
    key: str,
    label: str,
    *,
    required: bool,
    description: str,
    default_option: str | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "key": key,
        "label": label,
        "required": bool(required),
        "description": description,
    }
    if default_option:
        spec["configured_by"] = default_option
    return spec


_COMMON_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "spacy_model",
        lt("spaCy-Modell", "Annotation pipeline (spaCy)"),
        default=_DEFAULT_SPACY_MODEL,
        description=lt("Pipeline für Tokenisierung und optionale linguistische Annotationen.", "Pipeline for tokenization and optional linguistic annotation."),
    ),
    _option_spec(
        "language",
        lt("Korpussprache", "Corpus language"),
        "choice",
        default="",
        choices=_language_choices(),
        description=lt(
            "ISO-639-Code der Korpussprache. Ohne spacy_model wählt er die "
            "Standard-Pipeline der Sprache (Feld pipeline der Auswahl).",
            "ISO 639 code of the corpus language. Without spacy_model it selects "
            "the default pipeline of the language (field pipeline of the choice).",
        ),
    ),
    _option_spec(
        "batch_size",
        lt("Batchgröße", "Batch size"),
        "integer",
        default=0,
        description=lt("0 nutzt die automatische Backend-Heuristik.", "0 uses the automatic server heuristic."),
    ),
    _option_spec(
        "n_process",
        lt("Prozesse", "Processes"),
        "integer",
        default=0,
        description=lt("0 nutzt die automatische Backend-Heuristik.", "0 uses the automatic server heuristic."),
    ),
    _option_spec(
        "max_doc_chars",
        lt("Maximale Dokumentlänge", "Maximum document length"),
        "integer",
        default=1_000_000,
        description=lt("Lange Dokumente werden je nach split_long_texts sicher segmentiert.", "Long documents are segmented safely, depending on split_long_texts."),
    ),
    _option_spec(
        "meta_index_fields",
        lt("Metadatenindex-Felder", "Metadata index fields"),
        "string_list",
        default=[],
        description=lt("Felder, die zusätzlich als Metadatenindex verfügbar sein sollen.", "Fields that should also be available as a metadata index."),
        placeholder="date, genre, source",
    ),
    _option_spec(
        "enable_ner",
        lt("Named Entities erzeugen", "Generate named entities"),
        "boolean",
        default=False,
        description=lt("Erzeugt NER-Attribute, sofern die spaCy-Pipeline sie unterstützt.", "Generates NER attributes if the spaCy pipeline supports them."),
    ),
    _option_spec(
        "enable_deps",
        lt("Dependenzen erzeugen", "Generate dependency relations"),
        "boolean",
        default=True,
        description=lt("Erzeugt Head-/Relation-Attribute, sofern die Pipeline sie unterstützt.", "Generates head and relation attributes if the pipeline supports them."),
    ),
    _option_spec(
        "split_long_texts",
        lt("Lange Texte segmentieren", "Segment long texts"),
        "boolean",
        default=True,
        description=lt("Schützt den Import vor sehr langen Einzeltexten.", "Protects the import from very long single texts."),
    ),
    _option_spec(
        "capture_whitespace",
        lt("Originale Leerzeichen speichern", "Keep the original spacing"),
        "boolean",
        default=True,
        description=lt(
            "Speichert je Token, ob im Text ein Leerzeichen folgt (whitespace_after.bin, "
            "ein Byte je Token). Konkordanz, Dokumentkontext, Volltext und Exporte zeigen "
            "den Text dann wie geschrieben, etwa „soul. No“ statt „soul . No“. VRT mit "
            "annotation_mode=adopt enthält keine Leerzeichen und bleibt bei der tokenweisen "
            "Darstellung.",
            "Records for each token whether a space follows it in the text "
            "(whitespace_after.bin, one byte per token). Concordance lines, document "
            "context, full text and exports then show the text as written, for example "
            "\"soul. No\" instead of \"soul . No\". VRT with annotation_mode=adopt holds "
            "no spacing and keeps showing tokens separated by spaces.",
        ),
    ),
    _option_spec(
        "build_word_faiss",
        lt("Wort-Thesaurus (Word-FAISS) nach dem Import bauen", "Build the similar words index (word FAISS) after the import"),
        "boolean",
        default=False,
        description=lt(
            "Nachschritt nach erfolgreichem Publish: scannt das gesamte Wortlexikon, "
            "liest spaCy-Wortvektoren und schreibt faiss_word.index + word_ids.npy. "
            "Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur "
            "Vokabulargröße; benötigt ein spaCy-Modell mit Vektoren (z. B. "
            "de_core_news_md — blank:-Pipelines liefern keine Vektoren, der "
            "Nachschritt schlägt dann fehl und wird als Import-Warnung gemeldet). "
            "Erst nach erfolgreichem Nachschritt wird semantic.word_similarity "
            "(Wort-Thesaurus) für dieses Korpus wahr.",
            "Post-step after a successful publish: scans the whole word lexicon, "
            "reads spaCy word vectors and writes faiss_word.index + word_ids.npy. "
            "Cost: additional run time and memory proportional to the vocabulary "
            "size. Needs a spaCy pipeline with vectors (for example "
            "de_core_news_md). blank: pipelines have no vectors, so the post-step "
            "then fails and is reported as an import warning. Only after a "
            "successful post-step does semantic.word_similarity (similar words) "
            "become true for this corpus.",
        ),
    ),
)

_PARQUET_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "text_column",
        lt("Textspalte", "Text column"),
        default="input_text",
        required=True,
        description=lt("Spalte, die als Dokumenttext indexiert wird.", "Column indexed as the document text."),
    ),
    _option_spec(
        "id_column",
        lt("ID-Spalte", "ID column"),
        default="id",
        description=lt("Optionale Dokument-ID; fehlt die Spalte, erzeugt der Import stabile IDs.", "Optional document ID. If the column is missing, the import generates stable IDs."),
    ),
    _option_spec(
        "meta_columns",
        lt("Metadatenspalten", "Metadata columns"),
        "string_list",
        default=[],
        description=lt("Zusätzliche Spalten, die als Dokumentmetadaten übernommen werden.", "Additional columns imported as document metadata."),
    ),
    _option_spec("source", lt("Quellenlabel", "Source label"), default="parquet-import", description=lt("Freies Quellenlabel für den Import.", "Free-form source label for the import.")),
)

_VRT_LEGACY_TEXT_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "include_prompts",
        lt("Prompttexte übernehmen", "Import prompt texts"),
        "boolean",
        default=False,
        description=lt("Übernimmt vorhandene Promptspalten als Dokumentmetadaten.", "Imports existing prompt columns as document metadata."),
    ),
    _option_spec(
        "allow_missing_input_text",
        lt("Fehlenden input_text erlauben", "Allow missing input_text"),
        "boolean",
        default=False,
        description=lt(
            "Erlaubt Fallback-Textspalten, wenn input_text fehlt. Die tatsächlich "
            "verwendete Spalte steht im Build-Report.",
            "Allows fallback text columns when input_text is missing. The column "
            "actually used is listed in the build report.",
        ),
    ),
)

_VRT_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    *_VRT_LEGACY_TEXT_OPTION_SPECS,
    _option_spec("segment_tag", lt("Dokument-/Segment-Tag", "Document or segment tag"), default="text", description=lt("Tag, der ein Dokumentsegment bildet.", "Tag that forms a document segment.")),
    _option_spec("text_tag", lt("Text-Metadaten-Tag", "Text metadata tag"), default="text", description=lt("Elterntag für textbezogene Metadaten.", "Parent tag for text-level metadata.")),
    _option_spec("sentence_tag", lt("Satz-Tag", "Sentence tag"), default="s", description=lt("Satz-Tag für VRT-Diagnostik und Strukturhinweise.", "Sentence tag for VRT diagnostics and structure hints.")),
    _option_spec("source", lt("Fallback-Quelle", "Fallback source"), default="", description=lt("Quelle, falls sie nicht aus Attributen gelesen wird.", "Source, if it is not read from attributes.")),
    _option_spec("register", lt("Fallback-Register", "Fallback register"), default="", description=lt("Register, falls es nicht aus Attributen gelesen wird.", "Register, if it is not read from attributes.")),
    _option_spec("min_text_chars", lt("Minimale Textlänge", "Minimum text length"), "integer", default=1, description=lt("Kürzere Segmente werden verworfen.", "Shorter segments are discarded.")),
    _option_spec("variant", lt("Variante", "Variant"), default="document", description=lt("Metadatenwert für die importierte Textvariante.", "Metadata value for the imported text variant.")),
    _option_spec("model", lt("Modell/Importquelle", "Model or import source"), default="none", description=lt("Metadatenwert für die erzeugende Quelle.", "Metadata value for the generating source.")),
    _option_spec(
        "token_columns",
        lt("Token-Spalten", "Token columns"),
        "string_list",
        default=[],
        description=lt("Explizite VRT-Token-Spalten, z. B. Wort, Lemma, POS.", "Explicit VRT token columns, for example word, lemma, POS."),
        placeholder="word, lemma, pos",
    ),
    _option_spec(
        "token_separator",
        lt("Token-Trenner", "Token separator"),
        "choice",
        default="auto",
        choices=(_choice("auto"), _choice("tab"), _choice("whitespace")),
        description=lt("Wie Tokenzeilen in Spalten zerlegt werden.", "How token lines are split into columns."),
    ),
    _option_spec("word_column", lt("Wortspalte", "Word column"), default="word", description=lt("Spaltenname oder Index für die Wortform.", "Column name or index for the word form.")),
    _option_spec(
        "join_mode",
        lt("Token-Join-Modus", "Token join mode"),
        "choice",
        default="smart",
        choices=(_choice("smart"), _choice("space")),
        description=lt("Wie Token wieder zu Dokumenttext rekonstruiert werden.", "How tokens are joined back into document text."),
    ),
    _option_spec(
        "annotation_mode",
        lt("Annotationsmodus", "Annotation mode"),
        "choice",
        default="sidecar",
        choices=(
            _choice(
                "sidecar",
                "sidecar",
                lt("spaCy erzeugt die abfragbaren Indexspalten; mitgelieferte VRT-Annotationen bleiben als Sidecar (vrt_token_annotations.jsonl) erhalten, sind aber nicht abfragbar.", "spaCy generates the searchable index columns. Supplied VRT annotations are kept as a sidecar file (vrt_token_annotations.jsonl) but are not searchable."),
            ),
            _choice(
                "none",
                "none",
                lt("spaCy erzeugt die abfragbaren Indexspalten; mitgelieferte VRT-Annotationen werden verworfen.", "spaCy generates the searchable index columns. Supplied VRT annotations are discarded."),
            ),
            _choice(
                "adopt",
                "adopt",
                lt("Mitgelieferte lemma/pos/morph-Spalten werden roh als abfragbare Indexspalten übernommen: kein spaCy-Tagging, kein Mapping auf das UD-Tagset (Manifest: annotation_source=gold_vrt, tagset=raw). Leere Werte bleiben leer.", "Supplied lemma/pos/morph columns are adopted unchanged as searchable index columns: no spaCy tagging, no mapping to the UD tagset (manifest: annotation_source=gold_vrt, tagset=raw). Empty values stay empty."),
            ),
        ),
        description=lt(
            "Umgang mit mitgelieferten VRT-Token-Annotationen: sidecar/none erzeugen "
            "die Indexspalten per spaCy neu; adopt übernimmt die Gold-Spalten roh in den Index.",
            "Handling of supplied VRT token annotations: sidecar and none regenerate "
            "the index columns with spaCy. adopt copies the gold columns unchanged into the index.",
        ),
    ),
    _option_spec(
        "id_attrs",
        lt("ID-Attribute", "ID attributes"),
        "string_list",
        default=["id", "xml:id", "num", "n", "sid", "sent_id", "segment_id", "chunk_id"],
        description=lt("Attributnamen, aus denen Dokument-/Segment-IDs gelesen werden.", "Attribute names from which document or segment IDs are read."),
    ),
    _option_spec(
        "source_attrs",
        lt("Quellattribute", "Source attributes"),
        "string_list",
        default=["source", "source_id", "corpus", "name"],
        description=lt("Attributnamen für Quellenmetadaten.", "Attribute names for source metadata."),
    ),
    _option_spec(
        "register_attrs",
        lt("Registerattribute", "Register attributes"),
        "string_list",
        default=["register", "textclass", "domain", "subtype"],
        description=lt("Attributnamen für Register-/Domänenmetadaten.", "Attribute names for register or domain metadata."),
    ),
    _option_spec(
        "date_attrs",
        lt("Datumsattribute", "Date attributes"),
        "string_list",
        default=["date", "timestamp", "time", "created", "published"],
        description=lt("Attributnamen für Datumsmetadaten.", "Attribute names for date metadata."),
    ),
    _option_spec(
        "genre_attrs",
        lt("Genre-Attribute", "Genre attributes"),
        "string_list",
        default=["genre", "register", "textclass", "domain", "subtype"],
        description=lt("Attributnamen für Genre-/Registermetadaten.", "Attribute names for genre or register metadata."),
    ),
    _option_spec(
        "strict_columns",
        lt("Strikte Spaltenprüfung", "Strict column check"),
        "boolean",
        default=False,
        description=lt("Bricht bei unerwarteter Token-Spaltenstruktur früher ab.", "Stops earlier on an unexpected token column structure."),
    ),
    _option_spec("inspect", lt("Nur inspizieren", "Inspect only"), "boolean", default=False, description=lt("Diagnostiklauf ohne Indexbau.", "Diagnostic run without an index build.")),
    _option_spec("inspect_docs", lt("Inspect-Dokumente", "Inspect documents"), "integer", default=3, description=lt("Anzahl der Diagnostikbeispiele.", "Number of diagnostic examples.")),
)

_PREALIGNED_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec("text_column", lt("Textspalte", "Text column"), default="text", required=True, description=lt("Spalte mit dem Dokumenttext.", "Column with the document text.")),
    _option_spec("id_column", lt("ID-Spalte", "ID column"), default="id", description=lt("Optionale Dokument-ID; sonst erzeugt der Import stabile IDs.", "Optional document ID. Otherwise the import generates stable IDs.")),
    _option_spec("pair_key_column", lt("Pair-Key-Spalte", "Pair key column"), default="pair_id", required=True, description=lt("Gruppiert Zeilen, die zusammengehören.", "Groups rows that belong together.")),
    _option_spec("pair_role_column", lt("Pair-Role-Spalte", "Pair role column"), default="pair_role", required=True, description=lt("Rolle innerhalb einer Pair-Gruppe.", "Role within a pair group.")),
    _option_spec("anchor_role", lt("Ankerrolle", "Anchor role"), default="source", required=True, description=lt("Rolle, die als Anker der Pair-Gruppe dient.", "Role that serves as the anchor of the pair group.")),
    _option_spec("pair_axis", lt("Pair-Achse", "Pair axis"), default="prealigned", description=lt("Name der Pairing-Achse im Manifest.", "Name of the pairing axis in the manifest.")),
    _option_spec(
        "pair_order",
        lt("Pair-Reihenfolge", "Pair order"),
        "choice",
        default="unsorted",
        choices=(
            _choice("unsorted", lt("unsortiert", "unsorted"), lt("Sicher, aber puffert Pair-Gruppen.", "Safe, but buffers pair groups.")),
            _choice("grouped", lt("gruppiert", "grouped"), lt("Speicherschonend, wenn gleiche Pair-Keys zusammenhängend stehen.", "Saves memory when identical pair keys are contiguous.")),
            _choice("sorted", lt("sortiert", "sorted"), lt("Alias für grouped.", "Alias for grouped.")),
        ),
        description=lt("Speicher-/Validierungsannahme über die Reihenfolge der Pair-Keys.", "Memory and validation assumption about the order of the pair keys."),
    ),
    _option_spec("meta_columns", lt("Metadatenspalten", "Metadata columns"), "string_list", default=[], description=lt("Zusätzliche Spalten, die als Dokumentmetadaten übernommen werden.", "Additional columns imported as document metadata.")),
    _option_spec("source", lt("Quellenlabel", "Source label"), default="", description=lt("Freies Quellenlabel für den Import.", "Free-form source label for the import.")),
    _option_spec("variant_column", lt("Variantenspalte", "Variant column"), default="", description=lt("Optionale Spalte für Textvarianten.", "Optional column for text variants.")),
    _option_spec("model_column", lt("Modellspalte", "Model column"), default="", description=lt("Optionale Spalte für Modell-/Erzeugerangaben.", "Optional column for model or generator information.")),
    _option_spec(
        "reject_policy",
        lt("Reject-Policy", "Reject policy"),
        "choice",
        default="collect",
        choices=(
            _choice("collect", "collect", lt("Import läuft weiter und dokumentiert verworfene Zeilen.", "The import continues and records rejected rows.")),
            _choice("fail_fast", "fail_fast", lt("Import bricht beim ersten methodischen Fehler ab.", "The import stops at the first methodological error.")),
        ),
        description=lt("Umgang mit leeren Texten, fehlenden Pair-Keys oder fehlenden Rollen.", "Handling of empty texts, missing pair keys or missing roles."),
    ),
    _option_spec("reject_report", lt("Reject-Report-Pfad", "Rejected rows report path"), "path", default="", description=lt("Optionaler expliziter Pfad für den Reject-Report.", "Optional explicit path for the rejected rows report.")),
)

_REJECT_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "reject_policy",
        lt("Reject-Policy", "Reject policy"),
        "choice",
        default="collect",
        choices=(
            _choice("collect", "collect", lt("Import läuft weiter und dokumentiert verworfene Zeilen im Reject-Report.", "The import continues and records rejected rows in the rejected rows report.")),
            _choice("fail_fast", "fail_fast", lt("Import bricht beim ersten methodischen Fehler ab.", "The import stops at the first methodological error.")),
        ),
        description=lt("Umgang mit leeren Texten oder methodisch defekten Zeilen.", "Handling of empty texts or methodologically defective rows."),
    ),
    _option_spec("reject_report", lt("Reject-Report-Pfad", "Rejected rows report path"), "path", default="", description=lt("Optionaler expliziter Pfad für den Reject-Report.", "Optional explicit path for the rejected rows report.")),
)

_UNPAIRED_TABULAR_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "text_column",
        lt("Textspalte", "Text column"),
        default="text",
        required=True,
        description=lt("Spalte bzw. Feld, das als Dokumenttext indexiert wird.", "Column or field indexed as the document text."),
    ),
    _option_spec(
        "id_column",
        lt("ID-Spalte", "ID column"),
        default="",
        description=lt("Optionale Dokument-ID; leer erzeugt der Import stabile IDs.", "Optional document ID. If empty, the import generates stable IDs."),
    ),
    _option_spec(
        "meta_columns",
        lt("Metadatenspalten", "Metadata columns"),
        "string_list",
        default=[],
        description=lt("Zusätzliche Spalten/Felder, die als Dokumentmetadaten übernommen werden.", "Additional columns or fields imported as document metadata."),
    ),
    _option_spec("source", lt("Quellenlabel", "Source label"), default="", description=lt("Freies Quellenlabel für den Import.", "Free-form source label for the import.")),
)

_CSV_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    *_UNPAIRED_TABULAR_OPTION_SPECS,
    _option_spec(
        "delimiter",
        lt("CSV-Trenner", "CSV delimiter"),
        default="",
        description=lt(
            "Optionaler Delimiter. Leer nutzt die Autoerkennung (csv.Sniffer über "
            "Komma, Semikolon, Tab und Pipe auf einem 8-KiB-Sample; ohne Treffer "
            "fällt der Import auf Komma zurück).",
            "Optional delimiter. If empty, the import detects it with csv.Sniffer "
            "over comma, semicolon, tab and pipe on an 8 KiB sample. Without a "
            "match it falls back to comma.",
        ),
    ),
    *_REJECT_OPTION_SPECS,
)

_JSONL_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "text_column",
        lt("Textfeld", "Text field"),
        default="text",
        required=True,
        description=lt("Feld mit dem Dokumenttext; Dot-Pfade wie payload.text sind erlaubt.", "Field with the document text. Dot paths such as payload.text are allowed."),
    ),
    _option_spec(
        "id_column",
        lt("ID-Feld", "ID field"),
        default="",
        description=lt("Optionales ID-Feld (Dot-Pfade erlaubt); leer erzeugt der Import stabile IDs.", "Optional ID field (dot paths allowed). If empty, the import generates stable IDs."),
    ),
    _option_spec(
        "meta_columns",
        lt("Metadatenfelder", "Metadata fields"),
        "string_list",
        default=[],
        description=lt("Zusätzliche Felder (Dot-Pfade erlaubt), die als Dokumentmetadaten übernommen werden.", "Additional fields (dot paths allowed) imported as document metadata."),
    ),
    _option_spec("source", lt("Quellenlabel", "Source label"), default="", description=lt("Freies Quellenlabel für den Import.", "Free-form source label for the import.")),
    *_REJECT_OPTION_SPECS,
)

_PLAINTEXT_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "pattern",
        lt("Dateimuster", "File pattern"),
        default="*.txt",
        description=lt("Glob-Muster für die rekursive Dateisuche unterhalb des Eingabeverzeichnisses.", "Glob pattern for the recursive file search below the input directory."),
    ),
    _option_spec(
        "split_paragraphs",
        lt("Absätze als Dokumente", "Paragraphs as documents"),
        "boolean",
        default=False,
        description=lt("Zerlegt jede Datei an Leerzeilen in ein Dokument pro Absatz.", "Splits each file at blank lines into one document per paragraph."),
    ),
    _option_spec(
        "source",
        lt("Quellenlabel", "Source label"),
        default="",
        description=lt(
            "Freies Quellenlabel. Das register-Metadatum wird aus dem unmittelbaren "
            "Elternordner jeder Datei abgeleitet; die Dokument-ID aus dem relativen Pfad.",
            "Free-form source label. The register metadata value is derived from the "
            "immediate parent folder of each file, the document ID from the relative path.",
        ),
    ),
    *_REJECT_OPTION_SPECS,
)

_HF_OPTION_SPECS: tuple[dict[str, Any], ...] = (
    _option_spec(
        "text_column",
        lt("Textspalte", "Text column"),
        default="text",
        required=True,
        description=lt("Dataset-Spalte, die als Dokumenttext indexiert wird.", "Dataset column indexed as the document text."),
    ),
    _option_spec(
        "id_column",
        lt("ID-Spalte", "ID column"),
        default="",
        description=lt("Optionale Dokument-ID-Spalte; leer erzeugt der Import stabile IDs.", "Optional document ID column. If empty, the import generates stable IDs."),
    ),
    _option_spec(
        "meta_columns",
        lt("Metadatenspalten", "Metadata columns"),
        "string_list",
        default=[],
        description=lt("Zusätzliche Dataset-Spalten, die als Dokumentmetadaten übernommen werden.", "Additional dataset columns imported as document metadata."),
    ),
    _option_spec("config", lt("Dataset-Konfiguration", "Dataset configuration"), default="", description=lt("Optionaler Config-Name des Datasets.", "Optional configuration name of the dataset.")),
    _option_spec("split", "Split", default="train", description=lt("Dataset-Split, der importiert wird.", "Dataset split to import.")),
    _option_spec(
        "limit",
        lt("Zeilenlimit", "Row limit"),
        "integer",
        default=0,
        description=lt("Maximale Zeilenzahl (0 = unbegrenzt). Begrenzt Umfang und Laufzeit des Streaming-Imports.", "Maximum number of rows (0 = unlimited). Limits the size and run time of the streaming import."),
    ),
    _option_spec("source", lt("Quellenlabel", "Source label"), default="", description=lt("Freies Quellenlabel für den Import.", "Free-form source label for the import.")),
    *_REJECT_OPTION_SPECS,
)

_METHOD_OPTION_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "parquet": _PARQUET_OPTION_SPECS,
    "vrt": _VRT_OPTION_SPECS,
    "prealigned_parquet": _PREALIGNED_OPTION_SPECS,
    "prealigned_csv": (
        *_PREALIGNED_OPTION_SPECS,
        _option_spec("delimiter", lt("CSV-Trenner", "CSV delimiter"), default="", description=lt("Optionaler Delimiter; leer nutzt die CSV-Autoerkennung.", "Optional delimiter. If empty, CSV auto-detection is used.")),
    ),
    "prealigned_jsonl": _PREALIGNED_OPTION_SPECS,
    "plaintext": _PLAINTEXT_OPTION_SPECS,
    "csv": _CSV_OPTION_SPECS,
    "jsonl": _JSONL_OPTION_SPECS,
    "hf": _HF_OPTION_SPECS,
}

_METHOD_DESCRIPTIONS = {
    "parquet": lt("Bereits tabellarisch normalisierte Parquet-Daten mit input_text als Default-Textspalte.", "Parquet data already normalized as a table, with input_text as the default text column."),
    "vrt": lt("VRT/XML-artige Text- und Tokenstrukturen mit konfigurierbaren Tags.", "VRT or XML-like text and token structures with configurable tags."),
    "prealigned_parquet": lt("Extern gepaarte Parquet-Daten mit Pair-Key/Pair-Role-Spalten.", "Externally paired Parquet data with pair key and pair role columns."),
    "prealigned_csv": lt("Extern gepaarte CSV/TSV-Daten mit Pair-Key/Pair-Role-Spalten.", "Externally paired CSV/TSV data with pair key and pair role columns."),
    "prealigned_jsonl": lt("Extern gepaarte JSONL-Daten mit Pair-Key/Pair-Role-Feldern.", "Externally paired JSONL data with pair key and pair role fields."),
    "plaintext": lt(
        "Ordner, Einzeldatei oder Glob mit Textdateien; ein Dokument pro Datei "
        "(optional pro Absatz), register aus dem Elternordner.",
        "Folder, single file or glob with text files. One document per file "
        "(optionally per paragraph), register from the parent folder.",
    ),
    "csv": lt("Ungepaarte CSV/TSV-Tabellen mit konfigurierbarer Text- und ID-Spalte.", "Unpaired CSV/TSV tables with configurable text and ID columns."),
    "jsonl": lt("Ungepaarte JSONL-Zeilen mit konfigurierbarem Text- und ID-Feld (Dot-Pfade erlaubt).", "Unpaired JSONL lines with configurable text and ID fields (dot paths allowed)."),
    "hf": lt(
        "HuggingFace-Dataset per Dataset-ID; Download erfolgt erst beim Import "
        "(Streaming), trust_remote_code bleibt hart deaktiviert.",
        "Hugging Face dataset by dataset ID. The download happens during the import "
        "(streaming). trust_remote_code is always disabled.",
    ),
}

_METHOD_LABELS = {
    "parquet": "Parquet",
    "vrt": "VRT/XML",
    "prealigned_parquet": "Pre-grouped Parquet",
    "prealigned_csv": "Pre-grouped CSV/TSV",
    "prealigned_jsonl": "Pre-grouped JSONL",
    "plaintext": lt("Plaintext (Ordner/Datei)", "Plain text (folder or file)"),
    "csv": "CSV/TSV",
    "jsonl": "JSONL",
    "hf": lt("HuggingFace-Dataset", "Hugging Face dataset"),
}

_METHOD_INPUT_SPECS: dict[str, dict[str, Any]] = {
    "parquet": {
        "kind": "server_file",
        "extensions": [".parquet"],
        "accepts_directories": False,
        "path_hint": lt("/data/imports/korpus.parquet", "/data/imports/corpus.parquet"),
        "description": lt("Pfad zu einer serverseitig lesbaren Parquet-Datei.", "Path to a Parquet file readable on the server."),
    },
    "vrt": {
        "kind": "server_file",
        "extensions": [".vrt", ".xml"],
        "accepts_directories": False,
        "path_hint": lt("/data/imports/korpus.vrt", "/data/imports/corpus.vrt"),
        "description": lt("Pfad zu einer VRT/XML-artigen Datei auf dem Backend-Server.", "Path to a VRT or XML-like file on the server."),
    },
    "prealigned_parquet": {
        "kind": "server_file",
        "extensions": [".parquet"],
        "accepts_directories": False,
        "path_hint": "/data/imports/paired.parquet",
        "description": lt("Parquet-Datei mit Pair-Key/Pair-Role-Spalten.", "Parquet file with pair key and pair role columns."),
    },
    "prealigned_csv": {
        "kind": "server_file",
        "extensions": [".csv", ".tsv"],
        "accepts_directories": False,
        "path_hint": "/data/imports/paired.csv",
        "description": lt("CSV/TSV-Datei mit Pair-Key/Pair-Role-Spalten.", "CSV/TSV file with pair key and pair role columns."),
    },
    "prealigned_jsonl": {
        "kind": "server_file",
        "extensions": [".jsonl", ".ndjson"],
        "accepts_directories": False,
        "path_hint": "/data/imports/paired.jsonl",
        "description": lt("JSONL-Datei mit Pair-Key/Pair-Role-Feldern.", "JSONL file with pair key and pair role fields."),
    },
    "plaintext": {
        "kind": "server_file",
        "extensions": [],
        "accepts_directories": True,
        "path_hint": lt("/data/imports/texte/", "/data/imports/texts/"),
        "description": lt(
            "Serverseitig lesbares Verzeichnis (rekursiv per Dateimuster) oder "
            "eine einzelne Textdatei.",
            "Directory readable on the server (searched recursively by file pattern) "
            "or a single text file.",
        ),
    },
    "csv": {
        "kind": "server_file",
        "extensions": [".csv", ".tsv"],
        "accepts_directories": False,
        "path_hint": lt("/data/imports/korpus.csv", "/data/imports/corpus.csv"),
        "description": lt("Pfad zu einer serverseitig lesbaren CSV/TSV-Datei.", "Path to a CSV/TSV file readable on the server."),
    },
    "jsonl": {
        "kind": "server_file",
        "extensions": [".jsonl", ".ndjson"],
        "accepts_directories": False,
        "path_hint": lt("/data/imports/korpus.jsonl", "/data/imports/corpus.jsonl"),
        "description": lt("Pfad zu einer serverseitig lesbaren JSONL-Datei.", "Path to a JSONL file readable on the server."),
    },
    "hf": {
        "kind": "hf_dataset",
        "extensions": [],
        "accepts_directories": False,
        "path_hint": "organisation/dataset-name",
        "description": lt(
            "HuggingFace-Dataset-ID (kein Serverpfad). Der Download erfolgt erst "
            "beim Import; der Preflight bleibt ohne Netzzugriff.",
            "Hugging Face dataset ID (not a server path). The download happens "
            "during the import. The preflight check runs without network access.",
        ),
    },
}

_PARQUET_COLUMNS: tuple[dict[str, Any], ...] = (
    _column_spec(
        "input_text",
        lt("Textspalte", "Text column"),
        required=True,
        description=lt("Default-Textspalte für ungepaarte Parquet-Importe.", "Default text column for unpaired Parquet imports."),
        default_option="text_column",
    ),
    _column_spec(
        "id",
        lt("Dokument-ID", "Document ID"),
        required=False,
        description=lt("Optionale Default-ID-Spalte.", "Optional default ID column."),
        default_option="id_column",
    ),
)
_PREALIGNED_COLUMNS: tuple[dict[str, Any], ...] = (
    _column_spec("text", "Text", required=True, description=lt("Default-Textspalte.", "Default text column."), default_option="text_column"),
    _column_spec("pair_id", lt("Pair-Key", "Pair key"), required=True, description=lt("Default-Spalte für Pair-Gruppen.", "Default column for pair groups."), default_option="pair_key_column"),
    _column_spec("pair_role", lt("Pair-Role", "Pair role"), required=True, description=lt("Default-Spalte für Rollen innerhalb einer Pair-Gruppe.", "Default column for roles within a pair group."), default_option="pair_role_column"),
    _column_spec("id", lt("Dokument-ID", "Document ID"), required=False, description=lt("Optionale Default-ID-Spalte.", "Optional default ID column."), default_option="id_column"),
)
_UNPAIRED_TEXT_COLUMNS: tuple[dict[str, Any], ...] = (
    _column_spec(
        "text",
        lt("Textspalte", "Text column"),
        required=True,
        description=lt("Default-Textspalte/-Feld für ungepaarte Importe.", "Default text column or field for unpaired imports."),
        default_option="text_column",
    ),
    _column_spec(
        "id",
        lt("Dokument-ID", "Document ID"),
        required=False,
        description=lt("Optionale Default-ID-Spalte.", "Optional default ID column."),
        default_option="id_column",
    ),
)
_METHOD_EXPECTED_COLUMNS: dict[str, tuple[dict[str, Any], ...]] = {
    "parquet": _PARQUET_COLUMNS,
    "vrt": (),
    "prealigned_parquet": _PREALIGNED_COLUMNS,
    "prealigned_csv": _PREALIGNED_COLUMNS,
    "prealigned_jsonl": _PREALIGNED_COLUMNS,
    "plaintext": (),
    "csv": _UNPAIRED_TEXT_COLUMNS,
    "jsonl": _UNPAIRED_TEXT_COLUMNS,
    # hf: gleiche Spaltenerwartung, aber im Preflight NICHT verifizierbar
    # (kein Netzzugriff); die Prüfung passiert erst beim Import.
    "hf": _UNPAIRED_TEXT_COLUMNS,
}

_COMMON_OUTPUT_FEATURES = (
    "word_tokens",
    "document_metadata",
    "frequency_word",
    "kwic_ready",
)
_METHOD_OUTPUT_SPECS: dict[str, dict[str, Any]] = {
    "parquet": {
        "paired": False,
        "paired_data_dependent": False,
        "pairing_kind": "none",
        "emitted_features": [*_COMMON_OUTPUT_FEATURES, "lemma_pos_spacy", "optional_ner", "optional_deps"],
        "guarantees": [lt("vollständiger Indexbau oder fehlgeschlagener Job", "complete index build or failed job")],
        "limitations": [lt("Parquet-Spaltensemantik wird nicht als Forschungsdesign validiert.", "Parquet column semantics are not validated as a research design.")],
    },
    "vrt": {
        "paired": False,
        "pairing_kind": "none",
        "emitted_features": [
            *_COMMON_OUTPUT_FEATURES,
            "lemma_pos_spacy",
            "optional_lemma_pos_gold_adopt",
            "optional_ner",
            "optional_deps",
            "vrt_import_report",
        ],
        "guarantees": [lt("VRT-Struktur wird geparst und im Importreport dokumentiert.", "The VRT structure is parsed and documented in the import report.")],
        "limitations": [
            lt("VRT-Annotationen werden, je nach annotation_mode, als importierte Evidenz übernommen oder neu erzeugt.", "Depending on annotation_mode, VRT annotations are adopted as imported evidence or regenerated."),
            lt("annotation_mode=adopt übernimmt Gold-Tags roh (tagset=raw, kein UD-Mapping); NER/Dependenzen aus spaCy sind in diesem Modus nicht verfügbar.", "annotation_mode=adopt copies gold tags unchanged (tagset=raw, no UD mapping). spaCy named entities and dependency relations are not available in this mode."),
        ],
    },
    "prealigned_parquet": {
        "paired": True,
        "pairing_kind": "external_pair_keys",
        "emitted_features": [*_COMMON_OUTPUT_FEATURES, "pair_metadata", "pair_axes", "paired_with", "reject_summary"],
        "guarantees": [lt("Pair-Key/Pair-Role-Struktur wird geprüft.", "The pair key and pair role structure is checked.")],
        "limitations": [
            lt("Der Import prüft Paarstruktur, aber keine inhaltliche Übersetzungs- oder Alignmentqualität.", "The import checks the pair structure, but not the quality of translations or alignments."),
            lt("Automatische Sentence-Embedding-, embed- oder hybrid-Alignment-Builds bleiben Expert/API/CLI.", "Automatic sentence embedding, embed or hybrid alignment builds remain Expert/API/CLI features."),
        ],
    },
    "prealigned_csv": {
        "paired": True,
        "pairing_kind": "external_pair_keys",
        "emitted_features": [*_COMMON_OUTPUT_FEATURES, "pair_metadata", "pair_axes", "paired_with", "reject_summary"],
        "guarantees": [lt("Pair-Key/Pair-Role-Struktur wird geprüft.", "The pair key and pair role structure is checked.")],
        "limitations": [
            lt("Der Import prüft Paarstruktur, aber keine inhaltliche Übersetzungs- oder Alignmentqualität.", "The import checks the pair structure, but not the quality of translations or alignments."),
            lt("Automatische Sentence-Embedding-, embed- oder hybrid-Alignment-Builds bleiben Expert/API/CLI.", "Automatic sentence embedding, embed or hybrid alignment builds remain Expert/API/CLI features."),
        ],
    },
    "prealigned_jsonl": {
        "paired": True,
        "pairing_kind": "external_pair_keys",
        "emitted_features": [*_COMMON_OUTPUT_FEATURES, "pair_metadata", "pair_axes", "paired_with", "reject_summary"],
        "guarantees": [lt("Pair-Key/Pair-Role-Struktur wird geprüft.", "The pair key and pair role structure is checked.")],
        "limitations": [
            lt("Der Import prüft Paarstruktur, aber keine inhaltliche Übersetzungs- oder Alignmentqualität.", "The import checks the pair structure, but not the quality of translations or alignments."),
            lt("Automatische Sentence-Embedding-, embed- oder hybrid-Alignment-Builds bleiben Expert/API/CLI.", "Automatic sentence embedding, embed or hybrid alignment builds remain Expert/API/CLI features."),
        ],
    },
    "plaintext": {
        "paired": False,
        "paired_data_dependent": False,
        "pairing_kind": "none",
        "emitted_features": [
            *_COMMON_OUTPUT_FEATURES,
            "lemma_pos_spacy",
            "optional_ner",
            "optional_deps",
            "register_from_parent_dir",
            "reject_summary",
        ],
        "guarantees": [
            lt("Ein Dokument pro Datei (oder pro Absatz bei split_paragraphs).", "One document per file (or per paragraph with split_paragraphs)."),
            lt("Dokument-ID aus dem relativen Pfad, register aus dem unmittelbaren Elternordner.", "Document ID from the relative path, register from the immediate parent folder."),
        ],
        "limitations": [
            lt("Nicht-UTF-8-Dateien werden per Encoding-Erkennung bestmöglich dekodiert (ersatzweise mit Ersatzzeichen), nicht abgelehnt.", "Non-UTF-8 files are decoded as well as possible by encoding detection (with replacement characters where needed), not rejected."),
            lt("Symlinks, deren Ziel das Eingabeverzeichnis verlässt, werden übersprungen.", "Symlinks whose target lies outside the input directory are skipped."),
        ],
    },
    "csv": {
        "paired": False,
        "paired_data_dependent": False,
        "pairing_kind": "none",
        "emitted_features": [
            *_COMMON_OUTPUT_FEATURES,
            "lemma_pos_spacy",
            "optional_ner",
            "optional_deps",
            "reject_summary",
        ],
        "guarantees": [lt("Genau die konfigurierte Textspalte wird indexiert; Delimiter wird dokumentiert erkannt.", "Exactly the configured text column is indexed. The delimiter is detected and documented.")],
        "limitations": [
            lt("CSV-Spaltensemantik wird nicht als Forschungsdesign validiert.", "CSV column semantics are not validated as a research design."),
            lt("Delimiter-Autoerkennung arbeitet auf einem bounded Sample; bei exotischen Formaten delimiter explizit setzen.", "Delimiter detection works on a bounded sample. For unusual formats, set delimiter explicitly."),
        ],
    },
    "jsonl": {
        "paired": False,
        "paired_data_dependent": False,
        "pairing_kind": "none",
        "emitted_features": [
            *_COMMON_OUTPUT_FEATURES,
            "lemma_pos_spacy",
            "optional_ner",
            "optional_deps",
            "reject_summary",
        ],
        "guarantees": [lt("Fehlerhafte, überlange oder Nicht-Objekt-Zeilen werden dokumentiert verworfen statt den Import abzubrechen.", "Malformed, overlong or non-object lines are rejected and documented instead of stopping the import.")],
        "limitations": [
            lt("JSONL-Feldsemantik wird nicht als Forschungsdesign validiert.", "JSONL field semantics are not validated as a research design."),
        ],
    },
    "hf": {
        "paired": False,
        "paired_data_dependent": False,
        "pairing_kind": "none",
        "emitted_features": [
            *_COMMON_OUTPUT_FEATURES,
            "lemma_pos_spacy",
            "optional_ner",
            "optional_deps",
            "reject_summary",
        ],
        "guarantees": [
            lt("Streaming-Import mit optionalem Zeilenlimit; die Dataset-ID wird unverändert als Provenienz dokumentiert.", "Streaming import with an optional row limit. The dataset ID is documented unchanged as provenance."),
        ],
        "limitations": [
            lt("Der Import benötigt Netzzugriff und das Paket 'datasets'; der Preflight validiert nur den Descriptor ohne Netzzugriff.", "The import needs network access and the package 'datasets'. The preflight check validates only the descriptor, without network access."),
            lt("Sicherheitsgrenze: trust_remote_code bleibt hart False — Datasets, die eigenen Code ausführen wollen, werden nicht importiert.", "Security boundary: trust_remote_code is always False. Datasets that want to run their own code are not imported."),
            lt("Spalten und Splits werden erst beim Import geprüft, nicht im Preflight.", "Columns and splits are checked during the import, not in the preflight check."),
        ],
    },
}

_METHOD_REPORT_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "parquet": (
        {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
        {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Capability- und Provenienzbeschreibung des erzeugten Index.", "Capability and provenance description of the generated index.")},
        {"key": "build_meta", "label": lt("Build-Metadaten", "Build metadata"), "description": lt("Technische Build-Parameter und optionale Reject-Summary.", "Technical build parameters and an optional rejected rows summary.")},
    ),
    "vrt": (
        {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
        {"key": "vrt_import_report", "label": lt("VRT-Importreport", "VRT import report"), "description": lt("Strukturdiagnostik und erkannte VRT-Metadaten.", "Structure diagnostics and detected VRT metadata.")},
        {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Capability- und Provenienzbeschreibung des erzeugten Index.", "Capability and provenance description of the generated index.")},
    ),
    "prealigned_parquet": (
        {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
        {"key": "reject_report", "label": lt("Reject-Report", "Rejected rows report"), "description": lt("Verworfene Zeilen bei collect-Policy.", "Rejected rows under the collect policy.")},
        {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Pairing-Capabilities und Provenienzbeschreibung.", "Pairing capabilities and provenance description.")},
    ),
    "prealigned_csv": (
        {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
        {"key": "reject_report", "label": lt("Reject-Report", "Rejected rows report"), "description": lt("Verworfene Zeilen bei collect-Policy.", "Rejected rows under the collect policy.")},
        {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Pairing-Capabilities und Provenienzbeschreibung.", "Pairing capabilities and provenance description.")},
    ),
    "prealigned_jsonl": (
        {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
        {"key": "reject_report", "label": lt("Reject-Report", "Rejected rows report"), "description": lt("Verworfene Zeilen bei collect-Policy.", "Rejected rows under the collect policy.")},
        {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Pairing-Capabilities und Provenienzbeschreibung.", "Pairing capabilities and provenance description.")},
    ),
}
_UNPAIRED_ADAPTER_REPORT_SPECS: tuple[dict[str, Any], ...] = (
    {"key": "build_report", "label": lt("Build-Report", "Build report"), "description": lt("Status, Token-/Dokumentzahlen und Build-Phasen.", "Status, token and document counts, and build phases.")},
    {"key": "reject_report", "label": lt("Reject-Report", "Rejected rows report"), "description": lt("Verworfene Zeilen bei collect-Policy.", "Rejected rows under the collect policy.")},
    {"key": "manifest", "label": lt("Index-Manifest", "Index manifest"), "description": lt("Capability- und Provenienzbeschreibung des erzeugten Index.", "Capability and provenance description of the generated index.")},
    {"key": "build_meta", "label": lt("Build-Metadaten", "Build metadata"), "description": lt("Technische Build-Parameter und optionale Reject-Summary.", "Technical build parameters and an optional rejected rows summary.")},
)
for _adapter_method in ("plaintext", "csv", "jsonl", "hf"):
    _METHOD_REPORT_SPECS[_adapter_method] = _UNPAIRED_ADAPTER_REPORT_SPECS

_PARQUET_TEXT_CANDIDATE_COLUMNS = ("text", "target_text", "source_text")
# Ungepaarte Tabellenadapter (csv/jsonl): breitere, aber weiterhin bounded
# Kandidatenliste für den text_column-Mapping-Vorschlag.
_TEXT_CANDIDATE_COLUMNS_BY_METHOD: dict[str, tuple[str, ...]] = {
    "parquet": _PARQUET_TEXT_CANDIDATE_COLUMNS,
    "csv": ("text", "body", "content", "input_text", "target_text", "source_text"),
    "jsonl": ("text", "body", "content", "input_text", "target_text", "source_text"),
}


def _text_column_mapping_evidence(
    columns: Iterable[str],
    *,
    expected_column: str,
    candidate_columns: Iterable[str] = _PARQUET_TEXT_CANDIDATE_COLUMNS,
    fallback_behavior: str = lt("Der Import indexiert genau die konfigurierte Textspalte.", "The import indexes exactly the configured text column."),
) -> dict[str, Any] | None:
    column_set = set(columns)
    candidates = [
        column
        for column in candidate_columns
        if column in column_set and column != expected_column
    ]
    if not candidates:
        return None
    suggested = candidates[0]
    return {
        "missing_column": expected_column,
        "candidate_columns": candidates,
        "safe_mapping": lt("text_column={suggested} setzen, wenn diese Spalte den Dokumenttext enthält.", "Set text_column={suggested} if this column contains the document text.").format(suggested=suggested),
        "suggested_options": {"text_column": suggested},
        "fallback_behavior": fallback_behavior,
    }


def _parquet_text_column_mapping_evidence(
    columns: Iterable[str],
    *,
    expected_column: str,
) -> dict[str, Any] | None:
    return _text_column_mapping_evidence(
        columns,
        expected_column=expected_column,
        candidate_columns=_PARQUET_TEXT_CANDIDATE_COLUMNS,
        fallback_behavior=lt("Der generische Parquet-Import indexiert genau die konfigurierte Textspalte.", "The generic Parquet import indexes exactly the configured text column."),
    )


def _option_specs_for_method(method: str) -> list[dict[str, Any]]:
    specs = (*_COMMON_OPTION_SPECS, *_METHOD_OPTION_SPECS.get(method, ()))
    deduped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for spec in specs:
        deduped[str(spec["key"])] = dict(spec)
    return list(deduped.values())


def _method_ui_workflow(method: str) -> dict[str, str]:
    if method.startswith("prealigned_"):
        return {
            "status": "first_class",
            "label": "First-class Import",
            "reason": lt(
                "Prealigned-Dateien laufen über denselben UI-Pfad wie andere Importe: "
                "Methode wählen, Pair-Spalten konfigurieren, Preflight prüfen und Job überwachen. "
                "Der First-class-Pfad erwartet bereits gepaarte Zeilen; automatische "
                "Sentence-Embedding-, embed- oder hybrid-Alignment-Builds bleiben Expert/API/CLI.",
                "Pre-aligned files use the same interface path as other imports: "
                "choose the method, configure the pair columns, run the preflight check and monitor the job. "
                "The first-class path expects rows that are already paired. Automatic "
                "sentence embedding, embed or hybrid alignment builds remain Expert/API/CLI features.",
            ),
        }
    return {
        "status": "first_class",
        "label": "First-class Import",
        "reason": lt("Diese Methode ist im Importmanager mit Preflight und Jobmonitoring bedienbar.", "This method can be used in the import manager with a preflight check and job monitoring."),
    }


def import_method_descriptors() -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    for method in supported_import_methods():
        option_specs = _option_specs_for_method(method)
        output = dict(_METHOD_OUTPUT_SPECS.get(method, {}))
        emitted_features = list(output.get("emitted_features") or [])
        descriptors.append(
            {
                "schema_version": _IMPORT_METHOD_SCHEMA_VERSION,
                "method": method,
                "label": _METHOD_LABELS.get(method, method.replace("_", "-")),
                "description": _METHOD_DESCRIPTIONS.get(method, lt("Serverseitige Importmethode.", "Server-side import method.")),
                "input": dict(_METHOD_INPUT_SPECS.get(method, {"kind": "server_file"})),
                "availability": _builder_availability(method),
                "ui_workflow": _method_ui_workflow(method),
                "option_specs": option_specs,
                "option_keys": [str(spec["key"]) for spec in option_specs],
                "expected_columns": [dict(item) for item in _METHOD_EXPECTED_COLUMNS.get(method, ())],
                "output": output,
                "emitted_features": emitted_features,
                "reports": [dict(item) for item in _METHOD_REPORT_SPECS.get(method, ())],
            }
        )
    return descriptors


def _descriptor_for_method(method: str) -> dict[str, Any] | None:
    method_key = normalize_import_method(method)
    for descriptor in import_method_descriptors():
        if descriptor.get("method") == method_key:
            return descriptor
    return None


def _preflight_check(
    checks: list[dict[str, Any]],
    key: str,
    label: str,
    status: str,
    message: str,
    *,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    severity = "error" if status == "fail" else "warning" if status == "warn" else "info"
    checks.append(
        {
            "key": key,
            "label": label,
            "status": status,
            "severity": severity,
            "blocking": status == "fail",
            "message": message,
            "evidence": dict(evidence or {}),
        }
    )


def _read_text_sample(path: Path, max_bytes: int = _DEFAULT_PREFLIGHT_TEXT_BYTES) -> tuple[str, dict[str, Any]]:
    with path.open("rb") as fh:
        raw = fh.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    data = raw[:max_bytes]
    return data.decode("utf-8", errors="replace"), {
        "sample_bytes": len(data),
        "sample_byte_limit": max_bytes,
        "sample_truncated": truncated,
    }


def _preflight_csv_columns(path: Path, delimiter: object | None) -> tuple[list[str], dict[str, Any] | None]:
    try:
        sample, sample_meta = _read_text_sample(path)
        if not sample:
            return [], {"warning": "csv_empty_sample"}
        # Same delimiter detection as the builder (ingest_adapters.iter_csv_rows).
        from candyconc.ingest.ingest_adapters import detect_csv_delimiter

        dialect = csv.excel()
        if isinstance(delimiter, str) and delimiter:
            dialect.delimiter = delimiter
        else:
            dialect.delimiter = detect_csv_delimiter(sample, suffix=path.suffix)
        reader = csv.reader(sample.splitlines(), dialect)
        header = next(reader, [])
        return [str(item).strip() for item in header if str(item).strip()], {
            "delimiter": getattr(dialect, "delimiter", None),
            **sample_meta,
        }
    except Exception as exc:
        return [], {"warning": "csv_schema_unavailable", "error": str(exc)}


def _flatten_record(
    value: Mapping[str, Any],
    *,
    prefix: str = "",
    out: dict[str, Any] | None = None,
    max_keys: int = 1000,
) -> dict[str, Any]:
    target = out if out is not None else {}
    for key, item in value.items():
        if len(target) >= max_keys:
            break
        text_key = str(key)
        path = f"{prefix}.{text_key}" if prefix else text_key
        target[path] = item
        if isinstance(item, Mapping):
            _flatten_record(item, prefix=path, out=target, max_keys=max_keys)
    return target


def _iter_jsonl_sample_lines(
    path: Path,
    *,
    max_bytes: int = _DEFAULT_PREFLIGHT_JSONL_BYTES,
    max_rows: int = _DEFAULT_PREFLIGHT_JSONL_ROWS,
) -> tuple[list[bytes], dict[str, Any]]:
    """Collect complete JSONL records without reading beyond the byte budget."""
    lines: list[bytes] = []
    bytes_seen = 0
    truncated = False
    row_limit_reached = False
    with path.open("rb") as fh:
        while len(lines) < max_rows:
            remaining = max_bytes - bytes_seen
            if remaining <= 0:
                truncated = True
                break
            raw_line = fh.readline(remaining + 1)
            if not raw_line:
                break
            if len(raw_line) > remaining:
                bytes_seen = max_bytes
                truncated = True
                break
            bytes_seen += len(raw_line)
            lines.append(raw_line)
        if len(lines) >= max_rows:
            row_limit_reached = True
    return lines, {
        "sample_bytes": min(bytes_seen, max_bytes),
        "sample_byte_limit": max_bytes,
        "sample_truncated": truncated,
        "sample_row_limit": max_rows,
        "row_limit_reached": row_limit_reached,
    }


def _preflight_jsonl_columns(path: Path) -> tuple[list[str], dict[str, Any] | None]:
    columns: OrderedDict[str, None] = OrderedDict()
    rows = 0
    errors = 0
    try:
        raw_lines, sample_meta = _iter_jsonl_sample_lines(path)
        for raw_line in raw_lines:
            line = raw_line.decode("utf-8", errors="replace")
            text = line.strip()
            if not text:
                continue
            rows += 1
            try:
                value = json.loads(text)
            except ValueError:
                errors += 1
                continue
            if isinstance(value, Mapping):
                for key in _flatten_record(value):
                    columns.setdefault(str(key), None)
        return list(columns), {
            "sample_rows": rows,
            "parse_errors": errors,
            **sample_meta,
        }
    except Exception as exc:
        return [], {"warning": "jsonl_schema_unavailable", "error": str(exc)}


def _preflight_parquet_columns(path: Path) -> tuple[list[str], dict[str, Any] | None]:
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        schema = pq.read_schema(path)
        return [str(name) for name in schema.names], {"schema_reader": "pyarrow"}
    except Exception as exc:
        return [], {"warning": "parquet_schema_unavailable", "error": str(exc)}


def _configured_option(
    payload: Mapping[str, Any],
    snake_key: str,
    default: str,
) -> str:
    return str(payload.get(snake_key) or payload.get(snake_key.replace("_", "-")) or default)


def _preflight_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _preflight_pair_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text.strip() else ""


def _preflight_role_key(value: Any) -> str:
    value_text = _preflight_text(value).lower()
    return re.sub(r"\s+", "_", value_text) if value_text else ""


def _preflight_csv_rows(
    path: Path,
    delimiter: object | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        sample, sample_meta = _read_text_sample(path)
        if not sample:
            return [], {"warning": "csv_empty_sample"}
        # Same delimiter detection as the builder (ingest_adapters.iter_csv_rows).
        from candyconc.ingest.ingest_adapters import detect_csv_delimiter

        dialect = csv.excel()
        if isinstance(delimiter, str) and delimiter:
            dialect.delimiter = delimiter
        else:
            dialect.delimiter = detect_csv_delimiter(sample, suffix=path.suffix)
        reader = csv.DictReader(sample.splitlines(), dialect=dialect)
        rows: list[dict[str, Any]] = []
        for row in reader:
            if len(rows) >= limit:
                break
            rows.append({str(key): value for key, value in row.items() if key is not None})
        return rows, {
            "delimiter": getattr(dialect, "delimiter", None),
            "sample_rows": len(rows),
            "sample_row_limit": limit,
            "row_limit_reached": len(rows) >= limit,
            "sample_complete": not sample_meta["sample_truncated"] and len(rows) < limit,
            **sample_meta,
        }
    except Exception as exc:
        return [], {"warning": "csv_pair_sample_unavailable", "error": str(exc)}


def _preflight_jsonl_rows(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    rows: list[dict[str, Any]] = []
    parse_errors = 0
    try:
        raw_lines, sample_meta = _iter_jsonl_sample_lines(path, max_rows=limit)
        for raw_line in raw_lines:
            line = raw_line.decode("utf-8", errors="replace")
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except ValueError:
                parse_errors += 1
                continue
            if isinstance(value, Mapping):
                rows.append(_flatten_record(value))
        return rows, {
            "sample_rows": len(rows),
            "parse_errors": parse_errors,
            "sample_complete": not sample_meta["sample_truncated"] and not sample_meta["row_limit_reached"],
            **sample_meta,
        }
    except Exception as exc:
        return [], {"warning": "jsonl_pair_sample_unavailable", "error": str(exc)}


def _preflight_parquet_rows(path: Path, columns: list[str], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found]

        parquet = pq.ParquetFile(path)
        available_columns = set(str(name) for name in parquet.schema_arrow.names)
        requested_columns = [column for column in dict.fromkeys(columns) if column]
        selected_columns = [column for column in requested_columns if column in available_columns]
        if requested_columns and not selected_columns:
            return [], {
                "warning": "parquet_pair_sample_columns_unavailable",
                "schema_reader": "pyarrow",
                "requested_columns": requested_columns,
                "missing_columns": requested_columns,
                "sample_row_limit": limit,
                "total_rows": parquet.metadata.num_rows,
                "sample_complete": False,
            }
        batches = parquet.iter_batches(batch_size=limit, columns=selected_columns or None)
        batch = next(batches, None)
        if batch is None:
            return [], {
                "sample_rows": 0,
                "schema_reader": "pyarrow",
                "sample_row_limit": limit,
                "total_rows": parquet.metadata.num_rows,
                "sample_complete": True,
            }
        if hasattr(batch, "to_pylist"):
            py_rows = batch.to_pylist()
        else:  # pragma: no cover - compatibility with older pyarrow shapes
            import pyarrow as pa  # type: ignore[import-not-found]

            py_rows = pa.Table.from_batches([batch]).to_pylist()
        rows = [
            _flatten_record({str(key): value for key, value in row.items()})
            for row in py_rows
            if isinstance(row, Mapping)
        ]
        total_rows = parquet.metadata.num_rows
        return rows, {
            "sample_rows": len(rows),
            "schema_reader": "pyarrow",
            "sample_columns": selected_columns,
            "missing_columns": [column for column in requested_columns if column not in available_columns],
            "sample_row_limit": limit,
            "total_rows": total_rows,
            "row_limit_reached": len(rows) >= limit and total_rows > limit,
            "sample_complete": total_rows <= limit,
        }
    except Exception as exc:
        return [], {"warning": "parquet_pair_sample_unavailable", "error": str(exc)}


def _preflight_rows_for_method(
    method: str,
    path: Path,
    payload: Mapping[str, Any],
    columns: list[str],
    limit: int = _DEFAULT_PREFLIGHT_PAIR_ROWS,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    suffix = path.suffix.lower()
    if method in {"parquet", "prealigned_parquet"} or suffix == ".parquet":
        return _preflight_parquet_rows(path, columns, limit)
    if method == "prealigned_csv" or suffix in {".csv", ".tsv"}:
        return _preflight_csv_rows(path, payload.get("delimiter"), limit)
    if method == "prealigned_jsonl" or suffix in {".jsonl", ".ndjson"}:
        return _preflight_jsonl_rows(path, limit)
    return [], None


def _preflight_prealigned_pairing_evidence(
    method: str,
    path: Path,
    payload: Mapping[str, Any],
    columns: list[str],
) -> dict[str, Any]:
    text_column = _configured_option(payload, "text_column", "text")
    pair_key_column = _configured_option(payload, "pair_key_column", "pair_id")
    pair_role_column = _configured_option(payload, "pair_role_column", "pair_role")
    anchor_role = _preflight_role_key(_configured_option(payload, "anchor_role", "source"))
    pair_order = _preflight_role_key(_configured_option(payload, "pair_order", "unsorted")) or "unsorted"
    if pair_order == "sorted":
        pair_order = "grouped"
    sample_columns = list(dict.fromkeys([text_column, pair_key_column, pair_role_column]))
    rows, meta = _preflight_rows_for_method(method, path, payload, sample_columns)
    pair_counts: OrderedDict[str, int] = OrderedDict()
    anchor_counts: OrderedDict[str, int] = OrderedDict()
    role_counts: OrderedDict[str, int] = OrderedDict()
    closed_pair_keys: set[str] = set()
    active_pair_key: str | None = None
    non_contiguous_pair_keys: list[str] = []
    empty_text_rows = 0
    missing_pair_key_rows = 0
    missing_pair_role_rows = 0

    for row in rows:
        text_value = _preflight_text(row.get(text_column))
        pair_key = _preflight_pair_key(row.get(pair_key_column))
        pair_role = _preflight_role_key(row.get(pair_role_column))
        if not text_value:
            empty_text_rows += 1
            continue
        if not pair_key:
            missing_pair_key_rows += 1
            continue
        if not pair_role:
            missing_pair_role_rows += 1
            continue
        if pair_order == "grouped":
            if active_pair_key is None:
                if pair_key in closed_pair_keys and pair_key not in non_contiguous_pair_keys:
                    non_contiguous_pair_keys.append(pair_key)
                active_pair_key = pair_key
            elif pair_key != active_pair_key:
                closed_pair_keys.add(active_pair_key)
                if pair_key in closed_pair_keys and pair_key not in non_contiguous_pair_keys:
                    non_contiguous_pair_keys.append(pair_key)
                active_pair_key = pair_key
        pair_counts[pair_key] = pair_counts.get(pair_key, 0) + 1
        role_counts[pair_role] = role_counts.get(pair_role, 0) + 1
        if pair_role == anchor_role:
            anchor_counts[pair_key] = anchor_counts.get(pair_key, 0) + 1

    singleton_pairs = [pair_key for pair_key, count in pair_counts.items() if count == 1]
    missing_anchor_pairs = [pair_key for pair_key in pair_counts if anchor_counts.get(pair_key, 0) == 0]
    duplicate_anchor_pairs = [
        pair_key for pair_key, count in anchor_counts.items() if count > 1
    ]
    closed_singleton_pairs = [
        pair_key for pair_key in singleton_pairs if pair_key in closed_pair_keys
    ]
    closed_missing_anchor_pairs = [
        pair_key for pair_key in missing_anchor_pairs if pair_key in closed_pair_keys
    ]
    pair_sizes = list(pair_counts.values())
    return {
        "sample_bounded": True,
        "sample_row_limit": _DEFAULT_PREFLIGHT_PAIR_ROWS,
        "sample_rows": len(rows),
        "sample_columns": sample_columns,
        "text_column": text_column,
        "pair_key_column": pair_key_column,
        "pair_role_column": pair_role_column,
        "anchor_role": anchor_role,
        "anchor_role_present": anchor_role in role_counts,
        "pair_order": pair_order,
        "pair_count": len(pair_counts),
        "closed_pair_count": len(closed_pair_keys),
        "role_counts": dict(role_counts),
        "pair_size_min": min(pair_sizes) if pair_sizes else 0,
        "pair_size_max": max(pair_sizes) if pair_sizes else 0,
        "singleton_pair_count": len(singleton_pairs),
        "singleton_pairs_preview": singleton_pairs[:10],
        "closed_singleton_pair_count": len(closed_singleton_pairs),
        "closed_singleton_pairs_preview": closed_singleton_pairs[:10],
        "empty_text_rows": empty_text_rows,
        "missing_pair_key_rows": missing_pair_key_rows,
        "missing_pair_role_rows": missing_pair_role_rows,
        "missing_anchor_pair_count": len(missing_anchor_pairs),
        "missing_anchor_pairs_preview": missing_anchor_pairs[:10],
        "closed_missing_anchor_pair_count": len(closed_missing_anchor_pairs),
        "closed_missing_anchor_pairs_preview": closed_missing_anchor_pairs[:10],
        "duplicate_anchor_pair_count": len(duplicate_anchor_pairs),
        "duplicate_anchor_pairs_preview": duplicate_anchor_pairs[:10],
        "non_contiguous_pair_key_count": len(non_contiguous_pair_keys),
        "non_contiguous_pair_keys_preview": non_contiguous_pair_keys[:10],
        "sample_complete": bool(meta.get("sample_complete")) if isinstance(meta, Mapping) else False,
        **({"reader": meta} if meta else {}),
    }


def _preflight_vrt_evidence(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        sample, sample_meta = _read_text_sample(path)
    except Exception as exc:
        return {"warning": "vrt_sample_unavailable", "error": str(exc)}
    segment_tag = str(payload.get("segment_tag") or payload.get("segment-tag") or "text")
    text_tag = str(payload.get("text_tag") or payload.get("text-tag") or "text")
    token_like_lines = 0
    for line in sample.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("<") and not stripped.startswith("</"):
            token_like_lines += 1
    return {
        **sample_meta,
        "segment_tag": segment_tag,
        "text_tag": text_tag,
        "segment_tag_seen": f"<{segment_tag}" in sample,
        "text_tag_seen": f"<{text_tag}" in sample,
        "token_like_lines": token_like_lines,
        "truncated": sample_meta["sample_truncated"],
    }


_DEFAULT_PREFLIGHT_PLAINTEXT_FILES = 10_000
_DEFAULT_PREFLIGHT_ENCODING_FILES = 5
_DEFAULT_PREFLIGHT_ENCODING_BYTES = 4096
_HF_DATASET_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)?")


def _preflight_plaintext_evidence(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded real-structure sample for a plaintext import (no mutation).

    Counts matching files and their total size (capped at
    ``_DEFAULT_PREFLIGHT_PLAINTEXT_FILES``), probes the encoding of the first
    few files, and previews the parent-directory register values the import
    would derive.
    """
    pattern = str(payload.get("pattern") or "*.txt")
    evidence: dict[str, Any] = {
        "pattern": pattern,
        "file_count": 0,
        "total_size_bytes": 0,
        "file_scan_limit": _DEFAULT_PREFLIGHT_PLAINTEXT_FILES,
        "file_scan_truncated": False,
        "registers_preview": [],
        "encoding_sample": [],
        "encoding_utf8_files": 0,
        "encoding_fallback_files": 0,
    }
    try:
        if path.is_file():
            files: Iterable[Path] = [path]
        else:
            files = (p for p in sorted(path.rglob(pattern)) if p.is_file())
        registers: list[str] = []
        sampled = 0
        count = 0
        total = 0
        for fp in files:
            count += 1
            if count > _DEFAULT_PREFLIGHT_PLAINTEXT_FILES:
                evidence["file_scan_truncated"] = True
                count = _DEFAULT_PREFLIGHT_PLAINTEXT_FILES
                break
            try:
                total += int(fp.stat().st_size)
            except OSError:
                continue
            if path.is_dir():
                register = fp.parent.name if fp.parent != path else ""
                if register and register not in registers:
                    registers.append(register)
            if sampled < _DEFAULT_PREFLIGHT_ENCODING_FILES:
                sampled += 1
                try:
                    with fp.open("rb") as fh:
                        raw = fh.read(_DEFAULT_PREFLIGHT_ENCODING_BYTES)
                    if raw[:3] == b"\xef\xbb\xbf":
                        raw = raw[3:]
                    try:
                        raw.decode("utf-8")
                        encoding = "utf-8"
                        evidence["encoding_utf8_files"] += 1
                    except UnicodeDecodeError:
                        encoding = lt("non-utf-8 (Fallback-Erkennung beim Import)", "non-utf-8 (fallback detection during import)")
                        evidence["encoding_fallback_files"] += 1
                    evidence["encoding_sample"].append(
                        {"file": str(fp.name), "encoding": encoding, "sample_bytes": len(raw)}
                    )
                except OSError as exc:
                    evidence["encoding_sample"].append({"file": str(fp.name), "error": str(exc)})
        evidence["file_count"] = count
        evidence["total_size_bytes"] = total
        evidence["registers_preview"] = registers[:10]
        evidence["encoding_sample_limit"] = _DEFAULT_PREFLIGHT_ENCODING_FILES
    except Exception as exc:
        evidence["warning"] = "plaintext_sample_unavailable"
        evidence["error"] = str(exc)
    return evidence


def _preflight_disk_space(
    checks: list[dict[str, Any]],
    evidence: dict[str, Any],
    *,
    input_size: int | None,
    payload: Mapping[str, Any],
) -> None:
    """Disk-space check against the managed corpus volume (shared heuristic)."""
    from candyconc.utils.disk_preflight import check_disk_space

    if input_size is None:
        return
    root_raw = payload.get("__managed_corpus_dir") or payload.get("corpora_dir")
    root = (
        Path(str(root_raw)).expanduser().resolve(strict=False)
        if root_raw
        else corpora_dir()
    )
    result = check_disk_space(
        int(input_size),
        root,
        build_word_faiss=_bool_option(payload.get("build_word_faiss") or payload.get("build-word-faiss")),
    )
    evidence["disk_space"] = result
    status = str(result.get("status") or "unknown")
    check_status = "fail" if status == "fail" else ("pass" if status == "pass" else "warn")
    _preflight_check(
        checks,
        "disk_space",
        lt("Freier Speicher", "Free disk space"),
        check_status,
        result.get("message") or lt("Freier Speicher konnte nicht bewertet werden.", "Free disk space could not be assessed."),
        evidence=result,
    )


def _option_value(payload: Mapping[str, Any], spec: Mapping[str, Any]) -> Any:
    keys = [str(spec.get("key") or "")]
    keys.extend(str(alias) for alias in spec.get("aliases", []) if alias)
    for key in keys:
        if key and key in payload:
            return payload[key]
        dashed = key.replace("_", "-")
        if dashed in payload:
            return payload[dashed]
    return spec.get("default")


def _public_payload_options(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in payload.items()
        if not str(key).startswith("__")
    }


def _is_internal_payload_key(key: object) -> bool:
    return str(key).startswith("__")


def _choice_values(spec: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for choice in spec.get("choices", []):
        if isinstance(choice, Mapping):
            values.add(str(choice.get("value")))
        else:
            values.add(str(choice))
    return values


def _validate_option_value(
    checks: list[dict[str, Any]],
    spec: Mapping[str, Any],
    value: Any,
) -> bool:
    key = str(spec.get("key") or "")
    if not key or _is_missing_option(value):
        return True
    label = spec.get("label") or key
    option_type = str(spec.get("type") or "string")

    if option_type == "choice":
        choices = _choice_values(spec)
        if choices and str(value) not in choices:
            _preflight_check(
                checks,
                f"option:{key}:choice",
                label,
                "fail",
                lt("Option {key} hat keinen erlaubten Wert: {value!r}", "Option {key} has a value that is not allowed: {value!r}").format(key=key, value=value),
                evidence={"allowed": sorted(choices), "value": value},
            )
            return False
    elif option_type == "boolean":
        if not isinstance(value, bool) and str(value).lower() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            _preflight_check(checks, f"option:{key}:type", label, "fail", lt("Option {key} muss boolean sein.", "Option {key} must be a boolean.").format(key=key), evidence={"value": value})
            return False
    elif option_type == "integer":
        try:
            if isinstance(value, bool):
                raise ValueError
            int(str(value))
        except (TypeError, ValueError):
            _preflight_check(checks, f"option:{key}:type", label, "fail", lt("Option {key} muss eine ganze Zahl sein.", "Option {key} must be an integer.").format(key=key), evidence={"value": value})
            return False
    elif option_type == "number":
        try:
            if isinstance(value, bool):
                raise ValueError
            float(str(value))
        except (TypeError, ValueError):
            _preflight_check(checks, f"option:{key}:type", label, "fail", lt("Option {key} muss numerisch sein.", "Option {key} must be numeric.").format(key=key), evidence={"value": value})
            return False
    elif option_type == "string_list":
        if not isinstance(value, (str, list, tuple, set)):
            _preflight_check(checks, f"option:{key}:type", label, "fail", lt("Option {key} muss Text oder Liste sein.", "Option {key} must be text or a list.").format(key=key), evidence={"value": value})
            return False
    return True


#: Python packages each import method needs at run time, with the extra that
#: installs them. spaCy tokenizes every method, even ``blank:<lang>``.
_METHOD_REQUIREMENTS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "parquet": (("spacy", None), ("pyarrow", None)),
    "vrt": (("spacy", None), ("pyarrow", None)),
    "prealigned_parquet": (("spacy", None), ("pyarrow", None)),
    "prealigned_csv": (("spacy", None), ("pyarrow", None)),
    "prealigned_jsonl": (("spacy", None), ("pyarrow", None)),
    "plaintext": (("spacy", None), ("pyarrow", None)),
    "csv": (("spacy", None), ("pyarrow", None)),
    "jsonl": (("spacy", None), ("pyarrow", None)),
    "hf": (("spacy", None), ("pyarrow", None), ("datasets", "hf")),
}


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _builder_availability(method: str) -> dict[str, Any]:
    """Report whether ``method`` can run in THIS installation.

    Checks what the import job actually executes: the builder implementation in
    :mod:`candyconc.ingest`, the Python packages the method needs (``datasets``
    for Hugging Face comes with the ``hf`` extra) and the file the job starts.
    """
    spec = import_builder_spec(method)
    if spec is None:
        return {"status": "unavailable", "reason": "unknown_method"}
    from candyconc.builders import _runner as _builders_runner

    base: dict[str, Any] = {
        "script": spec.script_name,
        "subcommand": list(spec.subcommand),
    }
    module = _builders_runner.IMPLEMENTATION_MODULES.get(spec.script_name)
    if module is None or not _module_available(module):
        return {
            **base,
            "status": "unavailable",
            "reason": f"The builder module for {spec.script_name} is not installed.",
        }
    missing = [
        (package, extra)
        for package, extra in _METHOD_REQUIREMENTS.get(normalize_import_method(method), ())
        if not _module_available(package)
    ]
    if missing:
        names = ", ".join(package for package, _extra in missing)
        extras = sorted({extra for _package, extra in missing if extra})
        remedy = (
            f"Install it with: pip install 'candyconc[{','.join(extras)}]'"
            if extras
            else "Reinstall candyconc with its dependencies."
        )
        return {
            **base,
            "status": "unavailable",
            "reason": f"Missing Python package: {names}. {remedy}",
            "missing_packages": [package for package, _extra in missing],
            "extras": extras,
        }
    try:
        script = find_builder_script(spec.script_name, start=__file__)
    except (FileNotFoundError, ValueError) as exc:
        return {**base, "status": "unavailable", "reason": str(exc)}
    return {**base, "status": "available", "script_path": str(script)}


def _is_missing_option(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _bool_option(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _preflight_columns_for_method(
    method: str,
    path: Path,
    payload: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    if method in {"plaintext", "hf"}:
        return [], None
    suffix = path.suffix.lower()
    if method in {"parquet", "prealigned_parquet"} or suffix == ".parquet":
        return _preflight_parquet_columns(path)
    if method in {"prealigned_csv", "csv"} or suffix in {".csv", ".tsv"}:
        return _preflight_csv_columns(path, payload.get("delimiter"))
    if method in {"prealigned_jsonl", "jsonl"} or suffix in {".jsonl", ".ndjson"}:
        return _preflight_jsonl_columns(path)
    return [], None


def preflight_import_method(
    method: str,
    input_path: str | os.PathLike[str] | None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect import inputs cheaply without mutating files or starting builders."""
    payload = dict(payload or {})
    method_key = normalize_import_method(method)
    descriptor = _descriptor_for_method(method_key)
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {
        "path": str(input_path or ""),
        "exists": False,
        "is_file": False,
        "is_dir": False,
        "size_bytes": None,
        "suffix": "",
        "columns": [],
        "method_contract": descriptor,
    }
    if descriptor is None:
        _preflight_check(
            checks,
            "method_supported",
            lt("Importmethode", "Import method"),
            "fail",
            lt("Importmethode wird vom Backend nicht unterstützt: {method!r}", "The server does not support this import method: {method!r}").format(method=method),
            evidence={"method": method},
        )
        return _finalize_preflight(method_key, input_path, payload, checks, evidence)

    _preflight_check(
        checks,
        "method_supported",
        lt("Importmethode", "Import method"),
        "pass",
        lt("Importmethode ist verfügbar: {label}", "Import method is available: {label}").format(label=descriptor.get("label") or method_key),
    )
    availability = descriptor.get("availability") if isinstance(descriptor.get("availability"), Mapping) else {}
    if availability.get("status") != "available":
        _preflight_check(
            checks,
            "builder_available",
            lt("Builder-Verfügbarkeit", "Builder availability"),
            "fail",
            lt("Der Builder für diese Importmethode ist in dieser Installation nicht verfügbar.", "The builder for this import method is not available in this installation."),
            evidence=availability,
        )
    else:
        _preflight_check(
            checks,
            "builder_available",
            lt("Builder-Verfügbarkeit", "Builder availability"),
            "pass",
            lt("Der Builder für diese Importmethode ist auflösbar.", "The builder for this import method can be resolved."),
            evidence=availability,
        )

    # The builder loads the pipeline in THIS Python environment. A missing
    # pipeline used to pass the preflight and fail only inside the job.
    from candyconc.ingest import pipelines as _pipelines

    try:
        spacy_model = _import_pipeline(payload)
    except ValueError as exc:
        spacy_model = ""
        _preflight_check(
            checks,
            "spacy_model",
            "spaCy pipeline",
            "fail",
            str(exc),
            evidence={
                "language": payload.get("language"),
                "spacy_model": payload.get("spacy_model") or payload.get("spacy-model"),
            },
        )
    if not spacy_model:
        pass
    elif method_key == "vrt" and (payload.get("annotation_mode") or payload.get("annotation-mode")) == "adopt":
        _preflight_check(
            checks, "spacy_model", lt("spaCy-Pipeline", "spaCy pipeline"), "pass",
            lt("VRT-Goldannotationen werden ohne spaCy-Pipeline indexiert.", "VRT gold annotations are indexed without a spaCy pipeline."),
        )
    elif _pipelines.pipeline_installed(spacy_model):
        _preflight_check(
            checks,
            "spacy_model",
            lt("spaCy-Pipeline", "spaCy pipeline"),
            "pass",
            lt("Die spaCy-Pipeline {spacy_model} ist verfügbar.", "The spaCy pipeline {spacy_model} is available.").format(spacy_model=spacy_model),
            evidence={"spacy_model": spacy_model},
        )
    else:
        _preflight_check(
            checks,
            "spacy_model",
            lt("spaCy-Pipeline", "spaCy pipeline"),
            "fail",
            _pipelines.missing_text(spacy_model),
            evidence={
                "spacy_model": spacy_model,
                "install_command": f"candy pipeline {spacy_model}",
                "blank_alternative": _pipelines.blank_alternative(spacy_model),
            },
        )

    path_text = _path_value(input_path)
    if path_text is None:
        _preflight_check(checks, "input_path", lt("Serverpfad", "Server path"), "fail", lt("Serverpfad fehlt.", "Server path is missing."))
        return _finalize_preflight(method_key, input_path, payload, checks, evidence)

    if method_key == "hf":
        # Eine HF-Dataset-ID ist KEIN Serverpfad: der Preflight validiert nur
        # den Descriptor (Dataset-ID, Optionen, Zielname) und bleibt ehrlich
        # OHNE Netzzugriff — Existenz, Spalten und Splits prüft erst der Import.
        dataset_id = path_text.strip()
        path = Path(dataset_id)
        evidence["path"] = dataset_id
        evidence["suffix"] = ""
        evidence["hf"] = {
            "dataset": dataset_id,
            "network_access": False,
            "descriptor_only": True,
        }
        if _HF_DATASET_ID_RE.fullmatch(dataset_id):
            _preflight_check(
                checks,
                "hf_dataset_id",
                lt("Dataset-ID", "Dataset ID"),
                "pass",
                lt("Dataset-ID ist syntaktisch gültig: {dataset_id}", "Dataset ID is syntactically valid: {dataset_id}").format(dataset_id=dataset_id),
                evidence={"dataset": dataset_id},
            )
        else:
            _preflight_check(
                checks,
                "hf_dataset_id",
                lt("Dataset-ID", "Dataset ID"),
                "fail",
                lt(
                    "Keine gültige HuggingFace-Dataset-ID: {dataset_id!r} "
                    "(erwartet 'name' oder 'organisation/name').",
                    "Not a valid Hugging Face dataset ID: {dataset_id!r} "
                    "(expected 'name' or 'organisation/name').",
                ).format(dataset_id=dataset_id),
                evidence={"dataset": dataset_id},
            )
        _preflight_check(
            checks,
            "hf_descriptor_only",
            lt("Offline-Preflight", "Offline preflight check"),
            "warn",
            lt(
                "Preflight validiert nur den Descriptor ohne Netzzugriff: Existenz, "
                "Spalten, Splits und Datenumfang des Datasets werden erst beim "
                "Import geprüft. trust_remote_code bleibt hart deaktiviert.",
                "The preflight check validates only the descriptor, without network access: "
                "the existence, columns, splits and size of the dataset are checked "
                "during the import. trust_remote_code is always disabled.",
            ),
            evidence={"network_access": False, "trust_remote_code": False},
        )
    else:
        path = Path(path_text).expanduser().resolve(strict=False)
        evidence["path"] = str(path)
        evidence["suffix"] = path.suffix.lower()
        if not path.exists():
            _preflight_check(
                checks,
                "input_exists",
                lt("Serverpfad", "Server path"),
                "fail",
                lt("Input existiert nicht: {path}", "Input does not exist: {path}").format(path=path),
                evidence={"path": str(path)},
            )
            return _finalize_preflight(method_key, path, payload, checks, evidence)

        evidence["exists"] = True
        evidence["is_file"] = path.is_file()
        evidence["is_dir"] = path.is_dir()
        try:
            evidence["size_bytes"] = path.stat().st_size
        except OSError:
            evidence["size_bytes"] = None

        input_spec = descriptor.get("input") if isinstance(descriptor.get("input"), Mapping) else {}
        accepts_directories = bool(input_spec.get("accepts_directories"))
        if path.is_dir() and not accepts_directories:
            _preflight_check(checks, "input_kind", lt("Input-Typ", "Input type"), "fail", lt("Diese Importmethode erwartet eine Datei, kein Verzeichnis.", "This import method expects a file, not a directory."))
        elif path.is_file() or (path.is_dir() and accepts_directories):
            _preflight_check(checks, "input_kind", lt("Input-Typ", "Input type"), "pass", lt("Input-Typ passt zur Importmethode.", "Input type matches the import method."))
        else:
            _preflight_check(checks, "input_kind", lt("Input-Typ", "Input type"), "fail", lt("Input ist weder lesbare Datei noch akzeptiertes Verzeichnis.", "Input is neither a readable file nor an accepted directory."))

        extensions = [str(item).lower() for item in input_spec.get("extensions", []) if item]
        if extensions and path.is_file() and evidence["suffix"] not in extensions:
            _preflight_check(
                checks,
                "input_extension",
                lt("Dateiendung", "File extension"),
                "fail",
                lt("Dateiendung {suffix} passt nicht zu {extensions}.", "File extension {suffix} does not match {extensions}.").format(suffix=evidence["suffix"] or lt("<keine>", "<none>"), extensions=", ".join(extensions)),
                evidence={"extensions": extensions, "suffix": evidence["suffix"]},
            )
        else:
            _preflight_check(checks, "input_extension", lt("Dateiendung", "File extension"), "pass", lt("Dateiendung passt zum Import-Contract.", "File extension matches the import contract."))

    raw_target_name = (
        payload.get("target_name")
        or payload.get("targetName")
        or payload.get("target")
    )
    if raw_target_name is not None or payload.get("__managed_corpus_dir"):
        try:
            target_name = _safe_target_name(raw_target_name or path.stem)
            evidence["target_name"] = target_name
            managed_root_raw = payload.get("__managed_corpus_dir") or payload.get("corpora_dir")
            if managed_root_raw:
                managed_root = Path(str(managed_root_raw)).expanduser().resolve(strict=False)
                target_path = (managed_root / target_name).resolve(strict=False)
                evidence["managed_corpus_dir"] = str(managed_root)
                evidence["target_path"] = str(target_path)
                if not target_path.is_relative_to(managed_root):
                    _preflight_check(
                        checks,
                        "target_path",
                        lt("Zielpfad", "Target path"),
                        "fail",
                        lt("target_path liegt außerhalb des verwalteten Korpusverzeichnisses.", "target_path is outside the managed corpus directory."),
                        evidence={"target_path": str(target_path), "managed_corpus_dir": str(managed_root)},
                    )
                elif target_path.exists():
                    _preflight_check(
                        checks,
                        "target_exists",
                        lt("Zielkorpus", "Target corpus"),
                        "fail",
                        lt("Zielkorpus existiert bereits: {target_path}", "Target corpus already exists: {target_path}").format(target_path=target_path),
                        evidence={"target_path": str(target_path)},
                    )
                else:
                    _preflight_check(
                        checks,
                        "target_available",
                        lt("Zielkorpus", "Target corpus"),
                        "pass",
                        lt("Zielname ist sicher und im verwalteten Korpusverzeichnis noch frei.", "Target name is safe and still free in the managed corpus directory."),
                        evidence={"target_path": str(target_path)},
                    )
            else:
                _preflight_check(checks, "target_name", lt("Zielname", "Target name"), "pass", lt("Zielname ist syntaktisch sicher.", "Target name is syntactically safe."))
        except ValueError as exc:
            _preflight_check(
                checks,
                "target_name",
                lt("Zielname", "Target name"),
                "fail",
                exception_text(exc),
                evidence={"target_name": str(raw_target_name or "")},
            )

    for spec in descriptor.get("option_specs", []):
        if not isinstance(spec, Mapping):
            continue
        value = _option_value(payload, spec)
        if spec.get("required") and _is_missing_option(value):
            _preflight_check(
                checks,
                f"option:{spec.get('key')}",
                spec.get("label") or str(spec.get("key")),
                "fail",
                lt("Erforderliche Option fehlt: {key}", "Required option is missing: {key}").format(key=spec.get("key")),
            )
            continue
        _validate_option_value(checks, spec, value)

    if method_key == "vrt" and _bool_option(payload.get("inspect") or payload.get("inspect-only")):
        _preflight_check(
            checks,
            "vrt_inspect_mode",
            lt("VRT-Inspect", "VRT inspect"),
            "fail",
            lt("inspect=true ist ein Diagnostikmodus ohne Indexbau und darf nicht als Importjob publiziert werden.", "inspect=true is a diagnostic mode without an index build and must not be published as an import job."),
            evidence={"inspect": True},
        )

    columns, column_meta = _preflight_columns_for_method(method_key, path, payload)
    evidence["columns"] = columns
    if column_meta:
        evidence["column_sample"] = column_meta
    if method_key == "vrt":
        vrt = _preflight_vrt_evidence(path, payload)
        evidence["vrt"] = vrt
        if vrt.get("warning"):
            _preflight_check(checks, "vrt_sample", lt("VRT-Sample", "VRT sample"), "warn", lt("VRT-Sample konnte nicht vollständig geprüft werden.", "The VRT sample could not be checked completely."), evidence=vrt)
        elif not vrt.get("segment_tag_seen") and not vrt.get("text_tag_seen"):
            _preflight_check(
                checks,
                "vrt_tags",
                lt("VRT-Tags", "VRT tags"),
                "warn",
                lt("Im bounded Sample wurde kein konfigurierter Text-/Segment-Tag gefunden.", "No configured text or segment tag was found in the bounded sample."),
                evidence=vrt,
            )
        else:
            _preflight_check(checks, "vrt_tags", lt("VRT-Tags", "VRT tags"), "pass", lt("Konfigurierte VRT-Tags erscheinen im bounded Sample.", "Configured VRT tags appear in the bounded sample."), evidence=vrt)
    elif path.is_file():
        if columns:
            _preflight_check(
                checks,
                "schema_read",
                lt("Spaltenprüfung", "Column check"),
                "pass",
                lt("{count} Spalten/Felder wurden erkannt.", "{count} columns or fields were detected.").format(count=len(columns)),
                evidence={"columns": columns[:50], "column_count": len(columns)},
            )
        elif column_meta and column_meta.get("warning"):
            _preflight_check(
                checks,
                "schema_read",
                lt("Spaltenprüfung", "Column check"),
                "warn",
                lt("Spalten/Felder konnten im bounded Preflight nicht gelesen werden.", "Columns or fields could not be read in the bounded preflight check."),
                evidence=column_meta,
            )

    if method_key == "plaintext":
        plaintext_sample = _preflight_plaintext_evidence(path, payload)
        evidence["plaintext"] = plaintext_sample
        if plaintext_sample.get("warning"):
            _preflight_check(
                checks,
                "plaintext_sample",
                lt("Plaintext-Sample", "Plain text sample"),
                "warn",
                lt("Plaintext-Struktur konnte nicht vollständig gelesen werden.", "The plain text structure could not be read completely."),
                evidence=plaintext_sample,
            )
        elif int(plaintext_sample.get("file_count") or 0) == 0:
            _preflight_check(
                checks,
                "plaintext_files",
                lt("Textdateien", "Text files"),
                "fail",
                lt(
                    "Keine Datei passt zum Muster {pattern!r} "
                    "unter {path}. Der Build würde ohne Dokumente scheitern.",
                    "No file matches the pattern {pattern!r} "
                    "under {path}. The build would fail without documents.",
                ).format(pattern=plaintext_sample.get("pattern"), path=path),
                evidence=plaintext_sample,
            )
        else:
            _preflight_check(
                checks,
                "plaintext_files",
                lt("Textdateien", "Text files"),
                "pass",
                lt(
                    "{file_count} Datei(en), "
                    "{total_size_bytes} Bytes im bounded Scan; "
                    "Encoding-Stichprobe: {utf8_files} UTF-8, "
                    "{fallback_files} mit Fallback-Dekodierung.",
                    "{file_count} file(s), "
                    "{total_size_bytes} bytes in the bounded scan. "
                    "Encoding sample: {utf8_files} UTF-8, "
                    "{fallback_files} with fallback decoding.",
                ).format(
                    file_count=plaintext_sample["file_count"],
                    total_size_bytes=plaintext_sample["total_size_bytes"],
                    utf8_files=plaintext_sample["encoding_utf8_files"],
                    fallback_files=plaintext_sample["encoding_fallback_files"],
                ),
                evidence=plaintext_sample,
            )

    option_specs = {
        str(spec.get("key")): spec
        for spec in descriptor.get("option_specs", [])
        if isinstance(spec, Mapping) and spec.get("key")
    }
    if columns:
        column_set = set(columns)
        parquet_text_mapping: dict[str, Any] | None = None
        for column in descriptor.get("expected_columns", []):
            if not isinstance(column, Mapping):
                continue
            configured_by = str(column.get("configured_by") or "")
            default_key = str(column.get("key") or "")
            expected = default_key
            if configured_by and configured_by in option_specs:
                expected = str(_option_value(payload, option_specs[configured_by]) or default_key)
            required = bool(column.get("required"))
            if expected in column_set:
                _preflight_check(checks, f"column:{expected}", column.get("label") or expected, "pass", lt("Spalte/Feld vorhanden: {expected}", "Column or field present: {expected}").format(expected=expected))
            elif (
                required
                and configured_by == "text_column"
                and method_key in _TEXT_CANDIDATE_COLUMNS_BY_METHOD
            ):
                parquet_text_mapping = _text_column_mapping_evidence(
                    columns,
                    expected_column=expected,
                    candidate_columns=_TEXT_CANDIDATE_COLUMNS_BY_METHOD[method_key],
                )
                if parquet_text_mapping:
                    evidence.setdefault("column_mapping_suggestions", []).append(parquet_text_mapping)
                candidates = (
                    ", ".join(parquet_text_mapping["candidate_columns"])
                    if parquet_text_mapping
                    else lt("keine", "none")
                )
                _preflight_check(
                    checks,
                    f"column:{expected}",
                    column.get("label") or expected,
                    "fail",
                    lt(
                        "Erforderliche Textspalte fehlt: {expected}. "
                        "Gefundene Textkandidat(en): {candidates}. "
                        "Setze text_column auf die passende Spalte, wenn sie den Dokumenttext enthält.",
                        "Required text column is missing: {expected}. "
                        "Text candidate(s) found: {candidates}. "
                        "Set text_column to the matching column if it contains the document text.",
                    ).format(expected=expected, candidates=candidates),
                    evidence=parquet_text_mapping or {},
                )
            elif required:
                _preflight_check(checks, f"column:{expected}", column.get("label") or expected, "fail", lt("Erforderliche Spalte/Feld fehlt: {expected}", "Required column or field is missing: {expected}").format(expected=expected))

    reject_policy = str(payload.get("reject_policy") or payload.get("reject-policy") or "")
    if method_key.startswith("prealigned"):
        pair_sample = _preflight_prealigned_pairing_evidence(method_key, path, payload, columns)
        evidence["prealigned_pairing_sample"] = pair_sample
        # A configured anchor_role absent from EVERY sample row is a deterministic
        # build failure: the builder rejects each group with invalid_anchor_count and
        # emits no documents (RuntimeError "Keine Dokumente im Input", returncode 1).
        # Block up front instead of warning-then-crash, regardless of reject_policy.
        if (
            pair_sample.get("pair_count")
            and not pair_sample.get("anchor_role_present", True)
        ):
            _preflight_check(
                checks,
                "prealigned_anchor_role",
                lt("Ankerrolle", "Anchor role"),
                "fail",
                lt(
                    "Konfigurierte Ankerrolle '{anchor_role}' fehlt in "
                    "jeder Sample-Zeile (gesehene Rollen: "
                    "{roles}). "
                    "Der Build würde scheitern (kein Dokument). "
                    "anchor_role auf eine vorhandene Rolle setzen.",
                    "The configured anchor role '{anchor_role}' is missing in "
                    "every sample row (roles seen: "
                    "{roles}). "
                    "The build would fail (no document). "
                    "Set anchor_role to a role that is present.",
                ).format(
                    anchor_role=pair_sample.get("anchor_role"),
                    roles=", ".join(pair_sample.get("role_counts", {})) or lt("keine", "none"),
                ),
                evidence={
                    "anchor_role": pair_sample.get("anchor_role"),
                    "role_counts": pair_sample.get("role_counts"),
                },
            )
        sample_warnings: list[str] = []
        hard_pairing_failures: list[str] = []
        if pair_sample.get("reader", {}).get("warning"):
            sample_warnings.append(lt("Pairing-Sample konnte nicht gelesen werden.", "The pairing sample could not be read."))
        if pair_sample.get("sample_rows", 0) == 0:
            sample_warnings.append(lt("Im bounded Sample wurden keine Datenzeilen gelesen.", "No data rows were read in the bounded sample."))
            hard_pairing_failures.append(lt("keine Datenzeilen im Sample", "no data rows in the sample"))
        if pair_sample.get("empty_text_rows"):
            message = lt("{count} Sample-Zeile(n) ohne Text.", "{count} sample row(s) without text.").format(count=pair_sample["empty_text_rows"])
            sample_warnings.append(message)
            hard_pairing_failures.append(message)
        if pair_sample.get("missing_pair_key_rows"):
            message = lt("{count} Sample-Zeile(n) ohne Pair-Key.", "{count} sample row(s) without a pair key.").format(count=pair_sample["missing_pair_key_rows"])
            sample_warnings.append(message)
            hard_pairing_failures.append(message)
        if pair_sample.get("missing_pair_role_rows"):
            message = lt("{count} Sample-Zeile(n) ohne Pair-Role.", "{count} sample row(s) without a pair role.").format(count=pair_sample["missing_pair_role_rows"])
            sample_warnings.append(message)
            hard_pairing_failures.append(message)
        if pair_sample.get("singleton_pair_count"):
            sample_warnings.append(
                lt("{count} Singleton-Pair(s) im Sample.", "{count} singleton pair(s) in the sample.").format(count=pair_sample["singleton_pair_count"])
            )
            if pair_sample.get("sample_complete"):
                hard_pairing_failures.append(lt("vollständiges Sample enthält Singleton-Pair(s)", "complete sample contains singleton pair(s)"))
            elif pair_sample.get("closed_singleton_pair_count"):
                hard_pairing_failures.append(
                    lt("grouped Sample enthält bereits geschlossene Singleton-Pair(s)", "grouped sample already contains closed singleton pair(s)")
                )
        if pair_sample.get("missing_anchor_pair_count"):
            sample_warnings.append(
                lt("{count} Pair(s) ohne Ankerrolle im Sample.", "{count} pair(s) without an anchor role in the sample.").format(count=pair_sample["missing_anchor_pair_count"])
            )
            if pair_sample.get("sample_complete"):
                hard_pairing_failures.append(lt("vollständiges Sample enthält Pair(s) ohne Ankerrolle", "complete sample contains pair(s) without an anchor role"))
            elif pair_sample.get("closed_missing_anchor_pair_count"):
                hard_pairing_failures.append(
                    lt("grouped Sample enthält bereits geschlossene Pair(s) ohne Ankerrolle", "grouped sample already contains closed pair(s) without an anchor role")
                )
        if pair_sample.get("duplicate_anchor_pair_count"):
            message = lt("{count} Pair(s) mit mehrfacher Ankerrolle im Sample.", "{count} pair(s) with more than one anchor role in the sample.").format(count=pair_sample["duplicate_anchor_pair_count"])
            sample_warnings.append(message)
            hard_pairing_failures.append(message)
        if pair_sample.get("non_contiguous_pair_key_count"):
            message = lt("{count} nicht zusammenhängende Pair-Key(s) bei pair_order=grouped im Sample.", "{count} non-contiguous pair key(s) with pair_order=grouped in the sample.").format(count=pair_sample["non_contiguous_pair_key_count"])
            sample_warnings.append(message)
            hard_pairing_failures.append(message)
        if sample_warnings:
            fail_fast_blocks = reject_policy == "fail_fast" and hard_pairing_failures
            _preflight_check(
                checks,
                "prealigned_pairing_sample",
                lt("Pairing-Sample", "Pairing sample"),
                "fail" if fail_fast_blocks else "warn",
                (
                    lt(
                        "Reject-Policy fail_fast würde sample-belegte Pairingfehler blockieren: {errors}",
                        "Reject policy fail_fast would block pairing errors shown in the sample: {errors}",
                    ).format(errors=join_texts(" ", hard_pairing_failures))
                    if fail_fast_blocks
                    else lt(
                        "Bounded Pairing-Sample braucht Prüfung: {warnings}",
                        "The bounded pairing sample needs review: {warnings}",
                    ).format(warnings=join_texts(" ", sample_warnings))
                ),
                evidence=pair_sample,
            )
        else:
            _preflight_check(
                checks,
                "prealigned_pairing_sample",
                lt("Pairing-Sample", "Pairing sample"),
                "pass",
                lt("Bounded Pairing-Sample zeigt Pair-Key, Pair-Role und Ankerrolle plausibel.", "The bounded pairing sample shows plausible pair keys, pair roles and anchor roles."),
                evidence=pair_sample,
            )
        if not reject_policy or reject_policy == "collect":
            _preflight_check(
                checks,
                "reject_policy",
                lt("Reject-Policy", "Reject policy"),
                "warn",
                lt("Reject-Policy collect kann den Import trotz verworfener Zeilen abschließen; Reject-Report prüfen.", "Reject policy collect can complete the import despite rejected rows. Check the rejected rows report."),
            )
        else:
            _preflight_check(checks, "reject_policy", lt("Reject-Policy", "Reject policy"), "pass", lt("Reject-Policy: {reject_policy}", "Reject policy: {reject_policy}").format(reject_policy=reject_policy))
        pair_order = str(payload.get("pair_order") or payload.get("pair-order") or "unsorted")
        if pair_order == "unsorted":
            _preflight_check(
                checks,
                "pair_order",
                lt("Pair-Reihenfolge", "Pair order"),
                "warn",
                lt("pair_order=unsorted ist sicher, kann bei großen Dateien aber mehr Arbeitsspeicher benötigen.", "pair_order=unsorted is safe but can need more memory for large files."),
            )

    # Disk-Space-Preflight (geteilte Faktor-Heuristik, env-tunebar): volle
    # Platte blockiert VOR dem Build. Für HF ist der Datenumfang ohne
    # Netzzugriff unbekannt — der Offline-Preflight-Check dokumentiert das.
    if method_key != "hf":
        if method_key == "plaintext" and evidence.get("is_dir"):
            plaintext_sample = evidence.get("plaintext")
            raw_size = (
                plaintext_sample.get("total_size_bytes")
                if isinstance(plaintext_sample, Mapping)
                else None
            )
        else:
            raw_size = evidence.get("size_bytes")
        _preflight_disk_space(
            checks,
            evidence,
            input_size=raw_size if isinstance(raw_size, int) else None,
            payload=payload,
        )

    allowed_payload_keys = {
        "method", "importMethod", "input", "path", "input_path", "inputPath",
        "target", "target_name", "targetName", "target_path", "staging_path",
        "activate", "activate_on_success", "activateOnSuccess",
    }
    for spec in descriptor.get("option_specs", []):
        if isinstance(spec, Mapping) and spec.get("key"):
            key = str(spec["key"])
            allowed_payload_keys.add(key)
            allowed_payload_keys.add(key.replace("_", "-"))
            allowed_payload_keys.update(str(alias) for alias in spec.get("aliases", []) if alias)
    unknown = sorted(
        key
        for key in payload
        if key not in allowed_payload_keys and not _is_internal_payload_key(key)
    )
    if unknown:
        _preflight_check(
            checks,
            "unknown_options",
            lt("Expertenoptionen", "Expert options"),
            "warn",
            lt("Payload enthält Optionen außerhalb des Import-Contracts.", "The payload contains options outside the import contract."),
            evidence={"unknown_options": unknown},
        )

    return _finalize_preflight(method_key, path, payload, checks, evidence)


def _finalize_preflight(
    method: str,
    input_path: str | os.PathLike[str] | None,
    payload: Mapping[str, Any],
    checks: list[dict[str, Any]],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    errors = [check["message"] for check in checks if check.get("severity") == "error"]
    warnings = [check["message"] for check in checks if check.get("severity") == "warning"]
    status = "error" if errors else "warning" if warnings else "pass"
    return {
        "schema_version": "corpus-import-preflight-v1",
        "method": method,
        "input_path": str(input_path or ""),
        "status": status,
        "ok": not errors,
        "blocking": bool(errors),
        "max_severity": "error" if errors else "warning" if warnings else "info",
        "summary": (
            lt("Preflight blockiert den Import.", "The preflight check blocks the import.")
            if errors
            else lt("Preflight mit Warnungen abgeschlossen.", "Preflight check completed with warnings.")
            if warnings
            else lt("Preflight erfolgreich.", "Preflight check passed.")
        ),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "evidence": dict(evidence),
        "normalized_payload": {
            "method": method,
            "input_path": str(input_path or ""),
            "options": _public_payload_options(payload),
        },
    }


def build_import_command(
    job: ImportJob,
    *,
    script_start: str | os.PathLike[str] | None = None,
) -> list[str]:
    spec = import_builder_spec(job.method)
    if spec is None:
        raise ValueError(lt("Import-Methode nicht unterstützt: {method}", "Import method not supported: {method}").format(method=job.method))
    script = find_builder_script(spec.script_name, start=script_start or __file__)
    cmd = [
        sys.executable,
        str(script),
        *spec.subcommand,
        "--input",
        job.input,
        "--output",
        job.output_dir,
    ]
    for option in iter_method_options(job.method, job.payload):
        cmd.extend(option)
    return cmd


def _report_paths(dirs: Iterable[str | os.PathLike[str] | None]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for raw_dir in dirs:
        if raw_dir is None:
            continue
        directory = Path(raw_dir).expanduser().resolve(strict=False)
        if not directory.is_dir():
            continue
        for name in _REPORT_NAMES:
            path = directory / name
            key = str(path)
            if path.is_file() and key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


def load_reports_from_dirs(
    dirs: Iterable[str | os.PathLike[str] | None],
    *,
    max_bytes: int = _DEFAULT_REPORT_MAX_BYTES,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for path in _report_paths(dirs):
        key = path.name
        if key in reports:
            key = f"{path.parent.name}/{path.name}"
        try:
            size = path.stat().st_size
            if max_bytes >= 0 and size > max_bytes:
                reports[key] = {
                    "path": str(path),
                    "bytes": size,
                    "truncated": True,
                    "error": "report_size_exceeds_limit",
                }
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            data: Any
            if path.suffix.lower() == ".json":
                data = json.loads(raw)
                if path.name == MANIFEST_FILENAME:
                    data = normalize_manifest_payload(data)
            else:
                data = raw
            reports[key] = {"path": str(path), "bytes": size, "data": data}
        except Exception as exc:
            reports[key] = {"path": str(path), "error": str(exc)}
    return reports


def _job_readiness(job: ImportJob) -> str:
    if job.status == "succeeded":
        return "partial_input" if job.partial_input else "complete"
    if job.status == "failed":
        return "failed"
    if job.status == "cancelled":
        return "cancelled"
    return "pending"


class ImportJobService:
    def __init__(
        self,
        *,
        max_jobs: int = _DEFAULT_JOB_LIMIT,
        tail_max_bytes: int | None = None,
        report_max_bytes: int | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = _now,
    ) -> None:
        self.max_jobs = max_jobs
        self.tail_max_bytes = (
            _env_int("CANDYCONC_IMPORT_TAIL_MAX_BYTES", _DEFAULT_TAIL_MAX_BYTES)
            if tail_max_bytes is None
            else tail_max_bytes
        )
        self.report_max_bytes = (
            _env_int("CANDYCONC_IMPORT_REPORT_MAX_BYTES", _DEFAULT_REPORT_MAX_BYTES)
            if report_max_bytes is None
            else report_max_bytes
        )
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock
        self._jobs: OrderedDict[str, ImportJob] = OrderedDict()
        self._lock = threading.RLock()

    def create(
        self,
        method: str,
        payload: Mapping[str, Any] | None = None,
        *,
        target: str | os.PathLike[str] | None = None,
        staging: str | os.PathLike[str] | None = None,
        activate: bool | None = None,
        job_id: str | None = None,
    ) -> ImportJob:
        fields = _coerce_job_fields(
            method,
            payload,
            target=target,
            staging=staging,
            activate=activate,
        )
        now = self._clock()
        job = ImportJob(
            job_id=job_id or self._id_factory(),
            created_at=now,
            updated_at=now,
            stdout=BoundedTextTail(self.tail_max_bytes),
            stderr=BoundedTextTail(self.tail_max_bytes),
            **fields,
        )
        with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(lt("Importjob existiert bereits: {job_id}", "Import job already exists: {job_id}").format(job_id=job.job_id))
            self._jobs[job.job_id] = job
            self._jobs.move_to_end(job.job_id)
            self._evict_if_needed()
        return job

    def get(self, job_id: str) -> ImportJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            self._jobs.move_to_end(job_id)
            return job

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._snapshot_unlocked(job, include_reports=False) for job in self._jobs.values()]

    def snapshot(self, job_id: str, *, include_reports: bool = False) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            return self._snapshot_unlocked(job, include_reports=include_reports)

    def load_reports(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            dirs = (job.staging, job.target)
        return load_reports_from_dirs(dirs, max_bytes=self.report_max_bytes)

    def start(
        self,
        job_id: str,
        *,
        popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
        activation_callback: Callable[[ImportJob], None] | None = None,
        script_start: str | os.PathLike[str] | None = None,
    ) -> ImportJob:
        with self._lock:
            job = self.get(job_id)
            if job.status != "queued":
                raise RuntimeError(lt("Importjob kann nicht gestartet werden: {status}", "Import job cannot be started: {status}").format(status=job.status))
            worker = threading.Thread(
                target=self._run_job,
                args=(job_id, popen_factory, activation_callback, script_start),
                name=f"candyconc-import-{job_id[:8]}",
                daemon=True,
            )
            job.worker = worker
            self._set_status_unlocked(job, "running", 1, "starting", "starting")
            worker.start()
            return job

    def cancel(self, job_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            if job.status in _TERMINAL_STATUSES:
                return self._snapshot_unlocked(job, include_reports=False)
            if job.finalization_started:
                # The outcome is being written or the staged corpus is being
                # published.  This is deliberately a no-op: a late cancellation
                # must never turn a published corpus into a supposedly cancelled
                # import.
                return self._snapshot_unlocked(job, include_reports=False)
            job.cancel_requested = True
            proc = job.process
            self._set_status_unlocked(job, "cancelled", job.progress, "cancelled", reason)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        with self._lock:
            return self._snapshot_unlocked(job, include_reports=False)

    def clear_terminal(self) -> int:
        with self._lock:
            removed = 0
            for job_id, job in list(self._jobs.items()):
                if job.status in _TERMINAL_STATUSES:
                    self._jobs.pop(job_id, None)
                    removed += 1
            return removed

    def _evict_if_needed(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        for job_id, job in list(self._jobs.items()):
            if job.status in _TERMINAL_STATUSES:
                self._jobs.pop(job_id, None)
                if len(self._jobs) <= self.max_jobs:
                    return
        raise RuntimeError(lt("Zu viele laufende Importjobs.", "Too many running import jobs."))

    def _set_status_unlocked(
        self,
        job: ImportJob,
        status: ImportJobStatus,
        progress: int,
        stage: str,
        message: str,
    ) -> None:
        now = self._clock()
        job.status = status
        job.progress = int(max(0, min(100, progress)))
        job.stage = str(stage)
        job.message = message if isinstance(message, LocalizedText) else str(message)
        job.updated_at = now
        if status == "running" and job.started_at is None:
            job.started_at = now
        if status in _TERMINAL_STATUSES and job.finished_at is None:
            job.finished_at = now

    def _snapshot_unlocked(self, job: ImportJob, *, include_reports: bool) -> dict[str, Any]:
        process = job.process
        data: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "stage": job.stage,
            "message": job.message,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "method": job.method,
            "input": job.input,
            "target": job.target,
            "staging": job.staging,
            "activate": job.activate,
            "output_dir": job.output_dir,
            "command": job.command,
            "returncode": job.returncode,
            "error": job.error,
            "cancel_requested": job.cancel_requested,
            "finalization_started": job.finalization_started,
            "cancellable": job.status not in _TERMINAL_STATUSES and not job.finalization_started,
            "process_pid": process.pid if process is not None else None,
            "stdout_tail": job.stdout.text(),
            "stdout_truncated": job.stdout.truncated,
            "stderr_tail": job.stderr.text(),
            "stderr_truncated": job.stderr.truncated,
            "partial_input": job.partial_input,
            "rejected_rows": job.rejected_rows,
            "warning_count": len(job.import_warnings),
            "import_warnings": list(job.import_warnings),
            "readiness": _job_readiness(job),
            "activation_skipped_reason": job.activation_skipped_reason,
        }
        if include_reports:
            data["reports"] = load_reports_from_dirs(
                (job.staging, job.target),
                max_bytes=self.report_max_bytes,
            )
        return data

    def _append_output(self, job_id: str, stream_name: str, chunk: str | bytes) -> None:
        text = (
            bytes(chunk).decode("utf-8", "replace")
            if isinstance(chunk, (bytes, bytearray))
            else str(chunk)
        )
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            tail = job.stdout if stream_name == "stdout" else job.stderr
            tail.append(text)
            if job.status != "running":
                return
            stripped = text.strip()
            if stripped.startswith("{"):
                try:
                    event = json.loads(stripped)
                except ValueError:
                    event = None
                if isinstance(event, dict) and "progress" in event:
                    try:
                        parsed = int(event["progress"])
                    except (TypeError, ValueError):
                        parsed = job.progress
                    progress = max(job.progress, min(95, parsed))
                    stage = str(event.get("stage") or job.stage or "building")
                    message = str(event.get("message") or stripped)[:300]
                    self._set_status_unlocked(job, "running", progress, stage, message)
                    return
            match = _PROGRESS_RE.search(text)
            if match:
                parsed = int(match.group(1))
                progress = max(job.progress, min(95, parsed))
                self._set_status_unlocked(job, "running", progress, "building", stripped[:300])

    def _drain_stream(self, job_id: str, stream_name: str, stream: Any) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self._append_output(job_id, stream_name, line)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _run_job(
        self,
        job_id: str,
        popen_factory: Callable[..., subprocess.Popen[Any]],
        activation_callback: Callable[[ImportJob], None] | None,
        script_start: str | os.PathLike[str] | None,
    ) -> None:
        stdout_thread: threading.Thread | None = None
        stderr_thread: threading.Thread | None = None
        try:
            with self._lock:
                job = self.get(job_id)
                if job.cancel_requested:
                    self._set_status_unlocked(job, "cancelled", job.progress, "cancelled", "cancelled")
                    return
                self._set_status_unlocked(job, "running", 3, "validating", "validating input")
                input_path = Path(job.input)
                # HF-Importe tragen eine Dataset-ID statt eines Serverpfads;
                # deren Existenz prüft erst der Builder (mit Netzzugriff).
                if job.method != "hf" and not input_path.exists():
                    raise FileNotFoundError(lt("Input fehlt: {path}", "Input is missing: {path}").format(path=job.input))
                Path(job.output_dir).mkdir(parents=True, exist_ok=True)
                command = build_import_command(job, script_start=script_start)
                job.command = command
                self._set_status_unlocked(job, "running", 5, "building", "builder running")

            proc = popen_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            should_terminate = False
            with self._lock:
                job = self.get(job_id)
                job.process = proc
                should_terminate = job.cancel_requested or job.status == "cancelled"
            if should_terminate:
                proc.terminate()

            stdout_thread = threading.Thread(
                target=self._drain_stream,
                args=(job_id, "stdout", proc.stdout),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._drain_stream,
                args=(job_id, "stderr", proc.stderr),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            returncode = proc.wait()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

            with self._lock:
                job = self.get(job_id)
                job.returncode = returncode
                job.process = None
                if job.cancel_requested or job.status == "cancelled":
                    self._set_status_unlocked(job, "cancelled", job.progress, "cancelled", "cancelled")
                    return
                if returncode != 0:
                    job.error = f"builder exited with code {returncode}"
                    self._set_status_unlocked(job, "failed", 100, "error", job.error)
                    return
                self._set_status_unlocked(job, "running", 98, "loading_report", "loading import report")

            reports = self.load_reports(job_id)
            with self._lock:
                job = self.get(job_id)
                if job.cancel_requested or job.status == "cancelled":
                    self._set_status_unlocked(job, "cancelled", job.progress, "cancelled", "cancelled")
                    return
                outcome = _apply_import_outcome_unlocked(job, reports)
                if job.partial_input and job.activate:
                    job.activation_skipped_reason = "partial_input"
                # Mark the irreversible boundary while holding the same lock
                # used by cancel().  A cancellation either wins before this
                # point (and nothing is published), or loses visibly and the
                # import completes honestly.
                job.finalization_started = True
                stage = "publishing" if activation_callback is not None else "finalizing"
                message = "publishing corpus" if activation_callback is not None else "writing import outcome"
                self._set_status_unlocked(job, "running", 99, stage, message)
            # The job retention is in-memory, so keep the quality outcome with
            # the corpus before publication/registration can make it selectable.
            write_import_outcome(Path(job.staging or job.target), outcome)
            if activation_callback is not None:
                activation_callback(self.get(job_id))
            with self._lock:
                job = self.get(job_id)
                self._set_status_unlocked(
                    job,
                    "succeeded",
                    100,
                    "done_with_warnings" if job.partial_input else "done",
                    _final_import_message(job, reports),
                )
        except Exception as exc:
            with self._lock:
                try:
                    job = self.get(job_id)
                except KeyError:
                    return
                if job.status == "cancelled":
                    return
                job.error = exception_text(exc)
                job.process = None
                self._set_status_unlocked(job, "failed", 100, "error", exception_text(exc))
        finally:
            with self._lock:
                job = self._jobs.get(job_id)
                staging = (
                    job.staging
                    if job is not None and job.status in {"failed", "cancelled"}
                    else None
                )
            if staging:
                _cleanup_staging_scratch(Path(staging))


_SERVICE = ImportJobService()


def supported_import_methods() -> tuple[str, ...]:
    return _builder_supported_import_methods()


def create(
    method: str,
    payload: Mapping[str, Any] | None = None,
    *,
    target: str | os.PathLike[str] | None = None,
    staging: str | os.PathLike[str] | None = None,
    activate: bool | None = None,
    job_id: str | None = None,
) -> ImportJob:
    return _SERVICE.create(
        method,
        payload,
        target=target,
        staging=staging,
        activate=activate,
        job_id=job_id,
    )


def start(
    job_id: str,
    *,
    popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    activation_callback: Callable[[ImportJob], None] | None = None,
    script_start: str | os.PathLike[str] | None = None,
) -> ImportJob:
    return _SERVICE.start(
        job_id,
        popen_factory=popen_factory,
        activation_callback=activation_callback,
        script_start=script_start,
    )


def get(job_id: str) -> ImportJob:
    return _SERVICE.get(job_id)


def snapshot(job_id: str, *, include_reports: bool = False) -> dict[str, Any]:
    return _SERVICE.snapshot(job_id, include_reports=include_reports)


def list_jobs() -> list[dict[str, Any]]:
    return _SERVICE.list()


def cancel(job_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
    return _SERVICE.cancel(job_id, reason=reason)


def load_reports(job_id: str) -> dict[str, Any]:
    return _SERVICE.load_reports(job_id)


def clear_terminal() -> int:
    return _SERVICE.clear_terminal()


def _urls(job_id: str) -> dict[str, str]:
    return {
        "status": f"/api/v1/corpora/imports/{job_id}",
        "cancel": f"/api/v1/corpora/imports/{job_id}/cancel",
        "reports": f"/api/v1/corpora/imports/{job_id}/reports",
    }


def _public_status(status: str) -> str:
    if status == "succeeded":
        return "done"
    if status == "failed":
        return "error"
    return status


def _public_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    job_id = str(raw.get("job_id") or "")
    status = str(raw.get("status") or "queued")
    target_path = str(raw.get("target") or raw.get("target_path") or "")
    payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
    raw_warnings = raw.get("import_warnings")
    import_warnings = (
        [item if isinstance(item, LocalizedText) else str(item) for item in raw_warnings]
        if isinstance(raw_warnings, list)
        else ([str(raw_warnings)] if raw_warnings else [])
    )
    target_name = str(
        raw.get("target_name")
        or payload.get("target_name")
        or (Path(target_path).name if target_path else "")
    )
    data = {
        "job_id": job_id,
        "status": _public_status(status),
        "progress": int(raw.get("progress") or 0),
        "stage": str(raw.get("stage") or raw.get("status") or "queued"),
        "message": (
            raw["message"] if isinstance(raw.get("message"), LocalizedText) else str(raw.get("message") or "")
        ),
        "method": str(raw.get("method") or ""),
        "input_path": str(raw.get("input") or raw.get("input_path") or ""),
        "target_name": target_name,
        "target_path": target_path,
        "staging_path": str(raw.get("staging") or raw.get("staging_path") or ""),
        "activate_on_success": bool(raw.get("activate") or raw.get("activate_on_success")),
        "pid": raw.get("process_pid"),
        "returncode": raw.get("returncode"),
        "error": raw.get("error"),
        "finalization_started": bool(raw.get("finalization_started")),
        "cancellable": bool(
            raw.get(
                "cancellable",
                status not in _TERMINAL_STATUSES and not raw.get("finalization_started"),
            )
        ),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "stdout_tail": raw.get("stdout_tail") or "",
        "stdout_truncated": bool(raw.get("stdout_truncated")),
        "stderr_tail": raw.get("stderr_tail") or "",
        "stderr_truncated": bool(raw.get("stderr_truncated")),
        "partial_input": bool(raw.get("partial_input")),
        "rejected_rows": int(raw.get("rejected_rows") or 0),
        "warning_count": int(raw.get("warning_count") or 0),
        "import_warnings": import_warnings,
        "readiness": str(raw.get("readiness") or "pending"),
        "activation_skipped_reason": raw.get("activation_skipped_reason"),
        "urls": _urls(job_id),
    }
    if "reports" in raw:
        data["reports"] = raw["reports"]
    return data


def _flatten_reports(raw: Mapping[str, Any]) -> dict[str, Any]:
    def _data(name: str) -> Any:
        item = raw.get(name)
        if isinstance(item, Mapping) and "data" in item:
            return item.get("data")
        return item

    return {
        "build_report": _data("build_report.json") or _data("build-report.json"),
        "build_report_md": _data("build_report.md") or _data("build-report.md"),
        "reject_report": _data("reject_report.json") or _data("reject-report.json"),
        "manifest": _data("index_manifest.json"),
        "build_meta": _data("index_build_meta.json"),
        "vrt_import_report": _data("vrt_import_report.json") or _data("vrt-import-report.json"),
        "import_outcome": _data(IMPORT_OUTCOME_FILENAME),
        "raw": dict(raw),
    }


def _report_record(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping) and "data" in value:
        value = value.get("data")
    return value if isinstance(value, Mapping) else None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _first_report_int(data: Mapping[str, Any], keys: Iterable[str]) -> int | None:
    for key in keys:
        parsed = _nonnegative_int(data.get(key))
        if parsed is not None:
            return parsed
    return None


def _append_unique_warning(warnings: list[str], message: str) -> None:
    text = message if isinstance(message, LocalizedText) else message.strip()
    if text and text not in warnings:
        warnings.append(text)


def _import_outcome_from_reports(raw_reports: Mapping[str, Any]) -> dict[str, Any]:
    reports = _flatten_reports(raw_reports)
    warnings: list[str] = []
    rejected_rows = 0
    partial_input = False

    reject_report = _report_record(reports.get("reject_report"))
    if reject_report is not None:
        rejected_rows = _first_report_int(
            reject_report,
            ("rejected_rows", "rows_rejected", "reject_count", "rejected_count", "rejected"),
        ) or 0
        if rejected_rows > 0:
            partial_input = True
            _append_unique_warning(
                warnings,
                lt("{rejected_rows} Eingabezeile(n) wurden laut Reject-Report nicht übernommen.", "{rejected_rows} input row(s) were not imported according to the rejected rows report.").format(rejected_rows=rejected_rows),
            )

    manifest = _report_record(reports.get("manifest"))
    if manifest is not None:
        if manifest.get("complete") is False:
            partial_input = True
            _append_unique_warning(
                warnings,
                lt("Das Index-Manifest markiert den Import als nicht vollständig.", "The index manifest marks the import as incomplete."),
            )
        incomplete_pairs = _first_report_int(
            manifest,
            ("incomplete_pairs", "incomplete_pair_count", "unpaired_rows", "orphan_rows"),
        )
        if incomplete_pairs and incomplete_pairs > 0:
            _append_unique_warning(
                warnings,
                lt("{incomplete_pairs} Paar-/Alignment-Eintrag(e) sind unvollständig.", "{incomplete_pairs} pair or alignment entries are incomplete.").format(incomplete_pairs=incomplete_pairs),
            )

    vrt_report = _report_record(reports.get("vrt_import_report"))
    if vrt_report is not None:
        skipped = (
            (_first_report_int(vrt_report, ("skipped_short_docs", "short_docs_skipped")) or 0)
            + (_first_report_int(vrt_report, ("skipped_outside_docs", "outside_docs_skipped")) or 0)
        )
        inconsistent = _first_report_int(
            vrt_report,
            ("inconsistent_column_lines", "inconsistent_lines"),
        ) or 0
        if skipped > 0:
            partial_input = True
            _append_unique_warning(
                warnings,
                lt("{skipped} VRT-Dokument(e) wurden beim Import übersprungen.", "{skipped} VRT document(s) were skipped during the import.").format(skipped=skipped),
            )
        if inconsistent > 0:
            partial_input = True
            _append_unique_warning(
                warnings,
                lt("{inconsistent} VRT-Zeile(n) haben inkonsistente Spalten.", "{inconsistent} VRT line(s) have inconsistent columns.").format(inconsistent=inconsistent),
            )

    for key in ("build_report", "build_meta"):
        data = _report_record(reports.get(key))
        report_warnings = data.get("warnings") if data is not None else None
        if isinstance(report_warnings, list):
            for item in report_warnings[:5]:
                _append_unique_warning(warnings, f"{key}: {item}")
        elif isinstance(report_warnings, str) and report_warnings.strip():
            _append_unique_warning(warnings, f"{key}: {report_warnings}")

    return {
        "partial_input": partial_input,
        "rejected_rows": rejected_rows,
        "warning_count": len(warnings),
        "import_warnings": warnings,
        "readiness": "partial_input" if partial_input else "complete",
    }


def _apply_import_outcome_unlocked(job: ImportJob, raw_reports: Mapping[str, Any]) -> dict[str, Any]:
    outcome = _import_outcome_from_reports(raw_reports)
    job.partial_input = bool(outcome["partial_input"])
    job.rejected_rows = int(outcome["rejected_rows"])
    job.import_warnings = list(outcome["import_warnings"])
    return outcome


def _final_import_message(job: ImportJob, reports: Mapping[str, Any]) -> str:
    report_note = f", {len(reports)} report(s)" if reports else ""
    if job.partial_input:
        parts = ["done with warnings"]
        if job.rejected_rows:
            parts.append(f"{job.rejected_rows} rejected row(s)")
        if job.activation_skipped_reason:
            parts.append("activation skipped")
        return "; ".join(parts) + report_note
    if job.activate and job.activation_skipped_reason:
        return f"done; activation skipped ({job.activation_skipped_reason}){report_note}"
    if job.activate:
        return f"done; activation requested{report_note}"
    return f"done{report_note}"


def _cleanup_staging_scratch(staging_path: Path) -> None:
    """Remove the per-job ``.imports/<job_id>`` scratch dir so it cannot accrete.

    ``staging_path`` is ``<root>/.imports/<job_id>/<safe_name>``; its parent is the
    per-job scratch directory. We only delete a directory whose own parent is named
    ``.imports`` so an unexpected layout can never widen the blast radius.
    """
    scratch = staging_path.parent
    if scratch.name and scratch.parent.name == ".imports":
        shutil.rmtree(scratch, ignore_errors=True)


def _publish_staging(staging_path: Path, target_path: Path) -> None:
    if staging_path.resolve(strict=False) == target_path.resolve(strict=False):
        return
    if not staging_path.exists():
        _cleanup_staging_scratch(staging_path)
        return
    if target_path.exists():
        raise FileExistsError(lt("Zielkorpus existiert bereits: {target_path}", "Target corpus already exists: {target_path}").format(target_path=target_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging_path), str(target_path))
    _cleanup_staging_scratch(staging_path)


def _load_word_faiss_builder() -> Callable[..., Mapping[str, Any]]:
    """Resolve the importable word-FAISS builder (seam; tests monkeypatch this)."""
    from candyconc.builders._impl_build_word_faiss_from_index import build_word_faiss

    return build_word_faiss


def _run_word_faiss_post_step(job_id: str, target_path: Path, payload: Mapping[str, Any]) -> None:
    """Run the optional word-FAISS post-step AFTER a successful publish.

    Writes ``faiss_word.index`` + ``word_ids.npy`` into the published corpus so
    the read-side capability overlay (``effective_capabilities`` /
    ``corpus_summary``) honestly reports ``semantic.word_similarity=true``.
    A failure never un-publishes the corpus: it is recorded as an import
    warning on the job snapshot instead.
    """
    with _SERVICE._lock:
        current = _SERVICE.get(job_id)
        _SERVICE._set_status_unlocked(
            current, "running", 99, "word_faiss", "building word similarity index (Word-FAISS)"
        )
    spacy_model = str(payload.get("spacy_model") or payload.get("spacy-model") or "").strip()
    try:
        builder = _load_word_faiss_builder()
        builder(Path(target_path), spacy_model=spacy_model or None)
    except Exception as exc:
        with _SERVICE._lock:
            current = _SERVICE.get(job_id)
            _append_unique_warning(
                current.import_warnings,
                lt(
                    "Word-FAISS-Nachschritt fehlgeschlagen (Korpus bleibt nutzbar, "
                    "semantic.word_similarity bleibt false): {error}",
                    "Word FAISS post-step failed (the corpus stays usable, "
                    "semantic.word_similarity stays false): {error}",
                ).format(error=exception_text(exc)),
            )


def start_import_job(
    *,
    method: str,
    input_path: str | os.PathLike[str],
    target_name: str,
    corpora_dir: str | os.PathLike[str] | None = None,
    activate_on_success: bool = False,
    builder_runner: Callable[..., Mapping[str, Any] | None] | None = None,
    register_success: Callable[..., Mapping[str, Any] | None] | None = None,
    run_inline: bool = False,
    options: Mapping[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Create and optionally run an observable corpus import job.

    This high-level facade is what backend routes and tests should use. The
    lower-level ``ImportJobService`` stays responsible for process ownership and
    bounded log/report retention.
    """
    method_key = normalize_import_method(method)
    if import_builder_spec(method_key) is None:
        raise ValueError(lt("Import-Methode nicht unterstützt: {method}", "Import method not supported: {method}").format(method=method))
    if method_key == "vrt" and _bool_option((options or {}).get("inspect") or (options or {}).get("inspect-only")):
        raise ValueError(lt("VRT inspect=true ist ein Diagnostikmodus und kann nicht als Importjob publiziert werden", "VRT inspect=true is a diagnostic mode and cannot be published as an import job"))
    safe_name = _safe_target_name(target_name)
    if method_key == "hf":
        # HF: der Input ist eine Dataset-ID (kein Serverpfad) und bleibt
        # unverändert; Existenz prüft erst der Builder (mit Netzzugriff).
        source_value = str(input_path).strip()
        if not source_value:
            raise ValueError(lt("input fehlt", "input is missing"))
    else:
        source = Path(input_path).expanduser().resolve(strict=False)
        if not source.exists():
            raise FileNotFoundError(lt("Input fehlt: {path}", "Input is missing: {path}").format(path=source))
        source_value = str(source)
    root = Path(corpora_dir).expanduser().resolve(strict=False) if corpora_dir is not None else corpora_dir()
    target_path = (root / safe_name).resolve(strict=False)
    actual_job_id = job_id or uuid.uuid4().hex
    staging_path = (root / ".imports" / actual_job_id / safe_name).resolve(strict=False)
    if not target_path.is_relative_to(root.resolve(strict=False)):
        raise ValueError(lt("target_path liegt außerhalb des verwalteten Korpusverzeichnisses", "target_path is outside the managed corpus directory"))
    if target_path.exists():
        raise FileExistsError(lt("Zielkorpus existiert bereits: {target_path}", "Target corpus already exists: {target_path}").format(target_path=target_path))
    payload = dict(options or {})
    payload.update(
        {
            "input": source_value,
            "output": str(staging_path),
            "target_name": safe_name,
            "activate": bool(activate_on_success),
        }
    )
    build_word_faiss_requested = _bool_option(
        payload.get("build_word_faiss") or payload.get("build-word-faiss")
    )
    job = _SERVICE.create(
        method_key,
        payload,
        target=target_path,
        staging=staging_path,
        activate=bool(activate_on_success),
        job_id=actual_job_id,
    )

    def _register(job_obj: ImportJob) -> None:
        _publish_staging(Path(job_obj.staging or job_obj.target), Path(job_obj.target))
        if build_word_faiss_requested:
            _run_word_faiss_post_step(job_obj.job_id, Path(job_obj.target), payload)
        if register_success is not None:
            activate = bool(job_obj.activate and not job_obj.activation_skipped_reason)
            register_success(Path(job_obj.target), target_name=safe_name, activate=activate)

    if builder_runner is not None:
        def _report(*, progress: int | None = None, stage: str | None = None, message: str | None = None) -> None:
            with _SERVICE._lock:
                current = _SERVICE.get(job.job_id)
                _SERVICE._set_status_unlocked(
                    current,
                    "running",
                    int(progress if progress is not None else current.progress),
                    stage or current.stage,
                    message or current.message,
                )

        def _run_fake_builder() -> None:
            try:
                with _SERVICE._lock:
                    current = _SERVICE.get(job.job_id)
                    if current.cancel_requested or current.status == "cancelled":
                        _SERVICE._set_status_unlocked(current, "cancelled", current.progress, "cancelled", "cancelled")
                        return
                    _SERVICE._set_status_unlocked(current, "running", 5, "building", "builder running")
                result = builder_runner(
                    method=method_key,
                    input_path=source_value,
                    target_name=safe_name,
                    target_path=target_path,
                    staging_path=staging_path,
                    payload=payload,
                    report=_report,
                )
                returncode = 0
                if isinstance(result, Mapping):
                    returncode = int(result.get("returncode", 0) or 0)
                with _SERVICE._lock:
                    current = _SERVICE.get(job.job_id)
                    current.returncode = returncode
                    if current.cancel_requested or current.status == "cancelled":
                        _SERVICE._set_status_unlocked(current, "cancelled", current.progress, "cancelled", "cancelled")
                        return
                if returncode != 0:
                    raise RuntimeError(f"builder exited with code {returncode}")
                reports = _SERVICE.load_reports(job.job_id)
                with _SERVICE._lock:
                    current = _SERVICE.get(job.job_id)
                    if current.cancel_requested or current.status == "cancelled":
                        _SERVICE._set_status_unlocked(current, "cancelled", current.progress, "cancelled", "cancelled")
                        return
                    outcome = _apply_import_outcome_unlocked(current, reports)
                    if current.partial_input and current.activate:
                        current.activation_skipped_reason = "partial_input"
                    current.finalization_started = True
                    _SERVICE._set_status_unlocked(current, "running", 99, "publishing", "publishing corpus")
                write_import_outcome(Path(current.staging or current.target), outcome)
                _register(_SERVICE.get(job.job_id))
                with _SERVICE._lock:
                    current = _SERVICE.get(job.job_id)
                    _SERVICE._set_status_unlocked(
                        current,
                        "succeeded",
                        100,
                        "done_with_warnings" if current.partial_input else "done",
                        _final_import_message(current, reports),
                    )
            except Exception as exc:
                with _SERVICE._lock:
                    current = _SERVICE.get(job.job_id)
                    if current.status == "cancelled":
                        return
                    current.error = exception_text(exc)
                    _SERVICE._set_status_unlocked(current, "failed", 100, "error", exception_text(exc))
            finally:
                with _SERVICE._lock:
                    current = _SERVICE._jobs.get(job.job_id)
                    should_cleanup = current is not None and current.status in {"failed", "cancelled"}
                if should_cleanup:
                    _cleanup_staging_scratch(staging_path)

        if run_inline:
            _run_fake_builder()
        else:
            thread = threading.Thread(
                target=_run_fake_builder,
                name=f"candyconc-import-{job.job_id[:8]}",
                daemon=True,
            )
            with _SERVICE._lock:
                job.worker = thread
            thread.start()
    elif run_inline:
        raise ValueError("run_inline benötigt builder_runner")
    else:
        _SERVICE.start(job.job_id, activation_callback=_register)
    return _public_snapshot(_SERVICE.snapshot(job.job_id, include_reports=True))


def get_import_job(job_id: str) -> dict[str, Any]:
    return _public_snapshot(_SERVICE.snapshot(job_id, include_reports=True))


def list_import_jobs() -> list[dict[str, Any]]:
    return [_public_snapshot(snapshot) for snapshot in _SERVICE.list()]


def preflight_import_job(method: str, input_path: str | os.PathLike[str] | None, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return preflight_import_method(method, input_path, options)


def cancel_import_job(job_id: str) -> dict[str, Any]:
    return _public_snapshot(_SERVICE.cancel(job_id))


def get_import_reports(job_id: str) -> dict[str, Any]:
    raw = _SERVICE.load_reports(job_id)
    reports = _flatten_reports(raw)
    outcome = _import_outcome_from_reports(raw)
    return {
        "schema_version": IMPORT_REPORTS_SCHEMA_VERSION,
        "job_id": job_id,
        "reports": reports,
        "outcome": outcome,
        # Legacy compatibility for clients still reading flattened report keys.
        **reports,
    }


__all__ = [
    "BoundedTextTail",
    "ImportJob",
    "ImportJobService",
    "ImportJobStatus",
    "IMPORT_REPORTS_SCHEMA_VERSION",
    "build_import_command",
    "cancel",
    "clear_terminal",
    "create",
    "get",
    "import_method_descriptors",
    "iter_method_options",
    "list_jobs",
    "load_reports",
    "load_reports_from_dirs",
    "preflight_import_job",
    "preflight_import_method",
    "snapshot",
    "start",
    "supported_import_methods",
    "start_import_job",
    "get_import_job",
    "list_import_jobs",
    "cancel_import_job",
    "get_import_reports",
]
