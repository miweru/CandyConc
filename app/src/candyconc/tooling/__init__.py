"""Tooling utilities for CandyConc."""
# mypy: ignore-errors

from __future__ import annotations

# Import tools to populate the registry at package load time
from .registry import REGISTRY, llm_tool, get_tools, get_schema_map, get_tool_runtime_info
from .tool_selection import (
    bindings_allow_default_release_dispatch,
    filter_dispatchable_tools_for_principal,
    is_tool_dispatchable_for_principal,
    product_binding_metadata,
    product_tool_bindings_by_name,
    response_contract_for_prompt,
    select_tools_for_prompt,
)
import candyconc.candyconc_copilot.tool_wrappers  # noqa: F401

__all__ = [
    "llm_tool",
    "get_tools",
    "get_schema_map",
    "get_tool_runtime_info",
    "select_tools_for_prompt",
    "response_contract_for_prompt",
    "product_tool_bindings_by_name",
    "bindings_allow_default_release_dispatch",
    "product_binding_metadata",
    "is_tool_dispatchable_for_principal",
    "filter_dispatchable_tools_for_principal",
    "REGISTRY",
]
