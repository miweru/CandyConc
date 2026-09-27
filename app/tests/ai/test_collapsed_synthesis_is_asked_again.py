# -*- coding: utf-8 -*-
"""Retry a synthesis that collapses the draft before accepting the final answer."""

from __future__ import annotations

import asyncio

from tests.ai import _real_copilot
from candyconc.candyconc_copilot import interpretation_synthesis as ds

ReActOrchestrator = _real_copilot.orchestrator.ReActOrchestrator
_RunTurnState = _real_copilot.orchestrator._RunTurnState

_EVIDENZ = {"id": "ev1", "tool": "query_count", "tool_call_id": "c1", "query": "x",
            "status": "success", "grounding_surface": ["total=8343253"],
            "fact_surface": {"total": 8343253}}

#: Die ersten zwei Absaetze der aufgezeichneten Synthese, woertlich.
KURZ = ("Kompositawachstum ist im Korpus eine vollzählige, monoton fallende Längenreihe ab 13 "
        "Buchstaben, die sich erst bei **L = 30 Buchstaben** registerscharf spaltet: `legal` "
        "dominiert die Klasse, `spoken` und `easy_language` fallen gleichzeitig auf eine "
        "praktisch vernachlässigbare Rate.\n\nGezählt wurde Wortformlänge per Regex, "
        "case-sensitiv, Nenner jeweils Token.")
LANG = KURZ + "\n\n" + ("Die Serie ab 13 Buchstaben summiert sich auf 8343253 {{ev:ev1}} Treffer. " * 40)
ENTWURF = "Werkzeugphase: die Serie. " + ("Klasse 13: 2.202.045 Treffer, Klasse 14: 1.579.725. " * 60)


def _orchestrator(antworten):
    aufrufe = []

    async def _call_llm(messages, exposed_tools, **kwargs):
        aufrufe.append(messages)
        return {"choices": [{"message": {"content": antworten[min(len(aufrufe), len(antworten)) - 1]}}]}

    async def _dispatch(tool_call, _token=None):
        raise AssertionError("kein Tool-Call erwartet")

    orch = ReActOrchestrator([], _call_llm, _dispatch)
    orch._emit_output = lambda bus, event: None
    orch._turn_evidence_items = [dict(_EVIDENZ)]
    return orch, aufrufe


def _turn_state():
    ts = _RunTurnState()
    ts.question = ts.normalized_question = "Wortlaengenverteilung ab 13 Buchstaben?"
    ts.role = "user"
    ts.llm_is_async = True
    ts.accepts_stream = False
    ts.accepts_json_schema = False
    ts.accepts_tool_choice = False
    ts.forced_next_tools = []
    ts.llm_calls_used = 0
    ts.principal = None
    ts.system_prompt = ""
    return ts


def test_a_collapsed_synthesis_is_asked_again():
    orch, aufrufe = _orchestrator([KURZ, LANG])
    text = asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf=ENTWURF))
    assert len(aufrufe) == 2, len(aufrufe)
    assert "Die Serie ab 13 Buchstaben" in text


def test_a_full_synthesis_is_not_asked_again():
    orch, aufrufe = _orchestrator([LANG])
    asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf=ENTWURF))
    assert len(aufrufe) == 1


def test_a_short_draft_never_triggers_it():
    orch, aufrufe = _orchestrator([KURZ])
    asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf="kurzer Entwurf"))
    assert len(aufrufe) == 1


def test_if_every_attempt_collapses_the_longest_one_stands():
    zweiter = KURZ + " Zusatz."
    orch, aufrufe = _orchestrator([KURZ, zweiter, KURZ])
    text = asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf=ENTWURF))
    assert len(aufrufe) == 3
    assert "Zusatz" in text


#: Zyklus 11, deutung-stilmerkmale-paarig: gleiche Laenge, keine Zahl mehr.
ENTWURF_MIT_ZAHLEN = "Werkzeugphase: die Merkmale. " + " ".join(
    f"Merkmal {i}: {3000 + i * 17},{i % 10} pmw in KI gegen {800 + i * 13},{(i + 3) % 10} pmw in Human."
    for i in range(30))
SYNTHESE_OHNE_ZAHLEN = ("In news steht sondern in KI bei deutlich höherer Rate als in Human "
                        "{{ev:ev1}}, im blog ebenfalls deutlich höher {{ev:ev1}}. " * 40)
SYNTHESE_MIT_ZAHLEN = SYNTHESE_OHNE_ZAHLEN + " ".join(
    f"Merkmal {i}: {3000 + i * 17},{i % 10} gegen {800 + i * 13},{(i + 3) % 10}." for i in range(30))


def test_a_synthesis_that_drops_every_number_is_asked_again():
    orch, aufrufe = _orchestrator([SYNTHESE_OHNE_ZAHLEN, SYNTHESE_MIT_ZAHLEN])
    text = asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf=ENTWURF_MIT_ZAHLEN))
    assert len(aufrufe) == 2, len(aufrufe)
    assert "3017,1" in text


def test_a_synthesis_that_keeps_the_numbers_is_not_asked_again():
    orch, aufrufe = _orchestrator([SYNTHESE_MIT_ZAHLEN])
    asyncio.run(ds.fuehre_deutungs_synthese_aus(
        orch, _turn_state(), None, [dict(_EVIDENZ)], entwurf=ENTWURF_MIT_ZAHLEN))
    assert len(aufrufe) == 1
