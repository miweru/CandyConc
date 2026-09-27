"""Track B (R6) guidance-truth regression tests.

Covers the truncation-flag contract for ``frequency_list`` (B5) on the real
bench index, plus a light check that the corrected science guidance / honest
one-sided rendering survives in the prompt and grounding helpers.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

from candyconc.candyconc_copilot import prompts
from candyconc.candyconc_copilot.analysis_grounding import _format_log_ratio_metric


def _real_tool_wrappers():
    """Return the REAL tool_wrappers module, bypassing the conftest stub.

    The root tests/conftest.py installs a lightweight stub at
    ``candyconc.candyconc_copilot.tool_wrappers`` for the whole suite. For these
    contract tests we need the production wrapper (with the truncation flags), so
    drop the stub from sys.modules and import the real one fresh.
    """
    sys.modules.pop("candyconc.candyconc_copilot.tool_wrappers", None)
    return importlib.import_module("candyconc.candyconc_copilot.tool_wrappers")


@pytest.fixture(scope="module", autouse=True)
def _load_bench_index():
    """Load the bench index so corpus-backed tool wrappers can run."""
    index_path = os.environ.get("CANDYCONC_INDEX_PATH")
    if not index_path or not os.path.isdir(index_path):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    from candyconc.core import query_runtime
    from candyconc.core.corpus_index import CorpusIndex

    # Remember the conftest stub so we can restore it for sibling tests after
    # we swap in the real tool_wrappers module.
    stub = sys.modules.get("candyconc.candyconc_copilot.tool_wrappers")

    idx = CorpusIndex(index_path)
    query_runtime.set_corpus(idx)
    yield

    if stub is not None:
        sys.modules["candyconc.candyconc_copilot.tool_wrappers"] = stub


def test_frequency_list_reports_truncated_when_over_cap():
    """frequency_list caps at top-100; total>rows must set truncated=True."""
    frequency_list_tool = _real_tool_wrappers().frequency_list_tool

    result = frequency_list_tool()
    assert result["status"] == "success"
    rows = result["rows"]
    total = result["total"]
    assert "truncated" in result, "frequency_list must surface a truncated flag"
    assert result["truncated"] == (total > len(rows))
    if total > 100:
        # Bench index is large enough to exceed the top-100 cap.
        assert len(rows) == 100
        assert result["truncated"] is True


def test_one_sided_log_ratio_rendered_honestly():
    """A one-sided collocate must not be quoted as an exact ratio."""
    one_sided = _format_log_ratio_metric({"log_ratio": 9.97, "one_sided": True})
    assert "einseitig" in one_sided
    assert "geglaettet" in one_sided

    two_sided = _format_log_ratio_metric({"log_ratio": 1.5, "one_sided": False})
    assert two_sided == "log_ratio=1.5"

    assert _format_log_ratio_metric({"log_ratio": None}) == ""


def test_science_guidance_uses_real_keyness_fields():
    """Keyness guidance leads with log_ratio effect size + FDR caveat."""
    prompt = prompts.get_system_prompt()
    assert "log_ratio" in prompt
    assert "q_value" in prompt  # multiple-comparison correction
    assert "logDice" in prompt
    # collocation ll thresholds now valid for the full G^2
    assert "10.83" in prompt
    # one_sided flag is documented for the copilot
    assert "one_sided" in prompt
