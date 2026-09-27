"""Die Antwort steht, bevor die Gegenlesung durch ist.

Der Grund ist gemessen, nicht vermutet. Live am 2026-08-28, qwen3.8-27b
gegen den Testindex, eine einzelne Assoziationsfrage:

    t=   6.3s     5.4s  Rezeptwahl
    t=  53.7s    47.2s  Werkzeugrunde
    t= 101.7s    47.9s  Werkzeugrunde
    t= 140.8s    39.1s  Freitext-Entwurf, 316 Zeichen
    t= 491.5s   350.6s  answer_envelope
    t= 607.7s   116.2s  grounding_verdict
    t= 965.2s   357.5s  answer_envelope   (zweite Runde)
    t=1274.9s   309.7s  grounding_verdict (zweite Runde)
    t=1640.5s   365.7s  answer_envelope   (dritte Runde)

Der deterministisch gedeckte Text lag bei Minute zwei bereit. Angezeigt
wurde bis Minute siebenundzwanzig nichts. Die Verifikation kostet ein
Vielfaches der Antwort, die sie prueft, und ihr Retry-Budget wiederholt
beide Schritte.

WAS AUSGELIEFERT WIRD, IST KEIN ROHTEXT. Es ist derselbe Text, den der
Harness ausliefern wuerde, wenn im selben Moment die Zeit ausginge:
Referenzen aufgeloest, Zitate gegen die Evidenzzeilen geprueft, unbelegte
Zahlen gestrichen. Diese Wachen kosten null Modellaufrufe, lassen sich
nicht ueberspringen, und sie sind es, die die erfundenen Zitate frueherer
Laeufe gefangen haben.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.recipe_runtime import (  # noqa: E402
    VORLAEUFIG_HINWEIS,
    bodentext_statt_absage,
    vorlaeufige_antwort_senden,
)


class _Bus:
    def __init__(self) -> None:
        self.ereignisse: list = []

    def __call__(self, ereignis) -> None:
        self.ereignisse.append(ereignis)


class DasEreignisTraegtWasDieOberflaecheBraucht(unittest.TestCase):
    def test_text_und_zustand_werden_gesendet(self):
        bus = _Bus()
        zurueck = vorlaeufige_antwort_senden(bus, lambda: "Kernbefund: 805 Treffer.")
        self.assertEqual(zurueck, "Kernbefund: 805 Treffer.")
        self.assertEqual(len(bus.ereignisse), 1)
        e = bus.ereignisse[0]
        self.assertEqual(e["event"], "copilot.vorlaeufige_antwort")
        self.assertEqual(e["text"], "Kernbefund: 805 Treffer.")
        self.assertIs(e["geprueft"], False)
        self.assertEqual(e["hinweis"], VORLAEUFIG_HINWEIS)

    def test_der_hinweis_nennt_den_zustand_ohne_zu_warnen(self):
        # Der Text ist brauchbar, ihm fehlt die Gegenlesung. Ein Warnton
        # waere falsch: er ist durch die deterministischen Wachen gelaufen.
        self.assertIn("Vorläufig", VORLAEUFIG_HINWEIS)
        self.assertIn("Gegenlesung", VORLAEUFIG_HINWEIS)


class EineVorschauDarfDieAntwortNieKosten(unittest.TestCase):
    """Jeder Fehler hier bleibt folgenlos fuer den Turn."""

    def test_ein_werfender_textbauer_sendet_nichts_und_wirft_nicht(self):
        bus = _Bus()

        def _wirft():
            raise RuntimeError("Evidenz kaputt")

        self.assertEqual(vorlaeufige_antwort_senden(bus, _wirft), "")
        self.assertEqual(bus.ereignisse, [])

    def test_ein_werfender_kanal_wirft_nicht_weiter(self):
        def _sendet_nicht(_ereignis):
            raise RuntimeError("Bus tot")

        self.assertEqual(
            vorlaeufige_antwort_senden(_sendet_nicht, lambda: "Befund."), ""
        )

    def test_leerer_text_wird_nicht_gesendet(self):
        bus = _Bus()
        for leer in ("", "   ", "\n"):
            with self.subTest(leer=repr(leer)):
                self.assertEqual(vorlaeufige_antwort_senden(bus, lambda: leer), "")
        self.assertEqual(bus.ereignisse, [])

    def test_ein_nicht_string_wird_nicht_gesendet(self):
        bus = _Bus()
        self.assertEqual(vorlaeufige_antwort_senden(bus, lambda: None), "")
        self.assertEqual(vorlaeufige_antwort_senden(bus, lambda: 42), "")
        self.assertEqual(bus.ereignisse, [])


class SieBeendetNichts(unittest.TestCase):
    def test_kein_verdict_und_kein_abschluss_im_ereignis(self):
        # Die Verifikation laeuft unveraendert weiter. Ein Ereignis, das
        # wie ein Abschluss aussieht, wuerde die Oberflaeche stoppen.
        bus = _Bus()
        vorlaeufige_antwort_senden(bus, lambda: "Befund.")
        e = bus.ereignisse[0]
        for verboten in ("verdict", "done", "usage", "final"):
            self.assertNotIn(verboten, e)


class DerBodenStattDerAbsage(unittest.TestCase):
    """Ein Prinzip, das je nach erschoepfter Ressource gilt, ist keines.

    Der Verweigerungspfad lieferte bisher 234 Zeichen („liesz sich keine
    interpretative Endantwort verifizieren“), waehrend derselbe Entwurf bei
    erschoepfter ZEIT eine Ebene hoeher ohne Murren ausgeliefert wurde.

    Im live gemessenen Turn vom 2026-08-28 kostete dieser Zustand 65,3
    Minuten und 17 Modellaufrufe, davon 3775 Sekunden Verifikation, die in
    sieben Aufrufen KEINEN Claim abgelehnt hat. Der Entwurf lag nach 2,3
    Minuten vor.
    """

    def test_ohne_claim_und_ohne_faktenantwort_kommt_der_boden(self):
        self.assertEqual(
            bodentext_statt_absage([], False, lambda: "Kernbefund: 805 Treffer."),
            "Kernbefund: 805 Treffer.",
        )

    def test_mit_angenommenem_claim_bleibt_alles_beim_alten(self):
        # Dann traegt die verifizierte Modellantwort, der Boden hat nichts
        # zu suchen.
        self.assertEqual(
            bodentext_statt_absage(["c01"], False, lambda: "Boden."), ""
        )

    def test_bei_erlaubter_faktenantwort_bleibt_alles_beim_alten(self):
        self.assertEqual(
            bodentext_statt_absage([], True, lambda: "Boden."), ""
        )

    def test_ein_werfender_textbauer_kostet_die_antwort_nicht(self):
        def _wirft():
            raise RuntimeError("Evidenz kaputt")

        self.assertEqual(bodentext_statt_absage([], False, _wirft), "")

    def test_leerer_boden_faellt_auf_den_alten_pfad_zurueck(self):
        for leer in ("", "   ", None, 42):
            with self.subTest(leer=repr(leer)):
                self.assertEqual(
                    bodentext_statt_absage([], False, lambda: leer), ""
                )


class DerOrchestratorRuftSieVorDerVerifikation(unittest.TestCase):
    """Der Aufruf muss VOR ``in_verifier_phase`` stehen, sonst nuetzt er nichts."""

    QUELLE = (_SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py")

    def test_die_reihenfolge_im_quelltext_stimmt(self):
        quelle = self.QUELLE.read_text(encoding="utf-8")
        ruf = quelle.find("vorlaeufige_antwort_senden(\n")
        phase = quelle.find("turn_state.in_verifier_phase = True")
        self.assertGreater(ruf, 0, "Aufruf fehlt")
        self.assertGreater(phase, 0, "Verifier-Phase fehlt")
        self.assertLess(
            ruf, phase,
            "Die vorlaeufige Antwort muss VOR der Modellverifikation raus",
        )

    def test_sie_steht_vor_dem_zeittor(self):
        """Sonst feuert sie unter Produktivvorgabe nie.

        Das Tor schliesst bei 84 von 120 Sekunden
        (VERIFIER_MIN_TIME_FRACTION 0,3). Der live gemessene Entwurf war
        erst bei 140,8 s fertig. Eine Vorschau dahinter hilft genau dort
        nicht, wo es lange dauert. Die erste Fassung stand dahinter.
        """
        quelle = self.QUELLE.read_text(encoding="utf-8")
        ruf = quelle.find("vorlaeufige_antwort_senden(\n")
        tor = quelle.find("if not _budgets.verifier_time_remaining_ok(")
        self.assertGreater(ruf, 0, "Aufruf fehlt")
        self.assertGreater(tor, 0, "Zeittor fehlt")
        self.assertLess(ruf, tor, "Die Vorschau muss VOR dem Zeittor raus")

    def test_der_boden_haengt_am_verweigerungspfad(self):
        quelle = self.QUELLE.read_text(encoding="utf-8")
        self.assertIn("bodentext_statt_absage(", quelle)


if __name__ == "__main__":
    unittest.main()
