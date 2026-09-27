"""The keyness view reports the contribution of each spelling in a folded class."""

import json

from candyconc.candyconc_copilot import grounding_evidence as ge


def _keyness() -> dict:
    return {"status": "success", "rows": [{
        "word": "wer", "direction": "target", "target_freq": 30809, "reference_freq": 898,
        "target_per_million": 1684.8, "reference_per_million": 678.7, "diff_per_million": 1006.1,
        "ll_signed": 1444.0, "log_ratio": 1.31, "log_ratio_ci_low": 1.24, "log_ratio_ci_high": 1.38,
        "lrc": 1.1, "q_value": 0.0, "low_reliability": False,
        "surface_variants": {"target": {"Wer": 21000, "wer": 9809}, "reference": {"Wer": 320, "wer": 578}},
    }], "rows_total": 131948}


def test_die_sicht_traegt_die_schreibungen():
    zeile = ge.extract_raw_surface(_keyness(), werkzeug="keyness")["rows"][0]
    # Die begrenzte Flaeche verdichtet verschachtelte Werte zu JSON-Text.
    varianten = zeile["surface_variants"]
    varianten = json.loads(varianten) if isinstance(varianten, str) else varianten
    assert varianten["target"]["Wer"] == 21000
    assert varianten["reference"]["wer"] == 578
