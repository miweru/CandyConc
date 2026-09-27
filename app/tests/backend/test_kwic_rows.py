import unittest
from unittest.mock import patch

from candyconc.services.backend.kwic import kwic_rows, kwic_rows_list
import candyconc.services.backend.kwic as kwic_module


class TestKwicRows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.run_query_patch = patch(
            "candyconc.services.backend.kwic.run_query",
            return_value=[{"left": "quick brown", "kw": "fox", "right": "jumps over", "pos": 3}],
        )
        self.mask_patch = patch(
            "candyconc.services.backend.kwic.mask_pii",
            side_effect=lambda text, **_: text,
        )
        self.run_query_patch.start()
        self.mask_patch.start()
        kwic_module._CORPUS_INDEX = object()

    async def asyncTearDown(self):
        self.mask_patch.stop()
        self.run_query_patch.stop()
        kwic_module._CORPUS_INDEX = None
    async def test_row_contains_pos(self):
        gen = kwic_rows("fox", ctx=2)
        row = await gen.__anext__()
        self.assertIn("pos", row)

    async def test_kwic_rows_list_matches_async_path(self):
        rows = kwic_rows_list("fox", ctx=2)
        gen = kwic_rows("fox", ctx=2)
        row = await gen.__anext__()
        self.assertEqual(rows, [row])


if __name__ == "__main__":
    unittest.main()
