"""The thesaurus identifies exact shared spaCy vectors separately from cosine."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from candyconc.core import cql_macros
from candyconc.services.backend import server
from candyconc.services.backend.routes import semantic


@pytest.mark.parametrize("term,spacy_source,word_index", [
    ("seed", True, True), ("SEED", True, True), ("seed", False, True),
    ("seed", True, False), ("SEED", True, False),
])
def test_neighbours_identify_the_actual_query_vector(monkeypatch, term, spacy_source, word_index):
    import spacy

    nlp = spacy.blank("en")
    for word, vector in {"seed": [2, 0], "shared": [2, 0], "scaled": [4, 0], "near": [2, 0.0001]}.items():
        nlp.vocab.set_vector(word, np.asarray(vector, dtype=np.float32))
    words = ["seed", "shared", "scaled", "near", "SEED"]
    lexicon = SimpleNamespace(
        get_id=lambda word: words.index(word) + 1 if word in words else 0,
        get_string=lambda wid: words[wid - 1],
    )
    index = SimpleNamespace(fast_index=SimpleNamespace(
        index_path="", lexicons=SimpleNamespace(word=lexicon),
    ))
    faiss = SimpleNamespace(search=lambda _vector, _k: (
        np.array([[1.0, 1.0, 1.0]], dtype=np.float32), np.array([[0, 1, 2]]),
    ))
    monkeypatch.setattr(cql_macros, "_SIM_CACHE", type(cql_macros._SIM_CACHE)())
    monkeypatch.setattr(cql_macros, "_load_word_faiss", lambda _index:
                        (faiss, np.array([2, 3, 4]), True) if word_index else None)
    monkeypatch.setattr(cql_macros, "_embedding_backend_query_vector", lambda _term:
                        None if spacy_source else np.array([1, 0], dtype=np.float32))
    monkeypatch.setattr(cql_macros, "_corpus_spacy_model", lambda _key: nlp)
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: index)
    monkeypatch.setattr(semantic, "_word_similarity_available", lambda _index: True)
    monkeypatch.setattr(semantic, "_corpus_frequency_lookup", lambda *_args: dict.fromkeys(words, 3))

    client = TestClient(server.app)
    response = client.get("/api/v1/semantic/similar_words", params={"term": term, "k": 4})
    assert response.status_code == 200, response.text
    neighbours = response.json()["neighbours"]
    if word_index:
        assert [item["word"] for item in neighbours] == ["shared", "scaled", "near"]
    assert [item["score"] for item in neighbours] == [1.0, 1.0, 1.0]
    assert {item["word"]: item["shared_query_vector"] for item in neighbours} == (
        {"shared": True, "scaled": False, "near": False} if spacy_source
        else {"shared": None, "scaled": None, "near": None}
    )
    cached = client.get("/api/v1/semantic/similar_words", params={"term": term, "k": 4})
    assert cached.json() == response.json()
