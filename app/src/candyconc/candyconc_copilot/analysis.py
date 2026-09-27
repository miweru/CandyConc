import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Sequence

import numpy as np
import pandas as pd

from candyconc.analysis_defaults import (
    filter_frequency_frame,
    normalize_compare_collocate_frame,
    normalize_default_collocate_frame,
    summarize_dispersion_offsets,
)
from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.doc_search import document_search as _document_search
from candyconc.core.fast_index_native import strings_for_ids
from candyconc.core import query_runtime
from candyconc.config import get as get_config
from candyconc.services.semantic.availability import semantic_search_status
from candyconc.tools.word_sketch import word_sketch as _word_sketch
from candyconc.tools.collocate_stats import collocate_stats as _collocate_stats
from candyconc.services import embeddings
from candyconc.services.remote_embeddings import embed_remote
from candyconc import model_registry
from candyconc.services.tools.keyness import compute_keyness as _compute_keyness

if sys.platform == "darwin":
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:  # optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover - faiss missing
    faiss = None  # type: ignore

LOGGER = logging.getLogger(__name__)
_GEMMA_INDEX_CACHE: dict[str, tuple[object, list, bool]] = {}
_SEMANTIC_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def _resolve_fast_index_path(corpus: CorpusIndex | None) -> Path:
    if corpus is None or not hasattr(corpus, "fast_index") or corpus.fast_index is None:
        return Path(get_config("FAISS_DIR", "runtime") or "runtime")
    return Path(corpus.fast_index.index_path)


def collocate_stats(
    term: str,
    window: int = 5,
    *,
    lemmatizer: Callable[[str], str] | None = None,
    use_gpu: bool | None = None,
    corpus: CorpusIndex | None = None,
    doc_ids: Sequence[int] | None = None,
    within_sentence: bool = True,
    sort_by: str | None = None,
    min_freq: int | None = None,
) -> pd.DataFrame:
    """Return collocations for ``term`` using high-performance engine.

    ``min_freq=None``/``0`` = AUTO (H6/B6): the shared ``tools.collocate_stats``
    seam calibrates the co-occurrence floor deterministically on the node
    frequency (5 for frequent nodes, down to 2 for rare ones). Explicit values
    are passed through unclamped (the seam itself enforces the hard minimum of
    2); the applied floor is disclosed in ``df.attrs``.
    """
    if use_gpu is not None:
        LOGGER.debug("use_gpu ignored for fast collocation engine")
    df = _collocate_stats(
        term,
        window=window,
        lemmatizer=lemmatizer,
        within_sentence=within_sentence,
        top_n=None,
        sort_by=sort_by,
        corpus=corpus,
        doc_ids=doc_ids,
        min_count=min_freq,
    )
    return normalize_default_collocate_frame(df, sort_by)



def compare_collocates(
    term: str,
    window: int = 5,
    corpus: CorpusIndex | None = None,
) -> pd.DataFrame:
    """
    Compare collocations between Human and AI texts.
    Returns DataFrame with columns: word, freq_human, freq_ai, chi2_cell_human,
    chi2_cell_ai, log_ratio.
    """
    # Only supported by fast engine
    from candyconc.core.collocation_engine import get_engine

    idx = corpus or query_runtime._CORPUS_INDEX
    corpus_path = _resolve_fast_index_path(idx)
    engine = get_engine(corpus_path)
    df = engine.compare_human_ai(
        term=term,
        window_left=window,
        window_right=window,
        within_sentence=True
    )
    return normalize_compare_collocate_frame(df)


def word_sketch(term: str, *, top_rows: int = 8) -> Dict[str, pd.DataFrame]:
    """Return grammatical collocations grouped by dependency relation."""
    return _word_sketch(term, top_rows=top_rows)


def dispersion_offsets(term: str, *, corpus: CorpusIndex | None = None) -> list[int]:
    """Return token offsets for occurrences of ``term`` in the active corpus."""
    idx = corpus or query_runtime._CORPUS_INDEX
    if idx is None:
        raise RuntimeError("No corpus available. Index a corpus first.")
    return idx.sequence_positions([term])


def dispersion_profile(
    term: str,
    *,
    corpus: CorpusIndex | None = None,
    partitions: int = 10,
) -> dict[str, Any]:
    idx = corpus or query_runtime._CORPUS_INDEX
    if idx is None:
        raise RuntimeError("No corpus available. Index a corpus first.")
    offsets = np.asarray(
        idx.sequence_positions([term]), dtype=np.uint32
    )
    try:
        token_count = int(idx.token_count())
    except Exception:
        token_count = int(offsets.max()) + 1 if offsets.size else 0
    # Drive document-mode dispersion (the corrected Gries DP over real document
    # boundaries) so the copilot path matches the REST path. Fall back to the
    # positional-window mode only when boundaries are unavailable.
    doc_bounds = None
    try:
        boundaries = idx.fast_index.boundaries
        if boundaries and boundaries.document and boundaries.document._positions.size:
            doc_bounds = np.asarray(boundaries.document._positions, dtype=np.int64)
    except Exception:
        doc_bounds = None
    return {
        "term": str(term),
        "offsets": offsets.astype(int).tolist(),
        **summarize_dispersion_offsets(
            offsets, token_count=token_count, doc_bounds=doc_bounds, partitions=partitions
        ),
    }


def keyness(
    target: list[str],
    reference: list[str],
    *,
    pos_map: dict[str, str] | None = None,
    pos: str | None = None,
) -> pd.DataFrame:
    """Return chi-square cell contribution and log-likelihood scores.

    Parameters
    ----------
    pos_map:
        Optional mapping of token to POS tag. If provided together with ``pos``,
        only tokens whose tag starts with ``pos`` are included.
    pos:
        Part-of-speech prefix used for filtering. REQUIRES ``pos_map``:
        bare word lists carry no part of speech, so passing ``pos`` alone
        raises instead of silently returning unfiltered rows. The docset
        path does not need the map, it reads the tag from the index.
    """

    return _compute_keyness(target, reference, pos_map=pos_map, pos=pos)


def frequency_list(
    stopwords: Sequence[str] | None = None,
    *,
    corpus: CorpusIndex | None = None,
    use_gpu: bool | None = None,
    doc_ids: Sequence[int] | None = None,
    group_by: str = "word",
) -> pd.DataFrame:
    """Return word/lemma/POS counts for the active corpus as a DataFrame.

    Parameters
    ----------
    stopwords:
        Optional sequence of words to exclude from the list.
    """

    if corpus is None:
        corpus = query_runtime._CORPUS_INDEX

    if corpus is None:
        raise RuntimeError("Fast Index erforderlich für frequency_list")

    if doc_ids is not None:
        df = corpus.frequency_list_docset(doc_ids, stopwords=stopwords, attr=group_by)
    else:
        df = corpus.frequency_list(stopwords=stopwords, attr=group_by)
    return filter_frequency_frame(df)


def _cosine(v1: np.ndarray, v2: np.ndarray) -> float:
    """Return cosine similarity of ``v1`` and ``v2``."""
    denom = float(np.linalg.norm(v1) * np.linalg.norm(v2))
    if denom == 0.0:
        return 0.0
    return float(v1.dot(v2) / denom)


def _configure_faiss_index(index: Any | None) -> None:
    if index is None:
        return
    try:
        nprobe_raw = get_config("CANDYCONC_FAISS_NPROBE", "0")
        nprobe = int(nprobe_raw or 0)
    except Exception:
        nprobe = 0
    if nprobe <= 0:
        return
    if not hasattr(index, "nprobe"):
        return
    try:
        nlist = getattr(index, "nlist", None)
        if nlist:
            nprobe = min(int(nprobe), int(nlist))
        index.nprobe = int(nprobe)
    except Exception:
        return


def _semantic_index_type(index: Any | None) -> str:
    if index is None:
        return "unknown"
    return type(index).__name__ or "unknown"


def _semantic_candidate_exactness(index: Any | None) -> str:
    index_type = _semantic_index_type(index).lower()
    if index is None or index_type == "unknown":
        return "unknown"
    approximate_markers = ("ivf", "hnsw", "pq", "lsh", "annoy", "approx")
    if any(marker in index_type for marker in approximate_markers):
        return "approximate"
    if "flat" in index_type:
        return "exact"
    return "unknown"


def _semantic_response_meta(
    *,
    backend: str,
    level: str,
    method: str,
    index: Any | None,
    top_n: int,
    candidate_limit: int,
    candidate_count: int,
    total_vectors: int,
    lexical_seed_count: int,
    rerank_input_count: int,
    output_count: int,
    docset_doc_ids: set[int] | None,
    min_score: float,
    oversample: int | None = None,
) -> dict[str, Any]:
    exactness = _semantic_candidate_exactness(index)
    candidate_generation: dict[str, Any] = {
        "backend": backend,
        "level": level,
        "method": method,
        "indexType": _semantic_index_type(index),
        "searchMode": exactness,
        "requestedTopN": int(top_n),
        "candidateLimit": int(candidate_limit),
        "candidateCount": int(candidate_count),
        "totalVectors": int(total_vectors),
        "lexicalSeedCount": int(lexical_seed_count),
    }
    if oversample is not None:
        candidate_generation["oversample"] = int(oversample)
    return {
        "exactness": exactness,
        "candidateGeneration": candidate_generation,
        "rerank": {
            "enabled": True,
            "method": "lexical_overlap_then_vector_score",
            "inputCount": int(rerank_input_count),
            "outputCount": int(output_count),
        },
        "filtering": {
            "docsetApplied": docset_doc_ids is not None,
            "docsetDocCount": len(docset_doc_ids) if docset_doc_ids is not None else None,
            "minScore": float(min_score),
            "postFilterCandidateCount": int(candidate_count),
        },
    }


def _semantic_query_terms(term: str) -> list[str]:
    tokens = [tok.casefold() for tok in _SEMANTIC_TOKEN_RE.findall(term) if len(tok) > 1]
    return tokens or ([term.strip().casefold()] if term.strip() else [])


def _semantic_probe_terms(term: str) -> list[str]:
    normalized = term.strip()
    return [normalized] if normalized else []


def _semantic_lexical_rank(term: str, text: str) -> tuple[int, float, int]:
    norm_term = " ".join(_semantic_query_terms(term))
    norm_text = str(text).casefold()
    if not norm_text:
        return (0, 0.0, 0)
    phrase_hit = 1 if norm_term and norm_term in norm_text else 0
    query_terms = []
    for probe_term in _semantic_probe_terms(term):
        query_terms.extend(_semantic_query_terms(probe_term))
    if query_terms:
        query_terms = list(dict.fromkeys(query_terms))
    if not query_terms:
        return (phrase_hit, 0.0, 0)
    text_terms = set(_SEMANTIC_TOKEN_RE.findall(norm_text))
    token_hits = sum(1 for tok in query_terms if tok in text_terms or tok in norm_text)
    overlap = float(token_hits) / float(len(query_terms))
    return (phrase_hit, overlap, token_hits)


def _semantic_rerank_rows(term: str, rows: list[dict], top_n: int) -> list[dict]:
    scored: list[tuple[tuple[int, float, int, float], dict]] = []
    for row in rows:
        # SEM-01: every row converges here, so stamp the score's KIND once. The
        # lexical document-search seed rows already carry score_kind="lexical";
        # everything else is a FAISS row whose score IS a bounded cosine. The kind
        # travels with the score so the renderer (sibling frontend) labels it
        # honestly instead of painting a relevance value as a cosine %.
        row.setdefault("score_kind", "cosine")
        phrase_hit, overlap, token_hits = _semantic_lexical_rank(term, str(row.get("kw") or ""))
        score = float(row.get("score", 0.0) or 0.0)
        scored.append(((phrase_hit, overlap, token_hits, score), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:top_n]]


def _doc_id_for_position(corpus: CorpusIndex, pos: int) -> int | None:
    fast = corpus.fast_index
    doc_bounds = (
        fast.boundaries.document._positions
        if fast.boundaries and fast.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    if doc_bounds.size == 0:
        return 0 if pos >= 0 else None
    doc_id = int(np.searchsorted(doc_bounds, np.uint32(pos), side="right") - 1)
    if doc_id < 0 or doc_id >= int(doc_bounds.size):
        return None
    return doc_id


def _semantic_row_for_doc_id(
    corpus: CorpusIndex,
    doc_id: int,
    *,
    score: float,
    focus_pos: int | None = None,
    window: int = 30,
) -> dict[str, Any]:
    fast = corpus.fast_index
    doc_bounds = (
        fast.boundaries.document._positions
        if fast.boundaries and fast.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    token_count = int(fast.token_store.token_count)
    doc_start = int(doc_bounds[doc_id]) if doc_bounds.size else 0
    doc_end = int(doc_bounds[doc_id + 1]) if (doc_id + 1) < int(doc_bounds.size) else token_count
    snippet_start = doc_start
    snippet_end = doc_end
    if focus_pos is not None and doc_start <= int(focus_pos) < doc_end:
        snippet_start = max(doc_start, int(focus_pos) - int(window))
        snippet_end = min(doc_end, int(focus_pos) + int(window) + 1)
    ids = fast.token_store.word_stream.get_range(snippet_start, snippet_end)
    if ids.size == 0:
        text = ""
    else:
        word_lex = fast.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt.")
        words = strings_for_ids(
            word_lex.offsets,
            word_lex.strings_view,
            ids.astype(np.uint32, copy=False),
            True,
        )
        text = " ".join(str(word) for word in words).strip()
    if snippet_start > doc_start and text:
        text = f"... {text}"
    if snippet_end < doc_end and text:
        text = f"{text} ..."
    text_max = 800
    if len(text) > text_max:
        text = text[:text_max].rstrip()
    meta = fast.doc_metadata.get(int(doc_id), {}) if fast.doc_metadata else {}
    return {
        "left": "",
        "kw": text,
        "right": "",
        "score": float(score),
        # SEM-01: this score is the lexical document-search relevance (tf/tf-idf/
        # bm25), NOT a bounded cosine. Tag its kind so the renderer never paints
        # the rerank/overlap value as a cosine %.
        "score_kind": "lexical",
        "doc_id": int(doc_id),
        "meta": meta,
    }


def _lexical_semantic_seed_rows(
    term: str,
    corpus: CorpusIndex,
    *,
    top_n: int,
    docset_doc_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    if not _semantic_query_terms(term):
        return []
    if len(_semantic_query_terms(term)) > 4:
        return []
    probe = _document_search(corpus, term, top_n=max(int(top_n), 1), snippet=30)
    probe_terms = _semantic_probe_terms(term)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    per_probe_top_n = max(4, min(int(top_n), 8))
    for probe_term in probe_terms:
        if probe_term != term:
            probe = _document_search(corpus, probe_term, top_n=per_probe_top_n, snippet=30)
        for hit in probe:
            hit_pos = int(hit.get("pos", -1))
            doc_id = _doc_id_for_position(corpus, hit_pos)
            if doc_id is None or doc_id in seen:
                continue
            if docset_doc_ids is not None and int(doc_id) not in docset_doc_ids:
                continue
            seen.add(doc_id)
            rows.append(
                _semantic_row_for_doc_id(
                    corpus,
                    doc_id,
                    score=float(hit.get("score", 0.0)),
                    focus_pos=hit_pos,
                )
            )
            if len(rows) >= max(int(top_n), per_probe_top_n * 2):
                return rows
    return rows


def _load_gemma_index(
    corpus_path: Path, level: str = "doc"
) -> tuple[object, list, bool]:
    kind = "sentence" if level == "sentence" else "doc"
    idx_path = corpus_path / f"faiss_gemma_{kind}.index"
    texts_path = corpus_path / f"gemma_{kind}_texts.json"
    if not idx_path.exists() or not texts_path.exists():
        raise RuntimeError("Gemma Index fehlt. Bitte Index neu bauen.")
    cache_key = str(idx_path)
    cached = _GEMMA_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    index = model_registry.get_faiss_index(idx_path)
    _configure_faiss_index(index)
    texts = json.loads(texts_path.read_text(encoding="utf-8"))
    normalized = True
    meta_path = corpus_path / "embedding_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
            info = meta.get(f"gemma_{kind}") or {}
            if isinstance(info, dict) and "normalized" in info:
                normalized = bool(info.get("normalized"))
        except Exception:
            normalized = True
    _GEMMA_INDEX_CACHE[cache_key] = (index, texts, normalized)
    return _GEMMA_INDEX_CACHE[cache_key]


def _gemma_query_vector(term: str, corpus_path: Path, level: str) -> np.ndarray:
    meta_path = corpus_path / "embedding_meta.json"
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metadata = {}
    level_meta = metadata.get(f"gemma_{'sentence' if level == 'sentence' else 'doc'}") or {}
    if isinstance(level_meta, dict) and level_meta.get("query_provider") == "managed_mlx":
        from candyconc.services.local_mlx_embeddings import embed_local_mlx

        model = str(level_meta.get("model") or "mlx-community/embeddinggemma-300m-4bit")
        return embed_local_mlx([term], model=model).astype(np.float32, copy=False)
    endpoint = get_config("CANDYCONC_GEMMA_EMB_ENDPOINT", "http://127.0.0.1:1234/v1/embeddings")
    model = get_config("CANDYCONC_GEMMA_EMB_MODEL", "google/embedding-gemma-300m")
    batch = int(get_config("CANDYCONC_GEMMA_EMB_BATCH", "32") or 32)
    timeout = float(get_config("CANDYCONC_GEMMA_EMB_TIMEOUT", "120") or 120)
    vecs = embed_remote([term], endpoint=endpoint, model=model, batch_size=batch, timeout=timeout)
    if vecs.size == 0:
        raise RuntimeError("Gemma Embeddings leer")
    return vecs.astype(np.float32, copy=False)


def _semantic_search_gemma(
    term: str,
    *,
    top_n: int,
    level: str,
    backend: str = "gemma",
    docset_doc_ids: set[int] | None,
    min_score: float,
    corpus_index: CorpusIndex | None = None,
    return_meta: bool = False,
) -> list[dict] | tuple[list[dict], dict[str, Any]]:
    idx = corpus_index if corpus_index is not None else query_runtime._CORPUS_INDEX
    if idx is None:
        raise RuntimeError("Kein Korpus geladen.")
    corpus_path = _resolve_fast_index_path(idx)
    index, texts, normalized = _load_gemma_index(corpus_path, level=level)
    q = _gemma_query_vector(term, corpus_path, level)
    if normalized:
        norm = float(np.linalg.norm(q))
        if norm > 0:
            q = q / norm
    total = int(getattr(index, "ntotal", 0) or len(texts))
    total = min(total, len(texts))
    if total <= 0:
        if return_meta:
            meta = _semantic_response_meta(
                backend=backend,
                level=level,
                method="faiss_gemma",
                index=index,
                top_n=top_n,
                candidate_limit=0,
                candidate_count=0,
                total_vectors=0,
                lexical_seed_count=0,
                rerank_input_count=0,
                output_count=0,
                docset_doc_ids=docset_doc_ids,
                min_score=min_score,
            )
            return [], meta
        return []
    k = min(max(1, int(top_n) * 8), total)
    dist, idxs = index.search(q.astype(np.float32, copy=False), int(k))
    sims = dist[0] if dist is not None else []
    hits = idxs[0] if idxs is not None else []
    rows: list[dict] = []
    for score, hit_idx in zip(sims, hits):
        if hit_idx < 0:
            continue
        hit = int(hit_idx)
        if hit >= len(texts):
            continue
        if min_score > 0.0 and float(score) < float(min_score):
            continue
        item = texts[hit]
        doc_id = None
        meta = None
        chunk_id = None
        text = ""
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("kw") or item.get("passage") or "")
            doc_id = item.get("doc_id")
            meta = item.get("meta")
            chunk_id = item.get("sent_id") or item.get("chunk_id")
        else:
            text = str(item)
        if doc_id is not None and docset_doc_ids is not None:
            try:
                if int(doc_id) not in docset_doc_ids:
                    continue
            except Exception:
                continue
        row = {"left": "", "kw": text, "right": "", "score": float(score), "doc_id": doc_id, "meta": meta}
        if chunk_id is not None:
            row["chunk_id"] = chunk_id
        rows.append(row)
        if len(rows) >= k:
            break
    merged = rows
    lexical = _lexical_semantic_seed_rows(
        term,
        idx,
        top_n=max(top_n * 4, 16),
        docset_doc_ids=docset_doc_ids,
    )
    if lexical:
        by_doc: dict[int, dict[str, Any]] = {}
        for row in lexical + rows:
            doc_id = row.get("doc_id")
            if doc_id is None:
                continue
            by_doc[int(doc_id)] = row
        merged = list(by_doc.values())
    final_rows = _semantic_rerank_rows(term, merged, top_n)
    if return_meta:
        meta = _semantic_response_meta(
            backend=backend,
            level=level,
            method="faiss_gemma",
            index=index,
            top_n=top_n,
            candidate_limit=k,
            candidate_count=len(rows),
            total_vectors=total,
            lexical_seed_count=len(lexical),
            rerank_input_count=len(merged),
            output_count=len(final_rows),
            docset_doc_ids=docset_doc_ids,
            min_score=min_score,
        )
        return final_rows, meta
    return final_rows


def semantic_search(
    term: str,
    top_n: int = 10,
    ctx: int = 5,
    *,
    level: str = "doc",
    min_score: float = 0.0,
    docset_doc_ids: set[int] | None = None,
    oversample: int = 5,
    faiss_index: Any | None = None,
    passages: Sequence[Any] | None = None,
    corpus_index: CorpusIndex | None = None,
    backend: str | None = None,
    return_meta: bool = False,
) -> list[dict] | tuple[list[dict], dict[str, Any]]:
    """Return semantic search results using FAISS index."""
    idx = corpus_index if corpus_index is not None else query_runtime._CORPUS_INDEX
    corpus_path = _resolve_fast_index_path(idx)
    status = semantic_search_status(corpus_path, backend=backend, level=level)
    if not status.available:
        raise RuntimeError(status.message or "Embedding Search ist im Fast Index Modus deaktiviert")
    backend_name = (backend or get_config("CANDYCONC_EMB_BACKEND", "spacy")).strip().lower()
    if backend_name in {"gemma", "gemma_doc", "gemma_sentence"}:
        use_level = "sentence" if backend_name == "gemma_sentence" else level
        return _semantic_search_gemma(
            term,
            top_n=top_n,
            level=use_level,
            backend=backend_name,
            docset_doc_ids=docset_doc_ids,
            min_score=min_score,
            corpus_index=idx,
            return_meta=return_meta,
        )
    if backend_name == "none":
        raise RuntimeError("Embedding Backend ist deaktiviert")
    if faiss is None:
        raise RuntimeError("FAISS fehlt")
    if top_n <= 0:
        return []
    if docset_doc_ids is not None and idx is None:
        raise RuntimeError("Kein Korpus geladen.")
    index_path = corpus_path / "faiss_passage.index"
    meta_path = corpus_path / "passage_texts.json"
    if passages is None:
        if not meta_path.exists():
            raise RuntimeError("FAISS Metadaten fehlen")
        texts = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        texts = list(passages)
    if faiss_index is None:
        if not index_path.exists():
            raise RuntimeError("FAISS Index fehlt")
        index = model_registry.get_faiss_index(index_path)
    else:
        index = faiss_index
    _configure_faiss_index(index)
    # The query in the vector space of the passages: the pipeline that built
    # the passage index (embedding_meta.json), else CANDYCONC_EMB_SPACY_MODEL.
    q = embeddings.embed(
        [term], task="retrieval.query", pipeline=embeddings.passage_pipeline(corpus_path)
    ).astype(np.float32)
    # ANALYSIS-DISTRIBUTIONAL-01: the stored passage vectors are L2-normalized
    # (the build writes unit vectors), but the spaCy/jina query vector is NOT —
    # so the IndexFlatIP inner product was ||q||*cos, which the UI rendered as an
    # impossible 1900–2270 % "cosine". L2-normalize the query (the gemma path
    # already does this) so the inner product IS a bounded cosine in [-1, 1].
    # One source of truth: the REST embedding_search route and the copilot
    # semantic_search tool both flow through here.
    q_norm = float(np.linalg.norm(q[0])) if q.size else 0.0
    if q_norm > 0.0:
        q = q / q_norm
    total = int(getattr(index, "ntotal", 0) or len(texts))
    total = min(total, len(texts))
    if total <= 0:
        if return_meta:
            meta = _semantic_response_meta(
                backend=backend_name,
                level=level,
                method="faiss_passage",
                index=index,
                top_n=top_n,
                candidate_limit=0,
                candidate_count=0,
                total_vectors=0,
                lexical_seed_count=0,
                rerank_input_count=0,
                output_count=0,
                docset_doc_ids=docset_doc_ids,
                min_score=min_score,
                oversample=oversample,
            )
            return [], meta
        return []
    k = max(1, int(top_n) * 8)
    if docset_doc_ids:
        k = max(k, int(top_n) * max(1, int(oversample or 1)))
    k = min(k, total)
    rows: list[dict] = []
    seen: set[int] = set()
    while True:
        dist, idxs = index.search(q, int(k))
        sims = dist[0] if dist is not None else []
        hits = idxs[0] if idxs is not None else []
        if min_score > 0.0 and len(sims):
            if float(sims[-1]) < float(min_score) and not docset_doc_ids:
                hits = [h for h, s in zip(hits, sims) if float(s) >= float(min_score)]
                sims = [s for s in sims if float(s) >= float(min_score)]
        for score, hit_idx in zip(sims, hits):
            if hit_idx < 0:
                continue
            hit = int(hit_idx)
            if hit >= len(texts):
                continue
            if hit in seen:
                continue
            seen.add(hit)
            if min_score > 0.0 and float(score) < float(min_score):
                continue
            item = texts[hit]
            doc_id = None
            meta = None
            chunk_id = None
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("kw") or item.get("passage") or "")
                doc_id = item.get("doc_id")
                meta = item.get("meta")
                chunk_id = item.get("chunk_id")
            else:
                text = str(item)
            if doc_id is None:
                doc_id = hit
            if docset_doc_ids is not None:
                try:
                    doc_id_int = int(doc_id)
                except Exception:
                    continue
                if doc_id_int not in docset_doc_ids:
                    continue
            row = {"left": "", "kw": text, "right": "", "score": float(score), "doc_id": doc_id, "meta": meta}
            if chunk_id is not None:
                row["chunk_id"] = chunk_id
            rows.append(row)
            if len(rows) >= k:
                break
        if len(rows) >= k or k >= total:
            break
        k = min(total, max(int(k) * 2, int(top_n)))
    merged = rows
    lexical: list[dict[str, Any]] = []
    if idx is not None:
        lexical = _lexical_semantic_seed_rows(
            term,
            idx,
            top_n=max(top_n * 4, 16),
            docset_doc_ids=docset_doc_ids,
        )
        if lexical:
            merged = best_passage_per_document(lexical, rows)
    final_rows = _semantic_rerank_rows(term, merged, top_n)
    if return_meta:
        meta = _semantic_response_meta(
            backend=backend_name,
            level=level,
            method="faiss_passage",
            index=index,
            top_n=top_n,
            candidate_limit=k,
            candidate_count=len(rows),
            total_vectors=total,
            lexical_seed_count=len(lexical),
            rerank_input_count=len(merged),
            output_count=len(final_rows),
            docset_doc_ids=docset_doc_ids,
            min_score=min_score,
            oversample=oversample,
        )
        return final_rows, meta
    return final_rows


def embedding_search(
    term: str,
    embeddings: Dict[str, Sequence[float]] | None = None,
    top_n: int = 3,
    ctx: int = 5,
) -> list[dict]:
    """Return semantic search results using the Fast Index FAISS artifacts."""
    _ = embeddings
    result = semantic_search(term, top_n=top_n, ctx=ctx)
    return result[0] if isinstance(result, tuple) else result



def run_cqlf_query(query: str, ctx: int = 5) -> dict:
    """Execute ``query`` against the active corpus and return KWIC rows.

    CQL attribute failures remain visible; this never weakens the requested
    expression into a semantically different plain-text search.

    .. deprecated::
        FT-COPILOT-PARITY introduced :func:`run_cqlf_query_full`, which returns a
        ``total``/``truncated`` envelope and honours sort/docset/case/limit. This
        thin form is retained for backwards compatibility (it now reuses the
        full implementation and exposes the truncation flag) but the copilot
        wrapper drives the richer entry point.
    """
    result = run_cqlf_query_full(query, ctx=ctx)
    return {
        "status": result["status"],
        "rows": result["rows"],
        "total": result["total"],
        "truncated": result["truncated"],
    }


_RUN_CQLF_DEFAULT_LIMIT = 50
_RUN_CQLF_MAX_LIMIT = 1000


def _bounded_run_cqlf_limit(limit: int | None) -> int:
    """Clamp the copilot KWIC row limit into ``[1, _RUN_CQLF_MAX_LIMIT]``."""
    if limit is None:
        return _RUN_CQLF_DEFAULT_LIMIT
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return _RUN_CQLF_DEFAULT_LIMIT
    if value <= 0:
        return _RUN_CQLF_DEFAULT_LIMIT
    return min(value, _RUN_CQLF_MAX_LIMIT)


def vorgabe_seed(abfrage: str, bereich: str) -> int:
    """Derive a reproducible default sample seed from the query and subcorpus.

    A constant seed would repeatedly select the same quantiles of ordered hit
    lists. Query-specific seeds vary those selections while keeping each call
    repeatable and reporting the seed used.
    """
    import zlib

    return zlib.crc32(f"{abfrage}\x1f{bereich}".encode("utf-8")) & 0x7FFFFFFF


def stichprobe_statt_indexkopf(
    ergebnis: Dict[str, Any],
    *,
    sample: Any,
    seed: Any,
    sort_by: Any,
    ziehen: Callable[..., Dict[str, Any]],
    seed_vorgabe: int,
) -> Dict[str, Any]:
    """Sample run_cqlf_query results when sample, seed and sorting are unspecified.

    Use the REST sampling path over the full hit population with a reproducible
    query-specific seed. Report its requested size, drawn size, seed and population.
    Preserve explicit sampling or sorting and complete results within the limit.
    If the index cannot support sampling, retain the prefix without a sample label.
    """
    from .tool_errors import ToolInputError

    zeilen = ergebnis.get("rows") or []
    # sort_by allein ist keine Bitte um den Indexkopf. Sortiert wurden bisher
    # die ersten limit Treffer nach Korpusposition: in Kandidat 4
    # (r5a-wort-gegen-lemma, sort_by="1R") kamen alle 50 Zeilen aus Claude und
    # aus den zwei vordersten Quellen (Pruefer Evidenzfluss, 2026-09-26). Jetzt
    # wird gezogen und die Ziehung sortiert. Nur "position" verlangt ausdruecklich
    # die Indexreihenfolge.
    indexfolge = str(sort_by or "").strip().lower() == "position"
    if sample is not None or seed is not None or indexfolge or int(ergebnis.get("total") or 0) <= len(zeilen):
        return ergebnis
    try:
        gezogen = ziehen(sample_size=int(ergebnis.get("limit") or len(zeilen)), seed_value=int(seed_vorgabe))
    except ToolInputError:
        return ergebnis
    return {**ergebnis, "rows": gezogen["rows"], "sample": gezogen["sample"],
            "truncated": int(ergebnis["total"]) > len(gezogen["rows"])}


def trefferfolge_aus_dem_index(row: Dict[str, Any], idx: Any) -> "Dict[str, Any] | None":
    """Read match and match_tokens directly at the hit's index positions.

    Splitting displayed context loses whitespace tokens and cannot recover a
    match longer than the context. Read the complete token sequence in the same
    display form as its context. Return None only without a readable index.
    Keep left context and extend right context through rechts_hinter_dem_treffer.
    """
    try:
        pos = int(row["pos"])
        versatz = sorted({0, *(int(o) for o in row.get("match_offsets") or [])})
        speicher, lexikon = idx.fast_index.token_store, idx.fast_index.lexicons.word
        anfang, ende = pos + versatz[0], pos + versatz[-1] + 1
        if lexikon is None or anfang < 0 or ende > int(speicher.token_count):
            return None
        ids = speicher.word_stream.get_range_i32(anfang, ende)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if int(ids.size) != ende - anfang:
        return None
    from candyconc.core.source_spacing import display_flags, join_tokens_with_starts
    from candyconc.utils.text_normalize import normalize_index_display_text as _anzeige

    roh = [lexikon.get_string(int(ids[o - versatz[0]])) for o in versatz]
    ws = display_flags(idx)
    if ws is not None and versatz == list(range(versatz[0], versatz[-1] + 1)):
        # A contiguous match with the spacing of the text, like left and right.
        treffer, _starts = join_tokens_with_starts(roh, anfang, ws)
    else:
        treffer = _anzeige(" ".join(roh))
    return {"match": treffer, "match_tokens": [_anzeige(t) for t in roh]}


def cql_faltung(abfrage: str) -> tuple[int, int]:
    """Wie viele Wertbedingungen einer CQL-Abfrage %c tragen, und wie viele es gibt.

    Gelesen am Parser der Suchmaschine, auf dem Text, den sie ausfuehrt.
    Metadaten in where() sind keine Tokenbedingungen und zaehlen nicht mit,
    eine Wertmenge [lemma in {"a","b"}%c] ist eine gefaltete Bedingung. Die
    fruehere Textregel zaehlte jeden Wert in Anfuehrungszeichen und sah beide
    Faelle als ungefaltet. Sie zaehlt nur noch, wo der Parser die Abfrage
    nicht annimmt (dann scheitert die Abfrage ohnehin mit ihrer Meldung).
    """
    from cqlhpc.parser import parse_cql

    from candyconc.core.cql_macros import normalize_query_input
    from candyconc.utils.text_normalize import normalize_text_basic

    text = normalize_query_input(normalize_text_basic(str(abfrage or "")))
    text = text[4:].strip() if text.lower().startswith("cql:") else text
    try:
        offen = [parse_cql(text)]
    except Exception:
        werte = re.findall(r"""(?:"[^"]*"|'[^']*')\s*(%[a-z]+)?""", text)
        return sum("c" in (flag or "") for flag in werte), len(werte)
    gefaltet = alle = 0
    while offen:
        knoten = offen.pop()
        for bedingung in getattr(getattr(knoten, "clause", None), "conds", ()):
            alle += 1
            gefaltet += "c" in (bedingung.flags or "")
        # Seq und Alt tragen Teile, Quant, Within und Where einen Knoten. Das
        # where() selbst (expr) bleibt aussen vor.
        offen.extend(getattr(knoten, "parts", ()) or getattr(knoten, "options", ()))
        if getattr(knoten, "node", None) is not None:
            offen.append(knoten.node)
    return gefaltet, alle


def rechts_hinter_dem_treffer(row: Dict[str, Any], idx: Any, ctx: Any) -> Dict[str, Any]:
    """Extend right context to ctx tokens beyond the end of a multi-token hit.

    Right context still starts after the pivot. Extending its endpoint keeps
    the continuation visible when the match itself is longer than ctx.
    """
    try:
        pos, ende, weite = int(row["pos"]), max(int(o) for o in row.get("match_offsets") or [0]), int(ctx)
    except (KeyError, TypeError, ValueError):
        return row
    lesen = getattr(getattr(idx, "fast_index", None), "kwic_rows_for_positions", None)
    if ende <= 0 or weite <= 0 or lesen is None:
        return row
    breit = lesen(
        np.asarray([pos], dtype=np.uint32), ende + weite, include_arcs=False, include_file=False)
    if not breit:
        return row
    from candyconc.core.source_spacing import TOKEN_STARTS, apply_source_spacing, display_flags
    from candyconc.services.backend.kwic_renderer import normalise_kwic_row_display

    lang = dict(breit[0])
    ws = display_flags(idx)
    if ws is not None and isinstance(row.get(TOKEN_STARTS), dict):
        # The row has the spacing of the text, the longer right context too.
        lang["pos"] = pos
        apply_source_spacing(lang, ws)
        starts = lang.get(TOKEN_STARTS)
        if isinstance(starts, dict) and "right" in starts:
            neu = normalise_kwic_row_display(lang)
            return {
                **row,
                "right": neu.get("right", row.get("right")),
                TOKEN_STARTS: {**row[TOKEN_STARTS], "right": starts["right"]},
            }
        # The longer context does not map to its tokens: its offsets are unknown.
        rest = {k: v for k, v in row[TOKEN_STARTS].items() if k != "right"}
        return {**row, "right": normalise_kwic_row_display(lang).get("right", row.get("right")),
                TOKEN_STARTS: rest}
    return {**row, "right": normalise_kwic_row_display(lang).get("right", row.get("right"))}


def cql_faltet(abfrage: str) -> bool:
    """Faltet diese CQL-Abfrage Gross-/Kleinschreibung? Nur %c am Wert tut es.

    Der Parameter ``case_insensitive`` wirkt allein auf die einfache
    Wortsuche (siehe unten). Bis zum 2026-09-25 meldeten run_cqlf_query und
    query_count fuer CQL trotzdem den Parameter: [word="zusammenfassend"]
    fand 52 kleingeschriebene Treffer, die Klartextsuche 1.489, beide
    meldeten case_insensitive=true, und ein Modell, das der Meldung glaubte,
    drehte sich 126.194 Denk-Token lang im Kreis.
    """
    gefaltet, alle = cql_faltung(abfrage)
    return alle > 0 and gefaltet == alle


def abfrage_methode(query: str, *, case_insensitive: bool) -> Dict[str, Any]:
    """Report query mode, attribute and folding for query and count results.

    Treat every form routed to the CQL parser, including within(), as CQL.
    Only %c folds CQL values. When just some values use it, retain a false
    query-wide case_insensitive value and report faltung_teilweise.
    """
    from candyconc.core.cql_macros import _looks_like_bare_cql

    stripped = str(query or "").strip()
    if not (stripped.lower().startswith("cql:") or stripped.startswith("[") or _looks_like_bare_cql(stripped)):
        return {"query_mode": "plain_word", "attribute": "word", "case_insensitive": bool(case_insensitive)}
    gefaltet, alle = cql_faltung(stripped)
    methode: Dict[str, Any] = {
        "query_mode": "cqlf",
        "attribute": "explicit_in_query",
        "case_insensitive": alle > 0 and gefaltet == alle,
    }
    if 0 < gefaltet < alle:
        methode["faltung_teilweise"] = f"%c an {gefaltet} von {alle} Werten"
    return methode


def run_cqlf_query_full(
    query: str,
    *,
    ctx: int = 5,
    corpus: CorpusIndex | None = None,
    docset_mask: np.ndarray | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    case_insensitive: bool = True,
    limit: int | None = None,
) -> dict:
    """Execute ``query`` and return ``{status, rows, total, truncated, ...}``.

    FT-COPILOT-PARITY: the legacy :func:`run_cqlf_query` hard-capped at 50 rows
    with NO total/truncated flag — a grounding hazard, because the copilot could
    not tell a 50-row PAGE from a 50-hit corpus. This brings the copilot KWIC
    path up to REST ``/query`` parity:

    - ``total`` is the EXACT hit count (resolved via ``run_query``'s ``count_cb``,
      the same primitive the REST count uses), independent of the row cap.
    - ``truncated`` is ``total > len(rows)``.
    - ``sort_by``/``sort_dir`` reuse ``kwic_renderer.sort_kwic_rows`` (AntConc
      vocabulary: 1L/2L/3L/node/1R/2R/3R/meta:FIELD).
    - ``case_insensitive`` mirrors the export/search contract: a bare single
      token is rewritten to ``cql:[word="X" %c]`` (CI) or ``cql:[word="X"]``
      (case-sensitive), since the plain-term path is case-insensitive by default.
    - ``docset_mask`` scopes the query to a subcorpus.

    Attribute errors fail closed: retrying CQL as plain text can change the
    matched language, especially by collapsing a multi-cell span to one token.
    """
    from candyconc.services.backend.kwic_renderer import parse_sort, sort_kwic_rows

    idx = corpus if corpus is not None else query_runtime._CORPUS_INDEX
    if idx is None:
        raise RuntimeError("No corpus available. Index a corpus first.")

    try:
        sort_spec = parse_sort(sort_by)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    row_limit = _bounded_run_cqlf_limit(limit)

    # Case-folding rewrite (mirrors _collect_export_rows): only a bare single
    # token can be safely rewritten to an explicit word cell without changing the
    # matched language.
    effective = str(query or "")
    stripped = effective.strip()
    # Strip query quotation marks before counting a quoted plain word.
    zitiert = len(stripped) > 2 and stripped[0] in "\"'" and stripped[-1] == stripped[0]
    # = und ~ gehen ebenfalls an die Wortsuche: word=und schrieb die Umschreibung
    # als Wortform in eine Zelle und zaehlte still 0, die Wortsuche nennt dafuer
    # die Form in Klammern (wortsuche_hinweis). Woertliche Formen zaehlen gleich.
    is_simple = bool(stripped) and not zitiert and not stripped.lower().startswith("cql:") \
        and not any(ch.isspace() for ch in stripped) \
        and not any(ch in stripped for ch in "*?[]{}()|+.^$\\=~")
    if is_simple:
        escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
        effective = f'cql:[word="{escaped}" %c]' if case_insensitive else f'cql:[word="{escaped}"]'

    total_holder: dict[str, int] = {}

    def _count_cb(total: int) -> None:
        total_holder["total"] = int(total)

    def _execute(q: str) -> list[dict]:
        return list(
            query_runtime.run_query(
                q,
                ctx,
                corpus=idx,
                limit=row_limit,
                docset_mask=docset_mask,
                count_cb=_count_cb,
                include_file=True,
            )
        )

    rows = _execute(effective)

    if sort_spec is not None:
        rows = sort_kwic_rows(rows, sort_by, sort_dir=sort_dir)

    # total: the count_cb fires with the EXACT hit count when the scan completes
    # within budget. When the result is genuinely capped (more hits than the row
    # limit) the callback is suppressed by run_query; in that case the floor is
    # the returned row count, and truncated must be True.
    total = total_holder.get("total")
    if total is None:
        # The exact-count callback was suppressed because the scan was genuinely
        # capped. The cql: branch still yields an exact count, but the un-prefixed
        # plain-bracket path ([pos=NOUN]) does not — so resolve the exact total via
        # the SAME primitive REST /query/count uses, instead of reporting the
        # row-cap floor as the total (COPILOT-COUNT-BRACKETCQL-DIVERGE: total used
        # to read 5 for [pos=NOUN] while REST/query_count read 9740).
        # Scheitert diese Zaehlung, gibt es keine Zahl, die Meldung geht an den
        # Aufrufer. Hier stand ein Rueckfall auf len(rows): "Und OR Oder" meldete
        # total 1 statt 125, NOT ueber einem grossen Korpus total 5 bei 54.663
        # Treffern, beides als vollstaendig (2026-09-26).
        from candyconc.services.backend.server import _compute_query_count

        exact, _ms, _partial = _compute_query_count(
            idx,
            str(query or ""),
            0,
            None,
            None,
            docset_mask,
            case_insensitive=case_insensitive,
        )
        total = int(exact)
        truncated = int(total) > len(rows)
    else:
        truncated = int(total) > len(rows)
    return {
        "status": "success",
        "rows": rows,
        "total": int(total),
        "truncated": bool(truncated),
        "limit": int(row_limit),
    }


def best_passage_per_document(
    lexical: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Eine Zeile je Dokument: die staerkste Passage der Vektorsuche, sonst die lexikalische.

    ``rows`` kommen absteigend nach Aehnlichkeit aus dem Passagenindex. Die
    Vorfassung ueberschrieb je Dokument mit der jeweils letzten Zeile und
    behielt damit die schwaechste Passage (Methodenbefund B9 der Session
    CandyConc Paper, 2026-09-26).
    """
    by_doc: dict[int, dict[str, Any]] = {}
    for row in lexical:
        doc_id = row.get("doc_id")
        if doc_id is not None:
            by_doc[int(doc_id)] = row
    aus_vektorsuche: set[int] = set()
    for row in rows:
        doc_id = row.get("doc_id")
        if doc_id is None or int(doc_id) in aus_vektorsuche:
            continue
        aus_vektorsuche.add(int(doc_id))
        by_doc[int(doc_id)] = row
    return list(by_doc.values())
