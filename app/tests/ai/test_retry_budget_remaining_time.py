"""P3.3: Das Verifier-Retry-Budget folgt der Restzeit, nicht einer Konstante.

Bis hierher stand es auf 6, bei Bestaetigungsdruck bis 8, unabhaengig
davon, ob noch 90 Sekunden uebrig waren oder 9. Jeder Retry kostet ZWEI
Roundtrips.

Gemessen am 2026-08-17: die Finalisierung wird im Median nach 16,0
Sekunden erreicht, das Verifier-Tor schliesst bei 84,0 Sekunden (max_time
120 mal 1 minus VERIFIER_MIN_TIME_FRACTION 0,3). Es bleiben rund 68
Sekunden, und ein Paar aus Synthese und Verifikation kostet rund 22.
Damit passen zwei bis drei Paare, nie sechs.

Das Budget war also KONSTRUKTIV UNERREICHBAR. Die Restrunden endeten nicht
als geplante Landung, sondern als Abbruch mitten im Protokoll, und genau
auf dieser Skip-Landung sind die drei erfundenen Zitate der Kampagne
entstanden.

Die Rechnung kann das Budget nur SENKEN, nie heben. Sonst waere sie keine
Anpassung an die Wirklichkeit, sondern eine Fahigkeitsaenderung.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import budgets  # noqa: E402

MAX_TIME = 120.0


def _budget(verbraucht: float, *, guarded: bool = False, kandidaten: int = 0) -> int:
    """Budget bei ``verbraucht`` Sekunden Verbrauch, ohne Wanduhr-Abhaengigkeit."""
    return budgets.retry_budget_fuer_restzeit(
        started_at=0.0,
        max_time=MAX_TIME,
        confirmation_guarded=guarded,
        retrieval_candidate_count=kandidaten,
        now=verbraucht,
    )


class DasBudgetFolgtDerRestzeit(unittest.TestCase):
    def test_frueher_eintritt_erlaubt_mehr(self):
        """Bei 16,0 s Verbrauch, dem gemessenen Median."""
        # 120 * 0,7 = 84 bis zum Tor, minus 16 sind 68, geteilt durch 22
        # sind drei volle Paare.
        self.assertEqual(_budget(16.0), 3)

    def test_spaeter_eintritt_erlaubt_weniger(self):
        self.assertEqual(_budget(50.0), 1)
        self.assertEqual(_budget(70.0), 0 + 1)

    def test_am_tor_bleibt_ein_versuch(self):
        """Wer den Verifier startet, bekommt einen Versuch."""
        self.assertEqual(_budget(84.0), 1)
        self.assertEqual(_budget(200.0), 1)

    def test_nie_groesser_als_die_alte_konstante(self):
        """Die Rechnung darf nur senken, sonst waere sie eine Aufweitung."""
        for verbraucht in range(0, 120, 3):
            self.assertLessEqual(_budget(float(verbraucht)), 6)

    def test_bestaetigungsdruck_hebt_die_obergrenze_nicht_ueber_acht(self):
        for kandidaten in (0, 4, 6, 20):
            self.assertLessEqual(
                _budget(0.0, guarded=True, kandidaten=kandidaten), 8
            )

    def test_ohne_zeitbudget_gilt_die_alte_obergrenze(self):
        """Kein max_time heisst keine Schranke, an der man rechnen koennte."""
        self.assertEqual(
            budgets.retry_budget_fuer_restzeit(
                0.0, None, confirmation_guarded=False, retrieval_candidate_count=0
            ),
            6,
        )
        self.assertEqual(
            budgets.retry_budget_fuer_restzeit(
                0.0, None, confirmation_guarded=True, retrieval_candidate_count=6
            ),
            8,
        )

    def test_monoton_fallend(self):
        """Mehr Verbrauch darf nie mehr Budget ergeben."""
        werte = [_budget(float(v)) for v in range(0, 100, 2)]
        self.assertEqual(werte, sorted(werte, reverse=True))


class DerOrchestratorBenutztDieRechnung(unittest.TestCase):
    """Verdrahtung, nicht nur Logik. Die Lehre der Zitatwache."""

    def test_die_konstante_steht_nicht_mehr_im_orchestrator(self):
        quelle = (
            _SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        self.assertIn("retry_budget_fuer_restzeit", quelle)
        self.assertNotIn("min(8, max(6, retrieval_candidate_count + 2))", quelle)

    def test_die_restzeit_wird_wirklich_uebergeben(self):
        quelle = (
            _SRC / "candyconc" / "candyconc_copilot" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        start = quelle.index("retry_budget_fuer_restzeit")
        aufruf = quelle[start:start + 260]
        self.assertIn("turn_state.started_at", aufruf)
        self.assertIn("turn_state.max_time", aufruf)


if __name__ == "__main__":
    unittest.main()
