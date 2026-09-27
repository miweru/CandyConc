"""
High-Performance Collocation Engine.

Main integration module that provides a unified API for:
- Fast collocation calculation over entire corpus (no sampling)
- Proper statistical measures (MI, chi-square cell contribution, T-score, Log-Likelihood-like scores, Dice)
- Boundary-aware window clipping

Contrast architecture (one kernel, documented shims, two scoring tails)
=======================================================================

Single-docset stats
    :meth:`CollocationEngine.collocate_stats` — full-corpus (or docset-masked)
    collocation statistics via ``_calculate_statistics_arrays`` (the ONE live
    vectorised stats path; pinned by
    ``tests/core/test_collocation_engine_selected_scores.py``).

Contrast kernel
    :meth:`CollocationEngine.compare_by_docset_masks`: pairing-free contrast
    over two boolean doc masks. Scores the ``chi2_cell`` contribution per side
    against the GLOBAL corpus
    baseline and derives ``log_ratio`` from context-mass-normalised
    frequencies. This is the human versus AI copilot tail. Its output is
    golden-pinned by ``tests/core/test_compare_human_ai_golden.py``.

Documented shim
    :meth:`CollocationEngine.compare_human_ai`: thin rename shim
    (``target``/``reference`` -> ``human``/``ai``) over the kernel,
    byte-identical to the historical human versus AI specialist view.

The second scoring tail (server diff path)
    ``candyconc.services.backend.server._collocates_diff_rows_for_term``
    (feeding ``/analysis/collocates_diff/job`` and ``/analysis/contrast``)
    shares this module's counting substrate —
    :meth:`CollocationEngine.split_anchor_positions_by_doc_masks`,
    ``_docset_word_counts_dense``, ``_calculate_selected_score_array`` and the
    :class:`CollocationDiffBasis` cache — but keeps a SEPARATE scoring tail on
    purpose. Its semantics genuinely differ from the kernel and must not be
    silently unified (both tails are golden-pinned):

    - PER-DOCSET baseline (expected = side context mass x side docset
      frequency / side docset token total) vs the kernel's GLOBAL corpus
      baseline;
    - explicit CQL match spans and per-anchor context clipping vs the kernel's
      single-token node resolution;
    - CQL multi-token anchors (spans) vs single-token terms;
    - one selected score per side (default dice) + per-million columns,
      sorted by |diff_per_million| — vs fixed chi2_cell pair + log_ratio sorted by
      |log_ratio|. See ``tests/backend/test_collocates_diff_golden.py``.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import numpy as np
import pandas as pd

from .token_store import TokenStore
from .lexicon import LexiconSet, Lexicon
from .boundaries import BoundarySet
from .coverage_sweep import (
    coverage_sweep_arrays,
    total_context_mass_arrays,
)
from .counting_kernels import (
    count_collocates,
    count_hashmap_svb_dense,
    filter_positions_by_docset_fast,
    gather_u64_to_f64_fast,
    map_positions_to_doc_ids_fast,
)
from .collocation_cache import CollocationCache
from .pairing import is_anchor, is_version
from .index_signature import (
    INDEX_SIG_ARTIFACTS as _ENGINE_SIG_ARTIFACTS,  # noqa: F401  re-export for tests
    index_artifact_signature as _index_artifact_signature,
)


LOGGER = logging.getLogger(__name__)


def _contingency_cells(
    observed: np.ndarray,
    row_total: float,
    column_total: np.ndarray,
    event_total: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build a valid 2x2 table in the distance-based co-occurrence event space.

Use Evert (2004), Fig. 2.13: the row marginal is the window union |W(u)|,
the column marginal is the plain collocate frequency f(v), and the
population is |T|. Pair weighting adds a window multiplier to the column
marginal. Although it cancels in the expected frequency, it changes
log-likelihood, chi-squared, Dice and delta-P."""
    o11 = np.asarray(observed, dtype=np.float64)
    r1 = float(row_total)
    c1 = np.asarray(column_total, dtype=np.float64)
    n = float(event_total)
    o12 = r1 - o11
    o21 = c1 - o11
    o22 = n - r1 - c1 + o11
    cells = (o11, o12, o21, o22)
    minimum = min(float(np.min(cell)) if cell.size else 0.0 for cell in cells)
    if n <= 0.0 or minimum < -1e-9:
        raise ValueError(
            "Ungültige Kollokationskontingenz: Ereignisraum und Randhäufigkeiten passen nicht zusammen."
        )
    # Only erase floating-point dust after validation. A real negative cell is
    # a scientific error, not a value to repair silently.
    return tuple(np.maximum(cell, 0.0) for cell in cells)  # type: ignore[return-value]


def _g2_loglikelihood(
    observed: np.ndarray,
    row_total: float,
    column_total: np.ndarray,
    event_total: float,
) -> np.ndarray:
    """Full vectorised Dunning G² over valid event-space marginals."""
    obs = np.asarray(observed, dtype=np.float64)
    if event_total <= 0.0:
        return np.zeros_like(obs)
    o11, o12, o21, o22 = _contingency_cells(
        obs, row_total, column_total, event_total
    )
    r1 = float(row_total)
    c1 = np.asarray(column_total, dtype=np.float64)
    n = float(event_total)

    e11 = r1 * c1 / n
    e12 = r1 * (n - c1) / n
    e21 = (n - r1) * c1 / n
    e22 = (n - r1) * (n - c1) / n

    def _term(o: np.ndarray, e: np.ndarray) -> np.ndarray:
        valid = (o > 0.0) & (e > 0.0)
        return np.where(valid, o * np.log(np.divide(o, e, out=np.ones_like(o), where=valid)), 0.0)

    g2 = 2.0 * (_term(o11, e11) + _term(o12, e12) + _term(o21, e21) + _term(o22, e22))
    return np.maximum(g2, 0.0)


def _delta_p_arrays(
    observed: np.ndarray,
    row_total: float,
    column_total: np.ndarray,
    event_total: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Directional delta-P values from the same valid 2x2 event space."""
    if event_total <= 0.0:
        empty = np.zeros_like(np.asarray(observed, dtype=np.float64))
        return empty, empty
    o11, o12, o21, _o22 = _contingency_cells(
        observed, row_total, column_total, event_total
    )
    r1 = float(row_total)
    c1 = np.asarray(column_total, dtype=np.float64)
    n = float(event_total)
    p_c_given_r = np.divide(o11, r1, out=np.zeros_like(o11), where=r1 > 0.0)
    p_c_given_not_r = np.divide(
        o21, n - r1, out=np.zeros_like(o11), where=(n - r1) > 0.0
    )
    p_r_given_c = np.divide(o11, c1, out=np.zeros_like(o11), where=c1 > 0.0)
    p_r_given_not_c = np.divide(
        o12, n - c1, out=np.zeros_like(o11), where=(n - c1) > 0.0
    )
    return (
        np.clip(p_c_given_r - p_c_given_not_r, -1.0, 1.0),
        np.clip(p_r_given_c - p_r_given_not_c, -1.0, 1.0),
    )


def _empty_stats_arrays() -> Tuple[np.ndarray, ...]:
    """Empty return for ``_calculate_statistics_arrays`` (word_ids + 13 stats)."""
    return (
        np.array([], dtype=np.uint32),
        np.array([], dtype=np.float64),  # observed
        np.array([], dtype=np.float64),  # expected
        np.array([], dtype=np.float64),  # mi
        np.array([], dtype=np.float64),  # lmi
        np.array([], dtype=np.float64),  # npmi
        np.array([], dtype=np.float64),  # z
        np.array([], dtype=np.float64),  # chi2_cell
        np.array([], dtype=np.float64),  # t_score
        np.array([], dtype=np.float64),  # log_likelihood
        np.array([], dtype=np.float64),  # dice
        np.array([], dtype=np.float64),  # delta_p_nc
        np.array([], dtype=np.float64),  # delta_p_cn
        np.array([], dtype=np.float64),  # mi3
    )


@dataclass
class CollocationDiffBasis:
    word_ids: np.ndarray
    target_observed: np.ndarray
    reference_observed: np.ndarray
    target_freqs: np.ndarray
    reference_freqs: np.ndarray
    target_match_count: int
    reference_match_count: int
    target_context_mass: int
    reference_context_mass: int
    target_token_total: int
    reference_token_total: int


class CollocationEngine:
    """
    High-performance collocation engine following whitepaper principles.
    
    Features:
    - Full corpus coverage (no sampling) for scientific accuracy
    - Coverage-sweep algorithm for efficient overlap handling
    - Multiple counting kernels with cost-based selection
    - Proper statistical association measures
    """
    
    def __init__(self, fast_index_path: Path):
        """
        Initialize engine with pre-built fast index.
        
        fast_index_path: Directory containing binary index files
        """
        self.index_path = Path(fast_index_path)
        self.token_store: Optional[TokenStore] = None
        self.lexicons: Optional[LexiconSet] = None
        self.boundaries: Optional[BoundarySet] = None
        self._doc_bounds: Optional[np.ndarray] = None
        self._doc_types: Optional[np.ndarray] = None
        self._loaded = False
        self._very_frequent_ratio = 0.005
        self._very_frequent_min = 1_000_000
        self._lock = threading.RLock()
        self._docset_dense_stats_cache: OrderedDict[str, tuple[np.ndarray, int]] = OrderedDict()
        self._docset_dense_stats_cache_max = 6
        self._docset_dense_stats_cache_bytes = 0
        self._docset_dense_stats_cache_max_bytes = 256 * 1024 * 1024
        self._diff_basis_cache: OrderedDict[str, CollocationDiffBasis] = OrderedDict()
        self._diff_basis_cache_max = 12
        # Lazily-built casefold -> [lexicon ids] maps (one per attr). These let
        # term resolution mirror ``CorpusIndex.term_positions(case_insensitive=True)``
        # by unioning every lexicon type whose casefold matches the query.
        self._casefold_index: Dict[str, Dict[str, Tuple[int, ...]]] = {}

    def load(self) -> None:
        """Load all index structures."""
        with self._lock:
            if self._loaded:
                return

            LOGGER.info("Loading fast collocation index from %s", self.index_path)

            self.token_store = TokenStore(self.index_path)
            self.token_store.load()

            self.lexicons = LexiconSet(self.index_path)
            self.lexicons.load()

            self.boundaries = BoundarySet(self.index_path)
            self.boundaries.load()
            self._build_doc_type_cache()

            self._loaded = True
            LOGGER.info("Loaded %d tokens, %d word types",
                       self.token_store.token_count,
                       self.lexicons.word.vocab_size if self.lexicons.word else 0)

    def _cache_get(self, cache: OrderedDict, key: str):
        with self._lock:
            value = cache.get(key)
            if value is None:
                return None
            cache.move_to_end(key)
            return value

    def _cache_set(self, cache: OrderedDict, key: str, value: object, limit: int) -> None:
        with self._lock:
            cache[key] = value
            cache.move_to_end(key)
            while len(cache) > limit:
                cache.popitem(last=False)

    @staticmethod
    def _docset_signature(docset_mask: np.ndarray) -> str | None:
        """Stable content hash of a docset's *membership* for cache keying.

        Hashes the sorted document-id array (``np.flatnonzero`` is already sorted),
        plus the member count and total mask length, so the key changes whenever
        membership changes and never collides between a true subset and its
        complement that happen to share a member count. Returns ``None`` if the mask
        can't be reduced to a stable byte buffer (caller then skips caching). The
        per-engine cache is already corpus-scoped (one engine == one index) and the
        dense cache prefixes ``attr:``, so this signature only needs to disambiguate
        docsets within a single (engine, attr).
        """
        try:
            mask = np.asarray(docset_mask)
            doc_ids = np.flatnonzero(mask).astype(np.int64, copy=False)
            digest = hashlib.blake2b(doc_ids.tobytes(), digest_size=16)
            digest.update(int(doc_ids.size).to_bytes(8, "little"))
            digest.update(int(mask.size).to_bytes(8, "little"))
            return digest.hexdigest()
        except Exception:
            return None

    def _dense_cache_get(self, key: str) -> tuple[np.ndarray, int] | None:
        with self._lock:
            value = self._docset_dense_stats_cache.get(key)
            if value is None:
                return None
            self._docset_dense_stats_cache.move_to_end(key)
            return value

    def _dense_cache_set(self, key: str, value: tuple[np.ndarray, int]) -> None:
        counts, _total_tokens = value
        entry_bytes = int(getattr(counts, "nbytes", 0))
        with self._lock:
            existing = self._docset_dense_stats_cache.pop(key, None)
            if existing is not None:
                self._docset_dense_stats_cache_bytes -= int(getattr(existing[0], "nbytes", 0))
            self._docset_dense_stats_cache[key] = value
            self._docset_dense_stats_cache.move_to_end(key)
            self._docset_dense_stats_cache_bytes += entry_bytes
            while len(self._docset_dense_stats_cache) > self._docset_dense_stats_cache_max:
                _old_key, old_value = self._docset_dense_stats_cache.popitem(last=False)
                self._docset_dense_stats_cache_bytes -= int(getattr(old_value[0], "nbytes", 0))
            while (
                self._docset_dense_stats_cache
                and self._docset_dense_stats_cache_bytes > self._docset_dense_stats_cache_max_bytes
            ):
                _old_key, old_value = self._docset_dense_stats_cache.popitem(last=False)
                self._docset_dense_stats_cache_bytes -= int(getattr(old_value[0], "nbytes", 0))

    def get_diff_basis(self, key: str) -> Optional[CollocationDiffBasis]:
        return self._cache_get(self._diff_basis_cache, key)

    def set_diff_basis(self, key: str, basis: CollocationDiffBasis) -> None:
        self._cache_set(self._diff_basis_cache, key, basis, self._diff_basis_cache_max)

    def _freqs_for_word_ids(
        self,
        word_ids: np.ndarray,
        lexicon: Lexicon,
        *,
        freqs_override: Dict[int, int] | None = None,
        freqs_override_arr: np.ndarray | None = None,
    ) -> np.ndarray:
        if freqs_override_arr is not None:
            return gather_u64_to_f64_fast(freqs_override_arr, word_ids)
        if freqs_override is None:
            return lexicon.get_freqs_for_ids(word_ids).astype(np.float64, copy=False)
        return np.fromiter(
            (float(freqs_override.get(int(tid), 0)) for tid in word_ids),
            dtype=np.float64,
        )

    def _build_doc_type_cache(self) -> None:
        if not self.boundaries or not self.boundaries.document:
            self._doc_bounds = None
            self._doc_types = None
            return
        doc_bounds = self.boundaries.document._positions
        self._doc_bounds = doc_bounds
        doc_types = np.full(len(doc_bounds), -1, dtype=np.int8)
        for doc_idx, meta in self.boundaries._doc_metadata.items():
            if doc_idx < 0 or doc_idx >= len(doc_types):
                continue
            t = meta.get("text_type")
            if is_anchor(t):
                doc_types[doc_idx] = 0
            elif is_version(t):
                doc_types[doc_idx] = 1
        self._doc_types = doc_types
                   
    def _get_lexicon(self, attr: str) -> Lexicon:
        if not self.lexicons:
            raise RuntimeError("Lexika fehlen. Bitte Index neu bauen.")
        if attr == "word":
            lex = self.lexicons.word
        elif attr == "lemma":
            lex = self.lexicons.lemma
        else:
            raise ValueError("attr muss word oder lemma sein")
        if not lex:
            raise RuntimeError("Lexikon fehlt. Bitte Index neu bauen.")
        return lex

    @staticmethod
    def _canonicalize_term(term: str) -> str:
        """Canonicalize a query term the same way the index normalises tokens.

        NFKC + the basic whitespace/control normalisation used at index build
        time, so a query that differs only by compatibility codepoints (e.g.
        full-width digits, combining forms) still resolves. Falls back to a bare
        NFKC normalisation if the shared normaliser is unavailable.
        """
        if not term:
            return ""
        try:
            from candyconc.utils.text_normalize import normalize_text_basic

            return normalize_text_basic(term)
        except Exception:
            return unicodedata.normalize("NFKC", term)

    def _lexicon_attr_name(self, lexicon: Optional[Lexicon]) -> str:
        """Stable cache key for the per-attr casefold index ('word' / 'lemma')."""
        lexicons = getattr(self, "lexicons", None)
        if lexicon is not None and lexicons is not None:
            if lexicon is getattr(lexicons, "lemma", None):
                return "lemma"
        return "word"

    def _casefold_map(self, lexicon: Lexicon, attr: str) -> Dict[str, Tuple[int, ...]]:
        """Lazily build (and cache) a lowercase -> sorted id tuple map.

        One full pass over the lexicon (vocabulary sized, about 12k types on a
        small test index, built in about 15 ms). Mirrors the case-folding
        semantics of ``CorpusIndex.term_positions(case_insensitive=True)``:
        every lexicon type whose ``str.lower`` equals the query's lowercase
        contributes its postings. ß and ss stay separate (see
        query_parser.casefold_key).
        """
        # Defensive: stub engines built via ``__new__`` in unit tests may not have
        # ``_lock`` / ``_casefold_index``. Fall back to a dummy lock and a local
        # cache dict so resolution still works without the full __init__.
        lock = getattr(self, "_lock", None) or threading.RLock()
        index = getattr(self, "_casefold_index", None)
        if index is None:
            index = {}
            try:
                self._casefold_index = index
            except Exception:
                pass
        with lock:
            cached = index.get(attr)
            if cached is not None:
                return cached
            mapping: Dict[str, List[int]] = {}
            vocab = int(getattr(lexicon, "vocab_size", 0) or 0)
            get_string = getattr(lexicon, "get_string", None)
            get_strings = getattr(lexicon, "get_strings_for_ids", None)
            if callable(get_string):
                items = ((tid, get_string(tid)) for tid in range(1, vocab + 1))
            elif callable(get_strings):
                ids = np.arange(1, vocab + 1, dtype=np.int64)
                items = zip((int(tid) for tid in ids), get_strings(ids))
            else:
                items = ()
            for tid, s in items:
                if not s:
                    continue
                mapping.setdefault(s.lower(), []).append(tid)
            frozen: Dict[str, Tuple[int, ...]] = {
                k: tuple(sorted(v)) for k, v in mapping.items()
            }
            index[attr] = frozen
            return frozen

    def _resolve_term_ids(
        self, term: str, lexicon: Optional[Lexicon] = None
    ) -> Tuple[int, ...]:
        """Resolve ``term`` to the FULL set of case-matching lexicon ids.

        Mirrors ``CorpusIndex.term_positions(case_insensitive=True)``: the union
        of every lexicon type whose ``str.lower`` equals the (canonicalized)
        query's lowercase. So a lowercase query of a capitalized-only noun ('menschen')
        resolves to {'Menschen'} and the counts match the case-insensitive plain
        search. Returns a sorted, de-duplicated tuple of ids (empty if no match).
        """
        if not self._loaded:
            self.load()
        lex = lexicon or (self.lexicons.word if self.lexicons else None)
        if not lex:
            return ()
        attr = self._lexicon_attr_name(lex)
        canonical = self._canonicalize_term(term)
        if not canonical:
            return ()
        cf_map = self._casefold_map(lex, attr)
        ids = cf_map.get(canonical.lower())
        if ids:
            return ids
        # Defence-in-depth: an exact (case-sensitive) hit that somehow escaped
        # the casefold map (e.g. a codepoint normalisation edge) still resolves.
        get_id = getattr(lex, "get_id", None)
        exact = int(get_id(canonical)) if callable(get_id) else 0
        if exact > 0:
            return (exact,)
        return ()

    def _resolve_term_id(self, term: str, lexicon: Optional[Lexicon] = None) -> int:
        """Return a single canonical term id for ``term``.

        Case-insensitive: the canonical id is the exact-case hit when present
        (fast path, preserves the historical id for single-variant terms),
        otherwise the lowest-id casefold variant. Callers that need the full
        case-insensitive position set use :meth:`_resolve_term_ids` /
        :meth:`_get_term_positions` (which union all variants); this single-int
        accessor stays for cache-key/identity and back-compat callers.
        """
        if not self._loaded:
            self.load()
        lex = lexicon or (self.lexicons.word if self.lexicons else None)
        if not lex:
            return 0
        # Fast path: exact get_id hit on the canonicalized term.
        canonical = self._canonicalize_term(term)
        exact = int(lex.get_id(canonical)) if canonical else 0
        if exact > 0:
            return exact
        ids = self._resolve_term_ids(term, lex)
        return int(ids[0]) if ids else 0

    def _get_term_positions(
        self,
        term: str,
        attr: str = "word",
        term_id: Optional[int] = None,
        lexicon: Optional[Lexicon] = None,
        case_insensitive: bool = True,
    ) -> np.ndarray:
        """Return the token positions of ``term``.

        With ``case_insensitive=True`` (the default, used by the collocation /
        network path) the positions are the UNION over every casefold-matching
        lexicon id, mirroring ``CorpusIndex.term_positions(case_insensitive=True)``,
        so a lowercase query of a capitalized-only noun returns the same hits
        as the plain CI search. The pairing-free human versus AI contrast
        kernel opts OUT (``case_insensitive=False``) to keep its golden-pinned
        values byte-stable: it resolves the single canonical id only.
        """
        if not self._loaded:
            self.load()
        if not self.token_store:
            return np.array([], dtype=np.uint32)
        lex = lexicon or self._get_lexicon(attr)
        if attr == "word":
            get_positions = self.token_store.get_positions_for_word_id
        elif attr == "lemma":
            get_positions = self.token_store.get_positions_for_lemma_id
        else:
            raise ValueError("attr muss word oder lemma sein")

        if not case_insensitive:
            # Single canonical id only (historical contrast behaviour).
            if term_id is None:
                term_id = self._resolve_term_id(term, lex)
            if not term_id or term_id <= 0:
                return np.array([], dtype=np.uint32)
            return get_positions(int(term_id))

        # Case-insensitive union over every casefold-matching lexicon id, mirroring
        # CorpusIndex.term_positions(case_insensitive=True). A precomputed
        # ``term_id`` only pins the canonical variant, so we still widen to the
        # full casefold set for that term (e.g. 'die' unions Die/DIE) to keep the
        # collocation/network counts identical to the CI plain search.
        try:
            ids = self._resolve_term_ids(term, lex)
        except (AttributeError, TypeError):
            # Lexicon lacks the casefold accessors (e.g. a unit-test stub). Honour
            # an explicit caller-resolved id, else give up.
            ids = ()
        if not ids:
            if term_id and term_id > 0:
                # Honour an explicit id (caller already resolved it / no casefold
                # siblings available).
                return get_positions(int(term_id))
            return np.array([], dtype=np.uint32)
        if len(ids) == 1:
            return get_positions(int(ids[0]))
        parts = [get_positions(int(tid)) for tid in ids]
        parts = [p for p in parts if p.size]
        if not parts:
            return np.array([], dtype=np.uint32)
        # Postings per id are already sorted; concatenate + sort+unique so the
        # merged anchor stream is strictly increasing (coverage_sweep requires
        # sorted anchors and counts each corpus position once).
        merged = np.concatenate(parts)
        merged = np.unique(merged)
        return merged.astype(np.uint32, copy=False)

    def _warn_if_very_frequent(self, term: str, match_count: int) -> None:
        if not self.token_store:
            return
        token_count = self.token_store.token_count
        threshold = max(self._very_frequent_min, int(token_count * self._very_frequent_ratio))
        if match_count >= threshold:
            LOGGER.warning(
                "Term '%s' sehr häufig: %d Treffer. Laufzeit kann deutlich steigen.",
                term,
                match_count,
            )

    def _filter_positions_by_docset(
        self, positions: np.ndarray, docset_mask: np.ndarray
    ) -> np.ndarray:
        if positions.size == 0:
            return positions
        if not (self.boundaries and self.boundaries.document):
            raise RuntimeError("Dokumentgrenzen fehlen. Bitte Index neu bauen.")
        doc_bounds = self.boundaries.document._positions
        if doc_bounds.size == 0:
            return positions
        if docset_mask.size < doc_bounds.size:
            raise RuntimeError("Docset Maske passt nicht zu Dokumentanzahl.")
        return filter_positions_by_docset_fast(positions, doc_bounds, docset_mask)
        
    def collocate_stats(
        self,
        term: str,
        window_left: int = 5,
        window_right: int = 5,
        within_sentence: bool = False,
        stoplist: Optional[List[str]] = None,
        top_n: Optional[int] = None,
        # EVERT (2004), Abb. 2.13, "Alternative contingency table for
        # distance-based cooccurrences". Fuer Fensterkookkurrenz mit dem
        # Knoten als Basis gilt dort:
        #
        #     R1 = |W(u)|   (Fenstergroesse, UNION der lokalen Fenster)
        #     C1 = f(v)     (reine Korpusfrequenz des Kollokats)
        #     N  = |T|      (Korpusgroesse in Token)
        #
        # Evert schreibt ausdruecklich: "The window for a type v is the
        # UNION of its local windows", und dass bei Ueberlappung
        # |W(v)| != Summe der |W(t)| gilt.
        #
        # The default is False. True gives a table in MIXED units: R1 in
        # tokens, C1 = f(v)*m and N = |T|*m in anchor-times-token. In
        # E = R1*C1/N the m cancels, so MI, MI3, t, z, chi2_cell and LMI
        # look right, but every measure that needs the FULL table does not.
        #
        # On a 56,000-token test index, node "Merkel", recomputed by hand
        # against Evert's table:
        #     word        LL True   LL Evert
        #     Vasallen     29.39      31.91
        #     ihre         17.54      18.12
        #     von          15.48      15.80
        # And with C1 = f(v)*m, Dice = 2*O11/(R1+C1) becomes monotonic in
        # O11/f(v), i.e. MI-like: on a 142M-token corpus the logdice column
        # had 0 of 4,716 values in the defined band [0,14] and put hapaxes
        # above the real collocates.
        #
        # With False the engine's log-likelihood agrees with the hand
        # computation after Evert to two decimal places.
        pair_semantics: bool = False,
        attr: str = "word",
        cache_dir: Optional[Path] = None,
        cache_mode: str = "readwrite",
        term_id: Optional[int] = None,
        docset_mask: Optional[np.ndarray] = None,
        min_count: int = 5,
    ) -> pd.DataFrame:
        """
        Calculate collocation statistics for a term.
        
        Processes ENTIRE CORPUS - no sampling, scientifically accurate.
        
        Args:
            term: Search term
            window_left: Left context window size
            window_right: Right context window size
            within_sentence: If True, clip windows to sentence boundaries
            stoplist: Words to exclude from collocates
            top_n: Return only top N results (None = all)
            pair_semantics: Count overlapping windows multiple times
            
        Returns:
            DataFrame with columns: word, observed, expected, chi2_cell,
            t_score, log_likelihood, dice, rank
        """
        if not self._loaded:
            self.load()
            
        LOGGER.info("Computing collocations for '%s' (L=%d, R=%d)", 
                   term, window_left, window_right)
        
        # Step 1: Get all matches
        if cache_mode not in ("off", "read", "write", "readwrite"):
            raise ValueError("cache_mode muss off, read, write oder readwrite sein")
        if docset_mask is not None:
            cache_mode = "off"

        lex = self._get_lexicon(attr)
        if attr == "lemma" and lex.vocab_size == 0:
            raise RuntimeError("Lemma Lexikon fehlt. Bitte Index neu bauen.")
        if attr == "lemma" and self.token_store and not self.token_store.has_lemma_postings():
            raise RuntimeError("Lemma Postings fehlen. Bitte Index neu bauen.")

        if term_id is None:
            term_id = self._resolve_term_id(term, lex)
        resolved_ids = self._resolve_term_ids(term, lex)
        self_collocate_ids: Set[int] = {int(tid) for tid in resolved_ids if int(tid) > 0}
        if term_id and term_id > 0:
            self_collocate_ids.add(int(term_id))
        positions = self._get_term_positions(term, attr=attr, term_id=term_id, lexicon=lex)
        if docset_mask is not None:
            positions = self._filter_positions_by_docset(positions, docset_mask)
        if positions.size == 0:
            LOGGER.warning("No matches found for term '%s'", term)
            return pd.DataFrame()
            
        m = int(positions.size)
        LOGGER.info("Found %d matches", m)
        self._warn_if_very_frequent(term, m)
        
        # Step 2: Coverage sweep
        anchors = positions.astype(np.int64, copy=False)
        spans = np.ones_like(anchors, dtype=np.int64)
        seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
            anchors=anchors,
            spans=spans,
            window_left=window_left,
            window_right=window_right,
            # ALWAYS pass document boundaries (even when within_sentence is False
            # and no docset is set): clip_bounds_array(False) returns the document
            # bounds, so windows never bleed collocates across document edges.
            # Without this, windows clipped only at corpus ends and a node at a
            # document's last token collected collocates from the next document.
            boundaries=self.boundaries,
            within_sentence=within_sentence,
            pair_semantics=pair_semantics,
            total_tokens=self.token_store.token_count if self.token_store else 0,
        )
        u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
        if u <= 0:
            return pd.DataFrame()
        LOGGER.info("Generated %d coverage segments, context mass u=%d", len(seg_starts), u)
        
        # Step 3: Build stoplist as ID set
        stop_ids: Optional[Set[int]] = None
        if stoplist:
            stop_ids = {lex.get_id(w) for w in stoplist}

        cache = None
        cache_key = None
        if cache_dir and term_id > 0:
            cache = CollocationCache(cache_dir, self.index_path.name)
            cache_key = cache.make_key(
                term_id=term_id,
                window_left=window_left,
                window_right=window_right,
                within_sentence=within_sentence,
                pair_semantics=pair_semantics,
                stoplist_ids=stop_ids,
                top_n=top_n,
                attr_name=attr,
            )
            # Fold min_count into the cache key so a min_count=1 cache entry is not
            # served for a min_count=5 request (and vice versa).
            # V2 scores use the explicit anchor×token event space. V1 cache
            # entries encode invalid Dice/delta-P values and must never be read.
            cache_key = f"{cache_key}_eventspacev2_mc{int(min_count)}"
            if self_collocate_ids:
                cache_key = f"{cache_key}_noselfcf"
            # Fold the resolved case-insensitive id-set into the key: ``term_id``
            # only pins the canonical variant, but the positions are the UNION of
            # all casefold-matching ids (die/Die/DIE). Without this a single-variant
            # cache entry could be served for a multi-variant union (or vice versa)
            # that share the same canonical term_id, leaking wrong counts.
            if len(resolved_ids) > 1:
                ids_sig = hashlib.blake2b(
                    np.asarray(resolved_ids, dtype=np.int64).tobytes(), digest_size=8
                ).hexdigest()
                cache_key = f"{cache_key}_ci{ids_sig}"
            if cache_mode in ("read", "readwrite"):
                cached = cache.load(cache_key, lex)
                if cached is not None:
                    # The compact cache stores legacy columns only; reconstruct
                    # delta-P from V2's cached Dice and the same event universe.
                    n_total = self.lexicons.total_tokens if self.lexicons else 0
                    return self._attach_delta_p_to_cached(
                        cached,
                        u=float(u),
                        event_total=float((m if pair_semantics else 1) * n_total),
                    )

        # Step 4: Count collocates (kernel auto-selected)
        counts = count_collocates(
            self.token_store,
            seg_starts,
            seg_ends,
            seg_weights,
            stoplist=stop_ids,
            attr=attr,
            # ``top_n`` is an output rank limit; association top-k must be
            # scored over the full eligible candidate space before truncation.
            top_n=None,
        )
        
        LOGGER.info("Counted %d unique collocates", len(counts))

        # A node's own casefold variants are not collocates of that node.
        if self_collocate_ids and counts:
            counts = {
                tid: c
                for tid, c in counts.items()
                if int(tid) not in self_collocate_ids
            }
            if not counts:
                return pd.DataFrame()

        # Step 4b: Min-frequency guard. Drop collocates with co-occurrence below
        # ``min_count`` BEFORE ranking, so MI / logDice / NPMI top lists are not
        # dominated by O=1 hapaxes (an artefact, not an association signal).
        if min_count and min_count > 1 and counts:
            counts = {tid: c for tid, c in counts.items() if c >= min_count}
            if not counts:
                return pd.DataFrame()

        # Step 5: Calculate statistics (docset-aware, if provided)
        freqs_override: Dict[int, int] | None = None
        freqs_override_arr: np.ndarray | None = None
        total_tokens_override: int | None = None
        if docset_mask is not None:
            try:
                # Reuse a bounded LRU cache of dense docset frequencies keyed by a
                # stable membership signature, so repeated stats over the SAME
                # subcorpus don't trigger a fresh full rescan + vocab-sized dense
                # allocation. The key changes when membership changes (correctness
                # preserving); if the mask can't be hashed we skip caching.
                docset_cache_key = self._docset_signature(docset_mask)
                freqs_override_arr, total_tokens_override = self._docset_word_counts_dense(
                    docset_mask, attr=attr, cache_key=docset_cache_key
                )
            except Exception:
                LOGGER.exception(
                    "Docset-Frequenzen konnten nicht geladen werden; "
                    "Kollokationen brechen fail-closed ab."
                )
                raise RuntimeError(
                    "Docset-Frequenzen konnten nicht berechnet werden. "
                    "Kollokationswerte werden nicht mit globalen Korpusfrequenzen "
                    "als scheinbar docset-lokale Evidenz ausgegeben."
                )
        arrays = self._calculate_statistics_arrays(
            counts,
            m,
            u,
            lex,
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr,
            total_tokens_override=total_tokens_override,
            pair_semantics=pair_semantics,
        )
        if arrays[0].size == 0:
            return pd.DataFrame()

        sorted_arrays = self._sort_statistics_arrays(*arrays, top_n=top_n)
        df = self._statistics_frame_from_sorted(
            *sorted_arrays, lex=lex, node_frequency=int(m),
            context_mass=float(u),
            scope_tokens=float(
                total_tokens_override
                if total_tokens_override is not None
                else (self.lexicons.total_tokens if self.lexicons else 0)),
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr
        )

        if cache and cache_key and cache_mode in ("write", "readwrite"):
            # The on-disk cache schema (CollocationCache.save, a non-owned file)
            # accepts the fixed 12-array shape ``[:12]`` (word_ids..rank).
            # Directional delta-P is reconstructed from cached ``observed`` and
            # Dice plus the event-space marginals, so it need not be stored.
            cache.save(cache_key, sorted_arrays[:12])
        return df
        
    def _sort_statistics_arrays(
        self,
        word_ids: np.ndarray,
        observed: np.ndarray,
        expected: np.ndarray,
        mi: np.ndarray,
        lmi: np.ndarray,
        npmi: np.ndarray,
        z_score: np.ndarray,
        chi2_cell: np.ndarray,
        t_score: np.ndarray,
        log_likelihood: np.ndarray,
        dice: np.ndarray,
        delta_p_nc: np.ndarray,
        delta_p_cn: np.ndarray,
        mi3: np.ndarray,
        top_n: Optional[int],
    ) -> Tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ]:
        # DEFAULT ranking is logDice (a recognized association measure), NOT the
        # single-cell chi-square contribution, which is not a sound
        # ranking key. logDice = 14 + log2(dice) is a strictly monotonic transform
        # of dice, so ordering by ``dice`` descending is identical to ordering by
        # logDice descending (and avoids -inf for dice==0).
        sort_metric = dice
        if top_n and sort_metric.size > top_n:
            idx = np.argpartition(sort_metric, -top_n)[-top_n:]
            order = idx[np.argsort(sort_metric[idx])[::-1]]
        else:
            order = np.argsort(sort_metric)[::-1]
        # NOTE: ``ranks`` is kept at position 11 (the 12th element) so that
        # ``sorted_arrays[:12]`` is the exact legacy tuple shape consumed by
        # ``CollocationCache.save``. The two directional delta-P arrays and mi3
        # are appended AFTER ranks; the row builder reads them positionally.
        return (
            word_ids[order],
            observed[order],
            expected[order],
            mi[order],
            lmi[order],
            npmi[order],
            z_score[order],
            chi2_cell[order],
            t_score[order],
            log_likelihood[order],
            dice[order],
            np.arange(1, len(order) + 1, dtype=np.int64),
            delta_p_nc[order],
            delta_p_cn[order],
            mi3[order],
        )

    def _statistics_frame_from_sorted(
        self,
        word_ids: np.ndarray,
        observed: np.ndarray,
        expected: np.ndarray,
        mi: np.ndarray,
        lmi: np.ndarray,
        npmi: np.ndarray,
        z_score: np.ndarray,
        chi2_cell: np.ndarray,
        t_score: np.ndarray,
        log_likelihood: np.ndarray,
        dice: np.ndarray,
        ranks: np.ndarray,
        delta_p_nc: np.ndarray,
        delta_p_cn: np.ndarray,
        mi3: np.ndarray,
        lex: Lexicon,
        node_frequency: int,
        context_mass: float,
        scope_tokens: float,
        freqs_override: Dict[int, int] | None = None,
        freqs_override_arr: np.ndarray | None = None,
    ) -> pd.DataFrame:
        words = lex.get_strings_for_ids(word_ids)
        # logDice = 14 + log2(Dice) (Rikov/Kilgarriff): corpus-size independent,
        # comparable across corpora, the recommended default measure. Exposed as a
        # first-class column so consumers (and the copilot) see it directly rather
        # than re-deriving it from raw Dice. 0 where Dice == 0 (no co-occurrence).
        logdice = np.zeros_like(dice, dtype=np.float64)
        _pos = dice > 0
        np.log2(dice, out=logdice, where=_pos)
        logdice = np.where(_pos, 14.0 + logdice, 0.0)
        # Rychlys Nenner: f(Knoten) + f(Kollokat), beide als reine
        # Korpusfrequenzen. f(Kollokat) wird aus der Evert-Tafel
        # zurueckgewonnen: dice = 2*O11/(R1+C1) und expected = R1*C1/N.
        # The overrides MUST be passed on. Without them f(v) takes the
        # global lexicon frequency while O11 is counted docset-locally, and
        # Rychly's denominator mixes two reference spaces. On a test index
        # with where(split="test") the network nodes then switched from
        # content words to function words.
        _f2 = self._freqs_for_word_ids(
            word_ids, lex,
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr,
        ).astype(np.float64, copy=False)
        _nenner_r = float(node_frequency) + _f2
        _dice_r = np.divide(
            2.0 * observed.astype(np.float64, copy=False),
            _nenner_r,
            out=np.zeros(observed.shape, dtype=np.float64),
            where=_nenner_r > 0.0,
        )
        _logdice_rychly = np.zeros_like(_dice_r, dtype=np.float64)
        _pos_r = _dice_r > 0
        np.log2(_dice_r, out=_logdice_rychly, where=_pos_r)
        _logdice_rychly = np.where(_pos_r, 14.0 + _logdice_rychly, 0.0)

        # LOG RATIO (Hardie 2014) and CONSERVATIVE LOG RATIO (Evert 2022).
        #
        # Both need union-counted cooccurrences. A pair-weighted
        # cooccurrence against an unweighted corpus frequency would make
        # b = f(v) - O11 subtract two different counting schemes and turn
        # negative (on a 142M-token index 8,858 of 178,435 rows of the node
        # "der" had an O11 above the corpus frequency).
        #
        # Evert's contingency table provides union counts in the FIRST
        # sweep, so no second pass is needed and b is never negative:
        # union-counted, O11 <= f(v) holds (recounted over five nodes and
        # 1,551 rows on a 56,000-token test index: zero violations).
        #
        # The LRC is the ranking measure of the publication being
        # replicated (Heinrich/Evert 2024, CPSS 2024, 33-44,
        # https://aclanthology.org/2024.cpss-1.3/).
        # ``conservative_log_ratio_arrays`` is exact and conditional
        # (Clopper-Pearson) and validated against its Table 1 to 0.006. The
        # Bonferroni correction runs over the number of candidates tested
        # simultaneously, because exactly those are tested simultaneously.
        _lrc_spalten: Dict[str, np.ndarray] = {}
        _n1 = float(context_mass)
        _n2 = float(scope_tokens) - _n1
        if _n1 > 0.0 and _n2 > 0.0 and observed.size:
            from candyconc.core.significance import (
                conservative_log_ratio_arrays,
            )

            _a = observed.astype(np.float64, copy=False)
            _b = np.maximum(_f2 - _a, 0.0)
            _rate_ziel = _a / _n1
            _rate_rest = np.divide(
                _b, _n2, out=np.zeros_like(_b), where=_n2 > 0)
            # Haldane-Glaettung NUR fuer das rohe Verhaeltnis, damit eine
            # leere Referenzzelle keine Unendlichkeit ergibt. Der LRC
            # braucht sie nicht: sein Intervall ist exakt.
            _lr = np.log2(
                np.divide(_rate_ziel + 0.5 / _n1, _rate_rest + 0.5 / _n2,
                          out=np.ones_like(_a), where=True))
            # THE CORRECTION BASIS IS THE NUMBER OF CANDIDATES TESTED
            # SIMULTANEOUSLY, as in the publication.
            #
            # The corpus vocabulary (12,349 types on a 56,000-token test
            # index) is the wrong basis. With equal parameters (the same
            # within_sentence on both sides) both paths yield identically
            # R1=733, node=103, N=56191 and 56 candidates.
            #
            # Correcting over 12,349 types when 56 pairs were tested is
            # overcorrection: only two candidates would keep an LRC above
            # zero. The candidate count is determined by min_freq and the
            # analysis token filter and is therefore reproducible as long as
            # it is REPORTED. It appears as lrc_vocab in df.attrs and in the
            # method block.
            #
            # Candidates are the rows that can be output: punctuation and
            # other non-analysis tokens are dropped in all routes before
            # output and are not tested. They therefore do not count in m.
            from candyconc.analysis_defaults import is_analyst_token

            _vokabular = int(
                sum(1 for _w in words if is_analyst_token(str(_w or "")))
            ) or None
            _lrc_vokabular = _vokabular
            _lrc_spalten = {
                "log_ratio": np.round(_lr, 4),
                "lrc": np.round(
                    conservative_log_ratio_arrays(
                        _a, _b, _n1, _n2,
                        alpha=0.001, vocab=_vokabular),
                    4),
            }

        rahmen = pd.DataFrame({
            "word": words,
            "observed": observed.astype(np.int64, copy=False),
            # f(v), die Korpusfrequenz des Kollokats, also C1 der Tafel und
            # zugleich der zweite Summand in Rychlys Nenner. Sie wurde
            # oberhalb fuer genau diesen Nenner berechnet und dann
            # weggeworfen. Ohne sie laesst sich logdice nicht nachrechnen,
            # denn f(u) steht als node_frequency im Kopf der Antwort, f(v)
            # stand nirgends.
            "f2": _f2.astype(np.int64, copy=False),
            "expected": np.round(expected, 2),
            "mi": np.round(mi, 4),
            # MI3 (Oakes 1998): log2(O^3/E) over the same O/E pair as MI.
            "mi3": np.round(mi3, 4),
            "lmi": np.round(lmi, 4),
            "npmi": np.round(npmi, 4),
            "z": np.round(z_score, 4),
            "chi2_cell": np.round(chi2_cell, 2),
            "t_score": np.round(t_score, 2),
            "log_likelihood": np.round(log_likelihood, 2),
            "dice": dice,
            # TWO measures, named after the literature, not after
            # convenience.
            #
            # ``logdice`` = 14 + log2(2*O11/(f(u)+f(v))) is RYCHLY (2008),
            #   the canonical definition. A reader of "logdice" means this
            #   measure, hence it has the unmarked name.
            #
            # ``logdice_window`` = 14 + log2(2*O11/(|W(u)|+f(v))) is the
            #   log transform of the Dice coefficient on EVERT's contingency
            #   table for distance-based cooccurrence (2004, Fig. 2.13). It
            #   is NOT a "logDice after Evert": Evert 2004 defines Dice on
            #   the table, but no logDice. The log transform comes from
            #   Rychly, the table from Evert. This measure is consistent
            #   with ll, chi2 and delta_p, which use the same table.
            #
            # The difference lies in the reference mass of the denominator.
            # Evert's table normalizes against the union of the node windows
            # plus the collocate frequency, Rychly symmetrizes over the total
            # frequencies of both words. On a 56,000-token test index, node
            # "Merkel": "Vasallen" ranks first under Rychly with 10.70 and
            # eighth under the window table, behind "und" and "von". That is
            # not a numerical curiosity but the expression of this different
            # normalization.
            "logdice": np.round(_logdice_rychly, 4),
            "logdice_window": np.round(logdice, 4),
            **_lrc_spalten,
            "rank": ranks,
            # Directional delta-P (Gries 2013): asymmetric collocation strength.
            "delta_p_nc": np.round(delta_p_nc, 4),
            "delta_p_cn": np.round(delta_p_cn, 4),
        })
        # Die Korrekturbasis des LRC wird AUSGEWIESEN. Eine Zahl, deren
        # Zustandekommen die Leserin nicht nachrechnen kann, ist kein
        # Befund, und die Bonferroni-Korrektur ist der einzige Schritt des
        # LRC, der nicht aus den Randsummen der Zeile folgt.
        if _lrc_spalten:
            rahmen.attrs["lrc_vocab"] = int(_lrc_vokabular or 0)
            rahmen.attrs["lrc_alpha"] = 0.001
        # R1 = |W(u)| and N of the contingency table, so every row can be
        # recomputed from the response.
        rahmen.attrs["window_union_size"] = int(round(float(context_mass)))
        rahmen.attrs["scope_tokens"] = int(round(float(scope_tokens)))
        return rahmen
        # Pair-weighted co-occurrences can exceed the plain corpus frequency when a
        # token falls into several anchor windows. Subtracting them from the corpus
        # frequency would mix counting units and invalidate a token contingency table.
        # A conservative log ratio here would need a second sweep with
        # coverage_sweep_arrays(pair_semantics=False) to count the window union.
        # conservative_log_ratio_arrays remains available for valid token tables.

    def _attach_delta_p_to_cached(
        self, df: pd.DataFrame, *, u: float, event_total: float
    ) -> pd.DataFrame:
        """Add the directional delta-P columns to a frame loaded from the
        legacy collocation cache (which predates these columns).

        The cache stores raw (unrounded) ``observed`` (O11) and ``dice``, so the
        event-space collocate marginal is recovered losslessly:

            dice = 2*O11 / (u + C1)  =>  C1 = 2*O11/dice - u

        The cache key carries the event-space version, so it cannot read a
        pre-v2 entry with the old, invalid denominator.

        MI3 is likewise reconstructed losslessly: the cache stores the raw
        ``observed`` (O11) and ``expected`` (E11) arrays, and
        ``mi3 = log2(O11^3 / E11)`` uses exactly that pair (same as MI).
        """
        if df is None or df.empty:
            if df is not None and "delta_p_nc" not in df.columns:
                df = df.copy()
                df["delta_p_nc"] = pd.Series(dtype=np.float64)
                df["delta_p_cn"] = pd.Series(dtype=np.float64)
            if df is not None and "mi3" not in df.columns:
                df = df.copy()
                df["mi3"] = pd.Series(dtype=np.float64)
            return df
        out = df
        if "mi3" not in out.columns:
            observed_raw = out["observed"].to_numpy(dtype=np.float64, copy=False)
            expected_raw = out["expected"].to_numpy(dtype=np.float64, copy=False)
            valid = (observed_raw > 0) & (expected_raw > 0)
            mi3 = np.where(
                valid,
                np.log2(np.divide(
                    observed_raw ** 3,
                    expected_raw,
                    out=np.ones_like(observed_raw),
                    where=valid,
                )),
                0.0,
            )
            out = out.copy()
            out["mi3"] = np.round(mi3, 4)
        if "delta_p_nc" in out.columns and "delta_p_cn" in out.columns:
            return out
        observed = out["observed"].to_numpy(dtype=np.float64, copy=False)
        dice = out["dice"].to_numpy(dtype=np.float64, copy=False)
        c1 = np.where(
            dice > 0.0,
            (2.0 * observed) / np.where(dice > 0.0, dice, 1.0) - float(u),
            observed,
        )
        delta_p_nc, delta_p_cn = _delta_p_arrays(
            observed, float(u), c1, float(event_total)
        )
        if out is df:
            out = out.copy()
        out["delta_p_nc"] = np.round(delta_p_nc, 4)
        out["delta_p_cn"] = np.round(delta_p_cn, 4)
        return out

    def _calculate_statistics_arrays(
        self,
        counts: Dict[int, int],
        m: int,
        u: int,
        lexicon: Lexicon,
        *,
        freqs_override: Dict[int, int] | None = None,
        freqs_override_arr: np.ndarray | None = None,
        total_tokens_override: int | None = None,
        pair_semantics: bool = False,
    ) -> Tuple[
        np.ndarray,  # word_ids
        np.ndarray,  # observed
        np.ndarray,  # expected
        np.ndarray,  # mi
        np.ndarray,  # lmi
        np.ndarray,  # npmi
        np.ndarray,  # z_score
        np.ndarray,  # chi2_cell
        np.ndarray,  # t_score
        np.ndarray,  # log_likelihood
        np.ndarray,  # dice
        np.ndarray,  # delta_p_nc
        np.ndarray,  # delta_p_cn
        np.ndarray,  # mi3
    ]:
        if not lexicon:
            return _empty_stats_arrays()

        scope_total = total_tokens_override if total_tokens_override is not None else self.lexicons.total_tokens
        event_multiplier = int(m) if pair_semantics else 1
        event_total = int(scope_total) * event_multiplier
        if not counts or scope_total <= 0 or event_multiplier <= 0:
            return _empty_stats_arrays()

        word_ids = np.fromiter(counts.keys(), dtype=np.uint32)
        observed = np.fromiter(counts.values(), dtype=np.float64)
        max_id = lexicon.vocab_size
        valid_ids = (word_ids > 0) & (word_ids <= max_id)
        if not np.any(valid_ids):
            return _empty_stats_arrays()

        word_ids = word_ids[valid_ids]
        observed = observed[valid_ids]
        freqs = self._freqs_for_word_ids(
            word_ids,
            lexicon,
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr,
        )
        mask = freqs > 0
        if not np.any(mask):
            return _empty_stats_arrays()

        word_ids = word_ids[mask]
        observed = observed[mask]
        freqs = freqs[mask]

        # Every pair-semantics result lives in Ω = anchors × scope tokens. The
        # raw word frequency is therefore lifted by the *anchor multiplier*, not
        # fabricated from O11. This preserves the observed data and gives all
        # association measures one valid contingency table.
        collocate_event_mass = freqs * float(event_multiplier)
        expected = (float(u) * collocate_event_mass) / float(event_total)
        nonzero = expected > 0
        if not np.any(nonzero):
            return _empty_stats_arrays()

        word_ids = word_ids[nonzero]
        observed = observed[nonzero]
        collocate_event_mass = collocate_event_mass[nonzero]
        expected = expected[nonzero]

        mi = np.where(
            (observed > 0) & (expected > 0),
            np.log2(observed / expected),
            0.0,
        )
        lmi = observed * mi
        pxy = observed / float(event_total)
        npmi = np.where(
            pxy > 0,
            np.divide(mi, -np.log2(pxy), out=np.zeros_like(mi), where=pxy > 0),
            0.0,
        )
        z_score = np.where(expected > 0, (observed - expected) / np.sqrt(expected), 0.0)
        chi2_cell = ((observed - expected) ** 2) / expected
        t_score = (observed - expected) / np.sqrt(observed)
        log_likelihood = _g2_loglikelihood(
            observed, float(u), collocate_event_mass, float(event_total)
        )
        dice = np.divide(
            2.0 * observed,
            float(u) + collocate_event_mass,
            out=np.zeros_like(observed),
            where=(float(u) + collocate_event_mass) > 0.0,
        )
        delta_p_nc, delta_p_cn = _delta_p_arrays(
            observed, float(u), collocate_event_mass, float(event_total)
        )
        # MI3 (Oakes 1998): log2(O11^3 / E11), computed over EXACTLY the same
        # observed/expected pair as MI above (mi3 == mi + 2*log2(O11)). The
        # cubed observed count damps MI's low-frequency bias. 0.0 when O11 = 0
        # (no co-occurrence), same convention as MI.
        mi3 = np.where(
            (observed > 0) & (expected > 0),
            np.log2(np.divide(
                observed ** 3,
                expected,
                out=np.ones_like(observed),
                where=expected > 0,
            )),
            0.0,
        )

        return (
            word_ids,
            observed,
            expected,
            mi,
            lmi,
            npmi,
            z_score,
            chi2_cell,
            t_score,
            log_likelihood,
            dice,
            delta_p_nc,
            delta_p_cn,
            mi3,
        )

    def _calculate_selected_statistics_arrays(
        self,
        counts: Dict[int, int],
        m: int,
        u: int,
        lexicon: Lexicon,
        *,
        score_key: str,
        freqs_override: Dict[int, int] | None = None,
        freqs_override_arr: np.ndarray | None = None,
        total_tokens_override: int | None = None,
        pair_semantics: bool = False,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not lexicon:
            empty_u32 = np.array([], dtype=np.uint32)
            empty_f64 = np.array([], dtype=np.float64)
            return empty_u32, empty_f64, empty_f64

        scope_total = total_tokens_override if total_tokens_override is not None else self.lexicons.total_tokens
        event_multiplier = int(m) if pair_semantics else 1
        event_total = int(scope_total) * event_multiplier
        if not counts or scope_total <= 0 or event_multiplier <= 0:
            empty_u32 = np.array([], dtype=np.uint32)
            empty_f64 = np.array([], dtype=np.float64)
            return empty_u32, empty_f64, empty_f64

        word_ids = np.fromiter(counts.keys(), dtype=np.uint32)
        observed = np.fromiter(counts.values(), dtype=np.float64)
        max_id = lexicon.vocab_size
        valid_ids = (word_ids > 0) & (word_ids <= max_id)
        if not np.any(valid_ids):
            empty_u32 = np.array([], dtype=np.uint32)
            empty_f64 = np.array([], dtype=np.float64)
            return empty_u32, empty_f64, empty_f64

        word_ids = word_ids[valid_ids]
        observed = observed[valid_ids]
        freqs = self._freqs_for_word_ids(
            word_ids,
            lexicon,
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr,
        )
        mask = freqs > 0
        if not np.any(mask):
            empty_u32 = np.array([], dtype=np.uint32)
            empty_f64 = np.array([], dtype=np.float64)
            return empty_u32, empty_f64, empty_f64

        word_ids = word_ids[mask]
        observed = observed[mask]
        freqs = freqs[mask]
        collocate_event_mass = freqs * float(event_multiplier)
        expected = (float(u) * collocate_event_mass) / float(event_total)
        nonzero = expected > 0
        if not np.any(nonzero):
            empty_u32 = np.array([], dtype=np.uint32)
            empty_f64 = np.array([], dtype=np.float64)
            return empty_u32, empty_f64, empty_f64

        word_ids = word_ids[nonzero]
        observed = observed[nonzero]
        collocate_event_mass = collocate_event_mass[nonzero]
        expected = expected[nonzero]
        score = self._calculate_selected_score_array(
            observed,
            expected,
            collocate_event_mass,
            context_mass=float(u),
            event_total=float(event_total),
            score_key=score_key,
            node_frequency=float(m) if m else None,
        )
        return word_ids, observed, score

    @staticmethod
    def _calculate_selected_score_array(
        observed: np.ndarray,
        expected: np.ndarray,
        collocate_event_mass: np.ndarray,
        *,
        context_mass: float,
        event_total: float,
        score_key: str,
        node_frequency: float | None = None,
    ) -> np.ndarray:
        key = (score_key or "").strip().lower()
        valid = (observed > 0) & (expected > 0)
        ratio = np.divide(
            observed,
            expected,
            out=np.ones_like(observed, dtype=np.float64),
            where=valid,
        )
        mi = np.zeros_like(observed, dtype=np.float64)
        np.log2(ratio, out=mi, where=valid)
        if key == "f":
            return observed.astype(np.float64, copy=True)
        if key == "mi":
            return mi
        if key == "mi3":
            # MI3 = log2(O^3/E) = MI + 2*log2(O) over the same O/E pair.
            log_obs = np.zeros_like(observed, dtype=np.float64)
            np.log2(observed, out=log_obs, where=valid)
            return np.where(valid, mi + 2.0 * log_obs, 0.0)
        if key == "lmi":
            return observed * mi
        if key == "npmi":
            pxy = (
                observed / float(event_total)
                if event_total > 0.0
                else np.zeros_like(observed)
            )
            denom = np.zeros_like(mi, dtype=np.float64)
            positive_pxy = pxy > 0
            np.log2(pxy, out=denom, where=positive_pxy)
            denom *= -1.0
            return np.divide(
                mi,
                denom,
                out=np.zeros_like(mi, dtype=np.float64),
                where=positive_pxy & (denom > 0),
            )
        if key == "z":
            return np.divide(
                observed - expected,
                np.sqrt(expected, out=np.zeros_like(expected, dtype=np.float64), where=expected > 0),
                out=np.zeros_like(observed, dtype=np.float64),
                where=expected > 0,
            )
        if key == "chi2_cell":
            return np.divide(
                (observed - expected) ** 2,
                expected,
                out=np.zeros_like(observed, dtype=np.float64),
                where=expected > 0,
            )
        if key == "t":
            return np.divide(
                observed - expected,
                np.sqrt(observed, out=np.zeros_like(observed, dtype=np.float64), where=observed > 0),
                out=np.zeros_like(observed, dtype=np.float64),
                where=observed > 0,
            )
        if key == "ll":
            return _g2_loglikelihood(
                observed, float(context_mass), collocate_event_mass, float(event_total)
            )
        denom = float(context_mass) + collocate_event_mass
        dice = np.divide(
            2.0 * observed,
            denom,
            out=np.zeros_like(observed, dtype=np.float64),
            where=denom > 0,
        )
        if key in ("logdice", "logdice_window"):
            # Rychly's logDice needs the node frequency f(u). When it is unavailable,
            # return zero for logdice and expose the window formula under its own name.
            if key == "logdice":
                if node_frequency is None or float(node_frequency) <= 0:
                    return np.zeros_like(observed, dtype=np.float64)
                nenner_r = float(node_frequency) + collocate_event_mass
                verhaeltnis = np.divide(
                    2.0 * observed.astype(np.float64, copy=False),
                    nenner_r,
                    out=np.zeros_like(observed, dtype=np.float64),
                    where=nenner_r > 0,
                )
            else:
                verhaeltnis = dice
            out = np.zeros_like(verhaeltnis, dtype=np.float64)
            positive = verhaeltnis > 0
            np.log2(verhaeltnis, out=out, where=positive)
            return np.where(positive, 14.0 + out, 0.0)
        return dice

    def _docset_word_counts_dense(
        self,
        docset_mask: np.ndarray,
        *,
        attr: str = "word",
        cache_key: str | None = None,
    ) -> tuple[np.ndarray, int]:
        if cache_key:
            cached = self._dense_cache_get(f"{attr}:{cache_key}")
            if cached is not None:
                return cached
        if not self.token_store:
            return np.zeros(0, dtype=np.uint64), 0
        if not (self.boundaries and self.boundaries.document):
            raise RuntimeError("Dokumentgrenzen fehlen. Bitte Index neu bauen.")
        doc_bounds = self.boundaries.document._positions
        if doc_bounds.size == 0:
            return np.zeros(0, dtype=np.uint64), 0
        doc_ids = np.flatnonzero(docset_mask).astype(np.int64, copy=False)
        if doc_ids.size == 0:
            lex = self._get_lexicon(attr)
            return np.zeros(int(lex.vocab_size) + 1, dtype=np.uint64), 0
        token_count = int(self.token_store.token_count)
        starts = doc_bounds[doc_ids].astype(np.uint32, copy=False)
        next_ids = doc_ids + 1
        ends = np.empty_like(starts, dtype=np.uint32)
        mask = next_ids < doc_bounds.size
        if np.any(mask):
            ends[mask] = doc_bounds[next_ids[mask]].astype(np.uint32, copy=False)
        if np.any(~mask):
            ends[~mask] = np.uint32(token_count)
        seg_weights = np.ones(starts.shape[0], dtype=np.uint32)
        lex = self._get_lexicon(attr)
        counts = count_hashmap_svb_dense(
            self.token_store,
            attr,
            starts,
            ends,
            seg_weights,
            int(lex.vocab_size),
            stoplist=None,
        )
        total_tokens = int(np.sum(ends.astype(np.int64) - starts.astype(np.int64)))
        if cache_key:
            self._dense_cache_set(f"{attr}:{cache_key}", (counts, total_tokens))
        return counts, total_tokens
        
    @staticmethod
    def split_anchor_positions_by_doc_masks(
        anchors: np.ndarray,
        doc_bounds: np.ndarray,
        target_doc_mask: np.ndarray,
        reference_doc_mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Shared contrast substrate: split anchor positions by two docset masks.

        Maps each anchor position to its document index and decides which side(s)
        of the contrast it belongs to. Returns ``(valid, target, reference)``:

        - ``valid``: boolean mask over ``anchors`` — positions that map to a real
          document (callers must apply it to anchors AND any parallel arrays such
          as CQL match spans).
        - ``target`` / ``reference``: boolean masks aligned to
          ``anchors[valid]`` — membership in each docset (sides may overlap if
          the input masks do).

        This is the ONE counting front-end both contrast tails share — the
        global-baseline kernel (:meth:`compare_by_docset_masks`) and the server's
        per-docset diff path (``_collocates_diff_rows_for_term``). Keep it pure
        index arithmetic: both tails are golden-pinned byte-for-byte.
        """
        doc_idx = map_positions_to_doc_ids_fast(anchors, doc_bounds)
        valid = (doc_idx >= 0) & (doc_idx < int(doc_bounds.size))
        doc_idx = doc_idx[valid].astype(np.int64, copy=False)
        target = np.asarray(target_doc_mask, dtype=bool)[doc_idx]
        reference = np.asarray(reference_doc_mask, dtype=bool)[doc_idx]
        return valid, target, reference

    def compare_human_ai(
        self,
        term: str,
        window_left: int = 5,
        window_right: int = 5,
        top_n: int = 50,
        within_sentence: bool = True,
    ) -> pd.DataFrame:
        """Compare collocations between human and AI texts.

        Derive masks from ``self._doc_types`` (human==0, ai==1) and delegate to
        :meth:`compare_by_docset_masks`. Rename target/reference columns to
        human/ai, preserving the grounding contract and the ``log_ratio`` sign
        (human-leaning > 0). Scoring uses the global corpus baseline. See
        ``tests/core/test_compare_human_ai_golden.py``.
        """
        if not self._loaded:
            self.load()
        doc_types = self._doc_types
        if doc_types is None:
            return pd.DataFrame()
        target_mask = doc_types == 0
        reference_mask = doc_types == 1
        df = self.compare_by_docset_masks(
            term,
            target_doc_mask=target_mask,
            reference_doc_mask=reference_mask,
            window_left=window_left,
            window_right=window_right,
            top_n=top_n,
            within_sentence=within_sentence,
            scoring="global",
        )
        if df.empty:
            return df
        return df.rename(
            columns={
                "freq_target": "freq_human",
                "freq_reference": "freq_ai",
                "chi2_cell_target": "chi2_cell_human",
                "chi2_cell_reference": "chi2_cell_ai",
            }
        )

    def compare_by_docset_masks(
        self,
        term: str,
        *,
        target_doc_mask: np.ndarray,
        reference_doc_mask: np.ndarray,
        window_left: int = 5,
        window_right: int = 5,
        top_n: int = 50,
        within_sentence: bool = True,
        scoring: str = "global",
    ) -> pd.DataFrame:
        """Compare collocations between two docset masks without requiring pairing.

        ``target_doc_mask`` and ``reference_doc_mask`` are boolean arrays with
        one entry per document. Split the match positions of ``term`` by their
        document masks, then score each side independently.

        ``scoring="global"`` is the default and the only available mode.
        It scores ``chi2_cell`` against the corpus lexicon baseline, as in
        ``compare_human_ai``. A per-docset expected-frequency baseline would
        change the ``chi2_cell`` and ``log_ratio`` values.
        """
        if not self._loaded:
            self.load()
        if scoring != "global":
            raise ValueError(
                f"compare_by_docset_masks: scoring={scoring!r} not supported "
                "(only 'global' preserves the grounding contract)"
            )

        LOGGER.info("Contrasting docset masks for '%s'", term)

        # 1. Get all matches. The contrast kernel is golden-pinned to the
        # single-canonical-id resolution (case_insensitive=False); the CI union
        # used by the collocation/network path is deliberately NOT applied here so
        # the published chi2_cell/log_ratio values stay byte-stable.
        positions = self._get_term_positions(term, case_insensitive=False)
        if positions.size == 0:
            return pd.DataFrame()
            
        # 2. Split matches by docset membership (shared contrast substrate).
        if not self.boundaries or not self.boundaries.document:
            LOGGER.warning("No document boundaries found. Cannot split docsets.")
            return pd.DataFrame()

        self.boundaries.reset_cursors()

        doc_bounds = self._doc_bounds
        if doc_bounds is None:
            return pd.DataFrame()
        
        match_positions = positions.astype(np.uint32, copy=False)
        valid, mask_h, mask_a = self.split_anchor_positions_by_doc_masks(
            match_positions, doc_bounds, target_doc_mask, reference_doc_mask
        )
        if not np.any(valid):
            return pd.DataFrame()
        match_positions = match_positions[valid]
        positions_h = match_positions[mask_h]
        positions_a = match_positions[mask_a]

        LOGGER.info("Split matches: %d target, %d reference", positions_h.size, positions_a.size)
        
        # 3. Process Human Corpus
        anchors_h = positions_h.astype(np.int64, copy=False)
        spans_h = np.ones_like(anchors_h, dtype=np.int64)
        seg_h_starts, seg_h_ends, seg_h_weights = coverage_sweep_arrays(
            anchors=anchors_h,
            spans=spans_h,
            window_left=window_left,
            window_right=window_right,
            boundaries=self.boundaries,
            within_sentence=within_sentence,
            total_tokens=self.token_store.token_count if self.token_store else 0,
        )
        lex = self._get_lexicon("word")
        counts_human = count_collocates(
            self.token_store, seg_h_starts, seg_h_ends, seg_h_weights
        )
        stats_human = self._calculate_statistics_arrays(
            counts_human,
            int(positions_h.size),
            total_context_mass_arrays(seg_h_starts, seg_h_ends, seg_h_weights),
            lex,
        )
        
        # 4. Process AI Corpus
        anchors_a = positions_a.astype(np.int64, copy=False)
        spans_a = np.ones_like(anchors_a, dtype=np.int64)
        seg_a_starts, seg_a_ends, seg_a_weights = coverage_sweep_arrays(
            anchors=anchors_a,
            spans=spans_a,
            window_left=window_left,
            window_right=window_right,
            boundaries=self.boundaries,
            within_sentence=within_sentence,
            total_tokens=self.token_store.token_count if self.token_store else 0,
        )
        counts_ai = count_collocates(
            self.token_store, seg_a_starts, seg_a_ends, seg_a_weights
        )
        stats_ai = self._calculate_statistics_arrays(
            counts_ai,
            int(positions_a.size),
            total_context_mass_arrays(seg_a_starts, seg_a_ends, seg_a_weights),
            lex,
        )

        if stats_human[0].size == 0 and stats_ai[0].size == 0:
            return pd.DataFrame()
        
        # 5. Merge and Compare
        # Create dictionaries for fast lookup
        ids_h = stats_human[0]
        obs_h = stats_human[1]
        chi2_cell_h = stats_human[7]
        ids_a = stats_ai[0]
        obs_a = stats_ai[1]
        chi2_cell_a = stats_ai[7]

        if ids_h.size:
            order_h = np.argsort(ids_h, kind="mergesort")
            ids_h = ids_h[order_h]
            obs_h = obs_h[order_h]
            chi2_cell_h = chi2_cell_h[order_h]
        if ids_a.size:
            order_a = np.argsort(ids_a, kind="mergesort")
            ids_a = ids_a[order_a]
            obs_a = obs_a[order_a]
            chi2_cell_a = chi2_cell_a[order_a]

        from candyconc.core import _fast_index as _fast_index_mod  # type: ignore
        union_sorted = getattr(_fast_index_mod, "union_sorted", None)
        if union_sorted is None:
            raise RuntimeError("Fast Union Pfad fehlt. Bitte native Extension bauen.")
        all_ids = union_sorted(ids_h.astype(np.uint32, copy=False), ids_a.astype(np.uint32, copy=False))
        if all_ids.size == 0:
            return pd.DataFrame()

        idx_h = np.searchsorted(all_ids, ids_h)
        idx_a = np.searchsorted(all_ids, ids_a)

        freq_human = np.zeros(all_ids.size, dtype=np.float64)
        freq_ai = np.zeros(all_ids.size, dtype=np.float64)
        chi2_cell_human = np.zeros(all_ids.size, dtype=np.float64)
        chi2_cell_ai = np.zeros(all_ids.size, dtype=np.float64)

        freq_human[idx_h] = obs_h
        chi2_cell_human[idx_h] = chi2_cell_h
        freq_ai[idx_a] = obs_a
        chi2_cell_ai[idx_a] = chi2_cell_a

        u_h = float(total_context_mass_arrays(seg_h_starts, seg_h_ends, seg_h_weights))
        u_a = float(total_context_mass_arrays(seg_a_starts, seg_a_ends, seg_a_weights))

        # Hardie (2014) Log Ratio with Haldane-Anscombe +0.5 smoothing. Instead of
        # a hardcoded +/-10.0 sentinel for one-sided collocates (which both lied
        # about the effect size AND sorted every hapax above genuine effects), we
        # add +0.5 to each observed count and the totals so a zero cell yields an
        # HONEST finite ratio whose magnitude scales with the surviving evidence:
        #   log_ratio = log2( ((a+0.5)/(n1+0.5)) / ((b+0.5)/(n2+0.5)) )
        # with a=freq_human, b=freq_ai, n1=u_h, n2=u_a (context masses).
        a = freq_human
        b = freq_ai
        n1 = u_h if u_h > 0 else 0.0
        n2 = u_a if u_a > 0 else 0.0
        rel_h = (a + 0.5) / (n1 + 0.5)
        rel_a = (b + 0.5) / (n2 + 0.5)
        log_ratio = np.log2(rel_h / rel_a)

        # Flag collocates present on only one side so downstream can mark them as
        # "one-sided" instead of treating the smoothed ratio as a two-sided effect.
        one_sided = (a == 0) | (b == 0)

        words = self.lexicons.word.get_strings_for_ids(all_ids)

        rows = pd.DataFrame({
            "word": words,
            "freq_target": freq_human,
            "freq_reference": freq_ai,
            "chi2_cell_target": np.round(chi2_cell_human, 2),
            "chi2_cell_reference": np.round(chi2_cell_ai, 2),
            "log_ratio": np.round(log_ratio, 2),
            "one_sided": one_sided,
        })

        # Sort so one-sided hapaxes do NOT dominate. Primary key is |log_ratio|
        # descending, but the smoothed ratio of a 1-vs-0 hapax can still be large;
        # we therefore (1) apply a min_count floor on the larger side BEFORE
        # ranking (5000-vs-0 survives, 1-vs-0 is dropped) and (2) keep a fully
        # deterministic tiebreak chain (-|log_ratio|, -max(freq), word) via a
        # stable np.lexsort so the truncated slice is identical across runs.
        max_freq = np.maximum(
            rows["freq_target"].to_numpy(), rows["freq_reference"].to_numpy()
        )
        min_count = 5
        keep = max_freq >= min_count
        if np.any(keep):
            rows = rows.loc[keep].reset_index(drop=True)
            max_freq = max_freq[keep]
        abs_log = rows["log_ratio"].abs().to_numpy()
        words_arr = rows["word"].to_numpy()
        # np.lexsort sorts by the LAST key first; list keys in increasing priority.
        # Primary key (|log_ratio| desc) must be the last entry.
        order = np.lexsort((words_arr, -max_freq, -abs_log))
        rows = rows.iloc[order].reset_index(drop=True)
        rows = rows.head(top_n * 2) if top_n else rows
        # THE DENOMINATORS, which are already computed here.
        #
        # Without the context masses a contrast names neither direction nor
        # denominator, and freq_target=122 against freq_reference=0 is
        # neither a rate nor a ratio but two numbers without reference.
        #
        # No new computation: u_h and u_a are computed above, and so are the
        # anchor counts. Only an output field for work already paid for.
        rows.attrs["node_frequency_target"] = int(anchors_h.size)
        rows.attrs["node_frequency_reference"] = int(anchors_a.size)
        rows.attrs["context_mass_target"] = int(u_h)
        rows.attrs["context_mass_reference"] = int(u_a)
        return rows


# Global engine cache for integration.
#
# Keyed on the index path AND an artifact-mtime signature: keying on the path
# string alone serves a STALE engine after an in-place index rebuild (same
# path, new content) until the process restarts. The signature mirrors the
# backend's ``server._corpus_cache_signature`` approach (newest mtime_ns of a
# few representative index artifacts) and is shared with the CQLHPC engine cache
# via :mod:`candyconc.core.index_signature` (imported at module top as
# ``_index_artifact_signature`` / ``_ENGINE_SIG_ARTIFACTS``) so the two caches
# cannot drift.
_ENGINE_CACHE: "OrderedDict[str, Tuple[int, CollocationEngine]]" = OrderedDict()
_ENGINE_CACHE_MAX = 4
# Guards every mutation/lookup of ``_ENGINE_CACHE`` so concurrent get_engine /
# clear_engine_cache calls cannot corrupt the OrderedDict or evict a half-built
# entry. RLock so a future nested call from inside the lock stays safe.
_ENGINE_CACHE_LOCK = threading.RLock()


def get_engine(index_path: Optional[Path] = None) -> CollocationEngine:
    """Get or create a cached engine instance for ``index_path``.

    The cache entry is invalidated (stale instance evicted) when the artifact
    signature of the index directory changes, so an in-place rebuild gets a
    fresh engine without a process restart. ``index_path=None`` returns the
    most recently used engine (legacy singleton behaviour).
    """
    if index_path is None:
        with _ENGINE_CACHE_LOCK:
            if not _ENGINE_CACHE:
                raise ValueError("index_path required for first initialization")
            key = next(reversed(_ENGINE_CACHE))
            return _ENGINE_CACHE[key][1]
    path = Path(index_path)
    key = str(path)
    signature = _index_artifact_signature(path)
    with _ENGINE_CACHE_LOCK:
        cached = _ENGINE_CACHE.get(key)
        if cached is not None and cached[0] == signature:
            _ENGINE_CACHE.move_to_end(key)
            return cached[1]
    # Build OUTSIDE the lock so a slow engine construction does not block other
    # index paths; a concurrent build of the same key is acceptable (last writer
    # wins, both instances are equivalent).
    engine = CollocationEngine(path)
    with _ENGINE_CACHE_LOCK:
        _ENGINE_CACHE[key] = (signature, engine)
        _ENGINE_CACHE.move_to_end(key)
        while len(_ENGINE_CACHE) > _ENGINE_CACHE_MAX:
            _ENGINE_CACHE.popitem(last=False)
    return engine


def clear_engine_cache() -> None:
    """Drop all cached collocation engines.

    Wired into ``server.reset_default_corpus_runtime_state`` so an in-place
    rebuild or corpus reactivation cannot serve a stale engine. Safe to call
    concurrently with :func:`get_engine`.
    """
    with _ENGINE_CACHE_LOCK:
        _ENGINE_CACHE.clear()


def collocate_stats_fast(
    term: str,
    window: int = 5,
    corpus_path: Optional[Path] = None,
    top_n: Optional[int] = None,
    within_sentence: bool = False,
    cache_dir: Optional[Path] = None,
    cache_mode: str = "readwrite",
    attr: str = "word",
    term_id: Optional[int] = None,
    docset_mask: Optional[np.ndarray] = None,
    min_count: int = 5,
) -> pd.DataFrame:
    """
    Convenience function for fast collocation calculation.

    This is the main entry point for the new high-performance engine.
    """
    if corpus_path is None:
        raise ValueError("corpus_path required for fast collocation engine")

    engine = get_engine(corpus_path)
    return engine.collocate_stats(
        term=term,
        window_left=window,
        window_right=window,
        within_sentence=within_sentence,
        top_n=top_n,
        cache_dir=cache_dir,
        cache_mode=cache_mode,
        attr=attr,
        term_id=term_id,
        docset_mask=docset_mask,
        min_count=min_count,
    )
