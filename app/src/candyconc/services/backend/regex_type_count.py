# -*- coding: utf-8 -*-
"""Corpus count of a single regex cell over the type frequencies.

On a large corpus the positional path refuses ``query_count`` for
``[word=".{13,}"]`` with „Regex Treffer zu gross … 8.343.253 Tokens gegen
eine Grenze von 5.000.000“, and ``[word=".{20,}"]`` with „243.746 Typen“
against 200,000. The limits protect the positional evaluation. A corpus
count of a single cell needs no positions: it is the sum of the frequencies
of all types that fully match the pattern, the same resolution as in CQL
matching (``cqlhpc.predicates._regex_to_type_ids``), only without a limit.
Without this path a model queried 28 single character classes instead of
one count, and the question took 4,464 seconds.

Only without a subcorpus, only a single cell ``[word="…"]`` or
``[lemma="…"]`` without a flag. The count subtracts the line break marker
``|LBR|`` like the row path (``_exact_cql_count_sentinel_dropped``).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

import numpy as np

_EINZELZELLE = re.compile(r'^\s*(?:cql:)?\s*\[\s*(word|lemma)\s*=\s*"((?:[^"\\]|\\.)*)"\s*\]\s*$', re.I)


def einzelzelle(query: str) -> Optional[tuple[str, str]]:
    """``(attribut, muster)`` einer einzelnen Zelle ohne Flag, sonst None."""
    m = _EINZELZELLE.match(str(query or ""))
    if not m:
        return None
    return m.group(1).lower(), re.sub(r'\\"', '"', m.group(2))


def zaehlen(idx: Any, query: str, sentinel_id: Callable[[Any], int]) -> Optional[int]:
    """Die Zählung über die Typfrequenzen, oder None, wenn die Abfrage nicht passt."""
    zelle = einzelzelle(query)
    if zelle is None:
        return None
    attr, muster = zelle
    from cqlhpc.predicates import _regex_to_type_ids, _sum_freqs_for_ids

    lex = getattr(idx.fast_index.lexicons, attr, None)
    if lex is None:
        return None
    ids = _regex_to_type_ids(muster, lex, attr=attr, deckel=False)
    if ids is None or ids.size == 0:
        return 0
    if attr == "word":
        marke = int(sentinel_id(idx) or 0)
        if marke > 0:
            ids = ids[ids != np.int32(marke)]
    return int(_sum_freqs_for_ids(lex, ids))


def treffer_je_dokument(idx: Any, query: str, sentinel_id: Callable[[Any], int]) -> Optional[np.ndarray]:
    """Hits per document of a single cell over the type postings, without a limit.

    For the breakdown ``nach``: counting over positions in the subcorpus per
    value runs into the type limit. ``[word=".{20,}"]`` with nach="register"
    would end with „243.746 Typen gegen eine Grenze von 200.000“, and
    register rates would only be available from about 21 letters on. Here the
    positions of the types are merged ONCE and counted per document, the same
    types as in ``zaehlen``.
    """
    zelle = einzelzelle(query)
    if zelle is None:
        return None
    attr, muster = zelle
    from cqlhpc.predicates import _regex_to_type_ids

    lex = getattr(idx.fast_index.lexicons, attr, None)
    vereinigen = getattr(idx.fast_index, "_union_positions_for_ids", None)
    if lex is None or vereinigen is None:
        return None
    anfaenge = np.asarray(idx.fast_index.boundaries.document._positions, dtype=np.int64)
    ids = _regex_to_type_ids(muster, lex, attr=attr, deckel=False)
    if ids is None or ids.size == 0:
        return np.zeros(anfaenge.size, dtype=np.int64)
    if attr == "word":
        marke = int(sentinel_id(idx) or 0)
        if marke > 0:
            ids = ids[ids != np.int32(marke)]
    positionen = np.asarray(vereinigen(attr, np.asarray(ids, dtype=np.int32)), dtype=np.int64)
    dokumente = np.searchsorted(anfaenge, positionen, side="right") - 1
    return np.bincount(dokumente[dokumente >= 0], minlength=anfaenge.size).astype(np.int64)
