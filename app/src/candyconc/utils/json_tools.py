import json
import logging
import re

LOGGER = logging.getLogger(__name__)


def _balanced_json_slice(text: str) -> str | None:
    """Return the first balanced JSON slice in ``text`` or ``None``.

    The scan takes escaping and quoted strings into account so that braces
    inside strings do not influence the depth counter.
    """

    start = None
    depth = 0
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if start is None:
            if ch not in "[{":
                continue
            start = idx
            depth = 1
            continue
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def extract_json_block(text: str) -> dict | list:
    """Return the first JSON object or array found in ``text``.

    The parser tolerates stray backslashes like ``\\$`` by escaping them before
    decoding. Code fences and leading markup are stripped automatically.
    """

    clean = text.strip()
    # remove code fences
    if clean.startswith("```") and clean.endswith("```"):
        clean = re.sub(r"^```(?:\w+)?\n?|```$", "", clean, flags=re.S)

    block = _balanced_json_slice(clean)
    if block is None:
        raise RuntimeError("Kein JSON Block gefunden")

    # double stray backslashes. ``x`` is not part of the official JSON
    # escapes but is occasionally produced by some models.
    safe = re.sub(r"\\([^\"\\/bfnrtux])", r"\\\\\1", block)
    try:
        return json.loads(safe)
    except Exception as exc:  # pragma: no cover
        LOGGER.exception("JSON decode failed: %s", exc, extra={"raw": block[:500]})
        raise RuntimeError("JSON Block ungültig") from exc
