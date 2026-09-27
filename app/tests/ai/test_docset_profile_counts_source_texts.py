# -*- coding: utf-8 -*-
"""create_docset reports how many distinct source texts a docset covers.

Read on 2026-09-26, Muse cycle 6 on e07709979e, question
r5b-konkordanz-belegqualitaet: the question asks how many of 5,921 hits are
duplicates across the 13 versions of a source text. No tool reported the number
of source texts behind a hit set, and the answer estimated 5,921 / 13 ≈ 455.
The profile counted origin_id and dropped it as a source-text field (the axes
keep it out on purpose, see test_p27_confounders). ``source_texts`` carries
the count without the value distribution.
"""

from __future__ import annotations

import os

import pytest
from jsonschema import validate as _json_validate

from candyconc.services.tools.docset_profile import source_text_count
from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw
from tests.ai.test_tool_wrappers_parity_r5 import active_index  # noqa: F401

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


def test_the_field_covering_most_tokens_wins():
    counts = {
        "origin_id": {"a:1": 10, "b:1": 10, "a:2": 5},
        "origin_doc_id": {"1": 20, "2": 5},
        "pair_id": {"a:1": 6},
        "register": {"news": 25},
    }
    assert source_text_count(counts) == 3


def test_no_source_text_field_gives_none():
    assert source_text_count({"register": {"news": 25}}) is None


@pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="CANDYCONC_INDEX_PATH muss auf einen echten Fast Index zeigen",
)
def test_create_docset_reports_source_texts(active_index):  # noqa: F811
    antwort = tw.create_docset_tool(filters={"split": "test"})
    _json_validate(antwort, tw.CREATE_DOCSET_RESPONSE)
    ids = active_index.fast_index.doc_metadata
    erwartet = len({
        str(meta.get("origin_id"))
        for meta in ids.values()
        if isinstance(meta, dict) and meta.get("split") == "test" and meta.get("origin_id") not in (None, "")
    })
    assert antwort["profile"]["source_texts"] == erwartet
    assert "origin_id" not in antwort["profile"]["axes"]
