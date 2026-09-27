"""The two appendix lines about one subcorpus name what they count.

English probe of 2026-09-27, run b1: the experiment log wrote "Teilkorpus
gebildet `GOP addresses` → 36 Dokumente, 199.379 Token", the method card
"Zielkorpus 174.284 Tokens in 36 Dokumenten". Both numbers are right:
``create_docset.token_count`` counts all tokens including punctuation,
keyness counts word tokens (at least one letter or digit, target_tokens,
equal to ``create_docset.word_count``). The unit now says so, the numbers
stay.
"""

from __future__ import annotations

from candyconc.answer_language import answer_language_scope
from candyconc.candyconc_copilot.experiment_log import experimente
from candyconc.candyconc_copilot.method_sheet import _analysis_provenance_lines

GOP = "fa94c5d54c8541e793ebbc37b74db6b5"
DEM = "55530f10d20d4b228fb7fdeba6dc9333"


def _items():
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return [
        make_evidence_item(
            item_id="E_create_docset_2", tool="create_docset", tool_call_id="c2",
            query={"filters": {"party": "Republican"}, "label": "GOP addresses"},
            output={"status": "success", "docset_id": GOP, "doc_count": 36, "token_count": 199379,
                    "word_count": 174284, "label": "GOP addresses", "source": "metadata"},
            analysis_family="x"),
        make_evidence_item(
            item_id="E_create_docset_3", tool="create_docset", tool_call_id="c3",
            query={"filters": {"party": "Democratic"}, "label": "Dem addresses"},
            output={"status": "success", "docset_id": DEM, "doc_count": 29, "token_count": 203905,
                    "word_count": 180221, "label": "Dem addresses", "source": "metadata"},
            analysis_family="x"),
        make_evidence_item(
            item_id="E_keyness_4", tool="keyness", tool_call_id="c4",
            query={"target_docset_id": GOP, "reference_docset_id": DEM, "min_freq": 5},
            output={"status": "success", "rows": [{"word": "America", "log_ratio": 0.85}],
                    "diagnostics": {"target_docs": 36, "target_tokens": 174284,
                                    "target_tokens_roh": 199379, "reference_docs": 29,
                                    "reference_tokens": 180221, "reference_tokens_roh": 203905,
                                    "attribute": "word"}},
            analysis_family="x"),
    ]


def test_german_lines_name_both_units():
    log = experimente(_items())
    card = " ".join(_analysis_provenance_lines(_items()))
    assert log[0].startswith("Teilkorpus gebildet `GOP addresses` → 36 Dokumente, "
                             "199.379 Token mit Satzzeichen")
    assert "Zielkorpus 174.284 Wortformen ohne Satzzeichen in 36 Dokumenten" in card
    assert "Referenzkorpus 180.221 Wortformen ohne Satzzeichen in 29 Dokumenten" in card


def test_english_lines_name_both_units():
    with answer_language_scope("en"):
        log = experimente(_items())
        card = " ".join(_analysis_provenance_lines(_items()))
    assert log[0].startswith("Subcorpus built `GOP addresses` → 36 documents, "
                             "199,379 tokens including punctuation")
    assert "target corpus 174,284 word tokens without punctuation in 36 documents" in card
    assert "reference corpus 180,221 word tokens without punctuation in 29 documents" in card
