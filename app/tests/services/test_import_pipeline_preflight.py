"""The import preflight checks the chosen spaCy pipeline (erprobung B7).

Before, the preflight of the interface passed a missing pipeline and the job
failed afterwards with "builder exited with code 2", suggesting blank:de even
for an English corpus.
"""

from __future__ import annotations

from candyconc.ingest import pipelines
from candyconc.services.backend import corpus_import_jobs as jobs


def _csv(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("doc_id,text\nd1,The river rose.\n", encoding="utf-8")
    return source


def test_missing_pipeline_fails_the_preflight_with_the_install_command(tmp_path, monkeypatch):
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: pipelines.is_blank(name))
    source = _csv(tmp_path)
    result = jobs.preflight_import_job(
        "csv", str(source), {"method": "csv", "input_path": str(source), "text_column": "text", "spacy_model": "en_core_web_sm"}
    )
    check = next(item for item in result["checks"] if item["key"] == "spacy_model")
    assert check["status"] == "fail"
    assert result["ok"] is False
    assert "candy pipeline en_core_web_sm" in check["message"]
    assert "blank:en" in check["message"]
    assert "blank:de" not in check["message"]
    assert check["evidence"]["blank_alternative"] == "blank:en"


def test_blank_pipeline_passes_without_download(tmp_path):
    source = _csv(tmp_path)
    result = jobs.preflight_import_job(
        "csv", str(source), {"method": "csv", "input_path": str(source), "text_column": "text", "spacy_model": "blank:en"}
    )
    check = next(item for item in result["checks"] if item["key"] == "spacy_model")
    assert check["status"] == "pass"


def test_pipeline_helpers():
    assert pipelines.blank_alternative("en_core_web_sm") == "blank:en"
    assert pipelines.blank_alternative("de_core_news_md") == "blank:de"
    assert pipelines.blank_alternative("custom") == "blank:xx"
    assert pipelines.is_blank("blank:en")
    assert pipelines.pipeline_installed("blank:en")
    assert not pipelines.pipeline_installed("xx_no_such_pipeline_sm")
    assert "candy pipeline xx_no_such_pipeline_sm" in pipelines.missing_message("xx_no_such_pipeline_sm")


def test_install_command_prefers_pip_then_uv(monkeypatch, tmp_path):
    import importlib.util
    import shutil

    url = "https://example.invalid/en_core_web_sm-3.8.0-py3-none-any.whl"
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pip" else real_find_spec(name, *a))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    cmd = pipelines.install_command(url, target=tmp_path)
    assert cmd[:3] == ["/usr/bin/uv", "pip", "install"]
    assert "--target" in cmd and str(tmp_path) in cmd
    monkeypatch.setattr(shutil, "which", lambda name: None)
    try:
        pipelines.install_command(url)
    except RuntimeError as exc:
        assert url in str(exc)
    else:  # pragma: no cover
        raise AssertionError("without pip and uv the command must fail with the URL")
