"""Bind German rate labels to a supported preceding number.

In "12,5 Treffer pro Million", the rate precedes its label. When that
adjacent number is supported by a ``per_million`` or ``*_per_million``
field, bind the label to it rather than to a subsequent raw count.
Otherwise retain the existing forward binding.

Evidence markers belong to the preceding number and do not break adjacency.
Forward binding must not cross a sentence boundary.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Iterator, Mapping

#: Das Feld, auf das die Ratennamen (pmw, per_million, pro Million, per
#: million) in ``_MASSNAME_ZU_FELD`` zeigen.
RATENFELD = "per_million"

#: Eine Zahl, die kurz vor dem Namen endet. Der Abstand ist höchstens so
#: lang wie das Fenster hinter dem Namen (14 Zeichen) und darf ein Wort
#: enthalten ("326,6 Treffer pro Million"), aber keine Ziffer, keinen
#: Zeilenumbruch und kein Satzzeichen. Eine Zahl aus dem vorigen Satz oder
#: Satzglied zählt damit nicht. Das Lookbehind schließt Ziffern aus
#: Kennungen wie ``E_query_count_2`` aus.
_ZAHL_DAVOR = re.compile(
    r"(?<![\w.,])(?P<zahl>-?\d(?:[\d.,]*\d)?)(?P<luecke>[^\d\n.,;:!?]{0,14})$"
)

# An evidence marker and its preceding whitespace belong to the number.
# Ignore them when checking adjacency between a rate and its label.
_MARKE = re.compile(r"\s*(?:\[\[beleg:[^\]\n]*\]\]|\{\{ev:[^}\n]*\}\})")


def zahl_unmittelbar_davor(text: str, anfang: int, namen: Iterable[str]) -> str:
    """Die Zahl, die unmittelbar vor ``text[anfang:]`` endet, sonst ``""``.

    Steht zwischen ihr und ``anfang`` ein anderer Maßname aus ``namen``,
    gehört sie ihm und nicht dem Namen bei ``anfang``.
    """
    fenster = _MARKE.sub("", text[max(0, anfang - 240):anfang])
    treffer = _ZAHL_DAVOR.search(fenster, max(0, len(fenster) - 64))
    if treffer is None:
        return ""
    luecke = treffer.group("luecke").casefold()
    if any(name in luecke for name in namen):
        return ""
    return treffer.group("zahl")


def massnamen_ohne_rate_davor(
    text: str,
    muster: "re.Pattern[str]",
    feld_je_name: Mapping[str, str],
    rate_gedeckt: Callable[[str], bool],
) -> Iterator["re.Match[str]"]:
    """Die Treffer von ``muster`` wie bei ``finditer``, ohne gebundene Ratennamen.

    Ein Ratenname, vor dem unmittelbar eine Zahl steht, für die
    ``rate_gedeckt`` wahr ist, gilt dieser Zahl und wird ausgelassen. Die
    Suche läuft dann hinter dem NAMEN weiter, nicht hinter der Zahl, die das
    Muster ihm angehängt hätte. Sonst würde ein zweiter Name in diesem
    Stück ("326,6 pro Million (pmw 46.398)") nie geprüft.
    """
    anfang = 0
    while True:
        treffer = muster.search(text, anfang)
        if treffer is None:
            return
        name = " ".join(treffer.group("name").casefold().split())
        # "(pmw)" allein in Klammern fuehrt eine Abkuerzung ein und benennt
        # keine Zahl dahinter: "51,8 pro Mio. Woertern (pmw) bei 7351
        # Treffern" bekam den Hinweis 'pmw 7351' (Pruefer Nachbearbeitung,
        # zyklus6_teil2 a8d2e3c4). "(pmw 46.398)" bleibt eine Bindung.
        vor = text[:treffer.start("name")].rstrip()
        nach = text[treffer.end("name"):].lstrip()
        if vor.endswith("(") and nach.startswith(")"):
            anfang = treffer.end("name")
            continue
        if feld_je_name.get(name) == RATENFELD:
            zahl = zahl_unmittelbar_davor(text, treffer.start(), feld_je_name)
            if zahl and rate_gedeckt(zahl):
                anfang = treffer.end("name")
                continue
        anfang = treffer.end()
        yield treffer
