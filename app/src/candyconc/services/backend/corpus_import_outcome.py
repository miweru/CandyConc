"""Durable, bounded provenance for a completed corpus import.

Import jobs are intentionally in-memory and disappear on a backend restart. The
quality outcome must not disappear with them: activating a corpus with rejected
input is a research decision, not an accidental side effect of restarting the
server. This tiny file is written into the published corpus directory and read
by the catalogue without opening the index.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from candyconc.i18n import LocalizedText, bilingual_form, lt


IMPORT_OUTCOME_FILENAME = "import_outcome.json"
IMPORT_OUTCOME_SCHEMA_VERSION = "candyconc-import-outcome-v1"
_MAX_WARNINGS = 32
_MAX_WARNING_LENGTH = 500


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _warning(item: Any) -> str:
    # Warnings are kept in both languages: LocalizedText in memory,
    # {"de": ..., "en": ...} in the file (older files hold plain strings).
    if isinstance(item, LocalizedText):
        return lt(item.de.strip()[:_MAX_WARNING_LENGTH], item.en.strip()[:_MAX_WARNING_LENGTH])
    if isinstance(item, Mapping) and isinstance(item.get("de"), str) and isinstance(item.get("en"), str):
        return lt(item["de"].strip()[:_MAX_WARNING_LENGTH], item["en"].strip()[:_MAX_WARNING_LENGTH])
    return str(item).strip()[:_MAX_WARNING_LENGTH]


def _warnings(value: Any) -> list[str]:
    values = value if isinstance(value, list) else ([value] if isinstance(value, (str, Mapping)) else [])
    return [text for text in (_warning(item) for item in values) if text][:_MAX_WARNINGS]


def normalize_import_outcome(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return the small, stable public subset of an import outcome."""
    warnings = _warnings(raw.get("import_warnings"))
    partial_input = bool(raw.get("partial_input"))
    return {
        "schema_version": IMPORT_OUTCOME_SCHEMA_VERSION,
        "partial_input": partial_input,
        "rejected_rows": _nonnegative_int(raw.get("rejected_rows")),
        "warning_count": max(_nonnegative_int(raw.get("warning_count")), len(warnings)),
        "import_warnings": warnings,
        "readiness": "partial_input" if partial_input else "complete",
    }


def write_import_outcome(directory: str | os.PathLike[str], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically persist the outcome alongside a staged or published corpus."""
    corpus_dir = Path(directory)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    outcome = normalize_import_outcome(raw)
    marker = corpus_dir / IMPORT_OUTCOME_FILENAME
    temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(bilingual_form(outcome), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, marker)
    return outcome


def read_import_outcome(directory: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Read the marker conservatively; unreadable provenance requires review."""
    marker = Path(directory) / IMPORT_OUTCOME_FILENAME
    if not marker.is_file():
        return None
    try:
        raw = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "schema_version": IMPORT_OUTCOME_SCHEMA_VERSION,
            "partial_input": True,
            "rejected_rows": 0,
            "warning_count": 1,
            "import_warnings": [lt("Der gespeicherte Importausgang ist nicht lesbar und muss geprüft werden.", "The stored import outcome cannot be read and must be checked.")],
            "readiness": "partial_input",
        }
    if not isinstance(raw, Mapping) or raw.get("schema_version") != IMPORT_OUTCOME_SCHEMA_VERSION:
        return {
            "schema_version": IMPORT_OUTCOME_SCHEMA_VERSION,
            "partial_input": True,
            "rejected_rows": 0,
            "warning_count": 1,
            "import_warnings": [lt("Der gespeicherte Importausgang hat ein unbekanntes Format und muss geprüft werden.", "The stored import outcome has an unknown format and must be checked.")],
            "readiness": "partial_input",
        }
    return normalize_import_outcome(raw)


__all__ = [
    "IMPORT_OUTCOME_FILENAME",
    "IMPORT_OUTCOME_SCHEMA_VERSION",
    "normalize_import_outcome",
    "read_import_outcome",
    "write_import_outcome",
]
