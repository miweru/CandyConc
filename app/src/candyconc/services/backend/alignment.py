"""Sentence alignment and reference-document pair resolution.

Load sentence vectors only when an alignment call needs them. Shared
reference-document caches retain object identity across server, system
routes and tool callers. Keep this module independent of server and route
imports so the server can re-export its helpers without a cycle."""

from dataclasses import dataclass
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from candyconc.config import get as get_config
from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.pairing import is_anchor
from candyconc.entrypoints.errors import ApiError
from candyconc.i18n import lt

from .doc_meta import _doc_count_for_index
from .lru_maps import mark_lru_used, trim_lru_cache


@dataclass(frozen=True)
class SentenceData:
    index: int
    start_pos: int
    end_pos: int
    text: str
    tokens: list[str]


_REFDOC_INDEX_CACHE: dict[str, dict[int, list[int]]] = OrderedDict()
_REFDOC_INDEX_DOC_COUNT: dict[str, int] = OrderedDict()
_REFDOC_INDEX_CACHE_LIMIT = 16
_ALIGNMENT_MAX_EDIT_CELLS = 12_000_000
# Token edit distance is useful for proposing a sequence alignment, but it is
# not enough evidence to assert that two substantially different sentences are
# counterparts.  The presentation layer turns weaker proposals into two gaps.
_ALIGNMENT_MIN_CONFIDENT_SIMILARITY = 0.50
_ALIGNMENT_MIN_SHARED_TOKENS = 3


def _refdoc_index_cache_limit() -> int:
    try:
        raw = get_config("CANDYCONC_REFDOC_INDEX_CACHE_SIZE", str(_REFDOC_INDEX_CACHE_LIMIT))
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _REFDOC_INDEX_CACHE_LIMIT


def _mark_refdoc_index_used(corpus: str) -> None:
    for cache in (_REFDOC_INDEX_CACHE, _REFDOC_INDEX_DOC_COUNT):
        mark_lru_used(cache, corpus)


def _alignment_edit_cell_limit() -> int:
    """Return a bounded cost budget for complete token edit distances."""
    try:
        raw = get_config("CANDYCONC_ALIGNMENT_MAX_EDIT_CELLS", str(_ALIGNMENT_MAX_EDIT_CELLS))
        return max(1, int(raw))
    except (TypeError, ValueError):
        return _ALIGNMENT_MAX_EDIT_CELLS


def _trim_refdoc_index_cache() -> None:
    trim_lru_cache(
        _REFDOC_INDEX_CACHE,
        _refdoc_index_cache_limit(),
        on_evict=lambda corpus, _mapping: _REFDOC_INDEX_DOC_COUNT.pop(corpus, None),
    )


try:  # optional fast path
    from rapidfuzz.distance import Levenshtein as _RF_LEV  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _RF_LEV = None
try:  # optional fast path
    from candyconc.core.counting_kernels import levenshtein_tokens_fast_safe as _LEV_FAST  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _LEV_FAST = None


def _normalize_tokens(tokens: Sequence[str]) -> list[str]:
    """Normalise the complete sentence token sequence for exact edit scores."""
    return [str(token).lower() for token in tokens if token]


def _levenshtein_tokens_norm(a: Sequence[str], b: Sequence[str]) -> int:
    if _LEV_FAST is not None:
        try:
            return int(_LEV_FAST(list(a), list(b)))
        except Exception:
            pass
    if _RF_LEV is not None:
        try:
            return int(_RF_LEV.distance(a, b))
        except Exception:
            pass
    n = len(a)
    m = len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = i
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
        prev, curr = curr, prev
    return int(prev[m])


def _levenshtein_tokens(a_tokens: Sequence[str], b_tokens: Sequence[str]) -> int:
    a = _normalize_tokens(a_tokens)
    b = _normalize_tokens(b_tokens)
    return _levenshtein_tokens_norm(a, b)


def _normalized_med_norm(a_norm: Sequence[str], b_norm: Sequence[str], len_a: int, len_b: int) -> tuple[int, float, float]:
    med = _levenshtein_tokens_norm(a_norm, b_norm)
    denom = max(len_a, len_b, 1)
    norm = float(med) / float(denom)
    norm = min(norm, 2.0)
    similarity = max(0.0, 1.0 - min(norm, 1.0))
    return int(med), float(norm), float(similarity)


def _normalized_med(
    a_tokens: Sequence[str],
    b_tokens: Sequence[str],
) -> tuple[int, float, float]:
    a_norm = _normalize_tokens(a_tokens)
    b_norm = _normalize_tokens(b_tokens)
    return _normalized_med_norm(
        a_norm,
        b_norm,
        len(a_norm),
        len(b_norm),
    )


def _lexical_overlap_similarity(
    a_norm: Sequence[str],
    b_norm: Sequence[str],
) -> tuple[float, int]:
    """Return multiset token-F1 for a sentence pair and its evidence count.

    Token edit distance is sensitive to reordered clauses.  The overlap score
    supplies evidence for that common paraphrase case without pretending that
    two sentences are semantically equivalent.  Punctuation never contributes
    and a score based on fewer than three shared lexical tokens is not used to
    promote a candidate above the edit-distance evidence.
    """
    a_counts = Counter(token for token in a_norm if any(char.isalnum() for char in token))
    b_counts = Counter(token for token in b_norm if any(char.isalnum() for char in token))
    if not a_counts or not b_counts:
        return 0.0, 0
    shared = int(sum((a_counts & b_counts).values()))
    denominator = sum(a_counts.values()) + sum(b_counts.values())
    if denominator <= 0:
        return 0.0, shared
    return float((2.0 * shared) / denominator), shared


def _edit_similarity_with_overlap(
    a_norm: Sequence[str],
    b_norm: Sequence[str],
    edit_similarity: float,
) -> float:
    """The sentence-pair similarity of the ``edit`` method, in ONE place.

    Edit similarity, raised by the lexical overlap once at least
    ``_ALIGNMENT_MIN_SHARED_TOKENS`` words are shared. This is the score
    ``_conservative_alignment_pairs`` holds against its threshold, and parallel
    KWIC (``_best_matching_sentence``) presents a counterpart by the same rule
    as the document alignment.
    """
    overlap_similarity, shared_tokens = _lexical_overlap_similarity(a_norm, b_norm)
    if shared_tokens >= _ALIGNMENT_MIN_SHARED_TOKENS:
        return max(float(edit_similarity), overlap_similarity)
    return float(edit_similarity)


def _alignment_token_limit_not_applicable(
    *,
    max_tokens: int,
    observed_tokens: int,
) -> dict[str, Any]:
    """Refuse a bounded request rather than publish a prefix-based score."""
    return {
        "status": "not_applicable",
        "reason": "sentence_token_limit_exceeded",
        "detail": lt(
            "Die Satz-Ausrichtung berechnet Edit-Distanzen vollständig und kürzt "
            "keine Satzenden. Ein Satz enthält {observed_tokens} Tokens, das "
            "angefragte exakte Limit beträgt jedoch {max_tokens}.",
            "Sentence alignment computes complete edit distances and does not "
            "truncate sentence ends. A sentence contains {observed_tokens} tokens, "
            "but the requested exact limit is {max_tokens}.",
        ).format(observed_tokens=observed_tokens, max_tokens=max_tokens),
        "max_tokens": int(max_tokens),
        "observed_tokens": int(observed_tokens),
    }


def _alignment_edit_cell_count(
    ref_sents: Sequence[SentenceData],
    var_sents: Sequence[SentenceData],
) -> int:
    """Estimate the exact dynamic-programming work for one sentence window.

    This is deliberately based on complete normalized sentence lengths.  It is a
    preflight availability check, not an approximation used in the score itself.
    """
    ref_lengths = [len(_normalize_tokens(sentence.tokens)) for sentence in ref_sents]
    var_lengths = [len(_normalize_tokens(sentence.tokens)) for sentence in var_sents]
    return int(sum(ref_len * var_len for ref_len in ref_lengths for var_len in var_lengths))


def _conservative_alignment_pairs(
    pairs: Sequence[Mapping[str, Any]],
    *,
    minimum_similarity: float = _ALIGNMENT_MIN_CONFIDENT_SIMILARITY,
) -> list[dict[str, Any]]:
    """Keep only textually supported sentence correspondences as pairs.

    The sequence DP is deliberately retained: it preserves the order needed to
    place additions and omissions.  A low lexical similarity is nevertheless
    not sufficient evidence for a researcher-facing "sentence counterpart".
    Such a proposal is rendered as one reference-only and one variant-only row
    instead of a plausible-looking token diff.
    """
    result: list[dict[str, Any]] = []
    threshold = max(0.0, min(float(minimum_similarity), 1.0))
    for raw_pair in pairs:
        pair = dict(raw_pair)
        is_candidate = (
            pair.get("ref_index") is not None
            and pair.get("var_index") is not None
        )
        similarity = pair.get("similarity")
        is_confident = (
            is_candidate
            and isinstance(similarity, (int, float))
            and float(similarity) >= threshold
        )
        if not is_candidate or is_confident:
            result.append(pair)
            continue

        result.append({
            "ref_index": pair.get("ref_index"),
            "var_index": None,
            "ref_text": pair.get("ref_text") or "",
            "var_text": "",
            "ref_start": pair.get("ref_start"),
            "ref_end": pair.get("ref_end"),
            "var_start": None,
            "var_end": None,
            "med": None,
            "similarity": None,
            "norm_med": None,
        })
        result.append({
            "ref_index": None,
            "var_index": pair.get("var_index"),
            "ref_text": "",
            "var_text": pair.get("var_text") or "",
            "ref_start": None,
            "ref_end": None,
            "var_start": pair.get("var_start"),
            "var_end": pair.get("var_end"),
            "med": None,
            "similarity": None,
            "norm_med": None,
        })
    return result


def _alignment_summary_from_pairs(
    pairs: Sequence[Mapping[str, Any]],
    *,
    alignment_cost: float,
) -> dict[str, Any]:
    """Summarise only correspondence pairs that survived the evidence policy."""
    aligned = [
        pair for pair in pairs
        if pair.get("ref_index") is not None and pair.get("var_index") is not None
    ]
    med_values = [pair.get("med") for pair in aligned if isinstance(pair.get("med"), (int, float))]
    sim_values = [
        pair.get("similarity")
        for pair in aligned
        if isinstance(pair.get("similarity"), (int, float))
    ]
    return {
        "alignment_cost": float(alignment_cost),
        "aligned_pairs": int(len(aligned)),
        "avg_med": float(np.mean(med_values)) if med_values else None,
        "avg_similarity": float(np.mean(sim_values)) if sim_values else None,
    }


def _alignment_budget_not_applicable(
    *,
    edit_cells: int,
    max_edit_cells: int,
    variant_count: int | None = None,
) -> dict[str, Any]:
    """Refuse a too-expensive alignment without weakening its methodology."""
    detail = lt(
        "Die Satz-Ausrichtung würde vollständige Edit-Distanzen über "
        "{edit_cells:,} Tokenpaare berechnen; das konfigurierte Rechenbudget "
        "beträgt {max_edit_cells:,}. Es wurde keine verkürzte oder partielle "
        "Ausrichtung erzeugt. Verkleinere das Satzfenster oder wähle weniger Varianten.",
        "Sentence alignment would compute complete edit distances over "
        "{edit_cells:,} token pairs. The configured compute budget is "
        "{max_edit_cells:,}. No shortened or partial alignment was produced. "
        "Reduce the sentence window or choose fewer variants.",
    ).format(edit_cells=edit_cells, max_edit_cells=max_edit_cells)
    result: dict[str, Any] = {
        "status": "not_applicable",
        "reason": "exact_alignment_budget_exceeded",
        "detail": detail,
        "edit_cells": int(edit_cells),
        "max_edit_cells": int(max_edit_cells),
    }
    if variant_count is not None:
        result["variant_count"] = int(variant_count)
    return result


# Alignment methods the endpoint understands. ``edit`` combines complete token
# edit distance with sufficiently evidenced lexical overlap, so reordered
# paraphrases do not force an unrelated one-to-one sentence chain. ``embed`` /
# ``hybrid`` require per-sentence embeddings keyed by
# token_start_pos which no current index ships (a separate re-ingest prereq).
_ALIGNMENT_METHODS = ("edit", "embed", "hybrid")


def _sentence_embeddings_available(idx: Optional[CorpusIndex]) -> bool:
    """True only when the index exposes the (not-yet-built) sentence-embedding
    capability. Always False on current indices — the ``sentence_embeddings``
    capability maps to an artifact no builder produces yet (see index_format)."""
    if idx is None:
        return False
    caps = getattr(idx, "capabilities", None)
    if isinstance(caps, dict):
        return bool(caps.get("sentence_embeddings", False))
    manifest = getattr(idx, "manifest", None)
    mcaps = getattr(manifest, "capabilities", None)
    if isinstance(mcaps, dict):
        return bool(mcaps.get("sentence_embeddings", False))
    return False


def _alignment_not_applicable(method: str) -> dict[str, Any]:
    """Graceful envelope returned when an embedding-backed alignment method is
    requested but the prerequisite sentence embeddings are not built."""
    return {
        "status": "not_applicable",
        "reason": "sentence_embeddings_unavailable",
        "detail": lt(
            "Alignment-Methode '{method}' benötigt Satz-Embeddings (keyed by "
            "token_start_pos), die in diesem Index nicht gebaut sind. Re-Ingest "
            "mit Satz-Embeddings nötig; bis dahin nur method='edit' verfügbar.",
            "Alignment method '{method}' needs sentence embeddings (keyed by "
            "token_start_pos) that are not built in this index. A re-import "
            "with sentence embeddings is required. Until then only method='edit' "
            "is available.",
        ).format(method=method),
        "alignment_method": method,
    }


def _load_sentence_vectors(idx: Optional[CorpusIndex]) -> Optional[dict[int, np.ndarray]]:
    """Load sentence embeddings keyed by token ``start_pos`` from the index artifact.

    Contract (STEP 9): a future re-ingest writes ``<index>/sentence_vecs.npy`` — an
    ``(N, d)`` float array — alongside ``<index>/sentence_vec_starts.npy`` — an
    ``(N,)`` int array of the sentences' token ``start_pos`` (matching
    :attr:`SentenceData.start_pos`). Returns ``{start_pos: vector}`` or ``None`` when
    the artifacts are absent (every current index). Never raises.
    """
    base = getattr(idx, "path", None) or getattr(idx, "index_path", None)
    if base is None:
        return None
    try:
        base = Path(base)
        vecs_f = base / "sentence_vecs.npy"
        starts_f = base / "sentence_vec_starts.npy"
        if not (vecs_f.exists() and starts_f.exists()):
            return None
        vecs = np.load(vecs_f)
        starts = np.load(starts_f)
        return {int(s): np.asarray(vecs[i], dtype=np.float64) for i, s in enumerate(starts)}
    except Exception:
        return None


def _embed_pair_cost(
    vec_map: dict[int, np.ndarray], a_start: int, b_start: int
) -> tuple[float, float, bool]:
    """Cosine-based cost/similarity for one sentence pair, keyed by start_pos.

    Returns ``(cost, sim, ok)`` where ``cost`` and ``sim`` are normalised to ``[0,1]``
    (cost = ``(1-cos)/2``, on the same scale as the edit-distance ``norm`` so the DP
    gap_cost stays comparable). ``ok`` is False when either vector is missing or
    zero-norm, so callers fall back to the edit cost for that cell.
    """
    va = vec_map.get(int(a_start))
    vb = vec_map.get(int(b_start))
    if va is None or vb is None:
        return 0.0, 0.0, False
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0, 0.0, False
    cos = float(np.dot(va, vb) / (na * nb))
    cos = max(-1.0, min(1.0, cos))
    return (1.0 - cos) / 2.0, (cos + 1.0) / 2.0, True


def _align_sentence_lists(
    ref_sents: Sequence[SentenceData],
    var_sents: Sequence[SentenceData],
    *,
    gap_cost: float = 1.0,
    max_tokens: int = 512,
    method: str = "edit",
    idx: Optional[CorpusIndex] = None,
    sentence_vectors: Optional[Mapping[int, Any]] = None,
    max_edit_cells: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # STEP 9: additive method dispatch. ``method="edit"`` (the default) uses
    # full sentence token sequences; max_tokens is an honest availability guard,
    # never a prefix truncation that could turn a partial match into 100 %.
    # ``embed``/``hybrid`` source the cell cost from sentence embeddings (cosine);
    # ``sentence_vectors`` may be injected (tests / callers) to bypass disk loading.
    method = (method or "edit").lower()
    if method not in _ALIGNMENT_METHODS:
        raise ApiError(
            400,
            "alignment.method_unknown",
            lt("Unbekannte Alignment-Methode: {method!r}", "Unknown alignment method: {method!r}"),
            method=method,
        )
    vec_map: Optional[dict[int, np.ndarray]] = None
    if method in ("embed", "hybrid"):
        if sentence_vectors is not None:
            vec_map = {int(k): np.asarray(v, dtype=np.float64) for k, v in sentence_vectors.items()}
        elif _sentence_embeddings_available(idx):
            vec_map = _load_sentence_vectors(idx)
        if not vec_map:
            # No silent fallback to edit — surface the gap explicitly so the caller
            # can choose to render a not_applicable envelope.
            return [], _alignment_not_applicable(method)

    n = len(ref_sents)
    m = len(var_sents)
    if n == 0 and m == 0:
        return [], {"alignment_cost": 0.0, "aligned_pairs": 0}

    safe_max_tokens = max(1, int(max_tokens))
    observed_tokens = max(
        (len(sentence.tokens or []) for sentence in [*ref_sents, *var_sents]),
        default=0,
    )
    if observed_tokens > safe_max_tokens:
        return [], _alignment_token_limit_not_applicable(
            max_tokens=safe_max_tokens,
            observed_tokens=observed_tokens,
        )

    # Computing all sentence-pair costs is required for a complete global
    # alignment.  When it exceeds the explicit budget, refuse the request rather
    # than use prefixes, sample pairs, or return a plausible-looking subset.
    safe_max_edit_cells = (
        _alignment_edit_cell_limit() if max_edit_cells is None else max(1, int(max_edit_cells))
    )
    edit_cells = _alignment_edit_cell_count(ref_sents, var_sents)
    if edit_cells > safe_max_edit_cells:
        return [], _alignment_budget_not_applicable(
            edit_cells=edit_cells,
            max_edit_cells=safe_max_edit_cells,
        )

    costs = np.zeros((n, m), dtype=np.float64)
    edit_norms = np.zeros((n, m), dtype=np.float64)
    meds = np.zeros((n, m), dtype=np.int32)
    sims = np.zeros((n, m), dtype=np.float64)
    ref_norm = [_normalize_tokens(rs.tokens) for rs in ref_sents]
    var_norm = [_normalize_tokens(vs.tokens) for vs in var_sents]
    ref_lens = [len(tokens) for tokens in ref_norm]
    var_lens = [len(tokens) for tokens in var_norm]
    for i in range(n):
        a_norm = ref_norm[i]
        len_a = ref_lens[i]
        for j in range(m):
            med, edit_norm, edit_similarity = _normalized_med_norm(
                a_norm,
                var_norm[j],
                len_a,
                var_lens[j],
            )
            norm = edit_norm
            sim = edit_similarity
            if method == "edit":
                sim = _edit_similarity_with_overlap(a_norm, var_norm[j], sim)
                # A weak lexical proposal should lose to two explicit gaps.
                # Otherwise a global DP can preserve sentence order by pairing
                # unrelated text, which looks like a legitimate counterpart in
                # a research-facing comparison.
                norm = (
                    1.0 - sim
                    if sim >= _ALIGNMENT_MIN_CONFIDENT_SIMILARITY
                    else (2.0 * float(gap_cost)) + 1e-6
                )
            if method != "edit" and vec_map is not None:
                # embed: replace cost with cosine distance; hybrid: blend 50/50 with edit.
                e_cost, e_sim, ok = _embed_pair_cost(
                    vec_map, ref_sents[i].start_pos, var_sents[j].start_pos
                )
                if ok:
                    if method == "embed":
                        norm, sim, med = e_cost, e_sim, -1
                    else:  # hybrid
                        norm = 0.5 * norm + 0.5 * e_cost
                        sim = 0.5 * sim + 0.5 * e_sim
            costs[i, j] = norm
            edit_norms[i, j] = edit_norm
            meds[i, j] = med
            sims[i, j] = sim

    dp = np.zeros((n + 1, m + 1), dtype=np.float64)
    back = np.zeros((n + 1, m + 1), dtype=np.int8)
    for i in range(1, n + 1):
        dp[i, 0] = dp[i - 1, 0] + float(gap_cost)
        back[i, 0] = 1
    for j in range(1, m + 1):
        dp[0, j] = dp[0, j - 1] + float(gap_cost)
        back[0, j] = 2

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1, j - 1] + costs[i - 1, j - 1]
            up = dp[i - 1, j] + float(gap_cost)
            left = dp[i, j - 1] + float(gap_cost)
            best = diag
            direction: int = 0
            if up < best:
                best = up
                direction = 1
            if left < best:
                best = left
                direction = 2
            dp[i, j] = best
            back[i, j] = direction

    pairs_rev: list[dict[str, Any]] = []
    i = n
    j = m
    while i > 0 or j > 0:
        direction = int(back[i, j])
        if i > 0 and j > 0 and direction == 0:
            i -= 1
            j -= 1
            rs = ref_sents[i]
            vs = var_sents[j]
            pairs_rev.append(
                {
                    "ref_index": rs.index,
                    "var_index": vs.index,
                    "ref_text": rs.text,
                    "var_text": vs.text,
                    "ref_start": rs.start_pos,
                    "ref_end": rs.end_pos,
                    "var_start": vs.start_pos,
                    "var_end": vs.end_pos,
                    "med": int(meds[i, j]),
                    "similarity": float(sims[i, j]),
                    "norm_med": float(edit_norms[i, j]),
                }
            )
            continue
        if i > 0 and (j == 0 or direction == 1):
            i -= 1
            rs = ref_sents[i]
            pairs_rev.append(
                {
                    "ref_index": rs.index,
                    "var_index": None,
                    "ref_text": rs.text,
                    "var_text": "",
                    "ref_start": rs.start_pos,
                    "ref_end": rs.end_pos,
                    "var_start": None,
                    "var_end": None,
                    "med": None,
                    "similarity": None,
                    "norm_med": None,
                }
            )
            continue
        if j > 0:
            j -= 1
            vs = var_sents[j]
            pairs_rev.append(
                {
                    "ref_index": None,
                    "var_index": vs.index,
                    "ref_text": "",
                    "var_text": vs.text,
                    "ref_start": None,
                    "ref_end": None,
                    "var_start": vs.start_pos,
                    "var_end": vs.end_pos,
                    "med": None,
                    "similarity": None,
                    "norm_med": None,
                }
            )

    pairs = list(reversed(pairs_rev))
    aligned = [p for p in pairs if p.get("ref_index") is not None and p.get("var_index") is not None]
    avg_med = float(np.mean([p["med"] for p in aligned])) if aligned else None
    avg_sim = float(np.mean([p["similarity"] for p in aligned])) if aligned else None
    summary = {
        "alignment_cost": float(dp[n, m]),
        "aligned_pairs": int(len(aligned)),
        "avg_med": avg_med,
        "avg_similarity": avg_sim,
    }
    return pairs, summary


def _refdoc_index_for_corpus(idx: CorpusIndex, corpus: str) -> dict[int, list[int]]:
    doc_count = _doc_count_for_index(idx)
    cached = _REFDOC_INDEX_CACHE.get(corpus)
    cached_count = _REFDOC_INDEX_DOC_COUNT.get(corpus)
    if cached is not None and cached_count == int(doc_count):
        _mark_refdoc_index_used(corpus)
        return cached

    mapping: dict[int, list[int]] = {}
    meta = idx.fast_index.doc_metadata or {}
    for raw_doc_id, raw_meta in meta.items():
        try:
            doc_id = int(raw_doc_id)
        except Exception:
            continue
        if not isinstance(raw_meta, dict):
            continue
        text_type = raw_meta.get("text_type")
        ref_doc = raw_meta.get("ref_doc")
        if isinstance(ref_doc, str) and ref_doc.isdigit():
            ref_doc = int(ref_doc)
        if isinstance(ref_doc, int):
            mapping.setdefault(int(ref_doc), []).append(doc_id)
            continue
        if is_anchor(text_type):
            mapping.setdefault(doc_id, []).append(doc_id)

    _REFDOC_INDEX_CACHE[corpus] = mapping
    _REFDOC_INDEX_DOC_COUNT[corpus] = int(doc_count)
    _mark_refdoc_index_used(corpus)
    _trim_refdoc_index_cache()
    return mapping


def resolve_pair_groups(
    idx: CorpusIndex,
    corpus: str,
    *,
    axis: Optional[str] = None,
    anchor_role: Optional[str] = None,  # noqa: ARG001 — forwarded by callers, used downstream
) -> dict[Any, list[int]]:
    """Generalised pairing seam.

    ``axis=None`` reproduces the ``ref_doc`` grouping of paired human and AI
    corpora byte-identically (guarded by the refdoc golden test
    ``test_refdoc_mapping_golden``). It delegates to
    :func:`_refdoc_index_for_corpus` and returns ``{ref_doc: [doc_ids]}``
    (int keys).

    ``axis="<metadata-field>"`` (e.g. ``"model"`` for model-vs-model, ``"register"``)
    groups documents by that field's distinct values, returning ``{value: [doc_ids]}``
    (str keys, doc_ids sorted) — the substrate for a free contrast along any metadata
    axis. The field must exist in the corpus metadata, otherwise a 400 is raised (so an
    unknown axis fails loudly rather than silently returning nothing).
    """
    if axis is None:
        return _refdoc_index_for_corpus(idx, corpus)

    field = str(axis)
    fields = idx.metadata_fields() if hasattr(idx, "metadata_fields") else []
    if field not in set(fields):
        raise ApiError(
            400,
            "pairing.axis_unknown",
            lt("Unbekannte Pairing-Achse: {axis!r}", "Unknown pairing axis: {axis!r}"),
            axis=axis,
        )

    meta = idx.fast_index.doc_metadata or {}
    groups: dict[Any, list[int]] = {}
    for raw_doc_id, raw_meta in meta.items():
        try:
            doc_id = int(raw_doc_id)
        except Exception:
            continue
        if not isinstance(raw_meta, dict):
            continue
        value = raw_meta.get(field)
        if value is None:
            continue
        groups.setdefault(str(value), []).append(doc_id)
    for doc_ids in groups.values():
        doc_ids.sort()
    return groups
