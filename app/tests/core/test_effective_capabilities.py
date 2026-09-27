"""C1 (capability truth): effective_capabilities reconciles the FROZEN manifest
capability dict with CURRENT artifact presence for post-build-mutable keys
(embeddings / sentence_embeddings), without ever touching the
manifest on disk. Build-derived keys stay manifest-authoritative.

Pure-function tests — no index build, no spaCy/polars needed.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.core.index_format import (  # noqa: E402
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    _POST_BUILD_CAPABILITY_KEYS,
    effective_capabilities,
)


def _frozen_caps(**overrides) -> dict:
    caps = {
        "word_lex": True,
        "lemma_lex": True,
        "embeddings": False,
        "sentence_embeddings": False,
    }
    caps.update(overrides)
    return caps


def test_passage_faiss_alone_does_not_create_a_raw_capability(tmp_path):
    """A passage index alone is not a misleading ``word_faiss`` capability."""
    (tmp_path / "faiss_passage.index").write_bytes(b"fake")
    caps = effective_capabilities(_frozen_caps(), tmp_path)
    assert caps["embeddings"] is False  # passage_vecs.npy still absent
    assert caps["sentence_embeddings"] is False
    assert "word_faiss" not in caps


def test_artifact_deleted_post_build_flips_false(tmp_path):
    """Manifest claims embeddings, artifact gone → flag False."""
    caps = effective_capabilities(_frozen_caps(embeddings=True), tmp_path)
    assert caps["embeddings"] is False


def test_build_derived_keys_stay_manifest_authoritative(tmp_path):
    """word_lex/lemma_lex etc. are NOT re-probed — the manifest stays the truth
    for build-produced artifacts even if no file exists in the dir."""
    caps = effective_capabilities(_frozen_caps(), tmp_path)
    assert caps["word_lex"] is True
    assert caps["lemma_lex"] is True


def test_input_dict_not_mutated(tmp_path):
    (tmp_path / "faiss_passage.index").write_bytes(b"fake")
    frozen = _frozen_caps()
    before = dict(frozen)
    effective_capabilities(frozen, tmp_path)
    assert frozen == before


def test_post_build_key_set_is_exactly_embedding_class():
    assert _POST_BUILD_CAPABILITY_KEYS == {"embeddings", "sentence_embeddings"}


def test_corpus_summary_reconciles_and_leaves_manifest_byte_identical(tmp_path):
    """corpus_summary reports the reconciled view while index_manifest.json on
    disk stays byte-identical (read-side only, no rewrite)."""
    from candyconc.domain.corpus import corpus_summary

    (tmp_path / "meta.bin").write_bytes(struct.pack("<Q", 42))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "import_mode": "generic",
        "paired": False,
        "pair_axes": [],
        "annotation_source": "spacy",
        "capabilities": _frozen_caps(),
        "dtypes": {},
        "build_fingerprint": "fp",
        "created_at": "2026-01-01T00:00:00+00:00",
        "complete": True,
    }
    mpath = tmp_path / MANIFEST_FILENAME
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    # An old manifest can still contain the retired raw alias. Reading it must
    # not rewrite the file or expose the alias to the capability response.
    (tmp_path / "faiss_passage.index").write_bytes(b"fake")
    manifest["capabilities"]["word_faiss"] = False
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    raw_before = mpath.read_bytes()
    summary = corpus_summary(tmp_path)
    assert "word_faiss" not in summary["capabilities"]
    assert summary["capabilities"]["word_lex"] is True
    assert summary["token_count"] == 42
    assert summary["features"]["schema_version"] == "corpus-features-v1"
    assert summary["features"]["semantic"]["passage_search"] is False
    assert summary["features"]["semantic"]["word_similarity"] is False
    assert summary["features"]["alignment"]["pairing_schema"] is None

    # Manifest on disk untouched, byte for byte.
    assert mpath.read_bytes() == raw_before
    # The stale disk entry remains untouched; only the runtime contract drops it.
    assert json.loads(raw_before)["capabilities"]["word_faiss"] is False


def test_corpus_summary_exposes_versioned_feature_descriptor(tmp_path, monkeypatch):
    from candyconc.domain import corpus as corpus_mod
    from candyconc.domain.corpus import corpus_summary

    # Artifact recognition with the optional faiss package installed (extra
    # "semantic"). Without it, passage_search is false and missing_packages
    # names faiss-cpu (tests/services/test_optional_packages_reported.py).
    monkeypatch.setattr(corpus_mod, "_faiss_importable", lambda: True)

    (tmp_path / "meta.bin").write_bytes(struct.pack("<Q", 42))
    (tmp_path / "faiss_passage.index").write_bytes(b"fake")
    (tmp_path / "passage_vecs.npy").write_bytes(b"fake")
    (tmp_path / "faiss_word.index").write_bytes(b"fake")
    (tmp_path / "word_ids.npy").write_bytes(b"fake")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "import_mode": "generic",
        "paired": True,
        "pair_axes": ["model"],
        "annotation_source": "spacy",
        "capabilities": _frozen_caps(pos_lex=True, ent_lex=True),
        "dtypes": {},
        "build_fingerprint": "fp",
        "created_at": "2026-01-01T00:00:00+00:00",
        "complete": True,
    }
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    features = corpus_summary(tmp_path)["features"]

    assert [attr["id"] for attr in features["token_attributes"]] == [
        "word",
        "lemma",
        "pos",
        "ner",
        "sim",
    ]
    assert [group["id"] for group in features["frequency_groups"]] == ["word", "lemma", "pos"]
    assert features["semantic"] == {
        "passage_search": True,
        "word_similarity": True,
        "sentence_alignment": False,
        "missing_packages": [],
    }
    assert features["alignment"]["parallel_kwic"] is True
    assert features["alignment"]["pair_axes"] == ["model"]
    assert features["alignment"]["pairing_schema"] == {
        "schema_id": "legacy_ref_doc_v1",
        "group_key_field": "ref_doc",
        "anchor_role_field": "text_type",
        "default_anchor_role": "human",
        "variant_axis_fields": ["model"],
        "legacy_variant_filter_field": "model",
        "generic_axis_filters": False,
        "legacy_response_fields": {
            "anchor_doc_id": "human_doc_id",
            "comparison_doc_ids": "variant_doc_ids",
            "variant_counts": "models",
        },
    }


def test_corpus_summary_recognises_complete_gemma_document_search(tmp_path, monkeypatch):
    from candyconc.domain import corpus as corpus_mod
    from candyconc.domain.corpus import corpus_summary

    monkeypatch.setattr(corpus_mod, "_faiss_importable", lambda: True)

    (tmp_path / "meta.bin").write_bytes(struct.pack("<Q", 42))
    for artifact in (
        "faiss_gemma_doc.index",
        "gemma_doc_vecs.npy",
        "gemma_doc_texts.json",
    ):
        (tmp_path / artifact).write_bytes(b"fake")
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "import_mode": "generic",
        "paired": False,
        "pair_axes": [],
        "annotation_source": "spacy",
        "capabilities": _frozen_caps(),
        "dtypes": {},
        "build_fingerprint": "fp",
        "created_at": "2026-01-01T00:00:00+00:00",
        "complete": True,
    }
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    assert corpus_summary(tmp_path)["features"]["semantic"]["passage_search"] is True
