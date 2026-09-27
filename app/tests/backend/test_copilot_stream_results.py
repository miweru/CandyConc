import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from candyconc.services.backend import app, server
from candyconc.services.backend import copilot_event_bus


class TestCopilotStreamResults(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.token = self.client.post(
            "/api/v1/login",
            json={"username": "alice", "password": "alice"},
        ).json()["token"]
        server._active_orchestrators.clear()

    def tearDown(self) -> None:
        server._active_orchestrators.clear()

    def _chat_payload(self, content: str = "hello") -> dict:
        return {"messages": [{"role": "user", "content": content}]}

    def test_chat_stream_surfaces_session_scoped_tool_results(self) -> None:
        expected_outputs = [
            {
                "event": "copilot.tool_result",
                "toolResult": {
                    "tool": "frequency_list",
                    "status": "ok",
                    "rows": 2,
                },
            },
            {
                "delta": {
                    "role": "assistant",
                    "content": "Zwischenschritt abgeschlossen.",
                }
            },
        ]

        def _run(
            question: str,
            role: str = "user",
            *,
            principal: str | None = None,
            max_steps: int = 20,
            max_time: float | None = None,
        ) -> str:
            self.assertEqual(question, "hello")
            self.assertEqual(role, "user")
            self.assertEqual(
                principal,
                server.auth.username_for_token(self.token),
            )
            # Vorgabe der Route, 2026-09-01 von 10 auf 20 angehoben.
            self.assertEqual(max_steps, server._copilot_max_steps_ceiling())
            # r9 DT-SERVER: max_time is now wired into orch.run. Seit dem
            # 2026-09-20 ist None ein gueltiger Wert und heisst kein Budget
            # (Nutzervorgabe). Der Vertrag ist Durchreichen, nicht "positiv":
            # geprueft wird, dass die Route genau den aufgeloesten Wert gibt.
            self.assertEqual(max_time, server._copilot_max_time_sec())
            session_id = next(iter(server._active_orchestrators))
            for item in expected_outputs:
                copilot_event_bus.publish(item, session_id)
                time.sleep(0.01)
            return "final-answer"

        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.side_effect = _run

            with self.client.stream(
                "POST",
                "/api/v1/chat/stream",
                params={"token": self.token},
                json=self._chat_payload(),
            ) as resp:
                lines = [line for line in resp.iter_lines() if line]

        self.assertEqual(resp.status_code, 200)
        self.assertIn("event: copilot.session", lines)
        self.assertIn("event: copilot.tool_result", lines)
        # Final reply rides in the terminal ``copilot.done`` event under
        # ``text`` (per-session SSE bus contract), not a bare ``data:`` line.
        self.assertIn("event: copilot.done", lines)
        self.assertEqual(lines[-1], "data: [DONE]")
        self.assertLess(
            lines.index("event: copilot.tool_result"),
            lines.index("event: copilot.done"),
        )

        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in lines
            if line.startswith("data: {")
        ]
        self.assertEqual(payloads[0]["status"], "started")
        self.assertEqual(payloads[-1]["status"], "completed")
        done_payloads = [
            p for p in payloads if p.get("status") == "completed" and "text" in p
        ]
        self.assertEqual(len(done_payloads), 1)
        self.assertEqual(done_payloads[0]["text"], "final-answer")
        self.assertIn(expected_outputs[0], payloads)
        self.assertIn(expected_outputs[1], payloads)
        instance.run.assert_called_once_with(
            "hello",
            role="user",
            principal=server.auth.username_for_token(self.token),
            max_steps=server._copilot_max_steps_ceiling(),
            max_time=server._copilot_max_time_sec(),
        )

    def test_chat_stream_unsubscribes_after_completion(self) -> None:
        with patch("candyconc.services.backend.server.ReActOrchestrator") as mock_orch:
            instance = mock_orch.return_value
            instance.run.return_value = "done"

            with self.client.stream(
                "POST",
                "/api/v1/chat/stream",
                params={"token": self.token},
                json=self._chat_payload("cleanup"),
            ) as resp:
                lines = [line for line in resp.iter_lines() if line]

        self.assertEqual(resp.status_code, 200)
        # Reply text lives in the terminal ``copilot.done`` event.
        done_payloads = [
            json.loads(line.removeprefix("data: "))
            for line in lines
            if line.startswith("data: {") and '"text"' in line
        ]
        self.assertEqual(len(done_payloads), 1)
        self.assertEqual(done_payloads[0]["status"], "completed")
        self.assertEqual(done_payloads[0]["text"], "done")
        session_id = next(iter(server._active_orchestrators))
        self.assertNotIn(session_id, copilot_event_bus._session_listeners)


if __name__ == "__main__":
    unittest.main()
