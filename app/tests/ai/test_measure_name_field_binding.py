"""A measure name in prose must identify the corresponding evidence field.

A valid number can still be attributed to the wrong measure. Report a
binding error only when the value belongs to another field of the same
evidence item. Keep the answer text intact and report the mismatch through
annotations.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import recipe_runtime as rr  # noqa: E402

#: Ein Kontrastposten, wie ihn ngrams_diff/keyness liefern: log_ratio und
#: diff_per_million stehen SAUBER GETRENNT nebeneinander. Genau das machte
#: den Defekt unsichtbar, denn beide Zahlen sind echt.
POSTEN = [
    {
        "grounding_surface": [
            "word=Vertreibung",
            "log_ratio=5.38",
            "diff_per_million=-2345.3",
            "observed=44",
            "logdice=7.12",
        ]
    }
]


class DieVierB16FormulierungenFeuern(unittest.TestCase):
    """Prosa UND Zuweisung. Die Vorfassung fing nur die Zuweisungsform."""

    FAELLE = (
        "Das Token kommt 44-mal vor (log_ratio -2345,3 pmw).",
        "Der log_ratio betraegt -2345,3.",
        "log_ratio=-2345,3",
        "log_ratio: -2345,3",
    )

    def test_alle_vier(self):
        for text in self.FAELLE:
            befunde = rr.massname_an_feld_gebunden(text, POSTEN)
            self.assertTrue(befunde, text)

    def test_die_meldung_nennt_das_richtige_feld(self):
        """Kein Verdacht ohne Nachweis: die Herkunft steht in der Meldung."""
        befund = rr.massname_an_feld_gebunden(self.FAELLE[0], POSTEN)[0]
        self.assertIn("diff_per_million", befund)
        self.assertIn("nicht unter log_ratio", befund)


class KeinFehlalarm(unittest.TestCase):
    """Die Gatterung, die die Praezision traegt."""

    def test_die_richtige_bindung_bleibt_still(self):
        self.assertEqual(
            rr.massname_an_feld_gebunden(
                "Der log_ratio betraegt 5,38.", POSTEN
            ),
            [],
        )
        self.assertEqual(
            rr.massname_an_feld_gebunden("logDice liegt bei 7.12.", POSTEN), []
        )

    def test_eine_zahl_aus_KEINEM_feld_bleibt_still(self):
        """Zustaendig ist dann die Zahlenanker-Wache, nicht diese."""
        self.assertEqual(
            rr.massname_an_feld_gebunden("(log_ratio 1234,5)", POSTEN), []
        )

    def test_eine_schwellenangabe_bleibt_still(self):
        self.assertEqual(
            rr.massname_an_feld_gebunden(
                "Die Assoziation ist mit logDice ueber 7 stark.", POSTEN
            ),
            [],
        )

    def test_ohne_evidenz_kein_befund(self):
        self.assertEqual(
            rr.massname_an_feld_gebunden("log_ratio -2345,3", []), []
        )

    def test_die_vertauschung_faellt_in_beide_richtungen_auf(self):
        befund = rr.massname_an_feld_gebunden("logDice liegt bei 5.38.", POSTEN)
        self.assertTrue(befund)
        self.assertIn("steht unter log_ratio", befund[0])


class ZahlenSchreibweisen(unittest.TestCase):
    def test_deutsches_komma_und_englischer_punkt(self):
        for schreibweise in ("-2345,3", "-2345.3"):
            self.assertTrue(
                rr.massname_an_feld_gebunden(
                    f"log_ratio {schreibweise}", POSTEN
                ),
                schreibweise,
            )

    def test_tausendertrennung(self):
        posten = [{"grounding_surface": ["total=460712", "per_million=9790.1"]}]
        self.assertTrue(
            rr.massname_an_feld_gebunden("pmw 460.712", posten)
        )
        self.assertEqual(
            rr.massname_an_feld_gebunden("pmw 9790,1", posten), []
        )


class DerKanalIstNichtZerstoerend(unittest.TestCase):
    """Der zweite Streichungsgrund, eigens repariert."""

    def test_die_wache_faesst_den_text_nicht_an(self):
        text = "Der log_ratio betraegt -2345,3."
        poliert, annotationen = rr.politur_mit_zitatwache(text, POSTEN)
        self.assertIn("-2345,3", poliert)
        # Annotationen sind ABBILDUNGEN, nicht Zeichenketten.
        self.assertTrue(
            any(a.get("claim_id") == "massname_zeigt_auf_fremdes_feld"
                for a in annotationen),
            str(annotationen),
        )

    def test_kontextlokal_statt_global_streichen(self):
        """Ein pmw-Paarbefund darf die korrekte Nennung nicht mitloeschen.

        Bei 10.034.000 Tokens ist '30 Treffer (498.3 pmw)' arithmetisch
        falsch und '5000 Treffer (498.3 pmw)' korrekt. Der Befund nennt nur
        das erste Fragment.
        """
        text = (
            "Fluechtlinge: 30 Treffer (498.3 pmw). "
            "Migranten: 5000 Treffer (498.3 pmw)."
        )
        befund = [{
            "number": "498.3",
            "context": "30 Treffer (498.3 pmw)",
            "reason": "pmw_inconsistent_with_count",
        }]
        ergebnis = rr.strike_unbound_numbers(text, befund, annotate=False)
        self.assertEqual(ergebnis.count("498.3"), 1)
        self.assertIn("5000 Treffer (498.3 pmw)", ergebnis)
        self.assertIn("30 Treffer ([Beleg fehlt] pmw)", ergebnis)

    def test_ohne_kontext_bleibt_es_global(self):
        """Ein Befund ohne Kontext meint die Zahl selbst, nicht ein Paar."""
        text = "a 498.3 und b 498.3"
        ergebnis = rr.strike_unbound_numbers(
            text, [{"number": "498.3"}], annotate=False
        )
        self.assertNotIn("498.3", ergebnis)

class DerKontextWirdLEERRAUMTOLERANT_gesucht(unittest.TestCase):
    """Blockierender Befund der dritten Runde, mein eigener Rueckschritt.

    ``grounding_refs`` baut den Kontext leerraum-NORMALISIERT
    (``" ".join(real[start-48:end+48].split())``), die Vorfassung suchte
    ihn WOERTLICH. Sobald der Antworttext an der Stelle einen
    Zeilenumbruch hatte, fand sie nichts und strich GAR NICHTS. Aus einer
    zu breiten Ersetzung war eine wirkungslose geworden -- schlechter als
    der Zustand davor, denn die unbelegte Zahl blieb stehen.
    """

    BEFUND = [{"number": "498.3", "context": "30 Treffer (498.3 pmw)"}]

    def test_zeilenumbruch_im_text_verhindert_die_ersetzung_nicht(self):
        text = ("Fluechtlinge: 30 Treffer\n(498.3 pmw). "
                "Migranten: 5000 Treffer (498.3 pmw).")
        erg = rr.strike_unbound_numbers(text, self.BEFUND, annotate=False)
        self.assertIn("[Beleg fehlt] pmw). Migranten", erg)
        self.assertIn("5000 Treffer (498.3 pmw)", erg, "die belegte Nennung")

    def test_mehrfache_leerzeichen_ebenso(self):
        text = "Fluechtlinge: 30   Treffer  (498.3 pmw). B: 5000 (498.3 pmw)."
        erg = rr.strike_unbound_numbers(text, self.BEFUND, annotate=False)
        self.assertEqual(erg.count("498.3"), 1)

    def test_mehrdeutiger_kontext_wird_NICHT_gestrichen(self):
        """Lieber eine unbelegte Zahl stehen lassen als eine belegte
        loeschen: kommt der Kontext zweimal vor, ist unklar, welche
        Stelle der Befund meint."""
        text = "A: 30 Treffer (498.3 pmw). B: 30 Treffer (498.3 pmw)."
        self.assertEqual(
            rr.strike_unbound_numbers(text, self.BEFUND, annotate=False), text
        )

    def test_nicht_auffindbarer_kontext_ebenfalls_nicht(self):
        self.assertEqual(
            rr.strike_unbound_numbers(
                "x 498.3 y", [{"number": "498.3", "context": "gibt es nicht"}],
                annotate=False,
            ),
            "x 498.3 y",
        )


class DerMeldekanalLiefertABBILDUNGEN(unittest.TestCase):
    """``final_polish_event`` nimmt ``Sequence[Mapping]``, und
    ``final_answer_polish`` liefert ``{"claim_id", "note"}``.

    Die Zitatwache hat hier von Anfang an einen nackten String angehaengt,
    und die Massnamen-Bindung hat den Fehler vergroessert statt ihn zu
    bemerken. Ein Verbraucher, der ``eintrag["note"]`` liest, bekommt bei
    einem String einen TypeError oder still gar nichts.
    """

    def test_jede_annotation_ist_eine_abbildung(self):
        _text, ann = rr.politur_mit_zitatwache(
            "Der log_ratio betraegt -2345,3.", POSTEN
        )
        self.assertTrue(ann, "die Wache hat gar nicht gemeldet")
        for eintrag in ann:
            self.assertIsInstance(eintrag, dict)
            self.assertIn("claim_id", eintrag)
            self.assertIn("note", eintrag)

    def test_das_ereignis_baut_ohne_fehler(self):
        _text, ann = rr.politur_mit_zitatwache(
            "Der log_ratio betraegt -2345,3.", POSTEN
        )
        ereignis = rr.final_polish_event("kontrast", ann)
        self.assertIsInstance(ereignis, dict)

    def test_auch_die_zitatwache_meldet_als_abbildung(self):
        posten = [{"grounding_surface": ["word=Flucht"]}]
        text = 'Er sagte „ein vollstaendig erfundenes Zitat ohne Deckung".'
        _t, ann = rr.politur_mit_zitatwache(text, posten)
        for eintrag in ann:
            self.assertIsInstance(eintrag, dict, str(ann))

if __name__ == "__main__":
    unittest.main()


class DieMeldungErreichtDieAntwort(unittest.TestCase):
    """P3 (Runde 2): die Wache meldete nur in den Evidenzstrom — die
    Leserin sah zwei Fremdfeld-Zahlen unmarkiert (diachronie-3)."""

    def test_erste_fehlbindung_steht_am_antwortende(self):
        text = ("Die Gegenueberstellung faellt auf: das Token kommt 44-mal "
                "vor (log_ratio -2345,3 pmw).")
        poliert, annotationen = rr.politur_mit_zitatwache(text, POSTEN)
        self.assertIn("Hinweis: ", poliert)
        self.assertIn("diff_per_million", poliert)
        ids = {a.get("claim_id") for a in annotationen}
        self.assertIn("massname_zeigt_auf_fremdes_feld", ids)

    def test_ohne_fehlbindung_keine_zeile(self):
        text = "Der Befund bleibt bei log_ratio 5,38 wie gemessen."
        poliert, _ = rr.politur_mit_zitatwache(text, POSTEN)
        self.assertNotIn("Hinweis: ", poliert)
