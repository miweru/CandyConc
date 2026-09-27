import unittest
from unittest import mock

from candyconc import model_registry


class TestModelRegistry(unittest.TestCase):
    def setUp(self) -> None:
        model_registry.clear_registry()

    def test_get_spacy_cached(self):
        with mock.patch("spacy.load", return_value=object()) as load:
            a = model_registry.get_spacy("en_core_web_sm", disable=["tagger"])
            b = model_registry.get_spacy("en_core_web_sm", disable=["tagger"])
            self.assertIs(a, b)
            load.assert_called_once_with("en_core_web_sm", disable=["tagger"])



    def test_get_faiss_index_cached(self):
        fake_faiss = mock.Mock()
        fake_faiss.read_index.return_value = object()
        with mock.patch.object(model_registry, "faiss", fake_faiss):
            a = model_registry.get_faiss_index("path.idx")
            b = model_registry.get_faiss_index("path.idx")
            self.assertIs(a, b)
            fake_faiss.read_index.assert_called_once_with("path.idx")


if __name__ == "__main__":
    unittest.main()
