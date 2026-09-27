"""W1 keystone — golden anchors for the meta-filter unification (Master-Plan 2026-06-09).

Pin the EXACT behaviour of the canonical core builders BEFORE server.py/controller.py
delegate to them, so the unification is provably behaviour-preserving. ANCHOR-1..5,7,8,9
pin existing core behaviour; ANCHOR-6,10 pin the new opt-in translate_meta_field_aliases
(the only home for the transform->prompting_method alias).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cqlhpc.ast import MetaCond, MetaExpr  # noqa: E402
from candyconc.core.meta_filters import (  # noqa: E402
    build_meta_expr,
    canonicalize_metadata_filters,
    normalize_meta_value,
    metadata_mask,
    translate_meta_field_aliases,
)


def _cond(field, op, value):
    return MetaExpr(kind="cond", parts=(MetaCond(field=field, op=op, value=value),))


# --- ANCHOR-1..5,7,8: existing core build_meta_expr / canonicalize ---

def test_anchor1_scalar_to_cond():
    assert build_meta_expr({"source": "twitter"}) == _cond("source", "=", "twitter")


def test_anchor2_list_to_or():
    assert build_meta_expr({"model": ["gpt", "qwen"]}) == MetaExpr(
        kind="or", parts=(_cond("model", "=", "gpt"), _cond("model", "=", "qwen"))
    )


def test_anchor3_single_element_list_to_cond():
    assert build_meta_expr({"model": ["gpt"]}) == _cond("model", "=", "gpt")


def test_anchor4_multi_field_to_and():
    assert build_meta_expr({"source": "news", "model": "human"}) == MetaExpr(
        kind="and", parts=(_cond("source", "=", "news"), _cond("model", "=", "human"))
    )


def test_anchor5_empty_none_whitespace_to_none():
    assert build_meta_expr({}) is None
    assert build_meta_expr({"source": None}) is None
    assert build_meta_expr({"source": "  "}) is None


def test_anchor7_canonicalize_merges_legacy_date_genre():
    assert canonicalize_metadata_filters({"source": "news"}, date="2024-01", genre="politik") == {
        "source": "news", "date": "2024-01", "genre": "politik",
    }


def test_anchor8_legacy_does_not_overwrite_explicit_keys():
    assert canonicalize_metadata_filters({"date": "2023-12", "source": "news"}, date="2024-01") == {
        "date": "2023-12", "source": "news",
    }


# --- ANCHOR-9: recursive normalizer contract (server->core swap, REFUTED #1) ---

def test_anchor9_normalize_equivalence_and_recursion():
    assert normalize_meta_value(["a", "", None, "b"]) == ["a", "b"]  # flat: all 3 impls agree
    # the unified (recursive) core behaviour, documented:
    assert normalize_meta_value([["x", ""], "y"]) == [["x"], "y"]
    assert normalize_meta_value([[None]]) is None
    assert normalize_meta_value(("a", "b")) == ["a", "b"]


# --- ANCHOR-6: transform alias (the new opt-in function) ---

def test_anchor6_translate_transform_alias():
    assert translate_meta_field_aliases({"transform": "rewrite"}) == {"prompting_method": "direct"}
    assert translate_meta_field_aliases({"transform": ["summary", "multistep"]}) == {
        "prompting_method": ["zusammenfassung", "prompt_builder"]
    }
    # unknown value passes through unchanged
    assert translate_meta_field_aliases({"transform": "unknown"}) == {"prompting_method": "unknown"}
    # non-transform fields untouched
    assert translate_meta_field_aliases({"model": "gpt"}) == {"model": "gpt"}


def test_anchor6_translate_no_transform_is_passthrough():
    f = {"source": "news", "model": ["a", "b"]}
    assert translate_meta_field_aliases(f) == f


# --- ANCHOR-10: full pipeline translate -> build_meta_expr -> metadata_mask fallback ---

class _FakeFastIndex:
    def __init__(self) -> None:
        self.doc_metadata = {
            0: {"prompting_method": "direct", "source": "twitter"},
            1: {"prompting_method": "zusammenfassung", "source": "twitter"},
            2: {"prompting_method": "direct", "source": "news"},
        }
        self.meta_index = None

    def _doc_meta_for_idx(self, idx: int) -> dict:
        return dict(self.doc_metadata.get(int(idx), {}))


def test_anchor10_translate_then_mask_end_to_end():
    fake = _FakeFastIndex()
    filters = translate_meta_field_aliases({"transform": "rewrite", "source": "twitter"})
    assert filters == {"prompting_method": "direct", "source": "twitter"}
    mask = metadata_mask(fake, filters, doc_count=3)
    # only doc 0 is prompting_method=direct AND source=twitter
    assert np.array_equal(mask, np.array([1, 0, 0], dtype=np.uint8))


# --- ANCHOR-11..14: range/date operators (additive) ---

import pytest  # noqa: E402
from candyconc.core.meta_filters import match_meta_filters  # noqa: E402


def test_anchor11_op_tagged_scalar():
    assert build_meta_expr({"date": {"op": ">=", "value": 20240101}}) == _cond("date", ">=", 20240101)
    assert build_meta_expr({"year": {"op": "<", "value": 2020}}) == _cond("year", "<", 2020)


def test_anchor12_between_expands_to_and():
    assert build_meta_expr({"date": {"op": "between", "lo": 20240101, "hi": 20241231}}) == MetaExpr(
        kind="and",
        parts=(_cond("date", ">=", 20240101), _cond("date", "<=", 20241231)),
    )


def test_anchor12b_invalid_op_and_missing_between_raise():
    with pytest.raises(ValueError):
        build_meta_expr({"date": {"op": "~=", "value": 1}})
    with pytest.raises(ValueError):
        build_meta_expr({"date": {"op": "between", "lo": 1}})


def test_anchor13_match_range_ops_type_safe_and_none_skip():
    assert match_meta_filters({"year": 2024}, {"year": {"op": ">=", "value": 2020}}) is True
    assert match_meta_filters({"year": 2018}, {"year": {"op": ">=", "value": 2020}}) is False
    assert match_meta_filters({"year": 2024}, {"year": {"op": "between", "lo": 2020, "hi": 2025}}) is True
    assert match_meta_filters({"year": 2030}, {"year": {"op": "between", "lo": 2020, "hi": 2025}}) is False
    # incomparable str vs number -> no match, never raises
    assert match_meta_filters({"year": "n/a"}, {"year": {"op": ">", "value": 2020}}) is False


def test_anchor14_equality_unchanged_by_additive_change():
    # Regression guard: equality MetaExpr output is byte-identical to before.
    assert build_meta_expr({"source": "news", "model": ["a", "b"]}) == MetaExpr(
        kind="and",
        parts=(
            _cond("source", "=", "news"),
            MetaExpr(kind="or", parts=(_cond("model", "=", "a"), _cond("model", "=", "b"))),
        ),
    )
