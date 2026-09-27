# -*- coding: utf-8 -*-
"""Check that a table delivers the row count promised by its heading.

Grounding cleanup can remove rows while leaving a heading such as Top-10
unchanged. Compare the visible promise with the remaining rows and explain
a shortfall. This deterministic check also covers rows omitted for other reasons.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from candyconc.answer_language import choose as _t

#: Eine Ueberschrift, die eine Zeilenzahl zusagt. "Top-10", "Top 10",
#: "die 10 staerksten". Ohne Zusage gibt es nichts zu pruefen.
_ZUSAGE = re.compile(r"(?i)\bTop[\s\-]?(\d{1,3})\b")

# A negated promise such as "kein Top-100-Ausschnitt" commits to no row count.
_VERNEINT = re.compile(r"(?i)\b(?:kein\w*|nicht|statt|anstatt|ohne|not|no)\s+(?:[\w-]+\s+)?$")

#: Ein Satzende, das keine Ziffer abschliesst („2. Top-10“ ist eine Nummer).
_SATZENDE = re.compile(r"(?<!\d)[.!?](?:\s|$)")

#: Belegmarken zaehlen nicht zum Wortlaut einer Zeile.
_MARKE = re.compile(r"\[\[beleg:[^\]]*\]\]|\{\{ev:[^}]*\}\}")


def _ist_ueberschrift(kopf: str) -> bool:
    """Only headings promise a row count. Prose mentioning a top list does not."""
    if re.match(r"^\s{0,3}#{1,6}\s", kopf):
        return True
    return not _SATZENDE.search(_MARKE.sub("", kopf).strip())


#: Eine Markdown-Trennzeile (|---|---|), die keine Datenzeile ist.
_TRENNZEILE = re.compile(r"^\|[\s:\-|]+\|$")


def _zeilen_der_tabelle(rest: str) -> Tuple[int, bool]:
    """Datenzeilen der ERSTEN Tabelle in ``rest``, und ob es eine gab."""
    zeilen: List[str] = []
    kopf_gesehen = False
    for roh in rest.split("\n"):
        s = roh.strip()
        if not s:
            if zeilen or kopf_gesehen:
                break
            continue
        if not s.startswith("|"):
            if zeilen or kopf_gesehen:
                break
            continue
        if _TRENNZEILE.match(s):
            kopf_gesehen = True
            # Die Zeile ueber der Trennlinie war die Kopfzeile.
            if zeilen:
                zeilen.pop()
            continue
        zeilen.append(s)
    return len(zeilen), bool(zeilen or kopf_gesehen)


def luecken(antwort: str) -> List[Tuple[str, int, int]]:
    """``(ueberschrift, zugesagt, tatsaechlich)`` je gebrochener Zusage."""
    if not antwort:
        return []
    gefunden: List[Tuple[str, int, int]] = []
    for zeile in re.finditer(r"(?m)^.*$", antwort):
        kopf = zeile.group(0)
        treffer = _ZUSAGE.search(kopf)
        if not treffer or not _ist_ueberschrift(kopf):
            continue
        if _VERNEINT.search(kopf[:treffer.start()]):
            continue
        zugesagt = int(treffer.group(1))
        if zugesagt <= 0 or zugesagt > 500:
            continue
        anzahl, gab_tabelle = _zeilen_der_tabelle(antwort[zeile.end():])
        if not gab_tabelle or anzahl == 0:
            continue
        if anzahl < zugesagt:
            gefunden.append((kopf.strip(), zugesagt, anzahl))
    return gefunden


#: Eine Markdown-Ueberschrift.
_UEBERSCHRIFT = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def leere_abschnitte(antwort: str) -> List[str]:
    """Ueberschriften, unter denen nichts steht.

    Zweites Gesicht desselben Defekts. Entfernt die Zitatwache EINE Zeile
    einer Tabelle, verspricht die Ueberschrift zu viel (siehe ``luecken``).
    Entfernt sie ALLE, bleibt eine Ueberschrift ohne Inhalt stehen. Gemessen
    am 2026-08-31, Frage variation-1: "### Sichtbare gerichtete
    Keyness-Ergebnisse" stand unmittelbar vor "### Weiterfuehrende Fragen",
    ueber einem Lauf mit 138.445 Zeilen.

    Der Renderer selbst ist unschuldig: er gibt bei null ueberlebenden
    Zeilen "" zurueck. Die Ueberschrift kam MIT Tabelle und wurde danach
    entkernt.

    Der Methodensteckbrief nennt den Lauf weiterhin vollstaendig (Richtung,
    Ziel- und Referenzkorpus, Tokenzahlen), es geht also keine Auskunft
    verloren, wenn die leere Ueberschrift faellt.
    """
    if not antwort:
        return []
    zeilen = antwort.split("\n")
    leer: List[str] = []
    for i, z in enumerate(zeilen):
        if not _UEBERSCHRIFT.match(z):
            continue
        for folge in zeilen[i + 1:]:
            if not folge.strip():
                continue
            # A deeper heading remains part of the current section's content.
            if _UEBERSCHRIFT.match(folge) and len(folge.split()[0]) <= len(z.split()[0]):
                leer.append(z.strip())
            break
        else:
            leer.append(z.strip())
    return leer


def ohne_leere_abschnitte(antwort: str) -> str:
    """Entfernt Ueberschriften, unter denen nichts steht."""
    zu_entfernen = set(leere_abschnitte(antwort))
    if not zu_entfernen:
        return antwort
    behalten = [z for z in antwort.split("\n") if z.strip() not in zu_entfernen]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(behalten))


def saetze(antwort: str) -> List[str]:
    """Ein Satz je gebrochener Zusage, oder nichts."""
    aus: List[str] = []
    for kopf, zugesagt, anzahl in luecken(antwort):
        name = kopf.rstrip(":").strip()
        aus.append(_t(
            "Die Tabelle „{n}“ führt {a} statt {z} Zeilen. "
            "Es fehlt mindestens eine, deren Beleg sich nicht auflösen ließ, "
            "und sie ist nicht notwendig die schwächste.",
            "The table “{n}” lists {a} instead of {z} rows. At least one row "
            "is missing whose evidence could not be resolved, and it is not "
            "necessarily the weakest.",
        ).format(n=name, a=anzahl, z=zugesagt))
    return aus
