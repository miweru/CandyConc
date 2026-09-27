from pathlib import Path

class TestTmpPathIsolation:
    def test_write_file(self, tmp_path: Path):
        f = tmp_path / "foo.txt"
        f.write_text("bar")
        assert f.read_text() == "bar"

    def test_tmp_empty(self, tmp_path: Path):
        assert list(tmp_path.iterdir()) == []
