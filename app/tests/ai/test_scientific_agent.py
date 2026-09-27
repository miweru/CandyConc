"""Real ``scientific_agent`` contract.

The previous version imported ``scientific_agent`` from
``candyconc.candyconc_copilot`` -- which tests/conftest.py replaces with a
stub whose ``scientific_agent`` returns a constant and never calls
``_plan_scientific_tasks`` (the patch target therefore did not even exist and
the fixture raised AttributeError).  The real package
(src/candyconc/candyconc_copilot/__init__.py:276/295) plans via
``_plan_scientific_tasks`` and executes the tasks with ``run_query`` /
``collocate_stats``; both data calls are patched so no corpus index is
required.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "candyconc" / "candyconc_copilot"


def _load_real_package():
    """Load the real package __init__ under a private name.

    The prometheus client is masked during exec because the package pulls in
    the real dispatcher, whose module-level Counter may already be registered
    in the global CollectorRegistry (see _real_copilot.real_dispatcher).
    """
    spec = importlib.util.spec_from_file_location(
        "cc_real_copilot_pkg",
        _PKG_DIR / "__init__.py",
        submodule_search_locations=[str(_PKG_DIR)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    had_prom = "prometheus_client" in sys.modules
    prev_prom = sys.modules.get("prometheus_client")
    sys.modules["prometheus_client"] = None  # force ImportError -> shim
    sys.modules["cc_real_copilot_pkg"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if had_prom:
            sys.modules["prometheus_client"] = prev_prom
        else:
            sys.modules.pop("prometheus_client", None)
    return module


_cc = _load_real_package()


@pytest.fixture()
def plan_stub():
    with patch.object(_cc, "_plan_scientific_tasks") as mock, patch.object(
        _cc, "_LM_ENDPOINT", "http://test"
    ), patch.object(_cc, "run_query", return_value=iter([("fox", 1)])):
        mock.return_value = ("fox", ["frequency"])
        yield mock


def test_scientific_agent_calls_plan(plan_stub):
    reply = _cc.scientific_agent("dummy question")
    assert "fox" in reply
    plan_stub.assert_called_once()
