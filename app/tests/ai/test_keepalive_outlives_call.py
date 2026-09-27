"""The pooled-connection expiry exceeds the reference interval between model calls.

The fixture checks the configured relationship against a recorded roughly
200-second interval. It does not measure a live model call."""

from __future__ import annotations

import asyncio
import unittest

from candyconc.services.llm_client import _shared_http_client

#: Gemessen am 2026-09-01: 1211 s Verifikation auf etwa sechs Aufrufe.
GEMESSENE_AUFRUFDAUER_S = 200.0


class DieFristUeberlebtEinenAufruf(unittest.TestCase):
    def test_die_frist_liegt_ueber_der_gemessenen_aufrufdauer(self):
        async def hole():
            return _shared_http_client()

        client = asyncio.run(hole())
        pool = getattr(client, "_transport", None)
        frist = None
        for ort in (pool, getattr(pool, "_pool", None)):
            wert = getattr(ort, "_keepalive_expiry", None)
            if wert is not None:
                frist = float(wert)
                break
        self.assertIsNotNone(
            frist, "die Keepalive-Frist ist am Client nicht ablesbar"
        )
        self.assertGreater(
            frist, GEMESSENE_AUFRUFDAUER_S,
            f"Frist {frist}s liegt unter der gemessenen Aufrufdauer "
            f"{GEMESSENE_AUFRUFDAUER_S}s, die Wiederverwendung greift nie",
        )

    def test_sie_ist_kein_leerlauf_ohne_ende(self):
        """Die Gegenrichtung. Eine Frist, die nie abraeumt, ist keine."""
        async def hole():
            return _shared_http_client()

        client = asyncio.run(hole())
        pool = getattr(client, "_transport", None)
        for ort in (pool, getattr(pool, "_pool", None)):
            wert = getattr(ort, "_keepalive_expiry", None)
            if wert is not None:
                self.assertLess(float(wert), 24 * 3600.0)
                return
        self.fail("die Keepalive-Frist ist am Client nicht ablesbar")


if __name__ == "__main__":
    unittest.main()
