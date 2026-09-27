from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["app", "metrics", "server"]


def __getattr__(name: str) -> Any:
    if name == "server":
        return import_module(f"{__name__}.server")
    if name == "app":
        return import_module(f"{__name__}.server").app
    if name == "metrics":
        return import_module(f"{__name__}.metrics")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
