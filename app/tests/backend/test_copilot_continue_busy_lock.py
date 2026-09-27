"""B4 fix: orchestrator re-entrancy busy-lock.

``/copilot/continue`` used to check only ``orch.state`` before driving the
orchestrator — a race window in which two concurrent continues (or a continue
racing the initial ``/chat/stream`` run) would drive the SAME orchestrator
from two worker-thread event loops.

The fix adds a per-session ``threading.Lock``
(``_ActiveOrchestratorSession.run_lock``) taken with ``acquire(blocking=False)``
by every entry point that drives a registered orchestrator:

* ``/copilot/continue`` -> HTTP 409 "Session läuft bereits" while held,
  released when the SSE generator finishes.
* the initial ``/chat/stream`` run holds it for the whole stream so a continue
  cannot race the first run.
"""

import unittest
import uuid
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from candyconc.candyconc_copilot.orchestrator import State
from candyconc.services.backend import app, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _ContinuableOrch:
    """Active-session stub whose continuation completes normally."""

    state = State.WAITING_LLM

    async def continue_after_approval(self, *, max_steps: int = 8, max_time: float | None = None):  # pragma: no cover - safety
        return "continued-ok"

    async def continue_after_clarification(self, *, max_steps: int = 8, max_time: float | None = None):
        return "continued-ok"


class _LockProbeOrch:
    """chat/stream stub that reports whether its own busy-lock is held."""

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
        with server._ACTIVE_ORCH_LOCK:
            entry = server._active_orchestrators.get(session_id)
        locked = entry is not None and entry.run_lock.locked()
        return f"run-lock-held={locked};role={role};principal={principal}"


class TestCopilotContinueBusyLock(unittest.TestCase):
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

    def _pop_session(self, session_id):
        with server._ACTIVE_ORCH_LOCK:
            server._active_orchestrators.pop(session_id, None)

    def test_continue_returns_409_while_lock_held(self):
        session_id = f"busy-{uuid.uuid4().hex}"
        entry = server._register_active_orchestrator(
            session_id, _ContinuableOrch(), self.username
        )
        self.assertTrue(entry.run_lock.acquire(blocking=False))
        try:
            resp = self.client.post(
                "/api/v1/copilot/continue",
                params={"token": self.user_token},
                json={"sessionId": session_id},
            )
            self.assertEqual(resp.status_code, 409)
            self.assertIn("Session läuft bereits", resp.json()["detail"])
        finally:
            entry.run_lock.release()
            self._pop_session(session_id)

    def test_continue_works_after_lock_released_and_releases_again(self):
        session_id = f"busy-{uuid.uuid4().hex}"
        entry = server._register_active_orchestrator(
            session_id, _ContinuableOrch(), self.username
        )
        entry.run_lock.acquire()
        entry.run_lock.release()
        try:
            resp, lines = self._stream_lines(
                "/api/v1/copilot/continue", {"sessionId": session_id}
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(any("continued-ok" in line for line in lines))
            self.assertIn("event: copilot.done", lines)
            # The generator's finally released the lock for the next continue.
            self.assertTrue(entry.run_lock.acquire(blocking=False))
            entry.run_lock.release()
        finally:
            self._pop_session(session_id)

    def test_state_409_still_releases_lock(self):
        """A non-continuable state must not leave the busy-lock behind."""

        class _DoneOrch(_ContinuableOrch):
            state = State.FINISHED

        session_id = f"busy-{uuid.uuid4().hex}"
        entry = server._register_active_orchestrator(
            session_id, _DoneOrch(), self.username
        )
        try:
            resp = self.client.post(
                "/api/v1/copilot/continue",
                params={"token": self.user_token},
                json={"sessionId": session_id},
            )
            self.assertEqual(resp.status_code, 409)
            self.assertIn("cannot continue", resp.json()["detail"])
            self.assertTrue(entry.run_lock.acquire(blocking=False))
            entry.run_lock.release()
        finally:
            self._pop_session(session_id)

    def test_initial_stream_holds_lock_and_releases_after(self):
        with patch(
            "candyconc.services.backend.server.ReActOrchestrator", _LockProbeOrch
        ):
            resp, lines = self._stream_lines(
                "/api/v1/chat/stream",
                {"messages": [{"role": "user", "content": "hi"}]},
            )
        self.assertEqual(resp.status_code, 200)
        # The busy-lock was held while the orchestrator ran ...
        self.assertTrue(
            any("run-lock-held=True" in line for line in lines),
            f"lock not held during initial run: {lines}",
        )
        self.assertTrue(
            any(
                f"role=user;principal={self.username}" in line
                for line in lines
            ),
            f"stream route did not separate turn role and principal: {lines}",
        )
        self.assertEqual(lines[-1], "data: [DONE]")
        # ... and is free again afterwards (continue may drive the session).
        import json as _json

        session_id = None
        for line in lines:
            if line.startswith("data: ") and "sessionId" in line:
                session_id = _json.loads(line[len("data: "):]).get("sessionId")
                break
        self.assertIsNotNone(session_id)
        with server._ACTIVE_ORCH_LOCK:
            entry = server._active_orchestrators.get(session_id)
        self.assertIsNotNone(entry)
        try:
            self.assertTrue(entry.run_lock.acquire(blocking=False))
            entry.run_lock.release()
        finally:
            self._pop_session(session_id)


if __name__ == "__main__":
    unittest.main()
