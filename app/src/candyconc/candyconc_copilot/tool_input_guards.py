"""Wachen an der EINGABE der Copilot-Werkzeuge.

Gegenstueck zu :mod:`finding_substance`, das die AUSGABE bewacht. Hier
wird abgewiesen, bevor gerechnet wird, weil das Ergebnis sonst leer waere
und wie ein Befund aussaehe.
"""

from __future__ import annotations

from typing import Any

from candyconc.candyconc_copilot.tool_errors import ToolInputError


def pruefe_metadatenfelder(idx: Any, filters: Any) -> None:
    """Reject unknown metadata filters before interpreting an empty result.

    Apply the same guard across copilot tools with raw metadata filters.
    Resolve aliases before checking field names, then validate their values.
    Engine and REST empty-result semantics remain separate from this tool guard.
    """

    if not filters:
        return
    from candyconc.core.meta_filters import (
        metadata_fields as _felder,
        unbekannte_felder as _unbekannt,
        unbekannte_werte as _unbekannte_werte,
    )

    gepruefte = dict(filters)
    try:
        from candyconc.services.backend.docsets import (
            translate_meta_field_aliases as _alias,
        )

        gepruefte = dict(_alias(gepruefte) or gepruefte)
    except Exception:
        pass

    offen = _unbekannt(idx, gepruefte)
    if offen:
        vorhanden = ", ".join(_felder(idx)) or "keine"
        raise ToolInputError(
            "Unbekannte Metadatenfelder: "
            + ", ".join(offen)
            + ". Vorhanden sind: "
            + vorhanden
            + ". Ein unbekanntes Feld trifft nichts, das Ergebnis waere leer "
            "und saehe wie ein Befund aus."
        )

    # Die WERTEbene derselben Regel (Diagnose Lauf 3, Naht 4): der Wert
    # „ai" im Feld „model" lieferte success mit 0 Dokumenten, das Modell
    # rechnete gegen die leere Gegenseite und las daraus einen Befund.
    # Vertrag wie die Engine (Gleichheit auch in der str-Form), Range-
    # Dikte bleibt ungeprueft.
    befunde = _unbekannte_werte(idx, gepruefte)
    if not befunde:
        return
    feld, wert, vorhanden_werte = befunde[0]
    raise ToolInputError(
        "Wert " + repr(wert)
        + " ist kein Wert des Felds " + repr(feld)
        + ". Vorhandene Werte: "
        + (", ".join(vorhanden_werte) or "keine")
        + ". Ein Wert ausserhalb des Inventars trifft nichts, das "
        "Ergebnis waere leer und saehe wie ein Befund aus."
    )
