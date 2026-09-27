"""Which word vectors serve the thesaurus and ``sim()`` for one corpus.

One decision for the ``sim()`` query macro, the ``/semantic/similar_words``
route, the copilot tool and the corpus feature descriptor. The vectors have to
come from the corpus itself:

* a word vector index built for the corpus (``faiss_word.index`` and
  ``word_ids.npy``), queried with the vectors it was built from, or
* the static word vectors of the pipeline that annotated the corpus
  (``de_core_news_md``, ``en_core_web_md``).

A corpus annotated with a pipeline without static vectors (the ``_sm``
pipelines, ``blank:<lang>``) has no word vectors. It does not borrow the
vectors of another language.

Two states are kept apart. A corpus without word vectors is a property of the
corpus: a request that needs them is well-formed but does not fit the corpus
(HTTP 422, :class:`WordVectorsUnavailable`). A corpus whose pipeline has
vectors that this server cannot load, because the pipeline is not installed
or fails to load, is a missing server resource (HTTP 503,
:class:`WordVectorsServiceError`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from candyconc.i18n import lt

#: Shared text of the capability gate (REST 503, copilot ``reason``, ``sim()``).
UNAVAILABLE_MESSAGE = lt(
    "Für dieses Korpus gibt es keine Wortvektoren (word_similarity): Es hat weder "
    "einen Wortvektorindex (faiss_word.index/word_ids.npy) noch eine "
    "Annotationspipeline mit statischen Wortvektoren.",
    "No word vectors for this corpus (word_similarity): it has neither a word "
    "vector index (faiss_word.index/word_ids.npy) nor an annotation pipeline "
    "with static word vectors.",
)

#: Shared text of a corpus whose vectors the server cannot load (HTTP 503).
SERVICE_ERROR_MESSAGE = lt(
    "Die Wortvektoren dieses Korpus lassen sich auf diesem Server nicht laden.",
    "The word vectors of this corpus cannot be loaded on this server.",
)


class WordVectorsUnavailable(RuntimeError):
    """The corpus has no word vectors (HTTP 422, ``word_vectors.unavailable``)."""


class WordVectorsServiceError(RuntimeError):
    """The server cannot load the word vectors of the corpus (HTTP 503, ``word_vectors.service_error``)."""


@dataclass(frozen=True)
class WordVectorSource:
    available: bool
    #: spaCy pipeline whose vectors apply, None for a non-spaCy word index.
    pipeline: str | None
    #: True when faiss_word.index and word_ids.npy exist.
    word_index: bool
    #: Why the vectors are unavailable (German and English), empty when they are available.
    reason: str = ""
    #: True when the vectors are unavailable because this server cannot load the
    #: pipeline (not installed), not because the corpus has none.
    service_error: bool = False

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "source": ("word_index" if self.word_index else "pipeline") if self.available else None,
            "pipeline": self.pipeline,
            "reason": self.reason,
        }


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def corpus_pipeline(index_dir: Path) -> str | None:
    """The pipeline that annotated the corpus, as recorded by the build.

    The manifest field ``annotation_pipeline`` first, for older indexes the
    ``spacy_model`` of ``index_build_meta.json``. None when neither records it.
    """
    index_dir = Path(index_dir)
    manifest = _read_json(index_dir / "index_manifest.json")
    name = str(manifest.get("annotation_pipeline") or "").strip()
    if name:
        return name
    recorded = str(_read_json(index_dir / "index_build_meta.json").get("spacy_model") or "").strip()
    return recorded or None


def _recorded_vector_width(index_dir: Path, pipeline: str) -> int | None:
    """Vector width of ``pipeline`` as the build recorded it, None when not recorded."""
    manifest = _read_json(Path(index_dir) / "index_manifest.json")
    if str(manifest.get("annotation_pipeline") or "") != pipeline:
        return None
    try:
        recorded = int(manifest.get("pipeline_vectors", -1))
    except (TypeError, ValueError):
        return None
    return recorded if recorded >= 0 else None


def resolve_word_vectors(index_dir: Path) -> WordVectorSource:
    """Decide where the word vectors of the corpus at ``index_dir`` come from."""
    from candyconc.ingest.pipelines import is_blank, missing_text, pipeline_installed

    index_dir = Path(index_dir)
    word_index = (index_dir / "faiss_word.index").exists() and (index_dir / "word_ids.npy").exists()
    if word_index:
        # The index is queried with the vectors it was built from. The builder
        # records them, older builds used the corpus pipeline or the configured
        # embedding model (build_word_faiss_from_index._resolve_spacy_model).
        info = _read_json(index_dir / "embedding_meta.json").get("word_index")
        info = info if isinstance(info, dict) else {}
        pipeline = str(info.get("spacy_model") or "").strip() or corpus_pipeline(index_dir)
        if not pipeline and not (info.get("backend") or info.get("model")):
            from candyconc.config import get as get_config

            pipeline = str(get_config("CANDYCONC_EMB_SPACY_MODEL", "de_core_news_md") or "").strip()
        return WordVectorSource(True, pipeline or None, True)

    pipeline = corpus_pipeline(index_dir)
    if not pipeline:
        return WordVectorSource(
            False, None, False,
            lt(
                "Der Index verzeichnet nicht, welche Pipeline ihn annotiert hat.",
                "The index does not record the pipeline that annotated it.",
            ),
        )
    if is_blank(pipeline):
        return WordVectorSource(
            False, pipeline, False,
            lt(
                "Das Korpus wurde mit {pipeline} importiert, das nur tokenisiert und keine Wortvektoren hat.",
                "The corpus was imported with {pipeline}, which only tokenizes and has no word vectors.",
            ).format(pipeline=pipeline),
        )
    from candyconc.ingest.pipelines import pipeline_vector_width

    width = _recorded_vector_width(index_dir, pipeline)
    if width != 0 and not pipeline_installed(pipeline):
        return WordVectorSource(False, pipeline, False, missing_text(pipeline), service_error=True)
    if width is None:
        width = pipeline_vector_width(pipeline)
    if not width:
        return WordVectorSource(
            False, pipeline, False,
            lt(
                "Die Pipeline {pipeline} hat keine statischen Wortvektoren. Die Pipelines "
                "der Größen md und lg haben sie.",
                "The pipeline {pipeline} has no static word vectors. The pipelines "
                "of size md and lg have them.",
            ).format(pipeline=pipeline),
        )
    return WordVectorSource(True, pipeline, False)


def unavailable_error(source: WordVectorSource) -> RuntimeError:
    """The exception for an unavailable ``source``, with its reason."""
    if source.service_error:
        return WordVectorsServiceError(SERVICE_ERROR_MESSAGE + (" " + source.reason if source.reason else ""))
    return WordVectorsUnavailable(UNAVAILABLE_MESSAGE + (" " + source.reason if source.reason else ""))


def require_word_vectors(index_dir: Path) -> WordVectorSource:
    """The word vector source of the corpus, or the exception that says why there is none."""
    source = resolve_word_vectors(index_dir)
    if not source.available:
        raise unavailable_error(source)
    return source


def vector_pipeline(index_dir: Path) -> str:
    """The spaCy pipeline whose static vectors embed text of this corpus.

    Passage indexes and word clusters use it, like the thesaurus and
    ``sim()``. Raises :class:`WordVectorsUnavailable` or
    :class:`WordVectorsServiceError` when the corpus has no such pipeline.
    """
    source = require_word_vectors(index_dir)
    if not source.pipeline:
        # A word vector index built with a non-spaCy model has no pipeline
        # that could embed other text in the same space.
        raise WordVectorsUnavailable(
            UNAVAILABLE_MESSAGE
            + " "
            + lt(
                "Der Wortvektorindex des Korpus stammt nicht aus einer spaCy-Pipeline.",
                "The word vector index of the corpus does not come from a spaCy pipeline.",
            )
        )
    return source.pipeline


__all__ = [
    "SERVICE_ERROR_MESSAGE",
    "UNAVAILABLE_MESSAGE",
    "WordVectorSource",
    "WordVectorsServiceError",
    "WordVectorsUnavailable",
    "corpus_pipeline",
    "require_word_vectors",
    "resolve_word_vectors",
    "unavailable_error",
    "vector_pipeline",
]
