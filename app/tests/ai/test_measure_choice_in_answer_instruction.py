# -*- coding: utf-8 -*-
"""The optional measure-choice instruction belongs only in answer synthesis.

Check enabled and disabled forms without adding the instruction to
outline or section-writing calls."""

from candyconc.candyconc_copilot.interpretation_synthesis import (
    deutungs_synthese_messages,
    gutachten_abschnitt_messages,
    gutachten_gliederung_messages,
)


def _synthese():
    system, _user = deutungs_synthese_messages("Frage?", "Evidenz.")
    return system["content"]


def test_die_vorgabe_traegt_die_masswahl_nicht_mehr():
    """The measure-choice instruction is disabled by default."""
    assert "MASSWAHL-PFLICHT" not in _synthese()


def test_mit_schalter_steht_die_masswahl(monkeypatch):
    monkeypatch.setenv("CANDYCONC_MASSWAHL", "1")
    text = _synthese()
    assert "MASSWAHL-PFLICHT" in text, text[-600:]
    for stueck in ("eigenen Lauf", "Lehrbuchsatz"):
        assert stueck in text, (stueck, text[-600:])


def test_der_schalter_ist_fuer_die_isolation_da(monkeypatch):
    monkeypatch.setenv("CANDYCONC_MASSWAHL", "0")
    assert "MASSWAHL-PFLICHT" not in _synthese()
    monkeypatch.setenv("CANDYCONC_MASSWAHL", "1")
    assert "MASSWAHL-PFLICHT" in _synthese()


def test_die_andern_calls_tragen_sie_nicht():
    _system, _user = gutachten_gliederung_messages("Frage?", "Evidenz.")
    assert "MASSWAHL-PFLICHT" not in _system["content"]
    _system, _user = gutachten_abschnitt_messages(
        "Frage?", 1, "Titel", "Auftrag", "Evidenz.")
    assert "MASSWAHL-PFLICHT" not in _system["content"]
