"""Backend corpus import job lifecycle tests.

These tests intentionally target the public API proposed in
``docs/first_class_corpus_import_plan_20260612.md``.  They use tmp_path and
injected fakes so no real builder scripts or corpus data are touched.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest


def _import_jobs_module():
    try:
        return importlib.import_module("candyconc.services.backend.corpus_import_jobs")
    except ModuleNotFoundError:  # pragma: no cover - expected before implementation lands
        pytest.fail(
            "Expected candyconc.services.backend.corpus_import_jobs to provide the "
            "first-class import job API",
            pytrace=False,
        )


def _resolve(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    return value


def _start_import_job(jobs: Any, **kwargs: Any) -> dict[str, Any]:
    start = getattr(jobs, "start_import_job", None)
    if not callable(start):
        pytest.fail("corpus_import_jobs.start_import_job(...) is required", pytrace=False)
    snapshot = _resolve(start(**kwargs))
    assert isinstance(snapshot, dict)
    return snapshot


def _cancel_import_job(jobs: Any, job_id: str) -> dict[str, Any]:
    cancel = getattr(jobs, "cancel_import_job", None)
    if not callable(cancel):
        pytest.fail("corpus_import_jobs.cancel_import_job(job_id) is required", pytrace=False)
    snapshot = _resolve(cancel(job_id))
    assert isinstance(snapshot, dict)
    return snapshot


def _get_reports(jobs: Any, job_id: str) -> dict[str, Any]:
    reports_fn = getattr(jobs, "get_import_reports", None)
    if not callable(reports_fn):
        pytest.fail("corpus_import_jobs.get_import_reports(job_id) is required", pytrace=False)
    reports = _resolve(reports_fn(job_id))
    assert isinstance(reports, dict)
    return reports


def _fixture_source(tmp_path: Path) -> Path:
    source = tmp_path / "input.parquet"
    source.write_bytes(b"synthetic parquet placeholder")
    return source


def _fake_success_builder(*_args: Any, **kwargs: Any) -> dict[str, Any]:
    staging_path = Path(kwargs["staging_path"])
    staging_path.mkdir(parents=True, exist_ok=True)
    (staging_path / "index_manifest.json").write_text(
        json.dumps({"name": kwargs.get("target_name", "demo"), "token_count": 3}),
        encoding="utf-8",
    )
    (staging_path / "build_report.json").write_text(
        json.dumps({"status": "ok", "tokens": 3}),
        encoding="utf-8",
    )
    (staging_path / "reject_report.json").write_text(
        json.dumps({"rejected_rows": 1, "sample": [{"line": 2, "reason": "synthetic"}]}),
        encoding="utf-8",
    )
    report = kwargs.get("report")
    if callable(report):
        report(progress=100, stage="build", message="builder finished")
    return {"returncode": 0}


def _fake_clean_success_builder(*_args: Any, **kwargs: Any) -> dict[str, Any]:
    staging_path = Path(kwargs["staging_path"])
    staging_path.mkdir(parents=True, exist_ok=True)
    (staging_path / "index_manifest.json").write_text(
        json.dumps({"name": kwargs.get("target_name", "demo"), "token_count": 3, "complete": True}),
        encoding="utf-8",
    )
    (staging_path / "build_report.json").write_text(
        json.dumps({"status": "ok", "tokens": 3}),
        encoding="utf-8",
    )
    (staging_path / "reject_report.json").write_text(
        json.dumps({"rejected_rows": 0}),
        encoding="utf-8",
    )
    return {"returncode": 0}


def test_start_import_job_returns_snapshot_urls_and_safe_paths(tmp_path: Path):
    jobs = _import_jobs_module()
    corpora_dir = tmp_path / "corpora"
    source = _fixture_source(tmp_path)

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="Demo Corpus",
        corpora_dir=corpora_dir,
        activate_on_success=False,
        builder_runner=_fake_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    assert snapshot["method"] == "parquet"
    assert snapshot["target_name"] == "Demo Corpus"
    assert snapshot["input_path"] == str(source)
    assert snapshot["status"] in {"queued", "running", "publishing", "done"}
    assert 0 <= int(snapshot["progress"]) <= 100
    assert snapshot["job_id"]
    assert snapshot["urls"]["status"].endswith(f"/api/v1/corpora/imports/{snapshot['job_id']}")
    assert snapshot["urls"]["cancel"].endswith(f"/api/v1/corpora/imports/{snapshot['job_id']}/cancel")
    assert snapshot["urls"]["reports"].endswith(f"/api/v1/corpora/imports/{snapshot['job_id']}/reports")
    assert Path(snapshot["target_path"]).resolve().is_relative_to(corpora_dir.resolve())
    assert Path(snapshot["staging_path"]).resolve().is_relative_to((corpora_dir / ".imports").resolve())


def test_unknown_import_method_is_rejected_before_builder_runs(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)

    def should_not_run(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("builder must not run for an unknown method")

    with pytest.raises((ValueError, RuntimeError)) as excinfo:
        _start_import_job(
            jobs,
            method="totally_unknown",
            input_path=source,
            target_name="demo",
            corpora_dir=tmp_path / "corpora",
            builder_runner=should_not_run,
            register_success=lambda *_args, **_kwargs: None,
            run_inline=True,
        )

    assert "method" in str(excinfo.value).lower() or "methode" in str(excinfo.value).lower()


@pytest.mark.parametrize(
    "target_name",
    ["../escape", "nested/escape", "/tmp/escape", "..\\escape", "x" * 500],
)
def test_unsafe_target_names_are_rejected_before_builder_runs(tmp_path: Path, target_name: str):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)

    def should_not_run(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("builder must not run for an unsafe target name")

    with pytest.raises((ValueError, RuntimeError)) as excinfo:
        _start_import_job(
            jobs,
            method="parquet",
            input_path=source,
            target_name=target_name,
            corpora_dir=tmp_path / "corpora",
            builder_runner=should_not_run,
            register_success=lambda *_args, **_kwargs: None,
            run_inline=True,
        )

    msg = str(excinfo.value).lower()
    assert "target" in msg or "name" in msg or "path" in msg or "pfad" in msg


def test_preflight_overlong_target_name_blocks_without_oserror(tmp_path: Path):
    """CORPUS-LIFECYCLE-01 (import sibling): a >255-byte target_name must produce
    a clean blocking 'kein sicherer Korpusname' check, not an unguarded
    OSError(ENAMETOOLONG) from the later ``target_path.exists()`` probe.
    """
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    managed = tmp_path / "corpora"
    managed.mkdir()

    result = jobs.preflight_import_job(
        "parquet",
        str(source),
        {"target_name": "x" * 500, "__managed_corpus_dir": str(managed)},
    )

    assert result.get("blocking") is True
    target_checks = [
        check
        for check in result.get("checks", [])
        if "target" in str(check.get("key", "")).lower()
    ]
    assert target_checks, result.get("checks")
    assert any(check.get("status") == "fail" for check in target_checks)
    assert any(
        "sicherer korpusname" in str(check.get("message", "")).lower()
        for check in target_checks
    ), target_checks


def _write_parquet(path: Path, columns: list[str]) -> Path:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    table = pa.table({col: pa.array(["hallo welt", "zweite zeile"]) for col in columns})
    pq.write_table(table, path)
    return path


@pytest.mark.parametrize(
    ("columns", "options", "expect_blocking"),
    [
        # First-class Parquet is now a generic, ungepaarter Import: input_text is
        # the default text column and is sufficient for a runnable build.
        (["input_text"], {}, False),
        # Legacy/extra columns are harmless metadata candidates, not the text
        # contract for the generic importer.
        (["input_text", "target_text"], {}, False),
        # text-only remains invalid until the user explicitly maps text_column.
        (["text"], {}, True),
        (["text"], {"text_column": "text"}, False),
    ],
)
def test_parquet_preflight_target_text_matches_builder_contract(
    tmp_path: Path, columns: list[str], options: dict[str, Any], expect_blocking: bool
):
    """CORPUS-LIFECYCLE-01: preflight and builder must agree on the generic
    Parquet text-column contract. A PASS means the configured text column exists.
    """
    jobs = _import_jobs_module()
    source = _write_parquet(tmp_path / "input.parquet", columns)

    result = jobs.preflight_import_method("parquet", str(source), options)
    expected_column = options.get("text_column", "input_text")

    target_checks = [
        check
        for check in result["checks"]
        if str(check.get("key", "")) == f"column:{expected_column}"
    ]
    assert target_checks, result["checks"]
    failed = any(check.get("status") == "fail" for check in target_checks)
    assert failed is expect_blocking, target_checks
    if expect_blocking:
        assert result["blocking"] is True


def _write_prealigned_parquet(
    path: Path, *, pair_roles: list[str]
) -> Path:
    """One closed 2-row pair (pair_id='p1') whose roles are ``pair_roles``."""
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    table = pa.table(
        {
            "text": pa.array(["anker text", "ziel text"]),
            "pair_id": pa.array(["p1", "p1"]),
            "pair_role": pa.array(pair_roles),
        }
    )
    pq.write_table(table, path)
    return path


@pytest.mark.parametrize(
    ("anchor_role", "expect_block"),
    [
        # Configured anchor_role 'source' never appears in the data -> the builder
        # rejects every group (invalid_anchor_count) and emits no document
        # (RuntimeError, returncode 1). Preflight must BLOCK, not warn-then-crash.
        ("source", True),
        # anchor_role 'human' is present in the data -> a runnable build, so the
        # anchor-role gate must NOT block (a green preflight implies a runnable build).
        ("human", False),
    ],
)
def test_prealigned_preflight_blocks_absent_anchor_role(
    tmp_path: Path, anchor_role: str, expect_block: bool
):
    """CORPUS-LIFECYCLE (P2 honesty): a configured-but-absent anchor_role is a
    deterministic build crash (build_fast_index_from_parquet rejects every pair as
    invalid_anchor_count -> no documents -> returncode 1). The preflight must promote
    this from a non-blocking warning to a BLOCKING failure so a green preflight
    guarantees a runnable build; an anchor_role that IS present still passes.
    """
    jobs = _import_jobs_module()
    source = _write_prealigned_parquet(
        tmp_path / "pairs.parquet", pair_roles=["human", "simple"]
    )

    result = jobs.preflight_import_job(
        "prealigned_parquet", str(source), {"anchor_role": anchor_role}
    )

    anchor_checks = [
        check
        for check in result["checks"]
        if str(check.get("key", "")) == "prealigned_anchor_role"
    ]
    if expect_block:
        assert anchor_checks, result["checks"]
        assert anchor_checks[0]["status"] == "fail", anchor_checks
        assert result["blocking"] is True
        assert any("Ankerrolle" in msg for msg in result["errors"]), result["errors"]
    else:
        assert not anchor_checks, anchor_checks


def _advertised_spacy_model(jobs: Any, method: str) -> str:
    descriptor = jobs._descriptor_for_method(method)
    assert descriptor is not None
    spec = next(
        s for s in descriptor["option_specs"] if s.get("key") == "spacy_model"
    )
    return str(spec["default"])


@pytest.mark.parametrize(
    "method",
    [
        "parquet",
        "vrt",
        "prealigned_parquet",
        "prealigned_csv",
        "prealigned_jsonl",
        "plaintext",
        "csv",
        "jsonl",
        "hf",
    ],
)
def test_default_path_build_argv_carries_advertised_spacy_model(method: str):
    """CL-01 preflight==build: the spaCy model the preflight advertises/validates
    as the default (de_core_news_md) MUST be the model the builder is actually
    invoked with. Without an explicit --spacy-model on the argv, prealigned
    builders silently fall back to de_core_news_sm, so a green default-path
    preflight assumes a model the build never uses. iter_method_options is the
    single seam both the in-process command and build_import_command consume."""
    jobs = _import_jobs_module()
    advertised = _advertised_spacy_model(jobs, method)

    options = jobs.iter_method_options(method, {})
    flat = [token for option in options for token in option]

    assert "--spacy-model" in flat, flat
    assert flat[flat.index("--spacy-model") + 1] == advertised

    job = jobs.ImportJob(
        job_id="cl01",
        method=method,
        input="/tmp/in.parquet",
        target="/tmp/out",
        payload={},
    )
    command = jobs.build_import_command(
        job,
        script_start=jobs.__file__,
    )
    assert "--spacy-model" in command, command
    assert command[command.index("--spacy-model") + 1] == advertised


def test_explicit_spacy_model_overrides_advertised_default():
    """An explicit payload model still wins over the advertised default so the
    wiring does not pin every import to de_core_news_md."""
    jobs = _import_jobs_module()
    options = jobs.iter_method_options("parquet", {"spacy_model": "de_dep_news_trf"})
    flat = [token for option in options for token in option]
    assert flat.count("--spacy-model") == 1
    assert flat[flat.index("--spacy-model") + 1] == "de_dep_news_trf"


def test_prealigned_method_contract_is_first_class_but_not_auto_alignment():
    """P1-11: the UI may import already paired rows, not build embed/hybrid
    alignment silently behind the same button."""
    jobs = _import_jobs_module()
    descriptor = jobs._descriptor_for_method("prealigned_csv")

    assert descriptor is not None
    assert descriptor["ui_workflow"]["status"] == "first_class"
    contract_text = " ".join(
        [
            descriptor["ui_workflow"]["reason"],
            *descriptor["output"]["limitations"],
        ]
    )
    assert "bereits gepaarte Zeilen" in contract_text
    assert "Sentence-Embedding" in contract_text
    assert "hybrid" in contract_text
    assert "Expert/API/CLI" in contract_text


def test_generic_parquet_import_command_uses_text_column_contract():
    jobs = _import_jobs_module()
    job = jobs.ImportJob(
        job_id="generic-parquet",
        method="parquet",
        input="/tmp/in.parquet",
        target="/tmp/out",
        payload={"text_column": "body", "id_column": "docid", "meta_columns": ["register", "year"]},
    )

    command = jobs.build_import_command(job, script_start=jobs.__file__)

    assert "--generic" in command
    assert "--text-column" in command
    assert command[command.index("--text-column") + 1] == "body"
    assert "--id-column" in command
    assert command[command.index("--id-column") + 1] == "docid"
    assert command[command.index("--meta-columns") + 1 : command.index("--meta-columns") + 3] == [
        "register",
        "year",
    ]
    assert "--allow-missing-input-text" not in command


def test_success_registration_hook_can_be_monkeypatched(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    registrations: list[dict[str, Any]] = []

    def fake_register(path: str | Path, *, target_name: str, activate: bool) -> dict[str, Any]:
        registrations.append(
            {"path": Path(path), "target_name": target_name, "activate": activate}
        )
        return {"name": target_name, "active": activate}

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="registered-demo",
        corpora_dir=tmp_path / "corpora",
        activate_on_success=True,
        builder_runner=_fake_clean_success_builder,
        register_success=fake_register,
        run_inline=True,
    )

    assert snapshot["status"] == "done"
    assert snapshot["readiness"] == "complete"
    assert snapshot["partial_input"] is False
    assert registrations == [
        {
            "path": Path(snapshot["target_path"]),
            "target_name": "registered-demo",
            "activate": True,
        }
    ]


def _fake_failing_builder(*_args: Any, **kwargs: Any) -> dict[str, Any]:
    staging_path = Path(kwargs["staging_path"])
    staging_path.mkdir(parents=True, exist_ok=True)
    (staging_path / "partial.bin").write_bytes(b"half-built scratch")
    return {"returncode": 7}


def test_successful_publish_leaves_no_staging_scratch_dir(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    corpora_dir = tmp_path / "corpora"

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="gc-demo",
        corpora_dir=corpora_dir,
        activate_on_success=True,
        builder_runner=_fake_clean_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    assert snapshot["status"] == "done"
    assert Path(snapshot["target_path"]).exists()
    scratch = Path(snapshot["staging_path"]).parent
    assert scratch.name == snapshot["job_id"]
    assert not scratch.exists()
    # Only the per-job scratch is removed; the shared staging root may remain.
    imports_root = corpora_dir / ".imports"
    if imports_root.exists():
        assert list(imports_root.iterdir()) == []


def test_failed_import_cleans_up_staging_scratch_dir(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="gc-fail",
        corpora_dir=tmp_path / "corpora",
        activate_on_success=True,
        builder_runner=_fake_failing_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    assert snapshot["status"] in {"failed", "error"}
    assert not Path(snapshot["target_path"]).exists()
    assert not Path(snapshot["staging_path"]).parent.exists()


def test_import_reports_are_loaded_from_generated_artifacts(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="reported-demo",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    reports = _get_reports(jobs, snapshot["job_id"])

    assert reports["schema_version"] == "corpus-import-reports-v1"
    assert reports["job_id"] == snapshot["job_id"]
    assert reports["reports"]["build_report"]["status"] == "ok"
    assert reports["reports"]["reject_report"]["rejected_rows"] == 1
    assert reports["reports"]["manifest"]["token_count"] == 3
    # Compatibility for older clients during the envelope migration.
    assert reports["build_report"]["status"] == "ok"
    assert reports["build_report"]["tokens"] == 3
    assert reports["reject_report"]["rejected_rows"] == 1
    assert reports["manifest"]["token_count"] == 3
    assert reports["outcome"]["partial_input"] is True
    assert reports["outcome"]["rejected_rows"] == 1


def test_partial_import_is_visible_and_skips_auto_activation(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    registrations: list[dict[str, Any]] = []

    def fake_register(path: str | Path, *, target_name: str, activate: bool) -> dict[str, Any]:
        registrations.append(
            {"path": Path(path), "target_name": target_name, "activate": activate}
        )
        return {"name": target_name, "active": activate}

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="partial-demo",
        corpora_dir=tmp_path / "corpora",
        activate_on_success=True,
        builder_runner=_fake_success_builder,
        register_success=fake_register,
        run_inline=True,
    )

    assert snapshot["status"] == "done"
    assert snapshot["stage"] == "done_with_warnings"
    assert snapshot["readiness"] == "partial_input"
    assert snapshot["partial_input"] is True
    assert snapshot["rejected_rows"] == 1
    assert snapshot["warning_count"] >= 1
    assert "nicht übernommen" in " ".join(snapshot["import_warnings"])
    assert snapshot["activation_skipped_reason"] == "partial_input"
    assert registrations == [
        {
            "path": Path(snapshot["target_path"]),
            "target_name": "partial-demo",
            "activate": False,
        }
    ]
    persisted_outcome = json.loads(
        (Path(snapshot["target_path"]) / "import_outcome.json").read_text(encoding="utf-8")
    )
    assert persisted_outcome["schema_version"] == "candyconc-import-outcome-v1"
    assert persisted_outcome["partial_input"] is True
    assert persisted_outcome["rejected_rows"] == 1


def test_cancel_import_job_is_idempotent_for_terminal_jobs(tmp_path: Path):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="cancel-idempotent-demo",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    first = _cancel_import_job(jobs, snapshot["job_id"])
    second = _cancel_import_job(jobs, snapshot["job_id"])

    assert first["job_id"] == snapshot["job_id"]
    assert second["job_id"] == snapshot["job_id"]
    assert second["status"] == first["status"]
    assert second.get("error") == first.get("error")


def test_cancelling_before_finalisation_never_publishes_or_leaves_staging(tmp_path: Path):
    """A user-visible cancellation must win before a corpus becomes selectable."""
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    builder_started = threading.Event()
    allow_builder_to_finish = threading.Event()
    registrations: list[dict[str, Any]] = []

    def slow_builder(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        staging_path = Path(kwargs["staging_path"])
        staging_path.mkdir(parents=True, exist_ok=True)
        builder_started.set()
        assert allow_builder_to_finish.wait(timeout=2)
        (staging_path / "index_manifest.json").write_text(
            json.dumps({"name": kwargs["target_name"], "token_count": 3}),
            encoding="utf-8",
        )
        return {"returncode": 0}

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="cancel-before-publish",
        corpora_dir=tmp_path / "corpora",
        builder_runner=slow_builder,
        register_success=lambda path, *, target_name, activate: registrations.append(
            {"path": Path(path), "target_name": target_name, "activate": activate}
        ),
        run_inline=False,
    )
    assert builder_started.wait(timeout=2)

    cancelled = _cancel_import_job(jobs, snapshot["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellable"] is False
    allow_builder_to_finish.set()

    worker = jobs.get(snapshot["job_id"]).worker
    assert worker is not None
    worker.join(timeout=2)
    assert not worker.is_alive()

    final = jobs.get_import_job(snapshot["job_id"])
    assert final["status"] == "cancelled"
    assert registrations == []
    assert not Path(snapshot["target_path"]).exists()
    assert not Path(snapshot["staging_path"]).parent.exists()


def test_late_cancellation_cannot_label_a_publishing_corpus_as_cancelled(tmp_path: Path):
    """Once the final publish boundary begins, the UI must report it honestly."""
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    registration_started = threading.Event()
    allow_registration = threading.Event()
    registrations: list[dict[str, Any]] = []

    def blocking_register(path: str | Path, *, target_name: str, activate: bool) -> dict[str, Any]:
        registrations.append({"path": Path(path), "target_name": target_name, "activate": activate})
        registration_started.set()
        assert allow_registration.wait(timeout=2)
        return {"name": target_name, "active": activate}

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="publish-boundary",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_clean_success_builder,
        register_success=blocking_register,
        run_inline=False,
    )
    assert registration_started.wait(timeout=2)

    during_publish = _cancel_import_job(jobs, snapshot["job_id"])
    assert during_publish["status"] == "running"
    assert during_publish["stage"] == "publishing"
    assert during_publish["cancellable"] is False
    assert during_publish["finalization_started"] is True
    assert Path(snapshot["target_path"]).exists()

    allow_registration.set()
    worker = jobs.get(snapshot["job_id"]).worker
    assert worker is not None
    worker.join(timeout=2)
    assert not worker.is_alive()

    final = jobs.get_import_job(snapshot["job_id"])
    assert final["status"] == "done"
    assert final["cancellable"] is False
    assert registrations == [
        {"path": Path(snapshot["target_path"]), "target_name": "publish-boundary", "activate": False}
    ]


def test_vrt_annotation_mode_advertises_adopt_and_keeps_sidecar_default():
    """VRT-Gold-Adopt: the descriptor must advertise the adopt choice honestly
    (raw tagset, no spaCy tagging) while the default stays sidecar so existing
    imports keep their behaviour."""
    jobs = _import_jobs_module()
    descriptor = jobs._descriptor_for_method("vrt")
    assert descriptor is not None

    spec = next(s for s in descriptor["option_specs"] if s["key"] == "annotation_mode")
    assert spec["default"] == "sidecar"
    values = [choice["value"] for choice in spec["choices"]]
    assert values == ["sidecar", "none", "adopt"]

    adopt_choice = next(c for c in spec["choices"] if c["value"] == "adopt")
    description = str(adopt_choice.get("description", ""))
    # Honest contract: raw adoption, no UD mapping, provenance visible.
    assert "roh" in description
    assert "UD" in description
    assert "gold_vrt" in description

    features = descriptor["output"]["emitted_features"]
    assert "optional_lemma_pos_gold_adopt" in features


def test_vrt_annotation_mode_adopt_passes_through_to_builder_argv():
    jobs = _import_jobs_module()

    options = jobs.iter_method_options("vrt", {"annotation_mode": "adopt"})
    flat = [token for option in options for token in option]
    assert flat[flat.index("--annotation-mode") + 1] == "adopt"

    # Default path unchanged: no payload key still means sidecar.
    default_options = jobs.iter_method_options("vrt", {})
    default_flat = [token for option in default_options for token in option]
    assert default_flat[default_flat.index("--annotation-mode") + 1] == "sidecar"


# --------------------------------------------------------------------------- #
# S4 Ingestion-Adoption: end-to-end REST job path for the new unpaired
# adapters (real subprocess builder, blank:de for speed), hf dataset-id
# semantics, and the word-FAISS post-step.
# --------------------------------------------------------------------------- #
def _wait_terminal(jobs: Any, job_id: str, *, timeout: float = 240.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = jobs.get_import_job(job_id)
        if snapshot["status"] in {"done", "error", "cancelled"}:
            return snapshot
        time.sleep(0.5)
    pytest.fail(f"import job {job_id} did not finish within {timeout}s: {jobs.get_import_job(job_id)}")


def _assert_published_ready(target_path: Path, *, import_mode: str) -> None:
    from candyconc.core.index_format import IndexManifest, MANIFEST_FILENAME
    from candyconc.services.backend.corpus_registry_service import inspect_corpus_status

    manifest = IndexManifest.from_json(target_path / MANIFEST_FILENAME)
    assert manifest.complete is True
    assert manifest.import_mode == import_mode
    status = inspect_corpus_status(target_path)
    assert status.status == "ready", status


_E2E_OPTIONS = {"spacy_model": "blank:de", "batch_size": 2, "n_process": 1}


def test_plaintext_import_job_end_to_end_real_builder(tmp_path: Path):
    jobs = _import_jobs_module()
    docs = tmp_path / "docs"
    (docs / "news").mkdir(parents=True)
    (docs / "news" / "a.txt").write_text("alpha beta.", encoding="utf-8")
    (docs / "news" / "b.txt").write_text("alpha gamma.", encoding="utf-8")

    snapshot = _start_import_job(
        jobs,
        method="plaintext",
        input_path=docs,
        target_name="e2e-plaintext",
        corpora_dir=tmp_path / "corpora",
        register_success=lambda *_args, **_kwargs: None,
        options=dict(_E2E_OPTIONS),
    )
    final = _wait_terminal(jobs, snapshot["job_id"])

    assert final["status"] == "done", final
    assert final["readiness"] == "complete"
    _assert_published_ready(Path(final["target_path"]), import_mode="plaintext")


def test_csv_import_job_end_to_end_real_builder(tmp_path: Path):
    jobs = _import_jobs_module()
    source = tmp_path / "korpus.csv"
    source.write_text("id,text,register\n1,alpha beta.,news\n2,alpha gamma.,blog\n", encoding="utf-8")

    snapshot = _start_import_job(
        jobs,
        method="csv",
        input_path=source,
        target_name="e2e-csv",
        corpora_dir=tmp_path / "corpora",
        register_success=lambda *_args, **_kwargs: None,
        options={**_E2E_OPTIONS, "text_column": "text", "id_column": "id", "meta_columns": ["register"]},
    )
    final = _wait_terminal(jobs, snapshot["job_id"])

    assert final["status"] == "done", final
    assert final["readiness"] == "complete"
    _assert_published_ready(Path(final["target_path"]), import_mode="csv")


def test_jsonl_import_job_end_to_end_real_builder(tmp_path: Path):
    jobs = _import_jobs_module()
    source = tmp_path / "korpus.jsonl"
    source.write_text(
        json.dumps({"id": "1", "body": "alpha beta.", "meta": {"reg": "news"}})
        + "\n"
        + json.dumps({"id": "2", "body": "alpha gamma.", "meta": {"reg": "blog"}})
        + "\n",
        encoding="utf-8",
    )

    snapshot = _start_import_job(
        jobs,
        method="jsonl",
        input_path=source,
        target_name="e2e-jsonl",
        corpora_dir=tmp_path / "corpora",
        register_success=lambda *_args, **_kwargs: None,
        options={**_E2E_OPTIONS, "text_column": "body", "id_column": "id", "meta_columns": ["meta.reg"]},
    )
    final = _wait_terminal(jobs, snapshot["job_id"])

    assert final["status"] == "done", final
    assert final["readiness"] == "complete"
    _assert_published_ready(Path(final["target_path"]), import_mode="jsonl")


def test_hf_import_job_keeps_dataset_id_verbatim(tmp_path: Path):
    """The hf input is a dataset id, not a server path: it must reach the
    builder unresolved (never absolutised) and must not trip the input-exists
    guard. The network boundary is mocked via builder_runner."""
    jobs = _import_jobs_module()
    seen: dict[str, Any] = {}

    def fake_hf_builder(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        seen["input_path"] = str(kwargs["input_path"])
        seen["payload_input"] = str(kwargs["payload"]["input"])
        staging_path = Path(kwargs["staging_path"])
        staging_path.mkdir(parents=True, exist_ok=True)
        (staging_path / "index_manifest.json").write_text(
            json.dumps({"name": kwargs["target_name"], "token_count": 3, "complete": True}),
            encoding="utf-8",
        )
        (staging_path / "build_report.json").write_text('{"status": "ok"}', encoding="utf-8")
        return {"returncode": 0}

    snapshot = _start_import_job(
        jobs,
        method="hf",
        input_path="org/tiny-ds",
        target_name="e2e-hf",
        corpora_dir=tmp_path / "corpora",
        builder_runner=fake_hf_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    assert snapshot["status"] == "done", snapshot
    assert snapshot["input_path"] == "org/tiny-ds"
    assert seen["input_path"] == "org/tiny-ds"
    assert seen["payload_input"] == "org/tiny-ds"


def test_hf_build_command_uses_dataset_id_and_never_trust_remote_code():
    jobs = _import_jobs_module()
    job = jobs.ImportJob(
        job_id="hf-cmd",
        method="hf",
        input="org/tiny-ds",
        target="/tmp/out",
        payload={"split": "test", "limit": 25, "config": "de"},
    )

    command = jobs.build_import_command(job, script_start=jobs.__file__)

    assert "hf" in command
    assert command[command.index("--input") + 1] == "org/tiny-ds"
    assert command[command.index("--split") + 1] == "test"
    assert command[command.index("--limit") + 1] == "25"
    assert command[command.index("--config") + 1] == "de"
    # Sicherheitsgrenze: trust_remote_code bleibt hart deaktiviert.
    assert "--trust-remote-code" not in command


def _fake_word_faiss_builder(calls: list[dict[str, Any]]):
    def _build(index_path: Path, *, spacy_model: str | None = None) -> dict[str, Any]:
        calls.append({"index_path": Path(index_path), "spacy_model": spacy_model})
        (Path(index_path) / "faiss_word.index").write_bytes(b"fake faiss index")
        import numpy as np

        np.save(Path(index_path) / "word_ids.npy", np.asarray([1, 2, 3], dtype=np.uint32))
        return {"vector_count": 3, "dim": 300}

    return _build


def test_word_faiss_post_step_runs_after_publish_and_flips_capability(tmp_path: Path, monkeypatch):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "_load_word_faiss_builder", lambda: _fake_word_faiss_builder(calls))

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="word-faiss-demo",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_clean_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
        options={"build_word_faiss": True, "spacy_model": "de_core_news_md"},
    )

    assert snapshot["status"] == "done", snapshot
    target = Path(snapshot["target_path"])
    # Nachschritt lief NACH dem Publish auf dem Zielkorpus.
    assert calls == [{"index_path": target, "spacy_model": "de_core_news_md"}]
    assert (target / "faiss_word.index").exists()
    assert (target / "word_ids.npy").exists()
    # Capability-Overlay: semantic.word_similarity wird ehrlich wahr.
    from candyconc.domain.corpus import corpus_summary

    features = corpus_summary(target)["features"]
    assert features["semantic"]["word_similarity"] is True


def test_word_faiss_post_step_default_off_and_capability_stays_false(tmp_path: Path, monkeypatch):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "_load_word_faiss_builder", lambda: _fake_word_faiss_builder(calls))

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="word-faiss-off",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_clean_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
    )

    assert snapshot["status"] == "done", snapshot
    assert calls == []
    target = Path(snapshot["target_path"])
    assert not (target / "faiss_word.index").exists()
    from candyconc.domain.corpus import corpus_summary

    features = corpus_summary(target)["features"]
    assert features["semantic"]["word_similarity"] is False


def test_word_faiss_post_step_failure_is_warning_not_job_failure(tmp_path: Path, monkeypatch):
    jobs = _import_jobs_module()
    source = _fixture_source(tmp_path)

    def _failing_builder():
        def _build(index_path: Path, *, spacy_model: str | None = None) -> dict[str, Any]:
            raise RuntimeError("spaCy Embeddings nicht verfuegbar.")

        return _build

    monkeypatch.setattr(jobs, "_load_word_faiss_builder", _failing_builder)

    snapshot = _start_import_job(
        jobs,
        method="parquet",
        input_path=source,
        target_name="word-faiss-fail",
        corpora_dir=tmp_path / "corpora",
        builder_runner=_fake_clean_success_builder,
        register_success=lambda *_args, **_kwargs: None,
        run_inline=True,
        options={"build_word_faiss": True},
    )

    assert snapshot["status"] == "done", snapshot
    warnings = " ".join(snapshot["import_warnings"])
    assert "Word-FAISS" in warnings
    assert "word_similarity" in warnings
    target = Path(snapshot["target_path"])
    assert target.exists()
    assert not (target / "faiss_word.index").exists()
