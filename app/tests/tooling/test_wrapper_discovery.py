# The conftest registry shim only registers a subset of stub tools, so the
# discovery audit must run against the REAL production surface
# (src/candyconc/candyconc_copilot/tool_wrappers.py), loaded via the
# real-module loader in _real_tooling.py.
from tests.tooling._real_tooling import REAL_TOOLS


def test_wrapper_discovery():
    names = {t["function"]["name"] for t in REAL_TOOLS}
    assert {"run_cqlf_query", "frequency_list"}.issubset(names)
