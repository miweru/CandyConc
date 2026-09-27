import sys
from types import ModuleType, SimpleNamespace

import pytest

from candyconc.utils.import_builders import (
    find_builder_script,
    import_builder_spec,
    normalize_import_method,
)

# NOTE: the dead ``CandyService`` GUI dispatch path (and its ``_iter_method_options``
# helper) were removed in the D13 dead-code cleanup. The tests that exercised
# ``CandyService.import_corpus`` / ``controller._iter_method_options`` went with it
# because they only covered that dead class. The LIVE import surface — the
# ``candyconc.utils.import_builders`` helpers and the ``candy import`` CLI command
# (``candyconc.entrypoints.cli``) — is the real, shipped path and is covered below.


def test_import_builder_specs_normalize_hyphen_and_underscore():
    assert normalize_import_method("prealigned-csv") == "prealigned_csv"
    spec = import_builder_spec("prealigned-csv")
    assert spec is not None
    assert spec.script_name == "ingest_adapters.py"
    assert spec.subcommand == ("prealigned-csv",)


def test_find_builder_script_walks_upward_and_supports_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    root = tmp_path / "repo"
    jobs = root / "scripts" / "jobs"
    jobs.mkdir(parents=True)
    script = jobs / "ingest_adapters.py"
    script.write_text("# fake\n", encoding="utf-8")

    nested = root / "third_party" / "candyconc" / "app" / "src"
    nested.mkdir(parents=True)
    assert find_builder_script("ingest_adapters.py", start=nested) == script

    override = tmp_path / "override"
    override.mkdir()
    override_script = override / "build_fast_index_from_vrt.py"
    override_script.write_text("# fake\n", encoding="utf-8")
    monkeypatch.setenv("CANDYCONC_BUILDER_DIR", str(override))
    assert find_builder_script("build_fast_index_from_vrt.py", start=nested) == override_script


def _install_stub_ingest_adapters(monkeypatch, recorder: dict, *, rc: int = 0) -> None:
    """Register a fake in-process ingest_adapters module that records argv.

    Since the S4 Ingestion-Adoption the ingest adapters are wired into
    ``_runner._INPROCESS_MODULES`` (wheel-safe), so ``candy import`` dispatches
    them IN-PROCESS — the stub takes the place of the real (spaCy-heavy)
    implementation and any accidental subprocess fallback fails loud.
    """

    from candyconc.builders import _runner

    stub = ModuleType("candyconc.builders._stub_ingest_adapters")

    def _main(argv):
        recorder["argv"] = list(argv)
        return rc

    stub.main = _main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "candyconc.builders._stub_ingest_adapters", stub)
    monkeypatch.setitem(
        _runner._INPROCESS_MODULES,
        "ingest_adapters.py",
        ("candyconc.builders._stub_ingest_adapters",),
    )


def _forbid_subprocess(monkeypatch, cli_module) -> None:
    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("candy import must dispatch ingest_adapters in-process")

    monkeypatch.setattr(cli_module.subprocess, "run", _boom)


def test_cli_import_dispatches_prealigned_csv(monkeypatch, tmp_path):
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    input_file = tmp_path / "parallel.csv"
    input_file.write_text("id,text,pair_id,pair_role\ns,Quelle,p1,source\nt,Ziel,p1,target\n")
    output_dir = tmp_path / "idx"
    recorder: dict = {}
    _install_stub_ingest_adapters(monkeypatch, recorder)
    _forbid_subprocess(monkeypatch, candy_cli)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "import",
            "--input",
            str(input_file),
            "--output",
            str(output_dir),
            "--input-format",
            "prealigned-csv",
            "--spacy-model",
            "blank:de",
            "--text-column",
            "text",
            "--id-column",
            "id",
            "--pair-key-column",
            "pair_id",
            "--pair-role-column",
            "pair_role",
            "--anchor-role",
            "source",
            "--pair-axis",
            "translation",
            "--pair-order",
            "grouped",
            "--meta-columns",
            "register",
            "year",
        ],
    )

    candy_cli.main()

    argv = recorder["argv"]
    assert argv[0] == "prealigned-csv"
    assert "--pair-axis" in argv
    assert "translation" in argv
    assert "--pair-order" in argv
    assert "grouped" in argv
    assert "--meta-columns" in argv
    assert "register" in argv
    assert "year" in argv


def test_cli_import_dispatches_prealigned_parquet(monkeypatch, tmp_path):
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    input_file = tmp_path / "parallel.parquet"
    input_file.write_bytes(b"placeholder")
    output_dir = tmp_path / "idx"
    recorder: dict = {}
    _install_stub_ingest_adapters(monkeypatch, recorder)
    _forbid_subprocess(monkeypatch, candy_cli)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "import",
            "--input",
            str(input_file),
            "--output",
            str(output_dir),
            "--input-format",
            "prealigned-parquet",
            "--spacy-model",
            "blank:de",
            "--text-column",
            "body",
            "--id-column",
            "doc_id",
            "--pair-key-column",
            "align_id",
            "--pair-role-column",
            "align_role",
            "--anchor-role",
            "original",
            "--pair-axis",
            "revision",
            "--pair-order",
            "grouped",
        ],
    )

    candy_cli.main()

    argv = recorder["argv"]
    assert argv[0] == "prealigned-parquet"
    assert "--text-column" in argv
    assert "body" in argv
    assert "--pair-axis" in argv
    assert "revision" in argv
    assert "--pair-order" in argv
    assert "grouped" in argv
    assert "--delimiter" not in argv


def test_cli_import_dispatches_plaintext_dir_by_default(monkeypatch, tmp_path):
    # A directory input without --input-format resolves to the plaintext adapter.
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    docs = tmp_path / "docs"
    (docs / "news").mkdir(parents=True)
    (docs / "news" / "a.txt").write_text("alpha beta.")
    recorder: dict = {}
    _install_stub_ingest_adapters(monkeypatch, recorder)
    _forbid_subprocess(monkeypatch, candy_cli)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "import",
            "--input",
            str(docs),
            "--output",
            str(tmp_path / "idx"),
            "--spacy-model",
            "blank:de",
            "--pattern",
            "*.txt",
            "--split-paragraphs",
        ],
    )

    candy_cli.main()

    argv = recorder["argv"]
    assert argv[0] == "plaintext"
    assert "--input" in argv and str(docs) in argv
    assert "--pattern" in argv and "*.txt" in argv
    assert "--split-paragraphs" in argv


def test_cli_import_dispatches_csv_and_jsonl_by_extension(monkeypatch, tmp_path):
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    for filename, expected_subcommand in (("k.csv", "csv"), ("k.jsonl", "jsonl")):
        input_file = tmp_path / filename
        input_file.write_text("id,text\n1,Hallo\n" if filename.endswith(".csv") else '{"id":"1","text":"Hallo"}\n')
        recorder: dict = {}
        _install_stub_ingest_adapters(monkeypatch, recorder)
        _forbid_subprocess(monkeypatch, candy_cli)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "candy",
                "import",
                "--input",
                str(input_file),
                "--output",
                str(tmp_path / f"idx_{expected_subcommand}"),
                "--spacy-model",
                "blank:de",
                "--text-column",
                "text",
            ],
        )

        candy_cli.main()

        argv = recorder["argv"]
        assert argv[0] == expected_subcommand
        assert "--text-column" in argv and "text" in argv
        assert "--reject-policy" in argv


def test_cli_import_dispatches_hf_with_dataset_id(monkeypatch, tmp_path):
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    recorder: dict = {}
    _install_stub_ingest_adapters(monkeypatch, recorder)
    _forbid_subprocess(monkeypatch, candy_cli)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "import",
            "--input",
            "org/tiny-ds",
            "--output",
            str(tmp_path / "idx"),
            "--input-format",
            "hf",
            "--spacy-model",
            "blank:de",
            "--hf-config",
            "de",
            "--hf-split",
            "test",
            "--limit",
            "50",
        ],
    )

    candy_cli.main()

    argv = recorder["argv"]
    assert argv[0] == "hf"
    # Die Dataset-ID reist unveraendert durch den generischen --input-Slot.
    assert "--input" in argv and "org/tiny-ds" in argv
    assert "--config" in argv and "de" in argv
    assert "--split" in argv and "test" in argv
    assert "--limit" in argv and "50" in argv
    # Sicherheitsgrenze: trust_remote_code wird niemals durchgereicht.
    assert "--trust-remote-code" not in argv


# ---------------------------------------------------------------------------
# DT-PACKAGED-IMPORT: in-process (wheel-safe) builder dispatch.
# ---------------------------------------------------------------------------


def _install_stub_builder(monkeypatch, recorder: dict, *, rc: int = 0) -> None:
    """Register a fake in-process parquet builder module that records argv.

    Simulates a wheel: the runner finds an importable ``main(argv)`` and never
    walks the filesystem for ``scripts/jobs``. The stub takes the place of the
    real (spaCy-heavy) implementation.
    """

    from candyconc.builders import _runner

    stub = ModuleType("candyconc.builders._stub_parquet_builder")

    def _main(argv):
        recorder["argv"] = list(argv)
        return rc

    stub.main = _main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "candyconc.builders._stub_parquet_builder", stub)
    monkeypatch.setitem(
        _runner._INPROCESS_MODULES,
        "build_fast_index_from_parquet.py",
        ("candyconc.builders._stub_parquet_builder",),
    )


def test_runner_runs_parquet_builder_in_process_without_scripts_tree(monkeypatch):
    # Wheel-safety: run_in_process resolves an importable module and executes it
    # in-process, returning its exit code — no subprocess, no scripts/jobs walk.
    from candyconc.builders import _runner

    recorder: dict = {}
    _install_stub_builder(monkeypatch, recorder, rc=0)

    # Make the subprocess fallback explode so any accidental shell-out fails loud.
    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("subprocess fallback must not run when in-process succeeds")

    monkeypatch.setattr(_runner.subprocess, "run", _boom)

    rc = _runner.run_in_process(
        "build_fast_index_from_parquet.py", ["--input", "x.parquet", "--output", "out"]
    )
    assert rc == 0
    assert recorder["argv"] == ["--input", "x.parquet", "--output", "out"]


def test_runner_returns_none_for_unwired_builder(monkeypatch):
    # A builder without an importable in-process module yields None so the caller
    # falls back to the subprocess path (source-checkout-only builders).
    from candyconc.builders import _runner

    monkeypatch.setattr(_runner, "_INPROCESS_MODULES", {})
    assert _runner.run_in_process("build_fast_index_from_vrt.py", []) is None


def test_cli_import_parquet_runs_in_process_not_subprocess(monkeypatch, tmp_path):
    # End-to-end: ``candy import --input-format parquet`` runs the builder
    # in-process (wheel path) and does NOT shell out.
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    recorder: dict = {}
    _install_stub_builder(monkeypatch, recorder, rc=0)

    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("candy import parquet must not subprocess in the wheel path")

    monkeypatch.setattr(candy_cli.subprocess, "run", _boom)

    input_file = tmp_path / "corpus.parquet"
    input_file.write_bytes(b"placeholder")
    output_dir = tmp_path / "idx"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "import",
            "--input",
            str(input_file),
            "--output",
            str(output_dir),
            "--input-format",
            "parquet",
            "--spacy-model",
            "blank:de",
            "--max-doc-chars",
            "5000",
        ],
    )

    candy_cli.main()

    argv = recorder["argv"]
    assert "--input" in argv and str(input_file) in argv
    assert "--output" in argv and str(output_dir) in argv
    assert "--spacy-model" in argv and "blank:de" in argv
    # No subcommand for the plain parquet builder (only ingest_adapters has one).
    assert argv[0] == "--input"


def test_cli_import_propagates_in_process_nonzero_exit(monkeypatch, tmp_path):
    # A non-zero in-process exit code must surface as SystemExit (parity with the
    # old subprocess-returncode behavior).
    monkeypatch.delenv("CANDYCONC_BUILDER_DIR", raising=False)
    from candyconc.entrypoints import cli as candy_cli

    recorder: dict = {}
    _install_stub_builder(monkeypatch, recorder, rc=3)
    monkeypatch.setattr(candy_cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))

    input_file = tmp_path / "corpus.parquet"
    input_file.write_bytes(b"placeholder")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy", "import",
            "--input", str(input_file),
            "--output", str(tmp_path / "idx"),
            "--input-format", "parquet",
            # blank:de needs no installed pipeline, the test is about the
            # exit code, not about annotation.
            "--spacy-model", "blank:de",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        candy_cli.main()
    assert exc.value.code == 3
