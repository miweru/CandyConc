"""Context counts must not exceed the arithmetic bound imposed by the window."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot.recipe_runtime import (  # noqa: E402
    umfeldzahl_ueber_fensterdecke,
)


class _Posten:
    def __init__(self, tool: str, raw_surface: dict) -> None:
        self.tool = tool
        self.raw_surface = raw_surface


def _kollokation(node_frequency=3075, window=5) -> _Posten:
    return _Posten(
        "collocate_stats",
        {"node_frequency": node_frequency, "window": window},
    )


# Shortened answer fixture for the impossible context-count case.
DEFEKTTEXT = (
    "In der sichtbaren Frequenzliste fallen vor allem `Beifall` "
    "(f=946766, per_million=3461.0), `Herr` (f=857969), "
    "`Bundesregierung` (f=431907) auf."
)


class DerBefundWirdErkannt(unittest.TestCase):
    def test_der_echte_defekttext_wird_gemeldet(self):
        befunde = umfeldzahl_ueber_fensterdecke(DEFEKTTEXT, [_kollokation()])
        self.assertEqual(len(befunde), 3)
        self.assertIn("f=946766", befunde[0])
        self.assertIn("30750", befunde[0])
        self.assertIn("3075", befunde[0])

    def test_die_runde_eins_zahl_wird_ebenfalls_gemeldet(self):
        befunde = umfeldzahl_ueber_fensterdecke(
            "`die` (f=26107063, per_million=95438.0)", [_kollokation()]
        )
        self.assertEqual(len(befunde), 1)

    def test_die_meldung_nennt_die_rechnung(self):
        befund = umfeldzahl_ueber_fensterdecke(DEFEKTTEXT, [_kollokation()])[0]
        self.assertIn("Knotenfrequenz 3075 mal Fensterbreite 2x5", befund)


class KeinFehlalarm(unittest.TestCase):
    """Jeder Fall, in dem die Wache schweigen MUSS."""

    def test_ohne_kollokationsposten_gibt_es_keine_decke(self):
        # Dieselben Zahlen, aber nichts, woran sie zu messen waeren.
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke(
                DEFEKTTEXT, [_Posten("frequency_list", {"rows": []})]
            ),
            [],
        )

    def test_fehlende_knotenfrequenz_ist_nicht_pruefbar(self):
        # tools/collocate_stats.py faengt jede Ausnahme der
        # Positionsaufloesung ab und liefert node_frequency=None. Eine
        # geratene Decke waere die Erfindung genau der Schranke, die
        # durchgesetzt werden soll.
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke(
                DEFEKTTEXT, [_kollokation(node_frequency=None)]
            ),
            [],
        )

    def test_zahlen_unter_der_decke_bleiben_unbehelligt(self):
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke(
                "`Flucht` (f=980), `Politik` (f=12000)", [_kollokation()]
            ),
            [],
        )

    def test_genau_auf_der_decke_ist_erlaubt(self):
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke("`x` (f=30750)", [_kollokation()]), []
        )

    def test_mehrdeutige_schreibweise_schweigt(self):
        # 946.766 ist deutsch 946766 und englisch 946,766. Nur die erste
        # Lesart reiszt die Decke. Eine Wache, die hier meldet, raet.
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke("`x` (f=946.766)", [_kollokation()]),
            [],
        )

    def test_korpusfrequenz_ohne_f_etikett_wird_nicht_geprueft(self):
        # Die Wache bindet an das Etikett f=, nicht an jede grosse Zahl.
        # Nenner und Korpusgroesse stehen legitim in derselben Antwort.
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke(
                "Basis 273.550.093 Tokens im Gesamtkorpus, 3075 Treffer.",
                [_kollokation()],
            ),
            [],
        )

    def test_die_groesste_decke_gewinnt(self):
        # Mehrere Kollokationen: es gilt die nachsichtigste Schranke.
        befunde = umfeldzahl_ueber_fensterdecke(
            "`x` (f=200000)", [_kollokation(3075, 5), _kollokation(50000, 5)]
        )
        self.assertEqual(befunde, [])

    def test_eine_erhobene_korpusfrequenz_wird_nicht_gemeldet(self):
        """Der Fehlalarm, den ein adversarialer Pruefer nachgewiesen hat.

        Eine Triangulationsfrage („wie oft steht das Wort im Korpus, und
        was steht in seinem Umfeld“) nennt beide Zahlenarten voellig zu
        Recht nebeneinander. Die erste Fassung der Wache mass jede Zahl
        mit f-Etikett gegen die Decke und meldete damit die
        Korpusfrequenz einer fachlich einwandfreien Antwort an.

        Gemeldet wird deshalb nur, was die Decke reiszt UND unter keinem
        Feld irgendeines Evidenzpostens steht.
        """
        from candyconc.candyconc_copilot.grounding_facts import (
            make_evidence_item,
        )

        kollokation = make_evidence_item(
            item_id="e1", tool="collocate_stats", tool_call_id="c1",
            query={"term": "Migration"},
            output={
                "status": "success", "requested_term": "Migration",
                "window": 5, "within_sentence": True, "min_freq": 5,
                "node_frequency": 3075, "sort_by": "logdice",
                "scope": {"corpus_id": "x", "level": "corpus"},
                "rows": [{"word": "irreguläre", "f": 412, "logdice": 9.8}],
            },
            analysis_family="collocation",
        )
        frequenzliste = make_evidence_item(
            item_id="e2", tool="frequency_list", tool_call_id="c2",
            query={},
            output={
                "status": "success", "group_by": "word", "total": 49996,
                "scope": {"corpus_id": "x", "level": "corpus"},
                "rows": [
                    {"word": "Beifall", "f": 946766, "per_million": 3461.0}
                ],
            },
            analysis_family="collocation",
        )
        text = (
            "Im Umfeld steht `irreguläre` (f=412). Die Frequenzliste "
            "beginnt mit `Beifall` (f=946766)."
        )
        self.assertEqual(
            umfeldzahl_ueber_fensterdecke(text, [kollokation, frequenzliste]),
            [],
        )

    def test_eine_nirgends_gemessene_zahl_wird_gemeldet(self):
        # Die Klasse, um die es der Wache noch geht: eine Zahl, die als
        # Kookkurrenz auftritt, keine sein kann und aus keiner Messung
        # stammt.
        befunde = umfeldzahl_ueber_fensterdecke(
            "Im Umfeld steht `und` (f=7654321).", [_kollokation()]
        )
        self.assertEqual(len(befunde), 1)


class AmEngpassVerdrahtet(unittest.TestCase):
    def test_politur_meldet_den_befund_als_annotation(self):
        from candyconc.candyconc_copilot import recipe_runtime as rr

        _, annotationen = rr.politur_mit_zitatwache(
            DEFEKTTEXT, [_kollokation()]
        )
        kennungen = [
            eintrag.get("claim_id")
            for eintrag in annotationen
            if isinstance(eintrag, dict)
        ]
        self.assertIn("umfeldzahl_ueber_fensterdecke", kennungen)

    def test_der_text_wird_nicht_angetastet(self):
        from candyconc.candyconc_copilot import recipe_runtime as rr

        poliert, _ = rr.politur_mit_zitatwache(DEFEKTTEXT, [_kollokation()])
        self.assertIn("946766", poliert)
        self.assertNotIn("[Beleg fehlt]", poliert)


if __name__ == "__main__":
    unittest.main()
