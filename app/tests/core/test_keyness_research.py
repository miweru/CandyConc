"""Golden tests for release-grade keyness (Track FT-KEYNESS-RESEARCH).

Covers: min_freq filtering applied BEFORE the inferential statistics (so the
BH-FDR test count m shrinks), the low_reliability (E_min<5) flag, the external
reference-list path, and p/q values cross-checked against scipy.
"""

import numpy as np
import pytest
from scipy.stats import chi2 as _scipy_chi2

from candyconc.services.tools.keyness import (
    DEFAULT_MIN_FREQ,
    RELIABILITY_EXPECTED_MIN,
    complement_docset_ids,
    compute_keyness_counts,
    compute_keyness_external,
    expected_min_cell,
    normalize_disjoint_docsets,
    validate_external_reference,
)


def test_min_freq_drops_low_frequency_candidates_before_stats():
    freq_t = {"frequent": 50, "mid": 6, "singleton": 1}
    freq_r = {"frequent": 10, "mid": 0, "other": 1}
    # min_freq=5 on combined a+c: frequent=60, mid=6, singleton=1, other=1.
    df = compute_keyness_counts(freq_t, freq_r, 1000, 1000, min_freq=5)
    kept = set(df["word"].tolist())
    assert kept == {"frequent", "mid"}
    assert "singleton" not in kept
    assert "other" not in kept


def test_min_freq_changes_q_values_via_test_count_m():
    # Add many singletons that survive WITHOUT min_freq but are dropped WITH it.
    freq_t = {"frequent": 50}
    freq_r = {"frequent": 10}
    for i in range(40):
        freq_t[f"noise_{i}"] = 1  # combined freq 1 each -> dropped by min_freq=5

    df_off = compute_keyness_counts(dict(freq_t), dict(freq_r), 1000, 1000, min_freq=0)
    df_on = compute_keyness_counts(dict(freq_t), dict(freq_r), 1000, 1000, min_freq=5)

    # Fewer candidates with the filter on -> smaller m -> the surviving row's
    # q-value is no larger (BH q = p * m / rank, m strictly smaller here).
    q_off = float(df_off.loc[df_off["word"] == "frequent", "q_value"].iloc[0])
    q_on = float(df_on.loc[df_on["word"] == "frequent", "q_value"].iloc[0])
    assert len(df_on) < len(df_off)
    assert q_on <= q_off + 1e-12
    assert q_on < q_off  # m genuinely shrank from 41 to 1


def test_low_reliability_flag_matches_expected_min_rule():
    freq_t = {"reliable": 80, "rare": 2}
    freq_r = {"reliable": 60, "other": 80}
    df = compute_keyness_counts(freq_t, freq_r, 1000, 1000)
    assert "low_reliability" in df.columns
    assert "expected_min" in df.columns
    for _, row in df.iterrows():
        assert bool(row["low_reliability"]) == (
            float(row["expected_min"]) < RELIABILITY_EXPECTED_MIN
        )


def test_expected_min_cell_matches_hand_2x2():
    # a=10 c=2, N_t=100 N_r=100 -> N=200. Marginals row1=100,row2=100,
    # col1=12,col2=188. E = [6,94,6,94] -> E_min = 6.
    e = expected_min_cell(np.array([10]), np.array([2]), 100, 100)
    assert float(e[0]) == pytest.approx(6.0)


def test_p_value_matches_scipy_chi2_sf_on_g2():
    df = compute_keyness_counts({"w": 30}, {"w": 5}, 1000, 1000)
    row = df.iloc[0]
    g2 = abs(float(row["ll"]))
    expected_p = float(_scipy_chi2.sf(g2, df=1))
    assert float(row["p_value"]) == pytest.approx(expected_p, rel=1e-9)


def test_external_reference_path_scores_target_against_freq_list():
    # External German-reference-style frequency list with its own total.
    reference_list = {"und": 50000, "der": 48000, "KI": 12}
    target = {"KI": 40, "Modell": 25, "und": 100}
    df = compute_keyness_external(
        target,
        reference_list,
        total_t=2000,
        reference_total=1_000_000,
        min_freq=0,
    )
    words = set(df["word"].tolist())
    # Candidate union spans both sides; "Modell" (target-only) scores against
    # reference freq 0 and is over-represented in the target.
    assert "Modell" in words
    row_modell = df.loc[df["word"] == "Modell"].iloc[0]
    assert int(row_modell["reference_freq"]) == 0
    assert row_modell["direction"] == "target"
    assert float(row_modell["ll_signed"]) > 0.0


def test_external_reference_total_defaults_to_list_sum():
    reference_list = {"a": 30, "b": 70}
    df = compute_keyness_external({"a": 10}, reference_list, total_t=100)
    # reference_total defaults to sum(list) = 100; reference per-million for "a"
    # = 30/100 * 1e6 = 300000.
    row_a = df.loc[df["word"] == "a"].iloc[0]
    assert float(row_a["reference_per_million"]) == pytest.approx(300000.0)


def test_external_reference_contract_is_complete_casefolded_and_pos_matched():
    reference, total, scope = validate_external_reference(
        {"Die": 2, "die": 3, "Häuser": 1},
        reference_total=6,
        vocabulary_complete=True,
        target_pos="NOUN",
        reference_pos="NOUN",
    )
    assert reference == {"die": 5, "häuser": 1}
    assert total == 6
    assert scope == "NOUN"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference_total": 1, "vocabulary_complete": False, "target_pos": None, "reference_pos": None},
        {"reference_total": 0, "vocabulary_complete": True, "target_pos": None, "reference_pos": None},
        {"reference_total": 3, "vocabulary_complete": True, "target_pos": None, "reference_pos": None},
        {"reference_total": 2, "vocabulary_complete": True, "target_pos": "NOUN", "reference_pos": "VERB"},
    ],
)
def test_external_reference_contract_rejects_incomplete_or_incomparable_input(kwargs):
    with pytest.raises(ValueError):
        validate_external_reference({"wort": 2}, **kwargs)


def test_keyness_docsets_are_normalized_disjoint_and_complemented():
    target, reference = normalize_disjoint_docsets([2, 0, 2], [3, 1, 3])
    assert target.tolist() == [0, 2]
    assert reference.tolist() == [1, 3]
    assert complement_docset_ids(target, doc_count=4).tolist() == [1, 3]
    with pytest.raises(ValueError, match="gemeinsamen"):
        normalize_disjoint_docsets([0, 1], [1, 2])
    with pytest.raises(ValueError, match="gültige Dokument-ID"):
        normalize_disjoint_docsets([-1], [2])


def test_default_min_freq_constant_is_five():
    assert DEFAULT_MIN_FREQ == 5
    assert RELIABILITY_EXPECTED_MIN == 5.0
