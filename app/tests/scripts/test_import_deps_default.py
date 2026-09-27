"""Dependency parsing is on by default when the pipeline has a parser.

Before, every import without --enable-deps left Word Sketch and rel/head
queries locked, although the standard pipelines ship a parser. Measured on
the sample corpora the parser adds about 15 percent CPU time to an import.
``--no-deps`` and ``enable_deps: false`` keep the old behaviour.
"""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from candyconc.ingest import pipelines
from candyconc.services.backend import corpus_import_jobs as jobs


def _stub_builder(monkeypatch, recorder: dict) -> None:
    from candyconc.builders import _runner

    stub = ModuleType("candyconc.builders._stub_deps_builder")

    def _main(argv):
        recorder["argv"] = list(argv)
        return 0

    stub.main = _main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "candyconc.builders._stub_deps_builder", stub)
    monkeypatch.setitem(_runner._INPROCESS_MODULES, "ingest_adapters.py", ("candyconc.builders._stub_deps_builder",))


def _import(monkeypatch, tmp_path, *extra: str) -> list[str]:
    from candyconc.entrypoints import cli as candy_cli

    recorder: dict = {}
    _stub_builder(monkeypatch, recorder)
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,The river rose.\n")
    monkeypatch.setattr(sys, "argv", ["candy", "import", "--input", str(src), "--output", str(tmp_path / "idx"), *extra])
    candy_cli.main()
    return recorder["argv"]


@pytest.fixture
def _parser_pipeline(monkeypatch):
    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: True)
    monkeypatch.setattr(pipelines, "pipeline_has_parser", lambda name: not pipelines.is_blank(name))


def test_cli_parses_dependencies_when_the_pipeline_has_a_parser(monkeypatch, tmp_path, _parser_pipeline):
    assert "--enable-deps" in _import(monkeypatch, tmp_path, "--language", "en")


def test_cli_no_deps_and_blank_pipelines_stay_without(monkeypatch, tmp_path, _parser_pipeline):
    assert "--enable-deps" not in _import(monkeypatch, tmp_path, "--language", "en", "--no-deps")
    assert "--enable-deps" not in _import(monkeypatch, tmp_path, "--spacy-model", "blank:en")


def test_cli_explicit_enable_deps_is_passed_on(monkeypatch, tmp_path, _parser_pipeline):
    assert "--enable-deps" in _import(monkeypatch, tmp_path, "--spacy-model", "blank:en", "--enable-deps")


def _job_flags(payload: dict) -> list[str]:
    return [token for option in jobs.iter_method_options("csv", payload) for token in option]


def test_import_job_uses_the_same_default(monkeypatch, _parser_pipeline):
    assert "--enable-deps" in _job_flags({"language": "en"})
    assert "--enable-deps" not in _job_flags({"language": "en", "enable_deps": False})
    assert "--enable-deps" not in _job_flags({"spacy_model": "blank:en"})
    spec = next(s for s in jobs._COMMON_OPTION_SPECS if s["key"] == "enable_deps")
    assert spec["default"] is True


def test_parser_detection_reads_the_pipeline_meta():
    assert pipelines.pipeline_has_parser("blank:en") is False
    assert pipelines.pipeline_has_parser("candyconc_missing_pipeline") is False


@pytest.mark.parametrize("mode", ["none", "sidecar", "adopt"])
@pytest.mark.parametrize("explicit", [None, False, True])
def test_vrt_dependencies_follow_annotation_mode_unless_explicit(_parser_pipeline, mode, explicit):
    payload = {"language": "en", "annotation_mode": mode}
    if explicit is not None:
        payload["enable_deps"] = explicit
    flags = [token for option in jobs.iter_method_options("vrt", payload) for token in option]
    expected = mode != "adopt" if explicit is None else explicit
    assert ("--enable-deps" in flags) is expected
