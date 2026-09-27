import asyncio
from typing import AsyncGenerator, Dict, Callable, Iterable

import numpy as np

from candyconc.core.counting_kernels import position_to_doc_id_fast
from candyconc.core.corpus_index import CorpusIndex
from .pii_filter import mask_pii, _pii_mask_enabled
from candyconc.i18n import lt

from candyconc.core.query_runtime import run_query, run_query_list, _CORPUS_INDEX


def get_engine() -> str:
    """Return the underlying KWIC engine name."""

    return "fast-index"


engine = get_engine()


# Render KWIC rows with original spacing from whitespace_after.bin using
# core.source_spacing. The sidecar adds ws_before_kw, ws_after_kw and
# token_starts. Legacy indexes and PII-masked rows retain space joining.
# Keep the old helper names importable for callers and tests.
from candyconc.core.source_spacing import (  # noqa: E402, F401 (re-exported)
    apply_source_spacing as _apply_whitespace_to_row,
    join_tokens as _join_ws,
    whitespace_flags as _whitespace_after_for,
)


def _iter_kwic_rows(
    term: str,
    *,
    ctx: int = 5,
    date: str | None = None,
    genre: str | None = None,
    docset_mask: np.ndarray | None = None,
    corpus: "CorpusIndex | None" = None,
    offset: int = 0,
    limit: int | None = None,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    include_file: bool = True,
) -> Iterable[Dict[str, str]]:
    idx = corpus or _CORPUS_INDEX
    offset = max(0, int(offset))
    pii_enabled = _pii_mask_enabled()
    # Use source spacing only when the sidecar exists and PII masking is off.
    # Masking may change token counts and invalidate per-position flags.
    # Without the sidecar, legacy space-joined strings pass through unchanged.
    ws = _whitespace_after_for(idx) if not pii_enabled else None
    if (
        not pii_enabled
        and not date
        and not genre
        and docset_mask is None
    ):
        rows = run_query(
            term,
            ctx=ctx,
            corpus=idx,
            limit=limit,
            offset=offset,
            use_cache=use_cache,
            allow_cache_fallback=allow_cache_fallback,
            count_cb=count_cb,
            progress_cb=progress_cb,
            docset_mask=docset_mask,
            include_file=include_file,
        )
        if ws is None:
            yield from rows
        else:
            for row in rows:
                yield _apply_whitespace_to_row(row, ws)
        return
    if (date or genre) and idx is not None:
        limit_total = None if limit is None or docset_mask is not None else int(offset) + int(limit)
        rows = idx.query_metadata(term, date=date, genre=genre, ctx=ctx, limit=limit_total)
    else:
        rows = run_query(
            term,
            ctx=ctx,
            corpus=idx,
            limit=limit,
            offset=offset,
            use_cache=use_cache,
            allow_cache_fallback=allow_cache_fallback,
            count_cb=count_cb,
            progress_cb=progress_cb,
            docset_mask=docset_mask,
            include_file=include_file,
        )

    yielded = 0
    skipped = 0
    doc_bounds = None
    if docset_mask is not None and idx is not None:
        if not (idx.fast_index.boundaries and idx.fast_index.boundaries.document):
            raise RuntimeError(
                lt("Dokumentgrenzen fehlen. Bitte Index neu bauen.", "Document boundaries are missing. Rebuild the index.")
            )
        doc_bounds = idx.fast_index.boundaries.document._positions
        if doc_bounds.size == 0:
            raise RuntimeError(
                lt("Dokumentgrenzen leer. Bitte Index neu bauen.", "Document boundaries are empty. Rebuild the index.")
            )
        if docset_mask.size < doc_bounds.size:
            raise RuntimeError(
                lt(
                    "Docset Maske passt nicht zur Dokumentanzahl.",
                    "Document set mask does not match the number of documents.",
                )
            )

    for row in rows:
        if (date or genre) and docset_mask is not None and doc_bounds is not None:
            pos = row.get("pos")
            if pos is None:
                continue
            doc_id = position_to_doc_id_fast(pos, doc_bounds)
            if doc_id < 0 or doc_id >= int(docset_mask.size) or not docset_mask[doc_id]:
                continue
        if (date or genre) and offset and skipped < offset:
            skipped += 1
            continue
        pos = row.get("pos")
        if pii_enabled:
            if pos is None or idx is None:
                raise RuntimeError(
                    lt(
                        "PII Filter erfordert pos und geladenen Index",
                        "The PII filter requires pos and a loaded index",
                    )
                )
            left_tokens = str(row.get("left", "")).split()
            right_tokens = str(row.get("right", "")).split()
            kw_word = str(row.get("kw", ""))
            kw_tokens = kw_word.split() if kw_word else []
            row["left"] = mask_pii(
                " ".join(left_tokens),
                start_pos=pos - len(left_tokens),
                index=idx,
                tokens=left_tokens,
            )
            row["kw"] = mask_pii(
                kw_word,
                start_pos=pos,
                index=idx,
                tokens=kw_tokens,
            )
            row["right"] = mask_pii(
                " ".join(right_tokens),
                start_pos=pos + 1,
                index=idx,
                tokens=right_tokens,
            )
        if ws is not None:
            row = _apply_whitespace_to_row(row, ws)
        yield row
        yielded += 1
        if limit is not None and yielded >= limit:
            break


def kwic_rows_list(
    term: str,
    *,
    ctx: int = 5,
    date: str | None = None,
    genre: str | None = None,
    docset_mask: np.ndarray | None = None,
    corpus: "CorpusIndex | None" = None,
    offset: int = 0,
    limit: int | None = None,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    include_file: bool = True,
    compact_rows: bool = False,
) -> list[Dict[str, str]]:
    idx = corpus or _CORPUS_INDEX
    offset = max(0, int(offset))
    if (
        not _pii_mask_enabled()
        and not date
        and not genre
        and docset_mask is None
        and str(term or "").strip().lower().startswith("cql:")
    ):
        rows = run_query_list(
            term,
            ctx=ctx,
            corpus=idx,
            limit=limit,
            offset=offset,
            use_cache=use_cache,
            allow_cache_fallback=allow_cache_fallback,
            count_cb=count_cb,
            progress_cb=progress_cb,
            docset_mask=docset_mask,
            include_file=include_file,
            compact_rows=compact_rows,
        )
        if not compact_rows:
            # Compact tuple rows keep legacy rendering for the frontend buffer.
            # Dictionary rows receive the source spacing.
            ws = _whitespace_after_for(idx)
            if ws is not None:
                rows = [
                    _apply_whitespace_to_row(r, ws) if isinstance(r, dict) else r
                    for r in rows
                ]
        return rows
    return list(
        _iter_kwic_rows(
            term,
            ctx=ctx,
            date=date,
            genre=genre,
            docset_mask=docset_mask,
            corpus=corpus,
            offset=offset,
            limit=limit,
            use_cache=use_cache,
            allow_cache_fallback=allow_cache_fallback,
            count_cb=count_cb,
            progress_cb=progress_cb,
            include_file=include_file,
        )
    )


async def kwic_rows(
    term: str,
    *,
    ctx: int = 5,
    date: str | None = None,
    genre: str | None = None,
    docset_mask: np.ndarray | None = None,
    corpus: "CorpusIndex | None" = None,
    offset: int = 0,
    limit: int | None = None,
    use_cache: bool | None = None,
    allow_cache_fallback: bool = False,
    count_cb: Callable[[int], None] | None = None,
    progress_cb: Callable | None = None,
    cooperate_every: int = 0,
    include_file: bool = True,
) -> AsyncGenerator[Dict[str, str], None]:
    """Yield KWIC rows asynchronously from the active corpus."""

    cooperate_every = max(0, int(cooperate_every))
    yielded = 0
    for row in _iter_kwic_rows(
        term,
        ctx=ctx,
        date=date,
        genre=genre,
        docset_mask=docset_mask,
        corpus=corpus,
        offset=offset,
        limit=limit,
        use_cache=use_cache,
        allow_cache_fallback=allow_cache_fallback,
        count_cb=count_cb,
        progress_cb=progress_cb,
        include_file=include_file,
    ):
        yield row
        yielded += 1
        if cooperate_every and yielded % cooperate_every == 0:
            await asyncio.sleep(0)
