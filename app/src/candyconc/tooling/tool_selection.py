from __future__ import annotations

from typing import Any, Iterable

from candyconc.capabilities.product import (
    COPILOT_TURN_CONTROL_TOOLS,
    visible_product_copilot_tools,
)
from candyconc.question_kind import frage_ist_blosses_nachschlagen
from candyconc.question_language import render_english_cues


_TOOL_ORDER = (
    "run_cqlf_query",
    "query_count",
    "collocate_stats",
    "collocation_network",
    "compare_collocates",
    "contrast_collocates",
    "word_sketch",
    "frequency_list",
    "ngram_frequency",
    "ngram_contrast",
    "dispersion_offsets",
    "trend_analysis",
    "keyness",
    "lexical_diversity",
    "similar_words",
    "semantic_search",
    "parallel_groups",
    "parallel_kwic",
    "document_text",
    "kwic_context",
    "semantic_cluster",
    "semantic_cluster_words",
    "refine_cluster_label",
    "semantic_recluster",
    "document_search",
    "metadata_values",
    "create_docset",
    "list_docsets",
    "resolve_subcorpus",
    "documentation_search",
    "cluster_save",
    "cluster_export_md",
)


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("function", {}).get("name", ""))


def _ordered_subset(
    tools: Iterable[dict[str, Any]],
    names: set[str],
) -> list[dict[str, Any]]:
    by_name = {_tool_name(tool): tool for tool in tools}
    selected = [by_name[name] for name in _TOOL_ORDER if name in names and name in by_name]
    return selected


def _visible_product_tool_names() -> set[str]:
    return set(visible_product_copilot_tools())


# The model's exit is turn control like the control frames, not a product
# tool: no capability binds it, and none should. Without this exemption the
# static core (GEBUENDELTE_PLANUNG) instructs the model to call a tool the API
# never receives, and the turn ends at the round limit without a submission.
# The list lives in the capability contract (capabilities.product) so that
# the UI, the MCP status and the tool selection know the same set.
_TURN_STEUERUNG_TOOLS = COPILOT_TURN_CONTROL_TOOLS


def ist_turn_steuerung(name: str) -> bool:
    """The submit tool and its siblings: turn control, not product surface.

    Use this at EVERY check that decides whether the copilot may call a
    tool. The MCP route has the same exemption as the three orchestrator
    guards. Without it a 403 rejects every submission.
    """
    return name in _TURN_STEUERUNG_TOOLS


def _visible_product_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = _visible_product_tool_names() | _TURN_STEUERUNG_TOOLS
    return [tool for tool in tools if _tool_name(tool) in allowed]


def product_tool_bindings_by_name(*, visible_only: bool = True) -> dict[str, tuple[Any, ...]]:
    from candyconc.capabilities.product import product_copilot_tool_operation_bindings

    bindings: dict[str, list[Any]] = {}
    for binding in product_copilot_tool_operation_bindings(visible_only=visible_only):
        bindings.setdefault(binding.tool_name, []).append(binding)
    return {name: tuple(items) for name, items in bindings.items()}


def bindings_allow_default_release_dispatch(bindings: Iterable[Any]) -> bool:
    items = tuple(bindings)
    if not items:
        return False
    return all(
        "write" not in getattr(binding, "effects", ())
        and "destructive" not in getattr(binding, "effects", ())
        for binding in items
    )


def product_binding_metadata(bindings: Iterable[Any]) -> dict[str, Any]:
    items = tuple(bindings)
    return {
        "product_operation_ids": sorted({binding.operation_id for binding in items}),
        "product_capability_ids": sorted({binding.capability_id for binding in items}),
        "product_effects": sorted({effect for binding in items for effect in binding.effects}),
        "requires_corpus_features": sorted(
            {
                feature
                for binding in items
                for feature in binding.route.requires_corpus_features
            }
        ),
    }


def is_tool_dispatchable_for_principal(
    name: str,
    *,
    runtime_info: dict[str, dict[str, Any]],
    allowed_tools: Iterable[str] | None,
    release_mode: bool,
    bindings_by_tool: dict[str, tuple[Any, ...]] | None = None,
) -> bool:
    # Turn-Steuerung (der Ausgang des MODELLS) hat keine Produkt-Bindung
    # und braucht keine: sie ist Protokoll, kein Produktvorgang. Die
    # Dispatch-Wache prueft NUR runtime_info und allowed_tools dafuer.
    if name in _TURN_STEUERUNG_TOOLS:
        info = runtime_info.get(name)
        if info is None:
            return False
        if allowed_tools is not None:
            return name in {str(item) for item in allowed_tools}
        return True
    bindings = (bindings_by_tool or product_tool_bindings_by_name()).get(name, ())
    if not bindings:
        return False
    info = runtime_info.get(name)
    if info is None:
        return False
    if allowed_tools is not None:
        return name in {str(item) for item in allowed_tools}
    if release_mode:
        return bool(info.get("read_only", False)) and bindings_allow_default_release_dispatch(bindings)
    return True


def filter_dispatchable_tools_for_principal(
    tools: Iterable[dict[str, Any]],
    *,
    runtime_info: dict[str, dict[str, Any]],
    allowed_tools: Iterable[str] | None,
    release_mode: bool,
    bindings_by_tool: dict[str, tuple[Any, ...]] | None = None,
) -> list[dict[str, Any]]:
    bindings = bindings_by_tool or product_tool_bindings_by_name()
    return [
        tool
        for tool in tools
        if is_tool_dispatchable_for_principal(
            _tool_name(tool),
            runtime_info=runtime_info,
            allowed_tools=allowed_tools,
            release_mode=release_mode,
            bindings_by_tool=bindings,
        )
    ]


def _prompt_flags(question: str) -> dict[str, bool]:
    # An English question is read in the German keyword vocabulary
    # (candyconc.question_language). Every other question keeps the plain
    # lower-cased text, byte for byte as before.
    text = render_english_cues(question) or question.lower()
    return {
        "collocation": any(token in text for token in ("kollok", "collocat", "neben", "zusammen mit")),
        "network": any(
            token in text
            for token in (
                "netzwerk",
                "network",
                "graph",
                "wortnetz",
                "ego-netz",
                "egonetz",
                "kollokationsnetz",
            )
        ),
        "compare": any(
            token in text
            for token in (
                "vergleich",
                "compare",
                "unterschied",
                "unterscheid",
                "differenz",
                "kontrast",
                "vs",
                "versus",
            )
        ),
        "distinctive": any(
            token in text
            for token in (
                "häufiger", "häufiger", "seltener", "auffällig", "auffällig",
                "typisch", "charakteristisch", "überrepräsent", "überrepräsent",
                "unterrepräsent", "unterrepräsent", "over-represent", "overrepresent",
                "distinktiv", "distinctive",
            )
        ),
        "word_sketch": "word sketch" in text or "wortprofil" in text,
        "frequency": any(token in text for token in ("frequenz", "häufig", "häufig", "wie oft")),
        "ngram": any(
            token in text
            for token in ("n-gramm", "n-gramme", "ngram", "ngramme", "phrase", "phrasen", "bigramm", "trigramm", "wortfolge", "mehrwort")
        ),
        "keyness": any(token in text for token in ("keyness", "keyword", "schlüsselwort", "schlusselwort")),
        "diversity": any(
            token in text
            for token in (
                "lexikalische vielfalt",
                "lexical diversity",
                "wortvielfalt",
                "vielfalt",
                "ttr",
                "sttr",
                "type-token",
                "type token",
                "guiraud",
                "mattr",
            )
        ),
        "dispersion": any(token in text for token in ("dispersion", "verteilung")),
        "trend": any(
            token in text
            for token in (
                "trend",
                "verlauf",
                "zeitverlauf",
                "diachron",
                "über die zeit",
                "im zeitvergleich",
                "pro jahr",
                "je jahr",
                "nach jahr",
                "pro monat",
                "je monat",
                "monatlich",
                "jährlich",
                "over time",
            )
        ),
        "thesaurus": any(
            token in text
            for token in (
                "ähnliche wörter",
                "ähnliche wörter",
                "similar words",
                "thesaurus",
                "wortfeld",
                "bedeutungsähnlich",
                "synonyme",
                "nachbarwörter",
            )
        ),
        "semantic": any(token in text for token in ("cluster", "thema", "topic", "semantic", "semant")),
        "docs": any(token in text for token in ("cqlf", "syntax", "dokumentation", "erkläre", "erkläre", "manual")),
        "metadata": any(
            token in text
            for token in (
                "metadat",
                "quelle",
                "source",
                "register",
                "genre",
                "datum",
                "date",
                "modell",
                "model",
                "text_type",
                "text type",
                "texttyp",
                "subkorpus",
                "docset",
            )
        ),
        "exploratory": any(
            token in text
            for token in (
                "welche themen",
                "welche thematischen",
                "zentrale themen",
                "thematisch zentral",
                "besonders zentral",
                "interessante dinge",
                "interessante sachen",
                "über dieses korpus",
                "über dieses korpus",
                "überblick",
                "überblick",
                "insgesamt auf",
                "belegte dinge",
                "belegte sachen",
                "welche fragen",
                "anschlussfragen",
                "anschlussfrage",
                "forschungsfragen",
                "ergeben sich aus diesem korpus",
            )
        ),
        "method_help": any(
            token in text
            for token in (
                "erste analyseschritte",
                "erste analyse schritte",
                "erste schritte",
                "welche ersten",
                "würdest du empfehlen",
                "würdest du empfehlen",
                "wie würdest du anfangen",
                "wie würdest du anfangen",
                "neu bekaemst",
                "neu bekämst",
                "wie anfangen",
                "erste drei schritte",
                "erste drei analyseschritte",
                "methodisch sinnvoll anfangen",
            )
        ),
        "comparative_open": any(
            token in text
            for token in (
                "unterschiede zwischen",
                "unterscheid",
                "differenz",
                "im vergleich",
                "kontrast",
                "arbeite drei unterschiede",
                "human- und ai",
                "human und ai",
                "ai-teil",
                "human-teil",
            )
        ),
        "presence": (("kommt" in text and "vor" in text) or any(token in text for token in ("treffer", "beleg", "kwic", "kontext"))),
        "parallel": any(
            token in text
            for token in (
                "parallel",
                "aligned",
                "alignment",
                "ausgerichtet",
                "gegenüberstell",
                "gegenüberstell",
                "mensch vs",
                "mensch-vs",
                "human vs",
                "human-vs",
                "mensch gegen",
                "varianten nebeneinander",
                "nebeneinander",
            )
        ),
        "fulltext": any(
            token in text
            for token in (
                "volltext",
                "ganzer text",
                "ganze text",
                "gesamten text",
                "kompletten text",
                "vollständigen text",
                "vollständigen text",
                "lies das dokument",
                "lies den text",
                "zeig den text",
                "zeige den text",
                "im quelltext",
                "quelltext",
            )
        ),
        "export": any(token in text for token in ("export", "markdown")),
        "save": any(token in text for token in ("speicher", "save")),
    }


def response_contract_for_prompt(
    question: str,
    *,
    ui_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    if not question:
        return None
    flags = _prompt_flags(question)
    # Usage questions require analysis rather than a presence lookup. Share
    # the raw-question decision in candyconc.question_kind with the contract
    # layer so cues and question length produce the same answer requirements.
    simple_presence = flags["presence"] and frage_ist_blosses_nachschlagen(
        question
    ) and not any(
        flags[key]
        for key in ("collocation", "network", "compare", "word_sketch", "frequency", "keyness", "dispersion", "semantic", "docs", "export", "save")
    )
    simple_presence = simple_presence and not flags["exploratory"] and not flags["method_help"] and not flags["comparative_open"] and not flags["metadata"]
    if not simple_presence:
        return None
    active_tab = str((ui_context or {}).get("view", {}).get("activeTab", "") or (ui_context or {}).get("active_tab", "")).lower()
    contract = (
        "Beantworte die Frage knapp in 1-3 Saetzen. "
        "Beginne mit einem klaren Ja/Nein oder einer klaren Treffer-Aussage. "
        "Nenne hoechstens einen kompakten Evidenzpunkt aus dem Tool-Output und füge keine Tabelle oder lange Interpretation an, solange der Nutzer nicht danach fragt."
    )
    if active_tab == "kwic":
        contract += " Wenn KWIC-Kontext sichtbar ist, genügt ein kurzer Verweis auf den Trefferkontext."
    return {"response_style": "brief_presence_answer", "response_contract": contract}


def select_tools_for_prompt(
    question: str,
    tools: list[dict[str, Any]],
    *,
    ui_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a smaller, task-aligned tool subset for obvious prompt shapes.

    The function is intentionally conservative:
    - if the question shape is unclear, return the full tool set
    - only narrow for obvious corpus-analysis intents
    """

    visible_tools = _visible_product_tools(tools)

    if not question:
        return visible_tools

    # The narrowing from 23 keyword lists is ON by default. The flag
    # switches it off so that the full visible list stays, which allows a
    # paired blind comparison of whether the narrowing helps or harms the
    # answer.
    import os

    if os.environ.get("CANDYCONC_WERKZEUGRAUM_VERKLEINERN", "1").strip().lower() in (
        "0", "false", "nein", "aus",
    ):
        return visible_tools

    flags = _prompt_flags(question)
    names: set[str] = set()

    # The AnalysisContract is the product's authoritative prompt-level tool
    # constraint. Keep selector heuristics for compactness, but never narrow
    # away a tool the grounding layer has declared necessary.
    from candyconc.candyconc_copilot.analysis_grounding import (
        fallback_analysis_contract,
        heuristic_analysis_contract,
    )

    visible_names = {_tool_name(tool) for tool in visible_tools}
    grounding_contract = heuristic_analysis_contract(
        question,
        available_tools=visible_names,
        read_only_tools=visible_names,
    ) or fallback_analysis_contract(
        question,
        available_tools=visible_names,
        read_only_tools=visible_names,
    )
    if grounding_contract and grounding_contract.mode == "tool_analysis":
        names.update(grounding_contract.allowed_tools)

    if flags["collocation"]:
        names.update({"collocate_stats", "collocation_network", "run_cqlf_query", "frequency_list"})
    if flags["network"]:
        # A "network"/"graph"/"Wortnetz" question must keep the graph tool even
        # when the prompt does not contain a "kollok"/"collocat" trigger.
        names.update({"collocation_network", "collocate_stats", "run_cqlf_query"})
    if flags["collocation"] and flags["compare"]:
        names.update({"compare_collocates", "contrast_collocates", "collocate_stats"})
    if flags["word_sketch"]:
        names.update({"word_sketch", "collocate_stats", "run_cqlf_query"})
    if flags["frequency"]:
        # "Wie oft kommt X vor?" is a COUNT of one term -> query_count (exact
        # total). frequency_list is the whole-corpus ranking; run_cqlf_query gives
        # KWIC rows (capped, NOT a count). Keep all three reachable but lead with
        # query_count for the count-of-a-term shape.
        names.update({"query_count", "frequency_list", "run_cqlf_query"})
    if flags["ngram"]:
        # Phrase / n-gram questions route to the n-gram tools (and keep the raw
        # KWIC path as a fallback for verbatim phrase lookups).
        names.update({"ngram_frequency", "run_cqlf_query"})
        if flags["compare"]:
            names.add("ngram_contrast")
    if flags["keyness"]:
        names.update({"keyness", "frequency_list"})
    if flags["compare"] and (flags["frequency"] or flags["distinctive"]):
        # Plain-language frequency comparisons need keyness even when the user
        # does not name the measure. Expose the tool for these questions.
        names.update({"keyness", "frequency_list", "metadata_values"})
    if flags["diversity"]:
        # Lexical-diversity questions must keep the diversity tool even when a
        # sibling trigger word (vergleiche / häufig / register) co-fires and
        # would otherwise narrow it out. Unconditional on the flag (keyness
        # pattern) so it persists in the human-vs-AI / per-register use cases.
        names.update({"lexical_diversity", "frequency_list"})
    if flags["thesaurus"]:
        # Distributional-thesaurus questions ("ähnliche Wörter" / "Synonyme" /
        # "Wortfeld") must keep the similar_words tool even when a sibling
        # trigger (semantic "cluster"/"thema", frequency "häufig", compare
        # "vergleiche") co-fires and would otherwise narrow it out via
        # _ordered_subset. Unconditional on the flag (keyness / diversity
        # pattern) so the tool stays reachable.
        names.update({"similar_words", "frequency_list"})
    if flags["dispersion"]:
        names.update({"dispersion_offsets", "run_cqlf_query"})
    if flags["trend"]:
        # Diachronic trend questions ("Trend"/"Verlauf"/"pro Jahr") need the
        # trend tool plus metadata_values (to discover the date field) and
        # query_count as the whole-corpus baseline. Unconditional on the flag
        # (keyness / diversity pattern) so a co-firing sibling trigger never
        # narrows it out.
        names.update({"trend_analysis", "metadata_values", "query_count"})
    if flags["exploratory"]:
        names.update(
            {
                "frequency_list",
                "metadata_values",
                "similar_words",
                "semantic_cluster_words",
                "document_search",
            }
        )
    if flags["method_help"]:
        names.update(
            {
                "frequency_list",
                "metadata_values",
                "similar_words",
                "document_search",
                "documentation_search",
            }
        )
    if flags["comparative_open"]:
        names.update(
            {
                "compare_collocates",
                "contrast_collocates",
                "keyness",
                "frequency_list",
                "metadata_values",
                "create_docset",
                "list_docsets",
            }
        )
    if flags["metadata"]:
        names.update({"metadata_values", "document_search", "create_docset", "list_docsets", "resolve_subcorpus"})
        if flags["compare"] or flags["keyness"]:
            names.add("keyness")
        # A subcorpus/docset metadata question that also asks to contrast needs
        # the pairing-free contrast tool plus the docset builders.
        if flags["compare"]:
            names.add("contrast_collocates")
    if flags["semantic"]:
        names.update(
            {
                "similar_words",
                "semantic_cluster",
                "semantic_cluster_words",
                "semantic_recluster",
                "refine_cluster_label",
                "document_search",
            }
        )
    if flags["parallel"]:
        # The flagship Human-vs-AI aligned view: list the parallel groups and
        # read aligned KWIC across the variants. Keep run_cqlf_query so the LLM can
        # locate the hit position to align on first.
        names.update({"parallel_groups", "parallel_kwic", "run_cqlf_query"})
    if flags["fulltext"]:
        # "Read the full text / source text" -> document_text (+ a wide window
        # around a specific hit via kwic_context). document_search locates docs.
        names.update({"document_text", "kwic_context", "document_search"})
    if flags["docs"]:
        names.add("documentation_search")
    if flags["presence"] and not flags["exploratory"] and not flags["method_help"] and not flags["comparative_open"]:
        names.add("run_cqlf_query")
        # A presence/KWIC question benefits from reading a wide window around a
        # hit; keep kwic_context reachable for grounding.
        names.add("kwic_context")
        if not response_contract_for_prompt(question, ui_context=ui_context):
            names.add("frequency_list")
    if flags["export"]:
        names.add("cluster_export_md")
    if flags["save"]:
        names.add("cluster_save")

    active_tab = str((ui_context or {}).get("view", {}).get("activeTab", "") or (ui_context or {}).get("active_tab", "")).lower()
    if active_tab == "kwic":
        names.add("run_cqlf_query")

    abgabe = [t for t in visible_tools if _tool_name(t) == "deutung_abgeben"]
    if not names:
        return visible_tools

    selected = _ordered_subset(visible_tools, names) or visible_tools
    selected = [t for t in selected if _tool_name(t) != "deutung_abgeben"] + abgabe
    return selected
