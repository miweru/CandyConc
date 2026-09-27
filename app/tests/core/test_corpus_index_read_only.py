from __future__ import annotations

from pathlib import Path

import pytest

import candyconc.core.corpus_index as ci


class _StubBackend:
    """Minimal stand-in so CorpusIndex.__init__ needs no real index files."""

    def __init__(self, path):
        self.path = path


@pytest.fixture
def index_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(ci, "FastIndexBackend", _StubBackend)
    return tmp_path


def test_read_only_open_does_not_mutate(index_dir: Path) -> None:
    # A legacy tuned-env file present, no config.json yet.
    env_path = index_dir / "cqlhpc_tuned.env"
    env_path.write_text("CANDYCONC_CQLHPC_FOO=1\n", encoding="utf-8")

    idx = ci.CorpusIndex(index_dir)  # read_only defaults to True

    assert idx.read_only is True
    # No config.json written on open ...
    assert not (index_dir / "config.json").exists()
    # ... and the legacy env file is read but neither migrated nor deleted.
    assert env_path.exists()
    # The tuned env is still applied/available in-memory.
    assert idx.get_cqlhpc_env().get("CANDYCONC_CQLHPC_FOO") == "1"


def test_read_only_setters_raise(index_dir: Path) -> None:
    idx = ci.CorpusIndex(index_dir)
    with pytest.raises(RuntimeError):
        idx.set_ranking_metric("bm25")
    with pytest.raises(RuntimeError):
        idx.set_autotune_lock_ttl(123)
    with pytest.raises(RuntimeError):
        idx.set_cqlhpc_env({"CANDYCONC_CQLHPC_FOO": "2"})


def test_writable_open_migrates_and_persists(index_dir: Path) -> None:
    env_path = index_dir / "cqlhpc_tuned.env"
    env_path.write_text("CANDYCONC_CQLHPC_FOO=1\n", encoding="utf-8")

    idx = ci.CorpusIndex(index_dir, read_only=False)

    assert idx.read_only is False
    # Writable open persists ranking_metric and migrates the env file away.
    assert (index_dir / "config.json").exists()
    assert not env_path.exists()
    assert idx.get_cqlhpc_env().get("CANDYCONC_CQLHPC_FOO") == "1"

    # Setters work when writable.
    idx.set_ranking_metric("bm25")
    reopened = ci.CorpusIndex(index_dir)
    assert reopened.ranking_metric == "bm25"
