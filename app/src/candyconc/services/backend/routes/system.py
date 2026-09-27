"""Operational backend routes kept out of the main concordance server module."""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from pathlib import Path
import json
from typing import Annotated, Any

from fastapi import Body, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from candyconc import paths as _user_paths
from candyconc.config import APP_CONFIG
from candyconc.entrypoints.errors import CandyAPIRouter
from candyconc.i18n import exception_text, lt

# Import mutation-only cache objects and pure helpers directly. Read
# rebound byte counters through the server module.
from ..alignment import _REFDOC_INDEX_CACHE, _REFDOC_INDEX_DOC_COUNT
from ..doc_meta import _doc_count_for_index
from ..docsets import _DOCSET_CACHE
from ..query_count import _QUERY_COUNT_CACHE, _QUERY_COUNT_THREAD_LOCK

from .. import auth, metrics, model_route

router = CandyAPIRouter()


def _cache_size_text(entries: int) -> str:
    """Size of the document-set cache for the system panel, in both languages."""
    if entries == 1:
        return lt("1 Eintrag", "1 entry")
    return lt("{entries} Einträge", "{entries} entries").format(entries=entries)


def _server():
    from .. import server as _backend_server

    return _backend_server


@router.get("/health")
async def health_endpoint() -> dict[str, str]:
    """Return basic server health status."""
    srv = _server()
    return {"status": "ok", "engine": srv.kwic_adapter.engine}


@router.get("/help")
async def help_endpoint() -> dict[str, Any]:
    """Where the bundled user documentation is served, if the package holds it.

    The help menu reads this before it opens ``/docs/``. Without a packaged
    build the menu says so instead of opening an empty page.
    """
    from .. import docs_static

    srv = _server()
    available = any(
        getattr(route, "name", None) == docs_static.DOCS_MOUNT_NAME for route in srv.app.router.routes
    )
    return {
        "docsAvailable": available,
        "docsUrl": docs_static.DOCS_URL if available else None,
    }


@router.get("/auth/dev-token", include_in_schema=False)
async def dev_token_endpoint() -> dict[str, str]:
    """Issue a guest user-token for LOCAL-FIRST use only."""
    srv = _server()
    if auth.RBAC_ENABLED or not auth.is_local_dev_unsafe_mode():
        raise HTTPException(status_code=404, detail="Not available")
    token = getattr(srv, "_DEV_TOKEN", None)
    if token is None or auth.username_for_token(token) is None:
        token = auth._issue_token(auth.LOCAL_DEV_USERNAME)
        srv._DEV_TOKEN = token
    return {"token": token}


@router.get("/system/info")
async def system_info_endpoint(
    corpus: str | None = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, Any]:
    """Return a compact system snapshot used by the web frontend."""
    srv = _server()
    srv._require_admin_access(token)

    # The package metadata is the single source. CANDYCONC_VERSION may label a
    # deployment explicitly (it used to be read but never took effect).
    from candyconc.version import package_version

    version = os.environ.get("CANDYCONC_VERSION", "").strip() or package_version()
    runtime_facts = {
        "copilotConfigured": bool(APP_CONFIG.copilot_configured),
        "paths": _user_paths.describe(),
    }
    uptime = srv._format_uptime(time.time() - srv._START_TIME)
    if corpus is None and getattr(srv, "_STARTED_WITHOUT_CORPUS", False) and srv._INDEX is None:
        # First start without any corpus: an expected state, not a failure.
        return {
            "version": version,
            "backendVersion": version,
            "uptime": uptime,
            "corpusName": "",
            "tokenCount": 0,
            "documentCount": 0,
            "lastUpdated": None,
            "indexStatus": "error",
            "diskUsage": {"used": 0, "total": int(shutil.disk_usage(Path.home()).total)},
            "faissStatus": "unavailable",
            "vectorCount": 0,
            "cacheSize": _cache_size_text(0),
            "source": "no_corpus",
            **runtime_facts,
        }
    try:
        idx = srv.get_corpus(corpus)
        index_path = idx.path
        token_count = int(idx.token_count())
        try:
            document_count = int(_doc_count_for_index(idx))
        except Exception:
            document_count = 0

        dir_size = srv._dir_size_bytes(index_path)
        disk = None
        with contextlib.suppress(OSError):
            disk = shutil.disk_usage(index_path)
        if disk is None:
            disk = shutil.disk_usage(Path.home())

        last_updated_ts = 0.0
        with contextlib.suppress(OSError):
            last_updated_ts = index_path.stat().st_mtime
        last_updated = (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last_updated_ts))
            if last_updated_ts
            else None
        )

        from candyconc.domain.corpus import corpus_summary

        summary = corpus_summary(index_path)
        semantic_ready = bool(
            summary.get("features", {}).get("semantic", {}).get("passage_search", False)
        )
        faiss_status = (
            "ready"
            if semantic_ready
            else getattr(srv.manager, "faiss_status", "unavailable") or "unavailable"
        )
        if faiss_status not in {"ready", "building", "error", "unavailable"}:
            faiss_status = "unavailable"
        faiss_detail = getattr(srv.manager, "faiss_status_detail", None)
        passages = getattr(srv.manager, "passages", None)
        vector_count = int(len(passages)) if passages is not None else 0
        if semantic_ready:
            try:
                embedding_meta = json.loads((index_path / "embedding_meta.json").read_text("utf-8"))
                vector_count = int((embedding_meta.get("gemma_doc") or {}).get("count") or vector_count)
            except (OSError, ValueError, TypeError):
                pass

        cache_entries = len(_DOCSET_CACHE)

        response: dict[str, Any] = {
            "version": version,
            "backendVersion": version,
            "uptime": uptime,
            "corpusName": index_path.name,
            "tokenCount": token_count,
            "documentCount": document_count,
            "lastUpdated": last_updated,
            "indexStatus": "building" if faiss_status == "building" else "ready",
            "diskUsage": {"used": int(dir_size), "total": int(disk.total)},
            "faissStatus": faiss_status,
            "vectorCount": vector_count,
            "cacheSize": _cache_size_text(cache_entries),
            "source": "backend",
            **runtime_facts,
        }
        if faiss_detail:
            response["faissDetail"] = faiss_detail
        return response
    except Exception as exc:  # pragma: no cover - defensive fallback
        srv.logger.exception("system_info_endpoint failed: %s", exc)
        return {
            "version": version,
            "backendVersion": version,
            "uptime": uptime,
            "corpusName": corpus or "default",
            "tokenCount": 0,
            "documentCount": 0,
            "lastUpdated": None,
            "indexStatus": "error",
            "diskUsage": {"used": 0, "total": int(shutil.disk_usage(Path.home()).total)},
            "faissStatus": "unavailable",
            "vectorCount": 0,
            "cacheSize": _cache_size_text(0),
            "source": "no_corpus" if getattr(srv, "_STARTED_WITHOUT_CORPUS", False) else "backend_degraded_fallback",
            **runtime_facts,
        }


@router.get("/settings/model-route")
async def model_route_get(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, Any]:
    """The model connection the copilot uses.

    The API key is never returned, only whether one is set and its last four
    characters.

    \f
    Welchen Weg der Copilot zum Modell nimmt.

    Der Schluessel selbst wird NIE zurueckgegeben, nur ob einer gesetzt ist
    und seine letzten vier Zeichen.
    """
    srv = _server()
    srv._require_admin_access(token)
    return model_route.stand()


@router.post("/settings/model-route")
async def model_route_set(
    payload: dict[str, Any] = Body(
        ...,
        examples={
            "openrouter": {
                "summary": "Switch to a provider",
                "value": {
                    "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                    "modell": "z-ai/glm-5.3-flash",
                    "schluessel": "sk-or-...",
                },
            },
            "lokal": {
                "summary": "Back to the local model",
                "value": {
                    "endpoint": "http://127.0.0.1:1234/v1/chat/completions",
                    "modell": "local-model",
                },
            },
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, Any]:
    """Change the model connection without a restart.

    The API key can only be written. It stays in the running process and is not
    written to disk.

    \f
    Modellweg umstellen, ohne Neustart.

    Der Schluessel ist NUR schreibbar. Er bleibt im laufenden Prozess und wird
    nicht auf die Platte geschrieben, siehe ``model_route``.
    """
    srv = _server()
    srv._require_admin_access(token)
    try:
        return model_route.setzen(
            endpoint=payload.get("endpoint"),
            modell=payload.get("modell"),
            schluessel=payload.get("schluessel"),
        )
    except model_route.ModellwegFehler as fehler:
        raise HTTPException(status_code=400, detail=exception_text(fehler)) from fehler


@router.post("/system/clear-cache")
async def system_clear_cache(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, Any]:
    """Clear in-memory caches used by the backend."""
    srv = _server()
    srv._require_admin_access(token)

    with srv._QUERY_ROWS_RESPONSE_CACHE_LOCK:
        srv._QUERY_ROWS_RESPONSE_CACHE.clear()
        srv._QUERY_ROWS_RESPONSE_CACHE_BYTES = 0
    with srv._QUERY_STREAM_BATCH_CACHE_LOCK:
        srv._QUERY_STREAM_BATCH_CACHE.clear()
        srv._QUERY_STREAM_BATCH_CACHE_BYTES = 0
    with srv._ANCHOR_POS_CACHE_LOCK:
        srv._ANCHOR_POS_CACHE.clear()
        srv._ANCHOR_POS_CACHE_BYTES = 0
    _REFDOC_INDEX_CACHE.clear()
    _REFDOC_INDEX_DOC_COUNT.clear()
    _DOCSET_CACHE.clear()

    with _QUERY_COUNT_THREAD_LOCK:
        for state in list(_QUERY_COUNT_CACHE.values()):
            if state.task is not None and not state.task.done():
                state.task.cancel()
            if state.cancel_task is not None and not state.cancel_task.done():
                state.cancel_task.cancel()
        _QUERY_COUNT_CACHE.clear()
    try:
        from candyconc.domain import query_eval as query_eval_mod
    except Exception:
        query_eval_mod = None
    if query_eval_mod is not None and hasattr(query_eval_mod, "clear_positions_cache"):
        with contextlib.suppress(Exception):
            query_eval_mod.clear_positions_cache()

    try:
        from candyconc.core import query_runtime as query_runtime_mod
    except Exception:
        query_runtime_mod = None
    if query_runtime_mod is not None and hasattr(query_runtime_mod, "clear_cql_positions_cache"):
        with contextlib.suppress(Exception):
            query_runtime_mod.clear_cql_positions_cache()

    return {"status": "ok", "docsetCacheEntries": len(_DOCSET_CACHE)}


@router.post("/system/rebuild-index")
async def system_rebuild_index(
    payload: dict[str, str] | None = Body(default=None),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, str]:
    """Trigger FAISS rebuild using the existing build pipeline.

    Without stored passage vectors the passages are embedded with the word
    vectors of the corpus pipeline. A corpus without them answers 422
    ``word_vectors.unavailable``, one whose pipeline is not installed 503
    ``word_vectors.service_error``, before a job starts.
    """
    from candyconc.services.backend.query_count import _word_vectors_error

    srv = _server()
    srv._require_admin_access(token)
    corpus = ((payload or {}).get("corpus") or "default").strip() or "default"
    try:
        job_id = await srv.start_faiss_build(corpus)
    except RuntimeError as exc:
        mapped = _word_vectors_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    return {"jobId": job_id, "wsUrl": f"/api/v1/ws/faiss/{job_id}"}


@router.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    """Return Prometheus metrics in text format."""
    return PlainTextResponse(metrics.metrics_text() + _server()._obs_metrics_text())
