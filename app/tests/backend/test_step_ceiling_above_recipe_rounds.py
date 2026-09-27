# -*- coding: utf-8 -*-
"""Die Schrittdecke liegt ueber der Rezeptgrenze.

Routenvorgabe 20 und Decke 24 lagen unter max_tool_runden 200 und griffen in
acht Muse-Laeufen (ein Aufruf je Runde), nie bei Qwen (20 bis 40 Aufrufe je
Runde). Die Decke ist eine Missbrauchsgrenze ueber der inhaltlichen Grenze
des Rezepts, nicht darunter.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.recipes import RECIPES
from candyconc.services.backend import copilot_helpers, server

#: Werkzeugaufrufe des groessten gemessenen Turns (Qwen, Kandidat 4, Frage 7).
AUFRUFE_GROESSTER_TURN = 223


def test_default_ceiling_lies_above_every_recipe_round_limit(monkeypatch):
    monkeypatch.delenv("CANDYCONC_MAX_COPILOT_STEPS", raising=False)
    decke = server._copilot_max_steps_ceiling()
    grenzen = {r.id: r.max_tool_runden for r in RECIPES}
    assert grenzen, "keine Rezepte geladen"
    assert decke > max(grenzen.values()), (decke, grenzen)


def test_one_call_per_round_may_do_the_work_of_the_largest_measured_turn(monkeypatch):
    monkeypatch.delenv("CANDYCONC_MAX_COPILOT_STEPS", raising=False)
    assert server._copilot_max_steps_ceiling() >= AUFRUFE_GROESSTER_TURN


def test_route_default_is_the_ceiling(monkeypatch):
    monkeypatch.delenv("CANDYCONC_MAX_COPILOT_STEPS", raising=False)
    decke = server._copilot_max_steps_ceiling()
    assert server._clamp_copilot_max_steps(decke) == decke
    assert copilot_helpers._COPILOT_MAX_STEPS_HARD_DEFAULT == decke


def test_operator_can_still_lower_the_ceiling(monkeypatch):
    monkeypatch.setenv("CANDYCONC_MAX_COPILOT_STEPS", "16")
    assert server._clamp_copilot_max_steps(server._copilot_max_steps_ceiling()) == 16
