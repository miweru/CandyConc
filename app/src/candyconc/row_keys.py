from __future__ import annotations

from typing import Mapping, Any


def text_id(row: Mapping[str, Any]) -> str:
    """Return a stable text-based identifier for a KWIC row."""
    left = str(row.get("left", ""))
    kw = str(row.get("kw", ""))
    right = str(row.get("right", ""))
    return f"text:{left}|{kw}|{right}"


def row_id(row: Mapping[str, Any]) -> str:
    """Return a stable identifier for a KWIC row.

    Prefers file+pos (or file+line_id) when available to avoid collisions.
    Falls back to a text-based identifier when no stable positional info exists.
    """
    file = row.get("file")
    pos = row.get("pos")
    if file is not None and pos is not None:
        try:
            pos_val = int(pos)
        except Exception:
            pos_val = None
        if pos_val is not None:
            return f"file:{file}|pos:{pos_val}"
    line_id = row.get("line_id")
    if file is not None and line_id is not None:
        try:
            line_val = int(line_id)
        except Exception:
            line_val = None
        if line_val is not None:
            return f"file:{file}|line:{line_val}"
    return text_id(row)
