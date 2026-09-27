"""Zwei gleiche Runden beweisen, dass eine dritte nichts beitraegt.

Live mitgeschnitten am 2026-08-28, eine Assoziationsfrage auf dem
56k-Testindex: sieben ``answer_envelope``-Aufrufe zu je rund 360
Sekunden, sieben ``grounding_verdict``-Aufrufe, insgesamt 65,3 Minuten.
Vier der sieben Verdicts waren BYTE-IDENTISCH. Das Modell sagte jedes Mal
„pass" und wies nichts zurueck. Ausgeliefert wurde am Ende eine Absage von
234 Zeichen.

Eine Schleife, die denselben Zustand viermal sieht und weitermacht, kann
nicht konvergieren.

DAS SIGNAL IST DIE HUELLE, NICHT DER GRUND. Eine erste Fassung dieser
Bremse verglich nur die Beanstandungen zweier Runden und schnitt damit
``test_third_repair_attempt_can_complete_a_required_deliverable`` ab: dort
beanstanden zwei Runden dasselbe, die dritte repariert es aber wirklich.
Gleiche Beanstandung heisst nicht gleiche Eingabe, denn die
Reparaturziele wandern mit. Erst wenn die neu synthetisierte Huelle
WORTGLEICH die vorige ist, steht fest, dass die naechste Runde dieselbe
Eingabe bekommt.

UND SIE GEHOERT ZUM TEMPERATUR-PIN. Die beiden Schleifenaufrufe
(``synthesise_envelope``, ``verify_envelope``) pinnten ``temperature``
nicht, acht andere Struktur-Schritte taten es. Ohne Pin ist eine
Wiederholung eine unabhaengige Ziehung, und Gleichheit zweier Runden sagt
nichts ueber die dritte. Ohne Bremse bliebe umgekehrt ein festgefahrener
Envelope festgefahren. Nie einzeln.
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

_QUELLE = (
    _SRC / "candyconc" / "candyconc_copilot" / "grounding_verifier.py"
).read_text(encoding="utf-8")


class BeideSchleifenaufrufeSindGepinnt(unittest.TestCase):
    """Sonst ist die Bremse nicht scharf."""

    RUF = "await self._run_structured_step("

    def test_jede_aufrufstelle_pinnt_die_temperatur(self):
        """Die Invariante direkt, nicht ueber Anker geraten.

        Zwei der Aufrufstellen pinnten nicht: die Synthese und das
        Verdikt, also genau die beiden, die die Schleife dreht.
        """
        stellen = [
            i for i in range(len(_QUELLE))
            if _QUELLE.startswith(self.RUF, i)
        ]
        self.assertGreaterEqual(len(stellen), 10, "Aufrufstellen nicht gefunden")
        for nr, start in enumerate(stellen, 1):
            ende = _QUELLE.find(self.RUF, start + 1)
            rumpf = _QUELLE[start:ende if ende > 0 else start + 4000]
            with self.subTest(aufruf=nr, zeile=_QUELLE[:start].count(chr(10)) + 1):
                self.assertIn("temperature=0.0", rumpf)

    def test_alle_struktur_schritte_pinnen(self):
        # Zehn Aufrufstellen, zehn Pins. Sieben plus die beiden der
        # Schleife plus die Wiederherstellung.
        self.assertGreaterEqual(_QUELLE.count("temperature=0.0"), 10)


class DieBremseGreiftNurBeiGleicherHuelle(unittest.TestCase):
    def test_die_bedingung_vergleicht_die_huelle(self):
        # Die Beanstandung allein genuegt NICHT, siehe Modul-Docstring.
        start = _QUELLE.find("STAGNATION")
        self.assertGreater(start, 0)
        block = _QUELLE[_QUELLE.find("if len(tor_verlauf) >= 2:"):][:600]
        self.assertIn('a.get("huelle")', block)
        self.assertIn('a.get("huelle") == b.get("huelle")', block)

    def test_die_huellensignatur_meidet_die_fakt_nummern(self):
        # _claim_signature traegt fact_ids, und die werden je Runde neu
        # nummeriert. Dieselbe Aussage haette dann zwei Signaturen.
        block = _QUELLE[_QUELLE.find("def _envelope_signatur("):][:900]
        self.assertIn('getattr(c, "text", "")', block)
        # Der Rumpf darf _claim_signature nicht benutzen (die traegt
        # fact_ids). Der Docstring NENNT sie, deshalb nur der Code.
        rumpf = block[block.find('"""', block.find('"""') + 3):]
        self.assertNotIn("_claim_signature", rumpf)
        self.assertNotIn("fact_ids", rumpf)


class DerAbbruchNenntSeinenGrund(unittest.TestCase):
    def test_stagnation_ist_nicht_budget_erschoepfung(self):
        """Beides zu vermischen waere eine Falschaussage ueber den Abbruch."""
        from candyconc.candyconc_copilot.grounding_verifier import (
            GroundingVerifier,
        )

        self.assertNotEqual(
            GroundingVerifier.STAGNATION_REASON,
            GroundingVerifier.RETRY_EXHAUSTED_REASON,
        )
        self.assertIn("Neusynthese", GroundingVerifier.STAGNATION_REASON)

    def test_der_erschoepfungsgrund_bleibt_der_stagnation_erspart(self):
        block = _QUELLE[_QUELLE.find("if self.should_retry(verdict):"):][:700]
        self.assertIn("not stagniert", block)


class DerTorVerlaufWirdAufgezeichnet(unittest.TestCase):
    """Ohne ihn ist jede Messung an der Schleife blind."""

    def test_jede_runde_wird_festgehalten(self):
        self.assertIn("_runde_festhalten(1, verdict, envelope)", _QUELLE)
        self.assertIn(
            "_runde_festhalten(attempts + 1, verdict, envelope)", _QUELLE
        )

    def test_der_verlauf_traegt_grund_und_anomalien(self):
        block = _QUELLE[_QUELLE.find("def _runde_festhalten("):][:1200]
        for feld in ('"gruende"', '"anomalien"', '"angenommen"', '"verworfen"'):
            self.assertIn(feld, block)

    def test_er_erreicht_die_aufzeichnung(self):
        # to_dict ist asdict(self) und sieht keine Unterstrich-Attribute.
        from candyconc.candyconc_copilot.grounding_schemas import (
            GroundingVerdict,
        )

        v = GroundingVerdict(verdict="retry", needs_retry=True)
        v._claim_reasons = {"c01": {"Zahl ohne Deckung"}}
        v._tor_verlauf = [{"runde": 1, "gruende": ["followup_breadth"]}]
        v._omitted_claim_ids = {"c02", "c01"}
        d = v.to_dict()
        self.assertEqual(d["claim_reasons"], {"c01": ["Zahl ohne Deckung"]})
        self.assertEqual(d["tor_verlauf"][0]["runde"], 1)
        # Mengen sortiert, damit zwei Laeufe vergleichbar bleiben.
        self.assertEqual(d["omitted_claim_ids"], ["c01", "c02"])

    def test_die_aufzeichnung_bleibt_json_faehig(self):
        import json

        from candyconc.candyconc_copilot.grounding_schemas import (
            GroundingVerdict,
        )

        v = GroundingVerdict()
        v._claim_reasons = {"c01": {"a", "b"}}
        v._omitted_claim_ids = {"c01"}
        v._tor_verlauf = [{"runde": 1, "huelle": ["Ein Satz."]}]
        json.dumps(v.to_dict())


if __name__ == "__main__":
    unittest.main()
