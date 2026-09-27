"""The keyness tool accepts a model-selected row count."""

import pytest

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

ZIEL = ["Menschen", "Kinder", "und", "die", "der", "ist"]
REFERENZ = ["Politik", "Hund", "das", "dem", "war", "sind"]


@pytest.fixture(scope="module")
def keyness():
    return _load_real_tool_wrappers().keyness_tool


def test_ohne_limit_kommt_die_ganze_tabelle(keyness):
    r = keyness(target=ZIEL, reference=REFERENZ, min_freq=1)
    assert r["status"] == "success"
    assert r["rows_returned"] == r["rows_total"] == len(r["rows"])
    assert r["rows_total"] > 2, "Die Probe braucht eine Tabelle, die kappbar ist."


def test_mit_limit_kommt_genau_die_verlangte_zahl(keyness):
    voll = keyness(target=ZIEL, reference=REFERENZ, min_freq=1)
    r = keyness(target=ZIEL, reference=REFERENZ, min_freq=1, limit=2)
    assert len(r["rows"]) == r["rows_returned"] == 2
    assert r["rows_total"] == voll["rows_total"], (
        "rows_total sagt die Wahrheit ueber die Tabelle, nicht ueber die Auswahl."
    )
    assert r["rows"] == voll["rows"][:2], "Gekappt wird NACH der Sortierung."


def test_die_sortierung_wird_genannt(keyness):
    r = keyness(target=ZIEL, reference=REFERENZ, min_freq=1, limit=1, sort_by="lrc")
    assert r["sortiert_nach"] == "lrc", (
        "Wer eine Auswahl bekommt, muss wissen, wonach ausgewaehlt wurde."
    )


@pytest.mark.parametrize("schlecht", [0, -3, "viele"])
def test_ein_unsinniges_limit_ist_ein_eingabefehler(keyness, schlecht):
    modul = _load_real_tool_wrappers()
    with pytest.raises(modul.ToolInputError):
        keyness(target=ZIEL, reference=REFERENZ, min_freq=1, limit=schlecht)
