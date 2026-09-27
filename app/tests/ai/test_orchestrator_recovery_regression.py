import importlib.util
import sys
import types
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.ai._sysmod_guard import preserve_sys_modules

#: Production-name sys.modules entries the loader below replaces/pops; they
#: are restored after the load so no other test module observes the stubs
#: (cross-directory isolation: tests/backend patches dotted candyconc paths).
#:
#: The ``candyconc_copilot.*`` top-level aliases MUST be preserved too: the
#: loader REPLACES the package object (dropping conftest attributes like
#: ``scientific_agent``/``_lm_chat_async``) and installs private real modules
#: under the alias names; without preservation those leak order-dependently
#: into later-collected test modules (and ``relink_parent_attrs`` would weld
#: them onto the conftest package at guard exit).
_TOUCHED_PRODUCTION_MODULES = (
    "candyconc",
    "candyconc.tooling",
    "candyconc.tooling.registry",
    "candyconc.services",
    "candyconc.services.backend",
    "candyconc.services.llm_client",
    "candyconc.project",
    "fastapi",
    "candyconc_copilot",
    "candyconc_copilot.session_manager",
    "candyconc_copilot.policy_engine",
    "candyconc_copilot.observability",
    "candyconc_copilot.prompts",
    "candyconc_copilot.orchestrator",
)


class _FakeEventBus:
    def __init__(self) -> None:
        self.outputs = []

    def clear(self) -> None:
        self.outputs.clear()

    def publish(self, payload, session_id=None):
        self.outputs.append(payload)


_FAKE_EVENT_BUS = _FakeEventBus()


def _load_orchestrator():
    root = Path(__file__).resolve().parents[2]
    orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
    prompts_path = root / "src" / "candyconc" / "candyconc_copilot" / "prompts.py"
    src_path = root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    candyconc_pkg = types.ModuleType("candyconc")
    candyconc_pkg.__path__ = [str(root / "src" / "candyconc")]
    sys.modules["candyconc"] = candyconc_pkg

    package = types.ModuleType("candyconc_copilot")
    package.__path__ = [str(root / "src" / "candyconc" / "candyconc_copilot")]
    sys.modules["candyconc_copilot"] = package

    if "fastapi" not in sys.modules:
        fastapi_module = types.ModuleType("fastapi")

        class _HTTPException(Exception):
            def __init__(self, status_code: int = 0, detail: str = ""):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        fastapi_module.HTTPException = _HTTPException
        sys.modules["fastapi"] = fastapi_module

    tooling_pkg = sys.modules.get("candyconc.tooling")
    if tooling_pkg is None:
        tooling_pkg = types.ModuleType("candyconc.tooling")
        tooling_pkg.__path__ = [str(root / "src" / "candyconc" / "tooling")]
        sys.modules["candyconc.tooling"] = tooling_pkg
    if "candyconc.tooling.registry" not in sys.modules:
        registry_module = types.ModuleType("candyconc.tooling.registry")

        def get_tool_runtime_info():
            return {
                "document_search": {"read_only": True},
                "semantic_search": {"read_only": True},
                "documentation_search": {"read_only": True},
            }

        registry_module.get_tool_runtime_info = get_tool_runtime_info
        sys.modules["candyconc.tooling.registry"] = registry_module

    services_pkg = types.ModuleType("candyconc.services")
    services_pkg.__path__ = [str(root / "src" / "candyconc" / "services")]
    sys.modules["candyconc.services"] = services_pkg
    candyconc_pkg.services = services_pkg

    llm_client_module = types.ModuleType("candyconc.services.llm_client")

    class LLMErrorKind:
        CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
        MAX_OUTPUT_TOKENS = "max_output_tokens"
        TRANSIENT = "transient"
        CAPABILITY_MISMATCH = "capability_mismatch"
        MEDIA_UNSUPPORTED = "media_unsupported"

    class LLMRequestError(Exception):
        def __init__(
            self,
            *,
            kind=LLMErrorKind.TRANSIENT,
            message="",
            retryable=False,
            model=None,
            route=None,
            detail=None,
        ):
            super().__init__(message)
            self.kind = kind
            self.message = message
            self.detail = detail or message
            self.retryable = retryable
            self.model = model
            self.route = route

    llm_client_module.LLMErrorKind = LLMErrorKind
    llm_client_module.LLMRequestError = LLMRequestError
    sys.modules["candyconc.services.llm_client"] = llm_client_module

    backend_module = types.ModuleType("candyconc.services.backend")
    backend_module.copilot_event_bus = _FAKE_EVENT_BUS
    sys.modules["candyconc.services.backend"] = backend_module
    services_pkg.backend = backend_module

    project_module = types.ModuleType("candyconc.project")

    class _Project:
        pass

    project_module.Project = _Project
    sys.modules["candyconc.project"] = project_module

    for mod_name in [
        "candyconc_copilot.session_manager",
        "candyconc_copilot.policy_engine",
        "candyconc_copilot.observability",
        "candyconc_copilot.prompts",
    ]:
        path = (
            prompts_path
            if mod_name == "candyconc_copilot.prompts"
            else root / "src" / "candyconc" / "candyconc_copilot" / f"{mod_name.split('.')[-1]}.py"
        )
        spec = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        sys.modules[mod_name] = module

    orch_spec = importlib.util.spec_from_file_location(
        "candyconc_copilot.orchestrator",
        orch_path,
    )
    orch_module = importlib.util.module_from_spec(orch_spec)
    assert orch_spec and orch_spec.loader
    orch_spec.loader.exec_module(orch_module)  # type: ignore[arg-type]
    sys.modules["candyconc_copilot.orchestrator"] = orch_module
    return orch_module


with preserve_sys_modules(_TOUCHED_PRODUCTION_MODULES):
    orch_module = _load_orchestrator()
ReActOrchestrator = orch_module.ReActOrchestrator
# Bind the SAME exception classes the privately loaded orchestrator caught at
# exec time (the loader's llm_client stub) — the sys.modules entry is restored
# to the real module by the guard above, so it must not be consulted here.
LLMErrorKind = orch_module.LLMErrorKind
LLMRequestError = orch_module.LLMRequestError


def _dispatch(*args, **kwargs):
    return {"status": "ok"}


class TestOrchestratorRecoveryRegression(unittest.IsolatedAsyncioTestCase):
    _MISSING = object()

    def setUp(self) -> None:
        _FAKE_EVENT_BUS.clear()
        # Snapshot for tearDown: the fake backend must not outlive the test
        # (tests/backend resolves candyconc.services.backend.* dotted paths).
        self._had_backend = "candyconc.services.backend" in sys.modules
        self._prev_backend = sys.modules.get("candyconc.services.backend")
        backend_module = types.ModuleType("candyconc.services.backend")
        backend_module.__package__ = "candyconc.services"
        backend_module.__path__ = []
        backend_module.copilot_event_bus = _FAKE_EVENT_BUS
        sys.modules["candyconc.services.backend"] = backend_module
        services_pkg = sys.modules.get("candyconc.services")
        self._services_pkg = services_pkg
        self._prev_backend_attr = getattr(services_pkg, "backend", self._MISSING)
        if services_pkg is not None:
            services_pkg.backend = backend_module

    def tearDown(self) -> None:
        if self._had_backend:
            sys.modules["candyconc.services.backend"] = self._prev_backend
        else:
            sys.modules.pop("candyconc.services.backend", None)
        if self._services_pkg is not None:
            if self._prev_backend_attr is self._MISSING:
                try:
                    delattr(self._services_pkg, "backend")
                except AttributeError:
                    pass
            else:
                self._services_pkg.backend = self._prev_backend_attr

    async def test_context_recovery_records_route_and_model_then_switches(self):
        attempts = {"count": 0}

        async def call_llm(messages, tools, stream=False, **kwargs):
            if messages and str(messages[0].get("content", "")).startswith(
                "Ordne die folgende korpuslinguistische Nutzerfrage"
            ):
                # H9/C1 Router-Klassifikator (Stufe 2): 'frei' antworten,
                # ohne den gescripteten Versuchszaehler zu beruehren.
                return {"choices": [{"message": {"content": "frei"}}]}
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise LLMRequestError(
                    kind=LLMErrorKind.CONTEXT_WINDOW_EXCEEDED,
                    message="Kontextfenster zu klein",
                    retryable=True,
                    model="small-model",
                    route="chat:small",
                )
            return {
                "_cc_model": "large-model",
                "_cc_route": "chat:large",
                "choices": [{"message": {"content": "fertig"}}],
            }

        orch = ReActOrchestrator([], call_llm, _dispatch, llm_retries=1)
        with patch.object(orch.session, "microcompact", return_value=True):
            result = await orch.run_async("Bitte weitermachen")

        self.assertEqual(result, "fertig")
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(orch._last_llm_model, "large-model")
        self.assertEqual(orch._last_llm_route, "chat:large")
        self.assertTrue(
            any(
                "microcompact" in entry and "small-model" in entry and "chat:small" in entry
                for entry in orch._recent_recoveries
            )
        )
        self.assertTrue(
            any(
                item.get("event") == "copilot.recovery"
                and item.get("recovery", {}).get("kind") == "microcompact"
                for item in _FAKE_EVENT_BUS.outputs
            )
        )

    async def test_output_resume_inserts_continue_note_and_recovery(self):
        responses = [
            {
                "_cc_model": "resume-model",
                "_cc_route": "chat:resume",
                "choices": [
                    {
                        "message": {"content": "Teil 1"},
                        "finish_reason": "length",
                    }
                ],
            },
            {
                "_cc_model": "resume-model",
                "_cc_route": "chat:resume",
                "choices": [
                    {
                        "message": {"content": "Teil 2"},
                        "finish_reason": "stop",
                    }
                ],
            },
        ]

        async def call_llm(messages, tools, stream=False, **kwargs):
            if messages and str(messages[0].get("content", "")).startswith(
                "Ordne die folgende korpuslinguistische Nutzerfrage"
            ):
                # H9/C1 Router-Klassifikator (Stufe 2): 'frei' antworten,
                # ohne die gescriptete Antwortfolge zu verbrauchen.
                return {"choices": [{"message": {"content": "frei"}}]}
            if not responses:
                raise AssertionError("Zu viele LLM-Aufrufe")
            return responses.pop(0)

        orch = ReActOrchestrator([], call_llm, _dispatch)
        result = await orch.run_async("Erzähle weiter")

        self.assertEqual(result, "Teil 2")
        assistant_messages = [
            str(msg.get("content", ""))
            for msg in orch.messages
            if msg.get("role") == "assistant"
        ]
        self.assertGreaterEqual(len(assistant_messages), 2)
        self.assertEqual(assistant_messages[-2:], ["Teil 1", "Teil 2"])
        self.assertTrue(
            any(
                "Ausgabelimit abgeschnitten" in str(msg.get("content", ""))
                for msg in orch.messages
                if msg.get("role") == "user"
            )
        )
        self.assertTrue(any("output_resume" in entry for entry in orch._recent_recoveries))
        self.assertTrue(
            any(
                item.get("event") == "copilot.recovery"
                and item.get("recovery", {}).get("kind") == "output_resume"
                for item in _FAKE_EVENT_BUS.outputs
            )
        )


if __name__ == "__main__":
    unittest.main()
