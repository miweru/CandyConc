# -*- coding: utf-8 -*-
"""The final calculation belongs in the instruction that produces the answer."""

from candyconc.candyconc_copilot.interpretation_synthesis import (
    deutungs_synthese_messages,
    gutachten_abschnitt_messages,
    gutachten_gliederung_messages,
)


def _synthese():
    system, _user = deutungs_synthese_messages("Frage?", "Evidenz.")
    return system["content"]


def test_die_vorgabe_tragt_die_rechen_pflicht_nicht_mehr():
    """Seit dem 2026-09-22 AUS: gepaart ohne messbare Bewegung, die
    Aenderung bleibt nicht im Produkt (Schalter Vorgabe AUS)."""
    assert "RECHEN-PFLICHT" not in _synthese()


def test_mit_schalter_steht_die_rechen_pflicht(monkeypatch):
    monkeypatch.setenv("CANDYCONC_RECHEN_PFLICHT", "1")
    text = _synthese()
    assert "RECHEN-PFLICHT" in text, text[-600:]
    for stueck in ("Rate", "Verhältnis", "Differenz", "Befund"):
        assert stueck in text, (stueck, text[-600:])


def test_die_andern_calls_tragen_sie_nicht():
    """Die Pflicht gehört in den Antwort-Call. Gliederung und Abschnitt
    planen beziehungsweise schreiben Abschnitte — dort wäre sie ein
    zweiter Auftrag und würde die Messung verwässern."""
    _system, _user = gutachten_gliederung_messages("Frage?", "Evidenz.")
    assert "RECHEN-PFLICHT" not in _system["content"]
    _system, _user = gutachten_abschnitt_messages(
        "Frage?", 1, "Titel", "Auftrag", "Evidenz.")
    assert "RECHEN-PFLICHT" not in _system["content"]


def test_die_absenz_regel_bleibt_neben_ihr_stehen():
    """Der vorherige Auftrag (ABSENZ-REGEL) bleibt unverändert neben der
    RECHEN-PFLICHT stehen — der Bau ersetzt nichts, er ergänzt."""
    text = _synthese()
    assert "ABSENZ-REGEL" in text, text[-600:]


def test_der_rechen_schalter_ist_fuer_die_isolation_da(monkeypatch):
    """Disabling the calculation instruction preserves the other instruction bytes."""
    monkeypatch.setenv("CANDYCONC_RECHEN_PFLICHT", "0")
    assert "RECHEN-PFLICHT" not in _synthese()
    monkeypatch.setenv("CANDYCONC_RECHEN_PFLICHT", "1")
    assert "RECHEN-PFLICHT" in _synthese()
