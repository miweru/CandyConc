#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import numpy as np

from candyconc.config import get as _config_get

from candyconc.core.fast_index_backend import FastIndexBackend

try:
    import spacy
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"spaCy is missing: {exc}") from exc


_SAMPLE_MAX = 50_000
_ADD_BATCH = 10_000
_LOG_EVERY = int(os.environ.get("CANDYCONC_WORD_FAISS_LOG_EVERY", "100000") or 100000)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)


def _faiss_mode() -> str:
    mode = os.environ.get("CANDYCONC_FAISS_MODE", "auto").lower()
    if os.environ.get("CANDYCONC_FAISS_SAFE", "0") == "1":
        mode = "flat"
    if mode == "auto":
        mode = "flat" if sys.platform == "darwin" else "ivf"
    if (
        mode == "ivf"
        and sys.platform == "darwin"
        and os.environ.get("CANDYCONC_FAISS_ALLOW_IVF_DARWIN", "0") != "1"
    ):
        print(
            "FAISS IVF is disabled on macOS (stability). Using Flat. Set "
            "CANDYCONC_FAISS_ALLOW_IVF_DARWIN=1 to force it.",
            file=sys.stderr,
        )
        mode = "flat"
    return "flat" if mode not in ("ivf", "flat") else mode


def _resolve_spacy_model(index_path: Path, override: str | None) -> str:
    if override:
        return override
    for name in ("index_build_meta.json", "embedding_meta.json"):
        meta_path = index_path / name
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text("utf-8"))
                model = meta.get("spacy_model") if isinstance(meta, dict) else None
                if model:
                    return str(model)
            except Exception:
                continue
    return _config_get("CANDYCONC_EMB_SPACY_MODEL", "de_core_news_md")


def _build_word_faiss(index_path: Path, spacy_model: str | None = None) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    start_perf = time.perf_counter()
    backend = FastIndexBackend(index_path)
    lex = backend.lexicons.word
    vocab_size = int(getattr(lex, "_vocab_size", 0) or 0)
    if vocab_size <= 0:
        offsets = getattr(lex, "_offsets", None)
        if offsets is not None:
            vocab_size = max(int(len(offsets) - 1), 0)
    if vocab_size <= 1:
        raise RuntimeError("Word-Lexikon leer.")

    model_name = _resolve_spacy_model(index_path, spacy_model)
    LOGGER.info("Word FAISS: spaCy pipeline=%s", model_name)
    try:
        nlp = spacy.load(
            model_name,
            disable=["parser", "ner", "tagger", "lemmatizer", "attribute_ruler", "tok2vec", "senter"],
        )
    except OSError as exc:
        raise RuntimeError(f"spaCy embedding model '{model_name}' not available") from exc
    if nlp.vocab.vectors_length == 0:
        raise RuntimeError("spaCy Embeddings nicht verfuegbar.")

    try:
        import faiss  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "The word-vector index needs faiss, which is not installed. "
            "Install it with: pip install 'candyconc[semantic]'"
        ) from exc
    faiss_threads = os.environ.get("CANDYCONC_FAISS_THREADS")
    if not faiss_threads and sys.platform == "darwin":
        faiss_threads = "1"
    if faiss_threads:
        try:
            faiss.omp_set_num_threads(int(faiss_threads))
        except Exception:
            pass

    out_vecs = index_path / "word_vecs.tmp.bin"
    out_ids = index_path / "word_ids.npy"
    vec_fh = out_vecs.open("wb")
    ids_tmp = index_path / "word_ids.tmp.bin"
    ids_fh = ids_tmp.open("wb")

    dim = 0
    count = 0
    sample_chunks: List[np.ndarray] = []
    sample_count = 0

    for wid in range(1, vocab_size + 1):
        token = lex.get_string(wid)
        if not token:
            continue
        if not nlp.vocab.has_vector(token):
            continue
        vec = nlp.vocab.get_vector(token)
        if vec is None or not np.any(vec):
            continue
        vec = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            continue
        vec = vec / norm
        if dim == 0:
            dim = int(vec.shape[0])
        vec_fh.write(vec.tobytes())
        ids_fh.write(np.asarray([int(wid)], dtype=np.uint32).tobytes())
        count += 1
        if sample_count < _SAMPLE_MAX:
            sample_chunks.append(vec.copy())
            sample_count += 1
        if _LOG_EVERY > 0 and count % _LOG_EVERY == 0:
            LOGGER.info("Word FAISS: %d vectors collected", count)

    vec_fh.close()
    ids_fh.close()
    if count <= 0 or dim <= 0:
        raise RuntimeError("Keine Wortvektoren gefunden.")

    vecs_mem = np.memmap(out_vecs, dtype=np.float32, mode="r", shape=(count, dim))
    ids_mem = np.memmap(ids_tmp, dtype=np.uint32, mode="r", shape=(count,))
    ids_out = np.lib.format.open_memmap(out_ids, mode="w+", dtype=np.uint32, shape=(count,))
    for start in range(0, count, _ADD_BATCH):
        end = min(count, start + _ADD_BATCH)
        ids_out[start:end] = ids_mem[start:end]
    ids_out.flush()

    sample = np.vstack(sample_chunks) if sample_chunks else None
    nlist = max(1, min(4096, int(math.sqrt(count))))
    mode = _faiss_mode()
    trained = False
    if mode == "flat" or sample is None or sample.shape[0] < nlist:
        index = faiss.IndexFlatIP(dim)
        index_type = "flat_ip"
    else:
        quant = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quant, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        index.train(sample)
        trained = True
        index_type = "ivf_flat_ip"
    for start in range(0, count, _ADD_BATCH):
        end = min(count, start + _ADD_BATCH)
        index.add(np.asarray(vecs_mem[start:end], dtype=np.float32))
    faiss.write_index(index, str(index_path / "faiss_word.index"))
    LOGGER.info("Word FAISS: done (count=%d, dim=%d)", count, dim)

    meta_path = index_path / "embedding_meta.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except Exception:
            meta = {}
    meta["word_index"] = {
        "count": int(count),
        "dim": int(dim),
        "normalized": True,
        "spacy_model": model_name,
        "faiss_mode": mode,
        "nlist": int(nlist),
        "index_type": index_type,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=True, indent=2), encoding="utf-8")

    out_vecs.unlink(missing_ok=True)
    ids_tmp.unlink(missing_ok=True)

    ended_at = datetime.now(timezone.utc).isoformat()
    duration_s = round(time.perf_counter() - start_perf, 3)
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_s": duration_s,
        "index_root": str(index_path),
        "spacy_model": model_name,
        "vocab_size": int(vocab_size),
        "vector_count": int(count),
        "coverage": float(count) / float(vocab_size) if vocab_size else 0.0,
        "dim": int(dim),
        "faiss_mode": mode,
        "nlist": int(nlist),
        "index_type": index_type,
        "trained": trained,
        "index_path": str(index_path / "faiss_word.index"),
        "ids_path": str(out_ids),
        "embedding_meta": str(meta_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the word FAISS index from an existing fast index")
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--spacy-model", default=None)
    parser.add_argument("--out-report", type=Path, default=None)
    args = parser.parse_args(argv)
    report = _build_word_faiss(args.index, spacy_model=args.spacy_model)
    if args.out_report is None:
        args.out_report = args.index / "word_faiss.report.json"
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    report_md = args.out_report.with_suffix(".md")
    lines = [
        "# Word FAISS Build Report",
        "",
        f"- started_at: {report.get('started_at')}",
        f"- ended_at: {report.get('ended_at')}",
        f"- index_root: {report.get('index_root')}",
        f"- spacy_model: {report.get('spacy_model')}",
        f"- vocab_size: {report.get('vocab_size')}",
        f"- vector_count: {report.get('vector_count')}",
        f"- coverage: {report.get('coverage')}",
        f"- dim: {report.get('dim')}",
        f"- faiss_mode: {report.get('faiss_mode')}",
        f"- nlist: {report.get('nlist')}",
        f"- index_type: {report.get('index_type')}",
        f"- index_path: {report.get('index_path')}",
    ]
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
