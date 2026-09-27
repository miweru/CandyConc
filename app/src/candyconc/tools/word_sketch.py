from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd
import numpy as np

from candyconc.analysis_defaults import (
    normalize_word_sketch_tables,
    word_sketch_score_row,
)
from candyconc.core import query_runtime
from candyconc.i18n import lt
from candyconc.core.fast_index_native import word_sketch_counts


def word_sketch(term: str, *, top_rows: int = 8) -> dict[str, pd.DataFrame]:
    """Return grammatical collocations grouped by dependency relation."""

    if query_runtime._CORPUS_INDEX is None:
        raise RuntimeError("No corpus available. Index a corpus first.")
    fast = query_runtime._CORPUS_INDEX.fast_index
    store = fast.token_store
    lex = fast.lexicons
    rel_lex = lex.rel if lex else None
    word_lex = lex.word if lex else None
    if word_lex is None:
        raise RuntimeError(
            lt("Wortlexikon fehlt. Bitte Index neu bauen.", "Word lexicon is missing. Rebuild the index.")
        )
    term_id = word_lex.get_id(term) or word_lex.get_id(term.lower())
    if term_id <= 0:
        return {}

    positions = store.get_positions_for_word_id(term_id)
    if positions.size == 0:
        return {}

    head_ids = store.head_ids
    rel_ids = store.rel_ids
    word_stream = store.word_stream
    if word_stream is None:
        raise RuntimeError(
            lt("Word Stream fehlt. Bitte Index neu bauen.", "Word stream is missing. Rebuild the index.")
        )

    def _ensure_writeable(arr: np.ndarray, dtype: np.dtype) -> np.ndarray:
        out = np.asarray(arr, dtype=dtype)
        base = out.base
        if (
            not out.flags.writeable
            or (base is not None and isinstance(base, np.memmap) and getattr(base, "mode", "r") == "r")
        ):
            out = np.array(out, copy=True)
        return out

    dep_counts, head_counts = word_sketch_counts(
        _ensure_writeable(positions, np.uint32),
        _ensure_writeable(head_ids, np.int64),
        _ensure_writeable(rel_ids, np.uint32),
        word_stream.offsets,
        word_stream.data,
        int(word_stream.block_size),
        int(store.token_count),
    )

    term_count = word_lex.get_freq(term_id)
    total = word_lex.total_tokens

    coll_counts: dict[str, Counter[int]] = {}

    for rel_id, counter in dep_counts.items():
        rel_name = rel_lex.get_string(int(rel_id)) if rel_lex else str(rel_id)
        label = f"{rel_name}_rev"
        coll_counts[label] = Counter({int(k): int(v) for k, v in counter.items()})

    for rel_id, counter in head_counts.items():
        rel_name = rel_lex.get_string(int(rel_id)) if rel_lex else str(rel_id)
        coll_counts[rel_name] = Counter({int(k): int(v) for k, v in counter.items()})

    results: dict[str, pd.DataFrame] = {}
    for label, counter in coll_counts.items():
        rows = []
        for word_id, obs in counter.items():
            f2 = int(word_lex.get_freq(word_id))
            word = word_lex.get_string(word_id)
            # Shared per-row scorer (single source of truth with the REST path
            # server._word_sketch_for_query): full 2x2 Dunning G^2 + signed LL,
            # ranked by ll_signed — not by a single-cell score.
            rows.append(
                word_sketch_score_row(
                    word,
                    int(obs),
                    int(term_count),
                    f2,
                    int(total),
                    f2_basis="global",
                )
            )
        df = pd.DataFrame(rows)
        if df.empty:
            continue
        df = df.sort_values("ll_signed", ascending=False).reset_index(drop=True)
        df.index += 1
        df["rank"] = df.index
        results[label] = df

    return normalize_word_sketch_tables(results, term, top_rows=top_rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute grammatical collocations"
    )
    parser.add_argument("term", help="Keyword")
    parser.add_argument(
        "-n",
        "--relations",
        type=int,
        default=5,
        help="number of dependency relations to display",
    )
    args = parser.parse_args()

    tables = word_sketch(args.term)
    # sort relations by association strength of their top collocate (signed G^2,
    # matching the per-row ranking key used by both word-sketch paths)
    def _rel_strength(df: pd.DataFrame) -> float:
        if df.empty:
            return float("-inf")
        col = "ll_signed" if "ll_signed" in df.columns else ("score" if "score" in df.columns else None)
        return float(df[col].max()) if col else float("-inf")

    items = sorted(tables.items(), key=lambda t: _rel_strength(t[1]), reverse=True)
    for rel, df in items[: args.relations]:
        print(f"## {rel}")
        if df.empty:
            print("(no data)")
            continue
        print(df.to_string(index=False))
        print()


if __name__ == "__main__":  # pragma: no cover
    main()
