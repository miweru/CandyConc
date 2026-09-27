"""Analysis HTTP routes sharing backend job, query and corpus helpers.

Handlers resolve server-owned caches, configuration and job runners at
call time to avoid a circular import and preserve server-namespace
overrides. The server also re-exports handlers for existing callers."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import heapq
import io
import json as _json
import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

import numpy as np
from fastapi import Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from candyconc.analysis_defaults import (
    analysierbare_groesse,
    CASE_POLICY_GEFALTET,
    LABEL_POLICY_GEFALTET,
    WORD_SKETCH_DEFAULT_MIN_FREQ,
    adaptive_collocate_min_freq,
    collocate_floor_mode,
    apply_word_sketch_min_freq,
    build_method_block,
    collocation_frame_provenance,
    collocation_method_extra,
    filter_collocate_frame_by_min_freq,
    filter_frequency_frame,
    is_analyst_token,
    sketch_difference,
    word_sketch_relation_label,
)
from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.domain.corpus import dependency_label_scheme
from candyconc.core.pairing import is_anchor, is_version
from candyconc.i18n import exception_text, lt
from candyconc.domain.query_parser import casefold_key
from candyconc.services.backend.query_count import _word_vectors_error
from candyconc.services.semantic.availability import SemanticLevel, semantic_search_status
from candyconc.services.tools.keyness import (
    schreibungen_anhaengen,
    DEFAULT_MIN_FREQ,
    RELIABILITY_EXPECTED_MIN,
    chi2_2x2_pooled,
    complement_docset_ids,
    compute_keyness_external,
    expected_min_cell,
    keyness_full_stats,
    normalize_disjoint_docsets,
    validate_external_reference,
)
from candyconc.services.backend.textnorm import _is_simple_single_token

from .. import auth, rate_limit
from ..schemas import (
    AnalysisTrendRequest,
    CollocationNetworkResponse,
    ConcordanceExportRequest,
    DispersionAnalysisResponse,
    DocsetFromSearchResponse,
    JobLaunchResponse,
    LexicalDiversityResponse,
    PagedCollocatesResponse,
    PagedFrequencyResponse,
    PagedKeynessResponse,
    PagedNgramsResponse,
    SketchDiffResponse,
    request_body_as_dict,
)

router = CandyAPIRouter()


def _label_scheme(idx: Any) -> str | None:
    """Annotation scheme of the dependency labels of ``idx`` (None if unknown)."""
    path = getattr(idx, "path", None)
    return dependency_label_scheme(path) if path else None


def _index_fingerprint(idx: Any) -> str:
    """Corpus cache signature used as the response ``indexFingerprint``.

    Reuses the server-side ``_corpus_cache_signature`` (read-only import): it
    changes whenever the index is rebuilt in place, so a recorded provenance
    block can be matched against the exact index state that produced it.
    Never raises — degrades to an empty string when the signature is
    unavailable so provenance injection can stay unconditional.
    """
    try:
        from .. import server as _server

        fast_index = getattr(idx, "fast_index", None)
        if fast_index is None:
            return ""
        fallback = str(getattr(fast_index, "index_path", "") or "")
        # Gehasht, bevor der Wert den Prozess verlaesst. Die Signatur lautet
        # roh "<absoluter Pfad>@<mtime_ns>", und dieses Feld ging bisher als
        # Klartext in jede Analyse-Antwort, in den Ereignisstrom und in die
        # Kopfzeile jedes Exports (NgramsTab schreibt
        # "# indexFingerprint: ..." in die Datei). Die Copilot-Naht hashte
        # bereits, die REST-Naht nicht: dieselbe Angabe, zwei Werte.
        # Dieselbe Funktion an beiden Naehten, damit sie byte-gleich sind.
        from candyconc.analysis_defaults import kurzer_indexstand

        return kurzer_indexstand(
            str(_server._corpus_cache_signature(fast_index, fallback))
        )
    except Exception:
        return ""

MAX_DISPERSION_PARTITIONS = 2048
MAX_SEMANTIC_SEARCH_TOP_N = 200
# Server-side caps for the collocation-network endpoint so a single request
# cannot build a graph large enough to exhaust memory/serialisation budgets.
# These mirror the engine-level guards in tools/collocate_stats.py.
MAX_COLLOCATION_NETWORK_NODES = 80
MAX_COLLOCATION_NETWORK_DEPTH = 2
MAX_SEMANTIC_SEARCH_CTX = 80

# The collocation engine enforces a hard minimum co-occurrence frequency floor
# (f >= COLLOCATE_COOCCURRENCE_FLOOR) before any candidate is scored. It is a
# deliberate statistical floor (single-cell chi-square is unreliable for tiny
# co-occurrence counts), but it was previously undocumented (FT id 5): a
# mid-frequency node could collapse to one function word with no explanation.
# We now surface it in the collocates method/params block and let callers raise
# it further with the validated ``min_freq`` query param (FT id 6).
COLLOCATE_COOCCURRENCE_FLOOR = 5


def _sanitize_float(value: Any) -> Any:
    """Map non-finite floats (NaN/Inf) to ``None`` for strict-JSON compliance.

    A single helper so every analysis route serialises identically and no raw
    NaN/Inf can leak into a response body and break a strict JSON client.
    """
    import math

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Apply :func:`_sanitize_float` to every cell of one result row."""
    return {key: _sanitize_float(val) for key, val in row.items()}


def _safe_positive_int(value: Any, *, name: str, default: int, max_value: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be an integer") from exc
    if parsed < 1:
        raise HTTPException(status_code=422, detail=f"{name} must be >= 1")
    if parsed > max_value:
        raise HTTPException(status_code=422, detail=f"{name} must be <= {max_value}")
    return parsed


def _safe_dispersion_partitions(partitions: int) -> int:
    value = int(partitions)
    if value < 1:
        return 1
    if value > MAX_DISPERSION_PARTITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"partitions must be <= {MAX_DISPERSION_PARTITIONS}",
        )
    return value


def _reject_malformed_bracket_cql(server_module: Any, idx: Any, term: str) -> None:
    """Raise a 400 ``CQL Parse Fehler`` for a bracket-CQL that ``normalize_query_input``
    leaves un-prefixed (so it would silently degrade to a literal-text miss).

    A leading ``[`` marks a CQL token-clause attempt. ``normalize_query_input``
    only adds the ``cql:`` prefix for *valid bare CQL* (quoted attributes or the
    ``[]`` wildcard); a malformed bracket form like ``[pos=NOUN`` / ``[pos=`` /
    ``[[[`` stays un-prefixed, and ``_dispersion_positions_for_term`` would then
    scan it as a literal word — yielding a dishonest freq-0 ``not_found`` instead
    of the parse error the /query path raises for the same input. We force the
    term through the SAME CQL parser the /query path uses (one shared decision):
    valid bare CQL already carries the ``cql:`` prefix and is left untouched; only
    the unparseable bracket forms reach here and surface the real 400.
    """
    raw = (term or "").strip()
    if not raw.startswith("["):
        return
    from candyconc.core.cql_macros import normalize_query_input

    if normalize_query_input(raw).lower().startswith("cql:"):
        # Valid bare CQL — already routed through the parser by the position path.
        return
    if server_module._is_legacy_bracket_attr_query(raw):
        # The legacy query parser intentionally accepts e.g. [pos=NOUN]. The
        # analysis route must not be stricter than /query for that supported shape.
        return
    try:
        server_module._positions_from_query(
            idx, f"cql:{raw}", limit=server_module._ANALYSIS_MATCH_LIMIT
        )
    except Exception as exc:  # noqa: BLE001 — surface the parser's user-error as 400
        word_vectors_error = _word_vectors_error(exc)
        if word_vectors_error is not None:
            raise word_vectors_error from exc
        if server_module._is_query_user_error(str(exc)):
            raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
        raise


def _collocation_node_term(server_module: Any, idx: Any, term: str) -> str:
    """Resolve a collocation node term like the search box does.

    Bare CQL (a quoted attribute or ``[]``) becomes ``cql:`` exactly as in
    ``/query``. Any other term that opens with ``[`` would be looked up as a
    literal word and give zero candidates without a word of explanation
    (inventar 3.11: ``[lemma="Regen"]`` without prefix returned
    ``node_frequency: 0``). A parse error surfaces as 400, a legacy unquoted
    clause as 422 with the accepted form.
    """
    from candyconc.core.cql_macros import normalize_query_input

    raw = (term or "").strip()
    normalized = normalize_query_input(raw)
    if normalized.lower().startswith("cql:"):
        return normalized
    if raw.lstrip("( \t").startswith("["):
        _reject_malformed_bracket_cql(server_module, idx, raw)
        raise ApiError(
            422,
            "collocation.node_not_cql",
            lt(
                "Der Knoten ist als Abfrage geschrieben, aber nicht als CQL lesbar. "
                "Kollokationen brauchen Attributwerte in Anführungszeichen, etwa "
                '[lemma="Regen"] oder [pos="NOUN"].',
                "The node is written as a query but cannot be read as CQL. "
                "Collocations need attribute values in quotation marks, for example "
                '[lemma="Regen"] or [pos="NOUN"].',
            ),
        )
    return raw


def _keyness_min_freq(value: Any) -> int:
    """Resolve the keyness reliability ``min_freq`` (FT-KEYNESS-RESEARCH).

    This is the *route-layer product policy*: the keyness endpoint defaults to a
    research-grade reliability floor of ``DEFAULT_MIN_FREQ`` (5) — candidates
    below it have an expected cell < 5, where the chi-square / log-likelihood
    approximation is unreliable. The reliability is *also* surfaced
    non-destructively via the per-row ``low_reliability``/``expected_min`` flags.
    The pure compute functions (``compute_keyness``/``compute_keyness_counts``)
    stay policy-free (default 0); the floor lives here so the math and the product
    default are separable. A client opts out with ``min_freq: 0``. Negative or
    non-integer values are a validation error (422).
    """
    if value is None:
        return int(DEFAULT_MIN_FREQ)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="min_freq must be an integer") from exc
    if parsed < 0:
        raise HTTPException(status_code=422, detail="min_freq must be >= 0")
    return parsed


def _keyness_external_reference_spec(
    payload: Dict[str, Any],
    reference_freq_list: Any,
    *,
    pos: str | None,
) -> tuple[dict[str, int], int, str | None]:
    """Validate an API-only external Keyness reference before a job is created."""
    vocabulary_complete = payload.get(
        "reference_vocabulary_complete", payload.get("reference_complete")
    )
    try:
        return validate_external_reference(
            reference_freq_list,
            reference_total=payload.get("reference_total"),
            vocabulary_complete=vocabulary_complete,
            target_pos=pos,
            reference_pos=payload.get("reference_pos"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc


def _keyness_disjoint_docsets(
    target_doc_ids: Any,
    reference_doc_ids: Any,
) -> tuple[np.ndarray, np.ndarray]:
    try:
        return normalize_disjoint_docsets(target_doc_ids, reference_doc_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc


def _keyness_docset_pair(
    _server: Any,
    payload: Dict[str, Any],
    *,
    source: str | None,
    corpus: Any,
) -> tuple[str, np.ndarray, np.ndarray] | None:
    """Resolve the one disjoint-docset contract shared by sync and job Keyness."""
    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    if source == "whole":
        has_other_population = any(
            payload.get(key) is not None
            for key in (
                "target_corpus",
                "reference_corpus",
                "target",
                "reference",
                "reference_freq_list",
                "reference_freqlist",
            )
        )
        if not target_docset_id or reference_docset_id or has_other_population:
            raise ApiError(
                422,
                "keyness.whole_target_only",
                lt(
                    "reference_source=whole ist nur für ein target_docset_id ohne "
                    "weitere Ziel- oder Referenzpopulation belegt",
                    "reference_source=whole is only supported for a target_docset_id "
                    "without any other target or reference population",
                ),
            )
        idx = _server.get_corpus(corpus)
        target_docset = _server._get_docset(str(target_docset_id))
        if target_docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        target_ids_raw = target_docset.get("doc_ids")
        if target_ids_raw is None:
            target_ids_raw = np.zeros(0, dtype=np.uint32)
        try:
            reference_ids = complement_docset_ids(
                target_ids_raw, doc_count=_server._doc_count_for_index(idx)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
        if reference_ids.size == 0:
            raise ApiError(
                422,
                "keyness.whole_reference_empty",
                lt(
                    "reference_source=whole benötigt mindestens ein Dokument außerhalb des Ziel-Docsets",
                    "reference_source=whole needs at least one document outside the target document set",
                ),
            )
        target_ids, reference_ids = _keyness_disjoint_docsets(
            target_ids_raw, reference_ids
        )
        return "whole", target_ids, reference_ids

    if source != "docset":
        return None
    if not target_docset_id or not reference_docset_id:
        raise ApiError(
            422,
            "analysis.docset_pair_required",
            lt(
                "target_docset_id und reference_docset_id sind erforderlich",
                "target_docset_id and reference_docset_id are required",
            ),
        )
    target_docset = _server._get_docset(str(target_docset_id))
    reference_docset = _server._get_docset(str(reference_docset_id))
    if target_docset.get("corpus") != (corpus or "default") or reference_docset.get(
        "corpus"
    ) != (corpus or "default"):
        raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
    target_ids_raw = target_docset.get("doc_ids")
    reference_ids_raw = reference_docset.get("doc_ids")
    return "docset", *_keyness_disjoint_docsets(
        target_ids_raw if target_ids_raw is not None else np.zeros(0, dtype=np.uint32),
        reference_ids_raw if reference_ids_raw is not None else np.zeros(0, dtype=np.uint32),
    )


async def _keyness_docset_population(
    _server: Any,
    idx: Any,
    doc_ids: np.ndarray,
    *,
    pos: str | None,
) -> tuple[dict[str, int], int]:
    """Resolve counts and denominator from the same document/POS population."""
    lex = idx.fast_index.lexicons.word
    if lex is None:
        raise RuntimeError(
            lt("Word Lexikon fehlt. Bitte Index neu bauen.", "Word lexicon missing. Rebuild the index.")
        )
    term_ids, counts = await asyncio.to_thread(
        idx.frequency_counts_docset,
        doc_ids,
        stopwords=None,
        pos_prefix=pos,
        case_fold=True,
    )
    words = _server.strings_for_ids(
        lex.offsets,
        lex.strings_view,
        np.asarray(term_ids, dtype=np.uint32),
        True,
    )
    total = (
        int(np.asarray(counts, dtype=np.uint64).sum(dtype=np.uint64))
        if pos
        else int(await asyncio.to_thread(idx.docset_token_count, doc_ids))
    )
    freq_map: dict[str, int] = {}
    for word, count in zip(words, counts):
        key = casefold_key(str(word))
        freq_map[key] = freq_map.get(key, 0) + int(count)
    return freq_map, total


def _resolve_ngram_n(payload: Dict[str, Any]) -> tuple[int, int]:
    """Resolve the ngram length bounds from the payload (FT id 9).

    Historically only ``min_n``/``max_n`` were honoured and a documented ``n``
    alias was silently dropped (``{"n":3}`` returned unigrams mislabeled
    ``n:1``). We now accept ``n`` as an alias: when NEITHER ``min_n`` nor
    ``max_n`` is supplied but ``n`` is present, ``min_n = max_n = int(n)`` so a
    request for trigrams actually returns trigrams. Explicit ``min_n``/``max_n``
    always win (when either is given, ``n`` is ignored). Non-integer values are
    a validation error (422) instead of a silent no-op.
    """

    def _coerce(name: str, value: Any, default: int) -> int:
        if value is None:
            return int(default)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                422,
                "param.not_integer",
                lt("{name} muss eine ganze Zahl sein", "{name} must be an integer"),
                name=name,
            ) from exc

    has_min = payload.get("min_n") is not None
    has_max = payload.get("max_n") is not None
    if not has_min and not has_max and payload.get("n") is not None:
        n_val = _coerce("n", payload.get("n"), 1)
        return n_val, n_val
    min_n = _coerce("min_n", payload.get("min_n"), 1)
    max_n = _coerce("max_n", payload.get("max_n"), min_n)
    return min_n, max_n


def _ngram_min_freq(value: Any) -> int:
    """Validate the N-gram frequency floor used before ranking.

    The UI exposes this as ``Mindestfrequenz``.  Applying it only after a
    top-N result has been selected can hide valid high-difference candidates
    behind low-frequency rows, so the route resolves it before either
    frequency or contrast runner ranks candidates.
    """
    return _safe_positive_int(
        value,
        name="min_freq",
        default=1,
        max_value=2_147_483_647,
    )


def _frequency_diff_min_freq(value: Any) -> int:
    """Validate the exact frequency-contrast floor before full ranking."""
    return _safe_positive_int(
        value,
        name="min_freq",
        default=1,
        max_value=2_147_483_647,
    )


def _collocate_attribute(value: Any) -> str:
    """Validate the collocation counting attribute (``word`` | ``lemma``)."""
    key = str(value or "word").strip().lower()
    if key not in {"word", "lemma"}:
        raise ApiError(
            422,
            "collocation.attribute_invalid",
            lt("attribute muss 'word' oder 'lemma' sein", "attribute must be 'word' or 'lemma'"),
        )
    return key


def _require_lemma_attribute(idx: Any) -> None:
    """Reject ``attribute=lemma`` with a capability hint when the index lacks it.

    A usable lemma layer needs BOTH a non-empty lemma lexicon and lemma
    postings (``token_attributes.lemma``). Raising 422 here keeps the error a
    caller-side capability message instead of a leaked engine RuntimeError.
    """
    fast_index = getattr(idx, "fast_index", None)
    lex = None
    try:
        lex = fast_index._lexicon_for_attr("lemma") if fast_index is not None else None
    except Exception:
        lex = None
    token_store = getattr(fast_index, "token_store", None)
    try:
        has_postings = bool(token_store.has_lemma_postings()) if token_store is not None else False
    except Exception:
        has_postings = False
    if lex is None or int(getattr(lex, "vocab_size", 0) or 0) <= 0 or not has_postings:
        raise ApiError(
            422,
            "collocation.lemma_unavailable",
            lt(
                "attribute=lemma ist für dieses Korpus nicht verfügbar: das "
                "Korpus-Feature token_attributes.lemma fehlt (kein Lemma-Lexikon "
                "oder keine Lemma-Postings im Index). attribute=word bleibt "
                "nutzbar; für Lemma-Kollokationen den Index mit Lemma-Annotation "
                "neu bauen.",
                "attribute=lemma is not available for this corpus: the corpus "
                "feature token_attributes.lemma is missing (no lemma lexicon or no "
                "lemma postings in the index). attribute=word remains usable. For "
                "lemma collocations, rebuild the index with lemma annotation.",
            ),
        )


def _identity_lemma(value: str) -> str:
    """Identity 'lemmatizer' for attribute=lemma.

    The tools-level seam selects the lemma counting column via the presence of
    a lemmatizer callable. The REST contract treats the entered term as ALREADY
    being a lemma, so the term itself must pass through unchanged.
    """
    return value


def _collocate_min_freq(value: Any) -> int:
    """Validate the collocates ``min_freq`` query param (FT id 5/6).

    ``None`` -> 0 (no extra filtering beyond the engine's hidden floor). A
    non-integer or negative value is a validation error (422); never a silent
    no-op. The returned value is applied as a route-level post-filter that drops
    rows with co-occurrence frequency ``f`` below it.
    """
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="min_freq must be an integer") from exc
    if parsed < 0:
        raise HTTPException(status_code=422, detail="min_freq must be >= 0")
    return parsed


# WORD_SKETCH_DEFAULT_MIN_FREQ is the ONE reliability floor (FT id 7), imported
# above from analysis_defaults so the REST profile, the copilot word_sketch tool
# and the /wordsketch_diff path all read the SAME constant — it removes f=1/f=2
# hapaxes (typos, list bullets) that otherwise dominate the default ranking with
# inflated single-cell chi2 scores.


def _word_sketch_min_freq(value: Any) -> int:
    """Validate the wordsketch ``min_freq`` (FT id 6/7).

    ``None`` -> :data:`WORD_SKETCH_DEFAULT_MIN_FREQ` (3). A client opts out with
    ``min_freq: 0``. Negative or non-integer values are a validation error
    (422) — the param must never be a silent no-op (the prior behaviour the
    audit flagged: ``min_freq`` accepted but ignored).
    """
    if value is None:
        return int(WORD_SKETCH_DEFAULT_MIN_FREQ)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="min_freq must be an integer") from exc
    if parsed < 0:
        raise HTTPException(status_code=422, detail="min_freq must be >= 0")
    return parsed


def _word_sketch_rank_rows(rows: list[dict[str, Any]], *, min_freq: int) -> list[dict[str, Any]]:
    """Drop low-frequency wordsketch rows and re-rank by a robust measure (FT id 7).

    1. Drop every row whose co-occurrence frequency ``f`` is below ``min_freq``
       (the default floor of 3 removes hapaxes/typos/list bullets).
    2. Re-rank the survivors by the most FREQUENCY-ROBUST field present: prefer
       an explicit ``logdice``/``logDice`` if the rows ever carry one; otherwise
       fall back to the signed Dunning ``ll_signed`` (the statistic the engine
       already sorts on) rather than the fragile single-cell ``chi2_cell``.
    3. Renumber ``rank`` 1..N over the survivors.

    Operates on the already-serialised row dicts so it is route-level and
    frame-shape-agnostic.
    """
    if not rows:
        return rows
    if min_freq > 0:
        kept: list[dict[str, Any]] = []
        for row in rows:
            try:
                f_val = int(row.get("f", 0))
            except (TypeError, ValueError):
                f_val = 0
            if f_val >= int(min_freq):
                kept.append(row)
        rows = kept
    if not rows:
        return rows

    # Most frequency-robust ranking field available on the rows.
    rank_key = None
    for candidate in ("logdice", "logDice", "ll_signed", "ll"):
        if candidate in rows[0]:
            rank_key = candidate
            break

    if rank_key is not None:
        def _score(row: dict[str, Any]) -> float:
            try:
                value = float(row.get(rank_key))
            except (TypeError, ValueError):
                return float("-inf")
            if value != value:  # NaN
                return float("-inf")
            return value

        rows = sorted(rows, key=_score, reverse=True)

    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def _word_sketch_all_rows_from_frame(frame: Any, _server: Any) -> list[dict[str, Any]]:
    """Serialise a normalized relation frame without applying a display cap."""
    if frame is None:
        return []
    if hasattr(frame, "to_dicts"):
        rows = frame.to_dicts()
    elif hasattr(frame, "to_dict"):
        rows = frame.to_dict("records")
    else:
        rows = []
    return [
        {key: _server._sanitize_float(value) for key, value in dict(row).items()}
        for row in rows
    ]


# Keyness sort keys a caller may request (FT id 8). Each maps to the response
# row field the rows are re-ordered by (descending).
_KEYNESS_SORT_KEYS = {
    "ll_signed": "ll_signed",
    "ll": "ll",
    "chi2": "chi2",
    "chi2_signed": "chi2_signed",
    "chi2_cell": "chi2_cell",
    "log_ratio": "log_ratio",
    "bic": "bic",
}

# The analyst-token policy applied to the keyness dict-based paths (FT id 2),
# mirroring the policy frequency_list already advertises.
_FREQUENCY_FILTERED_TOKEN_POLICY = lt(
    "Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen",
    "Empty values, values without alphanumeric characters and |marker| values are excluded",
)
_KEYNESS_FILTERED_TOKEN_POLICY = lt(
    "Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen "
    "(gleiche Analyst-Token-Politik wie frequency_list)",
    "Empty values, values without alphanumeric characters and |marker| values "
    "are excluded (same word-token policy as frequency_list)",
)


def _keyness_sort(value: Any) -> str:
    """Validate the keyness ``sort`` param (FT id 8); 422 on an unknown key.

    Defaults to ``ll_signed`` (the documented default_sort). The prior behaviour
    the audit flagged was a silently-ignored ``sort`` param; we now both reject
    unknown keys AND actually re-order the rows by the requested key.
    """
    raw = str(value if value is not None else "ll_signed").strip().lower()
    if not raw:
        raw = "ll_signed"
    if raw in {"mi2", "mi2_signed"}:
        raise ApiError(
            422,
            "keyness.sort_mi2_replaced",
            lt("sort=mi2 wurde durch sort=chi2_cell ersetzt.", "sort=mi2 has been replaced by sort=chi2_cell."),
        )
    if raw not in _KEYNESS_SORT_KEYS:
        raise ApiError(
            422,
            "keyness.sort_invalid",
            lt("sort muss eines von {allowed} sein", "sort must be one of {allowed}"),
            allowed=sorted(_KEYNESS_SORT_KEYS),
        )
    return raw


def _apply_keyness_sort(rows: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    """Re-order keyness result rows by the requested sort key, descending.

    Route-level re-sort of the materialised rows (FT id 8) for the dict-based
    keyness paths (corpus-vs-corpus, whole/corpus, freqlist, wordlist) whose
    underlying compute always emits a single default order. Rows missing the
    field sort last. Used BEFORE paging on the synchronous paths.
    """
    field = _KEYNESS_SORT_KEYS.get(sort_key, "ll_signed")

    def _score(row: dict[str, Any]) -> float:
        value = row.get(field)
        try:
            num = float(value)
        except (TypeError, ValueError):
            return float("-inf")
        if num != num:  # NaN
            return float("-inf")
        return num

    return sorted(rows, key=_score, reverse=True)


def _filter_keyness_freq_map(freq_map: dict[str, int]) -> dict[str, int]:
    """Drop non-analyst-token keys from a keyness frequency map (FT id 2).

    Removes newline/punctuation/empty/``|marker|`` tokens BEFORE the keyness
    math runs, so ``\\n`` / ``:`` / ``,`` no longer headline the ranking — the
    same token policy frequency_list applies. (Alnum template tokens like
    ``Assistant``/``END_OF_DOCUMENT`` are a corpus-build contamination, NOT
    something this lexical filter removes; that is flagged separately.)
    """
    return {word: count for word, count in freq_map.items() if is_analyst_token(word)}


def _semantic_level(value: Any) -> SemanticLevel:
    raw = str(value or "doc").strip().lower()
    if raw in {"", "doc", "document"}:
        return "doc"
    if raw in {"sentence", "sent"}:
        return "sentence"
    raise HTTPException(status_code=422, detail=f"Unsupported semantic level: {value}")


def _semantic_error_detail(
    *,
    code: str,
    message: str,
    backend: str | None = None,
    level: str | None = None,
    faiss_status: str | None = None,
    missing_assets: tuple[str, ...] = (),
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if backend is not None:
        detail["backend"] = backend
    if level is not None:
        detail["level"] = level
    if faiss_status:
        detail["faissStatus"] = faiss_status
    if missing_assets:
        detail["missingAssets"] = list(missing_assets)
    return detail


def _semantic_faiss_status(server_module: Any) -> str | None:
    manager_obj = getattr(getattr(server_module, "manager", None), "_manager", None)
    if manager_obj is None:
        return None
    value = getattr(manager_obj, "faiss_status", None)
    return str(value) if value else None


def _semantic_runtime_error_detail(
    exc: RuntimeError,
    *,
    backend: str | None,
    level: str,
    faiss_status: str | None,
) -> dict[str, Any] | None:
    message = exception_text(exc)
    lowered = str(exc).lower()
    if "faiss" in lowered and ("fehl" in lowered or "missing" in lowered or "not found" in lowered):
        return _semantic_error_detail(
            code="semantic_index_missing",
            message=message,
            backend=backend,
            level=level,
            faiss_status=faiss_status,
        )
    if "embedding" in lowered or "faiss" in lowered or "deaktiviert" in lowered:
        return _semantic_error_detail(
            code="semantic_runtime_error",
            message=message,
            backend=backend,
            level=level,
            faiss_status=faiss_status,
        )
    return None


def _fallback_semantic_meta(
    *,
    status: Any,
    level: str,
    top_n: int,
    ctx: int,
    rows: list[dict],
    docset_ids: set[int] | None,
) -> dict[str, Any]:
    return {
        "exactness": "unknown",
        "candidateGeneration": {
            "backend": getattr(status, "backend", None),
            "level": level,
            "method": "semantic_search",
            "searchMode": "unknown",
            "requestedTopN": int(top_n),
            "requestedContext": int(ctx),
            "candidateCount": len(rows),
        },
        "rerank": {
            "enabled": True,
            "method": "semantic_search_service",
            "outputCount": len(rows),
        },
        "filtering": {
            "docsetApplied": docset_ids is not None,
            "docsetDocCount": len(docset_ids) if docset_ids is not None else None,
        },
    }


def _coerce_semantic_search_output(
    result: Any,
    *,
    status: Any,
    level: str,
    top_n: int,
    ctx: int,
    docset_ids: set[int] | None,
) -> tuple[list[dict], dict[str, Any]]:
    rows: list[dict]
    meta: dict[str, Any] | None = None
    if isinstance(result, tuple) and len(result) == 2:
        rows_raw, meta_raw = result
        rows = list(rows_raw or [])
        if isinstance(meta_raw, dict):
            meta = dict(meta_raw)
    elif isinstance(result, dict) and "rows" in result:
        rows = list(result.get("rows") or [])
        meta_raw = result.get("meta")
        if isinstance(meta_raw, dict):
            meta = dict(meta_raw)
    else:
        rows = list(result or [])
    if meta is None:
        meta = _fallback_semantic_meta(
            status=status,
            level=level,
            top_n=top_n,
            ctx=ctx,
            rows=rows,
            docset_ids=docset_ids,
        )
    return rows, meta


def _semantic_docset_ids(server_module: Any, docset_id: Any, corpus: Any) -> set[int] | None:
    if not docset_id:
        return None
    docset = server_module._get_docset(str(docset_id))
    expected_corpus = str(corpus or "default")
    if docset.get("corpus") != expected_corpus:
        raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
    doc_ids = docset.get("doc_ids")
    if doc_ids is None:
        raise ApiError(
            422, "docset.doc_ids_missing", lt("Docset ohne doc_ids", "Document set without doc_ids")
        )
    return {int(doc_id) for doc_id in doc_ids}



@router.get(
    "/analysis/meta_schema",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "schemaVersion": 1,
                        "corpus": "default",
                        "documentCount": 1200,
                        "indexFingerprint": "sha256:...",
                        "metadataSchemaHash": "sha256:...",
                        "fingerprintStrength": "structural_index_artifacts",
                        "metadataFields": [
                            {
                                "name": "genre",
                                "kind": "string",
                                "hasString": True,
                                "hasNumber": False,
                                "stringValueCount": 12,
                                "numericValueCount": 0,
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analysis_meta_schema(
    corpus: str | None = "default",
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> dict[str, Any]:
    """Return metadata schema evidence without loading or decoding corpus data."""
    from .. import server as _server

    _server._require_user_access(token)
    corpus_name, index_path = _server._resolve_meta_schema_index_path(corpus)
    return _server._build_meta_schema_fingerprint(index_path, corpus_name)


@router.post(
    "/analysis/meta_values",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"values": {"party": ["Democratic", "Republican"], "decade": ["1940s", "1950s"]}}
                }
            }
        }
    },
)
async def analysis_meta_values(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Query metadata fields",
                "value": {"fields": ["genre", "source"], "corpus": "default"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Return bounded metadata-value suggestions for requested fields."""
    from .. import server as _server

    _server._require_user_access(token)

    fields = payload.get("fields") or []
    corpus = payload.get("corpus")
    raw_filters = payload.get("filters") or {}
    raw_limit = payload.get("limit", 250)
    if not isinstance(fields, list):
        raise ApiError(422, "meta.fields_not_list", lt("fields muss Liste sein", "fields must be a list"))
    if raw_filters and not isinstance(raw_filters, dict):
        raise ApiError(422, "meta.filters_not_dict", lt("filters muss dict sein", "filters must be a dict"))
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or raw_limit < 1:
        raise ApiError(
            422,
            "meta.limit_invalid",
            lt("limit muss positive ganze Zahl sein", "limit must be a positive integer"),
        )
    # Metadata values drive select/datalist suggestions. Keep their response
    # bounded even when a corpus has one distinct value per document.
    limit = min(raw_limit, 1_000)
    idx = _server.get_corpus(corpus)

    def _canonicalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
        # Single source of truth for the legacy transform->prompting_method alias.
        from candyconc.core.meta_filters import translate_meta_field_aliases

        return translate_meta_field_aliases(filters)

    filters = _canonicalize_filters(raw_filters) if raw_filters else None
    values: dict[str, list[str]] = {}
    truncated_fields: list[str] = []
    for field in dict.fromkeys(str(field) for field in fields):
        # Ask for one extra item so the response can state honestly whether the
        # displayed suggestions are complete. The actual filtering endpoint
        # remains exact; only its picker values are bounded.
        candidates = idx.metadata_values(field, filters=filters, limit=limit + 1)
        if len(candidates) > limit:
            values[field] = candidates[:limit]
            truncated_fields.append(field)
        else:
            values[field] = candidates
    return {
        "values": values,
        "truncated_fields": truncated_fields,
        "limit": limit,
    }


@router.post(
    "/analysis/meta_counts",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"counts": {"genre": {"news": 120, "blog": 42}}}
                }
            }
        }
    },
)
async def analysis_meta_counts(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Metadata fields with counts",
                "value": {"fields": ["genre", "source"], "corpus": "default"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Return metadata value counts for requested fields."""
    from .. import server as _server

    _server._require_user_access(token)

    fields = payload.get("fields") or []
    corpus = payload.get("corpus")
    raw_filters = payload.get("filters") or {}
    if not isinstance(fields, list):
        raise ApiError(422, "meta.fields_not_list", lt("fields muss Liste sein", "fields must be a list"))
    if raw_filters and not isinstance(raw_filters, dict):
        raise ApiError(422, "meta.filters_not_dict", lt("filters muss dict sein", "filters must be a dict"))
    idx = _server.get_corpus(corpus)

    def _canonicalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
        # Single source of truth for the legacy transform->prompting_method alias.
        from candyconc.core.meta_filters import translate_meta_field_aliases

        return translate_meta_field_aliases(filters)

    counts: dict[str, dict[str, int]] = {str(field): {} for field in fields}
    filters = _canonicalize_filters(raw_filters) if raw_filters else {}
    doc_meta = idx.fast_index.doc_metadata or {}
    # Vierte Naht, siehe server._search_docset_doc_ids: ein unbekanntes
    # Feld trifft nichts, in JEDE Richtung. Vorher lieferte
    # {'gibtsnicht': {'op':'!=','value':'x'}} hier die VOLLE Verteilung,
    # byte-gleich zur Kontrolle ohne Filter.
    from candyconc.core.meta_filters import (
        pruefe_filter_traegt_bedingung,
        unbekannte_felder,
    )

    # Fuenfte Naht derselben Klasse: {"split": ""} lieferte hier die VOLLE
    # Verteilung {'test': 683, 'train': 1317}, byte-gleich zum Aufruf ganz
    # ohne Filter, waehrend dieselbe Eingabe an der Docset-Naht warf. Die
    # Oberflaeche schickt unausgefuellte Felder als ``undefined`` und ist
    # davon nicht betroffen (KeynessTab.buildCountFilters,
    # SubcorpusPanel.buildAiFilters sieben Leerwerte beide aus).
    pruefe_filter_traegt_bedingung(raw_filters, fast_index=idx.fast_index)

    _unbekannt = bool(unbekannte_felder(idx.fast_index, filters or {}))

    for meta in doc_meta.values():
        if not isinstance(meta, dict):
            continue
        if _unbekannt:
            # Vierte Naht, siehe server._search_docset_doc_ids: ein
            # unbekanntes Feld trifft nichts, in JEDE Richtung. Vorher
            # lieferte {'gibtsnicht': {'op':'!=','value':'x'}} hier die
            # VOLLE Verteilung, byte-gleich zur Kontrolle ohne Filter.
            continue
        if filters and not _server._match_meta_filters(meta, filters):
            continue
        for field in fields:
            f = str(field)
            value = meta.get(f)
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    if item is None:
                        continue
                    s = str(item).strip()
                    if not s:
                        continue
                    counts[f][s] = counts[f].get(s, 0) + 1
            else:
                s = str(value).strip()
                if not s:
                    continue
                counts[f][s] = counts[f].get(s, 0) + 1

    return {"counts": counts}


@router.post(
    "/analysis/frequency_list/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_frequency_list_job(
    payload: Dict[str, Any] = Body(
        {},
        examples={
            "docset": {
                "summary": "Frequency list as a background job",
                "value": {
                    "corpus": "default",
                    "docset_id": "abcd1234",
                    "stopwords": "the,and,of",
                    "pos_prefix": "N",
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    corpus = payload.get("corpus")
    docset_id = payload.get("docset_id")
    pos_prefix = payload.get("pos_prefix")
    stopwords = _server._parse_stopwords(payload.get("stopwords"))
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    idx = _server.get_corpus(corpus)
    doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, docset_id)
    params = {
        "docset_id": docset_id or "",
        "stopwords": stopwords or [],
        "pos_prefix": pos_prefix or "",
        "doc_count": int(doc_ids.size),
        "row_limit": int(limit),
    }
    try:
        job = _server.analysis_jobs.create("frequency_list", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _server._run_frequency_job(
            job.job_id,
            corpus=corpus,
            doc_ids=doc_ids,
            stopwords=stopwords,
            pos_prefix=str(pos_prefix).strip() if pos_prefix else None,
            limit=limit,
        )
    )
    _server.analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


@router.post(
    "/analysis/frequency_diff/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_frequency_diff_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "default": {
                "summary": "Exact frequency contrast as a background job",
                "value": {
                    "target_docset_id": "a1b2c3",
                    "reference_docset_id": "d4e5f6",
                    "min_freq": 1,
                    "limit": 30,
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Launch an exact frequency-difference ranking for two disjoint docsets."""
    from .. import server as _server

    _server._require_user_access(token)
    corpus = payload.get("corpus")
    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    if not target_docset_id or not reference_docset_id:
        raise ApiError(
            422,
            "analysis.docset_pair_required",
            lt(
                "target_docset_id und reference_docset_id sind erforderlich",
                "target_docset_id and reference_docset_id are required",
            ),
        )
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    min_freq = _frequency_diff_min_freq(payload.get("min_freq"))
    idx = _server.get_corpus(corpus)
    target_doc_ids = _server._resolve_doc_ids_for_job(
        idx, corpus, str(target_docset_id)
    )
    reference_doc_ids = _server._resolve_doc_ids_for_job(
        idx, corpus, str(reference_docset_id)
    )
    target_doc_ids, reference_doc_ids = _keyness_disjoint_docsets(
        target_doc_ids, reference_doc_ids
    )
    if target_doc_ids.size == 0 or reference_doc_ids.size == 0:
        raise ApiError(
            422,
            "frequency_diff.empty_docset",
            lt(
                "Frequenzdifferenzen benötigen zwei nichtleere Docsets",
                "Frequency differences need two non-empty document sets",
            ),
        )
    params = {
        "target_docset_id": str(target_docset_id),
        "reference_docset_id": str(reference_docset_id),
        "min_freq": int(min_freq),
        "row_limit": int(limit),
        "target_doc_count": int(target_doc_ids.size),
        "reference_doc_count": int(reference_doc_ids.size),
    }
    try:
        job = _server.analysis_jobs.create("frequency_diff", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _server._run_frequency_diff_job(
            job.job_id,
            corpus=corpus,
            target_doc_ids=target_doc_ids,
            reference_doc_ids=reference_doc_ids,
            min_freq=min_freq,
            limit=limit,
        )
    )
    _server.analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


@router.get(
    "/analysis/jobs/{job_id}",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "kind": "frequency_list",
                        "status": "running",
                        "progress": 42,
                        "total_rows": None,
                    }
                }
            }
        }
    },
)
async def analysis_job_status(
    job_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    try:
        return _server.analysis_jobs.snapshot(job_id)
    except KeyError as exc:
        raise ApiError(404, "analysis_job.not_found", lt("Analysejob nicht gefunden", "Analysis job not found")) from exc


@router.post(
    "/analysis/jobs/{job_id}/cancel",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status": "cancelled",
                        "progress": 42,
                        "message": "cancelled",
                    }
                }
            }
        }
    },
)
async def analysis_job_cancel(
    job_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    try:
        _server.analysis_jobs.cancel(job_id)
        return _server.analysis_jobs.snapshot(job_id)
    except KeyError as exc:
        raise ApiError(404, "analysis_job.not_found", lt("Analysejob nicht gefunden", "Analysis job not found")) from exc


@router.get(
    "/analysis/jobs/{job_id}/rows",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status": "done",
                        "offset": 0,
                        "limit": 200,
                        "total_rows": 12345,
                        "rows": [{"word": "the", "f": 20907}],
                    }
                }
            }
        }
    },
)
async def analysis_job_rows(
    job_id: str,
    offset: int = 0,
    limit: int = 200,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    safe_offset = _server._bounded_offset(offset)
    safe_limit = _server._bounded_page_limit(limit)
    try:
        job = _server.analysis_jobs.get(job_id)
    except KeyError as exc:
        raise ApiError(404, "analysis_job.not_found", lt("Analysejob nicht gefunden", "Analysis job not found")) from exc
    snap = _server.analysis_jobs.snapshot(job_id)
    if job.status != "done":
        # Noch nicht fertig, aber Status zurückgeben.
        return {
            **snap,
            "offset": int(safe_offset),
            "limit": int(safe_limit),
            "rows": [],
        }
    if job.result is None:
        return {
            **snap,
            "offset": int(safe_offset),
            "limit": int(safe_limit),
            "total": job.total_rows,
            "truncated": False,
            "rows": [],
        }
    if job.kind == "frequency_list":
        idx = _server.get_corpus(job.corpus)
        rows = _server._frequency_rows_from_result(idx, job.result, offset=safe_offset, limit=safe_limit)
    elif job.kind == "keyness_docset":
        idx = _server.get_corpus(job.corpus)
        rows = _server._keyness_rows_from_result(idx, job.result, offset=safe_offset, limit=safe_limit)
    elif job.kind in {
        "keyness_external",
        "collocates",
        "collocates_diff",
        "frequency_diff",
        "ngrams",
        "ngrams_diff",
    }:
        rows = _server._rows_from_result_list(job.result, offset=safe_offset, limit=safe_limit)
    else:
        raise ApiError(
            422,
            "analysis_job.unknown_kind",
            lt("Unbekannter Analysejobtyp: {kind}", "Unknown analysis job type: {kind}"),
            kind=job.kind,
        )
    return {
        **snap,
        **_server._result_limit_meta(job.result),
        "offset": int(safe_offset),
        "limit": int(safe_limit),
        "rows": rows,
    }


@router.get(
    "/analysis/frequency_list",
    response_model=PagedFrequencyResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"rows": [{"word": "the", "f": 20907}]}
                }
            }
        }
    },
)
async def analysis_frequency_list(
    stopwords: str | None = None,
    use_gpu: str | None = None,
    corpus: str | None = None,
    docset_id: str | None = None,
    group_by: str = "word",
    pos: str | None = None,
    cql: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Frequency list of word forms, lemmas or part-of-speech tags.

    Parameters
    - stopwords: comma-separated forms that are removed from the output
    - use_gpu: optional hint for the GPU path
    - corpus: corpus name
    - docset_id: optional document set that restricts the count
    - pos: optional part-of-speech prefix (for example ``NOUN``). With
      ``group_by=word`` or ``group_by=lemma`` it returns the most frequent word
      forms or lemmas of this part of speech.

    Response
    - rows: list with word and f

    \f
    Häufigkeitsliste für Wortformen, Lemmata oder POS-Tags.

    Parameter
    - stopwords: Kommagetrennte Liste, die aus der Ausgabe entfernt wird
    - use_gpu: optionaler Hinweis für GPU Pfad
    - corpus: Korpusname
    - docset_id: optionaler Filter auf eine Teilmenge
    - pos: optionaler POS-Prefix-Filter (z. B. ``NOUN``). Mit
      ``group_by=word`` oder ``group_by=lemma`` belegt; liefert die häufigsten
      Wortformen bzw. Lemmata DIESER POS-Klasse über den indexierten
      POS-Tagstrom (FT id 15).

    Antwort
    - rows: Liste mit word und f
    """
    from .. import server as _server

    stop = None
    if stopwords:
        stop = [w for w in stopwords.split(",") if w]
    gpu = None
    if use_gpu is not None:
        gpu = use_gpu == "1"
    safe_offset = _server._bounded_offset(offset)
    safe_limit = _server._bounded_analysis_sync_limit(limit)
    group_by_norm = str(group_by or "word").strip().lower()
    if group_by_norm not in {"word", "lemma", "pos"}:
        raise ApiError(
            422,
            "frequency.group_by_invalid",
            lt("group_by muss word, lemma oder pos sein", "group_by must be word, lemma or pos"),
        )

    # FT id 15: honor the previously-silently-ignored `pos`/`cql` params instead
    # of dropping them. A `cql` frequency filter is not implemented on this
    # endpoint, so reject it explicitly rather than returning unfiltered counts.
    pos_prefix = str(pos).strip() if pos is not None and str(pos).strip() else None
    if cql is not None and str(cql).strip():
        raise ApiError(
            422,
            "frequency.cql_unsupported",
            lt(
                "cql wird auf /analysis/frequency_list nicht unterstützt; bitte pos verwenden oder /query nutzen",
                "cql is not supported on /analysis/frequency_list. Use pos or /query instead.",
            ),
        )
    if pos_prefix is not None and group_by_norm not in {"word", "lemma"}:
        raise ApiError(
            422,
            "frequency.pos_filter_group_by",
            lt(
                "pos-Filter ist nur mit group_by=word oder group_by=lemma belegt",
                "The pos filter is only supported with group_by=word or group_by=lemma",
            ),
        )

    idx = _server.get_corpus(corpus)
    doc_ids = None
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        doc_ids = docset.get("doc_ids")

    if pos_prefix is not None:
        # POS-filtered frequency goes through the index's pos-prefix path
        # (frequency_list_docset(..., pos_prefix=...)). When no docset is given we
        # resolve the full corpus doc id range so the whole corpus is covered.
        pos_doc_ids = doc_ids if doc_ids is not None else _server._resolve_doc_ids_for_job(idx, corpus, None)
        df = await asyncio.to_thread(
            idx.frequency_list_docset,
            np.asarray(pos_doc_ids, dtype=np.uint32),
            stopwords=stop,
            pos_prefix=pos_prefix,
            attr=group_by_norm,
        )
        df = filter_frequency_frame(df)
    else:
        # We need to pass the corpus index to the helper
        df = await asyncio.to_thread(
            _server._frequency_list,
            stopwords=stop,
            use_gpu=gpu,
            corpus=idx,
            doc_ids=doc_ids,
            group_by=group_by_norm,
        )
    rows = _server._rows_from_frame_page(df, offset=safe_offset, limit=safe_limit)
    try:
        total_candidates = int(len(df))
    except TypeError:
        total_candidates = len(rows)
    if group_by_norm == "pos":
        basis = "pos_tag_frequency"
        filtered_policy = lt(
            "POS-Tags werden über den indexierten Tokenstrom gezählt; "
            "Oberflächen-Token-Ausschlüsse sind aus gruppierten POS-Zeilen nicht ableitbar",
            "POS tags are counted over the indexed token stream. "
            "Surface token exclusions cannot be derived from grouped POS rows",
        )
    elif pos_prefix is not None:
        basis = f"pos_filtered_{group_by_norm}_frequency"
        filtered_policy = _FREQUENCY_FILTERED_TOKEN_POLICY
    else:
        basis = "analyst_token_frequency"
        filtered_policy = _FREQUENCY_FILTERED_TOKEN_POLICY
    result: Dict[str, Any] = {
        "rows": rows,
        "group_by": group_by_norm,
        "basis": basis,
        "filtered_token_policy": filtered_policy,
        **_server._bounded_result_meta(
            row_limit=safe_limit,
            total_candidates=total_candidates,
            offset=safe_offset,
        ),
    }
    if pos_prefix is not None:
        result["pos"] = pos_prefix
    # FT id 0: word/lemma counts are aggregated case-INSENSITIVELY (str.lower),
    # which mismatches a case-sensitive CQL [lemma="X"] count. Disclose the policy
    # (counting itself is unchanged) so a cross-check is possible.
    if group_by_norm in {"word", "lemma"}:
        result["case_policy"] = CASE_POLICY_GEFALTET
        result["label_policy"] = LABEL_POLICY_GEFALTET
    return result


@router.post(
    "/analysis/docset_from_meta",
    tags=["analysis"],
)
async def analysis_docset_from_meta(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "equality": {"summary": "Metadata filter without a search",
                         "value": {"corpus": "default", "filters": {"source": "news"}}},
            "range": {"summary": "Date or range filter",
                      "value": {"corpus": "default", "filters": {"year": {"op": "between", "lo": 2020, "hi": 2024}}}},
        },
    ),
) -> Dict[str, Any]:
    """Build a docset from metadata filters ALONE (no prior search required).

    Supports the op-tagged range/date shape ({'op':'>=','value':X} /
    {'op':'between','lo','hi'}). Additive: reuses the same read-only helpers as the
    search/intersection producers; the existing producers are untouched.
    """
    from .. import server as _server

    corpus = payload.get("corpus")
    raw_filters = payload.get("filters")
    if not isinstance(raw_filters, dict) or not raw_filters:
        raise ApiError(
            422, "docset.filters_missing", lt("filters fehlt oder leer", "filters is missing or empty")
        )
    idx = _server.get_corpus(corpus)
    doc_count = _server._doc_count_for_index(idx)
    from candyconc.core.meta_filters import EingabeFormFehler

    try:
        doc_ids = _server._doc_ids_from_meta(idx, raw_filters)
    except EingabeFormFehler:
        # Ein Formfehler der Aufruferin, und derselbe an allen Naehten. Der
        # lokale Fang machte daraus 422, waehrend meta_counts,
        # docset_from_search und meta_values fuer DIESELBE Eingabe 400
        # lieferten: ein gemeinsamer Waechter mit vier Antworten. Der
        # App-Handler (entrypoints/errors.py) bildet EingabeFormFehler auf
        # 400 ab, deshalb durchreichen statt umdeuten.
        raise
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
    docset_id = _server._store_docset(corpus, doc_ids, doc_count)
    result: Dict[str, Any] = {"docset_id": docset_id, "doc_count": int(doc_ids.size)}
    if payload.get("token_count"):
        try:
            result["token_count"] = int(idx.docset_token_count(doc_ids))
        except Exception:
            result["token_count"] = None
    return result


# ---------------------------------------------------------------------------
# T3 — Trend / Diachronie
# ---------------------------------------------------------------------------

# Leading year with an optional month part; anchored at the START of the value
# so a stray 4-digit number inside free text does not silently pass as a date.
_TREND_DATE_RE = re.compile(r"^\s*(\d{4})(?:[-/.](\d{1,2}))?")

# Two-sided 95% normal quantile (z_{0.975}); documented in the method block.
_TREND_CI_Z = 1.959963984540054

# Defensive ceiling: one hit-count runs per period, so an unbounded period set
# (e.g. per-day values under month granularity) must not DoS the endpoint.
_TREND_MAX_PERIODS = 500


def _trend_period_for_value(value: Any, granularity: str) -> str | None:
    """Parse a metadata date value into its period bucket.

    ``year``: leading YYYY. ``month``: leading YYYY-MM (separators -, /, .).
    Returns ``None`` when the value has no usable date for the granularity —
    those documents land in the explicit 'undatiert' bucket, never in a faked
    period.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    match = _TREND_DATE_RE.match(text)
    if match is None:
        return None
    year = match.group(1)
    if granularity == "year":
        return year
    month = match.group(2)
    if month is None:
        return None
    month_num = int(month)
    if month_num < 1 or month_num > 12:
        return None
    return f"{year}-{month_num:02d}"


def _trend_wilson_interval(hits: int, total: int) -> tuple[float, float]:
    """Wilson score interval (Wilson 1927) for the per-token rate p=hits/total.

    Returns ``(low, high)`` on the PROPORTION scale (caller scales to per
    million). ``hits=0`` yields ``low == 0.0`` exactly; ``total<=0`` degrades
    to ``(0, 0)``.
    """
    if total <= 0:
        return 0.0, 0.0
    n = float(total)
    p = float(hits) / n
    z = _TREND_CI_Z
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) / n) + z2 / (4.0 * n * n))) / denom
    return max(0.0, center - half), min(1.0, center + half)


@router.post("/analysis/trend", tags=["analysis"])
async def analysis_trend(
    payload: AnalysisTrendRequest = Body(
        ...,
        examples={
            "year": {
                "summary": "Yearly trend for a search term",
                "value": {
                    "query": "freedom",
                    "date_field": "date",
                    "granularity": "year",
                    "corpus": "default",
                },
            },
            "cql_month": {
                "summary": "Monthly trend for a CQL query",
                "value": {
                    "cql": "[pos=\"NOUN\"]",
                    "date_field": "date",
                    "granularity": "month",
                },
            },
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Frequency of a query over the values of a date field (diachronic trend).

    Request body
    - query or cql: search term or CQL query (cql gets the prefix cql: added)
    - date_field: metadata field with dates (for example 'date' or 'year')
    - granularity: 'year' or 'month'
    - docset_id, corpus: optional restriction

    Response
    - periods: [{period, hits, tokens, per_million, ci_low, ci_high}], only
      periods with documents (gaps are not filled with 0)
    - documents without a date that can be read go into the period 'undatiert'
      (last entry) and are named in warnings
    - method: provenance (family 'trend', Wilson interval)

    \f
    Frequenzverlauf einer Abfrage über ein Metadaten-Datumsfeld (Diachronie).

    Request-Body (Modell ist absichtlich permissiv, die handgeschriebenen
    422-Prüfungen unten bleiben die Validierungswahrheit)
    - query ODER cql: Suchbegriff bzw. CQL (cql wird automatisch geprefixt)
    - date_field: Metadatenfeld mit Datumswerten (z.B. 'date', 'year')
    - granularity: 'year' oder 'month'
    - docset_id, corpus: optionale Einschränkung

    Antwort
    - periods: [{period, hits, tokens, per_million, ci_low, ci_high}], nur
      Perioden mit Dokumenten (Lücken werden NICHT als 0 aufgefüllt). Mit
      period_values: true traegt jede datierte Periode zusaetzlich values,
      die Metadatenwerte des Datumsfelds, die sie bilden (ein
      Metadatenfilter auf genau diese Werte oeffnet ihre Treffer)
    - Dokumente ohne parsbares Datum landen im Bucket 'undatiert' (letzter
      Eintrag) und werden im Feld warnings ausgewiesen
    - method: Provenienz (family 'trend', Wilson-Intervall dokumentiert)
    """
    from .. import server as _server

    _server._require_user_access(token)

    payload = request_body_as_dict(payload)
    corpus = payload.get("corpus")
    raw_query = payload.get("query")
    raw_cql = payload.get("cql")
    if raw_query is not None and not str(raw_query).strip() and raw_cql is None:
        raw_query = None
    if raw_query is None and raw_cql is not None:
        cql_text = str(raw_cql).strip()
        raw_query = cql_text if cql_text.lower().startswith("cql:") else f"cql:{cql_text}"
    query_str = str(raw_query or "").strip()
    if not query_str:
        raise ApiError(422, "trend.query_missing", lt("query oder cql fehlt", "query or cql is missing"))

    date_field = str(payload.get("date_field") or "").strip()
    if not date_field:
        raise ApiError(422, "trend.date_field_missing", lt("date_field fehlt", "date_field is missing"))
    granularity = str(payload.get("granularity") or "year").strip().lower()
    if granularity not in {"year", "month"}:
        raise ApiError(
            422,
            "trend.granularity_invalid",
            lt("granularity muss 'year' oder 'month' sein", "granularity must be 'year' or 'month'"),
        )

    idx = _server.get_corpus(corpus)
    allowed_ids: set[int] | None = None
    docset_id = payload.get("docset_id")
    if docset_id:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        allowed_ids = {
            int(i) for i in np.asarray(docset.get("doc_ids"), dtype=np.int64).tolist()
        }

    # Dieselbe where()-Einschraenkung wie an der Copilot-Naht: ohne sie
    # zaehlt die Periode 262 Treffer gegen die Tokenzahl des GANZEN
    # Korpus. Die Copilot-Naht war dafuer schon repariert, diese nicht.
    from candyconc.core.meta_filters import where_dokumente

    _wo = where_dokumente(idx, query_str)
    if _wo is not None:
        _wo_ids = {int(i) for i in np.asarray(_wo, dtype=np.int64).tolist()}
        allowed_ids = _wo_ids if allowed_ids is None else (allowed_ids & _wo_ids)

    doc_count = _server._doc_count_for_index(idx)
    doc_meta = idx.fast_index.doc_metadata or {}

    groups: dict[str, list[int]] = {}
    # The metadata values behind each period, so that a client can open the
    # hits of one period with a metadata filter on exactly these values.
    period_values: dict[str, dict[str, Any]] = {}
    undated: list[int] = []
    field_seen = False
    for doc_idx in range(int(doc_count)):
        if allowed_ids is not None and doc_idx not in allowed_ids:
            continue
        meta = doc_meta.get(doc_idx, {}) or {}
        if not isinstance(meta, dict):
            meta = {}
        if date_field in meta:
            field_seen = True
        period = _trend_period_for_value(meta.get(date_field), granularity)
        if period is None:
            undated.append(doc_idx)
        else:
            groups.setdefault(period, []).append(doc_idx)
            raw_value = meta.get(date_field)
            period_values.setdefault(period, {})[f"{type(raw_value).__name__}:{raw_value}"] = raw_value

    # The field check above only sees the allowed documents. If the
    # selection is empty, no document is seen, field_seen stays False, and a
    # message would claim that the field does not exist in the CORPUS.
    # Example: a docset from where(split="test", [word="gibtsnichtxyz"]) has
    # 0 documents, and trend_analysis(date_field="split") would answer
    # "date_field 'split' existiert nicht in den Dokument-Metadaten dieses
    # Korpus", while split separates 683 test and 1317 training documents
    # there. A false statement about the corpus, caused by an empty
    # selection.
    #
    # The field therefore counts as known if ANY document of the corpus has
    # it, and the empty selection gets its own, true message.
    if not field_seen:
        im_korpus = any(
            isinstance(m, dict) and date_field in m
            for m in (doc_meta or {}).values()
        )
        if im_korpus:
            raise ApiError(
                422,
                "trend.selection_empty",
                lt(
                    "Die gewählte Dokumentmenge ist leer, deshalb gibt es "
                    "keine Periode fuer date_field '{date_field}'. Das Feld "
                    "existiert im Korpus.",
                    "The selected document set is empty, so there is no period "
                    "for date_field '{date_field}'. The field exists in the corpus.",
                ),
                date_field=date_field,
            )
        raise ApiError(
            422,
            "trend.date_field_unknown",
            lt(
                "date_field '{date_field}' existiert nicht in den "
                "Dokument-Metadaten dieses Korpus (siehe /analysis/meta_schema).",
                "date_field '{date_field}' does not exist in the document "
                "metadata of this corpus (see /analysis/meta_schema).",
            ),
            date_field=date_field,
        )
    if len(groups) > _TREND_MAX_PERIODS:
        raise ApiError(
            422,
            "trend.too_many_periods",
            lt(
                "Zu viele Perioden ({count} > {max_periods}); "
                "granularity='year' verwenden oder per docset_id einschränken.",
                "Too many periods ({count} > {max_periods}). "
                "Use granularity='year' or restrict with docset_id.",
            ),
            count=len(groups),
            max_periods=_TREND_MAX_PERIODS,
        )

    def _compute_trend() -> tuple[list[Dict[str, Any]], list[str]]:
        from candyconc.core.fast_index_native import docset_mask_from_ids

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
            # The same denominator as the copilot tool and keyness: the
            # analysis tokens of the period. The raw count is reported next
            # to it.
            from candyconc.candyconc_copilot.word_denominator import nenner as _wortnenner

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
        if payload.get("period_values"):
            for row in rows:
                row["values"] = sorted(period_values[row["period"]].values(), key=str)
        if undated:
            rows.append(_period_row("undatiert", undated))
            warnings.append(
                lt(
                    "{count} Dokument(e) ohne parsbaren Datumswert im Feld "
                    "'{date_field}' wurden dem Bucket 'undatiert' zugeordnet.",
                    "{count} document(s) without a parsable date value in field "
                    "'{date_field}' were assigned to the bucket 'undatiert'.",
                ).format(count=len(undated), date_field=date_field)
            )
        if partial_periods:
            warnings.append(
                lt(
                    "Trefferzählung unvollständig (Zähl-Limit erreicht) für Perioden: {periods}",
                    "Hit count incomplete (count limit reached) for periods: {periods}",
                ).format(periods=", ".join(partial_periods))
            )
        return rows, warnings

    periods, warnings = await _server._run_heavy_scan(_compute_trend)

    method = build_method_block(
        "trend",
        index_fingerprint=_index_fingerprint(idx),
        extra={
            "date_field": date_field,
            "granularity": granularity,
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
        "query": query_str,
        "date_field": date_field,
        "granularity": granularity,
        "periods": periods,
        "warnings": warnings,
        "method": method,
    }


def _version_side_values(idx: Any) -> str | list[str]:
    """``text_type`` values of the compared side of the pairs in ``idx``."""
    try:
        present = {str(value) for value in idx.metadata_values("text_type")}
    except Exception:
        present = set()
    values = sorted(value for value in present if is_version(value))
    if not values:
        return "ai"
    return values[0] if len(values) == 1 else values


@router.post(
    "/analysis/docset_intersection",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "intersection_count": 120,
                        "groups": [
                            {"label": "gpt", "docset_id": "a1", "doc_count": 120, "ref_count": 120},
                            {"label": "qwen", "docset_id": "b2", "doc_count": 120, "ref_count": 120},
                        ],
                    }
                }
            }
        }
    },
)
async def analysis_docset_intersection(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Intersection of shared references",
                "value": {
                    "groups": [
                        {"label": "gpt", "filters": {"text_type": "ai", "model": "gpt-oss-120b"}},
                        {"label": "qwen", "filters": {"text_type": "ai", "model": "qwen"}},
                    ],
                    "include_human": True,
                },
            }
        },
    ),
) -> Dict[str, Any]:
    """Return docset ids for groups restricted to shared reference docs."""
    from .. import server as _server

    corpus = payload.get("corpus")
    groups = payload.get("groups") or []
    include_human = bool(payload.get("include_human", False))
    if not isinstance(groups, list) or not groups:
        raise ApiError(
            422, "docset.groups_missing", lt("groups fehlt oder leer", "groups is missing or empty")
        )

    idx = _server.get_corpus(corpus)
    doc_count = _server._doc_count_for_index(idx)
    doc_meta = idx.fast_index.doc_metadata
    group_docs: list[dict[str, Any]] = []
    ref_sets: list[set[int]] = []

    for i, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ApiError(422, "docset.group_not_dict", lt("group muss dict sein", "group must be a dict"))
        label = str(group.get("label") or f"group_{i+1}")
        raw_filters = group.get("filters")
        if not isinstance(raw_filters, dict):
            raw_filters = {k: v for k, v in group.items() if k not in {"label", "filters"}}
        if "text_type" not in raw_filters:
            # Default: the compared side of the pairs. It is ``version`` in
            # paired imports and ``ai`` in older indexes and the human/AI
            # research layout. Only values present in the corpus are named.
            requested = payload.get("text_type")
            raw_filters["text_type"] = requested or _version_side_values(idx)
        doc_ids = _server._doc_ids_from_meta(idx, raw_filters)
        refs: set[int] = set()
        for doc_id in doc_ids:
            meta = doc_meta.get(int(doc_id), {})
            ref_doc = meta.get("ref_doc")
            if isinstance(ref_doc, str) and ref_doc.isdigit():
                ref_doc = int(ref_doc)
            if isinstance(ref_doc, int):
                refs.add(int(ref_doc))
        group_docs.append({"label": label, "doc_ids": doc_ids, "filters": raw_filters})
        ref_sets.append(refs)

    if not ref_sets:
        intersection: set[int] = set()
    else:
        intersection = set.intersection(*ref_sets) if ref_sets else set()

    response_groups: list[dict[str, Any]] = []
    for group in group_docs:
        doc_ids = group["doc_ids"]
        if intersection:
            kept: list[int] = []
            for doc_id in doc_ids:
                meta = doc_meta.get(int(doc_id), {})
                ref_doc = meta.get("ref_doc")
                if isinstance(ref_doc, str) and ref_doc.isdigit():
                    ref_doc = int(ref_doc)
                if isinstance(ref_doc, int) and int(ref_doc) in intersection:
                    kept.append(int(doc_id))
            kept_ids = np.asarray(kept, dtype=np.uint32)
        else:
            kept_ids = np.zeros(0, dtype=np.uint32)
        docset_id = _server._store_docset(corpus, kept_ids, doc_count)
        token_count = 0
        if kept_ids.size:
            try:
                token_count = int(await asyncio.to_thread(idx.docset_token_count, kept_ids))
            except Exception:
                token_count = 0
        response_groups.append(
            {
                "label": group["label"],
                "docset_id": docset_id,
                "doc_count": int(kept_ids.size),
                "ref_count": int(len(intersection)),
                "token_count": token_count,
            }
        )

    out: dict[str, Any] = {
        "intersection_count": int(len(intersection)),
        "groups": response_groups,
    }
    if include_human:
        human_ids = np.asarray(sorted(intersection), dtype=np.uint32)
        human_docset = _server._store_docset(corpus, human_ids, doc_count)
        human_token_count = 0
        if human_ids.size:
            try:
                human_token_count = int(await asyncio.to_thread(idx.docset_token_count, human_ids))
            except Exception:
                human_token_count = 0
        out["human"] = {
            "docset_id": human_docset,
            "doc_count": int(human_ids.size),
            "token_count": human_token_count,
        }
    return out


@router.post(
    "/analysis/parallel_groups",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "total": 120,
                        "groups": [
                            {
                                "ref_doc": 42,
                                "doc_count": 4,
                                "human_doc_id": 42,
                                "variant_doc_ids": [43, 44, 45],
                                "models": [{"model": "gpt-oss-120b", "count": 2}],
                                "sources": ["news"],
                                "label": "news/001.txt",
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analysis_parallel_groups(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Parallel groups for ref_doc IDs",
                "value": {"corpus": "default", "docset_id": "a1b2c3", "limit": 50},
            }
        },
    ),
) -> Dict[str, Any]:
    from .. import server as _server

    corpus = str(payload.get("corpus") or "default")
    docset_id = payload.get("docset_id") or payload.get("docsetId")
    raw_ref_doc = payload.get("ref_doc") if "ref_doc" in payload else payload.get("refDoc")
    requested_ref_doc: Optional[int] = None
    if raw_ref_doc is not None:
        try:
            requested_ref_doc = int(raw_ref_doc)
        except (TypeError, ValueError):
            raise ApiError(422, "parallel.ref_doc_not_int", lt("ref_doc muss int sein", "ref_doc must be an int")) from None
    include_all_variants = bool(payload.get("include_all_variants", True))
    sort = str(payload.get("sort") or "ref_doc")

    limit = _server._bounded_page_limit(payload.get("limit") or 50)
    offset = _server._bounded_offset(payload.get("offset"))

    idx = _server.get_corpus(corpus)
    _na = _server._paired_guard(idx, "parallel_groups")
    if _na is not None:
        return _na

    # Cheap docset validation stays on the loop so the error surfaces directly.
    raw_doc_ids = None
    if docset_id:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(
                422,
                "docset.other_corpus",
                lt("docset_id gehört zu anderem Korpus", "docset_id belongs to a different corpus"),
            )
        raw_doc_ids = _server._coerce_doc_ids(docset.get("doc_ids"))

    # Full-corpus scan + group summaries are CPU-bound; offload off the event loop.
    def _compute_parallel_groups() -> Dict[str, Any]:
        mapping = _server.resolve_pair_groups(idx, corpus, axis=None)
        docset_ids_set: set[int] | None = None

        if raw_doc_ids is not None:
            docset_ids_set = {int(doc_id) for doc_id in raw_doc_ids}

        if requested_ref_doc is not None:
            ref_docs = [int(requested_ref_doc)] if int(requested_ref_doc) in mapping else []
        elif raw_doc_ids is not None:

            reverse_map: dict[int, int] = {}
            for ref_doc, doc_ids in mapping.items():
                for doc_id in doc_ids:
                    reverse_map[int(doc_id)] = int(ref_doc)

            meta = idx.fast_index.doc_metadata or {}
            selected_ref_docs: set[int] = set()
            for doc_id in raw_doc_ids:
                ref_doc = reverse_map.get(int(doc_id))
                if ref_doc is None:
                    ref_doc = _server._parse_ref_doc_from_meta(meta.get(int(doc_id), {}), int(doc_id))
                if ref_doc is None:
                    continue
                selected_ref_docs.add(int(ref_doc))
            ref_docs = sorted(selected_ref_docs)
        else:
            ref_docs = list(mapping.keys())

        if sort == "variant_count":
            ref_docs.sort(key=lambda ref_doc: len(mapping.get(int(ref_doc), [])), reverse=True)
        else:
            ref_docs.sort()

        total = int(len(ref_docs))
        ref_docs = ref_docs[offset : offset + limit]

        groups: list[dict[str, Any]] = []
        for ref_doc in ref_docs:
            doc_ids = [int(doc_id) for doc_id in mapping.get(int(ref_doc), [])]
            if docset_ids_set is not None and not include_all_variants:
                doc_ids = [doc_id for doc_id in doc_ids if doc_id in docset_ids_set]
            groups.append(_server._parallel_group_summary(idx, int(ref_doc), doc_ids))

        return {"total": total, "groups": groups}

    # Run the full pair-group scan on the bounded pool so it cannot starve
    # small offloads on the default executor.
    return await _server._run_heavy_scan(_compute_parallel_groups)


@router.post(
    "/analysis/alignment/ref_doc",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "ref_doc": 42,
                        "corpus": "default",
                        "reference": {
                            "doc_id": 42,
                            "window_start": 10,
                            "window_end": 34,
                        },
                        "variants": [
                            {
                                "doc_id": 43,
                                "model": "openai/gpt-oss-120b",
                                "summary": {"avg_med": 6.2, "avg_similarity": 0.71},
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analysis_alignment_ref_doc(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "focused": {
                "summary": "Alignment around a hit position",
                "value": {
                    "corpus": "default",
                    "ref_doc": 128,
                    "focus_pos": 250000,
                    "window_sentences": 28,
                    "variant_margin": 6,
                    "max_variants": 6,
                },
            }
        },
    ),
) -> Dict[str, Any]:
    from .. import server as _server

    corpus = str(payload.get("corpus") or "default")
    raw_ref_doc = payload.get("ref_doc") if "ref_doc" in payload else payload.get("refDoc")
    if raw_ref_doc is None:
        raise ApiError(422, "parallel.ref_doc_missing", lt("ref_doc fehlt", "ref_doc is missing"))
    try:
        ref_doc = int(raw_ref_doc)
    except Exception:
        raise ApiError(422, "parallel.ref_doc_not_int", lt("ref_doc muss int sein", "ref_doc must be an int")) from None

    raw_focus = payload.get("focus_pos") if "focus_pos" in payload else payload.get("pos")
    focus_pos: Optional[int] = None
    if raw_focus is not None:
        try:
            focus_pos = int(raw_focus)
        except Exception:
            raise ApiError(
                422, "parallel.focus_pos_not_int", lt("focus_pos muss int sein", "focus_pos must be an int")
            ) from None

    window_sentences = int(payload.get("window_sentences") or 28)
    variant_margin = int(payload.get("variant_margin") or 6)
    max_variants = int(payload.get("max_variants") or 6)
    max_tokens = int(payload.get("max_tokens") or 512)
    # ``edit`` is the available lexical method. embed/hybrid require sentence
    # embeddings (not built yet) -> graceful not_applicable; unknown -> 400.
    alignment_method = str(payload.get("alignment_method") or "edit").lower()
    if alignment_method not in _server._ALIGNMENT_METHODS:
        raise ApiError(
            400,
            "alignment.method_unknown",
            lt("Unbekannte Alignment-Methode: {method!r}", "Unknown alignment method: {method!r}"),
            method=alignment_method,
        )

    # Compute budget guardrails
    window_sentences = max(8, min(window_sentences, 80))
    variant_margin = max(0, min(variant_margin, 12))
    max_variants = max(1, min(max_variants, 8))
    # Exact alignment never truncates a sentence to satisfy this budget. A
    # sentence above the requested ceiling returns an explicit not_applicable
    # envelope instead of an apparently precise prefix score.
    max_tokens = max(64, min(max_tokens, 2_048))

    raw_models = payload.get("include_models") or payload.get("models")
    include_models: Optional[list[str]] = None
    if raw_models:
        if isinstance(raw_models, str):
            include_models = [m.strip() for m in raw_models.split(",") if m and m.strip()]
        elif isinstance(raw_models, list):
            include_models = [str(m) for m in raw_models if m is not None and str(m)]

    raw_doc_ids = payload.get("include_doc_ids") or payload.get("includeDocIds")
    include_doc_ids: Optional[list[int]] = None
    if raw_doc_ids is not None:
        if not isinstance(raw_doc_ids, list):
            raise ApiError(
                422,
                "alignment.include_doc_ids_not_list",
                lt(
                    "include_doc_ids muss eine Liste von Dokument-IDs sein",
                    "include_doc_ids must be a list of document IDs",
                ),
            )
        try:
            include_doc_ids = [int(doc_id) for doc_id in raw_doc_ids]
        except (TypeError, ValueError):
            raise ApiError(
                422,
                "alignment.include_doc_ids_not_int",
                lt(
                    "include_doc_ids muss nur ganzzahlige Dokument-IDs enthalten",
                    "include_doc_ids must contain only integer document IDs",
                ),
            ) from None

    idx = _server.get_corpus(corpus)
    _na = _server._paired_guard(idx, "alignment_ref_doc")
    if _na is not None:
        return _na
    return await asyncio.to_thread(
        _server._alignment_for_ref_doc_sync,
        idx=idx,
        corpus=corpus,
        ref_doc=ref_doc,
        focus_pos=focus_pos,
        window_sentences=window_sentences,
        variant_margin=variant_margin,
        include_models=include_models,
        max_variants=max_variants,
        max_tokens=max_tokens,
        include_doc_ids=include_doc_ids,
        method=alignment_method,
    )


@router.post(
    "/analysis/docset_from_search",
    response_model=DocsetFromSearchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "docset_id": "a1b2c3",
                        "doc_count": 1200,
                        "hit_doc_count": 600,
                        "ref_doc_count": 580,
                    }
                }
            }
        }
    },
)
async def analysis_docset_from_search(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "simple": {
                "summary": "Document set from a query",
                "value": {"query": "cql:[lemma=\"gehen\"]", "limit": 2000},
            },
            "with_filters": {
                "summary": "Document set from metadata filters",
                "value": {
                    "query": "energy",
                    "meta_filters": {"genre": "news"},
                    "ai_filters": {"model": "gpt-oss-120b"},
                    "include_ai": True,
                    "include_human": True,
                },
            },
        },
    ),
) -> Dict[str, Any]:
    """Document set from the documents with hits of a query, optionally with their version families.

    Input
    - query: search expression, CQL with the prefix cql:
    - limit: maximum number of hits
    - include_ai, include_human: which sides the document set may contain
    - ai_filters, meta_filters: optional metadata filters. Every document of the
      set meets meta_filters, every AI document also ai_filters.
    - familien (default true): adds the reference documents of the documents with
      hits and their AI versions, also without a hit of their own. false returns
      exactly the documents with hits.

    Response
    - docset_id, doc_count, token_count
    - familien: whether families were added
    - hit_doc_count: documents of the set with a hit of their own. doc_count minus
      hit_doc_count are the documents added through families.
    - ref_doc_count: reference documents whose families were added

    \f
    Docset aus Suchtreffern, auf Wunsch samt ihren Fassungsfamilien.

    Eingabe
    - query: Suchausdruck, optional CQL mit Prefix cql:
    - limit: Maximale Anzahl Treffer
    - include_ai, include_human: welche Seiten das Docset enthalten darf
    - ai_filters, meta_filters: optionale Metadatenfilter. Jedes Dokument im
      Docset erfüllt meta_filters, jedes KI-Dokument zusätzlich ai_filters.
    - familien (Voreinstellung true): ergänzt zu den Trefferdokumenten ihre
      Referenzdokumente und deren KI-Fassungen, auch ohne eigenen Treffer.
      false liefert genau die Trefferdokumente, wie create_docset im Copilot.

    Antwort
    - docset_id, doc_count, token_count
    - familien: ob Familien ergänzt wurden
    - hit_doc_count: Dokumente des Docsets mit eigenem Treffer. doc_count
      minus hit_doc_count sind die über Familien ergänzten Dokumente.
    - ref_doc_count: Referenzdokumente, deren Familien ergänzt wurden
    """
    from .. import server as _server

    corpus = payload.get("corpus")
    query = str(payload.get("query") or "").strip()
    include_ai = bool(payload.get("include_ai", True))
    include_human = bool(payload.get("include_human", True))
    # Familien sind die dokumentierte Aufgabe dieser Route, der Paarbaum
    # der Oberfläche baut damit Parallelvergleiche. Sie bleiben deshalb
    # Voreinstellung und stehen in der Antwort.
    familien = bool(payload.get("familien", True))
    ai_filters = payload.get("ai_filters") or {}
    meta_filters = payload.get("meta_filters") or {}
    # An omitted limit requests the complete hit scan. A default top-N cap
    # would produce a corpus prefix rather than the requested docset.
    _roh_limit = payload.get("limit")
    limit = (
        None if _roh_limit in (None, "")
        else _server._bounded_analysis_job_limit(_roh_limit)
    )
    if not query:
        raise ApiError(422, "query.missing", lt("query fehlt", "query is missing"))

    idx = _server.get_corpus(corpus)
    doc_count = _server._doc_count_for_index(idx)
    # Run the full scan on the bounded pool. Its worker count limits parallel
    # scans while leaving the default executor available for small offloads.
    scan_bericht: Dict[str, Any] = {}
    try:
        doc_ids, hit_doc_count, ref_doc_count = await _server._run_heavy_scan(
            _server._search_docset_doc_ids,
            idx, query,
            meta_filters=meta_filters, ai_filters=ai_filters,
            include_ai=include_ai, include_human=include_human, limit=limit,
            bericht=scan_bericht, familien=familien,
        )
    except ValueError as exc:
        # Both scope and metadata filter validation raise ValueError for invalid
        # input. Preserve the actionable error message.
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    docset_id = _server._store_docset(corpus, doc_ids, doc_count)
    token_count = 0
    if doc_ids.size:
        try:
            token_count = int(await asyncio.to_thread(idx.docset_token_count, doc_ids))
        except Exception:
            token_count = 0
    antwort: Dict[str, Any] = {
        "docset_id": docset_id,
        "hit_doc_count": int(hit_doc_count),
        "ref_doc_count": int(ref_doc_count),
        "doc_count": int(doc_ids.size),
        "token_count": token_count,
        "familien": familien,
    }
    # Eine Kappung darf sein, sie darf nur nicht schweigen. Ohne dieses
    # Feld sahen 1051 gekappte und 1995 vollstaendige Dokumente gleich
    # aus, und der Wiederherstellungspfad einer Subkorpus-Definition
    # loest immer ungedeckelt auf: dieselbe Abfrage, zwei Groessen.
    if scan_bericht.get("gekappt"):
        antwort["truncated"] = True
        antwort["scan_limit"] = int(limit) if limit is not None else None
        antwort["truncation_note"] = lt(
            "Der Trefferscan hat den Deckel von {limit} erreicht. Dieses Docset "
            "ist ein Präfix der Abfrage, kein vollständiger Korpusschnitt. "
            "Ohne limit löst dieselbe Abfrage vollständig auf, und genau "
            "das tut auch das Wiederherstellen einer gespeicherten "
            "Subkorpus-Definition.",
            "The hit scan reached the limit of {limit}. This document set "
            "is a prefix of the query, not a complete corpus selection. "
            "Without limit, the same query resolves completely, and restoring "
            "a saved subcorpus definition does exactly that.",
        ).format(limit=limit)
    return antwort


@router.post(
    "/analysis/ngrams",
    response_model=PagedNgramsResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"rows": [{"ngram": "of the", "freq": 340, "n": 2}]}
                }
            }
        }
    },
)
async def analysis_ngrams(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "bigrams": {
                "summary": "Bigrams",
                "value": {"min_n": 2, "max_n": 2, "limit": 50},
            },
            "docset": {
                "summary": "N-grams in a document set",
                "value": {"min_n": 1, "max_n": 3, "docset_id": "a1b2c3", "limit": 100},
            },
        },
    ),
) -> Dict[str, Any]:
    """N-gram frequencies for the corpus or a document set.

    Input
    - min_n, max_n: n-gram length
    - min_freq: minimum frequency before ranking
    - limit: number of results
    - docset_id: optional document set

    \f
    Ngram Häufigkeiten für Korpus oder Docset.

    Eingabe
    - min_n, max_n: Ngram Länge
    - min_freq: Mindestfrequenz vor dem Ranking
    - limit: Anzahl Ergebnisse
    - docset_id: optionaler Filter
    """
    from .. import server as _server

    corpus = payload.get("corpus")
    docset_id = payload.get("docset_id")
    min_n, max_n = _resolve_ngram_n(payload)
    min_freq = _ngram_min_freq(payload.get("min_freq"))
    limit = _server._bounded_analysis_sync_limit(payload.get("limit"), default=200)
    min_n, max_n = _server._validate_ngram_bounds(min_n, max_n)

    idx = _server.get_corpus(corpus)
    doc_ids = None
    if docset_id:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        doc_ids = docset.get("doc_ids")

    counts = await asyncio.to_thread(_server._ngram_counts, idx, doc_ids, min_n, max_n)
    lex = idx.fast_index.lexicons.word
    # Same analyst-token policy as frequency_list: keep an n-gram only when EVERY
    # constituent token is an analyst token, so punctuation, |LBR|/marker tokens
    # and emoji never headline the ranking. We filter the WHOLE candidate set
    # before taking the top-N (mirroring frequency_list, which paginates the
    # already-filtered frame) so the limit and total_candidates describe the
    # analyst-token basis rather than the raw token stream.
    analyst_candidates: list[tuple[tuple[int, ...], int, list[str]]] = []
    for key, count in counts.items():
        if int(count) < min_freq:
            continue
        words: list[str] = []
        for wid in key:
            word = lex.get_string(int(wid)) if lex else ""
            if not is_analyst_token(word):
                words = []
                break
            words.append(word)
        if not words:
            continue
        analyst_candidates.append((key, int(count), words))
    total_candidates = len(analyst_candidates)
    ranked_candidates = heapq.nsmallest(
        limit,
        analyst_candidates,
        key=lambda item: (-int(item[1]), tuple(int(token_id) for token_id in item[0])),
    )
    rows: list[dict[str, object]] = [
        {"ngram": " ".join(words), "freq": count, "n": len(key)}
        for key, count, words in ranked_candidates
    ]
    try:
        scope_total = int(await asyncio.to_thread(idx.docset_token_count, doc_ids)) if doc_ids is not None else int(idx.token_count())
    except Exception:
        scope_total = 0
    return {
        "rows": rows,
        "method": build_method_block(
            "ngrams",
            index_fingerprint=_index_fingerprint(idx),
            target_total=scope_total or None,
            extra={
                "min_n": int(min_n),
                "max_n": int(max_n),
                "min_freq": int(min_freq),
                "candidate_policy": "complete_analyst_token_universe_before_ranking",
                "tie_break": "token_id_ascending",
            },
        ),
        "min_freq": int(min_freq),
        **_server._bounded_result_meta(
            row_limit=limit,
            total_candidates=total_candidates,
        ),
    }


@router.post(
    "/analysis/ngrams/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_ngrams_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "default": {
                "summary": "N-grams as a background job",
                "value": {"min_n": 1, "max_n": 3, "docset_id": "a1b2c3"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    corpus = payload.get("corpus")
    docset_id = payload.get("docset_id")
    min_n, max_n = _resolve_ngram_n(payload)
    min_freq = _ngram_min_freq(payload.get("min_freq"))
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    min_n, max_n = _server._validate_ngram_bounds(min_n, max_n)
    idx = _server.get_corpus(corpus)
    doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, docset_id)
    params = {
        "docset_id": docset_id or "",
        "min_n": int(min_n),
        "max_n": int(max_n),
        "min_freq": int(min_freq),
        "doc_count": int(doc_ids.size),
        "row_limit": int(limit),
    }
    try:
        job = _server.analysis_jobs.create("ngrams", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _server._run_ngrams_job(
            job.job_id,
            corpus=corpus,
            doc_ids=doc_ids,
            min_n=min_n,
            max_n=max_n,
            min_freq=min_freq,
            limit=limit,
        )
    )
    _server.analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


@router.post(
    "/analysis/ngrams_diff/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_ngrams_diff_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "default": {
                "summary": "N-gram differences as a background job",
                "value": {
                    "target_docset_id": "a1b2c3",
                    "reference_docset_id": "d4e5f6",
                    "min_n": 2,
                    "max_n": 2,
                    "limit": 100,
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    corpus = payload.get("corpus")
    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    if not target_docset_id or not reference_docset_id:
        raise ApiError(422, "analysis.docset_pair_required", lt("target_docset_id und reference_docset_id sind erforderlich", "target_docset_id and reference_docset_id are required"))
    min_n, max_n = _resolve_ngram_n(payload)
    min_freq = _ngram_min_freq(payload.get("min_freq"))
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    idx = _server.get_corpus(corpus)
    target_doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, str(target_docset_id))
    reference_doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, str(reference_docset_id))
    params = {
        "target_docset_id": str(target_docset_id),
        "reference_docset_id": str(reference_docset_id),
        "min_n": int(min_n),
        "max_n": int(max_n),
        "min_freq": int(min_freq),
        "limit": int(limit),
        "row_limit": int(limit),
        "target_doc_count": int(target_doc_ids.size),
        "reference_doc_count": int(reference_doc_ids.size),
    }
    try:
        job = _server.analysis_jobs.create("ngrams_diff", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _server._run_ngrams_diff_job(
            job.job_id,
            corpus=corpus,
            target_doc_ids=target_doc_ids,
            reference_doc_ids=reference_doc_ids,
            min_n=min_n,
            max_n=max_n,
            min_freq=min_freq,
            limit=limit,
        )
    )
    _server.analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


@router.post(
    "/analysis/embedding_search",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "rows": [{"doc_id": 12, "score": 0.83, "text": "..." }],
                        "meta": {
                            "exactness": "approximate",
                            "candidateGeneration": {"method": "faiss_passage", "searchMode": "approximate"},
                            "rerank": {"enabled": True, "method": "lexical_overlap_then_vector_score"},
                            "filtering": {"docsetApplied": False},
                        },
                    }
                }
            }
        }
    },
)
async def embedding_search_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Semantic passage search",
                "value": {"term": "energy policy", "top_n": 5, "ctx": 5},
            }
        },
    ),
) -> Dict[str, Any]:
    """Semantic passage search over embeddings.

    Input
    - term: search text
    - top_n: number of hits
    - ctx: context width

    \f
    Semantische Suche über Embeddings.

    Eingabe
    - term: Suchtext
    - top_n: Anzahl Treffer
    - ctx: Kontextfenster
    """
    from .. import server as _server

    term = (payload.get("term") or "").strip()
    top_n = _safe_positive_int(
        payload.get("top_n"),
        name="top_n",
        default=5,
        max_value=MAX_SEMANTIC_SEARCH_TOP_N,
    )
    ctx = _safe_positive_int(
        payload.get("ctx"),
        name="ctx",
        default=5,
        max_value=MAX_SEMANTIC_SEARCH_CTX,
    )
    docset_id = payload.get("docset_id")
    corpus = payload.get("corpus")
    backend = payload.get("backend") or payload.get("index") or payload.get("model")
    level = _semantic_level(payload.get("level"))
    if not term:
        raise HTTPException(status_code=422, detail="Missing term")

    idx = _server.get_corpus(corpus)
    index_path = getattr(getattr(idx, "fast_index", None), "index_path", None)
    docset_ids = _semantic_docset_ids(_server, docset_id, corpus)
    status = semantic_search_status(index_path, backend=backend, level=level)
    if not status.available:
        # DT-VERTRAEGE: an unsupported backend/level is an input-validation
        # error (the 422 class); a missing/unavailable index is a 503 state.
        status_code = 422 if status.code == "semantic_unsupported" else 503
        raise HTTPException(
            status_code=status_code,
            detail=_semantic_error_detail(
                code=status.code,
                message=status.message,
                backend=status.backend,
                level=status.level,
                faiss_status=_semantic_faiss_status(_server),
                missing_assets=status.missing_assets,
            ),
        )

    from candyconc.candyconc_copilot.analysis import semantic_search as _semantic_search

    corpus_key = str(corpus or "default").strip().lower()
    use_default_corpus = corpus_key in {"", "default"}
    try:
        semantic_result: Any = await asyncio.to_thread(
            _semantic_search,
            term,
            top_n=top_n,
            ctx=ctx,
            docset_doc_ids=docset_ids,
            corpus_index=idx,
            faiss_index=_server.manager.faiss_index_obj if use_default_corpus else None,
            passages=_server.manager.passages if use_default_corpus and _server.manager.passages else None,
            backend=status.backend,
            level=level,
            return_meta=True,
        )
    except RuntimeError as exc:
        detail = _semantic_runtime_error_detail(
            exc,
            backend=status.backend or (str(backend) if backend else None),
            level=level,
            faiss_status=_semantic_faiss_status(_server),
        )
        if detail is not None:
            raise HTTPException(status_code=503, detail=detail) from exc
        if docset_id:
            raise HTTPException(status_code=409, detail=exception_text(exc)) from exc
        raise HTTPException(status_code=503, detail=exception_text(exc)) from exc
    rows, meta = _coerce_semantic_search_output(
        semantic_result,
        status=status,
        level=level,
        top_n=top_n,
        ctx=ctx,
        docset_ids=docset_ids,
    )
    # ANALYSIS-DISTRIBUTIONAL-02: run each passage through the SAME display
    # normaliser the KWIC path uses so the index-only |LBR| marker never reaches
    # the UI (it covers the kw/text fields the semantic rows carry).
    from candyconc.services.backend.kwic_renderer import normalise_kwic_row_display

    rows = [normalise_kwic_row_display(row) for row in rows]
    return {"rows": rows, "meta": meta}


@router.get(
    "/analysis/collocates",
    response_model=PagedCollocatesResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {"rows": [{"word": "peace", "chi2_cell": 6.2, "t": 3.1, "rank": 1}]}
                }
            }
        }
    },
)
async def analysis_collocates(
    term: str,
    window: int = 5,
    within_sentence: bool = True,
    sort_by: str | None = None,
    min_freq: int | None = None,
    attribute: str = "word",
    corpus: str | None = None,
    docset_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Collocates in a window around the search term.

    Parameters
    - term: search term
    - window: window width to the left and right
    - min_freq: minimum co-occurrence frequency (>= 0). Rows with a co-frequency
      ``f`` below it are removed. Without a value the floor follows the node
      frequency: ``f >= 5`` for frequent nodes, down to ``f >= 2`` for rare nodes
      (``method.floor_mode = "adaptive"``, based on ``method.node_frequency``).
      Explicit values apply from 2 on the word, lemma and ``cql:`` paths.
      ``method.effective_min_cooccurrence`` names the floor the rows meet.
    - attribute: counting attribute 'word' (default) or 'lemma'. With 'lemma' the
      search term is read as a lemma and co-occurrences are counted over the
      lemma column. 422 with a capability hint when the corpus has no lemmas.
    - corpus, docset_id: optional filters

    Response
    - rows with measures such as chi2_cell, t, ll and rank

    """
    from .. import server as _server

    window = _server._validate_collocate_window(window)
    if str(sort_by or "").strip().lower() == "mi2":
        raise ApiError(
            422,
            "collocation.sort_mi2_replaced",
            lt(
                "sort_by=mi2 wurde durch sort_by=chi2_cell ersetzt.",
                "sort_by=mi2 has been replaced by sort_by=chi2_cell.",
            ),
        )
    attribute_key = _collocate_attribute(attribute)
    safe_offset = _server._bounded_offset(offset)
    safe_limit = _server._bounded_analysis_sync_limit(limit)
    # FT id 5/6: validate min_freq (int >= 0, 422 on negative/non-int) and apply
    # it as a route-level post-filter on the engine rows below.
    min_freq_value = _collocate_min_freq(min_freq)
    idx = _server.get_corpus(corpus)
    term = _collocation_node_term(_server, idx, term)
    doc_ids = None
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        doc_ids = docset.get("doc_ids")
    # Eine where()-Einschraenkung IM Term schraenkt den Knoten ein, das
    # Referenzuniversum blieb hier der ganze Korpus. Die Copilot-Naht war
    # dafuer schon repariert, diese nicht, und dieselbe Abfrage lieferte
    # zwei verschiedene Erwartungswerte:
    #     REST     erwartet 0,57, Referenz 56.191 Tokens, kein Scope
    #     Copilot  erwartet 1,10, Referenz 18.761 Tokens, docset/683
    # Ein Fix an einer von zwei Nahtstellen ist eine Verschiebung.
    from candyconc.core.meta_filters import where_dokumente

    _wo = where_dokumente(idx, term)
    if _wo is not None:
        doc_ids = (
            np.asarray(_wo, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_wo, dtype=np.uint32),
            )
        )
    try:
        from candyconc.tools.collocate_stats import (
            collocate_stats as _tools_collocate_stats,
        )

        if attribute_key == "lemma":
            # Lemma path: capability-gated, counted over the lemma column via the
            # shared tools seam (identity lemmatizer = term IS the lemma). The
            # word default below stays byte-identical to the historical path.
            _require_lemma_attribute(idx)
            df = await asyncio.to_thread(
                _tools_collocate_stats,
                term,
                window=window,
                lemmatizer=_identity_lemma,
                within_sentence=within_sentence,
                sort_by=sort_by,
                corpus=idx,
                doc_ids=doc_ids,
                # None calibrates the floor from node frequency. Explicit values take
                # precedence in the shared resolver.
                min_count=(min_freq_value or None),
            )
        else:
            # Pass min_freq through the shared candidate builder so REST and copilot
            # use the same floor. The CQL path derives node frequency from anchors
            # and exposes its applied calibration through df.attrs.
            df = await asyncio.to_thread(
                _server._collocate_stats_for_term,
                idx,
                term,
                window=window,
                within_sentence=within_sentence,
                sort_by=sort_by,
                doc_ids=doc_ids,
                min_count=(min_freq_value or None),
            )
    except (RuntimeError, ValueError) as exc:
        detail = str(exc)
        if "Docset-Frequenzen konnten nicht berechnet werden" in detail:
            raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
        # COLLOC-2: a malformed ``cql:`` term raises ParseError(ValueError); classify
        # it as the caller's fault (4xx) like /query, never a leaked 500.
        mapped = _server._classify_query_runtime_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    # Filter on the effective co-occurrence floor before paging so candidate
    # counts describe the returned set. Plain, lemma and CQL builders share
    # the adaptive resolver and expose the floor through df.attrs. The
    # fallback covers builder doubles without those attributes.
    frame_attrs = dict(getattr(df, "attrs", {}) or {})
    node_freq = frame_attrs.get("node_frequency")
    builder_floor = frame_attrs.get("effective_min_count")
    df = _server.normalize_default_collocate_frame(df, sort_by)
    desired_floor = adaptive_collocate_min_freq(node_freq, min_freq_value or None)
    if builder_floor is None:
        builder_floor = (
            int(COLLOCATE_COOCCURRENCE_FLOOR) if node_freq is None else int(desired_floor)
        )
    # The disclosed effective floor is the one the DATA actually honor: an
    # explicit min_freq can raise it further, but cannot recover rows the
    # candidate builder already dropped.
    effective_min_freq = max(int(desired_floor), int(builder_floor))
    # Resolve the floor mode for all builders through
    # analysis_defaults.collocate_floor_mode.
    floor_mode = collocate_floor_mode(
        min_freq_value, effective_min_freq, node_freq
    )
    df = filter_collocate_frame_by_min_freq(df, effective_min_freq)
    rows = _server._rows_from_frame_page(df, offset=safe_offset, limit=safe_limit)
    try:
        total_candidates = int(len(df))
    except TypeError:
        total_candidates = len(rows)

    sanitized_rows = [_sanitize_row(row) for row in rows]
    try:
        scope_total = int(await asyncio.to_thread(idx.docset_token_count, doc_ids)) if doc_ids is not None else int(idx.token_count())
    except Exception:
        scope_total = 0
    method = build_method_block(
        "collocates",
        index_fingerprint=_index_fingerprint(idx),
        target_total=scope_total or None,
        window=window,
        within_sentence=bool(within_sentence),
        sort_key=(str(sort_by).strip().lower() or None) if sort_by else None,
        # Report the effective floor and its origin: adaptive for node-frequency
        # calibration, requested for caller input, or default for builders without
        # calibration metadata. cooccurrence_floor names the default ceiling.
        extra=collocation_method_extra({
            "cooccurrence_floor": int(COLLOCATE_COOCCURRENCE_FLOOR),
            "min_freq": int(min_freq_value),
            "effective_min_cooccurrence": int(effective_min_freq),
            "floor_mode": floor_mode,
            **(
                {"node_frequency": int(node_freq)}
                if node_freq is not None
                else {}
            ),
            # Counting attribute provenance: 'word' (surface forms) or 'lemma'.
            "attribute": attribute_key,
            # R1, N and the LRC correction basis.
            **collocation_frame_provenance(frame_attrs),
        }),
    )
    return {
        "rows": sanitized_rows,
        "method": method,
        **_server._bounded_result_meta(
            row_limit=safe_limit,
            total_candidates=total_candidates,
            offset=safe_offset,
        ),
    }


def _bounded_network_nodes(value: Any) -> int:
    return _safe_positive_int(
        value,
        name="max_nodes",
        default=30,
        max_value=MAX_COLLOCATION_NETWORK_NODES,
    )


def _bounded_network_depth(value: Any) -> int:
    return _safe_positive_int(
        value,
        name="expand_depth",
        default=1,
        max_value=MAX_COLLOCATION_NETWORK_DEPTH,
    )


async def _compute_collocation_network(
    *,
    term: str,
    window: int,
    measure: str | None,
    max_nodes: int,
    expand_depth: int,
    min_count: int,
    within_sentence: bool,
    corpus: str | None,
    docset_id: str | None,
    attribute: str = "word",
) -> Dict[str, Any]:
    """Shared engine + corpus/docset resolution for the network endpoints."""
    from .. import server as _server
    from candyconc.tools.collocate_stats import (
        NETWORK_MEASURES,
        collocate_network_data,
    )

    term_str = (term or "").strip()
    if not term_str:
        raise ApiError(422, "collocation.term_missing", lt("term fehlt", "term is missing"))

    window = _server._validate_collocate_window(window)
    attribute_key = _collocate_attribute(attribute)
    measure_key = (measure or "logdice").strip().lower()
    if measure_key == "mi2":
        raise ApiError(
            422,
            "collocation.measure_mi2_replaced",
            lt(
                "measure=mi2 wurde durch measure=chi2_cell ersetzt.",
                "measure=mi2 has been replaced by measure=chi2_cell.",
            ),
        )
    if measure_key not in NETWORK_MEASURES:
        raise ApiError(
            422,
            "collocation.measure_invalid",
            lt("measure muss eines von {allowed} sein", "measure must be one of {allowed}"),
            allowed=sorted(NETWORK_MEASURES),
        )
    min_count_safe = _safe_positive_int(
        min_count, name="min_count", default=5, max_value=10_000
    )

    idx = _server.get_corpus(corpus)
    term_str = _collocation_node_term(_server, idx, term_str)
    if attribute_key == "lemma":
        _require_lemma_attribute(idx)
    doc_ids = None
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        doc_ids = docset.get("doc_ids")
    # Dieselbe Einschraenkung wie bei der Kollokationstabelle: der Knoten
    # folgt where(), das Referenzuniversum blieb hier der ganze Korpus.
    # Gemessen kippen dadurch nicht nur die Werte, sondern die
    # Knotenmenge selbst (drei von sieben tauschen).
    from candyconc.core.meta_filters import where_dokumente

    _wo = where_dokumente(_server.get_corpus(corpus), term_str)
    if _wo is not None:
        doc_ids = (
            np.asarray(_wo, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_wo, dtype=np.uint32),
            )
        )

    try:
        data = await asyncio.to_thread(
            collocate_network_data,
            term_str,
            window=window,
            measure=measure_key,
            max_nodes=max_nodes,
            expand_depth=expand_depth,
            min_count=min_count_safe,
            # Identity lemmatizer selects the lemma counting column; the seed
            # term is treated as already being a lemma (same contract as
            # /analysis/collocates?attribute=lemma).
            lemmatizer=_identity_lemma if attribute_key == "lemma" else None,
            corpus=idx,
            doc_ids=doc_ids,
            within_sentence=within_sentence,
        )
    except (RuntimeError, ValueError) as exc:
        detail = str(exc)
        if "Docset-Frequenzen konnten nicht berechnet werden" in detail:
            raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
        # COLLOC-2: a malformed ``cql:`` seed raises ParseError(ValueError); classify
        # it as the caller's fault (4xx) like /query, never a leaked 500.
        mapped = _server._classify_query_runtime_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    import math

    def _clean(value: Any) -> Any:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value

    edges = [
        {
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
            "weight": _clean(edge.get("weight")),
            "measure": str(edge.get("measure", measure_key)),
        }
        for edge in data.get("edges", [])
    ]
    return {
        "term": data.get("term", term_str),
        "measure": data.get("measure", measure_key),
        "nodes": data.get("nodes", []),
        "edges": edges,
        "diagnostics": data.get("diagnostics", {}),
        # Provenance for the network (collocates family): carries the edge-weight
        # statistics, default sort, fingerprint and the window/within_sentence
        # scope so the FE MethodPanel can render it like the other analyses.
        # ``target_total`` gehoert dazu: derselbe Block deklariert
        # ``event_total_definition: anchor_count_times_scope_tokens`` und
        # benannte damit eine Groesse, die die Antwort nirgends lieferte.
        # Die Route schraenkt ueber where() ein (siehe oben) und schwieg
        # darueber -- aus 26 statt 30 Knoten war nicht ablesbar, ob sie aus
        # 683 oder aus 2000 Dokumenten stammen.
        "method": build_method_block(
            "collocates",
            index_fingerprint=_index_fingerprint(idx),
            window=window,
            within_sentence=bool(within_sentence),
            sort_key=measure_key,
            target_total=(
                int(idx.token_count()) if doc_ids is None
                else int(idx.docset_token_count(doc_ids))
            ),
            extra=collocation_method_extra({"attribute": attribute_key}),
        ),
    }


_COLLOCATION_NETWORK_RESPONSES = {
    200: {
        "content": {
            "application/json": {
                "example": {
                    "term": "freedom",
                    "measure": "logdice",
                    "nodes": [
                        {"id": "freedom", "freq": None, "depth": 0},
                        {"id": "peace", "freq": 52, "depth": 1, "freq_via": "freedom"},
                    ],
                    "edges": [
                        {
                            "source": "freedom",
                            "target": "peace",
                            "weight": 10.5789,
                            "measure": "logdice",
                        }
                    ],
                    "diagnostics": {
                        "node_count": 2,
                        "edge_count": 1,
                        "first_order_count": 1,
                        "second_order_count": 0,
                        "expand_depth": 1,
                        "max_nodes": 2,
                        "window": 5,
                        "min_count": 5,
                        "truncated": False,
                    },
                }
            }
        }
    }
}


@router.get(
    "/analysis/collocation_network",
    response_model=CollocationNetworkResponse,
    responses=_COLLOCATION_NETWORK_RESPONSES,
)
async def analysis_collocation_network_get(
    term: str,
    window: int = 5,
    measure: str = "logdice",
    max_nodes: int = 30,
    expand_depth: int = 1,
    min_count: int = 5,
    within_sentence: bool = True,
    attribute: str = "word",
    corpus: str | None = None,
    docset_id: str | None = None,
) -> Dict[str, Any]:
    """Collocation network around a search term (nodes and edges).

    Parameters
    - term: search term (also CQL with the prefix cql:)
    - window: window width to the left and right
    - measure: edge weight (default logdice, also dice, mi, mi3, lmi, npmi, z, t,
      ll, chi2_cell)
    - max_nodes: maximum number of nodes (limited by the server)
    - expand_depth: 1 = star, 2 = ego network with second-order collocates (at
      most 2)
    - min_count: minimum co-occurrence frequency before ranking
    - attribute: counting attribute 'word' (default) or 'lemma' (422 with a
      capability hint when the corpus has no lemmas)
    - corpus, docset_id: optional filters

    Response
    - nodes with id, freq and depth, edges with source, target, weight and
      measure, diagnostics

    \f
    Kollokationsnetzwerk um einen Suchbegriff (Knoten + Kanten).

    Parameter
    - term: Suchbegriff (auch CQL mit Prefix cql:)
    - window: Fenstergröße links und rechts
    - measure: Kantengewicht-Maß (Default logdice; dice, mi, mi3, lmi, npmi, z, t, ll, chi2_cell)
    - max_nodes: Maximale Knotenzahl (serverseitig begrenzt)
    - expand_depth: 1=Stern, 2=Ego-Netz mit Kollokaten zweiter Ordnung (max 2)
    - min_count: Mindest-Ko-Frequenz vor Ranking
    - attribute: Zählattribut 'word' (Default) oder 'lemma' (422 mit
      Capability-Hinweis, wenn das Korpus kein Lemma-Attribut trägt)
    - corpus, docset_id: optionale Filter

    Antwort
    - nodes mit id/freq/depth, edges mit source/target/weight/measure, diagnostics
    """
    safe_nodes = _bounded_network_nodes(max_nodes)
    safe_depth = _bounded_network_depth(expand_depth)
    return await _compute_collocation_network(
        term=term,
        window=window,
        measure=measure,
        max_nodes=safe_nodes,
        expand_depth=safe_depth,
        min_count=min_count,
        within_sentence=within_sentence,
        corpus=corpus,
        docset_id=docset_id,
        attribute=attribute,
    )


@router.get(
    "/analysis/collocates/kwic",
    response_model=Dict[str, Any],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "rows": [
                            {
                                "left": "of religious tolerance, political",
                                "kw": "freedom",
                                "right": "and economic opportunity. For",
                                "pos": 1104,
                                "doc_id": 0,
                                "meta": {"president": "Harry S. Truman", "year": "1945"},
                            }
                        ],
                        "total": 1,
                        "next_offset": None,
                        "truncated": False,
                    }
                }
            }
        }
    },
)
async def analysis_collocates_kwic(
    term: str,
    collocate: str,
    window: int = 5,
    ctx: int = 5,
    limit: int = 500,
    offset: int = 0,
    within_sentence: bool = True,
    attribute: str = "word",
    corpus: str | None = None,
    docset_id: str | None = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
) -> Dict[str, Any]:
    """Concordance rows behind a collocation row.

    One row per node hit of ``term`` that has ``collocate`` inside its window
    ``[s - window, s)`` or ``[e, e + window)``, clipped at the document and,
    with ``within_sentence``, at the sentence. The node resolves like the
    collocation table (plain term: case-folded class on ``attribute``,
    ``cql:``: match spans), the collocate as the exact value on ``attribute``
    like a table row. ``collocate_tokens`` counts the collocate tokens in the
    union of all node windows, which is the row's O11. ``total`` counts rows
    (node hits), so the two numbers differ when windows overlap or one window
    holds the collocate twice.
    """
    from .. import server as _server
    from ..co_occurrence import co_occurrence, collocate_offsets, node_match_offsets

    attribute_key = _collocate_attribute(attribute)
    term = (term or "").strip()
    collocate = (collocate or "").strip()
    collocates = _server._split_collocate_terms(collocate)
    if not term or not collocates:
        raise ApiError(
            422,
            "collocation.term_and_collocate_required",
            lt("term und collocate sind erforderlich", "term and collocate are required"),
        )

    idx = _server.get_corpus(corpus)
    term = _collocation_node_term(_server, idx, term)
    if attribute_key == "lemma":
        _require_lemma_attribute(idx)
    fast = idx.fast_index
    window = _server._validate_collocate_window(int(window))
    ctx = max(1, min(int(ctx), 600))
    limit = _server._bounded_analysis_sync_limit(limit)
    offset = _server._bounded_offset(offset)

    def _result(rows: list, total: int, next_offset: int | None, node_hits: int, tokens: dict) -> Dict[str, Any]:
        return {
            "rows": rows,
            "total": int(total),
            "next_offset": next_offset,
            "truncated": next_offset is not None,
            "row_unit": "node_hit",
            "node_hits": int(node_hits),
            "collocate_tokens": {str(k): int(v) for k, v in tokens.items()},
            "attribute": attribute_key,
            "collocate_match": "exact",
            "node_match": "cql" if term.lower().startswith("cql:") else "case_folded",
            "window": int(window),
            "within_sentence": bool(within_sentence),
        }

    if int(fast.token_store.token_count) <= 0:
        return _result([], 0, None, 0, {c: 0 for c in collocates})

    doc_bounds = _server._doc_bounds_for_index(idx)
    docset_mask = None
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")
        if docset_mask is not None:
            docset_mask = np.asarray(docset_mask, dtype=np.bool_)
        else:
            doc_ids_raw = docset.get("doc_ids")
            doc_ids = np.asarray(doc_ids_raw if doc_ids_raw is not None else [], dtype=np.uint32)
            docset_mask = _server.docset_mask_from_ids(doc_ids, int(doc_bounds.size))

    try:
        co = await asyncio.to_thread(
            co_occurrence,
            idx,
            term,
            collocates,
            window=window,
            within_sentence=bool(within_sentence),
            attribute=attribute_key,
            docset_mask=docset_mask,
            doc_bounds=doc_bounds,
            match_limit=_server._ANALYSIS_MATCH_LIMIT,
        )
    except (RuntimeError, ValueError) as exc:
        # COLLOC-2: a malformed ``cql:`` term raises ParseError(ValueError);
        # classify it as the caller's fault (4xx) like /query, never a 500.
        mapped = _server._classify_query_runtime_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    co_positions_all = co.rows
    total = int(co_positions_all.size)
    if total == 0 or offset >= total:
        return _result([], total, None, co.node_hits, co.collocate_tokens)
    co_positions = co_positions_all[offset: offset + limit].astype(np.uint32, copy=False)
    offset_map = collocate_offsets(co, co_positions)
    match_offset_map = node_match_offsets(co, co_positions)

    rows = await asyncio.to_thread(
        fast.kwic_rows_for_positions,
        co_positions,
        int(ctx),
        False,
    )

    from candyconc.core.source_spacing import apply_source_spacing, display_flags
    from candyconc.services.backend.pii_filter import mask_pii

    # Original spacing when the index has whitespace_after.bin and masking is
    # off. Otherwise apply PII masking. Both enrich with document metadata.
    ws = display_flags(idx)
    for row in rows:
        pos = int(row.get("pos", -1))
        if pos < 0:
            continue
        offsets = offset_map.get(pos, [])
        if ws is not None:
            apply_source_spacing(row, ws)
        else:
            _mask_co_kwic_row(row, pos, idx, mask_pii)

        doc_id = _server._doc_id_for_position(idx, pos, doc_bounds)
        file_label = str(row.get("file") or "") or None
        doc_label, meta = _server._doc_meta_for_doc_id(idx, doc_id, file_label=file_label)
        row["doc_id"] = int(doc_id)
        row["doc"] = doc_label
        row["meta"] = meta
        row["collocate"] = collocate
        row["window"] = int(window)
        row["coll_offsets"] = [int(x) for x in offsets]
        row["match_offsets"] = match_offset_map.get(pos, [])

    next_offset = offset + int(co_positions.size)
    if next_offset >= total:
        next_offset = None
    return _result(rows, total, next_offset, co.node_hits, co.collocate_tokens)


def _mask_co_kwic_row(row: dict[str, Any], pos: int, idx: Any, mask_pii: Any) -> None:
    """PII masking of one Co-KWIC row (legacy space-joined text)."""
    left_tokens = str(row.get("left", "")).split()
    right_tokens = str(row.get("right", "")).split()
    left_raw = " ".join(left_tokens)
    right_raw = " ".join(right_tokens)
    row["left"] = (
        mask_pii(left_raw, start_pos=pos - len(left_tokens), index=idx, tokens=left_tokens)
        if left_raw
        else left_raw
    )
    row["kw"] = mask_pii(
        str(row.get("kw", "")),
        start_pos=pos,
        index=idx,
        tokens=str(row.get("kw", "")).split(),
    )
    row["right"] = (
        mask_pii(right_raw, start_pos=pos + 1, index=idx, tokens=right_tokens)
        if right_raw
        else right_raw
    )


@router.post(
    "/analysis/kwic_parallel",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "ref_doc": 42,
                        "base_doc_id": 42,
                        "variants": [
                            {
                                "doc_id": 43,
                                "model": "openai/gpt-oss-120b",
                                "prompting_method": "prompt_builder",
                                "text_type": "ai",
                                "left": "…",
                                "kw": "freedom",
                                "right": "…",
                                "matched": True,
                                "med": 5,
                                "norm_med": 0.21,
                                "similarity": 0.79,
                            }
                        ],
                    }
                }
            }
        }
    },
)
async def analysis_kwic_parallel(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Parallel KWIC lines for a hit position",
                "value": {
                    "pos": 123,
                    "keyword": "freedom",
                    "ctx": 6,
                    "max_variants": 3,
                },
            }
        },
    ),
) -> Dict[str, Any]:
    from .. import server as _server

    corpus = str(payload.get("corpus") or "default")
    raw_pos = payload.get("pos")
    if raw_pos is None:
        raise ApiError(422, "parallel.pos_missing", lt("pos fehlt", "pos is missing"))
    try:
        pos = int(raw_pos)
    except Exception:
        raise ApiError(422, "parallel.pos_not_int", lt("pos muss int sein", "pos must be an int")) from None

    ctx = max(1, _server._bounded_query_context(int(payload.get("ctx") or 6)))
    keyword = str(payload.get("keyword") or payload.get("kw") or "").strip()
    kw_tokens = _server._tokenize_kw(keyword)

    include_models = payload.get("include_models") or payload.get("models") or []
    models: list[str] = []
    if isinstance(include_models, str):
        models = [m.strip() for m in include_models.split(",") if m and m.strip()]
    elif isinstance(include_models, list):
        models = [str(m) for m in include_models if m is not None and str(m)]

    max_variants = int(payload.get("max_variants") or 3)
    max_variants = max(1, min(max_variants, 6))

    sentence_margin = int(payload.get("sentence_margin") or 6)
    sentence_margin = max(0, min(sentence_margin, 12))

    exclude_base = bool(payload.get("exclude_base", True))

    idx = _server.get_corpus(corpus)
    _na = _server._paired_guard(idx, "kwic_parallel")
    if _na is not None:
        return _na

    # Full-corpus pair scan + per-variant sentence matching is CPU-bound; offload it.
    def _compute_kwic_parallel() -> Dict[str, Any]:
        doc_bounds = _server._doc_bounds_for_index(idx)
        sentence_bounds = _server._sentence_bounds_for_index(idx)

        base_doc_id = _server._doc_id_for_position(idx, int(pos), doc_bounds)
        metadata_by_doc_id: dict[int, dict[str, str]] = {}

        def doc_meta_for(doc_id: int) -> dict[str, str]:
            """Read metadata through the index-neutral server accessor.

            Fast Indexes expose an mmap-backed ``Mapping`` in production, while
            small tests often use a plain dict.  The shared accessor supports
            both, so parallel KWIC must not narrow the implementation to dict.
            """
            normalized = int(doc_id)
            cached = metadata_by_doc_id.get(normalized)
            if cached is not None:
                return cached
            _label, meta = _server._doc_meta_for_doc_id(idx, normalized)
            metadata_by_doc_id[normalized] = meta
            return meta

        base_meta = doc_meta_for(int(base_doc_id))

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
            idx,
            int(base_doc_id),
            doc_bounds=doc_bounds,
            sentence_bounds=sentence_bounds,
        )
        focus_idx = _server._sentence_index_for_pos(base_bounds, int(pos))
        if focus_idx is None:
            focus_idx = 0 if base_bounds else 0
        base_sentence_list = _server._sentence_data_for_indices(idx, int(base_doc_id), base_bounds, [int(focus_idx)])
        if not base_sentence_list:
            return {"ref_doc": int(ref_doc), "base_doc_id": int(base_doc_id), "variants": []}
        base_sentence = base_sentence_list[0]

        mapping = _server.resolve_pair_groups(idx, corpus, axis=None)
        candidate_ids = [int(doc_id) for doc_id in mapping.get(int(ref_doc), [])]
        if exclude_base:
            candidate_ids = [doc_id for doc_id in candidate_ids if int(doc_id) != int(base_doc_id)]
        if models:
            candidate_ids = [
                doc_id
                for doc_id in candidate_ids
                if str(doc_meta_for(doc_id).get("model") or "") in models
            ]

        def _model_key(doc_id: int) -> tuple[int, str, int]:
            # The anchor of the pair first, then the versions by model.
            meta = doc_meta_for(doc_id)
            model = str(meta.get("model") or "")
            first = 0 if is_anchor(meta.get("text_type")) or model == "human" else 1
            return (first, model, int(doc_id))

        candidate_ids.sort(key=_model_key)
        if max_variants > 0:
            candidate_ids = candidate_ids[: int(max_variants)]

        variants: list[dict[str, Any]] = []
        for doc_id in candidate_ids:
            meta = doc_meta_for(doc_id)
            best_sentence, med, norm, sim = _server._best_matching_sentence(
                idx,
                ref_sentence=base_sentence,
                ref_index=int(focus_idx),
                doc_id=int(doc_id),
                doc_bounds=doc_bounds,
                sentence_bounds=sentence_bounds,
                margin=sentence_margin,
            )
            # Ohne Gegenstueck bleibt die Fassung sichtbar, als nicht ausgerichtet.
            kwic = _server._kwic_from_sentence(idx, best_sentence, kw_tokens=kw_tokens, ctx=ctx)
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
            "ref_doc": int(ref_doc),
            "base_doc_id": int(base_doc_id),
            "variants": variants,
        }

    # Run per-variant alignment and KWIC on the bounded heavy-scan pool.
    return await _server._run_heavy_scan(_compute_kwic_parallel)


@router.post(
    "/analysis/collocates/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_collocates_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "default": {
                "summary": "Collocates as a background job",
                "value": {"term": "freedom", "window": 5, "docset_id": "a1b2c3"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    term = str(payload.get("term") or "").strip()
    if not term:
        raise ApiError(422, "collocation.term_missing", lt("term fehlt", "term is missing"))
    collocate = str(payload.get("collocate") or "").strip()
    sort_by = str(payload.get("sort_by") or "").strip()
    if sort_by.lower() == "mi2":
        raise ApiError(
            422,
            "collocation.sort_mi2_replaced",
            lt(
                "sort_by=mi2 wurde durch sort_by=chi2_cell ersetzt.",
                "sort_by=mi2 has been replaced by sort_by=chi2_cell.",
            ),
        )
    window = _server._validate_collocate_window(int(payload.get("window", 5) or 5))
    min_freq_value = _collocate_min_freq(payload.get("min_freq"))
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    within_sentence = bool(payload.get("within_sentence", True))
    corpus = payload.get("corpus")
    docset_id = payload.get("docset_id")
    idx = _server.get_corpus(corpus)
    term = _collocation_node_term(_server, idx, term)
    doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, docset_id)
    # The job path must restrict the population like the synchronous route
    # and the copilot seam, which cut the where() documents into it, and the
    # job path is the one the UI takes. On a 56,000-token test index for
    # where(split="test", [word="und"]), same numerator (node_frequency 262,
    # 55 candidates), different denominator:
    #     synchronous  target_total 18761, expected 1.10, chi2 43.08
    #     job          target_total 56191, expected 0.57, chi2 96.21
    # The RANKING flips: rank 2 is "unsere" in one and "Welt" in the other.
    # The job declares event_total_definition
    # "anchor_count_times_scope_tokens" in the same method block and would
    # report the corpus value as scope tokens although it read 683 of 2000
    # documents.
    from candyconc.core.meta_filters import where_dokumente

    _wo_job = where_dokumente(idx, term)
    if _wo_job is not None:
        doc_ids = (
            np.asarray(_wo_job, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(
                np.asarray(doc_ids, dtype=np.uint32),
                np.asarray(_wo_job, dtype=np.uint32),
            )
        )
    params = {
        "term": term,
        "collocate": collocate,
        "window": int(window),
        "within_sentence": bool(within_sentence),
        "sort_by": sort_by,
        "min_freq": int(min_freq_value),
        "docset_id": docset_id or "",
        "doc_count": int(doc_ids.size),
        "row_limit": int(limit),
    }
    try:
        job = _server.analysis_jobs.create("collocates", corpus or "default", params)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
    task = asyncio.create_task(
        _server._run_collocates_job(
            job.job_id,
            corpus=corpus,
            term=term,
            collocate=collocate or None,
            window=window,
            within_sentence=within_sentence,
            sort_by=sort_by or None,
            doc_ids=doc_ids,
            limit=limit,
            min_freq=min_freq_value,
        )
    )
    _server.analysis_jobs.attach_task(job.job_id, task)
    return {
        "job_id": job.job_id,
        "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
        "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
        "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
    }


@router.post(
    "/analysis/collocates_diff/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_collocates_diff_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "default": {
                "summary": "Collocation differences as a background job",
                "value": {
                    "term": "freedom",
                    "target_docset_id": "a1b2c3",
                    "reference_docset_id": "d4e5f6",
                    "window": 5,
                    "within_sentence": True,
                    "sort_by": "dice",
                    "limit": 200,
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    term = str(payload.get("term") or "").strip()
    if not term:
        raise ApiError(422, "collocation.term_missing", lt("term fehlt", "term is missing"))
    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    if not target_docset_id or not reference_docset_id:
        raise ApiError(422, "analysis.docset_pair_required", lt("target_docset_id und reference_docset_id sind erforderlich", "target_docset_id and reference_docset_id are required"))
    sort_by = str(payload.get("sort_by") or "").strip()
    if sort_by.lower() == "mi2":
        raise ApiError(
            422,
            "collocation.sort_mi2_replaced",
            lt(
                "sort_by=mi2 wurde durch sort_by=chi2_cell ersetzt.",
                "sort_by=mi2 has been replaced by sort_by=chi2_cell.",
            ),
        )
    window = _server._validate_collocate_window(int(payload.get("window", 5) or 5))
    within_sentence = bool(payload.get("within_sentence", True))
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    corpus = payload.get("corpus")
    idx = _server.get_corpus(corpus)
    term = _collocation_node_term(_server, idx, term)
    target_doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, str(target_docset_id))
    reference_doc_ids = _server._resolve_doc_ids_for_job(idx, corpus, str(reference_docset_id))
    return _server._launch_collocates_diff(
        corpus, term, window=window, within_sentence=within_sentence,
        sort_by=sort_by, limit=limit,
        target_doc_ids=target_doc_ids, reference_doc_ids=reference_doc_ids,
        target_key=str(target_docset_id), reference_key=str(reference_docset_id),
    )


@router.post("/analysis/contrast", tags=["analysis"])
async def analysis_contrast(
    payload: Dict[str, Any] = Body(
        ...,
        examples={"subcorpora": {"summary": "Free contrast of two subcorpora (any corpus)",
                                 "value": {"term": "freedom", "target_subcorpus": "republican",
                                           "reference_subcorpus": "democratic"}}},
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Free contrast of two arbitrary docsets/subcorpora — works on ANY corpus
    (no human/AI pairing required). Each side is a docset_id OR a persistent
    subcorpus name; delegates to the (pairing-free) collocates-diff engine."""
    from .. import server as _server

    _server._require_user_access(token)
    term = str(payload.get("term") or "").strip()
    if not term:
        raise ApiError(422, "collocation.term_missing", lt("term fehlt", "term is missing"))
    corpus = payload.get("corpus")
    corpus_name = str(corpus or "default")
    idx = _server.get_corpus(corpus)
    term = _collocation_node_term(_server, idx, term)

    async def _resolve_side(role: str) -> tuple[np.ndarray, str]:
        docset_id = payload.get(f"{role}_docset_id")
        subname = payload.get(f"{role}_subcorpus")
        if docset_id:
            return _server._resolve_doc_ids_for_job(idx, corpus, str(docset_id)), str(docset_id)
        if subname:
            definition = await asyncio.to_thread(_server._get_project().get_subcorpus, str(subname))
            if definition is None:
                raise ApiError(
                    404,
                    "subcorpus.not_found",
                    lt("Subkorpus nicht gefunden: {name}", "Subcorpus not found: {name}"),
                    name=subname,
                )
            # A subcorpus may only be contrasted within its own stored corpus, else its
            # filter would resolve against the wrong index (silently-wrong doc ids).
            stored_corpus = str(definition.get("corpus") or "default")
            if stored_corpus != corpus_name:
                raise ApiError(
                    422,
                    "subcorpus.corpus_mismatch",
                    lt(
                        "Subkorpus '{name}' gehört zu Korpus '{corpus}', nicht '{expected}'",
                        "Subcorpus '{name}' belongs to corpus '{corpus}', not '{expected}'",
                    ),
                    name=subname,
                    corpus=stored_corpus,
                    expected=corpus_name,
                )
            # Run the full scan on the bounded pool to preserve default-executor
            # capacity for small offloads.
            doc_ids = await _server._run_heavy_scan(
                _server._resolve_subcorpus_doc_ids, idx, definition
            )
            return doc_ids, _server._store_docset(corpus, doc_ids, _server._doc_count_for_index(idx))
        raise ApiError(
            422,
            "contrast.side_missing",
            lt("{role}_docset_id oder {role}_subcorpus erforderlich", "{role}_docset_id or {role}_subcorpus required"),
            role=role,
        )

    target_doc_ids, target_key = await _resolve_side("target")
    reference_doc_ids, reference_key = await _resolve_side("reference")
    sort_by = str(payload.get("sort_by") or "").strip()
    if sort_by.lower() == "mi2":
        raise ApiError(
            422,
            "collocation.sort_mi2_replaced",
            lt(
                "sort_by=mi2 wurde durch sort_by=chi2_cell ersetzt.",
                "sort_by=mi2 has been replaced by sort_by=chi2_cell.",
            ),
        )
    return _server._launch_collocates_diff(
        corpus, term,
        window=_server._validate_collocate_window(int(payload.get("window", 5) or 5)),
        within_sentence=bool(payload.get("within_sentence", True)),
        sort_by=sort_by,
        limit=_server._bounded_analysis_job_limit(payload.get("limit")),
        target_doc_ids=target_doc_ids, reference_doc_ids=reference_doc_ids,
        target_key=target_key, reference_key=reference_key,
    )


@router.get(
    "/analysis/dispersion_offsets",
    # DISP-1: no strict response_model here — a strict model silently strips the
    # honest completeness fields (truncated/total/next_offset) that a CAPPED page
    # must carry, mirroring the /query completeness contract. The example below
    # documents the envelope.
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "offsets": [12, 48, 96, 210],
                        "partial": True,
                        "truncated": True,
                        "total": 919,
                        "next_offset": 500,
                    }
                }
            }
        }
    },
)
async def analysis_dispersion_offsets(
    term: str,
    corpus: str | None = None,
    docset_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> Dict[str, Any]:
    """Corpus positions of the hits of a query, for dispersion analyses.

    \f
    Positionsliste für Dispersion Analysen."""
    from .. import server as _server

    safe_offset = _server._bounded_offset(offset)
    safe_limit = _server._bounded_analysis_sync_limit(limit)
    idx = _server.get_corpus(corpus)
    docset_mask = None
    doc_ids = None
    basis = "global"
    token_count: int | None = 0
    limitations: list[dict[str, Any]] = []
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")
        doc_ids = docset.get("doc_ids")

    # Dieselbe where()-Einschraenkung wie an der Copilot-Naht. Jede
    # Reparatur dieser Klasse sass bisher NUR dort, und die REST-Route
    # lieferte fuer dieselbe Abfrage die Zahl gegen den GANZEN Korpus.
    from candyconc.core.meta_filters import where_dokumente

    _wo = where_dokumente(_server.get_corpus(corpus), term)
    if _wo is not None:
        doc_ids = (
            np.asarray(_wo, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(np.asarray(doc_ids, dtype=np.uint32),
                                np.asarray(_wo, dtype=np.uint32))
        )
        from candyconc.core.fast_index_native import docset_mask_from_ids

        _idx = _server.get_corpus(corpus)
        try:
            _n = int(_idx.fast_index.boundaries.document._positions.size)
        except Exception:
            _n = int(_server._doc_count_for_index(_idx))
        docset_mask = docset_mask_from_ids(
            np.asarray(doc_ids, dtype=np.uint32), _n)

    # Finding 17 (frontend audit): a malformed/empty CQL term must surface as a
    # clean 4xx (like /query), not a 500. The engine raises a ParseError/ValueError
    # for bad CQL; classify it the same way the query route does.
    if not str(term).strip():
        raise ApiError(400, "query.empty", lt("Bitte einen Suchbegriff eingeben.", "Please enter a search term."))
    # A bracket-prefixed term that is NOT valid bare CQL (e.g. ``[pos=NOUN``,
    # ``[pos=``, ``[[[``) can never be a literal word; reject it as the same 400
    # the /query path raises instead of a silent literal-match miss.
    _reject_malformed_bracket_cql(_server, idx, term)
    try:
        offsets_np = await asyncio.to_thread(
            _server._dispersion_positions_for_term,
            idx,
            term,
            docset_mask=docset_mask,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — classify user CQL errors as 400
        word_vectors_error = _word_vectors_error(exc)
        if word_vectors_error is not None:
            raise word_vectors_error from exc
        if _server._is_query_user_error(str(exc)):
            raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
        raise
    try:
        if doc_ids is not None:
            doc_bounds = _server._doc_bounds_for_index(idx)
            local_doc_ids = _server._docset_local_doc_ids(doc_ids, doc_bounds)
            token_count = int(await asyncio.to_thread(idx.docset_token_count, local_doc_ids))
            corpus_token_count = int(idx.token_count())
            offsets_np = _server._docset_local_offsets(
                offsets_np,
                doc_bounds,
                local_doc_ids,
                token_count=corpus_token_count,
            )
            basis = "docset_local"
        else:
            token_count = int(idx.token_count())
    except Exception as exc:
        # Exact offsets are still useful evidence, but their maximum is not a
        # corpus/docset token count.  Do not invent a denominator from it.
        basis = "docset_offsets_only" if doc_ids is not None else "global_offsets_only"
        token_count = None
        limitations.append(
            {
                "code": "dispersion_offsets_token_basis_unavailable",
                "message": lt(
                    "Die exakte Token-Basis für die Dispersion-Offsets ist nicht verfügbar; "
                    "die Positionen bleiben prüfbar, dürfen aber nicht als normierte Basis gelesen werden.",
                    "The exact token basis for the dispersion offsets is not available. "
                    "The positions remain verifiable but must not be read as a normalized basis.",
                ),
                "detail": exception_text(exc),
            }
        )
    # DISP-1: report the honest completeness of the offset PAGE, mirroring the
    # /query contract (truncated/next_offset/total). The served list is a slice
    # ``offsets_np[start:stop]`` of the full hit set; when that slice is a strict
    # subset (a high-frequency term capped at the sync limit, e.g. 500 of 919)
    # the response must say so — ``partial:true`` plus the full ``total`` and a
    # ``next_offset`` to resume — instead of implying the page is the whole set.
    total = int(offsets_np.size)
    start, stop = _server._page_bounds(total, safe_offset, safe_limit)
    offsets_page = offsets_np[start:stop]
    truncated = bool(stop < total)
    next_offset = stop if truncated else None
    return {
        "offsets": offsets_page.astype(int).tolist(),
        "basis": basis,
        "token_count": token_count,
        "fallback": False,
        "partial": bool(token_count is None or truncated),
        "truncated": truncated,
        "total": total,
        "next_offset": next_offset,
        "limitations": limitations,
    }


@router.get(
    "/analysis/dispersion",
    response_model=DispersionAnalysisResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "term": "freedom",
                        "partitions": [3, 1, 0, 4],
                        "dp": 0.42,
                        "dpnorm": 0.55,
                        "unit": "documents",
                        "classification": "fairly_even",
                    }
                }
            }
        }
    },
)
async def analysis_dispersion(
    term: str,
    partitions: int = 0,
    corpus: str | None = None,
    docset_id: str | None = None,
) -> Dict[str, Any]:
    """Dispersion over the document boundaries with Gries' DP (raw) and DPnorm.

    The unit is the document: every partition is one document, and the expected
    proportion of a document is ``doc_size_i / N`` (its share of tokens), not
    ``1/n``.

    - ``dp``: raw DP over documents, range about [0, 1] (0 = even, 1 = clumped)
    - ``dpnorm``: DP / (1 - min_i(expected_i)), normalized to the reachable maximum
    - ``partitions``: hits per document (same order as ``doc_sizes``)
    - ``positional_dp_windowed``: optional older value over position windows of
      equal width (only when ``partitions`` > 0 is requested)

    The parameter ``partitions`` (token slices of equal width) is optional and
    only controls ``positional_dp_windowed``.

    \f
    Dispersion über reale Dokumentgrenzen mit Gries DP (raw) und DPnorm.

    Standardeinheit ist das Dokument: jede Partition entspricht genau einem
    Dokument, und die erwartete Proportion eines Dokuments ist
    ``doc_size_i / N`` (sein Tokenanteil), nicht ``1/n``.

    - ``dp``: roher Gries DP über Dokumente, Bereich ~[0,1] (0 = gleichmäßig, 1 = geklumpt)
    - ``dpnorm``: DP / (1 - min_i(expected_i)), auf das erreichbare Maximum normiert
    - ``partitions``: Trefferzählung je Dokument (gleiche Reihenfolge wie ``doc_sizes``)
    - ``positional_dp_windowed``: optionaler Legacy-Wert über gleich breite
      positionsbasierte Fenster (nur wenn ``partitions`` > 0 angefragt wird)

    Der frühere ``partitions``-Parameter (gleich breite Token-Slices) ist optional
    und steuert ausschließlich den separaten ``positional_dp_windowed``-Wert.
    """
    from .. import server as _server

    requested_windows = int(partitions or 0)
    # Validate the optional positional-window count up-front (before any corpus
    # lookup) so an out-of-range request fails fast, just like the legacy bound.
    if requested_windows > 0:
        _safe_dispersion_partitions(requested_windows)
    idx = _server.get_corpus(corpus)
    offsets_np: np.ndarray
    doc_ids: np.ndarray | None = None
    docset_mask = None
    basis = "global"
    token_count = 0
    limitations: list[dict[str, Any]] = []
    if docset_id:
        docset = _server._get_docset(docset_id)
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")
        doc_ids = docset.get("doc_ids")

    # Siehe /analysis/dispersion_offsets: dieselbe Klasse, dieselbe Naht.
    from candyconc.core.meta_filters import where_dokumente

    _wo2 = where_dokumente(_server.get_corpus(corpus), term)
    if _wo2 is not None:
        doc_ids = (
            np.asarray(_wo2, dtype=np.uint32) if doc_ids is None
            else np.intersect1d(np.asarray(doc_ids, dtype=np.uint32),
                                np.asarray(_wo2, dtype=np.uint32))
        )

    # Finding 17 (frontend audit): a malformed/empty CQL term must surface as a
    # clean 4xx (like /query), not a 500. The engine raises a ParseError/ValueError
    # for bad CQL; classify it the same way the query route does.
    if not str(term).strip():
        raise ApiError(400, "query.empty", lt("Bitte einen Suchbegriff eingeben.", "Please enter a search term."))
    # A bracket-prefixed term that is NOT valid bare CQL (e.g. ``[pos=NOUN``,
    # ``[pos=``, ``[[[``) can never be a literal word; reject it as the same 400
    # the /query path raises instead of a silent literal-match miss (freq-0
    # ``not_found``).
    _reject_malformed_bracket_cql(_server, idx, term)
    try:
        offsets_np = await asyncio.to_thread(
            _server._dispersion_positions_for_term,
            idx,
            term,
            docset_mask=docset_mask,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — classify user CQL errors as 400
        word_vectors_error = _word_vectors_error(exc)
        if word_vectors_error is not None:
            raise word_vectors_error from exc
        if _server._is_query_user_error(str(exc)):
            raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
        raise

    counts_arr = np.zeros(0, dtype=np.int64)
    doc_sizes_arr = np.zeros(0, dtype=np.int64)
    positional_dp_windowed: float | None = None

    try:
        doc_bounds = _server._doc_bounds_for_index(idx)
        corpus_token_count = int(idx.token_count())
        if doc_ids is not None:
            # Document-based DP over the documents that make up the docset.
            local_doc_ids = _server._docset_local_doc_ids(doc_ids, doc_bounds)
            token_count = int(await asyncio.to_thread(idx.docset_token_count, local_doc_ids))
            bounds_i64 = np.asarray(doc_bounds, dtype=np.int64)
            n_docs = int(bounds_i64.size)
            offsets_clean = offsets_np.astype(np.int64, copy=False)
            offsets_clean = offsets_clean[(offsets_clean >= 0) & (offsets_clean < corpus_token_count)]
            doc_idx = np.searchsorted(bounds_i64, offsets_clean, side="right") - 1
            doc_idx = np.clip(doc_idx, 0, n_docs - 1)
            sel = local_doc_ids.astype(np.int64, copy=False)
            ends = np.empty(n_docs, dtype=np.int64)
            ends[: n_docs - 1] = bounds_i64[1:]
            ends[n_docs - 1] = corpus_token_count
            sizes_all = np.clip(ends - bounds_i64, 0, None)
            counts_all = np.zeros(n_docs, dtype=np.int64)
            if offsets_clean.size:
                np.add.at(counts_all, doc_idx, 1)
            counts_arr = counts_all[sel]
            doc_sizes_arr = sizes_all[sel]
            basis = "docset_local"
        else:
            token_count = corpus_token_count
            counts_arr, doc_sizes_arr = _server._dispersion_document_profile(
                offsets_np,
                doc_bounds,
                token_count=corpus_token_count,
            )
            basis = "global"
    except HTTPException:
        raise
    except Exception as exc:
        # Gries DP is defined over real document partitions.  A synthetic set
        # of position windows would be a different statistic, not a degraded
        # DP result, so fail honestly instead of publishing a plausible number.
        raise ApiError(
            422,
            "dispersion.basis_unavailable",
            lt(
                "Dispersion benötigt exakte Dokumentgrenzen und eine Token-Basis; "
                "dieses Korpus kann die Analyse derzeit nicht belastbar berechnen. "
                "Details: {error}",
                "Dispersion needs exact document boundaries and a token basis. "
                "This corpus cannot compute the analysis reliably at present. "
                "Details: {error}",
            ),
            error=exception_text(exc),
        ) from exc

    counts = counts_arr.astype(int).tolist()
    doc_sizes = doc_sizes_arr.astype(int).tolist()
    dp_result = _server._gries_dp_documents(counts_arr, doc_sizes_arr)
    dp = float(dp_result["dp"])
    dpnorm = float(dp_result["dpnorm"])

    # FT id 3: a term that does not occur (observed frequency 0) must NOT be
    # classified "even" — dp=0.0 here means "no hits", not "uniformly
    # dispersed". Flag it distinctly so a null-result lookup is unambiguous.
    observed_frequency = int(counts_arr.astype(np.int64).sum()) if counts_arr.size else 0
    # Dieselbe Leiter wie die Copilot-Naht, mit denselben Referenzwerten.
    # Ohne sie liefen die beiden auseinander: 93 von 100 haeufigsten
    # Woertern trugen gegenlaeufige Etiketten. Sie steht HIER, weil
    # observed_frequency erst an dieser Stelle existiert.
    classification = _server._dispersion_classification(
        dp,
        total_hits=observed_frequency or None,
        dp_erwartet=dp_result.get("dp_erwartet"),
        dp_min=dp_result.get("dp_min"),
        dp_max=dp_result.get("dp_max"),
    )
    if observed_frequency == 0:
        classification = "not_found"
        limitations.append(
            {
                "code": "dispersion_term_not_found",
                "message": lt(
                    "Der Term kommt im Korpus/Docset nicht vor (Frequenz 0); es wird "
                    "KEIN Dispersionswert als 'gleichmäßig' ausgewiesen.",
                    "The term does not occur in the corpus or document set (frequency 0). "
                    "NO dispersion value is reported as 'even'.",
                ),
            }
        )

    # FT-DISPERSION-FAMILY: surface the dispersion family (Juilland's D,
    # Carroll's D2, Range, VC) over the SAME per-document distribution that
    # drives DP. The math lives in services.tools.dispersion_family (B-analysis
    # owns it); this route only calls it and threads server._gries_dp_documents
    # so dp/dpnorm stay a single source of truth. Degrades to zeros if the
    # compute module is unavailable so the rest of the response is unaffected.
    family: dict[str, Any]
    try:
        from candyconc.services.tools.dispersion_family import dispersion_family

        family = dispersion_family(
            counts_arr, doc_sizes_arr, gries_dp=_server._gries_dp_documents
        )
    except Exception as exc:  # pragma: no cover - defensive degrade
        family = {
            "juilland_d": 0.0,
            "carroll_d2": 0.0,
            "range": 0,
            "range_prop": 0.0,
            "vc": 0.0,
        }
        limitations.append(
            {
                "code": "dispersion_family_unavailable",
                "message": lt(
                    "Die Dispersionsfamilie (Juilland D / Carroll D2 / Range / VC) "
                    "konnte nicht berechnet werden; nur DP/DPnorm sind verfügbar.",
                    "The dispersion family (Juilland D / Carroll D2 / Range / VC) "
                    "could not be computed. Only DP/DPnorm are available.",
                ),
                "detail": exception_text(exc),
            }
        )

    # Optional legacy positional-window DP, surfaced under its own field only.
    if requested_windows > 0:
        safe_windows = _safe_dispersion_partitions(requested_windows)
        offsets_clean = offsets_np.astype(np.int64, copy=False)
        offsets_clean = offsets_clean[offsets_clean >= 0]
        win_token_count = max(1, int(token_count) if token_count > 0 else (int(offsets_clean.max()) + 1 if offsets_clean.size else 1))
        win_counts = np.zeros(safe_windows, dtype=np.int64)
        if offsets_clean.size:
            scale = float(safe_windows) / float(win_token_count)
            idxs = np.clip((offsets_clean * scale).astype(np.int64, copy=False), 0, safe_windows - 1)
            win_counts = np.bincount(idxs, minlength=safe_windows).astype(np.int64, copy=False)
        positional_dp_windowed = _server._gries_dp(win_counts.astype(int).tolist())

    dispersion_method = build_method_block(
        "dispersion",
        index_fingerprint=_index_fingerprint(idx),
        target_total=int(token_count) or None,
    )
    response: Dict[str, Any] = {
        "term": term,
        "partitions": counts,
        "doc_sizes": doc_sizes,
        "unit": "documents",
        "dp": dp,
        "dpnorm": dpnorm,
        # Forward all three dispersion reference values from _gries_dp_documents
        # so the REST response supports the same interpretation as the copilot.
        "dp_min": _sanitize_float(float(dp_result.get("dp_min") or 0.0)),
        "dp_erwartet": _sanitize_float(float(dp_result.get("dp_erwartet") or 0.0)),
        "dp_max": _sanitize_float(float(dp_result.get("dp_max") or 0.0)),
        # FT-DISPERSION-FAMILY additive fields (B-frontend reads these names).
        "juilland_d": _sanitize_float(float(family["juilland_d"])),
        "carroll_d2": _sanitize_float(float(family["carroll_d2"])),
        "range": int(family["range"]),
        "range_prop": _sanitize_float(float(family["range_prop"])),
        "vc": _sanitize_float(float(family["vc"])),
        "classification": classification,
        # FT id 3: explicit observed count so an absent term (0) is unambiguous
        # and never reads as "evenly dispersed".
        "observed_frequency": int(observed_frequency),
        "basis": basis,
        "token_count": int(token_count),
        "fallback": False,
        "partial": False,
        "method": dispersion_method,
        "limitations": limitations,
    }
    if positional_dp_windowed is not None:
        response["positional_dp_windowed"] = float(positional_dp_windowed)
        response["positional_window_count"] = int(_safe_dispersion_partitions(requested_windows))
    return response


@router.post(
    "/analysis/keyness/job",
    response_model=JobLaunchResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "job123",
                        "status_url": "/api/v1/analysis/jobs/job123",
                        "rows_url": "/api/v1/analysis/jobs/job123/rows?offset=0&limit=200",
                        "ws_url": "/api/v1/ws/analysis/job123",
                    }
                }
            }
        }
    },
)
async def analysis_keyness_job(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "docsets": {
                "summary": "Keyness as a background job",
                "value": {
                    "target_docset_id": "a1",
                    "reference_docset_id": "b2",
                    "pos": "N",
                    "corpus": "default",
                },
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    from .. import server as _server

    _server._require_user_access(token)

    corpus = payload.get("corpus")
    pos = payload.get("pos")
    if isinstance(pos, str):
        pos = pos.strip() or None
    limit = _server._bounded_analysis_job_limit(payload.get("limit"))
    min_freq = _keyness_min_freq(payload.get("min_freq"))

    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    target_corpus_name = payload.get("target_corpus")
    ref_corpus_name = payload.get("reference_corpus")
    target = payload.get("target")
    reference_freq_list = payload.get("reference_freq_list") or payload.get("reference_freqlist")

    reference_source = (payload.get("reference_source") or "").strip().lower() or None
    if reference_source not in {None, "docset", "whole", "corpus", "freqlist", "wordlist"}:
        raise ApiError(
            422,
            "keyness.reference_source_invalid",
            lt(
                "reference_source muss docset, whole, corpus oder freqlist sein",
                "reference_source must be docset, whole, corpus or freqlist",
            ),
        )
    if reference_source is None:
        if reference_freq_list is not None:
            reference_source = "freqlist"
        elif ref_corpus_name:
            reference_source = "corpus"
        else:
            reference_source = "docset"

    docset_pair = _keyness_docset_pair(
        _server, payload, source=reference_source, corpus=corpus
    )
    if docset_pair is not None:
        docset_reference_source, t_ids, r_ids = docset_pair
        params = {
            "target_docset_id": str(target_docset_id),
            "reference_docset_id": (
                str(reference_docset_id) if reference_docset_id else None
            ),
            "reference_source": docset_reference_source,
            "pos": pos or "",
            "min_freq": int(min_freq),
            "target_doc_count": int(t_ids.size),
            "reference_doc_count": int(r_ids.size),
            "row_limit": int(limit),
        }
        try:
            job = _server.analysis_jobs.create("keyness_docset", corpus or "default", params)
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
        task = asyncio.create_task(
            _server._run_keyness_docset_job(
                job.job_id,
                corpus=corpus,
                target_doc_ids=t_ids,
                reference_doc_ids=r_ids,
                pos=pos,
                limit=limit,
                min_freq=min_freq,
                reference_source=docset_reference_source,
            )
        )
        _server.analysis_jobs.attach_task(job.job_id, task)
        return {
            "job_id": job.job_id,
            "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
            "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
            "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
        }

    if target_docset_id:
        _server.get_corpus(corpus)
        target_docset = _server._get_docset(str(target_docset_id))
        if target_docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
    elif target_corpus_name:
        _server.get_corpus(target_corpus_name)
    elif isinstance(target, list) and target:
        if pos:
            raise ApiError(
                422,
                "keyness.pos_requires_index",
                lt(
                    "pos erfordert ein indexiertes Ziel-Docset oder Ziel-Korpus",
                    "pos requires an indexed target document set or target corpus",
                ),
            )
    else:
        raise ApiError(
            422,
            "keyness.target_missing",
            lt(
                "target, target_docset_id oder target_corpus für Keyness erforderlich",
                "target, target_docset_id or target_corpus is required for keyness",
            ),
        )

    if reference_source in {"freqlist", "wordlist"}:
        _keyness_external_reference_spec(payload, reference_freq_list, pos=pos)
    else:
        if not ref_corpus_name:
            raise ApiError(
                422,
                "keyness.reference_corpus_missing",
                lt(
                    "reference_source=corpus erfordert reference_corpus (Korpusname)",
                    "reference_source=corpus requires reference_corpus (corpus name)",
                ),
            )
        _server.get_corpus(ref_corpus_name)

    if reference_source in {"freqlist", "wordlist", "corpus"}:
        params = {
            "reference_source": reference_source,
            "pos": pos or "",
            "min_freq": int(min_freq),
            "row_limit": int(limit),
        }
        try:
            job = _server.analysis_jobs.create("keyness_external", corpus or "default", params)
        except RuntimeError as exc:
            raise HTTPException(status_code=429, detail=exception_text(exc)) from exc
        task = asyncio.create_task(
            _run_keyness_external_job(
                _server,
                job.job_id,
                payload,
                reference_source=reference_source,
                corpus=corpus,
                pos=pos,
                target=target,
                target_docset_id=target_docset_id,
                target_corpus_name=target_corpus_name,
                ref_corpus_name=ref_corpus_name,
                reference_freq_list=reference_freq_list,
                min_freq=min_freq,
                limit=limit,
            )
        )
        _server.analysis_jobs.attach_task(job.job_id, task)
        return {
            "job_id": job.job_id,
            "status_url": f"/api/v1/analysis/jobs/{job.job_id}",
            "rows_url": f"/api/v1/analysis/jobs/{job.job_id}/rows?offset=0&limit=200",
            "ws_url": f"/api/v1/ws/analysis/{job.job_id}",
        }
    raise AssertionError("Keyness-Referenzmodus wurde nicht aufgelöst")


async def _run_keyness_external_job(
    _server: Any,
    job_id: str,
    payload: Dict[str, Any],
    *,
    reference_source: str,
    corpus: Any,
    pos: str | None,
    target: Any,
    target_docset_id: Any,
    target_corpus_name: Any,
    ref_corpus_name: Any,
    reference_freq_list: Any,
    min_freq: int,
    limit: int,
) -> None:
    """Run a keyness job against a corpus or validated external frequency map."""
    try:
        _server.analysis_jobs.update(
            job_id,
            progress=10,
            message=lt("Zielfrequenzen werden bestimmt", "Determining target frequencies"),
            status="running",
        )
        freq_t, total_t, target_idx = await _keyness_target_freqs(
            _server,
            target=target,
            target_docset_id=target_docset_id,
            target_corpus_name=target_corpus_name,
            corpus=corpus,
            pos=pos,
        )
        _server.analysis_jobs.update(
            job_id, progress=45, message=lt("Referenz wird aufgelöst", "Resolving reference")
        )
        method_extra: dict[str, Any] = {
            "min_freq": int(min_freq),
            "reference_source": reference_source,
        }
        if reference_source in {"freqlist", "wordlist"}:
            ref_map, reference_total, reference_pos = _keyness_external_reference_spec(
                payload, reference_freq_list, pos=pos
            )
            freq_t = _filter_keyness_freq_map(freq_t)
            ref_map = _filter_keyness_freq_map(ref_map)
            # Dieselbe Regel wie oben, dieselbe Begruendung. Eine Reparatur
            # an EINER von zwei Naehten waere eine Verschiebung.
            total_t_roh = int(total_t)
            total_t = analysierbare_groesse(freq_t)
            reference_total = analysierbare_groesse(ref_map)
            method_extra["target_tokens_roh"] = total_t_roh
            df = await asyncio.to_thread(
                compute_keyness_external,
                freq_t,
                ref_map,
                int(total_t),
                reference_total,
                min_freq=min_freq,
            )
            ref_total_effective = int(reference_total)
            method_extra.update(
                {
                    "reference_vocabulary_complete": True,
                    "reference_pos": reference_pos,
                }
            )
        elif reference_source == "corpus":
            if not ref_corpus_name:
                raise ValueError(
                    lt(
                        "reference_source=corpus erfordert reference_corpus (Korpusname).",
                        "reference_source=corpus requires reference_corpus (corpus name).",
                    )
                )
            ref_idx = _server.get_corpus(ref_corpus_name)
            reference_ids = np.arange(
                _server._doc_count_for_index(ref_idx), dtype=np.uint32
            )
            freq_r, ref_total_effective = await _keyness_docset_population(
                _server, ref_idx, reference_ids, pos=pos
            )
            freq_t = _filter_keyness_freq_map(freq_t)
            freq_r = _filter_keyness_freq_map(freq_r)
            # Der Nenner gehoert zum gefilterten Zaehler. Diese Naht fehlte
            # in 781e5e4179, waehrend der freqlist-Zweig darueber repariert
            # wurde. Die Reparatur war damit INVERTIERT: bei freqlist war
            # der Job richtig und die Route roh, bei corpus umgekehrt.
            total_t_roh = int(total_t)
            ref_total_roh = int(ref_total_effective)
            total_t = analysierbare_groesse(freq_t)
            ref_total_effective = analysierbare_groesse(freq_r)
            method_extra["target_tokens_roh"] = total_t_roh
            method_extra["reference_tokens_roh"] = ref_total_roh
            df = await asyncio.to_thread(
                _server._compute_keyness_counts,
                freq_t,
                freq_r,
                int(total_t),
                int(ref_total_effective),
                min_freq=min_freq,
            )
        else:
            raise ValueError(lt("Ungültige Keyness-Referenz", "Invalid keyness reference"))
        _server.analysis_jobs.update(
            job_id, progress=85, message=lt("Keyness Scores werden berechnet", "Computing keyness scores")
        )
        all_rows = [_sanitize_row(r) for r in _server._rows_from_frame_page(df, offset=0, limit=int(len(df)))]
        method = build_method_block(
            "keyness",
            index_fingerprint=_index_fingerprint(target_idx) if target_idx is not None else None,
            target_total=int(total_t),
            reference_total=int(ref_total_effective),
            counting_attribute="word",
            extra=method_extra,
        )
        result = {
            "rows": all_rows,
            "method": method,
            "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
            "row_limit": int(limit),
            "total_candidates": int(len(all_rows)),
            "truncated": False,
        }
        _server.analysis_jobs.set_result(job_id, result=result, total_rows=int(len(all_rows)))
    except HTTPException as exc:  # pragma: no cover - surfaced as job error
        _server.analysis_jobs.set_error(
            job_id,
            RuntimeError(exc.detail if isinstance(exc.detail, str) else str(exc.detail)),
        )
    except Exception as exc:  # pragma: no cover - background errors
        _server.analysis_jobs.set_error(job_id, exc)


async def _keyness_target_freqs(
    _server: Any,
    *,
    target: Any,
    target_docset_id: Any,
    target_corpus_name: Any,
    corpus: Any,
    pos: str | None,
) -> tuple[dict[str, int], int, Any]:
    """Resolve keyness target counts for a docset, corpus, or word list."""
    if target_docset_id:
        idx = _server.get_corpus(corpus)
        docset = _server._get_docset(str(target_docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        ids_raw = docset.get("doc_ids")
        ids = np.unique(
            np.asarray(
                ids_raw if ids_raw is not None else np.zeros(0, dtype=np.uint32),
                dtype=np.uint32,
            )
        )
        freq_map, total = await _keyness_docset_population(
            _server, idx, ids, pos=pos
        )
        return freq_map, total, idx
    if target_corpus_name:
        idx = _server.get_corpus(target_corpus_name)
        ids = np.arange(_server._doc_count_for_index(idx), dtype=np.uint32)
        freq_map, total = await _keyness_docset_population(
            _server, idx, ids, pos=pos
        )
        return freq_map, total, idx
    if isinstance(target, list) and target:
        if pos:
            raise ApiError(
                422,
                "keyness.pos_requires_index",
                lt(
                    "pos erfordert ein indexiertes Ziel-Docset oder Ziel-Korpus",
                    "pos requires an indexed target document set or target corpus",
                ),
            )
        from collections import Counter

        freq_map = {
            word: int(count)
            for word, count in Counter(casefold_key(str(t)) for t in target).items()
            if word
        }
        return freq_map, int(len(target)), None
    raise ApiError(
        422,
        "keyness.freqlist_target_missing",
        lt(
            "target, target_docset_id oder target_corpus für reference_source=freqlist erforderlich",
            "target, target_docset_id or target_corpus is required for reference_source=freqlist",
        ),
    )


async def _keyness_external_freqlist(
    _server: Any,
    payload: Dict[str, Any],
    *,
    target: Any,
    target_docset_id: Any,
    target_corpus_name: Any,
    corpus: Any,
    pos: str | None,
    reference_freq_list: Any,
    min_freq: int,
    offset: int,
    limit: int,
) -> Dict[str, Any]:
    """Compute API-only keyness against a validated external frequency map."""
    ref_map, reference_total, reference_pos = _keyness_external_reference_spec(
        payload, reference_freq_list, pos=pos
    )

    freq_t, total_t, target_idx = await _keyness_target_freqs(
        _server,
        target=target,
        target_docset_id=target_docset_id,
        target_corpus_name=target_corpus_name,
        corpus=corpus,
        pos=pos,
    )
    sort_key = _keyness_sort(payload.get("sort"))
    freq_t = _filter_keyness_freq_map(freq_t)
    ref_map = _filter_keyness_freq_map(ref_map)
    # Der Nenner gehoert zum gefilterten Zaehler. Diese Naht fehlte in
    # 781e5e4179, waehrend ihr Job-Zwilling repariert wurde. Dieselbe
    # Anfrage lieferte danach ueber POST /analysis/keyness ein anderes
    # Vorzeichen als ueber POST /analysis/keyness/job.
    total_t_roh, reference_total_roh = int(total_t), int(reference_total)
    total_t = analysierbare_groesse(freq_t)
    reference_total = analysierbare_groesse(ref_map)
    df = await asyncio.to_thread(
        compute_keyness_external,
        freq_t,
        ref_map,
        int(total_t),
        reference_total,
        min_freq=min_freq,
    )
    total_candidates = int(len(df))
    all_rows = [_sanitize_row(r) for r in _server._rows_from_frame_page(df, offset=0, limit=int(len(df)))]
    all_rows = _apply_keyness_sort(all_rows, sort_key)
    rows = all_rows[offset : offset + limit]
    return {
        "rows": rows,
        "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
        "method": build_method_block(
            "keyness",
            index_fingerprint=_index_fingerprint(target_idx) if target_idx is not None else None,
            target_total=int(total_t),
            reference_total=int(reference_total),
            sort_key=sort_key,
            counting_attribute="word",
            extra={
                "min_freq": int(min_freq),
                "reference_source": "freqlist",
                "reference_vocabulary_complete": True,
                "reference_pos": reference_pos,
                # Die rohen Groessen gehen nicht verloren: target_total ist
                # die Groesse, auf der GERECHNET wurde, diese hier sagen,
                # wie gross Ziel und Referenz insgesamt sind.
                "target_tokens_roh": total_t_roh,
                "reference_tokens_roh": reference_total_roh,
            },
        ),
        **_server._bounded_result_meta(
            row_limit=limit,
            total_candidates=total_candidates,
            offset=offset,
        ),
    }


@router.post(
    "/analysis/keyness",
    response_model=PagedKeynessResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "rows": [
                            {
                                "word": "freedom",
                                "chi2_cell": 8.1,
                                "ll": 12.4,
                                "direction": "target",
                            }
                        ]
                    }
                }
            }
        }
    },
)
async def analysis_keyness(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "docsets": {
                "summary": "Keyness over document sets",
                "value": {
                    "target_docset_id": "a1",
                    "reference_docset_id": "b2",
                    "pos": "N",
                },
            },
            "lists": {
                "summary": "Keyness over word lists",
                "value": {"target": ["freedom", "liberty"], "reference": ["economy", "jobs"]},
            },
        },
    ),
) -> Dict[str, Any]:
    """Keyness comparison between two sets.

    Input
    - target, reference: optional word lists
    - target_docset_id, reference_docset_id: document sets to compare
    - pos: optional part-of-speech filter
    - corpus: corpus name

    \f
    Keyness Vergleich zwischen zwei Mengen.

    Eingabe
    - target, reference: optional direkte Wortlisten
    - target_docset_id, reference_docset_id: Docsets für Vergleich
    - pos: optionaler POS Filter
    - corpus: Korpusname
    """
    from .. import server as _server

    target = payload.get("target")
    reference = payload.get("reference")
    pos = payload.get("pos")
    if isinstance(pos, str):
        pos = pos.strip() or None
    target_docset_id = payload.get("target_docset_id")
    reference_docset_id = payload.get("reference_docset_id")
    corpus = payload.get("corpus")
    offset = _server._bounded_offset(payload.get("offset", 0))
    limit = _server._bounded_analysis_sync_limit(payload.get("limit"))
    sort_key = _keyness_sort(payload.get("sort"))

    min_freq = _keyness_min_freq(payload.get("min_freq"))

    target_corpus_name = payload.get("target_corpus")
    ref_corpus_name = payload.get("reference_corpus")

    reference_source = (payload.get("reference_source") or "").strip().lower() or None
    reference_freq_list = payload.get("reference_freq_list") or payload.get("reference_freqlist")

    if reference_source not in {None, "docset", "whole", "corpus", "freqlist", "wordlist"}:
        raise ApiError(
            422,
            "keyness.reference_source_invalid",
            lt(
                "reference_source muss docset, whole, corpus oder freqlist sein",
                "reference_source must be docset, whole, corpus or freqlist",
            ),
        )

    if reference_source in {"freqlist", "wordlist"} or (
        reference_source is None and reference_freq_list is not None
    ):
        return await _keyness_external_freqlist(
            _server,
            payload,
            target=target,
            target_docset_id=target_docset_id,
            target_corpus_name=target_corpus_name,
            corpus=corpus,
            pos=pos,
            reference_freq_list=reference_freq_list,
            min_freq=min_freq,
            offset=offset,
            limit=limit,
        )

    if reference_source is None and target_corpus_name and ref_corpus_name:
        reference_source = "corpus"

    docset_source = reference_source
    if docset_source is None and target_docset_id and reference_docset_id:
        docset_source = "docset"
    docset_pair = _keyness_docset_pair(
        _server, payload, source=docset_source, corpus=corpus
    )

    if reference_source == "corpus":
        if not ref_corpus_name:
            raise ApiError(
                422,
                "keyness.reference_corpus_missing",
                lt(
                    "reference_source=corpus erfordert reference_corpus (Korpusname)",
                    "reference_source=corpus requires reference_corpus (corpus name)",
                ),
            )
        ref_idx = _server.get_corpus(ref_corpus_name)
        freq_t, total_t, target_idx = await _keyness_target_freqs(
            _server,
            target=target,
            target_docset_id=target_docset_id,
            target_corpus_name=target_corpus_name,
            corpus=corpus,
            pos=pos,
        )
        reference_ids = np.arange(_server._doc_count_for_index(ref_idx), dtype=np.uint32)
        freq_r, total_r = await _keyness_docset_population(
            _server, ref_idx, reference_ids, pos=pos
        )
        freq_t = _filter_keyness_freq_map(freq_t)
        freq_r = _filter_keyness_freq_map(freq_r)
        # Der Nenner gehoert zum gefilterten Zaehler. Siehe
        # analysis_defaults.analysierbare_groesse: gemessen fielen 19,25
        # Prozent aller Token aus dem Zaehler, waehrend der Nenner die volle
        # Teilkorpusgroesse blieb. Beide Wahrscheinlichkeiten wurden zu
        # klein, und zwar ungleich stark, sobald die Seiten verschieden
        # viel Interpunktion tragen.
        total_t_roh, total_r_roh = int(total_t), int(total_r)
        total_t = analysierbare_groesse(freq_t)
        total_r = analysierbare_groesse(freq_r)
        df = await asyncio.to_thread(
            _server._compute_keyness_counts,
            freq_t,
            freq_r,
            int(total_t),
            int(total_r),
            min_freq=min_freq,
        )
        all_rows = [_sanitize_row(r) for r in _server._rows_from_frame_page(df, offset=0, limit=int(len(df)))]
        all_rows = _apply_keyness_sort(all_rows, sort_key)  # FT id 8
        total_candidates = len(all_rows)
        rows = all_rows[offset : offset + limit]
        return {
            "rows": rows,
            "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
            "method": build_method_block(
                "keyness",
                index_fingerprint=_index_fingerprint(target_idx) if target_idx is not None else None,
                target_total=int(total_t),
                reference_total=int(total_r),
                sort_key=sort_key,
                counting_attribute="word",
                extra={
                    "min_freq": int(min_freq),
                    "reference_source": reference_source,
                    # Die ROHE Teilkorpusgroesse geht nicht verloren. Wer
                    # target_total liest, sieht die Grundgesamtheit, auf der
                    # gerechnet wurde. Wer wissen will, wie gross das
                    # Teilkorpus ist, findet es hier daneben.
                    "target_tokens_roh": total_t_roh,
                    "reference_tokens_roh": total_r_roh,
                },
            ),
            **_server._bounded_result_meta(
                row_limit=limit,
                total_candidates=total_candidates,
                offset=offset,
            ),
        }

    if docset_pair is not None:
        docset_reference_source, t_ids, r_ids = docset_pair
        idx = _server.get_corpus(corpus)
        lex = idx.fast_index.lexicons.word
        if lex is None:
            raise RuntimeError(
                lt("Word Lexikon fehlt. Bitte Index neu bauen.", "Word lexicon missing. Rebuild the index.")
            )
        # Welche Schreibung welchen Anteil traegt. Ohne sie liest sich eine
        # Zeile als Aussage ueber ihr gedrucktes Etikett, waehrend sie eine
        # Aussage ueber die ganze Faltklasse ist. Dieselbe Angabe wie am
        # Copilot-Werkzeug, damit die Geschwisterflaechen nicht auseinanderlaufen.
        schreibungen_t: dict[int, dict[int, int]] = {}
        schreibungen_r: dict[int, dict[int, int]] = {}
        t_term_ids, t_counts = await asyncio.to_thread(
            idx.frequency_counts_docset, t_ids, stopwords=None, pos_prefix=pos, case_fold=True,
            variants_out=schreibungen_t
        )
        r_term_ids, r_counts = await asyncio.to_thread(
            idx.frequency_counts_docset, r_ids, stopwords=None, pos_prefix=pos, case_fold=True,
            variants_out=schreibungen_r
        )
        if pos:
            total_t = int(t_counts.sum(dtype=np.uint64))
            total_r = int(r_counts.sum(dtype=np.uint64))
        else:
            total_t = int(await asyncio.to_thread(idx.docset_token_count, t_ids))
            total_r = int(await asyncio.to_thread(idx.docset_token_count, r_ids))
        union_ids = np.union1d(
            t_term_ids.astype(np.uint32, copy=False),
            r_term_ids.astype(np.uint32, copy=False),
        )
        keyness_method = build_method_block(
            "keyness",
            index_fingerprint=_index_fingerprint(idx),
            target_total=int(total_t),
            reference_total=int(total_r),
            sort_key=sort_key,
            counting_attribute="word",
            extra={
                "min_freq": int(min_freq),
                "reference_source": docset_reference_source,
            },
        )

        def empty_result() -> dict[str, Any]:
            return {
                "rows": [],
                "method": keyness_method,
                "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
                **_server._bounded_result_meta(
                    row_limit=limit, total_candidates=0, offset=offset
                ),
            }

        if union_ids.size == 0:
            return empty_result()
        aligned_t = _server._align_counts_to_union(union_ids, t_term_ids, t_counts)
        aligned_r = _server._align_counts_to_union(union_ids, r_term_ids, r_counts)
        analyst_keep = _server._analyst_token_mask_for_term_ids(idx, union_ids)
        if not bool(np.all(analyst_keep)):
            union_ids = union_ids[analyst_keep]
            aligned_t = aligned_t[analyst_keep]
            aligned_r = aligned_r[analyst_keep]
            if union_ids.size == 0:
                return empty_result()
        # Der Nenner gehoert zum gefilterten Zaehler. Diese Naht fehlte in
        # 781e5e4179 und stand damit gegen den Job-Zwilling in server.py,
        # der sie jetzt hat. Ein Paritaetstest hat die Spaltung gefangen.
        total_t_roh, total_r_roh = int(total_t), int(total_r)
        total_t = int(aligned_t.sum(dtype=np.uint64))
        total_r = int(aligned_r.sum(dtype=np.uint64))
        keyness_method["target_total"] = total_t
        keyness_method["reference_total"] = total_r
        keyness_method["target_tokens_roh"] = total_t_roh
        keyness_method["reference_tokens_roh"] = total_r_roh
        if min_freq > 0:
            keep = (
                aligned_t.astype(np.int64) + aligned_r.astype(np.int64)
            ) >= int(min_freq)
            union_ids = union_ids[keep]
            aligned_t = aligned_t[keep]
            aligned_r = aligned_r[keep]
            if union_ids.size == 0:
                return empty_result()
        total_candidates = int(union_ids.size)
        chi2_cell_u, ll_u = await asyncio.to_thread(
            _server.keyness_scores_fast,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
        )
        # Full 2x2 Pearson chi-square (all four cells, no Yates correction to
        # match the G^2 convention) over the WHOLE candidate union BEFORE any
        # order/page slicing — the proper df=1 test statistic, distinct from the
        # single-cell ``chi2_cell``. Single source of truth with the keyness
        # sync/job paths (services.tools.keyness).
        chi2_u = await asyncio.to_thread(
            chi2_2x2_pooled,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
            correction=False,
        )
        # Inferential stats (log_ratio + CI, p-value, BH-FDR q-value) and the
        # reliability diagnostics (E_min, low_reliability, BIC) over the WHOLE
        # candidate union BEFORE any order/page slicing — q depends on the test
        # count m, so computing it after truncation would inflate significance.
        # Single source of truth with the keyness compute (services.tools.keyness
        # keyness_full_stats / expected_min_cell) so the docset job path and this
        # synchronous path emit the identical column set (C-contract-drift-4).
        full_stats_u = await asyncio.to_thread(
            keyness_full_stats,
            aligned_t,
            aligned_r,
            total_t,
            total_r,
            ll=ll_u,
        )
        log_ratio_u = full_stats_u["log_ratio"]
        # Katz delta-method (Hardie) log-ratio confidence interval, computed over
        # the WHOLE candidate union by the shared keyness_full_stats helper — the
        # SAME source the docset JOB path (_run_keyness_docset_job /
        # _keyness_rows_from_result) reads, so the synchronous docset response
        # carries an identical log_ratio_ci_low / log_ratio_ci_high column pair
        # (no null CI leak on the sync path; sync == JOB).
        log_ratio_ci_low_u = full_stats_u["log_ratio_ci_low"]
        log_ratio_ci_high_u = full_stats_u["log_ratio_ci_high"]
        lrc_u = full_stats_u["lrc"]
        p_value_u = full_stats_u["p_value"]
        q_value_u = full_stats_u["q_value"]
        e_min_u = await asyncio.to_thread(
            expected_min_cell, aligned_t, aligned_r, total_t, total_r
        )
        # BIC (Wilson): G^2 - ln(N), size-robust significance. Same formula as
        # the keyness compute path.
        n_total = float(total_t) + float(total_r)
        bic_u = np.asarray(ll_u, dtype=np.float64) - (
            np.log(n_total) if n_total > 0 else 0.0
        )
        # FT id 8: honor the (validated, outer) sort_key. Default ll_signed:
        # signed log-likelihood descending so over-represented (positive
        # direction) words lead, instead of an unsigned chi2-cell sort that
        # interleaves under-represented words at the top.
        sign_u = _server._keyness_signed_direction(aligned_t, aligned_r, total_t, total_r)
        if sort_key == "ll_signed":
            order = np.argsort(ll_u * sign_u, kind="stable")[::-1]
        elif sort_key == "ll":
            order = np.argsort(ll_u, kind="stable")[::-1]
        elif sort_key == "chi2_cell":
            order = np.argsort(chi2_cell_u, kind="stable")[::-1]
        elif sort_key in {"chi2", "chi2_signed"}:
            ranked = chi2_u * sign_u if sort_key == "chi2_signed" else chi2_u
            order = np.argsort(ranked, kind="stable")[::-1]
        elif sort_key == "log_ratio":
            order = np.argsort(log_ratio_u, kind="stable")[::-1]
        elif sort_key == "bic":
            order = np.argsort(bic_u, kind="stable")[::-1]
        else:
            order = np.argsort(ll_u * sign_u, kind="stable")[::-1]
        term_ids = union_ids[order].astype(np.uint32, copy=False)
        chi2_cell_u = chi2_cell_u[order]
        ll_u = ll_u[order]
        chi2_u = chi2_u[order]
        log_ratio_u = log_ratio_u[order]
        log_ratio_ci_low_u = log_ratio_ci_low_u[order]
        log_ratio_ci_high_u = log_ratio_ci_high_u[order]
        lrc_u = lrc_u[order]
        p_value_u = p_value_u[order]
        q_value_u = q_value_u[order]
        e_min_u = e_min_u[order]
        bic_u = bic_u[order]
        aligned_t = aligned_t[order]
        aligned_r = aligned_r[order]
        start, stop = _server._page_bounds(int(term_ids.size), offset, limit)
        term_ids = term_ids[start:stop]
        chi2_cell_u = chi2_cell_u[start:stop]
        ll_u = ll_u[start:stop]
        chi2_u = chi2_u[start:stop]
        log_ratio_u = log_ratio_u[start:stop]
        log_ratio_ci_low_u = log_ratio_ci_low_u[start:stop]
        log_ratio_ci_high_u = log_ratio_ci_high_u[start:stop]
        lrc_u = lrc_u[start:stop]
        p_value_u = p_value_u[start:stop]
        q_value_u = q_value_u[start:stop]
        e_min_u = e_min_u[start:stop]
        bic_u = bic_u[start:stop]
        target_counts = aligned_t[start:stop]
        reference_counts = aligned_r[start:stop]
        words = _server.strings_for_ids(lex.offsets, lex.strings_view, term_ids, True)
        rows: list[dict[str, Any]] = []
        for (
            word,
            target_freq,
            reference_freq,
            score_chi2_cell,
            score_ll,
            score_chi2,
            log_ratio,
            log_ratio_ci_low,
            log_ratio_ci_high,
            lrc_wert,
            p_value,
            q_value,
            e_min,
            bic,
        ) in zip(
            words,
            target_counts,
            reference_counts,
            chi2_cell_u,
            ll_u,
            chi2_u,
            log_ratio_u,
            log_ratio_ci_low_u,
            log_ratio_ci_high_u,
            lrc_u,
            p_value_u,
            q_value_u,
            e_min_u,
            bic_u,
        ):
            target_pm = (float(target_freq) / float(total_t) * 1_000_000.0) if total_t > 0 else 0.0
            reference_pm = (float(reference_freq) / float(total_r) * 1_000_000.0) if total_r > 0 else 0.0
            diff_pm = target_pm - reference_pm
            sign = 1.0 if diff_pm >= 0.0 else -1.0
            rows.append(
                _sanitize_row(
                    {
                        "word": str(word),
                        "target_freq": int(target_freq),
                        "reference_freq": int(reference_freq),
                        "target_per_million": target_pm,
                        "reference_per_million": reference_pm,
                        "diff_per_million": diff_pm,
                        "direction": "target" if diff_pm >= 0.0 else "reference",
                        # Full 2x2 Pearson chi-square (proper test statistic, df=1).
                        "chi2": float(score_chi2),
                        "chi2_signed": float(score_chi2) * sign,
                        # Single target-cell Pearson contribution (NOT a full test).
                        "chi2_cell": float(score_chi2_cell),
                        "ll": float(score_ll),
                        "chi2_cell_signed": float(score_chi2_cell) * sign,
                        "ll_signed": float(score_ll) * sign,
                        # Inferential + reliability columns (FT-KEYNESS-RESEARCH):
                        # the full keyness contract requires every row to carry
                        # log_ratio / log_ratio_ci_low / log_ratio_ci_high /
                        # p_value / q_value / expected_min / low_reliability / bic
                        # — identical to the docset job and external-reference paths.
                        "log_ratio": float(log_ratio),
                        "log_ratio_ci_low": float(log_ratio_ci_low),
                        "log_ratio_ci_high": float(log_ratio_ci_high),
                        "lrc": float(lrc_wert),
                        "p_value": float(p_value),
                        "q_value": float(q_value),
                        "expected_min": float(e_min),
                        "low_reliability": bool(float(e_min) < RELIABILITY_EXPECTED_MIN),
                        "bic": float(bic),
                    }
                )
            )
        schreibungen_anhaengen(
            rows,
            lambda ids: _server.strings_for_ids(
                lex.offsets, lex.strings_view, np.asarray(ids, dtype=np.uint32), True
            ),
            (term_ids, words, schreibungen_t),
            (term_ids, words, schreibungen_r),
        )
        return {
            "rows": rows,
            "method": keyness_method,
            "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
            **_server._bounded_result_meta(
                row_limit=limit,
                total_candidates=total_candidates,
                offset=offset,
            ),
        }

    # KEY-incomplete: a structured target/reference pairing that is missing its
    # opposite side must 4xx here — exactly like the JOB path, whose 'docset'
    # default requires BOTH target_docset_id AND reference_docset_id (:3558) and
    # whose contrast guard requires both sides (:3091). Without this, a lone
    # target_docset_id (or target_corpus, or a sole reference_docset_id/_corpus)
    # falls through to the word-list path, where ``target/reference or []`` makes
    # an EMPTY pair and returns HTTP 200 with no rows — silently claiming "no
    # keywords" for a request that never named a comparison. The shared rule:
    # a docset/corpus on one axis demands a resolved counterpart on the other.
    has_target_side = bool(target_docset_id or target_corpus_name)
    has_reference_side = bool(reference_docset_id or ref_corpus_name)
    if has_target_side != has_reference_side:
        raise ApiError(
            422,
            "keyness.pair_incomplete",
            lt(
                "Keyness braucht ein vollständiges Vergleichspaar: Ziel UND "
                "Referenz. Bitte target_docset_id/target_corpus mit dem passenden "
                "reference_docset_id/reference_corpus angeben (oder reference_source "
                "setzen).",
                "Keyness needs a complete comparison pair: target AND reference. "
                "Provide target_docset_id/target_corpus with the matching "
                "reference_docset_id/reference_corpus (or set reference_source).",
            ),
        )

    target = target or []
    reference = reference or []

    pos_map = payload.get("pos_map") or None
    pos = payload.get("pos") or None
    if not isinstance(target, list) or not isinstance(reference, list):
        raise HTTPException(
            status_code=422,
            detail=(
                "Provide either word lists in 'target'/'reference', or corpus "
                "names in 'target_corpus'/'reference_corpus', or docset ids in "
                "'target_docset_id'/'reference_docset_id'. A bare string in "
                "'target'/'reference' is not accepted."
            ),
        )
    # FT id 2: drop non-analyst tokens from both word lists before scoring so
    # newline/punctuation/marker pseudo-tokens cannot surface as keywords.
    target = [t for t in target if is_analyst_token(t)]
    reference = [r for r in reference if is_analyst_token(r)]
    try:
        df = await asyncio.to_thread(
            _server._compute_keyness,
            target,
            reference,
            pos_map=pos_map,
            pos=pos,
            min_freq=min_freq,
        )
    except ValueError as exc:
        # "pos ohne pos_map" ist eine Frage der Aufruferin, kein
        # Serverfehler. Ungefangen entkam der Fehler als HTTP 500,
        # gemessen mit dem TestClient. Die Meldung nennt den Ausweg.
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
    all_rows = [_sanitize_row(r) for r in _server._rows_from_frame_page(df, offset=0, limit=int(len(df)))]
    all_rows = _apply_keyness_sort(all_rows, sort_key)  # FT id 8
    total_candidates = len(all_rows)
    rows = all_rows[offset : offset + limit]
    return {
        "rows": rows,
        "filtered_token_policy": _KEYNESS_FILTERED_TOKEN_POLICY,
        # Word-list keyness has no corpus token basis to report; the method
        # block still documents the statistics (formula provenance) without
        # totals/fingerprint (degrades gracefully per the F1 contract).
        "method": build_method_block(
            "keyness",
            sort_key=sort_key,
            # Die Listen kommen vom Aufrufer, das Korpus wird nicht gezaehlt
            # und nichts gefaltet. Ausdruecklich None, nicht weggelassen.
            counting_attribute=None,
            extra={"min_freq": int(min_freq), "reference_source": "wordlist"},
        ),
        **_server._bounded_result_meta(
            row_limit=limit,
            total_candidates=total_candidates,
            offset=offset,
        ),
    }


@router.post(
    "/analysis/wordsketch",
    response_model=Dict[str, Any],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "sketches": {
                            "obj": [{"word": "defend", "f": 12, "score": 4.1}],
                            "amod": [{"word": "political", "f": 7, "score": 3.2}],
                        },
                        "method": {"family": "wordsketch", "default_sort": "score"},
                        # Legacy relation keys are mirrored at the top level for
                        # back-compat with older consumers (deprecated).
                        "obj": [{"word": "defend", "f": 12, "score": 4.1}],
                    }
                }
            }
        }
    },
)
async def word_sketch_endpoint(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {"summary": "Word sketch", "value": {"term": "freedom"}}
        },
    ),
) -> Dict[str, Any]:
    """Return grammatical collocations grouped by dependency relation.

    Response shape (Track F1): the relation->rows tables live under
    ``sketches`` and a top-level ``method`` block carries the statistical
    provenance. For backward compatibility the relation keys are ALSO mirrored
    at the top level (so existing ``Object.entries(tables)`` consumers keep
    working); new consumers should read ``sketches`` + ``method``.
    """
    from .. import server as _server

    # FT id 11/32: accept BOTH the documented ``word`` and the implemented
    # ``term`` payload keys (``term`` wins when both are present).
    term = (payload.get("term") or payload.get("word") or "").strip()
    if not term:
        raise ApiError(
            422, "wordsketch.term_missing", lt("Missing term (oder 'word')", "Missing term (or 'word')")
        )
    corpus = payload.get("corpus")
    docset_id = payload.get("docset_id")
    # FT id 6/7: validated min co-occurrence frequency floor. Default 3 removes
    # f=1/f=2 hapaxes (typos, list bullets) that otherwise dominate the ranking
    # with inflated single-cell chi2 scores. A client may override (0 disables);
    # negative / non-integer is a 422, never a silent no-op.
    min_freq = _word_sketch_min_freq(payload.get("min_freq"))
    limit = _server._bounded_analysis_sync_limit(payload.get("limit") or payload.get("relation_limit"))
    if docset_id:
        idx = _server.get_corpus(corpus)
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")
        docset_ids = docset.get("doc_ids")
        if docset_mask is None or docset_ids is None:
            raise ApiError(
                422,
                "wordsketch.docset_incomplete",
                lt("Docset unvollständig für Word Sketch", "Document set incomplete for word sketch"),
            )
        docset_ids_arr = np.asarray(docset_ids, dtype=np.uint32) if docset_ids is not None else None
        tables = await asyncio.to_thread(
            _server._word_sketch_for_query,
            idx,
            term,
            docset_mask=docset_mask,
            docset_ids=docset_ids_arr,
            relation_limit=0,
        )
    else:
        idx = _server.get_corpus(corpus)
        tables = await asyncio.to_thread(
            _server._word_sketch_for_query,
            idx,
            term,
            relation_limit=0,
        )
    sketches: Dict[str, Any] = {}
    label_scheme = _label_scheme(idx)
    relations_meta: Dict[str, dict[str, Any]] = {}
    for rel, df in tables.items():
        # FT id 6/7: apply the reliability floor BEFORE the page limit — the SAME
        # ordering the copilot tool (tool_wrappers.word_sketch_tool) and
        # /analysis/wordsketch_diff use (both floor the FULL relation via the
        # shared ``apply_word_sketch_min_freq`` seam, then limit). Page-limiting
        # FIRST and flooring after would let a below-floor row occupy a slot and
        # so drop a valid high-freq collocate that ranked just below the limit
        # (REST != copilot != diff). We serialise the WHOLE relation, floor +
        # re-rank the survivors (frame-shape-agnostic, like the prior route), and
        # only THEN apply the page limit — so the floor never operates on an
        # already-truncated page.
        rows = _word_sketch_all_rows_from_frame(df, _server)
        rows = _word_sketch_rank_rows(rows, min_freq=min_freq)
        total_candidates = len(rows)
        visible_rows = rows[:limit]
        if visible_rows:
            sketches[rel] = visible_rows
            relations_meta[rel] = {
                "relation": rel,
                "label": word_sketch_relation_label(rel, label_scheme),
                "row_limit": int(limit),
                "total_candidates": int(total_candidates),
                "total_rows": int(len(visible_rows)),
                "truncated": bool(total_candidates > int(limit)),
                "min_freq": int(min_freq),
            }

    # FT id 10: each relation group carries a gloss of its dependency code
    # (sb_rev, nk, amod, ...) in the request language, chosen by the
    # annotation scheme of the corpus (TIGER, ClearNLP). ``_rev`` marks the
    # reversed (node-is-dependent) direction.
    method = build_method_block(
        "wordsketch",
        index_fingerprint=_index_fingerprint(idx),
        # Default ranking is logDice (corpus-size-comparable, frequency-robust;
        # Rychlý 2008), matching the collocations default and Sketch Engine — not
        # the fragile single-cell chi2_cell. The min co-occurrence floor is
        # surfaced for transparency. ``min_freq_semantics`` states the exact
        # meaning of the floor (V4): it filters PARTNER rows, not relations.
        sort_key="logdice",
        extra={
            "min_freq": int(min_freq),
            "min_freq_semantics": lt(
                "Partnerzeilen mit f >= min_freq werden gelistet; die "
                "Schwelle filtert Partner, nicht Relationen.",
                "Partner rows with f >= min_freq are listed. The threshold "
                "filters partners, not relations.",
            ),
        },
    )
    # ``sketches`` + ``method`` is the canonical shape; relation keys are
    # mirrored at the top level for back-compat (never overwriting the two
    # reserved keys).
    result: Dict[str, Any] = {
        "sketches": sketches,
        "relations": relations_meta,
        "method": method,
        # The word form the sketch counts (exact, else lower case), None for a
        # cql: node. A row opens the concordance of node, relation, collocate.
        "node": _server._word_sketch_node_form(idx, term),
    }
    for rel, rows in sketches.items():
        if rel not in result:
            result[rel] = rows
    return result


# ---------------------------------------------------------------------------
# FT-SKETCH-DIFF-DISTRIBUTION — word sketch difference
# ---------------------------------------------------------------------------
def _sketch_relation_freq_map(tables: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Build relation -> {word: co-occurrence frequency} from floored sketch tables.

    The shared ``sketch_difference`` compute aligns by ``word`` and emits only the
    score columns, so the per-collocate co-occurrence frequency ``f`` (which the
    floored ``_word_sketch_for_query`` tables DO carry) never reaches the diff
    rows. We re-join it here from the SAME floored tables the diff was computed
    over, so ``f``/``f_a``/``f_b`` carry the real value instead of a null.
    """
    out: Dict[str, Dict[str, int]] = {}
    for rel, table in (tables or {}).items():
        rows: list[dict[str, Any]]
        if hasattr(table, "to_dict"):
            try:
                rows = table.to_dict("records")  # pandas DataFrame
            except TypeError:
                rows = list(table.to_dicts())  # polars frame
        elif isinstance(table, list):
            rows = [dict(r) for r in table]
        else:
            rows = []
        freq: Dict[str, int] = {}
        for r in rows:
            word = r.get("word")
            if word is None:
                continue
            raw_f = r.get("f", r.get("frequency"))
            try:
                freq[str(word)] = int(raw_f)
            except (TypeError, ValueError):
                continue
        out[str(rel)] = freq
    return out


def _map_sketch_difference_relations(
    diff: Dict[str, Any],
    freq_a: Dict[str, Dict[str, int]] | None = None,
    freq_b: Dict[str, Dict[str, int]] | None = None,
) -> Dict[str, dict[str, Any]]:
    """Map the shared :func:`sketch_difference` output to the wordsketch-diff
    RESPONSE CONTRACT (relations DICT, NaN/Inf-sanitized cells).

    The shared compute (``analysis_defaults.sketch_difference``) is the single
    source of truth for the diff math (alignment by ``word``, ``common`` carrying
    ``score_a``/``score_b``/``delta`` sorted by ``|delta|`` desc, ``only_a`` /
    ``only_b`` carrying a single ``score`` sorted by score desc). This adapter
    re-serialises its already-ordered buckets with the route's strict-JSON float
    sanitisation, and re-joins the per-collocate co-occurrence frequency from the
    floored side tables (``freq_a``/``freq_b``) the diff was computed over — so the
    schema's ``f``/``f_a``/``f_b`` fields carry the real value rather than null.
    """
    freq_a = freq_a or {}
    freq_b = freq_b or {}
    relations: Dict[str, dict[str, Any]] = {}
    for rel, buckets in (diff.get("relations") or {}).items():
        rel_key = str(rel)
        fa = freq_a.get(rel_key, {})
        fb = freq_b.get(rel_key, {})

        def _with_single_f(rows: Any, fmap: Dict[str, int]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for r in rows:
                row = dict(r)
                word = str(row.get("word", ""))
                if word in fmap:
                    row["f"] = fmap[word]
                    row["frequency"] = fmap[word]
                out.append(_sanitize_row(row))
            return out

        def _with_pair_f(rows: Any) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for r in rows:
                row = dict(r)
                word = str(row.get("word", ""))
                if word in fa:
                    row["f_a"] = fa[word]
                if word in fb:
                    row["f_b"] = fb[word]
                out.append(_sanitize_row(row))
            return out

        relations[rel_key] = {
            "only_a": _with_single_f(buckets.get("only_a", []), fa),
            "only_b": _with_single_f(buckets.get("only_b", []), fb),
            "common": _with_pair_f(buckets.get("common", [])),
        }
    return relations


@router.post(
    "/analysis/wordsketch_diff",
    response_model=SketchDiffResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "label_a": "freedom",
                        "label_b": "liberty",
                        "score_key": "score",
                        "relations": {
                            "obj": {
                                "only_a": [{"word": "defend", "score": 4.1}],
                                "only_b": [{"word": "preserve", "score": 3.7}],
                                "common": [
                                    {"word": "protect", "score_a": 4.1, "score_b": 2.0, "delta": 2.1}
                                ],
                            }
                        },
                    }
                }
            }
        }
    },
)
async def analysis_wordsketch_diff(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "two_terms": {
                "summary": "Compare two terms in the same corpus",
                "value": {"term_a": "freedom", "term_b": "liberty"},
            },
            "term_two_docsets": {
                "summary": "One term across two subcorpora (human vs AI)",
                "value": {"term": "freedom", "docset_a": "human1", "docset_b": "ai1"},
            },
        },
    ),
) -> Dict[str, Any]:
    """Difference between two word sketches.

    Two modes:
    - ``term_a`` against ``term_b`` (optional ``docset_id`` for both sides): two
      terms in the same corpus or subcorpus.
    - ``term`` with ``docset_a`` and ``docset_b``: the same term in two subcorpora.

    For every grammatical relation the collocates are split into ``only_a``,
    ``only_b`` and ``common``. ``common`` carries the score difference
    (score_a - score_b).

    \f
    Differenz zwischen zwei Word Sketches (FT-SKETCH-DIFF-DISTRIBUTION).

    Zwei Modi:
    - ``term_a`` vs ``term_b`` (optional ``docset_id`` für beide Seiten):
      zwei Terme im gleichen (Sub-)Korpus.
    - ``term`` mit ``docset_a`` und ``docset_b``: derselbe Term in zwei
      Subkorpora (Mensch-vs-KI-Sketch).

    Pro grammatischer Relation werden die Kollokate in ``only_a`` / ``only_b`` /
    ``common`` partitioniert; ``common`` trägt das Score-Delta (score_a -
    score_b). Die Word-Sketch-Berechnung selbst wird read-only über
    ``server._word_sketch_for_query`` wiederverwendet (kein Engine-Change).
    """
    from .. import server as _server

    corpus = payload.get("corpus")
    limit = _server._bounded_analysis_sync_limit(payload.get("limit") or payload.get("relation_limit"))
    # FT id 6/7: the SAME validated reliability floor the REST profile endpoint
    # applies, so the difference path can never headline an f=1/f=2 hapax that
    # the profile suppresses (WS-DIFF-NOFLOOR). Default 3; a client may override
    # (0 disables); negative / non-integer is a 422.
    min_freq = _word_sketch_min_freq(payload.get("min_freq"))
    limitations: list[dict[str, Any]] = []

    def _resolve_docset(docset_id: Any) -> tuple[Any, Any]:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        mask = docset.get("docset_mask")
        ids = docset.get("doc_ids")
        if mask is None or ids is None:
            raise ApiError(
                422,
                "wordsketch.docset_incomplete",
                lt("Docset unvollständig für Word Sketch", "Document set incomplete for word sketch"),
            )
        return mask, np.asarray(ids, dtype=np.uint32)

    term_a = (payload.get("term_a") or "").strip()
    term_b = (payload.get("term_b") or "").strip()
    term = (payload.get("term") or "").strip()
    docset_a = payload.get("docset_a")
    docset_b = payload.get("docset_b")
    docset_id = payload.get("docset_id")

    # Classify partners against the complete source tables and cap only the output groups.
    if term and docset_a and docset_b:
        idx = _server.get_corpus(corpus)
        # MODE 2: same term across two docsets (cross-subcorpus sketch).
        mask_a, ids_a = _resolve_docset(docset_a)
        mask_b, ids_b = _resolve_docset(docset_b)
        tables_a = await asyncio.to_thread(
            _server._word_sketch_for_query, idx, term,
            docset_mask=mask_a, docset_ids=ids_a, relation_limit=0,
        )
        tables_b = await asyncio.to_thread(
            _server._word_sketch_for_query, idx, term,
            docset_mask=mask_b, docset_ids=ids_b, relation_limit=0,
        )
        label_a = f"{term} @ {docset_a}"
        label_b = f"{term} @ {docset_b}"
    elif term_a and term_b:
        idx = _server.get_corpus(corpus)
        # MODE 1: two terms in the same (optionally docset-scoped) corpus.
        common_mask = None
        common_ids = None
        if docset_id:
            common_mask, common_ids = _resolve_docset(docset_id)
        tables_a = await asyncio.to_thread(
            _server._word_sketch_for_query, idx, term_a,
            docset_mask=common_mask, docset_ids=common_ids, relation_limit=0,
        )
        tables_b = await asyncio.to_thread(
            _server._word_sketch_for_query, idx, term_b,
            docset_mask=common_mask, docset_ids=common_ids, relation_limit=0,
        )
        label_a = term_a
        label_b = term_b
    else:
        raise ApiError(
            422,
            "wordsketch.diff_input_missing",
            lt(
                "Entweder term_a+term_b oder term+docset_a+docset_b erforderlich",
                "Either term_a+term_b or term+docset_a+docset_b is required",
            ),
        )

    # Apply the SHARED word-sketch reliability floor to BOTH sides BEFORE the
    # diff (WS-DIFF-NOFLOOR), so the difference path inherits the REST profile's
    # suppression of f=1/f=2 hapaxes — a hapax can never appear in only_a/only_b
    # or headline a relation here when the profile drops it. Same helper, same
    # default constant as the REST profile endpoint.
    tables_a = apply_word_sketch_min_freq(tables_a, min_freq=min_freq)
    tables_b = apply_word_sketch_min_freq(tables_b, min_freq=min_freq)

    # Single source of truth: delegate the diff math to the shared
    # ``analysis_defaults.sketch_difference`` (C-wordsketch-diff-parity-02). It
    # aligns by ``word`` per relation, emits ``common`` with score_a/score_b/delta
    # (|delta| desc) and ``only_a``/``only_b`` with a single ``score`` (score
    # desc) — exactly the WORDSKETCH-DIFF RESPONSE CONTRACT. The route only maps
    # its buckets through the strict-JSON float sanitiser.
    diff = sketch_difference(tables_a, tables_b, top_n=limit)
    if not (diff.get("relations") or {}):
        limitations.append(
            {
                "code": "wordsketch_diff_empty",
                "message": lt(
                    "Keine Word-Sketch-Relationen für eine der beiden Seiten gefunden.",
                    "No word sketch relations found for one of the two sides.",
                ),
            }
        )
    # Re-join the real co-occurrence frequency from the SAME floored tables the
    # diff was computed over, so the schema's f/frequency (only_a/only_b) and
    # f_a/f_b (common) carry the real value instead of a null.
    relations = _map_sketch_difference_relations(
        diff,
        freq_a=_sketch_relation_freq_map(tables_a),
        freq_b=_sketch_relation_freq_map(tables_b),
    )
    label_scheme = _label_scheme(idx)
    relation_labels = {
        rel: word_sketch_relation_label(rel, label_scheme)
        for rel in relations
    }
    return {
        "label_a": label_a,
        "label_b": label_b,
        # The word forms each side counts, for the back path of a row.
        "node_a": _server._word_sketch_node_form(idx, term_a or term),
        "node_b": _server._word_sketch_node_form(idx, term_b or term),
        "score_key": "score",
        "relations": relations,
        "relation_labels": relation_labels,
        "method": build_method_block(
            "wordsketch",
            index_fingerprint=_index_fingerprint(idx),
            # Default ranking is logDice, exactly like the profile endpoint — pass
            # the SAME sort_key so method.default_sort does not drift ('score' vs
            # 'logdice') between the profile and the diff surfaces.
            sort_key="logdice",
            # Disclose the applied reliability floor — the diff path floors both
            # sides with the SAME min_freq as the REST profile endpoint. The
            # semantics note matches the profile endpoint (V4): the floor
            # filters PARTNER rows, not relations.
            extra={
                "min_freq": int(min_freq),
                "min_freq_semantics": lt(
                    "Partnerzeilen mit f >= min_freq werden gelistet; die "
                    "Schwelle filtert Partner, nicht Relationen.",
                    "Partner rows with f >= min_freq are listed. The threshold "
                    "filters partners, not relations.",
                ),
            },
        ),
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# F4 — Lexical diversity (TTR / STTR / Guiraud / MATTR)
# ---------------------------------------------------------------------------
@router.get(
    "/analysis/lexical-diversity",
    response_model=LexicalDiversityResponse,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "ttr": 0.42,
                        "sttr": 0.71,
                        "sttr_window": 1000,
                        "guiraud": 58.3,
                        "n_tokens": 19234,
                        "n_types": 8077,
                        "basis": "corpus",
                    }
                }
            }
        }
    },
)
async def analysis_lexical_diversity(
    corpus: str | None = None,
    docset_id: str | None = None,
    target_docset_id: str | None = None,
    reference_docset_id: str | None = None,
    sttr_window: int = 1000,
    mattr: bool = False,
    mattr_window: int = 500,
    analyst_tokens_only: bool = True,
) -> Dict[str, Any]:
    """Lexical diversity (TTR, STTR, Guiraud, MATTR) of a corpus, subcorpus or document set.

    Parameters
    - corpus: corpus name (default: the active corpus)
    - docset_id: optional document set (one side)
    - target_docset_id, reference_docset_id: comparison of two sides (adds
      ``per_side`` and ``size_warning`` when the sizes differ)
    - sttr_window: STTR window in tokens (default 1000, reported)
    - mattr: also compute MATTR (slower)

    Response (one side): ttr, sttr, sttr_window, guiraud, mattr (optional),
    n_tokens, n_types. Raw TTR depends on the text length. Use STTR or Guiraud to
    compare samples of different size.

    \f
    Lexikalische Diversität (TTR/STTR/Guiraud/MATTR) für Korpus/Subkorpus/Docset.

    Parameter
    - corpus: Korpusname (default: aktives Korpus)
    - docset_id: optionaler Filter auf eine Dokumentmenge (einseitig)
    - target_docset_id, reference_docset_id: zweiseitiger Human-vs-AI-Vergleich
      (liefert ``per_side`` + ``size_warning`` bei Längen-Ungleichheit)
    - sttr_window: STTR-Fenstergröße in Tokens (Standard 1000, mitberichtet)
    - mattr: optional MATTR mitberechnen (teurer)

    Antwort (einseitig): ttr, sttr, sttr_window, guiraud, mattr?, n_tokens, n_types.
    Roh-TTR ist längen-konfundiert; STTR/Guiraud für Größenvergleiche nutzen.
    """
    from .. import server as _server
    from candyconc.services.tools.lexical_diversity import (
        compute_lexical_diversity,
        lexical_diversity_per_side,
    )

    safe_window = _safe_positive_int(
        sttr_window, name="sttr_window", default=1000, max_value=1_000_000
    )
    safe_mattr_window = _safe_positive_int(
        mattr_window, name="mattr_window", default=500, max_value=1_000_000
    )
    idx = _server.get_corpus(corpus)
    corpus_name = corpus or "default"

    def _docset_doc_ids(ds_id: str) -> np.ndarray:
        docset = _server._get_docset(str(ds_id))
        if docset.get("corpus") != corpus_name:
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        ids = docset.get("doc_ids")
        if ids is None:
            return np.zeros(0, dtype=np.uint32)
        return np.asarray(ids, dtype=np.uint32)

    fingerprint = _index_fingerprint(idx)

    # Two-sided comparison (the Human-vs-AI headline use-case).
    if target_docset_id and reference_docset_id:
        t_ids = _docset_doc_ids(target_docset_id)
        r_ids = _docset_doc_ids(reference_docset_id)
        # Real labels: the docset ids identify each side. They flow into the
        # per_side dict keys so a consumer can match a side back to its docset
        # (the FE coerces dict->array on insertion order, so the target side —
        # inserted first — stays first regardless of the key text).
        target_label = str(target_docset_id)
        reference_label = str(reference_docset_id)
        sides = await asyncio.to_thread(
            lexical_diversity_per_side,
            idx,
            target_doc_ids=t_ids,
            reference_doc_ids=r_ids,
            sttr_window=safe_window,
            include_mattr=bool(mattr),
            mattr_window=safe_mattr_window,
            analyst_tokens_only=bool(analyst_tokens_only),
            target_label=target_label,
            reference_label=reference_label,
        )
        method = build_method_block(
            "lexical_diversity",
            index_fingerprint=fingerprint,
            extra={"sttr_window": safe_window},
        )
        # Top-level metrics summarise the target side so the flat schema fields
        # are always populated; per_side carries both sides verbatim under their
        # real (docset-id) labels.
        target_side = sides["per_side"][target_label]
        return {
            **target_side,
            "basis": "docset_pair",
            "indexFingerprint": fingerprint,
            "method": method,
            "per_side": sides["per_side"],
            **({"size_warning": sides["size_warning"]} if "size_warning" in sides else {}),
        }

    # One-sided (corpus or single docset).
    doc_ids: np.ndarray | None = None
    basis = "corpus"
    if docset_id:
        doc_ids = _docset_doc_ids(docset_id)
        basis = "docset"

    metrics = await asyncio.to_thread(
        compute_lexical_diversity,
        idx,
        doc_ids=doc_ids,
        sttr_window=safe_window,
        include_mattr=bool(mattr),
        mattr_window=safe_mattr_window,
        analyst_tokens_only=bool(analyst_tokens_only),
    )
    method = build_method_block(
        "lexical_diversity",
        index_fingerprint=fingerprint,
        target_total=int(metrics.get("n_tokens") or 0) or None,
        extra={"sttr_window": safe_window},
    )
    return {
        **metrics,
        "basis": basis,
        "indexFingerprint": fingerprint,
        "method": method,
    }


# ---------------------------------------------------------------------------
# F2 — Server-side concordance export (exact count, bounded row stream)
# ---------------------------------------------------------------------------
# Hard ceiling on rows buffered/streamed by one export. The query count remains
# exact; callers can therefore distinguish the complete hit set from the file's
# bounded row payload instead of mistaking a cap for a complete export.
_EXPORT_HIT_CAP = 1_000_000
_EXPORT_FORMATS = {"csv", "tsv", "json", "jsonl", "xlsx"}

# One shared tabular column contract for CSV, TSV and XLSX exports. The XLSX
# parity test compares cell values against the CSV variant column by column.
# ``pos`` and ``node`` name the node token, ``left`` and ``right`` the context
# around it. ``match`` holds all tokens of the hit, ``match_start`` and
# ``match_end`` their first and last corpus position (appended so the earlier
# columns keep their place).
_EXPORT_TABULAR_HEADER = [
    "pos", "doc_id", "doc", "left", "node", "right", "meta", "match", "match_start", "match_end",
]

# Availability failures of a scientific export (exact denominator or row set
# not guaranteed). Raised inside the worker thread and mapped to 503.
_EXPORT_COUNT_INCOMPLETE = lt(
    "Die vollständige Trefferzahl konnte nicht bestimmt werden; Export wurde nicht erstellt.",
    "The complete hit count could not be determined. The export was not created.",
)
_EXPORT_ROWS_MISMATCH = lt(
    "Trefferzählung und exportierbare KWIC-Zeilen stimmen nicht überein; Export wurde nicht erstellt.",
    "The hit count and the exportable concordance lines do not match. The export was not created.",
)


def _csv_safe_cell(value: Any) -> str:
    """CSV/TSV-injection-safe stringification of one cell.

    Prefixes a single quote to any value whose first character is one of
    ``= + - @`` (or a control char a spreadsheet treats as a formula lead),
    so a malicious corpus token like ``=cmd|'/c calc'`` cannot execute when the
    export is opened in Excel/LibreOffice/Sheets. Quoting/escaping of the field
    delimiter itself is handled by the ``csv`` module (csv mode) or explicit
    replacement (tsv mode).
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r", "\n", "\x00"):
        return "'" + text
    return text


def _export_format(value: str | None) -> str:
    fmt = str(value or "csv").strip().lower()
    if fmt not in _EXPORT_FORMATS:
        raise ApiError(
            422,
            "export.format_invalid",
            lt("format muss eines von {allowed} sein", "format must be one of {allowed}"),
            allowed=sorted(_EXPORT_FORMATS),
        )
    return fmt


def _export_excel_de(payload: dict[str, Any], fmt: str) -> bool:
    """Parse the Excel-friendly CSV dialect switch (``;`` delimiter + UTF-8 BOM).

    Accepted spellings: ``excel_de: true`` / ``excelDe: true`` or
    ``dialect: "excel-de"``. German Excel installations misparse the default
    comma dialect; the default output stays byte-identical when the switch is
    absent. The dialect only exists for CSV — any other format is a 422 so a
    silently ignored parameter cannot misrepresent the produced file.
    """
    if "excel_de" in payload:
        excel_de = bool(payload.get("excel_de"))
    elif "excelDe" in payload:
        excel_de = bool(payload.get("excelDe"))
    else:
        excel_de = False
    dialect = payload.get("dialect")
    if dialect is not None:
        dialect_str = str(dialect).strip().lower()
        if dialect_str == "excel-de":
            excel_de = True
        elif dialect_str not in {"", "default"}:
            raise ApiError(
                422,
                "export.dialect_invalid",
                lt("dialect muss 'excel-de' oder 'default' sein", "dialect must be 'excel-de' or 'default'"),
            )
    if excel_de and fmt != "csv":
        raise ApiError(
            422,
            "export.dialect_csv_only",
            lt(
                "Der Dialekt 'excel-de' ist nur für format=csv verfügbar",
                "The dialect 'excel-de' is only available for format=csv",
            ),
        )
    return excel_de


def _export_index_provenance(_server: Any, idx: Any, corpus_name: str) -> dict[str, Any]:
    cache_signature = _index_fingerprint(idx)
    try:
        resolved_corpus, index_path = _server._resolve_meta_schema_index_path(corpus_name)
        schema = _server._build_meta_schema_fingerprint(index_path, resolved_corpus)
        index_fingerprint = str(schema.get("indexFingerprint") or cache_signature)
        return {
            "corpus": str(schema.get("corpus") or resolved_corpus or corpus_name),
            "indexFingerprint": index_fingerprint,
            "metadataSchemaHash": schema.get("metadataSchemaHash"),
            "fingerprintStrength": schema.get("fingerprintStrength"),
            "cacheSignature": cache_signature,
        }
    except Exception:
        return {
            "corpus": corpus_name,
            "indexFingerprint": cache_signature,
            "metadataSchemaHash": None,
            "fingerprintStrength": "runtime_cache_signature",
            "cacheSignature": cache_signature,
        }


async def _collect_export_rows(
    _server: Any,
    idx: Any,
    *,
    term: str,
    ctx: int,
    docset_mask: Any,
    sort_by: str | None,
    sort_dir: str,
    case_insensitive: bool,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Return capped export rows plus the exact total and truncation state.

    Reuses the canonical ``run_query`` render path (same engine the KWIC view
    uses) — no new engine path. A bare single token is rewritten to an explicit
    ``cql:[word="X"]`` term so case behaviour matches the search contract:
    with ``%c`` when ``case_insensitive`` (case-folded match), WITHOUT ``%c``
    when case-sensitive (exact-case match — the plain-term engine path is
    case-insensitive by default, so we must force the case-sensitive form).
    Phrases, wildcards and explicit ``cql:`` queries are passed through
    unchanged (rewriting them would change the matched language).
    """
    from candyconc.core.query_runtime import run_query
    from candyconc.services.backend.kwic_renderer import parse_sort, sort_kwic_rows

    try:
        sort_spec = parse_sort(sort_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=exception_text(exc)) from exc

    effective_term = term
    stripped = term.strip()
    if _is_simple_single_token(stripped):
        escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
        if case_insensitive:
            # A bare plain token -> case-insensitive CQL word match (%c flag), so
            # an export honours "ignore case" exactly like the search.
            effective_term = f'cql:[word="{escaped}" %c]'
        else:
            # Case-sensitive export: the bare-term engine path folds case by
            # default, so pin the exact case via an explicit CQL word cell
            # WITHOUT the %c flag.
            effective_term = f'cql:[word="{escaped}"]'

    def _run() -> tuple[list[dict[str, Any]], int, bool]:
        total_matches, _elapsed_ms, count_partial = _server._compute_query_count(
            idx,
            term,
            int(ctx),
            None,
            None,
            docset_mask,
            case_insensitive=case_insensitive,
        )
        if count_partial:
            # A scientific export may be row-capped, but its denominator must
            # never be a lower bound disguised as an exact match count.
            raise RuntimeError(_EXPORT_COUNT_INCOMPLETE)
        rows: list[dict[str, Any]] = []
        for row in run_query(
            effective_term,
            ctx=int(ctx),
            corpus=idx,
            limit=_EXPORT_HIT_CAP,
            docset_mask=docset_mask,
            include_file=True,
        ):
            rows.append(row)
        expected_rows = min(int(total_matches), _EXPORT_HIT_CAP)
        if len(rows) != expected_rows:
            raise RuntimeError(_EXPORT_ROWS_MISMATCH)
        _annotate_export_match_spans(idx, rows)
        _server._enrich_rows_with_doc_meta(
            idx,
            rows,
            doc_bounds=_server._doc_bounds_for_index(idx),
            token_count=int(idx.fast_index.token_store.token_count),
            cache={},
            include_file=True,
        )
        if sort_spec is not None:
            rows = sort_kwic_rows(rows, sort_by, sort_dir=sort_dir)
        return rows, int(total_matches), int(total_matches) > len(rows)

    try:
        return await asyncio.to_thread(_run)
    except (RuntimeError, ValueError) as exc:
        msg = str(exc)
        if msg == _EXPORT_COUNT_INCOMPLETE:
            # Never hand a plausible but numerically ambiguous export to a
            # researcher. This is an availability failure, not a user query
            # error, so clients can distinguish it from malformed CQL.
            raise ApiError(503, "export.count_incomplete", _EXPORT_COUNT_INCOMPLETE) from exc
        if msg == _EXPORT_ROWS_MISMATCH:
            raise ApiError(503, "export.rows_mismatch", _EXPORT_ROWS_MISMATCH) from exc
        word_vectors_error = _word_vectors_error(exc)
        if word_vectors_error is not None:
            raise word_vectors_error from exc
        if _server._is_query_user_error(msg):
            raise HTTPException(status_code=422, detail=exception_text(exc)) from exc
        raise


def _annotate_export_match_spans(idx: Any, rows: list[dict[str, Any]]) -> None:
    """Add the whole hit to each row: ``match``, ``match_start`` and ``match_end``.

    A row sits at its node token (``pos``, ``kw``) and lists the other tokens
    of the hit in ``match_offsets``. The hit runs from the lowest to the
    highest offset. Its word forms come from the index, so the span is complete
    for any context width. Tokens are joined with their original spacing when
    the index has ``whitespace_after.bin`` (like the context columns), else
    with single spaces.
    """
    from candyconc.core.source_spacing import display_flags, join_tokens

    fast_index = getattr(idx, "fast_index", None)
    token_store = getattr(fast_index, "token_store", None)
    word_lex = getattr(getattr(fast_index, "lexicons", None), "word", None)
    ws = display_flags(idx)
    for row in rows:
        pos = row.get("pos")
        if pos is None:
            continue
        offsets = [int(offset) for offset in (row.get("match_offsets") or [])]
        low = min([0, *offsets])
        high = max([0, *offsets])
        start = int(pos) + low
        end = int(pos) + high
        row["match_start"] = start
        row["match_end"] = end
        if low == high == 0 or token_store is None or word_lex is None:
            row["match"] = row.get("kw", row.get("node", ""))
            continue
        ids = token_store.get_word_ids_range(start, end + 1)
        words = [str(word_lex.get_string(int(wid)) or "") for wid in ids]
        row["match"] = " ".join(words) if ws is None else join_tokens(words, start, ws)


def _export_row_payload(row: dict[str, Any]) -> dict[str, Any]:
    from candyconc.utils.text_normalize import normalize_index_display_text

    doc_id = row.get("doc_id", row.get("docId"))
    doc = row.get("doc")
    node = row.get("kw", row.get("node", ""))
    return {
        "pos": row.get("pos"),
        "doc_id": doc_id,
        "docId": doc_id,
        "doc": doc,
        "document": doc,
        "left": normalize_index_display_text(row.get("left", "")),
        "node": normalize_index_display_text(node),
        "right": normalize_index_display_text(row.get("right", "")),
        "meta": row.get("meta") if isinstance(row.get("meta"), dict) else None,
        "match": normalize_index_display_text(row.get("match", node)),
        "match_start": row.get("match_start", row.get("pos")),
        "match_end": row.get("match_end", row.get("pos")),
    }


def _stable_sha256(value: Any) -> str:
    encoded = _json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _export_comment_value(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return str(value)


def _export_provenance_fields(
    *,
    fmt: str,
    term: str,
    total_matches: int,
    exported_rows: int,
    export_cap: int,
    truncated: bool,
    timestamp: str,
    query_params: dict[str, Any],
    index_provenance: dict[str, Any],
) -> list[tuple[str, Any]]:
    """Replay facts shared by the CSV/TSV comment prelude and the XLSX
    provenance sheet."""
    return [
        ("Schema", "candyconc-concordance-export-v1"),
        ("Query", term),
        ("Corpus", query_params.get("corpus")),
        ("DocsetId", query_params.get("docset_id")),
        ("Sort", query_params.get("sort")),
        ("SortDir", query_params.get("sort_dir")),
        ("CaseInsensitive", query_params.get("case_insensitive")),
        ("ContextTokens", query_params.get("ctx")),
        ("Format", fmt),
        ("TotalMatches", int(total_matches)),
        ("ExportedRows", int(exported_rows)),
        ("ExportCap", int(export_cap)),
        ("Truncated", bool(truncated)),
        ("Timestamp", timestamp),
        ("IndexFingerprint", index_provenance.get("indexFingerprint")),
        ("MetadataSchemaHash", index_provenance.get("metadataSchemaHash")),
        ("FingerprintStrength", index_provenance.get("fingerprintStrength")),
        ("QueryJson", query_params),
    ]


def _export_tabular_provenance_lines(
    *,
    fmt: str,
    term: str,
    total_matches: int,
    exported_rows: int,
    export_cap: int,
    truncated: bool,
    timestamp: str,
    query_params: dict[str, Any],
    index_provenance: dict[str, Any],
) -> list[str]:
    """Comment prelude for CSV/TSV exports.

    JSON/JSONL already carry provenance in structured payload fields. CSV/TSV
    need the same replay facts inside the file, not only in HTTP headers.
    """
    fields = _export_provenance_fields(
        fmt=fmt,
        term=term,
        total_matches=total_matches,
        exported_rows=exported_rows,
        export_cap=export_cap,
        truncated=truncated,
        timestamp=timestamp,
        query_params=query_params,
        index_provenance=index_provenance,
    )
    lines = ["# CandyConc Export"]
    for key, value in fields:
        safe_value = _export_comment_value(value).replace("\r", " ").replace("\n", " ")
        lines.append(f"# {key}: {safe_value}")
    return lines


def _export_tabular_cell(payload: dict[str, Any], col: str) -> str:
    """One injection-safe string cell, shared by CSV/TSV and XLSX.

    XLSX reuses the exact CSV stringification (contract parity) — the
    ``_csv_safe_cell`` quote prefix also stops openpyxl from typing a leading
    ``=`` string as a live formula cell.
    """
    value = payload.get(col)
    if col == "meta" and isinstance(value, dict):
        value = _json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _csv_safe_cell(value)


_XLSX_CONCORDANCE_SHEET = lt("Konkordanz", "Concordance")
_XLSX_PROVENANCE_SHEET = lt("Provenienz", "Provenance")
_XLSX_FIELD_HEADER = lt("Feld", "Field")
_XLSX_VALUE_HEADER = lt("Wert", "Value")


def _build_xlsx_export(
    rows: list[dict[str, Any]],
    *,
    provenance_fields: list[tuple[str, Any]],
) -> bytes:
    """Serialize the concordance as an XLSX workbook (openpyxl, in memory).

    The concordance sheet carries the identical column contract and cell
    values as the CSV variant. The provenance sheet carries the replay facts
    that CSV keeps in its comment prelude. Sheet names and the provenance
    header follow the request language (Concordance/Provenance, Konkordanz/
    Provenienz), the column names and field keys stay the same in both.
    """
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - dependency ships in requirements
        raise ApiError(
            501,
            "export.openpyxl_missing",
            lt("XLSX-Export benötigt das Paket openpyxl", "XLSX export needs the package openpyxl"),
        ) from exc

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(_XLSX_CONCORDANCE_SHEET.resolve())
    sheet.append(list(_EXPORT_TABULAR_HEADER))
    for row in rows:
        payload = _export_row_payload(row)
        sheet.append([_export_tabular_cell(payload, col) for col in _EXPORT_TABULAR_HEADER])
    provenance_sheet = workbook.create_sheet(_XLSX_PROVENANCE_SHEET.resolve())
    provenance_sheet.append([_XLSX_FIELD_HEADER.resolve(), _XLSX_VALUE_HEADER.resolve()])
    for key, value in provenance_fields:
        provenance_sheet.append([key, _export_comment_value(value)])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _stream_export(
    rows: list[dict[str, Any]],
    *,
    fmt: str,
    term: str,
    total_matches: int,
    exported_rows: int,
    export_cap: int,
    truncated: bool,
    query_params: dict[str, Any],
    index_provenance: dict[str, Any],
    excel_de: bool = False,
) -> StreamingResponse:
    timestamp = datetime.now(timezone.utc).isoformat()

    if fmt in {"csv", "tsv"}:
        # Default CSV stays byte-identical; the opt-in excel-de dialect swaps
        # the delimiter to ';' and prefixes a UTF-8 BOM so German Excel
        # installations open the file with correct columns and umlauts.
        if fmt == "tsv":
            delimiter = "\t"
        elif excel_de:
            delimiter = ";"
        else:
            delimiter = ","
        header = _EXPORT_TABULAR_HEADER

        def _gen_tabular():
            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
            prelude = "\n".join(
                _export_tabular_provenance_lines(
                    fmt=fmt,
                    term=term,
                    total_matches=total_matches,
                    exported_rows=exported_rows,
                    export_cap=export_cap,
                    truncated=truncated,
                    timestamp=timestamp,
                    query_params=query_params,
                    index_provenance=index_provenance,
                )
            ) + "\n"
            yield ("\ufeff" + prelude) if excel_de else prelude
            writer.writerow(header)
            yield buf.getvalue()
            for row in rows:
                buf.seek(0)
                buf.truncate(0)
                payload = _export_row_payload(row)
                writer.writerow([_export_tabular_cell(payload, col) for col in header])
                yield buf.getvalue()

        ext = fmt
        media = "text/tab-separated-values" if fmt == "tsv" else "text/csv"
        generator = _gen_tabular()
    elif fmt == "xlsx":
        payload_bytes = _build_xlsx_export(
            rows,
            provenance_fields=_export_provenance_fields(
                fmt=fmt,
                term=term,
                total_matches=total_matches,
                exported_rows=exported_rows,
                export_cap=export_cap,
                truncated=truncated,
                timestamp=timestamp,
                query_params=query_params,
                index_provenance=index_provenance,
            ),
        )
        ext = "xlsx"
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        generator = iter([payload_bytes])
    elif fmt == "jsonl":
        def _gen_jsonl():
            header = {
                "type": "header",
                "term": term,
                # `total` remains a compatibility alias, but now means the
                # exact match denominator rather than the number written.
                "total": total_matches,
                "total_matches": total_matches,
                "exported_rows": exported_rows,
                "export_cap": export_cap,
                "truncated": truncated,
                "timestamp": timestamp,
                "query": query_params,
                "indexFingerprint": index_provenance.get("indexFingerprint"),
                "metadataSchemaHash": index_provenance.get("metadataSchemaHash"),
                "fingerprintStrength": index_provenance.get("fingerprintStrength"),
            }
            yield _json.dumps(header, ensure_ascii=False) + "\n"
            for row in rows:
                yield _json.dumps(_export_row_payload(row), ensure_ascii=False) + "\n"

        ext = "jsonl"
        media = "application/x-ndjson"
        generator = _gen_jsonl()
    else:  # json

        def _gen_json():
            head = (
                "{"
                f"\"term\":{_json.dumps(term, ensure_ascii=False)},"
                f"\"total\":{int(total_matches)},"
                f"\"total_matches\":{int(total_matches)},"
                f"\"exported_rows\":{int(exported_rows)},"
                f"\"export_cap\":{int(export_cap)},"
                f"\"truncated\":{'true' if truncated else 'false'},"
                f"\"timestamp\":{_json.dumps(timestamp, ensure_ascii=False)},"
                f"\"query\":{_json.dumps(query_params, ensure_ascii=False)},"
                f"\"indexFingerprint\":{_json.dumps(index_provenance.get('indexFingerprint'), ensure_ascii=False)},"
                f"\"metadataSchemaHash\":{_json.dumps(index_provenance.get('metadataSchemaHash'), ensure_ascii=False)},"
                f"\"fingerprintStrength\":{_json.dumps(index_provenance.get('fingerprintStrength'), ensure_ascii=False)},"
                "\"rows\":["
            )
            yield head
            first = True
            for row in rows:
                prefix = "" if first else ","
                first = False
                yield prefix + _json.dumps(_export_row_payload(row), ensure_ascii=False)
            yield "]}"

        ext = "json"
        media = "application/json"
        generator = _gen_json()

    filename = f"concordance.{ext}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        # Existing clients use this header; retain it as the exact total.
        "X-CandyConc-Export-Total": str(int(total_matches)),
        "X-CandyConc-Export-Total-Matches": str(int(total_matches)),
        "X-CandyConc-Export-Exported-Rows": str(int(exported_rows)),
        "X-CandyConc-Export-Cap": str(int(export_cap)),
        "X-CandyConc-Export-Truncated": "1" if truncated else "0",
        "X-CandyConc-Index-Fingerprint": str(index_provenance.get("indexFingerprint") or ""),
    }
    return StreamingResponse(generator, media_type=media, headers=headers)


def _export_sort_dir(value: str | None) -> str:
    """Validate the export sort direction, defaulting to ascending.

    Mirrors ``sort_kwic_rows``' accepted vocabulary but rejects anything else
    with a 400 so a typo cannot silently fall through to ascending.
    """
    raw = str(value or "asc").strip().lower()
    if raw not in {"asc", "desc"}:
        raise ApiError(
            422,
            "export.sort_dir_invalid",
            lt("sort_dir muss 'asc' oder 'desc' sein", "sort_dir must be 'asc' or 'desc'"),
        )
    return raw


async def _export_concordance_impl(
    _server: Any,
    *,
    query: str,
    corpus: str | None,
    docset_id: str | None,
    sort: str | None,
    sort_dir: str,
    case_insensitive: bool,
    ctx: int,
    fmt: str,
    excel_de: bool = False,
) -> StreamingResponse:
    term = str(query or "").strip()
    if not term:
        raise ApiError(422, "query.missing", lt("query fehlt", "query is missing"))
    safe_ctx = _server._bounded_query_context(ctx)
    safe_sort_dir = _export_sort_dir(sort_dir)
    idx = _server.get_corpus(corpus)
    index_provenance = _export_index_provenance(_server, idx, corpus or "default")
    docset_mask = None
    if docset_id:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != (corpus or "default"):
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")

    rows, total_matches, truncated = await _collect_export_rows(
        _server,
        idx,
        term=term,
        ctx=int(safe_ctx),
        docset_mask=docset_mask,
        sort_by=sort,
        sort_dir=safe_sort_dir,
        case_insensitive=bool(case_insensitive),
    )
    query_params = {
        "query": term,
        "corpus": corpus or "default",
        "docset_id": docset_id or None,
        "sort": sort or None,
        "sort_dir": safe_sort_dir,
        "case_insensitive": bool(case_insensitive),
        "ctx": int(safe_ctx),
        "format": fmt,
    }
    if excel_de:
        # Only recorded when active so the default CSV stays byte-identical.
        query_params["dialect"] = "excel-de"
    return _stream_export(
        rows,
        fmt=fmt,
        term=term,
        total_matches=total_matches,
        exported_rows=len(rows),
        export_cap=_EXPORT_HIT_CAP,
        truncated=truncated,
        query_params=query_params,
        index_provenance=index_provenance,
        excel_de=excel_de,
    )


_CONCORDANCE_EXPORT_RESPONSES = {
    200: {
        "content": {
            "text/csv": {"example": (
                "# CandyConc Export\n# Schema: candyconc-concordance-export-v1\n"
                "pos,doc_id,doc,left,node,right,meta,match,match_start,match_end\n"
                '1104,0,sotu-1945-Truman,"of religious tolerance, political",freedom,'
                'and economic opportunity. For,"{}",political freedom,1103,1104\n'
            )},
            "text/tab-separated-values": {"example": (
                "# CandyConc Export\n# Schema: candyconc-concordance-export-v1\n"
                "pos\tdoc_id\tdoc\tleft\tnode\tright\tmeta\tmatch\tmatch_start\tmatch_end\n"
                "1104\t0\tsotu-1945-Truman\tof religious tolerance, political\tfreedom\t"
                "and economic opportunity. For\t{}\tpolitical freedom\t1103\t1104\n"
            )},
            "application/json": {"example": {
                "term": 'cql:[pos="ADJ"] [lemma="freedom"]',
                "total_matches": 1,
                "exported_rows": 1,
                "truncated": False,
                "rows": [{
                    "pos": 1104, "doc_id": 0, "doc": "sotu-1945-Truman",
                    "left": "of religious tolerance, political", "node": "freedom",
                    "right": "and economic opportunity. For", "meta": {},
                    "match": "political freedom", "match_start": 1103, "match_end": 1104,
                }],
            }},
            "application/x-ndjson": {"example": (
                '{"type":"header","term":"cql:[pos=\\"ADJ\\"] [lemma=\\"freedom\\"]","total_matches":1}\n'
                '{"pos":1104,"doc_id":0,"doc":"sotu-1945-Truman","node":"freedom",'
                '"match":"political freedom","match_start":1103,"match_end":1104}\n'
            )},
        }
    }
}


@router.post(
    "/export/concordance",
    tags=["export"],
    responses=_CONCORDANCE_EXPORT_RESPONSES,
)
async def export_concordance_post(
    payload: ConcordanceExportRequest = Body(
        ...,
        examples={
            "basic": {
                "summary": "Full export of all hits",
                "value": {"query": "freedom", "docset_id": "a1b2c3", "format": "csv"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> StreamingResponse:
    """Stream a bounded concordance row set with an exact match denominator.

    The rows carry the node (pos, node), its context (left, right), the whole
    hit (match, match_start, match_end) and the document metadata.

    \f
    Das Body-Modell ist absichtlich permissiv (reine OpenAPI-Dokumentation).
    Die handgeschriebenen 422-Prüfungen darunter bleiben die Wahrheit.
    """
    from .. import server as _server

    _server._require_user_access(token)
    # NACH der Zugriffspruefung: erst autorisieren, dann Eingaben
    # pruefen. Andernfalls verraet die 422-Meldung einem nicht
    # autorisierten Aufrufer, welche Filter der Export kennt.
    # ``extra: allow`` nimmt jedes Feld entgegen. Fuer date und genre gibt
    # es hier KEINE Auswertung: der Export lief ungefiltert und schwieg
    # darueber, also wieder "ein Filter bewirkt nichts und meldet Erfolg",
    # diesmal auf einem Ausgabepfad, dessen Ergebnis der Nutzer weiter
    # verarbeitet. Ein Filter, den diese Route nicht kennt, wird benannt.
    _nicht_ausgewertet = sorted(
        f for f in ("date", "genre")
        if str(getattr(payload, f, "") or "").strip()
    )
    if _nicht_ausgewertet:
        raise ApiError(
            422,
            "export.filters_unsupported",
            lt(
                "Der Konkordanz-Export wertet {fields} nicht aus. Den Ausschnitt "
                "vorher als Docset anlegen (/analysis/docset_from_meta) und "
                "docset_id übergeben.",
                "The concordance export does not evaluate {fields}. Create the "
                "selection as a document set first (/analysis/docset_from_meta) "
                "and pass docset_id.",
            ),
            fields=", ".join(_nicht_ausgewertet),
        )

    payload = request_body_as_dict(payload)
    # Accept both snake_case and camelCase aliases in the JSON body.
    if "case_insensitive" in payload:
        body_ci = bool(payload.get("case_insensitive"))
    elif "caseInsensitive" in payload:
        body_ci = bool(payload.get("caseInsensitive"))
    else:
        body_ci = True
    if "sort_dir" in payload:
        body_sort_dir = payload.get("sort_dir")
    elif "sortDir" in payload:
        body_sort_dir = payload.get("sortDir")
    else:
        body_sort_dir = "asc"
    fmt = _export_format(payload.get("format"))
    return await _export_concordance_impl(
        _server,
        query=str(payload.get("query") or ""),
        corpus=payload.get("corpus"),
        docset_id=payload.get("docset_id"),
        sort=payload.get("sort"),
        sort_dir=body_sort_dir,
        case_insensitive=body_ci,
        ctx=int(payload.get("ctx", 5) or 5),
        fmt=fmt,
        excel_de=_export_excel_de(payload, fmt),
    )


async def _export_evidence_package_impl(
    _server: Any,
    *,
    query: str,
    corpus: str | None,
    docset_id: str | None,
    sort: str | None,
    sort_dir: str,
    case_insensitive: bool,
    ctx: int,
    include_rows: bool,
) -> dict[str, Any]:
    term = str(query or "").strip()
    if not term:
        raise ApiError(422, "query.missing", lt("query fehlt", "query is missing"))
    safe_ctx = _server._bounded_query_context(ctx)
    safe_sort_dir = _export_sort_dir(sort_dir)
    corpus_name = corpus or "default"
    idx = _server.get_corpus(corpus)
    index_provenance = _export_index_provenance(_server, idx, corpus_name)
    docset_mask = None
    docset_fingerprint = None
    if docset_id:
        docset = _server._get_docset(str(docset_id))
        if docset.get("corpus") != corpus_name:
            raise ApiError(422, "docset.corpus_mismatch", lt("Docset passt nicht zum Korpus", "Document set does not match the corpus"))
        docset_mask = docset.get("docset_mask")
        docset_fingerprint = _stable_sha256(
            {
                "docset_id": docset_id,
                "corpus": docset.get("corpus"),
                "filter_spec": docset.get("filter_spec"),
                "meta_schema_hash": docset.get("meta_schema_hash"),
            }
        )

    rows, total_matches, truncated = await _collect_export_rows(
        _server,
        idx,
        term=term,
        ctx=int(safe_ctx),
        docset_mask=docset_mask,
        sort_by=sort,
        sort_dir=safe_sort_dir,
        case_insensitive=bool(case_insensitive),
    )
    row_payloads = [_export_row_payload(row) for row in rows]
    row_hash = _stable_sha256(row_payloads)
    query_params = {
        "query": term,
        "corpus": corpus_name,
        "docset_id": docset_id or None,
        "sort": sort or None,
        "sort_dir": safe_sort_dir,
        "case_insensitive": bool(case_insensitive),
        "ctx": int(safe_ctx),
    }
    query_trace_id = (
        _server._new_query_trace_id()
        if hasattr(_server, "_new_query_trace_id")
        else f"qtr_{row_hash[:32]}"
    )
    package_id = "evp_" + _stable_sha256(
        {
            "query_trace_id": query_trace_id,
            "query": query_params,
            "row_hash_sha256": row_hash,
        }
    )[:24]
    generated_at = datetime.now(timezone.utc).isoformat()
    index_fingerprint = str(index_provenance.get("indexFingerprint") or "")
    corpus_fingerprint = _stable_sha256(
        {
            "index_fingerprint": index_fingerprint,
            "docset_id": docset_id,
            "docset_fingerprint": docset_fingerprint,
        }
    )
    evidence: dict[str, Any] = {
        "schema_version": "candyconc-evidence-package-v1",
        "package_id": package_id,
        "generated_at": generated_at,
        "query_trace_id": query_trace_id,
        "scope": query_params,
        "corpus": {
            "name": index_provenance.get("corpus") or corpus_name,
            "fingerprint_sha256": corpus_fingerprint,
            "indexFingerprint": index_fingerprint,
            "index_fingerprint": index_fingerprint,
            "metadataSchemaHash": index_provenance.get("metadataSchemaHash"),
            "fingerprintStrength": index_provenance.get("fingerprintStrength"),
            "cacheSignature": index_provenance.get("cacheSignature"),
            "docset_id": docset_id or None,
            "docset_fingerprint_sha256": docset_fingerprint,
        },
        "result_summary": {
            # `observed_hit_count` is retained for older readers and names the
            # capped collection. New readers must use the explicit fields below.
            "observed_hit_count": len(row_payloads),
            "total_matches": int(total_matches),
            "exported_rows": len(row_payloads),
            "export_cap": _EXPORT_HIT_CAP,
            "rows_included": len(row_payloads) if include_rows else 0,
            "truncated": bool(truncated),
            "complete_within_export_cap": not truncated,
            "row_hash_sha256": row_hash,
        },
        "method_blocks": [
            {
                "id": "kwic_query_runtime",
                "label": "KWIC query runtime",
                "parameters": query_params,
                "limits": [
                    "Rows are collected by the same query runtime used by the KWIC view.",
                    "If truncated=true, the package is not a complete hit list.",
                ],
            },
            {
                "id": "evidence_package",
                "label": "Evidence package",
                "parameters": {
                    "include_rows": bool(include_rows),
                    "row_hash_sha256": row_hash,
                    "schema_version": "candyconc-evidence-package-v1",
                },
                "limits": [
                    "This JSON package is provenance evidence, not an interpretative prose report.",
                    "PDF/DOCX rendering must preserve this package metadata to be citeable.",
                ],
            },
        ],
    }
    if include_rows:
        evidence["rows"] = row_payloads
    return evidence


@router.post("/export/evidence-package", tags=["export"])
async def export_evidence_package_post(
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Reproducible evidence package",
                "value": {"query": "freedom", "docset_id": "a1b2c3"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _rate: Annotated[None, Depends(rate_limit.dependency)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> dict[str, Any]:
    """Build a machine-readable provenance package for replay/report export."""
    from .. import server as _server

    _server._require_user_access(token)
    if "case_insensitive" in payload:
        body_ci = bool(payload.get("case_insensitive"))
    elif "caseInsensitive" in payload:
        body_ci = bool(payload.get("caseInsensitive"))
    else:
        body_ci = True
    if "sort_dir" in payload:
        body_sort_dir = payload.get("sort_dir")
    elif "sortDir" in payload:
        body_sort_dir = payload.get("sortDir")
    else:
        body_sort_dir = "asc"
    return await _export_evidence_package_impl(
        _server,
        query=str(payload.get("query") or ""),
        corpus=payload.get("corpus"),
        docset_id=payload.get("docset_id"),
        sort=payload.get("sort"),
        sort_dir=body_sort_dir,
        case_insensitive=body_ci,
        ctx=int(payload.get("ctx", 5) or 5),
        include_rows=bool(payload.get("include_rows", True)),
    )
