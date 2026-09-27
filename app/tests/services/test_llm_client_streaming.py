import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
import sys
import types
import importlib

root = Path(__file__).resolve().parents[2]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

candyconc_pkg = sys.modules.setdefault("candyconc", types.ModuleType("candyconc"))
candyconc_pkg.__path__ = [str(src / "candyconc")]  # type: ignore[attr-defined]
services_pkg = sys.modules.setdefault("candyconc.services", types.ModuleType("candyconc.services"))
services_pkg.__path__ = [str(src / "candyconc" / "services")]  # type: ignore[attr-defined]


def _module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


try:
    import fastapi  # noqa: F401
except Exception:
    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = _module("fastapi", HTTPException=_HTTPException)

try:
    import httpx  # noqa: F401
except Exception:
    class _HTTPStatusError(Exception):
        def __init__(self, message="", request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    class _AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    sys.modules["httpx"] = _module(
        "httpx",
        AsyncClient=_AsyncClient,
        HTTPStatusError=_HTTPStatusError,
        ConnectError=type("ConnectError", (Exception,), {}),
        TimeoutException=type("TimeoutException", (Exception,), {}),
        ReadError=type("ReadError", (Exception,), {}),
        WriteError=type("WriteError", (Exception,), {}),
        RemoteProtocolError=type("RemoteProtocolError", (Exception,), {}),
        PoolTimeout=type("PoolTimeout", (Exception,), {}),
    )

sys.modules.setdefault(
    "candyconc.logging_config",
    _module("candyconc.logging_config", init_logging=lambda: None),
)
sys.modules.setdefault(
    "candyconc.config",
    _module(
        "candyconc.config",
        APP_CONFIG=types.SimpleNamespace(
            COPILOT_MODEL="test-model",
            COPILOT_ENDPOINT="http://test/v1/chat/completions",
        ),
        get=lambda _key, default=None: default,
    ),
)
sys.modules.setdefault(
    "candyconc.candyconc_copilot.policy_engine",
    _module(
        "candyconc.candyconc_copilot.policy_engine",
        PolicyEngine=type("PolicyEngine", (), {}),
    ),
)
registry_mod = sys.modules.setdefault(
    "candyconc.tooling.registry",
    _module(
        "candyconc.tooling.registry",
        REGISTRY=[],
        get_schema_map=lambda: {},
        get_tool_runtime_info=lambda: {},
        llm_tool=lambda *_args, **_kwargs: (lambda fn: fn),
    ),
)
if not hasattr(registry_mod, "get_tools"):
    registry_mod.get_tools = lambda: []

sys.modules.pop("candyconc.services.llm_client", None)
llm_client = importlib.import_module("candyconc.services.llm_client")


class _FakeStreamResponse:
    def __init__(self, items, *, status_code=200):
        self._items = list(items)
        self.status_code = status_code
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def aiter_lines(self):
        for item in self._items:
            if isinstance(item, BaseException):
                raise item
            yield item


class _FakeAsyncClient:
    def __init__(self, responses, requested):
        self._responses = responses
        self._requested = requested

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, endpoint, json, timeout, headers=None):
        self._requested.append((method, endpoint, json.get("model")))
        if not self._responses:
            raise AssertionError("Keine weitere Fake-Stream-Antwort konfiguriert.")
        return self._responses.pop(0)


class _FakeModelsResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestLLMClientStreaming(unittest.IsolatedAsyncioTestCase):
    # Diese Tests prüfen die Modellprüfung selbst. tests/conftest.py schaltet
    # sie für alle übrigen Unit-Tests aus, hier ist sie eingeschaltet.
    def setUp(self):
        super().setUp()
        from candyconc import config

        self._modellpruefung_vorher = config.APP_CONFIG.CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL
        config.APP_CONFIG.CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL = True

    def tearDown(self):
        from candyconc import config

        config.APP_CONFIG.CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL = self._modellpruefung_vorher
        super().tearDown()

    def test_local_route_candidates_never_switch_from_requested_model(self):
        values = {
            "LM_STUDIO_TRANSPORT": "responses",
            "LM_STUDIO_FALLBACK_MODELS": "model-b",
        }

        with patch.object(
            llm_client,
            "get_config",
            lambda key, default=None: values.get(key, default),
        ):
            routes = llm_client._build_route_candidates(
                "http://127.0.0.1:1234/v1/responses",
                "model-a",
                [{"role": "user", "content": "Hallo"}],
                tools=[],
                json_schema=None,
            )

        self.assertEqual(
            [
                (route.model, llm_client._route_endpoint_kind(route.endpoint))
                for route in routes
            ],
            [
                ("model-a", "responses"),
                ("model-a", "chat_completions"),
            ],
        )

    def test_structured_turn_prefers_native_chat_schema_over_responses_hint(self):
        values = {
            "LM_STUDIO_TRANSPORT": "responses",
            "LM_STUDIO_FALLBACK_MODELS": "",
            "USE_STRUCTURED_OUTPUT": "1",
        }
        schema = {
            "name": "three_items",
            "schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {"type": "string"},
                    }
                },
                "required": ["items"],
            },
        }

        with patch.object(
            llm_client,
            "get_config",
            lambda key, default=None: values.get(key, default),
        ):
            routes = llm_client._build_route_candidates(
                "http://127.0.0.1:1234/v1/responses",
                "model-a",
                [{"role": "user", "content": "Drei Einträge."}],
                tools=[],
                json_schema=schema,
            )

        self.assertEqual(
            [
                (
                    llm_client._route_endpoint_kind(route.endpoint),
                    route.structured_mode,
                )
                for route in routes
            ],
            [
                ("chat_completions", "json_schema"),
                ("responses", "prompt_hint"),
                ("chat_completions", "prompt_hint"),
            ],
        )

    def test_llm_error_messages_keep_readable_german_umlauts(self):
        cases = [
            llm_client._classify_http_error(
                "http://test/v1/responses",
                types.SimpleNamespace(
                    response=types.SimpleNamespace(
                        status_code=400,
                        text="maximum context length exceeded",
                        headers={},
                    )
                ),
            ).message,
            llm_client._classify_http_error(
                "http://test/v1/responses",
                types.SimpleNamespace(
                    response=types.SimpleNamespace(
                        status_code=401,
                        text="unauthorized",
                        headers={},
                    )
                ),
            ).message,
            llm_client._classify_http_error(
                "http://test/v1/responses",
                types.SimpleNamespace(
                    response=types.SimpleNamespace(
                        status_code=529,
                        text="overloaded",
                        headers={},
                    )
                ),
            ).message,
            llm_client._invalid_response_error(
                "http://test/v1/responses",
                ValueError("bad json"),
            ).message,
        ]

        joined = "\n".join(cases)
        self.assertIn("überschreitet", joined)
        self.assertIn("Prüfe Schlüssel", joined)
        self.assertIn("überlastet", joined)
        self.assertIn("ungültiges JSON", joined)
        self.assertNotRegex(joined, r"[ÃÂ�]")

    def test_output_token_error_is_not_misclassified_as_context_overflow(self):
        error = llm_client._classify_http_error(
            "http://test/v1/responses",
            types.SimpleNamespace(
                response=types.SimpleNamespace(
                    status_code=400,
                    text="Unsupported parameter: max_output_tokens",
                    headers={},
                )
            ),
        )

        self.assertEqual(
            error.kind,
            llm_client.LLMErrorKind.MAX_OUTPUT_TOKENS,
        )

    async def test_local_lm_studio_preflight_rejects_unloaded_model(self):
        requested = []

        class _ModelsClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, endpoint, timeout, headers=None):
                requested.append((endpoint, timeout))
                return _FakeModelsResponse({"data": [{"id": "loaded-model"}]})

        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/responses",
            model="missing-model",
        )
        llm_client._LM_STUDIO_MODEL_CACHE.clear()
        with patch.object(llm_client.httpx, "AsyncClient", lambda *args, **kwargs: _ModelsClient()):
            with self.assertRaises(llm_client.LLMRequestError) as ctx:
                await llm_client._ensure_lm_studio_model_loaded(
                    route,
                    timeout=1.0,
                    headers=None,
                )
        self.assertEqual(ctx.exception.kind, llm_client.LLMErrorKind.MODEL_NOT_LOADED)
        self.assertIn("not currently loaded", ctx.exception.message)
        self.assertEqual(requested, [("http://127.0.0.1:1234/v1/models", 1.0)])

    async def test_non_local_endpoint_skips_lm_studio_preflight(self):
        class _NoGetClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *_args, **_kwargs):
                raise AssertionError("non-local endpoints must not call /models")

        route = llm_client._LLMRoute(
            endpoint="http://example.test/v1/responses",
            model="missing-model",
        )
        llm_client._LM_STUDIO_MODEL_CACHE.clear()
        with patch.object(llm_client.httpx, "AsyncClient", lambda *args, **kwargs: _NoGetClient()):
            await llm_client._ensure_lm_studio_model_loaded(route, timeout=1.0, headers=None)

    async def test_runtime_preflight_rejects_empty_lm_studio_models(self):
        seen = []

        def fake_get_config(key, default=None):
            values = {
                "COPILOT_ENDPOINT": "http://127.0.0.1:1234/v1/chat/completions",
                "COPILOT_MODEL": "qwen-test",
                "LM_STUDIO_TRANSPORT": "chat_completions",
                "CANDYCONC_LM_STUDIO_REQUIRE_LOADED_MODEL": True,
            }
            return values.get(key, default)

        async def fake_loaded_models(endpoint, **_kwargs):
            seen.append(endpoint)
            return frozenset()

        with patch.object(llm_client, "get_config", fake_get_config):
            with patch.object(llm_client, "_lm_studio_loaded_models", fake_loaded_models):
                with patch.object(
                    llm_client.asyncio,
                    "sleep",
                    AsyncMock(),
                ):
                    with self.assertRaises(llm_client.LLMRequestError) as ctx:
                        await llm_client.ensure_copilot_runtime_available(
                            [{"role": "user", "content": "Hi"}],
                            [],
                        )

        self.assertEqual(ctx.exception.kind, llm_client.LLMErrorKind.MODEL_NOT_LOADED)
        self.assertEqual(ctx.exception.model, "qwen-test")
        self.assertEqual(
            seen,
            ["http://127.0.0.1:1234/v1/chat/completions"] * 3,
        )

    async def test_model_preflight_tolerates_one_transient_empty_probe(self):
        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/responses",
            model="model-a",
        )
        replies = [
            frozenset(),
            frozenset({"model-a"}),
        ]

        async def fake_loaded_models(*_args, **_kwargs):
            return replies.pop(0)

        with patch.object(
            llm_client,
            "_lm_studio_loaded_models",
            fake_loaded_models,
        ):
            with patch.object(
                llm_client.asyncio,
                "sleep",
                AsyncMock(),
            ) as sleep:
                await llm_client._ensure_lm_studio_model_loaded(
                    route,
                    timeout=None,
                    headers=None,
                )

        sleep.assert_awaited_once_with(0.5)

    async def test_preflight_waits_for_confirmed_model_to_reappear(self):
        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/responses",
            model="model-a",
        )
        models_endpoint = "http://127.0.0.1:1234/v1/models"
        replies = [
            frozenset(),
            frozenset(),
            frozenset(),
            frozenset(),
            frozenset({"model-a"}),
        ]

        async def fake_loaded_models(*_args, **_kwargs):
            return replies.pop(0)

        llm_client._LM_STUDIO_LAST_CONFIRMED_MODELS[
            models_endpoint
        ] = frozenset({"model-a"})
        try:
            with patch.object(
                llm_client,
                "_lm_studio_loaded_models",
                fake_loaded_models,
            ):
                with patch.object(
                    llm_client.asyncio,
                    "sleep",
                    AsyncMock(),
                ) as sleep:
                    await llm_client._ensure_lm_studio_model_loaded(
                        route,
                        timeout=None,
                        headers=None,
                    )
        finally:
            llm_client._LM_STUDIO_LAST_CONFIRMED_MODELS.pop(
                models_endpoint,
                None,
            )

        self.assertEqual(sleep.await_count, 4)
        self.assertEqual(replies, [])

    async def test_confirmed_model_never_switches_to_another_loaded_model(self):
        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/responses",
            model="model-a",
        )
        models_endpoint = "http://127.0.0.1:1234/v1/models"

        async def fake_loaded_models(*_args, **_kwargs):
            return frozenset({"model-b"})

        llm_client._LM_STUDIO_LAST_CONFIRMED_MODELS[
            models_endpoint
        ] = frozenset({"model-a"})
        try:
            with patch.object(
                llm_client,
                "_lm_studio_loaded_models",
                fake_loaded_models,
            ):
                with self.assertRaises(
                    llm_client.LLMRequestError
                ) as ctx:
                    await llm_client._ensure_lm_studio_model_loaded(
                        route,
                        timeout=None,
                        headers=None,
                    )
        finally:
            llm_client._LM_STUDIO_LAST_CONFIRMED_MODELS.pop(
                models_endpoint,
                None,
            )

        self.assertEqual(
            ctx.exception.kind,
            llm_client.LLMErrorKind.MODEL_NOT_LOADED,
        )
        self.assertIn("not currently loaded", ctx.exception.message)

    async def test_model_not_loaded_does_not_fallback_to_other_loaded_model(self):
        routes = [
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/responses",
                model="model-a",
            ),
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/responses",
                model="model-b",
            ),
        ]

        async def fake_loaded_models(*_args, **_kwargs):
            return frozenset({"model-b"})

        async def fail_post(*_args, **_kwargs):
            raise AssertionError("POST must not run when requested model is not loaded")

        with patch.object(llm_client, "_lm_studio_loaded_models", fake_loaded_models):
            with patch.object(llm_client, "_post_json_with_retry", fail_post):
                with self.assertRaises(llm_client.LLMRequestError) as ctx:
                    await llm_client._post_with_route_fallback(
                        routes,
                        [],
                        [],
                        timeout=1.0,
                        headers=None,
                    )

        self.assertEqual(ctx.exception.kind, llm_client.LLMErrorKind.MODEL_NOT_LOADED)
        self.assertEqual(ctx.exception.model, "model-a")

    async def test_loaded_local_model_allows_post(self):
        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/chat/completions",
            model="model-a",
        )
        posted = []

        async def fake_loaded_models(*_args, **_kwargs):
            return frozenset({"model-a"})

        async def fake_post(endpoint, payload, **_kwargs):
            posted.append((endpoint, payload.get("model")))
            return {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(llm_client, "_lm_studio_loaded_models", fake_loaded_models):
            with patch.object(llm_client, "_post_json_with_retry", fake_post):
                selected, data = await llm_client._post_with_route_fallback(
                    [route],
                    [{"role": "user", "content": "Hi"}],
                    [],
                    timeout=1.0,
                    headers=None,
                )

        self.assertEqual(selected, route)
        self.assertEqual(posted, [("http://127.0.0.1:1234/v1/chat/completions", "model-a")])
        self.assertEqual(data["choices"][0]["message"]["content"], "ok")

    async def test_stream_with_route_fallback_attaches_route_meta(self):
        route = llm_client._LLMRoute(
            endpoint="http://test/v1/chat/completions",
            model="model-a",
        )

        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {"choices": [{"delta": {"role": "assistant"}}]}
            yield {"choices": [{"delta": {"content": "Hallo"}, "finish_reason": "stop"}]}

        with patch.object(llm_client, "_stream_json_with_retry", fake_stream_json_with_retry):
            chunks = [
                chunk
                async for chunk in llm_client._stream_with_route_fallback(
                    [route],
                    [],
                    [],
                    timeout=1.0,
                    headers=None,
                )
            ]

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(chunk.get("_cc_model") == "model-a" for chunk in chunks))
        self.assertTrue(
            all(chunk.get("_cc_route") == llm_client._describe_route(route) for chunk in chunks)
        )

    async def test_buffered_responses_stream_returns_completed_response(self):
        completed = {
            "id": "resp_123",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Hallo"}],
                }
            ],
        }

        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {"type": "response.created", "response": {"id": "resp_123"}}
            yield {"type": "response.reasoning_text.delta", "delta": "Gedanke"}
            yield {"type": "response.completed", "response": completed}

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            result = await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "model-a", "stream": True},
                timeout=None,
                headers=None,
            )

        self.assertEqual(result, completed)

    async def test_buffered_responses_stream_logs_long_running_progress(self):
        completed = {
            "id": "resp_123",
            "status": "completed",
            "output": [],
        }

        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {"type": "response.created", "response": {"id": "resp_123"}}
            yield {"type": "response.completed", "response": completed}

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ), patch.object(
            llm_client.time,
            "monotonic",
            side_effect=[0.0, 61.0, 62.0],
        ), patch.object(llm_client.logger, "warning") as warning:
            result = await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {
                    "model": "model-a",
                    "stream": True,
                    "max_output_tokens": 16384,
                },
                timeout=None,
                headers=None,
            )

        self.assertEqual(result, completed)
        warning.assert_called_once()
        self.assertIn(
            "Responses stream still active",
            warning.call_args.args[0],
        )

    async def test_buffered_responses_stream_returns_incomplete_response(self):
        incomplete = {
            "id": "resp_123",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        }

        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {"type": "response.created", "response": {"id": "resp_123"}}
            yield {"type": "response.incomplete", "response": incomplete}

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            result = await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "model-a", "stream": True},
                timeout=None,
                headers=None,
            )

        self.assertEqual(result, incomplete)
        wrapped = llm_client._wrap_responses_api(result)
        self.assertEqual(wrapped["choices"][0]["finish_reason"], "length")

    def test_incomplete_responses_tool_call_is_not_executable(self):
        wrapped = llm_client._wrap_responses_api(
            {
                "id": "resp_cut",
                "status": "incomplete",
                "output": [
                    {
                        "type": "function_call",
                        "status": "incomplete",
                        "name": "frequency_list",
                        "arguments": "{\"group_by\":\"word\"",
                        "call_id": "call_cut",
                    }
                ],
            }
        )

        choice = wrapped["choices"][0]
        self.assertEqual(choice["finish_reason"], "length")
        self.assertNotIn("tool_calls", choice["message"])
        self.assertEqual(
            wrapped["_cc_discarded_incomplete_tool_calls"],
            1,
        )

    def test_completed_call_survives_an_incomplete_later_response_item(self):
        wrapped = llm_client._wrap_responses_api(
            {
                "id": "resp_cut_after_call",
                "status": "incomplete",
                "output": [
                    {
                        "type": "function_call",
                        "status": "completed",
                        "name": "frequency_list",
                        "arguments": "{\"group_by\":\"word\"}",
                        "call_id": "call_complete",
                    }
                ],
            }
        )

        choice = wrapped["choices"][0]
        self.assertEqual(choice["finish_reason"], "length")
        self.assertEqual(
            choice["message"]["tool_calls"][0]["function"]["name"],
            "frequency_list",
        )

    async def test_buffered_responses_stream_rejects_missing_completion(self):
        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {"type": "response.created", "response": {"id": "resp_123"}}

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            with self.assertRaises(llm_client.LLMRequestError) as ctx:
                await llm_client._post_responses_stream_buffered(
                    "http://127.0.0.1:1234/v1/responses",
                    {"model": "model-a", "stream": True},
                    timeout=None,
                    headers=None,
                )

        self.assertEqual(
            ctx.exception.kind,
            llm_client.LLMErrorKind.INVALID_RESPONSE,
        )

    async def test_buffered_responses_stream_recovers_terminal_text_without_completion(self):
        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {
                "type": "response.created",
                "response": {"id": "resp_123", "status": "in_progress"},
            }
            yield {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "msg_123",
                    "type": "message",
                    "role": "assistant",
                    "status": "in_progress",
                    "content": [],
                },
            }
            yield {
                "type": "response.output_text.done",
                "output_index": 0,
                "content_index": 0,
                "item_id": "msg_123",
                "text": "{\"claims\": []}",
            }

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            result = await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "model-a", "stream": True},
                timeout=None,
                headers=None,
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"][0]["status"], "completed")
        self.assertEqual(
            llm_client._wrap_responses_api(result)["choices"][0]["message"][
                "content"
            ],
            "{\"claims\": []}",
        )

    async def test_buffered_responses_stream_recovers_done_function_call(self):
        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": "fc_123",
                    "call_id": "call_123",
                    "type": "function_call",
                    "name": "frequency_list",
                    "arguments": "",
                    "status": "in_progress",
                },
            }
            yield {
                "type": "response.function_call_arguments.done",
                "output_index": 0,
                "item_id": "fc_123",
                "arguments": "{\"group_by\":\"word\"}",
            }

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            result = await llm_client._post_responses_stream_buffered(
                "http://127.0.0.1:1234/v1/responses",
                {"model": "model-a", "stream": True},
                timeout=None,
                headers=None,
            )

        wrapped = llm_client._wrap_responses_api(result)
        self.assertEqual(
            wrapped["choices"][0]["message"]["tool_calls"][0]["function"][
                "name"
            ],
            "frequency_list",
        )

    async def test_local_responses_route_uses_buffered_stream_by_default(self):
        route = llm_client._LLMRoute(
            endpoint="http://127.0.0.1:1234/v1/responses",
            model="model-a",
        )
        seen = []

        async def fake_preflight(*args, **kwargs):
            return None

        async def fake_buffered(endpoint, payload, **kwargs):
            seen.append((endpoint, payload))
            return {"id": "resp_123", "status": "completed", "output": []}

        async def fail_regular_post(*args, **kwargs):
            raise AssertionError("local Responses calls should use buffered SSE")

        with patch.object(
            llm_client,
            "_ensure_lm_studio_model_loaded",
            fake_preflight,
        ):
            with patch.object(
                llm_client,
                "_post_responses_stream_buffered",
                fake_buffered,
            ):
                with patch.object(
                    llm_client,
                    "_post_json_with_retry",
                    fail_regular_post,
                ):
                    selected, result = await llm_client._post_with_route_fallback(
                        [route],
                        [{"role": "user", "content": "Hallo"}],
                        [],
                        timeout=None,
                        headers=None,
                    )

        self.assertEqual(selected, route)
        self.assertEqual(result["id"], "resp_123")
        self.assertTrue(seen[0][1]["stream"])

    async def test_failed_buffered_responses_stream_falls_back_to_same_model_chat(self):
        routes = [
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/responses",
                model="model-a",
            ),
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/chat/completions",
                model="model-a",
            ),
        ]
        fallback_calls = []

        async def fake_preflight(*args, **kwargs):
            return None

        async def fail_buffered_stream(*args, **kwargs):
            raise llm_client.LLMRequestError(
                kind=llm_client.LLMErrorKind.INVALID_RESPONSE,
                message="Responses-Protokoll konnte die Ausgabe nicht parsen",
            )

        async def record_fallback(*args, **kwargs):
            fallback_calls.append(True)
            return {"choices": [{"message": {"content": "ok"}}]}

        with patch.object(
            llm_client,
            "_ensure_lm_studio_model_loaded",
            fake_preflight,
        ):
            with patch.object(
                llm_client,
                "_post_responses_stream_buffered",
                fail_buffered_stream,
            ):
                with patch.object(
                    llm_client,
                    "_post_json_with_retry",
                    record_fallback,
                ):
                    selected, result = await llm_client._post_with_route_fallback(
                        routes,
                        [{"role": "user", "content": "Hallo"}],
                        [],
                        timeout=None,
                        headers=None,
                    )

        self.assertEqual(selected, routes[1])
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(fallback_calls, [True])

    async def test_engine_failure_does_not_fallback_to_same_model_chat(self):
        routes = [
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/responses",
                model="model-a",
            ),
            llm_client._LLMRoute(
                endpoint="http://127.0.0.1:1234/v1/chat/completions",
                model="model-a",
            ),
        ]

        async def fake_preflight(*args, **kwargs):
            return None

        async def fail_engine(*args, **kwargs):
            raise llm_client.LLMRequestError(
                kind=llm_client.LLMErrorKind.ENGINE_UNAVAILABLE,
                message="engine unavailable",
            )

        async def unexpected_fallback(*args, **kwargs):
            raise AssertionError("Eine ausgefallene Engine ist kein Transport-Fallback.")

        with patch.object(
            llm_client,
            "_ensure_lm_studio_model_loaded",
            fake_preflight,
        ):
            with patch.object(
                llm_client,
                "_post_responses_stream_buffered",
                fail_engine,
            ):
                with patch.object(
                    llm_client,
                    "_post_json_with_retry",
                    unexpected_fallback,
                ):
                    with self.assertRaises(llm_client.LLMRequestError) as ctx:
                        await llm_client._post_with_route_fallback(
                            routes,
                            [{"role": "user", "content": "Hallo"}],
                            [],
                            timeout=None,
                            headers=None,
                        )

        self.assertEqual(
            ctx.exception.kind,
            llm_client.LLMErrorKind.ENGINE_UNAVAILABLE,
        )

    async def test_stream_http_error_reads_body_before_classification(self):
        import httpx

        attempts = 0

        def handle(request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                500,
                text="engine protocol predict stream returned an error",
                request=request,
            )

        real_async_client = httpx.AsyncClient
        transport = httpx.MockTransport(handle)

        with patch.object(
            llm_client.httpx,
            "AsyncClient",
            lambda *args, **kwargs: real_async_client(transport=transport),
        ):
            with self.assertRaises(llm_client.LLMRequestError) as ctx:
                async for _chunk in llm_client._stream_json_with_retry(
                    "http://test/v1/responses",
                    {"model": "model-a", "stream": True},
                    timeout=None,
                    headers=None,
                    max_retries=3,
                ):
                    pass

        self.assertEqual(
            ctx.exception.kind,
            llm_client.LLMErrorKind.ENGINE_UNAVAILABLE,
        )
        self.assertIn("engine protocol", ctx.exception.body)
        self.assertEqual(attempts, 1)

    async def test_buffered_responses_channel_error_is_engine_failure(self):
        async def fake_stream_json_with_retry(*args, **kwargs):
            yield {
                "type": "error",
                "error": {"message": "Channel Error"},
            }

        with patch.object(
            llm_client,
            "_stream_json_with_retry",
            fake_stream_json_with_retry,
        ):
            with self.assertRaises(llm_client.LLMRequestError) as ctx:
                await llm_client._post_responses_stream_buffered(
                    "http://127.0.0.1:1234/v1/responses",
                    {"model": "model-a", "stream": True},
                    timeout=None,
                    headers=None,
                )

        self.assertEqual(
            ctx.exception.kind,
            llm_client.LLMErrorKind.ENGINE_UNAVAILABLE,
        )
        self.assertIn("Channel Error", ctx.exception.body)

    async def test_stream_retries_lm_link_400_after_same_model_reappears(self):
        import httpx

        messages = (
            "LM Link connection entered error state peer_keepalive_timeout",
            "LM Link connection closed",
            "Connector is closed",
        )
        for message in messages:
            with self.subTest(message=message):
                attempts = 0

                def handle(request):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        return httpx.Response(
                            400,
                            json={"error": message},
                            request=request,
                        )
                    return httpx.Response(
                        200,
                        text=(
                            'data: {"type":"response.completed","response":{"id":"resp_1"}}\n\n'
                            "data: [DONE]\n\n"
                        ),
                        request=request,
                    )

                real_async_client = httpx.AsyncClient
                transport = httpx.MockTransport(handle)
                with patch.object(
                    llm_client.httpx,
                    "AsyncClient",
                    lambda *args, **kwargs: real_async_client(
                        transport=transport
                    ),
                ), patch.object(
                    llm_client,
                    "_wait_for_same_model_after_lm_link_disconnect",
                    AsyncMock(),
                ) as wait_for_model, patch.object(
                    llm_client.asyncio,
                    "sleep",
                    AsyncMock(),
                ) as sleep:
                    chunks = [
                        chunk
                        async for chunk in llm_client._stream_json_with_retry(
                            "http://127.0.0.1:1234/v1/responses",
                            {"model": "model-a", "stream": True},
                            timeout=None,
                            headers=None,
                            max_retries=1,
                        )
                    ]

                self.assertEqual(attempts, 2)
                self.assertEqual(chunks[0]["type"], "response.completed")
                wait_for_model.assert_awaited_once()
                sleep.assert_awaited_once()

    async def test_stream_json_with_retry_stops_retrying_after_tool_only_partial_output(self):
        requested = []
        responses = [
            _FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"lookup_term","arguments":"{}"}}]}}]}',
                    RuntimeError("kaputter Stream"),
                ]
            ),
            _FakeStreamResponse(
                [
                    'data: {"choices":[{"delta":{"content":"sollte nicht erneut gelesen werden"}}]}',
                    "data: [DONE]",
                ]
            ),
        ]

        def fake_async_client(*args, **kwargs):
            return _FakeAsyncClient(responses, requested)

        with patch.object(llm_client.httpx, "AsyncClient", fake_async_client):
            with patch.object(
                llm_client,
                "_is_retryable_exception",
                side_effect=lambda exc: isinstance(exc, RuntimeError),
            ):
                agen = llm_client._stream_json_with_retry(
                    "http://test/v1/chat/completions",
                    {"model": "model-a", "stream": True},
                    timeout=1.0,
                    headers=None,
                    max_retries=1,
                )
                first = await agen.__anext__()
                self.assertIn("tool_calls", first["choices"][0]["delta"])
                with self.assertRaises(llm_client.LLMRequestError):
                    await agen.__anext__()

        self.assertEqual(len(requested), 1)


if __name__ == "__main__":
    unittest.main()
