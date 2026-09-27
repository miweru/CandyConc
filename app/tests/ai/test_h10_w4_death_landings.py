"""H10/W4 (G4): Ehrliche, deliverable-bewusste Todespfad-Landungen.

Offline-Anker aus dem Gutachter-Dossier:

* KWIC-Evidenz mit 20 sichtbaren Zeilen + Backstop => Gebrauchsreport mit
  mindestens 4 Belegen und Einordnung ALLER Zeilen, KEIN Zwei-Fragmente-Digest
  ('Analysebericht (sichtbare Evidenz)').
* Engine-Fehler-Turn => partial/ehrlicher Status (nie formal 'completed'),
  die Landung nennt den Grund in genau einem Satz.
* Frequenz-Backstop => Zahl+pmw des RICHTIGEN Terms. Werte fremder Queries
  werden nie mit dem Frage-Term verheiratet (G2 auf Builder-Ebene).

Alles offline (Fake-Evidenz, kein LLM, kein Index).
"""

from __future__ import annotations

import unittest

from tests.ai._real_copilot import ReActOrchestrator

from candyconc.candyconc_copilot.death_landings import (
    build_death_landing,
    death_landing_from_turn_state,
)
from candyconc.candyconc_copilot.grounding_schemas import EvidenceItem
from candyconc.services.backend import server as _server
from candyconc.services.backend.routes.copilot import _copilot_terminal_events
import re

def _verteilungsabschnitt(text: str) -> list[tuple[int, int]]:
    """Die Gruppenzeilen des Verteilungsabschnitts als (n, gesamt)-Paare.

    Prueft die EIGENSCHAFT statt eines Markennamens: frueher stand hier
    ``assertIn("Typologie-Skelett", ...)``. Das nagelt eine Formulierung
    fest, nicht das Verhalten, und blockierte eine reine Textverbesserung,
    ohne irgendeine Zusicherung zu geben. Zugesichert ist: der Bericht
    ordnet ALLE sichtbaren Zeilen in Gruppen ein.
    """
    return [
        (int(a), int(b))
        for a, b in re.findall(r"^- .+?: (\d+) von (\d+) Zeilen", text, re.M)
    ]


def _ordnet_alle_zeilen_ein(text: str, erwartet: int | None = None) -> bool:
    paare = _verteilungsabschnitt(text)
    if not paare:
        return False
    gesamt = {b for _, b in paare}
    if len(gesamt) != 1:
        return False
    (n,) = gesamt
    if erwartet is not None and n != erwartet:
        return False
    return sum(a for a, _ in paare) == n



def _ev(tool: str, query: str, raw_surface: dict, *, status: str = "success") -> EvidenceItem:
    return EvidenceItem(
        id=f"ev_{tool}_{abs(hash(query)) % 10000}",
        tool=tool,
        tool_call_id="call_1",
        query=query,
        status=status,
        truncated=False,
        raw_surface=raw_surface,
    )


def _kwic_rows(n: int = 20) -> list:
    rows = []
    contexts = [
        ("wir leben in", "und nicht in Europa"),
        ("kein Wort über", "in dieser Debatte"),
        ("viele Menschen in", "sehen das anders"),
        ("Österreich und", "haben das Abkommen unterzeichnet"),
        ("die Lage in", "bleibt angespannt"),
    ]
    for index in range(n):
        left, right = contexts[index % len(contexts)]
        rows.append(
            {"left": f"{left} ({index})", "kw": "Deutschland", "right": right}
        )
    return rows


def _kwic_evidence(n: int = 20) -> list:
    return [
        _ev(
            "run_cqlf_query",
            '{"query": "Deutschland", "limit": 50}',
            {
                "query": "Deutschland",
                "total": 105,
                "rows_seen": n,
                "rows": _kwic_rows(n),
            },
        )
    ]


_KWIC_FRAGE = (
    "Welche Funktionen übernimmt ‚Deutschland‘ in den Äußerungen? Leite "
    "eine kleine Gebrauchstypologie ab und suche einen Gegenbeleg."
)


class TestKwicDeathLanding(unittest.TestCase):
    def test_backstop_lands_usage_report_not_two_fragment_digest(self):
        landing = build_death_landing(
            _kwic_evidence(20),
            recipe_id="gebrauch_kwic",
            question_scope=_KWIC_FRAGE,
        )
        self.assertIsNotNone(landing)
        assert landing is not None
        # Kein generischer Digest, kein Presence-Rahmen.
        self.assertNotIn("Analysebericht (sichtbare Evidenz)", landing)
        self.assertFalse(landing.startswith("Ja."))
        # >= 4 woertliche Belege.
        self.assertGreaterEqual(landing.count("- „"), 4)
        # Einordnung auf Basis ALLER sichtbaren Zeilen.
        self.assertTrue(_ordnet_alle_zeilen_ein(landing, 20), landing)
        self.assertIn("von 20 Zeilen", landing)
        # Gegenbeleg-Hinweis und korrekte Kopfzahlen mit Term-Provenienz.
        self.assertIn("Gegenbeleg", landing)
        self.assertIn("`Deutschland`", landing)
        # Die EIGENSCHAFT, nicht der Variablenname: die exakte
        # Korpus-Gesamtzahl steht da, UND sie ist von der Zahl der
        # ausgewerteten Zeilen unterscheidbar. Genau diese Verwechslung
        # (105 Treffer gegen 20 Zeilen) ist der fachliche Fehler, den der
        # Satz verhindern soll.
        self.assertIn("105", landing)
        self.assertRegex(landing, r"105 Mal vor")
        self.assertRegex(landing, r"20 Belegzeilen")

    def test_typologie_counts_cover_all_visible_rows(self):
        import re as _re

        landing = build_death_landing(
            _kwic_evidence(20),
            recipe_id="gebrauch_kwic",
            question_scope=_KWIC_FRAGE,
        )
        assert landing is not None
        counts = [
            int(match)
            for match in _re.findall(r"(\d+) von 20 Zeilen", landing)
        ]
        self.assertEqual(sum(counts), 20)

    def test_foreign_query_values_are_not_married_to_question_term(self):
        # Die einzige KWIC-Evidenz gehoert zu einer ANDEREN Query: der
        # Frage-Term darf nicht mit deren total verheiratet werden. Der
        # Report laeuft dann unter dem Term der Evidenz selbst.
        evidence = [
            _ev(
                "run_cqlf_query",
                '{"query": "Europa"}',
                {
                    "query": "Europa",
                    "total": 7,
                    "rows": [
                        {"left": "wir in", "kw": "Europa", "right": "leben"}
                    ],
                },
            )
        ]
        landing = build_death_landing(
            evidence,
            recipe_id="gebrauch_kwic",
            question_scope=_KWIC_FRAGE,
        )
        assert landing is not None
        self.assertNotIn("`Deutschland`", landing)
        self.assertIn("`Europa`", landing)

    def test_reason_is_exactly_one_appended_sentence(self):
        landing = build_death_landing(
            _kwic_evidence(6),
            recipe_id="gebrauch_kwic",
            question_scope=_KWIC_FRAGE,
            reason="Ein Engine-Fehler hat den Turn vorzeitig beendet.",
        )
        assert landing is not None
        self.assertEqual(landing.count("Ein Engine-Fehler hat den Turn"), 1)
        self.assertTrue(
            landing.rstrip().endswith(
                "Hinweis: Ein Engine-Fehler hat den Turn vorzeitig beendet."
            )
        )


class TestFrequencyDeathLanding(unittest.TestCase):
    def _frequency_evidence(self) -> list:
        return [
            _ev(
                "query_count",
                '{"query": "der"}',
                {
                    "query": "der",
                    "total": 917,
                    "per_million": 16319.3,
                    "denominator_scope": "corpus",
                    "denominator_tokens": 56191,
                },
            ),
            _ev(
                "query_count",
                '{"query": "Frau"}',
                {
                    "query": "Frau",
                    "total": 123,
                    "per_million": 2189.3,
                    "denominator_scope": "corpus",
                    "denominator_tokens": 56191,
                },
            ),
        ]

    def test_backstop_answers_with_number_pmw_of_right_term(self):
        landing = build_death_landing(
            self._frequency_evidence(),
            recipe_id="frequenz",
            question_scope="Wie häufig ist ‚Frau‘ in diesem Korpus?",
        )
        self.assertIsNotNone(landing)
        assert landing is not None
        self.assertIn("`Frau`", landing)
        self.assertIn("123", landing)
        self.assertIn("2189.3", landing)
        # Zaehlweise: Scope und Nenner werden benannt.
        self.assertIn("Korpus", landing)
        self.assertIn("56191", landing)
        # Der Wert der FREMDEN Query taucht nicht auf.
        self.assertNotIn("917", landing)
        self.assertNotIn("`der`", landing)

    def test_no_matching_term_evidence_means_no_landing(self):
        foreign_only = [
            item
            for item in self._frequency_evidence()
            if item.raw_surface.get("query") == "der"
        ]
        landing = build_death_landing(
            foreign_only,
            recipe_id="frequenz",
            question_scope="Wie häufig ist ‚Frau‘ in diesem Korpus?",
        )
        self.assertIsNone(landing)


class TestOtherRecipeLandings(unittest.TestCase):
    def test_metadata_recipe_lands_inventory(self):
        evidence = [
            _ev(
                "metadata_values",
                '{"fields": ["*"]}',
                {
                    "available_fields": ["register", "source", "jahr"],
                    "value_counts": {"register": 4, "source": 6, "jahr": 12},
                },
            )
        ]
        landing = build_death_landing(
            evidence,
            recipe_id="metadaten_struktur",
            question_scope="Welche Metadaten-Variablen hat das Korpus?",
        )
        self.assertIsNotNone(landing)
        assert landing is not None
        self.assertIn("register", landing)
        self.assertNotIn("Analysebericht (sichtbare Evidenz)", landing)

    def test_profil_recipe_lands_sketch_report(self):
        evidence = [
            _ev(
                "word_sketch",
                '{"term": "gehen"}',
                {
                    "term": "gehen",
                    "tables": {
                        "obj": [
                            {"word": "Schule", "score": 5.1, "f": 12},
                            {"word": "Arbeit", "score": 4.2, "f": 8},
                        ]
                    },
                    "relations": {
                        "obj": {"label": "Objekt von", "basis": "f"}
                    },
                },
            )
        ]
        landing = build_death_landing(
            evidence,
            recipe_id="profil",
            question_scope="Mit welchen Konstruktionen verbindet sich ‚gehen‘?",
        )
        self.assertIsNotNone(landing)
        assert landing is not None
        self.assertIn("Schule", landing)

    def test_unknown_recipe_returns_none_generic_digest_stays_last_resort(self):
        landing = build_death_landing(
            _kwic_evidence(3),
            recipe_id="exploration_meta",
            question_scope="Erkunde das Korpus frei.",
        )
        self.assertIsNone(landing)


class _OrchStub:
    """Turn-Zustand wie ihn der Server-Backstop vorfindet (Realfall (a)):

    Rezept gebrauch_kwic, ein NICHT passender Kontrakt (open_research),
    reichlich sichtbare KWIC-Evidenz. Die echten Orchestrator-Methoden
    laufen ungebunden auf diesem Zustand.
    """

    build_death_landing_markdown = ReActOrchestrator.build_death_landing_markdown
    build_salvage_markdown = ReActOrchestrator.build_salvage_markdown

    def __init__(self, evidence=None, recipe_id="gebrauch_kwic"):
        self._turn_evidence_items = [
            item.to_dict() for item in (evidence or _kwic_evidence(20))
        ]
        self._active_recipe_id = recipe_id
        self._active_analysis_contract = {
            "mode": "tool_analysis",
            "analysis_family": "open_research",
            "deliverable_kind": "overview",
            "question_scope": _KWIC_FRAGE,
        }
        self._evidence_gaps = []
        self._recent_tool_results = []


class TestServerBackstopHierarchy(unittest.TestCase):
    def test_salvage_markdown_prefers_recipe_landing_over_contract_digest(self):
        # Der Realfall (a): Kontrakt sagt open_research, Rezept sagt
        # gebrauch_kwic. Vorher: Zwei-Fragmente-Digest. Jetzt: Report.
        out = _OrchStub().build_salvage_markdown()
        self.assertIsNotNone(out)
        assert out is not None
        self.assertNotIn("Analysebericht (sichtbare Evidenz)", out)
        self.assertTrue(_ordnet_alle_zeilen_ein(out), out)
        self.assertGreaterEqual(out.count("- „"), 4)
        # Die ehrliche Salvage-Notiz bleibt erhalten.
        self.assertIn("vor der vollstaendigen Verifikation beendet", out)

    def test_server_backstop_uses_hierarchy(self):
        out = _server._copilot_timeout_salvage_text(
            "", None, _OrchStub(), timed_out=True, annotate=False
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(_ordnet_alle_zeilen_ein(out), out)
        self.assertNotIn("Analysebericht (sichtbare Evidenz)", out)

    def test_short_fragment_is_replaced_by_recipe_landing(self):
        out = _server._copilot_timeout_salvage_text(
            "Zwei kurze Fragmente ohne Substanz.",
            None,
            _OrchStub(),
            timed_out=True,
            annotate=False,
        )
        assert out is not None
        self.assertTrue(_ordnet_alle_zeilen_ein(out), out)
        self.assertNotIn("Zwei kurze Fragmente", out)

    def test_substantial_partial_text_is_kept(self):
        partial = (
            "Der sichtbare Suchlauf zu Deutschland zeigt ein breites "
            "Gebrauchsspektrum. Die Belege verteilen sich auf politische "
            "und geografische Kontexte, wobei die politischen Kontexte "
            "ueberwiegen. Die zitierten Kontexte stammen aus dem "
            "sichtbaren Ausschnitt der Trefferzeilen und beschreiben "
            "keine korpusweite Verteilung. Eine vollstaendige "
            "Gebrauchsanalyse stand noch aus."
        )
        out = _server._copilot_timeout_salvage_text(
            partial, None, _OrchStub(), timed_out=True, annotate=False
        )
        assert out is not None
        self.assertIn("Gebrauchsspektrum", out)
        self.assertFalse(_ordnet_alle_zeilen_ein(out), out)

    def test_engine_error_appends_exactly_one_reason_sentence(self):
        out = _server._copilot_timeout_salvage_text(
            "",
            None,
            _OrchStub(),
            timed_out=False,
            annotate=False,
            engine_error=True,
        )
        assert out is not None
        self.assertEqual(out.count("Engine-Fehler"), 1)
        self.assertTrue(_ordnet_alle_zeilen_ein(out), out)


class TestEngineErrorTerminalContract(unittest.TestCase):
    def test_engine_death_with_evidence_is_honest_partial(self):
        events = _copilot_terminal_events(
            session_id="s1",
            reply=None,
            salvage_text="Report aus gesicherter Evidenz.",
            timed_out=False,
            error_text="LLMRequestError: Engine-Ausfall",
            usage_report={"recipe_id": "gebrauch_kwic"},
        )
        done = [p for n, p in events if n == "copilot.done"][0]
        self.assertNotEqual(done["status"], "completed")
        self.assertTrue(done["partial"])
        self.assertIn("Engine-Ausfall", done["error"])
        self.assertEqual(done["text"], "Report aus gesicherter Evidenz.")
        grounding = [p for n, p in events if n == "copilot.grounding"][0]
        self.assertEqual(
            grounding["grounding"]["verdict"], "partial_on_engine_error"
        )

    def test_time_backstop_with_evidence_stays_clean_completed(self):
        # Anerkannter Fortschritt (r3): Zeit-Backstop mit Evidenz bleibt
        # completed_on_collected_evidence. Keine Regression.
        events = _copilot_terminal_events(
            session_id="s1",
            reply=None,
            salvage_text="Report.",
            timed_out=True,
            error_text="Copilot-Zeitlimit (135s) überschritten",
            usage_report={},
        )
        done = [p for n, p in events if n == "copilot.done"][0]
        self.assertEqual(done["status"], "completed")
        self.assertNotIn("partial", done)
        grounding = [p for n, p in events if n == "copilot.grounding"][0]
        self.assertEqual(
            grounding["grounding"]["verdict"],
            "completed_on_collected_evidence",
        )


class TestTurnStateAdapter(unittest.TestCase):
    def test_works_without_contract(self):
        # Engine-Tod VOR der Kontrakt-Phase: dank Vorplanung liegt Evidenz
        # vor, die Landung braucht keinen Kontrakt.
        landing = death_landing_from_turn_state(
            [item.to_dict() for item in _kwic_evidence(5)],
            recipe_id="gebrauch_kwic",
            contract={},
            question=_KWIC_FRAGE,
        )
        self.assertIsNotNone(landing)
        assert landing is not None
        self.assertTrue(_ordnet_alle_zeilen_ein(landing), landing)

    def test_empty_evidence_returns_none(self):
        self.assertIsNone(
            death_landing_from_turn_state([], recipe_id="gebrauch_kwic")
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
