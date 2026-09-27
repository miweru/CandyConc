"""Document search, context snippets, and full-text access routes."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import Annotated, Any, Dict

import numpy as np
from fastapi import Depends, HTTPException

from candyconc.core.doc_search import document_search
from candyconc.core.meta_index import DOCUMENT_LABEL_FIELDS, descriptive_fields
from candyconc.core.fast_index_native import strings_for_ids
from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, lt

from .. import rate_limit
from ..doc_meta import _doc_meta_for_doc_id
from ..kwic_render import _doc_bounds_for_index


router = CandyAPIRouter()


_GetIndex = Callable[[], Any]
_GetCorpus = Callable[[str | None], Any]
_DocIdForPosition = Callable[[Any, int, np.ndarray | None], int]
_get_index: _GetIndex | None = None
_get_corpus: _GetCorpus | None = None
_doc_id_for_position: _DocIdForPosition | None = None


def bind_document_runtime(
    *,
    get_index: _GetIndex,
    get_corpus: _GetCorpus,
    doc_id_for_position: _DocIdForPosition,
) -> None:
    """Bind the three server-owned index operations used by this router."""
    global _get_index, _get_corpus, _doc_id_for_position
    _get_index = get_index
    _get_corpus = get_corpus
    _doc_id_for_position = doc_id_for_position


def _document_runtime() -> tuple[_GetIndex, _GetCorpus, _DocIdForPosition]:
    if _get_index is None or _get_corpus is None or _doc_id_for_position is None:
        raise RuntimeError("Document routes wurden nicht an die Server-Laufzeit gebunden.")
    return _get_index, _get_corpus, _doc_id_for_position


@router.get(
    "/docs/search",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [
                        {
                            "doc_id": 31,
                            "score": 24.0,
                            "snippet": "... We depend on others for essential energy . ...",
                        }
                    ]
                }
            }
        }
    },
)
async def docs_search(
    term: str,
    top_n: int = 5,
    snippet: int = 30,
    metric: str | None = None,
) -> list[dict]:
    """Return ranked document hits."""
    term = term.strip()
    if not term:
        return []
    try:
        get_index, _, _ = _document_runtime()
        index = get_index()
        return document_search(
            index,
            term,
            top_n=max(1, int(top_n)),
            snippet=max(1, int(snippet)),
            metric=metric,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=exception_text(exc)) from exc


@router.get(
    "/doc/snippet",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "doc_id": 0,
                        "doc": "sotu-1945-Truman",
                        "meta": {"president": "Harry S. Truman", "party": "Democratic", "year": "1945"},
                        "pos": 123,
                        "ctx": 80,
                        "doc_start": 0,
                        "doc_end": 900,
                        "start_pos": 43,
                        "end_pos": 204,
                        "left": "...",
                        "kw": "freedom",
                        "right": "...",
                        "text": "... freedom ...",
                    }
                }
            }
        }
    },
)
async def doc_snippet_endpoint(
    pos: int,
    ctx: int = 80,
    corpus: str = "default",
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> Dict[str, Any]:
    """Return an expanded snippet around ``pos`` constrained to the document."""
    from candyconc.services.backend.pii_filter import mask_pii
    from candyconc.utils.text_normalize import normalize_index_display_text

    _, get_corpus, doc_id_for_position = _document_runtime()
    idx = get_corpus(corpus)
    doc_bounds = _doc_bounds_for_index(idx)
    # Reject an invalid position instead of silently clamping to the first doc.
    token_count = int(idx.fast_index.token_store.token_count)
    if int(pos) < 0 or int(pos) >= token_count:
        raise ApiError(404, "document.pos_out_of_corpus", lt("pos ausserhalb des Korpus", "pos is outside the corpus"))
    doc_id = doc_id_for_position(idx, int(pos), doc_bounds)

    doc_start = int(doc_bounds[doc_id])
    doc_end = (
        int(doc_bounds[doc_id + 1])
        if (doc_id + 1) < int(doc_bounds.size)
        else token_count
    )

    ctx = max(1, min(int(ctx), 600))
    start_pos = max(doc_start, int(pos) - ctx)
    end_pos = min(doc_end, int(pos) + ctx + 1)

    word_lex = idx.fast_index.lexicons.word
    if word_lex is None:
        raise ApiError(503, "index.word_lexicon_missing", lt("Word Lexikon fehlt", "Word lexicon missing"))

    ids = idx.fast_index.token_store.word_stream.get_range(start_pos, end_pos)
    if ids.size == 0:
        raise ApiError(404, "document.snippet_unavailable", lt("Kein Snippet verfügbar", "No snippet available"))

    offset = int(pos) - start_pos
    if offset < 0 or offset >= int(ids.size):
        raise ApiError(
            400, "document.pos_out_of_snippet", lt("pos liegt ausserhalb des Snippets", "pos is outside the snippet")
        )

    words = strings_for_ids(
        word_lex.offsets,
        word_lex.strings_view,
        ids.astype(np.uint32, copy=False),
        True,
    )
    left_words = [str(word) for word in words[:offset]]
    kw_word = str(words[offset])
    right_words = [str(word) for word in words[offset + 1 :]]

    # Original spacing (whitespace_after.bin), under the same condition as the
    # full text below: the side file is there and masking is off. The anchor
    # then reads like the concordance line and the full text ("soul. No").
    from candyconc.services.backend.kwic import _apply_whitespace_to_row, _whitespace_after_for
    from candyconc.services.backend.pii_filter import _pii_mask_enabled

    ws = _whitespace_after_for(idx) if not _pii_mask_enabled() else None
    if ws is not None:
        spaced = _apply_whitespace_to_row(
            {"pos": int(pos), "left": " ".join(left_words), "kw": kw_word, "right": " ".join(right_words)},
            ws,
        )
        if "token_starts" in spaced:
            left = normalize_index_display_text(str(spaced["left"])).strip()
            kw_word = normalize_index_display_text(str(spaced["kw"]))
            right = normalize_index_display_text(str(spaced["right"])).strip()
            text = (
                left
                + (" " if left and spaced.get("ws_before_kw") else "")
                + kw_word
                + (" " if right and spaced.get("ws_after_kw") else "")
                + right
            ).strip()
            doc_label, meta = _doc_meta_for_doc_id(idx, doc_id)
            return {
                "doc_id": int(doc_id),
                "doc": doc_label,
                "meta": meta,
                "pos": int(pos),
                "ctx": int(ctx),
                "doc_start": doc_start,
                "doc_end": doc_end,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "left": left,
                "kw": kw_word,
                "right": right,
                "text": text,
                "ws_before_kw": bool(spaced.get("ws_before_kw")),
                "ws_after_kw": bool(spaced.get("ws_after_kw")),
            }

    left_raw = " ".join(left_words).strip()
    right_raw = " ".join(right_words).strip()
    left = (
        mask_pii(left_raw, start_pos=start_pos, index=idx, tokens=list(left_words))
        if left_raw
        else left_raw
    )
    kw_word = (
        mask_pii(kw_word, start_pos=int(pos), index=idx, tokens=[kw_word])
        if kw_word
        else kw_word
    )
    right = (
        mask_pii(right_raw, start_pos=int(pos) + 1, index=idx, tokens=list(right_words))
        if right_raw
        else right_raw
    )
    left = normalize_index_display_text(left)
    kw_word = normalize_index_display_text(kw_word)
    right = normalize_index_display_text(right)
    text = normalize_index_display_text(" ".join([left, kw_word, right]).strip())

    doc_label, meta = _doc_meta_for_doc_id(idx, doc_id)
    return {
        "doc_id": int(doc_id),
        "doc": doc_label,
        "meta": meta,
        "pos": int(pos),
        "ctx": int(ctx),
        "doc_start": doc_start,
        "doc_end": doc_end,
        "start_pos": start_pos,
        "end_pos": end_pos,
        "left": left,
        "kw": kw_word,
        "right": right,
        "text": text,
    }


_DOC_REF_MAPS: "weakref.WeakKeyDictionary[Any, tuple[int, dict[str, list[int]]]]" = weakref.WeakKeyDictionary()


def _document_identifier_map(idx: Any) -> dict[str, list[int]]:
    """``metadata doc_id -> document numbers``, built once per open index."""
    md = idx.fast_index.doc_metadata
    n_docs = len(md)
    cached = _DOC_REF_MAPS.get(idx)
    if cached is not None and cached[0] == n_docs:
        return cached[1]
    mapping: dict[str, list[int]] = {}
    for number in range(n_docs):
        meta = md.get(number) or {}
        ref = meta.get("doc_id")
        if ref is None or str(ref) == "":
            continue
        mapping.setdefault(str(ref), []).append(number)
    try:
        _DOC_REF_MAPS[idx] = (n_docs, mapping)
    except TypeError:  # pragma: no cover - index objects without weakref support
        pass
    return mapping


def _document_number(idx: Any, ref: str, *, by: str, doc_count: int) -> int:
    """Resolve a document number or a document identifier to the number."""
    mode = str(by or "auto").strip().lower()
    if mode not in {"auto", "index", "doc_id"}:
        raise ApiError(
            422, "document.by_invalid", lt("by muss auto, index oder doc_id sein", "by must be auto, index or doc_id")
        )
    text = str(ref or "").strip()
    if not text:
        raise ApiError(422, "document.doc_id_missing", lt("doc_id fehlt", "doc_id is missing"))
    is_number = text.isascii() and text.isdigit()
    if mode == "index" or (mode == "auto" and is_number):
        if not is_number:
            raise ApiError(
                422,
                "document.by_index_needs_number",
                lt("by=index verlangt eine Dokumentnummer", "by=index requires a document number"),
            )
        return int(text)
    matches = _document_identifier_map(idx).get(text, [])
    if not matches:
        raise ApiError(
            404,
            "document.not_found",
            lt("Dokument nicht gefunden: {doc}", "Document not found: {doc}"),
            doc=text,
        )
    if len(matches) > 1:
        raise ApiError(
            409,
            "document.identifier_ambiguous",
            lt(
                "Die Kennung {doc} gehört zu {count} Dokumenten "
                "(Nummern {numbers}). "
                "Bitte die Dokumentnummer verwenden.",
                "The identifier {doc} belongs to {count} documents "
                "(numbers {numbers}). "
                "Use the document number.",
            ),
            doc=text,
            count=len(matches),
            numbers=", ".join(str(n) for n in matches[:20]),
        )
    return int(matches[0])


@router.get(
    "/document/{doc_id}",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "doc_id": 0,
                        "doc": "sotu-1945-Truman",
                        "meta": {"president": "Harry S. Truman", "party": "Democratic", "year": "1945"},
                        "text": "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS …",
                        "doc_start": 0,
                        "doc_end": 900,
                    }
                }
            }
        }
    },
)
async def document_endpoint(
    doc_id: str,
    corpus: str = "default",
    by: str = "auto",
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> Dict[str, Any]:
    """Return the full text of one document.

    ``doc_id`` is the internal document number (what KWIC rows and the
    document list carry as ``doc_id``) or the document identifier of the
    import (metadata ``doc_id``, the ``--id-column`` value). ``by=auto``
    reads digits as the number and anything else as the identifier,
    ``by=index`` and ``by=doc_id`` force one reading (for identifiers that
    consist of digits). The answer names both as ``doc_id`` and ``doc``.
    """
    from candyconc.services.backend.pii_filter import mask_pii
    from candyconc.utils.text_normalize import normalize_index_display_text

    _, get_corpus, _ = _document_runtime()
    idx = get_corpus(corpus)
    doc_bounds = _doc_bounds_for_index(idx)
    doc_id = _document_number(idx, doc_id, by=by, doc_count=int(doc_bounds.size))
    if doc_id < 0 or doc_id >= int(doc_bounds.size):
        raise ApiError(404, "document.doc_id_not_found", lt("doc_id nicht gefunden", "doc_id not found"))

    token_count = int(idx.fast_index.token_store.token_count)
    doc_start = int(doc_bounds[doc_id])
    doc_end = (
        int(doc_bounds[doc_id + 1])
        if (doc_id + 1) < int(doc_bounds.size)
        else token_count
    )

    word_lex = idx.fast_index.lexicons.word
    if word_lex is None:
        raise ApiError(503, "index.word_lexicon_missing", lt("Word Lexikon fehlt", "Word lexicon missing"))

    ids = idx.fast_index.token_store.word_stream.get_range(doc_start, doc_end)
    if ids.size == 0:
        raise ApiError(404, "document.empty", lt("Dokument leer", "Document is empty"))

    words = strings_for_ids(
        word_lex.offsets,
        word_lex.strings_view,
        ids.astype(np.uint32, copy=False),
        True,
    )
    # The full text is joined with the original spacing from
    # whitespace_after.bin, which every import writes since builder revision 3
    # ("im Judentum, im Islam." instead of "im Judentum , im Islam ."). Same
    # condition as the concordance rows (core.source_spacing): the side file is
    # there AND masking is off. mask_pii (pii_filter.py) rebuilds its output
    # with " ".join(), so masking would shift the flags and the character
    # anchors. Without the side file the text is byte-identical to before.
    #
    # The imports stay local like the two above, a module import would create
    # a cycle through kwic.py.
    from candyconc.services.backend.kwic import _join_ws, _whitespace_after_for
    from candyconc.services.backend.pii_filter import _pii_mask_enabled

    tokens = [str(word) for word in words]
    ws = _whitespace_after_for(idx) if not _pii_mask_enabled() else None
    text_raw = (
        " ".join(tokens) if ws is None else _join_ws(tokens, doc_start, ws)
    ).strip()
    text = (
        mask_pii(text_raw, start_pos=doc_start, index=idx, tokens=tokens)
        if text_raw
        else text_raw
    )
    text = normalize_index_display_text(text)

    doc_label, meta = _doc_meta_for_doc_id(idx, doc_id)
    return {
        "doc_id": int(doc_id),
        "doc": doc_label,
        "meta": meta,
        "text": text,
        "doc_start": doc_start,
        "doc_end": doc_end,
    }


#: A descriptive field with this name names the document in the reader.
_TITLE_FIELD = "title"


def _reader_fields(idx: Any, sample_meta: dict | None) -> dict[str, Any]:
    """Reader fields derived from the metadata schema of the corpus.

    ``label_fields`` are the fields that tell documents apart, the most
    general first (:func:`candyconc.core.meta_index.descriptive_fields`).
    ``title_field`` is ``title`` when the corpus has such a descriptive field.
    Without a metadata index the fields of a listed document stand in, and
    fields with one value cannot be recognised (``basis: "document"``).
    """
    meta_index = getattr(getattr(idx, "fast_index", None), "meta_index", None)
    if meta_index is not None and getattr(meta_index, "fields", None):
        fields = descriptive_fields(meta_index.value_counts())
        basis = "meta_index"
    else:
        fields = [key for key in (sample_meta or {}) if key not in DOCUMENT_LABEL_FIELDS]
        basis = "document"
    title = _TITLE_FIELD if _TITLE_FIELD in fields else None
    return {
        "title_field": title,
        "label_fields": [field for field in fields if field != title],
        "basis": basis,
    }


#: Harte Obergrenze einer Seite. Der Reader blaettert, er schuettet nicht aus.
_LISTEN_MAX = 200

#: So viele Token stehen in der Vorschau.
_VORSCHAU_TOKEN = 25


@router.get(
    "/docs/list",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "total": 65,
                        "offset": 0,
                        "limit": 50,
                        "reader_fields": {
                            "title_field": "title",
                            "label_fields": ["party", "decade", "president", "date", "year"],
                            "basis": "meta_index",
                        },
                        "items": [
                            {
                                "doc_id": 0,
                                "doc": "sotu-1945-Truman",
                                "meta": {
                                    "title": "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS",
                                    "party": "Democratic",
                                    "decade": "1940s",
                                    "president": "Harry S. Truman",
                                    "date": "1945-04-16",
                                    "year": "1945",
                                },
                                "token_count": 2193,
                                "preview": "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS\n\nApril 16, 1945\n\nMr. Speaker, Mr. President,",
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def docs_list_endpoint(
    corpus: str = "default",
    offset: int = 0,
    limit: int = 50,
    docset_id: str | None = None,
    scope_docset_id: str | None = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> Dict[str, Any]:
    """A pageable list of the documents of a corpus, for the reader.

    ``docset_id`` (the reader's own field filter) and ``scope_docset_id``
    (the active scope of the interface, a subcorpus or metadata filter)
    restrict the list. With both, it holds the documents in both.

    Each item carries its token count, a preview of the first 25 tokens and
    the metadata fields named in ``reader_fields``: ``title_field`` names the
    document, ``label_fields`` tell documents apart, the most general first.
    Both come from the metadata schema of the corpus. Fields with a single
    value and the fields that repeat the document label are left out of the
    items. The full metadata of a document comes from ``/document/{doc_id}``.
    """
    # The path is /docs/list and not /documents because route_matrix
    # classifies by the prefix /api/v1/docs. Totals and token counts come from
    # doc_bounds (O(1)), the preview from this response, never from one
    # /document call per row.
    from candyconc.services.backend.pii_filter import mask_pii
    from candyconc.utils.text_normalize import normalize_index_display_text

    _, get_corpus, _ = _document_runtime()
    idx = get_corpus(corpus)
    doc_bounds = _doc_bounds_for_index(idx)
    alle = int(doc_bounds.size)

    # DURCHSTOEBERN heisst filtern koennen. Ohne dies waere der Leser eine
    # Liste von 250.535 Dokumenten in der Reihenfolge des Indexbaus, und
    # niemand liest ein Korpus von vorne. Das Docset kommt aus
    # /analysis/docset_from_meta, also aus derselben Naht, die schon
    # Kontrast und Keyness fuettert: eine ZWEITE Filterlogik hier waere
    # genau die Naht, an der beide auseinanderlaufen.
    sichtbare = None
    for kennung in (docset_id, scope_docset_id):
        if not kennung:
            continue
        from candyconc.services.backend.docsets import _get_docset

        eintrag = _get_docset(str(kennung))
        if str(eintrag.get("corpus") or "default") != str(corpus or "default"):
            raise ApiError(
                422,
                "docset.other_corpus",
                lt("docset_id gehört zu anderem Korpus", "docset_id belongs to a different corpus"),
            )
        ids = np.unique(np.asarray(eintrag.get("doc_ids"), dtype=np.int64))
        sichtbare = ids if sichtbare is None else np.intersect1d(sichtbare, ids)
    gesamt = int(sichtbare.size) if sichtbare is not None else alle

    try:
        offset = max(0, int(offset))
        limit = int(limit)
    except (TypeError, ValueError):
        raise ApiError(
            422,
            "document.paging_not_integer",
            lt("offset und limit müssen ganze Zahlen sein", "offset and limit must be integers"),
        )
    if limit < 1:
        raise ApiError(422, "document.limit_invalid", lt("limit muss >= 1 sein", "limit must be >= 1"))
    limit = min(limit, _LISTEN_MAX)

    token_count = int(idx.fast_index.token_store.token_count)
    word_lex = idx.fast_index.lexicons.word
    # Dieselbe Bedingung wie im Volltext und in der KWIC-Naht: quellentreu
    # nur mit Sidecar UND ohne Maskierung.
    from candyconc.services.backend.kwic import _join_ws, _whitespace_after_for
    from candyconc.services.backend.pii_filter import _pii_mask_enabled

    ws = _whitespace_after_for(idx) if not _pii_mask_enabled() else None

    if sichtbare is not None:
        fenster = [int(i) for i in sichtbare[offset:offset + limit]]
    else:
        fenster = list(range(offset, min(offset + limit, gesamt)))

    items = []
    reader_fields: dict[str, Any] | None = None
    row_fields: list[str] = []
    for doc_id in fenster:
        doc_start = int(doc_bounds[doc_id])
        # Die Dokumentgrenze folgt aus dem NAECHSTEN Dokument des Index,
        # nicht aus der Position in der gefilterten Liste. Mit `gesamt`
        # gerechnet waere die letzte Zeile eines Docsets bis zum
        # Korpusende gelaufen.
        doc_end = (
            int(doc_bounds[doc_id + 1])
            if (doc_id + 1) < alle
            else token_count
        )
        vorschau = ""
        if word_lex is not None and doc_end > doc_start:
            bis = min(doc_start + _VORSCHAU_TOKEN, doc_end)
            ids = idx.fast_index.token_store.word_stream.get_range(doc_start, bis)
            if ids.size:
                woerter = [
                    str(w) for w in strings_for_ids(
                        word_lex.offsets, word_lex.strings_view,
                        ids.astype(np.uint32, copy=False), True,
                    )
                ]
                roh = (
                    " ".join(woerter) if ws is None
                    else _join_ws(woerter, doc_start, ws)
                ).strip()
                if roh:
                    roh = mask_pii(
                        roh, start_pos=doc_start, index=idx, tokens=woerter
                    )
                vorschau = normalize_index_display_text(roh)
        doc_label, meta = _doc_meta_for_doc_id(idx, doc_id)
        meta = meta if isinstance(meta, dict) else {}
        if reader_fields is None:
            reader_fields = _reader_fields(idx, meta)
            row_fields = (
                [reader_fields["title_field"]] if reader_fields["title_field"] else []
            ) + list(reader_fields["label_fields"])
        items.append({
            "doc_id": int(doc_id),
            "doc": doc_label,
            "meta": {
                k: meta[k] for k in row_fields
                if meta.get(k) not in (None, "")
            },
            "token_count": doc_end - doc_start,
            "preview": vorschau,
        })

    if reader_fields is None:
        reader_fields = _reader_fields(idx, None)
    return {
        "total": gesamt,
        "offset": offset,
        "limit": limit,
        "reader_fields": reader_fields,
        "items": items,
    }
