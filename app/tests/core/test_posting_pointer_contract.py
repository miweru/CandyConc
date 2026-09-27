from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cqlhpc.ast import MetaCond, MetaExpr
from candyconc.core.fast_index_backend import _LexiconPostingIndex
from candyconc.core.meta_index import MetaIndex
from candyconc.core import index_format
from scripts import build_fast_index
import candyconc.core.meta_index as meta_index_mod


def _docset_mask_from_ids(ids: np.ndarray, doc_count: int) -> np.ndarray:
    mask = np.zeros(int(doc_count), dtype=np.bool_)
    if ids.size:
        valid = ids[(ids >= 0) & (ids < int(doc_count))]
        mask[valid.astype(np.int64, copy=False)] = True
    return mask


def test_string_posting_pointer_keeps_highest_lexicon_key(tmp_path: Path) -> None:
    base = tmp_path / "word_lexicon.ngram3"
    build_fast_index._write_string_postings_index(
        base,
        {"aaa": [3, 1], "mmm": [2], "zzz": [9, 8]},
        {"kind": "ngram", "items": 3},
    )

    idx = _LexiconPostingIndex(Path(f"{base}.bin"))

    assert idx.ptr.shape[0] == idx.lex.vocab_size + 2
    np.testing.assert_array_equal(idx.ids_for("zzz"), np.array([8, 9], dtype=np.uint32))


def test_meta_posting_pointer_keeps_highest_string_value(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(meta_index_mod, "docset_mask_from_ids", _docset_mask_from_ids)
    build_fast_index._build_meta_index(
        {
            0: {"source": "aaa"},
            1: {"source": "mmm"},
            2: {"source": "zzz"},
        },
        tmp_path,
        doc_count=3,
    )

    idx = MetaIndex(tmp_path)
    idx.load()
    mask = idx.mask_for_expr(
        MetaExpr(kind="cond", parts=(MetaCond("source", "=", "zzz"),))
    )

    field = idx.fields["source"]
    assert field._str_offsets is not None
    assert field._lex is not None
    assert field._str_offsets.shape[0] == field._lex.vocab_size + 2
    np.testing.assert_array_equal(mask, np.array([False, False, True], dtype=np.bool_))
    assert ("source", "zzz", 1) in idx.sample_str_values(max_scan=10)


def test_unit_set_docset_keeps_highest_term() -> None:
    # Two units (e.g. documents): unit 0 covers ids [1, 3], unit 1 covers [2, 3].
    # Term id 3 is the highest in the vocabulary and appears in both units.
    ids = np.array([1, 3, 2, 3], dtype=np.uint32)
    bounds = np.array([0, 2], dtype=np.uint32)
    vocab_size = 3

    offsets, out = build_fast_index._build_unit_sets_from_bounds(
        ids, bounds, token_count=int(ids.size), vocab_size=vocab_size
    )

    # The docset pointer must carry the terminal sentinel so the reader can take
    # offsets[tid + 1] for the highest term id (regression: it was vocab_size+1).
    assert offsets.shape[0] == index_format.postings_ptr_len(vocab_size)

    # Reader convention: ids_for(tid) == out[offsets[tid]:offsets[tid + 1]].
    highest = vocab_size
    docset_highest = out[int(offsets[highest]):int(offsets[highest + 1])]
    np.testing.assert_array_equal(np.sort(docset_highest), np.array([0, 1], dtype=np.uint32))
