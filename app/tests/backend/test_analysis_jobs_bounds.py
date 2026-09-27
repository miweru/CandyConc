from __future__ import annotations

import asyncio

import pytest

from candyconc.services.backend import analysis_jobs


@pytest.fixture(autouse=True)
def _isolated_jobs():
    analysis_jobs._JOBS.clear()
    yield
    analysis_jobs._JOBS.clear()


def test_small_result_is_stored_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_jobs, "_RESULT_MAX_BYTES", 256)
    job = analysis_jobs.create("ngrams", "demo", {})
    result = {"rows": [{"ngram": "alpha beta", "f": 3}], "min_n": 2, "max_n": 2}

    analysis_jobs.set_result(job.job_id, result=result, total_rows=1)

    stored = analysis_jobs.get(job.job_id)
    snapshot = analysis_jobs.snapshot(job.job_id)
    assert stored.result is result
    assert stored.status == "done"
    assert stored.result_bytes == analysis_jobs._estimate_result_bytes(result)
    assert stored.result_available is True
    assert stored.result_discarded is False
    assert stored.result_discard_reason is None
    assert snapshot["result_available"] is True
    assert snapshot["result_discarded"] is False


def test_oversized_result_is_discarded_with_visible_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_jobs, "_RESULT_MAX_BYTES", 32)
    job = analysis_jobs.create("ngrams", "demo", {})
    result = {"rows": [{"ngram": "x" * 64, "f": 1}]}

    analysis_jobs.set_result(job.job_id, result=result, total_rows=1)

    stored = analysis_jobs.get(job.job_id)
    snapshot = analysis_jobs.snapshot(job.job_id)
    assert stored.status == "done"
    assert stored.progress == 100
    assert stored.result is None
    assert stored.total_rows == 1
    assert stored.result_bytes is not None
    assert stored.result_bytes > 32
    assert stored.result_max_bytes == 32
    assert stored.result_available is False
    assert stored.result_discarded is True
    assert stored.result_discard_reason == "result_size_exceeds_storage_cap"
    assert "discarded" in stored.message
    assert snapshot["result_available"] is False
    assert snapshot["result_discarded"] is True
    assert snapshot["result_discard_reason"] == "result_size_exceeds_storage_cap"
    assert snapshot["result_readiness"] == "discarded"
    assert snapshot["rows_state"] == "discarded"
    assert snapshot["result_warnings"]


def test_rows_route_returns_typed_terminal_envelope_for_discarded_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import analysis as analysis_routes

    monkeypatch.setattr(server, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(analysis_jobs, "_RESULT_MAX_BYTES", 32)
    job = analysis_jobs.create("ngrams", "demo", {})
    analysis_jobs.set_result(
        job.job_id,
        result={"rows": [{"ngram": "x" * 64, "f": 1}]},
        total_rows=1,
    )

    payload = asyncio.run(
        analysis_routes.analysis_job_rows(job.job_id, offset=0, limit=10, token=None)
    )

    assert payload["status"] == "done"
    assert payload["rows"] == []
    assert payload["total_rows"] == 1
    assert payload["total"] == 1
    assert payload["result_available"] is False
    assert payload["result_discarded"] is True
    assert payload["result_discard_reason"] == "result_size_exceeds_storage_cap"
    assert payload["rows_state"] == "discarded"
    assert payload["result_warnings"]


def test_error_does_not_retain_previous_result_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_jobs, "_RESULT_MAX_BYTES", 256)
    job = analysis_jobs.create("ngrams", "demo", {})
    analysis_jobs.set_result(job.job_id, result={"rows": []}, total_rows=0)
    job.status = "running"

    analysis_jobs.set_error(job.job_id, RuntimeError("boom"))

    snapshot = analysis_jobs.snapshot(job.job_id)
    assert analysis_jobs.get(job.job_id).result is None
    assert snapshot["status"] == "error"
    assert snapshot["result_bytes"] is None
    assert snapshot["result_available"] is False
    assert snapshot["result_discarded"] is False
    assert snapshot["result_discard_reason"] is None


def test_stream_broadcasts_coalesced_updates_to_each_subscriber() -> None:
    async def scenario() -> None:
        job = analysis_jobs.create("frequency", "demo", {})
        analysis_jobs.update(job.job_id, progress=1, message="running", status="running")
        first = analysis_jobs.stream(job.job_id)
        second = analysis_jobs.stream(job.job_id)

        assert (await anext(first))["progress"] == 1
        assert (await anext(second))["progress"] == 1

        analysis_jobs.update(job.job_id, progress=10, message="queued")
        analysis_jobs.update(job.job_id, progress=30, message="counting")
        first_update, second_update = await asyncio.gather(anext(first), anext(second))
        assert first_update["progress"] == second_update["progress"] == 30

        await first.aclose()
        analysis_jobs.update(job.job_id, progress=70, message="scoring")
        assert (await anext(second))["progress"] == 70

        late = analysis_jobs.stream(job.job_id)
        assert (await anext(late))["progress"] == 70

        analysis_jobs.update(job.job_id, progress=100, message="done", status="done")
        second_terminal, late_terminal = await asyncio.gather(anext(second), anext(late))
        assert second_terminal["status"] == late_terminal["status"] == "done"
        await second.aclose()
        await late.aclose()

    asyncio.run(scenario())
