"""Digits inside a model identifier do not receive an evidence chip."""

from candyconc.candyconc_copilot import interpretation_synthesis as modul


def test_modellname_bekommt_keinen_chip():
    assert modul._setze_beleg_chips("### GPT-OSS 20B", {"20.0": "E_metadata_values_4"}) == "### GPT-OSS 20B"


def test_eine_zahl_im_fliesstext_bekommt_ihren_chip():
    text = modul._setze_beleg_chips("Die Rate liegt bei 20 pro Million.", {"20.0": "E_query_count_3"})
    assert text.endswith("[[beleg:E_query_count_3]]")


def test_eine_jahreszahl_mit_endung_ist_keine_zahl():
    assert [m.group() for m in modul._ZAHL_IM_TEXT.finditer("die 2020er und 1.056 Treffer, 66,3.")] == ["1.056", "66,3."]
