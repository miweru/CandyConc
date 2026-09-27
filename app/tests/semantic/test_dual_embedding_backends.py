from __future__ import annotations

from candyconc.config import APP_CONFIG
from candyconc.services import embeddings


def test_spacy_word_model_is_available_with_gemma_semantic_backend(monkeypatch):
    lexical_model = object()
    monkeypatch.setattr(APP_CONFIG, "CANDYCONC_EMB_BACKEND", "gemma")
    monkeypatch.setattr(
        embeddings,
        "_get_model_cached",
        lambda backend: ("spacy", lexical_model) if backend == "spacy" else None,
    )

    assert embeddings.get_spacy_model() is lexical_model
