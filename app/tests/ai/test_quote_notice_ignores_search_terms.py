"""Ein Suchwort in Backticks leitet kein Korpuszitat ein.

K12-Lauf A, r3b-paar-1 (Sitzung in zyklus26_teil1): die Antwort schlug einen
Vortragssatz vor und endete mit „Hinweis: 2 wörtliche Zitate stehen nicht in
der Beleglage“. Gemeint waren der eigene Vortragssatz und „Meiden der
Funktion“. `_BELEGWORT` fand „beispiel“ in den Suchwörtern `beispielsweise`
und `zum Beispiel` vor der Anführung.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as synthesis

ZEILE = "Die Mark auf dem Tisch ist kein Bekenntnis zur Planwirtschaft"

VORTRAG = (
    "Sagen Sie im Vortrag nicht „KI-Texte meiden `deswegen`/`nämlich`/`beispielsweise`\", "
    "sondern: „Auftragsbasierte KI-Neufassungen verwenden `deswegen` (ca. 1/10), `nämlich` "
    "und `beispielsweise` (ca. 1/4 bis 1/5 des menschlichen Niveaus) deutlich seltener.“"
)

BEGRIFF = (
    "Was die Daten nicht hergeben, ist in einem Satz gesagt: ob KI stattdessen `daher`, "
    "`darum`, `zum Beispiel` setzt, ist nicht gezählt, „Meiden der Funktion“ wäre mehr als "
    "„selteneres Wort“ und hier nicht geprüft."
)


def test_der_vorgeschlagene_vortragssatz_ist_kein_korpuszitat():
    assert synthesis._unverifizierte_zitate(VORTRAG, [{"grounding_surface": [ZEILE]}]) == []


def test_ein_begriff_nach_einem_suchwort_ist_kein_korpuszitat():
    assert synthesis._unverifizierte_zitate(BEGRIFF, [{"grounding_surface": [ZEILE]}]) == []


def test_ein_belegwort_ausserhalb_der_backticks_gilt_weiter():
    text = "Zum Beispiel `zudem`: „Die Mark auf dem Tisch ist ein Bekenntnis zur Marktwirtschaft“."
    assert synthesis._unverifizierte_zitate(text, [{"grounding_surface": [ZEILE]}]) != []
