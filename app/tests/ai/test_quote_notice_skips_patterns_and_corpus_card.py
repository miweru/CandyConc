"""Muster mit Platzhaltern und Zitate aus der Korpuskarte sind keine Korpuszitate.

K15-Lauf A, gemischt-leichte-sprache-naeherung, und K16-Lauf A,
r3b-grundgesamtheit-1: der Hinweis meldete „Erste Meldung: ... / Meldung 1:
...“ und „Das nennt man … / Das heißt, man kann …“.
K16-Lauf A, r3b-spiegel-1: „aus der Korpusbeschreibung „Die elf Verfahren …““
galt wegen „schreib“ in „Korpusbeschreibung“ als Korpuszitat.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as synthesis

ZEILE = "Meldung 1 : Militärparade in Paris"

MUSTER = (
    "KI baut Überblicke als durchnummerierte Blöcke wie „Erste Meldung: ... / Meldung 1: ... / "
    "Vierte Meldung: ...“ [[beleg:E_run_cqlf_query_6]]."
)

KARTE = (
    "Dazu passt die Entstehungslogik aus der Korpusbeschreibung: „Die elf Verfahren mit "
    "generator im Namen erhielten je Quelltext denselben Auftrag“ [[beleg:E_query_count_3]]."
)


def test_ein_muster_mit_platzhaltern_ist_kein_korpuszitat():
    assert synthesis._unverifizierte_zitate(MUSTER, [{"grounding_surface": [ZEILE]}]) == []


def test_ein_zitat_nach_korpusbeschreibung_ist_kein_korpuszitat():
    assert synthesis._unverifizierte_zitate(KARTE, [{"grounding_surface": [ZEILE]}]) == []


def test_eine_zeile_mit_auslassung_ohne_alternativen_bleibt_geprueft():
    text = "Beleg: „Meldung 1: Militärparade in Berlin …“ [[beleg:E_run_cqlf_query_6]]."
    assert synthesis._unverifizierte_zitate(text, [{"grounding_surface": [ZEILE]}]) != []


def test_schreibt_leitet_weiter_ein_korpuszitat_ein():
    text = "Die Vorlage schreibt „Militärparade in Berlin fand statt“ [[beleg:E_run_cqlf_query_6]]."
    assert synthesis._unverifizierte_zitate(text, [{"grounding_surface": [ZEILE]}]) != []
