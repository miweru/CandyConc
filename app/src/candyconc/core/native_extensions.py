from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType

CANDYCONC_NATIVE_EXTENSIONS: tuple[str, ...] = (
    "candyconc.core._fast_count",
    "candyconc.core._fast_index",
)

CQLHPC_NATIVE_EXTENSIONS: tuple[str, ...] = (
    "cqlhpc.cython._lexicon",
    "cqlhpc.cython._nfa",
    "cqlhpc.cython._planner",
    "cqlhpc.cython._postings",
)

REQUIRED_NATIVE_EXTENSIONS: tuple[str, ...] = (
    *CANDYCONC_NATIVE_EXTENSIONS,
    *CQLHPC_NATIVE_EXTENSIONS,
)


def missing_native_extensions(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> dict[str, Exception]:
    missing: dict[str, Exception] = {}
    for module_name in REQUIRED_NATIVE_EXTENSIONS:
        try:
            importer(module_name)
        except Exception as exc:  # pragma: no cover - exercised with fake importer
            missing[module_name] = exc
    return missing


def require_native_extensions(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> None:
    missing = missing_native_extensions(importer)
    if not missing:
        return
    details = ", ".join(f"{name}: {exc}" for name, exc in missing.items())
    raise RuntimeError(
        "Native extensions fehlen oder laden nicht. "
        f"Bitte build_ext ausführen. Details: {details}"
    )
