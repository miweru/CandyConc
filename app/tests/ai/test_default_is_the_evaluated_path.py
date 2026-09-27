# -*- coding: utf-8 -*-
"""Ohne jeden Schalter laeuft der abgenommene Antwortweg.

Regression, entschieden von Michael am 2026-09-26: „Ich will, dass der
evaluierte und sauber entwickelte Pfad der Standardpfad ist“. Die Laeufe der
Abnahme setzten CANDYCONC_DEUTUNGSPFAD=1, CANDYCONC_PAKET_WAHRHEIT=1,
CANDYCONC_PAKET_KNAPP=1, CANDYCONC_PAKET_MAX_ZEICHEN=300000,
CANDYCONC_ZAHLEN_STREICHEN=0, CANDYCONC_ENTWURF_ALS_ANTWORT=0 und liessen
CANDYCONC_SYNTHESE_MIT_ENTWURF auf seiner Vorgabe. Der Code nahm ohne diese
Umgebung den frueheren Weg mit Verifikation und Neuaufbau.
"""

from __future__ import annotations

import pytest

from candyconc.candyconc_copilot import interpretation_synthesis as modul

SCHALTER = ("CANDYCONC_DEUTUNGSPFAD", "CANDYCONC_PAKET_WAHRHEIT", "CANDYCONC_PAKET_KNAPP",
            "CANDYCONC_PAKET_MAX_ZEICHEN", "CANDYCONC_ZAHLEN_STREICHEN",
            "CANDYCONC_ENTWURF_ALS_ANTWORT", "CANDYCONC_SYNTHESE_MIT_ENTWURF",
            "CANDYCONC_PAKET_VOLL")


@pytest.fixture
def ohne_umgebung(monkeypatch):
    for name in SCHALTER:
        monkeypatch.delenv(name, raising=False)


def test_the_answer_goes_through_the_evaluated_path(ohne_umgebung):
    assert modul.deutungspfad_aktiv() is True
    assert modul.synthese_mit_entwurf_aktiv() is True
    assert modul.entwurf_als_antwort_aktiv() is False


def test_the_evidence_package_is_the_evaluated_one(ohne_umgebung):
    assert modul.paket_wahrheit_aktiv() is True
    assert modul.paket_knapp_aktiv() is True
    assert modul.paket_masse() == (12, 300_000)


def test_numbers_are_recorded_not_struck(ohne_umgebung):
    assert modul.zahlen_streichen_aktiv() is False


def test_an_old_package_limit_in_the_environment_changes_nothing(ohne_umgebung, monkeypatch):
    """Die Zahl im Paket ist keine Stellschraube mehr."""
    monkeypatch.setenv("CANDYCONC_PAKET_MAX_ZEICHEN", "14000")
    assert modul.paket_masse() == (12, 300_000)
