"""Regenerate src/lib/measureCatalog.ts from the backend METHOD_META.

    PYTHONPATH=<repo>/app/src python scripts/generate_measure_catalog.py

Writes the German catalogue (MEASURE_CATALOG, the default rendering of the
backend) and the English catalogue (MEASURE_CATALOG_EN). The contract test
src/__tests__/lib/measureCatalogContract.test.ts compares both with the
backend field by field.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candyconc.analysis_defaults import METHOD_META
from candyconc.i18n import localize

FIELDS = ("name", "latex_formula", "smoothing", "sort_key", "formula_mathml", "explanation", "reference")
TARGET = Path(__file__).resolve().parents[1] / "src" / "lib" / "measureCatalog.ts"
START = "export const MEASURE_CATALOG: Record<string, MeasureCatalogEntry> = {"
END_MARKER = "/** Nachschlag mit Normalisierung"


def _block(name: str, language: str) -> str:
    rendered = localize(METHOD_META, language)
    entries = {key: {field: str(entry.get(field, "")) for field in FIELDS} for key, entry in rendered.items()}
    body = json.dumps(entries, ensure_ascii=False, indent=2)
    body = re.sub(r"\n\}$", ",\n}", body)
    return f"export const {name}: Record<string, MeasureCatalogEntry> = {body}\n"


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    start = source.index(START)
    end = source.index(END_MARKER)
    # The German rendering is data, not an untranslated interface text: the
    # i18n check skips the generated block (start marker stays above START).
    generated = (
        _block("MEASURE_CATALOG", "de") + "\n" + _block("MEASURE_CATALOG_EN", "en") + "// i18n-ignore-end\n\n"
    )
    TARGET.write_text(source[:start] + generated + source[end:], encoding="utf-8")


if __name__ == "__main__":
    main()
