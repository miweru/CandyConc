"""Metadata claim rules: singleton, homogeneity and confirmation predicates.

K3 Slice 2 (step 2): byte-verbatim extraction from ``analysis_grounding.py``.
The facade re-exports every name below eagerly, so all existing imports and
``analysis_grounding.<name>`` seams keep working. This module never imports
the facade.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Sequence

from ..grounding_schemas import (
    ObservedFact,
)
from ._shared import (
    _followup_changes_analysis_scope,
    _joined_surface_text,
    _metadata_fields_mentioned,
    _metadata_value_counts,
)


_FOLLOWUP_COMPLETE_METADATA_INVENTORY_PATTERN = re.compile(
    r"(?:"
    r"\bwelche\s+(?:weiteren?|anderen?|zusätzlichen?)?\s*"
    r"metadaten(?:attribute|felder)?\b[^?\n]{0,180}"
    r"\b(?:zur\s+verfügung|verfügbar|vorhanden|existieren|gibt\s+es)\b"
    r"|"
    r"\bwhat\s+(?:other|additional)?\s*metadata\s+"
    r"(?:attributes|fields)\b[^?\n]{0,180}\b(?:available|exist)\b"
    r")",
    re.IGNORECASE,
)
_FOLLOWUP_SETTLED_METADATA_USABILITY_PATTERN = re.compile(
    r"(?:"
    r"\blassen\s+sich\b[^?\n]{0,100}\bmetadaten(?:attribute|felder)?\b"
    r"[^?\n]{0,140}\b(?:vergleich|nutzen|nutzbar|geeignet)\w*"
    r"|"
    r"\bmetadaten(?:attribute|felder)?\b[^?\n]{0,160}"
    r"\b(?:durchweg|weitgehend|alle|insgesamt)\b[^?\n]{0,80}"
    r"\b(?:homogen|einwertig|nutzbar|geeignet)\w*"
    r")",
    re.IGNORECASE,
)


_METADATA_SINGLETON_CLAIM_PATTERN = re.compile(
    r"\b(?:(?:jeweils\s+)?(?:genau|nur)\s+"
    r"ein(?:e|en|em|er|es)?\s+(?:belegt\w*\s+)?wert"
    r"|exactly\s+one\s+(?:observed\s+)?value)\b",
    re.IGNORECASE,
)
_METADATA_UNIVERSAL_HOMOGENEITY_PATTERN = re.compile(
    r"(?:"
    r"\b(?:alle[nrsm]?|sämtliche[nrsm]?|saemtliche[nrsm]?)\b"
    r"[^.!?\n]{0,120}\b(?:feld\w*|metadatenachs\w*|dimension\w*)\b"
    r"[^.!?\n]{0,120}\b(?:homogen|einwertig|monovalent)\w*"
    r"|"
    r"\b(?:homogen|einwertig|monovalent)\w*"
    r"[^.!?\n]{0,120}\b(?:alle[nrsm]?|sämtliche[nrsm]?|saemtliche[nrsm]?)\b"
    r"[^.!?\n]{0,120}\b(?:feld\w*|metadatenachs\w*|dimension\w*)\b"
    r")",
    re.IGNORECASE,
)
_METADATA_HOMOGENEITY_PATTERN = re.compile(
    r"\b(?:einheitlich|homogen|einwertig|monovalent)\w*\b",
    re.IGNORECASE,
)
_METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN = re.compile(
    r"\b(?:sichtbar|belegt|zurückgegeben|zurueckgegeben|distinkt|"
    r"unter\s+den\s+(?:nichtleeren|sichtbaren|belegten)\s+werten)\w*\b",
    re.IGNORECASE,
)


_METADATA_CONFIRMATION_PATTERN = re.compile(
    r"(?:"
    r"\b(?:homogen\w*|einheitlich\w*|einwertig\w*|monovalent\w*)\b"
    r"[^.!?\n]{0,160}\b(?:bestätig\w*|bestaetig\w*|nachweis\w*|beleg\w*)\b"
    r"|"
    r"\b(?:bestätig\w*|bestaetig\w*|nachweis\w*|beleg\w*)\b"
    r"[^.!?\n]{0,160}\b(?:homogen\w*|einheitlich\w*|einwertig\w*|monovalent\w*)\b"
    r")",
    re.IGNORECASE,
)


# H6 (B4): Leerheits-Praedikate, die ein Metadatenfeld faelschlich als
# wertlos/leer deklarieren koennen. Bewusst eng: nur eindeutige
# Absenz-Formulierungen, kein Treffer auf "wenige Werte" oder
# quantifizierte Aussagen wie "2000 distinkte Werte".
_METADATA_FALSE_ABSENCE_PATTERN = re.compile(
    r"(?:"
    r"\bkeine?\s+(?:einzigen?\s+)?"
    r"(?:belegten?\s+|sichtbaren?\s+|distinkten?\s+)?wert\w*\b"
    r"|\bnicht\s+belegt\w*\b"
    r"|\bwertlos\w*\b"
    r"|\bleer(?:e[snmr]?)?\b"
    r"|\bno\s+values?\b"
    r"|\bempty\b"
    r")",
    re.IGNORECASE,
)
# Negatoren unmittelbar vor dem Praedikat entkraeften den Treffer
# ("nicht leer", "keineswegs wertlos").
_METADATA_FALSE_ABSENCE_NEGATOR_PATTERN = re.compile(
    r"(?:\bnicht\s+|\bnie(?:mals)?\s+|\bkeineswegs\s+|\bnot\s+)$",
    re.IGNORECASE,
)


def _clause_asserts_metadata_emptiness(clause: str) -> bool:
    text = str(clause or "")
    for match in _METADATA_FALSE_ABSENCE_PATTERN.finditer(text):
        prefix = text[max(0, match.start() - 24):match.start()]
        if _METADATA_FALSE_ABSENCE_NEGATOR_PATTERN.search(prefix):
            continue
        return True
    return False


def _metadata_values_falsely_absent_fields(
    claim_text: str,
    metadata_value_counts: Mapping[str, int],
) -> List[str]:
    """Fields the claim calls empty although evidence counts values (H6, B4).

    Conservative by design: the rule fires only when the field name AND an
    unambiguous emptiness predicate appear in the same clause, and only for
    fields whose value_count fact reports count > 0.
    """

    positive_fields = [
        field_name
        for field_name, count in metadata_value_counts.items()
        if isinstance(count, int) and count > 0
    ]
    if not positive_fields:
        return []
    result: List[str] = []
    for sentence in re.split(r"(?<=[.!?;:])\s+", str(claim_text or "")):
        clauses = re.split(
            r"\s+(?:während|waehrend|hingegen|jedoch|aber|wohingegen)\s+",
            sentence,
            flags=re.IGNORECASE,
        )
        for clause in clauses:
            if not _clause_asserts_metadata_emptiness(clause):
                continue
            result.extend(_metadata_fields_mentioned(clause, positive_fields))
    return list(dict.fromkeys(result))


_MORE_DOCUMENTS_FOR_METADATA_VARIANCE_PATTERN = re.compile(
    r"\b(?:weitere\w*|mehr|zusätzliche\w*|zusaetzliche\w*)\s+dokument\w*\b"
    r"[^.!?\n]{0,180}\b(?:metadaten|feld\w*|wert\w*|varianz|abdeckung)\b"
    r"|"
    r"\b(?:metadaten|feld\w*|wert\w*|varianz|abdeckung)\b"
    r"[^.!?\n]{0,180}\b(?:weitere\w*|mehr|zusätzliche\w*|"
    r"zusaetzliche\w*)\s+dokument\w*\b",
    re.IGNORECASE,
)


def _metadata_homogeneity_is_prejudged(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _METADATA_CONFIRMATION_PATTERN.search(claim_text or "") is None:
        return False
    surface = _joined_surface_text(
        [fact.statement for fact in facts]
        + [quote for fact in facts for quote in fact.grounding_quotes]
    )
    return re.search(
        r"\b(?:coverage_count|coverage_ratio|missing_count|"
        r"non_null_count|document_count|doc_count)\s*=",
        surface,
        re.IGNORECASE,
    ) is None


def _metadata_fields_asserted_singleton(
    claim_text: str,
    fields: Iterable[str],
) -> List[str]:
    """Limit singleton checks to the clause that makes the singleton claim."""

    result: List[str] = []
    for sentence in re.split(r"(?<=[.!?;])\s+", str(claim_text or "")):
        clauses = re.split(
            r"\s+(?:während|waehrend|hingegen|jedoch|aber)\s+",
            sentence,
            flags=re.IGNORECASE,
        )
        for clause in clauses:
            if not _METADATA_SINGLETON_CLAIM_PATTERN.search(clause):
                continue
            result.extend(_metadata_fields_mentioned(clause, fields))
    return list(dict.fromkeys(result))


def _followup_reasks_complete_metadata_inventory(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _followup_changes_analysis_scope(claim_text):
        return False
    if not _FOLLOWUP_COMPLETE_METADATA_INVENTORY_PATTERN.search(claim_text or ""):
        return False
    return any(
        fact.exactness == "exact"
        and fact.id.endswith("_metadata_available_fields")
        and any(
            str(quote or "").startswith("available_fields=")
            for quote in fact.grounding_quotes
        )
        for fact in facts
    )


def _followup_reasks_settled_metadata_usability(
    claim_text: str,
    facts: Sequence[ObservedFact],
) -> bool:
    if _followup_changes_analysis_scope(claim_text):
        return False
    if not _FOLLOWUP_SETTLED_METADATA_USABILITY_PATTERN.search(claim_text or ""):
        return False
    return bool(_metadata_value_counts(facts)) and any(
        fact.exactness == "exact"
        and fact.id.endswith("_metadata_available_fields")
        for fact in facts
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
def _vae_rule_negative_or_unknown_limitation_4(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6251-6263)."""
    if "_METADATA_HOMOGENEITY_PATTERN" in _vae_ctx:
        _METADATA_HOMOGENEITY_PATTERN = _vae_ctx["_METADATA_HOMOGENEITY_PATTERN"]
    if "_METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN" in _vae_ctx:
        _METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN = _vae_ctx["_METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN"]
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
        _METADATA_HOMOGENEITY_PATTERN.search(claim.text)
        and any(fact.fact_kind == "metadata" for fact in facts)
        and not negative_or_unknown_limitation
        and not _METADATA_VISIBLE_VALUE_QUALIFIER_PATTERN.search(
            claim.text
        )
    ):
        claim_reasons.append(
            "Einwertige Metadatenwerte belegen ohne Feldabdeckung nur "
            "einen sichtbaren distinkten Wert, keine dokumentweite "
            "Homogenität."
        )
    _vae_l = locals()
    for _vae_n in ("fact",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_negative_or_unknown_limitation_5(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6828-6847)."""
    if "_METADATA_SINGLETON_CLAIM_PATTERN" in _vae_ctx:
        _METADATA_SINGLETON_CLAIM_PATTERN = _vae_ctx["_METADATA_SINGLETON_CLAIM_PATTERN"]
    if "_metadata_fields_asserted_singleton" in _vae_ctx:
        _metadata_fields_asserted_singleton = _vae_ctx["_metadata_fields_asserted_singleton"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "contradicted_fields" in _vae_ctx:
        contradicted_fields = _vae_ctx["contradicted_fields"]
    if "field_name" in _vae_ctx:
        field_name = _vae_ctx["field_name"]
    if "mentioned_fields" in _vae_ctx:
        mentioned_fields = _vae_ctx["mentioned_fields"]
    if "metadata_value_counts" in _vae_ctx:
        metadata_value_counts = _vae_ctx["metadata_value_counts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if (
        _METADATA_SINGLETON_CLAIM_PATTERN.search(claim.text)
        and not negative_or_unknown_limitation
    ):
        mentioned_fields = _metadata_fields_asserted_singleton(
            claim.text,
            metadata_value_counts,
        )
        contradicted_fields = [
            field_name
            for field_name in mentioned_fields
            if metadata_value_counts[field_name] != 1
        ]
        if contradicted_fields:
            claim_reasons.append(
                "Der Claim bezeichnet Metadatenfelder als einwertig, obwohl "
                "die Evidenz mehrere Werte ausweist: "
                + ", ".join(contradicted_fields[:4])
                + "."
            )
    _vae_l = locals()
    for _vae_n in ("contradicted_fields", "field_name", "mentioned_fields"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_negative_or_unknown_limitation_6(_vae_ctx):
    """Verbatim cascade block from validate_answer_envelope (step-3 input lines 6848-6864)."""
    if "_METADATA_UNIVERSAL_HOMOGENEITY_PATTERN" in _vae_ctx:
        _METADATA_UNIVERSAL_HOMOGENEITY_PATTERN = _vae_ctx["_METADATA_UNIVERSAL_HOMOGENEITY_PATTERN"]
    if "claim" in _vae_ctx:
        claim = _vae_ctx["claim"]
    if "claim_reasons" in _vae_ctx:
        claim_reasons = _vae_ctx["claim_reasons"]
    if "count" in _vae_ctx:
        count = _vae_ctx["count"]
    if "field_name" in _vae_ctx:
        field_name = _vae_ctx["field_name"]
    if "metadata_value_counts" in _vae_ctx:
        metadata_value_counts = _vae_ctx["metadata_value_counts"]
    if "negative_or_unknown_limitation" in _vae_ctx:
        negative_or_unknown_limitation = _vae_ctx["negative_or_unknown_limitation"]
    if "non_singleton_fields" in _vae_ctx:
        non_singleton_fields = _vae_ctx["non_singleton_fields"]
    if (
        _METADATA_UNIVERSAL_HOMOGENEITY_PATTERN.search(claim.text)
        and not negative_or_unknown_limitation
    ):
        non_singleton_fields = [
            field_name
            for field_name, count in metadata_value_counts.items()
            if count != 1
        ]
        if non_singleton_fields:
            claim_reasons.append(
                "Der Claim bezeichnet alle sichtbaren Metadatenfelder als "
                "homogen, obwohl die Evidenz abweichende Kardinalitäten "
                "ausweist: "
                + ", ".join(non_singleton_fields[:6])
                + "."
            )
    _vae_l = locals()
    for _vae_n in ("count", "field_name", "non_singleton_fields"):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]


def _vae_rule_metadata_values_are_falsely_absent(_vae_ctx):
    """H6 (B4): harte Regel gegen faelschlich behauptete Metadaten-Leere.

    Klasse (d) der Severity-Politik: direkter, exakt gepruefter Widerspruch
    zur Evidenz. Feuert nur, wenn der Claim ein Metadatenfeld eindeutig als
    leer/wertlos bezeichnet, waehrend ein value_count-Fact desselben Turns
    fuer genau dieses Feld count > 0 ausweist.

    Neue Regel (kein Legacy-Seam): der Helper wird defensiv aus dem Kontext
    gelesen und faellt auf das Modul-Global zurueck, weil die Facade ihn
    nicht in die Kontext-Globals seedet (sonst UnboundLocalError).
    """
    helper = _vae_ctx.get(
        "_metadata_values_falsely_absent_fields",
        _metadata_values_falsely_absent_fields,
    )
    claim = _vae_ctx["claim"]
    claim_reasons = _vae_ctx["claim_reasons"]
    metadata_value_counts = _vae_ctx.get("metadata_value_counts") or {}
    falsely_absent_fields = helper(
        claim.text,
        metadata_value_counts,
    )
    if falsely_absent_fields:
        claim_reasons.append(
            "Die Antwort bezeichnet Metadatenfelder als leer oder wertlos, "
            "obwohl die Evidenz belegte Werte ausweist: "
            + ", ".join(
                f"{field_name} ({metadata_value_counts[field_name]} Werte)"
                for field_name in falsely_absent_fields[:4]
            )
            + "."
        )
    _vae_l = locals()
    for _vae_n in ("falsely_absent_fields",):
        if _vae_n in _vae_l:
            _vae_ctx[_vae_n] = _vae_l[_vae_n]
