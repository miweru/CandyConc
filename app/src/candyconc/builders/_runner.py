"""Shared launcher for the packaged Fast-Index builders.

The builder implementations ship in :mod:`candyconc.ingest`. This runner runs a
builder **in-process** via ``importlib`` (every implementation exposes
``main(argv) -> int``). The subprocess path remains for script names without
an in-process module and for an explicit ``CANDYCONC_BUILDER_DIR`` override of
the builder scripts.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

# Builder script name -> ordered list of dotted module names to try importing.
# The first module that imports AND exposes a ``main(argv)`` callable is run
# in-process.
_INPROCESS_MODULES: dict[str, tuple[str, ...]] = {
    "build_fast_index_from_parquet.py": ("candyconc.builders._impl_build_fast_index_from_parquet",),
    "ingest_adapters.py": ("candyconc.builders._impl_ingest_adapters",),
    "build_fast_index_from_vrt.py": ("candyconc.ingest.build_fast_index_from_vrt",),
}

#: Script name -> implementation module in :mod:`candyconc.ingest`.
IMPLEMENTATION_MODULES: dict[str, str] = {
    "build_fast_index_from_parquet.py": "candyconc.ingest.build_fast_index_from_parquet",
    "ingest_adapters.py": "candyconc.ingest.ingest_adapters",
    "build_fast_index_from_vrt.py": "candyconc.ingest.build_fast_index_from_vrt",
}


def _candidate_dirs() -> tuple[Path, ...]:
    here = Path(__file__).resolve()
    return (here, *here.parents)


def _import_builder_main(module_names: Sequence[str]) -> Callable[[list[str]], int] | None:
    """Import the first available builder module and return its ``main`` callable.

    Returns ``None`` when no candidate module imports with a usable ``main``.
    A ``ModuleNotFoundError`` for a candidate is expected (that builder is not
    packaged / not on the path); any *other* import error is genuine and is
    re-raised so the operator sees the real failure instead of a silent
    subprocess fallback.
    """

    for name in module_names:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # Only swallow "this module/its package is absent"; a missing
            # *transitive* dependency inside an otherwise-present builder is a
            # real error the operator must see.
            missing = (exc.name or "")
            top = name.split(".", 1)[0]
            if missing == name or name.startswith(missing + ".") or missing == top:
                continue
            raise
        main = getattr(module, "main", None)
        if callable(main):
            return main
    return None


def run_in_process(script_name: str, argv: list[str]) -> int | None:
    """Run the builder for ``script_name`` in-process if importable.

    Returns the builder's integer exit code, or ``None`` when no importable
    in-process module exists for ``script_name`` (caller should fall back to the
    subprocess path).
    """

    module_names = _INPROCESS_MODULES.get(script_name)
    if not module_names:
        return None
    main = _import_builder_main(module_names)
    if main is None:
        return None
    result = main(list(argv))
    # Builders return an int exit code; treat a ``None`` return as success.
    return int(result) if result is not None else 0


def resolve_repo_builder(
    script_name: str, *, env_var: str = "CANDYCONC_BUILDER_DIR"
) -> Path:
    """Return the path to the repo-root implementation ``script_name``.

    Looks under ``$CANDYCONC_BUILDER_DIR`` first (accepting the directory with
    the script itself, the checkout root with ``scripts/jobs/`` or its
    ``scripts`` directory, mirroring the in-process seams), then walks parents
    looking for a ``scripts/jobs/<script_name>`` file.
    """

    if not script_name or Path(script_name).name != script_name:
        raise ValueError(f"Invalid builder script name: {script_name!r}")

    configured = os.environ.get(env_var)
    if configured:
        base = Path(configured).expanduser().resolve()
        for candidate in (
            base / script_name,
            base / "jobs" / script_name,
            base / "scripts" / "jobs" / script_name,
        ):
            if candidate.is_file():
                return candidate

    for parent in _candidate_dirs():
        candidate = parent / "scripts" / "jobs" / script_name
        if candidate.is_file():
            return candidate
        if parent.name == "jobs":
            candidate = parent / script_name
            if candidate.is_file():
                return candidate

    raise FileNotFoundError(
        f"Builder implementation {script_name!r} not found. Looked under "
        f"${env_var} and for scripts/jobs/{script_name} above "
        f"{Path(__file__).resolve()}. Set {env_var} to the directory that "
        "contains the builder scripts (or scripts/jobs)."
    )


def run_repo_builder(script_name: str, argv: list[str]) -> int:
    """Locate ``script_name`` and run it as a subprocess; return its exit code.

    Subprocess is the last-resort path for builders that are not importable
    in-process (no packaged implementation module). Used only after
    :func:`run_in_process` returns ``None``.
    """

    target = resolve_repo_builder(script_name)
    cmd = [sys.executable, str(target), *argv]
    return subprocess.run(cmd, check=False).returncode


def main(script_name: str, argv: list[str] | None = None) -> int:
    """Console-style entry point for a packaged builder launcher.

    Prefers an in-process run and falls back to a builder script subprocess
    only when no importable builder module is available.
    """

    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    in_process = run_in_process(script_name, resolved_argv)
    if in_process is not None:
        return in_process
    return run_repo_builder(script_name, resolved_argv)
