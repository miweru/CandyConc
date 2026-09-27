"""A metadata field without values is empty rather than single-valued."""

from __future__ import annotations

from candyconc.candyconc_copilot.prompt_layout import _render_meta_axes
from candyconc.candyconc_copilot.recipe_runtime import (
    _classify_meta_axes,
    _meta_axis_alternative,
)

FELDER = ["paired_with", "register", "model", "split", "doc_id"]
ZAEHLUNG = {
    "paired_with": 0, "register": 1, "model": 1, "split": 2, "doc_id": 2000,
}


def _achsen():
    return _classify_meta_axes(FELDER, ZAEHLUNG, 2000)


def test_null_werte_werden_als_leer_gefuehrt_nicht_als_einwertig():
    nach_feld = {a["field"]: a["kind"] for a in _achsen()}
    assert nach_feld["paired_with"] == "empty"
    assert nach_feld["register"] == "single"


def test_das_leere_feld_verschwindet_nicht_aus_dem_prompt():
    zeilen = " ".join(_render_meta_axes(_achsen()))
    assert "paired_with" in zeilen
    assert "unbefüllt" in zeilen
    # Und es steht NICHT bei den einwertigen.
    einwertig = [t for t in zeilen.split("|") if "je 1 Wert" in t]
    assert all("paired_with" not in t for t in einwertig), einwertig


def test_das_leere_feld_verschwindet_nicht_aus_der_antwort():
    class _Rezept:
        precondition_alternative = "Docset-Kontrast."

    text = _meta_axis_alternative({"meta_axes": _achsen()}, _Rezept())
    assert "paired_with" in text
    assert "unbefüllt" in text


def test_eine_echte_achse_bleibt_kontrastierbar():
    # POSITIVE KLASSE. Ohne sie waere ein Klassifikator gruen, der ALLES
    # zu "empty" macht und damit jeden Kontrast unmoeglich meldet.
    achsen = _classify_meta_axes(
        ["speaker_party"], {"speaker_party": 6}, 2000
    )
    assert achsen[0]["kind"] == "axis"
