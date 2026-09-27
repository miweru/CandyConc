"""Golden tests for the sketch-difference scorer (Track FT-SKETCH-DIFF).

``analysis_defaults.sketch_difference(sketch_a, sketch_b, ...)`` is the pure
transform a route calls after computing two word sketches. Contract per
relation: {common:[{word,score_a,score_b,delta}], only_a:[{word,score}],
only_b:[{word,score}]}, with the top-level {term_a, term_b, relations,
relations_compared}.
"""

import pandas as pd
import pytest

from candyconc.analysis_defaults import sketch_difference


def _sketch(rows_by_rel):
    return {rel: pd.DataFrame(rows) for rel, rows in rows_by_rel.items()}


def test_basic_alignment_buckets_and_delta():
    a = _sketch(
        {
            "obj": [
                {"word": "Strategie", "score": 5.0},
                {"word": "Plan", "score": 2.0},
            ]
        }
    )
    b = _sketch(
        {
            "obj": [
                {"word": "Strategie", "score": 1.0},
                {"word": "Idee", "score": 3.0},
            ]
        }
    )
    diff = sketch_difference(a, b, term_a="Politik", term_b="Wirtschaft")

    assert diff["term_a"] == "Politik"
    assert diff["term_b"] == "Wirtschaft"
    assert diff["relations_compared"] == 1
    rel = diff["relations"]["obj"]

    assert rel["common"] == [
        {"word": "Strategie", "score_a": 5.0, "score_b": 1.0, "delta": 4.0}
    ]
    assert rel["only_a"] == [{"word": "Plan", "score": 2.0}]
    assert rel["only_b"] == [{"word": "Idee", "score": 3.0}]


def test_common_sorted_by_absolute_delta():
    a = _sketch(
        {
            "amod": [
                {"word": "x", "score": 10.0},
                {"word": "y", "score": 1.0},
                {"word": "z", "score": 4.0},
            ]
        }
    )
    b = _sketch(
        {
            "amod": [
                {"word": "x", "score": 9.0},   # delta +1
                {"word": "y", "score": 8.0},   # delta -7 (largest magnitude)
                {"word": "z", "score": 2.0},   # delta +2
            ]
        }
    )
    rel = sketch_difference(a, b)["relations"]["amod"]
    words_in_order = [r["word"] for r in rel["common"]]
    assert words_in_order == ["y", "z", "x"]
    assert rel["common"][0]["delta"] == pytest.approx(-7.0)


def test_relations_present_in_only_one_sketch_are_kept():
    a = _sketch({"obj": [{"word": "a", "score": 3.0}]})
    b = _sketch({"subj": [{"word": "b", "score": 4.0}]})
    diff = sketch_difference(a, b)
    assert set(diff["relations"]) == {"obj", "subj"}
    assert diff["relations"]["obj"]["only_a"] == [{"word": "a", "score": 3.0}]
    assert diff["relations"]["subj"]["only_b"] == [{"word": "b", "score": 4.0}]


def test_top_n_caps_each_bucket():
    a = _sketch({"obj": [{"word": f"a{i}", "score": float(10 - i)} for i in range(10)]})
    b = _sketch({"obj": [{"word": f"b{i}", "score": float(10 - i)} for i in range(10)]})
    rel = sketch_difference(a, b, top_n=3)["relations"]["obj"]
    assert len(rel["only_a"]) == 3
    assert len(rel["only_b"]) == 3
    # only_a sorted by score desc -> highest first.
    assert [r["word"] for r in rel["only_a"]] == ["a0", "a1", "a2"]


def test_score_fallback_when_no_score_column():
    # Raw (un-normalized) sketch rows expose ll_signed instead of score.
    a = {"obj": [{"word": "p", "ll_signed": 6.0}]}
    b = {"obj": [{"word": "p", "ll_signed": 2.0}]}
    rel = sketch_difference(a, b)["relations"]["obj"]
    assert rel["common"][0]["delta"] == pytest.approx(4.0)


def test_empty_inputs_return_empty_relations():
    diff = sketch_difference({}, {})
    assert diff["relations"] == {}
    assert diff["relations_compared"] == 0


def test_accepts_list_of_row_dicts_as_well_as_dataframes():
    a = {"obj": [{"word": "a", "score": 5.0}]}
    b = {"obj": [{"word": "a", "score": 1.0}]}
    rel = sketch_difference(a, b)["relations"]["obj"]
    assert rel["common"][0]["delta"] == pytest.approx(4.0)
