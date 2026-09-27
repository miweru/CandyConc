"""Convenience re-exports for core services."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "app",
]

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from .backend import app


def __getattr__(name: str):  # pragma: no cover - simple lazy imports
    if name == "app":
        from .backend import app as value
    else:
        raise AttributeError(name)

    globals()[name] = value
    return value
