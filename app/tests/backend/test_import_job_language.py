"""Import jobs of the web interface: the corpus language selects the pipeline.

Same rule as ``candy import --language``: ``spacy_model`` wins, a language
alone selects its standard pipeline, a contradiction blocks the preflight.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from candyconc.services.backend import corpus_import_jobs as jobs


def _pipeline(payload: dict) -> str:
    flat = [token for option in jobs.iter_method_options("csv", payload) for token in option]
    return flat[flat.index("--spacy-model") + 1]


def test_language_selects_the_standard_pipeline():
    assert _pipeline({}) == "de_core_news_md"
    assert _pipeline({"language": "en"}) == "en_core_web_md"
    assert _pipeline({"language": "en", "spacy_model": "en_core_web_sm"}) == "en_core_web_sm"


def test_descriptor_offers_languages_with_their_pipeline():
    csv = next(m for m in jobs.import_method_descriptors() if m["method"] == "csv")
    spec = next(s for s in csv["option_specs"] if s["key"] == "language")
    assert spec["type"] == "choice"
    by_value = {c["value"]: c for c in spec["choices"]}
    assert by_value[""]["label"] == ""
    assert by_value["en"]["pipeline"] == "en_core_web_md"
    assert by_value["de"]["pipeline"] == "de_core_news_md"


def test_contradiction_blocks_the_preflight(tmp_path: Path):
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n")
    managed = tmp_path / "corpora"
    managed.mkdir()
    result = jobs.preflight_import_job(
        "csv",
        str(src),
        {
            "target_name": "river",
            "language": "en",
            "spacy_model": "de_core_news_md",
            "__managed_corpus_dir": str(managed),
        },
    )
    assert result.get("blocking") is True
    check = next(c for c in result["checks"] if c["key"] == "spacy_model")
    assert check["status"] == "fail"
    assert "does not match" in check["message"]


def test_language_pipeline_is_the_one_the_preflight_checks(tmp_path: Path, monkeypatch):
    from candyconc.ingest import pipelines

    seen: list[str] = []
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: seen.append(name) or True)
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n")
    managed = tmp_path / "corpora"
    managed.mkdir()
    jobs.preflight_import_job(
        "csv", str(src), {"target_name": "river", "language": "en", "__managed_corpus_dir": str(managed)}
    )
    assert "en_core_web_md" in seen
