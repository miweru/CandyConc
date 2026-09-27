"""Corpus activation reports when a configured index pin prevents switching.

Environment and configuration pins take precedence over the registry.
The response must identify this state so subsequent queries can be
attributed to the index they actually use."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from candyconc.services.backend import server  # noqa: E402


class AktivierungWirkungslos(unittest.TestCase):
    def setUp(self):
        self._alt = os.environ.get("CANDYCONC_INDEX_PATH")
        self._pin = Path(__file__).resolve().parent
        self.addCleanup(self._restore)

    def _restore(self):
        if self._alt is None:
            os.environ.pop("CANDYCONC_INDEX_PATH", None)
        else:
            os.environ["CANDYCONC_INDEX_PATH"] = self._alt

    def test_pin_auf_anderen_index_ist_ein_hindernis(self):
        os.environ["CANDYCONC_INDEX_PATH"] = str(self._pin)
        grund = server.aktivierung_wirkungslos("/tmp/ganz_anderer_korpus")
        self.assertIsNotNone(grund)
        self.assertIn("CANDYCONC_INDEX_PATH", grund)
        self.assertIn("env > config > registry", grund)

    def test_die_meldung_nennt_beide_pfade(self):
        """Ohne beide Pfade kann niemand das Problem beheben."""
        os.environ["CANDYCONC_INDEX_PATH"] = str(self._pin)
        grund = server.aktivierung_wirkungslos("/tmp/ganz_anderer_korpus")
        self.assertIn(str(self._pin), grund)
        self.assertIn("ganz_anderer_korpus", grund)

    def test_pin_auf_dasselbe_ziel_ist_kein_hindernis(self):
        os.environ["CANDYCONC_INDEX_PATH"] = str(self._pin)
        self.assertIsNone(server.aktivierung_wirkungslos(str(self._pin)))

    def test_ohne_pin_kein_hindernis(self):
        os.environ.pop("CANDYCONC_INDEX_PATH", None)
        # Ohne env-Pin entscheidet die Konfiguration; zeigt sie nirgends
        # hin, ist die Aktivierung wirksam.
        grund = server.aktivierung_wirkungslos("/tmp/irgendein_korpus")
        if grund is not None:
            self.assertIn("Konfiguration", grund)

    def test_ohne_zielpfad_wird_nicht_geraten(self):
        os.environ["CANDYCONC_INDEX_PATH"] = str(self._pin)
        self.assertIsNone(server.aktivierung_wirkungslos(None))
        self.assertIsNone(server.aktivierung_wirkungslos(""))

    def test_unbrauchbarer_pin_blockiert_die_aktivierung_nicht(self):
        """Ein kaputter Pin ist ein eigenes Problem, kein Aktivierungs-Veto."""
        os.environ["CANDYCONC_INDEX_PATH"] = "/gibt/es/nicht/12345"
        self.assertIsNone(server.aktivierung_wirkungslos("/tmp/korpus"))


class RouteMeldetDieWirkungslosigkeit(unittest.TestCase):
    """Die Aktivierung wird nicht verweigert, aber auch nicht beschoenigt.

    Verweigern waere zu scharf: die Registry-Aktivierung ist fuer sich
    legitim -- sie haelt fest, welcher Korpus gelten soll, etwa vor einem
    Neustart ohne Pin. Ein bestehender Test sichert diese Umkehrbarkeit
    ausdruecklich. Falsch war nie die Aktivierung, sondern die stille
    Behauptung, sie wirke auf die Abfragen.
    """

    def test_warnung_steht_in_der_antwort(self):
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        from candyconc.domain import corpus
        from candyconc.services.backend import server

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            wurzel = Path(tmp)
            gepinnt = _index_verzeichnis(wurzel / "gepinnt")
            ziel = _index_verzeichnis(wurzel / "ziel")
            alt_registry = corpus._REGISTRY_PATH
            alt_dir = server._CORPUS_DIR
            alt_settings = server.load_settings
            alt_reload = server.reload_default_corpus_runtime_state
            alt_env = os.environ.get("CANDYCONC_INDEX_PATH")
            alt_tempdir = server.tempfile.gettempdir
            try:
                # Der Server weist Indexpfade unter dem System-Temp ab. Ohne
                # diesen Patch scheitert die Pfadaufloesung, und der
                # Waechter kaeme gar nicht erst zum Zug.
                server.tempfile.gettempdir = lambda: str(wurzel / "_system_tmp")
                corpus._REGISTRY_PATH = wurzel / "registry.json"
                server._CORPUS_DIR = wurzel / "managed"
                server._CORPUS_DIR.mkdir(exist_ok=True)
                server._INDEX_PATH = None
                server.load_settings = lambda: SimpleNamespace(index_dir="")
                os.environ["CANDYCONC_INDEX_PATH"] = str(gepinnt)

                async def _noop() -> None:
                    return None

                server.reload_default_corpus_runtime_state = _noop
                corpus.CorpusRegistry.load().register(gepinnt, activate=True)
                corpus.CorpusRegistry.load().register(ziel, activate=False)
                client = TestClient(server.app)
                antwort = client.post("/api/v1/corpora/ziel/activate")
                self.assertEqual(antwort.status_code, 200, antwort.text)
                nutzlast = antwort.json()
                self.assertIs(nutzlast.get("wirksam_fuer_abfragen"), False)
                self.assertIn("CANDYCONC_INDEX_PATH", nutzlast.get("warnung", ""))
            finally:
                server.tempfile.gettempdir = alt_tempdir
                corpus._REGISTRY_PATH = alt_registry
                server._CORPUS_DIR = alt_dir
                server.load_settings = alt_settings
                server.reload_default_corpus_runtime_state = alt_reload
                if alt_env is None:
                    os.environ.pop("CANDYCONC_INDEX_PATH", None)
                else:
                    os.environ["CANDYCONC_INDEX_PATH"] = alt_env


def _index_verzeichnis(pfad: Path) -> Path:
    pfad.mkdir(parents=True, exist_ok=True)
    for datei in ("meta.bin", "document_bounds.bin"):
        (pfad / datei).write_bytes(b"\x00")
    (pfad / "index_manifest.json").write_text('{"complete": true}', encoding="utf-8")
    return pfad


if __name__ == "__main__":
    unittest.main()
