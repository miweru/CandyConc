"""S5b Single-Command-Start: Auslieferung des gebauten Vue-Frontends.

Der Server mountet, falls ein Frontend-Build vorhanden ist, ein SPA-taugliches
``StaticFiles`` auf ``/``. Der Mount wird NACH allen API-/MCP-/WS-Routen
registriert, damit jede echte Route Vorrang behält. Ohne Build bleibt das
Serververhalten unverändert (``GET /`` und unbekannte Pfade -> 404
problem+json).

Search order for the build directory:

1. ``CANDYCONC_FRONTEND_DIST``: an explicit operator choice. If it is set, it
   is the only candidate (without an ``index.html`` in it: no interface).
2. The interface shipped in the package (``candyconc/web_dist``, written by
   ``packaging/build_web.py`` and included in sdist and wheel).
3. Walking up from this file to ``candyconc-web/dist`` (development checkout
   after ``npm run build``).

Caching: ``index.html`` and every file without a content hash in its name
are sent with ``Cache-Control: no-cache``, so the browser revalidates them
(ETag) on each load. After an update to a new wheel it therefore gets the new
``index.html`` and its new chunk names instead of a stale page whose chunks
answer 404. Hashed build output under ``assets/`` never changes its content
and may be cached for a year.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles

FRONTEND_DIST_ENV = "CANDYCONC_FRONTEND_DIST"
FRONTEND_MOUNT_NAME = "frontend"

# Erste Pfadsegmente der API-Familie: unbekannte Pfade darunter bleiben 404
# (problem+json über die registrierten Exception-Handler) statt SPA-Fallback.
RESERVED_FIRST_SEGMENTS = frozenset(
    {"api", "mcp", "ws", "health", "healthz", "metrics", "docs", "redoc"}
)
RESERVED_EXACT_PATHS = frozenset({"openapi.json"})

CACHE_NO_CACHE = "no-cache"
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
# Vite names build output ``assets/<name>-<hash>.<ext>`` with an 8 character
# base64url content hash.
_HASHED_ASSET_NAME = re.compile(r"-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")


def interface_cache_control(relative_path: str) -> str:
    """Cache policy for a file of the interface build, by its path in the build."""
    parts = PurePosixPath(relative_path.replace(os.sep, "/")).parts
    if len(parts) >= 2 and parts[0] == "assets" and _HASHED_ASSET_NAME.search(parts[-1]):
        return CACHE_IMMUTABLE
    return CACHE_NO_CACHE


class CacheControlStaticFiles(StaticFiles):
    """``StaticFiles`` that sets ``Cache-Control`` on every file response.

    The header is set before the conditional request check, so a
    ``304 Not Modified`` carries the same policy as the full response.
    """

    def cache_control(self, relative_path: str) -> str:
        return CACHE_NO_CACHE

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Any,
        status_code: int = 200,
    ) -> Response:
        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result)
        root = os.path.realpath(str(self.directory)) if self.directory is not None else ""
        relative = os.path.relpath(os.path.realpath(str(full_path)), root) if root else str(full_path)
        response.headers["cache-control"] = self.cache_control(relative)
        if self.is_not_modified(response.headers, Headers(scope=scope)):
            return NotModifiedResponse(response.headers)
        return response


def packaged_dist_dir() -> Path:
    """Location of the interface shipped inside the ``candyconc`` package."""
    return Path(__file__).resolve().parents[2] / "web_dist"


def frontend_dist_dir() -> Path | None:
    """Das Frontend-Build-Verzeichnis oder ``None``, wenn keines existiert.

    Ein Verzeichnis zählt nur mit vorhandener ``index.html`` als Build.
    """
    env_value = os.environ.get(FRONTEND_DIST_ENV, "").strip()
    if env_value:
        candidate = Path(env_value).expanduser()
        return candidate if (candidate / "index.html").is_file() else None
    packaged = packaged_dist_dir()
    if (packaged / "index.html").is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "candyconc-web" / "dist"
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _is_reserved(path: str) -> bool:
    normalized = path.strip("/")
    if normalized in RESERVED_EXACT_PATHS:
        return True
    return normalized.partition("/")[0] in RESERVED_FIRST_SEGMENTS


def _looks_like_file_request(path: str) -> bool:
    """True, wenn das letzte Pfadsegment eine Dateiendung trägt.

    Ein fehlender Pfad mit Dateiendung (z. B. ``/assets/alt-chunk.js`` eines
    veralteten Builds) ist eine Datei-Anfrage: die SPA-``index.html`` wäre dort
    eine irreführende 200-Antwort (Stale-Chunk-Schutz), also bleibt es 404.
    Versteckte Dateien ohne Endung (``.env``) und Segmente mit Punkten weiter
    vorn im Pfad zählen NICHT als Dateiendung.
    """
    return bool(PurePosixPath(path.strip("/")).suffix)


class SPAStaticFiles(CacheControlStaticFiles):
    """``StaticFiles`` mit SPA-Fallback für Client-seitiges Routing.

    * Unbekannte GET-/HEAD-Pfade außerhalb der API-Familie liefern
      ``index.html`` (Deep-Links wie ``/subcorpora`` überlebt ein Reload).
    * API-Familien-Pfade (``/api``, ``/mcp``, ``/ws``, ``/health``-Familie,
      Doku-Pfade) behalten ihr 404-problem+json.
    * Fehlende Pfade MIT Dateiendung (z. B. ``/assets/alt-chunk.js``) bleiben
      404 statt ``index.html`` (Stale-Chunk-Schutz: ein Client mit veralteter
      Chunk-Liste bekommt einen ehrlichen Fehler statt HTML als Skript).
    * Nicht-GET-Methoden auf unbekannten Pfaden bleiben 404 (vor dem Mount
      antwortete der Router dort mit 404, nicht mit 405).
    * ``index.html`` and unhashed files are revalidated, hashed assets are
      cached long (``interface_cache_control``).
    """

    def cache_control(self, relative_path: str) -> str:
        return interface_cache_control(relative_path)

    async def get_response(self, path: str, scope: Any) -> Response:
        if scope["method"] not in {"GET", "HEAD"}:
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _is_reserved(path) or _looks_like_file_request(path):
                raise
            return await super().get_response("index.html", scope)


def install_frontend(app: Any, dist_dir: Path | None = None) -> Path | None:
    """SPA auf ``/`` mounten, falls ein Frontend-Build existiert.

    Gibt das verwendete Dist-Verzeichnis zurück; ``None`` bedeutet: kein
    Build gefunden, Serververhalten unverändert.
    """
    dist = dist_dir if dist_dir is not None else frontend_dist_dir()
    if dist is None:
        return None
    app.mount(
        "/",
        SPAStaticFiles(directory=str(dist), html=True),
        name=FRONTEND_MOUNT_NAME,
    )
    return dist


def uninstall_frontend(app: Any) -> list[Any]:
    """Alle SPA-Mounts entfernen (Test-Naht); gibt die entfernten Routen zurück."""
    removed = [
        route
        for route in app.router.routes
        if getattr(route, "name", None) == FRONTEND_MOUNT_NAME
    ]
    for route in removed:
        app.router.routes.remove(route)
    return removed
