"""A table header without data rows must not be delivered as a completed table."""

from __future__ import annotations

import os

import pytest

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

from candyconc.candyconc_copilot.recipe_runtime import leere_tabelle_fuellen

LEER = """Der Knoten „Merkel" kommt 103-mal vor, 19 Kollokate erreichten den Boden.

**Top-Kollokate:**

| Rang | Wort | f | logDice |
|---|---|---|---|

Die uebrigen Top-Woerter sind Funktionswoerter.
"""

GEFUELLT = """Kopf

| Rang | Wort | f |
|---|---|---|
| 1 | Vasallen | 6 |

Schluss.
"""


class _Evidenz:
    """Ein EvidenceItem traegt seine Zeilen in ``fact_surface``.

    NICHT in ``output``: ein erster Anlauf griff dorthin, fand nichts, und
    entfernte die Tabelle statt sie zu fuellen. Die Wirkung sah nach
    Erfolg aus, weil der sichtbare Defekt verschwand.
    """

    def __init__(self, rows):
        self.fact_surface = {"rows": rows, "status": "success"}
        self.raw_surface = {"rows": rows}


ZEILEN = [
    {"rank": 1, "word": "Vasallen", "f": 6, "logdice": 6.4257, "ll": 29.39},
    {"rank": 2, "word": "ihre", "f": 7, "logdice": 4.9874, "ll": 17.54},
]


def test_die_tabelle_wird_aus_der_evidenz_gefuellt():
    text, notiz = leere_tabelle_fuellen(LEER, [_Evidenz(ZEILEN)])
    assert notiz == "leere_tabelle_aus_evidenz_gefuellt"
    assert "| 1 | Vasallen | 6 | 6.43 |" in text
    assert "| 2 | ihre | 7 | 4.99 |" in text


def test_ohne_evidenz_verschwindet_die_leere_tabelle():
    # Ein Tabellenkopf ohne Zeilen sagt nichts und sieht aus wie ein
    # Defekt. Lieber weg als leer.
    text, notiz = leere_tabelle_fuellen(LEER, [])
    assert notiz == "leere_tabelle_entfernt"
    assert "| Rang | Wort |" not in text
    assert "103-mal vor" in text


def test_eine_gefuellte_tabelle_bleibt_unberuehrt():
    # POSITIVE KLASSE. Ohne sie waere ein Handler gruen, der JEDE Tabelle
    # anfasst und dabei echte Modellzeilen ueberschreibt.
    text, notiz = leere_tabelle_fuellen(GEFUELLT, [_Evidenz(ZEILEN)])
    assert notiz == ""
    assert text == GEFUELLT


def test_die_zahlen_stammen_aus_dem_werkzeug_nicht_aus_dem_text():
    # Der Entwurf behauptet f = 999. Gefuellt wird trotzdem mit 6, denn
    # die Zeilen kommen aus der Evidenz, nicht aus dem Fliesstext.
    entwurf = LEER.replace(
        "19 Kollokate", "19 Kollokate mit f bis 999"
    )
    text, _ = leere_tabelle_fuellen(entwurf, [_Evidenz(ZEILEN)])
    assert "| 1 | Vasallen | 6 | 6.43 |" in text
    assert "| 999 |" not in text


def test_unbekannte_spalten_bleiben_leer_statt_geraten_zu_werden():
    kopf = LEER.replace(
        "| Rang | Wort | f | logDice |\n|---|---|---|---|",
        "| Rang | Wort | Erfundenes |\n|---|---|---|",
    )
    text, notiz = leere_tabelle_fuellen(kopf, [_Evidenz(ZEILEN)])
    assert notiz == "leere_tabelle_aus_evidenz_gefuellt"
    assert "| 1 | Vasallen |  |" in text


@pytest.mark.skipif(not _BENCH, reason="Testindex nicht gesetzt")
def test_am_echten_index_steht_vasallen_auf_rang_eins():
    """Der gemessene Fall, Ende zu Ende durch den Chokepoint."""
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.core import query_runtime as qr

    qr._CORPUS_INDEX = CorpusIndex(_BENCH)
    # NICHT ``import ... tool_wrappers``: die conftest dieses Baums
    # installiert dafuer einen Stub, dessen collocate_stats_tool kein
    # ``min_freq`` kennt. Ein Test, der den Stub trifft, prueft nichts.
    from tests.ai.test_tool_wrappers_parity_r5 import (
        _load_real_tool_wrappers,
    )

    tw = _load_real_tool_wrappers()
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
    from candyconc.candyconc_copilot.recipe_runtime import (
        politur_mit_zitatwache,
    )

    out = tw.collocate_stats_tool(
        term="Merkel", window=5, min_freq=5, sort_by="logdice"
    )
    item = make_evidence_item(
        item_id="e1", tool="collocate_stats", tool_call_id="c1",
        query={"term": "Merkel"}, output=out, analysis_family="collocation",
    )
    text, _ = politur_mit_zitatwache(LEER, [item])
    assert "Vasallen" in text
    # 6,43 war der Wert der Fensterformel unter dem Namen logDice. Seit dem
    # 2026-08-29 traegt die Spalte Rychlys logDice aus den Wortfrequenzen:
    # 14 + log2(2*6/(103+15)) = 10,7023, gerundet 10,70. Handnachgerechnet.
    assert "| 1 | Vasallen | 6 | 10.70 |" in text


# --------------------------------------------------------------------------- #
# Haertung: diese Wache laeuft auf JEDER Antwort. Was sie nicht anfassen     #
# darf, ist so wichtig wie das, was sie repariert. Alle drei Faelle unten    #
# sind bei der Haertung des ersten Entwurfs aufgefallen, zwei davon haetten  #
# GUTE Antworten beschaedigt.                                                #
# --------------------------------------------------------------------------- #

CODEBLOCK = "Text\n\n```\n| A | B |\n|---|---|\n```\n\nSchluss."
FREMDER_KOPF = "Kopf\n\n| A | B |\n|---|---|\n"


def test_eine_tabelle_in_einem_codeblock_bleibt_unberuehrt():
    # Eine Pipe-Tabelle in einem eingezaeunten Block ist ein BEISPIEL,
    # kein Befund. Der erste Entwurf hat sie umgeschrieben.
    text, notiz = leere_tabelle_fuellen(CODEBLOCK, [_Evidenz(ZEILEN)])
    assert notiz == ""
    assert text == CODEBLOCK


def test_ein_kopf_ohne_treffende_spalten_wird_entfernt_nicht_leer_gefuellt():
    # Der erste Entwurf baute daraus "|  |  |", eine Zeile aus lauter
    # Leerfeldern. Die sieht nach Inhalt aus und traegt keinen, ist also
    # schlechter als gar keine Tabelle.
    text, notiz = leere_tabelle_fuellen(FREMDER_KOPF, [_Evidenz(ZEILEN)])
    assert notiz == "leere_tabelle_entfernt"
    assert "|" not in text
    assert "Kopf" in text


def test_ausrichtungszeilen_werden_erkannt():
    text, notiz = leere_tabelle_fuellen(
        "| Rang | Wort |\n|:---|---:|\n\nText.", [_Evidenz(ZEILEN)]
    )
    assert notiz == "leere_tabelle_aus_evidenz_gefuellt"
    assert "| 1 | Vasallen |" in text
