"""/query routes: GET /query, GET /query/stream, GET+POST /query/analyse.

B13 (riskanteste Etappe): extracted verbatim from ``server.py``; only the
ACCESS PATH changed to the established routes pattern (``from .. import
server as _server`` at call time, ``_server.<name>`` for every symbol that is
server-resident or monkeypatched on the server namespace, identical to
routes/analysis.py). The CL-SSE-TOTAL-01 block in the stream generator (exact
count resolution for the done-frame on bounded non-exhaustive scans via
``_server._run_heavy_scan(count_total_matches)``) is byte-verbatim modulo that
access path; AST-isomorphism against the original bodies is proven in the B13
report. ``_resolve_case_insensitive`` lives here (Depends-target must exist at
router import time); server.py re-imports it for the staying /query/count
endpoint and re-exports the handler names (tests call ``srv.query_endpoint``
directly, e.g. tests/backend/test_p2_offload.py:137).

Plan-Abweichung (dokumentiert): B13 sollte "ohne _server-Late-Import"
auskommen; die beweisgefuehrte B5-B12-Realitaet (server-residente Patch-Seams:
Render-Kette, get_corpus/get_index, _LAST_SCAN_FULL, server._get_or_create_
query_count-Patches) macht das etablierte Late-Import-Muster zur einzig
seam-treuen Option. Der Zyklusbruch folgt in B15.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import numpy as np
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query, Request
from fastapi.responses import ORJSONResponse, Response, StreamingResponse

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, localize, lt
from candyconc.core.fast_index_native import lexicon_match_regex
from candyconc.core.source_spacing import apply_source_spacing_rows
from candyconc.services.backend.kwic_renderer import display_rows

from .. import auth, rate_limit
from ..schemas import (
    KWICRow,
    LexiconSuggestRequest,
    LexiconSuggestResponse,
    QueryAnalyseRequest,
    QueryAnalyseResponse,
)

router = CandyAPIRouter()

# Upper bound for the KWIC random-sample size (thinning). Keeps a sampled
# request renderable in one pass; paging/sorting then operate on the sample.
QUERY_SAMPLE_MAX = 10_000


def _validate_sample_params(sample: int | None, seed: int | None) -> tuple[int | None, int | None]:
    """Validate the KWIC thinning parameters (T1).

    ``sample`` must be an int > 0 (bounded by :data:`QUERY_SAMPLE_MAX`); once
    ``sample`` is set, ``seed`` is REQUIRED — there is deliberately NO implicit
    random seed, because reproducibility of the drawn sample is the point of
    the feature. A ``seed`` without ``sample`` has no effect.
    """
    if sample is None:
        return None, None
    try:
        sample_size = int(sample)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            422,
            "query.sample_invalid",
            lt("sample muss eine ganze Zahl > 0 sein", "sample must be an integer > 0"),
        ) from exc
    if sample_size <= 0:
        raise ApiError(
            422,
            "query.sample_invalid",
            lt("sample muss eine ganze Zahl > 0 sein", "sample must be an integer > 0"),
        )
    if sample_size > QUERY_SAMPLE_MAX:
        raise ApiError(
            422,
            "query.sample_too_large",
            lt("sample ist auf maximal {max_sample} begrenzt", "sample is limited to at most {max_sample}"),
            max_sample=QUERY_SAMPLE_MAX,
        )
    if seed is None:
        raise ApiError(
            422,
            "query.seed_required",
            lt(
                "seed ist Pflicht, sobald sample gesetzt ist: die Stichprobe "
                "muss reproduzierbar sein (kein impliziter Zufalls-Seed). "
                "Beispiel: sample=200&seed=42",
                "seed is required once sample is set: the sample must be "
                "reproducible (no implicit random seed). "
                "Example: sample=200&seed=42",
            ),
        )
    try:
        seed_value = int(seed)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            422,
            "query.seed_invalid",
            lt("seed muss eine ganze Zahl >= 0 sein", "seed must be an integer >= 0"),
        ) from exc
    if seed_value < 0:
        raise ApiError(
            422,
            "query.seed_invalid",
            lt("seed muss eine ganze Zahl >= 0 sein", "seed must be an integer >= 0"),
        )
    return sample_size, seed_value


def _sample_position_indices(population: int, drawn: int, seed: int) -> np.ndarray:
    """Uniform random sample WITHOUT replacement over match indices.

    Deterministic via ``numpy.random.default_rng(seed)``. The selected indices
    are sorted ascending so the sampled concordance keeps corpus order (stable
    rendering + stable paging).
    """
    if drawn >= population:
        return np.arange(population, dtype=np.int64)
    rng = np.random.default_rng(int(seed))
    sel = rng.choice(int(population), size=int(drawn), replace=False)
    sel.sort()
    return sel.astype(np.int64, copy=False)


def _sampled_query_rows(
    _server: Any,
    idx: Any,
    term: str,
    *,
    ctx: int,
    docset_mask: Any,
    case_insensitive: bool,
    sample_size: int,
    seed: int,
) -> tuple[list[Any], dict[str, Any]]:
    """Draw a seeded uniform sample over the FULL match set and render it.

    Efficiency contract (T1): the sample is drawn over match POSITIONS (indices
    into the exhaustive position scan), never over rendered rows — only the
    ``min(sample, population)`` sampled hits are rendered. Returns
    ``(rows, sample_meta)`` where ``sample_meta`` is the provenance block
    ``{requested, drawn, seed, population, population_partial}``.

    ``population_partial`` is True when the underlying position scan was
    bounded (e.g. a match-all capped at the CQL scan ceiling): the sample is
    then uniform over that bounded subset, not the true full match set — the
    flag keeps the provenance honest instead of silently overclaiming.
    """
    prepared_cql = _server._prepare_cql_rows_fast(
        idx, term, offset=0, limit=None, docset_mask=docset_mask
    )
    if prepared_cql is not None:
        (
            _query_text,
            positions,
            match_len_const,
            match_lengths,
            pivot_index,
            _total_matches,
            positions_are_full,
        ) = prepared_cql
        population = int(positions.size)
        drawn = min(int(sample_size), population)
        sel = _sample_position_indices(population, drawn, seed)
        sampled_positions = positions[sel]
        sampled_lengths = None if match_lengths is None else match_lengths[sel]
        rows = _server._render_cql_fast_rows(
            idx,
            positions=sampled_positions,
            match_len_const=match_len_const,
            match_lengths=sampled_lengths,
            pivot_index=pivot_index,
            ctx=int(ctx),
        )
        apply_source_spacing_rows(rows, idx)
        meta = {
            "requested": int(sample_size),
            "drawn": int(drawn),
            "seed": int(seed),
            "population": population,
            "population_partial": not bool(positions_are_full),
        }
        return rows, meta

    prepared_plain = _server._prepare_plain_rows_fast(
        idx,
        term,
        offset=0,
        limit=None,
        docset_mask=docset_mask,
        case_insensitive=case_insensitive,
    )
    if prepared_plain is not None:
        term_text, positions, _total_matches, positions_are_full = prepared_plain
        population = int(positions.size)
        drawn = min(int(sample_size), population)
        sel = _sample_position_indices(population, drawn, seed)
        rows = _server._render_fast_rows_for_positions(
            idx,
            positions=positions[sel],
            ctx=int(ctx),
            **_server._plain_render_kwargs(term_text),
        )
        apply_source_spacing_rows(rows, idx)
        meta = {
            "requested": int(sample_size),
            "drawn": int(drawn),
            "seed": int(seed),
            "population": population,
            "population_partial": not bool(positions_are_full),
        }
        return rows, meta

    raise ApiError(
        400,
        "query.sample_unavailable",
        lt(
            "Zufallsstichprobe (sample/seed) erfordert den Fast-Index-Pfad; "
            "für dieses Korpus nicht verfügbar.",
            "A random sample (sample/seed) requires the Fast Index path. "
            "It is not available for this corpus.",
        ),
    )


def _stream_error_text(exc: HTTPException) -> str:
    """Message of an HTTPException for an SSE error frame (pair kept when present)."""
    detail = exc.detail
    return detail if isinstance(detail, str) else str(detail)


def _stream_error_payload(exc: Exception) -> dict[str, Any]:
    """SSE error frame with the message and code GET /query answers for ``exc``.

    A query error raised inside the stream is classified like on GET /query and
    /query/count, so the frame carries the same text and, for an ApiError, the
    same ``code``.
    """
    if not isinstance(exc, HTTPException) and isinstance(exc, (RuntimeError, ValueError)):
        from candyconc.services.backend.query_count import _classify_query_runtime_error

        exc = _classify_query_runtime_error(exc) or exc
    if isinstance(exc, HTTPException):
        payload: dict[str, Any] = {"message": _stream_error_text(exc)}
        code = getattr(exc, "code", None)
        if code:
            payload["code"] = code
        return localize(payload)
    return localize({"message": exception_text(exc)})


def _resolve_case_insensitive(
    case_insensitive: Annotated[
        Optional[bool],
        Query(description="Ignore case (snake_case alias)."),
    ] = None,
    caseInsensitive: Annotated[  # noqa: N803 - external query-param name
        Optional[bool],
        Query(description="Ignore case (camelCase alias)."),
    ] = None,
) -> bool:
    """Accept BOTH ``case_insensitive`` and ``caseInsensitive`` query params.

    Seam C: the Vue frontend emits snake_case ``case_insensitive`` while older /
    external callers used camelCase ``caseInsensitive``. We expose both names so
    neither breaks; snake_case wins when both are supplied. Default is ``True``
    (German plain-search convention).
    """
    if case_insensitive is not None:
        return bool(case_insensitive)
    if caseInsensitive is not None:
        return bool(caseInsensitive)
    return True


@router.get(
    "/query",
    response_model=List[KWICRow],
    response_class=ORJSONResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [
                        {
                            "left": "to improve the welfare of",
                            "kw": "the",
                            "right": "American people. In addition",
                            "pos": 4790,
                            "doc_id": 1,
                            "doc": "sotu-1946-Truman",
                            "match_offsets": [1, 2],
                        }
                    ]
                }
            }
        }
    },
)
async def query_endpoint(
    term: str,
    ctx: int = 5,
    corpus: str = "default",
    date: str | None = None,
    genre: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    sample: int | None = None,
    seed: int | None = None,
    case_insensitive: Annotated[bool, Depends(_resolve_case_insensitive)] = True,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    user: str | None = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> List[Dict[str, Any]]:
    """Concordance lines of a query.

    Parameters
    - term: plain search, or a query of the query language with the prefix cql:
    - ctx: context width in tokens to the left and right, limited by
      CANDYCONC_QUERY_MAX_CONTEXT
    - corpus: corpus name, default is default
    - date, genre: optional metadata filters
    - limit: maximum number of lines, default CANDYCONC_QUERY_DEFAULT_LIMIT, at
      most 5000
    - sample: random sample, a uniform sample of size min(sample, hits) from all
      hits. Sorting and paging work on the sample.
    - seed: seed of the random sample (required with sample, the same seed gives
      the same sample)

    Response
    - list of concordance lines with fields such as left, kw, right, pos and, for
      a hit of several tokens, match_offsets
    - headers X-CandyConc-Truncated and X-CandyConc-Next-Offset mark a cut response
    - header X-CandyConc-Query-Trace-Id identifies this query run
    - header X-CandyConc-Sample carries the provenance of a sample
      {requested, drawn, seed, population, population_partial}

    \f
    KWIC Abfrage für einen Suchbegriff.

    Parameter
    - term: Suchbegriff, wird als Wortform im Index gesucht
    - ctx: Kontextfenster in Tokens links und rechts, begrenzt durch CANDYCONC_QUERY_MAX_CONTEXT
    - corpus: Korpusname, Standard ist default
    - date, genre: optionale Metadatenfilter
    - limit: Maximale Trefferzahl, default CANDYCONC_QUERY_DEFAULT_LIMIT, hard cap 5000
    - sample: Zufallsstichprobe (Thinning): uniforme Stichprobe der Größe
      min(sample, Treffermenge) aus der GESAMTEN Treffermenge; Sortierung und
      Paging operieren danach auf der Stichprobe
    - seed: deterministischer RNG-Seed (Pflicht, sobald sample gesetzt ist —
      identischer Seed reproduziert exakt dieselbe Stichprobe)

    Antwort
    - Liste von KWIC Zeilen mit Feldern wie left, kw, right, pos
    - Header X-CandyConc-Truncated/X-CandyConc-Next-Offset zeigen abgeschnittene Antworten an
    - Header X-CandyConc-Query-Trace-Id referenziert diesen Backend-Query-Lauf
    - Header X-CandyConc-Sample trägt bei Stichproben die Provenienz
      {requested, drawn, seed, population, population_partial}
    """
    from .. import server as _server

    # Finding 37: an empty/whitespace search box is a normal user action; reject
    # it with a friendly message BEFORE the CQL parser turns it into the jargon
    # "Query Parser Fehler: Unexpected end of input".
    if not term.strip():
        raise ApiError(400, "query.empty", lt("Bitte einen Suchbegriff eingeben.", "Please enter a search term."))

    # T1 (Thinning): validate sample/seed BEFORE any work; seed is mandatory
    # once sample is set (reproducibility contract, no implicit random seed).
    sample_size, seed_value = _validate_sample_params(sample, seed)
    sample_requested = sample_size is not None

    _server.metrics.inc_queries()
    start = _server.metrics.start_timer()

    idx = _server.get_corpus(corpus)
    ctx = _server._bounded_query_context(ctx)
    effective_limit, limit_defaulted, limit_clamped = _server._bounded_query_limit(
        limit, hard_max=_server._query_hard_limit(), strict=True
    )
    try:
        offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "query.offset_invalid", lt("offset muss >= 0 sein", "offset must be >= 0")) from exc
    _server._reject_negative_offset(offset)
    from candyconc.services.backend.kwic_renderer import parse_sort

    try:
        sort_spec = parse_sort(sort_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    # For a SORTED query we must scan beyond the first page so the ordering covers
    # (up to a cap of) the whole match set, not just the first `limit` positional
    # hits. Unsorted queries keep the cheap first-page-plus-one scan.
    sort_requested = sort_spec is not None
    sort_scan_cap = _server._kwic_sort_scan_cap() if sort_requested else 0
    scan_limit = (sort_scan_cap + 1) if sort_requested else (offset + effective_limit + 1)
    query_trace_id = _server._new_query_trace_id()
    fast_index = getattr(idx, "fast_index", None)
    cache_index_key = _server._corpus_cache_signature(fast_index, corpus or "default")
    response_cache_key = (
        cache_index_key,
        str(term),
        int(ctx),
        str(date or ""),
        str(genre or ""),
        _server._query_limit_cache_marker(effective_limit, limit_defaulted),
        int(offset),
        # sort_by/sort_dir MUST be in the cache key, else a sorted response would
        # be served for an unsorted request (and vice versa).
        str(sort_by or ""),
        str(sort_dir or "asc"),
        # case_insensitive changes the match set, so it is part of the identity.
        "ci" if case_insensitive else "cs",
        # sample+seed change the served row set, so they are part of the
        # identity (a sampled response must never be served for an unsampled
        # request, nor across different seeds/sizes).
        f"sample:{sample_size}:{seed_value}" if sample_requested else "nosample",
    )
    cached_response = _server._query_rows_response_cache_get(response_cache_key)
    if cached_response is not None:
        cached_payload, cached_headers = cached_response
        headers = dict(cached_headers)
        headers["X-CandyConc-Query-Trace-Id"] = query_trace_id
        _server.metrics.observe_latency(start)
        return Response(content=cached_payload, media_type="application/json", headers=headers)
    # CPU-heavy synchronous section (query eval + enrich + sort + JSON serialize).
    # Offloaded to a worker thread so the event loop stays free for concurrent
    # requests/SSE/WS. HTTPException(400) for user errors still propagates through
    # asyncio.to_thread unchanged. No awaits/locks/shared-state inside this closure.
    def _compute_query_payload() -> tuple[bytes, bool, bool, int, int | None, int | None, dict[str, Any] | None]:
        # KWIC-PLAIN-02: a sorted view orders only the SCANNED prefix. If that scan
        # was bounded (positions not exhaustive), the A-Z order is over a subset of
        # the true match set and must be flagged sort-approximate — even when the
        # post-sentinel-drop row count happens to fall below the sort scan cap.
        # ``scan_full`` carries scan-completeness out of the fast-row helpers.
        scan_full = True
        sample_meta: dict[str, Any] | None = None
        try:
            rows = None
            metadata_mask = _server._metadata_filter_docset_mask(idx, date=date, genre=genre)
            if sample_requested:
                # T1: exhaustive position scan -> seeded uniform sample over the
                # match indices -> render ONLY the sampled hits. Sorting/paging
                # below operate on the sample. ``scan_full`` mirrors whether the
                # population itself was exhaustive (honest sort-approximate flag).
                rows, sample_meta = _sampled_query_rows(
                    _server,
                    idx,
                    term,
                    ctx=int(ctx),
                    docset_mask=metadata_mask,
                    case_insensitive=case_insensitive,
                    sample_size=int(sample_size),
                    seed=int(seed_value),
                )
                scan_full = not bool(sample_meta.get("population_partial"))
            elif metadata_mask is None:
                _server._LAST_SCAN_FULL.set(True)
                rows = _server._query_rows_cql_fast(idx, term, ctx=int(ctx), limit=scan_limit)
                if rows is None:
                    rows = _server._query_rows_plain_fast(
                        idx, term, ctx=int(ctx), limit=scan_limit,
                        case_insensitive=case_insensitive,
                    )
                scan_full = bool(_server._LAST_SCAN_FULL.get())
            else:
                cql_prepared = _server._prepare_cql_rows_fast(
                    idx,
                    term,
                    offset=0,
                    limit=scan_limit,
                    docset_mask=metadata_mask,
                )
                if cql_prepared is not None:
                    (
                        _query_text,
                        positions,
                        match_len_const,
                        match_lengths,
                        pivot_index,
                        _total_matches,
                        positions_are_full,
                    ) = cql_prepared
                    scan_full = bool(positions_are_full)
                    rows = _server._render_cql_fast_rows(
                        idx,
                        positions=positions,
                        match_len_const=match_len_const,
                        match_lengths=match_lengths,
                        pivot_index=pivot_index,
                        ctx=int(ctx),
                    )
                if rows is None:
                    plain_prepared = _server._prepare_plain_rows_fast(
                        idx,
                        term,
                        offset=0,
                        limit=scan_limit,
                        docset_mask=metadata_mask,
                        case_insensitive=case_insensitive,
                    )
                    if plain_prepared is not None:
                        term_text, positions, _total_matches, positions_are_full = plain_prepared
                        scan_full = bool(positions_are_full)
                        rows = _server._render_fast_rows_for_positions(
                            idx,
                            positions=positions,
                            ctx=int(ctx),
                            **_server._plain_render_kwargs(term_text),
                        )
            if rows is None:
                from candyconc.services.backend.kwic import kwic_rows_list

                rows = kwic_rows_list(
                    term,
                    ctx=int(ctx),
                    date=None,
                    genre=None,
                    docset_mask=metadata_mask,
                    corpus=idx,
                    limit=scan_limit,
                    include_file=False,
                    compact_rows=True,
                )
        except (RuntimeError, ValueError) as exc:
            # Classify centrally: 503 for server-state (index-not-ready / rebuild
            # needed), 400 for caller-fault parse/regex errors, else re-raise so a
            # genuine bug surfaces honestly as a 500. Previously a server-state
            # RuntimeError on this path leaked as a 500 (god-module finding D).
            mapped = _server._classify_query_runtime_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise

        def _enrich_rows(rows):
            # Enrich rows with document metadata so the frontend can show source/model/etc.
            if rows and not (isinstance(rows[0], dict) and "meta" in rows[0] and "doc" in rows[0]):
                if isinstance(rows[0], tuple) and len(rows[0]) > 4:
                    rows = _server._enrich_compact_tuple_rows_with_doc_meta(
                        idx,
                        rows,
                        row_has_offsets=(len(rows[0]) > 5),
                    )
                else:
                    try:
                        doc_bounds = _server._doc_bounds_for_index(idx)
                    except RuntimeError:
                        doc_bounds = None
                    if doc_bounds is not None and doc_bounds.size:
                        token_count = int(idx.fast_index.token_store.token_count)
                        _server._enrich_rows_with_doc_meta(
                            idx,
                            rows,
                            doc_bounds=doc_bounds,
                            token_count=token_count,
                            cache={},
                            include_file=False,
                        )
            # Original spacing (whitespace_after.bin) on the final dict rows,
            # before the display normalisation and the sort, which both read
            # the rendered text. Sort keys stay token based (token_starts).
            return apply_source_spacing_rows(rows, idx)

        from candyconc.services.backend.kwic_renderer import normalise_kwic_row_display, sort_kwic_rows

        sort_approximate = False
        if sort_spec is not None:
            # Enrich the full fetched window FIRST so meta-sort works and rows are dicts,
            # then sort, then truncate — the order is over up to `sort_scan_cap` matches.
            # If more matches existed than we scanned, the global ordering is approximate.
            rows = _enrich_rows(rows)
            # The ordering is approximate when we scanned MORE than the cap (rows
            # beyond it were never ordered) OR when the underlying position scan was
            # itself bounded (``scan_full`` is False) — a broad match-all whose true
            # match set far exceeds what we scanned (KWIC-PLAIN-02). Without the
            # second clause a node-sorted [word=".*"] presents A-Z over a < cap
            # subset yet claims to be the complete ordering.
            #
            # SAMPLE MODE: the drawn sample IS the complete result set — it is
            # ordered in full (bounded by QUERY_SAMPLE_MAX) and never cut to the
            # sort scan cap; sampling provenance lives in X-CandyConc-Sample.
            if not sample_requested:
                sort_approximate = len(rows) > sort_scan_cap or not scan_full
                if len(rows) > sort_scan_cap:
                    rows = rows[:sort_scan_cap]
            # Normalise the display text BEFORE sorting so the sort keys on exactly
            # the text the user sees. Otherwise a right-context that begins with a
            # raw '|LBR|' marker sorts on '|' (0x7C, after 'z'), then the marker is
            # stripped for display, landing the row at the wrong alphabetical rank.
            rows = [normalise_kwic_row_display(row) for row in rows]
            rows = sort_kwic_rows(rows, sort_by, sort_dir=sort_dir)
            truncated = sort_approximate or len(rows) > (offset + effective_limit)
            rows = rows[offset : offset + effective_limit]
        else:
            # Default path: truncate, then enrich.
            truncated = len(rows) > (offset + effective_limit)
            rows = rows[offset : offset + effective_limit]
            rows = _enrich_rows(rows)

        rows = [normalise_kwic_row_display(row) for row in rows]
        row_count = len(rows)
        if sort_spec is None and not truncated and not scan_full and not sample_requested:
            # KWIC-PLAIN-03: the page check (`len(rows) > offset+limit`) is the
            # cheap truncation signal, but it NEVER fires for a broad query whose
            # first-page-plus-one scan caps at scan_limit and is then |LBR|-dropped
            # below the page size (e.g. [word=".*"] returns 300 rows yet has 55550
            # hits) — so the page would claim total == row_count (COMPLETE) with no
            # next_offset. Only in that ambiguous case (page not full BUT the scan
            # was bounded) do we reconcile against the canonical hit count — the
            # SAME source of truth /query/count and the SSE done event use. That
            # makes truncated/next_offset/X-Total honest in BOTH directions: a
            # genuinely short/empty result stays COMPLETE, a bounded subset is
            # flagged with the real total and a load-more offset. An exhaustive
            # scan (scan_full) keeps the cheap path — no extra count.
            exact_total, _elapsed, count_partial = _server._compute_query_count(
                idx, term, int(ctx), date, genre,
                case_insensitive=case_insensitive,
            )
            seen = offset + row_count
            truncated = bool(count_partial) or int(exact_total) > seen
            next_offset = seen if truncated and row_count > 0 else None
            total_count = None if (truncated or count_partial) else int(exact_total)
        else:
            next_offset = offset + row_count if truncated and row_count > 0 else None
            total_count = None if truncated else offset + row_count

        payload = _server._json_dumps_fast_bytes(rows)
        return payload, truncated, sort_approximate, row_count, next_offset, total_count, sample_meta

    payload, truncated, sort_approximate, row_count, next_offset, total_count, sample_meta = await _server._run_heavy_scan(_compute_query_payload)

    _server.metrics.observe_latency(start)
    _server.metrics.observe_throughput(row_count, start)
    headers = _server._query_bound_headers(
        effective_limit=effective_limit,
        limit_defaulted=limit_defaulted,
        effective_ctx=int(ctx),
        truncated=truncated,
        next_offset=next_offset,
    )
    if limit_clamped:
        # Finding 34: an oversized requested limit was capped to the hard max.
        # The /query body is a bare KWIC list with no envelope, so surface the
        # clamp via a header (alongside X-CandyConc-Limit / X-CandyConc-Truncated)
        # so the caller knows the result was bounded rather than silently cut.
        headers["X-CandyConc-Limit-Clamped"] = "true"
    if sort_approximate:
        # Ordering is over a bounded prefix of the match set, not the whole thing.
        headers["X-CandyConc-Sort-Approximate"] = "true"
    if sample_meta is not None:
        # Sampling provenance (T1): {requested, drawn, seed, population,
        # population_partial}. The /query body is a bare KWIC list, so the
        # method-style provenance travels as a compact JSON header (and is part
        # of the cached response like every other X-CandyConc-* header).
        headers["X-CandyConc-Sample"] = json.dumps(
            sample_meta, separators=(",", ":"), ensure_ascii=False
        )
    if total_count is not None:
        headers["X-CandyConc-Total"] = str(int(total_count))
    _server._query_rows_response_cache_set(response_cache_key, payload, headers)
    headers = dict(headers)
    headers["X-CandyConc-Query-Trace-Id"] = query_trace_id
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get(
    "/query/stream",
    responses={200: {"content": {"text/event-stream": {"example": ""}}}},
)
async def query_stream_endpoint(
    term: str,
    request: Request,
    ctx: int = 5,
    corpus: str = "default",
    date: str | None = None,
    genre: str | None = None,
    docset_id: str | None = None,
    batch_size: int = 50,
    limit: int | None = None,
    offset: int = 0,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    sample: int | None = None,
    seed: int | None = None,
    case_insensitive: Annotated[bool, Depends(_resolve_case_insensitive)] = True,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    user: str | None = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> StreamingResponse:
    """Concordance lines of a query as server-sent events.

    Sends the lines in batches, in corpus order, as they are found. Sorting is not
    supported: a request with ``sort_by`` is answered with 400. Sorted
    concordances come from GET /query.

    ``sample`` and ``seed`` work as on GET /query. Paging works on the sample, and
    the done event carries its provenance under ``sample``.

    Events:
    - batch: array of concordance lines (at most batch_size)
    - progress: {count, elapsed_ms}
    - count: {total, elapsed_ms, partial}
    - done: {total, query_time_ms, partial, truncated, next_offset}
    - error: {message, code}, with code where GET /query answers with one

    \f
    KWIC Abfrage mit Server-Sent Events Streaming.

    Streamt Ergebnisse in Batches für progressive Anzeige im Frontend.

    Sortierung wird vom Stream-Endpoint NICHT unterstützt: Streaming liefert
    Treffer in Korpus-Reihenfolge, sobald sie gefunden werden — eine globale
    Sortierung würde den vollständigen Scan vor dem ersten Event erzwingen.
    Ein gesetztes ``sort_by`` führt zu einem expliziten 400 (problem+json)
    statt eines stillen Ignorierens; sortierte Abfragen gehen über GET /query.

    Stichprobe (Thinning): ``sample``/``seed`` spiegeln GET /query — uniforme
    Zufallsstichprobe der Größe min(sample, Treffermenge) aus der gesamten
    Treffermenge, deterministisch über ``seed`` (Pflicht, sobald ``sample``
    gesetzt ist). Paging operiert auf der Stichprobe; das done-Event trägt die
    Provenienz unter ``sample``.

    Events:
    - batch: Array von KWIC-Zeilen (max batch_size)
    - progress: {count: int, elapsed_ms: float}
    - count: {total: int, elapsed_ms: float, partial: bool}
    - done: {total: int, query_time_ms: float, partial: bool, truncated: bool, next_offset: int | null}
    - error: {message: string}
    """
    from .. import server as _server
    # Finding 37: reject an empty/whitespace term with a friendly message BEFORE
    # opening the SSE stream (and before the CQL parser leaks "Unexpected end of
    # input"). Raised here so the global handler renders a clean problem+json.
    if not term.strip():
        raise ApiError(400, "query.empty", lt("Bitte einen Suchbegriff eingeben.", "Please enter a search term."))
    # Explicit guard instead of FastAPI silently dropping unknown params:
    # sorted KWIC is served by GET /query (which honors sort_by/sort_dir and
    # sets X-CandyConc-Sort-Approximate). Raised before the StreamingResponse
    # starts, so the global handler renders a clean problem+json body.
    if (sort_by or "").strip():
        raise ApiError(
            400,
            "query.stream_sort_unsupported",
            lt(
                "Sortierung wird vom Stream-Endpoint nicht unterstützt; "
                "nutze GET /query",
                "Sorting is not supported by the stream endpoint. Use GET /query.",
            ),
        )
    _ = sort_dir  # accepted for surface symmetry with GET /query; unused without sort_by
    # T1: same validation contract as GET /query — sample>0, seed mandatory.
    # Raised BEFORE the StreamingResponse starts (clean problem+json).
    sample_size, seed_value = _validate_sample_params(sample, seed)
    sample_requested = sample_size is not None
    if offset == 0:
        _server.metrics.inc_queries()
    query_trace_id = _server._new_query_trace_id()

    # Clamp parameters to reasonable bounds
    batch_size = max(10, min(500, batch_size))
    ctx = _server._bounded_query_context(ctx)
    try:
        offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "query.offset_invalid", lt("offset muss >= 0 sein", "offset must be >= 0")) from exc
    _server._reject_negative_offset(offset)
    page_limit, limit_defaulted, limit_clamped = _server._bounded_query_limit(
        limit, hard_max=_server._query_stream_hard_limit(), strict=True
    )
    scan_limit = page_limit + 1

    # SEARCH-KWIC-02: resolve (and thereby validate) the corpus BEFORE the
    # StreamingResponse is constructed. A bogus corpus made get_corpus() raise
    # inside the SSE body generator — after the 200 response had already
    # started — yielding an empty stream plus an unhandled TaskGroup traceback.
    # Raising here lets the global handler render a clean 404 (problem+json).
    corpus_index = _server.get_corpus(corpus)

    async def generate_sample_events():
        """T1 sampled stream: seeded uniform sample, paged, then batched.

        Deliberately bypasses the count-state machinery and the stream batch
        cache of the regular generator: the effective result set IS the drawn
        sample (count event total == drawn), and correctness of the cache key
        across (sample, seed) variants is not worth the extra cache surface.
        """

        start = _server.metrics.start_timer()
        idx = corpus_index
        try:
            docset_mask = None
            if docset_id:
                docset = _server._get_docset(str(docset_id))
                if docset.get("corpus") != (corpus or "default"):
                    raise ApiError(
                        422,
                        "docset.other_corpus",
                        lt("docset_id gehört zu anderem Korpus", "docset_id belongs to a different corpus"),
                    )
                docset_mask = docset.get("docset_mask")
            metadata_mask = _server._metadata_filter_docset_mask(idx, date=date, genre=genre)
            effective_docset_mask = _server._combine_docset_masks(docset_mask, metadata_mask)
            normalized_term = _server._normalize_query_key(term)

            rows, smeta = await _server._run_heavy_scan(
                _sampled_query_rows,
                _server,
                idx,
                normalized_term,
                ctx=int(ctx),
                docset_mask=effective_docset_mask,
                case_insensitive=case_insensitive,
                sample_size=int(sample_size),
                seed=int(seed_value),
            )
            drawn = int(smeta["drawn"])
            population_partial = bool(smeta.get("population_partial"))

            yield _server._sse_event_bytes(
                "count",
                _server._json_dumps_fast_bytes(
                    {
                        "total": drawn,
                        "elapsed_ms": (time.perf_counter() - start) * 1000,
                        "partial": population_partial,
                    }
                ),
            )

            page_rows = rows[offset:]
            if page_limit is not None:
                page_rows = page_rows[: int(page_limit)]

            try:
                doc_bounds = _server._doc_bounds_for_index(idx)
            except RuntimeError:
                doc_bounds = None
            token_count = 0
            if doc_bounds is not None and doc_bounds.size:
                token_count = int(idx.fast_index.token_store.token_count)
            doc_meta_cache: dict[tuple[int, str | None], tuple[str, dict[str, str]]] = {}

            emitted = 0
            for batch_start in range(0, len(page_rows), batch_size):
                if request is not None and await request.is_disconnected():
                    break
                batch_rows = page_rows[batch_start : batch_start + batch_size]
                if not batch_rows:
                    continue
                if isinstance(batch_rows[0], tuple) and len(batch_rows[0]) > 4:
                    batch_rows = _server._enrich_compact_tuple_rows_with_doc_meta(
                        idx,
                        batch_rows,
                        row_has_offsets=(len(batch_rows[0]) > 5),
                    )
                else:
                    _server._enrich_rows_with_doc_meta(
                        idx,
                        batch_rows,
                        doc_bounds=doc_bounds,
                        token_count=token_count,
                        cache=doc_meta_cache,
                        include_file=False,
                    )
                batch_rows = display_rows(batch_rows, idx)
                yield _server._sse_event_bytes(
                    "batch", _server._json_dumps_fast_bytes(batch_rows)
                )
                emitted += len(batch_rows)
                yield _server._sse_event_bytes(
                    "progress",
                    _server._json_dumps_fast_bytes(
                        {"count": emitted, "elapsed_ms": (time.perf_counter() - start) * 1000}
                    ),
                )

            elapsed_ms = (time.perf_counter() - start) * 1000
            _server.metrics.observe_latency(start)
            _server.metrics.observe_throughput(emitted, start)
            truncated = (int(offset) + emitted) < drawn
            done_payload = {
                "total": drawn,
                "query_time_ms": elapsed_ms,
                "partial": bool(truncated or population_partial),
                "truncated": truncated,
                "clamped": bool(limit_clamped),
                "next_offset": (int(offset) + emitted) if truncated and emitted > 0 else None,
                "limit": page_limit,
                "limit_defaulted": limit_defaulted,
                "ctx": int(ctx),
                "queryTraceId": query_trace_id,
                # Sampling provenance: mirrors the GET /query X-CandyConc-Sample
                # header {requested, drawn, seed, population, population_partial}.
                "sample": smeta,
            }
            yield _server._sse_event_bytes("done", _server._json_dumps_fast_bytes(done_payload))
        except asyncio.CancelledError:
            raise
        except HTTPException as e:
            yield _server._sse_event_bytes(
                "error", _server._json_dumps_fast_bytes(_stream_error_payload(e))
            )
        except Exception as e:
            yield _server._sse_event_bytes(
                "error", _server._json_dumps_fast_bytes(_stream_error_payload(e))
            )

    async def generate_events():
        from candyconc.services.backend.kwic import kwic_rows

        start = _server.metrics.start_timer()
        idx = corpus_index
        count_key = None
        stream_cache_key = None
        try:
            docset_mask = None
            if docset_id:
                docset = _server._get_docset(str(docset_id))
                if docset.get("corpus") != (corpus or "default"):
                    raise ApiError(
                        422,
                        "docset.other_corpus",
                        lt("docset_id gehört zu anderem Korpus", "docset_id belongs to a different corpus"),
                    )
                docset_mask = docset.get("docset_mask")
            metadata_mask = _server._metadata_filter_docset_mask(idx, date=date, genre=genre)
            effective_docset_mask = _server._combine_docset_masks(docset_mask, metadata_mask)

            normalized_term = _server._normalize_query_key(term)
            fast_index = getattr(idx, "fast_index", None)
            cache_index_key = _server._corpus_cache_signature(fast_index, corpus or "default")
            stream_cache_key = (
                cache_index_key,
                normalized_term,
                int(ctx),
                str(date or ""),
                str(genre or ""),
                str(docset_id or ""),
                int(batch_size),
                int(page_limit) if page_limit is not None else -1,
                int(offset),
                "ci" if case_insensitive else "cs",
            )
            cached_stream = _server._query_stream_batch_cache_get(stream_cache_key)
            if cached_stream is not None:
                cached_batches, cached_total, cached_partial, cached_next_offset, cached_truncated = cached_stream
                yield _server._sse_event_bytes(
                    "count",
                    _server._json_dumps_fast_bytes(
                        {"total": cached_total, "elapsed_ms": 0.0, "partial": cached_partial}
                    ),
                )
                emitted = 0
                for batch_payload, batch_rows in cached_batches:
                    if request is not None and await request.is_disconnected():
                        return
                    yield _server._sse_event_bytes("batch", batch_payload)
                    emitted += int(batch_rows)
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    yield _server._sse_event_bytes(
                        "progress",
                        _server._json_dumps_fast_bytes({"count": emitted, "elapsed_ms": elapsed_ms}),
                    )
                elapsed_ms = (time.perf_counter() - start) * 1000
                _server.metrics.observe_latency(start)
                _server.metrics.observe_throughput(cached_total, start)
                yield _server._sse_event_bytes(
                    "done",
                    _server._json_dumps_fast_bytes(
                        {
                            "total": cached_total,
                            "query_time_ms": elapsed_ms,
                            "partial": cached_partial,
                            "truncated": cached_truncated,
                            "clamped": bool(limit_clamped),
                            "next_offset": cached_next_offset,
                            "limit": page_limit,
                            "limit_defaulted": limit_defaulted,
                            "ctx": int(ctx),
                            "queryTraceId": query_trace_id,
                        }
                    ),
                )
                return

            def count_total_matches() -> tuple[int, float, bool]:
                return _server._compute_query_count(
                    idx,
                    normalized_term,
                    int(ctx),
                    None,
                    None,
                    effective_docset_mask,
                    case_insensitive=case_insensitive,
                )

            # Get document bounds once for enrichment
            try:
                doc_bounds = _server._doc_bounds_for_index(idx)
            except RuntimeError:
                doc_bounds = None

            token_count = 0
            if doc_bounds is not None and doc_bounds.size:
                token_count = int(idx.fast_index.token_store.token_count)
            doc_meta_cache: dict[tuple[int, str | None], tuple[str, dict[str, str]]] = {}
            stream_cache_batches: list[tuple[bytes, int]] = []

            batch: List[Dict[str, Any]] = []
            total_count = 0
            limited = False
            count_sent = False
            count_key = _server._query_count_key(
                normalized_term, corpus, date, genre, docset_id,
                build_sig=cache_index_key, case_insensitive=case_insensitive,
            )
            pending_count: tuple[int, float, bool] | None = None
            term_str = normalized_term.strip()
            if not term_str:
                done_payload = {
                    "total": 0,
                    "query_time_ms": 0,
                    "partial": False,
                    "truncated": False,
                    "clamped": bool(limit_clamped),
                    "next_offset": None,
                    "limit": page_limit,
                    "limit_defaulted": limit_defaulted,
                    "ctx": int(ctx),
                    "queryTraceId": query_trace_id,
                }
                yield _server._sse_event_bytes("done", _server._json_dumps_fast_bytes(done_payload))
                return

            should_inline_count = False
            should_background_count = False

            count_started = False
            count_state = await _server._get_or_create_query_count(
                count_key,
                create=False,
                compute_fn=count_total_matches,
                attach=bool(term_str),
            )
            if count_state is not None:
                count_started = True
            if count_state is not None:
                result = _server._resolve_query_count_result(count_state)
                if result is not None:
                    count_total, count_elapsed, count_partial = result
                    yield _server._sse_event_bytes(
                        "count",
                        _server._json_dumps_fast_bytes(
                            {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                        ),
                    )
                    count_sent = True

            count_start = time.perf_counter()

            def count_cb(total: int) -> None:
                nonlocal pending_count
                if pending_count is not None:
                    return
                elapsed_ms = (time.perf_counter() - count_start) * 1000
                pending_count = (total, elapsed_ms, False)
                asyncio.create_task(
                    _server._complete_query_count(
                        count_key,
                        total=total,
                        elapsed_ms=elapsed_ms,
                        partial=False,
                    )
                )

            # These position scans are CPU-heavy Cython work. Offload them to the
            # bounded heavy-scan pool so the SSE event loop stays responsive to
            # other connections instead of blocking inside the async generator
            # (D8 #6). _run_heavy_scan propagates exceptions/contextvars like
            # asyncio.to_thread, so user-error classification below is unchanged.
            cql_prepared = None
            plain_prepared = None
            cql_prepared = await _server._run_heavy_scan(
                _server._prepare_cql_rows_fast,
                idx,
                normalized_term,
                offset=offset,
                limit=scan_limit,
                docset_mask=effective_docset_mask,
            )
            if cql_prepared is None:
                plain_prepared = await _server._run_heavy_scan(
                    _server._prepare_plain_rows_fast,
                    idx,
                    normalized_term,
                    offset=offset,
                    limit=scan_limit,
                    docset_mask=effective_docset_mask,
                    case_insensitive=case_insensitive,
                )

            async def _emit_batch(batch_rows: list[Any]):
                nonlocal count_started, count_sent
                if not batch_rows:
                    return
                if isinstance(batch_rows[0], tuple) and len(batch_rows[0]) > 4:
                    batch_rows = _server._enrich_compact_tuple_rows_with_doc_meta(
                        idx,
                        batch_rows,
                        row_has_offsets=(len(batch_rows[0]) > 5),
                    )
                else:
                    _server._enrich_rows_with_doc_meta(
                        idx,
                        batch_rows,
                        doc_bounds=doc_bounds,
                        token_count=token_count,
                        cache=doc_meta_cache,
                        include_file=False,
                    )
                # Render index-only |LBR| markers to newlines before serialising,
                # so the stream serves the same display text as the non-stream
                # /query route. The normalised payload is what we cache, so the
                # cached-replay branch above is clean by construction.
                batch_rows = display_rows(batch_rows, idx)
                batch_payload = _server._json_dumps_fast_bytes(batch_rows)
                stream_cache_batches.append((batch_payload, len(batch_rows)))
                yield _server._sse_event_bytes("batch", batch_payload)

                elapsed = (time.perf_counter() - start) * 1000
                yield _server._sse_event_bytes(
                    "progress",
                    _server._json_dumps_fast_bytes({"count": total_count, "elapsed_ms": elapsed}),
                )

                if (
                    not count_started
                    and should_background_count
                    and pending_count is None
                ):
                    count_state_local = await _server._get_or_create_query_count(
                        count_key,
                        create=True,
                        compute_fn=count_total_matches,
                        attach=bool(term_str),
                    )
                    if count_state_local is not None:
                        count_started = True
                        nonlocal_count_state[0] = count_state_local

                if pending_count is not None and not count_sent:
                    count_total, count_elapsed, count_partial = pending_count
                    yield _server._sse_event_bytes(
                        "count",
                        _server._json_dumps_fast_bytes(
                            {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                        ),
                    )
                    count_sent = True

                state = nonlocal_count_state[0]
                if state is not None and not count_sent:
                    result = _server._resolve_query_count_result(state)
                    if result is not None:
                        count_total, count_elapsed, count_partial = result
                        yield _server._sse_event_bytes(
                            "count",
                            _server._json_dumps_fast_bytes(
                                {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                            ),
                        )
                        count_sent = True
                return

            nonlocal_count_state: list[Any] = [count_state]
            # CQL-WILDCARD-COUNT-02: when the position scan was bounded (NOT
            # exhaustive — e.g. a match-all [word=".*"] capped at scan_limit) we do
            # NOT know the true total here. Carry that so the done event is marked
            # partial instead of claiming the limited row count is COMPLETE.
            scan_incomplete = False

            if cql_prepared is not None:
                (
                    _query_text,
                    positions,
                    match_len_const,
                    match_lengths,
                    _pivot_index,
                    total_matches,
                    positions_are_full,
                ) = cql_prepared
                scan_incomplete = not positions_are_full
                if positions_are_full and pending_count is None:
                    pending_count = ((int(total_matches)), (time.perf_counter() - count_start) * 1000, False)
                batch_start = 0
                while batch_start < int(positions.size):
                    if request is not None and await request.is_disconnected():
                        break
                    batch_end = min(batch_start + batch_size, int(positions.size))
                    pos_batch = positions[batch_start:batch_end]
                    len_batch = None if match_lengths is None else match_lengths[batch_start:batch_end]
                    batch_rows = _server._render_cql_fast_rows(
                        idx,
                        positions=pos_batch,
                        match_len_const=match_len_const,
                        match_lengths=len_batch,
                        pivot_index=_pivot_index,
                        ctx=int(ctx),
                    )
                    batch_start = batch_end
                    if not batch_rows:
                        continue
                    if page_limit is not None:
                        remaining_allowed = page_limit - total_count
                        if remaining_allowed <= 0:
                            limited = True
                            break
                        if len(batch_rows) > remaining_allowed:
                            batch_rows = batch_rows[:remaining_allowed]
                            limited = True
                    total_count += len(batch_rows)
                    async for _event in _emit_batch(batch_rows):
                        yield _event
                    if limited:
                        break
                count_state = nonlocal_count_state[0]
            elif plain_prepared is not None:
                term_text, positions, total_matches, positions_are_full = plain_prepared
                plain_render_kwargs = _server._plain_render_kwargs(term_text)
                scan_incomplete = not positions_are_full
                if positions_are_full and pending_count is None:
                    pending_count = (int(total_matches), (time.perf_counter() - count_start) * 1000, False)
                batch_start = 0
                while batch_start < int(positions.size):
                    if request is not None and await request.is_disconnected():
                        break
                    batch_end = min(batch_start + batch_size, int(positions.size))
                    pos_batch = positions[batch_start:batch_end]
                    batch_rows = _server._render_fast_rows_for_positions(
                        idx,
                        positions=pos_batch,
                        ctx=int(ctx),
                        **plain_render_kwargs,
                    )
                    batch_start = batch_end
                    if not batch_rows:
                        continue
                    if page_limit is not None:
                        remaining_allowed = page_limit - total_count
                        if remaining_allowed <= 0:
                            limited = True
                            break
                        if len(batch_rows) > remaining_allowed:
                            batch_rows = batch_rows[:remaining_allowed]
                            limited = True
                    total_count += len(batch_rows)
                    async for _event in _emit_batch(batch_rows):
                        yield _event
                    if limited:
                        break
                count_state = nonlocal_count_state[0]
            else:
                async for row in kwic_rows(
                    normalized_term,
                    ctx=int(ctx),
                    date=None,
                    genre=None,
                    docset_mask=effective_docset_mask,
                    corpus=idx,
                    offset=offset,
                    limit=scan_limit,
                    use_cache=None,
                    allow_cache_fallback=True,
                    count_cb=count_cb if should_inline_count else None,
                    cooperate_every=batch_size,
                    include_file=False,
                ):
                    if request is not None and await request.is_disconnected():
                        break
                    batch.append(row)
                    total_count += 1
                    if page_limit is not None and total_count > page_limit:
                        limited = True
                        total_count -= 1
                        batch.pop()
                        break

                    if len(batch) >= batch_size:
                        async for _event in _emit_batch(batch):
                            yield _event
                        batch = []
                count_state = nonlocal_count_state[0]

            # Emit remaining rows
            if batch:
                async for _event in _emit_batch(batch):
                    yield _event
                batch = []

            if pending_count is not None and not count_sent:
                count_total, count_elapsed, count_partial = pending_count
                yield _server._sse_event_bytes(
                    "count",
                    _server._json_dumps_fast_bytes(
                        {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                    ),
                )
                count_sent = True

            if (
                not count_started
                and should_background_count
                and pending_count is None
            ):
                count_state = await _server._get_or_create_query_count(
                    count_key,
                    create=True,
                    compute_fn=count_total_matches,
                    attach=bool(term_str),
                )
                if count_state is not None:
                    count_started = True

            if count_state is not None and not count_sent:
                result = _server._resolve_query_count_result(count_state)
                if result is not None:
                    count_total, count_elapsed, count_partial = result
                    yield _server._sse_event_bytes(
                        "count",
                        _server._json_dumps_fast_bytes(
                            {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                        ),
                    )
                    count_sent = True

            # Final done event
            elapsed_ms = (_server.metrics.start_timer() - start) * 1000
            _server.metrics.observe_latency(start)
            _server.metrics.observe_throughput(total_count, start)
            done_total = total_count
            done_partial = bool(limited)
            count_partial = False
            exact_count_resolved = False
            if pending_count is not None:
                done_total, _, count_partial = pending_count
                done_partial = done_partial or bool(count_partial)
                exact_count_resolved = not bool(count_partial)
            elif count_state is not None:
                result = _server._resolve_query_count_result(count_state)
                if result is not None:
                    done_total, _, count_partial = result
                    done_partial = done_partial or bool(count_partial)
                    exact_count_resolved = not bool(count_partial)

            # CL-SSE-TOTAL-01: a bounded non-exhaustive scan leaves done_total at the
            # streamed page count — the exact-count callback never fired and no
            # /query/count was attached. Resolve the canonical total once (the SAME
            # compute /query/count uses, offloaded to the heavy-scan pool like the row
            # scans) so the raw SSE done.total EQUALS /query/count. It stays honestly
            # partial:true below because the emitted rows are still a subset. Only
            # fires for a genuine bounded subset, so a complete result never pays it.
            if not exact_count_resolved and (bool(limited) or bool(scan_incomplete)) and bool(term_str):
                try:
                    ctot, _cms, cpart = await _server._run_heavy_scan(count_total_matches)
                    done_total = int(ctot)
                    count_partial = bool(cpart)
                    done_partial = done_partial or bool(cpart)
                    exact_count_resolved = not bool(cpart)
                except Exception:
                    pass

            # CQL-WILDCARD-COUNT-03: derive completeness from whether the EMITTED
            # rows are a bounded subset of the match set — not from `limited`
            # alone. `limited` never fires for a broad query whose bounded scan
            # returns <= page_limit rows after |LBR|-dropping (e.g. [word=".*"]
            # streams 299 rows but its true total is 55550). When an EXACT total is
            # known we reconcile directly against the emitted row count (the one
            # source of truth: total > emitted ⇒ subset); a complete 0-hit/short
            # result then stays COMPLETE. Only when no exact count resolved do we
            # fall back to the scan-incomplete floor signal. Mirrors the SORTED GET
            # branch so the done event can never claim COMPLETE over a partial page
            # NOR claim partial over a genuinely complete one.
            if exact_count_resolved:
                rows_are_subset = bool(limited) or int(done_total) > int(total_count)
            else:
                rows_are_subset = bool(limited) or bool(scan_incomplete)
            done_partial = done_partial or rows_are_subset
            done_truncated = rows_are_subset
            done_next_offset = offset + total_count if rows_are_subset else None

            done_payload = {
                "total": done_total,
                "query_time_ms": elapsed_ms,
                "partial": done_partial,
                "truncated": done_truncated,
                # Finding 34: report when an oversized requested limit was capped
                # to the hard max, so a clamped page is distinguishable from a
                # naturally-short result.
                "clamped": bool(limit_clamped),
                "next_offset": done_next_offset,
                "limit": page_limit,
                "limit_defaulted": limit_defaulted,
                "ctx": int(ctx),
                "queryTraceId": query_trace_id,
            }
            if stream_cache_key is not None and stream_cache_batches:
                _server._query_stream_batch_cache_set(
                    stream_cache_key,
                    stream_cache_batches,
                    total=done_total,
                    partial=done_partial,
                    next_offset=done_next_offset,
                    truncated=done_truncated,
                )
            yield _server._sse_event_bytes("done", _server._json_dumps_fast_bytes(done_payload))

            if count_state is not None and not count_sent:
                try:
                    while True:
                        if request is not None and await request.is_disconnected():
                            break
                        result = _server._resolve_query_count_result(count_state)
                        if result is not None:
                            count_total, count_elapsed, count_partial = result
                            yield _server._sse_event_bytes(
                                "count",
                                _server._json_dumps_fast_bytes(
                                    {"total": count_total, "elapsed_ms": count_elapsed, "partial": count_partial}
                                ),
                            )
                            count_sent = True
                            break
                        if count_state.error:
                            break
                        yield b": keep-alive\n\n"
                        await asyncio.sleep(0.6)
                except Exception:
                    logging.exception("Failed to finalize count after done")
                finally:
                    count_sent = True

        except asyncio.CancelledError:
            raise
        except HTTPException as e:
            yield _server._sse_event_bytes(
                "error", _server._json_dumps_fast_bytes(_stream_error_payload(e))
            )
        except Exception as e:
            yield _server._sse_event_bytes(
                "error", _server._json_dumps_fast_bytes(_stream_error_payload(e))
            )
        finally:
            if count_key is not None:
                await _server._release_query_count(count_key)

    return StreamingResponse(
        generate_sample_events() if sample_requested else generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "X-CandyConc-Query-Trace-Id": query_trace_id,
        }
    )


@router.post(
    "/query/analyse",
    response_model=QueryAnalyseResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "errors": [],
                        "suggestions": ["cql:[lemma=\"gehen\"]"],
                        "hints": ["Token: lemma equals"],
                        "spans": [],
                    }
                }
            }
        }
    },
)
async def query_analyse_post(
    payload: QueryAnalyseRequest = Body(
        ...,
        examples={
            "cql": {
                "summary": "Query language",
                "value": {"query": "cql:[lemma=\"freedom\"]"},
            },
            "simple": {
                "summary": "Plain search",
                "value": {"query": "freedom AND peace"},
            },
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Return validation result for ``query`` using JSON body."""
    from .. import server as _server
    return await _server._analyse_query_text(payload.query.strip(), payload.corpus)


def _lexicon_suggest_values(index, attr: str, prefix: str, limit: int) -> list[str]:
    attr_map = {"ner": "ent", "entity": "ent"}
    attr = attr_map.get(attr, attr)
    prefix = (prefix or "").strip()
    limit = max(1, min(int(limit), 200))

    lex = index._lexicon_for_attr(attr)
    if lex is None:
        return []
    if attr == "ent" and lex.vocab_size == 0:
        default_ner = [
            "PER",
            "PERSON",
            "LOC",
            "GPE",
            "ORG",
            "MISC",
            "FAC",
            "NORP",
            "EVENT",
            "WORK_OF_ART",
            "PRODUCT",
            "LAW",
            "LANGUAGE",
            "DATE",
            "TIME",
            "MONEY",
            "PERCENT",
            "QUANTITY",
            "ORDINAL",
            "CARDINAL",
        ]
        if prefix:
            pref = prefix.lower()
            return [t for t in default_ner if t.lower().startswith(pref)][:limit]
        return default_ner[:limit]

    def _filter_prefix(values: list[str]) -> list[str]:
        if not prefix:
            return values
        pref = prefix.lower()
        return [v for v in values if v.lower().startswith(pref)]

    if attr in {"pos", "ent", "morph", "rel"}:
        ids = np.arange(1, lex.vocab_size + 1, dtype=np.uint32)
        if ids.size == 0:
            return []
        freqs = lex.get_freqs_for_ids(ids)
        order = np.argsort(-freqs)
        ids = ids[order]
        strings = lex.get_strings_for_ids(ids.tolist())
        out: list[str] = []
        for s in _filter_prefix(strings):
            if s:
                out.append(s)
            if len(out) >= limit:
                break
        return out

    def _apply_caps_boost(strings: list[str], freqs: np.ndarray, boost: float) -> np.ndarray:
        if boost <= 0:
            return freqs
        scores = freqs.astype(np.float64, copy=True)
        for idx, val in enumerate(strings):
            if val and val[0].isupper():
                scores[idx] *= (1.0 + boost)
        return scores

    prefix_is_lower = prefix.islower() if prefix else False

    if not prefix:
        if lex.top_global_ids is not None and lex.top_global_ids.size:
            ids = lex.top_global_ids
            strings = lex.get_strings_for_ids(ids.tolist())
            freqs = lex.get_freqs_for_ids(ids)
            if attr in {"word", "lemma"} and prefix_is_lower:
                scores = _apply_caps_boost(strings, freqs, 0.15 if attr == "word" else 0.1)
                order = np.argsort(-scores)
                strings = [strings[i] for i in order]
            return [s for s in strings if s][:limit]
        freqs = lex.get_freqs_array()
        if freqs.size <= 1:
            return []
        ids = np.arange(1, freqs.size, dtype=np.uint32)
        top_k = min(limit * 5, ids.size)
        top_idx = np.argpartition(freqs[1:], -top_k)[-top_k:]
        ids = ids[top_idx + 1]
        top_freqs = freqs[ids]
        strings = lex.get_strings_for_ids(ids.tolist())
        if attr in {"word", "lemma"} and prefix_is_lower:
            scores = _apply_caps_boost(strings, top_freqs, 0.15 if attr == "word" else 0.1)
            order = np.argsort(-scores)
        else:
            order = np.argsort(-top_freqs)
        ids = ids[order][:limit]
        strings = lex.get_strings_for_ids(ids.tolist())
        return [s for s in strings if s][:limit]

    # Prefer prefix cache if available
    prefix_lower = prefix.lower()
    if lex.prefix_top is not None and lex.prefix_len and len(prefix_lower) >= lex.prefix_len:
        key = prefix_lower[: lex.prefix_len]
        cached_ids = lex.prefix_top.get(key)
        if cached_ids is not None and cached_ids.size:
            strings = lex.get_strings_for_ids(cached_ids.tolist())
            freqs = lex.get_freqs_for_ids(cached_ids)
            filtered = [
                (s, freqs[i])
                for i, s in enumerate(strings)
                if s and s.lower().startswith(prefix_lower)
            ]
            if filtered:
                f_strings = [s for s, _ in filtered]
                f_freqs = np.array([f for _, f in filtered], dtype=np.int64)
                if attr in {"word", "lemma"} and prefix_is_lower:
                    scores = _apply_caps_boost(f_strings, f_freqs, 0.15 if attr == "word" else 0.1)
                    order = np.argsort(-scores)
                else:
                    order = np.argsort(-f_freqs)
                f_strings = [f_strings[i] for i in order]
                return [s for s in f_strings if s][:limit]

    pattern = re.compile(f"^{re.escape(prefix)}.*", re.IGNORECASE)
    ids = lexicon_match_regex(lex.offsets, lex.strings_view, pattern)
    if ids.size == 0:
        return []
    freqs = lex.get_freqs_for_ids(ids)
    top_k = min(limit * 5, ids.size)
    if ids.size > top_k:
        top_idx = np.argpartition(freqs, -top_k)[-top_k:]
        ids = ids[top_idx]
        freqs = freqs[top_idx]
    strings = lex.get_strings_for_ids(ids.tolist())
    if attr in {"word", "lemma"} and prefix_is_lower:
        scores = _apply_caps_boost(strings, freqs, 0.15 if attr == "word" else 0.1)
        order = np.argsort(-scores)
    else:
        order = np.argsort(-freqs)
    ids = ids[order]
    strings = [strings[i] for i in order]
    out: list[str] = []
    for s in _filter_prefix(strings):
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


@router.post(
    "/query/lexicon/suggest",
    response_model=LexiconSuggestResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"values": ["NOUN", "ADJ", "VERB"]}
                }
            }
        }
    },
)
async def lexicon_suggest_endpoint(
    payload: LexiconSuggestRequest = Body(
        ...,
        examples={
            "pos": {"summary": "POS suggestions", "value": {"attr": "pos", "prefix": "A", "limit": 50}},
            "word": {
                "summary": "Word suggestions",
                "value": {"attr": "word", "prefix": "Klim", "limit": 20, "corpus": "default"},
            },
        },
    ),
) -> Dict[str, list[str]]:
    from .. import server as _server

    try:
        idx = _server.get_corpus(payload.corpus)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
    try:
        values = await asyncio.to_thread(
            _lexicon_suggest_values,
            idx.fast_index,
            payload.attr.strip().lower(),
            payload.prefix or "",
            payload.limit,
        )
    except Exception as exc:  # pragma: no cover - optional
        logging.warning("Lexikon Vorschläge fehlgeschlagen: %s", exc)
        values = []
    return {"values": values}
