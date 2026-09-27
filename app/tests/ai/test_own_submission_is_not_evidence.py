"""Parse German numeric notation and prevent a submission from evidencing itself."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul


def _items():
    return [
        {"id": "E_query_count_5", "tool": "query_count",
         "fact_surface": {"total": 2994, "per_million": 21.1},
         "grounding_surface": ["total=2994", "per_million=21.1"]},
        {"id": "E_query_count_44", "tool": "query_count",
         "fact_surface": {"total": 551103}, "grounding_surface": ["total=551103"]},
        {"id": "E_deutung_abgeben_88", "tool": "deutung_abgeben",
         "fact_surface": {"beantwortet": "3082 Formen, 0,6 Prozent"},
         "grounding_surface": ["beantwortet=3082 Formen, 0,6 Prozent"]},
    ]


def test_die_eigene_abgabe_belegt_keine_zahl():
    zahlen = modul._evidenz_zahlen(_items())
    assert zahlen.get(modul._zahl_kanonisch("2994")) == "E_query_count_5"
    assert modul._zahl_kanonisch("3082") not in zahlen, (
        "Eine Zahl, die nur in der eigenen Abgabe des Modells steht, ist nicht belegt.")


def test_deutscher_tausenderpunkt_findet_seinen_beleg():
    zahlen = modul._evidenz_zahlen(_items())
    assert zahlen.get(modul._zahl_kanonisch("551.103", deutsch=True)) == "E_query_count_44"
    assert modul._zahl_kanonisch("21,1", deutsch=True) == modul._zahl_kanonisch("21.1")
    # Eine Dezimalzahl der Evidenz (JSON-Form) bleibt eine Dezimalzahl.
    assert modul._zahl_kanonisch("21.1") == repr(21.1)
    # Modellnamen mit Versionsnummer sind keine Tausender.
    assert modul._zahl_kanonisch("4.7", deutsch=True) == repr(4.7)


def test_chip_zeigt_auf_die_zaehlung_nicht_auf_die_abgabe():
    zahlen = modul._evidenz_zahlen(_items())
    text = modul._setze_beleg_chips("Im Korpus stehen 551.103 Formen.\nSelbst gerechnet: 3082.", zahlen)
    zeilen = text.split("\n")
    assert zeilen[0].endswith("[[beleg:E_query_count_44]]")
    assert "[[beleg:" not in zeilen[1]


def test_kleine_zahl_bekommt_keinen_chip():
    items = _items() + [{"id": "E_metadata_values_3", "tool": "metadata_values",
                         "fact_surface": {"value_counts": {"model": 5, "register": 10}},
                         "grounding_surface": []}]
    zahlen = modul._evidenz_zahlen(items)
    text = modul._setze_beleg_chips("Rund 5-mal seltener, bei GPT-5.4 mini.", zahlen)
    assert "[[beleg:" not in text
