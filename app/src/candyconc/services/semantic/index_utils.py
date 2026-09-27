from __future__ import annotations

import argparse
import json
import os
import sys
import shutil
import math
from pathlib import Path
from typing import Sequence, Iterable, Callable, Any

import numpy as np
import logging

from candyconc.config import APP_CONFIG
from candyconc.i18n import lt

if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:  # optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover - faiss missing
    faiss = None  # type: ignore

logger = logging.getLogger(__name__)

_FAISS_MISSING = lt(
    "FAISS fehlt. Bitte faiss installieren oder Embedding Search deaktivieren.",
    "FAISS is missing. Install faiss or disable embedding search.",
)

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
        logger.warning(
            "FAISS IVF is off on macOS (stability). Using Flat. "
            "Set CANDYCONC_FAISS_ALLOW_IVF_DARWIN=1 to force IVF."
        )
        mode = "flat"
    return "flat" if mode not in ("ivf", "flat") else mode


def _load_texts(path: Path) -> list[str]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(t) for t in data]
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_faiss_index(
    corpus: Path | str | Iterable[str],
    out_dir: Path | str,
    nlist: int = 256,
    *,
    progress_cb: Callable[[int, str], Any] | None = None,
    confirm: Callable[[int], bool] | None = None,
) -> None:
    """Build FAISS IVF-Flat index from corpus and store on disk."""
    if faiss is None:
        raise RuntimeError(_FAISS_MISSING)
    from candyconc.services import embeddings

    faiss_threads = os.environ.get("CANDYCONC_FAISS_THREADS")
    if not faiss_threads and sys.platform == "darwin":
        faiss_threads = "1"
    if faiss_threads:
        try:
            faiss.omp_set_num_threads(int(faiss_threads))
        except Exception:
            pass

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    vecs_path = out / "passage_vecs.npy"
    texts_path = out / "passage_texts.json"

    if isinstance(corpus, (str, Path)):
        corpus_path = Path(corpus).expanduser().resolve()
        src_vecs_path = corpus_path / "passage_vecs.npy"
        src_texts_path = corpus_path / "passage_texts.json"
        if not src_vecs_path.exists():
            raise RuntimeError(
                lt(
                    "passage_vecs.npy fehlt. Bitte Embeddings beim Indexbuild erzeugen.",
                    "passage_vecs.npy is missing. Create embeddings when building the index.",
                )
            )
        if not src_texts_path.exists():
            raise RuntimeError(
                lt(
                    "passage_texts.json fehlt. Bitte Embeddings beim Indexbuild erzeugen.",
                    "passage_texts.json is missing. Create embeddings when building the index.",
                )
            )
        vecs = np.load(src_vecs_path, mmap_mode="r")
        if progress_cb:
            progress_cb(10, "loaded")
    else:
        texts = [str(text) for text in corpus]
        if not texts:
            raise RuntimeError(lt("Korpus ist leer.", "The corpus is empty."))
        vecs = embeddings.embed(texts, task="retrieval.document", confirm=confirm).astype(np.float32, copy=False)
        np.save(vecs_path, vecs)
        texts_path.write_text(json.dumps(texts, ensure_ascii=True), encoding="utf-8")
        corpus_path = out
        if progress_cb:
            progress_cb(10, "embedded")

    d = vecs.shape[1]
    # FAISS IndexFlatIP / METRIC_INNER_PRODUCT computes raw dot products; to make that
    # equal cosine similarity the vectors MUST be L2-normalized. Normalize a writable
    # COPY so the on-disk raw vectors (passage_vecs.npy) stay unmodified.
    vecs = np.ascontiguousarray(vecs, dtype=np.float32).copy()
    faiss.normalize_L2(vecs)
    mode = _faiss_mode()
    if mode == "flat":
        index = faiss.IndexFlatIP(d)
        index.add(vecs)
        if progress_cb:
            progress_cb(80, "added")
    else:
        quantizer = faiss.IndexFlatIP(d)
        index = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_INNER_PRODUCT)
        sample_max = int(os.environ.get("CANDYCONC_FAISS_SAMPLE_MAX", "50000") or 50000)
        if sample_max > 0 and vecs.shape[0] > sample_max:
            rng = np.random.default_rng(0)
            sample_idx = rng.choice(vecs.shape[0], size=sample_max, replace=False)
            sample = np.asarray(vecs[sample_idx], dtype=np.float32)
        else:
            sample = np.asarray(vecs, dtype=np.float32)
        index.train(sample)
        if progress_cb:
            progress_cb(60, "trained")
        index.add(vecs)
        if progress_cb:
            progress_cb(80, "added")
    faiss.write_index(index, str(out / "faiss_passage.index"))
    if out.resolve() != corpus_path.resolve():
        shutil.copyfile(corpus_path / "passage_vecs.npy", vecs_path)
        shutil.copyfile(corpus_path / "passage_texts.json", texts_path)
        if progress_cb and vecs_path.stat().st_size > 2 * 1024 * 1024 * 1024:
            progress_cb(95, "warn_disk_space")
    else:
        if progress_cb and vecs_path.stat().st_size > 2 * 1024 * 1024 * 1024:
            progress_cb(95, "warn_disk_space")
    if progress_cb:
        progress_cb(100, "saved")


def build_faiss_index_from_fast_index(
    index_dir: Path | str,
    out_dir: Path | str,
    *,
    batch_size: int = 64,
    text_max_chars: int = 2000,
    progress_cb: Callable[[int, str], Any] | None = None,
    confirm: Callable[[int], bool] | None = None,
) -> None:
    """Build semantic search assets directly from an existing Fast Index."""

    if faiss is None:
        raise RuntimeError(_FAISS_MISSING)

    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core.fast_index_native import strings_for_ids
    from candyconc.core.word_vectors import vector_pipeline
    from candyconc.services import embeddings

    index_path = Path(index_dir).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    # The passages are embedded with the word vectors of the corpus pipeline,
    # like the thesaurus and sim(). A corpus without them gets the reason.
    pipeline = vector_pipeline(index_path)
    idx = CorpusIndex(index_path)
    try:
        fast = idx.fast_index
        doc_bounds = (
            fast.boundaries.document._positions
            if fast.boundaries and fast.boundaries.document
            else np.array([], dtype=np.uint32)
        )
        doc_count = int(doc_bounds.size)
        if doc_count <= 0:
            raise RuntimeError(lt("Fast Index enthält keine Dokumentgrenzen.", "The index has no document boundaries."))
        if progress_cb:
            progress_cb(5, "loaded")

        lex = fast.lexicons.word
        if lex is None:
            raise RuntimeError(lt("Word Lexikon fehlt.", "Word lexicon is missing."))

        token_count = int(fast.token_store.token_count)
        word_stream = fast.token_store.word_stream
        texts: list[dict[str, Any]] = []
        vecs_mem = None
        vec_path = out / "passage_vecs.npy"
        out.mkdir(parents=True, exist_ok=True)

        batches = max(1, math.ceil(doc_count / max(1, int(batch_size))))
        for batch_idx, start_doc in enumerate(range(0, doc_count, max(1, int(batch_size))), start=1):
            end_doc = min(doc_count, start_doc + max(1, int(batch_size)))
            batch_texts: list[str] = []
            for doc_id in range(start_doc, end_doc):
                doc_start = int(doc_bounds[doc_id])
                doc_end = int(doc_bounds[doc_id + 1]) if (doc_id + 1) < doc_count else token_count
                ids = word_stream.get_range(doc_start, doc_end)
                if ids.size == 0:
                    text = ""
                else:
                    words = strings_for_ids(
                        lex.offsets,
                        lex.strings_view,
                        ids.astype(np.uint32, copy=False),
                        True,
                    )
                    text = " ".join(str(word) for word in words).strip()
                if text_max_chars > 0 and len(text) > int(text_max_chars):
                    text = text[: int(text_max_chars)].rstrip()
                meta = fast.doc_metadata.get(int(doc_id), {}) if fast.doc_metadata else {}
                texts.append({"doc_id": int(doc_id), "text": text, "meta": meta})
                batch_texts.append(text or " ")

            batch_vecs = embeddings.embed(
                batch_texts, task="retrieval.document", confirm=confirm, pipeline=pipeline
            ).astype(np.float32, copy=False)
            if vecs_mem is None:
                vecs_mem = np.lib.format.open_memmap(
                    vec_path,
                    mode="w+",
                    dtype=np.float32,
                    shape=(doc_count, int(batch_vecs.shape[1])),
                )
            vecs_mem[start_doc:end_doc] = batch_vecs
            if progress_cb:
                progress = 5 + int(65 * (batch_idx / batches))
                progress_cb(progress, f"embedded:{end_doc}/{doc_count}")

        if vecs_mem is None:
            raise RuntimeError("Keine Embeddings erzeugt")
        vecs_mem.flush()

        texts_path = out / "passage_texts.json"
        texts_path.write_text(json.dumps(texts, ensure_ascii=True), encoding="utf-8")

        build_faiss_index(out, out, progress_cb=progress_cb, confirm=confirm)

        meta = {
            "backend": getattr(APP_CONFIG, "CANDYCONC_EMB_BACKEND", "spacy") or "spacy",
            "spacy_model": pipeline,
            "doc_count": int(doc_count),
        }
        (out / "embedding_meta.json").write_text(json.dumps(meta, ensure_ascii=True, indent=2), encoding="utf-8")
    finally:
        idx.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("corpus")
    b.add_argument("--out", default="runtime")
    b.add_argument("--nlist", type=int, default=256)
    f = sub.add_parser("build-fast-index")
    f.add_argument("index_dir")
    f.add_argument("--out", default=None)
    f.add_argument("--batch-size", type=int, default=64)
    f.add_argument("--text-max-chars", type=int, default=2000)
    args = parser.parse_args(argv)

    if args.cmd == "build":
        build_faiss_index(
            Path(args.corpus).expanduser().resolve(),
            Path(args.out).expanduser().resolve(),
            nlist=args.nlist,
        )
    if args.cmd == "build-fast-index":
        out = args.out or args.index_dir
        build_faiss_index_from_fast_index(
            Path(args.index_dir).expanduser().resolve(),
            Path(out).expanduser().resolve(),
            batch_size=args.batch_size,
            text_max_chars=args.text_max_chars,
        )


if __name__ == "__main__":  # pragma: no cover - CLI
    main()
