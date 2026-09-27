from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ImportBuilderSpec:
    script_name: str
    subcommand: tuple[str, ...] = ()


_IMPORT_BUILDERS: dict[str, ImportBuilderSpec] = {
    "parquet": ImportBuilderSpec("build_fast_index_from_parquet.py"),
    "vrt": ImportBuilderSpec("build_fast_index_from_vrt.py"),
    "prealigned_parquet": ImportBuilderSpec("ingest_adapters.py", ("prealigned-parquet",)),
    "prealigned_csv": ImportBuilderSpec("ingest_adapters.py", ("prealigned-csv",)),
    "prealigned_jsonl": ImportBuilderSpec("ingest_adapters.py", ("prealigned-jsonl",)),
    # Ungepaarte Adapter (S4 Ingestion-Adoption): dieselben ingest_adapters-
    # Subcommands, jetzt produktweit registriert (CLI + REST + UI-Descriptor).
    "plaintext": ImportBuilderSpec("ingest_adapters.py", ("plaintext",)),
    "csv": ImportBuilderSpec("ingest_adapters.py", ("csv",)),
    "jsonl": ImportBuilderSpec("ingest_adapters.py", ("jsonl",)),
    "hf": ImportBuilderSpec("ingest_adapters.py", ("hf",)),
}


def normalize_import_method(method: str | None) -> str:
    return str(method or "").strip().replace("-", "_").lower()


def supported_import_methods() -> tuple[str, ...]:
    return tuple(_IMPORT_BUILDERS)


def import_builder_spec(method: str | None) -> ImportBuilderSpec | None:
    return _IMPORT_BUILDERS.get(normalize_import_method(method))


def _candidate_dirs(start: str | os.PathLike[str] | None) -> Sequence[Path]:
    if start is None:
        here = Path(__file__).resolve()
    else:
        here = Path(start).expanduser().resolve()
    root = here if here.is_dir() else here.parent
    return (root, *root.parents)


def _package_builder(script_name: str) -> Path | None:
    """Return the packaged ``candyconc.builders`` launcher for ``script_name``.

    Resolved via ``importlib.resources`` so it works for both source checkouts
    and installed wheels. Returns ``None`` when the package or file is absent.
    """

    try:
        from importlib.resources import files

        resource = files("candyconc.builders").joinpath(script_name)
    except (ImportError, ModuleNotFoundError, AttributeError):
        return None
    try:
        path = Path(str(resource))
    except (TypeError, ValueError):
        return None
    return path if path.is_file() else None


def find_builder_script(
    script_name: str,
    *,
    start: str | os.PathLike[str] | None = None,
    env_var: str = "CANDYCONC_BUILDER_DIR",
) -> Path:
    """Resolve a builder script *file* path for the SUBPROCESS fallback path.

    ``candy import`` runs the builders in-process via
    ``candyconc.builders._runner``. The import jobs of the backend start the
    returned file as a subprocess: the packaged launcher in an installed
    package, the compatibility script under ``scripts/jobs`` in a source
    checkout, or a script under ``CANDYCONC_BUILDER_DIR`` when the operator
    sets that override. All of them run :mod:`candyconc.ingest`.
    """

    if not script_name or Path(script_name).name != script_name:
        raise ValueError(f"Invalid builder script name: {script_name!r}")

    # 1) Explicit override directory always wins (deliberate operator choice).
    #    Accepted layouts: the directory with the script itself, the scripts
    #    directory, or the checkout root.
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

    # 2) Installed package location (works from a wheel / any CWD, even when the
    #    repo-root scripts/jobs tree is not present). When ``start`` is provided
    #    the caller is explicitly anchoring the source-tree walk (test/dev), so
    #    the package copy is skipped to honor that anchor.
    if start is None:
        packaged = _package_builder(script_name)
        if packaged is not None:
            return packaged

    # 3) Source-tree parent walk to scripts/jobs/<script_name>.
    for parent in _candidate_dirs(start):
        candidate = parent / "scripts" / "jobs" / script_name
        if candidate.is_file():
            return candidate
        if parent.name == "jobs":
            candidate = parent / script_name
            if candidate.is_file():
                return candidate

    # 4) Package fallback when an explicit ``start`` walk found nothing.
    if start is not None:
        packaged = _package_builder(script_name)
        if packaged is not None:
            return packaged

    searched = ", ".join(
        str(parent / "scripts" / "jobs" / script_name)
        for parent in _candidate_dirs(start)
    )
    raise FileNotFoundError(
        f"Builder {script_name!r} not found. Looked in the installed "
        f"candyconc.builders package, ${env_var}, and source-tree locations "
        f"({searched}). Set {env_var} to the directory containing the builder "
        "scripts (or scripts/jobs), or reinstall candyconc so the builders "
        "package ships the launchers."
    )
