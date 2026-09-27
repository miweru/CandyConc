import json
import unittest
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from candyconc.services.backend import app, server
from candyconc.services.llm_client import LLMErrorKind, LLMRequestError


@dataclass(frozen=True)
class _FakeRoute:
    requires_corpus_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FakeBinding:
    tool_name: str
    operation_id: str
    effects: tuple[str, ...] = ("read",)
    capability_id: str = "test.capability"
    route: _FakeRoute = field(default_factory=_FakeRoute)


def _tool_schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


class TestChatAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        resp = self.client.post(
            "/api/v1/login",
            json={"username": "bob", "password": "bob"},
        )
        self.token = resp.json()["token"]
        self.username = server.auth.username_for_token(self.token)
        self._reset_policy_state()

    def tearDown(self):
        self._reset_policy_state()

    def _reset_policy_state(self):
        server.POLICY_BUDGETS.clear()
        server.POLICY_BUDGETS["default"] = 1000
        server.POLICY_ACLS.clear()

    def _chat_payload(self, content="hello", **overrides):
        payload = {"messages": [{"role": "user", "content": content}]}
        payload.update(overrides)
        return payload

    def _post_chat(self, payload):
        return self.client.post(
            "/api/v1/chat",
            params={"token": self.token},
            json=payload,
        )

    def test_chat_returns_orchestrator_reply(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.return_value = "ok"

            resp = self._post_chat(self._chat_payload("hello"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("content"), "ok")
        policy = mock_orch.call_args.kwargs["policy"]
        self.assertEqual(policy.token_budget, 1000)
        self.assertIsNone(policy.acl)
        # max_time is wired into orch.run (r9 DT-SERVER) so the orchestrator's
        # cooperative timeout arms; assert it is forwarded (non-None).
        instance.run.assert_called_once_with(
            "hello",
            role="user",
            principal=self.username,
            max_steps=server._copilot_max_steps_ceiling(),
            max_time=server._copilot_max_time_sec(),
        )

    def test_chat_strips_confirmed_provider_protocol_tail(self):
        leaked = (
            "Die belegte Analyse bleibt sichtbar.} ] } </s> Nachlauf <end> "
            "<assistant<|channel|>final<|message|>{"
        )
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = leaked

            resp = self._post_chat(self._chat_payload("hello"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json().get("content"),
            "Die belegte Analyse bleibt sichtbar.",
        )

    def test_chat_empty_messages_422_before_orchestrator(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            resp = self._post_chat({"messages": []})

        self.assertEqual(resp.status_code, 422)
        self.assertIn("messages", resp.json().get("detail", ""))
        mock_orch.assert_not_called()

    def test_chat_and_stream_model_not_loaded_return_424_before_orchestrator(self):
        error = LLMRequestError(
            kind=LLMErrorKind.MODEL_NOT_LOADED,
            message="LM Studio meldet kein geladenes Modell. No model load was attempted.",
            model="qwen-test",
            route="chat_completions:off",
        )
        calls = [
            lambda: self._post_chat(self._chat_payload("hello")),
            lambda: self.client.post(
                "/api/v1/chat/stream",
                params={"token": self.token},
                json=self._chat_payload("hi"),
            ),
        ]
        for call in calls:
            with patch(
                "candyconc.services.backend.server.ensure_copilot_runtime_available",
                side_effect=error,
            ), patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
                resp = call()
            self.assertEqual(resp.status_code, 424)
            self.assertNotIn("text/event-stream", resp.headers.get("content-type", ""))
            detail = resp.json().get("detail", {})
            self.assertEqual(detail.get("code"), "model_not_loaded")
            self.assertEqual(detail.get("model"), "qwen-test")
            mock_orch.assert_not_called()

    def test_server_side_policy_state_controls_chat_budget_and_acl(self):
        # Server-side per-user policy state (policy_state module) must drive the
        # chat policy; the former admin REST endpoint that mutated it was
        # removed, so the state is set directly.
        server.POLICY_BUDGETS[self.username] = 5
        server.POLICY_ACLS[self.username] = ["dummy"]

        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.return_value = "ok"

            resp = self._post_chat(self._chat_payload("hello"))

        self.assertEqual(resp.status_code, 200)
        policy = mock_orch.call_args.kwargs["policy"]
        self.assertEqual(policy.token_budget, 5)
        self.assertEqual(policy.acl, {self.username: ["dummy"]})
        instance.run.assert_called_once_with(
            "hello",
            role="user",
            principal=self.username,
            max_steps=server._copilot_max_steps_ceiling(),
            max_time=server._copilot_max_time_sec(),
        )

    def test_request_policy_override_ignored_for_non_admin(self):
        # C2 fix: a user-role caller must NOT be able to lift their own
        # budget/ACL restrictions by echoing the fields in the request body.
        # (max_steps is not security-sensitive and stays honored.)
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.return_value = "ok"

            resp = self._post_chat(
                self._chat_payload(
                    "hello",
                    budget=3,
                    acl=["dummy"],
                    max_steps=4,
                )
            )

        self.assertEqual(resp.status_code, 200)
        policy = mock_orch.call_args.kwargs["policy"]
        self.assertEqual(policy.token_budget, 1000)
        self.assertIsNone(policy.acl)
        instance.run.assert_called_once_with(
            "hello",
            role="user",
            principal=self.username,
            max_steps=4,
            max_time=server._copilot_max_time_sec(),
        )

    def test_stream_endpoint_emits_session_events_reply_and_done(self):
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.return_value = "stream-ok"

            with self.client.stream(
                "POST",
                "/api/v1/chat/stream",
                params={"token": self.token},
                json=self._chat_payload("hi"),
            ) as resp:
                lines = [line for line in resp.iter_lines() if line]

        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: copilot.session", lines)
        # The reply text is carried inside the terminal ``copilot.done`` event
        # (per-session SSE bus contract), not as a bare ``data: <text>`` line.
        self.assertIn("event: copilot.done", lines)
        self.assertEqual(lines[-1], "data: [DONE]")
        session_payloads = [
            json.loads(line.removeprefix("data: "))
            for line in lines
            if line.startswith("data: {")
        ]
        self.assertEqual(session_payloads[0]["status"], "started")
        done_payloads = [
            p
            for p in session_payloads
            if p.get("status") == "completed" and "text" in p
        ]
        self.assertEqual(len(done_payloads), 1)
        self.assertEqual(done_payloads[0]["text"], "stream-ok")
        self.assertEqual(session_payloads[-1]["status"], "completed")
        instance.run.assert_called_once_with(
            "hi",
            role="user",
            principal=self.username,
            max_steps=server._copilot_max_steps_ceiling(),
            max_time=server._copilot_max_time_sec(),
        )

    def test_stream_done_strips_confirmed_provider_protocol_tail(self):
        leaked = (
            "Die belegte Analyse bleibt sichtbar.} ] } </s> Nachlauf <end> "
            "<assistant<|channel|>final<|message|>{"
        )
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = leaked

            with self.client.stream(
                "POST",
                "/api/v1/chat/stream",
                params={"token": self.token},
                json=self._chat_payload("hi"),
            ) as resp:
                payloads = [
                    json.loads(line.removeprefix("data: "))
                    for line in resp.iter_lines()
                    if line.startswith("data: {")
                ]

        done = [payload for payload in payloads if "text" in payload]
        self.assertEqual(len(done), 1)
        self.assertEqual(
            done[0]["text"],
            "Die belegte Analyse bleibt sichtbar.",
        )

    def test_chat_exposes_only_mcp_dispatchable_tools_in_release_mode(self):
        tools = [_tool_schema("run_cqlf_query"), _tool_schema("query_count"), _tool_schema("frequency_list")]
        bindings = {
            "run_cqlf_query": (_FakeBinding("run_cqlf_query", "query"),),
            "query_count": (_FakeBinding("query_count", "count"),),
            "frequency_list": (_FakeBinding("frequency_list", "frequency"),),
        }
        runtime_info = {
            "frequency_list": {"read_only": True, "concurrency_safe": True},
            "query_count": {"read_only": False, "concurrency_safe": False},
            # run_cqlf_query intentionally has no runtime metadata here: fail closed.
        }
        with patch("candyconc.services.backend.server._get_tools", return_value=tools), patch(
            "candyconc.services.backend.server._get_tool_runtime_info",
            return_value=runtime_info,
        ), patch(
            "candyconc.services.backend.server._product_tool_bindings_by_name",
            return_value=bindings,
        ), patch("candyconc.services.backend.server.auth.is_release_mode", return_value=True), patch(
            "candyconc.services.backend.server.auth.validate_release_security",
            return_value=None,
        ), patch(
            "candyconc.services.backend.server.ensure_copilot_runtime_available",
            new_callable=AsyncMock,
        ), patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "ok"

            resp = self.client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {self.token}"},
                json=self._chat_payload("Erstelle eine Frequenzliste der häufigsten Wörter."),
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        selected = mock_orch.call_args.args[0]
        self.assertEqual([tool["function"]["name"] for tool in selected], ["frequency_list"])

    def test_chat_and_stream_share_explicit_acl_tool_gate(self):
        tools = [_tool_schema("frequency_list")]
        bindings = {
            "frequency_list": (
                _FakeBinding("frequency_list", "frequency", effects=("write",)),
            ),
        }
        runtime_info = {
            "frequency_list": {"read_only": False, "concurrency_safe": False},
        }
        server.POLICY_ACLS[self.username] = ["frequency_list"]
        with patch("candyconc.services.backend.server._get_tools", return_value=tools), patch(
            "candyconc.services.backend.server._get_tool_runtime_info",
            return_value=runtime_info,
        ), patch(
            "candyconc.services.backend.server._product_tool_bindings_by_name",
            return_value=bindings,
        ), patch("candyconc.services.backend.server.auth.is_release_mode", return_value=True), patch(
            "candyconc.services.backend.server.auth.validate_release_security",
            return_value=None,
        ), patch(
            "candyconc.services.backend.server.ensure_copilot_runtime_available",
            new_callable=AsyncMock,
        ), patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            mock_orch.return_value.run.return_value = "ok"

            chat_resp = self.client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {self.token}"},
                json=self._chat_payload("Erstelle eine Frequenzliste."),
            )
            with self.client.stream(
                "POST",
                "/api/v1/chat/stream",
                headers={"Authorization": f"Bearer {self.token}"},
                json=self._chat_payload("Erstelle eine Frequenzliste."),
            ) as stream_resp:
                list(stream_resp.iter_lines())

        self.assertEqual(chat_resp.status_code, 200, chat_resp.text)
        self.assertEqual(stream_resp.status_code, 200)
        selected_by_call = [
            [tool["function"]["name"] for tool in call.args[0]]
            for call in mock_orch.call_args_list
        ]
        self.assertEqual(selected_by_call, [["frequency_list"], ["frequency_list"]])


if __name__ == "__main__":
    unittest.main()
