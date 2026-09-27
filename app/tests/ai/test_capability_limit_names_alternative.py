"""Eine Grenze ohne Ausweg kostet den ganzen Turn.

LIVE am 2026-09-01, erste Antwort des sauberen Laufs. Das Modell rief
``frequency_list`` mit ``group_by="pos"`` auf einem Korpus auf, das nur
``word`` und ``lemma`` traegt. Der Aufruf scheiterte zu Recht. Die
ausgelieferte Antwort lautete danach VOLLSTAENDIG:

    Ich kann hier nur die direkt belegten Beobachtungen sicher berichten.

    Beobachtungen:
    - Es liegen noch keine hinreichend belegten Beobachtungen fuer eine
      belastbare Antwort vor.

    Limitationen:
    - Es fehlt fuer die angeforderte Analyse noetige Evidenz: Frequenzzeilen

525 Zeichen, null Befunde, 181 Sekunden. Dasselbe Werkzeug haette mit
``group_by="word"`` sofort geliefert.

DIE MELDUNG WAR DER GRUND. Sie lautete "Nicht erneut aufrufen: die Grenze
ehrlich benennen oder eine fachliche Alternative waehlen" und NANNTE
KEINE. Zusammengelesen heisst das: hoer auf. Genau das tat das Modell.

Der Harnisch kennt die Attributebenen des Korpus, sie stehen im
UI-Kontext und im Turn-Briefing. Wenn er sie kennt, muss er sie nennen.
Ein Turn ohne Befund ist teurer als jeder zusaetzliche Werkzeugaufruf.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from candyconc.candyconc_copilot.recipe_runtime import (
    capability_unavailable_result,
)

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "candyconc"

FEHLER = {
    "status": "error",
    "message": "missing_corpus_features: pos",
}


class DieGrenzeNenntDenAusweg(unittest.TestCase):
    def test_der_live_fall(self):
        aus = capability_unavailable_result(
            "frequency_list", FEHLER,
            args={"group_by": "pos"},
            vorhandene_ebenen=["word", "lemma"],
        )
        text = aus["message"]
        self.assertIn("word", text)
        self.assertIn("lemma", text)
        self.assertIn("group_by='word'", text)
        # Und das Wort, das das Modell zum Aufhoeren gebracht hat, ist weg.
        self.assertNotIn("Nicht erneut aufrufen", text)

    def test_der_ausweg_steht_auch_als_eigenes_feld(self):
        """Damit ein Renderer ihn zeigen kann, ohne den Satz zu zerlegen."""
        aus = capability_unavailable_result(
            "collocate_stats", FEHLER,
            args={"attribute": "pos"}, vorhandene_ebenen=["word"],
        )
        self.assertIn("attribute='word'", aus["ausweg"])

    def test_ohne_bekannte_ebenen_bleibt_es_bei_der_ehrlichen_grenze(self):
        """Nichts erfinden. Wer die Ebenen nicht kennt, nennt keine."""
        aus = capability_unavailable_result(
            "frequency_list", FEHLER, args={"group_by": "pos"},
        )
        self.assertEqual(aus["ausweg"], "")
        self.assertIn("fachliche Alternative", aus["message"])

    def test_eine_gueltige_ebene_bekommt_keinen_ausweg(self):
        """Scheitert word auf einem Korpus MIT word, liegt es nicht daran.

        Ohne diese Probe wuerde die Meldung dem Modell raten, denselben
        Aufruf mit demselben Argument zu wiederholen.
        """
        aus = capability_unavailable_result(
            "frequency_list", FEHLER,
            args={"group_by": "word"}, vorhandene_ebenen=["word", "lemma"],
        )
        self.assertEqual(aus["ausweg"], "")

    def test_ein_werkzeug_ohne_ebenenargument(self):
        aus = capability_unavailable_result(
            "word_sketch", FEHLER, args={}, vorhandene_ebenen=["word"],
        )
        self.assertEqual(aus["ausweg"], "")
        self.assertEqual(aus["status"], "unavailable")

    def test_der_orchestrator_reicht_die_ebenen_durch(self):
        """Die NAHT, ueber den Syntaxbaum.

        Ein Helfer, der die Ebenen verarbeiten KANN, nuetzt nichts, wenn
        der einzige Aufrufer sie nicht uebergibt.
        """
        quelle = (_SRC / "candyconc_copilot" / "orchestrator.py").read_text(
            encoding="utf-8"
        )
        rufe = [
            k for k in ast.walk(ast.parse(quelle))
            if isinstance(k, ast.Call)
            and getattr(k.func, "id", "") == "capability_unavailable_result"
        ]
        self.assertTrue(rufe, "kein Aufruf gefunden")
        for ruf in rufe:
            namen = {kw.arg for kw in ruf.keywords}
            self.assertIn("vorhandene_ebenen", namen, sorted(namen))
            self.assertIn("args", namen, sorted(namen))


class DieKeynessGrenzeNenntDenAusweg(unittest.TestCase):
    """Dieselbe Klasse, zweiter Fall, LIVE am 2026-09-02.

    Das Modell uebergab sieben zu pruefende Kandidatenformen als
    ``target`` und eine ``reference_docset_id``. Die Meldung nannte nur
    den fehlenden Parameter. Der Turn wich danach auf eine globale Keyness
    ueber 389.305 Zeilen aus und meldete, dass keiner der sieben in den
    sichtbaren Zeilen steht. Eine Grenze, die den Ausweg verschweigt,
    kostet den Rest des Turns.
    """

    def _quelle(self) -> str:
        return (
            _SRC / "candyconc_copilot" / "tool_wrappers.py"
        ).read_text(encoding="utf-8")

    def test_die_meldung_nennt_den_termlisten_weg(self):
        quelle = self._quelle()
        anfang = quelle.index(
            "reference_docset_id ohne target_docset_id ergibt keinen"
        )
        meldung = quelle[anfang : anfang + 700]
        # Der bisherige Satz bleibt: der fehlende Parameter ist die
        # naechstliegende Reparatur, wenn wirklich zwei Docsets gemeint waren.
        self.assertIn("Gib target_docset_id an.", meldung)
        # Und der Ausweg fuer den Fall, der die 400 ausgeloest hat.
        self.assertIn("Kandidatenliste", meldung)
        self.assertIn("query_count", meldung)
        self.assertIn("Tokenstrom", meldung)

    def test_der_ausweg_kommt_als_ganzer_satz_beim_modell_an(self):
        """Der ZUSAMMENGESETZTE String, nicht die Quellzeilen.

        Eine Probe an den Quellzeilen allein bemerkt einen fehlenden
        Zwischenraum an einer Fuegung nicht: aus "Tokenstrom, der"
        gezaehlt" und "wird." wird sonst "gezaehltwird". Der String wird
        deshalb aus dem Syntaxbaum ausgewertet. Ein Import von
        ``tool_wrappers`` scheidet aus, weil tests/conftest.py dort einen
        Stub in ``sys.modules`` haengt.
        """
        baum = ast.parse(self._quelle())
        texte = [
            k.value
            for k in ast.walk(baum)
            if isinstance(k, ast.Constant)
            and isinstance(k.value, str)
            and k.value.startswith(
                "reference_docset_id ohne target_docset_id"
            )
        ]
        self.assertEqual(len(texte), 1, "Meldung nicht eindeutig gefunden")
        text = texte[0]
        self.assertIn("target ist ein Tokenstrom, der gezählt wird", text)
        self.assertIn(
            "query_count(query=Kandidat, docset_id=...) auf beiden Seiten",
            text,
        )


if __name__ == "__main__":
    unittest.main()
