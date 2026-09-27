"""The CandyConc version, read from the package metadata.

The single source is ``version`` in the ``[project]`` table of
``pyproject.toml``. An installed package reports it through its metadata. A
source checkout that is used without installation (``PYTHONPATH=src``) reads
the same field from the checkout.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("candyconc")
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python 3.10
            import tomli as tomllib
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    except Exception:
        return "unknown"
    if project.get("name") == "candyconc" and project.get("version"):
        return str(project["version"])
    return "unknown"
