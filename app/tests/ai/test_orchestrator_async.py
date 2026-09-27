import asyncio
import unittest
from unittest.mock import AsyncMock, patch
import importlib.util
from pathlib import Path
import types
import sys

import importlib

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local test env without fastapi
    TestClient = None

from tests.ai._sysmod_guard import preserve_sys_modules  # noqa: E402

#: Production-name sys.modules entries the module-level loader below
#: replaces/pops; restored once the private orchestrator is built so no other
#: test module observes the stubs (cross-directory isolation: tests/backend
#: patches dotted candyconc paths).
#:
#: The ``candyconc_copilot.*`` top-level aliases MUST be preserved too: the
#: loader overwrites them with private stubs/real modules, and a leaked entry
#: would be welded onto the conftest package by ``relink_parent_attrs`` at
#: guard exit (e.g. the SimpleNamespace ``prompts`` stub broke
#: ``test_system_prompt.py`` when this file was imported first).
_TOUCHED_PRODUCTION_MODULES = (
    "fastapi",
    "httpx",
    "candyconc",
    "candyconc.tooling",
    "candyconc.tooling.registry",
    "candyconc.services",
    "candyconc.services.backend",
    "candyconc.services.llm_client",
    "candyconc_copilot",
    "candyconc_copilot.prompts",
    "candyconc_copilot.session_manager",
    "candyconc_copilot.policy_engine",
    "candyconc_copilot.observability",
    "candyconc_copilot.orchestrator",
)
_sysmod_guard = preserve_sys_modules(_TOUCHED_PRODUCTION_MODULES)
_sysmod_guard.__enter__()

if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)

if "httpx" not in sys.modules:
    class _AsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    sys.modules["httpx"] = types.SimpleNamespace(
        AsyncClient=_AsyncClient,
        ConnectError=type("ConnectError", (Exception,), {}),
        TimeoutException=type("TimeoutException", (Exception,), {}),
        ReadError=type("ReadError", (Exception,), {}),
        WriteError=type("WriteError", (Exception,), {}),
        RemoteProtocolError=type("RemoteProtocolError", (Exception,), {}),
        PoolTimeout=type("PoolTimeout", (Exception,), {}),
        HTTPStatusError=type("HTTPStatusError", (Exception,), {}),
    )

sys.modules.pop("candyconc.services.backend", None)
sys.modules.pop("candyconc.services", None)

root = Path(__file__).resolve().parents[2]
candy_root = root / "src" / "candyconc"
candy_pkg = sys.modules.setdefault("candyconc", types.ModuleType("candyconc"))
candy_pkg.__path__ = [str(candy_root)]  # type: ignore[attr-defined]
tooling_pkg = sys.modules.setdefault("candyconc.tooling", types.ModuleType("candyconc.tooling"))
tooling_pkg.__path__ = []  # type: ignore[attr-defined]
tooling_pkg.get_tools = lambda: []
registry_mod = sys.modules.setdefault(
    "candyconc.tooling.registry",
    types.SimpleNamespace(
        REGISTRY=[],
        get_tools=lambda: [],
        get_schema_map=lambda: {},
        llm_tool=lambda *_args, **_kwargs: (lambda fn: fn),
    ),
)
registry_mod.get_tool_runtime_info = lambda *args, **kwargs: {}
services_pkg = sys.modules.setdefault("candyconc.services", types.ModuleType("candyconc.services"))
services_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules["candyconc.services.llm_client"] = types.SimpleNamespace(
    LLMErrorKind=types.SimpleNamespace(
        CONTEXT_WINDOW_EXCEEDED="context_window_exceeded",
        MAX_OUTPUT_TOKENS="max_output_tokens",
    ),
    LLMRequestError=Exception,
    call_llm_async=AsyncMock(return_value={"choices": [{"message": {"content": "{}"}}]}),
)
orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
package_root = root / "src" / "candyconc" / "candyconc_copilot"
spec = importlib.util.spec_from_file_location("candyconc_copilot.orchestrator", orch_path)
orch_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
pkg = sys.modules.setdefault("candyconc_copilot", types.ModuleType("candyconc_copilot"))
pkg.__path__ = [str(package_root)]  # type: ignore[attr-defined]
sys.modules["candyconc_copilot.prompts"] = types.SimpleNamespace(
    get_system_prompt=lambda: "",
    get_system_prompt_with_context=lambda _context=None: "",
    parse_control_frame=lambda _content: None,
    extract_all_control_frames=lambda _content: [],
    remove_control_frames=lambda content: content,
)
path = root / "src" / "candyconc" / "candyconc_copilot" / "session_manager.py"
m_spec = importlib.util.spec_from_file_location("candyconc_copilot.session_manager", path)
module = importlib.util.module_from_spec(m_spec)
assert m_spec and m_spec.loader
m_spec.loader.exec_module(module)  # type: ignore[arg-type]
sys.modules["candyconc_copilot.session_manager"] = module


class _PolicyEngine:
    def __init__(self, *args, **kwargs):
        self.project = kwargs.get("project")

    def get(self, _user, _key, default=None):
        return default

    def check(self, _role, _tool, _tokens):
        return {"status": "ok"}


class _Observability:
    def __init__(self, *args, **kwargs):
        pass

    def record(self, *args, **kwargs):
        # Real orchestrator records metrics for research/tool/LLM phases
        # (e.g. observability.record(session_id, "research.<phase>", ...)).
        return None

    def span(self, *args, **kwargs):
        class _Dummy:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def set_attribute(self, *a, **k):
                return None

        return _Dummy()

    def end_session(self, *_args, **_kwargs):
        return None


sys.modules["candyconc_copilot.policy_engine"] = types.SimpleNamespace(
    PolicyEngine=_PolicyEngine
)
sys.modules["candyconc_copilot.observability"] = types.SimpleNamespace(
    Observability=_Observability
)
spec.loader.exec_module(orch_module)  # type: ignore[arg-type]
ReActOrchestrator = orch_module.ReActOrchestrator
sys.modules["candyconc_copilot.orchestrator"] = orch_module

# Private orchestrator is built — restore the production-name entries before
# anything else (including the real server import below) resolves them.
_sysmod_guard.__exit__(None, None, None)

_BACKEND_TESTS_AVAILABLE = TestClient is not None
if _BACKEND_TESTS_AVAILABLE:
    try:
        server = importlib.import_module("candyconc.services.backend.server")
        app = server.app
    except ModuleNotFoundError:
        _BACKEND_TESTS_AVAILABLE = False
        server = None
        app = None
else:
    server = None
    app = None


def _call_llm(messages, tools, **kwargs):
    return {"choices": [{"message": {"content": "done"}}]}


def _dispatch(name, **kw):
    return {"status": "ok"}


class TestRunAsync(unittest.IsolatedAsyncioTestCase):
    async def test_basic_async_run(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        result = await orch.run_async("hi")
        self.assertEqual(result, "done")
        self.assertEqual(orch.state.name, "FINISHED")

    async def test_stop_after_llm_return_blocks_the_pending_tool_dispatch(self):
        llm_started = asyncio.Event()
        release_llm = asyncio.Event()
        dispatch_calls = []

        async def call_llm(_messages, _tools, **_kwargs):
            llm_started.set()
            await release_llm.wait()
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "frequency_list",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }

        async def dispatch(tool_call, _token):
            dispatch_calls.append(tool_call)
            return {"status": "ok"}

        orch = ReActOrchestrator(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "frequency_list",
                        "description": "test tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            call_llm,
            dispatch,
        )
        # Isolate the stop boundary from the separate grounding-contract path.
        orch._ra_requires_grounding_contract = lambda: False

        running = asyncio.create_task(orch.run_async("Zeige Frequenzen"))
        await llm_started.wait()
        orch.request_cancel()
        release_llm.set()

        self.assertEqual(await running, "")
        self.assertEqual(dispatch_calls, [])
        self.assertEqual(orch.state.name, "FINISHED")

    async def test_end_session_called(self):
        obs_mod = sys.modules["candyconc_copilot.observability"]
        try:
            obs = obs_mod.Observability(enable_otel=False)
        except TypeError:
            obs = obs_mod.Observability()

        class DummySpan:
            def __enter__(self):
                self.attrs = {}
                return self

            def __exit__(self, exc_type, exc, tb):
                self.finished = True
                return False

            def set_attribute(self, *a, **k):
                if len(a) >= 2:
                    key, value = a[0], a[1]
                elif "key" in k and "value" in k:
                    key, value = k["key"], k["value"]
                else:
                    return
                self.attrs[key] = value

        orch = ReActOrchestrator([], _call_llm, _dispatch, observability=obs)
        with patch.object(obs, "span", return_value=DummySpan(), create=True):
            with patch.object(obs, "end_session", create=True) as end_session:
                await orch.run_async("hi")
                end_session.assert_called_once_with(orch.session.session_id)

    async def test_streaming_async(self):
        async def _call_llm_stream(messages, tools, stream=False, **kwargs):
            if stream:
                async def gen():
                    yield {"choices": [{"delta": {"role": "assistant"}}]}
                    yield {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}
                return gen()
            return {"choices": [{"message": {"content": "done"}}]}

        orch = ReActOrchestrator([], _call_llm_stream, _dispatch)
        result = await orch.run_async("hi", stream=True)
        self.assertEqual(result, "done")

    async def test_empty_selected_tool_surface_never_launches_background_research(self):
        dispatched = []

        async def dispatch(tool_call, token=None):
            dispatched.append((tool_call, token))
            return {"status": "success"}

        orch = ReActOrchestrator([], _call_llm, dispatch)
        result = await orch.run_async("Recherchiere bitte den Begriff Wandel.")

        self.assertEqual(result, "done")
        self.assertFalse(
            orch._should_run_research_worker(
                "Recherchiere bitte den Begriff Wandel.", "user"
            )
        )
        self.assertEqual(dispatched, [])
        self.assertEqual(orch._research_runs, [])

    async def test_disable_background_research_prevents_sidecar_dispatch(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "document_search",
                    "description": "Search documents.",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        dispatched = []

        async def dispatch(tool_call, token=None):
            dispatched.append((tool_call, token))
            return {"status": "success"}

        orch = ReActOrchestrator(
            tools,
            _call_llm,
            dispatch,
            ui_context={"disable_background_research": True},
        )
        orch._tool_runtime_info = {
            "document_search": {"read_only": True, "concurrency_safe": True}
        }
        result = await orch.run_async("Recherchiere bitte den Begriff Wandel.")

        self.assertTrue(result)
        self.assertFalse(
            orch._should_run_research_worker(
                "Recherchiere bitte den Begriff Wandel.", "user"
            )
        )
        self.assertEqual(dispatched, [])
        self.assertEqual(orch._research_runs, [])


def _tool_call_llm(messages, tools, **kwargs):
    """Fake LLM: request one read-only tool, then finalize on the next turn.

    A ``tool`` role message in history (the dispatched tool result) signals the
    second turn, where the model stops with a final answer.
    """
    if any(m.get("role") == "tool" for m in messages):
        return {"choices": [{"message": {"content": "fertig"}, "finish_reason": "stop"}]}
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "type": "function",
                            "function": {"name": "frequency_list", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


class TestAutonomyPlanGate(unittest.IsolatedAsyncioTestCase):
    """id 16: low autonomy (0/1) pauses for approval BEFORE the first tool
    batch even for read-only tools; levels 2+ auto-execute as before."""

    _TOOL_SPECS = [
        {
            "type": "function",
            "function": {
                "name": "frequency_list",
                "description": "Frequency list.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    def _orch(self, autonomy):
        dispatched = []

        def _dispatch_record(tool_call, token=None):
            dispatched.append(tool_call["function"]["name"])
            return {"status": "ok", "rows": []}

        orch = ReActOrchestrator(
            list(self._TOOL_SPECS),
            _tool_call_llm,
            _dispatch_record,
            ui_context={"autonomy_level": autonomy},
        )
        orch._tool_runtime_info = {
            "frequency_list": {"read_only": True, "concurrency_safe": True}
        }
        events = []
        orch._emit_output = lambda _ai, event: events.append(event)
        return orch, events, dispatched

    async def test_low_autonomy_pauses_before_first_tool_batch(self):
        for level in (0, 1):
            with self.subTest(level=level):
                orch, events, dispatched = self._orch(level)
                await orch.run_async("Was sind die häufigsten Wörter?")
                names = {e.get("event") for e in events}
                # A plan + approval request is emitted and the turn pauses.
                self.assertIn("copilot.plan", names)
                self.assertIn("copilot.action_request", names)
                self.assertEqual(orch.state.name, "WAITING_APPROVAL")
                # No tool ran before approval (and no tool-execution event fired).
                self.assertEqual(dispatched, [])
                self.assertNotIn("start", names)
                self.assertIsNotNone(orch._pending_action)
                self.assertEqual(
                    orch._pending_action["type"],
                    orch._PLAN_GATE_ACTION_TYPE,
                )

    async def test_high_autonomy_auto_executes_first_tool_batch(self):
        orch, events, dispatched = self._orch(4)
        await orch.run_async("Was sind die häufigsten Wörter?")
        names = {e.get("event") for e in events}
        # No plan/approval gate at high autonomy: the tool runs immediately and
        # the turn never pauses in WAITING_APPROVAL.
        self.assertNotIn("copilot.action_request", names)
        self.assertIn("frequency_list", dispatched)
        self.assertNotEqual(orch.state.name, "WAITING_APPROVAL")
        self.assertIsNone(orch._pending_action)

    async def test_plan_gate_resumes_and_executes_after_approval(self):
        orch, events, dispatched = self._orch(0)
        await orch.run_async("Was sind die häufigsten Wörter?")
        self.assertEqual(orch.state.name, "WAITING_APPROVAL")
        self.assertEqual(dispatched, [])  # nothing ran before approval
        request_id = orch._pending_action["requestId"]
        # Approve -> resume: the gate is now satisfied, tools auto-execute.
        self.assertTrue(orch.approve_action(request_id))
        await orch.continue_after_approval()
        self.assertIn("frequency_list", dispatched)
        self.assertNotEqual(orch.state.name, "WAITING_APPROVAL")


@unittest.skipIf(not _BACKEND_TESTS_AVAILABLE, "Backend-Teststack lokal nicht verfügbar")
class TestChatUsesAsync(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        resp = self.client.post("/api/v1/login", json={"username": "bob", "password": "bob"})
        self.token = resp.json()["token"]
        self.username = server.auth.username_for_token(self.token)

    def test_chat_endpoint_runs_orchestrator_off_loop(self):
        # Real contract: the /chat endpoint executes the orchestrator via
        # ``await asyncio.to_thread(orch.run, question, role="user",
        # principal=username, max_steps=...)`` (chat endpoint) -- the event loop stays
        # free, but the synchronous ``run`` entrypoint is what gets invoked.
        payload = {"messages": [{"role": "user", "content": "hello"}]}
        with patch.object(
            server.ReActOrchestrator, "run", return_value="ok"
        ) as sync_run:
            resp = self.client.post(
                "/api/v1/chat", params={"token": self.token}, json=payload
            )
        self.assertEqual(resp.json().get("content"), "ok")
        sync_run.assert_called_once()
        args, kwargs = sync_run.call_args
        self.assertEqual(args[0], "hello")
        self.assertEqual(len(args), 1)
        self.assertEqual(kwargs["role"], "user")
        self.assertEqual(kwargs["principal"], self.username)
        self.assertIn("max_steps", kwargs)



if __name__ == "__main__":
    unittest.main()
