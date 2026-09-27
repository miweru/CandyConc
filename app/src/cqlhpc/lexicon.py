from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left, bisect_right
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass(frozen=True, slots=True)
class Lexicon:
    """Immutable mapping between strings and integer type IDs.

    Completion strategy (fast + good ranking, without a heavy FST dependency):

    - Keep a lexicographically sorted table (term, id) for binary-range prefix lookup.
    - Additionally keep a small *top list per short prefix* (default: length=3) based on
      corpus frequency. This gives very good completions already after a few characters.

    The short-prefix top lists are small enough to live in RAM and to be
    mmap/pickle-friendly. For production you'd typically replace this with
    an FST/DAWG with subtree top-k.
    """

    id_to_str: Sequence[str]
    str_to_id: Dict[str, int]
    freqs: Optional[np.ndarray] = None  # shape (V,), dtype int64 or int32

    # sorted lexicographic tables for prefix ranges
    sorted_terms: Optional[Sequence[str]] = None
    sorted_ids: Optional[np.ndarray] = None

    # short-prefix -> top ids (frequency-ranked)
    prefix_len: int = 3
    top_per_prefix: int = 64
    prefix_top: Optional[Dict[str, np.ndarray]] = None
    top_global: Optional[np.ndarray] = None

    def __post_init__(self):
        if self.sorted_terms is None or self.sorted_ids is None:
            items = sorted(self.str_to_id.items(), key=lambda kv: kv[0])
            terms = [t for t, _ in items]
            ids = np.asarray([i for _, i in items], dtype=np.int32)
            object.__setattr__(self, "sorted_terms", tuple(terms))
            object.__setattr__(self, "sorted_ids", ids)

        if self.freqs is not None and self.top_global is None:
            # Global top list for empty prefix.
            K = min(2000, len(self.id_to_str))
            # argpartition is O(V)
            idx = np.argpartition(-self.freqs, K - 1)[:K]
            idx = idx[np.argsort(-self.freqs[idx])]
            object.__setattr__(self, "top_global", idx.astype(np.int32, copy=False))

        if self.freqs is not None and self.prefix_top is None:
            object.__setattr__(self, "prefix_top", _build_prefix_top(
                self.id_to_str,
                self.freqs,
                prefix_len=self.prefix_len,
                top_k=self.top_per_prefix,
            ))

    def suggest(self, prefix: str, limit: int = 50) -> List[Tuple[str, int]]:
        """Suggest up to `limit` terms (string, type_id), ranked by frequency if available."""
        prefix = prefix or ""

        # Fast path: short-prefix top lists.
        if self.freqs is not None and self.prefix_top is not None:
            if prefix == "":
                if self.top_global is not None:
                    ids = self.top_global[:limit]
                    return [(self.id_to_str[i], int(i)) for i in ids]
            else:
                key = prefix[: self.prefix_len] if len(prefix) >= self.prefix_len else prefix
                cand = self.prefix_top.get(key)
                if cand is not None:
                    out: List[Tuple[str, int]] = []
                    for tid in cand:
                        s = self.id_to_str[int(tid)]
                        if s.startswith(prefix):
                            out.append((s, int(tid)))
                            if len(out) >= limit:
                                return out
                    # If we didn't fill `limit`, fall through to lexicographic range.

        # Baseline: lexicographic range scan and local reranking.
        terms = self.sorted_terms or tuple(sorted(self.str_to_id.keys()))
        ids = self.sorted_ids
        lo = bisect_left(terms, prefix)
        hi = bisect_right(terms, prefix + "\uffff")
        # Take a window; do not scan too much on very short prefixes.
        window = min(2000, max(200, limit * 20))
        sl_hi = min(hi, lo + window)
        res: List[Tuple[str, int]] = []
        for i in range(lo, sl_hi):
            t = terms[i]
            if not t.startswith(prefix):
                break
            tid = int(ids[i]) if ids is not None else self.str_to_id[t]
            res.append((t, tid))
        if self.freqs is not None:
            res.sort(key=lambda x: int(self.freqs[x[1]]), reverse=True)
        return res[:limit]


def _build_prefix_top(id_to_str: Sequence[str], freqs: np.ndarray, prefix_len: int, top_k: int) -> Dict[str, np.ndarray]:
    """Build a short-prefix -> top_k ids table.

    This is an offline structure. Runtime is O(top_k) per completion.
    """

    # Use a dict of small Python lists during build; convert to compact numpy arrays.
    buckets: Dict[str, List[int]] = {}
    # First pass: accumulate ids per prefix.
    for tid, s in enumerate(id_to_str):
        if not s:
            continue
        key = s[:prefix_len] if len(s) >= prefix_len else s
        buckets.setdefault(key, []).append(tid)

    out: Dict[str, np.ndarray] = {}
    for key, ids in buckets.items():
        arr = np.asarray(ids, dtype=np.int32)
        # Keep only top_k by frequency.
        if arr.size > top_k:
            # argpartition is faster than full sort for large buckets.
            k = top_k
            part = np.argpartition(-freqs[arr], k - 1)[:k]
            arr = arr[part]
        # Sort candidates by frequency descending.
        arr = arr[np.argsort(-freqs[arr])]
        out[key] = arr
    return out
