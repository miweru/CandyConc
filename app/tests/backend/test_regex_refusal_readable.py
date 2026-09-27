"""Oversized regex and wildcard errors report their size as input errors.

The message must help users narrow the pattern, and both matching paths
must return an input error rather than an internal server failure."""

from __future__ import annotations

import unittest

from candyconc.services.backend import server as srv
from cqlhpc.predicates import regex_zu_gross


class DieAbsageNenntDieGroessenordnung(unittest.TestCase):
    def test_sie_nennt_gemessen_grenze_und_faktor(self):
        text = str(regex_zu_gross(
            gemessen=83_056_089, grenze=5_000_000,
            dimension="Tokens", muster=".*e.*",
        ))
        self.assertIn("83.056.089", text)
        self.assertIn("5.000.000", text)
        self.assertIn("16,6-fach", text)
        self.assertIn(".*e.*", text)

    def test_sie_unterscheidet_tokens_von_typen(self):
        tok = str(regex_zu_gross(gemessen=9, grenze=5, dimension="Tokens"))
        typ = str(regex_zu_gross(gemessen=9, grenze=5, dimension="Typen"))
        self.assertIn("Tokens", tok)
        self.assertIn("Typen", typ)
        self.assertNotIn("Typen", tok)

    def test_ohne_muster_bleibt_sie_lesbar(self):
        text = str(regex_zu_gross(gemessen=9, grenze=5, dimension="Tokens"))
        self.assertNotIn("''", text)
        self.assertTrue(text.startswith("Regex Treffer zu gross:"), text)

    def test_der_teilstring_der_klassifikation_bleibt_erhalten(self):
        """Die Routen pruefen auf diesen Text. Er darf nicht wegfallen."""
        text = str(regex_zu_gross(
            gemessen=9, grenze=5, dimension="Tokens", muster="x"
        ))
        self.assertIn("Regex Treffer zu gross", text)
        self.assertTrue(srv._is_query_user_error(text))


class WildcardIstAuchEinEingabefehler(unittest.TestCase):
    """Der aeltere Defekt: 500 statt 400 bei zu weiter Wildcard."""

    def test_die_wildcard_absage_gilt_als_eingabefehler(self):
        text = str(regex_zu_gross(
            gemessen=9_000_000, grenze=5_000_000,
            dimension="Tokens", muster="*e*", art="Wildcard",
        ))
        self.assertIn("Wildcard Treffer zu gross", text)
        self.assertTrue(
            srv._is_query_user_error(text),
            "zu weite Wildcard kommt als Serverfehler zurueck: %r" % text,
        )

    def test_auch_der_alte_wortlaut_wird_erkannt(self):
        """Aeltere Aufrufer und gespeicherte Meldungen bleiben gedeckt."""
        self.assertTrue(srv._is_query_user_error(
            "Wildcard Treffer zu gross. Bitte Suchmuster einschraenken."
        ))

    def test_ein_echter_serverfehler_bleibt_ein_serverfehler(self):
        """Positive Klasse: die Klassifikation sagt nicht zu allem ja."""
        self.assertFalse(srv._is_query_user_error(
            "Lexikon fehlt für word. Bitte Index neu bauen."
        ))


if __name__ == "__main__":
    unittest.main()
