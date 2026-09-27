"""Der Null-Treffer-Fall wird am Typ erkannt, nicht am Meldungstext.

Bis zum 2026-09-17 entschied ``"liefert keine Treffer" in str(exc)`` an vier
Nahtstellen darueber, ob ein Fehler null Treffer oder einen Ausfall bedeutet.
Jede Probe hier faehrt beide Klassen: die typisierte Ausnahme MIT fremdem
Text muss verschluckt werden, ein blosser ``ValueError`` MIT dem alten Satz
muss durchschlagen.
"""

from types import SimpleNamespace

import pytest

from candyconc.core import cql_engine
from cqlhpc.errors import EmptyMatchError

ALTER_SATZ = "CQL Bedingung liefert keine Treffer: wordin['x']"
FREMDER_TEXT = "nichts im Lexikon"


def _fake_search_engine(exc):
    class FakeEngine:
        def search(self, _query, options=None):
            raise exc

    return FakeEngine()


def _stelle_ein(monkeypatch, engine):
    monkeypatch.setattr(cql_engine, "_load_cqlhpc_env", lambda _p: {})
    monkeypatch.setattr(cql_engine, "_get_engine", lambda _b: (None, engine))


def test_search_liefert_leer_bei_typisiertem_fehler(monkeypatch) -> None:
    backend = SimpleNamespace(index_path=".")
    _stelle_ein(monkeypatch, _fake_search_engine(EmptyMatchError(FREMDER_TEXT)))

    assert cql_engine.search_cql_matches_backend(backend, 'cql:[word="x"]') == []


def test_search_reicht_blossen_valueerror_mit_altem_satz_durch(monkeypatch) -> None:
    backend = SimpleNamespace(index_path=".")
    _stelle_ein(monkeypatch, _fake_search_engine(ValueError(ALTER_SATZ)))

    with pytest.raises(ValueError, match="liefert keine Treffer"):
        cql_engine.search_cql_matches_backend(backend, 'cql:[word="x"]')


def _stelle_count_ein(monkeypatch, exc):
    class FakeQueryEngine:
        def __init__(self, corpus):
            self.corpus = corpus

        def count(self, _query, options=None):
            raise exc

    monkeypatch.setattr(cql_engine, "_load_cqlhpc_env", lambda _p: {})
    monkeypatch.setattr(cql_engine, "_get_engine", lambda _b: ("dummy-corpus", None))
    monkeypatch.setattr(cql_engine, "QueryEngine", FakeQueryEngine)


def test_count_liefert_null_bei_typisiertem_fehler(monkeypatch) -> None:
    backend = SimpleNamespace(index_path=".")
    _stelle_count_ein(monkeypatch, EmptyMatchError(FREMDER_TEXT))

    assert cql_engine.count_cql_matches_backend(backend, 'cql:[word="x"]') == 0


def test_count_reicht_blossen_valueerror_mit_altem_satz_durch(monkeypatch) -> None:
    backend = SimpleNamespace(index_path=".")
    _stelle_count_ein(monkeypatch, ValueError(ALTER_SATZ))

    with pytest.raises(ValueError, match="liefert keine Treffer"):
        cql_engine.count_cql_matches_backend(backend, 'cql:[word="x"]')


def test_alternationszweig_verschluckt_nur_den_typisierten_fehler() -> None:
    from cqlhpc.engine import _is_recognised_empty_match

    assert _is_recognised_empty_match(EmptyMatchError(FREMDER_TEXT)) is True
    assert _is_recognised_empty_match(ValueError(ALTER_SATZ)) is False


def test_zaehlnaht_des_servers_entscheidet_am_typ() -> None:
    from candyconc.services.backend.server import _is_cql_oov_zero_hits
    from cqlhpc.errors import UnresolvableConditionError

    assert _is_cql_oov_zero_hits(EmptyMatchError(FREMDER_TEXT)) is True
    assert _is_cql_oov_zero_hits(UnresolvableConditionError(FREMDER_TEXT)) is True
    assert _is_cql_oov_zero_hits(ValueError(ALTER_SATZ)) is False
