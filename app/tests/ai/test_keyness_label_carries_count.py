# -*- coding: utf-8 -*-
"""A keyness row uses the spelling that contributes its displayed count."""

import numpy as np

from candyconc.candyconc_copilot.row_spelling_note import (
    abweichende_schreibung,
    alle_saetze,
)
from candyconc.services.tools.keyness import schreibungen_anhaengen

REP = 10          # "Beschlussempfehlung" — kleinste ID, altes Etikett
REFORM = 11       # "Beschlussempfehlungen" — die tragende Schreibung
NAMEN = {REP: "Beschlussempfehlung", REFORM: "Beschlussempfehlungen"}


def _woerter(ids):
    return [NAMEN[int(i)] for i in ids]


def _etiketten():
    return [NAMEN[REP], NAMEN[REFORM]]


def test_nicht_tragendes_etikett_wird_umgetauft():
    zeilen = [{"word": "Beschlussempfehlung"}]
    schreibungen_anhaengen(
        zeilen, _woerter,
        ([REP, REFORM], _etiketten(), {REP: {REFORM: 18656}}),
        ([], [], {}),
    )
    assert zeilen[0]["word"] == "Beschlussempfehlungen", zeilen[0]
    # Nichts geht verloren: die Aufschluesselung bleibt komplett.
    assert zeilen[0]["surface_variants"] == {
        "target": {"Beschlussempfehlungen": 18656},
    }, zeilen[0]["surface_variants"]


def test_tragendes_etikett_bleibt_steht():
    zeilen = [{"word": "Beschlussempfehlung"}]
    schreibungen_anhaengen(
        zeilen, _woerter,
        ([REP, REFORM], _etiketten(),
         {REP: {REP: 18000, REFORM: 656}}),
        ([], [], {}),
    )
    assert zeilen[0]["word"] == "Beschlussempfehlung", zeilen[0]
    assert zeilen[0]["surface_variants"]["target"] == {
        "Beschlussempfehlung": 18000, "Beschlussempfehlungen": 656,
    }


def test_beide_seiten_werden_zusammen_gezaehlt():
    """Target traegt fast nur die alte Form, Referenz fast nur die neue;
    die Mehrheit entscheidet ueber den Namen, die Aufteilung bleibt je
    Seite sichtbar."""
    zeilen = [{"word": "Beschlussempfehlung"}]
    schreibungen_anhaengen(
        zeilen, _woerter,
        ([REP, REFORM], _etiketten(),
         {REP: {REP: 9000, REFORM: 100}}),
        ([REP, REFORM], _etiketten(),
         {REP: {REP: 50, REFORM: 20000}}),
    )
    assert zeilen[0]["word"] == "Beschlussempfehlungen", zeilen[0]
    assert zeilen[0]["surface_variants"]["target"]["Beschlussempfehlung"] == 9000
    assert zeilen[0]["surface_variants"]["reference"]["Beschlussempfehlungen"] == 20000


def test_die_erklaerende_wache_schweigt_zum_ehrlichen_etikett():
    """DAS EIGENTLICHE ZIEL: die Zeile traegt ihren Namen selbst, der
    Anhang ist nicht mehr noetig. Die Wache bleibt Failsafe."""
    zeilen = [{"word": "Beschlussempfehlung"}]
    schreibungen_anhaengen(
        zeilen, _woerter,
        ([REP, REFORM], _etiketten(), {REP: {REFORM: 18656}}),
        ([], [], {}),
    )
    antwort = ("In den 2010ern steht Beschlussempfehlungen mit 18.656 "
               "Treffern an der Spitze.")
    assert alle_saetze(antwort, [{"rows": zeilen}]) == []


def test_die_wache_meldet_weiter_bei_unbehandelten_zeilen():
    """Failsafe-Kontrolle: eine Zeile, die NICHT durch den Etikett-Fix
    ging (z.B. von einem anderen Pfad), wird weiter gemeldet."""
    zeile = {"word": "Beschlussempfehlung",
             "surface_variants": {"target": {
                 "Beschlussempfehlungen": 18656,
                 "Beschlussempfehlung": 0}}}
    assert abweichende_schreibung(zeile) is not None
    antwort = "Die Zeile Beschlussempfehlung zeigt 18656 Treffer."
    saetze = alle_saetze(antwort, [{"fact_surface": {"rows": [zeile]}}])
    assert saetze, saetze
