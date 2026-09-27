"""Preserve a completed preview answer when the surrounding operation reaches its deadline."""

from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from candyconc.services.backend import copilot_event_bus, server
from candyconc.services.backend.server import app

#: Lang genug, dass die Fragment-Schwelle des Salvage nicht greift, und mit
#: einer Zahl, die in KEINER Evidenz steht: so wird gleichzeitig geprueft,
#: dass die geborgene Antwort die Zahlenwache nicht umgeht.
VORSCHAU = (
    "Kernbefund: Das Suchwort erscheint in den ausgewerteten Belegzeilen "
    "durchgaengig in wertender Umgebung. Die Belege verteilen sich ueber "
    "mehrere Dokumente und stammen aus derselben Registerschicht. "
    "Methodisch beruht der Befund auf einer Konkordanzstichprobe, nicht "
    "auf einer Vollerhebung, und die Lesart der Umgebung ist eine "
    "Interpretation der Zeilen, keine Messung. "
) * 3


class _VorschauDannHaengen:
    """Sendet die Vorschau auf den Bus und wartet danach auf Abbruch."""

    def __init__(self, session_id: str) -> None:
        from candyconc.candyconc_copilot.orchestrator import State

        self.state = State.EXECUTING_TOOL
        self._session_id = session_id
        self._turn_evidence_items: list[dict] = []
        self._cancelled = threading.Event()

    def _vorschau_senden(self) -> None:
        copilot_event_bus.publish(
            {
                "event": "copilot.vorlaeufige_antwort",
                "text": VORSCHAU,
                "geprueft": False,
                "hinweis": "Vorlaeufig.",
            },
            self._session_id,
        )

    async def continue_after_approval(self, *, max_steps: int = 8, max_time=None):
        self._vorschau_senden()
        await asyncio.to_thread(self._cancelled.wait)
        return "nie"

    continue_after_clarification = continue_after_approval

    def request_cancel(self) -> None:
        self._cancelled.set()


class TestVorschauUeberlebtDenBackstop(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        resp = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        )
        self.token = resp.json()["token"]
        self.username = server.auth.username_for_token(self.token)

    def _lauf(self, session_id: str, orch=None) -> str:
        env = {
            "CANDYCONC_COPILOT_MAX_TIME_SEC": "0.25",
            "CANDYCONC_COPILOT_BACKSTOP_GRACE_SEC": "0.25",
        }
        orch = orch or _VorschauDannHaengen(session_id)
        session = server._register_active_orchestrator(
            session_id, orch, self.username
        )
        try:
            with patch.dict(os.environ, env):
                started = time.monotonic()
                with self.client.stream(
                    "POST",
                    "/api/v1/copilot/continue",
                    params={"token": self.token},
                    json={"sessionId": session_id},
                ) as resp:
                    self.assertEqual(resp.status_code, 200, resp.read())
                    body = "".join(chunk for chunk in resp.iter_text())
                self.assertLess(time.monotonic() - started, 10.0)
        finally:
            orch.request_cancel()
            server._active_orchestrators.pop(session_id, None)
            self.assertTrue(session.fertig.wait(5), "continue worker did not finish")
        return body

    def test_die_endantwort_traegt_die_vorschau_statt_leer_zu_sein(self):
        body = self._lauf("bergung-1")
        # Das Zeitlimit greift weiterhin und wird weiterhin ehrlich gemeldet.
        self.assertIn("Zeitlimit", body)
        self.assertIn("copilot.done", body)
        # The fallback must preserve a nonempty answer.
        import json as _json

        text = ""
        for block in body.split("\n\n"):
            if "copilot.done" not in block:
                continue
            for line in block.splitlines():
                if line.startswith("data: "):
                    text = _json.loads(line[6:]).get("text") or ""
        self.assertTrue(
            text.strip(),
            "Der Backstop hat die fertige Antwort wieder vernichtet.",
        )
        self.assertIn("Kernbefund", text)

    def test_ohne_vorschau_bleibt_die_ehrliche_leere_antwort(self):
        # Positive Klasse. Ohne diesen Fall waere ein Handler gruen, der
        # irgendeinen Text erfindet, sobald der Backstop greift.
        class _NurHaengen(_VorschauDannHaengen):
            def _vorschau_senden(self) -> None:
                return None

        session_id = "bergung-2"
        body = self._lauf(session_id, _NurHaengen(session_id))
        self.assertIn("Zeitlimit", body)
        self.assertNotIn("Kernbefund", body)


if __name__ == "__main__":
    unittest.main()
