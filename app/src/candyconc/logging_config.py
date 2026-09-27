from __future__ import annotations

import logging
import sys

from candyconc.config import APP_CONFIG


class _SafeStreamHandler(logging.StreamHandler):
    """Stream handler that ignores BrokenPipeError."""

    def handleError(self, record: logging.LogRecord) -> None:  # pragma: no cover - errors rare
        if isinstance(sys.exc_info()[1], BrokenPipeError):
            return
        super().handleError(record)


class _SafeFileHandler(logging.FileHandler):
    """File handler that ignores BrokenPipeError."""

    def handleError(self, record: logging.LogRecord) -> None:  # pragma: no cover - errors rare
        if isinstance(sys.exc_info()[1], BrokenPipeError):
            return
        super().handleError(record)


def init_logging() -> None:
    """Initialise logging based on environment variables."""
    level = APP_CONFIG.CANDYCONC_LOG_LEVEL.upper()
    log_file = APP_CONFIG.CANDYCONC_LOG_FILE

    handlers: list[logging.Handler] = []
    if log_file:
        handlers.append(_SafeFileHandler(log_file))
    handlers.append(_SafeStreamHandler())

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    # Suppress logging error tracebacks such as BrokenPipeError
    logging.raiseExceptions = False

    # Prevent uvicorn from overwriting our logging configuration
    try:
        import uvicorn.config as uviconfig

        uviconfig.LOGGING_CONFIG = None  # type: ignore[assignment]
    except Exception:
        logging.getLogger(__name__).exception("Failed to adjust uvicorn logging config")

    # Ensure uvicorn loggers propagate to the root logger so that our safe
    # handlers swallow ``BrokenPipeError`` raised when clients disconnect.
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
