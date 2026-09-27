# -*- coding: utf-8 -*-
"""The optional subquestion instruction preserves each requested question and its order."""

from candyconc.candyconc_copilot.interpretation_synthesis import (
    deutungs_synthese_messages,
    gutachten_abschnitt_messages,
    gutachten_gliederung_messages,
)


def _synthese():
    system, _user = deutungs_synthese_messages("Frage?", "Evidenz.")
    return system["content"]


def test_die_vorgabe_traegt_die_teilfragen_pflicht_nicht_mehr():
    """The subquestion instruction is disabled by default."""
    assert "TEILFRAGEN-PFLICHT" not in _synthese()


def test_mit_schalter_steht_die_teilfragen_pflicht(monkeypatch):
    monkeypatch.setenv("CANDYCONC_TEILFRAGEN_PFLICHT", "1")
    text = _synthese()
    assert "TEILFRAGEN-PFLICHT" in text, text[-600:]
    assert "Reihenfolge" in text and "Stückliste" in text, text[-600:]


def test_der_schalter_ist_fuer_die_isolation_da(monkeypatch):
    monkeypatch.setenv("CANDYCONC_TEILFRAGEN_PFLICHT", "0")
    assert "TEILFRAGEN-PFLICHT" not in _synthese()
    monkeypatch.setenv("CANDYCONC_TEILFRAGEN_PFLICHT", "1")
    assert "TEILFRAGEN-PFLICHT" in _synthese()


def test_die_andern_calls_tragen_sie_nicht():
    _system, _user = gutachten_gliederung_messages("Frage?", "Evidenz.")
    assert "TEILFRAGEN-PFLICHT" not in _system["content"]
    _system, _user = gutachten_abschnitt_messages(
        "Frage?", 1, "Titel", "Auftrag", "Evidenz.")
    assert "TEILFRAGEN-PFLICHT" not in _system["content"]
