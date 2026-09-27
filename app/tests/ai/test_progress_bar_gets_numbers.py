"""Der Fortschrittsbalken bekommt Zahlen, nicht nur ein Feld.

ANFORDERUNG vom 2026-09-01: "und er hat dann auch so ne progressbar".

WARUM DIESE PROBE. Die erste Fassung las ``self._turn_max_steps`` mit
``getattr`` und Vorgabe null, und das Attribut gab es nicht. Das
Statusereignis haette dann gar kein ``fortschritt``-Feld getragen, das
Frontend zeigt ohne Feld bewusst KEINEN Balken, und niemand haette
bemerkt, dass die Anzeige nie erscheint. Eine Anzeige, die nichts zeigt
und nicht sagt, dass sie nichts zeigt, ist schlimmer als keine.

Geprueft wird deshalb die KETTE, nicht das Vorhandensein eines Feldes:
das Budget wird beim Turnstart gemerkt, das Statusereignis rechnet daraus
einen Anteil, und der Anteil bleibt zwischen null und eins.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

_QUELLE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
)


def _funktion(name: str):
    quelle = _QUELLE.read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if (
            isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef))
            and knoten.name == name
        ):
            return ast.get_source_segment(quelle, knoten) or ""
    raise AssertionError(f"{name} nicht gefunden")


class DieKetteIstVollstaendig(unittest.TestCase):
    def test_das_budget_wird_beim_turnstart_gemerkt(self):
        """Ohne diese Zuweisung liest der Sender ein Attribut, das es nicht gibt."""
        quelle = _QUELLE.read_text(encoding="utf-8")
        self.assertIn("self._turn_max_steps = int(max_steps or 0)", quelle)

    def test_das_statusereignis_traegt_den_fortschritt(self):
        rumpf = _funktion("_ra_emit_status")
        for marke in ('"fortschritt"', "_turn_max_steps", "fortschrittsanteil"):
            with self.subTest(marke=marke):
                self.assertIn(marke, rumpf)

    def test_die_rechnung_selbst(self):
        """Die Rechnung liegt in copilot_sessions, also wird sie dort geprueft.

        Sie ist am 2026-09-01 dorthin gewandert, weil der Orchestrator an
        seinem Zeilendeckel sitzt und der Deckel Zerlegung verlangt statt
        Anhebung. Eine Probe, die nur den Aufruf sieht, prueft nichts.
        """
        from candyconc.services.backend.copilot_sessions import (
            fortschrittsanteil,
        )

        self.assertEqual(
            fortschrittsanteil(3, 10),
            {"schritt": 3, "von": 10, "anteil": 0.3},
        )
        # Ein Balken bei 130 Prozent ist schlimmer als keiner.
        gewachsen = fortschrittsanteil(13, 10)
        self.assertEqual(gewachsen["von"], 13)
        self.assertLessEqual(gewachsen["anteil"], 1.0)
        # Kein Budget heisst KEIN Balken, nicht ein geratener.
        self.assertIsNone(fortschrittsanteil(3, 0))
        self.assertIsNone(fortschrittsanteil(0, 0))


class DasFrontendZeichnetNurEchteZahlen(unittest.TestCase):
    """Die andere Haelfte der Naht, im Vue-Bauteil."""

    def setUp(self):
        # tests/ai/x.py -> ai, tests, app, Repowurzel.
        # Die erste Fassung griff eine Ebene zu hoch, und BEIDE Proben
        # wurden still uebersprungen. Ein uebersprungener Test ist kein
        # Test, und genau das ist in diesem Haus schon zweimal passiert.
        self.datei = (
            pathlib.Path(__file__).resolve().parents[3]
            / "candyconc-web" / "src" / "components" / "copilot" / "ChatMessage.vue"
        )
        if not self.datei.is_file():
            raise AssertionError(f"Frontend-Bauteil fehlt: {self.datei}")

    def test_der_balken_haengt_am_gemeldeten_anteil(self):
        text = self.datei.read_text(encoding="utf-8")
        self.assertIn("streamFortschritt", text)
        self.assertIn("fortschritt", text)
        # Kein Feld, kein Balken.
        self.assertIn("return null", text)
        self.assertIn('v-if="streamFortschritt"', text)

    def test_er_ist_als_fortschrittsbalken_ausgezeichnet(self):
        """Ohne role/aria ist es ein Strich, kein Balken."""
        text = self.datei.read_text(encoding="utf-8")
        self.assertIn('role="progressbar"', text)
        self.assertIn("aria-valuenow", text)


if __name__ == "__main__":
    unittest.main()
