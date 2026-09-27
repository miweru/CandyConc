"""Pure analysis computation helpers shared by backend callers.

Keep association scoring, dispersion, n-gram counting and collocate-frame
calculation independent of server and route imports. Server-owned job
runners resolve their configuration, caches and test overrides at call time."""

import logging
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np

from candyconc.core.corpus_index import CorpusIndex
from candyconc.i18n import lt
from candyconc.analysis_defaults import is_analyst_token, normalize_default_collocate_frame
from candyconc.domain.query_parser import (
    casefold_key,
    extract_simple_cql_token,
    simple_cql_literal,
)

from .doc_meta import _doc_count_for_index

logger = logging.getLogger(__name__)


def _g2_2x2(obs: float, f1: float, f2: float, n: float) -> float:
    """Full 2x2 Dunning log-likelihood G^2 for a co-occurrence cell.

    ``obs`` = O11 (joint count), ``f1`` = node marginal, ``f2`` = collocate
    marginal, ``n`` = corpus total. Returns ``2 * sum O_ij * ln(O_ij / E_ij)``
    over all four cells, each term 0 when its observed cell is <= 0 (this also
    absorbs degenerate tables where the window count exceeds a marginal). The
    result is >= 0, unlike the single-cell ``2*O*ln(O/E)`` approximation.
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


def _gries_dp(counts: list[int]) -> float:
    """Raw Gries Deviation of Proportions over EQUAL-WEIGHT parts.

    This is the legacy positional-window variant where every part is expected
    to hold an equal share (1/n) of the hits. It returns the *raw* DP

        DP = 0.5 * sum_i | observed_i / F - 1/n |

    where F is the total frequency. Note: this is the un-normalized value;
    the normalized variant (DPnorm) divides by (1 - min_i expected_i) = (1 - 1/n).
    Use :func:`_gries_dp_documents` for the document-boundary based measure that
    backs the dispersion endpoint default.
    """
    total = sum(counts)
    n = len(counts)
    if total <= 0 or n <= 1:
        return 0.0
    expected = 1.0 / n
    sum_abs = 0.0
    for count in counts:
        proportion = float(count) / float(total)
        sum_abs += abs(proportion - expected)
    return float(0.5 * sum_abs)


def _gries_dp_documents(
    counts: "np.ndarray | list[int]",
    doc_sizes: "np.ndarray | list[int]",
) -> dict[str, float]:
    """Gries Deviation of Proportions over real DOCUMENT boundaries.

    For each document i the expected proportion is ``doc_size_i / N`` (its share
    of all tokens N), NOT ``1/n``. With ``observed_i`` the hit count in document i
    and ``F = sum_i observed_i`` the total word frequency:

        dp     = 0.5 * sum_i | observed_i / F - doc_size_i / N |
        dpnorm = dp / (1 - min_i(expected_i))

    Returns a dict with ``dp`` (raw Gries DP, range ~[0,1], 0=even 1=clustered)
    and ``dpnorm`` (normalized to the achievable maximum).
    """
    obs = np.asarray(counts, dtype=np.float64).ravel()
    sizes = np.asarray(doc_sizes, dtype=np.float64).ravel()
    if obs.size == 0 or sizes.size == 0 or obs.size != sizes.size:
        return {"dp": 0.0, "dpnorm": 0.0, "dp_min": 0.0,
                "dp_erwartet": 0.0, "dp_max": 0.0}
    total_freq = float(obs.sum())
    total_tokens = float(sizes.sum())
    if total_freq <= 0.0 or total_tokens <= 0.0 or obs.size <= 1:
        return {"dp": 0.0, "dpnorm": 0.0, "dp_min": 0.0,
                "dp_erwartet": 0.0, "dp_max": 0.0}
    expected = sizes / total_tokens
    observed = obs / total_freq
    dp = 0.5 * float(np.abs(observed - expected).sum())
    min_expected = float(expected.min())
    denom = 1.0 - min_expected
    dpnorm = float(dp / denom) if denom > 0.0 else 0.0
    # Dieselben Referenzwerte wie auf der Copilot-Naht, aus derselben
    # Funktion. Zwei Oberflaechen, die dieselbe DP verschieden deuten,
    # sind in diesem Projekt eine eigene Fehlerklasse.
    from candyconc.analysis_defaults import dispersion_referenzwerte

    referenz = dispersion_referenzwerte(sizes, int(total_freq))
    return {"dp": dp, "dpnorm": dpnorm, **referenz}


def _ngram_counts(
    idx: CorpusIndex,
    doc_ids: np.ndarray | None,
    min_n: int,
    max_n: int,
) -> dict[tuple[int, ...], int]:
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(
            lt("Word Lexikon fehlt. Bitte Index neu bauen.", "Word lexicon is missing. Rebuild the index.")
        )
    token_store = idx.fast_index.token_store
    if doc_ids is None:
        doc_count = _doc_count_for_index(idx)
        doc_ids = np.arange(doc_count, dtype=np.uint32)
    starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    from candyconc.core.counting_kernels import count_ngrams_svb_fast

    return count_ngrams_svb_fast(token_store, starts, ends, min_n, max_n)


#: Number of documents one section counts.
#:
#: The value decides how long the GIL is held IN ONE STRETCH, not how long
#: the whole job takes. Measured on a corpus of 142 million tokens and
#: 250,535 documents, bigrams:
#:
#:      200 documents ->  0.06 s
#:    1,000 documents ->  0.30 s
#:    5,000 documents ->  1.76 s
#:   20,000 documents -> 10.43 s
#:
#: At 20,000, /health still timed out in thirteen of fourteen probes: one
#: section alone held the GIL longer than the time limit of the UI. 500 gives
#: about 0.15 s per stop, shorter than any span a user notices.
NGRAM_ABSCHNITT_DOKUMENTE = 500


def ngram_abschnitte(doc_ids: np.ndarray | None, idx: CorpusIndex) -> list[np.ndarray]:
    """Split the document set into sections so that the GIL comes back.

    Without sections a SINGLE bigram job on a corpus of 142 million tokens
    and 250,535 documents makes the backend unreachable for its whole
    duration. /health answers in 1.1 ms when idle and timed out in fourteen
    of fourteen probes during the job. The UI then shows "not ready" and
    drops the connection.

    Cause: ``count_ngrams_svb`` (_fast_count.pyx:1100) builds a Python dict
    and fills it in four nested loops. Filling a Python dict REQUIRES the
    GIL. The other kernels of the same file release it (``with nogil``,
    lines 347, 650, 822), this one is the exception.

    Hence neither ``asyncio.to_thread`` nor the bounded heavy-load pool
    helps: there is nothing to distribute when one thread does not release
    the GIL. The limit is NOT concurrency but the duration of ONE call.

    The sections do not change the result: n-grams are counted within
    document boundaries anyway, so a document always lies entirely in one
    section. Between two sections control returns to Python and the event
    loop gets its turn.
    """
    if doc_ids is None:
        doc_ids = np.arange(_doc_count_for_index(idx), dtype=np.uint32)
    ids = np.asarray(doc_ids, dtype=np.uint32)
    if ids.size <= NGRAM_ABSCHNITT_DOKUMENTE:
        return [ids]
    anzahl = int(np.ceil(ids.size / NGRAM_ABSCHNITT_DOKUMENTE))
    return [a for a in np.array_split(ids, anzahl) if a.size]


def _ngram_populations(
    idx: CorpusIndex,
    doc_ids: np.ndarray | None,
    min_n: int,
    max_n: int,
) -> dict[int, int]:
    """Wie viele n-Gramm-Positionen die Dokumentmenge je Ordnung traegt.

    Die Bezugsgroesse einer n-Gramm-Rate ist NICHT die Tokenzahl. Ein
    Dokument der Laenge L traegt ``L - n + 1`` Positionen der Ordnung n, und
    ein Dokument kuerzer als n traegt keine. ``_ngram_counts`` zaehlt bereits
    innerhalb der Dokumentgrenzen, die Zaehlung war also richtig und nur der
    Nenner falsch.

    On a 56,000-token test index: 54,191 bigram positions against 56,191
    tokens, so a token denominator is 3.69 percent too large, for trigrams
    7.66 and for five-grams 16.60 percent. The error grows with n
    AND with the share of short documents. In a contrast between document
    sets of different length it is therefore ASYMMETRIC and shifts the
    difference, not just both rates together.
    """
    if doc_ids is None:
        doc_ids = np.arange(_doc_count_for_index(idx), dtype=np.uint32)
    starts, ends, _ = idx._doc_ranges_for_ids(doc_ids)
    laengen = np.asarray(ends, dtype=np.int64) - np.asarray(starts, dtype=np.int64)
    return {
        n: int(np.maximum(laengen - (n - 1), 0).sum())
        for n in range(int(min_n), int(max_n) + 1)
    }


def _ngram_vereinigung(
    t_counts: dict[tuple[int, ...], int],
    r_counts: dict[tuple[int, ...], int],
) -> Iterator[tuple[tuple[int, ...], int, int]]:
    """Every n-gram type of both counts exactly once, with both frequencies.

    Used by both contrast seams (``server._run_ngrams_diff_job`` and
    ``tool_wrappers.ngram_contrast_tool``). It needs no union set, which
    would be another table over all types, built only to be traversed once
    before each type is looked up in both counts. For bigrams and trigrams
    of 231,263 against 19,272 documents such a union has over 53 million
    types. The order of the types changes no result: both seams sort by a
    key that contains the token id tuple and is therefore unique.
    """
    for key, f_t in t_counts.items():
        yield key, f_t, r_counts.get(key, 0)
    for key, f_r in r_counts.items():
        if key not in t_counts:
            yield key, 0, f_r


def _analysetoken_pruefer(lex: Any) -> Callable[[tuple[int, ...]], bool]:
    """Prüft, ob jedes Token eines n-Gramms ein Analyse-Token ist.

    Die Entscheidung fällt je Token-ID einmal. Vorher las jede Naht für jeden
    Typ jedes Token neu aus dem Lexikon und prüfte es neu, ein Wort wie
    "die" also so oft, wie es in verschiedenen n-Gramm-Typen steht, mit
    immer derselben Antwort. Der Zwischenspeicher des Lexikons fasst 65.536
    Zeichenketten, bei mehr Typen wird ein Teil der Zugriffe erneut
    dekodiert. Die Entscheidung hängt allein an der ID, der Filter und die
    Zahl der Kandidaten bleiben gleich.
    """
    entschieden: dict[Any, bool] = {}

    def alle_analysetoken(key: tuple[int, ...]) -> bool:
        for wid in key:
            gilt = entschieden.get(wid)
            if gilt is None:
                wort = lex.get_string(int(wid)) if lex else ""
                gilt = entschieden[wid] = is_analyst_token(wort)
            if not gilt:
                return False
        return True

    return alle_analysetoken


def _extract_simple_cql_token(term: str) -> str | None:
    """Keep the server facade on the shared CQL-literal parser."""
    return extract_simple_cql_token(term)


def _normalize_collocate_frame(
    df: Any,
    term: str,
    collocate_terms: list[str] | None,
    sort_by: str | None,
) -> Any:
    if df is None or df.empty:
        return df
    term_str = (term or "").strip()
    collocate_terms = collocate_terms or []
    if "word" in df.columns:
        if term_str:
            if term_str.lower().startswith("cql:"):
                literal = simple_cql_literal(term_str)
                if literal:
                    simple, case_insensitive = literal
                    if case_insensitive:
                        key = casefold_key(simple)
                        df = df[~df["word"].map(lambda word: casefold_key(str(word)) == key)]
                    else:
                        df = df[df["word"] != simple]
            else:
                term_key = casefold_key(term_str)
                df = df[~df["word"].map(lambda word: casefold_key(str(word)) == term_key)]
        if collocate_terms:
            collocate_keys = {casefold_key(value) for value in collocate_terms}
            df = df[~df["word"].map(lambda word: casefold_key(str(word)) in collocate_keys)]
    if "t_score" in df.columns:
        df = df.rename(columns={"t_score": "t"})
    if "log_likelihood" in df.columns:
        df = df.rename(columns={"log_likelihood": "ll"})
    if "observed" in df.columns:
        df = df.assign(f=df["observed"].astype(np.int64, copy=False))
    keep = [
        c
        for c in [
            "word", "f", "f2", "observed", "expected", "mi", "mi3", "lmi", "npmi", "z", "chi2_cell", "t", "ll",
            "dice", "logdice", "logdice_window", "log_ratio", "lrc",
            "delta_p_nc", "delta_p_cn",
            "rank",
        ]
        if c in df.columns
    ]
    df = df[keep]
    sort_key = (sort_by or "").strip().lower()
    if sort_key == "mi2":
        raise ValueError(
            lt("Sortiermaß 'mi2' wurde durch 'chi2_cell' ersetzt.", "Sort measure 'mi2' has been replaced by 'chi2_cell'.")
        )
    if (
        sort_key
        in {"mi", "mi3", "lmi", "npmi", "z", "chi2_cell", "t", "ll", "dice",
            "logdice", "logdice_window", "log_ratio", "lrc",
            "delta_p_nc", "delta_p_cn", "f"}
        and sort_key in df.columns
    ):
        df = df.sort_values(
            [sort_key, "word"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
        df["rank"] = np.arange(1, len(df) + 1, dtype=np.int64)
    return normalize_default_collocate_frame(df, sort_by)


@dataclass(frozen=True)
class _CollocateSegments:
    seg_starts: np.ndarray
    seg_ends: np.ndarray
    seg_weights: np.ndarray
    match_count: int
    context_mass: int


def _collocate_segments_for_anchors(
    engine: Any,
    anchors: np.ndarray,
    spans: np.ndarray,
    *,
    window: int,
    within_sentence: bool,
    clip_to_document: bool = False,
    pair_semantics: bool = False,
) -> _CollocateSegments:
    from candyconc.core.coverage_sweep import coverage_sweep_arrays, total_context_mass_arrays

    if anchors.size == 0 or engine.token_store is None:
        empty = np.zeros(0, dtype=np.uint32)
        return _CollocateSegments(
            seg_starts=empty,
            seg_ends=empty,
            seg_weights=empty,
            match_count=0,
            context_mass=0,
        )

    anchors_i64 = anchors.astype(np.int64, copy=False)
    spans_i64 = spans.astype(np.int64, copy=False) if spans.size else np.ones_like(anchors_i64)
    total_tokens = int(engine.token_store.token_count)
    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors=anchors_i64,
        spans=spans_i64,
        window_left=int(window),
        window_right=int(window),
        boundaries=engine.boundaries if (within_sentence or clip_to_document) else None,
        within_sentence=within_sentence,
        total_tokens=total_tokens,
        pair_semantics=pair_semantics,
    )
    u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
    return _CollocateSegments(
        seg_starts=seg_starts,
        seg_ends=seg_ends,
        seg_weights=seg_weights,
        match_count=int(anchors.size),
        context_mass=int(u),
    )


def _selbst_ids_aus_ankern(token_store, anchors, attr: str = "word") -> set[int]:
    """Return word IDs present in the matched anchor positions.

CQL queries supply positions rather than a single term. Reading the node
IDs from those positions excludes the node itself for plain words,
sequences and patterns, including case variants."""

    if token_store is None or anchors is None or len(anchors) == 0:
        return set()
    hole = (
        token_store.get_lemma_id if attr == "lemma"
        else token_store.get_word_id
    )
    try:
        heraus = set()
        for pos in anchors:
            wid = int(hole(int(pos)))
            if wid > 0:
                heraus.add(wid)
        return heraus
    except Exception:
        # Ein fehlender Zugriff darf die Analyse nicht abbrechen. Dann
        # bleibt es beim alten Verhalten, und der Paritaetstest schlaegt
        # an, statt dass still etwas Falsches ausgeliefert wird.
        return set()


def _collocate_stats_from_positions(
    idx: CorpusIndex,
    positions: np.ndarray,
    spans: np.ndarray,
    *,
    window: int,
    within_sentence: bool,
    sort_by: str | None,
    doc_ids: np.ndarray | None,
    min_count: int | None = None,
) -> Any:
    from candyconc.analysis_defaults import adaptive_collocate_min_freq
    from candyconc.core.collocation_engine import get_engine
    from candyconc.core.coverage_sweep import coverage_sweep_arrays, total_context_mass_arrays
    from candyconc.core.counting_kernels import count_collocates
    from candyconc.core.fast_index_native import docset_mask_from_ids
    import pandas as pd

    # Use the same adaptive floor as tools.collocate_stats. The anchor count
    # is the node frequency, and df.attrs records the applied calibration.
    try:
        requested_min_count = int(min_count) if min_count is not None else None
    except (TypeError, ValueError):
        requested_min_count = None
    if requested_min_count is not None and requested_min_count <= 0:
        requested_min_count = None
    node_frequency = int(positions.size)
    effective_min_count = adaptive_collocate_min_freq(
        node_frequency, requested_min_count
    )

    def _with_floor_attrs(frame: "pd.DataFrame") -> "pd.DataFrame":
        frame.attrs["node_frequency"] = node_frequency
        frame.attrs["effective_min_count"] = int(effective_min_count)
        frame.attrs["min_count_mode"] = (
            "requested" if requested_min_count else "adaptive"
        )
        return frame

    if positions.size == 0:
        return _with_floor_attrs(pd.DataFrame())
    engine = get_engine(idx.fast_index.index_path)
    engine.load()
    lex = engine._get_lexicon("word")
    if engine.token_store is None:
        return _with_floor_attrs(pd.DataFrame())

    anchors = positions.astype(np.int64, copy=False)
    spans_i64 = spans.astype(np.int64, copy=False) if spans.size else np.ones_like(anchors, dtype=np.int64)
    seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
        anchors=anchors,
        spans=spans_i64,
        window_left=int(window),
        window_right=int(window),
        # ALWAYS pass document boundaries (mirrors the engine collocate_stats
        # fix): otherwise the REST cql collocation path bled collocates across
        # document edges when within_sentence=False and no docset was set.
        boundaries=engine.boundaries,
        within_sentence=within_sentence,
        total_tokens=int(engine.token_store.token_count),
    )
    u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
    counts = count_collocates(
        engine.token_store,
        seg_starts,
        seg_ends,
        seg_weights,
        stoplist=None,
        attr="word",
        top_n=None,
    )
    # Ein Wort ist kein Kollokat von sich selbst.
    _selbst = _selbst_ids_aus_ankern(engine.token_store, anchors, "word")
    if _selbst:
        counts = {w: c for w, c in counts.items() if int(w) not in _selbst}
    if u <= 0:
        return _with_floor_attrs(pd.DataFrame())
    # Apply the shared adaptive floor before ranking. It ranges from 5 for
    # frequent nodes to 2 for rare nodes. Explicit requests take precedence,
    # with a minimum of 2 to exclude co-occurrence hapaxes.
    if effective_min_count > 1 and counts:
        counts = {tid: c for tid, c in counts.items() if c >= effective_min_count}
        if not counts:
            return _with_floor_attrs(pd.DataFrame())
    freqs_override = None
    freqs_override_arr = None
    total_tokens_override = None
    if doc_ids is not None:
        try:
            doc_bounds = (
                engine.boundaries.document._positions
                if engine.boundaries and engine.boundaries.document
                else None
            )
            if doc_bounds is None or doc_bounds.size <= 0:
                raise RuntimeError(
                    lt(
                        "Dokumentgrenzen fehlen für docset-lokale Kollokationsfrequenzen.",
                        "Document boundaries are missing for collocation frequencies local to the document set.",
                    )
                )
            ids = np.asarray(doc_ids, dtype=np.uint32)
            docset_mask = docset_mask_from_ids(ids, int(doc_bounds.size))
            freqs_override_arr, total_tokens_override = engine._docset_word_counts_dense(
                docset_mask, attr="word"
            )
        except Exception as exc:
            logger.exception(
                "Docset-Frequenzen konnten nicht berechnet werden; "
                "Kollokationen brechen fail-closed ab."
            )
            raise RuntimeError(
                lt(
                    "Docset-Frequenzen konnten nicht berechnet werden. "
                    "Kollokationswerte werden nicht mit globalen Korpusfrequenzen "
                    "als scheinbar docset-lokale Evidenz ausgegeben.",
                    "Document set frequencies could not be computed. "
                    "Collocation values are not reported with global corpus frequencies "
                    "as if they were evidence local to the document set.",
                )
            ) from exc
    arrays = engine._calculate_statistics_arrays(
        counts,
        int(anchors.size),
        int(u),
        lex,
        freqs_override=freqs_override,
        freqs_override_arr=freqs_override_arr,
        total_tokens_override=total_tokens_override,
    )
    if arrays[0].size == 0:
        return _with_floor_attrs(pd.DataFrame())
    sorted_arrays = engine._sort_statistics_arrays(*arrays, top_n=None)
    # node_frequency ist PFLICHT: logdice nach Rychly hat f(u) im Nenner.
    # Diese Stelle liess es weg, der Vorgabewert 0 kuerzte f(u) heraus, und
    # die REST-Antwort trug einen stillen, zu hohen logDice: fuer Knoten
    # "die" mit Kollokat "und" 12,8045 statt 11,45. Kein Test schlug an,
    # weil jede andere Spalte stimmte.
    df = engine._statistics_frame_from_sorted(
        *sorted_arrays, lex=lex, node_frequency=int(anchors.size),
        context_mass=float(u),
        scope_tokens=float(total_tokens_override or engine.lexicons.total_tokens),
        freqs_override=freqs_override,
        freqs_override_arr=freqs_override_arr)
    if df.empty:
        return _with_floor_attrs(df)
    # Re-attach the disclosure AFTER normalisation: pandas ops inside the
    # normalizer may rebuild the frame and drop ``attrs``.
    return _with_floor_attrs(_normalize_collocate_frame(df, "", None, sort_by))


def _per_million(freq: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (float(freq) * 1_000_000.0) / float(total)


def _keyness_signed_direction(
    counts_t: np.ndarray,
    counts_r: np.ndarray,
    total_t: int,
    total_r: int,
) -> np.ndarray:
    """Per-term sign (+1/-1) for keyness scores.

    +1 when the term is over-represented in the target (target relative
    frequency >= reference relative frequency), -1 otherwise. This matches the
    ``direction``/``diff_per_million`` convention used when emitting rows and
    lets us order keyness results by *signed* log-likelihood.
    """
    t = np.asarray(counts_t, dtype=np.float64).ravel()
    r = np.asarray(counts_r, dtype=np.float64).ravel()
    tt = float(total_t) if total_t else 0.0
    tr = float(total_r) if total_r else 0.0
    target_pm = (t / tt * 1_000_000.0) if tt > 0.0 else np.zeros_like(t)
    reference_pm = (r / tr * 1_000_000.0) if tr > 0.0 else np.zeros_like(r)
    diff = target_pm - reference_pm
    return np.where(diff >= 0.0, 1.0, -1.0)
