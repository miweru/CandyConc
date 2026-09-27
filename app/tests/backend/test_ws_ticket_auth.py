"""A7: one-time WebSocket ticket auth.

Browsers cannot set an Authorization header on ``new WebSocket()`` and release
mode (correctly) refuses query/body token transport — so the WS endpoints were
structurally unusable from browsers in release. Fix under test:

* ``POST /api/v1/ws-ticket`` (USER role) mints a short-TTL one-time ticket,
* the WS endpoints accept ``?ticket=`` as an auth path (header path stays),
* tickets are single-use and expire.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candyconc.services.backend import app, auth

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestWsTicketModule(unittest.TestCase):
    def test_mint_and_redeem_roundtrip(self):
        ticket, ttl = auth.mint_ws_ticket("bob")
        self.assertTrue(ticket)
        self.assertGreater(ttl, 0)
        self.assertEqual(auth.redeem_ws_ticket(ticket), "bob")

    def test_ticket_is_single_use(self):
        ticket, _ = auth.mint_ws_ticket("bob")
        self.assertEqual(auth.redeem_ws_ticket(ticket), "bob")
        self.assertIsNone(auth.redeem_ws_ticket(ticket), "ticket must be one-time")

    def test_unknown_and_empty_tickets_rejected(self):
        self.assertIsNone(auth.redeem_ws_ticket("no-such-ticket"))
        self.assertIsNone(auth.redeem_ws_ticket(None))
        self.assertIsNone(auth.redeem_ws_ticket(""))

    def test_expired_ticket_rejected(self):
        with patch.dict(
            "os.environ", {"CANDYCONC_WS_TICKET_TTL_SECONDS": "0.05"}
        ):
            ticket, ttl = auth.mint_ws_ticket("bob")
            self.assertLessEqual(ttl, 0.05)
        time.sleep(0.08)
        self.assertIsNone(auth.redeem_ws_ticket(ticket), "expired ticket must fail")

    def test_outstanding_tickets_are_capped(self):
        with auth._WS_TICKETS_LOCK:
            before = dict(auth._WS_TICKETS)
            auth._WS_TICKETS.clear()
        try:
            for _ in range(auth._WS_TICKET_MAX_OUTSTANDING + 10):
                auth.mint_ws_ticket("bob")
            with auth._WS_TICKETS_LOCK:
                self.assertLessEqual(
                    len(auth._WS_TICKETS), auth._WS_TICKET_MAX_OUTSTANDING
                )
        finally:
            with auth._WS_TICKETS_LOCK:
                auth._WS_TICKETS.clear()
                auth._WS_TICKETS.update(before)


class TestWsTicketEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user_token = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        ).json()["token"]

    def test_mint_endpoint_returns_one_time_ticket(self):
        resp = self.client.post(
            "/api/v1/ws-ticket", params={"token": self.user_token}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("ticket", body)
        self.assertIsInstance(body["expires_in"], int)
        self.assertGreater(body["expires_in"], 0)
        # The minted ticket is bound to the authenticated username.
        self.assertEqual(auth.redeem_ws_ticket(body["ticket"]), "bob")

    def _connect_code(self, path: str) -> int:
        """Open a WS handshake and return the close code it ends with.

        Auth denials close with 1008 (policy violation); a passed auth gate
        on an unknown job id closes with the default 1000 — so the code tells
        us on which side of the auth gate the handshake died.
        """
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with self.client.websocket_connect(path):
                pass
        return excinfo.value.code

    def test_ws_connect_with_ticket_then_reuse_rejected(self):
        """RBAC on: a fresh ticket authenticates the WS handshake, a reused
        (consumed) one is denied with a 1008 close — no fallback to open
        access."""
        with patch.object(auth, "RBAC_ENABLED", True):
            ticket, _ = auth.mint_ws_ticket("bob")

            # Fresh ticket: past the auth gate (unknown job id -> close 1000).
            code = self._connect_code(
                f"/api/v1/ws/analysis/no-such-job?ticket={ticket}"
            )
            self.assertNotEqual(code, 1008, "fresh ticket must authenticate")

            # Same ticket again: consumed -> no principal -> denial close.
            code = self._connect_code(
                f"/api/v1/ws/analysis/no-such-job?ticket={ticket}"
            )
            self.assertEqual(code, 1008, "reused ticket must be rejected")

    def test_ws_connect_without_ticket_or_token_rejected_in_rbac(self):
        with patch.object(auth, "RBAC_ENABLED", True):
            code = self._connect_code("/api/v1/ws/analysis/no-such-job")
            self.assertEqual(code, 1008)

    def test_ws_faiss_ticket_requires_admin_role(self):
        """/ws/faiss is ADMIN — a USER-bound ticket must be denied (1008)."""
        with patch.object(auth, "RBAC_ENABLED", True):
            user_ticket, _ = auth.mint_ws_ticket("bob")  # bob: role user
            code = self._connect_code(
                f"/api/v1/ws/faiss/no-such-job?ticket={user_ticket}"
            )
            self.assertEqual(code, 1008, "user-role ticket must not pass ADMIN gate")

            # Admin-bound ticket gets past auth (job lookup then closes 1000).
            admin_ticket, _ = auth.mint_ws_ticket("alice")  # alice: role admin
            code = self._connect_code(
                f"/api/v1/ws/faiss/no-such-job?ticket={admin_ticket}"
            )
            self.assertNotEqual(code, 1008, "admin ticket must authenticate")


class TestWsTicketRouteMatrix(unittest.TestCase):
    def test_ws_ticket_route_is_classified_user(self):
        from candyconc.services.backend.route_matrix import (
            AccessLevel,
            policy_for_path,
        )

        policy = policy_for_path("/api/v1/ws-ticket")
        self.assertIsNotNone(policy)
        self.assertEqual(policy.access, AccessLevel.USER)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
