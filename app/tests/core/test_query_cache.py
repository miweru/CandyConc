import os
import importlib
import unittest
from pathlib import Path

import numpy as np
import candyconc.domain.query_eval as query_eval


class _StubIndex:
    def __init__(self) -> None:
        self.path = Path("/tmp/candyconc-test-index")

    def term_positions(self, term: str, *, case_insensitive: bool = True) -> np.ndarray:
        if term == "alpha":
            return np.array([0, 2], dtype=np.uint32)
        return np.zeros(0, dtype=np.uint32)

    def close(self) -> None:
        return None


class TestQueryCache(unittest.TestCase):
    def setUp(self):
        os.environ["CANDYCONC_ENABLE_QUERY_CACHE"] = "1"
        importlib.reload(query_eval)
        query_eval._CACHE_ENABLED = True
        self.idx = _StubIndex()
        self._orig_kwic_rows = query_eval._kwic_rows_fast_iter
        query_eval._kwic_rows_fast_iter = lambda index, positions, ctx, limit: (
            {"pos": int(pos), "kw": "alpha"} for pos in positions.tolist()
        )

    def tearDown(self):
        os.environ.pop("CANDYCONC_ENABLE_QUERY_CACHE", None)
        query_eval._kwic_rows_fast_iter = self._orig_kwic_rows
        importlib.reload(query_eval)
        self.idx.close()

    def test_cache_hits(self):
        query_eval.clear_positions_cache()
        self.assertIsNone(query_eval.get_cached_positions("alpha", self.idx))

        first = query_eval.prefetch_positions("alpha", self.idx)
        cached = query_eval.get_cached_positions("alpha", self.idx)
        second = query_eval.prefetch_positions("alpha", self.idx)

        self.assertIsNotNone(cached)
        self.assertIs(cached, first)
        self.assertIs(second, first)
        self.assertEqual(first.tolist(), [0, 2])

if __name__ == "__main__":
    unittest.main()
