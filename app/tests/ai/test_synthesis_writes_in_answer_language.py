"""The synthesis call names the answer language, and its evidence speaks it.

English probe of 2026-09-27: the system message of the synthesis named no
language (c1 answered an English question in German), and the evidence
package was labelled in German. Words from the labels went into English
answers: b2 wrote "| Evidenz |", "(Treffer 0–28)" and "(Zeilen 2, 7, 12)".
Path labels (``rows[i]``) and evidence ids stay as they are, references
resolve against them. A German turn keeps every byte.
"""

from __future__ import annotations

from candyconc.candyconc_copilot import interpretation_synthesis as synthesis
from candyconc.answer_language import answer_language_scope
from candyconc.i18n import lt

QUESTION = "Which words are typical of Republican compared with Democratic addresses?"

KWIC = {
    "id": "E_run_cqlf_query_5",
    "tool": "run_cqlf_query",
    "query": '{"query": "Iraq", "docset_id": "628e64bf343649ce838120f1d89a3e47"}',
    "status": "success",
    "grounding_surface": [
        "rows[0] {'kw': 'Iraq', 'left': 'nature . Tonight in', 'right': ', Saddam walks amidst ruin'}",
        "total=68",
    ],
    "fact_surface": {
        "total": 68,
        "rows": [
            {"kw": "Iraq", "left": "nature . Tonight in", "right": ", Saddam walks amidst ruin",
             "file": "sotu-1991-Bush-2", "pos": 285317},
            {"kw": "Iraq", "left": "friends , and freedom in", "right": "will make America safer for",
             "file": "sotu-2005-GWBush", "pos": 396041},
        ],
    },
}
TABLE = {
    "id": "E_keyness_4",
    "tool": "keyness",
    "query": '{"target_docset_id": "a", "reference_docset_id": "b"}',
    "status": "success",
    "grounding_surface": ["rows[0] {'word': 'Iraq', 'target_freq': 68}", "total=40"],
    "fact_surface": {
        "total": 40,
        "warnings": [lt("Reihe ausgedünnt auf 60 von 61 Perioden.",
                        "Series thinned to 60 of 61 periods.")],
        "rows": [{"word": "Iraq", "target_freq": 68, "reference_freq": 6},
                 {"word": "regime", "target_freq": 29, "reference_freq": 0}],
    },
}


def test_an_english_turn_states_the_answer_language():
    with answer_language_scope("en"):
        system, user = synthesis.deutungs_synthese_messages(QUESTION, "EVIDENCE", "CORPUS", "draft")
    assert "ANTWORTSPRACHE: Englisch" in system["content"]
    assert "174,284" in system["content"]
    assert user["content"].startswith("QUESTION:\n")
    assert "EVIDENCE FROM THE TOOL RUNS:" in user["content"]
    assert "DRAFT FROM THE TOOL PHASE:" in user["content"]
    assert "EVIDENZ" not in user["content"] and "FRAGE" not in user["content"]


def test_a_german_turn_keeps_every_byte():
    frage = "Welche Wörter sind typisch für republikanische Reden?"
    ohne = synthesis.deutungs_synthese_messages(frage, "EVIDENZ", "KORPUS", "Entwurf")
    with answer_language_scope("de"):
        mit = synthesis.deutungs_synthese_messages(frage, "EVIDENZ", "KORPUS", "Entwurf")
    assert mit == ohne
    assert "ANTWORTSPRACHE" not in ohne[0]["content"]
    assert ohne[1]["content"].startswith("FRAGE:\n")


def test_the_report_calls_carry_the_language_too():
    with answer_language_scope("en"):
        for system, user in (
            synthesis.gutachten_gliederung_messages(QUESTION, "E"),
            synthesis.gutachten_abschnitt_messages(QUESTION, 1, "T", "A", "E"),
            synthesis.gutachten_gesamt_messages(QUESTION, ["S"]),
        ):
            assert "ANTWORTSPRACHE: Englisch" in system["content"]
            assert user["content"].startswith("QUESTION:\n")


def test_the_english_package_has_english_labels_and_the_same_paths():
    with answer_language_scope("en"):
        paket = synthesis.evidenz_paket_text([KWIC, TABLE])
    assert "Hit 0: nature . Tonight in [Iraq]" in paket
    assert "Row 0: word=Iraq" in paket
    assert "(… 1 more row of this table computed and not listed here)" in paket
    assert "Treffer " not in paket and "Zeile " not in paket
    assert "[E_run_cqlf_query_5]" in paket and "[E_keyness_4]" in paket
    # LocalizedText in a tool result reaches the English package in English.
    assert "Series thinned" in paket and "ausgedünnt" not in paket


def test_the_german_package_is_unchanged():
    ohne = synthesis.evidenz_paket_text([KWIC, TABLE])
    with answer_language_scope("de"):
        mit = synthesis.evidenz_paket_text([KWIC, TABLE])
    assert mit == ohne
    assert "Treffer 0: nature . Tonight in [Iraq]" in ohne
    assert "Zeile 0: " in ohne
