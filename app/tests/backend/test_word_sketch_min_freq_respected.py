"""The word sketch respects ``min_freq`` 0 and 1.

Before: ``normalize_word_sketch_tables`` dropped every partner with f < 2 as
soon as a relation had one partner with f >= 2. The route, the difference
route and the copilot tool apply their own floor afterwards (default 3, and
``min_freq=0`` disables it, as the route, ``apply_word_sketch_min_freq`` and
the method block "Partner rows with f >= min_freq are listed" state). A request
with ``min_freq`` 0 or 1 therefore silently lost the partners with f = 1.
The floor now lives only with the callers. The default result stays the same.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from candyconc.analysis_defaults import apply_word_sketch_min_freq, normalize_word_sketch_tables
from candyconc.services.backend import server
from candyconc.services.backend.routes.analysis import _word_sketch_rank_rows


class _WordLex:
    total_tokens = 100

    def get_id(self, word):
        return {"alpha": 1}.get(word, 0)

    def get_freq(self, word_id):
        return {1: 10, 2: 40, 3: 5}.get(int(word_id), 0)

    def get_string(self, word_id):
        return {1: "alpha", 2: "beta", 3: "gamma"}.get(int(word_id), f"w{word_id}")


class _Index:
    def __init__(self):
        store = SimpleNamespace(
            get_positions_for_word_id=lambda _term_id: np.array([0, 4, 8], dtype=np.uint32),
            head_ids=np.zeros(12, dtype=np.int64),
            rel_ids=np.zeros(12, dtype=np.uint32),
            word_stream=SimpleNamespace(offsets=None, data=None, block_size=4),
            token_count=12,
        )
        rel = SimpleNamespace(get_string=lambda rel_id: {7: "obj"}.get(int(rel_id), str(rel_id)))
        self.fast_index = SimpleNamespace(token_store=store, lexicons=SimpleNamespace(word=_WordLex(), rel=rel))


def _sketch(monkeypatch):
    # beta co-occurs twice, gamma once.
    monkeypatch.setattr(server, "_word_sketch_counts_safe", lambda *_a, **_k: ({7: {2: 2, 3: 1}}, {}))
    monkeypatch.setattr(
        server, "get_config",
        lambda name, default=None: "0" if name == "CANDYCONC_WORD_SKETCH_MASK_MAX_TOKENS" else default,
    )
    return server._word_sketch_for_query(_Index(), "alpha", relation_limit=0)


def test_the_sketch_passes_every_partner_to_the_floor(monkeypatch):
    tables = _sketch(monkeypatch)
    assert sorted(tables["obj_rev"]["word"]) == ["beta", "gamma"]


def test_min_freq_zero_and_one_keep_the_partner_with_f_one(monkeypatch):
    rows = _sketch(monkeypatch)["obj_rev"].to_dict("records")
    for min_freq in (0, 1):
        assert {row["word"] for row in _word_sketch_rank_rows(rows, min_freq=min_freq)} == {"beta", "gamma"}
    assert {row["word"] for row in _word_sketch_rank_rows(rows, min_freq=2)} == {"beta"}
    assert _word_sketch_rank_rows(rows, min_freq=3) == []


def test_the_shared_floor_keeps_its_default(monkeypatch):
    tables = _sketch(monkeypatch)
    assert apply_word_sketch_min_freq(tables) == {}
    assert sorted(apply_word_sketch_min_freq(tables, min_freq=0)["obj_rev"]["word"]) == ["beta", "gamma"]


def test_normalization_keeps_a_single_partner_with_f_one():
    tables = {"obj": pd.DataFrame([{"word": "gamma", "f": 1, "chi2_cell": 1.0, "t": 1.0, "ll": 1.0}])}
    assert normalize_word_sketch_tables(tables, "alpha")["obj"]["word"].tolist() == ["gamma"]
