import unittest

from candyconc.tooling.registry import REGISTRY, get_tools, llm_tool


class TestRegistry(unittest.TestCase):
    def test_register_new_tool_keeps_schema_and_callable(self):
        before = list(REGISTRY)

        try:
            @llm_tool(
                {
                    "type": "function",
                    "function": {
                        "name": "dummy",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                read_only=False,
                concurrency_safe=False,
            )
            def dummy_tool():
                return {"status": "ok"}

            names = [tool["function"]["name"] for tool in get_tools()]
            self.assertIn("dummy", names)

            entry = next(tool for tool in REGISTRY if tool["function"]["name"] == "dummy")
            self.assertIs(entry["callable"], dummy_tool)
            self.assertFalse(entry["read_only"])
            self.assertFalse(entry["concurrency_safe"])
            self.assertEqual(entry["function"]["parameters"]["type"], "object")
        finally:
            REGISTRY[:] = before

    def test_rejects_non_object_tool_schema(self):
        with self.assertRaises(ValueError):
            llm_tool(
                {
                    "type": "function",
                    "function": {
                        "name": "bad",
                        "parameters": {"type": "array"},
                    },
                }
            )(lambda: None)


if __name__ == "__main__":
    unittest.main()
