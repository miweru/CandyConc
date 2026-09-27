import hashlib
import unittest
from pathlib import Path

from candyconc.tools.embedding_package import download_embedding, load_embedding, EMB_DIR


class TestEmbeddingPackage(unittest.IsolatedAsyncioTestCase):
    async def test_download_and_load(self):
        tmp = Path(__file__).parent / "sample_emb.txt"
        tmp.write_text("fox 0.1 0.2\ndog 0.2 0.1\n", encoding="utf-8")
        sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
        url = tmp.as_uri()
        name = "sample"
        dest = EMB_DIR / "sample.txt"
        if dest.exists():
            dest.unlink()
        # file:// URLs are rejected on the server-exposed path by default
        # (src/candyconc/tools/embedding_package.py); local-file ingestion
        # needs the explicit opt-in.
        with self.assertRaises(ValueError):
            await download_embedding(name, url, sha)
        path = await download_embedding(name, url, sha, allow_file_url=True)
        self.assertTrue(path.exists())
        mapping = load_embedding(name)
        self.assertIn("fox", mapping)
        self.assertEqual(mapping["fox"], [0.1, 0.2])
        # cleanup
        path.unlink()
        tmp.unlink()
        if EMB_DIR.exists() and not any(EMB_DIR.iterdir()):
            EMB_DIR.rmdir()


if __name__ == "__main__":
    unittest.main()
