#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import hashlib
import logging
import os
import re
import math
import subprocess
import sys
import struct
import zlib
import shutil
import time
from contextlib import contextmanager
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Literal, Optional, Tuple

import numpy as np

from candyconc.config import get as _config_get

try:
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover
    pq = None

# spaCy is imported lazily inside the functions that need it (_preflight_checks,
# _load_spacy_pipeline, build_index_from_token_docs) so this module — and the
# pure helpers it exports (PairSink, BuildContext, _build_doc_stream, RejectSink,
# the binary writers) — stay importable in environments without spaCy installed.

from candyconc.ingest.build_fast_index import (  # noqa: E402
    _build_block_top,
    _build_meta_index_from_jsonl,
    _build_unit_sets_from_bounds,
    _write_array,
    _write_block_top,
    _write_hash_index,
    _write_lexicon_bin,
    _write_dense_bitsets,
    _write_ngram_index,
    _write_prefix_all_index,
    _write_prefix_top,
    _write_roaring_postings,
    _write_svb_stream,
    BLOCK_TOP_K,
    BLOCK_TOP_SIZE,
    NGRAM_LEN,
    PREFIX_ALL_LEN,
    PREFIX_LEN,
    PREFIX_TOP_GLOBAL,
    PREFIX_TOP_K,
    SVB_BLOCK_SIZE,
)
from candyconc.utils.text_normalize import normalize_text_basic  # noqa: E402
from candyconc.utils.disk_preflight import check_disk_space  # noqa: E402
from candyconc.i18n import localize, lt  # noqa: E402
from candyconc.core import index_format  # noqa: E402
from candyconc.core import pairing  # noqa: E402

from candyconc.ingest.build_fast_index import _iter_meta_jsonl  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)

_EMB_SAMPLE_MAX = 50_000
_EMB_ADD_BATCH = 10_000
_GEMMA_SAMPLE_MAX = 50_000
_GEMMA_ADD_BATCH = 10_000
_LOG_CONFIGURED = False
_BLANK_DEFAULTS_COMPONENT = "candyconc_blank_defaults"


def _candyconc_blank_defaults(doc):  # type: ignore[no-untyped-def]
    """Minimal deterministic annotations for explicit blank spaCy pipelines."""

    for tok in doc:
        tok.lemma_ = tok.lower_
        tok.pos_ = "X"
    return doc


@dataclass
class BuildContext:
    """Per-build run state (phases, warnings, preflight result).

    Replaces the former mutable module globals so a build is reentrant and
    unit-testable, and so the extracted backend (R3.4) receives this explicitly.
    """

    phases: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    preflight: dict | None = None
    reject_sink: "RejectSink | None" = None


class RejectError(RuntimeError):
    """Raised by RejectSink when error_policy='fail_fast' or a fatal reject occurs."""


@dataclass
class RejectSink:
    """Accumulates per-row rejection events during a doc-stream build (R3.12).

    Pass an instance as ``reject_sink=`` to ``_build_doc_stream`` /
    ``_build_generic_doc_stream``. The default ``None`` at every call site
    preserves the existing silent-continue behaviour BYTE-FOR-BYTE — the sink
    only adds counting/reporting on top, it never changes which rows are emitted.
    """

    error_policy: Literal["collect", "fail_fast"] = "collect"
    max_sample: int = 50
    log_path: Path | None = None  # optional JSONL per-row file; None = none

    rows_seen: int = field(default=0, init=False)
    rows_rejected: int = field(default=0, init=False)
    _counts: Dict[str, int] = field(default_factory=dict, init=False)
    _samples: List[dict] = field(default_factory=list, init=False)
    _log_fh: object = field(default=None, init=False, repr=False)

    # --- lifecycle ---
    def open_log(self) -> None:
        if self.log_path is not None and self._log_fh is None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = self.log_path.open("a", encoding="utf-8")

    def close_log(self) -> None:
        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

    # --- recording ---
    def seen(self) -> None:
        """Count one row entering the loop (before any filtering)."""
        self.rows_seen += 1

    def record(
        self,
        row_idx: int,
        reason: str,
        context: dict | None = None,
        *,
        fatal: bool = False,
    ) -> None:
        """Record one rejection. ``reason`` is a short snake_case code.

        Raises ``RejectError`` if ``fatal=True`` or ``error_policy='fail_fast'``.
        """
        self.rows_rejected += 1
        self._counts[reason] = self._counts.get(reason, 0) + 1
        entry = {"row_idx": row_idx, "reason": reason}
        if context:
            entry.update(context)
        if len(self._samples) < self.max_sample:
            self._samples.append(entry)
        if self._log_fh is not None:
            self._log_fh.write(json.dumps(entry, ensure_ascii=False))
            self._log_fh.write("\n")
        if fatal or self.error_policy == "fail_fast":
            raise RejectError(
                f"RejectSink: {reason} (row {row_idx}): "
                + json.dumps(context or {}, ensure_ascii=False)
            )

    # --- reporting ---
    def summary(self) -> dict:
        """Return a JSON-serialisable coverage/rejection summary."""
        return {
            "rows_seen": self.rows_seen,
            "rows_rejected": self.rows_rejected,
            "rejection_rate": (
                round(self.rows_rejected / self.rows_seen, 6)
                if self.rows_seen > 0 else 0.0
            ),
            "by_reason": dict(self._counts),
            "samples": list(self._samples),
        }

    def flush(self, output_path: Path) -> None:
        """Write reject_report.json into the index output directory."""
        self.close_log()
        _write_json(output_path / "reject_report.json", self.summary())


def _text_hash(text: str) -> str:
    if not text:
        return "0" * 16
    h = hashlib.blake2s(text.encode("utf-8"), digest_size=8).hexdigest()
    return h


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), "utf-8")


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` to ``path`` via a tmp file + ``os.replace`` so a crash
    mid-write never leaves a half-written (or truthy-but-partial) file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _configure_logging(output_path: Path | None = None, log_file: str | None = None) -> None:
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return
    log_target = log_file or os.environ.get("CANDYCONC_BUILD_LOG")
    if not log_target and output_path is not None:
        log_target = str(output_path / "build.log")
    if log_target:
        try:
            log_path = Path(log_target)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            LOGGER.info("Build log: %s", log_path)
        except Exception as exc:
            LOGGER.warning("Build log file could not be created: %s", exc)
    _LOG_CONFIGURED = True


def _snapshot_resources(path: Path | None = None) -> dict:
    info: dict = {"ts": _utc_now()}
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        info.update(
            {
                "mem_total": int(vm.total),
                "mem_available": int(vm.available),
                "mem_used": int(vm.used),
            }
        )
    except Exception:
        pass
    try:
        target = path or Path.cwd()
        usage = shutil.disk_usage(target)
        info.update(
            {
                "disk_total": int(usage.total),
                "disk_free": int(usage.free),
                "disk_used": int(usage.used),
            }
        )
    except Exception:
        pass
    return info


@contextmanager
def _phase(name: str, *, output_path: Path | None = None, ctx: "BuildContext | None" = None) -> Iterator[None]:
    start_perf = time.perf_counter()
    start = _snapshot_resources(output_path)
    LOGGER.info("Phase start: %s", name)
    try:
        yield
    finally:
        end_perf = time.perf_counter()
        end = _snapshot_resources(output_path)
        duration = end_perf - start_perf
        phase = {
            "name": name,
            "started_at": start.get("ts"),
            "finished_at": end.get("ts"),
            "duration_s": round(duration, 3),
        }
        for key in ("mem_total", "mem_available", "mem_used", "disk_total", "disk_free", "disk_used"):
            if key in start and key in end:
                phase[key] = {"start": start[key], "end": end[key], "delta": end[key] - start[key]}
        if ctx is not None:
            ctx.phases.append(phase)
        LOGGER.info("Phase end: %s (%.2fs)", name, duration)


def _preflight_checks(
    *,
    input_path: Path,
    output_path: Path,
    spacy_model: str,
    build_embeddings: bool,
    build_word_faiss: bool | None,
    build_gemma_embeddings: bool,
    export_gemma_texts: bool,
    gemma_endpoint: str | None,
    gemma_model: str | None,
    gemma_timeout: float,
    disable_ner: bool,
    disable_deps: bool,
    require_input_text: bool,
    generic_text_column: str | None = None,
) -> dict:
    errors: List[str] = []
    warnings: List[str] = []
    details: Dict[str, Any] = {}

    if not input_path.exists():
        errors.append(lt("Input Parquet fehlt: {path}", "Input Parquet file is missing: {path}").format(path=input_path))
    elif not input_path.is_file():
        errors.append(lt("Input ist keine Datei: {path}", "Input is not a file: {path}").format(path=input_path))

    if pq is None:
        errors.append(lt(
            "pyarrow fehlt (Parquet Streaming nicht moeglich).",
            "pyarrow is missing (Parquet streaming is not possible).",
        ))

    try:
        output_path.mkdir(parents=True, exist_ok=True)
        if any(output_path.iterdir()):
            warnings.append(lt(
                "Output-Verzeichnis ist nicht leer: {path}", "Output folder is not empty: {path}"
            ).format(path=output_path))
    except Exception as exc:
        errors.append(lt(
            "Output-Verzeichnis nicht beschreibbar: {error}", "Output folder is not writable: {error}"
        ).format(error=exc))

    # Disk-space estimate: shared heuristic from candyconc.utils.disk_preflight.
    # Identical factors, reserve and env knobs as the previous inline copy
    # (CANDYCONC_BUILD_DISK_FACTOR, CANDYCONC_BUILD_DISK_RESERVE_GB,
    # CANDYCONC_BUILD_ALLOW_LOW_DISK). The shared check never raises: an
    # unreadable volume yields a non-blocking warning, not an abort.
    try:
        input_size = int(input_path.stat().st_size) if input_path.exists() else 0
    except OSError:
        input_size = 0
    disk_check = check_disk_space(
        input_size,
        output_path,
        build_embeddings=build_embeddings,
        build_word_faiss=(build_word_faiss is True),
        build_gemma_embeddings=bool(build_gemma_embeddings or export_gemma_texts),
    )
    for disk_key in ("disk_free", "disk_required_est", "disk_reserve"):
        if disk_key in disk_check:
            details[disk_key] = disk_check[disk_key]
    if disk_check.get("blocking"):
        errors.append(disk_check.get("message") or lt(
            "Wenig freier Speicher fuer Build.", "Low free disk space for the build."
        ))
    elif disk_check.get("status") in {"warn", "unknown"}:
        warnings.append(disk_check.get("message") or lt(
            "Disk Usage konnte nicht ermittelt werden.", "Disk usage could not be determined."
        ))

    # Parquet schema checks
    if pq is not None and input_path.exists() and input_path.is_file():
        try:
            pf = pq.ParquetFile(input_path)
            cols = set(pf.schema.names)
            if generic_text_column:
                details["text_column"] = generic_text_column
                if generic_text_column not in cols:
                    errors.append(lt(
                        "Parquet fehlt konfigurierte Textspalte: {column}",
                        "The Parquet file lacks the configured text column: {column}",
                    ).format(column=generic_text_column))
            elif "target_text" not in cols:
                if "text" in cols:
                    warnings.append(lt(
                        "Parquet fehlt target_text, verwende Fallback auf text.",
                        "The Parquet file has no target_text. Using text instead.",
                    ))
                    details["target_text_fallback"] = "text"
                else:
                    errors.append(lt(
                        "Parquet fehlt Pflichtspalte: target_text",
                        "The Parquet file lacks the required column target_text",
                    ))
            if require_input_text and not generic_text_column and "input_text" not in cols:
                errors.append(lt(
                    "Parquet fehlt input_text, aber require_input_text ist aktiv. "
                    "Nutze --allow-missing-input-text falls passend.",
                    "The Parquet file has no input_text, but require_input_text is on. "
                    "Use --allow-missing-input-text if that fits.",
                ))
        except Exception as exc:
            warnings.append(lt(
                "Parquet Schema konnte nicht gelesen werden: {error}",
                "The Parquet schema could not be read: {error}",
            ).format(error=exc))

    # spaCy model + pipeline
    try:
        import spacy  # lazy: only reached when preflight actually runs
        blank_match = re.fullmatch(r"blank:([A-Za-z][A-Za-z_-]*)", str(spacy_model).strip())
        nlp = spacy.blank(blank_match.group(1).lower()) if blank_match else spacy.load(spacy_model)
        details["spacy_lang"] = nlp.lang
        details["spacy_pipe"] = list(nlp.pipe_names)
        if build_embeddings or (build_word_faiss is True):
            if nlp.vocab.vectors_length == 0:
                errors.append(lt(
                    "spaCy Modell hat keine Vektoren (Embeddings benoetigt).",
                    "The spaCy pipeline has no vectors (needed for embeddings).",
                ))
        if not disable_ner and "ner" not in nlp.pipe_names:
            errors.append(lt(
                "spaCy NER Pipeline fehlt, obwohl enable_ner gesetzt ist.",
                "The spaCy pipeline has no NER component, but enable_ner is set.",
            ))
        if not disable_deps and "parser" not in nlp.pipe_names:
            errors.append(lt(
                "spaCy Parser fehlt, obwohl enable_deps gesetzt ist.",
                "The spaCy pipeline has no parser, but enable_deps is set.",
            ))
    except Exception as exc:
        errors.append(lt(
            "spaCy Modell '{model}' nicht ladbar: {error}",
            "The spaCy pipeline '{model}' cannot be loaded: {error}",
        ).format(model=spacy_model, error=exc))

    # FAISS dependency
    if build_embeddings or build_gemma_embeddings or (build_word_faiss is True):
        try:
            import faiss  # type: ignore  # noqa: F401
        except Exception as exc:
            errors.append(lt("faiss fehlt: {error}", "faiss is missing: {error}").format(error=exc))

    # Gemma endpoint check (only when embeddings are built)
    if build_gemma_embeddings:
        endpoint = gemma_endpoint or _config_get(
            "CANDYCONC_GEMMA_EMB_ENDPOINT", "http://127.0.0.1:1234/v1/embeddings"
        )
        model = gemma_model or _config_get(
            "CANDYCONC_GEMMA_EMB_MODEL", "google/embedding-gemma-300m"
        )
        try:
            from candyconc.services.remote_embeddings import embed_remote

            embed_remote(
                ["ping"],
                endpoint=str(endpoint),
                model=str(model),
                batch_size=1,
                timeout=min(float(gemma_timeout), 15.0),
            )
            details["gemma_endpoint"] = str(endpoint)
            details["gemma_model"] = str(model)
        except Exception as exc:
            errors.append(lt(
                "Gemma Endpoint nicht erreichbar: {error}", "The Gemma endpoint cannot be reached: {error}"
            ).format(error=exc))
    elif export_gemma_texts:
        warnings.append(lt(
            "Gemma Embeddings deaktiviert. Es werden nur Texte exportiert.",
            "Gemma embeddings are off. Only the texts are exported.",
        ))

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "warnings": warnings, "details": details}


def _write_build_report(
    output_path: Path, *, status: str, ctx: "BuildContext", error: str | None = None
) -> None:
    report = {
        "status": status,
        "created_at": _utc_now(),
        "preflight": ctx.preflight,
        "phases": ctx.phases,
    }
    if ctx.warnings:
        report["warnings"] = list(ctx.warnings)
    if error:
        report["error"] = error
    _write_json(output_path / "build_report.json", report)
    _write_build_report_md(output_path / "build_report.md", report)


def _write_build_report_md(path: Path, report: dict) -> None:
    lines: List[str] = []
    lines.append("# Fast Index Build Report")
    lines.append("")
    lines.append(f"- status: {report.get('status')}")
    lines.append(f"- created_at: {report.get('created_at')}")
    if report.get("error"):
        lines.append(f"- error: {report.get('error')}")
    preflight = report.get("preflight") or {}
    lines.append("")
    lines.append("## Preflight")
    lines.append(f"- ok: {preflight.get('ok')}")
    for err in preflight.get("errors") or []:
        lines.append(f"- error: {err}")
    for warn in preflight.get("warnings") or []:
        lines.append(f"- warning: {warn}")
    for warn in report.get("warnings") or []:
        lines.append(f"- warning: {warn}")
    lines.append("")
    lines.append("## Phases")
    for phase in report.get("phases") or []:
        lines.append(f"- {phase.get('name')}: {phase.get('duration_s')}s")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cleanup_partial_output(output_path: Path) -> None:
    try:
        for tmp_dir in output_path.glob(".*_postings_tmp"):
            if tmp_dir.is_dir():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            else:
                tmp_dir.unlink(missing_ok=True)
    except Exception:
        pass
    tmp_files = [
        "word_ids.raw",
        "lemma_ids.raw",
        "pos_ids.raw",
        "morph_ids.raw",
        "ent_ids.raw",
        "rel_ids.raw",
        "head_ids.raw",
        "passage_vecs.tmp.bin",
        "passage_texts.tmp.jsonl",
        "word_vecs.tmp.bin",
        "word_ids.tmp.bin",
        "paired_with.tmp",
        "paired_with.ids.tmp",
        "doc_metadata.mmap.tmp",
        "doc_metadata.filtered.jsonl",
        "gemma_doc_texts.jsonl",
        "gemma_sentence_texts.jsonl",
    ]
    for name in tmp_files:
        path = output_path / name
        if path.exists():
            path.unlink(missing_ok=True)


def _autotune_script() -> Path:
    """Locate ``scripts/bench_cqlhpc_autotune.py`` in a source checkout.

    The benchmark is a development tool and not part of the package. Outside a
    checkout the path does not exist and the autotune step ends with a warning.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "bench_cqlhpc_autotune.py"
        if candidate.is_file():
            return candidate
    return Path("scripts") / "bench_cqlhpc_autotune.py"


def _clean_output_dir(output_path: Path) -> None:
    resolved = output_path.resolve()
    # Never wipe the filesystem root, the home directory or any directory that
    # contains this installation (site-packages, a source checkout).
    protected = {Path("/"), Path.home().resolve(), *Path(__file__).resolve().parents}
    if resolved in protected:
        raise RuntimeError(f"Refuse to clean unsafe path: {resolved}")
    if output_path.is_symlink():
        raise RuntimeError(f"Refuse to clean symlinked output: {output_path}")
    if output_path.exists():
        if output_path.is_dir():
            shutil.rmtree(output_path, ignore_errors=False)
        else:
            output_path.unlink()
    output_path.mkdir(parents=True, exist_ok=True)


def _origin_id(source: str | None, doc_id: str | None, fallback_id: str | None) -> str:
    s = source or ""
    d = doc_id or ""
    f = fallback_id or ""
    if s:
        if d:
            return f"{s}:{d}"
        if f:
            return f"{s}:{f}"
        return s
    return d or f or "unknown"


def _available_memory_bytes() -> Optional[int]:
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().available)
    except Exception:
        LOGGER.warning("psutil is not available, estimating the memory size without it")
    if sys.platform.startswith("linux"):
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            try:
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
            except Exception:
                return None
    if sys.platform == "darwin":
        try:
            output = subprocess.check_output(["vm_stat"], text=True)
            lines = output.splitlines()
            page_size = 4096
            if lines:
                match = re.search(r"page size of (\d+) bytes", lines[0])
                if match:
                    page_size = int(match.group(1))
            pages = {}
            for line in lines[1:]:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                value = value.strip().strip(".")
                if value.isdigit():
                    pages[key.strip()] = int(value)
            free_pages = (
                pages.get("Pages free", 0)
                + pages.get("Pages inactive", 0)
                + pages.get("Pages speculative", 0)
            )
            if free_pages:
                return int(free_pages) * int(page_size)
        except Exception:
            return None
    if hasattr(os, "sysconf"):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            page_count = os.sysconf("SC_PHYS_PAGES")
            return int(page_size) * int(page_count)
        except Exception:
            return None
    return None


def _auto_batch_size(available_bytes: Optional[int]) -> int:
    if not available_bytes:
        return 64
    gb = available_bytes / (1024**3)
    if gb < 4:
        return 16
    if gb < 8:
        return 32
    if gb < 16:
        return 64
    if gb < 32:
        return 128
    if gb < 64:
        return 256
    return 512


def _auto_n_process(batch_size: int) -> int:
    cpu_count = os.cpu_count() or 1
    available = _available_memory_bytes()
    if available:
        # Sehr grobe Heuristik: pro spaCy Prozess ca 4 GB ansetzen
        mem_cap = max(1, int(available // (4 * 1024**3)))
    else:
        mem_cap = 2
    return max(1, min(cpu_count, batch_size or cpu_count, mem_cap, 8))


def _safe_str(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if s.strip() else None


def _safe_meta_value(value: object) -> Optional[str]:
    """Coerce a (possibly nested) column value into a metadata string.

    Scalars go through :func:`_safe_str`. Nested values (dict / list / tuple from a
    parquet Struct / List column) are JSON-encoded so they are PRESERVED as readable
    metadata rather than dropped or stored as a Python ``repr``. ``numpy``/Arrow
    scalars inside nested values fall back to ``str`` via ``default=str``.
    """
    if isinstance(value, (dict, list, tuple)):
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
        return s if s.strip() else None
    return _safe_str(value)


def _safe_meta_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json

            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n+")


def _last_whitespace_cut(text: str, start: int, hard_end: int) -> int:
    """Return a cut offset in ``(start, hard_end]`` that ends just after the last
    run of whitespace at or before ``hard_end`` — so the chunk boundary lands on
    a token gap, never mid-token.

    The returned offset is inclusive of the trailing whitespace (it stays with
    the preceding chunk), keeping the split exactly content-preserving. Falls
    back to ``hard_end`` (a raw cut) only when the whole window is whitespace-free
    (e.g. one unbroken token longer than ``max_chars``), which is unavoidable.
    """
    cut = hard_end
    while cut > start and not text[cut - 1].isspace():
        cut -= 1
    # cut now points just after a whitespace char (or back at start if the window
    # is all non-space). Reject a degenerate cut == start (no progress).
    if cut <= start:
        return hard_end
    return cut


def _split_text_chunks_with_boundaries(
    text: str, max_chars: int
) -> List[Tuple[str, bool]]:
    """Split ``text`` like :func:`_split_text_chunks`, tagging each chunk with
    whether its START is a REAL boundary (document start or paragraph break) as
    opposed to a synthetic, content-arbitrary mid-paragraph WHITESPACE hard-cut.

    Returns ``[(chunk, is_real_boundary_start), ...]``. The chunk strings are
    byte-for-byte identical to ``_split_text_chunks(text, max_chars)`` — this is
    purely additive boundary classification, so the byte-identity golden and the
    unchunked path are unaffected.

    A chunk start is a real boundary when it coincides with either the document
    start or a paragraph break recognised by ``_PARAGRAPH_BREAK_RE``. The only
    synthetic starts are the 2nd+ slices produced when a SINGLE paragraph longer
    than ``max_chars`` is hard-split mid-content: those seams must NOT anchor a
    sentence start downstream (doing so inflates sentence_count and fragments
    ``within(<s>)`` at a position that is not a real sentence boundary).
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return [(text, True)]

    n = len(text)
    # Segment boundaries: each paragraph keeps the separator that follows it, so
    # the segments tile [0, n) with no gaps. text[seg_start:seg_end] slices are
    # exhaustive and non-overlapping by construction.
    seg_bounds: List[int] = [0]
    for m in _PARAGRAPH_BREAK_RE.finditer(text):
        # Cut after the separator so the separator travels with the preceding
        # paragraph; consecutive separators collapse into one boundary.
        seg_bounds.append(m.end())
    if seg_bounds[-1] != n:
        seg_bounds.append(n)
    # Deduplicate (a trailing separator can make m.end() == n).
    bounds: List[int] = []
    for b in seg_bounds:
        if not bounds or b != bounds[-1]:
            bounds.append(b)

    chunks: List[Tuple[str, bool]] = []
    cur_start = bounds[0]
    cur_end = bounds[0]
    for nxt in bounds[1:]:
        seg_len = nxt - cur_end
        # Hard-split any single segment longer than max_chars. Cuts are placed on
        # whitespace where possible so a split never lands mid-token — that keeps
        # the chunked build's token_count identical to the unchunked build (a raw
        # mid-word cut would re-tokenize into extra fragments). The split is still
        # exactly content-preserving because the whitespace at the cut travels
        # with the preceding chunk via offset slicing.
        if seg_len > max_chars:
            if cur_end > cur_start:
                # cur_start is a real boundary (doc start or prior paragraph flush).
                chunks.append((text[cur_start:cur_end], True))
            i = cur_end
            first_slice = True
            while i < nxt:
                hard_end = min(i + max_chars, nxt)
                cut = hard_end
                if hard_end < nxt:
                    cut = _last_whitespace_cut(text, i, hard_end)
                # The first slice begins at the segment (paragraph) start — a real
                # boundary. Every subsequent slice begins at a synthetic whitespace
                # hard-cut INSIDE the paragraph: not a real sentence boundary.
                chunks.append((text[i:cut], first_slice))
                first_slice = False
                i = cut
            cur_start = nxt
            cur_end = nxt
            continue
        if (cur_end - cur_start) + seg_len <= max_chars or cur_end == cur_start:
            cur_end = nxt
            continue
        # Flush the accumulated chunk and start a fresh one at this segment
        # boundary (a real paragraph break).
        chunks.append((text[cur_start:cur_end], True))
        cur_start = cur_end
        cur_end = nxt
    if cur_end > cur_start:
        chunks.append((text[cur_start:cur_end], True))
    return chunks


def _split_text_chunks(text: str, max_chars: int) -> List[str]:
    """Split ``text`` into chunks of at most ``max_chars`` characters.

    Content-preserving: ``"".join(_split_text_chunks(text, k)) == text`` for any
    input. Splits are placed on paragraph boundaries where possible (so each
    chunk re-tokenizes to the same sentences a standalone paragraph would), but
    every original character — including the paragraph separators themselves and
    any leading/trailing whitespace — is carried into exactly one chunk via
    offset slicing rather than strip()+rejoin (which dropped/altered content and
    silently changed token counts across re-builds).

    Thin wrapper over :func:`_split_text_chunks_with_boundaries` that drops the
    per-chunk real-boundary flag (callers that need the flag use that function
    directly). The returned strings are byte-identical to the historical output.
    """
    return [chunk for chunk, _is_real in _split_text_chunks_with_boundaries(text, max_chars)]


class _JsonArrayWriter:
    def __init__(self, path: Path) -> None:
        self._fh = path.open("w", encoding="utf-8")
        self._first = True
        self._fh.write("[")

    def append(self, obj: object) -> None:
        if not self._first:
            self._fh.write(",")
        self._fh.write(json.dumps(obj))
        self._first = False

    def close(self) -> None:
        self._fh.write("]")
        self._fh.close()


def _iter_jsonl_batches(path: Path, batch_size: int) -> Iterator[list[object]]:
    if batch_size <= 0:
        batch_size = 1
    batch: list[object] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            batch.append(json.loads(line))
            if len(batch) >= batch_size:
                yield batch
                batch = []
    if batch:
        yield batch


def _jsonl_to_json_array(src: Path, dst: Path) -> None:
    writer = _JsonArrayWriter(dst)
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            writer.append(json.loads(line))
    writer.close()


_RE_THINKING_TAG = re.compile(r"(?is)<thinking>.*?</thinking>")
_RE_FINAL = re.compile(r"(?i)\bfinal\s*:")
_RE_ANSWER = re.compile(r"(?i)\bantwort\s*:")
_RE_RESPONSE = re.compile(r"(?i)\bresponse\s*:")
_RE_ASSISTANT = re.compile(r"(?i)^\s*assistant\s*:")
_RE_SYSTEM = re.compile(r"(?i)^\s*system\s*:")
_RE_PROMPT_START = re.compile(
    r"(?i)^\s*(we need to|must be|must include|use short|avoid meta|write a|compose a|create a|generate a)"
)
_RE_ANALYSIS_START = re.compile(r"(?i)^\s*(analysis|analyse)\s*[:\n]")


def _extract_thinking(text: str) -> Tuple[str, str]:
    if not text:
        return "", ""
    t = text.strip()
    if not t:
        return "", ""
    thinking_parts: List[str] = []
    # Remove explicit thinking tags
    if "<thinking" in t.lower():
        matches = list(_RE_THINKING_TAG.finditer(t))
        if matches:
            for m in matches:
                thinking_parts.append(m.group(0))
            t = _RE_THINKING_TAG.sub("", t).strip()
    # Split on final/answer/response markers
    for marker in (_RE_FINAL, _RE_ANSWER, _RE_RESPONSE):
        matches = list(marker.finditer(t))
        if matches:
            last = matches[-1]
            left = t[: last.start()].strip()
            right = t[last.end() :].strip()
            if left:
                thinking_parts.append(left)
            return "\n\n".join(thinking_parts).strip(), right
    # Assistant or system prefixes
    if _RE_ASSISTANT.search(t):
        parts = _RE_ASSISTANT.split(t, maxsplit=1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        if left:
            thinking_parts.append(left)
        return "\n\n".join(thinking_parts).strip(), right
    if _RE_SYSTEM.search(t):
        parts = _RE_SYSTEM.split(t, maxsplit=1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        if left:
            thinking_parts.append(left)
        return "\n\n".join(thinking_parts).strip(), right
    # Prompt-like or analysis-only outputs
    if _RE_PROMPT_START.search(t) or _RE_ANALYSIS_START.search(t):
        return t, ""
    return "\n\n".join(thinking_parts).strip(), t


_SKIP_META_KEYS = {
    "text",
    "source_text",
    "target_text",
    "reference_text",
    "prompt_text",
    "input_text",
    "output_text",
    "full_text",
    "prompt_template",
    "params",
}


def _merge_scalar_meta(
    meta: dict,
    raw: dict,
    *,
    allow_override: bool = False,
    max_len: int = 512,
) -> None:
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if key in _SKIP_META_KEYS:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value or len(value) > max_len:
                continue
        if value is None:
            continue
        if not allow_override and key in meta and meta.get(key) not in (None, ""):
            continue
        meta[key] = value


class IdWriter:
    def __init__(self, path: Path, typecode: str, flush_size: int = 500_000) -> None:
        self.path = path
        self.typecode = typecode
        self.flush_size = int(flush_size)
        self._buf = array(typecode)
        self._fh = open(path, "wb")
        self.count = 0

    def extend(self, values: Iterable[int]) -> None:
        if isinstance(values, np.ndarray):
            if self.typecode == "I" and values.dtype == np.uint32:
                self._buf.frombytes(values.tobytes(order="C"))
            elif self.typecode == "i" and values.dtype == np.int32:
                self._buf.frombytes(values.tobytes(order="C"))
            else:
                self._buf.extend(values.tolist())
        else:
            self._buf.extend(values)
        if len(self._buf) >= self.flush_size:
            self.flush()

    def flush(self) -> None:
        if not self._buf:
            return
        self._buf.tofile(self._fh)
        self.count += len(self._buf)
        self._buf = array(self.typecode)

    def close(self) -> None:
        self.flush()
        self._fh.close()


def _iter_parquet_rows(path: Path, columns: List[str], batch_size: int) -> Iterator[dict]:
    if pq is None:
        raise SystemExit("pyarrow is missing for Parquet streaming")
    pf = pq.ParquetFile(path)
    # Use the Arrow schema's top-level column names, NOT pf.schema (the Parquet
    # *physical* schema), which flattens nested Struct/List columns into their leaf
    # field names (meta.author -> "author", a List -> "item"). Membership-checking
    # against the physical names made genuinely-present nested columns look MISSING,
    # so the builder silently set them to None and dropped the data. The Arrow
    # schema preserves the real top-level names (meta, tags) and iter_batches reads
    # the nested column whole.
    schema_names = list(pf.schema_arrow.names)
    missing = [c for c in columns if c not in schema_names]
    if missing:
        LOGGER.warning("Missing columns (set to None): %s", missing)
    used_columns = [c for c in columns if c in schema_names]
    for batch in pf.iter_batches(batch_size=batch_size, columns=used_columns):
        batch_dict = batch.to_pydict()
        num_rows = batch.num_rows
        for i in range(num_rows):
            row = {col: batch_dict[col][i] for col in used_columns}
            if missing:
                for col in missing:
                    row[col] = None
            yield row


class PairSink:
    """Backend-owned authority for document indices and human/AI pairing.

    The frontend stream tags each new document with a *logical* anchor (its dedup
    key) and calls :meth:`assign` to get a logical order. The engine, as it
    consumes documents, calls :meth:`bind` which asserts the logical order matches
    the physical ``doc_idx`` it assigns — making the previously-implicit lockstep
    explicit and fail-loud. Pairs and duplicates are recorded by logical anchor and
    resolved to physical ``doc_idx`` only after every document is bound, so the
    persisted ``paired_with`` / ``duplicate_count`` are identical to the legacy
    int-keyed path while no longer depending on a second, frontend-side counter.
    """

    def __init__(self) -> None:
        self._assign_seq: Dict[object, int] = {}
        self._next_seq = 0
        self._bound: Dict[object, int] = {}
        self._pairs: List[Tuple[object, object]] = []
        self._dups: Dict[object, int] = {}

    def assign(self, anchor: object) -> int:
        seq = self._assign_seq.get(anchor)
        if seq is None:
            seq = self._next_seq
            self._assign_seq[anchor] = seq
            self._next_seq += 1
        return seq

    def on_pair(self, human_anchor: object, ai_anchor: object) -> None:
        self._pairs.append((human_anchor, ai_anchor))

    def on_duplicate(self, ai_anchor: object, custom_id: str | None) -> None:
        self._dups[ai_anchor] = self._dups.get(ai_anchor, 0) + 1

    def bind(self, anchor: object, doc_idx: int) -> None:
        seq = self._assign_seq.get(anchor)
        if seq is None:
            raise RuntimeError(f"PairSink: nicht zugewiesener Anchor beim Binden: {anchor!r}")
        if seq != doc_idx:
            raise RuntimeError(
                f"PairSink: doc_idx Desync — Anchor-Sequenz {seq} != Engine doc_idx {doc_idx} "
                f"(anchor={anchor!r})"
            )
        self._bound[anchor] = doc_idx

    @property
    def n_assigned(self) -> int:
        return len(self._assign_seq)

    @property
    def n_bound(self) -> int:
        return len(self._bound)

    def resolve_pairs(self) -> Iterator[Tuple[int, int]]:
        for human_anchor, ai_anchor in self._pairs:
            if human_anchor not in self._bound or ai_anchor not in self._bound:
                raise RuntimeError("PairSink: ungebundener Anchor in resolve_pairs()")
            yield (self._bound[human_anchor], self._bound[ai_anchor])

    def resolve_duplicates(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for ai_anchor, count in self._dups.items():
            if ai_anchor not in self._bound:
                raise RuntimeError("PairSink: ungebundener Anchor in resolve_duplicates()")
            out[self._bound[ai_anchor]] = int(count)
        return out


def _build_doc_stream(
    rows: Iterable[dict],
    *,
    include_prompts: bool,
    split_long_texts: bool,
    max_doc_chars: int,
    require_input_text: bool,
    on_pair: callable | None = None,
    on_duplicate: callable | None = None,
    on_assign: callable | None = None,
    reject_sink: "RejectSink | None" = None,
) -> Iterator[Tuple[str, dict]]:
    human_idx_by_key: Dict[Tuple[str, str, str], int] = {}
    ai_idx_by_key: Dict[Tuple[str, str, str, str, str], int] = {}
    fallback_text_warned = False
    _local_seq = [0]
    _seen_idx = 0

    def _assign(anchor) -> int:
        if on_assign is not None:
            return int(on_assign(anchor))
        seq = _local_seq[0]
        _local_seq[0] += 1
        return seq

    def _add_doc(text: str, meta: dict, anchor) -> int:
        # Backend (PairSink) owns the authoritative doc_idx; the stream only carries
        # a logical anchor + assign-order that the engine binds and asserts.
        meta["_anchor"] = anchor
        return _assign(anchor)

    def _emit_text(text: str, meta: dict) -> Iterator[Tuple[str, dict]]:
        if not split_long_texts or not max_doc_chars or len(text) <= max_doc_chars:
            yield (text, meta)
            return
        chunks = _split_text_chunks_with_boundaries(text, max_doc_chars)
        for i, (chunk, is_real_boundary) in enumerate(chunks):
            # Fuer den ersten Chunk das Original-Meta verwenden, damit spaetere
            # Updates (z.B. paired_with) im Haupt-Meta sichtbar bleiben.
            # Only _chunk_index / _synthetic_seam are consumed by the engine; they
            # (and every other "_"-prefixed transport key) are stripped before
            # persisting.
            meta_chunk = meta if i == 0 else dict(meta)
            meta_chunk["_chunk_index"] = i
            # A non-first chunk whose start is NOT a real paragraph/doc boundary is
            # a synthetic mid-paragraph hard-cut: it must NOT anchor a sentence
            # start (see the spaCy loop). Only set the transport flag for such
            # seams so the common case carries no extra key.
            if i > 0 and not is_real_boundary:
                meta_chunk["_synthetic_seam"] = True
            yield (chunk, meta_chunk)

    for row in rows:
        _seen_idx += 1
        if reject_sink is not None:
            reject_sink.seen()
        row_origin_id = _safe_str(row.get("origin_id"))
        source_meta = _safe_meta_dict(row.get("source_meta"))
        source_provenance = _safe_meta_dict(row.get("source_provenance"))
        source_license = _safe_str(row.get("source_license"))
        source = _safe_str(row.get("source")) or _safe_str(source_meta.get("source"))
        doc_id = _safe_str(row.get("doc_id"))
        register = _safe_str(row.get("register")) or _safe_str(source_meta.get("register"))
        split = _safe_str(row.get("split")) or _safe_str(source_meta.get("split"))
        date = _safe_str(row.get("date")) or _safe_str(source_meta.get("date"))
        genre = _safe_str(row.get("genre")) or _safe_str(source_meta.get("genre"))
        input_text = _safe_str(row.get("input_text")) or ""
        if input_text:
            input_text = normalize_text_basic(input_text)
        if require_input_text and not input_text:
            if reject_sink is not None:
                reject_sink.record(
                    _seen_idx, "missing_input_text",
                    {"doc_id": doc_id, "source": source,
                     "variant": _safe_str(row.get("variant"))},
                    fatal=True,
                )
            raise RuntimeError(
                "input_text fehlt. Bitte zuerst Patch-Lauf nutzen und "
                "nur gekuerzte Inputs ins Korpus schreiben. "
                f"doc_id={doc_id} source={source} variant={_safe_str(row.get('variant'))}"
            )
        source_text = input_text or (_safe_str(row.get("source_text")) or "")
        if source_text:
            source_text = normalize_text_basic(source_text)
        target_text = _safe_str(row.get("target_text")) or ""
        if not target_text:
            fallback_text = _safe_str(row.get("text")) or ""
            if fallback_text:
                if not fallback_text_warned:
                    LOGGER.warning("target_text is missing. Using text for the build.")
                    fallback_text_warned = True
                target_text = fallback_text
        if target_text:
            target_text = normalize_text_basic(target_text)
        reference_text = _safe_str(row.get("reference_text")) or ""
        if reference_text:
            reference_text = normalize_text_basic(reference_text)
        row_prompt_text = _safe_str(row.get("prompt_text")) or ""
        if row_prompt_text:
            row_prompt_text = normalize_text_basic(row_prompt_text)
        row_prompt_custom_id = _safe_str(row.get("prompt_custom_id"))
        row_prompt_model = _safe_str(row.get("prompt_model"))
        variant = _safe_str(row.get("variant")) or "unknown"
        model = _safe_str(row.get("model")) or "unknown"
        row_text_type = _safe_str(row.get("text_type"))
        pair_id = _safe_str(row.get("pair_id"))
        step_index = row.get("step_index")

        if not target_text:
            if reject_sink is not None:
                reject_sink.record(
                    _seen_idx, "empty_target_text",
                    {"doc_id": doc_id, "source": source, "variant": variant},
                )
            continue

        text_type = row_text_type
        if not text_type:
            is_human = model in ("human", "human_gold") or variant in (
                "easy_gold",
                "original",
                "source",
                "reference",
            )
            text_type = "human" if is_human else "ai"
        fallback_id = pair_id
        if not fallback_id:
            if reference_text:
                fallback_id = _text_hash(reference_text)
            elif source_text:
                fallback_id = _text_hash(source_text)
        if not fallback_id and not row_origin_id and not doc_id:
            if reject_sink is not None:
                reject_sink.record(
                    _seen_idx, "no_alignment_anchor",
                    {"doc_id": doc_id, "source": source,
                     "variant": variant, "model": model},
                    fatal=True,
                )
            raise RuntimeError(
                "Kein Alignment Anker fuer origin_id. "
                f"doc_id={doc_id} source={source} variant={variant} model={model}"
            )
        origin_id = row_origin_id or _origin_id(source, doc_id, fallback_id)
        ref_text = reference_text
        if variant == "easy_gold" and not ref_text:
            ref_text = target_text
        if not ref_text:
            ref_text = source_text
        # A standalone row (an unpaired document, e.g. from VRT) is one
        # document like a human reference, without a version.
        single_document = text_type in ("human", pairing.STANDALONE)
        if not ref_text and single_document:
            ref_text = target_text
        if not ref_text:
            if reject_sink is not None:
                reject_sink.record(
                    _seen_idx, "no_ref_text",
                    {"doc_id": doc_id, "source": source,
                     "variant": variant, "text_type": text_type},
                )
            continue

        ref_hash = _text_hash(ref_text)
        if source == "simple_german_corpus":
            if variant == "easy_gold" or reference_text:
                ref_kind = "easy_gold"
            else:
                ref_kind = "source"
        else:
            ref_kind = "easy_gold" if variant == "easy_gold" else ("reference" if reference_text else "source")
        ref_key = (origin_id, ref_hash, ref_kind)
        src_doc_idx = human_idx_by_key.get(ref_key)
        base_meta: dict = {
            "origin_id": origin_id,
            "source": source,
            "register": register,
        }
        if doc_id or fallback_id:
            base_meta["origin_doc_id"] = doc_id or fallback_id
        if split:
            base_meta["split"] = split
        if date:
            base_meta["date"] = date
        if genre:
            base_meta["genre"] = genre
        if source_license:
            base_meta["source_license"] = source_license
        _merge_scalar_meta(base_meta, source_meta)
        _merge_scalar_meta(base_meta, source_provenance)

        if src_doc_idx is None and text_type == pairing.STANDALONE:
            # An unpaired document (VRT) keeps its own ID and claims no pair
            # fields, like the documents of a CSV or JSON Lines import.
            standalone_id = doc_id or fallback_id or origin_id
            meta = {
                key: value
                for key, value in base_meta.items()
                if key not in ("origin_id", "origin_doc_id")
            }
            meta.update(
                {
                    "doc_id": standalone_id,
                    "path": standalone_id,
                    "variant": variant or "document",
                    "model": model or "none",
                    "text_type": pairing.STANDALONE,
                }
            )
            src_doc_idx = _add_doc(ref_text, meta, ref_key)
            human_idx_by_key[ref_key] = src_doc_idx
            yield from _emit_text(ref_text, meta)
        elif src_doc_idx is None:
            human_variant = variant if single_document else "original"
            human_model = model if single_document else "human"
            src_doc_id = f"{origin_id}::{ref_kind}::{ref_hash}"
            meta = dict(base_meta)
            meta.update(
                {
                    "doc_id": src_doc_id,
                    "path": src_doc_id,
                    "variant": human_variant,
                    "model": human_model,
                    "text_type": "human",
                    "reference_kind": ref_kind,
                    "reference_hash": ref_hash,
                    "paired_with": [],
                }
            )
            if source_text and ref_text != source_text:
                meta["source_hash_full"] = _text_hash(source_text)
            src_doc_idx = _add_doc(ref_text, meta, ref_key)
            human_idx_by_key[ref_key] = src_doc_idx
            yield from _emit_text(ref_text, meta)

        if single_document:
            continue

        safe_model = model.replace("/", "_").replace(" ", "_")
        step_label = str(step_index) if step_index is not None else "na"
        thinking_text, cleaned_target = _extract_thinking(target_text)
        if thinking_text:
            base_meta.setdefault("thinking_text", thinking_text)
        if not cleaned_target:
            LOGGER.warning(
                "No answer left after removing the thinking part: source=%s variant=%s model=%s doc_id=%s",
                source,
                variant,
                model,
                doc_id,
            )
            if reject_sink is not None:
                reject_sink.record(
                    _seen_idx, "thinking_only_output",
                    {"doc_id": doc_id, "source": source,
                     "variant": variant, "model": model},
                )
            continue
        target_text = cleaned_target
        tgt_hash = _text_hash(target_text)
        tgt_key = (origin_id, variant, safe_model, step_label, tgt_hash)
        tgt_doc_idx = ai_idx_by_key.get(tgt_key)
        if tgt_doc_idx is not None:
            custom_id = _safe_str(row.get("custom_id"))
            if on_duplicate is not None:
                on_duplicate(tgt_key, custom_id)
            continue

        tgt_doc_id = f"{origin_id}::{variant}::{safe_model}::{step_label}::{tgt_hash}"
        prompting_method = (
            _safe_str(row.get("profile_id"))
            or _safe_str(row.get("profile_name"))
            or ("prompt_builder" if row_prompt_custom_id and row_prompt_text else "")
        )
        if not prompting_method:
            if source == "simple_german_corpus":
                prompting_method = "simple_corpus"
            else:
                prompting_method = "direct"

        meta = dict(base_meta)
        meta.update(
            {
                "doc_id": tgt_doc_id,
                "path": tgt_doc_id,
                "variant": variant,
                "model": model,
                "text_type": text_type,
                "pair_id": pair_id,
                "step_index": step_index,
                "ref_doc": src_doc_idx,
                "reference_kind": ref_kind,
                "reference_hash": ref_hash,
                "target_hash": tgt_hash,
                "custom_id": _safe_str(row.get("custom_id")),
                "profile_id": _safe_str(row.get("profile_id")),
                "profile_name": _safe_str(row.get("profile_name")),
                "generated_at": _safe_str(row.get("generated_at")),
                "prompting_method": prompting_method,
            }
        )
        if include_prompts:
            prompt_text = ""
            if source == "simple_german_corpus" and source_text:
                prompt_text = source_text
            elif row_prompt_custom_id and row_prompt_text:
                prompt_text = row_prompt_text
            if prompt_text:
                meta["prompt_text"] = prompt_text
                if row_prompt_custom_id:
                    meta["prompt_custom_id"] = row_prompt_custom_id
                if row_prompt_model:
                    meta["prompt_model"] = row_prompt_model

        tgt_doc_idx = _add_doc(target_text, meta, tgt_key)
        ai_idx_by_key[tgt_key] = tgt_doc_idx
        if on_pair is not None:
            on_pair(ref_key, tgt_key)
        yield from _emit_text(target_text, meta)


def _build_generic_doc_stream(
    rows: Iterable[dict],
    *,
    text_column: str,
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    source: str = "generic",
    on_assign: callable | None = None,
    reject_sink: "RejectSink | None" = None,
    split_long_texts: bool = False,
    max_doc_chars: int = 0,
) -> Iterator[Tuple[str, dict]]:
    """Unaligned/flat corpus stream: one document per row, no human/AI pairing.

    Each row becomes a single standalone document; there is no ``input_text``
    requirement and no alignment anchor. ``source``/``variant``/``model`` are set to
    placeholders so the metadata reader does not reverse-parse ``path`` (see R3.8).
    The same backend (:func:`build_index_from_token_docs`) consumes the result.
    """
    meta_columns = meta_columns or []
    _local_seq = [0]

    def _assign(anchor) -> int:
        if on_assign is not None:
            return int(on_assign(anchor))
        seq = _local_seq[0]
        _local_seq[0] += 1
        return seq

    for i, row in enumerate(rows):
        if reject_sink is not None:
            reject_sink.seen()
        text = _safe_str(row.get(text_column)) or ""
        if not text:
            if reject_sink is not None:
                doc_id_val = _safe_str(row.get(id_column)) if id_column else f"doc-{i}"
                # row_idx is 1-based to match _build_doc_stream's _seen_idx.
                reject_sink.record(
                    i + 1, "empty_text_column",
                    {"row": i + 1, "id_column": id_column, "doc_id": doc_id_val},
                )
            continue
        text = normalize_text_basic(text)
        doc_id = _safe_str(row.get(id_column)) if id_column else ""
        if not doc_id:
            doc_id = f"doc-{i}"
        row_source = _safe_str(row.get("source")) or source
        meta: dict = {
            "doc_id": doc_id,
            "path": doc_id,
            "source": row_source,
            "variant": "document",
            "model": "none",
            "text_type": pairing.STANDALONE,
        }
        for col in meta_columns:
            if col in ("doc_id", "path", "source", "variant", "model", "text_type"):
                continue
            val = _safe_meta_value(row.get(col))
            if val:
                meta[col] = val

        # Oversized standalone docs are split into independent chunk-docs (no
        # pairing to preserve), so an adapter doc beyond spaCy's max_length is
        # chunked instead of crashing the pipeline.
        if split_long_texts and max_doc_chars and len(text) > max_doc_chars:
            chunks = _split_text_chunks(text, max_doc_chars)
        else:
            chunks = [text]
        for ci, chunk in enumerate(chunks):
            chunk_meta = meta if len(chunks) == 1 else dict(meta)
            if len(chunks) > 1:
                chunk_meta["doc_id"] = f"{doc_id}#{ci}"
                chunk_meta["path"] = chunk_meta["doc_id"]
            anchor = ("generic", chunk_meta["doc_id"], i, ci)
            chunk_meta["_anchor"] = anchor
            _assign(anchor)
            yield (chunk, chunk_meta)


_PREALIGNED_RESERVED_META = {
    "doc_id",
    "path",
    "source",
    "variant",
    "model",
    "text_type",
    "pair_id",
    "pair_key",
    "pair_role",
    "pair_axis",
    "ref_doc",
    "paired_with",
}


def _role_key(value: object) -> str:
    """Normalize a pair-role/axis value to a snake_case key.

    None / blank / whitespace-only values normalize to "" so callers can route
    them into the ``missing_pair_role`` reject path instead of crashing.
    """
    value = (_safe_str(value) or "").strip().lower()
    return re.sub(r"\s+", "_", value) if value else ""


def _build_prealigned_doc_stream(
    rows: Iterable[dict],
    *,
    text_column: str,
    id_column: str | None = None,
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    source: str = "prealigned",
    variant_column: str | None = None,
    model_column: str | None = None,
    on_assign: callable | None = None,
    on_pair: callable | None = None,
    reject_sink: "RejectSink | None" = None,
    split_long_texts: bool = False,
    max_doc_chars: int = 0,
) -> Iterator[Tuple[str, dict]]:
    """Pre-aligned doc stream: many rows form one pair group via ``pair_key``.

    The stream accepts arbitrary row order. It materialises rows by pair group,
    emits the anchor role first, then all other roles, and wires them through
    ``PairSink``. This keeps the existing Fast Index contract intact:

    - anchor docs get ``text_type="anchor"`` (``candyconc.core.pairing``)
    - target docs get ``ref_doc=<anchor doc_idx>`` and ``text_type="version"``
    - anchor metadata receives ``paired_with`` during finalisation
    - ``model`` and ``variant`` default to the role from the data, so labels in
      the parallel concordance name the roles of the corpus

    Builds before builder revision 2 stored ``human`` and ``ai`` here and
    ``model="human"`` for anchors. Readers accept both.

    ``pair_order="unsorted"`` buffers all valid rows by pair key. Use
    ``pair_order="grouped"`` (or ``"sorted"``) for large inputs that are already
    contiguous by pair key; then memory is bounded by the largest pair group.
    """
    meta_columns = meta_columns or []
    anchor_role_norm = _role_key(anchor_role)
    if not anchor_role_norm:
        raise RuntimeError("anchor_role fehlt fuer prealigned Import")
    pair_axis_norm = _role_key(pair_axis) or "prealigned"
    pair_order_norm = _role_key(pair_order) or "unsorted"
    if pair_order_norm == "sorted":
        pair_order_norm = "grouped"
    if pair_order_norm not in {"unsorted", "grouped"}:
        raise RuntimeError(
            "Prealigned Import: pair_order muss 'unsorted', 'grouped' oder 'sorted' sein"
        )

    def _reject(row_idx: int, reason: str, context: dict | None = None) -> None:
        if reject_sink is not None:
            reject_sink.record(row_idx, reason, context or {})
            return
        raise RuntimeError(
            f"Prealigned Import: {reason} (row {row_idx}): "
            + json.dumps(context or {}, ensure_ascii=False)
        )

    def _valid_row(row_idx: int, row: dict) -> tuple[str, str] | None:
        text = _safe_str(row.get(text_column)) or ""
        pair_key = _safe_str(row.get(pair_key_column))
        role = _role_key(_safe_str(row.get(pair_role_column)))
        if not text:
            doc_id_val = _safe_str(row.get(id_column)) if id_column else ""
            _reject(row_idx, "empty_text_column", {"doc_id": doc_id_val, "text_column": text_column})
            return None
        if not pair_key:
            doc_id_val = _safe_str(row.get(id_column)) if id_column else ""
            _reject(row_idx, "missing_pair_key", {"doc_id": doc_id_val, "pair_key_column": pair_key_column})
            return None
        if not role:
            doc_id_val = _safe_str(row.get(id_column)) if id_column else ""
            _reject(row_idx, "missing_pair_role", {"doc_id": doc_id_val, "pair_role_column": pair_role_column})
            return None
        return pair_key, role

    emitted_doc_ids: set[str] = set()
    _local_seq = [0]

    def _assign(anchor) -> int:
        if on_assign is not None:
            return int(on_assign(anchor))
        seq = _local_seq[0]
        _local_seq[0] += 1
        return seq

    def _emit_text(text: str, meta: dict) -> Iterator[Tuple[str, dict]]:
        if not split_long_texts or not max_doc_chars or len(text) <= max_doc_chars:
            yield (text, meta)
            return
        chunks = _split_text_chunks_with_boundaries(text, max_doc_chars)
        for i, (chunk, is_real_boundary) in enumerate(chunks):
            meta_chunk = meta if i == 0 else dict(meta)
            meta_chunk["_chunk_index"] = i
            # See _build_doc_stream._emit_text: only a synthetic mid-paragraph
            # hard-cut seam (non-first chunk that is not a real boundary) gets the
            # flag; it must not anchor a sentence start downstream.
            if i > 0 and not is_real_boundary:
                meta_chunk["_synthetic_seam"] = True
            yield (chunk, meta_chunk)

    def _doc_id_for(pair_key: str, role: str, row_idx: int, row: dict) -> str:
        raw = _safe_str(row.get(id_column)) if id_column else ""
        doc_id = raw or f"{pair_key}::{role}"
        if doc_id in emitted_doc_ids:
            doc_id = f"{doc_id}#{row_idx}"
        emitted_doc_ids.add(doc_id)
        return doc_id

    def _meta_for(
        *,
        pair_key: str,
        role: str,
        row_idx: int,
        row: dict,
        ref_doc: int | None,
        anchor: object,
    ) -> dict:
        doc_id = _doc_id_for(pair_key, role, row_idx, row)
        row_source = _safe_str(row.get("source")) or source
        variant = _safe_str(row.get(variant_column)) if variant_column else ""
        model = _safe_str(row.get(model_column)) if model_column else ""
        is_anchor = ref_doc is None
        meta: dict = {
            "doc_id": doc_id,
            "path": doc_id,
            "origin_id": pair_key,
            "pair_id": pair_key,
            "pair_key": pair_key,
            "pair_axis": pair_axis_norm,
            "pair_role": role,
            "source": row_source,
            "variant": variant or role,
            "model": model or role,
            # The side of the pair. The role itself stays in pair_role.
            "text_type": pairing.ANCHOR if is_anchor else pairing.VERSION,
            "_anchor": anchor,
        }
        if is_anchor:
            meta.update({"paired_with": [], "anchor_role": role})
        else:
            meta.update({"ref_doc": int(ref_doc), "anchor_role": anchor_role_norm})
        for col in meta_columns:
            if col in _PREALIGNED_RESERVED_META:
                continue
            val = _safe_meta_value(row.get(col))
            if val:
                meta[col] = val
        return meta

    def _emit_group(
        pair_key: str,
        group_rows: list[tuple[int, dict]],
    ) -> Iterator[Tuple[str, dict]]:
        anchors = [
            (row_idx, row)
            for row_idx, row in group_rows
            if _role_key(_safe_str(row.get(pair_role_column))) == anchor_role_norm
        ]
        if len(anchors) != 1:
            for row_idx, row in group_rows:
                _reject(
                    row_idx,
                    "invalid_anchor_count",
                    {
                        "pair_key": pair_key,
                        "anchor_role": anchor_role_norm,
                        "anchor_count": len(anchors),
                        "doc_id": _safe_str(row.get(id_column)) if id_column else "",
                    },
                )
            return
        if len(group_rows) < 2:
            row_idx, row = anchors[0]
            _reject(
                row_idx,
                "singleton_pair_group",
                {"pair_key": pair_key, "doc_id": _safe_str(row.get(id_column)) if id_column else ""},
            )
            return

        anchor_idx, anchor_row = anchors[0]
        ordered = [(anchor_idx, anchor_row)] + [
            (row_idx, row)
            for row_idx, row in group_rows
            if not (row_idx == anchor_idx and row is anchor_row)
        ]

        anchor_obj = ("prealigned", pair_axis_norm, pair_key, anchor_role_norm)
        ref_doc = _assign(anchor_obj)
        anchor_meta = _meta_for(
            pair_key=pair_key,
            role=anchor_role_norm,
            row_idx=anchor_idx,
            row=anchor_row,
            ref_doc=None,
            anchor=anchor_obj,
        )
        anchor_text = normalize_text_basic(_safe_str(anchor_row.get(text_column)) or "")
        yield from _emit_text(anchor_text, anchor_meta)

        for row_idx, row in ordered[1:]:
            role = _role_key(_safe_str(row.get(pair_role_column)))
            target_anchor = ("prealigned", pair_axis_norm, pair_key, role, row_idx)
            _assign(target_anchor)
            if on_pair is not None:
                on_pair(anchor_obj, target_anchor)
            meta = _meta_for(
                pair_key=pair_key,
                role=role,
                row_idx=row_idx,
                row=row,
                ref_doc=ref_doc,
                anchor=target_anchor,
            )
            text = normalize_text_basic(_safe_str(row.get(text_column)) or "")
            yield from _emit_text(text, meta)

    if pair_order_norm == "unsorted":
        groups: dict[str, list[tuple[int, dict]]] = {}
        for row_idx, row in enumerate(rows, start=1):
            if reject_sink is not None:
                reject_sink.seen()
            valid = _valid_row(row_idx, row)
            if valid is None:
                continue
            pair_key, _role = valid
            groups.setdefault(pair_key, []).append((row_idx, row))

        if not groups:
            raise RuntimeError("Prealigned Import: keine gueltigen Pair-Gruppen gefunden")
        for pair_key, group_rows in groups.items():
            yield from _emit_group(pair_key, group_rows)
        return

    active_key: str | None = None
    active_rows: list[tuple[int, dict]] = []
    closed_keys: set[str] = set()
    saw_valid_row = False

    def _flush_active() -> Iterator[Tuple[str, dict]]:
        nonlocal active_key, active_rows
        if active_key is None:
            return
        closed_keys.add(active_key)
        yield from _emit_group(active_key, active_rows)
        active_key = None
        active_rows = []

    for row_idx, row in enumerate(rows, start=1):
        if reject_sink is not None:
            reject_sink.seen()
        valid = _valid_row(row_idx, row)
        if valid is None:
            continue
        pair_key, _role = valid
        saw_valid_row = True
        if active_key is None:
            if pair_key in closed_keys:
                _reject(
                    row_idx,
                    "non_contiguous_pair_key",
                    {"pair_key": pair_key, "pair_order": "grouped"},
                )
                continue
            active_key = pair_key
        elif pair_key != active_key:
            yield from _flush_active()
            if pair_key in closed_keys:
                _reject(
                    row_idx,
                    "non_contiguous_pair_key",
                    {"pair_key": pair_key, "pair_order": "grouped"},
                )
                continue
            active_key = pair_key
        active_rows.append((row_idx, row))

    yield from _flush_active()
    if not saw_valid_row:
        raise RuntimeError("Prealigned Import: keine gueltigen Pair-Gruppen gefunden")


def _map_id(mapping: Dict[str, int], freqs: List[int], value: str) -> int:
    if not value:
        return 0
    idx = mapping.get(value)
    if idx is None:
        idx = len(mapping) + 1
        mapping[value] = idx
        freqs.append(0)
    freqs[idx] += 1
    return idx


class SpacyModelMissingError(RuntimeError):
    """Fehlendes spaCy-Modell mit nutzerfertiger Meldung.

    Bewusst eine Exception (kein SystemExit): die Row-Builder-Pfade schreiben
    ihren failed-build_report ueber ``except Exception`` — ein SystemExit
    wuerde die Build-Forensik umgehen. Das CLI-main() faengt diesen Typ ab
    und zeigt die Meldung ohne Traceback.
    """


def _load_spacy_pipeline(
    spacy_model: str,
    *,
    disable_ner: bool,
    disable_deps: bool,
    max_doc_chars: int,
    output_path: Path,
    ctx: "BuildContext",
):
    """Load + configure a spaCy pipeline for a frontend. Returns (nlp, ner_enabled, deps_enabled)."""
    import spacy  # lazy: only reached when a real pipeline is needed
    from spacy.language import Language

    if _BLANK_DEFAULTS_COMPONENT not in Language.factories:
        Language.component(_BLANK_DEFAULTS_COMPONENT, func=_candyconc_blank_defaults)

    disable = []
    if disable_ner:
        disable.append("ner")
    if disable_deps:
        disable.append("parser")
    LOGGER.info("Loading spaCy pipeline: %s", spacy_model)
    with _phase("spacy_load", output_path=output_path, ctx=ctx):
        blank_match = re.fullmatch(r"blank:([A-Za-z][A-Za-z_-]*)", str(spacy_model).strip())
        try:
            nlp = spacy.blank(blank_match.group(1).lower()) if blank_match else spacy.load(spacy_model, disable=disable)
        except OSError as exc:
            from candyconc.ingest.pipelines import missing_message

            raise SpacyModelMissingError(missing_message(str(spacy_model))) from exc
        if blank_match and _BLANK_DEFAULTS_COMPONENT not in nlp.pipe_names:
            nlp.add_pipe(_BLANK_DEFAULTS_COMPONENT)
    desired_max = max(1_000_000, max_doc_chars or 0)
    if nlp.max_length < desired_max:
        nlp.max_length = desired_max
        LOGGER.info("spaCy max_length set to %d", nlp.max_length)
    if not disable_ner and "ner" not in nlp.pipe_names:
        raise RuntimeError("The spaCy pipeline has no NER component, but enable_ner is set.")
    if not disable_deps and "parser" not in nlp.pipe_names:
        raise RuntimeError("The spaCy pipeline has no parser, but enable_deps is set.")
    if disable_deps and "parser" not in nlp.pipe_names:
        if "senter" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
    ner_enabled = not disable_ner and "ner" in nlp.pipe_names
    deps_enabled = not disable_deps and "parser" in nlp.pipe_names
    return nlp, ner_enabled, deps_enabled


def _whitespace_origin(capture_whitespace: bool, build_info: dict) -> str:
    """Value of the manifest field ``whitespace`` for one build."""
    if capture_whitespace:
        if str(build_info.get("import_mode") or "") == "vrt":
            return index_format.WHITESPACE_VRT_JOIN
        return index_format.WHITESPACE_TEXT
    declared = str(build_info.get("whitespace") or "")
    return declared or index_format.WHITESPACE_DISABLED


def build_index_from_token_docs(
    token_docs: Iterable[Tuple[str, dict]],
    output_path: Path,
    *,
    nlp,
    ner_enabled: bool,
    deps_enabled: bool,
    batch_size: int,
    n_process: int,
    pair_sink: "PairSink",
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    build_gemma_embeddings: bool = False,
    export_gemma_texts: bool = False,
    export_gemma_sentences: bool = True,
    capture_whitespace: bool = True,
    build_sentence_embeddings: bool = False,
    keep_tmp: bool = False,
    keep_meta_jsonl: bool = False,
    gemma_endpoint: str | None = None,
    gemma_model: str | None = None,
    gemma_batch: int = 32,
    gemma_timeout: float = 120.0,
    build_info: dict | None = None,
    ctx: "BuildContext | None" = None,
) -> None:
    """Index a stream of ``(text, meta)`` documents into a Fast Index.

    The format-specific frontend (e.g. :func:`build_fast_index_from_parquet`) owns
    reading the source, the doc-stream / alignment and loading the spaCy pipeline.
    This backend owns tokenization via the supplied ``nlp``, id-mapping, every
    binary writer, pairing resolution (via ``pair_sink``) and finalization.
    ``build_info`` carries frontend-owned manifest fields (source, model, …) that
    are merged into ``index_build_meta.json``.
    """
    ctx = ctx if ctx is not None else BuildContext()
    build_info = build_info or {}
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _configure_logging(output_path, None)
    # Only the Parquet command line runs a preflight (see main). The adapter
    # imports check their input while reading, so a missing preflight is not
    # a warning here.
    _cleanup_partial_output(output_path)

    raw_word = output_path / "word_ids.raw"
    raw_lemma = output_path / "lemma_ids.raw"
    raw_pos = output_path / "pos_ids.raw"
    raw_morph = output_path / "morph_ids.raw"
    raw_ent = output_path / "ent_ids.raw"
    raw_rel = output_path / "rel_ids.raw"
    raw_head = output_path / "head_ids.raw"
    raw_ws = output_path / "whitespace_after.raw"

    for p in [raw_word, raw_lemma, raw_pos, raw_morph, raw_ent, raw_rel, raw_head, raw_ws]:
        if p.exists():
            p.unlink()

    word_writer = IdWriter(raw_word, "I")
    lemma_writer = IdWriter(raw_lemma, "I")
    pos_writer = IdWriter(raw_pos, "I")
    morph_writer = IdWriter(raw_morph, "I")
    ent_writer = IdWriter(raw_ent, "I")
    rel_writer = IdWriter(raw_rel, "I")
    head_writer = IdWriter(raw_head, "i")
    # One uint8 flag per token, set when spaCy reports trailing whitespace
    # in the normalized source. --no-capture-whitespace disables capture.
    ws_writer = IdWriter(raw_ws, "B") if capture_whitespace else None

    word_id_by_orth: Dict[int, int] = {}
    lemma_id_by_value: Dict[int, int] = {}
    pos_id_by_value: Dict[int, int] = {}
    ent_id_by_value: Dict[int, int] = {}
    rel_id_by_value: Dict[int, int] = {}
    morph_to_id: Dict[str, int] = {}

    word_str_by_id: List[str] = [""]
    lemma_str_by_id: List[str] = [""]
    pos_str_by_id: List[str] = [""]
    ent_str_by_id: List[str] = [""]
    rel_str_by_id: List[str] = [""]

    word_freqs: List[int] = [0]
    lemma_freqs: List[int] = [0]
    pos_freqs: List[int] = [0]
    morph_freqs: List[int] = [0]
    ent_freqs: List[int] = [0]
    rel_freqs: List[int] = [0]

    doc_bounds: List[int] = []
    sent_bounds: List[int] = [0]
    meta_jsonl_path = output_path / "doc_metadata.jsonl"
    meta_jsonl_fh = meta_jsonl_path.open("w", encoding="utf-8")
    paired_tmp_path = output_path / "paired_with.tmp"
    paired_tmp_fh = paired_tmp_path.open("w", encoding="utf-8")

    if batch_size <= 0:
        available = _available_memory_bytes()
        batch_size = _auto_batch_size(available)
        LOGGER.info("Auto batch_size: %d", batch_size)
    if n_process <= 0:
        n_process = _auto_n_process(batch_size)
        LOGGER.info("Auto n_process: %d", n_process)

    embed_vecs_raw = output_path / "passage_vecs.tmp.bin"
    embed_texts_tmp = output_path / "passage_texts.tmp.jsonl"
    embed_vecs_fh = None
    embed_texts_fh = None
    embed_dim = 0
    embed_count = 0
    embed_sample_chunks: List[np.ndarray] = []
    embed_sample_count = 0
    current_embed_idx: int | None = None
    current_embed_sum: np.ndarray | None = None
    current_embed_count = 0

    def _flush_embed() -> None:
        nonlocal current_embed_idx, current_embed_sum, current_embed_count
        nonlocal embed_dim, embed_count, embed_sample_count
        if not build_embeddings:
            return
        if current_embed_idx is None or current_embed_sum is None:
            return
        if current_embed_count <= 0:
            raise RuntimeError("Embedding Aggregation ist leer")
        vec = current_embed_sum / float(current_embed_count)
        vec = vec.astype(np.float32, copy=False)
        if embed_dim == 0:
            embed_dim = int(vec.shape[0])
        if embed_vecs_fh is not None:
            embed_vecs_fh.write(vec.tobytes())
        embed_count += 1
        if embed_sample_count < _EMB_SAMPLE_MAX:
            need = _EMB_SAMPLE_MAX - embed_sample_count
            if need > 0:
                embed_sample_chunks.append(vec[:].copy())
                embed_sample_count += 1
        current_embed_idx = None
        current_embed_sum = None
        current_embed_count = 0

    if build_embeddings:
        if nlp.vocab.vectors_length == 0:
            raise RuntimeError("The spaCy pipeline has no vectors. Use a pipeline with vectors.")
        try:
            import faiss  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("faiss is missing for the embedding build") from exc
        faiss_mode = os.environ.get("CANDYCONC_FAISS_MODE", "auto").lower()
        if os.environ.get("CANDYCONC_FAISS_SAFE", "0") == "1":
            faiss_mode = "flat"
        if faiss_mode == "auto":
            faiss_mode = "flat" if sys.platform == "darwin" else "ivf"
        if (
            faiss_mode == "ivf"
            and sys.platform == "darwin"
            and os.environ.get("CANDYCONC_FAISS_ALLOW_IVF_DARWIN", "0") != "1"
        ):
            LOGGER.warning(
                "FAISS IVF is off on macOS (stability). Using Flat. "
                "Set CANDYCONC_FAISS_ALLOW_IVF_DARWIN=1 to force IVF."
            )
            faiss_mode = "flat"
        LOGGER.info("FAISS mode (passage/word): %s", faiss_mode)
        faiss_threads = os.environ.get("CANDYCONC_FAISS_THREADS")
        if not faiss_threads and sys.platform == "darwin":
            faiss_threads = "1"
        if faiss_threads:
            try:
                faiss.omp_set_num_threads(int(faiss_threads))
            except Exception:
                pass
        if build_word_faiss is None:
            build_word_faiss = os.environ.get("CANDYCONC_BUILD_WORD_FAISS", "1") != "0"
        embed_vecs_fh = embed_vecs_raw.open("wb")
        embed_texts_fh = embed_texts_tmp.open("w", encoding="utf-8")

    # STEP 9 (opt-in re-ingest): per-sentence mean spaCy vectors keyed by the
    # sentence's global token start_pos. Stored RAW on disk (sentence_vecs.npy,
    # consistent with passage_vecs.npy / the FAISS convention — normalization is
    # query-side, see server._embed_pair_cost which is norm-invariant cosine).
    sent_vec_tmp = output_path / "sentence_vecs.tmp.bin"
    sent_vec_fh = None
    sent_vec_dim = 0
    sent_vec_count = 0
    sent_vec_starts: List[int] = []
    if build_sentence_embeddings:
        if nlp.vocab.vectors_length == 0:
            raise RuntimeError(
                "The spaCy pipeline has no vectors. Sentence embeddings "
                "(--build-sentence-embeddings) need a pipeline with vectors."
            )
        sent_vec_fh = sent_vec_tmp.open("wb")

    gemma_doc_tmp_fh = None
    gemma_sent_tmp_fh = None
    gemma_doc_tmp = output_path / "gemma_doc_texts.jsonl"
    gemma_sent_tmp = output_path / "gemma_sentence_texts.jsonl"
    gemma_doc_count = 0
    gemma_sent_count = 0
    gemma_sent_counter = 0

    build_gemma_texts = build_gemma_embeddings or export_gemma_texts
    if build_gemma_texts:
        if not gemma_endpoint:
            gemma_endpoint = _config_get(
                "CANDYCONC_GEMMA_EMB_ENDPOINT", "http://127.0.0.1:1234/v1/embeddings"
            )
        if not gemma_model:
            gemma_model = _config_get(
                "CANDYCONC_GEMMA_EMB_MODEL", "google/embedding-gemma-300m"
            )
        if gemma_batch <= 0:
            gemma_batch = int(_config_get("CANDYCONC_GEMMA_EMB_BATCH", "32") or 32)
        if gemma_timeout <= 0:
            gemma_timeout = float(_config_get("CANDYCONC_GEMMA_EMB_TIMEOUT", "120") or 120)
        if build_gemma_embeddings:
            try:
                import faiss  # type: ignore
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("faiss is missing for the Gemma embedding build") from exc
            faiss_mode_gemma = os.environ.get("CANDYCONC_FAISS_MODE", "auto").lower()
            if os.environ.get("CANDYCONC_FAISS_SAFE", "0") == "1":
                faiss_mode_gemma = "flat"
            if faiss_mode_gemma == "auto":
                faiss_mode_gemma = "flat" if sys.platform == "darwin" else "ivf"
            if (
                faiss_mode_gemma == "ivf"
                and sys.platform == "darwin"
                and os.environ.get("CANDYCONC_FAISS_ALLOW_IVF_DARWIN", "0") != "1"
            ):
                LOGGER.warning(
                    "FAISS IVF is off on macOS (stability). Using Flat. "
                    "Set CANDYCONC_FAISS_ALLOW_IVF_DARWIN=1 to force IVF."
                )
                faiss_mode_gemma = "flat"
            LOGGER.info("FAISS mode (gemma): %s", faiss_mode_gemma)
            faiss_threads = os.environ.get("CANDYCONC_FAISS_THREADS")
            if not faiss_threads and sys.platform == "darwin":
                faiss_threads = "1"
            if faiss_threads:
                try:
                    faiss.omp_set_num_threads(int(faiss_threads))
                except Exception:
                    pass
        gemma_doc_tmp_fh = gemma_doc_tmp.open("w", encoding="utf-8")
        if export_gemma_sentences:
            gemma_sent_tmp_fh = gemma_sent_tmp.open("w", encoding="utf-8")

    token_cursor = 0
    doc_idx = 0
    # Bounded warning counter for synthetic mid-paragraph chunk seams (list so the
    # nested loop body can mutate it without a `nonlocal`/global).
    synthetic_seam_warned = [0]
    # Cross-chunk sentence-continuation state for synthetic-seam handling. A
    # synthetic mid-paragraph WHITESPACE hard-cut is a real sentence boundary ONLY
    # if the *previous* chunk of the same document ended a sentence — i.e. its last
    # token is a sentence terminator. spaCy's sentencizer marks token-0 of the next
    # chunk as a sentence start iff the prior token is in ``punct_chars``; we read
    # that set from the pipeline so the test mirrors the runtime exactly. When no
    # sentencizer is present (e.g. a parser provides SENT_START), the across-seam
    # boundary is unknowable per-chunk, so we keep the legacy "anchor every seam"
    # behaviour by treating ``_seam_punct_chars`` as None.
    _seam_punct_chars: set | None = None
    for _pipe_name in ("sentencizer", "senter"):
        if _pipe_name in nlp.pipe_names:
            _pc = getattr(nlp.get_pipe(_pipe_name), "punct_chars", None)
            if _pc:
                _seam_punct_chars = set(_pc)
            break
    # Mutable holders (loop body can update without nonlocal): whether the previous
    # chunk of the current document ended with a sentence terminator.
    prev_chunk_ended_sentence = [False]
    from spacy import attrs  # lazy: this spaCy-Doc indexing path requires spaCy
    strings = nlp.vocab.strings
    attr_list = [attrs.ORTH, attrs.LEMMA, attrs.POS, attrs.MORPH, attrs.SENT_START]
    if deps_enabled:
        attr_list.extend([attrs.DEP, attrs.HEAD])
    if ner_enabled:
        attr_list.append(attrs.ENT_TYPE)
    if capture_whitespace:
        # attrs.SPACY is spaCy's boolean "token is followed by whitespace".
        attr_list.append(attrs.SPACY)
    attr_index = {attr: idx for idx, attr in enumerate(attr_list)}
    morph_tag_cache: Dict[Tuple[int, int], str] = {}

    def _map_vocab_ids(
        values: np.ndarray,
        mapping: Dict[int, int],
        id_to_str: List[str],
        freqs: List[int],
        string_store,
    ) -> np.ndarray:
        if values.size == 0:
            return np.zeros(0, dtype=np.uint32)
        uniq, inv = np.unique(values, return_inverse=True)
        counts = np.bincount(inv, minlength=uniq.size)
        mapped = np.zeros(uniq.size, dtype=np.uint32)
        for i, raw in enumerate(uniq):
            key = int(raw)
            if key == 0:
                mapped[i] = 0
                continue
            idx = mapping.get(key)
            if idx is None:
                idx = len(id_to_str)
                mapping[key] = idx
                id_to_str.append(string_store[key])
                freqs.append(0)
            mapped[i] = idx
            freqs[idx] += int(counts[i])
        return mapped[inv].astype(np.uint32, copy=False)

    def _map_morph_ids(pos_ids: np.ndarray, morph_values: np.ndarray) -> np.ndarray:
        if pos_ids.size == 0:
            return np.zeros(0, dtype=np.uint32)
        # spaCy morph keys are uint64 hashes. A signed dtype turns every key
        # from 2**63 upwards negative (about half of all feature sets,
        # "Number=Sing" among them), so the pairs stay unsigned.
        pairs = np.empty((pos_ids.size, 2), dtype=np.uint64)
        pairs[:, 0] = pos_ids.astype(np.uint64, copy=False)
        pairs[:, 1] = morph_values.astype(np.uint64, copy=False)
        uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        counts = np.bincount(inv, minlength=uniq.shape[0])
        mapped = np.zeros(uniq.shape[0], dtype=np.uint32)
        for i in range(uniq.shape[0]):
            pid_val = int(uniq[i, 0])
            morph_key = int(uniq[i, 1])
            if pid_val == 0 and morph_key == 0:
                mapped[i] = 0
                continue
            tag = morph_tag_cache.get((pid_val, morph_key))
            if tag is None:
                pos_tag_str = pos_str_by_id[pid_val] if pid_val < len(pos_str_by_id) else ""
                if morph_key:
                    morph_val = strings[morph_key]
                    tag = f"{pos_tag_str}|{morph_val}" if pos_tag_str else morph_val
                else:
                    tag = pos_tag_str
                morph_tag_cache[(pid_val, morph_key)] = tag
            if tag:
                mid = morph_to_id.get(tag)
                if mid is None:
                    mid = len(morph_to_id) + 1
                    morph_to_id[tag] = mid
                    morph_freqs.append(0)
                morph_freqs[mid] += int(counts[i])
                mapped[i] = mid
        return mapped[inv].astype(np.uint32, copy=False)

    doc_ids_seen: set[str] = set()
    with _phase("spacy_pipe", output_path=output_path, ctx=ctx):
        for doc, meta in nlp.pipe(token_docs, as_tuples=True, batch_size=batch_size, n_process=n_process):
            chunk_index = int(meta.pop("_chunk_index", 0)) if isinstance(meta, dict) else 0
            # A synthetic seam marks a non-first chunk that begins at a
            # content-arbitrary mid-paragraph WHITESPACE hard-cut (not a real
            # sentence/paragraph boundary). Such a seam must NOT anchor a sentence
            # start, or it inflates sentence_count and fragments within(<s>).
            synthetic_seam = bool(meta.pop("_synthetic_seam", False)) if isinstance(meta, dict) else False
            anchor = meta.pop("_anchor", None) if isinstance(meta, dict) else None
            doc_key = None
            if isinstance(meta, dict):
                doc_key = meta.get("doc_id") or meta.get("path") or meta.get("origin_id")
            if chunk_index == 0:
                doc_start = token_cursor
                doc_len = len(doc)
                doc_bounds.append(doc_start)
                # New document: there is no preceding chunk, so reset the
                # across-seam continuation state.
                prev_chunk_ended_sentence[0] = False
                if doc_key:
                    doc_ids_seen.add(doc_key)
                if isinstance(meta, dict):
                    leaked = [k for k in meta if isinstance(k, str) and k.startswith("_")]
                    if leaked:
                        raise RuntimeError(
                            f"Private Transport-Keys gelangen in doc_metadata: {leaked}"
                        )
                meta_jsonl_fh.write(json.dumps({"doc_idx": int(doc_idx), "meta": meta}))
                meta_jsonl_fh.write("\n")
                if build_embeddings:
                    _flush_embed()
                    current_embed_idx = doc_idx
                    current_embed_sum = np.asarray(doc.vector, dtype=np.float32)
                    current_embed_count = 1
                    if embedding_text_max > 0:
                        text_snip = doc.text
                        if len(text_snip) > embedding_text_max:
                            text_snip = text_snip[:embedding_text_max]
                        if embed_texts_fh is not None:
                            embed_texts_fh.write(json.dumps(text_snip))
                            embed_texts_fh.write("\n")
                if build_gemma_texts:
                    doc_text = doc.text
                    if embedding_text_max > 0 and len(doc_text) > embedding_text_max:
                        doc_text = doc_text[:embedding_text_max]
                    if gemma_doc_tmp_fh is not None:
                        payload = {"text": doc_text, "doc_id": int(doc_idx)}
                        gemma_doc_tmp_fh.write(json.dumps(payload))
                        gemma_doc_tmp_fh.write("\n")
                    gemma_doc_count += 1
                pair_sink.bind(anchor, doc_idx)
                doc_idx += 1
            else:
                doc_start = token_cursor
                doc_len = len(doc)
                if doc_key and doc_key not in doc_ids_seen:
                    raise RuntimeError(f"Chunk ohne bekanntes doc_id: {doc_key}")
                if build_embeddings:
                    if current_embed_sum is None:
                        raise RuntimeError("Embedding Aggregation ohne Startchunk")
                    current_embed_sum += np.asarray(doc.vector, dtype=np.float32)
                    current_embed_count += 1
            if build_gemma_texts:
                current_doc_id = doc_idx - 1
                if export_gemma_sentences:
                    for sent in doc.sents:
                        sent_text = sent.text.strip()
                        if not sent_text:
                            continue
                        if embedding_text_max > 0 and len(sent_text) > embedding_text_max:
                            sent_text = sent_text[:embedding_text_max]
                        if gemma_sent_tmp_fh is not None:
                            payload = {
                                "text": sent_text,
                                "doc_id": int(current_doc_id),
                                "sent_id": int(gemma_sent_counter),
                            }
                            gemma_sent_tmp_fh.write(json.dumps(payload))
                            gemma_sent_tmp_fh.write("\n")
                        gemma_sent_counter += 1
                        gemma_sent_count += 1

            arr = doc.to_array(attr_list)
            orths = arr[:, attr_index[attrs.ORTH]]
            lemmas_arr = arr[:, attr_index[attrs.LEMMA]]
            pos_arr = arr[:, attr_index[attrs.POS]]
            morph_arr = arr[:, attr_index[attrs.MORPH]]
            sent_start_arr = arr[:, attr_index[attrs.SENT_START]]
            dep_arr = arr[:, attr_index[attrs.DEP]] if deps_enabled else None
            head_arr = arr[:, attr_index[attrs.HEAD]] if deps_enabled else None
            ent_arr = arr[:, attr_index[attrs.ENT_TYPE]] if ner_enabled else None

            word_ids_np = _map_vocab_ids(orths, word_id_by_orth, word_str_by_id, word_freqs, strings)
            lemma_ids_np = _map_vocab_ids(lemmas_arr, lemma_id_by_value, lemma_str_by_id, lemma_freqs, strings)
            pos_ids_np = _map_vocab_ids(pos_arr, pos_id_by_value, pos_str_by_id, pos_freqs, strings)
            morph_ids_np = _map_morph_ids(pos_ids_np, morph_arr)

            if deps_enabled and dep_arr is not None and head_arr is not None:
                rel_ids_np = _map_vocab_ids(dep_arr, rel_id_by_value, rel_str_by_id, rel_freqs, strings)
                head_offsets = head_arr.astype(np.int64, copy=False)
                abs_head = head_offsets + np.arange(doc_len, dtype=np.int64)
                valid = (abs_head >= 0) & (abs_head < doc_len)
                head_global = np.where(valid, doc_start + abs_head, -1)
                # Safe to cast: enforce_scaling_limits() (called after this loop,
                # before any index file is written) aborts the build if
                # token_count >= MAX_I32, so every valid head position written to
                # disk fits in int32 and cannot alias the -1 sentinel.
                # FORMAT_NOTE(R6): widen head_ids.bin to int64 if the MAX_I32
                # ceiling is ever lifted (sentinel -> INT64_MIN).
                head_ids_np = head_global.astype(np.int32, copy=False)
            else:
                rel_ids_np = np.zeros(doc_len, dtype=np.uint32)
                head_ids_np = np.full(doc_len, -1, dtype=np.int32)

            if ner_enabled and ent_arr is not None:
                ent_ids_np = _map_vocab_ids(ent_arr, ent_id_by_value, ent_str_by_id, ent_freqs, strings)
            else:
                ent_ids_np = np.zeros(doc_len, dtype=np.uint32)

            # Every document/chunk begins a new sentence at its first token
            # (doc_start). spaCy emits SENT_START==1 at the chunk-relative
            # position 0, so the previous code dropped that first sentence by
            # slicing sent_indices[1:] — losing the first sentence of every doc
            # (and at every chunk seam), which under-counts sentence_count and
            # breaks within(<s>) for the opening sentence of each document. We
            # explicitly anchor doc_start as a sentence start, then append the
            # interior sentence starts. (sent_bounds is deduped/validated at
            # finalization, so re-emitting doc_start==0 for the first doc is
            # harmless.)
            #
            # EXCEPTION (C-builder-runner-parity-1): when this chunk begins at a
            # synthetic mid-paragraph WHITESPACE hard-cut (synthetic_seam) — a
            # boundary the chunker invented only to honour --max-doc-chars, not a
            # real sentence/paragraph break — anchoring doc_start UNCONDITIONALLY
            # would inflate sentence_count and fragment within(<s>) at a
            # non-boundary. spaCy re-tokenizes each chunk independently and always
            # marks the chunk's token 0 as a sentence start, so that flag alone
            # cannot tell a genuine sentence boundary (the previous chunk really
            # ended a sentence) from a continuation (the sentence spans the seam).
            # We resolve it with the same rule the sentencizer uses across the
            # seam: token 0 of this chunk is a real sentence start iff the previous
            # chunk's last token was a sentence terminator (``prev_chunk_ended_
            # sentence``). When no sentencizer set is available we cannot decide
            # per-chunk, so we keep the legacy "anchor every seam" behaviour.
            sent_indices = np.flatnonzero(sent_start_arr == 1)
            if synthetic_seam:
                seam_is_real_boundary = (
                    _seam_punct_chars is None or prev_chunk_ended_sentence[0]
                )
                if seam_is_real_boundary:
                    sent_bounds.append(doc_start)
                elif synthetic_seam_warned[0] < 5:
                    LOGGER.warning(
                        "Chunk seam is not a real sentence start. "
                        "No sentence anchor at doc_start=%d (doc_idx=%d, chunk=%d).",
                        doc_start, doc_idx, chunk_index,
                    )
                    synthetic_seam_warned[0] += 1
                # Drop spaCy's chunk-relative-0 start (already handled above) and
                # append only the genuine interior sentence starts.
                interior = sent_indices[1:] if (sent_indices.size > 0 and int(sent_indices[0]) == 0) else sent_indices
                for idx in interior:
                    sent_bounds.append(doc_start + int(idx))
            else:
                sent_bounds.append(doc_start)
                if sent_indices.size > 0:
                    # Skip the chunk-relative 0 start (already added as doc_start);
                    # append the remaining interior sentence starts. Guard against a
                    # pipeline that does not annotate position 0 as a sentence start
                    # by only dropping a leading zero.
                    interior = sent_indices[1:] if int(sent_indices[0]) == 0 else sent_indices
                    for idx in interior:
                        sent_bounds.append(doc_start + int(idx))

            # Record whether THIS chunk ends a sentence, for the NEXT chunk's seam
            # decision: the across-seam sentence start is real iff this chunk's
            # last token is a sentence terminator. Only meaningful when a
            # sentencizer punct set is known and the chunk has tokens.
            if _seam_punct_chars is not None and doc_len > 0:
                prev_chunk_ended_sentence[0] = doc[doc_len - 1].text in _seam_punct_chars

            if build_sentence_embeddings and doc_len > 0:
                # Keyed exactly like the runtime sentence starts
                # (_sentence_bounds_for_doc): interior SENT_START positions plus
                # the doc/chunk start itself (sent.start == 0 for the first
                # sentence). Pipelines without sentence annotation fall back to
                # one whole-doc sentence — matching the runtime fallback that
                # inserts doc_start as the only sentence start.
                if doc.has_annotation("SENT_START"):
                    sent_spans = list(doc.sents)
                else:
                    sent_spans = [doc[:]]
                for sent_span in sent_spans:
                    vec = np.asarray(sent_span.vector, dtype=np.float32)
                    if sent_vec_dim == 0:
                        sent_vec_dim = int(vec.shape[0])
                    if sent_vec_fh is not None:
                        sent_vec_fh.write(vec.tobytes())
                    sent_vec_starts.append(doc_start + int(sent_span.start))
                    sent_vec_count += 1

            word_writer.extend(word_ids_np)
            lemma_writer.extend(lemma_ids_np)
            pos_writer.extend(pos_ids_np)
            morph_writer.extend(morph_ids_np)
            ent_writer.extend(ent_ids_np)
            rel_writer.extend(rel_ids_np)
            head_writer.extend(head_ids_np)
            if ws_writer is not None:
                ws_flags = arr[:, attr_index[attrs.SPACY]].astype(np.uint8, copy=False)
                ws_writer.extend(ws_flags.tolist())

            token_cursor += doc_len
            if doc_idx % 200 == 0 and doc_idx:
                LOGGER.info("Docs %d, Tokens %d", doc_idx, token_cursor)

    if doc_idx <= 0:
        raise RuntimeError("Keine Dokumente im Input (nach Filter/require_input_text).")

    if gemma_doc_tmp_fh is not None:
        gemma_doc_tmp_fh.close()
    if gemma_sent_tmp_fh is not None:
        gemma_sent_tmp_fh.close()
    if build_gemma_texts:
        gemma_meta = {
            "created_at": _utc_now(),
            "doc_jsonl": gemma_doc_tmp.name,
            "doc_count": int(gemma_doc_count),
            "sent_jsonl": gemma_sent_tmp.name if export_gemma_sentences else None,
            "sent_count": int(gemma_sent_count),
            "export_sentences": bool(export_gemma_sentences),
            "embedding_text_max": int(embedding_text_max),
            "model": str(gemma_model),
            "endpoint": str(gemma_endpoint),
        }
        _write_json(output_path / "gemma_texts_meta.json", gemma_meta)
    # embed files are closed after the final _flush_embed in the embedding phase

    for writer in [word_writer, lemma_writer, pos_writer, morph_writer, ent_writer, rel_writer, head_writer]:
        writer.close()
    if ws_writer is not None:
        ws_writer.close()
    if sent_vec_fh is not None:
        sent_vec_fh.flush()
        sent_vec_fh.close()
        sent_vec_fh = None

    token_count = token_cursor
    LOGGER.info("Tokens total: %d", token_count)

    # Scaling guard (R6): fail fast before any int32 narrowing in the writers or
    # the query engine. No-op for any corpus within the safe range, so the
    # existing aligned path stays byte-identical.
    index_format.enforce_scaling_limits(
        token_count=token_count,
        context=str(output_path),
    )

    def _mapping_from_id_to_str(id_to_str: List[str]) -> Dict[str, int]:
        return {s: i for i, s in enumerate(id_to_str) if i and s}

    def _freq_dict(freqs: List[int]) -> Dict[int, int]:
        return {i: v for i, v in enumerate(freqs) if i and v}

    doc_bounds_sorted = list(doc_bounds)
    if not doc_bounds_sorted:
        doc_bounds_sorted = [0]
    if doc_bounds_sorted[0] != 0:
        doc_bounds_sorted = [0] + doc_bounds_sorted
    if any(b < a for a, b in zip(doc_bounds_sorted, doc_bounds_sorted[1:])):
        raise RuntimeError("Dokumentgrenzen nicht monoton steigend, Abbruch wegen inkonsistenter Indizes")

    # Sentence starts are emitted per document (doc_start + interior starts) and
    # may repeat doc_start==0 for the first document, so sort + dedup before the
    # monotonicity guard. Duplicates would otherwise create zero-length sentence
    # units; sorting tolerates any per-doc emission order.
    sent_bounds_sorted = sorted(set(int(b) for b in sent_bounds))
    if not sent_bounds_sorted:
        sent_bounds_sorted = [0]
    if sent_bounds_sorted[0] != 0:
        sent_bounds_sorted = [0] + sent_bounds_sorted
    if any(b <= a for a, b in zip(sent_bounds_sorted, sent_bounds_sorted[1:])):
        raise RuntimeError("Satzgrenzen nicht monoton steigend, Abbruch wegen inkonsistenter Indizes")
    sentence_count = max(len(sent_bounds_sorted) - 1, 0)

    # Invariant: every sentence start lies inside exactly one document span, and
    # every document start is itself a sentence start (each doc opens a new
    # sentence). This catches a regression of the per-doc seam fix above (a
    # dropped doc-start sentence, or a sentence leaking past token_count). Both
    # arrays are sorted/monotonic with a leading 0, so a set-subset check is
    # sufficient and O(n).
    if token_count > 0:
        sent_start_set = set(sent_bounds_sorted)
        missing_doc_starts = [d for d in doc_bounds_sorted if d not in sent_start_set]
        if missing_doc_starts:
            raise RuntimeError(
                "Dokumentstart ist keine Satzgrenze (verlorener erster Satz): "
                f"{missing_doc_starts[:5]}. Bitte Fast Index neu bauen."
            )
        if int(sent_bounds_sorted[-1]) >= int(token_count):
            raise RuntimeError(
                f"Satzgrenze {sent_bounds_sorted[-1]:,} liegt ausserhalb des Korpus "
                f"(token_count={token_count:,}). Bitte Fast Index neu bauen."
            )

    if doc_bounds_sorted and int(doc_bounds_sorted[-1]) > index_format.MAX_U32:
        raise RuntimeError(
            f"doc_start {doc_bounds_sorted[-1]:,} ueberschreitet uint32 "
            f"(MAX_U32={index_format.MAX_U32:,}). Teile das Korpus in kleinere Dateien auf."
        )
    with _phase("bounds_write", output_path=output_path, ctx=ctx):
        doc_starts_arr = np.array(doc_bounds_sorted, dtype=np.uint32)
        sent_starts_arr = np.array(sent_bounds_sorted, dtype=np.uint32)
        _write_array(output_path / "document_bounds.bin", doc_starts_arr)
        _write_array(output_path / "sentence_bounds.bin", sent_starts_arr)

        with open(output_path / "meta.bin", "wb") as f:
            f.write(np.uint64(token_count).tobytes())

    def _memmap_u32(path: Path) -> np.ndarray:
        size = path.stat().st_size // 4
        return np.memmap(path, dtype=np.uint32, mode="r", shape=(int(size),))

    def _memmap_i32(path: Path) -> np.ndarray:
        size = path.stat().st_size // 4
        return np.memmap(path, dtype=np.int32, mode="r", shape=(int(size),))

    word_ids = _memmap_u32(raw_word)
    lemma_ids = _memmap_u32(raw_lemma)
    pos_ids = _memmap_u32(raw_pos)
    morph_ids = _memmap_u32(raw_morph)
    ent_ids = _memmap_u32(raw_ent)
    rel_ids = _memmap_u32(raw_rel)
    head_ids = _memmap_i32(raw_head)

    with _phase("svb_streams", output_path=output_path, ctx=ctx):
        _write_svb_stream(output_path / "word_ids", word_ids, SVB_BLOCK_SIZE)
        _write_svb_stream(output_path / "lemma_ids", lemma_ids, SVB_BLOCK_SIZE)
        _write_array(output_path / "pos_ids.bin", pos_ids.astype(np.uint32, copy=False))
        _write_array(output_path / "morph_ids.bin", morph_ids.astype(np.uint32, copy=False))
        _write_array(output_path / "ent_ids.bin", ent_ids.astype(np.uint32, copy=False))
        _write_array(output_path / "rel_ids.bin", rel_ids.astype(np.uint32, copy=False))
        _write_array(output_path / "head_ids.bin", head_ids.astype(np.int32, copy=False))
        if capture_whitespace:
            # Count-prefixed uint8 sidecar with exactly one flag per token.
            ws_size = raw_ws.stat().st_size if raw_ws.exists() else 0
            if ws_size != token_count:
                raise RuntimeError(
                    f"whitespace_after Sidecar inkonsistent: {ws_size} Flags "
                    f"fuer {token_count} Tokens."
                )
            ws_arr = (
                np.memmap(raw_ws, dtype=np.uint8, mode="r", shape=(int(ws_size),))
                if ws_size
                else np.zeros(0, dtype=np.uint8)
            )
            _write_array(output_path / "whitespace_after.bin", ws_arr)

    word_to_id = _mapping_from_id_to_str(word_str_by_id)
    lemma_to_id = _mapping_from_id_to_str(lemma_str_by_id)
    pos_to_id = _mapping_from_id_to_str(pos_str_by_id)
    ent_to_id = _mapping_from_id_to_str(ent_str_by_id)
    rel_to_id = _mapping_from_id_to_str(rel_str_by_id)

    word_freqs_dict = _freq_dict(word_freqs)
    lemma_freqs_dict = _freq_dict(lemma_freqs)
    pos_freqs_dict = _freq_dict(pos_freqs)
    morph_freqs_dict = _freq_dict(morph_freqs)
    ent_freqs_dict = _freq_dict(ent_freqs)
    rel_freqs_dict = _freq_dict(rel_freqs)

    LOGGER.info("Writing lexicons")
    with _phase("lexicons", output_path=output_path, ctx=ctx):
        _write_lexicon_bin(output_path / "word_lexicon.bin", word_to_id, word_freqs_dict)
        _write_lexicon_bin(output_path / "lemma_lexicon.bin", lemma_to_id, lemma_freqs_dict)
        _write_lexicon_bin(output_path / "pos_lexicon.bin", pos_to_id, pos_freqs_dict)
        _write_lexicon_bin(output_path / "morph_lexicon.bin", morph_to_id, morph_freqs_dict)
        if ent_to_id:
            _write_lexicon_bin(output_path / "ent_lexicon.bin", ent_to_id, ent_freqs_dict)
        if rel_to_id:
            _write_lexicon_bin(output_path / "rel_lexicon.bin", rel_to_id, rel_freqs_dict)

        _write_hash_index(output_path / "word_lexicon.bin", word_to_id)
        _write_hash_index(output_path / "lemma_lexicon.bin", lemma_to_id)
        _write_hash_index(output_path / "pos_lexicon.bin", pos_to_id)
        _write_hash_index(output_path / "morph_lexicon.bin", morph_to_id)
        if ent_to_id:
            _write_hash_index(output_path / "ent_lexicon.bin", ent_to_id)
        if rel_to_id:
            _write_hash_index(output_path / "rel_lexicon.bin", rel_to_id)

    LOGGER.info("Prefix Top")
    with _phase("prefix_top", output_path=output_path, ctx=ctx):
        word_id_to_str = word_str_by_id
        _write_prefix_top(
            output_path / "word_lexicon.prefix.bin",
            word_id_to_str,
            word_freqs_dict,
            PREFIX_LEN,
            PREFIX_TOP_K,
            PREFIX_TOP_GLOBAL,
        )
        if lemma_to_id:
            lemma_id_to_str = lemma_str_by_id
            _write_prefix_top(
                output_path / "lemma_lexicon.prefix.bin",
                lemma_id_to_str,
                lemma_freqs_dict,
                PREFIX_LEN,
                PREFIX_TOP_K,
                PREFIX_TOP_GLOBAL,
            )
        if pos_to_id:
            pos_id_to_str = pos_str_by_id
            _write_prefix_top(
                output_path / "pos_lexicon.prefix.bin",
                pos_id_to_str,
                pos_freqs_dict,
                PREFIX_LEN,
                PREFIX_TOP_K,
                PREFIX_TOP_GLOBAL,
            )

    LOGGER.info("Prefix/Ngram Index")
    with _phase("prefix_ngram", output_path=output_path, ctx=ctx):
        _write_prefix_all_index(output_path, "word", word_str_by_id, PREFIX_ALL_LEN)
        if lemma_to_id:
            _write_prefix_all_index(output_path, "lemma", lemma_str_by_id, PREFIX_ALL_LEN)
        _write_ngram_index(output_path, "word", word_str_by_id, NGRAM_LEN)
        if lemma_to_id:
            _write_ngram_index(output_path, "lemma", lemma_str_by_id, NGRAM_LEN)

    LOGGER.info("Document set indexes")

    word_vocab_size = len(word_str_by_id) - 1
    lemma_vocab_size = len(lemma_str_by_id) - 1
    pos_vocab_size = len(pos_str_by_id) - 1
    morph_vocab_size = len(morph_to_id)
    ent_vocab_size = len(ent_str_by_id) - 1
    rel_vocab_size = len(rel_str_by_id) - 1

    with _phase("docsets", output_path=output_path, ctx=ctx):
        word_doc_ptr, word_doc_ids = _build_unit_sets_from_bounds(
            word_ids, doc_starts_arr, token_count, word_vocab_size, skip_zero=True
        )
        _write_array(output_path / "word_docset.ptr.bin", word_doc_ptr)
        _write_array(output_path / "word_docset.bin", word_doc_ids)
        if lemma_vocab_size and np.any(lemma_ids):
            lemma_doc_ptr, lemma_doc_ids = _build_unit_sets_from_bounds(
                lemma_ids, doc_starts_arr, token_count, lemma_vocab_size, skip_zero=True
            )
            _write_array(output_path / "lemma_docset.ptr.bin", lemma_doc_ptr)
            _write_array(output_path / "lemma_docset.bin", lemma_doc_ids)
        if pos_vocab_size and np.any(pos_ids):
            pos_doc_ptr, pos_doc_ids = _build_unit_sets_from_bounds(
                pos_ids, doc_starts_arr, token_count, pos_vocab_size, skip_zero=True
            )
            _write_array(output_path / "pos_docset.ptr.bin", pos_doc_ptr)
            _write_array(output_path / "pos_docset.bin", pos_doc_ids)

    LOGGER.info("POS sentence indexes")
    with _phase("sentence_docsets", output_path=output_path, ctx=ctx):
        if pos_vocab_size and np.any(pos_ids):
            pos_sent_ptr, pos_sent_ids = _build_unit_sets_from_bounds(
                pos_ids, sent_starts_arr, token_count, pos_vocab_size, skip_zero=True
            )
            _write_array(output_path / "pos_sentence.ptr.bin", pos_sent_ptr)
            _write_array(output_path / "pos_sentence.bin", pos_sent_ids)

    LOGGER.info("Block Top")
    with _phase("block_top", output_path=output_path, ctx=ctx):
        word_blk_ptr, word_blk_ids, word_blk_cnt, word_blk_tot = _build_block_top(
            word_ids, BLOCK_TOP_SIZE, BLOCK_TOP_K, skip_zero=True
        )
        _write_block_top(
            output_path,
            "word",
            word_blk_ptr,
            word_blk_ids,
            word_blk_cnt,
            word_blk_tot,
            BLOCK_TOP_SIZE,
            BLOCK_TOP_K,
        )
        if lemma_vocab_size and np.any(lemma_ids):
            lemma_blk_ptr, lemma_blk_ids, lemma_blk_cnt, lemma_blk_tot = _build_block_top(
                lemma_ids, BLOCK_TOP_SIZE, BLOCK_TOP_K, skip_zero=True
            )
            _write_block_top(
                output_path,
                "lemma",
                lemma_blk_ptr,
                lemma_blk_ids,
                lemma_blk_cnt,
                lemma_blk_tot,
                BLOCK_TOP_SIZE,
                BLOCK_TOP_K,
            )

    LOGGER.info("Postings")
    with _phase("postings", output_path=output_path, ctx=ctx):
        _write_roaring_postings(output_path, word_ids, word_vocab_size, name="word")
        if lemma_vocab_size and np.any(lemma_ids):
            _write_roaring_postings(output_path, lemma_ids, lemma_vocab_size, name="lemma", skip_zero=True)
        if pos_vocab_size and np.any(pos_ids):
            _write_roaring_postings(output_path, pos_ids, pos_vocab_size, name="pos", skip_zero=True)
        if morph_vocab_size and np.any(morph_ids):
            _write_roaring_postings(output_path, morph_ids, morph_vocab_size, name="morph", skip_zero=True)
        if ent_vocab_size and np.any(ent_ids):
            _write_roaring_postings(output_path, ent_ids, ent_vocab_size, name="ent", skip_zero=True)
        if rel_vocab_size and np.any(rel_ids):
            _write_roaring_postings(output_path, rel_ids, rel_vocab_size, name="rel", skip_zero=True)

    LOGGER.info("Dense Bitsets")
    with _phase("dense_bitsets", output_path=output_path, ctx=ctx):
        _write_dense_bitsets(output_path, "word", word_ids, word_freqs, token_count)
        if lemma_vocab_size and np.any(lemma_ids):
            _write_dense_bitsets(output_path, "lemma", lemma_ids, lemma_freqs, token_count)
        if pos_vocab_size and np.any(pos_ids):
            _write_dense_bitsets(output_path, "pos", pos_ids, pos_freqs, token_count)
        if ent_vocab_size and np.any(ent_ids):
            _write_dense_bitsets(output_path, "ent", ent_ids, ent_freqs, token_count)
        if rel_vocab_size and np.any(rel_ids):
            _write_dense_bitsets(output_path, "rel", rel_ids, rel_freqs, token_count)

    # Backend owns doc_idx: every assigned logical document must have been bound by
    # the engine (i.e. emitted and consumed). A mismatch means a frontend/engine desync.
    if pair_sink.n_bound != pair_sink.n_assigned:
        raise RuntimeError(
            f"doc_idx Desync: {pair_sink.n_assigned} Dokumente zugewiesen, "
            f"aber {pair_sink.n_bound} gebunden."
        )
    # Materialize pairs (logical anchors -> bound doc_idx) for the downstream passes.
    for human_idx, ai_idx in pair_sink.resolve_pairs():
        paired_tmp_fh.write(f"{human_idx}\t{ai_idx}\n")

    paired_tmp_fh.flush()
    paired_tmp_fh.close()
    meta_jsonl_fh.flush()
    meta_jsonl_fh.close()

    if meta_index_fields:
        meta_filtered_path = output_path / "doc_metadata.filtered.jsonl"
        with meta_jsonl_path.open("r", encoding="utf-8") as src, meta_filtered_path.open(
            "w", encoding="utf-8"
        ) as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                meta = obj.get("meta")
                if not isinstance(meta, dict):
                    continue
                filtered = {k: v for k, v in meta.items() if k in meta_index_fields}
                dst.write(json.dumps({"doc_idx": obj.get("doc_idx"), "meta": filtered}))
                dst.write("\n")
        meta_index_source = meta_filtered_path
    else:
        meta_index_source = meta_jsonl_path

    try:
        with _phase("meta_index", output_path=output_path, ctx=ctx):
            _build_meta_index_from_jsonl(meta_index_source, output_path, int(len(doc_bounds_sorted)))
        LOGGER.info("Metadata index built")
    except Exception as exc:
        raise RuntimeError(f"Meta Index Build fehlgeschlagen: {exc}") from exc

    # Build paired_with index (memory-light).
    with _phase("paired_with", output_path=output_path, ctx=ctx):
        doc_count = int(len(doc_bounds_sorted))
        paired_counts = np.zeros((doc_count,), dtype=np.uint32)
        if paired_tmp_path.exists():
            with paired_tmp_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) != 2:
                        continue
                    try:
                        human_idx = int(parts[0])
                    except Exception:
                        continue
                    if 0 <= human_idx < doc_count:
                        paired_counts[human_idx] += 1
        paired_offsets = np.zeros((doc_count + 1,), dtype=np.uint64)
        if doc_count > 0:
            paired_offsets[1:] = np.cumsum(paired_counts, dtype=np.uint64)
        paired_total = int(paired_offsets[-1]) if doc_count else 0
        paired_ids_path = output_path / "paired_with.ids.tmp"
        paired_ids = np.memmap(paired_ids_path, dtype=np.uint32, mode="w+", shape=(paired_total,))
        paired_cursor = paired_offsets.copy()
        if paired_tmp_path.exists() and paired_total > 0:
            with paired_tmp_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) != 2:
                        continue
                    try:
                        human_idx = int(parts[0])
                        ai_idx = int(parts[1])
                    except Exception:
                        continue
                    if human_idx < 0 or human_idx >= doc_count:
                        continue
                    pos = int(paired_cursor[human_idx])
                    paired_ids[pos] = int(ai_idx)
                    paired_cursor[human_idx] = pos + 1
        paired_ids.flush()

    # Build doc_metadata mmap (avoid large in-memory dict).
    with _phase("doc_metadata_mmap", output_path=output_path, ctx=ctx):
        offsets = np.zeros((doc_count + 1,), dtype=np.uint64)
        blob_tmp = output_path / "doc_metadata.mmap.tmp"
        blob_size = 0
        crc_path = output_path / "doc_metadata.crc.bin"
        crc_arr = np.zeros((doc_count,), dtype=np.uint32)
        duplicate_counts = pair_sink.resolve_duplicates()
        with blob_tmp.open("wb") as blob_f:
            last_doc = -1
            for doc_id, meta in _iter_meta_jsonl(meta_jsonl_path):
                if doc_id < 0 or doc_id >= doc_count:
                    raise RuntimeError(
                        f"doc_metadata.jsonl doc_idx {doc_id} ausserhalb [0,{doc_count}) — "
                        "Frontend/Engine doc_idx Desync."
                    )
                while last_doc + 1 < doc_id:
                    offsets[last_doc + 1] = blob_size
                    last_doc += 1
                if doc_id in duplicate_counts:
                    meta["duplicate_count"] = int(duplicate_counts[doc_id])
                if pairing.is_anchor(meta.get("text_type")):
                    start = int(paired_offsets[doc_id])
                    end = int(paired_offsets[doc_id + 1])
                    if end > start:
                        meta["paired_with"] = [int(x) for x in paired_ids[start:end]]
                payload = json.dumps(meta, ensure_ascii=False)
                data = payload.encode("utf-8")
                crc = zlib.crc32(data)
                crc_arr[doc_id] = int(crc)
                offsets[doc_id] = blob_size
                header = index_format.DOC_META_FRAME_MAGIC + struct.pack("<II", int(len(data)), int(crc))
                blob_f.write(header)
                blob_f.write(data)
                blob_size += len(header) + len(data)
                last_doc = doc_id
            while last_doc + 1 < doc_count:
                offsets[last_doc + 1] = blob_size
                last_doc += 1
            offsets[doc_count] = blob_size

        _write_array(output_path / "doc_metadata.idx.bin", offsets.astype(np.uint64, copy=False))
        _write_array(crc_path, crc_arr.astype(np.uint32, copy=False))
        blob_tmp.replace(output_path / "doc_metadata.mmap")
    with _phase("cleanup", output_path=output_path, ctx=ctx):
        if paired_tmp_path.exists():
            paired_tmp_path.unlink(missing_ok=True)
        if paired_ids_path.exists():
            paired_ids_path.unlink(missing_ok=True)
        if not keep_meta_jsonl and os.environ.get("CANDYCONC_KEEP_META_JSONL", "0") == "0":
            if meta_jsonl_path.exists():
                meta_jsonl_path.unlink(missing_ok=True)

        for p in [raw_word, raw_lemma, raw_pos, raw_morph, raw_ent, raw_rel, raw_head, raw_ws]:
            if p.exists():
                p.unlink()

    if build_embeddings:
        with _phase("embeddings_spacy", output_path=output_path, ctx=ctx):
            _flush_embed()
            if embed_vecs_fh is not None:
                embed_vecs_fh.flush()
                embed_vecs_fh.close()
                embed_vecs_fh = None
            if embed_texts_fh is not None:
                embed_texts_fh.flush()
                embed_texts_fh.close()
                embed_texts_fh = None
            if embed_count <= 0 or embed_dim <= 0:
                raise RuntimeError("Keine Embeddings erzeugt")

            vec_path = output_path / "passage_vecs.npy"
            raw_vecs = np.memmap(embed_vecs_raw, dtype=np.float32, mode="r", shape=(embed_count, embed_dim))
            vecs_mem = np.lib.format.open_memmap(
                vec_path, mode="w+", dtype=np.float32, shape=(embed_count, embed_dim)
            )
            for start in range(0, embed_count, _EMB_ADD_BATCH):
                end = min(embed_count, start + _EMB_ADD_BATCH)
                vecs_mem[start:end] = raw_vecs[start:end]
            vecs_mem.flush()

            texts_path = output_path / "passage_texts.json"
            _jsonl_to_json_array(embed_texts_tmp, texts_path)

            sample = np.vstack(embed_sample_chunks) if embed_sample_chunks else None
            nlist = max(1, min(256, int(math.sqrt(embed_count))))
            if faiss_mode == "flat" or sample is None or sample.shape[0] < nlist:
                index = faiss.IndexFlatIP(embed_dim)
            else:
                quantizer = faiss.IndexFlatIP(embed_dim)
                index = faiss.IndexIVFFlat(quantizer, embed_dim, nlist, faiss.METRIC_INNER_PRODUCT)
                # Inner-product == cosine only on L2-normalized vectors; train on a
                # normalized COPY so cluster centroids match the normalized adds below.
                train_sample = np.ascontiguousarray(sample, dtype=np.float32).copy()
                faiss.normalize_L2(train_sample)
                index.train(train_sample)
            for start in range(0, embed_count, _EMB_ADD_BATCH):
                end = min(embed_count, start + _EMB_ADD_BATCH)
                # Normalize a writable copy per batch — the on-disk passage_vecs.npy
                # memmap stays RAW (consistent with services/semantic/index_utils.py);
                # without this, IndexFlatIP ranks by length-biased dot product and the
                # query-side normalization alone cannot fix the ranking.
                batch = np.ascontiguousarray(vecs_mem[start:end], dtype=np.float32).copy()
                faiss.normalize_L2(batch)
                index.add(batch)
            faiss.write_index(index, str(output_path / "faiss_passage.index"))

            embedding_meta = {
                "backend": "spacy",
                "spacy_model": build_info.get("spacy_model"),
                "dim": int(embed_dim),
                "doc_count": int(embed_count),
            }

            if build_word_faiss:
                word_vecs_raw = output_path / "word_vecs.tmp.bin"
                word_ids_raw = output_path / "word_ids.tmp.bin"
                word_vecs_fh = word_vecs_raw.open("wb")
                word_ids_fh = word_ids_raw.open("wb")
                word_dim = 0
                word_count = 0
                word_sample_chunks: List[np.ndarray] = []
                word_sample_count = 0
                vocab = nlp.vocab
                for wid, token in enumerate(word_str_by_id):
                    if wid == 0 or not token:
                        continue
                    if not vocab.has_vector(token):
                        continue
                    vec = vocab.get_vector(token)
                    if vec is None or not np.any(vec):
                        continue
                    vec = np.asarray(vec, dtype=np.float32)
                    norm = float(np.linalg.norm(vec))
                    if norm == 0.0:
                        continue
                    vec = vec / norm
                    if word_dim == 0:
                        word_dim = int(vec.shape[0])
                    word_vecs_fh.write(vec.tobytes())
                    word_ids_fh.write(np.asarray([int(wid)], dtype=np.uint32).tobytes())
                    word_count += 1
                    if word_sample_count < _EMB_SAMPLE_MAX:
                        word_sample_chunks.append(vec.copy())
                        word_sample_count += 1
                word_vecs_fh.close()
                word_ids_fh.close()
                if word_count > 0 and word_dim > 0:
                    word_vecs_mem = np.memmap(
                        word_vecs_raw, dtype=np.float32, mode="r", shape=(word_count, word_dim)
                    )
                    word_ids_mem = np.memmap(word_ids_raw, dtype=np.uint32, mode="r", shape=(word_count,))
                    word_ids_out = np.lib.format.open_memmap(
                        output_path / "word_ids.npy", mode="w+", dtype=np.uint32, shape=(word_count,)
                    )
                    for start in range(0, word_count, _EMB_ADD_BATCH):
                        end = min(word_count, start + _EMB_ADD_BATCH)
                        word_ids_out[start:end] = word_ids_mem[start:end]
                    word_ids_out.flush()

                    word_sample = np.vstack(word_sample_chunks) if word_sample_chunks else None
                    wnlist = max(1, min(4096, int(math.sqrt(word_count))))
                    if faiss_mode == "flat" or word_sample is None or word_sample.shape[0] < wnlist:
                        windex = faiss.IndexFlatIP(word_dim)
                    else:
                        wquant = faiss.IndexFlatIP(word_dim)
                        windex = faiss.IndexIVFFlat(wquant, word_dim, wnlist, faiss.METRIC_INNER_PRODUCT)
                        windex.train(word_sample)
                    for start in range(0, word_count, _EMB_ADD_BATCH):
                        end = min(word_count, start + _EMB_ADD_BATCH)
                        windex.add(np.asarray(word_vecs_mem[start:end], dtype=np.float32))
                    faiss.write_index(windex, str(output_path / "faiss_word.index"))
                    embedding_meta["word_index"] = {
                        "count": int(word_count),
                        "dim": int(word_dim),
                        "normalized": True,
                    }
                else:
                    LOGGER.warning("No word vectors for the word FAISS index. Skipping it.")

                if not keep_tmp:
                    if word_vecs_raw.exists():
                        word_vecs_raw.unlink()
                    if word_ids_raw.exists():
                        word_ids_raw.unlink()

            meta_path = output_path / "embedding_meta.json"
            meta_path.write_text(json.dumps(embedding_meta), "utf-8")

            if not keep_tmp:
                if embed_vecs_raw.exists():
                    embed_vecs_raw.unlink()
                if embed_texts_tmp.exists():
                    embed_texts_tmp.unlink()

    if build_gemma_embeddings:
        from candyconc.services.remote_embeddings import embed_remote

        if gemma_doc_count <= 0:
            raise RuntimeError("Keine Texte fuer Gemma-Embeddings")

        def _build_gemma_index(
            *,
            label: str,
            tmp_path: Path,
            texts_path: Path,
            vecs_path: Path,
            index_path: Path,
            total_count: int,
            nlist_cap: int,
        ) -> tuple[int, int]:
            LOGGER.info("Building Gemma embeddings (%s): %d entries", label, total_count)
            writer = _JsonArrayWriter(texts_path)
            vecs_mem: np.memmap | None = None
            dim = 0
            cursor = 0
            sample_limit = min(_GEMMA_SAMPLE_MAX, total_count)
            sample_chunks: List[np.ndarray] = []
            sample_count = 0

            for batch in _iter_jsonl_batches(tmp_path, int(gemma_batch)):
                texts: List[str] = []
                for item in batch:
                    if isinstance(item, dict):
                        texts.append(str(item.get("text") or ""))
                    else:
                        texts.append(str(item))
                if not texts:
                    continue
                vecs = embed_remote(
                    texts,
                    endpoint=str(gemma_endpoint),
                    model=str(gemma_model),
                    batch_size=int(gemma_batch),
                    timeout=float(gemma_timeout),
                )
                if vecs.size == 0:
                    continue
                if int(vecs.shape[0]) != len(texts):
                    raise RuntimeError(
                        f"Gemma {label} Batch Groesse passt nicht: texts={len(texts)} vecs={int(vecs.shape[0])}"
                    )
                vecs = vecs.astype(np.float32, copy=False)
                norms = np.linalg.norm(vecs, axis=1, keepdims=True)
                norms[norms == 0.0] = 1.0
                vecs = vecs / norms
                if vecs_mem is None:
                    dim = int(vecs.shape[1])
                    vecs_mem = np.lib.format.open_memmap(
                        vecs_path, mode="w+", dtype=np.float32, shape=(total_count, dim)
                    )
                end = cursor + int(vecs.shape[0])
                if end > total_count:
                    raise RuntimeError(
                        f"Gemma {label} ueberlaeuft Ziel: cursor={cursor} batch={int(vecs.shape[0])} total={total_count}"
                    )
                vecs_mem[cursor:end] = vecs
                cursor = end
                for item in batch:
                    writer.append(item)
                if sample_limit > 0 and sample_count < sample_limit:
                    need = sample_limit - sample_count
                    if need > 0:
                        sample_part = vecs[:need].copy()
                        sample_chunks.append(sample_part)
                        sample_count += int(sample_part.shape[0])

            writer.close()
            if vecs_mem is None or dim <= 0 or cursor <= 0:
                raise RuntimeError(f"Gemma {label} Embeddings leer")
            if cursor != total_count:
                raise RuntimeError(
                    f"Gemma {label} Embedding Count mismatch: {cursor} != {total_count}"
                )
            vecs_mem.flush()

            sample = np.vstack(sample_chunks) if sample_chunks else None
            nlist = max(1, min(int(nlist_cap), int(math.sqrt(cursor))))
            if faiss_mode_gemma == "flat" or sample is None or sample.shape[0] < nlist:
                index = faiss.IndexFlatIP(dim)
            else:
                quant = faiss.IndexFlatIP(dim)
                index = faiss.IndexIVFFlat(quant, dim, nlist, faiss.METRIC_INNER_PRODUCT)
                index.train(sample)

            for start in range(0, cursor, _GEMMA_ADD_BATCH):
                end = min(cursor, start + _GEMMA_ADD_BATCH)
                index.add(np.asarray(vecs_mem[start:end], dtype=np.float32))

            faiss.write_index(index, str(index_path))
            return dim, cursor

        with _phase("embeddings_gemma", output_path=output_path, ctx=ctx):
            doc_dim, doc_count = _build_gemma_index(
                label="Docs",
                tmp_path=gemma_doc_tmp,
                texts_path=output_path / "gemma_doc_texts.json",
                vecs_path=output_path / "gemma_doc_vecs.npy",
                index_path=output_path / "faiss_gemma_doc.index",
                total_count=int(gemma_doc_count),
                nlist_cap=4096,
            )

            sent_dim = 0
            sent_count = 0
            if gemma_sent_count > 0:
                sent_dim, sent_count = _build_gemma_index(
                    label="Satz",
                    tmp_path=gemma_sent_tmp,
                    texts_path=output_path / "gemma_sentence_texts.json",
                    vecs_path=output_path / "gemma_sentence_vecs.npy",
                    index_path=output_path / "faiss_gemma_sentence.index",
                    total_count=int(gemma_sent_count),
                    nlist_cap=8192,
                )

            meta_path = output_path / "embedding_meta.json"
            meta: dict = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text("utf-8"))
                except Exception:
                    meta = {}
            meta["gemma_doc"] = {
                "model": str(gemma_model),
                "endpoint": str(gemma_endpoint),
                "dim": int(doc_dim),
                "count": int(doc_count),
                "normalized": True,
            }
            if sent_count:
                meta["gemma_sentence"] = {
                    "model": str(gemma_model),
                    "endpoint": str(gemma_endpoint),
                    "dim": int(sent_dim),
                    "count": int(sent_count),
                    "normalized": True,
                }
            meta_path.write_text(json.dumps(meta), "utf-8")

            if not keep_tmp and not export_gemma_texts:
                if gemma_doc_tmp.exists():
                    gemma_doc_tmp.unlink()
                if gemma_sent_tmp.exists():
                    gemma_sent_tmp.unlink()

    if build_sentence_embeddings:
        # STEP 9 artifacts (contract: server._load_sentence_vectors):
        #   sentence_vecs.npy        (N, d) float32, RAW (un-normalized) vectors
        #   sentence_vec_starts.npy  (N,)   int64 global token start_pos per sentence
        with _phase("sentence_embeddings", output_path=output_path, ctx=ctx):
            if sent_vec_count <= 0 or sent_vec_dim <= 0:
                raise RuntimeError("Keine Satz-Embeddings erzeugt")
            raw_vecs = np.memmap(
                sent_vec_tmp, dtype=np.float32, mode="r", shape=(sent_vec_count, sent_vec_dim)
            )
            vecs_out = np.lib.format.open_memmap(
                output_path / "sentence_vecs.npy",
                mode="w+",
                dtype=np.float32,
                shape=(sent_vec_count, sent_vec_dim),
            )
            for start in range(0, sent_vec_count, _EMB_ADD_BATCH):
                end = min(sent_vec_count, start + _EMB_ADD_BATCH)
                vecs_out[start:end] = raw_vecs[start:end]
            vecs_out.flush()
            np.save(
                output_path / "sentence_vec_starts.npy",
                np.asarray(sent_vec_starts, dtype=np.int64),
            )
            if not keep_tmp and sent_vec_tmp.exists():
                sent_vec_tmp.unlink()
            LOGGER.info(
                "Sentence embeddings: %d sentences, dim=%d", sent_vec_count, sent_vec_dim
            )

    build_meta = {
        "created_at": _utc_now(),
        "source_parquet": build_info.get("source_parquet"),
        "spacy_model": build_info.get("spacy_model"),
        "ner_enabled": bool(ner_enabled),
        "deps_enabled": bool(deps_enabled),
        "batch_size": int(batch_size),
        "n_process": int(n_process),
        "split_long_texts": build_info.get("split_long_texts"),
        "max_doc_chars": build_info.get("max_doc_chars"),
        "include_prompts": build_info.get("include_prompts"),
        "require_input_text": build_info.get("require_input_text"),
        "pair_order": build_info.get("pair_order"),
        "embedding_text_max": int(embedding_text_max),
        "text_normalization": "basic_nfkc_whitespace",
        "doc_count": int(doc_idx),
        "sentence_count": int(sentence_count),
        "token_count": int(token_count),
        "build_embeddings": bool(build_embeddings),
        "build_word_faiss": bool(build_word_faiss) if build_embeddings else False,
        "build_gemma_embeddings": bool(build_gemma_embeddings),
        "export_gemma_texts": bool(export_gemma_texts),
        "export_gemma_sentences": bool(export_gemma_sentences),
    }
    if ctx.preflight is not None:
        build_meta["preflight"] = {
            "ok": bool(ctx.preflight.get("ok")),
            "warnings": ctx.preflight.get("warnings", []),
            "errors": ctx.preflight.get("errors", []),
        }
    build_meta["build_report"] = "build_report.json"
    source_archive_sha256 = str(
        build_info.get("source_archive_sha256", "") or ""
    ).removeprefix("sha256:")
    if source_archive_sha256:
        if not re.fullmatch(r"[0-9a-f]{64}", source_archive_sha256):
            raise ValueError("source_archive_sha256 must be a lowercase SHA-256 digest")
        build_meta["source_archive_sha256"] = source_archive_sha256
    # Origin of the spacing (index_format.WHITESPACE_*): the text itself, the
    # text a VRT import rebuilt from its tokens, or none (switched off, or a
    # pre-tokenized input that a frontend declares through build_info).
    whitespace_origin = _whitespace_origin(capture_whitespace, build_info)
    build_meta["capture_whitespace"] = bool(capture_whitespace)
    build_meta["whitespace"] = whitespace_origin
    # Opt-in re-ingest features (STEP 9): keys appear only when the feature
    # was enabled.
    if build_sentence_embeddings:
        build_meta["build_sentence_embeddings"] = True
        build_meta["sentence_embedding_dim"] = int(sent_vec_dim)
        build_meta["sentence_embedding_count"] = int(sent_vec_count)
    if build_gemma_texts:
        build_meta["gemma_texts"] = {
            "doc_jsonl": gemma_doc_tmp.name,
            "doc_count": int(gemma_doc_count),
            "sent_jsonl": gemma_sent_tmp.name if export_gemma_sentences else None,
            "sent_count": int(gemma_sent_count),
            "model": str(gemma_model),
            "endpoint": str(gemma_endpoint),
        }
    # Reject/coverage reporting (R3.12). Opt-in: only when a sink is attached, so
    # the default path leaves index_build_meta.json (and reject_report.json absence)
    # byte-identical.
    if ctx.reject_sink is not None:
        ctx.reject_sink.flush(output_path)
        build_meta["reject_summary"] = ctx.reject_sink.summary()
    _write_json(output_path / "index_build_meta.json", build_meta)

    # Index manifest (R5): the authoritative capability + provenance descriptor,
    # written LAST and atomically so a crashed build never leaves a manifest
    # claiming complete=True. This is a NEW sidecar file — it touches none of the
    # binary artifacts, so the aligned path stays byte-identical.
    paired = bool(pair_sink is not None and getattr(pair_sink, "_pairs", None))
    import_mode = build_info.get("import_mode") or "unknown"
    manifest = index_format.IndexManifest(
        manifest_version=index_format.MANIFEST_VERSION,
        import_mode=str(import_mode),
        paired=paired,
        pair_axes=list(build_info.get("pair_axes", ["human_ai"] if paired else [])),
        annotation_source=str(build_info.get("annotation_source",
                                             "spacy" if nlp is not None else "unknown")),
        capabilities=index_format.capabilities_from_files(output_path),
        dtypes={"token_positions": "uint32", "term_ids": "uint32", "head_ids": "int32"},
        build_fingerprint=hashlib.sha256(
            json.dumps(
                {
                    "doc_count": int(doc_idx),
                    "token_count": int(token_count),
                    "spacy_model": build_info.get("spacy_model"),
                    "ner_enabled": bool(ner_enabled),
                    "deps_enabled": bool(deps_enabled),
                    "text_normalization": "basic_nfkc_whitespace",
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
        created_at=build_meta["created_at"],
        complete=True,
        builder_revision=index_format.BUILDER_REVISION,
        whitespace=whitespace_origin,
    )
    if nlp is not None:
        from candyconc.ingest.pipelines import pipeline_label

        manifest.language = str(getattr(nlp, "lang", "") or "")
        manifest.annotation_pipeline, manifest.annotation_pipeline_version = pipeline_label(
            build_info.get("spacy_model"), nlp
        )
        vocab = getattr(nlp, "vocab", None)
        manifest.pipeline_vectors = int(getattr(vocab, "vectors_length", 0) or 0)
    _write_json_atomic(output_path / index_format.MANIFEST_FILENAME, manifest.to_dict())

    LOGGER.info("Done: %s", output_path)


def build_fast_index_from_parquet(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str,
    batch_size: int,
    n_process: int,
    disable_ner: bool,
    disable_deps: bool,
    split_long_texts: bool,
    max_doc_chars: int,
    include_prompts: bool,
    require_input_text: bool,
    source_archive_sha256: str | None = None,
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    build_gemma_embeddings: bool = False,
    export_gemma_texts: bool = False,
    export_gemma_sentences: bool = True,
    capture_whitespace: bool = True,
    build_sentence_embeddings: bool = False,
    keep_tmp: bool = False,
    keep_meta_jsonl: bool = False,
    gemma_endpoint: str | None = None,
    gemma_model: str | None = None,
    gemma_batch: int = 32,
    gemma_timeout: float = 120.0,
    import_mode: str = index_format.PAIRED_PARQUET_IMPORT_MODE,
    ctx: "BuildContext | None" = None,
) -> None:
    """Parquet frontend: read rows, derive the aligned (text, meta) doc-stream and
    load spaCy, then delegate indexing to :func:`build_index_from_token_docs`.

    ``import_mode`` is recorded in the manifest. The VRT importer passes ``vrt``
    when it converts a VRT file to this layout for spaCy re-tokenization.
    """
    ctx = ctx if ctx is not None else BuildContext()
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _configure_logging(output_path, None)

    # Resolve batch/process counts here: they drive both parquet row reading and the
    # spaCy pipe below.
    if batch_size <= 0:
        batch_size = _auto_batch_size(_available_memory_bytes())
        LOGGER.info("Auto batch_size: %d", batch_size)
    if n_process <= 0:
        n_process = _auto_n_process(batch_size)
        LOGGER.info("Auto n_process: %d", n_process)

    # Load + configure the spaCy pipeline (the model lives in the frontend; the
    # backend receives the ready pipeline and the resolved attribute flags).
    try:
        nlp, ner_enabled, deps_enabled = _load_spacy_pipeline(
            spacy_model,
            disable_ner=disable_ner,
            disable_deps=disable_deps,
            max_doc_chars=max_doc_chars,
            output_path=output_path,
            ctx=ctx,
        )
    except Exception as exc:
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise

    columns = [
        "origin_id",
        "custom_id",
        "doc_id",
        "register",
        "source",
        "source_meta",
        "source_provenance",
        "source_license",
        "split",
        "date",
        "genre",
        "input_text",
        "source_text",
        "target_text",
        "text",
        "prompt_text",
        "prompt_custom_id",
        "prompt_model",
        "model",
        "variant",
        "text_type",
        "pair_id",
        "reference_text",
        "profile_id",
        "profile_name",
        "generated_at",
        "step_index",
    ]
    pair_sink = PairSink()
    if ctx.reject_sink is not None:
        ctx.reject_sink.open_log()
    row_iter = _iter_parquet_rows(input_path, columns, batch_size=batch_size)
    doc_iter = _build_doc_stream(
        row_iter,
        include_prompts=include_prompts,
        split_long_texts=split_long_texts,
        max_doc_chars=max_doc_chars,
        require_input_text=require_input_text,
        on_pair=pair_sink.on_pair,
        on_duplicate=pair_sink.on_duplicate,
        on_assign=pair_sink.assign,
        reject_sink=ctx.reject_sink,
    )

    build_index_from_token_docs(
        doc_iter,
        output_path,
        nlp=nlp,
        ner_enabled=ner_enabled,
        deps_enabled=deps_enabled,
        batch_size=batch_size,
        n_process=n_process,
        pair_sink=pair_sink,
        meta_index_fields=meta_index_fields,
        build_embeddings=build_embeddings,
        embedding_text_max=embedding_text_max,
        build_word_faiss=build_word_faiss,
        build_gemma_embeddings=build_gemma_embeddings,
        export_gemma_texts=export_gemma_texts,
        export_gemma_sentences=export_gemma_sentences,
        capture_whitespace=capture_whitespace,
        build_sentence_embeddings=build_sentence_embeddings,
        keep_tmp=keep_tmp,
        keep_meta_jsonl=keep_meta_jsonl,
        gemma_endpoint=gemma_endpoint,
        gemma_model=gemma_model,
        gemma_batch=gemma_batch,
        gemma_timeout=gemma_timeout,
        build_info={
            "source_parquet": str(input_path),
            "spacy_model": str(spacy_model),
            "split_long_texts": bool(split_long_texts),
            "max_doc_chars": int(max_doc_chars),
            "include_prompts": bool(include_prompts),
            "require_input_text": bool(require_input_text),
            "source_archive_sha256": source_archive_sha256,
            "import_mode": str(import_mode),
        },
        ctx=ctx,
    )


def build_fast_index_from_rows(
    rows: Iterable[dict],
    output_path: Path,
    *,
    spacy_model: str,
    text_column: str = "text",
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    source: str = "generic",
    batch_size: int = 0,
    n_process: int = 0,
    disable_ner: bool = True,
    disable_deps: bool = True,
    split_long_texts: bool = True,
    max_doc_chars: int = 1_000_000,
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    capture_whitespace: bool = True,
    build_info: dict | None = None,
    ctx: "BuildContext | None" = None,
) -> None:
    """Index an in-memory iterator of ``dict`` rows as an UNALIGNED corpus.

    This is the single seam every DocRecord-path adapter (CSV/JSONL/plaintext/HF)
    reuses: it owns the spaCy load, the auto batch/n_process sizing, the PairSink
    wiring, the generic doc-stream and the call into the extracted backend. The
    parquet generic frontend (:func:`build_fast_index_generic`) is just one caller
    that supplies a parquet row iterator; new format adapters supply their own.

    ``rows`` is any iterable of plain dicts (``text_column``/``id_column``/
    ``meta_columns`` select the fields). ``build_info`` lets the caller stamp the
    manifest (``import_mode``, ``source_*`` provenance); it defaults to a generic
    descriptor.
    """
    ctx = ctx if ctx is not None else BuildContext()
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _configure_logging(output_path, None)

    if batch_size <= 0:
        batch_size = _auto_batch_size(_available_memory_bytes())
        LOGGER.info("Auto batch_size: %d", batch_size)
    if n_process <= 0:
        n_process = _auto_n_process(batch_size)
        LOGGER.info("Auto n_process: %d", n_process)

    try:
        nlp, ner_enabled, deps_enabled = _load_spacy_pipeline(
            spacy_model,
            disable_ner=disable_ner,
            disable_deps=disable_deps,
            max_doc_chars=max_doc_chars,
            output_path=output_path,
            ctx=ctx,
        )
    except Exception as exc:
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise

    meta_columns = meta_columns or []
    pair_sink = PairSink()
    if ctx.reject_sink is not None:
        ctx.reject_sink.open_log()
    doc_iter = _build_generic_doc_stream(
        rows,
        text_column=text_column,
        id_column=id_column,
        meta_columns=meta_columns,
        source=source,
        on_assign=pair_sink.assign,
        reject_sink=ctx.reject_sink,
        split_long_texts=split_long_texts,
        max_doc_chars=max_doc_chars,
    )

    merged_build_info = {
        "spacy_model": str(spacy_model),
        "import_mode": "generic",
        "text_column": text_column,
        "id_column": id_column,
    }
    if build_info:
        merged_build_info.update(build_info)

    try:
        build_index_from_token_docs(
            doc_iter,
            output_path,
            nlp=nlp,
            ner_enabled=ner_enabled,
            deps_enabled=deps_enabled,
            batch_size=batch_size,
            n_process=n_process,
            pair_sink=pair_sink,
            meta_index_fields=meta_index_fields,
            build_embeddings=build_embeddings,
            embedding_text_max=embedding_text_max,
            build_word_faiss=build_word_faiss,
            capture_whitespace=capture_whitespace,
            build_info=merged_build_info,
            ctx=ctx,
        )
        _write_build_report(output_path, status="completed", ctx=ctx)
    except Exception as exc:
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise


def build_fast_index_from_prealigned_rows(
    rows: Iterable[dict],
    output_path: Path,
    *,
    spacy_model: str,
    text_column: str = "text",
    id_column: str | None = "id",
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    source: str = "prealigned",
    variant_column: str | None = None,
    model_column: str | None = None,
    batch_size: int = 0,
    n_process: int = 0,
    disable_ner: bool = True,
    disable_deps: bool = True,
    split_long_texts: bool = True,
    max_doc_chars: int = 1_000_000,
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    capture_whitespace: bool = True,
    build_info: dict | None = None,
    ctx: "BuildContext | None" = None,
) -> None:
    """Index a pre-aligned row stream as a paired corpus.

    This is the corpus-agnostic form of the historical aligned import path:
    callers provide explicit ``pair_key`` + ``pair_role`` columns instead of
    fixed ``human``/``ai`` row semantics. The resulting index remains
    backward-compatible with existing parallel/alignment endpoints because it
    still materialises ``ref_doc`` and ``paired_with``.
    """
    ctx = ctx if ctx is not None else BuildContext()
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    _configure_logging(output_path, None)

    if batch_size <= 0:
        batch_size = _auto_batch_size(_available_memory_bytes())
        LOGGER.info("Auto batch_size: %d", batch_size)
    if n_process <= 0:
        n_process = _auto_n_process(batch_size)
        LOGGER.info("Auto n_process: %d", n_process)

    try:
        nlp, ner_enabled, deps_enabled = _load_spacy_pipeline(
            spacy_model,
            disable_ner=disable_ner,
            disable_deps=disable_deps,
            max_doc_chars=max_doc_chars,
            output_path=output_path,
            ctx=ctx,
        )
    except Exception as exc:
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise

    meta_columns = meta_columns or []
    pair_sink = PairSink()
    if ctx.reject_sink is not None:
        ctx.reject_sink.open_log()
    doc_iter = _build_prealigned_doc_stream(
        rows,
        text_column=text_column,
        id_column=id_column,
        pair_key_column=pair_key_column,
        pair_role_column=pair_role_column,
        anchor_role=anchor_role,
        pair_axis=pair_axis,
        pair_order=pair_order,
        meta_columns=meta_columns,
        source=source,
        variant_column=variant_column,
        model_column=model_column,
        on_assign=pair_sink.assign,
        on_pair=pair_sink.on_pair,
        reject_sink=ctx.reject_sink,
        split_long_texts=split_long_texts,
        max_doc_chars=max_doc_chars,
    )

    merged_build_info = {
        "spacy_model": str(spacy_model),
        "import_mode": "prealigned",
        "pair_axes": [_role_key(pair_axis) or "prealigned"],
        "text_column": text_column,
        "id_column": id_column,
        "pair_key_column": pair_key_column,
        "pair_role_column": pair_role_column,
        "anchor_role": _role_key(anchor_role),
        "pair_order": _role_key(pair_order) or "unsorted",
    }
    if build_info:
        merged_build_info.update(build_info)
        merged_build_info["import_mode"] = build_info.get("import_mode") or "prealigned"
        axes = build_info.get("pair_axes") or merged_build_info["pair_axes"]
        if isinstance(axes, str):
            axes = [axes]
        merged_build_info["pair_axes"] = [
            _role_key(str(axis)) or "prealigned"
            for axis in list(axes or [])
        ]

    try:
        build_index_from_token_docs(
            doc_iter,
            output_path,
            nlp=nlp,
            ner_enabled=ner_enabled,
            deps_enabled=deps_enabled,
            batch_size=batch_size,
            n_process=n_process,
            pair_sink=pair_sink,
            meta_index_fields=meta_index_fields,
            build_embeddings=build_embeddings,
            embedding_text_max=embedding_text_max,
            build_word_faiss=build_word_faiss,
            capture_whitespace=capture_whitespace,
            build_info=merged_build_info,
            ctx=ctx,
        )
        _write_build_report(output_path, status="completed", ctx=ctx)
    except Exception as exc:
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise


def build_fast_index_prealigned(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str,
    text_column: str = "text",
    id_column: str | None = "id",
    pair_key_column: str = "pair_id",
    pair_role_column: str = "pair_role",
    anchor_role: str = "source",
    pair_axis: str = "prealigned",
    pair_order: str = "unsorted",
    meta_columns: Optional[List[str]] = None,
    source: str = "prealigned",
    variant_column: str | None = None,
    model_column: str | None = None,
    batch_size: int = 0,
    n_process: int = 0,
    disable_ner: bool = True,
    disable_deps: bool = True,
    split_long_texts: bool = True,
    max_doc_chars: int = 1_000_000,
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    capture_whitespace: bool = True,
    build_info: dict | None = None,
    ctx: "BuildContext | None" = None,
) -> None:
    """Parquet frontend for pre-aligned corpora."""
    ctx = ctx if ctx is not None else BuildContext()
    output_path = Path(output_path)

    if batch_size <= 0:
        batch_size = _auto_batch_size(_available_memory_bytes())

    meta_columns = meta_columns or []
    columns = list(
        dict.fromkeys(
            [text_column]
            + ([id_column] if id_column else [])
            + [pair_key_column, pair_role_column, "source"]
            + ([variant_column] if variant_column else [])
            + ([model_column] if model_column else [])
            + meta_columns
        )
    )
    row_iter = _iter_parquet_rows(input_path, columns, batch_size=batch_size)

    merged_build_info = {
        "source_parquet": str(input_path),
        "import_mode": "prealigned",
        "pair_axes": [_role_key(pair_axis) or "prealigned"],
        "pair_order": _role_key(pair_order) or "unsorted",
    }
    if build_info:
        merged_build_info.update(build_info)

    build_fast_index_from_prealigned_rows(
        row_iter,
        output_path,
        spacy_model=spacy_model,
        text_column=text_column,
        id_column=id_column,
        pair_key_column=pair_key_column,
        pair_role_column=pair_role_column,
        anchor_role=anchor_role,
        pair_axis=pair_axis,
        pair_order=pair_order,
        meta_columns=meta_columns,
        source=source,
        variant_column=variant_column,
        model_column=model_column,
        batch_size=batch_size,
        n_process=n_process,
        disable_ner=disable_ner,
        disable_deps=disable_deps,
        split_long_texts=split_long_texts,
        max_doc_chars=max_doc_chars,
        meta_index_fields=meta_index_fields,
        build_embeddings=build_embeddings,
        embedding_text_max=embedding_text_max,
        build_word_faiss=build_word_faiss,
        capture_whitespace=capture_whitespace,
        build_info=merged_build_info,
        ctx=ctx,
    )


def build_fast_index_generic(
    input_path: Path,
    output_path: Path,
    *,
    spacy_model: str,
    text_column: str = "text",
    id_column: str | None = None,
    meta_columns: Optional[List[str]] = None,
    source: str = "generic",
    source_archive_sha256: str | None = None,
    batch_size: int = 0,
    n_process: int = 0,
    disable_ner: bool = True,
    disable_deps: bool = True,
    split_long_texts: bool = True,
    max_doc_chars: int = 1_000_000,
    meta_index_fields: Optional[List[str]] = None,
    build_embeddings: bool = False,
    embedding_text_max: int = 2000,
    build_word_faiss: bool | None = None,
    capture_whitespace: bool = True,
    ctx: "BuildContext | None" = None,
) -> None:
    """Generic/flat parquet frontend: index an UNALIGNED corpus (one document per
    row, no human/AI pairing, no ``input_text`` requirement). Reuses the same
    backend via :func:`build_fast_index_from_rows`.

    ``text_column`` is the document text; ``id_column`` (optional) the document id;
    ``meta_columns`` are passed through as document metadata.
    """
    ctx = ctx if ctx is not None else BuildContext()
    output_path = Path(output_path)

    # Auto batch sizing must be resolved here too because _iter_parquet_rows needs
    # a concrete batch_size; build_fast_index_from_rows re-resolves any <=0 value.
    if batch_size <= 0:
        batch_size = _auto_batch_size(_available_memory_bytes())

    meta_columns = meta_columns or []
    # A per-row "source" column is optional: read it only when the file has one.
    optional = []
    if pq is not None:
        try:
            if "source" in pq.ParquetFile(input_path).schema_arrow.names:
                optional = ["source"]
        except Exception:
            optional = ["source"]
    columns = list(dict.fromkeys([text_column] + ([id_column] if id_column else []) + optional + meta_columns))
    row_iter = _iter_parquet_rows(input_path, columns, batch_size=batch_size)

    build_fast_index_from_rows(
        row_iter,
        output_path,
        spacy_model=spacy_model,
        text_column=text_column,
        id_column=id_column,
        meta_columns=meta_columns,
        source=source,
        batch_size=batch_size,
        n_process=n_process,
        disable_ner=disable_ner,
        disable_deps=disable_deps,
        split_long_texts=split_long_texts,
        max_doc_chars=max_doc_chars,
        meta_index_fields=meta_index_fields,
        build_embeddings=build_embeddings,
        embedding_text_max=embedding_text_max,
        build_word_faiss=build_word_faiss,
        capture_whitespace=capture_whitespace,
        build_info={
            "source_parquet": str(input_path),
            "import_mode": "generic",
            "source_archive_sha256": source_archive_sha256,
        },
        ctx=ctx,
    )


def main(argv: list[str] | None = None) -> int:
    # DT-PACKAGED-IMPORT: accept an explicit argv so the packaged in-process
    # builder runner (candyconc.builders._runner) can call this directly without
    # spawning a subprocess. Falls back to sys.argv[1:] when invoked as a script.
    parser = argparse.ArgumentParser(description="Build a fast index directly from Parquet")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--skip-preflight", action="store_true", default=False)
    # Set by the VRT importer, which converts VRT to this layout (not a user option).
    parser.add_argument(
        "--import-mode",
        choices=(index_format.PAIRED_PARQUET_IMPORT_MODE, "vrt"),
        default=index_format.PAIRED_PARQUET_IMPORT_MODE,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--preflight-only", action="store_true", default=False)
    parser.add_argument("--clean-output", action="store_true", default=False)
    parser.add_argument(
        "--generic",
        action="store_true",
        default=False,
        help="Index an unpaired Parquet file through the configured text column.",
    )
    parser.add_argument("--text-column", default="input_text")
    parser.add_argument("--id-column", default="id")
    parser.add_argument("--meta-columns", nargs="*", default=[])
    parser.add_argument("--source", default="parquet-import")
    parser.add_argument("--reject-policy", choices=("collect", "fail_fast"), default=None)
    parser.add_argument("--reject-report", type=Path, default=None)
    parser.add_argument(
        "--source-archive-sha256",
        default=None,
        help="SHA-256 of the immutable source archive recorded in build provenance.",
    )
    parser.add_argument("--spacy-model", default="de_core_news_md")
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--n-process", type=int, default=0)
    parser.add_argument("--include-prompts", dest="include_prompts", action="store_true", default=False)
    parser.add_argument("--no-prompts", dest="include_prompts", action="store_false")
    parser.add_argument("--enable-ner", action="store_true", default=False)
    parser.add_argument("--enable-deps", action="store_true", default=False)
    parser.add_argument("--split-long-texts", dest="split_long_texts", action="store_true", default=True)
    parser.add_argument("--no-split-long-texts", dest="split_long_texts", action="store_false")
    parser.add_argument(
        "--require-input-text",
        dest="require_input_text",
        action="store_true",
        default=True,
        help="Accept only input_text, otherwise stop.",
    )
    parser.add_argument(
        "--allow-missing-input-text",
        dest="require_input_text",
        action="store_false",
        help="input_text may be missing (not recommended).",
    )
    parser.add_argument("--max-doc-chars", type=int, default=1_000_000)
    parser.add_argument(
        "--capture-whitespace",
        dest="capture_whitespace",
        action="store_true",
        default=True,
        help=(
            "Write the whitespace_after.bin side file (one flag per token, "
            "spaCy token.whitespace_) so that concordance lines, document "
            "context, full text and exports show the text with its original "
            "spacing (default: on)."
        ),
    )
    parser.add_argument(
        "--no-capture-whitespace",
        dest="capture_whitespace",
        action="store_false",
        help="Do not write whitespace_after.bin. Tokens are then shown separated by single spaces.",
    )
    parser.add_argument(
        "--build-sentence-embeddings",
        action="store_true",
        default=False,
        help=(
            "Write sentence_vecs.npy + sentence_vec_starts.npy "
            "(mean spaCy vectors per sentence, keyed by token start_pos, raw "
            "on disk). Enables alignment method=embed/hybrid. Needs a "
            "spaCy pipeline with vectors."
        ),
    )
    parser.add_argument("--build-embeddings", action="store_true", default=False)
    parser.add_argument("--build-word-faiss", dest="build_word_faiss", action="store_true", default=None)
    parser.add_argument("--no-word-faiss", dest="build_word_faiss", action="store_false")
    parser.add_argument("--build-gemma", dest="build_gemma", action="store_true", default=False)
    parser.add_argument("--export-gemma-texts", dest="export_gemma_texts", action="store_true", default=False)
    parser.add_argument(
        "--no-gemma-sentences",
        dest="export_gemma_sentences",
        action="store_false",
        default=True,
        help="Do not export the Gemma sentence JSONL.",
    )
    parser.add_argument("--gemma-endpoint", default=_config_get("CANDYCONC_GEMMA_EMB_ENDPOINT", "http://127.0.0.1:1234/v1/embeddings"))
    parser.add_argument("--gemma-model", default=_config_get("CANDYCONC_GEMMA_EMB_MODEL", "google/embedding-gemma-300m"))
    parser.add_argument("--gemma-batch", type=int, default=int(_config_get("CANDYCONC_GEMMA_EMB_BATCH", "32")))
    parser.add_argument("--gemma-timeout", type=float, default=float(_config_get("CANDYCONC_GEMMA_EMB_TIMEOUT", "120")))
    parser.add_argument("--embedding-text-max", type=int, default=2000)
    parser.add_argument("--keep-tmp", action="store_true", default=False)
    parser.add_argument(
        "--keep-meta-jsonl",
        action="store_true",
        default=False,
        help="Keep doc_metadata.jsonl after the build.",
    )
    parser.add_argument("--meta-index-fields", default="")
    parser.add_argument(
        "--alignment-method",
        choices=("edit", "embed", "hybrid"),
        default="edit",
        help=(
            "Sentence alignment method the index should support (additive, "
            "default 'edit' = token edit distance, byte-identical to the previous "
            "behavior). 'embed' and 'hybrid' need sentence embeddings keyed by "
            "token_start_pos. Build them with --build-sentence-embeddings. The value "
            "itself is a no-op for the build (only recorded in build_report), "
            "so that the CLI contract stays stable."
        ),
    )
    parser.add_argument("--autotune-cqlhpc", action="store_true", default=False)
    parser.add_argument("--autotune-samples", type=int, default=24)
    parser.add_argument("--autotune-repeats", type=int, default=3)
    parser.add_argument("--autotune-env-out", default="")
    parser.add_argument("--autotune-grid", choices=("standard", "large"), default="standard")
    parser.add_argument("--autotune-full-grid", action="store_true", default=False)
    args = parser.parse_args(argv)

    fields = [f.strip() for f in args.meta_index_fields.split(",") if f.strip()]
    # The research field list belongs to the aligned layout. A generic table
    # indexes all of its metadata columns, like the CSV and JSONL import.
    if not fields and not args.generic:
        fields = [
            "origin_id",
            "origin_doc_id",
            "source",
            "register",
            "variant",
            "model",
            "text_type",
            "pair_id",
            "step_index",
            "profile_id",
            "profile_name",
            "prompting_method",
            "ref_doc",
            "reference_kind",
            "paired_with",
        ]

    output_path = Path(args.output)
    if args.clean_output or os.environ.get("CANDYCONC_BUILD_CLEAN", "0") == "1":
        _clean_output_dir(output_path)
    _configure_logging(output_path, args.log_file)
    ctx = BuildContext()
    if args.reject_policy or args.reject_report:
        ctx.reject_sink = RejectSink(
            error_policy=(args.reject_policy or "collect"),
            log_path=args.reject_report,
        )

    # STEP 9: the alignment method is an additive CLI contract. 'edit' is a no-op
    # for the build (it is the runtime default). embed/hybrid require sentence
    # embeddings keyed by token start_pos — built only with
    # --build-sentence-embeddings — so we warn when the prerequisite is missing
    # rather than silently ignore the request.
    if args.alignment_method != "edit" and not args.build_sentence_embeddings:
        msg = (
            f"--alignment-method={args.alignment_method} was requested, but "
            "--build-sentence-embeddings is not set. The index is built without "
            "sentence embeddings, and embed and hybrid stay not_applicable until the "
            "corpus is imported again with --build-sentence-embeddings."
        )
        ctx.warnings.append(msg)
        LOGGER.warning(msg)

    if args.skip_preflight:
        LOGGER.warning("Preflight skipped (--skip-preflight).")
    else:
        ctx.preflight = _preflight_checks(
            input_path=Path(args.input),
            output_path=output_path,
            spacy_model=args.spacy_model,
            build_embeddings=args.build_embeddings,
            build_word_faiss=args.build_word_faiss,
            build_gemma_embeddings=args.build_gemma,
            export_gemma_texts=args.export_gemma_texts,
            gemma_endpoint=args.gemma_endpoint,
            gemma_model=args.gemma_model,
            gemma_timeout=args.gemma_timeout,
            disable_ner=not args.enable_ner,
            disable_deps=not args.enable_deps,
            require_input_text=args.require_input_text,
            generic_text_column=args.text_column if args.generic else None,
        )
        for warn in ctx.preflight.get("warnings", []):
            LOGGER.warning("Preflight: %s", localize(warn, "en"))
        errors = ctx.preflight.get("errors", [])
        if errors:
            for err in errors:
                LOGGER.error("Preflight: %s", localize(err, "en"))
            _write_build_report(output_path, status="preflight_failed", ctx=ctx, error="; ".join(errors))
            raise SystemExit(1)
        _write_build_report(output_path, status="preflight_ok", ctx=ctx)
        if args.preflight_only:
            LOGGER.info("Preflight only: finished.")
            return 0

    try:
        with _phase("build_total", output_path=output_path, ctx=ctx):
            if args.generic:
                build_fast_index_generic(
                    args.input,
                    output_path,
                    spacy_model=args.spacy_model,
                    text_column=args.text_column,
                    id_column=args.id_column or None,
                    meta_columns=list(args.meta_columns or []),
                    source=args.source,
                    source_archive_sha256=args.source_archive_sha256,
                    batch_size=args.batch_size,
                    n_process=args.n_process,
                    disable_ner=not args.enable_ner,
                    disable_deps=not args.enable_deps,
                    split_long_texts=args.split_long_texts,
                    max_doc_chars=args.max_doc_chars,
                    meta_index_fields=fields or None,
                    build_embeddings=args.build_embeddings,
                    embedding_text_max=args.embedding_text_max,
                    build_word_faiss=args.build_word_faiss,
                    capture_whitespace=args.capture_whitespace,
                    ctx=ctx,
                )
            else:
                build_fast_index_from_parquet(
                    args.input,
                    output_path,
                    spacy_model=args.spacy_model,
                    batch_size=args.batch_size,
                    n_process=args.n_process,
                    disable_ner=not args.enable_ner,
                    disable_deps=not args.enable_deps,
                    split_long_texts=args.split_long_texts,
                    max_doc_chars=args.max_doc_chars,
                    include_prompts=args.include_prompts,
                    require_input_text=args.require_input_text,
                    source_archive_sha256=args.source_archive_sha256,
                    meta_index_fields=fields or None,
                    build_embeddings=args.build_embeddings,
                    embedding_text_max=args.embedding_text_max,
                    build_word_faiss=args.build_word_faiss,
                    build_gemma_embeddings=args.build_gemma,
                    export_gemma_texts=args.export_gemma_texts,
                    export_gemma_sentences=args.export_gemma_sentences,
                    capture_whitespace=args.capture_whitespace,
                    build_sentence_embeddings=args.build_sentence_embeddings,
                    keep_tmp=args.keep_tmp,
                    keep_meta_jsonl=args.keep_meta_jsonl,
                    gemma_endpoint=args.gemma_endpoint,
                    gemma_model=args.gemma_model,
                    gemma_batch=args.gemma_batch,
                    gemma_timeout=args.gemma_timeout,
                    import_mode=args.import_mode,
                    ctx=ctx,
                )
        if args.autotune_cqlhpc:
            tune_out = output_path / "cqlhpc_autotune.json"
            env_out = output_path / "cqlhpc_tuned.env"
            if args.autotune_env_out:
                env_out = Path(args.autotune_env_out)
            LOGGER.info(
                "CQLHPC autotune: starting (samples=%s repeats=%s)",
                args.autotune_samples,
                args.autotune_repeats,
            )
            script = _autotune_script()
            cmd = [
                sys.executable,
                str(script),
                "--index",
                str(output_path),
                "--samples",
                str(args.autotune_samples),
                "--repeats",
                str(args.autotune_repeats),
                "--grid",
                str(args.autotune_grid),
                "--out",
                str(tune_out),
                "--write-env",
                str(env_out),
            ]
            if args.autotune_full_grid:
                cmd.append("--full-grid")
            try:
                subprocess.run(cmd, check=True)
                LOGGER.info("CQLHPC autotune: done -> %s", tune_out)
            except Exception as exc:
                warn = f"CQLHPC autotune failed (the build stays valid): {exc}"
                ctx.warnings.append(warn)
                LOGGER.warning(warn)
        _write_build_report(output_path, status="completed", ctx=ctx)
        return 0
    except SpacyModelMissingError as exc:
        # Nutzerfertige Meldung ohne Traceback; failed-Report bleibt erhalten.
        LOGGER.error("%s", exc)
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise SystemExit(2) from exc
    except Exception as exc:
        LOGGER.exception("Build fehlgeschlagen: %s", exc)
        _write_build_report(output_path, status="failed", ctx=ctx, error=str(exc))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
