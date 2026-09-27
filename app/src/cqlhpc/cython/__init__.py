"""Cython accelerators for CQLHPC.

The package is import-safe: if extensions are not compiled, the public API
falls back to pure-Python implementations.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType

CQLHPC_NATIVE_EXTENSIONS: tuple[str, ...] = (
    "cqlhpc.cython._lexicon",
    "cqlhpc.cython._nfa",
    "cqlhpc.cython._planner",
    "cqlhpc.cython._postings",
)


def missing_cqlhpc_native_extensions(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> dict[str, Exception]:
    """Probe the optional CQLHPC accelerators without hiding import failures."""
    missing: dict[str, Exception] = {}
    for module_name in CQLHPC_NATIVE_EXTENSIONS:
        try:
            importer(module_name)
        except Exception as exc:  # pragma: no cover - exercised with fake importer
            missing[module_name] = exc
    return missing


def require_cqlhpc_native_extensions(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> None:
    missing = missing_cqlhpc_native_extensions(importer)
    if not missing:
        return
    details = ", ".join(f"{name}: {exc}" for name, exc in missing.items())
    raise RuntimeError(f"CQLHPC native extensions fehlen oder laden nicht: {details}")
