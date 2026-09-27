"""The answer language of a turn is decided once, from the question.

English probe of 2026-09-27: every English synthesis started its reasoning
with "Wir müssen die finale Antwort auf Deutsch?", run c1 answered an English
question in German, run c2 the same question in English. The interface
language (``locale``) decided nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from candyconc.answer_language import (
    answer_language,
    answer_language_scope,
    choose,
    detect_question_language,
    resolve_answer_language,
)

ENGLISH = [
    "How does the use of freedom change across the decades in these addresses?",
    "Which words are typical of Republican compared with Democratic addresses?",
    "What are the most frequent collocates of economy, and what do they suggest "
    "about how presidents talk about it?",
    "How often does freedom occur per million tokens?",
    'How is "Freiheit" used in these texts?',
    "Show me ten examples of allerdings.",
]

GERMAN = [
    "Wie wird Freiheit in den Texten verwendet, und unterscheiden sich die Gattungen?",
    "Welche Wörter sind typisch für republikanische im Vergleich zu demokratischen Reden?",
    "Zeig mir zehn Belege fuer 'allerdings'.",
    "Wie oft kommt Freiheit vor?",
    "Kollokationen von Freiheit",
    "Wie wird „freedom“ in den Reden verwendet?",
    "Unterscheiden sich KI-Texte und menschliche Texte im Gebrauch von zudem?",
]


@pytest.mark.parametrize("question", ENGLISH)
def test_english_questions_are_english(question):
    assert detect_question_language(question) == "en"


@pytest.mark.parametrize("question", GERMAN)
def test_german_questions_are_german(question):
    assert detect_question_language(question) == "de"


@pytest.mark.parametrize("question", ["freedom", '[word="Freiheit"]', "`economy`", ""])
def test_a_question_without_wording_does_not_decide(question):
    assert detect_question_language(question) is None


def test_the_interface_decides_only_when_the_question_does_not():
    assert resolve_answer_language("freedom", {"locale": "en"}, "de") == "en"
    assert resolve_answer_language("freedom", {}, "en-US") == "en"
    assert resolve_answer_language("freedom", {}, None) == "de"
    # A German question in an English interface stays German (run d).
    assert resolve_answer_language(GERMAN[0], {"locale": "en"}, "en") == "de"
    assert resolve_answer_language(ENGLISH[0], {"locale": "de"}, "de") == "en"


def test_outside_a_turn_everything_is_german():
    assert answer_language() == "de"
    assert choose("Treffer", "hits") == "Treffer"
    with answer_language_scope("en"):
        assert choose("Treffer", "hits") == "hits"
    assert answer_language() == "de"


def _orchestrator(ui_context):
    from tests.ai._real_copilot import make_orchestrator

    return make_orchestrator([], lambda *a, **k: {}, lambda *a, **k: {}, ui_context=ui_context)


class _Stop(Exception):
    pass


def _languages_seen(orch, calls):
    """Answer language right after run_async decided it, one entry per call."""
    seen = []

    def identity(role, principal):
        seen.append(answer_language())
        raise _Stop

    orch._resolve_turn_identity = identity
    for question, role in calls:
        try:
            asyncio.run(orch.run_async(question, role=role, principal="anon"))
        except _Stop:
            pass
    return seen


def test_the_turn_runs_in_the_language_of_its_question():
    orch = _orchestrator({"locale": "de"})
    seen = _languages_seen(orch, [
        (ENGLISH[1], "user"),
        # A continuation of the same turn (approval, clarification) keeps it.
        ("", "system"),
        (GERMAN[0], "user"),
    ])
    assert seen == ["en", "en", "de"]
    # The language lives in the task of the turn, the caller stays German.
    assert answer_language() == "de"


def test_the_route_language_is_the_last_fallback():
    orch = _orchestrator({})
    orch.interface_language = "en"
    assert _languages_seen(orch, [("economy", "user")]) == ["en"]
