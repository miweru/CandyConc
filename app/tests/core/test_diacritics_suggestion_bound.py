"""Der Empfehlungswaechter mass Breite statt Diakritika.

Befund
------
``%d`` wird abgelehnt, und die Meldung empfiehlt stattdessen eine
Zeichenklasse, die den Umlaut selbst enthaelt
(``[word~".*fl[uü]cht.*"%c]``). Der Waechter dazu, der bisherige
``test_die_empfehlung_schlaegt_die_ausgangsabfrage``, prueft die
Empfehlung so: er ersetzt jede Zeichenklasse durch ihren ERSTEN Buchstaben
und verlangt, dass die Empfehlung mehr als doppelt so viel findet.

Das misst "eine Zeichenklasse ist breiter als ein einzelner Buchstabe",
und das ist fuer JEDE erweiternde Klasse wahr, auch fuer eine, die mit
Diakritika nichts zu tun hat. Am Testindex nachgemessen, mit der
Pruefregel des alten Waechters:

    .*fl[uü]cht.*         besteht    76 gegen     7   (richtig)
    .*fl[uüaeiox]cht.*    besteht    83 gegen     7   (Muelleimer-Klasse)
    .*[a-z]cht.*          besteht  1545 gegen   195   (keine Diakritika)
    .*[sd]er.*            besteht  2059 gegen   283   (anderes Thema)

Drei davon sind als EMPFEHLUNG falsch und kamen durch. Ein Waechter, der
eine falsche Empfehlung durchlaesst, bindet nichts: er haette die
Regression, gegen die er gebaut ist, nicht bemerkt.

Was hier stattdessen geprueft wird
----------------------------------
Zwei Beine, ein strukturelles und ein gemessenes.

Strukturell: jede Zeichenklasse der Empfehlung besteht GENAU aus
Grundvokalen und deren eigenen Umlauten. Das schliesst die
Muelleimer-Klasse und jede Klasse ohne Umlaut aus.

Gemessen: die Empfehlung deckt BEIDE Schreibungen. Ersetzt man jede
Klasse einmal durch den Grundvokal und einmal durch den Umlaut, muessen
beide Treffermengen Teilmengen der Empfehlung sein, und die Umlautform
muss etwas finden, das die ASCII-Form NICHT findet. Der letzte Punkt ist
die positive Klasse: ohne ihn bestuende der Test auch dort, wo es gar
keine Umlautvariante gibt, und wuerde nichts belegen.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from cqlhpc.parser import parse_cql

# Grundvokal -> sein Umlaut. Das ss/ß-Paar gehoert nicht dazu: es ist
# keine Diakritika-Faltung, sondern eine Ligatur mit eigener Laenge.
_UMLAUTE = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}

_BENCH = os.environ.get("CANDYCONC_INDEX_PATH")


def _meldung() -> str:
    """Die vollstaendige Ablehnungsmeldung zu ``%d``."""
    from cqlhpc.parser import ParseError

    with pytest.raises(ParseError) as ctx:
        parse_cql('[word="x"%d]')
    return str(ctx.value)


def _empfehlung_aus_der_meldung() -> str:
    """Das Muster, das die Engine bei ``%d`` empfiehlt."""
    treffer = re.search(r'word~"([^"]+)"', _meldung())
    assert treffer is not None, f"kein Muster in der Meldung: {_meldung()}"
    return treffer.group(1)


def _klassen(muster: str) -> list[str]:
    return re.findall(r"\[([^\]]+)\]", muster)


def _ersetzt(muster: str, waehle) -> str:
    return re.sub(r"\[([^\]]+)\]", lambda m: waehle(m.group(1)), muster)


def _grundvokale(klasse: str) -> list[str]:
    return [z for z in klasse if z in _UMLAUTE]


def _klasse_ist_ein_umlautpaar(klasse: str) -> bool:
    """GENAU ein Grundvokal mit GENAU seinem eigenen Umlaut.

    Eine Vorfassung verlangte nur, dass die Klasse aus Grundvokalen und
    deren Umlauten besteht, und liess damit Muelleimer-Klassen mit
    mehreren Paaren durch: ``[uüaäoö]`` bestand sie, obwohl es fuer den
    Stamm "flucht" auch "flacht" und "flocht" trifft. Eine Empfehlung, die
    mehr trifft als die gesuchte Diakritika-Variante, ist keine.
    """
    basen = _grundvokale(klasse)
    if len(basen) != 1:
        return False
    return set(klasse) == {basen[0], _UMLAUTE[basen[0]]}


def _haelt_als_empfehlung(muster: str) -> bool:
    """Die EINE Pruefregel. Beide Tests rufen sie, keiner baut sie nach.

    Die erste Fassung des Abweis-Tests hatte die Regel inline wiederholt
    und ist beim Nachschaerfen der Struktur-Pruefung stehen geblieben.
    Zwei Kopien derselben Regel laufen auseinander, und die Kopie im
    Gegenprobe-Test haette den Waechter fuer haltbar erklaert, den er
    nicht mehr war.
    """
    klassen = _klassen(muster)
    if not klassen or not all(_klasse_ist_ein_umlautpaar(k) for k in klassen):
        return False
    # Und das GANZE Muster, nicht nur der Klammerinhalt. Die Endabnahme hat
    # den Vorgaenger widerlegt: er mass ausschliesslich zwischen den
    # eckigen Klammern, und alles davor, dazwischen und danach war
    # ungeprueft. ``.*fl[uü]cht.*|.*xyz.*`` haette ihn bestanden.
    #
    # Die Bindung: ersetzt man jede Klasse durch ihren Grundvokal, muss
    # ein Muster uebrig bleiben, das selbst KEINE erweiternden Konstrukte
    # mehr enthaelt. Genau dann ist die Empfehlung die ASCII-Schreibung
    # plus Umlautpaare und nichts sonst.
    ascii_form = _ersetzt(muster, lambda k: _grundvokale(k)[0])
    return not any(z in ascii_form for z in "[]{}|()")


class TestStrukturDerEmpfehlung:
    def test_die_empfehlung_traegt_die_faltungsflagge(self):
        """Ohne %c waere sie gross-klein-EMPFINDLICH.

        Der Waechter las bisher nur den Klammerinhalt. Eine Empfehlung
        ohne ``%c`` haette ihn bestanden und dabei genau die Haelfte ihrer
        Aufgabe verfehlt: die Zeichenklasse deckt den Umlaut, die Flagge
        die Gross-Klein-Schreibung.
        """
        meldung = _meldung()
        assert "%c" in meldung, meldung
        # Und zwar AN der empfohlenen Abfrage, nicht irgendwo im Text.
        assert re.search(r'\[word~"[^"]+"%c\]', meldung), meldung

    def test_die_empfehlung_ist_eine_vollstaendige_abfrage(self):
        """Nicht nur ein Muster, sondern etwas, das man einsetzen kann."""
        meldung = _meldung()
        treffer = re.search(r'(\[word~"[^"]+"%c\])', meldung)
        assert treffer is not None, meldung
        parse_cql(treffer.group(1))  # muss selbst parsen

    def test_die_empfehlung_enthaelt_ueberhaupt_eine_zeichenklasse(self):
        assert _klassen(_empfehlung_aus_der_meldung())

    def test_die_PRODUKTIV_empfehlung_besteht_die_pruefregel(self):
        """Die Regel auf die ECHTE Empfehlung, nicht nur auf Beispiele.

        Der Vorgaenger prueft klassenweise mit einer eigenen Schleife und
        rief ``_haelt_als_empfehlung`` NICHT auf. Die Regel, die alle
        Gegenbeispiele abweist, wurde damit nie auf das Muster angewandt,
        das die Engine tatsaechlich empfiehlt: sie haette eine Empfehlung
        mit Alternative oder zweiter Klasse durchgelassen.
        """
        empfehlung = _empfehlung_aus_der_meldung()
        assert _haelt_als_empfehlung(empfehlung), empfehlung

    def test_jede_klasse_ist_genau_grundvokal_plus_eigener_umlaut(self):
        """Schliesst Muelleimer-Klassen und umlautlose Klassen aus."""
        empfehlung = _empfehlung_aus_der_meldung()
        for klasse in _klassen(empfehlung):
            assert _klasse_ist_ein_umlautpaar(klasse), (
                f"{klasse!r} in {empfehlung!r} ist kein Umlautpaar: eine "
                "Zeichenklasse fuer Diakritika-Unempfindlichkeit paart "
                "GENAU einen Grundvokal mit seinem eigenen Umlaut"
            )

    @pytest.mark.parametrize(
        "falsch",
        [
            ".*fl[uü]cht.*|.*xyz.*",   # Alternative ausserhalb der Klasse
            ".*fl[uü]cht.*[a-z]",      # zweite, umlautlose Klasse
            ".*(fl[uü]cht|xyz).*",     # Gruppe mit Alternative
            ".*fl[uüaeiox]cht.*",   # Muelleimer-Klasse
            ".*fl[uüaä]cht.*",      # zwei Paare, trifft auch "flacht"
            ".*fl[uüaäoö]cht.*",    # drei Paare
            ".*[a-z]cht.*",         # keine Diakritika
            ".*[sd]er.*",           # anderes Thema
            ".*[Dd]ie.*",           # Gross-Klein, nicht Diakritika
            ".*fl[uue]cht.*",       # die widerlegte ASCII-Umschrift
            ".*flucht.*",           # gar keine Klasse
        ],
    )
    def test_der_waechter_weist_falsche_empfehlungen_ab(self, falsch):
        """Die Gegenprobe. Ohne sie misst der Waechter nur sich selbst.

        Genau diese Muster bestanden den Vorgaenger, der lediglich
        "Zeichenklasse schlaegt ihren ersten Buchstaben" verlangte.
        """
        assert not _haelt_als_empfehlung(falsch), (
            f"{falsch!r} wurde als Empfehlung akzeptiert"
        )

    @pytest.mark.parametrize("richtig", [".*fl[uü]cht.*", ".*M[aä]nner.*"])
    def test_der_waechter_haelt_die_richtigen(self, richtig):
        """Ein Waechter, der alles abweist, besteht jede Gegenprobe.

        ``.*[Ww][oö]rter.*`` steht hier bewusst NICHT: ``[Ww]`` ist eine
        Gross-Klein-Klasse, und die Empfehlung traegt ``%c``, das die
        Gross-Klein-Faltung bereits leistet. Eine solche Klasse ist
        redundant, und die Regel bleibt streng: jede Zeichenklasse einer
        Diakritika-Empfehlung paart genau einen Grundvokal mit seinem
        eigenen Umlaut.
        """
        assert _haelt_als_empfehlung(richtig), richtig


@pytest.mark.skipif(
    not _BENCH or not Path(_BENCH).exists(),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
class TestEmpfehlungDecktBeideSchreibungen:
    @classmethod
    def setup_class(cls):
        from candyconc.core.cql_engine import search_cql_match_arrays_backend
        from candyconc.core.fast_index_backend import FastIndexBackend

        cls._suche = staticmethod(search_cql_match_arrays_backend)
        cls._backend = FastIndexBackend(_BENCH)

    def _menge(self, muster: str) -> set[int]:
        starts, _ends = self._suche(
            self._backend, f'[word~"{muster}"%c]', limit=2_000_000_000
        )
        return {int(x) for x in starts}

    def test_beide_schreibungen_liegen_in_der_empfehlung(self):
        empfehlung = _empfehlung_aus_der_meldung()
        ascii_form = _ersetzt(empfehlung, lambda k: _grundvokale(k)[0])
        umlaut_form = _ersetzt(
            empfehlung, lambda k: _UMLAUTE[_grundvokale(k)[0]]
        )
        empfohlen = self._menge(empfehlung)
        mit_ascii = self._menge(ascii_form)
        mit_umlaut = self._menge(umlaut_form)

        assert mit_ascii <= empfohlen, (
            f"{empfehlung!r} deckt {ascii_form!r} nicht"
        )
        assert mit_umlaut <= empfohlen, (
            f"{empfehlung!r} deckt {umlaut_form!r} nicht"
        )

    def test_die_umlautform_findet_etwas_das_die_ascii_form_verfehlt(self):
        """Die positive Klasse. Ohne sie belegt der Test nichts.

        Am Testindex: ``.*fl[uü]cht.*`` findet 76, ``.*flucht.*`` 7,
        ``.*flücht.*`` 69, und alle 69 fehlen der ASCII-Form.
        """
        empfehlung = _empfehlung_aus_der_meldung()
        ascii_form = _ersetzt(empfehlung, lambda k: _grundvokale(k)[0])
        umlaut_form = _ersetzt(
            empfehlung, lambda k: _UMLAUTE[_grundvokale(k)[0]]
        )
        exklusiv = self._menge(umlaut_form) - self._menge(ascii_form)
        assert exklusiv, (
            f"{umlaut_form!r} findet nichts, was {ascii_form!r} verfehlt: "
            "die Empfehlung belegt am Korpus keinen Zugewinn"
        )
