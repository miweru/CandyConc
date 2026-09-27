from __future__ import annotations

from pathlib import Path
import json
import re
import threading
from typing import Any, List, Optional, Callable

import numpy as np
import logging

from cqlhpc import QueryEngine, SearchOptions, to_builder_json
from cqlhpc.config import use_config as use_cqlhpc_config
from cqlhpc.errors import UNKNOWN_ATTRIBUTE, EmptyMatchError
from cqlhpc.autocomplete import complete as cql_complete
from cqlhpc.diagnostics import diagnose as cql_diagnose
from cqlhpc.fast_corpus import FastCorpus
from cqlhpc.normalize import normalize
from cqlhpc.parser import parse_cql
from .fast_index_backend import FastIndexBackend
from .cql_macros import expand_sim_cql, normalize_sim_syntax
from .index_signature import index_artifact_signature
from .meta_index import descriptive_fields
from candyconc.utils.text_normalize import normalize_text_basic
from candyconc.config import get as get_config


# Cache value: (FastCorpus, QueryEngine, env_sig, artifact_sig). The cache is
# keyed on the index path, but a path alone serves a STALE engine after an
# in-place rebuild (same path, new content) AND ignores env-tuning changes, so
# the stored entry also carries the cqlhpc-env signature and the index-artifact
# mtime signature; a mismatch on either rebuilds the engine.
_ENGINE_CACHE: dict[
    str, tuple[FastCorpus, QueryEngine, tuple[tuple[str, str], ...], int]
] = {}
_ENGINE_CACHE_ORDER: list[str] = []
_ENGINE_CACHE_MAX = max(0, int(get_config("CANDYCONC_CQL_ENGINE_CACHE", "4") or 0))
# Guards every mutation/lookup of the engine cache so concurrent _get_engine /
# clear_engine_cache calls cannot corrupt the dict or the LRU order list. RLock
# because the build path re-enters the same lock to commit the entry.
_ENGINE_CACHE_LOCK = threading.RLock()
_CQLHPC_ENV_CACHE: dict[str, tuple[tuple[float | None, int | None], dict[str, str]]] = {}
LOGGER = logging.getLogger(__name__)


def clear_engine_cache(index_path: str | Path | None = None) -> None:
    """Clear cached QueryEngine instances globally or for one index path.

    ``CorpusIndex.close`` invalidates its own entry before closing the backend;
    otherwise a later reopen of the same path can reuse an engine backed by
    closed mmap resources and silently return no matches. A global clear remains
    available for env changes and server runtime resets. Safe to call
    concurrently with :func:`_get_engine`.
    """
    with _ENGINE_CACHE_LOCK:
        if index_path is None:
            _ENGINE_CACHE.clear()
            _ENGINE_CACHE_ORDER.clear()
            _CQLHPC_ENV_CACHE.clear()
            return
        key = str(index_path)
        _ENGINE_CACHE.pop(key, None)
        _CQLHPC_ENV_CACHE.pop(key, None)
        try:
            _ENGINE_CACHE_ORDER.remove(key)
        except ValueError:
            pass


def _planner_logger() -> Callable[[str], None]:
    def _cb(msg: str) -> None:
        LOGGER.info("CQLHPC %s", msg)
    return _cb


def _is_empty_match_error(exc: Exception) -> bool:
    """Wahr fuer den anerkannten Null-Treffer-Fehler der Abfrage-Maschine.

    Entschieden wird am Typ, nicht am Meldungstext (siehe ``cqlhpc.errors``).
    """
    return isinstance(exc, EmptyMatchError)


def _load_cqlhpc_env(index_path: Path) -> dict[str, str]:
    key = str(index_path)
    config_path = index_path / "config.json"
    if config_path.exists():
        stat = config_path.stat()
        cfg_mtime = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))
        cfg_size = int(stat.st_size)
    else:
        cfg_mtime = None
        cfg_size = None
    cfg_sig = (cfg_mtime, cfg_size)
    cached = _CQLHPC_ENV_CACHE.get(key)
    if cached and cached[0] == cfg_sig:
        return cached[1]
    env: dict[str, str] = {}
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            cfg_env = raw.get("cqlhpc_env")
            if isinstance(cfg_env, dict):
                env.update({str(k): str(v) for k, v in cfg_env.items()})
        except Exception:
            pass
    env = {k: v for k, v in env.items() if str(k).startswith("CANDYCONC_CQLHPC_")}
    _CQLHPC_ENV_CACHE[key] = (cfg_sig, env)
    return env


def _env_signature(env: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in env.items()))


def _get_engine(backend: FastIndexBackend) -> tuple[FastCorpus, QueryEngine]:
    """Reuse QueryEngine/FastCorpus per index path to avoid rebuild overhead.

    The cached entry is keyed on the index path but validated against BOTH the
    cqlhpc-env signature and the index-artifact signature, so an env-tuning
    change or an in-place rebuild (same path, new content) rebuilds the engine
    instead of serving a stale one.
    """
    key = str(getattr(backend, "index_path", ""))
    env = _load_cqlhpc_env(Path(key)) if key else {}
    env_sig = _env_signature(env)
    artifact_sig = index_artifact_signature(key) if key else 0
    if not key or _ENGINE_CACHE_MAX == 0:
        with use_cqlhpc_config(env):
            corpus = FastCorpus.from_backend(backend)
            return corpus, QueryEngine(corpus)
    with _ENGINE_CACHE_LOCK:
        cached = _ENGINE_CACHE.get(key)
        if cached is not None and cached[2] == env_sig and cached[3] == artifact_sig:
            try:
                _ENGINE_CACHE_ORDER.remove(key)
            except ValueError:
                pass
            _ENGINE_CACHE_ORDER.append(key)
            return cached[0], cached[1]
    # Build OUTSIDE the lock so a slow corpus construction does not block other
    # index paths; a concurrent build of the same key is acceptable (last writer
    # wins, both engines are equivalent for the same env+artifact signature).
    with use_cqlhpc_config(env):
        corpus = FastCorpus.from_backend(backend)
        engine = QueryEngine(corpus)
    with _ENGINE_CACHE_LOCK:
        _ENGINE_CACHE[key] = (corpus, engine, env_sig, artifact_sig)
        try:
            _ENGINE_CACHE_ORDER.remove(key)
        except ValueError:
            pass
        _ENGINE_CACHE_ORDER.append(key)
        while len(_ENGINE_CACHE_ORDER) > _ENGINE_CACHE_MAX:
            evict = _ENGINE_CACHE_ORDER.pop(0)
            _ENGINE_CACHE.pop(evict, None)
    return corpus, engine


def search_cql_rows(
    index_path: str | Path,
    query: str,
    *,
    ctx: int = 5,
    limit: Optional[int] = None,
    within_sentences_by_default: bool = True,
) -> List[dict[str, object]]:
    backend = FastIndexBackend(Path(index_path))
    return search_cql_rows_backend(
        backend,
        query,
        ctx=ctx,
        limit=limit,
        within_sentences_by_default=within_sentences_by_default,
    )


def normalize_cql_aliases(query: str) -> str:
    """Normalize common CQL attribute aliases (e.g. ner -> ent)."""
    if not query:
        return query
    # Replace token-local ner aliases in first or subsequent conditions:
    # [ner=...] / [word="X" & ner~"..."] / [ner in {...}] -> ent.
    return re.sub(
        r'((?:\[|&)\s*)ner(\s*(?:=|!=|~|in\b))',
        r'\1ent\2',
        query,
        flags=re.IGNORECASE,
    )


def search_cql_rows_backend(
    backend: FastIndexBackend,
    query: str,
    *,
    ctx: int = 5,
    limit: Optional[int] = None,
    within_sentences_by_default: bool = True,
    progress_cb: Callable | None = None,
    docset_mask: Optional[np.ndarray] = None,
) -> List[dict[str, object]]:
    query = normalize_text_basic(query or "")
    query = expand_sim_cql(query, backend)
    query = normalize_cql_aliases(query)
    env = _load_cqlhpc_env(Path(backend.index_path))
    if progress_cb is None and get_config("CANDYCONC_CQLHPC_LOG_PLANS", "0") == "1":
        progress_cb = _planner_logger()
    options = SearchOptions(
        max_matches=int(limit) if limit is not None else 20000,
        within_sentences_by_default=within_sentences_by_default,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    with use_cqlhpc_config(env):
        _, engine = _get_engine(backend)
        try:
            matches = engine.search(query, options=options)
        except ValueError as exc:
            if _is_empty_match_error(exc):
                return []
            raise
    if not matches:
        return []
    positions = np.array([m.start for m in matches], dtype=np.uint32)
    if limit is not None:
        positions = positions[: int(limit)]
    include_arcs = get_config("CANDYCONC_ENABLE_KWIC_ARCS", "0") == "1"
    return backend.kwic_rows_for_positions(positions, ctx, include_arcs=include_arcs)


def search_cql_matches(
    index_path: str | Path,
    query: str,
    *,
    limit: Optional[int] = None,
    within_sentences_by_default: bool = True,
):
    backend = FastIndexBackend(Path(index_path))
    return search_cql_matches_backend(
        backend,
        query,
        limit=limit,
        within_sentences_by_default=within_sentences_by_default,
    )


def search_cql_matches_backend(
    backend: FastIndexBackend,
    query: str,
    *,
    limit: Optional[int] = None,
    within_sentences_by_default: bool = True,
    progress_cb: Callable | None = None,
    docset_mask: Optional[np.ndarray] = None,
):
    query = normalize_text_basic(query or "")
    query = expand_sim_cql(query, backend)
    query = normalize_cql_aliases(query)
    env = _load_cqlhpc_env(Path(backend.index_path))
    if progress_cb is None and get_config("CANDYCONC_CQLHPC_LOG_PLANS", "0") == "1":
        progress_cb = _planner_logger()
    options = SearchOptions(
        max_matches=int(limit) if limit is not None else 20000,
        within_sentences_by_default=within_sentences_by_default,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    with use_cqlhpc_config(env):
        _, engine = _get_engine(backend)
        try:
            return engine.search(query, options=options)
        except ValueError as exc:
            if _is_empty_match_error(exc):
                return []
            raise


def search_cql_match_arrays_backend(
    backend: FastIndexBackend,
    query: str,
    *,
    limit: Optional[int] = None,
    within_sentences_by_default: bool = True,
    progress_cb: Callable | None = None,
    docset_mask: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, np.ndarray]:
    query = normalize_text_basic(query or "")
    query = expand_sim_cql(query, backend)
    query = normalize_cql_aliases(query)
    env = _load_cqlhpc_env(Path(backend.index_path))
    if progress_cb is None and get_config("CANDYCONC_CQLHPC_LOG_PLANS", "0") == "1":
        progress_cb = _planner_logger()
    options = SearchOptions(
        max_matches=int(limit) if limit is not None else 20000,
        within_sentences_by_default=within_sentences_by_default,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    with use_cqlhpc_config(env):
        _, engine = _get_engine(backend)
        try:
            return engine.search_arrays(query, options=options)
        except ValueError as exc:
            if _is_empty_match_error(exc):
                empty = np.zeros(0, dtype=np.uint32)
                return empty, empty
            raise


def check_cql_conditions(backend: FastIndexBackend, query: str) -> None:
    """Raise the caller errors of a CQL query without scanning the index.

    Parse errors, unknown attributes and a closed-class value outside the
    tagset (``[pos="NE"]`` on a UPOS index) raise exactly as the first step of
    the execution does, with the same messages. A background count can check
    this before it starts, so the caller gets the 400 in the first answer
    instead of ``running``. Conditions on ``sim`` are expanded
    at execution and are not checked here.
    """
    from cqlhpc.ast import Alt, Quant, Seq, Tok, Where, Within
    from cqlhpc.predicates import _check_closed_class_value

    text = normalize_cql_aliases(normalize_text_basic(query or ""))
    ast = normalize(parse_cql(text))
    env = _load_cqlhpc_env(Path(backend.index_path))
    with use_cqlhpc_config(env):
        corpus, _engine = _get_engine(backend)

    def _walk(node: Any):
        yield node
        if isinstance(node, Seq):
            for part in node.parts:
                yield from _walk(part)
        elif isinstance(node, Alt):
            for option in node.options:
                yield from _walk(option)
        elif isinstance(node, (Quant, Where, Within)):
            yield from _walk(node.node)

    for node in _walk(ast):
        if not isinstance(node, Tok):
            continue
        has_sim = any(str(cond.attr).lower() == "sim" for cond in node.clause.conds)
        for cond in node.clause.conds:
            if has_sim and str(cond.attr).lower() in {"sim", "k"}:
                continue
            if not corpus.has_attr(cond.attr):
                raise ValueError(UNKNOWN_ATTRIBUTE.format(attr=cond.attr))
            _check_closed_class_value(cond, corpus)


def count_cql_matches_backend(
    backend: FastIndexBackend,
    query: str,
    *,
    max_matches: Optional[int] = None,
    within_sentences_by_default: bool = True,
    progress_cb: Callable | None = None,
    docset_mask: Optional[np.ndarray] = None,
) -> int:
    query = normalize_text_basic(query or "")
    query = expand_sim_cql(query, backend)
    query = normalize_cql_aliases(query)
    env = _load_cqlhpc_env(Path(backend.index_path))
    if progress_cb is None and get_config("CANDYCONC_CQLHPC_LOG_PLANS", "0") == "1":
        progress_cb = _planner_logger()
    options = SearchOptions(
        max_matches=int(max_matches) if max_matches is not None else 2_000_000_000,
        within_sentences_by_default=within_sentences_by_default,
        progress_cb=progress_cb,
        docset_mask=docset_mask,
    )
    with use_cqlhpc_config(env):
        corpus, _engine = _get_engine(backend)
        engine = QueryEngine(corpus)
        try:
            return engine.count(query, options=options)
        except ValueError as exc:
            if _is_empty_match_error(exc):
                return 0
            raise


def _where_fields(corpus: Any) -> list[str]:
    """Metadata fields that tell documents apart, for the where() suggestion."""
    backend = getattr(corpus, "backend", None)
    meta_index = getattr(backend, "meta_index", None)
    if meta_index is None or not hasattr(meta_index, "value_counts"):
        return []
    return descriptive_fields(meta_index.value_counts())


def analyse_cql_backend(
    backend: FastIndexBackend,
    query: str,
    *,
    cursor: Optional[int] = None,
    limit: int = 20,
) -> dict[str, Any]:
    query = normalize_text_basic(query or "")
    query = normalize_sim_syntax(query)
    query = normalize_cql_aliases(query)
    raw = query
    prefix = ""
    cql_text = raw
    raw_l = raw.lstrip()
    lead = len(raw) - len(raw_l)
    if raw_l.lower().startswith("cql:"):
        prefix = raw[:lead] + raw_l[:4]
        cql_text = raw_l[4:]
    if cursor is None:
        cursor = len(cql_text)
    corpus = FastCorpus.from_backend(backend)
    env = _load_cqlhpc_env(Path(backend.index_path))
    with use_cqlhpc_config(env):
        engine = QueryEngine(corpus)
    docset_mask = None
    builder = None
    try:
        ast = normalize(parse_cql(cql_text))
        builder = to_builder_json(ast)
        docset_mask = engine._docset_from_where(ast)
    except Exception:
        docset_mask = None
    diags = cql_diagnose(cql_text, corpus)
    errors = [d.message for d in diags if d.severity == "error"]
    spans = [(d.start + len(prefix), d.end + len(prefix)) for d in diags if d.severity == "error"]
    diagnostics = [
        {
            "severity": d.severity,
            "message": d.message,
            "start": d.start + len(prefix),
            "end": d.end + len(prefix),
            "fixes": [
                {
                    "label": fix.label,
                    "start": fix.start + len(prefix),
                    "end": fix.end + len(prefix),
                    "replacement": fix.replacement,
                }
                for fix in d.fixes
            ],
        }
        for d in diags
    ]
    warnings = [d.message for d in diags if d.severity in {"warning", "info"}]

    suggestions: list[str] = []
    hints: list[str] = []
    kinds: list[str] = []

    def add_suggestion(text: str, hint: str, kind: str) -> None:
        if text in suggestions:
            return
        suggestions.append(text)
        hints.append(hint)
        kinds.append(kind)

    for d in diags:
        for fix in d.fixes:
            new_text = cql_text[: fix.start] + fix.replacement + cql_text[fix.end :]
            sug = prefix + new_text
            add_suggestion(sug, fix.label, "fix")

    for s in cql_complete(
        cql_text,
        cursor,
        corpus,
        limit=limit,
        docset_mask=docset_mask,
        where_fields=_where_fields(corpus),
    ):
        new_text = cql_text[: s.start] + s.insert_text + cql_text[s.end :]
        sug = prefix + new_text
        add_suggestion(sug, s.detail or s.label, "complete")

    filtered_suggestions: list[str] = []
    filtered_hints: list[str] = []
    filtered_kinds: list[str] = []
    for sug, hint, kind in zip(suggestions, hints, kinds):
        if re.search(r"within\([^,]+,\s*\)", sug):
            continue
        if re.search(r"\|\s*$", sug) or re.search(r"^\s*\|", sug):
            continue
        filtered_suggestions.append(sug)
        filtered_hints.append(hint)
        filtered_kinds.append(kind)

    return {
        "errors": errors,
        "suggestions": filtered_suggestions,
        "hints": filtered_hints,
        "kinds": filtered_kinds,
        "spans": spans,
        "builder": builder,
        "warnings": warnings,
        "diagnostics": diagnostics,
    }
