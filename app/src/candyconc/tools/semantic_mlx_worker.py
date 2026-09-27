"""Isolated MLX process used for semantic-index builds and query vectors."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mlx.core as mx
import numpy as np
from mlx_embeddings import load


DIMENSION = 768
DOCUMENT_PREFIX = "title: none | text: "
QUERY_PREFIX = "task: search result | query: "
MEMORY_LIMIT = 8 * 1024**3
CACHE_LIMIT = 512 * 1024**2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Build-State ist ungültig")
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
        raise KeyboardInterrupt


def _embed(model: Any, tokenizer: Any, texts: list[str], *, prefix: str) -> np.ndarray:
    encoded = tokenizer(
        [prefix + text for text in texts],
        padding=True,
        truncation=True,
        max_length=2048,
        return_tensors="mlx",
    )
    output = model(encoded["input_ids"], encoded["attention_mask"]).text_embeds
    mx.eval(output)
    vectors = np.asarray(output, dtype=np.float32)
    if vectors.shape != (len(texts), DIMENSION):
        raise RuntimeError(f"Unerwartete Vektorform: {vectors.shape}")
    if not np.isfinite(vectors).all():
        raise RuntimeError("Embedding enthält nicht-finite Werte")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise RuntimeError("Embedding enthält Nullvektor")
    return vectors / norms


def _build_level(
    *,
    kind: str,
    model: Any,
    tokenizer: Any,
    source: Path,
    artifacts: Path,
    total: int,
    batch_size: int,
    chunk_size: int,
    state_path: Path,
    completed_before: int,
    selected_total: int,
) -> int:
    final_path = artifacts / f"gemma_{kind}_vecs.npy"
    partial_path = artifacts / f"gemma_{kind}_vecs.partial.npy"
    state = _read_state(state_path)
    cursors = dict(state.get("cursors") or {})
    cursor = int(cursors.get(kind) or 0)

    if final_path.is_file():
        existing = np.load(final_path, mmap_mode="r")
        if existing.shape != (total, DIMENSION) or existing.dtype != np.float32:
            raise RuntimeError(f"{kind}: vorhandene Finaldatei ist ungültig")
        cursor = total
        cursors[kind] = total
        _update_state(state_path, cursors=cursors)
        return total

    if cursor == 0:
        vectors = np.lib.format.open_memmap(
            partial_path,
            mode="w+",
            dtype=np.float32,
            shape=(total, DIMENSION),
        )
    else:
        if not partial_path.is_file():
            raise RuntimeError(f"{kind}: Partialdatei fehlt bei Cursor {cursor}")
        vectors = np.load(partial_path, mmap_mode="r+")
        if vectors.shape != (total, DIMENSION) or vectors.dtype != np.float32:
            raise RuntimeError(f"{kind}: Partialdatei ist ungültig")

    started = time.perf_counter()
    start_cursor = cursor
    with source.open("r", encoding="utf-8") as handle:
        for _ in itertools.islice(handle, cursor):
            pass
        while cursor < total:
            _check_cancel(state_path)
            lines = list(itertools.islice(handle, min(chunk_size, total - cursor)))
            if not lines:
                raise RuntimeError(f"{kind}: Textinput endet bei {cursor}/{total}")
            items = [json.loads(line) for line in lines]
            texts = [str(item.get("text") or " ") for item in items]
            order = sorted(range(len(texts)), key=lambda index: len(texts[index]))
            chunk_vectors = np.empty((len(texts), DIMENSION), dtype=np.float32)
            for offset in range(0, len(order), batch_size):
                positions = order[offset : offset + batch_size]
                batch = [texts[position] for position in positions]
                chunk_vectors[positions] = _embed(
                    model,
                    tokenizer,
                    batch,
                    prefix=DOCUMENT_PREFIX,
                )
            end = cursor + len(texts)
            vectors[cursor:end] = chunk_vectors
            vectors.flush()
            cursor = end
            cursors[kind] = cursor
            del chunk_vectors, texts, items
            mx.clear_cache()
            elapsed = max(time.perf_counter() - started, 1e-9)
            rate = (cursor - start_cursor) / elapsed
            completed = completed_before + cursor
            eta = (selected_total - completed) / rate if rate > 0 else None
            _update_state(
                state_path,
                status="running",
                phase=f"embed_{kind}",
                progress=20 + int(65 * completed / max(1, selected_total)),
                message=f"{kind}-Embeddings: {cursor:,}/{total:,}.",
                cursors=cursors,
                rate=rate,
                eta_seconds=eta,
                mlx_memory={
                    "active_bytes": int(mx.get_active_memory()),
                    "cache_bytes": int(mx.get_cache_memory()),
                    "peak_bytes": int(mx.get_peak_memory()),
                },
            )

    del vectors
    os.replace(partial_path, final_path)
    cursors[kind] = total
    _update_state(state_path, cursors=cursors)
    return total


def build(args: argparse.Namespace) -> int:
    state_path = args.state.expanduser().resolve()
    artifacts = args.artifacts.expanduser().resolve()
    state = _read_state(state_path)
    levels = list(state.get("levels") or [])
    counts = dict(state.get("counts") or {})
    totals = {
        "doc": int(counts.get("documents") or 0),
        "sentence": int(counts.get("sentences") or 0),
    }
    selected_total = sum(totals[level] for level in levels)
    mx.set_memory_limit(MEMORY_LIMIT)
    mx.set_cache_limit(CACHE_LIMIT)
    _update_state(
        state_path,
        phase="model_load",
        message="EmbeddingGemma wird in der isolierten MLX-Laufzeit geladen.",
    )
    model, tokenizer = load(args.model)
    _update_state(
        state_path,
        phase="model_ready",
        message="EmbeddingGemma ist geladen.",
    )
    completed = 0
    metadata = json.loads((artifacts / "gemma_texts_meta.json").read_text(encoding="utf-8"))
    for level in levels:
        source_name = metadata["doc_jsonl" if level == "doc" else "sent_jsonl"]
        completed += _build_level(
            kind=level,
            model=model,
            tokenizer=tokenizer,
            source=artifacts / str(source_name),
            artifacts=artifacts,
            total=totals[level],
            batch_size=max(1, int(args.batch)),
            chunk_size=max(1, int(args.chunk)),
            state_path=state_path,
            completed_before=completed,
            selected_total=selected_total,
        )
    _update_state(
        state_path,
        phase="embeddings_complete",
        progress=85,
        message="Alle ausgewählten Embeddings sind erzeugt.",
        rate=None,
        eta_seconds=None,
    )
    return 0


def query_server(args: argparse.Namespace) -> int:
    mx.set_memory_limit(MEMORY_LIMIT)
    mx.set_cache_limit(CACHE_LIMIT)
    model, tokenizer = load(args.model)
    print(
        json.dumps({"status": "ready", "model": args.model, "dimension": DIMENSION}),
        flush=True,
    )
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            raw_inputs = request.get("input")
            inputs = [raw_inputs] if isinstance(raw_inputs, str) else list(raw_inputs or [])
            vectors = _embed(
                model,
                tokenizer,
                [str(item) for item in inputs],
                prefix=QUERY_PREFIX,
            )
            response = {
                "id": request_id,
                "data": vectors.tolist(),
                "model": args.model,
            }
        except Exception as exc:
            response = {"id": request_id, "error": str(exc)}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--state", type=Path, required=True)
    build_parser.add_argument("--artifacts", type=Path, required=True)
    build_parser.add_argument("--model", default="mlx-community/embeddinggemma-300m-4bit")
    build_parser.add_argument("--batch", type=int, default=16)
    build_parser.add_argument("--chunk", type=int, default=8192)
    query_parser = subparsers.add_parser("query-server")
    query_parser.add_argument("--model", default="mlx-community/embeddinggemma-300m-4bit")
    args = parser.parse_args()
    if args.command == "build":
        return build(args)
    return query_server(args)


if __name__ == "__main__":
    raise SystemExit(main())
