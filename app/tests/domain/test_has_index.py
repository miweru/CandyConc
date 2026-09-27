import shutil
import tempfile
import unittest
import json
from pathlib import Path

from candyconc.domain.corpus import has_index


class TestHasIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def _write_index(self, meta: str = "{}") -> None:
        (self.tmp / "meta.bin").write_bytes(b"\\x00")
        (self.tmp / "meta.json").write_text(meta)

    def _write_manifest(self, *, complete: bool = True) -> None:
        (self.tmp / "index_manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "import_mode": "test",
                    "paired": False,
                    "pair_axes": [],
                    "annotation_source": "test",
                    "capabilities": {},
                    "dtypes": {},
                    "build_fingerprint": "fixture",
                    "created_at": "2026-06-12T00:00:00Z",
                    "complete": complete,
                }
            ),
            encoding="utf-8",
        )

    def test_valid_index(self) -> None:
        self._write_index()
        self.assertTrue(has_index(self.tmp))

    def test_missing_index_file(self) -> None:
        (self.tmp / "meta.json").write_text("{}")
        self.assertFalse(has_index(self.tmp))

    def test_invalid_meta(self) -> None:
        (self.tmp / "meta.bin").write_bytes(b"\\x00")
        (self.tmp / "meta.json").write_text("{invalid}")
        self.assertTrue(has_index(self.tmp))

    def test_incomplete_manifest_is_not_ready(self) -> None:
        self._write_index()
        self._write_manifest(complete=False)
        self.assertFalse(has_index(self.tmp))

    def test_nonexistent_path(self) -> None:
        path = self.tmp / "does_not_exist"
        self.assertFalse(has_index(path))


if __name__ == "__main__":
    unittest.main()
