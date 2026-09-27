import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import server


_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class _FakeFastIndex:
    index_path = "fake-query-bounds"


class _FakeIndex:
    fast_index = _FakeFastIndex()


def _fake_index_with_doc_bounds(bounds: np.ndarray):
    document = SimpleNamespace(_positions=np.asarray(bounds, dtype=np.uint32))
    boundaries = SimpleNamespace(document=document)
    fast_index = SimpleNamespace(index_path="fake-docset-index", boundaries=boundaries)
    return SimpleNamespace(fast_index=fast_index)


def _fake_index_with_doc_meta(bounds: np.ndarray, metadata: dict[int, dict[str, str]]):
    document = SimpleNamespace(_positions=np.asarray(bounds, dtype=np.uint32))
    boundaries = SimpleNamespace(document=document)
    fast_index = SimpleNamespace(
        index_path="fake-doc-meta-index",
        boundaries=boundaries,
        doc_metadata=metadata,
        token_store=SimpleNamespace(token_count=int(np.asarray(bounds)[-1])),
    )
    fast_index.doc_path_for_idx = lambda doc_id: f"doc-{int(doc_id)}"

    def _literal_metadata_fallback(*_args, **_kwargs):
        raise AssertionError("CQL mit Metadatenfilter darf nicht als Literal-Wortsuche laufen")

    return SimpleNamespace(fast_index=fast_index, query_metadata=_literal_metadata_fallback)


def _stream_done_payload(client: TestClient, params: dict) -> tuple[dict, str]:
    current_event = None
    done_payload = None
    trace_id = ""
    with client.stream("GET", "/api/v1/query/stream", params=params) as resp:
        assert resp.status_code == 200
        trace_id = resp.headers["x-candyconc-query-trace-id"]
        assert trace_id.startswith("qtr_")
        for raw_line in resp.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line[7:].strip()
                continue
            if current_event == "done" and line.startswith("data: "):
                done_payload = json.loads(line[6:])
                break
    assert done_payload is not None
    return done_payload, trace_id


def _reset_query_caches():
    server._QUERY_ROWS_RESPONSE_CACHE.clear()
    server._QUERY_STREAM_BATCH_CACHE.clear()
    server._metadata_filter_mask_cache_clear()
    server._QUERY_ROWS_RESPONSE_CACHE_BYTES = 0
    server._QUERY_STREAM_BATCH_CACHE_BYTES = 0


def test_query_without_limit_uses_default_cap_and_reports_truncation(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))
    monkeypatch.setattr(server, "get_config", lambda key, default=None: "2" if key == "CANDYCONC_QUERY_DEFAULT_LIMIT" else default)

    calls = []

    def fake_cql_rows(idx, term, *, ctx, limit):
        calls.append({"ctx": ctx, "limit": limit})
        return [
            {"left": "", "kw": "a", "right": "", "pos": 1},
            {"left": "", "kw": "b", "right": "", "pos": 2},
            {"left": "", "kw": "c", "right": "", "pos": 3},
        ]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get("/api/v1/query", params={"term": "bounded-default", "ctx": 1000})

    assert resp.status_code == 200
    assert [row["kw"] for row in resp.json()] == ["a", "b"]
    assert calls == [{"ctx": 600, "limit": 3}]
    assert resp.headers["x-candyconc-limit"] == "2"
    assert resp.headers["x-candyconc-limit-defaulted"] == "true"
    assert resp.headers["x-candyconc-context"] == "600"
    assert resp.headers["x-candyconc-truncated"] == "true"
    assert resp.headers["x-candyconc-next-offset"] == "2"
    first_trace_id = resp.headers["x-candyconc-query-trace-id"]
    assert first_trace_id.startswith("qtr_")

    cached_resp = client.get("/api/v1/query", params={"term": "bounded-default", "ctx": 1000})
    assert cached_resp.status_code == 200
    assert cached_resp.json() == resp.json()
    assert calls == [{"ctx": 600, "limit": 3}]
    assert cached_resp.headers["x-candyconc-query-trace-id"].startswith("qtr_")
    assert cached_resp.headers["x-candyconc-query-trace-id"] != first_trace_id


def test_query_clamps_negative_context(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))

    calls = []

    def fake_cql_rows(idx, term, *, ctx, limit):
        calls.append({"ctx": ctx, "limit": limit})
        return [{"left": "", "kw": "a", "right": "", "pos": 1}]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get("/api/v1/query", params={"term": "negative-context", "ctx": -50, "limit": 1})

    assert resp.status_code == 200
    assert calls == [{"ctx": 0, "limit": 2}]
    assert resp.headers["x-candyconc-context"] == "0"
    assert resp.headers["x-candyconc-truncated"] == "false"


def test_query_stream_without_limit_uses_default_scan_limit(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))
    monkeypatch.setattr(server, "get_config", lambda key, default=None: "2" if key == "CANDYCONC_QUERY_DEFAULT_LIMIT" else default)
    monkeypatch.setattr(server, "_prepare_cql_rows_fast", lambda *args, **kwargs: None)
    async def fake_get_or_create_query_count(*args, **kwargs):
        return None

    monkeypatch.setattr(server, "_get_or_create_query_count", fake_get_or_create_query_count)

    calls = []

    def fake_prepare_plain(idx, term, *, offset, limit, docset_mask, case_insensitive=True):
        calls.append({"offset": offset, "limit": limit})
        return "stream-default", np.array([1, 2, 3], dtype="uint32"), 3, False

    def fake_render_rows(idx, *, positions, ctx):
        return [
            {"left": "", "kw": f"r{int(pos)}", "right": "", "pos": int(pos)}
            for pos in positions.tolist()
        ]

    monkeypatch.setattr(server, "_prepare_plain_rows_fast", fake_prepare_plain)
    monkeypatch.setattr(server, "_render_fast_rows_for_positions", fake_render_rows)

    client = TestClient(server.app)
    done_payload, trace_id = _stream_done_payload(
        client,
        {"term": "stream-default", "ctx": 5, "batch_size": 1},
    )

    assert calls == [{"offset": 0, "limit": 3}]
    assert done_payload["limit"] == 2
    assert done_payload["limit_defaulted"] is True
    assert done_payload["truncated"] is True
    assert done_payload["partial"] is True
    assert done_payload["next_offset"] == 2
    assert done_payload["queryTraceId"] == trace_id

    cached_done_payload, cached_trace_id = _stream_done_payload(
        client,
        {"term": "stream-default", "ctx": 5, "batch_size": 1},
    )
    assert calls == [{"offset": 0, "limit": 3}]
    assert cached_done_payload["queryTraceId"] == cached_trace_id
    assert cached_trace_id != trace_id
    assert cached_done_payload["total"] == done_payload["total"]
    assert cached_done_payload["next_offset"] == done_payload["next_offset"]


def test_query_offset_pages_on_backend_and_reports_next_offset(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))

    calls = []

    def fake_cql_rows(idx, term, *, ctx, limit):
        calls.append({"ctx": ctx, "limit": limit})
        return [
            {"left": "", "kw": f"r{i}", "right": "", "pos": i}
            for i in range(6)
        ][:limit]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get("/api/v1/query", params={"term": "page", "offset": 2, "limit": 2})

    assert resp.status_code == 200
    assert [row["kw"] for row in resp.json()] == ["r2", "r3"]
    assert calls == [{"ctx": 5, "limit": 5}]
    assert resp.headers["x-candyconc-truncated"] == "true"
    assert resp.headers["x-candyconc-next-offset"] == "4"
    assert "x-candyconc-total" not in resp.headers

    cached = client.get("/api/v1/query", params={"term": "page", "offset": 2, "limit": 2})
    assert cached.status_code == 200
    assert cached.json() == resp.json()
    assert calls == [{"ctx": 5, "limit": 5}]


def test_query_position_sort_does_not_trigger_sort_scan_cap(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))
    monkeypatch.setattr(server, "_kwic_sort_scan_cap", lambda: 1234)

    calls = []

    def fake_cql_rows(idx, term, *, ctx, limit):
        calls.append({"ctx": ctx, "limit": limit})
        return [
            {"left": "", "kw": "a", "right": "", "pos": 1},
            {"left": "", "kw": "b", "right": "", "pos": 2},
            {"left": "", "kw": "c", "right": "", "pos": 3},
        ]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get("/api/v1/query", params={"term": "position-sort", "sort_by": "position", "limit": 2})

    assert resp.status_code == 200
    assert calls == [{"ctx": 5, "limit": 3}]
    assert [row["kw"] for row in resp.json()] == ["a", "b"]
    assert "x-candyconc-total" not in resp.headers


def test_sorted_query_marks_prefix_scan_as_incomplete(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))
    monkeypatch.setattr(server, "_kwic_sort_scan_cap", lambda: 3)

    calls = []

    def fake_cql_rows(idx, term, *, ctx, limit):
        calls.append({"ctx": ctx, "limit": limit})
        rows = [
            {"left": "", "kw": "delta", "right": "", "pos": 1},
            {"left": "", "kw": "charlie", "right": "", "pos": 2},
            {"left": "", "kw": "bravo", "right": "", "pos": 3},
            {"left": "", "kw": "alpha", "right": "", "pos": 4},
        ]
        return rows[:limit]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get(
        "/api/v1/query",
        params={"term": "sorted-prefix", "sort_by": "node", "limit": 5},
    )

    assert resp.status_code == 200
    assert calls == [{"ctx": 5, "limit": 4}]
    assert [row["kw"] for row in resp.json()] == ["bravo", "charlie", "delta"]
    assert resp.headers["x-candyconc-sort-approximate"] == "true"
    assert resp.headers["x-candyconc-truncated"] == "true"
    assert resp.headers["x-candyconc-next-offset"] == "3"
    assert "x-candyconc-total" not in resp.headers


def test_prepare_plain_rows_filters_sparse_docset_before_page_cap(monkeypatch):
    idx = _fake_index_with_doc_bounds(np.array([0, 10, 20], dtype=np.uint32))
    all_positions = np.array([2, 12, 22], dtype=np.uint32)
    calls = []

    def fake_prefetch(term, idx_arg, *, limit, offset, use_cache, allow_cache_fallback):
        calls.append({"limit": limit, "offset": offset})
        start = int(offset)
        stop = None if limit is None else start + int(limit)
        return all_positions[start:stop], limit is None

    monkeypatch.setattr("candyconc.domain.query_eval.prefetch_positions_window", fake_prefetch)

    prepared = server._prepare_plain_rows_fast(
        idx,
        "needle",
        offset=0,
        limit=1,
        docset_mask=np.array([False, False, True], dtype=np.bool_),
    )

    assert calls == [{"limit": None, "offset": 0}]
    assert prepared is not None
    _term, positions, total_matches, positions_are_full = prepared
    np.testing.assert_array_equal(positions, np.array([22], dtype=np.uint32))
    assert total_matches == 1
    assert positions_are_full is True


def test_prepare_cql_rows_filters_sparse_docset_before_page_cap(monkeypatch):
    idx = _fake_index_with_doc_bounds(np.array([0, 10, 20], dtype=np.uint32))
    mask = np.array([False, False, True], dtype=np.bool_)
    calls = []

    def fake_resolve(idx_arg, query, *, max_matches, docset_mask=None, **kwargs):
        calls.append({"max_matches": max_matches, "docset_mask": docset_mask})
        assert docset_mask is mask
        return np.array([22], dtype=np.uint32), 1, None, False

    monkeypatch.setattr("candyconc.core.query_runtime._resolve_cql_match_arrays", fake_resolve)
    monkeypatch.setattr("candyconc.core.query_runtime._cql_pivot_index", lambda _query: 0)

    prepared = server._prepare_cql_rows_fast(
        idx,
        'cql:[word="needle"]',
        offset=0,
        limit=1,
        docset_mask=mask,
    )

    assert calls == [{"max_matches": 1, "docset_mask": mask}]
    assert prepared is not None
    _query, positions, match_len_const, match_lengths, _pivot, total_matches, positions_are_full = prepared
    np.testing.assert_array_equal(positions, np.array([22], dtype=np.uint32))
    assert match_len_const == 1
    assert match_lengths is None
    assert total_matches == 1
    assert positions_are_full is False


def test_compute_query_count_uses_complete_cql_domain_with_docset(monkeypatch):
    idx = _fake_index_with_doc_bounds(np.array([0, 10, 20], dtype=np.uint32))
    mask = np.array([False, False, True], dtype=np.bool_)
    calls = []

    monkeypatch.setattr(server, "_linebreak_sentinel_word_id", lambda _idx: 0)

    def fake_count(_fast_index, _query, *, max_matches, progress_cb, docset_mask=None):
        calls.append({"max_matches": max_matches, "docset_mask": docset_mask})
        return 17

    monkeypatch.setattr("candyconc.core.cql_engine.count_cql_matches_backend", fake_count)

    total, _elapsed_ms, partial = server._compute_query_count(
        idx,
        'cql:[word="needle"]',
        5,
        None,
        None,
        mask,
    )

    assert calls == [{"max_matches": server._CQL_COUNT_PROBE_HARD_MAX, "docset_mask": mask}]
    assert total == 17
    assert partial is False


def test_query_endpoint_filters_cql_by_metadata_mask_without_literal_fallback(monkeypatch):
    _reset_query_caches()
    mask = np.array([False, True], dtype=np.bool_)
    idx = _fake_index_with_doc_meta(
        np.array([0, 10], dtype=np.uint32),
        {0: {"date": "2024"}, 1: {"date": "2025"}},
    )
    monkeypatch.setattr(server, "get_corpus", lambda corpus: idx)
    monkeypatch.setattr(server, "_metadata_filter_docset_mask", lambda idx, *, date=None, genre=None: mask)
    calls = []

    def fake_prepare_cql(idx_arg, term, *, offset, limit, docset_mask):
        calls.append({"term": term, "mask": docset_mask, "offset": offset, "limit": limit})
        return "query", np.array([12], dtype=np.uint32), 1, None, 0, 1, True

    monkeypatch.setattr(server, "_prepare_cql_rows_fast", fake_prepare_cql)
    monkeypatch.setattr(
        server,
        "_render_cql_fast_rows",
        lambda *args, **kwargs: [
            {"left": "", "kw": "x", "right": "", "pos": 12, "doc": "doc-1", "meta": {"date": "2025"}}
        ],
    )

    client = TestClient(server.app)
    resp = client.get(
        "/api/v1/query",
        params={"term": 'cql:[word="x"]', "date": "2025", "limit": 1},
    )

    assert resp.status_code == 200
    assert resp.json()[0]["kw"] == "x"
    assert calls
    assert calls[0]["mask"] is mask


def test_compute_query_count_filters_complete_cql_count_by_metadata(monkeypatch):
    idx = _fake_index_with_doc_meta(
        np.array([0, 10], dtype=np.uint32),
        {0: {"date": "2024"}, 1: {"date": "2025"}},
    )
    calls = []

    def fake_count(_fast_index, _query, *, max_matches, progress_cb, docset_mask=None):
        calls.append({"max_matches": max_matches, "docset_mask": np.asarray(docset_mask)})
        return 1

    monkeypatch.setattr("candyconc.core.cql_engine.count_cql_matches_backend", fake_count)

    total, _elapsed_ms, partial = server._compute_query_count(
        idx,
        'cql:[word="x"]',
        5,
        "2025",
        None,
    )

    assert len(calls) == 1
    assert calls[0]["max_matches"] == server._CQL_COUNT_PROBE_HARD_MAX
    np.testing.assert_array_equal(calls[0]["docset_mask"], np.array([False, True], dtype=np.bool_))
    assert total == 1
    assert partial is False


def test_metadata_filter_docset_mask_reuses_cached_mask(monkeypatch):
    _reset_query_caches()
    idx = _fake_index_with_doc_meta(
        np.array([0, 10], dtype=np.uint32),
        {0: {"date": "2024"}, 1: {"date": "2025"}},
    )
    calls = 0
    original = server._shared_doc_meta_for_doc_id

    def counted_meta(index, doc_id):
        nonlocal calls
        calls += 1
        return original(index, doc_id)

    monkeypatch.setattr(server, "_shared_doc_meta_for_doc_id", counted_meta)

    first = server._metadata_filter_docset_mask(idx, date="2025")
    second = server._metadata_filter_docset_mask(idx, date="2025")

    assert first is second
    assert first is not None
    assert not first.flags.writeable
    assert calls == 2


def test_metadata_filter_docset_mask_supports_closed_and_open_date_ranges():
    _reset_query_caches()
    idx = _fake_index_with_doc_meta(
        np.array([0, 10, 20, 30], dtype=np.uint32),
        {
            0: {"date": "2023-12-31"},
            1: {"date": "2024"},
            2: {"date": "2024-06"},
            3: {"date": "2025-01-01"},
        },
    )

    closed = server._metadata_filter_docset_mask(idx, date="2024-01-01..2024-12-31")
    open_ended = server._metadata_filter_docset_mask(idx, date="..2024-06-30")

    np.testing.assert_array_equal(closed, np.array([False, True, True, False]))
    np.testing.assert_array_equal(open_ended, np.array([True, True, True, False]))


def test_metadata_filter_docset_mask_rejects_invalid_date_range():
    idx = _fake_index_with_doc_meta(
        np.array([0, 10], dtype=np.uint32), {0: {"date": "2024-01-01"}}
    )

    with pytest.raises(ValueError, match="Ungültiger Datumsbereich"):
        server._metadata_filter_docset_mask(idx, date="2024-15-01..2024-01-01")


def test_wildcard_case_flag_reaches_rows_and_count_evaluation(monkeypatch):
    """A case-sensitive wildcard must not silently use the CI default."""
    import candyconc.domain.query_eval as query_eval

    idx = _FakeIndex()
    row_calls = []
    count_calls = []
    monkeypatch.setattr(
        query_eval,
        "prefetch_positions_window",
        lambda *_args, **kwargs: (
            row_calls.append(kwargs["case_insensitive"])
            or (np.array([1], dtype=np.uint32), True)
        ),
    )
    monkeypatch.setattr(
        query_eval,
        "prefetch_positions",
        lambda *_args, **kwargs: (
            count_calls.append(kwargs["case_insensitive"])
            or np.array([1], dtype=np.uint32)
        ),
    )
    monkeypatch.setattr(server, "_drop_linebreak_sentinel_positions", lambda _idx, value: (value, 0))

    prepared = server._prepare_plain_rows_fast(idx, "Haus*", case_insensitive=False)
    count, _elapsed_ms, partial = server._compute_query_count(
        idx, "Haus*", 5, None, None, case_insensitive=False
    )

    assert prepared is not None
    assert row_calls == [False]
    assert count_calls == [False]
    assert count == 1
    assert partial is False


def test_query_offset_reports_exact_total_when_not_truncated(monkeypatch):
    _reset_query_caches()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: (_ for _ in ()).throw(RuntimeError("no bounds")))

    def fake_cql_rows(idx, term, *, ctx, limit):
        return [
            {"left": "", "kw": f"r{i}", "right": "", "pos": i}
            for i in range(4)
        ][:limit]

    monkeypatch.setattr(server, "_query_rows_cql_fast", fake_cql_rows)

    client = TestClient(server.app)
    resp = client.get("/api/v1/query", params={"term": "page-total", "offset": 2, "limit": 2})

    assert resp.status_code == 200
    assert [row["kw"] for row in resp.json()] == ["r2", "r3"]
    assert resp.headers["x-candyconc-truncated"] == "false"
    assert resp.headers["x-candyconc-total"] == "4"


def test_compute_query_count_ignores_legacy_cql_cap_and_returns_full_total(monkeypatch):
    calls = []

    monkeypatch.setattr(
        server,
        "get_config",
        lambda key, default=None: "2" if key == "CANDYCONC_CQL_COUNT_MAX" else default,
    )

    def fake_count(_fast_index, _query, *, max_matches, progress_cb):
        calls.append(max_matches)
        return 250_001

    monkeypatch.setattr("candyconc.core.cql_engine.count_cql_matches_backend", fake_count)

    total, _elapsed_ms, partial = server._compute_query_count(
        _FakeIndex(),
        'cql:[word="x"]',
        5,
        None,
        None,
    )

    assert calls == [server._CQL_COUNT_PROBE_HARD_MAX]
    assert total == 250_001
    assert partial is False
