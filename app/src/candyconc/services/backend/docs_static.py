"""Serve the bundled HTML user documentation under ``/docs/``.

The help menu of the interface links to ``/docs/``. The pages are the Sphinx
build of the ``docs`` folder, copied into the package by
``packaging/build_web.py`` when the documentation tools are installed. They
load no script from another host, so the manual works without a network
connection.

Search order for the documentation directory, as in ``frontend_static``:

1. ``CANDYCONC_DOCS_DIST``: an explicit operator choice. If it is set, it is
   the only candidate (without an ``index.html`` in it: no documentation).
2. The documentation shipped in the package (``candyconc/docs_html``).
3. Walking up from this file to a built ``docs/_build/html`` (published
   repository) or ``repo_root/docs/_build/html`` (development tree).

``/docs`` without a trailing slash stays the interactive API page of FastAPI,
which the release mode hides. Only paths below ``/docs/`` are the manual.

Every file is sent with ``Cache-Control: no-cache``. Sphinx output keeps its
names across versions (``searchindex.js``, pages, images), so after an update
the browser must revalidate instead of showing the previous manual.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .frontend_static import FRONTEND_MOUNT_NAME, CacheControlStaticFiles

DOCS_DIST_ENV = "CANDYCONC_DOCS_DIST"
DOCS_MOUNT_NAME = "user-docs"
DOCS_URL = "/docs/"


def packaged_docs_dir() -> Path:
    """Location of the documentation shipped inside the ``candyconc`` package."""
    return Path(__file__).resolve().parents[2] / "docs_html"


def docs_dist_dir() -> Path | None:
    """The documentation directory, or ``None`` when none is available."""
    env_value = os.environ.get(DOCS_DIST_ENV, "").strip()
    if env_value:
        candidate = Path(env_value).expanduser()
        return candidate if (candidate / "index.html").is_file() else None
    packaged = packaged_docs_dir()
    if (packaged / "index.html").is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        for candidate in (
            parent / "docs" / "_build" / "html",
            parent / "repo_root" / "docs" / "_build" / "html",
        ):
            if (candidate / "index.html").is_file():
                return candidate
    return None


def install_docs(app: Any, dist_dir: Path | None = None) -> Path | None:
    """Mount the documentation on ``/docs/`` if a build exists.

    The mount goes before the interface mount on ``/``, which would otherwise
    answer every path below ``/docs/`` with the interface.
    """
    dist = dist_dir if dist_dir is not None else docs_dist_dir()
    if dist is None:
        return None
    app.mount("/docs", CacheControlStaticFiles(directory=str(dist), html=True), name=DOCS_MOUNT_NAME)
    routes = app.router.routes
    mount = routes.pop()
    position = next(
        (i for i, route in enumerate(routes) if getattr(route, "name", None) == FRONTEND_MOUNT_NAME),
        len(routes),
    )
    routes.insert(position, mount)
    return dist


def uninstall_docs(app: Any) -> list[Any]:
    """Remove the documentation mount (test seam). Returns the removed routes."""
    removed = [route for route in app.router.routes if getattr(route, "name", None) == DOCS_MOUNT_NAME]
    for route in removed:
        app.router.routes.remove(route)
    return removed
