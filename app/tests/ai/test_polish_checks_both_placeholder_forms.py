"""Final polishing checks both raw markers and rendered placeholders."""

from __future__ import annotations

from candyconc.candyconc_copilot.grounding_refs import (
    MISSING_EVIDENCE_PLACEHOLDER as PLATZHALTER,
)
from candyconc.candyconc_copilot.recipe_runtime import final_answer_polish

#: Der ausgelieferte Text aus kontrast-2, gekuerzt auf die tragenden
#: Aussagen. Die Verhaeltnisse (betroffene zu gesamten Aussagen) bleiben
#: unter 50 Prozent, damit der Wachposten NICHT der Grund fuer ein
#: gruenes Ergebnis sein kann.
_ECHTER_TEXT = (
    f"**Kernbefund:** Die Frage {PLATZHALTER} ist aus dieser Session "
    "nicht beantwortbar.\n"
    "\n"
    "**Belege:** Aus den Tool-Outputs stehen keine Zahlen zur Verfuegung:\n"
    "- Gespeicherte Subkorpora existieren in dieser Session nicht.\n"
    "- Die Achse wurde nicht verifiziert und bleibt offen.\n"
    "- Der Tool-Space trug die noetige Funktion nicht.\n"
    "\n"
    f"Nur der direkte A/B-Kontrast trennt {PLATZHALTER} von "
    f"{PLATZHALTER}.\n"
    "\n"
    "**Grenzen:** Gemessen wurde in dieser Session nichts. Die Tabelle "
    "ist mit dem exponierten Tool-Space nicht erzeugbar. Ein "
    "kompositorischer Effekt kann den Rueckgang erklaeren.\n"
)


def test_bereits_ersetzte_platzhalter_erreichen_den_nutzer_nicht():
    """Rendered placeholders reach final polishing in this form."""

    assert "{{ev:" not in _ECHTER_TEXT, (
        "Der Test muss OHNE rohe Marker laufen, sonst prueft er den alten "
        "Zweig und nicht den Defekt."
    )
    poliert, _ = final_answer_polish(_ECHTER_TEXT)
    assert PLATZHALTER not in poliert, (
        "Platzhalter im ausgelieferten Text. Genau das war der Befund: "
        f"{poliert.count(PLATZHALTER)} Stueck.\n{poliert}"
    )


def test_rohe_marker_bleiben_ebenfalls_gedeckt():
    """Die alte Ankunftsform darf durch die Umstellung nicht verlieren."""

    roh = _ECHTER_TEXT.replace(PLATZHALTER, "{{ev:E_keyness_1.gibtesnicht}}")
    poliert, _ = final_answer_polish(roh)
    assert "{{ev:" not in poliert, poliert
    assert PLATZHALTER not in poliert, poliert


def test_die_tragenden_aussagen_ueberleben():
    """Kein Kahlschlag: was keinen Platzhalter traegt, bleibt stehen."""

    poliert, _ = final_answer_polish(_ECHTER_TEXT)
    for satz in (
        "Gespeicherte Subkorpora",
        "Gemessen wurde in dieser Session nichts",
        "kompositorischer Effekt",
    ):
        assert satz in poliert, f"{satz!r} verloren:\n{poliert}"


def test_der_wachposten_gegen_kahlschlag_bleibt_bindend():
    """Wuerde alles fallen, bleibt der Platzhalter sichtbar.

    Das ist die aeltere, bewusste Entscheidung (H11.4): eine entkernte
    Antwort waere unehrlicher als ein sichtbarer Platzhalter. Die
    Umstellung der Bedingung darf sie nicht aushebeln.
    """

    nur_luecke = f"Es gibt {PLATZHALTER} Treffer."
    poliert, _ = final_answer_polish(nur_luecke)
    assert PLATZHALTER in poliert, (
        "Der 50-Prozent-Wachposten hat nicht gegriffen, die Antwort wurde "
        f"entkernt: {poliert!r}"
    )
