# -*- coding: utf-8 -*-
"""Ist diese Frage ein blosses Nachschlagen oder die Bitte um ein Urteil?

EIN URTEIL, DREI SCHICHTEN. Dieselbe Frage wird an drei Stellen eingestuft:
in der Kontraktschicht (``candyconc_copilot.grounding_schemas`` und
``grounding_contracts``), in der Landungsschicht
(``candyconc_copilot.deterministic_landing``) und in der
Promptvertragsschicht (``candyconc.tooling.tool_selection``, deren Vertrag
ueber ``routes/copilot.py`` als ``ui_context`` live in den Turn geht).
Liefen sie auseinander, bekam eine Frage zugleich den Auftrag
"Analysebericht mit Deutung" und die Anweisung "knapp in 1-3 Saetzen,
hoechstens ein Evidenzpunkt, keine lange Interpretation".

WARUM DAS MODUL HIER OBEN STEHT UND NICHT IN EINER DER DREI SCHICHTEN.
``candyconc/tooling/__init__.py`` importiert
``candyconc.candyconc_copilot.tool_wrappers``. Ein Modul unter
``candyconc.tooling`` darf deshalb nicht aus ``candyconc_copilot`` lesen,
und ein Import aus ``candyconc.tooling`` in ``grounding_schemas`` schliesst
denselben Kreis von der anderen Seite. Dieses Modul haengt an nichts ausser
``re``, damit beide Seiten es lesen koennen.

Why a length threshold: plain lookup questions are short and the role
questions of real users are long (the measured lengths are listed at
``MAX_NACHSCHLAGEZEICHEN``). Three of eight role questions contain none of
the interpretation cues. The contract layer classified them as lookups by
their cues, while the landing layer classified them as non-lookups by their
length.
"""

from __future__ import annotations

from candyconc.question_language import normalised_question, routing_text


#: A question longer than this is no longer a lookup.
#:
#: The measured lengths separate cleanly. Plain lookup questions have 24 to
#: 39 characters:
#:
#:     24  Welche Register gibt es?
#:     35  Wie oft kommt 'Nachhaltigkeit' vor?
#:     39  Gibt es das Wort Klimawandel im Korpus?
#:
#: Eight role questions written by real users have 330 to 739 characters.
#:
#: 160 leaves a margin on both sides: four times the longest lookup question
#: and half the shortest role question.
#:
#: Length is a coarse but honest criterion. A user who supplies 300
#: characters of context, asks several sub-questions and describes an own
#: impression wants a judgement, not a number. A longer keyword list would
#: have had to grow until these eight questions fit, which adapts the rule to
#: the sample instead of to the task.
MAX_NACHSCHLAGEZEICHEN = 160


# Interpretation cues include the usage phrases in recipes_data.py so the
# contract and recipe layers agree on usage questions. Recipe cues also
# include family markers and tool names because they select a procedure.
DEUTUNGSCUES = (
    "interpret",
    "deute",
    "deutung",
    "einord",
    "erklär den beleg",
    "erklaer den beleg",
    "erkläre den beleg",
    "wie wird",
    "verwendet",
    "verwendung",
    "gebrauch",
)


def normalisierte_frage(question_text: str) -> str:
    """Kleinschreibung, ein Bindestrich, ein Leerzeichen."""

    return normalised_question(question_text)


def enthaelt_deutungscue(text: str) -> bool:
    """True, wenn die Frage ausdruecklich um Deutung oder Gebrauch bittet.

    An English question is read in the German cue vocabulary
    (``candyconc.question_language``): "How is 'home' used?" asks for usage
    like "Wie wird 'Heim' verwendet?". German questions read as before.
    """

    lowered = routing_text(text)
    return any(cue in lowered for cue in DEUTUNGSCUES)


def frage_ist_blosses_nachschlagen(text: str) -> bool:
    """Return whether the raw question asks only for an inventory lookup.

    Use interpretation cues together with question length. A short usage
    question can require analysis, while a short presence question can use
    the deterministic lookup answer. Evaluate the original question before
    whitespace folding, shortening or model-generated scope descriptions,
    since those transformations can change the length-based decision.
    """

    if len(str(text or "").strip()) > MAX_NACHSCHLAGEZEICHEN:
        return False
    return not enthaelt_deutungscue(text)
