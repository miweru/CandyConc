from __future__ import annotations

from candyconc.config import APP_CONFIG
from candyconc.services.semantic.availability import (
    semantic_artifact_paths,
    semantic_search_available,
    semantic_search_status,
)


def test_semantic_search_stays_off_without_assets(tmp_path):
    previous = APP_CONFIG.ENABLE_EMBEDDING_SEARCH
    APP_CONFIG.ENABLE_EMBEDDING_SEARCH = True
    try:
        assert not semantic_search_available(tmp_path, backend="spacy")
    finally:
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = previous



def test_semantic_search_detects_passage_assets(tmp_path):
    previous = APP_CONFIG.ENABLE_EMBEDDING_SEARCH
    APP_CONFIG.ENABLE_EMBEDDING_SEARCH = True
    try:
        for path in semantic_artifact_paths(tmp_path, backend="spacy"):
            path.write_bytes(b"x")
        assert semantic_search_available(tmp_path, backend="spacy")
    finally:
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = previous


def test_semantic_search_rejects_unsupported_backend_level(tmp_path):
    previous = APP_CONFIG.ENABLE_EMBEDDING_SEARCH
    APP_CONFIG.ENABLE_EMBEDDING_SEARCH = True
    try:
        status = semantic_search_status(tmp_path, backend="spacy", level="sentence")
        assert not status.available
        assert status.code == "semantic_unsupported"
        assert semantic_artifact_paths(tmp_path, backend="spacy", level="sentence") == ()
    finally:
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = previous


def test_semantic_search_uses_gemma_level_specific_assets(tmp_path):
    previous = APP_CONFIG.ENABLE_EMBEDDING_SEARCH
    APP_CONFIG.ENABLE_EMBEDDING_SEARCH = True
    try:
        paths = semantic_artifact_paths(tmp_path, backend="gemma", level="sentence")
        assert {path.name for path in paths} == {
            "faiss_gemma_sentence.index",
            "gemma_sentence_vecs.npy",
            "gemma_sentence_texts.json",
        }
    finally:
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = previous
