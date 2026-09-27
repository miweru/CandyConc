"""R6 golden tests: copilot-path dispersion must converge with the REST spec.

The corrected REST dispersion is DOCUMENT-based:

    expected_i = doc_size_i / N           (NOT 1/n)
    observed_i = hits in document i
    F          = total hits
    dp     = 0.5 * sum_i |observed_i / F - expected_i|     (RAW Gries DP)
    dpnorm = dp / (1 - min_i expected_i)

These tests recompute DP by hand over the REAL document boundaries of the bench
index and assert that ``summarize_dispersion_offsets`` (the copilot path) matches
to rtol 1e-6 -- AND that it uses the SAME boundary source the REST path uses
(``server._doc_bounds_for_index``), so copilot and REST cannot diverge.

Requires the bench index at CANDYCONC_INDEX_PATH.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from candyconc.analysis_defaults import summarize_dispersion_offsets
from candyconc.core.corpus_index import CorpusIndex
from candyconc.services.backend import server


_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")


pytestmark = pytest.mark.skipif(
    not (_INDEX_PATH and os.path.isdir(_INDEX_PATH)),
    reason="bench index (CANDYCONC_INDEX_PATH) required for dispersion golden",
)


@pytest.fixture(scope="module")
def bench_index() -> CorpusIndex:
    return CorpusIndex(_INDEX_PATH)


def _hand_document_dp(
    offsets: np.ndarray,
    doc_bounds: np.ndarray,
    token_count: int,
) -> tuple[float, float, int, int]:
    """Reference implementation of the corrected REST document-DP spec."""
    offs = np.asarray(offsets, dtype=np.int64)
    offs = offs[offs >= 0]
    F = int(offs.size)
    n = int(doc_bounds.size)
    doc_idx = np.searchsorted(doc_bounds, offs, side="right") - 1
    doc_idx = doc_idx[(doc_idx >= 0) & (doc_idx < n)]
    observed = np.bincount(doc_idx, minlength=n).astype(np.int64)
    ends = np.empty_like(doc_bounds)
    ends[:-1] = doc_bounds[1:]
    ends[-1] = int(token_count)
    doc_sizes = ends - doc_bounds
    expected = doc_sizes.astype(np.float64) / float(token_count)
    if F > 0:
        dp = 0.5 * float(np.sum(np.abs(observed.astype(np.float64) / F - expected)))
    else:
        dp = 0.0
    denom = 1.0 - float(expected.min())
    dpnorm = float(dp / denom) if denom > 0 else 0.0
    nonzero = int(np.count_nonzero(observed))
    return dp, dpnorm, F, nonzero


# A strongly clustered term (rare, few documents) and a relatively even one
# (frequent, spread across many documents) on the social-human bench index.
@pytest.mark.parametrize("term", ["Klima", "die", "ich"])
def test_document_dp_matches_hand_and_rest_boundary_source(bench_index, term) -> None:
    idx = bench_index
    token_count = int(idx.token_count())

    # SAME boundary source the REST path uses -> guarantees convergence.
    doc_bounds = server._doc_bounds_for_index(idx).astype(np.int64)
    assert np.array_equal(
        doc_bounds,
        idx.fast_index.boundaries.document._positions.astype(np.int64),
    )

    offsets = idx.sequence_positions([term])

    out = summarize_dispersion_offsets(
        offsets,
        token_count=token_count,
        doc_bounds=doc_bounds,
    )

    hand_dp, hand_dpnorm, F, nonzero = _hand_document_dp(
        np.asarray(offsets, dtype=np.int64), doc_bounds, token_count
    )

    assert F > 0, f"term {term!r} not found in bench index"
    assert out["unit"] == "documents"
    assert out["total_hits"] == F
    assert out["nonzero_partitions"] == nonzero
    # dp is the RAW Gries DP; dpnorm is the normalized variant.
    assert np.isclose(out["dp"], hand_dp, rtol=1e-6)
    assert np.isclose(out["dpnorm"], hand_dpnorm, rtol=1e-6)
    # Raw and normalized must differ structurally (norm divides by < 1) but both
    # in [0, 1]; for a non-degenerate corpus dpnorm >= dp.
    assert 0.0 <= out["dp"] <= 1.0
    assert out["dpnorm"] >= out["dp"] - 1e-9
    # Document mode never leaks the positional-window field under any name.
    assert "positional_dp_windowed" not in out


def test_clustered_term_is_more_dispersed_than_even_term(bench_index) -> None:
    idx = bench_index
    token_count = int(idx.token_count())
    doc_bounds = server._doc_bounds_for_index(idx).astype(np.int64)

    clustered = summarize_dispersion_offsets(
        idx.sequence_positions(["Klima"]),
        token_count=token_count,
        doc_bounds=doc_bounds,
    )
    even = summarize_dispersion_offsets(
        idx.sequence_positions(["die"]),
        token_count=token_count,
        doc_bounds=doc_bounds,
    )
    # Higher DP == more clustered. Klima (4 hits, 4 docs) >> die (1028 hits, 751 docs).
    assert clustered["dp"] > even["dp"]
    # ABER: "Klima" hat VIER Treffer in VIER Dokumenten. Das ist die
    # gleichmaessigste Verteilung, die vier Treffer haben koennen, nicht
    # die geklumpteste. Die alte Fassung nannte es strongly_clustered,
    # weil dp nahe 1 liegt, und dp liegt bei vier Treffern auf 2000
    # Dokumente IMMER nahe 1. Die erreichbare Spanne ist dort so schmal,
    # dass das Mass nichts unterscheiden kann.
    assert clustered["profile"] == "zu_wenig_treffer", clustered["profile"]


def test_dieselben_treffer_geklumpt_und_gleichmaessig_bekommen_verschiedene_etiketten() -> None:
    """Die POSITIVE KLASSE der Umstellung, und ihr staerkster Beleg.

    Zweihundert Treffer, einmal alle in EINEM Dokument, einmal verteilt
    auf zweihundert. Unter den festen Schnittpunkten hiessen BEIDE
    strongly_clustered, weil beide ueber 0,8 liegen: 0,9980 und 0,9000.
    Gegen die jeweilige Nullverteilung (0,9048) trennen sie sich.

    Ohne diesen Test waere eine Fassung gruen, die alles
    zu_wenig_treffer oder alles fairly_even nennt.
    """
    grenzen = np.arange(0, 2000 * 50, 50, dtype=np.int64)
    gesamt = 2000 * 50

    geklumpt = summarize_dispersion_offsets(
        np.arange(0, 200, dtype=np.int64),
        token_count=gesamt, doc_bounds=grenzen)
    verteilt = summarize_dispersion_offsets(
        np.array([i * 50 + 1 for i in range(200)], dtype=np.int64),
        token_count=gesamt, doc_bounds=grenzen)

    assert geklumpt["profile"] == "strongly_clustered", geklumpt["profile"]
    assert verteilt["profile"] == "fairly_even", verteilt["profile"]
    # Beide liegen ueber dem alten Schnittpunkt 0,8 und waeren dort
    # ununterscheidbar gewesen.
    assert geklumpt["dp"] > 0.8 and verteilt["dp"] > 0.8
    # Und die Trennung kommt aus der Nullverteilung, nicht aus dp allein.
    assert verteilt["dp"] <= verteilt["dp_erwartet"] < geklumpt["dp"]


def test_document_dp_equals_default_no_partitions_argument(bench_index) -> None:
    """The partitions=10 default is gone; document mode is the default unit."""
    idx = bench_index
    token_count = int(idx.token_count())
    doc_bounds = server._doc_bounds_for_index(idx).astype(np.int64)
    offsets = idx.sequence_positions(["ich"])

    # No ``partitions`` passed at all -> still document mode, identical numbers.
    out = summarize_dispersion_offsets(
        offsets, token_count=token_count, doc_bounds=doc_bounds
    )
    hand_dp, hand_dpnorm, _, _ = _hand_document_dp(
        np.asarray(offsets, dtype=np.int64), doc_bounds, token_count
    )
    assert np.isclose(out["dp"], hand_dp, rtol=1e-6)
    assert np.isclose(out["dpnorm"], hand_dpnorm, rtol=1e-6)


def test_positional_fallback_is_distinct_and_never_sets_dp() -> None:
    """Without doc_bounds, the windowed fallback must not populate ``dp``."""
    out = summarize_dispersion_offsets([1, 2, 3, 80, 95], token_count=100)
    assert out["unit"] == "positional_windows"
    assert "dp" not in out
    assert "dpnorm" not in out
    assert "positional_dp_windowed" in out
    assert 0.0 <= out["positional_dp_windowed"] <= 1.0
