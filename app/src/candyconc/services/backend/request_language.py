"""Interface language of a request, read from its ``Accept-Language`` header.

The web client sends the active interface language with every request
(``en, de;q=0.5`` or ``de, en;q=0.5``). Routes that return user-visible text
can call :func:`request_language` or declare it as a FastAPI dependency::

    @router.get("/example")
    def example(language: str = Depends(request_language)) -> dict: ...

Only the primary subtag counts (``en-GB`` gives ``en``). Unsupported or
missing values give German, the language of the existing server texts.
"""

from __future__ import annotations

from typing import Any, Optional

from starlette.requests import HTTPConnection

from candyconc.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, language_scope


def _quality(params: list[str]) -> Optional[float]:
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "q":
            try:
                quality = float(value.strip())
            except ValueError:
                return None
            if not 0.0 <= quality <= 1.0:
                return None
            return quality
    return 1.0


def parse_accept_language(header: Optional[str]) -> str:
    """Return the supported language with the highest quality in ``header``."""
    if not header:
        return DEFAULT_LANGUAGE
    candidates: list[tuple[float, int, str]] = []
    for index, entry in enumerate(header.split(",")):
        tag, *params = entry.strip().split(";")
        primary = tag.strip().lower().split("-")[0]
        quality = _quality(params)
        if not primary or quality is None or quality <= 0.0:
            continue
        candidates.append((quality, index, primary))
    for _quality_value, _index, primary in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if primary in SUPPORTED_LANGUAGES:
            return primary
        if primary == "*":
            return DEFAULT_LANGUAGE
    return DEFAULT_LANGUAGE


def request_language(request: HTTPConnection) -> str:
    """Interface language of an HTTP or WebSocket request (``de`` or ``en``).

    A WebSocket may name the language as ``?lang=`` (see LanguageMiddleware).
    """
    if request.scope.get("type") == "websocket":
        requested = _query_language(request.scope.get("query_string") or b"")
        if requested is not None:
            return requested
    return parse_accept_language(request.headers.get("accept-language"))


class LanguageMiddleware:
    """Pure ASGI middleware: serve each HTTP/WebSocket request in its language.

    Sets :func:`candyconc.i18n.current_language` for the whole request, so
    response rendering resolves :class:`candyconc.i18n.LocalizedText` values.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        header: Optional[str] = None
        for name, value in scope.get("headers") or ():
            if name == b"accept-language":
                header = value.decode("latin-1")
                break
        language = parse_accept_language(header)
        if scope.get("type") == "websocket":
            # A browser WebSocket upgrade sends the browser's own
            # Accept-Language, so the web client names the interface language
            # in the query string (``?lang=en``).
            requested = _query_language(scope.get("query_string") or b"")
            if requested is not None:
                language = requested
        with language_scope(language):
            await self.app(scope, receive, send)


def _query_language(query_string: bytes) -> Optional[str]:
    for pair in query_string.decode("latin-1").split("&"):
        name, _, value = pair.partition("=")
        if name == "lang" and value.strip().lower() in SUPPORTED_LANGUAGES:
            return value.strip().lower()
    return None
