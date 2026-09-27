"""Counts within a document scope retain CQL query provenance."""

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()


def test_within_doc_ist_cql():
    herkunft = _TW._query_method_provenance(
        'within(<doc>, [word="nicht"%c] [word="nur"] []{0,8} [word="sondern"%c] [word="auch"])',
        case_insensitive=True,
    )
    assert herkunft["query_mode"] == "cqlf"
    assert herkunft["attribute"] == "explicit_in_query"


def test_ein_klartextwort_bleibt_klartext():
    assert _TW._query_method_provenance("zudem", case_insensitive=True)["query_mode"] == "plain_word"
