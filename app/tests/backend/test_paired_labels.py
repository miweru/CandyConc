"""Paired imports label their versions with neutral terms and with the data.

The prealigned importer stored every anchor as ``text_type: human`` with
``model: human`` and every other version as ``text_type: ai``, whatever the
texts were. The parallel concordance listed the anchor of an easy-language
corpus as "human", and every consumer of ``text_type`` saw a human and an AI
side. Anchors are now ``anchor`` and the other versions ``version``, and the
``model`` of an anchor is its role from the data unless a model column names
one. Indexes with ``human``/``ai`` keep working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.index_format import BUILDER_REVISION
from candyconc.services.backend import server

pytest.importorskip("spacy", reason="spaCy not installed")

PAIRED_CSV = """id,pair_id,pair_role,text,level
s1,p1,source,"The committee postponed the decision because the figures were incomplete.",original
s1e,p1,easy,"The committee did not decide yet. The numbers were not complete.",easy
s2,p2,source,"The museum will close early on Friday because of the concert.",original
s2e,p2,easy,"The museum will close early on Friday. There is a concert.",easy
"""


@pytest.fixture(scope="module")
def paired_index(tmp_path_factory) -> Path:
    from candyconc.ingest.ingest_adapters import build_index_from_prealigned_csv

    root = tmp_path_factory.mktemp("paired")
    src = root / "paired.csv"
    src.write_text(PAIRED_CSV, encoding="utf-8")
    out = root / "paired_en"
    build_index_from_prealigned_csv(src, out, spacy_model="blank:en", meta_columns=["level"])
    return out


def _metas(idx: CorpusIndex) -> dict[str, dict]:
    return {str(meta["doc_id"]): dict(meta) for meta in idx.fast_index.doc_metadata.values()}


def test_anchor_and_version_carry_neutral_sides_and_data_roles(paired_index):
    idx = CorpusIndex(paired_index)
    metas = _metas(idx)
    anchor, version = metas["s1"], metas["s1e"]
    assert (anchor["text_type"], anchor["model"], anchor["pair_role"]) == ("anchor", "source", "source")
    assert (version["text_type"], version["model"], version["pair_role"]) == ("version", "easy", "easy")
    # The finalisation still links the anchor to its versions.
    assert anchor["paired_with"] == [version_doc_idx(idx, "s1e")]
    assert sorted(idx.metadata_values("model")) == ["easy", "source"]
    assert "human" not in idx.metadata_values("text_type")
    assert "ai" not in idx.metadata_values("text_type")
    assert idx.manifest.builder_revision == BUILDER_REVISION >= 2


def version_doc_idx(idx: CorpusIndex, doc_id: str) -> int:
    for raw, meta in idx.fast_index.doc_metadata.items():
        if meta.get("doc_id") == doc_id:
            return int(raw)
    raise AssertionError(doc_id)


@pytest.fixture
def client(paired_index, tmp_path, monkeypatch):
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    idx = CorpusIndex(paired_index)
    server.reset_default_corpus_runtime_state()
    server.set_default_index(idx, path=paired_index, corpus_index=idx)
    yield TestClient(server.app), idx
    server.reset_default_corpus_runtime_state()


def test_parallel_groups_find_the_anchor(client):
    http, idx = client
    body = http.post("/api/v1/analysis/parallel_groups", json={"limit": 10}).json()
    assert body["total"] == 2
    first = body["groups"][0]
    assert first["human_doc_id"] == version_doc_idx(idx, "s1")
    assert first["variant_doc_ids"] == [version_doc_idx(idx, "s1e")]
    assert first["text_types"] == {"anchor": 1, "version": 1}
    assert [m["label"] for m in first["models"]] == ["easy"]


def test_parallel_concordance_from_the_anchor_shows_the_version(client):
    http, idx = client
    rows = http.get("/api/v1/query", params={"term": "museum"}).json()
    anchor_row = next(row for row in rows if row["doc"] == "s2")
    body = http.post(
        "/api/v1/analysis/kwic_parallel",
        json={"pos": anchor_row["pos"], "keyword": "museum"},
    ).json()
    assert body["base_doc_id"] == version_doc_idx(idx, "s2")
    assert [(v["model"], v["text_type"], v["kw"]) for v in body["variants"]] == [("easy", "version", "museum")]


def test_parallel_concordance_from_a_version_lists_the_anchor_first(client):
    http, idx = client
    rows = http.get("/api/v1/query", params={"term": "museum"}).json()
    version_row = next(row for row in rows if row["doc"] == "s2e")
    body = http.post(
        "/api/v1/analysis/kwic_parallel",
        json={"pos": version_row["pos"], "keyword": "museum"},
    ).json()
    assert [(v["model"], v["text_type"]) for v in body["variants"]] == [("source", "anchor")]


def _fake_index(metas: dict[int, dict]) -> SimpleNamespace:
    import numpy as np

    boundaries = SimpleNamespace(document=SimpleNamespace(_positions=np.arange(len(metas), dtype=np.uint32)))
    return SimpleNamespace(
        fast_index=SimpleNamespace(doc_metadata=metas, boundaries=boundaries),
        manifest=SimpleNamespace(pair_axes=["prealigned"]),
    )


@pytest.mark.parametrize(
    ("anchor_type", "version_type"),
    [("human", "ai"), ("anchor", "version")],
)
def test_pair_groups_accept_old_and_new_labels(anchor_type, version_type):
    from candyconc.services.backend import alignment

    metas = {
        0: {"doc_id": "a", "text_type": anchor_type, "model": "source", "paired_with": [1]},
        1: {"doc_id": "b", "text_type": version_type, "model": "easy", "ref_doc": 0},
        2: {"doc_id": "c", "text_type": anchor_type, "model": "source", "paired_with": []},
    }
    idx = _fake_index(metas)
    corpus = f"labels-{anchor_type}"
    alignment._REFDOC_INDEX_CACHE.pop(corpus, None)
    assert alignment._refdoc_index_for_corpus(idx, corpus) == {0: [0, 1], 2: [2]}
    summary = server._parallel_group_summary(idx, 0, [1, 0])
    assert summary["human_doc_id"] == 0
    assert summary["variant_doc_ids"] == [1]
    assert server._parse_ref_doc_from_meta(metas[2], 2) == 2


def _manifest(path: Path, **fields) -> Path:
    path.mkdir(parents=True)
    (path / "meta.bin").write_bytes((0).to_bytes(8, "little"))
    payload = {
        "manifest_version": 1,
        "import_mode": "prealigned",
        "paired": True,
        "pair_axes": ["prealigned"],
        "annotation_source": "spacy",
        "capabilities": {},
        "dtypes": {},
        "build_fingerprint": "fixture",
        "created_at": "2026-09-27T00:00:00Z",
        "complete": True,
    }
    payload.update(fields)
    (path / "index_manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_pairing_schema_names_the_anchor_value_of_the_index(paired_index, tmp_path):
    from candyconc.domain.corpus import corpus_summary

    def anchor_value(index_dir: Path) -> str:
        schema = corpus_summary(index_dir)["features"]["alignment"]["pairing_schema"]
        return schema["default_anchor_role"]

    assert anchor_value(paired_index) == "anchor"
    assert anchor_value(_manifest(tmp_path / "old_prealigned", builder_revision=1)) == "human"
    assert anchor_value(_manifest(tmp_path / "research", import_mode="paired-parquet", builder_revision=2)) == "human"
