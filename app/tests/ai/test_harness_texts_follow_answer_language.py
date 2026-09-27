"""Texts the harness writes into the answer follow the answer language.

English probe of 2026-09-27: every English answer was mixed. The appendices
``### Experimente``, ``### Methodensteckbrief`` and ``### Belegzeilen`` came in
German ("Teilkorpus gebildet `GOP addresses` → 36 Dokumente, 199.379 Token"),
so did the logDice notes, the quotation notice and the recovery message "Das
Modell hat die Abgabe selbst erklärt …", with German digit grouping (for an
English reader "49.536" reads as 49.5). A German turn keeps every text.

The outputs below are the recorded tool results of run b1, reduced to the
fields the appendices read.
"""

from __future__ import annotations

from candyconc.answer_language import answer_language_scope
from candyconc.candyconc_copilot.experiment_log import protokoll_anhaengen
from candyconc.candyconc_copilot.measure_basis import saetze as logdice_saetze
from candyconc.candyconc_copilot.recipe_runtime import (
    methodensteckbrief_anhaengen,
    politur_mit_zitatwache,
)
from candyconc.i18n import lt

GOP = "fa94c5d54c8541e793ebbc37b74db6b5"
DEM = "55530f10d20d4b228fb7fdeba6dc9333"

CALLS = [
    ("create_docset", {"filters": {"party": "Republican"}, "label": "GOP addresses"},
     {"status": "success", "docset_id": GOP, "doc_count": 36, "token_count": 199379,
      "word_count": 174284, "label": "GOP addresses", "source": "metadata"}),
    ("create_docset", {"filters": {"party": "Democratic"}, "label": "Dem addresses"},
     {"status": "success", "docset_id": DEM, "doc_count": 29, "token_count": 203905,
      "word_count": 180221, "label": "Dem addresses", "source": "metadata"}),
    ("keyness", {"target_docset_id": GOP, "reference_docset_id": DEM, "min_freq": 5,
                 "sort_by": "ll_signed", "limit": 40},
     {"status": "success", "rows_total": 4627, "rows_returned": 2, "min_freq": 5,
      "rows": [{"word": "Applause", "log_ratio": 3.9587108045101416, "ll": 420.4413715452174},
               {"word": "America", "log_ratio": 0.8533701149661113, "ll": 93.35509062327174}],
      "diagnostics": {"target_docs": 36, "target_tokens": 174284, "target_tokens_roh": 199379,
                      "reference_docs": 29, "reference_tokens": 180221,
                      "reference_tokens_roh": 203905, "attribute": "word"}}),
    ("run_cqlf_query", {"query": "freedom", "docset_id": GOP, "limit": 50, "ctx": 5},
     {"status": "success", "total": 330, "truncated": True, "limit": 50, "query": "freedom",
      "ctx": 5, "query_mode": "plain_word", "attribute": "word", "case_insensitive": True,
      "scope": {"corpus_id": "sotu_en", "level": "docset", "docset_id": GOP, "doc_count": 36},
      "sample": {"requested": 50, "drawn": 50, "seed": 1742485633, "population": 330,
                 "population_partial": False},
      "rows": [{"kw": "freedom", "left": "never been used to destroy", "right": ", only to defend it",
                "file": "sotu-1972-Nixon", "pos": 187327}]}),
]

COLLOCATES = ("collocate_stats", {"term": "economy", "window": 5, "sort_by": "logdice"},
              {"status": "success", "node_frequency": 436, "result_count": 1,
               "rows": [{"word": "growing", "f": 28, "f2": 107, "logdice": 10.72}]})


def _items(calls):
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return [make_evidence_item(item_id=f"E_{tool}_{i}", tool=tool, tool_call_id=f"c{i}",
                               query=args, output=out, analysis_family="x")
            for i, (tool, args, out) in enumerate(calls, start=2)]


def test_the_experiment_log_speaks_english():
    with answer_language_scope("en"):
        text = protokoll_anhaengen("Answer.", _items(CALLS))
    assert "### Experiments\n" in text
    assert "1. Subcorpus built `GOP addresses` → 36 documents, 199,379 tokens including punctuation" in text
    assert "3. Keyness → 2 rows, strongest: Applause (log_ratio=3.9587108045101416, " in text
    assert "4. Search `freedom` → 330 hits, 1 row, subcorpus GOP addresses" in text
    assert "Teilkorpus" not in text and "Dokumente" not in text and "Treffer" not in text


def test_the_german_experiment_log_keeps_its_text():
    text = protokoll_anhaengen("Antwort.", _items(CALLS))
    assert "### Experimente\n" in text
    assert "3. Keyness → 2 Zeilen, stärkste: Applause (log_ratio=3.9587108045101416, " in text
    assert "4. Suche `freedom` → 330 Treffer, 1 Zeilen, Docset GOP addresses" in text


def test_the_method_card_speaks_english():
    with answer_language_scope("en"):
        text = methodensteckbrief_anhaengen("Answer.", _items(CALLS))
    assert "### Method card\n" in text
    assert "- Subcorpus: Label “GOP addresses”, Filter party=Republican." in text
    assert ("- KWIC: Corpus sotu_en, Subcorpus fa94c5d54c8541e793ebbc37b74db6b5, 36 documents, "
            "Query mode: plain_word, Attribute: word, Case ignored: yes, Search: freedom, "
            "Context width: 5, maximum requested rows: 50, Hits: 330, 1 of them returned as "
            "result rows, random sample of 50 from 330 hits, seed 1742485633.") in text
    assert "Methodensteckbrief" not in text and "Zählebene" not in text


def test_the_german_method_card_keeps_its_text():
    text = methodensteckbrief_anhaengen("Antwort.", _items(CALLS))
    assert "### Methodensteckbrief\n" in text
    assert "- Teilkorpusbildung: Label „GOP addresses“, Filter party=Republican." in text
    assert ("- KWIC: Korpus sotu_en, Teilkorpus fa94c5d54c8541e793ebbc37b74db6b5, 36 Dokumente, "
            "Abfragemodus: plain_word, Attribut: word, Groß-/Kleinschreibung ignoriert: ja, "
            "Suche: freedom, Kontextbreite: 5, maximal angeforderte Zeilen: 50, Treffer: 330, "
            "davon 1 als Ergebniszeilen zurückgegeben, Zufallsstichprobe von 50 aus 330 "
            "Treffern, Seed 1742485633.") in text


def test_the_logdice_note_speaks_english():
    antwort = "*growing* has logDice 10.72 [[beleg:E_collocate_stats_2]]."
    with answer_language_scope("en"):
        saetze = logdice_saetze(antwort, _items([COLLOCATES]))
    assert saetze == ["logDice for “growing” is computed from co-occurrence frequency 28, "
                      "corpus frequency of the collocate 107 and node frequency 436: "
                      "14 + log2(2 · f / (node + f2))."]
    assert logdice_saetze("*growing* hat logDice 10,72.", _items([COLLOCATES])) == [
        "logDice für „growing“ entsteht aus Kookkurrenz 28, Korpusfrequenz des Kollokats 107 "
        "und Knotenfrequenz 436: 14 + log2(2 · f / (Knoten + f2))."]


def test_an_english_answer_recognises_its_own_grouping():
    big = ("collocate_stats", {"term": "economy"},
           {"status": "success", "node_frequency": 4360, "result_count": 1,
            "rows": [{"word": "growing", "f": 28, "f2": 3476, "logdice": 10.72}]})
    with answer_language_scope("en"):
        assert logdice_saetze("*growing* has logDice 10.72 and f2 3,476.", _items([big])) == []


def test_the_chokepoint_writes_english_appendices_and_placeholder():
    antwort = ("*America* is typical [[beleg:E_keyness_4]], one figure is open [Beleg fehlt]. "
               "*freedom* appears 330 times [[beleg:E_run_cqlf_query_5]].")
    with answer_language_scope("en"):
        text, _ = politur_mit_zitatwache(antwort, _items(CALLS), eigene_zitate_bleiben=True)
    assert "[evidence missing]" in text and "[Beleg fehlt]" not in text
    assert "### Experiments" in text and "### Method card" in text
    assert "### Evidence lines" in text
    assert "Index version" not in text or "Indexstand" not in text


def test_the_german_chokepoint_keeps_placeholder_and_headers():
    antwort = ("*America* ist typisch [[beleg:E_keyness_4]], eine Zahl ist offen [Beleg fehlt]. "
               "*freedom* steht 330-mal da [[beleg:E_run_cqlf_query_5]].")
    text, _ = politur_mit_zitatwache(antwort, _items(CALLS), eigene_zitate_bleiben=True)
    assert "[Beleg fehlt]" in text
    assert "### Experimente" in text and "### Methodensteckbrief" in text
    assert "### Belegzeilen" in text


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, event, session_id=None):
        self.events.append(event)


def test_the_recovery_message_speaks_the_answer_language():
    from tests.ai._real_copilot import make_orchestrator

    message = lt("Das Modell hat die Abgabe selbst erklärt. Die Deutung entsteht jetzt aus der "
                 "vollen Evidenz.",
                 "The model declared its investigation finished. The interpretation is now "
                 "written from the full evidence.")
    orch = make_orchestrator([], lambda *a, **k: {}, lambda *a, **k: {})
    orch.session.session_id = "s1"
    bus = _Bus()
    with answer_language_scope("en"):
        orch._ra_emit_recovery(bus, "q", "deutung_abgegeben", message)
    orch._ra_emit_recovery(bus, "q", "deutung_abgegeben", message)
    texts = [e["recovery"]["message"] for e in bus.events if e.get("event") == "copilot.recovery"]
    assert texts == [message.en, message.de]
    assert type(texts[1]) is str
