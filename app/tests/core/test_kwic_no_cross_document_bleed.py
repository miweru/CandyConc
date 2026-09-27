"""Regression test for D2(a) — KWIC document-boundary clamp.

A KWIC context window must never spill past the document that contains the node
token. Before the fix, all three SVB KWIC kernels in ``_fast_index.pyx``
(``kwic_rows_svb`` packed branch, ``kwic_rows_svb`` scalar branch, and
``kwic_rows_svb_compact_buffers``) clamped only at the corpus ends, so a node at
a document's last token pulled left/right context out of the neighbouring
document.

These tests run against the REAL bench Fast Index (no mocks) and assert, for
every kernel, that the rendered left/right context for boundary-adjacent nodes
matches a ground-truth window recomputed with an explicit document clamp.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from candyconc.core.fast_index_backend import FastIndexBackend

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)

CTX = 5


@pytest.fixture(scope="module")
def backend() -> FastIndexBackend:
    return FastIndexBackend(Path(INDEX_PATH))


def _doc_bounds(backend: FastIndexBackend) -> np.ndarray:
    return (
        backend.boundaries.document._positions
        if backend.boundaries and backend.boundaries.document
        else np.array([], dtype=np.uint32)
    )


def _doc_range(db: np.ndarray, tok: int, pos: int) -> tuple[int, int]:
    i = int(np.searchsorted(db, pos, side="right")) - 1
    start = int(db[i])
    end = int(db[i + 1]) if i + 1 < db.size else tok
    return start, end


def _expected_window(backend: FastIndexBackend, db: np.ndarray, tok: int, pos: int):
    ws = backend.token_store.word_stream
    wlex = backend.lexicons.word
    ds, de = _doc_range(db, tok, pos)
    ls = max(pos - CTX, ds)
    re_ = min(pos + CTX + 1, de)
    left = [wlex.get_string(int(ws.get(j))) for j in range(ls, pos) if int(ws.get(j)) != 0]
    right = [wlex.get_string(int(ws.get(j))) for j in range(pos + 1, re_) if int(ws.get(j)) != 0]
    return " ".join(left), " ".join(right)


def _boundary_last_positions(db: np.ndarray, tok: int, n: int = 60) -> list[int]:
    return sorted({int(db[i]) - 1 for i in range(1, min(db.size, n)) if int(db[i]) - 1 >= 0})


def _boundary_first_positions(db: np.ndarray, tok: int, n: int = 200) -> list[int]:
    return sorted({int(db[i]) for i in range(1, min(db.size, n)) if int(db[i]) < tok})


def test_index_has_multiple_documents(backend: FastIndexBackend) -> None:
    db = _doc_bounds(backend)
    assert db.size > 1, "test needs a multi-document index to be meaningful"


def test_scalar_kernel_no_right_bleed(backend: FastIndexBackend) -> None:
    db = _doc_bounds(backend)
    tok = int(backend.token_store.token_count)
    last = _boundary_last_positions(db, tok)
    # n < 32 forces the scalar branch of kwic_rows_svb.
    pos = np.array(last[:10], dtype=np.uint32)
    rows = backend.kwic_rows_for_positions(pos, CTX, include_arcs=False, include_file=False)
    by_pos = {int(r["pos"]): (r["left"], r["right"]) for r in rows}
    for p in last[:10]:
        el, er = _expected_window(backend, db, tok, p)
        assert by_pos[p] == (el, er), f"scalar kernel bled at pos {p}"


def test_packed_kernel_no_right_bleed(backend: FastIndexBackend) -> None:
    db = _doc_bounds(backend)
    tok = int(backend.token_store.token_count)
    last = _boundary_last_positions(db, tok)
    assert len(last) >= 32, "need >=32 positions to exercise the packed branch"
    pos = np.array(last, dtype=np.uint32)
    rows = backend.kwic_rows_for_positions(pos, CTX, include_arcs=False, include_file=False)
    by_pos = {int(r["pos"]): (r["left"], r["right"]) for r in rows}
    for p in last:
        el, er = _expected_window(backend, db, tok, p)
        assert by_pos[p] == (el, er), f"packed kernel bled at pos {p}"


def test_compact_buffers_kernel_no_right_bleed(backend: FastIndexBackend) -> None:
    db = _doc_bounds(backend)
    tok = int(backend.token_store.token_count)
    last = _boundary_last_positions(db, tok)
    pos = np.array(last, dtype=np.uint32)
    crows = backend.kwic_compact_rows_for_positions(pos, CTX)
    assert crows is not None
    by_pos = {int(r[3]): (r[0], r[2]) for r in crows}
    for p in last:
        el, er = _expected_window(backend, db, tok, p)
        assert by_pos[p] == (el, er), f"compact_buffers kernel bled at pos {p}"


def test_left_context_empty_at_document_start(backend: FastIndexBackend) -> None:
    """A node that is the FIRST token of a document must have empty left context,
    even though the preceding token (last of the previous doc) is non-empty —
    which is exactly what a missing clamp would have leaked."""
    db = _doc_bounds(backend)
    tok = int(backend.token_store.token_count)
    ws = backend.token_store.word_stream
    first = _boundary_first_positions(db, tok)
    assert first, "need document-start positions"

    # Sanity: the fix is only meaningful if pos-1 is genuinely non-empty (i.e.
    # an unclamped window WOULD have bled). Confirm that holds for the sample.
    would_bleed = sum(1 for p in first if p > 0 and int(ws.get(p - 1)) != 0)
    assert would_bleed > 0, "sample does not exercise the bleed condition"

    pos = np.array(first, dtype=np.uint32)
    rows = backend.kwic_rows_for_positions(pos, CTX, include_arcs=False, include_file=False)
    by_pos = {int(r["pos"]): (r["left"], r["right"]) for r in rows}
    for p in first:
        left, _right = by_pos[p]
        assert left == "", f"left context bled across doc start at pos {p}: {left!r}"
