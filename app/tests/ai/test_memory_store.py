import unittest

from candyconc.candyconc_copilot.memory_store import MemoryStore
from candyconc.candyconc_copilot.session_manager import SessionManager


def dummy_call(messages, tools):
    dummy_call.last_messages = list(messages)
    return {"choices": [{"message": {"content": "ok"}}]}


def dummy_dispatch(name, **kw):
    return {"status": "ok"}


class TestMemoryStore(unittest.TestCase):
    def test_add_and_search(self):
        store = MemoryStore()
        store.add("a", [1.0])
        store.add("b", [0.5])
        res = store.search("q", k=1)
        self.assertEqual(res, ["a"])

    def test_retrieval_in_history(self):
        sm = SessionManager(max_messages=3)
        for i in range(5):
            sm.append({"role": "user", "content": f"m{i}"})
        sm.summarise()
        sm.search("query")
        hist = sm.get_history()
        self.assertEqual(hist[0]["role"], "system")
        self.assertIn("summary", hist[0]["content"])


if __name__ == "__main__":
    unittest.main()
