"""Observable ProductOperation run status routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException

from candyconc.entrypoints.errors import CandyAPIRouter
from candyconc.services.backend import auth
from candyconc.services.backend.operation_runs import operation_run_registry
from candyconc.services.backend.schemas import OperationRunSnapshot

router = CandyAPIRouter()


@router.get(
    "/operation-runs/{run_id}",
    response_model=OperationRunSnapshot,
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "run_id": "abc123",
                        "job_id": "abc123",
                        "operation_id": "settings.embedding_management.download",
                        "source_id": "jina-embeddings-v3",
                        "kind": "operation",
                        "label": "Embedding download: jina-embeddings-v3",
                        "status": "running",
                        "phase": "download",
                        "progress": 40,
                        "message": "Downloading the embedding package.",
                        "error": None,
                        "result_ref": None,
                        "readiness": "pending",
                        "warnings": [],
                        "evidence": {},
                        "created_at": "2026-06-20T10:00:00+00:00",
                        "updated_at": "2026-06-20T10:01:00+00:00",
                        "finished_at": None,
                    }
                }
            }
        }
    },
)
async def operation_run_status(
    run_id: str,
    _auth: Annotated[None, Depends(auth.require_role("admin"))] = None,
) -> dict[str, Any]:
    """Return the current backend-owned status for a long-running operation."""

    run = operation_run_registry.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Operation run not found")
    return run.to_dict()
