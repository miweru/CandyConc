"""ranking_metric persistence round-trip on a real Fast Index directory.

The old test passed a bare (non-existent) ``idx.db`` file path; the Fast Index
requires a real on-disk index directory (corpus_index.py: "Fast Index erwartet
ein Verzeichnis mit meta.bin"). Build one tiny real index (shared builder, see
tests/core/test_run_query.py) and run the original persistence contract
against its config.json (CorpusIndex._save_config / set_ranking_metric).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex

from tests.core.test_run_query import TOKENS_TEXT, build_tiny_fast_index


class TestRankingMetricPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = build_tiny_fast_index(self.tmp, TOKENS_TEXT)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_metric_saved_and_loaded(self):
        # Persisting ranking_metric is a write, so the index must be opened
        # writable (read_only defaults to True).
        idx = CorpusIndex(self.db, ranking_metric="tf-idf", read_only=False)
        idx.close()
        idx2 = CorpusIndex(self.db, read_only=False)
        self.assertEqual(idx2.ranking_metric, "tf-idf")
        idx2.set_ranking_metric("tf")
        idx2.close()
        idx3 = CorpusIndex(self.db)
        self.assertEqual(idx3.ranking_metric, "tf")


if __name__ == "__main__":
    unittest.main()
