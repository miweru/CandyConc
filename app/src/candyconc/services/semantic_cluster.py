from __future__ import annotations

from typing import Any, Dict, List, Sequence

import importlib

import numpy as np

from . import embeddings
from candyconc.core.corpus_index import CorpusIndex

try:  # optional dependency
    hdbscan = importlib.import_module("hdbscan")
except Exception:  # pragma: no cover - missing
    hdbscan = None

_GRAPH_PRIMARY_THRESHOLD = 0.60
_GRAPH_SECONDARY_THRESHOLD = 0.52
_GRAPH_PRIMARY_COHESION = 0.58
_GRAPH_SECONDARY_COHESION = 0.50
_GRAPH_TOP_K = 3


def _normalize_vectors(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.size == 0:
        return arr
    return arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)


def _connected_components(
    arr: np.ndarray,
    *,
    threshold: float,
    top_k: int,
    indices: Sequence[int] | None = None,
) -> list[list[int]]:
    base_indices = [int(idx) for idx in indices] if indices is not None else list(range(int(arr.shape[0])))
    if not base_indices:
        return []
    sub = arr[np.asarray(base_indices, dtype=np.int64)]
    sims = sub @ sub.T
    n_items = int(sub.shape[0])
    order = np.argsort(-sims, axis=1)
    neighbours: list[set[int]] = []
    for i in range(n_items):
        items = [int(j) for j in order[i] if int(j) != i][: int(top_k)]
        neighbours.append(set(items))
    edges: list[set[int]] = [set() for _ in range(n_items)]
    for i in range(n_items):
        for j in range(i + 1, n_items):
            if float(sims[i, j]) < float(threshold):
                continue
            if j in neighbours[i] or i in neighbours[j]:
                edges[i].add(j)
                edges[j].add(i)
    seen = [False] * n_items
    components: list[list[int]] = []
    for i in range(n_items):
        if seen[i]:
            continue
        stack = [i]
        seen[i] = True
        component: list[int] = []
        while stack:
            current = stack.pop()
            component.append(base_indices[current])
            for nxt in edges[current]:
                if not seen[nxt]:
                    seen[nxt] = True
                    stack.append(nxt)
        components.append(component)
    return components


def _cluster_cohesion(arr: np.ndarray, indices: Sequence[int]) -> float:
    members = [int(idx) for idx in indices]
    if len(members) < 2:
        return 0.0
    sub = arr[np.asarray(members, dtype=np.int64)]
    sims = sub @ sub.T
    mask = ~np.eye(len(members), dtype=bool)
    values = sims[mask]
    if values.size == 0:
        return 0.0
    return float(values.mean())


def _graph_cluster_labels(arr: np.ndarray, min_size: int) -> list[int]:
    labels = [-1] * int(arr.shape[0])
    next_label = 0
    leftovers: list[int] = []
    primary_components = _connected_components(
        arr,
        threshold=_GRAPH_PRIMARY_THRESHOLD,
        top_k=_GRAPH_TOP_K,
    )
    for component in primary_components:
        cohesion = _cluster_cohesion(arr, component)
        if len(component) >= int(min_size) and cohesion >= _GRAPH_PRIMARY_COHESION:
            for idx in component:
                labels[int(idx)] = next_label
            next_label += 1
        else:
            leftovers.extend(component)
    if leftovers:
        secondary_components = _connected_components(
            arr,
            threshold=_GRAPH_SECONDARY_THRESHOLD,
            top_k=_GRAPH_TOP_K,
            indices=sorted(leftovers),
        )
        secondary_min_size = max(2, int(min_size) - 1)
        for component in secondary_components:
            cohesion = _cluster_cohesion(arr, component)
            if len(component) >= secondary_min_size and cohesion >= _GRAPH_SECONDARY_COHESION:
                for idx in component:
                    labels[int(idx)] = next_label
                next_label += 1
    return labels


def _labels_quality(arr: np.ndarray, labels: Sequence[int], min_size: int) -> tuple[float, int, float]:
    clusters: Dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if int(label) < 0:
            continue
        clusters.setdefault(int(label), []).append(int(idx))
    if not clusters:
        return (0.0, 0, 0.0)
    valid_clusters = [members for members in clusters.values() if len(members) >= int(min_size)]
    if not valid_clusters:
        return (0.0, 0, 0.0)
    coverage = float(sum(len(members) for members in valid_clusters)) / float(int(arr.shape[0]) or 1)
    mean_cohesion = float(
        sum(_cluster_cohesion(arr, members) for members in valid_clusters) / float(len(valid_clusters))
    )
    score = float(len(valid_clusters)) * 3.0 + coverage * 2.0 + mean_cohesion
    return (score, len(valid_clusters), coverage)


def cluster_vectors(vectors: Sequence[Sequence[float]], min_size: int = 5) -> List[int]:
    """Cluster ``vectors`` and return labels."""

    arr = _normalize_vectors(vectors)
    if arr.size == 0:
        return []
    graph_labels = _graph_cluster_labels(arr, min_size=int(min_size))
    if hdbscan is not None:
        try:
            labels = hdbscan.HDBSCAN(
                min_cluster_size=int(min_size),
                metric="euclidean",
            ).fit_predict(arr)
            labels_list = [int(label) for label in labels.tolist()]
            if any(label >= 0 for label in labels_list):
                if _labels_quality(arr, graph_labels, int(min_size))[0] > _labels_quality(arr, labels_list, int(min_size))[0]:
                    return graph_labels
                return labels_list
        except Exception:
            pass
    return graph_labels


def label_cluster(idx: CorpusIndex, doc_ids: Sequence[int], top_k: int = 5) -> str:
    """Return a label based on Fast Index frequency list for the given doc IDs."""

    if not doc_ids:
        return ""
    df = idx.frequency_list_docset(doc_ids, stopwords=None)
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()
    if hasattr(df, "to_dicts"):
        rows = df.to_dicts()
    else:
        rows = df.to_dict("records") if hasattr(df, "to_dict") else []
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: int(r.get("f", 0)), reverse=True)
    for row in rows[: max(1, int(top_k))]:
        token = str(row.get("word", "")).strip()
        if token:
            return token
    return ""


def word_vectors(tokens: List[str], pipeline: str | None = None) -> np.ndarray:
    """Return word vectors for ``tokens`` from the spaCy pipeline ``pipeline``.

    The route passes the pipeline of the corpus. Without one the pipeline in
    CANDYCONC_EMB_SPACY_MODEL is used.
    """

    return embeddings.embed(tokens, task="text-matching", pipeline=pipeline).astype(np.float32)


def cluster_words(tokens: List[str], min_size: int = 5, pipeline: str | None = None) -> List[Dict[str, Any]]:
    """Cluster ``tokens`` using their embeddings."""

    vecs = word_vectors(tokens, pipeline=pipeline)
    labels = cluster_vectors(vecs, min_size=min_size)
    clusters: Dict[int, List[int]] = {}
    for idx, lab in enumerate(labels):
        clusters.setdefault(int(lab), []).append(idx)
    return [{"cluster": c, "idxs": idxs} for c, idxs in clusters.items()]


def cluster_centroids(vecs: Sequence[Sequence[float]], labels: Sequence[int]) -> Dict[int, np.ndarray]:
    """Return centroid vectors per cluster label."""

    arr = np.asarray(vecs, dtype=np.float32)
    labs = np.asarray(labels, dtype=int)
    centroids: Dict[int, np.ndarray] = {}
    for lab in sorted(set(labs.tolist())):
        members = arr[labs == lab]
        if members.size:
            centroids[int(lab)] = members.mean(axis=0)
    return centroids


def similarity_matrix(centroids: Dict[int, np.ndarray]) -> np.ndarray:
    """Return cosine similarity matrix for ``centroids``."""

    if not centroids:
        return np.zeros((0, 0), dtype=np.float32)
    vecs = np.vstack(list(centroids.values())).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
    vecs = vecs / norms
    return vecs @ vecs.T


def remap_split_idxs(cluster_tokens: List[int], local_idxs: List[int]) -> List[int]:
    """Return global token IDs for ``local_idxs`` inside ``cluster_tokens``."""

    ids: List[int] = []
    for idx in local_idxs:
        if 0 <= idx < len(cluster_tokens):
            ids.append(int(cluster_tokens[idx]))
    return ids
