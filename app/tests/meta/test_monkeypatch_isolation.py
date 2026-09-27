import os

class TestMonkeypatchIsolation:
    def test_set_env(self, monkeypatch):
        monkeypatch.setenv("TEMP_VAR", "VALUE")
        assert os.environ.get("TEMP_VAR") == "VALUE"

    def test_env_cleared(self):
        assert "TEMP_VAR" not in os.environ
