import unittest

# Real-module contract; see tests/ai/_real_copilot.py.
from tests.ai._real_copilot import make_orchestrator

from candyconc.candyconc_copilot.prompt_layout import build_static_core


class TestSystemPrompt(unittest.TestCase):
    def test_prompt_prepended(self):
        captured = {}

        def _call_llm(messages, tools, **kwargs):
            captured['messages'] = messages
            return {"choices": [{"message": {"content": "ok"}}]}

        orch = make_orchestrator([], _call_llm, lambda call, token=None: {})
        orch.run("hello")

        # R2 contract: messages[0] is the KV-split system prompt — the
        # byte-stable static core prefix, then the variable turn suffix that
        # ends with the <turn_briefing> block (orchestrator.py:
        # _ra_build_turn_system_prompt).
        static_core = build_static_core()
        self.assertEqual(captured['messages'][0]['role'], 'system')
        self.assertTrue(
            captured['messages'][0]['content'].startswith(static_core)
        )
        self.assertTrue(
            captured['messages'][0]['content'].rstrip().endswith(
                "</turn_briefing>"
            )
        )
        # History (incl. session rehydration frames) follows the system
        # prompt; the user turn is the last history entry.
        self.assertEqual(captured['messages'][-2]['role'], 'user')
        self.assertEqual(captured['messages'][-2]['content'], 'hello')
        # The per-call runtime guard is a turn variable and therefore sits at
        # the END of the message list, never before the static core. Seit der
        # Waechter-Rollen-Aenderung (a038abb3e1, Mistral-Jinja-Kompatibilitaet)
        # reist er als USER-Nachricht mit [System note:]-Wrapper.
        self.assertEqual(captured['messages'][-1]['role'], 'user')
        self.assertIn(
            "keine Tools verfügbar", captured['messages'][-1]['content']
        )
        self.assertIn(
            "[System note:", captured['messages'][-1]['content']
        )


if __name__ == "__main__":
    unittest.main()
