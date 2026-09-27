from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import candyconc.core.query_runtime as qrt
from candyconc.tools import word_sketch as ws_mod


class _FakeWordLex:
    def __init__(self) -> None:
        self._ids = {"mensch": 1}
        self._words = {
            1: "Mensch",
            2: "kann",
            3: "unsere",
            4: "#",
        }
        self._freqs = {1: 12, 2: 20, 3: 11, 4: 100}
        self.total_tokens = 1000

    def get_id(self, word: str) -> int:
        return int(self._ids.get(str(word).casefold(), 0))

    def get_freq(self, word_id: int) -> int:
        return int(self._freqs.get(int(word_id), 0))

    def get_string(self, word_id: int) -> str:
        return self._words.get(int(word_id), "")


class _FakeRelLex:
    def __init__(self) -> None:
        self._rels = {1: "sb", 2: "nk", 3: "ROOT", 4: "punct"}

    def get_string(self, rel_id: int) -> str:
        return self._rels.get(int(rel_id), str(rel_id))


class _FakeStore:
    def __init__(self) -> None:
        self.head_ids = np.array([1, 2, 3], dtype=np.int64)
        self.rel_ids = np.array([1, 2, 3], dtype=np.uint32)
        self.token_count = 3
        self.word_stream = SimpleNamespace(
            offsets=np.array([0], dtype=np.uint64),
            data=np.array([0], dtype=np.uint8),
            block_size=128,
        )

    def get_positions_for_word_id(self, word_id: int) -> np.ndarray:
        assert int(word_id) == 1
        return np.array([0, 1, 2], dtype=np.uint32)


class _FakeFastIndex:
    def __init__(self) -> None:
        self.token_store = _FakeStore()
        self.lexicons = SimpleNamespace(word=_FakeWordLex(), rel=_FakeRelLex())


class _FakeIndex:
    def __init__(self) -> None:
        self.fast_index = _FakeFastIndex()


def test_word_sketch_filters_root_self_and_noise(monkeypatch):
    original = qrt._CORPUS_INDEX
    qrt._CORPUS_INDEX = _FakeIndex()

    def _fake_counts(*args, **kwargs):
        dep_counts = {
            1: {2: 2},       # sb_rev -> "kann"
            3: {1: 4},       # ROOT_rev -> self, must disappear
        }
        head_counts = {
            2: {3: 3, 1: 4},  # nk -> keep "unsere", drop self "Mensch"
            4: {4: 5},        # punct -> drop "#"
        }
        return dep_counts, head_counts

    monkeypatch.setattr(ws_mod, "word_sketch_counts", _fake_counts)
    try:
        tables = ws_mod.word_sketch("Mensch")
    finally:
        qrt._CORPUS_INDEX = original

    assert list(tables) == ["nk", "sb_rev"]
    nk_row = tables["nk"].iloc[0].to_dict()
    assert nk_row["word"] == "unsere"
    assert nk_row["f"] == 3
    assert nk_row["rank"] == 1
    expected = (12 * 11) / 1000
    assert nk_row["chi2_cell"] == pytest.approx(((3 - expected) ** 2) / expected)
    # Default surfaced score is now logDice (corpus-size-comparable; Rychlý 2008),
    # not the fragile single-cell chi-square contribution.
    assert nk_row["score_key"] == "logdice"
    assert tables["sb_rev"].iloc[0]["word"] == "kann"
    assert "ROOT" not in tables
    assert "ROOT_rev" not in tables
    assert "punct" not in tables
