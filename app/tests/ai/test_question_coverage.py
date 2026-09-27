# -*- coding: utf-8 -*-
"""Was die Frage nennt und der Lauf nicht gerechnet hat, steht in der Antwort.

Am 2026-08-30 auf dem echten Produktpfad gemessen. Die Frage verlangte
woertlich "Rechne mir vor, was ich bei Fenster 1, 5 und 10 jeweils gewinne
und was ich verliere". Gerechnet wurden Fenster 1 und 5, Fenster 10 nie, und
die Antwort verschwieg das. Eine Deckung zu behaupten, die es nicht gibt,
ist eine Behauptung jenseits der Evidenz.

Die Wache MELDET und rechnet nicht nach. Der Baum hat die andere Naht
bereits (response_requirements), sie kostet aber je unerfuellter Pflicht
eine Neusynthese der ganzen Antwort, zuletzt sieben Mal zu je rund 360
Sekunden. Melden kostet null Modellaufrufe und wirkt bei jedem Modell.

NICHT fensterspezifisch: dieselbe Luecke besteht fuer min_freq und top_n.
Das Feld ist ein Parameter, Fenster nur der erste Fall.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from candyconc.candyconc_copilot.question_coverage import (
    FELDNAMEN,
    alle_luecken_saetze,
    genannte_werte,
    gerechnete_werte,
    luecke,
    luecken_satz,
)

_QUELLE = Path(__file__).resolve().parents[2] / "src" / "candyconc"


def _ev(**flaeche):
    return types.SimpleNamespace(raw_surface=dict(flaeche), query="")


class TestWasDieFrageNennt:
    def test_der_gemessene_fall(self):
        frage = ("Rechne mir vor, was ich bei Fenster 1, 5 und 10 jeweils "
                 "gewinne und was ich verliere.")
        assert genannte_werte("window", frage) == [1, 5, 10]

    @pytest.mark.parametrize("frage,erwartet", [
        ("Kollokationsprofil bei Fenster 5", [5]),
        ("Fenster 1, 5, 10 vergleichen", [1, 5, 10]),
        ("Fenster 2 bis 4", [2, 4]),
        ("Was ist mit der Fenstergroesse 7?", [7]),
        ("Gib mir die zehn staerksten Kollokate", []),
    ])
    def test_aufzaehlungen(self, frage, erwartet):
        assert genannte_werte("window", frage) == erwartet

    def test_zahlen_ohne_feldnamen_werden_nicht_eingesammelt(self):
        """Sonst meldet die Wache Luecken, die niemand gefragt hat."""
        frage = "Gib mir die 10 staerksten Kollokate zu Rolle bei Fenster 5."
        assert genannte_werte("window", frage) == [5]


class TestWasGerechnetWurde:
    def test_die_oberflaeche_schlaegt_die_anfrage(self):
        """Ein Werkzeug darf kalibrieren. Dann gilt der gerechnete Wert."""
        ev = types.SimpleNamespace(raw_surface={"window": 5},
                                   query='{"window": 99}')
        assert gerechnete_werte("window", [ev]) == [5]

    def test_ohne_oberflaeche_zaehlt_die_anfrage(self):
        ev = types.SimpleNamespace(raw_surface={}, query='{"window": 3}')
        assert gerechnete_werte("window", [ev]) == [3]


class TestDieLuecke:
    def test_der_gemessene_fall_wird_benannt(self):
        frage = "Rechne mir vor, was ich bei Fenster 1, 5 und 10 gewinne."
        satz = luecken_satz("window", frage, [_ev(window=1), _ev(window=5)])
        assert "Fenster 10" in satz
        assert "1, 5" in satz
        assert ";" not in satz

    def test_vollstaendige_deckung_schweigt(self):
        """Positive Klasse. Ohne sie bestuende der Test auch auf einer Wache,
        die immer meldet."""
        frage = "Rechne mir vor, was ich bei Fenster 1, 5 und 10 gewinne."
        assert luecke("window", frage,
                      [_ev(window=1), _ev(window=5), _ev(window=10)]) == []

    def test_ohne_jede_fensterrechnung_schweigt_sie(self):
        """Eine Frage, die Fenster nennt, kann ueber einen anderen Weg
        beantwortet werden. Dann ist nichts ausgelassen, sondern anders
        gerechnet, und eine Meldung waere falsch."""
        frage = "Wie wirkt sich Fenster 5 auf die Dispersion aus?"
        assert luecke("window", frage, [_ev(dp=0.8)]) == []

    def test_das_feld_ist_ein_parameter_nicht_das_fenster(self):
        """Der Zuschnitt gilt fuer jede aufgezaehlte Groesse."""
        assert "min_freq" in FELDNAMEN and "top_n" in FELDNAMEN
        frage = "Vergleiche mit Mindestfrequenz 5 und 20."
        satz = luecken_satz("min_freq", frage, [_ev(min_freq=5)])
        assert "20" in satz


class TestJedeLandungReichtDieFrageDurch:
    """Eine Naht ohne Frage laesst die Wache still verstummen.

    Genau diese Klasse hat in dieser Codebasis mehrfach zugeschlagen, zuletzt
    beim Feldvertrag: ein Vorgabewert an EINER Stelle gedreht, waehrend n
    Aufrufstellen den alten Wert behielten. Deshalb wird hier gezaehlt.
    """

    def _aufrufe(self):
        treffer = []
        for datei in (_QUELLE / "candyconc_copilot" / "orchestrator.py",
                      _QUELLE / "services" / "backend" / "routes" / "copilot.py"):
            baum = ast.parse(datei.read_text(encoding="utf-8"))
            for knoten in ast.walk(baum):
                if not isinstance(knoten, ast.Call):
                    continue
                ziel = knoten.func
                name = (ziel.id if isinstance(ziel, ast.Name)
                        else ziel.attr if isinstance(ziel, ast.Attribute) else None)
                if name in {"politur_mit_zitatwache", "_politur"}:
                    treffer.append((datei.name, knoten.lineno,
                                    {k.arg for k in knoten.keywords if k.arg}))
        return treffer

    def test_jede_landung_uebergibt_frage(self):
        aufrufe = self._aufrufe()
        assert aufrufe, "Kein Aufruf gefunden, der Test waere vakuum."
        ohne = [(d, z) for d, z, args in aufrufe if "frage" not in args]
        assert not ohne, (
            f"Politur ohne frage: {ohne}. Dort verstummt die Deckungswache "
            "still, und die Antwort behauptet wieder eine Deckung, die sie "
            "nicht hat.")


class TestUeberAlleFelder:
    def test_mehrere_luecken_kommen_in_fester_reihenfolge(self):
        frage = "Fenster 1 und 10, Mindestfrequenz 5 und 20."
        saetze = alle_luecken_saetze(frage, [_ev(window=1, min_freq=5)])
        assert len(saetze) == 2
        assert "Fenster" in saetze[0] and "Mindestfrequenz" in saetze[1]
