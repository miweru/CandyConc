"""Runtime messages of the word search reach the user in the request language.

``domain/query_eval.py`` raised German-only texts for missing document
boundaries, a document set mask of another index, a NOT query over the whole
corpus and a missing native extension. The first two answer as HTTP 503
(``query_count._SERVER_STATE_ERROR_MARKERS``), all of them appear in the
``error`` frame of ``/query/stream``. They are now German and English pairs.
The German text is unchanged, so the markers still classify them.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from candyconc.domain import query_eval
from candyconc.i18n import exception_text, localize
from candyconc.services.backend.query_count import _is_server_state_error


def _index(bounds):
    document = None if bounds is None else SimpleNamespace(_positions=np.asarray(bounds, dtype=np.uint32))
    return SimpleNamespace(fast_index=SimpleNamespace(boundaries=SimpleNamespace(document=document)))


CASES = [
    (None, 2, "Dokumentgrenzen fehlen. Bitte Index neu bauen.", "Document boundaries are missing. Rebuild the index."),
    ([], 2, "Dokumentgrenzen leer. Bitte Index neu bauen.", "Document boundaries are empty. Rebuild the index."),
    (
        [0, 5],
        1,
        "Docset Maske passt nicht zur Dokumentanzahl.",
        "Document set mask does not match the number of documents.",
    ),
]


def _filter(index, mask):
    return query_eval._filter_positions_by_docset_mask(index, np.array([1], dtype=np.uint32), mask)


def _iterate(index, mask):
    return list(query_eval._iter_positions_filtered(iter([1]), index, mask))


@pytest.mark.parametrize("run", [_filter, _iterate], ids=["filter", "iterate"])
@pytest.mark.parametrize(("bounds", "mask_size", "de", "en"), CASES, ids=["missing", "empty", "mask"])
def test_docset_filter_messages_are_pairs(run, bounds, mask_size, de, en):
    with pytest.raises(RuntimeError) as error:
        run(_index(bounds), np.ones(mask_size, dtype=bool))
    assert str(error.value) == de
    assert localize(exception_text(error.value), "en") == en


def test_boundary_messages_still_count_as_server_state():
    for bounds, mask_size, _de, _en in CASES[:2]:
        with pytest.raises(RuntimeError) as error:
            _filter(_index(bounds), np.ones(mask_size, dtype=bool))
        assert _is_server_state_error(str(error.value))


def test_not_over_the_whole_corpus_is_a_pair(monkeypatch):
    monkeypatch.setattr(query_eval, "_complement_sorted_fast", lambda *_a: np.zeros(0, dtype=np.uint32))
    index = SimpleNamespace(num_tokens=lambda: query_eval._NOT_MAX_TOKENS + 1)
    with pytest.raises(RuntimeError) as error:
        query_eval._complement_positions(index, np.zeros(0, dtype=np.uint32), None, False)
    assert str(error.value).startswith("NOT Query zu gross.")
    assert localize(exception_text(error.value), "en") == (
        "NOT query too large. Combine it with a positive term (AND) or set a limit."
    )


def test_a_missing_native_path_is_a_pair(monkeypatch):
    monkeypatch.setattr(query_eval, "_complement_sorted_fast", None)
    index = SimpleNamespace(num_tokens=lambda: 10)
    with pytest.raises(RuntimeError) as error:
        query_eval._complement_positions(index, np.zeros(0, dtype=np.uint32), None, False)
    assert localize(exception_text(error.value), "en") == (
        "The native NOT path is missing. Build the native extension."
    )
