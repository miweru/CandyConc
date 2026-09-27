"""dp_nach of a query_count breakdown carries its reference values.

dispersion_offsets delivers dp_min, dp_erwartet and dp_max, and the tool
documentation forbids reading dp against 0 to 1. The breakdown ``nach``
delivered the same measure without any reference. Gries' DP depends on the
number of hits: over ten registers, 126 hits already scatter to about 0.094
under proportional placement, 12,100 hits to about 0.0097 (PING, "Fazit").
These probes pin the values, their computation and their way to the evidence.
"""

from __future__ import annotations

import json

from candyconc.analysis_defaults import dispersion_referenzwerte
from candyconc.candyconc_copilot.count_breakdown import streuung
from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

REFERENCE = ("dp_min_nach", "dp_erwartet_nach")

# The human side of "Fazit" by register on the PING index (Muse cycle 8).
ROWS = [
    {"wert": "blog_essay", "total": 90, "docs": 4000, "tokens": 2344000},
    {"wert": "news", "total": 16, "docs": 4000, "tokens": 1970000},
    {"wert": "encyclopedia", "total": 0, "docs": 3000, "tokens": 1801000},
    {"wert": "scientific", "total": 6, "docs": 1500, "tokens": 740000},
    {"wert": "parliamentary", "total": 11, "docs": 1300, "tokens": 793000},
    {"wert": "social", "total": 3, "docs": 1300, "tokens": 112000},
]


def test_breakdown_reports_the_reference_values_of_its_partition():
    result = streuung(ROWS)
    expected = dispersion_referenzwerte([r["tokens"] for r in ROWS], sum(r["total"] for r in ROWS))
    assert result["dp_min_nach"] == expected["dp_min"]
    assert result["dp_erwartet_nach"] == expected["dp_erwartet"]
    assert result["dp_min_nach"] <= result["dp_erwartet_nach"] < result["dp_nach"]


def test_few_hits_raise_the_expected_value():
    few = [dict(r, total=r["total"] // 10) for r in ROWS]
    assert streuung(few)["dp_erwartet_nach"] > streuung(ROWS)["dp_erwartet_nach"]


def test_no_reference_without_a_partition_or_hits():
    assert streuung(ROWS[:1]) == {}
    assert streuung([dict(r, total=0) for r in ROWS]) == {}


def test_reference_values_reach_raw_and_fact_surface():
    output = {
        "status": "success", "query": "Fazit", "total": 126, "corpus_tokens": 142044149,
        "denominator_tokens": 9256396, "denominator_tokens_raw": 11200783,
        "denominator_scope": "docset", "denominator_source": "corpus_index.docset_word_count",
        "per_million": 13.6, "query_mode": "plain_word", "attribute": "word",
        "case_insensitive": True, "scope": {"corpus_id": "ping", "level": "docset"},
        "nach": "register", "rows": ROWS, **streuung(ROWS),
    }
    item = make_evidence_item(
        item_id="E_query_count_1", tool="query_count", tool_call_id="c1",
        query=json.dumps({"query": "Fazit", "nach": "register"}), output=output,
        analysis_family="frequency",
    )
    for field in REFERENCE:
        assert item.raw_surface.get(field) == output[field], field
        assert item.fact_surface.get(field) == output[field], field
        assert any(line.startswith(f"{field}=") for line in item.grounding_surface), field
