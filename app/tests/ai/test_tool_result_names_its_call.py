"""Every tool result identifies the call that produced it."""

import asyncio
import json
import unittest

from tests.ai._real_copilot import make_orchestrator
from tests.ai.test_empty_stop_is_retried import _antwort, _leerer_stop, _skript_llm, _spec


class ErgebnisNenntAufruf(unittest.TestCase):
    def _orch(self, skript):
        async def _dispatch(tool_call, _token=None):
            return {"status": "success", "total": 42}
        rufe = []
        return make_orchestrator([_spec("query_count")], _skript_llm(skript, rufe), _dispatch), rufe

    def test_werkzeugnachricht_traegt_werkzeug_und_argumente(self):
        def ruf(nr):
            return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{nr}", "type": "function",
                 "function": {"name": "query_count", "arguments": '{"query": "fazit", "docset_id": "d%d"}' % nr}}]},
                "finish_reason": "tool_calls"}]}
        orch, rufe = self._orch([ruf(0), _leerer_stop(), ruf(1), _antwort("Fertig.")])
        orch._turn_evidence_items = [{"id": "E1", "tool": "query_count"}]
        asyncio.run(orch.run_async("Wie oft kommt Fazit vor?"))
        werkzeug = [m for m in rufe[-1]["messages"] if m.get("role") == "tool"]
        self.assertTrue(werkzeug, "Die letzte Anfrage traegt das Werkzeugergebnis.")
        inhalt = json.loads(werkzeug[-1]["content"])
        self.assertEqual(inhalt["aufruf"], {"werkzeug": "query_count",
                                            "argumente": {"query": "fazit", "docset_id": "d1"}})


if __name__ == "__main__":
    unittest.main()
