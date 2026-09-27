"""Optional extras: a missing package yields a clear message, not a crash.

faiss (extra ``semantic``) backs the semantic passage search and the local
semantic index build. The corpus feature contract and the build preflight
report its absence, so the interface can explain instead of failing later.
"""

from __future__ import annotations

from types import SimpleNamespace

from candyconc.domain import corpus as corpus_mod
from candyconc.services import semantic_index_jobs as jobs


def _passage_index(tmp_path):
    for name in ("faiss_gemma_doc.index", "gemma_doc_vecs.npy", "gemma_doc_texts.json"):
        (tmp_path / name).write_bytes(b"x")
    return tmp_path


def test_feature_contract_names_missing_faiss(tmp_path, monkeypatch):
    index_dir = _passage_index(tmp_path)
    monkeypatch.setattr(corpus_mod, "_faiss_importable", lambda: False)
    features = corpus_mod._corpus_feature_descriptor({}, SimpleNamespace(paired=False, pair_axes=[]), index_dir)
    assert features["semantic"]["passage_search"] is False
    assert features["semantic"]["missing_packages"] == ["faiss-cpu"]


def test_feature_contract_with_faiss_keeps_passage_search(tmp_path, monkeypatch):
    index_dir = _passage_index(tmp_path)
    monkeypatch.setattr(corpus_mod, "_faiss_importable", lambda: True)
    features = corpus_mod._corpus_feature_descriptor({}, SimpleNamespace(paired=False, pair_axes=[]), index_dir)
    assert features["semantic"]["passage_search"] is True
    assert features["semantic"]["missing_packages"] == []


def test_semantic_build_refuses_without_faiss_with_install_hint(monkeypatch):
    monkeypatch.setattr(jobs, "_faiss_installed", lambda: False)
    monkeypatch.setattr(
        jobs,
        "preflight",
        lambda _index, _name: {
            "available_levels": {"doc": False, "sentence": False},
            "options": {"doc": {"can_build": False}},
            "platform": {"supported": True},
            "runtime": {"faiss_installed": False},
        },
    )
    try:
        jobs._launch_unlocked(object(), "demo", ["doc"])
    except RuntimeError as exc:
        assert "candyconc[semantic]" in str(exc)
    else:  # pragma: no cover - must not be reached
        raise AssertionError("launch without faiss must fail with a clear message")
