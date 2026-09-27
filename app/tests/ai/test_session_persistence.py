import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
import importlib.util
import sys
from unittest.mock import AsyncMock, patch
import types

root = Path(__file__).resolve().parents[2]

# remove stubs from conftest
for name in [
    "candyconc_copilot",
    "candyconc_copilot.session_manager",
    "candyconc_copilot.session_compaction",
    "candyconc_copilot.memory_store",
    "candyconc_copilot.orchestrator",
    "candyconc_copilot.policy_engine",
    "candyconc_copilot.observability",
]:
    sys.modules.pop(name, None)

base_pkg = types.ModuleType("candyconc_copilot")
# ``__path__`` zeigt auf das ECHTE Paketverzeichnis. Es stand hier leer, und
# weil dieses Modul das Ersatzpaket in sys.modules stehen laesst, sahen ALLE
# spaeter gesammelten Testmodule ein Paket ohne Suchpfad: jeder verzoegerte
# Import des Orchestrators (``from .deterministic_landing import ...``,
# orchestrator.py:5874) schlug dann mit ModuleNotFoundError fehl. Gemessen am
# 2026-09-02: fuenf Turn-Proben in tests/ai/test_p2_session_compaction.py
# waren allein gruen und in der Sammelmenge rot, und dieses Modul selbst
# brach beim Sammeln an ``candyconc_copilot.cql_validation`` ab.
base_pkg.__path__ = [str(root / "src" / "candyconc" / "candyconc_copilot")]
base_pkg._lm_chat_async = lambda msgs, tools=None: {}
sys.modules["candyconc_copilot"] = base_pkg

# load real package modules

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[arg-type]
    sys.modules[name] = mod
    return mod

_load("candyconc_copilot.memory_store", root / "src" / "candyconc" / "candyconc_copilot" / "memory_store.py")
# Muss VOR session_manager geladen sein: dessen ``from .sitzungsverdichtung
# import ...`` wird ueber den sys.modules-Eintrag aufgeloest, damit hier
# dieselbe Modulinstanz steht wie in ``sm_mod``.
_load("candyconc_copilot.session_compaction", root / "src" / "candyconc" / "candyconc_copilot" / "session_compaction.py")
sm_mod = _load("candyconc_copilot.session_manager", root / "src" / "candyconc" / "candyconc_copilot" / "session_manager.py")
_load("candyconc_copilot.policy_engine", root / "src" / "candyconc" / "candyconc_copilot" / "policy_engine.py")
_load("candyconc_copilot.observability", root / "src" / "candyconc" / "candyconc_copilot" / "observability.py")
orch_mod = _load("candyconc_copilot.orchestrator", root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py")

SessionManager = sm_mod.SessionManager
ReActOrchestrator = orch_mod.ReActOrchestrator


def dummy_llm(messages, tools):
    return {"choices": [{"message": {"content": "ok"}}]}


def dummy_dispatch(name, **kw):
    return {"status": "ok"}


class TestSessionPersistence(unittest.TestCase):
    @patch("candyconc_copilot._lm_chat_async", new_callable=AsyncMock)
    def test_persist_and_reload(self, mock_chat):
        mock_chat.return_value = {"role": "assistant", "content": "summary"}
        with TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "mem.db"
            sm1 = SessionManager(max_messages=3, session_id="s1", db_path=str(db))
            orch1 = ReActOrchestrator([], dummy_llm, dummy_dispatch, session=sm1)
            for i in range(5):
                orch1.session.append({"role": "user", "content": f"m{i}"})
            orch1.session.summarise()
            self.assertTrue(db.exists())
            self.assertTrue(sm1.summaries)
            sm1.close()

            sm2 = SessionManager(max_messages=3, session_id="s1", db_path=str(db))
            orch2 = ReActOrchestrator([], dummy_llm, dummy_dispatch, session=sm2)
            self.assertEqual(sm2.summaries, sm1.summaries)
            res = orch2.session.search("summary")
            self.assertTrue(res)
            sm2.close()


if __name__ == "__main__":
    unittest.main()
