"""Main CandyConc package exposing tooling utilities."""

from __future__ import annotations
# mypy: ignore-errors

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - optional heavy imports
    from .tooling.registry import (
        REGISTRY,
        get_schema_map,
        get_tool_runtime_info,
        get_tools,
        llm_tool,
    )

__all__ = [
    "llm_tool",
    "get_tools",
    "get_schema_map",
    "get_tool_runtime_info",
    "REGISTRY",
]


def __getattr__(name: str):  # pragma: no cover - lazy import to avoid circular deps
    if name == "__version__":
        from .version import package_version

        return package_version()
    if name in __all__:
        from .tooling.registry import (
            REGISTRY,
            get_schema_map,
            get_tool_runtime_info,
            get_tools,
            llm_tool,
        )
        return {
            "REGISTRY": REGISTRY,
            "llm_tool": llm_tool,
            "get_tools": get_tools,
            "get_schema_map": get_schema_map,
            "get_tool_runtime_info": get_tool_runtime_info,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
