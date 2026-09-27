"""Digits inside evidence identifiers are not numeric claims in the answer."""

from candyconc.candyconc_copilot.grounding_refs import resolve_references

_BUNDLE = {"items": [{"id": "E_query_count_44", "tool": "query_count", "status": "success",
                      "grounding_surface": ["total=1173", "per_million=112.2"]}]}


def test_die_kennung_im_chip_ist_keine_zahl():
    ergebnis = resolve_references(
        "Claude liegt bei 112,2 pro Million [[beleg:E_query_count_44]], "
        "zusammen mit [[beleg:E_query_count_55]].", _BUNDLE)
    assert ergebnis["bare_numbers"] == [], ergebnis["bare_numbers"]
    assert "[[beleg:E_query_count_44]]" in ergebnis["text"]


def test_eine_freie_zahl_neben_dem_chip_bleibt_ungebunden():
    ergebnis = resolve_references("Claude liegt bei 157,3 pro Million [[beleg:E_query_count_44]].", _BUNDLE)
    assert [b["number"] for b in ergebnis["bare_numbers"]] == ["157,3"], ergebnis["bare_numbers"]
