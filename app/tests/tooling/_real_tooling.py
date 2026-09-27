"""Shared loader for the REAL candyconc tooling registry surface.

tests/conftest.py installs a test-local registry shim under
``candyconc.tooling`` / ``candyconc.tooling.registry`` and only registers a
subset of stub tools (run_cqlf_query, collocate_stats, frequency_list,
dispersion_offsets, keyness, document_search, documentation_search,
semantic_search, transformer_search).  The real production surface defined in
``src/candyconc/candyconc_copilot/tool_wrappers.py`` additionally contains
compare_collocates, metadata_values, semantic_cluster_words, word_sketch,
contrast_collocates, ... -- so tests that audit or select over the real tool
surface fail in the stub environment ("stub shadowing").

This helper mirrors the proven pattern from ``tests/ai/_real_copilot.py``:
load the real modules exactly once via
``importlib.util.spec_from_file_location`` and then RESTORE every touched
``sys.modules`` entry, so no other test module ever observes the swap
(never leave a stub package replaced).

Loaded under the production module names (required so that
``tool_wrappers.py``'s ``from candyconc.tooling.registry import llm_tool``
binds the real private registry, and so its relative ``from .analysis
import ...`` resolves through the package ``__path__``).

Two seams are masked during the load:

* ``prometheus_client`` -- the real ``registry.py`` registers a module-level
  ``Counter("tool_registered_total")`` in the GLOBAL CollectorRegistry; a
  second registration in the same process raises "Duplicated timeseries".
  A no-op fake keeps the global registry untouched.
* ``candyconc.services.backend.server`` -- ``registry.get_tools()`` lazily
  imports the backend server purely for registration side effects
  (registry.py: ``import candyconc.services.backend.server``).  The real
  server registers no ``llm_tool`` entries itself (grep: no ``llm_tool`` in
  server.py), so a dummy module keeps the snapshot identical while avoiding
  the heavy FastAPI app import.

The surface is SNAPSHOTTED at load time (``REAL_TOOLS`` / ``REAL_SCHEMA_MAP``
/ ``REAL_RUNTIME_INFO``) because the real ``get_tools()`` re-runs its lazy
imports on every call, which would re-import the real server after the
sys.modules restore.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "candyconc"


class _NoopMetric:
    def __init__(self, *args, **kwargs):
        pass

    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return None


def _fake_prometheus() -> types.ModuleType:
    mod = types.ModuleType("prometheus_client")
    mod.Counter = _NoopMetric
    mod.Histogram = _NoopMetric
    mod.Gauge = _NoopMetric
    mod.Summary = _NoopMetric
    return mod


def _load_real_surface():
    """Load real registry + tool_wrappers, snapshot the surface, restore."""
    touched = [
        "prometheus_client",
        "candyconc.tooling.registry",
        "candyconc.candyconc_copilot.tool_wrappers",
        "candyconc_copilot.tool_wrappers",
        "candyconc.services.backend.server",
    ]
    saved = {name: sys.modules.get(name) for name in touched}
    had = {name: name in sys.modules for name in touched}
    try:
        sys.modules["prometheus_client"] = _fake_prometheus()

        reg_path = _SRC / "tooling" / "registry.py"
        reg_spec = importlib.util.spec_from_file_location(
            "candyconc.tooling.registry", reg_path
        )
        assert reg_spec and reg_spec.loader
        registry = importlib.util.module_from_spec(reg_spec)
        sys.modules["candyconc.tooling.registry"] = registry
        reg_spec.loader.exec_module(registry)

        # Dummy server so registry.get_tools()'s lazy import is a no-op.
        sys.modules["candyconc.services.backend.server"] = types.ModuleType(
            "candyconc.services.backend.server"
        )

        tw_path = _SRC / "candyconc_copilot" / "tool_wrappers.py"
        tw_spec = importlib.util.spec_from_file_location(
            "candyconc.candyconc_copilot.tool_wrappers", tw_path
        )
        assert tw_spec and tw_spec.loader
        tool_wrappers = importlib.util.module_from_spec(tw_spec)
        # Visible under both production aliases while decorators run.
        sys.modules["candyconc.candyconc_copilot.tool_wrappers"] = tool_wrappers
        sys.modules["candyconc_copilot.tool_wrappers"] = tool_wrappers
        tw_spec.loader.exec_module(tool_wrappers)

        tools = registry.get_tools()
        schema_map = registry.get_schema_map()
        runtime_info = registry.get_tool_runtime_info()
        return tools, schema_map, runtime_info, list(registry.REGISTRY)
    finally:
        for name in touched:
            if had[name]:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


REAL_TOOLS, REAL_SCHEMA_MAP, REAL_RUNTIME_INFO, REAL_REGISTRY = _load_real_surface()
