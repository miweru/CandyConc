"""NEAR zählt innerhalb eines Dokuments (Regression, Rest).

Ohne Dokumentgrenzen im Fenster verhält sich _near_im_dokument wie das native
near_positions, Treffer für Treffer. Über eine Grenze hinweg nicht mehr.
"""

import numpy as np
import pytest

from candyconc.domain import query_eval as qe


class _Grenzen:
    def __init__(self, anf):
        self._positions = np.asarray(anf, dtype=np.uint32)


class _Index:
    def __init__(self, anf, n):
        self.fast_index = type("F", (), {})()
        self.fast_index.boundaries = type("B", (), {})()
        self.fast_index.boundaries.document = _Grenzen(anf)
        self.fast_index.token_store = type("T", (), {"token_count": n})()


@pytest.mark.skipif(qe._near_positions_fast is None, reason="native Erweiterung fehlt")
def test_ein_dokument_gleich_dem_nativen_weg():
    rng = np.random.default_rng(7)
    for _ in range(50):
        links = np.unique(rng.integers(0, 400, 40)).astype(np.uint32)
        rechts = np.unique(rng.integers(0, 400, 30)).astype(np.uint32)
        d = int(rng.integers(0, 6))
        nativ = qe._near_positions_fast(links.copy(), rechts.copy(), d)
        neu = qe._near_im_dokument(links, rechts, d, _Index([0], 400))
        assert np.array_equal(np.asarray(nativ), neu), (d,)


def test_ueber_die_grenze_kein_treffer():
    # Dokument 0: 0..9, Dokument 1: 10..19. "links" endet Dokument 0, "rechts" beginnt Dokument 1.
    links = np.array([9], dtype=np.uint32)
    rechts = np.array([10], dtype=np.uint32)
    assert qe._near_im_dokument(links, rechts, 1, _Index([0, 10], 20)).size == 0
    assert qe._near_im_dokument(links, np.array([8], dtype=np.uint32), 1, _Index([0, 10], 20)).tolist() == [8, 9]
