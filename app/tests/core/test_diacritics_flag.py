"""Unsupported diacritic flags produce an actionable input error.

Read combined %cd flags as one token and preserve the distinction between
case folding and diacritic folding. Execute the suggested alternative on
a family of umlaut forms and, when available, through the reference index.
It must match more forms than the original query. Character classes must
contain the actual umlaut, since [uue] only matches u or e."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from cqlhpc.lexer import lex  # noqa: E402
from cqlhpc.parser import ParseError, Parser  # noqa: E402


def _flaggen(text: str) -> list[tuple[str, str]]:
    return [(t.kind, t.value) for t in lex(text) if t.kind in ("FLAG", "ERROR")]


def _parse(text: str):
    return Parser(lex(text)).parse()


class LexerLiestDenGanzenLauf(unittest.TestCase):
    def test_cd_ist_ein_token(self):
        """Vorher zerfiel das in FLAG 'c' plus IDENT 'd'."""
        self.assertEqual(_flaggen('[word="x"%cd]'), [("FLAG", "cd")])

    def test_einzelne_flaggen_unveraendert(self):
        self.assertEqual(_flaggen('[word="x"%c]'), [("FLAG", "c")])
        self.assertEqual(_flaggen('[word="x"%d]'), [("FLAG", "d")])

    def test_grossbuchstaben_werden_klein(self):
        self.assertEqual(_flaggen('[word="x"%CD]'), [("FLAG", "cd")])

    def test_blankes_prozent_bleibt_fehler(self):
        self.assertEqual(_flaggen('[word="x"%]'), [("ERROR", "%")])

    def test_flagbuchstaben_im_literal_bleiben_literal(self):
        """Der STRING-Zweig konsumiert sie, sie erreichen den Flag-Zweig nie."""
        self.assertEqual(_flaggen('[word="c d %c"]'), [])


class DFlaggeWirdAbgelehnt(unittest.TestCase):
    def test_d_allein_faellt(self):
        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%d]')
        self.assertIn("Diakritika", str(ctx.exception))

    def test_cd_faellt_mit_derselben_begruendung(self):
        """Und NICHT mehr mit 'expected RBRACK, got IDENT'."""
        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%cd]')
        meldung = str(ctx.exception)
        self.assertIn("Diakritika", meldung)
        self.assertNotIn("RBRACK", meldung)

    def test_die_meldung_nennt_den_ausweg(self):
        """Eine Absage ohne Alternative ist eine Sackgasse."""
        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%d]')
        meldung = str(ctx.exception)
        self.assertIn("~", meldung)
        self.assertIn("[", meldung)

    def test_der_ausweg_trifft_MEHR_als_die_ausgangsabfrage(self):
        """Die Eigenschaft, um die es geht, nicht eine Zeichenkette.

        Geprueft wird gegen eine FAMILIE, nicht gegen ein Wort: eine
        Empfehlung, die nur zufaellig ein handverlesenes Beispiel trifft,
        besteht hier nicht. Die Ausgangsabfrage wird aus dem empfohlenen
        Muster abgeleitet (Zeichenklasse durch ihr erstes Zeichen
        ersetzt), nicht fest verdrahtet.
        """
        import re

        formen = [
            "Flucht", "Fluchten", "fluchtartig",
            "Flüchtling", "Flüchtlinge", "Flüchtlingen",
            "Flüchtlingskrise", "flüchten", "geflüchtet", "flüchtig",
        ]
        empfohlen = self._empfohlenes_muster()
        ausgangs = re.sub(r"\[([^\]]+)\]", lambda m: m.group(1)[0], empfohlen)

        def _trifft(muster):
            return {w for w in formen if re.fullmatch(muster, w, re.IGNORECASE)}

        mit = _trifft(empfohlen)
        ohne = _trifft(ausgangs)
        self.assertTrue(
            ohne < mit,
            f"{empfohlen!r} trifft {len(mit)} Formen, die Ausgangsabfrage "
            f"{ausgangs!r} trifft {len(ohne)}. Der Ausweg muss STRIKT mehr "
            "treffen, sonst ist er keiner.",
        )
        self.assertTrue(
            any("ü" in w for w in mit - ohne),
            "der Zugewinn enthaelt keine einzige Umlautform",
        )

    def _empfohlenes_muster(self) -> str:
        import re

        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%d]')
        treffer = re.search(r'word~"([^"]+)"', str(ctx.exception))
        self.assertIsNotNone(treffer, "Meldung nennt kein Suchmuster")
        return treffer.group(1)

    def test_die_grammatikdoku_nennt_dasselbe_muster(self):
        """Code und Doku sind auseinandergelaufen, das faellt hier auf.

        Die Grammatik steht in der Referenz ``docs/reference/query-language.md``
        (neben ``app/`` im veroeffentlichten Repositorium, unter
        ``repo_root/docs`` im Entwicklungsbaum). Ihre Beispiele liegen in
        ``docs/_data/query_examples.json``, die Seite zeigt sie mit der
        Direktive ``query-example``.
        """
        import json
        import re

        app = Path(__file__).resolve().parents[2]
        docs = next(
            (p for p in (app.parent / "docs", app.parent / "repo_root" / "docs") if (p / "conf.py").is_file()),
            None,
        )
        if docs is None:
            self.skipTest("Dokumentation liegt nicht neben app/")
        seite = (docs / "reference" / "query-language.md").read_text(encoding="utf-8")
        beispiele = json.loads((docs / "_data" / "query_examples.json").read_text(encoding="utf-8"))
        texte = [seite]

        def sammeln(wert):
            if isinstance(wert, str):
                texte.append(wert)
            elif isinstance(wert, dict):
                for teil in wert.values():
                    sammeln(teil)
            elif isinstance(wert, list):
                for teil in wert:
                    sammeln(teil)

        sammeln(beispiele)
        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%d]')
        empfohlen = re.search(r'word~"([^"]+)"', str(ctx.exception)).group(1)
        self.assertTrue(
            any(empfohlen in text for text in texte),
            f"Die Abfragereferenz nennt das Muster {empfohlen!r} der Fehlermeldung nicht",
        )

    def test_c_bleibt_unveraendert_gueltig(self):
        knoten = _parse('[word="x"%c]')
        self.assertIsNotNone(knoten)

    def test_wiederholtes_c_faellt_weiterhin_zusammen(self):
        self.assertIsNotNone(_parse('[word="x"%cc]'))

    def test_ohne_flagge_unveraendert(self):
        self.assertIsNotNone(_parse('[word="x"]'))


class DieFaehigkeitsangabeSagtDieWahrheit(unittest.TestCase):
    def test_limits_behaupten_keinen_alias_mehr(self):
        from cqlhpc import capabilities

        text = "\n".join(
            zeile
            for eintrag in capabilities.CAPABILITIES
            for zeile in (getattr(eintrag, "limits", ()) or ())
        )
        self.assertNotIn("alias for %c", text)
        self.assertIn("rejected at parse time", text)


if __name__ == "__main__":
    unittest.main()


class DerAuswegFindetAmKorpusMehr(unittest.TestCase):
    """Das zweite Bein: gemessen an der echten Engine.

    Der Modul-Docstring hat diesen Vergleich einmal behauptet, ohne dass
    er existierte. Jetzt existiert er. Uebersprungen ohne Index, deshalb
    traegt ``DerAuswegTrifftDieUmlautformen`` oben die Bindung.

    Am Testindex gemessen: ``.*flucht.*`` 7 Treffer,
    ``.*fl[uue]cht.*`` 8, ``.*fl[uü]cht.*`` 76.
    """

    @classmethod
    def setUpClass(cls):
        import os

        roh = os.environ.get("CANDYCONC_INDEX_PATH")
        if not roh or not Path(roh).exists():
            raise unittest.SkipTest("CANDYCONC_INDEX_PATH fehlt")
        from candyconc.core.cql_engine import search_cql_match_arrays_backend
        from candyconc.core.fast_index_backend import FastIndexBackend

        cls._suche = staticmethod(search_cql_match_arrays_backend)
        cls._backend = FastIndexBackend(roh)

    def _treffer(self, muster: str) -> int:
        starts, _ends = self._suche(
            self._backend, f'[word~"{muster}"%c]', limit=2_000_000_000
        )
        return int(starts.size)

    def test_die_empfehlung_schlaegt_die_ausgangsabfrage(self):
        import re

        with self.assertRaises(ParseError) as ctx:
            _parse('[word="x"%d]')
        empfohlen = re.search(
            r'word~"([^"]+)"', str(ctx.exception)
        ).group(1)
        ausgangs = re.sub(
            r"\[([^\]]+)\]", lambda m: m.group(1)[0], empfohlen
        )
        mit, ohne = self._treffer(empfohlen), self._treffer(ausgangs)
        self.assertGreater(
            mit, ohne,
            f"{empfohlen!r} findet {mit}, {ausgangs!r} findet {ohne}",
        )
        # Nicht nur mehr, sondern DEUTLICH mehr: die ASCII-Umschrift
        # [uue] brachte 8 gegen 7, also Faktor 1,14.
        self.assertGreater(mit, 2 * ohne, "kein nennenswerter Zugewinn")

    def test_die_ascii_umschrift_besteht_diesen_test_NICHT(self):
        """Die Gegenprobe: der alte Ausweg faellt hier durch."""
        self.assertLess(self._treffer(".*fl[uue]cht.*"),
                        2 * self._treffer(".*flucht.*"))
