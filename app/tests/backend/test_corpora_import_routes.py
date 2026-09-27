"""Corpus import API route tests using a fake import job service."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _default_pipeline_installed(monkeypatch):
    """These tests cover column mapping, pairing and disk checks of the
    preflight. The spaCy pipeline check has its own tests
    (tests/services/test_import_pipeline_preflight.py), so the default pipeline
    counts as installed here, also on machines without de_core_news_md."""
    from candyconc.ingest import pipelines

    monkeypatch.setattr(pipelines, "pipeline_installed", lambda _name: True)


def _client():
    from fastapi.testclient import TestClient
    from candyconc.services.backend.server import app

    return TestClient(app)


def _fake_import_jobs(monkeypatch, tmp_path: Path) -> types.SimpleNamespace:
    state: dict[str, Any] = {"cancel_calls": 0, "payloads": []}
    source = tmp_path / "source.parquet"
    target = tmp_path / "corpora" / "route-demo"
    staging = tmp_path / "corpora" / ".imports" / "job-route-1" / "route-demo"
    source.write_bytes(b"synthetic parquet placeholder")

    def _snapshot(status: str = "queued") -> dict[str, Any]:
        return {
            "job_id": "job-route-1",
            "status": status,
            "progress": 0 if status == "queued" else 100,
            "stage": status,
            "message": status,
            "method": "parquet",
            "input_path": str(source),
            "target_name": "route-demo",
            "target_path": str(target),
            "staging_path": str(staging),
            "activate_on_success": False,
            "pid": None,
            "returncode": None,
            "error": None,
            "reports": {},
            "urls": {
                "status": "/api/v1/corpora/imports/job-route-1",
                "cancel": "/api/v1/corpora/imports/job-route-1/cancel",
                "reports": "/api/v1/corpora/imports/job-route-1/reports",
            },
        }

    def start_import_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
        state["payloads"].append({"args": args, "kwargs": kwargs})
        return _snapshot("queued")

    def get_import_job(job_id: str) -> dict[str, Any]:
        assert job_id == "job-route-1"
        return _snapshot("done")

    def list_import_jobs() -> list[dict[str, Any]]:
        return [_snapshot("running")]

    def cancel_import_job(job_id: str) -> dict[str, Any]:
        assert job_id == "job-route-1"
        state["cancel_calls"] += 1
        return _snapshot("cancelled")

    def get_import_reports(job_id: str) -> dict[str, Any]:
        assert job_id == "job-route-1"
        reports = {
            "build_report": {"status": "ok", "tokens": 3},
            "reject_report": {"rejected_rows": 0},
            "manifest": {"name": "route-demo"},
        }
        return {
            "schema_version": "corpus-import-reports-v1",
            "job_id": job_id,
            "reports": reports,
            **reports,
        }

    def preflight_import_job(method: str, input_path: str, options: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "corpus-import-preflight-v1",
            "method": method,
            "input_path": input_path,
            "status": "pass",
            "ok": True,
            "blocking": False,
            "max_severity": "info",
            "summary": "Preflight erfolgreich.",
            "errors": [],
            "warnings": [],
            "checks": [
                {
                    "key": "method_supported",
                    "label": "Importmethode",
                    "status": "pass",
                    "severity": "info",
                    "blocking": False,
                    "message": "ok",
                    "evidence": {"method": method},
                }
            ],
            "evidence": {"path": input_path, "exists": True, "columns": ["input_text"]},
            "normalized_payload": {"method": method, "input_path": input_path, "options": options},
        }

    def _method_descriptor(method: str, label: str, key: str) -> dict[str, Any]:
        return {
            "schema_version": "corpus-import-method-v1",
            "method": method,
            "label": label,
            "description": label,
            "input": {
                "kind": "server_file",
                "extensions": [".parquet" if "parquet" in method else ".vrt"],
                "accepts_directories": False,
                "path_hint": f"/imports/{method}",
            },
            "option_keys": [key],
            "option_specs": [
                {
                    "key": key,
                    "label": key,
                    "type": "string",
                    "required": method.startswith("prealigned"),
                    "description": f"{key} option",
                }
            ],
            "expected_columns": [
                {"key": key, "label": key, "required": method.startswith("prealigned")}
            ],
            "output": {
                "paired": method.startswith("prealigned"),
                "pairing_kind": "external_pair_keys" if method.startswith("prealigned") else "none",
                "emitted_features": ["kwic_ready"],
                "guarantees": ["synthetic route fixture"],
                "limitations": [],
            },
            "emitted_features": ["kwic_ready"],
            "reports": [{"key": "build_report", "label": "Build-Report"}],
        }

    fake = types.SimpleNamespace(
        state=state,
        supported_import_methods=lambda: ("parquet", "vrt", "prealigned_parquet"),
        import_method_descriptors=lambda: [
            _method_descriptor("parquet", "Parquet", "spacy_model"),
            _method_descriptor("vrt", "VRT", "text_tag"),
            _method_descriptor("prealigned_parquet", "Pre-grouped Parquet", "pair_key_column"),
        ],
        start_import_job=start_import_job,
        create_import_job=start_import_job,
        get_import_job=get_import_job,
        list_import_jobs=list_import_jobs,
        preflight_import_job=preflight_import_job,
        snapshot=get_import_job,
        cancel_import_job=cancel_import_job,
        cancel=cancel_import_job,
        get_import_reports=get_import_reports,
        reports=get_import_reports,
    )
    monkeypatch.setitem(sys.modules, "candyconc.services.backend.corpus_import_jobs", fake)
    from candyconc.services.backend.routes import corpora as corpora_routes

    monkeypatch.setattr(corpora_routes, "corpus_import_jobs", fake, raising=False)
    monkeypatch.setattr(corpora_routes, "import_jobs", fake, raising=False)
    return fake


def test_create_import_route_returns_job_snapshot_and_urls(monkeypatch, tmp_path: Path):
    fake = _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.post(
        "/api/v1/corpora/imports",
        json={
            "method": "parquet",
            "input_path": str(tmp_path / "source.parquet"),
            "target_name": "route-demo",
            "activate_on_success": False,
        },
    )

    assert response.status_code in {200, 202}, response.text
    body = response.json()
    assert body["job_id"] == "job-route-1"
    assert body["method"] == "parquet"
    assert body["urls"]["status"].endswith("/api/v1/corpora/imports/job-route-1")
    assert body["urls"]["cancel"].endswith("/api/v1/corpora/imports/job-route-1/cancel")
    assert body["urls"]["reports"].endswith("/api/v1/corpora/imports/job-route-1/reports")
    assert fake.state["payloads"], "route should delegate to import job service"


def test_create_import_route_rejects_blocking_preflight(monkeypatch, tmp_path: Path):
    fake = _fake_import_jobs(monkeypatch, tmp_path)

    def blocking_preflight(method: str, input_path: str, options: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "corpus-import-preflight-v1",
            "method": method,
            "input_path": input_path,
            "status": "error",
            "ok": False,
            "blocking": True,
            "max_severity": "error",
            "summary": "Preflight blockiert.",
            "errors": ["Dateiendung passt nicht."],
            "warnings": [],
            "checks": [
                {
                    "key": "input_extension",
                    "label": "Dateiendung",
                    "status": "fail",
                    "severity": "error",
                    "blocking": True,
                    "message": "Falsche Endung.",
                    "evidence": {},
                }
            ],
            "evidence": {"path": input_path, "exists": True, "columns": []},
        }

    fake.preflight_import_job = blocking_preflight
    client = _client()

    response = client.post(
        "/api/v1/corpora/imports",
        json={
            "method": "parquet",
            "input_path": str(tmp_path / "source.parquet"),
            "target_name": "route-demo",
        },
    )

    assert response.status_code == 400, response.text
    assert "Preflight" in response.text
    assert fake.state["payloads"] == []


def test_import_methods_route_returns_method_metadata(monkeypatch, tmp_path: Path):
    _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.get("/api/v1/corpora/import-methods")

    assert response.status_code == 200, response.text
    methods = response.json()["methods"]
    assert {item["method"] for item in methods} >= {"parquet", "vrt", "prealigned_parquet"}
    assert methods[0]["description"]
    assert isinstance(methods[0]["option_keys"], list)
    assert methods[0]["schema_version"] == "corpus-import-method-v1"
    assert methods[0]["input"]["kind"] == "server_file"
    assert methods[0]["option_specs"][0]["key"] in methods[0]["option_keys"]
    assert methods[0]["output"]["emitted_features"]
    assert methods[0]["reports"][0]["key"] == "build_report"


def test_import_preflight_route_returns_non_mutating_evidence(monkeypatch, tmp_path: Path):
    fake = _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.post(
        "/api/v1/corpora/import-preflight",
        json={
            "method": "parquet",
            "input_path": str(tmp_path / "source.parquet"),
            "target_name": "route-demo",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "corpus-import-preflight-v1"
    assert body["ok"] is True
    assert body["blocking"] is False
    assert body["evidence"]["columns"] == ["input_text"]
    assert fake.state["payloads"] == [], "preflight must not start an import job"


def test_real_import_method_descriptors_are_typed_and_methodically_bounded():
    from candyconc.services.backend import corpus_import_jobs

    methods = {item["method"]: item for item in corpus_import_jobs.import_method_descriptors()}
    assert {"parquet", "vrt", "prealigned_parquet", "prealigned_csv", "prealigned_jsonl"} <= set(methods)

    parquet = methods["parquet"]
    assert parquet["input"]["extensions"] == [".parquet"]
    parquet_options = {item["key"]: item for item in parquet["option_specs"]}
    assert parquet_options["text_column"]["default"] == "input_text"
    assert {item["key"] for item in parquet["expected_columns"]} >= {"input_text", "id"}
    assert parquet["output"]["paired"] is False
    assert parquet["output"]["paired_data_dependent"] is False
    for method in methods.values():
        assert method["option_keys"] == [item["key"] for item in method["option_specs"]]

    prealigned = methods["prealigned_csv"]
    assert prealigned["availability"]["status"] == "available"
    assert prealigned["ui_workflow"]["status"] == "first_class"
    assert "Preflight" in prealigned["ui_workflow"]["reason"]
    specs = {item["key"]: item for item in prealigned["option_specs"]}
    assert specs["pair_key_column"]["required"] is True
    assert specs["reject_policy"]["choices"]
    assert {item["key"] for item in prealigned["expected_columns"]} >= {"text", "pair_id", "pair_role"}
    assert prealigned["output"]["paired"] is True
    assert "inhaltliche" in " ".join(prealigned["output"]["limitations"]).lower()
    assert {item["key"] for item in prealigned["reports"]} >= {"build_report", "reject_report", "manifest"}


def test_descriptor_strings_are_free_of_recommendation_rhetoric():
    """Import-Descriptoren beschreiben neutral, ohne Empfehlungs-/Wertungsvokabular.

    Wortlisten-Wächter über ALLE String-Werte ALLER Methoden-Descriptoren
    (rekursiv über description, limitations, guarantees, Options-Hilfen,
    choices, reports, ui_workflow usw.), damit auch künftige Methoden und
    Felder automatisch erfasst sind.
    """
    from candyconc.services.backend import corpus_import_jobs

    forbidden = (
        "empfohlen",
        "empfehlens",
        "empfiehlt",
        "recommend",
        "am besten",
        "ideal",
    )
    violations: list[str] = []

    def _walk(value, trail: list[str]) -> None:
        if isinstance(value, str):
            lowered = value.lower()
            for word in forbidden:
                if word in lowered:
                    violations.append(f"{'/'.join(trail)}: {value!r} enthält {word!r}")
        elif isinstance(value, dict):
            for key, item in value.items():
                _walk(item, trail + [str(key)])
        elif isinstance(value, (list, tuple)):
            for pos, item in enumerate(value):
                _walk(item, trail + [str(pos)])

    descriptors = corpus_import_jobs.import_method_descriptors()
    assert descriptors
    for descriptor in descriptors:
        _walk(descriptor, [str(descriptor.get("method"))])
    assert violations == []


def test_string_list_import_options_are_cli_safe():
    from candyconc.services.backend import corpus_import_jobs

    options = corpus_import_jobs.iter_method_options(
        "vrt",
        {
            "meta_index_fields": ["date", "genre"],
            "token_columns": ["word", "lemma", "pos"],
            "id_attrs": ["id", "xml:id"],
            "source_attrs": ["source", "corpus"],
        },
    )

    option_map = {item[0]: item[1:] for item in options if len(item) > 1}
    assert option_map["--meta-index-fields"] == ["date,genre"]
    assert option_map["--token-columns"] == ["word,lemma,pos"]
    assert option_map["--id-attrs"] == ["id,xml:id"]
    assert option_map["--source-attrs"] == ["source,corpus"]
    assert "['date', 'genre']" not in str(options)


def test_real_parquet_preflight_explains_text_column_fallback(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "text_only.parquet"
    pq.write_table(pa.Table.from_pylist([{"id": "d1", "text": "Hallo Welt."}]), source)

    blocked = corpus_import_jobs.preflight_import_job(
        "parquet",
        str(source),
        {"method": "parquet", "input_path": str(source)},
    )

    assert blocked["ok"] is False
    input_check = next(check for check in blocked["checks"] if check["key"] == "column:input_text")
    assert input_check["status"] == "fail"
    assert "text_column" in input_check["message"]
    assert input_check["evidence"]["candidate_columns"] == ["text"]
    assert blocked["evidence"]["column_mapping_suggestions"][0]["suggested_options"] == {
        "text_column": "text",
    }

    explicit = corpus_import_jobs.preflight_import_job(
        "parquet",
        str(source),
        {
            "method": "parquet",
            "input_path": str(source),
            "text_column": "text",
        },
    )

    assert explicit["ok"] is True
    text_check = next(check for check in explicit["checks"] if check["key"] == "column:text")
    assert text_check["status"] == "pass"


def test_vrt_inspect_preflight_blocks_mutating_import(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "sample.vrt"
    source.write_text("<text id=\"t1\">\nHallo\tHallo\tINTJ\n</text>\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "vrt",
        str(source),
        {"method": "vrt", "input_path": str(source), "inspect": True},
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    inspect_check = next(check for check in result["checks"] if check["key"] == "vrt_inspect_mode")
    assert inspect_check["status"] == "fail"
    with pytest.raises(ValueError, match="Diagnostikmodus"):
        corpus_import_jobs.start_import_job(
            method="vrt",
            input_path=str(source),
            target_name="sample",
            corpora_dir=tmp_path / "corpora",
            options={"inspect": True},
        )


def test_prealigned_jsonl_preflight_does_not_read_overlong_line(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "huge.jsonl"
    source.write_text('{"payload":"' + ("x" * (200 * 1024)) + '"}\n', encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_jsonl",
        str(source),
        {
            "method": "prealigned_jsonl",
            "input_path": str(source),
            "reject_policy": "collect",
        },
    )

    sample = result["evidence"]["column_sample"]
    assert sample["sample_byte_limit"] == 128 * 1024
    assert sample["sample_bytes"] == 128 * 1024
    assert sample["sample_truncated"] is True
    assert result["evidence"]["columns"] == []


def test_real_prealigned_csv_preflight_checks_columns_and_warns_collect_policy(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text("text,pair_id,pair_role\nHallo,p1,source\nHello,p1,target\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {"method": "prealigned_csv", "input_path": str(source)},
    )

    assert result["ok"] is True
    assert result["status"] == "warning"
    assert "text" in result["evidence"]["columns"]
    pair_sample = result["evidence"]["prealigned_pairing_sample"]
    assert pair_sample["sample_bounded"] is True
    assert pair_sample["pair_key_column"] == "pair_id"
    assert pair_sample["pair_role_column"] == "pair_role"
    assert pair_sample["anchor_role"] == "source"
    assert pair_sample["pair_count"] == 1
    assert pair_sample["singleton_pair_count"] == 0
    assert any(check["key"] == "prealigned_pairing_sample" and check["status"] == "pass" for check in result["checks"])
    assert any(check["key"] == "column:pair_id" and check["status"] == "pass" for check in result["checks"])
    assert any(check["key"] == "reject_policy" and check["status"] == "warn" for check in result["checks"])


def test_real_prealigned_parquet_preflight_reads_pair_sample_rows(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.parquet"
    table = pa.Table.from_pylist([
        {"id": "s1", "text": "Hallo", "pair_id": "p1", "pair_role": "source"},
        {"id": "t1", "text": "Hello", "pair_id": "p1", "pair_role": "target"},
    ])
    pq.write_table(table, source)

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_parquet",
        str(source),
        {
            "method": "prealigned_parquet",
            "input_path": str(source),
            "reject_policy": "fail_fast",
            "pair_order": "grouped",
        },
    )

    assert result["ok"] is True
    assert result["blocking"] is False
    pair_sample = result["evidence"]["prealigned_pairing_sample"]
    assert pair_sample["sample_rows"] == 2
    assert pair_sample["pair_count"] == 1
    assert pair_sample["role_counts"] == {"source": 1, "target": 1}
    assert not pair_sample["reader"].get("warning")


def test_real_prealigned_csv_preflight_warns_on_pairing_sample_anomalies(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text(
        "text,pair_id,pair_role\n"
        "Hallo,p1,source\n"
        "Hello,p1,target\n"
        "Bonjour,p2,target\n"
        "Ciao,p3,source\n",
        encoding="utf-8",
    )

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "reject_policy": "collect",
        },
    )

    pair_sample = result["evidence"]["prealigned_pairing_sample"]
    assert result["ok"] is True
    assert result["status"] == "warning"
    assert pair_sample["pair_count"] == 3
    assert pair_sample["singleton_pair_count"] == 2
    assert pair_sample["missing_anchor_pair_count"] == 1
    assert pair_sample["singleton_pairs_preview"] == ["p2", "p3"]
    assert pair_sample["missing_anchor_pairs_preview"] == ["p2"]
    pairing_check = next(check for check in result["checks"] if check["key"] == "prealigned_pairing_sample")
    assert pairing_check["status"] == "warn"
    assert "Singleton" in pairing_check["message"]
    assert "Ankerrolle" in pairing_check["message"]


def test_real_prealigned_csv_preflight_fail_fast_blocks_sample_hard_errors(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text(
        "text,pair_id,pair_role\n"
        ",p1,source\n"
        "Hello,p1,target\n",
        encoding="utf-8",
    )

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "reject_policy": "fail_fast",
        },
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    pairing_check = next(check for check in result["checks"] if check["key"] == "prealigned_pairing_sample")
    assert pairing_check["status"] == "fail"
    assert pairing_check["evidence"]["empty_text_rows"] == 1


def test_real_prealigned_csv_preflight_preserves_pair_key_whitespace(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text(
        "text,pair_id,pair_role\n"
        "Hallo,p1,source\n"
        "Hello,p1 ,target\n",
        encoding="utf-8",
    )

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "reject_policy": "fail_fast",
            "pair_order": "grouped",
        },
    )

    sample = result["evidence"]["prealigned_pairing_sample"]
    assert result["ok"] is False
    assert sample["pair_count"] == 2
    assert sample["singleton_pairs_preview"] == ["p1", "p1 "]


def test_real_prealigned_csv_preflight_fail_fast_blocks_closed_grouped_missing_anchor(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    rows = ["text,pair_id,pair_role", "Hallo,p1,target"]
    rows.extend(["Hello,p2,source", "Salut,p2,target"])
    rows.extend([f"Extra {idx},p2,target" for idx in range(198)])
    source = tmp_path / "paired.csv"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "reject_policy": "fail_fast",
            "pair_order": "grouped",
        },
    )

    sample = result["evidence"]["prealigned_pairing_sample"]
    assert sample["sample_complete"] is False
    assert sample["closed_missing_anchor_pair_count"] == 1
    assert sample["closed_missing_anchor_pairs_preview"] == ["p1"]
    pairing_check = next(check for check in result["checks"] if check["key"] == "prealigned_pairing_sample")
    assert pairing_check["status"] == "fail"
    assert result["blocking"] is True


def test_real_prealigned_jsonl_preflight_supports_nested_dot_path_fields(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.jsonl"
    source.write_text(
        '{"payload":{"text":"Hallo"},"pair":{"id":"p1","role":"source"}}\n'
        '{"payload":{"text":"Hello"},"pair":{"id":"p1","role":"target"}}\n',
        encoding="utf-8",
    )

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_jsonl",
        str(source),
        {
            "method": "prealigned_jsonl",
            "input_path": str(source),
            "text_column": "payload.text",
            "pair_key_column": "pair.id",
            "pair_role_column": "pair.role",
            "reject_policy": "fail_fast",
            "pair_order": "grouped",
        },
    )

    assert result["ok"] is True
    assert result["status"] == "pass"
    assert {"payload.text", "pair.id", "pair.role"} <= set(result["evidence"]["columns"])
    sample = result["evidence"]["prealigned_pairing_sample"]
    assert sample["text_column"] == "payload.text"
    assert sample["pair_key_column"] == "pair.id"
    assert sample["pair_role_column"] == "pair.role"
    assert sample["pair_count"] == 1
    assert sample["singleton_pair_count"] == 0


def test_real_prealigned_csv_preflight_blocks_missing_required_column(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text("text,pair_id\nHallo,p1\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {"method": "prealigned_csv", "input_path": str(source), "reject_policy": "fail_fast"},
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    assert any("pair_role" in error for error in result["errors"])


def test_real_preflight_blocks_wrong_extension(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.txt"
    source.write_text("text,pair_id,pair_role\nHallo,p1,source\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {"method": "prealigned_csv", "input_path": str(source)},
    )

    assert result["ok"] is False
    assert any(check["key"] == "input_extension" and check["status"] == "fail" for check in result["checks"])


def test_real_preflight_blocks_existing_target_before_start(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text("text,pair_id,pair_role\nHallo,p1,source\n", encoding="utf-8")
    managed_root = tmp_path / "corpora"
    (managed_root / "existing-demo").mkdir(parents=True)

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "target_name": "existing-demo",
            "reject_policy": "fail_fast",
            "__managed_corpus_dir": str(managed_root),
        },
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    assert "__managed_corpus_dir" not in result["normalized_payload"]["options"]
    assert any(check["key"] == "target_exists" and check["status"] == "fail" for check in result["checks"])


def test_real_preflight_internal_managed_root_is_not_reported_as_unknown_option(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text("text,pair_id,pair_role\nHallo,p1,source\nHello,p1,target\n", encoding="utf-8")
    managed_root = tmp_path / "corpora"
    managed_root.mkdir()

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "target_name": "fresh-demo",
            "reject_policy": "fail_fast",
            "pair_order": "grouped",
            "__managed_corpus_dir": str(managed_root),
        },
    )

    assert result["ok"] is True
    assert result["status"] == "pass"
    assert "__managed_corpus_dir" not in result["normalized_payload"]["options"]
    assert not any(check["key"] == "unknown_options" for check in result["checks"])


def test_real_preflight_blocks_invalid_option_choice_and_type(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "paired.csv"
    source.write_text("text,pair_id,pair_role\nHallo,p1,source\n", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job(
        "prealigned_csv",
        str(source),
        {
            "method": "prealigned_csv",
            "input_path": str(source),
            "target_name": "typed-demo",
            "reject_policy": "silently_ignore_errors",
            "n_process": "many",
        },
    )

    assert result["ok"] is False
    assert any(check["key"] == "option:reject_policy:choice" and check["status"] == "fail" for check in result["checks"])
    assert any(check["key"] == "option:n_process:type" and check["status"] == "fail" for check in result["checks"])


def test_unknown_import_method_route_is_rejected(monkeypatch, tmp_path: Path):
    _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.post(
        "/api/v1/corpora/imports",
        json={
            "method": "not-a-real-method",
            "input_path": str(tmp_path / "source.parquet"),
            "target_name": "route-demo",
        },
    )

    assert response.status_code == 400, response.text
    assert "method" in response.text.lower() or "methode" in response.text.lower()


def test_list_import_route_returns_retained_job_snapshots(monkeypatch, tmp_path: Path):
    _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.get("/api/v1/corpora/imports")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["jobs"][0]["job_id"] == "job-route-1"
    assert body["jobs"][0]["status"] == "running"


def test_unsafe_target_name_route_is_rejected(monkeypatch, tmp_path: Path):
    _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.post(
        "/api/v1/corpora/imports",
        json={
            "method": "parquet",
            "input_path": str(tmp_path / "source.parquet"),
            "target_name": "../escape",
        },
    )

    assert response.status_code == 400, response.text
    assert "target" in response.text.lower() or "name" in response.text.lower()


def test_cancel_import_route_is_idempotent(monkeypatch, tmp_path: Path):
    fake = _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    first = client.post("/api/v1/corpora/imports/job-route-1/cancel")
    second = client.post("/api/v1/corpora/imports/job-route-1/cancel")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "cancelled"
    assert second.json()["status"] == "cancelled"
    assert fake.state["cancel_calls"] == 2


def test_import_reports_route_returns_loaded_reports(monkeypatch, tmp_path: Path):
    _fake_import_jobs(monkeypatch, tmp_path)
    client = _client()

    response = client.get("/api/v1/corpora/imports/job-route-1/reports")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "corpus-import-reports-v1"
    assert body["job_id"] == "job-route-1"
    assert body["reports"]["build_report"]["status"] == "ok"
    assert body["reports"]["reject_report"]["rejected_rows"] == 0
    assert body["reports"]["manifest"]["name"] == "route-demo"
    # Compatibility for older clients during the envelope migration.
    assert body["build_report"]["status"] == "ok"
    assert body["reject_report"]["rejected_rows"] == 0
    assert body["manifest"]["name"] == "route-demo"


def test_corpus_build_report_route_returns_versioned_envelope(monkeypatch, tmp_path: Path):
    import importlib

    from candyconc.services.backend.routes import corpora as corpora_routes

    corpus_dir = tmp_path / "registered-demo"
    corpus_dir.mkdir()
    (corpus_dir / "build_report.json").write_text('{"status":"ok","tokens":7}', encoding="utf-8")
    (corpus_dir / "index_manifest.json").write_text(
        '{"import_mode":"parquet","token_count":7}',
        encoding="utf-8",
    )

    fake_registry = types.SimpleNamespace(
        inspect=lambda corpus: {"name": corpus, "path": str(corpus_dir)}
    )
    real_import_jobs = importlib.import_module("candyconc.services.backend.corpus_import_jobs")
    monkeypatch.setattr(corpora_routes, "corpus_import_jobs", real_import_jobs)
    monkeypatch.setattr(corpora_routes, "_registry_service", lambda: fake_registry)
    client = _client()

    response = client.get("/api/v1/corpora/registered-demo/build-report")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "corpus-build-report-v1"
    assert body["corpus"] == "registered-demo"
    assert body["path"] == str(corpus_dir.resolve())
    assert body["reports"]["build_report"]["status"] == "ok"
    assert body["reports"]["manifest"]["import_mode"] == "parquet"
    # Compatibility for older clients during the envelope migration.
    assert body["build_report"]["tokens"] == 7
    assert body["manifest"]["token_count"] == 7


# --------------------------------------------------------------------------- #
# S4 Ingestion-Adoption: 9 vollstaendige Methoden-Descriptoren (GATE-Pin),
# Preflights der neuen Adapter und der Disk-Space-Preflight.
# --------------------------------------------------------------------------- #
EXPECTED_IMPORT_METHODS = {
    "parquet",
    "vrt",
    "prealigned_parquet",
    "prealigned_csv",
    "prealigned_jsonl",
    "plaintext",
    "csv",
    "jsonl",
    "hf",
}


def test_import_methods_route_serves_nine_real_descriptors(monkeypatch):
    """GATE (Route-Ebene): GET /corpora/import-methods liefert die 9 echten
    Methoden-Descriptoren ueber die FastAPI-App."""
    import importlib

    from candyconc.services.backend.routes import corpora as corpora_routes

    # Frühere Tests binden das Fake-Modul beim Erst-Import der Route; für den
    # Real-Pin explizit auf das echte Modul zeigen (Muster wie build-report-Test).
    real_import_jobs = importlib.import_module("candyconc.services.backend.corpus_import_jobs")
    monkeypatch.setattr(corpora_routes, "corpus_import_jobs", real_import_jobs)
    client = _client()

    response = client.get("/api/v1/corpora/import-methods")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 9
    assert {item["method"] for item in body["methods"]} == EXPECTED_IMPORT_METHODS
    assert all(item["schema_version"] == "corpus-import-method-v1" for item in body["methods"])


def test_import_methods_pin_nine_complete_descriptors():
    """GATE: GET /corpora/import-methods liefert genau 9 Methoden mit
    vollstaendigen, ehrlichen Descriptoren (corpus-import-method-v1)."""
    from candyconc.services.backend import corpus_import_jobs

    methods = corpus_import_jobs.import_method_descriptors()
    by_name = {item["method"]: item for item in methods}

    assert len(methods) == 9, sorted(by_name)
    assert set(by_name) == EXPECTED_IMPORT_METHODS

    for name, method in by_name.items():
        assert method["schema_version"] == "corpus-import-method-v1", name
        assert method["label"], name
        assert method["description"], name
        assert method["input"].get("kind"), name
        # Availability is honest about this installation: hf needs the
        # optional package datasets (extra "hf"), every other method only core
        # dependencies.
        import importlib.util

        expected = "available"
        if name == "hf" and importlib.util.find_spec("datasets") is None:
            expected = "unavailable"
        assert method["availability"]["status"] == expected, (name, method["availability"])
        assert method["ui_workflow"]["status"] == "first_class", name
        assert method["option_specs"], name
        assert method["option_keys"] == [spec["key"] for spec in method["option_specs"]], name
        assert method["output"]["emitted_features"], name
        assert method["output"]["guarantees"], name
        report_keys = {item["key"] for item in method["reports"]}
        assert {"build_report", "manifest"} <= report_keys, name
        # Der Word-FAISS-Nachschritt ist ueberall verfuegbar und dokumentiert
        # seine Kosten ehrlich im option_spec.
        wf = next(spec for spec in method["option_specs"] if spec["key"] == "build_word_faiss")
        assert wf["default"] is False, name
        assert "Kosten" in wf["description"], name

    plaintext = by_name["plaintext"]
    assert plaintext["input"]["accepts_directories"] is True
    assert "Elternordner" in " ".join(
        str(item) for item in (plaintext["output"]["guarantees"] + [plaintext["description"]])
    )

    csv_method = by_name["csv"]
    csv_specs = {spec["key"]: spec for spec in csv_method["option_specs"]}
    assert csv_specs["text_column"]["required"] is True
    assert "Sniffer" in csv_specs["delimiter"]["description"]

    hf = by_name["hf"]
    assert hf["input"]["kind"] == "hf_dataset"
    hf_limitations = " ".join(hf["output"]["limitations"])
    # Sicherheitsgrenze im Descriptor dokumentiert; kein opt-in Option-Spec.
    assert "trust_remote_code" in hf_limitations
    assert "hart False" in hf_limitations or "deaktiviert" in hf_limitations
    assert "trust_remote_code" not in hf["option_keys"]
    assert "Netzzugriff" in hf_limitations


def test_real_csv_preflight_reads_columns_and_suggests_text_mapping(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "korpus.csv"
    source.write_text("id;content;register\n1;Hallo Welt;news\n", encoding="utf-8")

    blocked = corpus_import_jobs.preflight_import_job("csv", str(source), {})
    assert blocked["ok"] is False
    text_check = next(check for check in blocked["checks"] if check["key"] == "column:text")
    assert text_check["status"] == "fail"
    assert blocked["evidence"]["column_mapping_suggestions"][0]["suggested_options"] == {
        "text_column": "content",
    }
    assert {"id", "content", "register"} <= set(blocked["evidence"]["columns"])

    explicit = corpus_import_jobs.preflight_import_job(
        "csv", str(source), {"text_column": "content", "meta_columns": ["register"]}
    )
    assert explicit["ok"] is True
    assert explicit["status"] == "pass"
    assert any(check["key"] == "column:content" and check["status"] == "pass" for check in explicit["checks"])
    assert any(check["key"] == "disk_space" and check["status"] == "pass" for check in explicit["checks"])


def test_real_jsonl_preflight_reads_nested_fields(tmp_path: Path):
    import json as _json

    from candyconc.services.backend import corpus_import_jobs

    source = tmp_path / "korpus.jsonl"
    source.write_text(
        _json.dumps({"payload": {"text": "Hallo"}, "id": "1"}) + "\n",
        encoding="utf-8",
    )

    result = corpus_import_jobs.preflight_import_job(
        "jsonl", str(source), {"text_column": "payload.text"}
    )

    assert result["ok"] is True
    assert "payload.text" in result["evidence"]["columns"]
    assert any(check["key"] == "column:payload.text" and check["status"] == "pass" for check in result["checks"])


def test_real_plaintext_preflight_reports_files_size_and_encoding(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    docs = tmp_path / "docs"
    (docs / "news").mkdir(parents=True)
    (docs / "news" / "a.txt").write_text("alpha beta.", encoding="utf-8")
    (docs / "news" / "b.txt").write_bytes("Käse Größe schön".encode("latin-1"))

    result = corpus_import_jobs.preflight_import_job("plaintext", str(docs), {})

    assert result["ok"] is True
    sample = result["evidence"]["plaintext"]
    assert sample["file_count"] == 2
    assert sample["total_size_bytes"] > 0
    assert sample["encoding_utf8_files"] == 1
    assert sample["encoding_fallback_files"] == 1
    assert sample["registers_preview"] == ["news"]
    assert any(check["key"] == "plaintext_files" and check["status"] == "pass" for check in result["checks"])
    assert any(check["key"] == "input_kind" and check["status"] == "pass" for check in result["checks"])


def test_real_plaintext_preflight_blocks_when_no_file_matches_pattern(tmp_path: Path):
    from candyconc.services.backend import corpus_import_jobs

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("kein txt", encoding="utf-8")

    result = corpus_import_jobs.preflight_import_job("plaintext", str(docs), {})

    assert result["ok"] is False
    assert result["blocking"] is True
    assert any(check["key"] == "plaintext_files" and check["status"] == "fail" for check in result["checks"])


def test_real_hf_preflight_is_descriptor_only_without_network(tmp_path: Path, monkeypatch):
    from candyconc.services.backend import corpus_import_jobs

    # The hf method needs the optional package datasets (extra "hf"). This test
    # covers the descriptor-only preflight, so the extra counts as installed.
    real = corpus_import_jobs._module_available
    monkeypatch.setattr(corpus_import_jobs, "_module_available", lambda name: name == "datasets" or real(name))
    result = corpus_import_jobs.preflight_import_job("hf", "org/tiny-ds", {"split": "test", "limit": 10})

    assert result["ok"] is True
    # Ehrlich als Offline-Preflight markiert: immer Warnstatus, nie "pass".
    assert result["status"] == "warning"
    assert result["evidence"]["hf"] == {
        "dataset": "org/tiny-ds",
        "network_access": False,
        "descriptor_only": True,
    }
    offline = next(check for check in result["checks"] if check["key"] == "hf_descriptor_only")
    assert offline["status"] == "warn"
    assert "Netzzugriff" in offline["message"]
    # Keine Dateisystem- und keine Disk-Checks fuer eine Dataset-ID.
    check_keys = {check["key"] for check in result["checks"]}
    assert "input_exists" not in check_keys
    assert "disk_space" not in check_keys

    invalid = corpus_import_jobs.preflight_import_job("hf", "../evil", {})
    assert invalid["ok"] is False
    assert any(check["key"] == "hf_dataset_id" and check["status"] == "fail" for check in invalid["checks"])


def test_preflight_disk_space_blocks_on_full_disk(tmp_path: Path, monkeypatch):
    import collections

    from candyconc.services.backend import corpus_import_jobs
    from candyconc.utils import disk_preflight

    source = tmp_path / "korpus.csv"
    source.write_text("id,text\n1,Hallo Welt\n", encoding="utf-8")
    usage = collections.namedtuple("usage", "total used free")

    monkeypatch.setattr(
        disk_preflight.shutil, "disk_usage", lambda _p: usage(total=100, used=90, free=10)
    )
    monkeypatch.delenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", raising=False)

    result = corpus_import_jobs.preflight_import_job(
        "csv",
        str(source),
        {"text_column": "text", "__managed_corpus_dir": str(tmp_path / "corpora")},
    )

    assert result["ok"] is False
    assert result["blocking"] is True
    disk_check = next(check for check in result["checks"] if check["key"] == "disk_space")
    assert disk_check["status"] == "fail"
    assert "Speicher" in disk_check["message"]
    assert disk_check["evidence"]["disk_free"] == 10

    # Env-Override degradiert den Block ehrlich zu einer Warnung.
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    downgraded = corpus_import_jobs.preflight_import_job(
        "csv",
        str(source),
        {"text_column": "text", "__managed_corpus_dir": str(tmp_path / "corpora")},
    )
    assert downgraded["ok"] is True
    disk_warn = next(check for check in downgraded["checks"] if check["key"] == "disk_space")
    assert disk_warn["status"] == "warn"


def test_report_envelope_routes_have_typed_openapi_models():
    from candyconc.services.backend.server import app

    spec = app.openapi()

    import_reports_schema = (
        spec["paths"]["/api/v1/corpora/imports/{job_id}/reports"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    build_report_schema = (
        spec["paths"]["/api/v1/corpora/{corpus}/build-report"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )

    assert import_reports_schema["$ref"].endswith("/CorpusImportReportsResponse")
    assert build_report_schema["$ref"].endswith("/CorpusBuildReportResponse")

    schemas = spec["components"]["schemas"]
    assert {"schema_version", "job_id", "reports"} <= set(schemas["CorpusImportReportsResponse"]["required"])
    assert {"schema_version", "corpus", "reports"} <= set(schemas["CorpusBuildReportResponse"]["required"])
