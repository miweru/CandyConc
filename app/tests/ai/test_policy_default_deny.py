"""Release gating contract for the cluster tool family.

History: ``PolicyEngine.check`` used to hard-deny the six cluster tools in
release mode when no ACL was configured (``DEFAULT_DENY_TOOLS``).  That list
is now empty — the cluster read tools run in release, and the mutating
cluster tools are registered ``read_only=False`` so the orchestrator's
write-tool approval gate (``_is_tool_known_write`` →
``_should_require_approval``, orchestrator.py ~2643-2660) pauses them for
user approval instead of blocking them outright.

Pinned contract:
* release mode + NO ACL: PolicyEngine allows the cluster tools (no more
  default-deny) — read tools run, write tools reach the orchestrator gate;
* an explicit ACL keeps governing exactly as before (release or dev);
* the empty ``DEFAULT_DENY_TOOLS`` seam stays importable for future entries;
* orchestrator side: a tool flagged ``read_only=False`` (e.g. cluster_save)
  is approval-required at low/medium autonomy and auto-runs only at >= 9.
"""

import re
import unittest
from pathlib import Path

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import (
    PolicyEngine,
    make_orchestrator,
    policy_engine as policy_engine_mod,
)

CLUSTER_READ_TOOLS = ("semantic_cluster", "semantic_cluster_words")
CLUSTER_WRITE_TOOLS = (
    "cluster_save",
    "cluster_export_md",
    "semantic_recluster",
    "refine_cluster_label",
)


class TestClusterToolsNotDefaultDenied(unittest.TestCase):
    def test_deny_list_is_empty(self):
        # The cluster family was removed from the release deny list; the seam
        # itself stays (future non-cluster entries would land here again).
        self.assertEqual(policy_engine_mod.DEFAULT_DENY_TOOLS, frozenset())

    def test_release_no_acl_allows_cluster_read_tools(self):
        policy = PolicyEngine(token_budget=100, release_mode=True)
        for tool in CLUSTER_READ_TOOLS:
            with self.subTest(tool=tool):
                res = policy.check("user", tool, 1)
                self.assertEqual(res["status"], "ok")

    def test_release_no_acl_passes_cluster_write_tools_to_orchestrator_gate(self):
        # The policy layer no longer hard-denies the write tools; they are
        # instead paused by the orchestrator write-tool approval gate (tested
        # below).
        policy = PolicyEngine(token_budget=100, release_mode=True)
        for tool in CLUSTER_WRITE_TOOLS:
            with self.subTest(tool=tool):
                res = policy.check("user", tool, 1)
                self.assertEqual(res["status"], "ok")

    def test_release_no_acl_allows_read_tool(self):
        policy = PolicyEngine(token_budget=100, release_mode=True)
        res = policy.check("user", "run_cqlf_query", 1)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(policy.remaining, 99)

    def test_release_with_acl_unchanged(self):
        # An explicit ACL keeps governing; nothing is allowed outside it.
        policy = PolicyEngine(
            token_budget=100,
            acl={"user": ["cluster_save"]},
            release_mode=True,
        )
        self.assertEqual(policy.check("user", "cluster_save", 1)["status"], "ok")
        self.assertEqual(
            policy.check("user", "run_cqlf_query", 1)["status"], "error"
        )

    def test_dev_no_acl_unchanged(self):
        policy = PolicyEngine(token_budget=100, release_mode=False)
        self.assertEqual(policy.check("user", "cluster_save", 1)["status"], "ok")


class TestClusterWriteToolsRouteThroughApprovalGate(unittest.TestCase):
    """cluster_save & co. are approval-required, not denied.

    The registry flags them ``read_only=False`` (anchored below against the
    real tool_wrappers source), and the orchestrator routes every known-write
    tool through ``_should_require_approval`` before dispatch
    (orchestrator.py ~2643-2660).
    """

    def _orchestrator(self, autonomy: int):
        async def _dispatch(call, token=None):  # pragma: no cover - not dispatched
            return {"status": "success"}

        orch = make_orchestrator(
            tools=[],
            call_llm=lambda messages, tools, **kwargs: {"choices": []},
            dispatch=_dispatch,
            ui_context={"autonomy_level": autonomy},
        )
        # Runtime info exactly as get_tool_runtime_info() derives it from the
        # real @llm_tool(..., read_only=False) registrations.
        orch._tool_runtime_info = {
            name: {"read_only": False, "concurrency_safe": False}
            for name in CLUSTER_WRITE_TOOLS
        }
        return orch

    def _write_action(self, tool_name: str):
        # Mirror of the action_data the orchestrator builds for write tools.
        return {
            "actionType": tool_name,
            "payload": {},
            "reversible": False,
            "summary": f"Schreib-Tool {tool_name} ausführen",
            "impact": f"Der Copilot moechte das schreibende Tool {tool_name} ausführen.",
        }

    def test_registry_flags_write_tools_read_only_false(self):
        # Source anchor: the conftest stubs tool_wrappers in sys.modules, so
        # assert against the real registration source instead of importing.
        src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "candyconc"
            / "candyconc_copilot"
            / "tool_wrappers.py"
        ).read_text(encoding="utf-8")
        anchors = {
            "cluster_save": r"@llm_tool\(CLUSTER_SAVE_TOOL,[^)]*read_only=False",
            "cluster_export_md": r"@llm_tool\(CLUSTER_EXPORT_MD_TOOL,[^)]*read_only=False",
            "semantic_recluster": r"@llm_tool\(SEMANTIC_RECLUSTER_TOOL,[^)]*read_only=False",
            "refine_cluster_label": r"@llm_tool\(REFINE_CLUSTER_LABEL_TOOL,[^)]*read_only=False",
        }
        for tool, pattern in anchors.items():
            with self.subTest(tool=tool):
                self.assertRegex(src, re.compile(pattern))

    def test_cluster_save_requires_approval_at_medium_autonomy(self):
        # Frontend medium level (4): non-reversible write tools pause for
        # approval instead of being dispatched or denied.
        orch = self._orchestrator(autonomy=4)
        for tool in CLUSTER_WRITE_TOOLS:
            with self.subTest(tool=tool):
                self.assertTrue(orch._is_tool_known_write(tool))
                self.assertTrue(
                    orch._should_require_approval(self._write_action(tool))
                )

    def test_cluster_save_requires_approval_at_low_autonomy(self):
        orch = self._orchestrator(autonomy=1)
        self.assertTrue(
            orch._should_require_approval(self._write_action("cluster_save"))
        )

    def test_cluster_save_autoruns_at_max_autonomy(self):
        orch = self._orchestrator(autonomy=10)
        self.assertTrue(orch._is_tool_known_write("cluster_save"))
        self.assertFalse(
            orch._should_require_approval(self._write_action("cluster_save"))
        )

    def test_read_only_tool_is_not_known_write(self):
        # A tool without a read_only=False flag never hits the write gate.
        orch = self._orchestrator(autonomy=4)
        self.assertFalse(orch._is_tool_known_write("run_cqlf_query"))


class TestDefaultDenyFromConfig(unittest.TestCase):
    """release_mode=None resolves CANDYCONC_SECURITY_MODE from candyconc.config.

    With an empty deny list the mode no longer changes tool gating, but the
    resolution path itself stays covered (it is shared with auth).
    """

    def _with_mode(self, mode: str):
        from candyconc import config as cc_config

        prev = cc_config.get("CANDYCONC_SECURITY_MODE", "local_dev_unsafe")
        cc_config.set("CANDYCONC_SECURITY_MODE", mode)
        self.addCleanup(cc_config.set, "CANDYCONC_SECURITY_MODE", prev)

    def test_config_release_mode_resolves_true(self):
        self._with_mode("release")
        policy = PolicyEngine(token_budget=100)
        self.assertTrue(policy._is_release_mode())
        # Empty deny list: cluster_save passes the policy layer even in
        # release (the orchestrator approval gate takes over).
        self.assertEqual(policy.check("user", "cluster_save", 1)["status"], "ok")

    def test_config_dev_default_resolves_false(self):
        self._with_mode("local_dev_unsafe")
        policy = PolicyEngine(token_budget=100)
        self.assertFalse(policy._is_release_mode())
        self.assertEqual(policy.check("user", "cluster_save", 1)["status"], "ok")


if __name__ == "__main__":
    unittest.main()
