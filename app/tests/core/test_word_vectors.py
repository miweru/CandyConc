"""Thesaurus and sim() take the corpus's own word vectors, one decision for both.

Before: ``sim()`` always used the vectors of ``CANDYCONC_EMB_SPACY_MODEL``
(``de_core_news_md``), also for English corpora, while the thesaurus route
answered 503 for every corpus without ``faiss_word.index``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spacy = pytest.importorskip("spacy", reason="spaCy not installed")

from candyconc.core import cql_macros  # noqa: E402
from candyconc.core.corpus_index import CorpusIndex  # noqa: E402
from candyconc.core.word_vectors import UNAVAILABLE_MESSAGE, resolve_word_vectors  # noqa: E402
from candyconc.domain.corpus import corpus_summary  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    monkeypatch.setattr(cql_macros, "_SIM_CACHE", type(cql_macros._SIM_CACHE)())


def _build(tmp_path: Path, pipeline: str, texts: list[str]) -> Path:
    from candyconc.ingest import ingest_adapters as ia

    src = tmp_path / "c.csv"
    src.write_text("id,text\n" + "".join(f'{i},"{t}"\n' for i, t in enumerate(texts)))
    out = tmp_path / "idx"
    ia.build_index_from_csv(src, out, spacy_model=pipeline, text_column="text", id_column="id",
                            batch_size=4, n_process=1)
    return out


def _payload(index: CorpusIndex, term: str):
    from candyconc.services.backend.routes import semantic as semantic_routes

    server = SimpleNamespace(get_corpus=lambda _corpus: index)
    return semantic_routes._build_similar_words_payload(
        server, term=term, k=5, min_score=None, corpus=None, docset_id=None
    )


def test_corpus_without_vectors_does_not_borrow_another_pipeline(tmp_path, monkeypatch):
    from fastapi import HTTPException

    out = _build(tmp_path, "blank:en", ["The river rose.", "The flood came.", "The river fell."])
    source = resolve_word_vectors(out)
    assert source.available is False
    assert "blank:en" in source.reason
    assert corpus_summary(out)["features"]["semantic"]["word_similarity"] is False

    def _borrowed(*_a, **_k):
        raise AssertionError("sim() loaded vectors of a pipeline the corpus was not annotated with")

    monkeypatch.setattr(cql_macros.embeddings, "get_spacy_model", _borrowed)
    monkeypatch.setattr(cql_macros.model_registry, "get_spacy", _borrowed)
    index = CorpusIndex(out, read_only=True)
    with pytest.raises(RuntimeError) as macro_error:
        cql_macros.similar_words_scored("river", 5, index)
    assert UNAVAILABLE_MESSAGE in str(macro_error.value)

    # The route reports the same decision with the same text. Since
    # 2026-09-27 it answers 422 word_vectors.unavailable like sim() in a query
    # (before: 503 semantic_index_missing with the reason under "cause").
    with pytest.raises(HTTPException) as route_error:
        _payload(index, "river")
    assert route_error.value.status_code == 422
    assert route_error.value.code == "word_vectors.unavailable"
    assert route_error.value.detail.startswith(UNAVAILABLE_MESSAGE)
    assert "blank:en" in route_error.value.detail


@pytest.mark.skipif(importlib.util.find_spec("de_core_news_md") is None, reason="de_core_news_md not installed")
def test_pipeline_vectors_serve_macro_and_route_alike(tmp_path):
    out = _build(
        tmp_path,
        "de_core_news_md",
        ["Der Hund bellt laut.", "Die Katze schläft.", "Ein Pferd läuft über die Wiese.", "Der Fluss steigt."],
    )
    source = resolve_word_vectors(out)
    assert (source.available, source.pipeline, source.word_index) == (True, "de_core_news_md", False)
    assert corpus_summary(out)["features"]["semantic"]["word_similarity"] is True

    index = CorpusIndex(out, read_only=True)
    macro_words = [entry["word"] for entry in cql_macros.similar_words_scored("Hund", 5, index)]
    assert macro_words[0] == "Hund"
    assert {"Katze", "Pferd"} <= set(macro_words)
    assert "Fluss" not in macro_words

    response = _payload(index, "Hund")
    assert response.status == "success"
    assert {n.word for n in response.neighbours} == set(macro_words[1:])
