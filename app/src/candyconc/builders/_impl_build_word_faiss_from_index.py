"""Importable seam for the word-FAISS post-step (thesaurus).

The implementation is :mod:`candyconc.ingest.build_word_faiss_from_index`. It
imports spaCy at module import time and raises ``SystemExit`` when it is
missing, and it needs ``faiss`` (extra ``semantic``). This seam converts both
into a regular ``RuntimeError`` so a missing optional dependency surfaces as an
honest job warning instead of killing the worker thread.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict


def _impl_module():
    try:
        return importlib.import_module("candyconc.ingest.build_word_faiss_from_index")
    except SystemExit as exc:  # the module guards its spaCy import with SystemExit
        raise RuntimeError(f"Word-FAISS-Builder nicht verfügbar: {exc}") from exc


def build_word_faiss(index_path: Path | str, *, spacy_model: str | None = None) -> Dict[str, Any]:
    """Build ``faiss_word.index`` + ``word_ids.npy`` for an existing index dir.

    Returns the builder's report dict. Raises ``RuntimeError`` on any failure
    (missing dependencies, empty lexicon, model without vectors, ...).
    """

    return dict(_impl_module()._build_word_faiss(Path(index_path), spacy_model=spacy_model))
