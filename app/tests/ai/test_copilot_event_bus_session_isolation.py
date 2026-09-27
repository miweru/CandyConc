"""Behavioural coverage for confidential, session-scoped Copilot events."""

import asyncio
import importlib.util
from pathlib import Path
import unittest


root = Path(__file__).resolve().parents[2]
bus_path = root / "src" / "candyconc" / "services" / "backend" / "copilot_event_bus.py"
spec = importlib.util.spec_from_file_location("candyconc.services.backend.copilot_event_bus", bus_path)
copilot_event_bus = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(copilot_event_bus)  # type: ignore[arg-type]


def _drain(queue) -> list:
    items = []
    while True:
        try:
            items.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return items


class TestCopilotEventSessionIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self._queues = []

    def tearDown(self) -> None:
        for queue in reversed(self._queues):
            copilot_event_bus.unsubscribe(queue)

    def _register(self, session_id: str):
        queue = copilot_event_bus.subscribe(session_id)
        self._queues.append(queue)
        return queue

    def test_event_for_session_a_is_never_delivered_to_session_b(self) -> None:
        queue_a = self._register("sess-A")
        queue_b = self._register("sess-B")

        copilot_event_bus.publish({"delta": {"content": "secret for A"}}, "sess-A")

        self.assertEqual(_drain(queue_a), [{"delta": {"content": "secret for A"}}])
        self.assertEqual(_drain(queue_b), [])

    def test_each_session_receives_only_its_own_event_order(self) -> None:
        queue_a = self._register("sess-A")
        queue_b = self._register("sess-B")

        copilot_event_bus.publish({"event": "start", "tool": "a-tool"}, "sess-A")
        copilot_event_bus.publish({"event": "start", "tool": "b-tool"}, "sess-B")

        self.assertEqual(_drain(queue_a), [{"event": "start", "tool": "a-tool"}])
        self.assertEqual(_drain(queue_b), [{"event": "start", "tool": "b-tool"}])

    def test_unregister_stops_delivery_only_for_that_listener(self) -> None:
        dropped = self._register("sess-A")
        kept = self._register("sess-A")
        copilot_event_bus.unsubscribe(dropped)
        self._queues.remove(dropped)

        copilot_event_bus.publish({"event": "ping"}, "sess-A")

        self.assertEqual(_drain(dropped), [])
        self.assertEqual(_drain(kept), [{"event": "ping"}])

    def test_unscoped_registration_and_delivery_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "session_id"):
            copilot_event_bus.subscribe(None)
        with self.assertRaisesRegex(ValueError, "session_id"):
            copilot_event_bus.publish({"event": "unsafe"}, None)
