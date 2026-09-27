"""Probe: die Nachbereitung nimmt Zwischenstaende je Stufe auf, wenn das
Umgebungsverzeichnis CANDYCONC_ZWISCHENSTAENDE_DIR gesetzt ist.

Gehoert zum Befund „die Nachbereitung entfernt die Deutung" (evaluation/
befunde/): ohne die Aufzeichnung der Zwischenstaende kann nicht benannt
werden, WELCHER Schritt 56 Prozent der deutenden Saetze entfernt.

Ohne die Nahtstellen-Einziehung in _ra_finish_turn ist die erste Probe ROT:
es entsteht keine Datei 4_poliert.txt unter der Sitzung.

Der Orchestrator wird ueber den _real_copilot-Loader geladen (der Stub-
Install in tests/conftest.py umgehend, siehe dessen Docstring), damit die
Probe den ECHTEN Code und die ECHTE _zwischenstand-Nahtstelle trifft.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.ai import _real_copilot

_zwischenstand = _real_copilot.orchestrator._zwischenstand
ReActOrchestrator = _real_copilot.orchestrator.ReActOrchestrator


class TestZwischenstaendeAufzeichnung(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.verzeichnis = Path(self._tmp.name) / "zwischenstaende"
        self._alte = os.environ.get("CANDYCONC_ZWISCHENSTAENDE_DIR")
        os.environ["CANDYCONC_ZWISCHENSTAENDE_DIR"] = str(self.verzeichnis)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._alte is None:
            os.environ.pop("CANDYCONC_ZWISCHENSTAENDE_DIR", None)
        else:
            os.environ["CANDYCONC_ZWISCHENSTAENDE_DIR"] = self._alte

    async def test_polierte_stufe_wird_aufgezeichnet(self):
        async def _call_llm(messages, exposed_tools, **kwargs):
            raise AssertionError("kein LLM-Call erwartet")

        async def _dispatch(tool_call, _token=None):
            raise AssertionError("kein Tool-Call erwartet")

        orch = ReActOrchestrator([], _call_llm, _dispatch)
        orch._emit_output = lambda bus, event: None
        polished = orch._ra_finish_turn(
            object(), "Wie viele Dokumente?",
            "Ein Text mit Deutung.", stream_emit=False,
        )
        self.assertEqual(polished, "Ein Text mit Deutung.")
        sitzung = orch.session.session_id
        datei = self.verzeichnis / sitzung / "4_poliert.txt"
        self.assertTrue(
            datei.exists(),
            "Der polierte Zwischenstand wurde nicht aufgezeichnet.",
        )
        self.assertIn("Deutung", datei.read_text(encoding="utf-8"))

    async def test_ohne_verzeichnis_wird_nichts_geschrieben(self):
        os.environ.pop("CANDYCONC_ZWISCHENSTAENDE_DIR", None)
        mit_temp = tempfile.TemporaryDirectory()
        self.addCleanup(mit_temp.cleanup)
        _zwischenstand("4_poliert", "irgendwas", sitzung="probe")
        self.assertFalse(
            (Path(mit_temp.name) / "probe").exists(),
            "Ohne Verzeichnis darf nichts landen.",
        )


    def test_claim_verdikt_als_zwischenstand(self):
        """Der gegroundete Pfad zeichnet Entwurf, Verdikt und Rebuild auf
        (F-65: die 56-Prozent-Stelle ist der Claim-Rebuild, nicht der
        freie Referenzpfad)."""
        os.environ["CANDYCONC_ZWISCHENSTAENDE_DIR"] = str(self.verzeichnis)
        from tests.ai import _real_copilot
        z = _real_copilot.orchestrator._zwischenstand
        z("3b_verdikt", json.dumps({"accepted": 3, "rejected": 1}),
          sitzung="probe_claims")
        datei = self.verzeichnis / "probe_claims" / "3b_verdikt.txt"
        self.assertTrue(datei.exists())
        geladen = json.loads(datei.read_text(encoding="utf-8"))
        self.assertEqual(geladen["accepted"], 3)


if __name__ == "__main__":
    unittest.main()
