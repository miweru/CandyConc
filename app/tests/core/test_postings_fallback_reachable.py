"""The postings fallback remains reachable without the compiled extension.

Exercise the heap-based NumPy path and compare its results with the
extension when available. An extension guard must not block this path."""

from __future__ import annotations

import numpy as np
import pytest

import cqlhpc.postings as P


class _NurListe:
    """Ein Index, der nur ``list`` kann. Genau der Rueckfall-Zweig."""

    def __init__(self, tafel):
        self.tafel = tafel

    def list(self, tid):
        return self.tafel[int(tid)]


class _MitOffsets:
    """Ein Index mit offsets/positions und OHNE ``list``: kein Rueckfall."""

    def __init__(self):
        self.offsets = np.array([0, 1], dtype=np.int32)
        self.positions = np.array([7], dtype=np.int32)


@pytest.fixture
def ohne_erweiterung(monkeypatch):
    """Die Erweiterung abschalten, wie auf einer ungebauten Installation."""

    monkeypatch.setattr(P, "_cy_merge_postings_many", None)
    monkeypatch.setattr(P, "_cy_union_positions_many", None)


def _tafel(rng, n):
    return {
        t: np.unique(rng.integers(0, 400, size=int(rng.integers(0, 60))))
        .astype(np.int32)
        for t in range(n)
    }


def test_der_rueckfall_liefert_dasselbe_wie_die_erweiterung(monkeypatch):
    """Der Kern: gleiche Eingabe, gleiches Ergebnis, mit und ohne Cython."""

    if P._cy_merge_postings_many is None:
        pytest.skip("Erweiterung nicht gebaut, Vergleich nicht moeglich")
    rng = np.random.default_rng(20260831)
    for versuch in range(50):
        n = int(rng.integers(2, 7))
        idx = _NurListe(_tafel(rng, n))
        tids = list(range(n))
        mit = P.merge_postings_many(idx, tids)

        with monkeypatch.context() as m:
            m.setattr(P, "_cy_merge_postings_many", None)
            m.setattr(P, "_cy_union_positions_many", None)
            ohne = P.merge_postings_many(idx, tids)

        assert np.array_equal(mit, ohne), (
            f"Versuch {versuch}: mit={mit[:8]} ohne={ohne[:8]}"
        )


def test_der_rueckfall_stimmt_mit_einer_unabhaengigen_referenz(
    ohne_erweiterung,
):
    """Nicht nur gleich, sondern RICHTIG: gegen np.unique(concatenate)."""

    rng = np.random.default_rng(4711)
    for _ in range(50):
        n = int(rng.integers(2, 7))
        tafel = _tafel(rng, n)
        ergebnis = P.merge_postings_many(_NurListe(tafel), list(range(n)))
        referenz = np.unique(
            np.concatenate([tafel[t] for t in range(n)] + [np.empty(0, np.int32)])
        )
        assert np.array_equal(
            np.asarray(ergebnis, dtype=np.int64),
            np.asarray(referenz, dtype=np.int64),
        )


def test_ohne_erweiterung_wird_nicht_mehr_geworfen(ohne_erweiterung):
    """Die Regression, ausbuchstabiert: vorher flog hier ein RuntimeError."""

    idx = _NurListe({0: np.array([1, 5], np.int32), 1: np.array([5, 9], np.int32)})
    ergebnis = P.merge_postings_many(idx, [0, 1])
    assert list(ergebnis) == [1, 5, 9], list(ergebnis)


def test_ohne_rueckfall_bleibt_die_ehrliche_meldung(ohne_erweiterung):
    """Wo es KEINEN Rueckfall gibt, muss der Grund weiter genannt werden."""

    with pytest.raises(RuntimeError, match="Extension fehlt"):
        P.merge_postings_many(_MitOffsets(), [0, 1])


def test_ein_einzelnes_type_id_braucht_nie_eine_erweiterung(ohne_erweiterung):
    """Der Kurzschluss oben in der Funktion bleibt unberuehrt."""

    idx = _NurListe({0: np.array([3, 4], np.int32)})
    assert list(P.merge_postings_many(idx, [0])) == [3, 4]
    assert P.merge_postings_many(idx, []).size == 0
