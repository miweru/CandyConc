import unittest

import importlib
import pandas as pd
from fastapi.testclient import TestClient
from candyconc.tools.memory_bench import benchmark_memory

# NOTE: no module-level sys.modules.pop here — pytest imports all test
# modules at collection time, and tests/tools collects AFTER tests/backend:
# popping the cached server module here installs a FRESH server module for
# the whole run phase while earlier test modules keep references (and the
# TestClient app) of the old one — their dotted-path patches then target the
# wrong module object (tests/ai/test_observability pattern).  A plain import
# resolves the real server: the conftest only stubs leaf modules.
server = importlib.import_module("candyconc.services.backend.server")


class TestKeyness(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def tearDown(self):
        if hasattr(self, "client"):
            self.client.close()

    def test_stats_and_wordcloud(self):
        target = "the quick brown fox".split()
        reference = "jumps over the lazy dog".split()
        pos_map = {
            "the": "DET",
            "quick": "ADJ",
            "brown": "ADJ",
            "fox": "N",
            "jumps": "V",
            "over": "PREP",
            "lazy": "ADJ",
            "dog": "N",
        }
        # min_freq=0: this test verifies the keyness *math* (chi2_cell, direction,
        # ll) on a toy example where every word has frequency 1. The endpoint's
        # default research-grade reliability floor (DEFAULT_MIN_FREQ=5) would
        # legitimately filter all of these out, which is orthogonal to what this
        # test asserts, so it opts out of the floor explicitly.
        resp = self.client.post(
            "/api/v1/analysis/keyness",
            json={"target": target, "reference": reference, "pos_map": pos_map, "min_freq": 0},
        )
        self.assertEqual(resp.status_code, 200)
        df = pd.DataFrame(resp.json().get("rows", resp.json()))
        self.assertIn("chi2_cell", df.columns)
        self.assertIn("direction", df.columns)
        target_rows = df[df["direction"] == "target"]
        reference_rows = df[df["direction"] == "reference"]
        self.assertTrue({"quick", "brown", "fox"} <= set(target_rows["word"]))
        self.assertTrue({"jumps", "over", "lazy", "dog"} <= set(reference_rows["word"]))
        self.assertGreater(float(target_rows.iloc[0]["chi2_cell"]), 0.0)
        self.assertLess(float(reference_rows.iloc[0]["chi2_cell_signed"]), 0.0)
        self.assertAlmostEqual(
            float(reference_rows[reference_rows["word"] == "dog"]["ll"].iloc[0]),
            1.274953,
            delta=0.01,
        )

        mem = benchmark_memory(
            lambda: self.client.post(
                "/api/v1/analysis/keyness",
                json={"target": target, "reference": reference, "min_freq": 0},
            ).json()
        )
        self.assertGreater(mem, 0)

        resp_n = self.client.post(
            "/api/v1/analysis/keyness",
            json={"target": target, "reference": reference, "pos_map": pos_map, "pos": "N", "min_freq": 0},
        )
        df_n = pd.DataFrame(resp_n.json().get("rows", resp_n.json()))
        self.assertEqual(set(df_n["word"]), {"dog", "fox"})



if __name__ == "__main__":
    unittest.main()
