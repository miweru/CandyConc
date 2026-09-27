"""Real vectorizer module contract.

The previous version of this file imported ``JinaBERTv3`` /
``FineTunedJinaBERTv3`` -- STUB-ONLY names that exist solely in the
tests/conftest.py ``vectorizer`` stub and were never exported by the real
module (src/candyconc/candyconc_copilot/vectorizer.py exports only
``VectorEmbeddings``, ``SpaCyEmbeddings`` and ``get_default_vectorizer``).
These tests pin the real module surface instead; instantiating
``SpaCyEmbeddings`` is avoided because it requires a spaCy model with vectors.
"""

import importlib.util
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_VEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "candyconc"
    / "candyconc_copilot"
    / "vectorizer.py"
)
_spec = importlib.util.spec_from_file_location("cc_real_vectorizer", _VEC_PATH)
assert _spec and _spec.loader
_vec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vec)


class TestVectorizers(unittest.TestCase):
    def test_real_module_exports(self):
        self.assertEqual(
            _vec.__all__,
            ["VectorEmbeddings", "SpaCyEmbeddings", "get_default_vectorizer"],
        )
        # Guard against stub-drift: the conftest stub exports Jina classes the
        # real module never had.
        self.assertFalse(hasattr(_vec, "JinaBERTv3"))
        self.assertFalse(hasattr(_vec, "FineTunedJinaBERTv3"))

    def test_get_default_vectorizer_rejects_non_spacy_backend(self):
        # Real contract: only the spaCy backend is allowed
        # (vectorizer.py: ``raise RuntimeError("Nur spaCy Embeddings ...")``).
        with patch.object(
            _vec, "APP_CONFIG", types.SimpleNamespace(CANDYCONC_EMB_BACKEND="jina")
        ):
            with self.assertRaises(RuntimeError):
                _vec.get_default_vectorizer()

    def test_vector_embeddings_protocol_shape(self):
        class Impl:
            dim = 4

            def vectorize(self, text):
                return None

            def batch_vectorize(self, texts, batch_size=-1):
                return None

            def clean_up(self):
                return None

        self.assertIsInstance(Impl(), _vec.VectorEmbeddings)


if __name__ == "__main__":
    unittest.main()
