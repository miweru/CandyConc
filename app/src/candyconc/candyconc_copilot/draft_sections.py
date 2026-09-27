"""Die vier Wrap-up-Sektionen des Entwurfs, an einer Stelle.

Das Wrap-up-Pflichtformat (``recipe_runtime.TOOL_ROUND_WRAPUP_LINE``) gibt
dem Modell vier Sektionsueberschriften vor: Kernbefund, Belege, Deutung,
Grenzen. Zwei Stellen brauchen dieselben Muster:

* ``recipe_runtime`` faltet die Label-Wiederholung unter der Ueberschrift.
* ``grounding_verifier`` reicht beim Retry fuer eine fehlende Deutung die
  Deutungs-Sektion des Entwurfs als Nicht-Evidenz zurueck.

Deshalb liegen Label-Liste und Ueberschriftmuster hier und nicht in einem
der beiden Module. Dieses Modul importiert nichts ausser ``re``, damit der
Verifier seine Import-Armut behaelt.
"""

from __future__ import annotations

import re
from typing import Dict, Pattern, Tuple


#: Reihenfolge wie im Wrap-up-Briefing. Sie ist Teil des Vertrags mit dem
#: Modell, nicht bloss eine Aufzaehlung.
SEKTIONSLABEL: Tuple[str, ...] = ("Kernbefund", "Belege", "Deutung", "Grenzen")

# H8/F1 (R7b-Befund 'Deutung\nDeutung: ...'): das Wrap-up-Pflichtformat gibt
# die Sektionsueberschrift vor, und das Modell wiederholt das Label am
# Zeilenanfang seines Textes. Konservative Politur: NUR wenn die unmittelbar
# vorangehende nicht-leere Zeile GENAU dieses eine Label-Wort ist (nackt, als
# Markdown-Ueberschrift oder fett), faellt das fuehrende 'Label:' der
# Folgezeile. Andere Doppelungen bleiben unangetastet.
# H11.4: Der Doppelpunkt kann INNERHALB der Auszeichnung stehen
# (``**Deutung:**``). So schreiben es die meisten Modelle, und genau diese
# Zeile galt bisher nicht als Ueberschrift, weshalb die Wiederholung in der
# Folgezeile stehen blieb. Kursiv (ein Markierungszeichen) kommt dazu, die
# Markierung muss symmetrisch sein (Rueckwaertsreferenz).
SEKTIONS_UEBERSCHRIFT_MUSTER: Dict[str, Pattern[str]] = {
    label.casefold(): re.compile(
        r"^(?:#{1,6}\s+)?(\*{1,2}|_{1,2})?"
        + label
        + r"\s*:?\s*\1?\s*:?\s*$",
        re.IGNORECASE,
    )
    for label in SEKTIONSLABEL
}

#: Anders als ``SEKTIONS_UEBERSCHRIFT_MUSTER`` erlaubt dieses Muster Text in
#: derselben Zeile (``**Deutung:** Die KI-Fassungen ...``). Genau so schrieb
#: das Modell den Entwurf im Turn gemischt-leichte-sprache-naeherung, und
#: eine reine Ueberschriftprobe haette die Sektion dort nicht gefunden. Die
#: Klammer deckt die Formatvorgabe ``Deutung (max 3 Saetze)`` ab, wenn das
#: Modell sie in die Ueberschrift uebernimmt.
_SEKTIONSSTART_MUSTER: Dict[str, Pattern[str]] = {
    label.casefold(): re.compile(
        r"^\s*(?:#{1,6}\s+)?(?:[-*+]\s+)?(?:\*{1,2}|_{1,2})?\s*"
        + label
        + r"\s*(?:\([^)\n]{0,80}\))?\s*(?:\*{1,2}|_{1,2})?\s*:?\s*"
        r"(?:\*{1,2}|_{1,2})?\s*$|"
        r"^\s*(?:#{1,6}\s+)?(?:[-*+]\s+)?(?:\*{1,2}|_{1,2})?\s*"
        + label
        + r"\s*(?:\([^)\n]{0,80}\))?\s*:\s*(?:\*{1,2}|_{1,2})?\s*\S",
        re.IGNORECASE,
    )
    for label in SEKTIONSLABEL
}


def entwurfssektion(text: str, label: str) -> str:
    """Gibt die genannte Wrap-up-Sektion des Entwurfs zurueck, sonst "".

    Der Block beginnt bei der Ueberschriftzeile des Labels und endet vor der
    naechsten Ueberschriftzeile eines der anderen drei Label. Die
    Ueberschriftzeile bleibt im Ergebnis, damit der Empfaenger sieht, was er
    bekommt. Findet sich das Label nicht, ist das Ergebnis leer, und der
    Aufrufer bleibt beim bisherigen Verhalten.
    """
    schluessel = str(label or "").casefold()
    startmuster = _SEKTIONSSTART_MUSTER.get(schluessel)
    if startmuster is None:
        return ""
    zeilen = str(text or "").split("\n")
    beginn = -1
    for index, zeile in enumerate(zeilen):
        if startmuster.match(zeile):
            beginn = index
            break
    if beginn < 0:
        return ""
    ende = len(zeilen)
    fremde_muster = [
        muster
        for anderes, muster in _SEKTIONSSTART_MUSTER.items()
        if anderes != schluessel
    ]
    for index in range(beginn + 1, len(zeilen)):
        if any(muster.match(zeilen[index]) for muster in fremde_muster):
            ende = index
            break
    return "\n".join(zeilen[beginn:ende]).strip()


#: Was aus dem Entwurf zurueckgeht, traegt keine Ziffer. Ein "erfundener
#: Schwellwert" (so der Kommentar an der Filterstelle grounding_verifier.py
#: 9361-9373, die fuer focused_response_requirement_repair die verworfene
#: Slot-Prosa entfernt) ist immer eine Zahl, und die frischen Fakten sollen
#: isoliert bleiben. Durch kommt die Deutung, nicht ihre Messwerte.
_ZIFFER = re.compile(r"\d")


def _ziffernfreie_absaetze(text: str) -> str:
    """Absaetze ohne Ziffer und ohne Tabellenzeile, in ihrer Reihenfolge."""
    absaetze = [
        absatz.strip()
        for absatz in str(text or "").split("\n\n")
        if absatz.strip()
    ]
    behalten = [
        absatz
        for absatz in absaetze
        if not _ZIFFER.search(absatz)
        and not any(
            zeile.lstrip().startswith("|") for zeile in absatz.split("\n")
        )
    ]
    ergebnis = "\n\n".join(behalten).strip()
    uebrige_zeilen = [
        zeile for zeile in ergebnis.split("\n") if zeile.strip()
    ]
    if uebrige_zeilen and all(
        any(
            muster.match(zeile.strip())
            for muster in SEKTIONS_UEBERSCHRIFT_MUSTER.values()
        )
        for zeile in uebrige_zeilen
    ):
        # Nur noch Ueberschriften: der Empfaenger bekaeme das Wort "Deutung"
        # ohne Deutung.
        return ""
    return ergebnis


def entwurfsdeutung(text: str) -> str:
    """Die Deutung des Entwurfs, notfalls ohne Sektionsueberschrift.

    Erster Weg: die Sektion "Deutung", wenn das Modell sie geschrieben hat.
    Gemessen an den zehn Turns aus
    ``evaluation/deutung/harnisch_nachher.jsonl`` trifft das auf zwei zu
    (deutung-verknuepfung-dispersion mit 462 Zeichen,
    gemischt-markerliste-robustheit mit 553).

    Zweiter Weg fuer die uebrigen acht: der Entwurf des Turns
    gemischt-leichte-sprache-naeherung (1491 Zeichen, genau der Fall, aus dem
    P8 stammt) traegt "**Setup:**" und "**Grenzen:**", aber keine Sektion
    "Deutung". Seine Deutung steht als freier Absatz darin ("Das passt zu
    deinem Eindruck: Leichte Sprache wird von den Modellen als anderes Genre
    produziert"). Ohne den Rueckfall bekaeme das Modell dort weiterhin
    nichts, und die Maerkmale des Entwurfs blieben verloren.

    Der Rueckfall nimmt die Absaetze VOR der ersten Sektion und setzt
    voraus, dass der Entwurf ueberhaupt eine der vier Sektionen traegt. Ein
    Entwurf ohne jede Wrap-up-Struktur ist kein unvollstaendiges Wrap-up,
    sondern eine Kurzantwort, und der bleibt draussen: der bestehende Test
    ``test_kwic_analysis_report_fresh_slot_repair_still_blanks_draft`` haelt
    genau diese Grenze fest ("Die Wortfolge ist vorhanden." darf den
    fehlenden Deutungs-Slot nicht verankern).

    Beide Wege laufen danach durch dieselbe Ziffernschranke, damit kein
    Messwert und kein erfundener Schwellwert aus dem Entwurf in den frischen
    Slot zurueckwandert.
    """
    entwurf = str(text or "")
    sektion = entwurfssektion(entwurf, "Deutung")
    if sektion:
        return _ziffernfreie_absaetze(sektion)
    muster = list(_SEKTIONSSTART_MUSTER.values())
    frei: list[str] = []
    in_sektion = False
    for zeile in entwurf.split("\n"):
        if any(einzeln.match(zeile) for einzeln in muster):
            in_sektion = True
            continue
        if not in_sektion:
            frei.append(zeile)
    if not in_sektion:
        return ""
    return _ziffernfreie_absaetze("\n".join(frei))
