"""The methods profile and the package name the word denominator.

Since query_count rates on analyst tokens, ``denominator_tokens`` holds the
word count (105,438,787 for the AI side of PING) while create_docset still
reports 130,843,366 tokens. A line "Basis 105.438.787 Tokens" would contradict
the docset profile next to it. The profile names the unit and the raw size.
"""

from __future__ import annotations

import json

from candyconc.candyconc_copilot.grounding_facts import make_evidence_item
from candyconc.candyconc_copilot.method_sheet import _analysis_provenance_lines
from candyconc.candyconc_copilot.word_denominator import ist_wortnenner


def _count_item(**extra):
    output = {
        "status": "success", "query": "sondern", "total": 300722,
        "corpus_tokens": 142044149, "denominator_tokens": 105438787,
        "denominator_scope": "docset", "per_million": 2852.1,
        "query_mode": "plain_word", "attribute": "word", "case_insensitive": True,
        "scope": {"corpus_id": "ping", "level": "docset", "doc_count": 231263},
        **extra,
    }
    return make_evidence_item(
        item_id="E_query_count_1", tool="query_count", tool_call_id="c1",
        query=json.dumps({"query": "sondern"}), output=output, analysis_family="frequency",
    )


def test_profile_names_words_and_the_raw_size():
    item = _count_item(denominator_tokens_raw=130843366,
                       denominator_source="corpus_index.docset_word_count")
    lines = " ".join(_analysis_provenance_lines([item]))
    assert "Basis 105.438.787 Wortformen ohne Satzzeichen (von 130.843.366 Token)" in lines


def test_raw_denominators_keep_their_old_wording():
    item = _count_item(denominator_tokens=130843366,
                       denominator_source="corpus_index.docset_token_count")
    lines = " ".join(_analysis_provenance_lines([item]))
    assert "Basis 130.843.366 Tokens" in lines
    assert "Wortformen" not in lines


def test_word_denominator_is_recognised_by_source_or_by_differing_raw_size():
    assert ist_wortnenner({"denominator_source": "corpus_index.word_count"})
    assert ist_wortnenner({"denominator_tokens": 9, "denominator_tokens_raw": 11,
                           "denominator_source": "where()-Einschraenkung der Abfrage"})
    assert not ist_wortnenner({"denominator_tokens": 11, "denominator_tokens_raw": 11})
    assert not ist_wortnenner({"denominator_tokens": 11})
