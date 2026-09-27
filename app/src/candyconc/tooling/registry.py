"""Central registry and decorator for LLM tools."""
# mypy: ignore-errors
from __future__ import annotations

from typing import Any, Callable, TypeVar, TYPE_CHECKING
from candyconc.services.semantic.availability import semantic_search_available

if TYPE_CHECKING:  # pragma: no cover - optional imports for type checking
    import candyconc.services.backend.server  # noqa: F401
    import candyconc.candyconc_copilot.tool_wrappers  # noqa: F401


try:
    from prometheus_client import Counter

    _REG_COUNTER = Counter("tool_registered_total", "Total registered LLM tools")
except ImportError:
    _REG_COUNTER = None
except ValueError:
    # Module re-executed while the process-global CollectorRegistry already
    # holds the counter (importlib-based loaders re-exec this file); reuse the
    # existing collector instead of crashing the whole import.
    from prometheus_client import REGISTRY as _PROM_REGISTRY

    _REG_COUNTER = _PROM_REGISTRY._names_to_collectors["tool_registered_total"]

F = TypeVar("F", bound=Callable[..., Any])

REGISTRY: list[dict[str, Any]] = []


def llm_tool(
    tool: dict[str, Any],
    response_schema: dict | None = None,
    *,
    read_only: bool = True,
    concurrency_safe: bool | None = None,
) -> Callable[[F], F]:
    """Register ``tool`` for the decorated function in :data:`REGISTRY`."""

    params = tool.get("function", {}).get("parameters")
    if not isinstance(params, dict) or params.get("type") != "object":
        raise ValueError("Tool schema must define object parameters")

    def wrap(fn: F) -> F:
        # Guard against a misattached decorator: if the tool schema declares a
        # function name it must match the decorated function, otherwise the tool
        # would register under one name but dispatch to a different callable
        # (the cluster_save-on-_stringify_ids class of bug).
        declared = tool.get("function", {}).get("name")
        if declared is not None and fn.__name__ not in (declared, f"{declared}_tool"):
            raise ValueError(
                f"llm_tool: schema name {declared!r} does not match decorated "
                f"function {fn.__name__!r} (expected {declared!r} or "
                f"{declared + '_tool'!r}); decorator is on the wrong function."
            )
        entry = {
            **tool,
            "function": {"name": fn.__name__, **tool.get("function", {})},
            "callable": fn,
            "read_only": read_only,
            "concurrency_safe": read_only if concurrency_safe is None else concurrency_safe,
        }
        if response_schema is not None:
            entry["response_schema"] = response_schema
        REGISTRY.append(entry)
        if _REG_COUNTER is not None:
            _REG_COUNTER.inc()
        return fn

    return wrap


def get_tools() -> list[dict[str, Any]]:
    """Return the list of registered tool schemas (JSON-serializable)."""
    import candyconc.services.backend.server  # noqa: F401
    import candyconc.candyconc_copilot.tool_wrappers  # noqa: F401
    result = []
    for t in _enabled_unique_tools():
        # Nur JSON-serialisierbare Felder zurückgeben (ohne callable/response_schema)
        clean = {
            "type": t.get("type", "function"),
            "function": t.get("function", {}),
        }
        result.append(clean)
    return result


def _tool_enabled(name: str) -> bool:
    if name == "semantic_search":
        if not semantic_search_available():
            return False
    return True


def _enabled_unique_tools() -> list[dict[str, Any]]:
    """Return enabled registry entries with one current entry per tool name."""

    seen: set[str] = set()
    unique_reversed: list[dict[str, Any]] = []
    for tool in reversed(REGISTRY):
        name = str(tool.get("function", {}).get("name", "") or "")
        if not name or name in seen or not _tool_enabled(name):
            continue
        seen.add(name)
        unique_reversed.append(tool)
    return list(reversed(unique_reversed))


def get_schema_map() -> dict[str, dict[str, Any]]:
    """Return a mapping of tool names to their parameter schemas."""

    return {
        t["function"]["name"]: t["function"].get("parameters", {}) for t in get_tools()
    }


def get_tool_runtime_info() -> dict[str, dict[str, Any]]:
    """Return runtime metadata for registered tools."""

    import candyconc.services.backend.server  # noqa: F401
    import candyconc.candyconc_copilot.tool_wrappers  # noqa: F401

    info: dict[str, dict[str, Any]] = {}
    for tool in _enabled_unique_tools():
        name = tool.get("function", {}).get("name")
        if not name:
            continue
        info[str(name)] = {
            "read_only": bool(tool.get("read_only", True)),
            "concurrency_safe": bool(tool.get("concurrency_safe", True)),
        }
    return info
