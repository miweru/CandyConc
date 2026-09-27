# -*- coding: utf-8 -*-
"""A curly opening quote with a straight closing quote forms a complete quoted span."""

from __future__ import annotations

from candyconc.candyconc_copilot import recipe_runtime as rr

ABSATZ = (
    "### (6) Ausdrückliches Urteil je Lesart\n\n"
    "Adjektivlesart: Kollegin hat recht — Faktor 4,3 bei *eigentliche*, 3,0 aggregiert, "
    "ohne überlappende Intervalle, getragen von Problem/Pointe/Lehre/Frage. Einschränkung: "
    "Menschen kennen die Form auch, 270 plus 239 Belege für die zwei Hauptformen allein, "
    "„nur KI\" wäre falsch; „ständig\" gilt vor allem für GPT-5.4-mini, Claude und Qwen, "
    "nicht für Teuken. Partikellesart: Kollegin hat nicht recht — Menschen 218,6 gegen KI "
    "194,7 pro Mio., satzinitial sogar 29,0 gegen 9,6 pro Mio. zugunsten Mensch; die lockere "
    "Satzpartikel ist eher ein Human-Stilmerkmal. Was die Evidenz nicht hergibt: keine manuell "
    "annotierte Lesartentrennung homographer Grenzfälle in einem Satz. "
    "[[beleg:E_metadata_values_1]]"
)


def test_das_urteil_zur_partikellesart_bleibt_stehen():
    poliert, _ = rr.politur_mit_zitatwache(ABSATZ, [], eigene_zitate_bleiben=True)
    assert "Partikellesart: Kollegin hat nicht recht" in poliert, poliert[-300:]
    assert "„nur KI\" wäre falsch" in poliert


def test_ein_wirklich_abgebrochenes_zitat_wird_weiter_gekappt():
    """Die Kappung selbst bleibt: endet die letzte Zeile in einem offenen „,
    fällt der Rest ab diesem Zeichen."""
    text = "Erster Absatz.\n\nDas Urteil lautet „nur KI\" und dann „abgebrochen mitten"
    aus = rr._trim_dangling_quote_spans(text)
    assert aus.endswith("„nur KI\" und dann"), aus


def test_ein_gerades_zeichen_im_korpusbeleg_schliesst_die_spanne_nicht():
    """Der Fall aus dem Kommentar zu ``_ZITATSPANNE_SCHUTZ``: ein gerades
    Anführungszeichen mitten in einem typografisch geschlossenen Beleg."""
    text = "Beleg: „Es muss \" dafür Sorge getragen werden“ [[beleg:E_x]]"
    assert rr._trim_dangling_quote_spans(text) == text
