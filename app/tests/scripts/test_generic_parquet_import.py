"""An ordinary Parquet table imports like CSV (inventar 20.4 and 20.5).

Before: ``candy import`` sent every Parquet file to the paired research layout
("Parquet fehlt input_text", then "Kein Alignment Anker fuer origin_id"), and
the builder's ``--generic`` mode still demanded ``input_text`` and indexed only
the research metadata fields instead of the chosen metadata columns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")
pytest.importorskip("spacy", reason="spaCy not installed")

from candyconc.core.corpus_index import CorpusIndex  # noqa: E402
from candyconc.core.index_format import IndexManifest  # noqa: E402


@pytest.fixture(autouse=True)
def _allow_small_disk(monkeypatch):
    # The disk preflight keeps a 5 GB reserve. These builds need kilobytes.
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)


def _table(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.parquet"
    pl.DataFrame(
        {
            "id": ["a", "b", "c"],
            "text": ["The river rose.", "Rain fell on the town.", ""],
            "genre": ["news", "fiction", "news"],
            "year": [1990, 1991, 1992],
        }
    ).write_parquet(path)
    return path


def _meta_fields(index_dir: Path) -> set[str]:
    data = json.loads((index_dir / "meta_index" / "meta_index.json").read_text())
    return {field["name"] for field in data["fields"]}


def _candy_import(monkeypatch, argv: list[str]) -> None:
    from candyconc.entrypoints import cli as candy_cli

    monkeypatch.setattr(sys, "argv", ["candy", "import", *argv])
    candy_cli.main()


def test_candy_import_reads_an_ordinary_parquet_table(tmp_path, monkeypatch):
    src = _table(tmp_path)
    out = tmp_path / "idx"
    report = tmp_path / "rejects.jsonl"
    _candy_import(
        monkeypatch,
        ["--input", str(src), "--output", str(out), "--spacy-model", "blank:en",
         "--meta-columns", "genre", "year", "--reject-report", str(report)],
    )
    idx = CorpusIndex(out, read_only=True)
    assert idx.token_count() == 10  # "The river rose ." + "Rain fell on the town ."
    assert IndexManifest.load(out).import_mode == "generic"
    assert {"genre", "year"} <= _meta_fields(out)
    meta0 = idx.fast_index.doc_metadata.get(0) or {}
    assert meta0.get("genre") == "news"
    assert meta0.get("year") == "1990"
    # The empty third row is reported, as in the CSV import.
    assert "empty_text_column" in report.read_text()


def test_parquet_builder_generic_mode_indexes_the_chosen_meta_columns(tmp_path):
    # The route the web interface and the API take: --generic, no
    # --allow-missing-input-text, no --meta-index-fields, preflight on.
    from candyconc.ingest.build_fast_index_from_parquet import main

    src = _table(tmp_path)
    out = tmp_path / "idx"
    rc = main(
        ["--input", str(src), "--output", str(out), "--generic", "--text-column", "text",
         "--id-column", "id", "--meta-columns", "genre", "year", "--spacy-model", "blank:en"]
    )
    assert rc == 0
    assert {"genre", "year"} <= _meta_fields(out)


def test_candy_import_keeps_the_paired_research_layout(tmp_path, monkeypatch):
    # A file in the research data model (target_text, no "text" column) still
    # takes the aligned builder, nothing was removed.
    src = tmp_path / "aligned.parquet"
    pl.DataFrame(
        {
            "source": ["news", "news"],
            "doc_id": ["d1", "d1"],
            "variant": ["rewrite", "simplify"],
            "model": ["gptA", "gptB"],
            "text_type": ["ai", "ai"],
            "input_text": ["Quelle eins.", "Quelle eins."],
            "target_text": ["Umschrift eins.", "Einfach eins."],
        }
    ).write_parquet(src)
    out = tmp_path / "idx"
    _candy_import(monkeypatch, ["--input", str(src), "--output", str(out), "--spacy-model", "blank:de"])
    manifest = IndexManifest.load(out)
    assert manifest.import_mode != "generic"
    assert manifest.paired is True


def test_candy_import_names_the_columns_when_the_text_column_is_missing(tmp_path, monkeypatch):
    src = tmp_path / "other.parquet"
    pl.DataFrame({"id": ["a"], "body": ["The river rose."]}).write_parquet(src)
    with pytest.raises(SystemExit) as exc:
        _candy_import(monkeypatch, ["--input", str(src), "--output", str(tmp_path / "idx"),
                                    "--spacy-model", "blank:en"])
    message = str(exc.value.code)
    assert "'text'" in message and "body" in message and "--text-column" in message
