"""Busy-lock release on mid-stream client disconnect (re-audit §4 residual).

The B4 busy-lock (``_ActiveOrchestratorSession.run_lock``) used to be released
only inside the SSE generators' ``finally``. On a mid-stream client disconnect
Starlette merely cancels the streaming task — the suspended *sync* generator is
finalized by GC eventually (non-deterministic), so the lock could stay held for
an arbitrary time, turning the session into a permanent 409.

Fix under test: an idempotent once-releaser (``server._make_once_releaser``)
shared by the generator ``finally`` (normal end) and the StreamingResponse
``background`` hook, which Starlette runs even after a client disconnect.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from candyconc.services.backend import app, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _BlockingOrch:
    """chat/stream stub whose run() blocks until the test releases it."""

    release_event: threading.Event = threading.Event()
    instances: list = []

    def __init__(self, *args, **kwargs):
        self.session = kwargs.get("session")
        type(self).instances.append(self)

    def run(
        self,
        question,
        role="user",
        *,
        principal=None,
        max_steps=20,
        max_time=None,
    ):
        type(self).release_event.wait(timeout=30)
        return "blocked-done"


class TestOnceReleaser(unittest.TestCase):
    def test_releases_exactly_once(self):
        lock = threading.Lock()
        self.assertTrue(lock.acquire(blocking=False))
        release = server._make_once_releaser(lock)

        release()
        self.assertFalse(lock.locked())

        # A new holder (e.g. a follow-up /copilot/continue) must NOT be
        # unlocked by a late second call (background hook after GC finally).
        self.assertTrue(lock.acquire(blocking=False))
        release()
        self.assertTrue(lock.locked(), "second release() must be a no-op")
        lock.release()

    def test_release_on_unlocked_lock_is_safe(self):
        lock = threading.Lock()
        release = server._make_once_releaser(lock)
        release()  # never acquired — must not raise


class TestBusyLockReleasedOnDisconnect(unittest.TestCase):
    """Drive the raw ASGI app and drop the client mid-stream."""

    def setUp(self):
        self.client = TestClient(app)
        self.user_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]
        _BlockingOrch.release_event = threading.Event()
        _BlockingOrch.instances = []

    def tearDown(self):
        _BlockingOrch.release_event.set()

    def _session_entry(self):
        orch = _BlockingOrch.instances[0]
        session_id = getattr(orch.session, "session_id", None)
        with server._ACTIVE_ORCH_LOCK:
            return session_id, server._active_orchestrators.get(session_id)

    def test_disconnect_mid_stream_releases_run_lock(self):
        body = json.dumps(
            {"messages": [{"role": "user", "content": "hi"}]}
        ).encode()

        async def drive() -> list:
            sent: list = []
            got_first_chunk = asyncio.Event()
            state = {"request_sent": False}

            async def receive():
                if not state["request_sent"]:
                    state["request_sent"] = True
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }
                # Client drops as soon as the first SSE chunk arrived.
                await got_first_chunk.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body" and message.get("body"):
                    got_first_chunk.set()

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/chat/stream",
                "raw_path": b"/api/v1/chat/stream",
                "query_string": f"token={self.user_token}".encode(),
                "root_path": "",
                "headers": [
                    (b"host", b"testserver"),
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            }
            await asyncio.wait_for(app(scope, receive, send), timeout=15)
            return sent

        with patch(
            "candyconc.services.backend.server.ReActOrchestrator", _BlockingOrch
        ):
            sent = asyncio.run(drive())

        # The stream started (status 200 + at least one chunk) and the app call
        # returned because of the disconnect — orch.run is still blocked.
        start = next(m for m in sent if m["type"] == "http.response.start")
        self.assertEqual(start["status"], 200)
        self.assertTrue(_BlockingOrch.instances, "orchestrator was never built")

        session_id, entry = self._session_entry()
        self.assertIsNotNone(entry, "active session vanished prematurely")

        # The busy-lock must be released promptly after the disconnect, NOT
        # only when GC eventually finalizes the suspended generator.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and entry.run_lock.locked():
            time.sleep(0.02)
        self.assertFalse(
            entry.run_lock.locked(),
            "run_lock still held after mid-stream client disconnect",
        )

        # Cleanup: unblock the worker thread and drop the session.
        _BlockingOrch.release_event.set()
        with server._ACTIVE_ORCH_LOCK:
            server._active_orchestrators.pop(session_id, None)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
