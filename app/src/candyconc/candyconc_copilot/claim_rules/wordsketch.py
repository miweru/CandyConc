"""Word-sketch claim rules: prevalence, relation-threshold and query-role predicates.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import List, Sequence

from ..grounding_schemas import (
    ObservedFact,
    _compact_text,
    _normalised_question_text,
)
from ._shared import (
    _NUMBER_WORD_TOKEN_SOURCE,
    _contains_literal_label,
    _field_numeric_values,
    _is_explicitly_bounded_claim,
    _joined_surface_text,
    _normalize_number_token,
    _number_word_value,
    _prose_outside_examples,
    _source_values_for_field,
)


_STATISTICAL_CERTAINTY_PATTERN = re.compile(
    r"\b(?:statistisch\s+)?signifikant(?:e|en|er|es)?\b|"
    r"\bstatistisch\s+(?:bedeutsam|bedeutend|relevant)"
    r"(?:e|en|er|es)?\b|"
    r"\bstatistically\s+(?:meaningful|significant)\b|"
    r"\bstabil(?:e|en|er|es)?\s+(?:kollok\w*|assoziat\w*|muster\w*)\b|"
    r"\b(?:inferenz)?statistisch\s+"
    r"(?:abgesichert|belastbar|bestätigt|bestaetigt)\b|"
    r"\bstatistisch\s+(?:nachgewiesen|belegt)\b|"
    r"\b(?:überzufällig|ueberzufaellig)\w*\b|"
    r"\b(?:überschreitet|ueberschreitet|übersteigt|uebersteigt)\b"
    r"[^.!?\n]{0,60}\b(?:die\s+)?zufallserwartung\b",
    re.IGNORECASE,
)


_EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN = re.compile(
    r"\b(?:p(?:_value|-wert)?|alpha|konfidenz(?:intervall)?|"
    r"signifikanzschwelle|significance_threshold)\s*=",
    re.IGNORECASE,
)


_WORD_SKETCH_PREVALENCE_PATTERN = re.compile(
    r"\b(?:häufig(?:e|en|er|es|ste|sten|ster|stes)?|"
    r"haeufig(?:e|en|er|es|ste|sten|ster|stes)?|"
    r"selten(?:e|en|er|es|ste|sten|ster|stes)?|"
    r"typisch(?:e|en|er|es|erweise)?|meist(?:ens)?|gelegentlich|"
    r"überwiegend|ueberwiegend|dominant(?:e|en|er|es)?|"
    r"frequent(?:ly|er|est)?|rare(?:ly|r|st)?|"
    r"occasionally|typical(?:ly)?|most\s+common)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_ABSOLUTE_PREVALENCE_PATTERN = re.compile(
    r"\b(?:häufig(?:e|en|es)?|haeufig(?:e|en|es)?|"
    r"selten(?:e|en|es)?|typisch(?:e|en|er|es|erweise)?|"
    r"meist(?:ens)?|gelegentlich|überwiegend|ueberwiegend|"
    r"dominant(?:e|en|er|es)?|frequently|rarely|occasionally|"
    r"typical(?:ly)?)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_EMPHASISED_SEGMENT_PATTERN = re.compile(
    r"(?<!\*)\*([^*\n]{2,180})\*(?!\*)"
)
_WORD_SKETCH_COUNT_UNIT_PATTERN = re.compile(
    rf"\b(?P<number>{_NUMBER_WORD_TOKEN_SOURCE}|\d+(?:[.,]\d+)?)\s+"
    r"(?:indexiert(?:e|en|er|es)?\s+)?"
    r"(?P<unit>Dependenzereignis\w*|Abhängigkeitsereignis\w*|"
    r"Abhaengigkeitsereignis\w*|Ereignis\w*|Vorkomm\w*|"
    r"occurrence\w*|event\w*|Token\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_ONCE_PATTERN = re.compile(
    r"\b(?:tritt|erscheint|kommt)\s+(?:nur\s+)?einmal\s+"
    r"(?:auf|vor)\b|\boccurs?\s+(?:only\s+)?once\b",
    re.IGNORECASE,
)
_WORD_SKETCH_FALSE_ABSENCE_PATTERN = re.compile(
    r"\b(?:kein(?:e|en|er|es)?\s+(?:konkret\w*\s+)?(?:f[- ]?wert\w*|"
    r"häufigkeitswert\w*|haeufigkeitswert\w*|messwert\w*|"
    r"metric[_ -]?rows?[- ]?beleg\w*)|"
    r"kein(?:en)?\s+zugriff\b[^.!?\n]{0,100}\b(?:word[- ]?sketch|tool)|"
    r"(?:word[- ]?sketch|tool)\b[^.!?\n]{0,100}\b"
    r"nicht\s+zur\s+verfügung|keine\s+tools?\s+zur\s+verfügung)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_QUERY_ROLE_PATTERN = re.compile(
    r"\b(?:suchterm|suchbegriff|zielwort|knoten|wortstelle|begriff|"
    r"wort|lemma|ausdruck)\w*\b[^.!?\n]{0,180}?"
    r"\b(?:sowohl\s+)?als\s+(?:nomen[- ]?kern|nominalkern|kern|"
    r"attribut|koordinator|artikel|determinant|determiner)\w*\b|"
    r"\b(?:suchterm|suchbegriff|zielwort|knoten|wortstelle|begriff|"
    r"wort|lemma|ausdruck)\w*\b[^.!?\n]{0,180}?"
    r"\b(?:fungier\w*|agier\w*|erschein\w*)\b[^.!?\n]{0,80}?"
    r"\b(?:nomen[- ]?kern|nominalkern|kern|attribut|koordinator)\w*\b",
    re.IGNORECASE,
)
_WORD_SKETCH_QUERY_PARTICIPATION_PATTERN = re.compile(
    r"\b(?:suchterm|suchbegriff|zielwort|knoten|wortstelle|begriff|wort|"
    r"lemma|ausdruck|entität|entitaet|substantiv)\w*\b"
    r"(?:[^.!?\n]{0,180}\b(?:in|innerhalb)\b[^.!?\n]{0,140}"
    r"\b(?:relation|beziehung|position|rolle|gefüge|gefuege|struktur)\w*\b"
    r"[^.!?\n]{0,100}\b(?:eingebund\w*|vorkomm\w*|auftret\w*|"
    r"steh\w*|verwend\w*|befind\w*)\b|"
    r"[^.!?\n]{0,120}\b(?:eingebund\w*|vorkomm\w*|auftret\w*|"
    r"erschein\w*|steh\w*|komm\w*)\b[^.!?\n]{0,80}\b(?:in|innerhalb)\b"
    r"[^.!?\n]{0,100}\b(?:relation|beziehung|position|gefüge|gefuege|"
    r"rolle|struktur)\w*\b)",
    re.IGNORECASE,
)
_WORD_SKETCH_QUERY_FUNCTION_OVERREAD_PATTERN = re.compile(
    r"\b(?:suchterm|suchbegriff|zielwort|knoten|wortstelle|begriff|wort|"
    r"lemma|ausdruck)\w*\b[^.!?\n]{0,180}"
    r"\b(?:syntaktisch\w*\s+verbind\w*|substantivisch\w*\s+"
    r"zentral\w*|verbindend\w*\s+element\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_ROW_CONTEXT_PATTERN = re.compile(
    r"\b(?:phrase\w*|wortgruppe\w*|nominalgruppe\w*|"
    r"koordinationswort\w*|"
    r"possessivpronomen\w*|possessivdetermin\w*|"
    r"bestimmt\w*\s+artikel\w*|artikel\w*|determinat\w*|"
    r"konjunktion(?:spartner)?\w*|preposition\w*|determiner\w*|"
    r"possessive\w*\s+(?:pronoun|determiner)\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_UNSUPPORTED_POS_PATTERN = re.compile(
    r"\b(?:koordinationswort\w*|possessivpronomen\w*|"
    r"bestimmt\w*\s+artikel\w*|artikel\w*|determinat\w*|"
    r"konjunktion(?:spartner|selement)?\w*|preposition\w*|"
    r"determiner\w*|possessive\w*\s+(?:pronoun|determiner)\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_RELATION_THRESHOLD_PATTERN = re.compile(
    r"\b(?:relation(?:sart|styp)?|relations?\s+type)\w*\b"
    r"[^.!?\n]{0,140}\b(?:beide|alle|sie|both|all)\b"
    r"[^.!?\n]{0,80}\b(?:über|oberhalb|erreich\w*|above|reach\w*)\b"
    r"[^.!?\n]{0,60}\b(?:mindestfrequenz\w*|min_freq|"
    r"schwelle\w*|threshold\w*)\b"
    r"|\b(?:relation(?:sart|styp)?|relations?\s+type)\w*\b"
    r"(?=[^.!?\n]{0,180}\b(?:beide|alle|sie|both|all)\b)"
    r"(?=[^.!?\n]{0,180}\b(?:mindestfrequenz\w*|minimum|min_freq|"
    r"schwelle\w*|threshold\w*)\b)"
    r"[^.!?\n]{0,200}\b(?:erfüll\w*|erreich\w*|meet\w*)\b"
    r"|\b(?:abhängigkeits|abhaengigkeits|dependenz)?relation(?:sart|styp)?\w*\b"
    r"(?=[^.!?\n]{0,180}\b(?:mindestfrequenz\w*|minimum|min_freq|"
    r"schwelle\w*|threshold\w*)\b)"
    r"[^.!?\n]{0,220}\b(?:überschreit\w*|ueberschreit\w*|"
    r"übertreff\w*|uebertreff\w*|erfüll\w*|erreich\w*|"
    r"lieg\w*|exceed\w*|meet\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_UNREPORTED_RELATION_PATTERN = re.compile(
    r"\b(?:alle\s+ander\w*|sämtlich\w*\s+ander\w*|"
    r"saemtlich\w*\s+ander\w*|all\s+other)\b"
    r"[^.!?\n]{0,100}\b(?:relation\w*|relation\s+types?)\b"
    r"[^.!?\n]{0,100}\b(?:unter|below)\b"
    r"[^.!?\n]{0,60}\b(?:schwelle\w*|mindestfrequenz\w*|"
    r"min_freq|threshold\w*)\b",
    re.IGNORECASE,
)
_WORD_SKETCH_PARTNER_EXCLUSIVITY_PATTERN = re.compile(
    r"\b(?:erschein\w*|vorkomm\w*|auftret\w*|steh\w*)\b"
    r"[^.!?\n]{0,80}\b(?:ausschließlich|ausschliesslich|nur|einzig)\b"
    r"[^.!?\n]{0,80}\b(?:in|bei)\b[^.!?\n]{0,50}\brelation\w*\b|"
    r"\b(?:ausschließlich|ausschliesslich|nur|einzig)\b"
    r"[^.!?\n]{0,80}\b(?:in|bei)\b[^.!?\n]{0,50}\brelation\w*\b",
    re.IGNORECASE,
)


def _word_sketch_semantic_violations(
    claim_text: str,
    facts: Sequence[ObservedFact],
    *,
    question_term: str = "",
) -> List[str]:
    sketch_facts = [
        fact
        for fact in facts
        if any(
            "word_sketch" in str(source_id or "").casefold()
            for source_id in fact.source_evidence_ids
        )
    ]
    if not sketch_facts:
        return []

    row_facts = [
        fact for fact in sketch_facts if fact.fact_kind == "ranked_row"
    ]
    row_surface = _joined_surface_text(
        [fact.statement for fact in row_facts]
        + [quote for fact in row_facts for quote in fact.grounding_quotes]
    )
    raw_f_values = _field_numeric_values(
        row_surface,
        ("f", "frequency"),
    )
    f_values = {
        int(float(value))
        for value in raw_f_values
        if float(value).is_integer()
    }
    supported_event_counts = {0}
    for value in f_values:
        supported_event_counts.update(
            existing + value
            for existing in list(supported_event_counts)
        )
    supported_event_counts.discard(0)
    f2_values = _field_numeric_values(row_surface, ("f2",))
    violations: List[str] = []

    for match in _WORD_SKETCH_COUNT_UNIT_PATTERN.finditer(claim_text or ""):
        raw_number = match.group("number")
        normalised = (
            _number_word_value(raw_number)
            or _normalize_number_token(raw_number)
        )
        if not normalised or not re.fullmatch(r"\d+(?:\.\d+)?", normalised):
            continue
        unit = match.group("unit").casefold()
        if unit.startswith("token"):
            if normalised not in f2_values:
                violations.append(
                    f"{match.group(0)} bezeichnet einen f-Wert fälschlich als Tokenzahl"
                )
            continue
        number = float(normalised)
        if not number.is_integer() or int(number) not in supported_event_counts:
            violations.append(
                f"{match.group(0)} verwechselt Partnerzeilen mit Dependenzereignissen"
            )

    if (
        _WORD_SKETCH_ONCE_PATTERN.search(claim_text or "")
        and 1 not in supported_event_counts
    ):
        violations.append(
            "einmaliges Auftreten verwechselt eine Partnerzeile mit ihrem f-Wert"
        )

    sketch_surface = _joined_surface_text(
        [fact.statement for fact in sketch_facts]
        + [quote for fact in sketch_facts for quote in fact.grounding_quotes]
    )
    if (
        _WORD_SKETCH_UNSUPPORTED_POS_PATTERN.search(claim_text or "")
        and re.search(r"\bpos\s*=", sketch_surface, re.IGNORECASE) is None
    ):
        violations.append(
            "Partnerformen werden ohne POS-Evidenz einer Wortart zugeordnet"
        )

    row_labels = {
        value
        for fact in row_facts
        for value in _source_values_for_field(
            "word",
            _joined_surface_text([fact.statement, *fact.grounding_quotes]),
        )
        if value
    }
    if (
        _WORD_SKETCH_PARTNER_EXCLUSIVITY_PATTERN.search(claim_text or "")
        and any(
            _contains_literal_label(claim_text, label)
            for label in row_labels
        )
        and not _is_explicitly_bounded_claim(claim_text)
    ):
        violations.append(
            "eine sichtbare Partnerzeile belegt ohne explizite Begrenzung "
            "nicht, dass der Partner in keiner anderen Relation vorkommt"
        )
    for match in _WORD_SKETCH_EMPHASISED_SEGMENT_PATTERN.finditer(
        claim_text or ""
    ):
        segment = _compact_text(match.group(1), 180)
        if not segment:
            continue
        lexical_tokens = re.findall(r"\w+", segment, re.UNICODE)
        if len(lexical_tokens) < 2 and not re.search(r"(?:\.\.\.|…)", segment):
            continue
        if any(
            _contains_literal_label(segment, label)
            and _normalised_question_text(segment)
            != _normalised_question_text(label)
            for label in row_labels
        ):
            violations.append(
                "eine hervorgehobene Konstruktion rekonstruiert aus Suchterm "
                "und Partner eine nicht belegte fortlaufende Phrase"
            )
            break
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", claim_text or ""):
        if _WORD_SKETCH_ROW_CONTEXT_PATTERN.search(sentence) is None:
            continue
        if re.search(
            r"\b(?:kein(?:e|en|er|es)?|nicht)\b[^.!?]{0,32}"
            r"(?:phrase|pos|wortart|artikel|pronomen|determiner)",
            sentence,
            re.IGNORECASE,
        ):
            continue
        if any(
            (
                len(label) > 3
                and _contains_literal_label(sentence, label)
            )
            or re.search(
                rf"(?:`|\*|['\"„“]){re.escape(label)}(?:`|\*|['\"„“])",
                sentence,
                re.IGNORECASE,
            )
            is not None
            for label in row_labels
        ):
            violations.append(
                "Partnerzeilen liefern weder fortlaufende Phrasen noch POS-Kategorien"
            )
            break

    if _WORD_SKETCH_UNREPORTED_RELATION_PATTERN.search(claim_text or ""):
        violations.append(
            "sichtbare Relationslisten belegen nicht den Schwellenstatus "
            "aller nicht ausgegebenen Relationstypen"
        )
    if _WORD_SKETCH_RELATION_THRESHOLD_PATTERN.search(claim_text or ""):
        violations.append(
            "min_freq gilt für Partnerzeilen, nicht als Schwellenwert einer "
            "Relation als Ganzes"
        )
    if (
        _STATISTICAL_CERTAINTY_PATTERN.search(
            _prose_outside_examples(claim_text or "")
        )
        and _EXPLICIT_SIGNIFICANCE_EVIDENCE_PATTERN.search(sketch_surface)
        is None
    ):
        violations.append(
            "deskriptive Assoziationsmaße wie t oder LogDice belegen keine "
            "inferenzstatistische Signifikanz"
        )
    role_assignment = _WORD_SKETCH_QUERY_ROLE_PATTERN.search(
        claim_text or ""
    )
    if role_assignment is None:
        role_assignment = _WORD_SKETCH_QUERY_PARTICIPATION_PATTERN.search(
            claim_text or ""
        )
    if role_assignment is None:
        role_assignment = _WORD_SKETCH_QUERY_FUNCTION_OVERREAD_PATTERN.search(
            claim_text or ""
        )
    if role_assignment is None and question_term:
        role_assignment = re.search(
            rf"(?<!\w){re.escape(question_term)}(?!\w)"
            r"(?:[^.!?\n]{0,160}?\b(?:sowohl\s+)?als\s+"
            r"(?:nomen[- ]?kern|nominalkern|kern|attribut|koordinator|"
            r"artikel|determinant|determiner)\w*\b|"
            r"[^.!?\n]{0,180}\b(?:in|innerhalb)\b[^.!?\n]{0,140}"
            r"\b(?:relation|beziehung|position|rolle|gefüge|gefuege|struktur)\w*\b"
            r"[^.!?\n]{0,100}\b(?:eingebund\w*|vorkomm\w*|auftret\w*|"
            r"steh\w*|verwend\w*|befind\w*)\b|"
            r"[^.!?\n]{0,120}\b(?:eingebund\w*|vorkomm\w*|auftret\w*|"
            r"erschein\w*|steh\w*|komm\w*)\b[^.!?\n]{0,80}"
            r"\b(?:in|innerhalb)\b[^.!?\n]{0,100}"
            r"\b(?:relation|beziehung|position|rolle|gefüge|gefuege|struktur)\w*\b)",
            claim_text or "",
            re.IGNORECASE,
        )
    if role_assignment is not None:
        violations.append(
            "ein Relationslabel wird unzulässig als syntaktische Rolle des "
            "Suchterms oder Partners gelesen"
        )
    return list(dict.fromkeys(violations))


def _word_sketch_evidence_is_falsely_absent(
    claim_text: str,
    observed_facts: Sequence[ObservedFact],
) -> bool:
    """Reject missing-tool/metric claims after a successful sketch result."""

    return bool(
        _WORD_SKETCH_FALSE_ABSENCE_PATTERN.search(claim_text or "")
        and any(
            fact.fact_kind == "ranked_row"
            and any(
                "word_sketch" in str(source_id or "").casefold()
                for source_id in fact.source_evidence_ids
            )
            for fact in observed_facts
        )
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
def _vae_rule_word_sketch_violations(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6066-6077)."""
    if "_word_sketch_semantic_violations" in _vae_ctx:
        _word_sketch_semantic_violations = _vae_ctx["_word_sketch_semantic_violations"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "facts" in _vae_ctx:
        facts = _vae_ctx["facts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "question_term" in _vae_ctx:
        question_term = _vae_ctx["question_term"]
    if "word_sketch_violations" in _vae_ctx:
        word_sketch_violations = _vae_ctx["word_sketch_violations"]
    word_sketch_violations = _word_sketch_semantic_violations(
        claim.text,
        facts,
        question_term=question_term,
    )
    if word_sketch_violations and not negative_or_unknown_limitation:
        claim_reasons.append(
            "Word-Sketch-Zähleinheit oder Evidenzumfang ist nicht "
            "belegt: "
            + "; ".join(word_sketch_violations[:4])
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("word_sketch_violations",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_word_sketch_evidence_is_falsely_absent(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6078-6086)."""
    if "_word_sketch_evidence_is_falsely_absent" in _vae_ctx:
        _word_sketch_evidence_is_falsely_absent = _vae_ctx["_word_sketch_evidence_is_falsely_absent"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "observed_facts" in _vae_ctx:
        observed_facts = _vae_ctx["observed_facts"]
    if _word_sketch_evidence_is_falsely_absent(
        claim.text,
        observed_facts,
    ):
        claim_reasons.append(
            "Die Antwort behauptet fehlenden Word-Sketch-Zugriff oder "
            "fehlende Messwerte, obwohl sichtbare Word-Sketch-Zeilen mit "
            "f-Werten vorliegen."
        )
