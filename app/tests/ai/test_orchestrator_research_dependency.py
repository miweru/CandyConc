import importlib.util
import sys
import types
from pathlib import Path
import unittest

from typing import Any, Dict, List

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


def _load_orchestrator():
    root = Path(__file__).resolve().parents[2]
    orch_path = root / "src" / "candyconc" / "candyconc_copilot" / "orchestrator.py"
    prompts_path = (
        root / "src" / "candyconc" / "candyconc_copilot" / "prompts.py"
    )
    src_path = root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    # Keep import side effects deterministic like the existing async orchestrator test.
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
    if "candyconc.services" not in sys.modules:
        services_pkg = types.ModuleType("candyconc.services")
        services_pkg.__path__ = [str(root / "src" / "candyconc" / "services")]
        sys.modules["candyconc.services"] = services_pkg
    if "candyconc.services.llm_client" not in sys.modules:
        llm_client_module = types.ModuleType("candyconc.services.llm_client")

        class LLMErrorKind:
            CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
            MAX_OUTPUT_TOKENS = "max_output_tokens"
            TRANSIENT = "transient"
            CAPABILITY_MISMATCH = "capability_mismatch"
            MEDIA_UNSUPPORTED = "media_unsupported"

        class LLMRequestError(Exception):
            def __init__(self, message="", *, kind=LLMErrorKind.TRANSIENT, detail=None):
                super().__init__(message)
                self.message = message
                self.detail = detail or message
                self.kind = kind

        llm_client_module.LLMErrorKind = LLMErrorKind
        llm_client_module.LLMRequestError = LLMRequestError
        sys.modules["candyconc.services.llm_client"] = llm_client_module
    sys.modules.pop("candyconc.services.backend", None)
    sys.modules.pop("candyconc.services", None)
    project_module = types.ModuleType("candyconc.project")
    if not hasattr(project_module, "Project"):
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
        if mod_name == "candyconc_copilot.prompts":
            path = prompts_path
        else:
            path = root / "src" / "candyconc" / "candyconc_copilot" / f"{mod_name.split('.')[-1]}.py"
        spec = importlib.util.spec_from_file_location(mod_name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        sys.modules[mod_name] = module

    orch_spec = importlib.util.spec_from_file_location(
        "candyconc_copilot.orchestrator", orch_path
    )
    orch_module = importlib.util.module_from_spec(orch_spec)
    assert orch_spec and orch_spec.loader
    orch_spec.loader.exec_module(orch_module)  # type: ignore[arg-type]
    sys.modules["candyconc_copilot.orchestrator"] = orch_module
    return orch_module


with preserve_sys_modules(_TOUCHED_PRODUCTION_MODULES):
    orch_module = _load_orchestrator()
ReActOrchestrator = orch_module.ReActOrchestrator


def _call_llm(messages, tools):
    return {"choices": [{"message": {"content": "ok"}}]}


def _dispatch(*args, **kwargs):
    return {"status": "ok"}


class TestOrchestratorResearchDependency(unittest.IsolatedAsyncioTestCase):
    def _orchestrator(self) -> ReActOrchestrator:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in (
                "document_search",
                "semantic_search",
                "documentation_search",
            )
        ]
        orch = ReActOrchestrator(tools, _call_llm, _dispatch)
        orch._tool_runtime_info = {
            "document_search": {"read_only": True},
            "semantic_search": {"read_only": True},
            "documentation_search": {"read_only": True},
        }
        return orch

    @staticmethod
    def _tool_name(tool_call: Dict[str, Any]) -> str:
        return str(tool_call.get("function", {}).get("name", "")).strip()

    def _run_tag(self, orchestrator: ReActOrchestrator, run_id: str) -> str:
        return orchestrator._research_run_tag({"id": run_id})

    def _research_run(self, run_id: str, status: str = "complete", dependencies: List[str] | None = None) -> Dict[str, Any]:
        return {
            "id": run_id,
            "status": status,
            "query": f"query-{run_id}",
            "context": {"corpus_id": "mock-corpus", "active_tab": "kwic"},
            "summaries": [f"summary-{run_id}"],
            "findings": 0,
            "tools": [],
            "dependencies": dependencies or [],
        }

    def test_closure_walks_dependency_graph(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)

        base = self._research_run("base_node_111", status="complete", dependencies=[])
        middle = self._research_run(
            "middle_2222",
            status="complete",
            dependencies=[orch._research_run_tag(base)],
        )
        leaf = self._research_run(
            "leaf_3333",
            status="complete",
            dependencies=[orch._research_run_tag(middle)],
        )
        orch._research_runs = [base, middle, leaf]

        tags = orch._collect_research_context_closure([orch._research_run_tag(leaf)])
        self.assertEqual(
            tags,
            [
                orch._research_run_tag(leaf),
                orch._research_run_tag(middle),
                orch._research_run_tag(base),
            ],
        )

    def test_runtime_state_only_includes_explicit_dependency_context(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        keep = self._research_run("keep_run__a", status="complete")
        other = self._research_run("other_run_b", status="complete")
        keep_tag = orch._research_run_tag(keep)
        other_tag = orch._research_run_tag(other)
        orch._research_runs = [other, keep]

        # Without an explicit context, no research context should leak into runtime state.
        state_without_keep = orch._build_runtime_state("Wie oft X?")
        self.assertEqual(state_without_keep["research_contexts"], [])
        self.assertEqual(state_without_keep["recent_research_findings"], [])
        self.assertEqual(state_without_keep["background_tasks"], [])

        # Explicitly keeping the relevant tag pulls only that run through the graph.
        orch._active_research_context_tags = [keep_tag]
        state_with_keep = orch._build_runtime_state("Wie oft X?")
        self.assertEqual(len(state_with_keep["research_contexts"]), 1)
        self.assertIn(orch._compact_runtime_text("query-keep_run__a", limit=180), state_with_keep["research_contexts"][0]["question"])

        # Explicit tag of an unrelated run selects only that run.
        orch._active_research_context_tags = [other_tag]
        state_other = orch._build_runtime_state("Wie oft X?")
        self.assertEqual(len(state_other["research_contexts"]), 1)
        self.assertIn(
            orch._compact_runtime_text("query-other_run_b", limit=180),
            state_other["research_contexts"][0]["question"],
        )

    def test_structured_research_context_exposes_explicit_dependencies(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        base = self._research_run("base_dep_1", status="complete")
        child = self._research_run(
            "childdep_2",
            status="complete",
            dependencies=[orch._research_run_tag(base)],
        )
        orch._research_runs = [base, child]
        orch._active_research_context_tags = [orch._research_run_tag(child)]

        state = orch._build_runtime_state("Führe den Forschungskontext fort")
        contexts = {item["task"]: item for item in state["research_contexts"]}
        self.assertEqual(contexts[orch._research_run_tag(base)].get("dependencies", []), [])
        self.assertEqual(
            contexts[orch._research_run_tag(child)].get("dependencies", []),
            [orch._research_run_tag(base)],
        )

    def test_reuse_lookup_is_tag_graph_driven(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        base = self._research_run("base_run_1", status="complete")
        followup = self._research_run("followup_1", status="complete", dependencies=[orch._research_run_tag(base)])
        unrelated = self._research_run("unrelated", status="complete")
        base_tag = orch._research_run_tag(base)
        followup_tag = orch._research_run_tag(followup)

        orch._research_runs = [base, followup, unrelated]

        orch._active_research_context_tags = [followup_tag]
        self.assertIs(orch._find_recent_research_run(), followup)

        orch._active_research_context_tags = [base_tag]
        self.assertIs(orch._find_recent_research_run(), base)

        orch._active_research_context_tags = [base_tag]
        self.assertIs(orch._find_recent_research_run([followup_tag]), followup)

        orch._active_research_context_tags = []
        self.assertIsNone(orch._find_recent_research_run())

    async def test_running_reuse_and_replay_is_tag_driven(self):
        # Reuse can only happen on explicitly reachable tags, not on question text.
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        target = self._research_run("target_run", status="complete")
        stale = self._research_run("stale_run_", status="complete")
        target_tag = orch._research_run_tag(target)

        orch._research_runs = [target, stale]
        orch._active_research_context_tags = [target_tag]
        result = orch._build_runtime_state("completely different and unrelated question")
        self.assertEqual(result["research_contexts"][0]["task"], target_tag)

        orch._active_research_context_tags = []
        result = orch._build_runtime_state("target question should NOT be reused due to no tag")
        self.assertEqual(result["research_contexts"], [])

    def test_recent_research_findings_are_bound_to_exact_tags(self):
        orch = ReActOrchestrator([], _call_llm, _dispatch)
        first = self._research_run("first_a1", status="complete")
        second = self._research_run("secondb2", status="complete")
        orch._research_runs = [first, second]

        orch._remember_research_summaries(["summary-first"], run=first)
        orch._remember_research_summaries(["summary-second"], run=second)

        first_visible = orch._visible_recent_research_findings([orch._research_run_tag(first)])
        second_visible = orch._visible_recent_research_findings([orch._research_run_tag(second)])

        self.assertEqual(first_visible, [orch._compact_runtime_text(
            f"{orch._research_run_tag(first)} | Korpus mock-corpus | summary-first",
            limit=220,
        )])
        self.assertEqual(second_visible, [orch._compact_runtime_text(
            f"{orch._research_run_tag(second)} | Korpus mock-corpus | summary-second",
            limit=220,
        )])

    def test_should_run_research_worker_is_capability_driven(self):
        orch = self._orchestrator()
        self.assertTrue(
            orch._should_run_research_worker("kurz", "user"),
            "Short user questions must not be blocked by heuristics.",
        )
        # A research sidecar needs both a selected schema and read-only runtime
        # capability. Marking the selected tools write-capable disables it.
        orch._tool_runtime_info = {
            name: {"read_only": False}
            for name in ("document_search", "semantic_search", "documentation_search")
        }
        self.assertFalse(
            orch._should_run_research_worker("kurz", "user"),
            "No read-only tools means no research run.",
        )
        self.assertFalse(orch._should_run_research_worker("lange Frage " * 8, "system"))

    def test_research_tool_calls_are_deterministic_and_tool_capability_driven(self):
        orch = self._orchestrator()
        calls = orch._build_research_tool_calls("kurz")
        tool_names = {self._tool_name(item) for item in calls}
        self.assertEqual(
            tool_names,
            {"document_search", "semantic_search", "documentation_search"},
        )
