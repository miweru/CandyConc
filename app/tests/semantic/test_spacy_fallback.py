import unittest
from pathlib import Path

import candyconc.config as cc_config
import candyconc.services.embeddings as cc_embeddings
from candyconc.config import APP_CONFIG
from candyconc.services.semantic.index_utils import build_faiss_index
from candyconc.candyconc_copilot.tool_wrappers import semantic_search_tool


def _spacy_model_available() -> bool:
    try:
        import spacy

        model = APP_CONFIG.CANDYCONC_EMB_SPACY_MODEL
        return bool(spacy.util.is_package(model) or Path(str(model)).exists())
    except Exception:
        return False


class TestSpacyFallback(unittest.TestCase):
    def setUp(self):
        if not _spacy_model_available():
            self.skipTest("spaCy embedding model not installed")
        # Post-D9 single-source config: switch the backend via config.set() so
        # the runtime (which reads APP_CONFIG) sees it; clear the model cache.
        self.prev_backend = APP_CONFIG.CANDYCONC_EMB_BACKEND
        self.prev_enabled = APP_CONFIG.ENABLE_EMBEDDING_SEARCH
        cc_config.set("CANDYCONC_EMB_BACKEND", "spacy")
        cc_embeddings._get_model_cached.cache_clear()
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = True
        build_faiss_index(["Das Klima wandelt sich."], "runtime")

    def tearDown(self):
        cc_config.set("CANDYCONC_EMB_BACKEND", self.prev_backend)
        cc_embeddings._get_model_cached.cache_clear()
        APP_CONFIG.ENABLE_EMBEDDING_SEARCH = self.prev_enabled
        for name in ("faiss_passage.index", "passage_vecs.npy", "passage_texts.json"):
            Path("runtime", name).unlink(missing_ok=True)

    def test_fallback(self):
        result = semantic_search_tool("Klima", top_n=1)
        rows = result.get("rows")
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
