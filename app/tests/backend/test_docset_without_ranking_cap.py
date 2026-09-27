"""P2.8: Ein such-gebautes Docset war ein Korpus-PRAEFIX, kein Schnitt.

Drei Aufrufstellen fuetterten ``_search_docset_doc_ids`` und missbrauchten
dabei einen Top-N-RANKINGdeckel (``_ANALYSIS_JOB_TOP_N_DEFAULT``,
Voreinstellung 5000) als TREFFER-Scan-Praefix. Wer mehr passende Dokumente
hatte, bekam die ersten 5000 und kein Signal darueber. Jede
pro-Million-Normalisierung auf so einem Docset rechnet gegen einen zu
kleinen Nenner.

Die erste Fassung dieses Fixes hat den Deckel nur VERSCHOBEN, nicht
aufgehoben, und dieser Docstring behauptete das Gegenteil. ``limit=None``
heisst eine Ebene tiefer naemlich NICHT "kein Deckel": in
``search_cql_matches_backend`` steht ``max_matches=20000``, wenn limit
None ist (cql_engine.py:258/:289), waehrend dieselbe Datei dreissig Zeilen
weiter fuer die ZAEHLroutine ``2_000_000_000`` setzt (:321). Aus dem
5.000er-Deckel wurde also ein 20.000er, ebenso still. Ein adversarialer
Pruefer hat das an der eingefrorenen Fassung gemessen und damit auch die
Erklaerung widerlegt, mit der die Vormessung verworfen worden war: die
723 Dokumente und 20.026 Tokens fuer ``[word=".*"]`` waren nicht der
Regex-Schutzwall, sondern die Signatur des 20.000er-Deckels. Derselbe Wert
kommt fuer ``cql:[]``, das gar keinen Regex enthaelt. Der Vorpruefer hatte
mit 2000 Dokumenten und 56.191 Tokens recht.

``_search_docset_doc_ids`` uebersetzt ``limit=None`` deshalb ausdruecklich
nach ``SCAN_ALLE_TREFFER``. Am Testindex (2.000 Dokumente, 56.191
Tokens) gemessen, alle drei Abfragen mit und ohne Deckel:

    cql:[pos="NOUN"]   limit=5000    1051 Dokumente /  28.995 Tokens
                       limit=None    1995 / 56.080   (= limit=200000)
    cql:[word=".*"]    limit=5000     187 /  5.010
                       limit=None    2000 / 56.191   (= limit=200000)
    cql:[]             limit=5000     187 /  5.010
                       limit=None    2000 / 56.191   (= limit=200000)

Die Oberflaeche sendet nie ein limit, der Deckel griff also auf dem
Standardweg.

Der ungedeckelte Vollscan laeuft im BEGRENZTEN Pool fuer schwere Scans,
nicht auf der Event-Loop und nicht auf dem geteilten Default-Executor.
``executors.py`` schreibt das ausdruecklich vor: der Pool IST das
Nebenlaeufigkeitssemaphor, sonst hungern die billigen Auslagerungen aus
(B6-Starvation-Befund). Das gilt seit dem Wegfall des Deckels auch fuer
die beiden Routen, die ``_resolve_subcorpus_doc_ids`` aufrufen.

Die erste Fassung dieser Datei bestand ausschliesslich aus Quelltext-Greps.
Genau deshalb konnte der 20.000er-Deckel eine Ebene tiefer unbemerkt
bleiben: ein Test, der die Zeichenkette ``limit=None`` findet, kann nicht
sehen, dass ``limit=None`` unten 20000 bedeutet. Die Greps stehen weiter
unten und pinnen die Verdrahtung, die Wahrheit prueft der Verhaltensteil
oben.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_ROUTE = _APP / "src" / "candyconc" / "services" / "backend" / "routes" / "analysis.py"
_SUBROUTE = _APP / "src" / "candyconc" / "services" / "backend" / "routes" / "subcorpora.py"
_SERVER = _APP / "src" / "candyconc" / "services" / "backend" / "server.py"
_WRAPPER = (
    _APP / "src" / "candyconc" / "candyconc_copilot" / "tool_wrappers.py"
)


class KeinDeckelHeisstKeinDeckel(unittest.TestCase):
    """Der Verhaltensteil. Braucht keinen Index und keine Engine."""

    def test_ungedeckelt_wird_als_FAHNE_weitergegeben(self):
        """Nicht als grosse Zahl: die beiden Zweige brauchen Gegenteiliges.

        Der CQL-Zweig braucht eine grosse Zahl, weil ``limit=None`` dort
        ``max_matches=20000`` bedeutet. Der Klartext-Zweig braucht
        ``limit=None``, weil ``_complement_positions`` seinen lauten
        NOT-Waechter (``_NOT_MAX_TOKENS``) NUR im Zweig ``limit is None``
        prueft. Eine Vorfassung reichte ueberall ``SCAN_ALLE_TREFFER``
        durch und hat den Waechter damit STILL ABGESCHALTET, waehrend sie
        einen anderen Deckel aufhob -- ein Deckel weg, ein Waechter tot.
        """
        from candyconc.services.backend import server as srv

        gesehen: list[dict] = []

        def _spion(idx, query, *, limit=None, ungedeckelt=False):
            gesehen.append({"limit": limit, "ungedeckelt": ungedeckelt})
            import numpy as np

            return np.zeros(0, dtype=np.uint32)

        original = srv._positions_from_query
        srv._positions_from_query = _spion
        try:
            srv._search_docset_doc_ids(
                _LeererIndex(), "cql:[]",
                meta_filters={}, ai_filters={},
                include_ai=True, include_human=True, limit=None,
            )
        finally:
            srv._positions_from_query = original

        self.assertEqual(len(gesehen), 1)
        self.assertTrue(gesehen[0]["ungedeckelt"], "Fahne nicht gesetzt")

    def test_jeder_zweig_uebersetzt_die_fahne_in_SEIN_idiom(self):
        """Der Kern des Befunds, an der Quelle geprueft."""
        rumpf = _funktion(_SERVER, "_positions_from_query")
        # CQL: grosse Zahl, weil None dort 20000 heisst.
        self.assertIn(
            "limit=SCAN_ALLE_TREFFER if ungedeckelt else limit", rumpf
        )
        # Klartext: None, weil nur dort der NOT-Waechter prueft.
        self.assertIn("limit=None if ungedeckelt else limit", rumpf)

    def test_der_not_waechter_prueft_nur_bei_None(self):
        """Die Tatsache, die den zweigspezifischen Vertrag erzwingt.

        Faellt dieser Test, hat jemand ``_complement_positions`` geaendert.
        Dann gehoert die Uebersetzung oben neu bewertet.
        """
        quelle = (
            _SRC / "candyconc" / "domain" / "query_eval.py"
        ).read_text(encoding="utf-8")
        i = quelle.index("def _complement_positions")
        rumpf = quelle[i: quelle.index("\ndef ", i + 10)]
        self.assertIn("if allow_limit and limit is not None:", rumpf)
        self.assertIn("if total > _NOT_MAX_TOKENS:", rumpf)
        self.assertLess(
            rumpf.index("if allow_limit and limit is not None:"),
            rumpf.index("if total > _NOT_MAX_TOKENS:"),
            "der Waechter steht im else-Zweig von limit is not None",
        )

    def test_ein_gesetztes_limit_kommt_unveraendert_an(self):
        from candyconc.services.backend import server as srv

        gesehen: list[dict] = []

        def _spion(idx, query, *, limit=None, ungedeckelt=False):
            gesehen.append({"limit": limit, "ungedeckelt": ungedeckelt})
            import numpy as np

            return np.zeros(0, dtype=np.uint32)

        original = srv._positions_from_query
        srv._positions_from_query = _spion
        try:
            srv._search_docset_doc_ids(
                _LeererIndex(), "cql:[]",
                meta_filters={}, ai_filters={},
                include_ai=True, include_human=True, limit=500,
            )
        finally:
            srv._positions_from_query = original
        self.assertEqual(gesehen, [{"limit": 500, "ungedeckelt": False}])

    def test_der_engine_default_ist_wirklich_20000(self):
        """Die Tatsache, die den ersten Fix widerlegt hat, wird gepinnt.

        Faellt dieser Test, hat jemand die Semantik von ``limit=None`` eine
        Ebene tiefer geaendert. Dann gehoert die Uebersetzung hier neu
        bewertet, nicht stillschweigend behalten.
        """
        quelle = (
            _SRC / "candyconc" / "core" / "cql_engine.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "max_matches=int(limit) if limit is not None else 20000", quelle
        )

    def test_scan_alle_treffer_liegt_ueber_dem_engine_default(self):
        from candyconc.services.backend import server as srv

        self.assertGreater(srv.SCAN_ALLE_TREFFER, 20000)


class _LeererIndex:
    """Gerade so viel Index, wie die Funktion vor dem Spion anfasst."""

    class _FI:
        doc_metadata: dict = {}

    fast_index = _FI()


class AmEchtenIndexGemessen(unittest.TestCase):
    """Der Beweis am Korpus. Uebersprungen ohne Index, deshalb steht der
    tragende Nachweis oben und nicht hier."""

    @classmethod
    def setUpClass(cls):
        roh = os.environ.get("CANDYCONC_INDEX_PATH")
        if not roh or not Path(roh).exists():
            raise unittest.SkipTest("CANDYCONC_INDEX_PATH fehlt")
        from candyconc.services.backend import server as srv

        cls.srv = srv
        cls.idx = srv.get_corpus(None)

    def _docs(self, query: str, limit):
        doc_ids, _h, _r = self.srv._search_docset_doc_ids(
            self.idx, query, meta_filters={}, ai_filters={},
            include_ai=True, include_human=True, limit=limit,
        )
        tokens = int(self.idx.docset_token_count(doc_ids)) if doc_ids.size else 0
        return int(doc_ids.size), tokens

    def test_ohne_limit_wie_mit_grossem_limit(self):
        for query in ('cql:[pos="NOUN"]', 'cql:[word=".*"]', "cql:[]"):
            self.assertEqual(
                self._docs(query, None), self._docs(query, 200_000), query
            )

    def test_ohne_limit_mehr_als_der_alte_deckel(self):
        """Ueber 20.000 Treffern trennt sich gedeckelt von ungedeckelt."""
        gross = self._docs("cql:[]", None)
        gekappt = self._docs("cql:[]", 5000)
        self.assertGreater(gross[1], 20026, "Signatur des 20.000er-Deckels")
        self.assertGreater(gross[0], gekappt[0])


def _ohne_kommentare(text: str) -> str:
    """Kommentare erklaeren das ALTE Verhalten und nennen es beim Namen."""
    return "\n".join(
        z for z in text.splitlines() if not z.lstrip().startswith("#")
    )


def _funktion(pfad: Path, name: str) -> str:
    quelle = pfad.read_text(encoding="utf-8")
    start = quelle.index("def " + name)
    rest = quelle[start + 4:]
    ende = rest.find("\ndef ")
    ende2 = rest.find("\nasync def ")
    kandidaten = [x for x in (ende, ende2) if x > 0]
    return rest[: min(kandidaten)] if kandidaten else rest


class DerRankingdeckelKapptDenScanNichtMehr(unittest.TestCase):
    def test_subcorpus_aufloesung_ohne_deckel(self):
        rumpf = _ohne_kommentare(_funktion(_SERVER, "_resolve_subcorpus_doc_ids"))
        self.assertIn("limit=None", rumpf)
        self.assertNotIn("_bounded_analysis_job_limit(None)", rumpf)

    def test_route_trennt_fehlendes_von_gesetztem_limit(self):
        rumpf = _funktion(_ROUTE, "analysis_docset_from_search")
        self.assertIn('None if _roh_limit in (None, "")', rumpf)

    def test_wrapper_trennt_ebenso(self):
        rumpf = _funktion(_WRAPPER, "create_docset_tool")
        self.assertIn('None if limit in (None, "")', rumpf)

    def test_ein_gesetztes_limit_wirkt_weiterhin(self):
        """Eine ausdrueckliche Kappung bleibt eine Kappung."""
        for pfad, name in ((_ROUTE, "analysis_docset_from_search"),
                           (_WRAPPER, "create_docset_tool")):
            rumpf = _funktion(pfad, name)
            self.assertIn("_bounded_analysis_job_limit", rumpf, name)


class DerVollscanLaeuftImBegrenztenPool(unittest.TestCase):
    """Der ernste Einwand aus Runde 4, angenommen statt umgangen."""

    def test_route_nutzt_den_schweren_pool(self):
        rumpf = _funktion(_ROUTE, "analysis_docset_from_search")
        self.assertIn("_run_heavy_scan", rumpf)

    def test_der_scan_blockiert_die_event_loop_nicht(self):
        rumpf = _funktion(_ROUTE, "analysis_docset_from_search")
        i = rumpf.index("_search_docset_doc_ids")
        self.assertIn("await", rumpf[max(0, i - 200):i])

    def test_auch_die_subkorpus_aufloeser_nutzen_ihn(self):
        """Der Nachzug aus der Endabnahme: seit dem Wegfall des Deckels ist
        auch _resolve_subcorpus_doc_ids ein Vollscan."""
        for pfad in (_SUBROUTE, _ROUTE):
            quelle = pfad.read_text(encoding="utf-8")
            self.assertNotIn(
                "asyncio.to_thread(_server._resolve_subcorpus_doc_ids",
                quelle,
                pfad.name,
            )
            self.assertIn("_run_heavy_scan(\n", quelle, pfad.name)

    def test_der_pool_existiert_und_ist_begrenzt(self):
        from candyconc.services.backend import executors

        self.assertTrue(hasattr(executors, "_HEAVY_SCAN_EXECUTOR"))
        self.assertGreater(executors._HEAVY_SCAN_WORKERS, 0)


if __name__ == "__main__":
    unittest.main()


class DerUmfangWirdGENANNTStattGekappt(unittest.TestCase):
    """Der Nachzug aus der Selbstpruefung nach der Endabnahme.

    Die erste Reparatur hat den Deckel richtig aufgehoben und dabei eine
    neue Gefahr eingebaut. Selbst gemessen am 142M-Korpus (250.535
    Dokumente):

        cql:[]              142.044.149 Positionen, 233,6 s, 16,33 GB RSS
        cql:[word="der"]      2.988.554 Positionen,   3,4 s,  2,86 GB RSS

    Ein ungedeckelter Vollscan der degenerierten Abfrage ist also eine
    echte Speichergefahr. Der Punkt heisst aber "stille Kappungen sichtbar
    machen", nicht "unbegrenzt scannen": ein Deckel darf sein, er darf nur
    nicht schweigen.

    Vorgezaehlt wird ueber count_cql_matches_backend, und das ist fast
    gratis (0,06 s fuer [word="der"] gegen 3,4 s fuers Materialisieren).
    Nach der Reparatur, wieder am 142M gemessen:

        cql:[word="der"]  249.586 Dokumente,  5,3 s, 2,28 GB
        cql:[]            ABBRUCH mit Umfangsangabe, 46,4 s, 2,30 GB
    """

    def test_die_grenze_liegt_ueber_der_haeufigsten_wortform(self):
        from candyconc.services.backend import server as srv

        # 2.988.554 Positionen fuer [word="der"] am 142M-Korpus.
        self.assertGreater(srv.DOCSET_SCAN_POSITIONEN_MAX, 3_000_000)

    def test_unter_der_grenze_laeuft_der_scan_durch(self):
        from candyconc.services.backend import server as srv

        with _zaehlung(srv, 1_000_000):
            srv._pruefe_scan_umfang(_LeererIndex(), 'cql:[word="der"]')

    def test_ueber_der_grenze_bricht_er_MIT_UMFANGSANGABE_ab(self):
        from candyconc.services.backend import server as srv

        with _zaehlung(srv, 142_044_149):
            with self.assertRaises(ValueError) as ctx:
                srv._pruefe_scan_umfang(_LeererIndex(), "cql:[]")
        meldung = str(ctx.exception)
        self.assertIn("142.044.149", meldung, "der Umfang wird nicht genannt")
        self.assertIn("20.000.000", meldung, "die Grenze wird nicht genannt")
        self.assertIn("Nenner", meldung, "die Folge wird nicht benannt")

    def test_klartextabfragen_werden_nicht_vorgezaehlt(self):
        """Sie sind durch die Frequenz EINES Terms begrenzt."""
        from candyconc.services.backend import server as srv

        with _zaehlung(srv, 142_044_149):
            srv._pruefe_scan_umfang(_LeererIndex(), "Flucht")

    def test_ein_zaehlfehler_blockiert_den_scan_nicht(self):
        """Zaehlen ist Schutz, kein Ergebnis: lieber teuer als still falsch."""
        from candyconc.core import cql_engine
        from candyconc.services.backend import server as srv

        original = cql_engine.count_cql_matches_backend

        def _kaputt(*a, **kw):
            raise RuntimeError("Zaehlung nicht moeglich")

        cql_engine.count_cql_matches_backend = _kaputt
        try:
            srv._pruefe_scan_umfang(_LeererIndex(), "cql:[]")
        finally:
            cql_engine.count_cql_matches_backend = original

    def test_die_route_meldet_400_statt_500(self):
        quelle = _ROUTE.read_text(encoding="utf-8")
        rumpf = _funktion(_ROUTE, "analysis_docset_from_search")
        self.assertIn("except ValueError as exc:", rumpf)
        self.assertIn("status_code=400", rumpf)
        del quelle


import contextlib  # noqa: E402


@contextlib.contextmanager
def _zaehlung(srv, treffer):
    """count_cql_matches_backend durch einen festen Wert ersetzen."""
    from candyconc.core import cql_engine

    original = cql_engine.count_cql_matches_backend
    cql_engine.count_cql_matches_backend = lambda *a, **kw: treffer
    try:
        yield
    finally:
        cql_engine.count_cql_matches_backend = original
