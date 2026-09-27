from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd
import polars as pl
import numpy as np
from collections import OrderedDict

from candyconc.i18n import lt


# ---------------------------------------------------------------------------
# Word-sketch per-row scorer — single source of truth (Track DT-WORD-SKETCH-ZOMBIE)
#
# BOTH the REST path (server._word_sketch_for_query) and the copilot path
# (tools.word_sketch.word_sketch) must score a (relation, collocate) cell with
# the SAME math. The corrected statistic is the full 2x2 Dunning G^2 (NOT the
# single-cell 2*O*ln(O/E) approximation, which goes negative and is not
# chi-square distributed) plus a signed variant for ranking. ``word_sketch_g2``
# is byte-identical to server._g2_2x2; ``word_sketch_score_row`` returns the
# full row dict both callers build their tables from.
# ---------------------------------------------------------------------------
def word_sketch_g2(obs: float, f1: float, f2: float, n: float) -> float:
    """Full 2x2 Dunning log-likelihood G^2 for a co-occurrence cell.

    ``obs`` = O11 (joint count), ``f1`` = node marginal (term_count), ``f2`` =
    collocate marginal, ``n`` = corpus token total. Returns
    ``2 * sum_ij O_ij * ln(O_ij / E_ij)`` over all four cells, each term 0 when
    its observed cell is <= 0 (this absorbs degenerate tables where a window
    count exceeds a marginal). Result is >= 0. Mirrors server._g2_2x2 exactly
    so the REST and copilot word-sketch paths produce identical scores.
    """
    if n <= 0 or f1 <= 0 or f2 <= 0:
        return 0.0
    o11 = float(obs)
    o12 = float(f1) - o11
    o21 = float(f2) - o11
    o22 = float(n) - float(f1) - float(f2) + o11
    e11 = float(f1) * float(f2) / float(n)
    e12 = float(f1) * (float(n) - float(f2)) / float(n)
    e21 = (float(n) - float(f1)) * float(f2) / float(n)
    e22 = (float(n) - float(f1)) * (float(n) - float(f2)) / float(n)
    g2 = 0.0
    for o, e in ((o11, e11), (o12, e12), (o21, e21), (o22, e22)):
        if o > 0.0 and e > 0.0:
            g2 += o * math.log(o / e)
    return float(2.0 * g2) if g2 > 0.0 else 0.0


def word_sketch_score_row(
    word: str,
    obs: int,
    term_count: int,
    f2: int,
    total: int,
    *,
    f2_basis: str | None = None,
) -> dict[str, Any]:
    """Score one (collocate ``word``) row for a word sketch.

    Computes the cell statistics shared by BOTH word-sketch implementations:
    ``chi2_cell`` (single target-cell Pearson contribution), ``t`` (t-score),
    ``ll`` (full 2x2 Dunning G^2 via
    :func:`word_sketch_g2`) and ``ll_signed`` (G^2 carrying the over/under-
    representation sign). Ranking uses ``ll_signed`` descending.

    Parameters mirror the 2x2 marginals: ``obs`` = O11 (co-occurrence count),
    ``term_count`` = node marginal, ``f2`` = collocate marginal, ``total`` =
    corpus token total. ``f2_basis`` ("global" / "docset_local") is attached
    when given so docset-scoped sketches stay self-describing.
    """
    obs_f = float(obs)
    exp = (term_count * f2 / total) if total else 0.0
    chi2_cell = ((obs_f - exp) ** 2) / exp if exp else 0.0
    t = (obs_f - exp) / math.sqrt(obs_f) if obs_f > 0.0 else 0.0
    ll = word_sketch_g2(obs_f, float(term_count), float(f2), float(total))
    ll_signed = ll if obs_f >= exp else -ll
    # logDice (Rychlý 2008): Dice coefficient on a shifted log2 scale. Corpus-size
    # independent (uses only O11 + the two marginals, not N), bounded (max 14),
    # and hapax-robust — the default word-sketch ranking, consistent with the
    # collocations default. Computed from the SAME marginals as chi2_cell/ll above.
    denom = float(term_count) + float(f2)
    dice = (2.0 * obs_f / denom) if denom > 0.0 else 0.0
    logdice = 14.0 + math.log2(dice) if dice > 0.0 else 0.0
    row: dict[str, Any] = {
        "word": word,
        "f": int(obs),
        "f2": int(f2),
        "chi2_cell": chi2_cell,
        "t": t,
        "ll": ll,
        "ll_signed": ll_signed,
        "dice": dice,
        "logdice": logdice,
    }
    if f2_basis is not None:
        row["f2_basis"] = f2_basis
    return row


# ---------------------------------------------------------------------------
# Statistical provenance — single source of truth (Track F1)
#
# METHOD_META is the ONE authoritative description of every association /
# keyness / diversity statistic the backend emits. It replaces the four
# hand-maintained Vue copies (KeynessTab.vue / CollocationsTab.vue formula
# blocks) so a script, the copilot trace, and the frontend all read the
# SAME formula, smoothing note and default sort key.
#
# Each entry carries:
#   name          human-readable statistic name (German UI label)
#   latex_formula a self-contained LaTeX expression of the implemented math
#   smoothing     smoothing / continuity correction note ("none" when exact)
#   sort_key      response field a sensible default ranking sorts on (desc)
#
# The LaTeX strings mirror the *implemented* math verbatim (verified against
# core/significance.py and core/collocation_engine.py), NOT a textbook ideal.
# ---------------------------------------------------------------------------
METHOD_META: dict[str, dict[str, str]] = {
    # --- Collocation association measures (window-based) ---
    "logdice": {
        "name": "logDice",
        "latex_formula": r"14 + \log_2\!\left(\frac{2\,O_{11}}{f_1 + f_2}\right)",
        "smoothing": "none",
        "sort_key": "dice",
    },
    # Nur auf den Kollokationsflaechen belegt, dort aber als Spalte
    # ausgeliefert. Ohne Eintrag HIER fuehrt method_statistics sie nicht, und
    # der Methodensteckbrief verschweigt eine Zahl, die im Ergebnis steht.
    "logdice_window": {
        "name": lt("logDice (Fenster-Randsummen)", "logDice (window marginals)"),
        "latex_formula": r"14 + \log_2\!\left(\frac{2\,O_{11}}{R_1 + C_1}\right)",
        "smoothing": "none",
        "sort_key": "logdice_window",
    },
    "dice": {
        "name": "Dice",
        "latex_formula": r"\frac{2\,O_{11}}{f_1 + f_2}",
        "smoothing": "none",
        "sort_key": "dice",
    },
    "mi": {
        "name": "Mutual Information (MI)",
        "latex_formula": r"\log_2\!\left(\frac{O_{11}}{E_{11}}\right),\quad E_{11} = \frac{R_1 \cdot C_1}{N_\Omega}",
        "smoothing": "none",
        "sort_key": "mi",
    },
    # MI3 (Oakes 1998): cubed observed count over the SAME O/E pair as MI —
    # mi3 = log2(O11^3 / E11) = MI + 2*log2(O11). Damps MI's low-frequency bias.
    "mi3": {
        "name": lt("MI3 (kubische MI)", "MI3 (cubic MI)"),
        "latex_formula": r"\log_2\!\left(\frac{O_{11}^{3}}{E_{11}}\right)",
        "smoothing": "none",
        "sort_key": "mi3",
    },
    "lmi": {
        "name": "Local MI (LMI)",
        "latex_formula": r"O_{11} \cdot \log_2\!\left(\frac{O_{11}}{E_{11}}\right)",
        "smoothing": "none",
        "sort_key": "lmi",
    },
    "npmi": {
        "name": "Normalized PMI",
        # Pair-event collocation: p_xy = O11/N_Omega, never O11/u. This keeps
        # NPMI in [-1, 1] in the same event space as MI and G².
        "latex_formula": r"\frac{\log_2(O_{11}/E_{11})}{-\log_2(O_{11}/N_\Omega)}",
        "smoothing": "none",
        "sort_key": "npmi",
    },
    "t": {
        "name": lt("t-Score", "t-score"),
        "latex_formula": r"\frac{O_{11} - E_{11}}{\sqrt{O_{11}}}",
        "smoothing": "none",
        "sort_key": "t",
    },
    "z": {
        "name": lt("z-Score", "z-score"),
        "latex_formula": r"\frac{O_{11} - E_{11}}{\sqrt{E_{11}}}",
        "smoothing": "none",
        "sort_key": "z",
    },
    "chi2_cell": {
        "name": lt("Chi-square Zellbeitrag", "Chi-square cell contribution"),
        "latex_formula": r"\frac{(O_{11} - E_{11})^2}{E_{11}}",
        # Pair-event marginals make the contingency table valid without a
        # continuity correction or fabricated observed data.
        "smoothing": "none",
        "sort_key": "chi2_cell",
    },
    "ll": {
        "name": "Log-Likelihood (G^2)",
        "latex_formula": r"2 \sum_{ij} O_{ij}\,\ln\!\left(\frac{O_{ij}}{E_{ij}}\right)",
        "smoothing": "none",
        "sort_key": "ll",
    },
    # --- Directional association (delta-P, Gries 2013) ---
    # delta_p_nc / delta_p_cn are the two ASYMMETRIC directional probabilities
    # implemented in core.collocation_engine._delta_p_arrays. The 2x2 cells are
    # O11 = co-occurrence count, R1 = context-pair mass, C1 = collocate-pair
    # marginal, N_Omega = anchor-count x scoped token count. Both lie in [-1, 1];
    # degenerate denominators yield 0.0 (no smoothing).
    "delta_p_nc": {
        "name": lt("Delta-P (Knoten -> Kollokat)", "Delta P (node -> collocate)"),
        "latex_formula": (
            r"\Delta P_{n\to c} = P(c \mid n) - P(c \mid \lnot n) "
            r"= \frac{O_{11}}{R_1} - \frac{C_1 - O_{11}}{N_\Omega - R_1}"
        ),
        "smoothing": "none",
        "sort_key": "delta_p_nc",
    },
    "delta_p_cn": {
        "name": lt("Delta-P (Kollokat -> Knoten)", "Delta P (collocate -> node)"),
        "latex_formula": (
            r"\Delta P_{c\to n} = P(n \mid c) - P(n \mid \lnot c) "
            r"= \frac{O_{11}}{C_1} - \frac{R_1 - O_{11}}{N_\Omega - C_1}"
        ),
        "smoothing": "none",
        "sort_key": "delta_p_cn",
    },
    # --- Keyness statistics (docset vs docset) ---
    # chi2 / chi2_signed are the FULL 2x2 Pearson chi-square (df=1) implemented
    # in services.tools.keyness.chi2_2x2_pooled(correction=False): summed over
    # ALL four cells against pooled expecteds E_ij = (row_i * col_j) / N with
    # N = N_t + N_r, no Yates correction. Distinct from chi2_cell (single
    # target-cell contribution). chi2_signed multiplies by sign(diff_per_million).
    "chi2": {
        "name": "Chi-square (2x2 Pearson, df=1)",
        "latex_formula": (
            r"\chi^2 = \sum_{ij} \frac{(O_{ij} - E_{ij})^2}{E_{ij}},\quad "
            r"E_{ij} = \frac{\text{row}_i \cdot \text{col}_j}{N}"
        ),
        "smoothing": "none",
        "sort_key": "chi2",
    },
    "chi2_signed": {
        "name": lt("Signiertes Chi-square (2x2 Pearson)", "Signed chi-square (2x2 Pearson)"),
        "latex_formula": (
            r"\operatorname{sign}(\Delta_{pm}) \cdot \sum_{ij} "
            r"\frac{(O_{ij} - E_{ij})^2}{E_{ij}}"
        ),
        "smoothing": "none",
        "sort_key": "chi2_signed",
    },
    "ll_signed": {
        "name": lt("Signiertes Log-Likelihood", "Signed log-likelihood"),
        "latex_formula": (
            r"\operatorname{sign}(\Delta_{pm}) \cdot 2 \sum_{ij} O_{ij}\,"
            r"\ln\!\left(\frac{O_{ij}}{E_{ij}}\right)"
        ),
        "smoothing": "none",
        "sort_key": "ll_signed",
    },
    "log_ratio": {
        "name": "Log Ratio (Hardie)",
        "latex_formula": (
            r"\log_2\!\left(\frac{(O_{11}+0.5)/N_t}{(O_{21}+0.5)/N_r}\right)"
        ),
        "smoothing": "Haldane-Anscombe +0.5",
        "sort_key": "log_ratio",
    },
    "lrc": {
        "name": lt("Konservatives Log Ratio (Evert 2022)", "Conservative Log Ratio (Evert 2022)"),
        "latex_formula": lt(
            r"\mathrm{LRC} = \operatorname{sign}(\widehat{LR}) \cdot "
            r"\max\left(0, \left|\text{nullnahe Grenze von }"
            r"\mathrm{KI}_{1-\alpha}(LR)\right|\right)",
            r"\mathrm{LRC} = \operatorname{sign}(\widehat{LR}) \cdot "
            r"\max\left(0, \left|\text{bound closer to zero of "
            r"}\mathrm{CI}_{1-\alpha}(LR)\right|\right)",
        ),
        "smoothing": "none",
        "sort_key": "lrc",
    },
    "bic": {
        "name": "Bayes Information Criterion",
        "latex_formula": r"G^2 - \ln(N_t + N_r)",
        "smoothing": "none",
        "sort_key": "bic",
    },
    "p_value": {
        "name": lt("p-Wert (Chi-square, df=1)", "p-value (chi-square, df=1)"),
        "latex_formula": r"P(\chi^2_1 \ge G^2)",
        "smoothing": "none",
        "sort_key": "p_value",
    },
    "q_value": {
        "name": lt("q-Wert (FDR, Benjamini-Hochberg)", "q-value (FDR, Benjamini-Hochberg)"),
        "latex_formula": r"q_{(i)} = \min_{k \ge i}\ \frac{m \cdot p_{(k)}}{k}",
        "smoothing": "none",
        "sort_key": "q_value",
    },
    "diff_per_million": {
        "name": lt("Differenz pro Million", "Difference per million"),
        "latex_formula": (
            r"\frac{O_{11}}{N_t}\cdot 10^6 - \frac{O_{21}}{N_r}\cdot 10^6"
        ),
        "smoothing": "none",
        "sort_key": "diff_per_million",
    },
    # Reliability diagnostics (Track FT-KEYNESS-RESEARCH). expected_min is the
    # smallest 2x2 expected cell count; low_reliability flags rows where it falls
    # below the E>=5 chi-square approximation rule.
    "expected_min": {
        "name": lt(
            "Kleinste erwartete Zellbesetzung E_min",
            "Smallest expected cell count E_min",
        ),
        "latex_formula": r"E_{\min} = \min_{ij} E_{ij},\quad E_{ij} = \frac{\text{row}_i \cdot \text{col}_j}{N}",
        "smoothing": "none",
        "sort_key": "expected_min",
    },
    "low_reliability": {
        "name": lt("Geringe Zuverlaessigkeit (E_min < 5)", "Low reliability (E_min < 5)"),
        "latex_formula": r"\mathbb{1}\!\left[E_{\min} < 5\right]",
        "smoothing": "none",
        "sort_key": "low_reliability",
    },
    # --- N-gram frequency (no association math) ---
    "frequency": {
        "name": lt("Frequenz", "Frequency"),
        "latex_formula": lt(
            r"f = \#\{\text{Vorkommen}\}",
            r"f = \#\{\text{occurrences}\}",
        ),
        "smoothing": "none",
        "sort_key": "freq",
    },
    # --- Lexical diversity (Track F4) ---
    "ttr": {
        "name": "Type-Token Ratio",
        "latex_formula": r"\mathrm{TTR} = \frac{V}{N}",
        "smoothing": "none",
        "sort_key": "ttr",
    },
    "sttr": {
        "name": "Standardised TTR",
        "latex_formula": lt(
            r"\mathrm{STTR} = \frac{1}{W}\sum_{w=1}^{W} \frac{V_w}{n}"
            r"\quad (n = \text{Fenstergröße})",
            r"\mathrm{STTR} = \frac{1}{W}\sum_{w=1}^{W} \frac{V_w}{n}\quad"
            r" (n = \text{window size})",
        ),
        "smoothing": "none",
        "sort_key": "sttr",
    },
    "guiraud": {
        "name": "Guiraud's R",
        "latex_formula": r"R = \frac{V}{\sqrt{N}}",
        "smoothing": "none",
        "sort_key": "guiraud",
    },
    "mattr": {
        "name": "Moving-Average TTR",
        "latex_formula": (
            r"\mathrm{MATTR} = \frac{1}{N - n + 1}\sum_{i=1}^{N-n+1}\frac{V_i}{n}"
        ),
        "smoothing": "none",
        "sort_key": "mattr",
    },
    # --- Dispersion family (Track FT-DISPERSION-FAMILY) ---
    # All computed over the SAME per-document distribution as Gries DP: o_i =
    # observed hits in part i, s_i = token size of part i, n = number of parts,
    # F = sum o_i, N = sum s_i. See services.tools.dispersion_family for the
    # implementation (verified against hand/scipy goldens).
    "dp": {
        "name": "Gries DP (Deviation of Proportions)",
        "latex_formula": (
            r"\mathrm{DP} = \tfrac{1}{2}\sum_i\left|\frac{o_i}{F} - \frac{s_i}{N}\right|"
        ),
        "smoothing": "none",
        "sort_key": "dp",
    },
    "dpnorm": {
        "name": lt("Gries DPnorm (normalisiert)", "Gries DPnorm (normalized)"),
        "latex_formula": r"\mathrm{DP_{norm}} = \frac{\mathrm{DP}}{1 - \min_i (s_i / N)}",
        "smoothing": "none",
        "sort_key": "dpnorm",
    },
    "juilland_d": {
        "name": "Juilland's D",
        "latex_formula": (
            r"D = 1 - \frac{\mathrm{VC}}{\sqrt{n - 1}},\quad "
            r"\mathrm{VC} = \frac{\sigma(v_i)}{\bar{v}},\ v_i = \frac{o_i}{s_i}"
        ),
        "smoothing": "none",
        "sort_key": "juilland_d",
    },
    "carroll_d2": {
        "name": lt(
            "Carroll's D2 (normalisierte Entropie)",
            "Carroll's D2 (normalized entropy)",
        ),
        "latex_formula": (
            r"D_2 = \frac{H}{\ln n},\quad H = -\sum_i p_i \ln p_i,\ p_i = \frac{o_i}{F}"
        ),
        "smoothing": "none",
        "sort_key": "carroll_d2",
    },
    "range_prop": {
        "name": lt("Range (Anteil erreichter Teile)", "Range (share of parts reached)"),
        "latex_formula": r"\mathrm{Range} = \frac{\#\{i : o_i > 0\}}{n}",
        "smoothing": "none",
        "sort_key": "range_prop",
    },
    "vc": {
        "name": lt("Variationskoeffizient (VC)", "Coefficient of variation (VC)"),
        "latex_formula": r"\mathrm{VC} = \frac{\sigma(v_i)}{\bar{v}},\ v_i = \frac{o_i}{s_i}",
        "smoothing": "none",
        "sort_key": "vc",
    },
    # --- Trend / Diachronie (Track T3) ---
    # h_p = hits in period p, n_p = running tokens of period p.
    "per_million": {
        "name": lt("Treffer pro Million (Periode)", "Hits per million (period)"),
        "latex_formula": r"\mathrm{pM} = \frac{h_p}{n_p}\cdot 10^{6}",
        "smoothing": "none",
        "sort_key": "per_million",
    },
    "wilson_ci": {
        "name": lt("Wilson-Konfidenzintervall (95%)", "Wilson confidence interval (95%)"),
        "latex_formula": (
            r"\frac{\hat p + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat p(1-\hat p)}{n}"
            r" + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}},\quad"
            r" \hat p = \frac{h_p}{n_p},\ z = 1{,}96"
        ),
        "smoothing": "none",
        "sort_key": "per_million",
    },
    # --- KWIC-Stichprobe (Track T1, Provenienz der Thinning-Funktion) ---
    "random_sample": {
        "name": lt(
            "Uniforme Zufallsstichprobe (Thinning)",
            "Uniform random sample (thinning)",
        ),
        "latex_formula": (
            r"S \subseteq \{1,\dots,N\},\ |S| = k = \min(\mathrm{sample},\,N),"
            r"\quad P(i \in S) = \frac{k}{N}"
        ),
        "smoothing": "none",
        "sort_key": "pos",
    },
}


def _mathml(inner: str) -> str:
    """Wrap presentation-MathML body in a display-ready <math> element."""
    return (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">'
        + inner
        + "</math>"
    )


# Shared presentation-MathML snippets (hand-translated from the LaTeX above).
_MML_O11 = "<msub><mi>O</mi><mn>11</mn></msub>"
_MML_E11 = "<msub><mi>E</mi><mn>11</mn></msub>"
_MML_LOG2 = "<msub><mi>log</mi><mn>2</mn></msub>"
_MML_NOMEGA = "<msub><mi>N</mi><mi>&#937;</mi></msub>"
_MML_R1 = "<msub><mi>R</mi><mn>1</mn></msub>"
_MML_C1 = "<msub><mi>C</mi><mn>1</mn></msub>"
_MML_F1 = "<msub><mi>f</mi><mn>1</mn></msub>"
_MML_F2 = "<msub><mi>f</mi><mn>2</mn></msub>"
_MML_OIJ = "<msub><mi>O</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub>"
_MML_EIJ = "<msub><mi>E</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub>"
_MML_O_MINUS_E_SQ = (
    "<msup><mrow><mo>(</mo>" + _MML_O11 + "<mo>&#8722;</mo>" + _MML_E11
    + "<mo>)</mo></mrow><mn>2</mn></msup>"
)
_MML_SUM_IJ = "<munder><mo>&#8721;</mo><mrow><mi>i</mi><mi>j</mi></mrow></munder>"
_MML_G2_SUM = (
    "<mn>2</mn>" + _MML_SUM_IJ + _MML_OIJ + "<mi>ln</mi><mrow><mo>(</mo><mfrac>"
    + _MML_OIJ + _MML_EIJ + "</mfrac><mo>)</mo></mrow>"
)
_MML_SIGN_DPM = (
    "<mi>sign</mi><mrow><mo>(</mo><msub><mi>&#916;</mi><mrow><mi>p</mi><mi>m</mi>"
    "</mrow></msub><mo>)</mo></mrow>"
)


# ---------------------------------------------------------------------------
# Methodenkatalog (Track T4): formula_mathml + explanation + reference
#
# One documentation record per METHOD_META statistic; merged into METHOD_META
# below (additive — the original name/latex_formula/smoothing/sort_key values
# stay byte-identical). ``formula_mathml`` is presentation MathML translated by
# hand from ``latex_formula``; ``explanation`` is a neutral 2-3 sentence German
# reading aid incl. known biases; ``reference`` is the established source of
# the measure (no invented citations).
# ---------------------------------------------------------------------------
_METHOD_META_DOCS: dict[str, dict[str, str]] = {
    "logdice": {
        "formula_mathml": _mathml(
            "<mn>14</mn><mo>+</mo>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac><mrow>"
            "<mn>2</mn>" + _MML_O11 + "</mrow><mrow>" + _MML_F1 + "<mo>+</mo>"
            + _MML_F2 + "</mrow></mfrac><mo>)</mo></mrow>"
        ),
        # Orientation points quoted from Rychlý (2008, RASLAN, p. 9). Neither
        # the paper nor the Sketch Engine statistics document (Lexical
        # Computing, 2015) gives a threshold for notable collocations.
        "explanation": lt(
            "Dice-Koeffizient auf einer log2-Skala nach Rychlý 2008. Der Wert "
            "hängt nicht von der Korpusgröße ab, ist frequenzstabil und wird von "
            "seltenen Paaren kaum verzerrt. Rychlý gibt Orientierungspunkte: 14 "
            "erreicht ein Paar, dessen Wörter immer gemeinsam vorkommen, meist "
            "liegt der Wert unter 10, 0 heißt weniger als ein gemeinsames "
            "Vorkommen auf 16.000 Vorkommen eines der beiden Wörter, und negative "
            "Werte zeigen keine statistisch bedeutsame Kollokation. Ein Punkt mehr "
            "bedeutet doppelt so häufiges gemeinsames Vorkommen, sieben Punkte "
            "rund hundertmal so häufiges. Eine Schwelle für bemerkenswerte "
            "Kollokationen gibt Rychlý nicht an.",
            "Dice coefficient on a log2 scale after Rychlý 2008. The value does "
            "not depend on corpus size, is stable across frequencies and is "
            "hardly distorted by rare pairs. Rychlý gives orientation points: a "
            "pair whose words always occur together reaches 14, values are "
            "usually below 10, 0 means less than one co-occurrence per 16,000 "
            "occurrences of either word, and negative values show no "
            "statistically significant collocation. One point more means "
            "co-occurrence twice as frequent, seven points roughly a hundred "
            "times as frequent. Rychlý gives no threshold for notable "
            "collocations.",
        ),
        "reference": "Rychlý 2008",
    },
    # Auf den Kollokationsflaechen und in jeder Keyness-Zeile ausgeliefert.
    # Ohne Basiseintrag verschweigt method_statistics eine Spalte, die im
    # Ergebnis steht, und der Methodensteckbrief ist unvollstaendig.
    "lrc": {
        # Echtes Praesentations-MathML mit Struktur, nicht eine flache
        # Zeichenkette: der Katalogwaechter verlangt mindestens ein
        # mfrac/msub/msup, und er hat recht. Eine Formel ohne Bruch zeigt
        # nicht, was verglichen wird.
        "formula_mathml": _mathml(
            "<mi>LRC</mi><mo>=</mo><mi>sgn</mi><mo>(</mo>"
            "<msub><mi>LR</mi><mn>0</mn></msub><mo>)</mo><mo>&#183;</mo>"
            "<mi>min</mi><mrow><mo>|</mo>"
            + _MML_LOG2 +
            "<mfrac><mrow>" + _MML_O11 + "<mo>/</mo>" + _MML_R1
            + "</mrow><mrow><msub><mi>O</mi><mn>21</mn></msub><mo>/</mo>"
            "<mo>(</mo><mi>N</mi><mo>-</mo>" + _MML_R1 + "<mo>)</mo>"
            "</mrow></mfrac><mo>|</mo></mrow>"
        ),
        "explanation": lt(
            "Konservatives Log Ratio: die Grenze des Konfidenzintervalls für "
            "das Log Ratio, die NÄHER AN NULL liegt, also die kleinste "
            "Effektstärke, die mit den Daten verträglich ist. Schließt das "
            "Intervall die Null ein, ist der Effekt nicht von Null zu trennen "
            "und der LRC ist 0. Genau deshalb spült er seltene Kandidaten "
            "nicht nach oben: ein einzelnes Vorkommen erzeugt ein weites "
            "Intervall und damit einen LRC von 0. Das Intervall ist EXAKT und "
            "bedingt auf die Randsumme (Clopper-Pearson), keine "
            "Normalnäherung. Die Bonferroni-Korrektur läuft über die Zahl der "
            "gleichzeitig geprüften Kandidaten (lrc_tests im Methodenblock), "
            "das Niveau ist lrc_alpha. Auf der Kollokationsfläche "
            "sind die Randsummen Everts Distanztafel: Zielrate O11/|W(u)|, "
            "Referenzrate (f(v)-O11)/(N-|W(u)|). In der Keyness vergleicht "
            "es Ziel und Referenz: a/N_t gegen c/N_r.",
            "Conservative Log Ratio: the bound of the confidence interval for "
            "the Log Ratio that lies CLOSER TO ZERO, that is, the smallest "
            "effect size compatible with the data. If the interval includes "
            "zero, the effect cannot be separated from zero and the LRC is 0. "
            "This is why it does not push rare candidates to the top: a single "
            "occurrence produces a wide interval and therefore an LRC of 0. The"
            " interval is EXACT and conditional on the marginal total "
            "(Clopper-Pearson), not a normal approximation. The Bonferroni "
            "correction runs over the number of candidates tested at the same "
            "time (lrc_tests in the method card), the level is lrc_alpha. On "
            "the collocation surface the marginal totals are Evert's distance "
            "table: target rate O11/|W(u)|, reference rate "
            "(f(v)-O11)/(N-|W(u)|). In keyness it compares target and "
            "reference: a/N_t against c/N_r.",
        ),
        "reference": "Evert 2022; Clopper & Pearson 1934",
    },
    "logdice_window": {
        "formula_mathml": _mathml(
            "<mn>14</mn><mo>+</mo>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac><mrow>"
            "<mn>2</mn>" + _MML_O11 + "</mrow><mrow>" + _MML_R1 + "<mo>+</mo>"
            + _MML_C1 + "</mrow></mfrac><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Log-Transformation des Dice-Koeffizienten über die Randsummen der "
            "Distanztafel. Nicht über Knoten vergleichbar.",
            "Log transform of the Dice coefficient over the marginal totals of "
            "the distance table. Not comparable across nodes.",
        ),
        "reference": lt("Dice auf Evert 2004, Fig. 2.13", "Dice on Evert 2004, Fig. 2.13"),
    },
    "dice": {
        "formula_mathml": _mathml(
            "<mfrac><mrow><mn>2</mn>" + _MML_O11 + "</mrow><mrow>" + _MML_F1
            + "<mo>+</mo>" + _MML_F2 + "</mrow></mfrac>"
        ),
        "explanation": lt(
            "Harmonische Verrechnung der Kookkurrenzfrequenz mit den Randhäufigkeiten "
            "beider Ausdrücke, Wertebereich 0 bis 1. Das Maß ist symmetrisch; hohe "
            "Werte setzen voraus, dass beide Ausdrücke überwiegend gemeinsam auftreten.",
            "Harmonic combination of the co-occurrence frequency with the "
            "marginal frequencies of both expressions, range 0 to 1. The "
            "measure is symmetric. High values require that both expressions "
            "mostly occur together.",
        ),
        "reference": "Dice 1945",
    },
    "mi": {
        "formula_mathml": _mathml(
            _MML_LOG2 + "<mrow><mo>(</mo><mfrac>" + _MML_O11 + _MML_E11
            + "</mfrac><mo>)</mo></mrow><mo>,</mo>" + _MML_E11 + "<mo>=</mo><mfrac>"
            "<mrow>" + _MML_R1 + "<mo>&#8901;</mo>" + _MML_C1 + "</mrow>"
            + _MML_NOMEGA + "</mfrac>"
        ),
        "explanation": lt(
            "Vergleicht die beobachtete mit der bei Unabhängigkeit erwarteten "
            "Kookkurrenz auf log2-Skala. MI überschätzt seltene Paare systematisch: "
            "schon wenige gemeinsame Vorkommen zweier niederfrequenter Ausdrücke "
            "erzeugen hohe Werte.",
            "Compares the observed co-occurrence with the co-occurrence "
            "expected under independence on a log2 scale. MI systematically "
            "overrates rare pairs: a few joint occurrences of two low-frequency"
            " expressions already produce high values.",
        ),
        "reference": "Church & Hanks 1990",
    },
    "mi3": {
        "formula_mathml": _mathml(
            _MML_LOG2 + "<mrow><mo>(</mo><mfrac><msup><mrow>" + _MML_O11
            + "</mrow><mn>3</mn></msup>" + _MML_E11 + "</mfrac><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Variante der MI mit kubierter beobachteter Kookkurrenz, gerechnet über "
            "exakt dasselbe O/E-Paar wie die MI. Die Kubierung dämpft die Verzerrung "
            "der MI zugunsten seltener Paare, sodass hohe Werte Assoziation und "
            "substanzielle Frequenz zugleich verlangen; eine Signifikanzaussage ist "
            "damit nicht verbunden.",
            "Variant of MI with the observed co-occurrence cubed, computed over"
            " exactly the same O/E pair as MI. Cubing dampens the bias of MI "
            "towards rare pairs, so high values require both association and "
            "substantial frequency. It makes no statement about significance.",
        ),
        "reference": "Oakes 1998",
    },
    "lmi": {
        "formula_mathml": _mathml(
            _MML_O11 + "<mo>&#8901;</mo>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac>"
            + _MML_O11 + _MML_E11 + "</mfrac><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Gewichtet die MI mit der beobachteten Kookkurrenzfrequenz und gleicht "
            "deren Überschätzung seltener Paare teilweise aus. Im Gegenzug dominieren "
            "hochfrequente Kombinationen die Rangliste stärker.",
            "Weights MI by the observed co-occurrence frequency and partly "
            "offsets its overrating of rare pairs. In return, high-frequency "
            "combinations dominate the ranking more strongly.",
        ),
        "reference": "Evert 2005",
    },
    "npmi": {
        "formula_mathml": _mathml(
            "<mfrac><mrow>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac>" + _MML_O11
            + _MML_E11 + "</mfrac><mo>)</mo></mrow></mrow><mrow><mo>&#8722;</mo>"
            + _MML_LOG2 + "<mrow><mo>(</mo><mfrac>" + _MML_O11 + _MML_NOMEGA
            + "</mfrac><mo>)</mo></mrow></mrow></mfrac>"
        ),
        "explanation": lt(
            "Auf den Bereich −1 bis 1 normierte punktweise MI: 1 bedeutet perfekte "
            "Kookkurrenz, 0 Unabhängigkeit. Die Normierung erleichtert Vergleiche, "
            "ändert aber nichts an der Instabilität bei sehr kleinen Frequenzen.",
            "Pointwise MI normalized to the range −1 to 1: 1 means perfect "
            "co-occurrence, 0 independence. The normalization makes comparisons"
            " easier but does not change the instability at very small "
            "frequencies.",
        ),
        "reference": "Bouma 2009",
    },
    "t": {
        "formula_mathml": _mathml(
            "<mfrac><mrow>" + _MML_O11 + "<mo>&#8722;</mo>" + _MML_E11
            + "</mrow><msqrt>" + _MML_O11 + "</msqrt></mfrac>"
        ),
        "explanation": lt(
            "Prüfgröße für die Differenz zwischen beobachteter und erwarteter "
            "Kookkurrenz relativ zur Streuung der Beobachtung. Der t-Score bevorzugt "
            "hochfrequente Kollokationen; die zugrunde liegende Normalverteilungs"
            "annahme ist bei Korpusdaten nur näherungsweise erfüllt.",
            "Test statistic for the difference between observed and expected "
            "co-occurrence relative to the variability of the observation. The "
            "t-score favors high-frequency collocations. The underlying "
            "normality assumption holds only approximately for corpus data.",
        ),
        "reference": "Church et al. 1991",
    },
    "z": {
        "formula_mathml": _mathml(
            "<mfrac><mrow>" + _MML_O11 + "<mo>&#8722;</mo>" + _MML_E11
            + "</mrow><msqrt>" + _MML_E11 + "</msqrt></mfrac>"
        ),
        "explanation": lt(
            "Standardisierte Abweichung der beobachteten von der erwarteten "
            "Kookkurrenz. Bei kleinen Erwartungswerten wird der z-Score stark "
            "aufgebläht und ist für seltene Kollokate entsprechend vorsichtig zu lesen.",
            "Standardized deviation of the observed from the expected "
            "co-occurrence. With small expected values the z-score is strongly "
            "inflated and should be read with corresponding caution for rare "
            "collocates.",
        ),
        "reference": "Berry-Rogghe 1973",
    },
    "chi2_cell": {
        "formula_mathml": _mathml(
            "<mfrac><mrow>" + _MML_O_MINUS_E_SQ + "</mrow>" + _MML_E11 + "</mfrac>"
        ),
        "explanation": lt(
            "Beitrag der Zelle (Knoten, Kollokat) zur Pearson-Chi-Quadrat-Statistik. "
            "Es handelt sich nur um eine der vier Zellen, nicht um den vollständigen "
            "Test; bei kleinen Erwartungswerten ist der Wert unzuverlässig.",
            "Contribution of the cell (node, collocate) to the Pearson "
            "chi-square statistic. It is only one of the four cells, not the "
            "complete test. With small expected values the value is unreliable.",
        ),
        "reference": "Pearson 1900",
    },
    "ll": {
        "formula_mathml": _mathml(_MML_G2_SUM),
        "explanation": lt(
            "Dunnings Log-Likelihood-Statistik (G²) über die vollständige "
            "2x2-Kontingenztafel; auch bei kleinen Frequenzen robuster als "
            "Chi-Quadrat. G² misst Signifikanz, nicht Effektstärke: in großen "
            "Korpora werden auch triviale Unterschiede hochsignifikant.",
            "Dunning's log-likelihood statistic (G²) over the complete 2x2 "
            "contingency table, more robust than chi-square also at small "
            "frequencies. G² measures significance, not effect size: in large "
            "corpora even trivial differences become highly significant.",
        ),
        "reference": "Dunning 1993",
    },
    "delta_p_nc": {
        "formula_mathml": _mathml(
            "<msub><mi>&#916;</mi><mrow><mi>n</mi><mo>&#8594;</mo><mi>c</mi></mrow>"
            "</msub><mi>P</mi><mo>=</mo><mfrac>" + _MML_O11 + _MML_R1
            + "</mfrac><mo>&#8722;</mo><mfrac><mrow>" + _MML_C1 + "<mo>&#8722;</mo>"
            + _MML_O11 + "</mrow><mrow>" + _MML_NOMEGA + "<mo>&#8722;</mo>"
            + _MML_R1 + "</mrow></mfrac>"
        ),
        "explanation": lt(
            "Asymmetrisches Assoziationsmaß: Differenz der Wahrscheinlichkeit des "
            "Kollokats mit und ohne Knoten, Wertebereich −1 bis 1. Erfasst "
            "Richtungseffekte, die symmetrische Maße wie MI oder Dice verdecken.",
            "Asymmetric association measure: difference between the probability"
            " of the collocate with and without the node, range −1 to 1. "
            "Captures directional effects that symmetric measures such as MI or"
            " Dice hide.",
        ),
        "reference": "Allan 1980; Ellis 2006; Gries 2013",
    },
    "delta_p_cn": {
        "formula_mathml": _mathml(
            "<msub><mi>&#916;</mi><mrow><mi>c</mi><mo>&#8594;</mo><mi>n</mi></mrow>"
            "</msub><mi>P</mi><mo>=</mo><mfrac>" + _MML_O11 + _MML_C1
            + "</mfrac><mo>&#8722;</mo><mfrac><mrow>" + _MML_R1 + "<mo>&#8722;</mo>"
            + _MML_O11 + "</mrow><mrow>" + _MML_NOMEGA + "<mo>&#8722;</mo>"
            + _MML_C1 + "</mrow></mfrac>"
        ),
        "explanation": lt(
            "Gegenrichtung des Delta-P: Differenz der Wahrscheinlichkeit des Knotens "
            "mit und ohne Kollokat, Wertebereich −1 bis 1. Zusammen mit der "
            "Hinrichtung zeigt es, welcher Partner den anderen stärker vorhersagt.",
            "Opposite direction of Delta P: difference between the probability "
            "of the node with and without the collocate, range −1 to 1. "
            "Together with the forward direction it shows which partner "
            "predicts the other more strongly.",
        ),
        "reference": "Allan 1980; Ellis 2006; Gries 2013",
    },
    "chi2": {
        "formula_mathml": _mathml(
            "<msup><mi>&#967;</mi><mn>2</mn></msup><mo>=</mo>" + _MML_SUM_IJ
            + "<mfrac><mrow><msup><mrow><mo>(</mo>" + _MML_OIJ + "<mo>&#8722;</mo>"
            + _MML_EIJ + "<mo>)</mo></mrow><mn>2</mn></msup></mrow>" + _MML_EIJ
            + "</mfrac>"
        ),
        "explanation": lt(
            "Pearsons Chi-Quadrat-Test über die vollständige 2x2-Tafel (df=1). "
            "Reines Signifikanzmaß ohne Effektstärke; bei erwarteten Zellbesetzungen "
            "unter 5 ist die Approximation unzuverlässig (siehe expected_min).",
            "Pearson's chi-square test over the complete 2x2 table (df=1). A "
            "pure significance measure without effect size. With expected cell "
            "counts below 5 the approximation is unreliable (see expected_min).",
        ),
        "reference": "Pearson 1900",
    },
    "chi2_signed": {
        "formula_mathml": _mathml(
            _MML_SIGN_DPM + "<mo>&#8901;</mo>" + _MML_SUM_IJ + "<mfrac><mrow><msup>"
            "<mrow><mo>(</mo>" + _MML_OIJ + "<mo>&#8722;</mo>" + _MML_EIJ
            + "<mo>)</mo></mrow><mn>2</mn></msup></mrow>" + _MML_EIJ + "</mfrac>"
        ),
        "explanation": lt(
            "Chi-Quadrat mit dem Vorzeichen der Frequenzdifferenz: positive Werte "
            "zeigen Überrepräsentation im Zielkorpus, negative im Referenzkorpus. "
            "Der Betrag ist wie chi2 zu lesen (Signifikanz, keine Effektstärke).",
            "Chi-square with the sign of the frequency difference: positive "
            "values show overrepresentation in the target corpus, negative "
            "values in the reference corpus. The absolute value reads like chi2"
            " (significance, not effect size).",
        ),
        "reference": "Pearson 1900",
    },
    "ll_signed": {
        "formula_mathml": _mathml(
            _MML_SIGN_DPM + "<mo>&#8901;</mo>" + _MML_G2_SUM
        ),
        "explanation": lt(
            "G² mit dem Vorzeichen der Frequenzdifferenz: positive Werte bedeuten "
            "Überrepräsentation im Zielkorpus, negative im Referenzkorpus. Wie das "
            "ungerichtete G² eine Signifikanz-, keine Effektstärkeaussage.",
            "G² with the sign of the frequency difference: positive values mean"
            " overrepresentation in the target corpus, negative values in the "
            "reference corpus. Like the undirected G², a statement about "
            "significance, not effect size.",
        ),
        "reference": "Dunning 1993",
    },
    "log_ratio": {
        "formula_mathml": _mathml(
            _MML_LOG2 + "<mrow><mo>(</mo><mfrac><mrow><mfrac><mrow>"
            "<msub><mi>O</mi><mn>11</mn></msub><mo>+</mo><mn>0.5</mn></mrow>"
            "<msub><mi>N</mi><mi>t</mi></msub></mfrac></mrow><mrow><mfrac><mrow>"
            "<msub><mi>O</mi><mn>21</mn></msub><mo>+</mo><mn>0.5</mn></mrow>"
            "<msub><mi>N</mi><mi>r</mi></msub></mfrac></mrow></mfrac><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Binärer Logarithmus des Verhältnisses der relativen Häufigkeiten "
            "(Effektstärke): +1 entspricht doppelter Häufigkeit im Zielkorpus. "
            "Log Ratio trifft keine Signifikanzaussage und wird deshalb mit einem "
            "Signifikanzmaß (G², BIC) kombiniert; die +0.5-Glättung hält einseitige "
            "Nullzellen endlich.",
            "Binary logarithm of the ratio of relative frequencies (effect "
            "size): +1 corresponds to twice the frequency in the target corpus."
            " Log Ratio makes no statement about significance and is therefore "
            "combined with a significance measure (G², BIC). The +0.5 smoothing"
            " keeps one-sided zero cells finite.",
        ),
        "reference": "Hardie 2014",
    },
    "bic": {
        "formula_mathml": _mathml(
            "<msup><mi>G</mi><mn>2</mn></msup><mo>&#8722;</mo><mi>ln</mi>"
            "<mrow><mo>(</mo><msub><mi>N</mi><mi>t</mi></msub><mo>+</mo>"
            "<msub><mi>N</mi><mi>r</mi></msub><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Bayessches Informationskriterium als Approximation aus G²: Werte über "
            "etwa 2 gelten als positive, über etwa 10 als sehr starke Evidenz gegen "
            "Unabhängigkeit. Anders als der p-Wert bestraft das BIC die Korpusgröße "
            "und läuft in großen Korpora nicht automatisch ins Signifikante.",
            "Bayesian information criterion approximated from G²: values above "
            "about 2 count as positive evidence, above about 10 as very strong "
            "evidence against independence. Unlike the p-value, the BIC "
            "penalizes corpus size and does not automatically become "
            "significant in large corpora.",
        ),
        "reference": "Wilson 2013",
    },
    "p_value": {
        "formula_mathml": _mathml(
            "<mi>P</mi><mrow><mo>(</mo><msubsup><mi>&#967;</mi><mn>1</mn>"
            "<mn>2</mn></msubsup><mo>&#8805;</mo><msup><mi>G</mi><mn>2</mn></msup>"
            "<mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Wahrscheinlichkeit, unter der Nullhypothese der Unabhängigkeit einen "
            "mindestens so großen G²-Wert zu beobachten (Chi-Quadrat-Verteilung, "
            "df=1). Bei vielen parallelen Tests ist der rohe p-Wert ohne Korrektur "
            "irreführend (siehe q-Wert).",
            "Probability of observing a G² value at least this large under the "
            "null hypothesis of independence (chi-square distribution, df=1). "
            "With many parallel tests the raw p-value is misleading without "
            "correction (see q-value).",
        ),
        "reference": "Dunning 1993",
    },
    "q_value": {
        "formula_mathml": _mathml(
            "<msub><mi>q</mi><mrow><mo>(</mo><mi>i</mi><mo>)</mo></mrow></msub>"
            "<mo>=</mo><munder><mi>min</mi><mrow><mi>k</mi><mo>&#8805;</mo>"
            "<mi>i</mi></mrow></munder><mfrac><mrow><mi>m</mi><mo>&#8901;</mo>"
            "<msub><mi>p</mi><mrow><mo>(</mo><mi>k</mi><mo>)</mo></mrow></msub>"
            "</mrow><mi>k</mi></mfrac>"
        ),
        "explanation": lt(
            "Benjamini-Hochberg-adjustierter p-Wert: kontrolliert die erwartete "
            "Falscherkennungsrate (FDR) über alle gleichzeitig getesteten Ausdrücke. "
            "Für Keyword-Listen mit vielen Tests dem rohen p-Wert vorzuziehen.",
            "Benjamini-Hochberg adjusted p-value: controls the expected false "
            "discovery rate (FDR) over all expressions tested at the same time."
            " Preferable to the raw p-value for keyword lists with many tests.",
        ),
        "reference": "Benjamini & Hochberg 1995",
    },
    "diff_per_million": {
        "formula_mathml": _mathml(
            "<mfrac><msub><mi>O</mi><mn>11</mn></msub><msub><mi>N</mi><mi>t</mi>"
            "</msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup>"
            "<mo>&#8722;</mo><mfrac><msub><mi>O</mi><mn>21</mn></msub>"
            "<msub><mi>N</mi><mi>r</mi></msub></mfrac><mo>&#8901;</mo>"
            "<msup><mn>10</mn><mn>6</mn></msup>"
        ),
        "explanation": lt(
            "Differenz der auf eine Million Tokens normalisierten Häufigkeiten "
            "zwischen Ziel- und Referenzkorpus. Deskriptives Maß ohne "
            "Signifikanzaussage; der Absolutwert hängt stark von der Grundfrequenz "
            "des Ausdrucks ab.",
            "Difference between the frequencies per million tokens in the "
            "target and the reference corpus. A descriptive measure without a "
            "statement about significance. The absolute value depends strongly "
            "on the base frequency of the expression.",
        ),
        "reference": "Brezina 2018",
    },
    "expected_min": {
        "formula_mathml": _mathml(
            "<msub><mi>E</mi><mi>min</mi></msub><mo>=</mo><munder><mi>min</mi>"
            "<mrow><mi>i</mi><mi>j</mi></mrow></munder>" + _MML_EIJ
        ),
        "explanation": lt(
            "Kleinste erwartete Zellbesetzung der 2x2-Tafel. Diagnostik für die "
            "Gültigkeit der asymptotischen Tests: liegt sie unter 5, ist die "
            "Chi-Quadrat-Approximation unzuverlässig.",
            "Smallest expected cell count of the 2x2 table. A diagnostic for "
            "the validity of the asymptotic tests: below 5, the chi-square "
            "approximation is unreliable.",
        ),
        "reference": "Cochran 1954",
    },
    "low_reliability": {
        "formula_mathml": _mathml(
            "<mi>&#120793;</mi><mrow><mo>[</mo><msub><mi>E</mi><mi>min</mi></msub>"
            "<mo>&lt;</mo><mn>5</mn><mo>]</mo></mrow>"
        ),
        "explanation": lt(
            "Markierung, dass mindestens eine erwartete Zellbesetzung unter 5 liegt. "
            "Die asymptotischen Teststatistiken (chi2, G²) sind für solche Zeilen "
            "nur eingeschränkt belastbar.",
            "Flag that at least one expected cell count is below 5. The "
            "asymptotic test statistics (chi2, G²) are of limited reliability "
            "for such rows.",
        ),
        "reference": "Cochran 1954",
    },
    "frequency": {
        "formula_mathml": lt(
            _mathml(
                "<mi>f</mi><mo>=</mo><mo>#</mo><mrow><mo>{</mo><mtext>Vorkommen</mtext>"
                "<mo>}</mo></mrow>"
            ),
            _mathml(
                "<mi>f</mi><mo>=</mo><mo>#</mo><mrow><mo>{</mo><mtext>occurrences</mtext>"
                "<mo>}</mo></mrow>"
            ),
        ),
        "explanation": lt(
            "Absolute Vorkommenshäufigkeit im gewählten Geltungsbereich. Für "
            "Vergleiche zwischen unterschiedlich großen Korpora oder Teilkorpora "
            "sind normalisierte Häufigkeiten (pro Million) erforderlich.",
            "Raw frequency of occurrence in the selected scope. Comparisons "
            "between corpora or subcorpora of different sizes require "
            "normalized frequencies (per million).",
        ),
        "reference": "Brezina 2018",
    },
    "ttr": {
        "formula_mathml": _mathml("<mfrac><mi>V</mi><mi>N</mi></mfrac>"),
        "explanation": lt(
            "Verhältnis der Typen (V) zur Tokenzahl (N) als Maß lexikalischer "
            "Vielfalt. Stark textlängenabhängig: längere Texte erhalten systematisch "
            "niedrigere Werte, direkte Vergleiche verlangen gleiche Längen oder "
            "standardisierte Varianten (STTR, MATTR).",
            "Ratio of types (V) to tokens (N) as a measure of lexical "
            "diversity. Strongly dependent on text length: longer texts "
            "systematically get lower values, and direct comparisons require "
            "equal lengths or standardized variants (STTR, MATTR).",
        ),
        "reference": "Brezina 2018",
    },
    "sttr": {
        "formula_mathml": _mathml(
            "<mfrac><mn>1</mn><mi>W</mi></mfrac><munderover><mo>&#8721;</mo><mrow>"
            "<mi>w</mi><mo>=</mo><mn>1</mn></mrow><mi>W</mi></munderover><mfrac>"
            "<msub><mi>V</mi><mi>w</mi></msub><mi>n</mi></mfrac>"
        ),
        "explanation": lt(
            "Mittlere TTR über aufeinanderfolgende, gleich große Textfenster; "
            "neutralisiert die Längenabhängigkeit der rohen TTR. Restfenster "
            "unterhalb der Fenstergröße bleiben unberücksichtigt.",
            "Mean TTR over consecutive text windows of equal size. It "
            "neutralizes the length dependence of the raw TTR. A remaining "
            "window shorter than the window size is not counted.",
        ),
        "reference": "Scott, WordSmith Tools",
    },
    "guiraud": {
        "formula_mathml": _mathml(
            "<mfrac><mi>V</mi><msqrt><mi>N</mi></msqrt></mfrac>"
        ),
        "explanation": lt(
            "Wurzeltransformierte Type-Token-Relation (V/√N). Mildert die "
            "Längenabhängigkeit der TTR ab, beseitigt sie aber nicht vollständig.",
            "Square-root transformed type-token relation (V/√N). Reduces the "
            "length dependence of the TTR but does not remove it completely.",
        ),
        "reference": "Guiraud 1954",
    },
    "mattr": {
        "formula_mathml": _mathml(
            "<mfrac><mn>1</mn><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi><mo>+</mo>"
            "<mn>1</mn></mrow></mfrac><munderover><mo>&#8721;</mo><mrow><mi>i</mi>"
            "<mo>=</mo><mn>1</mn></mrow><mrow><mi>N</mi><mo>&#8722;</mo><mi>n</mi>"
            "<mo>+</mo><mn>1</mn></mrow></munderover><mfrac><msub><mi>V</mi>"
            "<mi>i</mi></msub><mi>n</mi></mfrac>"
        ),
        "explanation": lt(
            "TTR über ein gleitendes Fenster fester Länge, über alle "
            "Fensterpositionen gemittelt. Weitgehend längenunabhängig und feiner "
            "aufgelöst als die fensterblockweise STTR.",
            "TTR over a moving window of fixed length, averaged over all window"
            " positions. Largely independent of length and finer-grained than "
            "the block-wise STTR.",
        ),
        "reference": "Covington & McFall 2010",
    },
    "dp": {
        "formula_mathml": _mathml(
            "<mfrac><mn>1</mn><mn>2</mn></mfrac><munder><mo>&#8721;</mo><mi>i</mi>"
            "</munder><mrow><mo>|</mo><mfrac><msub><mi>o</mi><mi>i</mi></msub>"
            "<mi>F</mi></mfrac><mo>&#8722;</mo><mfrac><msub><mi>s</mi><mi>i</mi>"
            "</msub><mi>N</mi></mfrac><mo>|</mo></mrow>"
        ),
        "explanation": lt(
            "Abweichung der beobachteten Trefferanteile von den nach Dokumentgröße "
            "erwarteten Anteilen: 0 bedeutet gleichmäßige Verteilung, Werte gegen 1 "
            "Konzentration auf wenige Dokumente. Ergänzt Frequenzmaße, die solche "
            "Klumpung verdecken.",
            "Deviation of the observed shares of hits from the shares expected "
            "from document size: 0 means an even distribution, values towards 1"
            " a concentration in few documents. Complements frequency measures,"
            " which hide such clustering.",
        ),
        "reference": "Gries 2008",
    },
    "dpnorm": {
        "formula_mathml": _mathml(
            "<mfrac><mi>DP</mi><mrow><mn>1</mn><mo>&#8722;</mo><munder><mi>min</mi>"
            "<mi>i</mi></munder><mrow><mo>(</mo><mfrac><msub><mi>s</mi><mi>i</mi>"
            "</msub><mi>N</mi></mfrac><mo>)</mo></mrow></mrow></mfrac>"
        ),
        "explanation": lt(
            "Auf den erreichbaren Maximalwert normierte DP. Dadurch zwischen "
            "Korpora mit unterschiedlich vielen und unterschiedlich großen Teilen "
            "vergleichbar.",
            "DP normalized to its attainable maximum. This makes it comparable "
            "between corpora with different numbers and sizes of parts.",
        ),
        "reference": "Lijffijt & Gries 2012",
    },
    "juilland_d": {
        "formula_mathml": _mathml(
            "<mi>D</mi><mo>=</mo><mn>1</mn><mo>&#8722;</mo><mfrac><mi>VC</mi>"
            "<msqrt><mrow><mi>n</mi><mo>&#8722;</mo><mn>1</mn></mrow></msqrt>"
            "</mfrac>"
        ),
        "explanation": lt(
            "Klassisches Dispersionsmaß auf Basis des Variationskoeffizienten der "
            "größennormalisierten Teilfrequenzen; 1 bedeutet perfekt gleichmäßige "
            "Verteilung. Bei vielen kleinen Teilen neigt D dazu, Gleichmäßigkeit zu "
            "überschätzen.",
            "Classic dispersion measure based on the coefficient of variation "
            "of the size-normalized part frequencies. 1 means a perfectly even "
            "distribution. With many small parts, D tends to overestimate "
            "evenness.",
        ),
        "reference": "Juilland & Chang-Rodríguez 1964",
    },
    "carroll_d2": {
        "formula_mathml": _mathml(
            "<msub><mi>D</mi><mn>2</mn></msub><mo>=</mo><mfrac><mi>H</mi><mrow>"
            "<mi>ln</mi><mi>n</mi></mrow></mfrac><mo>,</mo><mi>H</mi><mo>=</mo>"
            "<mo>&#8722;</mo><munder><mo>&#8721;</mo><mi>i</mi></munder>"
            "<msub><mi>p</mi><mi>i</mi></msub><mi>ln</mi><msub><mi>p</mi><mi>i</mi>"
            "</msub>"
        ),
        "explanation": lt(
            "Normierte Entropie der Trefferverteilung über die Teile: 1 bedeutet "
            "Gleichverteilung, 0 vollständige Konzentration auf einen Teil. "
            "Berücksichtigt anders als Range auch die Frequenzanteile.",
            "Normalized entropy of the distribution of hits over the parts: 1 "
            "means a uniform distribution, 0 complete concentration in one "
            "part. Unlike Range, it also takes the frequency shares into "
            "account.",
        ),
        "reference": "Carroll 1970",
    },
    "range_prop": {
        "formula_mathml": _mathml(
            "<mfrac><mrow><mo>#</mo><mrow><mo>{</mo><mi>i</mi><mo>:</mo>"
            "<msub><mi>o</mi><mi>i</mi></msub><mo>&gt;</mo><mn>0</mn><mo>}</mo>"
            "</mrow></mrow><mi>n</mi></mfrac>"
        ),
        "explanation": lt(
            "Anteil der Teile (Dokumente), in denen der Ausdruck mindestens einmal "
            "vorkommt. Robustes, aber grobes Streuungsmaß: Frequenzunterschiede "
            "innerhalb der Teile bleiben unberücksichtigt.",
            "Share of parts (documents) in which the expression occurs at least"
            " once. A robust but coarse dispersion measure: frequency "
            "differences within the parts are not taken into account.",
        ),
        "reference": "Brezina 2018",
    },
    "vc": {
        "formula_mathml": _mathml(
            "<mfrac><mrow><mi>&#963;</mi><mrow><mo>(</mo><msub><mi>v</mi><mi>i</mi>"
            "</msub><mo>)</mo></mrow></mrow><mover><mi>v</mi><mo>&#175;</mo></mover>"
            "</mfrac><mo>,</mo><msub><mi>v</mi><mi>i</mi></msub><mo>=</mo><mfrac>"
            "<msub><mi>o</mi><mi>i</mi></msub><msub><mi>s</mi><mi>i</mi></msub>"
            "</mfrac>"
        ),
        "explanation": lt(
            "Variationskoeffizient der größennormalisierten Teilfrequenzen; "
            "Grundbaustein von Juillands D. Höhere Werte bedeuten ungleichmäßigere "
            "Verteilung über die Teile.",
            "Coefficient of variation of the size-normalized part frequencies, "
            "the basis of Juilland's D. Higher values mean a less even "
            "distribution over the parts.",
        ),
        "reference": "Juilland & Chang-Rodríguez 1964",
    },
    "per_million": {
        "formula_mathml": _mathml(
            "<mfrac><msub><mi>h</mi><mi>p</mi></msub><msub><mi>n</mi><mi>p</mi>"
            "</msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup>"
        ),
        "explanation": lt(
            "Normalisierte Häufigkeit je Periode: Treffer pro Million laufender "
            "Tokens. Macht Perioden mit unterschiedlicher Textmenge vergleichbar; "
            "bei kleinen Perioden-Token-Zahlen schwankt der Wert stark (siehe "
            "Konfidenzintervall).",
            "Normalized frequency per period: hits per million running tokens. "
            "Makes periods with different amounts of text comparable. With "
            "small token counts per period the value varies strongly (see "
            "confidence interval).",
        ),
        "reference": "Brezina 2018",
    },
    "wilson_ci": {
        "formula_mathml": _mathml(
            "<mfrac><mrow><mover><mi>p</mi><mo>^</mo></mover><mo>+</mo><mfrac>"
            "<msup><mi>z</mi><mn>2</mn></msup><mrow><mn>2</mn><mi>n</mi></mrow>"
            "</mfrac><mo>&#177;</mo><mi>z</mi><msqrt><mrow><mfrac><mrow><mover>"
            "<mi>p</mi><mo>^</mo></mover><mrow><mo>(</mo><mn>1</mn><mo>&#8722;</mo>"
            "<mover><mi>p</mi><mo>^</mo></mover><mo>)</mo></mrow></mrow><mi>n</mi>"
            "</mfrac><mo>+</mo><mfrac><msup><mi>z</mi><mn>2</mn></msup><mrow>"
            "<mn>4</mn><msup><mi>n</mi><mn>2</mn></msup></mrow></mfrac></mrow>"
            "</msqrt></mrow><mrow><mn>1</mn><mo>+</mo><mfrac><msup><mi>z</mi>"
            "<mn>2</mn></msup><mi>n</mi></mfrac></mrow></mfrac>"
        ),
        "explanation": lt(
            "95%-Konfidenzintervall (Wilson-Score) für die Token-Rate einer Periode, "
            "auf pro Million skaliert. Das Intervall ist asymmetrisch und auch bei "
            "null Treffern definiert (Untergrenze 0); enge Intervalle erfordern "
            "große Token-Zahlen je Periode.",
            "95% confidence interval (Wilson score) for the token rate of a "
            "period, scaled to per million. The interval is asymmetric and "
            "defined even for zero hits (lower bound 0). Narrow intervals "
            "require large token counts per period.",
        ),
        "reference": "Wilson 1927",
    },
    "random_sample": {
        "formula_mathml": _mathml(
            "<mi>P</mi><mrow><mo>(</mo><mi>i</mi><mo>&#8712;</mo><mi>S</mi>"
            "<mo>)</mo></mrow><mo>=</mo><mfrac><mi>k</mi><mi>N</mi></mfrac>"
            "<mo>,</mo><mi>k</mi><mo>=</mo><mi>min</mi><mrow><mo>(</mo>"
            "<mtext>sample</mtext><mo>,</mo><mi>N</mi><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Uniforme Zufallsstichprobe ohne Zurücklegen aus der Gesamttreffermenge, "
            "über den angegebenen Seed deterministisch reproduzierbar. Statistiken "
            "über die Stichprobe schätzen die Vollmenge nur mit Stichprobenfehler; "
            "die Provenienz (requested, drawn, seed, population) wird mitgeliefert.",
            "Uniform random sample without replacement from all hits, "
            "reproducible through the given seed. Statistics over the sample "
            "estimate the full set with sampling error. The provenance "
            "(requested, drawn, seed, population) is included.",
        ),
        "reference": "Brezina 2018",
    },
}

# Merge the documentation fields into METHOD_META (additive; the original
# name/latex_formula/smoothing/sort_key values stay untouched). The guard makes
# an incomplete catalog fail at import time instead of silently shipping a
# statistic without formula/explanation/reference.
for _meta_key, _meta_entry in METHOD_META.items():
    _docs = _METHOD_META_DOCS.get(_meta_key)
    if _docs is None:
        raise RuntimeError(
            f"METHOD_META['{_meta_key}'] has no catalogue entry "
            "(formula_mathml/explanation/reference) in _METHOD_META_DOCS."
        )
    for _doc_field, _doc_value in _docs.items():
        _meta_entry.setdefault(_doc_field, _doc_value)


# Statistics surfaced by each analysis family, in display order. Used to
# assemble the per-response ``method`` block from METHOD_META.
_METHOD_STATISTICS: dict[str, tuple[str, ...]] = {
    "collocates": (
        "logdice",
        "logdice_window",
        "log_ratio",
        "lrc",
        "mi",
        "mi3",
        "lmi",
        "npmi",
        "t",
        "z",
        "chi2_cell",
        "ll",
        "delta_p_nc",
        "delta_p_cn",
    ),
    "keyness": (
        "ll_signed",
        "ll",
        "log_ratio",
        "lrc",
        "chi2",
        "chi2_signed",
        "chi2_cell",
        "bic",
        "p_value",
        "q_value",
        "diff_per_million",
        "expected_min",
        "low_reliability",
    ),
    # The contrast rows carry ONE association measure per side (score_key,
    # default dice), the per-million co-occurrence rates, their difference and
    # the log ratio of the two rates. The job passes the chosen measure.
    "contrast": ("dice", "diff_per_million", "log_ratio"),
    # Frequency contrast ranks the complete union of both scoped vocabularies
    # by the absolute normalized difference; no inferential statistic is implied.
    "frequency_diff": ("frequency", "diff_per_million"),
    # The n-gram contrast rows carry frequencies and rates only, no test
    # statistic.
    "ngrams_diff": ("frequency", "diff_per_million"),
    "ngrams": ("frequency",),
    "wordsketch": ("logdice", "chi2_cell", "t", "ll", "frequency"),
    "lexical_diversity": ("ttr", "sttr", "guiraud", "mattr"),
    # DP remains the default classification driver; the family members are
    # surfaced alongside it (Track FT-DISPERSION-FAMILY).
    "dispersion": ("dp", "dpnorm", "juilland_d", "carroll_d2", "range_prop", "vc"),
    # Trend/Diachronie (Track T3): per-period normalized rate + Wilson CI.
    "trend": ("per_million", "wilson_ci"),
    # KWIC-Thinning-Provenienz (Track T1): served for tooltip/catalog use.
    "sample": ("random_sample",),
}

# logDice and Dice occur in word sketches and collocations. Evert's
# distance table uses plain token marginals, so both paths use Rychly's
# logDice formula. logdice_window retains the distance-table denominator
# |W(u)| + f(v).
_PAIR_EVENT_METHOD_OVERRIDES: dict[str, dict[str, str]] = {
    "logdice": {
        "latex_formula": r"14 + \log_2\!\left(\frac{2\,O_{11}}{f(u) + f(v)}\right)",
        "formula_mathml": _mathml(
            "<mn>14</mn><mo>+</mo>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac><mrow>"
            "<mn>2</mn>" + _MML_O11 + "</mrow><mrow><mi>f</mi><mo>(</mo><mi>u</mi>"
            "<mo>)</mo><mo>+</mo><mi>f</mi><mo>(</mo><mi>v</mi><mo>)</mo>"
            "</mrow></mfrac><mo>)</mo></mrow>"
        ),
        # The explanation claims Rychly's comparability across nodes because
        # the column computes Rychly's definition on the WORD FREQUENCIES.
        # With a pair event space (C_1 = m*f) the value would depend on the
        # node frequency: on a 142M-token index the top logDice of 'Menschen'
        # (m=139450) would be -2.30 to -2.67, negative where Rychly's scale
        # caps at 14. Recomputed over five nodes and 7,504 rows on a
        # 56,000-token test index: logdice == 14 + log2(2*O11/(f(u)+f(v))) on
        # EVERY row, none above 14. What is not comparable across nodes is
        # called logdice_window and appears below.
        # 14 is not a cap here: O11 counts collocate tokens, and one window can
        # hold the collocate several times. Node "alpha" in "alpha beta beta
        # beta gamma" (window 5): O11 = f(v) = 3, f(u) = 1, logdice 14.585.
        "explanation": lt(
            "logDice nach Rychlý 2008 auf den Wortfrequenzen: 14 + log2(2*O11 / "
            "(f(u) + f(v))). O11 ist die Zahl der Kollokat-Token in der "
            "Vereinigung der Fenster um alle Treffer des Knotens. Der Wert hängt "
            "nicht von der Korpusgröße ab. Er hängt von der Fensterbreite ab: O11 "
            "wächst mit dem Fenster, f(u) und f(v) nicht, Werte sind deshalb nur "
            "bei gleicher Fensterbreite vergleichbar. Steht das Kollokat im "
            "Fenster eines Treffers mehrmals, kann O11 größer als f(u) sein und "
            "der Wert über 14 liegen. Rychlý gibt Orientierungspunkte (meist unter "
            "10, ein Punkt mehr bedeutet doppelt so häufiges gemeinsames "
            "Vorkommen) und keine Schwelle für bemerkenswerte Kollokationen.",
            "logDice after Rychlý 2008 on the word frequencies: 14 + log2(2*O11"
            " / (f(u) + f(v))). O11 is the number of collocate tokens in the "
            "union of the windows around all hits of the node. The value does not"
            " depend on corpus size. It depends on the window size: O11 grows "
            "with the window, f(u) and f(v) do not, so values are comparable only"
            " for the same window size. When the collocate occurs several times "
            "in the window of one hit, O11 can exceed f(u) and the value can "
            "exceed 14. Rychlý gives orientation points (usually below 10, one "
            "point more means co-occurrence twice as frequent) and no threshold "
            "for notable collocations.",
        ),
        "reference": "Rychlý 2008",
    },
    "logdice_window": {
        "latex_formula": r"14 + \log_2\!\left(\frac{2\,O_{11}}{R_1 + C_1}\right)",
        "formula_mathml": _mathml(
            "<mn>14</mn><mo>+</mo>" + _MML_LOG2 + "<mrow><mo>(</mo><mfrac><mrow>"
            "<mn>2</mn>" + _MML_O11 + "</mrow><mrow>" + _MML_R1 + "<mo>+</mo>"
            + _MML_C1 + "</mrow></mfrac><mo>)</mo></mrow>"
        ),
        "explanation": lt(
            "Log-Transformation des Dice-Koeffizienten auf Everts Kontingenz"
            "tafel für distanzbasierte Kookkurrenzen: Nenner ist R1 + C1 mit "
            "R1 = Umfang der Fenster-Vereinigung |W(u)| und C1 = f(v). Weil R1 "
            "mit Knotenfrequenz und Fensterbreite wächst, sinkt das erreichbare "
            "Niveau bei häufigen Knoten. Der Wert rankt INNERHALB einer "
            "Kollokatliste und ist NICHT über Knoten oder Korpora vergleichbar. "
            "Rychlýs Orientierungspunkte beziehen sich auf die Spalte logdice. "
            "Das ist NICHT logDice nach Rychlý, dafür steht die Spalte logdice.",
            "Log transform of the Dice coefficient on Evert's contingency table"
            " for distance-based co-occurrences: the denominator is R1 + C1 "
            "with R1 = size of the window union |W(u)| and C1 = f(v). Because "
            "R1 grows with node frequency and window size, the attainable level"
            " drops for frequent nodes. The value ranks WITHIN one collocate "
            "list and is NOT comparable across nodes or corpora. Rychlý's "
            "orientation points refer to the logdice column. This is"
            " NOT logDice after Rychlý, which is the logdice column.",
        ),
        "reference": lt("Dice auf Evert 2004, Fig. 2.13", "Dice on Evert 2004, Fig. 2.13"),
    },
    "dice": {
        "latex_formula": r"\frac{2\,O_{11}}{R_1 + C_1}",
        "formula_mathml": _mathml(
            "<mfrac><mrow><mn>2</mn>" + _MML_O11 + "</mrow><mrow>" + _MML_R1
            + "<mo>+</mo>" + _MML_C1 + "</mrow></mfrac>"
        ),
    },
    "diff_per_million": {
        "latex_formula": (
            r"\frac{O_{11,t}}{N_{\Omega,t}}\cdot 10^6 - "
            r"\frac{O_{11,r}}{N_{\Omega,r}}\cdot 10^6"
        ),
        "formula_mathml": _mathml(
            "<mfrac><msub><mi>O</mi><mrow><mn>11</mn><mo>,</mo><mi>t</mi></mrow>"
            "</msub><msub><mi>N</mi><mrow><mi>&#937;</mi><mo>,</mo><mi>t</mi>"
            "</mrow></msub></mfrac><mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn>"
            "</msup><mo>&#8722;</mo><mfrac><msub><mi>O</mi><mrow><mn>11</mn>"
            "<mo>,</mo><mi>r</mi></mrow></msub><msub><mi>N</mi><mrow>"
            "<mi>&#937;</mi><mo>,</mo><mi>r</mi></mrow></msub></mfrac>"
            "<mo>&#8901;</mo><msup><mn>10</mn><mn>6</mn></msup>"
        ),
    },
}

# Significance level of the keyness LRC before the Bonferroni division
# (services.tools.keyness.LRC_ALPHA reads it from here).
KEYNESS_LRC_ALPHA = 0.001

# Default ranking sort key per analysis family (the field rows are returned by).
_METHOD_DEFAULT_SORT: dict[str, str] = {
    # Der Methodenblock muss dieselbe Vorgabe nennen wie das Werkzeugschema und
    # wie die Sortierung. "dice" war die Engine-Reihenfolge, nicht die Zusage.
    "collocates": "logdice",
    "keyness": "ll_signed",
    # Contrast rows are ranked by |diff_per_million| (server rows builder),
    # whatever measure fills target_score/reference_score.
    "contrast": "diff_abs",
    "frequency_diff": "diff_abs",
    "ngrams_diff": "diff_per_million",
    "ngrams": "freq",
    "wordsketch": "score",
    "lexical_diversity": "sttr",
    "dispersion": "dp",
    # Trend rows are chronological, not ranked by a statistic.
    "trend": "period",
    # A drawn sample keeps corpus order (positions ascending).
    "sample": "pos",
}


# Contrast of two sides: the log ratio compares the two per-million
# co-occurrence rates, not window against rest as on the collocation table.
_CONTRAST_METHOD_OVERRIDES: dict[str, dict[str, str]] = {
    "log_ratio": {
        "name": lt("Log Ratio der Kookkurrenzraten", "Log Ratio of the co-occurrence rates"),
        "latex_formula": (
            r"\log_2\!\left(\frac{(O_{11,t}+0.5)/N_{\Omega,t}}"
            r"{(O_{11,r}+0.5)/N_{\Omega,r}}\right)"
        ),
        "smoothing": lt("+0.5 in beiden Zellen", "+0.5 in both cells"),
        "sort_key": "log_ratio",
        "explanation": lt(
            "Verhältnis der beiden Kookkurrenzraten pro Token der Seite, "
            "log2-skaliert: 1 heißt doppelt so häufig in A wie in B. "
            "Dieselbe Grundlage wie die Spalten pro Million. Die Glättung "
            "+0,5 hält Kollokate endlich, die nur auf einer Seite vorkommen "
            "(one_sided).",
            "Ratio of the two co-occurrence rates per token of each side, on a "
            "log2 scale: 1 means twice as frequent in A as in B. The same basis"
            " as the per-million columns. The +0.5 smoothing keeps collocates "
            "finite that occur on one side only (one_sided).",
        ),
    },
}


# Frequency contrast: both rates divide by the word tokens of their side, the
# denominator of keyness for the same document sets.
_FREQUENCY_DIFF_METHOD_OVERRIDES: dict[str, dict[str, str]] = {
    "diff_per_million": {
        "name": lt("Differenz pro Million Worttoken", "Difference per million word tokens"),
        "explanation": lt(
            "Differenz der auf eine Million Worttoken normalisierten Häufigkeiten "
            "zwischen Ziel und Referenz. N_t und N_r sind die Worttoken der beiden "
            "Seiten, die Token mit mindestens einem Buchstaben oder einer Ziffer "
            "ohne |Marker|. Keyness teilt durch dieselben Zahlen und nennt für "
            "dieselben Dokumentmengen dieselbe Rate. Die Tokenzahl mit Satzzeichen "
            "steht als target_tokens_roh und reference_tokens_roh im Methodenblock. "
            "Deskriptives Maß ohne Signifikanzaussage. Der Absolutwert hängt stark "
            "von der Grundfrequenz des Ausdrucks ab.",
            "Difference between the frequencies per million word tokens in the "
            "target and the reference. N_t and N_r are the word tokens of the two "
            "sides, the tokens with at least one letter or digit and no |marker|. "
            "Keyness divides by the same numbers and reports the same rate for the "
            "same document sets. The token count with punctuation is given as "
            "target_tokens_roh and reference_tokens_roh in the method block. A "
            "descriptive measure without a statement about significance. The "
            "absolute value depends strongly on the base frequency of the "
            "expression.",
        ),
    },
}


def method_statistics(family: str, keys: tuple[str, ...] | list[str] | None = None) -> list[dict[str, str]]:
    """Return the ordered statistic descriptors for an analysis ``family``.

    Each descriptor is a copy of the METHOD_META entry with its ``key`` added
    so a consumer can map the field name back to the formula. ``keys``
    replaces the family default when a response carries a different set
    (the contrast job names the measure it scored with).
    """
    out: list[dict[str, str]] = []
    overrides: dict[str, dict[str, str]] = {}
    if family in {"collocates", "contrast"}:
        overrides = dict(_PAIR_EVENT_METHOD_OVERRIDES)
    if family == "contrast":
        overrides.update(_CONTRAST_METHOD_OVERRIDES)
    if family == "frequency_diff":
        overrides = dict(_FREQUENCY_DIFF_METHOD_OVERRIDES)
    for key in (keys if keys is not None else _METHOD_STATISTICS.get(family, ())):  # pragma: no branch
        meta = METHOD_META.get(key)
        if meta is None:
            continue
        entry = {"key": key, **meta, **overrides.get(key, {})}
        out.append(entry)
    return out


def collocation_method_extra(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return invariant provenance for every collocation surface.

    SEIT 2026-08-29 rechnen die Assoziationsstatistiken auf Everts
    Kontingenztafel fuer distanzbasierte Kookkurrenzen (2004, Fig. 2.13):
    R1 = |W(u)| ist der Umfang der Fenster-Vereinigung, C1 = f(v) die
    Korpusfrequenz des Kollokats, N = |T| die Korpustoken. Vorher stand hier
    der Anker-Token-Paarraum mit N = m*|T|, in dem log-likelihood, chi2,
    Dice und delta-P eine andere Zahl ergaben.

    Diese Felder sind maschinenlesbar und werden von Replikationen gelesen.
    Sie muessen der Rechnung folgen, nicht der Gewohnheit.
    """
    return {
        "event_space": "corpus_tokens",
        "event_total_definition": "scope_tokens",
        "row_marginal_definition": "window_union_size",
        "column_marginal_definition": "collocate_corpus_frequency",
        "contingency_reference": "Evert 2004, Fig. 2.13",
        "anchor_span_policy": "own_match_span_excluded",
        # The two margins of the table follow DIFFERENT case policies, and
        # these fields disclose it. On a 56,000-token test index
        # collocate_stats(term="DIE"|"Die"|"die") returns node_frequency=1241
        # each time (= die 1028 + Die 206 + DIE 7), so the node is resolved
        # via its str.lower class (_resolve_term_ids, "the FULL set of
        # case-matching lexicon ids"). The collocates stay separate per
        # lexicon id: und f2=797, Und f2=113, UND f2=9 on ranks 3, 57 and
        # 749, while the class has O11=189 and f(v)=919.
        #
        # The engine computes the table it builds CORRECTLY: all thirteen
        # measures reproduce by hand from (O11, R1, C1, N), all four
        # quantities are in tokens. The problem is the asymmetry, which
        # splits the evidence of one word class across several ranks, not
        # the arithmetic.
        #
        # WHY IT IS ONLY DISCLOSED AND NOT RESOLVED: the direction is open
        # and both ways out break an existing contract. Folding the collocate
        # too breaks the documented promise of
        # tests/backend/test_collocates_lemma_attribute_t2.py ("attribute=word
        # keeps the case variants separate", "attribute=lemma merges").
        # Not folding the node breaks the guarantee that a lowercase query of
        # a capitalised noun returns the same hits as the plain search. An
        # implementation of folding made 13 tests fail, including that
        # promise.
        # lowercase_class: the node is folded with str.lower, which folds case
        # only. str.casefold would also fold ß to ss and merge daß and dass.
        "node_case_policy": "lowercase_class",
        "collocate_case_policy": "surface_form",
        "case_policy_asymmetry": lt(
            "Der Knoten wird ohne Beachtung der Gross- und Kleinschreibung "
            "aufgeloest (ß und ss bleiben getrennt), das "
            "Kollokat je Schreibung gezaehlt. Eine Wortklasse kann deshalb "
            "als mehrere Zeilen erscheinen. Fuer eine zusammengefasste "
            "Kollokatseite attribute=lemma verwenden.",
            "The node is resolved without regard to upper and lower case "
            "(ß and ss stay separate), the collocate is counted per "
            "spelling. One word can therefore appear as several rows. For a "
            "combined collocate side, use attribute=lemma.",
        ),
        **(extra or {}),
    }


def collocation_frame_provenance(frame_attrs: Mapping[str, Any] | None) -> dict[str, Any]:
    """Contingency and LRC provenance the collocation frame carries in ``attrs``.

    ``window_union_size`` is R1 = |W(u)|, ``scope_tokens`` is N. With O11
    (``f``) and C1 (``f2``) of a row they reproduce every association column.
    ``lrc_tests`` is the Bonferroni basis m of the LRC: the candidates after the
    co-occurrence floor that can appear as rows (analyst tokens, no
    punctuation), tested at ``lrc_alpha / m``.
    """
    attrs = dict(frame_attrs or {})
    out: dict[str, Any] = {}
    if attrs.get("window_union_size") is not None:
        out["window_union_size"] = int(attrs["window_union_size"])
    if attrs.get("scope_tokens") is not None:
        out["scope_tokens"] = int(attrs["scope_tokens"])
    if attrs.get("lrc_vocab") is not None:
        out["lrc_alpha"] = float(attrs.get("lrc_alpha", 0.001))
        out["lrc_tests"] = int(attrs["lrc_vocab"])
        out["lrc_correction"] = "bonferroni"
        out["lrc_candidate_policy"] = "analyst_tokens_after_floor"
    return out


def kurzer_indexstand(signatur: str) -> str:
    """Die Indexsignatur als zwoelfstelliger Hash statt als Dateipfad.

    ``_corpus_cache_signature`` fuehrt sie als ``<absoluter Pfad>@<mtime_ns>``.
    Als Antwortfeld ``indexFingerprint`` verlaesst sie den Prozess, und damit
    stand das Heimatverzeichnis des Betreibers in jeder REST-Antwort der
    Analysefamilien, im Copilot-Ereignisstrom und in den Kopfzeilen der
    Exporte (``NgramsTab``/``WordSketchTab`` schreiben
    ``# indexFingerprint: ...`` in die Datei).

    Der Hash leistet, was die Angabe leisten soll: gleicher Index gleicher
    Wert, neu gebauter Index anderer Wert. Ein bereits gehashter Wert wird
    unveraendert durchgereicht, damit zweimaliges Anwenden nichts aendert.

    Hier und nicht in ``build_method_block``, denn dessen Vertrag ist die
    woertliche Durchreiche, gepinnt von
    ``tests/backend/test_provenance_r7.py`` mit ``"idx@123"``. Dieser
    korrekte Test bleibt unangetastet.
    """
    import hashlib

    roh = str(signatur or "")
    if not roh.strip():
        return ""
    if len(roh) == 12 and all(z in "0123456789abcdef" for z in roh):
        return roh
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:12]


#: Familien, deren Zaehlung ueber ``str.lower`` aggregiert. Gemessen, nicht
#: angenommen: nur diese drei rufen ``frequency_counts_docset(case_fold=True)``
#: oder ``_fold_freq_ids`` (keyness ueber drei Naehte, frequency ueber zwei,
#: frequency_diff ueber eine). Kollokation und N-Gramme falten nicht.
#:
#: Why this is disclosed: one row stands for all upper and lower case
#: spellings of its word, and the label names only one of them. The count
#: folds with ``str.lower``, not ``str.casefold``, because casefold also
#: folds ß to ss across the spelling reform. daß and dass stay separate rows.
FALTENDE_FAMILIEN = frozenset({"keyness", "frequency", "frequency_diff"})

#: "lowercase", not "casefold": casefold in the Unicode sense folds ß to ss,
#: and this count does not. candyconc-web reads the same value.
CASE_POLICY_GEFALTET = "case_insensitive (lowercase)"
# Label of a folded frequency row: the class's most frequent spelling in the
# whole corpus (CorpusIndex._casefold_label_ids). The count covers every
# spelling of the class.
LABEL_POLICY_GEFALTET = "most_frequent_surface_in_corpus"


def gleichmaessige_auswahl(anzahl: int, deckel: int) -> list[int]:
    """Gleichmaessig verteilte Indizes, die BEIDE Enden enthalten.

    Fuer eine Zeitreihe ist ein Kopfschnitt die einzige Kappungspolitik, die
    GARANTIERT das Ende verliert, also genau das, wonach eine Trendfrage
    fragt. Gemessen am 2026-08-30: 73 Jahresperioden 1949 bis 2021 hinein,
    60 Perioden 1949 bis 2008 heraus.

    Steht hier und nicht in ``tool_wrappers``: die Fassade ist unter Test
    durch ein Doppel ersetzt, und ``grounding_evidence`` braucht dieselbe
    Politik fuer den ZWEITEN Schnitt. Zwei Schnitte mit verschiedenen
    Politiken wuerden gegeneinander arbeiten.
    """
    if anzahl <= deckel:
        return list(range(anzahl))
    if deckel <= 1:
        return [anzahl - 1]
    schritt = (anzahl - 1) / (deckel - 1)
    return sorted({round(i * schritt) for i in range(deckel)})


#: Der Bucket fuer Dokumente ohne parsbares Datum. Er ist KEINE Periode der
#: Reihe und darf beim Ausduennen nie den jungen Endpunkt verdraengen.
OHNE_DATUM = "undatiert"
#: In welchem Feld die Periode steht.
OHNE_DATUM_FELD = "period"


def perioden_ausduennen(perioden: list, deckel: int) -> list:
    """Duennt eine Periodenreihe aus und haelt beide DATIERTEN Enden.

    Diese Funktion ist der Grund, dass es sie gibt: die Periodenliste wird
    ZWEIMAL gekuerzt, einmal im Werkzeug (Kontextdeckel) und einmal in der
    Belegoberflaeche (Modellsicht). Ein adversarialer Pruefer hat am
    2026-08-30 gezeigt, dass zwei getrennte Politiken gegeneinander arbeiten:
    der erste Schnitt behandelte ``undatiert`` als Sonderfall und haengte ihn
    hinten an, der zweite kannte den Sonderfall nicht, duennte ueber die ganze
    Liste aus und hielt garantiert den LETZTEN Index. Der war nach dem ersten
    Schnitt ``undatiert``, nicht die juengste datierte Periode. Das junge Ende
    ging also wieder verloren, genau der Defekt, gegen den der erste Schnitt
    repariert worden war.

    Beide Schnitte rufen jetzt DIESE Funktion.
    """
    ohne_datum = [p for p in perioden if str(p.get(OHNE_DATUM_FELD, "")) == OHNE_DATUM]
    reihe = [p for p in perioden if str(p.get(OHNE_DATUM_FELD, "")) != OHNE_DATUM]
    if len(perioden) <= int(deckel):
        return list(perioden)
    platz = max(int(deckel) - len(ohne_datum), 1)
    gewaehlt = [reihe[i] for i in gleichmaessige_auswahl(len(reihe), platz)]
    return gewaehlt + ohne_datum


def trend_kuerzungshinweis(perioden: list, gesamt: int) -> str:
    """Was die Kuerzung wirklich getan hat, in einem Satz.

    Der alte Text nannte als Ausweg genau die Einstellung, die der Aufrufer
    schon gewaehlt hatte ("granularity='year' verwenden"), und die einzige
    Alternative war auf demselben Korpus durch eine andere Schranke gesperrt.
    Er war woertlich aus der 422-Meldung der REST-Route uebernommen, wo er
    sinnvoll ist, und am neuen Ort nicht mehr wahr.

    Der Satz sagt jetzt, was da ist: wie viele Zeilen, welche Spanne, und dass
    eine Summe ueber die angezeigten Zeilen keine Summe ueber die Reihe ist.
    """
    if not perioden:
        return ""
    erste = str(perioden[0].get("period", ""))
    letzte = ""
    for zeile in reversed(perioden):
        wert = str(zeile.get("period", ""))
        if wert != "undatiert":
            letzte = wert
            break
    spanne = (
        lt(" {erste} bis {letzte},", " {erste} to {letzte},").format(erste=erste, letzte=letzte)
        if erste and letzte
        else ""
    )
    # UNTER 220 Zeichen bleiben: grounding_evidence kuerzt jede Warnung mit
    # _compact_text(item, 220), und abgeschnitten wurde bisher genau der
    # Schlusssatz, also die einzige Aussage mit Warnwert.
    return lt(
        "Reihe ausgedünnt auf {shown} von {total} Perioden,"
        "{span} gleichmäßig verteilt, Werte unverändert. "
        "Zwischenperioden fehlen: eine Summe über die gezeigten Zeilen ist "
        "KEINE Summe über die Reihe.",
        "Series thinned to {shown} of {total} periods,{span} evenly spaced, "
        "values unchanged. Periods in between are missing: a sum over the "
        "rows shown is NOT a sum over the series.",
    ).format(shown=len(perioden), total=gesamt, span=spanne)


def build_method_block(
    family: str,
    *,
    index_fingerprint: str | None = None,
    target_total: int | None = None,
    reference_total: int | None = None,
    window: int | None = None,
    within_sentence: bool | None = None,
    sort_key: str | None = None,
    counting_attribute: str | None = None,
    extra: dict[str, Any] | None = None,
    statistics: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the per-response statistical-provenance ``method`` block.

    This is the single helper every analysis route uses so the provenance
    contract (Track F1, frontend Track B7) stays identical across endpoints.

    Returned shape (top-level ``method`` object on each response)::

        {
          "family": "keyness",
          "statistics": [{key, name, latex_formula, smoothing, sort_key}, ...],
          "default_sort": "ll_signed",
          "indexFingerprint": "<corpus cache signature>",   # if available
          "target_total": <int>, "reference_total": <int>,  # if available
          "window": <int>, "within_sentence": <bool>,       # collocation scope
          ...extra                                            # family extras
        }

    All numeric/scope fields are omitted when ``None`` so the block degrades
    gracefully (e.g. keyness has no window; n-grams have no totals).
    """
    block: dict[str, Any] = {
        "family": family,
        "statistics": method_statistics(family, statistics),
        "default_sort": sort_key or _METHOD_DEFAULT_SORT.get(family, ""),
    }
    if family == "keyness":
        # The LRC column of every keyness row: exact interval at alpha/m,
        # m = the candidates after min_freq, which the response reports as
        # total_candidates.
        block["lrc_alpha"] = KEYNESS_LRC_ALPHA
        block["lrc_correction"] = "bonferroni"
        block["lrc_tests"] = "total_candidates"
    if index_fingerprint:
        block["indexFingerprint"] = str(index_fingerprint)
    if target_total is not None:
        block["target_total"] = int(target_total)
    if reference_total is not None:
        block["reference_total"] = int(reference_total)
    if window is not None:
        block["window"] = int(window)
    if within_sentence is not None:
        block["within_sentence"] = bool(within_sentence)
    if family in FALTENDE_FAMILIEN and counting_attribute is not None:
        attribut = str(counting_attribute).strip().lower()
        if attribut in {"word", "lemma"}:
            block["case_policy"] = CASE_POLICY_GEFALTET
    if extra:
        for key, value in extra.items():
            block.setdefault(key, value)
    return block


# ---------------------------------------------------------------------------
# Word-sketch reliability floor — single source of truth (Track WS-DIFF-NOFLOOR
# + WS-COPILOT-NOFLOOR). The REST profile endpoint suppresses f=1/f=2 hapaxes
# (typos, list bullets) that an inflated single-cell chi2 would otherwise
# headline. BOTH sibling surfaces — the copilot ``word_sketch`` tool and the
# ``/analysis/wordsketch_diff`` difference path — MUST inherit the SAME floor so
# none of them headlines a hapax the profile drops. They import this ONE helper
# rather than re-deriving an inline threshold.
# ---------------------------------------------------------------------------
WORD_SKETCH_DEFAULT_MIN_FREQ = 3


def apply_word_sketch_min_freq(
    tables: dict[str, Any],
    *,
    min_freq: int = WORD_SKETCH_DEFAULT_MIN_FREQ,
) -> dict[str, Any]:
    """Drop word-sketch rows with co-occurrence frequency ``f`` < ``min_freq``.

    Operates on the relation -> table mapping the word-sketch path produces
    (``tools.word_sketch.word_sketch`` / ``server._word_sketch_for_query``);
    each value is a pandas DataFrame (or a list of row dicts) carrying an ``f``
    co-occurrence-count column. Relations left empty by the floor are removed.
    ``min_freq <= 0`` disables the floor (returns the tables unchanged) so a
    caller can explicitly opt out, matching the REST ``min_freq=0`` contract.

    This is the ONE place the reliability floor lives for the non-REST sibling
    surfaces; the REST endpoint applies the identical floor row-by-row via
    ``routes/analysis._word_sketch_rank_rows`` (same default constant).
    """
    if not tables or int(min_freq) <= 0:
        return tables
    floor = int(min_freq)
    out: dict[str, Any] = {}
    for relation, table in tables.items():
        if isinstance(table, pd.DataFrame):
            if table.empty or "f" not in table.columns:
                if not table.empty:
                    out[relation] = table
                continue
            kept = table[pd.to_numeric(table["f"], errors="coerce").fillna(0).astype(np.int64) >= floor]
            if kept.empty:
                continue
            kept = kept.reset_index(drop=True)
            if "rank" in kept.columns:
                kept["rank"] = np.arange(1, len(kept) + 1, dtype=np.int64)
            out[relation] = kept
        elif isinstance(table, list):
            kept_rows = []
            for row in table:
                try:
                    f_val = int(row.get("f", 0))
                except (TypeError, ValueError, AttributeError):
                    f_val = 0
                if f_val >= floor:
                    kept_rows.append(row)
            if not kept_rows:
                continue
            for i, row in enumerate(kept_rows, start=1):
                if "rank" in row:
                    row["rank"] = i
            out[relation] = kept_rows
        elif table is not None:
            out[relation] = table
    return out


# Shared adaptive co-occurrence floor for REST and copilot.
# A fixed floor of 5 can remove every collocate of a rare node. Calibrate
# from node frequency through tools.collocate_stats for both interfaces.
# The lower bound of 2 excludes co-occurrence hapaxes. For counts below 5,
# asymptotic ll, chi2 and t statistics are unstable, so interpretation
# needs the raw frequency and corpus evidence. At or above
# COLLOCATE_ADAPTIVE_NODE_THRESHOLD, keep COLLOCATE_DEFAULT_MIN_FREQ.
COLLOCATE_DEFAULT_MIN_FREQ = 5
COLLOCATE_EXPLORATORY_MIN_FREQ = 2
COLLOCATE_ADAPTIVE_NODE_THRESHOLD = 50


def collocate_floor_herkunft(
    floor_mode: Any, node_frequency: Any
) -> str:
    """Woher die Mindestfrequenz kommt, in einem Satzteil.

    Steht neben :func:`collocate_floor_mode`, weil es dessen Ausgabe deutet
    und mit ihr zusammen geaendert werden muss.

    ``adaptive`` alone is a false statement above the threshold:
    :func:`adaptive_collocate_min_freq` returns the default floor CONSTANTLY
    from a node frequency of ``COLLOCATE_ADAPTIVE_NODE_THRESHOLD`` on,
    regardless of the value (for 50, 51, 100, 1,241, 35,910 and 139,450
    always 5). For every realistic node that is not a calibrated floor, and
    "aus der Knotenfrequenz kalibriert" would claim a calibration that did
    not take place. The label therefore splits along THE SAME threshold the
    function draws.
    """

    modus = str(floor_mode or "").strip()
    fest = {
        "requested": lt("als Argument gesetzt", "set as an argument"),
        # Angehoben ist nicht gesetzt (Anforderung 1 -> 2).
        "requested_raised": lt(
            "angefordert und auf den Zuverlässigkeitsboden angehoben",
            "requested and raised to the reliability floor",
        ),
        "default": lt("Standardboden ohne Kalibrierungsbasis", "default floor without a calibration basis"),
    }
    if modus in fest:
        return fest[modus]
    if modus != "adaptive":
        return ""
    try:
        knoten = int(node_frequency)
    except (TypeError, ValueError):
        return lt("aus der Knotenfrequenz kalibriert", "calibrated from the node frequency")
    if knoten >= COLLOCATE_ADAPTIVE_NODE_THRESHOLD:
        return lt(
            "Standardboden, Knotenfrequenz {node} über der Kalibrierungsschwelle {threshold}",
            "default floor, node frequency {node} above the calibration threshold {threshold}",
        ).format(node=knoten, threshold=COLLOCATE_ADAPTIVE_NODE_THRESHOLD)
    if knoten <= 0:
        # A zero-hit result has no observed node frequency to calibrate from.
        # Report the default floor without claiming an adaptive calculation.
        return lt(
            "Untergrenze des Bodens, der Knoten hat keine Treffer",
            "lower bound of the floor, the node has no hits",
        )
    return lt(
        "aus der Knotenfrequenz {node} kalibriert, ein Zehntel davon, begrenzt auf 2 bis 5",
        "calibrated from the node frequency {node}, one tenth of it, limited to 2 to 5",
    ).format(node=knoten)


def collocate_floor_mode(requested: int | None, effective: int, node_freq: int | None) -> str:
    """Die Herkunft des Kookkurrenz-Bodens, an EINER Stelle (P2.3).

    Drei Erzeuger haben diesen Block wortgleich gefuehrt: der
    Copilot-Wrapper, die synchrone REST-Route und ``_run_collocates_job``.
    Die erste Fassung des Fixes hat zwei davon nachgezogen. Ergebnis: die
    synchrone Route meldete bei ``min_freq=1`` ``requested_raised``, der
    Job-Pfad weiterhin ``requested`` -- und der Job-Pfad ist der, den die
    Produktoberflaeche benutzt, waehrend die synchrone Route in
    ``capabilities/product.py`` ein reiner Expert/API-Pfad ist. Repariert
    war also der Pfad, den die Oberflaeche NICHT benutzen darf.

    ``requested_raised`` heisst: angefordert, aber vom Zuverlaessigkeitsboden
    oder vom Kandidaten-Builder ANGEHOBEN. ``adaptive_collocate_min_freq``
    klemmt jeden expliziten Wert auf mindestens
    ``COLLOCATE_EXPLORATORY_MIN_FREQ`` (2) hoch, ein f=1-Paar ist ein
    Kookkurrenz-Hapax. Wer 1 anfordert und 2 bekommt, hat 1 gesetzt.
    """
    if requested and int(requested) > 0:
        return (
            "requested"
            if int(effective) == int(requested)
            else "requested_raised"
        )
    if node_freq is not None:
        return "adaptive"
    return "default"


def adaptive_collocate_min_freq(
    node_freq: int | None, requested: int | None = None
) -> int:
    """Resolve the effective collocation co-occurrence floor.

    ``requested`` wins when given (> 0), but never below
    ``COLLOCATE_EXPLORATORY_MIN_FREQ`` (2): an f=1 pair is a co-occurrence
    hapax and never reportable. ``requested`` in (None, 0) means AUTO:

    - ``node_freq >= COLLOCATE_ADAPTIVE_NODE_THRESHOLD`` (50) ->
      ``COLLOCATE_DEFAULT_MIN_FREQ`` (5, the historical floor, byte-stable);
    - rarer nodes -> ``clamp(2, node_freq // 10, 5)`` so a 5-hit node gets
      floor 2 instead of a structurally empty result.

    ``node_freq=None`` (caller could not determine the node frequency, e.g. a
    builder without the adaptive seam) falls back to the historical default
    floor of 5 in auto mode.
    """
    try:
        requested_int = int(requested) if requested is not None else 0
    except (TypeError, ValueError):
        requested_int = 0
    if requested_int > 0:
        return max(COLLOCATE_EXPLORATORY_MIN_FREQ, requested_int)
    if node_freq is None:
        return COLLOCATE_DEFAULT_MIN_FREQ
    try:
        node_freq_int = int(node_freq)
    except (TypeError, ValueError):
        return COLLOCATE_DEFAULT_MIN_FREQ
    if node_freq_int >= COLLOCATE_ADAPTIVE_NODE_THRESHOLD:
        return COLLOCATE_DEFAULT_MIN_FREQ
    return max(
        COLLOCATE_EXPLORATORY_MIN_FREQ,
        min(node_freq_int // 10, COLLOCATE_DEFAULT_MIN_FREQ),
    )


_WORD_SKETCH_BLOCKED_RELATIONS = {
    "ROOT",
    "ROOT_rev",
    "punct",
    "punct_rev",
    "case",
    "case_rev",
    "pnc",
    "pnc_rev",
}


# Human-readable glosses for the raw dependency relation codes the word-sketch
# path emits (FT id 10), one table per annotation scheme. The codes are
# standard but cryptic for a non-expert (sb_rev, oa_rev, nk, ag_rev, ...).
# ``_rev`` marks the REVERSED direction: without it the node is the HEAD and
# the collocate its dependent (``sb`` = "hat als Subjekt"), with it the node
# is the DEPENDENT (``sb_rev`` = "Subjekt von").
#
# The same code means different things in different schemes: TIGER ``cc`` is
# a comparative complement, ClearNLP ``cc`` a coordinating conjunction. The
# table is therefore chosen by the annotation scheme of the corpus
# (:func:`candyconc.domain.corpus.dependency_label_scheme`), never by the
# interface language. Codes outside the chosen table stay raw.
#
# TIGER labels: G. Smith, "A Brief Introduction to the TIGER Treebank,
# Version 1", IMS Stuttgart, edge label list. spaCy's German pipelines use
# them and add ``dep`` (unclassified dependent).
_WORD_SKETCH_RELATION_GLOSSES: dict[str, str] = {
    "sb": lt("hat als Subjekt", "has subject"),
    "sb_rev": lt("Subjekt von", "subject of"),
    "sbp": lt("hat als passiviertes Subjekt (PP)", "has passivised subject (PP)"),
    "sbp_rev": lt("passiviertes Subjekt (PP) von", "passivised subject (PP) of"),
    "sp": lt("Subjekt oder Prädikativ", "subject or predicate"),
    "oa": lt("hat als Akkusativobjekt", "has accusative object"),
    "oa_rev": lt("Akkusativobjekt von", "accusative object of"),
    "oa2": lt("hat als zweites Akkusativobjekt", "has second accusative object"),
    "oa2_rev": lt("zweites Akkusativobjekt von", "second accusative object of"),
    "da": lt("hat als Dativobjekt", "has dative object"),
    "da_rev": lt("Dativobjekt von", "dative object of"),
    "og": lt("hat als Genitivobjekt", "has genitive object"),
    "og_rev": lt("Genitivobjekt von", "genitive object of"),
    "op": lt("hat als Präpositionalobjekt", "has prepositional object"),
    "op_rev": lt("Präpositionalobjekt von", "prepositional object of"),
    "oc": lt("hat als Satzobjekt", "has clausal object"),
    "oc_rev": lt("Satzobjekt von", "clausal object of"),
    "nk": lt("Kern/Attribut im Nominal (Nomen-Kern)", "kernel or attribute in the nominal (noun kernel)"),
    # The node is an NK element of the collocate (adjective or determiner of
    # the noun), so it modifies the collocate and not the other way round.
    "nk_rev": lt("Nomen-Kern-Element von", "noun kernel element of"),
    "ag": lt("hat als Genitivattribut", "has genitive attribute"),
    "ag_rev": lt("Genitivattribut von", "genitive attribute of"),
    "mo": lt("hat als Modifikator", "has modifier"),
    "mo_rev": lt("Modifikator von", "modifier of"),
    "mnr": lt("hat als nachgestellten Modifikator", "has postnominal modifier"),
    "mnr_rev": lt("nachgestellter Modifikator von", "postnominal modifier of"),
    "cj": lt("Konjunkt (verbunden mit)", "conjunct (coordinated with)"),
    "cj_rev": lt("Konjunkt (verbunden mit)", "conjunct (coordinated with)"),
    "cd": lt("Koordinator", "coordinating conjunction"),
    "cd_rev": lt("Koordinator von", "coordinating conjunction of"),
    "cc": lt("Vergleichskomplement", "comparative complement"),
    "cc_rev": lt("Vergleichskomplement von", "comparative complement of"),
    "cm": lt("Vergleichspartikel/Konjunktion", "comparative conjunction"),
    "cm_rev": lt("Vergleichspartikel/Konjunktion von", "comparative conjunction of"),
    "cp": lt("Komplementierer", "complementizer"),
    "cp_rev": lt("Komplementierer von", "complementizer of"),
    "pd": lt("hat als Prädikativ", "has predicate"),
    "pd_rev": lt("Prädikativ von", "predicate of"),
    "pg": lt("Pseudo-Genitiv (von-Konstruktion)", "phrasal genitive (von construction)"),
    "pg_rev": lt("Pseudo-Genitiv von", "phrasal genitive of"),
    "rc": lt("hat als Relativsatz", "has relative clause"),
    "rc_rev": lt("Relativsatz von", "relative clause of"),
    "rs": lt("hat als berichtete Rede", "has reported speech"),
    "rs_rev": lt("berichtete Rede von", "reported speech of"),
    "re": lt("hat als wiederholtes Element", "has repeated element"),
    "re_rev": lt("wiederholtes Element von", "repeated element of"),
    "ng": lt("Negation", "negation"),
    "ng_rev": lt("negiert", "negates"),
    "svp": lt("Verbpartikel", "separable verb prefix"),
    "svp_rev": lt("Verbpartikel von", "separable verb prefix of"),
    "ams": lt("Maß-/Mengenangabe", "measure argument of adjective"),
    "ams_rev": lt("Maß-/Mengenangabe von", "measure argument of"),
    "app": lt("Apposition", "apposition"),
    "app_rev": lt("Apposition von", "apposition of"),
    "par": lt("Parenthese", "parenthetical element"),
    "par_rev": lt("Parenthese von", "parenthetical element of"),
    "ju": lt("Junktor", "junctor"),
    "ju_rev": lt("Junktor von", "junctor of"),
    "uc": lt("Einheitskomponente", "unit component"),
    "uc_rev": lt("Einheitskomponente von", "unit component of"),
    # TIGER AVC is an adverbial phrase component, not an adverbial complement.
    "avc": lt("Adverbialphrasen-Komponente", "adverbial phrase component"),
    "avc_rev": lt("Adverbialphrasen-Komponente von", "adverbial phrase component of"),
    "cvc": lt("Kollokationsverb-Komplement", "collocational verb construction"),
    "cvc_rev": lt("Kollokationsverb-Komplement von", "collocational verb construction of"),
    "dm": lt("Diskursmarker", "discourse marker"),
    "dm_rev": lt("Diskursmarker von", "discourse marker of"),
    "ep": lt("expletives es", "expletive es"),
    "ep_rev": lt("expletives es von", "expletive es of"),
    "ph": lt("Platzhalter", "placeholder"),
    "ph_rev": lt("Platzhalter von", "placeholder of"),
    "vo": lt("Vokativ", "vocative"),
    "vo_rev": lt("Vokativ von", "vocative of"),
    "ac": lt("adpositionaler Kasusmarker", "adpositional case marker"),
    "adc": lt("Adjektivkomponente", "adjective component"),
    "dh": lt("Diskurs-Kopf", "discourse-level head"),
    "hd": lt("Kopf", "head"),
    "nmc": lt("Zahlkomponente", "numerical component"),
    "pm": lt("morphologische Partikel", "morphological particle"),
    "dep": lt("nicht klassifizierte Abhängigkeit", "unclassified dependent"),
}

# ClearNLP labels as used by spaCy's English pipelines: ClearNLP dependency
# guidelines, "Dependency Labels" (github.com/clir/clearnlp-guidelines).
_WORD_SKETCH_CLEARNLP_GLOSSES: dict[str, str] = {
    "acl": lt("hat als Satzattribut", "has clausal modifier"),
    "acl_rev": lt("Satzattribut von", "clausal modifier of"),
    "acomp": lt("hat als adjektivisches Komplement", "has adjectival complement"),
    "acomp_rev": lt("adjektivisches Komplement von", "adjectival complement of"),
    "advcl": lt("hat als Adverbialsatz", "has adverbial clause modifier"),
    "advcl_rev": lt("Adverbialsatz von", "adverbial clause modifier of"),
    "advmod": lt("hat als Adverbialmodifikator", "has adverbial modifier"),
    "advmod_rev": lt("Adverbialmodifikator von", "adverbial modifier of"),
    "agent": lt("hat als Agens", "has agent"),
    "agent_rev": lt("Agens von", "agent of"),
    "amod": lt("hat als adjektivischen Modifikator", "has adjectival modifier"),
    "amod_rev": lt("adjektivischer Modifikator von", "adjectival modifier of"),
    "appos": lt("hat als Apposition", "has appositional modifier"),
    "appos_rev": lt("Apposition von", "appositional modifier of"),
    "attr": lt("hat als Prädikatsnomen (Attribut)", "has attribute"),
    "attr_rev": lt("Prädikatsnomen (Attribut) von", "attribute of"),
    "aux": lt("hat als Hilfsverb", "has auxiliary"),
    "aux_rev": lt("Hilfsverb von", "auxiliary of"),
    "auxpass": lt("hat als Passiv-Hilfsverb", "has passive auxiliary"),
    "auxpass_rev": lt("Passiv-Hilfsverb von", "passive auxiliary of"),
    "cc": lt("hat als koordinierende Konjunktion", "has coordinating conjunction"),
    "cc_rev": lt("koordinierende Konjunktion von", "coordinating conjunction of"),
    "ccomp": lt("hat als Komplementsatz", "has clausal complement"),
    "ccomp_rev": lt("Komplementsatz von", "clausal complement of"),
    "compound": lt("hat als Kompositionsglied", "has compound modifier"),
    "compound_rev": lt("Kompositionsglied von", "compound modifier of"),
    "conj": lt("hat als Konjunkt", "has conjunct"),
    "conj_rev": lt("Konjunkt von", "conjunct of"),
    "csubj": lt("hat als Subjektsatz", "has clausal subject"),
    "csubj_rev": lt("Subjektsatz von", "clausal subject of"),
    "csubjpass": lt("hat als Subjektsatz (Passiv)", "has clausal subject (passive)"),
    "csubjpass_rev": lt("Subjektsatz (Passiv) von", "clausal subject (passive) of"),
    "dative": lt("hat als Dativ", "has dative"),
    "dative_rev": lt("Dativ von", "dative of"),
    "dep": lt("hat als nicht klassifizierte Abhängigkeit", "has unclassified dependent"),
    "dep_rev": lt("nicht klassifizierte Abhängigkeit von", "unclassified dependent of"),
    "det": lt("hat als Determinierer", "has determiner"),
    "det_rev": lt("Determinierer von", "determiner of"),
    "dobj": lt("hat als direktes Objekt", "has direct object"),
    "dobj_rev": lt("direktes Objekt von", "direct object of"),
    "expl": lt("hat als Expletivum", "has expletive"),
    "expl_rev": lt("Expletivum von", "expletive of"),
    "intj": lt("hat als Interjektion", "has interjection"),
    "intj_rev": lt("Interjektion von", "interjection of"),
    "mark": lt("hat als Markierer", "has marker"),
    "mark_rev": lt("Markierer von", "marker of"),
    "meta": lt("hat als Metamodifikator", "has meta modifier"),
    "meta_rev": lt("Metamodifikator von", "meta modifier of"),
    "neg": lt("hat als Negationsmodifikator", "has negation modifier"),
    "neg_rev": lt("Negationsmodifikator von", "negation modifier of"),
    "nmod": lt("hat als Nominalmodifikator", "has nominal modifier"),
    "nmod_rev": lt("Nominalmodifikator von", "nominal modifier of"),
    "npadvmod": lt("hat als adverbiale Nominalphrase", "has noun phrase as adverbial modifier"),
    "npadvmod_rev": lt("adverbiale Nominalphrase von", "noun phrase as adverbial modifier of"),
    "nsubj": lt("hat als nominales Subjekt", "has nominal subject"),
    "nsubj_rev": lt("nominales Subjekt von", "nominal subject of"),
    "nsubjpass": lt("hat als nominales Subjekt (Passiv)", "has nominal subject (passive)"),
    "nsubjpass_rev": lt("nominales Subjekt (Passiv) von", "nominal subject (passive) of"),
    "nummod": lt("hat als Zahlmodifikator", "has number modifier"),
    "nummod_rev": lt("Zahlmodifikator von", "number modifier of"),
    "oprd": lt("hat als Objektsprädikativ", "has object predicate"),
    "oprd_rev": lt("Objektsprädikativ von", "object predicate of"),
    "parataxis": lt("hat als Parataxe", "has parataxis"),
    "parataxis_rev": lt("Parataxe von", "parataxis of"),
    "pcomp": lt("hat als Komplement der Präposition", "has complement of preposition"),
    "pcomp_rev": lt("Komplement der Präposition", "complement of preposition"),
    "pobj": lt("hat als Objekt der Präposition", "has object of preposition"),
    "pobj_rev": lt("Objekt der Präposition", "object of preposition"),
    "poss": lt("hat als Possessivmodifikator", "has possession modifier"),
    "poss_rev": lt("Possessivmodifikator von", "possession modifier of"),
    "preconj": lt("hat als vorangestellte Korrelativkonjunktion", "has pre-correlative conjunction"),
    "preconj_rev": lt("vorangestellte Korrelativkonjunktion von", "pre-correlative conjunction of"),
    "predet": lt("hat als Prädeterminierer", "has pre-determiner"),
    "predet_rev": lt("Prädeterminierer von", "pre-determiner of"),
    "prep": lt("hat als Präpositionalmodifikator", "has prepositional modifier"),
    "prep_rev": lt("Präpositionalmodifikator von", "prepositional modifier of"),
    "prt": lt("hat als Partikel", "has particle"),
    "prt_rev": lt("Partikel von", "particle of"),
    "quantmod": lt("hat als Quantorenmodifikator", "has quantifier modifier"),
    "quantmod_rev": lt("Quantorenmodifikator von", "quantifier modifier of"),
    "relcl": lt("hat als Relativsatz", "has relative clause modifier"),
    "relcl_rev": lt("Relativsatz von", "relative clause modifier of"),
    "xcomp": lt("hat als offenes Satzkomplement", "has open clausal complement"),
    "xcomp_rev": lt("offenes Satzkomplement von", "open clausal complement of"),
}

WORD_SKETCH_GLOSS_SCHEMES: dict[str, dict[str, str]] = {
    "tiger": _WORD_SKETCH_RELATION_GLOSSES,
    "clearnlp": _WORD_SKETCH_CLEARNLP_GLOSSES,
}


def word_sketch_relation_label(relation: str, scheme: str | None = "tiger") -> str:
    """Gloss for a raw word-sketch dependency code in the corpus's ``scheme``.

    ``scheme`` names the annotation scheme of the corpus (``tiger``,
    ``clearnlp``). An unknown scheme (``None``) or a code outside the scheme's
    table returns the raw code, so an unmapped relation still renders without
    a borrowed gloss. The default ``tiger`` keeps the behaviour of callers that
    do not pass a scheme. The ``_rev`` suffix encodes the reversed direction.
    """
    rel = str(relation or "")
    glosses = WORD_SKETCH_GLOSS_SCHEMES.get(scheme or "")
    if glosses is None:
        return rel
    gloss = glosses.get(rel)
    if gloss is not None:
        return gloss
    if rel.endswith("_rev"):
        base = rel[: -len("_rev")]
        base_gloss = glosses.get(base)
        if base_gloss is not None:
            return base_gloss + lt(" (umgekehrte Richtung)", " (reverse direction)")
    return rel


def is_analyst_token(token: Any) -> bool:
    text = str(token or "").strip()
    if not text:
        return False
    if text.startswith("|") and text.endswith("|"):
        return False
    return any(ch.isalnum() for ch in text)


def analysierbare_groesse(freq_map: Mapping[str, Any]) -> int:
    """The population on which a filtered statistic actually computes.

    Keyness and log-ratio compare p(w | target) with p(w | reference). The
    numerator is filtered by ``is_analyst_token``: punctuation, line breaks
    and markers such as ``|LBR|`` are dropped because they would otherwise
    lead every ranking. A denominator taken from ``docset_token_count``
    (the full token count of the subcorpus) would put numerator and
    denominator on different populations. Both probabilities then become too
    small, and by different amounts as soon as the two sides contain
    different amounts of punctuation. That is exactly when a sign flips and
    "more frequent in the target" turns into "less frequent".

    Size of the effect on a corpus of 250,535 documents:

        docset_token_count            142,044,149
        sum of analysable counts      114,695,183
        filtered out                   27,348,966   19.25 percent
        denominator too large by                    23.84 percent

    The filtered types are not evenly distributed. The largest are "," with
    7.57 million, "." with 6.56 million and "*" with 3.06 million. The star
    is Markdown markup and occurs far more often on the machine-generated
    side of a human and AI corpus.

    Hence the rule: whoever filters the numerator counts the denominator
    from the same filtered inventory.
    """
    return int(sum(int(anzahl) for anzahl in freq_map.values()))


def filter_frequency_frame(df: Any) -> Any:
    if df is None:
        return df
    if isinstance(df, pl.DataFrame):
        if "word" not in df.columns or df.is_empty():
            return df
        mask = [is_analyst_token(word) for word in df.get_column("word").to_list()]
        return df.filter(pl.Series("mask", mask))
    if isinstance(df, pd.DataFrame):
        if "word" not in df.columns or df.empty:
            return df
        mask = df["word"].map(is_analyst_token)
        return df[mask].reset_index(drop=True)
    return df


#: Vorzugsreihenfolge der Rangmasse, wenn kein ``sort_by`` gesetzt ist.
#:
#: EINE Liste fuer die Vorgabe-Sortierung UND fuer die Frage, unter welchem
#: Mass eine verworfene Zeile berichtet wird. Zwei Kopien waeren genau die
#: Naht, an der beide auseinanderlaufen: die Rangfolge stuende dann unter
#: logdice und die Bilanz unter dice.
COLLOCATE_SORT_PREFERENCE = ("logdice", "dice", "ll", "t", "f")

#: Hoechstens so viele verworfene Zeilen werden namentlich gefuehrt. Eine
#: Bilanz, die zwanzig Interpunktionszeichen aufzaehlt, ist keine Auskunft.
ANALYSETOKEN_SPITZE = 3


def analysetoken_sortmass(spalten: Any, sort_by: str | None = None) -> str | None:
    """Das Mass, unter dem eine Kollokatzeile berichtet wird."""
    vorhanden = set(spalten or ())
    schluessel = (sort_by or "").strip().lower()
    if schluessel and schluessel in vorhanden:
        return schluessel
    for kandidat in COLLOCATE_SORT_PREFERENCE:
        if kandidat in vorhanden:
            return kandidat
    return None


def analysetoken_spitze(zeilen: Any, sort_by: str | None = None) -> list[str]:
    """Die staerksten vom Analyse-Token-Filter verworfenen Zeilen als Text.

    Zurueck kommen fertige Angaben der Form ``"," (logdice 12,25)``. Der
    MASSNAME steht dabei, weil ein Wert ohne ihn eine Zahl ohne
    Groessenklasse ist, und die Verwechslung von Groessenklassen ist einer
    der harten Fehler, die dieses Projekt ausdruecklich zaehlt.

    Fehlt jede Masspalte, steht nur das Wort da. Eine erfundene Zahl waere
    schlimmer als keine.
    """
    posten = [
        z for z in (zeilen or [])
        if isinstance(z, Mapping) and str(z.get("word") or "").strip()
    ]
    if not posten:
        return []
    mass = analysetoken_sortmass(
        {spalte for zeile in posten for spalte in zeile}, sort_by
    )

    def _wert(zeile: Mapping) -> float:
        try:
            zahl = float(zeile.get(mass))
        except (TypeError, ValueError):
            return float("-inf")
        return zahl if zahl == zahl else float("-inf")

    if mass is not None:
        posten = sorted(posten, key=lambda z: (-_wert(z), str(z.get("word"))))
    heraus: list[str] = []
    for zeile in posten[:ANALYSETOKEN_SPITZE]:
        wort = str(zeile.get("word")).strip()
        zahl = _wert(zeile) if mass is not None else float("-inf")
        if mass is None or zahl == float("-inf"):
            heraus.append(lt(f"\u201e{wort}\u201c", f"“{wort}”"))
        else:
            gerundet = f"{zahl:.2f}".replace(".", ",")
            heraus.append(lt(f"\u201e{wort}\u201c ({mass} {gerundet})", f"“{wort}” ({mass} {zahl:.2f})"))
    return heraus


def analysetoken_bilanz(roh: Any, verworfen: Any, sort_by: str | None) -> dict:
    """Bookkeeping for the analysis token filter.

    On a paired human and AI corpus the filter removes ``*``, ``#`` and
    ``|``, the three strongest human versus AI differences of the whole
    profile. Without this record no output said so, and readers concluded
    that the model had overlooked these rows when it had never seen them.

    The filter stays, because ranking ``,`` and ``.`` as collocates is the
    defect it prevents. This record states what it removed.
    """
    return {
        "analysetoken_kandidaten": int(len(roh)),
        "analysetoken_gefiltert": int(len(verworfen)),
        "analysetoken_spitze": analysetoken_spitze(verworfen, sort_by),
    }


def normalize_default_collocate_frame(df: pd.DataFrame, sort_by: str | None) -> pd.DataFrame:
    if df is None or not hasattr(df, "columns") or df.empty or "word" not in df.columns:
        return df
    sort_key = (sort_by or "").strip().lower()

    # Die verworfenen Zeilen werden GEZAEHLT, bevor sie verschwinden. Sie
    # liegen hier bereits im Speicher, es ist Buchfuehrung und keine
    # zweite Rechnung. Die Bilanz reist in ``attrs`` mit, dem Weg, auf dem
    # dieser Rahmen schon node_frequency und effective_min_count traegt.
    behalten = df["word"].map(is_analyst_token)
    bilanz = analysetoken_bilanz(
        df, df[~behalten].to_dict("records"), sort_key or sort_by
    )

    def _mit_bilanz(rahmen: pd.DataFrame) -> pd.DataFrame:
        # attrs wird ueber Filter und sort_values weitergereicht, aber das
        # ist pandas-seitig als experimentell gefuehrt. Hier wird es
        # ausdruecklich gesetzt, damit die Bilanz an JEDEM Rueckgabepfad
        # steht und nicht nur an den zufaellig funktionierenden.
        rahmen.attrs = {**dict(getattr(df, "attrs", {}) or {}),
                        **dict(getattr(rahmen, "attrs", {}) or {}), **bilanz}
        return rahmen

    filtered = df[behalten].reset_index(drop=True)
    if filtered.empty:
        return _mit_bilanz(filtered)
    if sort_key and sort_key in filtered.columns:
        filtered = filtered.sort_values(
            [sort_key, "word"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
    if "rank" in filtered.columns:
        filtered = filtered.copy()
        filtered["rank"] = np.arange(1, len(filtered) + 1, dtype=np.int64)
    if sort_key:
        return _mit_bilanz(filtered)

    if "f" in filtered.columns:
        freq_filtered = filtered[filtered["f"].astype(np.int64) >= 2].reset_index(drop=True)
        if not freq_filtered.empty:
            filtered = freq_filtered
    # The default ranking is logDice, sorted by that column directly.
    #
    # Sorting by ``dice`` is not equivalent. The engine reports two logDice
    # values: ``logdice`` after Rychly 2008 from the corpus marginals and
    # ``logdice_window`` as a log transform of dice on Evert's distance
    # table. Only the second is monotonic in ``dice``, so a dice sort would
    # leave rows out of order while the payload reports sort_by=logdice.
    # This branch sees ``sort_by=None`` and must pick the column itself.
    #
    # chi2_cell bleibt ausgeschlossen: eine Einzelzellenstatistik ist kein
    # ausgewogenes Assoziationsmass.
    preferred = None
    for candidate in COLLOCATE_SORT_PREFERENCE:
        if candidate in filtered.columns:
            preferred = candidate
            break
    if preferred is not None:
        filtered = filtered.sort_values(
            [preferred, "word"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
    if "rank" in filtered.columns:
        filtered["rank"] = np.arange(1, len(filtered) + 1, dtype=np.int64)
    return _mit_bilanz(filtered)


def filter_collocate_frame_by_min_freq(df: Any, min_freq: int) -> Any:
    """Keep only collocates meeting a declared co-occurrence floor.

    The REST and background-job paths both use this after their respective
    candidate builders. Keeping it here prevents one path from claiming a
    reliability floor that the other one does not actually enforce.
    """
    if min_freq <= 0 or not isinstance(df, pd.DataFrame):
        return df
    if df.empty or "f" not in df.columns:
        return df
    kept = df[df["f"].astype("int64") >= int(min_freq)].reset_index(drop=True)
    if "rank" in kept.columns:
        kept = kept.copy()
        kept["rank"] = np.arange(1, len(kept) + 1, dtype=np.int64)
    return kept


def normalize_compare_collocate_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "word" not in df.columns:
        return df

    filtered = df[df["word"].map(is_analyst_token)].reset_index(drop=True)
    if filtered.empty:
        return filtered

    freq_cols = [col for col in ("freq_human", "freq_ai") if col in filtered.columns]
    if freq_cols:
        max_freq = filtered[freq_cols].max(axis=1)
        freq_filtered = filtered[max_freq.astype(np.float64) >= 2].reset_index(drop=True)
        if not freq_filtered.empty:
            filtered = freq_filtered

    if "log_ratio" in filtered.columns:
        filtered = filtered.reindex(
            filtered["log_ratio"].abs().sort_values(ascending=False, kind="mergesort").index
        ).reset_index(drop=True)

    return filtered


def normalize_word_sketch_tables(
    tables: dict[str, pd.DataFrame],
    term: str | None = None,
    *,
    top_rows: int = 8,
) -> dict[str, pd.DataFrame]:
    if not tables:
        return {}

    # str.lower like the node resolution, so ß and ss stay separate.
    term_norm = str(term or "").strip().lower()
    filtered_tables: list[tuple[str, pd.DataFrame]] = []

    def _is_word_sketch_token(value: Any) -> bool:
        text = str(value or "").strip()
        if not is_analyst_token(text):
            return False
        if text.startswith("@") or text.startswith("#"):
            return False
        return True

    for relation, df in tables.items():
        if relation in _WORD_SKETCH_BLOCKED_RELATIONS:
            continue
        if df is None or df.empty or "word" not in df.columns:
            continue

        work = df[df["word"].map(_is_word_sketch_token)].copy()
        if work.empty:
            continue

        if term_norm:
            non_self = work[work["word"].map(lambda value: str(value).lower() != term_norm)].reset_index(drop=True)
            if not non_self.empty:
                work = non_self

        # No frequency floor here: the callers apply ``min_freq`` (the route
        # with _word_sketch_rank_rows, the difference route and the copilot tool
        # with apply_word_sketch_min_freq, default 3, 0 disables it). A fixed
        # f >= 2 here would override min_freq 0 and 1.
        if work.empty:
            continue

        # Default ranking key: logDice first (corpus-size-comparable,
        # frequency-robust; Rychlý 2008), matching the collocations default and
        # Sketch Engine. The remaining significance/frequency keys are tiebreakers
        # when a source has no logDice column.
        sort_cols = [col for col in ("logdice", "ll", "t", "f", "chi2_cell") if col in work.columns]
        if sort_cols:
            work = work.sort_values(sort_cols, ascending=[False] * len(sort_cols), kind="mergesort").reset_index(drop=True)
        if top_rows > 0:
            work = work.head(int(top_rows)).reset_index(drop=True)
        if "frequency" not in work.columns and "f" in work.columns:
            work["frequency"] = pd.to_numeric(work["f"], errors="coerce").fillna(0).astype(np.int64)
        if "score" not in work.columns:
            # Surface logDice as the visible score (corpus-size-comparable;
            # Rychlý 2008) so the UI's score bar + sort use the recommended
            # default measure, with the remaining score keys as fallbacks.
            score_key = "logdice" if "logdice" in work.columns else (
                "chi2_cell" if "chi2_cell" in work.columns else (
                    next((col for col in ("ll", "t", "f") if col in work.columns), None)
                )
            )
            if score_key is not None:
                work["score"] = pd.to_numeric(work[score_key], errors="coerce").fillna(0.0).astype(float)
                work["score_key"] = score_key
        if "score_key" not in work.columns:
            work["score_key"] = "score"
        work["rank"] = np.arange(1, len(work) + 1, dtype=np.int64)
        filtered_tables.append((relation, work))

    filtered_tables.sort(
        key=lambda item: tuple(
            float(item[1].iloc[0][col]) if col in item[1].columns and not item[1].empty else float("-inf")
            for col in ("logdice", "ll", "t", "f", "chi2_cell")
        ),
        reverse=True,
    )
    return OrderedDict(filtered_tables)


def dispersion_family_measures(
    observed: "np.ndarray | list[int]",
    sizes: "np.ndarray | list[int]",
) -> dict[str, float | int]:
    """Compute the dispersion family over a per-part distribution.

    Thin wrapper over ``services.tools.dispersion_family.dispersion_family`` so
    callers in this module stay decoupled from the engine module's import graph
    (imported lazily). Returns ``{dp, dpnorm, juilland_d, carroll_d2, range,
    range_prop, vc}``.
    """
    from candyconc.services.tools.dispersion_family import dispersion_family

    return dispersion_family(observed, sizes)


def dispersion_referenzwerte(
    teilgroessen: Any, treffer: int
) -> dict[str, float]:
    """What a DP value means for THESE part sizes and THIS number of hits.

    Gries' DP cannot be interpreted without these three values, and on large
    corpora the fixed cut points in :data:`DISPERSION_SCHNITTPUNKTE` cannot
    either. Measured and confirmed analytically on a corpus of 250,535
    documents and 142,044,149 tokens, for a word with 12,226 hits::

        dp_min       0.7818   as proportional as whole hits allow
        dp_erwartet  0.8973   pure scatter proportional to document length
        dp_max       1.0000   all hits in the smallest part

    There the NULL DISTRIBUTION lies above the cut point 0.8 from which the
    label ``strongly_clustered`` is assigned. Practically every word gets
    it, and it no longer separates anything. Example: an observed DP of
    0.8885 against a null range of 0.8955 to 0.8979 lies BELOW chance, so the
    word is slightly more even than random, while the fixed cut point calls
    it strongly clustered.

    ``dp_erwartet`` is ANALYTICAL, not simulated: a reference that returns a
    different number on every call is useless as a reference. The marginal
    distributions are exact (binomial per part), only the dependence between
    parts is approximated. Checked against 200 Monte Carlo draws: 0.01 to
    0.02 percent deviation at realistic corpus sizes, up to 4 percent only
    with three to ten parts. Cost on 250,535 documents: 22 milliseconds.
    """

    groessen = np.asarray(teilgroessen, dtype=np.float64).ravel()
    n = int(treffer)
    if groessen.size <= 1 or n <= 0 or groessen.sum() <= 0:
        return {"dp_min": 0.0, "dp_erwartet": 0.0, "dp_max": 0.0}
    s = groessen / groessen.sum()

    # dp_min: Groesstrest-Verfahren, also so proportional wie ganze Treffer
    # es zulassen.
    ziel = n * s
    ganz = np.floor(ziel)
    rest = int(round(n - ganz.sum()))
    if rest > 0:
        ganz[np.argsort(-(ziel - ganz))[:rest]] += 1.0
    dp_min = 0.5 * float(np.abs(ganz / n - s).sum())

    # dp_erwartet: E|X_i - n*s_i| je Teil, X_i ~ Binomial(n, s_i).
    #
    # Zwei Regime, und das ist keine Optimierung. (1-s)^n unterlaeuft fuer
    # grosse n auf Null, die Rekursion liefert dann still 0. Ein Entwurf
    # dieser Funktion tat genau das und gab fuer zehn gleich grosse Teile
    # mit 100.000 Treffern dp_erwartet 0,0 aus. Die Zahl sah plausibel aus
    # und war falsch gerechnet.
    #
    # EXAKT binomial, nicht Poisson: Poisson unterstellt Varianz n*s,
    # richtig ist n*s*(1-s). Bei vielen winzigen Teilen faellt das nicht
    # auf, bei zehn gleich grossen schon (0,1251 gegen simulierte 0,1160).
    mad = np.empty_like(ziel)
    gross = ziel > 30.0
    mad[gross] = np.sqrt(2.0 * ziel[gross] * (1.0 - s[gross]) / np.pi)
    klein = ~gross
    if klein.any():
        sk = s[klein]
        lk = ziel[klein]
        kmax = int(max(8, np.ceil(lk.max() + 8.0 * np.sqrt(lk.max() + 1.0))))
        kmax = min(kmax, n)
        rest_w = np.maximum(1.0 - sk, np.finfo(np.float64).tiny)
        p = np.exp(n * np.log1p(-sk))
        akk = p * lk
        quot = sk / rest_w
        for k in range(1, kmax + 1):
            p = p * ((n - k + 1) / k) * quot
            akk += p * np.abs(k - lk)
        mad[klein] = akk
    dp_erwartet = 0.5 * float(mad.sum()) / n

    return {
        "dp_min": round(dp_min, 6),
        "dp_erwartet": round(dp_erwartet, 6),
        "dp_max": round(1.0 - float(s.min()), 6),
    }


def dispersion_lagesatz(metriken: Any) -> str:
    """Ein Satz, der DP gegen seine Referenz stellt, statt es zu behaupten.

    Steht hier und nicht in der Markdown-Schicht, weil er die Ausgabe von
    :func:`dispersion_referenzwerte` deutet und mit ihr zusammen geaendert
    werden muss. Leerer String, wenn die Referenz fehlt: dann gibt es
    nichts zu vergleichen, und ein Satz waere wieder eine Behauptung.
    """

    if not isinstance(metriken, dict):
        return ""
    try:
        beobachtet = float(metriken.get("dp"))
        erwartet = float(metriken.get("dp_erwartet"))
    except (TypeError, ValueError):
        return ""
    dp_min = metriken.get("dp_min")
    if not erwartet:
        return ""
    try:
        spanne = (
            lt(", erreichbare Spanne {low} bis 1", ", attainable range {low} to 1").format(
                low=f"{float(dp_min):.4f}"
            )
            if dp_min
            else ""
        )
    except (TypeError, ValueError):
        spanne = ""
    unter = beobachtet < erwartet
    return (
        lt(
            "Gemessen an der Verteilung, die reines Streuen proportional zur "
            "Dokumentlänge ergibt, ist der Wert ",
            "Measured against the distribution that pure scattering in "
            "proportion to document length produces, the value is ",
        )
        + (lt("NICHT erhöht", "NOT elevated") if unter else lt("erhöht", "elevated"))
        + lt(
            ": dp={observed} gegen einen erwarteten Wert von {expected}{span}.",
            ": dp={observed} against an expected value of {expected}{span}.",
        ).format(observed=f"{beobachtet:.4f}", expected=f"{erwartet:.4f}", span=spanne)
        + (lt(
            " Der Ausdruck streut damit eher gleichmäßiger als Zufall.",
            " The expression is therefore spread more evenly than chance.",
        ) if unter else "")
    )


def _doc_sizes_from_bounds(doc_bounds: np.ndarray, token_count: int) -> np.ndarray:
    """Token count per document from start-position boundaries.

    ``doc_bounds[i]`` is the START position of document ``i`` (the same
    convention used by ``_doc_bounds_for_index`` / ``boundaries.document``
    on the REST path). Document ``i`` spans ``[doc_bounds[i], doc_bounds[i+1])``
    and the last document ends at ``token_count``.
    """
    bounds = np.asarray(doc_bounds, dtype=np.int64)
    if bounds.size == 0:
        return np.zeros(0, dtype=np.int64)
    ends = np.empty_like(bounds)
    ends[:-1] = bounds[1:]
    ends[-1] = int(token_count)
    sizes = ends - bounds
    # Guard against malformed/negative spans (e.g. token_count < last bound).
    sizes[sizes < 0] = 0
    return sizes


def _document_dispersion(
    offsets_arr: np.ndarray,
    doc_bounds: np.ndarray,
    token_count: int,
    doc_mask: Any = None,
) -> dict[str, Any]:
    """Gries DP over real document boundaries (copilot path == REST spec).

    expected_i = doc_size_i / N (NOT 1/n); observed_i = hits in document i;
    F = total hits. Returns BOTH the raw Gries DP and DPnorm:

        dp      = 0.5 * sum_i |observed_i/F - doc_size_i/N|
        dpnorm  = dp / (1 - min_i(expected_i))

    This mirrors the corrected REST dispersion exactly (document basis,
    doc_size_i/N expected proportions, raw-vs-norm split).
    """
    bounds = np.asarray(doc_bounds, dtype=np.int64)
    n_docs = int(bounds.size)
    corpus_tokens = max(1, int(token_count))
    doc_sizes = _doc_sizes_from_bounds(bounds, corpus_tokens)
    # Drop offsets outside the corpus token range so an out-of-range position is
    # not mis-bucketed into the last document (matches the REST path filter at
    # server._dispersion_document_profile).
    offsets_arr = offsets_arr[(offsets_arr >= 0) & (offsets_arr < corpus_tokens)]
    # observed_i: assign each offset to its document via the same right-search
    # boundary lookup the REST/copilot doc mapping uses.
    doc_idx = np.searchsorted(bounds, offsets_arr, side="right") - 1
    valid = (doc_idx >= 0) & (doc_idx < n_docs)
    doc_idx = doc_idx[valid]
    observed = np.bincount(doc_idx, minlength=n_docs).astype(np.int64, copy=False)
    total_hits = int(observed.sum())

    expected = doc_sizes.astype(np.float64) / float(corpus_tokens)
    if total_hits > 0:
        observed_prop = observed.astype(np.float64) / float(total_hits)
        dp = 0.5 * float(np.sum(np.abs(observed_prop - expected)))
    else:
        dp = 0.0
    min_expected = float(expected.min()) if expected.size else 0.0
    denom = 1.0 - min_expected
    dpnorm = float(dp / denom) if denom > 0 else 0.0

    # A restriction of the document universe acts AFTER counting: observed
    # and doc_sizes are cut to the selected documents, and all measures
    # compute on them. Otherwise dispersion is measured against the wrong
    # population: a where()-restricted query with 262 hits would report
    # n_documents 2000 instead of 683, a coverage that does not exist.
    # The GLOBAL document ids of the selected set. Without them
    # ``peak_partition`` after the cut is an index into the cut set, while
    # without a mask it is a global document id. On a 56,000-token test
    # index, the same peak as two numbers::
    #
    #     und                              n_documents 2000  peak 1527
    #     where(split="test",[word="und"]) n_documents  683  peak  519
    #
    # Global document 519 is split=train and has ZERO hits of the query.
    # ``document_text(doc_id)`` always reads globally: looking up the peak
    # would land on an unrelated training document, and no field would name
    # the difference.
    global_ids = None
    if doc_mask is not None:
        auswahl = np.asarray(doc_mask).astype(bool)
        if auswahl.size >= observed.size:
            auswahl = auswahl[: observed.size]
            global_ids = np.nonzero(auswahl)[0]
            observed = observed[auswahl]
            doc_sizes = doc_sizes[auswahl]
            n_docs = int(observed.size)
            corpus_tokens = max(1, int(doc_sizes.sum()))
            total_hits = int(observed.sum())
            expected = doc_sizes.astype(float) / float(corpus_tokens)
            if total_hits:
                dp = 0.5 * float(
                    np.abs(observed.astype(float) / float(total_hits) - expected).sum()
                )
            else:
                dp = 0.0
            min_expected = float(expected.min()) if expected.size else 0.0
            denom = 1.0 - min_expected
            dpnorm = float(dp / denom) if denom > 0 else 0.0

    nonzero_docs = int(np.count_nonzero(observed))
    coverage_ratio = float(nonzero_docs) / float(n_docs) if n_docs else 0.0
    peak_doc = int(np.argmax(observed)) if total_hits else 0
    peak_share = float(observed[peak_doc]) / float(total_hits) if total_hits else 0.0

    # Dispersion family (Juilland's D, Carroll's D2, Range, VC) over the SAME
    # per-document distribution as DP. DP stays the default classification
    # driver; the family members are additive.
    family = dispersion_family_measures(observed, doc_sizes)
    # Ohne diese drei Zahlen ist dp nicht deutbar. Sie kommen aus DENSELBEN
    # doc_sizes wie dp selbst, also aus der Verteilung, gegen die dp
    # gerechnet wurde, und nicht aus einer Faustregel.
    referenz = dispersion_referenzwerte(doc_sizes, total_hits)

    return {
        "unit": "documents",
        "n_documents": n_docs,
        "observed": observed.astype(int).tolist(),
        "doc_sizes": doc_sizes.astype(int).tolist(),
        "dp": dp,
        "dpnorm": dpnorm,
        "dp_min": referenz["dp_min"],
        "dp_erwartet": referenz["dp_erwartet"],
        "dp_max": referenz["dp_max"],
        "juilland_d": float(family["juilland_d"]),
        "carroll_d2": float(family["carroll_d2"]),
        "range": int(family["range"]),
        "range_prop": float(family["range_prop"]),
        "vc": float(family["vc"]),
        "total_hits": total_hits,
        "nonzero_partitions": nonzero_docs,
        "coverage_ratio": coverage_ratio,
        # Immer die GLOBALE Dokument-ID, damit document_text(doc_id) sie
        # aufloesen kann. ``peak_partition_basis`` sagt, worauf sich der
        # lokale Index bezogen haette.
        "peak_partition": (
            int(global_ids[peak_doc])
            if global_ids is not None and 0 <= peak_doc < int(global_ids.size)
            else peak_doc
        ),
        "peak_partition_local": (
            peak_doc if global_ids is not None else None
        ),
        "peak_share": peak_share,
        "profile": _dispersion_profile_label(
            total_hits, dp, peak_share,
            dp_erwartet=referenz["dp_erwartet"],
            dp_min=referenz["dp_min"], dp_max=referenz["dp_max"]),
        # Das gemeinsame Etikett beider Naehte, aus derselben Funktion wie
        # die REST-Antwort. Ohne es sagte dieselbe DP an zwei Oberflaechen
        # zwei Verschiedenes.
        "classification": dispersion_classification(
            dp, total_hits=total_hits,
            dp_erwartet=referenz["dp_erwartet"],
            dp_min=referenz["dp_min"], dp_max=referenz["dp_max"]),
        # Traegt die Information, die frueher IM Etikett steckte: ein
        # einzelnes Dokument haelt die Haelfte aller Treffer. Als eigenes
        # Feld, nicht in ein DP-Wort gefaltet.
        "peak_dominated": bool(peak_share >= 0.5),
    }


#: The cut points of the DP ladder. ONE source for both seams.
#:
#: Two ladders with different bounds that share the word ``fairly_even``
#: contradict each other. Over the 100 most frequent words of a 56,000-token
#: test index, 100 of 100 got different labels from two such ladders, and in
#: the band DP 0.35 to 0.5 the statement reversed::
#:
#:     Term   DP       REST seam      copilot seam
#:     .      0.3735   fairly_even    moderately_clustered
#:     ,      0.3909   fairly_even    moderately_clustered
#:
#: Dispersion classification is exactly the criterion by which an expert
#: decides whether a frequency finding holds corpus-wide or is an artefact of
#: a few documents. Two answers to the same question are not a matter of
#: taste there.
DISPERSION_SCHNITTPUNKTE = (0.2, 0.5, 0.8)

#: If the reachable range (dp_max - dp_min) is narrower than this, there is
#: no distribution verdict: the measure cannot distinguish anything. Over the
#: documents of a 56,000-token test index: 0.0138 for one hit, 0.0308 for 15,
#: 0.0779 for 61, 0.5959 for 919.
DISPERSION_MIN_SPANNE = 0.05


def dispersion_classification(
    dp: float,
    *,
    total_hits: int | None = None,
    dp_erwartet: float | None = None,
    dp_min: float | None = None,
    dp_max: float | None = None,
) -> str:
    """Das gemeinsame Etikett einer Gries-DP, aus der LAGE zur Nullverteilung.

    ZWEITE LEITER derselben Groesse. Als am 2026-08-30 nur ``profile``
    auf die Referenzwerte umgestellt wurde, liefen die beiden Naehte
    auseinander: 93 von 100 haeufigsten Woertern bekamen gegenlaeufige
    Etiketten, "und" hiess beim Copiloten fairly_even und an der
    REST-Naht fairly_clustered. Ein Test aus einer frueheren Runde hat es
    gefangen. Beide Leitern muessen dieselbe Frage gleich beantworten.

    Die vier Woerter bleiben, damit REST-Verbraucher nicht brechen. Ohne
    Referenzwerte gelten weiter die festen Schnittpunkte.
    """

    wert = float(dp)
    if dp_min is not None and dp_max is not None:
        if float(dp_max) - float(dp_min) < DISPERSION_MIN_SPANNE:
            return "zu_wenig_treffer"
    if dp_erwartet:
        erwartet = float(dp_erwartet)
        if wert <= erwartet:
            # Nicht erhoeht. "even" bleibt dem Fall vorbehalten, in dem
            # der Wert die erreichbare Untergrenze nahezu erreicht.
            return "even" if wert <= erwartet * 0.75 else "fairly_even"
        obergrenze = float(dp_max) if dp_max else 1.0
        spanne = obergrenze - erwartet
        if spanne <= 0.0:
            return "fairly_even"
        return "clustered" if (wert - erwartet) / spanne >= 0.5 else "fairly_clustered"
    niedrig, mittel, hoch = DISPERSION_SCHNITTPUNKTE
    if wert < niedrig:
        return "even"
    if wert < mittel:
        return "fairly_even"
    if wert < hoch:
        return "fairly_clustered"
    return "clustered"


def _dispersion_profile_label(
    total_hits: int,
    dp: float,
    peak_share: float,
    *,
    dp_erwartet: float | None = None,
    dp_min: float | None = None,
    dp_max: float | None = None,
) -> str:
    """The label from the POSITION relative to the reference values, not from fixed bounds.

    The three words stay because prompts, claim rules and several tests use
    them. What changes is their ASSIGNMENT.

    The fixed cut points 0.2/0.5/0.8 are calibrated for a handful of
    partitions, not for document dispersion over thousands of short texts.
    Over the 100 most frequent words of a 56,000-token test index they give
    90 strongly_clustered, 10 moderately_clustered and ZERO fairly_even. 47
    of the 100 lie BELOW the expected value under random scatter, so they
    are spread more evenly than chance, and 44 of them would still be called
    "strongly clustered".

    The label itself follows dp_erwartet. A wrong label with two
    relativising texts next to it is costlier and weaker than a correct
    label.

    The hapax comes out right by itself: with one hit dp ~ dp_erwartet ~
    dp_max, so the value is NOT elevated, and "fairly_even" correctly says
    that a single hit is exactly what chance yields. Fixed cut points would
    call the same case "strongly clustered".

    Without reference values the old cut points remain. That is no silent
    fallback: the reference values come from the same function as dp, and
    whoever lacks them has no distribution to compare against.
    """
    if total_hits <= 0:
        return "absent"
    # NO VERDICT WHERE THE MEASURE HAS NO ROOM.
    #
    # A fixed minimum number of hits (ten) is the wrong criterion: the
    # positional fallback with five hits on five equally large windows has a
    # reachable range of 0.8, and a verdict is quite possible there.
    #
    # What matters is whether DP can vary at all. Over the documents of a
    # 56,000-token test index: range 0.0138 for one hit, 0.0308 for 15,
    # 0.0779 for 61, 0.5959 for 919. Below 0.05 every statement lies within
    # what rounding already swallows, and "Klimawandel" with ONE hit would be
    # called strongly clustered.
    #
    # The criterion is computed from the DATA, not from a convention, and it
    # applies only where the reference values exist: without them there is
    # no range to check against.
    if dp_min is not None and dp_max is not None:
        if float(dp_max) - float(dp_min) < DISPERSION_MIN_SPANNE:
            return "zu_wenig_treffer"
    if dp_erwartet is None or not dp_erwartet:
        niedrig, mittel, hoch = DISPERSION_SCHNITTPUNKTE
        if dp >= hoch or peak_share >= 0.5:
            return "strongly_clustered"
        if dp >= mittel:
            return "moderately_clustered"
        return "fairly_even"
    if dp <= float(dp_erwartet):
        return "fairly_even"
    obergrenze = float(dp_max) if dp_max else 1.0
    spanne = obergrenze - float(dp_erwartet)
    if spanne <= 0.0:
        return "fairly_even"
    anteil = (float(dp) - float(dp_erwartet)) / spanne
    if anteil >= 0.5 or peak_share >= 0.5:
        return "strongly_clustered"
    return "moderately_clustered"


def summarize_dispersion_offsets(
    offsets: Any,
    *,
    token_count: int | None = None,
    doc_mask: Any = None,
    doc_bounds: Any = None,
    partitions: int | None = None,
) -> dict[str, Any]:
    """Summarize term dispersion.

    Default unit = ``documents`` (same as the corrected REST path): when
    ``doc_bounds`` are available, the hit stream is partitioned over the REAL
    document boundaries and Gries DP is computed against per-document expected
    proportions ``doc_size_i / N``. The ``dp`` field is the RAW Gries DP and a
    separate ``dpnorm`` field carries ``DP / (1 - min_i expected_i)``.

    The legacy equal-width positional windows are retained ONLY as an explicit,
    distinctly named fallback (``positional_dp_windowed``) used when no document
    boundaries are supplied; that mode NEVER populates the ``dp`` field, so the
    copilot can never report a window-based number under the ``dp`` name.
    """
    offsets_arr = np.asarray(offsets, dtype=np.int64)
    offsets_arr = offsets_arr[offsets_arr >= 0]
    total_hits = int(offsets_arr.size)

    corpus_tokens = int(token_count or 0)
    if corpus_tokens <= 0:
        corpus_tokens = int(offsets_arr.max()) + 1 if total_hits else 1
    corpus_tokens = max(1, corpus_tokens)

    bounds = None if doc_bounds is None else np.asarray(doc_bounds, dtype=np.int64)
    if bounds is not None and bounds.size > 0:
        # DOCUMENT MODE (default unit): identical inputs/formula to REST spec.
        return _document_dispersion(
            offsets_arr, bounds, corpus_tokens, doc_mask=doc_mask)

    # POSITIONAL-WINDOW FALLBACK (no document boundaries available).
    # Distinctly named output; never shares the ``dp`` field with document DP.
    safe_partitions = max(1, int(partitions if partitions is not None else 10))
    counts_arr = np.zeros(safe_partitions, dtype=np.int64)
    if total_hits:
        scale = float(safe_partitions) / float(corpus_tokens)
        idxs = (offsets_arr * scale).astype(np.int64, copy=False)
        idxs = np.clip(idxs, 0, safe_partitions - 1)
        counts_arr = np.bincount(idxs, minlength=safe_partitions)

    counts = counts_arr.astype(int).tolist()
    nonzero_partitions = int(np.count_nonzero(counts_arr))
    coverage_ratio = float(nonzero_partitions) / float(safe_partitions)
    positional_dp = _positional_window_dp(counts)
    peak_partition = int(np.argmax(counts_arr)) if total_hits else 0
    peak_share = float(counts_arr[peak_partition]) / float(total_hits) if total_hits else 0.0

    return {
        "unit": "positional_windows",
        "partitions": counts,
        "positional_dp_windowed": positional_dp,
        "total_hits": total_hits,
        "nonzero_partitions": nonzero_partitions,
        "coverage_ratio": coverage_ratio,
        "peak_partition": peak_partition,
        "peak_share": peak_share,
        "profile": _dispersion_profile_label(total_hits, positional_dp, peak_share),
    }


def _positional_window_dp(counts: list[int]) -> float:
    """Equal-width-window DP for the positional fallback ONLY.

    Uniform expected = 1/n over n equal windows; reported under the distinct
    ``positional_dp_windowed`` name, NEVER as ``dp``. This is the legacy
    window-based number kept for backwards visibility, not the document DP.
    """
    total = sum(counts)
    n = len(counts)
    if total <= 0 or n <= 1:
        return 0.0
    expected = 1.0 / n
    sum_abs = sum(abs(float(count) / float(total) - expected) for count in counts)
    return float(0.5 * sum_abs)


# ---------------------------------------------------------------------------
# Sketch-difference scorer (Track FT-SKETCH-DIFF-DISTRIBUTION, engine part)
# ---------------------------------------------------------------------------
def _sketch_row_score(row: dict[str, Any]) -> float:
    """Canonical association score for a normalized word-sketch row.

    Prefers the explicit ``score`` column written by
    :func:`normalize_word_sketch_tables`; otherwise falls back to the signed
    log-likelihood, then the unsigned LL / chi2_cell, so a raw (un-normalized)
    sketch table still scores sensibly.
    """
    for key in ("score", "ll_signed", "ll", "chi2_cell", "t", "f"):
        if key in row and row[key] is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def _sketch_table_to_rows(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    if isinstance(df, pd.DataFrame):
        if df.empty:
            return []
        return df.to_dict("records")
    if isinstance(df, list):
        return [dict(r) for r in df]
    return []


def sketch_difference(
    sketch_a: dict[str, Any],
    sketch_b: dict[str, Any],
    *,
    term_a: str | None = None,
    term_b: str | None = None,
    top_n: int = 20,
) -> dict[str, Any]:
    """Contrast two word sketches relation-by-relation.

    Inputs are the relation -> table mappings returned by the word-sketch path
    (``server._word_sketch_for_query`` / ``tools.word_sketch.word_sketch``);
    each table is a DataFrame (or list of row dicts) with at least ``word`` and a
    ``score`` column. For each grammatical relation present in either sketch the
    collocates are aligned by surface word into three buckets:

    - ``common``: words in BOTH sketches, with ``score_a``, ``score_b`` and
      ``delta = score_a - score_b`` (positive => stronger for term A), sorted by
      ``|delta|`` descending.
    - ``only_a`` / ``only_b``: words exclusive to one sketch, each with its
      single ``score`` (sorted by score descending).

    Returns::

        {
          "term_a": <str|None>, "term_b": <str|None>,
          "relations": {
            "<relation>": {
              "common": [{word, score_a, score_b, delta}, ...],
              "only_a": [{word, score}, ...],
              "only_b": [{word, score}, ...],
            }, ...
          },
          "relations_compared": <int>,
        }

    ``top_n`` caps each bucket per relation (<=0 disables the cap). This is a
    pure transform — no engine access — so the route computes the two sketches
    and hands them here, and it is golden-testable in isolation.
    """
    relations = sorted(set(sketch_a or {}) | set(sketch_b or {}))
    cap = int(top_n) if top_n and int(top_n) > 0 else None
    out_relations: dict[str, Any] = {}

    for relation in relations:
        rows_a = _sketch_table_to_rows((sketch_a or {}).get(relation))
        rows_b = _sketch_table_to_rows((sketch_b or {}).get(relation))
        scores_a = {str(r.get("word")): _sketch_row_score(r) for r in rows_a if r.get("word") is not None}
        scores_b = {str(r.get("word")): _sketch_row_score(r) for r in rows_b if r.get("word") is not None}

        common_words = set(scores_a) & set(scores_b)
        common = [
            {
                "word": w,
                "score_a": scores_a[w],
                "score_b": scores_b[w],
                "delta": scores_a[w] - scores_b[w],
            }
            for w in common_words
        ]
        common.sort(key=lambda d: abs(float(d["delta"])), reverse=True)

        only_a = [{"word": w, "score": scores_a[w]} for w in set(scores_a) - common_words]
        only_a.sort(key=lambda d: float(d["score"]), reverse=True)
        only_b = [{"word": w, "score": scores_b[w]} for w in set(scores_b) - common_words]
        only_b.sort(key=lambda d: float(d["score"]), reverse=True)

        if cap is not None:
            common = common[:cap]
            only_a = only_a[:cap]
            only_b = only_b[:cap]

        if not (common or only_a or only_b):
            continue

        out_relations[relation] = {
            "common": common,
            "only_a": only_a,
            "only_b": only_b,
        }

    return {
        "term_a": term_a,
        "term_b": term_b,
        "relations": out_relations,
        "relations_compared": len(out_relations),
    }
