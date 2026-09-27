# -*- coding: utf-8 -*-
"""Select rows across a long result list and preserve their evidence paths.

When a KWIC list exceeds the view limit, select evenly across it so later
corpus sections can appear. Each displayed row keeps its original path.
The model view, evidence entries and package therefore resolve ``rows[i]``
to the same row of the tool result through ``zeilen_nach_pfad``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

#: Der Schlüssel, unter dem eine gezeigte Zeile ihren Pfad im Werkzeugergebnis trägt.
PFAD = "pfad"

#: The lists whose shown entries carry their path: KWIC and table rows, and
#: the periods of a thinned trend series (perioden_mit_pfad).
_BEHAELTER = ("rows", "periods")

_PFAD_MUSTER = re.compile(r"^(rows|periods)\[(\d+)\]$")


def auswahlangabe(gesamt: int) -> str:
    """Was ``grounding_selection`` über eine gleichmäßig verteilte Auswahl sagt."""
    return f"gleichmäßig über rows[0] bis rows[{int(gesamt) - 1}], Pfad je Zeile"


def mit_pfad(zeilen: List[Dict[str, Any]], nummern: List[int]) -> List[Dict[str, Any]]:
    """Die gezeigten Zeilen, jede mit ihrem Pfad, wenn sie kein Anfang der Liste sind.

    Ein Anfang braucht keinen Pfad: dort ist der Platz in der Sicht der Index im
    Werkzeugergebnis, und die Sicht bleibt, wie sie war.
    """
    if list(nummern) == list(range(len(nummern))):
        return zeilen
    return [{PFAD: f"rows[{nummer}]", **zeile} for nummer, zeile in zip(nummern, zeilen)]


def zeilennummer(zeile: Any, platz: int, behaelter: str = "rows") -> int:
    """Der Index einer gezeigten Zeile im Werkzeugergebnis, sonst ihr Platz."""
    treffer = _PFAD_MUSTER.match(str(zeile.get(PFAD) or "")) if isinstance(zeile, Mapping) else None
    return int(treffer.group(2)) if treffer and treffer.group(1) == behaelter else platz


def perioden_mit_pfad(flaeche: Any, ausgabe: Any) -> Any:
    """The shown periods of a thinned series, each with its path in the tool result.

    Englischprobe 2026-09-27, run a1: trend_analysis returned 60 periods, the
    view showed 20 of them as a plain list, and the package numbered them
    anew (``periods[1]`` was 1948 there, 1946 in the tool result). A shown
    period is found in the tool result by its label. A series shown from its
    start, an ambiguous label or a period that is not found leaves the
    surface as it is.
    """
    gezeigt = flaeche.get("periods") if isinstance(flaeche, Mapping) else None
    alle = ausgabe.get("periods") if isinstance(ausgabe, Mapping) else None
    if not isinstance(gezeigt, list) or not gezeigt or not isinstance(alle, list):
        return flaeche
    platz_je_periode: Dict[str, int] = {}
    for nummer, periode in enumerate(alle):
        name = str(periode.get("period")) if isinstance(periode, Mapping) else None
        if name is None or name in platz_je_periode:
            return flaeche
        platz_je_periode[name] = nummer
    nummern: List[int] = []
    for periode in gezeigt:
        if not isinstance(periode, Mapping) or PFAD in periode:
            return flaeche
        nummer = platz_je_periode.get(str(periode.get("period")))
        if nummer is None:
            return flaeche
        nummern.append(nummer)
    if nummern == list(range(len(nummern))):
        return flaeche
    return {
        **flaeche,
        "periods": [{PFAD: f"periods[{nummer}]", **periode} for nummer, periode in zip(nummern, gezeigt)],
    }


def ohne_pfad(zeile: Any) -> Any:
    """Die Zeile ohne ihren Pfad, für Darstellung und aufgelöste Werte."""
    if isinstance(zeile, Mapping) and PFAD in zeile:
        return {schluessel: wert for schluessel, wert in zeile.items() if schluessel != PFAD}
    return zeile


def zeilen_nach_pfad(flaeche: Any) -> Any:
    """Die Oberfläche mit ihren gezeigten Zeilen an ihren Plätzen im Werkzeugergebnis.

    Für die Auflösung von ``rows[i]`` und ``periods[i]``: eine gezeigte Zeile
    steht an ihrem Index, jede andere Stelle ist leer, und die Auflösung liest
    dort die Belegaufzeichnung mit allen Zeilen. Ohne Pfade bleibt die
    Oberfläche, wie sie ist.
    """
    if not isinstance(flaeche, Mapping):
        return flaeche
    ergebnis = flaeche
    for behaelter in _BEHAELTER:
        zeilen = flaeche.get(behaelter)
        if not isinstance(zeilen, list) or not any(
            isinstance(zeile, Mapping) and PFAD in zeile for zeile in zeilen
        ):
            continue
        nummern = [zeilennummer(zeile, platz, behaelter) for platz, zeile in enumerate(zeilen)]
        plaetze: List[Any] = [None] * (max(nummern) + 1)
        for nummer, zeile in zip(nummern, zeilen):
            plaetze[nummer] = ohne_pfad(zeile)
        ergebnis = {**ergebnis, behaelter: plaetze}
    return ergebnis
