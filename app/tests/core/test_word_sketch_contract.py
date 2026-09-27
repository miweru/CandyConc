from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from candyconc.analysis_defaults import normalize_word_sketch_tables
from candyconc.services.backend import server


def test_word_sketch_normalization_adds_stable_score_contract():
    tables = {
        "obj": pd.DataFrame(
            [
                {"word": "Analyse", "f": 4, "chi2_cell": 3.5, "t": 1.2, "ll": 2.0},
                {"word": "Synthese", "f": 20, "chi2_cell": 10.0, "t": 5.0, "ll": 9.0},
            ]
        )
    }

    normalized = normalize_word_sketch_tables(tables, "Korpus")
    rows = normalized["obj"].to_dict("records")

    assert rows[0]["word"] == "Synthese"
    assert rows[0]["frequency"] == 20
    assert rows[0]["score"] == 10.0
    assert rows[0]["score_key"] == "chi2_cell"
    assert rows[0]["rank"] == 1
    assert rows[1]["word"] == "Analyse"
    assert rows[1]["frequency"] == 4
    assert rows[1]["score"] == 3.5
    assert rows[1]["score_key"] == "chi2_cell"
    assert rows[1]["rank"] == 2


def test_word_sketch_normalization_respects_explicit_relation_limit():
    tables = {
        "obj": pd.DataFrame(
            [
                {"word": f"collocate_{idx}", "f": 2, "chi2_cell": float(20 - idx), "t": 1.0, "ll": 1.0}
                for idx in range(12)
            ]
        )
    }

    default_rows = normalize_word_sketch_tables(tables, "alpha")["obj"].to_dict("records")
    requested_rows = normalize_word_sketch_tables(tables, "alpha", top_rows=10)["obj"].to_dict("records")

    assert len(default_rows) == 8
    assert len(requested_rows) == 10
    assert requested_rows[-1]["word"] == "collocate_9"


class _FakeWordLex:
    total_tokens = 100

    def get_id(self, word):
        return {"alpha": 1}.get(word, 0)

    def get_freq(self, word_id):
        return {1: 10, 2: 40}.get(int(word_id), 0)

    def get_string(self, word_id):
        return {1: "alpha", 2: "beta"}.get(int(word_id), f"w{word_id}")


class _FakeRelLex:
    def get_string(self, rel_id):
        return {7: "obj"}.get(int(rel_id), str(rel_id))


class _FakeIndex:
    def __init__(self):
        store = SimpleNamespace(
            get_positions_for_word_id=lambda _term_id: np.array([0, 4, 8], dtype=np.uint32),
            head_ids=np.zeros(12, dtype=np.int64),
            rel_ids=np.zeros(12, dtype=np.uint32),
            word_stream=SimpleNamespace(offsets=None, data=None, block_size=4),
            token_count=12,
        )
        self.fast_index = SimpleNamespace(
            token_store=store,
            lexicons=SimpleNamespace(word=_FakeWordLex(), rel=_FakeRelLex()),
        )

    def docset_token_count(self, docset_ids):
        assert np.asarray(docset_ids, dtype=np.uint32).tolist() == [1]
        return 10

    def frequency_counts_docset(self, docset_ids, *, stopwords=None, pos_prefix=None):
        assert stopwords is None
        assert pos_prefix is None
        assert np.asarray(docset_ids, dtype=np.uint32).tolist() == [1]
        return np.array([1, 2], dtype=np.uint32), np.array([3, 4], dtype=np.uint64)


def test_word_sketch_uses_docset_local_f2_for_docset_scores(monkeypatch):
    idx = _FakeIndex()
    monkeypatch.setattr(
        server,
        "_word_sketch_counts_safe",
        lambda *_args, **_kwargs: ({7: {2: 2}}, {}),
    )
    monkeypatch.setattr(
        server,
        "_filter_positions_by_docset",
        lambda _idx, positions, _mask: positions[:2],
    )
    monkeypatch.setattr(
        server,
        "get_config",
        lambda name, default=None: "0"
        if name == "CANDYCONC_WORD_SKETCH_MASK_MAX_TOKENS"
        else default,
    )

    global_rows = server._word_sketch_for_query(idx, "alpha")["obj_rev"].to_dict("records")
    docset_rows = server._word_sketch_for_query(
        idx,
        "alpha",
        docset_mask=np.array([False, True], dtype=np.bool_),
        docset_ids=np.array([1], dtype=np.uint32),
    )["obj_rev"].to_dict("records")

    assert global_rows[0]["f2_basis"] == "global"
    assert global_rows[0]["f2"] == 40
    assert docset_rows[0]["f2_basis"] == "docset_local"
    assert docset_rows[0]["f2"] == 4
    assert docset_rows[0]["chi2_cell"] == pytest.approx(((2 - 0.8) ** 2) / 0.8)
    assert docset_rows[0]["chi2_cell"] != pytest.approx(global_rows[0]["chi2_cell"])


def test_word_sketch_cql_anchors_use_unique_match_starts_only():
    positions = server._word_sketch_cql_anchor_positions(
        [
            SimpleNamespace(start=5, end=7),
            SimpleNamespace(start=5, end=6),
            SimpleNamespace(start=2, end=2),
            SimpleNamespace(start=1, end=2),
        ]
    )

    assert positions.dtype == np.uint32
    assert positions.tolist() == [1, 5]
