"""KWIC rendering helpers (Master-Plan Welle 1).

The single coherent home for KWIC-row operations that the divergent render paths
(server._render_*, query_runtime._kwic_rows_for_positions_fast) will converge on.
For now it owns the **sort** primitive — the #1 product gap — as a pure post-fetch
transform on already-rendered rows, so it composes with every render path without a
risky big-bang renderer rewrite.

Sort vocabulary follows the AntConc/CWB convention:
    1L 2L 3L   — 1st/2nd/3rd token to the LEFT of the node (1L = immediately left)
    node       — the keyword/match itself
    1R 2R 3R   — 1st/2nd/3rd token to the RIGHT of the node
    meta:FIELD — a document-metadata field

German collation: PyICU (DIN 5007-1) is used when available, otherwise a
casefold + umlaut-folding fallback (ä→a, ö→o, ü→u, ß→ss) that approximates
dictionary order. A stable secondary key on the hit position keeps the order
deterministic.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from candyconc.core.source_spacing import apply_source_spacing_rows, side_tokens
from candyconc.i18n import lt
from candyconc.utils.text_normalize import normalize_index_display_text

_LEFT_FIELDS = {"1l": 1, "2l": 2, "3l": 3}
_RIGHT_FIELDS = {"1r": 1, "2r": 2, "3r": 3}
SORT_FIELDS = frozenset({"1l", "2l", "3l", "node", "1r", "2r", "3r"})
_LINEBREAK_MARKER = "|LBR|"
_DISPLAY_TEXT_FIELDS = ("left", "kw", "right", "node", "text", "snippet")

# Optional ICU collator (DIN 5007-1). Absent in this env -> casefold fallback.
try:  # pragma: no cover - depends on optional dependency
    import icu as _icu  # type: ignore

    _COLLATOR = _icu.Collator.createInstance(_icu.Locale("de_DE"))
except Exception:  # pragma: no cover
    _COLLATOR = None

_UMLAUT_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "Ä": "a", "Ö": "o", "Ü": "u", "ß": "ss"})


def _fold(text: str) -> str:
    """Casefold + umlaut-fold a token for DIN-5007-1-approximate ordering."""
    return text.casefold().translate(_UMLAUT_FOLD)


def normalise_kwic_row_display(row: Any) -> Any:
    """Normalise visible KWIC fields while preserving all non-display payload data."""
    if not isinstance(row, dict):
        return row
    for field in _DISPLAY_TEXT_FIELDS:
        value = row.get(field)
        if isinstance(value, str) and _LINEBREAK_MARKER in value:
            row[field] = normalize_index_display_text(value)
    return row


def display_rows(rows: List[Any], idx: Any) -> List[Any]:
    """KWIC rows as they leave the server: original spacing, then display text.

    The spacing comes from ``whitespace_after.bin`` of ``idx`` and is applied
    before ``normalise_kwic_row_display``, which then finds no ``|LBR|``
    marker left in a spaced row. Rows of an index without the file keep the
    legacy space-joined text.
    """
    apply_source_spacing_rows(rows, idx)
    return [normalise_kwic_row_display(row) for row in rows]


def parse_sort(sort_by: str | None) -> Optional[Tuple[str, str]]:
    """Parse a sort spec into (field, arg). Returns None for no/empty sort.

    field ∈ SORT_FIELDS ∪ {"meta"}; arg is the metadata field name for meta:FIELD,
    else "". Raises ValueError on an unknown field so the endpoint can 400.
    """
    if not sort_by:
        return None
    spec = sort_by.strip().lower()
    if not spec or spec == "position":
        return None
    if spec.startswith("meta:"):
        field = sort_by.strip()[5:]
        if not field:
            raise ValueError(lt("meta:-Sortierung braucht einen Feldnamen", "meta: sorting needs a field name"))
        return ("meta", field)
    if spec in SORT_FIELDS:
        return (spec, "")
    raise ValueError(
        lt(
            "Unbekanntes Sortierfeld {field!r}. Erlaubt: 1L 2L 3L node 1R 2R 3R meta:FELD",
            "Unknown sort field {field!r}. Allowed: 1L 2L 3L node 1R 2R 3R meta:FIELD",
        ).format(field=sort_by)
    )


def _row_str(row: Any, key: str, default: str = "") -> str:
    if isinstance(row, dict):
        v = row.get(key, default)
        return v if isinstance(v, str) else (str(v) if v is not None else default)
    return default


def _row_meta(row: Any, field: str) -> str:
    if not isinstance(row, dict):
        return ""
    meta = row.get("meta")
    if isinstance(meta, dict) and field in meta:
        v = meta.get(field)
        return str(v) if v is not None else ""
    v = row.get(field)
    return str(v) if v is not None else ""


def _key_func(field: str, arg: str) -> Callable[[Any], str]:
    # Context sort keys address tokens, not whitespace-separated chunks: a row
    # with the original spacing ("Hof!") sorts like its space-joined form
    # ("Hof !"), see core.source_spacing.side_tokens.
    if field == "node":

        def _node(r: Any) -> str:
            if isinstance(r, dict) and "token_starts" in r:
                return _fold(" ".join(side_tokens(r, "kw")))
            return _fold(_row_str(r, "kw"))

        return _node
    if field == "meta":
        return lambda r: _fold(_row_meta(r, arg))
    if field in _LEFT_FIELDS:
        depth = _LEFT_FIELDS[field]

        def _left(r: Any) -> str:
            toks = side_tokens(r, "left")
            return _fold(toks[-depth]) if len(toks) >= depth else ""

        return _left
    depth = _RIGHT_FIELDS[field]

    def _right(r: Any) -> str:
        toks = side_tokens(r, "right")
        return _fold(toks[depth - 1]) if len(toks) >= depth else ""

    return _right


def _pos_of(row: Any) -> int:
    if isinstance(row, dict):
        p = row.get("pos")
        try:
            return int(p)
        except Exception:
            return 0
    return 0


def sort_kwic_rows(
    rows: List[Any],
    sort_by: str | None,
    *,
    sort_dir: str = "asc",
) -> List[Any]:
    """Return ``rows`` sorted by the AntConc-style ``sort_by`` spec.

    Pure and non-mutating: returns a new list (or ``rows`` unchanged when sort is
    None/empty). Secondary key is the hit position for deterministic ties. When the
    ICU collator is present it orders the primary key per DIN 5007-1; otherwise the
    keys are already casefold+umlaut-folded.
    """
    parsed = parse_sort(sort_by)
    if parsed is None:
        return rows
    field, arg = parsed
    keyfn = _key_func(field, arg)
    descending = str(sort_dir).strip().lower() in ("desc", "descending", "-1")

    if _COLLATOR is not None:  # pragma: no cover - optional dep
        import functools

        def _cmp(a: Any, b: Any) -> int:
            ka, kb = keyfn(a), keyfn(b)
            c = _COLLATOR.compare(ka, kb)
            if c == 0:
                c = (_pos_of(a) > _pos_of(b)) - (_pos_of(a) < _pos_of(b))
            return -c if descending else c

        return sorted(rows, key=functools.cmp_to_key(_cmp))

    return sorted(rows, key=lambda r: (keyfn(r), _pos_of(r)), reverse=descending)
