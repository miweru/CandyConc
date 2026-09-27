# -*- coding: utf-8 -*-
"""Resolve differently cased or bare-number markers only when the evidence target is unique."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from candyconc.candyconc_copilot import interpretation_synthesis as ds
from candyconc.candyconc_copilot.grounding_refs import resolve_references
from candyconc.candyconc_copilot.recipe_runtime import resolve_reference_draft

#: Zeile 41 der Rohsynthese, woertlich.
ZEILE = (
    "Human-Partikel, Docset 7ce502cc911f4243af031c8edd78b940, sample 6, seed 7, "
    "Population 2448 {{ev:E_run_cqlf_query_33}}: „[Eigentlich] darf der "
    "Auslandsgeheimdienst keine Deutschen überwachen\" {{ev:E_run_cqlf_query_33}}, "
    "„Dass Twitter in dieser Frage [eigentlich] so rigoros ist\" "
    "{{ev:e_run_cqlf_query_33}} [Nachweis in {{ev:E_run_cqlf_query_33}}], „da es "
    "sich [eigentlich] um eine beschränkte Online-Durchsuchung handle\" "
    "{{ev:E_run_cqlf_query_33}}."
)

POSTEN = [
    {"id": "E_run_cqlf_query_33", "tool": "run_cqlf_query", "status": "success",
     "grounding_surface": ["kwic[0]=[Eigentlich] darf der Auslandsgeheimdienst",
                           "sample.population=2448"],
     "fact_surface": {"sample": {"requested": 6, "drawn": 6, "seed": 7, "population": 2448}}},
    {"id": "E_query_count_19", "tool": "query_count", "status": "success",
     "raw_surface": {"total": 8, "per_million": 8.9},
     "fact_surface": {"total": 8, "per_million": 8.9}},
    {"id": "E_query_count_20", "tool": "query_count", "status": "success",
     "raw_surface": {"total": 3, "per_million": 2.6},
     "fact_surface": {"total": 3, "per_million": 2.6}},
]


def _orchestrator():
    """Der Teil des Orchestrators, den ``_verankere`` benutzt."""
    return SimpleNamespace(
        session=SimpleNamespace(session_id=""),
        _ra_resolve_reference_draft=lambda turn_state, text, detect_bare_numbers=False: (
            resolve_reference_draft(text, POSTEN, "", detect_bare_numbers=detect_bare_numbers)),
    )


def _verankert(text: str) -> str:
    import asyncio

    ergebnis, _ = asyncio.run(ds._verankere(
        _orchestrator(), SimpleNamespace(normalized_question=""), None, text, POSTEN))
    return ergebnis


def test_lowercase_marker_resolves_to_its_single_item():
    befund = resolve_references("x {{ev:e_run_cqlf_query_33}}", {"items": POSTEN})
    assert not befund["unresolved"], befund["unresolved"]
    assert befund["resolved"][0]["source_id"] == "E_run_cqlf_query_33"


def test_bare_running_number_resolves_to_its_single_item():
    # Mimo, woertlich: "(8,9 : 2,6 bei höchstens 27 Token Abstand {{ev:19}}{{ev:20}}"
    befund = resolve_references(
        "(8,9 : 2,6 bei höchstens 27 Token Abstand {{ev:19.per_million}}{{ev:20}}",
        {"items": POSTEN})
    assert not befund["unresolved"], befund["unresolved"]
    assert [r["source_id"] for r in befund["resolved"]] == ["E_query_count_19", "E_query_count_20"]


def test_ambiguous_number_stays_unresolved():
    doppelt = POSTEN + [{"id": "E_keyness_19", "tool": "keyness", "status": "success"}]
    befund = resolve_references("x {{ev:19}}", {"items": doppelt})
    assert befund["unresolved"]


def test_unknown_marker_stays_unresolved():
    befund = resolve_references("x {{ev:e_run_cqlf_query_34}}", {"items": POSTEN})
    assert befund["unresolved"]


def test_recorded_line_keeps_all_three_quotes():
    text = _verankert("Vorsatz.\n\n" + ZEILE + "\n\nNachsatz.")
    assert "Dass Twitter in dieser Frage [eigentlich] so rigoros ist" in text
    assert "Online-Durchsuchung handle" in text
    assert "Aussage(n) entfernt" not in text


def test_unresolvable_marker_beside_resolved_markers_drops_only_the_marker():
    unbekannt = ZEILE.replace("{{ev:e_run_cqlf_query_33}}", "{{ev:E_run_cqlf_query_99}}")
    text = _verankert("Vorsatz.\n\n" + unbekannt + "\n\nNachsatz.")
    assert "Dass Twitter in dieser Frage [eigentlich] so rigoros ist\" [Nachweis" in text
    assert "[Beleg fehlt]" not in text
    assert "Aussage(n) entfernt" not in text


_VIER_SAETZE = (
    "Erster Satz mit Beleg {{ev:E_run_cqlf_query_33}}. Zweiter Satz nur mit "
    "{{ev:E_run_cqlf_query_99}}. Dritter Satz {{ev:E_run_cqlf_query_33}}. "
    "Vierter Satz ohne Marke.")


def test_sentence_with_only_an_unresolvable_marker_still_falls_when_striking(monkeypatch):
    """Regel H6/B5 gilt weiter, wenn Zahlen gestrichen werden (Schalter)."""
    monkeypatch.setenv("CANDYCONC_ZAHLEN_STREICHEN", "1")
    text = _verankert(_VIER_SAETZE)
    assert "Zweiter Satz" not in text
    assert "Erster Satz" in text and "Dritter Satz" in text


def test_without_striking_only_the_unresolvable_marker_goes(monkeypatch):
    """Seit dem 2026-09-26 Vorgabe: siehe test_unresolvable_marker_keeps_its_sentence."""
    monkeypatch.delenv("CANDYCONC_ZAHLEN_STREICHEN", raising=False)
    text = _verankert(_VIER_SAETZE)
    assert "Zweiter Satz nur mit." in text, text
    assert "E_run_cqlf_query_99" not in text and "[Beleg fehlt]" not in text
    assert "Erster Satz" in text and "Dritter Satz" in text


def test_pathless_variant_marker_becomes_a_chip_not_a_value():
    """Mimo, woertlich: "sind mit 2940 je Million alltäglich {{ev:17}}".

    Ohne Schutz als Chip setzte die Aufloesung den Primaerwert des Postens ein
    ("alltäglich 417.652"). Eine Marke ohne Feld ist im Deutungspfad ein Beleg,
    kein Wert.
    """
    posten = POSTEN + [{"id": "E_query_count_17", "tool": "query_count", "status": "success",
                        "raw_surface": {"total": 417652, "per_million": 2940.4},
                        "fact_surface": {"total": 417652, "per_million": 2940.4}}]
    orchestrator = SimpleNamespace(
        session=SimpleNamespace(session_id=""),
        _ra_resolve_reference_draft=lambda turn_state, text, detect_bare_numbers=False: (
            resolve_reference_draft(text, posten, "", detect_bare_numbers=detect_bare_numbers)),
    )
    import asyncio

    text, _ = asyncio.run(ds._verankere(
        orchestrator, SimpleNamespace(normalized_question=""), None,
        "zwei *und* im selben Satz sind mit 2940,4 je Million alltäglich {{ev:17}}.", posten))
    assert "417" not in text
    assert text.endswith("alltäglich [[beleg:E_query_count_17]].")
