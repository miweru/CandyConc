"""Label metadata inventories with their complete value counts.

The tool returns a complete list, so its length is the inventory size.
A shortened display reports that size and keeps the field visible even
when its values exceed the display limit.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Mapping

from candyconc.answer_language import choose as _t


def metadatenbestand_zeilen(
    args: Mapping[str, Any],
    raw: Mapping[str, Any],
    normalisieren: Callable[[Any], str],
    formatieren: Callable[[Any], str],
) -> List[str]:
    """Die Steckbriefzeilen zum Metadateninventar eines Turns."""

    # DIE WERTEZAHL KOMMT AUS value_counts, NICHT AUS DER LISTENLAENGE.
    #
    # Ein erster Anlauf am 2026-08-29 zaehlte len(payload). Das war falsch,
    # und zwar schlimmer als der Defekt davor: extract_raw_surface kuerzt
    # die Werteliste auf ACHT Eintraege, bevor sie hier ankommt. Ein Feld
    # mit 10 Werten erschien als "3 von 8 Werten", eines mit 12 ebenfalls
    # als "3 von 8". Die Zahl saettigte bei acht und war weder Stichprobe
    # noch Inventar. Die richtige Zahl liegt im selben Objekt einen
    # Schluessel daneben.
    echte_zahlen = raw.get("value_counts")
    if not isinstance(echte_zahlen, Mapping):
        echte_zahlen = {}
    gekuerzte = raw.get("sampled_value_fields")
    gekuerzte = set(gekuerzte) if isinstance(gekuerzte, (list, tuple, set)) else set()

    bits: List[str] = []
    fields = args.get("fields")
    if isinstance(fields, list) and fields:
        bits.append(
            _t("angefragte Felder: ", "requested fields: ")
            + ", ".join(str(field) for field in fields[:12])
        )
    values = raw.get("values")
    if isinstance(values, dict):
        visible_values: List[str] = []
        for field_name, payload in values.items():
            if re.search(
                r"(?:^|_)(?:id|path|hash|url|text|content|snippet)$",
                str(field_name),
                re.IGNORECASE,
            ):
                continue
            if isinstance(payload, dict):
                count = payload.get("count")
                samples = payload.get("sample")
            else:
                samples = payload
                # NUR ein Rueckfall. Die Laenge stimmt genau dann, wenn
                # die Liste nicht gekuerzt wurde, und das entscheidet
                # oben value_counts. Ein Anlauf, der HIER die Laenge zur
                # Wertezahl erklaerte, druckte fuer ein Feld mit zehn
                # Werten "3 von 8", weil extract_raw_surface auf acht
                # kuerzt.
                count = len(payload) if isinstance(payload, list) else None
            if not isinstance(samples, list):
                samples = (
                    [samples]
                    if samples not in (None, "")
                    else []
                )
            compact_samples = [
                normalisieren(value)
                for value in samples
                if normalisieren(value)
                and len(normalisieren(value)) <= 60
            ]
            if not compact_samples:
                continue
            # Keep fields with long inventories visible and label shortened values
            # with their full count.
            gezeigt = compact_samples[:12]
            # Vorrang: die AUSGEWIESENE Wertezahl. Erst wenn sie fehlt
            # und das Feld nachweislich nicht gekuerzt wurde, darf die
            # Listenlaenge einspringen.
            roh_zahl = echte_zahlen.get(field_name, count)
            if roh_zahl in (None, "") and field_name in gekuerzte:
                roh_zahl = None
            try:
                gesamt = int(roh_zahl) if roh_zahl not in (None, "") else None
            except (TypeError, ValueError):
                gesamt = None
            zusatz = (
                "" if gesamt is None
                else _t(" ({} von {} Werten)", " ({} of {} values)").format(
                    len(gezeigt), formatieren(gesamt))
                if gesamt > len(gezeigt)
                else _t(" ({} Werte)", " ({} values)").format(formatieren(gesamt)))
            visible_values.append(
                f"{field_name}={', '.join(gezeigt)}{zusatz}")
            if len(visible_values) >= 6:
                break
        if visible_values:
            bits.append(
                _t("sichtbare Werte: ", "visible values: ") + "; ".join(visible_values)
            )
    diagnostics = raw.get("diagnostics")
    if isinstance(diagnostics, dict):
        missing = diagnostics.get("missing_requested_fields")
        if isinstance(missing, list) and missing:
            bits.append(
                _t("nicht belegt: ", "not present: ")
                + ", ".join(str(field) for field in missing[:12])
            )
    return bits
