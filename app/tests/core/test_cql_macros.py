from types import SimpleNamespace

import numpy as np
import pytest

from candyconc.core import cql_macros
from candyconc.core.cql_macros import expand_sim_cql, normalize_query_input, normalize_sim_syntax


def test_normalize_sim_bare_syntax() -> None:
    assert normalize_sim_syntax("sim Hase") == "sim Hase"


def test_normalize_query_input_cql_space_alias() -> None:
    assert normalize_query_input("cql sim Hase") == "cql sim Hase"


def test_normalize_query_input_sim_shortcut() -> None:
    assert normalize_query_input('sim("Hase", k=30)') == 'cql:[sim="Hase"&k=30]'


def test_normalize_query_input_cql_sim_colon_only() -> None:
    assert normalize_query_input('cql:sim("Hase", k=30)') == 'cql:[sim="Hase"&k=30]'


def test_normalize_query_input_bare_bracket_cql() -> None:
    assert normalize_query_input('[word="Politik"]') == 'cql:[word="Politik"]'


def test_normalize_query_input_bare_within_cql() -> None:
    assert (
        normalize_query_input('within(<s>, [word="du"] [word="gehst"])')
        == 'cql:within(<s>, [word="du"] [word="gehst"])'
    )


def test_normalize_query_input_keeps_legacy_dependency_syntax() -> None:
    assert normalize_query_input('[pos=VERB] >nsubj [pos=NOUN]') == '[pos=VERB] >nsubj [pos=NOUN]'


class _FakeLexicon:
    def __init__(self, words: list[str]) -> None:
        self._ids = {word: idx + 1 for idx, word in enumerate(words)}

    def get_id(self, word: str) -> int:
        return self._ids.get(word, 0)


class _FakeStrings:
    def __init__(self, mapping: dict[int, str]) -> None:
        self._mapping = mapping

    def __getitem__(self, key: int) -> str:
        return self._mapping[int(key)]


class _FakeLexeme:
    def __init__(self, word: str) -> None:
        self.is_stop = word.lower() in {"und", "oder", "ja"}
        self.is_punct = not any(ch.isalnum() for ch in word)
        self.like_num = word.isdigit()


class _FakeVectors:
    def __init__(self, entries: list[tuple[int, float]]) -> None:
        self._entries = entries
        self.n_keys = len(entries)

    def most_similar(self, _vec, n: int):
        entries = self._entries[: int(n)]
        keys = np.asarray([[key for key, _score in entries]], dtype=np.uint64)
        rows = np.zeros_like(keys, dtype=np.int64)
        scores = np.asarray([[score for _key, score in entries]], dtype=np.float32)
        return keys, rows, scores


class _FakeVocab:
    def __init__(self, key_to_word: dict[int, str], scores: list[tuple[int, float]]) -> None:
        self.strings = _FakeStrings(key_to_word)
        self.vectors = _FakeVectors(scores)

    def __getitem__(self, word: str) -> _FakeLexeme:
        return _FakeLexeme(word)


class _FakeNlp:
    def __init__(self, key_to_word: dict[int, str], scores: list[tuple[int, float]]) -> None:
        self.vocab = _FakeVocab(key_to_word, scores)

    def __call__(self, _term: str):
        return SimpleNamespace(vector=np.ones(3, dtype=np.float32))


def _fake_backend(words: list[str]):
    return SimpleNamespace(
        lexicons=SimpleNamespace(word=_FakeLexicon(words)),
        index_path="",
    )


def test_expand_sim_rejects_low_score_tail_and_stopwords(monkeypatch: pytest.MonkeyPatch) -> None:
    key_to_word = {1: "und", 2: "Tusse", 3: "Bergepanzer"}
    scores = [(1, 0.99), (2, 0.31), (3, 0.23)]
    monkeypatch.setattr(cql_macros, "_corpus_spacy_model", lambda _corpus_key: _FakeNlp(key_to_word, scores))
    monkeypatch.setattr(cql_macros, "_SIM_MIN_SCORE", 0.55)
    cql_macros._SIM_CACHE.clear()

    with pytest.raises(RuntimeError, match="oberhalb Score 0.55"):
        expand_sim_cql('cql:[sim="Hase"&k=5]', _fake_backend(["und", "Tusse", "Bergepanzer"]))


def test_expand_sim_keeps_only_content_candidates_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    key_to_word = {1: "und", 2: "Kaninchen", 3: "Tusse"}
    scores = [(1, 0.99), (2, 0.78), (3, 0.31)]
    monkeypatch.setattr(cql_macros, "_corpus_spacy_model", lambda _corpus_key: _FakeNlp(key_to_word, scores))
    monkeypatch.setattr(cql_macros, "_SIM_MIN_SCORE", 0.55)
    cql_macros._SIM_CACHE.clear()

    expanded = expand_sim_cql('cql:[sim="Hase"&k=5]', _fake_backend(["und", "Kaninchen", "Tusse"]))

    assert expanded == '[word in {"Kaninchen"}]'
