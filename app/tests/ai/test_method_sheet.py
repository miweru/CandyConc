"""P2.3: Der Methodensteckbrief ist Pflichtbestandteil jeder Antwort.

Die Werkzeuge liefern Abfragemodus, Attribut, Faltung, Fenster,
Satzgrenze, Mindestfrequenz und Nenner samt Scope bereits zwingend in
ihrem Response-Schema, und ``_analysis_provenance_lines`` rendert das seit
Langem. Nur zwang NICHTS zur Ausgabe. In der Antwort stand damit eine Zahl
ohne die Angaben, die eine Fachperson braucht, um sie einzuordnen.

Der Anhang haengt am Politur-Chokepoint und greift deshalb auf JEDER
Landung, auch auf dem Verifier-Skip-Pfad, wo der volle Regelsatz nicht
laeuft. Er kostet keinen Modellaufruf.

Dazu die eine echte Fehlmeldung der bestehenden Provenienz: 'Mindestfrequenz
5' liess offen, ob die Analystin den Wert gewaehlt hat oder ob der adaptive
Boden ihn kalibriert hat. Die Herkunft steht jetzt dabei, byte-gleich
berechnet zur REST-Route (dort der Block ab ``if min_freq_value > 0:``;
eine feste Zeilennummer war hier schon einmal falsch und zeigte auf den
Kommentar zum Kandidaten-Builder-Boden).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import recipe_runtime as rr  # noqa: E402
from candyconc.candyconc_copilot.analysis_grounding import (  # noqa: E402
    _analysis_provenance_lines,
)
from candyconc.candyconc_copilot.grounding_evidence import (  # noqa: E402
    build_grounding_surface,
    extract_raw_surface,
)
from candyconc.candyconc_copilot.grounding_facts import (  # noqa: E402
    make_evidence_item,
)

KOLLOKAT_AUSGABE = {
    "status": "success", "requested_term": "kunne", "effective_term": "kunne",
    "term_mode": "plain", "window": 5, "within_sentence": True,
    "min_freq": 5, "node_frequency": 460712, "sort_by": "logdice",
    "method": {"attribute": "word", "floor_mode": "adaptive"},
    "scope": {"corpus_id": "sample_corpus_v4", "level": "corpus"},
    "rows": [{"word": "vi", "f": 900, "logdice": 8.1}],
}

ZAEHL_AUSGABE = {
    "status": "success", "query": '[lemma="kunne"]', "total": 460712,
    "corpus_tokens": 47058875, "denominator_tokens": 47058875,
    "denominator_scope": "corpus", "per_million": 9790.1,
    "scope": {"corpus_id": "sample_corpus_v4", "level": "corpus"},
    "query_mode": "cqlf", "attribute": "explicit_in_query",
    "case_insensitive": True,
}


def _posten(tool: str, ausgabe: dict, item_id: str = "ev1"):
    return make_evidence_item(
        item_id=item_id, tool=tool, tool_call_id="c", query={"term": "kunne"},
        output=ausgabe, analysis_family="assoziation",
    )


def _als_dict(item):
    return item.model_dump() if hasattr(item, "model_dump") else dict(item.__dict__)



def _werkzeugzeilen(text: str) -> int:
    """Count tool provenance rows separately from the corpus revision.

The revision appears at most once and only for the corpus used by the
measurement. The synthetic sample_corpus_v4 fixture need not be loadable."""
    return sum(
        1 for zeile in text.splitlines()
        if zeile.startswith("- ") and "Indexstand" not in zeile
    )


class SteckbriefWirdAngehaengt(unittest.TestCase):
    def test_zwei_werkzeuge_ergeben_zwei_zeilen(self):
        text = rr.methodensteckbrief_anhaengen(
            "Kernbefund: kunne ist haeufig.",
            [_posten("query_count", ZAEHL_AUSGABE, "ev1"),
             _posten("collocate_stats", KOLLOKAT_AUSGABE, "ev2")],
        )
        self.assertIn(rr.METHODENSTECKBRIEF_UEBERSCHRIFT, text)
        # EINE Zeile je Werkzeug. Der Indexstand kommt seit P2.3 dazu und
        # gehoert dem KORPUS, nicht einem Werkzeug: er wird deshalb
        # getrennt gezaehlt, statt die Werkzeugzahl zu verwaessern.
        self.assertEqual(_werkzeugzeilen(text), 2)
        self.assertLessEqual(text.count("Indexstand"), 1)
        self.assertIn("Abfragemodus: cqlf", text)
        self.assertIn("Fenster ±5", text)

    def test_leerer_text_bleibt_leer(self):
        self.assertEqual(rr.methodensteckbrief_anhaengen("   ", [_posten("query_count", ZAEHL_AUSGABE)]), "   ")

    def test_ohne_evidenz_bleibt_der_text_unveraendert(self):
        roh = "Kernbefund: nichts gemessen."
        self.assertEqual(rr.methodensteckbrief_anhaengen(roh, []), roh)


class Zeilenbilanz(unittest.TestCase):
    """Distinguish the total hit count from the returned row count.

When they differ, state their relationship so row truncation is visible."""

    @staticmethod
    def _kwic(total: int, zeilen: int) -> dict:
        return {
            "status": "success", "query": '[lemma="kunne"]', "total": total,
            "query_mode": "cqlf", "attribute": "explicit_in_query",
            "case_insensitive": True, "ctx": 5,
            "scope": {"corpus_id": "sample_corpus_v4", "level": "corpus"},
            "rows": [
                {"left": f"l{i}", "kw": "kunne", "right": f"r{i}", "doc_id": i}
                for i in range(zeilen)
            ],
        }

    def test_gleichstand_nennt_die_zahl_nur_einmal(self):
        zeile = _analysis_provenance_lines(
            [_posten("run_cqlf_query", self._kwic(18, 18))]
        )[0]
        self.assertIn("Treffer: 18, alle als Ergebniszeilen zurückgegeben", zeile)
        self.assertNotIn("18, 18", zeile)

    def test_kappung_benennt_das_verhaeltnis(self):
        zeile = _analysis_provenance_lines(
            [_posten("run_cqlf_query", self._kwic(652124, 30))]
        )[0]
        self.assertIn(
            "Treffer: 652.124, davon 30 als Ergebniszeilen zurückgegeben", zeile
        )

    def test_ohne_trefferzahl_bleibt_der_wortlaut_unveraendert(self):
        # collocate_stats traegt keinen Treffer-Eintrag. Dort ist die
        # Zeilenzahl die einzige Angabe und traegt ihre Bedeutung allein.
        zeile = _analysis_provenance_lines(
            [_posten("collocate_stats", KOLLOKAT_AUSGABE)]
        )[0]
        self.assertIn("zurückgegebene Ergebniszeilen", zeile)
        self.assertNotIn("davon", zeile)


class Idempotenz(unittest.TestCase):
    """``_build_term_profile_markdown`` rendert dieselben Zeilen selbst."""

    def test_zweiter_durchlauf_ist_byte_identisch(self):
        posten = [_posten("collocate_stats", KOLLOKAT_AUSGABE)]
        einmal = rr.methodensteckbrief_anhaengen("Befund.", posten)
        zweimal = rr.methodensteckbrief_anhaengen(einmal, posten)
        self.assertEqual(einmal, zweimal)

    def test_bereits_gerenderte_zeile_verhindert_den_anhang(self):
        posten = [_posten("collocate_stats", KOLLOKAT_AUSGABE)]
        zeile = _analysis_provenance_lines(posten)[0].strip()
        roh = "Methoden- und Scope-Provenienz:\n" + zeile
        self.assertEqual(rr.methodensteckbrief_anhaengen(roh, posten), roh)


class RobustheitKostetNieDieAntwort(unittest.TestCase):
    def test_unvollstaendige_dicts_lassen_den_text_unveraendert(self):
        """Die Form aus tests/backend/test_salvage_quote_guard.py."""
        roh = "Kernbefund: etwas."
        kaputt = [{"grounding_surface": [], "fact_surface": {"rows": []}}]
        self.assertEqual(rr.methodensteckbrief_anhaengen(roh, kaputt), roh)

    def test_gescheiterte_werkzeuge_erzeugen_keinen_steckbrief(self):
        """Ein gescheitertes Werkzeug hat keine Methode beigetragen.

        Beim ersten vollen Lauf fielen sechs Tests aus Fehlerbehandlung und
        Retries, weil ``_analysis_provenance_lines`` fuer ein gescheitertes
        Werkzeug eine Zeile rendert ('lookup_tool (fehlgeschlagen): nicht
        als Evidenz verwendet, Fehler: boom'). Die gehoert in die
        Fehlerbehandlung, nicht unter eine Ueberschrift, die Methode
        verspricht, und schon gar nicht an eine Antwort, die 'done' lautet.
        """
        kaputt = _posten("collocate_stats", dict(KOLLOKAT_AUSGABE, status="error"))
        self.assertEqual(rr.methodensteckbrief_anhaengen("done", [kaputt]), "done")

    def test_erfolgreiche_neben_gescheiterten_zaehlen_weiter(self):
        gut = _posten("collocate_stats", KOLLOKAT_AUSGABE, "ev1")
        schlecht = _posten("query_count", dict(ZAEHL_AUSGABE, status="error"), "ev2")
        text = rr.methodensteckbrief_anhaengen("Befund.", [gut, schlecht])
        self.assertIn(rr.METHODENSTECKBRIEF_UEBERSCHRIFT, text)
        self.assertEqual(_werkzeugzeilen(text), 1)
        self.assertLessEqual(text.count("Indexstand"), 1)
        self.assertNotIn("fehlgeschlagen", text)

    def test_muell_laesst_den_text_unveraendert(self):
        roh = "Kernbefund: etwas."
        for muell in ([None], [42], ["text"], [{"a": object()}]):
            self.assertEqual(rr.methodensteckbrief_anhaengen(roh, muell), roh)


class VerdrahtungAmChokepoint(unittest.TestCase):
    """Die Lehre der vier Zitatwache-Anlaeufe: Verhalten UND Verdrahtung."""

    def test_politur_haengt_ihn_an(self):
        text, _ = rr.politur_mit_zitatwache(
            "Kernbefund: kunne ist haeufig.",
            [_als_dict(_posten("collocate_stats", KOLLOKAT_AUSGABE))],
        )
        self.assertIn(rr.METHODENSTECKBRIEF_UEBERSCHRIFT, text)

    def test_ohne_evidenz_kein_anhang(self):
        text, _ = rr.politur_mit_zitatwache("Kernbefund: etwas.", [])
        self.assertNotIn(rr.METHODENSTECKBRIEF_UEBERSCHRIFT, text)

    def test_die_quelle_ruft_ihn_im_chokepoint(self):
        """Der GANZE Rumpf, nicht die ersten 2.600 Zeichen davon.

        Die erste Fassung schnitt ein festes Zeichenfenster aus der Quelle.
        Am 2026-09-01 wanderte der Aufruf durch drei zusaetzliche
        Kommentarzeilen aus diesem Fenster heraus, und der Test meldete
        eine fehlende Verdrahtung, die vollstaendig vorhanden war. Ein
        Zeichenfenster misst die Laenge der Kommentare, nicht die
        Verdrahtung. Der Syntaxbaum misst die Verdrahtung.
        """
        import ast

        quelle = (
            _SRC / "candyconc" / "candyconc_copilot" / "recipe_runtime.py"
        ).read_text(encoding="utf-8")
        ziel = next(
            k for k in ast.walk(ast.parse(quelle))
            if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
            and k.name == "politur_mit_zitatwache"
        )
        gerufen = {
            getattr(k.func, "id", "")
            for k in ast.walk(ziel) if isinstance(k, ast.Call)
        }
        self.assertIn("methodensteckbrief_anhaengen", gerufen)

    def test_skip_pfad_traegt_ihn_ebenfalls(self):
        """Der Pfad, auf dem der volle Regelsatz NICHT laeuft."""
        entwurf = rr.verifier_skipped_answer_text(
            "Kernbefund: kunne ist haeufig.",
            lambda draft: {"text": draft, "bare_numbers": []},
            lambda: "",
            lambda _grund: "fail-closed",
            quote_surfaces=[],
        )
        text, _ = rr.politur_mit_zitatwache(
            entwurf, [_als_dict(_posten("collocate_stats", KOLLOKAT_AUSGABE))]
        )
        self.assertIn(rr.METHODENSTECKBRIEF_UEBERSCHRIFT, text)


class HerkunftDesBodens(unittest.TestCase):
    def test_renderer_nennt_die_kalibrierung_NICHT_wo_keine_ist(self):
        """Die Umkehrung des Vorgaengertests, und sie ist die Korrektur.

        Die Attrappe traegt node_frequency 460.712, also weit ueber der
        Kalibrierungsschwelle 50. Dort gibt adaptive_collocate_min_freq
        KONSTANT 5 zurueck, unabhaengig vom Wert. "aus der Knotenfrequenz
        kalibriert" war fuer jeden realistischen Knoten falsch, und eine
        Professorin-Subagentin hat den Satz am 2026-08-29 als schweren
        Mangel gewertet.
        """
        zeile = _analysis_provenance_lines(
            [_posten("collocate_stats", KOLLOKAT_AUSGABE)]
        )[0]
        self.assertIn("Mindestfrequenz 5 (Standardboden", zeile)
        self.assertIn("460712", zeile)
        self.assertIn("Kalibrierungsschwelle 50", zeile)
        self.assertNotIn("kalibriert)", zeile)

    def test_unterhalb_der_schwelle_wird_wirklich_kalibriert(self):
        """POSITIVE GEGENKLASSE.

        Ohne sie waere eine Fassung gruen, die das Wort ueberall streicht,
        und der Zusatz waere dort weg, wo er stimmt.
        """
        aus = dict(KOLLOKAT_AUSGABE)
        aus["node_frequency"] = 20
        aus["min_freq"] = 2
        zeile = _analysis_provenance_lines([_posten("collocate_stats", aus)])[0]
        self.assertIn("aus der Knotenfrequenz 20 kalibriert", zeile)
        self.assertNotIn("Standardboden", zeile)

    def test_als_argument_gesetzt(self):
        aus = dict(KOLLOKAT_AUSGABE)
        aus["method"] = {"attribute": "word", "floor_mode": "requested"}
        zeile = _analysis_provenance_lines([_posten("collocate_stats", aus)])[0]
        self.assertIn("(als Argument gesetzt)", zeile)

    def test_unbekannte_herkunft_wird_weggelassen_statt_geraten(self):
        aus = dict(KOLLOKAT_AUSGABE)
        aus["method"] = {"attribute": "word", "floor_mode": "quatsch"}
        zeile = _analysis_provenance_lines([_posten("collocate_stats", aus)])[0]
        self.assertIn("Mindestfrequenz 5,", zeile)
        self.assertNotIn("quatsch", zeile)

    def test_ueberlebt_beide_oberflaechen(self):
        """Der in Runde 1 uebersehene Teil: extract_raw_surface filtert VORHER."""
        roh = extract_raw_surface(KOLLOKAT_AUSGABE)
        self.assertEqual(roh["method"].get("floor_mode"), "adaptive")
        flaeche = build_grounding_surface(roh)
        self.assertTrue(any("floor_mode=adaptive" in z for z in flaeche))

    def test_alle_drei_erzeuger_nutzen_DIESELBE_naht(self):
        """Es gibt DREI Erzeuger, nicht zwei.

        Der Copilot-Wrapper, die synchrone REST-Route und
        ``_run_collocates_job`` haben den Block wortgleich gefuehrt. Die
        erste Fassung des Fixes hat zwei nachgezogen, und der dritte, der
        Job-Pfad, ist ausgerechnet der, den die Produktoberflaeche benutzt
        (``capabilities/product.py`` fuehrt die synchrone Route als
        Expert/API-Pfad). Repariert war also der Pfad, den die Oberflaeche
        NICHT benutzen darf. Deshalb pinnt dieser Test nicht mehr die
        Gleichheit dreier Textbloecke, sondern dass es nur noch EINEN gibt.
        """
        erzeuger = (
            _SRC / "candyconc" / "candyconc_copilot" / "tool_wrappers.py",
            _SRC / "candyconc" / "services" / "backend" / "routes" / "analysis.py",
            _SRC / "candyconc" / "services" / "backend" / "server.py",
        )
        # Eine ZUWEISUNG ist eine ganze Zeile. Eine Erwaehnung in einem
        # Docstring ist keine, und genau daran ist die erste Fassung
        # dieses Tests gescheitert.
        zuweisung = re.compile(
            r'^\s*floor_mode = "(adaptive|requested|default)"\s*$', re.M
        )
        for pfad in erzeuger:
            quelle = pfad.read_text(encoding='utf-8')
            self.assertIn('collocate_floor_mode(', quelle, pfad.name)
            self.assertIsNone(
                zuweisung.search(quelle),
                '%s fuehrt noch einen eigenen Block' % pfad.name,
            )

    def test_die_naht_entscheidet_wie_erwartet(self):
        from candyconc.analysis_defaults import collocate_floor_mode

        self.assertEqual(collocate_floor_mode(1, 2, 4393), "requested_raised")
        self.assertEqual(collocate_floor_mode(3, 3, 4393), "requested")
        self.assertEqual(collocate_floor_mode(None, 5, 4393), "adaptive")
        self.assertEqual(collocate_floor_mode(0, 5, None), "default")

    def test_ein_angehobener_boden_heisst_nicht_gesetzt(self):
        """Der ernste Einwand der Endabnahme.

        ``adaptive_collocate_min_freq`` klemmt jeden expliziten Wert auf
        mindestens 2 hoch (ein f=1-Paar ist ein Kookkurrenz-Hapax). Wer 1
        anforderte, las 'Mindestfrequenz 2 (als Argument gesetzt)'. Gesetzt
        war 1. Am Testindex nachgemessen: angefordert 1, effektiv 2,
        Modus jetzt ``requested_raised``.
        """
        from candyconc.analysis_defaults import adaptive_collocate_min_freq

        self.assertEqual(adaptive_collocate_min_freq(None, 1), 2)
        self.assertEqual(adaptive_collocate_min_freq(None, 3), 3)

        aus = dict(KOLLOKAT_AUSGABE)
        aus["min_freq"] = 2
        aus["method"] = {"attribute": "word", "floor_mode": "requested_raised"}
        zeile = _analysis_provenance_lines([_posten("collocate_stats", aus)])[0]
        self.assertIn(
            "Mindestfrequenz 2 (angefordert und auf den "
            "Zuverlässigkeitsboden angehoben)",
            zeile,
        )
        self.assertNotIn("(als Argument gesetzt)", zeile)

    def test_schema_verlangt_das_feld(self):
        """_obj setzt additionalProperties=False, ohne Deklaration bricht die Validierung.

        ``tests/conftest.py`` schiebt ein STUB-``tool_wrappers`` in
        ``sys.modules``, ein schlichtes ``import`` liefert also nicht die
        echten Schemata. Der vorgesehene Lader holt sie.
        """
        from tests.ai.test_tool_wrappers_parity_r5 import (
            _load_real_tool_wrappers,
        )

        echte = _load_real_tool_wrappers()
        method = echte.COLLOCATE_RESPONSE["properties"]["method"]
        self.assertIn("floor_mode", method["properties"])
        self.assertIn("floor_mode", method["required"])


if __name__ == "__main__":
    unittest.main()
