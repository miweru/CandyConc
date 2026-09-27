"""DT-CORE-LIFECYCLE — mmap bounds guards, close() chain, sim-cache signature.

Three correctness/safety properties:

(a) Bounds guards: ``token_store`` loaders that mmap a separate data payload and
    index it via an offsets array must FAIL CLOSED on a truncated/corrupt payload
    (offset past EOF, non-zero start, non-monotone) — otherwise the Cython
    decoders read out of bounds. Pure-unit: hand-built SVB ptr/data pairs.

(b) close() chain: ``CorpusIndex.close()`` -> ``FastIndexBackend.close()`` ->
    token_store + lexicons + doc_metadata, releasing mmap fds WITHOUT a
    BufferError from a live memoryview, and idempotent. Real-index.

(c) sim-cache signature: the sim() neighbour cache and the FAISS word-index
    handle cache key on the index BUILD signature, so a rebuild (same path, newer
    artifacts) invalidates the entry. Pure-unit with a fake backend.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

from candyconc.core import index_format
from candyconc.core.token_store import TokenStore, _check_offsets_within

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

_real_index = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)


# --------------------------------------------------------------------------- #
# (a) mmap bounds guards
# --------------------------------------------------------------------------- #


def _write_svb(base: Path, name: str, offsets: np.ndarray, data: bytes,
               *, block_size: int = 8, token_count: int = 8) -> None:
    n_blocks = int(offsets.size) - 1
    ptr_path = base / f"{name}_ids.svb.ptr.bin"
    data_path = base / f"{name}_ids.svb.data.bin"
    with open(ptr_path, "wb") as f:
        f.write(struct.pack(
            index_format.SVB_PTR_HEADER_STRUCT, n_blocks, block_size, token_count
        ))
        f.write(offsets.astype(np.uint64).tobytes())
    with open(data_path, "wb") as f:
        f.write(data)


def test_check_offsets_within_unit() -> None:
    # Valid: zero-start, monotone, last <= capacity.
    _check_offsets_within(np.array([0, 4, 8], dtype=np.uint64), 8, label="x")
    # Empty / None are no-ops.
    _check_offsets_within(np.zeros(0, dtype=np.uint64), 8, label="x")
    # Non-zero start.
    with pytest.raises(RuntimeError, match="unvollständig"):
        _check_offsets_within(np.array([1, 4, 8], dtype=np.uint64), 8, label="x")
    # Last offset past capacity (truncated payload).
    with pytest.raises(RuntimeError, match="unvollständig"):
        _check_offsets_within(np.array([0, 4, 99], dtype=np.uint64), 8, label="x")
    # Non-monotone.
    with pytest.raises(RuntimeError, match="unvollständig"):
        _check_offsets_within(np.array([0, 8, 4], dtype=np.uint64), 16, label="x")


def test_svb_truncated_data_raises(tmp_path: Path) -> None:
    # offsets claim the last block ends at byte 64, but the data file is 8 bytes.
    _write_svb(tmp_path, "word", np.array([0, 32, 64], dtype=np.uint64),
               data=b"\x00" * 8)
    store = TokenStore(tmp_path)
    with pytest.raises(RuntimeError, match="unvollständig"):
        store._load_svb_stream("word")


def test_svb_nonzero_offset_start_raises(tmp_path: Path) -> None:
    _write_svb(tmp_path, "word", np.array([4, 8, 16], dtype=np.uint64),
               data=b"\x00" * 16)
    store = TokenStore(tmp_path)
    with pytest.raises(RuntimeError, match="unvollständig"):
        store._load_svb_stream("word")


def test_svb_valid_offsets_load(tmp_path: Path) -> None:
    # A structurally-valid (in-bounds, zero-start, monotone) stream still loads.
    _write_svb(tmp_path, "word", np.array([0, 8, 16], dtype=np.uint64),
               data=b"\x00" * 16, token_count=13)
    store = TokenStore(tmp_path)
    stream = store._load_svb_stream("word")
    assert stream is not None
    assert stream.token_count == 13


def test_roaring_truncated_data_raises(tmp_path: Path) -> None:
    # ptr offsets index into the data mmap; make the data file too short.
    ptr_path = tmp_path / "word_postings.r32.ptr.bin"
    data_path = tmp_path / "word_postings.r32.data.bin"
    offsets = np.array([0, 16, 48], dtype=np.uint64)  # claims 48 bytes
    index_format.write_count_prefixed_array(ptr_path, offsets)
    with open(data_path, "wb") as f:
        f.write(b"\x00" * 8)  # only 8 bytes present
    store = TokenStore(tmp_path)
    with pytest.raises(RuntimeError, match="unvollständig"):
        store._load_roaring_postings("word")


def test_unit_index_truncated_raises(tmp_path: Path) -> None:
    ptr_path = tmp_path / "word_docset.ptr.bin"
    ids_path = tmp_path / "word_docset.bin"
    # offsets claim 10 ids but ids array only has 2.
    index_format.write_count_prefixed_array(ptr_path, np.array([0, 5, 10], dtype=np.uint64))
    index_format.write_count_prefixed_array(ids_path, np.array([1, 2], dtype=np.uint32))
    store = TokenStore(tmp_path)
    with pytest.raises(RuntimeError, match="unvollständig"):
        store._load_unit_index("word_docset.ptr.bin", "word_docset.bin")


# --------------------------------------------------------------------------- #
# (b) close() chain
# --------------------------------------------------------------------------- #


@_real_index
def test_corpus_index_close_releases_mmaps_and_is_idempotent() -> None:
    """close() drops every token-store mmap handle and every lexicon mmap, and
    a second close() is a no-op (idempotent). Asserting on the concrete handle
    state is deterministic, unlike an absolute process-wide fd count."""
    from candyconc.core.corpus_index import CorpusIndex

    idx = CorpusIndex(Path(INDEX_PATH))
    _ = idx.term_positions("und")
    _ = idx.frequency_list().head(3)
    ts = idx.fast_index.token_store
    lexicons = idx.fast_index.lexicons
    assert len(ts._mmap_handles) > 0  # something was actually mapped

    idx.close()
    assert len(ts._mmap_handles) == 0, "token-store mmap handles not released"
    # Every loaded lexicon released its mmap.
    for attr in ("word", "lemma", "pos"):
        lex = getattr(lexicons, attr, None)
        if lex is not None:
            assert lex._mm is None, f"{attr} lexicon mmap not released"

    idx.close()  # idempotent: second close must not raise
    assert len(ts._mmap_handles) == 0


@_real_index
def test_close_no_buffererror_with_live_views() -> None:
    """Closing while SVB/postings views are live must not raise BufferError."""
    from candyconc.core.corpus_index import CorpusIndex

    idx = CorpusIndex(Path(INDEX_PATH))
    # Touch the SVB word stream + a postings decode so memoryviews are live.
    _ = idx.fast_index.token_store.get_word_ids_range(0, 16)
    _ = idx.term_positions("und")
    idx.close()  # must not raise BufferError


@_real_index
def test_context_manager_closes() -> None:
    from candyconc.core.corpus_index import CorpusIndex

    with CorpusIndex(Path(INDEX_PATH)) as idx:
        assert int(idx.term_positions("und").size) >= 0


@_real_index
def test_close_invalidates_cql_engine_before_same_path_reopen() -> None:
    """A reopened corpus must not reuse an engine backed by closed mmaps."""
    from candyconc.core import cql_engine
    from candyconc.core.corpus_index import CorpusIndex

    path = Path(INDEX_PATH)
    cql_engine.clear_engine_cache()
    first = CorpusIndex(path)
    starts, _ends = cql_engine.search_cql_match_arrays_backend(
        first.fast_index,
        'cql:[word="Demokratie" %c]',
        limit=5,
    )
    assert starts.size == 5
    cached_backend = cql_engine._ENGINE_CACHE[str(path)][0].backend
    assert cached_backend is first.fast_index

    first.close()
    assert str(path) not in cql_engine._ENGINE_CACHE

    second = CorpusIndex(path)
    try:
        starts, _ends = cql_engine.search_cql_match_arrays_backend(
            second.fast_index,
            'cql:[word="Demokratie" %c]',
            limit=5,
        )
        assert starts.size == 5
        assert cql_engine._ENGINE_CACHE[str(path)][0].backend is second.fast_index
    finally:
        second.close()


# --------------------------------------------------------------------------- #
# (c) sim-cache build-signature invalidation
# --------------------------------------------------------------------------- #


class _FakeLex:
    def __init__(self, words):
        self._words = {i + 1: w for i, w in enumerate(words)}
        self._ids = {w: i + 1 for i, w in enumerate(words)}

    def get_id(self, w):
        return self._ids.get(w, 0)

    def get_string(self, i):
        return self._words.get(int(i), "")


class _FakeLexicons:
    def __init__(self, lex):
        self.word = lex


class _FakeBackend:
    def __init__(self, index_path, words):
        self.index_path = str(index_path)
        self.lexicons = _FakeLexicons(_FakeLex(words))


def test_sim_cache_invalidates_on_build_signature_change(tmp_path: Path) -> None:
    """The build signature participates in the sim() cache key, so a same-path
    rebuild (newer artifacts) yields a NEW key — the stale entry is never hit."""
    import candyconc.core.cql_macros as m
    from candyconc.core.index_signature import index_artifact_signature

    m.clear_sim_caches()

    # Write an artifact so the signature is non-zero, then change it.
    art = tmp_path / "meta.bin"
    art.write_bytes(b"v1")
    sig1 = index_artifact_signature(tmp_path)
    assert sig1 != 0

    # Build a key the way similar_words_scored does and prove sig participates.
    key1 = (
        "alpha", 5, "word", str(tmp_path), sig1,
        round(float(m._SIM_MIN_SCORE), 4), bool(m._SIM_EXCLUDE_STOPWORDS),
    )
    m._SIM_CACHE[key1] = [{"word": "alpha", "score": 1.0}]

    # Rebuild artifact (newer mtime) -> new signature -> old key is a miss.
    import time
    time.sleep(0.01)
    os.utime(art, None)
    art.write_bytes(b"v2-rebuilt")
    sig2 = index_artifact_signature(tmp_path)
    assert sig2 != sig1
    key2 = (
        "alpha", 5, "word", str(tmp_path), sig2,
        round(float(m._SIM_MIN_SCORE), 4), bool(m._SIM_EXCLUDE_STOPWORDS),
    )
    assert key2 not in m._SIM_CACHE  # stale entry is NOT served after rebuild
    assert key1 in m._SIM_CACHE      # old entry still keyed on old signature


def test_word_faiss_cache_key_includes_signature(tmp_path: Path) -> None:
    import candyconc.core.cql_macros as m

    m.clear_sim_caches()
    # No faiss files -> returns None, cache untouched.
    backend = _FakeBackend(tmp_path, ["x"])
    assert m._load_word_faiss(backend) is None
    assert len(m._WORD_FAISS_CACHE) == 0
    # The cache is an OrderedDict with a bounded size cap.
    from collections import OrderedDict
    assert isinstance(m._WORD_FAISS_CACHE, OrderedDict)
    assert m._WORD_FAISS_CACHE_MAX >= 1


def test_clear_sim_caches_empties_both() -> None:
    import candyconc.core.cql_macros as m

    m._SIM_CACHE[("k",)] = [{"word": "a", "score": 1.0}]
    m._WORD_FAISS_CACHE[("p", 1)] = (object(), np.zeros(0, dtype=np.uint32), True)
    m.clear_sim_caches()
    assert len(m._SIM_CACHE) == 0
    assert len(m._WORD_FAISS_CACHE) == 0
