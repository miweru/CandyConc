"""Unpaired VRT documents keep the ID of the VRT file and claim no pair fields.

Before: a VRT document was named ``t1::source::<hash>`` and carried
``reference_kind: source``, ``reference_hash``, ``paired_with: []`` and
``model: vrt-import``, the layout of the human/AI research data model. CSV and
JSON Lines imports name a document by its ID and set ``variant: document`` and
``model: none``. VRT documents now do the same: the ID comes from
``<text id=...>`` (or the attribute named by ``--id-attrs``).
"""

from __future__ import annotations

import importlib
import sys

import pytest

pytest.importorskip("spacy", reason="spaCy not installed")

VRT = "\n".join(
    [
        '<text id="t1" source="demo" genre="news">',
        "<s>",
        "Tea\ttea\tNOUN",
        "is\tbe\tAUX",
        "good\tgood\tADJ",
        ".\t.\tPUNCT",
        "</s>",
        "</text>",
        '<text xml:id="t2" source="demo">',
        "<s>",
        "Coffee\tcoffee\tNOUN",
        "wins\twin\tVERB",
        ".\t.\tPUNCT",
        "</s>",
        "</text>",
    ]
)
PAIR_FIELDS = ("reference_kind", "reference_hash", "paired_with", "origin_id", "origin_doc_id", "pair_id", "ref_doc")
MODES = [
    ("--spacy-model", "blank:en", "--batch-size", "4", "--n-process", "1"),
    ("--annotation-mode", "adopt"),
]


def _metas(tmp_path, monkeypatch, *extra) -> list[dict]:
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    module = importlib.import_module("candyconc.ingest.build_fast_index_from_vrt")
    vrt = tmp_path / "demo.vrt"
    vrt.write_text(VRT, encoding="utf-8")
    out = tmp_path / "idx"
    monkeypatch.setattr(
        sys, "argv",
        ["build_fast_index_from_vrt.py", "--input", str(vrt), "--output", str(out),
         "--token-columns", "word,lemma,pos", *extra],
    )
    assert module.main() == 0
    from candyconc.core.corpus_index import CorpusIndex

    index = CorpusIndex(out, read_only=True)
    try:
        doc_metadata = index.fast_index.doc_metadata
        return [dict(doc_metadata.get(i)) for i in range(len(doc_metadata))]
    finally:
        index.close()


@pytest.mark.parametrize("extra", MODES, ids=["spacy", "adopt"])
def test_documents_are_named_by_their_vrt_id(tmp_path, monkeypatch, extra):
    metas = _metas(tmp_path, monkeypatch, *extra)
    assert [meta["doc_id"] for meta in metas] == ["t1", "t2"]
    assert [meta["path"] for meta in metas] == ["t1", "t2"]
    for meta in metas:
        assert meta["text_type"] == "standalone"
        assert (meta["variant"], meta["model"]) == ("document", "none")
        assert meta["source"] == "demo"
        assert not [field for field in PAIR_FIELDS if field in meta], meta
    assert metas[0]["genre"] == "news"


@pytest.mark.parametrize("extra", MODES, ids=["spacy", "adopt"])
def test_explicit_variant_and_model_are_kept(tmp_path, monkeypatch, extra):
    metas = _metas(tmp_path, monkeypatch, *extra, "--variant", "letters", "--model", "editor")
    assert {(meta["variant"], meta["model"]) for meta in metas} == {("letters", "editor")}
    assert [meta["doc_id"] for meta in metas] == ["t1", "t2"]
