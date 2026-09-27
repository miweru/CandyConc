import sys
import unittest
import unittest.mock
from unittest.mock import patch
import types

# Real-module contract; see tests/ai/_real_copilot.py.  The summariser LLM is
# stubbed at the package seam used by the real SessionManager
# (session_manager.py: ``from . import _lm_chat_async``).
from tests.ai._real_copilot import SessionManager, lm_summary_stub, make_orchestrator


def dummy_call(messages, tools, **kwargs):
    return {"choices": [{"message": {"content": "ok"}}]}


def dummy_dispatch(call, token=None):
    return {"status": "ok"}


class TestConversationMemory(unittest.TestCase):
    def test_summarise_history(self):
        with lm_summary_stub() as stub:
            sm = SessionManager(max_messages=3, max_tokens=50)
            for i in range(6):
                sm.append({"role": "user", "content": f"msg {i}"})
            # summarisation should trigger
            self.assertTrue(stub.called)
            # history should be trimmed
            self.assertLessEqual(len(sm.history), 3)
            # summary note created
            self.assertTrue(sm.summaries)
            hist = sm.get_history()
            self.assertEqual(hist[0]["role"], "system")

    def test_orchestrator_auto_summarises(self):
        with lm_summary_stub() as stub:
            sm = SessionManager(max_messages=3, max_tokens=50)
            orch = make_orchestrator([], dummy_call, dummy_dispatch, session=sm)
            for i in range(6):
                orch.run(f"question {i}")
            self.assertLessEqual(len(sm.history), 3)
            self.assertTrue(sm.summaries)
            hist = sm.get_history()
            self.assertEqual(hist[0]["role"], "system")
            self.assertTrue(stub.called)

    def test_token_threshold_triggers_summary(self):
        with lm_summary_stub() as stub:
            sm = SessionManager(max_messages=10, max_tokens=20)
            for _ in range(10):
                sm.append({"role": "user", "content": "one two three four five"})
            self.assertLessEqual(len(sm.history), 10)
            self.assertTrue(sm.summaries)
            self.assertTrue(stub.called)
            total_tokens = sm._token_count(sm.history)
            self.assertLessEqual(total_tokens, sm._threshold)

    def test_token_count_zaehlt_woerter_auch_mit_tiktoken(self):
        """Umgekehrtes Pinning (2026-09-02): die Einheit ist das Wort.

        Hier stand ``test_token_count_uses_tiktoken`` und pinnte die
        Verzweigung, die ``_token_count`` in Tokens rechnen liess, sobald
        ``tiktoken`` importierbar war und ``encoding_for_model`` den
        Modellnamen kannte. Die Einheit des Budgets hing damit am venv.

        Die Verdichtungsschwelle wird seit P2 aus gemessenen WORTZAHLEN
        abgeleitet (sitzungsverdichtung.session_max_tokens: 652 Woerter je
        KWIC-Ergebnis mit 50 Zeilen, 114 + 833 Woerter fuer Frage und
        Antwort). In Tokens gerechnet traegt dieselbe Zahl deutlich weniger
        Werkzeugergebnisse, und die zugesicherte Rohheit der Evidenz fiele
        still weg, ohne dass irgendwo etwas rot wird. ``tiktoken`` steht in
        requirements.txt:17 und fehlt in diesem venv nur zufaellig.

        Die Probe ist damit nicht schwaecher, sondern zielt auf die andere
        Richtung: sie wird rot, wenn die Einheit wieder kippt.
        """
        fake = types.SimpleNamespace()
        enc = unittest.mock.Mock()
        enc.encode.side_effect = lambda t: t.split("-")
        fake.encoding_for_model = unittest.mock.Mock(return_value=enc)

        pkg = sys.modules["candyconc_copilot"]
        had_model = hasattr(pkg, "_LM_MODEL")
        prev_model = getattr(pkg, "_LM_MODEL", None)
        pkg._LM_MODEL = "test-model"
        try:
            with patch.dict("sys.modules", {"tiktoken": fake}):
                # "a-b-c" sind drei tiktoken-Einheiten, aber ein Wort.
                self.assertEqual(
                    SessionManager._token_count(
                        [{"role": "user", "content": "a-b-c"}]
                    ),
                    1,
                    "Die Schwelle zaehlt nicht mehr in Woertern",
                )
                self.assertFalse(
                    fake.encoding_for_model.called,
                    "tiktoken wird wieder befragt: die Einheit haengt am venv",
                )
        finally:
            if had_model:
                pkg._LM_MODEL = prev_model
            else:
                try:
                    delattr(pkg, "_LM_MODEL")
                except AttributeError:
                    pass


if __name__ == "__main__":
    unittest.main()
