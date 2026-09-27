"""A rejected punctuation pattern explains the literal-symbol form."""

from __future__ import annotations

import unittest

from candyconc.services.backend import server as srv
from cqlhpc.predicates import regex_zu_gross


def _text(muster: str, art: str = "Regex") -> str:
    return str(regex_zu_gross(gemessen=24_524_006, grenze=5_000_000,
                              dimension="Tokens", muster=muster, art=art))


class DerPunktSelbst(unittest.TestCase):
    def test_die_absage_nennt_die_woertliche_form(self):
        text = _text(".")
        self.assertIn('[word="\\."]', text)
        self.assertIn("beliebiges Zeichen", text)

    def test_mehrere_satzzeichen_werden_alle_maskiert(self):
        self.assertIn('[word="\\.\\.\\."]', _text("..."))

    def test_ein_gewolltes_regex_mit_buchstaben_bekommt_keinen_hinweis(self):
        self.assertNotIn("beliebiges Zeichen", _text(".*e.*"))

    def test_ein_maskierter_punkt_bekommt_keinen_hinweis(self):
        self.assertNotIn("beliebiges Zeichen", _text("\\."))

    def test_die_wildcard_absage_bleibt_ohne_regex_hinweis(self):
        self.assertNotIn("beliebiges Zeichen", _text(".", art="Wildcard"))

    def test_die_absage_bleibt_ein_eingabefehler(self):
        text = _text(".")
        self.assertTrue(text.startswith("Regex Treffer zu gross"), text)
        self.assertTrue(srv._is_query_user_error(text))
