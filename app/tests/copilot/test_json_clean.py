"""Direct tests for the JSON-cleaning helper ``candyconc.utils.extract_json_block``.

Historical note: this file used to exercise the helper indirectly through
``candyconc_copilot.query_suggest.suggest_queries`` (deleted — it had no
runtime consumer). The behaviour under test — pulling the first balanced JSON
block out of noisy LLM output (leading <think> chatter, code fences, stray
backslashes) — lives in ``candyconc.utils.json_tools.extract_json_block`` and
is tested here directly.
"""

import unittest

from candyconc.utils import extract_json_block


class TestExtractJsonBlock(unittest.TestCase):
    def test_json_after_think_prefix(self):
        # The exact payload shape the old suggest_queries test used: leading
        # <think> chatter before the JSON object.
        raw = ' <think>blah</think> {"suggestions": ["foo", "bar"]}'
        result = extract_json_block(raw)
        self.assertEqual(result, {"suggestions": ["foo", "bar"]})

    def test_json_in_code_fence(self):
        raw = '```json\n{"suggestions": ["foo"]}\n```'
        self.assertEqual(extract_json_block(raw), {"suggestions": ["foo"]})

    def test_top_level_list(self):
        raw = 'Vorspann ["a", "b"] Nachspann'
        self.assertEqual(extract_json_block(raw), ["a", "b"])

    def test_braces_inside_strings_do_not_break_balance(self):
        raw = '{"text": "ein { in einem String }", "n": 1}'
        self.assertEqual(
            extract_json_block(raw),
            {"text": "ein { in einem String }", "n": 1},
        )

    def test_stray_backslash_is_repaired(self):
        # \$ is not a valid JSON escape; the helper doubles stray backslashes.
        raw = '{"pattern": "\\$"}'
        self.assertEqual(extract_json_block(raw), {"pattern": "\\$"})

    def test_no_json_block_raises(self):
        with self.assertRaises(RuntimeError):
            extract_json_block("kein JSON hier")

    def test_unbalanced_json_raises(self):
        with self.assertRaises(RuntimeError):
            extract_json_block('{"open": [1, 2')


if __name__ == "__main__":
    unittest.main()
