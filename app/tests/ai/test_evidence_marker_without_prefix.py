"""An evidence marker without E_ resolves when its target is unique."""

from candyconc.candyconc_copilot.grounding_refs import resolve_references

BELEG = {"id": "E_query_count_49", "tool": "query_count", "status": "success",
         "raw_surface": {"total": 108, "per_million": 42.0},
         "fact_surface": {"total": 108, "per_million": 42.0}}


def test_die_marke_ohne_praefix_loest_auf():
    befund = resolve_references("social 42.0 {{ev:query_count_49.per_million}}", {"items": [BELEG]})
    assert not befund["unresolved"], befund["unresolved"]
    assert befund["resolved"] and befund["resolved"][0]["source_id"] == "E_query_count_49"


def test_die_marke_mit_praefix_bleibt_wie_sie_war():
    befund = resolve_references("social 42.0 {{ev:E_query_count_49.per_million}}", {"items": [BELEG]})
    assert not befund["unresolved"] and befund["resolved"][0]["source_id"] == "E_query_count_49"


def test_eine_unbekannte_kennung_bleibt_unaufgeloest():
    befund = resolve_references("x {{ev:query_count_50}}", {"items": [BELEG]})
    assert befund["unresolved"]
