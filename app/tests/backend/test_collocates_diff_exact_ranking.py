"""Regression: collocation contrast ranks its complete eligible vocabulary."""

from __future__ import annotations

import numpy as np

from candyconc.services.backend import server as srv


class _Lexicon:
    def __init__(self, words: dict[int, str]) -> None:
        self._words = words

    def get_strings_for_ids(self, ids: np.ndarray) -> list[str]:
        return [self._words[int(word_id)] for word_id in ids]


class _ScoreEngine:
    def _calculate_selected_score_array(self, observed, expected, event_mass, **_kwargs):
        return np.asarray(observed, dtype=np.float64)


def test_collocates_diff_filters_the_full_union_before_top_n_selection() -> None:
    """Punctuation cannot consume the candidate window ahead of valid rows."""
    from candyconc.core.collocation_engine import CollocationDiffBasis

    words = {
        **{index: "." for index in range(10)},
        10: "zulässig-a",
        11: "zulässig-b",
    }
    basis = CollocationDiffBasis(
        word_ids=np.arange(12, dtype=np.uint32),
        # The first ten rows have larger raw deltas but are punctuation.
        target_observed=np.asarray([100 - index for index in range(10)] + [2, 1], dtype=np.float64),
        reference_observed=np.zeros(12, dtype=np.float64),
        target_freqs=np.ones(12, dtype=np.float64),
        reference_freqs=np.ones(12, dtype=np.float64),
        target_match_count=1,
        reference_match_count=1,
        target_context_mass=100,
        reference_context_mass=100,
        target_token_total=1_000,
        reference_token_total=1_000,
    )

    rows, meta = srv._collocates_diff_rows_from_basis(
        _ScoreEngine(),
        _Lexicon(words),
        basis,
        term="node",
        sort_by="logdice",
        limit=2,
    )

    assert [row["word"] for row in rows] == ["zulässig-a", "zulässig-b"]
    assert meta == {"row_limit": 2, "total_candidates": 2, "truncated": False}
