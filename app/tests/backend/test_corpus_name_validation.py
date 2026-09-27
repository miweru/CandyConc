import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import candyconc.services.backend.server as server


class TestCorpusNameValidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.corpus_dir = Path(self.tmp.name)
        self.corpus_dir_patch = patch.object(server, "_CORPUS_DIR", self.corpus_dir)
        self.indices_patch = patch.object(server, "_LANG_INDICES", {})
        self.corpus_dir_patch.start()
        self.indices_patch.start()

    def tearDown(self) -> None:
        self.indices_patch.stop()
        self.corpus_dir_patch.stop()
        self.tmp.cleanup()

    def test_get_corpus_rejects_traversal_name(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            server.get_corpus("../../secret")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Ungültiger Korpusname")

    def test_get_corpus_rejects_absolute_name(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            server.get_corpus("/tmp/secret")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Ungültiger Korpusname")

    def test_get_corpus_loads_valid_corpus_dir(self) -> None:
        expected_path = (self.corpus_dir / "demo").resolve(strict=False)
        sentinel = object()
        with patch.object(
            server,
            "_resolve_catalogue_corpus_index_path",
            return_value=("demo", expected_path),
        ), patch.object(
            server, "CorpusIndex", return_value=sentinel
        ) as corpus_index:
            result = server.get_corpus("demo")

        self.assertIs(result, sentinel)
        corpus_index.assert_called_once_with(expected_path)


if __name__ == "__main__":
    unittest.main()
