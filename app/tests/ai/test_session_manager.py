import asyncio
import concurrent.futures
import sys
import unittest
from unittest.mock import patch

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import SessionManager, lm_summary_stub, make_orchestrator


def dummy_call(messages, tools, **kwargs):
    return {"choices": [{"message": {"content": "ok"}}]}


def dummy_dispatch(call, token=None):
    return {"status": "ok"}


class TestSessionManager(unittest.TestCase):
    def test_async_summary_has_no_second_hardcoded_timeout(self):
        result_calls = []

        class _Future:
            def result(self, *args, **kwargs):
                result_calls.append((args, kwargs))
                return {"role": "assistant", "content": "{}"}

        class _Executor:
            def __init__(self, *args, **kwargs):
                del args, kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, function):
                del function
                return _Future()

        async def _summarise_inside_running_loop():
            manager = SessionManager()
            return manager._lm_summary(
                [{"role": "user", "content": "Ein langer Verlauf"}]
            )

        with lm_summary_stub(), patch.object(
            concurrent.futures, "ThreadPoolExecutor", _Executor
        ):
            asyncio.run(_summarise_inside_running_loop())

        self.assertEqual(result_calls, [((), {})])

    def test_async_summary_propagates_worker_runtime_error_without_nested_loop_retry(self):
        calls = []

        async def failing_summary(*_args, **_kwargs):
            calls.append("called")
            raise RuntimeError("summary backend failed")

        async def _summarise_inside_running_loop():
            manager = SessionManager()
            with self.assertRaisesRegex(RuntimeError, "summary backend failed"):
                manager._lm_summary(
                    [{"role": "user", "content": "Ein langer Verlauf"}]
                )

        package = sys.modules["candyconc_copilot"]
        with patch.object(
            package,
            "_lm_chat_async",
            failing_summary,
            create=True,
        ):
            asyncio.run(_summarise_inside_running_loop())

        self.assertEqual(calls, ["called"])

    def test_trim_history(self):
        # Real SessionManager summarises via the package-level _lm_chat_async
        # seam (session_manager.py: ``from . import _lm_chat_async``); the
        # stub keeps the test deterministic without a live LLM.
        with lm_summary_stub():
            sm = SessionManager(max_messages=3)
            for i in range(5):
                sm.append({"role": "user", "content": str(i)})
            sm.summarise()
        self.assertEqual(len(sm.history), 3)
        self.assertTrue(sm.summaries)
        self.assertEqual(sm.history[0]["content"], "2")

    def test_orchestrator_persistence(self):
        with lm_summary_stub():
            sm = SessionManager(max_messages=10)
            orch = make_orchestrator([], dummy_call, dummy_dispatch, session=sm)
            orch.run("hi")
            self.assertEqual(len(sm.history), 2)
            orch.run("again")
            self.assertEqual(len(sm.history), 4)


if __name__ == "__main__":
    unittest.main()
