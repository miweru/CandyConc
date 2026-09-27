"""Expose the input counts of a measure quoted in an answer.

logDice uses 14 + log2(2*f / (node_frequency + f2)). The answer needs
``f2`` as well as the pair count and node frequency to make it reproducible.
Add that basis only when the answer names the collocate and its measure
and has not already supplied the count.

Run at ``politur_mit_zitatwache``, which every landing reaches, including
answers that bypass the verified-table renderer. The notice supplements
the quoted measure without duplicating the result table.
"""

from __future__ import annotations

import re
from typing import Any, List, Sequence

from candyconc.answer_language import choose as _t, format_int, is_english
from .evidence_access import belegflaeche, feld, zeilen

#: Hoechstens so viele Saetze. Eine Antwort, die zehn Grundlagen nachtraegt,
#: besteht aus Fussnoten.
MAX_SAETZE = 3


def _zahl_kommt_vor(zahl: float, antwort: str) -> bool:
    """Steht diese Zahl in der Antwort, deutsch oder englisch geschrieben?

    Geprueft werden beide Dezimaltrenner und beide ueblichen Rundungen. Die
    Wortgrenze verhindert, dass "11,5" in "11,52" trifft.
    """
    formen = set()
    for stellen in (2, 1):
        gerundet = f"{zahl:.{stellen}f}"
        formen.add(gerundet)
        formen.add(gerundet.replace(".", ","))
    for form in formen:
        if re.search(rf"(?<![\d.,]){re.escape(form)}(?![\d])", antwort):
            return True
    return False


def _ganzzahl_kommt_vor(zahl: int, antwort: str) -> bool:
    # An English answer groups with a comma (3,476). German answers keep the
    # German forms only, there 3,476 is a decimal number.
    formen = (str(zahl), f"{zahl:,}".replace(",", "."))
    if is_english():
        formen = (str(zahl), f"{zahl:,}")
    for form in formen:
        if re.search(rf"(?<!\w)(?<![.,]){re.escape(form)}(?!\d)(?![.,]\d)", antwort):
            return True
    return False


#: Satzgrenze: Satzzeichen, Leerraum und ein Satzanfang, oder ein Umbruch.
#: "Nummerierungen 7. mit logDice 9,68" trennt nicht, weil "mit" klein beginnt.
_SATZGRENZE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„\"(\[*_`#])|\n+")


def _saetze_mit_wort(wort: str, antwort: str) -> List[str]:
    """Die Saetze der Antwort, in denen das Kollokat als eigenes Wort steht."""
    muster = re.compile(rf"(?<![\w-]){re.escape(wort)}(?![\w-])")
    return [satz for satz in _SATZGRENZE.split(antwort) if muster.search(satz)]


#: Das Mass selbst beim Namen: im Satz oder im Kopf der Tabelle, in der er steht.
_LOGDICE = re.compile(r"log\s*dice", re.IGNORECASE)


def _table_header(piece: str, antwort: str) -> str:
    """Kopfzeile der Markdown-Tabelle, in der das Stueck steht, sonst leer."""
    zeilen = antwort.splitlines()
    for i, zeile in enumerate(zeilen):
        if piece.strip() and piece.strip() in zeile and zeile.lstrip().startswith("|"):
            while i > 0 and zeilen[i - 1].lstrip().startswith("|"):
                i -= 1
            return zeilen[i]
    return ""


def _names_logdice(satz: str, antwort: str) -> bool:
    return bool(_LOGDICE.search(satz) or _LOGDICE.search(_table_header(satz, antwort)))


def _de(zahl: int) -> str:
    """Integer with the thousands separator of the answer language."""
    return format_int(zahl)


def _kollokatzeilen(evidenz: Sequence[Any]):
    """(Zeile, node_frequency) je Kollokationsbeleg mit Knotenhaeufigkeit."""

    for eintrag in evidenz or []:
        if str(feld(eintrag, "tool", "")) != "collocate_stats":
            continue
        flaeche = belegflaeche(eintrag)
        if flaeche is None:
            continue
        knoten = feld(flaeche, "node_frequency")
        if knoten in (None, ""):
            continue
        try:
            knoten = int(knoten)
        except (TypeError, ValueError):
            continue
        if knoten <= 0:
            continue
        # zeilen() nimmt den BELEG, nicht die Flaeche: es holt sich die
        # Flaeche selbst. Der erste Anlauf uebergab die Flaeche, und die
        # Wache blieb still, ohne das zu melden. Genau der Fehler, vor dem
        # der Docstring von zeilen() warnt.
        for zeile in zeilen(eintrag):
            yield zeile, knoten


def saetze(antwort: str, evidenz: Sequence[Any]) -> List[str]:
    """Grundlagen fuer jeden genannten logDice-Wert, dessen f2 fehlt."""

    if not antwort:
        return []
    heraus: List[str] = []
    gesehen: set[str] = set()
    for zeile, knoten in _kollokatzeilen(evidenz):
        wort = str(feld(zeile, "word", ""))
        ld = feld(zeile, "logdice")
        f = feld(zeile, "f")
        f2 = feld(zeile, "f2")
        if not wort or ld in (None, "") or f in (None, "") or f2 in (None, ""):
            continue
        if wort in gesehen:
            continue
        try:
            ld_wert, f_wert, f2_wert = float(ld), int(f), int(f2)
        except (TypeError, ValueError):
            continue
        # Only supplement a measure actually named in the answer when its basis
        # is missing. Require the collocate, value and measure name in the same
        # sentence so an unrelated rate or an ordinary use of the word cannot
        # trigger a notice for a collocate that the answer never discussed.
        if not any(_zahl_kommt_vor(ld_wert, satz) and _names_logdice(satz, antwort)
                   for satz in _saetze_mit_wort(wort, antwort)):
            continue
        if _ganzzahl_kommt_vor(f2_wert, antwort):
            continue
        gesehen.add(wort)
        # Die Zahlen einzeln formatieren. Das Ersetzen ueber das ganze Stueck
        # machte aus dem trennenden Komma einen Punkt ("Kookkurrenz 541.
        # Korpusfrequenz des Kollokats 3.476 ...").
        heraus.append(_t(
            "logDice für „{w}“ entsteht aus Kookkurrenz {f}, "
            "Korpusfrequenz des Kollokats {f2} und Knotenfrequenz "
            "{k}: 14 + log2(2 · f / (Knoten + f2)).",
            "logDice for “{w}” is computed from co-occurrence frequency {f}, "
            "corpus frequency of the collocate {f2} and node frequency "
            "{k}: 14 + log2(2 · f / (node + f2)).",
        ).format(w=wort, f=_de(f_wert), f2=_de(f2_wert), k=_de(knoten)))
        if len(heraus) >= MAX_SAETZE:
            break
    return heraus
