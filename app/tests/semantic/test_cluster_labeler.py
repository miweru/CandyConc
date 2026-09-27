import asyncio
import unittest

from candyconc.services.cluster_labeler import generate_label


class TestClusterLabeler(unittest.TestCase):
    def test_generate_label_has_heuristic_fallback_for_token_samples(self):
        label = asyncio.run(generate_label(["Demokratie", "Rechtsstaat", "Wahl"]))
        self.assertTrue(label)
        self.assertIn(label.split()[0].casefold(), {"demokratie", "rechtsstaat", "wahl"})


if __name__ == "__main__":
    unittest.main()
