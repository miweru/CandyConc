from dataclasses import dataclass, field

from candyconc.tooling import (
    filter_dispatchable_tools_for_principal,
    response_contract_for_prompt,
    select_tools_for_prompt,
)

# The conftest registry shim only registers a subset of stub tools, so names
# like compare_collocates / metadata_values / semantic_cluster_words never
# reach the selector ("stub shadowing").  Use the REAL production surface
# (src/candyconc/candyconc_copilot/tool_wrappers.py) loaded via the
# real-module loader; the selection logic itself
# (src/candyconc/tooling/tool_selection.py) is already loaded real by
# the conftest.
from tests.tooling._real_tooling import REAL_TOOLS


@dataclass(frozen=True)
class _FakeRoute:
    requires_corpus_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FakeBinding:
    tool_name: str
    operation_id: str
    effects: tuple[str, ...] = ("read",)
    capability_id: str = "test.capability"
    route: _FakeRoute = field(default_factory=_FakeRoute)


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def _names(question: str, *, ui_context: dict | None = None) -> list[str]:
    return [
        tool["function"]["name"]
        for tool in select_tools_for_prompt(question, REAL_TOOLS, ui_context=ui_context)
    ]


def test_dispatchable_tool_filter_matches_release_read_only_gate():
    bindings = {
        "read_tool": (_FakeBinding("read_tool", "read"),),
        "write_tool": (_FakeBinding("write_tool", "write", effects=("write",)),),
        "missing_runtime": (_FakeBinding("missing_runtime", "missing"),),
    }
    runtime_info = {
        "read_tool": {"read_only": True, "concurrency_safe": True},
        "write_tool": {"read_only": False, "concurrency_safe": False},
    }

    names = [
        item["function"]["name"]
        for item in filter_dispatchable_tools_for_principal(
            [_tool("read_tool"), _tool("write_tool"), _tool("missing_runtime"), _tool("unbound")],
            runtime_info=runtime_info,
            allowed_tools=None,
            release_mode=True,
            bindings_by_tool=bindings,
        )
    ]

    assert names == ["read_tool"]


def test_dispatchable_tool_filter_respects_explicit_acl_and_still_requires_metadata():
    bindings = {
        "read_tool": (_FakeBinding("read_tool", "read"),),
        "write_tool": (_FakeBinding("write_tool", "write", effects=("write",)),),
        "missing_runtime": (_FakeBinding("missing_runtime", "missing"),),
    }
    runtime_info = {
        "read_tool": {"read_only": True, "concurrency_safe": True},
        "write_tool": {"read_only": False, "concurrency_safe": False},
    }

    names = [
        item["function"]["name"]
        for item in filter_dispatchable_tools_for_principal(
            [_tool("read_tool"), _tool("write_tool"), _tool("missing_runtime")],
            runtime_info=runtime_info,
            allowed_tools=["write_tool", "missing_runtime"],
            release_mode=True,
            bindings_by_tool=bindings,
        )
    ]

    assert names == ["write_tool"]


def test_collocation_prompt_prefers_collocation_tools():
    names = _names("Berechne die Kollokationen für das Wort Mensch.")
    assert "collocate_stats" in names
    assert "run_cqlf_query" in names
    assert "semantic_cluster" not in names
    assert "documentation_search" not in names


def test_compare_prompt_prefers_compare_collocates():
    names = _names("Vergleiche die Kollokationen von Mensch zwischen Human und AI.")
    assert "compare_collocates" in names
    assert "collocate_stats" in names


def test_frequency_prompt_prefers_frequency_tools():
    # FT-COPILOT-PARITY/DT-PROMPTS-DRIFT: a frequency/"how often" shape now also
    # surfaces query_count (the exact-count tool) alongside frequency_list and the
    # KWIC path, in deterministic _TOOL_ORDER.
    names = _names("Erstelle eine Frequenzliste und sage mir die häufigsten Wörter.")
    # deuting_abgeben (Ausgang des MODELLS) ist seit der Naht-Reparatur
    # immer am Ende der Auswahl (Diagnose diagnose_keine_abgabe.md).
    assert names == ["run_cqlf_query", "query_count", "frequency_list",
                     "deutung_abgeben"]


def test_count_question_routes_to_query_count():
    # "Wie oft kommt X vor?" must reach query_count (the COUNT tool); the DT-
    # PROMPTS-DRIFT fix moves the count question off run_cqlf_query/frequency_list.
    names = _names("Wie oft kommt das Wort Demokratie vor?")
    assert "query_count" in names


def test_presence_prompt_keeps_kwic_path():
    # A presence question keeps the KWIC path plus a wide-context grounding tool.
    names = _names("Kommt das Wort Demokratie im Korpus vor?")
    assert names == ["run_cqlf_query", "kwic_context", "deutung_abgeben"]


def test_kwic_context_prompt_keeps_kwic_path():
    names = _names("Zeig mir für 'Demokratie' kurz den sichtbaren Kontext.")
    assert names == ["run_cqlf_query", "kwic_context", "deutung_abgeben"]


def test_parallel_prompt_surfaces_parallel_tools():
    # FT-COPILOT-PARITY: the flagship Human-vs-AI aligned view.
    names = _names("Stelle Mensch vs KI parallel/ausgerichtet gegenüber.")
    assert "parallel_groups" in names
    assert "parallel_kwic" in names


def test_fulltext_prompt_surfaces_document_text():
    names = _names("Lies den ganzen Text des Dokuments und zeig mir den Quelltext.")
    assert "document_text" in names


def test_presence_prompt_adds_brief_contract():
    contract = response_contract_for_prompt("Kommt das Wort Demokratie im Korpus vor?")
    assert contract is not None
    assert contract["response_style"] == "brief_presence_answer"
    assert "1-3 Saetzen" in contract["response_contract"]


def test_metadata_prompt_prefers_metadata_and_document_tools():
    names = _names("Welche Metadatenfelder und Quellen hat das Korpus?")
    assert "metadata_values" in names
    assert "document_search" in names
    assert "semantic_cluster" not in names


def test_subcorpus_compare_prompt_adds_keyness():
    names = _names("Vergleiche die Subkorpora nach Metadaten und berechne Keyness.")
    assert "metadata_values" in names
    assert "document_search" in names
    assert "keyness" in names


def test_dispersion_prompt_prefers_dispersion_tool():
    names = _names("Untersuche die Verteilung von 'Demokratie' im Korpus.")
    assert "dispersion_offsets" in names
    assert "run_cqlf_query" in names
    assert "metadata_values" not in names


def test_trend_prompt_selects_trend_analysis():
    names = _names("Zeige den Trend von 'Demokratie' pro Jahr.")
    assert "trend_analysis" in names
    assert "metadata_values" in names
    assert "query_count" in names


def test_trend_prompt_survives_frequency_cofire():
    # "Verlauf" + "Häufigkeit" co-fires the frequency flag; the trend tool must
    # stay reachable (keyness / diversity pattern: unconditional on the flag).
    names = _names("Wie hat sich die Häufigkeit von Klima im Zeitverlauf entwickelt?")
    assert "trend_analysis" in names
    assert "query_count" in names


def test_semantic_prompt_prefers_similar_words_when_available():
    tools = [
        {"type": "function", "function": {"name": "similar_words"}},
        {"type": "function", "function": {"name": "semantic_cluster_words"}},
        {"type": "function", "function": {"name": "document_search"}},
    ]
    names = [
        tool["function"]["name"]
        for tool in select_tools_for_prompt("Finde semantisch ähnliche Texte zu Demokratie.", tools)
    ]
    assert names == ["similar_words", "document_search"]


def test_unclear_prompt_keeps_full_tool_surface():
    full_names = [tool["function"]["name"] for tool in REAL_TOOLS]
    names = _names("Hilf mir bitte.")
    assert "semantic_cluster" not in names
    assert "semantic_cluster_words" not in names
    assert set(names).issubset(set(full_names))
    assert "run_cqlf_query" in names
    assert "document_search" in names


def test_kwic_ui_context_keeps_query_tool():
    names = _names("Analysiere das.", ui_context={"view": {"activeTab": "kwic"}})
    assert "run_cqlf_query" in names


def test_open_exploratory_prompt_prefers_multi_tool_research_bundle():
    tools = [
        {"type": "function", "function": {"name": "frequency_list"}},
        {"type": "function", "function": {"name": "metadata_values"}},
        {"type": "function", "function": {"name": "similar_words"}},
        {"type": "function", "function": {"name": "semantic_cluster_words"}},
        {"type": "function", "function": {"name": "document_search"}},
        {"type": "function", "function": {"name": "run_cqlf_query"}},
    ]
    names = [
        tool["function"]["name"]
        for tool in select_tools_for_prompt(
            "Erzähle mir drei interessante, direkt belegte Dinge über dieses Korpus.",
            tools,
        )
    ]
    assert "frequency_list" in names
    assert "metadata_values" in names
    assert "similar_words" in names
    assert "semantic_cluster_words" not in names
    assert "run_cqlf_query" not in names


def test_open_comparative_prompt_prefers_comparison_bundle():
    names = _names("Arbeite drei belastbare Unterschiede zwischen Human- und AI-Teil des Korpus heraus.")
    assert "compare_collocates" in names
    assert "keyness" in names
    assert "metadata_values" in names
    assert "frequency_list" in names
    assert "run_cqlf_query" not in names


def test_unterscheiden_prompt_keeps_comparison_and_scope_tools():
    names = _names("Wie unterscheiden sich die Parteien beim Thema Flucht?")
    assert "contrast_collocates" in names
    assert "keyness" in names
    assert "metadata_values" in names
    assert "create_docset" in names


def test_open_theme_overview_prompt_prefers_exploratory_bundle():
    names = _names("Welche Themen wirken in diesem Korpus besonders zentral, und woran erkennt man das in den sichtbaren Belegen?")
    assert "frequency_list" in names
    assert "metadata_values" in names
    assert "semantic_cluster_words" not in names
    assert "run_cqlf_query" not in names


def test_followup_question_prompt_prefers_exploratory_bundle():
    names = _names("Welche korpuslinguistisch sinnvollen Anschlussfragen ergeben sich aus diesem Korpus, und welche sichtbaren Evidenzen motivieren diese Fragen?")
    assert "frequency_list" in names
    assert "metadata_values" in names
    assert "semantic_cluster_words" not in names


def test_collocation_network_in_real_surface():
    # The graph tool must exist in the production surface for _ordered_subset to
    # ever return it; D5 also relies on it sitting in _TOOL_ORDER.
    assert "collocation_network" in [tool["function"]["name"] for tool in REAL_TOOLS]


def test_collocation_prompt_keeps_collocation_network():
    # D5: narrowing a collocation prompt must NOT drop the network tool.
    names = _names("Berechne die Kollokationen für das Wort Mensch.")
    assert "collocation_network" in names
    assert "collocate_stats" in names


def test_network_prompt_keeps_collocation_network():
    for prompt in (
        "Zeig mir das Kollokationsnetzwerk von Klima.",
        "Baue ein Netzwerk der Kollokationen rund um Demokratie.",
        "Wortnetz von Haus bitte.",
        "Erzeuge einen Graph der stärksten Nachbarn von Mensch.",
    ):
        names = _names(prompt)
        assert "collocation_network" in names, prompt
        assert "collocate_stats" in names, prompt
        assert "run_cqlf_query" in names, prompt


def test_ngram_prompt_routes_to_ngram_tools():
    names = _names("Welche häufigen Phrasen und Bigramme treten im Korpus auf?")
    assert "ngram_frequency" in names


def test_ngram_compare_prompt_adds_ngram_contrast():
    names = _names("Vergleiche die häufigen Phrasen zwischen den Teilkorpora.")
    assert "ngram_frequency" in names
    assert "ngram_contrast" in names


def test_metadata_prompt_offers_docset_builders():
    names = _names("Welche Metadatenfelder und Quellen hat das Korpus?")
    assert "create_docset" in names
    assert "list_docsets" in names
    assert "resolve_subcorpus" in names


def test_subcorpus_contrast_metadata_prompt_adds_contrast_and_docset_tools():
    names = _names("Vergleiche die Subkorpora nach Quelle und kontrastiere ihre Kollokate.")
    assert "metadata_values" in names
    assert "create_docset" in names
    assert "contrast_collocates" in names


def test_new_f5_tools_present_in_real_surface():
    real_names = [tool["function"]["name"] for tool in REAL_TOOLS]
    for name in (
        "create_docset",
        "list_docsets",
        "resolve_subcorpus",
        "ngram_frequency",
        "ngram_contrast",
    ):
        assert name in real_names, name


def test_diversity_prompt_selects_lexical_diversity_bare():
    # T9: bare lexical-diversity phrasing must surface the diversity tool.
    names = _names("Berechne die lexikalische Vielfalt dieses Korpus.")
    assert "lexical_diversity" in names
    assert "frequency_list" in names


def test_diversity_prompt_keeps_tool_in_human_vs_ai_comparative():
    # T9: the headline human-vs-AI diversity comparison must NOT drop the tool
    # even though "vergleiche"/"human und ai" co-fire (compare/comparative_open).
    names = _names("Vergleiche die lexikalische Vielfalt zwischen Human- und AI-Teil.")
    assert "lexical_diversity" in names


def test_diversity_prompt_keeps_tool_per_register():
    # T9: a per-register diversity question co-fires the metadata branch; the
    # diversity tool must still be selected.
    names = _names("Wie unterscheidet sich die lexikalische Vielfalt je Register?")
    assert "lexical_diversity" in names


def test_diversity_prompt_keeps_tool_with_frequency_cofire():
    # T9: "häufig" trips the frequency branch; the diversity tool must persist.
    names = _names("Welche STTR und welche häufigsten Wörter hat das Korpus?")
    assert "lexical_diversity" in names
    assert "frequency_list" in names


def test_similar_words_tool_present_in_real_surface():
    # F8: the distributional-thesaurus tool must exist in the production surface
    # for _ordered_subset to ever return it (it also sits in _TOOL_ORDER).
    assert "similar_words" in [tool["function"]["name"] for tool in REAL_TOOLS]


def test_thesaurus_prompt_selects_similar_words():
    # F8: the obvious thesaurus phrasings must surface the similar_words tool.
    for prompt in (
        "Welche ähnliche Wörter zu Klima gibt es?",
        "Gib mir den Thesaurus für Mensch.",
        "Nenne Synonyme von Demokratie.",
        "Zeig mir das Wortfeld rund um Freiheit.",
        "Welche Nachbarwörter hat 'Haus'?",
    ):
        names = _names(prompt)
        assert "similar_words" in names, prompt


def test_thesaurus_prompt_survives_comparative_cofire():
    # F8: a comparative prompt that also asks for similar words co-fires the
    # compare branch; the similar_words tool must NOT be narrowed out.
    names = _names("Vergleiche die ähnliche Wörter zu Klima zwischen Human- und AI-Teil.")
    assert "similar_words" in names


def test_thesaurus_prompt_survives_frequency_cofire():
    # F8: "häufig" trips the frequency branch; the similar_words tool must persist.
    names = _names("Welche häufigsten und welche ähnliche Wörter (similar words) hat 'Klima'?")
    assert "similar_words" in names
    assert "frequency_list" in names


def test_thesaurus_prompt_survives_semantic_cofire():
    # F8: "thema"/"cluster" trips the semantic branch; the thesaurus tool must
    # still be reachable (sibling-flag co-fire is the F8 regression target).
    names = _names("Welche ähnliche Wörter zu Klima clustern sich zu einem Thema?")
    assert "similar_words" in names


def test_method_help_prompt_prefers_grounded_method_bundle():
    tools = [
        {"type": "function", "function": {"name": "frequency_list"}},
        {"type": "function", "function": {"name": "metadata_values"}},
        {"type": "function", "function": {"name": "similar_words"}},
        {"type": "function", "function": {"name": "document_search"}},
        {"type": "function", "function": {"name": "documentation_search"}},
        {"type": "function", "function": {"name": "run_cqlf_query"}},
    ]
    names = [
        tool["function"]["name"]
        for tool in select_tools_for_prompt(
            "Wenn du dieses Korpus als Forschender neu bekaemst: Welche ersten drei Analyseschritte würdest du empfehlen und warum, rein auf Basis sichtbarer Evidenz?",
            tools,
        )
    ]
    assert "frequency_list" in names
    assert "metadata_values" in names
    assert "similar_words" in names
    assert "document_search" in names
    assert "documentation_search" in names
    assert "run_cqlf_query" not in names


def test_usage_question_gets_no_brief_presence_contract():
    # H7/A1 (R7-Befund kwic_zeit): "Wie wird X verwendet?" ist eine Analyse.
    # Der brief-presence-Vertrag ("hoechstens EIN Evidenzpunkt") hat live die
    # Mehrbeleg-Antwortform des gebrauch_kwic-Rezepts ueberstimmt.
    contract = response_contract_for_prompt(
        "Wie wird 'Zeit' verwendet? Zeige KWIC-Belege im Kontext."
    )
    assert contract is None


def test_interpretation_cue_gets_no_brief_presence_contract():
    contract = response_contract_for_prompt(
        "Deute die KWIC-Belege für 'Zeit' im Kontext."
    )
    assert contract is None


def test_plain_presence_question_keeps_brief_contract():
    contract = response_contract_for_prompt(
        "Kommt das Wort Demokratie im Korpus vor?"
    )
    assert contract is not None
    assert contract["response_style"] == "brief_presence_answer"


def test_long_presence_question_loses_the_brief_contract():
    """Long inventory questions use the shared analysis decision.

The tool-selection and contract layers read candyconc.question_kind
so a long cue-free question does not receive contradictory answer instructions."""
    frage = (
        "Kommt das Wort Demokratie in den Texten der Schuelerinnen und "
        "Schueler ueberhaupt vor, und wenn ja, wie viele Belege finde ich "
        "dafuer in den menschlichen Fassungen des Korpus, die ich mir "
        "spaeter selbst ansehen moechte?"
    )
    assert len(frage) == 219
    assert response_contract_for_prompt(frage) is None


def test_long_presence_question_keeps_frequency_list_in_the_tool_set():
    """Der Vertrag traegt den Werkzeugriegel mit.

    ``select_tools_for_prompt`` strich ``frequency_list`` genau dann, wenn
    ``response_contract_for_prompt`` einen Kurzantwort-Vertrag lieferte.
    Faellt der Vertrag fuer die lange Frage weg, muss das Werkzeug wieder
    erreichbar sein, sonst haette die Massnahme die Anweisung geheilt und
    den Werkzeugraum weiter beschnitten.
    """
    frage = (
        "Kommt das Wort Demokratie in den Texten der Schuelerinnen und "
        "Schueler ueberhaupt vor, und wenn ja, wie viele Belege finde ich "
        "dafuer in den menschlichen Fassungen des Korpus, die ich mir "
        "spaeter selbst ansehen moechte?"
    )
    tools = [
        {"function": {"name": name}}
        for name in ("run_cqlf_query", "kwic_context", "frequency_list")
    ]
    ausgewaehlt = {
        tool["function"]["name"]
        for tool in select_tools_for_prompt(frage, tools)
    }
    assert "frequency_list" in ausgewaehlt

    kurz = "Kommt das Wort Demokratie im Korpus vor?"
    ausgewaehlt_kurz = {
        tool["function"]["name"]
        for tool in select_tools_for_prompt(kurz, tools)
    }
    assert "frequency_list" not in ausgewaehlt_kurz


# --------------------------------------------------------------------------- #
# Der Messarm des 2026-09-20: die Verkleinerung ist abschaltbar. Mit Vorgabe
# AN verengt select_tools_for_prompt fuer eine klare Frageform; mit
# CANDYCONC_WERKZEUGRAUM_VERKLEINERN=0 steht die volle sichtbare Liste.
# Gemessen, nicht repariert — ob die Verkleinerung hilft, entscheidet der
# gepaarte verblindete Vergleich.
# --------------------------------------------------------------------------- #

import pytest


def test_mit_flag_steht_die_volle_sichtbare_liste(monkeypatch):
    from candyconc.tooling.tool_selection import _visible_product_tools

    frage = "Kommt das Wort Demokratie im Korpus vor?"
    monkeypatch.setenv("CANDYCONC_WERKZEUGRAUM_VERKLEINERN", "0")
    ausgewaehlt = _names(frage)
    sichtbar = {t["function"]["name"] for t in _visible_product_tools(REAL_TOOLS)}
    assert set(ausgewaehlt) == sichtbar, (
        sichtbar - set(ausgewaehlt),
        "Die Stichwort-Verengung griff noch, obwohl sie abgeschaltet war.",
    )


def test_ohne_flag_wird_weiter_verengt(monkeypatch):
    frage = "Kommt das Wort Demokratie im Korpus vor?"
    monkeypatch.setenv("CANDYCONC_WERKZEUGRAUM_VERKLEINERN", "1")
    ausgewaehlt = _names(frage)
    verfuegbar = {t["function"]["name"] for t in REAL_TOOLS}
    assert len(ausgewaehlt) < len(verfuegbar), (
        "Die Kontrolle soll verengen, sonst prueft der Flag-Test nichts."
    )


def test_vorgabe_ist_verkleinern(monkeypatch):
    monkeypatch.delenv("CANDYCONC_WERKZEUGRAUM_VERKLEINERN", raising=False)
    frage = "Kommt das Wort Demokratie im Korpus vor?"
    verfuegbar = {t["function"]["name"] for t in REAL_TOOLS}
    assert len(_names(frage)) < len(verfuegbar)
