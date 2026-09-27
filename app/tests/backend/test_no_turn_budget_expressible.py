"""Kein Turn-Budget ist ein Zustand, keine grosse Zahl.

Nutzervorgabe vom 2026-09-20: "Ich will keine Max Time, deswegen hatte ich
gesagt das so hoch stellen." Die 8.000.000 Sekunden waren die Bauform dafuer,
weil ``_copilot_max_time_sec`` "kein Budget" nicht kannte: ``value if value >
0 else DEFAULT`` gab bei 0 den Vorgabewert zurueck.

Der Preis war nicht Kosmetik. 57 Stellen in acht Modulen rechnen gegen
max_time, und vier Bruchteile haengen daran: ANSWER_SWITCH_FRACTION 0,55,
RETRY_MIN_TIME_FRACTION 0,4, VERIFIER_MIN_TIME_FRACTION 0,3 und
_TURNENDE_RESERVE_SEC 20. Bei acht Millionen Sekunden griff keiner je, aber
sie standen scharf da. Wer max_time auf einen realistischen Wert gesetzt
haette, haette alle vier gleichzeitig geweckt, ungemessen.

Die Probe faehrt beide Klassen: ohne Budget sind die Tore offen, MIT Budget
greifen sie wieder. Ohne die zweite Haelfte waere nicht gezeigt, dass ein
gewolltes Budget noch funktioniert.
"""

import importlib
import os

import pytest

from candyconc.candyconc_copilot import budgets


@pytest.fixture
def ohne_env(monkeypatch):
    monkeypatch.delenv("CANDYCONC_COPILOT_MAX_TIME_SEC", raising=False)


def _resolver():
    modul = importlib.import_module("candyconc.services.backend.copilot_helpers")
    return modul._copilot_max_time_sec


@pytest.mark.parametrize("wert", [None, "", "0", "-5", "aus", "kein", "none"])
def test_diese_werte_heissen_kein_budget(monkeypatch, wert):
    monkeypatch.delenv("CANDYCONC_COPILOT_MAX_TIME_SEC", raising=False)
    if wert is not None:
        monkeypatch.setenv("CANDYCONC_COPILOT_MAX_TIME_SEC", wert)
    assert _resolver()() is None, f"{wert!r} muss 'kein Budget' heissen."


def test_eine_positive_zahl_bleibt_ein_budget(monkeypatch):
    monkeypatch.setenv("CANDYCONC_COPILOT_MAX_TIME_SEC", "120")
    assert _resolver()() == 120.0


def test_ohne_budget_sind_die_vier_tore_offen():
    """Die Tore, die bei acht Millionen Sekunden nur scheinbar offen waren."""
    assert budgets.retry_time_remaining_ok(0.0, None, now=1e9) is True
    assert budgets._time_remaining_ok(0.0, None, budgets.RETRY_MIN_TIME_FRACTION, 1e9) is True
    assert budgets._time_remaining_ok(0.0, None, budgets.VERIFIER_MIN_TIME_FRACTION, 1e9) is True


def test_mit_budget_schliessen_sie_wieder():
    """Ohne diese Haelfte pruefte die Probe nichts: sie waere auch gruen,
    wenn die Tore fuer JEDEN Wert offen stuenden."""
    # 100 Sekunden Budget, 99 davon verbraucht: unter jedem der Bruchteile.
    assert budgets.retry_time_remaining_ok(0.0, 100.0, now=99.0) is False
    assert budgets._time_remaining_ok(0.0, 100.0, budgets.VERIFIER_MIN_TIME_FRACTION, 99.0) is False


def test_die_ausgelieferte_vorgabe_ist_kein_budget(ohne_env):
    """Das Profil in pyproject.toml steht auf 0, also None."""
    assert _resolver()() is None
