from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import candyconc.core.query_runtime as query_runtime
from candyconc.config import APP_CONFIG, get as get_config
from candyconc.i18n import lt

SemanticLevel = Literal["doc", "sentence"]
SUPPORTED_SEMANTIC_BACKENDS = {"spacy", "gemma", "gemma_doc", "gemma_sentence"}


@dataclass(frozen=True)
class SemanticAvailability:
    available: bool
    code: str
    message: str
    backend: str
    level: SemanticLevel
    missing_assets: tuple[str, ...] = ()


def semantic_backend_name(backend: str | None = None) -> str:
    return str(backend or get_config("CANDYCONC_EMB_BACKEND", "spacy") or "").strip().lower()


def semantic_backend_level_supported(backend: str | None = None, level: SemanticLevel = "doc") -> bool:
    backend_name = semantic_backend_name(backend)
    if backend_name in {"", "none"}:
        return True
    if backend_name not in SUPPORTED_SEMANTIC_BACKENDS:
        return False
    if backend_name == "spacy":
        return level == "doc"
    if backend_name == "gemma_doc":
        return level == "doc"
    if backend_name == "gemma_sentence":
        return level == "sentence"
    return level in {"doc", "sentence"}


def _resolve_index_path(index_path: str | Path | None = None) -> Path | None:
    if index_path is not None:
        return Path(index_path)
    base = get_config("FAISS_DIR", "runtime") or "runtime"
    idx = getattr(query_runtime, "_CORPUS_INDEX", None)
    if idx is None:
        return Path(base)
    fast = getattr(idx, "fast_index", None)
    if fast is None:
        return Path(base)
    path = getattr(fast, "index_path", None)
    if path is not None:
        return Path(path)
    return Path(base)


def semantic_artifact_paths(
    index_path: str | Path | None = None,
    *,
    backend: str | None = None,
    level: SemanticLevel = "doc",
) -> tuple[Path, ...]:
    base = _resolve_index_path(index_path)
    if base is None:
        return tuple()
    backend_name = semantic_backend_name(backend)
    if not semantic_backend_level_supported(backend_name, level):
        return tuple()
    if backend_name in {"gemma", "gemma_doc"}:
        if level == "sentence" and backend_name == "gemma":
            return (
                base / "faiss_gemma_sentence.index",
                base / "gemma_sentence_vecs.npy",
                base / "gemma_sentence_texts.json",
            )
        return (
            base / "faiss_gemma_doc.index",
            base / "gemma_doc_vecs.npy",
            base / "gemma_doc_texts.json",
        )
    if backend_name == "gemma_sentence":
        return (
            base / "faiss_gemma_sentence.index",
            base / "gemma_sentence_vecs.npy",
            base / "gemma_sentence_texts.json",
        )
    if level == "sentence":
        return (
            base / "faiss_gemma_sentence.index",
            base / "gemma_sentence_vecs.npy",
            base / "gemma_sentence_texts.json",
        )
    return (
        base / "faiss_passage.index",
        base / "passage_vecs.npy",
        base / "passage_texts.json",
    )


def semantic_artifacts_available(
    index_path: str | Path | None = None,
    *,
    backend: str | None = None,
    level: SemanticLevel = "doc",
) -> bool:
    paths = semantic_artifact_paths(index_path, backend=backend, level=level)
    return bool(paths) and all(path.exists() for path in paths)


def semantic_search_available(
    index_path: str | Path | None = None,
    *,
    backend: str | None = None,
    level: SemanticLevel = "doc",
) -> bool:
    return semantic_search_status(index_path, backend=backend, level=level).available


def semantic_search_status(
    index_path: str | Path | None = None,
    *,
    backend: str | None = None,
    level: SemanticLevel = "doc",
) -> SemanticAvailability:
    base = _resolve_index_path(index_path)
    backend_name = semantic_backend_name(backend)
    if backend is None and base is not None:
        gemma_doc = (
            base / "faiss_gemma_doc.index",
            base / "gemma_doc_vecs.npy",
            base / "gemma_doc_texts.json",
        )
        if all(path.exists() for path in gemma_doc):
            backend_name = "gemma"
    if APP_CONFIG.ENABLE_EMBEDDING_SEARCH is False:
        return SemanticAvailability(
            False,
            "semantic_unavailable",
            lt("Semantische Suche ist deaktiviert.", "Semantic search is disabled."),
            backend_name,
            level,
        )
    if backend_name in {"", "none"}:
        return SemanticAvailability(
            False,
            "semantic_unavailable",
            lt("Kein Embedding-Backend konfiguriert.", "No embedding backend is configured."),
            backend_name,
            level,
        )
    if base is not None and (base / ".semantic_commit_in_progress").exists():
        return SemanticAvailability(
            False,
            "semantic_index_building",
            lt(
                "Der semantische Index wird gerade atomar aktiviert.",
                "The semantic index is being activated atomically.",
            ),
            backend_name,
            level,
        )
    if not semantic_backend_level_supported(backend_name, level):
        message = lt(
            "Semantische Suche unterstützt Backend '{backend}' nicht auf Ebene '{level}'.",
            "Semantic search does not support backend '{backend}' at level '{level}'.",
        ).format(backend=backend_name, level=level)
        if backend_name not in SUPPORTED_SEMANTIC_BACKENDS:
            message = lt(
                "Semantische Suche unterstützt Backend '{backend}' nicht.",
                "Semantic search does not support backend '{backend}'.",
            ).format(backend=backend_name)
        return SemanticAvailability(
            False,
            "semantic_unsupported",
            message,
            backend_name,
            level,
        )
    paths = semantic_artifact_paths(base, backend=backend_name, level=level)
    missing = tuple(str(path) for path in paths if not path.exists())
    if missing:
        return SemanticAvailability(
            False,
            "semantic_index_missing",
            lt(
                "Semantischer Vektorindex fehlt oder ist unvollständig.",
                "The semantic vector index is missing or incomplete.",
            ),
            backend_name,
            level,
            missing,
        )
    return SemanticAvailability(
        True,
        "",
        "",
        backend_name,
        level,
    )
