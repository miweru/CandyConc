# -*- coding: utf-8 -*-
"""The optional language-finding instruction belongs only in answer synthesis.

Check the enabled and disabled instruction forms and keep it out of
outline and section-writing requests."""

from candyconc.candyconc_copilot.interpretation_synthesis import (
    deutungs_synthese_messages,
    gutachten_abschnitt_messages,
    gutachten_gliederung_messages,
)


def _synthese():
    system, _user = deutungs_synthese_messages("Frage?", "Evidenz.")
    return system["content"]


def test_die_vorgabe_traegt_die_sprachdeutung_nicht_mehr():
    """The language-finding instruction is disabled by default."""
    assert "SPRACHDEUTUNG-PFLICHT" not in _synthese()


def test_mit_schalter_steht_die_sprachdeutung(monkeypatch):
    monkeypatch.setenv("CANDYCONC_SPRACHDEUTUNG", "1")
    text = _synthese()
    assert "SPRACHDEUTUNG-PFLICHT" in text, text[-600:]
    for stueck in ("sprachliche Befund", "Marker", "Metadatenachsen"):
        assert stueck in text, (stueck, text[-600:])


def test_der_schalter_ist_fuer_die_isolation_da(monkeypatch):
    monkeypatch.setenv("CANDYCONC_SPRACHDEUTUNG", "0")
    assert "SPRACHDEUTUNG-PFLICHT" not in _synthese()
    monkeypatch.setenv("CANDYCONC_SPRACHDEUTUNG", "1")
    assert "SPRACHDEUTUNG-PFLICHT" in _synthese()


def test_die_andern_calls_tragen_sie_nicht():
    _system, _user = gutachten_gliederung_messages("Frage?", "Evidenz.")
    assert "SPRACHDEUTUNG-PFLICHT" not in _system["content"]
    _system, _user = gutachten_abschnitt_messages(
        "Frage?", 1, "Titel", "Auftrag", "Evidenz.")
    assert "SPRACHDEUTUNG-PFLICHT" not in _system["content"]
