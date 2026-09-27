"""Zwei Filter, die nichts taten und Erfolg meldeten.

1. POS ohne Wortartenkarte
--------------------------
``compute_keyness`` filterte nur bei ``if pos and pos_map``. Ein ``pos``
OHNE Karte fiel damit still aus, und das Ergebnis war byte-gleich zu dem
ganz ohne Filter, samt Artikeln und Verben, mit HTTP 200:

    compute_keyness(T, R, pos="NOUN", pos_map=KARTE)
        -> ['Hund', 'Katze']
    compute_keyness(T, R, pos="NOUN", pos_map=None)
        -> ['Hund', 'Katze', 'der', 'langsam', 'laufen', 'schnell']
    compute_keyness(T, R)
        -> dieselbe Liste

Betroffen sind BEIDE Wortlisten-Eingaenge, die REST-Route
``/analysis/keyness`` und der Copilot-Wrapper. Der Docset-Pfad braucht die
Karte nicht, er liest die Wortart aus dem Index, und nur die
Wortlisten-Variante ist auf sie angewiesen. Sie wirft jetzt.

2. Die stille Kappung des Docset-Scans
--------------------------------------
``_search_docset_doc_ids`` kappt bei gesetztem ``limit`` den TREFFERSCAN,
und die Rueckgabe verriet das nicht: ``hit_doc_count`` war in jedem Fall
gleich der Dokumentzahl. Am Testindex, ``cql:[pos="NOUN"]``:

    limit=None   1995 Dokumente,  56.080 Tokens, hit_doc_count 1995
    limit=5000   1051 Dokumente,  28.995 Tokens, hit_doc_count 1051
    limit=100      24 Dokumente,     632 Tokens, hit_doc_count   24

Alle drei sehen gleich vollstaendig aus. Der Wiederherstellungspfad
``_resolve_subcorpus_doc_ids`` loest dagegen IMMER ungedeckelt auf, weil
eine Subkorpus-Definition kein ``limit`` speichert. Dieselbe Abfrage
lieferte damit beim Anlegen 1051 und beim Wiederherstellen 1995
Dokumente, ohne dass eine der beiden Antworten das sagte, waehrend der
Modul-Docstring "creation == restore reproduces the same doc set"
versprach.

Eine Kappung darf sein, sie darf nur nicht schweigen.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from candyconc.services.tools.keyness import compute_keyness

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")

_ZIEL = ["Hund", "Hund", "Hund", "laufen", "schnell", "der", "der"]
_REFERENZ = ["Katze", "Katze", "laufen", "langsam", "der"]
_KARTE = {
    "Hund": "NOUN", "Katze": "NOUN", "laufen": "VERB",
    "schnell": "ADJ", "langsam": "ADJ", "der": "DET",
}


class TestPosBrauchtEineWortartenkarte:
    def test_pos_ohne_karte_wirft(self):
        with pytest.raises(ValueError, match="pos_map"):
            compute_keyness(_ZIEL, _REFERENZ, pos="NOUN")

    def test_pos_mit_karte_filtert_wirklich(self):
        """Die Gegenprobe: der Filter darf nicht einfach abgeschafft sein."""
        woerter = sorted(
            compute_keyness(_ZIEL, _REFERENZ, pos_map=_KARTE, pos="NOUN")[
                "word"
            ].tolist()
        )
        assert woerter == ["Hund", "Katze"]

    def test_ohne_pos_bleibt_alles(self):
        woerter = sorted(
            compute_keyness(_ZIEL, _REFERENZ)["word"].tolist()
        )
        assert "der" in woerter and "laufen" in woerter

    def test_karte_ohne_pos_filtert_nicht(self):
        """Eine Karte ohne gewuenschte Wortart hat nichts zu filtern."""
        mit = sorted(
            compute_keyness(_ZIEL, _REFERENZ, pos_map=_KARTE)["word"].tolist()
        )
        ohne = sorted(compute_keyness(_ZIEL, _REFERENZ)["word"].tolist())
        assert mit == ohne


@pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestDieKappungMeldetSich:
    @staticmethod
    def _scan(limit):
        from candyconc.services.backend import server as srv

        bericht: dict = {}
        doc_ids, _hits, _refs = srv._search_docset_doc_ids(
            srv.get_corpus(None),
            'cql:[pos="NOUN"]',
            meta_filters={}, ai_filters={},
            include_ai=True, include_human=True,
            limit=limit, bericht=bericht,
        )
        return doc_ids, bericht

    def test_ohne_deckel_meldet_der_bericht_keine_kappung(self):
        doc_ids, bericht = self._scan(None)
        if doc_ids.size == 0:
            pytest.skip("Index kennt keine NOUN-Treffer")
        assert bericht["gekappt"] is False
        assert bericht["deckel"] is None

    @pytest.mark.parametrize("limit", [100, 5000])
    def test_mit_deckel_meldet_der_bericht_die_kappung(self, limit):
        voll, _ = self._scan(None)
        if voll.size == 0:
            pytest.skip("Index kennt keine NOUN-Treffer")
        gekappt, bericht = self._scan(limit)
        assert bericht["gekappt"] is True, bericht
        assert bericht["deckel"] == limit
        assert bericht["gescannte_treffer"] == limit
        # Und der Deckel wirkt wirklich: sonst waere die Meldung eine
        # Warnung ohne Anlass, also selbst wieder eine Unwahrheit.
        assert gekappt.size < voll.size

    def test_die_aufrufstelle_ohne_bericht_bleibt_unveraendert(self):
        """Zehn Aufrufer entpacken das Dreier-Tupel. Sie duerfen nichts merken."""
        from candyconc.services.backend import server as srv

        doc_ids, hits, refs = srv._search_docset_doc_ids(
            srv.get_corpus(None),
            'cql:[pos="NOUN"]',
            meta_filters={}, ai_filters={},
            include_ai=True, include_human=True, limit=None,
        )
        mit_bericht, _ = self._scan(None)
        assert doc_ids.size == mit_bericht.size
        assert isinstance(hits, int) and isinstance(refs, int)

    def test_wiederherstellen_loest_ungedeckelt_auf(self):
        """Der Kern der Divergenz, in einer Zeile nachgewiesen."""
        from candyconc.services.backend import server as srv

        voll, _ = self._scan(None)
        if voll.size == 0:
            pytest.skip("Index kennt keine NOUN-Treffer")
        wieder = srv._resolve_subcorpus_doc_ids(
            srv.get_corpus(None), {"query": 'cql:[pos="NOUN"]'}
        )
        assert wieder.size == voll.size
        gekappt, _ = self._scan(5000)
        assert gekappt.size < wieder.size
