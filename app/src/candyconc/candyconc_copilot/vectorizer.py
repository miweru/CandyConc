from __future__ import annotations

import logging
from typing import List, Protocol, runtime_checkable

import numpy as np

from candyconc.config import APP_CONFIG
from candyconc import model_registry


@runtime_checkable
class VectorEmbeddings(Protocol):
    """Protocol for embedding backends."""

    dim: int

    def vectorize(self, text: str) -> np.ndarray:
        ...

    def batch_vectorize(self, texts: List[str], batch_size: int = -1) -> np.ndarray:
        ...

    def clean_up(self) -> None:
        ...


class SpaCyEmbeddings:
    """Embeddings backed by spaCy vectors."""

    def __init__(
        self,
        dim: int = 16,
        *,
        model_name: str | None = None,
        disable: List[str] | None = None,
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        name = model_name or APP_CONFIG.CANDYCONC_EMB_SPACY_MODEL or "de_core_news_md"
        self._model = model_registry.get_spacy(name, disable=disable)
        if getattr(self._model.vocab, "vectors_length", 0) == 0:
            raise RuntimeError("spaCy Modell hat keine Vektoren")
        self.dim = int(self._model.vocab.vectors_length)

    def vectorize(self, text: str) -> np.ndarray:
        vec = self._model(text).vector
        return np.asarray(vec, dtype=np.float32)

    def batch_vectorize(self, texts: List[str], batch_size: int = -1) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if batch_size is None or int(batch_size) <= 0:
            batch_size = 256
        vecs = []
        for doc in self._model.pipe(texts, batch_size=int(batch_size)):
            vecs.append(doc.vector)
        return np.asarray(vecs, dtype=np.float32)

    def clean_up(self) -> None:
        if hasattr(self, "_model"):
            self._logger.debug("Releasing model from %s", self.__class__.__name__)
            self._model = None


def get_default_vectorizer(dim: int = 16) -> VectorEmbeddings:
    """Return a vectorizer instance based on APP_CONFIG."""
    backend = getattr(APP_CONFIG, "CANDYCONC_EMB_BACKEND", "spacy").lower()
    if backend != "spacy":
        raise RuntimeError("Nur spaCy Embeddings sind erlaubt")
    return SpaCyEmbeddings(dim=dim, disable=["ner", "parser", "tagger"])


__all__ = [
    "VectorEmbeddings",
    "SpaCyEmbeddings",
    "get_default_vectorizer",
]
