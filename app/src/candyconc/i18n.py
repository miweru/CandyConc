"""Bilingual server texts (German and English).

A user-visible text is written once as a German and English pair::

    from candyconc.i18n import lt

    MESSAGE = lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}")

:class:`LocalizedText` is a ``str`` whose value is the German text, so every
existing comparison, log line and test keeps seeing German. The English text
rides along in ``.en``. The pair is resolved to one language only when a
response is rendered: the backend sets the interface language of the request
(``Accept-Language``, see ``services/backend/request_language.py``) in a
context variable, and the JSON response class, the problem+json handlers and
the SSE encoder call :func:`localize`. German stays the default when a request
names no supported language.

String operations other than :meth:`LocalizedText.format` and ``+`` return a
plain German ``str``. Build messages with ``.format`` (not f-strings) when
both languages must survive.
"""

from __future__ import annotations

import string
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

SUPPORTED_LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"

_LANGUAGE: ContextVar[str] = ContextVar("candyconc_language", default=DEFAULT_LANGUAGE)


def normalize_language(language: str | None) -> str:
    """Return ``language`` if supported, otherwise the default language."""
    if language in SUPPORTED_LANGUAGES:
        return language  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


def current_language() -> str:
    """Interface language of the request being served (``de`` or ``en``)."""
    return _LANGUAGE.get()


@contextmanager
def language_scope(language: str | None) -> Iterator[str]:
    """Serve the enclosed code in ``language`` (used by middleware and tests)."""
    token = _LANGUAGE.set(normalize_language(language))
    try:
        yield _LANGUAGE.get()
    finally:
        _LANGUAGE.reset(token)


def _for_language(value: Any, language: str) -> Any:
    if isinstance(value, LocalizedText):
        return value.resolve(language)
    return value


class LocalizedText(str):
    """A German text (the ``str`` value) with its English counterpart."""

    en: str

    def __new__(cls, de: str, en: str) -> "LocalizedText":
        if not isinstance(de, str) or not isinstance(en, str):
            raise TypeError("LocalizedText needs a German and an English str")
        obj = super().__new__(cls, de)
        obj.en = str(en)
        return obj

    @property
    def de(self) -> str:
        return str.__str__(self)

    def resolve(self, language: str | None = None) -> str:
        """Plain text in ``language`` (default: the current request language)."""
        lang = normalize_language(language) if language is not None else current_language()
        return self.en if lang == "en" else str.__str__(self)

    def format(self, *args: Any, **kwargs: Any) -> "LocalizedText":  # type: ignore[override]
        de = str.format(
            str.__str__(self),
            *[_for_language(a, "de") for a in args],
            **{k: _for_language(v, "de") for k, v in kwargs.items()},
        )
        en = self.en.format(
            *[_for_language(a, "en") for a in args],
            **{k: _for_language(v, "en") for k, v in kwargs.items()},
        )
        return LocalizedText(de, en)

    def __add__(self, other: object) -> "LocalizedText":  # type: ignore[override]
        if isinstance(other, LocalizedText):
            return LocalizedText(str.__str__(self) + other.de, self.en + other.en)
        if isinstance(other, str):
            return LocalizedText(str.__str__(self) + other, self.en + other)
        return NotImplemented

    def __radd__(self, other: object) -> "LocalizedText":
        if isinstance(other, str):
            return LocalizedText(other + str.__str__(self), other + self.en)
        return NotImplemented

    def __getnewargs__(self) -> tuple[str, str]:
        return (str.__str__(self), self.en)

    def __repr__(self) -> str:
        return f"lt({str.__str__(self)!r}, {self.en!r})"


lt = LocalizedText


def join_texts(separator: str, parts: list[Any]) -> LocalizedText:
    """``separator.join(parts)`` that keeps both languages of LocalizedText parts."""
    return LocalizedText(
        separator.join(_for_language(p, "de") for p in parts),
        separator.join(_for_language(p, "en") for p in parts),
    )


def exception_text(exc: BaseException) -> str:
    """Message of ``exc``, keeping both languages when it was raised with LocalizedText.

    ``str(exc)`` always gives the German text. Use this where a route turns an
    exception into a user-visible ``detail`` or ``message``.
    """
    candidates = [getattr(exc, "message", None)]
    if exc.args:
        candidates.append(exc.args[0])
    for candidate in candidates:
        if isinstance(candidate, LocalizedText):
            return candidate
    return str(exc)


def localize(value: Any, language: str | None = None) -> Any:
    """Replace every LocalizedText in ``value`` (dicts, lists, tuples) by plain text.

    ``language`` defaults to the current request language. Other objects are
    returned unchanged. Containers are rebuilt, the input is not modified.
    """
    lang = normalize_language(language) if language is not None else current_language()
    return _localize(value, lang)


def _localize(value: Any, lang: str) -> Any:
    if isinstance(value, LocalizedText):
        return value.resolve(lang)
    if isinstance(value, dict):
        return {_localize(k, lang): _localize(v, lang) for k, v in value.items()}
    if isinstance(value, list):
        return [_localize(v, lang) for v in value]
    if isinstance(value, tuple):
        return tuple(_localize(v, lang) for v in value)
    return value


def bilingual_form(value: Any) -> Any:
    """Replace every LocalizedText by ``{"de": ..., "en": ...}``.

    For content hashes that must not depend on the request language but must
    change when either translation changes.
    """
    if isinstance(value, LocalizedText):
        return {"de": value.de, "en": value.en}
    if isinstance(value, dict):
        return {k: bilingual_form(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [bilingual_form(v) for v in value]
    return value


def placeholders(template: str) -> set[str] | None:
    """Named ``str.format`` fields of ``template`` (for catalogue tests).

    ``None`` when the text is no format template (for example LaTeX with
    literal braces), such a text must not be used with ``.format``.
    """
    try:
        return {
            field.split(".")[0].split("[")[0]
            for _, field, _, _ in string.Formatter().parse(template)
            if field
        }
    except ValueError:
        return None


__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "LocalizedText",
    "bilingual_form",
    "current_language",
    "exception_text",
    "join_texts",
    "language_scope",
    "localize",
    "lt",
    "normalize_language",
    "placeholders",
]
