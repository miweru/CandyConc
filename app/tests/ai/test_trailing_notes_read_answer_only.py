"""Trailing-note checks inspect the answer rather than its appendices."""

from candyconc.candyconc_copilot.recipe_runtime import politur_mit_zitatwache
from candyconc.candyconc_copilot.row_spelling_note import satz

# Die Zeile aus E_keyness_4 der Sitzung, wortgleich in den Schreibungen.
_QUESO = {
    "word": "queso", "target_freq": 3071, "reference_freq": 1,
    "surface_variants": {"target": {"queso": 3042, "Queso": 29}, "reference": {"Queso": 1}},
}
_KEYNESS = {"id": "E_keyness_4", "tool": "keyness", "status": "success",
            "fact_surface": {"status": "success", "rows": [_QUESO]}}


def test_eine_zahl_aus_dem_anhang_zitiert_keine_zeile():
    antwort = "Die stärksten Wörter sind teils Artefakte wie „queso“ [[beleg:E_keyness_4]]."
    poliert, _ = politur_mit_zitatwache(antwort, [_KEYNESS], eigene_zitate_bleiben=True)
    assert "### Experimente\n1. " in poliert, poliert
    assert "Schreibungsklasse" not in poliert, poliert


def test_eine_zahl_in_der_antwort_zitiert_die_zeile_weiter():
    antwort = "„queso“ steht auf der menschlichen Seite 1-mal [[beleg:E_keyness_4]]."
    poliert, _ = politur_mit_zitatwache(antwort, [_KEYNESS], eigene_zitate_bleiben=True)
    assert "den 1 Treffer trägt „Queso“" in poliert, poliert
    assert "- Schreibung „queso“: 1 Treffer, Mehrheit trägt „Queso“" in poliert, poliert


def test_ein_treffer_steht_im_singular():
    assert "Schreibungsklasse: den 1 Treffer trägt „Queso“" in satz(_QUESO)
    zwei = dict(_QUESO, surface_variants={"reference": {"Queso": 2}})
    assert "Schreibungsklasse: die 2 Treffer trägt „Queso“" in satz(zwei)
