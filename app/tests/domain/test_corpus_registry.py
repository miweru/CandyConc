import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import candyconc.domain.corpus as corpus


class TestCorpusRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "corpora.json"
        self.patcher = patch.object(corpus, "_REGISTRY_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_load_defaults(self):
        reg = corpus.CorpusRegistry.load()
        self.assertEqual(reg.indices, [])
        self.assertIsNone(reg.active)

    def test_register_and_unregister(self):
        reg = corpus.CorpusRegistry.load()
        p1 = Path("/a")
        p2 = Path("/b")
        reg.register(p1, activate=True)
        reg.register(p2)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["indices"], [str(p1), str(p2)])
        self.assertEqual(data["active"], str(p1))
        reg.unregister(p1)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["indices"], [str(p2)])
        self.assertEqual(data["active"], str(p2))

    def test_load_invalid_json(self):
        # Current contract (src/candyconc/domain/corpus.py, load()): an
        # unreadable registry file fails fast with RuntimeError instead of
        # silently returning an empty registry.
        self.path.write_text("{invalid}")
        with self.assertRaisesRegex(RuntimeError, "Korpus Registry unlesbar"):
            corpus.CorpusRegistry.load()

    def test_save_creates_parent(self):
        new_path = self.path.parent / "sub" / "corpora.json"
        with patch.object(corpus, "_REGISTRY_PATH", new_path):
            reg = corpus.CorpusRegistry(indices=["/x"], active="/x")
            reg.save()
            self.assertTrue(new_path.is_file())

if __name__ == "__main__":
    unittest.main()

