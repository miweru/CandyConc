"""Schema validation in the REAL tool dispatcher.

The conftest dispatcher stub has a drifted signature (``dispatch(name,
**kw)``), while the real contract is ``dispatch(call, token=None)`` with a
tool-call dict (src/candyconc/candyconc_copilot/dispatcher.py:28).  Load the
real module via the loader pattern from ``tests/ai/_real_copilot.py``
(``real_dispatcher``): exec under a private name with ``prometheus_client``
masked, so the module-level ``tool_calls_total`` Counter falls back to the
internal no-op shim instead of double-registering in the global
CollectorRegistry, and restore all touched ``sys.modules`` entries.

The original test also dispatched a NONEXISTENT tool name
("search_products"); the real dispatcher raises ``KeyError`` for unknown
names (``schema_map[name]``), not ``ValueError`` -- ValueError is the
contract for schema-invalid arguments of a KNOWN tool
(dispatcher.py: ``raise ValueError(f"Invalid arguments: ...")``).
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DISPATCHER_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "candyconc"
    / "candyconc_copilot"
    / "dispatcher.py"
)


def _load_real_dispatcher():
    spec = importlib.util.spec_from_file_location(
        "cc_real_dispatcher_tooling", _DISPATCHER_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    had_prom = "prometheus_client" in sys.modules
    prev_prom = sys.modules.get("prometheus_client")
    sys.modules["prometheus_client"] = None  # force ImportError -> no-op shim
    sys.modules["cc_real_dispatcher_tooling"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("cc_real_dispatcher_tooling", None)
        if had_prom:
            sys.modules["prometheus_client"] = prev_prom
        else:
            sys.modules.pop("prometheus_client", None)
    return module


def test_schema_error():
    dispatch = _load_real_dispatcher().dispatch
    # run_cqlf_query is a registered tool whose schema types "query" as a
    # string (tool_wrappers.py RUN_CQLF_TOOL; mirrored by the conftest stub
    # registry), so an integer must be rejected before any tool call.
    bad_call = {
        "function": {
            "name": "run_cqlf_query",
            "arguments": json.dumps({"query": 123}),
        }
    }
    with pytest.raises(ValueError, match="Invalid arguments"):
        asyncio.run(dispatch(bad_call))
