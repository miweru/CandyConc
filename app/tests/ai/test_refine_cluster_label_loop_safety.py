"""Regression: refine_cluster_label must not crash inside a running event loop.

Defect: the wrapper called ``asyncio.run(generate_label(...))`` directly.
``asyncio.run`` raises ``RuntimeError: asyncio.run() cannot be called from a
running event loop`` when the wrapper is dispatched from async orchestrator
code — the production path (``dispatcher.dispatch`` runs inside the FastAPI
event loop).

Fix (tool_wrappers.refine_cluster_label): detect a running loop via
``asyncio.get_running_loop()``; when one is active, run the coroutine on a
worker thread with its own loop (the SessionManager.summarise pattern).
Without a running loop the plain ``asyncio.run`` path is kept.
"""

import asyncio
import unittest

# Loading the module executes its module-level _TW load, which restores every
# touched sys.modules entry (conftest stubs stay in place for other tests).
from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

from candyconc.services import cluster_labeler


class TestRefineClusterLabelLoopSafety(unittest.TestCase):
    def setUp(self):
        self.tw = _load_real_tool_wrappers()
        # Patch at the module attribute the wrapper resolves at call time
        # (late lookup, also visible from the worker thread). No LLM traffic.
        self._orig_generate_label = cluster_labeler.generate_label

        async def _fake_generate_label(samples):
            await asyncio.sleep(0)  # prove a real coroutine ran on a loop
            return f"label-for-{len(samples)}-samples"

        cluster_labeler.generate_label = _fake_generate_label
        self.addCleanup(
            setattr, cluster_labeler, "generate_label", self._orig_generate_label
        )

    def test_call_inside_running_loop_does_not_crash(self):
        """The dispatcher-path shape: sync wrapper invoked from async code."""

        async def _dispatch_like_call():
            # Old code raised RuntimeError("asyncio.run() cannot be called
            # from a running event loop") right here.
            return self.tw.refine_cluster_label(7, ["Der Hund bellt", "Die Katze schläft"])

        result = asyncio.run(_dispatch_like_call())

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cluster_id"], 7)
        self.assertEqual(result["label"], "label-for-2-samples")

    def test_call_without_running_loop_still_works(self):
        """Plain sync callers keep the direct asyncio.run path."""
        result = self.tw.refine_cluster_label(1, ["nur ein Sample"])

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["cluster_id"], 1)
        self.assertEqual(result["label"], "label-for-1-samples")


if __name__ == "__main__":
    unittest.main()
