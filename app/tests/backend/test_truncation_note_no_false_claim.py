"""Der Harness darf nicht falsch ueber seinen eigenen Lauf reden.

Zwei Saetze aus dem Livelauf vom 2026-08-29, Frage "Untersuche den
Gebrauch von 'Frau' anhand von Konkordanzzeilen", beide nachweislich
falsch, beide deterministisch erzeugt:

1.  "Grenzen: Die zitierten Zeilen sind ein gekappter Ausschnitt (limit)"

    Das Werkzeug lieferte mit ``limit=50`` ALLE 37 Trefferzeilen,
    ``truncated`` war False. Gekappt hatte nicht das Werkzeug, sondern der
    Turn. Der Steckbrief derselben Antwort sagte es korrekt ("alle als
    Ergebniszeilen zurueckgegeben") und widersprach damit dem Fliesstext
    zwei Absaetze weiter oben.

2.  "Hinweis: Ein Engine-Fehler hat die Analyse unterbrochen"

    Das Laufprotokoll nennt "Der LLM-Endpunkt hat nicht rechtzeitig
    geantwortet". Die Korpusabfrage lief in 8,5 Millisekunden
    vollstaendig durch. Die Antwort schob ein Modellproblem auf die
    Datenschicht. Fuer die Leserin ist das die schaedlichste
    Fehlzuweisung, die es hier gibt: sie beginnt den Zahlen zu
    misstrauen, waehrend genau die Zahlen funktioniert haben.
"""

from __future__ import annotations

import unittest

from candyconc.candyconc_copilot.death_landings import _kwic_death_report
from candyconc.services.backend import server
from candyconc.services.backend.server import (
    _SALVAGE_ENGINE_ERROR_NOTE,
    _SALVAGE_MODELL_TIMEOUT_NOTE,
    _salvage_abbruch_hinweis,
)

ZEILEN = [f"links {i} Frau rechts {i}" for i in range(20)]


class TestKeineErfundeneKappung(unittest.TestCase):
    def test_ohne_kappung_wird_keine_behauptet(self):
        text = _kwic_death_report(
            query_term="Frau", total_hits=20, rows_seen=20, examples=ZEILEN
        )
        self.assertNotIn("gekappt", text)
        self.assertNotIn("(limit)", text)

    def test_der_gemessene_fall_nennt_beide_zahlen_ohne_kappungsbehauptung(self):
        # 37 Treffer, 20 davon ausgewertet: DAS ist wahr und steht da.
        text = _kwic_death_report(
            query_term="Frau", total_hits=37, rows_seen=37, examples=ZEILEN
        )
        self.assertNotIn("gekappt", text)
        self.assertNotIn("(limit)", text)
        self.assertIn("37", text)
        self.assertIn("20 Belegzeilen", text)
        self.assertIn("nicht auf allen 37 Treffern", text)

    def test_ohne_gesamtzahl_wird_die_offenheit_benannt(self):
        text = _kwic_death_report(
            query_term="Frau", total_hits=None, rows_seen=None, examples=ZEILEN
        )
        self.assertIn("Gesamttrefferzahl liegt nicht vor", text)
        self.assertNotIn("gekappt", text)


class TestDerGrundWirdBenanntNichtGeraten(unittest.TestCase):
    def test_modell_timeout_belastet_nicht_die_engine(self):
        hinweis = _salvage_abbruch_hinweis(
            "Der LLM-Endpunkt hat nicht rechtzeitig geantwortet."
        )
        self.assertEqual(hinweis, _SALVAGE_MODELL_TIMEOUT_NOTE)
        self.assertNotIn("Engine-Fehler", hinweis)
        # Und der Satz entlastet die Zahlen ausdruecklich, denn sie sind
        # das einzige, was in diesem Fall funktioniert hat.
        self.assertIn("Korpusabfragen", hinweis)

    def test_zeitlimit_wortlaut_ebenfalls(self):
        for text in (
            "Copilot-Zeitlimit (135s) überschritten",
            "ReadTimeout",
            "Strom ueberschritt das Per-Call-Limit (100s)",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    _salvage_abbruch_hinweis(text), _SALVAGE_MODELL_TIMEOUT_NOTE
                )

    def test_ein_echter_engine_ausfall_behaelt_seinen_satz(self):
        # POSITIVE KLASSE. Ohne sie waere ein Klassifikator gruen, der
        # ALLES als Modellproblem meldet und einen echten Engine-Ausfall
        # verharmlost. Eine falsche Entwarnung ist schlimmer als eine zu
        # vorsichtige Meldung.
        for text in (
            "Index nicht erreichbar",
            "RuntimeError: Bitte Index neu bauen",
            None,
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    _salvage_abbruch_hinweis(text), _SALVAGE_ENGINE_ERROR_NOTE
                )


if __name__ == "__main__":
    unittest.main()


class TestEinGescheitertesWerkzeugIstKeineBergung(unittest.TestCase):
    """Raw tool-error JSON must not become the user-facing answer."""

    def _salvage(self, tool_result):
        return server._copilot_timeout_salvage_text(
            "", tool_result, object(), timed_out=True, annotate=False
        )

    def test_ein_fehlerergebnis_wird_nicht_ausgeliefert(self):
        for status in ("error", "failed", "FAILURE"):
            with self.subTest(status=status):
                text = self._salvage(
                    {
                        "toolName": "keyness",
                        "output": {"status": status, "message": "kaputt"},
                    }
                )
                self.assertIsNone(text, text)

    def test_ein_erfolgreiches_ergebnis_wird_weiterhin_geborgen(self):
        # POSITIVE KLASSE. Ohne sie waere ein Filter gruen, der JEDES
        # Werkzeugergebnis verwirft und damit die Bergung abschaltet.
        text = self._salvage(
            {
                "toolName": "query_count",
                "output": {"status": "success", "total": 103},
            }
        )
        self.assertIsNotNone(text)
        self.assertIn("103", text)
