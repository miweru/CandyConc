from __future__ import annotations

import re

_BAD_PATTERNS = [re.compile(r"</?sys>", re.I), re.compile(r"<<"), re.compile(r"ignore\s+all", re.I)]


def clean_prompt(text: str) -> str:
    """Remove common jailbreak patterns from *text*."""
    cleaned = text
    for pat in _BAD_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    return cleaned
