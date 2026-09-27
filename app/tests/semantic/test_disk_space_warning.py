import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

import candyconc.config as cc_config
import candyconc.services.embeddings as cc_embeddings
from candyconc.config import APP_CONFIG
from candyconc.services.semantic.index_utils import build_faiss_index

# Embeddings are spaCy-only (src/candyconc/services/embeddings.py) and need a
# model with vectors.
_SPACY_MODEL = os.environ.get("CANDYCONC_EMB_SPACY_MODEL", "de_core_news_md")
spacy = pytest.importorskip("spacy", reason="spaCy not installed")
pytest.importorskip("faiss", reason="faiss required for build_faiss_index")
if not spacy.util.is_package(_SPACY_MODEL):
    pytest.skip(
        f"spaCy embedding model '{_SPACY_MODEL}' not installed "
        "(required by the spaCy-only embedding backend)",
        allow_module_level=True,
    )


class TestDiskSpaceWarning(unittest.TestCase):
    def setUp(self):
        # Post-D9 single-source config: switch via config.set() so the runtime
        # (reads APP_CONFIG, not live os.environ) sees the spaCy backend.
        self._prev_backend = APP_CONFIG.CANDYCONC_EMB_BACKEND
        cc_config.set("CANDYCONC_EMB_BACKEND", "spacy")
        cc_embeddings._get_model_cached.cache_clear()

    def tearDown(self):
        cc_config.set("CANDYCONC_EMB_BACKEND", self._prev_backend)
        cc_embeddings._get_model_cached.cache_clear()

    def test_warning_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            warnings = []

            def cb(progress: int, msg: str) -> None:
                warnings.append(msg)

            docs = ["foo", "bar"]

            orig_stat = Path.stat

            def fake_stat(self):
                if self.name == "passage_vecs.npy":
                    return types.SimpleNamespace(st_size=3 * 1024 * 1024 * 1024)
                return orig_stat(self)

            with patch.object(Path, "stat", fake_stat):
                build_faiss_index(docs, tmp, progress_cb=cb)

            self.assertIn("warn_disk_space", warnings)


if __name__ == "__main__":
    unittest.main()

