"""Build configuration that pyproject.toml cannot express.

Metadata, dependencies, extras and the ``candy`` entry point live in the
``[project]`` table of pyproject.toml. This file adds the package layout, the
built web interface as package data and the native Cython extensions from
``setup_native.py``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent
SETUP_NATIVE = ROOT / "setup_native.py"
WEB_DIST = ROOT / "src" / "candyconc" / "web_dist"
#: Optional HTML documentation, written by packaging/build_web.py when Sphinx is installed.
DOCS_HTML = ROOT / "src" / "candyconc" / "docs_html"
#: Release builds set this so a wheel without the web interface fails loudly.
REQUIRE_WEB_DIST_ENV = "CANDYCONC_REQUIRE_WEB_DIST"


def _load_build_extensions():
    spec = importlib.util.spec_from_file_location("candyconc_setup_native", SETUP_NATIVE)
    if spec is None or spec.loader is None:
        raise RuntimeError("setup_native.py konnte nicht geladen werden")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_extensions


def _web_dist_packages() -> dict[str, list[str]]:
    """The built interface as data packages: ``{"candyconc.web_dist": ["index.html", ...], ...}``.

    Each directory of the build is declared as a package with its files as
    package data, so setuptools includes it without the "package would be
    ignored" fallback.
    """
    if not (WEB_DIST / "index.html").is_file():
        if os.environ.get(REQUIRE_WEB_DIST_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
            raise SystemExit(
                f"{REQUIRE_WEB_DIST_ENV} is set but {WEB_DIST} has no index.html. "
                "Build the interface first: python packaging/build_web.py"
            )
        return {}
    packages: dict[str, list[str]] = {}
    for directory in sorted([WEB_DIST, *(d for d in WEB_DIST.rglob("*") if d.is_dir())]):
        name = ".".join(("candyconc", *directory.relative_to(WEB_DIST.parent).parts))
        packages[name] = sorted(p.name for p in directory.iterdir() if p.is_file())
    return packages


def _docs_package_data() -> dict[str, list[str]]:
    """The bundled documentation as package data of ``candyconc``, if it was built.

    A recursive glob instead of data packages: Sphinx output has directories
    such as ``get-started`` that are no valid package names.
    """
    if not (DOCS_HTML / "index.html").is_file():
        return {}
    return {"candyconc": ["docs_html/**/*"]}


build_extensions = _load_build_extensions()
WEB_DIST_PACKAGES = _web_dist_packages()
DOCS_PACKAGE_DATA = _docs_package_data()


setup(
    package_dir={"": "src"},
    packages=[*find_packages("src"), *WEB_DIST_PACKAGES],
    include_package_data=True,
    package_data={**WEB_DIST_PACKAGES, **DOCS_PACKAGE_DATA},
    exclude_package_data={"": ["*.c", "*.pyx"]},
    ext_modules=build_extensions(),
)
