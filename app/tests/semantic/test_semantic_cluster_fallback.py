from __future__ import annotations

import numpy as np

from candyconc.services import semantic_cluster


class _AllNoiseHdbscan:
    class HDBSCAN:
        def __init__(self, *args, **kwargs):
            pass

        def fit_predict(self, arr: np.ndarray) -> np.ndarray:
            return np.full(int(arr.shape[0]), -1, dtype=np.int32)


def test_cluster_vectors_graph_fallback_recovers_small_theme_pairs(monkeypatch):
    monkeypatch.setattr(semantic_cluster, "hdbscan", _AllNoiseHdbscan())
    vectors = np.asarray(
        [
            [1.0, 0.0],
            [0.98, 0.05],
            [0.0, 1.0],
            [0.05, 0.98],
            [-1.0, 0.0],
            [0.0, -1.0],
        ],
        dtype=np.float32,
    )

    labels = semantic_cluster.cluster_vectors(vectors, min_size=3)

    positive = [label for label in labels if label >= 0]
    assert len(set(positive)) == 2
    assert labels.count(-1) == 2
