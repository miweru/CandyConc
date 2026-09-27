"""Persistent local semantic-index jobs for Apple Silicon Macs."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import signal
import string
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from candyconc.i18n import LocalizedText, lt
from candyconc.paths import data_dir


MODEL_NAME = "mlx-community/embeddinggemma-300m-4bit"
DIMENSION = 768
RUNTIME_VERSION = "mlx-embeddings-v1"
RUNTIME_DOWNLOAD_BYTES = 1_250_000_000
MODEL_DOWNLOAD_BYTES = 250_000_000
STATE_SCHEMA = "candyconc-semantic-index-build-v1"
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "stale"}
LEVELS = {"doc", "sentence"}
_LAUNCH_LOCK = threading.Lock()


_PREPARING = lt("Lokaler Semantik-Build wird vorbereitet.", "Preparing the local semantic index build.")
_STARTED = lt("Lokaler Semantik-Build wurde gestartet.", "Local semantic index build started.")
_START_FAILED = lt(
    "Semantik-Build konnte nicht gestartet werden.",
    "The semantic index build could not be started.",
)
_INTERRUPTED = lt(
    "Der Build wurde unterbrochen und kann fortgesetzt werden.",
    "The build was interrupted and can be resumed.",
)
_PROCESS_GONE = lt("Build-Prozess ist nicht mehr aktiv.", "The build process is no longer running.")
_CANCELLED = lt(
    "Semantik-Build wurde abgebrochen; der Zwischenstand bleibt fortsetzbar.",
    "Semantic index build cancelled. The intermediate state can be resumed.",
)
_WARN_DOC_MEMORY = lt(
    "Für den Dokumentindex werden mindestens 16 GB gemeinsamer Speicher empfohlen.",
    "At least 16 GB of unified memory is recommended for the document index.",
)
_WARN_SENTENCE_MEMORY = lt(
    "Der Satzindex kann bei der Suche rund 27 GB Arbeitsspeicher belegen; "
    "48 GB gemeinsamer Speicher werden empfohlen.",
    "The sentence index can use about 27 GB of memory during search. "
    "48 GB of unified memory is recommended.",
)
_WARN_PLATFORM = lt(
    "Der lokale MLX-Build ist nur auf Apple-Silicon-Macs verfügbar.",
    "The local MLX build is only available on Apple silicon Macs.",
)
_WARN_NO_SENTENCES = lt(
    "Der Fast Index enthält keine Satzgrenzen; ein Satzindex ist nicht möglich.",
    "The index has no sentence boundaries, so a sentence index is not possible.",
)

#: Status and error texts of a local semantic-index build. This module, the
#: build process (tools/semantic_index_build.py) and the MLX worker
#: (tools/semantic_mlx_worker.py, which runs without candyconc) write them
#: into state.json as plain text. ``status_text`` maps a stored text back to
#: its pair, so a snapshot shows it in the language of the request. A
#: wrapper pattern must come before the patterns it can contain.
STATUS_TEXTS: tuple[LocalizedText, ...] = (
    _PREPARING,
    _STARTED,
    _START_FAILED,
    _INTERRUPTED,
    _PROCESS_GONE,
    _CANCELLED,
    _WARN_DOC_MEMORY,
    _WARN_SENTENCE_MEMORY,
    _WARN_PLATFORM,
    _WARN_NO_SENTENCES,
    # tools/semantic_index_build.py, message=
    lt("Lokaler Semantik-Build läuft.", "Local semantic index build running."),
    lt("MLX-Laufzeit ist bereit.", "MLX runtime is ready."),
    lt("Isolierte MLX-Laufzeit wird einmalig installiert.", "Installing the isolated MLX runtime once."),
    lt("MLX-Laufzeit wurde installiert und geprüft.", "MLX runtime installed and checked."),
    lt("Korpustexte werden rekonstruiert ({done}/{total}).", "Reconstructing corpus texts ({done}/{total})."),
    lt("Korpustexte rekonstruiert: {done}/{total}.", "Corpus texts reconstructed: {done}/{total}."),
    lt(
        "EmbeddingGemma wird geladen; beim ersten Lauf wird das Modell heruntergeladen.",
        "Loading EmbeddingGemma. The first run downloads the model.",
    ),
    lt("{level}-Vektoren und IDs werden vollständig geprüft.", "Checking all {level} vectors and IDs."),
    lt("{level}-Index ist validiert.", "{level} index validated."),
    lt("Validierte semantische Artefakte werden aktiviert.", "Activating the validated semantic artifacts."),
    lt("Lokaler semantischer Index wurde geprüft und aktiviert.", "Local semantic index checked and activated."),
    lt(
        "Build wurde abgebrochen; der Zwischenstand bleibt fortsetzbar.",
        "Build cancelled. The intermediate state can be resumed.",
    ),
    lt("Semantik-Build fehlgeschlagen: {error}", "Semantic index build failed: {error}"),
    # tools/semantic_mlx_worker.py, message=
    lt(
        "EmbeddingGemma wird in der isolierten MLX-Laufzeit geladen.",
        "Loading EmbeddingGemma in the isolated MLX runtime.",
    ),
    lt("EmbeddingGemma ist geladen.", "EmbeddingGemma is loaded."),
    lt("{kind}-Embeddings: {done}/{total}.", "{kind} embeddings: {done}/{total}."),
    lt("Alle ausgewählten Embeddings sind erzeugt.", "All selected embeddings have been created."),
    # tools/semantic_index_build.py, errors stored in state["error"]
    lt("Unbekannter Semantik-Build-State", "Unknown semantic index build state"),
    lt("Launcher hat den Build-Prozess nicht bestätigt", "The launcher did not confirm the build process"),
    lt(
        "Konfigurierte MLX-Laufzeit ist nicht verwendbar: {python}",
        "The configured MLX runtime cannot be used: {python}",
    ),
    lt(
        "Die isolierte MLX-Laufzeit konnte nicht installiert werden.",
        "The isolated MLX runtime could not be installed.",
    ),
    lt("Resume-Datei fehlt: {path}", "Resume file is missing: {path}"),
    lt("Dokumentgrenzen fehlen", "Document boundaries are missing"),
    lt("Satzgrenzen fehlen", "Sentence boundaries are missing"),
    lt("Wortlexikon fehlt", "Word lexicon is missing"),
    lt("Satzanzahl stimmt nicht: {found} != {expected}", "Sentence count does not match: {found} != {expected}"),
    lt("MLX-Worker endete mit Code {code}", "MLX worker exited with code {code}"),
    lt("doc: Positionsfehler {found} != {expected}", "doc: position error {found} != {expected}"),
    lt("sentence: Positionsfehler bei {position}", "sentence: position error at {position}"),
    lt("{kind}: ungültige doc_id {doc_id}", "{kind}: invalid doc_id {doc_id}"),
    lt("{kind}: doc_id-Reihenfolge ist nicht monoton", "{kind}: doc_id order is not monotonic"),
    lt("{kind}: Textanzahl {found} != {expected}", "{kind}: text count {found} != {expected}"),
    lt("{kind}: ungültige Vektorform {shape}", "{kind}: invalid vector shape {shape}"),
    lt("{kind}: nicht-finite Vektoren ab Position {position}", "{kind}: non-finite vectors from position {position}"),
    lt("{kind}: Vektoren sind nicht normalisiert", "{kind}: vectors are not normalized"),
    lt("{kind}: FAISS-Zählung {found} != {expected}", "{kind}: FAISS count {found} != {expected}"),
    lt("{kind}: gespeicherter FAISS-Index ist unvollständig", "{kind}: stored FAISS index is incomplete"),
)


def _text_pattern(template: str) -> "re.Pattern[str]":
    parts: list[str] = []
    for literal, field, _spec, _conversion in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if field:
            parts.append(f"(?P<{field}>.+?)")
    return re.compile("^" + "".join(parts) + "$", re.DOTALL)


_EXACT_TEXTS: dict[str, LocalizedText] = {}
_TEXT_PATTERNS: list[tuple["re.Pattern[str]", LocalizedText]] = []
for _pair in STATUS_TEXTS:
    for _form in (_pair.de, _pair.en):
        if "{" in _form:
            _TEXT_PATTERNS.append((_text_pattern(_form), _pair))
        else:
            _EXACT_TEXTS[_form] = _pair
del _pair, _form


def status_text(value: Any) -> Any:
    """Bilingual pair for a status text stored by a semantic-index build.

    Accepts the German or the English form. Unknown texts and non-text
    values are returned unchanged.
    """
    if not isinstance(value, str) or isinstance(value, LocalizedText) or not value:
        return value
    exact = _EXACT_TEXTS.get(value)
    if exact is not None:
        return exact
    for pattern, pair in _TEXT_PATTERNS:
        match = pattern.match(value)
        if match:
            return pair.format(**{key: status_text(part) for key, part in match.groupdict().items()})
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_root() -> Path:
    configured = os.environ.get("CANDYCONC_SEMANTIC_JOB_DIR")
    return Path(configured or data_dir() / "semantic-jobs").expanduser()


def runtime_python_path() -> Path:
    override = os.environ.get("CANDYCONC_MLX_RUNTIME_PYTHON")
    if override:
        return Path(override).expanduser()
    root = data_dir() / "runtimes" / RUNTIME_VERSION
    return root / "bin" / "python"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            lt(
                "Semantik-Build-Status ist unlesbar: {path}",
                "Semantic index build status cannot be read: {path}",
            ).format(path=path)
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise RuntimeError(
            lt(
                "Unbekannter Semantik-Build-Status: {path}",
                "Unknown semantic index build status: {path}",
            ).format(path=path)
        )
    return value


def _state_path(run_id: str) -> Path:
    normalized = str(run_id or "").strip().lower()
    if len(normalized) != 32 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise KeyError(run_id)
    return _job_root() / normalized / "state.json"


def _memory_bytes() -> int:
    if sys.platform == "darwin":
        try:
            value = subprocess.check_output(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                text=True,
                timeout=2,
            )
            return int(value.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        return page_size * pages
    except (AttributeError, OSError, ValueError):
        return 0


def _boundary_counts(index: Any) -> tuple[int, int, int]:
    fast = index.fast_index
    boundaries = fast.boundaries
    if not boundaries or not getattr(boundaries, "document", None):
        raise RuntimeError(
            lt(
                "Dokumentgrenzen fehlen. Bitte Fast Index neu bauen.",
                "Document boundaries are missing. Rebuild the index.",
            )
        )
    doc_starts = boundaries.document._positions.astype(np.uint32, copy=False)
    if doc_starts.size == 0:
        raise RuntimeError(lt("Dokumentgrenzen sind leer.", "Document boundaries are empty."))
    sentence = getattr(boundaries, "sentence", None)
    sentence_starts = (
        sentence._positions.astype(np.uint32, copy=False)
        if sentence is not None
        else np.zeros(0, dtype=np.uint32)
    )
    sentence_count = 0
    if sentence_starts.size:
        positions = np.searchsorted(sentence_starts, doc_starts)
        in_range = positions < sentence_starts.size
        matching = np.zeros(doc_starts.size, dtype=bool)
        matching[in_range] = sentence_starts[positions[in_range]] == doc_starts[in_range]
        sentence_count = int(sentence_starts.size + np.count_nonzero(~matching))
    token_count = int(fast.token_store.token_count)
    return int(doc_starts.size), sentence_count, token_count


def _asset_complete(index_path: Path, level: str) -> bool:
    names = (
        f"faiss_gemma_{level}.index",
        f"gemma_{level}_vecs.npy",
        f"gemma_{level}_texts.json",
    )
    return all((index_path / name).is_file() for name in names)


def _latest_state_for_corpus(
    corpus_path: Path,
    *,
    levels: Iterable[str] | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    root = _job_root()
    if not root.is_dir():
        return None
    requested = sorted(set(levels or ()))
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for path in root.glob("*/state.json"):
        try:
            state = _read_state(path)
        except RuntimeError:
            continue
        if Path(str(state.get("corpus_path") or "")).resolve(strict=False) != corpus_path:
            continue
        if requested and sorted(state.get("levels") or []) != requested:
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            stamp = 0.0
        candidates.append((stamp, path, state))
    if not candidates:
        return None
    _, path, state = max(candidates, key=lambda item: item[0])
    return path, state


def _active_state() -> dict[str, Any] | None:
    root = _job_root()
    if not root.is_dir():
        return None
    for path in root.glob("*/state.json"):
        try:
            state = _read_state(path)
        except RuntimeError:
            continue
        if state.get("status") not in {"queued", "running"}:
            continue
        if _process_group_alive(int(state.get("process_group_id") or 0)):
            return state
    return None


def _model_cache_present() -> bool:
    cache_name = "models--" + MODEL_NAME.replace("/", "--")
    roots = [
        Path(os.environ.get("HF_HOME", "")).expanduser() / "hub"
        if os.environ.get("HF_HOME")
        else None,
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    return any(root is not None and (root / cache_name).is_dir() for root in roots)


def _estimate_sizes(doc_count: int, sentence_count: int, token_count: int) -> dict[str, Any]:
    vector_bytes_doc = doc_count * DIMENSION * 4
    vector_bytes_sentence = sentence_count * DIMENSION * 4
    doc_text_bytes = min(token_count * 3, doc_count * 2_200)
    sentence_text_bytes = min(token_count * 8, sentence_count * 600)
    runtime_bytes = 0 if runtime_python_path().is_file() else RUNTIME_DOWNLOAD_BYTES
    model_bytes = 0 if _model_cache_present() else MODEL_DOWNLOAD_BYTES

    def level(vector_bytes: int, text_bytes: int) -> dict[str, int]:
        return {
            "final_bytes": int(2 * vector_bytes + text_bytes),
            "peak_build_bytes": int(2 * vector_bytes + 2 * text_bytes),
            "warm_search_bytes": int(vector_bytes + text_bytes + 2_000_000_000),
        }

    doc = level(vector_bytes_doc, doc_text_bytes)
    sentence = level(vector_bytes_sentence, sentence_text_bytes)
    return {
        "doc": doc,
        "sentence": sentence,
        "both": {
            key: int(doc[key] + sentence[key])
            for key in ("final_bytes", "peak_build_bytes", "warm_search_bytes")
        },
        "runtime_download_bytes": runtime_bytes,
        "model_download_bytes": model_bytes,
    }


FAISS_MISSING_MESSAGE = lt(
    "Der semantische Index braucht das optionale Paket faiss. "
    "Installation: pip install 'candyconc[semantic]'",
    "The semantic index needs the optional package faiss. "
    "Install it with: pip install 'candyconc[semantic]'",
)


def _faiss_installed() -> bool:
    try:
        return importlib.util.find_spec("faiss") is not None
    except (ImportError, ValueError):
        return False


def preflight(index: Any, corpus_name: str) -> dict[str, Any]:
    index_path = Path(index.fast_index.index_path).expanduser().resolve()
    doc_count, sentence_count, token_count = _boundary_counts(index)
    disk = shutil.disk_usage(index_path)
    memory = _memory_bytes()
    estimates = _estimate_sizes(doc_count, sentence_count, token_count)
    platform_supported = sys.platform == "darwin" and platform.machine() == "arm64"
    faiss_installed = _faiss_installed()
    runtime_ready = runtime_python_path().is_file()
    available = {
        "doc": _asset_complete(index_path, "doc"),
        "sentence": _asset_complete(index_path, "sentence"),
    }
    resumable = _latest_state_for_corpus(index_path)
    resumable_payload = None
    if resumable is not None:
        _, state = resumable
        if state.get("status") != "succeeded":
            resumable_payload = {
                "run_id": state.get("run_id"),
                "status": state.get("status"),
                "levels": state.get("levels") or [],
                "progress": state.get("progress"),
                "message": status_text(state.get("message") or ""),
            }

    base_download = estimates["runtime_download_bytes"] + estimates["model_download_bytes"]
    doc_peak = 0 if available["doc"] else estimates["doc"]["peak_build_bytes"]
    sentence_peak = 0 if available["sentence"] else estimates["sentence"]["peak_build_bytes"]
    doc_required = int((doc_peak + base_download) * 1.1)
    sentence_required = int((sentence_peak + base_download) * 1.1)
    both_required = int((doc_peak + sentence_peak + base_download) * 1.1)
    warnings: list[str] = []
    if platform_supported and memory and memory < 16 * 1024**3:
        warnings.append(_WARN_DOC_MEMORY)
    if platform_supported and memory and memory < 48 * 1024**3:
        warnings.append(_WARN_SENTENCE_MEMORY)
    if not platform_supported:
        warnings.append(_WARN_PLATFORM)
    if sentence_count <= 0:
        warnings.append(_WARN_NO_SENTENCES)
    if not faiss_installed:
        warnings.append(FAISS_MISSING_MESSAGE)

    return {
        "schema_version": "candyconc-semantic-index-preflight-v1",
        "corpus": corpus_name,
        "corpus_path": str(index_path),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "supported": platform_supported,
            "memory_bytes": memory,
        },
        "runtime": {
            "installed": runtime_ready,
            "python": str(runtime_python_path()),
            "model": MODEL_NAME,
            "model_cached": _model_cache_present(),
            "faiss_installed": faiss_installed,
        },
        "counts": {
            "documents": doc_count,
            "sentences": sentence_count,
            "tokens": token_count,
        },
        "disk": {
            "free_bytes": int(disk.free),
            "total_bytes": int(disk.total),
        },
        "estimates": estimates,
        "available_levels": available,
        "options": {
            "doc": {
                "can_build": platform_supported and faiss_installed and disk.free >= doc_required,
                "required_free_bytes": doc_required,
            },
            "sentence": {
                "can_build": platform_supported and faiss_installed and sentence_count > 0 and disk.free >= sentence_required,
                "required_free_bytes": sentence_required,
            },
            "both": {
                "can_build": platform_supported and faiss_installed and sentence_count > 0 and disk.free >= both_required,
                "required_free_bytes": both_required,
            },
        },
        "resumable_run": resumable_payload,
        "warnings": warnings,
    }


def _process_group_alive(group_id: int) -> bool:
    if group_id <= 0:
        return False
    try:
        os.kill(group_id, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _launch_state(path: Path, state: dict[str, Any]) -> None:
    state.update(
        {
            "status": "queued",
            "phase": "queued",
            "message": _STARTED,
            "error": "",
            "cancel_requested": False,
            "cancellable": True,
            "process_group_id": 0,
            "launcher_pid": 0,
            "updated_at": _now_iso(),
            "finished_at": None,
        }
    )
    _atomic_json(path, state)
    command = [
        sys.executable,
        "-m",
        "candyconc.tools.semantic_index_build",
        "--state",
        str(path),
        "--wait-for-launch",
    ]
    if sys.platform == "darwin" and Path("/usr/bin/caffeinate").is_file():
        command = ["/usr/bin/caffeinate", "-dimsu", *command]
    log_path = path.parent / "build.log"
    env = os.environ.copy()
    try:
        with log_path.open("ab", buffering=0) as log_handle:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        state.update(
            {
                "status": "failed",
                "phase": "failed",
                "message": _START_FAILED,
                "error": str(exc),
                "cancellable": False,
                "updated_at": _now_iso(),
                "finished_at": _now_iso(),
            }
        )
        _atomic_json(path, state)
        raise RuntimeError(_START_FAILED) from exc
    launched = _read_state(path)
    launched.update(
        {
            "process_group_id": int(process.pid),
            "launcher_pid": int(process.pid),
            "updated_at": _now_iso(),
        }
    )
    _atomic_json(path, launched)


def _launch_unlocked(index: Any, corpus_name: str, levels: Iterable[str]) -> dict[str, Any]:
    requested = sorted({str(level).strip().lower() for level in levels})
    if not requested or any(level not in LEVELS for level in requested):
        raise ValueError(
            lt("levels muss doc und/oder sentence enthalten", "levels must contain doc and/or sentence")
        )
    info = preflight(index, corpus_name)
    requested = [level for level in requested if not info["available_levels"][level]]
    if not requested:
        raise RuntimeError(
            lt(
                "Die ausgewählten semantischen Indexebenen sind bereits verfügbar.",
                "The selected semantic index levels are already available.",
            )
        )
    option_key = "both" if requested == ["doc", "sentence"] else requested[0]
    option = info["options"][option_key]
    if not option["can_build"]:
        if not info["platform"]["supported"]:
            raise RuntimeError(
                lt(
                    "Lokale MLX-Indizes benötigen einen Apple-Silicon-Mac.",
                    "Local MLX indexes need an Apple silicon Mac.",
                )
            )
        if not info["runtime"]["faiss_installed"]:
            raise RuntimeError(FAISS_MISSING_MESSAGE)
        raise RuntimeError(
            lt(
                "Nicht genügend freier Speicher für den gewählten semantischen Index.",
                "Not enough free disk space for the selected semantic index.",
            )
        )

    corpus_path = Path(info["corpus_path"])
    active = _active_state()
    if active is not None:
        same_corpus = Path(str(active.get("corpus_path") or "")).resolve()
        if same_corpus == corpus_path and sorted(active.get("levels") or []) == requested:
            return _launch_payload(active)
        raise RuntimeError(
            lt(
                "Ein anderer lokaler Semantik-Build läuft bereits. "
                "Warte auf dessen Abschluss oder brich ihn in den Einstellungen ab.",
                "Another local semantic index build is already running. "
                "Wait for it to finish or cancel it in Settings.",
            )
        )
    previous = _latest_state_for_corpus(corpus_path, levels=requested)
    if previous is not None:
        state_path, state = previous
        group_id = int(state.get("process_group_id") or 0)
        if state.get("status") in {"queued", "running"} and _process_group_alive(group_id):
            return _launch_payload(state)
        if state.get("status") != "succeeded":
            _launch_state(state_path, state)
            return _launch_payload(state)

    run_id = uuid.uuid4().hex
    job_dir = _job_root() / run_id
    state_path = job_dir / "state.json"
    state = {
        "schema_version": STATE_SCHEMA,
        "run_id": run_id,
        "operation_id": "settings.embedding_management.local_index_build",
        "corpus": corpus_name,
        "corpus_path": str(corpus_path),
        "levels": requested,
        "model": MODEL_NAME,
        "dimension": DIMENSION,
        "status": "queued",
        "phase": "queued",
        "progress": 0,
        "message": _PREPARING,
        "error": "",
        "warnings": list(info.get("warnings") or []),
        "counts": dict(info["counts"]),
        "staging_dir": str(job_dir / "artifacts"),
        "runtime_python": str(runtime_python_path()),
        "cancel_requested": False,
        "cancellable": True,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "finished_at": None,
    }
    _atomic_json(state_path, state)
    _launch_state(state_path, state)
    return _launch_payload(state)


def launch(index: Any, corpus_name: str, levels: Iterable[str]) -> dict[str, Any]:
    with _LAUNCH_LOCK:
        return _launch_unlocked(index, corpus_name, levels)


def _launch_payload(state: dict[str, Any]) -> dict[str, Any]:
    run_id = str(state["run_id"])
    return {
        "status": "queued",
        "run_id": run_id,
        "job_id": run_id,
        "status_url": f"/api/v1/embeddings/local-index/builds/{run_id}",
        "operation_id": "settings.embedding_management.local_index_build",
    }


def snapshot(run_id: str) -> dict[str, Any]:
    path = _state_path(run_id)
    if not path.is_file():
        raise KeyError(run_id)
    state = _read_state(path)
    status = str(state.get("status") or "stale")
    group_id = int(state.get("process_group_id") or 0)
    if status in {"queued", "running"} and not _process_group_alive(group_id):
        state.update(
            {
                "status": "stale",
                "phase": "interrupted",
                "message": _INTERRUPTED,
                "error": _PROCESS_GONE,
                "cancellable": False,
                "updated_at": _now_iso(),
                "finished_at": _now_iso(),
            }
        )
        _atomic_json(path, state)
        status = "stale"
    return {
        "run_id": str(state["run_id"]),
        "job_id": str(state["run_id"]),
        "operation_id": str(state.get("operation_id") or "settings.embedding_management.local_index_build"),
        "source_id": str(state.get("corpus") or state.get("corpus_path") or "corpus"),
        "kind": "semantic_index_build",
        "label": lt("Semantischer Index: {corpus}", "Semantic index: {corpus}").format(
            corpus=state.get("corpus") or lt("Korpus", "corpus")
        ),
        "status": status if status in TERMINAL_STATUSES | {"queued", "running"} else "stale",
        "phase": str(state.get("phase") or ""),
        "progress": int(state.get("progress") or 0),
        "message": status_text(str(state.get("message") or "")),
        "error": status_text(str(state.get("error") or "")) or None,
        "result_ref": str(state.get("result_ref") or "") or None,
        "readiness": "verified" if status == "succeeded" else ("failed" if status == "failed" else "pending"),
        "warnings": [status_text(warning) for warning in state.get("warnings") or []],
        "evidence": {
            "levels": list(state.get("levels") or []),
            "counts": dict(state.get("counts") or {}),
            "cursors": dict(state.get("cursors") or {}),
            "rate": state.get("rate"),
            "eta_seconds": state.get("eta_seconds"),
            "cancellable": bool(state.get("cancellable", False)),
            "resumable": status in {"failed", "cancelled", "stale"},
        },
        "created_at": str(state.get("created_at") or _now_iso()),
        "updated_at": str(state.get("updated_at") or _now_iso()),
        "finished_at": state.get("finished_at"),
    }


def cancel(run_id: str) -> dict[str, Any]:
    path = _state_path(run_id)
    if not path.is_file():
        raise KeyError(run_id)
    state = _read_state(path)
    if state.get("status") in TERMINAL_STATUSES:
        return snapshot(run_id)
    if not state.get("cancellable", True):
        raise RuntimeError(
            lt(
                "Der Build befindet sich bereits in der finalen Aktivierung.",
                "The build is already in its final activation.",
            )
        )
    state.update(
        {
            "cancel_requested": True,
            "status": "cancelled",
            "phase": "cancelled",
            "message": _CANCELLED,
            "error": "",
            "cancellable": False,
            "updated_at": _now_iso(),
            "finished_at": _now_iso(),
        }
    )
    _atomic_json(path, state)
    group_id = int(state.get("process_group_id") or 0)
    if _process_group_alive(group_id):
        try:
            os.killpg(group_id, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    return snapshot(run_id)


__all__ = [
    "DIMENSION",
    "MODEL_NAME",
    "STATE_SCHEMA",
    "cancel",
    "launch",
    "preflight",
    "runtime_python_path",
    "snapshot",
    "status_text",
]
