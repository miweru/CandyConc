"""Significance and effect-size helpers for keyness statistics.

This module is intentionally self-contained: it depends only on the standard
library, ``numpy`` and ``scipy`` and imports nothing from ``candyconc``.  It
collects the statistical primitives used to turn raw 2x2 contingency counts and
log-likelihood (Dunning G^2) scores into publishable, defensible numbers:

- p-values from the chi-square survival function (df=1),
- multiple-comparison corrections (Bonferroni, Benjamini-Hochberg FDR),
- the Log Ratio effect size (Hardie 2014) with a delta-method confidence
  interval (Katz et al. 1978),
- the conservative Log Ratio (LRC) from an exact conditional Clopper-Pearson
  interval (Evert 2022), and
- a low-frequency reliability flag.

References:
- Dunning, T. (1993). Accurate Methods for the Statistics of Surprise and
  Coincidence.
- Hardie, A. (2014). Log Ratio: an informal introduction. CASS blog. Defines
  the point estimate only, without an interval.
- Katz, D., Baptista, J., Azen, S. P. & Pike, M. C. (1978). Obtaining
  Confidence Intervals for the Risk Ratio in Cohort Studies. Biometrics
  34(3), 469-474. https://doi.org/10.2307/2530610
- Evert, S. (2022). Measuring Keyness. Digital Humanities 2022, Tokyo.
  https://doi.org/10.17605/OSF.IO/CY6MW
- Clopper, C. J. & Pearson, E. S. (1934). The use of confidence or fiducial
  limits illustrated in the case of the binomial. Biometrika 26(4), 404-413.
- Heinrich, P. & Evert, S. (2024). Operationalising the Hermeneutic Grouping Process in Corpus-assisted Discourse Studies.
  Proceedings of the 4th Workshop on Computational Linguistics for the Political and Social Sciences (CPSS), Vienna, 33-44.
  https://aclanthology.org/2024.cpss-1.3/
- Wilson, A. (2013). Embracing Bayes Factors for key item analysis (BIC).
- Benjamini, Y. & Hochberg, Y. (1995). Controlling the False Discovery Rate.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import beta as beta_verteilung, chi2, norm

__all__ = [
    "ll_to_p",
    "bonferroni",
    "bh_fdr",
    "log_ratio_ci",
    "log_ratio_ci_arrays",
    "low_freq_flag",
]


def ll_to_p(ll):
    """Two-sided p-value for a log-likelihood (Dunning G^2) score.

    The G^2 statistic is asymptotically chi-square distributed with one degree
    of freedom for a 2x2 table, so the p-value is the chi-square survival
    function (1 - CDF) evaluated at ``ll`` with ``df=1``.

    Accepts a scalar or an array-like and returns the matching shape. Negative
    inputs (which can only arise from a *signed* score being passed by mistake)
    are clamped to zero magnitude via ``abs`` so the p-value stays in [0, 1].
    """
    arr = np.abs(np.asarray(ll, dtype=np.float64))
    p = chi2.sf(arr, df=1)
    if np.isscalar(ll) or arr.ndim == 0:
        return float(p)
    return p


def bonferroni(pvals):
    """Bonferroni-corrected p-values: ``min(1, p * m)`` for ``m`` tests."""
    arr = np.asarray(pvals, dtype=np.float64)
    m = arr.size
    if m == 0:
        return arr
    corrected = np.minimum(arr * m, 1.0)
    return corrected


def bh_fdr(pvals):
    """Benjamini-Hochberg FDR adjusted p-values (q-values).

    Returns, for each input p-value, the BH-adjusted q-value with the standard
    monotonicity enforcement (step-up): q-values are non-decreasing in the rank
    order of the p-values and capped at 1.0.
    """
    arr = np.asarray(pvals, dtype=np.float64)
    m = arr.size
    if m == 0:
        return arr

    order = np.argsort(arr, kind="mergesort")
    ranked = arr[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    raw = ranked * m / ranks
    # Enforce monotonicity from the largest p downward (step-up procedure).
    q_sorted = np.minimum.accumulate(raw[::-1])[::-1]
    q_sorted = np.minimum(q_sorted, 1.0)

    q = np.empty(m, dtype=np.float64)
    q[order] = q_sorted
    return q


def log_ratio_ci(a, b, n1, n2, alpha=0.05):
    """Confidence interval for the Log Ratio effect size (Katz et al. 1978).

    ``a`` is the frequency of the item in the target corpus of ``n1`` tokens;
    ``b`` is its frequency in the reference corpus of ``n2`` tokens. The point
    estimate is the log2 relative risk with Haldane-Anscombe (+0.5) smoothing::

        LR = log2( ((a + 0.5) / n1) / ((b + 0.5) / n2) )

    The interval is built on the log scale using the delta-method standard
    error of the log relative risk (Katz et al. 1978), then converted to
    log2. Hardie (2014) defines the point estimate only::

        SE_ln = sqrt(1/(a+0.5) - 1/(n1+0.5) + 1/(b+0.5) - 1/(n2+0.5))

    Returns ``(low, high)`` in log2 units, with ``low <= LR <= high``.
    """
    a = float(a)
    b = float(b)
    n1 = float(n1)
    n2 = float(n2)

    a_s = a + 0.5
    b_s = b + 0.5
    rate_t = a_s / n1
    rate_r = b_s / n2

    point = math.log2(rate_t / rate_r)

    # Delta-method SE of the natural-log relative risk (Katz et al. 1978),
    # with the +0.5 continuity adjustment applied consistently.
    var_ln = (
        1.0 / a_s
        - 1.0 / (n1 + 0.5)
        + 1.0 / b_s
        - 1.0 / (n2 + 0.5)
    )
    var_ln = max(var_ln, 0.0)
    se_ln = math.sqrt(var_ln)
    se_log2 = se_ln / math.log(2.0)

    z = float(norm.ppf(1.0 - alpha / 2.0))
    half = z * se_log2
    return (point - half, point + half)


def log_ratio_ci_arrays(a, b, n1, n2, alpha=0.05):
    """Vectorized Log Ratio CI (Katz et al. 1978) over arrays of counts.

    Element-wise equivalent of :func:`log_ratio_ci` for whole candidate sets:
    ``a``/``b`` are array-likes of target/reference frequencies against the
    scalar totals ``n1``/``n2``. Returns ``(point, low, high)`` as float64
    arrays of the same shape, using the identical +0.5 Haldane-Anscombe
    smoothing and Katz delta-method standard error so per-element results match
    the scalar function exactly.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n1 = float(n1)
    n2 = float(n2)

    a_s = a + 0.5
    b_s = b + 0.5
    rate_t = a_s / n1 if n1 > 0.0 else np.zeros_like(a_s)
    rate_r = b_s / n2 if n2 > 0.0 else np.ones_like(b_s)

    point = np.log2(rate_t / rate_r)
    var_ln = (1.0 / a_s) - (1.0 / (n1 + 0.5)) + (1.0 / b_s) - (1.0 / (n2 + 0.5))
    var_ln = np.maximum(var_ln, 0.0)
    se_log2 = np.sqrt(var_ln) / math.log(2.0)

    z = float(norm.ppf(1.0 - alpha / 2.0))
    half = z * se_log2
    return point, point - half, point + half


def conservative_log_ratio_arrays(a, b, n1, n2, *, alpha=0.001, vocab=None):
    """Vectorized conservative log ratio (Evert 2022).

    LRC is the confidence-interval endpoint closest to zero, or 0 when the
    interval includes zero. It expresses the smallest effect compatible
    with the interval and provides a ranking measure for sparse candidates.

    ``vocab`` enables Bonferroni correction over all candidates, using
    ``alpha/vocab`` per test. Without ``vocab``, use the uncorrected ``alpha``.

    The interval is exact and conditional on the marginal ``a + b``.
    Construct a Clopper-Pearson interval for ``p = a / (a + b)`` and
    transform it to the base-2 log ratio with the identity

        log2((a/n1) / (b/n2)) == log2(p / (1 - p)) + log2(n2 / n1)

    The reference values are in Heinrich/Evert (2024), Table 1:
    https://aclanthology.org/2024.cpss-1.3/ (see the module references).

    ``log_ratio_ci_low`` and ``log_ratio_ci_high`` retain the unconditional
    Katz interval from :func:`log_ratio_ci_arrays`. LRC uses the exact
    conditional interval, so it is not an endpoint of those columns.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n1 = float(n1)
    n2 = float(n2)
    if vocab is not None:
        anzahl = max(1, int(vocab))
        alpha = float(alpha) / float(anzahl)
    alpha = float(alpha)

    if n1 <= 0.0 or n2 <= 0.0:
        return np.zeros(np.broadcast(a, b).shape, dtype=np.float64)

    gesamt = a + b
    hat_daten = gesamt > 0.0
    # Clopper-Pearson ueber die Beta-Quantile. Bei a == 0 ist die
    # Untergrenze 0, bei b == 0 die Obergrenze 1: beide Faelle sind
    # zulaessig und werden unten als unendliche Schranke behandelt.
    sicher = np.where(hat_daten, gesamt, 1.0)
    p_lo = np.where(a > 0.0,
                    beta_verteilung.ppf(alpha / 2.0, np.maximum(a, 1e-12),
                                        sicher - a + 1.0),
                    0.0)
    p_hi = np.where(b > 0.0,
                    beta_verteilung.ppf(1.0 - alpha / 2.0, a + 1.0,
                                        np.maximum(sicher - a, 1e-12)),
                    1.0)

    versatz = math.log2(n2 / n1)

    def _in_log_ratio(p, unendlich):
        p = np.asarray(p, dtype=np.float64)
        gueltig = (p > 0.0) & (p < 1.0)
        mit = np.clip(p, 1e-300, 1.0 - 1e-16)
        return np.where(gueltig, np.log2(mit / (1.0 - mit)) + versatz, unendlich)

    unten = _in_log_ratio(p_lo, -np.inf)
    oben = _in_log_ratio(p_hi, np.inf)

    # Die nullnaehere Grenze, und 0, sobald das Intervall die Null enthaelt
    # oder gar keine Beobachtung vorliegt.
    lrc = np.where(unten > 0.0, unten, np.where(oben < 0.0, oben, 0.0))
    lrc = np.where(hat_daten, lrc, 0.0)
    return np.where(np.isfinite(lrc), lrc, 0.0).astype(np.float64, copy=False)


def low_freq_flag(count, threshold=5):
    """Return ``True`` when an observed count is below ``threshold``.

    Low expected/observed cell counts make the chi-square approximation
    unreliable; this flag lets callers warn or down-weight such rows.
    """
    return int(count) < int(threshold)
