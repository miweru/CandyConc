# -*- coding: utf-8 -*-
"""English questions, read with the German cue vocabulary of the router.

The deterministic routing (recipe triggers, the cue branches of
``grounding_contracts.heuristic_analysis_contract``, the interpretation cues
of ``question_kind`` and the keyword flags of ``tooling.tool_selection``) is
written in German. An English question matched none of it: every English
question needed the recipe classifier, got the smaller tool space of the
recipe contract, and fell into the free mode when the classifier failed,
while the same question in German was routed by its wording.

This module renders the wording of an English question into the German cue
vocabulary, so that every cue list reads the English question the way it
reads the German one. The rendering replaces English cue phrases and the
function words the cue patterns depend on ("between ... and" becomes
"zwischen ... und") and leaves every other word as it is. It is not a
translation and never leaves the router: tool arguments, search terms and
the text the model reads come from the original question.

German questions are not touched. ``routing_text`` returns exactly
``normalisierte_frage`` for every question that ``is_english_question`` does
not classify as English, so the German routing stays byte-identical.

Two rules keep the rendering from inventing cues:

* Quoted search terms are never rendered. "How often does 'compare' occur?"
  asks for the word, not for a comparison.
* Every phrase matches at word boundaries only, so "use" never matches inside
  "because" and "hit" never inside "white".

The module depends on ``re`` only, like ``candyconc.question_kind``, so the
contract layer and ``candyconc.tooling`` can both import it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Tuple

#: Function words that occur only in English questions. Words that are also
#: German ("in", "an", "was", "will", "so", "also", "die", "man", "war",
#: "am", "hat") are not counted.
ENGLISH_FUNCTION_WORDS = frozenset(
    """
    the of and or is are were be been being does do did how what which who
    whom whose why when where this these that those it its they them their
    there than between across over about with from for to by on at into can
    could would should may might must not most more many much often each
    every all any some only both whether if my me you your we our us i he
    she his her has have had show give
    """.split()
)

#: Function words of German questions. Used only against the English count.
#: Words that are also English ("was", "war", "am") are not counted: "When
#: was the word first used?" is English.
GERMAN_FUNCTION_WORDS = frozenset(
    """
    der die das den dem des ein eine einen einem einer eines und oder ist
    sind waren wird werden wurde wie welche welcher welches welchen wer
    warum wann wo woran worin von mit für fuer auf aus bei nach über ueber
    im zum zur sich nicht kein keine es sie er wir ich du mir mich dass daß
    auch noch nur als zu gibt kommt haben hat man dieser diese dieses diesen
    zwischen unter vor durch gegen sowie ob wenn sondern aber beim vom um
    ins
    """.split()
)

#: Quoted spans that the rendering leaves alone. An opening quote must not
#: follow a word character and a closing quote must not precede one, so the
#: apostrophes of "what's" or "Democrats' speeches" open no quote.
_QUOTED = re.compile(
    r"""(?<!\w)["'`„“‘‚»›]([^"'`„“”‘’‚»«›‹\n]{1,80})["'`“”‘’»«›‹](?!\w)"""
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

#: English phrase (regular expression, lower case) and its German cue
#: rendering. Each entry names what a German question writes for the same
#: meaning, so each German cue list reacts to it exactly as to the German
#: question. Grouped by the cue family they feed. The rendering is one pass
#: over a single alternation, ordered by ``_ORDERED`` so that a phrase of
#: several words is tried before a shorter one starting at the same word
#: ("word sketch" before "word").
CUE_PHRASES: Tuple[Tuple[str, str], ...] = (
    # Noun compounds. German writes them as one word, and the cue lists
    # treat a trigger inside a compound as weak ("Kollokationslisten" is no
    # strong "kollokation" trigger). The rendering keeps that reading.
    (r"collocation lists?", "kollokationslisten"),
    (r"collocation profiles?", "kollokationsprofil"),
    (r"collocation networks?", "kollokationsnetz"),
    (r"association measures?", "assoziationsmaß"),
    (r"word frequenc(?:y|ies)", "wortfrequenz"),
    (r"frequency distributions?", "häufigkeitsverteilung"),
    (r"keyword lists?", "schlüsselwortliste"),
    (r"attestation passages?", "belegstellen"),
    # Collocation and co-occurrence
    (r"collocational partners?|collocation partners?", "kollokationspartner"),
    (r"collocates", "kollokate"),
    (r"collocate", "kollokat"),
    (r"collocations", "kollokationen"),
    (r"collocation(?:al)?", "kollokation"),
    (r"co-?occurrences?", "kookkurrenz"),
    (r"co-?occurs? with|co-?occurring with", "zusammen mit"),
    (r"(?:occurs?|appears?|occurring|appearing) together with", "zusammen mit"),
    (r"together with", "zusammen mit"),
    (r"(?:words|neighbou?rs) (?:near|close to|around)", "wörter in der nähe von"),
    (r"neighbou?ring words|neighbou?r words", "nachbarwörter"),
    (r"accompanying words|companion words", "begleitwörter"),
    (r"surrounding words", "umgebungswörter"),
    (r"(?:the )?immediate (?:vicinity|surroundings|environment) of", "unmittelbare umfeld von"),
    (r"(?:the )?(?:vicinity|surroundings|lexical environment) of", "umfeld von"),
    (r"neighbou?rhood of", "nachbarschaft von"),
    (r"stands next to", "steht neben"),
    (r"stand next to", "stehen neben"),
    (r"typically next to", "typischerweise neben"),
    (r"next to", "neben"),
    (r"statistically (?:salient|conspicuous|striking)", "statistisch auffällig"),
    (r"associations?", "assoziation"),
    (r"associated", "assoziiert"),
    # Contrast and keyness
    (r"keywords", "schlüsselwörter"),
    (r"key words", "schlüsselwörter"),
    (r"keyword", "schlüsselwort"),
    (r"(?:as )?compared (?:with|to)|in comparison (?:with|to)", "im vergleich zu"),
    (r"comparisons? between", "vergleich zwischen"),
    (r"comparisons? of", "vergleich von"),
    (r"comparisons", "vergleiche"),
    (r"comparison", "vergleich"),
    (r"compare|comparing|compared", "vergleiche"),
    (r"differences? between", "unterschiede zwischen"),
    (r"differences", "unterschiede"),
    (r"difference", "unterschied"),
    (r"differs(?: from)?", "unterscheidet sich"),
    (r"differ(?:ed)?(?: from)?", "unterscheiden sich"),
    (r"different(?:ly)?", "unterschiedlich"),
    (r"distinguish(?:es|ed)?|differentiat(?:e|es|ed)", "unterscheide"),
    (r"in contrast (?:to|with)", "im kontrast zu"),
    (r"contrasts?(?: with)?", "kontrast"),
    (r"contrasting", "kontrastiere"),
    (r"typical (?:of|for)", "typisch für"),
    (r"typically", "typischerweise"),
    (r"typical words", "typische wörter"),
    (r"typical", "typisch"),
    (r"characteristic(?:ally)? (?:of|for)", "charakteristisch für"),
    (r"characteristics?", "charakteristisch"),
    (r"distinctive", "distinktiv"),
    (r"peculiarit(?:y|ies)", "eigenheit"),
    (r"special features?|particularit(?:y|ies)", "besonderheit"),
    (r"sub-?corpora", "subkorpora"),
    (r"sub-?corpus", "subkorpus"),
    (r"document sets?", "docset"),
    (r"more often|more frequent(?:ly)?", "häufiger"),
    (r"less often|less frequent(?:ly)?|rarer|more rarely", "seltener"),
    (r"against", "gegen"),
    # Frequency and distribution
    (r"how often|how many times", "wie oft"),
    (r"how frequent(?:ly)?", "wie häufig"),
    (r"most (?:frequent|common)|commonest", "häufigste"),
    (r"frequently|frequent", "häufig"),
    (r"frequency lists?", "frequenzliste"),
    (r"word lists?", "wortliste"),
    (r"frequenc(?:y|ies)", "frequenz"),
    (r"hit counts?|number of hits", "trefferzahl"),
    (r"raw hits|raw counts", "rohtreffer"),
    (r"hits", "treffer"),
    (r"per million", "pro million"),
    (r"normali[sz]\w*", "normalisiert"),
    (r"broken down by|break(?:s)? (?:it )?down by|breakdown by", "aufgeschlüsselt nach"),
    (r"denominators?", "nenner"),
    (r"occurrences", "vorkommen"),
    (r"occurs?|occurring|appears?|appearing", "kommt vor"),
    (r"ranking|rank list", "rangliste"),
    (r"distributions?", "verteilung"),
    (r"distributed", "verteilt"),
    # Usage and concordance
    (r"kwic lines?", "kwic-belegzeilen"),
    (r"concordance lines?", "belegzeilen"),
    (r"concordances?", "konkordanz"),
    (r"in context", "im kontext"),
    (r"visible context", "sichtbarer kontext"),
    (r"extended context", "erweiterter kontext"),
    (r"(?:wider|broader) context", "breiterer kontext"),
    (r"full context", "vollständiger kontext"),
    (r"contexts?", "kontext"),
    (r"expand(?:ed|s)?", "erweitere"),
    (r"(?:the )?uses? of", "gebrauch von"),
    (r"usage", "gebrauch"),
    (r"used", "verwendet"),
    (r"uses", "verwendet"),
    (r"(?:matching|suitable|fitting) examples", "passende beispiele"),
    (r"examples from", "beispiele aus"),
    (r"text examples?", "textbeispiele"),
    (r"examples", "beispiele"),
    (r"example", "beispiel"),
    (r"evidence|instances", "belege"),
    (r"instance", "beleg"),
    (r"attestations?", "beleg"),
    (r"(?:text )?passages? in (?:the )?texts?|text passages?", "textstellen"),
    (r"quotations?|quotes?", "zitat"),
    (r"random sample", "zufallsstichprobe"),
    (r"samples?", "stichprobe"),
    (r"draw", "ziehe"),
    (r"full text|entire text|whole text", "volltext"),
    (r"read the document", "lies das dokument"),
    (r"show the text", "zeige den text"),
    (r"source text", "quelltext"),
    # Time
    (r"over time|across time|through time", "über die zeit"),
    (r"time course|diachronic(?:ally)?|diachrony", "diachron"),
    (r"time series", "zeitreihe"),
    (r"time axis", "zeitachse"),
    (r"development of", "entwicklung von"),
    (r"develops?|evolves?", "entwickelt sich"),
    (r"per year|each year|every year", "pro jahr"),
    (r"by year", "nach jahr"),
    (r"per month|each month", "pro monat"),
    (r"monthly", "monatlich"),
    (r"yearly|annually|annual", "jährlich"),
    (r"legislative periods?|electoral terms?", "wahlperiode"),
    (r"across", "hinweg"),
    # Corpus, metadata and structure
    (r"metadata fields?", "metadatenfelder"),
    (r"metadata", "metadaten"),
    (r"which registers", "welche register"),
    (r"which sources", "welche quellen"),
    (r"what is in the corpus", "was ist im korpus"),
    (r"what does the corpus contain", "was enthält das korpus"),
    (r"(?:the )?structure of the corpus", "struktur des korpus"),
    (r"(?:the )?(?:composition|make-?up) of the corpus", "zusammensetzung des korpus"),
    (r"corpus", "korpus"),
    (r"corpora", "korpora"),
    (r"documents", "dokumente"),
    (r"document", "dokument"),
    (r"texts", "texte"),
    (r"sources", "quellen"),
    (r"source", "quelle"),
    (r"words", "wörter"),
    (r"word", "wort"),
    (r"terms", "begriffe"),
    (r"term", "begriff"),
    # Exploration and method help
    (r"what stands out|what is striking|what is noticeable", "was fällt auf"),
    (r"strikingly|conspicuously|noticeably", "auffällig"),
    (r"striking|conspicuous|salient|noticeable", "auffällig"),
    (r"interesting", "interessant"),
    (r"remarkable|notable|noteworthy", "bemerkenswert"),
    (r"observations?", "beobachtung"),
    (r"findings?", "befund"),
    (r"give me an overview", "gib mir einen überblick"),
    (r"overview", "überblick"),
    (r"investigate|examine", "untersuche"),
    (r"explore|exploring", "erkunden"),
    (r"(?:which|what) (?:topics|themes)", "welche themen"),
    (r"(?:central|main) (?:topics|themes)", "zentrale themen"),
    (r"thematic(?:ally)?", "thematisch"),
    (r"what is it about", "worum geht"),
    (r"hypotheses", "hypothesen"),
    (r"hypothesis", "hypothese"),
    (r"characteri[sz](?:e|es|ed|ing|ation|ations)", "charakterisiere"),
    (r"linguistic style", "sprachstil"),
    (r"style", "stil"),
    (r"research questions?", "forschungsfragen"),
    (r"follow-?up questions?", "anschlussfragen"),
    (r"which questions", "welche fragen"),
    (r"further questions", "weitere fragen"),
    (r"next questions", "nächsten fragen"),
    (r"(?:which|what) (?:investigations|analyses)", "welche untersuchungen"),
    (r"about this corpus", "über dieses korpus"),
    (r"overall", "insgesamt"),
    (r"first (?:three )?analysis steps", "erste analyseschritte"),
    (r"first three steps", "erste drei schritte"),
    (r"first steps", "erste schritte"),
    (r"would you recommend", "würdest du empfehlen"),
    (r"how would you (?:start|begin)", "wie würdest du anfangen"),
    (r"how (?:to|do i|should i) (?:start|begin)|where (?:to|do i|should i) start", "wie anfangen"),
    (r"how (?:do|should) i proceed", "wie gehe ich"),
    (r"how (?:do|should) we proceed", "wie gehen wir"),
    (r"methodologically|methodically", "methodisch"),
    (r"complementary evidence", "komplementäre evidenz"),
    (r"triangulat\w*", "triangulieren"),
    (r"only supporting evidence", "nur passende belege"),
    (r"confirm\w*", "bestätige"),
    (r"prove", "beweise"),
    # Word sketch, n-grams, lexical diversity, semantics
    (r"word[- ]?sketch(?:es)?", "word sketch"),
    (r"word profile", "wortprofil"),
    (r"grammatical profile", "grammatisches profil"),
    (r"grammatical relations?", "grammatische relationen"),
    (r"exact word sequence", "exakte wortfolge"),
    (r"multi-?word sequences?", "mehrwortfolge"),
    (r"word sequences?|word order", "wortfolge"),
    (r"bigrams?", "bigramm"),
    (r"trigrams?", "trigramm"),
    (r"lexical diversity", "lexikalische diversität"),
    (r"lexical variety", "lexikalische vielfalt"),
    (r"lexical(?:ly)?", "lexikalisch"),
    (r"vocabulary", "wortschatz"),
    (r"synonyms", "synonyme"),
    (r"semantic fields?|word fields?", "wortfeld"),
    (r"semantically similar", "bedeutungsähnlich"),
    (r"central passages", "zentrale passagen"),
    (r"passages", "passagen"),
    (r"themes?", "thema"),
    (r"find", "finde"),
    (r"search", "suche"),
    (r"locate", "lokalisiere"),
    (r"data subsets?", "daten teilmenge"),
    # Construction and candidate lists
    (r"followed by", "gefolgt von"),
    (r"immediately before", "unmittelbar vor"),
    (r"immediately after", "unmittelbar nach"),
    (r"(?:any|arbitrary) tokens", "beliebige token"),
    (r"tokens in between", "token dazwischen"),
    (r"token distance", "token abstand"),
    (r"word distance", "wortabstand"),
    (r"distance limit", "distanzgrenze"),
    (r"middle (?:part|section)", "mittelstück"),
    (r"hinges?", "scharnier"),
    (r"(?:consists? )?of three parts", "aus drei teilen"),
    (r"correlatives?", "korrelat"),
    (r"signal words?", "signalwort"),
    (r"two-part|bipartite", "zweiteilig"),
    (r"three-part|tripartite", "dreiteilig"),
    (r"constructions?", "konstruktion"),
    (r"pattern with", "muster mit"),
    (r"idioms?|set phrases?|set expressions?|turns? of phrase", "wendung"),
    (r"sentence structure", "satzbau"),
    (r"of the type", "vom typ"),
    (r"not only", "nicht nur"),
    (r"but also", "sondern auch"),
    (r"candidates?", "kandidat"),
    (r"lists?", "liste"),
    (r"allegedly|alleged|supposed(?:ly)?|so-called", "angeblich"),
    (r"check|verify|test whether", "prüfe"),
    (r"holds? up|holds?", "hält"),
    (r"(?:is|are) (?:it|this|that|these|they) true", "stimmt"),
    (r"in the (?:opposite|other) direction|the other way round", "in die andere richtung"),
    (r"appl(?:y|ies) to", "trifft zu"),
    (r"reliable|robustly", "belastbar"),
    # Interpretation. "interpret" is a German cue as it stands.
    (r"place in context|situate|classify", "einordnen"),
    (r"contextuali[sz]\w*", "einordnung"),
    (r"explain the (?:evidence|example|line)", "erkläre den beleg"),
    # Function words the cue patterns depend on
    (r"as well as", "sowie"),
    (r"between", "zwischen"),
    (r"and", "und"),
    (r"or", "oder"),
    (r"with", "mit"),
    (r"of", "von"),
    (r"which", "welche"),
)

_ORDERED: Tuple[Tuple[str, str], ...] = tuple(
    sorted(CUE_PHRASES, key=lambda entry: (-entry[0].count(" "), -len(entry[0])))
)

_PHRASE_PATTERN = re.compile(
    "|".join(
        rf"(?P<g{number}>(?<!\w)(?:{pattern})(?!\w))"
        for number, (pattern, _) in enumerate(_ORDERED)
    )
)


def _words(text: str) -> Iterable[str]:
    return (match.group(0).lower() for match in _WORD.finditer(text))


def normalised_question(text: str) -> str:
    """Lower case, one hyphen, one space.

    The single implementation behind ``question_kind.normalisierte_frage``.
    """

    folded = str(text or "").lower()
    folded = re.sub(r"[‐‑‒–—−]", "-", folded)
    return " ".join(folded.split())


_normalised = normalised_question


def detect_question_language(text: str) -> str | None:
    """The shared language decision for routing and answer text.

    Counts English and German function words outside quoted terms. English
    needs more than twice as many English as German function words, and at
    least two of them unless no German one occurs at all. The margin keeps a
    German question with an unquoted English name ("Welche Kollokate hat
    'economy' in the State of the Union?") German.
    """

    unquoted = without_quoted_terms(text)
    english = german = 0
    for word in _words(unquoted):
        if word in ENGLISH_FUNCTION_WORDS:
            english += 1
        elif word in GERMAN_FUNCTION_WORDS:
            german += 1
    if english > 2 * german and (english >= 2 or german == 0):
        return "en"
    if german or re.search(r"[äöüß]", unquoted, re.IGNORECASE):
        return "de"
    return None


def is_english_question(text: str) -> bool:
    """Read the same language decision used by the answer renderer."""
    return detect_question_language(text) == "en"


def _render_segment(segment: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return _ORDERED[int(str(match.lastgroup)[1:])][1]

    return _PHRASE_PATTERN.sub(replace, segment)


@lru_cache(maxsize=1024)
def render_english_cues(text: str) -> str | None:
    """The router's reading of an English question, ``None`` for any other.

    The result is normalised like ``normalisierte_frage`` (lower case, one
    hyphen, one space). Quoted terms stay as they are.
    """

    if not is_english_question(text):
        return None
    return render_cues(text)


def render_cues(text: str) -> str:
    """Render ``text`` without asking for its language.

    For a fragment of a question already known to be English (a list item
    too short to classify on its own). Everything else goes through
    ``render_english_cues``.
    """

    normalised = _normalised(text)
    parts = []
    position = 0
    for quoted in _QUOTED.finditer(normalised):
        parts.append(_render_segment(normalised[position : quoted.start()]))
        parts.append(quoted.group(0))
        position = quoted.end()
    parts.append(_render_segment(normalised[position:]))
    return " ".join("".join(parts).split())


def without_quoted_terms(text: str) -> str:
    """``text`` without its quoted terms (apostrophes are no quotes)."""

    return _QUOTED.sub(" ", str(text or ""))


def routing_text(text: str) -> str:
    """Normalised question text for the cue lists of the router.

    German (and every question that is not classified as English): exactly
    ``normalisierte_frage``. English: the rendering of ``render_english_cues``.
    """

    rendered = render_english_cues(text)
    return rendered if rendered is not None else _normalised(text)


__all__ = (
    "CUE_PHRASES",
    "ENGLISH_FUNCTION_WORDS",
    "GERMAN_FUNCTION_WORDS",
    "detect_question_language",
    "is_english_question",
    "normalised_question",
    "render_cues",
    "render_english_cues",
    "routing_text",
    "without_quoted_terms",
)
