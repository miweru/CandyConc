"""D7 regression: copilot_event_bus SSE bus cross-thread delivery promptness.

The SSE generators in ``server.py`` run in a worker thread with their own event
loop that is only *running* inside ``run_until_complete`` windows. The
orchestrator emits events from a SEPARATE thread (``asyncio.to_thread``). The old
``_deliver`` gated cross-thread wakeups on ``loop.is_running()``; between the
generator's run windows that check was False, so it fell back to a bare
``put_nowait`` on the wrong thread and the waiting loop was never woken — the
consumer hung until the next unrelated wakeup. These tests pin that a queue bound
to an idle loop is woken promptly by an emit from another thread, and that the
``loop=`` capture is honoured.
"""

import asyncio
import importlib.util
import threading
from pathlib import Path

import pytest


root = Path(__file__).resolve().parents[2]
copilot_event_bus_path = root / "src" / "candyconc" / "services" / "backend" / "copilot_event_bus.py"
_spec = importlib.util.spec_from_file_location(
    "candyconc.services.backend.copilot_event_bus_xthread", copilot_event_bus_path
)
copilot_event_bus = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(copilot_event_bus)  # type: ignore[arg-type]


def test_emit_from_other_thread_wakes_idle_owner_loop_promptly():
    """A queue bound to an idle loop must be woken by a cross-thread emit.

    We register the queue against a loop that is NOT running at emit time, emit
    from a different thread, and then run the loop's ``queue.get()`` with a short
    timeout. With the old is_running() gate the get would time out (the loop was
    never woken); with call_soon_threadsafe it returns immediately.
    """
    loop = asyncio.new_event_loop()
    q = None
    try:
        # Register on the (currently idle) loop, exactly like server.py gen().
        q = copilot_event_bus.subscribe(session_id="sess-x", loop=loop)
        assert copilot_event_bus._listener_loop[id(q)] is loop

        emitted = {"delta": {"content": "from other thread"}}

        def _emit():
            # Different thread, target loop NOT running → must still schedule.
            copilot_event_bus.publish(emitted, session_id="sess-x")

        t = threading.Thread(target=_emit)
        t.start()
        t.join()

        # The loop was idle when the emit happened; draining it must surface the
        # event promptly (call_soon_threadsafe woke it). wait_for guards against
        # the regression (a hang) by failing fast.
        item = loop.run_until_complete(asyncio.wait_for(q.get(), timeout=2.0))
        assert item == emitted
    finally:
        if q is not None:
            copilot_event_bus.unsubscribe(q)
        loop.close()


def test_concurrent_emit_and_consume_across_threads_delivers_all():
    """All emitted events arrive at the bound loop's queue, in order."""
    loop = asyncio.new_event_loop()
    q = None
    n = 25
    try:
        q = copilot_event_bus.subscribe(session_id="sess-y", loop=loop)

        def _producer():
            for i in range(n):
                copilot_event_bus.publish({"i": i}, session_id="sess-y")

        async def _consume():
            received = []
            for _ in range(n):
                received.append(await asyncio.wait_for(q.get(), timeout=2.0))
            return received

        t = threading.Thread(target=_producer)
        t.start()
        received = loop.run_until_complete(_consume())
        t.join()

        assert [r["i"] for r in received] == list(range(n))
    finally:
        if q is not None:
            copilot_event_bus.unsubscribe(q)
        loop.close()


def test_register_without_loop_in_async_context_captures_running_loop():
    """subscribe(loop=None) inside an async context binds the running loop."""

    async def _inner():
        q = copilot_event_bus.subscribe(session_id="sess-z")
        try:
            assert copilot_event_bus._listener_loop[id(q)] is asyncio.get_running_loop()
            copilot_event_bus.publish({"hello": 1}, session_id="sess-z")
            return await asyncio.wait_for(q.get(), timeout=2.0)
        finally:
            copilot_event_bus.unsubscribe(q)

    item = asyncio.run(_inner())
    assert item == {"hello": 1}


def test_delivery_uses_registered_loop_not_queue_private_loop():
    """The fix binds delivery to the loop passed to register(), not q._loop.

    server.py creates the consumer loop in the sync generator body and subscribes
    the queue against it explicitly. The queue object's private ``_loop`` (set at
    construction time, before the gen loop is current) can point elsewhere; the
    old code keyed wakeups off ``q._loop`` + ``is_running()`` and could schedule
    on the wrong loop. This pins that ``_listener_loop`` (the registered loop) is
    what _deliver targets, regardless of ``q._loop``.
    """
    consumer_loop = asyncio.new_event_loop()
    q = None
    try:
        q = copilot_event_bus.subscribe(session_id="sess-bind", loop=consumer_loop)
        # Whatever q._loop happens to be, the bus must use the registered loop.
        assert copilot_event_bus._listener_loop[id(q)] is consumer_loop

        scheduled_on: list[object] = []
        real_csts = consumer_loop.call_soon_threadsafe

        def _spy(cb, *a):
            scheduled_on.append(consumer_loop)
            return real_csts(cb, *a)

        consumer_loop.call_soon_threadsafe = _spy  # type: ignore[assignment]

        def _emit():
            copilot_event_bus.publish({"k": "v"}, session_id="sess-bind")

        t = threading.Thread(target=_emit)
        t.start()
        t.join()

        assert scheduled_on == [consumer_loop], (
            "delivery must schedule on the registered consumer loop"
        )
        item = consumer_loop.run_until_complete(asyncio.wait_for(q.get(), timeout=2.0))
        assert item == {"k": "v"}
    finally:
        if q is not None:
            copilot_event_bus.unsubscribe(q)
        consumer_loop.close()


def test_unregister_drops_loop_binding():
    loop = asyncio.new_event_loop()
    q = None
    try:
        q = copilot_event_bus.subscribe(session_id="sess-u", loop=loop)
        assert id(q) in copilot_event_bus._listener_loop
        copilot_event_bus.unsubscribe(q)
        assert id(q) not in copilot_event_bus._listener_loop
        assert id(q) not in copilot_event_bus._listener_session
    finally:
        if q is not None:
            copilot_event_bus.unsubscribe(q)
        loop.close()


def test_emit_to_closed_loop_does_not_raise():
    """A teardown race (loop closed before emit) must not crash the producer."""
    loop = asyncio.new_event_loop()
    q = copilot_event_bus.subscribe(session_id="sess-c", loop=loop)
    try:
        loop.close()
        # Emitting now hits call_soon_threadsafe on a closed loop; _deliver
        # swallows the RuntimeError rather than propagating it to the worker.
        copilot_event_bus.publish({"late": True}, session_id="sess-c")
    finally:
        copilot_event_bus.unsubscribe(q)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
