"""Shared index-artifact signature helper for engine caches.

Both the CQLHPC engine cache (:mod:`candyconc.core.cql_engine`) and the
collocation engine cache (:mod:`candyconc.core.collocation_engine`) key cached
engine instances on the index path. Keying on the path string ALONE serves a
STALE engine after an in-place index rebuild (same path, new content) until the
process restarts. Mixing in the newest mtime of a few representative index
artifacts makes a rebuild invalidate the cached engine without a restart.

This module is the single source of truth for that signature so the two engine
caches cannot drift apart (and mirrors ``server._corpus_cache_signature`` without
importing the heavy server module).
"""

from __future__ import annotations

from pathlib import Path

# Representative index artifacts whose mtime changes on a rebuild. Kept in sync
# with ``server._CACHE_SIG_ARTIFACTS``.
INDEX_SIG_ARTIFACTS: tuple[str, ...] = (
    "meta.bin",
    "document_bounds.bin",
    "index_build_meta.json",
    "index_manifest.json",
)


def index_artifact_signature(index_path: Path | str | None) -> int:
    """Return the newest ``st_mtime_ns`` across the representative artifacts.

    Returns ``0`` when nothing is stat-able (missing path / fresh build with no
    artifacts yet), which is a stable sentinel for "no signature".
    """
    if not index_path:
        return 0
    base = Path(str(index_path))
    newest = 0
    for name in INDEX_SIG_ARTIFACTS:
        try:
            mtime = (base / name).stat().st_mtime_ns
        except OSError:
            continue
        if mtime > newest:
            newest = mtime
    return newest


def index_open_signature(index_path: Path | str | None) -> tuple[int, int, int]:
    """Identity of the build a reader opens at ``index_path``.

    Device and inode of the index directory plus the newest artifact mtime.
    ``candy import`` replaces an existing index by swapping in a new directory
    (new inode), and a builder that writes into the directory changes the
    artifact mtimes, so either kind of rebuild changes the signature.
    ``(0, 0, 0)`` means the directory is missing.
    """
    if not index_path:
        return (0, 0, 0)
    base = Path(str(index_path))
    try:
        stat = base.stat()
    except OSError:
        return (0, 0, 0)
    return (int(stat.st_dev), int(stat.st_ino), index_artifact_signature(base))
