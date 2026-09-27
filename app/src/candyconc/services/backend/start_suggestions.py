# -*- coding: utf-8 -*-
"""Suggestions from the corpus that is actually loaded.

The example questions of the recipes are hard-wired and can name things
that do not exist in the loaded corpus:

    "Welche Schluesselwoerter sind typisch fuer das Teilkorpus 'news' im
     Vergleich zum Teilkorpus 'chat'?"
    "Wie entwickelt sich 'Inflation' ueber die Zeit im Korpus?"

A corpus without subcorpora 'news' and 'chat' and without a time axis
answers such a suggestion with an honest empty result. That is worse than
no suggestion, because it costs work and delivers nothing. The axes the
corpus does have (for example text_type, model, register or source)
support the questions users actually ask.

TWO RULES.

First: a suggestion names only values that OCCUR in the corpus. No
invented subcorpora, no invented search terms.

Second: a suggestion is made only when the corpus can answer it. If the
axis is missing, the suggestion is dropped. A method without a suitable
axis thus disappears from the list instead of offering a question that
leads nowhere.

The result is a recipe list that tells the user what works HERE, not what
would work somewhere.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Sequence

from candyconc.i18n import lt

logger = logging.getLogger(__name__)

#: Achsen, die einen Kontrast tragen, in absteigender Aussagekraft.
#: Eine zweiwertige Achse ist die staerkste: sie ergibt genau EINEN
#: Kontrast und braucht keine Auswahl.
KONTRASTACHSEN = ("text_type", "register", "model", "source", "variant")

#: Achsen, die ein Inventar tragen. Identifikatoren gehoeren nicht dazu:
#: 19.272 Werte von ``origin_id`` sind keine Struktur, sondern eine Liste.
INVENTARACHSEN = ("register", "text_type", "model", "source", "profile_name")

#: Ab so vielen Werten ist eine Achse ein Identifikator und keine Struktur.
MAX_WERTE_JE_ACHSE = 40

#: So viele Vorschlaege je Rezept, hoechstens. Mehr ist eine Liste zum
#: Durchlesen, und Durchlesen war nie das Problem des Nutzers.
MAX_JE_REZEPT = 1


def _werte(idx: Any, feld: str) -> List[str]:
    try:
        werte = [str(w).strip() for w in idx.metadata_values(feld)]
    except Exception:
        return []
    return [w for w in werte if w]


def achsen(idx: Any) -> Dict[str, List[str]]:
    """Die nutzbaren Metadatenachsen mit ihren Werten.

    Identifikatorartige Achsen fallen heraus. ``origin_id`` mit 19.272
    Werten beantwortet keine Frage, es benennt Dokumente.
    """
    heraus: Dict[str, List[str]] = {}
    try:
        felder = list(idx.metadata_fields())
    except Exception:
        logger.debug("Metadatenfelder nicht lesbar", exc_info=True)
        return heraus
    for feld in felder:
        werte = _werte(idx, feld)
        if 2 <= len(werte) <= MAX_WERTE_JE_ACHSE:
            heraus[str(feld)] = werte
    return heraus


def _beste_kontrastachse(vorhanden: Mapping[str, Sequence[str]]) -> tuple[str, str, str] | None:
    """Feld und zwei Werte fuer einen Kontrast, oder nichts.

    The axes of KONTRASTACHSEN come first. A corpus that has none of them
    (a State of the Union corpus with ``party``, ``president``, ``decade``)
    still has contrast axes: then the axis with the fewest values wins,
    because two values give exactly one contrast. Ties keep the field order.
    """
    for feld in KONTRASTACHSEN:
        werte = list(vorhanden.get(feld) or ())
        if len(werte) >= 2:
            return feld, werte[0], werte[1]
    kandidaten = [
        (len(werte), position, feld)
        for position, (feld, werte) in enumerate(vorhanden.items())
        if len(werte) >= 2
    ]
    if not kandidaten:
        return None
    _, _, feld = min(kandidaten)
    werte = list(vorhanden[feld])
    return feld, werte[0], werte[1]


def _bestes_inventarfeld(vorhanden: Mapping[str, Sequence[str]]) -> str:
    """The field for the inventory question.

    Without one of INVENTARACHSEN the axis with the fewest values wins, as
    for the contrast. The first field in order was often a per-document
    field (``author`` with one value per text in a corpus of 30 texts).
    """
    for feld in INVENTARACHSEN:
        if vorhanden.get(feld):
            return feld
    kandidaten = [
        (len(werte), position, feld)
        for position, (feld, werte) in enumerate(vorhanden.items())
        if werte
    ]
    return min(kandidaten)[2] if kandidaten else ""


def vorschlaege(idx: Any) -> Dict[str, str]:
    """Je Rezept eine Beispielfrage, die DIESES Korpus beantworten kann.

    Rezepte ohne passende Achse fehlen im Ergebnis. Der Aufrufer laesst sie
    dann bei ihrer statischen Beispielfrage oder blendet sie aus, aber er
    erfindet keine.
    """
    vorhanden = achsen(idx)
    if not vorhanden:
        return {}
    heraus: Dict[str, str] = {}

    kontrast = _beste_kontrastachse(vorhanden)
    if kontrast:
        feld, a, b = kontrast
        heraus["kontrast"] = lt(
            "Welche Wörter sind typisch für {feld}={a} im Vergleich zu "
            "{feld}={b}, und was sagt der Unterschied über die beiden aus?",
            "Which words are typical of {feld}={a} compared with "
            "{feld}={b}, and what does the difference say about the two?",
        ).format(feld=feld, a=a, b=b)

    inventar = _bestes_inventarfeld(vorhanden)
    if inventar:
        anzahl = len(vorhanden[inventar])
        heraus["metadaten_struktur"] = lt(
            "Welche {anzahl} Werte hat das Feld {inventar}, und wie groß "
            "ist jeder Teil?",
            "Which {anzahl} values does the field {inventar} have, and how "
            "large is each part?",
        ).format(anzahl=anzahl, inventar=inventar)
        heraus["exploration_meta"] = lt(
            "Verschaffe mir einen Überblick: welche Felder gibt es, und "
            "wie verteilt sich das Korpus auf {inventar}?",
            "Give me an overview: which fields are there, and how is the "
            "corpus distributed across {inventar}?",
        ).format(inventar=inventar)

    if kontrast:
        feld, a, b = kontrast
        heraus["assoziation"] = lt(
            "Vergleiche die Kollokationen eines häufigen Wortes zwischen "
            "{feld}={a} und {feld}={b}.",
            "Compare the collocations of a frequent word between "
            "{feld}={a} and {feld}={b}.",
        ).format(feld=feld, a=a, b=b)

    # Build usage constructions in the corpus language. The system prompt
    # supports distance syntax, and this recipe needs no metadata value.
    paar = CONSTRUCTION_BY_LANGUAGE.get(corpus_language(idx) or "de")
    if paar is not None:
        erster, zweiter = paar
        heraus["gebrauch_kwic"] = lt(
            "Wo steht \"{erster}\" mit bis zu acht Token Abstand vor "
            "\"{zweiter}\", und in welchen Texten häuft sich das?",
            "Where does \"{erster}\" occur up to eight tokens before "
            "\"{zweiter}\", and in which texts does this cluster?",
        ).format(erster=erster, zweiter=zweiter)
    return heraus


#: The two-part connector of the construction suggestion, per corpus
#: language (ISO 639-1). A corpus in another language gets no construction
#: suggestion instead of a German one.
CONSTRUCTION_BY_LANGUAGE: Dict[str, tuple[str, str]] = {
    "de": ("nicht nur", "sondern auch"),
    "en": ("not only", "but also"),
}


def corpus_language(idx: Any) -> str:
    """Language of the corpus as ISO 639-1 code, empty when unknown.

    Read from the index manifest (``language``, recorded by the build). An
    older index without it falls back to the annotation pipeline
    (``dependency_label_scheme``: German or English spaCy pipeline). Empty
    means unknown, and ``vorschlaege`` then keeps the German construction it
    offered before the language was read.
    """
    manifest = getattr(idx, "manifest", None)
    sprache = str(getattr(manifest, "language", "") or "").strip().lower()
    if not sprache:
        pfad = getattr(idx, "path", None)
        if pfad:
            try:
                from candyconc.domain.corpus import dependency_label_scheme

                schema = dependency_label_scheme(pfad)
            except Exception:
                schema = None
            sprache = {"tiger": "de", "clearnlp": "en"}.get(str(schema or ""), "")
    return sprache.split("-")[0].split("_")[0]


def zeitachse_vorhanden(idx: Any) -> bool:
    """Traegt das Korpus eine Zeitachse, die ein Verlauf braucht?

    Ohne sie ist "Wie entwickelt sich X ueber die Zeit" nicht beantwortbar,
    und der Vorschlag gehoert nicht in die Liste.
    """
    try:
        roh = [str(f) for f in idx.metadata_fields()]
    except Exception:
        return False
    felder = {f.lower() for f in roh}
    if felder & {"date", "jahr", "year", "datum", "protocol_date"}:
        return True
    # A time axis under another name ("published", "Jahrgang") is found by
    # its values, with the same check the copilot's corpus card uses.
    try:
        from candyconc.candyconc_copilot.prompts import _detect_date_fields

        return bool(_detect_date_fields(idx, roh))
    except Exception:
        logger.debug("Datumsfelder nicht erkennbar", exc_info=True)
        return False
