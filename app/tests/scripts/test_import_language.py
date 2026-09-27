"""Corpus language as a property of the import and of the index.

``candy import --language`` selects a standard pipeline, ``--spacy-model``
stays the explicit way, a contradiction between both stops the import. The
manifest records language and pipeline, the corpus API returns them, and an
index built before these fields reads as unknown.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from candyconc.ingest import pipelines

spacy = pytest.importorskip("spacy", reason="spaCy not installed")


# --------------------------------------------------------------------------- #
# Pipeline choice
# --------------------------------------------------------------------------- #
def test_without_language_and_model_german_stays_the_default():
    assert pipelines.resolve_import_pipeline(None, None) == "de_core_news_md"
    assert pipelines.resolve_import_pipeline("", "") == "de_core_news_md"


def test_language_selects_its_standard_pipeline():
    assert pipelines.resolve_import_pipeline("en", None) == "en_core_web_md"
    assert pipelines.resolve_import_pipeline("EN-us", None) == "en_core_web_md"
    assert pipelines.resolve_import_pipeline("fr", None) == "fr_core_news_md"
    assert pipelines.resolve_import_pipeline("de", None) == "de_core_news_md"


def test_language_without_trained_pipeline_tokenizes_with_blank():
    # Basque has a spaCy tokenizer but no trained pipeline.
    assert pipelines.resolve_import_pipeline("eu", None) == "blank:eu"


def test_unknown_language_code_is_rejected():
    with pytest.raises(ValueError):
        pipelines.resolve_import_pipeline("qq", None)
    with pytest.raises(ValueError):
        pipelines.resolve_import_pipeline("english", None)


def test_explicit_model_wins_when_it_matches_the_language():
    assert pipelines.resolve_import_pipeline("en", "en_core_web_sm") == "en_core_web_sm"
    assert pipelines.resolve_import_pipeline("en", "blank:en") == "blank:en"
    assert pipelines.resolve_import_pipeline(None, "en_core_web_sm") == "en_core_web_sm"


def test_contradicting_language_and_model_raise():
    with pytest.raises(ValueError, match="does not match"):
        pipelines.resolve_import_pipeline("en", "de_core_news_md")
    with pytest.raises(ValueError, match="does not match"):
        pipelines.resolve_import_pipeline("de", "blank:en")


def _stub_builder(monkeypatch, recorder: dict, script: str = "ingest_adapters.py") -> None:
    from candyconc.builders import _runner

    stub = ModuleType("candyconc.builders._stub_language_builder")

    def _main(argv):
        recorder["argv"] = list(argv)
        return 0

    stub.main = _main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "candyconc.builders._stub_language_builder", stub)
    monkeypatch.setitem(_runner._INPROCESS_MODULES, script, ("candyconc.builders._stub_language_builder",))


def _run_cli(monkeypatch, argv: list[str]) -> None:
    from candyconc.entrypoints import cli as candy_cli

    monkeypatch.setattr(sys, "argv", ["candy", "import", *argv])
    candy_cli.main()


def test_cli_language_passes_the_standard_pipeline(monkeypatch, tmp_path):
    recorder: dict = {}
    _stub_builder(monkeypatch, recorder)
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: True)
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n")
    _run_cli(monkeypatch, ["--input", str(src), "--output", str(tmp_path / "idx"), "--language", "en"])
    argv = recorder["argv"]
    assert argv[argv.index("--spacy-model") + 1] == "en_core_web_md"


def test_cli_contradiction_stops_before_the_builder(monkeypatch, tmp_path):
    recorder: dict = {}
    _stub_builder(monkeypatch, recorder)
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n")
    with pytest.raises(SystemExit) as exc:
        _run_cli(
            monkeypatch,
            ["--input", str(src), "--output", str(tmp_path / "idx"),
             "--language", "en", "--spacy-model", "de_core_news_md"],
        )
    assert "does not match" in str(exc.value.code)
    assert "argv" not in recorder


def test_cli_without_language_keeps_german_default(monkeypatch, tmp_path):
    recorder: dict = {}
    _stub_builder(monkeypatch, recorder)
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: True)
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,Der Fluss stieg.\n")
    _run_cli(monkeypatch, ["--input", str(src), "--output", str(tmp_path / "idx")])
    argv = recorder["argv"]
    assert argv[argv.index("--spacy-model") + 1] == "de_core_news_md"


# --------------------------------------------------------------------------- #
# Manifest and corpus API
# --------------------------------------------------------------------------- #
def test_build_records_language_and_pipeline(tmp_path, monkeypatch):
    from candyconc.core.index_format import BUILDER_REVISION, IndexManifest
    from candyconc.domain.corpus import corpus_summary
    from candyconc.ingest import ingest_adapters as ia

    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n2,The rain fell.\n")
    out = tmp_path / "idx"
    ia.build_index_from_csv(src, out, spacy_model="blank:en", text_column="text", id_column="id",
                            batch_size=2, n_process=1)
    manifest = IndexManifest.load(out)
    assert manifest.language == "en"
    assert manifest.annotation_pipeline == "blank:en"
    assert manifest.pipeline_vectors == 0
    assert manifest.builder_revision == BUILDER_REVISION
    summary = corpus_summary(out)
    assert summary["language"] == "en"
    assert summary["annotation_pipeline"] == "blank:en"


def test_index_without_language_field_reads_as_unknown(tmp_path):
    # A manifest written before the language fields: no guessing from the
    # recorded spaCy model name.
    from candyconc.core.index_format import MANIFEST_FILENAME, IndexManifest
    from candyconc.domain.corpus import corpus_summary

    (tmp_path / "word_lexicon.bin").write_bytes(b"x")
    (tmp_path / "meta.bin").write_bytes((7).to_bytes(8, "little"))
    old = {
        "manifest_version": 1, "import_mode": "csv", "paired": False, "pair_axes": [],
        "annotation_source": "spacy", "capabilities": {"word_lex": True}, "dtypes": {},
        "build_fingerprint": "fp", "created_at": "2026-09-01T00:00:00+00:00", "complete": True,
    }
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps(old))
    (tmp_path / "index_build_meta.json").write_text(json.dumps({"spacy_model": "en_core_web_sm"}))
    manifest = IndexManifest.load(tmp_path)
    assert manifest.language == ""
    assert manifest.builder_revision == 0
    assert manifest.pipeline_vectors == -1
    summary = corpus_summary(tmp_path)
    assert summary["language"] is None
    # The recorded build model is a fact of the build, not a guess.
    assert summary["annotation_pipeline"] == "en_core_web_sm"


def test_pipeline_label_names_packages_not_paths():
    nlp = spacy.blank("en")
    assert pipelines.pipeline_label("blank:en", nlp) == ("blank:en", "")
    nlp.meta["name"] = "core_web_sm"
    nlp.meta["version"] = "3.8.0"
    assert pipelines.pipeline_label("/Users/x/models/en_core_web_sm", nlp) == ("en_core_web_sm", "3.8.0")
