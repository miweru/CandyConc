"""Counts disclose annotation components excluded by exact query semantics.

A lemma value such as Recht|Rechte contains components that an exact
query for Recht does not count. Keep CQP matching semantics unchanged
and report the excluded component values alongside the count."""

from __future__ import annotations

import unittest

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

# conftest.py schiebt fuer BEIDE Importpfade ein Attrappen-``tool_wrappers``
# in ``sys.modules``. Ein direkter Import traefe die Attrappe, nicht die
# Naht, die im Betrieb laeuft.
_TW = _load_real_tool_wrappers()
_EINE_WERTBEDINGUNG = _TW._EINE_WERTBEDINGUNG
_verbundtypen_hinweis = _TW._verbundtypen_hinweis


class DieAbfrageformWirdEngGefasst(unittest.TestCase):
    """Nur eine einzelne Wertbedingung ist eine Wertfrage."""

    ERKANNT = (
        ('[lemma="Recht"]', "lemma", "Recht"),
        ('cql:[lemma="Recht"]', "lemma", "Recht"),
        ('[word="Haus"]', "word", "Haus"),
        ('[pos="NOUN"]', "pos", "NOUN"),
        ('[morph="ADV"]', "morph", "ADV"),
        ('  [ lemma = "Recht" ]  ', "lemma", "Recht"),
    )

    ABGELEHNT = (
        '[lemma="Recht"] [pos="NOUN"]',       # Sequenz
        '[lemma="Recht" & pos="NOUN"]',       # Verbund
        '[lemma!="Recht"]',                   # Negation
        '[lemma~"Recht"]',                    # anderer Operator
        '[unbekannt="Recht"]',                # fremdes Attribut
        'Recht',                              # Klartext, kein Attribut
        '[lemma="Recht"] within s',
        '',
    )

    def test_die_einfache_form_wird_erkannt(self):
        for text, attr, wert in self.ERKANNT:
            with self.subTest(text):
                t = _EINE_WERTBEDINGUNG.match(text)
                self.assertIsNotNone(t, text)
                self.assertEqual(t.group("attr"), attr)
                self.assertEqual(t.group("wert"), wert)

    def test_alles_andere_faellt_durch(self):
        """Positive Klasse: sonst waere ein Muster, das alles frisst, gruen."""
        for text in self.ABGELEHNT:
            with self.subTest(text):
                self.assertIsNone(_EINE_WERTBEDINGUNG.match(text), text)


class MusterSindKeineWertfrage(unittest.TestCase):
    """Ein Wert mit Metazeichen ist ein Muster, keine Frage nach einem Wert."""

    def test_muster_liefern_keinen_hinweis(self):
        for text in ('[lemma=".*flucht.*"]', '[lemma="Recht|Rechte"]',
                     '[lemma="Rech?t"]', '[lemma="Dr."]'):
            with self.subTest(text):
                self.assertEqual(_verbundtypen_hinweis(object(), text), {})

    def test_ein_kaputter_index_stuerzt_die_zaehlung_nicht(self):
        """Die Angabe ist eine Zugabe und darf nie die Zahl kosten."""
        class _Kaputt:
            @property
            def fast_index(self):
                raise RuntimeError("Index weg")

        self.assertEqual(_verbundtypen_hinweis(_Kaputt(), '[lemma="Recht"]'), {})


if __name__ == "__main__":
    unittest.main()
