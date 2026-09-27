"""Regression test (FT id 1): lexical_diversity discloses the RAW corpus total.

``n_tokens`` only counts analyst tokens (punctuation/markers excluded), which
made a reported TTR look unanchored against the corpus size shown elsewhere
(/corpora token_count). ``compute_lexical_diversity`` now also returns
``corpus_raw_token_count`` (the raw index token_count) alongside ``n_tokens``,
keeping the ``analyst_tokens_only`` flag.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from candyconc.services.tools import lexical_diversity as ld


class _FakeLex:
    vocab_size = 4
    offsets = None
    strings_view = None


class _FakeStore:
    token_count = 56191  # the RAW corpus total (matches /corpora)

    def get_word_ids_range(self, start, end):
        # 5 analyst tokens, 4 distinct types.
        return np.array([1, 2, 3, 1, 4], dtype=np.int64)


class _FakeIndex:
    def __init__(self):
        self.fast_index = SimpleNamespace(
            token_store=_FakeStore(),
            lexicons=SimpleNamespace(word=_FakeLex()),
        )


def test_corpus_raw_token_count_present_and_distinct_from_n_tokens(monkeypatch):
    # Bypass analyst-token masking: count the raw 5-token stream directly so the
    # analyst n_tokens (5) is clearly distinct from the raw corpus total (56191).
    monkeypatch.setattr(ld, "strings_for_ids", lambda *a, **k: ["a", "b", "c", "d"])
    monkeypatch.setattr(
        ld, "_analyst_token_mask", lambda idx: np.ones(5, dtype=bool)
    )

    metrics = ld.compute_lexical_diversity(_FakeIndex(), analyst_tokens_only=True)

    assert metrics["n_tokens"] == 5
    assert metrics["n_types"] == 4
    # FT id 1: the raw corpus total is now disclosed alongside the analyst count.
    assert metrics["corpus_raw_token_count"] == 56191
    assert metrics["corpus_raw_token_count"] != metrics["n_tokens"]
    assert metrics["analyst_tokens_only"] is True
