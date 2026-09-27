# -*- coding: utf-8 -*-
"""Word clusters of the copilot tool semantic_cluster_words, computed locally.

The tool asks the backend route /semantic/cluster_words. When the route is not
reachable it clusters here, with the word vectors of the active corpus (the
pipeline comes in from the caller, see core.word_vectors.vector_pipeline).
Moved out of tool_wrappers unchanged (LOC budget of that module).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from candyconc.services.semantic_cluster import cluster_words


WORD_CLUSTER_STOPWORDS = {
    "aber",
    "alle",
    "als",
    "also",
    "am",
    "an",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bis",
    "da",
    "dann",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "doch",
    "du",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "er",
    "es",
    "für",
    "für",
    "gegen",
    "hab",
    "habe",
    "haben",
    "hat",
    "ich",
    "im",
    "in",
    "ist",
    "ja",
    "kann",
    "keine",
    "man",
    "mehr",
    "mich",
    "mit",
    "nach",
    "nicht",
    "noch",
    "nur",
    "oder",
    "ohne",
    "schon",
    "sie",
    "sind",
    "so",
    "um",
    "und",
    "uns",
    "von",
    "was",
    "wenn",
    "wer",
    "wie",
    "wir",
    "wird",
    "werden",
    "zu",
}


def word_cluster_label(samples: List[str]) -> str:
    visible = [str(item).strip() for item in samples if str(item).strip()]
    return " / ".join(visible[:2]) if visible else "misc"


def word_cluster_tokens(tokens: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen: set[str] = set()
    for token in tokens:
        text = re.sub(r"^[#@]+", "", str(token or "").strip())
        text = re.sub(r"^[^\wÄÖÜäöüß]+|[^\wÄÖÜäöüß]+$", "", text)
        if len(text) < 2:
            continue
        key = text.casefold()
        if key in WORD_CLUSTER_STOPWORDS or key in seen:
            continue
        cleaned.append(text)
        seen.add(key)
    return cleaned or [str(token).strip() for token in tokens if str(token).strip()]


def format_word_clusters(tokens: List[str], clusters: List[Dict[str, Any]], min_size: int, top_n: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    misc: List[int] = []
    for cluster in clusters:
        idxs = [int(idx) for idx in cluster.get("idxs", [])]
        cluster_id = int(cluster.get("cluster", -1))
        if len(idxs) < int(min_size) or cluster_id == -1:
            misc.extend(idxs)
            continue
        samples = [str(tokens[idx]) for idx in idxs if 0 <= idx < len(tokens)][:3]
        results.append(
            {
                "cluster_id": cluster_id,
                "size": len(idxs),
                "label": word_cluster_label(samples),
                "samples": samples,
            }
        )
    if misc:
        samples = [str(tokens[idx]) for idx in misc if 0 <= idx < len(tokens)][:3]
        results.append(
            {
                "cluster_id": -1,
                "size": len(misc),
                "label": "misc",
                "samples": samples,
            }
        )
    return results[: max(1, int(top_n))]


def local_word_clusters(
    tokens: List[str],
    *,
    min_size: int,
    top_n: int,
    reason: str,
    pipeline: str | None,
    input_token_count: int | None = None,
    cluster: Callable[..., List[Dict[str, Any]]] = cluster_words,
) -> Dict[str, Any]:
    """The clusters of ``tokens`` with the vectors of ``pipeline``, in the tool's answer shape.

    ``pipeline`` None embeds with CANDYCONC_EMB_SPACY_MODEL. ``cluster`` is the
    clustering function, passed in so that the caller's test seam holds.
    """
    clusters = format_word_clusters(
        list(tokens),
        cluster(list(tokens), min_size=int(min_size), pipeline=pipeline),
        min_size=int(min_size),
        top_n=int(top_n),
    )
    return {
        "status": "success",
        "clusters": clusters,
        "input_token_count": int(input_token_count if input_token_count is not None else len(tokens)),
        "cluster_token_count": len(tokens),
        "fallback": {
            "backend": "local",
            "reason": reason,
        },
    }
