"""Pure query-limit helpers with no configuration or mutable module state.

Server-owned helpers resolve configurable defaults through their own
get_config reference. Keep this module independent of server and routes."""

from candyconc.entrypoints.errors import ApiError
from candyconc.i18n import lt


def _query_hard_limit() -> int:
    return 5000


def _reject_non_positive_limit(value: int) -> None:
    """Raise HTTP 422 for an explicitly-supplied non-positive ``limit``.

    Uniform limit/offset policy (findings 4 + 34): a non-positive limit is a
    logically-invalid request (``limit=0`` cannot mean "give me everything"),
    so it must be rejected with the same 422 the ``group_by`` enum and ``window``
    range already use — not silently coerced to the default. Callers pass the
    raw user value; a missing/None limit is handled by the caller as "defaulted"
    and never reaches here.
    """
    if value <= 0:
        raise ApiError(
            422,
            "request.limit_not_positive",
            lt("limit muss >= 1 sein (erhalten: {value})", "limit must be >= 1 (received: {value})"),
            value=value,
        )
