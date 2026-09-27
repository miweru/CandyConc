"""P2.4: Dispersion gehoert zur Zaehlfrage, nicht in eine Prosa-Option.

Methoden-Invariante 3 (prompt_layout) verlangt, dass ein Frequenzbefund
ohne Dispersion oder Dokumentabdeckung nicht als korpusweit gilt. Die Norm
war faktisch abgeschaltet: ``dispersion_offsets`` stand nur als optionaler
Prosa-Schritt im Briefing des Rezepts ``frequenz`` und scheiterte an DREI
hintereinandergeschalteten Filtern.

    1. Werkzeugraum: ``expand_tools_for_recipe`` ergaenzt nur, was in
       ``kern_tools`` steht, und dort standen nur query_count und
       frequency_list.
    2. Kontrakt: ``heuristic_analysis_contract`` liefert fuer die
       Zaehlfrage ein Bundle ohne dispersion_offsets.
    3. Vorplan: ``preplanned_tool_calls`` verwirft jeden Eintrag, der
       weder verfuegbar noch im Kontrakt-Bundle liegt, und die Notklausel
       greift nur, wenn NICHTS uebrig bleibt. query_count ueberlebte, also
       fiel der Dispersionsschritt still heraus.

Ein Test, der nur den Vorplan prueft, haette das nicht gefunden: er
passiert Filter 3 nicht. Deshalb prueft dieser Test alle drei einzeln.

Die Berichtshaelfte erledigt P2.3: sobald ein Dispersions-Item vorliegt,
rendert der Methodensteckbrief Einheit, Trefferdokumente, Abdeckung, DP,
DPnorm, Juilland-D und Carroll-D2, und zwar auf JEDER Landung.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import recipe_runtime as rr  # noqa: E402
from candyconc.candyconc_copilot.grounding_contracts import (  # noqa: E402
    heuristic_analysis_contract,
)
from candyconc.candyconc_copilot.recipes import get_recipe  # noqa: E402

ZAEHLFRAGE = 'Wie haeufig kommt "Menschen" im Korpus vor, pro Million Tokens?'


class DerVorplanHoltDieDispersion(unittest.TestCase):
    def test_zwei_schritte_mit_gebundenem_term(self):
        plan = rr.plan_recipe_first_round("frequenz", "Wie oft kommt ‚Frau‘ vor?")
        self.assertEqual(
            plan,
            [
                {"tool": "query_count", "args": {"query": "Frau"}},
                {"tool": "dispersion_offsets", "args": {"term": "Frau"}},
            ],
        )

    def test_der_zaehlschritt_bleibt_der_erste(self):
        """Die exakte Zaehlung fuehrt, die Dispersion ergaenzt sie."""
        plan = rr.plan_recipe_first_round("frequenz", "Wie oft kommt ‚Frau‘ vor?")
        self.assertEqual(plan[0]["tool"], "query_count")

    def test_ohne_term_kein_plan(self):
        self.assertEqual(
            rr.plan_recipe_first_round("frequenz", "Wie oft kommt Frau vor?"), []
        )


class AlleDreiFilterLassenSieDurch(unittest.TestCase):
    """Der eigentliche Befund. Jeder Filter einzeln geprueft."""

    WERKZEUGE = (
        "query_count", "frequency_list", "run_cqlf_query",
        "dispersion_offsets", "kwic_context",
    )

    def test_filter_1_werkzeugraum(self):
        kern = get_recipe("frequenz").kern_tools
        self.assertIn("dispersion_offsets", kern)
        self.assertIn("query_count", kern)

    def test_filter_2_kontrakt_bundle(self):
        kontrakt = heuristic_analysis_contract(
            ZAEHLFRAGE,
            available_tools=self.WERKZEUGE,
            read_only_tools=self.WERKZEUGE,
        )
        erlaubt = list(getattr(kontrakt, "allowed_tools", []) or [])
        self.assertIn("dispersion_offsets", erlaubt)
        self.assertEqual(erlaubt[0], "query_count", "die Zaehlung fuehrt weiter")

    def test_filter_3_vorplan_verwirft_sie_nicht_mehr(self):
        """Der Filter, an dem die Dispersion still herausfiel."""
        kontrakt = heuristic_analysis_contract(
            ZAEHLFRAGE,
            available_tools=self.WERKZEUGE,
            read_only_tools=self.WERKZEUGE,
        )
        rufe, _notizen = rr.preplan_with_contract(
            "frequenz", ZAEHLFRAGE, None,
            available_tools=self.WERKZEUGE,
            gated_tools=None,
            contract_tools=list(getattr(kontrakt, "allowed_tools", []) or []),
        )
        # preplan_with_contract liefert fertige OpenAI-Tool-Calls, nicht
        # die Rohform des Vorplans.
        namen = [
            (r.get("function") or {}).get("name") for r in (rufe or [])
        ]
        self.assertIn("dispersion_offsets", namen)
        self.assertEqual(namen[0], "query_count")
        # Und der Term ist gebunden, nicht der Platzhalter.
        import json as _json
        args = _json.loads(
            (rufe[1].get("function") or {}).get("arguments") or "{}"
        )
        self.assertEqual(args.get("term"), "Menschen")


class DieBerichtshaelfteKommtVonP23(unittest.TestCase):
    """Sobald das Item da ist, rendert der Steckbrief die Kennwerte."""

    def _item(self):
        from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

        return make_evidence_item(
            item_id="ev2", tool="dispersion_offsets", tool_call_id="c2",
            query={"term": "Menschen"},
            # Keep n_documents as the corpus document count and range as the count
            # of hit-bearing documents. Swapping them would invalidate coverage.
            output={
                "status": "success", "term": "Menschen", "unit": "documents",
                "total_hits": 61, "n_documents": 2000, "range": 57,
                "coverage_ratio": 0.0285,
                "dp": 0.9557, "dpnorm": 0.9559, "juilland_d": 0.8595,
                "carroll_d2": 0.5289,
            },
            analysis_family="term_frequency",
        )

    def test_der_steckbrief_traegt_die_dispersion(self):
        # Bei 61 Treffern auf 2.000 Dokumente sind DP und Juilland-D nicht
        # deutbar: DP ist dort rechnerisch nahe 1 gebunden, unabhaengig von
        # der tatsaechlichen Streuung. Der Steckbrief traegt die Dispersion
        # trotzdem, nur als die Angabe, die etwas sagt.
        text = rr.methodensteckbrief_anhaengen(
            "`Menschen` kommt 61-mal vor.", [self._item()]
        )
        self.assertIn("Dispersion", text)
        self.assertIn("Dokumentabdeckung", text)
        self.assertIn("Reichweite", text)
        self.assertIn("57 von 2000", text)
        self.assertNotIn("0.9557", text)

    def test_bei_dichter_beleglage_stehen_die_kennwerte_im_steckbrief(self):
        # POSITIVE KLASSE. Ohne sie waere die Unterdrueckung nicht von
        # einem Renderer zu unterscheiden, der die Dispersion IMMER
        # verschweigt.
        from candyconc.candyconc_copilot.grounding_facts import (
            make_evidence_item,
        )

        dicht = make_evidence_item(
            item_id="ev3", tool="dispersion_offsets", tool_call_id="c3",
            query={"term": "und"},
            output={
                "status": "success", "term": "und", "unit": "documents",
                "total_hits": 919, "n_documents": 2000, "range": 700,
                "coverage_ratio": 0.35, "dp": 0.62, "dpnorm": 0.63,
                "juilland_d": 0.71, "carroll_d2": 0.55,
            },
            analysis_family="term_frequency",
        )
        text = rr.methodensteckbrief_anhaengen("`und` kommt vor.", [dicht])
        self.assertIn("DP 0.62", text)
        self.assertIn("Juilland-D 0.71", text)

    def test_auf_dem_skip_pfad_ebenfalls(self):
        entwurf = rr.verifier_skipped_answer_text(
            "`Menschen` kommt 61-mal vor.",
            lambda draft: {"text": draft, "bare_numbers": []},
            lambda: "", lambda _g: "fail-closed", quote_surfaces=[],
        )
        d = self._item()
        text, _ = rr.politur_mit_zitatwache(
            entwurf, [d.model_dump() if hasattr(d, "model_dump") else d]
        )
        self.assertIn("Dispersion", text)
        self.assertIn("Reichweite", text)

class KeineErfundeneKorpusweiteNull(unittest.TestCase):
    """Der ernste Einwand der Endabnahme.

    ``sequence_positions`` ist ein PHRASENsucher ueber eine Tokenliste. Ein
    mehrwortiger Term als EIN Listenelement schlug im Wortlexikon nach,
    fand kein Token 'nicht mehr', bekam id 0 und lieferte leer. Das
    Werkzeug meldete dafuer ``status: success`` mit ``total_hits: 0``,
    waehrend ``query_count`` fuer dieselbe Zeichenkette ehrlich scheitert.

    Weil P2.4 den Dispersionsschritt bei JEDER Zaehlfrage vorplant und P2.3
    ihn auf jeder Landung rendert, stand diese erfundene korpusweite Null
    danach im Methodensteckbrief unter einer Antwort, deren Zaehlung
    gescheitert war. Der Defekt ist aelter als der Punkt, aber P2.4 hat ihn
    auf den Standardpfad gehoben.

    Am Testindex nachgemessen: 'nicht mehr' liefert jetzt 36 Treffer,
    exakt die casefold-Zaehlung ``[word="nicht"%c] [word="mehr"%c]``. Der
    Klartextpfad ist per Vertrag gefaltet, die ungefaltete CQL-Variante
    findet 34.
    """

    def test_dispersion_und_zaehlung_lesen_DIESELBE_abfrage(self):
        """Der Kern, ueber ALLE Schreibweisen.

        Die erste Reparatur hat den Term in einer ZWEITEN, eigenen Funktion
        zerlegt (``_phrasen_tokens`` auf dem rohen Nutzerstring). Damit war
        die erfundene Null nicht weg, sondern auf die anderen
        Schreibweisen verschoben: Anfuehrungszeichen, Wildcards und
        Operatoren waren fuer sie Buchstaben eines Tokens. Am Testindex
        gemessen, Zaehlung gegen Dispersion:

            '"nicht mehr"'   36 gegen 0
            '"und"'         919 gegen 0
            'Mensch*'        95 gegen 0
            'nicht OR mehr' 753 gegen 0

        Jetzt laeuft der Klartextzweig durch ``_positions_from_query``,
        also durch dieselbe Auswertung wie ``query_count``.
        """
        quelle = (
            _SRC / "candyconc/services/backend/server.py"
        ).read_text(encoding="utf-8")
        i = quelle.index("def _dispersion_positions_for_term")
        rumpf = quelle[i: quelle.index("\ndef ", i + 10)]
        self.assertIn("_positions_from_query(", rumpf)
        self.assertNotIn("_dispersion_offsets(", rumpf)

    def test_es_gibt_keine_zweite_zerlegung_mehr(self):
        quelle = (
            _SRC / "candyconc/candyconc_copilot/analysis.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("_phrasen_tokens", quelle)


if __name__ == "__main__":
    unittest.main()
