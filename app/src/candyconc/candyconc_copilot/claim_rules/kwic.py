"""KWIC-context claim rules: window, category, prevalence, participant and source-role predicates with their regex vocabulary.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import Dict, List, Sequence

from ..grounding_schemas import (
    ObservedFact,
    _compact_text,
    _dedupe_ordered_strs,
)
from ._shared import (
    _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN,
    _NUMBER_WORD_TOKEN_SOURCE,
    _TENTATIVE_THEME_PATTERN,
    _is_explicitly_bounded_claim,
    _is_negative_or_unknown_limitation,
    _joined_surface_text,
    _normalise_quote_for_match,
    _number_word_value,
    _prose_outside_examples,
)


_NO_NEGATION_CLAIM_PATTERN = re.compile(
    r"\b(?:enthält|enthaelt|hat|weist\s+auf|zeigt)\b"
    r"[^.!?\n]{0,60}\b(?:keine|keinen|kein)\s+"
    r"(?:weitere\s+)?(?:negation|verneinung|umkehrung)\b|"
    r"\b(?:ohne|frei\s+von)\s+(?:weitere[rn]?\s+)?"
    r"(?:negation|verneinung)\b|\bnicht\s+negiert\b",
    re.IGNORECASE,
)
_NEGATION_TOKEN_PATTERN = re.compile(
    r"\b(?:nicht|nichts|nie|niemals|kein(?:e|en|er|es)?|"
    r"weder|ohne|kaum)\b",
    re.IGNORECASE,
)
_CATEGORICAL_ATTACHMENT_PATTERN = re.compile(
    r"\b(?:bezieht\s+sich(?:\s+syntaktisch\w*)?\s+auf|modifizier\w*|qualifizier\w*|"
    r"lokalisier\w*|fungier\w*|dient\b|bezugsrahmen|"
    r"syntaktisch\w*\s+(?:bezug|anbindung|kopf)|"
    r"functions?\s+as|situat\w*|specif\w*\s+where)\b|"
    r"\bals\b[^.!?\n]{0,80}\b(?:zusatz|angabe|lokalisierung|"
    r"präpositional\w*|praepositional\w*)\b[^.!?\n]{0,50}"
    r"\b(?:verstehen|lesen|deuten)\w*\b|"
    r"\b(?:locative\s+modifier|geographical\s+prepositional\s+phrase)\b|"
    r"\b(?:geograph\w*|räumlich\w*|raeumlich\w*|territorial\w*)\b"
    r"[^.!?\n]{0,60}\b(?:reichweite|geltungsbereich|bezug|rahmen)\b"
    r"[^.!?\n]{0,80}\b(?:markier|bestimm|lokalisier|verort)\w*\b|"
    r"\b(?:subjekt|objekt|prädikativ|praedikativ|attribut|"
    r"präpositionalobjekt|praepositionalobjekt|subject|object|"
    r"predicative|attribute)\b|"
    r"\b(?:ort|setting|zuständigkeit|zustaendigkeit)\b"
    r"[^.!?\n]{0,100}\b(?:stattfindet|angibt|markiert)\w*\b|"
    r"\b(?:takes?\s+place|happens?|exists?)\b[^.!?\n]{0,80}"
    r"\b(?:within|inside|in)\b",
    re.IGNORECASE,
)
_ATTACHMENT_QUALIFIER_PATTERN = re.compile(
    r"\b(?:kann|könnte|koennte|möglich\w*|moeglich\w*|"
    r"plausib\w*|vermutlich\w*|wahrscheinlich\w*|"
    r"eine\s+(?:mögliche|moegliche)\s+lesart|mehrdeutig\w*|"
    r"(?:lässt|laesst)\s+sich\b[^.!?\n]{0,100}"
    r"\b(?:verstehen|lesen|deuten|interpretieren)\w*|"
    r"(?:deutet|weist)\b[^.!?\n]{0,80}\bdarauf\s+hin\b|"
    r"legt\s+nahe|can|could|possible\w*|plausible\w*|likely\w*|"
    r"ambiguous\w*|possible\s+reading)\b",
    re.IGNORECASE,
)
_KWIC_SEMANTIC_DIVERSITY_PATTERN = re.compile(
    r"\b(?:vielfält\w*|vielfaelt\w*|unterschiedlich\w*|verschieden\w*)\b"
    r"[^.!?\n]{0,120}\b(?:kontext\w*|rahmen\w*|gebrauch\w*|verwendung\w*|"
    r"semant\w*)\b|"
    r"\b(?:neutral\w*|sachlich\w*)\b[^.!?\n]{0,140}"
    r"\b(?:kritisch\w*|wertend\w*|negativ\w*)\b|"
    r"\b(?:kritisch\w*|wertend\w*|negativ\w*)\b[^.!?\n]{0,140}"
    r"\b(?:neutral\w*|sachlich\w*)\b",
    re.IGNORECASE,
)
_PARTIAL_KWIC_PREVALENCE_PATTERN = re.compile(
    r"(?:"
    r"\b(?:häufig\w*|haeufig\w*|meist\w*|überwiegend\w*|"
    r"ueberwiegend\w*|mehrheitlich\w*|dominier\w*|vorherrsch\w*|"
    r"typisch\w*|tendenz\w*|häufung\w*|haeufung\w*)\b"
    r"[^.!?\n]{0,140}\b(?:kontext\w*|vorkomm\w*|verwend\w*|"
    r"gebrauch\w*|diskurs\w*|rahm\w*|bewertung\w*|verbind\w*|"
    r"zusammenhang\w*|umfeld\w*|nähe\w*|naehe\w*|wörter\w*|"
    r"woerter\w*|begriff\w*|lexem\w*|kollokat\w*)\b"
    r"|"
    r"\b(?:kontext\w*|vorkomm\w*|verwend\w*|gebrauch\w*|"
    r"diskurs\w*|rahm\w*|bewertung\w*|verbind\w*|"
    r"zusammenhang\w*|umfeld\w*|nähe\w*|naehe\w*|wörter\w*|"
    r"woerter\w*|begriff\w*|lexem\w*|kollokat\w*)\b"
    r"[^.!?\n]{0,140}"
    r"\b(?:häufig\w*|haeufig\w*|meist\w*|überwiegend\w*|"
    r"ueberwiegend\w*|mehrheitlich\w*|dominier\w*|vorherrsch\w*|"
    r"typisch\w*|tendenz\w*|häufung\w*|haeufung\w*)\b"
    r")",
    re.IGNORECASE,
)
_PARTIAL_KWIC_DISCOURSE_SYSTEM_PATTERN = re.compile(
    r"\b(?:diskurs(?:feld|muster|formation)?|deutungsmuster|"
    r"kontextmuster|rahmung)\w*\b[^.!?\n]{0,100}"
    r"\b(?:etablier\w*|besteh\w*|vorhanden\w*|präsent\w*|"
    r"praesent\w*|ausgeprägt\w*|ausgepraegt\w*)\b|"
    r"\b(?:etablier\w*|besteh\w*|vorhanden\w*|präsent\w*|"
    r"praesent\w*|ausgeprägt\w*|ausgepraegt\w*)\b"
    r"[^.!?\n]{0,100}\b(?:diskurs(?:feld|muster|formation)?|"
    r"deutungsmuster|kontextmuster|rahmung)\w*\b",
    re.IGNORECASE,
)


_VISIBLE_KWIC_SUBSET_COUNT_PATTERN = re.compile(
    rf"\b(?:(?:in|unter|bei|among|within)\s+)?"
    r"(?:(?P<qualifier>mindestens|zumindest|genau|exakt|nur|at\s+least|"
    r"exactly|only)\s+)?"
    rf"(?P<count>\d+|{_NUMBER_WORD_TOKEN_SOURCE})\s+"
    r"(?:(?:der|von\s+den|of\s+the)\s+"
    rf"(?P<visible_total>\d+|{_NUMBER_WORD_TOKEN_SOURCE})\s+)?"
    r"(?:hier\s+)?(?:sichtbar|gezeigt|zurückgegeben|zurueckgegeben|"
    r"visible|shown|returned)\w*\s+"
    r"(?:treffer(?:n)?|trefferkontexte?|kwic[- ]?(?:zeilen?|belege?)|"
    r"konkordanzzeilen?|hits?|matches|kwic\s+lines?)\b",
    re.IGNORECASE,
)
_KWIC_EVALUATIVE_CATEGORY_PATTERN = re.compile(
    r"\b(?:neutral|sachlich|positiv|negativ|kritisch|wertend|"
    r"zustimmend|ablehnend|feindlich|wohlwollend|affirmativ|"
    r"delegitimierend|stigmatisierend|neutral|factual|positive|"
    r"negative|critical|approving|hostile|supportive)\w*\b",
    re.IGNORECASE,
)
_VISIBLE_EPISTEMIC_QUALIFIER_PATTERN = re.compile(
    r"\b(?:könnt\w*|koennt\w*|möglicherweise|moeglicherweise|"
    r"denkbar\w*|plausib\w*|vorläufig\w*|vorlaeufig\w*|"
    r"hypothese\w*)\b|"
    r"\b(?:legt|legen|deutet|deuten|weist|weisen)\b"
    r"[^.!?\n]{0,100}\b(?:nahe|darauf\s+hin)\b|"
    r"\b(?:lässt|laesst|lassen)\b[^.!?\n]{0,100}"
    r"\b(?:vermuten|annehmen|lesen|deuten|interpretieren)\w*\b|"
    r"\b(?:could|might|may|possibly|plausibly|suggests?)\b",
    re.IGNORECASE,
)
_KWIC_AGGREGATE_CATEGORY_SCOPE_PATTERN = re.compile(
    r"\b(?:beide|alle|sämtlich\w*|saemtlich\w*|mehrere|jeweils|"
    r"both|all|several)\b[^.!?\n]{0,80}"
    r"\b(?:sichtbar\w*\s+)?(?:treffer\w*|kontext\w*|kwic[- ]?zeilen?\w*|"
    r"belege?\w*|passagen?\w*|hits?|matches|contexts?|passages?)\b|"
    r"\b(?:die|diese|den|unter\s+den|the|these)\s+sichtbar\w*\s+"
    r"(?:treffer\w*|kontext\w*|kwic[- ]?zeilen?\w*|belege?\w*|"
    r"passagen?\w*|hits?|matches|contexts?|passages?)\b|"
    r"\b(?:treffer|kontexte|kwic[- ]?zeilen|belege|passagen|hits|matches|"
    r"contexts|passages)\b[^.!?\n]{0,80}"
    r"\b(?:beide|alle|sämtlich\w*|saemtlich\w*|jeweils|both|all)\b",
    re.IGNORECASE,
)
_CONTEXT_CODING_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:context_label|coding_label|category_label|kontext_label)\s*="
    r"\s*[\"']?(?P<label>[A-Za-zÄÖÜäöüß_-]+)",
    re.IGNORECASE,
)
_KWIC_POSITION_ANCHOR_PATTERN = re.compile(
    r"\b(?:token[_ -]?position|position|pos)\s*(?:=|:)\s*(?P<pos>\d+)\b|"
    r"\btoken[- ]?position\s+(?P<natural_pos>\d+)\b",
    re.IGNORECASE,
)
_KWIC_DOCUMENT_ANCHOR_PATTERN = re.compile(
    r"\b(?:doc(?:ument)?_?id|file)\s*(?:=|:)\s*[\"']?"
    r"(?P<doc>[^\"'\s,;}]+)",
    re.IGNORECASE,
)
_KWIC_ROW_ANCHOR_PATTERN = re.compile(r"\b(?:row|kwic|hit)\[(?P<row>\d+)\]", re.IGNORECASE)
_KWIC_LITERAL_MEMBERSHIP_PATTERN = re.compile(
    r"\b(?:enthält|enthaelt|zeigen?|weist|weisen)\b[^.!?\n]{0,28}?"
    r"(?:das\s+)?(?:token|wort|lemma|muster|ausdruck)?\s*"
    r"[\"'„“‚‘]?(?P<after>[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]{2,})|"
    r"\b(?:tritt|kommt|erscheint|steht)\s+"
    r"[\"'„“‚‘]?(?P<middle>[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]{2,})"
    r"[\"'„“‚‘]?\s+(?:auf|vor|darin|therein)\b|"
    r"\b(?P<english>[A-Za-z][\w-]{2,})\s+(?:occurs?|appears?)\b",
    re.IGNORECASE,
)
_KWIC_METALINGUISTIC_CATEGORY_PATTERN = re.compile(
    r"\b(?:token|wortform|lemma|zeichenfolge|ausdruck)\b\s*"
    r"[\"'„“‚‘]?(?P<label>neutral\w*|sachlich\w*|positiv\w*|"
    r"negativ\w*|kritisch\w*|wertend\w*|positive\w*|negative\w*|"
    r"critical\w*)[\"'„“‚‘]?",
    re.IGNORECASE,
)
_KWIC_REFERENCE_RESOLUTION_PATTERN = re.compile(
    r"\bmit\s+[\"'„“‚‘]?(?:mir|dir|ihm|ihr|uns|euch|ihnen|mich|dich|"
    r"ihn|sie)[\"'„“‚‘]?\s+(?:ist|sind|sei|seien)\b"
    r"[^.!?\n]{0,100}\b(?:gemeint|bezeichnet|identifiziert)\w*\b|"
    r"\b[\"'„“‚‘]?(?:mir|dir|ihm|ihr|uns|euch|ihnen|mich|dich|ihn|sie)"
    r"[\"'„“‚‘]?\s+(?:bezieht\s+sich\s+auf|steht\s+für|steht\s+fuer|"
    r"meint|referenziert)\b|"
    r"\b[\"']?(?:you|they|them|he|him|she|her|we|us|it)[\"']?\s+"
    r"(?:refers?\s+to|means|identifies)\b",
    re.IGNORECASE,
)
_EXPLICIT_REFERENCE_EVIDENCE_PATTERN = re.compile(
    r"\b(?:coref(?:erence)?|referent|addressee|adressat|speaker|"
    r"participant_type|addressee_type|speaker_type|entity_type)\s*=",
    re.IGNORECASE,
)
_KWIC_PARTICIPANT_TYPING_PATTERN = re.compile(
    r"\b(?:adressat\w*|angesprochene\w*|sprecher\w*|verfasser\w*|"
    r"autor\w*|akteur\w*|addressee\w*|speaker\w*|author\w*|"
    r"participant\w*)\b[^.!?\n]{0,28}"
    r"(?:\bhier\b|\balso\b|\bnämlich\b|\bnaemlich\b|\bhere\b)\s+"
    r"(?:als\s+)?(?:ein(?:e|en|em|er|es)?|der|die|das|a|an|the)\s+"
    r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]{2,}",
    re.IGNORECASE,
)
_KWIC_PRONOUN_ROLE_FRAME_PATTERN = re.compile(
    r"\b(?:mich|dich|euch|uns|ihn|sie|ihnen|mir|dir|ihm|ihr|"
    r"me|you|him|her|them|us)\s+"
    r"(?:zum|zur|zu\s+einem|zu\s+einer|als|into\s+(?:a|an)|as\s+(?:a|an))\s+"
    r"(?P<role>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]{2,})",
    re.IGNORECASE,
)
_KWIC_NAMED_ROLE_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:der|die|das|den|dem|a|an|the)\s+"
    r"(?P<entity>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]{2,})\b"
    r"[^.!?\n]{0,90}\b(?:als|mit\s+(?:der\s+)?bezeichnung|as)\s+"
    r"[\"'„“‚‘]?(?P<role>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß-]{2,})",
    re.IGNORECASE,
)
_KWIC_CONTENT_PARAPHRASE_PATTERN = re.compile(
    r"\b(?:behaupt\w*|aussage\w*|vorwurf\w*|darstell\w*|beton\w*|"
    r"interpret\w*|deut\w*|claims?|statements?|accus\w*|"
    r"readings?|shows?|suggests?)\b[^.!?\n]{0,100}\b(?:dass|that)\b"
    r"(?P<clause>[^.!?\n]{1,240})",
    re.IGNORECASE,
)
_KWIC_NEW_PARTICIPANT_TYPE_PATTERN = re.compile(
    r"\b(?:person(?:en)?gruppe|person|individual|"
    r"sprecher(?:s|in|innen)?|speaker(?:s)?|author(?:s)?|"
    r"autor(?:s|en|in|innen)?|verfasser(?:s|in|innen)?|writer(?:s)?|"
    r"medienorganisation|medienunternehmen|organisation|unternehmen|"
    r"nachrichtensendung|sender(?:in|innen|gruppe|gruppen|s)?|"
    r"sendung|nutzer(?:in|innen)?|"
    r"media\s+outlet|media\s+organisation|media\s+organization|"
    r"news\s+organisation|news\s+organization|broadcaster|company)\b",
    re.IGNORECASE,
)
_KWIC_SOURCE_ROLE_ATTRIBUTION_PATTERN = re.compile(
    r"\b(?:nach\s+(?:ansicht|auffassung|meinung)\s+(?:des|der)|"
    r"laut\s+(?:dem|der)|according\s+to\s+the)\s+"
    r"(?:autor(?:s|en|in|innen)?|verfasser(?:s|in|innen)?|"
    r"sprecher(?:s|in|innen)?|author(?:s)?|writer(?:s)?|speaker(?:s)?)\b|"
    r"\b(?:der|die|the)\s+"
    r"(?:autor(?:in)?|verfasser(?:in)?|sprecher(?:in)?|author|writer|speaker)\s+"
    r"(?:behauptet|meint|sagt|vertritt|claims?|says?|argues?)\b",
    re.IGNORECASE,
)
_KWIC_ANONYMIZATION_PATTERN = re.compile(
    r"(?:\b(?:anonymisier|pseudonymisier|maskier|redact)\w*\b"
    r"[^.!?\n]{0,100}@[A-Za-z0-9_]{2,64}|"
    r"@[A-Za-z0-9_]{2,64}[^.!?\n]{0,100}"
    r"\b(?:anonymisier|pseudonymisier|maskier|redact)\w*\b)",
    re.IGNORECASE,
)
_KWIC_ANONYMIZATION_EVIDENCE_PATTERN = re.compile(
    r"\b(?:anonymized|anonymised|anonymisiert|pseudonymisiert|redacted|"
    r"masked)\s*(?:=|:)\s*(?:true|yes|ja|1)\b|"
    r"<(?:anon|anonymized|redacted)>",
    re.IGNORECASE,
)
_KWIC_CATEGORICAL_PURPOSE_PATTERN = re.compile(
    r"\b(?:das\s+)?(?:ziel|zweck|absicht)\s+(?:des\s+)?(?:text(?:es)?|"
    r"kommentars?|belegs?|äußerung|aeusserung)\s+(?:ist|besteht\s+darin)|"
    r"\b(?:the\s+)?(?:purpose|intent|goal)\s+of\s+(?:the\s+)?"
    r"(?:text|comment|excerpt|utterance)\s+is\b",
    re.IGNORECASE,
)
_KWIC_PURPOSE_EVIDENCE_PATTERN = re.compile(
    r"\b(?:purpose|intent|goal|ziel|zweck|absicht)\s*(?:=|:)",
    re.IGNORECASE,
)
_KWIC_REPETITION_PATTERN = re.compile(
    r"\b(?:wiederhol|repeat)\w*\b",
    re.IGNORECASE,
)
_QUOTED_CONTENT_PATTERN = re.compile(
    r"[\"'„“‚‘](?P<content>[^\"'„“‚‘\n]{2,160})[\"'„“‚‘]"
)
_KWIC_SAFE_META_PREDICATES = {
    "ausser",
    "behaupt",
    "bedeut",
    "beschreib",
    "bezeichn",
    "bewert",
    "darstell",
    "deut",
    "formulier",
    "interpretier",
    "kritisier",
    "les",
    "markier",
    "naheleg",
    "rahm",
    "signalisier",
    "verort",
    "vorwerf",
    "wert",
    "accus",
    "claim",
    "criticise",
    "describ",
    "depict",
    "evaluat",
    "frame",
    "indicat",
    "interpret",
    "mark",
    "mean",
    "occur",
    "read",
    "show",
    "state",
    "suggest",
}
_KWIC_AUXILIARY_PREDICATES = {
    "bleib",
    "durf",
    "hab",
    "ist",
    "kann",
    "kon",
    "muss",
    "schein",
    "hat",
    "sein",
    "soll",
    "werd",
    "wird",
    "are",
    "be",
    "can",
    "could",
    "has",
    "have",
    "is",
    "may",
    "might",
    "should",
    "would",
}


_KWIC_AS_COLLOCATION_METHOD_PATTERN = re.compile(
    r"\b(?:kollokation\w*|kollokat\w*)\b[^?\n]{0,180}"
    r"\b(?:durch|mittels|per|mit(?:hilfe)?\s+von)\s+(?:eine[rs]?\s+)?"
    r"(?:gezielte[rs]?\s+)?(?:keyword[- ]in[- ]context|kwic)\b|"
    r"\b(?:keyword[- ]in[- ]context|kwic)\b[^?\n]{0,180}"
    r"\b(?:identifizier\w*|ermittel\w*|berechn\w*)\b[^?\n]{0,100}"
    r"\b(?:kollokation\w*|kollokat\w*)\b",
    re.IGNORECASE,
)
_EXPLICIT_COLLOCATION_METHOD_PATTERN = re.compile(
    r"\b(?:collocate_stats|kollokationsstatistik|assoziationsmaß|"
    r"assoziationsmass|fensterbreite|logdice|log\s*likelihood|"
    r"mutual\s+information|mi3?|t[- ]?score)\b",
    re.IGNORECASE,
)


def _kwic_predicate_stem(token: str) -> str:
    value = str(token or "").casefold().translate(
        str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})
    )
    if value.startswith("ge") and len(value) >= 7:
        value = value[2:]
    for suffix in (
        "ungen",
        "ing",
        "ern",
        "eln",
        "est",
        "eten",
        "ten",
        "end",
        "ed",
        "en",
        "et",
        "te",
        "st",
        "t",
        "e",
        "s",
    ):
        if value.endswith(suffix) and len(value) - len(suffix) >= 4:
            value = value[: -len(suffix)]
            break
    return value


def _unsupported_kwic_event_paraphrases(
    claim_text: str,
    expanded_context: str,
) -> List[str]:
    """Reject a newly supplied event verb inside reported source content."""

    source_stems = {
        _kwic_predicate_stem(token)
        for token in re.findall(
            r"[A-Za-zÄÖÜäöüß]+",
            expanded_context or "",
        )
    }
    unsupported: List[str] = []
    prepared_claim = re.sub(
        r"\b(?:bzw|z\.\s*b|d\.\s*h|u\.\s*a)\.",
        " ",
        claim_text or "",
        flags=re.IGNORECASE,
    )
    for match in _KWIC_CONTENT_PARAPHRASE_PATTERN.finditer(prepared_claim):
        tokens = re.findall(
            r"[A-Za-zÄÖÜäöüß]+",
            match.group("clause") or "",
        )
        for token in reversed(tokens):
            if token[:1].isupper():
                continue
            stem = _kwic_predicate_stem(token)
            normalised_token = str(token or "").casefold().translate(
                str.maketrans(
                    {"ä": "a", "ö": "o", "ü": "u", "ß": "ss"}
                )
            )
            if stem in _KWIC_AUXILIARY_PREDICATES:
                continue
            if not re.search(
                r"(?:en|ern|eln|ieren|iert|end|est|et|te|st|t|ing|ed|s)$",
                token,
                re.IGNORECASE,
            ):
                continue
            # Short German function words frequently end in ``-t``/``-s``;
            # treating them as predicates would turn the guard into noise.
            if stem == normalised_token or len(normalised_token) < 6:
                continue
            if stem not in source_stems and stem not in _KWIC_SAFE_META_PREDICATES:
                unsupported.append(
                    "neues Ereignisprädikat in einer Inhaltsparaphrase: "
                    + token
                )
    return list(dict.fromkeys(unsupported))


_OPEN_KWIC_RIGHT_EDGE_PATTERN = re.compile(
    r"\b(?:bevor|weil|wenn|falls|obwohl|während|waehrend|nachdem|"
    r"seitdem|indem|damit|dass|ob|before|because|if|although|while|"
    r"after|since|whether|that)"
    r"(?:\s+(?:es|er|sie|wir|ihr|man|der|die|das|ein(?:e|en|em|er|es)?|"
    r"it|he|she|they|we|you|the|a|an))?\s*$",
    re.IGNORECASE,
)
_KWIC_WINDOW_QUOTE_PATTERN = re.compile(
    r'^kwic\[\d+\]\s+"(?P<text>.*)"\s*$',
    re.DOTALL,
)


def _unsupported_open_kwic_window_interpretations(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Do not let a model complete a syntactically open KWIC window."""

    open_fragments: List[str] = []
    for fact in facts:
        if fact.fact_kind != "kwic_example":
            continue
        for raw_quote in fact.grounding_quotes:
            match = _KWIC_WINDOW_QUOTE_PATTERN.fullmatch(
                " ".join(str(raw_quote or "").split())
            )
            if match is None:
                continue
            fragment = match.group("text").rstrip(
                " \t\r\n.,;:!?…'\"”’)]}"
            )
            if _OPEN_KWIC_RIGHT_EDGE_PATTERN.search(fragment):
                open_fragments.append(fragment)
    if not open_fragments:
        return []
    return _unsupported_kwic_event_paraphrases(
        claim_text,
        " ".join(open_fragments),
    )


def _unsupported_kwic_repetition_claims(
    claim_text: str,
    expanded_context: str,
) -> List[str]:
    unsupported: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", claim_text or ""):
        if _KWIC_REPETITION_PATTERN.search(sentence) is None:
            continue
        for match in _QUOTED_CONTENT_PATTERN.finditer(sentence):
            quoted = " ".join(match.group("content").casefold().split())
            source = " ".join((expanded_context or "").casefold().split())
            if quoted and source.count(quoted) < 2:
                unsupported.append(
                    "behauptete Wiederholung eines nur einmal sichtbaren "
                    f"Ausdrucks: {match.group('content')}"
                )
    return list(dict.fromkeys(unsupported))


def _unsupported_kwic_categorical_purpose(
    claim_text: str,
    expanded_context: str,
) -> bool:
    match = _KWIC_CATEGORICAL_PURPOSE_PATTERN.search(claim_text or "")
    if match is None or _KWIC_PURPOSE_EVIDENCE_PATTERN.search(
        expanded_context or ""
    ):
        return False
    prefix = str(claim_text or "")[max(0, match.start() - 90) : match.start()]
    return _ATTACHMENT_QUALIFIER_PATTERN.search(prefix) is None


def _kwic_participant_type_is_literal(
    participant_type: str,
    expanded_context: str,
) -> bool:
    label = " ".join(str(participant_type or "").casefold().split())
    source = " ".join(str(expanded_context or "").casefold().split())
    if not label:
        return True
    if label in source:
        return True
    if " " in label:
        return False
    inflection = re.compile(
        r"(?:innen|gruppen|gruppe|in|en|n|s)$",
        re.IGNORECASE,
    )
    label_base = inflection.sub("", label)
    if len(label_base) < 5:
        return False
    return any(
        inflection.sub("", token) == label_base
        for token in re.findall(
            r"[A-Za-zÄÖÜäöüß]+",
            source,
        )
    )


def _unsupported_kwic_source_role_attribution(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    """Require literal or metadata evidence before assigning source voice."""

    match = _KWIC_SOURCE_ROLE_ATTRIBUTION_PATTERN.search(claim_text or "")
    if match is None:
        return False
    context = " ".join(
        part
        for fact in facts
        if fact.fact_kind == "kwic_example"
        for part in [fact.statement, *fact.grounding_quotes]
        if str(part or "").strip()
    )
    if not context or _EXPLICIT_REFERENCE_EVIDENCE_PATTERN.search(context):
        return not context
    participant = _KWIC_NEW_PARTICIPANT_TYPE_PATTERN.search(match.group(0))
    return bool(
        participant is not None
        and not _kwic_participant_type_is_literal(
            participant.group(0),
            context,
        )
    )


def _unsupported_expanded_context_interpretations(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    raw_claim_text: str = "",
) -> List[str]:
    expanded_context = " ".join(
        part
        for fact in facts
        if fact.fact_kind == "kwic_example"
        and "erweiterte" in fact.statement.casefold()
        and "kontext" in fact.statement.casefold()
        for part in [fact.statement, *fact.grounding_quotes]
    )
    if not expanded_context:
        return []
    literal_context_parts = []
    for fact in facts:
        if (
            fact.fact_kind != "kwic_example"
            or "erweiterte" not in fact.statement.casefold()
            or "kontext" not in fact.statement.casefold()
        ):
            continue
        candidates = list(fact.grounding_quotes) or [fact.statement]
        for candidate in candidates:
            compact = " ".join(str(candidate or "").split())
            if compact and compact not in literal_context_parts:
                literal_context_parts.append(compact)
    literal_context = " ".join(literal_context_parts) or expanded_context

    unsupported: List[str] = []
    if (
        _NO_NEGATION_CLAIM_PATTERN.search(claim_text or "")
        and _NEGATION_TOKEN_PATTERN.search(expanded_context)
    ):
        unsupported.append(
            "behauptete Negationsfreiheit trotz sichtbarem Negationsmarker"
        )

    reference_evidence = bool(
        _EXPLICIT_REFERENCE_EVIDENCE_PATTERN.search(expanded_context)
        or _KWIC_REFERENCE_RESOLUTION_PATTERN.search(expanded_context)
    )
    visible_claim_text = raw_claim_text or claim_text or ""
    unsupported.extend(
        _unsupported_kwic_event_paraphrases(
            visible_claim_text,
            expanded_context,
        )
    )
    unsupported.extend(
        _unsupported_kwic_repetition_claims(
            visible_claim_text,
            literal_context,
        )
    )
    if (
        _KWIC_ANONYMIZATION_PATTERN.search(visible_claim_text)
        and _KWIC_ANONYMIZATION_EVIDENCE_PATTERN.search(
            expanded_context
        )
        is None
    ):
        unsupported.append(
            "Anonymisierung oder Maskierung eines Handles ohne "
            "entsprechende Evidenz"
        )
    if _unsupported_kwic_categorical_purpose(
        visible_claim_text,
        expanded_context,
    ):
        unsupported.append(
            "kategorial zugeschriebenes Textziel ohne Zweck- oder "
            "Intentionsmetadaten"
        )
    if (
        _KWIC_REFERENCE_RESOLUTION_PATTERN.search(
            visible_claim_text
        )
        and not reference_evidence
    ):
        unsupported.append(
            "kategoriale Pronomen- oder Adressatenauflösung ohne explizite "
            "Referenzrelation"
        )
    if (
        _KWIC_PARTICIPANT_TYPING_PATTERN.search(visible_claim_text)
        and not reference_evidence
    ):
        unsupported.append(
            "kategoriale Teilnehmeridentität oder Entitätstype ohne explizite "
            "Sprecher-, Adressaten- oder Referenzrelation"
        )
    participant_type = _KWIC_NEW_PARTICIPANT_TYPE_PATTERN.search(
        visible_claim_text
    )
    if (
        participant_type is not None
        and not _kwic_participant_type_is_literal(
            participant_type.group(0),
            expanded_context,
        )
        and not reference_evidence
    ):
        unsupported.append(
            "neue Teilnehmer- oder Entitätstype ohne explizite "
            "Referenzevidenz"
        )
    source_pronoun_roles = {
        match.group("role").casefold()
        for match in _KWIC_PRONOUN_ROLE_FRAME_PATTERN.finditer(
            expanded_context
        )
    }
    for assignment in _KWIC_NAMED_ROLE_ASSIGNMENT_PATTERN.finditer(
        visible_claim_text
    ):
        role = assignment.group("role").casefold()
        entity = assignment.group("entity")
        same_role_is_pronominal = any(
            role == source_role
            or (
                len(role) >= 5
                and len(source_role) >= 5
                and role[:5] == source_role[:5]
            )
            for source_role in source_pronoun_roles
        )
        literal_named_assignment = re.search(
            rf"\b{re.escape(entity)}\b[^.!?\n]{{0,90}}"
            rf"\b(?:zum|zur|als|as)\s+[\"'„“‚‘]?{re.escape(role)}\b",
            expanded_context,
            re.IGNORECASE,
        )
        if (
            same_role_is_pronominal
            and literal_named_assignment is None
            and not reference_evidence
        ):
            unsupported.append(
                "Teilnehmerrolle vom sichtbaren Pronomen auf eine benachbarte "
                "Entität verschoben"
            )
            break

    has_explicit_syntax = re.search(
        r"\b(?:dependency|dep|head|syntactic_function|relation)\s*=",
        expanded_context,
        re.IGNORECASE,
    ) is not None
    if not has_explicit_syntax:
        claim_has_qualifier = _ATTACHMENT_QUALIFIER_PATTERN.search(
            claim_text or ""
        ) is not None
        claim_keeps_attachment_open = _KWIC_AMBIGUITY_PATTERN.search(
            claim_text or ""
        ) is not None
        for sentence in re.split(r"(?<=[.!?])\s+", claim_text or ""):
            if (
                _CATEGORICAL_ATTACHMENT_PATTERN.search(sentence)
                and (
                    not claim_has_qualifier
                    or not claim_keeps_attachment_open
                )
            ):
                unsupported.append(
                    "kategoriale syntaktische Anbindung ohne Parse-Evidenz "
                    "oder Unsicherheitsmarkierung"
                )
                break
    return unsupported


def _unsupported_kwic_semantic_diversity_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    assertion_level: str = "",
) -> List[str]:
    """Require real context evidence before classifying KWIC usage diversity."""

    match = _KWIC_SEMANTIC_DIVERSITY_PATTERN.search(claim_text or "")
    if match is None:
        return []
    if (
        assertion_level == "tentative"
        and _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(claim_text or "")
    ):
        return []
    expanded_contexts = {
        fact.id
        for fact in facts
        if fact.fact_kind == "kwic_example"
        and "erweiter" in fact.statement.casefold()
        and "kontext" in fact.statement.casefold()
    }
    semantic_passages = {
        fact.id
        for fact in facts
        if fact.fact_kind == "kwic_example"
        and any(
            "semantic_search" in str(source_id or "").casefold()
            for source_id in list(fact.source_evidence_ids or [])
        )
        and any(
            str(quote or "").casefold().startswith("hit=")
            for quote in list(fact.grounding_quotes or [])
        )
    }
    contextualised_passages = expanded_contexts | semantic_passages
    return [] if len(contextualised_passages) >= 2 else [match.group(0)]


def _unsupported_partial_kwic_prevalence_claims(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    claim_kind: str = "",
) -> List[str]:
    """Keep visible KWIC candidates from becoming an uncoded distribution."""

    if _is_negative_or_unknown_limitation(
        claim_text,
        claim_kind=claim_kind,
    ):
        return []
    partial_kwic = [
        fact
        for fact in facts
        if fact.fact_kind == "kwic_example"
        and fact.exactness in {"partial", "sample_only", "top_n_only"}
    ]
    if not partial_kwic:
        return []
    violations: List[str] = []
    for clause in re.split(
        r"\n+|(?<=[.!?])\s+|;\s+(?=[A-ZÄÖÜ])",
        _prose_outside_examples(claim_text or ""),
    ):
        clause = clause.strip()
        if not clause:
            continue
        if not (
            _PARTIAL_KWIC_PREVALENCE_PATTERN.search(clause)
            or _PARTIAL_KWIC_DISCOURSE_SYSTEM_PATTERN.search(clause)
        ):
            continue
        if _claim_is_visibly_tentative(clause):
            continue
        if (
            _KWIC_EVALUATIVE_CATEGORY_PATTERN.search(clause)
            and _coded_kwic_prevalence_is_supported(clause, partial_kwic)
        ):
            continue
        violations.append(_compact_text(clause, 180))
    return _dedupe_ordered_strs(violations)


def _unsupported_visible_kwic_subset_counts(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> List[str]:
    """Bind a visible subset count to distinct, matching KWIC hits."""

    kwic_facts = [fact for fact in facts if fact.fact_kind == "kwic_example"]
    unique_facts: Dict[tuple[str, ...], ObservedFact] = {}
    for fact in kwic_facts:
        unique_facts.setdefault(_kwic_fact_identity(fact), fact)
    unsupported: List[str] = []
    for match in _VISIBLE_KWIC_SUBSET_COUNT_PATTERN.finditer(
        claim_text or ""
    ):
        raw_count = str(match.group("count") or "")
        value = raw_count if raw_count.isdigit() else _number_word_value(raw_count)
        if value is None:
            continue
        claimed_count = int(value)
        visible_total_raw = str(match.group("visible_total") or "")
        visible_total = (
            int(visible_total_raw)
            if visible_total_raw.isdigit()
            else _number_word_value(visible_total_raw)
        )
        if visible_total is not None and int(visible_total) > len(unique_facts):
            unsupported.append(match.group(0))
            continue
        membership_term = _kwic_subset_membership_term(
            claim_text or "",
            match.end(),
        )
        matching_facts = list(unique_facts.values())
        if membership_term:
            needle = _normalise_quote_for_match(membership_term)
            matching_facts = [
                fact
                for fact in matching_facts
                if needle
                and needle
                in _normalise_quote_for_match(
                    _joined_surface_text(
                        [fact.statement, *fact.grounding_quotes]
                    )
                )
            ]
        qualifier = str(match.group("qualifier") or "").casefold()
        enough = len(matching_facts) >= claimed_count
        if qualifier in {"genau", "exakt", "nur", "exactly", "only"}:
            enough = len(matching_facts) == claimed_count
        if not enough:
            unsupported.append(match.group(0))
    return _dedupe_ordered_strs(unsupported)


def _kwic_fact_identity(fact: ObservedFact) -> tuple[str, ...]:
    """Prefer stable document/position anchors over model-facing fact IDs."""

    surface = _joined_surface_text([fact.statement, *fact.grounding_quotes])
    position = _KWIC_POSITION_ANCHOR_PATTERN.search(surface)
    document = _KWIC_DOCUMENT_ANCHOR_PATTERN.search(surface)
    if position is not None:
        return (
            "position",
            str(document.group("doc") if document is not None else "").casefold(),
            str(position.group("pos") or position.group("natural_pos") or ""),
        )
    row = _KWIC_ROW_ANCHOR_PATTERN.search(surface)
    provenance = tuple(sorted(str(item) for item in fact.source_evidence_ids if item))
    if row is not None and provenance:
        return ("source_row", *provenance, str(row.group("row") or ""))
    return ("fact", str(fact.id))


def _kwic_subset_membership_term(text: str, match_end: int) -> str:
    sentence_tail = re.split(r"[.!?\n]", (text or "")[match_end:], maxsplit=1)[0]
    match = _KWIC_LITERAL_MEMBERSHIP_PATTERN.search(sentence_tail)
    if match is None:
        return ""
    term = next((value for value in match.groups() if value), "").strip()
    if term.casefold() in {
        "einen",
        "eine",
        "einem",
        "einer",
        "beleg",
        "beispiel",
        "muster",
        "treffer",
        "kontext",
        "wort",
        "token",
    }:
        return ""
    if _KWIC_EVALUATIVE_CATEGORY_PATTERN.fullmatch(term):
        return ""
    return term


def _normalise_kwic_category(value: str) -> str:
    token = str(value or "").casefold().strip(" _-")
    families = {
        "neutral": ("neutral", "sachlich", "factual"),
        "positive": ("positiv", "positive", "zustimm", "wohlwoll", "supportive"),
        "negative": ("negativ", "negative", "ablehn", "feind", "hostile"),
        "critical": ("kritisch", "critical"),
        "evaluative": ("wertend", "affirmativ", "delegitim", "stigmatis"),
    }
    for canonical, stems in families.items():
        if any(token.startswith(stem) for stem in stems):
            return canonical
    return token


def _fact_local_context_labels(fact: ObservedFact) -> set[str]:
    surface = _joined_surface_text([fact.statement, *fact.grounding_quotes])
    return {
        _normalise_kwic_category(match.group("label"))
        for match in _CONTEXT_CODING_ASSIGNMENT_PATTERN.finditer(surface)
        if str(match.group("label") or "").strip()
    }


def _claim_is_visibly_tentative(text: str) -> bool:
    return bool(
        _EXPLICIT_TESTABLE_HYPOTHESIS_PATTERN.search(text or "")
        or _TENTATIVE_THEME_PATTERN.search(text or "")
        or _ATTACHMENT_QUALIFIER_PATTERN.search(text or "")
        or _VISIBLE_EPISTEMIC_QUALIFIER_PATTERN.search(text or "")
    )


def _kwic_category_claim_is_supported(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    category_matches = list(
        _KWIC_EVALUATIVE_CATEGORY_PATTERN.finditer(claim_text or "")
    )
    if not category_matches:
        return True
    categories = {
        _normalise_kwic_category(match.group(0)) for match in category_matches
    }
    source_surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    metalinguistic = _KWIC_METALINGUISTIC_CATEGORY_PATTERN.search(claim_text or "")
    if metalinguistic is not None:
        literal = _normalise_quote_for_match(metalinguistic.group("label"))
        if literal and literal in _normalise_quote_for_match(source_surface):
            return True

    kwic_facts = [fact for fact in facts if fact.fact_kind == "kwic_example"]
    labels_by_identity: Dict[tuple[str, ...], set[str]] = {}
    for fact in kwic_facts:
        labels_by_identity.setdefault(_kwic_fact_identity(fact), set()).update(
            _fact_local_context_labels(fact)
        )
    if not labels_by_identity or any(not labels for labels in labels_by_identity.values()):
        return False
    visible_labels = set().union(*labels_by_identity.values())
    if not categories.issubset(visible_labels):
        return False
    if re.search(
        r"\b(?:beide|alle|sämtlich\w*|saemtlich\w*|jeweils|both|all)\b",
        claim_text or "",
        re.IGNORECASE,
    ) and len(categories) == 1:
        category = next(iter(categories))
        return all(category in labels for labels in labels_by_identity.values())
    for count_match in _VISIBLE_KWIC_SUBSET_COUNT_PATTERN.finditer(claim_text or ""):
        raw_count = str(count_match.group("count") or "")
        count = int(raw_count) if raw_count.isdigit() else _number_word_value(raw_count)
        if count is None or len(categories) != 1:
            continue
        category = next(iter(categories))
        labelled_count = sum(
            category in labels for labels in labels_by_identity.values()
        )
        qualifier = str(count_match.group("qualifier") or "").casefold()
        if qualifier in {"mindestens", "zumindest", "at least"}:
            return labelled_count >= int(count)
        return labelled_count == int(count)
    return True


def _coded_kwic_prevalence_is_supported(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    categories = {
        _normalise_kwic_category(match.group(0))
        for match in _KWIC_EVALUATIVE_CATEGORY_PATTERN.finditer(claim_text or "")
    }
    if len(categories) != 1:
        return False
    labels_by_identity: Dict[tuple[str, ...], set[str]] = {}
    for fact in facts:
        labels_by_identity.setdefault(_kwic_fact_identity(fact), set()).update(
            _fact_local_context_labels(fact)
        )
    if not labels_by_identity or any(not labels for labels in labels_by_identity.values()):
        return False
    category = next(iter(categories))
    count = sum(category in labels for labels in labels_by_identity.values())
    total = len(labels_by_identity)
    if re.search(
        r"\b(?:alle|sämtlich\w*|saemtlich\w*|ausschließlich\w*|"
        r"ausschliesslich\w*|all|exclusively)\b",
        claim_text or "",
        re.IGNORECASE,
    ):
        return count == total
    if re.search(
        r"\b(?:meist\w*|überwiegend\w*|ueberwiegend\w*|"
        r"mehrheitlich\w*|dominier\w*|vorherrsch\w*|mostly|majority|"
        r"predomin\w*)\b",
        claim_text or "",
        re.IGNORECASE,
    ):
        return count > total / 2
    return False


def _unsupported_exact_kwic_category_claim(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    claim_kind: str,
    assertion_level: str,
) -> bool:
    """Keep aggregate context coding distinct from local interpretation."""

    if _KWIC_EVALUATIVE_CATEGORY_PATTERN.search(claim_text or "") is None:
        return False
    kwic_facts = [fact for fact in facts if fact.fact_kind == "kwic_example"]
    if not kwic_facts:
        return False
    if _is_negative_or_unknown_limitation(
        claim_text,
        claim_kind=claim_kind,
    ):
        return False
    bounded_interpretation = bool(
        claim_kind == "interpretation"
        and assertion_level in {"qualified", "tentative"}
        and _is_explicitly_bounded_claim(claim_text)
        and len({_kwic_fact_identity(fact) for fact in kwic_facts}) >= 2
        and _VISIBLE_KWIC_SUBSET_COUNT_PATTERN.search(claim_text or "") is None
        and _PARTIAL_KWIC_PREVALENCE_PATTERN.search(claim_text or "") is None
    )
    if bounded_interpretation:
        # This is exactly the permitted analytical layer: a claim explicitly
        # about its cited visible passages, not a coded frequency statement.
        return False
    aggregate_category_claim = bool(
        claim_kind == "observation"
        or _VISIBLE_KWIC_SUBSET_COUNT_PATTERN.search(claim_text or "")
        or _PARTIAL_KWIC_PREVALENCE_PATTERN.search(claim_text or "")
        or _KWIC_SEMANTIC_DIVERSITY_PATTERN.search(claim_text or "")
        or _KWIC_AGGREGATE_CATEGORY_SCOPE_PATTERN.search(claim_text or "")
    )
    if not aggregate_category_claim:
        # A reading of one quoted passage is interpretation, not a hidden
        # annotation layer. Other source-anchor guards validate that reading.
        return False
    # Hidden schema metadata cannot turn an assertive sentence into a
    # hypothesis. The qualification must be visible to the researcher.
    if _claim_is_visibly_tentative(claim_text):
        return False
    return not _kwic_category_claim_is_supported(claim_text, facts)


def _followup_uses_kwic_as_collocation_statistic(claim_text: str) -> bool:
    return bool(
        _KWIC_AS_COLLOCATION_METHOD_PATTERN.search(claim_text or "")
        and not _EXPLICIT_COLLOCATION_METHOD_PATTERN.search(claim_text or "")
    )


_KWIC_AMBIGUITY_PATTERN = re.compile(
    r"\b(?:mehrdeutig\w*|möglich\w*\s+lesart\w*|"
    r"moeglich\w*\s+lesart\w*|anbindung\w*\s+(?:bleibt\s+)?offen|"
    r"bezug\w*\s+(?:bleibt\s+)?offen|verschiedene\w*\s+lesart\w*|"
    r"bleibt\s+(?:jedoch\s+)?offen\s*,?\s+(?:ob|welche\w*|wie)|"
    r"kann\b[^.!?\n]{0,100}\b(?:oder|sowohl)\b|"
    r"ambiguous\w*|possible\w*\s+reading\w*|"
    r"(?:attachment|reference)\w*\s+(?:remains?\s+)?open|"
    r"can\b[^.!?\n]{0,100}\b(?:or|both)\b)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# validate_answer_envelope rule wrappers (K3 Slice 2, step 3).
# Each function holds one cascade block verbatim (dedented one level).
# The generated prologue unpacks the names the block reads from the
# per-claim context when they are present; the epilogue writes every
# name the block (re)binds back into the context. Helper functions
# arrive through the context (seeded from the facade's globals), so
# facade-level monkeypatch seams keep working.
# --------------------------------------------------------------------------- #
def _vae_rule_unsupported_kwic_source_role_attribution(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6584-6592)."""
    if "_unsupported_kwic_source_role_attribution" in _vae_ctx:
        _unsupported_kwic_source_role_attribution = _vae_ctx["_unsupported_kwic_source_role_attribution"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _unsupported_kwic_source_role_attribution(
        claim.text,
        facts,
    ):
        claim_reasons.append(
            "Der Claim schreibt den sichtbaren Wortlaut einem Autor, "
            "Sprecher oder Verfasser zu, ohne dass Passage oder Metadaten "
            "diese Quellenrolle ausweisen."
        )


def _vae_rule_unsupported_context_interpretations(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6617-6631)."""
    if "_unsupported_expanded_context_interpretations" in _vae_ctx:
        _unsupported_expanded_context_interpretations = _vae_ctx["_unsupported_expanded_context_interpretations"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_context_interpretations" in _vae_ctx:
        unsupported_context_interpretations = _vae_ctx["unsupported_context_interpretations"]
    unsupported_context_interpretations = (
        _unsupported_expanded_context_interpretations(
            analytical_prose,
            facts,
            raw_claim_text=claim.text,
        )
    )
    if unsupported_context_interpretations:
        claim_reasons.append(
            "Die Deutung des erweiterten KWIC-Kontexts widerspricht dem "
            "Wortlaut oder legt eine syntaktische Anbindung ohne passende "
            "Evidenz fest: "
            + ", ".join(unsupported_context_interpretations[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_context_interpretations",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_open_window_interpretations(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6632-6645)."""
    if "_unsupported_open_kwic_window_interpretations" in _vae_ctx:
        _unsupported_open_kwic_window_interpretations = _vae_ctx["_unsupported_open_kwic_window_interpretations"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_open_window_interpretations" in _vae_ctx:
        unsupported_open_window_interpretations = _vae_ctx["unsupported_open_window_interpretations"]
    unsupported_open_window_interpretations = (
        _unsupported_open_kwic_window_interpretations(
            claim.text,
            facts,
        )
    )
    if unsupported_open_window_interpretations:
        claim_reasons.append(
            "Die Deutung des erweiterten KWIC-Kontexts widerspricht dem "
            "Wortlaut oder legt eine syntaktische Anbindung ohne passende "
            "Evidenz fest: "
            + ", ".join(unsupported_open_window_interpretations[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_open_window_interpretations",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_kwic_diversity(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6646-6660)."""
    if "_unsupported_kwic_semantic_diversity_claims" in _vae_ctx:
        _unsupported_kwic_semantic_diversity_claims = _vae_ctx["_unsupported_kwic_semantic_diversity_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_kwic_diversity" in _vae_ctx:
        unsupported_kwic_diversity = _vae_ctx["unsupported_kwic_diversity"]
    unsupported_kwic_diversity = (
        _unsupported_kwic_semantic_diversity_claims(
            analytical_prose,
            facts,
            assertion_level=claim.assertion_level,
        )
    )
    if unsupported_kwic_diversity:
        claim_reasons.append(
            "Semantische Vielfalt über mehrere KWIC-Zeilen braucht "
            "erweiterte Kontexte oder eine explizite Kontextkodierung; "
            "schmale KWIC-Fenster liefern dafür nur Kandidaten: "
            + ", ".join(unsupported_kwic_diversity[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_kwic_diversity",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_kwic_prevalence(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6661-6676)."""
    if "_unsupported_partial_kwic_prevalence_claims" in _vae_ctx:
        _unsupported_partial_kwic_prevalence_claims = _vae_ctx["_unsupported_partial_kwic_prevalence_claims"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_kwic_prevalence" in _vae_ctx:
        unsupported_kwic_prevalence = _vae_ctx["unsupported_kwic_prevalence"]
    unsupported_kwic_prevalence = (
        _unsupported_partial_kwic_prevalence_claims(
            analytical_prose,
            facts,
            claim_kind=claim.claim_kind,
        )
    )
    if unsupported_kwic_prevalence:
        claim_reasons.append(
            "Sichtbare oder partielle KWIC-Zeilen sind ohne explizite "
            "Kontextkodierung keine Häufigkeitsverteilung. Formuliere "
            "daraus eine prüfbare Hypothese statt einen bereits "
            "etablierten Korpusbefund: "
            + ", ".join(unsupported_kwic_prevalence[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_kwic_prevalence",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_kwic_subset_counts(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6677-6690)."""
    if "_unsupported_visible_kwic_subset_counts" in _vae_ctx:
        _unsupported_visible_kwic_subset_counts = _vae_ctx["_unsupported_visible_kwic_subset_counts"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "unsupported_kwic_subset_counts" in _vae_ctx:
        unsupported_kwic_subset_counts = _vae_ctx["unsupported_kwic_subset_counts"]
    unsupported_kwic_subset_counts = (
        _unsupported_visible_kwic_subset_counts(
            analytical_prose,
            facts,
        )
    )
    if unsupported_kwic_subset_counts:
        claim_reasons.append(
            "Eine behauptete Anzahl in einer sichtbar klassifizierten "
            "KWIC-Teilmenge braucht mindestens ebenso viele getrennt "
            "referenzierte KWIC-Belege: "
            + ", ".join(unsupported_kwic_subset_counts[:3])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("unsupported_kwic_subset_counts",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_unsupported_exact_kwic_category_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6691-6702)."""
    if "_unsupported_exact_kwic_category_claim" in _vae_ctx:
        _unsupported_exact_kwic_category_claim = _vae_ctx["_unsupported_exact_kwic_category_claim"]
    if "analytical_prose" in _vae_ctx:
        analytical_prose = _vae_ctx["analytical_prose"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if _unsupported_exact_kwic_category_claim(
        analytical_prose,
        facts,
        claim_kind=claim.claim_kind,
        assertion_level=claim.assertion_level,
    ):
        claim_reasons.append(
            "Eine wertende oder semantische Kontextkategorie ist ohne "
            "explizite Kontextkodierung keine exakte Beobachtung. Sie "
            "kann als evidenzgebundene Interpretation oder prüfbare "
            "Hypothese formuliert werden."
        )


def _vae_rule_has_definitive_global_scope_claim(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 7689-7706)."""
    if "_has_definitive_global_scope_claim" in _vae_ctx:
        _has_definitive_global_scope_claim = _vae_ctx["_has_definitive_global_scope_claim"]
    if "_is_existential_kwic_evidence_claim" in _vae_ctx:
        _is_existential_kwic_evidence_claim = _vae_ctx["_is_existential_kwic_evidence_claim"]
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
    if (
        claim.claim_kind != "followup"
        and not negative_or_unknown_limitation
        and not _is_existential_kwic_evidence_claim(
            claim.text,
            facts,
        )
        and any(
            fact.exactness
            in {"partial", "sample_only", "top_n_only", "derived"}
            for fact in facts
        )
        and _has_definitive_global_scope_claim(claim.text)
    ):
        claim_reasons.append(
            "Partielle, gesampelte oder Top-N-Evidenz trägt keinen "
            "affirmativen korpusweiten Geltungsanspruch."
        )
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]
