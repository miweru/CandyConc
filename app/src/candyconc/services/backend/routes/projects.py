"""Project persistence routes for clusters and analysis presets.

Use local persistence helpers and resolve shared server state lazily
inside handlers to avoid a circular import."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict

import jsonschema
from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import lt
from .. import auth

router = CandyAPIRouter()

# ---------------------------------------------------------------------------
# Cluster schema
#
# The schema was previously loaded from ``schemas/cluster.json``.  The
# JSON content is now embedded directly to avoid runtime file access.
_CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        "label": {"type": "string"},
        "tokens": {"type": "array"},
        "centroid": {"type": "array", "items": {"type": "number"}},
        "size": {"type": ["integer", "number"]},
        "samples": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "label"],
}

_CLUSTER_LOCKS: Dict[str, asyncio.Lock] = {}
_ANALYSIS_PRESET_LOCKS: Dict[str, asyncio.Lock] = {}
_RETIRED_CHI2_PARAM_KEYS = ("metric", "measure", "collocMeasure", "sortBy", "sort_by")


def _safe_project_dir(proj: str) -> Path:
    """Resolve the on-disk dir for a URL ``proj`` id, rejecting path traversal.

    ``proj`` is attacker-controlled (URL path); a value like ``../../etc`` or an
    absolute path would otherwise let cluster writes escape ``_PROJECTS_DIR``.
    """
    from .. import server as _server

    base = _server._PROJECTS_DIR.resolve()
    candidate = (base / str(proj)).resolve()
    if candidate != base and base not in candidate.parents:
        raise ApiError(400, "project.id_invalid", lt("Ungültige Projekt-ID", "Invalid project ID"))
    return candidate


def _analysis_presets_path(project: str) -> Path:
    from .. import server as _server

    safe = _server._safe_project_segment(project)
    path = _server._PROJECTS_DIR / safe
    path.resolve().relative_to(_server._PROJECTS_DIR.resolve())  # reject traversal
    if not _server.DRY_RUN:
        path.mkdir(parents=True, exist_ok=True)
    return path / "analysis_presets.json"


def _migrate_retired_chi2_params(preset: dict) -> bool:
    """Migrate only persisted preset parameters, never stored evidence."""
    params = preset.get("params")
    if not isinstance(params, dict):
        return False
    changed = False
    for key in _RETIRED_CHI2_PARAM_KEYS:
        if params.get(key) == "mi2":
            params[key] = "chi2_cell"
            changed = True
    return changed


def _reject_retired_chi2_params(payload: dict) -> None:
    """Prevent newly saved presets from reintroducing the retired metric name."""
    params = payload.get("params")
    if not isinstance(params, dict):
        return
    for key in _RETIRED_CHI2_PARAM_KEYS:
        if params.get(key) == "mi2":
            raise ApiError(
                422,
                "preset.mi2_replaced",
                lt("params.{key}=mi2 wurde durch chi2_cell ersetzt.", "params.{key}=mi2 has been replaced by chi2_cell."),
                key=key,
            )


def _load_analysis_presets(project: str) -> list[dict]:
    path = _analysis_presets_path(project)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    presets = data.get("presets") if isinstance(data, dict) else data
    if not isinstance(presets, list):
        return []
    changed = any(
        _migrate_retired_chi2_params(preset)
        for preset in presets
        if isinstance(preset, dict)
    )
    if changed:
        _persist_analysis_presets(project, presets)
    return presets


def _persist_analysis_presets(project: str, presets: list[dict]) -> None:
    from .. import server as _server

    if _server.DRY_RUN:
        return
    path = _analysis_presets_path(project)
    payload = {"presets": presets}
    path.write_text(json.dumps(payload), encoding="utf-8")


@router.post("/projects/create")
async def create_project(
    payload: Dict[str, str] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Create a project",
                "value": {"name": "demo", "owner": "admin", "quota": 100000},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> Dict[str, str]:
    """Create a new project owned by ``owner``."""
    from .. import server as _server

    _server._require_admin_access(token)
    name = payload.get("name")
    owner = payload.get("owner")
    quota = int(payload.get("quota", 0))
    if not name or not owner:
        raise HTTPException(status_code=400, detail="Missing name or owner")
    try:
        _server._safe_project_segment(name)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid project name")
    if name in _server._PROJECT_USERS:
        raise HTTPException(status_code=400, detail="Project exists")
    _server._PROJECT_USERS[name] = {owner}
    if quota:
        _server.PROJECT_QUOTAS[name] = quota
    _server._persist_project(name)
    return {"status": "ok"}


@router.put("/projects/{proj}/clusters")
@router.post("/projects/{proj}/clusters")
async def save_clusters(
    proj: str,
    request: Request,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Persist cluster JSON for ``proj``."""
    from .. import server as _server

    _server._user_key(token, proj)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    clusters = data.get("clusters") if isinstance(data, dict) else data
    if not isinstance(clusters, list):
        raise HTTPException(status_code=400, detail="clusters must be list")

    labels: list[str] = []
    for c in clusters:
        if _CLUSTER_SCHEMA is not None:
            with contextlib.suppress(Exception):
                jsonschema.validate(c, _CLUSTER_SCHEMA)
        label = str(c.get("label", "")).strip().lower()
        labels.append(label)
        if len(label.split()) > 3:
            raise HTTPException(
                status_code=400,
                detail={"error": "label too long", "hint": "max 3 tokens"},
            )
    if len(labels) != len(set(labels)):
        raise HTTPException(
            status_code=400,
            detail={"error": "duplicate label", "hint": "labels must be unique"},
        )

    lock = _CLUSTER_LOCKS.setdefault(proj, asyncio.Lock())
    path = _safe_project_dir(proj)
    if not _server.DRY_RUN:
        path.mkdir(parents=True, exist_ok=True)
    async with lock:
        if not _server.DRY_RUN:
            (path / "clusters.json").write_text(json.dumps(data), encoding="utf-8")
    return {"status": "ok"}


@router.get("/projects/{proj}/clusters")
async def load_clusters(
    proj: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> PlainTextResponse:
    """Return persisted clusters for ``proj``."""
    from .. import server as _server

    _server._user_key(token, proj)
    lock = _CLUSTER_LOCKS.setdefault(proj, asyncio.Lock())
    path = _safe_project_dir(proj) / "clusters.json"
    async with lock:
        if not path.exists():
            raise HTTPException(status_code=404, detail="clusters not found")
        text = path.read_text(encoding="utf-8")
    return PlainTextResponse(text, media_type="application/json")


@router.patch(
    "/projects/{proj}/clusters/rename",
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
async def rename_cluster(
    proj: str,
    payload: Dict[str, Any] = Body(
        ...,
        examples={"basic": {"summary": "Rename a cluster", "value": {"id": "1", "label": "politics"}}},
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Rename a cluster and persist the updated list."""
    from .. import server as _server

    user_token = token or payload.get("token")
    _server._user_key(user_token, proj)
    cid = str(payload.get("id", "")).strip()
    label = str(payload.get("label", "")).strip().lower()
    if len(label.split()) > 3:
        raise HTTPException(
            status_code=400,
            detail={"error": "label too long", "hint": "max 3 tokens"},
        )
    path = _safe_project_dir(proj) / "clusters.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="clusters not found")
    lock = _CLUSTER_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        data = json.loads(path.read_text(encoding="utf-8"))
        clusters = (
            data.get("clusters")
            if isinstance(data, dict) and "clusters" in data
            else data
        )
        found = False
        labels: list[str] = []
        for c in clusters:
            cid_val = str(c.get("id", c.get("cluster_id")))
            if cid_val == cid:
                c["label"] = label
                found = True
            labels.append(str(c.get("label", "")).strip().lower())
        if not found:
            raise HTTPException(status_code=404, detail="cluster not found")
        if len(labels) != len(set(labels)):
            raise HTTPException(
                status_code=400,
                detail={"error": "duplicate label", "hint": "labels must be unique"},
            )
        if not _server.DRY_RUN:
            path.write_text(json.dumps(data), encoding="utf-8")
    return {"status": "ok"}


@router.get("/projects/{proj}/analysis-presets")
async def list_analysis_presets(
    proj: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Return saved analysis presets for ``proj``."""
    from .. import server as _server

    _server._user_key(token, proj)
    lock = _ANALYSIS_PRESET_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        presets = _load_analysis_presets(proj)
    return {"presets": presets}


@router.post("/projects/{proj}/analysis-presets")
async def create_analysis_preset(
    proj: str,
    request: Request,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Create or upsert an analysis preset for ``proj``."""
    from .. import server as _server

    _server._user_key(token, proj)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    if isinstance(payload, dict) and "preset" in payload:
        preset = payload.get("preset")
    else:
        preset = payload
    if not isinstance(preset, dict):
        raise HTTPException(status_code=400, detail="preset must be object")
    _reject_retired_chi2_params(preset)

    now = int(time.time() * 1000)
    preset_id = str(preset.get("id") or uuid.uuid4())
    preset["id"] = preset_id
    preset.setdefault("created_at", now)
    preset.setdefault("updated_at", now)
    preset.setdefault("last_accessed_at", preset.get("created_at", now))

    lock = _ANALYSIS_PRESET_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        presets = _load_analysis_presets(proj)
        replaced = False
        for idx, entry in enumerate(presets):
            if str(entry.get("id")) == preset_id:
                presets[idx] = preset
                replaced = True
                break
        if not replaced:
            presets.append(preset)
        _persist_analysis_presets(proj, presets)

    return preset


@router.patch("/projects/{proj}/analysis-presets/{preset_id}")
async def update_analysis_preset(
    proj: str,
    preset_id: str,
    payload: Dict[str, Any] = Body(
        ...,
        examples={
            "basic": {
                "summary": "Update a saved analysis",
                "value": {"name": "Collocations · freedom", "status": "running"},
            }
        },
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Update an existing analysis preset."""
    from .. import server as _server

    _server._user_key(token, proj)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be object")
    _reject_retired_chi2_params(payload)

    lock = _ANALYSIS_PRESET_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        presets = _load_analysis_presets(proj)
        for idx, entry in enumerate(presets):
            if str(entry.get("id")) == preset_id:
                entry.update(payload)
                entry["id"] = preset_id
                entry["updated_at"] = int(time.time() * 1000)
                presets[idx] = entry
                _persist_analysis_presets(proj, presets)
                return entry
    raise HTTPException(status_code=404, detail="preset not found")


@router.post("/projects/{proj}/analysis-presets/{preset_id}/touch")
async def touch_analysis_preset(
    proj: str,
    preset_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, Any]:
    """Update ``last_accessed_at`` for a preset."""
    from .. import server as _server

    _server._user_key(token, proj)
    lock = _ANALYSIS_PRESET_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        presets = _load_analysis_presets(proj)
        for idx, entry in enumerate(presets):
            if str(entry.get("id")) == preset_id:
                entry["last_accessed_at"] = int(time.time() * 1000)
                presets[idx] = entry
                _persist_analysis_presets(proj, presets)
                return entry
    raise HTTPException(status_code=404, detail="preset not found")


@router.delete("/projects/{proj}/analysis-presets/{preset_id}")
async def delete_analysis_preset(
    proj: str,
    preset_id: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> Dict[str, str]:
    """Delete a saved analysis preset."""
    from .. import server as _server

    _server._user_key(token, proj)
    lock = _ANALYSIS_PRESET_LOCKS.setdefault(proj, asyncio.Lock())
    async with lock:
        presets = _load_analysis_presets(proj)
        next_presets = [entry for entry in presets if str(entry.get("id")) != preset_id]
        if len(next_presets) == len(presets):
            raise HTTPException(status_code=404, detail="preset not found")
        _persist_analysis_presets(proj, next_presets)
    return {"status": "ok"}
