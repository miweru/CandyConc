import pandas as pd
import polars as pl

from candyconc.analysis_defaults import (
    filter_frequency_frame,
    normalize_default_collocate_frame,
    summarize_dispersion_offsets,
)
from candyconc.candyconc_copilot.analysis import frequency_list
from candyconc.services.backend import server


def test_filter_frequency_frame_removes_punctuation_and_markup_tokens() -> None:
    df = pl.DataFrame(
        {
            "word": [".", ",", "|LBR|", "#", "ist", "nicht", "#Demokratie", "2024"],
            "f": [10, 9, 8, 7, 6, 5, 4, 3],
        }
    )

    out = filter_frequency_frame(df)

    assert out.get_column("word").to_list() == ["ist", "nicht", "#Demokratie", "2024"]


def test_normalize_default_collocate_frame_prefers_stabler_default_rows() -> None:
    df = pd.DataFrame(
        [
            {"word": ",", "f": 4, "t": 0.33, "ll": 1.43, "dice": 0.0038, "rank": 1},
            {"word": "Klasse", "f": 2, "t": 1.41, "ll": 24.12, "dice": 0.3333, "rank": 2},
            {"word": "Denkmustern", "f": 1, "t": 1.0, "ll": 12.87, "dice": 0.2, "rank": 3},
            {"word": "kein", "f": 2, "t": 1.35, "ll": 12.42, "dice": 0.0615, "rank": 4},
            {"word": "oder", "f": 2, "t": 1.28, "ll": 9.51, "dice": 0.0320, "rank": 5},
        ]
    )

    out = normalize_default_collocate_frame(df, None)

    assert out["word"].tolist() == ["Klasse", "kein", "oder"]
    assert out["rank"].tolist() == [1, 2, 3]


def test_normalize_default_collocate_frame_filters_explicit_sort_requests() -> None:
    df = pd.DataFrame(
        [
            {"word": ",", "f": 4, "t": 0.33, "ll": 1.43, "dice": 0.0038, "rank": 1},
            {"word": "Klasse", "f": 2, "t": 1.41, "ll": 24.12, "dice": 0.3333, "rank": 2},
        ]
    )

    out = normalize_default_collocate_frame(df, "dice")

    assert out["word"].tolist() == ["Klasse"]
    assert out["rank"].tolist() == [1]


def test_analysis_frequency_list_applies_analyst_filter() -> None:
    seen: dict[str, object] = {}

    class _DummyCorpus:
        def frequency_list(self, *, stopwords=None, attr="word"):
            seen["attr"] = attr
            return pl.DataFrame(
                {
                    "word": [".", "|LBR|", "ist", "nicht"],
                    "f": [10, 8, 6, 5],
                }
            )

    out = frequency_list(corpus=_DummyCorpus(), stopwords=["und"], group_by="lemma")

    assert seen["attr"] == "lemma"
    assert out.get_column("word").to_list() == ["ist", "nicht"]


def test_server_collocate_normalization_uses_product_defaults() -> None:
    df = pd.DataFrame(
        [
            {"word": ".", "f": 4, "t": 0.11, "ll": 0.47, "dice": 0.0034, "rank": 1},
            {"word": "Klasse", "f": 2, "t": 1.41, "ll": 24.12, "dice": 0.3333, "rank": 2},
            {"word": "Denkmustern", "f": 1, "t": 1.0, "ll": 12.87, "dice": 0.2, "rank": 3},
            {"word": "kein", "f": 2, "t": 1.35, "ll": 12.42, "dice": 0.0615, "rank": 4},
        ]
    )

    out = server._normalize_collocate_frame(df, "Mensch", None, None)

    assert out["word"].tolist() == ["Klasse", "kein"]
    assert out["rank"].tolist() == [1, 2]


def test_server_collocate_normalization_keeps_statistical_basis() -> None:
    df = pd.DataFrame(
        [
            {
                "word": "Klasse",
                "observed": 8,
                "expected": 3.5,
                "chi2_cell": 5.79,
                "dice": 0.3,
                "rank": 1,
            }
        ]
    )

    out = server._normalize_collocate_frame(df, "Mensch", None, "chi2_cell")

    assert out.loc[0, "f"] == 8
    assert out.loc[0, "observed"] == 8
    assert out.loc[0, "expected"] == 3.5
    assert out.loc[0, "chi2_cell"] == 5.79


def test_summarize_dispersion_positional_fallback_never_reports_dp() -> None:
    # No document boundaries supplied -> positional-window FALLBACK only.
    # This mode must be distinctly named and must NEVER populate ``dp`` (which is
    # reserved for the document-based Gries DP that converges with the REST path).
    summary = summarize_dispersion_offsets([1, 2, 3, 80, 95], token_count=100, partitions=5)

    assert summary["unit"] == "positional_windows"
    assert summary["total_hits"] == 5
    assert summary["partitions"] == [3, 0, 0, 0, 2]
    assert summary["nonzero_partitions"] == 2
    # Old behavior reported window DP under ``dp``; corrected behavior never does.
    assert "dp" not in summary
    assert "positional_dp_windowed" in summary
    assert 0.0 <= summary["positional_dp_windowed"] <= 1.0
    assert 0.0 <= summary["coverage_ratio"] <= 1.0
    assert summary["profile"] in {"moderately_clustered", "strongly_clustered"}
