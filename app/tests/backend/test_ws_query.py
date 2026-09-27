import json
import unittest
import httpx
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from candyconc.services.backend import app


# Patch httpx.Client to ignore unsupported 'app' kwarg used by TestClient on
# older Starlette versions.
_orig_client_init = httpx.Client.__init__


def _patched_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patched_init  # type: ignore


class TestQueryStreamSSE(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.get_corpus_patch = patch(
            "candyconc.services.backend.server.get_corpus",
            return_value=object(),
        )
        self.doc_bounds_patch = patch(
            "candyconc.services.backend.server._doc_bounds_for_index",
            side_effect=RuntimeError("no bounds"),
        )
        self.kwic_patch = patch(
            "candyconc.services.backend.kwic.kwic_rows",
            return_value=self._kwic_gen(),
        )
        self.get_corpus_patch.start()
        self.doc_bounds_patch.start()
        self.kwic_mock = self.kwic_patch.start()

    async def _kwic_gen(self):
        yield {"left": "", "kw": "the", "right": "quick", "pos": 0}
        yield {"left": "dog", "kw": "the", "right": "", "pos": 8}

    def test_query_stream_sends_batches_and_done(self):
        saw_batch = False
        saw_done = False
        current_event: str | None = None

        with patch(
            "candyconc.services.backend.server._prepare_cql_rows_fast",
            return_value=None,
        ), patch(
            "candyconc.services.backend.server._prepare_plain_rows_fast",
            return_value=None,
        ):
            with self.client.stream(
                "GET",
                "/api/v1/query/stream",
                params={"term": "the", "ctx": 1, "batch_size": 1, "limit": 2},
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                for raw_line in resp.iter_lines():
                    if raw_line is None:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]

                    if current_event == "batch":
                        rows = json.loads(data)
                        self.assertIsInstance(rows, list)
                        self.assertGreaterEqual(len(rows), 1)
                        self.assertEqual(rows[0]["kw"], "the")
                        saw_batch = True
                    elif current_event == "done":
                        payload = json.loads(data)
                        self.assertIn("total", payload)
                        saw_done = True
                        break

        self.assertTrue(saw_batch)
        self.assertTrue(saw_done)

    def test_query_stream_uses_direct_cql_fastpath(self):
        current_event: str | None = None
        saw_batch = False
        self.kwic_mock.side_effect = AssertionError("kwic_rows should not be used for direct CQL stream fastpath")
        prepared = ('[word="the"]', __import__("numpy").array([0, 8], dtype="uint32"), None, None, 0, 2, True)
        rendered_batches = [
            [{"left": "", "kw": "the", "right": "quick", "pos": 0, "doc_id": 0, "doc": "d0", "meta": {}}],
            [{"left": "dog", "kw": "the", "right": "", "pos": 8, "doc_id": 1, "doc": "d1", "meta": {}}],
        ]
        with patch(
            "candyconc.services.backend.server._prepare_cql_rows_fast",
            return_value=prepared,
        ), patch(
            "candyconc.services.backend.server._render_cql_fast_rows",
            side_effect=rendered_batches,
        ), patch(
            "candyconc.services.backend.server._get_or_create_query_count",
            new=AsyncMock(return_value=None),
        ):
            with self.client.stream(
                "GET",
                "/api/v1/query/stream",
                params={"term": 'cql:[word=\"the\"]', "ctx": 1, "batch_size": 1, "limit": 2},
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                for raw_line in resp.iter_lines():
                    if raw_line is None:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if current_event == "batch" and line.startswith("data: "):
                        rows = json.loads(line[6:])
                        self.assertEqual(rows[0]["kw"], "the")
                        saw_batch = True
                        break
        self.assertTrue(saw_batch)
        self.assertEqual(self.kwic_mock.call_count, 0)

    def test_query_stream_uses_direct_plain_fastpath(self):
        current_event: str | None = None
        saw_batch = False
        self.kwic_mock.side_effect = AssertionError("kwic_rows should not be used for direct plain stream fastpath")
        prepared = ("the", __import__("numpy").array([0, 8], dtype="uint32"), 2, False)
        rendered_batches = [
            [{"left": "", "kw": "the", "right": "quick", "pos": 0, "doc_id": 0, "doc": "d0", "meta": {}}],
            [{"left": "dog", "kw": "the", "right": "", "pos": 8, "doc_id": 1, "doc": "d1", "meta": {}}],
        ]
        with patch(
            "candyconc.services.backend.server._prepare_cql_rows_fast",
            return_value=None,
        ), patch(
            "candyconc.services.backend.server._prepare_plain_rows_fast",
            return_value=prepared,
        ), patch(
            "candyconc.services.backend.server._render_fast_rows_for_positions",
            side_effect=rendered_batches,
        ), patch(
            "candyconc.services.backend.server._get_or_create_query_count",
            new=AsyncMock(return_value=None),
        ):
            with self.client.stream(
                "GET",
                "/api/v1/query/stream",
                params={"term": "the", "ctx": 1, "batch_size": 1, "limit": 2},
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                for raw_line in resp.iter_lines():
                    if raw_line is None:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if current_event == "batch" and line.startswith("data: "):
                        rows = json.loads(line[6:])
                        self.assertEqual(rows[0]["kw"], "the")
                        saw_batch = True
                        break
        self.assertTrue(saw_batch)
        self.assertEqual(self.kwic_mock.call_count, 0)

    def test_query_stream_does_not_start_background_count_for_limited_plain_fastpath(self):
        current_event: str | None = None
        saw_batch = False
        prepared = ("the", __import__("numpy").array([0, 8], dtype="uint32"), 2, False)
        rendered_batches = [
            [{"left": "", "kw": "the", "right": "quick", "pos": 0, "doc_id": 0, "doc": "d0", "meta": {}}],
            [{"left": "dog", "kw": "the", "right": "", "pos": 8, "doc_id": 1, "doc": "d1", "meta": {}}],
        ]
        count_mock = AsyncMock(return_value=None)
        with patch(
            "candyconc.services.backend.server._prepare_cql_rows_fast",
            return_value=None,
        ), patch(
            "candyconc.services.backend.server._prepare_plain_rows_fast",
            return_value=prepared,
        ), patch(
            "candyconc.services.backend.server._render_fast_rows_for_positions",
            side_effect=rendered_batches,
        ), patch(
            "candyconc.services.backend.server._get_or_create_query_count",
            new=count_mock,
        ):
            with self.client.stream(
                "GET",
                "/api/v1/query/stream",
                params={"term": "the", "ctx": 1, "batch_size": 1, "limit": 2},
            ) as resp:
                self.assertEqual(resp.status_code, 200)
                for raw_line in resp.iter_lines():
                    if raw_line is None:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if current_event == "batch" and line.startswith("data: "):
                        rows = json.loads(line[6:])
                        self.assertEqual(rows[0]["kw"], "the")
                        saw_batch = True
                        break
        self.assertTrue(saw_batch)
        self.assertTrue(count_mock.await_args_list)
        self.assertFalse(any(call.kwargs.get("create") for call in count_mock.await_args_list))

    def tearDown(self):
        self.kwic_patch.stop()
        self.doc_bounds_patch.stop()
        self.get_corpus_patch.stop()


if __name__ == "__main__":
    unittest.main()
