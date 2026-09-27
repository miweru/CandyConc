from cqlhpc.autocomplete import complete
from types import SimpleNamespace

from candyconc.core import cql_engine


def _labels(text: str) -> set[str]:
    return {s.label for s in complete(text, len(text))}


def test_autocomplete_suggests_sim_attr() -> None:
    assert "sim" in _labels("[s")


def test_autocomplete_suggests_extended_attrs_from_capabilities() -> None:
    assert "ner" in _labels("[n")


def test_autocomplete_suggests_token_operators_from_capabilities() -> None:
    assert {"=", "!=", "~", "in"} <= _labels("[word")


def test_autocomplete_suggests_where_operators_from_capabilities() -> None:
    assert {"=", "!=", ">=", "<=", ">", "<"} <= _labels("where(source ")


def test_autocomplete_top_snippets_include_capability_snippets() -> None:
    labels = _labels("")
    assert '[sim="$1"&k=20]' in labels
    # Nachgezogen am 2026-09-02 mit dem Schnipsel der Registry. Die
    # Vorfassung ``where($1, $2)`` zeigte nicht, dass das erste Argument
    # feld="wert" ist, siehe tests/core/test_cqlf_where_conformance.py.
    assert 'where(model="x", $1)' in labels


def test_autocomplete_suggests_k_after_sim_clause() -> None:
    labels = _labels('[sim="Hasenfuss" & ')
    assert "k" in labels


def test_autocomplete_hides_k_when_already_present() -> None:
    labels = _labels('[sim="Hasenfuss" & k=20 & ')
    assert "k" not in labels


def test_analyse_cql_backend_returns_builder_json(monkeypatch) -> None:
    backend = SimpleNamespace(index_path=".")

    class FakeCorpus:
        pass

    class FakeQueryEngine:
        def __init__(self, corpus):
            self.corpus = corpus

        def _docset_from_where(self, _ast):
            return None

    monkeypatch.setattr(cql_engine, "FastCorpus", SimpleNamespace(from_backend=lambda _backend: FakeCorpus()))
    monkeypatch.setattr(cql_engine, "_load_cqlhpc_env", lambda _p: {})
    monkeypatch.setattr(cql_engine, "QueryEngine", FakeQueryEngine)
    monkeypatch.setattr(cql_engine, "cql_diagnose", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(cql_engine, "cql_complete", lambda *_args, **_kwargs: [])

    result = cql_engine.analyse_cql_backend(
        backend,
        'cql:where(source="mlsum", within(<s>, [lemma="Haus"] [pos="NN"]))',
    )

    assert result["errors"] == []
    assert result["builder"] is not None
    assert result["builder"]["type"] == "where"
