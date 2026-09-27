"""Zwei Saetze des Methodensteckbriefs, die etwas Falsches behaupteten.

P3b (kollokation-2, toedlich). Der Satz "Fuer den Knoten X erreicht im
sichtbaren Suchlauf kein Kollokat die Reliabilitaetsschwelle" wird
DETERMINISTISCH erzeugt, nicht vom Modell geschrieben, und er feuerte auch
dann, wenn der Knoten null Treffer hatte. Dann hat die Schwelle nie
gebunden und es wurde nichts gemessen. Eine Professorin-Subagentin hat den
Satz am 2026-08-29 als frei erfunden gewertet.

Der Ausloeser ist ``result_count=0``, und den traegt ein leerer Lauf
genauso wie ein echter Schwellenverfehler. Das Werkzeug meldet leere
Laeufe inzwischen als ``empty``, aber diese Naht liest den Zaehler, nicht
den Status: zweite Naht derselben Klasse.

P5 (kollokation-1, schwer). Der Steckbrief schrieb bei floor_mode
'adaptive' den Zusatz "aus der Knotenfrequenz kalibriert".
``adaptive_collocate_min_freq`` gibt ab Knotenfrequenz 50 KONSTANT 5
zurueck. Nachgerechnet fuer 50, 51, 100, 1.241, 35.910 und 139.450: immer
5. Fuer jeden realistischen Knoten war der Zusatz falsch.
"""

from __future__ import annotations

import pytest

from candyconc.analysis_defaults import (
    COLLOCATE_ADAPTIVE_NODE_THRESHOLD,
    adaptive_collocate_min_freq,
    collocate_floor_herkunft,
)


# --------------------------------------------------------------------------- #
# P5
# --------------------------------------------------------------------------- #

def test_der_boden_ist_oberhalb_der_schwelle_wirklich_konstant():
    """Die POSITIVE KLASSE des Befundes, als Zahl statt als Wortlaut.

    Ohne sie waere die Umbenennung eine Geschmacksfrage.
    """
    werte = {
        adaptive_collocate_min_freq(n, None)
        for n in (50, 51, 100, 1241, 35910, 139450)
    }
    assert werte == {5}, werte
    # Und darunter kalibriert sie wirklich, sonst waere der zweite Zweig
    # ebenso eine Fehlmeldung.
    assert adaptive_collocate_min_freq(20, None) < 5
    assert adaptive_collocate_min_freq(49, None) < 5


def test_oberhalb_der_schwelle_heisst_es_nicht_mehr_kalibriert():
    for knoten in (COLLOCATE_ADAPTIVE_NODE_THRESHOLD, 1241, 139450):
        text = collocate_floor_herkunft("adaptive", knoten)
        assert "Standardboden" in text, (knoten, text)
        assert "kalibriert" not in text, (knoten, text)
        assert str(knoten) in text


def test_unterhalb_der_schwelle_heisst_es_weiter_kalibriert():
    """Gegenklasse: die Umbenennung darf nicht in beide Richtungen greifen."""
    text = collocate_floor_herkunft("adaptive", 20)
    assert "kalibriert" in text
    assert "20" in text
    assert "Standardboden" not in text


def test_die_uebrigen_modi_bleiben_unveraendert():
    assert collocate_floor_herkunft("requested", 5) == "als Argument gesetzt"
    assert "Zuverlässigkeitsboden" in collocate_floor_herkunft(
        "requested_raised", 5)
    assert "ohne Kalibrierungsbasis" in collocate_floor_herkunft(
        "default", None)
    assert collocate_floor_herkunft("unbekannt", 5) == ""


def test_ohne_knotenfrequenz_wird_nichts_behauptet():
    """Fehlt die Zahl, faellt der Text auf die alte, unspezifische Form
    zurueck statt eine Schwelle zu behaupten, die niemand geprueft hat."""
    text = collocate_floor_herkunft("adaptive", None)
    assert text == "aus der Knotenfrequenz kalibriert"
    assert "Schwelle" not in text


# --------------------------------------------------------------------------- #
# P3b
# --------------------------------------------------------------------------- #

def _fakten(node_frequency, min_freq=5, term="eine Rolle spielen"):
    from candyconc.candyconc_copilot.grounding_facts import (
        _collocation_floor_facts,
    )
    from candyconc.candyconc_copilot.grounding_schemas import EvidenceItem

    item = EvidenceItem(
        id="e1",
        tool="collocate_stats",
        tool_call_id="c1",
        query={"term": term},
        raw_surface={
            "requested_term": term,
            "min_freq": min_freq,
            "result_count": 0,
            "node_frequency": node_frequency,
        },
        grounding_surface=[
            f"requested_term={term}",
            f"min_freq={min_freq}",
            "result_count=0",
            f"node_frequency={node_frequency}",
        ],
        analysis_family="collocation",
        status="empty" if not node_frequency else "success",
        truncated=False,
    )
    return _collocation_floor_facts([item], [item])


def test_null_treffer_behauptet_keine_verfehlte_schwelle():
    fakten = _fakten(0)
    assert fakten, "kein Fakt erzeugt, der Test praefte nichts"
    text = fakten[0].statement
    assert "null Treffer" in text
    assert "nicht gebunden" in text
    assert "belegt keine Seltenheit" in text
    # Der widerlegte Satz darf an keiner Stelle zurueckkommen.
    assert "erreicht" not in text, text
    assert "Reliabilitaetsschwelle" not in text, text


def test_ein_echter_schwellenverfehler_sagt_es_weiterhin():
    """POSITIVE GEGENKLASSE.

    Ohne sie waere eine Fassung gruen, die den Befund IMMER unterdrueckt,
    und das waere derselbe Fehler in der Gegenrichtung: ein Knoten mit
    Treffern, dessen Kollokate alle unter der Schwelle liegen, IST ein
    Befund.
    """
    fakten = _fakten(1241, term="die")
    assert fakten
    text = fakten[0].statement
    assert "Reliabilitaetsschwelle" in text, text
    assert "null Treffer" not in text, text
