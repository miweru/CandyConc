"""Recipe runtime helpers for turn prompts and evidence-based answers.

The orchestrator supplies context, session structures and evidence explicitly.
Keep imports in the foundational prompt, recipe, contract and reference modules
so this module does not depend on orchestrator or grounding_verifier.

Helpers build corpus cards and session briefings, append variable turn context
after the stable prompt core, resolve references and route recipe selection.
Recipe routing combines trigger-based selection with a classifier when needed.
"""

from __future__ import annotations

import asyncio
import bisect
import inspect
import json
import logging
import re
import time
from functools import lru_cache
from typing import (
    AbstractSet,
    Any,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
)

from candyconc.i18n import lt

from . import prompts as _prompt_helpers
from candyconc.answer_language import answer_language, choose as _t, is_english, text_value
from .draft_sections import (
    SEKTIONSLABEL,
    SEKTIONS_UEBERSCHRIFT_MUSTER,
)
from .quote_rules import (
    auslassungssegmente as _auslassungssegmente,
    spanne_ist_fragenbezug as _spanne_ist_fragenbezug,
)
from .question_coverage import alle_luecken_saetze as _alle_luecken_saetze
from .analysis_token_report import saetze as _analysetoken_saetze
from .experiment_log import protokoll_anhaengen as _experimentprotokoll
from .measure_basis import saetze as _massgrundlagen_saetze
from .rate_name_binding import massnamen_ohne_rate_davor
from .row_spelling_note import alle_saetze as _schreibungs_saetze
from .trailing_notices import ohne_schlusshinweise as _ohne_schlusshinweise
from .table_promise_check import (
    ohne_leere_abschnitte as _ohne_leere_abschnitte,
    saetze as _tabellenzusage_saetze,
)
from .question_form import (
    ROUTING_STAGE_FRAGEFORM,
    ist_kandidatenlisten_pruefung,
    ist_konstruktions_suchauftrag,
    kandidatenliste_aus_frage,
    starker_treffer,
)
from .grounding_contracts import (
    _RECIPE_DEFAULT_TOOLS,
    _is_exploratory_prompt,
    _normalised_question_text,
    _recipe_for_family,
    _recipe_tools_available,
    get_recipe,
    heuristic_analysis_contract,
    render_briefing,
    select_recipe,
)
from .claim_rules._shared import _numeric_token_is_supported
from .grounding_refs import (
    MISSING_EVIDENCE_PLACEHOLDER,
    MISSING_EVIDENCE_PLACEHOLDER_EN,
    resolve_references,
)
from .candidate_list import (  # Zitat-Extraktion: EINE Quelle, siehe dort
    extract_primary_terms,
    ist_kandidatenliste,
    kandidatenliste,
    kandidatenlisten_note,
)
from .prompt_layout import build_static_core, build_turn_briefing
from .id_scrub import scrub_internal_ids as _scrub_internal_ids
from .recipes import (
    ANSWER_SWITCH_UNSET,
    FREE_MODE_MAX_TOOL_RUNDEN,
    RECIPES,
    RECIPES_BY_ID,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Metadaten-Achsen-Klassifikation (Haertung r4, Fix 1+2): eine Achse ist nur   #
# dann kontrastierbar, wenn sie MEHR als einen Wert traegt und keine           #
# Ein-Wert-pro-Dokument-Identitaet ist. Dokument-ID-Felder (doc_id, origin_id, #
# path, reference_hash) haben so viele Werte wie Dokumente und taugen nicht    #
# als Gruppierungsachse.                                                       #
# --------------------------------------------------------------------------- #
_DOC_ID_MIN_DOCS = 10
_DOC_ID_RATIO = 0.9

# H6 (B7): technische Partitionsfelder sind Datenaufteilung, keine
# linguistische Achse. Konservative Namens-Blockliste (casefold-Vergleich);
# model/register/source/variant/text_type werden AUSDRUECKLICH NIE geblockt
# (linguistische bzw. Provenienz-Achsen, human-vs-AI ist Kern-Use-Case).
_TECHNICAL_AXIS_FIELDS = frozenset(
    {"split", "fold", "shard", "partition", "batch", "seed"}
)


def _classify_meta_axes(
    meta_fields: List[str],
    cardinality: Mapping[str, Any],
    doc_count: int | None,
) -> List[Dict[str, Any]]:
    """Ordne jedem Meta-Feld eine Achsen-Kategorie zu.

    kind ist ``"axis"`` (kontrastierbar, >=2 Werte, keine Dok-ID),
    ``"empty"`` (KEIN Wert), ``"single"`` (genau 1 Wert),
    ``"doc_id"`` (nahezu eine Wert-pro-Dokument-
    Identitaet), ``"technical"`` (Partitionsfeld wie split/fold, wird VOR
    der Kardinalitaet entschieden und ist nie kontrastierbar) oder
    ``"unknown"`` (keine Kardinalitaet verfuegbar).
    """
    axes: List[Dict[str, Any]] = []
    for field in meta_fields:
        name = str(field)
        if not name:
            continue
        raw = cardinality.get(name)
        try:
            count = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            count = None
        if name.casefold() in _TECHNICAL_AXIS_FIELDS:
            kind = "technical"
        elif count is None:
            kind = "unknown"
        elif count == 0:
            # Ein Feld OHNE Werte ist nicht einwertig, es ist leer, und
            # die Leere ist oft selbst der Befund. Gemessen am
            # 2026-08-29: ``paired_with`` wurde als einwertig ausgewiesen,
            # obwohl es null Werte traegt. Genau dieses Feld wuerde eine
            # Mensch/KI-Paarung tragen, und dass es vorhanden und
            # unbefuellt ist, ist der staerkste Beleg dafuer, dass der
            # Index ohne Partnerkorpus gebaut wurde. Die Antwort besass
            # den Beleg und steckte ihn in die falsche Schublade.
            kind = "empty"
        elif count <= 1:
            kind = "single"
        elif (
            isinstance(doc_count, int)
            and doc_count >= _DOC_ID_MIN_DOCS
            and count > 2
            and count >= _DOC_ID_RATIO * doc_count
        ):
            kind = "doc_id"
        elif (
            name.casefold() in QUELLTEXTFELDER
            and isinstance(doc_count, int)
            and doc_count >= 1.5 * count
        ):
            # A source-text field groups versions of the same text.
            # Its cardinality can be far below document count without making it
            # an appropriate contrast axis.
            kind = "quelltext"
        else:
            kind = "axis"
        axes.append({"field": name, "count": count, "kind": kind})
    return axes

# --------------------------------------------------------------------------- #
# Runden-Leitplanke (Haertung r1, Fix 2): weiche Landung statt Abbruch.        #
# --------------------------------------------------------------------------- #

# Beim Erreichen von max_tool_runden injiziert der Orchestrator diese Zeile
# in die Fortsetzungsnachricht und exponiert keine weiteren Tools fuer den
# Turn. Antwort-Synthese, Referenzpfad und Verifikation laufen normal weiter
# (KEIN globaler Call-Cap, Parallelsession-Entscheid). H6 (B8-S2): die Zeile
# ist eine Pflichtstruktur, kein blosser Abbruchsatz — Budget MIT
# Qualitaetsboden (Befund + Belege + Deutung + Grenzen im Budget).
TOOL_ROUND_WRAPUP_LINE = (
    "Letzte Werkzeug-Runde ist vorbei. Antworte jetzt aus der vorhandenen "
    "Evidenz in genau dieser Gestalt: Kernbefund (max 2 Sätze); Belege "
    "(3-6 Zahlen/Zitate mit {{ev:...}}, jede Zahl genau einmal); Deutung "
    "(max 3 Sätze, als Deutung gekennzeichnet); Grenzen (max 2 Sätze, nur "
    "Gemessenes)."
)

# H6 (B8-S1): Zeit-Schalter der Runden-Leitplanke. Ab diesem Anteil des
# Turn-Zeitbudgets schaltet der Turn auf die weiche Antwort-Landung
# (Tools weg, Wrap-up-Briefing, volle Synthese+Verifikation), statt bei
# 100% in die deterministische Timeout-Landung zu laufen. 0.55 laesst dem
# kontrast-Rezept seine 4 Runden bei normalem Tempo und reserviert bei
# langsamem Modell trotzdem ein Synthese-Fenster. H9/C2 (V5): Rezepte
# koennen den Schalter per Datenfeld ``answer_switch_fraction`` frueher
# legen (exploration_meta: 0.4); dieser Wert bleibt der globale Default.
ANSWER_SWITCH_FRACTION = 0.55


def answer_switch_fraction_for_recipe(recipe_id: str) -> float:
    """Zeit-Schalter des Rezepts (Datenfeld), sonst der globale Default."""
    if recipe_id:
        try:
            value = float(
                getattr(
                    get_recipe(recipe_id),
                    "answer_switch_fraction",
                    ANSWER_SWITCH_UNSET,
                )
            )
            if value != ANSWER_SWITCH_UNSET and 0.0 < value <= 1.0:
                return value
        except Exception:
            return ANSWER_SWITCH_FRACTION
    return ANSWER_SWITCH_FRACTION


def tool_rounds_exhausted(
    rounds: int,
    recipe_id: str,
    started_at: float | None = None,
    max_time: float | None = None,
    now: float | None = None,
) -> bool:
    """Runden- ODER Zeit-Leitplanke erreicht (weiche Landung auf Antwort).

    Pure Funktion (injizierbare Uhr ``now`` fuer Tests). True, wenn die
    Rundenzahl des Rezepts erreicht ist ODER (Zeitbudget gesetzt UND
    mindestens 1 Runde gelaufen UND verstrichene Zeit >
    ``answer_switch_fraction_for_recipe(recipe_id) * max_time``).
    ``max_time=None`` zaehlt nur Runden. Floor: der Zeit-Schalter kappt nie
    vor Runde 1 — eine angebrochene Runde laeuft zu Ende, erst danach
    greift der Wrap-up.
    """
    if rounds >= max_tool_rounds_for_recipe(recipe_id):
        return True
    if max_time is None or max_time < 0:
        return False
    if rounds < 1 or started_at is None:
        return False
    current = time.perf_counter() if now is None else now
    switch = answer_switch_fraction_for_recipe(recipe_id)
    return (current - started_at) > switch * max_time


def max_tool_rounds_for_recipe(recipe_id: str) -> int:
    """Runden-Leitplanke des Rezepts (freier Modus und Fehler: 4)."""
    if recipe_id:
        try:
            recipe = get_recipe(recipe_id)
            return max(
                1,
                int(
                    getattr(
                        recipe, "max_tool_runden", FREE_MODE_MAX_TOOL_RUNDEN
                    )
                ),
            )
        except Exception:
            return FREE_MODE_MAX_TOOL_RUNDEN
    return FREE_MODE_MAX_TOOL_RUNDEN


# --------------------------------------------------------------------------- #
# Hybride Rezeptwahl (H9/C1, Befund V8): Stufe 1 = bestehende Trigger-         #
# Heuristik plus deterministisches Eindeutigkeits-Urteil (0 Calls). Stufe 2    #
# = EIN kleiner Klassifikator-Call ans Session-LLM, nur wenn Stufe 1 nichts    #
# oder nichts Eindeutiges liefert. Fehler, Timeout und Muell-Antworten         #
# degradieren zum heutigen Verhalten (Stufe-1-Pick bzw. freier Modus).         #
# --------------------------------------------------------------------------- #

#: Reissleine des Klassifikator-Calls, kein Zeitplan.
#:
#: MESSUNG vom 2026-08-31, ueber den SSH-Tunnel gegen ein 27B-Modell: EIN
#: warmer Klassifikator-Call brauchte 16,6 s. Das damalige Budget stand auf
#: 25 s, also 1,5-mal die erwartete Arbeit. Von zwei Live-Fragen lief EINE
#: hinein und degradierte zum freien Modus. Ein Limit, das bei jeder zweiten
#: Frage greift, ist keine Ausnahmesicherung mehr, sondern eine Taktvorgabe.
#:
#: Die Hausregel in CLAUDE.md ist dazu eindeutig: "Ein Limit ist ein
#: Failsafe, kein Zeitplan. Es gehoert weit ueber die erwartete Arbeit.
#: Greift es systematisch statt im Ausnahmefall, ist es falsch gesetzt,
#: nicht die Arbeit zu langsam."
#:
#: 300 s sind das 18-fache der gemessenen warmen Arbeit. Sie decken einen
#: kalten Prefill, ein groesseres Modell, eine belegte Maschine und einen
#: langsamen Tunnel. Wer hier trotzdem anschlaegt, hat kein Zeitproblem,
#: sondern einen haengenden Endpunkt, und genau davor schuetzt eine
#: Reissleine.
#:
#: Die Geschichte dieser Zahl gehoert dazu: 6 s waren fuer einen kalten
#: 30B-Prompt ohne KV-Cache-Praefix zu knapp und erzeugten reihenweise
#: Timeouts. Die Antwort darauf waren 25 s. Es war dieselbe Diagnose und
#: eine zu kleine Korrektur, weil sie am gemessenen Wert klebte statt weit
#: darueber zu gehen. route_turn_recipe liest die Konstante zur Laufzeit
#: (monkeypatch-freundlich fuer Offline-Tests).
RECIPE_CLASSIFIER_TIMEOUT_S = 300.0

#: Warm gemessene Dauer EINES Klassifikator-Calls (2026-08-31, 27B ueber
#: Tunnel). Der Deckel muss weit darueber liegen, ein Test haelt das fest.
RECIPE_CLASSIFIER_GEMESSEN_WARM_S = 16.6


def recipe_classifier_timeout_s() -> float:
    """Effektives Klassifikator-Zeitbudget (Sekunden).

    Konfig-Muster des Repos (Env > pyproject > Default, siehe die anderen
    ``COPILOT_``-Knoepfe in ``candyconc.config``): ist
    ``COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S`` gesetzt, gilt dieser Wert,
    sonst die Modul-Konstante (weiterhin monkeypatch-freundlich fuer
    Offline-Tests). Unlesbare oder nicht-positive Werte fallen auf die
    Konstante zurueck.
    """
    try:
        # Lazy: haelt recipe_runtime frei von einem Import-Zeit-Config-Zwang
        # (Foundation-Schnitt), config selbst ist ein Leaf-Modul.
        from candyconc.config import APP_CONFIG

        raw = getattr(APP_CONFIG, "COPILOT_RECIPE_CLASSIFIER_TIMEOUT_S", None)
    except Exception:
        raw = None
    if raw is None:
        return RECIPE_CLASSIFIER_TIMEOUT_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return RECIPE_CLASSIFIER_TIMEOUT_S
    return value if value > 0 else RECIPE_CLASSIFIER_TIMEOUT_S

# Stufen-Namen der Routing-Annotation im copilot.grounding-Event.
ROUTING_STAGE_TRIGGER = "trigger"
ROUTING_STAGE_LLM = "llm"
ROUTING_STAGE_FREE = "frei"
# ROUTING_STAGE_FRAGEFORM kommt aus ``frageform`` (oben importiert und
# unten re-exportiert): der zweite Router, heuristic_analysis_contract,
# liest die Stufe und darf ``recipe_runtime`` nicht importieren.

_CLASSIFIER_PROMPT_MAX_CHARS = 2800

# Die Flexions- und Wortgrenzen-Logik des starken Treffers liegt seit
# P5 in ``frageform`` (oben importiert): die Konstruktions- und
# Kandidaten-Erkenner brauchen sie ebenso, und zwei Kopien waeren zwei
# Wahrheiten. ``_strong_phrase_match`` bleibt als Name bestehen, weil
# Tests und Nachbarn ihn kennen.
_strong_phrase_match = starker_treffer


# H9.1 (Befund 2): generische Trigger-Lexeme tragen keine rezeptspezifische
# Evidenz. Ein Stufe-1-Pick, dessen einzige lexikalische Stuetze eine
# Familien-Route ohne rezeptspezifisches Lexem oder ein Treffer aus dieser
# Menge ist, gilt als NICHT eindeutig (-> Stufe 2) und wird nach einem
# Stufe-2-Fehlschlag auch nicht als Fallback uebernommen (freier Modus ist
# ehrlicher als ein geratenes Rezept: die Live-Fehlroutings
# fresh_meta_stichprobe -> gebrauch_kwic und fresh_gender_darstellung ->
# metadaten_struktur entstanden genau so — Klassifikator-Timeout plus
# Fallback auf einen rein generisch gestuetzten Pick).
GENERIC_TRIGGER_LEXEMES = frozenset(
    {"untersuche", "zeige", "welche", "informationen", "dokumente"}
)

_GENERIC_TOKEN_SPLIT = re.compile(r"[^\wäöüß]+")


def _phrase_is_generic(phrase: str) -> bool:
    """True, wenn JEDES Wort der Trigger-Phrase generisch ist.

    Mehrwort-Trigger wie ``welche metadaten`` bleiben spezifisch, sobald
    eines ihrer Woerter nicht in ``GENERIC_TRIGGER_LEXEMES`` liegt.
    """
    text = phrase.split(":", 1)[1] if phrase.startswith("wort:") else phrase
    tokens = [t for t in _GENERIC_TOKEN_SPLIT.split(text.casefold()) if t]
    return bool(tokens) and all(t in GENERIC_TRIGGER_LEXEMES for t in tokens)


def _capability_tool_lists(
    capabilities: Mapping[str, Any] | None,
) -> tuple[List[str], List[str]]:
    """(available, read_only) exakt wie ``select_recipe`` sie herleitet."""
    caps: Mapping[str, Any] = (
        capabilities if isinstance(capabilities, Mapping) else {}
    )
    raw_available = caps.get("available_tools") or _RECIPE_DEFAULT_TOOLS
    available = [str(name) for name in raw_available if str(name).strip()]
    raw_read_only = caps.get("read_only_tools") or available
    read_only = [str(name) for name in raw_read_only if str(name).strip()]
    return available, read_only


def stage1_recipe_decision(
    frage: str,
    capabilities: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Stufe 1: ``select_recipe`` plus Eindeutigkeits-Urteil (0 LLM-Calls).

    ``recipe`` ist der unveraenderte Heuristik-Pick (None = freier Modus).
    ``confident`` ist nur dann True, wenn der Pick von mindestens ZWEI
    unabhaengigen Signalen getragen wird (Familien-Route, starker
    Phrasen-Trigger, Split-QA-Nachfrage, Explorations-Klassifikation),
    KEIN anderes Rezept einen starken Trigger-Treffer hat (Mehrdeutigkeit)
    UND mindestens ein Signal rezeptSPEZIFISCH ist (H9.1, Befund 2): ein
    starker Trigger auf einem nicht-generischen Lexem, die ausdrueckliche
    Split-QA-Nachfrage (kontrast) oder die Explorations-Klassifikation.
    Eine Familien-Route allein oder ein Treffer aus
    ``GENERIC_TRIGGER_LEXEMES`` ist NIE eindeutig -> Stufe 2.
    ``specific`` gibt das Spezifitaets-Urteil an den Aufrufer weiter
    (route_turn_recipe uebernimmt einen rein generischen Pick auch nach
    einem Stufe-2-Fehlschlag nicht als Fallback).
    """
    selected = select_recipe(frage, capabilities)
    # H11: Der deterministische Split-QA-Detektor ERZWINGT kontrast, auch
    # wenn kein Phrasen-Trigger anschlaegt — eine ausdrueckliche technische
    # Partitions-Nachfrage ('driften train und test auseinander?') hat genau
    # ein richtiges Rezept, und der LLM-Klassifikator waehlte hier nachweislich
    # falsch (H10-Akzeptanz: Rueckfrage statt Split-QA).
    if (
        (selected is None or selected.id != "kontrast")
        and is_explicit_split_qa_request(frage)
    ):
        forced = RECIPES_BY_ID.get("kontrast")
        if forced is not None:
            return {
                "recipe": forced,
                "confident": True,
                "signals": ("split_qa",),
                "conflict": False,
                "specific": True,
                "kandidaten": (),
            }
    if selected is None:
        return {
            "recipe": None,
            "confident": False,
            "signals": (),
            "conflict": False,
            "specific": False,
            "kandidaten": (),
        }
    lowered = _normalised_question_text(frage)
    available, read_only = _capability_tool_lists(capabilities)
    signals: List[str] = []
    try:
        contract = heuristic_analysis_contract(
            frage,
            available_tools=available,
            read_only_tools=read_only,
        )
    except Exception:
        contract = None
    if contract is not None:
        family_recipe = _recipe_for_family(contract.analysis_family)
        if family_recipe is not None and family_recipe.id == selected.id:
            signals.append("family")
    matched_triggers = [
        phrase
        for phrase in selected.phrasen_trigger
        if _strong_phrase_match(lowered, phrase)
    ]
    if matched_triggers:
        signals.append("strong_trigger")
    # H9.1: die ausdrueckliche Nachfrage nach der technischen Datenaufteilung
    # (V7-Detektor) ist rezeptspezifische Evidenz fuer kontrast — genau der
    # Fall fresh_split_qa, der ohne dieses Signal grundlos in Stufe 2 lief.
    if selected.id == "kontrast" and is_explicit_split_qa_request(frage):
        signals.append("split_qa")
    if selected.id == "exploration_meta" and _is_exploratory_prompt(lowered):
        signals.append("exploratory")
    # P5: die beiden Frageform-Erkenner sind rezeptspezifische Evidenz.
    # Eine Frage, die eine Abfolge vorschreibt UND Belege dazu verlangt,
    # hat genau ein richtiges Rezept, und eine mitgelieferte
    # Kandidatenliste, deren Geltung geprueft werden soll, ebenso. Ohne
    # diese Signale lief konstr-scharnier-dreigliedrig in Stufe 2, obwohl
    # Stufe 1 nach dem Vorrang in select_recipe schon richtig lag.
    #
    # Es ist DASSELBE Praedikat, das in select_recipe das Rezept gesetzt
    # hat, und es heisst hier nicht zufaellig genauso. Es traegt die Last
    # zweimal, weil es zwei Bedingungen verbindet, die unabhaengig
    # voneinander erfuellt sein muessen: die Suchform (starker Form-Cue
    # oder ein als Gegenstand markierter Konnektor) und die
    # Belegforderung. Fuer die Zwei-schwache-Cues-Route, die vorher hier
    # mitzaehlte, gilt das nicht, sie ist deshalb gestrichen.
    if selected.id == "gebrauch_kwic" and ist_konstruktions_suchauftrag(frage):
        signals.append("konstruktion")
    kandidaten: Tuple[str, ...] = ()
    if selected.id == "kontrast" and ist_kandidatenlisten_pruefung(frage):
        signals.append("kandidatenliste")
        kandidaten = kandidatenliste_aus_frage(frage)
    specific = (
        any(not _phrase_is_generic(p) for p in matched_triggers)
        or "split_qa" in signals
        or "exploratory" in signals
        or "konstruktion" in signals
        or "kandidatenliste" in signals
    )
    conflict = any(
        recipe.id != selected.id
        and any(
            _strong_phrase_match(lowered, phrase)
            for phrase in recipe.phrasen_trigger
        )
        for recipe in RECIPES
    )
    # H10.1: Zwei unabhaengig uebereinstimmende SPEZIFISCHE Signale
    # (split_qa, oder Familien-Route plus starker nicht-generischer
    # Trigger) schlagen einen blossen Substring-Konflikt eines dritten
    # Rezepts. Der Akzeptanzlauf zeigte zweimal, dass Stufe 1 richtig lag
    # und der Konflikt die Entscheidung an einen falsch waehlenden
    # Klassifikator abgab (kontrast/split_qa -> metadaten, verlauf ->
    # metadaten).
    #
    # WAS ZWEI SIGNALE HEISST, wenn nur eines dasteht. 'split_qa',
    # 'konstruktion' und 'kandidatenliste' sind je EIN Praedikat, und
    # jedes verbindet zwei Bedingungen, die unabhaengig voneinander
    # erfuellt sein muessen: 'konstruktion' die vorgeschriebene Suchform
    # UND die Belegforderung, 'kandidatenliste' die gelesene Aufzaehlung
    # UND den Geltungs-Cue. Ein einzelner Cue erreicht keines von beiden.
    # Die frueher hier mitzaehlende Zwei-schwache-Cues-Route ist genau
    # deshalb gestrichen: sie liess "konstruktion" plus "abstand"
    # ausreichen, und damit ging claude-gegen-gpt-konstruktion an ein
    # Rezept, das die verlangten Zahlen nicht rechnet.
    strong_agreement = (
        "split_qa" in signals
        or "konstruktion" in signals
        or "kandidatenliste" in signals
        or ("family" in signals and "strong_trigger" in signals and specific)
    )
    return {
        "recipe": selected,
        "confident": (
            (len(signals) >= 2 and specific and not conflict)
            or strong_agreement
        ),
        "signals": tuple(signals),
        "conflict": conflict,
        "specific": specific,
        "kandidaten": kandidaten,
    }


@lru_cache(maxsize=1)
def build_recipe_classifier_prompt() -> str:
    """Byte-stabiler Mini-Prompt des Rezept-Klassifikators (Stufe 2).

    Eigener kleiner Prompt, AUSSERHALB des statischen Kerns: der
    KV-Cache-Praefix der Session bleibt unberuehrt. Das Menue sind die acht
    ``id: einsatz``-Zeilen aus ``recipes.recipe_index()`` (Datenquelle
    ``recipes_data``), die Ausgabe ist strikt eine Rezept-id oder ``frei``.
    """
    # H9.2: Menuezeilen tragen zusaetzlich typische Forschungssprache-
    # Paraphrasen (router_paraphrasen, reine Rezept-Daten) — der Live-Lauf
    # eval_h9b zeigte, dass das nackte Einsatz-Menue Formulierungen wie
    # 'Belegzahl' oder 'lexikalische Gesellschaft' nicht zuordnet.
    menu_lines = "\n".join(
        f"{recipe.id}: {recipe.einsatz}"
        + (
            f" | typische Formulierungen: {', '.join(recipe.router_paraphrasen)}"
            if recipe.router_paraphrasen
            else ""
        )
        for recipe in RECIPES
    )
    prompt = (
        "Ordne die folgende korpuslinguistische Nutzerfrage GENAU EINEM "
        "Analyse-Rezept zu.\n\n"
        "Rezept-Menü (id: Einsatz | typische Formulierungen):\n"
        + menu_lines
        + "\n\nBeispiele:\n"
        "Frage: Wie verbreitet ist das Wort Hoffnung in diesem Bestand? -> frequenz\n"
        "Frage: Mit welchen Wörtern verbindet sich Krise bevorzugt? -> assoziation\n"
        "Frage: Was lässt sich über Zusammensetzung und Provenienz der Dokumente sagen? -> metadaten_struktur\n"
        "Frage: In welchen Zusammenhängen taucht Heimat auf? Zeige Textbelege. -> gebrauch_kwic\n"
        "Frage: Wie ist das Wetter morgen? -> frei\n"
        "\nAntworte mit GENAU EINEM Wort: der Rezept-id aus dem Menü. "
        "Passt kein Rezept klar, antworte: frei. Keine Begründung, keine "
        "Satzzeichen, nichts weiter."
    )
    if len(prompt) > _CLASSIFIER_PROMPT_MAX_CHARS:
        raise ValueError(
            "Klassifikator-Prompt ueberschreitet "
            f"{_CLASSIFIER_PROMPT_MAX_CHARS} Zeichen ({len(prompt)})"
        )
    return prompt


def build_recipe_classifier_messages(question: str) -> List[Dict[str, str]]:
    """Klassifikator-Nachrichten: byte-stabiler Praefix, Frage GANZ am Ende.

    H9.1 (Befund 1b): der komplette Praefix (System-Nachricht = statischer
    Mini-Prompt mit dem Rezept-Menue, ``lru_cache``) ist fuer JEDE Frage
    byte-identisch, danach folgt GENAU EINE User-Nachricht mit der
    unveraenderten Frage. Keine Session- oder Korpus-Daten im Praefix: LM
    Studio kann den Praefix nach dem ersten Call im KV-Cache halten, jeder
    Folge-Call zahlt nur noch die Frage. Der Pin-Test in
    ``tests/ai/test_h9_1_followup_fix.py`` dokumentiert die Byte-Stabilitaet.
    """
    return [
        {"role": "system", "content": build_recipe_classifier_prompt()},
        {"role": "user", "content": str(question or "")},
    ]


def _classifier_reply_text(raw: Any) -> str:
    """Antworttext aus String- oder choices-foermigen LLM-Ergebnissen."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Mapping):
        try:
            choices = raw.get("choices") or [{}]
            message = choices[0].get("message", {}) or {}
            return str(message.get("content", "") or "")
        except (AttributeError, IndexError, TypeError):
            return ""
    return ""


def parse_recipe_classifier_reply(reply: Any) -> str:
    """Robustes Parsen der Klassifikator-Antwort.

    Substring-Match auf die bekannten Rezept-ids: GENAU EINE id im Text
    waehlt dieses Rezept. Alles andere (leer, ``frei``, Muell, mehrere ids)
    ergibt ``""`` = freier Modus bzw. Stufe-1-Fallback beim Aufrufer.

    H11.4: Eine um Zeichen verkuerzte Antwort (gemessen: ``assoziatio``
    statt ``assoziation``) fiel bisher stumm in den freien Modus. Ein
    EINDEUTIGES Praefix ab vier Zeichen zaehlt deshalb als Treffer — die
    Eindeutigkeit bleibt die Bedingung, geraten wird nichts.
    """
    text = _classifier_reply_text(reply).strip().casefold()
    if not text:
        return ""
    hits = [rid for rid in RECIPES_BY_ID if rid in text]
    if len(hits) == 1:
        return hits[0]
    if hits:
        return ""
    praefix_treffer = [
        rid
        for rid in RECIPES_BY_ID
        if len(text) >= 4 and rid.startswith(text)
    ]
    if len(praefix_treffer) == 1:
        logger.warning(
            "Klassifikator-Antwort %r war unvollstaendig, eindeutiges "
            "Praefix von %r, Routing gerettet.",
            text,
            praefix_treffer[0],
        )
        return praefix_treffer[0]
    return ""


async def classify_recipe_llm(
    question: str,
    call_llm: Callable[..., Any],
    *,
    timeout_s: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """EIN Klassifikator-Call mit hartem Zeitbudget (Stufe 2).

    Fehler, Timeout und Muell-Antworten ergeben ``""`` (Aufrufer faellt auf
    das heutige Verhalten zurueck). Eine Turn-Cancellation (CancelledError)
    propagiert; die weiche ``cancelled``-Sonde bricht ohne Call ab.
    """
    if cancelled is not None and cancelled():
        return ""
    budget = recipe_classifier_timeout_s() if timeout_s is None else timeout_s
    messages = build_recipe_classifier_messages(question)
    try:
        # Async-Erkennung inkl. Callables mit async __call__ (Test-Fakes).
        if asyncio.iscoroutinefunction(call_llm) or asyncio.iscoroutinefunction(
            getattr(call_llm, "__call__", None)
        ):
            # temperature=0: Klassifikation muss deterministisch sein (Live-
            # Varianz: dieselbe Frage routete mal korrekt, mal 'frei').
            # Defensiv ohne kwarg wiederholen, falls ein Fake es nicht kennt.
            try:
                raw = await asyncio.wait_for(
                    call_llm(messages, [], temperature=0), timeout=budget
                )
            except TypeError:
                raw = await asyncio.wait_for(
                    call_llm(messages, []), timeout=budget
                )
        else:
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(
                        call_llm, messages, [], temperature=0
                    ),
                    timeout=budget,
                )
            except TypeError:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(call_llm, messages, []), timeout=budget
                )
            if inspect.isawaitable(raw):
                raw = await asyncio.wait_for(raw, timeout=budget)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Rezept-Klassifikator fehlgeschlagen oder Zeitbudget erreicht; "
            "Fallback auf Stufe-1-Verhalten",
            exc_info=True,
        )
        return ""
    if cancelled is not None and cancelled():
        return ""
    parsed = parse_recipe_classifier_reply(raw)
    # H9.2: Roh-Antwort einsehbar machen — der Live-Lauf eval_h9b zeigte
    # stumme frei-Degradationen, deren Ursache ohne dieses Log nicht
    # diagnostizierbar war (leerer content vs. Mehrfach-id vs. echtes frei).
    logger.warning(
        "Rezept-Klassifikator: parsed=%r content=%r",
        parsed,
        _classifier_reply_text(raw)[:120],
    )
    return parsed


def _routing_result(
    recipe: Any, stage: str, kandidaten: Sequence[str] = ()
) -> Dict[str, Any]:
    families = tuple(getattr(recipe, "familien", ()) or ())
    ergebnis: Dict[str, Any] = {
        "recipe_id": str(recipe.id),
        "family": families[0] if families else "",
        "stage": stage,
    }
    # P5/P7: die deterministisch gelesene Kandidatenliste reist mit dem
    # Routing-Ergebnis, weil der Termlisten-Modus des Kontrastrezepts sie
    # braucht und ein Eval-Lauf sonst nicht sieht, ob sie gelesen wurde.
    if kandidaten:
        ergebnis["kandidaten"] = tuple(kandidaten)
    return ergebnis


async def route_turn_recipe(
    question: str,
    capabilities: Mapping[str, Any] | None,
    call_llm: Callable[..., Any] | None,
    *,
    timeout_s: float | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Dict[str, Any]:
    """Hybride Rezeptwahl: Stufe 1 (0 Calls) sonst EIN Klassifikator-Call.

    Ergebnis: ``{"recipe_id", "family", "stage"}`` mit ``stage`` aus
    ``trigger`` (Stufe-1-Heuristik, auch als Fallback nach Stufe-2-Fehlern),
    ``llm`` (Klassifikator hat gewaehlt) oder ``frei`` (kein Rezept). Die
    Stufe wandert als Annotation ins copilot.grounding-Event, damit Evals
    die Routing-Quelle sehen. Nie eine Ablehnung. Degradation nach einem
    Stufe-2-Fehlschlag (H9.1, Befund 2): der Stufe-1-Pick wird nur dann
    uebernommen, wenn er rezeptspezifische Evidenz hat (``specific``);
    ein rein generisch gestuetzter Pick degradiert zum freien Modus, statt
    das dokumentierte Fehlrouting (gebrauch_kwic fuer eine Metadaten-Frage)
    als vermeintlich eindeutig auszugeben.
    """
    try:
        decision = stage1_recipe_decision(question, capabilities)
    except Exception:
        logger.exception(
            "stage1_recipe_decision fehlgeschlagen; der Turn laeuft im "
            "freien Modus"
        )
        decision = {"recipe": None, "confident": False, "specific": False}
    recipe = decision.get("recipe")
    signale = tuple(decision.get("signals") or ())
    # DIE LISTE IST EINE EIGENSCHAFT DER FRAGE, NICHT DES REZEPTS.
    # ``stage1_recipe_decision`` fuellt ihr Feld nur, wenn Stufe 1 selbst
    # kontrast gewaehlt hat. Waehlt Stufe 1 wegen der Turn-Sicht
    # (available_tools) ein anderes Rezept und kommt erst Stufe 2 aus dem
    # groesseren routing_tool_universe auf kontrast, ginge die Liste
    # sonst am LLM-Zweig verloren, und P7 wie der Eval-Lauf saehen nicht,
    # dass sie da war. Genau diese Universum-gegen-Turn-Sicht-Differenz
    # ist unten bei H9.2 als gemessener Fall dokumentiert.
    kandidaten = kandidatenliste_aus_frage(question)
    if recipe is not None and decision.get("confident"):
        stufe = (
            ROUTING_STAGE_FRAGEFORM
            if ("konstruktion" in signale or "kandidatenliste" in signale)
            else ROUTING_STAGE_TRIGGER
        )
        return _routing_result(recipe, stufe, kandidaten)
    chosen = ""
    if call_llm is not None:
        chosen = await classify_recipe_llm(
            question,
            call_llm,
            timeout_s=timeout_s,
            cancelled=cancelled,
        )
    verworfen = ""
    if chosen:
        candidate = RECIPES_BY_ID.get(chosen)
        available, _ = _capability_tool_lists(capabilities)
        # H9.2: der Klassifikator-Pick prueft gegen das ROUTING-Universum
        # (Registry minus Capability-Gates), nicht gegen die rezeptblinde
        # Stichwort-Vorauswahl des Turns — die verwarf korrekte Picks
        # ('frequenz' fiel, weil die Vorauswahl query_count nicht erriet).
        # Stufe 1 behaelt bewusst die Turn-Sicht (available_tools).
        caps_map: Mapping[str, Any] = (
            capabilities if isinstance(capabilities, Mapping) else {}
        )
        universe = list(caps_map.get("routing_tool_universe") or []) or available
        if candidate is not None and _recipe_tools_available(
            candidate, universe
        ):
            return _routing_result(candidate, ROUTING_STAGE_LLM, kandidaten)
        # WARUM EIN KORREKTER PICK FAELLT.
        #
        # Am 2026-08-31 sagte der Klassifikator zu einer Kontrastfrage
        # 'kontrast', und die Antwort trug trotzdem term_frequency. Warum der
        # Pick fiel, sagte keine Aufzeichnung. Beide Ausgaenge sahen von
        # aussen gleich aus: "der Klassifikator hat nichts geliefert" und
        # "der Klassifikator hat geliefert, und wir haben es weggeworfen".
        # Eine Fehlleitung, deren Ursache unsichtbar ist, wird bei jedem
        # Auftreten neu geraten.
        #
        # Der Grund wandert in den Log UND in das Routing-Ergebnis, weil der
        # Log in einem Eval-Lauf nicht mit der Antwort zusammenkommt, die
        # Annotation aber schon.
        if candidate is None:
            verworfen = f"unbekannte Rezept-Id {chosen!r}"
        else:
            verworfen = (
                f"{chosen}: kein Kernwerkzeug im Universum "
                f"(braucht eines von {sorted(candidate.kern_tools)})"
            )
        logger.warning("Rezept-Pick verworfen, %s", verworfen)
    if recipe is not None and decision.get("specific"):
        ergebnis = _routing_result(recipe, ROUTING_STAGE_TRIGGER, kandidaten)
        if verworfen:
            ergebnis["verworfen"] = verworfen
        return ergebnis
    frei = {"recipe_id": "", "family": "", "stage": ROUTING_STAGE_FREE}
    if verworfen:
        frei["verworfen"] = verworfen
    return frei


def recipe_routing_annotation(
    routing: Mapping[str, Any] | None,
) -> Dict[str, str]:
    """annotations-Eintrag fuers copilot.grounding-Event (leer ohne Routing)."""
    stage = str((routing or {}).get("stage") or "")
    if not stage:
        return {}
    recipe_id = str((routing or {}).get("recipe_id") or "")
    note = f"stage={stage} recipe={recipe_id or 'frei'}"
    # Der verworfene Pick gehoert IN die Annotation. Ein Eval-Lauf liest
    # Antworten, keine Serverlogs, und ohne diesen Zusatz sieht er nur ein
    # falsches Rezept ohne Ursache.
    verworfen = str((routing or {}).get("verworfen") or "")
    if verworfen:
        note += f" verworfen={verworfen}"
    # Die gelesene Kandidatenliste gehoert in dieselbe Zeile: sie ist der
    # Grund fuer das Rezept und zugleich die Eingabe des Termlisten-Modus.
    kandidaten = tuple((routing or {}).get("kandidaten") or ())
    if kandidaten:
        note += f" kandidaten={len(kandidaten)}"
    return {"claim_id": "recipe_routing", "note": note}


# --------------------------------------------------------------------------- #
# Capability-Fehlerklasse (Haertung r1, Fix 4): Korpus-Wahrheit statt          #
# Recovery-Anlass.                                                             #
# --------------------------------------------------------------------------- #

# Feature-Gate- und Semantic-Asset-Fehler sind deterministische Korpus-
# Wahrheiten (Eval-Runde 1: word_sketch-409- und semantic_search-Kaskaden
# frassen das Turn-Budget). GENAU EIN ehrliches unavailable-Item, danach
# fehlt das Werkzeug dem Tool-Space des Turns, außer die Absage nennt einen
# anderen Argumentwert desselben Werkzeugs (``ausweg``).
CAPABILITY_UNAVAILABLE_MARKERS = (
    "missing_corpus_features",
    "productoperation-feature-gate",
    "embedding search ist im fast index modus deaktiviert",
    "embedding backend ist deaktiviert",
    "faiss index fehlt",
    "faiss metadaten fehlen",
    "faiss fehlt",
    "semantic_index_missing",
    "word-lexikon fehlt",
    # Ein Attribut ohne Annotation ist eine Korpuswahrheit wie eine fehlende
    # Capability: ein zweiter Aufruf kann sie nicht aendern.
    "keine_annotation_im_attribut",
)


def capability_unavailable_reason(output: Any) -> str:
    """Grund, wenn ein Tool-Fehler die Capability-Fehlerklasse trifft.

    Leerer String fuer alle anderen Fehler: nur nachweislich
    korpusgebundene Unverfuegbarkeit rechtfertigt die Degradation, ein
    gewoehnlicher Laufzeitfehler behaelt seine normale Fehlersemantik.
    """
    if not isinstance(output, dict):
        return ""
    if str(output.get("status") or "").strip().casefold() != "error":
        return ""
    message = str(output.get("message") or "")
    lowered = message.casefold()
    for marker in CAPABILITY_UNAVAILABLE_MARKERS:
        if marker in lowered:
            return message[:300]
    return ""


#: Welche Ebene ein Werkzeug ueber welches Argument waehlt.
_EBENENARGUMENT = {
    "frequency_list": "group_by",
    "collocate_stats": "attribute",
    "keyness": "attribute",
    "ngram_frequency": "attribute",
}


def capability_unavailable_result(
    tool_name: str,
    output: Any,
    *,
    args: Mapping[str, Any] | None = None,
    vorhandene_ebenen: Sequence[str] = (),
) -> Dict[str, Any]:
    """Ehrliches unavailable-Ergebnis, und zwar eines mit einem Ausweg.

    LIVE am 2026-09-01. Das Modell rief ``frequency_list`` mit
    ``group_by="pos"`` auf einem Korpus auf, das nur ``word`` und
    ``lemma`` traegt. Der Aufruf scheiterte zu Recht. Die Antwort lautete
    danach vollstaendig:

        Ich kann hier nur die direkt belegten Beobachtungen sicher
        berichten. Es liegen noch keine hinreichend belegten Beobachtungen
        fuer eine belastbare Antwort vor.

    525 Zeichen, null Befunde, obwohl dasselbe Werkzeug mit ``word`` oder
    ``lemma`` sofort geliefert haette. Die Meldung sagte "eine fachliche
    Alternative waehlen" und NANNTE KEINE, dazu "Nicht erneut aufrufen".
    Zusammen liest sich das als: hoer auf. Genau das tat das Modell.

    Der Harnisch WEISS, welche Ebenen das Korpus traegt. Wenn er es weiss,
    muss er es sagen. Eine Grenze ohne Ausweg kostet den ganzen Turn, und
    ein Turn ohne Befund ist teurer als jeder zusaetzliche Aufruf.
    """
    reason = capability_unavailable_reason(output) or "Capability fehlt"
    argument = _EBENENARGUMENT.get(tool_name, "")
    gewaehlt = str((args or {}).get(argument) or "").strip() if argument else ""
    moeglich = [
        str(e).strip() for e in (vorhandene_ebenen or ()) if str(e).strip()
    ]
    ausweg, gegenstand = "", tool_name
    if argument and gewaehlt and moeglich and gewaehlt not in moeglich:
        andere = " oder ".join(f"{argument}={e!r}" for e in moeglich[:3])
        ausweg = (
            f" Dieses Korpus trägt {' und '.join(moeglich[:3])}, aber kein "
            f"{gewaehlt!r}. Wiederhole denselben Aufruf mit {andere}."
        )
        gegenstand = f"{tool_name} mit {argument}={gewaehlt!r}"  # nur der Wert fehlt
    return {
        "status": "unavailable",
        "code": "not_available",
        "tool": tool_name,
        "reason": reason,
        "ausweg": ausweg.strip(),
        "message": (
            f"{gegenstand} ist für dieses Korpus nicht verfügbar "
            "(fehlende Capability)." + (ausweg or
            " Nicht mit denselben Argumenten wiederholen: die Grenze "
            "ehrlich benennen oder eine fachliche Alternative wählen.")
        ),
    }


# --------------------------------------------------------------------------- #
# Zeitbewusste Verifikation (Haertung r1, Fix 3): Antworttext des Skip-Pfads.  #
# --------------------------------------------------------------------------- #

VERIFIER_SKIPPED_NOTE = "LLM-Verifikation übersprungen (Zeitbudget)"

# A deterministic fallback can follow different verification outcomes.
# Describe the actual outcome instead of attributing every fallback to
# the time budget, which may not have caused it.
VERIFIER_UNBESTAETIGT_NOTE = (
    "LLM-Verifikation abgeschlossen, ohne diese Aussagen zu bestätigen"
)
#: Hoechstens so viele deterministische Nachtraege stehen im Antworttext.
#:
#: Fuenf Wachen haengen am Chokepoint und koennen zusammen elf Saetze
#: erzeugen. Was darueber hinausgeht, wird nicht verworfen, sondern als
#: Annotation gefuehrt: es erreicht den Evidenzstrom, nicht die Prosa.
MAX_NACHTRAEGE = 2

VERIFIER_LAEUFT_NOTE = "LLM-Verifikation läuft noch (vorläufige Antwort)"

#: Alle Wortlaute, die denselben Zustand melden: der Text ist
#: deterministisch gedeckt, aber nicht modellgeprueft. Die Politur haengt
#: an dieser Menge, nicht an einem einzelnen Satz, damit ein vierter
#: Grund nicht wieder still durchfaellt.
VERIFIER_HINWEISE = (
    VERIFIER_SKIPPED_NOTE,
    VERIFIER_UNBESTAETIGT_NOTE,
    VERIFIER_LAEUFT_NOTE,
)

_VERIFIER_NOTE_ENGLISH = {
    VERIFIER_SKIPPED_NOTE: "LLM verification skipped (time budget)",
    VERIFIER_UNBESTAETIGT_NOTE: "LLM verification completed without confirming these claims",
    VERIFIER_LAEUFT_NOTE: "LLM verification is still running (provisional answer)",
}

# H6 (B5, Teil 2): Satz-Drop-Policy statt sichtbarer Inline-Platzhalter.
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_LIST_LINE_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_UNRESOLVED_DROP_NOTE = (
    "Aussage(n) entfernt: Referenz auf Evidenz nicht auflösbar."
)


def drop_unresolved_sentences(text: str) -> str:
    """Wie ``aussagen_ohne_deckung_streichen``, aber nur der Text.

    Vier Aufrufer brauchen bloss den bereinigten Text (Orchestrator,
    Server-Renderer, Kontrollrahmen, Verifier-Skip). Wer sagen will, WAS
    gefallen ist, nimmt die Berichtsfassung.
    """
    return aussagen_ohne_deckung_streichen(text)[0]


def aussagen_ohne_deckung_streichen(text: str) -> "tuple[str, list[str]]":
    """Entfernt Saetze/Listenzeilen mit unaufgeloesten Evidenz-Platzhaltern.

    Renderer-Policy (H6, B5): statt sichtbarer
    ``MISSING_EVIDENCE_PLACEHOLDER`` im Endtext fallen die betroffenen
    Aussagen, und GENAU EINE Sammel-Annotation benennt die Zahl der
    entfernten Aussagen. Wachposten: wuerden mehr als 50% der Aussagen
    fallen, bleibt das Original mit Platzhaltern erhalten (eine entkernte
    Antwort waere unehrlicher als ein sichtbarer Platzhalter). Kein Call,
    rein deterministisch.

    Der zweite Rueckgabewert nennt die gefallenen Aussagen einzeln. Die
    Sammelzeile allein hat eine Messung blind gemacht, und zwar an der
    GROESSEREN der beiden Zahlen: der zweite Messarm
    (``evaluation/deutung/harnisch_nachher.jsonl``, Turn
    gemischt-erklaerroutine-handschrift) meldete "7 Aussage(n) entfernt:
    Referenz auf Evidenz nicht aufloesbar" neben "8 Zitat(e) ohne Deckung
    entfernt", der Rumpf danach 548 Zeichen. Die 8 Zitate stehen seit der
    Stellenannotation einzeln im Ereignisstrom, die 7 Aussagen stammen aus
    dieser Funktion und waren es nicht. Ob dort Fabrikate oder
    Tabellenzeilen fielen, liess sich hinterher nicht entscheiden.
    """
    raw = str(text or "")
    if MISSING_EVIDENCE_PLACEHOLDER not in raw:
        return raw, []
    total = 0
    dropped: List[str] = []
    kept_lines: List[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if MISSING_EVIDENCE_PLACEHOLDER not in line:
            total += len(_SENTENCE_SPLIT_PATTERN.split(stripped))
            kept_lines.append(line)
            continue
        if _LIST_LINE_PATTERN.match(line):
            # Listenzeile = eine Aussage, faellt als Ganzes.
            total += 1
            dropped.append(stripped)
            continue
        sentences = _SENTENCE_SPLIT_PATTERN.split(stripped)
        kept = [
            s for s in sentences if MISSING_EVIDENCE_PLACEHOLDER not in s
        ]
        total += len(sentences)
        dropped.extend(
            s for s in sentences if MISSING_EVIDENCE_PLACEHOLDER in s
        )
        if kept:
            kept_lines.append(" ".join(kept))
    if not dropped:
        return raw, []
    if not total or len(dropped) / total > 0.5:
        return raw, []
    cleaned = "\n".join(kept_lines).strip()
    if not cleaned:
        return raw, []
    return f"{cleaned}\n\n{len(dropped)} {_UNRESOLVED_DROP_NOTE}", dropped


# H7/A1 (R7-Befunde kwic_zeit/profil_zeit): zwei callfreie Politur-Schritte
# fuer aufgeloeste Modell-Entwuerfe.
#
# 1. Wert-Doppelung "ZAHL Einheitenwort DIESELBE-ZAHL" ("32 Treffer 32",
#    "1 Treffer 1"): entsteht, wenn das Modell den Wert nennt, das
#    Einheitenwort schreibt und den {{ev:...}}-Marker DAHINTER setzt — der
#    Renderer setzt den Wert dann ein zweites Mal ein. Die Doppelung wird
#    nur fuer eine feste Einheitenwort-Liste kollabiert (digits-only-
#    Vergleich, gruppierungs-tolerant); "10 von 12" oder "f = 3 rank 3"
#    bleiben unangetastet.
# 2. Identische Zeilen-Duplikate ("total_candidates 1 / total_rows 1,
#    truncated false" identisch unter JEDER Relation): nur das erste
#    Vorkommen bleibt, weitere byte-identische Zeilen ab
#    _MIN_FOLD_LINE_CHARS fallen (reine Redundanz, kein Informationsverlust).
_UNIT_WORDS_FOR_DOUBLES = frozenset(
    {
        "treffer",
        "treffern",
        "beleg",
        "belege",
        "belegen",
        "token",
        "tokens",
        "dokument",
        "dokumente",
        "dokumenten",
        "wert",
        "werte",
        "werten",
        "zeile",
        "zeilen",
    }
)
_UNIT_DOUBLE_PATTERN = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)*)[ \t]+"
    r"([A-Za-zÄÖÜäöüß]+)[ \t]+"
    r"(\d+(?:[.,]\d+)*)(?![\d.,]?\d)"
)
_MIN_FOLD_LINE_CHARS = 25


def collapse_unit_number_doubles(text: str) -> str:
    """Kollabiert "32 Treffer 32" zu "32 Treffer" (feste Einheitenwortliste)."""

    def _replace(match: re.Match[str]) -> str:
        first, word, second = match.groups()
        if word.casefold() not in _UNIT_WORDS_FOR_DOUBLES:
            return match.group(0)
        if re.sub(r"\D", "", first) != re.sub(r"\D", "", second):
            return match.group(0)
        return f"{first} {word}"

    return _UNIT_DOUBLE_PATTERN.sub(_replace, str(text or ""))


# H8/F1 (R7b-Befund 'Deutung\nDeutung: ...'): das Wrap-up-Pflichtformat gibt
# die Sektionsueberschrift vor, und das Modell wiederholt das Label am
# Zeilenanfang seines Textes. Konservative Politur: NUR wenn die unmittelbar
# vorangehende nicht-leere Zeile GENAU dieses eine Label-Wort ist (nackt, als
# Markdown-Ueberschrift oder fett), faellt das fuehrende 'Label:' der
# Folgezeile. Andere Doppelungen bleiben unangetastet.
# P8: Label-Liste und Ueberschriftmuster leben in draft_sections, weil der
# grounding_verifier dieselben Muster braucht, um beim Deutungs-Retry die
# Deutungs-Sektion des Entwurfs zu finden. Zwei Kopien waeren zwei Naehte.
_SECTION_LABELS_FOR_DEDUP = SEKTIONSLABEL
_SECTION_HEADING_PATTERNS = SEKTIONS_UEBERSCHRIFT_MUSTER
# Der Doppelpunkt ist PFLICHT (sonst wuerde 'Deutung der Daten ...' unter
# einer 'Deutung'-Ueberschrift faelschlich gekuerzt). Auszeichnungs-Varianten
# nur explizit und symmetrisch. H11.4: kursiv (``*Deutung:*``) kam dazu —
# qwen3.8-27b schreibt die Wiederholung so, und sie blieb ungefaltet stehen.
#: H12: Beide Label in DERSELBEN Zeile. Live am 2026-08-29 gemessen:
#:
#:     **Deutung:** Deutung: Die Methode war korrekt gewaehlt ...
#:
#: Die bestehende Wache kennt nur Ueberschrift-plus-Folgezeile und liess
#: das stehen. Verlangt wird ein ausgezeichnetes Label mit Doppelpunkt,
#: unmittelbar gefolgt vom selben Label nackt mit Doppelpunkt.
_SECTION_LABEL_INLINE_PATTERNS = {
    label.casefold(): re.compile(
        r"^(\s*(?:\*\*|__|\*|_)"
        + label
        + r"\s*:(?:\*\*|__|\*|_)?\s*)"
        + label
        + r"\s*:\s*",
        re.IGNORECASE,
    )
    for label in _SECTION_LABELS_FOR_DEDUP
}


def label_doppelung_in_zeile_falten(text: str) -> str:
    """``**Deutung:** Deutung:`` faellt auf ``**Deutung:**``."""

    zeilen = []
    for zeile in str(text or "").split("\n"):
        for muster in _SECTION_LABEL_INLINE_PATTERNS.values():
            neu = muster.sub(r"\1", zeile, count=1)
            if neu != zeile:
                zeile = neu
                break
        zeilen.append(zeile)
    return "\n".join(zeilen)


_SECTION_LABEL_PREFIX_PATTERNS = {
    label.casefold(): re.compile(
        r"^(\s*)(?:"
        + r"|".join(
            (
                r"\*\*" + label + r"\s*:\*\*",
                r"__" + label + r"\s*:__",
                r"\*\*" + label + r"\*\*\s*:",
                r"__" + label + r"__\s*:",
                r"\*" + label + r"\s*:\*",
                r"_" + label + r"\s*:_",
                r"\*" + label + r"\*\s*:",
                r"_" + label + r"_\s*:",
                label + r"\s*:",
            )
        )
        + r")\s*",
        re.IGNORECASE,
    )
    for label in _SECTION_LABELS_FOR_DEDUP
}


def strip_repeated_section_labels(text: str) -> str:
    """Entfernt 'Deutung: ' am Zeilenanfang direkt unter der Zeile 'Deutung'.

    Rein deterministisch, exakte Label-Wiederholung der vier
    Wrap-up-Sektionslabels. Die Ueberschriftzeile bleibt, nur das
    wiederholte Praefix der Folgezeile faellt. Bleibt die Folgezeile
    danach leer, bleibt sie unveraendert (kein Informationsverlust).
    """
    lines = str(text or "").split("\n")
    previous_label = ""
    result: List[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            result.append(raw_line)
            continue
        if previous_label:
            prefix_pattern = _SECTION_LABEL_PREFIX_PATTERNS[previous_label]
            match = prefix_pattern.match(raw_line)
            if match:
                remainder = raw_line[match.end():]
                if remainder.strip():
                    raw_line = match.group(1) + remainder
                    stripped = raw_line.strip()
        previous_label = next(
            (
                label
                for label, pattern in _SECTION_HEADING_PATTERNS.items()
                if pattern.match(stripped)
            ),
            "",
        )
        result.append(raw_line)
    return "\n".join(result)


def fold_duplicate_lines(text: str) -> str:
    """Byte-identisch wiederholte Zeilen (>= 25 Zeichen) nur einmal zeigen.

    Normalisierung wie im Qualitaets-Lint: strip plus fuehrende
    Listenmarker. Kurze Zeilen (Tabellentrenner, Leerzeilen) bleiben
    unangetastet.
    """
    seen: set[str] = set()
    kept: List[str] = []
    for raw_line in str(text or "").split("\n"):
        line = raw_line.strip()
        while line[:1] in {"-", "*"}:
            line = line[1:].strip()
        if len(line) >= _MIN_FOLD_LINE_CHARS:
            if line in seen:
                continue
            seen.add(line)
        kept.append(raw_line)
    return "\n".join(kept)


def trim_incomplete_tail_sentence(text: str) -> str:
    """Kappt einen angebrochenen Schlusssatz am letzten Satzende.

    Server-Backstop-Politur (H6, B2): ein mitten im Stream abgebrochener
    Antworttext endet mitten im Satz. Endet der Text nicht auf einem Satz-
    oder Markdown-Schlusszeichen, wird am letzten Satzende (``.``/``!``/
    ``?`` vor Whitespace) gekappt. Existiert KEIN Satzende, bleibt der
    Text unveraendert (angebrochen ist ehrlicher als leer).
    """
    stripped = str(text or "").rstrip()
    if not stripped:
        return stripped
    if stripped[-1] in ".!?:`)*\"'":
        return stripped
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", stripped)]
    if not ends:
        return stripped
    return stripped[: ends[-1]].rstrip()


# --------------------------------------------------------------------------- #
# H9/C2 (V6+V11): finaler Politur-Chokepoint. ``final_answer_polish`` laeuft   #
# GENAU EINMAL auf jedem fertigen Antworttext, egal ueber welche Landung er    #
# den Orchestrator verlaesst (normal, wrap-up, skip, salvage, fail-closed).    #
# Rein deterministisch, kein LLM-Call.                                         #
# --------------------------------------------------------------------------- #

# Show verification status in the answer as well as event annotations.
# Distinguish completed deterministic checks from a skipped model review
# without retracting interpretations that were never rejected.
FINAL_POLISH_HONESTY_LINE = (
    "Verifikationsstand: Zahlen, Referenzen und Zitate deterministisch "
    "geprüft, ohne zweite Gegenlesung durch das Modell."
)
FINAL_POLISH_HONESTY_LINE_EN = (
    "Verification status: numbers, references and quotations checked "
    "deterministically, without a second reading by the model."
)
_POLISH_CLAIM_ID = "final_polish"

# V6(b): interne Marker, die nie sichtbar bleiben duerfen. ``{{ev:...}}``-
# Reste werden wie unaufloesbare Referenzen behandelt (Satz-Drop); nackte
# Evidenz-/Observed-Fact-Kuerzel (E_<tool>_<n>[_suffix], ev3) werden aus dem
# Satz gescrubbt, der Satz selbst bleibt.
_LEFTOVER_EV_MARKER_PATTERN = re.compile(r"\{\{\s*ev:[^}]*\}\}")
# V6(a): Inline-Label-Doppelung 'Deutung: Deutung:' (auch fett) faellt auf
# EIN Label. Die Zeilen-Variante 'Deutung\nDeutung:' behandelt weiterhin
# ``strip_repeated_section_labels``.
_INLINE_LABEL_DOUBLE_PATTERNS = tuple(
    re.compile(
        r"(?<![\wÄÖÜäöüß])(?:\*\*|__)?(" + label + r")(?:\*\*|__)?\s*:\s*"
        r"(?:\*\*|__)?" + label + r"(?:\*\*|__)?\s*:",
        re.IGNORECASE,
    )
    for label in _SECTION_LABELS_FOR_DEDUP
)

# V6(c): eine sichtbare Zeile, die NUR aus einer CQL-Query besteht, wird als
# Provenienz gerahmt ('Query: `...`'), nie als nackte Zeile stehen gelassen.
_NAKED_CQL_LINE_PATTERN = re.compile(
    r"^(?:\[[^\[\]]*\]|\{\d+(?:,\d+)?\}|within\s+\w+|[|()+*?\s])+$"
)

# V6(e)/V11: Meta-Zeilen, die aus dem sichtbaren Text in die Event-
# Annotationen wandern.
_DROP_STAT_LINE_PATTERN = re.compile(
    r"^\d+\s+Aussage\(n\)\s+entfernt\b.*$"
)


def _collapse_inline_label_doubles(text: str) -> str:
    for pattern in _INLINE_LABEL_DOUBLE_PATTERNS:
        text = pattern.sub(r"\1:", text)
    return text


#: Eine Zitatspanne in der Modellfassung. Bewusst weit gefasst und nur zum
#: SCHUETZEN benutzt: eine Spanne zu viel laesst Leerraum stehen, eine
#: Spanne zu wenig schreibt einen Korpusbeleg um.
#:
#: GIERIG bis zum typografischen Schluss. Eine nicht gierige Fassung endete
#: am ersten geraden Anfuehrungszeichen -- und genau das steht als
#: KORPUSTEXT mitten in vielen Belegen (``Es muss " dafuer Sorge getragen
#: werden``). Der Rest der Spanne blieb unmaskiert, und die Kappung schnitt
#: den gedeckten Beleg ab. In einem Lauf ueber 600 echte KWIC-Zitate traf
#: das sieben Zeilen, nachdem die Backtick-Klasse schon geschlossen war.
_ZITATSPANNE_SCHUTZ = re.compile(
    r'„[^\n]*“|„[^\n„“”"]*(?<=\S)"|»[^\n]*«|“[^\n]*”|«[^\n]*»|"[^\n"]{1,400}"')


def _ausserhalb_der_zitate(text: str, wandeln) -> str:
    """``wandeln`` auf alles anwenden, was NICHT in einer Zitatspanne steht."""
    roh = str(text or "")
    teile: List[str] = []
    letzte = 0
    for treffer in _ZITATSPANNE_SCHUTZ.finditer(roh):
        teile.append(wandeln(roh[letzte:treffer.start()]))
        teile.append(treffer.group(0))
        letzte = treffer.end()
    teile.append(wandeln(roh[letzte:]))
    return "".join(teile)


#: Zwei Zitatspannen, nur durch Leerraum oder einen Gedankenstrich
#: getrennt. Gruppe 1 ist die gerade gesetzte Modell-Fassung, Gruppe 2 die
#: vom Referenz-Renderer aufgeloeste Evidenz.
#: Die Modell-Fassung mischt die Anfuehrungszeichen frei (``„Text"``),
#: die Renderer-Fassung ist immer ``„Text“``.
_ADJACENT_QUOTE_PAIR = re.compile(
    r'[„"]([^„“"\n]{12,})["“](\s*[–-]?\s*)„([^„“\n]{12,})“'
)


def _quote_kern(span: str) -> str:
    """Vergleichsform einer Zitatspanne: nur Wortzeichen, kleingeschrieben."""
    return re.sub(r"[^\wÄÖÜäöüß]+", "", span).casefold()


def _collapse_duplicate_quote_spans(text: str) -> str:
    """Modell-Zitat neben identischem Renderer-Zitat faellt weg (H11.4).

    Gemessen mit qwen3.8-27b: das Modell schreibt die KWIC-Zeile selbst
    (mit ``[Suchwort]``-Klammern) UND setzt eine Evidenz-Referenz daneben,
    die deterministisch zur selben Zeile aufgeloest wird. Der Leser sieht
    dasselbe Zitat zweimal. Erhalten bleibt immer die aufgeloeste Fassung,
    weil nur sie aus der Turn-Evidenz stammt.
    """

    def _ersetze(match: re.Match) -> str:
        modell = _quote_kern(match.group(1))
        aufgeloest = _quote_kern(match.group(3))
        if not modell or not aufgeloest:
            return match.group(0)
        if modell in aufgeloest or aufgeloest in modell:
            return f"„{match.group(3)}“"
        return match.group(0)

    return _ADJACENT_QUOTE_PAIR.sub(_ersetze, str(text or ""))


# H11.6 ZURUECKGENOMMEN: _collapse_mixed_format_number_pairs.
#
# Die Regel "zwei benachbarte Zahlen in unterschiedlichem Format -> die
# zweite faellt" sollte die Renderer-Dublette '4781 4.513 VERB' aufraeumen.
# Sie kann diese aber nicht von legitimen Paaren unterscheiden, und der
# Schaden ist groesser als der Nutzen. Gemessen:
#
#   'Die Rate liegt bei 32 569,5 pmw.'  ->  'Die Rate liegt bei 32 pmw.'
#   'NOUN 9740 17,3 % aller Tokens.'    ->  'NOUN 9740 % aller Tokens.'
#   'Im Jahr 2020 1.234 Belege'         ->  'Im Jahr 2020 Belege'
#
# Aus einer richtigen Rate wird eine FALSCHE. Die Politur fabriziert damit
# selbst, wogegen der ganze Harness gebaut ist, und der Verlust bleibt
# unter der Meldeschwelle von _log_politur_verlust. Eine kosmetische
# Doppelung ist hinnehmbar, eine erfundene Zahl nicht.
#
# Die Dublette bleibt damit sichtbar. Das ist die richtige Seite des
# Fehlers: der Leser sieht zwei Zahlen und stutzt, statt eine falsche zu
# glauben.


def _wrap_naked_query_lines(text: str) -> str:
    lines: List[str] = []
    im_block = False
    for raw_line in str(text or "").split("\n"):
        stripped = raw_line.strip()
        # Preserve the code block so the query remains directly copyable.
        if re.match(r"(?:```|~~~)", stripped):
            im_block = not im_block
        elif (
            not im_block
            and stripped.startswith("[")
            and "=" in stripped
            and "`" not in stripped
            and _NAKED_CQL_LINE_PATTERN.match(stripped)
        ):
            indent = raw_line[: len(raw_line) - len(raw_line.lstrip())]
            raw_line = f"{indent}Query: `{stripped}`"
        lines.append(raw_line)
    return "\n".join(lines)


#: Code-Fences sind Nutztext, keine Zitatspanne.
_CODE_FENCE_PATTERN = re.compile(r"^\s*(?:```|~~~)")

#: Eindeutig schliessende Anfuehrungszeichen.
_QUOTE_CLOSERS = ("“", "”", "»")

#: Ein gerades ``"`` ist mehrdeutig. Es schliesst nur, wenn direkt davor
#: kein Leerraum steht — dieselbe Regel, nach der Smart-Quote-Verfahren
#: oeffnend von schliessend trennen. ``…zusammen" (Beleg 4)`` schliesst,
#: ``…bringen "??? Sie`` (Zitatzeichen aus dem Korpustext) nicht.
_STRAIGHT_QUOTE_CLOSER = re.compile(r'(?<=[^\s])"')


def _maskierte_zitatspannen(line: str) -> str:
    """Abgeschlossene Zitatspannen durch Fuellzeichen ersetzen, laengentreu.

    Nur zur ENTSCHEIDUNG, nie zur Ausgabe. Was in einer geschlossenen
    Spanne steht, ist Korpustext und darf keine Kappung ausloesen.
    """
    return _ZITATSPANNE_SCHUTZ.sub(
        lambda m: "\x01" * len(m.group(0)), str(line or ""))


def _quote_span_offen(line: str) -> bool:
    schliessend = sum(line.count(closer) for closer in _QUOTE_CLOSERS)
    schliessend += len(_STRAIGHT_QUOTE_CLOSER.findall(line))
    return line.count("„") > schliessend


def _trim_dangling_quote_spans(text: str) -> str:
    """Der sichtbare Text endet nie innerhalb einer „...“- oder `...`-Spanne.

    V6(d): Kuerzungen (Stream-Abbruch, Satz-Kappung) duerfen nie mitten in
    einem Zitat enden. Eine Kuerzung landet immer am ENDE des Textes, also
    wird auch nur die letzte sichtbare Zeile geprueft.

    H11.4 (gemessen mit qwen3.8-27b): die fruehere zeilenweise Pruefung hat
    81% einer Antwort entfernt — jede Zeile mit ``„Zitat"`` (typografisch
    geoeffnet, gerade geschlossen) und jede ```-Fence-Zeile galt als offene
    Spanne. Zeilen in Code-Fences und alle Zeilen vor der letzten bleiben
    deshalb byte-identisch.
    """
    lines = str(text or "").split("\n")
    im_fence = False
    fence_zeile: List[bool] = []
    for line in lines:
        ist_fence_marke = bool(_CODE_FENCE_PATTERN.match(line))
        # Die Fence-Marke selbst zaehlt als geschuetzt, danach kippt der
        # Zustand fuer die folgenden Zeilen.
        fence_zeile.append(ist_fence_marke or im_fence)
        if ist_fence_marke:
            im_fence = not im_fence

    letzte = -1
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() and not fence_zeile[idx]:
            letzte = idx
            break
    if letzte < 0:
        return "\n".join(lines)

    roh = lines[letzte]
    if re.search(r"(?:\w\w|\d|[)\]“”\"'»«*_`])[.!?](?:\s*(?:\[\[[^\[\]]*\]\]|\{\{[^{}]*\}\}|[)\]“”\"'»«*_`]))*\s*$", roh):
        return "\n".join(lines)  # A sentence ending is complete, while an unfinished abbreviation may not be.
    line = roh
    while True:
        # Auf der MASKIERTEN Fassung entscheiden. Ein Backtick oder ein
        # gerades Anfuehrungszeichen INNERHALB einer abgeschlossenen
        # „...“-Spanne ist Korpustext, kein Trenner. Der Bench-Korpus
        # fuehrt den Apostroph als Backtick (``kann ` s nicht fassen``),
        # und die Vorfassung schnitt daraufhin erst am Backtick und dann,
        # weil die „-Spanne nun offen schien, bis zum „ zurueck: der
        # GEDECKTE Beleg verschwand spurlos, ohne Annotation und ohne
        # Platzhalter, der Leser sah "Beleg:" und nichts dahinter.
        # In einem Lauf ueber 600 echte KWIC-Zitate traf das 12 Zeilen.
        # Die Maskierung ist laengentreu, die Indizes gelten also fuer
        # beide Fassungen.
        maskiert = _maskierte_zitatspannen(line)
        if maskiert.count("`") % 2 == 1:
            line = line[: maskiert.rfind("`")].rstrip()
            continue
        if _quote_span_offen(maskiert):
            line = line[: maskiert.rfind("„")].rstrip()
            continue
        break
    if line == roh:
        return "\n".join(lines)

    stripped = line.strip().strip("-*+ ").strip()
    if not stripped or not re.search(r"[\wÄÖÜäöüß]", stripped):
        return "\n".join(lines[:letzte] + lines[letzte + 1 :])
    return "\n".join(lines[:letzte] + [line] + lines[letzte + 1 :])


def _extract_meta_note_lines(
    text: str,
) -> tuple[str, List[Dict[str, str]], bool]:
    """Zieht Drop-Statistik- und Verifier-Skip-Zeilen aus dem Text.

    Rueckgabe: (bereinigter Text, Annotationen, verifier_uebersprungen).
    """
    annotations: List[Dict[str, str]] = []
    verifier_skipped = False
    kept: List[str] = []
    for raw_line in str(text or "").split("\n"):
        stripped = raw_line.strip()
        if _DROP_STAT_LINE_PATTERN.match(stripped):
            annotations.append(
                {"claim_id": _POLISH_CLAIM_ID, "note": stripped}
            )
            continue
        if any(hinweis in stripped for hinweis in (*VERIFIER_HINWEISE, *_VERIFIER_NOTE_ENGLISH.values())):
            annotations.append(
                {"claim_id": _POLISH_CLAIM_ID, "note": stripped}
            )
            verifier_skipped = True
            continue
        kept.append(raw_line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return cleaned, annotations, verifier_skipped


_TOOL_TRACE_LINE_PATTERN = re.compile(
    r"^\s*[-*]?\s*\w+\(\{.*\)\s*->\s*\{"
)


def _drop_tool_trace_lines(text: str) -> tuple[str, int]:
    """Rohe Tool-Trace-Zeilen ('name({...}) -> {...}') aus sichtbarem Text.

    H9.2 (V6, Engine-Ausfall-Salvage): der Server-Backstop kann den
    Stream-Teiltext mit rohen Tool-Aufruf-Protokollzeilen ausgeben. Das
    Muster (Call-Klammer MIT JSON plus '-> {'-Ergebnispfeil) kommt in
    legitimer Prosa nicht vor.
    """
    kept: List[str] = []
    dropped = 0
    for line in str(text or "").splitlines():
        if _TOOL_TRACE_LINE_PATTERN.match(line):
            dropped += 1
            continue
        kept.append(line)
    return "\n".join(kept), dropped


#: Ab diesem Anteil verlorener Zeichen ist die Politur ein Befund und
#: keine Kosmetik mehr.
POLITUR_VERLUST_SCHWELLE = 0.40


def _log_politur_verlust(stufen: Sequence[tuple[str, int]]) -> None:
    """Grossen Textverlust der Politur benennen, samt schuldiger Stufe."""
    if len(stufen) < 2:
        return
    roh = stufen[0][1]
    endstand = stufen[-1][1]
    if roh <= 0 or endstand >= roh * (1.0 - POLITUR_VERLUST_SCHWELLE):
        return
    schritte = [
        (name, stufen[i][1] - wert)
        for i, (name, wert) in enumerate(stufen[1:], start=0)
    ]
    schuldig = max(schritte, key=lambda paar: paar[1])
    logger.warning(
        "Politur hat %s%% des Antworttextes entfernt (%s -> %s Zeichen). "
        "Groesster Einzelverlust: %s (-%s). Verlauf: %s",
        round(100 * (roh - endstand) / roh),
        roh,
        endstand,
        schuldig[0],
        schuldig[1],
        " -> ".join(f"{name}:{wert}" for name, wert in stufen),
    )


def final_answer_polish(
    text: str, deckung_wache: bool = True
) -> tuple[str, List[Dict[str, str]]]:
    """EIN finaler Politur-Durchlauf fuer jeden fertigen Antworttext (V6/V11).

    Rein deterministisch: (a) Label-Doppelungen falten, (b) interne IDs
    scrubben (unaufloesbare ``{{ev:...}}``-Reste fallen wie gehabt als
    Saetze), (c) nackte Query-Zeilen als 'Query: `...`' rahmen, (d) keine
    Kuerzung endet in einer Zitat-Spanne, (e) Drop-Statistiken und der
    Verifier-Skip-Hinweis wandern in die zurueckgegebenen Annotationen
    (copilot.grounding-Event), im sichtbaren Text steht stattdessen genau
    EIN ehrlicher Satz. Leerer/whitespace-Text bleibt unveraendert.

    ``deckung_wache=False`` (Deutungs-Kontrakt, F6-Regelumkehr) ueberspringt
    das Streichen platzhaltertragender Saetze: dort ist der Platzhalter die
    Anker-Markierung der Deutungs-Pipeline und muss die Landung ueberleben
    (gemessen 2026-09-08: 3 NEIN-Urteile, 0 Markierungen in der
    Auslieferung, weil diese Wache die Saetze danach GANZ strich).
    """
    raw = str(text or "")
    if not raw.strip():
        return raw, []
    # H11.4: Jede Stufe wird vermessen. Die Politur soll putzen, nicht
    # entkernen — welche Stufe wie viel Text nimmt, gehoert bei grossem
    # Verlust ins Log, sonst ist eine ausgeduennte Antwort nicht
    # diagnostizierbar.
    stufen: List[tuple[str, int]] = [("roh", len(raw))]

    def _messen(name: str, wert: str) -> str:
        stufen.append((name, len(wert)))
        return wert

    polished = _messen("label_dedupe", strip_repeated_section_labels(raw))
    polished = _messen("inline_label", _collapse_inline_label_doubles(polished))
    polished = _messen("id_scrub", _scrub_internal_ids(polished))
    polished, _tool_traces = _drop_tool_trace_lines(polished)
    _messen("tool_traces", polished)
    leftover = _LEFTOVER_EV_MARKER_PATTERN.findall(polished)
    if leftover:
        # H11.4: Der Satz-Drop kann eine Antwort bis zur Substanzlosigkeit
        # ausduennen (gemessen mit qwen3.8-27b: 3.5k -> 657 Zeichen mit
        # leeren Belegpunkten). Welche Marker nicht aufloesbar waren, gehoert
        # ins Log — sonst sieht der Betreiber nur eine kurze Antwort.
        vorher = len(polished)
        polished = _LEFTOVER_EV_MARKER_PATTERN.sub(
            MISSING_EVIDENCE_PLACEHOLDER, polished
        )
        logger.warning(
            "Unaufloesbare Evidenz-Referenzen gestrichen: %s Marker, "
            "Text %s Zeichen. Marker: %s",
            len(leftover),
            vorher,
            ", ".join(sorted(set(leftover))[:12]),
        )
    # Check both raw unresolved markers and placeholders already produced by
    # reference resolution. Run the same cleanup for either form while keeping
    # the existing safeguard against removing most of an answer.
    if deckung_wache:
        polished, _gefallene_aussagen = aussagen_ohne_deckung_streichen(
            polished)
    else:
        _gefallene_aussagen: List[str] = []
    _messen("ev_marker", polished)
    polished, annotations, verifier_skipped = _extract_meta_note_lines(
        polished
    )
    # WAS gefallen ist, nicht nur WIE VIEL. Siehe
    # ``aussagen_ohne_deckung_streichen``: die groessere der beiden vom
    # Messarm gemeldeten Zahlen (7 Aussagen gegen 8 Zitate) entsteht hier.
    annotations = list(annotations) + aussagen_annotationen(
        _gefallene_aussagen)
    _messen("meta_notes", polished)
    polished = _messen(
        "zitat_dublette", _collapse_duplicate_quote_spans(polished)
    )
    polished = _messen("query_wrap", _wrap_naked_query_lines(polished))
    polished = _messen("quote_trim", _trim_dangling_quote_spans(polished))
    _log_politur_verlust(stufen)
    if verifier_skipped:
        polished = (
            polished.rstrip() + "\n\n"
            + _t(FINAL_POLISH_HONESTY_LINE, FINAL_POLISH_HONESTY_LINE_EN)
        )
    polished = polished.rstrip()
    if not polished:
        # Wachposten: die Politur darf eine Antwort nie entkernen.
        return raw, []
    return polished, annotations


# Recognize literal corpus quotations across supported punctuation forms.
# Use word boundaries for apostrophe forms so contractions do not open spans.
# Require a non-space after markdown emphasis markers so list bullets do
# not become quotations.
_ZITAT_PAARE = (
    # Pair matching quotation marks before applying the minimum span length.
    # Skipping short spans during scanning can pair one closer with the next opener.
    # For mixed typographic and straight quotes, enforce the full length in
    # that regex branch so a short mixed prefix cannot hide the remaining quote.
    r'„(?P<a>[^“\n]*?)“',
    r'„(?P<a2>[^„“\n]{12,}?)"',
    r'"(?P<b>[^"\n]*?)"',
    r'“(?P<c>[^”\n]*?)”',
    r'»(?P<d>[^«\n]*?)«',
    r'«(?P<e>[^»\n]*?)»',
    r'‚(?P<f>[^\u2018\n]*?)\u2018',
    r'(?<![\w\u2019])\u2018(?P<g>[^\u2019\n]*?)\u2019(?![\w])',
    r"(?<![\w'])'(?P<h>[^'\n]*?)'(?![\w])",
    r'`(?P<i>[^`\n]*?)`',
    r'(?<![\w*])\*(?P<j>[^\s*][^*\n]*?)\*(?![\w*])',
    r'(?<![\w_])_(?P<k>[^\s_][^_\n]*?)_(?![\w_])',
    # Ein Blockzitat OHNE eigene Anfuehrungszeichen. Mit ``.*`` verschlang
    # dieser Zweig die GANZE Zeile als Zitatinhalt, auch die vom Harness
    # selbst gebaute Belegzeile
    #     > **Beleg:** „<Korpuszeile>“ · Dokument `<id>`
    # Die Woerter "Beleg" und "Dokument" und die Dokument-ID stehen
    # natuerlich in keiner Belegzeile, also galt die Zeile als ungedeckt
    # und wurde vollstaendig durch den Platzhalter ersetzt. Traegt die
    # Zeile eigene Anfuehrungszeichen, gehoert sie den Zweigen darueber.
    r'^[ \t]*>[ \t]?(?P<l>[^„"“»«‚\u2018\u2019”‹›\n]*)$',
)
_WOERTLICHES_ZITAT = re.compile("|".join(_ZITAT_PAARE), re.MULTILINE)

#: Die Gruppen der Auszeichnungsformen (Code, Kursiv). Fuer sie gilt die
#: strengere Vorpruefung in ``strike_unsupported_quotes``.
_MARKUP_GRUPPEN = frozenset({"i", "j", "k", "l"})

#: Dieselben Paare, aber ueber Zeilengrenzen. Ein Zitat, das der Renderer
#: umgebrochen hat, war sonst unsichtbar fuer die Wache.
_WOERTLICHES_ZITAT_MEHRZEILIG = re.compile(
    r'„(?P<a>[^“]*?)“|»(?P<d>[^«]*?)«|“(?P<c>[^”]*?)”|"(?P<b>[^"]*?)"'
)

#: So viele Zeilenumbrueche darf ein mehrzeiliges Zitat hoechstens haben.
#:
#: Der Zweitlauf paarte ein UNPAARIGES oeffnendes „ ueber beliebig viele
#: Zeilen mit dem naechsten “ und behandelte alles dazwischen als EIN Zitat.
#: Ein vergessenes schliessendes Anfuehrungszeichen ist der haeufigste
#: Modellfehler ueberhaupt, und die Folge war, dass gegruendete Zahlen,
#: gedeckte Belege und Fliesstext gemeinsam als ungedeckt galten und
#: ``drop_unresolved_sentences`` sie ganz entfernte. Gemessen: von einer
#: Antwort mit zwei echten Belegen und vier gepruefen Zahlen blieben zwei
#: Saetze uebrig, und die Annotation meldete EIN entferntes Zitat.
#:
#: Ein vom Renderer umbrochenes Zitat laeuft ueber wenige Zeilen. Ueber eine
#: LEERZEILE laeuft es nie: dort endet der Absatz.
ZITAT_MAX_UMBRUECHE = 3

#: So viele Woerter eines Zitats muessen als zusammenhaengende Folge in der
#: sichtbaren Evidenz stehen, damit es als belegt gilt.
ZITAT_MINDESTFOLGE = 4

#: Ab dieser Laenge ist eine Spanne auch mit weniger Woertern eine
#: Belegstelle und keine Termnennung mehr. Die reine Wortschwelle liess
#: ``ruecksichtslose Invasoren marschieren`` durch: drei Woerter, 37
#: Zeichen, ungeprueft in die Antwort. Die Begruendung der Schwelle lautet
#: "Fachbegriffe oder Termnennungen", und die deckt eine 37-Zeichen-Phrase
#: nicht ab.
ZITAT_MINDESTZEICHEN = 20


def _zitat_normalisieren(text: str) -> list[str]:
    """Wortfolge eines Zitats, ohne Auszeichnung und Interpunktion."""
    ohne_markup = re.sub(r"[|`*_]+", " ", str(text or ""))
    return re.findall(r"\w+", ohne_markup.casefold(), re.UNICODE)


def zitat_ist_belegt(zitat: str, oberflaechen: Sequence[str]) -> bool:
    """Steht die Wortfolge des Zitats zusammenhaengend in der Evidenz?

    Bewusst genau die Pruefung, die auch ohne LLM moeglich ist: ein
    Vergleich der Tokenfolge gegen die sichtbaren Belegzeilen. Kein
    Netzwerk, kein Modell, keine Sekunde Zeitbudget.
    """
    return _zitat_gedeckt(
        zitat, [_zitat_normalisieren(o) for o in (oberflaechen or ())])


def _zitat_gedeckt(zitat: str, heuhaufen: "Sequence[list[str]]") -> bool:
    """Wie ``zitat_ist_belegt``, aber mit VORNORMALISIERTEN Belegzeilen.

    ``strike_unsupported_quotes`` prueft viele Zitate gegen dieselben
    Belegzeilen. Die Vorfassung normalisierte jede Belegzeile fuer JEDES
    Zitat neu: bei 800 Zitaten gegen 3161 Belegzeilen sind das 2,5
    Millionen Tokenisierungen derselben Zeichenketten. Gemessen 1921 ms fuer
    eine 83-KB-Antwort. Die Normalisierung passiert jetzt einmal.
    """
    # DIE SCHWELLE GILT DEM GANZEN ZITAT, NICHT EINEM SEGMENT DAVON.
    # Die erste Fassung dieser Auslassungsregel rief ``_zitat_gedeckt``
    # rekursiv je Segment auf, und damit galt die Termnennungs-Ausnahme je
    # Segment. Drei eingefuegte Punkte schalteten so ZITAT_MINDESTZEICHEN
    # ab. Gemessen gegen zwei Belegzeilen: ``ruecksichtslose Invasoren
    # marschieren`` fiel (richtig), ``ruecksichtslose ... Invasoren ...
    # marschieren`` galt als belegt und ging unveraendert durch, ebenso
    # ``die Invasoren ... marschieren durch``. Das ist wortgleich die
    # Phrase, deren Durchrutschen ZITAT_MINDESTZEICHEN ueberhaupt erzwungen
    # hat, und ``_shared._quoted_segment_is_supported`` urteilte ueber
    # beide Spannen False. Der Chokepoint war also lockerer als der
    # Verifizierer, den er absichern soll.
    segmente = _auslassungssegmente(zitat)
    if _ist_termnennung(zitat, segmente):
        return True
    if segmente:
        return _segmente_der_reihe_nach_gedeckt(segmente, heuhaufen)
    return _folge_gedeckt(zitat, heuhaufen)


def _folge_ab(nadel: "Sequence[str]", heu: "Sequence[str]", ab: int) -> int:
    """Das Ende der Wortfolge ab Position ``ab``, oder -1.

    Getrennt von ``_folge_gedeckt``, weil eine Auslassung nicht fragt, OB
    ein Segment vorkommt, sondern ob es NACH dem vorigen vorkommt.
    """
    breite = len(nadel)
    for start in range(ab, len(heu) - breite + 1):
        if heu[start:start + breite] == nadel:
            return start + breite
    return -1


def _segmente_der_reihe_nach_gedeckt(
    segmente: "Sequence[str]", heuhaufen: "Sequence[list[str]]"
) -> bool:
    """Stehen ALLE Segmente in Reihenfolge in EINER Belegzeile?

    ALLE IN EINER, NICHT JEDES IRGENDWO. Die Vorfassung pruefte jedes
    Segment einzeln gegen die ganze Belegliste, und damit galt eine
    Montage aus Bruchstuecken verschiedener KWIC-Zeilen als woertliches
    Korpuszitat. Gemessen gegen zwei Belegzeilen ("Wir muessen die Grenzen
    schuetzen und die Zuwanderung begrenzen" / "Die Politik hat versagt und
    die Menschen sind wuetend"): ``die Grenzen schuetzen ... die Menschen
    sind wuetend`` galt als belegt, und 'Ein Korpusbeleg lautet „...“.'
    lief unveraendert durch. Sogar die umgedrehte Reihenfolge (``die
    Zuwanderung begrenzen ... Wir muessen die Grenzen``) galt als belegt.
    Eine Spanne, die in keinem einzigen Dokument steht, als woertliches
    Zitat auszugeben, ist die Fabrikation, gegen die diese Wache steht.

    Die Begruendung der Vorfassung (zwei Belegstellen einer Konstruktion
    stuenden typischerweise nicht in derselben Zeile) ist durch den
    motivierenden Fall selbst widerlegt: KWIC-Zeilen zu ``nicht nur ...
    sondern auch`` tragen beide Teile in EINER Zeile und in dieser
    Reihenfolge ("| es geht nicht nur um Geld , sondern auch um Anstand
    |"). Die Lockerung kaufte dem Konstruktionsnamen also nichts ab und
    machte den Chokepoint zugleich lockerer als
    ``_shared._quoted_segment_is_supported``, den er absichert: dort
    laeuft seit jeher ein Cursor ueber EINE Flaeche.
    """
    # Ein Segment aus reiner Interpunktion deckt nichts und behauptet
    # nichts. Es darf die Deckung des Zitats weder tragen noch kippen.
    nadeln = [n for n in (_zitat_normalisieren(t) for t in segmente) if n]
    if not nadeln:
        return True
    for heu in heuhaufen or ():
        cursor = 0
        for nadel in nadeln:
            cursor = _folge_ab(nadel, heu, cursor)
            if cursor < 0:
                break
        else:
            return True
    return False


def _ist_termnennung(zitat: str, segmente: "Sequence[str] | None" = None) -> bool:
    """Ist die Spanne zu kurz, um ueberhaupt eine Belegstelle zu sein?

    Solche Spannen sind Fachbegriffe oder Termnennungen, keine Zitate. Die
    Zeichenlaenge zaehlt mit, sonst faellt eine dreiwortige 37-Zeichen-Phrase
    darunter (siehe ZITAT_MINDESTZEICHEN).

    Gemessen wird der KERN: bei einem Zitat mit Auslassung die Segmente
    ohne ihre Punkte, sonst das Zitat selbst. Sonst kaeme eine Spanne
    allein durch eingefuegte Auslassungspunkte ueber die Zeichenschwelle
    oder darunter.
    """
    kern = " ".join(segmente) if segmente else str(zitat or "").strip()
    nadel = _zitat_normalisieren(kern)
    if len(nadel) < ZITAT_MINDESTFOLGE and len(kern) < ZITAT_MINDESTZEICHEN:
        return True
    # Ein einzelnes Wort bleibt eine Termnennung, egal wie lang.
    return len(nadel) < 2


def _folge_gedeckt(zitat: str, heuhaufen: "Sequence[list[str]]") -> bool:
    """Steht die Wortfolge zusammenhaengend in EINER Belegzeile?

    Ohne jede Termnennungs-Ausnahme. Wer sie hier hineinnimmt, gibt sie je
    Auslassungssegment aus statt einmal fuer das ganze Zitat, und das war
    der Weg, auf dem ``ruecksichtslose ... Invasoren ... marschieren`` an
    der Wache vorbeikam.
    """
    nadel = _zitat_normalisieren(zitat)
    if not nadel:
        # Ein Segment aus reiner Interpunktion deckt nichts und behauptet
        # nichts. Es darf die Deckung des Zitats nicht kippen.
        return True
    for heu in heuhaufen or ():
        if len(heu) < len(nadel):
            continue
        for start in range(len(heu) - len(nadel) + 1):
            if heu[start : start + len(nadel)] == nadel:
                return True
    return False


#: Ueberschrift des deterministischen Methodensteckbriefs. Wer sie aendert,
#: muss auch die Abtrennung im Eval-Harness nachziehen (P2.3).
METHODENSTECKBRIEF_UEBERSCHRIFT = "### Methodensteckbrief"
#: The same heading in an English answer (glossary: "method card").
METHODENSTECKBRIEF_UEBERSCHRIFT_EN = "### Method card"


#: Massnamen, die in der Prosa vorkommen, zusammen mit dem Feld der
#: Evidenzoberflaeche, auf das sie zeigen MUESSEN (P2.2/B16). Nur Namen mit
#: mindestens drei Zeichen: 'mi' oder 'll' als blosses Wort waeren in
#: deutscher Prosa nicht sicher von Fliesstext zu trennen.
_MASSNAME_ZU_FELD: Dict[str, str] = {
    "log_ratio": "log_ratio", "log-ratio": "log_ratio",
    "log ratio": "log_ratio", "logratio": "log_ratio",
    "logdice": "logdice", "log-dice": "logdice", "log dice": "logdice",
    "npmi": "npmi", "mi3": "mi3", "lmi": "lmi",
    "t_score": "t", "t-score": "t", "z_score": "z", "z-score": "z",
    "chi2": "chi2", "delta_p": "delta_p",
    "pmw": "per_million", "per_million": "per_million",
    "pro million": "per_million", "per million": "per_million",
    "q_value": "q_value", "p_value": "p_value", "p-wert": "p_value",
    "dpnorm": "dpnorm", "juilland_d": "juilland_d",
    "carroll_d2": "carroll_d2",
}

#: Die Felder, die MASSE tragen. Nur zwischen ihnen ist eine Verwechslung
#: eine Fehlbindung; rank, window, min_freq und Verwandte sind Parameter und
#: Ordnungszahlen, deren Werte zufaellig mit jeder Prosa-Zahl kollidieren.
_MASSFELDER = frozenset(_MASSNAME_ZU_FELD.values()) | {
    "diff_per_million", "log_likelihood", "ll", "g2", "bic",
    "log_ratio_ci_low", "log_ratio_ci_high", "expected", "observed",
    "dice", "mi", "z", "t", "dp",
    # Zaehlung und Rate gehoeren dazu: 'pmw 460.712' mit der ROHZAHL statt
    # der Rate ist die Fehlbindung, gegen die B16 geschrieben wurde.
    "total", "total_hits", "observed_frequency", "freq", "f",
}

_MASSNAME_MUSTER = re.compile(
    "(?<![A-Za-zÄÖÜäöü_])(?P<name>"
    + "|".join(
        sorted((re.escape(n) for n in _MASSNAME_ZU_FELD), key=len, reverse=True)
    )
    + r")(?![A-Za-zÄÖÜäöü_])"
    r"(?:(?![.!?]\s)[^\d\n]){0,14}?(?P<zahl>-?\d[\d.,]*)",
    re.IGNORECASE,
)

_FELD_WERT_MUSTER = re.compile(
    r"(?:^|[\s,;(])(?P<feld>[A-Za-z_][A-Za-z0-9_.]{1,39})=(?P<wert>-?\d[\d.,]*)"
)


def _als_zahlen(roh: str) -> set:
    """Alle Lesarten einer Zahl in deutscher ODER englischer Schreibweise.

    ``460.712`` ist deutsch 460712 und englisch 460,712. Die Schreibweise
    allein entscheidet das nicht, und eine Wache, die raet, erzeugt genau
    den Fehlalarm, den sie verhindern soll. Deshalb werden BEIDE Lesarten
    gefuehrt: die Wache schweigt, sobald EINE davon zum genannten Feld
    passt, und meldet nur, wenn KEINE passt und mindestens eine auf ein
    anderes Feld desselben Postens zeigt.
    """
    text = str(roh or "").strip().rstrip(".,")
    if not text:
        return set()
    kandidaten = {text}
    if "," in text and "." in text:
        # Die HINTERE Trennung ist das Dezimalzeichen, das ist eindeutig.
        kandidaten = {
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        }
    elif "," in text:
        kandidaten = {text.replace(",", "."), text.replace(",", "")}
    elif "." in text:
        kandidaten = {text, text.replace(".", "")}
    werte = set()
    for kandidat in kandidaten:
        try:
            werte.add(float(kandidat))
        except ValueError:
            continue
    return werte


def _felder_je_posten(evidence_items: Sequence[Any]) -> List[Dict[str, set]]:
    """Je Evidenzposten die Abbildung Feldname -> gemessene Zahlenwerte."""
    posten: List[Dict[str, set]] = []
    for eintrag in evidence_items or ():
        if isinstance(eintrag, Mapping):
            zeilen = eintrag.get("grounding_surface") or ()
        else:
            zeilen = getattr(eintrag, "grounding_surface", ()) or ()
        felder: Dict[str, set] = {}
        for zeile in zeilen:
            for treffer in _FELD_WERT_MUSTER.finditer(str(zeile)):
                werte = _als_zahlen(treffer.group("wert"))
                if not werte:
                    continue
                feld = treffer.group("feld").rsplit(".", 1)[-1].casefold()
                felder.setdefault(feld, set()).update(werte)
        if felder:
            posten.append(felder)
    return posten


def _lesarten_mit_stellen(roh: str) -> List[Tuple[float, int]]:
    """Die Lesarten von ``_als_zahlen`` samt Nachkommastellen der Schreibweise."""
    text = str(roh or "").strip().rstrip(".,")
    lesarten: List[Tuple[float, int]] = []
    if "," in text and "." in text:
        trenner = "," if text.rfind(",") > text.rfind(".") else "."
        stellen = len(text) - text.rfind(trenner) - 1
        lesarten = [(w, stellen) for w in _als_zahlen(text)]
    elif "," in text or "." in text:
        trenner = "," if "," in text else "."
        roh_dezimal, roh_tausend = text.replace(",", "."), text.replace(trenner, "")
        for kandidat, stellen in ((roh_dezimal, len(text) - text.rfind(trenner) - 1), (roh_tausend, 0)):
            try:
                lesarten.append((float(kandidat), stellen))
            except ValueError:
                continue
    else:
        lesarten = [(w, 0) for w in _als_zahlen(text)]
    return lesarten


def _feldwerte_der_rohflaeche(evidence_items: Sequence[Any]) -> Dict[str, set]:
    """Feldname -> Zahlen aus den Rohflaechen aller Posten, Tabellenzeilen eingeschlossen.

    Die Oberflaechenzeilen fuehren Tabellenzeilen als Dict-Wiedergabe mit
    Doppelpunkt, ``_felder_je_posten`` sieht sie nicht (siehe
    ``_gemessene_zahlen``). Eine keyness-Rate stand damit fuer die Wache nirgends.
    """
    felder: Dict[str, set] = {}

    def _sammle(wert: Any, tiefe: int = 0) -> None:
        if tiefe > 4:
            return
        if isinstance(wert, Mapping):
            for schluessel, x in wert.items():
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    felder.setdefault(str(schluessel).casefold(), set()).add(float(x))
                else:
                    _sammle(x, tiefe + 1)
        elif isinstance(wert, (list, tuple)):
            for x in wert:
                _sammle(x, tiefe + 1)

    for eintrag in evidence_items or ():
        flaeche = eintrag.get("raw_surface") if isinstance(eintrag, Mapping) else getattr(eintrag, "raw_surface", None)
        if isinstance(flaeche, Mapping):
            _sammle(flaeche)
    return felder


def _massname_gedeckt(feld: str, lesarten: List[Tuple[float, int]], feldkarten: Sequence[Dict[str, set]]) -> bool:
    """Check whether any evidence item supports the value under the named measure.

    Accept fields ending in the measure name, such as target_per_million,
    and compare at the precision shown in the answer. Search all evidence
    items so an unrelated earlier result cannot determine the binding.
    """
    for karte in feldkarten:
        for name, werte in karte.items():
            if name != feld and not name.endswith("_" + feld):
                continue
            for wert in werte:
                for zahl, stellen in lesarten:
                    if wert == zahl or ((stellen or feld == "per_million") and _numeric_token_is_supported(
                        str(zahl), {str(wert)}, decimal_places=stellen,
                    )):
                        return True
    return False


def massname_an_feld_gebunden(
    text: str, evidence_items: Sequence[Any]
) -> List[str]:
    """Ein Massname in der Prosa muss auf SEIN Feld zeigen (P2.2/B16).

    Der Ausloeser: das Modell schrieb 'log_ratio minus 2345,3 pmw' und
    zeigte dabei auf ``diff_per_million``, waehrend die Werkzeugausgabe
    ``log_ratio: 5,38`` sauber getrennt lieferte. Keine bestehende Achse
    schlug an, weil die ZAHL korrekt ist und nur ihr NAME falsch. Fuer eine
    Leserin ist das eine falsche Groessenordnung unter einem vertrauten
    Etikett.

    Dieser Punkt war einmal gestrichen, mit einer Messung von 133
    aufgezeichneten Antworten und Praezision 0 aus 1. Die Endabnahme hat
    die Messung widerlegt: in jenen Laeufen gibt es keinen einzigen
    Kollokations-, Kontrast- oder Keyness-Aufruf, ``log_ratio`` kommt in
    null Antworten und null Werkzeugnutzlasten vor. Eine Praezision auf
    einer Population ohne positive Klasse misst nicht die Wache, sondern
    das Korpus. Der Lauf, in dem der Defekt beobachtet wurde
    (h10_split_drift), war gar nicht enthalten.

    Die Wache bindet deshalb an die EVIDENZ, nicht an die Sprache, und
    feuert nur, wenn beides gilt:

    1. Die Zahl steht NICHT unter dem genannten Feld dieses Postens.
    2. Sie steht unter einem ANDEREN Feld DESSELBEN Postens.

    Damit gibt es keinen Verdacht ohne Nachweis: die Meldung kann sagen,
    aus welchem Feld die Zahl stammt. Kommt der Wert in gar keinem Feld
    vor, ist das die Zustaendigkeit der Zahlenanker-Wache, nicht dieser.

    Gemeldet wird ueber die Annotationen, also in das
    ``copilot.grounding``-Ereignis. Der Text wird NICHT angetastet: der
    zerstoerende Kanal war ein eigener Befund und ist eigens repariert
    (siehe ``strike_unbound_numbers``).
    """
    befunde: List[str] = []
    posten = _felder_je_posten(evidence_items)
    if not posten:
        return befunde
    roh = _feldwerte_der_rohflaeche(evidence_items)
    for treffer in massnamen_ohne_rate_davor(str(text or ""), _MASSNAME_MUSTER, _MASSNAME_ZU_FELD,  # Rate davor
            lambda z: _massname_gedeckt("per_million", _lesarten_mit_stellen(z), [*posten, roh])):
        name = treffer.group("name").casefold()
        feld = _MASSNAME_ZU_FELD.get(name) or _MASSNAME_ZU_FELD.get(
            " ".join(name.split())
        )
        if not feld:
            continue
        lesarten = _als_zahlen(treffer.group("zahl"))
        if not lesarten:
            continue
        if _massname_gedeckt(feld, _lesarten_mit_stellen(treffer.group("zahl")), [*posten, roh]):
            continue
        for felder in posten:
            if feld not in felder:
                continue
            if lesarten & felder[feld]:
                break
            # Nur andere MASSE zaehlen als Fremdfeld. Ein Posten faltet
            # alle seine Oberflaechenzeilen zu EINER Abbildung, also liegen
            # rank=1..20, window, min_freq, result_count und
            # node_frequency im selben Posten wie logdice. Ohne diese
            # Einschraenkung kollidiert jede kleine ganze Zahl in
            # fachlich einwandfreier Prosa mit rank, und die Wache meldet
            # eine Fehlbindung, wo keine ist. Der Fixture-Test zur
            # Schwellenangabe bestand vorher nur, weil die Fixture zufaellig
            # kein Feld mit dem Wert 7 hatte.
            fremd = sorted(
                g for g, werte in felder.items()
                if g != feld and g in _MASSFELDER and (lesarten & werte)
            )
            if fremd:
                befunde.append(
                    "massname_zeigt_auf_fremdes_feld: '%s %s' -- der Wert "
                    "steht unter %s, nicht unter %s."
                    % (
                        treffer.group("name"),
                        treffer.group("zahl").rstrip(".,"),
                        fremd[0],
                        feld,
                    )
                )
                break
    return list(dict.fromkeys(befunde))


_UMFELDZAHL_MUSTER = re.compile(
    r"(?:^|[\s,;(\[])f\s*=\s*(?P<zahl>\d[\d.,]*)"
)


def _gemessene_zahlen(evidence_items: Sequence[Any]) -> set:
    """Jede Zahl, die IRGENDEIN Werkzeug in diesem Turn geliefert hat.

    Direkt aus der Rohflaeche, nicht aus den Oberflaechenzeilen.
    ``_felder_je_posten`` liest Text der Form ``feld=wert``, die
    Zeilenwerte stehen dort aber als Dict-Wiedergabe mit Doppelpunkt
    (``rows[0] {'word': 'Beifall', 'f': 946766}``). Genau das ``f``, um
    das es hier geht, faellt damit durch.
    """
    zahlen: set = set()

    def _sammle(wert: Any, tiefe: int = 0) -> None:
        if tiefe > 3:
            return
        if isinstance(wert, bool):
            return
        if isinstance(wert, (int, float)):
            zahlen.add(float(wert))
        elif isinstance(wert, Mapping):
            for x in wert.values():
                _sammle(x, tiefe + 1)
        elif isinstance(wert, (list, tuple)):
            for x in wert:
                _sammle(x, tiefe + 1)

    for eintrag in evidence_items or ():
        if isinstance(eintrag, Mapping):
            flaeche = eintrag.get("raw_surface")
        else:
            flaeche = getattr(eintrag, "raw_surface", None)
        if isinstance(flaeche, Mapping):
            _sammle(flaeche)
    return zahlen


def _fensterdecke(evidence_items: Sequence[Any]) -> Tuple[float, Dict[str, Any]]:
    """Die groesste Kookkurrenz-Obergrenze unter den Kollokationsposten.

    Jedes der ``node_frequency`` Vorkommen des Knotens stellt hoechstens
    ``2 * window`` Fensterplaetze, denn ``window`` ist die HALBE
    Fensterbreite (der Steckbrief schreibt darum „Fenster ±5“). Damit
    kann kein einzelnes Umfeldwort oefter als ``node_frequency * 2 *
    window`` mal im Fenster stehen.

    Es ist ausdruecklich eine obere SCHRANKE, keine Quote. Die
    Werkzeugausgabe warnt zu Recht, dass ``f`` und ``node_frequency``
    nach verschiedenen Schemata zaehlen und ``f / node_frequency`` kein
    Anteil ist. Als Schranke bleibt die Rechnung davon unberuehrt.

    Bei mehreren Kollokationen gilt die GROESSTE Decke, also die
    nachsichtigste. Fehlt ``node_frequency`` oder ``window``, gibt es
    keine Decke: dort ist nichts pruefbar, und eine geratene Grenze waere
    die Erfindung genau der Schranke, die durchgesetzt werden soll.
    """
    decke, quelle = 0.0, {}
    for eintrag in evidence_items or ():
        if isinstance(eintrag, Mapping):
            werkzeug = eintrag.get("tool")
            flaeche = eintrag.get("raw_surface") or {}
        else:
            werkzeug = getattr(eintrag, "tool", "")
            flaeche = getattr(eintrag, "raw_surface", None) or {}
        if werkzeug != "collocate_stats" or not isinstance(flaeche, Mapping):
            continue
        knoten, fenster = flaeche.get("node_frequency"), flaeche.get("window")
        if isinstance(knoten, bool) or isinstance(fenster, bool):
            continue
        try:
            grenze = float(knoten) * 2.0 * float(fenster)
        except (TypeError, ValueError):
            continue
        if grenze > decke:
            decke, quelle = grenze, {"knoten": knoten, "fenster": fenster}
    return decke, quelle


def umfeldzahl_ueber_fensterdecke(
    text: str, evidence_items: Sequence[Any]
) -> List[str]:
    """Report unsupported cooccurrence counts above the window bound.

    The node frequency and window size define the largest possible count.
    Report a value only when every numeric reading exceeds that bound and
    no evidence field contains the value. Preserve the number because an
    incorrect measure label does not establish that the number itself is false.

    Supported corpus frequencies remain available for comparisons alongside
    collocation counts. Without a known node frequency, no bound can be checked.
    """
    decke, quelle = _fensterdecke(evidence_items)
    if decke <= 0:
        return []
    gemessen = _gemessene_zahlen(evidence_items)
    befunde: List[str] = []
    for treffer in _UMFELDZAHL_MUSTER.finditer(str(text or "")):
        lesarten = _als_zahlen(treffer.group("zahl"))
        if not lesarten or not all(wert > decke for wert in lesarten):
            continue
        # Steht die Zahl unter IRGENDEINEM gemessenen Feld, ist sie
        # erhoben und nicht erfunden. Dann ist hoechstens ihr Etikett
        # falsch, und dafuer ist diese Wache nicht zustaendig.
        if lesarten & gemessen:
            continue
        befunde.append(
            "umfeldzahl_ueber_fensterdecke: 'f=%s' liegt ueber der "
            "Obergrenze %s (Knotenfrequenz %s mal Fensterbreite 2x%s) und "
            "kann keine Kookkurrenz im Fenster sein."
            % (
                treffer.group("zahl").rstrip(".,"),
                f"{int(decke):d}",
                quelle.get("knoten"),
                quelle.get("fenster"),
            )
        )
    return list(dict.fromkeys(befunde))


VORLAEUFIG_HINWEIS = (
    "Vorläufig und deterministisch gedeckt. Die Gegenlesung läuft noch."
)
VORLAEUFIG_HINWEIS_EN = (
    "Preliminary and deterministically covered. The second reading is still running."
)


def vorlaeufige_antwort_senden(senden: Any, textbauer: Any) -> str:
    """Die deterministisch gedeckte Antwort ausliefern, bevor geprueft wird.

    Der Grund ist gemessen, nicht vermutet. Am 2026-08-28 kostete ein
    einzelner ``answer_envelope`` 350 Sekunden und ein ``grounding_verdict``
    116, beides wiederholbar. Ein Turn stand nach 21 Minuten noch in der
    zweiten Runde derselben zwei Schritte. Solange nichts angezeigt wird,
    haelt der Harness eine fertige Antwort zurueck, hinter einer Pruefung,
    die ein Vielfaches ihrer Entstehung kostet.

    WAS HIER RAUSGEHT, IST KEIN ROHTEXT. Es ist derselbe Text, den der
    Harness ausliefern wuerde, wenn im selben Moment die Zeit ausginge:
    Referenzen aufgeloest, Zitate gegen die Evidenzzeilen geprueft,
    unbelegte Zahlen gestrichen. Diese Wachen kosten null Modellaufrufe und
    lassen sich nicht ueberspringen, und sie sind es, die die erfundenen
    Zitate frueherer Laeufe gefangen haben, nicht der Verifier.

    Sie setzt KEINEN Verdict und beendet nichts. Die Verifikation laeuft
    unveraendert weiter, und ihr Ergebnis ersetzt diesen Text.

    Eine Vorschau darf die Antwort nie kosten: jeder Fehler hier bleibt
    folgenlos fuer den Turn.
    """
    try:
        text = textbauer()
    except Exception:
        logger.warning("Vorlaeufige Antwort fehlgeschlagen", exc_info=True)
        return ""
    if not isinstance(text, str) or not text.strip():
        return ""
    try:
        senden({
            "event": "copilot.vorlaeufige_antwort",
            "text": text,
            "geprueft": False,
            "hinweis": _t(VORLAEUFIG_HINWEIS, VORLAEUFIG_HINWEIS_EN),
        })
    except Exception:
        logger.warning("Vorlaeufige Antwort nicht gesendet", exc_info=True)
        return ""
    return text


def strukturschritt_buchen(
    orchestrator: Any, schema: Any, payload: Any, ergebnis: Any
) -> Any:
    """Was ein schemagebundener Aufruf wirklich gekostet hat.

    DURCHREICHE: gibt ``ergebnis`` unveraendert zurueck, damit die Buchung
    an der Aufrufstelle keine eigene Zeile braucht (orchestrator.py steht
    auf 7800 von 7800).

    Der Anlass ist eine ungeklaerte Messung. Am 2026-08-28 kostete ein
    Freitext-Entwurf von 316 Zeichen 39 Sekunden, derselbe Inhalt als
    schemagebundenes JSON 350 Sekunden. Faktor neun, bei einem Schema von
    859 Zeichen. Vier Gutachten haben die Ursache diskutiert, alle vier
    sagen, niemand habe gemessen: Prompt-Groesse, erzwungenes Format oder
    ein anderer Transport sind gleichermassen moeglich.

    Gebucht wird nur, was ohnehin zurueckkommt, plus die Groesse der
    gesendeten Nutzlast. Kein zusaetzlicher Aufruf, keine Sekunde.
    """
    try:
        nutzung = (ergebnis or {}).get("usage") or {}
        # ZWEI Nutzungsformate. Chat Completions meldet prompt_tokens,
        # completion_tokens und completion_tokens_details.reasoning_tokens,
        # die Responses-API input_tokens, output_tokens und
        # output_tokens_details.reasoning_tokens. Der Harness benutzt
        # beide Transporte, und genau dieser Unterschied ist einer der
        # Kandidaten fuer die ungeklaerten 350 Sekunden. Eine Buchung, die
        # nur ein Format kennt, meldet dort still None.
        detail = (
            nutzung.get("completion_tokens_details")
            or nutzung.get("output_tokens_details")
            or {}
        )
        eintrag = {
            "schema": (schema or {}).get("name"),
            "nutzlast_zeichen": len(json.dumps(payload, ensure_ascii=False, default=str)),
            "prompt_tokens": (
                nutzung.get("prompt_tokens") or nutzung.get("input_tokens")
            ),
            "completion_tokens": (
                nutzung.get("completion_tokens") or nutzung.get("output_tokens")
            ),
            "reasoning_tokens": detail.get("reasoning_tokens"),
        }
        buch = list(getattr(orchestrator, "_strukturschritte", []) or [])
        buch.append(eintrag)
        orchestrator._strukturschritte = buch[-24:]
    except Exception:
        logger.warning("Strukturschritt nicht gebucht", exc_info=True)
    return ergebnis


def grenzen_anhaengen(text: str, evidenzluecken: Any) -> str:
    """Die Evidenzluecken unter den Text, im ueblichen Format.

    Die Absage trug sie, der Boden zunaechst nicht. Damit haette die
    Reparatur eine Ehrlichkeit gekostet: die Nutzerin erfuhr nicht mehr,
    WAS gefehlt hat. Derselbe Wortlaut und dieselbe Deckelung wie in den
    Familienverfassern (hoechstens sechs, je 220 Zeichen).
    """
    from .grounding_schemas import (
        _normalise_text_list,
        _user_facing_evidence_gap,
    )

    try:
        gaps = _normalise_text_list(
            [
                zeile
                for zeile in (
                    _user_facing_evidence_gap(g) for g in (evidenzluecken or ())
                )
                if zeile
            ],
            max_items=6,
            item_limit=220,
        )
    except Exception:
        logger.warning("Grenzen nicht anhaengbar", exc_info=True)
        return text
    if not gaps:
        return text
    return text + _t("\n\nLimitationen:\n", "\n\nLimitations:\n") + "\n".join(f"- {g}" for g in gaps)


def bodentext_statt_absage(
    angenommene_claims: Any,
    faktenantwort_erlaubt: bool,
    textbauer: Any,
    evidenzluecken: Any = (),
) -> str:
    """Der gedeckte Entwurf statt einer Absage, wenn nichts angenommen wurde.

    Bisher endete dieser Pfad mit: „Die Tool-Evidenz wurde erhoben, aber in
    diesem Lauf liesz sich keine interpretative Endantwort verifizieren.“
    234 Zeichen. Im live gemessenen Turn vom 2026-08-28 nach 65,3 Minuten
    und 17 Modellaufrufen, davon 3775 Sekunden Verifikation, die in sieben
    Aufrufen KEINEN einzigen Claim abgelehnt hat.

    Derselbe Entwurf wird eine Ebene hoeher, bei erschoepfter ZEIT, ohne
    Murren ausgeliefert (``_build_verifier_skipped_answer``). Ein Prinzip,
    das je nach erschoepfter Ressource gilt oder nicht, ist keines. Und die
    Degradation war damit invertiert: wer laenger prueft, bekam weniger.

    Der Text ist gedeckt, nicht roh. Referenzaufloesung, Zitatwache und
    Zahlenanker sind gelaufen, also genau die Wachen, die die drei
    erfundenen Zitate frueherer Laeufe gefangen haben. Der LLM-Verifier war
    es nicht, er wurde unter Zeitdruck uebersprungen.

    Leerer Rueckgabewert heisst: der Aufrufer macht weiter wie bisher.
    """
    if angenommene_claims or faktenantwort_erlaubt:
        return ""
    try:
        text = textbauer()
    except Exception:
        logger.warning("Bodentext fehlgeschlagen", exc_info=True)
        return ""
    if not isinstance(text, str) or not text.strip():
        return ""
    return grenzen_anhaengen(text, evidenzluecken)


def _indexstand_kurz(signatur: str) -> str:
    """Die Indexsignatur als kurzer Hash, nicht als Dateipfad.

    ``_index_fingerprint`` liefert ``<absoluter Pfad>@<mtime_ns>``. Eine
    erste Fassung dieser Zeile hat davon die ersten sechzehn Zeichen
    genommen, und im Antworttext stand dann "Indexstand
    /Users/name/P": ein abgeschnittenes Heimatverzeichnis, das nichts
    identifiziert und den Pfad des Betreibers preisgibt.

    Der Hash leistet, was die Angabe leisten soll: gleicher Index gleicher
    Wert, neu gebauter Index anderer Wert, und ein aufgezeichneter
    Steckbrief laesst sich gegen den Indexstand pruefen, der ihn erzeugt
    hat. ``server`` bildet denselben Wert fuer seine eigene
    Fingerabdruck-Antwort (``_canonical_sha256``).
    """
    roh = str(signatur or "").strip()
    if not roh:
        return ""
    # Schon gehasht? ``extract_raw_surface`` kuerzt den Wert bereits an
    # der Quelle, damit der Dateipfad nicht in den Modellkontext gerissen
    # wird. Ein zweiter Hash daraufhin ergaebe einen ANDEREN Wert, und
    # eine Antwort mit trend_analysis und query_count nebeneinander nannte
    # dann zwei verschiedene Indexstaende fuer denselben Korpus
    # (cf8d3b90e7c2 gegen 1e66f1329f2d). Eine Provenienzangabe, die sich
    # in derselben Antwort widerspricht, ist schlechter als keine.
    if len(roh) == 12 and all(z in "0123456789abcdef" for z in roh):
        return _t("Indexstand ", "Index version ") + roh
    import hashlib

    return _t("Indexstand ", "Index version ") + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:12]


def _indexstand_zeile(posten: Sequence[Any]) -> str:
    """Report the index fingerprint once per answer.

    Prefer a fingerprint supplied by a tool because it identifies the index
    used for that result. Otherwise query the active corpus. Emit no line
    when no fingerprint is available.
    """
    for eintrag in posten or ():
        roh = getattr(eintrag, "raw_surface", None)
        if not isinstance(roh, Mapping):
            continue
        block = roh.get("method")
        if not isinstance(block, Mapping):
            continue
        for schluessel in ("indexFingerprint", "index_fingerprint"):
            wert = str(block.get(schluessel) or "").strip()
            if wert:
                return _indexstand_kurz(wert)
    # Der Korpus, auf dem GERECHNET wurde, nicht der voreingestellte. Die
    # Evidenzposten fuehren ihn in scope.corpus_id. Der Rueckfall fragte
    # get_corpus(None), und auf einem Turn ueber einen anderen Korpus nannte
    # der Steckbrief damit den Stand eines Index, der an der Messung nicht
    # beteiligt war.
    korpus: str | None = None
    for eintrag in posten or ():
        roh = getattr(eintrag, "raw_surface", None)
        if not isinstance(roh, Mapping):
            continue
        bereich = roh.get("scope")
        if isinstance(bereich, Mapping):
            name = str(bereich.get("corpus_id") or "").strip()
            if name:
                korpus = name
                break
    try:
        from .tool_wrappers import _resolve_corpus_index
        from candyconc.services.backend.routes.analysis import (
            _index_fingerprint as _fp,
        )

        wert = str(_fp(_resolve_corpus_index(korpus)) or "").strip()
    except Exception:
        # Ohne Backend gibt es keinen Indexstand. Das ist kein Fehler der
        # Antwort, und eine Ausnahme hier wuerde den GANZEN Steckbrief
        # verschlucken.
        return ""
    return _indexstand_kurz(wert)


def methodensteckbrief_anhaengen(
    text: str, evidence_items: Sequence[Any]
) -> str:
    """Abfrageebene, Faltung, Fenster, Nenner und Scope sichtbar machen.

    P2.3. Die Werkzeuge liefern all das bereits zwingend in ihrem
    Response-Schema, und ``_analysis_provenance_lines`` rendert es seit
    Langem, aber NICHTS zwang zur Ausgabe. Damit stand in der Antwort eine
    Zahl ohne die Angaben, die eine Fachperson braucht, um sie einzuordnen:
    Wortform oder Lemma, gefaltet oder nicht, welcher Nenner, welcher Scope.

    Der Anhang haengt am Politur-Chokepoint und greift damit auf JEDER
    Landung, auch auf dem Verifier-Skip-Pfad, wo der volle Regelsatz nicht
    laeuft. Er kostet keinen Modellaufruf.

    Idempotent: rendert eine Landung dieselben Zeilen bereits selbst, etwa
    ``_build_term_profile_markdown`` unter der Ueberschrift 'Methoden- und
    Scope-Provenienz', bleibt der Text unveraendert. Jeder Fehler laesst den
    Grundtext unangetastet, Telemetrie darf eine Antwort nie kosten.
    """
    grundtext = str(text or "")
    if not grundtext.strip():
        return grundtext
    try:
        from .analysis_grounding import _analysis_provenance_lines
        from .grounding_schemas import EvidenceItem

        posten: List[Any] = []
        for eintrag in evidence_items or ():
            if isinstance(eintrag, Mapping):
                try:
                    kandidat: Any = EvidenceItem(**dict(eintrag))
                except (TypeError, ValueError):
                    continue
            else:
                kandidat = eintrag
            # Ein GESCHEITERTES Werkzeug hat keine Methode beigetragen.
            # _analysis_provenance_lines rendert dafuer eine Fehlerzeile
            # ('lookup_tool (fehlgeschlagen): nicht als Evidenz verwendet'),
            # und die gehoert in die Fehlerbehandlung, nicht unter eine
            # Ueberschrift, die Methode verspricht.
            #
            # Gescheitert heisst 'error', und zwar mit derselben Grenze, die
            # _analysis_provenance_lines selbst zieht. Die erste Fassung
            # verlangte 'success' und liess damit die ehrlichen
            # Zwischenzustaende herausfallen ('not_applicable' bei
            # compare_collocates auf ungepaartem Korpus, 'unavailable' bei
            # similar_words ohne Wort-Thesaurus). Der Analysebericht zeigte
            # deren Provenienzzeile weiter, der Steckbrief nicht: zwei
            # Evidenzoberflaechen, die sich still widersprechen.
            if str(getattr(kandidat, "status", "success") or "success") == "error":
                continue
            posten.append(kandidat)
        zeilen = [
            z.strip() for z in _analysis_provenance_lines(posten) if z and z.strip()
        ]
        if not zeilen:
            return grundtext
        # ERST wenn es Messangaben gibt. Der Indexstand qualifiziert
        # Messungen, er ist keine. Eine Vorfassung haengte ihn
        # unbedingt an, und eine Antwort ganz ohne Werkzeugeinsatz bekam
        # dadurch eine Ueberschrift "Methodensteckbrief" mit einem
        # einzigen Hash darunter: genau das strukturell leere Feld, das
        # der Steckbrief vermeiden soll.
        indexstand = _indexstand_zeile(posten)
        if indexstand and indexstand not in zeilen:
            zeilen.append(indexstand)
        # Doppelt gerendert heisst: die Landung hat den Steckbrief BEREITS.
        # Die Pruefung lief ueber ANY, und eine einzige uebereinstimmende
        # Zeile liess den GANZEN Anhang entfallen, samt der erst danach
        # angehaengten Indexstand-Zeile. Genau die Landungen, die ihre
        # Provenienz selbst drucken (_build_term_profile_markdown), haben
        # den Indexstand deshalb nie bekommen. Massgeblich ist, ob der
        # Grundtext die Ueberschrift schon fuehrt, nicht ob eine Zeile
        # zufaellig auch anderswo vorkommt.
        if (METHODENSTECKBRIEF_UEBERSCHRIFT in grundtext
                or METHODENSTECKBRIEF_UEBERSCHRIFT_EN in grundtext):
            return grundtext
        zeilen = [z for z in zeilen if z not in grundtext]
        if not zeilen:
            return grundtext
        return (
            grundtext.rstrip()
            + "\n\n"
            + _t(METHODENSTECKBRIEF_UEBERSCHRIFT, METHODENSTECKBRIEF_UEBERSCHRIFT_EN)
            + "\n"
            + "\n".join("- " + z for z in zeilen)
        )
    except Exception:
        logger.warning("Methodensteckbrief fehlgeschlagen", exc_info=True)
        return grundtext


def _rueckfrage_bewacht_anhaengen(
    text: str, rueckfrage: str, belegzeilen: Sequence[str], *,
    nutzerfrage: str = "",
) -> Tuple[str, List[Dict[str, str]]]:
    """Die aufgeschobene Rueckfrage durch dieselben Wachen wie die Antwort.

    Sie ist Modelltext und wurde bisher roh ans Ende gehaengt. Hier laeuft
    sie durch Zitatwache und Politur, bevor sie den Text beruehrt.

    Bleibt danach nichts uebrig, entfaellt sie GANZ. Der Vorspann "Offene
    Praezisierung:" ohne Frage dahinter waere schlimmer als keine Frage:
    er kuendigt etwas an, das nicht kommt. Was entfaellt, steht in den
    Annotationen, nicht im sichtbaren Text.
    """
    frage = str(rueckfrage or "").strip()
    if not frage:
        return text, []
    notizen: List[Dict[str, str]] = []
    sauber, entfernte = strike_unsupported_quotes(
        frage, belegzeilen, frage=nutzerfrage)
    if entfernte:
        sauber, gefallene = aussagen_ohne_deckung_streichen(sauber)
        notizen.append({
            "claim_id": "rueckfrage_zitat_ohne_deckung",
            "note": "%d Zitat(e) ohne Deckung aus der Rueckfrage entfernt"
                    % len(entfernte),
        })
        # Dieselbe Sichtbarkeitsluecke wie am Chokepoint: die Anzahl allein
        # sagt nicht, WAS aus der Rueckfrage verschwunden ist.
        notizen.extend(aussagen_annotationen(gefallene))
    sauber, politur_notizen = final_answer_polish(sauber)
    notizen.extend(politur_notizen)
    # Was nach der Wache nur noch aus Platzhaltern und Satzzeichen
    # besteht, ist LEER. Bestand die Rueckfrage allein aus einem
    # ungedeckten Zitat, blieb sonst "Offene Praezisierung: [Beleg fehlt]"
    # stehen: eine Ankuendigung ohne Frage, also genau der Zustand, den
    # der Verzicht auf den Vorspann vermeiden soll.
    rest = sauber.replace(MISSING_EVIDENCE_PLACEHOLDER, " ")
    if not any(z.isalnum() for z in rest):
        sauber = ""
    elif MISSING_EVIDENCE_PLACEHOLDER in sauber:
        # Gemessen am 273M-Lauf vom 2026-08-24, gp_wahlperiode: es blieb
        # "Soll [Beleg fehlt] nach Anzahl der Reden pro Wahlperiode im
        # Subkorpus protocol_lp gezaehlt werden?" stehen. Die Pruefung
        # oben greift nur, wenn NICHTS ausser Platzhaltern uebrig ist,
        # und liess damit jede Frage durch, die daneben noch Text traegt.
        #
        # Im Antworttext ist der Platzhalter richtig: er macht eine
        # Belegluecke sichtbar, statt eine Zahl zu erfinden. In einer
        # RUECKFRAGE ist er etwas anderes. Eine Frage, deren Gegenstand
        # unaufgeloest ist, kann niemand beantworten: der Nutzer weiss
        # nicht, wonach er gefragt wird. Sie entfaellt deshalb ganz, und
        # was entfaellt, steht in den Annotationen.
        sauber = ""
        notizen.append({
            "claim_id": "rueckfrage_platzhalter",
            "note": "Rueckfrage enthielt eine unaufgeloeste Referenz "
                    "und war damit nicht beantwortbar",
        })
    if not sauber.strip():
        notizen.append({
            "claim_id": "rueckfrage_verworfen",
            "note": "Rueckfrage blieb nach der Pruefung leer und entfaellt",
        })
        return text, notizen
    return mit_rueckfrage_am_ende(text, sauber), notizen


# Die Felder eines Kontrollrahmens, die PROSA tragen. Alles andere ist
# Struktur oder Ausfuehrungsdaten und wird nicht angefasst.
_RAHMEN_PROSAFELDER = frozenset({
    "question", "options", "rationale", "reason", "impact", "summary",
    "goal", "steps", "expectedOutcome", "title", "description", "note",
})


def kontrollrahmen_bewacht(
    daten: Any, evidence_items: Sequence[Any], *, frage: str = ""
) -> Any:
    """Die Textfelder eines Kontrollrahmens durch die Zitatwache.

    PLAN, CLARIFY und ACTION tragen MODELLTEXT: goal, steps,
    expectedOutcome, question, options, rationale, summary, reason. Der
    Orchestrator hat sie als copilot.plan / copilot.clarify /
    copilot.action roh an die Oberflaeche gegeben, und das Frontend macht
    daraus eine Assistenten-Nachricht beziehungsweise ein Aktionspanel.

    Die Reparatur der pausierenden Landungen hat nur den RUECKGABEWERT
    gedeckt. Der Rahmen daneben lief weiter ungeprueft: ein erfundenes
    woertliches Zitat in der Rueckfrage erreichte den Nutzer als Ereignis,
    waehrend derselbe Satz im Antworttext zu "[Beleg fehlt]" wurde. Zwei
    Ausgaenge desselben Turns, zwei verschiedene Wahrheiten.

    Nur die Zitatwache, nicht die volle Politur: ein Rahmenfeld ist kein
    Antworttext, Label-Faltung und Methodensteckbrief gehoeren nicht
    hinein.

    ``frage`` ist die Nutzerfrage des Turns, fuer die Ausnahme in
    ``strike_unsupported_quotes``. Der Orchestrator fuehrt sie als
    ``_turn_frage`` und setzt sie an derselben Zeile, an der auch
    ``turn_state.normalized_question`` entsteht: das LOC-Budget von
    ``orchestrator.py`` steht bei 7799 von 7800 Zeilen, und eine eigene
    Zuweisungszeile haette es aufgebraucht.
    """
    belege = evidenz_belegzeilen(evidence_items)

    def _text(wert: Any) -> Any:
        if isinstance(wert, str):
            sauber, entfernte = strike_unsupported_quotes(
                wert, belege, frage=frage)
            return drop_unresolved_sentences(sauber) if entfernte else sauber
        if isinstance(wert, (list, tuple)):
            return [_text(v) for v in wert]
        if isinstance(wert, Mapping):
            # ``steps`` und ``options`` tragen im Prompt-Beispiel OBJEKTE,
            # nicht blosse Zeichenketten: {"label": ..., "id": ...} und
            # {"title": ..., "n": ...}. Ohne diesen Zweig blieb genau die
            # Prosa darin ungeprueft, waehrend die Feldnamen daneben
            # bewacht wurden. Innerhalb eines PROSAfeldes ist alles Prosa,
            # deshalb hier ohne zweite Namensliste.
            return {k: _text(v) for k, v in wert.items()}
        return wert

    try:
        if not isinstance(daten, Mapping):
            return daten
        # NUR die Prosafelder. Eine Vorfassung lief ueber JEDE Zeichenkette
        # des Rahmens, also auch ueber ``payload`` und ``actionType`` der
        # ACTION. Das sind AUSFUEHRUNGSdaten: sie gehen nach der Freigabe
        # in _pending_action und von dort in den Aufruf. Live gemessen:
        #     Modell:      {"query": "\"die jungen Maenner sind hier\""}
        #     Ereignis:    {"query": "[Beleg fehlt]"}
        #     ausgefuehrt: query_count {"query": "[Beleg fehlt]"}
        # Der Konkordanzer fuehrte eine ANDERE Abfrage aus als die, die das
        # Modell komponiert hat, und niemand sah das Original. Eine Wache,
        # die Ausfuehrungsdaten anfasst, ist gefaehrlicher als der Text,
        # den sie schuetzt.
        return {
            k: (_text(v) if k in _RAHMEN_PROSAFELDER else v)
            for k, v in daten.items()
        }
    except Exception:  # Telemetrie darf einen Turn nie kosten.
        logger.warning("Kontrollrahmen-Wache fehlgeschlagen", exc_info=True)
        return daten


def _docset_achse_offen(*, successful_docset_ids: set, docset_attempts: int) -> bool:
    """Der Docset-Deckel bindet an die Achse (Distinkte erfolgreiche
    Docsets), nicht an die Anzahl der Aufrufe.

    Befund 3.3: bis zu sechs distinkte Docsets sind fuer mehrseitige
    Kontraste legitim.
    """
    return len(successful_docset_ids) <= 6
def pending_required_evidence_tools(
    contract: Any,
    allowed_tools: List[str] | None,
    *,
    turn_evidence_items: Sequence[Any],
    capability_unavailable_tools: Any,
    evidence_to_tools: Mapping[str, Sequence[str]],
) -> Tuple[List[str], List[str]]:
    """Fehlende Pflicht-Evidenz und die Werkzeuge, die sie liefern koennten.

    Aus dem Orchestrator ausgelagert: das Modul steht an seinem
    Zeilendeckel, und der Deckel verlangt ausdruecklich Zerlegung statt
    Anhebung. Die Funktion hing nur an zwei schlichten Attributen des
    Turns, die jetzt Parameter sind.
    """
    # Lazy, wie der bestehende Import derselben Fassade weiter unten in
    # diesem Modul: analysis_grounding importiert recipe_runtime nicht,
    # aber der Orchestrator zieht beide, und ein Modulimport hier waere
    # eine zusaetzliche Kante ohne Not.
    from .analysis_grounding import (
        EvidenceItem,
        build_evidence_bundle,
        evidence_kinds_for_item,
        same_corpus_collocation_evidence_gaps,
    )

    evidence_items = [
        EvidenceItem(**dict(item))
        for item in list(turn_evidence_items or [])
        if isinstance(item, dict)
    ]
    bundle = build_evidence_bundle(contract, evidence_items)
    missing = list(bundle.missing_required_evidence or [])
    lexical_collocation_gaps = same_corpus_collocation_evidence_gaps(
        contract,
        evidence_items,
    )
    successful_tool_counts = {
        tool_name: sum(
            item.tool == tool_name
            and str(item.status or "").lower() != "error"
            for item in evidence_items
        )
        for tool_name in {
            item.tool for item in evidence_items if item.tool
        }
    }
    negative_tools = {
        item.tool
        for item in evidence_items
        if str(item.status or "").strip().lower()
        in {"not_applicable", "unsupported", "unavailable"}
    }
    has_content_frequency = any(
        item.tool == "frequency_list"
        and "content_rows" in evidence_kinds_for_item(item)
        for item in evidence_items
    )
    pending_tools: List[str] = []
    unresolved_missing: List[str] = []
    allowed_set = set(allowed_tools or []) - set(
        capability_unavailable_tools
    )
    if lexical_collocation_gaps:
        if (
            any("Kollokationsprofil" in gap for gap in lexical_collocation_gaps)
            and "collocate_stats" in allowed_set
        ):
            pending_tools.append("collocate_stats")
        if (
            any(gap.startswith("Knotenfrequenz") for gap in lexical_collocation_gaps)
            and "query_count" in allowed_set
        ):
            pending_tools.append("query_count")
        if pending_tools:
            return pending_tools, lexical_collocation_gaps
    if not missing:
        return [], []
    successful_docset_ids: set[str] = set()
    docset_attempts = 0
    if contract.analysis_family == "contrast_keyness":
        successful_docset_ids = {
            str(item.raw_surface.get("docset_id") or "").strip()
            for item in evidence_items
            if item.tool == "create_docset"
            and str(item.status or "").strip().lower() == "success"
            and str(item.raw_surface.get("docset_id") or "").strip()
        }
        docset_attempts = sum(
            item.tool == "create_docset" for item in evidence_items
        )
    if (
        contract.analysis_family == "contrast_keyness"
        and "metadata_rows" in missing
        and "metric_rows" in missing
        and {"metadata_values", "create_docset", "keyness"}.issubset(
            allowed_set
        )
        and not successful_docset_ids
        and successful_tool_counts.get("metadata_values", 0) < 2
    ):
        # Discover the comparison values before asking the model to create
        # concrete scopes. Otherwise it has to guess split values and may
        # already emit a terminal keyness call with placeholder docset IDs.
        return ["metadata_values"], missing
    if (
        contract.analysis_family == "contrast_keyness"
        and "metric_rows" in missing
        and {"create_docset", "keyness"}.issubset(allowed_set)
        and (
            "metadata_rows" in bundle.present_evidence
            or successful_docset_ids
        )
    ):
        if len(successful_docset_ids) < 2:
            # Keyness consumes two concrete comparison scopes. Exposing the
            # terminal metric before both live docsets exist forces models to
            # guess identifiers from metadata labels. One successful scope is
            # itself enough state to keep building the missing side even when
            # an intervening metadata call returned an empty row set.
            if _docset_achse_offen(
                successful_docset_ids=successful_docset_ids,
                docset_attempts=docset_attempts,
            ):
                return ["create_docset"], missing
            return [], missing
    if (
        "content_rows" in missing
        and not has_content_frequency
        and "frequency_list" in allowed_set
        and successful_tool_counts.get("frequency_list", 0) < 3
    ):
        # Establish a substantive lexical anchor before contextual search;
        # otherwise a generic function word can become the accidental
        # topic of an open corpus exploration.
        return ["frequency_list"], missing
    for kind in missing:
        candidate_tools = evidence_to_tools.get(kind, ())
        if (
            kind == "content_rows"
            and successful_tool_counts.get("frequency_list", 0) >= 1
            and not has_content_frequency
            and "frequency_list" in allowed_set
        ):
            # Repair an unfiltered function-word list with a content-POS
            # frequency call before exposing unrelated retrieval tools
            # that would need a new, potentially ungrounded search anchor.
            candidate_tools = ("frequency_list",)
        if any(
            tool_name in negative_tools and tool_name in allowed_set
            for tool_name in candidate_tools
        ):
            # A method-specific negative result is evidence that the
            # requested analysis cannot be run on this corpus. Do not force
            # a semantically different metric tool merely to fill a row
            # shape; the final answer should explain the missing premise.
            continue
        unresolved_missing.append(kind)
        for tool_name in candidate_tools:
            if tool_name not in allowed_set:
                continue
            # One argument-level repair is useful when a multi-shape tool
            # returned the wrong evidence (for example POS rows where an
            # open analysis needs lexical rows). A second unsuccessful use
            # is enough; max_steps must not become a retry loop.
            content_frequency_repair = (
                kind == "content_rows"
                and tool_name == "frequency_list"
                and not has_content_frequency
                and successful_tool_counts.get(tool_name, 0) < 3
            )
            if (
                successful_tool_counts.get(tool_name, 0) >= 2
                and not content_frequency_repair
            ):
                continue
            if tool_name not in pending_tools:
                pending_tools.append(tool_name)
    return pending_tools, unresolved_missing


#: Kopfzeile plus Trennzeile einer Markdown-Tabelle, der KEINE Datenzeile
#: folgt.
_LEERE_TABELLE = re.compile(
    r"^(\|[^\n]*\|)[ \t]*\n(\|[ \t:\-|]+\|)[ \t]*\n(?!\s*\|)",
    re.M,
)


def leere_tabelle_fuellen(
    text: str, evidence_items: Sequence[Any]
) -> Tuple[str, str]:
    """Fill an empty result table from matching evidence rows.

    Use the tool's values directly. If no matching evidence exists, remove
    the empty table rather than deliver a heading without results.
    """

    roh = str(text or "")
    treffer = None
    for kandidat in _LEERE_TABELLE.finditer(roh):
        if not _im_codeblock(roh, kandidat.start()):
            treffer = kandidat
            break
    if treffer is None:
        return roh, ""
    kopf = [z.strip() for z in treffer.group(1).strip("|").split("|")]
    zeilen = _metrikzeilen_aus_evidenz(evidence_items)
    gebaut = []
    for rang, zeile in enumerate(zeilen, 1):
        felder = [_tabellenfeld(zeile, name, rang) for name in kopf]
        if not any(feld.strip() for feld in felder):
            # Keine einzige Spalte trifft ein Evidenzfeld. Eine Zeile aus
            # lauter Leerfeldern ist schlechter als gar keine Tabelle: sie
            # sieht nach Inhalt aus und traegt keinen.
            gebaut = []
            break
        gebaut.append("| " + " | ".join(felder) + " |")
    if not gebaut:
        return (
            roh.replace(treffer.group(0), "", 1),
            "leere_tabelle_entfernt",
        )
    ersatz = treffer.group(0).rstrip("\n") + "\n" + "\n".join(gebaut) + "\n"
    return (
        roh.replace(treffer.group(0), ersatz, 1),
        "leere_tabelle_aus_evidenz_gefuellt",
    )


def _im_codeblock(text: str, position: int) -> bool:
    r"""Steht ``position`` innerhalb eines eingezaeunten Codeblocks?

    Eine Pipe-Tabelle in einem ``\`\`\``-Block ist ein BEISPIEL, kein
    Befund. Die erste Fassung dieser Wache hat sie umgeschrieben, gefunden
    von der eigenen Haertung gegen Faelle, die sie nicht anfassen darf.
    """

    return text.count("```", 0, position) % 2 == 1


def _tabellenfeld(zeile: Mapping[str, Any], spalte: str, rang: int) -> str:
    """Ein Tabellenfeld aus einer Evidenzzeile, nach Spaltenname."""

    schluessel = spalte.strip().casefold()
    if schluessel in ("rang", "rank", "#"):
        return str(zeile.get("rank") or rang)
    for kandidat in (schluessel, _SPALTEN_ALIAS.get(schluessel, "")):
        if kandidat and kandidat in zeile:
            wert = zeile[kandidat]
            if isinstance(wert, float):
                return f"{wert:.2f}"
            return str(wert)
    return ""


#: Welche Spaltenueberschrift welches Feld der Werkzeugzeile meint.
_SPALTEN_ALIAS = {
    "wort": "word",
    "kollokat": "word",
    "partner": "word",
    "logdice": "logdice",
    "log-dice": "logdice",
    "ll": "ll",
    "log-likelihood": "ll",
    "mi": "mi",
    "t": "t",
    "score": "score",
    "haeufigkeit": "f",
    "häufigkeit": "f",
    "frequenz": "frequency",
}


def _metrikzeilen_aus_evidenz(
    evidence_items: Sequence[Any],
) -> List[Mapping[str, Any]]:
    """Die obersten Metrikzeilen des juengsten Werkzeuglaufs mit Rangfolge."""

    # ``EvidenceItem`` hat KEIN ``output``. Die Werkzeugausgabe liegt in
    # ``fact_surface`` (vollstaendig) und ``raw_surface`` (Teilmenge). Ein
    # erster Anlauf griff auf ``output`` zu, fand nichts, und entfernte die
    # Tabelle, statt sie zu fuellen: die Wirkung sah nach Erfolg aus, weil
    # der sichtbare Defekt verschwand.
    for item in reversed(list(evidence_items or ())):
        for feld in ("fact_surface", "raw_surface"):
            roh = (
                item.get(feld)
                if isinstance(item, Mapping)
                else getattr(item, feld, None)
            )
            if not isinstance(roh, Mapping):
                continue
            zeilen = roh.get("rows")
            if not isinstance(zeilen, list) or not zeilen:
                continue
            sauber = [
                z for z in zeilen if isinstance(z, Mapping) and "word" in z
            ]
            if sauber:
                return sauber[:10]
    return []


_BELEGZEILEN_KOPF = "### Belegzeilen"
_BELEGZEILEN_KOPF_EN = "### Evidence lines"
_BELEGZEILEN_MAX_JE_ID = 6
_BELEGZEILEN_MAX_IDS = 8
_BELEGZEILEN_MAX_FUSSNOTEN = 6

# Schreibungs-Fußnoten (row_spelling_note.satz): ihre Zeile muss in
# den Anhang, sonst ist die Zahl für den Leser unbelegt (Messung 11).
_FUSSNOTE_ZEILE = re.compile(
    r"Die Zeile „([^“\n]+)“ zählt eine Schreibungsklasse: "
    r"(?:(?:die|den) (\d+) Treffer trägt „([^“\n]+)“"
    r"|von den (\d+) Treffern trägt „[^“\n]+“ selbst (\d+)"
    r"(?:, die Mehrheit trägt „([^“\n]+)“)?)"
)


def _belegzeilen_fussnoten(text: str) -> List[str]:
    """Anhangs-Zeilen für Schreibungs-Fußnoten im Text."""
    zeilen: List[str] = []
    gesehen: set[str] = set()
    for m in _FUSSNOTE_ZEILE.finditer(str(text or "")):
        etikett = m.group(1)
        if etikett in gesehen:
            continue
        gesehen.add(etikett)
        gesamt = m.group(2) or m.group(4) or "?"
        eigen = m.group(5)
        traegt = m.group(3) or m.group(6) or ""
        teil = "- Schreibung „" + etikett + "“: " + gesamt + " Treffer"
        if eigen:
            teil += ", „" + etikett + "“ selbst " + eigen
        if traegt:
            teil += ", Mehrheit trägt „" + traegt + "“"
        zeilen.append(teil)
        if len(zeilen) >= _BELEGZEILEN_MAX_FUSSNOTEN:
            break
    return zeilen


#: Die Zeilennummer einer Belegzeile: "rows[3] ...", 'match[3]="..."', "rank=3".
_ZEILENNUMMER = re.compile(r"^(?:(?:rows|kwic|match)\[(\d+)\]|rank=(\d+))")


def _zitierte_zeilen(text: str, eid: str, item: Mapping[str, Any]) -> List[int]:
    """Select an item's cited rows in reading order.

    Require a text line with the item's chip plus its standalone row label
    or a quoted span from its KWIC context. A mere mention of the search term
    does not select a row. Include identical contexts only once.
    """
    umfeld = "\n".join(z for z in str(text or "").split("\n") if f"[[beleg:{eid}]]" in z)
    roh = item.get("raw_surface")
    reihen = roh.get("rows") if isinstance(roh, Mapping) else None
    if not umfeld or not isinstance(reihen, list):
        return []
    spannen = [(m.start(), m.group(m.lastgroup or 0)) for m in _WOERTLICHES_ZITAT.finditer(umfeld)]
    zitate = [(ort, _zitat_normalisieren(spanne)) for ort, spanne in spannen
              if not _ist_termnennung(spanne, _auslassungssegmente(spanne))]
    stelle: Dict[Any, Tuple[int, int]] = {}
    for nummer, reihe in enumerate(reihen):
        if not isinstance(reihe, Mapping):
            continue
        if reihe.get("left") or reihe.get("right"):
            kontexte = [_zitat_normalisieren(" ".join(str(reihe.get(k) or "") for k in teile))
                        for teile in (("left", "kw", "right"), ("left", "match"))]
            orte, schluessel = [o for o, worte in zitate if any(_folge_ab(worte, k, 0) >= 0 for k in kontexte)], tuple(kontexte[0])
        else:
            etikett = str(reihe.get("word") or reihe.get("ngram") or "")
            fund = re.search(rf"(?<!\w){re.escape(etikett)}(?!\w)", umfeld) if etikett else None
            orte, schluessel = ([fund.start()] if fund else []), nummer
        if orte and schluessel not in stelle:
            stelle[schluessel] = (min(orte), nummer)
    return [nummer for _, nummer in sorted(stelle.values())]


def _belegzeilen_anhang(text: str, evidence_items: Sequence[Any]) -> str:
    """Zeilen der ZITIERTEN Evidenz-Elemente als Anhang (Klasse c,
    Messung 10): ein Chip [[beleg:ID]] ist für den Leser nur prüfbar,
    wenn der Text die Zeilen des Elements trägt. Nur zitierte IDs, je
    Element wenige Zeilen; nicht zitierte Elemente bleiben draußen."""
    zitiert: List[str] = []
    gesehen: set[str] = set()
    for treffer in re.finditer(r"\[\[beleg:([^\]\n]+)\]\]", str(text or "")):
        eid = treffer.group(1).strip()
        if eid and eid not in gesehen:
            gesehen.add(eid)
            zitiert.append(eid)
    if not zitiert:
        fussnoten = _belegzeilen_fussnoten(text)
        if fussnoten:
            return "\n".join([_t(_BELEGZEILEN_KOPF, _BELEGZEILEN_KOPF_EN)] + fussnoten)
        return ""
    nach_id: Dict[str, Any] = {}
    for roh in list(evidence_items or []):
        item = roh.to_dict() if hasattr(roh, "to_dict") else roh
        if isinstance(item, dict) and item.get("id"):
            nach_id[str(item["id"])] = item
    zeilen: List[str] = [_t(_BELEGZEILEN_KOPF, _BELEGZEILEN_KOPF_EN)]
    # Messung 13: substantielle Zeilen (rows/kwic/match) vorziehen. Die
    # Skalare (status/total/query) stehen in der Fläche zuerst, und die
    # Kappe schnitt sonst genau die Belegzeilen weg.
    _substantiell = re.compile(r"^(rows\[|kwic\[|match\[|rank=|Fakten:)")
    # Place items containing evidence rows before pure counts so the display
    # limit preserves the sources of quoted examples.
    zitiert.sort(key=lambda eid: not any(
        _substantiell.match(str(z).strip())
        for z in (nach_id.get(eid) or {}).get("grounding_surface") or ()))
    for eid in zitiert[:_BELEGZEILEN_MAX_IDS]:
        item = nach_id.get(eid)
        if not isinstance(item, dict):
            continue
        flaeche = [
            str(z).strip()
            for z in (item.get("grounding_surface") or [])
            if str(z).strip()
        ]
        substantiell = [z for z in flaeche if _substantiell.match(z)]
        # Die zitierten Zeilen zuerst, der Rest in seiner Reihenfolge (A8.1).
        rang = {n: r for r, n in enumerate(_zitierte_zeilen(text, eid, item))}

        def _rang(zeile: str) -> int:
            m = _ZEILENNUMMER.match(zeile)
            return rang.get(int(m.group(1) or m.group(2)), len(rang)) if m else len(rang)

        substantiell.sort(key=_rang)
        skalare = [z for z in flaeche if not _substantiell.match(z)]
        # Bei einer Zaehlung traegt total die Zahl, status belegt nichts (A3).
        skalare.sort(key=lambda z: not z.startswith("total="))
        quellen = (substantiell[:_BELEGZEILEN_MAX_JE_ID]
                   + skalare[:1])
        if not quellen:
            quellen = [json.dumps(
                item.get("fact_surface") or {}, ensure_ascii=False)[:160]]
        # Der Aufruf ganz: nach 80 Zeichen brach er mitten in der Abfrage ab
        # ("[word=\"zudem\" %c] "), und der Kopf nannte keinen Aufruf mehr (A3).
        kopf = "[{}] {} ({})".format(
            eid, item.get("tool", "?"), str(item.get("query", "") or ""))
        zeilen.append(
            "- " + kopf + ": " + " | ".join(quellen[:_BELEGZEILEN_MAX_JE_ID + 1])
        )
        # Klasse c für Metadatenfelder (Messung 25): die Wertelisten der
        # genannten Inventar-Felder gehören in den Anhang — sonst bleiben
        # Behauptungen über Feldinhalte für den Leser unprüfbar.
        fakten_flaeche = item.get("fact_surface")
        if isinstance(fakten_flaeche, dict):
            werte = fakten_flaeche.get("values")
            if isinstance(werte, dict) and werte:
                inventar = []
                for feld, eintraege in list(werte.items())[:4]:
                    if not isinstance(eintraege, (list, tuple)) or not eintraege:
                        continue
                    liste = ", ".join(str(x) for x in eintraege[:6])
                    mehr = f" (+{len(eintraege) - 6})" \
                        if len(eintraege) > 6 else ""
                    inventar.append(f"{feld}: {liste}{mehr}")
                if inventar:
                    zeilen.append(_t("  Werte: ", "  Values: ") + "; ".join(inventar))
    zeilen.extend(_belegzeilen_fussnoten(text))
    return "\n".join(zeilen) if len(zeilen) > 1 else ""


def politur_mit_zitatwache(
    text: str, evidence_items: Sequence[Any], *, rueckfrage: str = "",
    frage: str = "", ausgewertet: Optional[AbstractSet[str]] = None,
    eigene_zitate_bleiben: bool = False,
) -> Tuple[str, List[str]]:
    """Endpolitur UND Zitatpruefung an EINER Stelle.

    ``eigene_zitate_bleiben=True`` kehrt die Wachen-Regel fuer Texte aus
    dem Deutungspfad um (Diagnose 2026-09-04): eine vorgeschlagene
    Formulierung in Anfuehrungszeichen ist keine Fundstellenbehauptung,
    und die Wache traf zielsicher genau das Lieferstueck, weil sie
    beides nicht unterscheiden kann. Die Ankerungspflicht gilt dort fuer
    ZAHLEN (schon in der Deutungs-Pipeline; der Satz bleibt stehen) und
    fuer FUNDSTELLEN ({{ev:ID}}-Referenzen). Zitate ohne Deckung sind
    eigene Stimme und bleiben; gedeckte Zitate bleiben ebenfalls.

    H11.7, zweite Fassung. Die erste haengte die Wache nur an den
    Verifier-Skip-Pfad. Der Live-Nachweis zeigte, dass das nicht genuegt:
    dieselbe Frage lieferte das Fabrikat erneut aus, weil der fertige Text
    danach noch durch die Endpolitur laeuft und diese jede Landung
    bedient. Eine Wache, die nur einen Zweig deckt, ist keine Wache.

    Sie sitzt jetzt dort, wo laut Architektur GENAU EIN Durchlauf fuer
    jeden fertigen Antworttext stattfindet, egal ueber welche Landung er
    den Orchestrator verlaesst.

    P2.3: Aus demselben Grund haengt hier auch der deterministische
    Methodensteckbrief an. Was auf jeder Landung gelten soll, gehoert an
    die eine Stelle, die jede Landung durchlaeuft.

    Aus demselben Grund haengt hier auch die aufgeschobene Rueckfrage an.
    Der Orchestrator hat sie NACH diesem Aufruf angehaengt, und sie ist
    Modelltext: sie kam aus ``clarification_question`` des Kontrakts, also
    aus einem LLM-Vorlauf. Damit ist der einzige Textteil, der die Antwort
    beendet, an Zitatwache und Politur vorbeigelaufen. Ein erfundenes
    Zitat oder ein unaufloesbarer Marker in der Rueckfrage stand
    ungeprueft in der ausgelieferten Antwort. Ein Chokepoint, den ein
    Aufrufer nachtraeglich umgehen kann, ist keiner.
    """
    belege = evidenz_belegzeilen(evidence_items)
    if eigene_zitate_bleiben:
        bereinigt = str(text or "")
        entfernte: list[ZitatStreichung] = []
    else:
        bereinigt, entfernte = zitate_ohne_deckung_streichen(
            str(text or ""), belege, frage=frage)
    gefallene_aussagen: List[str] = []
    if entfernte:
        bereinigt, gefallene_aussagen = aussagen_ohne_deckung_streichen(
            bereinigt)
    bereinigt = label_doppelung_in_zeile_falten(bereinigt)
    bereinigt, tabellennotiz = leere_tabelle_fuellen(bereinigt, evidence_items)
    poliert, annotationen = final_answer_polish(
        bereinigt, deckung_wache=not eigene_zitate_bleiben)
    # PUNKT 5 der Anforderung vom 2026-08-31: erst die Deutung, dann die
    # Experimente mit ihrem Ergebnis. Der Methodensteckbrief nennt die
    # PARAMETER eines Laufs, das Protokoll nennt, WAS gefragt wurde und WAS
    # herauskam. An zwei Live-Antworten machte der Parameteranhang 56,6
    # Prozent des Textes aus, ohne ein einziges Ergebnis zu nennen.
    #
    # WO DIE ANTWORT AUFHOERT. Beide Anhaenge haengen nur an
    # (``grundtext.rstrip() + "\n\n" + Abschnitt``), der Rumpf bleibt also
    # unveraendert vorn stehen. Diese Marke ueberlebt sie deshalb und
    # sagt spaeter, wo die Vorbehalte hingehoeren: unter die ANTWORT, nicht
    # unter den letzten Anhang.
    _antwortende = len(poliert.rstrip())
    poliert = _experimentprotokoll(poliert, evidence_items, ausgewertet=ausgewertet)
    poliert = methodensteckbrief_anhaengen(poliert, evidence_items)
    # Combine supplementary notices in one paragraph, in a fixed priority order:
    # missing requested evidence, measure inputs, filtered analysis tokens,
    # spelling contributions and promised table rows. Prioritize information
    # needed to interpret the answer correctly.
    #
    # Limit the visible supplement to two notices. Additional findings remain
    # in annotations and the evidence stream. Checks read answer content only,
    # excluding appendices and other checks' notices.
    _antwort = _ohne_schlusshinweise(poliert[:_antwortende])
    _nachtraege: List[str] = []
    _nachtraege.extend(_alle_luecken_saetze(frage, evidence_items))
    _nachtraege.extend(_massgrundlagen_saetze(_antwort, evidence_items))
    _nachtraege.extend(_analysetoken_saetze(_antwort, evidence_items))
    _nachtraege.extend(_schreibungs_saetze(_antwort, evidence_items))
    _nachtraege.extend(_tabellenzusage_saetze(_antwort))
    _offen = [s for s in _nachtraege if s and s not in poliert]
    _zurueckgestellt = _offen[MAX_NACHTRAEGE:]
    _offen = _offen[:MAX_NACHTRAEGE]
    if _offen:
        # UNTER DIE ANTWORT, NICHT ANS ENDE. Ein Vorbehalt schraenkt die
        # Antwort ein, also steht er bei ihr. Hinter dem Steckbrief stand
        # er als Letztes im Text, und die Hausregel sagt: "Der letzte Satz
        # eines Absatzes ist, was die Leserin behaelt. Kein Absatz endet
        # auf seinem eigenen Vorbehalt."
        #
        # Der zweite Gewinn ist eine ehrliche Messung. Der Deckel zaehlt
        # SAETZE, und ein nummeriertes Experiment ("1. Suche ...") sieht
        # fuer jede Satztrennung an ". " wie ein weiterer Vorbehalt aus.
        # Getrennte Bereiche lassen sich getrennt zaehlen.
        _rumpf = poliert[:_antwortende].rstrip()
        _anhaenge = poliert[_antwortende:]
        poliert = f"{_rumpf}\n\n" + " ".join(_offen) + _anhaenge
    # Zweites Gesicht desselben Defekts: entfernt die Zitatwache ALLE Zeilen
    # eines Abschnitts, bleibt eine Ueberschrift ohne Inhalt stehen. Der
    # Methodensteckbrief nennt den Lauf weiterhin, es geht nichts verloren.
    poliert = _ohne_leere_abschnitte(poliert)
    poliert, rueckfrage_notizen = _rueckfrage_bewacht_anhaengen(
        poliert, rueckfrage, belege, nutzerfrage=frage
    )
    # Annotationen sind ABBILDUNGEN, keine Zeichenketten: final_polish_event
    # nimmt ``Sequence[Mapping[str, Any]]`` und final_answer_polish liefert
    # ``{"claim_id": ..., "note": ...}``. Die Zitatwache hat hier von Anfang
    # an einen nackten String angehaengt, und die Massnamen-Bindung hat den
    # Fehler vergroessert statt ihn zu bemerken. Ein Verbraucher, der
    # ``eintrag["note"]`` liest, bekommt bei einem String einen TypeError
    # oder still gar nichts.
    zusatz: List[Dict[str, str]] = []
    # Die Aussagen, die der Zitatwache-Durchlauf oben nach sich gezogen hat.
    # Sie fallen VOR ``final_answer_polish`` und tauchen deshalb in dessen
    # Annotationen nicht auf: dort ist der Platzhalter laengst weg.
    zusatz.extend(aussagen_annotationen(gefallene_aussagen))
    # Was der Deckel aus dem Text genommen hat, geht NICHT verloren. Es
    # wandert in den Evidenzstrom, wo Meta ueber die Antwort hingehoert.
    # Ein Nachtrag, der still verschwindet, waere ein verschobener Defekt.
    for satz in _zurueckgestellt:
        zusatz.append({"claim_id": "nachtrag_ueber_deckel", "note": satz})
    if tabellennotiz:
        zusatz.append({"claim_id": "", "note": tabellennotiz})
    if entfernte:
        zusatz.append({
            "claim_id": "zitat_ohne_deckung_entfernt",
            "note": _t("%d Zitat(e) ohne Deckung entfernt",
                       "%d quotation(s) without support removed") % len(entfernte),
        })
        # WAS gefallen ist, nicht nur WIE VIEL. Die Sammelzeile allein hat
        # eine Messung blind gemacht: der zweite Messarm meldete fuer
        # erklaerroutine 7 gestrichene Aussagen und 8 Zitate, und weder das
        # Feld ``vorschau`` noch die Annotation nannte eine davon. Ob dort
        # Fabrikate oder Tabellenzeilen fielen, liess sich hinterher nicht
        # mehr entscheiden.
        #
        # ``channel: diagnostik`` ist hier PFLICHT, nicht Schmuck. Die
        # Annotationen des Politur-Events landen ueber
        # ``sanitizeGroundingAnnotations`` in ``ChatMessage.vue``, das sie
        # unter jeder Antwort als "Hinweise (n)" ausklappbar rendert. Ohne
        # das Feld stand das gestrichene Fabrikat samt seinem Traegersatz
        # eine Zeile unter der bereinigten Antwort, in derselben
        # Nachrichtenblase: die Wache haette es aus dem Rumpf genommen und
        # sofort wieder ausgeliefert. Die Messung liest den
        # Ereignisstrom, der Leser der Antwort bekommt diese Zeilen nicht.
        for streichung in entfernte[:_ANNOTATION_MAX_STELLEN]:
            zusatz.append({
                "claim_id": "zitat_ohne_deckung_stelle",
                "channel": "diagnostik",
                "note": "Satz: %s | Zitat: %s" % (
                    streichung.satz,
                    streichung.zitat.strip()[:_ANNOTATION_MAX_ZEICHEN],
                ),
            })
    # P2.2: die Massnamen-Bindung meldet, sie loescht nicht. Gemessen wird
    # der Prosateil, der Steckbrief nennt seine Felder selbst korrekt.
    try:
        fehlbindungen = massname_an_feld_gebunden(bereinigt, evidence_items)
    except Exception:  # Telemetrie darf eine Antwort nie kosten.
        logger.warning("Massnamen-Bindung fehlgeschlagen", exc_info=True)
        fehlbindungen = []
    for befund in fehlbindungen:
        zusatz.append({
            "claim_id": "massname_zeigt_auf_fremdes_feld", "note": str(befund),
        })
    # P3 (Runde 2): die Meldung erreicht bisher nur den Evidenzstrom, nicht
    # die Leserin (Messung diachronie-3: zwei harte Fremdfeld-Fehler waren
    # meldbar und stehen trotzdem unmarkiert im Text). F6-konform: die
    # erste Meldung kommt als Standzeile unter die Antwort — markieren,
    # nicht streichen.
    if fehlbindungen and poliert.strip():
        meldung = str(fehlbindungen[0])
        meldung = meldung.split(": ", 1)[-1] if ": " in meldung else meldung
        poliert = poliert.rstrip() + "\n\n" + _t("Hinweis: ", "Note: ") + meldung[:240]
    # Dieselbe Bauart, dieselbe Begruendung: eine Zahl, deren ETIKETT
    # arithmetisch unmoeglich ist, wird gemeldet, nicht gestrichen.
    try:
        umfeldbefunde = umfeldzahl_ueber_fensterdecke(bereinigt, evidence_items)
    except Exception:  # Telemetrie darf eine Antwort nie kosten.
        logger.warning("Fensterdecke fehlgeschlagen", exc_info=True)
        umfeldbefunde = []
    for befund in umfeldbefunde:
        zusatz.append({
            "claim_id": "umfeldzahl_ueber_fensterdecke", "note": str(befund),
        })
    zusatz.extend(rueckfrage_notizen)
    if zusatz:
        annotationen = list(annotationen) + zusatz
    # Klasse c (Messung 10): der Anhang trägt die Zeilen der zitierten
    # Evidenz-Elemente — Chips bleiben für den Leser prüfbar.
    anhang = _belegzeilen_anhang(poliert, evidence_items)
    if anhang:
        poliert = poliert.rstrip() + "\n\n" + anhang
    if is_english():
        # Inside the pipeline the placeholder stays "[Beleg fehlt]", every
        # guard detects that form. The finished English answer shows the
        # English form (glossary: "[evidence missing]").
        poliert = poliert.replace(MISSING_EVIDENCE_PLACEHOLDER, MISSING_EVIDENCE_PLACEHOLDER_EN)
    return poliert, annotationen


# Die Regel, welche Zeilen ein Zitat decken duerfen, liegt in
# grounding_evidence: sie hat ZWEI Konsumenten, diese Wache und die
# Faktenbildung, und eine zweite Kopie waere die naechste Divergenz.
from .grounding_evidence import (  # noqa: E402
    INHALT_SCHLUESSEL as _INHALT_SCHLUESSEL,
    traegt_korpusinhalt as _traegt_korpusinhalt,
    werkzeug_liefert_korpusbeleg as _werkzeug_liefert_korpusbeleg,
)


def evidenz_belegzeilen(evidence_items: Sequence[Any]) -> List[str]:
    """Die sichtbaren Belegzeilen eines Turns, gegen die Zitate pruefen.

    Liegt bei der Zitatlogik statt beim Orchestrator: die beiden gehoeren
    zusammen, und der Orchestrator hat ein Zeilenbudget, das ein
    Architektur-Waechter durchsetzt.
    """
    zeilen: List[str] = []

    def _texte(knoten: Any) -> None:
        stapel = [knoten]
        while stapel:
            k = stapel.pop()
            if isinstance(k, str):
                if k.strip():
                    zeilen.append(k)
            elif isinstance(k, dict):
                # H11.7, dritte Fassung: eine KWIC-Zeile liegt als
                # {"left": ..., "kw": ..., "right": ...} vor. Die Felder
                # EINZELN zu sammeln genuegt nicht -- ein Zitat laeuft
                # ueber alle drei, und die zweite Fassung strich deshalb
                # in einer KWIC-Frage zehn legitime Belegzeilen weg. Die
                # zusammengesetzte Zeile ist das, was der Leser als Beleg
                # sieht, und genau sie muss vergleichbar sein.
                if "kw" in k:
                    zusammen = " ".join(
                        str(k.get(feld) or "").strip()
                        for feld in ("left", "kw", "right")
                    ).strip()
                    if zusammen:
                        zeilen.append(zusammen)
                stapel.extend(k.values())
            elif isinstance(k, (list, tuple)):
                stapel.extend(k)

    def _feld(item: Any, name: str) -> Any:
        # H11.7, vierte Fassung: im Chokepoint kommen die Evidenz-Eintraege
        # als DICTS an, nicht als EvidenceItem. getattr lieferte dort
        # nichts, die Belegzeilen blieben leer, und die Wache strich
        # daraufhin JEDES Zitat -- zwoelf in einem Lauf, keines ueberlebte.
        # Eine Wache ohne Evidenz ist eine Schere.
        if isinstance(item, Mapping):
            return item.get(name)
        return getattr(item, name, None)

    for item in evidence_items or ():
        # Ein GESCHEITERTES Werkzeug hat keinen Beleg beigetragen. Dieselbe
        # Grenze zieht methodensteckbrief_anhaengen bereits. Ohne sie trug
        # die Fehlermeldung das Argument des Modells umformatiert zurueck
        # ("Ungueltig: <Phrase>") und deckte damit das Fabrikat, nachdem
        # alle anderen Wege geschlossen waren.
        if str(_feld(item, "status") or "").strip().casefold() == "error":
            continue
        # Check provenance before the rendered form. A tool can echo supplied text
        # or search documentation without reading the corpus. Such output cannot
        # establish support for a literal corpus quotation.
        if not _werkzeug_liefert_korpusbeleg(_feld(item, "tool")):
            continue
        # Die EIGENE Eingabe des Modells belegt nichts. make_evidence_item
        # haengt die Werkzeugargumente als "tool_args={...}" und den
        # Analyse-Eingabewert an dieselbe Flaeche wie die Korpusbelege,
        # und diese Funktion gab beides an zitat_ist_belegt weiter. Damit
        # liess sich die Zitatwache VOM MODELL aushebeln: wer seine
        # erfundene Phrase als Suchargument uebergibt, deckt sie selbst.
        # Gemessen auf dem HAUPTpfad, gleicher Antworttext, gleiche Wache,
        # nur ein anderes Werkzeugargument:
        #     query="und"        -> Passage [Beleg fehlt].
        #     query="<Fabrikat>" -> Passage "der jungen Maenner sind keine
        #                           Fluechtlinge. Sie sind ruecksichtslose
        #                           Invasoren."
        # Ein Beleg ist, was im KORPUS steht, nicht was das Modell gefragt
        # hat. Das ist der schwerste Fund dieser Kampagne: die Wache, um
        # die alles gebaut ist, war vom Bewachten abschaltbar.
        # HERKUNFT, nicht Zeichenkettenvergleich. Die Vorfassung verglich
        # Belegzeilen mit der Abfrage des Modells, und das war umgehbar:
        # ein Anfuehrungszeichen, ein doppeltes Leerzeichen, die
        # 512-Zeichen-Kuerzung von query_text oder die JSON-Maskierung
        # einer CQL-Abfrage brachen den Vergleich, und das Fabrikat deckte
        # sich wieder selbst. make_evidence_item markiert die Eingabe
        # jetzt beim Anlegen, und Herkunft laesst sich nicht umformatieren.
        eingabe = {str(z) for z in (_feld(item, "eingabe_surface") or [])}

        for zeile in list(_feld(item, "grounding_surface") or []):
            roh = str(zeile or "")
            if not roh.strip() or roh in eingabe or roh.strip() in eingabe:
                continue
            if not _traegt_korpusinhalt(roh.strip()):
                continue
            zeilen.append(roh)
        # payload_preview NICHT: es ist eine Vorschau fuer das Modell und
        # buendelt status, message und die ersten Zeilen. Der
        # message-Anteil traegt bei mehreren Werkzeugen den Suchbegriff
        # zurueck ("Keine Treffer fuer '<Phrase>'"), und darueber deckte
        # sich das Fabrikat erneut selbst. Der rows-Anteil ist ohnehin
        # abgedeckt, weil die Zeilen unten direkt gelesen werden.
        # H11.7, zweite Fassung: fact_surface ist die UNGEKUERZTE
        # Werkzeugausgabe, und dort stehen die KWIC-Zeilen. Die erste
        # Fassung nahm nur die gekuerzte grounding_surface und strich
        # deshalb in einer KWIC-Frage fuenf voellig legitime Belegzeilen
        # weg -- die Antwort verlor ihre Beispiele. Eine Wache, die echte
        # Belege entfernt, ist so schaedlich wie eine, die Fabrikate
        # durchlaesst.
        # Auch hier ohne die Modelleingabe: raw_surface fuehrt "query"
        # auf seiner Namensliste, die Abfrage steht also in BEIDEN
        # Flaechen. Die erste Fassung dieser Reparatur filterte nur
        # grounding_surface, und das Fabrikat kam ueber raw_surface
        # zurueck. Ein Fix an einer von zwei Flaechen ist eine
        # Verschiebung.
        vorher = len(zeilen)
        # NUR die inhaltstragenden Schluessel. Vorher lief der Sammler
        # ueber die GANZE Flaeche, also auch ueber message, query,
        # effective_term und jedes andere Skalarfeld, das ein Werkzeug
        # fuehrt. Ein Zitat belegt sich damit selbst, sobald irgendein
        # Feld den Suchbegriff zurueckspiegelt, und jedes neue Werkzeug
        # kann ein weiteres solches Feld mitbringen. Eine Erlaubnisliste
        # waechst nicht mit fremden Feldern mit.
        for feld in ("fact_surface", "raw_surface"):
            flaeche = _feld(item, feld)
            if not isinstance(flaeche, Mapping):
                continue
            # Eine KWIC-Zeile auf der OBERSTEN Ebene: kwic_context legt
            # left/kw/right nicht in ein Objekt, sondern direkt in die
            # Flaeche. Einzeln gesammelt ergeben sie drei Fragmente, und
            # ein Zitat laeuft ueber alle drei. Die zusammengesetzte
            # Zeile ist das, was der Leser als Beleg sieht.
            if "kw" in flaeche:
                _texte(dict(flaeche))
            else:
                for schluessel in _INHALT_SCHLUESSEL:
                    if schluessel in flaeche:
                        _texte(flaeche.get(schluessel))
        zeilen[vorher:] = [
            z for z in zeilen[vorher:]
            if z not in eingabe and z.strip() not in eingabe
            and _traegt_korpusinhalt(z.strip())
        ]
    return zeilen


#: BLOCK-Kontexte, die Text als Beleg praesentieren, ohne ein
#: Anfuehrungszeichen zu setzen.
#:
#: Die Wache zaehlte AnfuehrungsFORMEN auf, und diese Aufzaehlung kann nicht
#: vollstaendig werden: nach elf Formen fand das zwoelfte Gate sechs weitere
#: Wege, einen erfundenen Korpussatz als Beleg zu praesentieren. Der
#: schwerste war die MARKDOWN-TABELLENZELLE -- genau das Format, das der
#: Systemprompt fuer Belege vorsieht ("Bei >=4 Datenpunkten: Tabelle oder
#: Liste statt Fliesstext", plus ein Beispiel mit Evidenzmarker IN der
#: Zelle). Dazu Code-Fence, eingerueckter Codeblock und Fettung.
#:
#: Hier steht deshalb keine weitere Delimiter-Liste, sondern der Kontext
#: selbst. Fuer alle gilt dieselbe Vorpruefung wie fuer Code- und
#: Kursivspannen: mindestens vier Woerter und kein Zuweisungszeichen, damit
#: die maschinenlesbare Auszeichnung des Harness unberuehrt bleibt.
#:
#: Die eigenen Tabellen des Harness sind davon nicht betroffen: sie werden
#: in grounding_markdown aus ``item.raw_surface["rows"]`` gebaut, ihr Inhalt
#: ist also gedeckt.
_TABELLENZELLE = re.compile(r"(?<=\|)(?P<z>[^|\n]+)(?=\|)")
_EINGERUECKT = re.compile(r"^(?:[ ]{4}|\t)(?P<z>\S[^\n]*)$", re.MULTILINE)
_FETTUNG = re.compile(r"\*\*(?P<z>[^*\n]+?)\*\*")
_FENCE_MARKE = re.compile(r"^\s*(?:```|~~~)", re.MULTILINE)


def _blockspannen(text: str) -> "list[tuple[int, int]]":
    """Die Spannen der Block-Kontexte, ohne Ueberschneidung, sortiert."""
    spannen: list[tuple[int, int]] = []
    for muster in (_TABELLENZELLE, _EINGERUECKT, _FETTUNG):
        for m in muster.finditer(text):
            spannen.append((m.start("z"), m.end("z")))
    # Code-Fences brauchen Zustand: die Zeilen ZWISCHEN zwei Marken.
    marken = [m for m in _FENCE_MARKE.finditer(text)]
    for i in range(0, len(marken) - 1, 2):
        anfang = text.find("\n", marken[i].end())
        if anfang < 0:
            continue
        spannen.append((anfang + 1, marken[i + 1].start()))
    spannen.sort()
    ohne_ueberschneidung: list[tuple[int, int]] = []
    for a, e in spannen:
        if e - a < 12:
            continue
        if ohne_ueberschneidung and a < ohne_ueberschneidung[-1][1]:
            continue
        ohne_ueberschneidung.append((a, e))
    return ohne_ueberschneidung


#: Der Satz, aus dem ein Zitat gestrichen wurde, fuer die Annotation.
#: Weder Trennzeichen noch Anfuehrungsform sind hier gemeint, sondern die
#: Grenze, an der eine Aussage endet.
_SATZGRENZE = re.compile(r"(?:[.!?](?=\s)|\n)")

#: So viele Zeichen eines Traegersatzes stehen in der Annotation. Die
#: Annotation soll zeigen, WAS gefallen ist, nicht die Antwort ein zweites
#: Mal fuehren. Dieselbe Zahl wie ``_compact_text(..., 160)`` in
#: ``claim_rules/_shared``, wo Zitatspannen fuer die Meldung gekuerzt
#: werden. Wie lang die gestrichenen Aussagen des Messarms waren, ist
#: nicht bekannt: genau deshalb steht diese Annotation hier.
_ANNOTATION_MAX_ZEICHEN = 160

#: So viele Streichungen werden EINZELN benannt. Die Sammelzeile nennt die
#: Gesamtzahl weiterhin, es geht also nichts verloren. Der hoechste
#: gemessene Wert eines Turns waren 8 Zitate (erklaerroutine), der Deckel
#: liegt weit darueber und faengt nur den entarteten Fall ab, in dem eine
#: Antwort ohne Belegzeilen jedes ihrer Zitate verliert.
_ANNOTATION_MAX_STELLEN = 20


def aussagen_annotationen(gestrichen: Sequence[str]) -> List[Dict[str, str]]:
    """Je gestrichener Aussage eine Diagnosezeile mit ihrem Satz.

    Dieselbe Bauart und dieselbe Begruendung wie
    ``zitat_ohne_deckung_stelle``: die Sammelzeile nennt die Zahl,
    diese Zeilen nennen den Fall. ``channel: diagnostik`` ist Pflicht,
    sonst rendert ``ChatMessage.vue`` die Zeile unter der Antwort als
    "Hinweise (n)" und liefert die eben gestrichene Aussage in derselben
    Nachrichtenblase erneut aus.

    Der Platzhalter bleibt IM Satz stehen. Er ist die Stelle, an der die
    Referenz nicht aufloesbar war, und ohne ihn zeigt die Zeile den Satz,
    aber nicht den Grund.
    """
    zeilen: List[Dict[str, str]] = []
    for satz in list(gestrichen)[:_ANNOTATION_MAX_STELLEN]:
        knapp = " ".join(str(satz or "").split())
        if len(knapp) > _ANNOTATION_MAX_ZEICHEN:
            knapp = knapp[:_ANNOTATION_MAX_ZEICHEN].rstrip() + " [...]"
        zeilen.append({
            "claim_id": "aussage_ohne_deckung_stelle",
            "channel": "diagnostik",
            "note": "Aussage: %s" % knapp,
        })
    return zeilen


class ZitatStreichung(NamedTuple):
    """Ein gestrichenes Zitat samt dem Satz, in dem es stand."""

    zitat: str
    satz: str


def _satzgrenzen(text: str) -> "list[int]":
    """Die Endpositionen aller Satzgrenzen eines Textes, einmal berechnet.

    Die Vorfassung von ``_satzumgebung`` scannte mit
    ``_SATZGRENZE.finditer(text, 0, anfang)`` je Streichung von vorn, und
    pro Streichung geschah das zweimal (Fragenbezug und Traegersatz). Das
    ist dieselbe Quadratik, die der Docstring von ``_zitat_gedeckt`` mit
    1921 ms fuer eine 83-KB-Antwort als behoben fuehrt. Gemessen an einem
    Text mit 800 ungedeckten Zitaten und 58979 Zeichen -- der entartete
    Fall einer Antwort ohne Belegzeilen, also die fail-closed-Landung:
    739,8 ms gegen 15,4 ms ohne die Satzsuche, und der Verlauf war sauber
    quadratisch (100 Zitate 13,4 ms, 200 49,1 ms, 400 188,6 ms).
    """
    return [grenze.end() for grenze in _SATZGRENZE.finditer(text)]


def _satzspanne(
    text: str, anfang: int, ende: int, grenzen: "Sequence[int] | None" = None
) -> "tuple[int, int]":
    """Anfang und Ende des Satzes, in dem eine Fundstelle liegt."""
    if grenzen is None:
        grenzen = _satzgrenzen(text)
    davor = bisect.bisect_right(grenzen, anfang)
    danach = bisect.bisect_right(grenzen, ende)
    return (
        grenzen[davor - 1] if davor else 0,
        grenzen[danach] if danach < len(grenzen) else len(text),
    )


def _satzumgebung(
    text: str, anfang: int, ende: int, grenzen: "Sequence[int] | None" = None
) -> str:
    """Der ganze Satz um eine Fundstelle, in einer Zeile.

    DER SATZ, nicht ein Zeichenfenster. Die erste Fassung nahm plus minus
    48 Zeichen, wie ``claim_rules/_shared`` es um eine Fundstelle im
    einzelnen Claim tut. Hier ist der Text aber die ganze Antwort, und das
    Fenster griff in den NACHBARsatz: bei "Der Suchbegriff „X“ wurde in 12
    Zeilen untersucht. Ein Beleg lautet ..." fand die Pruefung "Beleg" und
    "lautet" hinter der Satzgrenze und stufte die Scope-Nennung als Befund
    ein. Ein Satz ist die Einheit, in der eine Spanne als Gegenstand oder
    als Beleg gefuehrt wird.
    """
    links, rechts = _satzspanne(text, anfang, ende, grenzen)
    return " ".join(text[links:rechts].split())


def _traegersatz(
    text: str, anfang: int, ende: int, grenzen: "Sequence[int] | None" = None
) -> str:
    """Der Satz um eine Fundstelle, mit der Fundstelle als PLATZHALTER.

    Die Annotation soll zeigen, WO ein Zitat stand, und darf das Zitat
    nicht ein zweites Mal ausliefern. Die erste Fassung nahm den Satz
    unveraendert, und ``ChatMessage.vue`` rendert jede Annotation unter der
    Antwort ("Hinweise (n)"). Gemessen: aus 'Ein Korpusbeleg lautet
    „ruecksichtslose Invasoren marschieren“.' wurde der Rumpf bereinigt,
    und dieselbe Nachrichtenblase trug das Fabrikat samt Traegersatz eine
    Zeile tiefer erneut. Hier steht deshalb der Satz, wie der Leser ihn
    nach der Streichung saehe.
    """
    links, rechts = _satzspanne(text, anfang, ende, grenzen)
    roh = text[links:anfang] + MISSING_EVIDENCE_PLACEHOLDER + text[ende:rechts]
    satz = " ".join(roh.split())
    if len(satz) > _ANNOTATION_MAX_ZEICHEN:
        satz = satz[:_ANNOTATION_MAX_ZEICHEN].rstrip() + " [...]"
    return satz


def strike_unsupported_quotes(
    text: str, oberflaechen: Sequence[str], *, frage: str = ""
) -> tuple[str, list[str]]:
    """Wie ``zitate_ohne_deckung_streichen``, aber nur die Zitate.

    Vier Aufrufer brauchen bloss die Liste der gestrichenen Spannen. Der
    Chokepoint ``politur_mit_zitatwache`` braucht dazu den Satz, aus dem
    jede Spanne verschwand, und nimmt deshalb die Berichtsfassung.
    """
    sauber, streichungen = zitate_ohne_deckung_streichen(
        text, oberflaechen, frage=frage)
    return sauber, [eintrag.zitat for eintrag in streichungen]


def zitate_ohne_deckung_streichen(
    text: str, oberflaechen: Sequence[str], *, frage: str = ""
) -> tuple[str, list[ZitatStreichung]]:
    """Remove literal corpus quotations unsupported by the evidence.

    Apply the deterministic check even when model verification was skipped.
    Individual words occurring in the corpus do not establish that the
    quoted phrase occurs there.
    """
    if not text:
        return text, []
    entfernt: list[ZitatStreichung] = []

    # Die Belegzeilen EINMAL normalisieren, nicht je Zitat neu.
    heuhaufen = [_zitat_normalisieren(o) for o in (oberflaechen or ())]
    # Und die Satzgrenzen EINMAL je Textfassung, nicht je Streichung
    # zweimal. Siehe die Messung an ``_satzgrenzen``. Der Schluessel ist
    # der Text selbst, weil dieser Lauf drei Fassungen sieht (einzeilig,
    # mehrzeilig, Bloecke) und ``id`` nach einer Freigabe wiederverwendet
    # wuerde.
    grenzen_je_text: Dict[str, "list[int]"] = {}

    def _grenzen(fassung: str) -> "list[int]":
        vorhanden = grenzen_je_text.get(fassung)
        if vorhanden is None:
            vorhanden = grenzen_je_text[fassung] = _satzgrenzen(fassung)
        return vorhanden

    def _ersetzen(treffer: "re.Match[str]") -> str:
        # Die erste Gruppe, die getroffen hat. Die Alternation fuehrt je
        # Zitatform eine eigene Gruppe, damit sich die Klammerregeln nicht
        # gegenseitig stoeren.
        gruppen = treffer.groupdict()
        name = next((k for k, v in gruppen.items() if v is not None), "")
        inhalt = gruppen.get(name) or treffer.group(0)
        # Code- und Kursivspannen sind im Haus MASCHINENauszeichnung, nicht
        # Zitatform: die deterministischen Renderer setzen `Zeit` und
        # `total=7` selbst. Zwei solche Spannen in einer Zeile verketten
        # sich ausserdem falsch, und die Wache strich dann die vom Harness
        # ERZEUGTE, gepruefte Auszeichnung -- gemessen an
        # "Gebrauch von `Zeit` im sichtbaren Suchlauf: `total=7` Treffer".
        # Fuer diese Formen zaehlt daher nur, was wie ein Korpussatz
        # aussieht: mindestens vier Woerter und kein Zuweisungszeichen.
        # Die Laenge entscheidet HIER, nicht in der Regex: siehe die
        # Paarungs-Anmerkung an _ZITAT_PAARE.
        if len(inhalt.strip()) < 12:
            return treffer.group(0)
        # Eine Spanne, die eine LEERZEILE oder zu viele Umbrueche
        # ueberspannt, ist kein umbrochenes Zitat, sondern ein unpaariges
        # oeffnendes Anfuehrungszeichen. Siehe ZITAT_MAX_UMBRUECHE.
        if "\n\n" in inhalt or inhalt.count("\n") > ZITAT_MAX_UMBRUECHE:
            return treffer.group(0)
        if name in _MARKUP_GRUPPEN:
            worte = _zitat_normalisieren(inhalt)
            if len(worte) < ZITAT_MINDESTFOLGE or "=" in inhalt:
                return treffer.group(0)
        if _zitat_gedeckt(inhalt, heuhaufen):
            return treffer.group(0)
        # Eine Spanne, die WOERTLICH in der Nutzerfrage steht, ist kein
        # Korpuszitat, sondern der Gegenstand der Frage. Die Wache strich
        # sie trotzdem, weil sie in keiner Belegzeile stehen kann: die
        # Frage ist kein Korpus. Die Regel liegt in ``quote_rules`` und
        # verlangt zusaetzlich, dass der Nahkontext die Spanne als
        # Gegenstand fuehrt und nicht als Befund. Ohne diese zweite
        # Bedingung koennte ein Fragesteller die Wache abschalten, indem
        # er das Fabrikat in seine Frage schreibt.
        ganzer_text = treffer.string
        satzgrenzen = _grenzen(ganzer_text)
        umgebung = _satzumgebung(
            ganzer_text, treffer.start(), treffer.end(), satzgrenzen)
        if _spanne_ist_fragenbezug(inhalt, umgebung, frage):
            return treffer.group(0)
        entfernt.append(ZitatStreichung(inhalt, _traegersatz(
            ganzer_text, treffer.start(), treffer.end(), satzgrenzen)))
        return MISSING_EVIDENCE_PLACEHOLDER

    bereinigt = _WOERTLICHES_ZITAT.sub(_ersetzen, text)
    # Zweiter Lauf ueber Zeilengrenzen. Erst danach, damit einzeilige
    # Zitate von der engeren, sichereren Fassung behandelt werden.
    bereinigt = _WOERTLICHES_ZITAT_MEHRZEILIG.sub(_ersetzen, bereinigt)
    # Dritter Lauf: die BLOCK-Kontexte, die Text als Beleg praesentieren,
    # ohne ein Anfuehrungszeichen zu setzen. Siehe _blockspannen.
    stuecke: list[str] = []
    letzte = 0
    blockgrenzen = _grenzen(bereinigt)
    for anfang, ende in _blockspannen(bereinigt):
        inhalt = bereinigt[anfang:ende]
        worte = _zitat_normalisieren(inhalt)
        if len(worte) < ZITAT_MINDESTFOLGE or "=" in inhalt:
            continue
        if _zitat_gedeckt(inhalt, heuhaufen):
            continue
        if _spanne_ist_fragenbezug(
            inhalt,
            _satzumgebung(bereinigt, anfang, ende, blockgrenzen),
            frage,
        ):
            continue
        stuecke.append(bereinigt[letzte:anfang])
        stuecke.append(MISSING_EVIDENCE_PLACEHOLDER)
        entfernt.append(ZitatStreichung(
            inhalt, _traegersatz(bereinigt, anfang, ende, blockgrenzen)))
        letzte = ende
    if stuecke:
        stuecke.append(bereinigt[letzte:])
        bereinigt = "".join(stuecke)
    return bereinigt, entfernt


def verifier_skipped_answer_text(
    initial_draft: str,
    resolve_draft: Callable[[str], Mapping[str, Any]],
    deterministic_markdown: Callable[[], Any],
    fail_closed: Callable[[str], str],
    quote_surfaces: Sequence[str] = (),
    grund: str = VERIFIER_SKIPPED_NOTE,
    frage: str = "",
) -> str:
    """Deterministischer Antworttext ohne Modellbestaetigung.

    Der Referenz-Pfad laeuft immer: der Modellentwurf wird deterministisch
    gegen die Turn-Evidenz aufgeloest und unbelegte Zahlen werden markiert
    (kein weiterer LLM-Call). Ohne Entwurf faellt der Text auf das
    deterministische Evidenz-Markdown zurueck, zuletzt auf fail-closed.

    ``grund`` benennt, WARUM keine Modellbestaetigung vorliegt. Der
    Vorgabewert ist das Zeitbudget, weil das der aelteste Verbraucher ist.
    Die beiden spaeteren (vorlaeufige Antwort, Rueckfall nach einem
    Verdikt ohne Bestaetigung) reichen ihren eigenen Grund durch. Vorher
    trugen alle drei denselben Satz, und die Telemetrie behauptete ein
    Zeitproblem, wo das Modell schlicht nicht bestaetigt hatte.
    """
    grund = _t(grund, _VERIFIER_NOTE_ENGLISH.get(grund, grund))
    draft = str(initial_draft or "").strip()
    if draft:
        resolution = resolve_draft(draft)
        text = str(resolution.get("text") or "")
        bare_numbers = list(resolution.get("bare_numbers") or [])
        if bare_numbers:
            text = strike_unbound_numbers(text, list(bare_numbers))
        # H6 (B5): Platzhalter-Saetze fallen mit Sammel-Annotation, statt
        # sichtbar im Endtext zu stehen (50%-Wachposten in der Funktion).
        text = drop_unresolved_sentences(text)
        # H7/A1: Wert-Doppelung aus Marker-Einsetzung kollabieren und
        # byte-identische Wiederholzeilen einmalig zeigen (beides callfrei).
        text = collapse_unit_number_doubles(text)
        text = fold_duplicate_lines(text)
        # H8/F1: 'Deutung\nDeutung: ...' — wiederholtes Sektionslabel unter
        # der gleichnamigen Ueberschrift deterministisch falten.
        text = strip_repeated_section_labels(text)
        # Check literal quotations here as well as numbers so the reported
        # verification status describes the checks that actually ran.
        text, entfernte_zitate = strike_unsupported_quotes(
            text, quote_surfaces, frage=frage
        )
        if entfernte_zitate:
            text = drop_unresolved_sentences(text)
        if text.strip():
            # Was IMMER dasteht, traegt keine Auskunft. Was SELTEN dasteht,
            # traegt eine.
            #
            # Hier standen drei Saetze in JEDER Antwort: der Grund, die
            # Zusicherung "Zahlen und Zitate sind deterministisch gegen die
            # sichtbare Tool-Evidenz aufgeloest" und, falls zutreffend, die
            # Zaehlung der entfernten Zitate. Auf die Frage "Zeige mir
            # Kollokationen zu Nachhaltigkeit" las der Nutzer daraufhin
            # sechs Vorbehalte und einen Werkstattbericht ueber einem
            # einzigen Absatz zur Sache.
            #
            # Die ZUSICHERUNG faellt weg: sie stand in jeder Antwort, also
            # trug sie nichts. Die ZAEHLUNG bleibt: sie steht nur, wenn dem
            # ausgelieferten Text wirklich etwas fehlt, das das Modell
            # geschrieben hatte. Ohne sie liest jemand eine Antwort mit
            # einem Loch und erfaehrt den Grund nicht. Ein erster Anlauf
            # hat beides gestrichen, und zwei Tests haben das zu Recht
            # aufgehalten.
            if entfernte_zitate:
                text += (
                    _t("\n\nHinweis: %s. %d Zitat%s ohne Deckung in der "
                       "Evidenz entfernt.", "\n\nNote: %s. %d unsupported quotation%s removed.")
                    % (
                        grund,
                        len(entfernte_zitate),
                        "" if len(entfernte_zitate) == 1 else _t("e", "s"),
                    )
                )
                if not quote_surfaces:
                    text += _t(" Fuer diesen Turn lag keine Belegzeile vor.", " No concordance line was available for this turn.")
                return text.rstrip()
            return text.rstrip() + _t("\n\nHinweis: ", "\n\nNote: ") + grund + "."
    markdown = deterministic_markdown()
    if isinstance(markdown, str) and markdown.strip():
        return markdown.rstrip() + _t("\n\nHinweis: ", "\n\nNote: ") + grund + "."
    return fail_closed(
        grund
        + _t(": es lag kein verifizierbarer Antwortentwurf vor. Die "
           "Tool-Evidenz bleibt im Lauf erhalten.", ": no verifiable draft answer was available. The tool evidence remains available in the run.")
    )

build_context_message = getattr(
    _prompt_helpers,
    "build_context_message",
    lambda _context=None: "",
)
_get_corpus_metadata = getattr(
    _prompt_helpers,
    "_get_corpus_metadata",
    lambda: {},
)

def registry_tool_names() -> List[str]:
    """Alle Tool-Namen der Registry (der volle Werkzeug-Raum des Produkts).

    H9.2: Die prompt-basierte Vorauswahl (``select_tools_for_prompt``,
    Vor-Rezept-Aera) reicht dem Turn oft nur 2-3 Werkzeuge. Die Rezeptwahl
    muss aber gegen den ECHTEN Werkzeug-Raum pruefen — sonst verwirft sie
    einen korrekten Klassifikator-Pick, weil die Stichwort-Vorauswahl die
    Kernwerkzeuge des Rezepts nicht erraten hat (Belegzahl-Frage bekam nur
    run_cqlf_query+kwic_context, frequenz wurde deshalb still zu frei).
    Lazy-Import, damit recipe_runtime ohne Registry importierbar bleibt.
    """
    try:
        from candyconc.tooling.registry import REGISTRY
    except Exception:  # pragma: no cover - Registry ist im Produkt immer da
        return []
    names: List[str] = []
    seen: set = set()
    for tool in REGISTRY:
        if not isinstance(tool, Mapping):
            continue
        name = str((tool.get("function") or {}).get("name") or tool.get("name") or "").strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def expand_tools_for_recipe(
    tools: List[Dict[str, Any]],
    recipe_id: str,
    gated: Collection[str] = (),
) -> List[Dict[str, Any]]:
    """Erweitert den Turn-Tool-Raum um fehlende Werkzeuge des Rezepts.

    Die Stichwort-Vorauswahl kennt die Rezept-Entscheidung nicht; nach dem
    Routing MUSS der Turn die ``kern_tools`` seines Rezepts rufen koennen,
    UND die ``wegbereiter_tools``, mit denen es die Vorbedingung seines
    eigenen Riegels herstellt. Fehlt ein Wegbereiter, entsteht ein
    Deadlock: der Riegel verlangt etwas, das im Raum niemand bauen kann,
    und die Fehlermeldung rät zu einem Werkzeug, das es nicht gibt. Genau
    das war bei 'kontrast' der Fall, in allen 16 gemessenen Anomalien.
    Ergaenzt werden nur Registry-Specs (ohne ``callable``), die weder schon
    im Raum noch capability-gegated sind. Ohne Rezept oder ohne Fehlbestand
    wird die Eingabeliste unveraendert zurueckgegeben.
    """
    recipe = RECIPES_BY_ID.get(str(recipe_id or ""))
    if recipe is None:
        return tools
    gebraucht: Tuple[str, ...] = tuple(
        getattr(recipe, "kern_tools", ()) or ()
    ) + tuple(getattr(recipe, "wegbereiter_tools", ()) or ())
    if not gebraucht:
        return tools
    present = set()
    for tool in tools or []:
        if isinstance(tool, Mapping):
            present.add(
                str((tool.get("function") or {}).get("name") or "").strip()
            )
    missing = [
        name
        for name in gebraucht
        if name and name not in present and name not in set(gated or ())
    ]
    if not missing:
        return tools
    try:
        from candyconc.tooling.registry import REGISTRY
    except Exception:  # pragma: no cover
        return tools
    expanded = list(tools or [])
    for name in missing:
        for tool in REGISTRY:
            if not isinstance(tool, Mapping):
                continue
            tool_name = str(
                (tool.get("function") or {}).get("name") or ""
            ).strip()
            if tool_name != name:
                continue
            spec = {k: v for k, v in tool.items() if k != "callable"}
            expanded.append(spec)
            break
    return expanded


# --------------------------------------------------------------------------- #
# H10/G1: deterministische Schritt-1-Vorplanung (Aufgaben-Werkzeug-Bindung).   #
# Das Rezept kennt seine Kernwerkzeuge, die Frage traegt die Slots (Terme in   #
# Anfuehrungszeichen). Die erste Werkzeug-Runde plant deshalb der Harness      #
# selbst (0 LLM-Planung); die Templates sind reine Rezept-DATEN               #
# (recipes_data: "vorplan"). Fehlt ein Slot, gibt es KEINE Vorplanung und der  #
# Turn laeuft den heutigen Weg (Modellplanung). Nie raten.                     #
# --------------------------------------------------------------------------- #

PREPLAN_CALL_ID_PREFIX = "preplan_"

_PREPLAN_SLOT_KEYS = ("{TERM}", "{TERM2}", "{DATE_FIELD}")

PREPLAN_ABORT_RESULT = {
    "status": "error",
    "reason": "preplan_abort",
    "message": (
        "Vorgeplante Runde abgebrochen; die Planung uebernimmt wieder das "
        "Modell."
    ),
}


def unanswered_tool_calls(
    planned: Sequence[Mapping[str, Any]], history: Iterable[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """Geplante Calls ohne Tool-Ergebnis in der Historie."""
    beantwortet = {
        str(entry.get("tool_call_id") or "")
        for entry in list(history)
        if entry.get("role") == "tool"
    }
    return [
        dict(call)
        for call in planned
        if str(call.get("id") or "") not in beantwortet
    ]


CLARIFY_ZUSATZ_NOTE = lt(
    "Der Kontrakt wollte nur zurückfragen. Der Turn analysiert stattdessen "
    "unter genannten Annahmen weiter; die Rückfrage steht am Ende der "
    "Antwort.",
    "The contract only wanted to ask back. The turn continues the analysis "
    "under stated assumptions instead, the question stands at the end of the "
    "answer.",
)

_CLARIFY_FALLBACK = (
    "Welche für die Analyse wesentlichen Angaben soll ich verwenden?"
)
_CLARIFY_FALLBACK_EN = "Which details essential for the analysis should I use?"


def clarify_als_zusatz(
    contract: Any, available_tools: Sequence[str]
) -> Tuple[bool, str]:
    """``mode=clarify`` in eine Analyse mit angehaengter Rueckfrage wandeln.

    Rueckgabe ``(weiter, text)``. Bei ``weiter`` ist ``text`` die
    Rueckfrage, die ans ENDE der fertigen Antwort gehoert, und der
    Kontrakt steht auf ``tool_analysis``. Sonst ist ``text`` die
    vollstaendige Rueckfrage-Landung.

    Die Hausregel lautet "unter genannten Annahmen antworten, eine
    praezisierende Rueckfrage hoechstens ZUSAETZLICH am Ende"
    (``prompt_layout`` V2). Der Code hat den Turn hier trotzdem beendet:
    gemessen mit qwen3.8-27b kam die vollstaendig beantwortbare
    Profil-Frage der eingefrorenen H10-Suite als blosse Gegenfrage ohne
    eine einzige Zahl zurueck. Ohne Werkzeuge gibt es nichts zu
    analysieren, dann bleibt die Rueckfrage die ehrliche Landung.
    """
    frage = str(getattr(contract, "clarification_question", "") or "").strip()
    werkzeuge = [str(name) for name in available_tools if str(name)]
    if not werkzeuge:
        return False, frage or _t(_CLARIFY_FALLBACK, _CLARIFY_FALLBACK_EN)
    contract.mode = "tool_analysis"
    contract.needs_clarification = False
    if not contract.allowed_tools:
        contract.allowed_tools = werkzeuge
    return True, frage


def final_polish_event(
    analysis_family: str, annotations: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """``copilot.grounding``-Event der Politur-Annotationen."""
    return {
        "event": "copilot.grounding",
        "grounding": {
            "analysis_family": analysis_family,
            "verdict": "final_polish",
            "rejected_claim_count": 0,
            "annotations": list(annotations),
            "ts": int(time.time() * 1000),
        },
    }


def mit_rueckfrage_am_ende(text: str, rueckfrage: str) -> str:
    """Aufgeschobene Rueckfrage NACH die Antwort haengen, nie an ihre Stelle."""
    frage = str(rueckfrage or "").strip()
    if not frage or not str(text or "").strip() or frage in text:
        return text
    return text.rstrip() + "\n\n" + _t("Offene Präzisierung: ", "Open clarification: ") + frage


def preplan_with_contract(
    recipe_id: str,
    question: str,
    card: Mapping[str, Any] | None,
    *,
    available_tools: Sequence[str],
    gated_tools: Mapping[str, Any] | None,
    contract_tools: Sequence[str] | None,
    auslassungen: List[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Vorplan der ersten Runde, gegen den Kontrakt abgeglichen (H11.4).

    Rueckgabe ``(calls, erweiterte_kontrakt_tools)``. Die zweite Liste ist
    leer, wenn der Kontrakt unangetastet bleibt. Die Rueckgabe bleibt
    zwei-elementig: ausgelassene Vorplan-Eintraege sammelt die optionale
    Liste ``auslassungen``, damit der Aufrufer sie sichtbar machen kann,
    ohne dass ein drittes Tupel-Element jeden Aufrufer bricht.

    Der Vorplan IST die Bindung von Aufgabe an Werkzeug und ist lesend. Ein
    Kontrakt OHNE jede Werkzeugangabe hat nichts entschieden und darf den
    Vorplan nicht verhungern lassen: sonst plant das Modell frei und
    beantwortet eine Zaehlfrage mit einer Frequenzliste (gemessen an
    ``h10_freq_frau``, qwen3.8-27b). Eine ausdrueckliche Werkzeugliste ist
    dagegen eine Entscheidung und bleibt unangetastet, ebenso die
    Capability-Gates und die Werkzeugliste des Turns.
    """
    kwargs = {
        "available_tools": available_tools,
        "gated_tools": gated_tools,
        "auslassungen": auslassungen,
    }
    calls = preplanned_tool_calls(
        recipe_id, question, card,
        allowed_tools=(list(contract_tools) if contract_tools is not None else None),
        **kwargs,
    )
    if calls or contract_tools is None:
        return list(calls or []), []
    ungefiltert = preplanned_tool_calls(
        recipe_id, question, card, allowed_tools=None, **kwargs
    )
    if not ungefiltert:
        return [], []
    termgebunden = _plan_ist_termgebunden(ungefiltert, question)
    if contract_tools and not termgebunden:
        # Eine ausdrueckliche Werkzeugliste ohne Termbezug ist eine
        # Entscheidung des Kontrakts (ein semantischer Kontrakt darf auf
        # semantische Werkzeuge einschraenken) und bleibt unangetastet.
        return [], []
    namen = [
        name
        for name in (
            str((call.get("function") or {}).get("name") or "")
            for call in ungefiltert
        )
        if name
    ]
    logger.warning(
        "Kontrakt-Werkzeuge %s decken den Vorplan (%s) nicht; der Vorplan "
        "gilt (%s).",
        list(contract_tools) or "[leer]",
        ", ".join(namen),
        "termgebunden" if termgebunden else "Kontrakt nannte nichts",
    )
    return list(ungefiltert), sorted(set(list(contract_tools) + namen))


def _plan_ist_termgebunden(
    calls: Sequence[Mapping[str, Any]], question: str
) -> bool:
    """Traegt der Vorplan einen Term AUS DER FRAGE in seinen Argumenten?

    Nur dann ist die Bindung von Aufgabe an Werkzeug eindeutig genug, um
    eine ausdrueckliche Kontrakt-Werkzeugliste zu ergaenzen: die Frage
    nennt den Gegenstand, und das Werkzeug muss genau diesen Gegenstand
    behandeln. Gemessen an ``h10_freq_frau`` — der Kontrakt liess nur
    ``frequency_list`` zu, die Frage verlangte die Zaehlung von ‚Frau‘,
    und die Antwort wurde eine generische Top-10-Liste.
    """
    terme = {term.casefold() for term in extract_primary_terms(question)}
    if not terme:
        return False
    for call in calls:
        roh = (call.get("function") or {}).get("arguments")
        if not isinstance(roh, str):
            continue
        try:
            args = json.loads(roh)
        except (TypeError, ValueError):
            continue
        for wert in args.values() if isinstance(args, dict) else []:
            if isinstance(wert, str) and wert.casefold() in terme:
                return True
    return False


def plan_recipe_first_round(
    recipe_id: str,
    question: str,
    card: Mapping[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """Konkrete Schritt-1-Tool-Calls des Rezepts (Templates gefuellt).

    Ergebnis: Liste von ``{"tool": name, "args": dict}`` in
    Datenreihenfolge. Leer, wenn das Rezept keine Vorplanung traegt oder
    ein benoetigter Slot fehlt ({TERM}/{TERM2} aus den Anfuehrungszeichen
    der Frage, {DATE_FIELD} aus der Korpus-Karte). Teilplaene gibt es
    nicht: fehlt EIN Slot, plant das Modell die ganze Runde.
    """
    try:
        recipe = get_recipe(str(recipe_id or ""))
    except Exception:
        return []
    vorplan = tuple(getattr(recipe, "vorplan", ()) or ())
    if not vorplan:
        return []
    # H10/G3: der Vorplan eines Rezepts mit meta_axis-Vorbedingung (kontrast)
    # ist der SUCHDEFINIERTE Pfad (Docsets per Suche). Er plant nur vor, wenn
    # dieser Pfad aktiv ist: zwei Anfuehrungs-Terme in Vergleichskonstruktion
    # und KEINE kontrastierbare Metadaten-Achse in der Karte. Achsen-Kontraste
    # behalten die Modellplanung (heutiger Weg), Split-QA bleibt Split-QA.
    requires = str(
        dict(getattr(recipe, "precondition", {}) or {}).get("requires", "")
        or ""
    )
    if requires == "meta_axis" and not _search_contrast_preplan_active(
        question, card
    ):
        return []
    terms = extract_primary_terms(question)
    slots: Dict[str, str] = {}
    if terms:
        slots["{TERM}"] = terms[0]
    if len(terms) > 1:
        slots["{TERM2}"] = terms[1]
    date_fields = [
        str(f)
        for f in (card or {}).get("date_fields") or []
        if str(f).strip()
    ]
    if date_fields:
        slots["{DATE_FIELD}"] = date_fields[0]
    planned: List[Dict[str, Any]] = []
    for entry in vorplan:
        tool = str(entry.get("tool", "") or "").strip()
        if not tool:
            return []
        args: Dict[str, Any] = {}
        for key, value in dict(entry.get("args", {}) or {}).items():
            if isinstance(value, str) and value in _PREPLAN_SLOT_KEYS:
                if value not in slots:
                    return []
                args[str(key)] = slots[value]
            else:
                args[str(key)] = value
        planned.append({"tool": tool, "args": args})
    return planned


def plan_free_mode_first_round(question: str) -> List[Dict[str, Any]]:
    """Grundevidenz-Vorplanung des FREIEN Modus (H11/B1, rezeptlos).

    Enthaelt die Frage GENAU EINEN Anfuehrungs-Term
    (``extract_primary_terms``), ist ``query_count(query=TERM)`` die
    deterministische Runde 1: jeder Turn mit benanntem Gegenstand steht auf
    Grundevidenz, bevor das Modell spricht (Rueckfragen statt Antwort
    verhungern strukturell, jede Todeslandung hat Substanz). Kein Term oder
    mehrere Terme -> keine Vorplanung (heutiges Verhalten, nie raten).
    """
    terms = extract_primary_terms(question)
    if len(terms) != 1:
        return []
    # F-66 (2026-09-04): Kollokationsfragen („Welche Wörter treten neben X
    # auf") bekommen ihren collocate_stats DETERMINISTISCH in Runde 1 —
    # sonst antwortet das Modell textonly und der Deutungs-Call sieht ein
    # leeres Paket (Live-Befund F7-Smoke).
    if re.search(r"\bneben\b", question.casefold()):
        return [
            {"tool": "collocate_stats", "args": {"term": terms[0]}},
            {"tool": "query_count", "args": {"query": terms[0]}},
        ]
    return [{"tool": "query_count", "args": {"query": terms[0]}}]


# Token-Attribute des Index. Ein Vorplan-Eintrag BENENNT hoechstens eines,
# und ueber welches Argument, steht in _EBENENARGUMENT (frequency_list ueber
# group_by, collocate_stats/keyness/ngram_frequency ueber attribute). Die
# uebrigen Vorplan-Argumente (query, term, fields, date_field, label, window,
# min_freq, limit) sind Werte oder Meta-Felder, keine Attributnamen.
_TOKEN_ATTRIBUTE = frozenset({"word", "lemma", "pos", "morph", "ent", "rel"})


def unbrauchbares_vorplan_attribut(
    card: Mapping[str, Any] | None,
    args: Mapping[str, Any],
    *,
    tool_name: str,
) -> str:
    """Return why a planned attribute operation cannot provide a result, or empty.

    Use the tool's entry in _EBENENARGUMENT to find its requested attribute.
    Reject attributes listed as constant, even if the same corpus card also
    lists them as available. If an attribute list is supplied, also reject
    missing token attributes. Metadata fields use their separate inventory.
    With no attribute inventory, leave availability undecided.
    """
    argument = _EBENENARGUMENT.get(str(tool_name or ""), "")
    if not argument:
        return ""
    attribut = args.get(argument)
    if not isinstance(attribut, str) or not attribut.strip():
        return ""
    attribut = attribut.strip()
    karte = card or {}
    konstant = karte.get("constant_attributes")
    if isinstance(konstant, (list, tuple)) and attribut in {
        str(item) for item in konstant
    }:
        return f"{attribut} ist einwertig, die Gruppierung ergaebe eine Zeile"
    vorhanden = karte.get("attributes")
    if (
        attribut in _TOKEN_ATTRIBUTE
        and isinstance(vorhanden, (list, tuple))
        and vorhanden
        and attribut not in {str(item) for item in vorhanden}
    ):
        return f"{attribut} ist in diesem Korpus nicht annotiert"
    return ""


def preplanned_tool_calls(
    recipe_id: str,
    question: str,
    card: Mapping[str, Any] | None,
    *,
    available_tools: Collection[str],
    gated_tools: Collection[str] = (),
    allowed_tools: Collection[str] | None = None,
    auslassungen: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Dispatch-fertige Schritt-1-Tool-Calls oder ``[]``.

    Ohne ``recipe_id`` (freier Modus) plant ``plan_free_mode_first_round``
    (H11/B1), sonst das Rezept-Template. Es laufen NUR ausfuehrbare Calls:
    der Werkzeugname muss im verfuegbaren Raum liegen, darf nicht
    capability-gegated sein und muss (bei aktivem Kontrakt) im erlaubten
    Bundle stehen. Nicht ausfuehrbare Templates fallen still aus dem Plan
    (nie ein vorgeplant-blockierter Call, z.B. query_count neben
    collocate_stats, wenn das Kontrakt-Bundle nur letzteres erlaubt).
    Zusaetzlich faellt ein Eintrag heraus, dessen Ebenen-Attribut die
    Korpus-Karte als einwertig oder als nicht annotiert ausweist
    (``unbrauchbares_vorplan_attribut``). Der Grund geht in die Log-Zeile
    UND, wenn der Aufrufer eine Liste ``auslassungen`` mitgibt, in diese:
    ein Serverlog erreicht weder den SSE-Strom noch die Messdateien des
    Laeufers, und der Befund lautete, dass die Auslassung stumm ist.
    Bleibt nichts uebrig, gibt es KEINE Vorplanung und der Turn laeuft den
    heutigen Weg.
    """
    planned = (
        plan_recipe_first_round(recipe_id, question, card)
        if str(recipe_id or "").strip()
        else plan_free_mode_first_round(question)
    )
    if not planned:
        return []
    available = {str(name) for name in (available_tools or [])}
    gated = {str(name) for name in (gated_tools or ())}
    allowed = (
        {str(name) for name in allowed_tools}
        if allowed_tools is not None
        else None
    )
    uebrig: List[Dict[str, Any]] = []
    for entry in planned:
        if (
            entry["tool"] not in available
            or entry["tool"] in gated
            or (allowed is not None and entry["tool"] not in allowed)
        ):
            continue
        grund = unbrauchbares_vorplan_attribut(
            card, entry.get("args") or {}, tool_name=entry["tool"]
        )
        if grund:
            # Nicht stumm: die Karte verwirft einwertige Attribute schon,
            # und ohne diese Zeile bliebe unsichtbar, dass ein geplanter
            # Call deshalb gar nicht erst lief.
            satz = _t("Vorplan-Eintrag {}({}) ausgelassen: {}",
                      "Preplanned call {}({}) skipped: {}").format(
                entry["tool"],
                json.dumps(entry["args"], ensure_ascii=False),
                grund,
            )
            logger.info("%s", satz)
            # Dieselbe Funktion laeuft in preplan_with_contract zweimal
            # (gefiltert und ungefiltert), der Satz waere sonst doppelt.
            if auslassungen is not None and satz not in auslassungen:
                auslassungen.append(satz)
            continue
        uebrig.append(entry)
    planned = uebrig
    if not planned:
        return []
    return [
        {
            "id": f"{PREPLAN_CALL_ID_PREFIX}{pos}",
            "type": "function",
            "function": {
                "name": entry["tool"],
                "arguments": json.dumps(entry["args"], ensure_ascii=False),
            },
        }
        for pos, entry in enumerate(planned, start=1)
    ]


# --------------------------------------------------------------------------- #
# H10/G3: suchdefinierte Kontraste. Die kontrast-Vorbedingung (meta_axis)      #
# erzwang die Fehlantwort, obwohl create_docset(query=...) beide Seiten ohne   #
# Metadaten-Achse bauen kann (der Kurzschluss-Text bot den Weg selbst an).     #
# Nennt die Frage ZWEI Terme in Anfuehrungszeichen in einer Vergleichs-        #
# konstruktion, gilt die Vorbedingung als ueber den Docset-per-Suche-Pfad      #
# ERFUELLT: kein Kurzschluss, Runde 1 plant beide create_docset-Calls          #
# deterministisch vor, das Briefing broadcastet den keyness-Folgeweg.          #
# --------------------------------------------------------------------------- #

# Vergleichskonstruktionen: vs/versus/gegen(ueber), Vergleich(e)/verglichen,
# unterscheiden/Unterschied, kontrastieren, "als Teilmengen", "typisch fuer".
_SEARCH_CONTRAST_PATTERN = re.compile(
    r"(?<!\w)(?:vs\.?|versus|gegen)(?!\w)"
    r"|gegen(?:ü|ue)ber|vergleich|verglichen|unterschied|unterscheid"
    r"|kontrast|teilmenge|typisch f(?:ü|ue)r",
    re.IGNORECASE,
)


def is_search_defined_contrast(question: str) -> bool:
    """ZWEI suchdefinierte Seiten: >=2 Anfuehrungs-Terme + Vergleichsmarker.

    Rein deterministisch (0 Calls). Ein Term allein oder eine Frage ohne
    Vergleichskonstruktion ist KEIN suchdefinierter Kontrast; dort bleibt
    das heutige Verhalten (ehrlicher Kurzschluss bzw. Achsenweg).
    """
    text = str(question or "")
    if not text.strip():
        return False
    if len(extract_primary_terms(text)) < 2:
        return False
    return _SEARCH_CONTRAST_PATTERN.search(text) is not None


def search_contrast_briefing_note(terms: Sequence[str]) -> str:
    """Briefing-Hinweis des suchdefinierten Kontrasts (Folgeweg-Broadcast)."""
    pair = " vs ".join(f"'{str(t)}'" for t in list(terms)[:2])
    return (
        f"Suchdefinierter Kontrast ({pair}): beide Vergleichsseiten sind "
        "suchdefinierte Teilmengen, keine Metadaten-Achse. Je Term ein "
        "create_docset(query=Term, label=Term), danach "
        "keyness(target_docset_id=A, reference_docset_id=B) mit den "
        "zurückgegebenen docset_ids. Effektgrößen berichten (log_ratio mit "
        "CI plus per_million beidseitig) und Robustheit ansprechen: "
        "Dispersion/Dokumentstreuung der Top-Keywords (Einzeldokument-"
        "Dominanz benennen)."
    )


def _search_contrast_preplan_active(
    question: str, card: Mapping[str, Any] | None
) -> bool:
    """Gate der kontrast-Vorplanung: NUR der suchdefinierte Pfad plant vor.

    True nur, wenn (a) die Frage einen suchdefinierten Kontrast traegt,
    (b) die Karte ihr Achsen-Inventar POSITIV ausweist und darin KEINE
    kontrastierbare Achse liegt (Achsen-Kontraste behalten die
    Modellplanung des heutigen Wegs, auch wenn Achsenwerte zitiert werden)
    und (c) keine eingeloeste Split-QA vorliegt (dort sind die zitierten
    Werte Partitionsnamen, keine Suchterme).
    """
    if not is_search_defined_contrast(question):
        return False
    if not isinstance(card, Mapping) or "meta_fields" not in card:
        return False
    axes = card.get("meta_axes")
    if not isinstance(axes, list):
        return False
    entries = [a for a in axes if isinstance(a, Mapping)]
    if any(a.get("kind") == "axis" for a in entries):
        return False
    technical = [a for a in entries if a.get("kind") == "technical"]
    if technical and is_explicit_split_qa_request(question):
        return False
    return True


# --------------------------------------------------------------------------- #
# H10/G1 (LOC-Naht): die System-Note der Vertragsevidenz-Schleife und zwei     #
# reine Frage-Parser, aus dem Orchestrator hierher gezogen. Die Absaetze der   #
# Note tragen den Wortlaut von damals.                                         #
# --------------------------------------------------------------------------- #

_EVIDENCE_NOTE_DOCSET_HINT = (
    "Erzeuge mit `create_docset` genau eine noch fehlende Vergleichsseite "
    "aus einem sichtbaren Metadatenwert; verwende dafür `filters` und "
    "merke dir die zurückgegebene `docset_id`. "
)

# Explain only the evidence kinds that are missing from this turn.
_EVIDENCE_NOTE_ABSAETZE: Dict[str, str] = {
    "lexical_frequency_rows": (
        "Für `lexical_frequency_rows` nutze `frequency_list` mit "
        "`group_by=word` oder `group_by=lemma`; `group_by=pos` zählt dafür "
        "nicht."
    ),
    "content_rows": (
        "Für `content_rows` nutze eine Wort-/Lemmaliste mit "
        "`pos=NOUN`, `PROPN`, `VERB` oder `ADJ` oder einen fachlich "
        "motivierten semantischen, Cluster- oder Dokumenttreffer; eine "
        "unbereinigte Funktionswortliste zählt nicht."
    ),
    "contextual_rows": (
        "Für `contextual_rows` nutze einen fachlich motivierten "
        "KWIC-, Dokument-, semantischen oder Cluster-Treffer; der "
        "Suchanker muss aus der Nutzerfrage oder bereits sichtbarer "
        "Lexik stammen."
    ),
}


def contract_evidence_note(
    missing_evidence: Sequence[str],
    forced_tools: Sequence[str] | None,
    anchor_guidance: str,
) -> str:
    """System-Note, wenn das Modell mit fehlender Pflichtevidenz antworten will.

    Sie steht am Ende der Werkzeugphase. Die Folgenotiz nach jedem
    Werkzeugschritt ist entfallen, siehe den Kommentar an der Werkzeugrunde
    im Orchestrator.
    """
    missing = [str(name) for name in (missing_evidence or [])][:4]
    forced = [str(name) for name in (forced_tools or [])]
    docset_hint = (
        _EVIDENCE_NOTE_DOCSET_HINT if forced == ["create_docset"] else ""
    )
    absaetze = " ".join(
        text for art, text in _EVIDENCE_NOTE_ABSAETZE.items() if art in missing
    )
    kopf = (
        "[System note: Es fehlt noch vertraglich geforderte Evidenz für "
        + ", ".join(missing)
        + ". Im nächsten Aufruf werden nur noch diese verbleibenden Tools "
        "exponiert: "
        + ", ".join(forced[:4])
        + ". Antworte noch nicht abschließend, sondern sammle zuerst diese "
        "Evidenz. "
        + docset_hint
        + absaetze
    )
    return (
        kopf.rstrip()
        + anchor_guidance
        + " Wenn keines der exponierten Tools fachlich passt, sage danach "
        "explizit, dass die geforderte Evidenz nicht erzeugbar ist.]"
    )


def exact_cql_from_question(question: str) -> str:
    """Return a user-supplied CQL literal only for an explicit verbatim request."""

    text = str(question or "")
    lowered = text.casefold()
    if not any(
        marker in lowered
        for marker in (
            "exakt",
            "unverändert",
            "unveraendert",
            "wortwörtlich",
            "wortwoertlich",
            "verbatim",
        )
    ):
        return ""
    match = re.search(r"(?i)cql:\s*", text)
    if match is None:
        return ""
    start = match.start()
    tail = text[start:]
    if start > 0 and text[start - 1] == "`":
        closing_tick = tail.find("`")
        if closing_tick >= 0:
            return tail[:closing_tick].strip()
    tail = tail.splitlines()[0]
    # An unclosed CQL cell has no syntactic endpoint. In prose, a following
    # conditional clause marks the end without guessing a repaired bracket.
    boundary = re.search(
        r"\.\s+(?=(?:falls|wenn|if|when)\b)",
        tail,
        flags=re.IGNORECASE,
    )
    if boundary is not None:
        tail = tail[: boundary.start()]
    return tail.strip().rstrip(".,;").strip()


CONFIRMATION_KWIC_CONTEXT_MIN = 30
_EXPLICIT_KWIC_CONTEXT_PATTERN = re.compile(
    r"(?:\bctx\s*(?:=|:)?\s*\d+\b|"
    r"\b(?:kontext(?:breite|fenster)?|context(?:\s+(?:width|window))?)\b"
    r"\s*(?:(?:=|:|von|of)\s*)?\d+\b|"
    r"\b\d+\s*(?:token|wörter|woerter|words?)\b[^.!?\n]{0,30}"
    r"\b(?:kontext|context)\b|"
    r"\b(?:knapp|kurz|eng|breit|weit|ausführlich|ausfuehrlich)\w*\s+"
    r"(?:kontext|context)\b)",
    re.IGNORECASE,
)


def question_sets_kwic_context(question: str) -> bool:
    """Keep an explicit user choice of KWIC context width authoritative."""

    return (
        _EXPLICIT_KWIC_CONTEXT_PATTERN.search(str(question or "")) is not None
    )


__all__ = [
    "ANSWER_SWITCH_FRACTION",
    "CONFIRMATION_KWIC_CONTEXT_MIN",
    "PREPLAN_CALL_ID_PREFIX",
    "contract_evidence_note",
    "exact_cql_from_question",
    "extract_primary_terms",
    "ist_kandidatenliste",
    "kandidatenliste",
    "kandidatenlisten_note",
    "plan_free_mode_first_round",
    "plan_recipe_first_round",
    "preplanned_tool_calls",
    "unbrauchbares_vorplan_attribut",
    "question_sets_kwic_context",
    "expand_tools_for_recipe",
    "registry_tool_names",
    "CAPABILITY_UNAVAILABLE_MARKERS",
    "FINAL_POLISH_HONESTY_LINE",
    "GENERIC_TRIGGER_LEXEMES",
    "RECIPE_CLASSIFIER_TIMEOUT_S",
    "ROUTING_STAGE_FRAGEFORM",
    "ROUTING_STAGE_FREE",
    "ROUTING_STAGE_LLM",
    "ROUTING_STAGE_TRIGGER",
    "TOOL_ROUND_WRAPUP_LINE",
    "VERIFIER_SKIPPED_NOTE",
    "VERIFIER_UNBESTAETIGT_NOTE",
    "VERIFIER_LAEUFT_NOTE",
    "VERIFIER_HINWEISE",
    "answer_switch_fraction_for_recipe",
    "build_recipe_classifier_messages",
    "build_recipe_classifier_prompt",
    "build_turn_system_prompt",
    "classify_recipe_llm",
    "recipe_classifier_timeout_s",
    "final_answer_polish",
    "is_explicit_split_qa_request",
    "is_search_defined_contrast",
    "search_contrast_briefing_note",
    "split_qa_briefing_note",
    "word_similarity_unavailable_gate",
    "parse_recipe_classifier_reply",
    "recipe_routing_annotation",
    "route_turn_recipe",
    "stage1_recipe_decision",
    "capability_unavailable_reason",
    "capability_unavailable_result",
    "collapse_unit_number_doubles",
    "corpus_card_from_context",
    "corpus_card_from_ui_context",
    "aussagen_annotationen",
    "aussagen_ohne_deckung_streichen",
    "drop_unresolved_sentences",
    "fold_duplicate_lines",
    "embedding_unavailable_gate",
    "free_mode_evidence_digest",
    "max_tool_rounds_for_recipe",
    "precondition_unmet_answer",
    "recipe_precondition_status",
    "reference_hard_findings",
    "resolve_reference_draft",
    "session_briefing_state",
    "strike_unbound_numbers",
    "strip_repeated_section_labels",
    "tool_rounds_exhausted",
    "trim_incomplete_tail_sentence",
    "verifier_skipped_answer_text",
    "zitate_ohne_deckung_streichen",
]


#: Felder, unter denen ein Korpus mehrere Fassungen DESSELBEN Quelltextes
#: fuehrt. Bewusst eine feste, kurze Liste statt einer Heuristik: ein Feld,
#: das nur zufaellig gruppiert, wuerde sonst als Quelltextfeld gelten und
#: die Meldung etwas Falsches behaupten.
QUELLTEXTFELDER = ("origin_id", "origin_doc_id", "pair_id")


def _vervielfaeltigung(
    cardinality: Mapping[str, Any], doc_count: int | None
) -> Dict[str, Any] | None:
    """Report multiple document versions per source text when the ratio is at least 1.5.

    Return None when the corpus does not meet that threshold.
    """

    if not isinstance(cardinality, Mapping) or not doc_count:
        return None
    for feld in QUELLTEXTFELDER:
        roh = cardinality.get(feld)
        try:
            quellen = int(roh)
        except (TypeError, ValueError):
            continue
        if quellen <= 0 or doc_count < 1.5 * quellen:
            continue
        return {
            "feld": feld,
            "anzahl": quellen,
            "fassungen_je_quelltext": round(doc_count / quellen, 2),
        }
    return None


def corpus_card_from_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    """Kompakte Korpus-Karte fuer ``build_turn_briefing`` aus ui_context."""
    card: Dict[str, Any] = {}
    corpus_block = context.get("corpus")
    corpus_id = context.get("corpus_id")
    if not corpus_id and isinstance(corpus_block, Mapping):
        corpus_id = corpus_block.get("corpusId")
    if corpus_id:
        card["corpus_id"] = str(corpus_id)
    if context.get("corpus_tokens") is not None:
        card["tokens"] = context["corpus_tokens"]
    if context.get("corpus_docs") is not None:
        card["docs"] = context["corpus_docs"]
    attributes = context.get("corpus_attributes")
    if isinstance(attributes, (list, tuple)) and attributes:
        card["attributes"] = [str(item) for item in attributes]
    if context.get("corpus_lemma_ist_wortform"):
        card["lemma_ist_wortform"] = True
    # Record constant attributes that were checked and rejected.
    # The deterministic plan uses this field to skip uninformative grouping calls.
    konstant = context.get("corpus_constant_attributes")
    if isinstance(konstant, (list, tuple)) and konstant:
        card["constant_attributes"] = [str(item) for item in konstant]
    # Set metadata fields explicitly, even when empty, so the corpus card
    # can explain unavailable comparisons and time analyses before tool calls.
    meta_fields = context.get("corpus_meta_fields")
    if isinstance(meta_fields, (list, tuple)):
        card["meta_fields"] = [str(item) for item in meta_fields]
        date_fields = context.get("corpus_date_fields")
        card["date_fields"] = (
            [str(item) for item in date_fields]
            if isinstance(date_fields, (list, tuple))
            else []
        )
        # Kardinalitaet -> Achsen-Klassifikation. Nur wenn die Wertezahlen
        # vorliegen; sonst bleibt es beim reinen Namensinventar (die
        # Vorbedingung schliesst dann NICHT kurz, kein False-Negative).
        cardinality = context.get("corpus_meta_field_cardinality")
        if isinstance(cardinality, Mapping):
            raw_docs = context.get("corpus_docs")
            try:
                doc_count = int(raw_docs) if raw_docs is not None else None
            except (TypeError, ValueError):
                doc_count = None
            card["meta_axes"] = _classify_meta_axes(
                card["meta_fields"], cardinality, doc_count
            )
            # Use the available cardinality to distinguish documents from source texts.
            # Report repeated versions in the corpus card before analysis so document
            # coverage is not mistaken for independent-source coverage.
            fassungen = _vervielfaeltigung(cardinality, doc_count)
            if fassungen:
                card["quelltexte"] = fassungen
    if isinstance(e := context.get("corpus_entstehung"), Mapping) and (e.get("werte") or e.get("beschreibung")):
        card["entstehung"] = dict(e)  # Verfahren je Fassung und Korpusbeschreibung, prompts.py
    if "embeddings_available" in context:
        card["capabilities"] = {
            "embeddings": bool(context.get("embeddings_available"))
        }
    subcorpus = (
        corpus_block.get("subcorpus")
        if isinstance(corpus_block, Mapping)
        else None
    )
    if isinstance(subcorpus, Mapping) and subcorpus:
        entry: Dict[str, Any] = {}
        size = subcorpus.get("size")
        if isinstance(size, Mapping):
            if size.get("docs") is not None:
                entry["docs"] = size["docs"]
            if size.get("tokens") is not None:
                entry["tokens"] = size["tokens"]
        filters = subcorpus.get("filters")
        if isinstance(filters, list) and filters:
            rendered = "; ".join(
                " ".join(
                    str(part)
                    for part in (
                        f.get("field", ""),
                        f.get("op", "eq"),
                        f.get("value", ""),
                    )
                ).strip()
                for f in filters
                if isinstance(f, Mapping)
            )
            if rendered:
                entry["label"] = rendered
        if entry:
            card["subcorpus"] = entry
    return card


def session_briefing_state(
    ui_context: Mapping[str, Any],
    recent_tool_results: List[Dict[str, Any]],
    failed_tool_attempts: Mapping[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Session-Stand fuer das Turn-Briefing: eine Zeile je Analyse.

    Speist sich aus den vorhandenen Session-Strukturen (Tool + Kernergebnis
    aus den Tool-Ergebnis-Zeilen, ``failed_attempts`` als harte
    Negativhinweise).
    """
    state: Dict[str, Any] = {}
    autonomy = ui_context.get("autonomy_level")
    if autonomy is None and isinstance(ui_context.get("session"), Mapping):
        autonomy = ui_context["session"].get("autonomy")
    if autonomy is not None:
        state["autonomy_level"] = autonomy
    state["turns"] = [
        item["summary"]
        for item in recent_tool_results
        if item.get("ok") and item.get("summary")
    ]
    state["failed_attempts"] = [
        (
            f"{entry.get('tool')}({entry.get('args')}) -> {entry.get('reason')}"
            if entry.get("args")
            else f"{entry.get('tool')} -> {entry.get('reason')}"
        )
        for entry in failed_tool_attempts.values()
    ][-4:]
    return state


def free_mode_evidence_digest(
    recent_tool_results: Sequence[Mapping[str, Any]] | None,
) -> str:
    """Deterministischer Zwischenstand aus den erfolgreichen Tool-Ergebnissen.

    H5, Fix 5: Freie (kontraktlose) Turns wie die offene Exploration haben am
    Wall-/Schritt-Budget keinen LLM-Call mehr fuer die Synthese. Ohne diesen
    Digest gab der Turn eine LEERE Antwort zurueck und verwarf die bereits
    erhobene Tool-Evidenz (Live-Befund R5: 'kein gueltiger AnalysisContract',
    leere Nichtantwort). Der Digest listet die erfolgreichen Tool-Ergebnisse
    als ehrlichen Zwischenstand. Er interpretiert nicht und erfindet nichts:
    die Zeilen sind die kompakten Tool-Ausgaben selbst. Leer, wenn keine
    erfolgreiche Evidenz vorliegt (dann bleibt es beim bisherigen Verhalten).
    """
    seen: set[str] = set()
    findings: List[str] = []
    for item in recent_tool_results or []:
        if not isinstance(item, Mapping) or not item.get("ok"):
            continue
        line = str(item.get("summary") or "").strip()
        if line and line not in seen:
            seen.add(line)
            findings.append(line)
    if not findings:
        return ""
    lines = [
        _t("Das Zeit- bzw. Schrittbudget wurde erreicht, bevor eine "
           "abschliessende Synthese moeglich war. Zwischenstand aus den "
           "bereits erhobenen Tool-Ergebnissen:", "The time or step budget was reached before final synthesis. Interim results from the tool evidence collected so far:"),
        "",
    ]
    lines.extend(f"- {line}" for line in findings[:8])
    lines.extend(
        [
            "",
            _t("Limitationen:", "Limitations:"),
            _t("- Dies ist ein deterministischer Zwischenstand ohne "
               "interpretative Synthese oder Verifikation. Fuer eine "
               "gedeutete Endantwort den Turn fortsetzen.", "- This is a deterministic interim report. Continue the turn for an interpreted final answer and verification."),
        ]
    )
    return "\n".join(lines).strip()


def _context_with_corpus_metadata(
    ui_context: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """ui_context angereichert um die (index-abgeleiteten) Korpus-Metadaten."""
    context = dict(ui_context or {})
    try:
        corpus_meta = _get_corpus_metadata() or {}
    except Exception:
        corpus_meta = {}
    if corpus_meta:
        context = {**context, **corpus_meta}
    return context


def corpus_card_from_ui_context(
    ui_context: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Korpus-Karte aus dem (metadaten-angereicherten) ui_context.

    Gemeinsame Naht fuer ``build_turn_system_prompt`` (Prompt) und die
    deterministische Vorbedingungspruefung (Fix 2): beide sehen exakt
    dieselbe Karte, damit der Kurzschluss genau das benennt, was auch im
    Briefing steht.
    """
    return corpus_card_from_context(_context_with_corpus_metadata(ui_context))


# Haertung r4, Fix 3: Werkzeuge, die einen Passagen-Vektorindex (Embeddings)
# brauchen. similar_words (spaCy-Wortvektoren) und document_search (BM25)
# gehoeren NICHT dazu und bleiben verfuegbar.
_EMBEDDING_DEPENDENT_TOOLS = frozenset(
    {"semantic_search", "semantic_cluster", "semantic_cluster_words"}
)


def embedding_unavailable_gate(
    ui_context: Mapping[str, Any] | None,
    available_tools: Any,
) -> Dict[str, str]:
    """``{tool: grund}`` fuer embeddingsabhaengige Werkzeuge ohne Embeddings.

    Weist die Korpus-Karte ``capabilities: embeddings=false`` aus, gehoeren
    semantic_search & Co. praeemptiv (nicht erst nach einem Fehl-Call) aus dem
    Tool-Space, damit das Modell keine embeddingsfreien Muell-Paare berichtet.
    Leer, wenn Embeddings verfuegbar oder unbekannt sind. Nur tatsaechlich
    vorhandene Werkzeuge werden gemeldet.
    """
    try:
        card = corpus_card_from_ui_context(ui_context)
    except Exception:
        return {}
    capabilities = card.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return {}
    if "embeddings" not in capabilities or capabilities.get("embeddings"):
        return {}
    available = set(available_tools or [])
    reason = (
        "embeddings=false: dieses Korpus hat keinen Passagen-Vektorindex, "
        "semantische Suche ist nicht verfuegbar."
    )
    return {
        name: reason
        for name in _EMBEDDING_DEPENDENT_TOOLS
        if name in available
    }


def word_similarity_unavailable_gate(
    available_tools: Any,
    index_path: Any = None,
) -> Dict[str, str]:
    """``{"similar_words": grund}``, wenn der Wort-Thesaurus real fehlt (V9).

    Kontrakt aus Paket B: ``tool_wrappers.word_similarity_available``
    prueft die Dateipraesenz (faiss_word.index UND word_ids.npy). Der
    Gate-Eintrag nimmt ``similar_words`` praeemptiv aus dem Tool-Space,
    statt wiederholte unavailable-Calls zuzulassen. Defensiv per
    getattr-Import: fehlt der Export (aelterer Stand, Test-Stubs) oder ist
    kein Indexpfad aufloesbar, gibt es KEIN Gate (fail open = heutiges
    Verhalten, nie ein faelschliches Wegsperren).
    """
    if "similar_words" not in set(available_tools or []):
        return {}
    try:
        from . import tool_wrappers as _tool_wrappers
    except Exception:
        return {}
    checker = getattr(_tool_wrappers, "word_similarity_available", None)
    if not callable(checker):
        return {}
    if index_path in (None, ""):
        resolver = getattr(_tool_wrappers, "_resolve_corpus_index", None)
        if not callable(resolver):
            return {}
        try:
            idx = resolver(None)
            index_path = getattr(
                getattr(idx, "fast_index", None), "index_path", None
            )
        except Exception:
            return {}
    if index_path in (None, ""):
        return {}
    try:
        if checker(index_path):
            return {}
    except Exception:
        return {}
    return {
        "similar_words": (
            "semantic.word_similarity fehlt: faiss_word.index/word_ids.npy "
            "liegen fuer dieses Korpus nicht auf der Platte."
        )
    }


def _verlauf_alternative(card: Mapping[str, Any], recipe: Any) -> str:
    """Build a useful alternative when a time analysis lacks its required field.

    Select from the same axis inventory used for contrast prerequisites.
    Suggest only fields with multiple values so the alternative can provide
    a distribution rather than a single constant group.
    """

    axes = [a for a in (card.get("meta_axes") or []) if isinstance(a, Mapping)]
    if not axes:
        # Ohne Inventar keine Behauptung ueber Alternativen. Der statische
        # Text bleibt, weil das Schweigen sonst schlechter waere.
        return text_value(getattr(recipe, "precondition_alternative", "") or "")
    linguistisch = [
        str(a.get("field"))
        for a in axes
        if a.get("kind") == "axis" and a.get("field")
    ]
    technisch = [
        str(a.get("field"))
        for a in axes
        if a.get("kind") == "technical" and a.get("field")
    ]
    if linguistisch:
        return (
            _t("Als Ersatzachse kommt in Frage, was mehr als einen Wert "
            "trägt: ", 'Possible substitute axes with multiple values: ') + ", ".join(linguistisch[:8]) + "."
        )
    if technisch:
        # Die technische Partition als Zeitersatz vorzuschlagen waere
        # derselbe Fehler in klein: sie traegt zwar mehrere Werte, bildet
        # aber keine Zeit ab.
        return (
            _t("Eine linguistische Ersatzachse gibt es hier nicht. Mehr als "
            "einen Wert trägt allein die technische Datenaufteilung (", 'No linguistic substitute axis is available. Only the technical data partition has multiple values (')
            + ", ".join(technisch[:8])
            + _t("), die keine Zeit abbildet. Was bleibt, ist der Blick auf "
            "die einzelnen Belege.", '), which does not represent time. Individual concordance lines can still be examined.')
        )
    return (
        _t("Eine Ersatzachse gibt es hier nicht: alle Metadatenfelder tragen "
        "genau einen Wert. Was bleibt, ist der Blick auf die einzelnen "
        "Belege.", 'No substitute axis is available because every metadata field has one value. The individual concordance lines can still be examined.')
    )


def _meta_axis_alternative(card: Mapping[str, Any], recipe: Any) -> str:
    """Dynamischer ``{alternative}``-Fuellwert fuer den kontrast-Kurzschluss.

    Zaehlt die tatsaechlich vorhandenen (aber nicht kontrastierbaren) Achsen
    mit ihrer Kategorie auf und haengt den statischen Docset-Ausweichpfad des
    Rezepts an, damit die Antwort ehrlich benennt, WAS es gibt und WAS trotzdem
    moeglich bleibt.
    """
    axes = [a for a in (card.get("meta_axes") or []) if isinstance(a, Mapping)]
    single = [a for a in axes if a.get("kind") == "single"]
    leer = [a for a in axes if a.get("kind") == "empty"]
    doc_id = [a for a in axes if a.get("kind") == "doc_id"]
    quelltext = [a for a in axes if a.get("kind") == "quelltext"]
    technical = [a for a in axes if a.get("kind") == "technical"]
    inventory_parts: List[str] = []
    if single:
        inventory_parts.append(
            _t("einwertige Felder: ", 'single-valued fields: ')
            + ", ".join(str(a.get("field")) for a in single[:8])
        )
    if leer:
        inventory_parts.append(
            _t("vorhanden, aber unbefüllt: ", 'present but empty: ')
            + ", ".join(str(a.get("field")) for a in leer[:8])
        )
    if doc_id:
        inventory_parts.append(
            _t("Dokument-ID-Felder: ", 'document ID fields: ')
            + ", ".join(str(a.get("field")) for a in doc_id[:8])
        )
    if quelltext:
        # Ohne diesen Zweig verschwaende das Feld aus dem Inventar, und
        # eine unvollstaendige Aufzaehlung sieht aus wie eine vollstaendige.
        inventory_parts.append(
            _t("Quelltext-Gruppierung (gleicher Text in mehreren Fassungen, "
            "nicht kontrastierbar): ", 'source-text grouping (versions of the same text, no contrast): ')
            + ", ".join(str(a.get("field")) for a in quelltext[:8])
        )
    if technical:
        inventory_parts.append(
            _t("technische Partition (Datenaufteilung, keine linguistische "
            "Achse): ", 'technical partition (data subdivision, rather than a linguistic axis): ')
            + ", ".join(str(a.get("field")) for a in technical[:8])
        )
    inventory = ". ".join(inventory_parts)
    # H6 (B7): der Kurzschluss lenkt um, statt abzuwuergen — ein Kontrast
    # entlang der technischen Partition bleibt auf ausdrueckliche Nachfrage
    # als Split-QA moeglich.
    technical_hint = (
        _t(" Ein Kontrast entlang der technischen Partition (", ' A contrast along the technical partition (')
        + ", ".join(str(a.get("field")) for a in technical[:8])
        + _t(") bleibt auf ausdrückliche Nachfrage als Split-QA möglich.", ') remains available as split QA when explicitly requested.')
        if technical
        else ""
    )
    static_alt = text_value(getattr(recipe, "precondition_alternative", "") or "")
    if inventory and static_alt:
        return (
            _t(f"Vorhandene Achsen ({inventory}) sind nicht kontrastierbar. ", f"Available axes ({inventory}) cannot support a contrast. ")
            + static_alt
            + technical_hint
        )
    return (static_alt or inventory) + technical_hint


# H9/C2 (V7) + H11/B2: deterministische Erkennung einer AUSDRUECKLICHEN
# Partitions-Nachfrage, generisch verbreitert (Gutachter-Mandat
# "Generalisierungsrest"). Beide Muster muessen treffen:
# (i) eine Partitions-Nennung — BEIDE Partitionsnamen train UND test als
#     eigenstaendige Tokens (Wortgrenzen: "trainieren" und "Der Test war
#     schwer" feuern NIE) ODER ein Partitions-Lexem (split/partition/
#     aufteilung, inkl. Komposita wie Trainingspartition/Datenaufteilung).
#     "teilmenge" zaehlt NUR datentechnisch (neben "daten"), nie fuer
#     suchdefinierte Teilmengen (H10/G3 bleibt unberuehrt).
# (ii) ein Untersuchungs-/QA-Kontext (untersuch/pruef/vergleich/unterschied/
#     drift/auseinander/qa/technisch plus die bisherigen Verben).
_SPLIT_QA_TRAIN_TOKEN = re.compile(r"(?<!\w)train(?!\w)", re.IGNORECASE)
_SPLIT_QA_TEST_TOKEN = re.compile(r"(?<!\w)test(?!\w)", re.IGNORECASE)
_SPLIT_QA_PARTITION_LEXEME = re.compile(
    r"split|partition|aufteilung", re.IGNORECASE
)
_SPLIT_QA_DATA_SUBSET = re.compile(r"teilmenge", re.IGNORECASE)
_SPLIT_QA_DATA_MARKER = re.compile(r"daten", re.IGNORECASE)
_SPLIT_QA_CONTEXT_PATTERN = re.compile(
    r"untersuch|pr(?:ü|ue)f|vergleich|unterschied|unterscheid|drift"
    r"|auseinander|(?<!\w)qa(?!\w)|technisch"
    r"|analysier|kontrastier|check|teste",
    re.IGNORECASE,
)


def is_explicit_split_qa_request(question: str) -> bool:
    """Ausdrueckliche Nachfrage nach der technischen Datenaufteilung (V7/B2)."""
    from candyconc.question_language import routing_text

    text = routing_text(question)
    if not text.strip():
        return False
    partition = (
        (
            _SPLIT_QA_TRAIN_TOKEN.search(text) is not None
            and _SPLIT_QA_TEST_TOKEN.search(text) is not None
        )
        or _SPLIT_QA_PARTITION_LEXEME.search(text) is not None
        or (
            _SPLIT_QA_DATA_SUBSET.search(text) is not None
            and _SPLIT_QA_DATA_MARKER.search(text) is not None
        )
    )
    return partition and _SPLIT_QA_CONTEXT_PATTERN.search(text) is not None


def split_qa_briefing_note(technical_fields: Sequence[str]) -> str:
    """Briefing-Hinweis fuer die eingeloeste Split-QA (V7)."""
    fields = ", ".join(str(f) for f in technical_fields if str(f).strip())
    return (
        f"Split-QA: Achse {fields or 'split'} ist technisch, Befunde als "
        "Datenaufteilungs-QA rahmen, nicht als Sprachbefund."
    )


def recipe_precondition_status(
    recipe_id: str,
    card: Mapping[str, Any],
    question: str = "",
) -> Dict[str, Any]:
    """Deterministische Vorbedingungspruefung gegen die Korpus-Karte (0 Calls).

    Liefert ``{"short_circuit": bool, "reason": str, "alternative": str}``,
    bei eingeloester Split-QA zusaetzlich ``briefing_note``.

    ``short_circuit`` ist nur dann ``True``, wenn (a) das Rezept eine
    fallback-lose Vorbedingung deklariert, (b) die Karte ihr Meta-Inventar
    POSITIV ausweist und (c) die geforderte Faehigkeit dort nachweislich fehlt.

    * ``date_field`` (verlauf): kein Datumsfeld in der Karte.
    * ``meta_axis`` (kontrast): KEINE Achse mit >=2 Werten (Dok-ID-Felder
      ausgeschlossen). Nur entscheidbar, wenn die Karte ``meta_axes``
      (Kardinalitaet) ausweist; ohne Kardinalitaet wird nie kurzgeschlossen
      (kein False-Negative gegen echte Metadaten). Der Kurzschluss-Antworttext
      benennt die vorhandenen (nicht kontrastierbaren) Achsen und den
      Docset-ueber-Suche-Ausweichpfad, wuergt die Interpretation also nicht ab,
      sondern lenkt sie ehrlich um.
    * H9/C2 (V7): fragt die Nutzerfrage AUSDRUECKLICH nach der technischen
      Datenaufteilung (``is_explicit_split_qa_request``) und traegt die Karte
      eine technische Partitions-Achse, dann gilt diese als kontrastierbar:
      KEIN Kurzschluss, der Kontrast laeuft ueber die technische Achse und
      das Briefing bekommt den Split-QA-Rahmungshinweis.
    """
    empty = {"short_circuit": False, "reason": "", "alternative": ""}
    if not recipe_id:
        return empty
    try:
        recipe = get_recipe(recipe_id)
    except Exception:
        return empty
    precondition = dict(getattr(recipe, "precondition", {}) or {})
    requires = str(precondition.get("requires", "") or "")
    if not requires:
        return empty
    # Nur entscheiden, wenn die Karte ihr Meta-Inventar positiv ausweist.
    if "meta_fields" not in card:
        return empty
    if requires == "date_field":
        unmet = not list(card.get("date_fields") or [])
        alternative = _verlauf_alternative(card, recipe)
    elif requires == "meta_axis":
        axes = card.get("meta_axes")
        # Ohne Kardinalitaet keine Achsen-Entscheidung -> nie kurzschliessen.
        if not isinstance(axes, list):
            return empty
        contrastable = [
            a
            for a in axes
            if isinstance(a, Mapping) and a.get("kind") == "axis"
        ]
        technical = [
            a
            for a in axes
            if isinstance(a, Mapping) and a.get("kind") == "technical"
        ]
        # P7: Termlisten-Modus. Traegt die Frage eine Kandidatenliste UND
        # hat der Korpus eine Achse, laeuft der Kontrast als Zaehlung je
        # Kandidat auf beiden Achsenseiten. Die Note steht hinter der
        # Achsenpruefung: ohne Achse gibt es keine zwei Seiten, und dann
        # bleibt der ehrliche Kurzschluss richtig. Beobachtet am 2026-09-02
        # an der Markerfrage, deren sieben Kandidaten als keyness-``target``
        # uebergeben wurden und mit 400 endeten.
        if contrastable and ist_kandidatenliste(question):
            return {
                **empty,
                "briefing_note": kandidatenlisten_note(
                    kandidatenliste(question)
                ),
            }
        # V7 Split-QA-Einloesung: ausdrueckliche Partitions-Nachfrage plus
        # vorhandene technische Achse -> Kontrast laeuft, kein Kurzschluss.
        if (
            not contrastable
            and technical
            and is_explicit_split_qa_request(question)
        ):
            return {
                **empty,
                "briefing_note": split_qa_briefing_note(
                    [str(a.get("field")) for a in technical[:4]]
                ),
            }
        # H10/G3: suchdefinierter Kontrast — nennt die Frage ZWEI Terme in
        # Anfuehrungszeichen in einer Vergleichskonstruktion, ist die
        # Vorbedingung ueber den Docset-per-Suche-Pfad ERFUELLT (KEIN
        # Kurzschluss): create_docset(query=...) baut beide Seiten ohne
        # Metadaten-Achse, die Vorplanung (plan_recipe_first_round) ruft
        # beide Calls deterministisch, das Briefing broadcastet den
        # keyness-Folgeweg samt Effektgroessen und Streuungs-Robustheit.
        if not contrastable and is_search_defined_contrast(question):
            return {
                **empty,
                "briefing_note": search_contrast_briefing_note(
                    extract_primary_terms(question)
                ),
            }
        unmet = not contrastable
        alternative = _meta_axis_alternative(card, recipe)
    else:
        return empty
    if not unmet:
        return empty
    # Fallback vorhanden -> nicht kurzschliessen, das Briefing brieft den
    # Ausweichpfad (nur wenn AUCH der nicht traegt, waere ein Kurzschluss
    # angebracht; das entscheidet dann der Modellpfad ehrlich, nicht dieser
    # deterministische Vorabtest).
    if str(precondition.get("fallback", "") or ""):
        return empty
    return {
        "short_circuit": True,
        "reason": requires,
        "alternative": alternative,
    }


def precondition_unmet_answer(recipe_id: str, alternative: str = "") -> str:
    """Ehrlicher Kurzschluss-Antworttext des Rezepts (Template gefuellt)."""
    try:
        recipe = get_recipe(recipe_id)
    except Exception:
        return ""
    template = text_value(getattr(recipe, "precondition_unmet_text", "") or "")
    if not template:
        return ""
    fill = alternative or text_value(
        getattr(recipe, "precondition_alternative", "") or ""
    )
    try:
        return template.format(alternative=fill)
    except Exception:
        return template.replace("{alternative}", fill)


def build_turn_system_prompt(
    ui_context: Mapping[str, Any] | None,
    recipe_id: str,
    session_state: Mapping[str, Any] | None,
) -> str:
    """System-Nachricht: byte-stabiler Kern + Turn-Suffix strikt am Ende.

    ``build_static_core()`` ist der byte-identische Praefix aller Turns einer
    Session (LM-Studio-Prefix-Cache). Alles Variable (ui_context,
    Korpus-Karte, Session-Stand, Rezept-Briefing) folgt DANACH, das
    ``<turn_briefing>`` steht als letzter Block am Ende.
    """
    parts: List[str] = [build_static_core()]
    context = _context_with_corpus_metadata(ui_context)
    try:
        context_msg = build_context_message(context)
    except Exception:
        context_msg = ""
    if context_msg:
        parts.append(context_msg)
    recipe = None
    if recipe_id:
        try:
            recipe = get_recipe(recipe_id)
        except Exception:
            recipe = None
    recipe_briefing = render_briefing(recipe) if recipe is not None else None
    parts.append(
        build_turn_briefing(
            corpus_card_from_context(context),
            recipe_briefing,
            session_state,
            answer_language=answer_language(),
        )
    )
    return "\n\n".join(parts)


def resolve_reference_draft(
    text: str,
    evidence_items: List[Dict[str, Any]],
    question: str,
    *,
    detect_bare_numbers: bool = True,
) -> Dict[str, Any]:
    """Loest ``{{ev:...}}``-Referenzen deterministisch gegen die Evidenz.

    Die Nutzerfrage gehoert zur erlaubten Oberflaeche: vom Nutzer selbst
    genannte Zahlen sind keine Fabrikation.
    """
    bundle: Dict[str, Any] = {
        "items": [
            item for item in list(evidence_items or []) if isinstance(item, dict)
        ],
    }
    if question:
        bundle["grounding_surface"] = [f"frage={question}"]
    try:
        return resolve_references(
            text,
            bundle,
            detect_bare_numbers=detect_bare_numbers,
        )
    except Exception:
        logger.exception("resolve_references fehlgeschlagen")
        return {
            "text": text,
            "resolved": [],
            "unresolved": [],
            "messages": [],
            "bare_numbers": [],
        }


def reference_hard_findings(resolution: Mapping[str, Any]) -> List[str]:
    """Return concrete unresolved-reference and unsupported-number errors."""
    findings: List[str] = []
    for marker in resolution.get("unresolved") or []:
        findings.append(f"Referenz {marker} existiert nicht in der Evidenz")
    for item in resolution.get("bare_numbers") or []:
        number = str(item.get("number", "") or "")
        context = str(item.get("context", "") or "")
        entry = f"Zahl {number} ohne Beleg"
        if context:
            entry = f"{entry} (Kontext: {context})"
        findings.append(entry)
    return findings


def _kontext_spannen(text: str, kontext: str):
    r"""Fundstellen eines LEERRAUM-NORMALISIERTEN Kontexts im Rohtext.

    ``grounding_refs`` baut den Kontext mit ``" ".join(...split())``. Im
    Antworttext koennen an denselben Stellen Zeilenumbrueche oder
    Mehrfach-Leerzeichen stehen. Deshalb wird jede Leerraumfolge des
    Kontexts als ``\s+`` gesucht, statt woertlich zu vergleichen.
    """
    teile = [re.escape(w) for w in kontext.split() if w]
    if not teile:
        return
    muster = re.compile(r"\s+".join(teile))
    for treffer in muster.finditer(text):
        yield (treffer.start(), treffer.end())


def strike_unbound_numbers(
    text: str,
    bare_numbers: List[Dict[str, str]],
    *,
    annotate: bool = True,
) -> str:
    """Ehrliche Platzhalter fuer weiterhin unbelegte Zahlen (kein Call).

    ``annotate=False`` (H9/C2, V11a) unterdrueckt die angehaengte
    Hinweis-Zeile: der Salvage-Pfad laesst die Platzhalter-Saetze direkt
    ueber ``drop_unresolved_sentences`` fallen, und eine Meta-Zeile mit
    Platzhalter wuerde dessen 50%-Wachposten verfaelschen.

    Kontextlokal, wo der Befund einen Kontext nennt (P2.2, Endabnahme).
    Ein Befund aus ``_pmw_pair_findings`` beanstandet nicht die ZAHL,
    sondern das PAAR aus Zahl und Bezugsgroesse: bei 10.034.000 Tokens ist
    '30 Treffer (498.3 pmw)' arithmetisch falsch und '5000 Treffer (498.3
    pmw)' korrekt. Eine globale Ersetzung des Tokens loeschte beide,
    obwohl der Befund nur das erste nennt, und damit eine evidenzgedeckte
    Nennung. Ein Befund OHNE Kontext meint die Zahl selbst und wird
    weiterhin ueberall ersetzt.
    """
    # Alle Ersetzungen werden gegen den URSPRUENGLICHEN Text geplant und
    # danach in EINEM Durchlauf angewandt. Die erste Fassung hat den Text
    # nach jedem Befund veraendert und den naechsten Kontext im schon
    # veraenderten Text gesucht. Weil die Kontextfenster benachbarter
    # Befunde ueberlappen und die pmw-Befunde NACH den bare_numbers an
    # dieselbe Liste angehaengt werden, war der Kontext des zweiten Befunds
    # dann regelmaessig nicht mehr woertlich vorhanden -- und der Code fiel
    # auf die GLOBALE Ersetzung zurueck, also genau auf den Schaden, den
    # die Reparatur verhindern sollte.
    # Alle Ersetzungen werden gegen den URSPRUENGLICHEN Text geplant und
    # danach in EINEM Durchlauf angewandt. Eine Vorfassung veraenderte den
    # Text nach jedem Befund und suchte den naechsten Kontext im schon
    # veraenderten Text; weil die Kontextfenster benachbarter Befunde
    # ueberlappen, fiel sie regelmaessig auf die GLOBALE Ersetzung zurueck.
    #
    # Der Kontext wird LEERRAUM-NORMALISIERT erzeugt (grounding_refs:
    # ``" ".join(real[start-48:end+48].split())``), also muss er auch
    # leerraum-tolerant gesucht werden. Die zweite Fassung suchte ihn
    # woertlich: sobald der Text an dieser Stelle einen Zeilenumbruch oder
    # doppelte Leerzeichen hatte, fand sie nichts und strich GAR NICHTS.
    # Aus einer zu breiten Ersetzung war eine wirkungslose geworden.
    #
    # Kommt der Kontext MEHRDEUTIG vor, wird nicht gestrichen: lieber eine
    # unbelegte Zahl stehen lassen als eine belegte loeschen.
    struck: List[str] = []
    spannen: List[Tuple[int, int]] = []
    for finding in bare_numbers:
        token = str(finding.get("number", "") or "").strip()
        if not token:
            continue
        # Jahre sind keine Beleg-Maengel (Messung 9: „seit 2026 bekannt").
        if re.fullmatch(r"(?:19|20)\d{2}", token):
            continue
        # Messung 6/9: Ziffern in alphanumerischen Bezeichnern („GPT‑5.2",
        # „404-Fehler") sind keine unbelegte Zahl — der Bindestrich-Kontext
        # zu einem Buchstaben schuetzt Kopf UND Fortsetzung des Tokens.
        pattern = re.compile(
            r"(?<![\w.,])(?<![A-Za-zÄÖÜäöüß][\-–—‑.])"
            + re.escape(token) + r"(?![\w.,])(?![\-–—‑][A-Za-zÄÖÜäöüß])"
        )
        kontext = str(finding.get("context", "") or "").strip()
        bereiche: List[Tuple[int, int]] = [(0, len(text))]
        if kontext:
            treffer = list(_kontext_spannen(text, kontext))
            if len(treffer) != 1:
                # Nicht auffindbar oder mehrdeutig: nicht streichen.
                continue
            bereiche = treffer
        getroffen = False
        for start_b, ende_b in bereiche:
            for treffer_z in pattern.finditer(text, start_b, ende_b):
                spannen.append((treffer_z.start(), treffer_z.end()))
                getroffen = True
        if getroffen and token not in struck:
            struck.append(token)
    if spannen:
        spannen.sort()
        teile: List[str] = []
        zuletzt = 0
        for a, b in spannen:
            if a < zuletzt:
                continue
            teile.append(text[zuletzt:a])
            teile.append(MISSING_EVIDENCE_PLACEHOLDER)
            zuletzt = b
        teile.append(text[zuletzt:])
        text = "".join(teile)
    if struck and annotate:
        text = (
            text.rstrip()
            + "\n\nHinweis: Unbelegte Zahlenangaben wurden durch "
            + MISSING_EVIDENCE_PLACEHOLDER
            + " ersetzt ("
            + ", ".join(struck[:6])
            + ")."
        )
    return text
