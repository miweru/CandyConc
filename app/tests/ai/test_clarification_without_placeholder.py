"""Clarification questions must resolve their references.

A missing-evidence placeholder may describe a gap in an answer, but makes
a clarification question ambiguous even when other words remain."""

from __future__ import annotations

import unittest

from candyconc.candyconc_copilot.grounding_refs import MISSING_EVIDENCE_PLACEHOLDER
from candyconc.candyconc_copilot.recipe_runtime import _rueckfrage_bewacht_anhaengen


ANTWORT = "Die Wahlperiode 10 umfasst 65116 Dokumente."


class RueckfrageMitPlatzhalterEntfaellt(unittest.TestCase):
    def test_der_fall_aus_dem_messlauf(self):
        frage = (
            "Soll %s nach Anzahl der Reden pro Wahlperiode im Subkorpus "
            "protocol_lp gezaehlt werden?" % MISSING_EVIDENCE_PLACEHOLDER
        )
        text, notizen = _rueckfrage_bewacht_anhaengen(ANTWORT, frage, [])
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, text)
        self.assertEqual(text, ANTWORT, "die Antwort selbst wurde veraendert")
        self.assertTrue(
            any(n.get("claim_id") == "rueckfrage_platzhalter" for n in notizen),
            "der Verzicht ist nicht annotiert: %r" % notizen,
        )

    def test_auch_wenn_der_platzhalter_am_ende_steht(self):
        frage = "Soll nach Reden oder nach Tokens gezaehlt werden, %s?" % (
            MISSING_EVIDENCE_PLACEHOLDER,
        )
        text, _n = _rueckfrage_bewacht_anhaengen(ANTWORT, frage, [])
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, text)

    def test_mehrere_platzhalter(self):
        frage = "Soll %s oder %s gezaehlt werden?" % (
            MISSING_EVIDENCE_PLACEHOLDER,
            MISSING_EVIDENCE_PLACEHOLDER,
        )
        text, _n = _rueckfrage_bewacht_anhaengen(ANTWORT, frage, [])
        self.assertNotIn(MISSING_EVIDENCE_PLACEHOLDER, text)


class SaubereRueckfragenUeberlebenWeiterhin(unittest.TestCase):
    """Positive Klasse: eine Wache, die alles verwirft, waere kaputt.

    Ohne diese Faelle waere ein ``sauber = ""`` ohne jede Bedingung gruen.
    """

    def test_eine_frage_ohne_platzhalter_bleibt_stehen(self):
        frage = "Soll nach Reden oder nach Tokens gezaehlt werden?"
        text, notizen = _rueckfrage_bewacht_anhaengen(ANTWORT, frage, [])
        self.assertIn("Reden oder nach Tokens", text)
        self.assertNotEqual(text, ANTWORT, "die Rueckfrage wurde verschluckt")
        self.assertFalse(
            any(n.get("claim_id") == "rueckfrage_platzhalter" for n in notizen)
        )

    def test_eine_frage_mit_eckigen_klammern_ohne_platzhalter_bleibt(self):
        """Nicht jede eckige Klammer ist ein Platzhalter."""
        frage = "Soll das Feld [protocol_lp] oder [protocol_year] gelten?"
        text, _n = _rueckfrage_bewacht_anhaengen(ANTWORT, frage, [])
        self.assertIn("protocol_lp", text)

    def test_leere_rueckfrage_aendert_nichts(self):
        text, notizen = _rueckfrage_bewacht_anhaengen(ANTWORT, "", [])
        self.assertEqual(text, ANTWORT)
        self.assertEqual(notizen, [])

    def test_die_wache_unterscheidet_ueberhaupt(self):
        """Kontrollmessung gegen eine Wache mit nur einer Antwort."""
        mit = _rueckfrage_bewacht_anhaengen(
            ANTWORT, "Soll %s gelten?" % MISSING_EVIDENCE_PLACEHOLDER, []
        )[0]
        ohne = _rueckfrage_bewacht_anhaengen(
            ANTWORT, "Soll das Feld protocol_lp gelten?", []
        )[0]
        self.assertEqual(mit, ANTWORT)
        self.assertNotEqual(ohne, ANTWORT)


if __name__ == "__main__":
    unittest.main()
