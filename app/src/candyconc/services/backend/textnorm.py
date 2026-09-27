"""Stateless text and query-term normalization.

Load core helpers at call time without importing server or routes. The
server re-exports these helpers for existing callers."""

from typing import Any


_SINGLE_TOKEN_METACHARS = frozenset('*?[]"\'{}()|+&!^$.\\')


def _canonicalize_term(term: str) -> str:
    """Normalize query terms with NFKC consistently with the corpus index.

Compatibility characters must produce the same lookup and cache key as
their indexed form. Prefer corpus_index.canonicalize_term and use local
NFKC normalization when that helper is unavailable."""
    raw = term or ""
    try:
        from candyconc.core.corpus_index import canonicalize_term as _core_canon

        return _core_canon(raw)
    except Exception:
        pass
    try:
        # query_parser.canonicalize_term is the existing single source of truth
        # (NFKC via normalize_text_basic + CQL entry-form normalization); use it
        # so server-side cache keys match the query-eval row path byte-for-byte.
        from candyconc.domain.query_parser import canonicalize_term as _qp_canon

        return _qp_canon(raw)
    except Exception:
        import unicodedata

        return unicodedata.normalize("NFKC", raw)


def _normalize_query_key(term: str) -> str:
    from candyconc.core.cql_macros import normalize_query_input

    # NFKC-canonicalize before the query-input normalization so codepoint
    # variants collapse to one cache key (D8 #4).
    return normalize_query_input(_canonicalize_term(term))


def _normalize_meta_value(value: Any) -> Any:
    # Delegates to the canonical core normalizer (single source of truth). Core is
    # recursive + handles tuple/set (superset); identical for the flat string|string[]
    # shapes the API/frontend emit. See tests/core/test_meta_filters_golden ANCHOR-9.
    from candyconc.core.meta_filters import normalize_meta_value

    return normalize_meta_value(value)


def _is_simple_single_token(term: str) -> bool:
    """True for a bare literal token eligible for plain-token fast paths."""
    if not term or term.lower().startswith("cql:"):
        return False
    if any(ch.isspace() for ch in term):
        return False
    return not any(ch in _SINGLE_TOKEN_METACHARS for ch in term)
