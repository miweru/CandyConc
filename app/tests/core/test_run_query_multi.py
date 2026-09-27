"""OR query contract on a real Fast Index.

The retired SQLite-era ``CorpusIndex(":memory:")`` + ``import_tokens`` API is
gone (corpus_index.py requires an on-disk Fast Index directory). Reuse the
shared tiny-index builder from tests/core/test_run_query.py.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.query_runtime import run_query, set_corpus

from tests.core.test_run_query import TOKENS_TEXT, build_tiny_fast_index


class TestRunQueryMulti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_run_query_multi_idx_")
        cls.index_path = build_tiny_fast_index(Path(cls._tmp), TOKENS_TEXT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)

    def tearDown(self):
        set_corpus(None)
        self.idx.close()

    def test_or_query(self):
        rows = list(run_query("fox OR dog", ctx=1))
        kws = {r["kw"] for r in rows}
        self.assertEqual(kws, {"fox", "dog"})
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
