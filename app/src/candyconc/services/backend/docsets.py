"""Shared docset storage and helpers independent of server state.

Mutate the LRU cache in place so server, routes and tool wrappers retain
the same object. Query-dependent resolution remains with its callers,
which pass through the server namespace when an override is required."""

import uuid
from collections import OrderedDict
from typing import Any, Dict, Iterable

import numpy as np

from cqlhpc.ast import MetaExpr

from candyconc.entrypoints.errors import ApiError
from candyconc.i18n import lt

_DOCSET_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_DOCSET_CACHE_LIMIT = 192


def _build_meta_expr(filters: Dict[str, Any]) -> MetaExpr | None:
    # Delegates to the canonical core builder. The legacy "transform" alias is
    # applied via translate_meta_field_aliases (opt-in, this service boundary only),
    # exactly reproducing the former inline _canonicalize. Single source of truth.
    from candyconc.core.meta_filters import build_meta_expr, translate_meta_field_aliases

    return build_meta_expr(translate_meta_field_aliases(filters))


def _store_docset(
    corpus: str | None,
    doc_ids: np.ndarray,
    doc_count: int,
) -> str:
    from candyconc.core.fast_index_native import docset_mask_from_ids

    ids = np.asarray(doc_ids, dtype=np.uint32)
    if ids.size:
        mask = docset_mask_from_ids(ids, int(doc_count))
    else:
        mask = np.zeros(doc_count, dtype=np.bool_)
    docset_id = uuid.uuid4().hex
    _DOCSET_CACHE[docset_id] = {
        "corpus": corpus or "default",
        "doc_ids": ids,
        "docset_mask": mask,
    }
    _DOCSET_CACHE.move_to_end(docset_id)
    while len(_DOCSET_CACHE) > _DOCSET_CACHE_LIMIT:
        _DOCSET_CACHE.popitem(last=False)
    return docset_id


def drop_docsets_for_corpora(corpora: Iterable[str]) -> int:
    """Forget the document sets of ``corpora`` (their doc ids refer to an old build)."""
    wanted = {str(name) for name in corpora}
    dropped = 0
    for docset_id, entry in list(_DOCSET_CACHE.items()):
        if str(entry.get("corpus")) in wanted and _DOCSET_CACHE.pop(docset_id, None) is not None:
            dropped += 1
    return dropped


def _get_docset(docset_id: str) -> dict[str, Any]:
    docset = _DOCSET_CACHE.get(docset_id)
    if not docset:
        raise ApiError(404, "docset.not_found", lt("Docset nicht gefunden", "Document set not found"))
    _DOCSET_CACHE.move_to_end(docset_id)
    return docset


def _combine_docset_masks(
    left: np.ndarray | None,
    right: np.ndarray | None,
) -> np.ndarray | None:
    if left is None:
        return right
    if right is None:
        return left
    left_arr = np.asarray(left, dtype=np.bool_)
    right_arr = np.asarray(right, dtype=np.bool_)
    if left_arr.size != right_arr.size:
        raise RuntimeError(
            lt(
                "Docset Masken passen nicht zur Dokumentanzahl.",
                "Document set masks do not match the number of documents.",
            )
        )
    return np.logical_and(left_arr, right_arr)
