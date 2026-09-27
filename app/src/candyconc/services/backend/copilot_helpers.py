"""Copilot request-limit helpers and LLM error classification.

Read environment overrides before configuration at call time. Keep these
helpers independent of server and route imports so server-owned callers
can share them without an import cycle."""

import os
from typing import Any

from fastapi import HTTPException

from candyconc.config import get as get_config


# --------------------------------------------------------------------------- #
# Copilot abuse ceilings
#
# A client-supplied ``max_steps`` (or a missing time budget) lets a single chat
# turn run the ReAct loop unboundedly, pinning the LLM + tool pool. The server
# therefore clamps both, regardless of what the client requests.
# --------------------------------------------------------------------------- #
# The ceiling lies ABOVE the recipe round limit, never below it. The recipe
# round limit (max_tool_runden) is the analytical bound, max_steps the abuse
# ceiling above it. Recipes allow up to 200 rounds. A lower ceiling cuts off
# models that make one call per round (for example on matrix questions),
# each time without a draft, while models that bundle 20 to 40 calls per
# round never reach it. 240 lies above the recipe limit and above the 223
# tool calls of the largest measured turn: a model with one call per round
# may do the same work as a bundling one. The compaction budget follows the
# context window and does not depend on this number.
_COPILOT_MAX_STEPS_HARD_DEFAULT = 240
# The time budget is a failsafe, not a schedule. With 120 s, nine of twelve
# measured turns on a corpus of 142 million tokens hit the backstop exactly,
# and not one of them sent a preliminary answer. Waiting time is addressed by
# transparency in the SSE stream, not by a shorter cut.
_COPILOT_MAX_TIME_SEC_DEFAULT = 8_000_000.0


def _copilot_max_steps_ceiling() -> int:
    # os.environ first (matches _heavy_scan_worker_count and friends), since
    # these runtime knobs are not AppConfig model fields and config.get does not
    # fall through to the environment for non-model keys.
    raw = os.environ.get("CANDYCONC_MAX_COPILOT_STEPS") or get_config(
        "CANDYCONC_MAX_COPILOT_STEPS", str(_COPILOT_MAX_STEPS_HARD_DEFAULT)
    )
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return _COPILOT_MAX_STEPS_HARD_DEFAULT
    return max(1, value)


def _copilot_max_time_sec() -> float | None:
    """Return an explicit positive turn budget, or None for an unlimited turn.

None is understood by the budget helpers as unlimited. A configured
positive value also enables the answer-switch, retry, verifier and final
reserve calculations that depend on that budget."""
    raw = os.environ.get("CANDYCONC_COPILOT_MAX_TIME_SEC") or get_config(
        "CANDYCONC_COPILOT_MAX_TIME_SEC", ""
    )
    text = str(raw).strip().lower()
    if not text or text in {"kein", "keins", "aus", "none", "off"}:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# Grace margin (seconds) the server-side wall-clock backstop adds ABOVE the
# cooperative ``max_time`` passed to ``orch.run``. The orchestrator's cooperative
# timeout (orchestrator.py run loop) is the primary control: it stops the ReAct
# loop at a step boundary and returns a grounded partial answer at ~max_time.
# The server backstop (asyncio.wait_for / stream_deadline) is the secondary
# control for the case where a single step (e.g. a wedged LLM/tool call) blocks
# past the cooperative check. Setting the backstop a few seconds ABOVE max_time
# lets the cooperative path win the race in the common case (returning a useful
# 200 partial) and only fires the hard 504 when cooperation genuinely failed.
_COPILOT_BACKSTOP_GRACE_SEC_DEFAULT = 15.0


def _copilot_backstop_grace_sec() -> float:
    raw = os.environ.get("CANDYCONC_COPILOT_BACKSTOP_GRACE_SEC") or get_config(
        "CANDYCONC_COPILOT_BACKSTOP_GRACE_SEC",
        str(_COPILOT_BACKSTOP_GRACE_SEC_DEFAULT),
    )
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return _COPILOT_BACKSTOP_GRACE_SEC_DEFAULT
    return value if value >= 0 else _COPILOT_BACKSTOP_GRACE_SEC_DEFAULT


def _clamp_copilot_max_steps(requested: Any) -> int:
    """Clamp a client ``max_steps`` into ``[1, CANDYCONC_MAX_COPILOT_STEPS]``."""
    try:
        req = int(requested)
    except (TypeError, ValueError):
        req = 10
    return max(1, min(req, _copilot_max_steps_ceiling()))


# Copilot payload abuse ceilings (DoS finding B). Unbounded question/history is
# an LLM-cost and memory amplification vector: every turn re-sends the whole
# history to the model. These cap the per-turn payload BEFORE the orchestrator
# runs. Overridable via env so a research deployment can tune them.
_COPILOT_MAX_QUESTION_CHARS_DEFAULT = 8_000
_COPILOT_MAX_MESSAGES_DEFAULT = 50
_COPILOT_MAX_HISTORY_CHARS_DEFAULT = 64_000


def _copilot_payload_ceiling(env_key: str, default: int) -> int:
    raw = os.environ.get(env_key) or get_config(env_key, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _enforce_copilot_payload_caps(messages: list, question: str) -> None:
    """Reject oversized chat payloads with HTTP 413 (DoS finding B).

    ``messages`` is the full client-supplied list (history + current turn);
    ``question`` is the already-extracted latest user content. Raises
    HTTPException(413) when the message count, the latest question length, or the
    cumulative history size exceeds the configured ceiling — bounding both
    server memory and downstream LLM token cost per turn.
    """
    max_messages = _copilot_payload_ceiling(
        "CANDYCONC_COPILOT_MAX_MESSAGES", _COPILOT_MAX_MESSAGES_DEFAULT
    )
    if len(messages) > max_messages:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Nachrichten ({len(messages)} > {max_messages})",
        )
    max_question = _copilot_payload_ceiling(
        "CANDYCONC_COPILOT_MAX_QUESTION_CHARS", _COPILOT_MAX_QUESTION_CHARS_DEFAULT
    )
    if len(question) > max_question:
        raise HTTPException(
            status_code=413,
            detail=f"Frage zu lang ({len(question)} > {max_question} Zeichen)",
        )
    max_history = _copilot_payload_ceiling(
        "CANDYCONC_COPILOT_MAX_HISTORY_CHARS", _COPILOT_MAX_HISTORY_CHARS_DEFAULT
    )
    total_chars = 0
    for msg in messages:
        if isinstance(msg, dict):
            total_chars += len(str(msg.get("content", "")))
        if total_chars > max_history:
            raise HTTPException(
                status_code=413,
                detail=f"Chatverlauf zu gross (> {max_history} Zeichen)",
            )
