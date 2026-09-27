"""B1 residual: anchor-position + refdoc caches must be rebuild-safe.

Two gaps left after the cache-signature wave:

1. ``_ANCHOR_POS_CACHE`` was keyed on the raw index path string, so an
   in-place rebuild (same path, new content) kept serving stale anchors. It is
   now keyed via ``_corpus_cache_signature`` (artifact mtimes).
2. Neither ``_ANCHOR_POS_CACHE`` nor ``_REFDOC_INDEX_CACHE`` was flushed by
   ``POST /system/clear-cache``.
"""

import os
from pathlib import Path

import httpx
import numpy as np
from fastapi.testclient import TestClient

from candyconc.services.backend import app, server

_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _DummyFastIndex:
    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        self.term_calls = 0

    def term_positions(self, term: str, attr: str = "word") -> np.ndarray:
        self.term_calls += 1
        return np.array([2, 5, 9], dtype=np.uint32)


class _DummyIndex:
    def __init__(self, index_path: Path):
        self.fast_index = _DummyFastIndex(index_path)


def test_clear_cache_flushes_anchor_and_refdoc_caches():
    client = TestClient(app)
    admin_token = client.post(
        "/api/v1/login", json={"username": "alice", "password": "alice"}
    ).json()["token"]

    server._anchor_positions_cache_set(
        ("sig-test", "haus", True),
        np.zeros(4, dtype=np.uint32),
        np.ones(4, dtype=np.int64),
    )
    server._REFDOC_INDEX_CACHE["clear-cache-corpus"] = {1: [1, 2]}
    server._REFDOC_INDEX_DOC_COUNT["clear-cache-corpus"] = 2
    assert len(server._ANCHOR_POS_CACHE) > 0
    assert server._ANCHOR_POS_CACHE_BYTES > 0

    resp = client.post("/api/v1/system/clear-cache", params={"token": admin_token})

    assert resp.status_code == 200
    assert len(server._ANCHOR_POS_CACHE) == 0
    assert server._ANCHOR_POS_CACHE_BYTES == 0
    assert server._REFDOC_INDEX_CACHE == {}
    assert server._REFDOC_INDEX_DOC_COUNT == {}


def test_anchor_cache_invalidated_by_in_place_rebuild(tmp_path):
    index_dir = tmp_path / "idx"
    index_dir.mkdir()
    meta = index_dir / "meta.bin"
    meta.write_bytes(b"build-1")
    idx = _DummyIndex(index_dir)

    first = server._resolve_term_anchor_positions(idx, "haus", within_sentence=False)
    again = server._resolve_term_anchor_positions(idx, "haus", within_sentence=False)
    assert idx.fast_index.term_calls == 1  # second call served from cache
    np.testing.assert_array_equal(first[0], again[0])

    # Simulate an in-place rebuild: same path, newer artifact mtime.
    stat = meta.stat()
    os.utime(meta, ns=(stat.st_atime_ns + 2_000_000_000, stat.st_mtime_ns + 2_000_000_000))

    server._resolve_term_anchor_positions(idx, "haus", within_sentence=False)
    assert idx.fast_index.term_calls == 2  # rebuild invalidated the cache entry
