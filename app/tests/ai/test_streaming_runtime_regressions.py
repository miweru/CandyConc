import importlib.util
from pathlib import Path
import sys
import types
import unittest


root = Path(__file__).resolve().parents[2]
package_root = root / "src" / "candyconc" / "candyconc_copilot"


def _module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


pkg = sys.modules.setdefault("candyconc_copilot", types.ModuleType("candyconc_copilot"))
pkg.__path__ = [str(package_root)]  # type: ignore[attr-defined]
if "fastapi" not in sys.modules:
    class _HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    sys.modules["fastapi"] = _module("fastapi", HTTPException=_HTTPException)

candyconc_pkg = sys.modules.setdefault("candyconc", types.ModuleType("candyconc"))
candyconc_pkg.__path__ = [str(root / "src" / "candyconc")]  # type: ignore[attr-defined]
core_pkg = sys.modules.setdefault("candyconc.core", types.ModuleType("candyconc.core"))
lineage_mod = sys.modules.setdefault(
    "candyconc.core.lineage",
    _module("candyconc.core.lineage", log_tool=lambda *args, **kwargs: None),
)
core_pkg.lineage = lineage_mod
tooling_pkg = sys.modules.setdefault("candyconc.tooling", types.ModuleType("candyconc.tooling"))
tooling_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault(
    "candyconc.tooling.registry",
    _module("candyconc.tooling.registry", get_tool_runtime_info=lambda *args, **kwargs: {}),
)
services_pkg = sys.modules.setdefault("candyconc.services", types.ModuleType("candyconc.services"))
services_pkg.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault(
    "candyconc.services.llm_client",
    _module(
        "candyconc.services.llm_client",
        LLMErrorKind=types.SimpleNamespace(
            CONTEXT_WINDOW_EXCEEDED="context_window_exceeded",
            MAX_OUTPUT_TOKENS="max_output_tokens",
        ),
        LLMRequestError=Exception,
    ),
)
backend_mod = sys.modules.setdefault(
    "candyconc.services.backend",
    types.ModuleType("candyconc.services.backend"),
)
if not hasattr(backend_mod, "copilot_event_bus"):
    backend_mod.copilot_event_bus = types.SimpleNamespace(publish=lambda *args, **kwargs: None)
orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
spec = importlib.util.spec_from_file_location("candyconc_copilot.orchestrator", orch_path)
orch_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["candyconc_copilot.prompts"] = _module(
    "candyconc_copilot.prompts",
    get_system_prompt=lambda: "",
    get_system_prompt_with_context=lambda _context=None: "",
    parse_control_frame=lambda _content: None,
    extract_all_control_frames=lambda _content: [],
    remove_control_frames=lambda content: content,
)


class _PolicyEngine:
    def __init__(self, *args, **kwargs):
        self.project = kwargs.get("project")

    def get(self, _user, _key, default=None):
        return default

    def check(self, _role, _tool, _tokens):
        return {"status": "ok"}


class _Observability:
    def record(self, *args, **kwargs):
        return None


sys.modules["candyconc_copilot.policy_engine"] = _module(
    "candyconc_copilot.policy_engine",
    PolicyEngine=_PolicyEngine,
)
sys.modules["candyconc_copilot.observability"] = _module(
    "candyconc_copilot.observability",
    Observability=_Observability,
)
for mod_name in [
    "candyconc_copilot.memory_store",
    "candyconc_copilot.session_manager",
]:
    path = root / "src" / "candyconc" / "candyconc_copilot" / f"{mod_name.split('.')[-1]}.py"
    m_spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(m_spec)
    assert m_spec and m_spec.loader
    m_spec.loader.exec_module(module)  # type: ignore[arg-type]
    sys.modules[mod_name] = module
spec.loader.exec_module(orch_module)  # type: ignore[arg-type]
ReActOrchestrator = orch_module.ReActOrchestrator


class TestStreamingRuntimeRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_tool_call_deltas_are_merged_and_route_meta_is_preserved(self):
        tool = {
            "type": "function",
            "function": {
                "name": "lookup_term",
                "parameters": {
                    "type": "object",
                    "properties": {"term": {"type": "string"}},
                    "required": ["term"],
                },
            },
            "schema": {
                "type": "object",
                "properties": {"term": {"type": "string"}},
                "required": ["term"],
            },
        }
        dispatched = []

        def _dispatch_tool(tool_call, _token):
            dispatched.append(tool_call)
            return {
                "status": "ok",
                "term": orch_module.ReActOrchestrator._tool_args(tool_call).get("term"),
            }

        async def _call_llm_stream(messages, tools, stream=False, **kwargs):
            has_tool_result = any(message.get("role") == "tool" for message in messages)
            if not has_tool_result:
                assert stream

                async def gen():
                    yield {
                        "_cc_route": "chat:fragmented",
                        "_cc_model": "local-qwen",
                        "choices": [{"delta": {"role": "assistant"}}],
                    }
                    yield {
                        "_cc_route": "chat:fragmented",
                        "_cc_model": "local-qwen",
                        "choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "lookup_"}}]}}],
                    }
                    yield {
                        "_cc_route": "chat:fragmented",
                        "_cc_model": "local-qwen",
                        "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "term", "arguments": "{\"term\":\"fo"}}]}}],
                    }
                    yield {
                        "_cc_route": "chat:fragmented",
                        "_cc_model": "local-qwen",
                        "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "x\"}"}}]}, "finish_reason": "tool_calls"}],
                    }

                return gen()

            assert stream

            async def done_gen():
                yield {
                    "_cc_route": "chat:fragmented",
                    "_cc_model": "local-qwen",
                    "choices": [{"delta": {"role": "assistant"}}],
                }
                yield {
                    "_cc_route": "chat:fragmented",
                    "_cc_model": "local-qwen",
                    "choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}],
                }

            return done_gen()

        orch = ReActOrchestrator([tool], _call_llm_stream, _dispatch_tool)
        # Disable the background research worker: _is_tool_read_only falls
        # back to GROUNDING_TRIGGER_TOOLS when _tool_runtime_info has no entry
        # (orchestrator.py:509-514), so with the empty registry stub above the
        # worker would dispatch document/semantic/documentation_search through
        # _dispatch_tool and break the merged-delta single-dispatch assertion.
        orch._tool_runtime_info = {
            name: {"read_only": False}
            for name in ("document_search", "semantic_search", "documentation_search")
        }
        result = await orch.run_async("hi", stream=True)

        self.assertEqual(result, "done")
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0]["function"]["name"], "lookup_term")
        self.assertEqual(
            orch_module.ReActOrchestrator._tool_args(dispatched[0]),
            {"term": "fox"},
        )
        self.assertEqual(orch._last_llm_route, "chat:fragmented")
        self.assertEqual(orch._last_llm_model, "local-qwen")
        runtime_state = orch._build_runtime_state("hi")
        self.assertIn("chat:fragmented", runtime_state["last_llm_route"])
        self.assertIn("local-qwen", runtime_state["last_llm_route"])


if __name__ == "__main__":
    unittest.main()
