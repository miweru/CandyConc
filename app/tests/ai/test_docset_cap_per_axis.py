"""Probe: der Docset-Deckel bindet an die Achse (Distinkte erfolgreiche
Docsets), nicht an die Anzahl der Aufrufe.

Befund 3.3: drei von sechs Kontrast-Turns bauen bis zu zwoelf Teilkorpora
und rechnen nichts, weil der Deckel `docset_attempts < 4` raw Aufrufe
zaehlt. Eine Reparatur muss die sechs zulassen.
"""
import pytest

from candyconc.candyconc_copilot.recipe_runtime import (
    _docset_achse_offen,
)


def _evidenz(docset_ids, status="success"):
    """Baut Evidence-Items fuer create_docset-Aufrufe."""
    from candyconc.candyconc_copilot.orchestrator import AnalysisCopilot
    items = []
    for i, did in enumerate(docset_ids):
        item = type("E", (), {})()
        item.tool = "create_docset"
        item.status = status
        item.raw_surface = {"docset_id": did}
        items.append(item)
    return items


class TestDocsetDeckelAchse:
    def test_sechs_distinkte_docsets_werden_zugelassen(self):
        """Sechs erfolgreiche Docsets mit Distinktheit: der Deckel
        darf sie nicht an der Aufrufzahl stoppen."""
        assert _docset_achse_offen(
            successful_docset_ids={"a", "b", "c", "d", "e", "f"},
            docset_attempts=8,
        ), "Sechs distinkte Docsets muessen zugelassen bleiben."

    def test_zwei_distinkte_noch_offen(self):
        assert _docset_achse_offen(
            successful_docset_ids={"a", "b"},
            docset_attempts=2,
        ), "Zwei distinkte Docsets: die Achse ist noch offen."

    def test_dubletten_zaehlen_nicht_als_fortschritt(self):
        """Vier Aufrufe, aber nur zwei distinkte Docsets: der Deckel
        geht nach Achse, nicht nach Aufrufzahl."""
        assert _docset_achse_offen(
            successful_docset_ids={"a", "b"},
            docset_attempts=4,
        ), "Vier Aufrufe bei zwei Docsets: die Achse ist noch offen."
