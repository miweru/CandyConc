#!/usr/bin/env python3
"""Erzeugt den Frontend-Spiegel des Methodenkatalogs aus METHOD_META.

``candyconc-web/src/lib/measureCatalog.ts`` traegt seit jeher den Hinweis
"GENERIERT aus METHOD_META, NICHT von Hand editieren", nur gab es das
erzeugende Skript nicht. Der Spiegel wurde also doch von Hand gepflegt, und
am 2026-08-30 fehlten ihm ``lrc`` und ``logdice_window``, also genau die
beiden Masse, die diese Kampagne neu eingezogen hat. Der Kontrakt-Test
``measureCatalogContract.test.ts`` stand deshalb rot.

Aufruf:

    python3 scripts/gen_measure_catalog.py            # schreibt
    python3 scripts/gen_measure_catalog.py --pruefen  # meldet nur Abweichung
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ZIEL = APP.parent / "candyconc-web" / "src" / "lib" / "measureCatalog.ts"

# Genau die Felder, die der Kontrakt-Test byte-identisch pinnt.
FELDER = (
    "name",
    "latex_formula",
    "smoothing",
    "sort_key",
    "formula_mathml",
    "explanation",
    "reference",
)

ANKER = "export const MEASURE_CATALOG"
# Der Katalog ist nicht das Dateiende. Darunter stehen Alias-Tabelle und
# Nachschlagfunktion, beides Handarbeit. Ein Generator, der ab dem Anker
# einfach weiterschreibt, loescht sie still.
SCHWANZ_ANKER = "/** Nachschlag mit Normalisierung"


def _rendern(method_meta: dict, kopf: str, schwanz: str) -> str:
    teile = [kopf, "export const MEASURE_CATALOG: Record<string, MeasureCatalogEntry> = {\n"]
    for name, eintrag in method_meta.items():
        teile.append(f"  {json.dumps(name)}: {{\n")
        letztes = FELDER[-1]
        for feld in FELDER:
            wert = json.dumps(eintrag.get(feld, ""), ensure_ascii=False)
            komma = "" if feld == letztes else ","
            teile.append(f"    {json.dumps(feld)}: {wert}{komma}\n")
        teile.append("  },\n")
    teile.append("}\n\n")
    teile.append(schwanz)
    return "".join(teile)


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--pruefen", action="store_true",
                          help="nur melden, ob der Spiegel abweicht")
    args = zerleger.parse_args()

    sys.path.insert(0, str(APP / "src"))
    from candyconc.analysis_defaults import METHOD_META

    bestand = ZIEL.read_text(encoding="utf-8")
    schnitt = bestand.index(ANKER)
    schwanz_ab = bestand.index(SCHWANZ_ANKER)
    if schwanz_ab < schnitt:
        raise SystemExit("Dateiaufbau unerwartet: der Schwanz steht vor dem Katalog.")
    # Alles vor dem Katalog und alles danach ist Handarbeit und bleibt stehen.
    neu = _rendern(METHOD_META, bestand[:schnitt], bestand[schwanz_ab:])

    if neu == bestand:
        print(f"Spiegel ist aktuell ({len(METHOD_META)} Masse).")
        return 0
    if args.pruefen:
        print(f"Spiegel weicht ab. {ZIEL} neu erzeugen mit:")
        print("  python3 scripts/gen_measure_catalog.py")
        return 1
    ZIEL.write_text(neu, encoding="utf-8")
    print(f"Spiegel neu geschrieben: {len(METHOD_META)} Masse nach {ZIEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
