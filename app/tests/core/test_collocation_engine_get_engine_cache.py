"""Regression tests for the signature-keyed ``get_engine`` cache.

DEFECT (re-audit medium): ``get_engine(path)`` cached the engine per
path-string only, so an IN-PLACE index rebuild (same path, new artifact
content) kept serving the stale pre-rebuild engine until the process was
restarted (operators had to bounce the backend). The cache is now keyed on
the path PLUS an artifact-mtime signature (newest ``st_mtime_ns`` of
``meta.bin`` / ``document_bounds.bin`` / ``index_build_meta.json`` /
``index_manifest.json`` — mirroring ``server._corpus_cache_signature`` without a
server import) and evicts the stale instance when the signature changes.

``CollocationEngine.__init__`` is lazy (no index load), so a temp directory
with the artifact files stands in for a tiny index here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import candyconc.core.collocation_engine as ce


@pytest.fixture(autouse=True)
def _isolated_engine_cache():
    """Snapshot/restore the module-level cache so tests stay order-independent."""
    saved = dict(ce._ENGINE_CACHE)
    ce._ENGINE_CACHE.clear()
    try:
        yield
    finally:
        ce._ENGINE_CACHE.clear()
        ce._ENGINE_CACHE.update(saved)


def _make_index_dir(base: Path, name: str) -> Path:
    index_dir = base / name
    index_dir.mkdir()
    for artifact in ce._ENGINE_SIG_ARTIFACTS:
        (index_dir / artifact).write_bytes(b"\x00")
    return index_dir


def _bump_mtime(path: Path, delta_ns: int = 2_000_000_000) -> None:
    """Advance mtime explicitly (granularity-proof, unlike ``Path.touch``)."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + delta_ns))


def test_unchanged_signature_returns_same_instance(tmp_path: Path) -> None:
    index_dir = _make_index_dir(tmp_path, "idx")
    first = ce.get_engine(index_dir)
    second = ce.get_engine(index_dir)
    assert second is first


def test_inplace_rebuild_serves_fresh_instance(tmp_path: Path) -> None:
    """Touching ``meta.bin`` (in-place rebuild) must evict the stale engine."""
    index_dir = _make_index_dir(tmp_path, "idx")
    stale = ce.get_engine(index_dir)
    _bump_mtime(index_dir / "meta.bin")
    fresh = ce.get_engine(index_dir)
    assert fresh is not stale
    assert fresh.index_path == stale.index_path
    # the stale instance was evicted, not kept alongside the fresh one
    assert len(ce._ENGINE_CACHE) == 1
    # and the fresh engine is now stable for the new signature
    assert ce.get_engine(index_dir) is fresh


def test_each_signature_artifact_invalidates(tmp_path: Path) -> None:
    index_dir = _make_index_dir(tmp_path, "idx")
    previous = ce.get_engine(index_dir)
    for artifact in ce._ENGINE_SIG_ARTIFACTS:
        _bump_mtime(index_dir / artifact)
        current = ce.get_engine(index_dir)
        assert current is not previous, f"{artifact} mtime bump did not invalidate"
        previous = current


def test_none_path_returns_most_recently_used(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ce.get_engine(None)
    idx_a = _make_index_dir(tmp_path, "idx_a")
    idx_b = _make_index_dir(tmp_path, "idx_b")
    engine_a = ce.get_engine(idx_a)
    engine_b = ce.get_engine(idx_b)
    assert ce.get_engine(None) is engine_b
    assert ce.get_engine(idx_a) is engine_a  # path switch still cached
    assert ce.get_engine(None) is engine_a


def test_cache_is_bounded(tmp_path: Path) -> None:
    dirs = [
        _make_index_dir(tmp_path, f"idx_{i}") for i in range(ce._ENGINE_CACHE_MAX + 2)
    ]
    engines = [ce.get_engine(d) for d in dirs]
    assert len(ce._ENGINE_CACHE) == ce._ENGINE_CACHE_MAX
    # oldest entries were evicted, newest survive
    surviving = {id(sig_engine[1]) for sig_engine in ce._ENGINE_CACHE.values()}
    assert id(engines[-1]) in surviving
    assert id(engines[0]) not in surviving
