# -*- coding: utf-8 -*-
"""The bounded model view lists a metadata field with up to 50 values in full.

Found by the flow reviewer on 2026-09-26, Muse cycle 8 (r3b-spiegel-1, round 2):
the inventory listed 12 of the 13 values of ``variant`` with ``value_counts``
13 beside it. The missing value was Teuken, the only generator that flips the
register contrast in that question.
"""

from __future__ import annotations

from candyconc.candyconc_copilot.grounding_evidence import extract_raw_surface


def test_thirteen_variants_are_all_visible():
    varianten = [f"v{i}" for i in range(12)] + ["teuken_7b_instruct_v0_6_generator_lmstudio"]
    roh = extract_raw_surface({"status": "success", "values": {"variant": varianten}, "diagnostics": {}})
    assert "teuken_7b_instruct_v0_6_generator_lmstudio" in roh["values"]["variant"]
    assert len(roh["values"]["variant"]) == 13
