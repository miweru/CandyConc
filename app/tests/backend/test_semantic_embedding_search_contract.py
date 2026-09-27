import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import server
from candyconc.services.backend.routes import analysis as analysis_routes
from candyconc.services.semantic.availability import SemanticAvailability


def _fake_corpus(index_path: str = "/private/index"):
    return SimpleNamespace(fast_index=SimpleNamespace(index_path=index_path))


def _install_semantic_search(monkeypatch, func):
    import candyconc.candyconc_copilot as copilot_pkg

    module = ModuleType("candyconc.candyconc_copilot.analysis")
    module.semantic_search = func
    monkeypatch.setitem(sys.modules, "candyconc.candyconc_copilot.analysis", module)
    monkeypatch.setattr(copilot_pkg, "analysis", module, raising=False)


@pytest.fixture(autouse=True)
def _canonical_backend_server(monkeypatch):
    import candyconc.services.backend as backend_pkg

    monkeypatch.setitem(sys.modules, "candyconc.services.backend.server", server)
    monkeypatch.setattr(backend_pkg, "server", server, raising=False)


def test_embedding_search_missing_term_precedes_availability_check(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("availability must not mask payload validation")

    monkeypatch.setattr(analysis_routes, "semantic_search_status", fail_if_called)
    client = TestClient(server.app)

    response = client.post("/api/v1/analysis/embedding_search", json={"term": "   "})

    # DT-VERTRAEGE: input validation is the 422 class.
    assert response.status_code == 422
    assert response.json()["detail"] == "Missing term"


def test_embedding_search_rejects_unbounded_top_n_before_availability(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("availability must not mask payload bounds")

    monkeypatch.setattr(analysis_routes, "semantic_search_status", fail_if_called)
    client = TestClient(server.app)

    response = client.post("/api/v1/analysis/embedding_search", json={"term": "Klima", "top_n": 100000})

    assert response.status_code == 422
    assert "top_n" in response.json()["detail"]


def test_embedding_search_unavailable_is_503_not_empty_rows(monkeypatch):
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: _fake_corpus())
    monkeypatch.setattr(
        analysis_routes,
        "semantic_search_status",
        lambda *_args, **_kwargs: SemanticAvailability(
            False,
            "semantic_index_missing",
            "Semantischer Vektorindex fehlt oder ist unvollständig.",
            "spacy",
            "doc",
            ("/private/index/faiss_passage.index",),
        ),
    )
    client = TestClient(server.app)

    response = client.post("/api/v1/analysis/embedding_search", json={"term": "Klima"})

    assert response.status_code == 503
    body = response.json()
    assert "rows" not in body
    assert body["detail"]["code"] == "semantic_index_missing"
    assert body["detail"]["backend"] == "spacy"
    assert body["detail"]["missingAssets"] == ["/private/index/faiss_passage.index"]


def test_embedding_search_success_includes_exactness_generation_rerank_filtering_meta(monkeypatch):
    fake_idx = _fake_corpus()
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: fake_idx)

    def semantic_status(index_path=None, **_kwargs):
        assert index_path == "/private/index"
        return SemanticAvailability(True, "", "", "spacy", "doc")

    monkeypatch.setattr(
        analysis_routes,
        "semantic_search_status",
        semantic_status,
    )
    monkeypatch.setattr(
        server,
        "manager",
        SimpleNamespace(faiss_index_obj=None, passages=[{"doc_id": 7, "text": "Klima"}]),
    )
    monkeypatch.setattr(server, "_get_docset", lambda _docset_id: {"corpus": "default", "doc_ids": [7, 8]})

    def fake_semantic_search(*_args, **kwargs):
        assert kwargs["return_meta"] is True
        assert kwargs["corpus_index"] is fake_idx
        assert kwargs["docset_doc_ids"] == {7, 8}
        assert kwargs["backend"] == "spacy"
        return [
            {
                "left": "",
                "kw": "Klima und Energie",
                "right": "",
                "score": 0.91,
                "doc_id": 7,
                "meta": {"source": "news", "year": 2026, "flags": ["ai"]},
            }
        ], {
            "exactness": "approximate",
            "candidateGeneration": {
                "backend": "spacy",
                "level": "doc",
                "method": "faiss_passage",
                "searchMode": "approximate",
                "requestedTopN": 3,
                "candidateCount": 12,
            },
            "rerank": {
                "enabled": True,
                "method": "lexical_overlap_then_vector_score",
                "inputCount": 12,
                "outputCount": 1,
            },
            "filtering": {
                "docsetApplied": True,
                "docsetDocCount": 2,
                "postFilterCandidateCount": 12,
            },
        }

    _install_semantic_search(monkeypatch, fake_semantic_search)
    client = TestClient(server.app)

    response = client.post(
        "/api/v1/analysis/embedding_search",
        json={"term": "Klima", "top_n": 3, "docset_id": "docset-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["doc_id"] == 7
    assert body["rows"][0]["meta"] == {"source": "news", "year": 2026, "flags": ["ai"]}
    assert body["meta"]["exactness"] == "approximate"
    assert body["meta"]["candidateGeneration"]["method"] == "faiss_passage"
    assert body["meta"]["candidateGeneration"]["searchMode"] == "approximate"
    assert body["meta"]["rerank"]["enabled"] is True
    assert body["meta"]["filtering"] == {
        "docsetApplied": True,
        "docsetDocCount": 2,
        "postFilterCandidateCount": 12,
    }


def test_embedding_search_validates_docset_corpus_before_search(monkeypatch):
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: _fake_corpus())
    monkeypatch.setattr(
        analysis_routes,
        "semantic_search_status",
        lambda *_args, **_kwargs: SemanticAvailability(True, "", "", "spacy", "doc"),
    )
    monkeypatch.setattr(server, "_get_docset", lambda _docset_id: {"corpus": "other", "doc_ids": [7, 8]})

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("semantic search must not run for a foreign docset")

    _install_semantic_search(monkeypatch, fail_if_called)
    client = TestClient(server.app)

    response = client.post(
        "/api/v1/analysis/embedding_search",
        json={"term": "Klima", "corpus": "default", "docset_id": "docset-1"},
    )

    # DT-VERTRAEGE: docset/corpus mismatch is input validation -> 422 class.
    assert response.status_code == 422
    assert "Docset" in response.json()["detail"]


def test_embedding_search_rejects_unsupported_backend_level(monkeypatch):
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: _fake_corpus())
    client = TestClient(server.app)

    response = client.post(
        "/api/v1/analysis/embedding_search",
        json={"term": "Klima", "backend": "spacy", "level": "sentence"},
    )

    # DT-VERTRAEGE: an unsupported backend/level is an input-validation error.
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "semantic_unsupported"


def test_embedding_search_faiss_runtime_error_is_503_even_with_docset(monkeypatch):
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: _fake_corpus())
    monkeypatch.setattr(
        analysis_routes,
        "semantic_search_status",
        lambda *_args, **_kwargs: SemanticAvailability(True, "", "", "spacy", "doc"),
    )
    monkeypatch.setattr(
        server,
        "manager",
        SimpleNamespace(faiss_index_obj=None, passages=[]),
    )
    monkeypatch.setattr(server, "_get_docset", lambda _docset_id: {"corpus": "default", "doc_ids": [1, 2]})

    def raise_faiss_missing(*_args, **_kwargs):
        raise RuntimeError("FAISS Index fehlt")

    _install_semantic_search(monkeypatch, raise_faiss_missing)
    client = TestClient(server.app)

    response = client.post(
        "/api/v1/analysis/embedding_search",
        json={"term": "Klima", "docset_id": "docset-1"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "semantic_index_missing"
