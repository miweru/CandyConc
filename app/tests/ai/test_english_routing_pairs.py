# -*- coding: utf-8 -*-
"""Equivalent English and German questions follow the same routing chain.

Compare keyword tools, recipe selection, classifier fallback, recipe tool
expansion and analysis contracts. Classifier responses are simulated.
The paired questions cover simple requests and each recipe. German
inflection gaps and accidental substring triggers are outside these pairs."""

from __future__ import annotations

import asyncio

import pytest

from candyconc import question_kind as qk
from candyconc.capabilities.product import visible_product_copilot_tools
from candyconc.candyconc_copilot import question_form as qf
from candyconc.candyconc_copilot import recipe_runtime as rr
from candyconc.candyconc_copilot.grounding_contracts import (
    fallback_analysis_contract,
    heuristic_analysis_contract,
    select_recipe,
)
from candyconc.candyconc_copilot.recipes import RECIPES, RECIPES_BY_ID
from candyconc.question_language import render_english_cues
from candyconc.tooling.tool_selection import (
    response_contract_for_prompt,
    select_tools_for_prompt,
)

PAIRS = (
    # The three English questions of the probe and their German versions.
    (
        "probe_usage_over_decades",
        "Wie verändert sich der Gebrauch von freedom über die Jahrzehnte in diesen Reden?",
        "How does the use of freedom change across the decades in these addresses?",
    ),
    (
        "probe_typical_words",
        "Welche Wörter sind typisch für republikanische im Vergleich zu demokratischen Reden?",
        "Which words are typical of Republican compared with Democratic addresses?",
    ),
    (
        "probe_collocates",
        "Was sind die häufigsten Kollokate von economy, und was sagen sie darüber, "
        "wie Präsidenten darüber sprechen?",
        "What are the most frequent collocates of economy, and what do they suggest "
        "about how presidents talk about it?",
    ),
    # Question set einfach_2026-09-02.
    ("simple_frequency", "Wie oft kommt 'Nachhaltigkeit' vor?", "How often does 'sustainability' occur?"),
    ("simple_existence", "Gibt es das Wort Klimawandel im Korpus?", "Is the word climate change in the corpus?"),
    ("simple_documents", "Wie viele Dokumente hat das Korpus?", "How many documents does the corpus have?"),
    ("simple_kwic", "Zeig mir zehn Belege fuer 'allerdings'.", "Show me ten instances of 'however'."),
    ("simple_metadata", "Welche Register gibt es im Korpus?", "Which registers are there in the corpus?"),
    # Evaluation questions, the research corpus name replaced by "this collection".
    (
        "eval_group_keywords",
        "Was ist am Wortschatz der AfD-Fraktion charakteristisch, wenn man sie mit der "
        "Linksfraktion vergleicht? Ich schreibe ein Kapitel ueber Oppositionsrhetorik und "
        "brauche belastbare Schluesselwoerter fuer beide Seiten.",
        "What is characteristic of the vocabulary of the AfD parliamentary group when you "
        "compare it with the Left group? I am writing a chapter on opposition rhetoric and "
        "need reliable keywords for both sides.",
    ),
    (
        "eval_spelling_switch",
        "Wann genau ist der Bundestag von 'daß' auf 'dass' umgestiegen, und hat sich das "
        "über Jahre hingezogen oder gab es einen Bruch? Mich interessiert, ob man daran "
        "Sprachwandel im Parlament ablesen kann.",
        "When exactly did the Bundestag switch from 'daß' to 'dass', and did this drag on "
        "over years or was there a break? I am interested in whether one can read language "
        "change in parliament from it.",
    ),
    (
        "eval_denominator",
        "In unserer Arbeitsgruppe streiten wir darueber, wer die Partei des Wortes 'Volk' "
        "ist. Ich habe dazu schon zwei Antworten liegen: In der einen lag die CDU/CSU vorn, "
        "in der anderen die AfD. Beide Antworten nennen Zahlen. Klaeren Sie das "
        "abschliessend auf. Ich brauche (1) die Rohtreffer je Fraktion, (2) die Rate pro "
        "Million je Fraktion - und Sie sagen mir zu JEDER Rate, welcher Nenner "
        "dahintersteckt - und (3) die Aussage, wer unter welcher Rechnung vorn liegt.",
        "In our working group we argue about who is the party of the word 'Volk'. I already "
        "have two answers: in one the CDU/CSU was ahead, in the other the AfD. Both answers "
        "give numbers. Settle this conclusively. I need (1) the raw hits per group, (2) the "
        "rate per million per group - and you tell me for EACH rate which denominator is "
        "behind it - and (3) the statement of who is ahead under which calculation.",
    ),
    (
        "eval_collocation_measures",
        "Ich brauche für den Knoten \"Rolle\" das Kollokationsprofil bei Fenster 5. Gib mir "
        "die zehn stärksten Kollokate nach logDice, und daneben die zehn stärksten nach "
        "Log-Likelihood und nach MI. Die drei Listen werden auseinandergehen. Sag mir, "
        "welcher ich für eine Publikation über Stützverbgefüge trauen kann, und woran die "
        "beiden anderen scheitern.",
        "I need the collocation profile for the node \"Rolle\" with window 5. Give me the "
        "ten strongest collocates by logDice, and next to them the ten strongest by "
        "log-likelihood and by MI. The three lists will diverge. Tell me which one I can "
        "trust for a publication on support verb constructions, and where the other two fail.",
    ),
    (
        "eval_named_construction",
        "Es heißt, KI-Texte benutzen auffällig oft die Konstruktion nicht nur ... sondern "
        "auch. Stimmt das für diese Sammlung, und wie sicher ist der Befund?",
        "It is said that AI texts use the construction not only ... but also conspicuously "
        "often. Is that true for this collection, and how certain is the finding?",
    ),
    (
        "eval_hinge_construction",
        "Mir fällt in diesen Texten ein Scharnier auf, das aus drei Teilen besteht: erst ein "
        "Wort wie zudem oder darüber hinaus, dann ein Komma oder nicht, dann ein "
        "Substantiv, und irgendwo danach ein zweites Signalwort. Kann ich so etwas "
        "überhaupt suchen? Ich hätte gern gewusst, ob das in KI-Texten häufiger vorkommt "
        "als in den menschlichen, und zwar mit Beispielen, die ich meiner Klasse zeigen kann.",
        "In these texts I notice a hinge that consists of three parts: first a word like "
        "moreover or furthermore, then a comma or not, then a noun, and somewhere after "
        "that a second signal word. Can I search for something like that at all? I would "
        "like to know whether this occurs more often in AI texts than in the human ones, "
        "with examples I can show my class.",
    ),
    (
        "eval_marker_list",
        "Es kursieren überall Listen angeblicher KI-Marker: Herausforderung, Aspekt, "
        "entscheidend, darüber hinaus, zudem, essentiell, maßgeblich. Nimm diese Liste und "
        "prüf sie an dieser Sammlung durch. Welche halten, welche nicht, und welche gehen "
        "sogar in die andere Richtung? Und sag mir bei denen, die halten, ob sie in allen "
        "Modellen und Registern halten oder nur in einigen.",
        "Lists of alleged AI markers circulate everywhere: challenge, aspect, crucial, "
        "furthermore, moreover, essential, decisive. Take this list and check it against "
        "this collection. Which ones hold, which do not, and which even go in the opposite "
        "direction? And for those that hold, tell me whether they hold in all models and "
        "registers or only in some.",
    ),
    # One pair per recipe, written for this test.
    (
        "recipe_trend",
        "Wie entwickelt sich die Häufigkeit von 'freedom' über die Zeit?",
        "How does the frequency of 'freedom' develop over time?",
    ),
    (
        "recipe_word_sketch",
        "Erstelle ein Word Sketch für 'house': welche grammatischen Relationen prägen das Wort?",
        "Create a word sketch for 'house': which grammatical relations shape the word?",
    ),
    (
        "recipe_dispersion",
        "Wie ist das Wort 'war' über die Dokumente verteilt? Berechne die Dispersion.",
        "How is the word 'war' distributed across the documents? Compute the dispersion.",
    ),
    (
        "recipe_exploration",
        "Was fällt in diesem Korpus thematisch auf? Gib mir einen Überblick.",
        "What stands out thematically in this corpus? Give me an overview.",
    ),
    (
        "recipe_construction_search",
        "Wo steht 'nicht nur' gefolgt von 'sondern auch' mit höchstens acht Token Abstand? "
        "Zeig mir fünf Beispiele.",
        "Where is 'not only' followed by 'but also' with at most eight tokens in between? "
        "Show me five examples.",
    ),
    ("recipe_usage", "Wie wird 'home' in diesen Texten verwendet?", "How is 'home' used in these texts?"),
    (
        "recipe_keyness",
        "Mach mir eine Keyness-Analyse: welche Schlüsselwörter unterscheiden das Subkorpus "
        "'news' vom Subkorpus 'blog'?",
        "Run a keyness analysis for me: which keywords distinguish the subcorpus 'news' "
        "from the subcorpus 'blog'?",
    ),
    (
        "recipe_collocates_with_examples",
        "Welche typischen Begleitwörter hat 'Krise', und zeig mir passende Beispiele aus "
        "dem Korpus.",
        "Which typical accompanying words does 'crisis' have, and show me matching "
        "examples from the corpus.",
    ),
    (
        "recipe_metadata",
        "Welche Metadatenfelder gibt es im Korpus und welche Werte haben sie?",
        "Which metadata fields are there in the corpus and which values do they have?",
    ),
    (
        "recipe_sample",
        "Ziehe eine Zufallsstichprobe von 20 Treffern für 'Freiheit' mit Seed 7.",
        "Draw a random sample of 20 hits for 'freedom' with seed 7.",
    ),
)

_VISIBLE = sorted(visible_product_copilot_tools())
_ALL_TOOLS = [{"type": "function", "function": {"name": name}} for name in (*_VISIBLE, "deutung_abgeben")]
_UNIVERSE = list(_VISIBLE)
_CLASSIFIER_ANSWERS = (None, "frei", *(recipe.id for recipe in RECIPES))


def _names(tools) -> list[str]:
    return [str(tool["function"]["name"]) for tool in tools]


def _contract(contract) -> dict | None:
    if contract is None:
        return None
    return {
        "mode": contract.mode,
        "track": contract.track,
        "family": contract.analysis_family,
        "deliverable": contract.deliverable_kind,
        "allowed_tools": list(contract.allowed_tools or []),
        "required_evidence": list(contract.required_evidence or []),
        "response_shape": contract.response_shape,
    }


def _fake_classifier(answer: str):
    async def call(messages, tools=None, **_kwargs):
        return {"choices": [{"message": {"content": answer}}]}

    return call


def _turn_tools(names: list[str], recipe_id: str) -> list[str]:
    """Names after the recipe tool expansion (``expand_tools_for_recipe``)."""
    recipe = RECIPES_BY_ID.get(recipe_id)
    if recipe is None:
        return names
    needed = (*recipe.kern_tools, *recipe.wegbereiter_tools)
    return names + [name for name in needed if name not in names and name in _UNIVERSE]


def _route(question: str) -> dict:
    tools = select_tools_for_prompt(question, list(_ALL_TOOLS))
    names = _names(tools)
    caps = {"available_tools": names, "read_only_tools": names, "routing_tool_universe": _UNIVERSE}
    decision = rr.stage1_recipe_decision(question, caps)
    routes = {}
    for answer in _CLASSIFIER_ANSWERS:
        call = None if answer is None else _fake_classifier(answer)
        result = asyncio.run(rr.route_turn_recipe(question, caps, call))
        recipe_id = str(result.get("recipe_id") or "")
        stage = str(result.get("stage") or "")
        turn = _turn_tools(names, recipe_id)
        routes[str(answer)] = {
            "recipe": recipe_id,
            "stage": stage,
            "tools": turn,
            "heuristic": _contract(heuristic_analysis_contract(
                question, available_tools=turn, read_only_tools=turn,
                rezept_id=recipe_id, rezept_stufe=stage,
            )),
            "fallback": _contract(fallback_analysis_contract(
                question, available_tools=turn, read_only_tools=turn,
            )),
        }
    return {
        "tools": names,
        "select_recipe": getattr(select_recipe(question, caps), "id", None),
        "stage1": {
            "recipe": getattr(decision.get("recipe"), "id", None),
            "confident": decision.get("confident"),
            "signals": list(decision.get("signals") or ()),
            "specific": decision.get("specific"),
            "conflict": decision.get("conflict"),
        },
        "response_contract": (response_contract_for_prompt(question) or {}).get("response_style"),
        "lookup": qk.frage_ist_blosses_nachschlagen(question),
        "interpretation_cue": qk.enthaelt_deutungscue(question),
        "construction_search": qf.ist_konstruktions_suchauftrag(question),
        "candidate_list_check": qf.ist_kandidatenlisten_pruefung(question),
        "routes": routes,
    }


@pytest.mark.parametrize("german, english", [pair[1:] for pair in PAIRS], ids=[pair[0] for pair in PAIRS])
def test_english_question_takes_the_german_route(german, english):
    assert _route(english) == _route(german)


@pytest.mark.parametrize("german", [pair[1] for pair in PAIRS], ids=[pair[0] for pair in PAIRS])
def test_german_question_is_read_as_it_stands(german):
    assert render_english_cues(german) is None


def test_collocate_question_keeps_the_kwic_tool_without_the_classifier():
    """The motivating case of the probe, stated as behaviour."""

    english = PAIRS[2][2]

    async def classifier_must_not_run(*_args, **_kwargs):
        raise AssertionError("stage 1 decides this question, no classifier call")

    tools = select_tools_for_prompt(english, list(_ALL_TOOLS))
    names = _names(tools)
    caps = {"available_tools": names, "read_only_tools": names, "routing_tool_universe": _UNIVERSE}
    routing = asyncio.run(rr.route_turn_recipe(english, caps, classifier_must_not_run))
    assert routing["recipe_id"] == "assoziation"
    assert routing["stage"] == rr.ROUTING_STAGE_TRIGGER
    turn = _turn_tools(names, routing["recipe_id"])
    contract = heuristic_analysis_contract(
        english, available_tools=turn, read_only_tools=turn,
        rezept_id=routing["recipe_id"], rezept_stufe=routing["stage"],
    )
    assert contract.analysis_family == "collocation"
    assert contract.allowed_tools == ["collocate_stats", "query_count", "run_cqlf_query"]


def test_specific_stage1_pick_survives_a_failed_classifier():
    """Without a usable classifier answer the English question keeps its recipe.

    Before, English questions had no stage-1 pick and fell into the free
    mode (``recipe_runtime.route_turn_recipe``), German ones kept theirs.
    """

    english = PAIRS[1][2]
    routing = asyncio.run(rr.route_turn_recipe(english, None, _fake_classifier("")))
    assert routing["recipe_id"] == "kontrast"
    assert routing["stage"] == rr.ROUTING_STAGE_TRIGGER
