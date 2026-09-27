import os
from pathlib import Path

import numpy as np

from candyconc.core import query_runtime
class _DummyFastIndex:
    def __init__(self, index_path: str):
        self.index_path = Path(index_path)


class _DummyIndex:
    def __init__(self, index_path: str):
        self.path = Path(index_path)
        self.fast_index = _DummyFastIndex(index_path)


def test_resolve_cql_match_arrays_caches_variable_spans(monkeypatch) -> None:
    query_runtime.clear_cql_positions_cache()
    idx = _DummyIndex("/tmp/candyconc-query-runtime-cache-variable")
    calls = {"count": 0}

    def _fake_search(*_args, **_kwargs):
        calls["count"] += 1
        return np.array([7, 2], dtype=np.uint32), np.array([10, 3], dtype=np.uint32)

    monkeypatch.setattr("candyconc.core.cql_engine.search_cql_match_arrays_backend", _fake_search)
    monkeypatch.setattr(query_runtime, "_cql_fixed_token_count", lambda _q: None)

    first_pos, first_fixed, first_spans, first_full = query_runtime._resolve_cql_match_arrays(
        idx,
        "[word=\"x\"][]{0,2}",
        max_matches=100,
        use_cache=True,
        exhaustive=True,
    )
    second_pos, second_fixed, second_spans, second_full = query_runtime._resolve_cql_match_arrays(
        idx,
        "[word=\"x\"][]{0,2}",
        max_matches=100,
        use_cache=True,
        exhaustive=True,
    )

    assert calls["count"] == 1
    assert first_fixed is None and second_fixed is None
    assert first_full and second_full
    np.testing.assert_array_equal(first_pos, np.array([2, 7], dtype=np.uint32))
    np.testing.assert_array_equal(first_spans, np.array([1, 3], dtype=np.int64))
    np.testing.assert_array_equal(second_pos, first_pos)
    np.testing.assert_array_equal(second_spans, first_spans)


def test_resolve_cql_match_arrays_caches_fixed_length_without_spans(monkeypatch) -> None:
    query_runtime.clear_cql_positions_cache()
    idx = _DummyIndex("/tmp/candyconc-query-runtime-cache-fixed")
    calls = {"count": 0}

    def _fake_search(*_args, **_kwargs):
        calls["count"] += 1
        return np.array([5, 1], dtype=np.uint32), np.array([7, 3], dtype=np.uint32)

    monkeypatch.setattr("candyconc.core.cql_engine.search_cql_match_arrays_backend", _fake_search)
    monkeypatch.setattr(query_runtime, "_cql_fixed_token_count", lambda _q: 2)

    first_pos, first_fixed, first_spans, first_full = query_runtime._resolve_cql_match_arrays(
        idx,
        "[word=\"a\"] [word=\"b\"]",
        max_matches=100,
        use_cache=True,
        exhaustive=True,
    )
    second_pos, second_fixed, second_spans, second_full = query_runtime._resolve_cql_match_arrays(
        idx,
        "[word=\"a\"] [word=\"b\"]",
        max_matches=100,
        use_cache=True,
        exhaustive=True,
    )

    assert calls["count"] == 1
    assert first_fixed == 2 and second_fixed == 2
    assert first_spans is None and second_spans is None
    assert first_full and second_full
    np.testing.assert_array_equal(first_pos, np.array([1, 5], dtype=np.uint32))
    np.testing.assert_array_equal(second_pos, first_pos)


def test_run_query_does_not_prefetch_regular_simple_terms_for_lbr_drop(monkeypatch) -> None:
    """Only the literal |LBR| marker needs full postings for the sentinel drop."""
    idx = _DummyIndex("/tmp/candyconc-query-runtime-no-plain-prefetch")
    monkeypatch.setattr(query_runtime, "linebreak_sentinel_word_id", lambda _idx: 7)

    def _forbidden_prefetch(*_args, **_kwargs):
        raise AssertionError("regular terms must not materialize full postings")

    def _fake_evaluate(*_args, **_kwargs):
        yield {"pos": 1, "kw": "und"}

    monkeypatch.setattr(query_runtime, "prefetch_positions", _forbidden_prefetch)
    monkeypatch.setattr(query_runtime, "evaluate", _fake_evaluate)

    assert list(query_runtime.run_query("und", ctx=0, corpus=idx, limit=1)) == [
        {"pos": 1, "kw": "und"}
    ]


def test_cql_positions_cache_key_changes_when_index_artifact_changes(monkeypatch, tmp_path) -> None:
    query_runtime.clear_cql_positions_cache()
    (tmp_path / "meta.bin").write_bytes(b"v1")
    idx = _DummyIndex(str(tmp_path))
    calls = {"count": 0}

    def _fake_search(*_args, **_kwargs):
        calls["count"] += 1
        start = calls["count"]
        return np.array([start], dtype=np.uint32), np.array([start + 1], dtype=np.uint32)

    monkeypatch.setattr("candyconc.core.cql_engine.search_cql_match_arrays_backend", _fake_search)
    monkeypatch.setattr(query_runtime, "_cql_fixed_token_count", lambda _q: 1)

    first_pos, *_ = query_runtime._resolve_cql_match_arrays(
        idx,
        '[word="x"]',
        max_matches=10,
        use_cache=True,
        exhaustive=True,
    )
    second_pos, *_ = query_runtime._resolve_cql_match_arrays(
        idx,
        '[word="x"]',
        max_matches=10,
        use_cache=True,
        exhaustive=True,
    )
    (tmp_path / "meta.bin").write_bytes(b"v2")
    os.utime(tmp_path / "meta.bin", ns=(2_000_000_000_000_000_000, 2_000_000_000_000_000_000))
    third_pos, *_ = query_runtime._resolve_cql_match_arrays(
        idx,
        '[word="x"]',
        max_matches=10,
        use_cache=True,
        exhaustive=True,
    )

    assert calls["count"] == 2
    np.testing.assert_array_equal(first_pos, np.array([1], dtype=np.uint32))
    np.testing.assert_array_equal(second_pos, np.array([1], dtype=np.uint32))
    np.testing.assert_array_equal(third_pos, np.array([2], dtype=np.uint32))


def test_resolve_cql_match_arrays_marks_short_limited_scan_full(monkeypatch) -> None:
    query_runtime.clear_cql_positions_cache()
    idx = _DummyIndex("/tmp/candyconc-query-runtime-short-limited-full")

    def _fake_search(*_args, **_kwargs):
        return np.array([4, 9], dtype=np.uint32), np.array([5, 10], dtype=np.uint32)

    monkeypatch.setattr("candyconc.core.cql_engine.search_cql_match_arrays_backend", _fake_search)
    monkeypatch.setattr(query_runtime, "_cql_fixed_token_count", lambda _q: 1)

    positions, match_len, spans, positions_are_full = query_runtime._resolve_cql_match_arrays(
        idx,
        '[word="x"]',
        max_matches=3,
        use_cache=False,
        exhaustive=False,
    )

    assert match_len == 1
    assert spans is None
    assert positions_are_full is True
    np.testing.assert_array_equal(positions, np.array([4, 9], dtype=np.uint32))


def test_apply_cql_span_to_row_keeps_row_text_for_pivot_zero() -> None:
    row = {"left": "a b", "kw": "und", "right": "der die ist", "pos": 10}

    out = query_runtime._apply_cql_span_to_row(row, 3, 0)

    assert out["left"] == "a b"
    assert out["kw"] == "und"
    assert out["right"] == "der die ist"
    assert out["pos"] == 10
    assert out["match_offsets"] == [1, 2]


def test_apply_cql_span_to_row_shifts_text_for_nonzero_pivot() -> None:
    row = {"left": "a b", "kw": "und", "right": "der die ist", "pos": 10}

    out = query_runtime._apply_cql_span_to_row(row, 3, 1)

    assert out["left"] == "a b und"
    assert out["kw"] == "der"
    assert out["right"] == "die ist"
    assert out["pos"] == 11
    assert out["match_offsets"] == [-1, 1]


def test_run_query_list_uses_pivot_positions_for_fixed_length_cql(monkeypatch) -> None:
    class _FastIndex:
        def __init__(self) -> None:
            self.calls = []

        def kwic_rows_for_positions(self, positions, ctx, include_arcs=True, include_file=True):
            self.calls.append((positions.copy(), ctx, include_arcs, include_file))
            return [
                {"left": "a und", "kw": "ist", "right": "b", "pos": int(positions[0])},
                {"left": "c und", "kw": "ist", "right": "d", "pos": int(positions[1])},
            ]

    class _Index:
        def __init__(self) -> None:
            self.path = Path("/tmp/candyconc-run-query-list-pivot")
            self.fast_index = _FastIndex()

    idx = _Index()
    monkeypatch.setattr(
        query_runtime,
        "_resolve_cql_match_arrays",
        lambda *_args, **_kwargs: (np.array([10, 20], dtype=np.uint32), 2, None, True),
    )
    monkeypatch.setattr(query_runtime, "_cql_pivot_index", lambda _q: 1)

    rows = query_runtime.run_query_list(
        'cql:[word~"^un.*"] [word="ist"]',
        ctx=5,
        corpus=idx,
        use_cache=False,
        allow_cache_fallback=False,
    )

    np.testing.assert_array_equal(idx.fast_index.calls[0][0], np.array([11, 21], dtype=np.uint32))
    assert rows[0]["kw"] == "ist"
    assert rows[0]["pos"] == 11
    assert rows[0]["match_offsets"] == [-1]


def test_run_query_list_treats_bare_bracket_cql_as_cql(monkeypatch) -> None:
    class _FastIndex:
        def __init__(self) -> None:
            self.calls = []

        def kwic_rows_for_positions(self, positions, ctx, include_arcs=True, include_file=True):
            self.calls.append((positions.copy(), ctx, include_arcs, include_file))
            return [{"left": "", "kw": "Politik", "right": "", "pos": int(positions[0])}]

    class _Index:
        def __init__(self) -> None:
            self.path = Path("/tmp/candyconc-run-query-list-bare-cql")
            self.fast_index = _FastIndex()

    idx = _Index()
    monkeypatch.setattr(
        query_runtime,
        "_resolve_cql_match_arrays",
        lambda *_args, **_kwargs: (np.array([7], dtype=np.uint32), 1, None, True),
    )
    monkeypatch.setattr(query_runtime, "_cql_pivot_index", lambda _q: 0)

    rows = query_runtime.run_query_list(
        '[word="Politik"]',
        ctx=3,
        corpus=idx,
        use_cache=False,
        allow_cache_fallback=False,
    )

    np.testing.assert_array_equal(idx.fast_index.calls[0][0], np.array([7], dtype=np.uint32))
    assert rows == [{"left": "", "kw": "Politik", "right": "", "pos": 7}]


def test_run_query_list_reports_exact_cql_count_at_count_limit(monkeypatch) -> None:
    class _FastIndex:
        def kwic_rows_for_positions(self, positions, ctx, include_arcs=True, include_file=True):
            return [{"left": "", "kw": "x", "right": "", "pos": int(positions[0])}]

    class _Index:
        def __init__(self) -> None:
            self.path = Path("/tmp/candyconc-run-query-list-count-exact")
            self.fast_index = _FastIndex()

    counts = []
    count_limits = []

    def _fake_count(*_args, **kwargs):
        count_limits.append(kwargs["max_matches"])
        return 2

    monkeypatch.setattr(query_runtime, "_CQL_COUNT_MAX", 2)
    monkeypatch.setattr("candyconc.core.cql_engine.count_cql_matches_backend", _fake_count)
    monkeypatch.setattr(
        query_runtime,
        "_resolve_cql_match_arrays",
        lambda *_args, **_kwargs: (np.array([3], dtype=np.uint32), 1, None, False),
    )
    monkeypatch.setattr(query_runtime, "_cql_pivot_index", lambda _q: 0)

    rows = query_runtime.run_query_list(
        'cql:[word="x"]',
        ctx=2,
        corpus=_Index(),
        limit=1,
        count_cb=counts.append,
        use_cache=False,
    )

    assert [row["kw"] for row in rows] == ["x"]
    assert count_limits == [3]
    assert counts == [2]


def test_run_query_list_suppresses_capped_cql_count_callback(monkeypatch) -> None:
    class _FastIndex:
        def kwic_rows_for_positions(self, positions, ctx, include_arcs=True, include_file=True):
            return [{"left": "", "kw": "x", "right": "", "pos": int(positions[0])}]

    class _Index:
        def __init__(self) -> None:
            self.path = Path("/tmp/candyconc-run-query-list-count-capped")
            self.fast_index = _FastIndex()

    counts = []
    count_limits = []

    def _fake_count(*_args, **kwargs):
        count_limits.append(kwargs["max_matches"])
        return 3

    monkeypatch.setattr(query_runtime, "_CQL_COUNT_MAX", 2)
    monkeypatch.setattr("candyconc.core.cql_engine.count_cql_matches_backend", _fake_count)
    monkeypatch.setattr(
        query_runtime,
        "_resolve_cql_match_arrays",
        lambda *_args, **_kwargs: (np.array([3], dtype=np.uint32), 1, None, False),
    )
    monkeypatch.setattr(query_runtime, "_cql_pivot_index", lambda _q: 0)

    rows = query_runtime.run_query_list(
        'cql:[word="x"]',
        ctx=2,
        corpus=_Index(),
        limit=1,
        count_cb=counts.append,
        use_cache=False,
    )

    assert [row["kw"] for row in rows] == ["x"]
    assert count_limits == [3]
    assert counts == []
