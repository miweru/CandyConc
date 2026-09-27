"""Collapse a repeated interpretation label within the same line."""

from __future__ import annotations

import pytest

from candyconc.candyconc_copilot.recipe_runtime import (
    label_doppelung_in_zeile_falten,
)

GEFALTET = [
    ("**Deutung:** Deutung: Die Methode war korrekt.",
     "**Deutung:** Die Methode war korrekt."),
    ("*Grenzen:* Grenzen: Nur der Ausschnitt.",
     "*Grenzen:* Nur der Ausschnitt."),
    ("**Kernbefund:** Kernbefund: 103 Treffer.",
     "**Kernbefund:** 103 Treffer."),
    ("__Belege:__ Belege: eine Zeile.",
     "__Belege:__ eine Zeile."),
]

#: Was die Wache NICHT anfassen darf. Ohne diese Faelle waere ein
#: Handler gruen, der jedes Vorkommen des Label-Wortes wegschneidet und
#: damit echten Text zerstoert.
UNBERUEHRT = [
    "**Deutung:** Die Deutung der Daten ist offen.",
    "Die Deutung: Deutung ist schwer.",
    "**Belege:** Deutung: gehoert nicht gefaltet",
    "**Deutung:** Deutungsspielraum bleibt.",
    "Deutung",
    "",
]


@pytest.mark.parametrize("roh,erwartet", GEFALTET)
def test_die_doppelung_faellt(roh, erwartet):
    assert label_doppelung_in_zeile_falten(roh) == erwartet


@pytest.mark.parametrize("roh", UNBERUEHRT)
def test_echter_text_bleibt_stehen(roh):
    assert label_doppelung_in_zeile_falten(roh) == roh


def test_mehrere_zeilen_werden_einzeln_behandelt():
    text = (
        "**Kernbefund:** Kernbefund: A.\n"
        "\n"
        "**Deutung:** Die Deutung bleibt.\n"
        "**Grenzen:** Grenzen: B."
    )
    assert label_doppelung_in_zeile_falten(text) == (
        "**Kernbefund:** A.\n"
        "\n"
        "**Deutung:** Die Deutung bleibt.\n"
        "**Grenzen:** B."
    )


def test_nur_die_erste_doppelung_je_zeile():
    # Konservativ: eine Faltung pro Zeile. Mehr waere Raten.
    roh = "**Deutung:** Deutung: Deutung: dreifach"
    assert label_doppelung_in_zeile_falten(roh) == "**Deutung:** Deutung: dreifach"


def test_die_wache_haengt_im_chokepoint():
    """Sie muss auf JEDER Landung laufen, nicht nur auf einem Zweig.

    Genau dieser Fehler (eine Wache an nur einem Zweig) hat frueher drei
    erfundene Zitate ausgeliefert.
    """
    from candyconc.candyconc_copilot.recipe_runtime import (
        politur_mit_zitatwache,
    )

    text, _ = politur_mit_zitatwache("**Deutung:** Deutung: A.", [])
    assert "**Deutung:** A." in text
    assert "Deutung: Deutung:" not in text
