from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable
from http import HTTPStatus

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException, RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel


class Problem(BaseModel):
    """RFC 7807 compatible problem description.

    ``detail`` is written in the interface language of the request. ``code``
    and ``params`` identify the message independently of the language for
    errors raised as :class:`ApiError`.
    """

    type: str = "about:blank"
    title: str
    status: int
    detail: Any | None = None
    instance: str | None = None
    code: str | None = None
    params: dict[str, Any] | None = None


from candyconc.core.meta_filters import EingabeFormFehler  # noqa: E402
from candyconc.i18n import LocalizedText, exception_text, localize, lt  # noqa: E402
from candyconc.services.backend.request_language import request_language  # noqa: E402


class ApiError(HTTPException):
    """HTTPException with a stable message code and a bilingual message.

    ``message`` is a :class:`~candyconc.i18n.LocalizedText` template whose
    named fields are filled from ``params``. ``detail`` holds the filled
    message, whose ``str`` value is German, so code and tests that read
    ``exc.detail`` keep working. The problem+json handler sends ``detail`` in
    the request language and adds ``code`` and ``params``::

        raise ApiError(404, "corpus.not_found",
                       lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"),
                       name=name)
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: LocalizedText,
        *,
        headers: dict[str, str] | None = None,
        **params: Any,
    ) -> None:
        self.code = code
        self.params = params
        self.message = message
        detail = message.format(**params) if params else message
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def _json_param(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_param(v) for v in value]
    return str(value)


def problem(
    status: int,
    detail: Any = None,
    *,
    title: str | None = None,
    type: str = "about:blank",
    instance: str | None = None,
    code: str | None = None,
    params: dict[str, Any] | None = None,
    language: str | None = None,
) -> JSONResponse:
    """Return a :class:`JSONResponse` with a serialized :class:`Problem`.

    LocalizedText in ``detail`` is resolved to ``language`` (default: the
    language of the current request).
    """

    title = title or HTTPStatus(status).phrase

    body = Problem(
        type=type,
        title=title,
        status=status,
        detail=localize(detail, language),
        instance=instance,
        code=code,
        params=(
            {k: _json_param(v) for k, v in localize(params, language).items()}
            if params is not None
            else None
        ),
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        media_type="application/problem+json",
    )



def http_exc_to_problem(request: Request, exc: HTTPException) -> JSONResponse:
    """Convert :class:`HTTPException` to :func:`problem` in the request language."""

    return problem(
        status=exc.status_code,
        detail=exc.detail,
        title=HTTPStatus(exc.status_code).phrase,
        instance=request.url.path,
        code=exc.code if isinstance(exc, ApiError) else None,
        params=exc.params if isinstance(exc, ApiError) else None,
        language=request_language(request),
    )


def validation_to_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert :class:`RequestValidationError` to :func:`problem`.

    Normalizes the validation envelope so ``detail`` is *always* a stable,
    human-readable string (RFC 7807 ``detail`` is defined as a string), while the
    full structured per-field list lives under a stable sibling key ``errors``.
    Historically ``detail`` was the structured object ``{"errors": [...]}``, which
    forced clients to branch between a string ``detail`` (other handlers) and an
    object ``detail`` (validation). This change is additive: the same structured
    list is still emitted (now under top-level ``errors``, mirroring its prior
    nested shape), so existing readers of the error rows keep working while
    ``detail`` becomes reliably a string.
    """

    errors: list[Any] = []
    for err in exc.errors():
        try:
            errors.append(dict(err))
        except Exception:  # pragma: no cover - defensive
            errors.append(str(err))

    # Stable, always-string human-readable summary for ``detail``.
    count = len(errors)
    if count == 1:
        message = lt(
            "Anfrage ungültig: 1 Fehler",
            "Request validation failed: 1 error",
        )
    else:
        message = lt(
            "Anfrage ungültig: {count} Fehler",
            "Request validation failed: {count} errors",
        ).format(count=count)

    body = Problem(
        type="about:blank",
        title=HTTPStatus(400).phrase,
        status=400,
        detail=message.resolve(request_language(request)),
        instance=request.url.path,
        code="request.validation_failed",
        params={"count": count},
    )
    content = body.model_dump(exclude_none=True)
    # Structured per-field detail under a stable sibling key (was previously
    # nested inside ``detail`` as ``{"errors": [...]}``).
    content["errors"] = errors
    return JSONResponse(
        status_code=400,
        content=content,
        media_type="application/problem+json",
    )


def unhandled_to_problem(request: Request, exc: Exception) -> JSONResponse:
    """Convert any unhandled :class:`Exception` to an RFC 7807 problem (500).

    Without this catch-all, an unexpected error escapes FastAPI as a
    ``text/plain`` 500, breaking the ``application/problem+json`` contract that
    every documented response code already advertises. The exception detail is
    deliberately generic (no stack/internal message leaked to the client); the
    real exception still surfaces in server logs via the framework's logger.
    """
    return problem(
        status=500,
        detail=lt("Interner Serverfehler", "Internal server error"),
        title=HTTPStatus(500).phrase,
        instance=request.url.path,
        code="server.internal_error",
        language=request_language(request),
    )


def eingabeform_to_problem(request: Any, exc: Exception) -> Any:
    """Ungueltige Eingabeform -> HTTP 400 mit der vollen Meldung.

    SYNCHRON, wie ``http_exc_to_problem``. Die erste Fassung war
    ``async def`` und hat die synchrone Funktion AWAITET. Jeder Aufruf
    endete in ``TypeError: object JSONResponse can't be used in 'await'
    expression``, fiel in ``unhandled_to_problem`` und lieferte HTTP 500
    mit verschluckter Meldung -- also woertlich den Zustand, den der
    Handler beheben sollte. Er war 0 von 4 wirksam, und kein Test hat ihn
    je aufgerufen. ``tests/backend/test_input_form_error_handler.py`` tut es
    jetzt, ueber die echte App.
    """
    return http_exc_to_problem(
        request, HTTPException(status_code=400, detail=exception_text(exc))
    )


def register_exception_handlers(app: Any) -> None:
    """Register all problem+json exception handlers on a FastAPI ``app``.

    Single entry point so the generic-Exception catch-all (Track D12) is wired
    consistently alongside the HTTPException / validation handlers. The generic
    handler MUST be registered last (most general) — Starlette dispatches the
    most specific registered handler, so the specific ones still win.
    """
    # ``StarletteHTTPException`` is registered alongside ``fastapi.HTTPException``
    # because framework-level routing errors (404 Not Found, 405 Method Not
    # Allowed) are raised as the Starlette base type, not the FastAPI subclass.
    # Without this, those routes fell back to Starlette's default bare
    # ``{"detail": "..."}`` body, breaking the ``application/problem+json``
    # envelope that every application-level error already uses.
    app.add_exception_handler(HTTPException, http_exc_to_problem)
    app.add_exception_handler(StarletteHTTPException, http_exc_to_problem)
    app.add_exception_handler(RequestValidationError, validation_to_problem)
    # Map invalid input forms to HTTP 400 in one handler. Otherwise routes
    # without a local catch would turn the same input error into HTTP 500.
    app.add_exception_handler(EingabeFormFehler, eingabeform_to_problem)
    app.add_exception_handler(Exception, unhandled_to_problem)


def _localizing_call(call: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an endpoint so its return value is localized before serialization."""
    if asyncio.iscoroutinefunction(call):

        @functools.wraps(call)
        async def async_endpoint(*args: Any, **kwargs: Any) -> Any:
            return localize(await call(*args, **kwargs))

        endpoint: Callable[..., Any] = async_endpoint
    else:

        @functools.wraps(call)
        def sync_endpoint(*args: Any, **kwargs: Any) -> Any:
            return localize(call(*args, **kwargs))

        endpoint = sync_endpoint
    endpoint._candyconc_localized = True  # type: ignore[attr-defined]
    return endpoint


class LocalizedRoute(APIRoute):
    """APIRoute that resolves bilingual texts before FastAPI serializes them.

    A route with a response model (declared, or inferred from the return
    annotation such as ``-> dict[str, Any]``) is serialized by pydantic in
    JSON mode, which turns every LocalizedText into its German ``str`` before
    the response class sees it. For those routes the endpoint result is
    localized to the request language first. Routes without a response model
    keep the LocalizedText values until ``_SafeJSONResponse`` renders them.
    """

    def get_route_handler(self) -> Callable[..., Any]:
        call = self.dependant.call
        if (
            self.response_field is not None
            and call is not None
            and not getattr(call, "_candyconc_localized", False)
        ):
            self.dependant.call = _localizing_call(call)
        return super().get_route_handler()


class CandyAPIRouter(APIRouter):
    """APIRouter with default Problem responses and bilingual responses."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", LocalizedRoute)
        super().__init__(*args, **kwargs)

    DEFAULT_RESPONSES = {
        400: {"model": Problem},
        401: {"model": Problem},
        403: {"model": Problem},
        404: {"model": Problem},
        409: {"model": Problem},
        422: {"model": Problem},
        503: {"model": Problem},
    }
    DEFAULT_TAGS = {
        "login": ["Auth"],
        "users": ["Auth"],
        "policy": ["Admin"],
        "rate_limit": ["Admin"],
        "jobs": ["Jobs"],
        "health": ["System"],
        "metrics": ["System"],
        "system": ["System"],
        "docs": ["Documents"],
        "query": ["Query"],
        "analysis": ["Analysis"],
        "semantic": ["Semantic"],
        "export": ["Export"],
        "download": ["Export"],
        "embeddings": ["Embeddings"],
        "projects": ["Projects"],
        "results": ["Corpora"],
        "chat": ["Chat"],
        "prefs": ["System"],
        "admin": ["Admin"],
        "settings": ["Admin"],
        "tasks": ["Tasks"],
        "search": ["Search"],
    }

    def add_api_route(
        self,
        path: str,
        endpoint: Callable,
        *,
        responses: dict[int | str, dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:  # type: ignore[override]
        combined = dict(self.DEFAULT_RESPONSES)
        if responses:
            combined.update(responses)
        if "tags" not in kwargs or kwargs["tags"] is None:
            tag_key = path.strip("/").split("/", 1)[0] if path else ""
            tags = self.DEFAULT_TAGS.get(tag_key)
            if tags is not None:
                kwargs["tags"] = tags
        return super().add_api_route(path, endpoint, responses=combined, **kwargs)


__all__ = [
    "ApiError",
    "Problem",
    "problem",
    "http_exc_to_problem",
    "validation_to_problem",
    "unhandled_to_problem",
    "register_exception_handlers",
    "CandyAPIRouter",
    "LocalizedRoute",
]
