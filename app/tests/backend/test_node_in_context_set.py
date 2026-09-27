"""Der Knoten gehoert wahlweise in die Kontextmenge.

Publikationen unterscheiden sich in dieser Konvention. Heinrich/Evert 2024
setzen ``node_removed_from_context = false`` und argumentieren ausdruecklich
gegen das Entfernen (contra Evert 2004). Unsere Naht schloss den Knoten per
Konstruktion aus, und ohne die Option war ihre Tabelle nicht reproduzierbar:
R1 lag bei 12.330 gegen publizierte 13.344, mit Knoten bei 13.199.

Geprueft wird gegen das Orakel der Engine, nicht gegen eine ausgedachte Zahl,
und beide Richtungen stehen hier: ohne die Gegenprobe waere ein
``knoten_im_kontext``, das gar nichts tut, gruen.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from candyconc.core.fast_index_backend import FastIndexBackend
from candyconc.services.tools.context_keyness import (
    _vereinige,
    context_token_counts,
)

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


class TestVereinige:
    """Der Verschmelzer, ohne Index."""

    def test_disjunkte_intervalle_bleiben(self):
        s, e = _vereinige(np.array([0, 10]), np.array([5, 15]))
        assert s.tolist() == [0, 10]
        assert e.tolist() == [5, 15]

    def test_ueberlappende_verschmelzen(self):
        s, e = _vereinige(np.array([0, 3]), np.array([5, 8]))
        assert s.tolist() == [0]
        assert e.tolist() == [8]

    def test_beruehrende_verschmelzen_denn_es_ist_eine_positionsmenge(self):
        s, e = _vereinige(np.array([5, 10]), np.array([10, 11]))
        assert s.tolist() == [5]
        assert e.tolist() == [11]

    def test_enthaltene_verschwinden(self):
        s, e = _vereinige(np.array([0, 2]), np.array([10, 4]))
        assert s.tolist() == [0]
        assert e.tolist() == [10]

    def test_unsortierte_eingabe_wird_sortiert(self):
        s, e = _vereinige(np.array([10, 0]), np.array([15, 5]))
        assert s.tolist() == [0, 10]
        assert e.tolist() == [5, 15]

    def test_leere_eingabe(self):
        s, e = _vereinige(np.zeros(0, np.int64), np.zeros(0, np.int64))
        assert s.size == 0 and e.size == 0

    def test_die_gesamtmasse_waechst_nie(self):
        """Eine Vereinigung kann nicht mehr Positionen ergeben als die Summe."""
        rng = np.random.default_rng(3)
        for _ in range(200):
            a = rng.integers(0, 500, 40).astype(np.int64)
            b = a + rng.integers(1, 30, 40).astype(np.int64)
            s, e = _vereinige(a, b)
            assert int((e - s).sum()) <= int((b - a).sum())
            assert bool(np.all(s[1:] > e[:-1])), "Ergebnis nicht disjunkt"


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestAmEchtenIndex:
    @staticmethod
    def _knoten(backend) -> str:
        lex = backend.lexicons.word
        ids = np.arange(1, int(lex.vocab_size), dtype=np.int64)
        freqs = np.asarray(lex.get_freqs_for_ids(ids), dtype=np.int64)
        namen = list(lex.get_strings_for_ids(ids))
        for i in np.argsort(-freqs):
            wort = str(namen[i])
            if wort.isalpha() and len(wort) > 1 and int(freqs[i]) <= 20_000:
                return wort
        raise AssertionError("kein brauchbarer Knoten")

    def test_mit_knoten_sind_es_mehr_positionen(self):
        b = FastIndexBackend(_INDEX_PATH)
        q = 'cql:[word="%s"]' % self._knoten(b)
        _f0, p0, kn0, _o0 = context_token_counts(b, q, window_left=5, window_right=5)
        _f1, p1, kn1, _o1 = context_token_counts(
            b, q, window_left=5, window_right=5, knoten_im_kontext=True
        )
        assert kn0 == kn1 > 0, "Knotenzahl darf sich nicht aendern"
        assert p1 > p0, "knoten_im_kontext hat nichts bewirkt: %d == %d" % (p0, p1)
        # Hoechstens ein Token je Knoten kommt dazu, und weniger, wenn ein
        # Knoten schon im Fenster eines anderen liegt.
        assert p1 - p0 <= kn0, "mehr Zuwachs als Knoten: %d gegen %d" % (p1 - p0, kn0)

    def test_die_invariante_haelt_auch_mit_knoten(self):
        b = FastIndexBackend(_INDEX_PATH)
        q = 'cql:[word="%s"]' % self._knoten(b)
        freq, pos, _kn, ohne = context_token_counts(
            b, q, window_left=5, window_right=5, knoten_im_kontext=True
        )
        assert sum(freq.values()) + ohne == pos

    def test_der_knoten_steht_dann_in_seiner_eigenen_liste(self):
        """Die Gegenprobe zum bisherigen Verhalten, als Zahl."""
        b = FastIndexBackend(_INDEX_PATH)
        wort = self._knoten(b)
        q = 'cql:[word="%s"]' % wort
        ohne_k, _p0, kn, _o0 = context_token_counts(b, q, window_left=5, window_right=5)
        mit_k, _p1, _kn, _o1 = context_token_counts(
            b, q, window_left=5, window_right=5, knoten_im_kontext=True
        )
        # Ohne die Option taucht der Knoten nur auf, wenn er in seinem
        # eigenen Fenster wiederkehrt. Mit der Option zaehlt jede Fundstelle.
        assert mit_k.get(wort, 0) > ohne_k.get(wort, 0)
        assert mit_k.get(wort, 0) - ohne_k.get(wort, 0) <= kn

    def test_ohne_die_option_bleibt_alles_wie_bisher(self):
        """Positive Klasse gegen eine Regression im Vorgabepfad."""
        b = FastIndexBackend(_INDEX_PATH)
        q = 'cql:[word="%s"]' % self._knoten(b)
        f1, p1, k1, o1 = context_token_counts(b, q, window_left=5, window_right=5)
        f2, p2, k2, o2 = context_token_counts(
            b, q, window_left=5, window_right=5, knoten_im_kontext=False
        )
        assert (p1, k1, o1) == (p2, k2, o2)
        assert f1 == f2
