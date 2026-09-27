import importlib
import unittest

class TestCopilotExports(unittest.TestCase):
    def test_module_functions_exist(self):
        mod = importlib.import_module("candyconc.candyconc_copilot")
        for name in [
            "frequency_list",
            "collocate_stats",
            "word_sketch",
            "dispersion_offsets",
            "keyness",
            "run_cqlf_query",
        ]:
            with self.subTest(name=name):
                self.assertTrue(hasattr(mod, name))

    def test_tool_wrappers_exist(self):
        mod = importlib.import_module("candyconc.candyconc_copilot.tool_wrappers")
        for name in [
            "run_cqlf_query_tool",
            "collocate_stats_tool",
            "frequency_list_tool",
            "dispersion_offsets_tool",
            "keyness_tool",
            "semantic_search_tool",
            "transformer_search_tool",
        ]:
            with self.subTest(name=name):
                self.assertTrue(hasattr(mod, name))

if __name__ == "__main__":
    unittest.main()
