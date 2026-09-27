"""CQLHPC public facade.

The package-level API is intentionally lazy: importing CQLF capability metadata
must not import the full query engine or NumPy-backed corpus runtime.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "parse_cql": ("parser", "parse_cql"),
    "ParseError": ("parser", "ParseError"),
    "normalize": ("normalize", "normalize"),
    "CountResult": ("engine", "CountResult"),
    "QueryEngine": ("engine", "QueryEngine"),
    "SearchOptions": ("engine", "SearchOptions"),
    "Match": ("engine", "Match"),
    "complete": ("autocomplete", "complete"),
    "Suggestion": ("autocomplete", "Suggestion"),
    "diagnose": ("diagnostics", "diagnose"),
    "Diagnostic": ("diagnostics", "Diagnostic"),
    "Fix": ("diagnostics", "Fix"),
    "to_builder_json": ("builder", "to_builder_json"),
    "from_builder_json": ("builder", "from_builder_json"),
    "to_cql": ("builder", "to_cql"),
    "Corpus": ("corpus", "Corpus"),
    "build_toy_corpus": ("corpus", "build_toy_corpus"),
    "Capability": ("capabilities", "Capability"),
    "CapabilitySnippet": ("capabilities", "CapabilitySnippet"),
    "all_capabilities": ("capabilities", "all_capabilities"),
    "build_cqlf_capability_contract": ("capabilities", "build_cqlf_capability_contract"),
    "capability_by_id": ("capabilities", "capability_by_id"),
    "copilot_cqlf_capability_summary": ("capabilities", "copilot_cqlf_capability_summary"),
    "supported_capabilities": ("capabilities", "supported_capabilities"),
    "FastCorpus": ("fast_corpus", "FastCorpus"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(f"{__name__}.{module_name}"), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
