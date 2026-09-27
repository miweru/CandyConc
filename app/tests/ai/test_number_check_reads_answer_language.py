"""The number check reads numbers in the convention of the answer language.

English probe of 2026-09-27, run b1, ``zahlen_ohne_wortbeleg.txt``: the
correct English numbers "174,284" and "180,221" (keyness corpus sizes) were
listed as unsupported, and "85" and "78" appeared from ".85" and ".78". The
check read the comma as a decimal comma. With ``CANDYCONC_ZAHLEN_STREICHEN=1``
these numbers would have been replaced by the missing-evidence placeholder.
German answers keep the German reading.
"""

from __future__ import annotations

from candyconc.answer_language import answer_language_scope
from candyconc.candyconc_copilot import grounding_refs
from candyconc.candyconc_copilot import interpretation_synthesis as synthesis
from candyconc.candyconc_copilot.recipe_runtime import resolve_reference_draft

# Recorded keyness result of run b1, reduced to the values the sentence cites.
KEYNESS = {
    "status": "success",
    "total": 40,
    "diagnostics": {"target_tokens": 174284, "target_docs": 36,
                    "reference_tokens": 180221, "reference_docs": 29},
    "rows": [
        {"word": "America", "target_freq": 701, "reference_freq": 401,
         "target_per_million": 4022.1707098758347, "reference_per_million": 2225.0459158477647,
         "log_ratio": 0.8533701149661113, "log_ratio_ci_low": 0.6771, "log_ratio_ci_high": 1.0296},
        {"word": "freedom", "target_freq": 330, "reference_freq": 165,
         "log_ratio": 1.0461460535640008, "log_ratio_ci_low": 0.7766, "log_ratio_ci_high": 1.3157},
    ],
}

SENTENCE = (
    "Republican addresses (36 texts, 174,284 words) vs Democratic addresses (29 texts, "
    "180,221 words): *America* has log_ratio .85 [CI .68–1.03] and *freedom* log_ratio "
    "1.05 [CI .78–1.32] [[beleg:E_keyness_4]]."
)


def _items():
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return [make_evidence_item(item_id="E_keyness_4", tool="keyness", tool_call_id="c4",
                               query={"target_docset_id": "a", "reference_docset_id": "b"},
                               output=KEYNESS, analysis_family="contrast_keyness").to_dict()]


def _flagged(text):
    result = resolve_reference_draft(text, _items(), "Which words are typical?")
    return [finding["number"] for finding in result["bare_numbers"]]


def test_english_grouping_and_short_decimals_are_supported():
    with answer_language_scope("en"):
        flagged = _flagged(SENTENCE)
    for number in ("174,284", "180,221", ".85", ".68", ".78", "85", "78"):
        assert number not in flagged, flagged


def test_a_wrong_english_number_is_still_flagged():
    with answer_language_scope("en"):
        flagged = _flagged(SENTENCE.replace("174,284", "174,824").replace(".85", ".58"))
    assert "174,824" in flagged and ".58" in flagged


def test_the_german_reading_is_unchanged():
    # German answer text: "174,284" is a decimal number there and not supported,
    # ".85" is read as 85.
    flagged = _flagged(SENTENCE)
    assert "174,284" in flagged and "85" in flagged


def test_canonical_form_follows_the_answer_language():
    assert synthesis._zahl_kanonisch("174,284", deutsch=True) == repr(174.284)
    assert synthesis._zahl_kanonisch("174.284", deutsch=True) == repr(174284.0)
    with answer_language_scope("en"):
        assert synthesis._zahl_kanonisch("174,284", deutsch=True) == repr(174284.0)
        assert synthesis._zahl_kanonisch("1,592.3", deutsch=True) == repr(1592.3)
        assert synthesis._zahl_kanonisch(".85", deutsch=True) == repr(0.85)
        assert synthesis._zahl_kanonisch("0.85,", deutsch=True) == repr(0.85)
    # Evidence values (JSON form) keep their reading in both languages.
    with answer_language_scope("en"):
        assert synthesis._zahl_kanonisch("21.1") == repr(21.1)


def test_rounded_restatement_uses_the_answer_language():
    assert grounding_refs._zahllesarten("1,592.3") == [(1.5923, 4)]
    with answer_language_scope("en"):
        assert grounding_refs._zahllesarten("1,592.3") == [(1592.3, 1)]
        assert grounding_refs._zahllesarten("174,284") == [(174284.0, 0)]
        assert grounding_refs._zahllesarten("18.761") == [(18.761, 3)]


def test_inserted_values_use_the_grouping_of_the_answer_language():
    assert grounding_refs._format_number(49536) == "49.536"
    assert grounding_refs._format_number(True) == "ja"
    with answer_language_scope("en"):
        assert grounding_refs._format_number(49536) == "49,536"
        assert grounding_refs._format_number(49536.0) == "49,536"
        assert grounding_refs._format_number(True) == "yes"
