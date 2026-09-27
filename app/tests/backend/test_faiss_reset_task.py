"""Fire-and-forget FAISS reset task: strong reference + exception logging.

The old ``add_done_callback(lambda _t: asyncio.create_task(reset_faiss_build()))``
left the reset task unreferenced — it could be garbage-collected mid-flight and
its exceptions were silently swallowed. The task is now held in
``server._FAISS_RESET_TASKS`` until completion and failures are logged.
"""

import asyncio
import logging

from candyconc.services.backend import server


def test_faiss_reset_task_is_referenced_and_logs_failures(monkeypatch, caplog):
    async def _boom():
        raise RuntimeError("reset-failed")

    monkeypatch.setattr(server, "reset_faiss_build", _boom)

    async def _run():
        server._schedule_faiss_reset(None)
        # Strong reference held while the task is in flight.
        assert len(server._FAISS_RESET_TASKS) == 1
        task = next(iter(server._FAISS_RESET_TASKS))
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)  # let the done-callback run

    with caplog.at_level(logging.ERROR, logger="candyconc.services.backend.server"):
        asyncio.run(_run())

    assert server._FAISS_RESET_TASKS == set()
    assert any("reset_faiss_build failed" in rec.message for rec in caplog.records)


def test_faiss_reset_task_success_leaves_no_residue(monkeypatch):
    async def _ok():
        return None

    monkeypatch.setattr(server, "reset_faiss_build", _ok)

    async def _run():
        server._schedule_faiss_reset(None)
        task = next(iter(server._FAISS_RESET_TASKS))
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert server._FAISS_RESET_TASKS == set()
