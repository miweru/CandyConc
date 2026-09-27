# -*- coding: utf-8 -*-
"""Remove internal evidence IDs from a finished answer.

Part of the final polish (``recipe_runtime.final_answer_polish``). Bare
evidence and fact IDs (``E_<tool>_<n>``, ``ev3``) never stay visible, the
sentence around them stays. ``[[beleg:ID]]`` chips are server anchors of the
interpretation path and keep their ID.

Only the whitespace a removed ID leaves behind is folded. The previous
version dropped every space before ``,.;:!?`` outside quotations, also when
no ID had been removed. In the English probe of 2026-09-27 (runs b1, b2, c2)
that turned "log_ratio .85 [CI .68–1.03]" into "log_ratio.85 [CI.68–1.03]"
and "expected .64" into "expected.64". Text without an ID keeps its spacing,
so quotations stay byte-identical to their concordance line (the index is
tokenised, most lines carry a space before ``,`` and ``.``).
"""

from __future__ import annotations

import re

_INTERNAL_ID_TOKEN_PATTERN = re.compile(
    # The first lookbehind spares [[beleg:ID]] chips: server anchors of the
    # interpretation path, not leaked model IDs.
    r"(?<!\[\[beleg:)(?<![\wÄÖÜäöüß])(?:ev\d+|E_[A-Za-z][A-Za-z0-9_]*_\d+[A-Za-z_]*)"
    r"(?![\wÄÖÜäöüß])"
)
_PARENTHESIZED_ID_PATTERN = re.compile(
    r"\(\s*(?:ev\d+|E_[A-Za-z][A-Za-z0-9_]*_\d+[A-Za-z_]*)"
    r"(?:\s*,\s*(?:ev\d+|E_[A-Za-z][A-Za-z0-9_]*_\d+[A-Za-z_]*))*\s*\)"
)

#: Marks the place of a removed ID. Only its neighbourhood is tidied, empty
#: brackets elsewhere (``dummy()``) are text and stay.
_ID_SENTINEL = "\x00"


def scrub_internal_ids(text: str) -> str:
    """``text`` without bare internal IDs, whitespace folded only where one stood."""
    text = _PARENTHESIZED_ID_PATTERN.sub(_ID_SENTINEL, text)
    text = _INTERNAL_ID_TOKEN_PATTERN.sub(_ID_SENTINEL, text)
    if _ID_SENTINEL not in text:
        return text
    # A separator next to the ID falls with it ("(, Zeile 3)" was measured
    # before), the other text in the bracket stays. The sentinel stays in
    # place so that the folding below knows where the ID was.
    text = re.sub(
        r"\s*[,;]?\s*" + _ID_SENTINEL + r"\s*[,;]?\s*",
        lambda m: (" " if m.group(0).startswith(" ") else "") + _ID_SENTINEL,
        text,
    )
    # A bracket that held only the ID falls completely.
    text = re.sub(r"\(\s*" + _ID_SENTINEL + r"?\s*\)(?=\s*[.,;:!?]|\s*$|\s)", _ID_SENTINEL, text)
    # Space before a punctuation mark right after the removed ID, and double
    # space around it.
    text = re.sub(r"[ \t]*" + _ID_SENTINEL + r"+[ \t]*(?=[,.;:!?])", "", text)
    text = re.sub(r"[ \t]+" + _ID_SENTINEL + r"+[ \t]+", " ", text)
    return text.replace(_ID_SENTINEL, "")
