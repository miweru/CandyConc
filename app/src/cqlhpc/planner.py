from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .corpus import Corpus
from .config import get_int, get_float, get_bool

@dataclass(frozen=True, slots=True)
class ClauseStats:
    idx: int
    est_len: int
    attr: Optional[str]
    type_ids: Optional[np.ndarray]
    materialized_len: Optional[int] = None
    doc_freq: Optional[int] = None
    sent_freq: Optional[int] = None

    @property
    def effective_len(self) -> int:
        if self.materialized_len is not None:
            return int(self.materialized_len)
        return int(self.est_len)


@dataclass(frozen=True, slots=True)
class ClausePlan:
    idx: int
    method: str  # "merge" or "bitset"
    est_cost: float


@dataclass(frozen=True, slots=True)
class SequencePlan:
    anchor_idx: int
    ordered: Tuple[ClausePlan, ...]
    total_cost: float
    strategy: str = "global"  # global | partitioned | hybrid
    notes: Tuple[str, ...] = ()


def _docset_selectivity(docset_mask: Optional[np.ndarray], corpus: Corpus) -> float:
    if docset_mask is None:
        return 1.0
    if docset_mask.size == 0:
        return 0.0
    n_docs = int(corpus.doc_starts.shape[0])
    if n_docs <= 0:
        return 1.0
    allowed = int(np.count_nonzero(docset_mask))
    return max(0.0, min(1.0, allowed / float(n_docs)))


def _estimate_merge_cost(anchor_len: int, clause_len: int) -> float:
    # Two-pointer style: roughly proportional to sum of list lengths.
    return float(anchor_len + clause_len)


def _estimate_bitset_cost(anchor_len: int, clause_len: int) -> float:
    # Bitset build ~ postings length; filter ~ anchor length.
    build_weight = get_float("CANDYCONC_CQLHPC_BITSET_BUILD_WEIGHT", 1.0)
    filter_weight = get_float("CANDYCONC_CQLHPC_BITSET_FILTER_WEIGHT", 1.0)
    return float(clause_len * build_weight + anchor_len * filter_weight)


def _should_use_bitset(clause_len: int, n_tokens: int, has_dense: bool = False) -> bool:
    if has_dense:
        return True
    if n_tokens <= 0:
        return False
    density = clause_len / float(n_tokens)
    dens_thresh = get_float("CANDYCONC_CQLHPC_BITSET_DENSITY", 0.02)
    if density >= dens_thresh:
        return True
    hard = get_int("CANDYCONC_CQLHPC_BITSET_THRESHOLD", 0)
    return hard > 0 and clause_len >= hard


def _docset_count_for_types(
    corpus: Corpus, attr: Optional[str], type_ids: Optional[np.ndarray]
) -> Optional[int]:
    if attr is None or type_ids is None or type_ids.size == 0:
        return None
    if not hasattr(corpus, "docset_index"):
        return None
    try:
        docset_index = corpus.docset_index(attr)  # type: ignore[call-arg]
    except Exception:
        return None
    if docset_index is None:
        return None
    n_docs = int(getattr(corpus, "doc_starts", np.zeros(0)).shape[0])
    if n_docs <= 0:
        return None
    # Approximate union size using independence assumption.
    try:
        counts = docset_index.counts()
        vals = counts[type_ids.astype(np.int64, copy=False)]
        if vals.size == 0:
            return 0
        p_not = float(np.prod(1.0 - (vals / float(n_docs))))
    except Exception:
        p_not = 1.0
        for tid in type_ids.tolist():
            c = docset_index.count_for(int(tid))
            if c <= 0:
                continue
            p_not *= max(0.0, 1.0 - (c / float(n_docs)))
    est = int(round(n_docs * (1.0 - p_not)))
    if est < 0:
        est = 0
    if est > n_docs:
        est = n_docs
    return est


def _pos_sentence_count(
    corpus: Corpus, attr: Optional[str], type_ids: Optional[np.ndarray]
) -> Optional[int]:
    if attr != "pos" or type_ids is None or type_ids.size == 0:
        return None
    if not hasattr(corpus, "pos_sentence_index"):
        return None
    try:
        pos_sentence = corpus.pos_sentence_index()  # type: ignore[call-arg]
    except Exception:
        return None
    if pos_sentence is None:
        return None
    n_sents = int(getattr(corpus, "sent_starts", np.zeros(0)).shape[0])
    if n_sents <= 0:
        return None
    try:
        counts = pos_sentence.counts()
        vals = counts[type_ids.astype(np.int64, copy=False)]
        if vals.size == 0:
            return 0
        p_not = float(np.prod(1.0 - (vals / float(n_sents))))
    except Exception:
        p_not = 1.0
        for tid in type_ids.tolist():
            c = pos_sentence.count_for(int(tid))
            if c <= 0:
                continue
            p_not *= max(0.0, 1.0 - (c / float(n_sents)))
    est = int(round(n_sents * (1.0 - p_not)))
    if est < 0:
        est = 0
    if est > n_sents:
        est = n_sents
    return est


def _prepare_stats(
    node_simple: Sequence[Optional[Tuple[str, np.ndarray, int]]],
    pos_lists: Sequence[Optional[np.ndarray]],
    corpus: Corpus,
) -> List[ClauseStats]:
    stats: List[ClauseStats] = []
    for i, simple in enumerate(node_simple):
        if pos_lists[i] is not None:
            stats.append(
                ClauseStats(
                    idx=i,
                    est_len=int(pos_lists[i].size),
                    attr=None,
                    type_ids=None,
                    materialized_len=int(pos_lists[i].size),
                )
            )
            continue
        if simple is None:
            stats.append(ClauseStats(idx=i, est_len=0, attr=None, type_ids=None))
            continue
        attr, tids, est = simple
        doc_freq = _docset_count_for_types(corpus, attr, tids)
        sent_freq = _pos_sentence_count(corpus, attr, tids)
        stats.append(
            ClauseStats(
                idx=i,
                est_len=int(est),
                attr=attr,
                type_ids=tids,
                doc_freq=doc_freq,
                sent_freq=sent_freq,
            )
        )
    return stats


def _has_dense_bitset(corpus: Corpus, attr: Optional[str], tids: Optional[np.ndarray]) -> bool:
    if attr is None or tids is None or tids.size != 1:
        return False
    if not hasattr(corpus, "dense_bitset_available"):
        return False
    try:
        return bool(corpus.dense_bitset_available(attr, int(tids[0])))  # type: ignore[call-arg]
    except Exception:
        return False


def _estimate_selectivity(
    clause_len: int,
    n_tokens: int,
    *,
    scope: Optional[str],
    doc_freq: Optional[int],
    sent_freq: Optional[int],
    n_docs: int,
    n_sents: int,
) -> float:
    if scope == "doc" and doc_freq is not None and n_docs > 0:
        return max(0.0, min(1.0, doc_freq / float(n_docs)))
    if scope == "s" and sent_freq is not None and n_sents > 0:
        return max(0.0, min(1.0, sent_freq / float(n_sents)))
    if n_tokens <= 0:
        return 1.0
    return max(0.0, min(1.0, clause_len / float(n_tokens)))


def _order_clauses_dp_python(
    stats: Sequence[ClauseStats],
    *,
    anchor_idx: int,
    n_tokens: int,
    scope: Optional[str],
    selectivity: float,
    n_docs: int,
    n_sents: int,
    corpus: Corpus,
) -> Tuple[Tuple[ClausePlan, ...], float]:
    # Selinger-style DP over clause ordering (small N).
    indices = [st.idx for st in stats if st.idx != anchor_idx]
    if not indices:
        return tuple(), 0.0
    dp_max = get_int("CANDYCONC_CQLHPC_DP_MAX", 8)
    dp_min_ratio = get_float("CANDYCONC_CQLHPC_DP_MIN_RATIO", 4.0)
    if len(indices) > dp_max:
        # fallback to greedy later
        return tuple(), -1.0
    if dp_min_ratio > 1.0:
        lengths = [stats[idx].effective_len for idx in indices]
        if lengths:
            mn = min(lengths)
            mx = max(lengths)
            if mn > 0 and (mx / float(mn)) >= dp_min_ratio:
                # Skipping DP when lengths are extremely skewed.
                return tuple(), -1.0

    idx_to_pos = {idx: pos for pos, idx in enumerate(indices)}
    n = len(indices)
    full_mask = (1 << n) - 1
    # Precompute per clause info
    clause_info: Dict[int, Dict[str, object]] = {}
    for st in stats:
        if st.idx == anchor_idx:
            continue
        clause_len = int(st.effective_len * selectivity)
        if clause_len < 0:
            clause_len = 0
        sel = _estimate_selectivity(
            clause_len,
            n_tokens,
            scope=scope,
            doc_freq=st.doc_freq,
            sent_freq=st.sent_freq,
            n_docs=n_docs,
            n_sents=n_sents,
        )
        has_dense = _has_dense_bitset(corpus, st.attr, st.type_ids)
        clause_info[st.idx] = {
            "len": clause_len,
            "sel": sel,
            "dense": has_dense,
        }

    dp_cost = np.full((1 << n,), np.inf, dtype=np.float64)
    dp_size = np.zeros((1 << n,), dtype=np.float64)
    back_idx = np.full((1 << n,), -1, dtype=np.int32)
    back_method: Dict[int, str] = {}
    back_step_cost: Dict[int, float] = {}

    # base: empty set, size = anchor_len
    anchor_len = float(stats[anchor_idx].effective_len)
    dp_cost[0] = 0.0
    dp_size[0] = anchor_len

    for mask in range(1 << n):
        base_cost = dp_cost[mask]
        if not np.isfinite(base_cost):
            continue
        cur_size = dp_size[mask]
        for idx in indices:
            bit = 1 << idx_to_pos[idx]
            if mask & bit:
                continue
            info = clause_info[idx]
            clause_len = float(info["len"])
            sel = float(info["sel"])
            has_dense = bool(info["dense"])
            # choose method by cheaper estimated cost at current size
            merge_cost = _estimate_merge_cost(int(cur_size), int(clause_len))
            if has_dense:
                build_weight = 0.0
            else:
                build_weight = get_float("CANDYCONC_CQLHPC_BITSET_BUILD_WEIGHT", 1.0)
            filter_weight = get_float("CANDYCONC_CQLHPC_BITSET_FILTER_WEIGHT", 1.0)
            bitset_cost = clause_len * build_weight + cur_size * filter_weight
            method = "bitset" if bitset_cost <= merge_cost else "merge"
            step_cost = bitset_cost if method == "bitset" else merge_cost
            new_mask = mask | bit
            new_cost = base_cost + step_cost
            new_size = cur_size * sel
            if new_size < 0:
                new_size = 0.0
            if new_cost < dp_cost[new_mask]:
                dp_cost[new_mask] = new_cost
                dp_size[new_mask] = new_size
                back_idx[new_mask] = idx
                back_method[new_mask] = method
                back_step_cost[new_mask] = float(step_cost)

    if not np.isfinite(dp_cost[full_mask]):
        return tuple(), -1.0

    # Reconstruct order
    order: List[ClausePlan] = []
    mask = full_mask
    while mask:
        idx = int(back_idx[mask])
        if idx < 0:
            break
        method = back_method.get(mask, "merge")
        step_cost = float(back_step_cost.get(mask, dp_cost[mask]))
        order.append(ClausePlan(idx=idx, method=method, est_cost=step_cost))
        bit = 1 << idx_to_pos[idx]
        mask &= ~bit
    order.reverse()
    return tuple(order), float(dp_cost[full_mask])


def _order_clauses_dp(
    stats: Sequence[ClauseStats],
    *,
    anchor_idx: int,
    n_tokens: int,
    scope: Optional[str],
    selectivity: float,
    n_docs: int,
    n_sents: int,
    corpus: Corpus,
) -> Tuple[Tuple[ClausePlan, ...], float]:
    indices = [st.idx for st in stats if st.idx != anchor_idx]
    if not indices:
        return tuple(), 0.0
    dp_max = get_int("CANDYCONC_CQLHPC_DP_MAX", 8)
    if len(indices) > dp_max:
        return tuple(), -1.0
    dp_min_ratio = get_float("CANDYCONC_CQLHPC_DP_MIN_RATIO", 4.0)
    lengths = [stats[idx].effective_len for idx in indices]
    if dp_min_ratio > 1.0 and lengths:
        mn = min(lengths)
        mx = max(lengths)
        if mn > 0 and (mx / float(mn)) >= dp_min_ratio:
            return tuple(), -1.0

    # try Cython DP if available
    try:
        from .cython._planner import dp_order as _cy_dp_order  # type: ignore
    except Exception:
        _cy_dp_order = None

    if _cy_dp_order is None:
        return _order_clauses_dp_python(
            stats,
            anchor_idx=anchor_idx,
            n_tokens=n_tokens,
            scope=scope,
            selectivity=selectivity,
            n_docs=n_docs,
            n_sents=n_sents,
            corpus=corpus,
        )

    # Prepare arrays for Cython
    clause_len = []
    clause_sel = []
    has_dense = []
    idx_map = []
    for st in stats:
        if st.idx == anchor_idx:
            continue
        clause_len_i = int(st.effective_len * selectivity)
        if clause_len_i < 0:
            clause_len_i = 0
        sel = _estimate_selectivity(
            clause_len_i,
            n_tokens,
            scope=scope,
            doc_freq=st.doc_freq,
            sent_freq=st.sent_freq,
            n_docs=n_docs,
            n_sents=n_sents,
        )
        idx_map.append(st.idx)
        clause_len.append(clause_len_i)
        clause_sel.append(sel)
        has_dense.append(1 if _has_dense_bitset(corpus, st.attr, st.type_ids) else 0)

    if not clause_len:
        return tuple(), 0.0

    bitset_build_weight = get_float("CANDYCONC_CQLHPC_BITSET_BUILD_WEIGHT", 1.0)
    bitset_filter_weight = get_float("CANDYCONC_CQLHPC_BITSET_FILTER_WEIGHT", 1.0)
    order_idx, methods, step_costs, total_cost = _cy_dp_order(
        int(stats[anchor_idx].effective_len),
        np.asarray(clause_len, dtype=np.int32),
        np.asarray(clause_sel, dtype=np.float64),
        np.asarray(has_dense, dtype=np.uint8),
        float(bitset_build_weight),
        float(bitset_filter_weight),
    )
    if order_idx is None or len(order_idx) == 0:
        return tuple(), -1.0

    plans: List[ClausePlan] = []
    for step_idx, method, cost in zip(order_idx.tolist(), methods.tolist(), step_costs.tolist()):
        real_idx = idx_map[int(step_idx)]
        m = "bitset" if int(method) == 1 else "merge"
        plans.append(ClausePlan(idx=real_idx, method=m, est_cost=float(cost)))
    return tuple(plans), float(total_cost)


def plan_sequence(
    corpus: Corpus,
    node_simple: Sequence[Optional[Tuple[str, np.ndarray, int]]],
    pos_lists: Sequence[Optional[np.ndarray]],
    docset_mask: Optional[np.ndarray],
    scope: Optional[str],
) -> SequencePlan:
    # Conservative cost model: scale by docset selectivity if present.
    selectivity = _docset_selectivity(docset_mask, corpus)
    stats = _prepare_stats(node_simple, pos_lists, corpus)

    # Choose anchor by minimal adjusted length (fallback to raw length).
    best_idx = 0
    best_len = None
    for st in stats:
        eff = st.effective_len
        adj = int(eff * selectivity)
        if docset_mask is not None:
            if scope == "doc" and st.doc_freq is not None:
                adj = int(st.doc_freq)
            elif scope == "s" and st.sent_freq is not None:
                adj = int(st.sent_freq)
            elif st.doc_freq is not None:
                adj = int(st.doc_freq * selectivity)
        if best_len is None or adj < best_len:
            best_len = adj
            best_idx = st.idx

    anchor_len = stats[best_idx].effective_len
    n_tokens = corpus.n_tokens
    n_docs = int(getattr(corpus, "doc_starts", np.zeros(0)).shape[0])
    n_sents = int(getattr(corpus, "sent_starts", np.zeros(0)).shape[0])

    plans: List[ClausePlan] = []
    total = 0.0
    notes: List[str] = []

    # Try DP ordering for small clause counts (Selinger-style).
    dp_order, dp_cost = _order_clauses_dp(
        stats,
        anchor_idx=best_idx,
        n_tokens=n_tokens,
        scope=scope,
        selectivity=selectivity,
        n_docs=n_docs,
        n_sents=n_sents,
        corpus=corpus,
    )
    used_dp = False
    if dp_order:
        plans = list(dp_order)
        total = float(dp_cost)
        used_dp = True
    else:
        for st in stats:
            if st.idx == best_idx:
                continue
            clause_len = int(st.effective_len * selectivity)
            if clause_len < 0:
                clause_len = 0
            has_dense = _has_dense_bitset(corpus, st.attr, st.type_ids)
            use_bitset = _should_use_bitset(clause_len, n_tokens, has_dense=has_dense)
            if use_bitset:
                build_weight = 0.0 if has_dense else get_float(
                    "CANDYCONC_CQLHPC_BITSET_BUILD_WEIGHT", 1.0
                )
                filter_weight = get_float("CANDYCONC_CQLHPC_BITSET_FILTER_WEIGHT", 1.0)
                cost = float(clause_len * build_weight + anchor_len * filter_weight)
                plans.append(ClausePlan(idx=st.idx, method="bitset", est_cost=cost))
            else:
                cost = _estimate_merge_cost(anchor_len, clause_len)
                plans.append(ClausePlan(idx=st.idx, method="merge", est_cost=cost))
            total += cost

    # Order by estimated cost ascending (cheapest constraints first) when not DP ordered.
    if not used_dp:
        plans.sort(key=lambda p: p.est_cost)

    strategy = "global"
    if scope in {"s", "doc"}:
        # Decide if partitioned execution should be preferred.
        n_tokens = corpus.n_tokens
        n_segments = int(corpus.sent_starts.shape[0]) if scope == "s" else int(corpus.doc_starts.shape[0])
        avg_seg_len = (n_tokens / n_segments) if n_segments > 0 else n_tokens
        max_len = get_int("CANDYCONC_CQLHPC_PARTITION_MAX_LEN", 600)
        sel_thresh = get_float("CANDYCONC_CQLHPC_PARTITION_DOCSET", 0.2)
        dens_thresh = get_float("CANDYCONC_CQLHPC_PARTITION_DENSITY", 0.01)
        anchor_density = anchor_len / float(n_tokens) if n_tokens > 0 else 0.0
        if avg_seg_len <= max_len or selectivity <= sel_thresh or anchor_density >= dens_thresh:
            strategy = "partitioned"

    # Hybrid cost model (conservative): estimate candidate sentences from anchor frequency.
    # Hybrid is only chosen when it is clearly cheaper than postings path.
    if get_bool("CANDYCONC_CQLHPC_HYBRID_PLAN", True):
        min_tokens_for_hybrid = get_int("CANDYCONC_CQLHPC_HYBRID_MIN_TOKENS", 1_000_000)
        allow_hybrid = corpus.n_tokens >= min_tokens_for_hybrid
        n_sents = int(corpus.sent_starts.shape[0])
        if n_sents > 0:
            avg_sent_len = corpus.n_tokens / n_sents
        else:
            avg_sent_len = None
        # Approximate candidate sentences by anchor hits / avg_sent_len
        if avg_sent_len is not None and allow_hybrid:
            est_anchor_hits = max(1, anchor_len)
            est_cand_sents = min(n_sents, int(est_anchor_hits / max(1.0, avg_sent_len)))
            # Apply docset selectivity if present
            est_cand_sents = int(est_cand_sents * selectivity)
            hybrid_factor = get_float("CANDYCONC_CQLHPC_HYBRID_COST_FACTOR", 1.5)
            hybrid_cost = float(est_cand_sents * avg_sent_len * hybrid_factor)
            # Compare to postings cost with margin
            margin = get_float("CANDYCONC_CQLHPC_HYBRID_MARGIN", 0.6)
            if hybrid_cost < total * margin:
                strategy = "hybrid"

    if scope:
        notes.append(f"scope={scope}")
    if docset_mask is not None:
        notes.append(f"docset_selectivity={selectivity:.4f}")
    notes.append("order=dp" if used_dp else "order=greedy")
    notes.append(f"strategy={strategy}")

    return SequencePlan(anchor_idx=best_idx, ordered=tuple(plans), total_cost=total, strategy=strategy, notes=tuple(notes))


def explain_plan(plan: SequencePlan) -> str:
    parts = [f"anchor={plan.anchor_idx}"]
    if plan.notes:
        parts.append(" ".join(plan.notes))
    for step in plan.ordered:
        parts.append(f"[{step.idx}:{step.method}:{step.est_cost:.1f}]")
    return " ".join(parts)


def validate_plan(plan: SequencePlan, n_clauses: int) -> bool:
    if n_clauses <= 0:
        return False
    if plan.anchor_idx < 0 or plan.anchor_idx >= n_clauses:
        return False
    if plan.strategy not in {"global", "partitioned", "hybrid"}:
        return False
    seen = set()
    for step in plan.ordered:
        if step.idx == plan.anchor_idx:
            return False
        if step.idx < 0 or step.idx >= n_clauses:
            return False
        if step.idx in seen:
            return False
        if step.method not in {"merge", "bitset"}:
            return False
        seen.add(step.idx)
    # Allow missing steps if DP was truncated? We currently expect full coverage.
    if len(seen) != max(0, n_clauses - 1):
        return False
    return True
