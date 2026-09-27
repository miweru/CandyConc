"""Die Diagnostik einer Kontext-Keyness bleibt in Modellsicht und Belegzeilen ganz.

Die Sicht zeigte die ersten zehn Diagnostikeinträge (DIAGNOSTIK_SICHTBAR).
Eine Kontext-Keyness mit Wortartfilter führt vierzehn: hinter den zehn
Nennerangaben standen context_positions, unlabelled_positions, pos und
case_policy. Das angewandte pos ist der Vorbehalt, der nach keyness_tool_def
„in DIESELBE Quelle wie die Zahl“ gehört, und er fiel aus Sicht und Paket.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.grounding_evidence import (
    build_grounding_surface,
    extract_raw_surface,
)

DIAGNOSTIK = {
    "target_tokens": 1200, "reference_tokens": 9000000, "target_tokens_roh": 1300,
    "reference_tokens_roh": 9500000, "target_docs": 800, "reference_docs": 19272,
    "reference_kind": "rest_des_korpus", "node_hits": 240, "context_window": 5,
    "attribute": "word", "context_positions": 1400, "unlabelled_positions": 200,
    "pos": "ADJ", "case_policy": "gefaltet",
}


def _ausgabe() -> dict:
    return {"status": "success", "rows_total": 2, "rows_returned": 2, "sortiert_nach": "ll_signed",
            "rows": [{"word": "klar", "direction": "target", "ll_signed": 12.0},
                     {"word": "neu", "direction": "reference", "ll_signed": -3.0}],
            "diagnostics": dict(DIAGNOSTIK)}


def test_bounded_view_keeps_all_declared_keyness_diagnostics():
    sicht = extract_raw_surface(_ausgabe(), werkzeug="keyness")
    assert sicht["diagnostics"] == DIAGNOSTIK


def test_grounding_lines_name_the_applied_pos_filter():
    zeilen = build_grounding_surface(extract_raw_surface(_ausgabe(), werkzeug="keyness"))
    assert "diagnostics.pos=ADJ" in zeilen, zeilen
    assert "diagnostics.case_policy=gefaltet" in zeilen, zeilen
    assert "diagnostics.context_positions=1400" in zeilen, zeilen
