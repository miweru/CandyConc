"""Deferred clarification questions pass through the quote guard."""

from __future__ import annotations

import unittest

from candyconc.candyconc_copilot import recipe_runtime as rr

# Genau das Fabrikat aus der Kampagne, das in DREI unabhaengigen Laeufen
# derselben Frage auftrat. Die Einzelwoerter stehen im Korpus, die Phrase
# nie.
_FABRIKAT = (
    "der jungen Maenner sind keine Fluechtlinge. "
    "Sie sind ruecksichtslose Invasoren."
)

_EVIDENZ = [
    # `tool` produktivtreu: orchestrator.py:6989 setzt es immer, und die
    # Wache entscheidet nach HERKUNFT, nicht nur nach der Form der Zeile.
    {"tool": "document_search",
     "grounding_surface": [
        "In der Debatte sprach die Abgeordnete ueber Fluechtlinge.",
        "Der Redner nannte Zahlen zur Aufnahme.",
    ]}
]


class RueckfrageLaeuftDurchDieWache(unittest.TestCase):
    def test_erfundenes_zitat_in_der_rueckfrage_wird_entfernt(self):
        """Der Befund selbst: das Fabrikat darf die Antwort nicht erreichen."""
        text, annotationen = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.",
            _EVIDENZ,
            rueckfrage=f'Meinten Sie die Passage "{_FABRIKAT}"?',
        )
        self.assertNotIn("ruecksichtslose Invasoren", text)
        self.assertNotIn(_FABRIKAT, text)
        claims = {a.get("claim_id") for a in annotationen if isinstance(a, dict)}
        self.assertIn("rueckfrage_zitat_ohne_deckung", claims)

    def test_saubere_rueckfrage_bleibt_erhalten(self):
        """Die Wache darf die Rueckfrage nicht einfach abschaffen.

        Eine Wache, die alles streicht, besteht jeden Fabrikationstest und
        ist trotzdem falsch. Der Gegenbeleg gehoert dazu.
        """
        text, _ = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.",
            _EVIDENZ,
            rueckfrage="Meinen Sie die Wortform oder das Lemma?",
        )
        self.assertIn("Meinen Sie die Wortform oder das Lemma?", text)
        self.assertIn("Offene Präzisierung", text)

    def test_belegtes_zitat_in_der_rueckfrage_bleibt(self):
        """Deckung entscheidet, nicht die Tatsache, dass es ein Zitat ist."""
        text, _ = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.",
            _EVIDENZ,
            rueckfrage='Meinten Sie "Der Redner nannte Zahlen zur Aufnahme."?',
        )
        self.assertIn("Der Redner nannte Zahlen zur Aufnahme", text)

    def test_leer_gewordene_rueckfrage_entfaellt_ganz(self):
        """Kein Vorspann ohne Frage dahinter."""
        text, annotationen = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.",
            _EVIDENZ,
            rueckfrage=f'"{_FABRIKAT}"',
        )
        self.assertNotIn("Offene Präzisierung", text)
        claims = {a.get("claim_id") for a in annotationen if isinstance(a, dict)}
        self.assertIn("rueckfrage_verworfen", claims)

    def test_ohne_rueckfrage_bleibt_alles_wie_zuvor(self):
        """Der Normalfall darf sich durch die Erweiterung nicht aendern."""
        mit_kwarg, ann_a = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.", _EVIDENZ, rueckfrage="")
        ohne_kwarg, ann_b = rr.politur_mit_zitatwache(
            "Kernbefund: 12 Treffer.", _EVIDENZ)
        self.assertEqual(mit_kwarg, ohne_kwarg)
        self.assertEqual(ann_a, ann_b)
        self.assertNotIn("Offene Präzisierung", ohne_kwarg)

    def test_der_orchestrator_haengt_NICHTS_hinter_die_wache(self):
        """Sonst waere die Naht nur verschoben.

        Der Chokepoint ist die eine Stelle, die jede Landung durchlaeuft.
        Haengt der Aufrufer danach noch Text an, ist er wieder umgangen,
        gleich welchen Namen die anhaengende Funktion traegt.
        """
        from pathlib import Path

        # NICHT ueber das importierte Modul: tests/conftest.py schiebt fuer
        # candyconc_copilot Stubs in sys.modules, die kein __file__ haben.
        quelle = (
            Path(__file__).resolve().parents[2]
            / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        start = quelle.index("def _ra_finish_turn(")
        rumpf = quelle[start: quelle.index("\n    @staticmethod", start)]

        self.assertIn("rueckfrage=", rumpf)
        self.assertNotIn("mit_rueckfrage_am_ende", rumpf)
        # Zwischen der Wache und der Uebergabe an die Session darf der Text
        # nicht mehr angefasst werden.
        nach_wache = rumpf[rumpf.index("politur_mit_zitatwache"):]
        vor_session = nach_wache[: nach_wache.index("self.session.append")]
        self.assertNotIn("polished =", vor_session)


if __name__ == "__main__":
    unittest.main()
