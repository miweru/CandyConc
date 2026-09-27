"""Derive the analysis contract from the recipe already selected by the router.

The active recipe is known before preflight, so another model call would
repeat a completed classification."""

from __future__ import annotations

import pytest

from candyconc.candyconc_copilot.grounding_contracts import (
    RECIPES,
    heuristic_analysis_contract,
)

#: NICHT aus ``get_tools()``: die conftest dieses Verzeichnisses stubbt das
#: Registry auf neun Werkzeuge, und ``word_sketch``, ``query_count``,
#: ``metadata_values`` und ``trend_analysis`` fehlen darin. Ein Test, der
#: davon abhinge, wuerde nicht das Verhalten messen, sondern den Stub.
#: Der ehrliche Werkzeugraum dieses Merkmals ist die Vereinigung der
#: Kernwerkzeuge aller Rezepte, denn genau daraus baut der Rueckfall.
ALLE = sorted({name for r in RECIPES for name in r.kern_tools})

#: Die vier Fragen, die im Livelauf den Klassifikator gezogen haben, mit
#: dem Rezept, das der Router fuer sie gewaehlt hatte.
#: ``exploration_meta`` und ``gebrauch_kwic`` fehlen hier: ihre Familien
#: ``open_research`` und ``kwic_context`` sind vom Rueckfall ausgenommen,
#: mit Begruendung bei ``_FAMILIEN_OHNE_RUECKFALL``.
GEMESSENE_KLASSIFIKATORFRAGEN = [
    ("Erstelle ein grammatisches Profil des Verbs 'gehen'.", "profil",
     "word_sketch_profile"),
    ("Unterscheiden sich train- und test-Teil dieses Korpus sprachlich? "
     "Untersuche ausdrücklich die Datenaufteilung selbst.", "kontrast",
     "contrast_keyness"),
    ("Vergleiche die Sprache von Menschen und KI in diesem Korpus.",
     "kontrast", "contrast_keyness"),
]


def _kontrakt(frage: str, rezept_id: str = ""):
    return heuristic_analysis_contract(
        frage, available_tools=ALLE, read_only_tools=ALLE,
        rezept_id=rezept_id,
    )


@pytest.mark.parametrize(
    "frage,rezept_id,familie", GEMESSENE_KLASSIFIKATORFRAGEN
)
def test_das_rezept_ersetzt_den_klassifikatoraufruf(frage, rezept_id, familie):
    # Positive Klasse zuerst: ohne Rezept schweigen die Cues wirklich.
    # Ohne diese Zeile waere der Test auch dann gruen, wenn ein Cue-Zweig
    # die Frage laengst faengt und der Rueckfall nie liefe.
    assert _kontrakt(frage) is None, (
        "Diese Frage wird inzwischen von einem Cue-Zweig gefangen. Dann "
        "misst der Test nicht mehr, was er zu messen behauptet."
    )
    kontrakt = _kontrakt(frage, rezept_id)
    assert kontrakt is not None
    assert kontrakt.analysis_family == familie
    assert kontrakt.allowed_tools, "ohne Werkzeuge traegt der Kontrakt nichts"
    assert kontrakt.required_evidence, "ohne Pflichtevidenz keine Bindung"


def test_ein_cue_schlaegt_die_routerentscheidung():
    """Eine Formulierung, die eine Familie NENNT, behaelt Vorrang.

    Sonst koennte eine Fehlleitung des Routers eine ausdrueckliche
    Nutzerabsicht ueberschreiben, und zwar unsichtbar.
    """
    frage = "Wie häufig ist 'Deutschland' im Korpus, absolut und pro Million?"
    ohne = _kontrakt(frage)
    assert ohne is not None and ohne.analysis_family == "term_frequency"
    # Der Router liegt hier falsch. Der Cue gewinnt trotzdem.
    mit = _kontrakt(frage, "kontrast")
    assert mit is not None
    assert mit.analysis_family == "term_frequency"


def test_ein_unbekanntes_rezept_aendert_nichts():
    frage = "Erstelle ein grammatisches Profil des Verbs 'gehen'."
    assert _kontrakt(frage, "gibt-es-nicht") is None
    assert _kontrakt(frage, "") is None


def test_jedes_rezept_traegt_eine_familie_die_der_rueckfall_kennt():
    """Ein neues Rezept ohne Familieneintrag faellt sonst still zurueck.

    Die Zuordnung kommt aus dem ``family:``-Trigger des Rezepts, also aus
    derselben Quelle wie die Gegenrichtung ``_recipe_for_family``. Dieser
    Test haelt beide Richtungen zusammen.
    """
    from candyconc.candyconc_copilot.grounding_contracts import (
        _FAMILIEN_KONTRAKT,
        _FAMILIEN_OHNE_RUECKFALL,
    )

    ohne_familie = [r.id for r in RECIPES if not r.familien]
    assert not ohne_familie, ohne_familie
    unbekannt = [
        (r.id, r.familien[0])
        for r in RECIPES
        if r.familien[0] not in _FAMILIEN_KONTRAKT
        and r.familien[0] not in _FAMILIEN_OHNE_RUECKFALL
    ]
    assert not unbekannt, (
        f"Diese Rezepte haetten keinen Rueckfall und wuerden weiter einen "
        f"Modellaufruf kosten: {unbekannt}"
    )


def test_der_rueckfall_liefert_denselben_kontrakt_wie_der_cue_zweig():
    """Kein zweiter Wahrheitsstrang.

    Fuer eine Frage, die BEIDE Wege klaeren, muessen Familie, Track,
    Lieferart und Antwortform uebereinstimmen. Sonst haengt das Verhalten
    daran, welcher Weg zuerst greift, und das ist keine Zusicherung.
    """
    # The cue and recipe paths agree for the context question. Other
    # wordings can select term_profile through cues while the recipe lists
    # collocation first. Recipe fallback applies only when cues are silent,
    # so it does not override an existing cue decision.
    frage = "Welche Wörter bilden das unmittelbare Umfeld von 'Merkel'?"
    ueber_cue = _kontrakt(frage)
    ueber_rezept = _kontrakt("Sag etwas zu diesem Korpus.", "assoziation")
    assert ueber_cue is not None and ueber_rezept is not None
    assert ueber_cue.analysis_family == "collocation"
    assert ueber_cue.analysis_family == ueber_rezept.analysis_family
    assert ueber_cue.track == ueber_rezept.track
    assert ueber_cue.deliverable_kind == ueber_rezept.deliverable_kind
    assert ueber_cue.response_shape == ueber_rezept.response_shape


@pytest.mark.parametrize("connector", ["und", "oder", "and", "or", "pair"])
def test_register_axis_words_do_not_select_a_register(connector):
    from candyconc.candyconc_copilot.grounding_contracts import _requested_register_value

    question = f"Analysiere die Metadaten register {connector} source."
    assert _requested_register_value(question) == ""
    contract = _kontrakt(question)
    assert contract is not None
    assert contract.analysis_family == "metadata_capability"


@pytest.mark.parametrize("value", ["social", "'news'", '"pair"', "namens und"])
def test_requested_register_still_accepts_values(value):
    from candyconc.candyconc_copilot.grounding_contracts import _requested_register_value

    assert _requested_register_value(f"Suche im Register {value} nach Arbeit.") == (
        value.removeprefix("namens ").strip("'\"")
    )


def test_classifier_collocation_contract_allows_count_and_context_check():
    tools = ["collocate_stats", "query_count", "run_cqlf_query"]
    contract = heuristic_analysis_contract(
        "Sag etwas zu diesem Korpus.", available_tools=tools, read_only_tools=tools,
        rezept_id="assoziation", rezept_stufe="llm",
    )
    assert contract is not None
    assert contract.analysis_family == "collocation"
    assert contract.allowed_tools == tools
    assert contract.required_evidence == ["metric_rows", "total_hits"]


def test_collocation_support_tools_do_not_replace_the_core_tool():
    tools = ["query_count", "run_cqlf_query"]
    contract = heuristic_analysis_contract(
        "Sag etwas zu diesem Korpus.", available_tools=tools, read_only_tools=tools,
        rezept_id="assoziation", rezept_stufe="llm",
    )
    assert contract is None
