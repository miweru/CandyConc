"""H5, Fix 5: der freie Modus (kontraktlose Turns wie die offene Exploration)
gibt am Wall-/Schritt-Budget NICHT mehr leer zurueck, sondern synthetisiert die
gesammelte Tool-Evidenz zu einem ehrlichen Zwischenstand.

Getestet wird die pure Funktion ``free_mode_evidence_digest`` (recipe_runtime),
an die die Orchestrator-Methode delegiert. Offline, kein LLM, kein Index.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.recipe_runtime import free_mode_evidence_digest


def test_digest_synthesises_successful_tool_results():
    results = [
        {"tool": "frequency_list", "ok": True,
         "summary": "frequency_list(pos=NOUN) -> Zeit=321, Arbeit=210"},
        {"tool": "metadata_values", "ok": True,
         "summary": "metadata_values(fields=[*]) -> register: news, chat"},
    ]
    text = free_mode_evidence_digest(results)
    assert text  # nicht leer
    assert "Zwischenstand" in text
    assert "frequency_list(pos=NOUN) -> Zeit=321, Arbeit=210" in text
    assert "register: news, chat" in text
    assert "Limitationen:" in text


def test_digest_skips_failed_and_dedupes():
    results = [
        {"tool": "collocate_stats", "ok": True, "summary": "collocate_stats(Arbeit) -> leer"},
        {"tool": "collocate_stats", "ok": True, "summary": "collocate_stats(Arbeit) -> leer"},
        {"tool": "run_cqlf_query", "ok": False, "summary": "run_cqlf_query(kaputt) -> Fehler"},
    ]
    text = free_mode_evidence_digest(results)
    assert "Fehler" not in text  # fehlerhafter Call taucht nicht auf
    assert text.count("collocate_stats(Arbeit) -> leer") == 1  # Duplikat nur einmal


def test_digest_empty_without_successful_evidence():
    assert free_mode_evidence_digest([]) == ""
    assert free_mode_evidence_digest(None) == ""
    assert free_mode_evidence_digest(
        [{"tool": "x", "ok": False, "summary": "x -> Fehler"}]
    ) == ""
