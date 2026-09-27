"""Convert compact CWB output to VRT with structural attributes.

CWB emits separate attribute tags and nested attribute lists. The importer
expects one segment tag containing the combined XML attributes."""

from __future__ import annotations

import importlib
import io
import unittest
from pathlib import Path

#: The converter ships in the package, scripts/jobs/cwb_decode_to_vrt.py is a
#: thin entry point to it.
SKRIPT = (
    Path(__file__).resolve().parents[2] / "src" / "candyconc" / "ingest" / "cwb_decode_to_vrt.py"
)


def _modul():
    return importlib.import_module("candyconc.ingest.cwb_decode_to_vrt")


def _wandle(text, **kwargs):
    m = _modul()
    aus = io.StringIO()
    zahlen = m.konvertiere(io.StringIO(text), aus, **kwargs)
    return aus.getvalue(), zahlen


@unittest.skipUnless(SKRIPT.exists(), f"{SKRIPT} fehlt")
class KonverterKern(unittest.TestCase):
    # Synthetic compact CWB sample with nested attributes.
    SYNTHETIC_CWB = (
        "<protocol_lp 19>\n"
        "<protocol_date 2018-05-16>\n"
        '<speaker who="Muster" name="Erika Muster" parlgroup="Party A" '
        'party="Party A" role="mp">\n'
        "<s>\n"
        "Wir\twir\tPRON\tPPER\n"
        "sind\tsein\tAUX\tVAFIN\n"
        "</s>\n"
        "</speaker>\n"
        "</protocol_date>\n"
        "</protocol_lp>\n"
    )

    def test_unterattribute_werden_ausgepackt(self):
        aus, _ = _wandle(self.SYNTHETIC_CWB, segment="speaker")
        kopf = aus.splitlines()[0]
        self.assertIn('speaker_party="Party A"', kopf)
        self.assertIn('speaker_role="mp"', kopf)
        self.assertIn('speaker_name="Erika Muster"', kopf)

    def test_aeussere_attribute_landen_auf_dem_segment(self):
        """protocol_* umschliesst viele Reden und gilt fuer jede darin."""
        aus, _ = _wandle(self.SYNTHETIC_CWB, segment="speaker")
        kopf = aus.splitlines()[0]
        self.assertIn('protocol_lp="19"', kopf)
        self.assertIn('protocol_date="2018-05-16"', kopf)

    def test_tokens_und_saetze_bleiben_unveraendert(self):
        aus, zahlen = _wandle(self.SYNTHETIC_CWB, segment="speaker")
        self.assertIn("Wir\twir\tPRON\tPPER", aus)
        self.assertEqual(zahlen["tokens"], 2)
        self.assertEqual(zahlen["saetze"], 1)
        self.assertEqual(zahlen["segmente"], 1)

    def test_jedes_segment_bekommt_seinen_eigenen_wert(self):
        text = (
            "<protocol_lp 19>\n"
            '<speaker party="Party A">\n<s>\nA\ta\tX\tY\n</s>\n</speaker>\n'
            '<speaker party="Party B">\n<s>\nB\tb\tX\tY\n</s>\n</speaker>\n'
            "</protocol_lp>\n"
        )
        aus, zahlen = _wandle(text, segment="speaker")
        koepfe = [z for z in aus.splitlines() if z.startswith("<speaker")]
        self.assertEqual(len(koepfe), 2)
        self.assertIn('speaker_party="Party A"', koepfe[0])
        self.assertIn('speaker_party="Party B"', koepfe[1])
        self.assertEqual(zahlen["segmente"], 2)


@unittest.skipUnless(SKRIPT.exists(), f"{SKRIPT} fehlt")
class VerlustIstLaut(unittest.TestCase):
    def test_tokens_ausserhalb_werden_gezaehlt(self):
        text = (
            "<protocol_lp 19>\n"
            "Waise\twaise\tNOUN\tNN\n"
            '<speaker party="Party A">\n<s>\nA\ta\tX\tY\n</s>\n</speaker>\n'
            "</protocol_lp>\n"
        )
        _aus, zahlen = _wandle(text, segment="speaker")
        self.assertEqual(zahlen["tokens_ausserhalb"], 1)
        self.assertEqual(zahlen["tokens"], 1)


@unittest.skipUnless(SKRIPT.exists(), f"{SKRIPT} fehlt")
class Unterattribute(unittest.TestCase):
    def test_reine_attributliste_wird_aufgeloest(self):
        m = _modul()
        self.assertEqual(
            m._unterattribute('who="Sample" party="Party C"'),
            {"who": "Sample", "party": "Party C"},
        )

    def test_freitext_bleibt_freitext(self):
        """Ein Wert, der kein Attributpaar ist, darf nicht zerlegt werden."""
        m = _modul()
        self.assertEqual(m._unterattribute("Rede zum Haushalt"), {})
        self.assertEqual(m._unterattribute("Party C"), {})

    def test_gemischter_wert_wird_nicht_halb_zerlegt(self):
        m = _modul()
        self.assertEqual(m._unterattribute('Vorwort who="Sample"'), {})

    def test_freitextwert_landet_als_value_attribut(self):
        aus, _ = _wandle(
            "<speaker Praesident>\n<s>\nA\ta\tX\tY\n</s>\n</speaker>\n",
            segment="speaker",
        )
        self.assertIn('speaker_value="Praesident"', aus.splitlines()[0])


@unittest.skipUnless(SKRIPT.exists(), f"{SKRIPT} fehlt")
class AttributNachSegment(unittest.TestCase):
    """Include attributes opening after the segment tag but before its first token.

CWB orders structural tags by the requested -S flags. Delay writing the
segment tag so either flag order preserves all attributes."""

    NACHZUEGLER = (
        "<protocol_date 1949-09-07>\n"
        "<speaker Alex Sample>\n"
        "<speaker_party Party C>\n"
        "<s>\nWir\twir\tPRON\tPPER\n</s>\n"
        "</speaker_party>\n</speaker>\n</protocol_date>\n"
    )

    def test_spaeter_oeffnendes_attribut_geht_mit(self):
        aus, _ = _wandle(self.NACHZUEGLER, segment="speaker")
        kopf = aus.splitlines()[0]
        self.assertIn('speaker_party="Party C"', kopf)
        self.assertIn('protocol_date="1949-09-07"', kopf)

    def test_beide_flag_reihenfolgen_liefern_dasselbe(self):
        vorher = (
            "<protocol_date 1949-09-07>\n"
            "<speaker_party Party C>\n<speaker Alex Sample>\n"
            "<s>\nWir\twir\tPRON\tPPER\n</s>\n"
            "</speaker>\n</speaker_party>\n</protocol_date>\n"
        )
        a, _ = _wandle(self.NACHZUEGLER, segment="speaker")
        b, _ = _wandle(vorher, segment="speaker")
        self.assertEqual(a.splitlines()[0], b.splitlines()[0])

    def test_token_und_satz_bleiben_in_ordnung(self):
        aus, zahlen = _wandle(self.NACHZUEGLER, segment="speaker")
        zeilen = aus.splitlines()
        self.assertTrue(zeilen[0].startswith("<speaker "))
        self.assertEqual(zeilen[1], "<s>")
        self.assertEqual(zeilen[2], "Wir\twir\tPRON\tPPER")
        self.assertEqual(zeilen[3], "</s>")
        self.assertEqual(zeilen[4], "</speaker>")
        self.assertEqual(zahlen["tokens"], 1)
        self.assertEqual(zahlen["saetze"], 1)

    def test_wirklich_zu_spaetes_attribut_wird_gezaehlt(self):
        """Nach dem ersten Token gilt es fuer dieses Segment nicht mehr."""
        text = (
            "<speaker A>\n<s>\nWir\twir\tPRON\tPPER\n</s>\n"
            "<nachzuegler X>\n</speaker>\n"
        )
        aus, zahlen = _wandle(text, segment="speaker")
        self.assertNotIn("nachzuegler", aus.splitlines()[0])
        self.assertEqual(zahlen["attribute_zu_spaet"], 1)


if __name__ == "__main__":
    unittest.main()
