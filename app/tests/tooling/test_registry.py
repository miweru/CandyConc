import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import candyconc
from candyconc.tooling import get_tool_runtime_info

# The conftest registry shim only registers a subset of stub tools (no
# metadata_values, compare_collocates, ...), so the surface audit must run
# against the REAL production registry + tool_wrappers
# (src/candyconc/tooling/registry.py,
# src/candyconc/candyconc_copilot/tool_wrappers.py), snapshotted by the
# real-module loader in _real_tooling.py.
from tests.ai._real_copilot import policy_engine as policy_engine_mod
from tests.tooling._real_tooling import (
    REAL_RUNTIME_INFO,
    REAL_SCHEMA_MAP,
    REAL_TOOLS,
)

CORE_ANALYSIS_TOOLS = {
    "run_cqlf_query",
    "frequency_list",
    "collocate_stats",
    "document_search",
    "metadata_values",
    # S3 follow-up: diachronic trend over a metadata date field.
    "trend_analysis",
}

INTERPRETATIVE_OR_MUTATING_TOOLS = {
    "cluster_export_md",
    "cluster_save",
    "refine_cluster_label",
    "semantic_cluster",
    "semantic_cluster_words",
    "semantic_recluster",
}


def test_tool_registration_and_execution_without_optional_metrics(monkeypatch):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    path = Path(__file__).resolve().parents[2] / "src/candyconc/tooling/registry.py"
    spec = importlib.util.spec_from_file_location("registry_without_metrics", path)
    registry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registry)

    @registry.llm_tool({"function": {"name": "example", "parameters": {"type": "object"}}})
    def example():
        return {"count": 3}

    assert len(registry.REGISTRY) == 1
    assert registry.REGISTRY[0]["callable"]() == {"count": 3}
    assert registry.REGISTRY[0]["read_only"] is True


def test_registry_tool_surface_is_unique_serializable_and_auditable():
    tools = REAL_TOOLS
    names = [tool["function"]["name"] for tool in tools]

    assert tools, "LLM tool surface must not be empty"
    assert CORE_ANALYSIS_TOOLS <= set(names)
    assert "run_cqp_query" not in names
    assert [name for name, count in Counter(names).items() if count > 1] == []

    for tool in tools:
        json.dumps(tool)
        function = tool.get("function", {})
        parameters = function.get("parameters")
        assert tool.get("type") == "function"
        assert isinstance(function.get("name"), str)
        assert isinstance(parameters, dict)
        assert parameters.get("type") == "object"

    assert set(REAL_SCHEMA_MAP) == set(names)
    assert set(REAL_RUNTIME_INFO) == set(names)
    for name, info in REAL_RUNTIME_INFO.items():
        assert isinstance(info.get("read_only"), bool), name
        assert isinstance(info.get("concurrency_safe"), bool), name


def test_runtime_info_is_available_from_public_package_surfaces():
    assert candyconc.get_tool_runtime_info is get_tool_runtime_info


def test_trend_analysis_is_registered_read_only_with_sample_and_attribute_params():
    """S3 follow-up surface audit: the new/extended tool contracts are exact.

    - trend_analysis is registered, read-only (release default-dispatchable) and
      requires date_field.
    - run_cqlf_query advertises the sample/seed mirror of REST GET /query.
    - collocate_stats / collocation_network advertise the attribute param
      (word|lemma counting, REST T2b parity).
    """
    names = {tool["function"]["name"] for tool in REAL_TOOLS}
    assert "trend_analysis" in names
    assert REAL_RUNTIME_INFO["trend_analysis"]["read_only"] is True
    assert REAL_SCHEMA_MAP["trend_analysis"]["required"] == ["date_field"]
    trend_props = set(REAL_SCHEMA_MAP["trend_analysis"]["properties"])
    assert trend_props == {"query", "cql", "date_field", "granularity", "docset_id", "corpus"}

    kwic_props = set(REAL_SCHEMA_MAP["run_cqlf_query"]["properties"])
    assert {"sample", "seed"} <= kwic_props

    assert "attribute" in REAL_SCHEMA_MAP["collocate_stats"]["properties"]
    assert "attribute" in REAL_SCHEMA_MAP["collocation_network"]["properties"]


def test_interpretative_or_mutating_tools_are_not_read_only():
    missing = INTERPRETATIVE_OR_MUTATING_TOOLS - set(REAL_RUNTIME_INFO)
    assert missing == set()

    for name in sorted(INTERPRETATIVE_OR_MUTATING_TOOLS):
        assert REAL_RUNTIME_INFO[name]["read_only"] is False, name
        assert REAL_RUNTIME_INFO[name]["concurrency_safe"] is False, name


def test_policy_default_deny_empty_and_write_gate_surface_is_exact():
    """Release gating moved from the policy deny list to the orchestrator.

    The cluster family was removed from ``DEFAULT_DENY_TOOLS`` (now empty):
    read cluster tools run in release, and every ``read_only=False`` tool is
    paused by the orchestrator write-tool approval gate
    (``_is_tool_known_write`` -> ``_should_require_approval``).  The audit
    value stays: the non-read-only surface must remain EXACTLY the known
    write-gate set, so a newly registered mutating tool has to be added here
    consciously instead of slipping past both gates.
    """
    assert policy_engine_mod.DEFAULT_DENY_TOOLS == frozenset()

    non_read_only = {
        name for name, info in REAL_RUNTIME_INFO.items() if info.get("read_only") is False
    }
    assert non_read_only == INTERPRETATIVE_OR_MUTATING_TOOLS
