# -*- coding: utf-8 -*-
"""Report rows excluded by the analysis-token filter.

The filter removes punctuation and formatting symbols before scoring. These
excluded rows can still explain a corpus contrast, so the answer reports the
removed count when it has not already done so.

The notice runs in ``politur_mit_zitatwache``, which every landing reaches.
It therefore also reaches answers that bypass the verified-table renderer.
The filter remains the source of the ranked analysis rows.
"""

from __future__ import annotations

import re
from typing import Any, List, Sequence

from candyconc.answer_language import choose as _t, is_english
from .evidence_access import belegflaeche

#: Hoechstens ein Satz je Antwort. Zwei Werkzeuge koennen im selben Turn
#: filtern, und zwei Fussnoten ueber denselben Sachverhalt sind eine zu
#: viel.
MAX_SAETZE = 1


def _zahl_kommt_vor(zahl: int, antwort: str) -> bool:
    """Nennt die Antwort diese Zahl bereits?

    Wortgleich zu ``massgrundlagen._ganzzahl_kommt_vor``: beide Schreibungen
    der Tausendertrennung, und die Grenzen verhindern, dass 20 in 201 oder
    in 1,20 trifft.
    """
    formen = (str(zahl), f"{zahl:,}" if is_english() else f"{zahl:,}".replace(",", "."))
    for form in formen:
        if re.search(rf"(?<!\w)(?<![.,]){re.escape(form)}(?!\d)(?![.,]\d)", antwort):
            return True
    return False


def _bilanz(flaeche: Any) -> tuple[int, List[str]] | None:
    """Zahl und Spitze aus EINER Werkzeugflaeche, oder None."""
    if not isinstance(flaeche, dict):
        return None
    diagnostik = flaeche.get("diagnostics")
    if not isinstance(diagnostik, dict):
        return None
    try:
        anzahl = int(diagnostik.get("gefiltert"))
    except (TypeError, ValueError):
        return None
    if anzahl <= 0:
        return None
    spitze = [
        str(eintrag).strip()
        for eintrag in (diagnostik.get("gefiltert_spitze") or [])
        if str(eintrag).strip()
    ]
    return anzahl, spitze


def saetze(antwort: str, evidenz: Sequence[Any]) -> List[str]:
    """Ein Satz ueber die verworfenen Zeilen, sonst nichts.

    Gelesen wird ueber ``evidence_access.belegflaeche``, also die
    UNBESCHRAENKTE Aufzeichnung. Die Modellsicht kappt die Diagnostik, und
    eine Wache, die die Darstellung statt der Messung liest, meldet
    irgendwann das Falsche.
    """
    text = str(antwort or "")
    gesammelt: List[str] = []
    for eintrag in evidenz or []:
        bilanz = _bilanz(belegflaeche(eintrag))
        if bilanz is None:
            continue
        anzahl, spitze = bilanz
        if _zahl_kommt_vor(anzahl, text):
            continue
        wort = _t("Zeile", "row") if anzahl == 1 else _t("Zeilen", "rows")
        satz = _t(
            "Vor der Rangfolge hat der Analyse-Token-Filter {} "
            "{} ohne alphanumerisches Zeichen verworfen",
            "Before ranking, the word token filter discarded {} "
            "{} without an alphanumeric character",
        ).format(anzahl, wort)
        if spitze:
            satz += _t(", die stärksten davon ", ", the strongest of them ") + ", ".join(spitze)
        gesammelt.append(satz + ".")
        if len(gesammelt) >= MAX_SAETZE:
            break
    return gesammelt
