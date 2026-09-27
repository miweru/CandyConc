"""The contributor smoke isolates app state and supports both source layouts."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from candyconc.tools import backend_ui_live_smoke as smoke


@pytest.mark.parametrize("app_dir", ["app", "app"])
def test_runner_preserves_home_and_isolates_both_model_endpoints(tmp_path, monkeypatch, app_dir):
    root = tmp_path / "repo"
    src = root / app_dir / "src" / "candyconc"
    src.mkdir(parents=True)
    web = root / "candyconc-web"
    web.mkdir()
    (web / "package.json").write_text("{}")
    assert smoke._repo_root(src) == root
    monkeypatch.setenv("HOME", str(tmp_path / "host-home"))
    monkeypatch.setenv("CANDYCONC_CONFIG_FILE", str(tmp_path / "host-config.toml"))
    monkeypatch.setenv("CANDYCONC_GEMMA_EMB_ENDPOINT", "http://host-model/embeddings")
    host = dict(os.environ)
    calls = []
    built_with = []
    monkeypatch.setattr(smoke, "build_smoke_index", lambda root, work:
                        built_with.append(dict(os.environ)) or work / "index")
    monkeypatch.setattr(smoke, "_wait_for_http", lambda *a, **kw: None)
    monkeypatch.setattr(smoke, "run_import_preflight_matrix", lambda *a: {"status": "passed"})
    monkeypatch.setattr(smoke, "run_collocation_stat_parity", lambda *a: {"status": "passed"})
    backend = Mock()
    backend.poll.side_effect = [None, 0]
    monkeypatch.setattr(smoke.subprocess, "Popen", lambda cmd, **kw:
                        calls.append((cmd, kw)) or backend)
    monkeypatch.setattr(smoke.subprocess, "run", lambda cmd, **kw:
                        calls.append((cmd, kw)) or SimpleNamespace(returncode=0))
    result = smoke.run_backend_ui_live_smoke(root, backend_port=8101, frontend_port=8102)
    assert result["status"] == "passed"
    assert calls[0][0][-2:] == ["--port", "8101"]
    for env in [built_with[0], *(kwargs["env"] for _, kwargs in calls)]:
        assert env["HOME"] == host["HOME"]
        assert Path(env["CANDYCONC_HOME"]).is_relative_to(Path(result["work_dir"]))
        assert Path(env["CANDYCONC_CONFIG_FILE"]).read_text() == ""
        assert env["COPILOT_ENDPOINT"] == "http://127.0.0.1:9/v1/responses"
        assert env["CANDYCONC_GEMMA_EMB_ENDPOINT"] == "http://127.0.0.1:9/v1/embeddings"
        assert env["PYTHONPATH"].split(os.pathsep)[0] == str(src.parent)
        assert env["CANDYCONC_FRONTEND_PORT"] == "8102"
    assert dict(os.environ) == host
    backend.terminate.assert_called_once()


def test_cli_forwards_explicit_ports(tmp_path, monkeypatch):
    run = Mock(return_value={"name": "backend_ui_live_smoke", "status": "passed"})
    monkeypatch.setattr(smoke, "run_backend_ui_live_smoke", run)
    assert smoke.main(["--repo-root", str(tmp_path), "--backend-port", "8101",
                       "--frontend-port", "8102", "--json"]) == 0
    run.assert_called_once_with(tmp_path, timeout=240, backend_port=8101, frontend_port=8102)


def test_preflight_matrix_needs_no_installed_pipeline(tmp_path, monkeypatch):
    from candyconc.ingest import pipelines
    from candyconc.services.backend import corpus_import_jobs

    monkeypatch.setattr(pipelines, "pipeline_installed", lambda name: name.startswith("blank:"))
    monkeypatch.setattr(smoke, "_post_json", lambda url, payload:
                        corpus_import_jobs.preflight_import_job(
                            payload["method"], payload["input_path"], payload))
    result = smoke.run_import_preflight_matrix("http://unused/api/v1", tmp_path)
    assert result["status"] == "passed", result["methods"]
    assert result["method_count"] == 5


def test_install_smoke_isolates_both_model_endpoints(tmp_path, monkeypatch):
    from candyconc.tools import install_smoke

    monkeypatch.setenv("COPILOT_ENDPOINT", "http://host-model/responses")
    monkeypatch.setenv("CANDYCONC_GEMMA_EMB_ENDPOINT", "http://host-model/embeddings")
    host = dict(os.environ)
    env = install_smoke._environment(tmp_path, tmp_path / "home")
    assert env["COPILOT_ENDPOINT"] == "http://127.0.0.1:9/v1/responses"
    assert env["CANDYCONC_GEMMA_EMB_ENDPOINT"] == "http://127.0.0.1:9/v1/embeddings"
    assert dict(os.environ) == host
