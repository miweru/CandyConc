import unittest
from unittest.mock import patch

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import (
    make_orchestrator,
    orchestrator as orchestrator_module,
)


class TestUserMessageRole(unittest.TestCase):
    """Regression: authenticated identity must not replace the turn role.

    ``role`` controls user-turn reset, search and grounding preflight.
    ``principal`` controls policy/ACL and LLM request scoping. Conflating them
    caused principals such as ``anon`` to bypass every ``role == "user"`` guard.
    """

    def _capture_turn(self, role: str = "user", principal: str | None = None):
        captured = {}

        def _call_llm(messages, tools, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return {"choices": [{"message": {"content": "ok"}}]}

        orch = make_orchestrator([], _call_llm, lambda call, token=None: {})
        if principal is None:
            # Exercise the deliberate compatibility path for legacy positional
            # usernames as well as ordinary ChatML roles.
            orch.run("hello world", role)
        else:
            orch.run("hello world", role=role, principal=principal)
        return captured

    @staticmethod
    def _last_turn(messages):
        # R2 KV-split + Waechter-Rollen-Aenderung (a038abb3e1): der
        # Runtime-Guard reist als USER-Nachricht mit [System note:]-Wrapper
        # am Ende; der Nutzer-Turn ist die letzte Nachricht ohne Wrapper
        # und ohne System-Rolle.
        for message in reversed(messages):
            if message.get("role") == "system":
                continue
            if str(message.get("content") or "").startswith("[System note:"):
                continue
            return message
        raise AssertionError("kein Nutzer-Turn in den Nachrichten")

    def test_legacy_positional_username_is_a_user_turn(self):
        captured = self._capture_turn("guest")
        messages = captured["messages"]
        last = self._last_turn(messages)
        self.assertEqual(
            last["role"],
            "user",
            f"user turn must have role 'user', got {last['role']!r}",
        )
        self.assertEqual(last["content"], "hello world")
        # No message may leak a non-standard role to the LLM.
        allowed = {"system", "user", "assistant", "tool"}
        bad = [m for m in messages if m.get("role") not in allowed]
        self.assertEqual(bad, [], f"non-standard roles leaked to LLM: {bad}")
        self.assertEqual(captured["kwargs"]["user"], "guest")

    def test_explicit_principal_is_separate_from_user_role(self):
        captured = self._capture_turn(role="user", principal="anon")
        self.assertEqual(self._last_turn(captured["messages"])["role"], "user")
        self.assertEqual(captured["kwargs"]["user"], "anon")

    def test_default_user_role_unchanged(self):
        messages = self._capture_turn("user")["messages"]
        last = self._last_turn(messages)
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["content"], "hello world")

    def test_principal_user_turn_resets_and_runs_contract_preflight(self):
        captured = {}

        def _call_llm(messages, tools, **kwargs):
            captured["kwargs"] = kwargs
            return {"choices": [{"message": {"content": "ok"}}]}

        tool = {
            "type": "function",
            "function": {
                "name": "run_cqlf_query",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        contract = orchestrator_module.AnalysisContract(
            mode="direct_answer",
            track="lookup",
            analysis_family="term_frequency",
            deliverable_kind="lookup_answer",
            question_scope="count Zeit",
        )
        orch = make_orchestrator([tool], _call_llm, lambda call, token=None: {})
        orch._failed_tool_attempts["stale"] = {"message": "old failure"}
        orch._active_analysis_contract = {"stale": True}
        orch._turn_evidence_items = [{"id": "stale-evidence"}]

        with patch.object(
            orchestrator_module,
            "heuristic_analysis_contract",
            return_value=contract,
        ) as preflight:
            result = orch.run(
                "Wie oft kommt Zeit vor?",
                role="user",
                principal="anon",
            )

        self.assertEqual(result, "ok")
        preflight.assert_called_once()
        self.assertEqual(orch._failed_tool_attempts, {})
        self.assertEqual(orch._turn_evidence_items, [])
        self.assertEqual(
            orch._active_analysis_contract.get("analysis_family"),
            "term_frequency",
        )
        self.assertEqual(captured["kwargs"]["user"], "anon")


if __name__ == "__main__":
    unittest.main()
