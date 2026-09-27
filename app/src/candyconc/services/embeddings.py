from __future__ import annotations

import json
from pathlib import Path
import logging
from typing import Dict, Any, TYPE_CHECKING, Union, Callable

from candyconc.tools.embedding_package import EMB_DIR
from candyconc.config import APP_CONFIG
from functools import lru_cache
from typing import Sequence
import numpy as np

if TYPE_CHECKING:  # pragma: no cover - optional deps for typing only
    from spacy.language import Language

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILE = ROOT / "vendor" / "embedding_packages.json"
LOGGER = logging.getLogger(__name__)

#: Values of CANDYCONC_EMB_BACKEND that :func:`embed` serves: the vectors of
#: the spaCy pipeline named in CANDYCONC_EMB_SPACY_MODEL, or no embeddings.
SUPPORTED_BACKENDS: tuple[str, ...] = ("spacy", "none")


def current_backend() -> str:
    """The configured embedding backend (CANDYCONC_EMB_BACKEND, lower case)."""
    return str(getattr(APP_CONFIG, "CANDYCONC_EMB_BACKEND", "spacy") or "spacy").strip().lower()


def spacy_model_name() -> str:
    """The spaCy pipeline whose vectors the ``spacy`` backend uses."""
    return getattr(APP_CONFIG, "CANDYCONC_EMB_SPACY_MODEL", "de_core_news_md") or "de_core_news_md"


def list_packages() -> Dict[str, Any]:
    if PACKAGE_FILE.exists():
        try:
            with PACKAGE_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            LOGGER.exception("Failed to read embedding package metadata: %s", PACKAGE_FILE)
            raise RuntimeError("embedding package metadata invalid") from exc
    return {}


def remove_package(name: str) -> None:
    # Validate name to a single safe segment so unlink cannot escape EMB_DIR.
    from candyconc.domain.corpus import normalize_corpus_name

    safe = normalize_corpus_name(name)
    path = EMB_DIR / f"{safe}.txt"
    path.resolve().relative_to(EMB_DIR.resolve())
    if path.exists():
        path.unlink()

# ---------------------------------------------------------------------------
# Embedding wrapper around spaCy only


def _load_spacy() -> Language:
    """Return the configured spaCy embedding pipeline."""

    import spacy

    model_name = spacy_model_name()
    try:
        return spacy.load(model_name)
    except OSError as exc:
        raise RuntimeError(f"spaCy embedding model '{model_name}' not available") from exc


@lru_cache(maxsize=1)
def _get_model_cached(backend: str) -> tuple[str, Union[Language, None]]:
    if backend == "spacy":
        return "spacy", _load_spacy()
    raise RuntimeError("Nur spaCy Embeddings sind erlaubt")


def _get_model(
    backend: str, confirm: Callable[[int], bool] | None = None
) -> tuple[str, Union[Language, None]]:
    return _get_model_cached(backend)


def get_spacy_model() -> "Language | None":
    """Return the lexical spaCy model independently of the semantic backend."""
    _mode, model = _get_model_cached("spacy")
    return model


def passage_pipeline(index_dir: str | Path) -> str | None:
    """The spaCy pipeline that embedded the passage index in ``index_dir``.

    ``embedding_meta.json`` records it. Queries against the index have to be
    embedded with the same pipeline. None when the index records none.
    """
    try:
        meta = json.loads((Path(index_dir) / "embedding_meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    name = meta.get("spacy_model") if isinstance(meta, dict) else None
    return str(name).strip() or None if name else None


def _pipeline_model(pipeline: str) -> "Language":
    """The spaCy pipeline ``pipeline``, shared with the thesaurus and ``sim()``."""
    from candyconc import model_registry
    from candyconc.core.word_vectors import SERVICE_ERROR_MESSAGE, WordVectorsServiceError
    from candyconc.i18n import lt

    try:
        return model_registry.get_spacy(pipeline)
    except (ImportError, OSError) as exc:
        raise WordVectorsServiceError(
            SERVICE_ERROR_MESSAGE
            + " "
            + lt(
                "Die Pipeline {pipeline} lässt sich nicht laden: {error}",
                "The pipeline {pipeline} cannot be loaded: {error}",
            ).format(pipeline=pipeline, error=str(exc))
        ) from exc


def embed(
    texts: Sequence[str],
    *,
    task: str = "retrieval.query",
    confirm: Callable[[int], bool] | None = None,
    pipeline: str | None = None,
) -> np.ndarray:
    """Return embedding vectors for ``texts`` using the configured backend.

    ``pipeline`` names the spaCy pipeline whose vectors embed the texts, the
    pipeline of the corpus (``core.word_vectors.vector_pipeline``). Without it
    the pipeline in CANDYCONC_EMB_SPACY_MODEL is used.
    """

    backend = current_backend()
    if backend == "none":
        raise RuntimeError("embedding backend disabled")
    if pipeline:
        mode, model = "spacy", _pipeline_model(pipeline)
    else:
        mode, model = _get_model(backend, confirm)
    if mode == "spacy" and model is not None:
        vecs = [model(t).vector for t in texts]
        arr = np.asarray(vecs, dtype=np.float32)
        if not np.any(arr):
            raise RuntimeError("spaCy Embeddings sind leer. Bitte Modell mit Vektoren nutzen.")
        return arr
    raise RuntimeError("embedding backend unavailable")


__all__ = [
    "SUPPORTED_BACKENDS",
    "current_backend",
    "embed",
    "get_spacy_model",
    "list_packages",
    "passage_pipeline",
    "remove_package",
    "spacy_model_name",
]
