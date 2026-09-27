"""Shared registry for heavy ML models.

This module lazily loads spaCy pipelines and FAISS indexes. Loaded objects
are cached so subsequent calls return the same instance. ``clear_registry``
removes all cached objects and is used by tests to ensure isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple, Dict, Any

# spaCy is imported lazily inside get_spacy() so this module — and everything
# that imports it (cql_macros, analysis, vectorizer, startup) — stays importable
# without spaCy installed.

try:  # optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover - package not installed
    faiss = None  # type: ignore

__all__ = [
    "get_spacy",
    "get_faiss_index",
    "clear_registry",
]


_SpacyKey = Tuple[str, Tuple[str, ...]]
_spacy_models: Dict[_SpacyKey, Any] = {}
_faiss_indices: Dict[str, Any] = {}


def get_spacy(model_name: str, disable: Iterable[str] | None = None):
    """Return spaCy model ``model_name`` with optional components disabled."""

    import spacy  # lazy: only load when a pipeline is actually requested
    disabled = tuple(disable or ())
    key: _SpacyKey = (model_name, disabled)
    if key not in _spacy_models:
        _spacy_models[key] = spacy.load(model_name, disable=list(disabled))
    return _spacy_models[key]


def get_faiss_index(path: str | Path):
    """Return FAISS index loaded from ``path``."""

    if faiss is None:  # pragma: no cover - optional dep
        raise RuntimeError("faiss not installed")
    path = str(Path(path))
    if path not in _faiss_indices:
        _faiss_indices[path] = faiss.read_index(path)
    return _faiss_indices[path]


def clear_registry() -> None:
    """Clear all cached models (for tests)."""

    _spacy_models.clear()
    _faiss_indices.clear()
