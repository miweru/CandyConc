# -*- coding: utf-8 -*-
"""Language of the answer to one Copilot turn (``de`` or ``en``).

The language is decided once at the start of a turn, from the wording of the
question. When the question does not show its language (a single word, a
query in brackets), the interface language decides: first ``locale`` from the
UI context, then the ``Accept-Language`` of the request. German is the last
fallback, because the harness texts were German before English existed.

Every place that writes text for the answer (synthesis instruction, evidence
package labels, appendices, notes, status texts) reads :func:`answer_language`.
It defaults to German, so a code path that runs outside a turn, and every
German turn, produces exactly the text it produced before.

The interface language of a request (``candyconc.i18n.current_language``) is a
different thing: it decides the language of product surfaces such as tool
cards. A German question asked in an English interface gets a German answer.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping, Optional

from candyconc.i18n import LocalizedText, localize
from candyconc.question_language import detect_question_language

LANGUAGES = ("de", "en")
DEFAULT = "de"

_ANSWER_LANGUAGE: ContextVar[str] = ContextVar("candyconc_answer_language", default=DEFAULT)


def normalize(language: Any) -> Optional[str]:
    """``de`` or ``en`` for a language tag such as ``en-US``, else ``None``."""
    text = str(language or "").strip().lower().replace("_", "-")
    primary = text.split("-")[0]
    return primary if primary in LANGUAGES else None


def answer_language() -> str:
    """Language of the answer being written (``de`` outside a turn)."""
    return _ANSWER_LANGUAGE.get()


def is_english() -> bool:
    return _ANSWER_LANGUAGE.get() == "en"


@contextmanager
def answer_language_scope(language: Any) -> Iterator[str]:
    """Write the enclosed code's answer texts in ``language``."""
    token = _ANSWER_LANGUAGE.set(normalize(language) or DEFAULT)
    try:
        yield _ANSWER_LANGUAGE.get()
    finally:
        _ANSWER_LANGUAGE.reset(token)


def enter_answer_language(language: Any) -> None:
    """Set the answer language for the rest of the current context.

    For the coroutine of a turn, which runs in its own asyncio task and thus
    in its own copy of the context. Everywhere else use
    :func:`answer_language_scope`.
    """
    _ANSWER_LANGUAGE.set(normalize(language) or DEFAULT)


def choose(de: str, en: str) -> str:
    """``en`` in an English answer, otherwise ``de`` unchanged."""
    return en if _ANSWER_LANGUAGE.get() == "en" else de


def resolve(value: Any) -> Any:
    """A LocalizedText (also inside dicts and lists) in the answer language."""
    return localize(value, _ANSWER_LANGUAGE.get())


def text_value(value: Any) -> str:
    """``str(value)`` in the answer language (German value for LocalizedText)."""
    if isinstance(value, LocalizedText):
        return value.resolve(_ANSWER_LANGUAGE.get())
    return str(value)


# --------------------------------------------------------------------------- #
# Numbers                                                                      #
# --------------------------------------------------------------------------- #
def format_int(value: int) -> str:
    """``49.536`` in German, ``49,536`` in English."""
    grouped = f"{value:,}"
    return grouped if _ANSWER_LANGUAGE.get() == "en" else grouped.replace(",", ".")


def yes_no(value: bool) -> str:
    return choose("ja" if value else "nein", "yes" if value else "no")


# --------------------------------------------------------------------------- #
# Detection                                                                    #
# --------------------------------------------------------------------------- #
def resolve_answer_language(
    question: Any,
    ui_context: Optional[Mapping[str, Any]] = None,
    interface_language: Any = None,
) -> str:
    """Question language, else UI ``locale``, else request language, else German."""
    detected = detect_question_language(question)
    if detected:
        return detected
    context = ui_context if isinstance(ui_context, Mapping) else {}
    session = context.get("session")
    session = session if isinstance(session, Mapping) else {}
    locale = normalize(context.get("locale")) or normalize(session.get("locale"))
    return locale or normalize(interface_language) or DEFAULT


__all__ = [
    "DEFAULT",
    "LANGUAGES",
    "answer_language",
    "answer_language_scope",
    "choose",
    "detect_question_language",
    "enter_answer_language",
    "format_int",
    "is_english",
    "normalize",
    "resolve",
    "resolve_answer_language",
    "text_value",
    "yes_no",
]
