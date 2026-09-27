"""For an English question the model reads English tool texts.

English probe of 2026-09-27, run a1, round 2: ``_tool_output_for_model``
serialised a LocalizedText with its German value, so the model read "Reihe
ausgedünnt auf 60 von 61 Perioden …" while the interface showed "Series
thinned to 60 of 61 periods …" for the same call. A German turn keeps every
byte of the model view.
"""

from __future__ import annotations

import json

from candyconc.answer_language import answer_language_scope
from candyconc.i18n import lt
from tests.ai._real_copilot import orchestrator

OUTPUT = {
    "status": "success",
    "periods_total": 61,
    "warnings": [lt("Reihe ausgedünnt auf 60 von 61 Perioden.",
                    "Series thinned to 60 of 61 periods.")],
    "periods": [{"period": "1946", "hits": 9}, {"period": "1947", "hits": 4}],
}


def test_the_english_turn_reads_the_english_value():
    with answer_language_scope("en"):
        view = json.dumps(orchestrator._tool_output_for_model(OUTPUT, werkzeug="trend_analysis"),
                          ensure_ascii=False)
    assert "Series thinned to 60 of 61 periods." in view
    assert "ausgedünnt" not in view
    # Paths and values stay as they are: references resolve against them.
    assert '"period": "1946"' in view and '"hits": 9' in view


def test_the_german_turn_keeps_every_byte():
    ohne = json.dumps(orchestrator._tool_output_for_model(OUTPUT, werkzeug="trend_analysis"),
                      ensure_ascii=False)
    with answer_language_scope("de"):
        mit = json.dumps(orchestrator._tool_output_for_model(OUTPUT, werkzeug="trend_analysis"),
                         ensure_ascii=False)
    assert mit == ohne == json.dumps(OUTPUT, ensure_ascii=False)
    assert "Reihe ausgedünnt auf 60 von 61 Perioden." in ohne
