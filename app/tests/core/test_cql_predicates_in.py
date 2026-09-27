import numpy as np

from cqlhpc.ast import Cond
from cqlhpc import predicates


class _FakeLexicon:
    def __init__(self, mapping: dict[str, int]) -> None:
        self._mapping = mapping

    def get_id(self, value: str) -> int:
        return int(self._mapping.get(value, 0))


class _FakeCorpus:
    def __init__(self, mapping: dict[str, int]) -> None:
        self._lex = _FakeLexicon(mapping)

    def lexicon(self, _attr: str):
        return self._lex


def test_in_operator_falls_back_to_python_lookup_when_cython_ids_empty(monkeypatch) -> None:
    monkeypatch.setattr(predicates, "_cy_lex_lookup_id", None)
    monkeypatch.setattr(
        predicates,
        "_cy_lex_lookup_ids",
        lambda *args, **kwargs: np.empty((0,), dtype=np.int32),
    )
    monkeypatch.setattr(
        predicates,
        "_fast_lex_arrays",
        lambda _lex: (None, None, None, None, None, 0),
    )
    cond = Cond(attr="word", op="in", value=["hase", "x"])
    ids = predicates._value_to_type_ids(cond, _FakeCorpus({"hase": 17}))
    assert ids is not None
    assert ids.tolist() == [17]
