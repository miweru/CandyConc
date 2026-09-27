import importlib
import importlib.util
import unittest
from pathlib import Path

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import make_orchestrator

# Real SSE bus, loaded privately: other test modules in this directory
# (grounding runtime / timeout evidence bootstraps) overwrite the
# ``candyconc.services.backend.copilot_event_bus`` attribute with SimpleNamespace fakes,
# so a plain ``from candyconc.services.backend import copilot_event_bus`` is
# order-dependent. The orchestrator resolves the bus lazily via
# ``from candyconc.services.backend import copilot_event_bus`` inside ``run_async``,
# which reads the parent-module attribute -- setUp pins that attribute to this
# private real instance and tearDown restores the previous value.
_EVENT_BUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "candyconc"
    / "services"
    / "backend"
    / "copilot_event_bus.py"
)
_spec = importlib.util.spec_from_file_location("cc_real_copilot_event_bus", _EVENT_BUS_PATH)
assert _spec and _spec.loader
copilot_event_bus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(copilot_event_bus)

_backend = importlib.import_module("candyconc.services.backend")

TOOLS = [
    {"type": "function", "function": {"name": "dummy", "parameters": {"type": "object"}}}
]


def _call_llm(messages, tools, stream=False, **kwargs):
    if not any(m.get("role") == "tool" for m in messages):
        msg = {
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "dummy", "arguments": "{}"},
                }
            ]
        }
    else:
        msg = {"content": "done"}
    if stream:
        def gen():
            yield {"choices": [{"delta": msg}]}

        return gen()
    return {"choices": [{"message": msg}]}


class TestProgressEvents(unittest.TestCase):
    _MISSING = object()

    def setUp(self) -> None:
        import sys

        self._backend = sys.modules.get("candyconc.services.backend") or _backend
        self._prev_copilot_event_bus = getattr(self._backend, "copilot_event_bus", self._MISSING)
        self._backend.copilot_event_bus = copilot_event_bus

    def tearDown(self) -> None:
        if self._prev_copilot_event_bus is self._MISSING:
            try:
                delattr(self._backend, "copilot_event_bus")
            except AttributeError:
                pass
        else:
            self._backend.copilot_event_bus = self._prev_copilot_event_bus

    def test_event_order(self):
        attempts = []

        def _dispatch(call, token=None):
            # Real contract: dispatch(tool_call_dict, token) (dispatcher.py:28).
            attempts.append(1)
            if len(attempts) == 1:
                return {"status": "retry", "delay": 0}
            return {"status": "ok"}

        # tool_retries=1 is required: with the default of 0 the retry loop is
        # already exhausted after the first {"status": "retry"} response and
        # the retry result is kept as the final tool output
        # (orchestrator.py ``_dispatch`` retry loop).
        orch = make_orchestrator(TOOLS, _call_llm, _dispatch, tool_retries=1)
        queue = copilot_event_bus.subscribe(orch.session.session_id)
        try:
            result = orch.run("hi", stream=True)
            self.assertEqual(result, "done")
            self.assertEqual(len(attempts), 2)

            # Real stream contract: start -> copilot.recovery (tool_retry) ->
            # copilot.tool_result -> end.  Read the session listener directly;
            # Copilot events are intentionally not retained as global history.
            events = []
            while not queue.empty():
                event = queue.get_nowait()
                if event.get("event") in {
                    "start",
                    "end",
                    "copilot.recovery",
                    "copilot.tool_result",
                }:
                    events.append(event)
        finally:
            copilot_event_bus.unsubscribe(queue)
        kinds = [e["event"] for e in events]
        self.assertEqual(
            kinds, ["start", "copilot.recovery", "copilot.tool_result", "end"]
        )
        self.assertEqual(events[0]["tool"], "dummy")
        self.assertEqual(events[-1]["tool"], "dummy")
        self.assertEqual(events[1]["recovery"]["kind"], "tool_retry")
        tool_result = events[2]["toolResult"]
        self.assertEqual(tool_result["toolName"], "dummy")
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["output"], {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
