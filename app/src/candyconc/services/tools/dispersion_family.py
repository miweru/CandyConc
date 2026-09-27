"""Corpus dispersion family — Juilland's D, Carroll's D2, Range and VC.

This module is the single source of truth for the *dispersion-family* measures
that complement Gries' Deviation of Proportions (DP). All measures operate over
the SAME per-document distribution the DP path already produces: a vector of
per-part observed counts ``o_i`` and a vector of per-part token sizes ``s_i``
(see ``server._gries_dp_documents`` / ``analysis_defaults._document_dispersion``).
Re-using that distribution guarantees every measure partitions the corpus the
same way, so they are mutually comparable on one response.

Measures implemented (n = number of parts, F = sum o_i, N = sum s_i):

- ``range`` / ``range_prop``
    Range = number of parts with at least one occurrence. ``range_prop`` is the
    same divided by ``n`` (the proportion of parts the word reaches), so it is
    comparable across corpora with different part counts. ``range`` is also the
    plain integer count of nonzero parts.

- ``vc`` (variation coefficient)
    VC = sigma / mean of the per-part *normalized* frequencies
    ``v_i = o_i / s_i`` (relative frequency within each part), using the
    POPULATION standard deviation (``ddof=0``). VC is scale-invariant, so the
    common per-million scaling of ``v_i`` cancels and is omitted. Lower VC means
    a more even spread. Undefined (returned as 0.0) when the mean is 0 or n<2.

- ``juilland_d`` (Juilland & Chang-Rodriguez 1964)
    D = 1 - VC / sqrt(n - 1), bounded to [0, 1]. 1.0 = perfectly even, 0.0 =
    maximally clustered. Built on the per-part normalized frequencies ``v_i``
    so it accounts for unequal part sizes. Degenerate (n<2 or F<=0) -> 0.0:
    an absent term (zero total frequency) returns 0.0, not 1.0, to stay
    consistent with the rest of the family.

- ``carroll_d2`` (Carroll 1970, normalized entropy D2)
    D2 = H / log(n) with H = -sum_i p_i * ln(p_i), p_i = o_i / F (the share of
    all occurrences falling in part i; zero-count parts contribute nothing).
    Bounded to [0, 1]; 1.0 = even, 0.0 = all occurrences in a single part.
    Degenerate (n<2 or F<=0) -> 0.0.

The return dict deliberately mirrors the DP contract (``dp`` / ``dpnorm``) by
re-using ``server._gries_dp_documents`` so a route can emit one merged block:
``{dp, dpnorm, juilland_d, carroll_d2, range, range_prop, vc}``.

References:
- Juilland, A. & Chang-Rodriguez, E. (1964). Frequency Dictionary of Spanish Words.
- Carroll, J. B. (1970). An alternative to Juilland's usage coefficient ... .
- Gries, S. Th. (2008/2020). Dispersions and adjusted frequencies in corpora.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "dispersion_family",
    "range_count",
    "range_proportion",
    "variation_coefficient",
    "juilland_d",
    "carroll_d2",
]


def _as_float_pair(
    counts: "np.ndarray | list[int]",
    sizes: "np.ndarray | list[int]",
) -> tuple[np.ndarray, np.ndarray]:
    obs = np.asarray(counts, dtype=np.float64).ravel()
    siz = np.asarray(sizes, dtype=np.float64).ravel()
    return obs, siz


def range_count(counts: "np.ndarray | list[int]") -> int:
    """Number of parts containing at least one occurrence (integer Range)."""
    obs = np.asarray(counts, dtype=np.float64).ravel()
    return int(np.count_nonzero(obs > 0.0))


def range_proportion(counts: "np.ndarray | list[int]") -> float:
    """Range normalized by the number of parts (in [0, 1])."""
    obs = np.asarray(counts, dtype=np.float64).ravel()
    n = int(obs.size)
    if n <= 0:
        return 0.0
    return float(np.count_nonzero(obs > 0.0)) / float(n)


def variation_coefficient(
    counts: "np.ndarray | list[int]",
    sizes: "np.ndarray | list[int]",
) -> float:
    """Variation coefficient of the per-part normalized frequencies v_i=o_i/s_i.

    Uses the population standard deviation (ddof=0) so it matches the Juilland D
    convention. Returns 0.0 for degenerate input (n < 2, all-zero, or a zero
    mean), never NaN/inf.
    """
    obs, siz = _as_float_pair(counts, sizes)
    n = int(obs.size)
    if n < 2 or siz.size != obs.size:
        return 0.0
    # Normalized per-part frequency; guard divide-by-zero on empty parts.
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(siz > 0.0, obs / siz, 0.0)
    mean_v = float(v.mean())
    if mean_v <= 0.0:
        return 0.0
    sd_v = float(v.std(ddof=0))
    vc = sd_v / mean_v
    if not np.isfinite(vc):
        return 0.0
    return float(vc)


def juilland_d(
    counts: "np.ndarray | list[int]",
    sizes: "np.ndarray | list[int]",
) -> float:
    """Juilland's D = 1 - VC / sqrt(n - 1), clamped to [0, 1].

    An absent term (total count <= 0) returns 0.0, NOT 1.0. With no
    occurrences VC collapses to 0, which would otherwise yield D = 1.0
    ("perfectly even") for a word that does not occur at all. Returning 0.0
    keeps an absent term consistent with the rest of the family
    (carroll_d2 / range / range_prop / vc all return 0) and with the frontend
    hint "1 = sehr gleichmäßig · 0 = stark geklumpt".
    """
    obs, _siz = _as_float_pair(counts, sizes)
    n = int(obs.size)
    if n < 2:
        return 0.0
    # Absent term: no occurrences -> collapse to 0.0 like the rest of the family
    # (avoid the degenerate D = 1.0 "perfectly even" for a word that never occurs).
    if float(obs.sum()) <= 0.0:
        return 0.0
    vc = variation_coefficient(counts, sizes)
    d = 1.0 - vc / np.sqrt(float(n - 1))
    if not np.isfinite(d):
        return 0.0
    return float(min(1.0, max(0.0, d)))


def carroll_d2(counts: "np.ndarray | list[int]") -> float:
    """Carroll's normalized entropy D2 = H / log(n), clamped to [0, 1]."""
    obs = np.asarray(counts, dtype=np.float64).ravel()
    n = int(obs.size)
    if n < 2:
        return 0.0
    total = float(obs.sum())
    if total <= 0.0:
        return 0.0
    p = obs / total
    nz = p > 0.0
    if not np.any(nz):
        return 0.0
    h = -float(np.sum(p[nz] * np.log(p[nz])))
    denom = np.log(float(n))
    if denom <= 0.0:
        return 0.0
    d2 = h / denom
    if not np.isfinite(d2):
        return 0.0
    return float(min(1.0, max(0.0, d2)))


def dispersion_family(
    counts: "np.ndarray | list[int]",
    sizes: "np.ndarray | list[int]",
    *,
    gries_dp: Any = None,
) -> dict[str, float | int]:
    """Compute the full dispersion family over a per-part distribution.

    Parameters
    - ``counts``: per-part observed hit counts ``o_i`` (one entry per part).
    - ``sizes``: per-part token sizes ``s_i`` (same length as ``counts``).
    - ``gries_dp``: optional callable ``(counts, sizes) -> {"dp", "dpnorm"}``
      (i.e. ``server._gries_dp_documents``). When supplied, its ``dp`` /
      ``dpnorm`` are merged into the returned block so a route emits ONE
      dispersion object. When omitted, ``dp`` / ``dpnorm`` are computed locally
      via the identical formula (no engine dependency), so the module is usable
      standalone and golden-testable.

    Returns a dict with the keys (the downstream contract):
    ``{dp, dpnorm, juilland_d, carroll_d2, range, range_prop, vc}``.
    """
    obs, siz = _as_float_pair(counts, sizes)
    if obs.size != siz.size:
        siz = np.zeros_like(obs)

    if gries_dp is not None:
        dp_block = gries_dp(obs, siz)
        dp = float(dp_block.get("dp", 0.0))
        dpnorm = float(dp_block.get("dpnorm", 0.0))
    else:
        dp, dpnorm = _gries_dp_local(obs, siz)

    return {
        "dp": dp,
        "dpnorm": dpnorm,
        "juilland_d": juilland_d(obs, siz),
        "carroll_d2": carroll_d2(obs),
        "range": range_count(obs),
        "range_prop": range_proportion(obs),
        "vc": variation_coefficient(obs, siz),
    }


def _gries_dp_local(obs: np.ndarray, sizes: np.ndarray) -> tuple[float, float]:
    """Standalone Gries DP / DPnorm over real part sizes.

    Identical formula to ``server._gries_dp_documents`` (expected_i = s_i / N),
    duplicated here only so ``dispersion_family`` works without importing the
    server module. Routes pass ``gries_dp=server._gries_dp_documents`` to keep a
    single source of truth at runtime.
    """
    if obs.size == 0 or sizes.size == 0 or obs.size != sizes.size:
        return 0.0, 0.0
    total_freq = float(obs.sum())
    total_tokens = float(sizes.sum())
    if total_freq <= 0.0 or total_tokens <= 0.0 or obs.size <= 1:
        return 0.0, 0.0
    expected = sizes / total_tokens
    observed = obs / total_freq
    dp = 0.5 * float(np.abs(observed - expected).sum())
    min_expected = float(expected.min())
    denom = 1.0 - min_expected
    dpnorm = float(dp / denom) if denom > 0.0 else 0.0
    return dp, dpnorm
