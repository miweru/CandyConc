"""H11.8: Die Salvage-Landung umging die Zitatwache.

Gefunden von einem unabhaengigen Pruefagenten, nachgeprueft am Code.
``routes/copilot.py`` trug ueber der Politur den Kommentar

    auch die Server-Salvage-Landung laeuft durch den finalen
    Politur-Chokepoint

und rief darunter ``final_answer_polish`` allein -- also die Textpolitur
ohne ``strike_unsupported_quotes``. Der Kommentar behauptete den vollen
Chokepoint, der Code lieferte die Haelfte.

Das ist derselbe Fehlertyp, der die drei erfundenen Zitate der Kampagne
vom 2026-08-16 ausgeliefert hat, und er sass ausgerechnet in dem Zweig,
der nur unter Zeitdruck ausloest: Wanduhr-Backstop und Engine-Ausfall.
Genau dort, wo der LLM-Verifier ohnehin schon uebersprungen ist.

Die Zitatwache hat vier Anlaeufe gebraucht, und JEDER Fehlschlag war nur
im Livelauf sichtbar, waehrend die Unittests gruen standen. Der Grund war
jedes Mal die Verdrahtung, nie die Logik. Dieser Test prueft deshalb
beides: dass die Kette das Fabrikat faellt (Verhalten) und dass der Zweig
die volle Wache benennt (Verdrahtung).
"""

from __future__ import annotations

import re
import sys
import unittest
import unittest.mock
from pathlib import Path

_APP = Path(__file__).resolve().parents[2]
_SRC = _APP / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.candyconc_copilot import recipe_runtime as rr  # noqa: E402

#: Woertlich aus drei unabhaengigen Laeufen derselben Frage, im Korpus nie.
FABRIKAT = (
    "der jungen Männer sind keine Flüchtlinge. Sie sind rücksichtslose "
    "Invasoren."
)

#: Eine echte KWIC-Zeile, wie der Turn-Evidenzeintrag sie als DICT traegt.
#: `tool` gehoert dazu: orchestrator.py:6997 legt `evidence_item.to_dict()`
#: ab, und das Feld ist dort immer gesetzt. Die Wache entscheidet nach
#: HERKUNFT, weil die Form einer Zeile allein nicht reicht --
#: semantic_cluster_words spiegelt Modelltext in einen Inhaltsschluessel.
ECHTE_EVIDENZ = {
    "tool": "run_cqlf_query",
    "grounding_surface": [],
    "payload_preview": "",
    "raw_surface": {},
    "fact_surface": {
        "rows": [
            {
                "left": "# JuFo # Israel #",
                "kw": "Deutschland",
                "right": "ist ein Land",
                "pos": 416,
            }
        ]
    },
}


class SalvageKetteFaelltDasFabrikat(unittest.TestCase):
    """Verhalten: was die Route nach der Reparatur mit dem Teiltext tut."""

    def _salvage_politur(self, text: str, evidenz):
        return rr.politur_mit_zitatwache(text, list(evidenz))

    def test_fabrikat_ueberlebt_die_salvage_landung_nicht(self):
        text, entfernt = self._salvage_politur(
            f'Ein Nutzer schreibt: „{FABRIKAT}"\n\nDeutung: klare Ablehnung.',
            [ECHTE_EVIDENZ],
        )
        self.assertNotIn("Invasoren", text)
        self.assertTrue(entfernt)

    def test_echtes_kwic_zitat_ueberlebt_die_salvage_landung(self):
        """Eine Wache, die echte Belege streicht, ist so schaedlich wie keine."""
        text, _ = self._salvage_politur(
            'Beleg: „Israel # Deutschland ist ein Land"\n\nDeutung: Kontext.',
            [ECHTE_EVIDENZ],
        )
        self.assertIn("Deutschland ist ein Land", text)

    def test_ohne_evidenz_faellt_jedes_zitat(self):
        """Engine-Ausfall vor dem ersten Werkzeug: kein Beleg, kein Zitat."""
        text, entfernt = self._salvage_politur(
            f'Ein Nutzer schreibt: „{FABRIKAT}"', []
        )
        self.assertNotIn("Invasoren", text)
        self.assertTrue(entfernt)

    def test_annotationen_bleiben_serialisierbar(self):
        """Die Route haengt sie an ein copilot.grounding-Event.

        ``final_answer_polish`` liefert Dicts, die Zitatwache haengt einen
        String an. Die Liste ist damit gemischt -- das ist seit H11.7 auch
        am Orchestrator-Chokepoint so und muss JSON-fest bleiben, sonst
        stirbt die Landung an der Serialisierung statt am Fabrikat.
        """
        import json

        _text, annotationen = self._salvage_politur(
            f'Ein Nutzer schreibt: „{FABRIKAT}"', [ECHTE_EVIDENZ]
        )
        json.dumps(list(annotationen))


class DerZweigBenenntDieVolleWache(unittest.TestCase):
    """Verdrahtung: der Teil, den vier Anlaeufe lang kein Unittest sah.

    Ein reiner Verhaltenstest der Politurfunktion war bei allen vier
    Fehlschlaegen gruen. Was fehlte, war der Nachweis, dass der
    Produktivzweig sie ueberhaupt aufruft.
    """

    def _salvage_zweig(self) -> str:
        quelle = (
            _SRC / "candyconc" / "services" / "backend" / "routes" / "copilot.py"
        ).read_text(encoding="utf-8")
        treffer = re.search(
            r"if salvage_text is not None:.*?polish_annotations = (.{0,4000}?)\n\s*#",
            quelle,
            re.S,
        )
        self.assertIsNotNone(
            treffer, "Salvage-Politurzweig in routes/copilot.py nicht gefunden"
        )
        return treffer.group(0)

    def test_zweig_ruft_die_zitatwache(self):
        self.assertIn("politur_mit_zitatwache", self._salvage_zweig())

    def test_zweig_ruft_nicht_die_halbe_politur(self):
        """``final_answer_polish`` allein war genau der Defekt."""
        zweig = self._salvage_zweig()
        aufrufe = re.findall(r"=\s*_?(\w*polish\w*|_politur)\s*\(", zweig)
        self.assertNotIn("final_answer_polish", aufrufe)

    def test_zweig_reicht_die_turn_evidenz_durch(self):
        """Eine Wache ohne Evidenz ist eine Schere (H11.7, vierte Fassung)."""
        self.assertIn("_turn_evidence_items", self._salvage_zweig())


class DerBergungspfadKenntDieFrage(unittest.TestCase):
    """The fallback route passes the current turn question to quote verification.

Use an orchestrator double with _turn_frage and no question attribute,
matching the production state ownership. Assert route behavior rather
than the presence of a call in source text."""

    #: Die Spanne steht woertlich in der Frage und in keiner Belegzeile.
    #: Ohne den Fix streicht die Bergung sie.
    GEFRAGTE_PHRASE = "Das Boot ist voll und die Grenze muss dicht"
    FRAGE = 'Wie oft kommt „%s“ im Korpus vor?' % GEFRAGTE_PHRASE
    VORSCHAU = (
        "Der Suchbegriff „%s“ wurde im gesamten Material untersucht. "
        "Die Auswertung stuetzt sich auf eine Konkordanzabfrage ueber "
        "alle Dokumente des aktiven Korpus, nicht auf eine Stichprobe. "
        "Die Lesart der Umgebung bleibt eine Interpretation der Zeilen. "
        % GEFRAGTE_PHRASE
    ) * 2

    def setUp(self):
        from fastapi.testclient import TestClient

        from candyconc.services.backend import server

        self.server = server
        self.client = TestClient(server.app, raise_server_exceptions=False)
        antwort = self.client.post(
            "/api/v1/login", json={"username": "bob", "password": "bob"}
        )
        self.token = antwort.json()["token"]
        self.username = server.auth.username_for_token(self.token)

    def _geborgener_text(self, session_id: str) -> str:
        import asyncio
        import json
        import os
        from unittest.mock import patch

        from candyconc.services.backend import copilot_event_bus
        from candyconc.candyconc_copilot.orchestrator import State

        vorschau = self.VORSCHAU
        frage = self.FRAGE

        class _VorschauDannHaengen:
            """Traegt ``_turn_frage``, wie der echte Orchestrator es tut."""

            def __init__(self) -> None:
                self.state = State.EXECUTING_TOOL
                self._turn_evidence_items: list[dict] = []
                self._turn_frage = frage

            def _senden(self) -> None:
                copilot_event_bus.publish(
                    {
                        "event": "copilot.vorlaeufige_antwort",
                        "text": vorschau,
                        "geprueft": False,
                        "hinweis": "Vorlaeufig.",
                    },
                    session_id,
                )

            async def continue_after_approval(self, *, max_steps=8, max_time=None):
                self._senden()
                # ENDLICH, und weit ueber dem Backstop. Die Vorfassung
                # schlief 3600 Sekunden, und der Schlaf ueberlebte den
                # Test: der pytest-Prozess meldete "9 passed in 3.89s" und
                # lief danach weiter, weil der Hauptthread in
                # ``Py_FinalizeEx`` auf diesen Nicht-Daemon-Thread
                # wartete. Gemessen im Arbeitsbaum: nach 120 Sekunden noch
                # lebend, kein Exitcode, waehrend derselbe Lauf auf der
                # Basis 09aa9816d0 nach einer Sekunde endete. Jedes Gate,
                # das ``tests/backend`` faehrt, haengt daran eine Stunde.
                #
                # Kein Widerspruch zur Zeitlimit-Regel: das ist die
                # Lebensdauer eines Testdoppels, kein Per-Call-Limit eines
                # Produktpfads. Der Backstop dieses Tests feuert bei 0,25
                # plus 0,25 Sekunden, fuenf Sekunden liegen zehnfach
                # darueber und sind trotzdem endlich.
                await asyncio.sleep(5)
                return "nie"

            continue_after_clarification = continue_after_approval

            def request_cancel(self) -> None:
                return None

        doppel = _VorschauDannHaengen()
        # Die Naht ist genau das: der echte Orchestrator hat kein
        # ``question``. Ein Doppel, das eines traegt, haette den Defekt
        # zugedeckt.
        self.assertFalse(hasattr(doppel, "question"))
        self.server._register_active_orchestrator(
            session_id, doppel, self.username
        )
        try:
            with patch.dict(
                os.environ,
                {
                    "CANDYCONC_COPILOT_MAX_TIME_SEC": "0.25",
                    "CANDYCONC_COPILOT_BACKSTOP_GRACE_SEC": "0.25",
                },
            ):
                with self.client.stream(
                    "POST",
                    "/api/v1/copilot/continue",
                    params={"token": self.token},
                    json={"sessionId": session_id},
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    body = "".join(chunk for chunk in resp.iter_text())
        finally:
            self.server._active_orchestrators.pop(session_id, None)
        text = ""
        for block in body.split("\n\n"):
            if "copilot.done" not in block:
                continue
            for zeile in block.splitlines():
                if zeile.startswith("data: "):
                    text = json.loads(zeile[6:]).get("text") or ""
        return text

    def test_die_frage_erreicht_die_zitatwache_der_bergung(self):
        """Ohne den Fix faellt die Spanne aus der Frage."""
        text = self._geborgener_text("bergung-frage-1")
        self.assertTrue(text.strip(), "Die Bergung lieferte keinen Text.")
        self.assertIn(self.GEFRAGTE_PHRASE, text)
        self.assertNotIn(rr.MISSING_EVIDENCE_PLACEHOLDER, text)

    def test_die_bergung_streicht_ein_fabrikat_weiterhin(self):
        """Positive Klasse. Die Wache bleibt auf diesem Zweig scharf.

        Ohne sie waere ein Zweig gruen, der die Zitatwache ganz umgeht.
        """
        eigen = dict(self.__class__.__dict__)
        with unittest.mock.patch.object(
            self.__class__,
            "VORSCHAU",
            (
                'Ein Korpusbeleg lautet: „%s“. Die Auswertung stuetzt sich '
                "auf eine Konkordanzabfrage ueber alle Dokumente des "
                "aktiven Korpus. Die Lesart bleibt eine Interpretation. "
                % FABRIKAT
            )
            * 2,
        ):
            text = self._geborgener_text("bergung-frage-2")
        self.assertTrue(eigen)
        self.assertTrue(text.strip(), "Die Bergung lieferte keinen Text.")
        self.assertNotIn("Invasoren", text)


class DerLaufDieserDateiEndet(unittest.TestCase):
    """Eine bestandene Probe ist noch kein beendeter Prozess.

    Gemessen im Arbeitsbaum: diese Datei meldete "9 passed in 3.89s", und
    der pytest-Prozess lief danach weiter. Der Hauptthread stand in
    ``Py_FinalizeEx`` und wartete auf den Nicht-Daemon-Thread, in dem der
    3600-Sekunden-Schlaf des Orchestrator-Doppels lief. Nach 120 Sekunden
    noch lebend, kein Exitcode. Auf der Basis 09aa9816d0 endete derselbe
    Lauf nach einer Sekunde.

    Die Wache misst das VERHALTEN, nicht die Schreibweise: sie startet
    genau die Probe mit dem Doppel in einem Unterprozess und verlangt
    einen Exitcode. Eine Regex ueber den Quelltext haette denselben
    Ausfall bei jeder anderen Wartezeit durchgelassen, und die
    Projekterinnerung nennt das den Grep-Test, der die Absicht prueft
    statt der Wirkung.
    """

    def test_die_probe_mit_dem_doppel_liefert_einen_exitcode(self):
        import subprocess

        lauf = subprocess.run(
            [
                sys.executable, "-m", "pytest", str(Path(__file__)),
                "-q", "-p", "no:cacheprovider",
                "-k", "die_frage_erreicht_die_zitatwache_der_bergung",
            ],
            cwd=str(_APP),
            capture_output=True,
            text=True,
            # Weit ueber der gemessenen Laufzeit der Einzelprobe (2,89 s)
            # und weit unter dem Schlaf, der den Ausfall ausmachte.
            timeout=120,
        )
        self.assertEqual(
            lauf.returncode, 0,
            "Der Lauf endete nicht sauber:\n%s\n%s"
            % (lauf.stdout[-2000:], lauf.stderr[-2000:]),
        )


if __name__ == "__main__":
    unittest.main()
