import unittest

from candyconc.domain.query_parser import parse_query, Regex, Wildcard
from candyconc.domain.query_eval import evaluate_tokens
tokens = "the quick brown fox jumps over the lazy dog".split()


class TestRegexWildcard(unittest.TestCase):
    def test_regex_search(self):
        node = parse_query("/f.x/")
        self.assertIsInstance(node, Regex)
        matches = evaluate_tokens(node, tokens)
        self.assertEqual([tokens[i] for i in sorted(matches)], ["fox"])

    def test_wildcard_search(self):
        node = parse_query("do?")
        self.assertIsInstance(node, Wildcard)
        matches = evaluate_tokens(node, tokens)
        self.assertEqual([tokens[i] for i in sorted(matches)], ["dog"])


if __name__ == "__main__":
    unittest.main()
