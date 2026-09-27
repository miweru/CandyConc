# Tool wrapper definitions for CandyConc
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import contextlib
import json
import re

import httpx
from candyconc.config import APP_CONFIG, get as get_config
from candyconc.i18n import lt
import numpy as np

from candyconc.tooling.registry import llm_tool
from candyconc.candyconc_copilot.finding_substance import (
    annotation_entartet as _annotation_entartet,
    knoten_ohne_treffer as _knoten_ohne_treffer)
from candyconc.candyconc_copilot.tool_input_guards import (
    pruefe_metadatenfelder)
from candyconc.candyconc_copilot.ngram_tool_defs import (
    NGRAM_CONTRAST_TOOL,
    NGRAM_FREQUENCY_TOOL,
)
from candyconc.candyconc_copilot.keyness_count_level import (
    counts_docset as _frequency_counts_docset_folded,
    schreibungen_anhaengen as _schreibungen_anhaengen,
    schreibungs_faltung as _schreibungs_faltung,
    ganzzahl_mindestens_eins as _ganzzahl_mindestens_eins,
    frequenzliste as _keyness_frequenzliste,
    lexikon_fuer as _keyness_lexikon,
    zaehlebene as _keyness_zaehlebene,
)
from candyconc.analysis_defaults import (
    CASE_POLICY_GEFALTET,
    analysetoken_spitze as _analysetoken_spitze,
    apply_word_sketch_min_freq as _apply_word_sketch_min_freq,
    filter_frequency_frame as _filter_frequency_frame,
    is_analyst_token as _is_analyst_token,
    summarize_dispersion_offsets as _summarize_dispersion_offsets,
    WORD_SKETCH_DEFAULT_MIN_FREQ,
    word_sketch_relation_label,
)
from .case_variant_count import hinweis as _mit_c_hinweis
from .query_count_tool_def import QUERY_COUNT_TOOL
from . import count_breakdown as _auf
from .word_denominator import (
    nenner as _wortnenner, nenner_der_frequenzliste as _nenner_der_frequenzliste,
    rate_je_million as _rate_je_million)
from . import hit_spread as _ts
from .schema_parts import (
    _bool, _int, _num, _obj, _row_schema, _rows_response, _str,
)
from candyconc.analysis_defaults import analysierbare_groesse
from candyconc.core.fast_index_native import strings_for_ids
from candyconc.services.tools.keyness import (
    compute_keyness as _compute_keyness,
    compute_keyness_counts as _compute_keyness_counts,
    DEFAULT_MIN_FREQ as _DEFAULT_MIN_FREQ,
    normalize_disjoint_docsets,
)
from .word_clusters import (
    WORD_CLUSTER_STOPWORDS as _WORD_CLUSTER_STOPWORDS,  # noqa: F401
    format_word_clusters as _format_word_clusters,  # noqa: F401
    local_word_clusters as _local_word_clusters,
    word_cluster_label as _word_cluster_label,  # noqa: F401
    word_cluster_tokens as _word_cluster_tokens,
)

from candyconc.core.corpus_index import CorpusIndex
from candyconc.core.doc_search import document_search as _document_search
from candyconc.core import query_runtime
from candyconc.core.pairing import is_anchor as _is_anchor, is_version as _is_version

from .analysis import (
    collocate_stats as _collocate_stats,
    compare_collocates as _compare_collocates,
    word_sketch as _word_sketch,
    frequency_list as _frequency_list,
    run_cqlf_query_full as _run_cqlf_query_full, trefferfolge_aus_dem_index, rechts_hinter_dem_treffer,
    abfrage_methode as _query_method_provenance, stichprobe_statt_indexkopf, vorgabe_seed,
    semantic_search as _semantic_search,
)

_HTTP_TIMEOUT = float(get_config("HTTP_TIMEOUT", "10"))


from candyconc.candyconc_copilot.tool_errors import (  # noqa: F401
    ToolInputError,
    UnknownResourceError,
)


def _reraise_query_user_error(exc: BaseException) -> None:
    """Re-raise a query-path error as ``ToolInputError`` when it is the caller's fault.

    FIX-B (COPILOT-CQL-PARSE-500): a malformed CQL/plain query on the copilot
    ``run_cqlf_query`` / ``query_count`` tools used to bubble a raw
    ``ParseError``/``RuntimeError`` to the MCP boundary, which mapped it to a
    misleading HTTP 500 — while the REST ``/query`` sibling already returns 400.
    We classify with the SAME shared seam the REST path uses
    (``server._is_query_user_error`` / ``_is_server_state_error``): a parse/regex
    user error becomes a ``ToolInputError`` (MCP -> 400), genuine engine/index
    faults are left to propagate (MCP -> 500), matching REST exactly. Lazy import
    keeps this module free of an eager backend dependency.
    """
    from candyconc.services.backend.server import (
        _is_query_user_error,
        _is_server_state_error,
    )

    msg = str(exc)
    if _is_server_state_error(msg):
        # Unserveable server state (index not ready) is not a bad request — let it
        # propagate so the MCP boundary surfaces it honestly, same as REST 503.
        return
    if _is_query_user_error(msg):
        raise ToolInputError(msg) from exc


# --------------------------------------------------------------------------- #
def _analysis_scope_response() -> Dict[str, Any]:
    return _obj(
        {
            "corpus_id": _str(),
            "level": _str(),
            "docset_id": _str(),
            "doc_count": _int(),
        },
        required=["corpus_id", "level"],
    )


def _get_index() -> CorpusIndex:
    """Return the active corpus index.

    The process global is set by the server's ``get_index()``. After an import
    into the folder of the active corpus it still holds the old build, after
    an activation it is empty, until some route calls ``get_index()`` again.
    In both cases the server is asked here, which reopens the new build.
    """
    current = query_runtime._CORPUS_INDEX
    stale = current is None
    if current is not None:
        check = getattr(current, "rebuilt_on_disk", None)
        try:
            stale = bool(callable(check) and check())
        except Exception:
            stale = False
    if stale:
        try:
            from candyconc.services.backend import server as _server

            return _server.get_index()
        except Exception:
            # No corpus configured (or no backend): the error below.
            current = query_runtime._CORPUS_INDEX
    if current is None:
        raise RuntimeError("No corpus available. Index a corpus first.")
    return current

def _get_doc_index() -> CorpusIndex:
    """Return the active corpus index for document search."""
    return _get_index()


def _backend_server() -> Any:
    """The backend module, for count_breakdown and hit_spread (import contract)."""
    from candyconc.services.backend import server as _server

    return _server


def _normalise_corpus_reference(corpus: str | None) -> str | None:
    """Map the public ``active`` alias to the implicit active corpus."""

    if str(corpus or "").strip().casefold() == "active":
        return None
    return corpus


def _docset_corpus_name(corpus: str | None) -> str:
    """The catalogue name of ``corpus``, under which its docsets are stored.

    The interface and the REST routes address the active corpus by its
    catalogue name and reject a docset stored under another one. That name is
    ``default`` when the server runs on CANDYCONC_INDEX_PATH or ``index_dir``,
    otherwise the name of the active catalogue entry (its folder name). A
    concrete name is kept as given.
    """
    requested = str(_normalise_corpus_reference(corpus) or "").strip()
    if requested and requested.casefold() != "default":
        return requested
    from candyconc.services.backend import server as _server

    try:
        if _server._configured_default_index_path() is not None:
            return "default"
    except RuntimeError:
        return "default"
    from candyconc.domain.corpus import CorpusRegistry

    active = str(CorpusRegistry.load().active or "").strip()
    return Path(active).expanduser().resolve(strict=False).name if active else "default"


def _resolve_corpus_index(corpus: str | None) -> CorpusIndex:
    """Resolve the CorpusIndex for a per-call ``corpus`` argument.

    FT-COPILOT-CORPUS-RESOLVE: the analysis tools used to read the global
    ``query_runtime._CORPUS_INDEX`` directly via ``_get_index()`` /
    ``_get_doc_index()``. Under concurrency that global is shared across requests
    so a tool could silently analyse the WRONG corpus while another request was
    swapping the active index. This helper resolves the corpus PER CALL from the
    requested name instead of the process-global:

    - ``None`` / ``"default"`` -> the active corpus (server-wide "default" alias,
      see ``services.backend.server.get_corpus``); resolved through the server so
      it never disagrees with the REST path.
    - a concrete corpus name -> ``server.get_corpus(name)`` (a per-corpus index
      from the bounded ``_LANG_INDICES`` cache, NOT the mutable global).

    When the server module is unavailable (bare test fakes / no backend) it falls
    back to the legacy global so unit tests that only set
    ``query_runtime._CORPUS_INDEX`` keep working.

    GROUNDING SAFETY (C-copilot-tools-wiring-1): a concrete-but-unknown corpus
    name (typo / not loaded) makes ``get_corpus`` raise an HTTP 404 ("Korpus
    nicht gefunden") / 400 (bad name). Previously this was swallowed and the tool
    silently analysed the ACTIVE corpus instead — grounding the answer on the
    WRONG corpus. We now only fall back to the default index when the server
    signals "no index loaded at all" (the 503 / "no index" RuntimeError class);
    a genuine 404/400 propagates as a RuntimeError so the tool errors explicitly,
    matching the explicit guard already in ``_resolve_docset_doc_ids``.
    """
    corpus = _normalise_corpus_reference(corpus)
    try:
        from candyconc.services.backend import server as _server
    except Exception:  # pragma: no cover - backend module unavailable
        return _get_index()
    try:
        return _server.get_corpus(corpus)
    except Exception as exc:
        # The "default"/active corpus path raises only when NO index is loaded at
        # all (get_index() RuntimeError -> 503): fall back to the global so the
        # legacy "no corpus" RuntimeError surfaces unchanged.
        if not corpus or str(corpus).strip().lower() == "default":
            return _get_index()
        status = getattr(exc, "status_code", None)
        if status == 503:
            # No index loaded at all (server-state, not a bad request) -> default.
            return _get_index()
        if status is not None:
            # A genuine 4xx (404 "Korpus nicht gefunden" / 400 bad name): the
            # named corpus is unknown. Do NOT silently fall back to the active
            # corpus — that would ground the analysis on the wrong corpus.
            detail = getattr(exc, "detail", None) or str(exc)
            raise UnknownResourceError(str(detail)) from exc
        # A non-HTTP error without a status_code. If it is the "no index" class
        # (RuntimeError from get_index()), fall back; otherwise re-raise so the
        # named-corpus failure is never masked by the active corpus.
        message = str(exc)
        if "no corpus" in message.lower() or "no index" in message.lower():
            return _get_index()
        raise


def _get_doc_count(idx: Any) -> int:
    """Best-effort document count for an index (for docset_mask sizing)."""
    try:
        from candyconc.services.backend import server as _server

        return int(_server._doc_count_for_index(idx))
    except Exception:
        meta = getattr(getattr(idx, "fast_index", None), "doc_metadata", None)
        return int(len(meta)) if meta is not None else 0


def _get_backend_url() -> str:
    return get_config("CANDYCONC_BACKEND_URL", APP_CONFIG.CANDYCONC_BACKEND_URL) or APP_CONFIG.CANDYCONC_BACKEND_URL


def _metadata_axis_values(idx: Any, field: str) -> List[str]:
    try:
        values = idx.metadata_values(field)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _local_semantic_cluster_words(
    tokens: List[str],
    *,
    min_size: int,
    top_n: int,
    reason: str,
    input_token_count: int | None = None,
) -> Dict[str, Any]:
    from candyconc.core.word_vectors import vector_pipeline

    # The word vectors of the active corpus, like /semantic/cluster_words. A
    # corpus without them raises WordVectorsUnavailable with the reason.
    return _local_word_clusters(
        tokens, min_size=min_size, top_n=top_n, reason=reason,
        pipeline=vector_pipeline(_resolve_corpus_index(None).fast_index.index_path),
        input_token_count=input_token_count,
    )


def _sanitise_semantic_search_row(row: Any) -> Any:
    """Bring engine rows in die Form des Response-Schemas (Live-Defekt r1).

    Der Engine-Pfad (``analysis.semantic_search``) liefert ``doc_id`` als
    int (Fallback auf den FAISS-Hit-Index) und ``meta`` als ``None``. Das
    Response-Schema pinnt ``doc_id`` als String und ``meta`` als Objekt, die
    In-Process-MCP-Validierung machte daraus einen 500er ("Invalid result:
    1431 is not of type 'string'") und die Recovery frass das Turn-Budget.
    Deterministische Normalisierung statt Schema-Aufweichung: doc_id wird
    String, ``None``-Felder entfallen.
    """
    if not isinstance(row, dict):
        return row
    cleaned = dict(row)
    doc_id = cleaned.get("doc_id")
    if doc_id is None:
        cleaned.pop("doc_id", None)
    else:
        cleaned["doc_id"] = str(doc_id)
    meta = cleaned.get("meta")
    if not isinstance(meta, dict):
        cleaned.pop("meta", None)
    return cleaned


def _coerce_semantic_search_result(result: Any) -> tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
    if isinstance(result, tuple) and len(result) == 2:
        rows_raw, meta_raw = result
        rows = list(rows_raw or [])
        meta = dict(meta_raw) if isinstance(meta_raw, dict) else None
        return rows, meta
    if isinstance(result, dict) and "rows" in result:
        rows = list(result.get("rows") or [])
        meta_raw = result.get("meta")
        meta = dict(meta_raw) if isinstance(meta_raw, dict) else None
        return rows, meta
    return list(result or []), None


def _active_corpus_names(idx: Any) -> set:
    """Best-effort identity of the ACTIVE index for the corpus-mismatch guard.

    A5: ``idx._config['corpus']`` is never written by any index builder, so a
    guard based on it alone never fires.  Additionally derive the corpus name
    from the index directory (``CorpusIndex.path`` /
    ``FastIndexBackend.index_path``).  An empty set means the identity is
    unknown — the guard then stays permissive (legacy behaviour for bare
    test fakes).
    """
    names: set = set()
    cfg = getattr(idx, "_config", None)
    if isinstance(cfg, dict) and cfg.get("corpus"):
        names.add(str(cfg["corpus"]))
    for candidate in (
        getattr(idx, "path", None),
        getattr(getattr(idx, "fast_index", None), "index_path", None),
    ):
        if not candidate:
            continue
        try:
            name = Path(str(candidate)).name
        except Exception:  # pragma: no cover - exotic fake path objects
            continue
        if name:
            names.add(name)
    return names


def _analysis_scope_provenance(
    idx: Any,
    *,
    corpus: str | None,
    docset_id: str | None,
    doc_ids: Any,
) -> Dict[str, Any]:
    """Describe the effective corpus scope without exposing an absolute path."""

    corpus = _normalise_corpus_reference(corpus)
    requested = str(corpus or "").strip()
    if requested and requested.lower() != "default":
        corpus_id = requested
    else:
        active_names = sorted(_active_corpus_names(idx))
        corpus_id = active_names[0] if active_names else "default"

    scope: Dict[str, Any] = {
        "corpus_id": corpus_id,
        "level": "docset" if doc_ids is not None else "corpus",
    }
    if docset_id:
        scope["docset_id"] = str(docset_id)
    if doc_ids is not None:
        scope["doc_count"] = int(len(doc_ids))
    return scope


def _resolve_docset_doc_ids(
    corpus: str | None,
    docset_id: str | None,
) -> tuple[CorpusIndex, Optional[np.ndarray]]:
    corpus = _normalise_corpus_reference(corpus)
    idx = _get_index()
    # "default" is the server-wide alias for the ACTIVE corpus (see
    # services.backend.server.get_corpus) — it always matches, never a mismatch.
    if corpus and str(corpus).strip().lower() != "default":
        active = _active_corpus_names(idx)
        if active and str(corpus) not in active:
            shown = sorted(active)[0]
            raise UnknownResourceError(
                f"Docset-Korpus '{corpus}' ist nicht geladen (aktiv: {shown})."
            )
    if not docset_id:
        return idx, None
    from candyconc.services.backend.server import _get_docset
    try:
        docset = _get_docset(str(docset_id))
    except Exception as exc:
        # _get_docset raises HTTPException(404, "Docset nicht gefunden") for an
        # unknown id. That is a bad request (the LLM named a missing docset), not
        # an internal fault — surface it as the unknown-resource class so the MCP
        # boundary maps it to 404 rather than the blanket 500.
        if getattr(exc, "status_code", None) == 404:
            detail = getattr(exc, "detail", None) or str(exc)
            raise UnknownResourceError(str(detail)) from exc
        raise
    docset_corpus = docset.get("corpus")
    # default and the catalogue name of the active corpus name the same corpus.
    if corpus and docset_corpus and _docset_corpus_name(docset_corpus) != _docset_corpus_name(corpus):
        raise UnknownResourceError(f"Docset '{docset_id}' gehört zu Korpus '{docset_corpus}', nicht '{corpus}'.")
    ids = docset.get("doc_ids")
    if ids is None:
        return idx, None
    return idx, np.asarray(ids, dtype=np.uint32)


def _coerce_docset_id(reference: str | None, corpus: str | None) -> str | None:
    """Accept EITHER a live docset_id (ephemeral cache hit) OR a persisted
    subcorpus NAME, returning a live docset_id usable by the analysis tools.

    The contrast/keyness tools take ``docset_id`` arguments, but the copilot
    naturally refers to subcorpora by their human-readable saved name. This
    resolver tries the ephemeral docset cache first (the value is already a live
    id); on a miss it treats the value as a saved subcorpus name and re-hydrates
    it into a fresh docset via the canonical project-store path. Returns ``None``
    for an empty reference so callers can keep passing it straight through.
    """
    corpus = _normalise_corpus_reference(corpus)
    ref = str(reference or "").strip()
    if not ref:
        return None
    from candyconc.services.backend import server as _server

    try:
        _server._get_docset(ref)
        return ref  # already a live docset_id
    except Exception:
        pass
    definition = _server._get_project().get_subcorpus(ref)
    if definition is None:
        raise UnknownResourceError(
            f"'{ref}' ist weder ein aktives Docset noch ein gespeicherter Subkorpus-Name. "
            "Mit list_docsets die verfügbaren Subkorpora auflisten."
        )
    stored_corpus = str(definition.get("corpus") or "default")
    if corpus and str(corpus) != stored_corpus and str(corpus).strip().lower() != "default":
        raise UnknownResourceError(
            f"Subkorpus '{ref}' gehört zu Korpus '{stored_corpus}', nicht '{corpus}'."
        )
    idx = _server.get_corpus(stored_corpus)
    doc_count = _server._doc_count_for_index(idx)
    doc_ids = _server._run_heavy_scan_sync(
        _server._resolve_subcorpus_doc_ids, idx, definition
    )
    return _server._store_docset(stored_corpus, doc_ids, doc_count)



RUN_CQLF_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_cqlf_query",
        "description": (
            "Execute a single plain token or a CQLF query and return KWIC rows WITH the "
            "exact total hit count. rows is capped at 'limit' (default 50, max "
            "1000); 'total' is the full hit count and 'truncated' is true when "
            "the corpus has more hits than the returned rows — so a rows length "
            "is NEVER a hit count. Exact multi-token phrases must use one CQLF "
            "word cell per token, for example [word=\"in\"] [word=\"Deutschland\"]. "
            "CQLF attribute values require double quotes; single quotes are invalid. "
            "Adjacent cells ALWAYS mean consecutive tokens; they do not combine "
            "attributes on one token. Combine constraints for the SAME token inside "
            "one cell with &: [lemma=\"gehen\" & pos=\"VERB\"]. Start a claim test "
            "with a broad literal/lemma baseline before justified narrower sequence "
            "patterns, and never repeat an identical successful call. "
            "Optional sort (AntConc 1L/2L/3L/node/1R/2R/3R/"
            "meta:FIELD), case folding, corpus and docset scoping."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Single plain token or CQLF query. For an exact phrase, "
                        "use [word=\"token1\"] [word=\"token2\"]. Adjacent "
                        "Attribute values require double quotes; single quotes "
                        "are invalid. "
                        "cells are consecutive tokens. Same-token attributes "
                        "belong in one cell joined by &, e.g. "
                        "[lemma=\"gehen\" & pos=\"VERB\"]."
                    ),
                },
                "ctx": {
                    "type": "integer",
                    "description": "context tokens",
                    "default": 5,
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID ODER Subkorpus-Name (optional).",
                },
                "sort_by": {
                    "type": "string",
                    "description": (
                        "KWIC-Sortierfeld: 1L|2L|3L (links), node (Treffer), 1R|2R|3R "
                        "(rechts), meta:FELD, position = Indexreihenfolge. Leer: siehe sample."
                    ),
                },
                "sort_dir": {
                    "type": "string",
                    "description": "Sortierrichtung asc|desc (Default asc).",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Gross-/Kleinschreibung ignorieren (Default true), nur fuer die einfache Wortsuche. In CQL faltet allein %c: [word=\"und\" %c] faltet, [word=\"und\"] nicht.",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max. zurückgegebene KWIC-Zeilen (Default 50, max 1000).",
                    "default": 50,
                },
                "sample": {
                    "type": "integer",
                    "description": (
                        "Zufallsstichprobe: uniform min(sample, Treffermenge) aus der GESAMTEN "
                        "Treffermenge (max 10000), seed ist dann Pflicht. Ohne sample, seed und "
                        "sort_by zieht das Werkzeug selbst limit Zeilen uniform, mit festem Seed "
                        "je Abfrage, gemeldet im sample-Block. Bis limit Treffer kommen alle."
                    ),
                },
                "seed": {
                    "type": "integer",
                    "description": (
                        "Deterministischer RNG-Seed für sample (>= 0), identischer "
                        "Seed reproduziert exakt dieselbe Stichprobe. Ohne sample "
                        "wie bei REST: keine Stichprobe, Indexreihenfolge."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ctx": {"type": "integer"},
            "corpus": {"type": "string"},
            "docset_id": {"type": "string"},
            "sort_by": {"type": "string"},
            "sort_dir": {"type": "string"},
            "case_insensitive": {"type": "boolean"},
            "limit": {"type": "integer"},
            "sample": {"type": "integer"},
            "seed": {"type": "integer"},
        },
        "required": ["query"],
    },
}


RUN_CQLF_RESPONSE = _rows_response(
    {
        "file": _str(),
        "kw": _str(),
        # ``kw`` remains the pivot token for backwards compatibility.  Span
        # queries additionally expose the complete matched token sequence so
        # an analyst (and the copilot) never has to infer it from the right
        # context plus relative offsets.
        "match": _str(),
        "match_tokens": {"type": "array", "items": {"type": "string"}},
        "left": _str(),
        "right": _str(),
        "pos": _int(),
        # CQL multi-token matches carry the relative offsets of the non-pivot
        # tokens (e.g. [-1] / [1,2]); present only for span matches.
        "match_offsets": {"type": "array", "items": {"type": "integer"}},
        # Rows of an index with the original spacing (whitespace_after.bin):
        # is there a space between left and kw, between kw and right. The
        # harness joins evidence lines with them (core/source_spacing).
        "ws_before_kw": _bool(),
        "ws_after_kw": _bool(),
    },
    extra_top={
        "query": _str(),
        "query_mode": _str(),
        "attribute": _str(),
        "case_insensitive": _bool(),
        "faltung_teilweise": _str(),  # nur bei %c an einem Teil der Werte (abfrage_methode)
        "ctx": _int(),
        "scope": _analysis_scope_response(),
        "total": _int(),
        "docs_with_hits": _int(), "source_texts_with_hits": _int(),
        "truncated": _bool(),
        "limit": _int(),
        # Sampling provenance (mirrors the REST GET /query X-CandyConc-Sample
        # header): present ONLY when sample was requested. population_partial
        # is True when the underlying position scan was bounded — the sample is
        # then uniform over that bounded subset, not the true full match set.
        "sample": _obj(
            {
                "requested": _int(),
                # Die Zahl der WIRKLICH gelieferten Zeilen. Vorher stand hier
                # die Zahl der gezogenen, waehrend die Antwort weniger
                # ausgab: sample=500 meldete drawn 500 und lieferte 50.
                "drawn": _int(),
                "seed": _int(),
                "population": _int(),
                "population_partial": _bool(),
                # Nur ohne sort_by bei echter Ziehung: die Zeilen stehen in Ziehungsfolge.
                "order": _str(),
            },
            required=["requested", "drawn", "seed", "population", "population_partial"],
        ),
    },
    required=["status", "rows", "total", "truncated"],
)


def _without_token_starts(result: Dict[str, Any]) -> Dict[str, Any]:
    """The rows without their token offsets, once sorting and match span used them.

    The offsets address tokens in a text with the original spacing. The model
    reads left, kw and right, and the response schema has no field for them.
    """
    rows = result.get("rows")
    if isinstance(rows, list):
        result["rows"] = [
            {k: v for k, v in row.items() if k != "token_starts"} if isinstance(row, dict) else row
            for row in rows
        ]
    return result


def _with_explicit_match_span(row: Dict[str, Any], idx: Any = None, ctx: Any = None) -> Dict[str, Any]:
    """Add an auditable full match for CQL spans while preserving ``kw``."""

    offsets = row.get("match_offsets")
    if not isinstance(offsets, list) or not offsets:
        return row
    # Read index positions because splitting displayed text discards line-break tokens.
    folge = trefferfolge_aus_dem_index(row, idx)
    if folge is not None:
        return rechts_hinter_dem_treffer({**row, **folge}, idx, ctx)
    try:
        relative_offsets = sorted({0, *(int(value) for value in offsets)})
    except (TypeError, ValueError):
        return row
    from candyconc.core.source_spacing import side_tokens

    # Tokens, not whitespace chunks: with the original spacing "soul." is two.
    left_tokens = side_tokens(row, "left")
    pivot_tokens = side_tokens(row, "kw")
    right_tokens = side_tokens(row, "right")
    if len(pivot_tokens) != 1:
        return row
    matched: list[str] = []
    for offset in relative_offsets:
        if offset == 0:
            matched.append(pivot_tokens[0])
        elif offset < 0 and len(left_tokens) >= abs(offset):
            matched.append(left_tokens[offset])
        elif offset > 0 and len(right_tokens) >= offset:
            matched.append(right_tokens[offset - 1])
        else:
            return row
    return rechts_hinter_dem_treffer({**row, "match": " ".join(matched), "match_tokens": matched}, idx, ctx)


def _sampled_run_cqlf_result(
    idx: Any,
    query: str,
    *,
    ctx: int,
    docset_mask: Any,
    sort_by: str | None,
    sort_dir: str,
    case_insensitive: bool,
    limit: int | None,
    sample_size: int,
    seed_value: int,
) -> Dict[str, Any]:
    """Seeded uniform KWIC sample — the copilot mirror of REST GET /query sample.

    Uses the SAME REST seam (``routes.query._sampled_query_rows``: exhaustive
    position scan -> seeded draw -> render only the sampled hits), so the drawn
    row set is identical to what GET /query?sample=..&seed=.. serves. The REST
    provenance header X-CandyConc-Sample {requested, drawn, seed, population,
    population_partial} is returned as the in-body ``sample`` block. Rows are
    projected onto the documented copilot row shape (file/kw/left/right/pos
    [+match_offsets]) and display-normalised like the non-sample path. ``total``
    stays the exact population (full match-set size), NOT the sample size.
    Dieselben Zeilen wie REST, ohne sort_by aber in Ziehungsfolge (sample_order).
    """
    from fastapi import HTTPException

    from candyconc.services.backend import server as _server
    from candyconc.services.backend.kwic_renderer import (
        normalise_kwic_row_display,
        parse_sort,
        sort_kwic_rows,
    )
    from candyconc.services.backend.routes.query import _sampled_query_rows

    from .analysis import _bounded_run_cqlf_limit

    try:
        sort_spec = parse_sort(sort_by)
    except ValueError as exc:
        raise ToolInputError(str(exc)) from exc

    try:
        raw_rows, sample_meta = _sampled_query_rows(
            _server,
            idx,
            query,
            ctx=int(ctx),
            docset_mask=docset_mask,
            case_insensitive=case_insensitive,
            sample_size=int(sample_size),
            seed=int(seed_value),
        )
    except HTTPException as exc:
        # 400/422 from the REST seam (e.g. "Zufallsstichprobe ... erfordert den
        # Fast-Index-Pfad") is the caller's fault -> honest status=error with the
        # SERVER message (ToolInputError -> MCP 400 -> orchestrator error envelope).
        if int(getattr(exc, "status_code", 0) or 0) in (400, 422):
            raise ToolInputError(str(getattr(exc, "detail", exc))) from exc
        raise
    except (RuntimeError, ValueError) as exc:
        _reraise_query_user_error(exc)
        raise

    rows: list[Dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        projected: Dict[str, Any] = {
            "file": str(row.get("doc") or row.get("file") or ""),
            "kw": row.get("kw"),
            "left": row.get("left"),
            "right": row.get("right"),
            "pos": row.get("pos"),
        }
        if row.get("match_offsets") is not None:
            projected["match_offsets"] = row.get("match_offsets")
        # The spacing fields of a row with the original spacing, as on the
        # full path: sorting and the match span address tokens through them.
        for feld in ("ws_before_kw", "ws_after_kw", "token_starts"):
            if feld in row:
                projected[feld] = row[feld]
        rows.append(
            _with_explicit_match_span(
                normalise_kwic_row_display(projected), idx, ctx
            )
        )

    if sort_spec is not None:
        rows = sort_kwic_rows(rows, sort_by, sort_dir=sort_dir)

    row_limit = _bounded_run_cqlf_limit(limit)
    # Höchstens limit Zeilen als Teilziehung, kein Präfix (Gate 11). Ohne sort_by, auch
    # ohne sort_by="position", in der Folge der Ziehung, die REST-Naht bleibt sortiert.
    from candyconc.candyconc_copilot.sample_order import in_ziehungsfolge

    rows, folge = in_ziehungsfolge(rows, sample_meta, limit=row_limit, sortiert=bool(str(sort_by or "").strip()))
    population = int(sample_meta.get("population", 0))
    sample_block: Dict[str, Any] = {
        "requested": int(sample_meta["requested"]),
        # Die WIRKLICH gelieferte Zahl, nicht die urspruenglich gezogene.
        "drawn": len(rows),
        "seed": int(sample_meta["seed"]),
        "population": population,
        "population_partial": bool(sample_meta.get("population_partial", False)),
        **folge,
    }
    # KEIN eigenes Feld fuer die Zahl VOR dem Schnitt. Der Systemprompt
    # steht bei 30.999 von 31.000 Zeichen, und der Doku-Waechter verlangt
    # jedes ausgelieferte Feld dort. Der Sachverhalt steht schon in der
    # Antwort: requested 500, drawn 50, population 55550 heisst
    # unmissverstaendlich "der Zeilendeckel hat gedeckelt". Was gefaehrlich
    # war, ist der PRAEFIX, und der ist weg.
    return {
        "status": "success",
        "rows": rows,
        "total": population,
        "truncated": population > len(rows),
        "limit": int(row_limit),
        "sample": sample_block,
    }


@llm_tool(RUN_CQLF_TOOL, RUN_CQLF_RESPONSE)
def run_cqlf_query_tool(
    query: str,
    ctx: int = 5,
    corpus: str | None = None,
    docset_id: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    case_insensitive: bool = True,
    limit: int | None = None,
    sample: int | None = None,
    seed: int | None = None,
) -> Dict[str, Any]:
    """KWIC rows + exact total for ``query`` (FT-COPILOT-PARITY).

    Returns ``{status, rows, total, truncated, limit}``. ``total`` is the exact
    hit count (NOT len(rows)); ``truncated`` is true when more hits exist than
    the returned page. Optional sort, case folding, and corpus/docset scoping
    bring the copilot KWIC path up to REST /query parity.

    ``sample``/``seed`` mirror REST GET /query (T1 thinning): a seeded uniform
    sample over the FULL match set, validated by the SAME server rule
    (``routes.query._validate_sample_params`` — seed is REQUIRED once sample is
    set; the server's 422 message is passed through verbatim as the tool error).
    The sample provenance {requested, drawn, seed, population,
    population_partial} — the REST X-CandyConc-Sample header block — is returned
    as the ``sample`` field.
    """
    if sample is not None or seed is not None:
        from fastapi import HTTPException

        from candyconc.services.backend.routes.query import _validate_sample_params

        try:
            sample_size, seed_value = _validate_sample_params(sample, seed)
        except HTTPException as exc:
            # Pass the server's 422 validation message through verbatim
            # (ToolInputError -> MCP 400 -> {"status": "error", message}).
            raise ToolInputError(str(getattr(exc, "detail", exc))) from exc
    else:
        sample_size, seed_value = None, None

    resolved_docset = _coerce_docset_id(docset_id, corpus) if docset_id else None
    idx, doc_ids = _resolve_docset_doc_ids(corpus, resolved_docset)
    # Reflect where() restrictions in the reported scope and denominator.
    # The engine already applies them during execution, so keep doc_ids unchanged
    # to avoid a second filter or a different execution path. Classify scope-parse
    # errors like the main query path so invalid input receives the same response.
    try:
        _eng = _where_dokumente(idx, query)
    except (RuntimeError, ValueError) as exc:
        _reraise_query_user_error(exc)
        raise
    _scope_ids = doc_ids
    if _eng is not None:
        _scope_ids = (
            np.asarray(_eng, dtype=np.uint32)
            if doc_ids is None
            else np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_eng, dtype=np.uint32),
                assume_unique=False,
            )
        )
    scope = _analysis_scope_provenance(
        idx,
        corpus=corpus,
        docset_id=resolved_docset,
        doc_ids=_scope_ids,
    )
    query_method = _query_method_provenance(
        query,
        case_insensitive=case_insensitive,
    )
    docset_mask = None
    if doc_ids is not None:
        from candyconc.core.fast_index_native import docset_mask_from_ids

        try:
            n_docs = int(idx.fast_index.boundaries.document._positions.size)
        except Exception:
            n_docs = int(_get_doc_count(idx))
        docset_mask = docset_mask_from_ids(np.asarray(doc_ids, dtype=np.uint32), n_docs)
    if sample_size is not None:
        # A validated seed without sample is a no-op (REST contract); the sampled
        # path only runs when sample itself was requested.
        result = _sampled_run_cqlf_result(
            idx,
            query,
            ctx=ctx,
            docset_mask=docset_mask,
            sort_by=sort_by,
            sort_dir=sort_dir,
            case_insensitive=case_insensitive,
            limit=limit,
            sample_size=sample_size,
            seed_value=seed_value,
        )
        result.update(
            {
                "query": str(query),
                "ctx": int(ctx),
                "scope": scope,
                **query_method,
                **_ts.kwic_felder(idx, query, docset_mask, result.get("total"), _scope_ids,
                                  server=_backend_server()),
            }
        )
        return _without_token_starts(result)
    try:
        result = _run_cqlf_query_full(
            query,
            ctx=ctx,
            corpus=idx,
            docset_mask=docset_mask,
            sort_by=sort_by,
            sort_dir=sort_dir,
            case_insensitive=case_insensitive,
            limit=limit,
        )
    except (RuntimeError, ValueError) as exc:
        # FIX-B: malformed CQL/plain query -> 400 (ToolInputError), matching REST
        # /query. Genuine faults fall through to the original exception (-> 500).
        _reraise_query_user_error(exc)
        raise
    # COPILOT-2: normalise the visible KWIC text through the SAME helper the REST
    # /query path uses, so the index-only '|LBR|' linebreak sentinel never leaks
    # into copilot answers (the engine emits it; only the display layer strips it).
    rows = result.get("rows")
    if isinstance(rows, list):
        from candyconc.services.backend.kwic_renderer import normalise_kwic_row_display

        result["rows"] = [
            _with_explicit_match_span(normalise_kwic_row_display(row), idx, ctx)
            for row in rows
        ]
    # Ohne sample und seed eine gemeldete Stichprobe statt des Indexkopfs, auch mit sort_by (dann sortiert).
    result = stichprobe_statt_indexkopf(result, sample=sample, seed=seed, sort_by=sort_by, ziehen=lambda **wahl: _sampled_run_cqlf_result(
        idx, query, ctx=ctx, docset_mask=docset_mask, sort_by=sort_by, sort_dir=sort_dir, case_insensitive=case_insensitive, limit=limit, **wahl),
        seed_vorgabe=vorgabe_seed(str(query), f"{scope.get('corpus_id')}|{resolved_docset or ''}"))
    result.update(
        {
            "query": str(query),
            "ctx": int(ctx),
            "scope": scope,
            **query_method,
            **_ts.kwic_felder(idx, query, docset_mask, result.get("total"), _scope_ids,
                              server=_backend_server()),
        }
    )
    return _without_token_starts(result)




QUERY_COUNT_RESPONSE = _obj(
    {
        "status": _str(),
        "query": _str(),
        "total": _int(),
        # B2 (Q2): vorgerechnete Normalisierung - Modelle rechnen pmw nicht selbst.
        "corpus_tokens": _int(),
        "denominator_tokens": _int(),
        # Expose raw tokens alongside the analysis-token denominator.
        "denominator_tokens_raw": _int(),
        "denominator_scope": _str(),
        "denominator_source": _str(),
        "per_million": _num(),
        "query_mode": _str(),
        "attribute": _str(),
        "case_insensitive": _bool(),
        "faltung_teilweise": _str(),  # nur bei %c an einem Teil der Werte (abfrage_methode)
        # Nur bei einer Faltklasse mit mehr als einer Schreibung: Anteil je Schreibung.
        "schreibung_gefaltet": {"type": "object", "additionalProperties": {"type": "integer"}},
        "scope": _analysis_scope_response(),
        # Nur vorhanden, wenn der gesuchte Wert ueberhaupt in Verbundtypen
        # vorkommt. Keine Pflichtfelder: leere Felder waeren eine Behauptung
        # ueber jeden Wert, fuer den nichts vorliegt.
        "bestandteile_masse": _int(),
        "bestandteile_anteil": _num(),
        "bestandteile_muster": _str(),
        # Declare optional count fields because MCP rejects unknown response properties.
        "mit_c": _obj({"query": _str(), "total": _int()}, required=["query", "total"]), "andere_schreibung": _obj({"query": _str(), "total": _int()}, required=["query", "total"]),
        "nach": _str(),
        "dp_nach": _num(),
        "dp_norm_nach": _num(),
        # Reference values for dp_nach, matching dispersion_offsets.
        "dp_min_nach": _num(),
        "dp_erwartet_nach": _num(),
        **_ts.ANTWORTFELDER,
        "rows": {"type": "array", "items": _obj(
            {"wert": _str(), "total": _int(), "docs": _int(), "tokens": _int(),
             "tokens_raw": _int(), "per_million": {"type": ["number", "null"]},
             # Dokumente je Verfahren, nur an einer Zeile, die als Ausnahme
             # mehrere mischt (count_breakdown.mischverfahren).
             "procedures": {"type": "object", "additionalProperties": {"type": "integer"}},
             **_ts.ZEILENFELDER},
            required=["wert", "total", "docs", "tokens"])},
    },
    required=[
        "status",
        "query",
        "total",
        "corpus_tokens",
        "denominator_tokens",
        "denominator_scope",
        "denominator_source",
        "per_million",
        "query_mode",
        "attribute",
        "case_insensitive",
        "scope",
    ],
)



def _where_dokumente(idx: Any, query: Any) -> Any:
    """Verweis auf core.meta_filters.where_dokumente, siehe dort."""
    from candyconc.core.meta_filters import where_dokumente

    return where_dokumente(idx, query)
# Ein Abfragetext, der GENAU eine Wertbedingung traegt: [attr="wert"] oder
# der blosse Klartext. Nur dafuer ist die Frage "welche Verbundtypen
# tragen diesen Wert" ueberhaupt gestellt. Alles andere, Sequenzen,
# Alternationen, Muster mit Metazeichen, wird bewusst uebergangen.
_EINE_WERTBEDINGUNG = re.compile(
    r'^\s*(?:cql:\s*)?\[\s*(?P<attr>word|lemma|pos|morph)\s*=\s*'
    r'"(?P<wert>[^"\\]*)"\s*\]\s*$'
)
_METAZEICHEN = set(".^$*+?()[]{}|\\")


def _verbundtypen_hinweis(idx: Any, query: str) -> Dict[str, Any]:
    """Report compound annotation values alongside an exact-value query.

    Pipe-separated annotations can encode alternatives such as ``Recht|Rechte``
    or combined labels such as ``ADV|Degree=Pos``. An exact component query does
    not count those types. Report their contribution separately while preserving
    the original query's matching semantics.
    """
    treffer = _EINE_WERTBEDINGUNG.match(str(query or ""))
    if treffer is None:
        return {}
    wert = treffer.group("wert")
    if not wert or any(z in _METAZEICHEN for z in wert):
        # Ein Muster ist keine Wertfrage.
        return {}
    try:
        from candyconc.core.component_types import bericht, bestandteile_fuer

        attribut = treffer.group("attr")
        lexikon = getattr(idx.fast_index.lexicons, attribut, None)
        if lexikon is None:
            return {}
        befund = bericht(bestandteile_fuer(lexikon, wert, attribut=attribut))
    except Exception:  # noqa: BLE001 - siehe unten
        # Die Angabe ist eine Zugabe. Sie darf eine Zaehlung nie stuerzen.
        # Diese Datei fuehrt keinen Modul-Logger, deshalb hier einer auf
        # Abruf statt eines NameError im Ausnahmezweig, der genau das
        # verursachen wuerde, was er verhindern soll.
        import logging

        logging.getLogger(__name__).debug(
            "Verbundtypen-Hinweis fehlgeschlagen", exc_info=True
        )
        return {}
    if not befund:
        return {}
    # Drei flache Felder statt eines verschachtelten Objekts: der statische
    # Kern liegt an seiner harten Grenze von 31.000 Zeichen, und jedes
    # angekuendigte Feld kostet dort Platz. Das Modell braucht die Masse,
    # den Anteil und die fertige Abfrage. Die Typenliste bleibt im Befund
    # fuer Artefakte und die REST-Flaeche, wird aber nicht angekuendigt.
    return {
        "bestandteile_masse": befund["in_verbundtypen"],
        "bestandteile_anteil": befund["fehlanteil"],
        "bestandteile_muster": befund["muster_mit_verbundtypen"],
    }


@llm_tool(QUERY_COUNT_TOOL, QUERY_COUNT_RESPONSE)
def query_count_tool(
    query: str,
    corpus: str | None = None,
    docset_id: str | None = None,
    case_insensitive: bool = True,
    filters: Dict[str, Any] | None = None,
    nach: str | None = None,
) -> Dict[str, Any]:
    """Exact total hit count for ``query`` (no KWIC rows) — FT-COPILOT-PARITY.

    Returns the exact ``total`` plus a precomputed ``per_million`` value.
    ``denominator_tokens`` is the effective normalisation base: the full corpus
    for an unscoped query and ``idx.docset_token_count(doc_ids)`` for a docset.
    ``denominator_scope`` and ``denominator_source`` make that choice auditable;
    the backwards-compatible ``corpus_tokens`` field always remains the full
    corpus size. This is the correct tool for "how often does X occur" —
    run_cqlf_query returns KWIC rows (capped) and frequency_list is a whole-corpus
    ranking.

    COPILOT-COUNT-BRACKETCQL-DIVERGE: the count is computed by the SAME
    ``server._compute_query_count`` primitive the REST ``/query/count`` route
    uses — one shared exact-count seam — so EVERY query form yields the identical
    total. The previous ``run_query`` row-path with ``limit=1`` silently collapsed
    an un-prefixed CWB bracket like ``[pos=NOUN]`` to the row cap (total=1),
    because its exact-count callback only fires for the ``cql:`` branch; the plain
    bracket path that ``/query/count`` resolves (``[pos=NOUN]`` -> 9740) never
    triggered it. Routing through the REST primitive removes that divergence and
    inherits its honest 4xx for genuinely malformed CQL.
    """
    resolved_docset = _coerce_docset_id(docset_id, corpus) if docset_id else None
    idx, doc_ids = _resolve_docset_doc_ids(corpus, resolved_docset)
    if resolved_docset is not None and doc_ids is None:
        raise UnknownResourceError(
            f"Docset '{resolved_docset}' enthält keine auflösbaren Dokument-IDs."
        )
    pruefe_metadatenfelder(idx, filters)
    doc_ids = _auf.ids_mit_filtern(idx, filters, doc_ids, server=_backend_server())
    scope = _analysis_scope_provenance(
        idx,
        corpus=corpus,
        docset_id=resolved_docset,
        doc_ids=doc_ids,
    )
    docset_mask = None
    if doc_ids is not None:
        from candyconc.core.fast_index_native import docset_mask_from_ids

        try:
            n_docs = int(idx.fast_index.boundaries.document._positions.size)
        except Exception:
            n_docs = int(_get_doc_count(idx))
        docset_mask = docset_mask_from_ids(np.asarray(doc_ids, dtype=np.uint32), n_docs)
    from candyconc.services.backend.server import _compute_query_count

    try:
        total, _elapsed_ms, _partial = _compute_query_count(
            idx,
            str(query),
            0,
            None,
            None,
            docset_mask,
            case_insensitive=case_insensitive,
        )
    except (RuntimeError, ValueError) as exc:
        # Malformed CQL/plain query -> 400 (ToolInputError), matching REST /count.
        # Genuine faults fall through to the original exception (-> 500).
        _reraise_query_user_error(exc)
        raise
    # B2 (Q2): deliver the pmw normalisation instead of letting the model
    # compute it (models mis-round; e.g. "173 pmw" instead of 173337.4 for
    # 9740/56191). ``corpus_tokens`` keeps its established whole-corpus meaning;
    # ``denominator_tokens`` is the actual scoped normalisation base. Never fall
    # back to the full corpus for a docset: that would yield a plausible-looking
    # but methodologically wrong rate.
    corpus_tokens = 0
    with contextlib.suppress(Exception):
        corpus_tokens = int(idx.token_count())
    # Auch MIT docset_id: eine where()-Einschraenkung schraenkt weiter
    # ein, und der Docset-Nenner allein waere dann zu gross. Eine
    # Vorfassung uebersprang den Zweig, sobald ein Docset gesetzt war.
    if doc_ids is not None:
        _eng = _where_dokumente(idx, query)
        if _eng is not None:
            doc_ids = np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_eng, dtype=np.uint32),
                assume_unique=False,
            )
            # Der Scope wurde VOR dem Schnitt gebildet und widersprach
            # danach dem Nenner: Docset "train" (1317 Dokumente) mit
            # where(split="test") ergibt eine LEERE Schnittmenge, und die
            # Antwort meldete 0 Treffer bei Nenner 0 und gleichzeitig
            # doc_count 1317.
            scope = _analysis_scope_provenance(
                idx, corpus=corpus, docset_id=resolved_docset, doc_ids=doc_ids)
    if doc_ids is None:
        # A where() restriction narrows the document population without setting
        # docset_id. Apply it to the denominator as well as the query's hits.
        where_ids = _where_dokumente(idx, query)
        bereich_ids = where_ids
        if where_ids is not None:
            # "docset", nicht ein neuer Wert: eine where()-Einschraenkung
            # IST eine Dokumentteilmenge, und die Werkzeugdoku kennt genau
            # zwei Werte (corpus, docset). Eine Vorfassung meldete
            # "query_where", das in keiner Doku stand, und behielt
            # gleichzeitig scope.level="corpus" -- die Antwort widersprach
            # sich in zwei benachbarten Feldern. Woher die Teilmenge
            # kommt, sagt denominator_source.
            bezug = _wortnenner(idx, where_ids)
            denominator_scope = "docset"
            denominator_source = "where()-Einschraenkung der Abfrage"
            if isinstance(scope, dict):
                scope = {**scope, "level": "docset",
                         "doc_count": int(len(where_ids))}
        else:
            bezug = (_wortnenner(idx, None) if corpus_tokens
                     else {"woerter": 0, "roh": 0, "quelle": "corpus_index.token_count"})
            denominator_scope = "corpus"
            denominator_source = bezug["quelle"]
    else:
        bereich_ids = doc_ids
        bezug = _wortnenner(idx, doc_ids)
        denominator_scope = "docset"
        denominator_source = bezug["quelle"]
    # Add hit coverage by document and source text, plus rate intervals.
    streuung, streuung_kontext = _ts.fuer_zaehlung(
        idx, str(query), docset_mask, int(total), bereich_ids,
        mit_zeilen=_where_dokumente(idx, query) is None, server=_backend_server())
    # Use analysis tokens as the denominator, matching keyness.
    # Expose the raw count separately as denominator_tokens_raw.
    denominator_tokens = int(bezug["woerter"])
    # Unter 1 zwei geltende Ziffern: 3 Treffer auf 130,8 Mio. Token sind 0.023, nicht 0.0 (Lesung Q4, A4).
    per_million = _rate_je_million(total, denominator_tokens)
    return {
        "status": "success",
        "query": str(query),
        "total": int(total),
        "corpus_tokens": corpus_tokens,
        "denominator_tokens": denominator_tokens,
        "denominator_tokens_raw": int(bezug["roh"]),
        "denominator_scope": denominator_scope,
        "denominator_source": denominator_source,
        "per_million": per_million,
        **streuung,
        "scope": scope,
        **_schreibungs_faltung(idx, query, case_insensitive=case_insensitive,
                               unscoped=doc_ids is None),
        **_verbundtypen_hinweis(idx, query),
        **_mit_c_hinweis(query, total, lambda q: _compute_query_count(
            idx, q, 0, None, None, docset_mask, case_insensitive=case_insensitive)[0]),
        **_auf.zeilen(idx, query, nach=nach, filters=filters, basis=doc_ids,
                      case_insensitive=case_insensitive, kontext=streuung_kontext,
                      server=_backend_server()),
        **_query_method_provenance(
            query,
            case_insensitive=case_insensitive,
        ),
    }


COLLOCATE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "collocate_stats",
        "description": "Compute collocate statistics for a term, including the chi-square cell contribution.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Keyword"},
                "window": {
                    "type": "integer",
                    "description": "token window",
                    "minimum": 1,
                    "default": 5,
                },
                "within_sentence": {
                    "type": "boolean",
                    "description": "Nur innerhalb von Satzgrenzen zählen",
                    "default": True,
                },
                "sort_by": {
                    "type": "string",
                    "description": (
                        "Sortiermaß (mi, mi3, lmi, npmi, z, chi2_cell, t, ll, dice, "
                        "logdice, f, delta_p_nc, delta_p_cn)."
                    ),
                    "enum": [
                        "chi2_cell",
                        "delta_p_nc",
                        "delta_p_cn",
                        "logdice", "logdice_window", "log_ratio", "lrc",
                        "dice",
                        "npmi",
                        "mi3",
                        "lmi",
                        "mi",
                        "ll",
                        "z",
                        "t",
                        "f",
                    ],
                    "default": "logdice",
                },
                "min_freq": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "0 = automatische Kalibrierung an der Knotenfrequenz "
                        "(5 bei häufigen Knoten, bis 2 bei seltenen); "
                        "explizite Werte >=2 gelten."
                    ),
                    "default": 0,
                },
                "attribute": {
                    "type": "string",
                    "description": (
                        "Zählattribut 'word' (Default, Oberflächenformen) oder "
                        "'lemma' (Term wird als Lemma interpretiert, Kookkurrenz "
                        "über die Lemma-Spalte gezählt; Fehler mit Capability-"
                        "Hinweis, wenn das Korpus kein Lemma-Attribut trägt)."
                    ),
                    "default": "word",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID (optional).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "window": {"type": "integer", "minimum": 1, "default": 5},
            "within_sentence": {"type": "boolean", "default": True},
            "sort_by": {
                "type": "string",
                "enum": [
                    "chi2_cell", "delta_p_nc", "delta_p_cn", "logdice", "logdice_window",
                    "log_ratio", "lrc",
                    "dice", "npmi", "mi3", "lmi", "mi", "ll", "z", "t", "f",
                ],
                "default": "logdice",
            },
            "min_freq": {"type": "integer", "minimum": 0, "default": 0},
            "attribute": {"type": "string", "default": "word"},
            "corpus": {"type": "string"},
            "docset_id": {"type": "string"},
        },
        "required": ["term"],
    },
}


COLLOCATE_RESPONSE = _rows_response(
    {
        "word": _str(),
        "f": _int(),
        # f(v), die Korpusfrequenz des Kollokats. Ohne sie ist logdice
        # nicht nachrechenbar: f(u) steht als node_frequency im Kopf,
        # f(v) stand nirgends. MUSS hier deklariert sein, sonst bricht
        # die MCP-Route mit HTTP 500.
        "f2": _int(),
        "observed": _int(),
        "expected": _num(),
        "mi": _num(),
        # mi3 = log2(O11^3/E11) = MI + 2*log2(O11); damps MI's low-frequency bias
        # (first-class engine column, same as REST /analysis/collocates).
        "mi3": _num(),
        "lmi": _num(),
        "npmi": _num(),
        "z": _num(),
        "t": _num(),
        "ll": _num(),
        "dice": _num(),
        # logdice = Rychly 2008 (kanonisch). logdice_window = Dice auf
        # Everts Distanztafel, log-transformiert. Verschiedene Normierung.
        "logdice": _num(),
        "logdice_window": _num(),
        # Log Ratio und sein konservatives Gegenstueck (Hardie 2014). Sie
        # MUESSEN hier stehen, sonst bricht die MCP-Route mit HTTP 500.
        "log_ratio": _num(),
        "lrc": _num(),
        "chi2_cell": _num(),
        # delta-P directional collocation (F3, surfaced via seam A).
        "delta_p_nc": _num(),
        "delta_p_cn": _num(),
        "rank": _int(),
    },
    extra_top={
        "requested_term": _str(),
        "effective_term": _str(),
        "term_mode": _str(),
        # EFFECTIVE co-occurrence floor actually applied to the rows (H6/B6:
        # adaptively calibrated on the node frequency unless explicitly set).
        "min_freq": _int(),
        # Scoped hit count of the node itself — the calibration basis; null
        # only when the engine seam could not determine it.
        "node_frequency": _int(),
        # Declare the no-hit fields emitted by finding_substance.knoten_ohne_treffer.
        # The response schema rejects undeclared properties.
        "diagnosis": _str(),
        "schwelle_gebunden": _bool(),
        # Die Bilanz des Analyse-Token-Filters. OHNE diesen Eintrag bricht
        # die MCP-Route mit HTTP 500, weil _obj additionalProperties:false
        # setzt. Genau das ist am 2026-08-29 zweimal passiert.
        "diagnostics": _obj({}, additional=True),
        # Describe the fields supplied by this collocate row so the schema,
        # reported units and tool documentation agree.
        "metric_units": _obj(
            {
                "f": _str(),
                # Ohne Deklaration weist die eigene Validierung den neuen
                # Glossareintrag ab, und die MCP-Route antwortet mit 500.
                # Dieselbe Falle wie bei zwei Schluesseln zuvor.
                "f2": _str(),
                "observed": _str(),
                "expected": _str(),
                "node_frequency": _str(),
                "min_freq": _str(),
                "rank": _str(),
            },
            required=[
                "f",
                "f2",
                "observed",
                "expected",
                "node_frequency",
                "min_freq",
                "rank",
            ],
        ),
        "window": _int(),
        "within_sentence": _bool(),
        "sort_by": _str(),
        "result_count": _int(),
        "scope": _analysis_scope_response(),
        # Counting-attribute provenance, mirroring REST method.attribute:
        # 'word' (surface forms) or 'lemma'.
        "method": _obj(
            {"attribute": _str(), "floor_mode": _str()},
            required=["attribute", "floor_mode"],
        ),
    },
    required=[
        "status",
        "rows",
        "requested_term",
        "effective_term",
        "term_mode",
        "min_freq",
        "node_frequency",
        "window",
        "within_sentence",
        "sort_by",
        "result_count",
        "scope",
        "metric_units",
        "method",
    ],
)


def _validated_collocate_attribute(idx: Any, attribute: str | None) -> str:
    """Validate the counting attribute via the SAME REST seams (T2b parity).

    ``routes.analysis._collocate_attribute`` (word|lemma, else 422) and
    ``_require_lemma_attribute`` (422 with the token_attributes.lemma capability
    hint when the index lacks a usable lemma layer). Both server messages are
    passed through verbatim as ``ToolInputError`` so the MCP boundary maps them
    to an honest 400 error envelope instead of a leaked 500.
    """
    from fastapi import HTTPException

    from candyconc.services.backend.routes.analysis import (
        _collocate_attribute,
        _require_lemma_attribute,
    )

    try:
        attribute_key = _collocate_attribute(attribute)
        if attribute_key == "lemma":
            _require_lemma_attribute(idx)
    except HTTPException as exc:
        if int(getattr(exc, "status_code", 0) or 0) == 422:
            raise ToolInputError(str(getattr(exc, "detail", exc))) from exc
        raise
    return attribute_key


def _kollokat_einheiten() -> Dict[str, str]:
    """Das Einheiten-Glossar der Kollokationsantwort, EINE Quelle.

    Es stand als Literal in der Erfolgsantwort. Der leere Umschlag
    (Knoten ohne Treffer) braucht dasselbe Glossar, und zwei Kopien
    waeren genau die Naht, an der sie auseinanderlaufen. Am
    2026-08-30 hat der Prompt schon einmal das Gegenteil des Glossars
    behauptet, weil zwei Texte dieselbe Zahl beschrieben.
    """
    return {
        "f": lt(
            "Tokenzahl des Kollokats in der VEREINIGUNG der Fenster um alle Treffer des Knotens. Ein "
            "Token, das im Fenster mehrerer Treffer liegt, zählt einmal. f übersteigt die "
            "Korpusfrequenz des Kollokats daher nicht. O11 von Everts Kontingenztafel für "
            "distanzbasierte Kookkurrenzen (2004, Fig. 2.13). logdice ist Rychlý 2008 aus den "
            "Wortfrequenzen, logdice_window die Log-Transformation von dice auf derselben Distanztafel.",
            "Token count of the collocate in the UNION of the windows around all node hits. A token "
            "inside the windows of several hits is counted once. Thus f does not exceed the corpus "
            "frequency of the collocate. O11 in Evert’s contingency table for distance-based "
            "co-occurrences (2004, Fig. 2.13). logdice follows Rychlý 2008 using word frequencies, "
            "while logdice_window is the log transformation of dice on the same distance table.",
        ),
        "observed": lt("identisch mit f, O11 der 2x2-Tabelle", "identical to f, O11 of the 2x2 table"),
        "f2": lt(
            "Korpusfrequenz des Kollokats, C1 der Tafel. Zusammen mit node_frequency der Nenner von "
            "logdice: 14 + log2(2*f/(node_frequency + f2)).",
            "Corpus frequency of the collocate, C1 of the table. Together with node_frequency, the "
            "denominator of logdice: 14 + log2(2*f/(node_frequency + f2)).",
        ),
        "expected": lt(
            "E11 = R1*C1/N mit R1 = Umfang der Fenster-Vereinigung, C1 = Korpusfrequenz des Kollokats, "
            "N = Korpustoken. Eine Tokenerwartung, in derselben Einheit wie f.",
            "E11 = R1*C1/N with R1 = size of the window union, C1 = corpus frequency of the collocate, "
            "N = corpus tokens. An expected token count, in the same unit as f.",
        ),
        "node_frequency": lt(
            "Treffer des Knotens im Korpus. f/node_frequency ist kein Anteil: der Nenner von f ist der "
            "Umfang der Fenster-Vereinigung, nicht die Trefferzahl.",
            "Node hits in the corpus. f/node_frequency is not a proportion: the denominator of f is the"
            " size of the window union, not the hit count.",
        ),
        "min_freq": lt(
            "Mindest-f einer Zeile, keine Assoziationsschwelle",
            "Minimum f of a row, not an association threshold",
        ),
        "rank": lt("Zeilenposition unter sort_by, ab 1", "Row position under sort_by, starting at 1"),
    }


@llm_tool(COLLOCATE_TOOL, COLLOCATE_RESPONSE)
def collocate_stats_tool(
    term: str,
    window: int = 5,
    within_sentence: bool = True,
    sort_by: str | None = None,
    min_freq: int = 0,
    corpus: str | None = None,
    docset_id: str | None = None,
    attribute: str = "word",
) -> Dict[str, Any]:
    """Wrapper for :func:`collocate_stats` returning JSON rows.

    ``attribute`` mirrors REST /analysis/collocates (T2b): 'word' (default,
    byte-identical to the historical path) or 'lemma' (the term IS a lemma and
    co-occurrence is counted over the lemma column via the shared identity-
    lemmatizer seam). Validation and the lemma capability gate reuse the SAME
    route helpers, so a missing lemma layer yields the server's 422 message as
    an honest error. ``method.attribute`` records the provenance in the answer.
    Empty surface-form results stay empty: changing the node to a lemma would be
    a different analysis and must therefore be requested explicitly.

    ``min_freq=0`` (default) = automatic floor calibration on the node
    frequency (H6/B6) via the ONE shared seam ``tools.collocate_stats``: 5 for
    frequent nodes (byte-identical to the historical behaviour), down to 2 for
    rare nodes, so a 5-hit node no longer returns a structurally empty table.
    Explicit values >= 2 win. The response's ``min_freq`` is the EFFECTIVE
    floor applied to the rows and ``node_frequency`` the scoped hit count of
    the node the calibration is based on.
    """
    # Eingabe VOR dem Korpus pruefen: ohne aktiven Index kam sonst
    # RuntimeError statt ToolInputError (test_h6_collocate_adaptive_floor).
    try:
        requested_min_freq = int(min_freq)
    except (TypeError, ValueError) as exc:
        raise ToolInputError("min_freq muss eine ganze Zahl sein") from exc
    if requested_min_freq < 0:
        raise ToolInputError(
            "min_freq muss >= 0 sein (0 = automatische Kalibrierung)"
        )
    idx, doc_ids = _resolve_docset_doc_ids(corpus, docset_id)
    # Eine where()-Einschraenkung IM Term schraenkt den KNOTEN ein
    # (node_frequency 262 statt 919), das Referenzuniversum blieb aber
    # der ganze Korpus, und der gemeldete Scope sagte weiter "corpus".
    # Erwartungswerte gegen ein Universum, in dem der Knoten gar nicht
    # gesucht wurde, sind keine Erwartungswerte. Dieselbe Verwechslung
    # wie beim Nenner von query_count, beim Universum der Dispersion und
    # bei den Periodengroessen des Trends.
    _wo = _where_dokumente(idx, term)
    if _wo is not None:
        if doc_ids is None:
            doc_ids = np.asarray(_wo, dtype=np.uint32)
        else:
            doc_ids = np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_wo, dtype=np.uint32),
            )
    scope = _analysis_scope_provenance(
        idx,
        corpus=corpus,
        docset_id=docset_id,
        doc_ids=doc_ids,
    )
    attribute_key = _validated_collocate_attribute(idx, attribute)

    lemmatizer = None
    if attribute_key == "lemma":
        from candyconc.services.backend.routes.analysis import _identity_lemma

        lemmatizer = _identity_lemma

    df = _collocate_stats(
        term,
        window,
        lemmatizer=lemmatizer,
        within_sentence=within_sentence,
        sort_by=sort_by,
        corpus=idx,
        doc_ids=doc_ids,
        min_freq=(requested_min_freq or None),
    )
    rows = df.to_dict("records") if not df.empty else []
    frame_attrs = dict(getattr(df, "attrs", {}) or {})
    node_frequency = frame_attrs.get("node_frequency")
    effective_min_freq = frame_attrs.get("effective_min_count")
    if effective_min_freq is None:
        # Defensive fallback (engine doubles without the attrs seam): resolve
        # via the same shared helper the seam uses.
        from candyconc.analysis_defaults import adaptive_collocate_min_freq

        effective_min_freq = adaptive_collocate_min_freq(
            node_frequency, requested_min_freq or None
        )
    effective_term = term
    term_mode = "surface_or_cql" if attribute_key == "word" else "lemma_attribute"
    # P2.3: EINE Naht fuer alle drei Erzeuger, siehe
    # analysis_defaults.collocate_floor_mode.
    from candyconc.analysis_defaults import collocate_floor_mode

    floor_mode = collocate_floor_mode(
        requested_min_freq, effective_min_freq, node_frequency
    )
    _leer = _knoten_ohne_treffer(  # finding_substance
        term, node_frequency, int(effective_min_freq),
        effective_term=effective_term, term_mode=term_mode,
        method={"attribute": attribute_key, "floor_mode": floor_mode},
        scope=scope,
        herkunft={"window": int(window),
                  "within_sentence": bool(within_sentence),
                  "sort_by": str(sort_by or "logdice"),
                  "metric_units": _kollokat_einheiten()})
    if _leer is not None:
        return _leer
    return {
        "status": "success",
        "rows": rows,
        "requested_term": term,
        "effective_term": effective_term,
        "term_mode": term_mode,
        "min_freq": int(effective_min_freq),
        "node_frequency": (
            int(node_frequency) if node_frequency is not None else None
        ),
        "window": int(window),
        "within_sentence": bool(within_sentence),
        "sort_by": str(sort_by or "logdice"),
        "result_count": len(rows),
        "scope": scope,
        # Report the counting units with the result. The engine uses the union
        # of windows in Evert's distance table (2004, Fig. 2.13), so f counts tokens.
        "metric_units": _kollokat_einheiten(),
        "method": {"attribute": attribute_key, "floor_mode": floor_mode},
        # Expose counts of rows removed by the analysis-token filter.
        # normalize_default_collocate_frame records them before removal.
        # Keep them in diagnostics alongside the retained result count.
        "diagnostics": {
            "kandidaten": frame_attrs.get("analysetoken_kandidaten"),
            "gefiltert": frame_attrs.get("analysetoken_gefiltert"),
            "gefiltert_spitze": frame_attrs.get("analysetoken_spitze") or [],
        },
    }


COLLOCATION_NETWORK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "collocation_network",
        "description": (
            "Build a collocation NETWORK (graph) around a term: nodes are the "
            "term and its strongest collocates, edges carry an association "
            "measure (default logDice). expand_depth=2 builds an ego network "
            "with second-order collocates. Use this for 'network'/'graph'/'web' "
            "questions; use collocate_stats for a ranked table."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Keyword (auch CQL mit Prefix cql:)"},
                "window": {"type": "integer", "description": "token window", "default": 5},
                "measure": {
                    "type": "string",
                    "description": (
                        "Edge weight measure: logdice (empfohlen), dice, mi, mi3, "
                        "lmi, npmi, z, t, ll, chi2_cell."
                    ),
                    "default": "logdice",
                },
                "max_nodes": {
                    "type": "integer",
                    "description": "Max total nodes (capped server-side).",
                    "default": 30,
                },
                "expand_depth": {
                    "type": "integer",
                    "description": "1=star (first order), 2=ego network (second order).",
                    "default": 1,
                },
                "min_count": {
                    "type": "integer",
                    "description": "Minimum co-occurrence count before ranking.",
                    "default": 5,
                },
                "attribute": {
                    "type": "string",
                    "description": (
                        "Zählattribut 'word' (Default) oder 'lemma' (Seed-Term "
                        "wird als Lemma interpretiert; Fehler mit Capability-"
                        "Hinweis, wenn das Korpus kein Lemma-Attribut trägt)."
                    ),
                    "default": "word",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID (optional).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "window": {"type": "integer"},
            "measure": {"type": "string"},
            "max_nodes": {"type": "integer"},
            "expand_depth": {"type": "integer"},
            "min_count": {"type": "integer"},
            "attribute": {"type": "string"},
            "corpus": {"type": "string"},
            "docset_id": {"type": "string"},
        },
        "required": ["term"],
    },
}


COLLOCATION_NETWORK_RESPONSE = _obj(
    {
        "status": _str(),
        "term": _str(),
        "measure": _str(),
        "nodes": {
            "type": "array",
            # freq_via: the node from which a second order node's freq was
            # counted (tools/collocate_stats.py), not a corpus frequency.
            "items": _row_schema({"id": _str(), "freq": _int(), "depth": _int(), "freq_via": _str()}),
        },
        "edges": {
            "type": "array",
            "items": _row_schema(
                {"source": _str(), "target": _str(), "weight": _num(), "measure": _str()}
            ),
        },
        "diagnostics": _obj(
            {
                "node_count": _int(),
                "edge_count": _int(),
                "first_order_count": _int(),
                "second_order_count": _int(),
                "expand_depth": _int(),
                "max_nodes": _int(),
                "window": _int(),
                "min_count": _int(),
                "truncated": _bool(),
            },
            additional=True,
        ),
        # Counting-attribute provenance (REST parity): 'word' | 'lemma'.
        "method": _obj({"attribute": _str()}, required=["attribute"]),
        "metric_units": _obj(
            {"freq": _str(), "weight": _str()},
            required=["freq", "weight"],
        ),
        # Das Dokumentuniversum. Ohne dieses Feld war aus der Antwort nicht
        # ablesbar, ob 26 Knoten aus 683 oder aus 2000 Dokumenten stammen:
        # das Werkzeug schraenkt ueber where() ein und schwieg darueber,
        # waehrend das Nachbarwerkzeug collocate_stats fuer dieselbe
        # Abfrage scope level "docset", doc_count 683 meldete. Schweigen
        # liest sich als Korpus.
        "scope": _analysis_scope_response(),
    },
    required=[
        "status",
        "term",
        "measure",
        "nodes",
        "edges",
        "diagnostics",
        "method",
        "metric_units",
    ],
)


@llm_tool(COLLOCATION_NETWORK_TOOL, COLLOCATION_NETWORK_RESPONSE)
def collocation_network_tool(
    term: str,
    window: int = 5,
    measure: str = "logdice",
    max_nodes: int = 30,
    expand_depth: int = 1,
    min_count: int = 5,
    corpus: str | None = None,
    docset_id: str | None = None,
    attribute: str = "word",
) -> Dict[str, Any]:
    """Build a serializable collocation network around ``term``.

    Returns ``{status, term, measure, nodes, edges, diagnostics, method}`` where:
    - nodes: [{id: str, freq: int|None, depth: int}] — depth 0=seed, 1=first order, 2=second order.
    - edges: [{source: str, target: str, weight: float, measure: str}] — weight is the chosen measure.
    - diagnostics: {node_count, edge_count, first_order_count, second_order_count,
      expand_depth, max_nodes, window, min_count, truncated}.
    - method: {attribute} — counting-attribute provenance ('word' | 'lemma').
    No other fields are returned.

    ``attribute`` mirrors REST /analysis/collocation_network (T2b): 'lemma'
    interprets the seed term as a lemma and counts co-occurrence over the lemma
    column (identity-lemmatizer seam); the lemma capability gate reuses the SAME
    route helper, so a missing lemma layer yields the server's 422 message as an
    honest error. ``measure`` accepts the full REST list incl. mi3.
    """
    from candyconc.tools.collocate_stats import collocate_network_data

    idx, doc_ids = _resolve_docset_doc_ids(corpus, docset_id)
    # Wie bei der Kollokationstabelle: der Knoten folgt where(), das
    # Referenzuniversum blieb der ganze Korpus. Gemessen kippen dadurch
    # nicht nur die Assoziationswerte, sondern die Knotenmenge selbst.
    _wo = _where_dokumente(idx, term)
    if _wo is not None:
        doc_ids = (
            np.asarray(_wo, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_wo, dtype=np.uint32),
            )
        )
    attribute_key = _validated_collocate_attribute(idx, attribute)
    lemmatizer = None
    if attribute_key == "lemma":
        from candyconc.services.backend.routes.analysis import _identity_lemma

        lemmatizer = _identity_lemma
    data = collocate_network_data(
        term,
        window=window,
        measure=measure,
        max_nodes=max_nodes,
        expand_depth=expand_depth,
        min_count=min_count,
        lemmatizer=lemmatizer,
        corpus=idx,
        doc_ids=doc_ids,
        # Set sentence boundaries explicitly to match the REST route.
        # The core collocate_network_data default otherwise permits cross-sentence windows.
        within_sentence=True,
    )
    return {
        "status": "success",
        "term": data["term"],
        "measure": data["measure"],
        "nodes": data["nodes"],
        "edges": data["edges"],
        "diagnostics": data["diagnostics"],
        "method": {"attribute": attribute_key},
        "metric_units": {
            "freq": lt(
                "Tokenzahl in der VEREINIGUNG der Fenster, dieselbe Zahl wie f bei collocate_stats: ein "
                "Token im Fenster mehrerer Treffer zählt einmal, und f übersteigt die Korpusfrequenz des "
                "Kollokats nicht. Beim Seed ist es die Trefferzahl.",
                "Token count in the UNION of the windows, the same count as f in collocate_stats: a token "
                "inside the windows of several hits is counted once, and f does not exceed the corpus "
                "frequency of the collocate. For the seed, this is the hit count.",
            ),
            "weight": lt(
                "der unter measure gewählte Assoziationswert der Kante",
                "The association measure selected under measure for the edge",
            ),
        },
        "scope": _analysis_scope_provenance(
            idx, corpus=corpus, docset_id=docset_id, doc_ids=doc_ids),
    }


COMPARE_COLLOCATES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "compare_collocates",
        "description": "Compare collocations for a term between Human and AI subcorpora.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Keyword"},
                "window": {
                    "type": "integer",
                    "description": "token window",
                    "default": 5,
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "window": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": ["term"],
    },
}


COMPARE_COLLOCATES_RESPONSE = _rows_response(
    {
        "word": _str(),
        "freq_human": _int(),
        "freq_ai": _int(),
        "chi2_cell_human": _num(),
        "chi2_cell_ai": _num(),
        "log_ratio": _num(),
        "one_sided": _bool(),
    },
    extra_top={
        "total": _int(),
        "truncated": _bool(),
        "reason": _str(),  # present on the not_applicable branch
        "message": _str(),
        "diagnostics": _obj({}, additional=True),
    },
)


@llm_tool(COMPARE_COLLOCATES_TOOL, COMPARE_COLLOCATES_RESPONSE)
def compare_collocates_tool(
    term: str,
    window: int = 5,
    corpus: str | None = None,
) -> Dict[str, Any]:
    idx, _ = _resolve_docset_doc_ids(corpus, None)
    # W2 STEP 7: the Human/AI comparison is only meaningful on a paired corpus.
    # On a flat / unpaired corpus it would degenerate (all collocates on one side,
    # log_ratio pinned to ±10), so surface a graceful not_applicable and point the
    # copilot at the pairing-free alternative instead of returning misleading rows.
    manifest = getattr(idx, "manifest", None)
    if manifest is not None and not bool(getattr(manifest, "paired", False)):
        return {
            "status": "not_applicable",
            "reason": "corpus_not_paired",
            "rows": [],
            "message": (
                "Dieser Korpus ist nicht gepaart (kein Mensch/KI-Kontrast vorhanden). "
                "Für einen Kontrast zweier beliebiger Teilkorpora nutze 'collocate_stats' "
                "je Docset bzw. den freien Kontrast (/analysis/contrast)."
            ),
            "diagnostics": {"paired": False},
        }
    df = _compare_collocates(term, window=window, corpus=idx)
    rows = df.to_dict("records") if not df.empty else []
    model_values = _metadata_axis_values(idx, "model")
    text_type_values = _metadata_axis_values(idx, "text_type")
    # compare_human_ai is a thin shim over compare_by_docset_masks, which returns
    # a single UNIFIED table capped at top_n*2 = 100 (not 50 per side). Flag
    # truncation against that real cap, else 50-99-row results false-positive.
    _compare_cap = 100
    return {
        "status": "success",
        "rows": rows,
        "total": len(rows),
        "truncated": len(rows) >= _compare_cap,
        "diagnostics": {
            "model_values": model_values,
            "text_type_values": text_type_values,
            "top_n": _compare_cap,
            # Paired imports since builder revision 2 record the sides as
            # text_type anchor and version (core.pairing), older ones as human and ai.
            "has_human_axis": any(value.lower() in {"human", "mensch", "menschen"} for value in model_values + text_type_values)
            or any(_is_anchor(value) for value in text_type_values),
            "has_ai_axis": any(value.lower() in {"ai", "ki", "llm", "machine", "synthetic"} for value in model_values + text_type_values)
            or any(_is_version(value) for value in text_type_values),
        },
    }


CONTRAST_COLLOCATES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "contrast_collocates",
        "description": (
            "Pairing-free collocation contrast of a term between TWO arbitrary "
            "subcorpora (docsets). Works on ANY corpus — no Human/AI pairing "
            "required. Use this for 'compare collocates of X in subcorpus A vs B' "
            "(e.g. news vs blog, model-vs-model, register-vs-register). "
            "Distinct from 'compare_collocates', which is the Human/AI specialist "
            "axis and only works on a PAIRED corpus. Both docset ids are required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                # Der where()-Hinweis steht HIER und nicht in TOOLS_DOC: die
                # Parameterbeschreibung geht als Funktionsschema an das Modell
                # und zahlt nicht auf STATIC_CORE_CHAR_COUNT ein, das bei 3
                # Zeichen Rest steht.
                "term": {
                    "type": "string",
                    "description": (
                        "Wortform oder CQL-Muster. KEIN where(): die beiden "
                        "Docsets definieren den Kontrast bereits, eine dritte "
                        "Einschraenkung waere entweder redundant oder "
                        "widerspricht ihnen. Schneide sie in die Docsets."
                    ),
                },
                "target_docset_id": {
                    "type": "string",
                    "description": "Docset-ID ODER gespeicherter Subkorpus-Name des Zielkorpus (Seite A).",
                },
                "reference_docset_id": {
                    "type": "string",
                    "description": "Docset-ID ODER gespeicherter Subkorpus-Name des Referenzkorpus (Seite B).",
                },
                "window": {
                    "type": "integer",
                    "description": "token window",
                    "default": 5,
                },
                "top_n": {
                    "type": "integer",
                    "description": "Anzahl der zurückgegebenen Zeilen",
                    "default": 50,
                },
                "within_sentence": {
                    "type": "boolean",
                    "description": "Nur innerhalb von Satzgrenzen zählen",
                    "default": True,
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["term", "target_docset_id", "reference_docset_id"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "target_docset_id": {"type": "string"},
            "reference_docset_id": {"type": "string"},
            "window": {"type": "integer"},
            "top_n": {"type": "integer"},
            "within_sentence": {"type": "boolean"},
            "corpus": {"type": "string"},
        },
        "required": ["term", "target_docset_id", "reference_docset_id"],
    },
}


CONTRAST_COLLOCATES_RESPONSE = _rows_response(
    {
        "word": _str(),
        "freq_target": _num(),
        "freq_reference": _num(),
        "chi2_cell_target": _num(),
        "chi2_cell_reference": _num(),
        "log_ratio": _num(),
        "one_sided": _bool(),
    },
    extra_top={
        "total": _int(),
        "truncated": _bool(),
        # Die beiden Kontrastseiten. Sie MUESSEN im Schema stehen: das
        # Antwortschema traegt additionalProperties:false, und ein neuer
        # Schluessel ohne Eintrag hier bricht die MCP-Route mit HTTP 500
        # ("Additional properties are not allowed"). Genau das ist am
        # 2026-08-29 passiert, als die Schluessel eingefuehrt wurden, ohne
        # das Schema nachzuziehen. Die Suite war gruen, weil kein Test die
        # MCP-Naht fuhr.
        "target_docset_id": _str(),
        "reference_docset_id": _str(),
        "diagnostics": _obj({}, additional=True),
    },
)


@llm_tool(CONTRAST_COLLOCATES_TOOL, CONTRAST_COLLOCATES_RESPONSE)
def contrast_collocates_tool(
    term: str,
    target_docset_id: str,
    reference_docset_id: str,
    window: int = 5,
    top_n: int = 50,
    within_sentence: bool = True,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """Pairing-free collocation contrast between two arbitrary docsets (W2).

    Resolves both docsets to document-id arrays, builds two boolean document
    masks, and calls :meth:`CollocationEngine.compare_by_docset_masks` (scoring
    stays ``global`` to preserve the grounding contract). Unlike
    :func:`compare_collocates_tool` this requires NO paired corpus.
    """
    if not term or not str(term).strip():
        raise RuntimeError("term muss angegeben werden.")
    if not target_docset_id or not reference_docset_id:
        raise RuntimeError(
            "target_docset_id und reference_docset_id müssen beide angegeben werden."
        )
    try:
        window = int(window)
    except (TypeError, ValueError):
        raise RuntimeError("window muss eine ganze Zahl sein.")
    if window < 1:
        raise RuntimeError("window muss >= 1 sein.")

    # Both ids accept EITHER a live docset_id OR a persisted subcorpus name.
    target_docset_id = _coerce_docset_id(target_docset_id, corpus)
    reference_docset_id = _coerce_docset_id(reference_docset_id, corpus)
    idx, target_ids = _resolve_docset_doc_ids(corpus, target_docset_id)
    _, reference_ids = _resolve_docset_doc_ids(corpus, reference_docset_id)
    if target_ids is None or reference_ids is None:
        raise RuntimeError("Docset-IDs konnten nicht geladen werden.")

    # The two docsets define this contrast's populations. A where() clause
    # inside the anchor term is ambiguous: applying it to both sides could
    # empty a reference population, while treating it literally could return
    # a false zero. Request clarification instead of choosing either meaning.
    if _where_dokumente(idx, term) is not None:
        raise ToolInputError(
            "term darf hier kein where() enthalten: die beiden Docsets "
            "definieren den Kontrast bereits, eine dritte Einschränkung "
            "wäre entweder redundant oder widerspricht ihnen. Gib die "
            "Wortform als term an und schneide die Einschränkung in die "
            "Docsets (create_docset)."
        )

    from candyconc.core.collocation_engine import get_engine

    corpus_path = Path(idx.fast_index.index_path)
    engine = get_engine(corpus_path)
    if not getattr(engine, "_loaded", False):
        engine.load()

    # The engine's document masks are indexed by document index and must match
    # the length the engine itself uses (``len(engine._doc_bounds)`` — the same
    # source ``compare_human_ai`` derives its human/ai masks from). Falling back
    # to the index's document count keeps this robust if doc bounds are absent.
    doc_bounds = getattr(engine, "_doc_bounds", None)
    if doc_bounds is not None:
        n_docs = int(len(doc_bounds))
    else:
        n_docs = int(idx.fast_index.boundaries.document._positions.size)

    target_mask = np.zeros(n_docs, dtype=bool)
    reference_mask = np.zeros(n_docs, dtype=bool)
    t_ids = np.asarray(target_ids, dtype=np.int64)
    r_ids = np.asarray(reference_ids, dtype=np.int64)
    t_ids = t_ids[(t_ids >= 0) & (t_ids < n_docs)]
    r_ids = r_ids[(r_ids >= 0) & (r_ids < n_docs)]
    target_mask[t_ids] = True
    reference_mask[r_ids] = True

    df = engine.compare_by_docset_masks(
        term,
        target_doc_mask=target_mask,
        reference_doc_mask=reference_mask,
        window_left=window,
        window_right=window,
        top_n=int(top_n),
        within_sentence=bool(within_sentence),
        scoring="global",
    )
    if hasattr(df, "to_dicts"):
        rows = df.to_dicts()  # Polars
    elif hasattr(df, "to_dict"):
        rows = df.to_dict("records") if not df.empty else []  # Pandas
    else:
        rows = []
    # Apply the same analysis-token rule as frequency, n-gram and REST
    # collocation results to exclude punctuation and internal index markers.
    kandidaten = len(rows)
    # Keep the removed rows as well as their count so the answer can identify
    # which formatting or punctuation contrasts the analysis filter excluded.
    _verworfen = [
        r for r in rows
        if not _is_analyst_token(str(r.get("word") or r.get("collocate") or ""))
    ]
    rows = [
        r for r in rows
        if _is_analyst_token(str(r.get("word") or r.get("collocate") or ""))
    ]
    # The engine returns a single UNIFIED contrast table capped at top_n*2
    # (collocation_engine.compare_by_docset_masks), not top_n per side. Flag
    # truncation against that real cap, else frequent terms false-positive.
    truncated = kandidaten >= int(top_n) * 2
    # RICHTUNG und NENNER, beide bereits berechnet.
    #
    # Ohne die Docset-Kennungen ist aus der Nutzlast nicht rekonstruierbar,
    # welche Seite target und welche reference ist: die Antwort sprach
    # deshalb von "Seite A" und "Seite B", und eine Professorin-Subagentin
    # hat das am 2026-08-29 als toedlich gewertet, weil die Zahlen damit
    # unzitierfaehig sind. Die IDs stehen im Aufruf, sie werden hier nur
    # zurueckgegeben.
    #
    # Ohne die Kontextmassen sind freq_target und freq_reference zwei
    # Zahlen ohne Bezug. Die Engine haengt sie seit heute an df.attrs.
    _attrs = dict(getattr(df, "attrs", {}) or {})
    return {
        "status": "success",
        "rows": rows,
        "target_docset_id": str(target_docset_id or ""),
        "reference_docset_id": str(reference_docset_id or ""),
        # Die KANDIDATENmenge vor dem Analyse-Token-Filter, nicht die
        # Zeilenzahl. "total gleich len(rows)" sagt nur, wie lang die
        # Antwort ist, und verschweigt, wie viel die Rangliste weggelassen
        # hat -- dieselbe Auskunft, die ngram_contrast als
        # total_candidates fuehrt.
        "total": kandidaten,
        "truncated": truncated,
        "diagnostics": {
            "paired": bool(getattr(getattr(idx, "manifest", None), "paired", False)),
            "n_docs": n_docs,
            "target_docs": int(t_ids.size),
            "reference_docs": int(r_ids.size),
            # Die Nenner, gegen die freq_target und freq_reference zu lesen
            # sind. Ohne sie ist "122 gegen 0" kein Verhaeltnis.
            "node_frequency_target": _attrs.get("node_frequency_target"),
            "node_frequency_reference": _attrs.get("node_frequency_reference"),
            "context_mass_target": _attrs.get("context_mass_target"),
            "context_mass_reference": _attrs.get("context_mass_reference"),
            # DIREKT hinter den Nennern, nicht am Ende: die Modellsicht
            # kappt diese Abbildung (grounding_evidence), und scoring/
            # within_sentence/top_n sind die Parameter des Aufrufers
            # selbst, die er ohnehin kennt.
            "gefiltert": len(_verworfen),
            "gefiltert_spitze": _analysetoken_spitze(_verworfen, "log_ratio"),
            "scoring": "global",
            "within_sentence": bool(within_sentence),
            "top_n": int(top_n),
        },
    }


WORD_SKETCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "word_sketch",
        "description": (
            "Compute grammatical collocations from the indexed dependency "
            "head/relation layer, not from a token window. Applies the same "
            "reliability floor as the analysis profile: collocates with a "
            "co-occurrence frequency below the disclosed `min_freq` (default 3) "
            "are suppressed, so f=1/f=2 hapaxes never headline a relation. The "
            "applied `min_freq` is returned on the response. `min_freq` is a "
            "PARTNER-ROW threshold: partner rows with f >= min_freq are listed; "
            "the floor filters partners, not relations. Without an explicit "
            "coverage denominator the rows do not show what proportion of all "
            "term tokens has a relation, so do not call a relation dominant or "
            "predominant."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Keyword"}
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {"term": {"type": "string"}},
        "required": ["term"],
    },
}


WORD_SKETCH_RESPONSE = _obj(
    {
        "status": _str(),
        # Disclosed reliability floor (WS-COPILOT-NOFLOOR): rows whose
        # co-occurrence frequency ``f`` is below ``min_freq`` are suppressed, so
        # the copilot tool headlines the SAME floored relations as the REST
        # profile and /analysis/wordsketch_diff (no f=1/f=2 hapaxes).
        "min_freq": _int(),
        # Härtung r3, Fix 3: ``metric_units`` is REQUIRED (below) and always
        # returned, but was never declared here — with the object's
        # ``additionalProperties: false`` a real success response validated as a
        # 500 ("Additional properties are not allowed ('metric_units' was
        # unexpected)"). Masked on the bench index because word_sketch fails the
        # ``token_attributes.rel`` feature-gate before returning rows. Declared
        # with the SAME shape collocate_stats uses so the schema stays strict.
        "metric_units": _obj(
            {
                "f": _str(),
                "frequency": _str(),
                "f2": _str(),
                "f2_basis": _str(),
                "min_freq": _str(),
                "rank": _str(),
                "score": _str(),
            },
            required=[
                "f",
                "frequency",
                "f2",
                "f2_basis",
                "min_freq",
                "rank",
                "score",
            ],
        ),
        "relations": {
            "type": "object",
            "additionalProperties": _obj(
                {
                    "relation": _str(),
                    "label": _str(),
                    "row_limit": _int(),
                    "total_candidates": _int(),
                    "total_rows": _int(),
                    "truncated": _bool(),
                    "min_freq": _int(),
                    "basis": _str(),
                    "coverage_scope": _str(),
                },
                required=[
                    "relation",
                    "label",
                    "row_limit",
                    "total_candidates",
                    "total_rows",
                    "truncated",
                    "min_freq",
                    "basis",
                    "coverage_scope",
                ],
            ),
        },
        "tables": {
            # Keys are dependency-relation names; each maps to a list of rows.
            "type": "object",
            "additionalProperties": {
                "type": "array",
                "items": _row_schema(
                    {
                        "word": _str(),
                        "f": _int(),
                        "frequency": _int(),
                        "chi2_cell": _num(),
                        "t": _num(),
                        "ll": _num(),
                        # Shared per-row word-sketch scorer (DT-WORD-SKETCH-ZOMBIE):
                        # f2 = collocate marginal frequency, f2_basis names how it
                        # was derived, ll_signed carries the direction sign. The
                        # visible ranking is conveyed by score / score_key; the raw
                        # ``dice`` / ``logdice`` scorer columns are stripped from the
                        # copilot rows so the advertised row stays exactly these
                        # documented fields (no undeclared field reaches the LLM).
                        "f2": _int(),
                        "f2_basis": _str(),
                        "ll_signed": _num(),
                        "rank": _int(),
                        "score": _num(),
                        "score_key": _str(),
                    }
                ),
            },
        },
    },
    required=["status", "metric_units", "tables"],
)


@llm_tool(WORD_SKETCH_TOOL, WORD_SKETCH_RESPONSE)
def word_sketch_tool(term: str) -> Dict[str, Any]:
    """Wrapper for :func:`word_sketch` returning JSON rows per relation.

    Applies the SHARED word-sketch reliability floor (WS-COPILOT-NOFLOOR) so the
    copilot tool headlines the SAME floored relations as the REST profile and
    /analysis/wordsketch_diff — a single accidental co-occurrence (typo, list
    bullet) can no longer top a relation via an inflated single-cell chi2. The
    applied ``min_freq`` is disclosed on the response.
    """
    min_freq = int(WORD_SKETCH_DEFAULT_MIN_FREQ)
    row_limit = 8
    tables = _apply_word_sketch_min_freq(_word_sketch(term, top_rows=0), min_freq=min_freq)
    # The visible ranking is conveyed by ``score`` / ``score_key``; drop the raw
    # ``dice`` / ``logdice`` scorer columns so each row carries exactly the
    # advertised (response_schema) fields and the LLM never sees an undocumented
    # column (the row schema is additionalProperties:false).
    drop_cols = ("dice", "logdice")
    result: Dict[str, List[Dict[str, Any]]] = {}
    relations: Dict[str, Dict[str, Any]] = {}
    for rel, df in tables.items():
        if df is None:
            continue
        total_candidates = int(len(df))
        visible_df = df.head(row_limit)
        rows = visible_df.drop(columns=[c for c in drop_cols if c in visible_df.columns]).to_dict("records")
        if not rows:
            continue
        result[rel] = rows
        relations[rel] = {
            "relation": rel,
            "label": word_sketch_relation_label(rel),
            "row_limit": row_limit,
            "total_candidates": total_candidates,
            "total_rows": int(len(rows)),
            "truncated": total_candidates > row_limit,
            "min_freq": min_freq,
            "basis": "indexed_dependency_relations",
            "coverage_scope": "relation_events_at_or_above_min_freq",
        }
    return {
        "status": "success",
        "min_freq": min_freq,
        "metric_units": {
            "f": "indexed dependency event count for this partner row",
            "frequency": "alias of f",
            "f2": "marginal token frequency of the partner",
            "f2_basis": "corpus scope used to compute f2",
            "min_freq": (
                "minimum f required to include a partner row; not a "
                "relation-level threshold"
            ),
            "rank": "one-based row position under score_key",
            "score": "ranking value named by score_key",
        },
        "relations": relations,
        "tables": result,
    }


FREQUENCY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "frequency_list",
        "description": (
            "Return word, lemma, or POS frequency list for the active corpus. "
            "Pass `pos` (a UPOS tag, e.g. 'NOUN', 'VERB', 'ADJ') to restrict the "
            "word/lemma ranking to tokens of that part of speech — this is the "
            "correct way to answer 'die häufigsten Substantive/Nomen' (NOUN), "
            "'häufigste Verben' (VERB), etc. Without `pos` the ranking spans the "
            "whole vocabulary (function words dominate). `limit` caps the returned "
            "rows (default/max 100). Per-million values use denominator_tokens: "
            "the whole corpus when unscoped, or the selected docset's exact token "
            "count. denominator_scope/source disclose that provenance; "
            "corpus_tokens always remains the full corpus size. `docset_id` must "
            "be a live ID returned by create_docset/resolve_subcorpus or an "
            "existing saved subcorpus name; never pass a raw value returned by "
            "metadata_values as a docset ID."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stopwords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Words to exclude",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "docset_id": {
                    "type": "string",
                    "description": (
                        "Optionale Live-Docset-ID aus create_docset/"
                        "resolve_subcorpus oder belegter gespeicherter "
                        "Subkorpus-Name. Kein roher Metadatenwert."
                    ),
                },
                "group_by": {
                    "type": "string",
                    "enum": ["word", "lemma", "pos"],
                    "description": "Zählebene der Frequenzliste.",
                },
                "pos": {
                    "type": "string",
                    "description": (
                        "Optionaler UPOS-Tag (z.B. 'NOUN', 'VERB', 'ADJ'): "
                        "beschraenkt die Wort-/Lemma-Rangliste auf Tokens dieser "
                        "Wortart. Nur für group_by=word/lemma sinnvoll."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max. zurückgegebene Zeilen (Default/Max 100).",
                },
            },
            "additionalProperties": False,
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "stopwords": {
                "type": "array",
                "items": {"type": "string"},
            },
            "corpus": {"type": "string"},
            "docset_id": {"type": "string"},
            "group_by": {"type": "string", "enum": ["word", "lemma", "pos"]},
            "pos": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "additionalProperties": False,
    },
}


FREQUENCY_RESPONSE = _rows_response(
    # B2 (Q2): per_million je Zeile mit dem expliziten Scope-Nenner vorgerechnet.
    {"word": _str(), "f": _int(), "per_million": _num()},
    extra_top={
        "total": _int(),
        "truncated": _bool(),
        "corpus_tokens": _int(),
        "denominator_tokens": _int(),
        "denominator_tokens_raw": _int(),
        "denominator_scope": _str(),
        "denominator_source": _str(),
        "group_by": _str(),
        "pos": _str(),
        # Absage-Schluessel fuer ein Attribut ohne Annotation
        # (finding_substance.annotation_entartet). Ohne Deklaration
        # setzt _obj additionalProperties=False durch und die MCP-Route
        # antwortet HTTP 500, statt die Absage durchzulassen. Gemessen im
        # nachher-Lauf, Zeile 910. Gleiche Fehlerklasse wie bei
        # COLLOCATE_RESPONSE oben: dort war es knoten_ohne_treffer.
        "message": _str(),
    },
    required=[
        "status",
        "rows",
        "total",
        "truncated",
        "corpus_tokens",
        "denominator_tokens",
        "denominator_scope",
        "denominator_source",
        "group_by",
    ],
)


_FREQUENCY_ROW_CAP = 100


@llm_tool(FREQUENCY_TOOL, FREQUENCY_RESPONSE)
def frequency_list_tool(
    stopwords: Optional[List[str]] = None,
    corpus: str | None = None,
    docset_id: str | None = None,
    group_by: str = "word",
    pos: str | None = None,
    limit: int | None = None,
    **_extra: Any,
) -> Dict[str, Any]:
    """Wrapper for :func:`frequency_list` returning JSON rows.

    ``pos`` (id 15): an optional UPOS tag (e.g. ``"NOUN"``) restricts the
    word/lemma ranking to tokens of that part of speech, so a request for the
    most frequent nouns runs a real POS-filtered frequency over the WHOLE corpus
    (or docset) instead of being eyeballed off the top unfiltered lemmas. It
    reuses the index's existing pos-prefix frequency path
    (``frequency_counts_docset(..., pos_prefix=...)`` via
    :meth:`CorpusIndex.frequency_list_docset`) — the same mechanism keyness uses.
    A POS prefix is only meaningful for word/lemma rankings, so it is ignored
    for ``group_by="pos"``.

    ``limit`` (id 13): caps the returned rows (default/max 100). The function
    also accepts and ignores stray keyword arguments (``**_extra``) so an
    unexpected kwarg emitted by the LLM (e.g. an extra filter param) degrades to
    a normal answer instead of crashing with a TypeError -> HTTP 500.
    """
    pos_prefix = str(pos).strip() if pos and str(pos).strip() else None
    if group_by not in ("word", "lemma"):
        pos_prefix = None
    idx, doc_ids = _resolve_docset_doc_ids(corpus, docset_id)

    if pos_prefix:
        # POS-filtered ranking: reuse the index pos-prefix frequency path for the
        # requested word or lemma stream. The docset helper resolves to the WHOLE
        # corpus when no docset was given (all doc ids).
        ids = doc_ids
        if ids is None:
            ids = np.arange(_get_doc_count(idx), dtype=np.uint32)
        df = idx.frequency_list_docset(
            ids,
            stopwords=stopwords,
            pos_prefix=pos_prefix,
            attr=group_by,
        )
        # FIX-A (COPILOT-POS-FREQ-LEAK): the POS-filtered ranking must drop the
        # SAME non-analyst tokens (emoji/symbols/|LBR|/punctuation) the REST/UI
        # path drops — route it through the one shared analyst-token seam
        # (filter_frequency_frame), the same call routes/analysis.py applies after
        # frequency_list_docset(pos_prefix=...). Without this the copilot total and
        # rows leak tokens the REST sibling excludes (e.g. 9741/4842 rows instead
        # of the filtered 9611/4817 for NOUN), contradicting the other surfaces.
        df = _filter_frequency_frame(df)
    else:
        df = _frequency_list(
            stopwords=stopwords, corpus=idx, doc_ids=doc_ids, group_by=group_by
        )

    cap = _FREQUENCY_ROW_CAP
    if limit is not None:
        try:
            cap = max(1, min(int(limit), _FREQUENCY_ROW_CAP))
        except (TypeError, ValueError):
            cap = _FREQUENCY_ROW_CAP
    if hasattr(df, "to_dicts"):
        rows = df.head(cap).to_dicts()  # Polars — limit for LLM context
    elif hasattr(df, "to_dict"):
        rows = df.head(cap).to_dict("records")  # Pandas
    else:
        rows = []
    total = len(df) if hasattr(df, "__len__") else len(rows)
    # The row cap means the bundle is NOT complete when total exceeds the
    # returned rows. Surface a truncation flag so the copilot never claims it
    # has seen the full frequency distribution.
    # Keep full-corpus size and effective normalisation denominator separate.
    # Using corpus_tokens for a docset would produce plausible but wrong rates.
    corpus_tokens = 0
    with contextlib.suppress(Exception):
        corpus_tokens = int(idx.token_count())
    # Use analysis tokens as the denominator, matching keyness.
    bezug = _nenner_der_frequenzliste(idx, doc_ids, group_by, corpus_tokens)
    denominator_scope = "corpus" if doc_ids is None else "docset"
    denominator_tokens = int(bezug["woerter"])
    denominator_source = bezug["quelle"]
    if denominator_tokens > 0:
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("f"), (int, float)):
                row["per_million"] = round(
                    float(row["f"]) * 1_000_000 / denominator_tokens,
                    1,
                )
    result = {
        "status": "success",
        "rows": rows,
        "total": total,
        "truncated": total > len(rows),
        "corpus_tokens": corpus_tokens,
        "denominator_tokens": denominator_tokens,
        "denominator_tokens_raw": int(bezug["roh"]),
        "denominator_scope": denominator_scope,
        "denominator_source": denominator_source,
        "group_by": group_by,
    }
    # Die Absage erbt die PFLICHTFELDER des Erfolgsumschlags und
    # ueberschreibt nur status/message. Anders herum (erst absagen, dann
    # den Erfolgsumschlag bauen) fehlten dem Fehlerfall acht der neun
    # required-Felder, und die MCP-Route beantwortete ihn mit HTTP 500.
    _absage = _annotation_entartet(  # finding_substance
        group_by, rows, denominator_tokens, umschlag=result)
    if _absage is not None:
        return _absage
    if pos_prefix:
        result["pos"] = pos_prefix
    return result


DISPERSION_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "dispersion_offsets",
        "description": "Return token offsets plus a compact dispersion profile for the given term.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Search term"},
                "partitions": {
                    "type": "integer",
                    "description": "Number of corpus buckets for the summary profile",
                    "default": 10,
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "partitions": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": ["term"],
    },
}


DISPERSION_RESPONSE = _obj(
    {
        "status": _str(),
        "term": _str(),
        "offsets": {"type": "array", "items": {"type": "integer"}},
        "unit": _str(),  # "documents" | "positional_windows"
        "total_hits": _int(),
        "nonzero_partitions": _int(),
        "coverage_ratio": _num(),
        "peak_partition": _int(),
        "peak_share": _num(),
        # peak_partition ist IMMER eine globale Dokument-ID, auch unter
        # where(). Vorher war es dort ein Index in die zugeschnittene
        # Menge, und wer den Spitzenreiter nachschlug, landete auf einem
        # unbeteiligten Dokument.
        "profile": _str(),
        # DOCUMENT mode (default unit="documents"):
        "n_documents": _int(),
        "observed": {"type": "array", "items": {"type": "integer"}},
        "doc_sizes": {"type": "array", "items": {"type": "integer"}},
        "dp": _num(),
        "dpnorm": _num(),
        # Die drei Referenzwerte, ohne die dp nicht deutbar ist. Sie
        # MUESSEN hier stehen: das Antwortschema traegt
        # additionalProperties:false, und ein Feld ohne Eintrag bricht die
        # MCP-Route mit HTTP 500. Als die Felder am 2026-08-29 eingefuehrt
        # wurden, blieb dieser Eintrag aus, und die volle Suite war gruen,
        # weil kein Test die Antwort gegen ihr eigenes Schema hielt.
        "dp_min": _num(),
        "dp_erwartet": _num(),
        "dp_max": _num(),
        # Dispersion family (FT-DISPERSION-FAMILY, surfaced via
        # summarize_dispersion_offsets): Juilland's D, Carroll's D2, Range and
        # the coefficient of variation alongside the default DP.
        "juilland_d": _num(),
        "carroll_d2": _num(),
        "range": _int(),
        "range_prop": _num(),
        "vc": _num(),
        # POSITIONAL-WINDOW fallback (unit="positional_windows"):
        "partitions": {"type": "array", "items": {"type": "integer"}},
        "positional_dp_windowed": _num(),
    },
    required=["status", "term", "offsets", "unit", "total_hits", "profile"],
)


@llm_tool(DISPERSION_TOOL, DISPERSION_RESPONSE)
def dispersion_offsets_tool(
    term: str, partitions: int = 10, corpus: str | None = None
) -> Dict[str, Any]:
    """Wrapper for :func:`dispersion_offsets` returning offsets and a summary profile.

    FT-COPILOT-CORPUS-RESOLVE: resolves the corpus PER CALL (``corpus`` arg, else
    the active corpus) via ``_resolve_corpus_index`` instead of reading the
    process-global ``query_runtime._CORPUS_INDEX``.

    FIX-D (COPILOT-DISPERSION-BRACKET-CQL): offsets are resolved through the SAME
    REST seam the /analysis/dispersion path uses
    (``server._dispersion_positions_for_term``), so bracket-CQL forms like
    ``[word=".*"]`` / ``[pos="NOUN"]`` resolve via the CQL engine (non-zero) and
    the index-only ``|LBR|`` sentinel is dropped — instead of the old
    ``sequence_positions([term])`` path that treated a CQL string as one literal
    token and returned total_hits=0. The dispersion math (``summarize_dispersion_
    offsets``) is unchanged, so copilot total_hits now equals REST/count:
    ``[word=".*"]``=55550, ``[word="|LBR|"]``=0, ``[pos="NOUN"]``=9740.

    COPILOT-COUNT-BRACKETCQL-DIVERGE: malformed un-prefixed bracket attempts are
    rejected with the SAME 400 the REST /analysis/dispersion route raises (via the
    shared ``_reject_malformed_bracket_cql`` guard), while legacy attribute clauses
    accepted by /query (for example ``[pos=NOUN]``) remain supported.
    """
    idx = _resolve_corpus_index(corpus)
    from candyconc.services.backend import server as _server
    from candyconc.services.backend.routes.analysis import _reject_malformed_bracket_cql
    from fastapi import HTTPException

    # COPILOT-COUNT-BRACKETCQL-DIVERGE: malformed bracket attempts must surface the
    # SAME 400 the REST /analysis/dispersion route raises — not the silent
    # total_hits=0 the literal-token fall-through used to return. The guard raises
    # an HTTPException(400); re-raise it as ToolInputError so the MCP boundary maps
    # it to a 400 (a raw HTTPException would degrade to 500).
    try:
        _reject_malformed_bracket_cql(_server, idx, term)
    except HTTPException as exc:
        if getattr(exc, "status_code", None) == 400:
            raise ToolInputError(str(getattr(exc, "detail", exc))) from exc
        raise

    # Apply the query's where() restriction to the document population.
    # Dispersion and document coverage need the same scope as the hit count.
    _wo = _where_dokumente(idx, term)
    _maske = None
    if _wo is not None:
        from candyconc.core.fast_index_native import docset_mask_from_ids

        try:
            _n = int(idx.fast_index.boundaries.document._positions.size)
        except Exception:
            _n = int(_get_doc_count(idx))
        _maske = docset_mask_from_ids(np.asarray(_wo, dtype=np.uint32), _n)
    offsets = np.asarray(
        _server._dispersion_positions_for_term(idx, term, docset_mask=_maske),
        dtype=np.uint32,
    )
    try:
        token_count = int(idx.token_count())
    except Exception:
        token_count = int(offsets.max()) + 1 if offsets.size else 0
    doc_bounds = None
    try:
        boundaries = idx.fast_index.boundaries
        if boundaries and boundaries.document and boundaries.document._positions.size:
            doc_bounds = np.asarray(boundaries.document._positions, dtype=np.int64)
    except Exception:
        doc_bounds = None
    profile = {
        "term": str(term),
        "offsets": offsets.astype(int).tolist(),
        **_summarize_dispersion_offsets(
            offsets,
            token_count=token_count,
            doc_bounds=doc_bounds,
            doc_mask=_maske,
            partitions=partitions,
        ),
    }
    # Die drei Zusatzfelder aus summarize_dispersion_offsets bleiben der
    # REST-Naht und programmatischen Aufrufern vorbehalten. Der
    # Systemprompt hat ein HARTES Budget von 31.000 Zeichen und steht bei
    # 30.999, und der Werkzeug-Doku-Waechter verlangt, dass jedes
    # ausgelieferte Feld dort dokumentiert ist -- sonst erfindet das Modell
    # Feldnamen. Der Befund, den sie begleiten, ist ohne sie geschlossen:
    # die gemeinsamen DP-Schnittpunkte machen `profile` und die
    # REST-`classification` richtungsgleich (0 von 100 der haeufigsten
    # Woerter weichen noch ab, vorher 100 von 100), und `peak_partition`
    # ist jetzt IMMER eine globale Dokument-ID.
    for _nur_rest in ("classification", "peak_dominated", "peak_partition_local"):
        profile.pop(_nur_rest, None)
    return {"status": "success", **profile}


TREND_ANALYSIS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "trend_analysis",
        "description": (
            "Frequenzverlauf (Diachronie) einer Abfrage über ein Metadaten-"
            "Datumsfeld: pro Periode Treffer, Tokengröße, per_million-Rate und "
            "Wilson-95%-Konfidenzintervall. Nutze DIES für 'Trend'/'Verlauf'/"
            "'über die Zeit'/'pro Jahr'-Fragen. date_field muss ein existierendes "
            "Metadatenfeld mit Datumswerten sein (mit metadata_values prüfen); "
            "Perioden ohne Dokumente werden AUSGELASSEN (nie als 0 gefaked), "
            "Dokumente ohne parsbares Datum landen im Bucket 'undatiert'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff (Klartext oder mit Prefix cql:). Alternativ cql angeben.",
                },
                "cql": {
                    "type": "string",
                    "description": "CQL-Abfrage (wird automatisch mit cql: geprefixt). Alternativ query angeben.",
                },
                "date_field": {
                    "type": "string",
                    "description": "Metadatenfeld mit Datumswerten (z.B. 'date', 'year').",
                },
                "granularity": {
                    "type": "string",
                    "description": "Periodengranularität: 'year' (Default) oder 'month'.",
                    "default": "year",
                },
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID ODER Subkorpus-Name (optional).",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["date_field"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "cql": {"type": "string"},
            "date_field": {"type": "string"},
            "granularity": {"type": "string"},
            "docset_id": {"type": "string"},
            "corpus": {"type": "string"},
        },
        "required": ["date_field"],
    },
}


TREND_ANALYSIS_RESPONSE = _obj(
    {
        "status": _str(),
        "query": _str(),
        "date_field": _str(),
        "granularity": _str(),
        "periods": {
            "type": "array",
            "items": _row_schema(
                {
                    "period": _str(),
                    "documents": _int(),
                    "hits": _int(),
                    "tokens": _int(),
                    "tokens_raw": _int(),
                    "per_million": _num(),
                    "ci_low": _num(),
                    "ci_high": _num(),
                }
            ),
        },
        "periods_total": _int(),
        "truncated": _bool(),
        "warnings": {"type": "array", "items": _str()},
        # REST-identical provenance block (build_method_block family 'trend':
        # rate_definition, ci_method wilson_score, ci_level/ci_z/ci_formula,
        # empty_period_policy, undated_policy, index_fingerprint, ...).
        "method": {"type": "object", "additionalProperties": True},
    },
    required=[
        "status",
        "query",
        "date_field",
        "granularity",
        "periods",
        "periods_total",
        "truncated",
        "warnings",
        "method",
    ],
)


# Kontextdeckel fuer Trendperioden. Die REST-Route liefert bis
# _TREND_MAX_PERIODS (500), die Copilot-Antwort wird gedeckelt und
# gekennzeichnet, damit ein breiter Monatstrend den Kontext nicht flutet.
_TREND_TOOL_MAX_PERIODS = 60


def _cap_trend_periods(
    periods: list[Dict[str, Any]], cap: int = _TREND_TOOL_MAX_PERIODS
) -> tuple[list[Dict[str, Any]], bool]:
    """Thin periods across the full time range for the model context.

    Preserve both endpoints and keep the undated bucket outside thinning.
    Return ``(periods, shortened)``. The caller exposes ``periods_total``
    so the displayed subset cannot be mistaken for the complete series.
    """
    from candyconc.analysis_defaults import perioden_ausduennen

    total = len(periods)
    if total <= int(cap):
        return list(periods), False
    return perioden_ausduennen(periods, int(cap)), True


@llm_tool(TREND_ANALYSIS_TOOL, TREND_ANALYSIS_RESPONSE, read_only=True)
def trend_analysis_tool(
    date_field: str,
    query: str | None = None,
    cql: str | None = None,
    granularity: str = "year",
    docset_id: str | None = None,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """Diachronic frequency trend over a metadata date field (REST /analysis/trend parity).

    In-process sibling of POST /api/v1/analysis/trend (the dispersion_offsets
    pattern: no HTTP loopback, the SAME server/route seams are imported so the
    numbers cannot drift):

    - period bucketing via ``routes.analysis._trend_period_for_value`` (year =
      leading YYYY, month = leading YYYY-MM; unparsable -> 'undatiert' bucket),
    - per-period hit counts via ``server._compute_query_count`` (the exact-count
      primitive REST /query/count uses) over a per-period docset mask,
    - per-period token totals via ``idx.docset_token_count``,
    - Wilson 95% CI via ``routes.analysis._trend_wilson_interval``,
    - the identical ``build_method_block('trend', ...)`` provenance block.

    Validation mirrors the route's 422s verbatim (query/cql fehlt, date_field
    fehlt, granularity, unknown date_field, too many periods) as
    ``ToolInputError`` -> honest 400/error envelope. The period list is capped
    at ``_TREND_TOOL_MAX_PERIODS`` (60) for the LLM context with
    ``truncated``/``periods_total`` keeping the completeness honest.
    """
    from candyconc.analysis_defaults import build_method_block
    from candyconc.services.backend import server as _server
    from candyconc.services.backend.routes.analysis import (
        _TREND_CI_Z,
        _TREND_MAX_PERIODS,
        _index_fingerprint,
        _trend_period_for_value,
        _trend_wilson_interval,
    )
    from candyconc.core.fast_index_native import docset_mask_from_ids

    # Query normalisation — verbatim route logic (query wins; cql is prefixed).
    raw_query: Any = query
    raw_cql: Any = cql
    if raw_query is not None and not str(raw_query).strip() and raw_cql is None:
        raw_query = None
    if raw_query is None and raw_cql is not None:
        cql_text = str(raw_cql).strip()
        raw_query = cql_text if cql_text.lower().startswith("cql:") else f"cql:{cql_text}"
    query_str = str(raw_query or "").strip()
    if not query_str:
        raise ToolInputError("query oder cql fehlt")

    date_field_str = str(date_field or "").strip()
    if not date_field_str:
        raise ToolInputError("date_field fehlt")
    granularity_key = str(granularity or "year").strip().lower()
    if granularity_key not in {"year", "month"}:
        raise ToolInputError("granularity muss 'year' oder 'month' sein")

    resolved_docset = _coerce_docset_id(docset_id, corpus) if docset_id else None
    idx, doc_ids = _resolve_docset_doc_ids(corpus, resolved_docset)
    allowed_ids: set | None = None
    if doc_ids is not None:
        allowed_ids = {int(i) for i in np.asarray(doc_ids, dtype=np.int64).tolist()}
    # Apply where() restrictions to each period's population as well as
    # its hits so the rate uses the same scope for numerator and denominator.
    _wo = _where_dokumente(idx, query_str)
    if _wo is not None:
        _wo_ids = {int(i) for i in np.asarray(_wo, dtype=np.int64).tolist()}
        allowed_ids = _wo_ids if allowed_ids is None else (allowed_ids & _wo_ids)

    doc_count = _get_doc_count(idx)
    doc_meta = getattr(idx.fast_index, "doc_metadata", None) or {}

    groups: dict[str, list[int]] = {}
    undated: list[int] = []
    field_seen = False
    for doc_idx in range(int(doc_count)):
        if allowed_ids is not None and doc_idx not in allowed_ids:
            continue
        meta = doc_meta.get(doc_idx, {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        if date_field_str in meta:
            field_seen = True
        period = _trend_period_for_value(meta.get(date_field_str), granularity_key)
        if period is None:
            undated.append(doc_idx)
        else:
            groups.setdefault(period, []).append(doc_idx)

    # Check field existence across the corpus before inspecting a selection.
    # An empty selection cannot establish that a metadata field is absent.
    if not field_seen:
        im_korpus = any(
            isinstance(m, dict) and date_field_str in m
            for m in (doc_meta or {}).values()
        )
        if im_korpus:
            raise ToolInputError(
                "Die gewaehlte Dokumentmenge ist leer, deshalb gibt es keine "
                f"Periode fuer date_field '{date_field_str}'. Das Feld "
                "existiert im Korpus."
            )
        raise ToolInputError(
            f"date_field '{date_field_str}' existiert nicht in den "
            "Dokument-Metadaten dieses Korpus (siehe /analysis/meta_schema)."
        )
    if len(groups) > _TREND_MAX_PERIODS:
        raise ToolInputError(
            f"Zu viele Perioden ({len(groups)} > {_TREND_MAX_PERIODS}); "
            "granularity='year' verwenden oder per docset_id einschränken."
        )

    doc_bounds = _server._doc_bounds_for_index(idx)
    n_docs = int(doc_bounds.size)
    warnings: list[str] = []
    partial_periods: list[str] = []

    def _period_row(period_label: str, doc_idx_list: list[int]) -> Dict[str, Any]:
        ids = np.asarray(sorted(doc_idx_list), dtype=np.uint32)
        mask = docset_mask_from_ids(ids, n_docs)
        hits, _elapsed_ms, count_partial = _server._compute_query_count(
            idx, query_str, 5, None, None, mask, case_insensitive=True
        )
        if count_partial:
            partial_periods.append(period_label)
        # Use period analysis tokens and retain the raw count alongside them.
        bezug = _wortnenner(idx, ids)
        tokens = int(bezug["woerter"])
        hits = int(hits)
        per_million = (float(hits) / float(tokens) * 1_000_000.0) if tokens > 0 else 0.0
        low, high = _trend_wilson_interval(hits, tokens)
        return {
            "period": period_label,
            "documents": int(ids.size),
            "hits": hits,
            "tokens": tokens,
            "tokens_raw": int(bezug["roh"]),
            "per_million": per_million,
            "ci_low": low * 1_000_000.0,
            "ci_high": high * 1_000_000.0,
        }

    rows = [_period_row(period, groups[period]) for period in sorted(groups)]
    if undated:
        rows.append(_period_row("undatiert", undated))
        warnings.append(lt(
            "{count} Dokument(e) ohne parsbaren Datumswert im Feld "
            "'{date_field}' wurden dem Bucket 'undatiert' zugeordnet.",
            "{count} document(s) without a parsable date value in field "
            "'{date_field}' were assigned to the bucket 'undatiert'.",
        ).format(count=len(undated), date_field=date_field_str))
    if partial_periods:
        warnings.append(lt(
            "Trefferzählung unvollständig (Zähl-Limit erreicht) für Perioden: {periods}",
            "Hit count incomplete (count limit reached) for periods: {periods}",
        ).format(periods=", ".join(partial_periods)))

    periods_total = len(rows)
    capped_rows, truncated = _cap_trend_periods(rows)
    if truncated:
        from candyconc.analysis_defaults import trend_kuerzungshinweis

        warnings.append(trend_kuerzungshinweis(capped_rows, periods_total))

    method = build_method_block(
        "trend",
        index_fingerprint=_index_fingerprint(idx),
        extra={
            "date_field": date_field_str,
            "granularity": granularity_key,
            "rate_definition": lt(
                "per_million = hits / tokens * 10^6 je Periode",
                "per_million = hits / tokens * 10^6 per period",
            ),
            "ci_method": "wilson_score",
            "ci_level": 0.95,
            "ci_z": _TREND_CI_Z,
            "ci_formula": lt(
                "Wilson-Score-Intervall auf der Token-Rate p = hits/tokens: "
                "(p + z²/2n ± z·√(p(1−p)/n + z²/4n²)) / (1 + z²/n), "
                "mit n = tokens und z = 1.96 (95%); Grenzen mit 10^6 skaliert.",
                "Wilson score interval on the token rate p = hits/tokens: "
                "(p + z²/2n ± z·√(p(1−p)/n + z²/4n²)) / (1 + z²/n), "
                "with n = tokens and z = 1.96 (95%). Bounds scaled by 10^6.",
            ),
            "empty_period_policy": lt(
                "Perioden ohne Dokumente werden ausgelassen, nicht als 0 ausgegeben.",
                "Periods without documents are left out, not reported as 0.",
            ),
            "undated_policy": lt(
                "Unparsbare Datumswerte bilden den Bucket 'undatiert'.",
                "Unparseable date values form the bucket 'undatiert'.",
            ),
        },
    )
    return {
        "status": "success",
        "query": query_str,
        "date_field": date_field_str,
        "granularity": granularity_key,
        "periods": capped_rows,
        "periods_total": periods_total,
        "truncated": bool(truncated),
        "warnings": warnings,
        "method": method,
    }


from candyconc.candyconc_copilot.keyness_tool_def import KEYNESS_RESPONSE, KEYNESS_TOOL


def _validierter_keyness_sortierschluessel(sort_by: Any) -> str:
    """Nur die Uebersetzung nach ToolInputError (MCP-Grenze -> HTTP 400),
    Fachlogik in services/tools/keyness.validate_sort_key."""
    from candyconc.services.tools.keyness import validate_sort_key
    try:
        return validate_sort_key(sort_by)
    except ValueError as exc:
        raise ToolInputError(str(exc)) from exc


@llm_tool(KEYNESS_TOOL, KEYNESS_RESPONSE)
def keyness_tool(
    target: Optional[List[str]] = None,
    reference: Optional[List[str]] = None,
    *,
    target_corpus: str | None = None,
    reference_corpus: str | None = None,
    target_docset_id: str | None = None,
    reference_docset_id: str | None = None,
    corpus: str | None = None,
    pos_map: Optional[Dict[str, str]] = None,
    pos: Optional[str] = None,
    min_freq: int = _DEFAULT_MIN_FREQ,
    sort_by: str = "ll_signed",
    target_context_query: str | None = None,
    context_window: int = 5,
    attribute: str = "word",
    limit: int | None = None,
) -> Dict[str, Any]:
    """Wrapper for :func:`keyness` returning JSON rows.

    ``min_freq`` defaults to the research-grade reliability floor
    (:data:`DEFAULT_MIN_FREQ` = 5), matching the REST keyness route. The floor
    is applied BEFORE the inferential statistics so the BH-FDR q-values are not
    inflated by thousands of untestable singletons — without it the copilot's
    q-values would silently disagree with /analysis/keyness (C-keyness-references-04).

    A whole-corpus comparison (``target_corpus`` vs ``reference_corpus``) mirrors
    the supported REST corpus-vs-corpus path (frequency_list + token_count +
    ``_compute_keyness_counts``) so the copilot and ``/analysis/keyness`` agree.
    It deliberately does NOT route through the docset/project store, which would
    otherwise raise a misleading "Legacy Projektdatei" 500 for a plain corpus
    name (B1).
    """
    if isinstance(pos, str):
        pos = pos.strip() or None
    sortierschluessel = _validierter_keyness_sortierschluessel(sort_by)
    attribut = _keyness_zaehlebene(attribute)
    # P2.7: Vergleichsgrundlage. Ohne sie ist die vom Rezept
    # verlangte Nennung der Teilkorpusgroessen aus dem
    # Keyness-Output heraus UNMOEGLICH.
    # reference_kind ist eine Zeichenkette, die uebrigen Werte sind Zahlen.
    groessen: Dict[str, Any] = {}
    seiten: tuple | None = None  # nur der Docset-Zweig zaehlt und faltet
    if target_context_query:
        # P2.5: der KONTEXT eines Knotens gegen den REST des Korpus. Eine
        # andere Analyse als Docset gegen Docset (Ziel ist eine
        # Positionsmenge) und als collocate_stats (dort gilt der
        # Paar-Ereignisraum). Fachlogik in services/tools/context_keyness.
        from candyconc.services.tools.context_keyness import (
            build_context_keyness_frames,
        )

        if target_docset_id or reference_docset_id or target or reference:
            raise ToolInputError(
                "target_context_query schließt Docsets und Wortlisten aus: "
                "das Ziel ist hier das Kontextfenster, nicht eine "
                "Dokumentmenge."
            )
        idx = _resolve_corpus_index(corpus) if corpus else _get_index()
        try:
            freq_t, freq_r, total_t, total_r, groessen = (
                build_context_keyness_frames(
                    idx.fast_index,
                    str(target_context_query),
                    window=int(context_window),
                    attribute=attribut,
                    ist_analysetoken=_is_analyst_token,
                )
            )
        except ValueError as exc:
            raise ToolInputError(str(exc)) from exc
        df = _compute_keyness_counts(
            freq_t, freq_r, int(total_t), int(total_r),
            min_freq=int(min_freq), sort_by=sortierschluessel,
        )
    elif target_corpus or reference_corpus:
        if not target_corpus or not reference_corpus:
            raise ToolInputError(
                "target_corpus und reference_corpus müssen gemeinsam angegeben werden."
            )
        if pos:
            raise ToolInputError(
                "POS-gefilterte Keyness ist für Korpus-vs-Korpus nicht belegt. "
                "Bitte Docsets verwenden oder den POS-Filter entfernen."
            )
        c_target = _resolve_corpus_index(target_corpus)
        c_ref = _resolve_corpus_index(reference_corpus)
        if attribut != "word":
            # Nur die bestellte Abweichung wird geprueft, fuer Wortformen
            # meldet frequency_list einen kaputten Index selbst.
            _keyness_lexikon(c_target, attribut)
            _keyness_lexikon(c_ref, attribut)
        df_t = _keyness_frequenzliste(c_target, attr=attribut)
        df_r = _keyness_frequenzliste(c_ref, attr=attribut)
        rows_t = df_t.to_dicts() if hasattr(df_t, "to_dicts") else df_t.to_dict("records")
        rows_r = df_r.to_dicts() if hasattr(df_r, "to_dicts") else df_r.to_dict("records")
        # REST parity (routes/analysis.py:4392-4393 _filter_keyness_freq_map):
        # drop |LBR|/emoji/punctuation pseudo-tokens before scoring so they
        # cannot surface as keyness candidates (COPILOT-KEYNESS-NONANALYST-LEAK).
        freq_t = {str(r["word"]): int(r["f"]) for r in rows_t if _is_analyst_token(r["word"])}
        freq_r = {str(r["word"]): int(r["f"]) for r in rows_r if _is_analyst_token(r["word"])}
        # FUENFTE NAHT derselben Fehlerklasse, gefunden von einer
        # adversarialen Pruefung: der Zaehler zwei Zeilen darueber ist
        # gefiltert, der Nenner war die volle Korpusgroesse.
        total_t_roh = int(c_target.token_count())
        total_r_roh = int(c_ref.token_count())
        total_t = analysierbare_groesse(freq_t)
        total_r = analysierbare_groesse(freq_r)
        groessen = {
            "target_tokens": total_t, "reference_tokens": total_r,
            "target_tokens_roh": total_t_roh,
            "reference_tokens_roh": total_r_roh,
            "attribute": attribut,
        }
        if pos:
            groessen["pos"] = str(pos)
        for schluessel, quelle in (
            ("target_docs", c_target), ("reference_docs", c_ref),
        ):
            anzahl = int(_get_doc_count(quelle))
            if anzahl > 0:
                groessen[schluessel] = anzahl
        df = _compute_keyness_counts(
            freq_t, freq_r, total_t, total_r,
            min_freq=int(min_freq), sort_by=sortierschluessel,
        )
    elif target_docset_id or reference_docset_id:
        if not target_docset_id:
            # DER AUSWEG GEHOERT IN DIE MELDUNG. Am 2026-09-02 traf genau
            # diese Grenze eine Frage mit sieben Kandidatenformen: das
            # Modell hatte sie als ``target`` uebergeben, die Meldung nannte
            # nur den fehlenden Parameter, und der Turn wich auf eine
            # globale Keyness ueber 389.305 Zeilen aus, in deren sichtbarer
            # Spitze keiner der sieben stand.
            raise ToolInputError(
                "reference_docset_id ohne target_docset_id ergibt keinen "
                "Kontrast. Gib target_docset_id an. Für eine "
                "Kandidatenliste gegen ein Teilkorpus ist keyness die "
                "falsche Form: target ist ein Tokenstrom, der gezählt "
                "wird. Zähle je Kandidat mit query_count(query=Kandidat, "
                "docset_id=...) auf beiden Seiten und normiere auf die "
                "Tokenzahl der jeweiligen Seite."
            )
        # Both ids accept EITHER a live docset_id OR a persisted subcorpus name.
        target_docset_id = _coerce_docset_id(target_docset_id, corpus)
        idx, target_ids = _resolve_docset_doc_ids(corpus, target_docset_id)
        if reference_docset_id:
            reference_docset_id = _coerce_docset_id(reference_docset_id, corpus)
            _, reference_ids = _resolve_docset_doc_ids(corpus, reference_docset_id)
            referenzart = "docset"
        else:
            # Das Gegenstueck zu reference_source="whole" der REST-Route.
            # Referenz ist der REST des Korpus, nicht das ganze Korpus: sonst
            # steckte das Ziel in seiner eigenen Referenz.
            from candyconc.services.backend import server as _srv
            from candyconc.services.tools.keyness import complement_docset_ids

            try:
                reference_ids = complement_docset_ids(
                    target_ids if target_ids is not None else np.zeros(0, dtype=np.uint32),
                    doc_count=int(_srv._doc_count_for_index(idx)),
                )
            except ValueError as exc:
                raise ToolInputError(str(exc)) from exc
            if reference_ids.size == 0:
                raise ToolInputError(
                    "Das Docset umfasst das ganze Korpus, außerhalb liegt kein "
                    "Dokument. Ein Kontrast gegen den Rest ist dann leer."
                )
            referenzart = "rest_des_korpus"
        if target_ids is None or reference_ids is None:
            raise RuntimeError("Docset-IDs konnten nicht geladen werden.")
        try:
            target_ids, reference_ids = normalize_disjoint_docsets(
                target_ids, reference_ids
            )
        except ValueError as exc:
            raise ToolInputError(str(exc)) from exc
        lex = _keyness_lexikon(idx, attribut)

        def _woerter(ids):
            return strings_for_ids(lex.offsets, lex.strings_view,
                                   np.asarray(ids).astype(np.uint32, copy=False), True)

        # Die Zaehlung bleibt HIER. Ein Auslagern in ein Helfermodul greift an
        # den Ersetzungen der Werkzeugtests vorbei, die _frequency_counts_docset_folded
        # und strings_for_ids an DIESEM Modul austauschen, und liesse sechs
        # Tests fallen, die den Nennervertrag mit einem schmalen Doppel pruefen.
        varianten_t: Dict[int, Dict[int, int]] = {}
        varianten_r: Dict[int, Dict[int, int]] = {}
        t_ids, t_counts = _frequency_counts_docset_folded(
            idx, target_ids, pos=pos, attr=attribut, variants_out=varianten_t)
        r_ids, r_counts = _frequency_counts_docset_folded(
            idx, reference_ids, pos=pos, attr=attribut, variants_out=varianten_r)
        t_words, r_words = _woerter(t_ids), _woerter(r_ids)
        # REST-Paritaet (routes/analysis._filter_keyness_freq_map): |LBR|, Emoji
        # und Satzzeichen fallen VOR der Bewertung heraus.
        freq_t = {w: int(c) for w, c in zip(t_words, t_counts) if _is_analyst_token(w)}
        freq_r = {w: int(c) for w, c in zip(r_words, r_counts) if _is_analyst_token(w)}
        seiten = ((t_ids, t_words, varianten_t), (r_ids, r_words, varianten_r))
        # Count the denominator from the same filtered population as the numerator.
        # Unequal punctuation shares can otherwise distort the contrast between groups.
        # Keep raw subcorpus sizes alongside the analysis-token counts.
        total_t = analysierbare_groesse(freq_t)
        total_r = analysierbare_groesse(freq_r)
        roh_t = int(
            np.asarray(t_counts, dtype=np.uint64).sum(dtype=np.uint64)
            if pos else idx.docset_token_count(target_ids)
        )
        roh_r = int(
            np.asarray(r_counts, dtype=np.uint64).sum(dtype=np.uint64)
            if pos else idx.docset_token_count(reference_ids)
        )
        # P2.7 (Endabnahme): genannt wird die Groesse, auf der die Statistik
        # RECHNET. Bei gesetztem POS-Filter ist das die Summe der gefilterten
        # Counts, nicht die Teilkorpusgroesse. Vorher stand hier unbedingt
        # docset_token_count, und der Renderer stempelte diese UNGEFILTERTE
        # Zahl mit '(nur POS ...)'. Das ist schlechter als gar keine Zahl,
        # weil der Leser die Fehlinformation nicht erkennen kann: gerechnet
        # wurde auf 9 Tokens, gedruckt standen 10.000 als POS-Grundlage.
        # Nebeneffekt: die Teilkorpusgroesse wird nicht mehr doppelt gezaehlt.
        groessen = {
            "target_docs": int(len(target_ids)),
            "target_tokens": int(total_t),
            "target_tokens_roh": roh_t,
            "reference_docs": int(len(reference_ids)),
            "reference_tokens": int(total_r),
            "reference_tokens_roh": roh_r,
        }
        # Woher die Referenz kommt, gehoert in die Antwort: "1317 Dokumente"
        # sieht gleich aus, ob sie ein zweites Docset sind oder der Rest des
        # Korpus, und die Deutung unterscheidet sich.
        groessen["reference_kind"] = referenzart
        groessen["attribute"] = attribut
        # Eine Zeile steht fuer alle Gross- und Kleinschreibungen ihres Worts.
        if str(attribut).strip().lower() in {"word", "lemma"}:
            groessen["case_policy"] = CASE_POLICY_GEFALTET
        if pos:
            groessen["pos"] = str(pos)
        df = _compute_keyness_counts(
            freq_t, freq_r, int(total_t), int(total_r),
            min_freq=int(min_freq), sort_by=sortierschluessel,
        )
    else:
        if not target or not reference:
            raise ToolInputError("target und reference müssen angegeben werden, wenn keine Docsets genutzt werden.")
        if attribut != "word":
            raise ToolInputError(
                "attribute gilt nicht für target/reference: diese Listen "
                "kommen vom Aufrufer, das Korpus wird dafür nicht gezählt."
            )
        # REST parity (routes/analysis.py:4445-4453): drop non-analyst tokens
        # (|LBR|/emoji/punctuation) BEFORE scoring and apply the same min_freq
        # reliability floor so the BH-FDR q-values are not inflated by
        # untestable singletons (COPILOT-KEYNESS-MINFREQ-DROP / -NONANALYST-LEAK).
        target = [t for t in target if _is_analyst_token(t)]
        reference = [r for r in reference if _is_analyst_token(r)]
        try:
            df = _compute_keyness(
                target, reference, pos_map=pos_map, pos=pos,
                min_freq=int(min_freq), sort_by=sortierschluessel,
            )
        except ValueError as exc:
            # Dieselbe Grenze wie in der REST-Route: eine Eingabefrage
            # gehoert als ToolInputError gemeldet, nicht als roher
            # ValueError, der den Turn abbricht.
            raise ToolInputError(str(exc)) from exc
    if hasattr(df, "to_dicts"):
        rows = df.to_dicts()  # Polars
    elif hasattr(df, "to_dict"):
        rows = df.to_dict("records")  # Pandas
    else:
        rows = []
    if seiten is not None:
        _schreibungen_anhaengen(rows, _woerter, *seiten)
    # DAS MODELL DARF DIE GROESSE WAEHLEN (2026-09-17, gelesen am Turn:
    # 389.305 Zeilen gerechnet, 20 gezeigt, Frage war Streuung -- das Modell
    # zerschnitt das Korpus, weil es keine ZEILEN fordern durfte).
    gesamt = len(rows)
    if limit is not None:
        rows = rows[:_ganzzahl_mindestens_eins(limit)]
    ergebnis: Dict[str, Any] = {"status": "success", "rows": rows,
                                "rows_total": gesamt, "rows_returned": len(rows),
                                "sortiert_nach": sortierschluessel}
    if groessen:
        ergebnis["diagnostics"] = groessen
    return ergebnis


# ---------------------------------------------------------------------------
# Semantic search


SEMANTIC_SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "semantic_search",
        "description": (
            "Retrieve passages/documents by embedding similarity via FAISS. "
            "This is not exact term, frequency, co-occurrence, or collocation "
            "evidence; use run_cqlf_query/query_count or collocate_stats for those."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Search term"},
                "top_n": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10,
                },
                "level": {
                    "type": "string",
                    "enum": ["doc", "sentence"],
                    "default": "doc",
                },
                "min_score": {"type": "number", "default": 0.0},
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "top_n": {"type": "integer"},
            "level": {"type": "string"},
            "min_score": {"type": "number"},
        },
        "required": ["term"],
    },
}


# Semantic-search rows are backend-dependent (FAISS vs spaCy fallback) and could
# not be probed on the bench index (no semantic assets), so the row object stays
# permissive (additionalProperties:true) rather than risk a false-negative.
SEMANTIC_SEARCH_RESPONSE = _obj(
    {
        "status": _str(),
        "rows": {
            "type": "array",
            "items": _obj(
                {
                    "kw": _str(),
                    "left": _str(),
                    "right": _str(),
                    "score": _num(),
                    "file": _str(),
                    "pos": _int(),
                    "doc_id": _str(),
                    "meta": _obj({}, additional=True),
                },
                additional=True,
            ),
        },
        "level": _str(),
        "meta": _obj({}, additional=True),
        "fallback": _obj({}, additional=True),
    },
    required=["status", "rows"],
)


@llm_tool(SEMANTIC_SEARCH_TOOL, SEMANTIC_SEARCH_RESPONSE)
def semantic_search_tool(
    term: str,
    top_n: int = 10,
    *,
    level: str = "doc",
    min_score: float = 0.0,
) -> Dict[str, Any]:
    """Wrapper for :func:`semantic_search` returning JSON rows."""
    from candyconc.services.backend.kwic_renderer import normalise_kwic_row_display

    requested_level = (level or "doc").strip().lower()
    try:
        raw = _semantic_search(
            term,
            level=requested_level,
            top_n=top_n,
            min_score=min_score,
            return_meta=True,
        )
        rows, meta = _coerce_semantic_search_result(raw)
        # Strip the index-only |LBR| sentinel from passage text so it never leaks
        # into the LLM/renderer evidence (parity with the run_cqlf_query path).
        rows = [
            _sanitise_semantic_search_row(normalise_kwic_row_display(row))
            for row in rows
        ]
        result: Dict[str, Any] = {"status": "success", "rows": rows, "level": requested_level}
        if meta is not None:
            result["meta"] = meta
        return result
    except Exception as exc:
        if requested_level != "sentence":
            raise
        raw = _semantic_search(term, level="doc", top_n=top_n, min_score=min_score, return_meta=True)
        rows, meta = _coerce_semantic_search_result(raw)
        rows = [
            _sanitise_semantic_search_row(normalise_kwic_row_display(row))
            for row in rows
        ]
        result = {
            "status": "success",
            "rows": rows,
            "level": "doc",
            "fallback": {
                "requested_level": "sentence",
                "used_level": "doc",
                "reason": str(exc),
            },
        }
        if meta is not None:
            result["meta"] = meta
        return result


# ---------------------------------------------------------------------------
# Distributional thesaurus (F8): corpus-restricted similar words with scores.


SIMILAR_WORDS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "similar_words",
        "description": (
            "Distributioneller Thesaurus: korpus-restringierte ähnliche Wörter "
            "für einen Begriff, mit Kosinus-Score und Korpusfrequenz. Nur Wörter, "
            "die im indexierten Korpus vorkommen, werden zurückgegeben."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Ausgangswort"},
                "k": {
                    "type": "integer",
                    "description": "Anzahl Nachbarn",
                    "default": 20,
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "k": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": ["term"],
    },
}


SIMILAR_WORDS_RESPONSE = _obj(
    {
        "status": _str(),
        "term": _str(),
        "neighbours": {
            "type": "array",
            "items": _row_schema(
                {
                    "word": _str(),
                    "score": _num(),
                    "corpus_frequency": _int(),
                }
            ),
        },
        # Present only on the graceful-degradation path (status="unavailable")
        # so the copilot can explain why the thesaurus produced no neighbours
        # instead of seeing a tool crash.
        "code": _str(),
        "reason": _str(),
        "backend": _str(),
    },
    required=["status", "term", "neighbours"],
)


def word_similarity_available(index_path: Any) -> bool:
    """Reine Dateipräsenz-Prüfung der Wort-Thesaurus-Capability (V9/H9).

    ``semantic.word_similarity`` ist genau dann real vorhanden, wenn BEIDE
    Artefakte auf der Platte liegen: ``faiss_word.index`` UND ``word_ids.npy``
    (dieselbe Wahrheit wie ``domain.corpus._corpus_feature_descriptor``).
    Geprüft wird die Dateipräsenz, NICHT ein Manifest-Flag. Fail closed:
    unlesbarer/leerer Pfad => False.

    Kontrakt für das präemptive Capability-Gate (recipe_runtime, Paket C2):
    Tool-Name ``similar_words`` gehört aus dem Tool-Space, wenn
    ``not word_similarity_available(index_path)``.
    """
    if index_path in (None, ""):
        return False
    try:
        base = Path(index_path)
        return (base / "faiss_word.index").exists() and (
            base / "word_ids.npy"
        ).exists()
    except (TypeError, ValueError, OSError):
        return False


@llm_tool(SIMILAR_WORDS_TOOL, SIMILAR_WORDS_RESPONSE)
def similar_words_tool(term: str, k: int = 20, corpus: str | None = None) -> Dict[str, Any]:
    """Corpus-restricted distributional thesaurus neighbours with scores.

    Promotes the similarity engine that previously only fed sim() query
    expansion. Returns the (word, cosine score) neighbours present in the indexed
    corpus, joined with their corpus frequency. The seed term is excluded; an
    empty ``neighbours`` list means nothing cleared the engine threshold.

    Degradation contract (mirrors the REST route's 503): when the embedding
    backend / word lexicon is unavailable for this corpus the tool does NOT
    raise. It returns ``{"status": "unavailable", "code": ..., "reason": ...,
    "backend": ..., "term": ..., "neighbours": []}`` so the copilot can degrade
    gracefully instead of surfacing a 500/tool-crash to the user.
    """
    from candyconc.core import cql_macros as _cql_macros
    from candyconc.services.backend.query_count import _word_vectors_error
    from candyconc.services.backend.routes.semantic import (
        WORD_SIMILARITY_UNAVAILABLE_MESSAGE as _WORD_SIMILARITY_UNAVAILABLE_MESSAGE,
        _word_similarity_available as _word_similarity_available,
        _word_similarity_backend as _word_similarity_backend,
        _word_similarity_error as _word_similarity_error,
    )

    clean = (term or "").strip()
    if not clean:
        raise RuntimeError("term darf nicht leer sein")
    # FT-COPILOT-CORPUS-RESOLVE: resolve the corpus per call, not the global.
    idx = _resolve_corpus_index(corpus)
    backend = _word_similarity_backend(idx)
    # SEM-01/V9 sibling-surface parity: the Wort-Thesaurus availability is ONE
    # decision the UI, REST (routes/semantic.py) and copilot must all reflect —
    # the SAME predicate AND the SAME human message (a former belt-and-braces
    # file check here duplicated the decision with a drifted text; the shared
    # predicate already fails CLOSED and its feature descriptor checks the very
    # same on-disk files, so the file truth stays the last word). On a
    # word_similarity:false corpus the engine still produces spaCy-fallback
    # neighbours, but those are NOT a corpus thesaurus result — so we gate them
    # the SAME way REST does and return the identical "unavailable" contract
    # instead of advertising a capability the corpus does not have. (No change
    # for a word_similarity:true corpus.)
    if not _word_similarity_available(idx):
        return {
            "status": "unavailable",
            # The code of the REST answer: word_vectors.unavailable (the
            # corpus has none) or word_vectors.service_error (not loadable).
            "code": _word_similarity_error(idx).code,
            "reason": _WORD_SIMILARITY_UNAVAILABLE_MESSAGE,
            "backend": backend,
            "term": clean,
            "neighbours": [],
        }
    try:
        bounded_k = int(k)
    except (TypeError, ValueError):
        bounded_k = 20
    bounded_k = max(1, bounded_k)
    try:
        scored = _cql_macros.similar_words_scored(clean, bounded_k, idx)
    except RuntimeError as exc:
        lowered = str(exc).lower()
        # Per-term misses (index/backend fine, this seed yielded nothing) are an
        # honest empty 200 — NOT an outage. Mirror routes/semantic.py's classifier:
        # "oberhalb score" = nothing cleared the threshold; "keine embeddings für
        # sim()" = out-of-vocabulary seed (nlp(term).vector all-zero).
        if "oberhalb score" in lowered or "keine embeddings für sim()" in lowered:
            return {"status": "success", "term": clean, "neighbours": []}
        # Embedding backend / word lexicon / vectors unavailable for this corpus.
        # Degrade gracefully with the code of the route's answer instead of raising.
        mapped = _word_vectors_error(exc)
        return {
            "status": "unavailable",
            "code": mapped.code if mapped is not None else "word_vectors.service_error",
            "reason": str(exc),
            "backend": backend,
            "term": clean,
            "neighbours": [],
        }
    freq: Dict[str, int] = {}
    try:
        df = idx.frequency_list()
        for row in df.to_dicts():
            word = row.get("word")
            if word is not None:
                freq[str(word)] = int(row.get("f", 0) or 0)
    except Exception:
        freq = {}
    neighbours: List[Dict[str, Any]] = []
    for entry in scored:
        word = str(entry.get("word", ""))
        if not word or word == clean:
            continue
        raw_score = entry.get("score")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(score):
            continue
        corpus_frequency = int(freq.get(word, 0))
        if corpus_frequency < 1:
            # Corpus-restricted contract (mirror routes/semantic.py): a neighbour
            # the embedding backend knows but that is absent from THIS corpus is
            # not a corpus neighbour. Drop it so copilot == REST.
            continue
        neighbours.append(
            {
                "word": word,
                "score": score,
                "corpus_frequency": corpus_frequency,
            }
        )
    neighbours.sort(key=lambda n: n["score"], reverse=True)
    return {"status": "success", "term": clean, "neighbours": neighbours}


SEMANTIC_CLUSTER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "semantic_cluster",
        "description": "Cluster semantic search hits.",
        "parameters": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "integer"}},
                "top_n": {"type": "integer", "default": 6},
            },
            "required": ["ids"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "ids": {"type": "array", "items": {"type": "integer"}},
            "top_n": {"type": "integer"},
        },
        "required": ["ids"],
    },
}


SEMANTIC_CLUSTER_RESPONSE = _obj(
    {
        "status": _str(),
        "clusters": {"type": "array", "items": {}},
    },
    required=["status", "clusters"],
)


@llm_tool(SEMANTIC_CLUSTER_TOOL, SEMANTIC_CLUSTER_RESPONSE, read_only=False, concurrency_safe=False)
def semantic_cluster_tool(ids: List[int], top_n: int = 6) -> Dict[str, Any]:
    """Request clustered hits from the backend."""
    url = _get_backend_url()
    min_size = 2 if len(ids) < 16 else 3 if len(ids) < 24 else 5
    resp = httpx.post(
        f"{url}/semantic/cluster", json={"ids": ids, "min_size": min_size}, timeout=_HTTP_TIMEOUT
    )
    resp.raise_for_status()
    return {"status": "success", "clusters": resp.json()[:top_n]}


SEMANTIC_CLUSTER_WORDS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "semantic_cluster_words",
        "description": "Cluster tokens using embeddings and LLM labels.",
        "parameters": {
            "type": "object",
            "properties": {
                "tokens": {"type": "array", "items": {"type": "string"}},
                "top_n": {"type": "integer", "default": 6},
            },
            "required": ["tokens"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "tokens": {"type": "array", "items": {"type": "string"}},
            "top_n": {"type": "integer"},
        },
        "required": ["tokens"],
    },
}


SEMANTIC_CLUSTER_WORDS_RESPONSE = _obj(
    {
        "status": _str(),
        "clusters": {"type": "array", "items": {}},
        "input_token_count": _int(),
        "cluster_token_count": _int(),
        "fallback": _obj({"backend": _str(), "reason": _str()}, additional=True),
    },
    required=["status", "clusters"],
)


@llm_tool(SEMANTIC_CLUSTER_WORDS_TOOL, SEMANTIC_CLUSTER_WORDS_RESPONSE, read_only=False, concurrency_safe=False)
def semantic_cluster_words_tool(tokens: List[str], top_n: int = 6) -> Dict[str, Any]:
    """Request word-level clusters from the backend."""
    url = _get_backend_url()
    cluster_tokens = _word_cluster_tokens(tokens)
    min_size = 2 if len(cluster_tokens) < 64 else 3
    payload = {"tokens": cluster_tokens, "examples": cluster_tokens, "min_size": min_size}
    try:
        resp = httpx.post(
            f"{url}/semantic/cluster_words",
            json=payload,
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return {
            "status": "success",
            "clusters": resp.json()[:top_n],
            "input_token_count": len(tokens),
            "cluster_token_count": len(cluster_tokens),
        }
    except httpx.HTTPStatusError as exc:
        status_code = int(getattr(exc.response, "status_code", 0) or 0)
        if status_code == 404:
            return _local_semantic_cluster_words(
                cluster_tokens,
                min_size=min_size,
                top_n=top_n,
                reason="backend_endpoint_missing_404",
                input_token_count=len(tokens),
            )
        if status_code and status_code < 500:
            raise
        return _local_semantic_cluster_words(
            cluster_tokens,
            min_size=min_size,
            top_n=top_n,
            reason=f"backend_http_{status_code or 'error'}",
            input_token_count=len(tokens),
        )
    except httpx.RequestError as exc:
        return _local_semantic_cluster_words(
            cluster_tokens,
            min_size=min_size,
            top_n=top_n,
            reason=f"{type(exc).__name__}: {exc}",
            input_token_count=len(tokens),
        )


REFINE_CLUSTER_LABEL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "refine_cluster_label",
        "description": "Generate a fresh label for given samples.",
        "parameters": {
            "type": "object",
            "properties": {
                "cluster_id": {"type": "integer"},
                "samples": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["cluster_id", "samples"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "integer"},
            "samples": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["cluster_id", "samples"],
    },
}


REFINE_CLUSTER_LABEL_RESPONSE = _obj(
    {"status": _str(), "cluster_id": _int(), "label": _str()},
    required=["status", "cluster_id", "label"],
)


@llm_tool(REFINE_CLUSTER_LABEL_TOOL, REFINE_CLUSTER_LABEL_RESPONSE, read_only=False, concurrency_safe=False)
def refine_cluster_label(
    cluster_id: int, samples: List[str]
) -> Dict[str, Any]:
    """Refine a cluster label using the LLM."""
    from candyconc.services import cluster_labeler
    import asyncio
    import concurrent.futures

    def _run_sync() -> str:
        # Late attribute lookup so test monkeypatches on the module land even
        # when the coroutine runs on a worker thread.
        return asyncio.run(cluster_labeler.generate_label(samples))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (plain sync caller): asyncio.run is safe here.
        label = _run_sync()
    else:
        # Called from a running event loop (orchestrator dispatch path):
        # asyncio.run() would raise "cannot be called from a running event
        # loop". Run the coroutine on a worker thread with its own loop —
        # same pattern as SessionManager.summarise.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            label = executor.submit(_run_sync).result()
    return {"status": "success", "cluster_id": cluster_id, "label": label}


SEMANTIC_RECLUSTER_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "semantic_recluster",
        "description": "Suggest merges or splits for clusters using the LLM.",
        "parameters": {
            "type": "object",
            "properties": {
                "clusters": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["clusters"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "clusters": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["clusters"],
    },
}


SEMANTIC_RECLUSTER_RESPONSE = _obj(
    {"status": _str(), "plan": _obj({}, additional=True)},
    required=["status", "plan"],
)


@llm_tool(SEMANTIC_RECLUSTER_TOOL, SEMANTIC_RECLUSTER_RESPONSE, read_only=False, concurrency_safe=False)
def semantic_recluster(clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Request reclustering plan from the backend."""
    url = _get_backend_url()
    resp = httpx.post(
        f"{url}/semantic/recluster",
        json={"clusters": clusters},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return {"status": "success", "plan": resp.json()}


DOCUMENT_SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "document_search",
        "description": "Return ranked documents for the term.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Search term"},
                "top_n": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 5,
                },
                "snippet": {
                    "type": "integer",
                    "description": "Snippet length",
                    "default": 30,
                },
                "metric": {
                    "type": "string",
                    "description": "Ranking metric",
                },
                "date": {"type": "string", "description": "Date filter"},
                "genre": {"type": "string", "description": "Genre filter"},
                "metadata_filters": {
                    "type": "object",
                    "description": "Beliebige Metadatenfilter für Felder wie source, model, register oder text_type.",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "top_n": {"type": "integer"},
            "snippet": {"type": "integer"},
            "metric": {"type": "string"},
            "date": {"type": "string"},
            "genre": {"type": "string"},
            "metadata_filters": {
                "type": "object",
                "additionalProperties": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                },
            },
            "corpus": {"type": "string"},
        },
        "required": ["term"],
    },
}


METADATA_VALUES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "metadata_values",
        "description": (
            "Inventory document-level metadata fields and their distinct values "
            "for the active corpus, optionally within document-metadata filters. "
            "Omit fields (or pass ['*']) to inspect the complete metadata "
            "inventory. This does not inspect token annotations: word, lemma, "
            "POS, morphology, named-entity and dependency attributes belong to "
            "token queries or frequency/KWIC tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional document-metadata fields. Omit this argument "
                        "or pass ['*'] to return all available fields; do not "
                        "request token attributes such as word, lemma or POS."
                    ),
                },
                "filters": {
                    "type": "object",
                    "description": "Optional metadata filters to narrow the returned values.",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
            },
            "required": [],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "fields": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "type": "object",
                "additionalProperties": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                },
            },
            "corpus": {"type": "string"},
        },
        "required": [],
    },
}


DOCUMENTATION_SEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "documentation_search",
        "description": "Search project documentation for lines with the term.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Search term"},
                "top_n": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 5,
                },
                "snippet": {
                    "type": "integer",
                    "description": "Snippet length in characters",
                    "default": 30,
                },
            },
            "required": ["term"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "top_n": {"type": "integer"},
            "snippet": {"type": "integer"},
        },
        "required": ["term"],
    },
}


_METADATA_DISCOVERY_FIELDS: tuple[str, ...] = (
    "source",
    "register",
    "model",
    "text_type",
    "variant",
    "reference_kind",
)


def _selected_metadata_fields(
    fields: Optional[List[str]],
    available_fields: List[str],
) -> tuple[List[str], List[str], List[str]]:
    requested = [str(field).strip() for field in (fields or []) if str(field).strip()]
    if not requested or "*" in requested:
        return list(available_fields), [], []
    available = set(available_fields)
    selected: List[str] = []
    for field in requested:
        if field not in selected:
            selected.append(field)
    missing_requested = [field for field in selected if field not in available]
    discovery_added: List[str] = []
    if missing_requested:
        for field in _METADATA_DISCOVERY_FIELDS:
            if field in available and field not in selected:
                selected.append(field)
                discovery_added.append(field)
    return selected, missing_requested, discovery_added


DOCUMENT_SEARCH_RESPONSE = _rows_response(
    # ``document_search`` rows carry ``doc_id`` alongside file/pos/score/snippet
    # (core/doc_search.py). The row schema is additionalProperties:false, so the
    # MCP response gate 500s every result unless ``doc_id`` is declared too.
    {"doc_id": _int(), "file": _str(), "pos": _int(), "score": _num(), "snippet": _str()},
)



@llm_tool(DOCUMENT_SEARCH_TOOL, DOCUMENT_SEARCH_RESPONSE)
def document_search_tool(
    term: str,
    top_n: int = 5,
    snippet: int = 30,
    *,
    metric: str | None = None,
    date: str | None = None,
    genre: str | None = None,
    metadata_filters: Dict[str, Any] | None = None,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """Wrapper for :func:`document_search` returning JSON rows.

    FT-COPILOT-CORPUS-RESOLVE: resolves the corpus per call instead of reading
    the process-global index.
    """
    idx = _resolve_corpus_index(corpus)
    # NICHT vorkanonisieren: das Kanonisieren laesst Eintraege fallen,
    # deren Wert zu nichts wird, und ein Filter auf ein unbekanntes Feld
    # verschwand damit VOR dem Waechter in metadata_mask. Gemessen:
    # {"gibtsnichtxyz": "x"} traf 0 Dokumente, {"gibtsnichtxyz": "   "}
    # lieferte das volle Ergebnis. Dieselbe Eingabe, zwei Antworten, je
    # nach Leerraum. doc_search kanonisiert selbst.
    filters = dict(metadata_filters or {})
    pruefe_metadatenfelder(idx, filters)
    if str(date or "").strip():
        filters.setdefault("date", date)
    if str(genre or "").strip():
        filters.setdefault("genre", genre)
    rows = _document_search(
        idx,
        term,
        top_n=top_n,
        snippet=snippet,
        metric=metric,
        metadata_filters=filters,
    )
    return {"status": "success", "rows": rows}


METADATA_VALUES_RESPONSE = _obj(
    {
        "status": _str(),
        "available_fields": {"type": "array", "items": _str()},
        "values": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": _str()},
        },
        "diagnostics": _obj(
            {
                "requested_fields": {"type": "array", "items": _str()},
                "missing_requested_fields": {"type": "array", "items": _str()},
                "discovery_fields_added": {"type": "array", "items": _str()},
            },
            additional=True,
        ),
    },
    required=["status", "available_fields", "values", "diagnostics"],
)


@llm_tool(METADATA_VALUES_TOOL, METADATA_VALUES_RESPONSE)
def metadata_values_tool(
    fields: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    corpus: str | None = None,
) -> Dict[str, Any]:
    # FT-COPILOT-CORPUS-RESOLVE: resolve the corpus per call, not the global.
    idx = _resolve_corpus_index(corpus)
    pruefe_metadatenfelder(idx, filters)
    available_fields = idx.metadata_fields()
    selected_fields, missing_requested, discovery_added = _selected_metadata_fields(
        fields,
        available_fields,
    )
    values = {
        field: idx.metadata_values(field, filters=filters)
        for field in selected_fields
    }
    return {
        "status": "success",
        "available_fields": available_fields,
        "values": values,
        "diagnostics": {
            "requested_fields": [str(field).strip() for field in (fields or []) if str(field).strip()],
            "missing_requested_fields": missing_requested,
            "discovery_fields_added": discovery_added,
        },
    }


DOCUMENTATION_SEARCH_RESPONSE = _rows_response(
    {"file": _str(), "snippet": _str()},
)


@llm_tool(DOCUMENTATION_SEARCH_TOOL, DOCUMENTATION_SEARCH_RESPONSE)
def documentation_search_tool(
    term: str, top_n: int = 5, snippet: int = 30
) -> Dict[str, Any]:
    """Search the shipped user documentation for ``term`` and return snippets.

    Reads the manual that ``/docs/`` serves (packaged ``docs_html`` or
    ``CANDYCONC_DOCS_DIST``), see ``services/backend/docs_search.py``.
    """
    from candyconc.services.backend.docs_search import search_documentation

    return search_documentation(term, top_n=top_n, snippet=snippet)


# ---------------------------------------------------------------------------
# Docset creation / discovery (F5): closes the contrast/phrase path by letting
# the copilot BUILD the two sides of a contrast (not just read existing ones).


CREATE_DOCSET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_docset",
        "description": (
            "Build an ephemeral docset (subcorpus) from metadata filters AND/OR a "
            "search query, returning a live docset_id usable by contrast_collocates, "
            "keyness, collocate_stats, frequency_list and ngram_frequency. Typical "
            "flow: metadata_values -> create_docset(side A) -> create_docset(side B) "
            "-> contrast_collocates. Give at least one of filters or query. "
            "Nur um je Wert eines Feldes zu zählen (je Register, je Modell): "
            "query_count(nach=Feld, filters=...) liefert alle Werte in einem Aufruf."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "Metadatenfilter (z.B. {\"model\": \"human\"}); op-getaggte Range-Filter erlaubt.",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "object"},
                        ]
                    },
                },
                "query": {
                    "type": "string",
                    "description": "Optionaler Suchausdruck (Klartext oder CQL mit Prefix cql:) zur Trefferbasis.",
                },
                "meta_filters": {
                    "type": "object",
                    "description": "Metadatenfilter, die NUR auf den query-Pfad angewendet werden (Alias zu filters wenn query gesetzt).",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "object"},
                        ]
                    },
                },
                "label": {
                    "type": "string",
                    "description": "Optionales Label zur Wiedererkennung in der Antwort (rein informativ).",
                },
                "corpus": {
                    "type": "string",
                    "description": "Korpuskennung (optional, sonst aktives Korpus).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max. Treffer für den query-Pfad (server-seitig gedeckelt).",
                },
            },
            "required": [],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "filters": {"type": "object"},
            "query": {"type": "string"},
            "meta_filters": {"type": "object"},
            "label": {"type": "string"},
            "corpus": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": [],
    },
}


CREATE_DOCSET_RESPONSE = _obj(
    {
        "status": _str(),
        "docset_id": _str(),
        "doc_count": _int(),
        "token_count": _int(),
        # Use this subcorpus's analysis tokens for every word rate.
        "word_count": _int(),
        "label": _str(),
        "source": _str(),
        # _obj setzt additionalProperties=False, und mcp_server validiert
        # JEDES Ergebnis gegen dieses Schema. Ohne diese drei Namen
        # scheiterte create_docset mit gesetztem limit an der eigenen
        # Validierung: "Invalid result: Additional properties are not
        # allowed (scan_limit, truncated, truncation_note were
        # unexpected)", HTTP 500. Die Vorfassung dieses Punktes hat die
        # Kappung also nicht gemeldet, sondern den Aufruf zerstoert --
        # schlechter als das Schweigen, das sie beheben sollte.
        "truncated": {"type": "boolean"},
        # P2.7: die Konfundierer reisen mit, statt ein eigenes Werkzeug (und
        # damit einen zusaetzlichen Modellaufruf) zu bekommen.
        "profile": _obj(
            {
                "doc_len": _obj(
                    {
                        "min": _int(),
                        "median": _num(),
                        "mean": _num(),
                        "max": _int(),
                    },
                    required=["min", "median", "mean", "max"],
                ),
                "axes": {"type": "object", "additionalProperties": _str()},
                "source_texts": _int(),
            },
            required=["doc_len", "axes"],
        ),
    },
    required=["status", "docset_id", "doc_count", "token_count", "source"],
)


# read_only=True: building an ephemeral docset only populates an in-process LRU
# cache (no persisted / destructive side effect) — the same non-mutating class
# as compare/contrast_collocates which already build docsets internally. It is
# NOT concurrency_safe because the shared _DOCSET_CACHE is mutated without a lock.
@llm_tool(CREATE_DOCSET_TOOL, CREATE_DOCSET_RESPONSE, read_only=True, concurrency_safe=False)
def create_docset_tool(
    filters: Optional[Dict[str, Any]] = None,
    query: str | None = None,
    meta_filters: Optional[Dict[str, Any]] = None,
    label: str | None = None,
    corpus: str | None = None,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Create a live docset from metadata filters and/or a search query.

    Returns ``{status, docset_id, doc_count, token_count, label, source}`` where
    ``source`` is one of ``"query"`` / ``"metadata"`` recording how the docset
    was built. The ``docset_id`` is an ephemeral cache id consumable by the
    other analysis tools for the rest of the session.
    """
    from candyconc.services.backend import server as _server

    corpus = _normalise_corpus_reference(corpus)
    idx = _server.get_corpus(corpus)
    doc_count = _server._doc_count_for_index(idx)
    query_text = str(query or "").strip()
    # BEIDE Dikte, nicht eines von beiden. Die Vorfassung waehlte genau
    # eines aus und verwarf das andere STILL, mit status success:
    #     {"filters":{"split":"train"},"meta_filters":{"split":"test"}}
    #         -> 1317 Dokumente statt 0
    #     {"query":"und","filters":{"split":"test"},
    #      "meta_filters":{"model":"human"}} -> 741 statt 247
    # In EINEM Dikt uebergeben liefert dieselbe Kombination das richtige
    # Ergebnis, die Vereinigung ist also moeglich und war nur nicht
    # gemacht. Das Schema erlaubt beide Felder nebeneinander, kein oneOf.
    # Widersprechen sie einander im selben Feld, ist das ein EINGABEfehler.
    # Eine Vorfassung dieser Reparatur liess meta_filters gewinnen und
    # meldete das Verworfene in einem Zusatzfeld: das ist dieselbe Klasse
    # noch einmal, ein Filter wirkt nicht und der Aufruf meldet Erfolg.
    # {"filters":{"split":"train"},"meta_filters":{"split":"test"}} kann
    # kein Dokument erfuellen, und 683 Dokumente sehen aus wie ein Befund.
    _zusammen: Dict[str, Any] = {}
    for _quelle in (filters or {}, meta_filters or {}):
        for _feld, _wert in (_quelle or {}).items():
            if _feld in _zusammen and _zusammen[_feld] != _wert:
                raise ToolInputError(
                    f"Feld {_feld} ist in filters und meta_filters "
                    f"widerspruechlich belegt ({_zusammen[_feld]!r} gegen "
                    f"{_wert!r}). Beide Dikte werden vereinigt, ein Feld "
                    "kann nur eine Bedingung tragen."
                )
            _zusammen[_feld] = _wert
    applied_filters = _zusammen
    pruefe_metadatenfelder(idx, applied_filters)
    # VOR der Verzweigung: der Metadaten-Zweig scannt keine Treffer und
    # laesst das Fach leer. Eine Vorfassung legte es nur im Query-Zweig an,
    # und die Rueckgabe las es unbedingt -- UnboundLocalError auf jedem
    # Metadaten-Docset, von zwei bestehenden Tests gefangen.
    _scan_bericht: Dict[str, Any] = {}
    if query_text:
        # P2.8: wie in der Route, ein fehlendes limit ist kein Deckel.
        bounded_limit = (
            None if limit in (None, "")
            else _server._bounded_analysis_job_limit(limit)
        )
        # P2.8: ungedeckelter Vollscan gehoert in den begrenzten Pool,
        # auch vom Copilot aus (B6-Starvation-Befund).
        # Zweite Naht der Kappungsmeldung. Die REST-Route reicht das
        # Ausgabefach seit aee3bde7b4 durch, diese Stelle nicht: der
        # Copilot baute ein gedeckeltes Docset und schwieg darueber,
        # waehrend REST es meldete. Ein Fix an einer von zwei Nahtstellen
        # ist eine Verschiebung.
        doc_ids, _hits, _refs = _server._run_heavy_scan_sync(
            _server._search_docset_doc_ids,
            idx,
            query_text,
            meta_filters=applied_filters or {},
            ai_filters={},
            include_ai=True,
            include_human=True,
            limit=bounded_limit,
            bericht=_scan_bericht,
            # Keep exactly the matching documents within the filter.
            # Expanding source families would add documents that do not match it.
            familien=False,
        )
        source = "query"
    else:
        if not filters and not meta_filters:
            raise RuntimeError("Mindestens filters oder query muss angegeben werden.")
        doc_ids = _server._doc_ids_from_meta(idx, applied_filters)
        source = "metadata"
    # Under the catalogue name of the corpus it was built on, the name the
    # interface sends with a chip's KWIC query (not the alias default).
    docset_id = _server._store_docset(_docset_corpus_name(corpus), doc_ids, doc_count)
    token_count = 0
    word_count = 0
    if getattr(doc_ids, "size", 0):
        try:
            bezug = _wortnenner(idx, doc_ids)
            token_count, word_count = int(bezug["roh"]), int(bezug["woerter"])
        except Exception:
            token_count = word_count = 0
    response_label = str(label or "").strip()
    if not response_label and source == "metadata" and len(applied_filters) == 1:
        filter_value = next(iter(applied_filters.values()))
        if not isinstance(filter_value, (dict, list, tuple, set)):
            response_label = str(filter_value or "").strip()
    antwort: Dict[str, Any] = {
        "status": "success",
        "docset_id": docset_id,
        "doc_count": int(getattr(doc_ids, "size", len(doc_ids))),
        "token_count": token_count,
        "word_count": word_count,
        "label": response_label,
        "source": source,
    }
    # Der Bericht wurde eingesammelt und NIE gelesen. Das Argument
    # durchzureichen und den Wert wegzuwerfen sieht nach Reparatur aus und
    # ist keine: die Kappung blieb auf dieser Naht genauso still wie
    # vorher, waehrend REST sie meldete.
    # NUR das Kennzeichen, nicht die Prosanotiz. Der statische Prompt-Kern
    # hat EIN Zeichen Luft bis zum harten Limit von 31.000, und jedes Feld
    # des Antwortschemas muss laut test_prompt_output_doc_matches_schema in
    # der Werkzeugdoku stehen. Drei Namen dort ergaben 31.102. Das Modell
    # kennt sein eigenes limit, die Notiz traegt ihm nichts bei. Die
    # REST-Antwort fuehrt weiterhin alle drei Felder.
    if _scan_bericht.get("gekappt"):
        antwort["truncated"] = True
    from candyconc.services.tools.docset_profile import docset_konfundierer

    profil = docset_konfundierer(idx, doc_ids)
    if profil is not None:
        antwort["profile"] = profil
    return antwort


LIST_DOCSETS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_docsets",
        "description": (
            "List the persisted named subcorpora (durable docset definitions). "
            "Use a returned name with resolve_subcorpus, or pass it directly as a "
            "docset_id to contrast_collocates / keyness (they accept a name or id)."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "schema": {"type": "object", "properties": {}, "required": []},
}


LIST_DOCSETS_RESPONSE = _obj(
    {
        "status": _str(),
        # Each subcorpus is a stored definition; the exact extra fields depend on
        # how it was saved, so the row stays permissive.
        "subcorpora": {
            "type": "array",
            "items": _obj({"name": _str(), "corpus": _str()}, additional=True),
        },
        "total": _int(),
    },
    required=["status", "subcorpora", "total"],
)


@llm_tool(LIST_DOCSETS_TOOL, LIST_DOCSETS_RESPONSE)
def list_docsets_tool() -> Dict[str, Any]:
    """List persisted named subcorpora.

    Returns ``{status, subcorpora: [{name, corpus, ...}], total}``. Each row is
    the stored SubcorpusDefinition (at least ``name`` and ``corpus``); the exact
    extra fields depend on how the subcorpus was saved.
    """
    from candyconc.services.backend import server as _server

    subs = _server._get_project().subcorpora()
    rows = list(subs or [])
    return {"status": "success", "subcorpora": rows, "total": len(rows)}


RESOLVE_SUBCORPUS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "resolve_subcorpus",
        "description": (
            "Re-hydrate a persisted named subcorpus into a fresh live docset_id "
            "(re-runs its stored filter/query). Returns the docset_id to feed into "
            "the analysis tools. Use list_docsets first to discover names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name des gespeicherten Subkorpus."},
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
            },
            "required": ["name"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "corpus": {"type": "string"},
        },
        "required": ["name"],
    },
}


RESOLVE_SUBCORPUS_RESPONSE = _obj(
    {
        "status": _str(),
        "name": _str(),
        "docset_id": _str(),
        "doc_count": _int(),
        "token_count": _int(),
        "corpus": _str(),
    },
    required=["status", "name", "docset_id", "doc_count", "token_count", "corpus"],
)


# read_only=True: re-hydrating a saved subcorpus only reads its definition and
# populates the ephemeral docset cache (no persisted mutation). Not
# concurrency_safe (mutates the shared _DOCSET_CACHE without a lock).
@llm_tool(RESOLVE_SUBCORPUS_TOOL, RESOLVE_SUBCORPUS_RESPONSE, read_only=True, concurrency_safe=False)
def resolve_subcorpus_tool(name: str, corpus: str | None = None) -> Dict[str, Any]:
    """Re-hydrate a named subcorpus into a live docset.

    Returns ``{status, name, docset_id, doc_count, token_count, corpus}``.
    """
    from candyconc.services.backend import server as _server

    corpus = _normalise_corpus_reference(corpus)
    ref = str(name or "").strip()
    if not ref:
        raise RuntimeError("name muss angegeben werden.")
    definition = _server._get_project().get_subcorpus(ref)
    if definition is None:
        raise RuntimeError(f"Subkorpus '{ref}' nicht gefunden.")
    stored_corpus = str(definition.get("corpus") or "default")
    if corpus and str(corpus) != stored_corpus and str(corpus).strip().lower() != "default":
        raise RuntimeError(
            f"Subkorpus '{ref}' gehört zu Korpus '{stored_corpus}', nicht '{corpus}'."
        )
    idx = _server.get_corpus(stored_corpus)
    doc_count = _server._doc_count_for_index(idx)
    doc_ids = _server._run_heavy_scan_sync(
        _server._resolve_subcorpus_doc_ids, idx, definition
    )
    docset_id = _server._store_docset(stored_corpus, doc_ids, doc_count)
    token_count = 0
    if getattr(doc_ids, "size", 0):
        try:
            token_count = int(idx.docset_token_count(doc_ids))
        except Exception:
            token_count = 0
    return {
        "status": "success",
        "name": ref,
        "docset_id": docset_id,
        "doc_count": int(getattr(doc_ids, "size", len(doc_ids))),
        "token_count": token_count,
        "corpus": stored_corpus,
    }


# ---------------------------------------------------------------------------
# N-gram frequency (F5): contiguous word n-grams over corpus / docset.

_NGRAM_ROW_CAP = 100


def _ngram_rows(
    idx: Any,
    doc_ids: Optional[np.ndarray],
    min_n: int,
    max_n: int,
    limit: int,
) -> tuple[List[Dict[str, Any]], int]:
    """Return ``([{ngram, freq, n}], total_candidates)`` sorted by freq desc.

    Mirrors the REST /analysis/ngrams row builder exactly: keep an n-gram only
    when EVERY constituent token passes ``is_analyst_token`` (so |LBR|/marker
    tokens, emoji and punctuation never headline the ranking), and filter the
    WHOLE candidate set before taking the top-N so ``total_candidates`` describes
    the analyst-token basis — identical to routes/analysis.py. This keeps the
    copilot ngram top list byte-identical to the REST sibling.
    """
    import heapq

    from candyconc.services.backend import server as _server

    counts = _server._ngram_counts(idx, doc_ids, min_n, max_n)
    lex = idx.fast_index.lexicons.word
    analyst_candidates: List[tuple[tuple[int, ...], int, List[str]]] = []
    for key, count in counts.items():
        words: List[str] = []
        for wid in key:
            word = lex.get_string(int(wid)) if lex else ""
            if not _is_analyst_token(word):
                words = []
                break
            words.append(word)
        if not words:
            continue
        analyst_candidates.append((key, int(count), words))
    total_candidates = len(analyst_candidates)
    # Match REST ordering: descending frequency, then ascending token-ID tuple.
    # The deterministic tie-break keeps both returned rows and their ranks aligned.
    rows: List[Dict[str, Any]] = [
        {"ngram": " ".join(words), "freq": count, "n": len(key)}
        for key, count, words in heapq.nsmallest(
            max(1, int(limit)),
            analyst_candidates,
            key=lambda item: (-item[1], tuple(int(w) for w in item[0])),
        )
    ]
    return rows, total_candidates


NGRAM_FREQUENCY_RESPONSE = _rows_response(
    {"ngram": _str(), "freq": _int(), "n": _int()},
    extra_top={
        "total": _int(),
        "truncated": _bool(),
        "min_n": _int(),
        "max_n": _int(),
    },
    required=["status", "rows", "total", "truncated", "min_n", "max_n"],
)


@llm_tool(NGRAM_FREQUENCY_TOOL, NGRAM_FREQUENCY_RESPONSE)
def ngram_frequency_tool(
    min_n: int = 2,
    max_n: int = 2,
    docset_id: str | None = None,
    corpus: str | None = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Return the most frequent contiguous word n-grams.

    Returns ``{status, rows: [{ngram, freq, n}], total, truncated, min_n, max_n}``
    with rows capped at the top 100 (like frequency_list) and ``truncated`` set
    when the full candidate set exceeds the returned rows.
    """
    from candyconc.services.backend import server as _server

    min_n, max_n = _server._validate_ngram_bounds(int(min_n), int(max_n))
    resolved_id = _coerce_docset_id(docset_id, corpus)
    idx, doc_ids = _resolve_docset_doc_ids(corpus, resolved_id)
    try:
        row_limit = min(_NGRAM_ROW_CAP, int(limit) if limit else _NGRAM_ROW_CAP)
    except (TypeError, ValueError):
        row_limit = _NGRAM_ROW_CAP
    row_limit = max(1, row_limit)
    rows, total = _ngram_rows(idx, doc_ids, min_n, max_n, row_limit)
    return {
        "status": "success",
        "rows": rows,
        "total": int(total),
        "truncated": int(total) > len(rows),
        "min_n": int(min_n),
        "max_n": int(max_n),
    }


NGRAM_CONTRAST_RESPONSE = _rows_response(
    {
        "ngram": _str(),
        "n": _int(),
        "freq_target": _int(),
        "freq_reference": _int(),
        "per_million_target": _num(),
        "per_million_reference": _num(),
        "diff_per_million": _num(),
    },
    extra_top={
        "total": _int(),
        "truncated": _bool(),
        "min_n": _int(),
        "max_n": _int(),
        # Die Bezugsgroesse je Ordnung: Summe von L - n + 1 ueber die
        # Dokumente der jeweiligen Menge, NICHT die Tokenzahl. _obj setzt
        # additionalProperties=False, ohne Deklaration schluege die eigene
        # Validierung als 500 zurueck.
        "populations": {
            "type": "array",
            "items": _obj(
                {"n": _int(), "target": _int(), "reference": _int()},
                required=["n", "target", "reference"],
            ),
        },
    },
    required=["status", "rows", "total", "truncated", "min_n", "max_n"],
)


@llm_tool(NGRAM_CONTRAST_TOOL, NGRAM_CONTRAST_RESPONSE)
def ngram_contrast_tool(
    target_docset_id: str,
    reference_docset_id: str,
    min_n: int = 2,
    max_n: int = 2,
    corpus: str | None = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Contrast n-gram frequencies between two docsets.

    Returns ``{status, rows: [{ngram, n, freq_target, freq_reference,
    per_million_target, per_million_reference, diff_per_million}], total,
    truncated, min_n, max_n, populations}`` sorted by the absolute
    ``diff_per_million``, both directions. Rates are per million n-gram
    positions of the same order, ``populations`` holds the denominators.
    """
    import heapq

    from candyconc.services.backend import server as _server

    min_n, max_n = _server._validate_ngram_bounds(int(min_n), int(max_n))
    target_id = _coerce_docset_id(target_docset_id, corpus)
    reference_id = _coerce_docset_id(reference_docset_id, corpus)
    if not target_id or not reference_id:
        raise RuntimeError("target_docset_id und reference_docset_id müssen beide angegeben werden.")
    idx, target_ids = _resolve_docset_doc_ids(corpus, target_id)
    _, reference_ids = _resolve_docset_doc_ids(corpus, reference_id)

    t_counts = _server._ngram_counts(idx, target_ids, min_n, max_n)
    r_counts = _server._ngram_counts(idx, reference_ids, min_n, max_n)
    # Use a separate denominator for each n-gram order.
    # A document of length L offers max(0, L - n + 1) positions, so raw token
    # counts would bias contrasts between document collections of different lengths.
    stellen_t = _server._ngram_populations(idx, target_ids, min_n, max_n)
    stellen_r = _server._ngram_populations(idx, reference_ids, min_n, max_n)
    lex = idx.fast_index.lexicons.word
    try:
        row_limit = min(_NGRAM_ROW_CAP, int(limit) if limit else _NGRAM_ROW_CAP)
    except (TypeError, ValueError):
        row_limit = _NGRAM_ROW_CAP
    row_limit = max(1, row_limit)
    # Apply the REST analysis-token filter once per token ID so punctuation
    # and internal index markers do not enter the n-gram contrast ranking.
    alle_analysetoken = _server._analysetoken_pruefer(lex)
    total = 0

    def _kandidaten():
        nonlocal total
        for key, ft, fr in _server._ngram_vereinigung(t_counts, r_counts):
            if not alle_analysetoken(key):
                continue
            total += 1
            ft, fr = int(ft), int(fr)
            nenner_t = int(stellen_t.get(len(key), 0))
            nenner_r = int(stellen_r.get(len(key), 0))
            pmt = (ft * 1_000_000.0 / nenner_t) if nenner_t else 0.0
            pmr = (fr * 1_000_000.0 / nenner_r) if nenner_r else 0.0
            # Sortierschluessel, byte-gleich zur REST-Schwester
            # (server._run_ngrams_diff_job): absteigend nach dem BETRAG
            # der UNGERUNDETEN Differenz, bei Gleichstand aufsteigend
            # nach dem Token-ID-Tupel. Die Vorfassung sortierte auf dem
            # gerundeten Wert ohne Gleichstandsregel, und bei
            # 239.79377641241456 entschied die Mengenreihenfolge:
            # der Copilot fuehrte "hast du", REST "nicht als".
            yield -abs(pmt - pmr), tuple(map(int, key)), key, ft, fr, pmt, pmr

    # Rank by absolute difference, matching REST, to include both directions.
    # Use nsmallest and a token-ID tie-break to select rows without sorting or
    # materializing every type. Build dictionaries and text only for returned
    # rows while total still counts every filtered type.
    rows = [
        {
            "ngram": " ".join(lex.get_string(int(w)) for w in key),
            "n": len(key),
            "freq_target": ft,
            "freq_reference": fr,
            "per_million_target": round(pmt, 4),
            "per_million_reference": round(pmr, 4),
            "diff_per_million": round(pmt - pmr, 4),
        }
        for _, _, key, ft, fr, pmt, pmr in heapq.nsmallest(
            row_limit, _kandidaten(), key=lambda eintrag: (eintrag[0], eintrag[1])
        )
    ]
    # Der Nenner gehoert in DIESELBE Antwort wie die Rate, sonst laesst sie
    # sich nicht nachrechnen. Je Ordnung eine Zeile.
    stellen = [
        {
            "n": int(n),
            "target": int(stellen_t.get(n, 0)),
            "reference": int(stellen_r.get(n, 0)),
        }
        for n in range(int(min_n), int(max_n) + 1)
    ]
    return {
        "status": "success",
        "rows": rows,
        "total": int(total),
        "truncated": int(total) > len(rows),
        "min_n": int(min_n),
        "max_n": int(max_n),
        "populations": stellen,
    }


# ---------------------------------------------------------------------------
# FT-COPILOT-PARITY: parallel / aligned KWIC — the flagship Human-vs-AI feature.
# Read-only wrappers over the server's parallel-group + alignment handlers,
# guarded by _paired_guard so they degrade to a graceful not_applicable on an
# unpaired corpus (mirroring compare_collocates_tool) instead of returning
# degenerate self-mapped groups.


PARALLEL_GROUPS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parallel_groups",
        "description": (
            "List parallel document groups (one human source + its AI variants, "
            "keyed by ref_doc) on a PAIRED corpus — the Human-vs-AI substrate. "
            "Each group exposes the human_doc_id and the variant_doc_ids. Use a "
            "group's ref_doc/doc positions with parallel_kwic. Returns "
            "not_applicable on an unpaired corpus."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "docset_id": {
                    "type": "string",
                    "description": "Subkorpus/Docset-ID ODER Subkorpus-Name (optional, sonst ganzer Korpus).",
                },
                "sort": {
                    "type": "string",
                    "description": "Sortierung: ref_doc (Default) oder variant_count.",
                },
                "limit": {"type": "integer", "description": "Max. Gruppen.", "default": 50},
                "offset": {"type": "integer", "description": "Seiten-Offset.", "default": 0},
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
            },
            "required": [],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "docset_id": {"type": "string"},
            "sort": {"type": "string"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": [],
    },
}


PARALLEL_GROUPS_RESPONSE = _obj(
    {
        "status": _str(),
        "total": _int(),
        "groups": {
            "type": "array",
            "items": _row_schema(
                {
                    "ref_doc": _int(),
                    "doc_count": _int(),
                    "doc_ids": {"type": "array", "items": {"type": "integer"}},
                    "human_doc_id": _int(),
                    "variant_doc_ids": {"type": "array", "items": {"type": "integer"}},
                    "models": {
                        "type": "array",
                        "items": _row_schema({"model": _str(), "count": _int()}),
                    },
                    "text_types": _obj({}, additional=True),
                    "sources": {"type": "array", "items": _str()},
                    "label": _str(),
                }
            ),
        },
        # not_applicable branch (unpaired corpus):
        "reason": _str(),
        "feature": _str(),
        "detail": _str(),
    },
    required=["status"],
)


@llm_tool(PARALLEL_GROUPS_TOOL, PARALLEL_GROUPS_RESPONSE)
def parallel_groups_tool(
    docset_id: str | None = None,
    sort: str = "ref_doc",
    limit: int = 50,
    offset: int = 0,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """List parallel document groups (Human + AI variants) on a paired corpus.

    Returns ``{status, total, groups: [...]}`` on a paired corpus or the
    ``{status: "not_applicable", reason: "corpus_not_paired", ...}`` envelope on
    an unpaired corpus (same graceful degradation as compare_collocates_tool).
    """
    from candyconc.services.backend import server as _server

    corpus = _normalise_corpus_reference(corpus)
    corpus_name = corpus or "default"
    idx = _server.get_corpus(corpus_name)
    na = _server._paired_guard(idx, "parallel_groups")
    if na is not None:
        return na

    raw_doc_ids = None
    if docset_id:
        resolved = _coerce_docset_id(docset_id, corpus)
        docset = _server._get_docset(str(resolved))
        raw_doc_ids = _server._coerce_doc_ids(docset.get("doc_ids"))

    mapping = _server.resolve_pair_groups(idx, corpus_name, axis=None)
    ref_docs = list(mapping.keys())
    if raw_doc_ids is not None:
        reverse_map: dict[int, int] = {}
        for ref_doc, doc_ids in mapping.items():
            for doc_id in doc_ids:
                reverse_map[int(doc_id)] = int(ref_doc)
        meta = idx.fast_index.doc_metadata or {}
        selected: set[int] = set()
        for doc_id in raw_doc_ids:
            ref_doc = reverse_map.get(int(doc_id))
            if ref_doc is None:
                ref_doc = _server._parse_ref_doc_from_meta(meta.get(int(doc_id), {}), int(doc_id))
            if ref_doc is None:
                continue
            selected.add(int(ref_doc))
        ref_docs = sorted(selected)

    if str(sort) == "variant_count":
        ref_docs.sort(key=lambda r: len(mapping.get(int(r), [])), reverse=True)
    else:
        ref_docs.sort()

    total = int(len(ref_docs))
    safe_limit = _server._bounded_page_limit(limit or 50)
    safe_offset = _server._bounded_offset(offset)
    ref_docs = ref_docs[safe_offset : safe_offset + safe_limit]

    groups: List[Dict[str, Any]] = []
    for ref_doc in ref_docs:
        doc_ids = [int(d) for d in mapping.get(int(ref_doc), [])]
        groups.append(_server._parallel_group_summary(idx, int(ref_doc), doc_ids))
    return {"status": "success", "total": total, "groups": groups}


PARALLEL_KWIC_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parallel_kwic",
        "description": (
            "Aligned KWIC: for a hit POSITION in one document, return the "
            "ALIGNED sentence + KWIC from the parallel variants (human source and "
            "its AI versions) of the same ref_doc, the core Human-vs-AI compare "
            "view. Pass a 'pos' from a run_cqlf_query row. Returns not_applicable "
            "on an unpaired corpus. aligned=false: no sentence in the window reaches the "
            "document-alignment threshold (similarity 0.5), left/kw/right stay empty. "
            "matched=false: the keyword is absent from the counterpart, kw stays empty."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pos": {"type": "integer", "description": "Token-Position eines Treffers (aus run_cqlf_query)."},
                "keyword": {"type": "string", "description": "Optionales Stichwort zur Hervorhebung im Variant."},
                "ctx": {"type": "integer", "description": "Kontext-Tokens.", "default": 6},
                "max_variants": {"type": "integer", "description": "Max. Varianten (1-6).", "default": 3},
                "include_models": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nur diese Modelle als Varianten (optional).",
                },
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
            },
            "required": ["pos"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "pos": {"type": "integer"},
            "keyword": {"type": "string"},
            "ctx": {"type": "integer"},
            "max_variants": {"type": "integer"},
            "include_models": {"type": "array", "items": {"type": "string"}},
            "corpus": {"type": "string"},
        },
        "required": ["pos"],
    },
}


PARALLEL_KWIC_RESPONSE = _obj(
    {
        "status": _str(),
        "ref_doc": _int(),
        "base_doc_id": _int(),
        "variants": {
            "type": "array",
            "items": _row_schema(
                {
                    "doc_id": _int(),
                    "model": _str(),
                    "prompting_method": _str(),
                    "text_type": _str(),
                    "left": _str(),
                    "kw": _str(),
                    "right": _str(),
                    "matched": _bool(),
                    "aligned": _bool(),  # false: kein Satz erreicht die Schwelle der Dokumentausrichtung
                    "med": _num(),
                    "norm_med": _num(),
                    "similarity": _num(),
                }
            ),
        },
        # not_applicable branch (unpaired corpus):
        "reason": _str(),
        "feature": _str(),
        "detail": _str(),
    },
    required=["status"],
)


@llm_tool(PARALLEL_KWIC_TOOL, PARALLEL_KWIC_RESPONSE)
def parallel_kwic_tool(
    pos: int,
    keyword: str | None = None,
    ctx: int = 6,
    max_variants: int = 3,
    include_models: Optional[List[str]] = None,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """Aligned KWIC across the parallel variants of a hit position.

    Returns ``{status, ref_doc, base_doc_id, variants: [...]}`` on a paired
    corpus or the ``not_applicable`` envelope on an unpaired corpus. Mirrors the
    REST /analysis/kwic_parallel handler (same alignment + KWIC primitives).
    """
    from candyconc.services.backend import server as _server

    corpus = _normalise_corpus_reference(corpus)
    corpus_name = corpus or "default"
    idx = _server.get_corpus(corpus_name)
    na = _server._paired_guard(idx, "kwic_parallel")
    if na is not None:
        return na

    try:
        pos_i = int(pos)
    except (TypeError, ValueError):
        raise RuntimeError("pos muss eine ganze Zahl sein.")

    ctx_i = max(1, min(int(ctx), 80))
    max_v = max(1, min(int(max_variants), 6))
    kw_tokens = _server._tokenize_kw(str(keyword or "").strip())
    models = [str(m) for m in (include_models or []) if m is not None and str(m)]

    doc_bounds = _server._doc_bounds_for_index(idx)
    sentence_bounds = _server._sentence_bounds_for_index(idx)
    base_doc_id = _server._doc_id_for_position(idx, pos_i, doc_bounds)
    # Derselbe Zugriff wie der REST-Pfad: doc_metadata ist produktiv ein mmap-Mapping, kein dict. Die
    # dict-Pruefung liess auf PING jede Variante verschwinden (ref_doc fiel auf das Dokument selbst zurueck).
    def _meta(d: Any) -> Dict[str, Any]:
        return _server._doc_meta_for_doc_id(idx, int(d))[1]

    base_meta = _meta(base_doc_id)

    ref_doc = None
    if isinstance(base_meta, dict):
        raw_ref = base_meta.get("ref_doc")
        if isinstance(raw_ref, str) and raw_ref.isdigit():
            ref_doc = int(raw_ref)
        elif isinstance(raw_ref, int):
            ref_doc = int(raw_ref)
    if ref_doc is None:
        ref_doc = int(base_doc_id)

    base_bounds = _server._sentence_bounds_for_doc(
        idx, int(base_doc_id), doc_bounds=doc_bounds, sentence_bounds=sentence_bounds
    )
    focus_idx = _server._sentence_index_for_pos(base_bounds, pos_i)
    if focus_idx is None:
        focus_idx = 0
    base_sentence_list = _server._sentence_data_for_indices(
        idx, int(base_doc_id), base_bounds, [int(focus_idx)]
    )
    if not base_sentence_list:
        return {"status": "success", "ref_doc": int(ref_doc), "base_doc_id": int(base_doc_id), "variants": []}
    base_sentence = base_sentence_list[0]

    mapping = _server.resolve_pair_groups(idx, corpus_name, axis=None)
    candidate_ids = [int(d) for d in mapping.get(int(ref_doc), []) if int(d) != int(base_doc_id)]
    if models:
        candidate_ids = [d for d in candidate_ids if str(_meta(d).get("model") or "") in models]

    def _model_key(doc_id: int) -> tuple[int, str, int]:
        meta = _meta(doc_id)
        model = str(meta.get("model") or "")
        return (0 if model == "human" else 1, model, int(doc_id))

    candidate_ids.sort(key=_model_key)
    candidate_ids = candidate_ids[:max_v]

    variants: List[Dict[str, Any]] = []
    for doc_id in candidate_ids:
        meta = _meta(doc_id)
        best_sentence, med, norm, sim = _server._best_matching_sentence(
            idx,
            ref_sentence=base_sentence,
            ref_index=int(focus_idx),
            doc_id=int(doc_id),
            doc_bounds=doc_bounds,
            sentence_bounds=sentence_bounds,
            margin=6,
        )
        # Ohne Gegenstueck bleibt die Fassung sichtbar, als nicht ausgerichtet (wie der REST-Pfad).
        kwic = _server._kwic_from_sentence(idx, best_sentence, kw_tokens=kw_tokens, ctx=ctx_i)
        variants.append(
            {
                "doc_id": int(doc_id),
                "model": str(meta.get("model") or ""),
                "prompting_method": str(meta.get("prompting_method") or ""),
                "text_type": str(meta.get("text_type") or ""),
                "left": kwic.get("left", ""),
                "kw": kwic.get("kw", ""),
                "right": kwic.get("right", ""),
                "matched": bool(kwic.get("matched")),
                "aligned": best_sentence is not None,
                "med": med,
                "norm_med": norm,
                "similarity": sim,
            }
        )
    return {
        "status": "success",
        "ref_doc": int(ref_doc),
        "base_doc_id": int(base_doc_id),
        "variants": variants,
    }


# ---------------------------------------------------------------------------
# FT-COPILOT-PARITY: full-text / snippet retrieval — the grounding-core ability
# to actually READ a matched document (not just its KWIC line).


DOCUMENT_TEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "document_text",
        "description": (
            "Read the full (or capped) plain text of ONE document by doc_id, with "
            "its metadata. Use this to GROUND an interpretation in the actual "
            "source text behind a KWIC hit (the doc_id comes from a parallel_kwic "
            "variant or a document position). max_chars caps the returned text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "integer", "description": "Dokument-ID."},
                "max_chars": {
                    "type": "integer",
                    "description": "Max. Zeichen (Default 4000, hart gedeckelt bei 16000).",
                    "default": 4000,
                },
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
            },
            "required": ["doc_id"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "doc_id": {"type": "integer"},
            "max_chars": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": ["doc_id"],
    },
}


DOCUMENT_TEXT_RESPONSE = _obj(
    {
        "status": _str(),
        "doc_id": _int(),
        "text": _str(),
        "char_count": _int(),
        "token_count": _int(),
        "truncated": _bool(),
        "meta": _obj({}, additional=True),
    },
    required=["status", "doc_id", "text", "truncated"],
)


_DOCUMENT_TEXT_HARD_CAP = 16000


@llm_tool(DOCUMENT_TEXT_TOOL, DOCUMENT_TEXT_RESPONSE)
def document_text_tool(
    doc_id: int,
    max_chars: int = 4000,
    corpus: str | None = None,
) -> Dict[str, Any]:
    """Return the (capped) plain text of one document with its metadata.

    Returns ``{status, doc_id, text, char_count, token_count, truncated, meta}``.
    ``truncated`` is true when the document text exceeded ``max_chars`` (clamped
    to a 16000-char hard cap). Reuses the same word-stream -> strings render the
    semantic snippet path uses, so the text is the corpus's tokenised form.
    """
    idx = _resolve_corpus_index(corpus)
    fast = idx.fast_index
    doc_bounds = (
        fast.boundaries.document._positions
        if fast.boundaries and fast.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    try:
        did = int(doc_id)
    except (TypeError, ValueError):
        raise RuntimeError("doc_id muss eine ganze Zahl sein.")
    n_docs = int(doc_bounds.size)
    if n_docs == 0:
        raise RuntimeError("Dokumentgrenzen fehlen. Bitte Index neu bauen.")
    if did < 0 or did >= n_docs:
        raise RuntimeError(f"doc_id {did} ausserhalb des Bereichs (0..{n_docs - 1}).")

    token_count_total = int(fast.token_store.token_count)
    doc_start = int(doc_bounds[did])
    doc_end = int(doc_bounds[did + 1]) if (did + 1) < n_docs else token_count_total
    ids = fast.token_store.word_stream.get_range(doc_start, doc_end)
    doc_token_count = int(ids.size)
    if ids.size == 0:
        text = ""
    else:
        word_lex = fast.lexicons.word
        if word_lex is None:
            raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")
        words = strings_for_ids(
            word_lex.offsets,
            word_lex.strings_view,
            ids.astype(np.uint32, copy=False),
            True,
        )
        text = " ".join(str(word) for word in words).strip()

    try:
        cap = int(max_chars)
    except (TypeError, ValueError):
        cap = 4000
    cap = max(1, min(cap, _DOCUMENT_TEXT_HARD_CAP))
    full_len = len(text)
    truncated = full_len > cap
    if truncated:
        text = text[:cap].rstrip()

    meta = fast.doc_metadata.get(did, {}) if fast.doc_metadata else {}
    return {
        "status": "success",
        "doc_id": did,
        "text": text,
        "char_count": len(text),
        "token_count": doc_token_count,
        "truncated": bool(truncated),
        "meta": meta if isinstance(meta, dict) else {},
    }


KWIC_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "kwic_context",
        "description": (
            "Read a wide text WINDOW around a single token position (more context "
            "than a KWIC line). Use this to GROUND a claim about the immediate "
            "surroundings of a specific hit — pass the 'pos' from a run_cqlf_query "
            "row and a wide 'ctx' (e.g. 30) to see the full sentence/paragraph."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pos": {"type": "integer", "description": "Token-Position (aus run_cqlf_query)."},
                "ctx": {"type": "integer", "description": "Kontext-Tokens links/rechts.", "default": 30},
                "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
            },
            "required": ["pos"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {
            "pos": {"type": "integer"},
            "ctx": {"type": "integer"},
            "corpus": {"type": "string"},
        },
        "required": ["pos"],
    },
}


KWIC_CONTEXT_RESPONSE = _obj(
    {
        "status": _str(),
        "pos": _int(),
        "doc_id": _int(),
        "left": _str(),
        "kw": _str(),
        "right": _str(),
        "meta": _obj({}, additional=True),
    },
    required=["status", "pos", "left", "kw", "right"],
)


_KWIC_CONTEXT_MAX = 80


@llm_tool(KWIC_CONTEXT_TOOL, KWIC_CONTEXT_RESPONSE)
def kwic_context_tool(pos: int, ctx: int = 30, corpus: str | None = None) -> Dict[str, Any]:
    """Wide KWIC window around a single token position (grounding-core).

    Returns ``{status, pos, doc_id, left, kw, right, meta}`` — a single KWIC row
    with a wide context window, clipped to the containing document so the window
    never bleeds across document boundaries.
    """
    idx = _resolve_corpus_index(corpus)
    fast = idx.fast_index
    try:
        pos_i = int(pos)
    except (TypeError, ValueError):
        raise RuntimeError("pos muss eine ganze Zahl sein.")
    token_count_total = int(fast.token_store.token_count)
    if pos_i < 0 or pos_i >= token_count_total:
        raise RuntimeError(f"pos {pos_i} ausserhalb des Bereichs (0..{token_count_total - 1}).")

    ctx_i = max(1, min(int(ctx), _KWIC_CONTEXT_MAX))
    doc_bounds = (
        fast.boundaries.document._positions
        if fast.boundaries and fast.boundaries.document
        else np.array([], dtype=np.uint32)
    )
    doc_id = None
    doc_start = 0
    doc_end = token_count_total
    if doc_bounds.size:
        doc_id = int(np.searchsorted(doc_bounds, np.uint32(pos_i), side="right") - 1)
        if doc_id < 0:
            doc_id = 0
        doc_start = int(doc_bounds[doc_id])
        doc_end = int(doc_bounds[doc_id + 1]) if (doc_id + 1) < int(doc_bounds.size) else token_count_total

    left_start = max(doc_start, pos_i - ctx_i)
    right_end = min(doc_end, pos_i + ctx_i + 1)

    word_lex = fast.lexicons.word
    if word_lex is None:
        raise RuntimeError("Word Lexikon fehlt. Bitte Index neu bauen.")

    from candyconc.core.source_spacing import display_flags, join_tokens_with_starts

    ws = display_flags(idx)

    def _render(start: int, end: int) -> str:
        if end <= start:
            return ""
        ids = fast.token_store.word_stream.get_range(start, end)
        if ids.size == 0:
            return ""
        words = strings_for_ids(
            word_lex.offsets, word_lex.strings_view, ids.astype(np.uint32, copy=False), True
        )
        if ws is not None and len(words) == end - start:
            # The spacing of the text, like the KWIC rows of the other readers.
            return join_tokens_with_starts([str(w) for w in words], start, ws)[0].strip()
        return " ".join(str(w) for w in words).strip()

    left = _render(left_start, pos_i)
    kw = _render(pos_i, pos_i + 1)
    right = _render(pos_i + 1, right_end)
    meta = {}
    if doc_id is not None and fast.doc_metadata:
        raw = fast.doc_metadata.get(int(doc_id), {})
        meta = raw if isinstance(raw, dict) else {}
    return {
        "status": "success",
        "pos": pos_i,
        "doc_id": int(doc_id) if doc_id is not None else 0,
        "left": left,
        "kw": kw,
        "right": right,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# Lexical diversity (thin copilot wrapper over the F4/B4 services tool).
# Registration is GUARDED: if the services module is not present at import time
# (concurrent-track ordering) the tool is simply not registered, never crashing
# the copilot surface.
try:  # pragma: no cover - import guarded for concurrent-track ordering
    from candyconc.services.tools.lexical_diversity import (
        compute_lexical_diversity as _compute_lexical_diversity,
    )
except Exception:  # pragma: no cover
    _compute_lexical_diversity = None

if _compute_lexical_diversity is not None:
    LEXICAL_DIVERSITY_TOOL: Dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "lexical_diversity",
            "description": (
                "Lexical-diversity metrics (TTR, STTR, Guiraud R and MATTR) for "
                "the corpus or a docset/subcorpus. STTR (mean TTR over a fixed window) "
                "is the corpus-size-comparable measure; raw TTR is length-confounded, so "
                "prefer STTR/MATTR when comparing differently sized sides. MATTR is "
                "included by default and can be disabled explicitly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "docset_id": {
                        "type": "string",
                        "description": "Docset-ID ODER Subkorpus-Name (optional, sonst ganzes Korpus).",
                    },
                    "corpus": {"type": "string", "description": "Korpuskennung (optional)."},
                    "sttr_window": {"type": "integer", "description": "STTR-Fenstergröße in Token.", "default": 1000},
                    "include_mattr": {"type": "boolean", "description": "MATTR mitberechnen (standardmäßig ja).", "default": True},
                },
                "required": [],
            },
        },
        "schema": {
            "type": "object",
            "properties": {
                "docset_id": {"type": "string"},
                "corpus": {"type": "string"},
                "sttr_window": {"type": "integer"},
                "include_mattr": {"type": "boolean"},
            },
            "required": [],
        },
    }

    LEXICAL_DIVERSITY_RESPONSE = _obj(
        {
            "status": _str(),
            "ttr": _num(),
            "sttr": _num(),
            "sttr_window": _int(),
            "sttr_n_windows": _int(),
            "guiraud": _num(),
            "n_tokens": _int(),
            "n_types": _int(),
            # compute_lexical_diversity discloses the RAW corpus token total
            # (lexical_diversity.py) so TTR is anchored against the corpus size;
            # the response gate is additionalProperties:false, so it must be
            # declared here or every call 500s at the MCP boundary.
            "corpus_raw_token_count": _int(),
            "analyst_tokens_only": _bool(),
            "analyst_token_policy": _str(),
            "mattr": _num(),
            "mattr_window": _int(),
        },
        required=["status", "ttr", "sttr", "guiraud", "n_tokens", "n_types"],
    )

    @llm_tool(LEXICAL_DIVERSITY_TOOL, LEXICAL_DIVERSITY_RESPONSE)
    def lexical_diversity_tool(
        docset_id: str | None = None,
        corpus: str | None = None,
        sttr_window: int = 1000,
        include_mattr: bool = True,
    ) -> Dict[str, Any]:
        """Lexical-diversity metrics for the corpus or a docset/subcorpus.

        Returns ``{status, ttr, sttr, sttr_window, sttr_n_windows, guiraud,
        n_tokens, n_types, analyst_tokens_only, analyst_token_policy}``
        (+ ``mattr``/``mattr_window`` when ``include_mattr``). STTR/MATTR are
        ``None`` when the token stream is shorter than the window.
        """
        resolved_id = _coerce_docset_id(docset_id, corpus)
        idx, doc_ids = _resolve_docset_doc_ids(corpus, resolved_id)
        result = _compute_lexical_diversity(
            idx,
            doc_ids=None if doc_ids is None else doc_ids.tolist(),
            sttr_window=int(sttr_window),
            include_mattr=bool(include_mattr),
        )
        return {"status": "success", **result}


CLUSTER_SAVE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cluster_save",
        "description": "Persist cluster changes for the active project.",
        "parameters": {
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {"plan": {"type": "object"}},
        "required": ["plan"],
    },
}


def _stringify_ids(obj: Any) -> None:
    """Recursively cast ``id`` fields to strings in ``obj``."""

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "id":
                obj[key] = str(value)
            else:
                _stringify_ids(value)
    elif isinstance(obj, list):
        for item in obj:
            _stringify_ids(item)


CLUSTER_SAVE_RESPONSE = _obj({"status": _str()}, required=["status"])


@llm_tool(CLUSTER_SAVE_TOOL, CLUSTER_SAVE_RESPONSE, read_only=False, concurrency_safe=False)
def cluster_save(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Store cluster plan via the backend."""
    url = _get_backend_url()
    project = get_config("CANDYCONC_PROJECT", "default")
    payload = json.loads(json.dumps(plan))
    _stringify_ids(payload)
    resp = httpx.put(
        f"{url}/projects/{project}/clusters",
        json=payload,
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return {"status": "ok"}


CLUSTER_EXPORT_MD_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "cluster_export_md",
        "description": "Export clusters as Markdown outline.",
        "parameters": {
            "type": "object",
            "properties": {"clusters": {"type": "array", "items": {"type": "object"}}},
            "required": ["clusters"],
        },
    },
    "schema": {
        "type": "object",
        "properties": {"clusters": {"type": "array", "items": {"type": "object"}}},
        "required": ["clusters"],
    },
}


CLUSTER_EXPORT_MD_RESPONSE = _obj(
    {"status": _str(), "url": _str()}, required=["status", "url"]
)


@llm_tool(CLUSTER_EXPORT_MD_TOOL, CLUSTER_EXPORT_MD_RESPONSE, read_only=False, concurrency_safe=False)
def cluster_export_md(clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Request Markdown outline from the backend."""
    url = _get_backend_url()
    resp = httpx.post(
        f"{url}/semantic/outline",
        json={"clusters": clusters},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return {"status": "ok", "url": resp.json().get("url", "")}


# Abschlusswerkzeug, Bauform in deutung_abgeben.py (Name passt fuer llm_tool).
from .deutung_abgeben import DEUTUNG_ABGEBEN_TOOL, deutung_abgeben_tool  # noqa: E402,F401
llm_tool(DEUTUNG_ABGEBEN_TOOL)(deutung_abgeben_tool)
