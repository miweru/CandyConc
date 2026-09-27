# -*- coding: utf-8 -*-
"""With numeric deletion disabled, an unresolved marker removes only the marker."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from candyconc.candyconc_copilot import interpretation_synthesis as ds
from candyconc.candyconc_copilot.recipe_runtime import resolve_reference_draft

POSTEN = [
    {"id": "E_run_cqlf_query_6", "tool": "run_cqlf_query", "status": "success",
     "grounding_surface": ["total=173"], "fact_surface": {"total": 173}},
]

#: Woertlich aus der Rohsynthese.
SATZ = ("In den Zitatstichproben sind mindestens sechs exakt übereinstimmende Fassungsbelege "
        "sichtbar; daraus schätze ich für das Gesamtkorpus eine Dublettengröße von ca. 300 "
        "überzähligen Fassungsbelegen, mit einer Spanne von etwa 100 bis 600, weil die 13 "
        "Fassungen je Quelltext {{ev:KORPUS}} exakt übernommene Zitate und Formulierungen "
        "mehrfach zählen lassen. Die Daten schließen eine größere Aufblähung nicht aus.")


def _verankert(text, monkeypatch, streichen):
    monkeypatch.setenv("CANDYCONC_ZAHLEN_STREICHEN", streichen)
    orch = SimpleNamespace(
        session=SimpleNamespace(session_id=""),
        _ra_resolve_reference_draft=lambda ts, t, detect_bare_numbers=False: (
            resolve_reference_draft(t, POSTEN, "", detect_bare_numbers=detect_bare_numbers)))
    ergebnis, _ = asyncio.run(ds._verankere(
        orch, SimpleNamespace(normalized_question=""), None, text, POSTEN))
    return ergebnis


def test_the_estimate_survives_an_unknown_marker(monkeypatch):
    text = _verankert(SATZ, monkeypatch, "0")
    assert "ca. 300 überzähligen Fassungsbelegen" in text, text
    assert "100 bis 600" in text
    assert "KORPUS" not in text and "[Beleg fehlt]" not in text, text


def test_striking_keeps_its_old_rule(monkeypatch):
    """Mit ZAHLEN_STREICHEN=1 faellt die Aussage wie bisher (Regel H6/B5)."""
    text = _verankert(SATZ, monkeypatch, "1")
    assert "100 bis 600" not in text
