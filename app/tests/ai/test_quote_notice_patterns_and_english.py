"""Quotation notice: gap notes in patterns, and English quotation forms.

1. A pattern with a size note at its gap, „nicht nur …(≤12 Token)… sondern“,
   triggered the notice although no corpus line can contain "(≤12 Token)".
   The literal parts stay checked. „kein Beleg für „X““ no longer triggers it
   (fixed earlier, checked here again).
2. The notice looked at „…“ only. An English answer quotes with “…” or "…",
   so every English quotation passed unchecked. Case b2 of the English probe
   of 2026-09-27: four quotations taken from concordance lines.
3. A real misquotation stays reported (run d: „das Recht über sein Leben und
   Freiheit zu verfügen“, the line starts with "Recht über sein Leben").
"""

from __future__ import annotations

from candyconc.answer_language import answer_language_scope
from candyconc.candyconc_copilot import interpretation_synthesis as synthesis

KORRELAT = [{"grounding_surface": [
    "Treffer 3: Das ist nicht nur eine Frage des Geldes , sondern auch der Zeit  (doc_1, pos 17)",
]}]

MUSTER = ("Gesucht wurde die Korrelatfolge „nicht nur …(≤12 Token)… sondern“ "
          "[[beleg:E_run_cqlf_query_3]], sie trifft 45-mal.")

BEHAUPTUNG = ("Die Zählung ist kein Beleg für „KI übertreibt mit nicht nur … sondern auch“ "
              "[[beleg:E_run_cqlf_query_3]].")

# Recorded rows of E_run_cqlf_query_5 and _6 in run b2 (sotu_en).
_IRAQ = [
    {"file": "sotu-2003-GWBush", "kw": "Iraq", "left": "with UN inspectors in disarming",
     "right": "will be killed , along", "pos": 383076},
    {"file": "sotu-2005-GWBush", "kw": "Iraq", "left": "friends , and freedom in",
     "right": "will make America safer for", "pos": 396041},
    {"file": "sotu-1991-Bush-2", "kw": "Iraq", "left": "nature . \n Tonight in",
     "right": ", Saddam walks amidst ruin", "pos": 285317},
]
_REGIME = [
    {"left": "The only answer to a", "kw": "regime", "right": "that wages total cold war",
     "pos": 97450, "file": "sotu-1958-Eisenhower"},
]


def _b2():
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return [
        make_evidence_item(item_id=eid, tool="run_cqlf_query", tool_call_id=eid, query={"query": q},
                           output={"status": "success", "total": len(rows), "rows": rows},
                           analysis_family="kwic_context").to_dict()
        for eid, q, rows in (("E_run_cqlf_query_5", "Iraq", _IRAQ),
                             ("E_run_cqlf_query_6", "regime", _REGIME))
    ]


B2_TEXT = (
    "*Iraq* occurs in 9 GOP documents with 68 hits [[beleg:E_run_cqlf_query_5]], including "
    "“Tonight in [Iraq], Saddam walks amidst ruin” from the 1991 G.H.W. Bush address "
    "[[beleg:E_run_cqlf_query_5]]. The KWIC line “The only answer to a [regime] that wages total "
    "cold war” shows the hostile-government framing [[beleg:E_run_cqlf_query_6]]. The KWIC line "
    "“freedom in [Iraq] will make America safer” shows how the frames converge "
    "[[beleg:E_run_cqlf_query_5]]."
)

D_ZEILE = [{"grounding_surface": [
    "rows[1] {'kw': 'Freiheit', 'left': 'Recht über sein Leben und', 'right': 'zu verfügen und sie zu', "
    "'file': 'perthes_buchhandel_1816', 'pos': 51805}",
]}]
D_TEXT = ("In Gebrauchsliteratur ist sie vor allem ein Item in Rechtsaufzählungen: „das Recht über "
          "sein Leben und Freiheit zu verfügen“ [[beleg:E_run_cqlf_query_8]].")


def test_a_pattern_with_a_gap_note_is_no_corpus_quotation():
    assert synthesis._unverifizierte_zitate(MUSTER, KORRELAT) == []


def test_its_literal_parts_stay_checked():
    falsch = MUSTER.replace("sondern", "vielmehr")
    assert synthesis._unverifizierte_zitate(falsch, KORRELAT) != []


def test_evidence_for_introduces_a_statement():
    assert synthesis._unverifizierte_zitate(BEHAUPTUNG, KORRELAT) == []


def test_the_real_misquotation_of_run_d_stays_reported():
    assert synthesis._unverifizierte_zitate(D_TEXT, D_ZEILE) == [
        "das Recht über sein Leben und Freiheit zu verfügen"]


def test_english_quotations_from_concordance_lines_are_verified():
    with answer_language_scope("en"):
        spans = [m.group(1) for m in synthesis._zitatspannen(B2_TEXT)]
        assert len(spans) == 3
        assert synthesis._unverifizierte_zitate(B2_TEXT, _b2()) == []


def test_an_english_misquotation_is_reported():
    falsch = B2_TEXT.replace("walks amidst ruin", "walks proudly among his troops")
    with answer_language_scope("en"):
        assert synthesis._unverifizierte_zitate(falsch, _b2()) == [
            "Tonight in [Iraq], Saddam walks proudly among his troops"]
    straight = ('For example, "Tonight in Iraq, Saddam walks proudly among his troops" '
                "[[beleg:E_run_cqlf_query_5]].")
    with answer_language_scope("en"):
        assert synthesis._unverifizierte_zitate(straight, _b2()) != []


def test_english_own_wording_is_no_corpus_quotation():
    text = ("A cautious phrasing would be “Republicans foreground security more often” "
            "[[beleg:E_keyness_4]].")
    with answer_language_scope("en"):
        assert synthesis._unverifizierte_zitate(text, _b2()) == []


def test_a_german_answer_ignores_english_quotation_marks_as_before():
    falsch = B2_TEXT.replace("walks amidst ruin", "walks proudly among his troops")
    assert synthesis._unverifizierte_zitate(falsch, _b2()) == []


def test_the_notice_speaks_the_answer_language():
    assert "(„" in synthesis.choose("(„{}“)", "(“{}”)").format("x")
    with answer_language_scope("en"):
        assert synthesis.choose("(„{}“)", "(“{}”)").format("x") == "(“x”)"
