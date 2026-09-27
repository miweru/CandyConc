"""FT-COPILOT-CORPUS-RESOLVE: copilot analysis tools must operate on the
PER-REQUEST corpus, not the process-global ``query_runtime._CORPUS_INDEX``.

Defect: ``dispersion_offsets_tool`` / ``document_search_tool`` /
``metadata_values_tool`` / ``similar_words_tool`` read the global index via bare
``_get_index()`` / ``_get_doc_index()``. Under concurrency that global is shared
across requests, so a tool could silently analyse the WRONG corpus while another
request swapped the active index.

Fixed contract: each of those tools resolves the corpus PER CALL via
``_resolve_corpus_index(corpus)``, which routes through
``services.backend.server.get_corpus`` (the canonical per-corpus resolver) —
never the mutable global. When a concrete corpus name is passed, the requested
corpus index is used; when the server is unavailable (bare fakes) the helper
falls back to the legacy global so unit tests keep working.
"""

import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _load_real_tool_wrappers():
    # conftest stubs the module in sys.modules; import the real one then restore.
    saved = sys.modules.get("candyconc_copilot.tool_wrappers")
    sys.modules.pop("candyconc_copilot.tool_wrappers", None)
    try:
        return importlib.import_module("candyconc_copilot.tool_wrappers")
    finally:
        if saved is not None:
            sys.modules["candyconc_copilot.tool_wrappers"] = saved
        else:
            sys.modules.pop("candyconc_copilot.tool_wrappers", None)


_tw = _load_real_tool_wrappers()


class TestResolveCorpusIndex(unittest.TestCase):
    def test_named_corpus_resolves_through_server_not_global(self):
        # A concrete corpus name must resolve via server.get_corpus(name) — the
        # per-corpus index — not the process-global _CORPUS_INDEX.
        from candyconc.services.backend import server as _server

        requested = SimpleNamespace(name="requested_corpus_index")
        global_idx = SimpleNamespace(name="GLOBAL_should_not_be_used")

        with patch.object(_server, "get_corpus", return_value=requested) as gc, patch.object(
            _tw, "_get_index", return_value=global_idx
        ):
            got = _tw._resolve_corpus_index("corpus_b")

        gc.assert_called_once_with("corpus_b")
        self.assertIs(got, requested)

    def test_default_corpus_resolves_through_server(self):
        from candyconc.services.backend import server as _server

        active = SimpleNamespace(name="active_default")
        with patch.object(_server, "get_corpus", return_value=active) as gc:
            got = _tw._resolve_corpus_index(None)
        gc.assert_called_once_with(None)
        self.assertIs(got, active)

    def test_active_alias_resolves_through_server_as_active_corpus(self):
        from candyconc.services.backend import server as _server

        active = SimpleNamespace(name="active_default")
        with patch.object(_server, "get_corpus", return_value=active) as gc:
            got = _tw._resolve_corpus_index("active")
        gc.assert_called_once_with(None)
        self.assertIs(got, active)

    def test_falls_back_to_global_when_server_resolution_fails(self):
        # No server-resolved corpus (e.g. get_index() raised because no index is
        # loaded): the helper falls back to the legacy global so the "no corpus"
        # RuntimeError surfaces unchanged.
        from candyconc.services.backend import server as _server

        global_idx = SimpleNamespace(name="legacy_global")
        with patch.object(_server, "get_corpus", side_effect=RuntimeError("no index")), patch.object(
            _tw, "_get_index", return_value=global_idx
        ):
            got = _tw._resolve_corpus_index("anything")
        self.assertIs(got, global_idx)


class TestToolsThreadPerRequestCorpus(unittest.TestCase):
    """Each touched tool must call _resolve_corpus_index with its corpus arg
    and analyse THAT index, never bare _get_index()/_get_doc_index()."""

    def test_dispersion_offsets_uses_resolved_corpus(self):
        # FIX-D: offsets are resolved via the REST dispersion seam
        # (server._dispersion_positions_for_term). The tool must still resolve the
        # per-call corpus and pass THAT index — never the active fallback — to the
        # seam. A boundaries-free fake index drives the positional-window summary.
        from candyconc.services.backend import server as _server

        requested = SimpleNamespace(
            name="corpus_b",
            token_count=lambda: 10,
            fast_index=SimpleNamespace(boundaries=None),
        )
        captured = {}

        def _fake_positions(idx, term, *, docset_mask):
            captured["idx"] = idx
            captured["term"] = term
            return [1, 5]

        with patch.object(_tw, "_resolve_corpus_index", return_value=requested) as rc, patch.object(
            _server, "_dispersion_positions_for_term", side_effect=_fake_positions
        ):
            res = _tw.dispersion_offsets_tool("fox", partitions=4, corpus="corpus_b")

        rc.assert_called_once_with("corpus_b")
        self.assertIs(captured["idx"], requested)
        self.assertEqual(captured["term"], "fox")
        self.assertEqual(res["status"], "success")

    def test_document_search_uses_resolved_corpus(self):
        requested = SimpleNamespace(name="corpus_b")
        captured = {}

        def _fake_search(idx, term, **kwargs):
            captured["idx"] = idx
            return [{"file": "d", "pos": 1, "score": 1.0, "snippet": "s"}]

        with patch.object(_tw, "_resolve_corpus_index", return_value=requested) as rc, patch.object(
            _tw, "_document_search", side_effect=_fake_search
        ):
            res = _tw.document_search_tool("fox", top_n=1, corpus="corpus_b")

        rc.assert_called_once_with("corpus_b")
        self.assertIs(captured["idx"], requested)
        self.assertEqual(res["status"], "success")

    def test_metadata_values_uses_resolved_corpus(self):
        class FakeIndex:
            name = "corpus_b"

            def metadata_fields(self):
                return ["source", "model"]

            def metadata_values(self, field, filters=None):
                return {"source": ["s"], "model": ["m"]}.get(field, [])

        requested = FakeIndex()
        with patch.object(_tw, "_resolve_corpus_index", return_value=requested) as rc:
            res = _tw.metadata_values_tool(fields=["source"], corpus="corpus_b")

        rc.assert_called_once_with("corpus_b")
        self.assertEqual(res["status"], "success")
        self.assertIn("source", res["values"])

    def test_similar_words_uses_resolved_corpus(self):
        from candyconc.core import cql_macros as _cql_macros
        from candyconc.services.backend.routes import semantic as _semantic_routes

        class _Freq:
            def to_dicts(self):
                # The returned neighbour must be corpus-present (corpus_frequency
                # >= 1) to survive the corpus-restriction skip that mirrors the
                # REST route; this test only cares about the resolved-corpus index.
                return [{"word": "hound", "f": 3}]

        class FakeIndex:
            name = "corpus_b"

            def frequency_list(self):
                return _Freq()

        requested = FakeIndex()
        captured = {}

        def _fake_scored(term, k, idx):
            captured["idx"] = idx
            return [{"word": "hound", "score": 0.9}]

        # SEM-01: this test asserts the resolved-corpus index reaches the engine,
        # which is DOWNSTREAM of the word_similarity capability gate. Let the shared
        # gate pass (the FakeIndex has no capability descriptor and would fail the
        # gate closed) so the resolved-corpus path is actually exercised.
        with patch.object(_tw, "_resolve_corpus_index", return_value=requested) as rc, patch.object(
            _cql_macros, "similar_words_scored", side_effect=_fake_scored
        ), patch.object(_semantic_routes, "_word_similarity_available", return_value=True):
            res = _tw.similar_words_tool("fox", k=5, corpus="corpus_b")

        rc.assert_called_once_with("corpus_b")
        self.assertIs(captured["idx"], requested)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["neighbours"])


if __name__ == "__main__":
    unittest.main()
