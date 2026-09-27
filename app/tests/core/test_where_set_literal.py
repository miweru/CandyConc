"""Das Mengenliteral in ``where()`` traf nichts und meldete Erfolg.

Befund
------
``parse_value`` liefert DREI Gestalten: Zeichenkette, Zahl und
Mengenliteral ``{...}``. Die Wertnormalisierung des ``where()``-Eingangs
deckte nur die erste ab, und beide Auswerter behandelten die Liste wie
einen Skalar:

* ``MetaFieldIndex.mask_for_cond`` verglich gegen ``str(["test"])``, also
  gegen die Zeichenkette ``"['test']"``,
* ``_eval_meta_cond`` verglich das Feld direkt gegen die Liste.

Beides trifft nie ein Dokument. Am Testindex gemessen, wo
``split=test`` 683 und ``split=train`` 1317 der 2000 Dokumente traegt:

    [word="und"]                                 797
    where(split="test",     [word="und"])        262
    where(split={"test"},   [word="und"])          0
    where(split={"test "},  [word="und"])          0
    where(split!={"test "}, [word="und"])        797   (das GANZE Ergebnis)

Also erneut die Klasse "ein Filter bewirkt nichts und meldet Erfolg", und
mit ``!=`` liefert er die volle Zahl, die wie ein Ergebnis aussieht. Eine
Null faellt auf, 797 nicht.

Reparatur
---------
Die Mengenschreibweise heisst Mitgliedschaft. Der Dikt-Eingang kann das
laengst: ``build_meta_expr`` faltet eine Liste in ein ODER von
Gleichheiten. Beide Auswerter tun das jetzt auch, und zwar indem sie
ihren EIGENEN Skalarzweig aufrufen statt ihn nachzubauen. Eine
Vorfassung hat im Mengenzweig mit ``str()``-Toleranz verglichen, waehrend
der Skalarzweig zwei Zeilen tiefer schlicht ``==`` benutzt: derselbe Wert
haette als Menge getroffen und als Skalar nicht.

Die Normalisierung liegt jetzt in ``cqlhpc.ast``, das jeder Auswerter
ohnehin importiert. Sie lag in ``candyconc.core.meta_filters`` und damit
oberhalb des Parsers, der sie deshalb nicht erreichen konnte und sich
seinen eigenen, kuerzeren Streifen gebaut hat. Getrennte
Implementierungen derselben Regel laufen auseinander.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cqlhpc.ast import MetaCond, normalize_meta_value
from cqlhpc.engine import _eval_meta_cond
from cqlhpc.parser import parse_cql

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")
_braucht_index = pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


def _meta_wert(quelle: str):
    """Den geparsten Wert der Metabedingung aus ``where(...)`` holen."""
    teil = parse_cql(quelle).expr.parts[0]
    while not isinstance(teil, MetaCond):
        teil = teil.parts[0]
    return teil.value


class TestParserNormalisiertAlleGestalten:
    def test_zeichenkette(self):
        assert _meta_wert('where(split="test ", [word="und"])') == "test"

    def test_mengenliteral(self):
        """Die Gestalt, die die erste Fassung ausliess."""
        assert _meta_wert('where(split={"test ","train "}, [word="und"])') == [
            "test", "train",
        ]

    def test_zahl_bleibt_zahl(self):
        assert _meta_wert('where(jahr=2020, [word="und"])') == 2020

    def test_die_normalisierung_hat_EINE_heimat(self):
        """Sonst laufen die Fassungen wieder auseinander.

        ``candyconc.core.meta_filters`` darf sie nur noch re-exportieren.
        """
        from candyconc.core import meta_filters

        assert meta_filters.normalize_meta_value is normalize_meta_value
        quelle = Path(meta_filters.__file__).read_text(encoding="utf-8")
        assert "def normalize_meta_value(" not in quelle


class TestDocRueckfallWertetMitgliedschaftAus:
    @pytest.mark.parametrize(
        "op,menge,wert,erwartet",
        [
            ("=", ["test", "train"], "test", True),
            ("=", ["test", "train"], "dev", False),
            ("!=", ["test"], "test", False),
            ("!=", ["test"], "train", True),
            ("=", [2020, 2021], 2020, True),
            # Ordnungsvergleiche auf einer Menge sind sinnlos und liefern
            # deshalb falsch, nicht irgendetwas.
            (">=", ["test"], "test", False),
        ],
    )
    def test_mitgliedschaft(self, op, menge, wert, erwartet):
        cond = MetaCond(field="split", op=op, value=list(menge))
        assert _eval_meta_cond(cond, wert) is erwartet

    @pytest.mark.parametrize("wert", ["test", "2020", 2020, None, ""])
    def test_menge_ist_ODER_ueber_den_SKALARZWEIG(self, wert):
        """Der Mengenzweig darf nicht toleranter sein als der Skalarzweig.

        Genau das war die Vorfassung: sie verglich mit ``str()``-Toleranz,
        waehrend der Skalarzweig ``==`` benutzt.
        """
        for kandidat in ("test", "2020", 2020):
            menge = _eval_meta_cond(
                MetaCond(field="f", op="=", value=[kandidat]), wert)
            skalar = _eval_meta_cond(
                MetaCond(field="f", op="=", value=kandidat), wert)
            assert menge is skalar, (kandidat, wert)


@_braucht_index
class TestAmEchtenIndex:
    @staticmethod
    def _zaehle(query: str) -> int:
        from cqlhpc.engine import SearchOptions

        from candyconc.core.cql_engine import _get_engine
        from candyconc.core.fast_index_backend import FastIndexBackend

        _corpus, engine = _get_engine(FastIndexBackend(_BENCH))
        return engine.count(
            query,
            SearchOptions(max_matches=10**9, within_sentences_by_default=True),
        )

    def test_menge_zaehlt_wie_der_skalar(self):
        skalar = self._zaehle('where(split="test", [word="und"])')
        # Do not skip a zero scalar result. That would conceal the regression
        # this scalar-versus-set comparison is intended to detect.
        assert skalar > 0, (
            "der Skalarpfad trifft nichts mehr: der Mengenvergleich "
            "haette dann nichts, woran er sich messen koennte"
        )
        assert self._zaehle('where(split={"test"}, [word="und"])') == skalar
        # Und mit Leerzeichen, das die erste Normalisierung nicht sah.
        assert self._zaehle('where(split={"test "}, [word="und"])') == skalar

    def test_die_menge_beider_werte_ergibt_das_ganze_ergebnis(self):
        """Der schaerfste Beleg: die Menge partitioniert nicht, sie deckt."""
        ganz = self._zaehle('[word="und"]')
        beide = self._zaehle('where(split={"test","train"}, [word="und"])')
        assert beide == ganz

    def test_ungleich_menge_ist_das_komplement_nicht_alles(self):
        """Vorher lieferte ``!={"test "}`` das GANZE Ergebnis."""
        ganz = self._zaehle('[word="und"]')
        test = self._zaehle('where(split={"test"}, [word="und"])')
        assert self._zaehle('where(split!={"test "}, [word="und"])') == ganz - test

    def test_unbekannter_wert_trifft_ehrlich_nichts(self):
        assert self._zaehle('where(split={"gibtsnichtxyz"}, [word="und"])') == 0

    def test_ordnungsvergleich_auf_einer_menge_wirft(self):
        """Statt still eine falsche Zahl zu liefern."""
        with pytest.raises(Exception):
            self._zaehle('where(split>={"test"}, [word="und"])')


class TestLeereMengeUndFalscherOperator:
    """Zwei Befunde des adversarialen Gates.

    ``pruefe_filterform`` weist am Dikt-Eingang eine leere Liste
    ausdruecklich ab. Der ``where()``-Eingang liess sie durch, und ``!=``
    machte daraus das GANZE Korpus: am Testindex ergab
    ``where(split!={}, [word="und"])`` 797 von 797 Treffern,
    ``where(split={}, ...)`` null. Ein Filter, der nichts einschraenkt,
    sieht aus wie einer.

    Und der Operatorfehler war ein ``RuntimeError``, also der Form nach ein
    Serverfehler, obwohl er eine Frage der Aufruferin beantwortet. Er ist
    jetzt ein ``EingabeFormFehler``, fuer den eine Ausnahmebehandlung
    existiert, die daraus HTTP 400 macht.
    """

    @pytest.mark.parametrize("quelle", [
        'where(split={}, [word="und"])',
        'where(split!={}, [word="und"])',
        'where(split={""}, [word="und"])',
        'where(split={"", " "}, [word="und"])',
    ])
    def test_leere_wertmenge_wird_abgewiesen(self, quelle):
        from cqlhpc.parser import ParseError

        with pytest.raises(ParseError, match="leere Wertmenge"):
            parse_cql(quelle)

    def test_die_nichtleere_menge_bleibt_unangetastet(self):
        """Die Gegenprobe: der Waechter darf die gueltige Form nicht fressen."""
        assert _meta_wert('where(split={"test"}, [word="und"])') == ["test"]
        assert _meta_wert('where(split={"test", ""}, [word="und"])') == ["test"]

    @_braucht_index
    @pytest.mark.parametrize("wert", [["test", "train"], "test", 5, 2020.5])
    def test_der_operatorfehler_ist_eine_eingabefrage(self, wert):
        """RuntimeError sieht aus wie ein Serverfehler und war einer.

        Die Vorfassung las 1400 Zeichen ab ``def mask_for_cond(`` und
        suchte dort nach ``raise RuntimeError``. Die Funktion ist 2182
        Zeichen lang, und genau im ungelesenen Rest lag der Zweig, der
        beim Ordnungsvergleich mit einer ZAHL weiter 500 lieferte, samt
        dem RuntimeError in ``_mask_num_range``, das gar nicht im Fenster
        liegt. Ein Waechter, der ein Fenster liest, bewacht das Fenster.

        Geprueft wird deshalb das VERHALTEN, ueber alle Wertgestalten,
        die einen anderen Zweig nehmen: Menge, Zeichenkette, ganze Zahl,
        Gleitkommazahl.
        """
        from candyconc.core.meta_filters import EingabeFormFehler
        from candyconc.core.meta_index import MetaIndex
        from cqlhpc.ast import MetaCond

        assert issubclass(EingabeFormFehler, ValueError)
        index = MetaIndex(Path(_BENCH))
        index.load()
        feld = index.fields.get("split")
        if feld is None:
            pytest.skip("Index kennt das Feld split nicht")
        with pytest.raises(EingabeFormFehler):
            feld.mask_for_cond(
                MetaCond(field="split", op=">=", value=wert), index.doc_count)

    @_braucht_index
    def test_und_die_gueltigen_operatoren_werfen_NICHT(self):
        """Sonst waere der Vergleich schlicht abgeschafft."""
        from candyconc.core.meta_index import MetaIndex
        from cqlhpc.ast import MetaCond

        index = MetaIndex(Path(_BENCH))
        index.load()
        feld = index.fields.get("split")
        if feld is None:
            pytest.skip("Index kennt das Feld split nicht")
        treffer = feld.mask_for_cond(
            MetaCond(field="split", op="=", value="test"), index.doc_count)
        assert int(treffer.sum()) == 683
