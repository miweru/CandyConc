"""Die Konformitaetsmatrix fuer ``within()``, und was sie kostet, wenn sie fehlt.

``cqlf.level2.within`` stand auf ``tests="partial"``. Es faellt dadurch aus
der Beispielsyntax des Systemprompts, denn die zeigt nur Faehigkeiten, die
in ALLEN Dimensionen ``supported`` sind. Die Folge ist nicht bloss eine
Luecke im Papier.

LIVE am 2026-09-01. Die Fachagentin, die die Referenzantwort zu
``konstr-scharnier-dreigliedrig`` erstellt hat, schrieb in ihre Grenzen:

    "Die Zahl haengt daran, ob das Fenster die Satzgrenze ueberschreiten
     darf, und zwar um Faktor drei. Die CQL-Abfrage dieses Motors kann es
     nicht, ihr Abstandsoperator []{0,N} bleibt im Satz, sie findet 12
     Belege. Die Positionsrechnung ueber Dokumentgrenzen darf es und
     findet 38."

"Die CQL-Abfrage dieses Motors kann es nicht" ist FALSCH. Sie kann es mit
``within(<doc>, ...)``. Faktor drei auf einer echten Nutzerfrage, weil
eine vorhandene Syntax weder im Prompt noch in der Referenzarbeit
vorkam.

DIE SEMANTIK, die diese Datei festhaelt:

    Abfragen sind SATZINTERN als Vorgabe
    (core/cql_engine.py: within_sentences_by_default = True)

    within(<s>, X)     wiederholt die Vorgabe, aendert also nichts
    within(<doc>, X)   LOCKERT sie auf Dokumentgrenzen

WARUM EIN EIGENER, WINZIGER INDEX. Wie bei der Quantorenmatrix: jede
erwartete Zahl muss von Hand nachzaehlbar sein.

    Position  0 1 2 3 4 5 6 7 8 9 10 11
    Token     a b c . d e f . g h  i  .
    Satzanfaenge        0     4     8

    Satz 1: a b c .      Satz 2: d e f .      Satz 3: g h i .

Ein Paar mit einem Token Abstand INNERHALB eines Satzes ist a _ c.
Ein Paar mit einem Token Abstand UEBER die Satzgrenze ist c _ d
(c auf 2, Luecke auf 3, d auf 4, und Satz 2 beginnt auf 4).

DIESER TEST UEBERSPRINGT NICHT. Er baut seinen Index selbst.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.query_runtime import run_query, set_corpus

_HIER = Path(__file__).resolve().parent
if str(_HIER) not in sys.path:
    sys.path.insert(0, str(_HIER))

from test_run_query import build_tiny_fast_index  # noqa: E402

#: Drei Saetze zu je vier Token. Satzanfaenge auf 0, 4 und 8.
TEXT = "a b c . d e f . g h i ."


class WithinKonformitaet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cc_within_idx_")
        cls.index_path = build_tiny_fast_index(Path(cls._tmp), TEXT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self.idx = CorpusIndex(self.index_path, read_only=True)
        set_corpus(self.idx)
        self.addCleanup(self.idx.close)
        self.addCleanup(set_corpus, None)

    def zaehle(self, cql: str) -> int:
        return len(list(run_query("cql:" + cql, ctx=0, corpus=self.idx)))

    def test_der_index_hat_die_erwarteten_satzgrenzen(self):
        """Ohne diese Probe steht alles Weitere auf einer Annahme."""
        pos = [
            int(x)
            for x in self.idx.fast_index.boundaries.sentence._positions
        ]
        self.assertEqual(pos, [0, 4, 8], pos)

    # ------------------------------------------------------------------ #
    # Innerhalb eines Satzes: alle drei Formen finden dasselbe.           #
    # ------------------------------------------------------------------ #

    def test_innerhalb_eines_satzes_sind_alle_drei_gleich(self):
        kern = '[word="a"] []{1} [word="c"]'
        self.assertEqual(self.zaehle(kern), 1)
        self.assertEqual(self.zaehle(f"within(<s>, {kern})"), 1)
        self.assertEqual(self.zaehle(f"within(<doc>, {kern})"), 1)

    # ------------------------------------------------------------------ #
    # Ueber die Satzgrenze: NUR der Dokument-Scope findet es.             #
    # DIE EIGENTLICHE AUSSAGE DIESES MODULS.                              #
    # ------------------------------------------------------------------ #

    def test_ueber_die_satzgrenze_findet_nur_der_dokument_scope(self):
        """c auf 2, Luecke auf 3, d auf 4. Satz 2 beginnt auf 4.

        Die freie Abfrage findet es NICHT, und das ist kein Defekt: die
        Vorgabe ist satzintern. Wer das nicht weiss, liest aus der Null
        heraus, die Konstruktion komme nicht vor.
        """
        kern = '[word="c"] []{1} [word="d"]'
        self.assertEqual(self.zaehle(kern), 0, "die Vorgabe ist satzintern")
        self.assertEqual(self.zaehle(f"within(<s>, {kern})"), 0)
        self.assertEqual(
            self.zaehle(f"within(<doc>, {kern})"), 1,
            "der Dokument-Scope muss ueber die Satzgrenze reichen",
        )

    def test_der_satz_scope_wiederholt_nur_die_vorgabe(self):
        """Deshalb ist er nie enger als die freie Abfrage, und nie weiter.

        Diese Probe steht hier, weil ich am 2026-09-01 aus genau dieser
        Gleichheit den falschen Schluss gezogen habe, der Scope wirke
        nicht. Zwei gleiche Zahlen sind kein Befund, sondern eine Frage.
        Die Probe darueber beantwortet sie.
        """
        for kern in (
            '[word="a"] []{1} [word="c"]',
            '[word="c"] []{1} [word="d"]',
            '[word="a"] []{0,8} [word="i"]',
        ):
            with self.subTest(cql=kern):
                self.assertEqual(
                    self.zaehle(kern), self.zaehle(f"within(<s>, {kern})")
                )

    def test_der_dokument_scope_ist_nie_enger_als_die_vorgabe(self):
        for kern in (
            '[word="a"] []{1} [word="c"]',
            '[word="c"] []{1} [word="d"]',
            '[word="a"] []{0,8} [word="i"]',
        ):
            with self.subTest(cql=kern):
                self.assertGreaterEqual(
                    self.zaehle(f"within(<doc>, {kern})"), self.zaehle(kern)
                )

    def test_ein_satzuebergreifender_bogen_ueber_zwei_grenzen(self):
        """a auf 0, i auf 10, dazwischen ZWEI Satzgrenzen (4 und 8)."""
        kern = '[word="a"] []{0,12} [word="i"]'
        self.assertEqual(self.zaehle(kern), 0)
        self.assertEqual(self.zaehle(f"within(<doc>, {kern})"), 1)

    # ------------------------------------------------------------------ #
    # Was die Sprache NICHT kann, und das gehoert festgehalten.           #
    # ------------------------------------------------------------------ #

    def test_satzinitial_ist_nicht_ausdrueckbar(self):
        """Kein Anker fuer den Satzanfang.

        Der Kernbefund der Referenzantwort zu
        deutung-verknuepfung-dispersion lautet "'Das bedeutet' AM
        SATZANFANG mit dem Faktor 2,50". Dafuer gibt es keine Syntax, und
        die Referenz rechnet ihn direkt an den Grenzen des Index.

        Diese Probe haelt die Luecke fest, damit sie nicht als
        Selbstverstaendlichkeit verschwindet. Faellt sie eines Tages, ist
        der Anker da und die Probe gehoert umgeschrieben.
        """
        with self.assertRaises(Exception):
            self.zaehle('<s> [word="d"]')


class DerPromptZeigtDieSyntax(unittest.TestCase):
    """Die Maschine kann es. Der Prompt muss es auch sagen.

    Genau diese Probe fehlte bei den Quantoren, und die Luecke kostete
    dort 0 statt 45.599 Treffer auf einer echten Nutzerfrage.
    """

    def test_der_dokument_scope_steht_im_systemprompt(self):
        from candyconc.candyconc_copilot.prompt_layout import build_static_core

        kern = build_static_core()
        self.assertIn("within(<doc>", kern)

    def test_der_kern_bleibt_unter_seinem_budget(self):
        from candyconc.candyconc_copilot.prompt_layout import (
            STATIC_CORE_MAX_CHARS,
            build_static_core,
        )

        self.assertLessEqual(len(build_static_core()), STATIC_CORE_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
