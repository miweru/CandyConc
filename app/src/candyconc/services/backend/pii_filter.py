from __future__ import annotations

import re
from typing import TYPE_CHECKING
from candyconc.config import get as get_config
from candyconc.i18n import lt

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from candyconc.core.corpus_index import CorpusIndex

PII_LABELS = {
    "PERSON",
    "ORG",
    "GPE",
    "LOC",
    "DATE",
    "TIME",
    "NORP",
    "FAC",
    "MONEY",
    "CARDINAL",
    "ORDINAL",
    "LANGUAGE",
}

_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
# A phone number is recognised by the form that marks it as one: a country
# code (+49, +1), a trunk prefix 0 before the area code (030, 0151), an area
# code in parentheses, or the North American 3-3-4 grouping with one
# separator. Plain digit groups are years, date ranges, counts with thousands
# separators or the numbers of a query and stay as written. At least seven
# digits in total, like the shortest landline number with its area code.
_PHONE_RE = re.compile(
    r"(?<![\w+])(?:"
    r"\+\d{1,3}(?:[ .\-/]?(?:\(\d{1,5}\)|\d{1,5})){1,6}"
    r"|\((?:0\d{1,4}|\d{3})\)[ .\-/]?\d{2,}(?:[ .\-/]?\d{2,}){0,3}"
    r"|0\d{2,5}(?:[ .\-/]\d{2,}){1,4}"
    r"|\d{3}([-.])\d{3}\1\d{4}"
    r")(?!\w)"
)
_PHONE_MIN_DIGITS = 7


def _mask_phone(match: "re.Match[str]") -> str:
    text = match.group(0)
    if sum(ch.isdigit() for ch in text) < _PHONE_MIN_DIGITS:
        return text
    return "<PHONE>"


def _pii_mask_enabled() -> bool:
    raw = get_config("CANDYCONC_ENABLE_PII_MASK", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _copilot_pii_mask_enabled() -> bool:
    """Keep outbound Copilot redaction independent from corpus ENT coverage."""
    raw = get_config("CANDYCONC_ENABLE_COPILOT_PII_MASK", "1")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def mask_pii(
    text: str,
    *,
    start_pos: int | None = None,
    index: "CorpusIndex | None" = None,
    tokens: list[str] | None = None,
) -> str:
    """Mask PII in ``text``.

    When ``index`` and ``start_pos`` are provided, the function uses
    precomputed entity tags from ``index`` starting at ``start_pos``.
    Ohne Indexdaten ist der PII Filter nicht verfügbar.
    """

    if not text:
        return text

    if not _pii_mask_enabled():
        return text

    if index is None or start_pos is None:
        raise RuntimeError(lt("PII Filter erfordert Index und start_pos", "The PII filter needs an index and start_pos"))

    if tokens is None:
        tokens = text.split()
    else:
        tokens = [t for t in tokens if t]
    fast = index.fast_index
    ent_lex = fast.lexicons.ent
    if ent_lex is None:
        raise RuntimeError(
            lt("ENT Lexikon fehlt. Bitte Index neu bauen.", "Named entity lexicon is missing. Rebuild the index.")
        )
    ent_ids = fast.token_store.ent_ids
    if ent_ids is None:
        raise RuntimeError(
            lt("ENT IDs fehlen. Bitte Index neu bauen.", "Named entity IDs are missing. Rebuild the index.")
        )
    end_pos = start_pos + len(tokens)
    if not (0 <= start_pos < fast.token_store.token_count and end_pos <= fast.token_store.token_count):
        raise RuntimeError(
            lt("PII Masking Positionen liegen ausserhalb des Index", "PII masking positions are outside the index")
        )
    slice_ids = ent_ids[start_pos:end_pos]
    if len(slice_ids) != len(tokens):
        raise RuntimeError(lt("PII Masking Alignment fehlerhaft", "PII masking alignment is inconsistent"))
    return " ".join(
        "<PII>" if ent_lex.get_string(int(ent_id)) in PII_LABELS and token else token
        for token, ent_id in zip(tokens, slice_ids)
    )


def mask_free_text_pii(text: str) -> str:
    """Mask obvious free-text PII before text leaves the local process."""
    if not text or not _copilot_pii_mask_enabled():
        return text
    masked = _EMAIL_RE.sub("<EMAIL>", text)
    masked = _IBAN_RE.sub("<IBAN>", masked)
    return _PHONE_RE.sub(_mask_phone, masked)
