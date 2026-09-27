"""Detached, resumable controller for local MLX semantic-index builds."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import traceback
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

import faiss
import numpy as np

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.fast_index_native import strings_for_ids
from candyconc.core.index_format import read_count_prefixed_array
from candyconc.services.semantic_index_jobs import DIMENSION, MODEL_NAME, STATE_SCHEMA


RUNTIME_PACKAGES = (
    "mlx==0.32.0",
    "mlx-embeddings==0.1.0",
    "transformers==5.12.1",
    "huggingface-hub==1.23.0",
)
TEXT_MAX_CHARS = 2_000
EXPORT_CHECKPOINT_DOCS = 1_000


class BuildCancelled(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise RuntimeError("Unbekannter Semantik-Build-State")
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _update_state(path: Path, **patch: Any) -> dict[str, Any]:
    state = _read_state(path)
    state.update(patch)
    state["updated_at"] = _now_iso()
    _atomic_json(path, state)
    return state


def _check_cancel(path: Path) -> None:
    state = _read_state(path)
    if state.get("cancel_requested") or state.get("status") == "cancelled":
        raise BuildCancelled("Build wurde abgebrochen")


def _wait_for_launch(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _read_state(path)
        if int(state.get("process_group_id") or 0) > 0:
            return
        time.sleep(0.01)
    raise RuntimeError("Launcher hat den Build-Prozess nicht bestätigt")


def _runtime_works(python: Path) -> bool:
    if not python.is_file():
        return False
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import mlx, mlx_embeddings, numpy; print('ok')",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def _ensure_runtime(state_path: Path) -> Path:
    state = _read_state(state_path)
    python = Path(str(state["runtime_python"])).expanduser()
    if _runtime_works(python):
        _update_state(
            state_path,
            phase="runtime_ready",
            progress=max(4, int(state.get("progress") or 0)),
            message="MLX-Laufzeit ist bereit.",
        )
        return python

    if os.environ.get("CANDYCONC_MLX_RUNTIME_PYTHON"):
        raise RuntimeError(
            f"Konfigurierte MLX-Laufzeit ist nicht verwendbar: {python}"
        )
    _update_state(
        state_path,
        phase="runtime_install",
        progress=1,
        message="Isolierte MLX-Laufzeit wird einmalig installiert.",
    )
    _check_cancel(state_path)
    runtime_root = python.parent.parent
    runtime_root.parent.mkdir(parents=True, exist_ok=True)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True, clear=False).create(runtime_root)
    _check_cancel(state_path)
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *RUNTIME_PACKAGES,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not _runtime_works(python):
        raise RuntimeError("Die isolierte MLX-Laufzeit konnte nicht installiert werden.")
    _update_state(
        state_path,
        phase="runtime_ready",
        progress=4,
        message="MLX-Laufzeit wurde installiert und geprüft.",
    )
    return python


def _render_tokens(words: list[str], start: int, whitespace: np.ndarray | None) -> str:
    if not words:
        return ""
    if whitespace is None:
        return " ".join(words)
    parts: list[str] = []
    last = len(words) - 1
    for offset, word in enumerate(words):
        parts.append(word)
        if offset < last and bool(whitespace[start + offset]):
            parts.append(" ")
    return "".join(parts)


def _open_checkpointed(
    path: Path,
    *,
    cursor: int,
    offset: int,
) -> BinaryIO:
    if cursor <= 0:
        return path.open("w+b")
    if not path.is_file():
        raise RuntimeError(f"Resume-Datei fehlt: {path}")
    handle = path.open("r+b")
    handle.truncate(offset)
    handle.seek(offset)
    return handle


def _write_jsonl(handle: BinaryIO, payload: dict[str, Any]) -> None:
    handle.write(
        (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )


def _export_texts(state_path: Path, artifacts: Path) -> dict[str, Any]:
    state = _read_state(state_path)
    export = dict(state.get("export") or {})
    if export.get("complete"):
        return export

    levels = set(state.get("levels") or [])
    counts = dict(state.get("counts") or {})
    total_docs = int(counts.get("documents") or 0)
    expected_sentences = int(counts.get("sentences") or 0)
    cursor = int(export.get("cursor_doc") or 0)
    sentence_count = int(export.get("sentence_count") or 0)
    offsets = dict(export.get("offsets") or {})
    doc_path = artifacts / "gemma_doc_texts.jsonl"
    sentence_path = artifacts / "gemma_sentence_texts.jsonl"
    artifacts.mkdir(parents=True, exist_ok=True)

    doc_handle = (
        _open_checkpointed(
            doc_path,
            cursor=cursor,
            offset=int(offsets.get("doc") or 0),
        )
        if "doc" in levels
        else None
    )
    sentence_handle = (
        _open_checkpointed(
            sentence_path,
            cursor=cursor,
            offset=int(offsets.get("sentence") or 0),
        )
        if "sentence" in levels
        else None
    )

    corpus_path = Path(str(state["corpus_path"]))
    index = CorpusIndex(corpus_path)
    started = time.perf_counter()
    start_cursor = cursor
    try:
        fast = index.fast_index
        boundaries = fast.boundaries
        if not boundaries or not boundaries.document:
            raise RuntimeError("Dokumentgrenzen fehlen")
        doc_starts = boundaries.document._positions.astype(np.uint32, copy=False)
        sentence = getattr(boundaries, "sentence", None)
        sentence_starts = (
            sentence._positions.astype(np.uint32, copy=False)
            if sentence is not None
            else np.zeros(0, dtype=np.uint32)
        )
        if "sentence" in levels and sentence_starts.size == 0:
            raise RuntimeError("Satzgrenzen fehlen")
        token_count = int(fast.token_store.token_count)
        lexicon = fast.lexicons.word
        if lexicon is None:
            raise RuntimeError("Wortlexikon fehlt")
        whitespace = read_count_prefixed_array(
            corpus_path / "whitespace_after.bin",
            np.uint8,
            label="whitespace_after",
            missing_ok=True,
        )
        if whitespace is not None and int(whitespace.size) != token_count:
            whitespace = None

        _update_state(
            state_path,
            status="running",
            phase="text_export",
            progress=5 + int(15 * cursor / max(1, total_docs)),
            message=f"Korpustexte werden rekonstruiert ({cursor:,}/{total_docs:,}).",
        )
        for doc_id in range(cursor, total_docs):
            _check_cancel(state_path)
            doc_start = int(doc_starts[doc_id])
            doc_end = (
                int(doc_starts[doc_id + 1])
                if doc_id + 1 < total_docs
                else token_count
            )
            ids = fast.token_store.word_stream.get_range(doc_start, doc_end)
            raw_words = strings_for_ids(
                lexicon.offsets,
                lexicon.strings_view,
                ids.astype(np.uint32, copy=False),
                True,
            )
            words = [str(word) for word in raw_words]
            if doc_handle is not None:
                text = _render_tokens(words, doc_start, whitespace)[:TEXT_MAX_CHARS]
                _write_jsonl(doc_handle, {"text": text, "doc_id": doc_id})

            if sentence_handle is not None:
                left = int(np.searchsorted(sentence_starts, doc_start, side="left"))
                right = int(np.searchsorted(sentence_starts, doc_end, side="left"))
                starts = sentence_starts[left:right]
                if starts.size == 0 or int(starts[0]) > doc_start:
                    starts = np.insert(starts, 0, np.uint32(doc_start))
                for position, sentence_start_raw in enumerate(starts):
                    sentence_start = int(sentence_start_raw)
                    sentence_end = (
                        int(starts[position + 1])
                        if position + 1 < int(starts.size)
                        else doc_end
                    )
                    rel_start = sentence_start - doc_start
                    rel_end = sentence_end - doc_start
                    sentence_words = words[rel_start:rel_end]
                    sentence_text = _render_tokens(
                        sentence_words,
                        sentence_start,
                        whitespace,
                    ).strip()[:TEXT_MAX_CHARS]
                    if not sentence_text:
                        continue
                    _write_jsonl(
                        sentence_handle,
                        {
                            "text": sentence_text,
                            "doc_id": doc_id,
                            "sent_id": sentence_count,
                        },
                    )
                    sentence_count += 1

            completed = doc_id + 1
            if completed % EXPORT_CHECKPOINT_DOCS == 0 or completed == total_docs:
                for handle in (doc_handle, sentence_handle):
                    if handle is not None:
                        handle.flush()
                        os.fsync(handle.fileno())
                elapsed = max(time.perf_counter() - started, 1e-9)
                rate = (completed - start_cursor) / elapsed
                eta = (total_docs - completed) / rate if rate > 0 else None
                export = {
                    "cursor_doc": completed,
                    "sentence_count": sentence_count,
                    "offsets": {
                        "doc": doc_handle.tell() if doc_handle is not None else 0,
                        "sentence": sentence_handle.tell()
                        if sentence_handle is not None
                        else 0,
                    },
                    "complete": completed == total_docs,
                }
                _update_state(
                    state_path,
                    export=export,
                    progress=5 + int(15 * completed / max(1, total_docs)),
                    message=f"Korpustexte rekonstruiert: {completed:,}/{total_docs:,}.",
                    rate=rate,
                    eta_seconds=eta,
                )
    finally:
        for handle in (doc_handle, sentence_handle):
            if handle is not None:
                handle.close()
        index.close()

    if "sentence" in levels and sentence_count != expected_sentences:
        raise RuntimeError(
            f"Satzanzahl stimmt nicht: {sentence_count} != {expected_sentences}"
        )
    metadata = {
        "schema_version": "candyconc-semantic-texts-v1",
        "created_at": _now_iso(),
        "doc_jsonl": doc_path.name if "doc" in levels else None,
        "doc_count": total_docs,
        "sent_jsonl": sentence_path.name if "sentence" in levels else None,
        "sent_count": sentence_count,
        "embedding_text_max": TEXT_MAX_CHARS,
        "complete": True,
    }
    _atomic_json(artifacts / "gemma_texts_meta.json", metadata)
    export["complete"] = True
    _update_state(state_path, export=export, progress=20, eta_seconds=None)
    return export


def _run_mlx_worker(state_path: Path, artifacts: Path, python: Path) -> None:
    worker = Path(__file__).with_name("semantic_mlx_worker.py")
    command = [
        str(python),
        str(worker),
        "build",
        "--state",
        str(state_path),
        "--artifacts",
        str(artifacts),
        "--model",
        MODEL_NAME,
        "--batch",
        os.environ.get("CANDYCONC_MLX_BATCH", "16"),
        "--chunk",
        os.environ.get("CANDYCONC_MLX_CHUNK", "8192"),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        state = _read_state(state_path)
        if state.get("cancel_requested") or state.get("status") == "cancelled":
            raise BuildCancelled("Build wurde abgebrochen")
        raise RuntimeError(f"MLX-Worker endete mit Code {result.returncode}")


def _json_array_from_jsonl(
    source: Path,
    target: Path,
    *,
    kind: str,
    expected: int,
    doc_count: int,
) -> None:
    temporary = target.with_suffix(target.suffix + ".tmp")
    count = 0
    previous_doc_id = -1
    with source.open("r", encoding="utf-8") as input_handle, temporary.open(
        "w", encoding="utf-8"
    ) as output_handle:
        output_handle.write("[")
        first = True
        for line in input_handle:
            raw = line.strip()
            if not raw:
                continue
            item = json.loads(raw)
            doc_id = int(item.get("doc_id", -1))
            if not 0 <= doc_id < doc_count:
                raise RuntimeError(f"{kind}: ungültige doc_id {doc_id}")
            if doc_id < previous_doc_id:
                raise RuntimeError(f"{kind}: doc_id-Reihenfolge ist nicht monoton")
            if kind == "doc" and doc_id != count:
                raise RuntimeError(f"doc: Positionsfehler {doc_id} != {count}")
            if kind == "sentence" and int(item.get("sent_id", -1)) != count:
                raise RuntimeError(f"sentence: Positionsfehler bei {count}")
            previous_doc_id = doc_id
            if not first:
                output_handle.write(",")
            output_handle.write(raw)
            first = False
            count += 1
        output_handle.write("]")
        output_handle.flush()
        os.fsync(output_handle.fileno())
    if count != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{kind}: Textanzahl {count} != {expected}")
    os.replace(temporary, target)


def _validate_vectors(vectors: np.ndarray, expected: int, kind: str) -> None:
    if vectors.shape != (expected, DIMENSION) or vectors.dtype != np.float32:
        raise RuntimeError(f"{kind}: ungültige Vektorform {vectors.shape} {vectors.dtype}")
    for start in range(0, expected, 100_000):
        chunk = np.asarray(vectors[start : min(expected, start + 100_000)])
        if not np.isfinite(chunk).all():
            raise RuntimeError(f"{kind}: nicht-finite Vektoren ab Position {start}")
        norms = np.linalg.norm(chunk, axis=1)
        if float(np.max(np.abs(norms - 1.0))) > 1e-4:
            raise RuntimeError(f"{kind}: Vektoren sind nicht normalisiert")


def _build_faiss_and_texts(state_path: Path, artifacts: Path) -> dict[str, Any]:
    state = _read_state(state_path)
    levels = list(state.get("levels") or [])
    counts = dict(state.get("counts") or {})
    doc_count = int(counts.get("documents") or 0)
    selected_total = sum(
        doc_count if level == "doc" else int(counts.get("sentences") or 0)
        for level in levels
    )
    completed = 0
    report: dict[str, Any] = {
        "schema_version": "candyconc-semantic-index-report-v1",
        "run_id": state["run_id"],
        "model": MODEL_NAME,
        "runtime": "mlx-embeddings",
        "started_at": state.get("started_at"),
        "levels": {},
    }
    faiss.omp_set_num_threads(1)
    for level in levels:
        _check_cancel(state_path)
        expected = doc_count if level == "doc" else int(counts.get("sentences") or 0)
        vector_path = artifacts / f"gemma_{level}_vecs.npy"
        jsonl_path = artifacts / f"gemma_{level}_texts.jsonl"
        texts_path = artifacts / f"gemma_{level}_texts.json"
        index_path = artifacts / f"faiss_gemma_{level}.index"
        vectors = np.load(vector_path, mmap_mode="r")
        _update_state(
            state_path,
            phase="validation",
            progress=86 + int(8 * completed / max(1, selected_total)),
            message=f"{level}-Vektoren und IDs werden vollständig geprüft.",
            cancellable=True,
        )
        _validate_vectors(vectors, expected, level)
        _json_array_from_jsonl(
            jsonl_path,
            texts_path,
            kind=level,
            expected=expected,
            doc_count=doc_count,
        )
        _check_cancel(state_path)
        index = faiss.IndexFlatIP(DIMENSION)
        for start in range(0, expected, 100_000):
            index.add(
                np.asarray(
                    vectors[start : min(expected, start + 100_000)],
                    dtype=np.float32,
                )
            )
        if int(index.ntotal) != expected:
            raise RuntimeError(f"{level}: FAISS-Zählung {index.ntotal} != {expected}")
        temporary = index_path.with_suffix(index_path.suffix + ".tmp")
        faiss.write_index(index, str(temporary))
        os.replace(temporary, index_path)
        persisted = faiss.read_index(str(index_path))
        if int(persisted.ntotal) != expected:
            raise RuntimeError(f"{level}: gespeicherter FAISS-Index ist unvollständig")
        report["levels"][level] = {
            "count": expected,
            "dimension": DIMENSION,
            "normalized": True,
            "index_type": "flat_ip",
            "vectors_bytes": vector_path.stat().st_size,
            "texts_bytes": texts_path.stat().st_size,
            "faiss_bytes": index_path.stat().st_size,
        }
        completed += expected
        _update_state(
            state_path,
            progress=86 + int(8 * completed / max(1, selected_total)),
            message=f"{level}-Index ist validiert.",
        )
    report["completed_at"] = _now_iso()
    _atomic_json(artifacts / "semantic_index_build_report.json", report)
    return report


def _link_or_copy(source: Path, target: Path) -> None:
    target.unlink(missing_ok=True)
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def _commit(state_path: Path, artifacts: Path, report: dict[str, Any]) -> None:
    state = _read_state(state_path)
    corpus_path = Path(str(state["corpus_path"]))
    levels = list(state.get("levels") or [])
    marker = corpus_path / ".semantic_commit_in_progress"
    marker.write_text(str(state["run_id"]) + "\n", encoding="utf-8")
    _update_state(
        state_path,
        phase="commit",
        progress=96,
        message="Validierte semantische Artefakte werden aktiviert.",
        cancellable=False,
    )
    try:
        for level in levels:
            for name in (
                f"gemma_{level}_vecs.npy",
                f"gemma_{level}_texts.json",
                f"faiss_gemma_{level}.index",
            ):
                source = artifacts / name
                temporary = corpus_path / f".{name}.{state['run_id']}.next"
                _link_or_copy(source, temporary)
                os.replace(temporary, corpus_path / name)

        metadata_path = corpus_path / "embedding_meta.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}
        for level in levels:
            level_report = report["levels"][level]
            metadata[f"gemma_{level}"] = {
                "model": MODEL_NAME,
                "runtime": "mlx-embeddings",
                "query_provider": "managed_mlx",
                "dimension": DIMENSION,
                "count": int(level_report["count"]),
                "normalized": True,
                "faiss_mode": "flat",
                "index_type": "flat_ip",
                "document_prefix": "title: none | text: ",
                "query_prefix": "task: search result | query: ",
                "build_run_id": state["run_id"],
                "built_at": report["completed_at"],
            }
        metadata_temp = artifacts / "embedding_meta.json"
        _atomic_json(metadata_temp, metadata)
        report_source = artifacts / "semantic_index_build_report.json"
        for source, name in (
            (metadata_temp, "embedding_meta.json"),
            (report_source, "semantic_index_build_report.json"),
        ):
            temporary = corpus_path / f".{name}.{state['run_id']}.next"
            _link_or_copy(source, temporary)
            os.replace(temporary, corpus_path / name)
    finally:
        marker.unlink(missing_ok=True)


def run(state_path: Path, *, wait_for_launch: bool = False) -> int:
    if wait_for_launch:
        _wait_for_launch(state_path)
    state = _read_state(state_path)
    started_at = state.get("started_at") or _now_iso()
    _update_state(
        state_path,
        status="running",
        phase="starting",
        progress=max(0, int(state.get("progress") or 0)),
        message="Lokaler Semantik-Build läuft.",
        error="",
        pid=os.getpid(),
        started_at=started_at,
        finished_at=None,
        cancellable=True,
    )
    artifacts = Path(str(state["staging_dir"]))
    try:
        _check_cancel(state_path)
        runtime_python = _ensure_runtime(state_path)
        _export_texts(state_path, artifacts)
        _check_cancel(state_path)
        _update_state(
            state_path,
            phase="model_load",
            progress=max(20, int(_read_state(state_path).get("progress") or 0)),
            message="EmbeddingGemma wird geladen; beim ersten Lauf wird das Modell heruntergeladen.",
        )
        _run_mlx_worker(state_path, artifacts, runtime_python)
        _check_cancel(state_path)
        report = _build_faiss_and_texts(state_path, artifacts)
        _check_cancel(state_path)
        _commit(state_path, artifacts, report)
        _update_state(
            state_path,
            status="succeeded",
            phase="verified",
            progress=100,
            message="Lokaler semantischer Index wurde geprüft und aktiviert.",
            error="",
            result_ref=str(state["corpus_path"]),
            cancellable=False,
            finished_at=_now_iso(),
            eta_seconds=None,
        )
        shutil.rmtree(artifacts, ignore_errors=True)
        return 0
    except BuildCancelled:
        current = _read_state(state_path)
        _update_state(
            state_path,
            status="cancelled",
            phase="cancelled",
            message="Build wurde abgebrochen; der Zwischenstand bleibt fortsetzbar.",
            error="",
            cancellable=False,
            finished_at=current.get("finished_at") or _now_iso(),
        )
        return 130
    except Exception as exc:
        traceback.print_exc()
        _update_state(
            state_path,
            status="failed",
            phase="failed",
            message=f"Semantik-Build fehlgeschlagen: {exc}",
            error=str(exc),
            cancellable=False,
            finished_at=_now_iso(),
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--wait-for-launch", action="store_true")
    args = parser.parse_args()
    return run(args.state.expanduser().resolve(), wait_for_launch=args.wait_for_launch)


if __name__ == "__main__":
    raise SystemExit(main())
