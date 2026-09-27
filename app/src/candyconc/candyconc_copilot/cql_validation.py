"""Lightweight, dependency-free diagnostics for literal CQLF input."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def validate(query: str) -> dict[str, Any]:
    """Validate a CQLF query string and return deterministic suggestions."""

    errors: list[str] = []
    spans: list[tuple[int, int]] = []
    suggestions: list[dict[str, str]] = []

    match = re.search(r'\[pos\s*=\s*""\s*\]', query)
    if match:
        errors.append("Empty POS tag")
        spans.append(match.span())
        suggestions.append(
            {
                "text": re.sub(r'\[pos\s*=\s*""\s*\]', '[pos="NN"]', query),
                "hint": "Specify part-of-speech",
            }
        )

    match = re.search(r"[\u201c\u201d]", query) or re.search("'", query)
    if match:
        errors.append("Wrong quotes")
        spans.append(match.span())
        clean = query.replace("\u201c", '"').replace("\u201d", '"').replace("'", '"')
        suggestions.append({"text": clean, "hint": "Use straight double quotes"})

    if query.count("[") != query.count("]"):
        errors.append("Unbalanced brackets")
        spans.append((0, len(query)))
        if query.count("[") > query.count("]"):
            diff = query.count("[") - query.count("]")
            suggestions.append(
                {"text": query + "]" * diff, "hint": "Add closing bracket"}
            )
        else:
            corrected = query
            for _ in range(query.count("]") - query.count("[")):
                corrected = corrected.replace("]", "", 1)
            suggestions.append(
                {"text": corrected, "hint": "Remove extra bracket"}
            )

    return {"errors": errors, "suggestions": suggestions, "spans": spans}


# --------------------------------------------------------------------------- #
# Fehlerveredelung
#
# Scheitert ein CQL-Aufruf, bekommt das Modell bis hierher nur die nackte
# Fehlermeldung des Motors zurueck. Diese Funktion haengt die
# deterministische Syntaxdiagnose an, die derselbe Validator ohnehin
# rechnet, damit der naechste Versuch den Fehler kennt statt ihn zu raten.
#
# Sie lag bis zum 2026-09-01 im Orchestrator. Dort war sie ein Fremdkoerper:
# sie orchestriert nichts, sie liest eine Abfrage und schreibt eine
# Diagnose. Ihre einzige Abhaengigkeit war ``validate`` aus genau diesem
# Modul, also ist sie hier zu Hause. Der Orchestrator holt sie zurueck,
# weil sein Aufrufpunkt und eine Probe sie unter seinem Namen erwarten.
# --------------------------------------------------------------------------- #


def _enrich_cql_error(
    tool_name: str,
    args: Dict[str, Any],
    output: Any,
) -> Any:
    """Attach deterministic syntax diagnostics to failed literal CQL calls."""

    if (
        tool_name not in {"run_cqlf_query", "query_count"}
        or not isinstance(output, dict)
        or str(output.get("status") or "").casefold() != "error"
    ):
        return output
    query = str(args.get("query") or "").strip()
    if not query.casefold().startswith("cql:"):
        return output
    diagnostics = validate(query[4:].strip())
    errors = [str(item) for item in diagnostics.get("errors", []) if str(item)]
    if not errors:
        return output
    suggestions: List[str] = []
    hints: List[str] = []
    for item in diagnostics.get("suggestions", []):
        if isinstance(item, dict):
            candidate = str(item.get("text") or "").strip()
            hint = str(item.get("hint") or "").strip()
        else:
            candidate = str(item or "").strip()
            hint = ""
        if candidate:
            suggestions.append(
                candidate
                if candidate.casefold().startswith("cql:")
                else f"cql:{candidate}"
            )
        if hint:
            hints.append(hint)
    return {
        **output,
        "query": query,
        "diagnostics": {
            "errors": errors,
            "suggestions": suggestions,
            "hints": hints,
        },
    }
