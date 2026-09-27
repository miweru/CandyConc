import numpy as np
import pytest

from candyconc.core.counting_kernels import keyness_chi2_cell_pooled
from candyconc.services.backend import server


def test_keyness_chi2_cell_uses_pooled_target_expectation():
    counts_t = np.asarray([10, 0, 10], dtype=np.uint64)
    counts_r = np.asarray([0, 10, 5], dtype=np.uint64)

    chi2_cell = keyness_chi2_cell_pooled(counts_t, counts_r, total_t=100, total_r=100)

    assert chi2_cell[0] == pytest.approx(5.0)
    assert chi2_cell[1] == pytest.approx(5.0)
    assert chi2_cell[2] == pytest.approx(0.8333333333)


def test_keyness_rows_expose_direction_rates_and_signed_scores(monkeypatch):
    idx = type("Idx", (), {})()
    lex = type("Lex", (), {"offsets": object(), "strings_view": object()})()
    idx.fast_index = type("Fast", (), {"lexicons": type("Lexicons", (), {"word": lex})()})()
    monkeypatch.setattr(server, "strings_for_ids", lambda *_args, **_kwargs: ["target_only", "reference_only"])
    result = {
        "term_ids": np.asarray([1, 2], dtype=np.uint32),
        "target_counts": np.asarray([10, 0], dtype=np.uint64),
        "reference_counts": np.asarray([0, 10], dtype=np.uint64),
        "chi2_cell": np.asarray([5.0, 5.0], dtype=np.float64),
        "ll": np.asarray([13.8, 13.8], dtype=np.float64),
        "total_t": 100,
        "total_r": 100,
    }

    rows = server._keyness_rows_from_result(idx, result, offset=0, limit=10)

    assert rows[0]["direction"] == "target"
    assert rows[0]["target_freq"] == 10
    assert rows[0]["reference_freq"] == 0
    assert rows[0]["target_per_million"] == pytest.approx(100000.0)
    assert rows[0]["reference_per_million"] == pytest.approx(0.0)
    assert rows[0]["chi2_cell_signed"] == pytest.approx(5.0)
    assert rows[1]["direction"] == "reference"
    assert rows[1]["target_per_million"] == pytest.approx(0.0)
    assert rows[1]["reference_per_million"] == pytest.approx(100000.0)
    assert rows[1]["chi2_cell_signed"] == pytest.approx(-5.0)
    assert rows[1]["ll_signed"] == pytest.approx(-13.8)
