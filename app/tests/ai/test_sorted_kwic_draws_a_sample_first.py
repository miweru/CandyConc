# -*- coding: utf-8 -*-
"""run_cqlf_query with sort_by sorts a drawn sample, not the head of the index.

Found by the evidence-flow reviewer on 2026-09-26: with sort_by and without
sample, run_cqlf_query sorted the first ``limit`` hits in corpus order. In
candidate 4 (Muse, r5a-wort-gegen-lemma) ``run_cqlf_query([word="recht"],
limit=50, sort_by="1R")`` on the AI docset returned 50 rows from one generator
(Claude Opus 4.7) and two sources (cpp_bt, klexikon_full), positions 12,370 to
2,055,820 of 142 million, and the answer read them as KI usage. The fix for the
unsorted case (sample instead of index head) did not cover sort_by.
"""

from __future__ import annotations

import os

import pytest

from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)


def test_sort_by_draws_a_reported_sample(active_index):  # noqa: F811
    result = tw.run_cqlf_query_tool("und", limit=20, sort_by="1R")
    assert result["total"] > 20
    assert "sample" in result, "sort_by returned the index head without a sample block"
    positions = sorted(int(row["pos"]) for row in result["rows"])
    assert positions[-1] > 20 * positions[0] + 1000, positions


def test_sorted_rows_follow_the_sort_key(active_index):  # noqa: F811
    result = tw.run_cqlf_query_tool("und", limit=20, sort_by="1R")
    right = [str(row["right"]).split()[0].lower() if str(row["right"]).split() else "" for row in result["rows"]]
    assert right == sorted(right), right


def test_position_still_means_index_order(active_index):  # noqa: F811
    result = tw.run_cqlf_query_tool("und", limit=20, sort_by="position")
    assert "sample" not in result
    positions = [int(row["pos"]) for row in result["rows"]]
    assert positions == sorted(positions)
