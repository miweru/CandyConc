# -*- coding: utf-8 -*-
"""The English reading of the router (``candyconc.question_language``).

Properties of the rendering itself. The route of whole questions is pinned
in ``test_english_routing_pairs``.
"""

from __future__ import annotations

import pytest

from candyconc import question_kind as qk
from candyconc.candyconc_copilot import question_form as qf
from candyconc.question_language import (
    is_english_question,
    render_english_cues,
    routing_text,
)
from candyconc.tooling.tool_selection import _prompt_flags

GERMAN = (
    "Wie oft kommt 'Nachhaltigkeit' vor?",
    "Wie oft kommt 'state of the union' vor?",
    "Wie verändert sich der Gebrauch von freedom über die Jahrzehnte in diesen Reden?",
    "Welche Kollokate hat 'economy' in the State of the Union?",
    "Zeig mir zehn Belege fuer 'allerdings'.",
)

ENGLISH = (
    "How often does 'sustainability' occur?",
    "Which words are typical of Republican compared with Democratic addresses?",
    "What are the most frequent collocates of economy?",
    "Collocates of economy?",
    "What's the difference between 'news' and 'blog'?",
)


@pytest.mark.parametrize("question", GERMAN)
def test_german_questions_are_not_rendered(question):
    assert not is_english_question(question)
    assert render_english_cues(question) is None
    assert routing_text(question) == qk.normalisierte_frage(question)


@pytest.mark.parametrize("question", ENGLISH)
def test_english_questions_are_rendered(question):
    assert is_english_question(question)
    assert render_english_cues(question) is not None


def test_quoted_terms_are_never_rendered():
    rendered = render_english_cues("How often does 'compare' occur in the corpus?")
    assert "'compare'" in rendered
    assert "wie oft" in rendered and "kommt vor" in rendered
    assert "vergleich" not in rendered


def test_apostrophes_open_no_quote():
    rendered = render_english_cues("What's the difference between 'news' and 'blog'?")
    assert "unterschiede zwischen 'news' und 'blog'" in rendered


def test_phrases_match_whole_words_only():
    rendered = render_english_cues("Why is this common because of the white house?")
    for german in ("gebrauch", "verwendet", "treffer", "häufig"):
        assert german not in rendered


def test_longer_phrase_wins_over_its_first_word():
    rendered = render_english_cues("Create a word sketch and a word profile for 'house'.")
    assert "word sketch" in rendered and "wortprofil" in rendered
    assert "wort sketch" not in rendered


def test_rendering_is_stable_when_applied_twice():
    for question in ENGLISH:
        once = render_english_cues(question)
        assert (render_english_cues(once) or once) == once


def test_english_usage_question_is_no_plain_lookup():
    """"How is 'home' used?" asks for usage, like "Wie wird 'Heim' verwendet?"."""
    assert not qk.frage_ist_blosses_nachschlagen("How is 'home' used?")
    assert not qk.frage_ist_blosses_nachschlagen("Wie wird 'Heim' verwendet?")
    assert qk.frage_ist_blosses_nachschlagen("Is the word 'home' in the corpus?")


def test_english_candidate_list_is_read_like_the_german_one():
    english = (
        "Lists of alleged AI markers circulate everywhere: delve, tapestry, crucial, "
        "moreover and furthermore. Do they hold up in this collection?"
    )
    assert qf.kandidatenliste_aus_frage(english) == (
        "delve", "tapestry", "crucial", "moreover", "furthermore",
    )
    assert qf.ist_kandidatenlisten_pruefung(english)


def test_german_candidate_list_keeps_its_german_parse():
    """English anchors and separators are read only in English questions."""
    german = "Die Liste der Marker lautet: the, list, and, or. Halten sie?"
    assert qf.kandidatenliste_aus_frage(german) == ("the", "list", "and", "or")


def test_english_construction_search_is_recognised():
    question = (
        "Where is 'not only' followed by 'but also' with at most eight tokens in between? "
        "Show me five examples."
    )
    assert qf.konstruktions_cues(question) == ("gefolgt von", "token dazwischen")
    assert qf.ist_konstruktions_suchauftrag(question)


def test_tool_flags_read_english_questions():
    flags = _prompt_flags("What are the most frequent collocates of economy?")
    assert flags["collocation"] and flags["frequency"]
    flags = _prompt_flags("How does the frequency of 'freedom' develop over time?")
    assert flags["trend"] and flags["frequency"]
