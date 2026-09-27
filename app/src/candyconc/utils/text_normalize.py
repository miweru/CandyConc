from __future__ import annotations

import re
import unicodedata

_RE_HSPACE = re.compile(r"[ \t\f\v]+")
_RE_NL = re.compile(r"\n{3,}")
_LLM_PROTOCOL_TAIL = re.compile(
    r"(?:<assistant|<\|assistant\|>|<\|start\|>\s*assistant)\s*"
    r"<\|channel\|>\s*final\s*<\|message\|>",
    re.IGNORECASE,
)
_LLM_PROTOCOL_LEAD = re.compile(r"</s>|<end>", re.IGNORECASE)


def normalize_text_basic(text: str) -> str:
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf"):
            if ch == "\n":
                out.append("\n")
            elif ch.isspace():
                out.append(" ")
            continue
        if ch.isspace():
            if ch == "\n":
                out.append("\n")
            else:
                out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    text = _RE_HSPACE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _RE_NL.sub("\n\n", text)
    return text.strip()


def normalize_index_display_text(value: object) -> str:
    """Render index-only linebreak markers for user-facing text fields."""
    text = "" if value is None else str(value)
    if "|LBR|" not in text:
        return text
    text = re.sub(r"[ \t\f\v]*\|LBR\|[ \t\f\v]*", "\n", text)
    return _RE_NL.sub("\n\n", text).strip(" \t")


def _markdown_code_ranges(text: str) -> list[tuple[int, int]]:
    """Return fenced and inline code ranges that must remain literal."""

    ranges: list[tuple[int, int]] = []
    offset = 0
    fence_start: int | None = None
    fence_char = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if marker is not None:
            token = marker.group(1)
            if fence_start is None:
                fence_start = offset + marker.start(1)
                fence_char = token[0]
                fence_length = len(token)
            elif token[0] == fence_char and len(token) >= fence_length:
                ranges.append((fence_start, offset + len(line)))
                fence_start = None
                fence_char = ""
                fence_length = 0
        if fence_start is None:
            line_start = offset
            for match in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", line):
                ranges.append(
                    (line_start + match.start(), line_start + match.end())
                )
        offset += len(line)
    if fence_start is not None:
        ranges.append((fence_start, len(text)))
    return ranges


def _inside_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)


def _is_vrt_sentence_close(text: str, position: int) -> bool:
    """Recognise a literal ``<s>... </s>`` pair before a leak signature."""

    opening = text.rfind("<s>", max(0, position - 4_000), position)
    previous_close = text.rfind("</s>", max(0, position - 4_000), position)
    return opening > previous_close


def _trim_unmatched_json_closer_suffix(text: str) -> str:
    """Remove schema closers only when they are provably unpaired."""

    trailing = re.search(r"(?:\s*[}\]])+\s*$", text)
    if trailing is None:
        return text.rstrip()
    stack: list[str] = []
    unmatched: set[int] = set()
    quote = ""
    escaped = False
    pairs = {"}": "{", "]": "["}
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char == '"':
            quote = char
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
            else:
                unmatched.add(index)
    closer_positions = [
        index
        for index in range(trailing.start(), len(text))
        if text[index] in "}]"
    ]
    if closer_positions and all(index in unmatched for index in closer_positions):
        return text[: trailing.start()].rstrip()
    return text.rstrip()


def strip_llm_protocol_tail(text: str) -> str:
    """Remove a confirmed terminal provider spill, preserving literal markup."""

    if not text:
        return text
    code_ranges = _markdown_code_ranges(text)
    matches = [
        match
        for match in _LLM_PROTOCOL_TAIL.finditer(text)
        if not _inside_ranges(match.start(), code_ranges)
    ]
    if not matches:
        return text
    tail = matches[-1]
    cut_at = tail.start()
    lead_candidates = [
        match
        for match in _LLM_PROTOCOL_LEAD.finditer(
            text,
            max(0, tail.start() - 2_000),
            tail.start(),
        )
        if not _inside_ranges(match.start(), code_ranges)
        and not (
            match.group(0).casefold() == "</s>"
            and _is_vrt_sentence_close(text, match.start())
        )
    ]
    if lead_candidates:
        cut_at = lead_candidates[0].start()
    return _trim_unmatched_json_closer_suffix(text[:cut_at])
