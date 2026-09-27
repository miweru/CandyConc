from types import SimpleNamespace

import numpy as np

from cqlhpc import predicates


class _Cache:
    def __init__(self) -> None:
        self._store = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value) -> None:
        self._store[key] = value


class _Backend:
    def __init__(self) -> None:
        self._regex_cache = _Cache()
        self.candidate_calls = []

    def _regex_candidates(self, attr: str, pattern: str, min_len: int, max_len: int | None):
        self.candidate_calls.append((attr, pattern, min_len, max_len))
        return np.array([1, 3], dtype=np.int32)


class _Lex:
    offsets = np.array([0, 1], dtype=np.int32)
    strings_view = memoryview(b"a")


def test_regex_type_ids_reuses_backend_cache_and_passes_pattern_string(monkeypatch) -> None:
    backend = _Backend()
    corpus = SimpleNamespace(backend=backend)
    lex = _Lex()
    regex_ids_calls = []

    def _regex_ids(offsets, strings_view, ids, rex, min_len, max_len):
        regex_ids_calls.append((ids.copy(), rex.pattern))
        return np.array([3], dtype=np.int32)

    def _regex_full(*args, **kwargs):
        raise AssertionError("full lexicon regex scan should not run when candidate narrowing is available")

    monkeypatch.setattr(predicates, "lexicon_match_regex_ids", _regex_ids)
    monkeypatch.setattr(predicates, "lexicon_match_regex", _regex_full)

    out1 = predicates._regex_to_type_ids(r"ab.*", lex, attr="word", corpus=corpus)
    out2 = predicates._regex_to_type_ids(r"ab.*", lex, attr="word", corpus=corpus)

    np.testing.assert_array_equal(out1, np.array([3], dtype=np.int32))
    np.testing.assert_array_equal(out2, np.array([3], dtype=np.int32))
    assert backend.candidate_calls == [("word", r"ab.*", 2, None)]
    assert len(regex_ids_calls) == 1
    np.testing.assert_array_equal(regex_ids_calls[0][0], np.array([1, 3], dtype=np.int32))
    assert regex_ids_calls[0][1] == r"ab.*"
