from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import candyconc.core.collocation_engine as ce
from candyconc.core.collocation_engine import CollocationEngine


class _Lexicon:
    vocab_size = 10

    def get_id(self, _word: str) -> int:
        return 0


def test_docset_stats_fail_closed_without_real_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Docset-local collocations must not fall back to global frequencies."""
    engine = CollocationEngine.__new__(CollocationEngine)
    engine._loaded = True
    engine.index_path = Path("unit-index")
    engine.token_store = SimpleNamespace(token_count=10)
    engine.boundaries = None
    engine._get_lexicon = lambda attr: _Lexicon()
    engine._resolve_term_id = lambda term, lex: 1
    engine._get_term_positions = lambda *args, **kwargs: np.array([1], dtype=np.uint32)
    engine._filter_positions_by_docset = lambda positions, docset_mask: positions
    engine._warn_if_very_frequent = lambda *args, **kwargs: None
    engine._docset_signature = lambda docset_mask: "unit-mask"

    def dense_counts_fail(*_args, **_kwargs):
        raise RuntimeError("dense count failure")

    def global_fallback_reached(*_args, **_kwargs):
        raise AssertionError("global frequency fallback was reached")

    engine._docset_word_counts_dense = dense_counts_fail
    engine._calculate_statistics_arrays = global_fallback_reached
    monkeypatch.setattr(
        ce,
        "coverage_sweep_arrays",
        lambda **_kwargs: (
            np.array([0], dtype=np.int64),
            np.array([1], dtype=np.int64),
            np.array([1], dtype=np.int64),
        ),
    )
    monkeypatch.setattr(
        ce,
        "total_context_mass_arrays",
        lambda starts, *_args, **_kwargs: 1 if starts.size else 0,
    )
    monkeypatch.setattr(ce, "count_collocates", lambda *_args, **_kwargs: {2: 1})

    with pytest.raises(RuntimeError, match="Docset-Frequenzen konnten nicht berechnet"):
        engine.collocate_stats(
            "und",
            docset_mask=np.array([True], dtype=bool),
            cache_mode="off",
            top_n=20,
            # The stub collocate has O=1; disable the min_count floor so it reaches
            # the docset-frequency path under test (fail-closed is orthogonal to it).
            min_count=1,
        )
