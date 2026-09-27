"""Concurrent connect/disconnect coverage for the Copilot event stream."""

import asyncio
import importlib.util
import threading
import time
from pathlib import Path

import pytest


root = Path(__file__).resolve().parents[2]
bus_path = root / "src" / "candyconc" / "services" / "backend" / "copilot_event_bus.py"
spec = importlib.util.spec_from_file_location(
    "candyconc.services.backend.copilot_event_bus_buslock", bus_path
)
copilot_event_bus = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(copilot_event_bus)  # type: ignore[arg-type]


def test_concurrent_register_unregister_while_events_stream_is_race_free():
    errors: list[BaseException] = []
    stop = threading.Event()

    def emit() -> None:
        sequence = 0
        while not stop.is_set():
            try:
                copilot_event_bus.publish({"sequence": sequence}, "shared")
            except BaseException as exc:  # noqa: BLE001 - capture a thread failure
                errors.append(exc)
                return
            sequence += 1
            time.sleep(0.0005)

    def churn() -> None:
        for _ in range(200):
            try:
                queue = copilot_event_bus.subscribe("shared")
                copilot_event_bus.unsubscribe(queue)
            except BaseException as exc:  # noqa: BLE001 - capture a thread failure
                errors.append(exc)
                return

    emitter = threading.Thread(target=emit)
    churners = [threading.Thread(target=churn) for _ in range(4)]
    emitter.start()
    for worker in churners:
        worker.start()
    for worker in churners:
        worker.join()
    stop.set()
    emitter.join()

    assert not errors, f"event-stream race produced errors: {errors[:3]}"


def test_unregistered_listener_never_receives_a_later_event():
    kept = copilot_event_bus.subscribe("sess-A")
    dropped = copilot_event_bus.subscribe("sess-A")
    try:
        copilot_event_bus.unsubscribe(dropped)
        copilot_event_bus.publish({"x": 1}, "sess-A")

        assert kept.get_nowait() == {"x": 1}
        with pytest.raises(asyncio.QueueEmpty):
            dropped.get_nowait()
    finally:
        copilot_event_bus.unsubscribe(kept)
