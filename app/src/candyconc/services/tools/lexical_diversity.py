"""Lexical-diversity metrics over the indexed token stream (Track F4).

Computes Type-Token Ratio (TTR), Standardised TTR (STTR), Guiraud's R and the
optional Moving-Average TTR (MATTR) directly from the Fast Index ``word_id``
stream (lexicon + token_store) — no new engine path, no re-tokenisation.

Why STTR/Guiraud matter here: raw TTR is confounded by text length (it falls
monotonically as N grows), so it is NOT comparable across corpora/subcorpora of
different size. STTR (mean TTR over fixed-size windows) and Guiraud's R are the
length-robust measures used by AntConc / WordSmith, which is why the Human-vs-AI
``per_side`` comparison reports them and warns when the two sides differ in size.

The headline product use-case (Human vs AI specialist) compares two docsets;
``lexical_diversity_per_side`` returns each side plus a ``size_warning`` when the
sides are length-imbalanced (so a reader never compares two raw TTRs that are not
on the same scale).
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from candyconc.core.fast_index_native import strings_for_ids


# AntConc / WordSmith STTR default window. Reported alongside every STTR value
# because STTR is only comparable across texts at the SAME window size.
DEFAULT_STTR_WINDOW = 1000
DEFAULT_MATTR_WINDOW = 500


def _is_analyst_token(text: str) -> bool:
    """A countable lexical type: non-empty, not a structural ``|marker|``, and
    carrying at least one alphanumeric character (excludes bare punctuation).

    Eine WEITERLEITUNG auf ``analysis_defaults.is_analyst_token``, nicht
    eine zweite Fassung derselben Regel. Hier stand bis heute eine
    wortgleiche Kopie, und zwei Kopien einer Filterpolitik sind genau die
    Naht, an der sie auseinanderlaufen. Dieses Projekt hat den Fall schon
    gehabt (siehe den Kommentar bei ``_kollokat_einheiten``). Der Import
    steht im Funktionskoerper, weil ``analysis_defaults`` pandas und
    polars zieht und dieses Modul sonst beim Import bezahlt, was es nur
    beim Zaehlen braucht.
    """
    from candyconc.analysis_defaults import is_analyst_token

    return is_analyst_token(text)


def _analyst_token_mask(idx: Any) -> np.ndarray:
    """Boolean mask over word-id space: True where the id is an analyst token.

    Index 0 is reserved/never-a-token; the mask is sized ``vocab_size + 1`` so a
    raw ``word_id`` can be used as a direct lookup.
    """
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
    vocab_size = int(lex.vocab_size)
    mask = np.zeros(vocab_size + 1, dtype=bool)
    if vocab_size <= 0:
        return mask
    ids = np.arange(1, vocab_size + 1, dtype=np.uint32)
    strings = strings_for_ids(lex.offsets, lex.strings_view, ids, True)
    for wid, text in zip(ids, strings):
        if _is_analyst_token(text):
            mask[int(wid)] = True
    return mask


def _word_id_stream(idx: Any, doc_ids: Sequence[int] | None) -> np.ndarray:
    """Concatenated ``word_id`` stream for the whole corpus or a docset.

    For a docset the per-document ranges are walked in id order and joined; the
    stream is the running token sequence (order preserved within each document),
    which is what STTR / MATTR sliding windows require.
    """
    store = idx.fast_index.token_store
    if doc_ids is None:
        token_count = int(store.token_count)
        if token_count <= 0:
            return np.zeros(0, dtype=np.int64)
        return store.get_word_ids_range(0, token_count).astype(np.int64, copy=False)

    starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    if starts.size == 0:
        return np.zeros(0, dtype=np.int64)
    segments: list[np.ndarray] = []
    for start, end in zip(starts.astype(np.int64), ends.astype(np.int64)):
        if end <= start:
            continue
        segments.append(store.get_word_ids_range(int(start), int(end)).astype(np.int64, copy=False))
    if not segments:
        return np.zeros(0, dtype=np.int64)
    return np.concatenate(segments)


def _sttr(stream: np.ndarray, window: int) -> tuple[float | None, int]:
    """Mean TTR over consecutive non-overlapping windows of ``window`` tokens.

    Returns ``(sttr, n_windows)``. A final short remainder window is dropped
    (AntConc/WordSmith convention) so every averaged window has equal size; if
    the stream is shorter than one window, STTR is undefined (``None``).
    """
    n = int(stream.size)
    if window <= 0 or n < window:
        return None, 0
    n_windows = n // window
    ratios = np.empty(n_windows, dtype=np.float64)
    for w in range(n_windows):
        chunk = stream[w * window : (w + 1) * window]
        types = int(np.unique(chunk).size)
        ratios[w] = types / float(window)
    return float(ratios.mean()), n_windows


def _mattr(stream: np.ndarray, window: int) -> float | None:
    """Moving-Average TTR: mean TTR over every sliding window of ``window``.

    Undefined (``None``) when the stream is shorter than one window.
    """
    n = int(stream.size)
    if window <= 0 or n < window:
        return None

    # Maintain type counts while the window slides. Re-running ``np.unique``
    # for every position is O(N*window) and made an otherwise routine MATTR
    # request unnecessarily expensive on large corpora.
    counts: dict[int, int] = {}
    distinct = 0
    for token in stream[:window]:
        key = int(token)
        previous = counts.get(key, 0)
        counts[key] = previous + 1
        if previous == 0:
            distinct += 1

    n_positions = n - window + 1
    total_distinct = distinct
    for right in range(window, n):
        outgoing = int(stream[right - window])
        remaining = counts[outgoing] - 1
        if remaining == 0:
            del counts[outgoing]
            distinct -= 1
        else:
            counts[outgoing] = remaining

        incoming = int(stream[right])
        previous = counts.get(incoming, 0)
        counts[incoming] = previous + 1
        if previous == 0:
            distinct += 1
        total_distinct += distinct

    return float(total_distinct / (n_positions * window))


def compute_lexical_diversity(
    idx: Any,
    *,
    doc_ids: Sequence[int] | None = None,
    sttr_window: int = DEFAULT_STTR_WINDOW,
    include_mattr: bool = False,
    mattr_window: int = DEFAULT_MATTR_WINDOW,
    analyst_tokens_only: bool = True,
) -> dict[str, Any]:
    """Lexical-diversity metrics for the corpus or a docset.

    Args:
        idx: a ``CorpusIndex``.
        doc_ids: restrict to these document ids (None = whole corpus).
        sttr_window: STTR/STTR window size in tokens (reported as ``sttr_window``).
        include_mattr: also compute MATTR (O(N*window), opt-in).
        mattr_window: MATTR window size in tokens.
        analyst_tokens_only: drop empty / pure-punctuation / ``|marker|`` tokens
            from the running stream before counting (default True). The boolean
            and ``analyst_token_policy`` make the basis explicit.

    Returns a dict with ``ttr, sttr, sttr_window, guiraud, mattr?, mattr_window?,
    n_tokens, n_types`` plus token-policy diagnostics. STTR/MATTR are ``None``
    when the stream is shorter than the window.
    """
    sttr_window = max(1, int(sttr_window))
    stream = _word_id_stream(idx, doc_ids)

    if analyst_tokens_only and stream.size:
        mask = _analyst_token_mask(idx)
        # Guard against any out-of-range id (truncated lexicon) before masking.
        in_range = (stream >= 0) & (stream < mask.size)
        stream = stream[in_range]
        if stream.size:
            stream = stream[mask[stream]]

    n_tokens = int(stream.size)
    n_types = int(np.unique(stream).size) if n_tokens else 0

    ttr = (n_types / n_tokens) if n_tokens else 0.0
    guiraud = (n_types / math.sqrt(n_tokens)) if n_tokens else 0.0
    sttr, n_windows = _sttr(stream, sttr_window)

    # FT id 1: disclose the RAW corpus token total alongside the analyst-token
    # ``n_tokens`` so TTR is anchored against the corpus size the user sees
    # elsewhere (e.g. /corpora token_count = 56191) — ``n_tokens`` only counts
    # analyst tokens (punctuation/markers excluded), which otherwise looks like
    # an unexplained, lower denominator. Degrades to None if unavailable.
    try:
        corpus_raw_token_count: int | None = int(idx.fast_index.token_store.token_count)
    except Exception:
        corpus_raw_token_count = None

    result: dict[str, Any] = {
        "ttr": float(ttr),
        "sttr": sttr,
        "sttr_window": int(sttr_window),
        "sttr_n_windows": int(n_windows),
        "guiraud": float(guiraud),
        "n_tokens": n_tokens,
        "n_types": n_types,
        "corpus_raw_token_count": corpus_raw_token_count,
        "analyst_tokens_only": bool(analyst_tokens_only),
        "analyst_token_policy": (
            "exclude_empty_pure_punctuation_and_index_markers"
            if analyst_tokens_only
            else "all_indexed_tokens"
        ),
    }
    if include_mattr:
        mattr_window = max(1, int(mattr_window))
        result["mattr"] = _mattr(stream, mattr_window)
        result["mattr_window"] = int(mattr_window)
    return result


def lexical_diversity_per_side(
    idx: Any,
    *,
    target_doc_ids: Sequence[int] | None,
    reference_doc_ids: Sequence[int] | None,
    sttr_window: int = DEFAULT_STTR_WINDOW,
    include_mattr: bool = False,
    mattr_window: int = DEFAULT_MATTR_WINDOW,
    analyst_tokens_only: bool = True,
    target_label: str = "target",
    reference_label: str = "reference",
) -> dict[str, Any]:
    """Two-sided diversity comparison (the Human-vs-AI headline use-case).

    Returns ``{per_side: {target, reference}, size_warning?}``. ``size_warning``
    is emitted when the two sides differ in length enough that raw TTR is not
    comparable (only STTR/MATTR should then be read across sides).
    """
    target = compute_lexical_diversity(
        idx,
        doc_ids=target_doc_ids,
        sttr_window=sttr_window,
        include_mattr=include_mattr,
        mattr_window=mattr_window,
        analyst_tokens_only=analyst_tokens_only,
    )
    reference = compute_lexical_diversity(
        idx,
        doc_ids=reference_doc_ids,
        sttr_window=sttr_window,
        include_mattr=include_mattr,
        mattr_window=mattr_window,
        analyst_tokens_only=analyst_tokens_only,
    )
    out: dict[str, Any] = {
        "per_side": {target_label: target, reference_label: reference},
        "sttr_window": int(max(1, int(sttr_window))),
    }
    n_t = int(target["n_tokens"])
    n_r = int(reference["n_tokens"])
    larger = max(n_t, n_r)
    smaller = min(n_t, n_r)
    # >20% length imbalance: raw TTR is length-confounded -> warn, steer to STTR.
    if larger > 0 and smaller / larger < 0.8:
        out["size_warning"] = (
            "Die Seiten unterscheiden sich in der Tokenzahl "
            f"({target_label}={n_t}, {reference_label}={n_r}); rohe TTR ist "
            "längen-konfundiert und NICHT direkt vergleichbar. Bitte STTR/MATTR "
            "für den Seitenvergleich verwenden."
        )
    return out
