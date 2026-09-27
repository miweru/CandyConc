"""Manipulationssicherheit der Lineage-Kette.

Diese Datei stand mit ``pytest.skip("legacy import",
allow_module_level=True)`` still, lief also NIE -- und die Begruendung war
falsch: alle vier Importe der Vorfassung (Project, ReActOrchestrator,
dispatch, get_tools) tragen heute. Was wirklich fehlschlug, war der Aufbau.
``NamedTemporaryFile`` legt eine LEERE Datei an, und ``Project`` weist sie
seit einer Formataenderung mit "Projektdatei unlesbar" ab
(project.py:_load, in tests/core/test_replay.py ausdruecklich vermerkt).

Der Orchestrator-Teil der Vorfassung ist hier NICHT wiederbelebt: unter
pytest legt ``tests/conftest.py`` ein Stub-Modul fuer ``candyconc_copilot``
in ``sys.modules``, ``ReActOrchestrator`` waere dort eine Attrappe, und der
Test pruefte den Produktivpfad nicht. Dass der Orchestrator seine Ausgabe
ins Lineage-Log schreibt, misst
``tests/backend/test_gate_followup_fixes.py::TestI`` am laufenden Turn.

Was hier bleibt, ist der Vertrag, den sonst NICHTS abdeckt: ein Eintrag mit
nachtraeglich veraenderter sha256 stoppt das Abspielen.
``tests/core/test_replay.py`` prueft, DASS abgespielt wird, nicht dass
Manipulation auffaellt.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from candyconc.project import Project


class TestLineageKette(unittest.TestCase):
    def setUp(self):
        self.verzeichnis = tempfile.mkdtemp()
        self.pfad = Path(self.verzeichnis) / "proj.ccproj"

    def tearDown(self):
        shutil.rmtree(self.verzeichnis, ignore_errors=True)

    def test_eine_unveraenderte_kette_spielt_ab(self):
        """Die positive Klasse. Ohne sie pruefte der Test unten nur, dass
        irgendetwas wirft."""
        p = Project(self.pfad)
        for i in range(3):
            p.log_op(json.dumps({"task": "run_query", "term": "und", "ctx": i}))
        self.assertEqual(len(p.timeline()), 3)
        p.replay()

    def test_eine_veraenderte_sha256_stoppt_das_abspielen(self):
        p = Project(self.pfad)
        p.log_op(json.dumps({"task": "run_query", "term": "und", "ctx": 1}))
        echt = json.loads(p.timeline()[-1])

        gefaelscht = dict(echt)
        gefaelscht["sha256"] = "0" * 64
        p.log_op(json.dumps(gefaelscht))

        with self.assertRaises(ValueError) as ctx:
            p.replay()
        self.assertIn("hash", str(ctx.exception).lower())

    def test_der_eintrag_selbst_bleibt_lesbar(self):
        """Gegenprobe: die Kette weist nur die Manipulation ab, nicht den
        gewoehnlichen Eintrag."""
        p = Project(self.pfad)
        p.log_op(json.dumps({"task": "run_query", "term": "und", "ctx": 1}))
        eintrag = json.loads(p.timeline()[-1])
        self.assertEqual(eintrag["task"], "run_query")
        self.assertEqual(eintrag["term"], "und")


if __name__ == "__main__":
    unittest.main()
