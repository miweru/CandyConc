"""Accept rounded table values when they match the named measure.

The evidence includes a keyness row whose reference rate rounds to 2.0
and an unrelated count with total=2. Match the named measure against its
row rather than the first item containing a similar field. Incorrect
field bindings remain covered by test_measure_name_field_binding.py.
"""

from candyconc.candyconc_copilot import recipe_runtime as rr

_KEYNESS = {
    "id": "E_keyness_6",
    "grounding_surface": [
        "rows_seen=40",
        "rows[0] {'word': 'unterstreicht', 'target_per_million': 66.33039764331805, "
        "'reference_per_million': 2.030622807244653}",
    ],
    "raw_surface": {
        "rows_seen": 40,
        "rows": [{"word": "unterstreicht", "target_freq": 1610, "reference_freq": 4,
                  "target_per_million": 66.33039764331805, "reference_per_million": 2.030622807244653}],
    },
}
_ZAEHLUNG = {
    "id": "E_query_count_21",
    "grounding_surface": ["total=2", "per_million=0.9", "denominator_tokens=2328677"],
    "raw_surface": {"total": 2, "per_million": 0.9, "denominator_tokens": 2328677},
}
_SATZ = "AI-News liegen bei 66,3 pro Million gegen 2,0 in Human-News ([[beleg:E_keyness_6]])."


def test_gerundete_rate_aus_der_tabellenzeile_ist_keine_fehlbindung():
    assert rr.massname_an_feld_gebunden(_SATZ, [_KEYNESS, _ZAEHLUNG]) == []


def test_eine_falsch_gerundete_rate_ist_nicht_gedeckt():
    assert not rr._massname_gedeckt(
        "per_million", rr._lesarten_mit_stellen("2,1"), [rr._feldwerte_der_rohflaeche([_KEYNESS])]
    )


def test_whole_rate_uses_zero_decimal_places():
    # Whole rates use zero decimal places, counts remain exact.
    assert rr._massname_gedeckt(
        "per_million", rr._lesarten_mit_stellen("2"), [rr._feldwerte_der_rohflaeche([_KEYNESS])]
    )
