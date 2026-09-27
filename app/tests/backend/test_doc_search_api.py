import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from candyconc.core.doc_search import document_search as core_document_search
from candyconc.services.backend import app


class TestDocSearchAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_doc_search_endpoint_returns_ranked_evidence(self):
        index = object()
        expected = [
            {
                "doc_id": 1,
                "file": "doc1.cwb",
                "score": 0.91,
                "snippet": "the quick brown fox jumps",
                "pos": 3,
            }
        ]
        with patch("candyconc.services.backend.server.get_index", return_value=index):
            with patch(
                "candyconc.services.backend.routes.documents.document_search",
                return_value=expected,
            ) as search:
                resp = self.client.get(
                    "/api/v1/docs/search",
                    params={
                        "term": "fox",
                        "top_n": 2,
                        "snippet": 6,
                        "metric": "bm25",
                    },
                )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), expected)
        search.assert_called_once_with(
            index,
            "fox",
            top_n=2,
            snippet=6,
            metric="bm25",
        )

    def test_core_doc_search_returns_openable_doc_id(self):
        case = self

        class _TokenStore:
            token_count = 20

        class _DocumentBoundary:
            _positions = np.array([0, 10], dtype=np.uint32)

        class _Boundaries:
            document = _DocumentBoundary()

        class _FastIndex:
            boundaries = _Boundaries()
            token_store = _TokenStore()

            def term_positions(self, _tok, attr="word"):
                case.assertEqual(attr, "word")
                return np.array([2, 14], dtype=np.uint32)

            def kwic_rows_for_positions(self, positions, half, include_arcs=False):
                case.assertEqual(half, 3)
                case.assertFalse(include_arcs)
                return [
                    {"pos": int(pos), "left": "links", "kw": "fox", "right": "rechts"}
                    for pos in positions
                ]

            def doc_path_for_idx(self, doc_id):
                return f"doc-{doc_id}.txt"

        class _Index:
            ranking_metric = "tf"
            fast_index = _FastIndex()

        with patch(
            "candyconc.core.doc_search.doc_search_scores",
            return_value=(
                np.array([1, 0], dtype=np.uint32),
                np.array([2.0, 1.0], dtype=np.float64),
                np.array([14, 2], dtype=np.uint32),
            ),
        ):
            rows = core_document_search(_Index(), "fox", top_n=2, snippet=6)

        self.assertEqual(rows[0]["doc_id"], 1)
        self.assertEqual(rows[0]["file"], "doc-1.txt")
        self.assertEqual(rows[0]["pos"], 14)
        self.assertIn("fox", rows[0]["snippet"])

    def test_doc_search_empty_term_does_not_require_index(self):
        with patch("candyconc.services.backend.server.get_index") as get_index:
            resp = self.client.get("/api/v1/docs/search", params={"term": "   "})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])
        get_index.assert_not_called()

    def test_doc_search_missing_index_returns_problem_503(self):
        with patch(
            "candyconc.services.backend.server.get_index",
            side_effect=RuntimeError("Kein Indexpfad konfiguriert."),
        ):
            resp = self.client.get("/api/v1/docs/search", params={"term": "fox"})

        self.assertEqual(resp.status_code, 503)
        data = resp.json()
        self.assertEqual(data.get("status"), 503)
        self.assertEqual(data.get("instance"), "/api/v1/docs/search")
        self.assertIn("Kein Indexpfad", data.get("detail", ""))


if __name__ == "__main__":
    unittest.main()
