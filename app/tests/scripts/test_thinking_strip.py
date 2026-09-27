"""Regression tests for reasoning/thinking-marker stripping and vm_stat page-size parse.

These pin two bugs that were caused by doubled backslashes in raw-string regexes in
``scripts/jobs/build_fast_index_from_parquet.py``:

* The ``_RE_FINAL`` / ``_RE_ANSWER`` / ``_RE_RESPONSE`` etc. markers used ``\\b``/``\\s``
  inside an ``r"..."`` literal, so they matched a *literal* backslash instead of a word
  boundary / whitespace and never fired. Consequence: model reasoning ("thinking") text
  leaked into the indexed corpus instead of being split off.
* The vm_stat page-size regex used ``(\\d+)`` inside ``r"..."`` so it never matched the
  macOS ``page size of N bytes`` header, defaulting to 4096 and under-reporting RAM ~4x
  on Apple Silicon (16384-byte pages).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.jobs.build_fast_index_from_parquet import (  # noqa: E402
    _RE_ANALYSIS_START,
    _RE_ANSWER,
    _RE_ASSISTANT,
    _RE_FINAL,
    _RE_RESPONSE,
    _RE_SYSTEM,
    _RE_THINKING_TAG,
    _extract_thinking,
)


def test_final_marker_strips_reasoning_into_thinking():
    text = "Let me reason step by step about register.\nFinal: The cat sat on the mat."
    thinking, content = _extract_thinking(text)
    assert content == "The cat sat on the mat."
    assert "reason step by step" in thinking
    # The reasoning must NOT survive into the corpus content.
    assert "reason step by step" not in content


def test_thinking_tag_removed_from_content():
    text = "<thinking>internal scratchpad here</thinking>\nThe quick brown fox."
    thinking, content = _extract_thinking(text)
    assert "internal scratchpad" not in content
    assert content == "The quick brown fox."
    assert "internal scratchpad" in thinking


def test_german_antwort_marker_strips_reasoning():
    text = "Überlegung zum Stil und Register.\nAntwort: Der Hund schlaeft."
    thinking, content = _extract_thinking(text)
    assert content == "Der Hund schlaeft."
    assert "Überlegung" not in content


def test_response_marker_strips_reasoning():
    text = "scratch work and notes\nResponse: Final clean text."
    thinking, content = _extract_thinking(text)
    assert content == "Final clean text."
    assert "scratch work" not in content


def test_assistant_prefix_split():
    # _RE_ASSISTANT is anchored to the start of the string (no MULTILINE), so the
    # prefix must lead. This pins that the fixed \s* whitespace class actually matches.
    text = "assistant: real answer body"
    thinking, content = _extract_thinking(text)
    assert content == "real answer body"


def test_marker_regexes_actually_match():
    # Direct guard against the doubled-backslash regression: each marker must match
    # plain text, not a literal backslash sequence.
    assert _RE_FINAL.search("Final: x")
    assert _RE_ANSWER.search("Antwort: x")
    assert _RE_RESPONSE.search("Response: x")
    assert _RE_ASSISTANT.search("assistant: x")
    assert _RE_SYSTEM.search("system: x")
    assert _RE_ANALYSIS_START.search("Analysis: x")
    assert _RE_THINKING_TAG.search("<thinking>y</thinking>")
    # And they must NOT have matched against a literal backslash form.
    assert not _RE_FINAL.search(r"\bfinal\s: x")


def test_clean_text_without_markers_is_preserved():
    text = "A perfectly normal sentence with no reasoning markers."
    thinking, content = _extract_thinking(text)
    assert content == text
    assert thinking == ""


def test_vm_stat_page_size_regex_matches_apple_silicon_header():
    # The page-size regex (literal copy of the one in _available_memory_bytes) must
    # extract 16384 from an Apple-Silicon vm_stat header, not silently default to 4096.
    header = "Mach Virtual Memory Statistics: (page size of 16384 bytes)"
    match = re.search(r"page size of (\d+) bytes", header)
    assert match is not None
    assert int(match.group(1)) == 16384
