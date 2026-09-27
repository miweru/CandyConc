"""Keyness statistics utilities."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from numbers import Integral
from typing import Any, Dict

import numpy as np
import pandas as pd

from candyconc.core.counting_kernels import keyness_scores_fast
from candyconc.core.significance import (
    bh_fdr,
    conservative_log_ratio_arrays,
    ll_to_p,
    log_ratio_ci_arrays,
)
from candyconc.domain.query_parser import casefold_key
from candyconc.i18n import lt

# Use the fixed significance level for conservative log ratio (Evert
# 2022). A model must not tune alpha to obtain significance. Direct
# callers can supply another alpha to conservative_log_ratio_arrays.
from candyconc.analysis_defaults import KEYNESS_LRC_ALPHA as LRC_ALPHA  # noqa: E402

__all__ = [
    "compute_keyness",
    "compute_keyness_counts",
    "compute_keyness_external",
    "chi2_2x2_pooled",
    "expected_min_cell",
    "keyness_full_stats",
    "complement_docset_ids",
    "normalize_disjoint_docsets",
    "validate_external_reference",
    "DEFAULT_SORT_KEY",
    "DEFAULT_MIN_FREQ",
    "RELIABILITY_EXPECTED_MIN",
]

# Default ranking statistic: the most over-represented words by signed Dunning
# G^2 (log-likelihood) sit at the top of the list.
DEFAULT_SORT_KEY = "ll_signed"

# Die Spalten, nach denen ``compute_keyness_counts`` wirklich ordnen kann.
SORT_KEYS: frozenset[str] = frozenset({
    "ll_signed", "ll", "chi2", "chi2_signed", "chi2_cell", "chi2_cell_signed",
    "log_ratio", "lrc", "bic", "diff_per_million", "target_freq",
    "reference_freq", "target_per_million", "reference_per_million",
    "expected_min", "p_value", "q_value",
})


def validate_sort_key(sort_by: Any) -> str:
    """Unbekannter Sortierschluessel ist ein Fehler, kein stiller Ersatz.

    ``compute_keyness_counts`` faellt bei einem unbekannten Schluessel still
    auf ``ll_signed`` zurueck. Als Bibliotheks-Schutz ist das richtig, als
    Verhalten einer aufgerufenen Schnittstelle waere es die schlimmste Sorte
    Fehler: es wird nach einer Rangfolge gefragt, eine andere geliefert, und
    nichts sagt es. Der Unterschied entscheidet hier etwas, denn gekappt wird
    NACH dem Sortieren: wer nach ``lrc`` fragt und ``ll_signed`` bekommt,
    sieht die LRC-Spitze womoeglich gar nicht.
    """
    key = str(sort_by or "").strip() or DEFAULT_SORT_KEY
    if key not in SORT_KEYS:
        raise ValueError(lt(
            "sort_by={key} ist keine Spalte dieser Analyse. Erlaubt: {allowed}.",
            "sort_by={key} is not a column of this analysis. Allowed: {allowed}.",
        ).format(key=repr(key), allowed=", ".join(sorted(SORT_KEYS))))
    return key

# Release-grade reliability defaults (Track FT-KEYNESS-RESEARCH). Candidates
# whose combined target+reference frequency is below DEFAULT_MIN_FREQ are
# dropped BEFORE the inferential statistics so the BH-FDR test count ``m`` only
# reflects testable candidates (otherwise thousands of singletons inflate m and
# silently shrink every q-value). RELIABILITY_EXPECTED_MIN is the smallest 2x2
# expected cell count below which the chi-square/G^2 approximation is unreliable
# (the textbook E>=5 rule) — surfaced as the ``low_reliability`` flag, not a
# hard filter.
DEFAULT_MIN_FREQ = 5
RELIABILITY_EXPECTED_MIN = 5.0

_TARGET_DOCSET = lt("Ziel-Docset", "Target document set")
_REFERENCE_DOCSET = lt("Referenz-Docset", "Reference document set")


def _strict_nonnegative_count(value: Any, *, label: str) -> int:
    message = lt(
        "{label} muss eine nichtnegative ganze Zahl sein",
        "{label} must be a non-negative integer",
    ).format(label=label)
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(message)
    count = int(value)
    if count < 0:
        raise ValueError(message)
    return count


def _normalize_docset_ids(value: Any, *, label: str) -> np.ndarray:
    """Normalize internally stored document ids without unsigned wraparound."""
    raw = np.asarray(value)
    if raw.ndim != 1:
        raise ValueError(lt(
            "{label} muss eine eindimensionale Dokument-ID-Liste sein",
            "{label} must be a one-dimensional list of document IDs",
        ).format(label=label))
    ids: list[int] = []
    for raw_id in raw.tolist():
        invalid = lt(
            "{label} enthält keine gültige Dokument-ID",
            "{label} contains an invalid document ID",
        ).format(label=label)
        if isinstance(raw_id, (bool, np.bool_)) or not isinstance(raw_id, Integral):
            raise ValueError(invalid)
        doc_id = int(raw_id)
        if doc_id < 0 or doc_id > np.iinfo(np.uint32).max:
            raise ValueError(invalid)
        ids.append(doc_id)
    return np.unique(np.asarray(ids, dtype=np.uint32))


def normalize_disjoint_docsets(
    target_doc_ids: Any,
    reference_doc_ids: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Normalize a Keyness comparison and reject overlapping document populations."""
    target = _normalize_docset_ids(target_doc_ids, label=_TARGET_DOCSET)
    reference = _normalize_docset_ids(reference_doc_ids, label=_REFERENCE_DOCSET)
    overlap = np.intersect1d(target, reference, assume_unique=True)
    if overlap.size:
        raise ValueError(lt(
            "Ziel- und Referenz-Docset dürfen keine gemeinsamen Dokumente enthalten",
            "The target and reference document sets must not share documents",
        ))
    return target, reference


def complement_docset_ids(target_doc_ids: Any, *, doc_count: int) -> np.ndarray:
    """Return the document complement used by ``reference_source=whole``."""
    if doc_count < 1:
        raise ValueError(lt("Korpus enthält keine Dokumente", "The corpus contains no documents"))
    target = _normalize_docset_ids(target_doc_ids, label=_TARGET_DOCSET)
    if target.size and int(target[-1]) >= int(doc_count):
        raise ValueError(lt(
            "Docset enthält eine Dokument-ID außerhalb des Korpus",
            "The document set contains a document ID outside the corpus",
        ))
    return np.setdiff1d(
        np.arange(int(doc_count), dtype=np.uint32), target, assume_unique=True
    )


def validate_external_reference(
    reference_freq_list: Any,
    *,
    reference_total: Any,
    vocabulary_complete: Any,
    target_pos: str | None,
    reference_pos: Any,
) -> tuple[dict[str, int], int, str | None]:
    """Validate the explicit research contract for an external Keyness list.

    Missing words can be interpreted as true zero counts only when the caller
    attests that the supplied vocabulary is complete for the same POS universe.
    """
    if not isinstance(reference_freq_list, Mapping) or not reference_freq_list:
        raise ValueError(lt(
            "reference_freq_list muss eine nicht-leere Wort->Frequenz-Tabelle sein",
            "reference_freq_list must be a non-empty word->frequency table",
        ))
    if vocabulary_complete is not True:
        raise ValueError(lt(
            "Externe Keyness-Referenzen benötigen reference_vocabulary_complete=true",
            "External keyness references need reference_vocabulary_complete=true",
        ))
    total_invalid = lt(
        "reference_total muss eine positive ganze Zahl sein",
        "reference_total must be a positive integer",
    )
    if isinstance(reference_total, bool) or not isinstance(reference_total, Integral):
        raise ValueError(total_invalid)
    total = int(reference_total)
    if total <= 0:
        raise ValueError(total_invalid)

    normalized: dict[str, int] = {}
    for raw_word, raw_count in reference_freq_list.items():
        if not isinstance(raw_word, str):
            raise ValueError(lt(
                "reference_freq_list darf nur Text-Wörter enthalten",
                "reference_freq_list may only contain text words",
            ))
        word = casefold_key(raw_word.strip())
        if not word:
            raise ValueError(lt(
                "reference_freq_list darf keine leeren Wörter enthalten",
                "reference_freq_list must not contain empty words",
            ))
        count = _strict_nonnegative_count(
            raw_count,
            label=lt("Frequenz für {word}", "Frequency of {word}").format(word=repr(word)),
        )
        normalized[word] = normalized.get(word, 0) + count

    listed_total = int(sum(normalized.values()))
    if listed_total <= 0:
        raise ValueError(lt(
            "reference_freq_list muss mindestens eine positive Frequenz enthalten",
            "reference_freq_list must contain at least one positive frequency",
        ))
    if listed_total != total:
        raise ValueError(lt(
            "reference_total muss bei vollständiger Referenzliste exakt der Summe "
            "der Referenzfrequenzen entsprechen",
            "With a complete reference list, reference_total must equal the sum "
            "of the reference frequencies exactly",
        ))

    target_scope = str(target_pos or "").strip() or None
    reference_scope = str(reference_pos or "").strip() or None
    if target_scope != reference_scope:
        raise ValueError(lt(
            "POS-Filter und externe Referenz müssen dieselbe POS-Grundgesamtheit ausweisen",
            "The POS filter and the external reference must declare the same POS population",
        ))
    return normalized, total, reference_scope


def expected_min_cell(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
) -> np.ndarray:
    """Smallest 2x2 expected cell count E_min per word (pooled marginals).

    For each word with target count ``a`` and reference count ``c`` over totals
    ``N_t`` / ``N_r``, the pooled 2x2 expecteds are ``E_ij = row_i*col_j/N`` with
    ``N = N_t + N_r``. Returns ``min(E11, E12, E21, E22)`` — the quantity the
    E>=5 reliability rule is applied to. Degenerate ``N<=0`` yields all zeros.
    """
    a = np.asarray(counts_t, dtype=np.float64)
    c = np.asarray(counts_r, dtype=np.float64)
    n_t = float(int(total_t))
    n_r = float(int(total_r))
    n = n_t + n_r
    if n <= 0.0:
        return np.zeros(a.shape, dtype=np.float64)
    b = n_t - a
    d = n_r - c
    row1 = a + b
    row2 = c + d
    col1 = a + c
    col2 = b + d
    e11 = row1 * col1 / n
    e12 = row1 * col2 / n
    e21 = row2 * col1 / n
    e22 = row2 * col2 / n
    return np.minimum(np.minimum(e11, e12), np.minimum(e21, e22))


def chi2_2x2_pooled(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
    *,
    correction: bool = False,
) -> np.ndarray:
    """Full 2x2 Pearson chi-square statistic per word (all four cells).

    For each word the contingency table is::

        [[a,        N_t - a],
         [c,        N_r - c]]

    where ``a`` is the target count, ``c`` the reference count, ``N_t`` the
    target total and ``N_r`` the reference total. The statistic is the standard
    Pearson chi-square summed over **all four** cells against the pooled
    expectation ``E_ij = (row_i * col_j) / N`` with ``N = N_t + N_r``::

        chi2 = sum_ij (O_ij - E_ij)^2 / E_ij

    Unlike :func:`candyconc.core.counting_kernels.keyness_chi2_cell_pooled` (the
    single target-cell contribution exposed as ``chi2_cell``), this sums every
    cell and is asymptotically chi-square distributed with one degree of
    freedom — the proper test statistic for a 2x2 table.

    ``correction`` toggles the Yates continuity correction (subtract 0.5 from
    each ``|O - E|`` before squaring). It defaults to ``False`` to match the
    no-correction convention used by the log-likelihood (Dunning G^2) statistic
    and by ``scipy.stats.chi2_contingency(..., correction=False)``.

    The result is unsigned (>= 0); over- and under-represented words both score
    positive. Use ``chi2_signed`` for a directed value.
    """
    a = np.asarray(counts_t, dtype=np.float64)
    c = np.asarray(counts_r, dtype=np.float64)
    if a.shape != c.shape:
        raise ValueError("counts_t und counts_r müssen gleich lang sein")

    n_t = float(int(total_t))
    n_r = float(int(total_r))
    n = n_t + n_r
    out = np.zeros(a.shape, dtype=np.float64)
    if n <= 0.0:
        return out

    # 2x2 observed cells.
    b = n_t - a  # target, not-word
    d = n_r - c  # reference, not-word

    row1 = a + b  # == n_t
    row2 = c + d  # == n_r
    col1 = a + c  # word total across both corpora
    col2 = b + d  # not-word total across both corpora

    # Expected frequencies under independence (pooled marginals).
    e_a = row1 * col1 / n
    e_b = row1 * col2 / n
    e_c = row2 * col1 / n
    e_d = row2 * col2 / n

    # A row/column marginal of zero makes the corresponding expecteds zero and
    # the chi-square undefined; those words contribute nothing (statistic 0).
    valid = (col1 > 0.0) & (col2 > 0.0) & (row1 > 0.0) & (row2 > 0.0)
    if not np.any(valid):
        return out

    def _cell(observed: np.ndarray, expected: np.ndarray) -> np.ndarray:
        diff = np.abs(observed[valid] - expected[valid])
        if correction:
            diff = np.maximum(diff - 0.5, 0.0)
        return diff * diff / expected[valid]

    out[valid] = _cell(a, e_a) + _cell(b, e_b) + _cell(c, e_c) + _cell(d, e_d)
    return out


def keyness_full_stats(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
    *,
    ll: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Compute per-row inferential statistics for the full keyness candidate set.

    The synchronous ``compute_keyness_counts`` path and the background docset
    job share this function. Call it over the entire vocabulary union before
    ``safe_limit`` or top-N truncation. BH-FDR depends on the number of
    simultaneous tests ``m``, so truncating first would inflate significance.

    Parameters
    - ``counts_t`` / ``counts_r``: per-word target/reference raw frequencies.
    - ``total_t`` / ``total_r``: token counts for each corpus or docset.
    - ``ll``: optional aligned Dunning G^2 log-likelihood values. If omitted,
      recompute them with ``keyness_scores_fast`` to keep p-values consistent
      with the ranking score.

    Return aligned float64 arrays: ``log_ratio``, ``log_ratio_ci_low``,
    ``log_ratio_ci_high``, ``lrc``, ``p_value`` (chi-square sf on |G^2|,
    df=1) and ``q_value`` (BH-FDR over the full set). Use
    ``significance.log_ratio_ci_arrays``, ``ll_to_p`` and ``bh_fdr`` as in
    the scalar path.

    LRC uses the interval endpoint closest to zero, or 0 when the interval
    includes zero. It is defined on the target/reference token table used
    here. Pair-weighted collocation counts can count a token in several
    anchor windows and cannot be substituted into that token table.
    Bonferroni correction also uses ``n``, the full candidate count, before
    any row truncation.
    """
    a = np.asarray(counts_t, dtype=np.float64)
    c = np.asarray(counts_r, dtype=np.float64)
    n = int(a.size)
    if ll is None:
        _chi2_cell, ll = keyness_scores_fast(
            a.astype(np.uint64, copy=False),
            c.astype(np.uint64, copy=False),
            int(total_t),
            int(total_r),
        )
    ll = np.asarray(ll, dtype=np.float64)

    n_t = float(total_t)
    n_r = float(total_r)
    if total_t > 0 and total_r > 0 and n > 0:
        log_ratio, lr_low, lr_high = log_ratio_ci_arrays(a, c, n_t, n_r)
        lrc = conservative_log_ratio_arrays(
            a, c, n_t, n_r, alpha=LRC_ALPHA, vocab=n
        )
    else:
        log_ratio = np.zeros(n, dtype=np.float64)
        lr_low = np.zeros(n, dtype=np.float64)
        lr_high = np.zeros(n, dtype=np.float64)
        lrc = np.zeros(n, dtype=np.float64)

    # p from chi-square sf (df=1) on the unsigned G^2; q from BH-FDR over the
    # ENTIRE candidate set (this is why callers must not pre-truncate).
    p_value = np.asarray(ll_to_p(ll), dtype=np.float64) if n else np.zeros(0, dtype=np.float64)
    q_value = bh_fdr(p_value)

    return {
        "log_ratio": log_ratio.astype(np.float64, copy=False),
        "log_ratio_ci_low": lr_low.astype(np.float64, copy=False),
        "log_ratio_ci_high": lr_high.astype(np.float64, copy=False),
        "lrc": lrc.astype(np.float64, copy=False),
        "p_value": p_value.astype(np.float64, copy=False),
        "q_value": q_value.astype(np.float64, copy=False),
    }


def compute_keyness(
    target: list[str],
    reference: list[str],
    *,
    pos_map: dict[str, str] | None = None,
    pos: str | None = None,
    sort_by: str = DEFAULT_SORT_KEY,
    min_freq: int = 0,
) -> pd.DataFrame:
    """Return keyness scores for ``target`` vs ``reference``.

    The implemented single target-cell chi-square contribution is exposed as
    ``chi2_cell``. The full 2x2 Pearson chi-square is exposed separately as
    ``chi2``.

    ``min_freq`` drops candidates whose combined target+reference frequency is
    below the threshold before any inferential statistics (see
    :func:`compute_keyness_counts`).

    ``pos`` requires ``pos_map``: bare word lists carry no part of speech.
    Passing ``pos`` alone raises instead of returning unfiltered rows.
    """

    if pos and not pos_map:
        # OHNE Wortartenkarte gibt es zu blossen Wortlisten keine Wortart.
        # Vorher stand hier ``if pos and pos_map``, und ein ``pos`` ohne
        # Karte fiel STILL aus: das Ergebnis war byte-gleich zu dem ganz
        # ohne Filter, samt Artikeln und Verben, mit status success. Der
        # Aufrufer hat eine Wortartenauswahl verlangt und eine bekommen,
        # die keine ist.
        #
        #     compute_keyness(T, R, pos="NOUN", pos_map=KARTE)
        #         -> ['Hund', 'Katze']
        #     compute_keyness(T, R, pos="NOUN", pos_map=None)
        #         -> ['Hund', 'Katze', 'der', 'langsam', 'laufen', 'schnell']
        #     compute_keyness(T, R)
        #         -> dieselbe Liste
        #
        # Der Docset-Pfad braucht diese Karte nicht, er liest die Wortart
        # aus dem Index. Nur die Wortlisten-Variante ist auf sie
        # angewiesen, und genau sie hat geschwiegen.
        raise ValueError(lt(
            "pos ohne pos_map: zu blossen Wortlisten ist keine Wortart "
            "bekannt. Entweder pos_map mitgeben oder ueber Docsets "
            "vergleichen, wo die Wortart aus dem Index kommt.",
            "pos without pos_map: plain word lists carry no part of speech. "
            "Either pass pos_map or compare document sets, where the part of "
            "speech comes from the index.",
        ))
    if pos and pos_map:
        target = [t for t in target if pos_map.get(t, "").startswith(pos)]
        reference = [t for t in reference if pos_map.get(t, "").startswith(pos)]

    freq_t = Counter(target)
    freq_r = Counter(reference)
    total_t = len(target)
    total_r = len(reference)
    return compute_keyness_counts(
        freq_t, freq_r, total_t, total_r, sort_by=sort_by, min_freq=min_freq
    )


def compute_keyness_external(
    freq_t: dict[str, int],
    reference_freq_list: dict[str, int],
    total_t: int,
    reference_total: int | None = None,
    *,
    sort_by: str = DEFAULT_SORT_KEY,
    min_freq: int = DEFAULT_MIN_FREQ,
) -> pd.DataFrame:
    """Keyness of a target frequency map against an EXTERNAL reference list.

    This low-level helper receives a trusted complete reference map. The HTTP
    route must call :func:`validate_external_reference` first; it is the layer
    that requires an explicit complete-vocabulary declaration, exact total, and
    matching POS scope. The optional total remains for internal callers only.

    Words present in the target but absent from the reference list are scored
    with reference frequency 0 (over-represented); words only in the reference
    contribute to the candidate union as under-represented. The result is the
    identical DataFrame contract as :func:`compute_keyness_counts`.
    """
    ref_total = (
        int(reference_total)
        if reference_total is not None
        else int(sum(int(v) for v in reference_freq_list.values()))
    )
    return compute_keyness_counts(
        freq_t,
        reference_freq_list,
        int(total_t),
        ref_total,
        sort_by=sort_by,
        min_freq=min_freq,
    )


def compute_keyness_counts(
    freq_t: dict[str, int],
    freq_r: dict[str, int],
    total_t: int,
    total_r: int,
    *,
    sort_by: str = DEFAULT_SORT_KEY,
    min_freq: int = 0,
) -> pd.DataFrame:
    """Return directed keyness scores for count dictionaries.

    Three distinct chi-square-family statistics are exposed; do not conflate
    them:

    - ``ll`` (+ ``ll_signed``): Dunning's log-likelihood ratio, the full 2x2
      G^2 statistic ``2 * sum O * ln(O / E)``. Default ranking key.
    - ``chi2`` (+ ``chi2_signed``): the full 2x2 **Pearson** chi-square,
      ``sum_ij (O_ij - E_ij)^2 / E_ij`` over all four cells of the pooled
      contingency table ``[[a, N_t - a], [c, N_r - c]]`` (no Yates correction,
      matching the G^2 convention). Asymptotically chi-square with df=1.
    - ``chi2_cell`` (+ ``chi2_cell_signed``): the **single target-cell**
      Pearson contribution ``(O - E)^2 / E`` for the target word cell only —
      NOT a full test statistic.

    Other columns: ``direction``, ``diff_per_million``, ``log_ratio`` with a
    Katz delta-method (Katz et al. 1978) ``log_ratio_ci_low`` / ``log_ratio_ci_high``,
    ``bic``, ``p_value`` and BH-FDR ``q_value``.

    The ``_signed`` variants carry the over/under-representation sign (positive
    when the word is over-represented in the target corpus, negative otherwise).

    By default rows are sorted by ``ll_signed`` descending so the most
    over-represented (target-key) words appear first. ``sort_by`` overrides the
    sort column.

    ``min_freq`` (default 0 = off) drops every candidate whose combined
    target+reference frequency is below the threshold BEFORE the inferential
    statistics are computed. This matters for correctness, not just noise: the
    BH-FDR q-value of a row depends on the number of simultaneous tests ``m``,
    so keeping thousands of untestable singletons in the candidate set would
    inflate ``m`` and silently shrink every q-value. The surviving rows also
    carry a ``low_reliability`` boolean (smallest 2x2 expected cell count below
    :data:`RELIABILITY_EXPECTED_MIN`, the E>=5 rule) so unreliable chi-square
    rows can be flagged without being dropped.
    """
    if str(sort_by or "").strip().lower() in {"mi2", "mi2_signed"}:
        raise ValueError(lt(
            "Sortiermaß 'mi2' wurde durch 'chi2_cell' ersetzt.",
            "The sort measure 'mi2' was replaced by 'chi2_cell'.",
        ))

    words = sorted(set(freq_t) | set(freq_r))
    if not words:
        return pd.DataFrame([])

    counts_t = np.fromiter((int(freq_t.get(w, 0)) for w in words), dtype=np.uint64)
    counts_r = np.fromiter((int(freq_r.get(w, 0)) for w in words), dtype=np.uint64)

    # Reliability filter (Track FT-KEYNESS-RESEARCH): drop low-frequency
    # candidates BEFORE keyness_full_stats so BH-FDR ``m`` counts only testable
    # rows. Applied on the combined frequency a+c so a word that is rare in both
    # corpora is excluded, but one frequent in either survives.
    if min_freq and int(min_freq) > 0:
        keep = (counts_t.astype(np.int64) + counts_r.astype(np.int64)) >= int(min_freq)
        if not np.any(keep):
            return pd.DataFrame([])
        words = [w for w, k in zip(words, keep.tolist()) if k]
        counts_t = counts_t[keep]
        counts_r = counts_r[keep]

    chi2_cell, ll = keyness_scores_fast(counts_t, counts_r, total_t, total_r)
    # Full 2x2 Pearson chi-square (all four cells), no Yates correction to match
    # the G^2 / log-likelihood convention used above.
    chi2_full = chi2_2x2_pooled(counts_t, counts_r, total_t, total_r, correction=False)
    a = counts_t.astype(np.float64)
    c = counts_r.astype(np.float64)
    n_t = float(total_t)
    n_r = float(total_r)
    target_pm = (a / n_t * 1_000_000.0) if total_t > 0 else np.zeros_like(chi2_cell)
    reference_pm = (c / n_r * 1_000_000.0) if total_r > 0 else np.zeros_like(chi2_cell)
    diff_pm = target_pm - reference_pm
    signs = np.where(diff_pm >= 0.0, 1.0, -1.0)

    # Log Ratio (Hardie 2014) + Katz CI, p-value and BH-FDR q-value over the FULL
    # candidate set, via the shared helper (single source of truth with the
    # server.py docset-job keyness path). q-FDR is computed over every row here.
    full = keyness_full_stats(a, c, total_t, total_r, ll=ll)
    log_ratio = full["log_ratio"]
    lr_low = full["log_ratio_ci_low"]
    lr_high = full["log_ratio_ci_high"]
    lrc = full["lrc"]
    p_value = full["p_value"]
    q_value = full["q_value"]

    # BIC (Wilson): size-robust significance, G^2 - ln(N).
    n_total = n_t + n_r
    bic = ll - (np.log(n_total) if n_total > 0 else 0.0)

    # Reliability flag: smallest 2x2 expected cell count below the E>=5 rule.
    e_min = expected_min_cell(counts_t, counts_r, total_t, total_r)
    low_reliability = e_min < RELIABILITY_EXPECTED_MIN

    df = pd.DataFrame(
        {
            "word": words,
            "target_freq": counts_t.astype(np.int64),
            "reference_freq": counts_r.astype(np.int64),
            "target_per_million": target_pm,
            "reference_per_million": reference_pm,
            "diff_per_million": diff_pm,
            "direction": np.where(diff_pm >= 0.0, "target", "reference"),
            # Full 2x2 Pearson chi-square (proper test statistic, df=1).
            "chi2": chi2_full,
            "chi2_signed": chi2_full * signs,
            # Single target-cell Pearson contribution (NOT a full statistic).
            "chi2_cell": chi2_cell,
            "chi2_cell_signed": chi2_cell * signs,
            "ll": ll,
            "ll_signed": ll * signs,
            "log_ratio": log_ratio,
            "log_ratio_ci_low": lr_low,
            "log_ratio_ci_high": lr_high,
            "lrc": lrc,
            "bic": bic,
            "p_value": p_value,
            "q_value": q_value,
            # E_min and the E>=5 reliability flag (low_reliability=True means the
            # chi-square/G^2 approximation is unreliable for this row).
            "expected_min": e_min,
            "low_reliability": low_reliability,
        }
    )
    if sort_by not in df.columns:
        sort_by = DEFAULT_SORT_KEY
    df = df.sort_values(sort_by, ascending=False).reset_index(drop=True)
    return df


def schreibungen_anhaengen(
    zeilen: list,
    woerter,
    *args,
) -> None:
    """Haengt jeder Zeile an, welche Schreibung welchen Anteil traegt.

    ``args`` sind Tripel (ids, etiketten, aufschluesselung) je Seite, also
    Ziel und Referenz. Eine Zeile bekommt den Zusatz nur, wenn ihr Etikett
    NICHT die einzige tragende Schreibung ist. Genau dieser Fall ist der
    gemeldete: die Zeile "Beschlussempfehlung" weist 18.656 Treffer in den
    2010ern aus, und dort steht ausschliesslich die reformierte Schreibung.
    """
    import numpy as _np

    # ``woerter`` loest IDs zu Zeichenketten auf und kommt vom Aufrufer. Der
    # Helfer holt sich strings_for_ids NICHT selbst: die Werkzeugtests
    # ersetzen es am aufrufenden Modul, und ein eigener Import wuerde an
    # diesem Ersatz vorbeigreifen. Genau daran sind sechs Tests gefallen.
    seiten = ("target", "reference")
    je_etikett: Dict[str, Dict[str, Dict[str, int]]] = {}
    for name, (ids, etiketten, teile) in zip(seiten, args):
        if not teile:
            continue
        nach_rep = {int(i): str(w) for i, w in zip(ids, etiketten)}
        beteiligt = _np.fromiter(
            (t for g in teile.values() for t in g), dtype=_np.uint32
        )
        if beteiligt.size == 0:
            continue
        namen = dict(zip(beteiligt.tolist(), woerter(beteiligt)))
        for rep, gruppe in teile.items():
            etikett = nach_rep.get(int(rep))
            if etikett is None:
                continue
            je_etikett.setdefault(etikett, {})[name] = {
                str(namen[t]): int(c)
                for t, c in sorted(gruppe.items(), key=lambda kv: -kv[1])
                if t in namen
            }
    if not je_etikett:
        return
    for zeile in zeilen:
        etikett = str(zeile.get("word", ""))
        teile = je_etikett.get(etikett)
        if not teile:
            continue
        zeile["surface_variants"] = teile
        # Display the spelling that contributes the count. Keep the internal
        # representative ID independent of the docset, and retain every spelling
        # in the breakdown.
        gesamt: Dict[str, int] = {}
        for schreibungen in teile.values():
            for form, zahl in schreibungen.items():
                gesamt[form] = gesamt.get(form, 0) + int(zahl or 0)
        tragende = max(gesamt.items(), key=lambda kv: kv[1])[0] if gesamt else ""
        if tragende and tragende != etikett:
            zeile["word"] = tragende
