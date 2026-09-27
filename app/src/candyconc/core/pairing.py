"""Roles of the documents in a paired corpus.

A paired import groups several versions of one text. One role is the anchor,
the version the others are compared with. The builder records the side of
each document in ``text_type``: ``anchor`` for the anchor, ``version`` for
every other version. The role itself, taken from the data, stays in
``pair_role``.

Indexes built before builder revision 2 used ``human`` and ``ai`` for these
two sides, whatever the texts were. The paired human/AI research layout
(``target_text``/``input_text`` rows) still records ``human`` and ``ai``,
because there the model column says so. Readers therefore accept both pairs
of values.
"""

from __future__ import annotations

from typing import Any

ANCHOR = "anchor"
VERSION = "version"
#: ``text_type`` of a document of an unpaired corpus. It is neither side of a pair.
STANDALONE = "standalone"

ANCHOR_VALUES = frozenset({ANCHOR, "human"})
VERSION_VALUES = frozenset({VERSION, "ai"})


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def is_anchor(text_type: Any) -> bool:
    """True for the ``text_type`` of an anchor document (``anchor`` or ``human``)."""
    return _norm(text_type) in ANCHOR_VALUES


def is_version(text_type: Any) -> bool:
    """True for the ``text_type`` of a compared version (``version`` or ``ai``)."""
    return _norm(text_type) in VERSION_VALUES
