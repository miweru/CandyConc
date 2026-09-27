"""Rezept-Bibliothek: Dataclasses, Validierung, Rendering, Index.

Acht redigierbare Analyse-Rezepte fuer wiederkehrende korpuslinguistische
Frageformen. Die Inhalte liegen als reine Daten in ``recipes_data.py``, dieses
Modul traegt die Struktur und das deterministische Rendering. Die
Auswahl-Heuristik ``select_recipe`` liegt in ``grounding_contracts.py`` (dort,
wo auch ``heuristic_analysis_contract`` wohnt).

Architektur: dieses Modul ist ein Leaf innerhalb ``candyconc_copilot``. Es
importiert nur die Standardbibliothek und ``recipes_data`` und darf nie
Orchestrator-, Verifier- oder Grounding-Module importieren.

Oeffentliche API (Kontrakt fuer Orchestrator- und Prompt-Integration):

* ``Recipe`` / ``RecipeStep``: eingefrorene Dataclasses (Felder siehe unten).
* ``RECIPES``: Tuple aller Rezepte in Trigger-Scan-Prioritaet (Datenreihen-
  folge aus ``recipes_data.RECIPES_DATA``).
* ``RECIPES_BY_ID``: Dict id -> Recipe.
* ``get_recipe(recipe_id)``: Recipe oder KeyError.
* ``recipe_index()``: genau 8 Zeilen ``id: einsatz`` fuer den STATISCHEN
  Prompt-Teil, stabil nach id sortiert (byte-identisch je Aufruf, KV-Cache).
* ``render_briefing(recipe, slots=None)``: deterministischer Briefing-Text
  fuer die Turn-Injection. Bekannte Slots werden als ``{name}``-Platzhalter
  in Briefing und Schritten ersetzt, offene Slots werden mit Beschreibung
  gelistet, damit das Modell sie aus der Frage belegt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from .recipes_data import RECIPES_DATA

_PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_MAX_BRIEFING_LINES = 25
_EXPECTED_RECIPE_COUNT = 8
# Erlaubte Korpus-Karten-Faehigkeiten fuer ``precondition.requires``.
_PRECONDITION_REQUIRES = frozenset({"date_field", "meta_axis"})

# Runden-Leitplanke des freien Modus: nach so vielen Tool-Runden injiziert
# der Orchestrator die Wrap-up-Zeile und exponiert keine weiteren Tools fuer
# den Turn.
#
# AM 2026-09-17 VON 16 AUF 200 GEHOBEN. Der Auftraggeber: "Das muss so
# gebaut sein, dass es LLM generiert selbstbestimmt an der richtigen Stelle
# aufhoert. Solange das nicht so ist, ist der Harness nicht gut genug." Und:
# "Es kann nicht sein, dass eine Recherche still abgebrochen wird."
#
# Sechzehn Runden entzogen dem Modell die Werkzeuge mitten in der Arbeit,
# und was danach herauskam, verbuchte der Lauf als beantwortete Frage. Der
# Wert bleibt als Reissleine gegen eine echte Schleife stehen, liegt aber
# jetzt weit ueber jeder Arbeit, die wir gesehen haben. Ein Turn des Piloten
# brauchte achtundzwanzig Schritte.
FREE_MODE_MAX_TOOL_RUNDEN = 200

# H9/C2 (V5): Sentinel fuer "kein rezept-eigener Antwort-Schalter gesetzt".
# Der wirksame Default (0.55) liegt in recipe_runtime.ANSWER_SWITCH_FRACTION;
# hier steht nur der Daten-Sentinel, damit recipes ein Leaf bleibt.
ANSWER_SWITCH_UNSET = 0.0


@dataclass(frozen=True)
class RecipeStep:
    """Ein Verfahrensschritt: Ziel, Werkzeug-Hinweis, benoetigte Slots."""

    ziel: str
    tool_hinweis: str
    slots: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Recipe:
    """Ein redigierbares Analyse-Rezept (Inhalte in ``recipes_data.py``)."""

    id: str
    name: str
    einsatz: str
    trigger: Tuple[str, ...]
    briefing: str
    schritte: Tuple[RecipeStep, ...]
    slots: Mapping[str, str]
    abbruch_kriterium: str
    deliverable: str
    leitplanken: Tuple[str, ...]
    beispiel_frage: str
    kern_tools: Tuple[str, ...] = field(default=())
    # Wegbereiter: Werkzeuge, die der Turn BRAUCHT, um die Vorbedingung
    # seines eigenen Riegels herzustellen, die aber nicht darueber
    # entscheiden, ob das Rezept ueberhaupt waehlbar ist. Die Trennung ist
    # nicht kosmetisch. ``kern_tools`` hat zwei Verbraucher mit
    # GEGENLAEUFIGER Semantik: ``_recipe_tools_available`` fragt "mindestens
    # eines davon da?", ``grounding_contracts`` gatet auf ``kern_tools[0]``.
    # Solange jedes Rezept genau ein Kernwerkzeug hatte, fielen beide
    # Lesarten zusammen. Haengt man Wegbereiter an ``kern_tools``, genuegt
    # ploetzlich der Wegbereiter allein, um das Rezept waehlbar zu machen,
    # auch wenn sein eigentliches Messwerkzeug fehlt. Genau so wurde
    # 'kontrast' ohne ``keyness`` waehlbar. Wegbereiter erweitern deshalb
    # NUR den Werkzeugraum (``expand_tools_for_recipe``), nie das Tor.
    wegbereiter_tools: Tuple[str, ...] = field(default=())
    # H10/G1: deterministische Schritt-1-Vorplanung als DATEN. Eintraege
    # ``{"tool": name, "args": template}``; String-Werte, die exakt
    # ``{TERM}``/``{TERM2}``/``{DATE_FIELD}`` sind, fuellt
    # ``recipe_runtime.plan_recipe_first_round`` zur Laufzeit (Terme aus
    # Anfuehrungszeichen der Frage, Datumsfeld aus der Korpus-Karte).
    # Leer = Runde 1 plant das Modell (heutiges Verhalten).
    vorplan: Tuple[Mapping[str, Any], ...] = field(default=())
    # Weiche Runden-Leitplanke: nach so vielen Tool-Runden folgt die
    # Wrap-up-Zeile plus Antwort-Synthese aus vorhandener Evidenz.
    max_tool_runden: int = field(default=FREE_MODE_MAX_TOOL_RUNDEN)
    # H9/C2 (V5): rezept-eigener Zeit-Schalter auf die Antwort-Landung.
    # Anteil des Turn-Zeitbudgets, ab dem der Turn auf die weiche
    # Antwort-Synthese schaltet. ``ANSWER_SWITCH_UNSET`` (0.0) heisst:
    # globaler Default aus recipe_runtime (0.55). exploration_meta setzt
    # 0.4, damit die Modell-Synthese VOR dem Server-Backstop laeuft
    # (Befund V5: beide offenen Explorationen endeten im Salvage).
    answer_switch_fraction: float = field(default=ANSWER_SWITCH_UNSET)
    # H9.2: typische Forschungssprache-Paraphrasen NUR fuer das Menue des
    # Stufe-2-Klassifikators (build_recipe_classifier_prompt). Bewusst NICHT
    # Teil von einsatz/recipe_index(), damit der statische Kern-Prompt und
    # dessen Byte-Pins unberuehrt bleiben.
    router_paraphrasen: Tuple[str, ...] = field(default=())
    # Haertung r2, Fix 2: strukturierte Vorbedingung an die Korpus-Karte.
    # ``requires`` nennt die noetige Karten-Faehigkeit ("date_field" =
    # mindestens ein Datumsfeld, "meta_axis" = mindestens ein Meta-Feld);
    # ``fallback`` (optional) nennt einen fachlichen Ausweichpfad, der die
    # Analyse trotz fehlender Vorbedingung noch traegt (z.B.
    # "docset_per_suche"). Ist ``fallback`` gesetzt, wird NICHT
    # kurzgeschlossen, sondern das Briefing brieft den Ausweichpfad. Leeres
    # ``precondition`` = keine deterministische Vorbedingung.
    precondition: Mapping[str, str] = field(default_factory=dict)
    # Ehrlicher Kurzschluss-Antworttext (Template mit ``{alternative}``), wenn
    # die fallback-lose Vorbedingung verletzt ist. 0 Tool-Runden, 0 LLM-Calls.
    precondition_unmet_text: str = field(default="")
    # Fuellwert fuer ``{alternative}`` im Kurzschluss-Antworttext.
    precondition_alternative: str = field(default="")

    @property
    def familien(self) -> Tuple[str, ...]:
        """Analyse-Familien aus ``family:``-Triggern (stabile Reihenfolge)."""

        return tuple(
            entry.split(":", 1)[1]
            for entry in self.trigger
            if entry.startswith("family:")
        )

    @property
    def phrasen_trigger(self) -> Tuple[str, ...]:
        """Phrasen-Trigger ohne die ``family:``-Eintraege.

        Zwei Formen: reine Substring-Muster und ``wort:<lexem>``-Eintraege,
        die nur an Wortgrenzen matchen (Auswertung in
        ``grounding_contracts._phrase_trigger_matches``, H8).
        """

        return tuple(
            entry
            for entry in self.trigger
            if not entry.startswith("family:")
        )


def _build_recipe(raw: Mapping[str, object]) -> Recipe:
    steps = tuple(
        RecipeStep(
            ziel=str(step["ziel"]),
            tool_hinweis=str(step["tool_hinweis"]),
            slots=tuple(str(name) for name in step.get("slots", ())),
        )
        for step in raw["schritte"]  # type: ignore[index]
    )
    return Recipe(
        id=str(raw["id"]),
        name=str(raw["name"]),
        einsatz=str(raw["einsatz"]),
        trigger=tuple(str(item) for item in raw["trigger"]),  # type: ignore[arg-type]
        briefing=str(raw["briefing"]),
        schritte=steps,
        slots={
            str(name): str(text)
            for name, text in dict(raw["slots"]).items()  # type: ignore[arg-type]
        },
        abbruch_kriterium=str(raw["abbruch_kriterium"]),
        deliverable=str(raw["deliverable"]),
        leitplanken=tuple(str(item) for item in raw["leitplanken"]),  # type: ignore[arg-type]
        beispiel_frage=str(raw["beispiel_frage"]),
        kern_tools=tuple(str(item) for item in raw.get("kern_tools", ())),
        wegbereiter_tools=tuple(
            str(item) for item in raw.get("wegbereiter_tools", ())
        ),
        vorplan=tuple(
            {
                "tool": str(dict(entry).get("tool", "")),
                "args": dict(dict(entry).get("args", {}) or {}),
            }
            for entry in raw.get("vorplan", ())  # type: ignore[union-attr]
        ),
        max_tool_runden=int(
            raw.get("max_tool_runden", FREE_MODE_MAX_TOOL_RUNDEN)  # type: ignore[arg-type]
        ),
        answer_switch_fraction=float(
            raw.get("answer_switch_fraction", ANSWER_SWITCH_UNSET)  # type: ignore[arg-type]
        ),
        router_paraphrasen=tuple(
            str(item) for item in raw.get("router_paraphrasen", ())
        ),
        precondition={
            str(name): str(value)
            for name, value in dict(raw.get("precondition", {})).items()  # type: ignore[arg-type]
        },
        precondition_unmet_text=raw.get("precondition_unmet_text", ""),
        precondition_alternative=raw.get("precondition_alternative", ""),
    )


def _validate_recipe(recipe: Recipe) -> None:
    problems: list[str] = []
    if not recipe.id or recipe.id != recipe.id.strip().lower():
        problems.append("id muss nicht-leer und kleingeschrieben sein")
    if len(recipe.briefing.splitlines()) > _MAX_BRIEFING_LINES:
        problems.append(
            f"briefing hat mehr als {_MAX_BRIEFING_LINES} Zeilen"
        )
    if not 2 <= len(recipe.leitplanken) <= 4:
        problems.append("leitplanken muessen 2 bis 4 Eintraege haben")
    if not recipe.schritte:
        problems.append("schritte duerfen nicht leer sein")
    if not recipe.kern_tools:
        problems.append("kern_tools duerfen nicht leer sein")
    for entry in recipe.vorplan:
        if not str(entry.get("tool", "") or "").strip():
            problems.append("vorplan-Eintrag ohne tool-Namen")
        args = entry.get("args", {})
        if not isinstance(args, Mapping):
            problems.append("vorplan-Eintrag mit args, die kein Mapping sind")
            continue
        for value in args.values():
            if (
                isinstance(value, str)
                and value.startswith("{")
                and value.endswith("}")
                and value not in ("{TERM}", "{TERM2}", "{DATE_FIELD}")
            ):
                problems.append(
                    f"vorplan kennt Platzhalter {value} nicht "
                    "(erlaubt: {TERM}, {TERM2}, {DATE_FIELD})"
                )
    if recipe.max_tool_runden < 1:
        problems.append("max_tool_runden muss mindestens 1 sein")
    if recipe.answer_switch_fraction != ANSWER_SWITCH_UNSET and not (
        0.0 < recipe.answer_switch_fraction <= 1.0
    ):
        problems.append("answer_switch_fraction muss in (0, 1] liegen")
    if not recipe.beispiel_frage.strip():
        problems.append("beispiel_frage fehlt")
    if recipe.precondition:
        requires = str(recipe.precondition.get("requires", "") or "")
        if requires not in _PRECONDITION_REQUIRES:
            problems.append(
                "precondition.requires muss eines von "
                f"{sorted(_PRECONDITION_REQUIRES)} sein"
            )
        has_fallback = bool(str(recipe.precondition.get("fallback", "") or ""))
        # Ohne Fallback muss ein Kurzschluss-Text existieren; er darf nur den
        # deklarierten Platzhalter {alternative} tragen.
        if not has_fallback:
            if not recipe.precondition_unmet_text.strip():
                problems.append(
                    "precondition ohne fallback braucht precondition_unmet_text"
                )
            for name in _PLACEHOLDER_PATTERN.findall(
                recipe.precondition_unmet_text
            ):
                if name != "alternative":
                    problems.append(
                        f"precondition_unmet_text kennt nur {{alternative}}, "
                        f"nicht {{{name}}}"
                    )
    elif recipe.precondition_unmet_text or recipe.precondition_alternative:
        problems.append(
            "precondition_unmet_text/alternative ohne precondition gesetzt"
        )
    declared = set(recipe.slots)
    for step in recipe.schritte:
        for name in step.slots:
            if name not in declared:
                problems.append(
                    f"Schritt-Slot '{name}' ist nicht in slots deklariert"
                )
    referenced_texts = [recipe.briefing]
    referenced_texts.extend(step.ziel for step in recipe.schritte)
    referenced_texts.extend(step.tool_hinweis for step in recipe.schritte)
    for text in referenced_texts:
        for name in _PLACEHOLDER_PATTERN.findall(text):
            if name not in declared:
                problems.append(
                    f"Platzhalter '{{{name}}}' ist nicht in slots deklariert"
                )
    if problems:
        raise ValueError(
            f"Rezept '{recipe.id}' ist inkonsistent: " + ", ".join(problems)
        )


def _load_recipes() -> Tuple[Recipe, ...]:
    recipes = tuple(_build_recipe(raw) for raw in RECIPES_DATA)
    seen: set[str] = set()
    for recipe in recipes:
        if recipe.id in seen:
            raise ValueError(f"Doppelte Rezept-id '{recipe.id}'")
        seen.add(recipe.id)
        _validate_recipe(recipe)
    if len(recipes) != _EXPECTED_RECIPE_COUNT:
        raise ValueError(
            f"Erwartet {_EXPECTED_RECIPE_COUNT} Rezepte, "
            f"gefunden {len(recipes)}"
        )
    return recipes


RECIPES: Tuple[Recipe, ...] = _load_recipes()
RECIPES_BY_ID: Dict[str, Recipe] = {recipe.id: recipe for recipe in RECIPES}


def get_recipe(recipe_id: str) -> Recipe:
    """Rezept per id (KeyError bei unbekannter id)."""

    return RECIPES_BY_ID[str(recipe_id)]


def recipe_index() -> str:
    """Acht Zeilen ``id: einsatz`` fuer den statischen Prompt-Teil.

    Stabil nach ``id`` sortiert und frei von Laufzeit-Zustand, damit der
    statische Prompt-Teil byte-identisch bleibt (KV-Cache-Wiederverwendung).
    """

    lines = [
        f"{recipe.id}: {recipe.einsatz}"
        for recipe in sorted(RECIPES, key=lambda item: item.id)
    ]
    return "\n".join(lines)


def _fill_slots(text: str, recipe: Recipe, filled: Mapping[str, str]) -> str:
    for name in recipe.slots:
        if name in filled:
            text = text.replace("{" + name + "}", filled[name])
    return text


def render_briefing(
    recipe: Recipe,
    slots: Mapping[str, str] | None = None,
) -> str:
    """Deterministischer Briefing-Text fuer die Turn-Injection.

    ``slots`` belegt deklarierte Platzhalter, unbekannte Schluessel werden
    ignoriert. Nicht belegte Slots bleiben als ``{name}`` sichtbar und werden
    unter "Offene Slots" mit Beschreibung gelistet, damit das Modell sie aus
    der Frage belegt. Gleiche Eingaben ergeben byte-identische Ausgaben.
    """

    filled = {
        name: str(value)
        for name, value in dict(slots or {}).items()
        if name in recipe.slots
    }
    lines: list[str] = [
        f"REZEPT {recipe.id} ({recipe.name})",
        f"Einsatz: {recipe.einsatz}",
        "",
        _fill_slots(recipe.briefing, recipe, filled).rstrip(),
        "",
        "Schritte:",
    ]
    for number, step in enumerate(recipe.schritte, start=1):
        ziel = _fill_slots(step.ziel, recipe, filled)
        hinweis = _fill_slots(step.tool_hinweis, recipe, filled)
        lines.append(f"{number}. {ziel}. Werkzeug: {hinweis}")
    open_slots = [name for name in recipe.slots if name not in filled]
    if open_slots:
        lines.append("Offene Slots (aus der Frage belegen):")
        for name in open_slots:
            lines.append(f"- {name}: {recipe.slots[name]}")
    lines.append(f"Abbruchkriterium: {recipe.abbruch_kriterium}")
    lines.append(f"Antwortform: {recipe.deliverable}")
    lines.append("Leitplanken:")
    for leitplanke in recipe.leitplanken:
        lines.append(f"- {leitplanke}")
    return "\n".join(lines)
