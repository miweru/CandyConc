"""Probe: usage_felder bleibt typstabil mit und ohne Verdichtung.

Der erste Aufrufzahler-Commit (05a4c7e) verdraengte die int-Variable
``aufrufe`` aus verdichtungs_bilanz durch das Stufen-Dict. Ein Turn mit
Verdichtung warf dann ``TypeError: int + dict`` und der ganze Lauf
fiel auf FEHLER. Ohne den Fix ist diese Probe ROT.
"""
import unittest
from types import SimpleNamespace

from tests.ai._real_copilot import _MODULES as _ECHTE_MODULE

_sv = _ECHTE_MODULE["candyconc_copilot.session_compaction"]
usage_felder = _sv.usage_felder
STUFE = _sv.STUFE_VERDICHTUNG


class TestUsageFelderTypstabil(unittest.TestCase):
    def test_mit_verdichtung_und_stufenzahl(self):
        ts = SimpleNamespace(
            llm_seconds=1.5,
            llm_seconds_je_stufe={"Werkzeuge": 1.5},
            llm_calls_used=2,
            llm_calls_je_stufe={"Werkzeuge": 2},
        )
        session = SimpleNamespace()
        felder = usage_felder(ts, session)
        self.assertIsInstance(felder["llm_calls_used"], int)
        self.assertEqual(felder["llm_calls_je_stufe"], {"Werkzeuge": 2})


    def test_buchung_auf_geslottetem_turn_state(self):
        """Der echte _RunTurnState traegt __slots__: das Feld muss dort
        deklariert sein, sonst wirft jede Buchung AttributeError. Genau
        dieser Fehler fiel Arm-5 bei Frage 1 nach 85 Sekunden."""
        orch = _ECHTE_MODULE["candyconc_copilot.orchestrator"]
        buchen = _sv.modellzeit_buchen
        ts = orch._RunTurnState()
        # Slots-Konfig minimal bestuecken, soweit __init__ es verlangt
        buchen(ts, "Werkzeuge", 0.5)
        buchen(ts, "Werkzeuge", 0.25)
        self.assertEqual(ts.llm_calls_je_stufe, {"Werkzeuge": 2})


if __name__ == "__main__":
    unittest.main()
