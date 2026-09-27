"""Ein Anführungszeichen in Backticks öffnet kein Zitat.

K15-Lauf A, r5b-konkordanz-belegqualitaet (zyklus27_teil1): die Antwort
schrieb „weil nur `„` mit je maximal 8 Token Abstand im selben Satz zählt“.
Das Zeichen in Backticks öffnete eine Spanne über den eigenen Text bis zum
echten Zitat dahinter, und der Hinweis meldete „` mit je maximal 8 Token
Abstand im selben Satz zählt. engli“ als unbelegt (Regression, zweite
Naht zu 146).
"""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as synthesis

ZEILE = "Warum denn nicht , sieh es doch als Herausforderung !"

ANTWORT = (
    "Das ist eine Untergrenze, weil nur `„` mit je maximal 8 Token Abstand im selben "
    "Satz zählt; englische Anführungszeichen fehlen. Wörtlich etwa „Warum denn nicht, "
    "sieh es doch als Herausforderung!\" in [[beleg:E_run_cqlf_query_2]]."
)


def test_das_zeichen_selbst_oeffnet_kein_zitat():
    assert synthesis._unverifizierte_zitate(ANTWORT, [{"grounding_surface": [ZEILE]}]) == []


def test_das_echte_zitat_dahinter_bleibt_geprueft():
    geaendert = ANTWORT.replace("sieh es doch", "sieh es bitte")
    assert synthesis._unverifizierte_zitate(geaendert, [{"grounding_surface": [ZEILE]}]) != []


def test_eine_kwic_zeile_in_backticks_bleibt_geprueft():
    text = "Beleg: `sagte er , „ das ist eine erfundene Herausforderung “ .` [[beleg:E_run_cqlf_query_1]]"
    assert synthesis._unverifizierte_zitate(text, [{"grounding_surface": [ZEILE]}]) != []
