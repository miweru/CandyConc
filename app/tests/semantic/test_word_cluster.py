import unittest
import importlib
import sys

from fastapi.testclient import TestClient

import candyconc.config as cc_config
import candyconc.services.embeddings as cc_embeddings
from candyconc.config import APP_CONFIG

sys.modules["fastapi"] = importlib.import_module("fastapi")
# NOTE: no module-level sys.modules.pop here — pytest imports all test
# modules at collection time, and popping the cached backend module breaks
# references bound earlier by other test modules (tests/ai/test_observability
# pattern).  A plain import works: the conftest only stubs leaf modules.
backend = importlib.import_module("candyconc.services.backend")


def _spacy_model_available() -> bool:
    try:
        import spacy

        model = APP_CONFIG.CANDYCONC_EMB_SPACY_MODEL
        return bool(spacy.util.is_package(model))
    except Exception:
        return False


class TestWordCluster(unittest.TestCase):
    def setUp(self):
        if not _spacy_model_available():
            self.skipTest("spaCy embedding model not installed")
        self.client = TestClient(backend.app)
        # Post-D9 single-source config: switch via config.set() so the runtime
        # (reads APP_CONFIG) sees the spaCy backend; clear the model cache.
        self._prev_backend = APP_CONFIG.CANDYCONC_EMB_BACKEND
        cc_config.set("CANDYCONC_EMB_BACKEND", "spacy")
        cc_embeddings._get_model_cached.cache_clear()

    def tearDown(self):
        cc_config.set("CANDYCONC_EMB_BACKEND", self._prev_backend)
        cc_embeddings._get_model_cached.cache_clear()

    def test_word_cluster_endpoint(self):
        tokens = ["solar"] * 10 + ["wind"] * 10 + ["dog"] * 10
        examples = [t + " example" for t in tokens]

        resp = self.client.post(
            "/api/v1/semantic/cluster_words",
            json={"tokens": tokens, "examples": examples, "min_size": 3},
        )
        self.assertEqual(resp.status_code, 200)
        clusters = resp.json()
        self.assertTrue(clusters)
        for cl in clusters:
            self.assertTrue(cl["label"])

    def test_word_cluster_endpoint_separates_migration_and_climate(self):
        tokens = [
            "Migration",
            "Flüchtlinge",
            "Asyl",
            "Einwanderung",
            "Klima",
            "Umwelt",
            "Artenvielfalt",
            "CO2",
        ]
        resp = self.client.post(
            "/api/v1/semantic/cluster_words",
            json={"tokens": tokens, "examples": tokens},
        )
        self.assertEqual(resp.status_code, 200)
        clusters = resp.json()
        named = [cl for cl in clusters if str(cl.get("label", "")).casefold() != "misc"]
        self.assertGreaterEqual(len(named), 2)


if __name__ == "__main__":
    unittest.main()
