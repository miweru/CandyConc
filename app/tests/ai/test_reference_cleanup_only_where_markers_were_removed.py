# -*- coding: utf-8 -*-
"""Reference cleanup changes only positions where a marker was removed."""

from __future__ import annotations

import pytest

from candyconc.candyconc_copilot.grounding_refs import resolve_references

POSTEN = {
    "items": [
        {"id": "E_query_count_2", "tool": "query_count",
         "raw_surface": {"total": 2245231}, "grounding_surface": ["total=2245231"]},
        {"id": "E_query_count_3", "tool": "query_count",
         "raw_surface": {"total": 108140}, "grounding_surface": ["total=108140"]},
        {"id": "E_run_cqlf_query_8", "tool": "run_cqlf_query",
         "grounding_surface": ["kwic[0]=Mit der Quarantäne will [man] verhindern , dass andere Menschen"]},
        {"id": "E_run_cqlf_query_11", "tool": "run_cqlf_query",
         "grounding_surface": ["kwic[0]=Herausforderung : Auswahl und Verstetigung"]},
    ],
}

#: zyklus8_teil3 db8a5cdc02134d03a2d405c4671e6cc5, deutungs_roh.txt
SATZ_GATTUNG = (
    "„daß\" ist ein Modell-Effekt weniger Systeme — Trainings- und "
    "Dekodierungsunterschied —, kein Gattungsmerkmal von KI-Text."
)
#: zyklus8_teil2 f069cfbe62864548948b43fb78582512, deutungs_roh.txt
SATZ_REGISTER = (
    "`wirklich`: KI über Human in 4 Registern — blog_essay, easy_language, "
    "social, spoken —, unter Human in 5 Registern — encyclopedia, "
    "narrative_contemporary, news, parliamentary, scientific —, Quoten aus den "
    "Matrixraten selbst gerechnet."
)
#: zyklus8_teil2 f069cfbe…, derselbe Rohtext, mit Belegmarke vor dem Strich
SATZ_MIT_MARKE = (
    "das knappe Plus kommt aus den kleinen, aber hochfrequenten Tokenmassen "
    "social plus spoken — 2570517 plus 2245231 [[beleg:E_query_count_2]] gegen "
    "nur 132201 plus 108140 [[beleg:E_query_count_3]] —, wo die KI stark überzieht."
)
#: zyklus8_teil3 03807620d1cf437887cd3ddbd2e8b958, deutungs_roh.txt
SATZ_LESART = (
    "Deutung: Die Adjektivlesart ist schriftlich-analytisch — Blog, News, "
    "Wissenschaft —, die Partikel mündlich-nah — Spoken, Social."
)
#: zyklus6_teil1 d4019fbda6a64467aacadc11bc1f0f2d und 19f14c2a…, deutungs_roh.txt
SATZ_ZITAT = (
    "Mensch „Mit der Quarantäne will [man] verhindern , dass andere Menschen\" "
    "[[beleg:E_run_cqlf_query_8]], dazu `Herausforderung : Auswahl und "
    "Verstetigung` [[beleg:E_run_cqlf_query_11]]."
)


@pytest.mark.parametrize(
    "satz", [SATZ_GATTUNG, SATZ_REGISTER, SATZ_MIT_MARKE, SATZ_LESART, SATZ_ZITAT],
    ids=["gattung", "register", "marke_vor_strich", "lesart", "zitat_und_code"],
)
def test_text_without_removed_markers_stays_byte_identical(satz):
    ergebnis = resolve_references(satz, POSTEN, detect_bare_numbers=False)
    assert ergebnis["text"] == satz


def test_closing_dash_of_parenthesis_survives():
    ergebnis = resolve_references(SATZ_GATTUNG, POSTEN, detect_bare_numbers=False)
    assert "Dekodierungsunterschied —, kein Gattungsmerkmal" in ergebnis["text"]


def test_verbatim_kwic_quote_keeps_its_token_spacing():
    ergebnis = resolve_references(SATZ_ZITAT, POSTEN, detect_bare_numbers=False)
    assert "verhindern , dass" in ergebnis["text"]
    assert "`Herausforderung : Auswahl" in ergebnis["text"]


@pytest.mark.parametrize(
    "roh, erwartet",
    [
        ("Belegt — {{ev:E_run_cqlf_query_8}}.", "Belegt."),
        ("Belegt ({{ev:E_run_cqlf_query_8}}).", "Belegt."),
        ("Belegt {{ev:E_run_cqlf_query_8}} , weiter.", "Belegt, weiter."),
        ("Es sind 108140 {{ev:E_query_count_3}}.", "Es sind 108140."),
        ("Es sind {{ev:E_query_count_3}} Treffer.", "Es sind 108.140 Treffer."),
    ],
)
def test_cleanup_still_tidies_where_a_marker_was_removed(roh, erwartet):
    """Der Zweck der Bereinigung bleibt: Reste einer entfernten Marke fallen."""
    ergebnis = resolve_references(roh, POSTEN, detect_bare_numbers=False)
    assert ergebnis["text"] == erwartet
