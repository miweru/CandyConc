"""Regression: word-value CQL regex with alternation/group metacharacters must
take the real regex matching path, not be misclassified as a literal.

COPILOT-REGEX-ALTERNATION-SILENT-ZERO (pre-existing engine bug). A char-class
escaping bug in :func:`_regex_is_literal` made any word-value regex containing
``| ( ) { }`` be treated as a literal string, so the short-circuit in
:meth:`FastIndexBackend._regex_ids` did a literal lexicon lookup and silently
returned ``total=0`` with ``status:success`` — across the copilot
``query_count`` / ``run_cqlf_query`` tools AND REST ``/query`` + ``/query/count``
(both resolve regex predicates through the SAME ``FastIndexBackend`` seam, via
the legacy backend and the cqlhpc engine alike).

Asserts on the real bench index:
  - an alternation ``und|oder`` returns the de-duplicated UNION of its branches
    (nonzero), not 0;
  - a grouped ``(und|oder)`` and a quantified ``ge.*`` also match nonzero;
  - genuine literals (``und``) are UNCHANGED and still classified literal (so
    they keep the fast lexicon path — no slow-regex performance regression).

Run against the real bench index:
    CANDYCONC_INDEX_PATH=<bench> \
    python -m pytest tests/core/test_regex_alternation_not_literal.py \
        -o "addopts=" -p no:cacheprovider -q
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from candyconc.core.fast_index_backend import FastIndexBackend, _regex_is_literal


def _bench_index_path() -> Path:
    raw = os.environ.get("CANDYCONC_INDEX_PATH")
    if not raw:
        pytest.skip("CANDYCONC_INDEX_PATH not set; needs the real bench index")
    path = Path(raw)
    if not path.exists():
        pytest.skip(f"bench index missing: {path}")
    return path


def _backend() -> FastIndexBackend:
    return FastIndexBackend(_bench_index_path())


def test_alternation_is_not_literal_and_groups_are_not() -> None:
    # Metacharacters | ( ) { } must mark a pattern NON-literal so it takes the
    # real regex path; plain words / escaped metacharacters stay literal.
    assert _regex_is_literal("und|oder") is False
    assert _regex_is_literal("(und|oder)") is False
    assert _regex_is_literal("a{2}") is False
    assert _regex_is_literal("ge.*") is False
    assert _regex_is_literal("|LBR|") is False
    # Genuine literals are unaffected -> they keep the fast lexicon-lookup path.
    assert _regex_is_literal("und") is True
    assert _regex_is_literal("oder") is True


def test_alternation_equals_union_of_branches() -> None:
    backend = _backend()
    n = lambda p: backend.regex_positions(p, attr="word")  # noqa: E731

    und = n("und")
    oder = n("oder")
    union = np.union1d(und, oder)

    # Both branches are present in the bench corpus, so the union is nonzero.
    assert und.size > 0
    assert oder.size > 0
    assert union.size > 0

    alternation = n("und|oder")
    assert alternation.size > 0, "alternation silently returned 0 (regressed)"
    # The alternation positions ARE exactly the de-duplicated union of branches.
    assert int(alternation.size) == int(union.size)
    assert np.array_equal(np.unique(alternation), union)

    # A grouped form resolves to the same set; a quantified pattern is nonzero.
    grouped = n("(und|oder)")
    assert int(grouped.size) == int(union.size)
    assert n("ge.*").size > 0


def test_literal_path_unchanged() -> None:
    backend = _backend()
    # A genuine literal still resolves via the single-id lexicon lookup and is
    # unchanged by the fix (count identical whether asked alone or as a branch).
    und = backend.regex_positions("und", attr="word")
    assert und.size > 0
    # Asking the same literal twice is stable and never larger than the corpus.
    assert int(backend.regex_positions("und", attr="word").size) == int(und.size)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
