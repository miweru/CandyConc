"""Cross-family claim-rule helpers: number/count/quote machinery and every predicate exercised by more than one analysis family (or only by the validate layer in the facade).

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
import math
import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..grounding_schemas import (
    ClaimDraft,
    EXACTNESS_VALUES,
    EvidenceItem,
    NON_AUTHORITATIVE_GROUNDING_TOOLS,
    ObservedFact,
    _HYPOTHESIS_PROPOSAL_PATTERN,
    _compact_text,
    _dedupe_ordered_strs,
    _is_testable_hypothesis_claim,
    _normalised_question_text,
)
from ..quote_rules import (
    EMPIRISCHER_KONTEXT,
    SCOPE_KONTEXT,
    auslassungssegmente,
    normalisiere_zitat_fuer_vergleich,
    spanne_ist_fragenbezug,
    spanne_kommt_wortweise_vor,
)
from ._table import PatternRule, run_pattern_rule


_GROUP_SEP = r"[.\u00a0\u202f ]"  # German / spaced thousands separators
_NUMBER_TOKEN_SOURCE = (
    # German/space grouped (opt. decimal comma). The trailing ``(?!\d)`` guard
    # anchors the grouped form so it cannot consume a dot-decimal: for a plain
    # 4+-fraction-digit value like ``12.3456`` the grouped alternative would
    # otherwise match ``12.345`` (dot + 3 digits) and leave ``6`` as a SPURIOUS
    # singleton integer token (the C-orch-grounding-1 defect). With the guard the
    # grouped form rejects ``12.345`` (followed by the digit ``6``) and the plain
    # alternative below captures the whole ``12.3456``. The guard forbids only a
    # following DIGIT, not a following ``.``/``,`` — a trailing separator is
    # usually sentence punctuation (``... bei 1.234,5.``), so blocking it would
    # false-split genuine thousands. Genuine forms still match: ``1.234`` (end of
    # token), ``1.234,5`` (comma fraction consumed inside this alternative),
    # ``1.234.567`` (all 3-digit groups consumed) are none of them followed by a
    # bare digit.
    rf"\d{{1,3}}(?:{_GROUP_SEP}\d{{3}})+(?:,\d+)?(?!\d)"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"  # English grouped (opt. decimal dot)
    r"|\d+(?:[.,]\d+)?"  # plain integer / single-separator decimal
)
_NUMBER_PATTERN = re.compile(_NUMBER_TOKEN_SOURCE)
_SIGNED_NUMBER_PATTERN = re.compile(rf"(?<!\w)[+-]?(?:{_NUMBER_TOKEN_SOURCE})")
_RANGE_PATTERN = re.compile(r"\b\d+\s*(?:-|–|bis)\s*\d+\b", re.IGNORECASE)
_WORD_RANGE_PATTERN = re.compile(
    r"\b(?:zwischen\s+rang\s+\d+\s+und\s+\d+|rang(?:bereich)?\s+\d+\s*(?:-|–|bis)\s*\d+)\b",
    re.IGNORECASE,
)
_RANK_RANGE_CONTEXT_PATTERN = re.compile(
    r"\b(?:rang(?:bereich|folge|liste)?|ränge|rängen|raenge|raengen|"
    r"position(?:en)?|platz|plätze|plaetze|stelle(?:n)?|top[- ]?\d*)\b",
    re.IGNORECASE,
)
_PERCENT_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*%|"
    r"\bprozent(?:ig\w*)?\b|"
    r"\banteil\b",
    re.IGNORECASE,
)
_NUMERIC_PERCENT_PATTERN = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|prozent(?:ig\w*)?\b)",
    re.IGNORECASE,
)
_COUNT_WORD_VALUES = {
    "null": "0",
    "zero": "0",
    "ein": "1",
    "eins": "1",
    "eine": "1",
    "einen": "1",
    "einem": "1",
    "einer": "1",
    "eines": "1",
    "one": "1",
    "zwei": "2",
    "drei": "3",
    "vier": "4",
    "fünf": "5",
    "fuenf": "5",
    "sechs": "6",
    "sieben": "7",
    "acht": "8",
    "neun": "9",
    "zehn": "10",
    "elf": "11",
    "zwölf": "12",
    "zwoelf": "12",
    "dreizehn": "13",
    "vierzehn": "14",
    "fünfzehn": "15",
    "fuenfzehn": "15",
    "sechzehn": "16",
    "siebzehn": "17",
    "achtzehn": "18",
    "neunzehn": "19",
    "zwanzig": "20",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
_GERMAN_COMPOUND_NUMBER_UNITS = {
    "ein": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "fuenf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
}
_GERMAN_TENS = {
    "zwanzig": 20,
    "dreißig": 30,
    "dreissig": 30,
    "vierzig": 40,
    "fünfzig": 50,
    "fuenfzig": 50,
    "sechzig": 60,
    "siebzig": 70,
    "achtzig": 80,
    "neunzig": 90,
}


_GERMAN_LARGE_NUMBER_SCALES = {
    "million": 1_000_000,
    "millionen": 1_000_000,
    "milliarde": 1_000_000_000,
    "milliarden": 1_000_000_000,
    "billion": 1_000_000_000_000,
    "billionen": 1_000_000_000_000,
}


def _number_word_value(raw: str) -> str | None:
    """Parse bounded German cardinal compounds used as empirical values."""

    spaced = re.sub(
        r"\s+",
        " ",
        str(raw or "").casefold().replace("-", " "),
    ).strip()
    for scale_word, scale in _GERMAN_LARGE_NUMBER_SCALES.items():
        if spaced == scale_word:
            return str(scale)
        suffix = f" {scale_word}"
        if not spaced.endswith(suffix):
            continue
        multiplier = _number_word_value(spaced[: -len(suffix)])
        if multiplier is None:
            return None
        return str(int(multiplier) * scale)

    token = spaced.replace(" ", "")
    direct = _COUNT_WORD_VALUES.get(token)
    if direct is not None:
        return direct

    if "tausend" in token:
        left, right = token.split("tausend", 1)
        left_value = (
            1
            if left in {"", "ein", "eins"}
            else _number_word_value(left)
        )
        right = right.removeprefix("und")
        right_value = 0 if not right else _number_word_value(right)
        if left_value is None or right_value is None:
            return None
        value = int(left_value) * 1000 + int(right_value)
        return str(value) if 0 <= value <= 999_999 else None

    if "hundert" in token:
        left, right = token.split("hundert", 1)
        left_value = (
            1
            if left in {"", "ein", "eins"}
            else _number_word_value(left)
        )
        right = right.removeprefix("und")
        right_value = 0 if not right else _number_word_value(right)
        if left_value is None or right_value is None:
            return None
        value = int(left_value) * 100 + int(right_value)
        return str(value) if 0 <= value <= 999_999 else None
    return None


_NUMBER_WORD_TOKEN_SOURCE = r"[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)?"
_COUNT_WORD_PATTERN_SOURCE = "|".join(
    sorted(
        (re.escape(word) for word in _COUNT_WORD_VALUES),
        key=len,
        reverse=True,
    )
)
_LARGE_COUNT_WORD_PATTERN_SOURCE = (
    rf"(?:{_NUMBER_WORD_TOKEN_SOURCE}\s+)?(?:"
    + "|".join(
        sorted(
            (re.escape(word) for word in _GERMAN_LARGE_NUMBER_SCALES),
            key=len,
            reverse=True,
        )
    )
    + r")"
)
_EMPIRICAL_COUNT_WORD_PATTERN_SOURCE = (
    rf"(?:{_LARGE_COUNT_WORD_PATTERN_SOURCE}|{_NUMBER_WORD_TOKEN_SOURCE})"
)
_WORD_COUNT_PATTERN = re.compile(
    rf"\b(?P<number>{_EMPIRICAL_COUNT_WORD_PATTERN_SOURCE})\s+"
    r"(?P<count_noun>treffer(?:n)?|trefferkontexte?|fundstellen?|"
    r"(?:konkordanz|kwic)[- ]?(?:zeilen?|instanzen?)|"
    r"passagen?|zeilen?|belege?|beobachtungen?|"
    r"muster(?:n)?|gruppen?|cluster(?:n)?|ergebnisse?|dokumente?|"
    r"texte?|vorkommen)\b",
    re.IGNORECASE,
)
_EXPLICIT_SINGLE_COUNT_QUALIFIER_PATTERN = re.compile(
    r"\b(?:genau|exakt|insgesamt|nur|mindestens|höchstens|hoechstens|"
    r"maximal)\s*$",
    re.IGNORECASE,
)


def _word_count_match_is_indefinite_article(
    match: re.Match[str],
    text: str,
) -> bool:
    raw_number = str(match.group("number") or "").casefold()
    if _number_word_value(raw_number) != "1":
        return False
    prefix = str(text or "")[max(0, match.start() - 32) : match.start()]
    if re.search(
        r"\b(?:es\s+gibt|there\s+(?:is|are))\s*$",
        prefix,
        re.IGNORECASE,
    ):
        return False
    # German ein/eine/einen is usually an indefinite article, not a measured
    # cardinality. Only an explicit quantifier turns it into a count claim.
    # Restricting this exception to "ein Muster" made ordinary phrases such
    # as "ein Beleg" fail the unsupported-count guard.
    return _EXPLICIT_SINGLE_COUNT_QUALIFIER_PATTERN.search(prefix) is None
_DOZEN_COUNT_PATTERN = re.compile(
    rf"\b(?:(?P<multiplier>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+)?"
    r"dutzend\s+"
    r"(?P<noun>treffer(?:n)?|trefferkontexte?|fundstellen?|"
    r"(?:konkordanz|kwic)[- ]?zeilen?|passagen?|zeilen?|beleg(?:e|en)?|"
    r"beobachtungen?|muster(?:n)?|gruppen?|cluster(?:n)?|"
    r"ergebnisse?|dokumente?|texte?|vorkommen)\b",
    re.IGNORECASE,
)
_EXISTENTIAL_KWIC_EVIDENCE_PATTERN = re.compile(
    r"\b(?:mindestens|zumindest)\s+(?:1|ein(?:e|en|er|es)?)\s+"
    r"(?:treffer(?:n)?|trefferkontext(?:e|en)?|fundstelle(?:n)?|"
    r"(?:konkordanz|kwic)[- ]?zeile(?:n)?|beleg(?:e|en)?|vorkommen)\b|"
    r"\bat\s+least\s+(?:1|one)\s+"
    r"(?:hit|match|concordance\s+line|kwic\s+line|occurrence)s?\b",
    re.IGNORECASE,
)
_DIGIT_COUNT_PATTERN = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\s*(?:treffer(?:n)?|trefferkontexte?|fundstellen?|"
    r"(?:konkordanz|kwic)[- ]?(?:zeilen?|instanzen?)|passagen?|zeilen?|"
    r"belege?|beobachtungen?|muster(?:n)?|gruppen?|cluster(?:n)?|"
    r"ergebnisse?|dokumente?|texte?|vorkommen)\b|"
    r"\b(?:insgesamt|anzahl|häufigkeit|haeufigkeit|frequenz|"
    r"trefferzahl|zählung|zaehlung)\b[^\n.!?]{0,40}"
    r"\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_RESULT_CARDINALITY_NOUN_SOURCE = (
    r"(?:wörter?|woerter?|kollokat(?:e|en|ion(?:en)?)?|"
    r"eintr(?:ag|äge|aege|ägen|aegen)|resultate?)"
)
_RESULT_CARDINALITY_DESCRIPTOR_SOURCE = (
    r"(?:[A-Za-zÄÖÜäöüß]+(?:-[A-Za-zÄÖÜäöüß]+)?\s+){0,6}"
)
_WORD_RESULT_COUNT_PATTERN = re.compile(
    rf"\b(?P<number>(?:{_LARGE_COUNT_WORD_PATTERN_SOURCE}|"
    rf"{_COUNT_WORD_PATTERN_SOURCE}))\s+"
    rf"{_RESULT_CARDINALITY_DESCRIPTOR_SOURCE}"
    rf"{_RESULT_CARDINALITY_NOUN_SOURCE}\b",
    re.IGNORECASE,
)
_DIGIT_RESULT_COUNT_PATTERN = re.compile(
    rf"\b(?P<number>\d+)\s+"
    rf"{_RESULT_CARDINALITY_DESCRIPTOR_SOURCE}"
    rf"{_RESULT_CARDINALITY_NOUN_SOURCE}\b",
    re.IGNORECASE,
)
_COUNT_VALUE_PATTERN = re.compile(
    rf"(?:"
    rf"(?P<value_before>{_NUMBER_PATTERN.pattern})\s*"
    r"(?P<noun_after>treffer(?:n)?|trefferkontexte?|fundstellen?|"
    r"(?:konkordanz|kwic)[- ]?(?:zeilen?|instanzen?)|passagen?|zeilen?|belege?|"
    r"beobachtungen?|muster(?:n)?|gruppen?|cluster(?:n)?|"
    r"ergebnisse?|dokumente?|texte?|vorkommen)\b"
    r"|"
    r"\b(?P<noun_before>insgesamt|anzahl|(?:mindest)?häufigkeit|"
    r"(?:mindest)?haeufigkeit|frequenz|trefferzahl|zählung|zaehlung)\b"
    r"(?P<middle>[^\n.!?]{0,40}?)"
    rf"(?P<value_after>{_NUMBER_PATTERN.pattern})"
    r")",
    re.IGNORECASE,
)
_MARKDOWN_LIST_ORDINAL_PATTERN = re.compile(
    r"(?m)^(\s*(?:#{1,6}\s*)?)\d+[.)]\s+"
)
_CLAIM_STEP_ORDINAL_PATTERN = re.compile(
    r"(?:\b(?:schritt|step|punkt)\s+\d+\s*[:.)-]?|"
    r"^\s*\d+(?:(?:\ufe0f?\u20e3)\s*|\s*[:.)\-–—]\s*))",
    re.IGNORECASE,
)
# A list marker must not start after a numeric separator. Without this guard,
# ``173337.4. Die`` loses its decimal fraction because ``4. `` looks like an
# inline list ordinal.
_INLINE_LIST_ORDINAL_PATTERN = re.compile(
    r"(?<![\w.,])\d+[.)]\s+(?=\S)"
)


_QUOTED_SEGMENT_PATTERN = re.compile(
    r"<<([^>]+)>>"
    r'|"([^"]+)"'
    r"|„([^“]+)“"  # „ … “  (German low-high)
    r"|»([^«]+)«"  # » … «  (German guillemets)
    r"|«([^»]+)»"  # « … »  (French guillemets)
    r"|“([^”]+)”"  # “ … ”  (curly doubles)
    r"|‚([^‘]+)‘"  # ‚ … ‘  (German curly singles)
    r"|‘([^’]+)’"  # ‘ … ’  (curly singles)
    r"|(?<!\w)'([^'\n]+)'(?!\w)"  # ' … ' but not apostrophes in words
)
_INLINE_CODE_SEGMENT_PATTERN = re.compile(r"`([^`\n]{1,160})`")
_MARKDOWN_BLOCKQUOTE_PATTERN = re.compile(r"(?m)^\s*>\s*(.+?)\s*$")
_COMPACT_BLOCKQUOTE_PATTERN = re.compile(
    r"\b(?:beleg|zitat|beispiel|kwic(?:[- ]?zeile)?|"
    r"wörtlich|woertlich)\b[^.!?\n]{0,80}:\s*>\s*(.+)$",
    re.IGNORECASE,
)
_EMPIRICAL_EXAMPLE_CUE_SOURCE = (
    r"(?:(?:beleg|beispiel|zitat|kwic(?:[- ]?zeile)?)\s+"
    r"(?:lautet|heißt|heisst)|(?:als\s+)?"
    r"(?:beleg|beispiel|zitat|kwic(?:[- ]?zeile)?)|"
    r"(?:passage|(?:fund|text)?stelle|beleg|beispiel|zitat|"
    r"kwic(?:[- ]?zeile)?)\s+"
    r"(?:gibt[^.!?\n:]{0,48}(?:wörtlich|woertlich|wortgetreu)"
    r"[^.!?\n:]{0,24}wieder|"
    r"formuliert\s+(?:wörtlich|woertlich|wortgetreu))|"
    r"(?:genau(?:e|en|er|es)?\s+)?wortlaut\s+(?:ist|lautet))"
)
_UNQUOTED_EMPIRICAL_EXAMPLE_PATTERN = re.compile(
    rf"\b{_EMPIRICAL_EXAMPLE_CUE_SOURCE}\s*:"
    r"(?!\s*[>\"'`„“»«])\s*(?P<example>[^.!?\n]{3,160})",
    re.IGNORECASE,
)
_UNDELIMITED_WORDING_EXAMPLE_PATTERN = re.compile(
    r"\b(?:im\s+)?(?:beleg|fundstelle|passage|kwic(?:[- ]?zeile)?)\s+"
    r"(?:steht|lautet)\s+(?:wörtlich|woertlich|wortgetreu)\s+"
    r"(?P<example>[^.!?\n]{3,160})",
    re.IGNORECASE,
)
_WORDING_FIRST_EXAMPLE_PATTERN = re.compile(
    r"\b(?:wortwörtlich|wortwoertlich|wörtlich|woertlich|wortgetreu)\s+"
    r"(?:liest|findet)\s+man\s+(?:im|in\s+der)\s+"
    r"(?:beleg|fundstelle|passage|kwic(?:[- ]?zeile)?)\s+"
    r"(?P<example>[^.!?\n]{3,160})",
    re.IGNORECASE,
)
_ORIGINAL_FORMULATION_EXAMPLE_PATTERN = re.compile(
    r"\b(?:die\s+)?originalformulierung\s+(?:des|der)\s+"
    r"(?:belegs?|fundstelle|passage|kwic(?:[- ]?zeile)?)\s+"
    r"(?:lautet|ist)\s+(?P<example>[^.!?\n]{3,160})",
    re.IGNORECASE,
)
_TEXT_BOUNDARY_EXAMPLE_PATTERN = re.compile(
    r"\b(?:der|die|das)\s+"
    r"(?:beleg|fundstelle|passage|kwic(?:[- ]?zeile)?)\s+"
    r"(?:beginnt|endet)\s+mit\s+(?P<example>[^.!?\n]{3,160})",
    re.IGNORECASE,
)
_UNPAIRED_EMPIRICAL_QUOTE_PATTERN = re.compile(
    rf"\b{_EMPIRICAL_EXAMPLE_CUE_SOURCE}\s*:\s*"
    r"(?P<opener>[\"'`„“»«‘])\s*(?P<example>[^\n]{3,160})",
    re.IGNORECASE,
)
_EMPIRICAL_QUOTE_CLOSERS = {
    '"': '"',
    "'": "'",
    "`": "`",
    "„": "“",
    "“": "”",
    "»": "«",
    "«": "»",
    "‚": "‘",
    "‘": "’",
}
_CATEGORY_PATTERN = re.compile(
    r"\b(?:überwiegend|ueberwiegend|überwieg(?:en|t)|ueberwieg(?:en|t)|"
    r"hauptsaechlich|hauptsächlich|mehrheitlich|fast nur|fast ausschließlich|"
    r"fast ausschliesslich|ausschließlich|ausschliesslich|dominieren|"
    r"dominant(?:e|en|er|es)?|dominiert|"
    r"typisch(?:e|en|er|es|erweise)?|typical(?:ly)?|meistens|"
    r"vor allem(?!\s+(?:eine?\s+)?(?:rein\s+)?(?:deskriptiv\w*\s+)?"
    r"(?:zusammenschau|analyse|einordnung|beschreibung|darstellung|methode))|"
    r"vorwiegend|kennzeichnend für|kennzeichnend fuer|"
    r"charakteristisch für|charakteristisch fuer|primär|primaer|primarily)\b",
    re.IGNORECASE,
)


_WEAK_CATEGORY_PATTERN = re.compile(
    r"\b(überwiegend|überwiegend|hauptsaechlich|hauptsächlich|mehrheitlich|"
    r"fast nur|dominant|dominiert|typisch für|typisch für|meistens|"
    r"vor allem|vorwiegend|eher|klar|deutlich|offenbar|wirkt)\b",
    re.IGNORECASE,
)
_PARTIAL_MAGNITUDE_PATTERN = re.compile(
    r"\b(?:tiefgreifend|fundamental|weitreichend|massiv|ausgeprägt|"
    r"stark|extrem|erheblich)(?:e|en|er|es)?\s+"
    r"(?:polarisierung(?:en)?|spaltung(?:en)?|dominanz|tendenz(?:en)?|"
    r"muster|kontrast(?:e|en)?|gegensatz(?:e|es)?|"
    r"spannungsfeld(?:er|es)?)\b|"
    r"\b(?:deep|profound|massive|pronounced|strong|extreme|substantial)\s+"
    r"(?:polarization|polarisation|division|dominance|trend|pattern|contrast)\b"
    r"|\b(?:stark|massiv|weitgehend)\s+von\s+[^.!?\n]{1,100}\b"
    r"(?:geprägt|gepraegt|bestimmt|dominiert)\w*\b",
    re.IGNORECASE,
)
_OPERATIONALISED_MAGNITUDE_PATTERN = re.compile(
    r"\b\d+\s+(?:von|aus|of)\s+\d+\b|"
    r"\b(?:verhältnis|verhaeltnis|ratio|anteil|score|index|koeffizient|"
    r"effektstärke|effektstaerke|effect\s+size)\b"
    r"[^.!?\n]{0,36}(?:=|beträgt|betraegt|von|bei|is)\s*[-+]?\d",
    re.IGNORECASE,
)
#: Reichweiten, die ueber die untersuchten Daten hinausgreifen.
#:
#: A1. Eine Deutung darf sagen, was in DIESEM Korpus gilt. Sie darf nicht
#: sagen, was im Deutschen gilt, was immer gilt oder was generell gilt,
#: denn dafuer liegt keine Evidenz vor und kann in einem Korpus auch nicht
#: vorliegen. Genau diese Grenze soll die Regel ziehen, und genau die zog
#: sie nicht: sie zog eine Vokabelgrenze.
_UEBERDEHNTE_REICHWEITE = re.compile(
    r"\b(?:generell|allgemein(?:e|en|er|es)?\s+(?:gilt|zeigt|ist)|"
    r"grundsätzlich|grundsaetzlich|"
    r"im\s+deutschen\b|in\s+der\s+(?:sprache|gegenwartssprache)\b|"
    r"sprachübergreifend|sprachuebergreifend|universell|"
    r"immer\b|stets\b|ausnahmslos|in\s+allen\s+(?:texten|korpora|registern)|"
    r"jede[rsmn]?\s+(?:text|sprecher|autor)\b|"
    r"beweist|belegt\s+eindeutig|zeigt\s+eindeutig)",
    re.IGNORECASE,
)

#: Wendungen, die korpusweite Geltung behaupten.
#:
#: Sie sind ERLAUBT, wenn die Evidenz korpusweit exakt ist, und nur dann.
#: "Im Korpus dominieren 12 Treffer" ist richtig, wenn die 12 aus einem
#: exakten Count ueber das ganze Korpus stammen, und eine Hochrechnung aus
#: einem Ausschnitt, wenn nicht. Der Unterschied liegt in der EVIDENZ, und
#: genau daran wird er jetzt gemessen.
_KORPUSWEITE_GELTUNG = re.compile(
    r"\b(?:im\s+(?:gesamt)?korpus|korpusweit|über\s+das\s+(?:gesamte\s+)?korpus|"
    r"insgesamt\s+(?:dominier|überwieg|ueberwieg))",
    re.IGNORECASE,
)

# P8: die Liste kannte bis hierher nur ein Etikett-Vokabular ("sichtbar",
# "vorliegend", "ausgegeben"). Dieselbe Formel schrieben drei Prompt-Docs vor,
# und der Endtext des Turns gemischt-leichte-sprache-naeherung (3315 Zeichen
# Rumpf) trug daraufhin 17 mal "sichtbare Keyness-Zeile" und keine einzige
# Dezimalzahl, waehrend der Entwurf (1491 Zeichen) je Kandidat log_ratio und
# pmw nannte. Eine ausgezaehlte AUSSCHNITTSMENGE ("in den 12 Zeilen") nennt
# die Kappe selbst und begrenzt damit mindestens so scharf wie das Etikett.
#
# Was hier NICHT hinein gehoert, gemessen am 2026-09-03 im Arbeitsbaum:
# "je Richtung" stand einen Commit lang in dieser Liste und nannte keine
# Menge. "Je Richtung ist 'Meldung' deutlich das dominante Wort." galt
# damit als begrenzt, und _stronger_than_exactness(sample_only) fiel dafuer
# von True auf False. Eine Gruppierungsangabe ist keine Geltungsgrenze.
# Ebenso stand "dokumenten" in der ausgezaehlten Menge: 5832 und 486 sind im
# gemessenen Turn die Groesse des ganzen Ziel- und Referenzkorpus, also die
# Grundgesamtheit. Die Menge bindet deshalb nur an Ausschnittswoerter.
_BOUNDED_SCOPE_PATTERN = re.compile(
    r"\b(?:sichtbar(?:e|en|er|es)?|top[- ]?(?:n|\d+)|ausschnitt|"
    r"teilmenge|stichprob\w*|samples?|"
    r"(?:in|innerhalb|unter|von|bei|auf)\s+(?:den|die|diesen|dieser)\s+"
    r"\d+\s+(?:ausgewiesenen\s+|ausgewerteten\s+|verglichenen\s+)?"
    r"(?:zeilen|treffern?|kandidaten|einträgen?|eintraegen?|belegen?|"
    r"partnerzeilen)|"
    r"(?:(?:gemessen|beurteilt)\s+an|auf\s+grundlage)\s+"
    r"(?:den|der|dieser)\s+"
    r"(?:hier\s+)?(?:gezeigt(?:e|en|er|es)?|sichtbar(?:e|en|er|es)?|"
    r"vorliegend(?:e|en|er|es)?|dargestellt(?:e|en|er|es)?)\s+"
    r"(?:word[- ]?sketch[- ]?)?(?:zeilen|tabelle|ausgabe)|"
    r"(?:in|innerhalb|unter|bezogen\s+auf)\s+"
    r"(?:dieser|diese|diesen|den|der)\s+"
    r"(?:word[- ]?sketch[- ]?)?"
    r"(?:tabelle|liste|ausgabe|zeilen|einträgen|eintraegen)|"
    r"unter\s+den\s+(?:sichtbaren|zurückgegebenen|zurueckgegebenen|"
    r"angezeigten|vorliegenden)?\s*(?:zeilen|einträgen|eintraegen)|"
    r"bereitgestellt(?:e|en|er|es)?|vorliegend(?:e|en|er|es)?|"
    r"zurückgegeben(?:e|en|er|es)?|zurueckgegeben(?:e|en|er|es)?|"
    r"abgerufen(?:e|en|er|es)?|angezeigt(?:e|en|er|es)?|"
    r"ausgegeben(?:e|en|er|es)?|"
    r"analysiert(?:e|en|er|es)?|untersucht(?:e|en|er|es)?|"
    r"betrachtet(?:e|en|er|es)?|ausgewertet(?:e|en|er|es)?)\b",
    re.IGNORECASE,
)
_GLOBAL_SCOPE_PATTERN = re.compile(
    r"\b(?:im|für\s+(?:das|den)|fuer\s+(?:das|den)|"
    r"über\s+(?:das|den)|ueber\s+(?:das|den))\s+"
    r"(?:gesamtkorpus|(?:gesamten?\s+)?korpus)\b|"
    r"\b(?:korpusweit|über\s+alle\s+vorkommen|ueber\s+alle\s+vorkommen)\b|"
    r"\b(?:in|für|fuer|über|ueber)\s+"
    r"(?:jedem|jeder|jedes|jeden|alle|allen|sämtliche|saemtliche|"
    r"sämtlichen|saemtlichen)\s+"
    r"(?:teilkorp(?:us|ora)|subkorp(?:us|ora)|registern?|genres?|"
    r"textsorten?|quellen?|sprachen?|dokument(?:e|en)?|text(?:e|en)?|"
    r"zeiträumen?|zeitraeumen?)"
    r"(?:\s+hinweg)?\b|"
    r"\bunabhängig\s+von\s+(?:(?:der|dem|den)\s+)?"
    r"(?:textsorte|genre|register|quelle|sprache|zeitraum)\b|"
    r"\b(?:im|für|fuer|auf|über|ueber)\s+"
    r"(?:(?:den|dem)\s+)?gesamten?\s+"
    r"(?:datenbestand|datensatz|datenkorpus|datenmaterial)\b|"
    r"\bkein(?:es)?\s+dokument\b",
    re.IGNORECASE,
)
_PARTITION_PURPOSE_PATTERN = re.compile(
    r"\b(modellvalidierung|modellpruefung|modellprüfung|trainings?|evaluation|"
    r"datenqualit\w*|robust\w*|"
    r"maschinenlern\w*|maschinell\w*\s+lern\w*|"
    r"machine[- ]learning|ml[- ](?:partition|split)|"
    r"test(?:daten|partition(?:en)?|satz)|"
    r"validierung|sampling|stichproben(?:bildung|ziehung)?)\b",
    re.IGNORECASE,
)
_CROSS_RESULT_RANKING_PATTERN = re.compile(
    r"\b(?:gefolgt\s+von|"
    r"an\s+(?:erster|ersten|zweiter|zweiten|dritter|dritten)\s+stelle|"
    r"followed\s+by)\b|"
    r"\b(?:zusammen|gemeinsam\w*|kombiniert\w*|"
    r"übergreifend\w*|uebergreifend\w*)"
    r"[^.!?\n]{0,60}\b(?:rangliste|rangfolge|ranking)\b",
    re.IGNORECASE,
)
_SEPARATE_RESULT_SPACE_PATTERN = re.compile(
    r"\b(?:getrennt(?:e|en|er|es)?|separat(?:e|en|er|es)?|jeweils)\b"
    r"[^.!?]{0,100}\b(?:auswertung\w*|liste\w*|profil\w*|rangfolg\w*|"
    r"ranking\w*)\b"
    r"|\b(?:keine|nicht\s+als)\s+gemeinsame\s+(?:rangfolge|rangliste|ranking)\b",
    re.IGNORECASE,
)
_RESULT_SCOPE_MARKER_PATTERN = re.compile(
    r"\b(?:group_by|pos)\s*=\s*[A-Za-z_]+"
    r"|\b(?:wort|lemma|pos|nomen|verb|adjektiv)[- ]?"
    r"(?:basiert\w*|gefiltert\w*)?\s*(?:auswertung\w*|liste\w*|profil\w*)\b",
    re.IGNORECASE,
)
_RESULT_SCOPE_CONTRAST_PATTERN = re.compile(
    r"\b(?:während|waehrend|hingegen|dagegen|demgegenüber|demgegenueber)\b",
    re.IGNORECASE,
)
_CROSS_SOURCE_LITERAL_SEPARATION_PATTERN = re.compile(
    r"\b(?:außerdem|ausserdem|zudem|zusätzlich|zusaetzlich|"
    r"separat|jeweils|während|waehrend|hingegen|einerseits|"
    r"andererseits)\b",
    re.IGNORECASE,
)
_CROSS_SOURCE_ANAPHORIC_JOIN_PATTERN = re.compile(
    r"^(?:darin|dort|hierin|innerhalb\s+(?:dieses|dieser)|"
    r"in\s+(?:diesem|dieser)|für\s+(?:dieses|diesen|diese)|"
    r"fuer\s+(?:dieses|diesen|diese)|bezogen\s+(?:hier)?darauf)\b",
    re.IGNORECASE,
)
_CORPUS_PURPOSE_CLAIM_PATTERN = re.compile(
    r"\b(?:korpus|corpus|datensatz|dataset|material|sammlung|collection)\b"
    r"[^.!?\n]{0,180}\b(?:konzipiert|erstellt|zusammengestellt|gesammelt|"
    r"entwickelt|geeignet|vorgesehen|dient|designed|intended|compiled|"
    r"collected|serves?)\b|"
    r"\b(?:korpus|corpus|datensatz|dataset|material|sammlung|collection)\b"
    r"[^.!?\n]{0,100}\b(?:ist|war|wurde|wird)\s+"
    r"(?:für|fuer|zur|zum)\b[^.!?\n]{0,100}\bbestimmt\b",
    re.IGNORECASE,
)
_EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN = re.compile(
    r"(?:field=|values\[|value_count\[)"
    r"(?:purpose|intended_use|collection_purpose|sampling_design|"
    r"korpuszweck|erhebungsziel|verwendungszweck)\b"
    r"|\b(?:purpose|intended_use|collection_purpose|sampling_design|"
    r"korpuszweck|erhebungsziel|verwendungszweck)\s*=",
    re.IGNORECASE,
)


_TEXT_PRODUCTION_ORIGIN_PATTERN = re.compile(
    r"\b(?:automatisiert\w*\s+(?:text)?generator\w*|"
    r"automatisch\s+(?:erzeugt|generiert|verfasst|geschrieben)\w*|"
    r"maschinell\s+(?:erzeugt|generiert|verfasst|geschrieben)\w*|"
    r"(?:ki|llm)[- ]generiert\w*|textgenerator\w*|"
    r"machine[- ]generated|automatically\s+generated|"
    r"human[- ]written|menschlich\s+(?:verfasst|geschrieben)\w*)\b",
    re.IGNORECASE,
)
_TEXT_PRODUCTION_INFERENCE_PATTERN = re.compile(
    r"\b(?:deut\w*\s+auf|hindeut\w*|hinweis\w*|spr(?:icht|echen)\s+für|"
    r"laesst\s+vermuten|lässt\s+vermuten|stamm\w*\s+von|"
    r"erzeugt\w*\s+durch|generiert\w*\s+durch|"
    r"verfasst\w*\s+von|geschrieben\w*\s+von)\b",
    re.IGNORECASE,
)
_TEXT_PRODUCTION_EVIDENCE_PATTERN = re.compile(
    r"(?:field=|values\[|value_count\[)?"
    r"(?:model|text_type|generator|generator_model|author_type|authorship)"
    r"(?:\]|\b)\s*=",
    re.IGNORECASE,
)
_LEMMA_CLAIM_PATTERN = re.compile(
    r"\b(?:lemma\w*|lemmatisier\w*)\b",
    re.IGNORECASE,
)
_LEMMA_QUERY_CLAIM_PATTERN = re.compile(
    r"\b(?:lemma[- ]?(?:abfrage|suche)|lemma\s+query|"
    r"nach\s+dem\s+lemma)\b",
    re.IGNORECASE,
)
_PROPOSED_LEMMA_ANALYSIS_PATTERN = re.compile(
    r"\b(?:lemmatisier\w*|lemma[- ]?(?:analyse|gruppierung)|"
    r"normalisier\w*|normalisierungsanalyse\w*)\b",
    re.IGNORECASE,
)
_EXISTING_LEMMA_RESULT_PATTERN = re.compile(
    r"\b(?:vorliegend\w*|aktuell\w*|bereits|ausgegeben\w*|sichtbar\w*)\b"
    r"[^.!?\n]{0,100}\blemma[- ]?(?:abfrage|suche|analyse|liste|ergebnis)\w*\b",
    re.IGNORECASE,
)


_DIVERSITY_NORMATIVE_PATTERN = re.compile(
    r"\b(?:ttr|sttr|mattr|(?:lexikalisch\w*\s+)?diversität\w*)\b"
    r"(?:[^.!?\n]|(?<=\d)\.(?=\d)){0,100}"
    r"\b(?:typisch(?:e|en|er|es)?|"
    r"mittler(?:e|en|er|es)?|mittel|"
    r"moderat(?:e|en|er|es)?|"
    r"überdurchschnittlich\w*|ueberdurchschnittlich\w*|"
    r"unterdurchschnittlich\w*|(?:sehr\s+)?(?:hoch|niedrig)"
    r"(?:e|en|er|es)?)\b|"
    r"\b(?:typisch(?:e|en|er|es)?|mittler(?:e|en|er|es)?|mittel|"
    r"moderat(?:e|en|er|es)?|"
    r"überdurchschnittlich\w*|"
    r"ueberdurchschnittlich\w*|unterdurchschnittlich\w*|"
    r"(?:sehr\s+)?(?:hoch|niedrig)(?:e|en|er|es)?)\b"
    r"(?:[^.!?\n]|(?<=\d)\.(?=\d)){0,100}"
    r"\b(?:ttr|sttr|mattr|"
    r"(?:lexikalisch\w*\s+)?diversität\w*)\b",
    re.IGNORECASE,
)
_DIVERSITY_METHOD_SUPERLATIVE_PATTERN = re.compile(
    r"\b(?:robusteste\w*|am\s+(?:wenigsten|meisten)\s+belastbar\w*|"
    r"noch\s+robustere\w*|"
    r"bevorzugte\w*\s+(?:kennzahl|maß|mass|metrik)|"
    r"beste\w*\s+(?:kennzahl|maß|mass|metrik))\b",
    re.IGNORECASE,
)
_DIVERSITY_METHOD_RELATION_PATTERN = re.compile(
    r"\b(?:belastbarer|robuster|stabiler|besser|geeigneter|überlegen|"
    r"ueberlegen|weniger\s+(?:belastbar|robust|stabil|geeignet))\w*\b|"
    r"\b(?:übertrifft|uebertrifft|vorzuziehen|vorgezogen|bevorzugt)\w*\b",
    re.IGNORECASE,
)
_DIVERSITY_CROSS_METRIC_MAGNITUDE_PATTERN = re.compile(
    r"\bmattr\b[^.!?\n]{0,100}\b(?:höher|hoeher|größer|groesser)\w*\b"
    r"[^.!?\n]{0,120}\b(?:zeig\w*|beleg\w*|bedeut\w*|spricht\s+für)\b"
    r"[^.!?\n]{0,100}\b(?:zusätzlich\w*|mehr|höher\w*|hoeher\w*)\b"
    r"[^.!?\n]{0,60}\b(?:diversität\w*|vielfalt\w*)\b",
    re.IGNORECASE,
)
_DIVERSITY_CROSS_METRIC_INTERPRETATION_PATTERN = re.compile(
    r"\bmattr\b[^.!?\n]{0,160}\b(?:höher|hoeher|größer|groesser)\w*\b"
    r"[^.!?\n]{0,80}\bsttr\b[^.!?\n]{0,160}"
    r"(?:\b(?:deut\w*\s+auf|spricht\s+für|spricht\s+fuer)\b|"
    r"\bweist\b[^.!?\n]{0,80}\bhin\b)"
    r"[^.!?\n]{0,120}\b(?:variation\w*|diversität\w*|vielfalt\w*|"
    r"typenverteilung\w*)\b",
    re.IGNORECASE,
)
_TTR_TOKEN_BASE_PATTERN = re.compile(
    r"\b(?:bei|mit|auf\s+(?:der\s+)?basis\s+von)\s+"
    r"(?P<count>\d{1,3}(?:[.\u00a0\u202f ]\d{3})+|\d+)\s+tokens?\b"
    r"[^.!?\n]{0,100}\bttr\b",
    re.IGNORECASE,
)
_LEXICAL_ROBUSTNESS_REQUEST_PATTERN = re.compile(
    r"\b(?:belastbar\w*|robust\w*|längensensitiv\w*|"
    r"laengensensitiv\w*|korpusgröße\w*|korpusgroesse\w*)\b",
    re.IGNORECASE,
)
_LEXICAL_ROBUSTNESS_ANSWER_PATTERN = re.compile(
    r"(?:"
    r"\bsttr\b[^.!?\n]{0,100}\bmattr\b|"
    r"\bmattr\b[^.!?\n]{0,100}\bsttr\b"
    r")[^.!?\n]{0,180}\b(?:belastbar\w*|robust\w*|"
    r"längen[- ]?(?:sensitiv|kontrolliert)\w*|"
    r"laengen[- ]?(?:sensitiv|kontrolliert)\w*)\b|"
    r"\b(?:belastbar\w*|robust\w*|"
    r"längen[- ]?(?:sensitiv|kontrolliert)\w*|"
    r"laengen[- ]?(?:sensitiv|kontrolliert)\w*)\b[^.!?\n]{0,180}(?:"
    r"\bsttr\b[^.!?\n]{0,100}\bmattr\b|"
    r"\bmattr\b[^.!?\n]{0,100}\bsttr\b)",
    re.IGNORECASE,
)
_TTR_WINDOW_DEPENDENCE_PATTERN = re.compile(
    r"\b(?:global(?:e[rsnm]?)?\s+)?ttr\b[^.!?\n]{0,100}"
    r"\b(?:ist|sei|bleibt|wäre|waere)\b[^.!?\n]{0,30}"
    r"\bfensterabhängig\w*\b|"
    r"\b(?:ttr\b[^.!?\n]{0,80}\bsttr|sttr\b[^.!?\n]{0,80}\bttr)\b"
    r"[^.!?\n]{0,80}\bbeide\b[^.!?\n]{0,50}"
    r"\bfensterabhängig\w*\b|"
    r"\balle\s+drei\s+(?:kennzahlen|maße|masse|metriken)\b"
    r"[^.!?\n]{0,100}\bfensterabhängig\w*\b",
    re.IGNORECASE,
)
_ROBUSTNESS_REFERENCE_CONFUSION_PATTERN = re.compile(
    r"\bohne\s+(?:einen\s+)?referenz[- ]?korpus\b[^.!?\n]{0,180}"
    r"\b(?:welche\w*\s+)?(?:kennzahl|maß|mass|metrik|ttr|sttr|mattr)\w*\b"
    r"[^.!?\n]{0,100}\b(?:belastbar|robust|stabil|zuverlässig|"
    r"zuverlaessig)\w*\b|"
    r"\b(?:kennzahl\w*|maß\w*|mass\w*|metrik\w*|ttr|sttr|mattr)\b"
    r"[^.!?\n]{0,180}\b(?:belastbar|robust|stabil|zuverlässig|"
    r"zuverlaessig)\w*\b[^.!?\n]{0,180}"
    r"\bohne\s+(?:einen\s+)?referenz[- ]?korpus\b",
    re.IGNORECASE,
)
_LEXICAL_REFERENCE_INTERPRETABILITY_PATTERN = re.compile(
    r"\bohne\s+(?:einen\s+)?referenz[- ]?korpus\b[^.!?\n]{0,280}"
    r"\b(?:werte?|kennzahlen?|maße?|masse?|metriken?|ttr|sttr|mattr)\b"
    r"[^.!?\n]{0,140}\b(?:nicht\s+interpretier\w*|"
    r"nicht\s+interpretiert\w*|keine\s+interpretation)\b",
    re.IGNORECASE,
)
_LEXICAL_RATING_INTERPRETATION_SCOPE_PATTERN = re.compile(
    r"\binterpret\w*\b[^.!?\n]{0,100}\b(?:als\s+)?(?:hoch|niedrig|"
    r"moderat|typisch|qualitätsniveau|qualitaetsniveau|"
    r"qualitätsvergleich|qualitaetsvergleich)\w*\b",
    re.IGNORECASE,
)
_STTR_VARIANCE_SMOOTHING_PATTERN = re.compile(
    r"\bsttr\b[^.!?\n]{0,140}\b(?:glätt\w*|glaett\w*)\b"
    r"[^.!?\n]{0,80}\bvarianz\w*\b|"
    r"\bsttr\b[^.!?\n]{0,140}\bvarianz\w*\b"
    r"[^.!?\n]{0,80}\b(?:glätt\w*|glaett\w*)\b|"
    r"\bvarianz\w*\b[^.!?\n]{0,80}\b(?:glätt\w*|glaett\w*)\b"
    r"[^.!?\n]{0,140}\bsttr\b",
    re.IGNORECASE,
)
_STTR_UNSUPPORTED_VARIABILITY_PATTERN = re.compile(
    r"\bsttr\b[^.!?\n]{0,160}\b(?:weniger\s+variier\w*|"
    r"variationsärmer\w*|variationsaermer\w*|glatter\w*\s+schätzung\w*)\b|"
    r"\b(?:weniger\s+variier\w*|variationsärmer\w*|"
    r"variationsaermer\w*|glatter\w*\s+schätzung\w*)\b"
    r"[^.!?\n]{0,160}\bsttr\b",
    re.IGNORECASE,
)
_LEXICAL_DENSITY_CONFUSION_PATTERN = re.compile(
    r"\b(?:lexikalisch\w*\s+)?(?:dichte|lexikaldichte)\b",
    re.IGNORECASE,
)
_EQUAL_WINDOW_ASSUMPTION_PATTERN = re.compile(
    r"\bbei\s+(?:der\s+)?gleiche[rmn]?\s+fenster(?:größe|groesse|länge|laenge)\b",
    re.IGNORECASE,
)
_UNEQUAL_WINDOW_BOUNDARY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:verschieden\w*|unterschiedlich\w*)\s+"
    r"fenster(?:größ|groess|läng|laeng)\w*\b[^.!?\n]{0,220}"
    r"\b(?:nicht\s+(?:direkt\s+)?vergleich\w*|keine\s+(?:direkte\s+)?"
    r"(?:rangfolge|methodenrangfolge|vergleichbarkeit)|nicht\s+zur\s+rangfolge)\b|"
    r"\b(?:sttr|mattr)\b[^.!?\n]{0,120}\b(?:sttr|mattr)\b"
    r"[^.!?\n]{0,180}\b(?:nicht\s+(?:direkt\s+)?vergleich\w*|"
    r"keine\s+(?:direkte\s+)?(?:rangfolge|methodenrangfolge|vergleichbarkeit))\b"
    r")",
    re.IGNORECASE,
)
_TTR_STTR_ROBUSTNESS_EQUIVOCATION_PATTERN = re.compile(
    r"\bweder\s+ttr\s+noch\s+(?:sttr|mattr)\b[^.!?\n]{0,140}"
    r"\b(?:belastbar|robust|stabil|zuverlässig|zuverlaessig)\w*\b",
    re.IGNORECASE,
)
_TTR_CATEGORICAL_SIZE_DECLINE_PATTERN = re.compile(
    r"\bttr\b[^.!?\n]{0,140}\b(?:sinkt|fällt|faellt|nimmt\s+ab)\b"
    r"[^.!?\n]{0,100}\b(?:zunehmend\w*|wachsend\w*|größer\w*|"
    r"groesser\w*)\b[^.!?\n]{0,60}\b(?:korp(?:us|ora)|text|stichprob)\w*|"
    r"\b(?:zunehmend\w*|wachsend\w*|größer\w*|groesser\w*)\b"
    r"[^.!?\n]{0,60}\b(?:korp(?:us|ora)|text|stichprob)\w*[^.!?\n]{0,100}"
    r"\bttr\b[^.!?\n]{0,80}\b(?:sinkt|fällt|faellt|nimmt\s+ab)\b|"
    r"\bttr\b[^.!?\n]{0,180}\b(?:größer\w*|groesser\w*|"
    r"wachsend\w*|zunehmend\w*)\b[^.!?\n]{0,60}"
    r"\b(?:korp(?:us|ora)|text|stichprob)\w*[^.!?\n]{0,100}"
    r"\b(?:sinkt|fällt|faellt|nimmt\s+ab)\b",
    re.IGNORECASE,
)
_TTR_SIZE_TENDENCY_QUALIFIER_PATTERN = re.compile(
    r"\b(?:tendier\w*|typischerweise|üblicherweise|ueblicherweise|"
    r"in\s+der\s+regel|im\s+mittel|häufig|haeufig)\b",
    re.IGNORECASE,
)
_TTR_EXCLUSIVE_SMALL_SCOPE_PATTERN = re.compile(
    r"\bttr\b[^.!?\n]{0,80}\b(?:sollte|darf|kann)\b"
    r"[^.!?\n]{0,50}\bnur\b[^.!?\n]{0,100}"
    r"\b(?:klein|kurz)\w*\b[^.!?\n]{0,60}"
    r"\b(?:korpus|text|stichprob)\w*\b",
    re.IGNORECASE,
)
_N_TYPES_AS_TOKENS_PATTERN = re.compile(
    r"\b(?P<count>\d{1,3}(?:[.\u00a0\u202f ]\d{3})+|\d+)\s+"
    r"(?:unterschiedlich|verschieden|eindeutig|unique)\w*\s+tokens?\b",
    re.IGNORECASE,
)
_MISSING_FILTER_POLICY_PATTERN = re.compile(
    r"\b(?:ohne|fehl(?:t|en|end\w*)|unklar|unbekannt|nicht\s+"
    r"(?:explizit\s+)?angegeben)\b[^.!?\n]{0,140}"
    r"\b(?:filterpolitik|filterprozesse?|filterregeln?|filterung)\b|"
    r"\b(?:filterpolitik|filterprozesse?|filterregeln?|filterung)\b"
    r"[^.!?\n]{0,140}\b(?:fehl(?:t|en|end\w*)|unklar|unbekannt|"
    r"nicht\s+(?:explizit\s+)?angegeben)\b",
    re.IGNORECASE,
)
_WHOLE_CORPUS_ANALYSIS_TOKEN_PATTERN = re.compile(
    r"\b(?:(?:aktive[nrsm]?|active)\s+)?(?:korpus|corpus)\b"
    r"[^.!?\n]{0,80}"
    r"\b(?:besteht\s+aus|umfasst|enthält|enthaelt|hat|contains|"
    r"comprises|has)\b[^.!?\n]{0,100}?"
    r"(?:(?:insgesamt|exakt|genau|exactly|in\s+total)\s+)?"
    r"(?P<count>\d{1,3}(?:[.\u00a0\u202f ]\d{3})+|\d+)\s+tokens?\b",
    re.IGNORECASE,
)


_CONTEXT_CODING_EVIDENCE_PATTERN = re.compile(
    r"\b(?:coded_contexts|context_count|context_label|label_count|"
    r"category_count|coding_coverage|kodierte[_ -]?kontexte|"
    r"kontextkodierung)\s*=",
    re.IGNORECASE,
)


_RELATIVE_FREQUENCY_PATTERN = re.compile(
    r"\b(?:relative|normalisierte?)\s+"
    r"(?:verwendung|häufigkeit|haeufigkeit|frequenz|rate)\b|"
    r"\b(?:verwendung|häufigkeit|haeufigkeit|frequenz|rate)\s+"
    r"(?:relativ|normalisiert)\b",
    re.IGNORECASE,
)
_TIME_COMPARISON_PATTERN = re.compile(
    r"\bvon\s+(?P<start_year>\d{4})\s+"
    r"(?:auf|bis)\s+(?P<end_year>\d{4})\b",
    re.IGNORECASE,
)
_TIME_CHANGE_PATTERN = re.compile(
    r"\b(?P<change>"
    r"verdoppel\w*|halbier\w*|gestieg\w*|gestiegen|zugenomm\w*|"
    r"gesunk\w*|gesunken|gefall\w*|höher\w*|hoeher\w*|"
    r"niedriger\w*|gleich\s+geblieben)\b",
    re.IGNORECASE,
)
_GENERIC_TIME_TREND_PATTERN = re.compile(
    r"\b(?:gebrauch|verwendung|häufigkeit|haeufigkeit|frequenz|rate)\b"
    r"[^.!?\n]{0,140}\b(?P<change>"
    r"nimmt\b[^.!?\n]{0,24}\bzu|steig\w*|wächst|waechst|"
    r"nimmt\b[^.!?\n]{0,24}\bab|sink\w*|fällt|faellt)\b",
    re.IGNORECASE,
)


_EXPLICIT_CAUSAL_EVIDENCE_PATTERN = re.compile(
    r"\b(?:causal_design|experimental_design|randomized_design|"
    r"randomised_design)\s*=\s*true\b|"
    r"\bdesign\s*=\s*(?:randomized|randomised|experimental)\b",
    re.IGNORECASE,
)
_NEGATED_PURPOSE_PATTERN = re.compile(
    r"\b(nicht|kein(?:e|en|er|es)?|unklar|unbekannt|unbelegt|"
    r"laesst sich nicht|lässt sich nicht|darf nicht)\b",
    re.IGNORECASE,
)
_NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN = re.compile(
    r"\b(?:nicht|kein(?:e|en|er|es)?|ohne|weder|unklar|unbekannt|unbelegt|"
    r"offen|fehl(?:t|en|end\w*)|nicht\s+bestimmbar|nicht\s+ableitbar|"
    r"lässt\s+sich\s+nicht|laesst\s+sich\s+nicht|"
    r"kann\s+nicht|darf\s+nicht)\b",
    re.IGNORECASE,
)
_EPISTEMIC_SCOPE_LIMITATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:bleibt|ist)\s+(?:weiterhin\s+)?(?:offen|unklar|unbekannt)\b|"
    r"\b(?:lässt|laesst)\s+sich\s+nicht\s+"
    r"(?:(?:eindeutig|belastbar|sicher)\s+)?"
    r"(?:bestimmen|beurteilen|ableiten|verallgemeinern|"
    r"schließen|schliessen|folgern|conclude)\b|"
    r"\b(?:nicht|kein(?:e|en|er|es)?)\s+"
    r"(?:bestimmbar|beurteilbar|ableitbar|bekannt)\b|"
    r"\bkein(?:e|en|er|es)?\s+(?:aussage|schluss|rückschluss|"
    r"rueckschluss)\b[^.!?\n]{0,80}\b(?:möglich|moeglich|zulässig|"
    r"zulaessig)\b|"
    r"\b(?:lässt|laesst)\s+sich\s+kein(?:e|en|er|es)?\b"
    r"[^.!?\n]{0,140}\b(?:ableiten|bestimmen|beurteilen|"
    r"verallgemeinern|schließen|schliessen|folgern|conclude)\b|"
    r"\b(?:belegt|zeigt|trägt|traegt|erlaubt)\s+"
    r"kein(?:e|en|er|es)?\b[^.!?\n]{0,140}\b"
    r"(?:im|für|fuer|auf|über|ueber)\s+"
    r"(?:das|den|dem)?\s*(?:gesamt\w*\s+)?"
    r"(?:gesamtkorpus|korpus|datenbestand|datensatz)\b"
    r")",
    re.IGNORECASE,
)
_MISSING_CORPUS_TOKEN_PATTERN = re.compile(
    r"(?:"
    r"(?:corpus_tokens|korpus[- ]?tokens?|gesamttokenzahl|"
    r"tokenbezugsgr(?:ö|oe)ße|korpusgr(?:ö|oe)ße)"
    r"[^\n.!?]{0,80}"
    r"(?:fehl|unklar|unbekannt|nicht sichtbar|keine angabe|nicht angegeben|"
    r"keine rückschlüsse|keine rueckschluesse|nicht möglich|nicht moeglich)"
    r"|"
    r"(?:fehl|unklar|unbekannt|nicht sichtbar|keine angabe|ohne|"
    r"keine rückschlüsse|keine rueckschluesse)"
    r"[^\n.!?]{0,80}"
    r"(?:corpus_tokens|korpus[- ]?tokens?|gesamttokenzahl|"
    r"tokenbezugsgr(?:ö|oe)ße|korpusgr(?:ö|oe)ße)"
    r"|"
    r"klare definition[^\n.!?]{0,80}"
    r"(?:gesamttokenzahl|tokenbezugsgr(?:ö|oe)ße)"
    r")",
    re.IGNORECASE,
)
_MISSING_TOTAL_HITS_PATTERN = re.compile(
    r"(?:"
    r"(?:gesamt(?:zahl|trefferzahl|häufigkeit|haeufigkeit)|"
    r"trefferzahl|total(?:_hits)?)"
    r"[^\n.!?]{0,100}"
    r"(?:kein(?:e|en|er|es)?|fehl\w*|unklar|unbekannt|unbelegt|nicht\s+(?:sichtbar|belegt|"
    r"angegeben)|keine\s+angabe)"
    r"|"
    r"(?:kein(?:e|en|er|es)?|fehl\w*|unklar|unbekannt|unbelegt|nicht\s+(?:sichtbar|belegt|"
    r"angegeben)|keine\s+angabe)"
    r"[^\n.!?]{0,100}"
    r"(?:gesamt(?:zahl|trefferzahl|häufigkeit|haeufigkeit)|"
    r"trefferzahl|total(?:_hits)?)"
    r")",
    re.IGNORECASE,
)
_METADATA_VALUE_COUNT_QUOTE_PATTERN = re.compile(
    r"value_count\[([^\]]+)\]=(\d+)",
    re.IGNORECASE,
)
_FOLLOWUP_METADATA_AXIS_PATTERN = re.compile(
    r"\b(?:subkorp\w*|vergleich\w*|teilkorp\w*|"
    r"korrel\w*|assozi\w*|zusammenh[aä]ng\w*|bezieh\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_SINGLETON_SCOPE_CLOSURE_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?|nicht\s+(?:als|für|fuer))\b"
    r"[^.!?\n]{0,100}\b(?:intern\w*\s+)?"
    r"(?:vergleichsachse\w*|vergleich\w*|varianz\w*|kontrast\w*)\b|"
    r"\b(?:vergleichsachse\w*|vergleich\w*|varianz\w*|kontrast\w*)\b"
    r"[^.!?\n]{0,100}\b(?:nicht\s+verfügbar|nicht\s+verfuegbar|"
    r"nicht\s+möglich|nicht\s+moeglich|ausgeschlossen)\b",
    re.IGNORECASE,
)
_FOLLOWUP_RANKING_CONTEXT_PATTERN = re.compile(
    r"(?:"
    r"\b(?:rangfolg\w*|ranglist\w*|ranking\w*)\b[^?\n]{0,180}"
    r"\b(?:kwic|kontext(?:basiert|analyse|auswertung)?|kookkurrenz\w*|"
    r"kollokation\w*)\b"
    r"|"
    r"\b(?:kwic|kontext(?:basiert|analyse|auswertung)?|kookkurrenz\w*|"
    r"kollokation\w*)\b[^?\n]{0,180}"
    r"\b(?:rangfolg\w*|ranglist\w*|ranking\w*)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_CONTROLLED_RERANK_PATTERN = re.compile(
    r"\b(?:filter\w*|auswahl\w*|subkorp\w*|teilkorp\w*|"
    r"group_by|gruppier\w*|z[aä]hleinheit\w*)\b",
    re.IGNORECASE,
)
_FOLLOWUP_RERANK_INTENT_PATTERN = re.compile(
    r"(?:"
    r"\b(?:ver[aä]nder\w*|verschieb\w*|neuberechn\w*|"
    r"neu\s+(?:berechn\w*|ordn\w*|sortier\w*)|"
    r"rerank\w*|umsortier\w*|steig\w*|fall\w*|rück\w*|rueck\w*)\b"
    r"[^?\n]{0,100}\b(?:rangfolg\w*|ranglist\w*|ranking\w*|"
    r"position\w*|pl[aä]tz\w*)\b"
    r"|"
    r"\b(?:rangfolg\w*|ranglist\w*|ranking\w*|position\w*|pl[aä]tz\w*)\b"
    r"[^?\n]{0,100}\b(?:ver[aä]nder\w*|verschieb\w*|neuberechn\w*|"
    r"neu\s+(?:berechn\w*|ordn\w*|sortier\w*)|"
    r"rerank\w*|umsortier\w*|steig\w*|fall\w*|rück\w*|rueck\w*)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_CONTEXT_CHANGE_TARGET_PATTERN = re.compile(
    r"\bver[aä]nder\w*\s+sich\s+(?:der|die|das)\s+"
    r"(?:gebrauch|verwendung|bedeutung|kontext|muster|kollokation)\w*\b",
    re.IGNORECASE,
)
_FOLLOWUP_SCOPE_CHANGE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:stattdessen|alternativ\w*|ander\w*|neu\w*|zusätzlich\w*|"
    r"zusaetzlich\w*|ergänzt\w*|ergaenzt\w*|importiert\w*|wechsel\w*)\b"
    r"[^?\n]{0,120}\b(?:gesamt|sub|teil|vergleichs)?korpus\w*|"
    r"\b(?:gesamt|sub|teil|vergleichs)?korpus\w*\b"
    r"[^?\n]{0,120}\b(?:stattdessen|alternativ\w*|ander\w*|neu\w*|"
    r"zusätzlich\w*|zusaetzlich\w*|ergänzt\w*|ergaenzt\w*|"
    r"importiert\w*|wechsel\w*|umstell\w*)\b|"
    r"\b(?:gesamtkorpus|gesamt(?:e[sn]?\s+)?korpus)\s+als\s+"
    r"(?:nenner|denominator|tokenbezugsgr(?:ö|oe)ße)\b"
    r")",
    re.IGNORECASE,
)


_FOLLOWUP_SETTLED_DENOMINATOR_SCOPE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:tokenbezugsgr(?:ö|oe)ße|denominator|nenner|tokenzahl)\b"
    r"[^?\n]{0,180}\b(?:gesamtkorpus|gesamte[sn]?\s+korpus|subkorpus|"
    r"subscope|teilkorpus|filter)\b"
    r"|"
    r"\b(?:gesamtkorpus|subkorpus|subscope|teilkorpus)\b"
    r"[^?\n]{0,180}\b(?:tokenbezugsgr(?:ö|oe)ße|denominator|nenner|tokenzahl)\b"
    r")",
    re.IGNORECASE,
)


_POS_INFERENCE_TARGET_PATTERN = re.compile(
    r"\b(?:sprachlich\w*\s+)?(?:komplex\w*|stil|"
    r"registertyp\w*|korpusspezif\w*|repräsentativ\w*|repraesentativ\w*|"
    r"textform\w*|texttyp\w*|textstruktur\w*|"
    r"thematisch\w*\s+(?:ausrichtung|schwerpunkt)|"
    r"sprachlich\w*\s+charakter)\b|"
    r"\b(?:syntakt\w*|grammat\w*|morpholog\w*)\s+"
    r"(?:struktur\w*|profil\w*|merkmal\w*)\b",
    re.IGNORECASE,
)
_POS_INFERENCE_BRIDGE_PATTERN = re.compile(
    r"\b(?:deut\w*\s+auf|sprich\w*\s+für|sprich\w*\s+fuer|"
    r"lässt\s+auf|laesst\s+auf|beleg\w*|zeig\w*|bestimm\w*|"
    r"(?:ge)?kennzeichn\w*|charakterisier\w*|"
    r"weis\w*[^.!?\n]{0,120}\bauf)\b",
    re.IGNORECASE,
)
_POS_INVENTORY_CLAIM_PATTERN = re.compile(
    r"\b(?:top[- ]?(?:n|\d+)[- ]?)?(?:liste|rangliste)\b"
    r"[^.!?\n]{0,80}\b(?:wortarten|pos(?!\s*=)(?:-kategorien)?)\b|"
    r"\b(?:wortarten|pos(?!\s*=)(?:-kategorien)?)\b[^.!?\n]{0,80}"
    r"\b(?:liste|rangliste)\b",
    re.IGNORECASE,
)
_METHODOLOGICAL_TEST_INTENT_PATTERN = re.compile(
    r"\b(?:prüf\w*|pruef\w*|untersuch\w*|validier\w*|hypothese\w*|"
    r"offene\s+frage|zu\s+klären|zu\s+klaeren)\b",
    re.IGNORECASE,
)
_METHOD_PROPOSAL_MODALITY_PATTERN = re.compile(
    r"\b(?:empfiehl\w*|sollt\w*|soll\w*|ratsam\w*|"
    r"notwendig\w*|nötig\w*|noetig\w*|"
    r"durchzuführ\w*|durchzufuehr\w*|"
    r"durchgeführt\s+werden|durchgefuehrt\s+werden)\b",
    re.IGNORECASE,
)
_ANALYSIS_OPERATION_PATTERN = re.compile(
    r"\b[\w-]*(?:analys|auswert|untersuch|prüf|pruef|vergleich|"
    r"abgleich|kodier|modellier)[\w-]*\b",
    re.IGNORECASE,
)
_THEME_INFERENCE_PATTERN = re.compile(
    r"\b(?:(?:thema|themen)(?:(?:feld|bereich)\w*)?|thematisch\w*\s+"
    r"(?:ausrichtung|schwerpunkt|profil|fokus|fokussierung|konzentration|breite|"
    r"verteilung|verknüpfung|verknuepfung|beziehung|zusammenhang)\w*|"
    r"inhaltlich\w*\s+"
    r"(?:ausrichtung|schwerpunkt|profil|fokus|fokussierung|konzentration|"
    r"verteilung|verknüpfung|verknuepfung|beziehung|zusammenhang)\w*|"
    r"thematisch\w*[^.!?\n]{0,60}\b(?:verknüpf\w*|verknuepf\w*|"
    r"zusammenh\w*|assoziier\w*)|"
    r"kernthem\w*|themenkern\w*|diskursschwerpunkt\w*|"
    r"diskursfeld\w*|spannungsfeld\w*|"
    r"(?:häuf\w*|konzentrat\w*)[^.!?\n]{0,80}"
    r"\b(?:bereich|thema|feld)\w*)\b",
    re.IGNORECASE,
)
_SEMANTIC_CLASS_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:begriff\w*|wortform\w*|wörter\w*|woerter\w*|nomen\w*|"
    r"lexem\w*|bezeichnung\w*)\b[^.!?\n]{0,100}"
    r"\b(?:für|fuer|als)\b[^.!?\n]{0,100}"
    r"\b(?:gruppe\w*|entität\w*|entitaet\w*|akteur\w*|"
    r"kategorie\w*|themen?(?:bereich|feld)?\w*)\b",
    re.IGNORECASE,
)


_TENTATIVE_THEME_PATTERN = re.compile(
    r"\b(?:kandidat\w*|hypothese\w*|möglich\w*|moeglich\w*|"
    r"potenziell\w*|vorläufig\w*|vorlaeufig\w*|hinweis\w*)\b",
    re.IGNORECASE,
)
_THEME_VALIDATION_PATTERN = re.compile(
    r"\b(?:kwic|konkordanz|kontext\w*|kollok\w*|dispersion\w*|"
    r"keyness|vergleich\w*)\b",
    re.IGNORECASE,
)


_PLATFORM_SPECIFIC_HANDLE_PATTERN = re.compile(
    r"\b(?:twitter|mastodon|bluesky|facebook|instagram)[- ]?"
    r"(?:handle|account|nutzername|profil)\w*\b",
    re.IGNORECASE,
)
_DOCUMENT_CLASS_LABEL_PATTERN = re.compile(
    r"\b(?P<label>tweets?|social[- ]?media[- ]?(?:posts?|beiträge?|beitraege)|"
    r"foren[- ]?posts?|forum[- ]?posts?|blog[- ]?posts?|posts?)\b",
    re.IGNORECASE,
)
_ASSERTED_USER_HANDLE_PATTERN = re.compile(
    r"\b(?:user[- ]?handles?|nutzer[- ]?handles?|"
    r"nutzername\w*|benutzername\w*)\b",
    re.IGNORECASE,
)
_OPEN_HANDLE_IDENTITY_TEST_PATTERN = re.compile(
    r"(?:"
    r"\b(?:prüf\w*|pruef\w*|untersuch\w*|klär\w*|klaer\w*|"
    r"ermittel\w*|überprüf\w*|ueberpruef\w*|validier\w*)\b"
    r"[^?!\n]{0,120}\bob\b[^?!\n]{0,160}"
    r"(?:"
    r"(?:@[A-Za-z0-9_]{2,64}|@[- ]?(?:form|token)\w*|"
    r"(?:wort)?form\w*|token\w*|eintrag\w*)"
    r"[^?!\n]{0,100}\b(?:handles?|user[- ]?handles?|"
    r"nutzer[- ]?handles?|nutzername\w*|account\w*)\b"
    r"[^?!\n]{0,60}\b(?:ist|sind|darstell\w*|handel\w*)\b"
    r"|"
    r"\bes\s+sich\b[^?!\n]{0,100}\bum\b[^?!\n]{0,80}"
    r"\b(?:handles?|user[- ]?handles?|nutzer[- ]?handles?|"
    r"nutzername\w*|account\w*)\b[^?!\n]{0,40}\bhandel\w*\b"
    r")"
    r")",
    re.IGNORECASE,
)
_DIRECT_HANDLE_QUALIFIER_PATTERN = re.compile(
    r"(?:"
    r"\b(?:möglich\w*|moeglich\w*|mutmaßlich\w*|mutmasslich\w*|"
    r"vermutlich\w*)\s+(?:ein\w*\s+)?"
    r"(?:user[- ]?|nutzer[- ]?)?handles?\b"
    r"|"
    r"\b(?:user[- ]?|nutzer[- ]?)?handles?\b[^.!?;\n]{0,24}"
    r"\b(?:möglich\w*|moeglich\w*|mutmaßlich\w*|mutmasslich\w*|"
    r"vermutlich\w*)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_PRESUPPOSED_EFFECT_PATTERN = re.compile(
    r"\b(?:wie|inwiefern)\b[^?\n]{0,180}\b(?:"
    r"beeinfluss\w*|bewirk\w*|verursach\w*|"
    r"verzerr\w*|wirk\w*\s+sich[^?\n]{0,50}\baus|"
    r"führ\w*[^?\n]{0,30}\bzu)\b",
    re.IGNORECASE,
)
_OPEN_EFFECT_QUESTION_PATTERN = re.compile(
    r"\b(?:ob(?:\s+und\s+wie)?|falls|gegebenenfalls|"
    r"lässt\s+sich|laesst\s+sich|prüf\w*,?\s+ob|pruef\w*,?\s+ob)\b",
    re.IGNORECASE,
)
_UNOBSERVED_RELATION_PRESUPPOSITION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:in\s+abhängig\w*\s+von|aufgrund|durch)\b"
    r"[^?!\n]{0,100}\b(?:kollok\w*|ko[- ]?okkur\w*|kookkur\w*|"
    r"co-?occurr\w*|assoziation\w*|zusammenhang\w*|"
    r"thematisch\w*\s+(?:verknüpfung|verknuepfung|beziehung))\b"
    r"|"
    r"\bwie\s+unterscheid\w*\s+sich\b[^?!\n]{0,100}"
    r"\b(?:kollok\w*|ko[- ]?okkur\w*|kookkur\w*|"
    r"co-?occurr\w*|assoziation\w*|zusammenhang\w*)\b"
    r"|"
    r"\b(?:warum|wie)\b[^?!\n]{0,140}"
    r"\b(?:kollok\w*|ko[- ]?okkur\w*|kookkur\w*|"
    r"co-?occurr\w*|assoziier\w*)\b"
    r")",
    re.IGNORECASE,
)
_OPEN_RELATION_TEST_PATTERN = re.compile(
    r"\b(?:ob(?:\s+und\s+wie)?|prüf\w*|pruef\w*|untersuch\w*|"
    r"ermittel\w*|lässt\s+sich|laesst\s+sich|"
    r"welche\w*\s+(?:kollok\w*|ko[- ]?okkur\w*|kookkur\w*|"
    r"assoziation\w*|zusammenh\w*))\b",
    re.IGNORECASE,
)
_EXPLICIT_CAUSAL_DESIGN_PATTERN = re.compile(
    r"\b(?:experiment\w*|intervention\w*|randomis\w*|"
    r"quasi[- ]?experiment\w*|natürlich\w*\s+experiment\w*|"
    r"kausal\w*\s+(?:design|identifikation|modell))\b",
    re.IGNORECASE,
)
_RELATIVE_FREQUENCY_PHRASE_PATTERN = re.compile(
    r"\brelative[snr]?\s+(?:häufigkeit|haeufigkeit|frequenz)\w*\b",
    re.IGNORECASE,
)
_ABSOLUTE_F_VALUE_PATTERN = re.compile(r"\bf\s*=\s*\d", re.IGNORECASE)
_RELATIVE_FREQUENCY_VALUE_PATTERN = re.compile(
    r"\b(?:per[_ -]?million|pro\s+million|pmw|anteil|prozent)\b|%",
    re.IGNORECASE,
)


_ABSOLUTE_ASSOCIATION_MAGNITUDE_PATTERN = re.compile(
    r"\b(?:sehr\s+)?(?:stark(?:e|en|er|es)?|schwach(?:e|en|er|es)?)\s+"
    r"(?:assoziation\w*|kollokation\w*|zusammenhang\w*)\b|"
    r"\b(?:stark|schwach)\s+"
    r"(?:assoziiert|kollokiert|verbunden)\b",
    re.IGNORECASE,
)


_EXPLICIT_ASSOCIATION_MAGNITUDE_REFERENCE_PATTERN = re.compile(
    r"\b(?:im\s+vergleich|verglichen\s+mit|gegenüber|gegenueber|"
    r"stärker\s+als|staerker\s+als|schwächer\s+als|schwaecher\s+als|"
    r"unter\s+den\s+sichtbaren|rang\w*|top[- ]?(?:n|\d+)|"
    r"schwellenwert|grenzwert|cut[- ]?off)\b",
    re.IGNORECASE,
)
_REGISTER_PATTERN = re.compile(r"\bregister\w*\b", re.IGNORECASE)
_CORRELATION_QUESTION_PATTERN = re.compile(
    r"\b(?:korrel\w*|zusammenhang\w*)\b",
    re.IGNORECASE,
)
_OBSERVATION_UNIT_PATTERN = re.compile(
    r"\b(?:dokument\w*|beitrag\w*|post\w*|tweet\w*|abschnitt\w*|"
    r"subkorp\w*|teilkorp\w*|"
    r"zeit(?:raum|punkt|periode)?\w*|autor\w*|account\w*)\b"
    r"|"
    r"\b(?:satz(?:es|e|en)?|sätz(?:e|en)|satzebene|satzweise)\b"
    r"|"
    r"\b(?:pro|je)\s+(?:text|dokument|beitrag|post|tweet|abschnitt|satz)\b",
    re.IGNORECASE,
)
_AGGREGATE_POS_MANUAL_AGREEMENT_PATTERN = re.compile(
    r"(?:"
    r"\b(?:übereinstimm\w*|uebereinstimm\w*|vergleich\w*|stimm\w*)\b"
    r"[^?!\n]{0,180}\b(?:pos|wortklass\w*)[- ]?frequenz\w*"
    r"[^?!\n]{0,180}\b(?:manuell\w*|stichprobe\w*|tokenisier\w*)\b"
    r"|"
    r"\b(?:pos|wortklass\w*)[- ]?frequenz\w*"
    r"[^?!\n]{0,180}\b(?:übereinstimm\w*|uebereinstimm\w*|"
    r"vergleich\w*|stimm\w*)\b"
    r"[^?!\n]{0,180}\b(?:manuell\w*|stichprobe\w*|tokenisier\w*)\b"
    r")",
    re.IGNORECASE,
)
_PAIRED_TOKEN_LABEL_VALIDATION_PATTERN = re.compile(
    r"(?=[^?!\n]{0,500}\bsystem(?:-|s)?(?:label|pos|tag)?\w*\b)"
    r"(?=[^?!\n]{0,500}\bgold(?:-|s)?(?:label|pos|tag)?\w*\b)"
    r"(?=[^?!\n]{0,500}\b(?:tokenebene|(?:pro|je|dieselbe\w*)\s+token)\b)"
    r"[^?!\n]+",
    re.IGNORECASE,
)
_SENTENCE_LENGTH_COMPLEXITY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:strukturell\w*|syntaktisch\w*)\s+komplexität\w*\b"
    r"[^?!\n]{0,180}\bsatzläng\w*\b"
    r"|"
    r"\bsatzläng\w*\b[^?!\n]{0,180}"
    r"\b(?:strukturell\w*|syntaktisch\w*)\s+komplexität\w*\b"
    r")",
    re.IGNORECASE,
)
_EXPLICIT_COMPLEXITY_PROXY_TEST_PATTERN = re.compile(
    r"\b(?:prüf\w*|pruef\w*|validier\w*)\b[^?!\n]{0,100}"
    r"\b(?:proxy|indikator|maß|mass)\w*\b",
    re.IGNORECASE,
)


_LOCAL_ASSOCIATION_GOAL_PATTERN = re.compile(
    r"\b(?:lokal\w*\s+assoziation\w*|"
    r"assoziation\w*\s+(?:im|in\s+einem)\s+(?:lokal\w*\s+)?"
    r"kontext)\b",
    re.IGNORECASE,
)
_COLLOCATION_CONTEXT_UNIT_PATTERN = re.compile(
    r"\b(?:fenster\w*|window\s*=\s*\d+|satz(?:grenze|ebene|weise)?\w*|"
    r"links|rechts|tokenabstand\w*)\b",
    re.IGNORECASE,
)
_ASSOCIATION_REFERENCE_PATTERN = re.compile(
    r"\b(?:assoziationsmaß\w*|assoziationsmass\w*|logdice|"
    r"log\s*likelihood|mutual\s+information|mi3?|t[- ]?score|"
    r"randfrequenz\w*|erwartungswert\w*|nullmodell\w*)\b",
    re.IGNORECASE,
)
_CATEGORY_SUM_TOTAL_GAP_PATTERN = re.compile(
    r"\b(?:differenz|lücke|luecke|residuum|abweichung)\w*\b"
    r"[^?!\n]{0,220}\b(?:summe\w*|gesamt\w*|korpusgröße\w*|"
    r"korpusgroesse\w*|tokenwert\w*)\b"
    r"|"
    r"\b(?:summe\w*|gesamt\w*|korpusgröße\w*|korpusgroesse\w*|"
    r"tokenwert\w*)\b[^?!\n]{0,220}"
    r"\b(?:differenz|lücke|luecke|residuum|abweichung)\w*\b",
    re.IGNORECASE,
)
_TOKEN_ACCOUNTING_METHOD_PATTERN = re.compile(
    r"\b(?:tokenweis\w*|bestandsabgleich\w*|zählgrundlage\w*|"
    r"zaehlgrundlage\w*|gruppierbar\w*|nicht\s+repräsentiert\w*|"
    r"nicht\s+repraesentiert\w*|fehlend\w*\s+(?:pos|tag|wert)\w*|"
    r"(?:null|leer|unknown|unbekannt)\w*\s+(?:pos|tag|wert)\w*|"
    r"ausgeschlossen\w*\s+token\w*|abdeckungszählung\w*|"
    r"abdeckungszaehlung\w*)\b",
    re.IGNORECASE,
)
_DISTRIBUTION_METHOD_PATTERN = re.compile(
    r"\b(?:(?:dokument|token|lexem|wort)?dispersion\w*|"
    r"verteil\w*|streu\w*|"
    r"dokumentabdeckung\w*|document_coverage)\b",
    re.IGNORECASE,
)
_POS_INVENTORY_METHOD_PATTERN = re.compile(
    r"(?:"
    r"\b(?:pos|part[- ]?of[- ]?speech|wortart)\w*\b"
    r"[^.!?\n]{0,100}\b(?:kategor\w*|frequenz\w*|verteil\w*|"
    r"auswert\w*|inventar\w*)\b"
    r"|"
    r"\b(?:kategor\w*|frequenz\w*|verteil\w*|auswert\w*|inventar\w*)\b"
    r"[^.!?\n]{0,100}\b(?:pos|part[- ]?of[- ]?speech|wortart)\w*\b"
    r")",
    re.IGNORECASE,
)
_EXPLICIT_POS_DISTRIBUTION_CLAIM_PATTERN = re.compile(
    r"\b(?:pos(?!\s*=)|part[- ]?of[- ]?speech|wortart)(?:-|\s*)"
    r"(?:verteilung|häufigkeit|haeufigkeit|frequenz|inventar|profil)\w*\b|"
    r"\b(?:verteilung|häufigkeit|haeufigkeit|frequenz|inventar|profil)\w*"
    r"[^.!?\n]{0,50}\b(?:der\s+)?(?:pos(?!\s*=)|wortarten?)\b",
    re.IGNORECASE,
)
_MORPHOSYNTACTIC_ANALYSIS_TARGET_PATTERN = re.compile(
    r"\b(?:(?:morpho)?syntakt\w*|grammatik\w*|grammatisch\w*)\b"
    r"[^.!?\n]{0,80}"
    r"\b(?:struktur\w*|profil\w*|vollständig\w*|vollstaendig\w*)\b"
    r"|"
    r"\b(?:struktur\w*|profil\w*|vollständig\w*|vollstaendig\w*)\b"
    r"[^.!?\n]{0,80}"
    r"\b(?:(?:morpho)?syntakt\w*|grammatik\w*|grammatisch\w*)\b",
    re.IGNORECASE,
)
_THEMATIC_OR_SEMANTIC_REACH_PATTERN = re.compile(
    r"\b(?:thematisch\w*|semantisch\w*)\s+"
    r"(?:reichweite|breite|spektrum|profil|bedeutung\w*|"
    r"schwerpunkt\w*|cluster\w*)\b",
    re.IGNORECASE,
)


_CONTEXTUAL_MEANING_PATTERN = re.compile(
    r"\b(?:bedeutung\w*|gebrauchsweis\w*|verwendungsweis\w*|"
    r"semantik\w*|sinn\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_CONTEXT_METHOD_PATTERN = re.compile(
    r"\b(?:kwic|konkordanz|kollok\w*|kontextanalyse\w*|"
    r"semantisch\w*\s+suche|semantisch\w*\s+clusteranalyse\w*|"
    r"clusteranalyse\w*|word[- ]?sketch)\b",
    re.IGNORECASE,
)
_FUNCTION_OR_ROLE_TARGET_PATTERN = re.compile(
    r"\b(?:funktion\w*|rolle\w*|akteursmarker\w*|"
    r"adressierungsfunktion\w*|interaktionsfunktion\w*)\b",
    re.IGNORECASE,
)


_GRAMMATICAL_PROFILE_PATTERN = re.compile(
    r"\b(?:pronomen\w*|personalpronomen\w*|funktionswörter\w*|"
    r"funktionswoerter\w*|interpunktion\w*|wortart\w*|pos\b)\b",
    re.IGNORECASE,
)
_STYLE_OR_TEXTTYPE_PATTERN = re.compile(
    r"\b(?:stil\w*|register\w*|textform\w*|texttyp\w*|textsorte\w*|"
    r"berichtend\w*|erzählend\w*|erzaehlend\w*|narrativ\w*|"
    r"dialogisch\w*|journalistisch\w*|informell\w*|formell\w*)\b",
    re.IGNORECASE,
)
_STYLE_INFERENCE_BRIDGE_PATTERN = re.compile(
    r"\b(?:deut\w*\s+auf|sprich\w*\s+für|sprich\w*\s+fuer|"
    r"lässt\s+vermuten|laesst\s+vermuten|lässt\s+auf|laesst\s+auf|"
    r"typisch\w*\s+(?:für|fuer)|kennzeichn\w*|charakterisier\w*)\b",
    re.IGNORECASE,
)
_CURRENT_RESULT_AS_SAMPLE_PATTERN = re.compile(
    r"\b(?:die|diese|dieser|diesem|der|vorliegend\w*|sichtbar\w*)\s+"
    r"stichprobe\b|\bin\s+(?:dieser|der)\s+stichprobe\b|"
    r"\b(?:in|bei)\s+(?:diesem|dem)\s+stichprobenumfang\b",
    re.IGNORECASE,
)
_LOCAL_COOCCURRENCE_QUESTION_PATTERN = re.compile(
    r"\b(?:kollok\w*|ko[- ]?okkur\w*|kookkur\w*|"
    r"(?:unmittelbar\w*|lokal\w*)\s+näh\w*|"
    r"im\s+(?:direkten|lokalen)\s+umfeld)\b",
    re.IGNORECASE,
)
_FOCAL_NODE_PATTERN = re.compile(
    r"\b(?:begriff|term|wort|lemma|lexem)\s+"
    r"[`'\"„“‚‘]?(?P<term>[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]{1,80})",
    re.IGNORECASE,
)
_METHOD_STEP_TEXT_ORDINAL_PATTERN = re.compile(
    r"\b(?P<ordinal>erste\w*|zweite\w*|dritte\w*|vierte\w*|"
    r"fünfte\w*|fuenfte\w*|sechste\w*|siebte\w*|achte\w*)\s+"
    r"(?:analyse[- ]?)?schritt\b",
    re.IGNORECASE,
)
_LEADING_METHOD_STEP_ORDINAL_PATTERN = re.compile(
    r"^\s*(?:"
    r"\d+(?:\ufe0f?\u20e3)?\s*[:.)\-–—]?\s*"
    r"|(?:(?:als|im|der|die|das|ein(?:e|en|em|er|es)?)\s+)?"
    r"(?:erste\w*|zweite\w*|dritte\w*|vierte\w*|"
    r"fünfte\w*|fuenfte\w*|sechste\w*|siebte\w*|achte\w*)\s+"
    r"(?:analyse[- ]?)?schritt\b"
    r"\s*(?:[:,;–—-]\s*)?"
    r")",
    re.IGNORECASE,
)
_METHOD_STEP_ORDINAL_VALUES = {
    "erste": 1,
    "zweite": 2,
    "dritte": 3,
    "vierte": 4,
    "fünfte": 5,
    "fuenfte": 5,
    "sechste": 6,
    "siebte": 7,
    "achte": 8,
}
_REDUNDANT_LEMMA_ANALYSIS_PATTERN = re.compile(
    r"(?:"
    r"\blemmatisier\w*\b"
    r"|"
    r"\b(?:lemma|lemmatisierungs|normalisierungs)[- ]?"
    r"(?:analyse|auswertung|gruppierung)\b"
    r"[^.!?\n]{0,220}\b(?:eigenständig\w*\s+lemm|flexionsform\w*|"
    r"zusammenfass\w*|zusammenführ\w*)\b"
    r"|"
    r"\b(?:feststell\w*|ermittel\w*|prüf\w*|pruef\w*)\b"
    r"[^.!?\n]{0,180}\bob\b[^.!?\n]{0,100}"
    r"\b(?:lemma\w*|flexionsform\w*)\b"
    r")",
    re.IGNORECASE,
)
_LEMMA_ANNOTATION_QA_PATTERN = re.compile(
    r"\b(?:annotation\w*|tagg\w*|fehl\w*|qualität\w*|qualitaet\w*|"
    r"validier\w*|plausibil\w*|stichprobe\w*)\b",
    re.IGNORECASE,
)


_SINGLETON_DISTINCTIVENESS_PATTERN = re.compile(
    r"(?:"
    r"\bwelche\b[^?\n]{0,160}\b(?:merkmal\w*|eigenschaft\w*)\b"
    r"[^?\n]{0,120}\b(?:zeichn\w*[^?\n]{0,80}\baus|spezif\w*|charakteristisch\w*|"
    r"unterscheid\w*)\b"
    r"|"
    r"\b(?:wie|wodurch)\b[^?\n]{0,160}\bunterscheid\w*\b"
    r")",
    re.IGNORECASE,
)
_EXPLICIT_NEW_COMPARATOR_PATTERN = re.compile(
    r"\b(?:gegenüber|gegenueber|im\s+vergleich\s+mit|vergleichskorpus|"
    r"ander(?:e|en|er|es)\s+(?:korpus|register|texttyp|modell|gruppe)|"
    r"zusätzlich(?:e[snr]?)?\s+(?:korpus|daten|gruppe))\b",
    re.IGNORECASE,
)
_SELF_CORPUS_COMPARATOR_PATTERN = re.compile(
    r"\b(?:gegenüber|gegenueber|im\s+vergleich\s+mit)\s+"
    r"(?:dem|diesem|dem\s+aktuellen|dem\s+gesamten|dem\s+restlichen)\s+"
    r"(?:gesamt)?korpus\b",
    re.IGNORECASE,
)


_COLLOCATION_METHOD_MENTION_PATTERN = re.compile(
    r"\b(?:kollokation\w*|kollokat\w*)\b",
    re.IGNORECASE,
)
_EMPTY_COLLOCATION_PROFILE_OVERREAD_PATTERN = re.compile(
    r"(?:"
    r"\bfehl\w*\s+kollokationsstruktur\w*\b|"
    r"\bkein(?:e|en|er|es)?\b[^.!?\n]{0,100}"
    r"\b(?:kollokat\w*|kontextmuster\w*|gemeinsam\w*\s+kontext\w*)\b|"
    r"\bkein(?:e|en|er|es)?\b[^.!?\n]{0,100}"
    r"\bausreichend\w*\s+(?:häufig\w*|haeufig\w*)\b[^.!?\n]{0,80}"
    r"\b(?:kollokat\w*|kontext\w*|nachbar\w*|partner\w*)\b|"
    r"\b(?:nur|ausschließlich|ausschliesslich)\b[^.!?\n]{0,140}"
    r"\b(?:spezifisch\w*|feststeh\w*|formelhaft\w*)\b[^.!?\n]{0,100}"
    r"\b(?:wendung\w*|gebrauch\w*|verwendungsweis\w*|kontext\w*)\b|"
    r"\b(?:spezifisch\w*|feststeh\w*|formelhaft\w*)\b[^.!?\n]{0,100}"
    r"\b(?:wendung\w*|gebrauch\w*|verwendungsweis\w*)\b[^.!?\n]{0,100}"
    r"\b(?:nur|ausschließlich|ausschliesslich)\b"
    r")",
    re.IGNORECASE,
)
_EMPTY_COLLOCATION_PARAMETER_BOUND_ZERO_PATTERN = re.compile(
    r"(?=[^.!?\n]{0,260}\b(?:min_freq|mindestfrequenz|"
    r"unter\s+diesen\s+parametern|bei\s+(?:dieser|der)\s+schwelle)\b)"
    r"(?=[^.!?\n]{0,260}\b(?:0\s+(?:zeilen|rows)|"
    r"keine?\b[^.!?\n]{0,100}\b(?:zurückgegeben|zurueckgegeben|"
    r"ausgegeben|geliefert))\b)[^.!?\n]+",
    re.IGNORECASE,
)
_EMPTY_COLLOCATION_PROFILE_TEST_PATTERN = re.compile(
    r"\b(?:kwic|konkordanz|kontext(?:stichprobe|analyse|kodierung)?\w*|"
    r"min_freq|mindestfrequenz|schwellenwert|fensterbreite)\b",
    re.IGNORECASE,
)
_COLLOCATION_POS_COMPOSITION_PATTERN = re.compile(
    r"\b(?:dominanz|dominant\w*|überwiegend\w*|ueberwiegend\w*|vorwiegend\w*|"
    r"hauptsächlich\w*|hauptsaechlich\w*|mehrheitlich\w*)\b"
    r"[^.!?\n]{0,140}\b(?:artikel\w*|präposition\w*|praeposition\w*|"
    r"konjunktion\w*|pronomen\w*|determiner\w*)\b|"
    r"\b(?:artikel\w*|präposition\w*|praeposition\w*|konjunktion\w*|"
    r"pronomen\w*|determiner\w*)\b[^.!?\n]{0,140}"
    r"\b(?:dominier\w*|überwieg\w*|ueberwieg\w*|vorwieg\w*)\b",
    re.IGNORECASE,
)
_DISCOURSE_FUNCTION_TARGET_PATTERN = re.compile(
    r"\b(?:diskursiv\w*\s+valenz\w*|stance\w*|haltung\w*|"
    r"frame\w*|framing\w*|abwert\w*|aufwert\w*|evaluativ\w*|"
    r"bewertungsmechanism\w*|diskursmechanism\w*|"
    r"mechanism\w*\s+(?:der\s+)?(?:abwertung|aufwertung|bewertung))\b",
    re.IGNORECASE,
)
_QUALITATIVE_CONTEXT_VALIDATION_PATTERN = re.compile(
    r"\b(?:kwic|konkordanz|qualitativ\w*\s+(?:kontext\w*|lektüre|lektuere)|"
    r"kontextkodier\w*|stance[- ]?kodier\w*|frame[- ]?kodier\w*|"
    r"manuell\w*\s+(?:prüf|pruef|validier|kodier)\w*)\b",
    re.IGNORECASE,
)
_COLLOCATION_PROFILE_COMPARISON_PATTERN = re.compile(
    r"\b(?:kollokationsprofil\w*|kollokatprofil\w*|"
    r"profilvergleich\w*|cosin\w*|jaccard\w*|"
    r"ähnlichkeitsmaß\w*|aehnlichkeitsmass\w*|distanzmaß\w*|"
    r"distanzmass\w*)\b|"
    r"\bunterscheid\w*\s+sich\s+die\s+"
    r"(?:kollokationen|kollokationsprofile|kollokatprofile)\b|"
    r"\bvergleich\w*\b[^?!\n]{0,80}\b"
    r"(?:kollokationen|kollokationsprofile|kollokatprofile)\b",
    re.IGNORECASE,
)


_UNIVERSAL_ABSENCE_PATTERN = re.compile(
    r"\b(?:alle|sämtliche|saemtliche|ausschließlich|ausschliesslich|"
    r"durchweg)\b[^.!?\n]{0,140}\b(?:fehl\w*|nicht\s+vorhanden|"
    r"gar\s+nicht|null\s+vorkommen)\b",
    re.IGNORECASE,
)


_HASHTAG_LABEL_PATTERN = re.compile(r"\bhashtags?\b", re.IGNORECASE)
_DOCUMENT_GROUP_PRESUPPOSITION_PATTERN = re.compile(
    r"\b(?:über|zwischen|nach|innerhalb)\b[^.?!\n]{0,100}"
    r"\b(?:dokument(?:unter)?grupp\w*|register\w*|teilkorp\w*)\b",
    re.IGNORECASE,
)
_CONDITIONAL_AVAILABILITY_PATTERN = re.compile(
    r"\b(?:falls|sofern|wenn|ob)\b[^.?!\n]{0,100}"
    r"\b(?:vorhanden|verfügbar|verfuegbar|existier\w*)\b",
    re.IGNORECASE,
)
_COLLOCATION_SYNTAX_GOAL_PATTERN = re.compile(
    r"\b(?:kollokation\w*|kollokat\w*)\b[^?\n]{0,180}"
    r"\b(?:syntakt\w*|grammat\w*)\b|"
    r"\b(?:syntakt\w*|grammat\w*)\b[^?\n]{0,180}"
    r"\b(?:kollokation\w*|kollokat\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_SYNTACTIC_METHOD_PATTERN = re.compile(
    r"\b(?:word[- ]?sketch|dependenz\w*|kolligation\w*|"
    r"pos[- ]?muster\w*|kwic|konkordanz\w*)\b",
    re.IGNORECASE,
)
_DATA_QUALITY_METHOD_PATTERN = re.compile(
    r"\b(?:annotat\w*|tagg\w*|pos(?:-tagg\w*)?|wortart\w*|"
    r"tokenis\w*|lemmati\w*|klassifiz\w*)\b",
    re.IGNORECASE,
)
_PRIMARY_DATA_QUALITY_FOLLOWUP_PATTERN = re.compile(
    r"\b(?:datenqualit\w*|qualit\w*|fehl\w*|plausib\w*|"
    r"korrekt\w*|zuweisung\w*|verzerr\w*|genauigkeit\w*|"
    r"übereinstimm\w*|uebereinstimm\w*|validier\w*|evaluier\w*)\b",
    re.IGNORECASE,
)
_SYSTEMATIC_DATA_QUALITY_PATTERN = re.compile(
    r"\b(?:mehrer\w*|systematisch\w*|stichprobe\w*|fehlerrate\w*|"
    r"verzerr\w*|datenqualit\w*|repräsentativ\w*|repraesentativ\w*)\b",
    re.IGNORECASE,
)
_TECHNICAL_PARTITION_MENTION_PATTERN = re.compile(
    r"\b(?:train|training|test|split|fold|partition)\w*\b",
    re.IGNORECASE,
)
_PARTITION_CONTENT_COMPARISON_PATTERN = re.compile(
    r"\b(?:inhalt\w*|thema\w*|diskurs\w*|sprach\w*|lexik\w*|"
    r"frequenz\w*|häufig\w*|haeufig\w*|unterschied\w*|"
    r"diskrepanz\w*|schwerpunkt\w*)\b",
    re.IGNORECASE,
)
_PARTITION_QA_FRAMING_PATTERN = re.compile(
    r"\b(?:datenqualit\w*|sampling\w*|robust\w*|balance\w*|"
    r"verzerr\w*|distribution[- ]?shift|leakage\w*|"
    r"kontamin\w*|fehlerrate\w*|unbeabsichtigt\w*)\b",
    re.IGNORECASE,
)
_PARTITION_QA_MEASUREMENT_PATTERN = re.compile(
    r"\b(?:normalis\w*|nenner\w*|tokennenner\w*|tokenzahl\w*|"
    r"proportion\w*|kontroll\w*)\b",
    re.IGNORECASE,
)
_PARTITION_QA_OPERATION_PATTERN = re.compile(
    r"\b(?:prüf\w*|pruef\w*|untersuch\w*|audit\w*|validier\w*|"
    r"schätz\w*|schaetz\w*|mess\w*)\b",
    re.IGNORECASE,
)
_RAW_TRUNCATION_MARKER_PATTERN = re.compile(
    r"\btruncated\s*=\s*(?:true|false)\b",
    re.IGNORECASE,
)
_INTERNAL_GROUNDING_MARKER_PATTERN = re.compile(
    r"\b(?:grounding_(?:rows|truncated)\w*|raw_ref|synthesefenster)\b",
    re.IGNORECASE,
)
_SYNTACTIC_GENERALISATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:breit\w*|vielfältig\w*|vielfaeltig\w*|dominant\w*|typisch\w*)\b"
    r"[^.!?\n]{0,100}\b(?:syntakt\w*|grammat\w*)\b"
    r"|"
    r"\b(?:syntakt\w*|grammat\w*)\b[^.!?\n]{0,100}"
    r"\b(?:breit\w*|vielfältig\w*|vielfaeltig\w*|dominant\w*|typisch\w*)\b"
    r")",
    re.IGNORECASE,
)
_SYNTACTIC_FUNCTION_GENERALISATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:dominanz|dominant\w*|typisch\w*|häufig\w*|haeufig\w*|oft|"
    r"überwiegend\w*|ueberwiegend\w*|meist\w*|regelmäßig\w*|regelmaessig\w*)\b"
    r"[^.!?\n]{0,160}\b(?:prädikat\w*|praedikat\w*|subjekt\w*|objekt\w*|"
    r"argument\w*|einbett\w*|verbgrupp\w*|konstruktion\w*|"
    r"prädikatsbestandteil\w*|praedikatsbestandteil\w*|"
    r"syntaktische[nrsm]?\s+funktion\w*|fungier\w*)\b"
    r"|"
    r"\b(?:prädikat\w*|praedikat\w*|subjekt\w*|objekt\w*|argument\w*|"
    r"einbett\w*|verbgrupp\w*|konstruktion\w*|"
    r"prädikatsbestandteil\w*|praedikatsbestandteil\w*|"
    r"syntaktische[nrsm]?\s+funktion\w*|fungier\w*)\b"
    r"[^.!?\n]{0,160}\b(?:dominanz|dominant\w*|typisch\w*|häufig\w*|"
    r"haeufig\w*|oft|überwiegend\w*|ueberwiegend\w*|meist\w*|"
    r"regelmäßig\w*|regelmaessig\w*)\b"
    r")",
    re.IGNORECASE,
)
_CATEGORICAL_SYNTACTIC_ROLE_PATTERNS = (
    (
        "object",
        re.compile(
            r"\b(?:direkt(?:e[snm]?|er)?\s+objekt|"
            r"akkusativobjekt|objektrelation)\w*\b",
            re.IGNORECASE,
        ),
    ),
    (
        "indirect_object",
        re.compile(
            r"\b(?:indirekt(?:e[snm]?|er)?\s+objekt|"
            r"dativobjekt)\w*\b",
            re.IGNORECASE,
        ),
    ),
    (
        "subject",
        re.compile(r"\b(?:subjekt|subjektrelation)\w*\b", re.IGNORECASE),
    ),
    (
        "predicate",
        re.compile(
            r"\b(?:prädikativ|praedikativ|prädikatsbestandteil|"
            r"praedikatsbestandteil|prädikat|praedikat)\w*\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prepositional_object",
        re.compile(
            r"\b(?:präpositionalobjekt|praepositionalobjekt|"
            r"präpositionales\s+objekt|praepositionales\s+objekt)\w*\b",
            re.IGNORECASE,
        ),
    ),
    (
        "genitive_attribute",
        re.compile(
            r"\b(?:genitivattribut|genitivmodifikator|"
            r"genitivisches\s+(?:attribut|modifikator))\w*\b",
            re.IGNORECASE,
        ),
    ),
)
_SYNTACTIC_ROLE_VALUE_ALIASES = {
    "object": frozenset(
        {"object", "object_of", "direct_object", "obj", "dobj"}
    ),
    "indirect_object": frozenset(
        {"indirect_object", "iobj", "dative_object"}
    ),
    "subject": frozenset(
        {"subject", "subject_of", "subj", "nsubj"}
    ),
    "predicate": frozenset(
        {"predicate", "predicative", "predicate_complement"}
    ),
    "prepositional_object": frozenset(
        {"prepositional_object", "prep_object", "pobj"}
    ),
    "genitive_attribute": frozenset(
        {"genitive_attribute", "genitive_modifier", "nmod_gen"}
    ),
}
_NEGATIVE_PRESENCE_PATTERN = re.compile(
    r"\b(?P<label>[A-ZÄÖÜ][\wÄÖÜäöüß-]{1,80})\s+"
    r"(?:kommt|tritt)\b[^.!?\n]{0,100}\b"
    r"(?:überhaupt\s+|ueberhaupt\s+)?nicht\s+(?:vor|auf)\b",
    re.IGNORECASE,
)
_FACTUAL_LIST_PRESENCE_PATTERN = re.compile(
    r"\b(?P<label>[A-ZÄÖÜ][\wÄÖÜäöüß-]{1,80})\s+"
    r"(?:ist|steht)\b[^.!?\n]{0,80}\b"
    r"(?:frequenzliste|rangliste|ranking)\b[^.!?\n]{0,40}\b"
    r"(?:belegt|enthalten|sichtbar)\b",
    re.IGNORECASE,
)
_ROW_SCOPE_ABSENCE_PATTERN = re.compile(
    r"(?:"
    r"\bfehl(?:t|en|end\w*)\b|"
    r"\bnicht\s+vorhanden\b|"
    r"\bnicht\s+(?:vor|auf)kommt\b|"
    r"\bnicht\s+auftritt\b|"
    r"\bkein(?:e|en|er|es)?\s+(?:vorkommen|beleg|treffer)\w*\b|"
    r"\b(?:kommt|tritt)\b[^.!?\n]{0,80}\bnicht\s+(?:vor|auf)\b"
    r")",
    re.IGNORECASE,
)
_ROW_SCOPE_PRESENCE_PATTERN = re.compile(
    r"(?:"
    r"\bvorhanden\b|\bvorkommend\w*\b|"
    r"\b(?:kommt|tritt)\b[^.!?\n]{0,80}\b(?:vor|auf)\b"
    r")",
    re.IGNORECASE,
)
_PARTIAL_EXHAUSTIVE_RESULT_PATTERN = re.compile(
    r"(?:"
    r"\b(?:unterschied\w*|ergebnis\w*|befund\w*|resultat\w*|"
    r"muster\w*|rangliste\w*|liste\w*)\b[^.!?\n]{0,80}"
    r"\b(?:beschränk\w*\s+sich\s+auf|beschraenk\w*\s+sich\s+auf|"
    r"besteh\w*\s+(?:nur|ausschließlich|ausschliesslich)\s+aus|"
    r"umfass\w*\s+(?:nur|ausschließlich|ausschliesslich)|"
    r"zeig\w*\s+(?:nur|ausschließlich|ausschliesslich))\b"
    r"|"
    r"\b(?:nur|ausschließlich|ausschliesslich)\s+"
    r"(?:diese|solche)\s+(?:unterschied\w*|ergebnis\w*|befund\w*|"
    r"muster\w*)\b"
    r")",
    re.IGNORECASE,
)
_ARTIFACT_CLASSIFICATION_PATTERN = re.compile(
    r"\b(?:technisch\w*\s+)?(?:artefakt\w*|ausreißer\w*|"
    r"ausreisser\w*|rauschen|noise|fehlerprodukt\w*)\b",
    re.IGNORECASE,
)
_ARTIFACT_QUALIFIER_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|"
    r"möglicherweise|moeglicherweise|potenziell\w*|vermutlich\w*|"
    r"hypothese\w*|zu\s+prüfen|zu\s+pruefen|denkbar\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_ARTIFACT_EVIDENCE_PATTERN = re.compile(
    r"\b(?:is_artifact|artifact|artifact_label|noise_label|"
    r"preprocessing_artifact)\s*=\s*(?:true|1|yes|artifact|noise)\b",
    re.IGNORECASE,
)
_PRESCRIBED_ARTIFACT_HANDLING_PATTERN = re.compile(
    r"\b(?:behandel\w*|klassifizier\w*|markier\w*|ignorier\w*|"
    r"entfern\w*|filter\w*)\b[^.!?\n]{0,100}"
    r"\b(?:artefakt\w*|ausreißer\w*|ausreisser\w*|rauschen|noise)\b",
    re.IGNORECASE,
)
_NATURAL_POS_PATTERNS = (
    (
        frozenset({"noun", "n", "substantive"}),
        re.compile(
            r"\b(?:substantiv|nomen)\b[^.!?\n]{0,60}\b"
            r"(?:annotiert|getaggt|markiert)\b|"
            r"\b(?:annotiert|getaggt|markiert)\b[^.!?\n]{0,60}\b"
            r"(?:substantiv|nomen)\b",
            re.IGNORECASE,
        ),
    ),
    (
        frozenset({"verb", "v"}),
        re.compile(
            r"\bverb\b[^.!?\n]{0,60}\b(?:annotiert|getaggt|markiert)\b|"
            r"\b(?:annotiert|getaggt|markiert)\b[^.!?\n]{0,60}\bverb\b",
            re.IGNORECASE,
        ),
    ),
    (
        frozenset({"adj", "adjective", "adjektiv"}),
        re.compile(
            r"\badjektiv\b[^.!?\n]{0,60}\b"
            r"(?:annotiert|getaggt|markiert)\b|"
            r"\b(?:annotiert|getaggt|markiert)\b[^.!?\n]{0,60}\b"
            r"adjektiv\b",
            re.IGNORECASE,
        ),
    ),
)
_KWIC_PROVENANCE_PATTERN = re.compile(
    r"\b(?:kwic|konkordanz)(?:[- ]?(?:ausgabe|zeile|treffer))?\b"
    r"[^.!?\n]{0,100}\b(?:weist|zeigt|enthält|enthaelt|liefert|ergibt)\b|"
    r"\b(?:kwic|konkordanz)[- ]?(?:zeile|treffer)\w*\b"
    r"[^.!?\n]{0,80}\b(?:zurückgegeben|zurueckgegeben|ausgegeben|"
    r"sichtbar\w*|vorlieg\w*)\b|"
    r"\b(?:zurückgegeben|zurueckgegeben|ausgegeben|sichtbar\w*|"
    r"vorlieg\w*)\b[^.!?\n]{0,80}"
    r"\b(?:kwic|konkordanz)[- ]?(?:zeile|treffer)\w*\b|"
    r"\b(?:diese[snr]?|vorliegende[snr]?|sichtbare[snr]?)\s+"
    r"(?:kwic|konkordanz)[- ]?(?:beispiel|zeile|treffer)\w*\b",
    re.IGNORECASE,
)
_SEMANTIC_PROVENANCE_PATTERN = re.compile(
    r"\bsemantisch\w*\s+"
    r"(?:suche|treffer\w*|ergebnis\w*|resultat\w*|untersuch\w*)\b",
    re.IGNORECASE,
)
_UNIFORM_DISPERSION_PATTERN = re.compile(
    r"\b(?:gleichmäßig|gleichmaessig|gleichförmig|gleichfoermig)\b"
    r"[^.!?\n]{0,120}\b(?:verteilt|streu\w*)\b|"
    r"\b(?:verteilt|streu\w*)\b[^.!?\n]{0,120}"
    r"\b(?:gleichmäßig|gleichmaessig|gleichförmig|gleichfoermig)\b",
    re.IGNORECASE,
)


_COMPLETENESS_CLAIM_PATTERN = re.compile(
    r"\b(?:vollständig|vollstaendig|komplett|lückenlos|lueckenlos)\b"
    r"[^.!?\n]{0,100}\b(?:\w*liste|ausgabe|ergebnis\w*)\b|"
    r"\b(?:\w*liste|ausgabe|ergebnis\w*)\b[^.!?\n]{0,100}"
    r"\b(?:vollständig|vollstaendig|komplett|lückenlos|lueckenlos)\b",
    re.IGNORECASE,
)
_REPRESENTATIVENESS_CLAIM_PATTERN = re.compile(
    r"\brepräsentativ|repraesentativ|repräsentier\w*|repraesentier\w*\b",
    re.IGNORECASE,
)


_CORRELATION_DIRECTION_PATTERN = re.compile(
    r"\b(?:korrelier\w*|korrelation\w*)\b[^.!?\n]{0,80}\b"
    r"(?P<direction>positiv|negativ)\w*\b|"
    r"\b(?P<direction_first>positiv|negativ)\w*\b[^.!?\n]{0,80}"
    r"\b(?:korrelier\w*|korrelation\w*)\b",
    re.IGNORECASE,
)
_INFERENTIAL_OBSERVATION_PATTERN = re.compile(
    r"\b(?:beweist|belegen?\s+damit|erklärt|erklaert|verursacht|"
    r"erzeug\w*|"
    r"(?:frequenz|häufigkeit|haeufigkeit|wert)\b[^.!?\n]{0,40}"
    r"\b(?:begünstig|beguenstig|verstärk|verstaerk|schür|schuer|"
    r"befeuer)\w*|"
    r"führt\s+(?:zu|dazu)|fuehrt\s+(?:zu|dazu)|bedingt|impliziert|legt\s+nahe|"
    r"deutet\s+auf|spricht\s+für|spricht\s+fuer|"
    r"wegen|aufgrund|löst\b[^.!?\n]{0,80}\baus|"
    r"loest\b[^.!?\n]{0,80}\baus|ausgelöst|ausgeloest|"
    r"sorgt\b[^.!?\n]{0,80}\bfür|sorgt\b[^.!?\n]{0,80}\bfuer|"
    r"ruft\b[^.!?\n]{0,80}\bhervor|"
    r"hat\b[^.!?\n]{0,80}\bzur\s+folge|"
    r"ist\b[^.!?\n]{0,80}\b(?:verantwortlich|geschuldet)|"
    r"zuzuschreiben|resultiert\s+aus|"
    r"geht\b[^.!?\n]{0,120}\bauf\b[^.!?\n]{0,120}\b"
    r"(?:zurück|zurueck)\b|"
    r"deshalb|daher|folglich|infolgedessen|"
    r"daraus\s+folgt(?!\s+(?:noch\s+)?(?:kein\w*|nicht))|"
    r"aus\b[^.!?\n]{0,80}\bfolgt"
    r"(?!\s+(?:noch\s+)?(?:kein\w*|nicht))|"
    r"ist\s+(?:eine?\s+)?ursache|gesellschaftliche\s+relevanz|"
    r"(?:offenbar|verdeutlich|illustrier)\w*[^.!?\n]{0,80}"
    r"\b(?:spannungsfeld|kontrast|polarisier\w*)|"
    r"dien\w*[^.!?\n]{0,80}\bals\s+(?:indikator|hinweis)\w*|"
    r"charakteristisch\s+sein\s+könn\w*|"
    r"charakteristisch\s+sein\s+koenn\w*|"
    r"lässt\s+auf[^.!?\n]{0,80}\bschließ\w*|"
    r"laesst\s+auf[^.!?\n]{0,80}\bschliess\w*)\b",
    re.IGNORECASE,
)
_CROSS_TOOL_CAUSAL_PATTERN = re.compile(
    r"\b(?:erklärt|erklaert|verursacht|führt\s+(?:zu|dazu)|"
    r"erzeug\w*|"
    r"(?:frequenz|häufigkeit|haeufigkeit|wert)\b[^.!?\n]{0,40}"
    r"\b(?:begünstig|beguenstig|verstärk|verstaerk|schür|schuer|"
    r"befeuer)\w*|"
    r"fuehrt\s+(?:zu|dazu)|"
    r"bedingt|bewirkt|aufgrund|wegen|infolge|ursächlich|ursaechlich|"
    r"löst\b[^.!?\n]{0,80}\baus|loest\b[^.!?\n]{0,80}\baus|"
    r"ausgelöst|ausgeloest|hat\b[^.!?\n]{0,80}\bzur\s+folge|"
    r"sorgt\b[^.!?\n]{0,80}\bfür|sorgt\b[^.!?\n]{0,80}\bfuer|"
    r"ruft\b[^.!?\n]{0,80}\bhervor|"
    r"ist\b[^.!?\n]{0,80}\b(?:verantwortlich|geschuldet)|"
    r"zuzuschreiben|resultiert\s+aus|"
    r"geht\b[^.!?\n]{0,120}\bauf\b[^.!?\n]{0,120}\b"
    r"(?:zurück|zurueck)\b|"
    r"ist\s+(?:eine?\s+)?ursache|korreliert|korrelation|zusammenhang|"
    r"aus\b[^.!?\n]{0,80}\bfolgt"
    r"(?!\s+(?:noch\s+)?(?:kein\w*|nicht))|"
    r"(?:deshalb|daraus)\s+(?:entsteht|ergibt|resultiert|"
    r"folgt(?!\s+(?:noch\s+)?(?:kein\w*|nicht))))\b",
    re.IGNORECASE,
)
_CAUSAL_ASSERTION_PATTERN = re.compile(
    r"\b(?:erklärt|erklaert|verursacht|führt\s+(?:zu|dazu)|"
    r"erzeug\w*|"
    r"(?:frequenz|häufigkeit|haeufigkeit|wert)\b[^.!?\n]{0,40}"
    r"\b(?:begünstig|beguenstig|verstärk|verstaerk|schür|schuer|"
    r"befeuer)\w*|"
    r"fuehrt\s+(?:zu|dazu)|"
    r"bedingt|bewirkt|ursächlich|ursaechlich|wegen|aufgrund|"
    r"löst\b[^.!?\n]{0,80}\baus|loest\b[^.!?\n]{0,80}\baus|"
    r"ausgelöst|ausgeloest|hat\b[^.!?\n]{0,80}\bzur\s+folge|"
    r"sorgt\b[^.!?\n]{0,80}\bfür|sorgt\b[^.!?\n]{0,80}\bfuer|"
    r"ruft\b[^.!?\n]{0,80}\bhervor|"
    r"ist\b[^.!?\n]{0,80}\b(?:verantwortlich|geschuldet)|"
    r"zuzuschreiben|resultiert\s+aus|"
    r"geht\b[^.!?\n]{0,120}\bauf\b[^.!?\n]{0,120}\b"
    r"(?:zurück|zurueck)\b|"
    r"ist\s+(?:deshalb\s+)?(?:eine?\s+)?ursache|"
    r"aus\b[^.!?\n]{0,80}\bfolgt"
    r"(?!\s+(?:(?:noch\s+)?(?:kein\w*|nicht)|"
    r"als\s+(?:nächster|naechster)\s+schritt))|"
    r"(?:deshalb|daraus)\s+(?:entsteht|ergibt|resultiert|"
    r"folgt(?!\s+(?:noch\s+)?(?:kein\w*|nicht))))\b",
    re.IGNORECASE,
)
_NEGATIVE_METHOD_CONCLUSION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:nicht|kein(?:e|en|er|es)?|fehl(?:t|en|end\w*)|unbekannt|"
    r"unklar|unbelegt)\b[^.!?\n]{0,140}"
    r"\b(?:voraussetzung|vergleich|\w*(?:analys|urteil|berechn)\w*|"
    r"auswertung|auswertbar|methode|"
    r"anwendbar|durchführbar|durchfuehrbar|interpretierbar|ableitbar|"
    r"beurteilbar|evidenz|grundlage)\w*"
    r"|"
    r"\b(?:voraussetzung|vergleich|\w*(?:analys|urteil|berechn)\w*|"
    r"auswertung|auswertbar|methode|"
    r"anwendbar|durchführbar|durchfuehrbar|interpretierbar|ableitbar|"
    r"beurteilbar|evidenz|grundlage)\w*[^.!?\n]{0,140}"
    r"\b(?:nicht|kein(?:e|en|er|es)?|fehl(?:t|en|end\w*)|unbekannt|"
    r"unklar|unbelegt)\b"
    r")",
    re.IGNORECASE,
)
_METHOD_ONLY_NEGATIVE_CONCLUSION_PATTERN = re.compile(
    r"\bmethodisch\s+(?:nur|lediglich)\b"
    r"[^.!?\n]{0,220}\b(?:nicht\s+(?:auswertbar|anwendbar|"
    r"durchführbar|durchfuehrbar|beurteilbar|ableitbar|interpretierbar)|"
    r"kein(?:e|en|er|es)?\s+(?:auswertung|vergleich|schluss|"
    r"rückschluss|rueckschluss))\b",
    re.IGNORECASE,
)
_PURE_EPISTEMIC_NEGATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:nicht|kein(?:e|en|er|es)?|ohne|unklar|unbekannt|unbelegt|"
    r"fehl(?:t|en|end\w*))\b[^.!?\n]{0,120}"
    r"\b(?:beleg\w*|evidenz\w*|nachweis\w*|ableit\w*|bestimm\w*|"
    r"beurteil\w*|sichtbar\w*|bekannt\w*|grundlage\w*)\b"
    r"|"
    r"\b(?:beleg\w*|evidenz\w*|nachweis\w*|ableit\w*|bestimm\w*|"
    r"beurteil\w*|sichtbar\w*|bekannt\w*|grundlage\w*)\b"
    r"[^.!?\n]{0,120}\b(?:nicht|kein(?:e|en|er|es)?|ohne|unklar|"
    r"unbekannt|unbelegt|fehl(?:t|en|end\w*))\b"
    r")",
    re.IGNORECASE,
)
_LEXICAL_SUBSTITUTION_PATTERN = re.compile(
    r"(?:\b(?:synonym\w*|thematisch\w*\s+verwandt\w*\s+begriff\w*|"
    r"alternativ\w*\s+lexik\w*)\b[^.!?\n]{0,140}"
    r"\b(?:verwend\w*|gebrauch\w*|nutz\w*|ersetz\w*|anstelle)\b|"
    r"\b(?:anstelle|stattdessen|ersetz\w*)\b[^.!?\n]{0,140}"
    r"\b(?:wort\w*|begriff\w*|terminolog\w*)\b|"
    r"\b(?:lexikalisch\w*\s+(?:fokus|präferenz|praeferenz)|"
    r"sprachlich\w*\s+präferenz|sprachlich\w*\s+praeferenz)\b)",
    re.IGNORECASE,
)
_INTENTIONAL_LEXICAL_AVOIDANCE_PATTERN = re.compile(
    r"\b(?:bewusst|absichtlich|gezielt|strategisch)\w*\b"
    r"[^.!?\n]{0,120}\b(?:meid\w*|vermeid\w*|umgeh\w*|"
    r"nicht\s+verwend\w*)\b|"
    r"\bterminologiestrateg\w*\b",
    re.IGNORECASE,
)
_EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN = re.compile(
    r"\b(?:zu\s+prüf\w*|zu\s+pruef\w*|hypothese\w*|"
    r"widerleg\w*|falsifizier\w*|prüfen\s+ließe|pruefen\s+liesse)\b",
    re.IGNORECASE,
)
_NEGATIVE_RESULT_POSITIVE_ASSERTION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:ist|sind|bleibt|bleiben)\s+(?:klar\s+)?"
    r"(?:belegt|nachgewiesen|vorhanden|sichtbar)\b|"
    r"\b(?:beleg|beweis|zeig|nachweis|enthält|enthaelt|stamm)\w*\b|"
    r"\b(?:tritt|kommt)\b[^.!?\n]{0,80}\b(?:auf|vor)\b"
    r")",
    re.IGNORECASE,
)
_NEGATED_CAUSAL_RELATION_PATTERN = re.compile(
    r"(?:"
    r"\bweder\b[^.!?\n]{0,100}\b"
    r"(?:zusammenhang\w*|korrelation\w*)\b"
    r"|"
    r"\bkein(?:e|en|er|es)?\s+"
    r"(?:(?:belastbar|statistisch|kausal)\w*\s+){0,3}"
    r"(?:zusammenhang\w*|korrelation\w*)\b"
    r"|"
    r"\bkein(?:e|en|er|es)?\s+"
    r"(?:[\wÄÖÜäöüß-]+\s+){0,2}"
    r"(?:aussage|schluss|rückschluss|rueckschluss)\w*\b"
    r"[^.!?\n]{0,80}\b(?:zusammenhang\w*|korrelation\w*)\b"
    r"|"
    r"\bkein(?:e|en|er|es)?\s+hinweis\s+auf\s+"
    r"(?:kausal\w*|ursache\w*|wirkung\w*|zusammenhang\w*|korrelation\w*)\b"
    r"|"
    r"\b(?:kein(?:e|en|er|es)?|ohne)\s+"
    r"(?:kausal\w*|ursache\w*|wirkung\w*|zusammenhang\w*|korrelation\w*)\b"
    r"|"
    r"\b(?:kausal\w*|ursache\w*|wirkung\w*|zusammenhang\w*|korrelation\w*)\b"
    r"[^.!?\n]{0,80}\b(?:nicht|kein(?:e|en|er|es)?|unbelegt)\b"
    r"|"
    r"\b(?:verursacht|erklärt|erklaert|bewirkt|bedingt|erzeug\w*)\s+nicht\b"
    r"|"
    r"\b(?:frequenz|häufigkeit|haeufigkeit|wert)\b[^.!?\n]{0,40}"
    r"\b(?:begünstig|beguenstig|verstärk|verstaerk|schür|schuer|"
    r"befeuer)\w*\s+nicht\b"
    r"|"
    r"\b(?:führt|fuehrt)\s+nicht\s+(?:zu|dazu)\b"
    r"|"
    r"\b(?:löst|loest)\b[^.!?\n]{0,80}\bnicht\s+aus\b"
    r"|"
    r"\bsorgt\b[^.!?\n]{0,80}\bnicht\s+(?:für|fuer)\b"
    r"|"
    r"\bruft\b[^.!?\n]{0,80}\bnicht\s+hervor\b"
    r"|"
    r"\bist\b[^.!?\n]{0,80}\bnicht\s+verantwortlich\b"
    r"|"
    r"\bist\b[^.!?\n]{0,80}\bnicht\b[^.!?\n]{0,40}\bgeschuldet\b"
    r"|"
    r"\bresultiert\s+nicht\s+aus\b"
    r"|"
    r"\bgeht\s+nicht\b[^.!?\n]{0,120}\bauf\b"
    r"[^.!?\n]{0,120}\b(?:zurück|zurueck)\b"
    r")",
    re.IGNORECASE,
)
_METHODOLOGICAL_SCOPE_EXPLANATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:sortier\w*|top[- ]?(?:n|\d+)|begrenz\w*|"
    r"gruppier\w*|unterschiedlich\w*\s+messgr(?:ö|oe)ß\w*|"
    r"verschieden\w*\s+messniveau\w*|"
    r"getrennt\w*\s+ergebnisr[aä]um\w*|"
    r"(?:nicht\s+)?kommensurab\w*)\b"
    r"[^.!?\n]{0,180}\b(?:sichtbar\w*|ausschnitt\w*|außerhalb|"
    r"ausserhalb|list\w*|rang\w*|ranking\w*|interpretier\w*|"
    r"vergleich\w*|gemeinsam\w*|wortform\w*|lemmaeintr\w*|"
    r"zusammenfass\w*|definier\w*|verbind\w*)\b"
    r"|"
    r"\b(?:sichtbar\w*|ausschnitt\w*|außerhalb|ausserhalb|"
    r"list\w*|rang\w*|ranking\w*|interpretier\w*|vergleich\w*|"
    r"gemeinsam\w*|wortform\w*|lemmaeintr\w*|zusammenfass\w*|"
    r"definier\w*|verbind\w*)\b"
    r"[^.!?\n]{0,180}"
    r"\b(?:sortier\w*|top[- ]?(?:n|\d+)|begrenz\w*|gruppier\w*|"
    r"unterschiedlich\w*\s+messgr(?:ö|oe)ß\w*|"
    r"verschieden\w*\s+messniveau\w*|"
    r"getrennt\w*\s+ergebnisr[aä]um\w*|"
    r"(?:nicht\s+)?kommensurab\w*)\b"
    r")",
    re.IGNORECASE,
)
_METHODOLOGICAL_SCOPE_EVIDENCE_PATTERN = re.compile(
    r"\b(?:sort_by|limit|top_n|truncated|group_by|result_scope)\s*="
    r"|\b(?:top[- ]?n|sortier\w*|begrenz\w*)\b",
    re.IGNORECASE,
)
_INCOMMENSURABLE_RESULTS_PATTERN = re.compile(
    r"(?:"
    r"\bunterschiedlich\w*\s+messgr(?:ö|oe)ß\w*\b"
    r"[^.!?\n]{0,180}\b(?:kein\w*\s+gemeinsam\w*\s+"
    r"(?:rangplatz|rangfolg\w*|ranglist\w*|ranking)|"
    r"nicht\s+(?:direkt\s+)?vergleich\w*|nicht\s+ableitbar)\b"
    r"|"
    r"\b(?:kein\w*\s+gemeinsam\w*\s+"
    r"(?:rangplatz|rangfolg\w*|ranglist\w*|ranking)|"
    r"nicht\s+(?:direkt\s+)?vergleich\w*|nicht\s+ableitbar)\b"
    r"[^.!?\n]{0,180}\bunterschiedlich\w*\s+messgr(?:ö|oe)ß\w*\b"
    r"|"
    r"\bnicht\s+kommensurab\w*\b[^.!?\n]{0,180}\b"
    r"(?:gemeinsam\w*\s+)?(?:rangplatz|rangfolg\w*|ranglist\w*|ranking)\b"
    r"[^.!?\n]{0,80}\bnicht\s+definier\w*\b"
    r")",
    re.IGNORECASE,
)
_FIELD_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![\w.])([A-Za-z_][A-Za-z0-9_.-]{0,39})\s*(=|:)\s*"
    r"\(?\s*(?:[\"'`]([^\"'`\n]{1,120})[\"'`]|"
    r"(-?\d+(?:[.,]\d+)?|true|false|null|none|"
    r"[A-Za-z_][A-Za-z0-9_.:/-]{0,119}"
    r"(?![A-Za-z0-9_.:/-]|\s*=)))\s*\)?",
    re.IGNORECASE,
)
_ROW_SCOPED_FIELD_NAMES = frozenset(
    {
        "rank",
        "word",
        "kw",
        "f",
        "f2",
        "frequency",
        "logdice",
        "mi3",
        "score",
        "score_key",
        "mi",
        "t",
        "ll",
        "dice",
        "chi2_cell",
        "chi2_cell_human",
        "chi2_cell_ai",
        "chi2_cell_target",
        "chi2_cell_reference",
        "delta_p_nc",
        "delta_p_cn",
        "freq_human",
        "freq_ai",
        "freq_target",
        "freq_reference",
        "log_ratio",
        "one_sided",
        "per_million",
        "p_value",
        "standard_deviation",
        "standard_error",
        "median",
        "lmi",
        "npmi",
        "z",
        "doc_id",
        "snippet",
    }
)
_DECIMAL_METRIC_FIELD_NAMES = frozenset(
    {
        "score",
        "logdice",
        "mi3",
        "mi",
        "t",
        "ll",
        "dice",
        "chi2_cell",
        "chi2_cell_human",
        "chi2_cell_ai",
        "chi2_cell_target",
        "chi2_cell_reference",
        "delta_p_nc",
        "delta_p_cn",
        "log_ratio",
        "lmi",
        "npmi",
        "z",
        "dp",
        "dpnorm",
        "juilland_d",
        "carroll_d2",
        "range_prop",
        "vc",
        "coverage_ratio",
        "peak_share",
        "per_million",
        "p_value",
        "standard_deviation",
        "standard_error",
        "median",
    }
)
_HIT_COUNT_FIELD_NAMES = frozenset(
    {
        "total",
        "total_hits",
        "f",
        "f2",
        "freq",
        "frequency",
        "count",
        "anchor_count",
        "coverage_count",
        "range",
        "freq_human",
        "freq_ai",
        "freq_target",
        "freq_reference",
    }
)
_TOTAL_HIT_COUNT_FIELD_NAMES = frozenset({"total", "total_hits"})
_RESULT_COUNT_FIELD_NAMES = frozenset(
    {"rows_seen", "result_count", "candidate_count", "row_limit", "total_rows"}
)
_DOCUMENT_COUNT_FIELD_NAMES = frozenset(
    {"n_documents", "documents_with_hits", "doc_count"}
)
_CLUSTER_COUNT_FIELD_NAMES = frozenset(
    {"clusters_seen", "cluster_count", "total_clusters"}
)
_RATIO_PERCENT_FIELD_NAMES = frozenset(
    {"coverage_ratio", "peak_share"}
)
_EXPLICIT_PERCENT_FIELD_NAMES = frozenset(
    {"percent", "percentage", "share_percent"}
)
_INTEGER_COUNT_FIELD_NAMES = frozenset(
    set(_HIT_COUNT_FIELD_NAMES)
    | set(_TOTAL_HIT_COUNT_FIELD_NAMES)
    | set(_RESULT_COUNT_FIELD_NAMES)
    | set(_DOCUMENT_COUNT_FIELD_NAMES)
    | set(_CLUSTER_COUNT_FIELD_NAMES)
    | {
        "corpus_raw_token_count",
        "corpus_tokens",
        "denominator_tokens",
        "n_tokens",
        "n_types",
        "population",
        "requested",
        "drawn",
        "limit",
        "min_freq",
        "rank",
        "sttr_n_windows",
        "sttr_window",
        "mattr_window",
        "window",
    }
)
_FIELD_VALUE_ATOM_PATTERN = re.compile(
    r"[\"'`]([^\"'`\n]{1,120})[\"'`]|"
    r"(-?\d+(?:[.,]\d+)?|true|false|null|none|"
    r"[^\s,;|()\[\]{}=\"'`]{1,120})",
    re.IGNORECASE,
)


_GROUP_SEP_CHARS = ".   "  # thousands separators stripped during normalisation
_FIELD_NAME_ALIASES = {
    "attribut": "attribute",
    "abhaengigkeitsereignis": "f",
    "abhaengigkeitsereignisse": "f",
    "abhängigkeitsereignis": "f",
    "abhängigkeitsereignisse": "f",
    "dependenzereignis": "f",
    "dependenzereignisse": "f",
    "fenster": "window",
    "kontextfenster": "window",
    "korpus_id": "corpus_id",
    "mindestfrequenz": "min_freq",
    "request": "requested",
    "satzgrenze": "within_sentence",
    "sortierung": "sort_by",
}


def _normalize_number_token(
    token: str,
    *,
    integer_grouping: bool = False,
) -> str:
    """Canonicalise a matched number so equal magnitudes compare equal regardless
    of locale grouping.

    The grounding membership tests compare claim numbers against the numbers in
    the evidence surface as a *set*. A tool renders a raw integer ("1234") while
    the LLM may echo it with a German thousands dot/space ("1.234" / "1 234") or
    an English thousands comma ("1,234"); all four denote the same magnitude and
    must collapse to one token, otherwise a perfectly grounded count is
    false-rejected.

    Disambiguation rules (a single `.`/`,` before exactly three digits is the
    classic thousands ambiguity):

    * Spaced groups ("1 234", incl. U+00A0/U+202F) are always thousands.
    * Multiple identical separators ("1.234.567" / "1,234,567") are thousands.
    * German grouped with decimal comma ("1.234,5") -> strip dots, comma -> dot.
    * English grouped with decimal dot ("1,234.5") -> strip commas, keep dot.
    * A lone "X.YYY" / "X,YYY" is ambiguous and therefore remains decimal by
      default. It is collapsed only when the caller knows that the value is an
      integer count (for example ``total=1.234`` or ``1.234 Tokens``).
    * Everything else is a plain integer or a genuine single-separator decimal
      ("3.14", "0,5"); the decimal separator normalises to "." and trailing
      zeros are trimmed so "12" == "12.0".
    """
    raw = token.strip()
    if not raw:
        return ""
    has_space = any(ch in raw for ch in "   ")
    dot_count = raw.count(".")
    comma_count = raw.count(",")

    def _trim(value: str) -> str:
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        return value or "0"

    # German grouped with explicit decimal comma: 1.234,56 / 1 234,56
    if comma_count == 1 and (dot_count >= 1 or has_space) and raw.rfind(",") > raw.rfind("."):
        integer = raw[: raw.rfind(",")]
        frac = raw[raw.rfind(",") + 1 :]
        for ch in _GROUP_SEP_CHARS:
            integer = integer.replace(ch, "")
        return _trim(f"{integer}.{frac}")
    # English grouped with explicit decimal dot: 1,234.56
    if dot_count == 1 and comma_count >= 1 and raw.rfind(".") > raw.rfind(","):
        return _trim(raw.replace(",", ""))
    # Pure spaced/multi-dot/multi-comma grouping -> integer thousands.
    if has_space or dot_count >= 2 or comma_count >= 2:
        for ch in _GROUP_SEP_CHARS + ",":
            raw = raw.replace(ch, "")
        return raw or "0"
    # A lone three-digit tail is grouped only in an explicit integer context.
    # A leading zero remains decimal even there: ``0.977`` is a common metric.
    m = re.fullmatch(r"([+-]?)(\d{1,3})[.,](\d{3})", raw)
    if integer_grouping and m and m.group(2) != "0":
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    # Plain integer or genuine single-separator decimal.
    return _trim(raw.replace(",", "."))


def _number_has_integer_grouping_context(
    text: str,
    match: re.Match[str],
) -> bool:
    """Resolve a lone three-digit separator only from an explicit count context."""

    raw = match.group(0)
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", raw) is None:
        return False
    before = str(text or "")[max(0, match.start() - 64) : match.start()]
    after = str(text or "")[match.end() : match.end() + 40]
    field_match = re.search(
        r"([A-Za-z_][A-Za-z0-9_.-]{0,39})\s*(?:=|:)\s*$",
        before,
    )
    if field_match is not None:
        field = _FIELD_NAME_ALIASES.get(
            field_match.group(1).casefold(),
            field_match.group(1).casefold(),
        )
        if field in _INTEGER_COUNT_FIELD_NAMES:
            return True
    return re.match(
        r"\s*(?:analysierte\s+)?(?:tokens?|types?|dokumente?|docs?|"
        r"treffer(?:n)?|vorkommen|belege?|zeilen|fenster|windows?|"
        r"kandidaten?|cluster|lemmata|wortformen?)\b",
        after,
        re.IGNORECASE,
    ) is not None


def _extract_numeric_tokens(text: str, *, signed: bool = False) -> List[str]:
    return [
        _normalize_number_token(
            match.group(0),
            integer_grouping=_number_has_integer_grouping_context(text, match),
        )
        for match in (_SIGNED_NUMBER_PATTERN if signed else _NUMBER_PATTERN).finditer(text)
    ]


def _normalise_field_value(value: Any, *, field: str = "") -> str:
    text = str(value or "").strip().strip("`\"'").rstrip(".,;:!?").casefold()
    canonical_field = _FIELD_NAME_ALIASES.get(field.casefold(), field.casefold())
    if (
        canonical_field in _DECIMAL_METRIC_FIELD_NAMES
        and re.fullmatch(r"-?\d+(?:[.,]\d+)?", text)
    ):
        decimal = text.replace(",", ".")
        if "." in decimal:
            decimal = decimal.rstrip("0").rstrip(".")
        return decimal or "0"
    numbers = [
        _normalize_number_token(
            text,
            integer_grouping=canonical_field in _INTEGER_COUNT_FIELD_NAMES,
        )
    ] if re.fullmatch(r"-?\d+(?:[.,]\d+)?", text) else []
    if len(numbers) == 1 and re.fullmatch(r"-?\d+(?:[.,]\d+)?", text):
        return numbers[0]
    return text


def _source_values_for_field(field: str, source_surface: str) -> set[str]:
    escaped = re.escape(field)
    field_token = (
        rf"(?<![A-Za-z0-9_.-])[\"'`]?{escaped}[\"'`]?"
        rf"(?![A-Za-z0-9_.-])"
    )
    pair_pattern = re.compile(
        rf"(?:values\[{escaped}\]|{field_token})\s*(?:=|:)\s*"
        r"\(?\s*(\[[^\]\n]{0,240}\]|[\"'`][^\"'`\n]{1,120}[\"'`]|"
        r"-?\d+(?:[.,]\d+)?|true|false|null|none|"
        r"[^\s,;|()\[\]{}=\"'`]{1,120})\s*\)?",
        re.IGNORECASE,
    )
    values: set[str] = set()
    for pair in pair_pattern.finditer(source_surface or ""):
        for atom in _FIELD_VALUE_ATOM_PATTERN.finditer(pair.group(1)):
            value = _normalise_field_value(
                atom.group(1) or atom.group(2) or "",
                field=field,
            )
            if value:
                values.add(value)
    return values


def _canonical_field_name(field: str) -> str:
    lowered = str(field or "").strip().casefold()
    return _FIELD_NAME_ALIASES.get(lowered, lowered)


def _unsupported_field_assignments(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    unsupported: List[str] = []
    for match in _FIELD_ASSIGNMENT_PATTERN.finditer(claim_text or ""):
        original_field = match.group(1)
        separator = match.group(2)
        field = _canonical_field_name(original_field)
        raw_value = match.group(3) or match.group(4) or ""
        value = _normalise_field_value(raw_value, field=field)
        source_values = _source_values_for_field(field, source_surface)
        if (
            separator == ":"
            and not source_values
            and original_field.casefold() not in _FIELD_NAME_ALIASES
        ):
            continue
        if value and value not in source_values:
            unsupported.append(f"{original_field}={raw_value}")
    return list(dict.fromkeys(unsupported))


_SLASH_SEPARATED_ROW_FIELD_PATTERN = re.compile(
    rf"(?<![\w.])(?P<field>[A-Za-z_][A-Za-z0-9_.-]{{0,39}})"
    rf"\s*(?:=|:)\s*(?P<values>-?(?:{_NUMBER_PATTERN.pattern})"
    rf"(?:\s*/\s*-?(?:{_NUMBER_PATTERN.pattern}))+)",
    re.IGNORECASE,
)


def _unsupported_slash_separated_row_field_bindings(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    """Reject several row values compressed into one singular field binding."""

    unsupported: List[str] = []
    for match in _SLASH_SEPARATED_ROW_FIELD_PATTERN.finditer(
        claim_text or ""
    ):
        field = _canonical_field_name(match.group("field"))
        if (
            field not in _ROW_SCOPED_FIELD_NAMES
            or field in _ROW_LABEL_FIELD_NAMES
        ):
            continue
        raw_values = match.group("values")
        exact_binding = re.compile(
            rf"(?<![\w.]){re.escape(match.group('field'))}\s*(?:=|:)\s*"
            + r"\s*/\s*".join(
                re.escape(value.group(0))
                for value in _NUMBER_PATTERN.finditer(raw_values)
            ),
            re.IGNORECASE,
        )
        if exact_binding.search(source_surface or "") is None:
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _literal_value_occurrences(text: str, value: str) -> List[tuple[int, int]]:
    needle = str(value or "").strip()
    if not needle:
        return []
    boundary_left = r"(?<!\w)" if needle[0].isalnum() else ""
    boundary_right = r"(?!\w)" if needle[-1].isalnum() else ""
    return [
        (match.start(), match.end())
        for match in re.finditer(
            boundary_left + re.escape(needle) + boundary_right,
            text or "",
            re.IGNORECASE,
        )
    ]


def _literal_value_occurs_in_compound(text: str, value: str) -> bool:
    """Detect long lexical metadata values inside German compounds."""

    needle = str(value or "").strip()
    if len(needle) < 5 or not needle.isalpha():
        return False
    escaped = re.escape(needle)
    return re.search(
        rf"(?<!\w){escaped}(?=[A-Za-zÄÖÜäöüß])"
        rf"|(?<=[A-Za-zÄÖÜäöüß]){escaped}(?!\w)",
        text or "",
        re.IGNORECASE,
    ) is not None


_RELATION_LABEL_ALIASES = {
    "object": ("Objektrelation", "Objekt-Relation"),
    "object_of": ("Objektrelation", "Objekt-Relation"),
    "subject": ("Subjektrelation", "Subjekt-Relation"),
    "subject_of": ("Subjektrelation", "Subjekt-Relation"),
}


def _row_label_surface_forms(field: str, value: str) -> tuple[str, ...]:
    aliases = (
        _RELATION_LABEL_ALIASES.get(value.casefold(), ())
        if field == "relation"
        else ()
    )
    return tuple(dict.fromkeys((value, *aliases)))


def _row_label_mentions(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[tuple[int, int, str, str]]:
    mentions: List[tuple[int, int, str, str]] = []
    seen: set[tuple[int, int, str]] = set()
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        for field in _ROW_LABEL_FIELD_NAMES:
            for value in _source_values_for_field(field, surface):
                for surface_form in _row_label_surface_forms(field, value):
                    for start, end in _literal_value_occurrences(
                        claim_text,
                        surface_form,
                    ):
                        key = (start, end, value)
                        if key in seen:
                            continue
                        seen.add(key)
                        mentions.append((start, end, field, value))
    return sorted(mentions)


def _row_binding_mentions(
    claim_text: str,
    facts: Sequence[ObservedFact],
    measurement_spans: Sequence[tuple[int, int, str]],
) -> List[tuple[int, int, str, str]]:
    """Drop repeated discourse mentions that carry no new row measurement."""

    mentions = _row_label_mentions(claim_text, facts)
    if len(mentions) < 2:
        return mentions
    result: List[tuple[int, int, str, str]] = []
    seen_values: set[tuple[str, str]] = set()
    for index, mention in enumerate(mentions):
        start, end, field, value = mention
        key = (field, value)
        next_label_start = (
            mentions[index + 1][0]
            if index + 1 < len(mentions)
            else len(claim_text)
        )
        previous_label_end = mentions[index - 1][1] if index else 0
        adjacent_measurement = any(
            (
                previous_label_end <= metric_start
                and metric_end <= start
            )
            or (
                end <= metric_start
                and metric_end <= next_label_start
            )
            for metric_start, metric_end, _measurement in measurement_spans
        )
        if key in seen_values and not adjacent_measurement:
            continue
        seen_values.add(key)
        result.append(mention)
    return result


def _row_field_assignments_are_atomic(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    assignments = [
        match
        for match in _FIELD_ASSIGNMENT_PATTERN.finditer(claim_text or "")
        if _canonical_field_name(match.group(1)) in _ROW_SCOPED_FIELD_NAMES
    ]
    metric_assignments = [
        match
        for match in assignments
        if _canonical_field_name(match.group(1))
        not in _ROW_LABEL_FIELD_NAMES
    ]
    measurement_spans: List[tuple[int, int, str]] = [
        (match.start(), match.end(), match.group(0))
        for match in metric_assignments
    ]
    for pattern in (
        _COUNT_VALUE_PATTERN,
        _WORD_COUNT_PATTERN,
        _DOZEN_COUNT_PATTERN,
        _TIMES_COUNT_PATTERN,
    ):
        measurement_spans.extend(
            (match.start(), match.end(), match.group(0))
            for match in pattern.finditer(claim_text or "")
        )
    for pattern in _UNIT_FREE_ROW_COUNT_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            measurement_spans.extend(
                (
                    match.start(group_name),
                    match.end(group_name),
                    match.group(group_name),
                )
                for group_name in ("first", "second")
            )
    for _field, pattern in _NATURAL_METRIC_PATTERNS:
        measurement_spans.extend(
            (match.start(), match.end(), match.group(0))
            for match in pattern.finditer(
                _prose_outside_examples(claim_text)
            )
        )
    measurement_spans.extend(
        (match.start(), match.end(), match.group(0))
        for pattern in (
            _ORDINAL_RANK_PATTERN,
            _PREDICATIVE_ORDINAL_RANK_PATTERN,
            _COPULATIVE_ORDINAL_RANK_PATTERN,
            _ORDERED_LIST_ENTRY_RANK_PATTERN,
            _LIST_ENTRY_IN_RANKING_PATTERN,
            _PRECEDING_ENTRIES_RANK_PATTERN,
            _WORD_RANK_PATTERN,
            *_RANK_ONE_PATTERNS,
        )
        for match in pattern.finditer(_prose_outside_examples(claim_text))
    )
    measurement_spans = sorted(set(measurement_spans))
    elliptical_spans = [
        match.span()
        for pattern in (
            _ELLIPTICAL_COUNT_COMPARISON_PATTERN,
            _POSTPOSED_ELLIPTICAL_COUNT_PATTERN,
            *_UNIT_FREE_ROW_COUNT_PATTERNS,
        )
        for match in pattern.finditer(claim_text or "")
    ]
    if (
        elliptical_spans
        and not _unsupported_elliptical_count_bindings(
            claim_text,
            facts,
        )
        and not _unsupported_postposed_count_bindings(
            claim_text,
            facts,
        )
        and not _unsupported_unit_free_row_counts(
            claim_text,
            facts,
        )
        and all(
            any(
                elliptical_start <= measurement_start
                and measurement_end <= elliptical_end
                for elliptical_start, elliptical_end in elliptical_spans
            )
            for measurement_start, measurement_end, _text
            in measurement_spans
        )
    ):
        return True
    if not measurement_spans:
        return True

    label_mentions = _row_binding_mentions(
        claim_text,
        facts,
        measurement_spans,
    )
    if label_mentions:
        def supported_by_one_fact(
            field: str,
            value: str,
            fragment: str,
        ) -> bool:
            row_assignment_text = "; ".join(
                match.group(0)
                for match in _FIELD_ASSIGNMENT_PATTERN.finditer(fragment)
                if _canonical_field_name(match.group(1))
                in _ROW_SCOPED_FIELD_NAMES
            )
            analytical_fragment = _prose_outside_examples(fragment)
            return any(
                value in _source_values_for_field(
                    field,
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                and not _unsupported_field_assignments(
                    row_assignment_text,
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                and not _unsupported_slash_separated_row_field_bindings(
                    fragment,
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                and not _unsupported_count_bindings(
                    analytical_fragment,
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                and not _unsupported_natural_metric_bindings(
                    analytical_fragment,
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                for fact in facts
            )

        prefixed_row_segments: List[tuple[str, str, str]] = []
        for start, end, field, value in label_mentions:
            boundary = max(
                claim_text.rfind(separator, 0, start)
                for separator in (",", ";", ".", "!", "?")
            ) + 1
            preceding = [
                span
                for span in measurement_spans
                if span[0] >= boundary and span[1] <= start
            ]
            if not preceding:
                break
            metric_start, metric_end, _measurement = preceding[-1]
            connector = claim_text[metric_end:start]
            if re.search(
                r"\b(?:(?:entfallen|fallen)\s+)?(?:auf|für|fuer)\s*$",
                connector,
                re.IGNORECASE,
            ) is None:
                break
            prefixed_row_segments.append(
                (field, value, claim_text[metric_start:end])
            )
        if len(prefixed_row_segments) == len(label_mentions):
            return all(
                supported_by_one_fact(field, value, fragment)
                for field, value, fragment in prefixed_row_segments
            )

        # Coordinated forms such as "Haus und Katze: f=12 bzw. f=2"
        # bind labels and measurements in textual order.
        if (
            len(label_mentions) == len(measurement_spans)
            and re.search(
                r"\b(?:bzw\.?|respektive|jeweils)\b",
                claim_text,
                re.IGNORECASE,
            )
        ):
            return all(
                supported_by_one_fact(
                    field,
                    value,
                    measurement,
                )
                for (_start, _end, field, value), (
                    _metric_start,
                    _metric_end,
                    measurement,
                ) in zip(label_mentions, measurement_spans)
            )

        # A prose claim may report several rows, but each label and the metrics
        # attached to it must resolve to one atomic fact. Segmenting at the next
        # visible row label admits honest multi-row summaries while rejecting
        # ``Haus hat f=2`` when 2 belongs to a different row.
        for index, (start, _end, field, value) in enumerate(label_mentions):
            segment_start = 0 if len(label_mentions) == 1 else start
            segment_end = (
                len(claim_text)
                if index + 1 == len(label_mentions)
                else label_mentions[index + 1][0]
            )
            segment = claim_text[segment_start:segment_end]
            if not any(
                metric_start >= segment_start
                and metric_start < segment_end
                for metric_start, _metric_end, _measurement
                in measurement_spans
            ):
                continue
            if not supported_by_one_fact(field, value, segment):
                return False
        return True

    if len(assignments) < 2:
        return True
    return any(
        not _unsupported_field_assignments(
            claim_text,
            _joined_surface_text([fact.statement, *fact.grounding_quotes]),
        )
        for fact in facts
    )


_WORD_PERCENT_PATTERN = re.compile(
    rf"\b({_NUMBER_WORD_TOKEN_SOURCE})\s*prozent(?:ig\w*)?\b",
    re.IGNORECASE,
)
_NATURAL_PERCENT_VALUE_PATTERN = re.compile(
    rf"\b(?:anteil|abdeckung|coverage(?:[_ -]?ratio)?|quote)\b"
    rf"[^\n.!?]{{0,32}}?\b(?:beträgt|betraegt|liegt\s+bei|ist|von)\s*"
    rf"(?P<value>{_NUMBER_PATTERN.pattern})",
    re.IGNORECASE,
)
_LOG_RATIO_LABEL_PATTERN = (
    r"(?:log[- ]?ratio(?:[- ]?wert)?|lr(?:[- ]?wert)?|"
    r"logarithmisch(?:e|en|er|es)?\s+(?:verhältnis|quotient))"
)
_RATE_VALUE_PATTERN = re.compile(
    rf"(?<![\w.,])(?P<value>{_NUMBER_TOKEN_SOURCE})\s*"
    r"(?:(?:treffer(?:n)?|fundstellen?|belege?|vorkommen|tokens?)\s+)?"
    r"(?:(?:pro|per|je)\s+million(?:\s+(?:tokens?|wörter?|woerter?))?|"
    r"pmw)\b",
    re.IGNORECASE,
)
_NATURAL_METRIC_PATTERNS = (
    (
        "f",
        re.compile(
            rf"\bf[- ]?wert\b[^\n.!?]{{0,24}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|lautet|ist|von|=|:)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "f",
        re.compile(
            rf"\bf[- ]?wert\b\s*(?:=|:)?\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "log_ratio",
        re.compile(
            rf"\b{_LOG_RATIO_LABEL_PATTERN}\b"
            rf"[^\n.!?]{{0,48}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|ist)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "log_ratio",
        re.compile(
            rf"\b{_LOG_RATIO_LABEL_PATTERN}\b\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "log_ratio",
        re.compile(
            rf"\b{_LOG_RATIO_LABEL_PATTERN}\b\s*(?:=|:)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "pos",
        re.compile(
            rf"\b(?:token|korpus|treffer)[- ]?position\b\s*"
            rf"(?:(?:beträgt|betraegt|ist|liegt\s+bei|=|:)\s*)?"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "rank",
        re.compile(
            rf"\b(?:rang|platz)\b\s*"
            rf"(?:(?:beträgt|betraegt|ist|liegt\s+bei|=|:)\s*)?"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "position",
        re.compile(
            rf"(?<!token-)(?<!token )(?<!korpus-)(?<!korpus )"
            rf"(?<!treffer-)(?<!treffer )\bposition\b\s*"
            rf"(?:(?:beträgt|betraegt|ist|liegt\s+bei|=|:)\s*)?"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "per_million",
        _RATE_VALUE_PATTERN,
    ),
    (
        "p_value",
        re.compile(
            rf"\b(?:p[- ]?wert|irrtumswahrscheinlichkeit)\b"
            rf"[^\n.!?]{{0,32}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|ist|von)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "standard_deviation",
        re.compile(
            rf"\b(?:standardabweichung|standarddeviation|stddev)\b"
            rf"[^\n.!?]{{0,32}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|ist|von)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "standard_error",
        re.compile(
            rf"\b(?:standardfehler|standarderror)\b"
            rf"[^\n.!?]{{0,32}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|ist|von)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
    (
        "median",
        re.compile(
            rf"\bmedian\b[^\n.!?]{{0,32}}?"
            rf"(?:beträgt|betraegt|liegt\s+bei|ist|von)\s*"
            rf"(?P<value>{_NUMBER_PATTERN.pattern})",
            re.IGNORECASE,
        ),
    ),
)
_ORDINAL_RANK_STEMS = {
    "erst": "1",
    "zweit": "2",
    "dritt": "3",
    "viert": "4",
    "fünft": "5",
    "fuenft": "5",
    "sechst": "6",
    "siebt": "7",
    "acht": "8",
    "neunt": "9",
    "zehnt": "10",
    "elft": "11",
    "zwölft": "12",
    "zwoelft": "12",
    "dreizehnt": "13",
    "vierzehnt": "14",
    "fünfzehnt": "15",
    "fuenfzehnt": "15",
    "sechzehnt": "16",
    "siebzehnt": "17",
    "achtzehnt": "18",
    "neunzehnt": "19",
    "zwanzigst": "20",
}
_ORDINAL_RANK_STEM_SOURCE = "|".join(
    sorted(
        (re.escape(stem) for stem in _ORDINAL_RANK_STEMS),
        key=len,
        reverse=True,
    )
)
_ORDINAL_RANK_PATTERN = re.compile(
    r"\b(" + _ORDINAL_RANK_STEM_SOURCE
    + r")(?:e|en|er|em|es)\s+(?:rang|platz|stelle)\b",
    re.IGNORECASE,
)
_PREDICATIVE_ORDINAL_RANK_PATTERN = re.compile(
    r"\brangier\w*\s+(?:als|auf\s+(?:dem\s+)?)\s+("
    + _ORDINAL_RANK_STEM_SOURCE
    + r")(?:e|en|er|em|es)\b",
    re.IGNORECASE,
)
_COPULATIVE_ORDINAL_RANK_PATTERN = re.compile(
    r"\b(?:ist|bleibt)\s+("
    + _ORDINAL_RANK_STEM_SOURCE
    + r")(?:e|en|er|em|es)\s+(?:in|auf)\s+"
    r"(?:(?:der|einer)\s+)?(?:frequenz|rang|ergebnis)"
    r"(?:liste|ranking)\b",
    re.IGNORECASE,
)
_ORDERED_LIST_ENTRY_RANK_PATTERN = re.compile(
    r"\b(?:frequenzliste|rangliste|ergebnisliste|"
    r"nach\s+(?:der\s+)?frequenz\s+geordnet\w*\s+liste)\b"
    r"[^.!?\n]{0,140}\b("
    + _ORDINAL_RANK_STEM_SOURCE
    + r")(?:e|en|er|em|es)\s+eintrag\b",
    re.IGNORECASE,
)
_LIST_ENTRY_IN_RANKING_PATTERN = re.compile(
    r"\b("
    + _ORDINAL_RANK_STEM_SOURCE
    + r")(?:e|en|er|em|es)\s+eintrag\b"
    r"[^.!?\n]{0,100}\b(?:in|auf)\s+(?:der|einer)\s+"
    r"(?:frequenzliste|rangliste|ergebnisliste)\b",
    re.IGNORECASE,
)
_PRECEDING_ENTRIES_RANK_PATTERN = re.compile(
    r"\bvor\b[^.!?\n]{1,100}\b(?:steh\w*|befinden\s+sich)\b"
    r"[^.!?\n]{0,80}\b(?P<number>"
    + _NUMBER_WORD_TOKEN_SOURCE
    + r"|\d+)\s+eintr(?:ag|äge|aege|ägen|aegen)\b",
    re.IGNORECASE,
)
_WORD_RANK_PATTERN = re.compile(
    rf"\b(?:rang|platz|position|stelle)\b\s*(?:ist|=|:)?\s*"
    rf"(?P<number>{_NUMBER_WORD_TOKEN_SOURCE})\b",
    re.IGNORECASE,
)
_RANK_ONE_PATTERNS = (
    re.compile(
        r"\b(?:spitzenreiter|listenführer|listenfuehrer|"
        r"ranglistenführer|ranglistenfuehrer)\b"
        r"[^.!?\n]{0,80}\b(?:frequenzliste|rangliste|ranking)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:führt|fuehrt)\b[^.!?\n]{0,80}\b"
        r"(?:frequenzliste|rangliste|ranking)\s+an\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:steht|liegt)\s+an\s+der\s+spitze\b"
        r"[^.!?\n]{0,80}\b(?:frequenzliste|rangliste|ranking)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:belegt|hält|haelt|hat)\s+(?:den\s+)?"
        r"(?:obersten|höchsten|hoechsten|führenden|fuehrenden)\s+"
        r"(?:listenplatz|rang|platz|position)\b",
        re.IGNORECASE,
    ),
)
_METRIC_MAXIMUM_PATTERN = re.compile(
    r"\b(?P<degree>höchst\w*|hoechst\w*|größt\w*|groesst\w*|"
    r"maximal\w*)\s+"
    r"(?P<metric>log[- ]?dice|mi3?|mutual\s+information|"
    r"t[- ]?score|log[- ]?likelihood|ll|dice|lmi|npmi|"
    r"chi(?:-?quadrat|2(?:_cell)?)|z[- ]?score|"
    r"delta[_ -]?p[_ -]?(?:nc|cn)|score)"
    r"(?:[- ]?wert\w*)?\b",
    re.IGNORECASE,
)
_NAMED_METRIC_RANGE_PATTERN = re.compile(
    rf"\b(?P<metric>log[- ]?dice|mi3?|mutual\s+information|"
    rf"t[- ]?score|log[- ]?likelihood|ll|dice|lmi|npmi|"
    rf"chi(?:-?quadrat|2(?:_cell)?)|z[- ]?score|"
    rf"delta[_ -]?p[_ -]?(?:nc|cn)|score)\b"
    rf"[^.!?\n]{{0,64}}\bzwischen\s+(?:etwa|ca\.?|circa)?\s*"
    rf"(?P<low>{_NUMBER_PATTERN.pattern})\s+"
    rf"(?:und|bis)\s+(?:etwa|ca\.?|circa)?\s*"
    rf"(?P<high>{_NUMBER_PATTERN.pattern})",
    re.IGNORECASE,
)
_RESULT_WIDE_METRIC_RANGE_PATTERN = re.compile(
    r"\b(?:liste|output|ergebnis|sämtlich\w*|saemtlich\w*|alle\w*|"
    r"beobachtet\w*\s+wert\w*|sichtbar\w*\s+wert\w*)\b",
    re.IGNORECASE,
)
_FRACTION_PERCENT_VALUES = {
    "hälfte": "50",
    "haelfte": "50",
    "drittel": "33.3333333333",
    "viertel": "25",
    "fünftel": "20",
    "fuenftel": "20",
    "sechstel": "16.6666666667",
    "siebtel": "14.2857142857",
    "achtel": "12.5",
    "neuntel": "11.1111111111",
    "zehntel": "10",
    "zwanzigstel": "5",
    "hundertstel": "1",
}
_FRACTION_RATIOS = {
    "hälfte": (1, 2),
    "haelfte": (1, 2),
    "drittel": (1, 3),
    "viertel": (1, 4),
    "fünftel": (1, 5),
    "fuenftel": (1, 5),
    "sechstel": (1, 6),
    "siebtel": (1, 7),
    "achtel": (1, 8),
    "neuntel": (1, 9),
    "zehntel": (1, 10),
    "zwanzigstel": (1, 20),
    "hundertstel": (1, 100),
}
_DISTRIBUTIVE_FRACTION_RATIOS = {
    "zweit": (1, 2),
    "dritt": (1, 3),
    "viert": (1, 4),
    "fünft": (1, 5),
    "fuenft": (1, 5),
    "sechst": (1, 6),
    "siebt": (1, 7),
    "acht": (1, 8),
    "neunt": (1, 9),
    "zehnt": (1, 10),
}
_FRACTION_PERCENT_PATTERN = re.compile(
    r"\b(?:ein(?:e|en|em|er|es)?\s+)?("
    + "|".join(
        sorted(
            (re.escape(word) for word in _FRACTION_PERCENT_VALUES),
            key=len,
            reverse=True,
        )
    )
    + r")\b",
    re.IGNORECASE,
)
_DISTRIBUTIVE_FRACTION_PATTERN = re.compile(
    r"\b(?:jeder|jede|jedes)\s+("
    + "|".join(
        sorted(
            (
                re.escape(stem)
                for stem in _DISTRIBUTIVE_FRACTION_RATIOS
            ),
            key=len,
            reverse=True,
        )
    )
    + r")(?:e|en|er|es)\s+"
    r"(?:treffer|fundstelle|beleg|vorkommen)\w*\b",
    re.IGNORECASE,
)
_TIMES_COUNT_PATTERN = re.compile(
    r"(?:"
    r"\b(?:kommt|tritt|erscheint|findet\s+sich)\b[^.!?\n]{0,32}\b"
    r"(?P<word_before>"
    + _NUMBER_WORD_TOKEN_SOURCE
    + r"|\d+)\s*-?mal\b"
    r"|"
    r"\b(?P<word_after>"
    + _NUMBER_WORD_TOKEN_SOURCE
    + r"|\d+)\s*-?mal\b[^.!?\n]{0,24}\b"
    r"(?:vor|belegt|gezählt|gezaehlt|gefunden)\b"
    r")",
    re.IGNORECASE,
)
_RATIO_COMPARISON_PATTERN = re.compile(
    rf"\b(?P<factor>{_NUMBER_WORD_TOKEN_SOURCE}|\d+(?:[.,]\d+)?)"
    r"(?:"
    r"\s*-?mal\s+so\s+(?:häufig|haeufig|oft)\s+(?:wie|als)\b"
    r"|"
    r"\s*[- ]?fache\b(?:\s+der\s+(?:frequenz|häufigkeit|haeufigkeit)\s+von)?"
    r")",
    re.IGNORECASE,
)
_NAMED_FREQUENCY_FACTOR_PATTERN = re.compile(
    rf"\bfrequenzfaktor\s+(?:von|=|:)\s*"
    rf"(?P<factor>{_NUMBER_WORD_TOKEN_SOURCE}|\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
_RATIO_BINDING_PATTERNS = (
    _RATIO_COMPARISON_PATTERN,
    _NAMED_FREQUENCY_FACTOR_PATTERN,
)
_EXPLICIT_COUNT_PERCENT_PATTERN = re.compile(
    rf"(?<![\w.,])(?P<numerator>{_NUMBER_TOKEN_SOURCE})\s+"
    r"(?:von|of|out\s+of)\s+"
    rf"(?P<denominator>{_NUMBER_TOKEN_SOURCE})\s+"
    r"(?:treffer(?:n)?|fundstellen?|belege?|vorkommen|hits?|matches)\b"
    r"[^.!?\n]{0,48}?"
    rf"(?P<percent>{_NUMBER_TOKEN_SOURCE})\s*(?:%|prozent\b)",
    re.IGNORECASE,
)
_EXPLICIT_SLASH_PERCENT_PATTERN = re.compile(
    rf"(?<![\w.,])(?P<numerator>{_NUMBER_TOKEN_SOURCE})\s*/\s*"
    rf"(?P<denominator>{_NUMBER_TOKEN_SOURCE})"
    r"(?:\s+(?:treffer(?:n)?|fundstellen?|belege?|vorkommen|hits?|matches))?"
    r"[^.!?\n]{0,48}?"
    rf"(?P<percent>{_NUMBER_TOKEN_SOURCE})\s*(?:%|prozent\b)",
    re.IGNORECASE,
)
_EXPLICIT_POSTPOSED_PERCENT_PATTERN = re.compile(
    rf"(?P<percent>{_NUMBER_TOKEN_SOURCE})\s*(?:%|prozent\b)"
    r"[^.!?\n]{0,32}?\(\s*"
    rf"(?P<numerator>{_NUMBER_TOKEN_SOURCE})\s*"
    r"(?:/|von|of|out\s+of)\s*"
    rf"(?P<denominator>{_NUMBER_TOKEN_SOURCE})\s*\)",
    re.IGNORECASE,
)
_EXPLICIT_COUNT_PERCENT_PATTERNS = (
    _EXPLICIT_COUNT_PERCENT_PATTERN,
    _EXPLICIT_SLASH_PERCENT_PATTERN,
    _EXPLICIT_POSTPOSED_PERCENT_PATTERN,
)
_ELLIPTICAL_COUNT_COMPARISON_PATTERN = re.compile(
    rf"\b(?P<left>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
    r"(?:im\s+vergleich\s+zu|gegenüber|gegenueber)\s+"
    rf"(?P<right>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
    r"(?:treffer(?:n)?|belege?|vorkommen)\b",
    re.IGNORECASE,
)
_POSTPOSED_ELLIPTICAL_COUNT_PATTERN = re.compile(
    rf"\b(?P<first>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
    r"(?:treffer(?:n)?|belege?|vorkommen)\s+"
    r"(?:entfallen|fallen)\s+auf\s+"
    r"(?P<first_label>[^,;.!?\n]{1,80}?)\s*,\s*"
    r"auf\s+(?P<second_label>[^,;.!?\n]{1,80}?)\s+"
    r"(?:dagegen|hingegen|demgegenüber|demgegenueber)\s+"
    rf"(?P<second>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\b",
    re.IGNORECASE,
)
_UNIT_FREE_ROW_COUNT_PATTERNS = (
    re.compile(
        r"\b(?:von\s+den\s+)?(?:treffern?|fundstellen?|belegen?|"
        r"vorkommen)\s+(?:entfallen|fallen)\s+auf\s+"
        r"(?P<first_label>[^,;.!?\n]{1,80}?)\s+"
        rf"(?P<first>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
        r"(?:und|sowie)\s+auf\s+"
        r"(?P<second_label>[^,;.!?\n]{1,80}?)\s+"
        rf"(?P<second>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:von\s+den\s+)?(?:treffern?|fundstellen?|belegen?|"
        r"vorkommen)\s+gehören\s+"
        rf"(?P<first>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+zu\s+"
        r"(?P<first_label>[^,;.!?\n]{1,80}?)\s+"
        r"(?:und|sowie)\s+"
        rf"(?P<second>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+zu\s+"
        r"(?P<second_label>[^,;.!?\n]{1,80}?)"
        r"(?=[,;.!?\n]|$)",
        re.IGNORECASE,
    ),
)
_RATE_DENOMINATOR_PATTERNS = (
    re.compile(
    r"\bauf\s+(?P<all>alle[nrsm]?\s+)?"
    rf"(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
    r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
    r"[- ]?tokens?\s+(?:bezogen|normalisiert)\b",
    re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
        r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
        r"[- ]?tokens?\s+(?:bilden|sind)\b"
        r"[^.!?\n]{0,60}\b(?:bezugsgröße|bezugsbasis|nenner)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:bilden|stellen)\s+"
        rf"(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
        r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
        r"[- ]?tokens?\s+(?:die|den)\s+"
        r"(?:bezugsgröße|bezugsbasis|nenner)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:bezugsgröße|bezugsbasis|nenner)\b"
        r"[^.!?\n]{0,48}?\b(?:von|sind|beträgt|betraegt)?\s*"
        rf"(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
        r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
        r"[- ]?tokens?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:berechnungsbasis|bezugsbasis|bezugsgröße|nenner)\b"
        r"[^.!?\n]{0,80}?\b(?:dienen|fungieren)\s+"
        rf"(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
        r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
        r"[- ]?tokens?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:normierung|normalisierung|rate)\b"
        r"[^.!?\n]{0,80}?\b(?:stützt|stuetzt)\s+sich\s+auf\s+"
        rf"(?P<tokens>{_NUMBER_TOKEN_SOURCE})\s+"
        r"(?P<scope>korpus|corpus|docset|subkorpus|teilkorpus)?"
        r"[- ]?tokens?\b",
        re.IGNORECASE,
    ),
)
_ROW_LABEL_FIELD_NAMES = frozenset(
    {"word", "kw", "lemma", "relation", "doc_id"}
)


def _count_fields_for_claim_fragment(fragment: str) -> frozenset[str]:
    lowered = str(fragment or "").casefold()
    if re.search(r"\b(?:per[_ -]?million|pro\s+million|normiert)\w*\b", lowered):
        return frozenset({"per_million"})
    if re.search(r"\b(?:mindest\w*|min_freq)\b", lowered):
        return frozenset({"min_freq"})
    if re.search(
        r"\b(?:insgesamt|gesamt(?:zahl|trefferzahl|häufigkeit|haeufigkeit)|"
        r"trefferzahl|(?:konkordanz|kwic)[- ]?instanz\w*)\b",
        lowered,
    ):
        return _TOTAL_HIT_COUNT_FIELD_NAMES
    if re.search(
        r"\b(?:konkordanz|kwic)[- ]?zeil\w*\b",
        lowered,
    ):
        return _RESULT_COUNT_FIELD_NAMES
    if re.search(
        r"\b(?:frequenz|häufigkeit|haeufigkeit|treffer|fundstell|vorkommen|"
        r"kommt|tritt|erscheint|gefunden)\w*\b",
        lowered,
    ):
        return _HIT_COUNT_FIELD_NAMES
    if re.search(r"\b(?:dokument|texte?)\w*\b", lowered):
        return _DOCUMENT_COUNT_FIELD_NAMES
    if re.search(
        r"\b(?:zeil|ergebnis|passag|beobachtung|wörter?|woerter?|"
        r"kollokat|eintr(?:ag|äg|aeg)|resultat)\w*\b",
        lowered,
    ):
        return _RESULT_COUNT_FIELD_NAMES
    if re.search(r"\b(?:cluster|gruppe|muster)\w*\b", lowered):
        return _CLUSTER_COUNT_FIELD_NAMES
    return _HIT_COUNT_FIELD_NAMES


def _field_numeric_values(
    source_surface: str,
    fields: Sequence[str],
) -> set[str]:
    values = {
        value
        for field in fields
        for value in _source_values_for_field(field, source_surface)
        if re.fullmatch(r"-?\d+(?:\.\d+)?", value)
    }
    if set(fields).intersection(_TOTAL_HIT_COUNT_FIELD_NAMES):
        natural_total_pattern = re.compile(
            rf"\b(?:insgesamt|gesamt(?:zahl|trefferzahl)?|"
            rf"treffer(?:zahl)?\s+gesamt)\b"
            rf"(?:\s*(?:=|:|beträgt|betraegt|sind))?\s*"
            rf"(?P<value>{_NUMBER_TOKEN_SOURCE})",
            re.IGNORECASE,
        )
        values.update(
            _normalize_number_token(
                match.group("value"),
                integer_grouping=True,
            )
            for match in natural_total_pattern.finditer(source_surface or "")
        )
    return values


def _dozen_count_value(match: re.Match[str]) -> str | None:
    raw_multiplier = str(match.group("multiplier") or "ein").casefold()
    fractional_multiplier = {
        "halb": (1, 2),
        "halbe": (1, 2),
        "halben": (1, 2),
        "halber": (1, 2),
        "halbes": (1, 2),
        "halbem": (1, 2),
        "anderthalb": (3, 2),
        "eineinhalb": (3, 2),
    }.get(raw_multiplier)
    if fractional_multiplier is not None:
        numerator, denominator = fractional_multiplier
        scaled = numerator * 12
        if scaled % denominator:
            return None
        value = scaled // denominator
        return str(value) if 0 <= value <= 999_999 else None
    if raw_multiplier.startswith("ein"):
        multiplier = "1"
    elif raw_multiplier.isdigit():
        multiplier = raw_multiplier
    else:
        multiplier = _number_word_value(raw_multiplier)
    if multiplier is None:
        return None
    value = int(multiplier) * 12
    return str(value) if 0 <= value <= 999_999 else None


def _unsupported_count_bindings(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    unsupported: List[str] = []
    derived_rank_count_spans = [
        match.span("number")
        for match in _PRECEDING_ENTRIES_RANK_PATTERN.finditer(
            claim_text or ""
        )
    ]

    def is_derived_rank_count(start: int, end: int) -> bool:
        return any(
            owner_start <= start and end <= owner_end
            for owner_start, owner_end in derived_rank_count_spans
        )

    ratio_factor_spans = [
        match.span("factor")
        for pattern in _RATIO_BINDING_PATTERNS
        for match in pattern.finditer(claim_text or "")
    ]
    for match in _COUNT_VALUE_PATTERN.finditer(claim_text or ""):
        group_name = (
            "value_before"
            if match.group("value_before") is not None
            else "value_after"
        )
        raw_value = match.group(group_name)
        value_start, value_end = match.span(group_name)
        if is_derived_rank_count(value_start, value_end):
            # "Vor X steht ein Eintrag" expresses rank=2, not f=1.
            # _unsupported_natural_metric_bindings validates that arithmetic.
            continue
        if any(
            start <= value_start and value_end <= end
            for start, end in ratio_factor_spans
        ):
            # A validated ratio owns this derived number. Its dedicated row
            # binding below decides whether the arithmetic is correct.
            continue
        value = _normalize_number_token(raw_value, integer_grouping=True)
        following = str(claim_text or "")[match.end() : match.end() + 32]
        if re.search(
            r"\b(?:per[_ -]?million|pro\s+million)\b",
            following,
            re.IGNORECASE,
        ):
            # Natural phrasing such as "normierte Häufigkeit von 569,5 pro
            # Million" contains the generic noun Häufigkeit, but the adjacent
            # unit makes this a rate. The dedicated metric binding validates it.
            continue
        # Bind the number to the noun phrase that owns it. A broad character
        # window can leak a neighbouring metric across a semicolon or an
        # ``und`` coordination (for example frequency=12 followed by
        # per_million=12000, or row_limit=8 followed by min_freq=3).
        field_context = match.group(0)
        count_fields = _count_fields_for_claim_fragment(field_context)
        allowed = _field_numeric_values(source_surface, count_fields)
        if (
            allowed
            and not _numeric_token_is_supported(value, allowed)
        ) or (
            not allowed
            and count_fields != _HIT_COUNT_FIELD_NAMES
        ):
            unsupported.append(value)
    for match in _WORD_COUNT_PATTERN.finditer(claim_text or ""):
        if is_derived_rank_count(*match.span("number")):
            continue
        if _word_count_match_is_indefinite_article(
            match,
            claim_text or "",
        ):
            # "ein Muster, das ..." is normally predicative, not a measured
            # cluster count. "genau ein Muster" remains numeric.
            continue
        value = _number_word_value(match.group("number"))
        if not value:
            continue
        context = match.group(0)
        count_fields = _count_fields_for_claim_fragment(context)
        allowed = _field_numeric_values(source_surface, count_fields)
        if (
            allowed
            and value not in allowed
        ) or (
            not allowed
            and count_fields != _HIT_COUNT_FIELD_NAMES
        ):
            unsupported.append(value)
    for match in _WORD_RESULT_COUNT_PATTERN.finditer(claim_text or ""):
        if is_derived_rank_count(*match.span("number")):
            continue
        value = _number_word_value(match.group("number"))
        if value is None:
            continue
        allowed = _field_numeric_values(
            source_surface,
            _RESULT_COUNT_FIELD_NAMES,
        )
        if not allowed or value not in allowed:
            unsupported.append(value)
    for match in _DIGIT_RESULT_COUNT_PATTERN.finditer(claim_text or ""):
        if is_derived_rank_count(*match.span("number")):
            continue
        value = _normalize_number_token(
            match.group("number"),
            integer_grouping=True,
        )
        allowed = _field_numeric_values(
            source_surface,
            _RESULT_COUNT_FIELD_NAMES,
        )
        if not allowed or value not in allowed:
            unsupported.append(value)
    for match in _DOZEN_COUNT_PATTERN.finditer(claim_text or ""):
        value = _dozen_count_value(match)
        if value is None:
            continue
        count_fields = _count_fields_for_claim_fragment(match.group(0))
        allowed = _field_numeric_values(source_surface, count_fields)
        if (
            allowed
            and value not in allowed
        ) or (
            not allowed
            and count_fields != _HIT_COUNT_FIELD_NAMES
        ):
            unsupported.append(value)
    for match in _TIMES_COUNT_PATTERN.finditer(claim_text or ""):
        raw_value = match.group("word_before") or match.group("word_after")
        value = (
            _number_word_value(raw_value)
            if not raw_value.isdigit()
            else raw_value
        )
        allowed = _field_numeric_values(
            source_surface,
            _HIT_COUNT_FIELD_NAMES,
        )
        if value and allowed and value not in allowed:
            unsupported.append(value)
    return list(dict.fromkeys(unsupported))


def _row_count_for_label(
    label: str,
    facts: Sequence[ObservedFact],
) -> float | None:
    values: set[str] = set()
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        if not any(
            label in _source_values_for_field(field, surface)
            for field in _ROW_LABEL_FIELD_NAMES
        ):
            continue
        values.update(
            _field_numeric_values(
                surface,
                _HIT_COUNT_FIELD_NAMES,
            )
        )
    if len(values) != 1:
        return None
    try:
        return float(next(iter(values)))
    except (TypeError, ValueError):
        return None


def _displayed_scaled_quotient_matches(
    claimed_token: str,
    numerator: float,
    denominator: float,
    *,
    scale: float,
) -> bool:
    """Validate a displayed quotient at the precision the claim exposes."""

    if denominator <= 0:
        return False
    try:
        claimed = float(claimed_token)
    except (TypeError, ValueError):
        return False
    decimals = (
        len(claimed_token.rsplit(".", 1)[1])
        if "." in claimed_token
        else 0
    )
    tolerance = 0.5 * (10.0 ** -decimals) + 1e-12
    return abs(claimed - (numerator / denominator * scale)) <= tolerance


def _fact_provenance_surfaces(
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Return fact-local and same-source surfaces for safe derivations."""

    surfaces: List[str] = []
    by_source: Dict[str, List[str]] = {}
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        if surface:
            surfaces.append(surface)
        for source_id in fact.source_evidence_ids:
            if source_id:
                by_source.setdefault(str(source_id), []).append(surface)
    surfaces.extend(
        _joined_surface_text(group)
        for group in by_source.values()
        if group
    )
    return list(dict.fromkeys(surface for surface in surfaces if surface))


def _rate_token_is_supported(
    token: str,
    source_surfaces: Sequence[str],
) -> bool:
    """Accept an explicit rate, or derive it from one unambiguous provenance."""

    for source_surface in source_surfaces:
        direct_rates = _field_numeric_values(
            source_surface,
            ("per_million",),
        )
        if direct_rates:
            if _numeric_token_is_supported(token, direct_rates):
                return True
            # An explicit tool value is authoritative for this provenance.
            continue
        numerators = _field_numeric_values(
            source_surface,
            ("f", "freq", "frequency", "count", "total", "total_hits"),
        )
        denominators = _field_numeric_values(
            source_surface,
            ("denominator_tokens",),
        )
        if len(numerators) != 1 or len(denominators) != 1:
            continue
        try:
            numerator = float(next(iter(numerators)))
            denominator = float(next(iter(denominators)))
        except (TypeError, ValueError):
            continue
        if _displayed_scaled_quotient_matches(
            token,
            numerator,
            denominator,
            scale=1_000_000.0,
        ):
            return True
    return False


def _rate_binding_status(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> tuple[List[str], List[tuple[int, int]]]:
    unsupported: List[str] = []
    supported_value_spans: List[tuple[int, int]] = []
    source_surfaces = _fact_provenance_surfaces(facts)
    for match in _RATE_VALUE_PATTERN.finditer(claim_text or ""):
        token = _normalize_number_token(match.group("value"))
        if _rate_token_is_supported(token, source_surfaces):
            supported_value_spans.append(match.span("value"))
        else:
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported)), supported_value_spans


def _explicit_percent_binding_status(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> tuple[List[str], List[tuple[int, int]]]:
    """Bind written count-share operands before checking the result."""

    unsupported: List[str] = []
    supported_percent_spans: List[tuple[int, int]] = []
    source_surfaces = _fact_provenance_surfaces(facts)
    parsed_expression_spans: List[tuple[int, int]] = []
    for pattern in _EXPLICIT_COUNT_PERCENT_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            parsed_expression_spans.append(match.span())
            claimed_numerator = _normalize_number_token(
                match.group("numerator"),
                integer_grouping=True,
            )
            claimed_denominator = _normalize_number_token(
                match.group("denominator"),
                integer_grouping=True,
            )
            claimed_percent = _normalize_number_token(match.group("percent"))
            supported = False
            for source_surface in source_surfaces:
                numerators = _field_numeric_values(
                    source_surface,
                    ("f", "freq", "frequency", "count"),
                )
                denominators = _field_numeric_values(
                    source_surface,
                    ("total", "total_hits", "anchor_count"),
                )
                if len(numerators) != 1 or len(denominators) != 1:
                    continue
                expected_numerator = next(iter(numerators))
                expected_denominator = next(iter(denominators))
                if (
                    claimed_numerator != expected_numerator
                    or claimed_denominator != expected_denominator
                ):
                    continue
                try:
                    numerator = float(expected_numerator)
                    denominator = float(expected_denominator)
                except (TypeError, ValueError):
                    continue
                direct_percents = _field_numeric_values(
                    source_surface,
                    _EXPLICIT_PERCENT_FIELD_NAMES,
                )
                if direct_percents and not _numeric_token_is_supported(
                    claimed_percent,
                    direct_percents,
                ):
                    continue
                if _displayed_scaled_quotient_matches(
                    claimed_percent,
                    numerator,
                    denominator,
                    scale=100.0,
                ):
                    supported = True
                    break
            if supported:
                supported_percent_spans.append(match.span("percent"))
            else:
                unsupported.append(match.group(0))

    # If a clause visibly presents count operands next to a percentage in an
    # unrecognised layout, independent number membership is not enough: 2/1 and
    # 1/2 use the same tokens but encode opposite arithmetic roles.
    for percent_match in _NUMERIC_PERCENT_PATTERN.finditer(claim_text or ""):
        if any(
            start <= percent_match.start() and percent_match.end() <= end
            for start, end in parsed_expression_spans
        ):
            continue
        clause_start = max(
            (claim_text or "").rfind(separator, 0, percent_match.start())
            for separator in (".", "!", "?", "\n", ";")
        ) + 1
        following_boundaries = [
            position
            for separator in (".", "!", "?", "\n", ";")
            for position in [(claim_text or "").find(separator, percent_match.end())]
            if position >= 0
        ]
        clause_end = min(following_boundaries) if following_boundaries else len(claim_text or "")
        clause = (claim_text or "")[clause_start:clause_end]
        other_numbers = [
            token
            for token in _NUMBER_PATTERN.finditer(clause)
            if not (
                token.start() + clause_start >= percent_match.start()
                and token.end() + clause_start <= percent_match.end()
            )
        ]
        if len(other_numbers) >= 2 and re.search(
            r"/|=|\b(?:von|of|out\s+of)\b",
            clause,
            re.IGNORECASE,
        ):
            unsupported.append(_compact_text(clause, 180))
    return list(dict.fromkeys(unsupported)), supported_percent_spans


def _ratio_comparison_binding_status(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> tuple[List[str], List[tuple[int, int]]]:
    unsupported: List[str] = []
    supported_factor_spans: List[tuple[int, int]] = []
    label_mentions = _row_label_mentions(claim_text, facts)

    for pattern in _RATIO_BINDING_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            left_mentions = [
                mention
                for mention in label_mentions
                if mention[1] <= match.start()
            ]
            right_mentions = [
                mention
                for mention in label_mentions
                if mention[0] >= match.end()
            ]
            if (
                pattern is _NAMED_FREQUENCY_FACTOR_PATTERN
                and not right_mentions
                and len(left_mentions) >= 2
            ):
                left_mention = left_mentions[-2]
                right_mention = left_mentions[-1]
            elif left_mentions and right_mentions:
                left_mention = left_mentions[-1]
                right_mention = right_mentions[0]
            else:
                unsupported.append(match.group(0))
                continue
            left = _row_count_for_label(left_mention[3], facts)
            right = _row_count_for_label(right_mention[3], facts)
            raw_factor = match.group("factor")
            factor_token = (
                _normalize_number_token(raw_factor)
                if re.fullmatch(r"\d+(?:[.,]\d+)?", raw_factor)
                else _number_word_value(raw_factor)
            )
            if (
                left is None
                or right in {None, 0.0}
                or factor_token is None
            ):
                unsupported.append(match.group(0))
                continue
            claimed = float(factor_token)
            decimals = (
                len(factor_token.rsplit(".", 1)[1])
                if "." in factor_token
                else 0
            )
            tolerance = (
                0.5 * (10.0 ** -decimals)
                if decimals
                else 1e-9
            )
            if abs(claimed - (left / right)) > tolerance:
                unsupported.append(match.group(0))
                continue
            supported_factor_spans.append(match.span("factor"))
    return list(dict.fromkeys(unsupported)), supported_factor_spans


def _unsupported_elliptical_count_bindings(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    unsupported: List[str] = []
    label_mentions = _row_label_mentions(claim_text, facts)

    for match in _ELLIPTICAL_COUNT_COMPARISON_PATTERN.finditer(
        claim_text or ""
    ):
        left_mentions = [
            mention
            for mention in label_mentions
            if mention[1] <= match.start("left")
        ]
        right_mentions = [
            mention
            for mention in label_mentions
            if mention[0] >= match.end("right")
        ]
        if not left_mentions or not right_mentions:
            unsupported.append(match.group(0))
            continue
        expected_left = _row_count_for_label(
            left_mentions[-1][3],
            facts,
        )
        expected_right = _row_count_for_label(
            right_mentions[0][3],
            facts,
        )
        claimed_left = _count_token_value(match.group("left"))
        claimed_right = _count_token_value(match.group("right"))
        # The broad token pattern also sees the unit in phrases such as
        # "9 Treffern gegenüber 61 Treffern" as a possible number word.
        # Ignore that lexical overlap; only actual numeric tokens define a
        # count comparison.
        if claimed_left is None or claimed_right is None:
            continue
        if (
            expected_left is None
            or expected_right is None
            or claimed_left != expected_left
            or claimed_right != expected_right
        ):
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _count_token_value(raw: str) -> float | None:
    token = (
        _normalize_number_token(raw)
        if raw.isdigit()
        else _number_word_value(raw)
    )
    try:
        return float(token) if token is not None else None
    except (TypeError, ValueError):
        return None


def _unsupported_named_count_pair_bindings(
    claim_text: str,
    facts: Sequence[ObservedFact],
    pattern: re.Pattern[str],
) -> List[str]:
    unsupported: List[str] = []
    label_mentions = _row_label_mentions(claim_text, facts)
    for match in pattern.finditer(claim_text or ""):
        first_mentions = [
            mention
            for mention in label_mentions
            if match.start("first_label") <= mention[0]
            and mention[1] <= match.end("first_label")
        ]
        second_mentions = [
            mention
            for mention in label_mentions
            if match.start("second_label") <= mention[0]
            and mention[1] <= match.end("second_label")
        ]
        if len(first_mentions) != 1 or len(second_mentions) != 1:
            unsupported.append(match.group(0))
            continue
        expected_first = _row_count_for_label(
            first_mentions[0][3],
            facts,
        )
        expected_second = _row_count_for_label(
            second_mentions[0][3],
            facts,
        )
        if (
            expected_first is None
            or expected_second is None
            or _count_token_value(match.group("first")) != expected_first
            or _count_token_value(match.group("second")) != expected_second
        ):
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _unsupported_postposed_count_bindings(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    return _unsupported_named_count_pair_bindings(
        claim_text,
        facts,
        _POSTPOSED_ELLIPTICAL_COUNT_PATTERN,
    )


def _unsupported_unit_free_row_counts(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    return list(
        dict.fromkeys(
            unsupported
            for pattern in _UNIT_FREE_ROW_COUNT_PATTERNS
            for unsupported in _unsupported_named_count_pair_bindings(
                claim_text,
                facts,
                pattern,
            )
        )
    )


def _single_fact_numeric_value(
    fact: ObservedFact,
    fields: Sequence[str],
) -> float | None:
    surface = _joined_surface_text(
        [fact.statement, *fact.grounding_quotes]
    )
    for field in fields:
        values = _source_values_for_field(field, surface)
        if len(values) != 1:
            continue
        try:
            return float(next(iter(values)))
        except (TypeError, ValueError):
            continue
    return None


def _normalised_time_trend_status(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool | None:
    """Validate a stated time change against count/denominator pairs."""

    if _RELATIVE_FREQUENCY_PATTERN.search(claim_text or "") is None:
        return None
    time_match = _TIME_COMPARISON_PATTERN.search(claim_text or "")
    change_match = _TIME_CHANGE_PATTERN.search(claim_text or "")
    if time_match is None or change_match is None:
        return None
    rates_by_year = _normalised_rates_by_year(facts)
    start_rates = rates_by_year.get(
        int(time_match.group("start_year")),
        [],
    )
    end_rates = rates_by_year.get(int(time_match.group("end_year")), [])
    if len(start_rates) != 1 or len(end_rates) != 1 or start_rates[0] == 0:
        return False
    return _time_change_matches_ratio(
        change_match.group("change"),
        end_rates[0] / start_rates[0],
    )


def _normalised_rates_by_year(
    facts: Sequence[ObservedFact],
) -> Dict[int, List[float]]:
    rates_by_year: Dict[int, List[float]] = {}
    for fact in facts:
        year = _single_fact_numeric_value(fact, ("year",))
        count = _single_fact_numeric_value(
            fact,
            ("f", "total", "frequency", "count"),
        )
        denominator = _single_fact_numeric_value(
            fact,
            ("denominator_tokens", "corpus_tokens"),
        )
        if (
            year is None
            or count is None
            or denominator is None
            or denominator <= 0
            or not year.is_integer()
        ):
            continue
        rates_by_year.setdefault(int(year), []).append(count / denominator)
    return rates_by_year


def _time_change_matches_ratio(change_text: str, ratio: float) -> bool:
    change = change_text.casefold()
    if change.startswith("verdoppel"):
        return abs(ratio - 2.0) <= 1e-9
    if change.startswith("halbier"):
        return abs(ratio - 0.5) <= 1e-9
    if (
        change.startswith(("gestieg", "zugenomm", "höher", "hoeher"))
    ):
        return ratio > 1.0
    if change.startswith(("gesunk", "gefall", "niedriger")):
        return ratio < 1.0
    if change.startswith("gleich"):
        return abs(ratio - 1.0) <= 1e-9
    return False


def _generic_time_trend_status(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool | None:
    match = _GENERIC_TIME_TREND_PATTERN.search(claim_text or "")
    if match is None:
        return None
    rates_by_year = _normalised_rates_by_year(facts)
    years = sorted(rates_by_year)
    if (
        len(years) < 2
        or len(rates_by_year[years[0]]) != 1
        or len(rates_by_year[years[-1]]) != 1
        or rates_by_year[years[0]][0] == 0
    ):
        return False
    ratio = rates_by_year[years[-1]][0] / rates_by_year[years[0]][0]
    change = match.group("change").casefold()
    if (
        change.startswith(("nimmt", "steig", "wächst", "waechst"))
        and not re.search(r"\bnimmt\b[^.!?\n]{0,24}\bab\b", change)
    ):
        return ratio > 1.0
    return ratio < 1.0


def _unsupported_syntactic_role_claims(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    source_values = {
        value
        for field in (
            "syntactic_function",
            "relation",
            "dependency_relation",
            "dep",
        )
        for value in _source_values_for_field(field, source_surface)
    }
    unsupported: List[str] = []
    for role, pattern in _CATEGORICAL_SYNTACTIC_ROLE_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            nearby = str(claim_text or "")[
                max(0, match.start() - 40) : match.end()
            ]
            if re.search(
                r"\b(?:nicht|kein(?:e|en|er|es)?|weder|ohne)\b",
                nearby,
                re.IGNORECASE,
            ):
                continue
            if not source_values.intersection(
                _SYNTACTIC_ROLE_VALUE_ALIASES[role]
            ):
                unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _source_row_label_lookup(
    facts: Sequence[ObservedFact],
) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        for field in _ROW_LABEL_FIELD_NAMES:
            for value in _source_values_for_field(field, surface):
                labels.setdefault(value.casefold(), value)
    return labels


def _unsupported_presence_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    labels = _source_row_label_lookup(facts)
    unsupported: List[str] = []
    for match in _FACTUAL_LIST_PRESENCE_PATTERN.finditer(claim_text or ""):
        if match.group("label").casefold() not in labels:
            unsupported.append(match.group(0))
    for match in _NEGATIVE_PRESENCE_PATTERN.finditer(claim_text or ""):
        label = labels.get(match.group("label").casefold())
        count = _row_count_for_label(label, facts) if label else None
        if count != 0:
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _contains_literal_label(text: str, label: str) -> bool:
    if not label:
        return False
    return re.search(
        rf"(?<!\w){re.escape(label)}(?!\w)",
        text or "",
        re.IGNORECASE,
    ) is not None


def _unsupported_directional_scope_presence_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Check natural presence language against keyness target/reference counts."""

    unsupported: List[str] = []
    sentences = re.split(r"(?<=[.!?])\s+|\n+", claim_text or "")
    for fact in facts:
        if fact.fact_kind != "ranked_row":
            continue
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        row_labels = {
            value
            for field in _ROW_LABEL_FIELD_NAMES
            for value in _source_values_for_field(field, surface)
        }
        target_labels = _source_values_for_field("target", surface)
        reference_labels = _source_values_for_field("reference", surface)
        target_counts = _field_numeric_values(surface, ("target_freq",))
        reference_counts = _field_numeric_values(
            surface,
            ("reference_freq",),
        )
        if not (
            len(row_labels) == 1
            and len(target_labels) == 1
            and len(reference_labels) == 1
            and len(target_counts) == 1
            and len(reference_counts) == 1
        ):
            continue
        row_label = next(iter(row_labels))
        scoped_counts = (
            (next(iter(target_labels)), float(next(iter(target_counts)))),
            (
                next(iter(reference_labels)),
                float(next(iter(reference_counts))),
            ),
        )
        for sentence in sentences:
            if not _contains_literal_label(sentence, row_label):
                continue
            fragments = re.split(
                r"[,;]|\s+[–—]\s+|\bund\b(?=\s+(?:im|in|beim)\b)",
                sentence,
                flags=re.IGNORECASE,
            )
            for fragment in fragments:
                for scope_label, count in scoped_counts:
                    if not _contains_literal_label(fragment, scope_label):
                        continue
                    if (
                        _ROW_SCOPE_ABSENCE_PATTERN.search(fragment)
                        and count != 0
                    ) or (
                        _ROW_SCOPE_PRESENCE_PATTERN.search(fragment)
                        and count == 0
                    ):
                        unsupported.append(_compact_text(fragment, 180))
    return list(dict.fromkeys(unsupported))


# --------------------------------------------------------------------------- #
# K3 Slice 3: mechanical rules as PatternRule rows (one generic executor in
# ``_table``). The thin defs keep name/signature for the facade re-exports
# and the ``_vae_ctx`` seams.
# --------------------------------------------------------------------------- #
_RULE_HASHTAG_LABEL = PatternRule(
    name="unsupported_hashtag_label",
    scan="search",
    claim_patterns=(_HASHTAG_LABEL_PATTERN,),
    evidence_checks=(("no_row_label_prefixed", {"prefix": "#"}),),
    reason="Row labels carry no hashtag marker.",
)

_RULE_PARTIAL_EXHAUSTIVE_CLAIMS = PatternRule(
    name="unsupported_partial_exhaustive_claims",
    scan="findall",
    claim_patterns=(_PARTIAL_EXHAUSTIVE_RESULT_PATTERN,),
    evidence_checks=(
        (
            "any_fact_exactness",
            {
                "values": frozenset(
                    {"partial", "sample_only", "top_n_only", "derived"}
                )
            },
        ),
    ),
    exception_checks=("explicitly_bounded",),
    reason="Partial evidence supports no exhaustive result claim.",
)


def _unsupported_hashtag_label(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(run_pattern_rule(_RULE_HASHTAG_LABEL, claim_text, facts=facts))


def _unsupported_partial_exhaustive_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    return list(
        run_pattern_rule(
            _RULE_PARTIAL_EXHAUSTIVE_CLAIMS, claim_text, facts=facts
        )
    )


_RULE_ARTIFACT_CLASSIFICATIONS = PatternRule(
    name="unsupported_artifact_classifications",
    scan="sentences",
    evidence_checks=(
        ("surface_lacks", {"pattern": _EXPLICIT_ARTIFACT_EVIDENCE_PATTERN}),
        ("question_lacks", {"pattern": _PRESCRIBED_ARTIFACT_HANDLING_PATTERN}),
    ),
    sentence_patterns=(_ARTIFACT_CLASSIFICATION_PATTERN,),
    sentence_exception_patterns=(_ARTIFACT_QUALIFIER_PATTERN,),
    sentence_exception_checks=("negative_or_unknown_limitation",),
    dedupe=True,
    reason="Artifact classifications need explicit artifact evidence.",
)


def _unsupported_artifact_classifications(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    question_text: str = "",
) -> List[str]:
    return list(
        run_pattern_rule(
            _RULE_ARTIFACT_CLASSIFICATIONS,
            claim_text,
            facts=facts,
            question_text=question_text,
        )
    )


def _match_is_part_of_proposed_test(
    text: str,
    match: re.Match[str],
) -> bool:
    """Distinguish a future measurement question from an observed result."""

    start = max(text.rfind(mark, 0, match.start()) for mark in ".!?\n") + 1
    following = [
        position
        for mark in ".!?\n"
        for position in [text.find(mark, match.end())]
        if position >= 0
    ]
    sentence = text[start : min(following, default=len(text))]
    return bool(
        re.search(
            r"\b(?:prüf|pruef|untersuch|validier|klär|klaer)\w*\b",
            sentence,
            re.IGNORECASE,
        )
        and re.search(r"\b(?:ob|whether)\b", sentence, re.IGNORECASE)
    )


def _match_is_part_of_conditional_test(
    text: str,
    match: re.Match[str],
) -> bool:
    """Recognise future or falsifying analyses without treating them as results."""

    start = max(text.rfind(mark, 0, match.start()) for mark in ".!?\n") + 1
    following = [
        position
        for mark in ".!?\n"
        for position in [text.find(mark, match.end())]
        if position >= 0
    ]
    sentence = text[start : min(following, default=len(text))]
    if _match_is_part_of_proposed_test(text, match):
        return True
    return bool(
        re.search(
            r"\b(?:wenn|falls|if|would|würde|wuerde|könnte|koennte|"
            r"sollte|müsste|muesste|zu\s+prüfen|zu\s+pruefen|"
            r"widerleg\w*|falsifiz\w*)\b",
            sentence,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:prüf\w*|pruef\w*|untersuch\w*|analys\w*|"
            r"auswert\w*|kodier\w*|klassifiz\w*|vergleich\w*|"
            r"zeig\w*|ergeb\w*)\b",
            sentence,
            re.IGNORECASE,
        )
    )


_RULE_TEXT_PRODUCTION_INFERENCES = PatternRule(
    name="unsupported_text_production_inferences",
    scan="sentences",
    evidence_checks=(
        ("surface_lacks", {"pattern": _TEXT_PRODUCTION_EVIDENCE_PATTERN}),
    ),
    sentence_patterns=(
        _TEXT_PRODUCTION_ORIGIN_PATTERN,
        _TEXT_PRODUCTION_INFERENCE_PATTERN,
    ),
    sentence_exception_checks=("negative_or_unknown_limitation",),
    dedupe=True,
    reason="Text-production origins need production evidence.",
)


def _unsupported_text_production_inferences(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    return list(
        run_pattern_rule(
            _RULE_TEXT_PRODUCTION_INFERENCES, claim_text, facts=facts
        )
    )


def _unsupported_pos_claims(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    source_values = {
        value.casefold()
        for field in ("pos", "pos_tag", "upos")
        for value in _source_values_for_field(field, source_surface)
    }
    unsupported: List[str] = []
    for allowed_values, pattern in _NATURAL_POS_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            if not source_values.intersection(allowed_values):
                unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _unsupported_tool_provenance_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    unsupported: List[str] = []
    kwic_matches = list(
        _KWIC_PROVENANCE_PATTERN.finditer(claim_text or "")
    )
    if any(
        not _match_is_part_of_conditional_test(claim_text or "", match)
        for match in kwic_matches
    ):
        has_kwic_source = any(
            "kwic" in fact.statement.casefold()
            or any(
                "kwic" in source_id.casefold()
                or "run_cqlf_query" in source_id.casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in facts
        )
        if not has_kwic_source:
            unsupported.append("KWIC-Ausgabe")
    if _SEMANTIC_PROVENANCE_PATTERN.search(claim_text or "") is not None:
        semantic_facts = [
            fact
            for fact in facts
            if "semantisch" in fact.statement.casefold()
            or any(
                "semantic_search" in source_id.casefold()
                for source_id in fact.source_evidence_ids
            )
        ]
        if not semantic_facts:
            unsupported.append("semantische Treffer")
        else:
            semantic_surfaces = [
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                )
                for fact in semantic_facts
            ]
            for segment in _extract_grounding_example_segments(
                claim_text
            ):
                if not any(
                    _quoted_segment_is_supported(segment, surface)
                    for surface in semantic_surfaces
                ):
                    unsupported.append(
                        f"semantischer Treffer: {segment}"
                    )
    return list(dict.fromkeys(unsupported))


_RULE_DISTRIBUTION_CLAIMS = PatternRule(
    name="unsupported_distribution_claims",
    scan="search_constant",
    claim_patterns=(_UNIFORM_DISPERSION_PATTERN,),
    # A proposed dispersion test is a method, not a claim that the
    # distribution is already uniform.
    per_match_exception="proposed_test",
    evidence_checks=(
        (
            "field_values_lack",
            {
                "fields": ("dispersion", "distribution", "distribution_profile"),
                "values": frozenset(
                    {"uniform", "even", "evenly_distributed", "gleichmaessig"}
                ),
            },
        ),
    ),
    constant_result=("gleichmäßige Verteilung",),
    reason="A uniform distribution needs a visible dispersion value.",
)

_RULE_SCOPE_DESIGN_COMPLETENESS = PatternRule(
    name="unsupported_scope_design_completeness",
    scan="search_constant",
    claim_patterns=(_COMPLETENESS_CLAIM_PATTERN,),
    evidence_checks=(
        (
            "fields_lack_conjunction",
            {
                "specs": (
                    ("complete", frozenset({"true"})),
                    ("result_scope", frozenset({"full", "complete", "all"})),
                ),
            },
        ),
    ),
    constant_result=("Vollständigkeit",),
    reason="Completeness claims need complete=true and a full result scope.",
)

_RULE_SCOPE_DESIGN_REPRESENTATIVENESS = PatternRule(
    name="unsupported_scope_design_representativeness",
    scan="search_constant",
    claim_patterns=(_REPRESENTATIVENESS_CLAIM_PATTERN,),
    evidence_checks=(
        (
            "fields_lack_disjunction",
            {
                "specs": (
                    ("representative", frozenset({"true"})),
                    ("sampling_design", frozenset({"representative"})),
                ),
            },
        ),
    ),
    constant_result=("Repräsentativität",),
    reason="Representativeness claims need a visible sampling design.",
)


def _unsupported_distribution_claims(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    return list(
        run_pattern_rule(
            _RULE_DISTRIBUTION_CLAIMS,
            claim_text,
            source_surface=source_surface,
        )
    )


def _unsupported_scope_design_claims(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    # A boundary such as "nicht repräsentativ" protects against an
    # overclaim; it must not itself be treated as the overclaim.  Evaluate
    # mixed claims clause by clause so an affirmative neighbouring sentence
    # is still checked.
    affirmative_clauses = [
        clause.strip()
        for clause in re.split(
            r"(?<=[.!?])\s+|[;\n]+|"
            r",?\s*\b(?:aber|sondern|jedoch|hingegen|dennoch)\b\s*",
            claim_text or "",
            flags=re.IGNORECASE,
        )
        if clause.strip()
        and not (
            _is_negative_or_unknown_limitation(
                clause,
                claim_kind="limitation",
            )
            and re.search(r"\bnicht\s+nur\b", clause, re.IGNORECASE) is None
        )
    ]
    affirmative_surface = " ".join(affirmative_clauses)
    return [
        *run_pattern_rule(
            _RULE_SCOPE_DESIGN_COMPLETENESS,
            affirmative_surface,
            source_surface=source_surface,
        ),
        *run_pattern_rule(
            _RULE_SCOPE_DESIGN_REPRESENTATIVENESS,
            affirmative_surface,
            source_surface=source_surface,
        ),
    ]


_LEXICAL_RATING_WORD_PATTERN = re.compile(
    r"\b(?:hoch|niedrig|mittel|mittler|typisch|moderat|überdurchschnittlich|"
    r"ueberdurchschnittlich|unterdurchschnittlich)\w*\b",
    re.IGNORECASE,
)
_LEXICAL_RATING_DENIAL_PATTERN = re.compile(
    r"\bkein(?:e|en|er|es)?\s+"
    r"(?:(?:belastbar|objektiv|methodisch|valide|zuverlässig|"
    r"zuverlaessig)\w*\s+){0,2}"
    r"(?:einordnung|bewertung|klassifikation|qualitätsurteil|"
    r"qualitaetsurteil|qualitätsvergleich|qualitaetsvergleich|"
    r"qualität|qualitaet)\w*\b|"
    r"\bkein(?:e|en|er|es)?\s+(?:belastbare\w*\s+)?aussage\b"
    r"[^.!?\n]{0,120}\b(?:qualität|qualitaet|qualitätsniveau|qualitaetsniveau|"
    r"hoch|niedrig|mittel|mittler|moderat|typisch)\w*\b|"
    r"\b(?:lässt|laesst)\s+sich\b[^.!?\n]{0,120}\bnicht\b"
    r"[^.!?\n]{0,120}\b(?:einordnen|bewerten|bezeichnen|"
    r"klassifizieren|ableiten|beurteilen)\w*\b|"
    r"\b(?:kann|darf)\b[^.!?\n]{0,120}\bnicht\b"
    r"[^.!?\n]{0,120}\b(?:eingeordnet|bewertet|bezeichnet|"
    r"klassifiziert|abgeleitet|beurteilt)\w*\b",
    re.IGNORECASE,
)


def _is_lexical_reference_boundary_claim(text: str) -> bool:
    """Require an actual denied rating, not merely the word ``ohne``."""

    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        if re.search(
            r"\b(?:referenzkorpus|vergleichsbasis|vergleichskorpus)\b",
            sentence,
            re.IGNORECASE,
        ) is None:
            continue
        if _LEXICAL_RATING_DENIAL_PATTERN.search(sentence):
            return True
        if (
            _LEXICAL_RATING_WORD_PATTERN.search(sentence)
            and re.search(
                r"\b(?:nicht\s+(?:belegbar|bestimmbar|ableitbar|"
                r"zulässig|zulaessig)|unbelegt)\w*\b",
                sentence,
                re.IGNORECASE,
            )
        ):
            return True
    return False


def _has_relative_sttr_mattr_preference(text: str) -> bool:
    """Find a preference between STTR and MATTR, in either word order."""

    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        if not (
            re.search(r"\bsttr\b", sentence, re.IGNORECASE)
            and re.search(r"\bmattr\b", sentence, re.IGNORECASE)
        ):
            continue
        metric = r"(?:sttr|mattr)"
        relation = (
            r"(?:(?:belastbarer|robuster|stabiler|besser|geeigneter|"
            r"überlegen|ueberlegen|weniger\s+(?:belastbar|robust|"
            r"stabil|geeignet))\w*|"
            r"weniger\b[^.!?\n]{0,80}\b(?:abhängig|abhaengig|sensitiv|"
            r"längensensitiv|laengensensitiv)\w*)"
        )
        patterns = (
            rf"\b{metric}\b[^.!?\n]{{0,100}}\b{relation}\b"
            rf"[^.!?\n]{{0,60}}\b(?:als|gegenüber|gegenueber)\s+{metric}\b",
            rf"\b{metric}\b[^.!?\n]{{0,100}}\b(?:im\s+vergleich\s+zu|"
            rf"gegenüber|gegenueber)\s+{metric}\b[^.!?\n]{{0,100}}"
            rf"\b{relation}\b",
            rf"\b(?:im\s+vergleich\s+zu|gegenüber|gegenueber)\s+{metric}\b"
            rf"[^.!?\n]{{0,100}}\b{metric}\b[^.!?\n]{{0,100}}\b{relation}\b",
            rf"\b{metric}\b[^.!?\n]{{0,80}}\b(?:übertrifft|uebertrifft)\w*\b"
            rf"[^.!?\n]{{0,80}}\b{metric}\b",
            rf"\b{metric}\b[^.!?\n]{{0,80}}\b{metric}\b[^.!?\n]{{0,80}}"
            rf"\b(?:vorzuziehen|vorgezogen|bevorzugt)\w*\b",
        )
        if any(re.search(pattern, sentence, re.IGNORECASE) for pattern in patterns):
            return True
    return False


def _supported_equal_window_boundary_comparison(
    claim_text: str,
    source_surface: str,
) -> bool:
    """Recognise the one grounded STTR/MATTR preference encoded by the tool."""

    if re.search(
        r"\bmethod_comparison\s*=\s*[^\n]*"
        r"at_equal_window_mattr_is_less_sensitive_to_"
        r"arbitrary_segment_boundaries\b",
        source_surface,
        re.IGNORECASE,
    ) is None:
        return False
    for sentence in re.split(r"(?<=[.!?])\s+", str(claim_text or "")):
        lowered = sentence.casefold()
        if not (
            re.search(r"\bmattr\b", lowered)
            and re.search(r"\bsttr\b", lowered)
            and re.search(
                r"\b(?:bei|unter)\s+(?:der\s+)?(?:gleiche\w*|identische\w*)\s+"
                r"fenster\w*\b",
                lowered,
            )
            and re.search(
                r"\b(?:segment|fenster)?grenz\w*\b|"
                r"\bwillkür\w*\s+grenz\w*\b|"
                r"\barbitrary\s+(?:segment\s+)?boundar\w*\b",
                lowered,
            )
            and re.search(
                r"\bweniger\b[^.!?\n]{0,100}\b"
                r"(?:abhängig|abhaengig|sensitiv)\w*\b",
                lowered,
            )
        ):
            continue
        mattr_pos = lowered.find("mattr")
        sttr_pos = lowered.find("sttr")
        less_pos = lowered.find("weniger")
        if less_pos > mattr_pos and (sttr_pos < mattr_pos or sttr_pos > less_pos):
            return True
    return False


def _lexical_window_parameters_differ(
    facts: Sequence[ObservedFact],
) -> bool:
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    sttr_windows = _source_values_for_field("sttr_window", source_surface)
    mattr_windows = _source_values_for_field("mattr_window", source_surface)
    return bool(
        len(sttr_windows) == 1
        and len(mattr_windows) == 1
        and sttr_windows != mattr_windows
    )


def _unsupported_lexical_diversity_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    claim_kind: str = "",
) -> List[str]:
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    if not re.search(r"\b(?:ttr|sttr|mattr|n_tokens)\s*=", source_surface):
        return []

    unsupported: List[str] = []
    if re.search(
        r"\b(?:token[- ](?:zu|to)[- ]type|token[- ]type)[- ]ratio\b",
        claim_text or "",
        re.IGNORECASE,
    ):
        unsupported.append(
            "TTR als Token-zu-Type statt als Type-Token-Ratio bezeichnet"
        )
    baseline_visible = bool(
        re.search(
            r"\b(?:reference_corpus|referenzkorpus|baseline|benchmark|"
            r"norm_value|threshold|vergleichsverteilung)\s*=",
            source_surface,
            re.IGNORECASE,
        )
    )
    if (
        _has_unnegated_pattern(
            claim_text or "",
            _DIVERSITY_NORMATIVE_PATTERN,
        )
        and not baseline_visible
        and not (
            claim_kind == "limitation"
            and _is_lexical_reference_boundary_claim(claim_text)
        )
    ):
        unsupported.append("normatives Diversitätsurteil ohne Vergleichsbasis")
    method_validation_visible = bool(
        re.search(
            r"\bvalidation_result\s*=",
            source_surface,
            re.IGNORECASE,
        )
    )
    supported_boundary_comparison = _supported_equal_window_boundary_comparison(
        claim_text,
        source_surface,
    )
    if (
        _has_unnegated_pattern(
            claim_text or "",
            _DIVERSITY_METHOD_SUPERLATIVE_PATTERN,
        )
        and not method_validation_visible
    ):
        unsupported.append("unbelegter methodischer Superlativ")
    if (
        _has_relative_sttr_mattr_preference(claim_text)
        and not method_validation_visible
        and not supported_boundary_comparison
    ):
        unsupported.append("unbelegter relativer Methodenvergleich")
    if _TTR_WINDOW_DEPENDENCE_PATTERN.search(claim_text or ""):
        unsupported.append(
            "globalen TTR fälschlich als fensterabhängiges Maß beschrieben"
        )
    if _ROBUSTNESS_REFERENCE_CONFUSION_PATTERN.search(claim_text or ""):
        unsupported.append(
            "Methodenrobustheit fälschlich von einem Referenzkorpus abhängig gemacht"
        )
    if (
        _LEXICAL_REFERENCE_INTERPRETABILITY_PATTERN.search(claim_text or "")
        and _LEXICAL_RATING_INTERPRETATION_SCOPE_PATTERN.search(
            claim_text or ""
        )
        is None
    ):
        unsupported.append(
            "deskriptive Interpretierbarkeit der berechneten Maße fälschlich "
            "von einem Referenzkorpus abhängig gemacht"
        )
    if _TTR_STTR_ROBUSTNESS_EQUIVOCATION_PATTERN.search(claim_text or ""):
        unsupported.append(
            "globalen TTR und fensterbasierte Maße in der Größenrobustheit gleichgestellt"
        )
    if _STTR_VARIANCE_SMOOTHING_PATTERN.search(claim_text or ""):
        unsupported.append(
            "STTR fälschlich als Varianzglättung statt als Standardisierung "
            "auf feste Segmentlängen beschrieben"
        )
    if _STTR_UNSUPPORTED_VARIABILITY_PATTERN.search(claim_text or ""):
        unsupported.append(
            "geringere empirische Variation von STTR ohne entsprechende "
            "Variabilitätsauswertung behauptet"
        )
    if _LEXICAL_DENSITY_CONFUSION_PATTERN.search(claim_text or ""):
        unsupported.append(
            "lexikalische Diversität mit der davon verschiedenen "
            "Lexikaldichte verwechselt"
        )
    if (
        _lexical_window_parameters_differ(facts)
        and _EQUAL_WINDOW_ASSUMPTION_PATTERN.search(claim_text or "")
        and not supported_boundary_comparison
    ):
        unsupported.append(
            "gleiche Fensterparameter behauptet, obwohl STTR und MATTR im "
            "sichtbaren Lauf verschieden parametrisiert sind"
        )
    if (
        _TTR_CATEGORICAL_SIZE_DECLINE_PATTERN.search(claim_text or "")
        and _TTR_SIZE_TENDENCY_QUALIFIER_PATTERN.search(claim_text or "")
        is None
    ):
        unsupported.append(
            "TTR-Abnahme mit wachsender Stichprobe als monotone Gewissheit "
            "statt als typische Tendenz beschrieben"
        )
    if _TTR_EXCLUSIVE_SMALL_SCOPE_PATTERN.search(claim_text or ""):
        unsupported.append(
            "TTR ohne methodische Bedingung pauschal auf kleine Korpora "
            "beschränkt"
        )

    n_types = _source_values_for_field("n_types", source_surface)
    for match in _N_TYPES_AS_TOKENS_PATTERN.finditer(claim_text or ""):
        if (
            len(n_types) == 1
            and _normalize_number_token(
                match.group("count"),
                integer_grouping=True,
            ) in n_types
        ):
            unsupported.append(
                "n_types als unterschiedliche Tokens statt als Types oder "
                "verschiedene Wortformen bezeichnet"
            )
            break

    if (
        _source_values_for_field("analyst_token_policy", source_surface)
        and _MISSING_FILTER_POLICY_PATTERN.search(claim_text or "")
    ):
        unsupported.append(
            "sichtbare Filterpolitik fälschlich als nicht angegeben bezeichnet"
        )

    for sentence in re.split(r"(?<=[.!?])\s+", claim_text or ""):
        if (
            re.search(r"\bttr\b", sentence, re.IGNORECASE)
            and re.search(
                r"\b(?:bedeutet|heißt|heisst|entspricht)\b",
                sentence,
                re.IGNORECASE,
            )
            and re.search(r"\btokens?\b", sentence, re.IGNORECASE)
            and re.search(
                r"\b(?:einzigartig|unique|nur\s+einmal)\w*\b",
                sentence,
                re.IGNORECASE,
            )
        ):
            unsupported.append(
                "TTR als Anteil einmaliger Tokens statt Types pro Token"
            )
            break

    sttr_windows = _source_values_for_field("sttr_window", source_surface)
    mattr_windows = _source_values_for_field("mattr_window", source_surface)
    cross_metric_interpretation = any(
        re.search(r"\bmattr\b", sentence, re.IGNORECASE)
        and re.search(r"\bsttr\b", sentence, re.IGNORECASE)
        and re.search(
            r"\b(?:höher|hoeher|niedriger|größer|groesser|kleiner)\w*\b",
            sentence,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:variation\w*|diversität\w*|vielfalt\w*|"
            r"typenverteilung\w*)\b",
            sentence,
            re.IGNORECASE,
        )
        and re.search(
            r"(?:\b(?:deut\w*|hinweis\w*)\b|"
            r"\bweist\b[^.!?\n]{0,100}\bhin\b|"
            r"\bspricht\s+(?:für|fuer)\b)",
            sentence,
            re.IGNORECASE,
        )
        for sentence in re.split(r"(?<=[.!?])\s+", claim_text or "")
    )
    if (
        sttr_windows
        and mattr_windows
        and sttr_windows != mattr_windows
        and (
            _has_unnegated_pattern(
                claim_text or "",
                _DIVERSITY_CROSS_METRIC_MAGNITUDE_PATTERN,
            )
            or _DIVERSITY_CROSS_METRIC_INTERPRETATION_PATTERN.search(
                claim_text or ""
            )
            or cross_metric_interpretation
        )
    ):
        unsupported.append(
            "direkte Diversitätssteigerung aus verschieden gefensterten Maßen"
        )

    analysed = _source_values_for_field("n_tokens", source_surface)
    raw = _source_values_for_field("corpus_raw_token_count", source_surface)
    ttr_base_match = _TTR_TOKEN_BASE_PATTERN.search(claim_text or "")
    if (
        ttr_base_match is not None
        and len(analysed) == 1
        and len(raw) == 1
        and analysed != raw
        and _normalize_number_token(
            ttr_base_match.group("count"),
            integer_grouping=True,
        ) in raw
    ):
        unsupported.append(
            "rohe Korpustokens als Nenner der TTR auf der gefilterten Analysebasis"
        )
    population_match = _WHOLE_CORPUS_ANALYSIS_TOKEN_PATTERN.search(
        claim_text or ""
    )
    if (
        population_match is not None
        and len(analysed) == 1
        and len(raw) == 1
        and analysed != raw
        and _normalize_number_token(
            population_match.group("count"),
            integer_grouping=True,
        )
        in analysed
    ):
        nearby = str(claim_text or "")[
            population_match.start() : population_match.end()
        ]
        if re.search(
            r"\b(?:analysiert|gefiltert|analysebasis|ausgewertet)\w*\b",
            nearby,
            re.IGNORECASE,
        ) is None:
            unsupported.append(
                "gefilterte Analysetokens als gesamte Korpusgröße"
            )
    return unsupported


def _unsupported_correlation_claims(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    unsupported: List[str] = []
    values = _field_numeric_values(
        source_surface,
        ("correlation", "correlation_coefficient", "r"),
    )
    directions = _source_values_for_field("direction", source_surface)
    for match in _CORRELATION_DIRECTION_PATTERN.finditer(claim_text or ""):
        claimed = (
            match.group("direction") or match.group("direction_first") or ""
        ).casefold()
        explicit = claimed in directions
        numeric = False
        if len(values) == 1:
            try:
                coefficient = float(next(iter(values)))
                numeric = (
                    coefficient > 0
                    if claimed == "positiv"
                    else coefficient < 0
                )
            except (TypeError, ValueError):
                pass
        if not (explicit or numeric):
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _unsupported_rate_denominator_bindings(
    claim_text: str,
    source_surface: str,
) -> List[str]:
    expected_tokens = _source_values_for_field(
        "denominator_tokens",
        source_surface,
    )
    expected_scopes = _source_values_for_field(
        "denominator_scope",
        source_surface,
    )
    unsupported: List[str] = []
    for pattern in _RATE_DENOMINATOR_PATTERNS:
        for match in pattern.finditer(claim_text or ""):
            claimed_tokens = _normalize_number_token(
                match.group("tokens"),
                integer_grouping=True,
            )
            raw_scope = str(match.group("scope") or "").casefold()
            claimed_scope = (
                "corpus"
                if raw_scope in {"korpus", "corpus"}
                else "docset"
                if raw_scope in {"docset", "subkorpus", "teilkorpus"}
                else ""
            )
            if (
                claimed_tokens not in expected_tokens
                or (
                    claimed_scope
                    and expected_scopes
                    and claimed_scope not in expected_scopes
                )
                or (
                    match.groupdict().get("all")
                    and expected_scopes
                    and "corpus" not in expected_scopes
                )
            ):
                unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _extract_numeric_tokens_outside_spans(
    text: str,
    ignored_spans: Sequence[tuple[int, int]],
) -> List[str]:
    return [
        _normalize_number_token(
            match.group(0),
            integer_grouping=_number_has_integer_grouping_context(text, match),
        )
        for match in _NUMBER_PATTERN.finditer(text or "")
        if not any(
            start <= match.start() and match.end() <= end
            for start, end in ignored_spans
        )
    ]


def _natural_metric_bindings(
    text: str,
) -> List[tuple[str, str]]:
    bindings: List[tuple[str, str]] = []
    for field, pattern in _NATURAL_METRIC_PATTERNS:
        for match in pattern.finditer(text or ""):
            raw_value = match.group("value")
            if raw_value:
                bindings.append((field, raw_value))
    for match in _ORDINAL_RANK_PATTERN.finditer(text or ""):
        value = _ORDINAL_RANK_STEMS.get(match.group(1).casefold())
        if value:
            bindings.append(("rank", value))
    for match in _PREDICATIVE_ORDINAL_RANK_PATTERN.finditer(text or ""):
        value = _ORDINAL_RANK_STEMS.get(match.group(1).casefold())
        if value:
            bindings.append(("rank", value))
    for match in _COPULATIVE_ORDINAL_RANK_PATTERN.finditer(text or ""):
        value = _ORDINAL_RANK_STEMS.get(match.group(1).casefold())
        if value:
            bindings.append(("rank", value))
    for pattern in (
        _ORDERED_LIST_ENTRY_RANK_PATTERN,
        _LIST_ENTRY_IN_RANKING_PATTERN,
    ):
        for match in pattern.finditer(text or ""):
            value = _ORDINAL_RANK_STEMS.get(match.group(1).casefold())
            if value:
                bindings.append(("rank", value))
    for match in _PRECEDING_ENTRIES_RANK_PATTERN.finditer(text or ""):
        raw_count = match.group("number")
        count = (
            raw_count
            if raw_count.isdigit()
            else _number_word_value(raw_count)
        )
        if count is not None:
            rank = int(count) + 1
            if 1 <= rank <= 1_000_000:
                bindings.append(("rank", str(rank)))
    for match in _WORD_RANK_PATTERN.finditer(text or ""):
        value = _number_word_value(match.group("number"))
        if value:
            bindings.append(("rank", value))
    if any(pattern.search(text or "") for pattern in _RANK_ONE_PATTERNS):
        bindings.append(("rank", "1"))
    return bindings


def _unsupported_natural_metric_bindings(
    text: str,
    source_surface: str,
) -> List[str]:
    unsupported: List[str] = []
    for field, raw_value in _natural_metric_bindings(text):
        value = _normalise_field_value(raw_value, field=field)
        if field == "per_million":
            if not _rate_token_is_supported(value, [source_surface]):
                unsupported.append(f"{field}={raw_value}")
            continue
        if field == "position":
            # In a ranked table "Position" denotes rank; in KWIC provenance
            # it denotes an absolute token position. Resolve the ambiguous
            # natural-language label against the fields actually present.
            source_values = {
                *_source_values_for_field("rank", source_surface),
                *_source_values_for_field("pos", source_surface),
            }
        else:
            source_values = _source_values_for_field(field, source_surface)
        if not source_values or not _numeric_token_is_supported(
            value,
            source_values,
        ):
            unsupported.append(f"{field}={raw_value}")
    return list(dict.fromkeys(unsupported))


def _canonical_claim_metric(raw_metric: str) -> str:
    normalised = re.sub(
        r"[- ]+",
        " ",
        str(raw_metric or "").casefold(),
    ).strip()
    return {
        "log dice": "logdice",
        "mutual information": "mi",
        "t score": "t",
        "log likelihood": "ll",
        "chi quadrat": "chi2_cell",
        "chiquadrat": "chi2_cell",
        "chi2": "chi2_cell",
        "z score": "z",
        "delta p nc": "delta_p_nc",
        "delta p cn": "delta_p_cn",
    }.get(normalised, normalised.replace(" ", ""))


def _visible_metric_values_by_label(
    metric: str,
    referenced_facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
) -> tuple[Dict[str, float], Dict[str, str]]:
    source_ids = {
        source_id
        for fact in referenced_facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    candidate_facts = [
        fact
        for fact in observed_facts
        if fact.fact_kind == "ranked_row"
        and (
            not source_ids
            or source_ids.intersection(fact.source_evidence_ids)
        )
    ]
    if not candidate_facts:
        candidate_facts = [
            fact
            for fact in referenced_facts
            if fact.fact_kind == "ranked_row"
        ]

    values_by_label: Dict[str, float] = {}
    display_by_label: Dict[str, str] = {}
    for fact in candidate_facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        raw_values = _source_values_for_field(metric, surface)
        if not raw_values:
            continue
        try:
            value = float(next(iter(raw_values)))
        except (TypeError, ValueError):
            continue
        labels = {
            label
            for field in _ROW_LABEL_FIELD_NAMES
            for label in _source_values_for_field(field, surface)
            if label
        }
        for label in labels:
            key = label.casefold()
            values_by_label[key] = value
            display_by_label[key] = label
    return values_by_label, display_by_label


def _unsupported_metric_maximum_claims(
    text: str,
    referenced_facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
) -> List[str]:
    """Check named metric maxima against every visible row of that result."""

    unsupported: List[str] = []
    for match in _METRIC_MAXIMUM_PATTERN.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 16) : match.start()]
        if re.search(r"(?:unter|zu)\s+den\s+$", prefix, re.IGNORECASE):
            # "unter/zu den höchsten" denotes a top group, not an exact tie
            # for the maximum.
            continue
        metric = _canonical_claim_metric(match.group("metric"))
        values_by_label, display_by_label = (
            _visible_metric_values_by_label(
                metric,
                referenced_facts,
                observed_facts,
            )
        )
        if not values_by_label:
            unsupported.append(match.group(0))
            continue

        source_ids = {
            source_id
            for fact in referenced_facts
            for source_id in fact.source_evidence_ids
            if source_id
        }
        source_facts = [
            fact
            for fact in observed_facts
            if not source_ids
            or source_ids.intersection(fact.source_evidence_ids)
        ]
        metric_facts = [
            fact
            for fact in source_facts
            if fact.fact_kind == "ranked_row"
            and _source_values_for_field(
                metric,
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                ),
            )
        ]
        result_is_partial = any(
            fact.exactness in {"sample_only", "top_n_only", "partial"}
            for fact in metric_facts
        )
        sort_metrics = {
            _canonical_claim_metric(value)
            for fact in source_facts
            for field in ("sort_by", "score_key")
            for value in _source_values_for_field(
                field,
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                ),
            )
        }
        rank_one_visible = any(
            "1"
            in _source_values_for_field(
                "rank",
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                ),
            )
            for fact in metric_facts
        )
        if (
            result_is_partial
            and not _is_explicitly_bounded_claim(text)
            and (metric not in sort_metrics or not rank_one_visible)
        ):
            unsupported.append(
                f"{metric} Maximum außerhalb des sichtbaren Ausschnitts"
            )
            continue

        quoted = {
            _normalise_quote_for_match(segment)
            for segment in _extract_grounding_example_segments(text)
            if _normalise_quote_for_match(segment)
        }
        mentioned = {
            label
            for label in values_by_label
            if label in quoted
            or (
                len(label) >= 3
                and re.search(
                    rf"(?<!\w){re.escape(label)}(?!\w)",
                    (text or "").casefold(),
                )
            )
        }
        if not mentioned:
            referenced_labels = _source_row_label_lookup(
                referenced_facts
            )
            mentioned = {
                label.casefold()
                for label in referenced_labels.values()
                if label.casefold() in values_by_label
            }

        maximum = max(values_by_label.values())
        if not mentioned or any(
            not math.isclose(
                values_by_label[label],
                maximum,
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
            for label in mentioned
        ):
            labels = ", ".join(
                display_by_label[label]
                for label in sorted(mentioned)
            )
            unsupported.append(
                f"{metric} Maximum"
                + (f": {labels}" if labels else "")
            )
    return list(dict.fromkeys(unsupported))


def _unsupported_result_wide_metric_ranges(
    text: str,
    referenced_facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
) -> List[str]:
    if _RESULT_WIDE_METRIC_RANGE_PATTERN.search(text or "") is None:
        return []

    unsupported: List[str] = []
    for match in _NAMED_METRIC_RANGE_PATTERN.finditer(text or ""):
        metric = _canonical_claim_metric(match.group("metric"))
        values_by_label, _ = _visible_metric_values_by_label(
            metric,
            referenced_facts,
            observed_facts,
        )
        if not values_by_label:
            unsupported.append(match.group(0))
            continue
        low = _normalize_number_token(match.group("low"))
        high = _normalize_number_token(match.group("high"))
        visible_low = _normalise_field_value(
            min(values_by_label.values()),
            field=metric,
        )
        visible_high = _normalise_field_value(
            max(values_by_label.values()),
            field=metric,
        )
        if not (
            _numeric_token_is_supported(low, {visible_low})
            and _numeric_token_is_supported(high, {visible_high})
        ):
            unsupported.append(
                f"{metric}={match.group('low')}–{match.group('high')}"
            )
    return list(dict.fromkeys(unsupported))


def _numeric_percent_tokens(text: str) -> set[str]:
    tokens = {
        _normalize_number_token(match.group(1))
        for match in re.finditer(
            r"\b(\d+(?:[.,]\d+)?)\s*"
            r"(?:%|prozent(?:ig\w*)?\b)",
            text or "",
            re.IGNORECASE,
        )
    }
    tokens.update(
        _normalize_number_token(match.group("value"))
        for match in _NATURAL_PERCENT_VALUE_PATTERN.finditer(text or "")
    )
    return tokens


def _unsupported_word_percent_bindings(
    text: str,
    source_surface: str,
) -> List[str]:
    unsupported: List[str] = []
    for match in _WORD_PERCENT_PATTERN.finditer(text or ""):
        value = _number_word_value(match.group(1))
        if value and not _percent_token_is_supported(value, source_surface):
            unsupported.append(match.group(0))
    fraction_share_claim = re.search(
        r"\b(?:ein(?:e|en|em|er|es)?\s+)?(?:"
        + "|".join(
            sorted(
                (re.escape(word) for word in _FRACTION_RATIOS),
                key=len,
                reverse=True,
            )
        )
        + r")\b[^.!?\n]{0,40}\b(?:der|aller)\s+"
        r"(?:treffer|fundstellen|belege|vorkommen)\b",
        text or "",
        re.IGNORECASE,
    )
    if fraction_share_claim or re.search(
        r"\b(?:anteil|quote|coverage(?:[_ -]?ratio)?|abdeckung|"
        r"entspricht|bruchteil)\b",
        text or "",
        re.IGNORECASE,
    ):
        for match in _FRACTION_PERCENT_PATTERN.finditer(text or ""):
            fraction_word = match.group(1).casefold()
            if (
                fraction_word in _FRACTION_RATIOS
                and not _fraction_percent_is_supported(
                    fraction_word,
                    source_surface,
                )
            ):
                unsupported.append(match.group(0))
    for match in _DISTRIBUTIVE_FRACTION_PATTERN.finditer(text or ""):
        numerator, denominator = _DISTRIBUTIVE_FRACTION_RATIOS[
            match.group(1).casefold()
        ]
        if not _ratio_share_is_supported(
            numerator,
            denominator,
            source_surface,
        ):
            unsupported.append(match.group(0))
    return list(dict.fromkeys(unsupported))


def _fraction_percent_is_supported(
    fraction_word: str,
    source_surface: str,
) -> bool:
    numerator, denominator = _FRACTION_RATIOS[fraction_word]
    return _ratio_share_is_supported(
        numerator,
        denominator,
        source_surface,
    )


def _ratio_share_is_supported(
    numerator: int,
    denominator: int,
    source_surface: str,
) -> bool:
    exact_ratio = numerator / denominator

    def visible_value_matches(raw: str, expected: float) -> bool:
        try:
            visible = float(raw)
        except (TypeError, ValueError):
            return False
        decimals = len(raw.rsplit(".", 1)[1]) if "." in raw else 0
        tolerance = 0.5 * (10.0 ** -decimals) if decimals else 0.5
        return abs(visible - expected) <= tolerance + 1e-12

    if any(
        visible_value_matches(value, exact_ratio)
        for value in _field_numeric_values(
            source_surface,
            _RATIO_PERCENT_FIELD_NAMES,
        )
    ):
        return True
    if any(
        visible_value_matches(value, exact_ratio * 100.0)
        for value in _field_numeric_values(
            source_surface,
            _EXPLICIT_PERCENT_FIELD_NAMES,
        )
    ):
        return True
    numerators = _field_numeric_values(
        source_surface,
        ("f", "freq", "frequency", "count"),
    )
    denominators = _field_numeric_values(
        source_surface,
        ("total", "total_hits", "anchor_count"),
    )
    if len(numerators) != 1 or len(denominators) != 1:
        return False
    try:
        numerator = float(next(iter(numerators)))
        denominator = float(next(iter(denominators)))
    except (TypeError, ValueError):
        return False
    return (
        denominator > 0
        and abs((numerator / denominator) - exact_ratio) <= 1e-12
    )


def _percent_token_is_supported(
    token: str,
    source_surface: str,
    *,
    decimal_places: int | None = None,
) -> bool:
    percentages = set(_field_numeric_values(source_surface, _EXPLICIT_PERCENT_FIELD_NAMES))
    try:
        percentages.update(
            str(Decimal(ratio) * 100)
            for ratio in _field_numeric_values(source_surface, _RATIO_PERCENT_FIELD_NAMES)
        )
        numerators = _field_numeric_values(source_surface, ("f", "freq", "frequency", "count"))
        denominators = _field_numeric_values(source_surface, ("total", "total_hits", "anchor_count"))
        if len(numerators) == 1 and len(denominators) == 1:
            denominator = Decimal(next(iter(denominators)))
            if denominator > 0:
                percentages.add(str(100 * Decimal(next(iter(numerators))) / denominator))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return _numeric_token_is_supported(token, percentages, decimal_places=decimal_places)


def _numeric_token_is_supported(
    token: str,
    allowed_numbers: set[str],
    *,
    decimal_places: int | None = None,
) -> bool:
    """Compare exact values or decimal rounding at the written precision.

    Integer evidence stays exact. Fractional metrics can be rounded to any
    stated precision, including whole rates. Halfway values round away from zero.
    """
    try:
        claimed = Decimal(token)
        if not claimed.is_finite():
            return False
        places = max(0, -claimed.as_tuple().exponent) if decimal_places is None else decimal_places
        quantum = Decimal(1).scaleb(-places)
    except (InvalidOperation, TypeError, ValueError):
        return False
    for allowed in allowed_numbers:
        try:
            visible = Decimal(allowed)
            if not visible.is_finite():
                continue
            if visible == claimed:
                return True
            if visible != visible.to_integral_value() and visible.quantize(
                quantum, rounding=ROUND_HALF_UP,
            ) == claimed:
                return True
        except (InvalidOperation, TypeError, ValueError):
            continue
    return False


def _extract_ranges(text: str) -> List[str]:
    return [re.sub(r"\s+", "", match.group(0)) for match in _RANGE_PATTERN.finditer(text)]


def _has_word_range_claim(text: str) -> bool:
    return bool(_WORD_RANGE_PATTERN.search(text or ""))


def _has_word_count_claim(text: str) -> bool:
    return (
        bool(_DOZEN_COUNT_PATTERN.search(text or ""))
        or any(
            _number_word_value(match.group("number")) is not None
            and not _word_count_match_is_indefinite_article(
                match,
                text or "",
            )
            for match in _WORD_COUNT_PATTERN.finditer(text or "")
        )
        or any(
            _number_word_value(match.group("number")) is not None
            for match in _WORD_RESULT_COUNT_PATTERN.finditer(text or "")
        )
    )


def _is_existential_kwic_evidence_claim(
    text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """A visible KWIC row proves existence, but no larger cardinality."""

    return bool(
        _EXISTENTIAL_KWIC_EVIDENCE_PATTERN.search(text or "")
        and any(fact.fact_kind == "kwic_example" for fact in facts)
    )


def _has_digit_count_claim(text: str) -> bool:
    return bool(
        _DIGIT_COUNT_PATTERN.search(text or "")
        or _DIGIT_RESULT_COUNT_PATTERN.search(text or "")
    )


def _without_markdown_list_ordinals(text: str) -> str:
    return _MARKDOWN_LIST_ORDINAL_PATTERN.sub(
        lambda match: match.group(1),
        text or "",
    )


def _without_claim_step_ordinals(text: str) -> str:
    without_named_steps = _CLAIM_STEP_ORDINAL_PATTERN.sub("", text or "")
    return _INLINE_LIST_ORDINAL_PATTERN.sub("", without_named_steps)


def _extract_quoted_segments(text: str) -> List[str]:
    result: List[str] = []
    for match in _QUOTED_SEGMENT_PATTERN.finditer(text):
        # One capture group per quote pair; exactly one is populated per match.
        value = next((group for group in match.groups() if group), "")
        value = _compact_text(value, 160)
        if value:
            result.append(value)
    return result


def _extract_blockquote_segments(text: str) -> List[str]:
    """Join contiguous Markdown quote lines into the corpus passage they quote."""

    segments: List[str] = []
    current_lines: List[str] = []

    def flush() -> None:
        if not current_lines:
            return
        value = _compact_text(" ".join(current_lines), 160)
        if value:
            segments.append(value)
        current_lines.clear()

    for line in str(text or "").splitlines():
        match = re.match(r"^\s*>\s?(.*)$", line)
        if match is None:
            flush()
            continue
        current_lines.append(match.group(1).strip())
    flush()

    for match in _COMPACT_BLOCKQUOTE_PATTERN.finditer(text or ""):
        value = re.sub(r"\s+>\s*", " ", match.group(1))
        value = _compact_text(value, 160)
        if value:
            segments.append(value)
    return list(dict.fromkeys(segments))


def _unpaired_empirical_quote_matches(
    text: str,
) -> List[re.Match[str]]:
    """Return only empirical quote cues whose opener has no matching closer."""

    matches: List[re.Match[str]] = []
    for match in _UNPAIRED_EMPIRICAL_QUOTE_PATTERN.finditer(text or ""):
        closer = _EMPIRICAL_QUOTE_CLOSERS.get(match.group("opener"), "")
        if closer and closer in match.group("example"):
            continue
        matches.append(match)
    return matches


def _prose_outside_examples(text: str) -> str:
    """Return analytical prose without quoted corpus language or inline code."""

    def mask(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    prose = str(text or "")
    for match in reversed(_unpaired_empirical_quote_matches(prose)):
        prose = (
            prose[: match.start()]
            + (" " * (match.end() - match.start()))
            + prose[match.end() :]
        )
    for pattern in (
        _MARKDOWN_BLOCKQUOTE_PATTERN,
        _COMPACT_BLOCKQUOTE_PATTERN,
        _UNQUOTED_EMPIRICAL_EXAMPLE_PATTERN,
        _UNDELIMITED_WORDING_EXAMPLE_PATTERN,
        _WORDING_FIRST_EXAMPLE_PATTERN,
        _ORIGINAL_FORMULATION_EXAMPLE_PATTERN,
        _TEXT_BOUNDARY_EXAMPLE_PATTERN,
        _QUOTED_SEGMENT_PATTERN,
        _INLINE_CODE_SEGMENT_PATTERN,
    ):
        prose = pattern.sub(mask, prose)
    return prose


#: Beide Namen zeigen jetzt auf ``quote_rules``. Die Wache im Chokepoint
#: (``recipe_runtime.strike_unsupported_quotes``) braucht dieselbe
#: Normalisierung und dieselbe Wortgrenzen-Regel, und zwei Fassungen
#: derselben Regel sind die naechste Divergenz.
_normalise_quote_for_match = normalisiere_zitat_fuer_vergleich
_normalised_quote_occurs = spanne_kommt_wortweise_vor


def _quoted_segment_is_supported(segment: str, surface: str) -> bool:
    """Accept exact quotes and explicit ellipsis abbreviations in source order."""
    needle = _normalise_quote_for_match(segment)
    haystack = _normalise_quote_for_match(surface)
    if not needle:
        return False
    if _normalised_quote_occurs(needle, haystack):
        return True
    # A copied sentence remains verbatim when only terminal sentence
    # punctuation was supplied by the surrounding prose rather than the raw
    # corpus field. Internal punctuation and token order remain exact.
    needle_without_terminal = needle.rstrip(".!?")
    if (
        needle_without_terminal != needle
        and _normalised_quote_occurs(needle_without_terminal, haystack)
    ):
        return True
    # Corpus tokenisation may expose quote marks as separate tokens. Preserve
    # lexical verbatimness when every word is still a contiguous exact token
    # sequence; this does not license substitutions or reordered paraphrases.
    needle_tokens = re.findall(r"\w+", needle, re.UNICODE)
    haystack_tokens = re.findall(r"\w+", haystack, re.UNICODE)
    if len(needle_tokens) >= 4 and len(needle_tokens) <= len(haystack_tokens):
        width = len(needle_tokens)
        if any(
            haystack_tokens[index : index + width] == needle_tokens
            for index in range(len(haystack_tokens) - width + 1)
        ):
            return True
    # Dieselbe Auslassungsdefinition wie im Chokepoint. Sie deckt jetzt
    # auch vier Punkte ab (drei Auslassungspunkte plus Satzpunkt), die die
    # frueher hier stehende ``\.\.\.``-Fassung als drei Punkte plus einen
    # Fragmentanfang gelesen hat.
    fragments = auslassungssegmente(needle)
    has_ellipsis = bool(fragments)
    if len(fragments) == 1 and has_ellipsis:
        fragment = fragments[0]
        # A leading/trailing ellipsis is a legitimate abbreviation of an exact
        # corpus line. Require a substantial fragment so a tiny quoted token
        # cannot masquerade as a grounded example.
        if len(fragment) >= 12 and len(fragment.split()) >= 3:
            return _normalised_quote_occurs(fragment, haystack)
    if len(fragments) < 2:
        return False
    cursor = 0
    for fragment in fragments:
        match = re.search(
            rf"(?<!\w){re.escape(fragment)}(?!\w)",
            haystack[cursor:],
        )
        if match is None:
            return False
        cursor += match.end()
    return True


_EMPIRICAL_QUOTE_CONTEXT_PATTERN = EMPIRISCHER_KONTEXT
_SCOPE_QUOTE_CONTEXT_PATTERN = SCOPE_KONTEXT


def _extract_empirical_inline_code_segments(text: str) -> List[str]:
    segments: List[str] = []
    raw = str(text or "")
    for match in _INLINE_CODE_SEGMENT_PATTERN.finditer(raw):
        nearby = raw[
            max(0, match.start() - 48) : min(len(raw), match.end() + 48)
        ]
        if _EMPIRICAL_QUOTE_CONTEXT_PATTERN.search(nearby):
            value = _compact_text(match.group(1), 160)
            # Snake-case identifiers denote tools/fields in explanatory prose,
            # not quoted corpus material (for example `metadata_values`).
            if value and not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+", value):
                segments.append(value)
    return segments


def _extract_grounding_example_segments(text: str) -> List[str]:
    unquoted_examples = [
        _compact_text(match.group("example"), 160)
        for match in _UNQUOTED_EMPIRICAL_EXAMPLE_PATTERN.finditer(text or "")
        if _compact_text(match.group("example"), 160)
    ]
    undelimited_examples = [
        _compact_text(match.group("example"), 160)
        for match in _UNDELIMITED_WORDING_EXAMPLE_PATTERN.finditer(
            text or ""
        )
        if _compact_text(match.group("example"), 160)
    ]
    wording_first_examples = [
        _compact_text(match.group("example"), 160)
        for match in _WORDING_FIRST_EXAMPLE_PATTERN.finditer(text or "")
        if _compact_text(match.group("example"), 160)
    ]
    original_formulation_examples = [
        _compact_text(match.group("example"), 160)
        for match in _ORIGINAL_FORMULATION_EXAMPLE_PATTERN.finditer(
            text or ""
        )
        if _compact_text(match.group("example"), 160)
    ]
    boundary_examples = [
        _compact_text(match.group("example"), 160)
        for match in _TEXT_BOUNDARY_EXAMPLE_PATTERN.finditer(text or "")
        if _compact_text(match.group("example"), 160)
    ]
    unpaired_examples = [
        _compact_text(match.group("example"), 160)
        for match in _unpaired_empirical_quote_matches(text)
        if _compact_text(match.group("example"), 160)
    ]
    return list(
        dict.fromkeys(
            [
                *_extract_quoted_segments(text),
                *_extract_empirical_inline_code_segments(text),
                *_extract_blockquote_segments(text),
                *unquoted_examples,
                *undelimited_examples,
                *wording_first_examples,
                *original_formulation_examples,
                *boundary_examples,
                *unpaired_examples,
            ]
        )
    )


_SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN = re.compile(
    r"\b(?:passage|ausschnitt|beleg|fundstelle|quelle|text|tweet|"
    r"äußerung|aeusserung|excerpt|passage|source)\w*\b"
    r"[^.!?\n]{0,100}\b(?:(?:leg\w*\s+(?:dar|nahe))|"
    r"(?:heiß|heiss)\w*|(?:behaupt|formulier|sag|schreib|beschreib|"
    r"interpret|kritis|bewert|bezeichn|charakteris|präsent|praesent|"
    r"verknüpf|verknuepf|verbind|rahm|stell)\w*)\b|"
    r"\b(?:laut|according\s+to)\s+(?:der|dem|dieser|diesem|the)\s+"
    r"(?:passage|ausschnitt|beleg|quelle|source)\b",
    re.IGNORECASE,
)
_SOURCE_ATTRIBUTED_CAUSAL_LINK_PATTERN = re.compile(
    r"\b(?:weil|denn|da|wegen|aufgrund|infolge|deshalb|daher|"
    r"verursach\w*|bewirk\w*|bedingt\w*|ursäch\w*|ursaech\w*|"
    r"(?:grund|ursache)\s+(?:dafür|dafuer|für|fuer|von))\b",
    re.IGNORECASE,
)
_SOURCE_READING_TOKEN_STOPWORDS = {
    "aber",
    "auch",
    "dass",
    "dieser",
    "diesem",
    "einzelne",
    "einer",
    "eines",
    "passage",
    "quelle",
    "source",
    "text",
    "wegen",
}
_CROSS_SENTENCE_INFERENCE_PATTERN = re.compile(
    r"\b(?:dadurch|deshalb|daraus|infolgedessen|somit|damit|"
    r"so\s+dass|sodass)\b",
    re.IGNORECASE,
)
_SOURCE_READING_CLAUSE_SPLIT_PATTERN = re.compile(
    r"(?<=[.!?;])\s+|\b(?:aber|während|waehrend|wohingegen|"
    r"but|while|whereas)\b",
    re.IGNORECASE,
)
_LIKELY_PREDICATE_TOKEN_PATTERN = re.compile(
    r"(?:en|ern|eln|st|t|te|ten|tet|ed|ing|es|s)$",
    re.IGNORECASE,
)


def _source_passage_sentence_units(
    facts: Sequence[ObservedFact],
) -> List[List[str]]:
    passages: List[List[str]] = []
    for fact in facts:
        if fact.fact_kind != "kwic_example":
            continue
        passage_segments = _dedupe_ordered_strs(
            [
                segment
                for surface in [fact.statement, *fact.grounding_quotes]
                for segment in _extract_grounding_example_segments(surface)
                if segment
            ]
        )
        for passage in passage_segments:
            sentences = [
                " ".join(part.split())
                for part in re.split(
                    r"(?<=[.!?])\s+|[\r\n]+",
                    passage,
                )
                if " ".join(part.split())
            ]
            if sentences:
                passages.append(sentences)
    return passages


def _source_attributed_cross_sentence_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Reject a new inference that joins separate source sentences."""

    if (
        _SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN.search(claim_text or "")
        is None
        or _CROSS_SENTENCE_INFERENCE_PATTERN.search(claim_text or "") is None
    ):
        return False
    claim_tokens = {
        token.casefold()
        for token in re.findall(r"[^\W\d_]+", claim_text or "", re.UNICODE)
        if len(token) >= 4
        and token.casefold() not in _SOURCE_READING_TOKEN_STOPWORDS
    }

    def related(left: str, right: str) -> bool:
        return left == right or (
            min(len(left), len(right)) >= 5
            and left[:5] == right[:5]
        )

    for sentences in _source_passage_sentence_units(facts):
        if len(sentences) < 2:
            continue
        sentence_tokens = [
            {
                token.casefold()
                for token in re.findall(r"[^\W\d_]+", sentence, re.UNICODE)
                if len(token) >= 4
            }
            for sentence in sentences
        ]
        matched_units = 0
        for index, tokens in enumerate(sentence_tokens):
            other_tokens = set().union(
                *(
                    value
                    for other_index, value in enumerate(sentence_tokens)
                    if other_index != index
                )
            )
            distinctive = tokens - other_tokens
            if any(
                related(claim_token, source_token)
                for claim_token in claim_tokens
                for source_token in distinctive
            ):
                matched_units += 1
        if matched_units >= 2:
            return True
    return False


def _source_attributed_unmarked_causal_link(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Reject causal binding added to a source passage without a causal marker."""

    if (
        _SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN.search(claim_text or "")
        is None
        or not _has_unnegated_pattern(
            claim_text or "",
            _SOURCE_ATTRIBUTED_CAUSAL_LINK_PATTERN,
        )
    ):
        return False
    source_units = [
        sentence
        for sentences in _source_passage_sentence_units(facts)
        for sentence in sentences
    ]
    return bool(source_units) and not any(
        _CAUSAL_ASSERTION_PATTERN.search(sentence)
        for sentence in source_units
    )


def _source_attributed_cross_sentence_predicate_transfer(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Catch a predicate borrowed from one sentence for another participant."""

    if (
        _SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN.search(claim_text or "")
        is None
    ):
        return False

    def tokens_with_stems(text: str) -> List[Tuple[str, str]]:
        return [
            (token, token.casefold()[:5])
            for token in re.findall(
                r"[^\W\d_]+",
                text or "",
                re.UNICODE,
            )
            if len(token) >= 5
            and token.casefold() not in _SOURCE_READING_TOKEN_STOPWORDS
        ]

    claim_clauses = [
        tokens_with_stems(clause)
        for clause in _SOURCE_READING_CLAUSE_SPLIT_PATTERN.split(
            claim_text or ""
        )
        if clause.strip()
    ]
    for sentences in _source_passage_sentence_units(facts):
        if len(sentences) < 2:
            continue
        sentence_tokens = [tokens_with_stems(sentence) for sentence in sentences]
        sentence_stems = [
            {stem for _token, stem in tokens}
            for tokens in sentence_tokens
        ]
        distinctive_participants: List[set[str]] = []
        distinctive_predicates: List[set[str]] = []
        for index, tokens in enumerate(sentence_tokens):
            other_stems = set().union(
                *(
                    stems
                    for other_index, stems in enumerate(sentence_stems)
                    if other_index != index
                )
            )
            distinctive_participants.append(
                {
                    stem
                    for token, stem in tokens
                    if token[:1].isupper() and stem not in other_stems
                }
            )
            distinctive_predicates.append(
                {
                    stem
                    for token, stem in tokens
                    if token[:1].islower()
                    and stem not in other_stems
                    and _LIKELY_PREDICATE_TOKEN_PATTERN.search(token)
                }
            )
        for clause_tokens in claim_clauses:
            clause_stems = {stem for _token, stem in clause_tokens}
            participant_sources = {
                index
                for index, stems in enumerate(distinctive_participants)
                if clause_stems.intersection(stems)
            }
            predicate_sources = {
                index
                for index, stems in enumerate(distinctive_predicates)
                if clause_stems.intersection(stems)
            }
            if any(
                participant_source != predicate_source
                for participant_source in participant_sources
                for predicate_source in predicate_sources
            ):
                return True
    return False


def _grounded_source_attributed_causal_reading(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Allow reporting a source's causal wording without claiming causation."""

    if (
        _SOURCE_ATTRIBUTED_CAUSAL_READING_PATTERN.search(claim_text or "")
        is None
        or _GLOBAL_SCOPE_PATTERN.search(claim_text or "")
        or _CATEGORY_PATTERN.search(claim_text or "")
    ):
        return False
    claim_tokens = {
        token.casefold()
        for token in re.findall(
            r"[^\W\d_]+",
            claim_text or "",
            re.UNICODE,
        )
        if len(token) >= 4
        and token.casefold() not in _SOURCE_READING_TOKEN_STOPWORDS
    }
    for fact in facts:
        if fact.fact_kind != "kwic_example":
            continue
        for sentences in _source_passage_sentence_units([fact]):
            causal_sentences = [
                sentence
                for sentence in sentences
                if _CAUSAL_ASSERTION_PATTERN.search(sentence)
            ]
            if not causal_sentences:
                continue
            causal_tokens = {
                token.casefold()
                for sentence in causal_sentences
                for token in re.findall(
                    r"[^\W\d_]+",
                    sentence,
                    re.UNICODE,
                )
                if len(token) >= 4
            }
            outside_tokens = {
                token.casefold()
                for sentence in sentences
                if sentence not in causal_sentences
                for token in re.findall(
                    r"[^\W\d_]+",
                    sentence,
                    re.UNICODE,
                )
                if len(token) >= 4
            } - causal_tokens
            if not claim_tokens.intersection(outside_tokens):
                return True
    return False


def _quote_is_user_scope_reference(
    segment: str,
    claim_text: str,
    question_text: str,
) -> bool:
    """Allow a quoted user term only as scope, never as claimed corpus evidence."""

    needle = normalisiere_zitat_fuer_vergleich(segment)
    claim = normalisiere_zitat_fuer_vergleich(claim_text)
    position = claim.find(needle) if needle else -1
    if position < 0:
        return False
    nearby = claim[
        max(0, position - 48) : position + len(needle) + 48
    ]
    # Die Regel selbst liegt in ``quote_rules``: derselbe Fragenbezug
    # entscheidet im Chokepoint der Politur, und die Vorfassung dort kannte
    # ihn gar nicht.
    return spanne_ist_fragenbezug(segment, nearby, question_text)


def _quote_is_negative_temporal_field_example(
    segment: str,
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Allow conventional field labels only inside an exact absence claim."""

    label = _normalise_quote_for_match(segment)
    if label not in {
        "date",
        "year",
        "time",
        "timestamp",
        "datum",
        "jahr",
        "zeit",
    }:
        return False
    if _NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN.search(claim_text or "") is None:
        return False
    return any(
        fact.fact_kind == "negative_result"
        and fact.exactness == "exact"
        and re.search(
            r"\b(?:zeitachse|datums?|jahres?|zeitfeld)\w*\b",
            _normalised_question_text(fact.statement),
        )
        for fact in facts
    )


def _quote_is_negative_lexical_rating_example(
    segment: str,
    claim_text: str,
    claim_kind: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Allow conventional rating words only when denying such a rating."""

    label = _normalise_quote_for_match(segment)
    if label not in {
        "hoch",
        "niedrig",
        "typisch",
        "moderat",
        "überdurchschnittlich",
        "unterdurchschnittlich",
    }:
        return False
    if claim_kind != "limitation":
        return False
    if not _is_lexical_reference_boundary_claim(claim_text):
        return False
    return any(
        fact.fact_kind == "distribution"
        and re.search(
            r"\b(?:ttr|sttr|mattr)\s*=",
            _joined_surface_text(
                [fact.statement, *fact.grounding_quotes]
            ),
            re.IGNORECASE,
        )
        for fact in facts
    )


def _joined_surface_text(lines: Sequence[str]) -> str:
    return " || ".join(_compact_text(line, 220) for line in lines if _compact_text(line, 220))


def _stronger_than_exactness(text: str, exactness_values: Sequence[str]) -> bool:
    lowered = text.lower()
    if any(value in {"partial", "sample_only", "top_n_only", "derived"} for value in exactness_values):
        # The downgrade heuristic keeps the broader weak-token set: when the
        # evidence is only partial/sampled, even a hedged "eher"/"deutlich"
        # framing is stronger than the exactness allows UNLESS the claim itself
        # is explicitly bounded to that visible subset. Exact comparisons among
        # visible Top-N rows remain valid; only their corpus-wide extrapolation
        # is forbidden.
        if (
            _WEAK_CATEGORY_PATTERN.search(lowered)
            and not _is_explicitly_bounded_claim(text)
        ):
            return True
    return False


def _unmeasured_partial_magnitude_claims(
    text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Find magnitude language that a retrieval slice cannot quantify alone."""

    if not any(
        fact.exactness in {"partial", "sample_only", "top_n_only", "derived"}
        for fact in facts
    ):
        return []
    matches = [
        match.group(0).strip()
        for match in _PARTIAL_MAGNITUDE_PATTERN.finditer(text or "")
        if match.group(0).strip()
    ]
    if not matches:
        return []
    if (
        _NUMERIC_PERCENT_PATTERN.search(text or "")
        or _RATIO_COMPARISON_PATTERN.search(text or "")
        or _NAMED_FREQUENCY_FACTOR_PATTERN.search(text or "")
        or _ELLIPTICAL_COUNT_COMPARISON_PATTERN.search(text or "")
        or _OPERATIONALISED_MAGNITUDE_PATTERN.search(text or "")
    ):
        return []
    return list(dict.fromkeys(matches))


def _has_definitive_global_scope_claim(text: str) -> bool:
    for clause in re.split(r";|(?<=[.!?])\s+", str(text or "")):
        if (
            _GLOBAL_SCOPE_PATTERN.search(clause)
            and _EPISTEMIC_SCOPE_LIMITATION_PATTERN.search(clause) is None
            and not (
                _TENTATIVE_THEME_PATTERN.search(clause)
                and _METHODOLOGICAL_TEST_INTENT_PATTERN.search(clause)
            )
        ):
            return True
    return False


def _is_explicitly_bounded_claim(text: str) -> bool:
    """Traegt der Satz eine Geltungsgrenze, die keine Ueberdehnung aufhebt.

    Die Funktion ist ein ENTSCHAERFER: liefert sie True, unterbleiben harte
    Regeln (``_shared`` 5375 und 6394, ``wordsketch`` 282,
    ``grounding_validation`` 2383, ``cross_tool_scope_missing``). Deshalb
    stehen zwei Vetos davor und nicht nur eins.

    ``_has_definitive_global_scope_claim`` faengt die korpusweite Geltung.
    ``_UEBERDEHNTE_REICHWEITE`` faengt die Woerter, die ueber jede Datenlage
    hinausgreifen und die das Global-Muster gerade NICHT kennt: generell,
    immer, beweist, im Deutschen. Gemessen am 2026-09-03 im Arbeitsbaum
    ergaben "In den 12 Zeilen zeigt sich generell ein Unterschied." und "Im
    sichtbaren Ausschnitt beweist sich der Unterschied." bounded=True bei
    global=False, und damit fiel ``cross_tool_scope_missing`` weg, obwohl
    beide Saetze genau die Reichweite behaupten, die die Regel verbieten
    soll. Ein Begrenzungsmarker entschuldigt kein "generell".
    """
    if not _BOUNDED_SCOPE_PATTERN.search(text or ""):
        return False
    if _UEBERDEHNTE_REICHWEITE.search(text or ""):
        return False
    return not _has_definitive_global_scope_claim(text)


def _fact_bound_values(fact: ObservedFact) -> set[str]:
    surface = _joined_surface_text(
        [fact.statement, *fact.grounding_quotes]
    )
    values: set[str] = set()
    for match in _FIELD_ASSIGNMENT_PATTERN.finditer(surface):
        field = _canonical_field_name(match.group(1))
        raw_value = match.group(3) or match.group(4) or ""
        value = _normalise_field_value(raw_value, field=field)
        if value and value not in {"true", "false", "null", "none"}:
            values.add(value)
    return values


def _clause_supporting_source_ids(
    clause: str,
    facts: Sequence[ObservedFact],
) -> set[str]:
    support: set[str] = set()
    assignments = list(_FIELD_ASSIGNMENT_PATTERN.finditer(clause or ""))
    quoted_segments = _extract_grounding_example_segments(clause)
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        supported_assignment = any(
            _normalise_field_value(
                match.group(3) or match.group(4) or "",
                field=_canonical_field_name(match.group(1)),
            )
            in _source_values_for_field(
                _canonical_field_name(match.group(1)),
                surface,
            )
            for match in assignments
        )
        assignment_anchor = (
            supported_assignment
            and not _unsupported_field_assignments(clause, surface)
        )
        literal_anchor = any(
            _literal_value_occurrences(clause, value)
            or _literal_value_occurs_in_compound(clause, value)
            for value in _fact_bound_values(fact)
        )
        quote_anchor = bool(quoted_segments) and all(
            any(
                _quoted_segment_is_supported(segment, quote_surface)
                for quote_surface in [
                    fact.statement,
                    *fact.grounding_quotes,
                ]
            )
            for segment in quoted_segments
        )
        if assignment_anchor or literal_anchor or quote_anchor:
            support.update(
                source_id
                for source_id in fact.source_evidence_ids
                if source_id
            )
    return support


def _supports_distinct_sources(
    clause_sources: Sequence[set[str]],
    *,
    minimum: int = 2,
) -> bool:
    usable = [sources for sources in clause_sources if sources]
    if len(usable) < minimum:
        return False

    def assign(index: int, used: set[str]) -> bool:
        if len(used) >= minimum:
            return True
        if index >= len(usable):
            return False
        for source_id in usable[index]:
            if source_id not in used and assign(
                index + 1,
                {*used, source_id},
            ):
                return True
        return assign(index + 1, used)

    return assign(0, set())


def _has_cross_source_literal_separation(
    text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    claim = str(text or "").strip()
    clauses = [
        clause.strip()
        for clause in re.split(
            r";|(?<=[.!?])\s+|"
            r"\s+\b(?:während|waehrend|hingegen|dagegen|"
            r"demgegenüber|demgegenueber)\b\s+",
            claim,
            flags=re.IGNORECASE,
        )
        if clause.strip()
    ]
    clause_sources = [
        _clause_supporting_source_ids(clause, facts)
        for clause in clauses
    ]
    if (
        len({source for sources in clause_sources for source in sources}) > 1
        and any(
            _CROSS_SOURCE_ANAPHORIC_JOIN_PATTERN.search(clause)
            for clause in clauses[1:]
        )
    ):
        return False
    # Every empirical observation clause must remain source-atomic. Repeating a
    # safe single-source clause later cannot repair an earlier implicit join.
    if any(len(sources) > 1 for sources in clause_sources):
        return False
    # A pure statement that the result spaces stay separate is safe. A fused
    # empirical clause cannot be laundered by appending that disclaimer.
    if (
        _SEPARATE_RESULT_SPACE_PATTERN.search(claim)
    ):
        return True
    if _supports_distinct_sources(
        clause_sources
    ):
        return True
    for pattern in (
        _CROSS_SOURCE_LITERAL_SEPARATION_PATTERN,
        _SEPARATE_RESULT_SPACE_PATTERN,
        _RESULT_SCOPE_CONTRAST_PATTERN,
    ):
        for match in pattern.finditer(claim):
            before = claim[: match.start()].strip(" \t,;:.!?")
            after = claim[match.end() :].strip(" \t,;:.!?")
            if _supports_distinct_sources(
                [
                    _clause_supporting_source_ids(before, facts),
                    _clause_supporting_source_ids(after, facts),
                ]
            ):
                return True
    return False


def _has_positive_extra_clause(text: str) -> bool:
    clauses = [
        clause.strip()
        for clause in re.split(
            r";|(?<=[.!?])\s+|,\s+(?=[A-ZÄÖÜ])",
            str(text or ""),
        )
        if clause.strip()
    ]
    method_clauses = {
        index
        for index, clause in enumerate(clauses)
        if _NEGATIVE_METHOD_CONCLUSION_PATTERN.search(clause)
    }
    return any(
        index not in method_clauses
        and _PURE_EPISTEMIC_NEGATION_PATTERN.search(clause) is None
        and _NEGATIVE_RESULT_POSITIVE_ASSERTION_PATTERN.search(clause)
        is not None
        for index, clause in enumerate(clauses)
    )


def _is_grounded_methodological_explanation(
    text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Allow method effects without treating them as empirical causation."""

    if (
        facts
        and _METHODOLOGICAL_TEST_INTENT_PATTERN.search(text or "")
        and _ANALYSIS_OPERATION_PATTERN.search(text or "")
        and _METHOD_PROPOSAL_MODALITY_PATTERN.search(text or "")
        and not _has_unnegated_pattern(
            text,
            _CROSS_TOOL_CAUSAL_PATTERN,
        )
    ):
        # Multiple visible findings may jointly motivate a future, explicitly
        # open test. That is a research design, not a claimed empirical join.
        return True
    if (
        facts
        and all(
            fact.fact_kind in {"negative_result", "limitation"}
            for fact in facts
        )
        and _METHOD_ONLY_NEGATIVE_CONCLUSION_PATTERN.search(text or "")
        and _NEGATIVE_METHOD_CONCLUSION_PATTERN.search(text or "")
        and not _has_positive_extra_clause(text)
    ):
        return True
    if not _METHODOLOGICAL_SCOPE_EXPLANATION_PATTERN.search(text or ""):
        return False
    surface = _joined_surface_text(
        [
            value
            for fact in facts
            for value in [fact.statement, *fact.grounding_quotes]
        ]
    )
    if _METHODOLOGICAL_SCOPE_EVIDENCE_PATTERN.search(surface):
        return True
    source_ids = {
        source_id
        for fact in facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    return (
        len(source_ids) > 1
        and _NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN.search(text or "") is not None
        and (
            _SEPARATE_RESULT_SPACE_PATTERN.search(text or "") is not None
            or _INCOMMENSURABLE_RESULTS_PATTERN.search(text or "") is not None
        )
    )


def _has_unnegated_pattern(
    text: str,
    pattern: re.Pattern[str],
) -> bool:
    segments = [
        segment.strip()
        for segment in re.split(
            r";|(?<=[.!?])\s+|"
            r"\s+\b(?:aber|jedoch|sondern|vielmehr|stattdessen)\b\s+",
            str(text or ""),
            flags=re.IGNORECASE,
        )
        if segment.strip()
    ]
    for segment in segments:
        negated_spans = [
            (match.start(), match.end())
            for match in _NEGATED_CAUSAL_RELATION_PATTERN.finditer(segment)
        ]
        for match in pattern.finditer(segment):
            overlaps_negation = any(
                match.start() < end and start < match.end()
                for start, end in negated_spans
            )
            discourse_cause = match.group(0).casefold() in {
                "aufgrund",
                "wegen",
            }
            if overlaps_negation or (
                discourse_cause and negated_spans
            ):
                continue
            return True
    return False


def _metadata_value_counts(
    facts: Sequence[ObservedFact],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for fact in facts:
        if fact.exactness != "exact":
            continue
        for quote in fact.grounding_quotes:
            match = _METADATA_VALUE_COUNT_QUOTE_PATTERN.fullmatch(
                str(quote or "").strip()
            )
            if match is None:
                continue
            field_name = match.group(1).strip()
            if not field_name:
                continue
            counts[field_name.casefold()] = int(match.group(2))
    return counts


def _metadata_fields_mentioned(
    claim_text: str,
    fields: Iterable[str],
) -> List[str]:
    lowered = str(claim_text or "").casefold()
    return [
        field_name
        for field_name in fields
        if re.search(
            rf"(?<!\w){re.escape(field_name.casefold())}(?!\w)",
            lowered,
        )
    ]


def _metadata_singleton_values(
    facts: Sequence[ObservedFact],
) -> Dict[str, List[str]]:
    counts = _metadata_value_counts(facts)
    values: Dict[str, List[str]] = {}
    for fact in facts:
        for quote in fact.grounding_quotes:
            match = re.fullmatch(
                r"values\[([^\]]+)\]=\[(.*)\]",
                str(quote or "").strip(),
            )
            if match is None:
                continue
            field_name = match.group(1).strip().casefold()
            if counts.get(field_name) != 1:
                continue
            visible = [
                value.strip()
                for value in re.findall(
                    r"['\"]([^'\"]+)['\"]",
                    match.group(2),
                )
                if value.strip()
            ]
            if visible:
                values[field_name] = visible
    return values


# --------------------------------------------------------------------------- #
# K3 Slice 3: mechanical POS/association/theme rules as PatternRule rows.
# --------------------------------------------------------------------------- #
_POS_GROUP_BY_PATTERN = re.compile(
    r"\bgroup_by\s*=\s*pos\b",
    re.IGNORECASE,
)
_LEXICAL_GROUP_BY_SURFACE_PATTERN = re.compile(
    r"\bgroup_by\s*=\s*(?:word|lemma)\b",
    re.IGNORECASE,
)
_ANY_GROUP_BY_SURFACE_PATTERN = re.compile(
    r"\bgroup_by\s*=\s*(?:word|lemma|pos)\b",
    re.IGNORECASE,
)
_POS_INDEPENDENT_SUPPORT_FACT_PATTERN = re.compile(
    r"\b(?:log_ratio|q_value|p_value|dispersion|"
    r"sentence_length|lexical_diversity|dependency)\s*=",
    re.IGNORECASE,
)
_STYLE_INDEPENDENT_SUPPORT_FACT_PATTERN = re.compile(
    r"\b(?:keyness|log_ratio|dispersion)\s*=",
    re.IGNORECASE,
)

_RULE_RAW_POS_INFERENCE = PatternRule(
    name="unsupported_raw_pos_inference",
    scan="search",
    claim_patterns=(
        _POS_INFERENCE_TARGET_PATTERN,
        _POS_INFERENCE_BRIDGE_PATTERN,
    ),
    exception_groups=((_METHODOLOGICAL_TEST_INTENT_PATTERN,),),
    evidence_checks=(
        ("surface_matches", {"pattern": _POS_GROUP_BY_PATTERN}),
        (
            "no_fact_support",
            {
                "fact_kinds": frozenset({"kwic_example"}),
                "supports": frozenset({"comparisons"}),
                "pattern": _POS_INDEPENDENT_SUPPORT_FACT_PATTERN,
            },
        ),
    ),
    reason="A raw POS profile alone supports no functional inference.",
)

_RULE_POS_INVENTORY_PROVENANCE = PatternRule(
    name="unsupported_pos_inventory_provenance",
    scan="search",
    claim_patterns=(_POS_INVENTORY_CLAIM_PATTERN,),
    evidence_checks=(
        ("surface_lacks", {"pattern": _POS_GROUP_BY_PATTERN}),
        ("surface_matches", {"pattern": _LEXICAL_GROUP_BY_SURFACE_PATTERN}),
    ),
    reason="Word rows are no POS-category inventory.",
)


def _unsupported_raw_pos_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(_RULE_RAW_POS_INFERENCE, claim_text, facts=facts)
    )


def _unsupported_pos_inventory_provenance(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Reject word rows described as a POS-category inventory."""

    affirmative_text = " ".join(
        clause.strip()
        for clause in re.split(r"(?<=[.!?])\s+|[;\n]+", claim_text or "")
        if clause.strip()
        and not _is_negative_or_unknown_limitation(
            clause,
            claim_kind="limitation",
        )
    )
    return bool(
        run_pattern_rule(
            _RULE_POS_INVENTORY_PROVENANCE,
            affirmative_text,
            facts=facts,
        )
    )


_NATURAL_POS_LABELS: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    (re.compile(r"\bpronomen\w*\b", re.IGNORECASE), frozenset({"PRON"})),
    (re.compile(r"\b(?:nomen|substantiv)\w*\b", re.IGNORECASE), frozenset({"NOUN"})),
    (re.compile(r"\beigennamen?\w*\b", re.IGNORECASE), frozenset({"PROPN"})),
    (re.compile(r"\bverben?\w*\b", re.IGNORECASE), frozenset({"VERB", "AUX"})),
    (re.compile(r"\badjektiv\w*\b", re.IGNORECASE), frozenset({"ADJ"})),
    (re.compile(r"\badverb\w*\b", re.IGNORECASE), frozenset({"ADV"})),
    (re.compile(r"\bdeterminat\w*\b", re.IGNORECASE), frozenset({"DET"})),
)


def _unsupported_natural_pos_label(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    required_tags = [
        tags
        for pattern, tags in _NATURAL_POS_LABELS
        if pattern.search(claim_text or "")
    ]
    if not required_tags or _METHODOLOGICAL_TEST_INTENT_PATTERN.search(
        claim_text or ""
    ):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    visible_tags = {
        match.group(1).upper()
        for match in re.finditer(
            r"\b(?:pos|label)\s*=\s*(NOUN|PROPN|VERB|AUX|ADJ|ADV|DET|PRON)\b",
            source_surface,
            re.IGNORECASE,
        )
    }
    # This guard protects an explicit tag from being mistranslated (for
    # example NOUN -> Pronomen). It does not ban ordinary, visibly bounded
    # grammatical interpretation of a KWIC passage that carries no POS tag.
    if not visible_tags:
        return False
    return any(tags.isdisjoint(visible_tags) for tags in required_tags)


_RULE_ABSOLUTE_ASSOCIATION_MAGNITUDE = PatternRule(
    name="unsupported_absolute_association_magnitude",
    scan="search",
    claim_patterns=(_ABSOLUTE_ASSOCIATION_MAGNITUDE_PATTERN,),
    exception_groups=(
        (_EXPLICIT_ASSOCIATION_MAGNITUDE_REFERENCE_PATTERN,),
    ),
    reason="Strong/weak association labels need a comparator or threshold.",
)


def _unsupported_absolute_association_magnitude(
    claim_text: str,
) -> bool:
    """Require a comparator or threshold for strong/weak association labels."""

    return bool(
        run_pattern_rule(_RULE_ABSOLUTE_ASSOCIATION_MAGNITUDE, claim_text)
    )


def _empty_collocation_profile_is_overread(
    claim_text: str,
    facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
    *,
    assertion_level: str = "qualified",
) -> bool:
    """Keep a thresholded zero-row result from becoming a linguistic fact."""

    if _EMPTY_COLLOCATION_PROFILE_OVERREAD_PATTERN.search(
        claim_text or ""
    ) is None:
        return False
    if _EMPTY_COLLOCATION_PARAMETER_BOUND_ZERO_PATTERN.search(
        claim_text or ""
    ):
        return False
    cited_sources = {
        source_id
        for fact in facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    if not cited_sources:
        return False
    zero_row_sources: set[str] = set()
    collocation_sources: set[str] = set()
    for fact in observed_facts:
        sources = {
            source_id
            for source_id in fact.source_evidence_ids
            if source_id
        }
        if not sources:
            continue
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        if re.search(
            r"\b(?:rows_seen|result_count)\s*=\s*0(?:\D|$)",
            surface,
            re.IGNORECASE,
        ):
            zero_row_sources.update(sources)
        if re.search(
            # kollokationsausgabe (Rohparameter-Fakt) ODER die linguistische
            # Floor-Formulierung (Kollokationsknoten/-liste, Haertung r4,
            # Fix 4) ODER der Werkzeugname.
            r"\b(?:kollokations(?:ausgabe|knoten|liste)|collocate_stats)\b",
            surface,
            re.IGNORECASE,
        ):
            collocation_sources.update(sources)
    zero_collocation_sources = zero_row_sources.intersection(
        collocation_sources
    )
    if not zero_collocation_sources:
        return False
    relevant_sources = zero_collocation_sources.intersection(cited_sources)
    if not relevant_sources:
        for fact in observed_facts:
            fact_sources = zero_collocation_sources.intersection(
                fact.source_evidence_ids
            )
            if not fact_sources:
                continue
            surface = _joined_surface_text(
                [fact.statement, *fact.grounding_quotes]
            )
            for match in re.finditer(
                # Stop at the surface-join separator "||" too: a requested_term
                # carried as a standalone grounding quote (linguistic floor
                # fact, Haertung r4) is "||"-joined, not ";"-separated like the
                # old method fact.
                r"\brequested_term\s*=\s*([^;,|\n]+)",
                surface,
                re.IGNORECASE,
            ):
                term = match.group(1).strip(" `\"'„“")
                if term and re.search(
                    rf"(?<!\w){re.escape(term)}(?!\w)",
                    claim_text or "",
                    re.IGNORECASE,
                ):
                    relevant_sources.update(fact_sources)
    if not relevant_sources:
        return False
    # A visibly tentative, testable explanation remains legitimate. The gate
    # blocks only the conversion of a thresholded empty table into a finding.
    if (
        assertion_level == "tentative"
        and (
            _HYPOTHESIS_PROPOSAL_PATTERN.search(claim_text or "")
            or _TENTATIVE_THEME_PATTERN.search(claim_text or "")
        )
        and _EMPTY_COLLOCATION_PROFILE_TEST_PATTERN.search(claim_text or "")
    ):
        return False
    return not (
        _ARTIFACT_QUALIFIER_PATTERN.search(claim_text or "")
        and _METHODOLOGICAL_TEST_INTENT_PATTERN.search(claim_text or "")
        and _EMPTY_COLLOCATION_PROFILE_TEST_PATTERN.search(claim_text or "")
    )


def _unsupported_collocation_pos_composition(
    claim_text: str,
    facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Do not turn surface collocates into an observed POS profile."""

    if _COLLOCATION_POS_COMPOSITION_PATTERN.search(claim_text or "") is None:
        return False
    selected_sources = {
        source_id
        for fact in facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    collocation_facts = [
        fact
        for fact in observed_facts
        if selected_sources.intersection(fact.source_evidence_ids)
    ]
    if not collocation_facts:
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in collocation_facts]
        + [
            quote
            for fact in collocation_facts
            for quote in fact.grounding_quotes
        ]
    )
    if re.search(
        r"\b(?:collocate_stats|kollokationsausgabe)\b",
        source_surface,
        re.IGNORECASE,
    ) is None:
        return False
    return re.search(
        r"\b(?:pos|upos|part_of_speech)\s*=",
        source_surface,
        re.IGNORECASE,
    ) is None


def _collocation_substitutes_for_discourse_function(
    claim_text: str,
) -> bool:
    return bool(
        _COLLOCATION_METHOD_MENTION_PATTERN.search(claim_text or "")
        and _DISCOURSE_FUNCTION_TARGET_PATTERN.search(claim_text or "")
        and _QUALITATIVE_CONTEXT_VALIDATION_PATTERN.search(
            claim_text or ""
        )
        is None
    )


def _facts_contain_relational_evidence(
    facts: Sequence[ObservedFact],
) -> bool:
    return any(
        fact.fact_kind == "kwic_example"
        or "comparisons" in fact.supports_claims
        or re.search(
            r"\b(?:kollokat\w*|co-?occurr\w*|kookkurr\w*|"
            r"doc(?:ument)?_coverage|document_count|dispersion)\b",
            "\n".join([fact.statement, *fact.grounding_quotes]),
            re.IGNORECASE,
        )
        is not None
        for fact in facts
    )


def _unsupported_platform_handle_label(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    question_text: str = "",
) -> bool:
    del question_text
    match = _PLATFORM_SPECIFIC_HANDLE_PATTERN.search(claim_text or "")
    if match is None:
        return False
    platform = re.split(r"[- ]", match.group(0), maxsplit=1)[0].casefold()
    claim_tokens = {
        token.casefold()
        for token in re.findall(r"@[A-Za-z0-9_]{2,64}", claim_text or "")
    }
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        ).casefold()
        if platform not in surface:
            continue
        if not claim_tokens or any(token in surface for token in claim_tokens):
            return False
    return True


def _unsupported_document_class_label(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    match = _DOCUMENT_CLASS_LABEL_PATTERN.search(claim_text or "")
    if match is None or _METHODOLOGICAL_TEST_INTENT_PATTERN.search(
        claim_text or ""
    ):
        return False
    raw_label = match.group("label").casefold()
    expected = "tweet" if raw_label.startswith("tweet") else "post"
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        if re.search(
            rf"\b(?:text_type|document_type|genre)\b[^|\n]{{0,100}}"
            rf"\b{expected}s?\b|\b{expected}s?\b[^|\n]{{0,100}}"
            rf"\b(?:text_type|document_type|genre)\b",
            surface,
            re.IGNORECASE,
        ):
            return False
    return True


def _unsupported_user_handle_identity(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    identity_match = _ASSERTED_USER_HANDLE_PATTERN.search(claim_text or "")
    if identity_match is None:
        return False
    if _OPEN_HANDLE_IDENTITY_TEST_PATTERN.search(claim_text or ""):
        return False
    if _DIRECT_HANDLE_QUALIFIER_PATTERN.search(claim_text or ""):
        return False

    claim_tokens = {
        token.casefold()
        for token in re.findall(r"@[A-Za-z0-9_]{2,64}", claim_text or "")
    }
    if not claim_tokens:
        source_surface = _joined_surface_text(
            [fact.statement for fact in facts]
            + [quote for fact in facts for quote in fact.grounding_quotes]
        )
        return re.search(
            r"\b(?:author|account|username|user_id|handle)\s*(?:=|:)",
            source_surface,
            re.IGNORECASE,
        ) is None

    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        ).casefold()
        for token in claim_tokens:
            value = re.escape(token.removeprefix("@"))
            if token not in surface:
                continue
            if re.search(
                rf"\b(?:author|account|username|user_id|handle)"
                rf"\s*(?:=|:)\s*['\"„“]?\s*@?{value}\b",
                surface,
                re.IGNORECASE,
            ):
                return False
    return True


def _followup_presupposes_effect_without_design(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if (
        _FOLLOWUP_PRESUPPOSED_EFFECT_PATTERN.search(claim_text or "") is None
        or _OPEN_EFFECT_QUESTION_PATTERN.search(claim_text or "")
        or _EXPLICIT_CAUSAL_DESIGN_PATTERN.search(claim_text or "")
    ):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return _EXPLICIT_CAUSAL_EVIDENCE_PATTERN.search(source_surface) is None


def _followup_presupposes_unobserved_relation(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if (
        _UNOBSERVED_RELATION_PRESUPPOSITION_PATTERN.search(
            claim_text or ""
        )
        is None
        or _OPEN_RELATION_TEST_PATTERN.search(claim_text or "")
        or _COLLOCATION_PROFILE_COMPARISON_PATTERN.search(
            claim_text or ""
        )
    ):
        return False
    return not _facts_contain_relational_evidence(facts)


def _absolute_counts_called_relative(claim_text: str) -> bool:
    return bool(
        _RELATIVE_FREQUENCY_PHRASE_PATTERN.search(claim_text or "")
        and _ABSOLUTE_F_VALUE_PATTERN.search(claim_text or "")
        and _RELATIVE_FREQUENCY_VALUE_PATTERN.search(claim_text or "") is None
    )


_RULE_REGISTER_THEME_INFERENCE = PatternRule(
    name="unsupported_register_theme_inference",
    scan="search",
    claim_patterns=(_REGISTER_PATTERN, _THEME_INFERENCE_PATTERN),
    evidence_checks=(("any_fact_kind", {"kind": "metadata"}),),
    exception_groups=(
        (_TENTATIVE_THEME_PATTERN, _THEME_VALIDATION_PATTERN),
    ),
    reason="Register metadata alone supports no theme inference.",
)


def _unsupported_register_theme_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(
            _RULE_REGISTER_THEME_INFERENCE, claim_text, facts=facts
        )
    )


def _followup_correlation_is_operationalised(claim_text: str) -> bool:
    if _CORRELATION_QUESTION_PATTERN.search(claim_text or "") is None:
        return True
    return _OBSERVATION_UNIT_PATTERN.search(claim_text or "") is not None


def _followup_mixes_aggregate_and_token_validation(
    claim_text: str,
) -> bool:
    return bool(
        _AGGREGATE_POS_MANUAL_AGREEMENT_PATTERN.search(
            claim_text or ""
        )
        and _PAIRED_TOKEN_LABEL_VALIDATION_PATTERN.search(
            claim_text or ""
        )
        is None
    )


def _followup_uses_sentence_length_as_complexity(
    claim_text: str,
) -> bool:
    return bool(
        _SENTENCE_LENGTH_COMPLEXITY_PATTERN.search(claim_text or "")
        and not _EXPLICIT_COMPLEXITY_PROXY_TEST_PATTERN.search(
            claim_text or ""
        )
    )


def _distribution_substitutes_for_thematic_analysis(
    claim_text: str,
) -> bool:
    return bool(
        _DISTRIBUTION_METHOD_PATTERN.search(claim_text or "")
        and (
            _THEMATIC_OR_SEMANTIC_REACH_PATTERN.search(claim_text or "")
            or _THEME_INFERENCE_PATTERN.search(claim_text or "")
            or _CONTEXTUAL_MEANING_PATTERN.search(claim_text or "")
        )
        and _EXPLICIT_CONTEXT_METHOD_PATTERN.search(claim_text or "")
        is None
    )


def _distribution_substitutes_for_function_analysis(
    claim_text: str,
) -> bool:
    return bool(
        _DISTRIBUTION_METHOD_PATTERN.search(claim_text or "")
        and _FUNCTION_OR_ROLE_TARGET_PATTERN.search(claim_text or "")
        and _EXPLICIT_CONTEXT_METHOD_PATTERN.search(claim_text or "") is None
    )


def _pos_inventory_substitutes_for_morphosyntax(
    claim_text: str,
) -> bool:
    return bool(
        _POS_INVENTORY_METHOD_PATTERN.search(claim_text or "")
        and _MORPHOSYNTACTIC_ANALYSIS_TARGET_PATTERN.search(
            claim_text or ""
        )
        and _EXPLICIT_SYNTACTIC_METHOD_PATTERN.search(claim_text or "")
        is None
    )


def _pos_filtered_lexicon_called_pos_distribution(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Distinguish a POS-filtered lexicon from counts grouped by POS."""

    if (
        _EXPLICIT_POS_DISTRIBUTION_CLAIM_PATTERN.search(
            claim_text or ""
        )
        is None
    ):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return bool(
        re.search(
            r"\bgroup_by\s*=\s*(?:word|lemma)\b",
            source_surface,
            re.IGNORECASE,
        )
        and re.search(
            r"\bpos\s*=\s*[A-Z][A-Z0-9_-]*\b",
            source_surface,
        )
        and re.search(
            r"\bgroup_by\s*=\s*pos\b",
            source_surface,
            re.IGNORECASE,
        )
        is None
    )


def _local_association_lacks_collocation_design(
    claim_text: str,
) -> bool:
    if _LOCAL_ASSOCIATION_GOAL_PATTERN.search(claim_text or "") is None:
        return False
    return not (
        _COLLOCATION_CONTEXT_UNIT_PATTERN.search(claim_text or "")
        and _ASSOCIATION_REFERENCE_PATTERN.search(claim_text or "")
    )


def _accounting_gap_lacks_token_reconciliation(
    claim_text: str,
) -> bool:
    return bool(
        _CATEGORY_SUM_TOTAL_GAP_PATTERN.search(claim_text or "")
        and _TOKEN_ACCOUNTING_METHOD_PATTERN.search(claim_text or "")
        is None
    )


def _lexical_absence_overreads_contextual_retrieval(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    assertion_level: str,
) -> bool:
    """Block substitution or author-intent claims from zero + Top-N context."""

    if _LEXICAL_SUBSTITUTION_PATTERN.search(claim_text or "") is None and (
        _INTENTIONAL_LEXICAL_AVOIDANCE_PATTERN.search(claim_text or "")
        is None
    ):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    has_exact_zero = bool(
        re.search(
            r"\b(?:total|count|frequency|f)\s*=\s*0(?:\.0+)?\b",
            source_surface,
            re.IGNORECASE,
        )
    )
    has_bounded_context = any(
        fact.fact_kind == "kwic_example"
        and fact.exactness in {"top_n_only", "sample_only", "partial"}
        for fact in facts
    )
    if not (has_exact_zero and has_bounded_context):
        return False
    if _INTENTIONAL_LEXICAL_AVOIDANCE_PATTERN.search(claim_text or ""):
        return True
    return not (
        assertion_level == "tentative"
        and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(claim_text or "")
    )


_RULE_GRAMMATICAL_PROFILE_INFERENCE = PatternRule(
    name="unsupported_grammatical_profile_inference",
    scan="search",
    claim_patterns=(
        _GRAMMATICAL_PROFILE_PATTERN,
        _STYLE_OR_TEXTTYPE_PATTERN,
        _STYLE_INFERENCE_BRIDGE_PATTERN,
    ),
    exception_groups=((_METHODOLOGICAL_TEST_INTENT_PATTERN,),),
    evidence_checks=(
        ("surface_matches", {"pattern": _ANY_GROUP_BY_SURFACE_PATTERN}),
        (
            "no_fact_support",
            {
                "fact_kinds": frozenset({"kwic_example"}),
                "supports": frozenset({"comparisons"}),
                "pattern": _STYLE_INDEPENDENT_SUPPORT_FACT_PATTERN,
            },
        ),
    ),
    reason="A frequency profile alone supports no style inference.",
)


def _unsupported_grammatical_profile_inference(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    return bool(
        run_pattern_rule(
            _RULE_GRAMMATICAL_PROFILE_INFERENCE, claim_text, facts=facts
        )
    )


def _result_is_mislabeled_as_sample(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _CURRENT_RESULT_AS_SAMPLE_PATTERN.search(claim_text or "") is None:
        return False
    if any(fact.exactness == "sample_only" for fact in facts):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    if all(
        re.search(rf"\b{field}\s*=", source_surface, re.IGNORECASE)
        for field in ("requested", "drawn", "seed")
    ):
        return False
    return bool(facts)


_DECLARED_SAMPLE_CARDINALITY_PATTERN = re.compile(
    rf"\bstichprobe\s*(?:umfasst|enthält|enthaelt|hat|:|=)\s*"
    rf"(?P<count>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
    r"(?:sichtbar\w*\s+|geliefert\w*\s+|gezogen\w*\s+|"
    r"zurückgegeben\w*\s+|zurueckgegeben\w*\s+){0,3}"
    r"(?:(?:kwic|konkordanz)[-‑ ]?)?"
    r"(?:zeilen?|belege?|beispiele?|treffer)\b|"
    rf"\b(?P<count_before>{_NUMBER_WORD_TOKEN_SOURCE}|\d+)\s+"
    r"(?:sichtbar\w*\s+|geliefert\w*\s+|gezogen\w*\s+|"
    r"zurückgegeben\w*\s+|zurueckgegeben\w*\s+){0,3}"
    r"(?:(?:kwic|konkordanz)[-‑ ]?)?"
    r"(?:zeilen?|belege?|beispiele?|treffer)\b[^.!?\n]{0,40}"
    r"\b(?:bilden|sind|ergeben)\s+(?:die|eine)\s+stichprobe\b",
    re.IGNORECASE,
)


def _declared_sample_cardinality_is_wrong(
    claim_text: str,
    facts: Sequence[ObservedFact],
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Bind an asserted full sample size to the tool's sampling provenance."""

    match = _DECLARED_SAMPLE_CARDINALITY_PATTERN.search(claim_text or "")
    if match is None:
        return False
    raw_count = match.group("count") or match.group("count_before") or ""
    claimed = (
        raw_count
        if raw_count.isdigit()
        else _number_word_value(raw_count)
    )
    if claimed is None:
        return False
    source_ids = {
        source_id
        for fact in facts
        for source_id in fact.source_evidence_ids
        if source_id
    }
    scope_facts = [
        fact
        for fact in observed_facts
        if not source_ids
        or source_ids.intersection(fact.source_evidence_ids)
    ]
    surface = _joined_surface_text(
        [fact.statement for fact in scope_facts]
        + [
            quote
            for fact in scope_facts
            for quote in fact.grounding_quotes
        ]
    )
    drawn = _field_numeric_values(surface, ("drawn",))
    return len(drawn) == 1 and claimed not in drawn


def _local_cooccurrence_anchors(claim_text: str) -> set[str]:
    if _LOCAL_COOCCURRENCE_QUESTION_PATTERN.search(claim_text or "") is None:
        return set()
    explicit_anchors = {
        _normalised_question_text(match.group("term"))
        for match in _FOCAL_NODE_PATTERN.finditer(claim_text or "")
        if _normalised_question_text(match.group("term"))
    }
    quoted_anchors = {
        _normalised_question_text(segment)
        for segment in _extract_quoted_segments(claim_text or "")
        if _normalised_question_text(segment)
    }
    return explicit_anchors | quoted_anchors


def _overview_observation_is_provenance_only(
    facts: Sequence[ObservedFact],
) -> bool:
    if not facts:
        return False
    for fact in facts:
        if fact.fact_kind == "limitation":
            continue
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        corpus_size_only = (
            fact.fact_kind == "count"
            and re.search(
                r"\b(?:corpus_tokens|gesamtkorpusgröße|"
                r"gesamtkorpusgroesse|normalisierungsnenner)\b",
                surface,
                re.IGNORECASE,
            )
            is not None
            and re.search(r"\b(?:row|word|lemma|pos)\[\d+\]", surface) is None
        )
        result_shape_only = (
            re.search(r"\brows_seen\s*=", surface, re.IGNORECASE) is not None
            and re.search(
                r"\btotal\s*=\s*\d+\s+kategorien\b",
                surface,
                re.IGNORECASE,
            )
            is not None
            and re.search(r"\b(?:row|word|lemma|pos)\[\d+\]", surface) is None
        )
        if not (corpus_size_only or result_shape_only):
            return False
    return True


def _method_step_text_ordinal(claim_text: str) -> int | None:
    match = _METHOD_STEP_TEXT_ORDINAL_PATTERN.search(claim_text or "")
    if match is None:
        return None
    token = match.group("ordinal").casefold()
    for stem, value in _METHOD_STEP_ORDINAL_VALUES.items():
        if token.startswith(stem):
            return value
    return None


def _strip_redundant_method_step_ordinal(claim_text: str) -> str:
    """Drop a leading ordinal because the renderer numbers method steps."""

    original = str(claim_text or "").strip()
    stripped = _LEADING_METHOD_STEP_ORDINAL_PATTERN.sub(
        "",
        original,
        count=1,
    ).strip()
    if not stripped or stripped == original:
        return original
    if re.match(
        r"^(?:sollte|soll|könnte|koennte|kann|wird|werden)\b",
        stripped,
        re.IGNORECASE,
    ):
        return "Es " + stripped
    if re.match(r"^(?:wäre|waere)\b", stripped, re.IGNORECASE):
        return "Empfohlen " + stripped
    if re.match(r"^ist\b", stripped, re.IGNORECASE):
        return re.sub(
            r"^ist\b",
            "Empfohlen ist",
            stripped,
            count=1,
            flags=re.IGNORECASE,
        )
    if re.match(
        r"^(?:besteht|umfasst|beinhaltet)\b",
        stripped,
        re.IGNORECASE,
    ):
        return "Der Schritt " + stripped
    if re.match(
        r"^empfiehlt\s+sich\s+als\b",
        stripped,
        re.IGNORECASE,
    ):
        return re.sub(
            r"^empfiehlt\s+sich\b",
            "Dies empfiehlt sich",
            stripped,
            count=1,
            flags=re.IGNORECASE,
        )
    return stripped[:1].upper() + stripped[1:]


def _claim_mentions_specific_fact_anchor(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    anchors = {
        value
        for fact in facts
        for value in _fact_bound_values(fact)
        if value
        and value not in {"true", "false", "null", "none"}
        and not (
            value.isdigit()
            and int(value) <= 3
        )
    }
    if not anchors:
        return True
    if any(
        _literal_value_occurrences(claim_text, anchor)
        or _literal_value_occurs_in_compound(claim_text, anchor)
        for anchor in anchors
    ):
        return True
    claim_tokens = set(_semantic_theme_tokens(claim_text))
    return any(
        claim_tokens.intersection(
            _semantic_theme_tokens(
                " ".join(
                    [
                        fact.statement,
                        *fact.grounding_quotes,
                    ]
                )
            )
        )
        for fact in facts
        if fact.fact_kind == "kwic_example"
    )


def _claim_has_structural_fact_anchor(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _followup_changes_analysis_scope(claim_text):
        return True
    if (
        _FOLLOWUP_RANKING_CONTEXT_PATTERN.search(claim_text or "")
        and any("ranks" in fact.supports_claims for fact in facts)
    ):
        return True
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    if (
        re.search(
            r"\b(?:pos|part[- ]?of[- ]?speech|wortart)\w*\b"
            r"[^.!?\n]{0,100}\b(?:verteil\w*|frequenz\w*|inventar\w*|"
            r"kategor\w*|bestandsaufnahme)\b"
            r"|"
            r"\b(?:verteil\w*|frequenz\w*|inventar\w*|kategor\w*|"
            r"bestandsaufnahme)\b[^.!?\n]{0,100}"
            r"\b(?:pos|part[- ]?of[- ]?speech|wortart)\w*\b",
            claim_text or "",
            re.IGNORECASE,
        )
        and re.search(r"\bgroup_by\s*=\s*pos\b", source_surface, re.IGNORECASE)
    ):
        return True
    if (
        re.search(
            r"\b(?:frequenz\w*|häufigkeit\w*|haeufigkeit\w*|"
            r"top[- ]?n|rangliste\w*)\b",
            claim_text or "",
            re.IGNORECASE,
        )
        and any(
            {"counts", "ranks"}.intersection(fact.supports_claims)
            for fact in facts
        )
    ):
        return True
    if (
        re.search(r"\bmetadaten\w*\b", claim_text or "", re.IGNORECASE)
        and any(fact.fact_kind == "metadata" for fact in facts)
    ):
        return True
    return bool(
        re.search(
            r"\b(?:kwic|kollokationsanalyse|kollokationsstatistik)\b",
            claim_text or "",
            re.IGNORECASE,
        )
        and any(
            re.search(
                r"\bsemantisch\w*\s+(?:treffer|retrieval)\b",
                fact.statement,
                re.IGNORECASE,
            )
            for fact in facts
        )
    )


def _merges_cross_result_rankings(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if not _CROSS_RESULT_RANKING_PATTERN.search(claim_text or ""):
        return False
    ranking_sources = {
        source_id
        for fact in facts
        if (
            "ranks" in fact.supports_claims
            or _source_values_for_field(
                "rank",
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                ),
            )
            or (
                fact.exactness == "top_n_only"
                and re.search(
                    r"\b(?:frequenzzeile|rang(?:liste|folge)?)\b|"
                    r"\brow\[\d+\]",
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                    re.IGNORECASE,
                )
                is not None
            )
        )
        for source_id in fact.source_evidence_ids
        if source_id
    }
    if len(ranking_sources) < 2:
        return False
    if _SEPARATE_RESULT_SPACE_PATTERN.search(claim_text or ""):
        return False
    scoped_results = _RESULT_SCOPE_MARKER_PATTERN.findall(claim_text or "")
    if (
        len(scoped_results) >= 2
        and _RESULT_SCOPE_CONTRAST_PATTERN.search(claim_text or "")
    ):
        return False
    return True


def _followup_reasks_known_singleton_axis(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    if _followup_changes_analysis_scope(claim_text):
        return []
    if _EXPLICIT_SINGLETON_SCOPE_CLOSURE_PATTERN.search(
        claim_text or ""
    ):
        return []
    counts = _metadata_value_counts(facts)
    singleton_fields = [
        field_name for field_name, count in counts.items() if count == 1
    ]
    direct_fields = (
        _metadata_fields_mentioned(claim_text, singleton_fields)
        if _FOLLOWUP_METADATA_AXIS_PATTERN.search(claim_text or "")
        else []
    )
    distribution_fields: List[str] = []
    if re.search(r"\bverteil\w*\b", claim_text or "", re.IGNORECASE):
        for field_name in _metadata_fields_mentioned(
            claim_text,
            singleton_fields,
        ):
            field = rf"['\"`]?{re.escape(field_name)}['\"`]?"
            if re.search(
                rf"(?:\bverteil\w*\b[^.!?\n]{{0,80}}"
                rf"(?:\b(?:nach|über|ueber|zwischen|je|pro)\b"
                rf"[^.!?\n]{{0,24}}{field}|"
                rf"\b(?:von|der|des)\s+{field})|"
                rf"{field}[-_ ]?\s*verteil\w*)",
                claim_text or "",
                re.IGNORECASE,
            ):
                distribution_fields.append(field_name)
    direct_fields = list(
        dict.fromkeys([*direct_fields, *distribution_fields])
    )
    if not (
        _SINGLETON_DISTINCTIVENESS_PATTERN.search(claim_text or "")
        and (
            not _EXPLICIT_NEW_COMPARATOR_PATTERN.search(claim_text or "")
            or _SELF_CORPUS_COMPARATOR_PATTERN.search(claim_text or "")
        )
    ):
        return direct_fields
    lowered = str(claim_text or "").casefold()
    value_fields = [
        field_name
        for field_name, values in _metadata_singleton_values(facts).items()
        if any(
            re.search(
                rf"(?<!\w){re.escape(value.casefold())}(?!\w)",
                lowered,
            )
            for value in values
        )
    ]
    return list(dict.fromkeys([*direct_fields, *value_fields]))


def _followup_reasks_settled_denominator_scope(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _followup_changes_analysis_scope(claim_text):
        return False
    if not _FOLLOWUP_SETTLED_DENOMINATOR_SCOPE_PATTERN.search(claim_text or ""):
        return False
    return any(
        fact.exactness == "exact"
        and any(
            re.fullmatch(
                r"denominator_scope=(?:corpus|docset)",
                str(quote or "").strip(),
                re.IGNORECASE,
            )
            for quote in fact.grounding_quotes
        )
        for fact in facts
    )


def _followup_changes_analysis_scope(claim_text: str) -> bool:
    """A new corpus or denominator makes a superficially repeated question new."""

    return _FOLLOWUP_SCOPE_CHANGE_PATTERN.search(claim_text or "") is not None


def _followup_confuses_context_with_reranking(claim_text: str) -> bool:
    if not _FOLLOWUP_RANKING_CONTEXT_PATTERN.search(claim_text or ""):
        return False
    if not _FOLLOWUP_RERANK_INTENT_PATTERN.search(claim_text or ""):
        return False
    if _FOLLOWUP_CONTEXT_CHANGE_TARGET_PATTERN.search(claim_text or ""):
        return False
    return not _FOLLOWUP_CONTROLLED_RERANK_PATTERN.search(claim_text or "")


def _presupposes_unseen_document_groups(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _DOCUMENT_GROUP_PRESUPPOSITION_PATTERN.search(claim_text or "") is None:
        return False
    if _CONDITIONAL_AVAILABILITY_PATTERN.search(claim_text or ""):
        return False
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return re.search(
        r"\b(?:available_fields|field|values|value_count)\s*=|"
        r"\b(?:register|subcorpus|subkorpus|document_group)\s*=",
        source_surface,
        re.IGNORECASE,
    ) is None


def _uses_collocation_as_syntax_method(claim_text: str) -> bool:
    return bool(
        _COLLOCATION_SYNTAX_GOAL_PATTERN.search(claim_text or "")
        and not _EXPLICIT_SYNTACTIC_METHOD_PATTERN.search(claim_text or "")
    )


def _pos_filtered_handle_anomalies(
    facts: Sequence[ObservedFact],
) -> Dict[str, set[str]]:
    result: Dict[str, set[str]] = {}
    for fact in facts:
        surface = _joined_surface_text(
            [fact.statement, *fact.grounding_quotes]
        )
        if (
            re.search(
                r"\bpos\s*=\s*(?:NOUN|PROPN|VERB|ADJ|ADV|DET|PRON|AUX|X)\b",
                surface,
                re.IGNORECASE,
            )
        ):
            handles = {
                handle.casefold()
                for handle in re.findall(
                    r"@[A-Za-z0-9_]{2,64}",
                    surface,
                )
            }
            if handles:
                result[fact.id] = handles
    return result


def _pos_filtered_handle_fact_ids(
    facts: Sequence[ObservedFact],
) -> set[str]:
    return set(_pos_filtered_handle_anomalies(facts))


def _is_data_quality_followup(
    claim: ClaimDraft,
    anomalies_by_fact: Dict[str, set[str]],
) -> bool:
    return bool(
        claim.claim_kind == "followup"
        and set(anomalies_by_fact).intersection(claim.fact_ids)
        and _DATA_QUALITY_METHOD_PATTERN.search(claim.text or "")
    )


def _is_systematic_data_quality_followup(
    claim: ClaimDraft,
    anomalies_by_fact: Dict[str, set[str]],
) -> bool:
    referenced_handles = {
        handle
        for fact_id in claim.fact_ids
        for handle in anomalies_by_fact.get(fact_id, set())
    }
    return bool(
        _is_data_quality_followup(claim, anomalies_by_fact)
        and (
            len(referenced_handles) >= 2
            or _SYSTEMATIC_DATA_QUALITY_PATTERN.search(claim.text or "")
        )
    )


def _is_primary_data_quality_followup(claim: ClaimDraft) -> bool:
    return bool(
        claim.claim_kind == "followup"
        and _DATA_QUALITY_METHOD_PATTERN.search(claim.text or "")
        and _PRIMARY_DATA_QUALITY_FOLLOWUP_PATTERN.search(claim.text or "")
    )


def _uses_technical_partition_as_content_axis(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    qa_framed = bool(
        _PARTITION_QA_FRAMING_PATTERN.search(claim_text or "")
        or (
            _PARTITION_QA_MEASUREMENT_PATTERN.search(claim_text or "")
            and _PARTITION_QA_OPERATION_PATTERN.search(claim_text or "")
        )
    )
    if (
        _TECHNICAL_PARTITION_MENTION_PATTERN.search(claim_text or "") is None
        or _PARTITION_CONTENT_COMPARISON_PATTERN.search(claim_text or "") is None
        or qa_framed
    ):
        return False
    return any(
        "technische Datenaufteilung" in fact.statement
        or any(
            "technisch" in limitation.lower()
            and (
                "partition" in limitation.lower()
                or "aufteilung" in limitation.lower()
            )
            for limitation in fact.limitations
        )
        for fact in facts
    )


def _near_duplicate_research_question(left: str, right: str) -> bool:
    left_anchors = _local_cooccurrence_anchors(left)
    right_anchors = _local_cooccurrence_anchors(right)
    if left_anchors and left_anchors.intersection(right_anchors):
        return True

    left_normalised = _normalised_question_text(left)
    right_normalised = _normalised_question_text(right)
    if (
        min(len(left_normalised), len(right_normalised)) >= 48
        and SequenceMatcher(
            None,
            left_normalised,
            right_normalised,
            autojunk=False,
        ).ratio()
        >= 0.84
    ):
        return True

    def tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(
                r"[a-zäöüß]{3,}",
                _normalised_question_text(text),
            )
        }

    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if min(len(left_tokens), len(right_tokens)) < 6:
        return False
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return bool(union and overlap / union >= 0.78)


def _has_positive_partition_purpose_claim(text: str) -> bool:
    clauses = re.split(
        r"(?<=[.!?;])\s+|,\s+(?=(?:aber|jedoch|ohne|wobei|"
        r"während|waehrend)\b)",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    for sentence in clauses:
        if (
            _PARTITION_PURPOSE_PATTERN.search(sentence)
            and not _NEGATED_PURPOSE_PATTERN.search(sentence)
        ):
            return True
    return False


def _range_is_covered_by_numbers(
    range_token: str,
    allowed_numbers: set[str],
) -> bool:
    match = re.fullmatch(
        r"(\d+)(?:-|–|bis)(\d+)",
        re.sub(r"\s+", "", str(range_token or "").lower()),
    )
    if match is None:
        return False
    start, end = (int(match.group(1)), int(match.group(2)))
    if end < start or end - start > 100:
        return False
    return all(str(value) in allowed_numbers for value in range(start, end + 1))


def _is_rank_range_claim(text: str) -> bool:
    return bool(
        _has_word_range_claim(text)
        or (
            _extract_ranges(text)
            and _RANK_RANGE_CONTEXT_PATTERN.search(text or "")
        )
    )


def _is_negative_or_unknown_limitation(
    text: str,
    *,
    claim_kind: str,
) -> bool:
    """Recognise an atomic limitation rather than an affirmative claim."""

    return (
        claim_kind == "limitation"
        and _NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN.search(text or "") is not None
    )


def _is_authoritative_evidence_item(item: EvidenceItem) -> bool:
    return item.tool not in set(NON_AUTHORITATIVE_GROUNDING_TOOLS)


_MODEL_FACT_FUNCTION_WORDS = {
    "a",
    "als",
    "am",
    "an",
    "and",
    "auf",
    "aus",
    "bei",
    "das",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "ein",
    "eine",
    "einer",
    "eines",
    "for",
    "für",
    "fuer",
    "im",
    "in",
    "is",
    "ist",
    "mit",
    "of",
    "on",
    "the",
    "to",
    "und",
    "von",
    "weist",
    "zu",
}
_MODEL_FACT_SCAFFOLD_PREFIXES = (
    "ausgabe",
    "beispiel",
    "beobacht",
    "beträg",
    "betraeg",
    "dokument",
    "enthält",
    "enthaelt",
    "ergebnis",
    "erscheint",
    "evidenz",
    "fakt",
    "feld",
    "grounding",
    "kwic",
    "lautet",
    "liste",
    "metrik",
    "passage",
    "rang",
    "sichtbar",
    "statement",
    "tool",
    "treffer",
    "wert",
    "zeig",
    "zeile",
)


def _model_fact_content_terms(text: str) -> List[str]:
    token_pattern = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
    terms: List[str] = []
    for token in token_pattern.findall(text or ""):
        lowered = token.casefold()
        if (
            len(lowered) <= 2
            or lowered in _MODEL_FACT_FUNCTION_WORDS
            or any(
                lowered.startswith(prefix)
                for prefix in _MODEL_FACT_SCAFFOLD_PREFIXES
            )
        ):
            continue
        terms.append(lowered)
    return list(dict.fromkeys(terms))


def _unsupported_model_fact_terms(fact: ObservedFact) -> List[str]:
    """Reject content words introduced only by an untrusted fact statement."""

    if not fact._untrusted_model_fact:
        return []
    evidence_terms = {
        term
        for quote in fact.grounding_quotes
        for term in _model_fact_content_terms(str(quote or ""))
    }
    return [
        term
        for term in _model_fact_content_terms(fact.statement)
        if term not in evidence_terms
    ]


def _nonpositive_only_claim_has_positive_assertion(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if not facts or any(
        fact.fact_kind not in {"negative_result", "limitation"}
        for fact in facts
    ):
        return False
    if all(
        fact.fact_kind == "limitation"
        and
        not fact._untrusted_model_fact
        and "interpretation_anchor" in fact.supports_claims
        for fact in facts
    ):
        # A deterministic fact may explicitly expose its bounded content as an
        # interpretation anchor. The semantic verifier still evaluates the
        # paraphrase; this guard only avoids treating every non-negative word
        # as smuggled positive corpus evidence.
        return False
    clauses = [
        clause.strip()
        for clause in re.split(
            r";|(?<=[.!?])\s+|,\s+(?=[A-ZÄÖÜ])|"
            r"\s+und\s+(?=[A-ZÄÖÜ][\w-]*\s+(?:nicht|kein))",
            _prose_outside_examples(claim_text),
        )
        if clause.strip()
    ]
    return any(
        (
            _NEGATIVE_RESULT_POSITIVE_ASSERTION_PATTERN.search(clause)
            or _CATEGORY_PATTERN.search(clause)
        )
        and _NEGATIVE_OR_UNKNOWN_CLAIM_PATTERN.search(clause) is None
        for clause in clauses
    )


def _safe_multi_field_statement_frame(text: str) -> bool:
    """Allow harmless prose around an otherwise explicit field record."""

    if re.fullmatch(r"[\s,;:.()/-]*", text or "") is not None:
        return True
    return (
        re.fullmatch(
            r"[\s,;:.()/-]*"
            r"(?:(?:die|der|das)\s+)?"
            r"(?:(?:sichtbar(?:e|en|er|es)?|vorliegend(?:e|en|er|es)?|"
            r"belegt(?:e|en|er|es)?)\s+)*"
            r"(?:werte?|angaben?|kennzahlen?)"
            r"(?:\s+(?:lauten|sind))?"
            r"[\s,;:.()/-]*",
            text or "",
            re.IGNORECASE,
        )
        is not None
    )


def _model_fact_has_atomic_quote_support(fact: ObservedFact) -> bool:
    """Require one quote to preserve every binding made by a model fact.

    Union-level token checks allow a model to splice ``Haus`` from one row
    together with ``f=5`` from another. Observed facts are atomic evidence, not
    synthesis; cross-row interpretation happens later in ClaimDrafts.
    """

    if not fact._untrusted_model_fact:
        return True
    required_terms = set(_model_fact_content_terms(fact.statement))
    required_numbers = set(_extract_numeric_tokens(fact.statement))
    required_ranges = set(_extract_ranges(fact.statement))
    required_segments = _extract_grounding_example_segments(fact.statement)
    for quote in fact.grounding_quotes:
        quote_text = str(quote or "")
        quote_terms = set(_model_fact_content_terms(quote_text))
        if not required_terms <= quote_terms:
            continue
        allowed_numbers = set(_extract_numeric_tokens(quote_text))
        if any(
            not _numeric_token_is_supported(token, allowed_numbers)
            for token in required_numbers
        ):
            continue
        allowed_ranges = set(_extract_ranges(quote_text))
        if any(
            range_token not in allowed_ranges
            and not _range_is_covered_by_numbers(
                range_token,
                allowed_numbers,
            )
            for range_token in required_ranges
        ):
            continue
        if any(
            not _quoted_segment_is_supported(segment, quote_text)
            for segment in required_segments
        ):
            continue
        if _unsupported_field_assignments(fact.statement, quote_text):
            continue
        return True
    # Multiple top-level fields from one result (for example ``total=12`` and
    # ``corpus_tokens=1000``) are a safe atomic record when the statement keeps
    # their explicit field bindings. Row/table snippets remain single-quote
    # only so values from different observations cannot be spliced together.
    row_scoped_quote = re.compile(
        r"^(?:row|metric|kwic|table\[[^\]]+\])\[\d+\]",
        re.IGNORECASE,
    )
    assignment_matches = list(
        _FIELD_ASSIGNMENT_PATTERN.finditer(fact.statement)
    )
    assignment_fields = {
        match.group(1).casefold() for match in assignment_matches
    }
    assignment_remainder = _FIELD_ASSIGNMENT_PATTERN.sub(
        "",
        fact.statement,
    )
    assignment_remainder = re.sub(
        r"\b(?:und|and)\b",
        "",
        assignment_remainder,
        flags=re.IGNORECASE,
    )
    if (
        len(fact.source_evidence_ids) == 1
        and len(assignment_matches) >= 2
        and not assignment_fields.intersection(_ROW_SCOPED_FIELD_NAMES)
        and _safe_multi_field_statement_frame(assignment_remainder)
        and not any(
            row_scoped_quote.search(str(quote or "").strip())
            for quote in fact.grounding_quotes
        )
        and not _unsupported_field_assignments(
            fact.statement,
            _joined_surface_text(fact.grounding_quotes),
        )
    ):
        return True
    return False


def _sanitise_model_fact_contract(
    fact: ObservedFact,
    referenced_items: Sequence[EvidenceItem],
) -> None:
    """Derive support metadata for an already quote-validated model fact.

    The model may propose statement wording and fact kind, but it does not get
    to self-certify population scope or supported claim classes. Those are
    derived here from the authoritative evidence shape after exact quotes,
    numbers and ranges have passed validation.
    """

    if not fact._untrusted_model_fact:
        return

    any_truncated = any(item.truncated for item in referenced_items)
    if any_truncated:
        fact.exactness = (
            "top_n_only"
            if fact.fact_kind in {"ranked_row", "distribution"}
            else "partial"
        )
    elif fact.fact_kind == "kwic_example":
        fact.exactness = "sample_only"
    elif fact.fact_kind == "ranked_row":
        fact.exactness = "top_n_only"
    elif fact.exactness not in EXACTNESS_VALUES:
        fact.exactness = "derived"

    surface = _joined_surface_text(
        [fact.statement, *fact.grounding_quotes]
    )
    supports: List[str] = []
    if (
        fact.fact_kind in {"count", "pmw", "ranked_row", "distribution"}
        and _extract_numeric_tokens(surface)
    ):
        supports.append("counts")
    if fact.fact_kind in {"kwic_example", "ranked_row"}:
        supports.append("examples")
    if fact.fact_kind == "ranked_row":
        supports.append("ranks")
    if fact.fact_kind == "distribution" and _PERCENT_PATTERN.search(surface):
        supports.append("percentages")
    if fact.fact_kind in {
        "kwic_example",
        "ranked_row",
        "distribution",
        "metadata",
        "negative_result",
    }:
        supports.append("interpretation_anchor")
    fact.supports_claims = list(dict.fromkeys(supports))


def _violates_forbidden_claim(
    claim_text: str,
    forbidden_claims: Sequence[str],
    facts: Sequence[ObservedFact],
    *,
    claim_kind: str,
    assertion_level: str = "",
    scope_terms: Sequence[str] = (),
    question_text: str = "",
) -> List[str]:
    lowered_text = str(claim_text or "").lower()
    lowered_forbidden = {str(item or "").strip().lower() for item in forbidden_claims if str(item or "").strip()}
    reasons: List[str] = []
    support_values = {support for fact in facts for support in fact.supports_claims}
    exactness_values = {fact.exactness for fact in facts}
    negative_or_unknown_limitation = _is_negative_or_unknown_limitation(
        claim_text,
        claim_kind=claim_kind,
    )
    existential_kwic_evidence = _is_existential_kwic_evidence_claim(
        claim_text,
        facts,
    )
    grounded_limitation = (
        claim_kind == "limitation"
        and any(fact.fact_kind == "limitation" for fact in facts)
    )
    grounded_testable_hypothesis = bool(
        claim_kind == "interpretation"
        and assertion_level == "tentative"
        and "interpretation_anchor" in support_values
        and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(claim_text or "")
    )
    quote_surfaces = [
        line
        for fact in facts
        for line in [fact.statement, *fact.grounding_quotes]
        if str(line or "").strip()
    ]
    if (
        "unsupported counts" in lowered_forbidden
        and (
            _has_digit_count_claim(lowered_text)
            or _has_word_count_claim(lowered_text)
        )
        and "counts" not in support_values
        and not negative_or_unknown_limitation
        and not existential_kwic_evidence
    ):
        reasons.append("Der Vertrag verbietet unbelegte Count-Claims.")
    if (
        "unsupported rank ranges" in lowered_forbidden
        and _is_rank_range_claim(lowered_text)
        and "ranks" not in support_values
    ):
        reasons.append("Der Vertrag verbietet unbelegte Rangbereichs-Claims.")
    if (
        "unsupported examples" in lowered_forbidden
        and any(
            not any(
                _quoted_segment_is_supported(segment, quote_surface)
                for quote_surface in quote_surfaces
            )
            and all(
                _normalise_quote_for_match(segment)
                != _normalise_quote_for_match(scope_term)
                for scope_term in scope_terms
                if scope_term
            )
            and not _quote_is_user_scope_reference(
                segment,
                claim_text,
                question_text,
            )
            and not _quote_is_negative_lexical_rating_example(
                segment,
                claim_text,
                claim_kind,
                facts,
            )
            for segment in _extract_grounding_example_segments(claim_text)
        )
    ):
        reasons.append("Der Vertrag verbietet unbelegte Beispiel-Claims.")
    if (
        "unsupported percentages" in lowered_forbidden
        and _PERCENT_PATTERN.search(claim_text)
        and "percentages" not in support_values
        and not (
            negative_or_unknown_limitation
            and not _NUMERIC_PERCENT_PATTERN.search(claim_text)
        )
    ):
        reasons.append("Der Vertrag verbietet unbelegte Prozent- oder Anteilsclaims.")
    if (
        "unsupported category claims" in lowered_forbidden
        and _CATEGORY_PATTERN.search(lowered_text)
        and not grounded_limitation
        and not negative_or_unknown_limitation
        and not grounded_testable_hypothesis
        and (
            "interpretation_anchor" not in support_values
            or (
                any(
                    value in {"partial", "sample_only", "top_n_only", "derived"}
                    for value in exactness_values
                )
                and not _is_explicitly_bounded_claim(claim_text)
            )
        )
    ):
        reasons.append("Der Vertrag verbietet unbelegte Kategorie- oder Dominanzclaims.")
    return reasons


def _looks_like_opaque_id(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 24:
        return False
    if ":" in text:
        text = text.split(":", 1)[1]
    alnum = "".join(ch for ch in text if ch.isalnum())
    if len(alnum) < 24:
        return False
    return all(ch.isdigit() or "a" <= ch.lower() <= "f" for ch in alnum[:32])


_SEMANTIC_THEME_STOPWORDS = {
    "aber",
    "alle",
    "allen",
    "alles",
    "als",
    "also",
    "auch",
    "auf",
    "aus",
    "bei",
    "bin",
    "bis",
    "das",
    "dass",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "doch",
    "dort",
    "durch",
    "ein",
    "eine",
    "einem",
    "einen",
    "einer",
    "eines",
    "endlich",
    "für",
    "für",
    "haben",
    "hat",
    "hier",
    "ich",
    "ihm",
    "ihn",
    "ihr",
    "ihre",
    "ihrem",
    "ihren",
    "ihrer",
    "ihres",
    "im",
    "ist",
    "kein",
    "keine",
    "mit",
    "nicht",
    "noch",
    "nur",
    "oder",
    "sich",
    "sein",
    "seine",
    "seinem",
    "seinen",
    "seiner",
    "seines",
    "sie",
    "sind",
    "steht",
    "the",
    "this",
    "und",
    "uns",
    "von",
    "war",
    "was",
    "weil",
    "wenn",
    "werden",
    "wie",
    "wir",
    "wird",
    "with",
    "zu",
    "zum",
    "zur",
    "text",
    "texte",
    "korpus",
    "corpus",
    "snippet",
    "score",
}


def _semantic_theme_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]{2,}", text):
        token = raw.strip("-").lower()
        if len(token) < 4 or token in _SEMANTIC_THEME_STOPWORDS or _looks_like_opaque_id(token):
            continue
        tokens.append(token)
    return tokens


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_claim_restates_user_task(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5716-5726)."""
    if "_claim_restates_user_task" in _vae_ctx:
        _claim_restates_user_task = _vae_ctx["_claim_restates_user_task"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "normalized_requirements" in _vae_ctx:
        normalized_requirements = _vae_ctx["normalized_requirements"]
    if "question_text" in _vae_ctx:
        question_text = _vae_ctx["question_text"]
    if "response_assignment_reasons" in _vae_ctx:
        response_assignment_reasons = _vae_ctx["response_assignment_reasons"]
    if _claim_restates_user_task(
        claim.text,
        question_text,
        normalized_requirements,
    ):
        response_assignment_reasons.append(
            "Der Claim wiederholt nur eine Arbeitsanweisung des Nutzers."
        )
        claim_reasons.append(
            "Eine kopierte Arbeitsanweisung ist kein analytischer Claim."
        )


def _vae_rule_response_requirement_id(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5727-5767)."""
    if "_RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN" in _vae_ctx:
        _RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN = _vae_ctx["_RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN"]
    if "_RESPONSE_REQUIREMENT_HEADING_PATTERN" in _vae_ctx:
        _RESPONSE_REQUIREMENT_HEADING_PATTERN = _vae_ctx["_RESPONSE_REQUIREMENT_HEADING_PATTERN"]
    if "_response_requirement_condition_reasons" in _vae_ctx:
        _response_requirement_condition_reasons = _vae_ctx["_response_requirement_condition_reasons"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "requirement_by_id" in _vae_ctx:
        requirement_by_id = _vae_ctx["requirement_by_id"]
    if "response_assignment_reasons" in _vae_ctx:
        response_assignment_reasons = _vae_ctx["response_assignment_reasons"]
    if "response_completion_reasons" in _vae_ctx:
        response_completion_reasons = _vae_ctx["response_completion_reasons"]
    if "response_requirement" in _vae_ctx:
        response_requirement = _vae_ctx["response_requirement"]
    if "response_requirement_id" in _vae_ctx:
        response_requirement_id = _vae_ctx["response_requirement_id"]
    if response_requirement_id:
        response_requirement = requirement_by_id.get(
            response_requirement_id
        )
        if response_requirement is None:
            response_assignment_reasons.append(
                "Der Claim verweist auf einen unbekannten "
                "response_requirement_id."
            )
        elif claim.claim_kind != response_requirement.claim_kind:
            response_assignment_reasons.append(
                "Der Claim-Typ erfüllt den zugeordneten Antwortslot "
                f"nicht: erwartet ist {response_requirement.claim_kind}."
            )
        else:
            response_completion_reasons = (
                _response_requirement_condition_reasons(
                    claim.text,
                    response_requirement,
                    assertion_level=claim.assertion_level,
                )
            )
            response_assignment_reasons.extend(
                response_completion_reasons
            )
        if (
            _RESPONSE_REQUIREMENT_ANNOUNCEMENT_PATTERN.search(
                claim.text or ""
            )
            or _RESPONSE_REQUIREMENT_HEADING_PATTERN.search(
                claim.text or ""
            )
        ):
            response_assignment_reasons.append(
                "Der Claim ist nur eine Ankündigung oder Überschrift und erfüllt den "
                "zugeordneten Antwortslot nicht."
            )
            claim_reasons.append(
                "Eine Ankündigung späterer Antwortbestandteile erfüllt "
                "keinen substanziellen analytischen Beitrag."
            )
    _vae_l = locals()
    for _vae_n in ("response_completion_reasons", "response_requirement"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_claim_bundles_analytical_units(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5768-5780)."""
    if "_claim_bundles_analytical_units" in _vae_ctx:
        _claim_bundles_analytical_units = _vae_ctx["_claim_bundles_analytical_units"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "response_assignment_reasons" in _vae_ctx:
        response_assignment_reasons = _vae_ctx["response_assignment_reasons"]
    if "response_completion_reasons" in _vae_ctx:
        response_completion_reasons = _vae_ctx["response_completion_reasons"]
    claim._response_requirement_assignment_reasons = (
        response_assignment_reasons
    )
    claim._response_requirement_completion_reasons = (
        response_completion_reasons
    )
    if _claim_bundles_analytical_units(claim.text or ""):
        claim_reasons.append(
            "Der Claim bündelt mehrere analytische Einheiten. Jeder "
            "Claim muss genau eine Beobachtung, Interpretation oder "
            "Hypothese tragen, damit Evidenz und Aussagegrad atomar "
            "prüfbar bleiben."
        )


def _vae_rule_lexical_absence_overreads_contextual_retrieval(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5781-5792)."""
    if "_lexical_absence_overreads_contextual_retrieval" in _vae_ctx:
        _lexical_absence_overreads_contextual_retrieval = _vae_ctx["_lexical_absence_overreads_contextual_retrieval"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _lexical_absence_overreads_contextual_retrieval(
        claim.text,
        facts,
        assertion_level=claim.assertion_level,
    ):
        claim_reasons.append(
            "Eine exakte Nullsuche zusammen mit begrenzten Kontext- oder "
            "semantischen Treffern belegt weder lexikalische Ersetzung "
            "noch bewusste Begriffsvermeidung. Als klar testbare, "
            "tentative Hypothese ist eine Alternativlexik möglich; "
            "Autorintention bleibt ohne eigene Evidenz unbelegt."
        )


def _vae_rule_expanded_kwic_fact_ids(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5793-5803)."""
    if "analysis_family" in _vae_ctx:
        analysis_family = _vae_ctx["analysis_family"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "expanded_kwic_fact_ids" in _vae_ctx:
        expanded_kwic_fact_ids = _vae_ctx["expanded_kwic_fact_ids"]
    if (
        analysis_family == "kwic_context"
        and claim.claim_kind == "interpretation"
        and expanded_kwic_fact_ids
        and expanded_kwic_fact_ids.isdisjoint(claim.fact_ids)
    ):
        claim_reasons.append(
            "Eine Deutung des KWIC-Belegs muss an den abgerufenen "
            "erweiterten Kontext gebunden sein; das schmale KWIC-Fenster "
            "allein trägt keine Volltextinterpretation."
        )


def _vae_rule_has_cross_source_literal_separation(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5804-5815)."""
    if "_has_cross_source_literal_separation" in _vae_ctx:
        _has_cross_source_literal_separation = _vae_ctx["_has_cross_source_literal_separation"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "cross_source_fact_mix" in _vae_ctx:
        cross_source_fact_mix = _vae_ctx["cross_source_fact_mix"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "generic_time_trend_status" in _vae_ctx:
        generic_time_trend_status = _vae_ctx["generic_time_trend_status"]
    if "normalised_time_trend_status" in _vae_ctx:
        normalised_time_trend_status = _vae_ctx["normalised_time_trend_status"]
    if (
        claim.claim_kind == "observation"
        and cross_source_fact_mix
        and not _has_cross_source_literal_separation(claim.text, facts)
        and normalised_time_trend_status is not True
        and generic_time_trend_status is not True
    ):
        claim_reasons.append(
            "Beobachtungen aus getrennten Evidenzquellen müssen atomar "
            "aufgeteilt werden; ihre Verknüpfung ist eine zu "
            "verifizierende Interpretation."
        )


def _vae_rule_normalised_time_trend_status(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5816-5820)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "normalised_time_trend_status" in _vae_ctx:
        normalised_time_trend_status = _vae_ctx["normalised_time_trend_status"]
    if normalised_time_trend_status is False:
        claim_reasons.append(
            "Die behauptete relative Zeitentwicklung stimmt nicht mit "
            "den Count-/Nenner-Paaren der genannten Zeitpunkte überein."
        )


def _vae_rule_generic_time_trend_status(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5821-5826)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "generic_time_trend_status" in _vae_ctx:
        generic_time_trend_status = _vae_ctx["generic_time_trend_status"]
    if generic_time_trend_status is False:
        claim_reasons.append(
            "Die behauptete Zeitentwicklung ist ohne mindestens zwei "
            "zeitgebundene Count-/Nenner-Paare nicht belegt oder weist "
            "die falsche Richtung auf."
        )


def _vae_rule_nonpositive_only_claim_has_positive_assertion(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5827-5845)."""
    if "_is_grounded_methodological_explanation" in _vae_ctx:
        _is_grounded_methodological_explanation = _vae_ctx["_is_grounded_methodological_explanation"]
    if "_is_negative_or_unknown_limitation" in _vae_ctx:
        _is_negative_or_unknown_limitation = _vae_ctx["_is_negative_or_unknown_limitation"]
    if "_nonpositive_only_claim_has_positive_assertion" in _vae_ctx:
        _nonpositive_only_claim_has_positive_assertion = _vae_ctx["_nonpositive_only_claim_has_positive_assertion"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    negative_or_unknown_limitation = _is_negative_or_unknown_limitation(
        claim.text,
        claim_kind=claim.claim_kind,
    )
    grounded_methodological_explanation = (
        _is_grounded_methodological_explanation(
            analytical_prose,
            facts,
        )
    )
    if _nonpositive_only_claim_has_positive_assertion(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Ein negatives, begrenzendes oder nicht anwendbares "
            "Tool-Ergebnis belegt "
            "keine zusätzliche positive Korpusaussage."
        )
    _vae_l = locals()
    for _vae_n in ("grounded_methodological_explanation", "negative_or_unknown_limitation"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_negative_or_unknown_limitation(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5846-5919)."""
    if "_EXISTING_LEMMA_RESULT_PATTERN" in _vae_ctx:
        _EXISTING_LEMMA_RESULT_PATTERN = _vae_ctx["_EXISTING_LEMMA_RESULT_PATTERN"]
    if "_LEMMA_CLAIM_PATTERN" in _vae_ctx:
        _LEMMA_CLAIM_PATTERN = _vae_ctx["_LEMMA_CLAIM_PATTERN"]
    if "_LEMMA_QUERY_CLAIM_PATTERN" in _vae_ctx:
        _LEMMA_QUERY_CLAIM_PATTERN = _vae_ctx["_LEMMA_QUERY_CLAIM_PATTERN"]
    if "_PROPOSED_LEMMA_ANALYSIS_PATTERN" in _vae_ctx:
        _PROPOSED_LEMMA_ANALYSIS_PATTERN = _vae_ctx["_PROPOSED_LEMMA_ANALYSIS_PATTERN"]
    if "_TOTAL_HIT_COUNT_FIELD_NAMES" in _vae_ctx:
        _TOTAL_HIT_COUNT_FIELD_NAMES = _vae_ctx["_TOTAL_HIT_COUNT_FIELD_NAMES"]
    if "_field_numeric_values" in _vae_ctx:
        _field_numeric_values = _vae_ctx["_field_numeric_values"]
    if "_joined_surface_text" in _vae_ctx:
        _joined_surface_text = _vae_ctx["_joined_surface_text"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "explicit_lemma_query_evidence" in _vae_ctx:
        explicit_lemma_query_evidence = _vae_ctx["explicit_lemma_query_evidence"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "lemma_grouping_evidence" in _vae_ctx:
        lemma_grouping_evidence = _vae_ctx["lemma_grouping_evidence"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if "proposes_new_lemma_analysis" in _vae_ctx:
        proposes_new_lemma_analysis = _vae_ctx["proposes_new_lemma_analysis"]
    if "quote" in _vae_ctx:
        quote = _vae_ctx["quote"]
    if "re" in _vae_ctx:
        re = _vae_ctx["re"]
    if "source_evidence_ids" in _vae_ctx:
        source_evidence_ids = _vae_ctx["source_evidence_ids"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    claim_corpus_token_basis_is_visible = any(
        source_evidence_ids.intersection(fact.source_evidence_ids)
        and (
            "corpus_tokens=" in fact.statement
            or any(
                "corpus_tokens=" in quote
                for quote in fact.grounding_quotes
            )
        )
        for fact in observed_facts
    )
    claim_total_hits_basis_is_visible = any(
        source_evidence_ids.intersection(fact.source_evidence_ids)
        and bool(
            _field_numeric_values(
                _joined_surface_text(
                    [fact.statement, *fact.grounding_quotes]
                ),
                _TOTAL_HIT_COUNT_FIELD_NAMES,
            )
        )
        for fact in observed_facts
    )
    explicit_lemma_query_evidence = bool(
        "lemma-abfrage" in source_surface.lower()
        or re.search(
            r"\blemma\s*(?:=|in\b)",
            source_surface,
            re.IGNORECASE,
        )
        or re.search(
            r"\battribute\s*=\s*lemma\b",
            source_surface,
            re.IGNORECASE,
        )
    )
    lemma_grouping_evidence = bool(
        re.search(
            r"\bgroup_by\s*=\s*lemma\b",
            source_surface,
            re.IGNORECASE,
        )
    )
    proposes_new_lemma_analysis = bool(
        (
            claim.claim_kind == "followup"
            or (
                deliverable_kind == "method_advice"
                and claim.claim_kind == "interpretation"
            )
        )
        and _PROPOSED_LEMMA_ANALYSIS_PATTERN.search(claim.text)
        and _EXISTING_LEMMA_RESULT_PATTERN.search(claim.text) is None
    )
    if (
        not negative_or_unknown_limitation
        and not proposes_new_lemma_analysis
        and (
        (
            _LEMMA_CLAIM_PATTERN.search(claim.text)
            and not explicit_lemma_query_evidence
            and not lemma_grouping_evidence
        )
        or (
            _LEMMA_QUERY_CLAIM_PATTERN.search(claim.text)
            and not explicit_lemma_query_evidence
        )
        )
    ):
        claim_reasons.append(
            "Der Claim bezeichnet eine Suche oder Auswertung als "
            "Lemma-Abfrage, ohne dass die referenzierten Facts eine "
            "Lemma-Abfrage oder Lemma-Gruppierung belegen."
        )
    _vae_l = locals()
    for _vae_n in ("claim_corpus_token_basis_is_visible", "claim_total_hits_basis_is_visible", "explicit_lemma_query_evidence", "fact", "lemma_grouping_evidence", "proposes_new_lemma_analysis", "quote"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_flattened_cqlf_query(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5920-5930)."""
    if "_misdescribed_multi_token_cqlf_query" in _vae_ctx:
        _misdescribed_multi_token_cqlf_query = _vae_ctx["_misdescribed_multi_token_cqlf_query"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "flattened_cqlf_query" in _vae_ctx:
        flattened_cqlf_query = _vae_ctx["flattened_cqlf_query"]
    flattened_cqlf_query = _misdescribed_multi_token_cqlf_query(
        claim.text,
        facts,
    )
    if flattened_cqlf_query:
        claim_reasons.append(
            "Der Claim beschreibt die mehrgliedrige CQLF-Abfrage "
            f"{flattened_cqlf_query!r} wie eine einzelne kombinierte "
            "Attributsuche. Gib die Query wörtlich wieder oder benenne "
            "ihre Tokenfolge ausdrücklich."
        )
    _vae_l = locals()
    for _vae_n in ("flattened_cqlf_query",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_negative_or_unknown_limitation_2(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5931-5939)."""
    if "_CORPUS_PURPOSE_CLAIM_PATTERN" in _vae_ctx:
        _CORPUS_PURPOSE_CLAIM_PATTERN = _vae_ctx["_CORPUS_PURPOSE_CLAIM_PATTERN"]
    if "_EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN" in _vae_ctx:
        _EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN = _vae_ctx["_EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if (
        _CORPUS_PURPOSE_CLAIM_PATTERN.search(claim.text)
        and not _EXPLICIT_CORPUS_PURPOSE_EVIDENCE_PATTERN.search(source_surface)
        and not negative_or_unknown_limitation
    ):
        claim_reasons.append(
            "Beobachtete Korpusmerkmale belegen keinen Erhebungs-, "
            "Erstellungs- oder Verwendungszweck des Korpus."
        )


def _vae_rule_unsupported_raw_pos_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5940-5949)."""
    if "_unsupported_raw_pos_inference" in _vae_ctx:
        _unsupported_raw_pos_inference = _vae_ctx["_unsupported_raw_pos_inference"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_raw_pos_inference(claim.text, facts)
    ):
        claim_reasons.append(
            "Rohe POS-Häufigkeiten tragen ohne unabhängige Vergleichs- "
            "oder Direktmessung keine Aussage über Stil, Komplexität, "
            "Registertypik, Thema oder Textform."
        )


def _vae_rule_unsupported_pos_inventory_provenance(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5950-5961)."""
    if "_unsupported_pos_inventory_provenance" in _vae_ctx:
        _unsupported_pos_inventory_provenance = _vae_ctx["_unsupported_pos_inventory_provenance"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_pos_inventory_provenance(
            claim.text,
            facts,
        )
    ):
        claim_reasons.append(
            "Eine Wort-/Lemmarangliste darf nicht als Liste der "
            "POS-Kategorien beschrieben werden."
        )


def _vae_rule_unsupported_natural_pos_label(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5962-5970)."""
    if "_unsupported_natural_pos_label" in _vae_ctx:
        _unsupported_natural_pos_label = _vae_ctx["_unsupported_natural_pos_label"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_natural_pos_label(claim.text, facts)
    ):
        claim_reasons.append(
            "Eine natürliche Wortartbezeichnung muss zum expliziten "
            "POS-Tag der referenzierten Evidenz passen."
        )


def _vae_rule_unsupported_absolute_association_magnitude(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5980-5988)."""
    if "_unsupported_absolute_association_magnitude" in _vae_ctx:
        _unsupported_absolute_association_magnitude = _vae_ctx["_unsupported_absolute_association_magnitude"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_absolute_association_magnitude(claim.text)
    ):
        claim_reasons.append(
            "Eine Assoziation ist ohne sichtbaren Vergleich oder "
            "operationalisierten Schwellenwert weder stark noch schwach."
        )


def _vae_rule_empty_collocation_profile_is_overread(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 5989-6005)."""
    if "_empty_collocation_profile_is_overread" in _vae_ctx:
        _empty_collocation_profile_is_overread = _vae_ctx["_empty_collocation_profile_is_overread"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and _empty_collocation_profile_is_overread(
            claim.text,
            facts,
            observed_facts,
            assertion_level=claim.assertion_level,
        )
    ):
        claim_reasons.append(
            "Ein leeres, mindestfrequenzgefiltertes Kollokationsprofil "
            "belegt nur null zurückgegebene Zeilen unter diesen "
            "Parametern. Es belegt weder fehlende Kontextmuster noch "
            "eine spezifische oder feste Verwendungsweise; solche "
            "Deutungen müssen als prüfbare Hypothesen mit KWIC- oder "
            "Kontextevidenz formuliert werden."
        )


def _vae_rule_unsupported_collocation_pos_composition(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6006-6019)."""
    if "_unsupported_collocation_pos_composition" in _vae_ctx:
        _unsupported_collocation_pos_composition = _vae_ctx["_unsupported_collocation_pos_composition"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_collocation_pos_composition(
            claim.text,
            facts,
            observed_facts,
        )
    ):
        claim_reasons.append(
            "Oberflächenformen einer Kollokattabelle belegen ohne "
            "POS- oder KWIC-Evidenz keine Dominanz bestimmter "
            "Wortarten."
        )


def _vae_rule_is_explicitly_bounded_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6020-6065)."""
    if "_EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN" in _vae_ctx:
        _EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN = _vae_ctx["_EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN"]
    if "_WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN" in _vae_ctx:
        _WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN = _vae_ctx["_WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN"]
    if "_WORD_SKETCH_PREVALENCE_PATTERN" in _vae_ctx:
        _WORD_SKETCH_PREVALENCE_PATTERN = _vae_ctx["_WORD_SKETCH_PREVALENCE_PATTERN"]
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "_joined_surface_text" in _vae_ctx:
        _joined_surface_text = _vae_ctx["_joined_surface_text"]
    if "_source_values_for_field" in _vae_ctx:
        _source_values_for_field = _vae_ctx["_source_values_for_field"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "re" in _vae_ctx:
        re = _vae_ctx["re"]
    if "source_id" in _vae_ctx:
        source_id = _vae_ctx["source_id"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _WORD_SKETCH_PREVALENCE_PATTERN.search(claim.text)
        and any(
            "word_sketch" in source_id.casefold()
            or "word sketch" in fact.statement.casefold()
            for fact in facts
            for source_id in (
                fact.source_evidence_ids or [""]
            )
        )
        and not re.search(
            r"\b(?:anchor_count|coverage_ratio|coverage_count|"
            r"anteil|prozent|rate)\s*=",
            source_surface,
            re.IGNORECASE,
        )
        and not (
            _is_explicitly_bounded_claim(claim.text)
            and any(
                fact.fact_kind == "ranked_row"
                and _source_values_for_field(
                    "f",
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    ),
                )
                for fact in facts
            )
        )
        and (
            _EXPLICIT_FREQUENCY_MAGNITUDE_REFERENCE_PATTERN.search(
                claim.text
            )
            is None
            or _WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN.search(
                claim.text
            )
        )
    ):
        claim_reasons.append(
            "Sichtbare Word-Sketch-Relationszeilen ohne Nenner über alle "
            "Vorkommen belegen keine häufige, typische oder dominante "
            "Konstruktion."
        )
    _vae_l = locals()
    for _vae_n in ("fact", "source_id"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_platform_handle_label(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6136-6147)."""
    if "_unsupported_platform_handle_label" in _vae_ctx:
        _unsupported_platform_handle_label = _vae_ctx["_unsupported_platform_handle_label"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "question_text" in _vae_ctx:
        question_text = _vae_ctx["question_text"]
    if (
        not negative_or_unknown_limitation
        and _unsupported_platform_handle_label(
            claim.text,
            facts,
            question_text=question_text,
        )
    ):
        claim_reasons.append(
            "Ein @-Token belegt ohne Plattformmetadaten nur eine "
            "handleartige Form, aber kein plattformspezifisches Handle."
        )


def _vae_rule_unsupported_document_class_label(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6148-6157)."""
    if "_unsupported_document_class_label" in _vae_ctx:
        _unsupported_document_class_label = _vae_ctx["_unsupported_document_class_label"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_document_class_label(claim.text, facts)
    ):
        claim_reasons.append(
            "Eine Dokumentklasse wie Tweet oder Post ist nur durch ein "
            "explizites Texttyp- oder Genre-Metadatenfeld belegt; "
            "Registerlabels und @-Formen genügen dafür nicht."
        )


def _vae_rule_unsupported_user_handle_identity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6158-6169)."""
    if "_unsupported_user_handle_identity" in _vae_ctx:
        _unsupported_user_handle_identity = _vae_ctx["_unsupported_user_handle_identity"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        not negative_or_unknown_limitation
        and _unsupported_user_handle_identity(
            claim.text,
            facts,
        )
    ):
        claim_reasons.append(
            "Ein @-Token belegt ohne Autor-, Account- oder "
            "Plattformmetadaten nur eine handleartige Wortform, aber "
            "noch keine Identität als User-Handle."
        )


def _vae_rule_absolute_counts_called_relative(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6183-6191)."""
    if "_absolute_counts_called_relative" in _vae_ctx:
        _absolute_counts_called_relative = _vae_ctx["_absolute_counts_called_relative"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        not negative_or_unknown_limitation
        and _absolute_counts_called_relative(claim.text)
    ):
        claim_reasons.append(
            "Der Claim bezeichnet absolute f-Werte als relative "
            "Häufigkeiten, ohne per_million, Anteil oder Vergleich "
            "auszuweisen."
        )


def _vae_rule_unsupported_register_theme_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6192-6200)."""
    if "_unsupported_register_theme_inference" in _vae_ctx:
        _unsupported_register_theme_inference = _vae_ctx["_unsupported_register_theme_inference"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_register_theme_inference(claim.text, facts)
    ):
        claim_reasons.append(
            "Ein Registerwert bezeichnet eine Kommunikationssituation, "
            "aber ohne inhaltliche Evidenz kein Themenfeld."
        )


def _vae_rule_unsupported_grammatical_profile_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6201-6213)."""
    if "_unsupported_grammatical_profile_inference" in _vae_ctx:
        _unsupported_grammatical_profile_inference = _vae_ctx["_unsupported_grammatical_profile_inference"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and not negative_or_unknown_limitation
        and _unsupported_grammatical_profile_inference(
            claim.text,
            facts,
        )
    ):
        claim_reasons.append(
            "Rohe Pronomen-, Funktionswort- oder POS-Frequenzen "
            "belegen ohne Kontext- oder Vergleichsevidenz weder Stil "
            "noch Textsorte oder Register."
        )


def _vae_rule_result_is_mislabeled_as_sample(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6214-6222)."""
    if "_result_is_mislabeled_as_sample" in _vae_ctx:
        _result_is_mislabeled_as_sample = _vae_ctx["_result_is_mislabeled_as_sample"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        not negative_or_unknown_limitation
        and _result_is_mislabeled_as_sample(claim.text, facts)
    ):
        claim_reasons.append(
            "Eine Vollauswertung oder ein Top-N-Ausschnitt ist keine "
            "gezogene Stichprobe; ohne Samplingprovenienz darf das "
            "Ergebnis nicht als Stichprobe bezeichnet werden."
        )


def _vae_rule_declared_sample_cardinality_is_wrong(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6223-6234)."""
    if "_declared_sample_cardinality_is_wrong" in _vae_ctx:
        _declared_sample_cardinality_is_wrong = _vae_ctx["_declared_sample_cardinality_is_wrong"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if (
        not negative_or_unknown_limitation
        and _declared_sample_cardinality_is_wrong(
            claim.text,
            facts,
            observed_facts,
        )
    ):
        claim_reasons.append(
            "Die behauptete Größe der gezogenen Stichprobe stimmt nicht "
            "mit der Samplingprovenienz des Tool-Ergebnisses überein."
        )


def _vae_rule_is_explicitly_bounded_claim_2(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6264-6282)."""
    if "_CATEGORY_PATTERN" in _vae_ctx:
        _CATEGORY_PATTERN = _vae_ctx["_CATEGORY_PATTERN"]
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "re" in _vae_ctx:
        re = _vae_ctx["re"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if (
        _CATEGORY_PATTERN.search(analytical_prose)
        and "word sketch" in source_surface.lower()
        and not negative_or_unknown_limitation
        and not re.search(
            r"\b(?:anchor_count|coverage_ratio|coverage_count|anteil)\s*=",
            source_surface,
            re.IGNORECASE,
        )
        and not (
            claim.assertion_level == "qualified"
            and _is_explicitly_bounded_claim(claim.text)
        )
    ):
        claim_reasons.append(
            "Word-Sketch-Relationszeilen ohne Anteilsnenner belegen keine "
            "dominante, überwiegende oder typische Relation über alle "
            "Vorkommen des Suchbegriffs."
        )


def _vae_rule_is_explicitly_bounded_claim_3(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6283-6331)."""
    if "_SYNTACTIC_FUNCTION_GENERALISATION_PATTERN" in _vae_ctx:
        _SYNTACTIC_FUNCTION_GENERALISATION_PATTERN = _vae_ctx["_SYNTACTIC_FUNCTION_GENERALISATION_PATTERN"]
    if "_SYNTACTIC_GENERALISATION_PATTERN" in _vae_ctx:
        _SYNTACTIC_GENERALISATION_PATTERN = _vae_ctx["_SYNTACTIC_GENERALISATION_PATTERN"]
    if "_EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN" in _vae_ctx:
        _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN = _vae_ctx["_EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN"]
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "re" in _vae_ctx:
        re = _vae_ctx["re"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if (
        (
            _SYNTACTIC_GENERALISATION_PATTERN.search(analytical_prose)
            or _SYNTACTIC_FUNCTION_GENERALISATION_PATTERN.search(
                analytical_prose
            )
        )
        and not negative_or_unknown_limitation
        and not _is_testable_hypothesis_claim(
            claim.text,
            claim_kind=claim.claim_kind,
            assertion_level=claim.assertion_level,
        )
        and not (
            (
                "word sketch" in source_surface.lower()
                and (
                    re.search(
                        r"\b(?:anchor_count|coverage_ratio|coverage_count)\s*=",
                        source_surface,
                        re.IGNORECASE,
                    )
                    or (
                        claim.assertion_level == "qualified"
                        and _is_explicitly_bounded_claim(claim.text)
                    )
                )
            )
            or (
                re.search(
                    r"\bsyntactic_function\s*=",
                    source_surface,
                    re.IGNORECASE,
                )
                and re.search(
                    r"\banchor_count\s*=",
                    source_surface,
                    re.IGNORECASE,
                )
                and re.search(
                    r"\bcoverage_count\s*=",
                    source_surface,
                    re.IGNORECASE,
                )
                and claim.assertion_level == "qualified"
                and _is_explicitly_bounded_claim(claim.text)
            )
        )
    ):
        claim_reasons.append(
            "Breite oder typische syntaktische Generalisierungen brauchen "
            "eine explizite Relationsauswertung mit Bezugsgröße; sichtbare "
            "Fensterkollokationen oder einzelne KWIC-Zeilen reichen nicht."
        )


def _vae_rule_unsupported_syntactic_roles(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6332-6342)."""
    if "_unsupported_syntactic_role_claims" in _vae_ctx:
        _unsupported_syntactic_role_claims = _vae_ctx["_unsupported_syntactic_role_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_syntactic_roles" in _vae_ctx:
        unsupported_syntactic_roles = _vae_ctx["unsupported_syntactic_roles"]
    unsupported_syntactic_roles = _unsupported_syntactic_role_claims(
        analytical_prose,
        source_surface,
    )
    if unsupported_syntactic_roles and not _is_testable_hypothesis_claim(
        claim.text,
        claim_kind=claim.claim_kind,
        assertion_level=claim.assertion_level,
    ):
        claim_reasons.append(
            "Syntaktische Rollen brauchen eine explizite Relations- oder "
            "Funktionsangabe; Fensterkollokationen reichen nicht: "
            + ", ".join(unsupported_syntactic_roles[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_syntactic_roles",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_presence(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6343-6353)."""
    if "_unsupported_presence_claims" in _vae_ctx:
        _unsupported_presence_claims = _vae_ctx["_unsupported_presence_claims"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_presence" in _vae_ctx:
        unsupported_presence = _vae_ctx["unsupported_presence"]
    unsupported_presence = _unsupported_presence_claims(
        claim.text,
        facts,
    )
    if unsupported_presence:
        claim_reasons.append(
            "Präsenz- und Abwesenheitsclaims stimmen nicht mit den "
            "referenzierten Zeilen und Counts überein: "
            + ", ".join(unsupported_presence[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_presence",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_directional_presence(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6354-6366)."""
    if "_unsupported_directional_scope_presence_claims" in _vae_ctx:
        _unsupported_directional_scope_presence_claims = _vae_ctx["_unsupported_directional_scope_presence_claims"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_directional_presence" in _vae_ctx:
        unsupported_directional_presence = _vae_ctx["unsupported_directional_presence"]
    unsupported_directional_presence = (
        _unsupported_directional_scope_presence_claims(
            claim.text,
            facts,
        )
    )
    if unsupported_directional_presence:
        claim_reasons.append(
            "Die behauptete Präsenz oder Abwesenheit in Ziel- und "
            "Referenzscope widerspricht den gerichteten Keyness-Counts: "
            + ", ".join(unsupported_directional_presence[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_directional_presence",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_hashtag_label(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6412-6415)."""
    if "_unsupported_hashtag_label" in _vae_ctx:
        _unsupported_hashtag_label = _vae_ctx["_unsupported_hashtag_label"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _unsupported_hashtag_label(analytical_prose, facts):
        claim_reasons.append(
            "Ein @-Ausdruck ist ohne passende #‑Form kein Hashtag."
        )


def _vae_rule_unsupported_partial_exhaustivity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6416-6428)."""
    if "_unsupported_partial_exhaustive_claims" in _vae_ctx:
        _unsupported_partial_exhaustive_claims = _vae_ctx["_unsupported_partial_exhaustive_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_partial_exhaustivity" in _vae_ctx:
        unsupported_partial_exhaustivity = _vae_ctx["unsupported_partial_exhaustivity"]
    unsupported_partial_exhaustivity = (
        _unsupported_partial_exhaustive_claims(
            analytical_prose,
            facts,
        )
    )
    if unsupported_partial_exhaustivity:
        claim_reasons.append(
            "Ein sichtbarer Ausschnitt trägt keine unmarkierte "
            "Ausschließlichkeits- oder Vollständigkeitsbehauptung: "
            + ", ".join(unsupported_partial_exhaustivity[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_partial_exhaustivity",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_artifacts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6429-6440)."""
    if "_unsupported_artifact_classifications" in _vae_ctx:
        _unsupported_artifact_classifications = _vae_ctx["_unsupported_artifact_classifications"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "question_text" in _vae_ctx:
        question_text = _vae_ctx["question_text"]
    if "unsupported_artifacts" in _vae_ctx:
        unsupported_artifacts = _vae_ctx["unsupported_artifacts"]
    unsupported_artifacts = _unsupported_artifact_classifications(
        analytical_prose,
        facts,
        question_text=question_text,
    )
    if unsupported_artifacts:
        claim_reasons.append(
            "Artefakt-, Noise- oder Ausreißeretiketten brauchen ein "
            "explizites Qualitätsfeld oder eine Hypothesenmarkierung: "
            + ", ".join(unsupported_artifacts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_artifacts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_ngram_function_frequency(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6482-6489)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "unsupported_ngram_function_frequency" in _vae_ctx:
        unsupported_ngram_function_frequency = _vae_ctx["unsupported_ngram_function_frequency"]
    if unsupported_ngram_function_frequency:
        claim_reasons.append(
            "Die Rohfrequenz eines N-Gramms belegt nicht, dass es eine "
            "bestimmte Kontext- oder Satzfunktion regelmäßig erfüllt; "
            "das muss KWIC beziehungsweise Kontextkodierung prüfen: "
            + ", ".join(unsupported_ngram_function_frequency[:3])
            + "."
        )


def _vae_rule_unsupported_text_origin(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6503-6513)."""
    if "_unsupported_text_production_inferences" in _vae_ctx:
        _unsupported_text_production_inferences = _vae_ctx["_unsupported_text_production_inferences"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_text_origin" in _vae_ctx:
        unsupported_text_origin = _vae_ctx["unsupported_text_origin"]
    unsupported_text_origin = _unsupported_text_production_inferences(
        analytical_prose,
        facts,
    )
    if unsupported_text_origin:
        claim_reasons.append(
            "Rohfrequenzen belegen ohne Autor- oder Modellmetadaten "
            "keine menschliche oder automatisierte Textentstehung: "
            + ", ".join(unsupported_text_origin[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_text_origin",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_pos(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6514-6524)."""
    if "_unsupported_pos_claims" in _vae_ctx:
        _unsupported_pos_claims = _vae_ctx["_unsupported_pos_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_pos" in _vae_ctx:
        unsupported_pos = _vae_ctx["unsupported_pos"]
    unsupported_pos = _unsupported_pos_claims(
        analytical_prose,
        source_surface,
    )
    if unsupported_pos:
        claim_reasons.append(
            "Natürlich formulierte POS-Tags brauchen ein explizites "
            "pos-/upos-Feld: "
            + ", ".join(unsupported_pos[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_pos",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_provenance(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6525-6535)."""
    if "_unsupported_tool_provenance_claims" in _vae_ctx:
        _unsupported_tool_provenance_claims = _vae_ctx["_unsupported_tool_provenance_claims"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_provenance" in _vae_ctx:
        unsupported_provenance = _vae_ctx["unsupported_provenance"]
    unsupported_provenance = _unsupported_tool_provenance_claims(
        claim.text,
        facts,
    )
    if unsupported_provenance:
        claim_reasons.append(
            "Die behauptete Tool-Provenienz ist in den referenzierten "
            "Facts nicht belegt: "
            + ", ".join(unsupported_provenance[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_provenance",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_distribution(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6536-6544)."""
    if "_unsupported_distribution_claims" in _vae_ctx:
        _unsupported_distribution_claims = _vae_ctx["_unsupported_distribution_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_distribution" in _vae_ctx:
        unsupported_distribution = _vae_ctx["unsupported_distribution"]
    unsupported_distribution = _unsupported_distribution_claims(
        analytical_prose,
        source_surface,
    )
    if unsupported_distribution:
        claim_reasons.append(
            "Eine Dispersionscharakterisierung braucht ein explizites "
            "Dispersions- oder Verteilungsfeld."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_distribution",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_scope_design(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6561-6571)."""
    if "_unsupported_scope_design_claims" in _vae_ctx:
        _unsupported_scope_design_claims = _vae_ctx["_unsupported_scope_design_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_scope_design" in _vae_ctx:
        unsupported_scope_design = _vae_ctx["unsupported_scope_design"]
    unsupported_scope_design = _unsupported_scope_design_claims(
        analytical_prose,
        source_surface,
    )
    if unsupported_scope_design:
        claim_reasons.append(
            "Vollständigkeit oder Repräsentativität braucht explizite "
            "Scope-/Sampling-Evidenz: "
            + ", ".join(unsupported_scope_design[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_scope_design",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_diversity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6572-6583)."""
    if "_unsupported_lexical_diversity_claims" in _vae_ctx:
        _unsupported_lexical_diversity_claims = _vae_ctx["_unsupported_lexical_diversity_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_diversity" in _vae_ctx:
        unsupported_diversity = _vae_ctx["unsupported_diversity"]
    unsupported_diversity = _unsupported_lexical_diversity_claims(
        analytical_prose,
        facts,
        claim_kind=claim.claim_kind,
    )
    if unsupported_diversity:
        claim_reasons.append(
            "Lexikalische Diversität wird stärker interpretiert, als "
            "Vergleichsbasis und Analysepopulation erlauben: "
            + ", ".join(unsupported_diversity[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_diversity",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_source_attributed_cross_sentence_inference(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6593-6600)."""
    if "_source_attributed_cross_sentence_inference" in _vae_ctx:
        _source_attributed_cross_sentence_inference = _vae_ctx["_source_attributed_cross_sentence_inference"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _source_attributed_cross_sentence_inference(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Die Deutung verbindet getrennte Quellsätze durch einen im "
            "Wortlaut nicht vorhandenen Folgerungs- oder Kausalmarker."
        )


def _vae_rule_source_attributed_unmarked_causal_link(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6601-6608)."""
    if "_source_attributed_unmarked_causal_link" in _vae_ctx:
        _source_attributed_unmarked_causal_link = _vae_ctx["_source_attributed_unmarked_causal_link"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _source_attributed_unmarked_causal_link(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Die Deutung ergänzt eine Kausalverknüpfung, für die im "
            "sichtbaren Quelltext kein Kausalmarker vorhanden ist."
        )


def _vae_rule_source_attributed_cross_sentence_predicate_transfer(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6609-6616)."""
    if "_source_attributed_cross_sentence_predicate_transfer" in _vae_ctx:
        _source_attributed_cross_sentence_predicate_transfer = _vae_ctx["_source_attributed_cross_sentence_predicate_transfer"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _source_attributed_cross_sentence_predicate_transfer(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Die Deutung überträgt ein Prädikat aus einem Quellsatz auf "
            "einen nur in einem anderen Quellsatz genannten Beteiligten."
        )


def _vae_rule_unsupported_correlations(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6716-6726)."""
    if "_unsupported_correlation_claims" in _vae_ctx:
        _unsupported_correlation_claims = _vae_ctx["_unsupported_correlation_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_correlations" in _vae_ctx:
        unsupported_correlations = _vae_ctx["unsupported_correlations"]
    unsupported_correlations = _unsupported_correlation_claims(
        analytical_prose,
        source_surface,
    )
    if unsupported_correlations:
        claim_reasons.append(
            "Eine Korrelationsrichtung braucht ein explizites "
            "Korrelationsresultat: "
            + ", ".join(unsupported_correlations[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_correlations",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_merges_cross_result_rankings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6727-6735)."""
    if "_merges_cross_result_rankings" in _vae_ctx:
        _merges_cross_result_rankings = _vae_ctx["_merges_cross_result_rankings"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "cross_source_fact_mix" in _vae_ctx:
        cross_source_fact_mix = _vae_ctx["cross_source_fact_mix"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "grounded_methodological_explanation" in _vae_ctx:
        grounded_methodological_explanation = _vae_ctx["grounded_methodological_explanation"]
    if (
        cross_source_fact_mix
        and _merges_cross_result_rankings(claim.text, facts)
        and not grounded_methodological_explanation
    ):
        claim_reasons.append(
            "Getrennte Tool-Ergebnisse dürfen nicht als eine gemeinsame "
            "Rangfolge dargestellt werden."
        )


def _vae_rule_analytical_prose(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6736-6744)."""
    if "_EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN" in _vae_ctx:
        _EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN = _vae_ctx["_EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN"]
    if "_STATISTICAL_CERTAINTY_PATTERN" in _vae_ctx:
        _STATISTICAL_CERTAINTY_PATTERN = _vae_ctx["_STATISTICAL_CERTAINTY_PATTERN"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if (
        _STATISTICAL_CERTAINTY_PATTERN.search(analytical_prose)
        and not _EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN.search(source_surface)
        and not negative_or_unknown_limitation
    ):
        claim_reasons.append(
            "Signifikanz oder Stabilität wird ohne explizite Schwelle, "
            "p-Wert- oder Konfidenzevidenz behauptet."
        )


def _vae_rule_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6778-6827)."""
    if "_CAUSAL_ASSERTION_PATTERN" in _vae_ctx:
        _CAUSAL_ASSERTION_PATTERN = _vae_ctx["_CAUSAL_ASSERTION_PATTERN"]
    if "_CROSS_TOOL_CAUSAL_PATTERN" in _vae_ctx:
        _CROSS_TOOL_CAUSAL_PATTERN = _vae_ctx["_CROSS_TOOL_CAUSAL_PATTERN"]
    if "_EXPLICIT_CAUSAL_EVIDENCE_PATTERN" in _vae_ctx:
        _EXPLICIT_CAUSAL_EVIDENCE_PATTERN = _vae_ctx["_EXPLICIT_CAUSAL_EVIDENCE_PATTERN"]
    if "_INFERENTIAL_OBSERVATION_PATTERN" in _vae_ctx:
        _INFERENTIAL_OBSERVATION_PATTERN = _vae_ctx["_INFERENTIAL_OBSERVATION_PATTERN"]
    if "_grounded_source_attributed_causal_reading" in _vae_ctx:
        _grounded_source_attributed_causal_reading = _vae_ctx["_grounded_source_attributed_causal_reading"]
    if "_has_unnegated_pattern" in _vae_ctx:
        _has_unnegated_pattern = _vae_ctx["_has_unnegated_pattern"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "cross_source_fact_mix" in _vae_ctx:
        cross_source_fact_mix = _vae_ctx["cross_source_fact_mix"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "grounded_methodological_explanation" in _vae_ctx:
        grounded_methodological_explanation = _vae_ctx["grounded_methodological_explanation"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if claim.claim_kind == "interpretation":
        if _has_unnegated_pattern(
            analytical_prose,
            _CAUSAL_ASSERTION_PATTERN,
        ) and not (
            grounded_methodological_explanation
            or _EXPLICIT_CAUSAL_EVIDENCE_PATTERN.search(source_surface)
            or _grounded_source_attributed_causal_reading(
                claim.text,
                facts,
            )
        ):
            claim_reasons.append(
                "Korpusbeobachtungen tragen eine vorsichtige Interpretation, "
                "aber ohne kausales Design keine Ursache-Wirkungs-Behauptung."
            )
    elif (
        claim.claim_kind == "observation"
        and (
            _has_unnegated_pattern(
                analytical_prose,
                _INFERENTIAL_OBSERVATION_PATTERN,
            )
            or (
                cross_source_fact_mix
                and _has_unnegated_pattern(
                    analytical_prose,
                    _CROSS_TOOL_CAUSAL_PATTERN,
                )
            )
        )
        and not grounded_methodological_explanation
    ):
        claim_reasons.append(
            "Inferentielle oder erklärende Aussagen müssen als "
            "Interpretation formuliert und verifiziert werden."
        )
    elif (
        claim.claim_kind == "limitation"
        and cross_source_fact_mix
        and _has_unnegated_pattern(
            analytical_prose,
            _CROSS_TOOL_CAUSAL_PATTERN,
        )
        and not grounded_methodological_explanation
    ):
        claim_reasons.append(
            "Eine Limitation darf getrennte Evidenzquellen nicht durch "
            "eine unbelegte Kausal- oder Korrelationsaussage verknüpfen."
        )


def _vae_rule_uses_technical_partition_as_content_axis(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6865-6874)."""
    if "_uses_technical_partition_as_content_axis" in _vae_ctx:
        _uses_technical_partition_as_content_axis = _vae_ctx["_uses_technical_partition_as_content_axis"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _uses_technical_partition_as_content_axis(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Eine technische Partition ist keine vorab fachliche "
            "Vergleichsachse. Formuliere den Vergleich als "
            "Datenqualitäts- oder Robustheitsprüfung und erhebe "
            "split-spezifische Nenner."
        )


def _vae_rule_claim_2(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6889-7061)."""
    if "_followup_confuses_context_with_reranking" in _vae_ctx:
        _followup_confuses_context_with_reranking = _vae_ctx["_followup_confuses_context_with_reranking"]
    if "_followup_infers_morphology_from_surface_frequency" in _vae_ctx:
        _followup_infers_morphology_from_surface_frequency = _vae_ctx["_followup_infers_morphology_from_surface_frequency"]
    if "_followup_presupposes_effect_without_design" in _vae_ctx:
        _followup_presupposes_effect_without_design = _vae_ctx["_followup_presupposes_effect_without_design"]
    if "_followup_presupposes_unobserved_relation" in _vae_ctx:
        _followup_presupposes_unobserved_relation = _vae_ctx["_followup_presupposes_unobserved_relation"]
    if "_followup_reasks_complete_metadata_inventory" in _vae_ctx:
        _followup_reasks_complete_metadata_inventory = _vae_ctx["_followup_reasks_complete_metadata_inventory"]
    if "_followup_reasks_known_singleton_axis" in _vae_ctx:
        _followup_reasks_known_singleton_axis = _vae_ctx["_followup_reasks_known_singleton_axis"]
    if "_followup_reasks_settled_denominator_scope" in _vae_ctx:
        _followup_reasks_settled_denominator_scope = _vae_ctx["_followup_reasks_settled_denominator_scope"]
    if "_followup_reasks_settled_frequency_normalization" in _vae_ctx:
        _followup_reasks_settled_frequency_normalization = _vae_ctx["_followup_reasks_settled_frequency_normalization"]
    if "_followup_reasks_settled_metadata_usability" in _vae_ctx:
        _followup_reasks_settled_metadata_usability = _vae_ctx["_followup_reasks_settled_metadata_usability"]
    if "_followup_uses_kwic_as_collocation_statistic" in _vae_ctx:
        _followup_uses_kwic_as_collocation_statistic = _vae_ctx["_followup_uses_kwic_as_collocation_statistic"]
    if "_frequency_substitutes_for_contextual_meaning" in _vae_ctx:
        _frequency_substitutes_for_contextual_meaning = _vae_ctx["_frequency_substitutes_for_contextual_meaning"]
    if "_is_data_quality_followup" in _vae_ctx:
        _is_data_quality_followup = _vae_ctx["_is_data_quality_followup"]
    if "_is_systematic_data_quality_followup" in _vae_ctx:
        _is_systematic_data_quality_followup = _vae_ctx["_is_systematic_data_quality_followup"]
    if "_presupposes_unseen_document_groups" in _vae_ctx:
        _presupposes_unseen_document_groups = _vae_ctx["_presupposes_unseen_document_groups"]
    if "_uses_collocation_as_syntax_method" in _vae_ctx:
        _uses_collocation_as_syntax_method = _vae_ctx["_uses_collocation_as_syntax_method"]
    if "anomalies_by_fact" in _vae_ctx:
        anomalies_by_fact = _vae_ctx["anomalies_by_fact"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "exhausted_fields" in _vae_ctx:
        exhausted_fields = _vae_ctx["exhausted_fields"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "handle" in _vae_ctx:
        handle = _vae_ctx["handle"]
    if "handles" in _vae_ctx:
        handles = _vae_ctx["handles"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if claim.claim_kind == "followup":
        if (
            len(
                {
                    handle
                    for handles in anomalies_by_fact.values()
                    for handle in handles
                }
            )
            > 1
            and _is_data_quality_followup(
                claim,
                anomalies_by_fact,
            )
            and not _is_systematic_data_quality_followup(
                claim,
                anomalies_by_fact,
            )
        ):
            claim_reasons.append(
                "Mehrere auffällige POS-Zeilen bilden ein systematisches "
                "Qualitätssignal; eine Qualitätsfrage darf nicht nur ein "
                "Einzelbeispiel verifizieren."
            )
        exhausted_fields = _followup_reasks_known_singleton_axis(
            claim.text,
            observed_facts,
        )
        if exhausted_fields:
            claim_reasons.append(
                "Die Anschlussfrage fragt erneut nach einer bereits vollständig "
                "belegten homogenen Metadatenachse: "
                + ", ".join(exhausted_fields[:4])
                + "."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_reasks_complete_metadata_inventory(
                claim.text,
                observed_facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage fragt erneut nach dem bereits vollständig "
                "belegten Metadateninventar."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_reasks_settled_metadata_usability(
                claim.text,
                observed_facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage fragt erneut nach der bereits aus dem "
                "vollständigen Metadateninventar beantworteten Eignung oder "
                "Homogenität der Vergleichsachsen."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_reasks_settled_denominator_scope(
                claim.text,
                observed_facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage fragt erneut nach dem bereits explizit "
                "ausgewiesenen Scope des Normalisierungsnenners."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_reasks_settled_frequency_normalization(
                claim.text,
                observed_facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage fragt erneut nach einer bereits "
                "vorgerechneten per_million-Normalisierung mit explizitem "
                "Korpus- oder Docset-Nenner."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_confuses_context_with_reranking(claim.text)
        ):
            claim_reasons.append(
                "KWIC-, Kollokations- oder Kontextanalyse erklärt lokale "
                "Verwendungen, berechnet aber ohne veränderte Auswahl, "
                "Filterung oder Zähleinheit keine neue Frequenzrangfolge."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_uses_kwic_as_collocation_statistic(
                claim.text
            )
        ):
            claim_reasons.append(
                "KWIC illustriert Kontexte, ersetzt aber keine "
                "Kollokationsstatistik mit definiertem Knoten, Fenster "
                "und Assoziationsmaß."
            )
        if (
            deliverable_kind == "followup_questions"
            and _presupposes_unseen_document_groups(
                claim.text,
                facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage setzt Dokumentgruppen, Register oder "
                "Teilkorpora voraus, die in der referenzierten Evidenz "
                "nicht ausgewiesen sind; formuliere die Voraussetzung "
                "explizit oder erhebe zuerst die Metadaten."
            )
        if (
            deliverable_kind == "followup_questions"
            and _uses_collocation_as_syntax_method(claim.text)
        ):
            claim_reasons.append(
                "Fensterkollokationen allein operationalisieren keine "
                "syntaktischen oder grammatischen Relationen; die Frage "
                "braucht dafür eine explizite Relations-, Kolligations- "
                "oder Kontextmethode."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_presupposes_effect_without_design(
                claim.text,
                facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage setzt einen Einfluss oder Effekt "
                "bereits voraus. Ohne kausales Design muss sie "
                "ergebnisoffen nach einem prüfbaren Zusammenhang fragen."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_presupposes_unobserved_relation(
                claim.text,
                facts,
            )
        ):
            claim_reasons.append(
                "Die Anschlussfrage setzt eine noch nicht gemessene "
                "Kollokation oder Relation bereits voraus. Formuliere sie "
                "ergebnisoffen als Prüfung, ob die Relation in einer "
                "benannten Kontext- oder Beobachtungseinheit besteht."
            )
        if (
            deliverable_kind == "followup_questions"
            and _frequency_substitutes_for_contextual_meaning(
                claim.text
            )
        ):
            claim_reasons.append(
                "Eine Frequenzanalyse misst Häufigkeit und Rang, aber "
                "keine Bedeutung oder Gebrauchsweise im Kontext; die "
                "Anschlussfrage muss dafür eine konkrete Kontextanalyse "
                "benennen."
            )
        if (
            deliverable_kind == "followup_questions"
            and _followup_infers_morphology_from_surface_frequency(
                claim.text,
                facts,
            )
        ):
            claim_reasons.append(
                "Wortformfrequenzen wählen Kandidaten aus, belegen aber "
                "ohne Lemma-, Morphologie- oder Kontextanalyse noch keine "
                "Singular-, Plural- oder andere Flexionskategorie."
            )
    _vae_l = locals()
    for _vae_n in ("exhausted_fields", "handle", "handles"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_deliverable_kind(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7062-7152)."""
    if "_LEMMA_ANNOTATION_QA_PATTERN" in _vae_ctx:
        _LEMMA_ANNOTATION_QA_PATTERN = _vae_ctx["_LEMMA_ANNOTATION_QA_PATTERN"]
    if "_MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN" in _vae_ctx:
        _MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN = _vae_ctx["_MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN"]
    if "_REDUNDANT_LEMMA_ANALYSIS_PATTERN" in _vae_ctx:
        _REDUNDANT_LEMMA_ANALYSIS_PATTERN = _vae_ctx["_REDUNDANT_LEMMA_ANALYSIS_PATTERN"]
    if "_claim_has_structural_fact_anchor" in _vae_ctx:
        _claim_has_structural_fact_anchor = _vae_ctx["_claim_has_structural_fact_anchor"]
    if "_claim_mentions_specific_fact_anchor" in _vae_ctx:
        _claim_mentions_specific_fact_anchor = _vae_ctx["_claim_mentions_specific_fact_anchor"]
    if "_followup_reasks_known_singleton_axis" in _vae_ctx:
        _followup_reasks_known_singleton_axis = _vae_ctx["_followup_reasks_known_singleton_axis"]
    if "_frequency_substitutes_for_contextual_meaning" in _vae_ctx:
        _frequency_substitutes_for_contextual_meaning = _vae_ctx["_frequency_substitutes_for_contextual_meaning"]
    if "_metadata_homogeneity_is_prejudged" in _vae_ctx:
        _metadata_homogeneity_is_prejudged = _vae_ctx["_metadata_homogeneity_is_prejudged"]
    if "_method_step_text_ordinal" in _vae_ctx:
        _method_step_text_ordinal = _vae_ctx["_method_step_text_ordinal"]
    if "_pos_filtered_lexicon_called_pos_distribution" in _vae_ctx:
        _pos_filtered_lexicon_called_pos_distribution = _vae_ctx["_pos_filtered_lexicon_called_pos_distribution"]
    if "_strip_redundant_method_step_ordinal" in _vae_ctx:
        _strip_redundant_method_step_ordinal = _vae_ctx["_strip_redundant_method_step_ordinal"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "detail" in _vae_ctx:
        detail = _vae_ctx["detail"]
    if "embedded_ordinal" in _vae_ctx:
        embedded_ordinal = _vae_ctx["embedded_ordinal"]
    if "exhausted_fields" in _vae_ctx:
        exhausted_fields = _vae_ctx["exhausted_fields"]
    if "expected_ordinal" in _vae_ctx:
        expected_ordinal = _vae_ctx["expected_ordinal"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "lemma_grouping_evidence" in _vae_ctx:
        lemma_grouping_evidence = _vae_ctx["lemma_grouping_evidence"]
    if "method_step_positions" in _vae_ctx:
        method_step_positions = _vae_ctx["method_step_positions"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if "repaired_method_text" in _vae_ctx:
        repaired_method_text = _vae_ctx["repaired_method_text"]
    if (
        deliverable_kind == "method_advice"
        and claim.claim_kind == "interpretation"
    ):
        repaired_method_text = _strip_redundant_method_step_ordinal(
            claim.text
        )
        embedded_ordinal = _method_step_text_ordinal(repaired_method_text)
        expected_ordinal = method_step_positions.get(claim.id)
        if embedded_ordinal is not None:
            detail = (
                f" ({embedded_ordinal} statt {expected_ordinal})"
                if expected_ordinal is not None
                and embedded_ordinal != expected_ordinal
                else ""
            )
            claim_reasons.append(
                "Die Darstellung nummeriert Analyseschritte bereits; eine "
                "eingebettete Schrittnummer erzeugt eine doppelte oder "
                f"widersprüchliche Nummerierung{detail}."
            )
        if (
            not _claim_mentions_specific_fact_anchor(claim.text, facts)
            and not _claim_has_structural_fact_anchor(claim.text, facts)
        ):
            claim_reasons.append(
                "Der Analyseschritt benennt keinen konkreten sichtbaren "
                "Wert oder Befund aus den referenzierten Facts als "
                "Motivation."
            )
        if (
            any(fact.fact_kind == "metadata" for fact in facts)
            and _metadata_homogeneity_is_prejudged(claim.text, facts)
        ):
            claim_reasons.append(
                "Der Analyseschritt setzt Metadatenhomogenität bereits als "
                "zu bestätigendes Ergebnis voraus; ohne Abdeckungs- und "
                "Fehlwertzählung muss er sie ergebnisoffen prüfen."
            )
        if _frequency_substitutes_for_contextual_meaning(claim.text):
            claim_reasons.append(
                "Eine Frequenzanalyse misst Häufigkeit und Rang, aber "
                "keine Bedeutung oder Gebrauchsweise im Kontext; dafür "
                "muss der Schritt eine konkrete Kontextanalyse benennen."
            )
        if _pos_filtered_lexicon_called_pos_distribution(
            claim.text,
            facts,
        ):
            claim_reasons.append(
                "Die referenzierte Auswertung ist nach Wort oder Lemma "
                "gruppiert und lediglich durch POS gefiltert. Sie misst "
                "lexikalische Häufigkeiten innerhalb der gewählten "
                "Wortart, nicht die Verteilung von POS-Kategorien."
            )
        exhausted_fields = _followup_reasks_known_singleton_axis(
            claim.text,
            observed_facts,
        )
        if exhausted_fields:
            claim_reasons.append(
                "Für die genannte Metadatenachse ist im aktiven Scope "
                "bereits nur ein Wert belegt; ein interner Vergleich über "
                "diese Achse ist daher nicht verfügbar: "
                + ", ".join(exhausted_fields[:4])
                + ". Nutze dies als Scope-Grenze statt die Eignung erneut "
                "offenzulassen."
            )
        if (
            lemma_grouping_evidence
            and _REDUNDANT_LEMMA_ANALYSIS_PATTERN.search(claim.text)
            and _LEMMA_ANNOTATION_QA_PATTERN.search(claim.text) is None
        ):
            claim_reasons.append(
                "Die sichtbare Frequenzliste ist bereits nach Lemma "
                "gruppiert. Ein weiterer Schritt darf die ausgegebenen "
                "Zeilen nicht erneut als ungeklärte Wortformen behandeln; "
                "auffällige Werte motivieren stattdessen Annotations-QA."
            )
        if (
            any(fact.fact_kind == "metadata" for fact in facts)
            and _MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN.search(
                claim.text
            )
        ):
            claim_reasons.append(
                "metadata_values inventarisiert bereits das aktive Korpus. "
                "Mehr Dokumente desselben Inventars erzeugen keine neue "
                "Feldvarianz; prüfe stattdessen Abdeckung, Fehlwerte oder "
                "eine andere sichtbare Evidenz."
            )
    _vae_l = locals()
    for _vae_n in ("detail", "embedded_ordinal", "exhausted_fields", "expected_ordinal", "fact", "repaired_method_text"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_near_duplicate_research_question(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7153-7165)."""
    if "_near_duplicate_research_question" in _vae_ctx:
        _near_duplicate_research_question = _vae_ctx["_near_duplicate_research_question"]
    if "accepted_followup_texts" in _vae_ctx:
        accepted_followup_texts = _vae_ctx["accepted_followup_texts"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "previous" in _vae_ctx:
        previous = _vae_ctx["previous"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and any(
            _near_duplicate_research_question(claim.text, previous)
            for previous in accepted_followup_texts
        )
    ):
        claim_reasons.append(
            "Die Anschlussfrage wiederholt inhaltlich bereits eine zuvor "
            "akzeptierte Frage und liefert keinen eigenständigen "
            "Forschungsansatz."
        )
    _vae_l = locals()
    for _vae_n in ("previous",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_followup_correlation_is_operationalised(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7166-7175)."""
    if "_followup_correlation_is_operationalised" in _vae_ctx:
        _followup_correlation_is_operationalised = _vae_ctx["_followup_correlation_is_operationalised"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and not _followup_correlation_is_operationalised(claim.text)
    ):
        claim_reasons.append(
            "Eine Korrelationsfrage muss eine Beobachtungseinheit wie "
            "Dokument, Zeitraum, Teilkorpus oder Gruppe benennen; globale "
            "Korpusfrequenzen allein bilden keine Korrelation."
        )


def _vae_rule_followup_mixes_aggregate_and_token_validation(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7176-7187)."""
    if "_followup_mixes_aggregate_and_token_validation" in _vae_ctx:
        _followup_mixes_aggregate_and_token_validation = _vae_ctx["_followup_mixes_aggregate_and_token_validation"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and _followup_mixes_aggregate_and_token_validation(claim.text)
    ):
        claim_reasons.append(
            "Aggregierte POS-Frequenzen und eine manuelle "
            "Tokenisierungsstichprobe liegen auf verschiedenen "
            "Granularitäten und prüfen verschiedene Aufgaben. "
            "POS-Qualität braucht gepaarte System-/Goldlabels pro Token; "
            "Token-Grenzen werden davon getrennt geprüft."
        )


def _vae_rule_followup_uses_sentence_length_as_complexity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7188-7197)."""
    if "_followup_uses_sentence_length_as_complexity" in _vae_ctx:
        _followup_uses_sentence_length_as_complexity = _vae_ctx["_followup_uses_sentence_length_as_complexity"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and _followup_uses_sentence_length_as_complexity(claim.text)
    ):
        claim_reasons.append(
            "Satzlänge ist ohne eigenständige Validierung kein Maß für "
            "strukturelle oder syntaktische Komplexität. Benenne sie als "
            "Längenmaß oder prüfe ausdrücklich ihre Eignung als Proxy."
        )


def _vae_rule_distribution_substitutes_for_thematic_analysis(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7209-7227)."""
    if "_distribution_substitutes_for_thematic_analysis" in _vae_ctx:
        _distribution_substitutes_for_thematic_analysis = _vae_ctx["_distribution_substitutes_for_thematic_analysis"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        (
            deliverable_kind == "followup_questions"
            and claim.claim_kind == "followup"
        )
        or (
            deliverable_kind == "method_advice"
            and claim.claim_kind == "interpretation"
        )
    ) and _distribution_substitutes_for_thematic_analysis(
        claim.text
    ):
        claim_reasons.append(
            "Dokumentverteilung oder Dispersion misst Streuung und "
            "Konzentration, aber keine thematische oder semantische "
            "Reichweite. Dafür braucht der Schritt zusätzlich eine "
            "explizite Kontextanalyse; andernfalls muss das Erkenntnisziel "
            "auf Verteilungsbreite begrenzt bleiben."
        )


def _vae_rule_distribution_substitutes_for_function_analysis(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7228-7245)."""
    if "_distribution_substitutes_for_function_analysis" in _vae_ctx:
        _distribution_substitutes_for_function_analysis = _vae_ctx["_distribution_substitutes_for_function_analysis"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        (
            deliverable_kind == "followup_questions"
            and claim.claim_kind == "followup"
        )
        or (
            deliverable_kind == "method_advice"
            and claim.claim_kind == "interpretation"
        )
    ) and _distribution_substitutes_for_function_analysis(
        claim.text
    ):
        claim_reasons.append(
            "Dispersion oder Dokumentkonzentration misst Verteilung, aber "
            "nicht die kommunikative Funktion oder Akteursrolle einer "
            "Wortform. Dafür braucht der Schritt zusätzlich eine "
            "explizite Kontext- oder Relationsanalyse."
        )


def _vae_rule_pos_inventory_substitutes_for_morphosyntax(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7246-7264)."""
    if "_pos_inventory_substitutes_for_morphosyntax" in _vae_ctx:
        _pos_inventory_substitutes_for_morphosyntax = _vae_ctx["_pos_inventory_substitutes_for_morphosyntax"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        (
            deliverable_kind == "followup_questions"
            and claim.claim_kind == "followup"
        )
        or (
            deliverable_kind == "method_advice"
            and claim.claim_kind == "interpretation"
        )
    ) and _pos_inventory_substitutes_for_morphosyntax(
        claim.text
    ):
        claim_reasons.append(
            "Ein POS-Inventar misst die Verteilung von Wortartlabels, "
            "aber keine morphosyntaktische Struktur. Dafür braucht der "
            "Schritt eine explizite morphologische oder syntaktische "
            "Relationsanalyse; alternativ ist das Ziel auf "
            "POS-Abdeckung zu begrenzen."
        )


def _vae_rule_collocation_substitutes_for_discourse_function(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7265-7282)."""
    if "_collocation_substitutes_for_discourse_function" in _vae_ctx:
        _collocation_substitutes_for_discourse_function = _vae_ctx["_collocation_substitutes_for_discourse_function"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        (
            deliverable_kind == "followup_questions"
            and claim.claim_kind == "followup"
        )
        or (
            deliverable_kind == "method_advice"
            and claim.claim_kind == "interpretation"
        )
    ) and _collocation_substitutes_for_discourse_function(
        claim.text
    ):
        claim_reasons.append(
            "Kollokationsstatistik misst lokale Assoziation, bestimmt "
            "aber allein keine diskursive Valenz, Haltung oder "
            "Abwertungsfunktion. Dafür muss der Schritt eine qualitative "
            "KWIC-, Kontext- oder Kodierungsprüfung anschließen."
        )


def _vae_rule_local_association_lacks_collocation_design(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7283-7295)."""
    if "_local_association_lacks_collocation_design" in _vae_ctx:
        _local_association_lacks_collocation_design = _vae_ctx["_local_association_lacks_collocation_design"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and _local_association_lacks_collocation_design(
            claim.text
        )
    ):
        claim_reasons.append(
            "Eine Frage nach lokaler Assoziation braucht für eine "
            "Kollokationsanalyse mindestens eine Kontext- oder "
            "Fenstereinheit und eine Referenz wie Randfrequenzen, "
            "Nullmodell oder Assoziationsmaß."
        )


def _vae_rule_accounting_gap_lacks_token_reconciliation(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7296-7309)."""
    if "_accounting_gap_lacks_token_reconciliation" in _vae_ctx:
        _accounting_gap_lacks_token_reconciliation = _vae_ctx["_accounting_gap_lacks_token_reconciliation"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and _accounting_gap_lacks_token_reconciliation(
            claim.text
        )
    ):
        claim_reasons.append(
            "Eine Differenz zwischen Kategoriefrequenzen und Gesamtzahl "
            "ist zuerst ein Abdeckungs- oder Zählproblem, nicht bereits "
            "Tagging-Qualität. Gleiche die Grundgesamtheit tokenweise mit "
            "gruppierten, fehlenden und ausgeschlossenen Werten ab; "
            "Korrektheit erfordert danach getrennt Goldlabels."
        )


def _vae_rule_claim_mentions_specific_fact_anchor(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7310-7319)."""
    if "_claim_has_structural_fact_anchor" in _vae_ctx:
        _claim_has_structural_fact_anchor = _vae_ctx["_claim_has_structural_fact_anchor"]
    if "_claim_mentions_specific_fact_anchor" in _vae_ctx:
        _claim_mentions_specific_fact_anchor = _vae_ctx["_claim_mentions_specific_fact_anchor"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if (
        deliverable_kind == "followup_questions"
        and claim.claim_kind == "followup"
        and not _claim_mentions_specific_fact_anchor(claim.text, facts)
        and not _claim_has_structural_fact_anchor(claim.text, facts)
    ):
        claim_reasons.append(
            "Die Anschlussfrage benennt keine konkrete sichtbare Evidenz "
            "aus den referenzierten Facts als Motivation."
        )


def _vae_rule_overview_observation_is_provenance_only(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7320-7329)."""
    if "_overview_observation_is_provenance_only" in _vae_ctx:
        _overview_observation_is_provenance_only = _vae_ctx["_overview_observation_is_provenance_only"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if (
        deliverable_kind == "overview"
        and claim.claim_kind == "observation"
        and _overview_observation_is_provenance_only(facts)
    ):
        claim_reasons.append(
            "Korpusgröße oder Rückgabeform dokumentieren die "
            "Datengrundlage, zählen aber nicht als eigenständiger "
            "inhaltlicher Befund eines Forschungsüberblicks."
        )


def _vae_rule_analytical_prose_2(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7330-7350)."""
    if "_NUMERIC_PERCENT_PATTERN" in _vae_ctx:
        _NUMERIC_PERCENT_PATTERN = _vae_ctx["_NUMERIC_PERCENT_PATTERN"]
    if "_PERCENT_PATTERN" in _vae_ctx:
        _PERCENT_PATTERN = _vae_ctx["_PERCENT_PATTERN"]
    if "_numeric_percent_tokens" in _vae_ctx:
        _numeric_percent_tokens = _vae_ctx["_numeric_percent_tokens"]
    if "_percent_token_is_supported" in _vae_ctx:
        _percent_token_is_supported = _vae_ctx["_percent_token_is_supported"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "numeric_percent_tokens" in _vae_ctx:
        numeric_percent_tokens = _vae_ctx["numeric_percent_tokens"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "token" in _vae_ctx:
        token = _vae_ctx["token"]
    if "transparently_derived_percent" in _vae_ctx:
        transparently_derived_percent = _vae_ctx["transparently_derived_percent"]
    if (
        _PERCENT_PATTERN.search(analytical_prose)
        and not (
            negative_or_unknown_limitation
            and not _NUMERIC_PERCENT_PATTERN.search(analytical_prose)
        )
    ):
        numeric_percent_tokens = _numeric_percent_tokens(
            analytical_prose
        )
        transparently_derived_percent = bool(
            numeric_percent_tokens
        ) and all(
            _percent_token_is_supported(token, source_surface)
            for token in numeric_percent_tokens
        )
        if not (
            any("percentages" in fact.supports_claims for fact in facts)
            or transparently_derived_percent
        ):
            claim_reasons.append("Prozent- oder Anteilsclaim ohne Prozent-Evidenz.")
    _vae_l = locals()
    for _vae_n in ("fact", "numeric_percent_tokens", "token", "transparently_derived_percent"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_is_rank_range_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7351-7374)."""
    if "_extract_ranges" in _vae_ctx:
        _extract_ranges = _vae_ctx["_extract_ranges"]
    if "_has_word_range_claim" in _vae_ctx:
        _has_word_range_claim = _vae_ctx["_has_word_range_claim"]
    if "_is_rank_range_claim" in _vae_ctx:
        _is_rank_range_claim = _vae_ctx["_is_rank_range_claim"]
    if "_range_is_covered_by_numbers" in _vae_ctx:
        _range_is_covered_by_numbers = _vae_ctx["_range_is_covered_by_numbers"]
    if "allowed_numbers" in _vae_ctx:
        allowed_numbers = _vae_ctx["allowed_numbers"]
    if "allowed_ranges" in _vae_ctx:
        allowed_ranges = _vae_ctx["allowed_ranges"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "range_token" in _vae_ctx:
        range_token = _vae_ctx["range_token"]
    if "ranges" in _vae_ctx:
        ranges = _vae_ctx["ranges"]
    ranges = _extract_ranges(claim.text)
    if _is_rank_range_claim(claim.text):
        if not any("ranks" in fact.supports_claims for fact in facts):
            claim_reasons.append("Rangbereich ohne Rank-Evidenz.")
        elif ranges and any(
            range_token not in allowed_ranges
            and not _range_is_covered_by_numbers(
                range_token,
                allowed_numbers,
            )
            for range_token in ranges
        ):
            claim_reasons.append("Rangbereich nicht in der Evidenz sichtbar.")
        elif _has_word_range_claim(claim.text) and not ranges:
            claim_reasons.append("Verbaler Rangbereich ist nicht direkt in der Evidenz sichtbar.")
    elif ranges and any(
        range_token not in allowed_ranges
        and not _range_is_covered_by_numbers(
            range_token,
            allowed_numbers,
        )
        for range_token in ranges
    ):
        claim_reasons.append("Numerischer Bereich ist nicht in der Evidenz sichtbar.")
    _vae_l = locals()
    for _vae_n in ("fact", "range_token", "ranges"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_numeric_tokens(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7375-7413)."""
    if "_explicit_percent_binding_status" in _vae_ctx:
        _explicit_percent_binding_status = _vae_ctx["_explicit_percent_binding_status"]
    if "_extract_numeric_tokens_outside_spans" in _vae_ctx:
        _extract_numeric_tokens_outside_spans = _vae_ctx["_extract_numeric_tokens_outside_spans"]
    if "_numeric_percent_tokens" in _vae_ctx:
        _numeric_percent_tokens = _vae_ctx["_numeric_percent_tokens"]
    if "_numeric_token_is_supported" in _vae_ctx:
        _numeric_token_is_supported = _vae_ctx["_numeric_token_is_supported"]
    if "_percent_token_is_supported" in _vae_ctx:
        _percent_token_is_supported = _vae_ctx["_percent_token_is_supported"]
    if "_rate_binding_status" in _vae_ctx:
        _rate_binding_status = _vae_ctx["_rate_binding_status"]
    if "_ratio_comparison_binding_status" in _vae_ctx:
        _ratio_comparison_binding_status = _vae_ctx["_ratio_comparison_binding_status"]
    if "_without_claim_step_ordinals" in _vae_ctx:
        _without_claim_step_ordinals = _vae_ctx["_without_claim_step_ordinals"]
    if "allowed_numbers" in _vae_ctx:
        allowed_numbers = _vae_ctx["allowed_numbers"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "numeric_claim_text" in _vae_ctx:
        numeric_claim_text = _vae_ctx["numeric_claim_text"]
    if "numeric_tokens" in _vae_ctx:
        numeric_tokens = _vae_ctx["numeric_tokens"]
    if "percent_tokens" in _vae_ctx:
        percent_tokens = _vae_ctx["percent_tokens"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "supported_percent_value_spans" in _vae_ctx:
        supported_percent_value_spans = _vae_ctx["supported_percent_value_spans"]
    if "supported_rate_value_spans" in _vae_ctx:
        supported_rate_value_spans = _vae_ctx["supported_rate_value_spans"]
    if "supported_ratio_factor_spans" in _vae_ctx:
        supported_ratio_factor_spans = _vae_ctx["supported_ratio_factor_spans"]
    if "token" in _vae_ctx:
        token = _vae_ctx["token"]
    if "unsupported_numbers" in _vae_ctx:
        unsupported_numbers = _vae_ctx["unsupported_numbers"]
    numeric_claim_text = _without_claim_step_ordinals(claim.text)
    (
        unsupported_ratio_bindings,
        supported_ratio_factor_spans,
    ) = _ratio_comparison_binding_status(
        numeric_claim_text,
        facts,
    )
    unsupported_rate_bindings, supported_rate_value_spans = (
        _rate_binding_status(numeric_claim_text, facts)
    )
    unsupported_percent_bindings, supported_percent_value_spans = (
        _explicit_percent_binding_status(numeric_claim_text, facts)
    )
    numeric_tokens = _extract_numeric_tokens_outside_spans(
        numeric_claim_text,
        [
            *supported_ratio_factor_spans,
            *supported_rate_value_spans,
            *supported_percent_value_spans,
        ],
    )
    percent_tokens = _numeric_percent_tokens(analytical_prose)
    if numeric_tokens:
        unsupported_numbers = [
            token
            for token in numeric_tokens
            if not (
                _percent_token_is_supported(token, source_surface)
                if token in percent_tokens
                else _numeric_token_is_supported(token, allowed_numbers)
            )
        ]
        if unsupported_numbers:
            claim_reasons.append(
                "Numerische Claims führen nicht belegte Werte ein: "
                + ", ".join(unsupported_numbers[:4])
                + "."
            )
    _vae_l = locals()
    for _vae_n in ("numeric_claim_text", "numeric_tokens", "percent_tokens", "supported_percent_value_spans", "supported_rate_value_spans", "supported_ratio_factor_spans", "token", "unsupported_numbers", "unsupported_percent_bindings", "unsupported_rate_bindings", "unsupported_ratio_bindings"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_count_bindings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7414-7423)."""
    if "_unsupported_count_bindings" in _vae_ctx:
        _unsupported_count_bindings = _vae_ctx["_unsupported_count_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_count_bindings" in _vae_ctx:
        unsupported_count_bindings = _vae_ctx["unsupported_count_bindings"]
    unsupported_count_bindings = _unsupported_count_bindings(
        analytical_prose,
        source_surface,
    )
    if unsupported_count_bindings:
        claim_reasons.append(
            "Count-Claims verwenden Werte aus einer anderen Metrik: "
            + ", ".join(unsupported_count_bindings[:4])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_count_bindings",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_ratio_bindings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7424-7430)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "unsupported_ratio_bindings" in _vae_ctx:
        unsupported_ratio_bindings = _vae_ctx["unsupported_ratio_bindings"]
    if unsupported_ratio_bindings:
        claim_reasons.append(
            "Vergleichende Häufigkeitsfaktoren stimmen nicht mit den "
            "referenzierten Zeilen überein: "
            + ", ".join(unsupported_ratio_bindings[:3])
            + "."
        )


def _vae_rule_unsupported_rate_bindings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7431-7437)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "unsupported_rate_bindings" in _vae_ctx:
        unsupported_rate_bindings = _vae_ctx["unsupported_rate_bindings"]
    if unsupported_rate_bindings:
        claim_reasons.append(
            "Normalisierte Raten stimmen nicht mit Zähler und Nenner der "
            "referenzierten Evidenz überein: "
            + ", ".join(unsupported_rate_bindings[:3])
            + "."
        )


def _vae_rule_unsupported_percent_bindings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7438-7444)."""
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "unsupported_percent_bindings" in _vae_ctx:
        unsupported_percent_bindings = _vae_ctx["unsupported_percent_bindings"]
    if unsupported_percent_bindings:
        claim_reasons.append(
            "Explizite Prozentrechnungen vertauschen Zähler oder Nenner "
            "oder ergeben nicht den genannten Anteil: "
            + ", ".join(unsupported_percent_bindings[:3])
            + "."
        )


def _vae_rule_unsupported_elliptical_counts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7445-7457)."""
    if "_unsupported_elliptical_count_bindings" in _vae_ctx:
        _unsupported_elliptical_count_bindings = _vae_ctx["_unsupported_elliptical_count_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_elliptical_counts" in _vae_ctx:
        unsupported_elliptical_counts = _vae_ctx["unsupported_elliptical_counts"]
    unsupported_elliptical_counts = (
        _unsupported_elliptical_count_bindings(
            analytical_prose,
            facts,
        )
    )
    if unsupported_elliptical_counts:
        claim_reasons.append(
            "Elliptische Count-Vergleiche vertauschen oder lösen die "
            "Werte von ihren referenzierten Zeilen: "
            + ", ".join(unsupported_elliptical_counts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_elliptical_counts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_postposed_counts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7458-7470)."""
    if "_unsupported_postposed_count_bindings" in _vae_ctx:
        _unsupported_postposed_count_bindings = _vae_ctx["_unsupported_postposed_count_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_postposed_counts" in _vae_ctx:
        unsupported_postposed_counts = _vae_ctx["unsupported_postposed_counts"]
    unsupported_postposed_counts = (
        _unsupported_postposed_count_bindings(
            analytical_prose,
            facts,
        )
    )
    if unsupported_postposed_counts:
        claim_reasons.append(
            "Nachgestellte elliptische Count-Vergleiche vertauschen oder "
            "lösen Werte von ihren referenzierten Zeilen: "
            + ", ".join(unsupported_postposed_counts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_postposed_counts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_unit_free_counts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7471-7483)."""
    if "_unsupported_unit_free_row_counts" in _vae_ctx:
        _unsupported_unit_free_row_counts = _vae_ctx["_unsupported_unit_free_row_counts"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_unit_free_counts" in _vae_ctx:
        unsupported_unit_free_counts = _vae_ctx["unsupported_unit_free_counts"]
    unsupported_unit_free_counts = (
        _unsupported_unit_free_row_counts(
            analytical_prose,
            facts,
        )
    )
    if unsupported_unit_free_counts:
        claim_reasons.append(
            "Einheitenlose elliptische Count-Vergleiche vertauschen "
            "Werte zwischen den referenzierten Zeilen: "
            + ", ".join(unsupported_unit_free_counts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_unit_free_counts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_word_percent_bindings(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7484-7496)."""
    if "_unsupported_word_percent_bindings" in _vae_ctx:
        _unsupported_word_percent_bindings = _vae_ctx["_unsupported_word_percent_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_word_percent_bindings" in _vae_ctx:
        unsupported_word_percent_bindings = _vae_ctx["unsupported_word_percent_bindings"]
    unsupported_word_percent_bindings = (
        _unsupported_word_percent_bindings(
            analytical_prose,
            source_surface,
        )
    )
    if unsupported_word_percent_bindings:
        claim_reasons.append(
            "Ausgeschriebene Prozentwerte sind nicht an einer "
            "Prozent- oder Ratio-Metrik belegt: "
            + ", ".join(unsupported_word_percent_bindings[:4])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_word_percent_bindings",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_natural_metrics(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7497-7507)."""
    if "_unsupported_natural_metric_bindings" in _vae_ctx:
        _unsupported_natural_metric_bindings = _vae_ctx["_unsupported_natural_metric_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_natural_metrics" in _vae_ctx:
        unsupported_natural_metrics = _vae_ctx["unsupported_natural_metrics"]
    unsupported_natural_metrics = _unsupported_natural_metric_bindings(
        analytical_prose,
        source_surface,
    )
    if unsupported_natural_metrics:
        claim_reasons.append(
            "Natürlich formulierte Metrikwerte sind nicht am "
            "genannten Evidenzfeld belegt: "
            + ", ".join(unsupported_natural_metrics[:4])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_natural_metrics",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_metric_maxima(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7508-7519)."""
    if "_unsupported_metric_maximum_claims" in _vae_ctx:
        _unsupported_metric_maximum_claims = _vae_ctx["_unsupported_metric_maximum_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if "unsupported_metric_maxima" in _vae_ctx:
        unsupported_metric_maxima = _vae_ctx["unsupported_metric_maxima"]
    unsupported_metric_maxima = _unsupported_metric_maximum_claims(
        analytical_prose,
        facts,
        observed_facts,
    )
    if unsupported_metric_maxima:
        claim_reasons.append(
            "Ein behauptetes Metrikmaximum stimmt nicht mit sämtlichen "
            "sichtbaren Zeilen desselben Ergebnisses überein: "
            + ", ".join(unsupported_metric_maxima[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_metric_maxima",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_metric_ranges(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7520-7533)."""
    if "_unsupported_result_wide_metric_ranges" in _vae_ctx:
        _unsupported_result_wide_metric_ranges = _vae_ctx["_unsupported_result_wide_metric_ranges"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if "unsupported_metric_ranges" in _vae_ctx:
        unsupported_metric_ranges = _vae_ctx["unsupported_metric_ranges"]
    unsupported_metric_ranges = (
        _unsupported_result_wide_metric_ranges(
            analytical_prose,
            facts,
            observed_facts,
        )
    )
    if unsupported_metric_ranges:
        claim_reasons.append(
            "Eine als ergebnisweit formulierte Metrikspanne lässt "
            "sichtbare Extremwerte desselben Ergebnisses aus: "
            + ", ".join(unsupported_metric_ranges[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_metric_ranges",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_rate_denominators(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7534-7546)."""
    if "_unsupported_rate_denominator_bindings" in _vae_ctx:
        _unsupported_rate_denominator_bindings = _vae_ctx["_unsupported_rate_denominator_bindings"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_rate_denominators" in _vae_ctx:
        unsupported_rate_denominators = _vae_ctx["unsupported_rate_denominators"]
    unsupported_rate_denominators = (
        _unsupported_rate_denominator_bindings(
            analytical_prose,
            source_surface,
        )
    )
    if unsupported_rate_denominators:
        claim_reasons.append(
            "Der natürliche Normalisierungsnenner stimmt nicht mit "
            "denominator_tokens und denominator_scope überein: "
            + ", ".join(unsupported_rate_denominators[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_rate_denominators",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_assignments(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7547-7557)."""
    if "_unsupported_field_assignments" in _vae_ctx:
        _unsupported_field_assignments = _vae_ctx["_unsupported_field_assignments"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    if "unsupported_assignments" in _vae_ctx:
        unsupported_assignments = _vae_ctx["unsupported_assignments"]
    unsupported_assignments = _unsupported_field_assignments(
        claim.text,
        source_surface,
    )
    if unsupported_assignments:
        claim_reasons.append(
            "Explizite Feld-Wert-Claims sind nicht am gleichnamigen "
            "Evidenzfeld belegt: "
            + ", ".join(unsupported_assignments[:4])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_assignments",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_row_field_assignments_are_atomic(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7561-7565)."""
    if "_row_field_assignments_are_atomic" in _vae_ctx:
        _row_field_assignments_are_atomic = _vae_ctx["_row_field_assignments_are_atomic"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    # Row labels often appear as quoted lexical items. Keep them for the
    # atomicity check; stripping quoted spans leaves the metrics behind and
    # can make a valid multi-row claim look unbound.
    if not _row_field_assignments_are_atomic(claim.text, facts):
        claim_reasons.append(
            "Zeilengebundene Feld-Wert-Claims müssen gemeinsam in "
            "demselben Observed Fact belegt sein."
        )


def _vae_rule_RAW_TRUNCATION_MARKER_PATTERN(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7566-7571)."""
    if "_RAW_TRUNCATION_MARKER_PATTERN" in _vae_ctx:
        _RAW_TRUNCATION_MARKER_PATTERN = _vae_ctx["_RAW_TRUNCATION_MARKER_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if _RAW_TRUNCATION_MARKER_PATTERN.search(claim.text):
        claim_reasons.append(
            "Der interne Marker truncated=... gehört nicht in die "
            "Nutzerantwort; seine methodische Bedeutung muss in natürlicher "
            "Sprache formuliert werden."
        )


def _vae_rule_INTERNAL_GROUNDING_MARKER_PATTERN(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7572-7576)."""
    if "_INTERNAL_GROUNDING_MARKER_PATTERN" in _vae_ctx:
        _INTERNAL_GROUNDING_MARKER_PATTERN = _vae_ctx["_INTERNAL_GROUNDING_MARKER_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if _INTERNAL_GROUNDING_MARKER_PATTERN.search(claim.text):
        claim_reasons.append(
            "Interne Grounding- oder Kontextfenster-Marker gehören nicht "
            "in eine wissenschaftliche Nutzerantwort."
        )


def _vae_rule_unsupported_quoted_segments(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7577-7612)."""
    if "_extract_grounding_example_segments" in _vae_ctx:
        _extract_grounding_example_segments = _vae_ctx["_extract_grounding_example_segments"]
    if "_quote_is_negative_lexical_rating_example" in _vae_ctx:
        _quote_is_negative_lexical_rating_example = _vae_ctx["_quote_is_negative_lexical_rating_example"]
    if "_quote_is_negative_temporal_field_example" in _vae_ctx:
        _quote_is_negative_temporal_field_example = _vae_ctx["_quote_is_negative_temporal_field_example"]
    if "_quote_is_user_scope_reference" in _vae_ctx:
        _quote_is_user_scope_reference = _vae_ctx["_quote_is_user_scope_reference"]
    if "_quoted_segment_is_supported" in _vae_ctx:
        _quoted_segment_is_supported = _vae_ctx["_quoted_segment_is_supported"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "question_text" in _vae_ctx:
        question_text = _vae_ctx["question_text"]
    if "quote_surface" in _vae_ctx:
        quote_surface = _vae_ctx["quote_surface"]
    if "quote_surfaces" in _vae_ctx:
        quote_surfaces = _vae_ctx["quote_surfaces"]
    if "quoted_segments" in _vae_ctx:
        quoted_segments = _vae_ctx["quoted_segments"]
    if "segment" in _vae_ctx:
        segment = _vae_ctx["segment"]
    if "unsupported_quoted_segments" in _vae_ctx:
        unsupported_quoted_segments = _vae_ctx["unsupported_quoted_segments"]
    quoted_segments = _extract_grounding_example_segments(claim.text)
    unsupported_quoted_segments = [
        segment
        for segment in quoted_segments
        if not any(
            _quoted_segment_is_supported(segment, quote_surface)
            for quote_surface in quote_surfaces
        )
        and not _quote_is_user_scope_reference(
            segment,
            claim.text,
            question_text,
        )
        and not _quote_is_negative_temporal_field_example(
            segment,
            claim.text,
            facts,
        )
        and not _quote_is_negative_lexical_rating_example(
            segment,
            claim.text,
            claim.claim_kind,
            facts,
        )
    ]
    if unsupported_quoted_segments:
        claim_reasons.append(
            "Zitat oder Beispiel ist nicht wortgetreu in den "
            "Grounding-Quotes sichtbar: "
            + ", ".join(
                repr(segment)
                for segment in unsupported_quoted_segments[:3]
            )
            + ". Als Paraphrase ohne Anführungszeichen formulieren oder "
            "wortgetreu aus einem referenzierten Fact übernehmen."
        )
    _vae_l = locals()
    for _vae_n in ("quote_surface", "quoted_segments", "segment", "unsupported_quoted_segments"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_claim_3(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7613-7630)."""
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "exact_local_observation" in _vae_ctx:
        exact_local_observation = _vae_ctx["exact_local_observation"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "has_substantive_fact" in _vae_ctx:
        has_substantive_fact = _vae_ctx["has_substantive_fact"]
    if (
        claim.claim_kind != "limitation"
        and any(fact.fact_kind == "limitation" for fact in facts)
    ):
        has_substantive_fact = any(
            fact.fact_kind
            not in {"limitation", "negative_result"}
            for fact in facts
        )
        exact_local_observation = bool(
            has_substantive_fact
            and _is_explicitly_bounded_claim(claim.text)
        )
        if (
            claim.assertion_level == "exact"
            and not exact_local_observation
        ):
            claim_reasons.append("Exakter Claim auf Basis einer Limitation.")
    _vae_l = locals()
    for _vae_n in ("exact_local_observation", "fact", "has_substantive_fact"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_claim_corpus_token_basis_is_visible(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7631-7643)."""
    if "_MISSING_CORPUS_TOKEN_PATTERN" in _vae_ctx:
        _MISSING_CORPUS_TOKEN_PATTERN = _vae_ctx["_MISSING_CORPUS_TOKEN_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_corpus_token_basis_is_visible" in _vae_ctx:
        claim_corpus_token_basis_is_visible = _vae_ctx["claim_corpus_token_basis_is_visible"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    grounded_limitation = (
        claim.claim_kind == "limitation"
        and any(fact.fact_kind == "limitation" for fact in facts)
    )
    if (
        claim.claim_kind == "limitation"
        and claim_corpus_token_basis_is_visible
        and _MISSING_CORPUS_TOKEN_PATTERN.search(claim.text)
    ):
        claim_reasons.append(
            "Der Claim bezeichnet die Tokenbezugsgröße als fehlend, obwohl "
            "ein Observed Fact corpus_tokens ausweist."
        )
    _vae_l = locals()
    for _vae_n in ("fact", "grounded_limitation"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_claim_total_hits_basis_is_visible(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7644-7652)."""
    if "_MISSING_TOTAL_HITS_PATTERN" in _vae_ctx:
        _MISSING_TOTAL_HITS_PATTERN = _vae_ctx["_MISSING_TOTAL_HITS_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "claim_total_hits_basis_is_visible" in _vae_ctx:
        claim_total_hits_basis_is_visible = _vae_ctx["claim_total_hits_basis_is_visible"]
    if (
        claim.claim_kind == "limitation"
        and claim_total_hits_basis_is_visible
        and _MISSING_TOTAL_HITS_PATTERN.search(claim.text)
    ):
        claim_reasons.append(
            "Der Claim bezeichnet die Gesamttrefferzahl als fehlend, "
            "obwohl ein Fact desselben Tool-Laufs total ausweist."
        )


def _vae_rule_has_positive_partition_purpose_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7653-7676)."""
    if "_has_positive_partition_purpose_claim" in _vae_ctx:
        _has_positive_partition_purpose_claim = _vae_ctx["_has_positive_partition_purpose_claim"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "deliverable_kind" in _vae_ctx:
        deliverable_kind = _vae_ctx["deliverable_kind"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "limitation" in _vae_ctx:
        limitation = _vae_ctx["limitation"]
    if "partition_labels_visible" in _vae_ctx:
        partition_labels_visible = _vae_ctx["partition_labels_visible"]
    if "partition_scope_limited" in _vae_ctx:
        partition_scope_limited = _vae_ctx["partition_scope_limited"]
    if "re" in _vae_ctx:
        re = _vae_ctx["re"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    partition_scope_limited = any(
        "technische Datenaufteilung" in fact.statement
        or any("technischen Partition" in limitation for limitation in fact.limitations)
        for fact in facts
    )
    partition_labels_visible = bool(
        re.search(
            r"(?:field=|values\[|value_count\[)split\b|"
            r"Metadatenfeld\s+['\"]?split\b",
            source_surface,
            re.IGNORECASE,
        )
    )
    if (
        (partition_scope_limited or partition_labels_visible)
        and _has_positive_partition_purpose_claim(claim.text)
        and not (
            deliverable_kind in {"followup_questions", "method_advice"}
            and claim.claim_kind in {"followup", "interpretation"}
        )
    ):
        claim_reasons.append(
            "Der Zweck der technischen Partition ist in der Evidenz nicht belegt."
        )
    _vae_l = locals()
    for _vae_n in ("fact", "limitation", "partition_labels_visible", "partition_scope_limited"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_fact(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7677-7688)."""
    if "_CATEGORY_PATTERN" in _vae_ctx:
        _CATEGORY_PATTERN = _vae_ctx["_CATEGORY_PATTERN"]
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "grounded_limitation" in _vae_ctx:
        grounded_limitation = _vae_ctx["grounded_limitation"]
    if any(fact.exactness == "derived" for fact in facts):
        if claim.assertion_level == "exact" and not grounded_limitation:
            claim_reasons.append("Exakter Claim auf Basis nur abgeleiteter Facts.")
        if (
            _CATEGORY_PATTERN.search(claim.text.lower())
            and not grounded_limitation
            and not (
                claim.assertion_level == "qualified"
                and _is_explicitly_bounded_claim(claim.text)
            )
        ):
            claim_reasons.append("Kategorisierende Aussage auf Basis nur abgeleiteter Facts.")
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unmeasured_magnitude(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7707-7722)."""
    if "_unmeasured_partial_magnitude_claims" in _vae_ctx:
        _unmeasured_partial_magnitude_claims = _vae_ctx["_unmeasured_partial_magnitude_claims"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "item" in _vae_ctx:
        item = _vae_ctx["item"]
    if "unmeasured_magnitude" in _vae_ctx:
        unmeasured_magnitude = _vae_ctx["unmeasured_magnitude"]
    unmeasured_magnitude = _unmeasured_partial_magnitude_claims(
        claim.text,
        facts,
    )
    if (
        claim.claim_kind in {"observation", "interpretation"}
        and unmeasured_magnitude
        and not _is_testable_hypothesis_claim(
            claim.text,
            claim_kind=claim.claim_kind,
            assertion_level=claim.assertion_level,
        )
    ):
        claim_reasons.append(
            "Partielle, gesampelte oder Top-N-Evidenz trägt keinen "
            "unoperationalisierten Intensitätsgrad: "
            + ", ".join(repr(item) for item in unmeasured_magnitude[:3])
            + ". Den sichtbaren Kontrast ohne Größenurteil beschreiben "
            "oder den Intensitätsgrad mit einer expliziten "
            "Vergleichsmetrik belegen."
        )
    _vae_l = locals()
    for _vae_n in ("item", "unmeasured_magnitude"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_item(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7723-7785)."""
    if "_CATEGORY_PATTERN" in _vae_ctx:
        _CATEGORY_PATTERN = _vae_ctx["_CATEGORY_PATTERN"]
    if "_CROSS_TOOL_CAUSAL_PATTERN" in _vae_ctx:
        _CROSS_TOOL_CAUSAL_PATTERN = _vae_ctx["_CROSS_TOOL_CAUSAL_PATTERN"]
    if "_EXPLICIT_CAUSAL_EVIDENCE_PATTERN" in _vae_ctx:
        _EXPLICIT_CAUSAL_EVIDENCE_PATTERN = _vae_ctx["_EXPLICIT_CAUSAL_EVIDENCE_PATTERN"]
    if "_NEGATIVE_METHOD_CONCLUSION_PATTERN" in _vae_ctx:
        _NEGATIVE_METHOD_CONCLUSION_PATTERN = _vae_ctx["_NEGATIVE_METHOD_CONCLUSION_PATTERN"]
    if "_has_positive_extra_clause" in _vae_ctx:
        _has_positive_extra_clause = _vae_ctx["_has_positive_extra_clause"]
    if "_has_unnegated_pattern" in _vae_ctx:
        _has_unnegated_pattern = _vae_ctx["_has_unnegated_pattern"]
    if "_is_explicitly_bounded_claim" in _vae_ctx:
        _is_explicitly_bounded_claim = _vae_ctx["_is_explicitly_bounded_claim"]
    if "_violates_forbidden_claim" in _vae_ctx:
        _violates_forbidden_claim = _vae_ctx["_violates_forbidden_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "cross_source_fact_mix" in _vae_ctx:
        cross_source_fact_mix = _vae_ctx["cross_source_fact_mix"]
    if "cross_tool_causal_claim" in _vae_ctx:
        cross_tool_causal_claim = _vae_ctx["cross_tool_causal_claim"]
    if "cross_tool_positive_extra_clause" in _vae_ctx:
        cross_tool_positive_extra_clause = _vae_ctx["cross_tool_positive_extra_clause"]
    if "cross_tool_scope_missing" in _vae_ctx:
        cross_tool_scope_missing = _vae_ctx["cross_tool_scope_missing"]
    if "exact_negative_method_conclusion" in _vae_ctx:
        exact_negative_method_conclusion = _vae_ctx["exact_negative_method_conclusion"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "forbidden_claims" in _vae_ctx:
        forbidden_claims = _vae_ctx["forbidden_claims"]
    if "fully_anchored" in _vae_ctx:
        fully_anchored = _vae_ctx["fully_anchored"]
    if "item" in _vae_ctx:
        item = _vae_ctx["item"]
    if "question_term" in _vae_ctx:
        question_term = _vae_ctx["question_term"]
    if "question_text" in _vae_ctx:
        question_text = _vae_ctx["question_text"]
    if "source_surface" in _vae_ctx:
        source_surface = _vae_ctx["source_surface"]
    claim_reasons.extend(
        _violates_forbidden_claim(
            claim.text,
            forbidden_claims,
            facts,
            claim_kind=claim.claim_kind,
            assertion_level=claim.assertion_level,
            scope_terms=[question_term] if question_term else [],
            question_text=question_text,
        )
    )
    if "unsupported cross-tool inference" in {item.lower() for item in forbidden_claims}:
        if (
            claim.claim_kind == "interpretation"
            and cross_source_fact_mix
        ):
            testable_hypothesis = _is_testable_hypothesis_claim(
                claim.text,
                claim_kind=claim.claim_kind,
                assertion_level=claim.assertion_level,
            )
            anchor_present = any(
                "interpretation_anchor" in fact.supports_claims
                for fact in facts
            )
            fully_anchored = all(
                "interpretation_anchor" in fact.supports_claims
                or fact.fact_kind == "limitation"
                or (
                    testable_hypothesis
                    and anchor_present
                    and fact.fact_kind == "count"
                    and fact.exactness == "exact"
                )
                for fact in facts
            )
            # A1, 2026-08-31: REICHWEITE statt Vokabel.
            #
            # Hier stand ``not _is_explicitly_bounded_claim(claim.text)``,
            # und damit entschied ueber jede werkzeugübergreifende Deutung
            # ein WORTSCHATZ (_BOUNDED_SCOPE_PATTERN), nicht die Evidenz.
            # Gemessen an vier Saetzen auf identischer Faktenlage:
            #
            #   "Im sichtbaren Ausschnitt liegt A ueber B."      besteht
            #   "A liegt ueber B, wie die untersuchten Daten
            #    zeigen."                                        besteht
            #   "A liegt IN DIESEM KORPUS deutlich ueber B."     FAELLT
            #   "A ist haeufiger als B."                         faellt
            #
            # Der dritte Fall ist der Defekt. "In diesem Korpus" ist die
            # natuerlichste und korrekteste Reichweitenangabe der
            # Korpuslinguistik ueberhaupt, sie stand nur nicht in der
            # Liste. Der zweite Fall ist das Gegenstueck: eine Floskel
            # genuegte, um eine unbegrenzte Behauptung durchzulassen.
            #
            # Hart bleibt jetzt, was UEBER die Daten hinausgreift, nicht
            # was eine Hoeflichkeitsformel vermissen laesst. Eine Deutung
            # ohne Reichweitenwort ist unvollstaendig, aber nicht falsch.
            # Fabrikation faengt sie ohnehin nicht: dafuer stehen die
            # Zahl- und Zitatbindungen, fully_anchored und
            # cross_tool_causal_claim, und die bleiben unveraendert.
            # Korpusweite Geltung darf behaupten, wessen Evidenz
            # korpusweit exakt ist. Ist auch nur ein Fakt ungenau oder
            # gekappt, ist "im Korpus" eine Hochrechnung aus einem
            # Ausschnitt und faellt.
            alle_fakten_exakt = bool(facts) and all(
                fact.exactness == "exact" for fact in facts
            )
            hochrechnung_aus_ausschnitt = (
                bool(_KORPUSWEITE_GELTUNG.search(claim.text))
                and not alle_fakten_exakt
            )
            cross_tool_scope_missing = (
                not testable_hypothesis
                and (
                    bool(_UEBERDEHNTE_REICHWEITE.search(claim.text))
                    or hochrechnung_aus_ausschnitt
                )
                and not _is_explicitly_bounded_claim(claim.text)
            )
            cross_tool_causal_claim = bool(
                _has_unnegated_pattern(
                    analytical_prose,
                    _CROSS_TOOL_CAUSAL_PATTERN,
                )
                and not _EXPLICIT_CAUSAL_EVIDENCE_PATTERN.search(
                    source_surface
                )
            )
            cross_tool_positive_extra_clause = (
                any(
                    fact.fact_kind == "negative_result"
                    for fact in facts
                )
                and (
                    _has_positive_extra_clause(claim.text)
                    or bool(_CATEGORY_PATTERN.search(claim.text))
                )
            )
            exact_negative_method_conclusion = (
                fully_anchored
                and all(fact.exactness == "exact" for fact in facts)
                and any(fact.fact_kind == "negative_result" for fact in facts)
                and _NEGATIVE_METHOD_CONCLUSION_PATTERN.search(
                    claim.text
                )
                and not cross_tool_causal_claim
                and not cross_tool_positive_extra_clause
            )
            if not exact_negative_method_conclusion and (
                not fully_anchored
                or cross_tool_scope_missing
                or cross_tool_causal_claim
                or cross_tool_positive_extra_clause
            ):
                claim_reasons.append(
                    "Cross-Tool-Interpretationen müssen vollständig geankert "
                    "und ausdrücklich auf die sichtbare Evidenz begrenzt sein."
                )
    _vae_l = locals()
    for _vae_n in ("cross_tool_causal_claim", "cross_tool_positive_extra_clause", "cross_tool_scope_missing", "exact_negative_method_conclusion", "fact", "fully_anchored", "item"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_stronger_than_exactness(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7786-7790)."""
    if "_stronger_than_exactness" in _vae_ctx:
        _stronger_than_exactness = _vae_ctx["_stronger_than_exactness"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "fact" in _vae_ctx:
        fact = _vae_ctx["fact"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if claim.assertion_level == "exact" and _stronger_than_exactness(
        claim.text,
        [fact.exactness for fact in facts],
    ):
        claim_reasons.append("Claim ist stärker als die Exactness der referenzierten Facts.")
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


# K3 Slice 3: declarative rows of this module (see claim_rules._table).
PATTERN_RULES = (
    _RULE_HASHTAG_LABEL,
    _RULE_PARTIAL_EXHAUSTIVE_CLAIMS,
    _RULE_ARTIFACT_CLASSIFICATIONS,
    _RULE_TEXT_PRODUCTION_INFERENCES,
    _RULE_DISTRIBUTION_CLAIMS,
    _RULE_SCOPE_DESIGN_COMPLETENESS,
    _RULE_SCOPE_DESIGN_REPRESENTATIVENESS,
    _RULE_RAW_POS_INFERENCE,
    _RULE_POS_INVENTORY_PROVENANCE,
    _RULE_ABSOLUTE_ASSOCIATION_MAGNITUDE,
    _RULE_REGISTER_THEME_INFERENCE,
    _RULE_GRAMMATICAL_PROFILE_INFERENCE,
)
