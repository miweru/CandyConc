"""Answer and routing language agree across deterministic response paths."""
from types import SimpleNamespace

import pytest

from candyconc.answer_language import answer_language_scope, detect_question_language
from candyconc.question_language import is_english_question
from candyconc.candyconc_copilot import grounding_markdown as gm
from candyconc.candyconc_copilot.death_landings import _kwic_death_report
from candyconc.candyconc_copilot.deterministic_landing import korpusgroesse_antwort
from candyconc.candyconc_copilot.grounding_schemas import _user_facing_evidence_gap
from candyconc.candyconc_copilot.recipe_runtime import is_explicit_split_qa_request, verifier_skipped_answer_text
from candyconc.candyconc_copilot.row_spelling_note import alle_saetze


def test_mixed_question_has_one_language_decision():
    question = "Welche Kollokate hat 'economy' in the State of the Union?"
    assert detect_question_language(question) == "de"
    assert is_english_question(question) == (detect_question_language(question) == "en")


@pytest.mark.parametrize("question", [
    "Compare the train and test partitions.",
    "Investigate differences between the data subsets.",
    "Examine the data split.",
])
def test_english_split_qa_reads_routing_cues(question):
    assert is_explicit_split_qa_request(question)


@pytest.mark.parametrize("counts", [{"home": 1200}, {"Home": 20, "home": 1180}])
def test_spelling_note_uses_answer_language_and_grouped_count(counts):
    item = SimpleNamespace(fact_surface={"rows": [{"word": "Home", "surface_variants": {"target": counts}}]})
    with answer_language_scope("en"):
        notes = alle_saetze('The row "Home" has 1,200 hits.', [item])
    assert len(notes) == 1
    assert "spelling class" in notes[0]
    assert '"home"' in notes[0]
    assert "1,200" in notes[0]


def test_verifier_skip_is_english_with_and_without_draft():
    with answer_language_scope("en"):
        for draft in ("", "One example is visible."):
            text = verifier_skipped_answer_text(draft, lambda s: {"text": s}, lambda: "Visible evidence.", str)
            assert "Note: LLM verification skipped (time budget)." in text
            assert "Hinweis" not in text


def test_kwic_death_landing_is_english_and_keeps_corpus_quote():
    with answer_language_scope("en"):
        text = _kwic_death_report(query_term="Heimat", total_hits=2, rows_seen=1, examples=["Heimat ist hier."])
    assert "occurs" in text and "Concordance lines:" in text
    assert "Heimat ist hier." in text
    assert "Belegzeile" not in text


def test_corpus_card_landing_is_english():
    with answer_language_scope("en"):
        text = korpusgroesse_antwort("Wie groß ist das Korpus?", {"docs": 1200, "tokens": 13000, "corpus_id": "sample"})
    assert "The active corpus sample" in text
    assert "1,200 documents" in text and "13,000 tokens" in text


def test_conservative_landing_is_english():
    with answer_language_scope("en"):
        text = gm.build_conservative_markdown([], evidence_gaps=["kwic_rows"])
    assert "Observations:" in text and "Limitations:" in text
    assert "concordance lines" in text
    assert "Beobachtungen" not in text


@pytest.mark.parametrize("gap, expected", [("kwic_rows", "concordance lines"), ("frequency_rows", "frequency rows"), ("truncated=true", "limited to the visible top-N results")])
def test_evidence_gap_labels_follow_answer_language(gap, expected):
    with answer_language_scope("en"):
        assert _user_facing_evidence_gap(gap) == expected


def test_nested_ui_locale_precedes_request_language():
    from candyconc.answer_language import resolve_answer_language

    assert resolve_answer_language('[lemma="tree"]', {"session": {"locale": "en"}}, "de") == "en"
    assert resolve_answer_language('[lemma="tree"]', {"session": {"locale": "de"}}, "en") == "de"


def evidence(tool, surface):
    from candyconc.candyconc_copilot.grounding_schemas import EvidenceItem

    return EvidenceItem(id="ev1", tool=tool, tool_call_id="call1", query='{"query":"home"}', status="success", truncated=False, raw_surface=surface)


def test_generated_facts_use_answer_language_without_changing_evidence():
    from candyconc.candyconc_copilot.grounding_facts import _query_count_facts

    item = evidence("query_count", {"total": 1200, "query": "home"})
    item.grounding_surface = ["total=1200"]
    with answer_language_scope("de"):
        german = _query_count_facts(item)
    with answer_language_scope("en"):
        english = _query_count_facts(item)
    assert german and english
    assert "exact hit count" in english[0].statement
    assert english[0].grounding_quotes == german[0].grounding_quotes
    assert english[0].supports_claims == german[0].supports_claims


@pytest.mark.parametrize("builder,tool,surface,expected", [
    (gm._build_term_frequency_markdown, "query_count", {"total": 1200, "query": "home", "denominator_scope": "corpus"}, "occurs exactly 1200 times in the active corpus"),
    (gm._build_metadata_capability_markdown, "metadata_values", {"values": {"genre": ["essay", "speech"]}}, "Visible metadata fields:"),
    (gm._build_semantic_markdown, "semantic_search", {"rows": [{"text": "A small home near the sea."}]}, "Visible semantic passages:"),
])
def test_family_landing_templates_are_english(builder, tool, surface, expected):
    with answer_language_scope("en"):
        text = builder([evidence(tool, surface)], evidence_gaps=[])
    assert expected in text
    for german in ("sichtbare", "Sichtbare", "Korpus", "Limitationen", "Treffer", "Metadatenfelder"):
        assert german not in text


def test_english_verifier_note_is_recognised_by_final_polish():
    from candyconc.candyconc_copilot.recipe_runtime import final_answer_polish

    with answer_language_scope("en"):
        draft = verifier_skipped_answer_text("One example is visible.", lambda text: {"text": text}, lambda: "", str)
        text, annotations = final_answer_polish(draft)
    assert "Verification status:" in text
    assert "LLM verification skipped" not in text
    assert any("LLM verification skipped" in entry["note"] for entry in annotations)


@pytest.mark.parametrize("recipe,axes,expected", [
    ("verlauf", [], "This corpus has no date field"),
    ("verlauf", [{"field": "genre", "kind": "axis"}], "genre"),
    ("verlauf", [{"field": "split", "kind": "technical"}], "technical data partition"),
    ("verlauf", [{"field": "source", "kind": "single"}], "individual concordance lines"),
    ("kontrast", [], "This corpus has no metadata axis"),
    ("kontrast", [{"field": "genre", "kind": "single"}, {"field": "split", "kind": "technical"}], "single-valued fields"),
])
def test_precondition_landing_uses_the_answer_language(recipe, axes, expected):
    from candyconc.candyconc_copilot.recipe_runtime import precondition_unmet_answer, recipe_precondition_status

    with answer_language_scope("en"):
        status = recipe_precondition_status(recipe, {"meta_fields": [axis["field"] for axis in axes], "meta_axes": axes, "date_fields": []})
        assert status["short_circuit"]
        text = precondition_unmet_answer(recipe, status["alternative"])
    assert expected in text
    for german in ("Korpus", "keine", "Alternative", "einen", "Frequenz", "einwertige"):
        assert german not in text
