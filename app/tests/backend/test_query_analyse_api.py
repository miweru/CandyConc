import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from fastapi.testclient import TestClient

from candyconc.services.backend import app, server
from candyconc.services.backend.routes import query as query_routes


class TestQueryAnalyseAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_post_preserves_explicit_cql_prefix_in_suggestion(self):
        resp = self.client.post(
            "/api/v1/query/analyse",
            json={"query": 'cql:[pos=""] fox'},
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("Empty POS tag", data.get("errors", []))
        self.assertIn('cql:[pos="NN"] fox', data.get("suggestions", []))
        self.assertIn("Specify part-of-speech", data.get("hints", []))

    def test_post_preserves_cqlf_warnings_and_diagnostics(self):
        def fake_analyse(_backend, query):
            return {
                "errors": [],
                "warnings": ["[cqlf.level2.quantifiers] bounded gap is guarded"],
                "diagnostics": [
                    {
                        "severity": "warning",
                        "message": "[cqlf.level2.quantifiers] bounded gap is guarded",
                        "start": 4,
                        "end": 14,
                        "fixes": [],
                    }
                ],
                "suggestions": [],
                "hints": [],
                "kinds": [],
                "spans": [],
                "builder": {"type": "sequence"},
            }

        with patch.object(server, "get_corpus", lambda _corpus=None: SimpleNamespace(fast_index=object())):
            with patch("candyconc.core.cql_engine.analyse_cql_backend", fake_analyse):
                resp = self.client.post(
                    "/api/v1/query/analyse",
                    json={"query": 'cql:[word="Hase"]+'},
                )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["warnings"], ["[cqlf.level2.quantifiers] bounded gap is guarded"])
        self.assertEqual(data["diagnostics"][0]["severity"], "warning")
        self.assertEqual(data["diagnostics"][0]["start"], 4)
        self.assertEqual(data["builder"], {"type": "sequence"})

    def test_post_scopes_backend_analysis_to_payload_corpus(self):
        captured = []

        def fake_get_corpus(corpus=None):
            captured.append(corpus)
            return SimpleNamespace(fast_index=object())

        def fake_analyse(_backend, _query):
            return {
                "errors": [],
                "warnings": [],
                "diagnostics": [],
                "suggestions": [],
                "hints": [],
                "kinds": [],
                "spans": [],
                "builder": None,
            }

        with patch.object(server, "get_corpus", fake_get_corpus):
            with patch("candyconc.core.cql_engine.analyse_cql_backend", fake_analyse):
                resp = self.client.post(
                    "/api/v1/query/analyse",
                    json={"query": 'cql:[word="Hase"]+', "corpus": "demo-corpus"},
                )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured, ["demo-corpus"])

    def test_lexicon_suggest_scopes_backend_lookup_to_payload_corpus(self):
        captured = []

        def fake_get_corpus(corpus=None):
            captured.append(corpus)
            return SimpleNamespace(fast_index=object())

        with patch.object(server, "get_corpus", fake_get_corpus):
            with patch.object(query_routes, "_lexicon_suggest_values", lambda *_args, **_kwargs: ["Hase"]):
                resp = self.client.post(
                    "/api/v1/query/lexicon/suggest",
                    json={"attr": "word", "prefix": "Ha", "limit": 5, "corpus": "demo-corpus"},
                )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"values": ["Hase"]})
        self.assertEqual(captured, ["demo-corpus"])

    def test_lexicon_suggest_preserves_unicode_frequency_order_and_limit(self):
        class _Lexicon:
            offsets = object()
            strings_view = object()
            vocab_size = 3
            top_global_ids = np.array([1, 2], dtype=np.uint32)
            prefix_top = None
            prefix_len = 0
            _strings = {1: "ßeta", 2: "ßahn"}
            _freqs = {1: 2, 2: 8}

            def _lexicon_for_attr(self, _attr):
                return self

            def get_freqs_for_ids(self, ids):
                return np.array([self._freqs[int(value)] for value in ids], dtype=np.int64)

            def get_strings_for_ids(self, ids):
                return [self._strings[int(value)] for value in ids]

        seen = {}

        def fake_regex(_offsets, _strings_view, pattern):
            seen["pattern"] = pattern
            return np.array([1, 2], dtype=np.uint32)

        with patch.object(query_routes, "lexicon_match_regex", fake_regex):
            values = query_routes._lexicon_suggest_values(_Lexicon(), "word", "ß", 1)
            empty_prefix = query_routes._lexicon_suggest_values(_Lexicon(), "word", "", 1)

        self.assertTrue(seen["pattern"].match("ßeta"))
        self.assertEqual(values, ["ßahn"])
        self.assertEqual(empty_prefix, ["ßeta"])

    def test_lexicon_suggest_propagates_unknown_corpus_status(self):
        with patch.object(
            server,
            "get_corpus",
            side_effect=HTTPException(status_code=404, detail="Korpus nicht gefunden: fehlt"),
        ):
            resp = self.client.post(
                "/api/v1/query/lexicon/suggest",
                json={"attr": "word", "prefix": "Ha", "limit": 5, "corpus": "fehlt"},
            )

        self.assertEqual(resp.status_code, 404)
        self.assertIn("Korpus nicht gefunden", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
