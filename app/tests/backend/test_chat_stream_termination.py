"""A3 fix: SSE generators must always end with terminal events.

Two defects in ``/chat/stream`` and ``/copilot/continue``:

1. ``reply = task.result()`` was unguarded — an orchestrator exception killed
   the stream mid-flight with no ``copilot.error``/``copilot.done``.
2. After ``task = None``, re-entering ``asyncio.wait({None, next_item})``
   while the event queue still had items raised ``TypeError`` and aborted the
   stream before the queued events and the terminal lines were emitted.
"""

import asyncio
import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from candyconc.candyconc_copilot.orchestrator import State
from candyconc.services.backend import copilot_event_bus, app, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _ExplodingOrch:
    """Orchestrator stub whose run() raises (chat_stream_endpoint path)."""

    def __init__(self, *args, **kwargs):
        pass

    def run(self, *args, **kwargs):
        raise RuntimeError("boom-orchestrator")


class _BurstOrch:
    """Stub that enqueues events synchronously and then finishes immediately.

    The events are still in the session queue when the run task completes,
    which is exactly the state that used to re-enter
    ``asyncio.wait({None, next_item})`` and die with a TypeError.
    """

    def __init__(self, *args, **kwargs):
        self.session = kwargs.get("session")

    def run(
        self,
        question,
        role="user",
        *,
        principal=None,
        max_steps=20,
        max_time=None,
    ):
        session_id = getattr(self.session, "session_id", None)
        for i in range(3):
            copilot_event_bus.publish(
                {"event": "copilot.delta", "chunk": f"delta-{i}"}, session_id
            )
        return "burst-done"


class _FailingContinueOrch:
    """Active-session stub whose continuation coroutine raises."""

    state = State.EXECUTING_TOOL

    async def continue_after_approval(self, *, max_steps: int = 8, max_time: float | None = None):
        raise RuntimeError("boom-continue")

    async def continue_after_clarification(self, *, max_steps: int = 8, max_time: float | None = None):  # pragma: no cover - safety
        raise RuntimeError("boom-continue")


class _ReturningContinueOrch:
    state = State.EXECUTING_TOOL

    async def continue_after_approval(
        self,
        *,
        max_steps: int = 8,
        max_time: float | None = None,
    ):
        return (
            "Die Fortsetzung bleibt sichtbar.} ] } </s> Nachlauf <end> "
            "<assistant<|channel|>final<|message|>{"
        )

    async def continue_after_clarification(
        self,
        *,
        max_steps: int = 8,
        max_time: float | None = None,
    ):  # pragma: no cover - safety
        return "unused"


class TestChatStreamTermination(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        self.username = server.auth.username_for_token(self.user_token)

    def _stream_lines(self, url, payload):
        with self.client.stream(
            "POST", url, params={"token": self.user_token}, json=payload
        ) as resp:
            lines = [line for line in resp.iter_lines() if line]
        return resp, lines

    def test_stream_emits_error_and_done_when_orchestrator_raises(self):
        with patch(
            "candyconc.services.backend.server.ReActOrchestrator", _ExplodingOrch
        ):
            resp, lines = self._stream_lines(
                "/api/v1/chat/stream",
                {"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: copilot.error", lines)
        self.assertTrue(any("boom-orchestrator" in line for line in lines))
        # The stream still terminates cleanly with the session-end + [DONE].
        self.assertTrue(any('"status": "error"' in line for line in lines))
        self.assertEqual(lines[-1], "data: [DONE]")

    def test_stream_drains_queued_events_after_task_completes(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator", _BurstOrch):
            resp, lines = self._stream_lines(
                "/api/v1/chat/stream",
                {"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(resp.status_code, 200)
        for i in range(3):
            self.assertTrue(
                any(f"delta-{i}" in line for line in lines),
                f"missing queued event delta-{i} in {lines}",
            )
        self.assertIn("event: copilot.done", lines)
        self.assertTrue(any('"text": "burst-done"' in line for line in lines))
        self.assertEqual(lines[-1], "data: [DONE]")

    def test_continue_emits_error_and_done_when_continuation_raises(self):
        session_id = f"continue-err-{uuid.uuid4().hex}"
        server._register_active_orchestrator(
            session_id, _FailingContinueOrch(), self.username
        )
        pending_on_close = []
        real_new_event_loop = asyncio.new_event_loop

        def _tracked_loop():
            loop = real_new_event_loop()
            close = loop.close

            def _close():
                pending_on_close.extend(
                    task for task in asyncio.all_tasks(loop) if not task.done()
                )
                close()

            loop.close = _close  # type: ignore[assignment]
            return loop

        try:
            with patch(
                "candyconc.services.backend.routes.copilot.asyncio.new_event_loop",
                side_effect=_tracked_loop,
            ):
                resp, lines = self._stream_lines(
                    "/api/v1/copilot/continue", {"sessionId": session_id}
                )
        finally:
            with server._ACTIVE_ORCH_LOCK:
                server._active_orchestrators.pop(session_id, None)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: copilot.error", lines)
        self.assertTrue(any("boom-continue" in line for line in lines))
        self.assertIn("event: copilot.done", lines)
        self.assertTrue(any('"status": "error"' in line for line in lines))
        self.assertEqual(pending_on_close, [])

    def test_continue_done_strips_confirmed_provider_protocol_tail(self):
        session_id = f"continue-clean-{uuid.uuid4().hex}"
        server._register_active_orchestrator(
            session_id,
            _ReturningContinueOrch(),
            self.username,
        )
        try:
            resp, lines = self._stream_lines(
                "/api/v1/copilot/continue",
                {"sessionId": session_id},
            )
        finally:
            with server._ACTIVE_ORCH_LOCK:
                server._active_orchestrators.pop(session_id, None)

        self.assertEqual(resp.status_code, 200)
        done_payloads = [
            line
            for line in lines
            if line.startswith("data: {") and '"text"' in line
        ]
        self.assertEqual(len(done_payloads), 1)
        self.assertIn("Die Fortsetzung bleibt sichtbar.", done_payloads[0])
        self.assertNotIn("<assistant", done_payloads[0])


if __name__ == "__main__":
    unittest.main()
