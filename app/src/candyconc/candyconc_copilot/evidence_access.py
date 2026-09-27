# -*- coding: utf-8 -*-
"""Wie man an einen Beleg herankommt, egal in welcher Gestalt er vorliegt.

Am 2026-08-30 haben zwei an einem Tag gebaute Wachen (question_coverage,
row_spelling_note) auf dem Produktpfad NICHTS gemeldet. Beide lasen
``getattr(eintrag, "raw_surface", None)``. Der Orchestrator fuehrt seine
Belege aber als ``List[Dict[str, Any]]`` (orchestrator.py:954), und an einem
dict liefert ``getattr`` nichts.

Beide Testreihen waren gruen, weil sie sich Objekte mit Attributen erfunden
haben statt der dicts, die die Produktion benutzt. Genau die Klasse, gegen
die die Lektion vom selben Tag geschrieben wurde: eine Wache gilt erst als
gebaut, wenn sie den ECHTEN Ausfall einmal gefangen hat.

Diese Datei ist die eine Naht, an der der Zugriff stattfindet. Wer sie
benutzt, kann die Gestalt nicht mehr verfehlen.
"""

from __future__ import annotations

from typing import Any, Mapping


def feld(eintrag: Any, name: str, ersatz: Any = None) -> Any:
    """Ein Feld eines Belegs, aus dict ODER Objekt.

    Die Reihenfolge ist Absicht: der Produktpfad fuehrt dicts, also wird
    zuerst dort gesucht.
    """
    if isinstance(eintrag, Mapping):
        wert = eintrag.get(name, ersatz)
        return ersatz if wert is None else wert
    wert = getattr(eintrag, name, ersatz)
    return ersatz if wert is None else wert


def flaeche(eintrag: Any) -> Mapping[str, Any] | None:
    """Die ``raw_surface`` eines Belegs, oder None."""
    wert = feld(eintrag, "raw_surface")
    return wert if isinstance(wert, Mapping) else None


def belegflaeche(eintrag: Any) -> Mapping[str, Any] | None:
    """Die UNBESCHRAENKTE Aufzeichnung, sonst die Modellsicht.

    ``raw_surface`` ist die gekuerzte Modellsicht, ``fact_surface`` die
    vollstaendige Aufzeichnung, gegen die spaeter geprueft wird. Eine Wache
    prueft, also liest sie die Aufzeichnung. Der Rueckfall ist da, weil
    ``to_dict(include_fact_surface=False)`` an einer Naht bewusst kuerzt.
    """
    wert = feld(eintrag, "fact_surface")
    if isinstance(wert, Mapping):
        return wert
    return flaeche(eintrag)


def zeilen(eintrag: Any) -> list:
    """Die Ergebniszeilen eines Belegs.

    Sie liegen UNTER ``rows``, nicht auf der obersten Ebene der Oberflaeche.
    Eine Wache, die oben sucht, findet nie etwas und meldet das nicht.
    """
    flaechen = belegflaeche(eintrag)
    if not isinstance(flaechen, Mapping):
        return []
    reihen = flaechen.get("rows")
    return [z for z in reihen if isinstance(z, Mapping)] if isinstance(reihen, list) else []
