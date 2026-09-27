"""Corpus catalogue, lifecycle, and import routes.

The catalogue endpoints remain cheap and safe for normal users. Import mutation,
report, and activation endpoints are admin-only because local paths, logs, and
reject reports can contain sensitive corpus data.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any, Dict, Literal, Mapping

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, localize, lt
from candyconc.services.backend import corpus_import_jobs
from candyconc.utils.import_builders import normalize_import_method
from .. import auth

logger = logging.getLogger(__name__)

router = CandyAPIRouter()
CORPUS_BUILD_REPORT_SCHEMA_VERSION = "corpus-build-report-v1"


class CorpusImportReportsResponse(BaseModel):
    """Versioned report envelope for a retained import job."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["corpus-import-reports-v1"]
    job_id: str
    reports: Dict[str, Any]


class CorpusBuildReportResponse(BaseModel):
    """Versioned report envelope for a registered corpus."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["corpus-build-report-v1"]
    corpus: str
    path: str | None = None
    reports: Dict[str, Any]


def _corpus_dir_and_default():
    """Lazily fetch (_CORPUS_DIR, default_index_path) from the server module."""
    from .. import server as _server

    try:
        default_path = _server._configured_default_index_path()
    except Exception:
        default_path = None
    return _server._CORPUS_DIR, default_path


def _registry_service():
    from candyconc.services.backend.corpus_registry_service import CorpusRegistryService

    corpus_dir, default_path = _corpus_dir_and_default()
    return CorpusRegistryService(corpus_dir, default_path)


def _managed_corpus_dir() -> Path:
    corpus_dir, _default_path = _corpus_dir_and_default()
    return Path(corpus_dir).expanduser().resolve(strict=False)


def _import_register_success(path: str | Path, *, target_name: str, activate: bool) -> Dict[str, Any]:
    """Register an imported corpus and reload runtime state when activated."""
    result = _registry_service().register(Path(path), activate=bool(activate))
    if activate:
        from .. import server as _server

        asyncio.run(_server.reload_default_corpus_runtime_state())
    return result


def _report_data(reports: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        item = reports.get(name)
        if isinstance(item, Mapping) and "data" in item:
            return item.get("data")
        if item is not None:
            return item
    return None


def _validate_import_method(method: object) -> str:
    normalized = normalize_import_method(str(method or ""))
    supported = {
        normalize_import_method(item)
        for item in corpus_import_jobs.supported_import_methods()
    }
    if not normalized or normalized not in supported:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_import_method",
                "method": str(method or ""),
                "supported": sorted(supported),
            },
        )
    return normalized


def _validate_target_name(value: object) -> str:
    name = str(value or "").strip()
    path = Path(name)
    if (
        not name
        or path.is_absolute()
        or path.name != name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise ApiError(400, "import.target_name_unsafe", lt("target_name ist kein sicherer Korpusname", "target_name is not a safe corpus name"))
    return name


def _build_report_for_corpus(corpus: str) -> Dict[str, Any]:
    summary = _registry_service().inspect(corpus)
    path = Path(str(summary.get("path") or "")).expanduser().resolve(strict=False)
    if not path.is_dir():
        raise FileNotFoundError(lt("Korpusverzeichnis nicht gefunden: {path}", "Corpus directory not found: {path}").format(path=path))
    reports = corpus_import_jobs.load_reports_from_dirs((path,))
    normalized_reports = {
        "build_report": _report_data(reports, "build_report.json", "build-report.json"),
        "build_report_md": _report_data(reports, "build_report.md", "build-report.md"),
        "reject_report": _report_data(reports, "reject_report.json", "reject-report.json"),
        "manifest": _report_data(reports, "index_manifest.json"),
        "build_meta": _report_data(reports, "index_build_meta.json"),
        "vrt_import_report": _report_data(reports, "vrt_import_report.json", "vrt-import-report.json"),
        "import_outcome": _report_data(reports, "import_outcome.json"),
        "raw": reports,
    }
    return {
        "schema_version": CORPUS_BUILD_REPORT_SCHEMA_VERSION,
        "corpus": summary.get("name") or corpus,
        "path": str(path),
        "reports": normalized_reports,
        # Legacy compatibility for clients still reading flattened report keys.
        **normalized_reports,
    }


@router.get("/corpora", tags=["corpora"])
async def list_corpora_route(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:
    """List available corpora with token/doc counts and capability flags."""
    corpora = await asyncio.to_thread(lambda: _registry_service().list_corpora())
    return localize({"corpora": corpora, "count": len(corpora)})


@router.get("/corpora/import-methods", tags=["corpora"])
async def list_corpus_import_methods_route(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """List the first-class import methods supported by the backend."""
    methods = corpus_import_jobs.import_method_descriptors()
    return localize({"methods": methods, "count": len(methods)})


@router.post("/corpora/import-preflight", tags=["corpora"])
async def corpus_import_preflight_route(
    payload: Dict[str, Any],
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Inspect a corpus import input without mutating files or starting a job."""
    method = payload.get("method") or payload.get("importMethod")
    input_path = payload.get("input_path") or payload.get("inputPath") or payload.get("input") or payload.get("path")
    method_key = _validate_import_method(method)
    return localize(await asyncio.to_thread(
        corpus_import_jobs.preflight_import_job,
        method_key,
        str(input_path or ""),
        {**dict(payload), "__managed_corpus_dir": str(_managed_corpus_dir())},
    ))


@router.post("/corpora/imports", status_code=status.HTTP_202_ACCEPTED, tags=["corpora"])
async def create_corpus_import_route(
    payload: Dict[str, Any],
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Start an observable corpus import job."""
    method = payload.get("method") or payload.get("importMethod")
    input_path = payload.get("input_path") or payload.get("inputPath") or payload.get("input") or payload.get("path")
    target_name = payload.get("target_name") or payload.get("targetName")
    if not str(input_path or "").strip():
        raise ApiError(400, "import.input_path_missing", lt("input_path fehlt", "input_path is missing"))
    if not target_name and input_path:
        target_name = Path(str(input_path)).stem
    method_key = _validate_import_method(method)
    safe_target_name = _validate_target_name(target_name)
    options = dict(payload)
    preflight = await asyncio.to_thread(
        corpus_import_jobs.preflight_import_job,
        method_key,
        str(input_path or ""),
        {**options, "target_name": safe_target_name, "__managed_corpus_dir": str(_managed_corpus_dir())},
    )
    if preflight.get("blocking") or preflight.get("ok") is False or preflight.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail={
                "message": lt("Import-Preflight blockiert den Import.", "The import preflight check blocks the import."),
                "preflight": preflight,
            },
        )
    try:
        return localize(await asyncio.to_thread(
            corpus_import_jobs.start_import_job,
            method=method_key,
            input_path=str(input_path or ""),
            target_name=safe_target_name,
            corpora_dir=_managed_corpus_dir(),
            activate_on_success=bool(
                payload.get("activate_on_success") or payload.get("activateOnSuccess") or payload.get("activate")
            ),
            register_success=_import_register_success,
            run_inline=False,
            options=options,
        ))
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.get("/corpora/imports", tags=["corpora"])
async def list_corpus_imports_route(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """List observable import jobs retained by the backend service."""
    jobs = await asyncio.to_thread(corpus_import_jobs.list_import_jobs)
    return localize({"jobs": jobs, "count": len(jobs)})


@router.get("/corpora/imports/{job_id}", tags=["corpora"])
async def get_corpus_import_route(
    job_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return the latest snapshot for one corpus import job."""
    try:
        return localize(await asyncio.to_thread(corpus_import_jobs.get_import_job, job_id))
    except KeyError as exc:
        raise ApiError(404, "import.job_not_found", lt("Importjob nicht gefunden", "Import job not found")) from exc


@router.post("/corpora/imports/{job_id}/cancel", tags=["corpora"])
async def cancel_corpus_import_route(
    job_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Cancel a running or queued corpus import job."""
    try:
        return localize(await asyncio.to_thread(corpus_import_jobs.cancel_import_job, job_id))
    except KeyError as exc:
        raise ApiError(404, "import.job_not_found", lt("Importjob nicht gefunden", "Import job not found")) from exc


@router.get(
    "/corpora/imports/{job_id}/reports",
    tags=["corpora"],
    response_model=CorpusImportReportsResponse,
)
async def get_corpus_import_reports_route(
    job_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return bounded build/reject/manifest reports for one import job."""
    try:
        return localize(await asyncio.to_thread(corpus_import_jobs.get_import_reports, job_id))
    except KeyError as exc:
        raise ApiError(404, "import.job_not_found", lt("Importjob nicht gefunden", "Import job not found")) from exc


@router.get(
    "/corpora/{corpus}/build-report",
    tags=["corpora"],
    response_model=CorpusBuildReportResponse,
)
async def corpus_build_report_route(
    corpus: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Return build/report artifacts for an already registered or managed corpus."""
    try:
        return localize(await asyncio.to_thread(_build_report_for_corpus, corpus))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.get("/corpora/{corpus}/capabilities", tags=["corpora"])
async def corpus_capabilities_route(
    corpus: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:
    """Return the capability surface (manifest-declared + file-detected) for one corpus."""
    # Dot-prefixed entries (e.g. '.imports') are internal staging dirs the catalog
    # hides (corpus_registry_service._iter_refs). A direct capability query for one
    # must 404 — consistent with the catalog — not surface it as a 409 incomplete.
    if corpus.strip().lstrip("/").startswith("."):
        raise ApiError(404, "corpus.not_found", lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"), name=corpus)
    try:
        summary = await asyncio.to_thread(lambda: _registry_service().inspect(corpus))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    if summary.get("status") == "ready":
        return localize(summary)
    if summary.get("status") == "missing" and summary.get("source") == "managed":
        raise ApiError(404, "corpus.not_found", lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}"), name=corpus)
    raise HTTPException(
        status_code=409,
        detail={
            "status": summary.get("status"),
            "reason": summary.get("status_reason") or lt("Korpus ist nicht bereit", "Corpus is not ready"),
            "corpus": summary.get("name"),
        },
    )


@router.post("/corpora/register", tags=["corpora"])
async def register_corpus_route(
    payload: Dict[str, Any],
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, Any]:
    """Register an existing index directory without deleting or importing files."""
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ApiError(400, "corpus.path_missing", lt("path fehlt", "path is missing"))
    try:
        def _register() -> Dict[str, Any]:
            return _registry_service().register(
                Path(path),
                activate=bool(payload.get("activate")),
                acknowledge_partial_input=bool(
                    payload.get("acknowledge_partial_input")
                    or payload.get("acknowledgePartialInput")
                ),
            )

        result = await asyncio.to_thread(_register)
        if result.get("active"):
            from .. import server as _server

            await _server.reload_default_corpus_runtime_state()
        return localize(result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.post("/corpora/{corpus}/activate", tags=["corpora"])
async def activate_corpus_route(
    corpus: str,
    payload: Dict[str, Any] | None = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Mark a ready corpus as the active registered corpus.

    Switching the active corpus is a normal read-side user action (the web
    "switch corpus" control calls this so the server stays the single source of
    truth for "active corpus"), so it only requires the ``user`` role. Importing
    and deleting corpora remain admin-only.
    """
    try:
        def _activate() -> Dict[str, Any]:
            service = _registry_service()
            # A truly-unknown corpus must read 404, not 409: only a corpus that
            # exists-but-is-not-ready is a conflict. Mirror the capabilities route.
            summary = service.inspect(corpus)
            if summary.get("status") == "missing" and summary.get("source") == "managed":
                raise FileNotFoundError(lt("Korpus nicht gefunden: {name}", "Corpus not found: {name}").format(name=corpus))
            return service.activate(
                corpus,
                acknowledge_partial_input=bool(
                    (payload or {}).get("acknowledge_partial_input")
                    or (payload or {}).get("acknowledgePartialInput")
                ),
            )

        from .. import server as _server

        vorschau = await asyncio.to_thread(
            lambda: _registry_service().inspect(corpus)
        )
        # Check whether activation changes the index used for queries. An
        # environment or config pin overrides the registry. Keep the requested
        # registry activation but report when the pin prevents it taking effect.
        hindernis = _server.aktivierung_wirkungslos(vorschau.get("path"))

        result = await asyncio.to_thread(_activate)
        await _server.reload_default_corpus_runtime_state()
        if hindernis:
            logger.warning("Aktivierung ohne Wirkung auf Abfragen: %s", hindernis)
            # Nur im Problemfall annotieren: eine Warnung, die immer da
            # steht, liest niemand mehr.
            if isinstance(result, dict):
                result = {
                    **result,
                    "wirksam_fuer_abfragen": False,
                    "warnung": hindernis,
                    "effective_for_copilot": False,
                    "notice": lt(
                        "Suchen und Analysen in diesem Fenster verwenden das ausgewählte Korpus. "
                        "Der Copilot verwendet weiter das Korpus, mit dem der Server gestartet wurde "
                        "(CANDYCONC_INDEX_PATH oder index_dir). Damit auch der Copilot wechselt, "
                        "den Server ohne diese Einstellung neu starten.",
                        "Searches and analyses in this window use the selected corpus. "
                        "The copilot keeps using the corpus the server was started with "
                        "(CANDYCONC_INDEX_PATH or index_dir). Restart the server without "
                        "that setting to switch the copilot as well.",
                    ),
                }
        return localize(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


@router.delete("/corpora/{corpus}/registration", tags=["corpora"])
async def unregister_corpus_route(
    corpus: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Remove a corpus from the registry without deleting files."""
    try:
        def _unregister() -> Dict[str, str]:
            return _registry_service().unregister(corpus)

        result = await asyncio.to_thread(_unregister)
        from .. import server as _server

        await _server.reload_default_corpus_runtime_state()
        return localize(result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc


def _delete_registered_corpus(corpus: str) -> Dict[str, str]:
    """Unregister ``corpus`` from the registry, guarding active/last removal.

    Resolves the corpus name against the registry's registered indices (the
    default corpus and managed-but-unregistered dirs are not deletable here),
    then delegates to :meth:`CorpusRegistry.delete`, which refuses to drop the
    active or last corpus. Files on disk are intentionally left untouched.
    """
    from candyconc.domain.corpus import CorpusRegistry

    wanted = str(corpus or "").strip()
    if not wanted or wanted.lower() == "default":
        raise RuntimeError(lt("Der Standard-Korpus kann nicht gelöscht werden", "The default corpus cannot be deleted"))
    reg = CorpusRegistry.load()
    matches = [
        Path(raw).expanduser().resolve(strict=False)
        for raw in reg.indices
        if Path(raw).name == wanted
    ]
    if not matches:
        raise FileNotFoundError(lt("Registrierter Korpus nicht gefunden: {name}", "Registered corpus not found: {name}").format(name=wanted))
    path = matches[0]
    reg.delete(path)
    return {"status": "ok", "name": wanted, "path": str(path)}


@router.delete("/corpora/{corpus}", tags=["corpora"])
async def delete_corpus_route(
    corpus: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Delete (unregister) a corpus, refusing the active or last corpus.

    Admin-only. Removes the corpus from the registry so it disappears from the
    catalogue and can no longer be activated. The active corpus and the last
    remaining registered corpus are protected with a ``409`` so the server keeps
    a single, valid active corpus.
    """
    try:
        result = await asyncio.to_thread(_delete_registered_corpus, corpus)
        from .. import server as _server

        await _server.reload_default_corpus_runtime_state()
        return localize(result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exception_text(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc
