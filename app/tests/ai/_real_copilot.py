"""Shared loader for the REAL candyconc_copilot modules.

tests/conftest.py installs lightweight stubs for the whole copilot package in
``sys.modules`` (both under ``candyconc_copilot`` and
``candyconc.candyconc_copilot``).  Legacy unit tests in this directory were
written against the *real* orchestrator/session-manager contract, so they need
the real modules.

This helper loads the real modules exactly once via
``importlib.util.spec_from_file_location`` and then RESTORES the previous
``sys.modules`` entries, so no other test module ever observes the swap
(per-test isolation; see the gotcha note in
``test_copilot_event_bus_session_isolation.py``: never leave a stub package registered).

Real call contracts mirrored here (cite: src/candyconc/candyconc_copilot/...):

* ``orchestrator.ReActOrchestrator`` calls ``call_llm(messages, tools,
  user=principal, policy=..., [stream=...], [json_schema=...])``
  (orchestrator.py, ``llm_kwargs``) -- LLM fakes must accept ``**kwargs``.
* ``dispatch`` is invoked as ``dispatch(tool_call_dict, token)``
  (orchestrator.py: ``await self.dispatch(tc, self.token)``;
  dispatcher.py:28 ``async def dispatch(call, token=None)``).
* ``_is_tool_read_only`` (orchestrator.py:509-514) falls back to
  ``GROUNDING_TRIGGER_TOOLS`` when ``_tool_runtime_info`` has no entry, so an
  *empty* runtime map still enables the background research worker.  Tests
  that need a deterministic single-tool run must disable it via
  ``RESEARCH_OFF`` below.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PKG_DIR = _ROOT / "src" / "candyconc" / "candyconc_copilot"

#: Runtime-info map that switches the orchestrator's background research
#: worker off (the three research tools must be explicitly non-read-only,
#: orchestrator.py:852-864).
RESEARCH_OFF = {
    name: {"read_only": False, "concurrency_safe": False}
    for name in ("document_search", "semantic_search", "documentation_search")
}


def _load_real_modules() -> dict[str, types.ModuleType]:
    """Load real copilot modules, restoring all sys.modules entries after."""
    names = [
        "candyconc_copilot.memory_store",
        # Muss VOR session_manager stehen: dessen ``from
        # .sitzungsverdichtung import ...`` wird ueber den
        # sys.modules-Eintrag aufgeloest, nicht ueber das Dateisystem.
        "candyconc_copilot.session_compaction",
        "candyconc_copilot.session_manager",
        "candyconc_copilot.prompts",
        "candyconc_copilot.observability",
        "candyconc_copilot.policy_engine",
        "candyconc_copilot.orchestrator",
    ]
    saved = {name: sys.modules.get(name) for name in names}
    loaded: dict[str, types.ModuleType] = {}
    try:
        for name in names:
            path = _PKG_DIR / f"{name.split('.')[-1]}.py"
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            # must be visible while later modules resolve their relative
            # imports (e.g. orchestrator: ``from .session_manager import ...``)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
    finally:
        for name, prev in saved.items():
            if prev is not None:
                sys.modules[name] = prev
            else:
                sys.modules.pop(name, None)
    return loaded


_MODULES = _load_real_modules()

memory_store = _MODULES["candyconc_copilot.memory_store"]
session_manager = _MODULES["candyconc_copilot.session_manager"]
prompts = _MODULES["candyconc_copilot.prompts"]
observability = _MODULES["candyconc_copilot.observability"]
policy_engine = _MODULES["candyconc_copilot.policy_engine"]
orchestrator = _MODULES["candyconc_copilot.orchestrator"]

ReActOrchestrator = orchestrator.ReActOrchestrator
State = orchestrator.State
SessionManager = session_manager.SessionManager
MemoryStore = memory_store.MemoryStore
Observability = observability.Observability
PolicyEngine = policy_engine.PolicyEngine


def make_orchestrator(*args, research: bool = False, **kwargs):
    """Build a real ReActOrchestrator with deterministic defaults.

    ``research=False`` disables the background research worker so simple
    fakes only see the tool calls the test itself scripted.
    """
    orch = ReActOrchestrator(*args, **kwargs)
    if not research:
        orch._tool_runtime_info = dict(RESEARCH_OFF)
    return orch


_REAL_DISPATCHER: types.ModuleType | None = None


def real_dispatcher() -> types.ModuleType:
    """Load the real dispatcher module once (cached).

    Loaded under a private name so the conftest stub stays untouched.  The
    prometheus client is masked during exec: dispatcher.py registers a
    module-level Counter, and registering ``tool_calls_total`` twice in the
    global CollectorRegistry raises ``Duplicated timeseries`` -- the module
    falls back to its internal no-op Counter shim instead.
    """
    global _REAL_DISPATCHER
    if _REAL_DISPATCHER is not None:
        return _REAL_DISPATCHER
    path = _PKG_DIR / "dispatcher.py"
    spec = importlib.util.spec_from_file_location("cc_real_dispatcher", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    had_prom = "prometheus_client" in sys.modules
    prev_prom = sys.modules.get("prometheus_client")
    sys.modules["prometheus_client"] = None  # force ImportError -> shim
    sys.modules["cc_real_dispatcher"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("cc_real_dispatcher", None)
        if had_prom:
            sys.modules["prometheus_client"] = prev_prom
        else:
            sys.modules.pop("prometheus_client", None)
    _REAL_DISPATCHER = module
    return module


class MetricsObservability(Observability):
    """Real Observability (historical alias).

    This used to override ``span`` because the real ``Observability.span``
    yielded ``None`` when OTEL is disabled, crashing the orchestrator's
    unconditional ``span.set_attribute(...)`` call sites.  That defect is
    FIXED (observability.py now yields an inert ``_NoopSpan``), so the class
    is a plain alias kept for the many existing imports — tests now exercise
    the REAL span path (see test_observability_noop_span.py).
    """


class lm_summary_stub:
    """Context manager stubbing the package-level ``_lm_chat_async`` seam.

    The real ``SessionManager._lm_summary`` resolves the summariser LLM via
    ``from . import _lm_chat_async`` (session_manager.py), i.e. through the
    ``candyconc_copilot`` package object in ``sys.modules``.  Tests install an
    async fake there for the duration of the block and restore the previous
    state afterwards.
    """

    _MISSING = object()

    def __init__(self, content: str = "summary"):
        self.content = content
        self.calls: list = []

    def __enter__(self):
        pkg = sys.modules.get("candyconc_copilot")
        if pkg is None:  # pragma: no cover - conftest always installs it
            pkg = types.ModuleType("candyconc_copilot")
            sys.modules["candyconc_copilot"] = pkg
        self._pkg = pkg
        self._prev = getattr(pkg, "_lm_chat_async", self._MISSING)

        async def _fake_lm_chat_async(messages, tools=None, **kwargs):
            self.calls.append(messages)
            return {"role": "assistant", "content": self.content}

        pkg._lm_chat_async = _fake_lm_chat_async
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._prev is self._MISSING:
            try:
                delattr(self._pkg, "_lm_chat_async")
            except AttributeError:
                pass
        else:
            self._pkg._lm_chat_async = self._prev
        return False

    @property
    def called(self) -> bool:
        return bool(self.calls)
