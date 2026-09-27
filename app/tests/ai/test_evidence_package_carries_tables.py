"""The evidence package includes the computed tables under its configured mode.

A 73-period trend must expose the same evidence as its untruncated appendix.
Check both flag values so changes to one mode do not alter the other."""

import os

import pytest

from candyconc.candyconc_copilot.interpretation_synthesis import (
    MAX_ZEILEN_JE_ITEM,
    PAKET_MAX_ZEICHEN,
    PAKET_VOLL_MAX_ZEICHEN,
    PAKET_VOLL_ZEILEN_JE_ITEM,
    evidenz_paket_text,
    paket_masse,
)


def _arme_des_piloten(monkeypatch):
    """Die gemessenen Arme liefen ohne Paketwahrheit und knappe Form.

    Beide sind seit dem 2026-09-26 Vorgabe. Diese Proben
    beschreiben die Arme des Piloten und setzen sie deshalb ausdruecklich aus.
    """
    monkeypatch.setenv("CANDYCONC_PAKET_WAHRHEIT", "0")
    monkeypatch.setenv("CANDYCONC_PAKET_KNAPP", "0")


@pytest.fixture
def ohne_flag(monkeypatch):
    _arme_des_piloten(monkeypatch)
    monkeypatch.delenv("CANDYCONC_PAKET_VOLL", raising=False)


@pytest.fixture
def mit_flag(monkeypatch):
    _arme_des_piloten(monkeypatch)
    monkeypatch.setenv("CANDYCONC_PAKET_VOLL", "1")


def _trendreihe(perioden: int = 73) -> dict:
    return {
        "id": "ev1",
        "tool": "trend_analysis",
        "query": "daß",
        "status": "success",
        "grounding_surface": [
            f"rows[{i}] period={1949 + i} hits={100 + i} per_million={7.5 + i}"
            for i in range(perioden)
        ],
    }


def test_vorgabe_bleibt_bei_zwoelf_zeilen(ohne_flag):
    # The package emergency ceiling is 300,000 characters. The twelve-row
    # limit per element still applies in this mode.
    assert paket_masse() == (MAX_ZEILEN_JE_ITEM, PAKET_MAX_ZEICHEN) == (12, 300_000)
    text = evidenz_paket_text([_trendreihe()])
    zeilen = [z for z in text.splitlines() if z.startswith("  rows[")]
    assert len(zeilen) == 10, (
        "So lief der Pilot: von 73 Perioden erreichen zehn den Deutungsaufruf."
    )
    assert "period=1958" in text, "rows[9] ist 1958, die zehnte Periode."
    assert "period=1959" not in text, "Ab der elften ist Schluss."
    assert "weitere Belegzeilen" not in text, "Die Vorgabe sagt nicht, was fehlt."


def test_mit_flag_stehen_die_perioden_im_paket(mit_flag):
    assert paket_masse() == (PAKET_VOLL_ZEILEN_JE_ITEM, PAKET_VOLL_MAX_ZEICHEN)
    text = evidenz_paket_text([_trendreihe()])
    zeilen = [z for z in text.splitlines() if z.startswith("  rows[")]
    assert len(zeilen) == 73, "Alle 73 Perioden, nicht die ersten zehn."
    assert "period=2021" in text


def test_mit_flag_wird_die_kappung_genannt(mit_flag):
    text = evidenz_paket_text([_trendreihe(perioden=200)])
    zeilen = [z for z in text.splitlines() if z.startswith("  rows[")]
    # Zwei der achtzig Zeilen bleiben fuer die Skalare reserviert, damit
    # status und Abfrage nicht von der Tabelle verdraengt werden.
    assert len(zeilen) == PAKET_VOLL_ZEILEN_JE_ITEM - 2 == 78
    assert "122 weitere Belegzeilen" in text, (
        "Wird doch gekappt, steht die Zahl der fehlenden Zeilen im Paket."
    )


_EINE_SKALARZEILE = {
    "id": "ev2",
    "tool": "collocate_stats",
    "query": "Volk",
    "status": "success",
    "grounding_surface": ["status=success"],
    "payload_preview": '{"rows": [{"word": "deutsche", "f": 6306}]}',
}


def test_vorgabe_laesst_die_tabelle_hinter_einer_skalarzeile_liegen(ohne_flag):
    text = evidenz_paket_text([_EINE_SKALARZEILE])
    assert "status=success" in text
    assert "6306" not in text, (
        "Eine einzige Skalarzeile galt als Beleg, die Tabelle blieb draussen."
    )


def test_mit_flag_kommt_die_tabelle_hinter_der_skalarzeile_mit(mit_flag):
    text = evidenz_paket_text([_EINE_SKALARZEILE])
    assert "6306" in text


def test_flagwerte_die_nicht_eins_sind_aendern_nichts(monkeypatch):
    for wert in ("0", "", "nein", "aus", "false"):
        monkeypatch.setenv("CANDYCONC_PAKET_VOLL", wert)
        assert paket_masse() == (12, 300_000), f"Wert {wert!r} darf nichts schalten."
