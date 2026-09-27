from __future__ import annotations

import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

from candyconc.services import semantic_index_jobs as jobs


def _fake_index(tmp_path):
    document = SimpleNamespace(_positions=np.asarray([0, 4], dtype=np.uint32))
    sentence = SimpleNamespace(_positions=np.asarray([0, 2, 5], dtype=np.uint32))
    boundaries = SimpleNamespace(document=document, sentence=sentence)
    token_store = SimpleNamespace(token_count=8)
    fast_index = SimpleNamespace(
        index_path=tmp_path,
        boundaries=boundaries,
        token_store=token_store,
    )
    return SimpleNamespace(fast_index=fast_index)


@pytest.mark.parametrize("faiss_available", [True, False])
def test_preflight_reports_real_fast_index_counts_and_mac_gate(monkeypatch, tmp_path, faiss_available):
    monkeypatch.setattr(jobs, "_faiss_installed", lambda: faiss_available)
    monkeypatch.setattr(jobs.sys, "platform", "darwin")
    monkeypatch.setattr(jobs.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(jobs.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(jobs, "_memory_bytes", lambda: 64 * 1024**3)
    monkeypatch.setenv("CANDYCONC_SEMANTIC_JOB_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("CANDYCONC_MLX_RUNTIME_PYTHON", str(tmp_path / "missing-python"))

    result = jobs.preflight(_fake_index(tmp_path), "demo")

    assert result["platform"]["supported"] is True
    assert result["counts"] == {"documents": 2, "sentences": 4, "tokens": 8}
    assert result["options"]["doc"]["can_build"] is faiss_available
    assert (jobs.FAISS_MISSING_MESSAGE in result["warnings"]) is not faiss_available
    assert result["options"]["both"]["required_free_bytes"] > 0
    assert result["runtime"]["model"] == jobs.MODEL_NAME


def test_preflight_treats_complete_triplets_as_available(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.sys, "platform", "darwin")
    monkeypatch.setattr(jobs.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("CANDYCONC_SEMANTIC_JOB_DIR", str(tmp_path / "jobs"))
    for level in ("doc", "sentence"):
        for name in (
            f"faiss_gemma_{level}.index",
            f"gemma_{level}_vecs.npy",
            f"gemma_{level}_texts.json",
        ):
            (tmp_path / name).write_bytes(b"ready")

    result = jobs.preflight(_fake_index(tmp_path), "demo")

    assert result["available_levels"] == {"doc": True, "sentence": True}
    assert result["options"]["both"]["required_free_bytes"] < 2_000_000_000


def test_persisted_running_job_without_process_becomes_resumable(monkeypatch, tmp_path):
    monkeypatch.setenv("CANDYCONC_SEMANTIC_JOB_DIR", str(tmp_path))
    run_id = "a" * 32
    state_path = tmp_path / run_id / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": jobs.STATE_SCHEMA,
                "run_id": run_id,
                "operation_id": "settings.embedding_management.local_index_build",
                "corpus": "demo",
                "corpus_path": str(tmp_path / "corpus"),
                "levels": ["doc"],
                "status": "running",
                "phase": "embed_doc",
                "progress": 42,
                "message": "läuft",
                "process_group_id": 99_999_999,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    snapshot = jobs.snapshot(run_id)

    assert snapshot["status"] == "stale"
    assert snapshot["evidence"]["resumable"] is True
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["phase"] == "interrupted"


def test_launch_reuses_same_active_job_and_blocks_competing_build(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "_faiss_installed", lambda: True)
    job_root = tmp_path / "jobs"
    corpus_path = tmp_path / "corpus"
    corpus_path.mkdir()
    monkeypatch.setenv("CANDYCONC_SEMANTIC_JOB_DIR", str(job_root))
    monkeypatch.setenv("CANDYCONC_MLX_RUNTIME_PYTHON", str(tmp_path / "missing-python"))
    monkeypatch.setattr(jobs.sys, "platform", "darwin")
    monkeypatch.setattr(jobs.platform, "machine", lambda: "arm64")
    run_id = "b" * 32
    state_path = job_root / run_id / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": jobs.STATE_SCHEMA,
                "run_id": run_id,
                "operation_id": "settings.embedding_management.local_index_build",
                "corpus": "demo",
                "corpus_path": str(corpus_path),
                "levels": ["doc"],
                "status": "running",
                "phase": "embed_doc",
                "progress": 20,
                "message": "läuft",
                "process_group_id": os.getpid(),
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    same = jobs.launch(_fake_index(corpus_path), "demo", ["doc"])
    assert same["run_id"] == run_id

    other_path = tmp_path / "other"
    other_path.mkdir()
    with pytest.raises(RuntimeError, match="anderer lokaler Semantik-Build"):
        jobs.launch(_fake_index(other_path), "other", ["doc"])
