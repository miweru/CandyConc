"""Rare rates retain significant digits rather than rounding to 0.0."""

from unittest import mock

from tests.core.test_cqlf_where_conformance import _AmMiniaturindex


class SelteneRate(_AmMiniaturindex):
    def _zaehle(self, nenner: int) -> dict:
        from candyconc.services.backend import server as _server
        from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

        tw = _load_real_tool_wrappers()
        vorher = getattr(_server, "_INDEX", None)
        _server.set_default_index(self.idx)
        try:
            # Only the denominator grows. Hits and query stay fixed while the
            # word_count and raw-token denominators grow together.
            with mock.patch.object(type(self.idx), "token_count", lambda _self: nenner), \
                    mock.patch.object(type(self.idx), "word_count", lambda _self: nenner):
                return tw.query_count_tool('cql:[word="zudem"]')
        finally:
            _server.set_default_index(vorher)

    def test_vier_treffer_auf_130_millionen_token_sind_keine_null(self):
        r = self._zaehle(130_843_366)
        self.assertEqual(int(r["total"]), 4)
        self.assertEqual(int(r["denominator_tokens"]), 130_843_366)
        self.assertEqual(float(r["per_million"]), 0.031)

    def test_raten_ab_eins_behalten_eine_nachkommastelle(self):
        r = self._zaehle(2_328_677)
        self.assertEqual(float(r["per_million"]), 1.7)
