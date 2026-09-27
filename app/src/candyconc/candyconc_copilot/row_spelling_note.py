# -*- coding: utf-8 -*-
"""Explain the spellings represented by a folded keyness row.

Counting uses str.lower, so a class combines capitalization variants while
keeping sharp s distinct from ss. Its display label comes from a lexicon ID
and can differ from the spelling responsible for most hits.

When an answer names that label and its count without the contributing
spelling, add a deterministic note from surface_variants. Require a numeric
claim so ordinary uses of common words do not trigger the note.
"""

from __future__ import annotations

from candyconc.answer_language import choose as _t, format_int

import re
from typing import Any, List, Mapping, Sequence

from .evidence_access import zeilen as _zeilen

#: Ab welchem Anteil das Etikett als tragend durchgeht. Darunter wird
#: gemeldet. 0,5 ist kein gewaehlter Schwellenwert, sondern die Grenze, ab
#: der die Mehrheit der Treffer ANDERS geschrieben ist als das, was dasteht.
MEHRHEIT = 0.5


def _zeilen_mit_schreibungen(evidenz: Sequence[Any]) -> List[Mapping[str, Any]]:
    """Alle Belegzeilen, die eine Aufschluesselung tragen.

    Die Zeilen liegen unter ``rows`` der Belegaufzeichnung, nicht auf der
    obersten Ebene. Der erste Entwurf suchte oben und fand deshalb nie etwas.
    """
    gefunden: List[Mapping[str, Any]] = []
    for eintrag in evidenz or ():
        for zeile in _zeilen(eintrag):
            teile = zeile.get("surface_variants")
            if isinstance(teile, Mapping) and teile and zeile.get("word"):
                gefunden.append(zeile)
    return gefunden


def abweichende_schreibung(zeile: Mapping[str, Any]) -> tuple[str, str, int, int] | None:
    """``(etikett, tragende_schreibung, anteil_des_etiketts, gesamt)`` oder None.

    Gemeldet wird die Seite, auf der das Etikett am wenigsten traegt. Ist es
    ueberall in der Mehrheit, gibt es nichts zu melden: dann sagt die Zeile
    im Wesentlichen die Wahrheit.
    """
    etikett = str(zeile.get("word") or "")
    teile = zeile.get("surface_variants")
    if not etikett or not isinstance(teile, Mapping):
        return None
    schlimmste = None
    for schreibungen in teile.values():
        if not isinstance(schreibungen, Mapping) or not schreibungen:
            continue
        gesamt = sum(int(v or 0) for v in schreibungen.values())
        if gesamt <= 0:
            continue
        eigen = int(schreibungen.get(etikett) or 0)
        if eigen / gesamt >= MEHRHEIT:
            continue
        traegt = max(schreibungen.items(), key=lambda kv: int(kv[1] or 0))[0]
        if schlimmste is None or eigen / gesamt < schlimmste[2] / max(schlimmste[3], 1):
            schlimmste = (etikett, str(traegt), eigen, gesamt)
    return schlimmste


def satz(zeile: Mapping[str, Any]) -> str:
    """Ein Satz, der die Zeile ehrlich macht, oder leer."""
    befund = abweichende_schreibung(zeile)
    if befund is None:
        return ""
    etikett, traegt, eigen, gesamt = befund
    if eigen == 0:
        # Use singular wording for one hit.
        artikel = "den" if gesamt == 1 else "die"
        return (
            _t(f"Die Zeile „{etikett}“ zählt eine Schreibungsklasse: {artikel} {gesamt} "
            f"Treffer trägt „{traegt}“, „{etikett}“ selbst kommt dort nicht vor.", f"""The row "{etikett}" counts a spelling class: the {format_int(gesamt)} hits use "{traegt}", while "{etikett}" itself does not occur there.""")
        )
    return (
        _t(f"Die Zeile „{etikett}“ zählt eine Schreibungsklasse: von den {gesamt} "
        f"Treffern trägt „{etikett}“ selbst {eigen}, die Mehrheit trägt „{traegt}“.", f"""The row "{etikett}" counts a spelling class: of {format_int(gesamt)} hits, {format_int(eigen)} use "{etikett}" itself and the majority use "{traegt}".""")
    )


def _zahl_kommt_vor(zahl: int, antwort: str) -> bool:
    """Steht diese Zahl in der Antwort, mit oder ohne Tausenderpunkt?"""
    for form in (str(zahl), format_int(zahl)):
        # Match a complete numeric value. Reject a following digit block and
        # digits inside identifiers while allowing sentence-final punctuation.
        if re.search(
            rf"(?<!\w)(?<![.,_-]){re.escape(form)}(?!\d)(?![.,]\d)", antwort
        ):
            return True
    return False


def _wird_genannt(etikett: str, antwort: str) -> bool:
    r"""Steht das Etikett als eigenes Wort in der Antwort?

    NICHT als Teilzeichenkette. Der erste Entwurf pruefte mit ``in`` und
    meldete deshalb fuer die Zeile "Arm", wenn die Antwort "Die Armut steigt"
    sagte, also fuer eine Zeile, die niemand zitiert hatte. Eine Wache, die
    zu einer nicht genannten Zeile etwas anhaengt, ist Laerm, und Laerm macht
    die echten Meldungen unlesbar.

    Die Grenzen sind ``\w``-basiert und damit unicodefaehig: "Gruene" trifft
    nicht in "Gruenen". Anfuehrungszeichen und Satzzeichen sind keine
    Wortzeichen, "Arm" trifft also in einem zitierten Etikett.
    """
    return bool(_saetze_mit_etikett(etikett, antwort))


#: Satzgrenze oder Zeilenumbruch. "18.656" trennt nicht, weil nach dem Punkt
#: kein Leerraum steht.
_SATZGRENZE = re.compile(r"(?<=[.!?])\s+|\n+")


def _saetze_mit_etikett(etikett: str, antwort: str) -> List[str]:
    """Return sentences containing the label as a standalone word.

    A label embedded in a hyphenated compound does not identify the row.
    """
    if not etikett or not antwort:
        return []
    muster = re.compile(rf"(?<![\w-]){re.escape(etikett)}(?![\w-])")
    return [satz for satz in _SATZGRENZE.split(antwort) if muster.search(satz)]


def _zahl_zur_zeile_zitiert(zeile: Mapping[str, Any], antwort: str) -> bool:
    """Steht eine der Zahlen dieser Zeile in der Antwort?

    Geprueft werden die Summen je Seite, also genau die Zahlen, ueber die die
    Zeile eine Aussage macht.
    """
    teile = zeile.get("surface_variants")
    if not isinstance(teile, Mapping):
        return False
    for schreibungen in teile.values():
        if not isinstance(schreibungen, Mapping):
            continue
        summe = sum(int(v or 0) for v in schreibungen.values())
        if summe and _zahl_kommt_vor(summe, antwort):
            return True
    return False


def alle_saetze(antwort: str, evidenz: Sequence[Any]) -> List[str]:
    """Saetze fuer jede genannte Zeile, deren Etikett die Zahl nicht traegt.

    Nur fuer Etiketten, die in der Antwort WIRKLICH als Wort vorkommen. Eine
    Wache, die ueber alle 11.209 Zeilen meldet, ist keine Meldung, sondern
    Laerm.
    """
    if not antwort:
        return []
    gesehen: set[str] = set()
    saetze: List[str] = []
    for zeile in _zeilen_mit_schreibungen(evidenz):
        etikett = str(zeile.get("word") or "")
        saetze_mit_etikett = _saetze_mit_etikett(etikett, antwort)
        if etikett in gesehen or not saetze_mit_etikett:
            continue
        # Require the row's count in the same sentence as its label.
        # Common words can be class labels without referring to an evidence row,
        # and a number elsewhere in the answer cannot establish that connection.
        if not any(_zahl_zur_zeile_zitiert(zeile, satz) for satz in saetze_mit_etikett):
            continue
        text = satz(zeile)
        if text:
            gesehen.add(etikett)
            saetze.append(text)
    return saetze
