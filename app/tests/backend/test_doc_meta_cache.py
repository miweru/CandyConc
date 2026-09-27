from __future__ import annotations

import numpy as np
import candyconc.core.query_runtime as query_runtime
import candyconc.core.cql_engine as cql_engine
import candyconc.services.backend.server as backend_server

from candyconc.services.backend.server import (
    _apply_cql_two_token_pivot_one_rows,
    _doc_meta_for_doc_id,
    _enrich_compact_tuple_rows_with_doc_meta,
    _enrich_rows_with_doc_meta,
    _materialize_compact_buffer_rows_with_doc_meta,
    _prewarm_query_path,
    _query_rows_cql_fast,
    _query_rows_plain_fast,
    _query_rows_response_cache_get,
    _query_rows_response_cache_set,
    _query_stream_batch_cache_get,
    _query_stream_batch_cache_set,
    _shared_doc_meta_cache,
)


class _FastIndex:
    def __init__(self) -> None:
        self.doc_metadata = {
            7: {
                "path": "source::variant::model",
                "author": "Ada",
                "tags": ["x", "y"],
            }
        }
        self.token_store = type("_TokenStore", (), {"token_count": 100})()

    def doc_path_for_idx(self, doc_idx: int) -> str:
        return f"doc-{doc_idx}"

    def kwic_rows_for_positions(self, positions, ctx, include_arcs=False, include_file=False, compact=False):
        rows = []
        for pos in positions.tolist():
            doc_id = 0 if int(pos) < 10 else 1
            rows.append(("", f"kw-{int(pos)}", "", int(pos), doc_id))
        return rows

    def kwic_compact_buffers_for_positions(self, positions, ctx):
        pos_list = [int(pos) for pos in positions.tolist()]
        merged_texts = [f"kw-{pos}" for pos in pos_list]
        row_count = len(pos_list)
        return {
            "merged_texts": merged_texts,
            "positions": np.array(pos_list, dtype=np.uint32),
            "row_merged_idx": np.arange(row_count, dtype=np.int32),
            "left_lo": np.full(row_count, -1, dtype=np.int32),
            "left_hi": np.full(row_count, -1, dtype=np.int32),
            "kw_lo": np.zeros(row_count, dtype=np.int32),
            "kw_hi": np.array([len(text) for text in merged_texts], dtype=np.int32),
            "right_lo": np.full(row_count, -1, dtype=np.int32),
            "right_hi": np.full(row_count, -1, dtype=np.int32),
            "doc_ids": np.array([0 if pos < 10 else 1 for pos in pos_list], dtype=np.int32),
        }


class _Index:
    def __init__(self) -> None:
        self.fast_index = _FastIndex()


def test_doc_meta_shared_cache_reuses_canonical_entry() -> None:
    idx = _Index()

    first = _doc_meta_for_doc_id(idx, 7)
    second = _doc_meta_for_doc_id(idx, 7, file_label="source::variant::model")

    assert first is second
    assert _shared_doc_meta_cache(idx)[7] is first


def test_doc_meta_override_keeps_shared_canonical_entry() -> None:
    idx = _Index()

    canonical = _doc_meta_for_doc_id(idx, 7)
    override = _doc_meta_for_doc_id(idx, 7, file_label="other::demo::na")

    assert canonical[0] == "source::variant::model"
    assert override[0] == "source::variant::model"
    assert canonical is not override
    assert canonical[1]["source"] == "source"
    assert override[1]["source"] == "other"
    assert override[1]["variant"] == "demo"
    assert override[1]["author"] == "Ada"
    assert override[1]["tags"] == "x, y"


def test_doc_meta_prepared_entry_shortcuts_canonical_build() -> None:
    class _PreparedMeta(dict):
        def prepared_entry(self, idx: int):
            return ("prepared::variant::model", {"path": "prepared::variant::model", "doc_id": str(idx)})

    idx = _Index()
    idx.fast_index.doc_metadata = _PreparedMeta()

    canonical = _doc_meta_for_doc_id(idx, 7)

    assert canonical[0] == "prepared::variant::model"
    assert canonical[1]["doc_id"] == "7"


def test_enrich_rows_without_file_keeps_doc_but_omits_file() -> None:
    idx = _Index()
    rows = [{"pos": 1, "left": "", "kw": "x", "right": ""}]

    _enrich_rows_with_doc_meta(
        idx,
        rows,
        doc_bounds=np.array([0, 10], dtype=np.uint32),
        token_count=10,
        cache={},
        include_file=False,
    )

    assert rows[0]["doc"] == "doc-0"
    assert "file" not in rows[0]
    assert rows[0]["meta"]["doc_id"] == "0"


def test_enrich_compact_tuple_rows_uses_doc_ids_directly() -> None:
    idx = _Index()
    rows = [
        ("l1", "k1", "r1", 1, 0),
        ("l2", "k2", "r2", 8, 0, [1]),
        ("l3", "k3", "r3", 11, 1),
    ]

    enriched = _enrich_compact_tuple_rows_with_doc_meta(idx, rows)

    assert enriched[0]["doc_id"] == 0
    assert enriched[0]["doc"] == "doc-0"
    assert enriched[1]["match_offsets"] == [1]
    assert enriched[2]["doc_id"] == 1
    assert enriched[2]["meta"]["doc_id"] == "1"


def test_query_rows_cql_fast_enriches_compact_rows_and_offsets(monkeypatch) -> None:
    idx = _Index()
    idx.fast_index.doc_metadata = {
        0: {"path": "src::v0::m0"},
        1: {"path": "src::v1::m1"},
    }

    monkeypatch.setattr(query_runtime, "_resolve_cql_match_arrays", lambda *a, **k: (
        np.array([1, 11], dtype=np.uint32),
        2,
        None,
        True,
    ))
    monkeypatch.setattr(query_runtime, "_cql_pivot_index", lambda query: 0)
    monkeypatch.setattr(query_runtime, "_CQL_RESULTS_MAX", 2_000_000_000)
    monkeypatch.setattr(cql_engine, "normalize_cql_aliases", lambda query: query)

    rows = _query_rows_cql_fast(idx, 'cql:[word="x"] [word="y"]', ctx=5, limit=None)

    assert rows is not None
    assert len(rows) == 2
    assert rows[0]["doc_id"] == 0
    assert rows[1]["doc_id"] == 1
    assert rows[0]["match_offsets"] == [1]
    assert rows[1]["meta"]["path"] == "src::v1::m1"


def test_query_rows_cql_fast_passes_prepared_pivot_index(monkeypatch) -> None:
    idx = _Index()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        backend_server,
        "_prepare_cql_rows_fast",
        lambda *a, **k: (
            '[word="x"] [word="y"]',
            np.array([3, 9], dtype=np.uint32),
            2,
            None,
            1,
            2,
            True,
        ),
    )

    def _fake_render(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(backend_server, "_render_cql_fast_rows", _fake_render)

    rows = _query_rows_cql_fast(idx, 'cql:[word="x"] [word="y"]', ctx=5, limit=None)

    assert rows == []
    assert captured["pivot_index"] == 1
    assert captured["match_len_const"] == 2


def test_enrich_compact_rows_uses_match_lengths_without_row_offsets() -> None:
    idx = _Index()
    idx.fast_index.doc_metadata = {
        0: {"path": "src::v0::m0"},
    }
    rows = [
        ("l1", "k1", "r1", 1, 0),
        ("l2", "k2", "r2", 2, 0),
        ("l3", "k3", "r3", 3, 0),
    ]

    enriched = _enrich_compact_tuple_rows_with_doc_meta(
        idx,
        rows,
        match_lengths=np.array([1, 3, 2], dtype=np.int32),
        row_has_offsets=False,
    )

    assert "match_offsets" not in enriched[0]
    assert enriched[1]["match_offsets"] == [1, 2]
    assert enriched[2]["match_offsets"] == [1]


def test_apply_cql_two_token_pivot_one_rows_shifts_rows_in_place() -> None:
    rows = [
        {"left": "a", "kw": "und", "right": "ist b", "pos": 10},
        {"left": "", "kw": "oder", "right": "ist", "pos": 20},
    ]

    _apply_cql_two_token_pivot_one_rows(rows)

    assert rows == [
        {"left": "a und", "kw": "ist", "right": "b", "pos": 11, "match_offsets": [-1]},
        {"left": "oder", "kw": "ist", "right": "", "pos": 21, "match_offsets": [-1]},
    ]


def test_materialize_compact_buffer_rows_shifts_two_token_pivot_one() -> None:
    idx = _Index()
    idx.fast_index.doc_metadata = {0: {"path": "src::v0::m0"}}
    buffers = {
        "merged_texts": ["a und ist b", "oder ist"],
        "positions": np.array([10, 20], dtype=np.uint32),
        "row_merged_idx": np.array([0, 1], dtype=np.int32),
        "left_lo": np.array([0, -1], dtype=np.int32),
        "left_hi": np.array([1, -1], dtype=np.int32),
        "kw_lo": np.array([2, 0], dtype=np.int32),
        "kw_hi": np.array([5, 4], dtype=np.int32),
        "right_lo": np.array([6, 5], dtype=np.int32),
        "right_hi": np.array([11, 8], dtype=np.int32),
        "doc_ids": np.array([0, 0], dtype=np.int32),
    }

    rows = _materialize_compact_buffer_rows_with_doc_meta(
        idx,
        buffers,
        two_token_pivot_one=True,
    )

    assert rows == [
        {
            "left": "a und",
            "kw": "ist",
            "right": "b",
            "pos": 11,
            "doc_id": 0,
            "doc": "src::v0::m0",
            "meta": {"path": "src::v0::m0", "doc_id": "0", "source": "src", "variant": "v0", "model": "m0"},
            "match_offsets": [-1],
        },
        {
            "left": "oder",
            "kw": "ist",
            "right": "",
            "pos": 21,
            "doc_id": 0,
            "doc": "src::v0::m0",
            "meta": {"path": "src::v0::m0", "doc_id": "0", "source": "src", "variant": "v0", "model": "m0"},
            "match_offsets": [-1],
        },
    ]


def test_materialize_compact_buffer_rows_uses_complete_query_cache_list() -> None:
    class _QueryMetaList:
        def __init__(self) -> None:
            self._query_cache = [
                ("doc-0", {"path": "doc-0", "doc_id": "0"}),
                ("doc-1", {"path": "doc-1", "doc_id": "1"}),
            ]
            self._query_cache_complete = True

        def query_entries_many(self, doc_ids):
            raise AssertionError("query_entries_many should not run with complete query cache")

    idx = _Index()
    idx.fast_index.doc_metadata = _QueryMetaList()
    buffers = {
        "merged_texts": ["l0 k0 r0", "l1 k1 r1"],
        "positions": np.array([10, 20], dtype=np.uint32),
        "row_merged_idx": np.array([0, 1], dtype=np.int32),
        "left_lo": np.array([0, 0], dtype=np.int32),
        "left_hi": np.array([2, 2], dtype=np.int32),
        "kw_lo": np.array([3, 3], dtype=np.int32),
        "kw_hi": np.array([5, 5], dtype=np.int32),
        "right_lo": np.array([6, 6], dtype=np.int32),
        "right_hi": np.array([8, 8], dtype=np.int32),
        "doc_ids": np.array([0, 1], dtype=np.int32),
    }

    rows = _materialize_compact_buffer_rows_with_doc_meta(idx, buffers)

    assert rows[0]["doc"] == "doc-0"
    assert rows[0]["meta"]["doc_id"] == "0"
    assert rows[1]["doc"] == "doc-1"
    assert rows[1]["meta"]["doc_id"] == "1"


def test_query_rows_plain_fast_enriches_compact_rows(monkeypatch) -> None:
    import candyconc.domain.query_eval as query_eval

    idx = _Index()
    idx.fast_index.doc_metadata = {
        0: {"path": "src::v0::m0"},
        1: {"path": "src::v1::m1"},
    }
    monkeypatch.setattr(
        query_eval,
        "prefetch_positions_window",
        lambda query, index, **kwargs: (np.array([1, 11], dtype=np.uint32), True),
    )

    rows = _query_rows_plain_fast(idx, "x", ctx=5, limit=None)

    assert rows is not None
    assert len(rows) == 2
    assert rows[0]["doc_id"] == 0
    assert rows[1]["doc_id"] == 1
    assert rows[0]["kw"] == "kw-1"
    assert rows[1]["meta"]["path"] == "src::v1::m1"


def test_query_rows_plain_fast_chunks_large_results(monkeypatch) -> None:
    import candyconc.domain.query_eval as query_eval

    idx = _Index()
    monkeypatch.setattr(
        query_eval,
        "prefetch_positions_window",
        lambda query, index, **kwargs: (np.arange(1, 2506, dtype=np.uint32), True),
    )
    monkeypatch.setattr(backend_server, "get_config", lambda key, default=None: {"CANDYCONC_QUERY_FAST_CHUNK_THRESHOLD": "2", "CANDYCONC_QUERY_FAST_CHUNK_SIZE": "2"}.get(key, default))
    calls: list[list[int]] = []

    def _fake_render(index, *, positions, ctx, prepared_cache=None, fixed_match_offsets=None):
        calls.append(positions.tolist())
        return [{"kw": f"kw-{int(pos)}", "pos": int(pos)} for pos in positions.tolist()]

    monkeypatch.setattr(backend_server, "_render_fast_rows_for_positions", _fake_render)

    rows = _query_rows_plain_fast(idx, "x", ctx=5, limit=None)

    assert rows is not None
    assert rows[0]["pos"] == 1
    assert rows[-1]["pos"] == 2505
    assert len(rows) == 2505
    assert [len(call) for call in calls] == [1000, 1000, 505]


def test_query_rows_plain_fast_uses_window_limit(monkeypatch) -> None:
    import candyconc.domain.query_eval as query_eval

    idx = _Index()
    seen: dict[str, object] = {}

    def _fake_window(query, index, **kwargs):
        seen["query"] = query
        seen.update(kwargs)
        return np.array([11, 12], dtype=np.uint32), False

    monkeypatch.setattr(query_eval, "prefetch_positions_window", _fake_window)

    rows = _query_rows_plain_fast(idx, "x", ctx=5, limit=2)

    assert rows is not None
    assert len(rows) == 2
    assert seen["query"] == "x"
    assert seen["limit"] == 2


def test_prewarm_query_path_warms_query_meta_in_chunks(monkeypatch) -> None:
    import candyconc.core.cql_engine as cql_engine_mod

    class _Engine:
        def __init__(self) -> None:
            self.dense_calls: list[tuple[str, int]] = []

        def _dense_bitset_for_type(self, attr: str, tid: int):
            self.dense_calls.append((attr, int(tid)))
            return object() if tid % 2 == 1 else None

    class _MetaStore:
        def __init__(self) -> None:
            self.query_calls: list[list[int]] = []
            self.prepared_calls: list[list[int]] = []
            self._query_cache = [None] * 10

        def query_entries_many(self, doc_ids):
            vals = list(doc_ids)
            self.query_calls.append(vals)
            return [("", {}) for _ in vals]

        def prepared_entries_many(self, doc_ids):
            vals = list(doc_ids)
            self.prepared_calls.append(vals)
            return [("", {}) for _ in vals]

    class _FastIndexForPrewarm:
        def __init__(self) -> None:
            self.index_path = "/tmp/prewarm-index"
            self.token_store = type(
                "_TokenStore",
                (),
                {
                    "__init__": lambda self: setattr(self, "position_calls", []),
                    "get_positions_for_word_id": lambda self, tid: (
                        self.position_calls.append(int(tid)) or np.array([int(tid)], dtype=np.uint32)
                    ),
                },
            )()
            self.doc_metadata = _MetaStore()
            self.lexicons = type(
                "_Lex",
                (),
                {"word": type("_WordLex", (), {"top_global_ids": [0, 1, 2, 3, 4, 5]})()},
            )()

    idx = type("_Index", (), {"fast_index": _FastIndexForPrewarm()})()
    engine = _Engine()
    corpus_calls: list[str] = []
    cql_calls: list[tuple[str, int, int | None]] = []
    plain_calls: list[tuple[str, int, int | None]] = []
    response_cache_sets: list[tuple[tuple[object, ...], bytes]] = []

    class _Corpus:
        def token_to_sent(self):
            corpus_calls.append("token_to_sent")
            return object()

        def sent_to_doc(self):
            corpus_calls.append("sent_to_doc")
            return np.array([0], dtype=np.int32)

    monkeypatch.setattr(cql_engine_mod, "_get_engine", lambda backend: (_Corpus(), engine))
    monkeypatch.setattr(backend_server, "_doc_bounds_for_index", lambda _idx: np.arange(10, dtype=np.uint32))
    monkeypatch.setattr(
        backend_server,
        "_query_rows_cql_fast",
        lambda idx, term, ctx, limit: cql_calls.append((term, int(ctx), limit)) or [("l", "k", "r", 1, 0)],
    )
    monkeypatch.setattr(
        backend_server,
        "_query_rows_plain_fast",
        lambda idx, term, ctx, limit: plain_calls.append((term, int(ctx), limit)) or [("l", "k", "r", 1, 0)],
    )
    monkeypatch.setattr(
        backend_server,
        "_enrich_compact_tuple_rows_with_doc_meta",
        lambda idx, rows, row_has_offsets=False: [{"left": "l", "kw": "k", "right": "r", "pos": 1, "doc": "d", "meta": {}}],
    )
    monkeypatch.setattr(
        backend_server,
        "_json_dumps_fast_bytes",
        lambda payload: b"payload",
    )
    monkeypatch.setattr(
        backend_server,
        "_query_rows_response_cache_set",
        lambda key, payload: response_cache_sets.append((key, payload)),
    )
    monkeypatch.setattr(
        backend_server,
        "get_config",
        lambda key, default=None: {
            "CANDYCONC_PREWARM_QUERY_META_MAX_DOCS": "10",
            "CANDYCONC_PREWARM_QUERY_META_BATCH": "4",
            "CANDYCONC_PREWARM_DOC_META": "3",
            "CANDYCONC_PREWARM_KWIC_STRINGS": "0",
            "CANDYCONC_PREWARM_DENSE_WORD_BITSETS": "2",
            "CANDYCONC_PREWARM_WORD_POSITIONS": "2",
            "CANDYCONC_PREWARM_SHAPE_QUERIES": "1",
            "CANDYCONC_PREWARM_SHAPE_LIMIT": "123",
            "CANDYCONC_PREWARM_SHAPE_RESPONSES": "1",
        }.get(key, default),
    )

    _prewarm_query_path(idx)

    assert idx.fast_index.doc_metadata.query_calls == [
        [0, 1, 2, 3],
        [4, 5, 6, 7],
        [8, 9],
    ]
    assert idx.fast_index.doc_metadata._query_cache_complete is True
    assert idx.fast_index.doc_metadata.prepared_calls == [[0, 1, 2]]
    assert engine.dense_calls == [("word", 1), ("word", 2), ("word", 3)]
    assert idx.fast_index.token_store.position_calls == [1, 2]
    assert corpus_calls == ["token_to_sent", "sent_to_doc"]
    assert cql_calls == [
        ('cql:[word~"^un.*"] [word="ist"]', 5, None),
        ('cql:within(<s>, [word="und"]+ [word="ist"])', 5, None),
        ('cql:[word="und"] ([word="der"]|[word="die"]){0,30} [word="ist"]', 5, None),
    ]
    assert plain_calls == [
        ("*ung", 5, 123),
        ("*lich*", 5, 123),
        ("un*", 5, 123),
    ]
    assert [item[0] for item in response_cache_sets] == [
        ("/tmp/prewarm-index", 'cql:[word~"^un.*"] [word="ist"]', 5, "", "", -1),
        ("/tmp/prewarm-index", 'cql:within(<s>, [word="und"]+ [word="ist"])', 5, "", "", -1),
        ("/tmp/prewarm-index", 'cql:[word="und"] ([word="der"]|[word="die"]){0,30} [word="ist"]', 5, "", "", -1),
        ("/tmp/prewarm-index", "*ung", 5, "", "", 123),
        ("/tmp/prewarm-index", "*lich*", 5, "", "", 123),
        ("/tmp/prewarm-index", "un*", 5, "", "", 123),
    ]


def test_compact_meta_enrichment_prefers_query_entries_many() -> None:
    class _QueryMeta(dict):
        def __init__(self):
            super().__init__({0: {"path": "src::v0::m0"}, 1: {"path": "src::v1::m1"}})
            self.calls: list[list[int]] = []

        def query_entries_many(self, doc_ids):
            ids = [int(doc_id) for doc_id in doc_ids]
            self.calls.append(ids)
            return [(f"doc-{doc_id}", {"path": f"doc-{doc_id}", "doc_id": str(doc_id)}) for doc_id in ids]

        def prepared_entries_many(self, doc_ids):
            raise AssertionError("prepared_entries_many should not be used when query_entries_many is available")

    idx = _Index()
    meta_store = _QueryMeta()
    idx.fast_index.doc_metadata = meta_store
    rows = [("l1", "k1", "r1", 1, 0), ("l2", "k2", "r2", 11, 1)]

    enriched = _enrich_compact_tuple_rows_with_doc_meta(idx, rows)

    assert meta_store.calls == [[0, 1]]
    assert enriched[0]["meta"]["doc_id"] == "0"
    assert enriched[1]["meta"]["path"] == "doc-1"


def test_compact_meta_enrichment_reuses_query_cache_list() -> None:
    class _QueryMetaList:
        def __init__(self) -> None:
            self._query_cache = [
                ("doc-0", {"path": "doc-0", "doc_id": "0"}),
                None,
            ]
            self.calls: list[list[int]] = []

        def query_entries_many(self, doc_ids):
            ids = [int(doc_id) for doc_id in doc_ids]
            self.calls.append(ids)
            return [(f"doc-{doc_id}", {"path": f"doc-{doc_id}", "doc_id": str(doc_id)}) for doc_id in ids]

    idx = _Index()
    meta_store = _QueryMetaList()
    idx.fast_index.doc_metadata = meta_store
    rows = [("l1", "k1", "r1", 1, 0), ("l2", "k2", "r2", 11, 1)]

    enriched = _enrich_compact_tuple_rows_with_doc_meta(idx, rows)

    assert meta_store.calls == [[1]]
    assert enriched[0]["meta"]["doc_id"] == "0"
    assert enriched[1]["meta"]["doc_id"] == "1"


def test_compact_meta_enrichment_skips_lookup_when_query_cache_complete() -> None:
    class _QueryMetaList:
        def __init__(self) -> None:
            self._query_cache = [
                ("doc-0", {"path": "doc-0", "doc_id": "0"}),
                ("doc-1", {"path": "doc-1", "doc_id": "1"}),
            ]
            self._query_cache_complete = True
            self.calls: list[list[int]] = []

        def query_entries_many(self, doc_ids):
            ids = [int(doc_id) for doc_id in doc_ids]
            self.calls.append(ids)
            return [(f"doc-{doc_id}", {"path": f"doc-{doc_id}", "doc_id": str(doc_id)}) for doc_id in ids]

    idx = _Index()
    meta_store = _QueryMetaList()
    idx.fast_index.doc_metadata = meta_store
    rows = [("l1", "k1", "r1", 1, 0), ("l2", "k2", "r2", 11, 1)]

    enriched = _enrich_compact_tuple_rows_with_doc_meta(idx, rows)

    assert meta_store.calls == []
    assert enriched[0]["meta"]["doc_id"] == "0"
    assert enriched[1]["meta"]["doc_id"] == "1"


def test_compact_meta_enrichment_bypasses_resolve_when_query_cache_complete(monkeypatch) -> None:
    class _QueryMetaList:
        def __init__(self) -> None:
            self._query_cache = [
                ("doc-0", {"path": "doc-0", "doc_id": "0"}),
                ("doc-1", {"path": "doc-1", "doc_id": "1"}),
            ]
            self._query_cache_complete = True

    idx = _Index()
    idx.fast_index.doc_metadata = _QueryMetaList()
    rows = [("l1", "k1", "r1", 1, 0), ("l2", "k2", "r2", 11, 1)]

    monkeypatch.setattr(
        backend_server,
        "_resolve_query_meta_lookup",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not resolve")),
    )

    enriched = _enrich_compact_tuple_rows_with_doc_meta(idx, rows)

    assert enriched[0]["meta"]["doc_id"] == "0"
    assert enriched[1]["meta"]["doc_id"] == "1"


def test_query_rows_response_cache_roundtrip() -> None:
    # Real contract: _query_rows_response_cache_set(key, payload, headers=None)
    # and _query_rows_response_cache_get returns (payload, headers)
    # (src/candyconc/services/backend/server.py:230-258).
    key = ("idx", "term", 5, "", "", -1)
    payload = b'[{"kw":"und"}]'
    headers = {"X-Total-Count": "1"}

    _query_rows_response_cache_set(key, payload, headers)

    assert _query_rows_response_cache_get(key) == (payload, headers)


def test_query_stream_batch_cache_roundtrip() -> None:
    # Real contract: the stream batch cache also records the keyword-only
    # `truncated` flag, and the getter returns a 5-tuple
    # (batches, total, partial, next_offset, truncated)
    # (src/candyconc/services/backend/server.py:339-357).
    key = ("idx", "term", 5, "", "", "", 50, -1, 0)
    batches = [(b'[{"kw":"und"}]', 1), (b'[{"kw":"oder"}]', 1)]

    _query_stream_batch_cache_set(
        key,
        batches,
        total=2,
        partial=False,
        next_offset=None,
        truncated=False,
    )

    assert _query_stream_batch_cache_get(key) == (batches, 2, False, None, False)
