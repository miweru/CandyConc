"""Original spacing between tokens, read from ``whitespace_after.bin``.

The side file holds one uint8 flag per token: 1 when a space followed the
token in the imported text (spaCy ``token.whitespace_``). With it, readers
join tokens as written ("soul. No words", "TRUMAN'S ADDRESS"). Without it
(indexes built before builder revision 3, ``--no-capture-whitespace``, VRT
with ``--annotation-mode adopt``) every token is separated by one space, as
before.

The spacing changes only the rendered text. Positions, counts, hit spans and
``match_offsets`` address tokens and stay as they are. A rendered KWIC row
carries ``token_starts``: the start offset (in Unicode code points) of every
token in ``left``, ``kw`` and ``right``, so that readers that address tokens
by index (hit and collocate highlighting, sorting by 1L or 1R) still find
them when a token is attached to its neighbour without a space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np

from candyconc.config import get as get_config
from candyconc.core.index_format import read_count_prefixed_array

WHITESPACE_FILE = "whitespace_after.bin"
TOKEN_STARTS = "token_starts"
LINEBREAK_MARKER = "|LBR|"
_CACHE_ATTR = "_kwic_whitespace_after_cache"
_SIDES = ("left", "kw", "right")


def whitespace_flags(idx: Any) -> np.ndarray | None:
    """The flags of ``idx`` (read once per opened index), or None without the file.

    A file whose length differs from the token count belongs to another build
    and is ignored.
    """
    if idx is None:
        return None
    cached = getattr(idx, _CACHE_ATTR, None)
    if cached is not None:
        return cached[0]
    base = getattr(idx, "path", None)
    arr: np.ndarray | None = None
    if base is not None:
        try:
            arr = read_count_prefixed_array(
                Path(base) / WHITESPACE_FILE, np.uint8, label="whitespace_after", missing_ok=True
            )
        except Exception:
            arr = None
    if arr is not None:
        try:
            token_count = int(idx.fast_index.token_store.token_count)
        except Exception:
            token_count = None
        if token_count is not None and int(arr.size) != token_count:
            arr = None
    try:
        setattr(idx, _CACHE_ATTR, (arr,))
    except Exception:
        pass
    return arr


def pii_masking_enabled() -> bool:
    """Same switch as ``pii_filter._pii_mask_enabled``.

    Masking rebuilds its output with single spaces and may replace one token
    by several, so the flags would no longer line up with the text.
    """
    raw = get_config("CANDYCONC_ENABLE_PII_MASK", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def display_flags(idx: Any) -> np.ndarray | None:
    """Flags for rendering, or None when the file is absent or masking is on."""
    if pii_masking_enabled():
        return None
    return whitespace_flags(idx)


def join_tokens(tokens: list[str], base: int, ws: np.ndarray) -> str:
    """Join contiguous tokens starting at position ``base`` with their spacing."""
    if len(tokens) <= 1:
        return tokens[0] if tokens else ""
    parts: list[str] = []
    last = len(tokens) - 1
    for i, tok in enumerate(tokens):
        parts.append(tok)
        if i < last and ws[base + i]:
            parts.append(" ")
    return "".join(parts)


def join_tokens_with_starts(tokens: list[str], base: int, ws: np.ndarray) -> tuple[str, list[int]]:
    """``join_tokens`` plus the start offset of every token in the result.

    The line break marker ``|LBR|`` of some imported corpora is rendered as a
    line break without surrounding spaces, exactly as
    ``normalize_index_display_text`` would render it, so that the offsets stay
    valid after display normalisation.
    """
    parts: list[str] = []
    starts: list[int] = []
    length = 0
    last = len(tokens) - 1
    for i, tok in enumerate(tokens):
        is_break = tok == LINEBREAK_MARKER
        if is_break:
            if parts and parts[-1] == " ":
                parts.pop()
                length -= 1
            tok = "\n"
        starts.append(length)
        parts.append(tok)
        length += len(tok)
        nxt_break = i < last and tokens[i + 1] == LINEBREAK_MARKER
        if i < last and ws[base + i] and not is_break and not nxt_break:
            parts.append(" ")
            length += 1
    return "".join(parts), starts


def _split(text: str) -> list[str] | None:
    """Tokens of a legacy space-joined field, None if the split is ambiguous."""
    if not text:
        return []
    tokens = text.split(" ")
    if any(tok == "" for tok in tokens):
        # A doubled space: the field does not map one-to-one to tokens.
        return None
    return tokens


def apply_source_spacing(row: Any, ws: np.ndarray) -> Any:
    """Render one KWIC row with the original spacing.

    ``row`` is a dict with ``pos`` (position of the first ``kw`` token) and
    the legacy space-joined ``left``, ``kw`` and ``right``. The row gains
    ``ws_before_kw``, ``ws_after_kw`` and ``token_starts``. A row that already
    carries ``token_starts``, has no position or does not map to a contiguous
    window keeps its text unchanged.
    """
    if not isinstance(row, dict) or TOKEN_STARTS in row:
        return row
    pos = row.get("pos")
    if isinstance(pos, bool) or not isinstance(pos, (int, np.integer)):
        return row
    pos = int(pos)
    left_tokens = _split(str(row.get("left", "") or ""))
    kw_tokens = _split(str(row.get("kw", "") or ""))
    right_tokens = _split(str(row.get("right", "") or ""))
    if left_tokens is None or kw_tokens is None or right_tokens is None or not kw_tokens:
        return row
    start = pos - len(left_tokens)
    after_kw = pos + len(kw_tokens)
    end = after_kw + len(right_tokens)
    if start < 0 or pos < 0 or end > int(ws.size):
        return row
    left, left_starts = join_tokens_with_starts(left_tokens, start, ws)
    kw, kw_starts = join_tokens_with_starts(kw_tokens, pos, ws)
    right, right_starts = join_tokens_with_starts(right_tokens, after_kw, ws)
    row["left"] = left
    row["kw"] = kw
    row["right"] = right
    row["ws_before_kw"] = (
        bool(left_tokens) and bool(ws[pos - 1])
        and left_tokens[-1] != LINEBREAK_MARKER and kw_tokens[0] != LINEBREAK_MARKER
    )
    row["ws_after_kw"] = (
        bool(right_tokens) and bool(ws[after_kw - 1])
        and kw_tokens[-1] != LINEBREAK_MARKER and right_tokens[0] != LINEBREAK_MARKER
    )
    row[TOKEN_STARTS] = {"left": left_starts, "kw": kw_starts, "right": right_starts}
    return row


def apply_source_spacing_rows(rows: Iterable[Any], idx: Any) -> Any:
    """Render every dict row of ``rows`` with the spacing of ``idx`` (in place).

    Returns ``rows``. Tuple rows and rows of an index without the side file
    stay as they are.
    """
    ws = display_flags(idx)
    if ws is None:
        return rows
    for row in rows:
        apply_source_spacing(row, ws)
    return rows


def side_tokens(row: Any, side: str) -> list[str]:
    """The non-blank tokens of one side of a row, in order.

    Uses ``token_starts`` when the row has them, so an attached token ("Hof"
    and "!" in "Hof!") counts as two, like in the legacy space-joined text.
    Line break tokens are skipped, like ``str.split()`` skips them.
    """
    if not isinstance(row, dict):
        return []
    value = row.get(side)
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    starts = (row.get(TOKEN_STARTS) or {}).get(side) if isinstance(row.get(TOKEN_STARTS), dict) else None
    if not isinstance(starts, list) or not starts:
        return text.split()
    tokens: list[str] = []
    bounds = [*starts, len(text)]
    for begin, stop in zip(bounds, bounds[1:]):
        try:
            tok = text[int(begin):int(stop)].rstrip(" ")
        except (TypeError, ValueError):
            return text.split()
        if tok.strip():
            tokens.append(tok)
    return tokens
