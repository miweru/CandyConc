# -*- coding: utf-8 -*-
"""query_count reports alternate spellings excluded by the chosen form."""

from candyconc.candyconc_copilot import case_variant_count as cvc


def test_die_andere_schreibung_der_reform():
    assert cvc.andere_schreibung("essentiell") == "essenziell"
    assert cvc.andere_schreibung('[word="essentiell"%c]') == '[word="essenziell"%c]'
    assert cvc.andere_schreibung('[word="(?i)essentiell.*"]') == '[word="(?i)essenziell.*"]'
    assert cvc.andere_schreibung("daß") == "dass"
    assert cvc.andere_schreibung("dass") == "daß"
    assert cvc.andere_schreibung("Potential") == "Potenzial"
    assert cvc.andere_schreibung('cql:[lemma="daß"]') == 'cql:[lemma="dass"]'


def test_ohne_reformschreibung_keine_variante():
    for query in ("Wissen", "Klasse", "nicht nur", '[word="nicht"%c] [word="nur"%c]', '[word="da(ss|ß)"]'):
        assert cvc.andere_schreibung(query) is None, query


def test_die_zaehlung_steht_neben_der_abfrage():
    zaehle = {'[word="essenziell"%c]': 1624}.get
    assert cvc.hinweis('[word="essentiell"%c]', 84, zaehle) == {
        "andere_schreibung": {"query": '[word="essenziell"%c]', "total": 1624}}


def test_eine_schreibung_ohne_treffer_bleibt_ungenannt():
    assert cvc.hinweis("Straße", 50, lambda _q: 0) == {}


def test_mit_c_bleibt_wie_bisher():
    zaehle = {'[word="essentiell"%c]': 84, '[word="essenziell"]': 1380}.get
    assert cvc.hinweis('[word="essentiell"]', 78, zaehle) == {
        "mit_c": {"query": '[word="essentiell"%c]', "total": 84},
        "andere_schreibung": {"query": '[word="essenziell"]', "total": 1380}}
