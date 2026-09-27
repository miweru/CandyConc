import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from candyconc.services.backend import app


class TestNoCorpus(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.fake_idx = object()
        self.get_corpus_patch = patch(
            "candyconc.services.backend.server.get_corpus",
            return_value=self.fake_idx,
        )
        self.doc_bounds_patch = patch(
            "candyconc.services.backend.server._doc_bounds_for_index",
            side_effect=RuntimeError("no bounds"),
        )
        self.kwic_patch = patch(
            "candyconc.services.backend.kwic.kwic_rows",
            return_value=self._kwic_gen(),
        )
        self.kwic_list_patch = patch(
            "candyconc.services.backend.kwic.kwic_rows_list",
            return_value=[{"left": "quick", "kw": "fox", "right": "jumps", "pos": 2}],
        )
        self.query_cql_fast_patch = patch(
            "candyconc.services.backend.server._query_rows_cql_fast",
            return_value=None,
        )
        self.query_plain_fast_patch = patch(
            "candyconc.services.backend.server._query_rows_plain_fast",
            return_value=None,
        )
        self.get_corpus_patch.start()
        self.doc_bounds_patch.start()
        self.kwic_patch.start()
        self.kwic_list_patch.start()
        self.query_cql_fast_patch.start()
        self.query_plain_fast_patch.start()

    def tearDown(self):
        self.query_plain_fast_patch.stop()
        self.query_cql_fast_patch.stop()
        self.kwic_patch.stop()
        self.kwic_list_patch.stop()
        self.doc_bounds_patch.stop()
        self.get_corpus_patch.stop()

    async def _kwic_gen(self):
        yield {"left": "quick", "kw": "fox", "right": "jumps", "pos": 2}

    def test_query_endpoint_works_without_runtime_global(self):
        resp = self.client.get("/api/v1/query", params={"term": "fox", "ctx": 1})
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["kw"], "fox")

    def test_query_endpoint_reports_empty_sim_expansion_as_user_error(self):
        with patch(
            "candyconc.services.backend.server._query_rows_cql_fast",
            side_effect=RuntimeError('Keine ähnlichen Korpuswörter für sim("Hase") oberhalb Score 0.55 gefunden.'),
        ):
            resp = self.client.get("/api/v1/query", params={"term": 'cql:[sim="Hase"&k=5]', "ctx": 1})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Keine ähnlichen Korpuswörter", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
