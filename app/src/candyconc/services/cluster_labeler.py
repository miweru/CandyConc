from __future__ import annotations

import re
from collections import Counter
from typing import List

_LABEL_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_LABEL_STOPWORDS = {
    "der",
    "die",
    "das",
    "und",
    "oder",
    "mit",
    "von",
    "für",
    "the",
    "and",
    "mitte",
}


def _heuristic_label(sample_texts: List[str]) -> str:
    counts: Counter[str] = Counter()
    for text in sample_texts[:5]:
        for token in _LABEL_TOKEN_RE.findall(str(text).casefold()):
            if len(token) <= 2 or token in _LABEL_STOPWORDS:
                continue
            counts[token] += 1
    if not counts:
        raw = str(sample_texts[0]).strip()
        return raw[:40] if raw else ""
    top = [token for token, _ in counts.most_common(3)]
    return " ".join(top).strip()


async def generate_label(sample_texts: List[str]) -> str:
    """Return a short topic label using the LLM."""

    if not sample_texts:
        return ""
    if all(len(_LABEL_TOKEN_RE.findall(str(text))) <= 3 for text in sample_texts[:3]):
        return _heuristic_label(sample_texts)
    prompt = (
        "You are a linguist. Given these concordance snippets, "
        "suggest a 1-3-word topic label.\n"
    )
    for txt in sample_texts[:3]:
        prompt += f"- {txt}\n"
    try:
        from candyconc.services.llm_client import call_llm_async
    except Exception:
        return _heuristic_label(sample_texts)
    try:
        data = await call_llm_async([
            {"role": "user", "content": prompt}], [], user="cluster")
        label = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        label = re.split(r"\r?\n", label)[0].strip()
        return label or _heuristic_label(sample_texts)
    except Exception:
        return _heuristic_label(sample_texts)


__all__ = ["generate_label"]
