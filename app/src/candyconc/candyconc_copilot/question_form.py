"""Die Form der Frage, deterministisch gelesen (P5).

Zwei Fragearten kamen im Messarm vom 2026-08-31 nie bei ihrem Rezept an,
und zwar nicht, weil das Modell schlecht waehlte, sondern weil ihm die
Kategorie fehlte. In ``harnisch_nachher.jsonl`` trug die
grounding-Annotation bei sechs von sieben Turns ``stage=llm``, das Menue
des Klassifikators (``recipe_runtime.build_recipe_classifier_prompt``)
kennt aber weder eine Konstruktion noch eine Kandidatenliste. Fuer eine
Frage nach "KI gegen Mensch" blieb ihm nur ``kontrast``.

Hier stehen die beiden Erkenner, die diese Fragearten VOR dem
Klassifikator entscheiden, plus der starke Phrasentreffer, den sie mit
``recipe_runtime`` teilen (er lag dort, wird jetzt an beiden Naehten
gebraucht und darf nicht zweimal existieren).

BEIDE ERKENNER SIND ENGER, ALS IHR NAME KLINGT, und jede Verengung
steht auf einem gemessenen Fall. Eine Konstruktionsfrage routet nur dann
deterministisch, wenn sie zusaetzlich Belege verlangt
(``ist_konstruktions_suchauftrag``): ohne diese Bedingung gingen ueber
die fuenf Fragensaetze unter ``evaluation/fragen/`` drei Fragen an
``gebrauch_kwic``, die normalisierte Zahlen im Gruppenvergleich wollen,
die dieses Rezept mit seinem einen Kernwerkzeug nicht rechnet. Ein
zweiteiliger Konnektor zaehlt nur, wenn er ERWAEHNT und nicht GEBRAUCHT
wird. Und die Geltungs-Cues der Kandidatenliste halten dieselben
Wortgrenzen wie ihre Anker, sonst trifft "halten" in "enthalten".

Das Modul importiert nur ``grounding_schemas`` (Foundation) und ist damit
von ``grounding_contracts`` wie von ``recipe_runtime`` aus benutzbar.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from candyconc.question_language import (
    is_english_question,
    render_cues,
    render_english_cues,
    routing_text,
)

from .grounding_schemas import _normalised_question_text

#: Name der Routing-Stufe, in der die FRAGEFORM entschieden hat.
#:
#: DIESES HAUS HAT ZWEI ROUTER, und die Stufe ist das einzige, woran der
#: zweite den ersten erkennt. ``route_turn_recipe`` waehlt das Rezept,
#: die Cue-Zweige von ``heuristic_analysis_contract`` waehlen die
#: Analysefamilie, und die bestimmt Werkzeuge und Verfasser. Der
#: Rezeptvorrang ``_kontrakt_aus_rezept`` griff bisher nur bei
#: ``stage='llm'``. Gemessen an konstr-scharnier-dreigliedrig mit allen
#: 15 Werkzeugen im Raum: Rezept ``gebrauch_kwic`` (kern_tools
#: ``run_cqlf_query``), Kontrakt aber ``term_frequency`` mit
#: ``allowed_tools ['frequency_list']``. Das Kernwerkzeug des gewaehlten
#: Rezepts war im Turn nicht freigegeben, also genau die Lage, die am
#: 2026-09-01 einen Turn 825 Sekunden stillstehen liess.
#:
#: Die Konstante liegt in diesem Foundation-Modul, weil beide Router sie
#: brauchen und ``grounding_contracts`` ``recipe_runtime`` nicht
#: importieren darf (Zyklus).
ROUTING_STAGE_FRAGEFORM = "frageform"

# --------------------------------------------------------------------------- #
# Starker Phrasentreffer (verschoben aus recipe_runtime, eine Wahrheit)        #
# --------------------------------------------------------------------------- #

# Flexions-Reste fuer starke Trigger-Treffer: ein Ein-Wort-Trigger, der an
# einer Wortgrenze BEGINNT, gilt nur dann als starker Treffer, wenn der Rest
# bis zur naechsten Wortgrenze eine deutsche Flexionsendung ist. Komposita-
# Reste ("beleg" in "Belegzahl" -> "zahl", "stichprobe" in
# "Stichprobenbildung" -> "nbildung") sind damit KEIN starkes Signal: die
# frischen Fehlroutings des zweiten Verdikts kamen genau aus solchen
# Kompositum-Innentreffern. Fuer P5 zaehlt derselbe Schutz nach innen:
# "Wortlisten" (Frage deutung-stilmerkmale-paarig) darf den Listen-Anker
# "liste" NICHT ausloesen, sonst gilt eine Stilfrage als Markerliste.
_INFLECTION_REMAINDERS = frozenset(
    {
        "",
        "e",
        "en",
        "n",
        "s",
        "es",
        "er",
        "ern",
        "em",
        "et",
        "st",
        "t",
        "te",
        "ten",
        "sten",
        "esten",
    }
)


_ANFUEHRUNG = "\"'„“”»«‚‘›‹`"


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def starke_treffer_position(lowered: str, phrase: str) -> int:
    """Index des ersten starken Treffers, sonst -1.

    ``wort:``-Trigger sind per Definition wortgrenzen-genau (H8) und damit
    stark. Fuer alle anderen gilt: der Treffer beginnt an einer Wortgrenze,
    und was bis zur naechsten Wortgrenze folgt, ist eine Flexionsendung
    (``kollokation`` + ``en`` stark, ``beleg`` + ``zahl`` schwach).
    """
    if phrase.startswith("wort:"):
        lexem = phrase.split(":", 1)[1].strip()
        if not lexem:
            return -1
        treffer = re.search(
            r"(?<!\w)" + re.escape(lexem) + r"(?!\w)", lowered
        )
        return treffer.start() if treffer else -1
    needle = phrase.strip()
    if not needle:
        return -1
    start = 0
    while True:
        idx = lowered.find(needle, start)
        if idx < 0:
            return -1
        start = idx + 1
        if idx > 0 and _is_word_char(lowered[idx - 1]):
            continue
        end = idx + len(needle)
        rest: List[str] = []
        while end < len(lowered) and _is_word_char(lowered[end]):
            rest.append(lowered[end])
            end += 1
        if "".join(rest) in _INFLECTION_REMAINDERS:
            return idx


def starker_treffer(lowered: str, phrase: str) -> bool:
    """Ob ``phrase`` einen starken Treffer in ``lowered`` hat.

    An English question is matched in its rendering into the German cue
    vocabulary (``candyconc.question_language``), so the German triggers of
    the recipes and cue lists match it as they match the German question.
    German text is matched as it stands. ``starke_treffer_position`` keeps
    reading the text as given, its positions index the caller's text.
    """
    text = render_english_cues(lowered) or lowered
    return starke_treffer_position(text, phrase) >= 0


# --------------------------------------------------------------------------- #
# Konstruktionsfragen                                                          #
# --------------------------------------------------------------------------- #

# Die Frage schreibt eine SUCHFORM vor: Reihenfolge, Abstand oder einen
# benannten Konstruktionstyp. Jeder einzelne Eintrag genuegt.
#
# Gemessen an den beiden Konstruktionsfragen des Fragensatzes
# (evaluation/fragen/deutung_rollen_2026-08-31.json):
# konstr-korrelat-fenster traegt "gefolgt von", "beliebige Token",
# "Distanzgrenze", "Mittelstueck" und "zweiteilige".
# konstr-scharnier-dreigliedrig traegt "Scharnier", "aus drei Teilen" und
# "Signalwort".
KONSTRUKTIONS_FORM_CUES: Tuple[str, ...] = (
    # Reihenfolge
    "gefolgt von",
    "unmittelbar vor",
    "unmittelbar nach",
    "unmittelbar davor",
    "unmittelbar danach",
    "wortfolge",
    "wortabfolge",
    # Abstand
    "beliebige token",
    "token dazwischen",
    "token abstand",
    "distanzgrenze",
    "mittelstück",
    "mittelstueck",
    # Benannter Konstruktionstyp
    "scharnier",
    "korrelat",
    "signalwort",
    "zweiteilig",
    "dreiteilig",
    "dreigliedrig",
    "aus drei teilen",
)

# WARUM HIER KEINE SCHWACHEN CUES MEHR STEHEN.
#
# Bis zum 2026-09-03 fuehrte dieses Modul "konstruktion", "muster mit",
# "signalwort", "abstand" und "fenster" als schwache Cues, von denen ZWEI
# wie ein starker zaehlten. Gemessen ueber alle fuenf Fragensaetze unter
# evaluation/fragen/ war das die haeufigste Fehlerquelle des ganzen
# Cue-Satzes, weil "abstand" und "fenster" gerade in Kollokations- und
# Verlaufsfragen zusammen auftreten, also in genau den Frageformen, die
# der Kommentar ausschliessen wollte:
#
#   "Welche Kollokationen hat Herausforderung im Fenster von fuenf Token,
#    und spielt der Abstand dabei eine Rolle?"   assoziation -> gebrauch_kwic
#   "Wie entwickelt sich das Wort Aspekt ueber die Jahre, im Fenster 2019
#    bis 2024 und mit welchem Abstand zwischen den Erhebungen?"
#                                                verlauf     -> gebrauch_kwic
#   modellkontrast_2026-09-01 claude-gegen-gpt-konstruktion
#                                                frequenz    -> gebrauch_kwic
#
# Der letzte Fall lief ueber "konstruktion" plus "abstand", also ueber zwei
# Woerter, die beide nichts ueber die Suchform sagen. "Fenster" und
# "Abstand" sind das Standardvokabular der Kollokationsanalyse. Sie sind
# gestrichen, "signalwort" ist zu den starken Cues gewandert (es benennt
# ein Element der gesuchten Abfolge), und aus dem Rest ist die
# Metamarker-Liste unten geworden, die nur noch eine Aufgabe hat: zu
# unterscheiden, ob ein zweiteiliger Konnektor ERWAEHNT oder GEBRAUCHT
# wird.

KONSTRUKTIONS_CUES: Tuple[str, ...] = KONSTRUKTIONS_FORM_CUES

# Woerter, die einen Ausdruck als Untersuchungsgegenstand markieren.
# Bewusst eng: "muster" allein ist zu generisch, "muster mit" benennt eine
# Zusammensetzung.
KONSTRUKTIONS_METAMARKER: Tuple[str, ...] = (
    "konstruktion",
    "muster mit",
    "wendung",
    "satzbau",
    "vom typ",
)

# Distinguish mentioning a two-part connector from using it in a question.
# The connector counts as a search subject only when quotation marks,
# ellipsis or a metalinguistic cue identify it. Otherwise ordinary wording
# such as "nicht nur die Frequenz, sondern auch die Verteilung" would
# override a request for frequency or distribution analysis.
_KONSTRUKTIONS_PAARE: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\w)nicht nur\b.{0,60}?\bsondern auch(?!\w)", re.S),
    re.compile(r"(?<!\w)zwar\b.{0,60}?\baber(?!\w)", re.S),
)

_AUSLASSUNG = ("...", "…")


def _paar_wird_erwaehnt(lowered: str, treffer: re.Match[str]) -> bool:
    """Ist der Konnektor Gegenstand der Frage und nicht ihre Syntax?"""
    stelle = treffer.group(0)
    if any(zeichen in stelle for zeichen in _AUSLASSUNG):
        return True
    davor = lowered[max(0, treffer.start() - 2) : treffer.start()]
    if any(zeichen in davor for zeichen in _ANFUEHRUNG):
        return True
    return any(
        starker_treffer(lowered, marker)
        for marker in KONSTRUKTIONS_METAMARKER
    )


def _erwaehnte_paare(lowered: str) -> List[re.Match[str]]:
    treffer: List[re.Match[str]] = []
    for muster in _KONSTRUKTIONS_PAARE:
        fund = muster.search(lowered)
        if fund is not None and _paar_wird_erwaehnt(lowered, fund):
            treffer.append(fund)
    return treffer


def konstruktions_cues(frage: str) -> Tuple[str, ...]:
    """Alle getroffenen Konstruktions-Cues, in kanonischer Reihenfolge."""
    lowered = routing_text(frage)
    if not lowered:
        return ()
    treffer = [
        cue for cue in KONSTRUKTIONS_FORM_CUES if starker_treffer(lowered, cue)
    ]
    treffer.extend(fund.re.pattern for fund in _erwaehnte_paare(lowered))
    return tuple(treffer)


def ist_konstruktionsfrage(frage: str) -> bool:
    """Beschreibt die Frage eine Konstruktion als Suchform?

    Ein starker Form-Cue genuegt, ebenso ein zweiteiliger Konnektor, der
    als Gegenstand markiert ist. Fuer die ROUTING-Entscheidung reicht das
    nicht, dafuer siehe ``ist_konstruktions_suchauftrag``.
    """
    lowered = routing_text(frage)
    if not lowered:
        return False
    if any(starker_treffer(lowered, cue) for cue in KONSTRUKTIONS_FORM_CUES):
        return True
    return bool(_erwaehnte_paare(lowered))


# Ein Beleg-, Beispiel- oder Konkordanzwunsch. ``beleg`` matcht flexions-
# genau, "Belegzahl" ist deshalb keiner (der Kompositum-Innentreffer war
# schon beim Trigger-Scan die Quelle frischer Fehlroutings), "Belegstelle"
# steht darum als eigener Eintrag.
BELEG_CUES: Tuple[str, ...] = (
    "beleg",
    "belegstelle",
    "belegzeile",
    "beispiel",
    "kwic",
    "konkordanz",
    "textstelle",
    "fundstelle",
    "zitat",
)


def verlangt_belege(frage: str) -> bool:
    """Will die Frage Textstellen sehen und nicht nur Zahlen?"""
    lowered = _normalised_question_text(frage)
    if not lowered:
        return False
    return any(starker_treffer(lowered, cue) for cue in BELEG_CUES)


def ist_konstruktions_suchauftrag(frage: str) -> bool:
    """Select the evidence recipe for a construction search requesting examples.

    ``gebrauch_kwic`` supplies concordance rows through ``run_cqlf_query``.
    Require an explicit request for examples as well as construction cues
    so a request for normalized rates or group comparisons keeps its analysis route.
    """
    return ist_konstruktionsfrage(frage) and verlangt_belege(frage)


# --------------------------------------------------------------------------- #
# Kandidatenlisten                                                             #
# --------------------------------------------------------------------------- #

# Woerter, hinter denen eine aufgezaehlte Kandidatenliste steht. Die
# Ankerpruefung ist wortgrenzen-genau, damit "Wortlisten" (Frage
# deutung-stilmerkmale-paarig) den Anker "liste" nicht ausloest.
KANDIDATEN_ANKER: Tuple[str, ...] = (
    "marker",
    "liste",
    "kandidat",
    "angeblich",
)

# Eine Liste allein ist noch kein Kontrast. Erst die Frage, ob sie haelt,
# macht sie zu einem Gruppenvergleich. Ohne diesen Cue bleibt die
# Aufzaehlung eine Frequenzfrage ("Wie haeufig sind A, B und C?").
#
# WORTGRENZEN GELTEN HIER GENAUSO wie bei den Ankern. Bis zum 2026-09-03
# lief die Pruefung als rohes ``cue in lowered``, und damit traf "halten"
# in "enthalten" und "stimmt" in "bestimmt". Gemessen, vorher gegen
# nachher:
#
#   "Welche Dokumente enthalten die Marker Herausforderung, Aspekt,
#    entscheidend und zudem? Ich will nur die Trefferzahl."
#                                                frequenz -> kontrast
#   "In der Liste Herausforderung, Aspekt, entscheidend, zudem ist
#    bestimmt etwas Brauchbares. Wie haeufig sind sie?"
#                                                frequenz -> kontrast
KANDIDATEN_GELTUNGS_CUES: Tuple[str, ...] = (
    "prüf",
    "pruef",
    "hält",
    "haelt",
    "halten",
    "in die andere richtung",
    "stimmt",
    "trifft zu",
    "bestätig",
    "bestaetig",
    "robust",
    "belastbar",
)

_LISTEN_TRENNER = re.compile(r"\s*(?:,|;|\boder\b|\bund\b|\bsowie\b)\s*")

#: Anchors and separators of an English question. Only an English question
#: reads them (``is_english_question``), so a German question keeps its
#: German parse. The German anchors stay valid ("markers").
KANDIDATEN_ANKER_EN: Tuple[str, ...] = (
    "list",
    "candidate",
    "alleged",
    "allegedly",
    "supposed",
    "supposedly",
    "so-called",
)
_LISTEN_TRENNER_EN = re.compile(r"\s*(?:,|;|\bor\b|\band\b|\bas well as\b)\s*")
_SATZ_ENDE = re.compile(r"[?!]|\.(?:\s|$)")

#: Mindestlaenge einer Kandidatenliste. Zwei Terme sind ein Paar und
#: koennen jeder Nebensatz sein, ab drei ist es eine Aufzaehlung.
KANDIDATEN_MINDESTZAHL = 3

#: Mehr als drei Woerter ist Prosa, kein Kandidat.
_KANDIDAT_MAX_WOERTER = 3


def _ende_des_ankerworts(lowered: str, start: int) -> int:
    """Position hinter dem Anker samt Flexionsendung."""
    ende = start
    while ende < len(lowered) and _is_word_char(lowered[ende]):
        ende += 1
    return ende


def kandidatenliste_aus_frage(frage: str) -> Tuple[str, ...]:
    """Die aufgezaehlten Kandidaten hinter einem Listen-Anker.

    Deterministischer Parser, kein Modellaufruf. Gemessen an
    gemischt-markerliste-robustheit ("Es kursieren ueberall Listen
    angeblicher KI-Marker: Herausforderung, Aspekt, entscheidend, darueber
    hinaus, zudem, essentiell, massgeblich."): sieben Kandidaten. Die
    uebrigen sieben Fragen des Satzes ergeben die leere Liste.

    DER ANKER GEHOERT NICHT IN DEN ERSTEN KANDIDATEN, und ein Geltungs-Cue
    nicht in den letzten. Bis zum 2026-09-03 begann der Rest AN der
    Ankerposition und wurde nur bei einem Doppelpunkt beschnitten. Die
    einzige gemessene Frage hat einen Doppelpunkt, deshalb fiel es nicht
    auf. Ohne ihn kam Falsches heraus:

        "Wie haeufig sind die Marker zudem, ferner und ueberdies?"
            -> ("Marker zudem", "ferner", "ueberdies")
        "Nimm die Kandidaten Herausforderung, Aspekt, entscheidend und
         pruef sie durch."
            -> ("Kandidaten Herausforderung", "Aspekt", "entscheidend",
                "pruef sie durch")

    P7 (Termlisten-Modus des Kontrastrezepts) haette damit Suchterme
    bekommen, die es im Korpus nicht gibt.
    """
    text = str(frage or "")
    lowered = text.lower()
    if not lowered:
        return ()
    englisch = is_english_question(text)
    anker_liste = KANDIDATEN_ANKER + (KANDIDATEN_ANKER_EN if englisch else ())
    trenner = _LISTEN_TRENNER_EN if englisch else _LISTEN_TRENNER
    positionen = [
        pos
        for pos in (
            starke_treffer_position(lowered, anker)
            for anker in anker_liste
        )
        if pos >= 0
    ]
    if not positionen:
        return ()
    rest = text[_ende_des_ankerworts(lowered, min(positionen)) :]
    ende = _SATZ_ENDE.search(rest)
    if ende is not None:
        rest = rest[: ende.start()]
    # Ein Doppelpunkt eroeffnet die Aufzaehlung nur, wenn er VOR dem
    # ersten Trenner steht. Danach gehoert er zum Rest des Satzes.
    doppelpunkt = rest.find(":")
    erster_trenner = trenner.search(rest)
    if doppelpunkt >= 0 and (
        erster_trenner is None or doppelpunkt < erster_trenner.start()
    ):
        rest = rest[doppelpunkt + 1 :]
    kandidaten: List[str] = []
    for roh in trenner.split(rest):
        eintrag = roh.strip().strip(_ANFUEHRUNG).strip()
        woerter = eintrag.split()
        if not eintrag or len(woerter) > _KANDIDAT_MAX_WOERTER:
            # Eine Aufzaehlung ist zusammenhaengend. Beim ersten
            # Nicht-Kandidaten ist sie zu Ende, sonst sammelt der Parser
            # Prosa aus dem Rest des Satzes ein.
            break
        if _traegt_geltungs_cue(eintrag, englisch):
            # "... entscheidend und pruef sie durch" endet bei "pruef".
            break
        kandidaten.append(eintrag)
    if len(kandidaten) < KANDIDATEN_MINDESTZAHL:
        return ()
    return tuple(kandidaten)


def _traegt_geltungs_cue(text: str, englisch: bool | None = None) -> bool:
    """Carries ``text`` a validity cue?

    ``englisch`` is the language of the whole question when ``text`` is one
    list item, too short to classify on its own. Without it the text is the
    whole question and ``starker_treffer`` reads its language itself.
    """
    lowered = _normalised_question_text(text)
    if not lowered:
        return False
    if englisch is None:
        return any(
            starker_treffer(lowered, cue) for cue in KANDIDATEN_GELTUNGS_CUES
        )
    gelesen = render_cues(lowered) if englisch else lowered
    return any(
        starke_treffer_position(gelesen, cue) >= 0
        for cue in KANDIDATEN_GELTUNGS_CUES
    )


def ist_kandidatenlisten_pruefung(frage: str) -> bool:
    """Wird eine mitgelieferte Kandidatenliste auf ihre Geltung geprueft?"""
    if not kandidatenliste_aus_frage(frage):
        return False
    return _traegt_geltungs_cue(frage)


__all__: Sequence[str] = (
    "BELEG_CUES",
    "KANDIDATEN_ANKER",
    "KANDIDATEN_ANKER_EN",
    "KANDIDATEN_GELTUNGS_CUES",
    "KANDIDATEN_MINDESTZAHL",
    "KONSTRUKTIONS_CUES",
    "KONSTRUKTIONS_FORM_CUES",
    "KONSTRUKTIONS_METAMARKER",
    "ROUTING_STAGE_FRAGEFORM",
    "ist_kandidatenlisten_pruefung",
    "ist_konstruktions_suchauftrag",
    "ist_konstruktionsfrage",
    "kandidatenliste_aus_frage",
    "konstruktions_cues",
    "starke_treffer_position",
    "starker_treffer",
    "verlangt_belege",
)
