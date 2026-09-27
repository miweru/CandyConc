"""Ein Langlaeufer stirbt nicht, wenn der Chat wechselt.

ANFORDERUNG des Auftraggebers vom 2026-09-01, woertlich:

    Also Langlaeufer sind jetzt explizit erlaubt ABER! Es sollte moeglich
    sein, dass der Langlaeufer laeuft, man einen anderen Chat waehrenddessen
    oeffnet aber der Langlaeufer davon nicht stirbt. Und er hat dann auch so
    ne progressbar cheggsd du

VORGESCHICHTE, ebenfalls von ihm: "oberflaeche war disconnected und einige
analysen waren timeout, Backend war zeitweise als nicht bereit angezeigt."

WAS VORHER GESCHAH. Der Turn lief als Task IN dem Event-Loop, den der
SSE-Generator selbst anlegt (``routes/copilot.py``: ``loop =
asyncio.new_event_loop()``, dann ``loop.create_task(asyncio.to_thread(
orch.run, ...))``). Bricht die Verbindung ab, hoert Starlette auf zu
iterieren, der suspendierte Generator wird erst vom Garbage Collector
finalisiert, und mit ihm verschwindet der Loop. Der Arbeitsthread lief
zwar weiter, aber niemand nahm sein Ergebnis entgegen. Aus Sicht des
Nutzers war eine halbe Stunde Arbeit weg.

Diese Proben pruefen die BEIDEN Zusagen einzeln: der Lauf ueberlebt, und
sein Fortschritt ist als Anteil ablesbar, nicht nur als Textzeile.
"""

from __future__ import annotations

import threading
import time
import unittest

from candyconc.services.backend.copilot_sessions import (
    _ActiveOrchestratorSession,
    fortschritt_setzen,
    lauf_abgekoppelt_starten,
)


def _sitzung() -> _ActiveOrchestratorSession:
    jetzt = time.monotonic()
    return _ActiveOrchestratorSession(
        orchestrator=object(),  # type: ignore[arg-type]
        owner="bob",
        created_at=jetzt,
        last_seen=jetzt,
        run_lock=threading.Lock(),
    )


class DerLaufUeberlebt(unittest.TestCase):
    def test_das_ergebnis_liegt_an_der_sitzung_nicht_am_aufrufer(self):
        """Der Kern: wer die Verbindung verliert, verliert nicht die Arbeit."""
        sitzung = _sitzung()
        faden = lauf_abgekoppelt_starten(sitzung, lambda: "fertige Antwort")
        faden.join(timeout=5)
        self.assertTrue(sitzung.fertig.is_set())
        self.assertEqual(sitzung.ergebnis["status"], "fertig")
        self.assertEqual(sitzung.ergebnis["antwort"], "fertige Antwort")

    def test_der_aufrufer_darf_verschwinden(self):
        """Der Lauf laeuft weiter, auch wenn niemand mehr wartet.

        Das ist der Fall "anderer Chat geoeffnet": der Wartende ist weg,
        die Arbeit nicht.
        """
        sitzung = _sitzung()
        gestartet = threading.Event()
        weiter = threading.Event()

        def _lang():
            gestartet.set()
            weiter.wait(timeout=5)
            return "spaet, aber da"

        lauf_abgekoppelt_starten(sitzung, _lang)
        self.assertTrue(gestartet.wait(timeout=5))
        # Der Aufrufer geht weg, ohne zu joinen.
        self.assertFalse(sitzung.fertig.is_set())
        weiter.set()
        self.assertTrue(sitzung.fertig.wait(timeout=5))
        self.assertEqual(sitzung.ergebnis["antwort"], "spaet, aber da")

    def test_eine_ausnahme_endet_die_sitzung_statt_sie_haengen_zu_lassen(self):
        """Ein Thread, der still stirbt, laesst die Sitzung ewig warten."""
        sitzung = _sitzung()

        def _kaputt():
            raise RuntimeError("kaboom")

        faden = lauf_abgekoppelt_starten(sitzung, _kaputt)
        faden.join(timeout=5)
        self.assertTrue(sitzung.fertig.is_set())
        self.assertEqual(sitzung.ergebnis["status"], "fehler")
        self.assertIn("kaboom", sitzung.ergebnis["fehler"])

    def test_der_faden_ist_kein_daemon(self):
        """Ein Daemon wird beim Prozessende hart abgeschnitten.

        Genau das soll nicht passieren: eine laufende Analyse ist Arbeit,
        die nicht auf halbem Weg verworfen gehoert.
        """
        sitzung = _sitzung()
        faden = lauf_abgekoppelt_starten(sitzung, lambda: "x")
        self.assertFalse(faden.daemon)
        faden.join(timeout=5)

    def test_argumente_werden_durchgereicht(self):
        sitzung = _sitzung()
        faden = lauf_abgekoppelt_starten(
            sitzung, lambda a, b=0: a + b, 40, b=2
        )
        faden.join(timeout=5)
        self.assertEqual(sitzung.ergebnis["antwort"], 42)


class DerFortschrittIstAblesbar(unittest.TestCase):
    def test_er_nennt_anteil_und_text(self):
        sitzung = _sitzung()
        fortschritt_setzen(sitzung, schritt=3, von=10, text="Kollokate")
        self.assertEqual(sitzung.fortschritt["schritt"], 3)
        self.assertEqual(sitzung.fortschritt["von"], 10)
        self.assertAlmostEqual(sitzung.fortschritt["anteil"], 0.3)
        self.assertEqual(sitzung.fortschritt["text"], "Kollokate")

    def test_der_balken_laeuft_nie_ueber(self):
        """Ein Balken bei 130 Prozent ist schlimmer als keiner.

        Braucht ein Turn mehr Schritte als geplant, waechst die erwartete
        Zahl mit, statt dass der Anteil ueber eins geht.
        """
        sitzung = _sitzung()
        fortschritt_setzen(sitzung, schritt=13, von=10)
        self.assertLessEqual(sitzung.fortschritt["anteil"], 1.0)
        self.assertEqual(sitzung.fortschritt["von"], 13)

    def test_null_von_null_faellt_nicht_um(self):
        sitzung = _sitzung()
        fortschritt_setzen(sitzung, schritt=0, von=0)
        self.assertEqual(sitzung.fortschritt["anteil"], 0.0)

    def test_eine_neue_sitzung_hat_noch_keinen_fortschritt(self):
        self.assertEqual(_sitzung().fortschritt, {})
        self.assertIsNone(_sitzung().ergebnis)
        self.assertFalse(_sitzung().fertig.is_set())


if __name__ == "__main__":
    unittest.main()
