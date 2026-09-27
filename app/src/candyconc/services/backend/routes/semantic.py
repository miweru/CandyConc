"""Semantic clustering + embedding-package routes.

POST /api/v1/semantic/cluster          — cluster semantic search hits (FAISS vectors)
POST /api/v1/semantic/cluster_words    — cluster a token list, LLM-label each cluster
POST /api/v1/semantic/recluster        — LLM merge/split/rename plan for clusters
PUT  /api/v1/semantic/clusters/apply   — validate and echo a merge/split/rename plan
POST /api/v1/semantic/outline          — Markdown outline export for clusters
GET  /api/v1/embeddings/list           — available embedding packages + install state
POST /api/v1/embeddings/download       — download an embedding package (admin)
POST /api/v1/embeddings/remove         — remove an installed embedding package (admin)
GET  /api/v1/settings/embeddings       embedding backend, accepted values, spaCy pipeline (admin)
POST /api/v1/settings/embeddings       set the embedding backend to spacy or none (admin)

Extracted verbatim from ``server.py`` (route-extraction slice 3, Master-Plan W0
anchors guard the OpenAPI shape). Helpers used only by these routes moved here
(``_RECLUSTER_SCHEMA`` + ``_validate_recluster``, the semantic_cluster /
recluster_prompt / cluster_labeler / embedding_package imports); shared server
internals (``manager`` — the FAISS ``_ManagerProxy`` singleton — plus
``get_index``, ``call_llm_async``, ``_EXPORT_DIR``/``DRY_RUN`` shared with the
/download and /export routes, and ``_require_admin_access``) are imported lazily
inside the handlers to avoid a circular import (server.py imports this module at
load time) and to keep test monkeypatches on ``server`` attributes working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from typing import Annotated, Any, Dict, List, Optional

import jsonschema
import numpy as np
from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel, Field

from candyconc.config import get as get_config
from candyconc.config import set as set_config
from candyconc.core import cql_macros, word_vectors
from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, lt
from candyconc.services import embeddings
from candyconc.services.cluster_labeler import generate_label
from candyconc.services.recluster_prompt import (
    SYSTEM_PROMPT as RECLUSTER_SYSTEM_PROMPT,
    build_prompt as build_recluster_prompt,
)
from candyconc.services.semantic_cluster import (
    cluster_vectors,
    cluster_words,
    label_cluster,
    remap_split_idxs,
    similarity_matrix,
)
from candyconc.services.backend.operation_runs import operation_run_registry
from candyconc.services.backend.query_count import _word_vectors_error
from candyconc.services import semantic_index_jobs
from candyconc.services.backend.schemas import OperationRunLaunchResponse
from candyconc.services.backend.schemas import OperationRunSnapshot
from candyconc.tools.embedding_package import (
    download_embedding,
    EMB_DIR,
)
from .. import auth

router = CandyAPIRouter()

logger = logging.getLogger(__name__)


class LocalSemanticIndexBuildRequest(BaseModel):
    corpus: str = "default"
    levels: List[str] = Field(default_factory=lambda: ["doc"])


_RECLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "merges": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "integer"}},
        },
        "splits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "subsets": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                },
                "required": ["id", "subsets"],
            },
        },
        "renames": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
}


def _validate_recluster(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise recluster JSON."""

    jsonschema.validate(data, _RECLUSTER_SCHEMA)
    renames = data.get("renames", {})
    labels = list(renames.values())
    if len(labels) != len(set(labels)):
        raise ValueError("duplicate labels")
    for lab in labels:
        if len(str(lab).split()) > 3:
            raise ValueError("label too long")
    return data


class SimilarWordNeighbour(BaseModel):
    """A corpus-restricted distributional neighbour with its cosine score."""

    word: str
    score: float
    corpus_frequency: int = 0
    shared_query_vector: bool | None = Field(
        default=None,
        description="Exact equality with the spaCy query vector. Null when not checked.",
    )


class SimilarWordsResponse(BaseModel):
    """Ranked distributional thesaurus neighbours for ``term``."""

    status: str = "success"
    term: str
    backend: str
    neighbours: List[SimilarWordNeighbour] = Field(default_factory=list)


_SIM_MAX_K = int(get_config("CANDYCONC_SIM_MAX_K", "2000") or 2000)
_SIM_DEFAULT_K = int(get_config("CANDYCONC_SIM_DEFAULT_K", "20") or 20)


def _bounded_sim_k(value: Any) -> int:
    """Clamp the requested neighbour count to [1, CANDYCONC_SIM_MAX_K]."""
    try:
        parsed = int(value if value is not None else _SIM_DEFAULT_K)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="k must be an integer") from exc
    if parsed < 1:
        raise HTTPException(status_code=422, detail="k must be >= 1")
    if _SIM_MAX_K > 0 and parsed > _SIM_MAX_K:
        parsed = _SIM_MAX_K
    return parsed


def _embeddings_unavailable_message(exc: Exception) -> bool:
    """True when a thesaurus RuntimeError signals a missing embedding INDEX/asset.

    The engine raises ``RuntimeError`` for two fundamentally different conditions,
    and conflating them misreports a per-term miss as a service outage:

    * a genuine service outage — the embedding backend / word lexicon / vectors
      are unavailable for THIS corpus ("Word-Lexikon fehlt", "spaCy Embeddings
      nicht verfügbar", "spaCy Modell hat keine Vektoren"). These must surface as
      a 503 ``word_vectors.service_error``.
    * a per-term miss — the index is present and works for other terms, but THIS
      seed produced no result: nothing cleared the similarity threshold
      ("... oberhalb Score ...") OR the seed term itself has no embedding, i.e.
      it is out-of-vocabulary ("Keine Embeddings für sim() gefunden."). Neither
      is an outage; both are an honest empty 200 (the UI's "Keine Nachbarn"
      empty-state), not a "Vektorindex fehlt" hard error.

    Returns ``True`` only for the genuine-outage class.
    """
    lowered = str(exc).lower()
    # Per-term misses (index present, this seed yielded nothing) => empty result.
    if "oberhalb score" in lowered:
        # "Keine ähnlichen Korpuswörter ... oberhalb Score ..." => empty result.
        return False
    if "keine embeddings für sim()" in lowered:
        # Out-of-vocabulary seed: nlp(term).vector is all-zero, so the term is not
        # in the embedding vocabulary. The index/backend is fine for other terms.
        return False
    return True


def _resolve_corpus_and_docset(server_module: Any, corpus: Any, docset_id: Any):
    """Return (corpus_index, doc_ids|None), validating docset↔corpus binding."""
    idx = server_module.get_corpus(corpus)
    doc_ids = None
    if docset_id:
        docset = server_module._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(
                422,
                "docset.corpus_mismatch",
                lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"),
            )
        doc_ids = docset.get("doc_ids")
    return idx, doc_ids


def _corpus_frequency_lookup(idx: Any, doc_ids: Any) -> Dict[str, int]:
    """Word -> frequency map for the corpus (or docset slice when given)."""
    if doc_ids is not None:
        df = idx.frequency_list_docset(doc_ids)
    else:
        df = idx.frequency_list()
    freq: Dict[str, int] = {}
    for row in df.to_dicts():
        word = row.get("word")
        if word is None:
            continue
        freq[str(word)] = int(row.get("f", 0) or 0)
    return freq


# ONE human message for the word_similarity capability gate, shared by the REST
# 503 detail, the copilot tool's degradation ``reason`` and sim() (SEM-01/V9: one
# decision, one text). The decision itself is core.word_vectors.
WORD_SIMILARITY_UNAVAILABLE_MESSAGE = word_vectors.UNAVAILABLE_MESSAGE


def _word_similarity_available(idx: Any) -> bool:
    """True when THIS corpus has the word-similarity capability (one source of truth).

    Mirrors the ``semantic.word_similarity`` feature the UI and copilot gate on
    (domain.corpus._corpus_feature_descriptor → core.word_vectors).
    Without it the engine still produces spaCy-fallback neighbours, but those are
    NOT a corpus word-similarity result — so the REST route must gate them out the
    same way, instead of advertising a capability the corpus does not have.
    """
    from candyconc.domain.corpus import corpus_summary

    try:
        index_dir = idx.fast_index.index_path
        summary = corpus_summary(index_dir)
    except Exception:
        # Fail CLOSED: if the capability descriptor cannot be read, availability is
        # UNCONFIRMED, so the honest contract is "not available" — the same 503 the
        # UI/copilot honor — NOT a pass-through to spaCy-fallback neighbours the
        # corpus may not actually back. A gate that fails open here would advertise
        # a capability we could not verify (and silently re-open the OOV-vs-outage
        # honesty path on a word_similarity:false corpus).
        return False
    return bool(summary.get("features", {}).get("semantic", {}).get("word_similarity", False))


def _word_similarity_error(idx: Any) -> ApiError:
    """The answer for a corpus without usable word vectors.

    422 ``word_vectors.unavailable`` when the corpus has none, 503
    ``word_vectors.service_error`` when the server cannot load them. The same
    codes as sim() in a query (query_count._word_vectors_error).
    """
    try:
        source = word_vectors.resolve_word_vectors(idx.fast_index.index_path)
    except Exception:
        source = None
    if source is None or source.available:
        # The capability could not be confirmed (the gate fails closed).
        error = word_vectors.WordVectorsServiceError(word_vectors.SERVICE_ERROR_MESSAGE)
    else:
        error = word_vectors.unavailable_error(source)
    mapped = _word_vectors_error(error)
    assert mapped is not None
    return mapped


def _word_similarity_backend(idx: Any) -> str:
    """Return the backend that built this corpus's word-neighbour index."""
    configured = str(get_config("CANDYCONC_EMB_BACKEND", "spacy") or "spacy").strip().lower()
    try:
        meta_path = idx.fast_index.index_path / "embedding_meta.json"
        word_meta = json.loads(meta_path.read_text("utf-8")).get("word_index", {})
        if isinstance(word_meta, dict):
            if word_meta.get("spacy_model"):
                return "spacy"
            actual = word_meta.get("backend") or word_meta.get("model")
            if actual:
                return str(actual).strip().lower()
    except Exception:
        pass
    return configured


def _build_similar_words_payload(
    server_module: Any,
    *,
    term: str,
    k: int,
    min_score: float | None,
    corpus: Any,
    docset_id: Any,
) -> SimilarWordsResponse:
    term = (term or "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="Missing term")
    idx, doc_ids = _resolve_corpus_and_docset(server_module, corpus, docset_id)
    backend = _word_similarity_backend(idx)

    # P3 gate: a corpus without the word_similarity capability has no word
    # thesaurus. Answer like sim() in a query (422 or 503 with the reason),
    # rather than with spaCy-fallback neighbours the corpus cannot back.
    if not _word_similarity_available(idx):
        raise _word_similarity_error(idx)

    threshold = float(min_score) if min_score is not None else None

    try:
        scored = cql_macros.similar_words_scored(term, k, idx)
    except RuntimeError as exc:
        mapped = _word_vectors_error(exc)
        if mapped is not None:
            raise mapped from exc
        if _embeddings_unavailable_message(exc):
            raise ApiError(
                503,
                "word_vectors.service_error",
                word_vectors.SERVICE_ERROR_MESSAGE + " " + exception_text(exc),
            ) from exc
        # No neighbour cleared the engine threshold -> empty (not an error).
        return SimilarWordsResponse(status="success", term=term, backend=backend, neighbours=[])

    freq = _corpus_frequency_lookup(idx, doc_ids)
    neighbours: List[SimilarWordNeighbour] = []
    for entry in scored:
        word = str(entry.get("word", ""))
        if not word or word == term:
            # Drop the seed term itself; callers want neighbours.
            continue
        raw_score = entry.get("score")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        if threshold is not None and score < threshold:
            continue
        corpus_frequency = int(freq.get(word, 0))
        if corpus_frequency < 1:
            # Corpus-restricted contract: a neighbour the embedding backend knows
            # but that is absent from THIS corpus is not a corpus neighbour. The
            # engine ranks over the backend vocabulary, so drop the non-present
            # words here rather than advertise a "corpus-restricted" word with
            # frequency 0.
            continue
        neighbours.append(
            SimilarWordNeighbour(
                word=word,
                score=score,
                corpus_frequency=corpus_frequency,
                shared_query_vector=entry.get("shared_query_vector"),
            )
        )
    neighbours.sort(key=lambda n: n.score, reverse=True)
    return SimilarWordsResponse(
        status="success", term=term, backend=backend, neighbours=neighbours
    )


@router.get(
    "/semantic/similar_words",
    response_model=SimilarWordsResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "term": "freedom",
                        "backend": "spacy",
                        "neighbours": [
                            {"word": "liberty", "score": 0.82, "corpus_frequency": 41},
                            {"word": "democracy", "score": 0.71, "corpus_frequency": 12},
                        ],
                    }
                }
            }
        }
    },
)
async def semantic_similar_words_get(
    term: str,
    k: int = _SIM_DEFAULT_K,
    min_score: Optional[float] = None,
    corpus: Optional[str] = None,
    docset_id: Optional[str] = None,
) -> SimilarWordsResponse:
    """Corpus-restricted distributional thesaurus neighbours for ``term``.

    Promotes the similarity engine that previously only fed sim() query
    expansion: returns the (word, cosine score) neighbours that live in the
    indexed corpus, joined with their corpus frequency. Empty ``neighbours`` (not
    an error) when nothing clears the threshold. A corpus without word vectors
    answers 422 ``word_vectors.unavailable``, a corpus whose vectors the server
    cannot load (pipeline not installed) 503 ``word_vectors.service_error``,
    both with the reason in ``detail``, like sim() in a query.
    """
    from .. import server as _server

    bounded_k = _bounded_sim_k(k)
    return await asyncio.to_thread(
        _build_similar_words_payload,
        _server,
        term=term,
        k=bounded_k,
        min_score=min_score,
        corpus=corpus,
        docset_id=docset_id,
    )


@router.post(
    "/semantic/cluster",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [{"cluster_id": 0, "size": 12, "label": "politics", "sample_sentence": "..." }]
                }
            }
        }
    },
)
async def semantic_cluster_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {"summary": "Cluster IDs", "value": {"ids": [1, 2, 3], "min_size": 2}},
        },
    ),
) -> List[Dict[str, Any]]:
    """Return clustered semantic search hits."""
    from .. import server as _server

    ids = payload.get("ids") or []
    if not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="ids must be list")
    raw_min_size = payload.get("min_size")
    min_size = int(raw_min_size) if raw_min_size is not None else (2 if len(ids) < 16 else 3 if len(ids) < 24 else 5)
    if len(ids) > 1000:
        ids = ids[:1000]
    if not _server.manager.passages:
        raise HTTPException(status_code=503, detail="index missing")
    if _server.manager.faiss_index_obj is not None:
        vecs = [_server.manager.faiss_index_obj.reconstruct(int(i)) for i in ids]
    elif _server.manager.faiss_vecs_mmap is not None:
        vecs = [_server.manager.faiss_vecs_mmap[int(i)] for i in ids]
    else:
        raise HTTPException(status_code=503, detail="index missing")
    texts = _server.manager.passages
    labels = cluster_vectors(vecs, min_size=min_size)
    results = []
    for label in sorted(set(labels)):
        if label == -1:
            continue
        idxs = [j for j, lab in enumerate(labels) if lab == label]
        cluster_doc_ids = [int(ids[j]) for j in idxs if int(ids[j]) < len(texts)]
        if not cluster_doc_ids:
            continue
        cluster_texts = [texts[int(doc_id)] for doc_id in cluster_doc_ids]
        idx = _server.get_index()
        results.append(
            {
                "cluster_id": int(label),
                "size": len(idxs),
                "label": label_cluster(idx, cluster_doc_ids),
                "sample_sentence": cluster_texts[0].split(".")[0],
            }
        )
    return results


@router.post(
    "/semantic/cluster_words",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [{"cluster_id": 0, "size": 5, "label": "energy", "samples": ["..."]}]
                }
            }
        }
    },
)
async def semantic_cluster_words_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Token Cluster",
                "value": {"tokens": ["energy", "oil", "gas"], "examples": ["..."], "corpus": "sotu_en"},
            }
        },
    ),
) -> List[Dict[str, Any]]:
    """Return clusters for a list of tokens.

    The tokens are embedded with the word vectors of the corpus pipeline
    (``corpus``, default the active corpus), like the thesaurus. A corpus
    without word vectors answers 422 ``word_vectors.unavailable``, a corpus
    whose pipeline is not installed 503 ``word_vectors.service_error``.
    """
    from .. import server as _server

    tokens = payload.get("tokens") or []
    if not isinstance(tokens, list):
        raise HTTPException(status_code=400, detail="tokens must be list")
    examples = payload.get("examples") or []
    raw_min_size = payload.get("min_size")
    min_size = int(raw_min_size) if raw_min_size is not None else (2 if len(tokens) < 16 else 3 if len(tokens) < 24 else 5)
    idx = _server.get_corpus(payload.get("corpus") or None)
    try:
        pipeline = word_vectors.vector_pipeline(idx.fast_index.index_path)
        clusters = await asyncio.to_thread(cluster_words, tokens, min_size=min_size, pipeline=pipeline)
    except RuntimeError as exc:
        mapped = _word_vectors_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    results: List[Dict[str, Any]] = []
    misc: List[int] = []
    for c in clusters:
        idxs = c["idxs"]
        if len(idxs) < min_size or c["cluster"] == -1:
            misc.extend(idxs)
            continue
        samples = [examples[i] for i in idxs if i < len(examples)][:3]
        label = await generate_label(samples)
        if not label:
            label = "misc"
        results.append(
            {
                "cluster_id": int(c["cluster"]),
                "size": len(idxs),
                "label": label,
                "samples": samples,
            }
        )
    if misc:
        samples = [examples[i] for i in misc if i < len(examples)][:3]
        results.append(
            {
                "cluster_id": -1,
                "size": len(misc),
                "label": "misc",
                "samples": samples,
            }
        )
    return results


@router.post(
    "/semantic/recluster",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"merges": [], "splits": [], "renames": {"1": "politics"}}
                }
            }
        }
    },
)
async def semantic_recluster_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Recluster Plan",
                "value": {"clusters": [{"id": 1, "label": "a", "tokens": ["x"]}]},
            }
        },
    ),
) -> Dict[str, Any]:
    """Return LLM plan to merge or split clusters."""
    from .. import server as _server

    clusters = payload.get("clusters") or []
    if not isinstance(clusters, list):
        raise HTTPException(status_code=400, detail="clusters must be list")
    thresh = float(payload.get("thresh", 0.85))

    centroids: Dict[int, np.ndarray] = {}
    for c in clusters:
        vec = c.get("centroid") or c.get("vec")
        if vec is None:
            continue
        centroids[int(c.get("id", 0))] = np.asarray(vec, dtype=np.float32)
    sim = similarity_matrix(centroids)
    ids = list(centroids.keys())
    candidates: Dict[int, List[int]] = {}
    for i, cid in enumerate(ids):
        scored = [
            (float(sim[i, j]), ids[j])
            for j in range(len(ids))
            if i != j and sim[i, j] > thresh
        ]
        scored.sort(reverse=True)
        candidates[cid] = [sid for _, sid in scored[:3]]

    prompt_text = build_recluster_prompt(clusters, candidates)
    messages = [
        {"role": "system", "content": RECLUSTER_SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    try:
        if get_config("USE_STRUCTURED_OUTPUT") == "1":
            resp = await _server.call_llm_async(
                messages, [], json_schema=_RECLUSTER_SCHEMA, user="cluster"
            )
        else:
            resp = await _server.call_llm_async(messages, [], user="cluster")
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        data = json.loads(content)
        result = _validate_recluster(data)
    except json.JSONDecodeError:
        return {"merges": [], "splits": [], "renames": {}}
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"error": str(exc), "hint": "invalid LLM response"}
        )

    id_to_tokens = {int(c.get("id", 0)): c.get("tokens", []) for c in clusters}
    for split in result.get("splits", []):
        tokens = id_to_tokens.get(int(split.get("id", 0)), [])
        new_subsets = []
        for subset in split.get("subsets", []):
            new_subsets.append(remap_split_idxs(tokens, subset))
        split["subsets"] = new_subsets

    labels: List[str] = []
    renames = result.get("renames", {})
    for c in clusters:
        cid = str(c.get("id"))
        final = renames.get(cid, c.get("label", ""))
        labels.append(str(final).strip().lower())

    if len(labels) != len(set(labels)):
        raise HTTPException(
            status_code=400,
            detail={"error": "duplicate labels", "hint": "labels must be unique"},
        )

    for lab in labels:
        if len(lab.split()) > 3:
            raise HTTPException(
                status_code=400,
                detail={"error": "label too long", "hint": "max 3 tokens"},
            )

    return result


@router.put(
    "/semantic/clusters/apply",
    responses={
        200: {"content": {"application/json": {"example": {"status": "ok"}}}}
    },
)
async def semantic_apply_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Apply a plan",
                "value": {"merges": [], "splits": [], "renames": {}},
            }
        },
    ),
) -> Dict[str, Any]:
    """Validate and echo merge/split/rename plan."""

    try:
        plan = _validate_recluster(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"error": str(exc), "hint": "invalid plan"}
        )
    return {"status": "ok", "plan": plan}


@router.post(
    "/semantic/outline",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"url": "/api/v1/download/outline.md"}
                }
            }
        }
    },
)
async def semantic_outline(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {"summary": "Outline", "value": {"clusters": [{"label": "politics", "samples": ["..."]}]}},
        },
    ),
) -> Dict[str, str]:
    """Return Markdown outline for provided clusters."""
    from .. import server as _server

    clusters = payload.get("clusters")
    if not isinstance(clusters, list):
        raise HTTPException(status_code=400, detail="clusters must be list")

    lines: List[str] = []
    for cl in clusters:
        label = str(cl.get("label", "")).strip()
        lines.append(f"# {label}")
        samples = (
            cl.get("samples")
            or cl.get("snippets")
            or ([cl.get("sample_sentence")] if cl.get("sample_sentence") else [])
        )
        for s in list(samples)[:3]:
            lines.append(f"\u2022 {s}")

    text = "\n".join(lines) + "\n"
    fid = f"{uuid.uuid4().hex}.md"
    path = _server._EXPORT_DIR / fid
    if not _server.DRY_RUN:
        path.write_text(text, encoding="utf-8")
    # The download route lives on the /api/v1 router (routes/exports.py,
    # GET /download/{file_id}); without the prefix every returned link 404s.
    return {"url": f"/api/v1/download/{fid}"}


@router.get("/embeddings/local-index/preflight")
async def local_semantic_index_preflight(
    corpus: str = "default",
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return Apple-Silicon, corpus, memory, and disk readiness for a local build."""
    from .. import server as _server

    _server._require_admin_access(token)
    idx = _server.get_corpus(corpus)
    try:
        return semantic_index_jobs.preflight(idx, corpus)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.post(
    "/embeddings/local-index/build",
    response_model=OperationRunLaunchResponse,
)
async def local_semantic_index_build(
    payload: LocalSemanticIndexBuildRequest,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Start or resume a detached, checkpointed local MLX index build."""
    from .. import server as _server

    _server._require_admin_access(token)
    idx = _server.get_corpus(payload.corpus)
    try:
        return semantic_index_jobs.launch(idx, payload.corpus, payload.levels)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.get(
    "/embeddings/local-index/builds/{run_id}",
    response_model=OperationRunSnapshot,
)
async def local_semantic_index_build_status(
    run_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return the persisted status of a local semantic-index build."""
    from .. import server as _server

    _server._require_admin_access(token)
    try:
        return semantic_index_jobs.snapshot(run_id)
    except KeyError as exc:
        raise ApiError(
            404,
            "semantic_build.not_found",
            lt("Semantik-Build nicht gefunden", "Semantic index build not found"),
        ) from exc


@router.post(
    "/embeddings/local-index/builds/{run_id}/cancel",
    response_model=OperationRunSnapshot,
)
async def local_semantic_index_build_cancel(
    run_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Cancel a build before activation while retaining its checkpoints."""
    from .. import server as _server

    _server._require_admin_access(token)
    try:
        return semantic_index_jobs.cancel(run_id)
    except KeyError as exc:
        raise ApiError(
            404,
            "semantic_build.not_found",
            lt("Semantik-Build nicht gefunden", "Semantic index build not found"),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.get(
    "/embeddings/list",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"example-vectors": {"installed": False, "dim": 300}}
                }
            }
        }
    },
)
async def embeddings_list() -> Dict[str, Any]:
    """Return the word vector packages of the package catalogue and their state.

    The catalogue is ``vendor/embedding_packages.json`` inside the package.
    This release ships none, so the list is empty. No analysis reads an
    installed package (see the limits of ``settings.embedding_management``).
    """

    packages = embeddings.list_packages()
    results: Dict[str, Any] = {}
    for name, info in packages.items():
        path = EMB_DIR / f"{name}.txt"
        entry = dict(info)
        entry["installed"] = path.exists()
        results[name] = entry
    return results


#: What the pipeline in ``spacy_model`` embeds. Passage index builds
#: (``/system/rebuild-index``), ``/semantic/cluster_words``, the thesaurus,
#: ``sim()``, the word clusters of the copilot and the search text of a
#: passage search (the pipeline the passage index records) take the pipeline
#: of the corpus (core.word_vectors). Left for ``spacy_model``: text of
#: corpora and indexes that record no pipeline.
SPACY_MODEL_USES: tuple[str, ...] = ("fallback",)


def _corpus_word_vector_sources() -> list[Dict[str, Any]]:
    """Where each registered corpus takes its word vectors from (core.word_vectors)."""
    from .corpora import _registry_service

    try:
        entries = _registry_service().list_corpora()
    except Exception:
        return []
    sources: list[Dict[str, Any]] = []
    for entry in entries:
        vectors = entry.get("word_vectors")
        if isinstance(vectors, dict):
            sources.append({"corpus": entry.get("name"), **vectors})
    return sources


def _embedding_backend_state() -> Dict[str, Any]:
    return {
        "backend": embeddings.current_backend(),
        "supported_backends": list(embeddings.SUPPORTED_BACKENDS),
        "spacy_model": embeddings.spacy_model_name(),
        "spacy_model_used_for": list(SPACY_MODEL_USES),
        "word_vectors": _corpus_word_vector_sources(),
    }


@router.get(
    "/settings/embeddings",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "backend": "spacy",
                        "supported_backends": ["spacy", "none"],
                        "spacy_model": "de_core_news_md",
                        "spacy_model_used_for": ["fallback"],
                        "word_vectors": [
                            {
                                "corpus": "sotu_en",
                                "available": True,
                                "source": "pipeline",
                                "pipeline": "en_core_web_md",
                                "reason": "",
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def get_embeddings(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return the embedding backend and where vectors come from (admin only).

    ``spacy`` embeds with the vectors of spaCy pipelines, ``none`` switches
    embeddings off. The thesaurus, ``sim()``, passage index builds and word
    clusters take the word vectors of each corpus, listed in ``word_vectors``
    with their source (the corpus's word vector index or the pipeline that
    annotated it). The search text of a passage search takes the pipeline the
    passage index records. ``spacy_model`` (CANDYCONC_EMB_SPACY_MODEL) is the
    pipeline for the rest, named in ``spacy_model_used_for``: ``fallback``
    (corpora and indexes that record no pipeline).
    """
    from .. import server as _server

    _server._require_admin_access(token)
    return _embedding_backend_state()


@router.post("/settings/embeddings")
async def set_embeddings(
    payload: Dict[str, str] = Body(
        ...,
        examples={"basic": {"summary": "Embedding backend", "value": {"backend": "spacy"}}},
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Set the embedding backend, ``spacy`` or ``none`` (admin only).

    The value lasts until the server stops. Any other value, and a request
    without ``backend``, is rejected with 422: the server has no other
    embedding backend.
    """
    from .. import server as _server

    _server._require_admin_access(token)
    backend = str(payload.get("backend") or "").strip().lower()
    if not backend:
        raise ApiError(
            422,
            "embeddings.backend_missing",
            lt(
                "backend fehlt. Möglich sind: {supported}.",
                "backend is missing. Supported: {supported}.",
            ),
            supported=", ".join(embeddings.SUPPORTED_BACKENDS),
        )
    if backend not in embeddings.SUPPORTED_BACKENDS:
        raise ApiError(
            422,
            "embeddings.backend_unsupported",
            lt(
                "Embedding-Backend '{backend}' gibt es nicht. Möglich sind: {supported}.",
                "There is no embedding backend '{backend}'. Supported: {supported}.",
            ),
            backend=backend,
            supported=", ".join(embeddings.SUPPORTED_BACKENDS),
        )
    set_config("CANDYCONC_EMB_BACKEND", backend)
    return {"status": "ok", **_embedding_backend_state()}


@router.post(
    "/embeddings/download",
    response_model=OperationRunLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "status": "queued",
                        "run_id": "abc123",
                        "job_id": "abc123",
                        "status_url": "/api/v1/operation-runs/abc123",
                        "operation_id": "settings.embedding_management.download",
                    }
                }
            }
        }
    },
)
async def embeddings_download(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Download",
                "value": {"name": "example-vectors", "url": "https://example.com/vectors.txt"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Download an embedding package in the background."""
    from .. import server as _server

    _server._require_admin_access(token)

    name = payload.get("name", "")
    requested_url = payload.get("url", "")
    if not name:
        raise HTTPException(status_code=400, detail="Missing name")

    packages = embeddings.list_packages()
    package = packages.get(name)
    if not isinstance(package, dict):
        raise HTTPException(status_code=400, detail="Unknown embedding package")
    url = str(package.get("url") or "")
    sha = str(package.get("sha256") or "").strip()
    if not url or not sha:
        raise HTTPException(status_code=400, detail="Embedding package metadata incomplete")
    if requested_url and requested_url != url:
        raise HTTPException(status_code=400, detail="Embedding package URL does not match backend catalog")

    existing = operation_run_registry.find_active(
        operation_id="settings.embedding_management.download",
        source_id=name,
    )
    if existing is not None:
        status_url = f"/api/v1/operation-runs/{existing.run_id}"
        return {
            "status": "queued",
            "run_id": existing.run_id,
            "job_id": existing.run_id,
            "status_url": status_url,
            "operation_id": existing.operation_id,
        }

    run = operation_run_registry.create(
        operation_id="settings.embedding_management.download",
        source_id=name,
        kind="operation",
        label=lt("Embedding-Download: {name}", "Embedding download: {name}").format(name=name),
        message=lt(
            "Embedding-Download wurde serverseitig eingereiht.",
            "The embedding download was queued on the server.",
        ),
        progress=0,
    )

    async def runner() -> None:
        operation_run_registry.mark_running(
            run.run_id,
            phase="download",
            progress=10,
            message=lt("Embedding-Paket wird heruntergeladen.", "Downloading the embedding package."),
        )
        try:
            path = await download_embedding(name, url, sha)
            installed = path.exists()
            operation_run_registry.mark_succeeded(
                run.run_id,
                message=lt(
                    "Embedding-Paket wurde installiert und verifiziert.",
                    "The embedding package was installed and verified.",
                ),
                result_ref=str(path),
                evidence={
                    "installed": installed,
                    "package": name,
                    "path": str(path),
                    "checksum_provided": bool(sha),
                },
            )
        except asyncio.CancelledError:
            operation_run_registry.mark_cancelled(
                run.run_id,
                message=lt(
                    "Embedding-Download wurde vom Backend abgebrochen.",
                    "The server cancelled the embedding download.",
                ),
            )
            raise
        except Exception as exc:
            logger.exception("Embedding download failed: %s", name)
            operation_run_registry.mark_failed(
                run.run_id,
                error=lt(
                    "Embedding-Download fehlgeschlagen: {name} ({error})",
                    "Embedding download failed: {name} ({error})",
                ).format(name=name, error=exception_text(exc)),
            )

    asyncio.create_task(runner())
    status_url = f"/api/v1/operation-runs/{run.run_id}"
    return {
        "status": "queued",
        "run_id": run.run_id,
        "job_id": run.run_id,
        "status_url": status_url,
        "operation_id": run.operation_id,
    }


@router.post(
    "/embeddings/remove",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def embeddings_remove(
    payload: Dict[str, str] = Body(
        ...,
        examples={"basic": {"summary": "Remove", "value": {"name": "example-vectors"}}},
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Remove an installed embedding package."""
    from .. import server as _server

    _server._require_admin_access(token)

    name = payload.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Missing name")
    embeddings.remove_package(name)
    return {"status": "ok"}
