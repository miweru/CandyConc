from __future__ import annotations

import numpy as np

from candyconc.core import fast_index_backend
from candyconc.core.fast_index_backend import FastIndexBackend, _DocPathLookup
from candyconc.core.fast_index_native import (
    bitset_positions_limit,
    kwic_compact_buffer_rows,
    kwic_rows_svb,
    kwic_rows_svb_compact_buffers,
    roaring_postings_to_bitset,
    union_roar_positions_limited,
)


def test_doc_path_lookup_reads_and_caches_values() -> None:
    class _Meta:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, idx: int, default=None):
            self.calls += 1
            if idx == 0:
                return {"path": "doc-a.txt"}
            if idx == 1:
                return {"doc_id": "doc-b"}
            return default

    meta = _Meta()
    lookup = _DocPathLookup(3, meta)

    assert len(lookup) == 3
    assert lookup[0] == "doc-a.txt"
    assert lookup[1] == "doc-b"
    assert lookup[2] == ""
    # Cached access should not hit metadata again.
    assert lookup[0] == "doc-a.txt"
    assert meta.calls == 3


def _svb_encode(values: list[int]) -> bytes:
    groups = (len(values) + 3) // 4
    controls = bytearray(groups)
    payload = bytearray()
    for g in range(groups):
        ctrl = 0
        for i in range(4):
            idx = g * 4 + i
            if idx >= len(values):
                break
            payload.append(int(values[idx]) & 0xFF)
            ctrl |= ((1 - 1) & 0x3) << (2 * i)
        controls[g] = ctrl
    return bytes(controls + payload)


def _lexicon_blob(strings: list[str]) -> tuple[np.ndarray, bytes]:
    blob = bytearray()
    offsets = [0, 0]
    for value in strings:
        blob.extend(value.encode("utf-8"))
        offsets.append(len(blob))
    return np.array(offsets, dtype=np.uint64), bytes(blob)


def _roar_bitmap_blob(positions: list[int], *, high16: int = 0) -> bytes:
    words = [0] * 1024
    for pos in positions:
        low = pos & 0xFFFF
        words[low >> 6] |= 1 << (low & 63)
    out = bytearray()
    out.extend((1).to_bytes(4, "little"))
    out.extend(int(high16).to_bytes(2, "little"))
    out.append(1)
    out.append(0)
    out.extend(len(positions).to_bytes(4, "little"))
    for word in words:
        out.extend(int(word).to_bytes(8, "little"))
    while len(out) % 8:
        out.append(0)
    return bytes(out)


def test_kwic_rows_svb_maps_doc_paths_for_sorted_and_unsorted_positions() -> None:
    values = [1, 2, 3, 4, 5, 6]
    blob = _svb_encode(values)
    lex_offsets, lex_blob = _lexicon_blob(["a", "b", "c", "d", "e", "f"])
    offsets = np.array([0, len(blob)], dtype=np.uint64)
    doc_bounds = np.array([0, 3], dtype=np.uint32)
    doc_paths = ["doc-a.txt", "doc-b.txt"]

    sorted_rows = kwic_rows_svb(
        np.array([1, 4], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        0,
        doc_bounds,
        doc_paths,
        lex_offsets,
        lex_blob,
    )
    unsorted_rows = kwic_rows_svb(
        np.array([4, 1], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        0,
        doc_bounds,
        doc_paths,
        lex_offsets,
        lex_blob,
    )

    assert [row["file"] for row in sorted_rows] == ["doc-a.txt", "doc-b.txt"]
    assert [row["file"] for row in unsorted_rows] == ["doc-b.txt", "doc-a.txt"]


def test_kwic_rows_svb_omits_file_when_disabled() -> None:
    values = [1, 2, 3]
    blob = _svb_encode(values)
    lex_offsets, lex_blob = _lexicon_blob(["a", "b", "c"])
    offsets = np.array([0, len(blob)], dtype=np.uint64)
    doc_bounds = np.array([0], dtype=np.uint32)

    rows = kwic_rows_svb(
        np.array([1], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        0,
        doc_bounds,
        ["doc-a.txt"],
        lex_offsets,
        lex_blob,
        include_file=False,
    )

    assert "file" not in rows[0]


def test_kwic_rows_svb_compact_rows_keep_doc_ids_without_file_paths() -> None:
    values = [1, 2, 3, 4, 5, 6]
    blob = _svb_encode(values)
    lex_offsets, lex_blob = _lexicon_blob(["a", "b", "c", "d", "e", "f"])
    offsets = np.array([0, len(blob)], dtype=np.uint64)
    doc_bounds = np.array([0, 3], dtype=np.uint32)

    rows = kwic_rows_svb(
        np.array([4, 1], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        0,
        doc_bounds,
        ["doc-a.txt", "doc-b.txt"],
        lex_offsets,
        lex_blob,
        include_file=False,
        compact=True,
    )

    assert rows == [
        ("", "e", "", 4, 1),
        ("", "b", "", 1, 0),
    ]


def test_kwic_rows_svb_compact_buffers_preserve_text_and_doc_ids() -> None:
    values = [1, 2, 3, 4, 5, 6]
    blob = _svb_encode(values)
    lex_offsets, lex_blob = _lexicon_blob(["a", "b", "c", "d", "e", "f"])
    offsets = np.array([0, len(blob)], dtype=np.uint64)
    doc_bounds = np.array([0, 3], dtype=np.uint32)

    buffers = kwic_rows_svb_compact_buffers(
        np.array([1, 4], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        1,
        doc_bounds,
        lex_offsets,
        lex_blob,
    )

    assert buffers is not None
    merged_texts = buffers["merged_texts"]
    positions = buffers["positions"]
    doc_ids = buffers["doc_ids"]
    row_merged_idx = buffers["row_merged_idx"]
    left_lo = buffers["left_lo"]
    left_hi = buffers["left_hi"]
    kw_lo = buffers["kw_lo"]
    kw_hi = buffers["kw_hi"]
    right_lo = buffers["right_lo"]
    right_hi = buffers["right_hi"]

    rows = []
    for i in range(len(positions)):
        merged = merged_texts[int(row_merged_idx[i])]
        rows.append(
            (
                merged[int(left_lo[i]):int(left_hi[i])] if int(left_lo[i]) >= 0 else "",
                merged[int(kw_lo[i]):int(kw_hi[i])] if int(kw_lo[i]) >= 0 else "",
                merged[int(right_lo[i]):int(right_hi[i])] if int(right_lo[i]) >= 0 else "",
                int(positions[i]),
                int(doc_ids[i]),
            )
        )

    assert rows == [
        ("a", "b", "c", 1, 0),
        ("d", "e", "f", 4, 1),
    ]


def test_kwic_compact_buffer_rows_materialize_expected_tuples() -> None:
    values = [1, 2, 3, 4, 5, 6]
    blob = _svb_encode(values)
    lex_offsets, lex_blob = _lexicon_blob(["a", "b", "c", "d", "e", "f"])
    offsets = np.array([0, len(blob)], dtype=np.uint64)
    doc_bounds = np.array([0, 3], dtype=np.uint32)

    buffers = kwic_rows_svb_compact_buffers(
        np.array([1, 4], dtype=np.uint32),
        offsets,
        blob,
        len(values),
        len(values),
        1,
        doc_bounds,
        lex_offsets,
        lex_blob,
    )

    assert buffers is not None
    assert kwic_compact_buffer_rows(buffers) == [
        ("a", "b", "c", 1, 0),
        ("d", "e", "f", 4, 1),
    ]


def test_roaring_postings_to_bitset_bitmap_container_matches_expected_bits() -> None:
    positions = [1, 63, 64, 130, 4097, 65535]
    blob = _roar_bitmap_blob(positions)
    offsets = np.array([0, 0, len(blob)], dtype=np.uint64)

    out = roaring_postings_to_bitset(
        offsets,
        blob,
        np.array([1], dtype=np.uint32),
        65536,
    )

    expected = np.zeros((65536 + 7) >> 3, dtype=np.uint8)
    for pos in positions:
        expected[pos >> 3] |= np.uint8(1 << (pos & 7))
    assert np.array_equal(out, expected)


def test_bitset_positions_limit_returns_sorted_prefix() -> None:
    bitset = np.zeros(4, dtype=np.uint8)
    for pos in (1, 5, 9, 17, 22):
        bitset[pos >> 3] |= np.uint8(1 << (pos & 7))
    out = bitset_positions_limit(bitset, 32, 3)
    np.testing.assert_array_equal(out, np.array([1, 5, 9], dtype=np.uint32))


def test_union_roar_positions_limited_returns_sorted_unique_prefix() -> None:
    blob_a = _roar_bitmap_blob([1, 5, 9])
    blob_b = _roar_bitmap_blob([5, 7, 11])
    blob = blob_a + blob_b
    offsets = np.array([0, 0, len(blob_a), len(blob)], dtype=np.uint64)
    out = union_roar_positions_limited(
        offsets,
        blob,
        np.array([1, 2], dtype=np.uint32),
        4,
    )
    np.testing.assert_array_equal(out, np.array([1, 5, 7, 9], dtype=np.uint32))


def test_kwic_compact_buffer_rows_shift_two_token_pivot_one() -> None:
    buffers = {
        "merged_texts": ["a b c d"],
        "positions": np.array([1], dtype=np.uint32),
        "row_merged_idx": np.array([0], dtype=np.int32),
        "left_lo": np.array([0], dtype=np.int32),
        "left_hi": np.array([1], dtype=np.int32),
        "kw_lo": np.array([2], dtype=np.int32),
        "kw_hi": np.array([3], dtype=np.int32),
        "right_lo": np.array([4], dtype=np.int32),
        "right_hi": np.array([7], dtype=np.int32),
        "doc_ids": np.array([0], dtype=np.int32),
    }
    assert kwic_compact_buffer_rows(buffers, two_token_pivot_one=True) == [
        ("a b", "c", "d", 2, 0),
    ]


def test_kwic_compact_buffer_rows_uses_prepared_two_token_offsets() -> None:
    buffers = {
        "merged_texts": ["a b c d"],
        "positions": np.array([1], dtype=np.uint32),
        "row_merged_idx": np.array([0], dtype=np.int32),
        "left_lo": np.array([0], dtype=np.int32),
        "left_hi": np.array([3], dtype=np.int32),
        "kw_lo": np.array([4], dtype=np.int32),
        "kw_hi": np.array([5], dtype=np.int32),
        "right_lo": np.array([6], dtype=np.int32),
        "right_hi": np.array([7], dtype=np.int32),
        "doc_ids": np.array([0], dtype=np.int32),
        "two_token_pivot_one_prepared": True,
    }
    assert kwic_compact_buffer_rows(buffers, two_token_pivot_one=True) == [
        ("a b", "c", "d", 2, 0),
    ]


def test_regex_ids_simple_prefix_skips_regex_compile(monkeypatch) -> None:
    class _Cache:
        def __init__(self) -> None:
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value) -> None:
            self.store[key] = value

    class _Lex:
        def __init__(self) -> None:
            self.offsets = np.array([0, 0], dtype=np.uint64)
            self.strings_view = memoryview(b"")

        def get_id(self, value: str) -> int:
            return 0

    backend = FastIndexBackend.__new__(FastIndexBackend)
    backend._regex_cache = _Cache()
    backend._prefix_all = {}
    backend._ngram_idx = {}
    backend._lexicon_for_attr = lambda attr: _Lex()
    backend._regex_candidates = lambda attr, pattern, min_len, max_len, **kwargs: None

    prefix_calls = []

    def _prefix(offsets, strings_view, literal, min_len, max_len):
        prefix_calls.append((literal, min_len, max_len))
        return np.array([7, 9], dtype=np.uint32)

    monkeypatch.setattr(fast_index_backend, "lexicon_match_prefix", _prefix)
    monkeypatch.setattr(
        fast_index_backend,
        "_compile_regex",
        lambda pattern: (_ for _ in ()).throw(AssertionError("_compile_regex should not run for simple prefix regex")),
    )

    out = FastIndexBackend._regex_ids(backend, "word", r"^un.*")

    np.testing.assert_array_equal(out, np.array([7, 9], dtype=np.uint32))
    assert prefix_calls == [("un", 2, None)]


def test_regex_ids_anchored_prefix_skips_regex_compile(monkeypatch) -> None:
    class _Cache:
        def __init__(self) -> None:
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value) -> None:
            self.store[key] = value

    class _Lex:
        def __init__(self) -> None:
            self.offsets = np.array([0, 0], dtype=np.uint64)
            self.strings_view = memoryview(b"")

        def get_id(self, value: str) -> int:
            return 0

    backend = FastIndexBackend.__new__(FastIndexBackend)
    backend._regex_cache = _Cache()
    backend._prefix_all = {}
    backend._ngram_idx = {}
    backend._lexicon_for_attr = lambda attr: _Lex()
    backend._regex_candidates = lambda attr, pattern, min_len, max_len, **kwargs: None

    prefix_calls = []

    def _prefix(offsets, strings_view, literal, min_len, max_len):
        prefix_calls.append((literal, min_len, max_len))
        return np.array([11, 13], dtype=np.uint32)

    monkeypatch.setattr(fast_index_backend, "lexicon_match_prefix", _prefix)
    monkeypatch.setattr(
        fast_index_backend,
        "_compile_regex",
        lambda pattern: (_ for _ in ()).throw(
            AssertionError("_compile_regex should not run for anchored simple prefix regex")
        ),
    )

    out = FastIndexBackend._regex_ids(backend, "word", r"^un.*$")

    np.testing.assert_array_equal(out, np.array([11, 13], dtype=np.uint32))
    assert prefix_calls == [("un", 2, None)]


def test_wildcard_positions_prefix_uses_simple_regex_fastpath(monkeypatch) -> None:
    class _Lex:
        def get_freqs_for_ids(self, ids):
            return np.array([1] * int(ids.size), dtype=np.int64)

    backend = FastIndexBackend.__new__(FastIndexBackend)
    backend._MAX_REGEX_POSITIONS = 5_000_000
    backend._lexicon_for_attr = lambda attr: _Lex()
    backend._union_positions_for_ids = lambda attr, ids: ids

    calls = []

    def _regex_ids(attr, pattern, *, cache_key=None):
        calls.append((attr, pattern, cache_key))
        return np.array([5, 9], dtype=np.uint32)

    backend._regex_ids = _regex_ids

    out = FastIndexBackend.wildcard_positions(backend, "un*")

    np.testing.assert_array_equal(out, np.array([5, 9], dtype=np.uint32))
    assert calls == [("word", r"^un.*$", ("word", "__wc__:^un.*$"))]


def test_regex_positions_with_limit_uses_limited_union(monkeypatch) -> None:
    class _Lex:
        def get_freqs_for_ids(self, ids):
            return np.ones(int(ids.size), dtype=np.int64)

    backend = FastIndexBackend.__new__(FastIndexBackend)
    backend._MAX_REGEX_POSITIONS = 5_000_000
    backend._lexicon_for_attr = lambda attr: _Lex()
    backend._regex_ids = lambda attr, pattern: np.array([3, 7, 9], dtype=np.uint32)
    backend._union_positions_for_ids = lambda attr, ids: (_ for _ in ()).throw(
        AssertionError("full union should not run when limit is provided")
    )
    backend._union_positions_for_ids_limited = lambda attr, ids, limit: np.array([11, 13], dtype=np.uint32)

    out = FastIndexBackend.regex_positions(backend, r".*ung$", limit=2)

    np.testing.assert_array_equal(out, np.array([11, 13], dtype=np.uint32))


def test_wildcard_positions_with_limit_uses_limited_union(monkeypatch) -> None:
    class _Lex:
        def get_freqs_for_ids(self, ids):
            return np.ones(int(ids.size), dtype=np.int64)

    backend = FastIndexBackend.__new__(FastIndexBackend)
    backend._MAX_REGEX_POSITIONS = 5_000_000
    backend._lexicon_for_attr = lambda attr: _Lex()
    backend._regex_ids = lambda attr, pattern, *, cache_key=None: np.array([5, 9], dtype=np.uint32)
    backend._union_positions_for_ids = lambda attr, ids: (_ for _ in ()).throw(
        AssertionError("full union should not run when limit is provided")
    )
    backend._union_positions_for_ids_limited = lambda attr, ids, limit: np.array([17, 23], dtype=np.uint32)

    out = FastIndexBackend.wildcard_positions(backend, "*ung", limit=2)

    np.testing.assert_array_equal(out, np.array([17, 23], dtype=np.uint32))


def test_limited_union_prefers_native_roaring_limit(monkeypatch) -> None:
    backend = FastIndexBackend.__new__(FastIndexBackend)

    class _TokenStore:
        token_count = 1024

        def get_roaring_postings(self, attr):
            return np.array([0, 0], dtype=np.uint64), b""

    backend.token_store = _TokenStore()
    backend._positions_for_id = lambda attr, tid: np.array([], dtype=np.uint32)
    backend._union_positions_for_ids = lambda attr, ids: (_ for _ in ()).throw(
        AssertionError("full union should not run")
    )
    called = {}

    monkeypatch.setattr(
        fast_index_backend,
        "union_roar_positions_limited",
        lambda offsets, data, ids, limit: called.setdefault(
            "result",
            np.array([3, 7], dtype=np.uint32),
        ),
    )

    out = FastIndexBackend._union_positions_for_ids_limited(
        backend,
        "word",
        np.arange(1, 300, dtype=np.uint32),
        2,
    )

    np.testing.assert_array_equal(out, np.array([3, 7], dtype=np.uint32))


def test_limited_union_falls_back_to_bitset_when_native_limit_fails(monkeypatch) -> None:
    backend = FastIndexBackend.__new__(FastIndexBackend)

    class _TokenStore:
        token_count = 1024

        def get_roaring_postings(self, attr):
            return np.array([0, 0], dtype=np.uint64), b""

    backend.token_store = _TokenStore()
    backend._positions_for_id = lambda attr, tid: np.array([], dtype=np.uint32)
    backend._union_positions_for_ids = lambda attr, ids: (_ for _ in ()).throw(
        AssertionError("full union should not run")
    )
    called = {}

    monkeypatch.setattr(
        fast_index_backend,
        "union_roar_positions_limited",
        lambda offsets, data, ids, limit: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    def _bitset(attr, ids, n_tokens):
        called["args"] = (attr, int(ids.size), n_tokens)
        out = np.zeros(128, dtype=np.uint8)
        for pos in (3, 7, 11):
            out[pos >> 3] |= np.uint8(1 << (pos & 7))
        return out

    backend._bitset_for_ids = _bitset

    out = FastIndexBackend._union_positions_for_ids_limited(
        backend,
        "word",
        np.arange(1, 300, dtype=np.uint32),
        2,
    )

    np.testing.assert_array_equal(out, np.array([3, 7], dtype=np.uint32))
    assert called["args"] == ("word", 299, 1024)


def test_sequence_positions_filters_anchor_once_and_keeps_u32(monkeypatch) -> None:
    backend = FastIndexBackend.__new__(FastIndexBackend)

    class _WordLex:
        def get_id(self, token: str) -> int:
            mapping = {"eins": 1, "zwei": 2, "drei": 3}
            return mapping.get(token, 0)

    class _Lexicons:
        word = _WordLex()

    class _TokenStore:
        token_count = 10

        def get_positions_for_word_id(self, word_id: int) -> np.ndarray:
            mapping = {
                1: np.array([1, 5, 9], dtype=np.uint32),
                2: np.array([2, 6, 9], dtype=np.uint32),
                3: np.array([3, 7], dtype=np.uint32),
            }
            return mapping[word_id]

    backend.lexicons = _Lexicons()
    backend.token_store = _TokenStore()

    calls: list[tuple[np.ndarray, np.ndarray, int, int]] = []

    def _fake_intersect_shifted(a, b, shift: int, max_pos: int) -> np.ndarray:
        calls.append((a.copy(), b.copy(), int(shift), int(max_pos)))
        return np.array([1, 5], dtype=np.uint32)

    monkeypatch.setattr(fast_index_backend, "_intersect_sorted_fast", object())
    monkeypatch.setattr(fast_index_backend, "intersect_shifted", _fake_intersect_shifted)

    out = FastIndexBackend.sequence_positions(backend, ["eins", "zwei", "drei"])

    np.testing.assert_array_equal(out, np.array([1, 5], dtype=np.uint32))
    assert len(calls) == 2
    first_a, first_b, first_shift, first_max_pos = calls[0]
    second_a, second_b, second_shift, second_max_pos = calls[1]
    np.testing.assert_array_equal(first_a, np.array([1, 5], dtype=np.uint32))
    np.testing.assert_array_equal(first_b, np.array([2, 6, 9], dtype=np.uint32))
    np.testing.assert_array_equal(second_a, np.array([1, 5], dtype=np.uint32))
    np.testing.assert_array_equal(second_b, np.array([3, 7], dtype=np.uint32))
    assert first_shift == 1
    assert second_shift == 2
    assert first_max_pos == 7
    assert second_max_pos == 7
    assert first_a.dtype == np.uint32
    assert first_b.dtype == np.uint32
