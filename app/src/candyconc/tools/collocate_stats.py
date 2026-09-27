from __future__ import annotations

import argparse
from typing import Callable, Sequence, TYPE_CHECKING

import numpy as np

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - hint for static type checkers
    import networkx as nx

from candyconc.analysis_defaults import (
    adaptive_collocate_min_freq,
    is_analyst_token,
)
from candyconc.core import query_runtime
from candyconc.i18n import lt
from candyconc.core.collocation_engine import CollocationEngine, get_engine as _get_cached_engine
from candyconc.core.counting_kernels import filter_positions_and_values_by_docset_fast
from candyconc.core.fast_index_native import docset_mask_from_ids
from candyconc.domain.query_parser import (
    casefold_key,
    extract_simple_cql_token as _extract_simple_cql_token,
    simple_cql_literal,
)


_DOC_BOUNDS_MISSING = lt(
    "Dokumentgrenzen fehlen. Docset Filter nicht möglich.",
    "Document boundaries are missing. Filtering by document set is not possible.",
)
_LEMMA_LEXICON_MISSING = lt(
    "Lemma Lexikon fehlt. Bitte Index neu bauen.",
    "Lemma lexicon is missing. Rebuild the index.",
)
_LEMMA_POSTINGS_MISSING = lt(
    "Lemma Postings fehlen. Bitte Index neu bauen.",
    "Lemma postings are missing. Rebuild the index.",
)


def _get_engine(index: "query_runtime.CorpusIndex | None" = None) -> CollocationEngine:
    """Resolve the active corpus and return its cached collocation engine.

    Delegates to :func:`candyconc.core.collocation_engine.get_engine`, the single
    signature-aware, lock-guarded engine cache. The previous module-level
    ``_ENGINE`` single-slot cache here never invalidated on an in-place rebuild
    and duplicated the caching responsibility.
    """
    idx = index or query_runtime._CORPUS_INDEX
    fast_index = getattr(idx, "fast_index", None)
    if idx is None or fast_index is None:
        raise RuntimeError(lt("Kein Korpus aktiv. Bitte Index laden.", "No corpus is active. Load an index."))
    return _get_cached_engine(fast_index.index_path)


def collocate_stats(
    term: str,
    window: int = 5,
    *,
    lemmatizer: Callable[[str], str] | None = None,
    within_sentence: bool = False,
    top_n: int | None = None,
    sort_by: str | None = None,
    corpus: "query_runtime.CorpusIndex | None" = None,
    doc_ids: Sequence[int] | None = None,
    min_count: int | None = None,
) -> pd.DataFrame:
    """Return collocate statistics for ``term``.

    The DataFrame includes MI, the ``chi2_cell`` contribution, t-score and
    a log-likelihood-like value.

    ``min_count=None`` or ``0`` selects automatic calibration through
    :func:`candyconc.analysis_defaults.adaptive_collocate_min_freq`:
    5 for frequent nodes, down to 2 for rare nodes. An explicit ``min_count``
    takes precedence with a lower bound of 2, excluding co-occurrence hapaxes.

    ``df.attrs`` reports ``node_frequency`` (scoped node hits, or ``None``
    if unavailable), ``effective_min_count`` and ``min_count_mode``
    (``adaptive`` or ``requested``).
    """

    engine = _get_engine(corpus)
    if min_count is None:
        requested_min_count: int | None = None
    else:
        try:
            requested_min_count = int(min_count)
        except (TypeError, ValueError):
            requested_min_count = None
        if requested_min_count is not None and requested_min_count <= 0:
            requested_min_count = None
    node_frequency: int | None = None
    effective_min_count = adaptive_collocate_min_freq(None, requested_min_count)

    def _with_floor_attrs(frame: pd.DataFrame) -> pd.DataFrame:
        """Disclose the applied floor calibration on the frame itself."""
        frame.attrs["node_frequency"] = node_frequency
        frame.attrs["effective_min_count"] = int(effective_min_count)
        frame.attrs["min_count_mode"] = (
            "requested" if requested_min_count else "adaptive"
        )
        return frame

    term = term or ""
    term_str = term.strip()
    is_cql = term_str.lower().startswith("cql:")
    attr = "lemma" if lemmatizer else "word"
    if lemmatizer and not is_cql:
        term = lemmatizer(term)
        term_str = term.strip()
    docset_mask = None
    idx = corpus or query_runtime._CORPUS_INDEX
    if idx is None or getattr(idx, "fast_index", None) is None:
        raise RuntimeError(lt("Fast Index fehlt. Bitte Index neu bauen.", "The index is missing. Rebuild the index."))
    if doc_ids is not None:
        doc_bounds = (
            idx.fast_index.boundaries.document._positions
            if idx.fast_index.boundaries and idx.fast_index.boundaries.document
            else np.array([], dtype=np.uint32)
        )
        if doc_bounds.size == 0:
            raise RuntimeError(_DOC_BOUNDS_MISSING)
        ids = np.asarray(doc_ids, dtype=np.uint32)
        docset_mask = docset_mask_from_ids(ids, int(doc_bounds.size))
    if is_cql:
        query = term_str[4:].strip()
        if not query:
            return pd.DataFrame()
        engine.load()
        lex = engine._get_lexicon(attr)
        if attr == "lemma" and lex.vocab_size == 0:
            raise RuntimeError(_LEMMA_LEXICON_MISSING)
        if attr == "lemma" and engine.token_store and not engine.token_store.has_lemma_postings():
            raise RuntimeError(_LEMMA_POSTINGS_MISSING)
        from candyconc.core.cql_engine import search_cql_matches_backend

        matches = search_cql_matches_backend(
            idx.fast_index,
            query,
            limit=2_000_000_000,
            within_sentences_by_default=within_sentence,
        )
        if not matches:
            node_frequency = 0
            effective_min_count = adaptive_collocate_min_freq(0, requested_min_count)
            return _with_floor_attrs(pd.DataFrame())
        positions = np.array([m.start for m in matches], dtype=np.uint32)
        spans = np.array(
            [
                max(1, int(getattr(m, "end", int(m.start) + 1)) - int(m.start))
                for m in matches
            ],
            dtype=np.int64,
        )
        if docset_mask is not None:
            doc_bounds = (
                idx.fast_index.boundaries.document._positions
                if idx.fast_index.boundaries and idx.fast_index.boundaries.document
                else np.array([], dtype=np.uint32)
            )
            if doc_bounds.size == 0:
                raise RuntimeError(_DOC_BOUNDS_MISSING)
            positions, spans = filter_positions_and_values_by_docset_fast(
                positions,
                spans,
                doc_bounds,
                docset_mask,
            )
        if positions.size == 0:
            node_frequency = 0
            effective_min_count = adaptive_collocate_min_freq(0, requested_min_count)
            return _with_floor_attrs(pd.DataFrame())
        if positions.size > 1:
            order = np.argsort(positions, kind="mergesort")
            positions = positions[order]
            spans = spans[order]
        # The scoped anchor count is the node frequency used to calibrate the
        # co-occurrence floor.
        node_frequency = int(positions.size)
        effective_min_count = adaptive_collocate_min_freq(
            node_frequency, requested_min_count
        )
        anchors = positions.astype(np.int64, copy=False)
        spans = spans.astype(np.int64, copy=False)
        from candyconc.core.coverage_sweep import (
            coverage_sweep_arrays,
            total_context_mass_arrays,
        )
        from candyconc.core.counting_kernels import count_collocates

        seg_starts, seg_ends, seg_weights = coverage_sweep_arrays(
            anchors=anchors,
            spans=spans,
            window_left=window,
            window_right=window,
            # ALWAYS pass document boundaries (mirrors the engine collocate_stats
            # fix): without this the CQL collocation path bled collocates across
            # document edges when within_sentence=False. within_sentence still
            # controls the additional sentence-level clipping on top.
            boundaries=engine.boundaries,
            within_sentence=within_sentence,
            total_tokens=int(engine.token_store.token_count) if engine.token_store else 0,
        )
        u = total_context_mass_arrays(seg_starts, seg_ends, seg_weights)
        stop_ids: set[int] | None = None
        counts = count_collocates(
            engine.token_store,
            seg_starts,
            seg_ends,
            seg_weights,
            stoplist=stop_ids,
            attr=attr,
            # Output limiting happens after every candidate has been scored.
            top_n=None,
        )
        if u <= 0:
            return _with_floor_attrs(pd.DataFrame())
        # Apply the adaptive co-occurrence floor before ranking to exclude
        # hapaxes from MI and logDice results.
        if effective_min_count > 1 and counts:
            counts = {tid: c for tid, c in counts.items() if c >= effective_min_count}
            if not counts:
                return _with_floor_attrs(pd.DataFrame())
        freqs_override = None
        freqs_override_arr = None
        total_tokens_override = None
        if docset_mask is not None:
            try:
                freqs_override_arr, total_tokens_override = engine._docset_word_counts_dense(
                    docset_mask, attr=attr
                )
            except Exception:
                freqs_override = None
                freqs_override_arr = None
                total_tokens_override = None
        arrays = engine._calculate_statistics_arrays(
            counts,
            int(positions.size),
            int(u),
            lex,
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr,
            total_tokens_override=total_tokens_override,
        )
        if arrays[0].size == 0:
            return _with_floor_attrs(pd.DataFrame())
        sorted_arrays = engine._sort_statistics_arrays(*arrays, top_n=top_n)
        df = engine._statistics_frame_from_sorted(
            *sorted_arrays, lex=lex, node_frequency=int(positions.size),
            context_mass=float(u),
            scope_tokens=float(total_tokens_override or engine.lexicons.total_tokens),
            freqs_override=freqs_override,
            freqs_override_arr=freqs_override_arr)
    else:
        # Resolve the scoped node frequency before the engine call and pass the
        # adaptive floor as min_count. Use the same case-insensitive union and
        # docset filter as the engine. Engine doubles without these helpers use
        # the fixed default.
        try:
            engine.load()
            lex = engine._get_lexicon(attr)
            if attr == "lemma" and lex.vocab_size == 0:
                raise RuntimeError(_LEMMA_LEXICON_MISSING)
            if (
                attr == "lemma"
                and engine.token_store
                and not engine.token_store.has_lemma_postings()
            ):
                raise RuntimeError(_LEMMA_POSTINGS_MISSING)
            node_positions = engine._get_term_positions(term_str, attr=attr, lexicon=lex)
            if docset_mask is not None:
                node_positions = engine._filter_positions_by_docset(
                    node_positions, docset_mask
                )
            node_frequency = int(node_positions.size)
        except RuntimeError:
            raise
        except Exception:
            node_frequency = None
        effective_min_count = adaptive_collocate_min_freq(
            node_frequency, requested_min_count
        )
        df = engine.collocate_stats(
            term_str,
            window_left=window,
            window_right=window,
            attr=attr,
            within_sentence=within_sentence,
            top_n=top_n,
            docset_mask=docset_mask,
            min_count=effective_min_count,
        )
    if df.empty:
        return _with_floor_attrs(df)
    if "word" in df.columns:
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
            # Exclude all case-folded forms of the node, as the REST normalizer does,
            # so both paths return the same candidate set.
            term_key = casefold_key(term_str)
            df = df[~df["word"].map(lambda word: casefold_key(str(word)) == term_key)]
    df = df.rename(columns={"t_score": "t", "log_likelihood": "ll"})
    if "observed" in df.columns:
        df = df.assign(f=df["observed"].astype(np.int64, copy=False))
    keep = [
        c
        for c in [
            "word", "f", "f2", "observed", "expected", "mi", "mi3", "lmi", "npmi", "z", "chi2_cell", "t", "ll",
            "dice", "logdice", "logdice_window", "log_ratio", "lrc",
            "delta_p_nc", "delta_p_cn", "rank",
        ]
        if c in df.columns
    ]
    df = df[keep]
    # WITHOUT sort_by the rows are sorted here too. The engine order follows
    # dice, and logdice_window is 14 + log2(dice), the same order. The tool
    # schema, however, promises the model "default": "logdice", which is
    # Rychly's measure with the denominator f(u) + f(v), a DIFFERENT order.
    #
    # Engine order under the heading "sorted by logdice" would print the top
    # 10 by logdice_window next to the values of the other column. In a
    # support verb list that put "als", "des" and "der" into the top 10 while
    # "spielten" and "entscheidende", two members of the paradigm in
    # question, were missing.
    #
    # Schema and answer both say logdice, so the default follows the schema.
    sort_key = (sort_by or "logdice").strip().lower()
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
    return _with_floor_attrs(df)


# Edge weight measures supported by ``collocate_network``. Each maps to a column
# produced by ``collocate_stats``. ``logdice`` is the recommended default: it is a
# corpus-size-independent association measure and stays comparable across corpora.
NETWORK_MEASURES: tuple[str, ...] = (
    "logdice",
    "dice",
    "mi",
    "mi3",
    "lmi",
    "npmi",
    "z",
    "t",
    "ll",
    "chi2_cell",
)

# Server-friendly caps so a single call cannot blow up the response/graph.
MAX_NETWORK_NODES = 120
MAX_EXPAND_DEPTH = 2


def _network_term_label(term: str) -> str:
    """Human-readable node id for the seed term (strip the ``cql:`` prefix)."""

    raw = (term or "").strip()
    if raw.lower().startswith("cql:"):
        simple = _extract_simple_cql_token(raw)
        if simple:
            return simple
        return raw[4:].strip() or raw
    return raw


def collocate_network_data(
    term: str,
    window: int = 5,
    *,
    measure: str = "logdice",
    max_nodes: int = 30,
    expand_depth: int = 1,
    min_count: int = 5,
    lemmatizer: Callable[[str], str] | None = None,
    corpus: "query_runtime.CorpusIndex | None" = None,
    doc_ids: Sequence[int] | None = None,
    within_sentence: bool = False,
) -> dict:
    """Return a serializable collocation network for ``term``.

    The seed term is linked to its strongest collocates (ranked by ``measure``,
    default logDice). With ``expand_depth=2`` an ego network is built: the
    second-order collocates of the strongest first-order nodes are added and
    inter-node edges are drawn, capped at ``max_nodes`` total nodes.

    Returns ``{"nodes": [{"id", "freq", "depth"}], "edges": [{"source",
    "target", "weight", "measure"}], "measure", "term", "diagnostics": {...}}``.
    A raw networkx object is intentionally NOT returned across the API; use
    :func:`collocate_network` for the in-process networkx convenience.
    """

    measure_key = (measure or "logdice").strip().lower()
    if measure_key == "mi2":
        raise ValueError(
            lt("Kantenmaß 'mi2' wurde durch 'chi2_cell' ersetzt.", "Edge measure 'mi2' has been replaced by 'chi2_cell'.")
        )
    if measure_key not in NETWORK_MEASURES:
        measure_key = "logdice"
    # Clamp the structural budgets defensively; callers may pass user input.
    try:
        max_nodes = int(max_nodes)
    except (TypeError, ValueError):
        max_nodes = 30
    max_nodes = max(2, min(max_nodes, MAX_NETWORK_NODES))
    try:
        expand_depth = int(expand_depth)
    except (TypeError, ValueError):
        expand_depth = 1
    expand_depth = max(1, min(expand_depth, MAX_EXPAND_DEPTH))
    try:
        min_count = int(min_count)
    except (TypeError, ValueError):
        min_count = 5
    min_count = max(1, min_count)

    seed_label = _network_term_label(term)

    def _top_collocates(query: str, limit: int) -> "pd.DataFrame":
        df = collocate_stats(
            query,
            window=window,
            lemmatizer=lemmatizer,
            top_n=None,
            sort_by=measure_key,
            corpus=corpus,
            doc_ids=doc_ids,
            within_sentence=within_sentence,
            min_count=min_count,
        )
        if df is None or df.empty or measure_key not in df.columns:
            return pd.DataFrame()
        df = df[df[measure_key].notna()]
        # Same analyst-token policy as every other collocation surface: drop
        # punctuation and structural markers (|LBR|, '#', emoji, …) before they
        # can claim a node/edge slot, exactly like normalize_default_collocate_frame.
        if "word" in df.columns:
            df = df[df["word"].map(is_analyst_token)]
        if df.empty:
            return pd.DataFrame()
        df = df.sort_values(measure_key, ascending=False, kind="mergesort")
        return df.head(int(limit))

    nodes: dict[str, dict] = {seed_label: {"id": seed_label, "freq": None, "depth": 0}}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()

    def _add_edge(source: str, target: str, weight: float) -> None:
        if source == target:
            return
        key = (source, target) if source <= target else (target, source)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "weight": float(weight),
                "measure": measure_key,
            }
        )

    # For a depth-2 ego network we must reserve budget for second-order nodes,
    # otherwise the first-order ring alone consumes all of ``max_nodes`` and the
    # graph never expands. Cap the number of first-order *hub* nodes when
    # expanding; depth-1 uses the full budget. We still compute the FULL seed
    # direct-collocate ranking (below) so depth labelling can tell a genuine
    # first-order collocate from a true second-order one even when the visible
    # hub ring is capped.
    if expand_depth >= 2:
        first_order_limit = max(5, (max_nodes - 1) // 2)
    else:
        first_order_limit = max_nodes - 1

    # Compute direct seed collocates once. A direct collocate stays depth=1
    # even if it falls below the visible hub cap and appears via a hub.
    # Depth=2 means the seed is reachable only through a hub.
    seed_collocates_full = _top_collocates(term, max_nodes)
    seed_rank: dict[str, int] = {}
    seed_weight: dict[str, float] = {}
    for rank_idx, (_, srow) in enumerate(seed_collocates_full.iterrows()):
        sword = str(srow["word"])
        if not sword or sword == seed_label:
            continue
        if sword not in seed_rank:
            seed_rank[sword] = rank_idx
            seed_weight[sword] = float(srow[measure_key])

    def _seed_depth(word: str) -> int:
        """Authoritative depth for ``word`` w.r.t. the seed: 1 if it is a direct
        seed collocate, else 2."""
        return 1 if word in seed_rank else 2

    def _ensure_seed_edge(word: str) -> None:
        """Draw the seed -> word edge with the seed's own weight if ``word`` is a
        direct seed collocate (idempotent via _add_edge dedup)."""
        if word in seed_weight:
            _add_edge(seed_label, word, seed_weight[word])

    # The visible first-order ring: the strongest direct seed collocates, capped.
    first = seed_collocates_full.head(int(first_order_limit))
    truncated = False
    first_order_labels: list[str] = []
    for _, row in first.iterrows():
        if len(nodes) >= max_nodes:
            truncated = True
            break
        word = str(row["word"])
        if not word or word == seed_label:
            continue
        freq = int(row["f"]) if "f" in row and pd.notna(row["f"]) else None
        # ``freq`` is O11 of this word in the collocate row of the node it was
        # reached from (``freq_via``), not a corpus frequency.
        node = nodes.setdefault(
            word, {"id": word, "freq": freq, "depth": 1, "freq_via": seed_label}
        )
        if node.get("freq") is None and freq is not None:
            node["freq"] = freq
            node["freq_via"] = seed_label
        first_order_labels.append(word)
        _add_edge(seed_label, word, row[measure_key])

    if expand_depth >= 2 and first_order_labels and len(nodes) < max_nodes:
        # Ego network: expand the strongest first-order nodes (highest weight to
        # the seed). ``first_order_labels`` is already in descending order of
        # seed association. We iterate over a SNAPSHOT of the hub ring so that
        # depth-1 children discovered while expanding are labelled/edged as first
        # order WITHOUT themselves becoming additional hubs (which would blow the
        # budget and the depth-2 reservation).
        for parent in list(first_order_labels):
            if len(nodes) >= max_nodes:
                truncated = True
                break
            child_df = _top_collocates(parent, max_nodes)
            for _, row in child_df.iterrows():
                child = str(row["word"])
                if not child or child == parent:
                    continue
                weight = row[measure_key]
                if child == seed_label:
                    # The seed reappears as a hub's collocate: just (re)assert the
                    # seed<->parent edge, never add a node.
                    _ensure_seed_edge(parent)
                    continue
                if child in nodes:
                    # Already present: connect parent -> child, but NEVER promote
                    # an existing node's depth. If the existing node is in fact a
                    # direct seed collocate, make sure its depth/seed edge reflect
                    # that (it may have been added as depth=2 by an earlier hub
                    # before we saw it was first-order — repair it here).
                    existing_node = nodes[child]
                    if child in seed_rank and existing_node.get("depth", 2) != 1:
                        existing_node["depth"] = 1
                        _ensure_seed_edge(child)
                    _add_edge(parent, child, weight)
                    continue
                if len(nodes) >= max_nodes:
                    truncated = True
                    break
                freq = int(row["f"]) if "f" in row and pd.notna(row["f"]) else None
                # A new child that is itself a direct seed collocate is FIRST
                # order (depth=1) and gets a seed edge with the seed's weight;
                # only genuine non-seed collocates are depth=2.
                depth = _seed_depth(child)
                nodes[child] = {"id": child, "freq": freq, "depth": depth, "freq_via": parent}
                if depth == 1:
                    _ensure_seed_edge(child)
                _add_edge(parent, child, weight)

    first_order_count = sum(1 for n in nodes.values() if n.get("depth") == 1)
    second_order_count = sum(1 for n in nodes.values() if n.get("depth") == 2)

    node_list = sorted(
        nodes.values(),
        key=lambda n: (n.get("depth", 99), -(n.get("freq") or 0), n["id"]),
    )
    return {
        "term": seed_label,
        "measure": measure_key,
        "nodes": node_list,
        "edges": edges,
        "diagnostics": {
            "node_count": len(node_list),
            "edge_count": len(edges),
            "first_order_count": first_order_count,
            "second_order_count": second_order_count,
            "expand_depth": expand_depth,
            "max_nodes": max_nodes,
            "window": int(window),
            "min_count": int(min_count),
            "truncated": bool(truncated or seed_rank.keys() - nodes.keys()),
        },
    }


def collocate_network(
    term: str,
    window: int = 5,
    *,
    measure: str = "logdice",
    max_nodes: int = 30,
    expand_depth: int = 1,
    min_count: int = 5,
    lemmatizer: Callable[[str], str] | None = None,
    corpus: "query_runtime.CorpusIndex | None" = None,
    doc_ids: Sequence[int] | None = None,
    within_sentence: bool = False,
) -> "nx.Graph":
    """Return a networkx graph of collocations for ``term``.

    Thin in-process convenience around :func:`collocate_network_data`. The seed
    term is linked to each collocate with the chosen ``measure`` (default
    logDice) stored as the edge ``weight``. For the API/serialization use
    :func:`collocate_network_data`, which never returns a live networkx object.
    """

    import networkx as nx

    data = collocate_network_data(
        term,
        window=window,
        measure=measure,
        max_nodes=max_nodes,
        expand_depth=expand_depth,
        min_count=min_count,
        lemmatizer=lemmatizer,
        corpus=corpus,
        doc_ids=doc_ids,
        within_sentence=within_sentence,
    )
    g = nx.Graph()
    for node in data["nodes"]:
        g.add_node(node["id"], freq=node.get("freq"), depth=node.get("depth"))
    for edge in data["edges"]:
        g.add_edge(
            edge["source"],
            edge["target"],
            weight=edge["weight"],
            measure=edge["measure"],
        )
    return g


def main() -> None:  # pragma: no cover - CLI helper
    parser = argparse.ArgumentParser(description="Compute collocation statistics")
    parser.add_argument("term", help="Keyword")
    parser.add_argument(
        "-w",
        "--window",
        type=int,
        default=5,
        help="Token window to either side of the keyword",
    )
    args = parser.parse_args()

    df = collocate_stats(args.term, window=args.window)
    if df.empty:
        print("(no data)")
        return
    print(df.to_string(index=False))


if __name__ == "__main__":  # pragma: no cover
    main()
