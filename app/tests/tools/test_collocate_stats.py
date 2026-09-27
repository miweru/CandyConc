"""Collocate stats over the active runtime corpus.

Rewritten from the retired CorpusIndex(":memory:") / import_tokens API to a
tiny real Fast Index (see tests/tools/conftest.py).
"""

import pytest

from candyconc.tools.collocate_stats import collocate_stats


def test_top_collocates(tokens_corpus):
    # H6/B6 floor contract: an explicit min_count wins but is never applied
    # below 2 (co-occurrence hapaxes stay out). min_count=1 therefore means an
    # effective floor of 2; in the tiny corpus only "the" co-occurs twice with
    # "fox", which is enough for the column-contract check.
    df = collocate_stats("fox", min_count=1)
    assert not df.empty
    assert "word" in df.columns
    assert "chi2_cell" in df.columns
    assert "t" in df.columns
    assert "ll" in df.columns


def test_retired_mi2_sort_is_rejected(tokens_corpus):
    with pytest.raises(ValueError, match="chi2_cell"):
        collocate_stats("fox", min_count=1, sort_by="mi2")


def test_collocate_stats_keeps_the_chi_square_cell_basis(tokens_corpus):
    # H6/B6: the requested min_count=1 is clamped to the hard exploratory
    # floor of 2 (adaptive_collocate_min_freq contract), so the f=1 hapax
    # "quick" no longer appears. The chi2_cell cell-basis contract is checked
    # on "the", the only collocate of "fox" with f=2 in the tiny corpus.
    df = collocate_stats("fox", min_count=1, sort_by="chi2_cell")

    assert df.attrs["effective_min_count"] == 2
    assert df.attrs["min_count_mode"] == "requested"
    assert "quick" not in set(df["word"])

    assert {"f", "observed", "expected", "chi2_cell"}.issubset(df.columns)
    row = df[df["word"] == "the"].iloc[0]
    assert int(row["f"]) == int(row["observed"]) == 2
    assert float(row["expected"]) > 0.0
    assert float(row["chi2_cell"]) == pytest.approx(
        (float(row["observed"]) - float(row["expected"])) ** 2 / float(row["expected"]),
        abs=0.02,
    )
    assert "mi2" not in df.columns


@pytest.mark.parametrize(
    "max_nodes,depth,expand,node_count,truncated",
    [(3, 1, False, 3, True), (5, 1, False, 5, True),
     (10, 1, False, 10, False), (30, 1, False, 10, False),
     (11, 2, False, 6, True), (11, 2, True, 10, False)],
)
def test_network_reports_omitted_nodes(max_nodes, depth, expand, node_count, truncated, monkeypatch):
    import importlib
    import pandas as pd

    module = importlib.import_module("candyconc.tools.collocate_stats")
    words = ["green", "a", "black", "herbal", "white", "strong", "hot", "iced", "fresh"]
    frame = pd.DataFrame({"word": words + ["tea", ".", "unknown"],
                          "f": list(range(9, 0, -1)) + [0, 99, 99],
                          "logdice": list(range(9, 0, -1)) + [0, 99, float("nan")]})
    monkeypatch.setattr(module, "collocate_stats", lambda query, **kw:
                        frame if query == "tea" or expand else frame.iloc[:0])
    result = module.collocate_network_data("tea", max_nodes=max_nodes, expand_depth=depth)

    assert result["diagnostics"]["node_count"] == node_count
    assert [node["id"] for node in result["nodes"]] == ["tea", *words[:node_count - 1]]
    assert [(edge["target"], edge["weight"]) for edge in result["edges"]
            if edge["source"] == "tea"] == list(zip(words[:node_count - 1], range(9, 10 - node_count, -1)))
    assert result["diagnostics"]["truncated"] is truncated
