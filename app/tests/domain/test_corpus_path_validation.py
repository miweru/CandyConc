import tempfile
import unittest
from pathlib import Path

from candyconc.domain.corpus import normalize_corpus_name, resolve_corpus_path


class TestCorpusPathValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_normalize_accepts_single_segment_name(self) -> None:
        self.assertEqual(normalize_corpus_name("demo_index"), "demo_index")

    def test_normalize_rejects_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "Ungültiger Korpusname"):
            normalize_corpus_name("../../secret")

    def test_normalize_rejects_absolute_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "Ungültiger Korpusname"):
            normalize_corpus_name("/tmp/secret")

    def test_resolve_keeps_path_under_base_dir(self) -> None:
        name, path = resolve_corpus_path(self.base_dir, "demo")
        self.assertEqual(name, "demo")
        self.assertEqual(
            path,
            (self.base_dir / "demo").resolve(strict=False),
        )


if __name__ == "__main__":
    unittest.main()
