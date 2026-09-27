import unittest
import importlib
import sys


class TestDocumentationTool(unittest.TestCase):
    def test_documentation_search(self):
        sys.modules.pop("candyconc_copilot.tool_wrappers", None)
        tool_mod = importlib.import_module("candyconc_copilot.tool_wrappers")
        res = tool_mod.documentation_search_tool("CandyConc", top_n=1)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["rows"])


if __name__ == "__main__":
    unittest.main()
