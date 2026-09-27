import asyncio

import numpy as np

from candyconc.services.backend import server


class _DocsetIndex:
    def __init__(self, doc_bounds, token_count):
        self.doc_bounds = np.asarray(doc_bounds, dtype=np.uint32)
        self._token_count = int(token_count)
        self.docset_token_count_calls = []

    def token_count(self):
        return self._token_count

    def docset_token_count(self, doc_ids):
        ids = np.asarray(doc_ids, dtype=np.int64)
        self.docset_token_count_calls.append(ids.astype(int).tolist())
        total = 0
        for doc_id in ids.tolist():
            start = int(self.doc_bounds[int(doc_id)])
            next_doc = int(doc_id) + 1
            end = (
                int(self.doc_bounds[next_doc])
                if next_doc < int(self.doc_bounds.size)
                else self._token_count
            )
            total += max(0, end - start)
        return total


def test_docset_local_offsets_remap_non_prefix_docset_positions():
    doc_bounds = np.asarray([0, 100, 200, 300], dtype=np.uint32)
    doc_ids = np.asarray([2, 3], dtype=np.uint32)
    global_offsets = np.asarray([210, 250, 320], dtype=np.uint32)

    local_offsets = server._docset_local_offsets(
        global_offsets,
        doc_bounds,
        doc_ids,
        token_count=400,
    )

    assert local_offsets.tolist() == [10, 50, 120]

    token_count = 200
    partitions = 4
    scale = float(partitions) / float(token_count)
    idxs = np.clip((local_offsets * scale).astype(np.int64), 0, partitions - 1)
    bins = np.bincount(idxs, minlength=partitions)

    assert bins.tolist() == [1, 1, 1, 0]


def test_docset_local_doc_ids_are_sorted_unique_and_valid():
    doc_bounds = np.asarray([0, 10, 20, 35], dtype=np.uint32)
    doc_ids = np.asarray([2, 1, 2, 999, 1], dtype=np.uint32)

    normalized = server._docset_local_doc_ids(doc_ids, doc_bounds)

    assert normalized.tolist() == [1, 2]


def test_docset_local_offsets_ignore_duplicates_and_offsets_outside_docset():
    doc_bounds = np.asarray([0, 10, 20, 35], dtype=np.uint32)
    doc_ids = np.asarray([2, 1, 2], dtype=np.uint32)
    global_offsets = np.asarray([9, 10, 19, 20, 34, 35], dtype=np.uint32)

    local_offsets = server._docset_local_offsets(
        global_offsets,
        doc_bounds,
        doc_ids,
        token_count=35,
    )

    assert local_offsets.tolist() == [0, 9, 10, 24]


def test_docset_local_offsets_keep_doc_start_and_drop_doc_end_boundaries():
    doc_bounds = np.asarray([0, 10, 20], dtype=np.uint32)
    doc_ids = np.asarray([1, 2], dtype=np.uint32)
    global_offsets = np.asarray([9, 10, 19, 20, 29, 30], dtype=np.uint32)

    local_offsets = server._docset_local_offsets(
        global_offsets,
        doc_bounds,
        doc_ids,
        token_count=30,
    )

    assert local_offsets.tolist() == [0, 9, 10, 19]


def test_docset_local_offsets_empty_docset_returns_empty_array():
    doc_bounds = np.asarray([0, 10, 20], dtype=np.uint32)
    global_offsets = np.asarray([0, 10, 19], dtype=np.uint32)

    local_offsets = server._docset_local_offsets(
        global_offsets,
        doc_bounds,
        np.asarray([], dtype=np.uint32),
        token_count=20,
    )

    assert local_offsets.tolist() == []


def test_analysis_dispersion_docset_local_uses_unique_doc_ids_for_denominator(monkeypatch):
    doc_bounds = np.asarray([0, 10, 20, 35], dtype=np.uint32)
    idx = _DocsetIndex(doc_bounds, token_count=35)
    docset_mask = np.asarray([False, True, True], dtype=np.bool_)
    docset = {
        "corpus": "default",
        "doc_ids": np.asarray([2, 1, 1], dtype=np.uint32),
        "docset_mask": docset_mask,
    }
    global_offsets = np.asarray([9, 10, 19, 20, 34, 35], dtype=np.uint32)

    def fake_positions(idx_arg, term, *, docset_mask):
        assert idx_arg is idx
        assert term == "term"
        assert docset_mask is docset["docset_mask"]
        return global_offsets

    monkeypatch.setattr(server, "get_corpus", lambda corpus: idx)
    monkeypatch.setattr(server, "_get_docset", lambda docset_id: docset)
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx_arg: doc_bounds)
    monkeypatch.setattr(server, "_dispersion_positions_for_term", fake_positions)

    result = asyncio.run(server.analysis_dispersion(term="term", docset_id="docset"))

    # Document-based dispersion: partitions are per docset document (docs 1 and 2),
    # not equal token slices. doc1 spans [10,20) -> hits at 10,19; doc2 spans
    # [20,35) -> hits at 20,34 (35 is the corpus boundary and excluded).
    assert idx.docset_token_count_calls == [[1, 2]]
    assert result["unit"] == "documents"
    assert result["partitions"] == [2, 2]
    assert result["doc_sizes"] == [10, 15]


def test_analysis_dispersion_offsets_empty_docset_returns_docset_local_empty(monkeypatch):
    doc_bounds = np.asarray([0, 10, 20], dtype=np.uint32)
    idx = _DocsetIndex(doc_bounds, token_count=20)
    docset = {
        "corpus": "default",
        "doc_ids": np.asarray([], dtype=np.uint32),
        "docset_mask": np.zeros(3, dtype=np.bool_),
    }

    monkeypatch.setattr(server, "get_corpus", lambda corpus: idx)
    monkeypatch.setattr(server, "_get_docset", lambda docset_id: docset)
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx_arg: doc_bounds)
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *args, **kwargs: np.asarray([0, 10, 19], dtype=np.uint32),
    )

    result = asyncio.run(server.analysis_dispersion_offsets(term="term", docset_id="empty"))

    # An empty docset still resolves to a docset_local basis (doc_ids is an
    # empty array, not None), yielding the partial-state superset response with
    # no offsets, a zero token basis, and no fallback/limitations. The honest
    # completeness envelope (DISP-1) reports the full set is served: total 0,
    # not truncated, no next_offset, not partial.
    assert result == {
        "offsets": [],
        "basis": "docset_local",
        "token_count": 0,
        "fallback": False,
        "partial": False,
        "truncated": False,
        "total": 0,
        "next_offset": None,
        "limitations": [],
    }
