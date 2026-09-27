from pathlib import Path

import numpy as np

from candyconc.services.backend import server


class _DummyFastIndex:
    def __init__(self, index_path: str):
        self.index_path = Path(index_path)
        self.term_calls = 0

    def term_positions(self, term: str, attr: str = "word") -> np.ndarray:
        self.term_calls += 1
        return np.array([2, 5, 9], dtype=np.uint32)


class _DummyIndex:
    def __init__(self, index_path: str):
        self.fast_index = _DummyFastIndex(index_path)


# The cql: branch of server._resolve_term_anchor_positions goes through
# query_runtime._resolve_cql_match_arrays, whose backend seam today is
# cql_engine.search_cql_match_arrays_backend returning (starts, ends) arrays
# (src/candyconc/core/query_runtime.py:336). The old seam
# search_cql_matches_backend (Match list) is no longer on this path — patching
# it let the real engine run and blow up on the dummy index
# (FastCorpus.from_backend needs token_store, src/cqlhpc/fast_corpus.py:391).


def test_resolve_term_anchor_positions_caches_fixed_span_cql(monkeypatch) -> None:
    idx = _DummyIndex("/tmp/candyconc-anchor-cache-fixed")
    calls = {"count": 0}

    def _fake_search_arrays(*_args, **_kwargs):
        calls["count"] += 1
        # match spans (5,7) and (2,4): unsorted starts, fixed width 2
        return (
            np.array([5, 2], dtype=np.uint32),
            np.array([7, 4], dtype=np.uint32),
        )

    monkeypatch.setattr(
        "candyconc.core.cql_engine.search_cql_match_arrays_backend",
        _fake_search_arrays,
    )
    monkeypatch.setattr("candyconc.core.query_runtime._cql_fixed_token_count", lambda _q: 2)

    first_pos, first_spans = server._resolve_term_anchor_positions(
        idx,
        "cql:[word=\"eins\"] [word=\"zwei\"]",
        within_sentence=True,
    )
    second_pos, second_spans = server._resolve_term_anchor_positions(
        idx,
        "cql:[word=\"eins\"] [word=\"zwei\"]",
        within_sentence=True,
    )

    assert calls["count"] == 1
    np.testing.assert_array_equal(first_pos, np.array([2, 5], dtype=np.uint32))
    np.testing.assert_array_equal(first_spans, np.array([2, 2], dtype=np.int64))
    np.testing.assert_array_equal(second_pos, first_pos)
    np.testing.assert_array_equal(second_spans, first_spans)


def test_resolve_term_anchor_positions_sorts_variable_spans(monkeypatch) -> None:
    idx = _DummyIndex("/tmp/candyconc-anchor-cache-variable")

    monkeypatch.setattr(
        "candyconc.core.cql_engine.search_cql_match_arrays_backend",
        # match spans (8,11) and (3,4): variable width
        lambda *_args, **_kwargs: (
            np.array([8, 3], dtype=np.uint32),
            np.array([11, 4], dtype=np.uint32),
        ),
    )
    monkeypatch.setattr("candyconc.core.query_runtime._cql_fixed_token_count", lambda _q: None)

    positions, spans = server._resolve_term_anchor_positions(
        idx,
        "cql:[word=\"x\"][]{0,1}",
        within_sentence=False,
    )

    np.testing.assert_array_equal(positions, np.array([3, 8], dtype=np.uint32))
    np.testing.assert_array_equal(spans, np.array([1, 3], dtype=np.int64))
