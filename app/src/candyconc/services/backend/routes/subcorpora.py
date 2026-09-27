"""Persist named subcorpus definitions and resolve them to live docsets.

The stored definition is durable, while docset_id is an ephemeral cache
reference. Resolving an unchanged definition against an unchanged index
reproduces the same documents. Resolve shared server state at call time."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any, Dict

from fastapi import Body, Depends, HTTPException

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, lt

# Import helpers directly from their owning modules.
from ..doc_meta import _doc_count_for_index
from ..docsets import _store_docset
from .. import auth

router = CandyAPIRouter()

# Sentinel "creator" values that pre-date per-creator authorization (or were
# written by an unauthenticated/dev request). A record owned by one of these is
# treated as legacy/unowned: any authenticated principal may access it so the
# IDOR hardening never locks owners out of their own pre-existing data.
_LEGACY_CREATORS = frozenset({"", "unknown", "anon", "guest"})


def _is_admin(token: str | None) -> bool:
    return auth.role_for_token(token) == "admin"


def _assert_owner_or_admin(creator: str | None, token: str | None) -> None:
    """Authorize a read/mutate against a record's stored ``creator`` (IDOR guard).

    Convention (mirrors ``routes/jobs._assert_job_owner_or_admin``):

    * **RBAC off** (local_dev_unsafe): single-tenant, every caller resolves to the
      same ``guest`` principal, so ownership is a no-op — open access is preserved
      for local dev exactly as before.
    * **Admins** bypass the check (manager+ is the editorial/ops role).
    * A **legacy/sentinel creator** (see ``_LEGACY_CREATORS``) is unowned and
      accessible to any authenticated principal (back-compat: don't lock out
      pre-ownership data).
    * Otherwise the caller must BE the creator; a mismatch is **403 Forbidden**.

    403-vs-404: the resource's existence is already established by the caller's
    own GET/LIST (subcorpus names are listable by everyone in a shared project),
    so hiding existence buys nothing — 403 is the honest, consistent status here.
    """
    if not auth.RBAC_ENABLED:
        return
    if _is_admin(token):
        return
    owner = str(creator or "").strip()
    if owner.lower() in _LEGACY_CREATORS:
        return
    identity = auth.username_for_token(token)
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if owner != identity:
        raise HTTPException(status_code=403, detail="Forbidden")


def _project_or_503() -> Any:
    """Open the Project store, mapping a backing-store failure to HTTP 503.

    ``_get_project`` constructs the on-disk Project (a SQLite-backed store);
    when that backing store is unavailable/locked it raises ``RuntimeError``,
    which previously escaped as an opaque 500. A store-availability failure is a
    transient *service* condition, so it is surfaced as 503 (Service
    Unavailable) per the problem+json contract.
    """
    from .. import server as _server

    try:
        return _server._get_project()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=exception_text(exc)) from exc


def _corpus_schema_hash(corpus: str | None) -> str:
    from .. import server as _server

    try:
        idx = _server.get_corpus(corpus)
        index_path = Path(str(getattr(idx.fast_index, "index_path", "")))
        fp = _server._build_meta_schema_fingerprint(index_path, corpus or "default")
        return str(fp.get("metadataSchemaHash") or "")
    except Exception:
        return ""


@router.get("/subcorpora", tags=["subcorpora"])
async def list_subcorpora(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:
    """List all persisted SubcorpusDefinitions."""

    proj = _project_or_503()
    subs = await asyncio.to_thread(proj.subcorpora)
    return {"subcorpora": subs}


@router.get("/subcorpora/{name}", tags=["subcorpora"])
async def get_subcorpus(
    name: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:

    proj = _project_or_503()
    sub = await asyncio.to_thread(proj.get_subcorpus, name)
    if sub is None:
        raise ApiError(
            404,
            "subcorpus.not_found",
            lt("Subkorpus nicht gefunden: {name}", "Subcorpus not found: {name}"),
            name=name,
        )
    return sub


@router.post("/subcorpora", tags=["subcorpora"])
async def save_subcorpus_route(
    payload: Dict[str, Any] = Body(
        ...,
        examples={"meta": {"summary": "Subcorpus from metadata",
                           "value": {"name": "republican_since_1981", "corpus": "sotu_en",
                                     "filter_spec": {"party": "Republican", "year": {"op": ">=", "value": 1981}}}}},
    ),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:
    """Create/upsert a durable named SubcorpusDefinition."""

    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError(400, "subcorpus.name_missing", lt("name fehlt", "name is missing"))
    corpus = payload.get("corpus") or "default"
    filter_spec = payload.get("filter_spec") if isinstance(payload.get("filter_spec"), dict) else {}
    query = payload.get("query")
    if not filter_spec and not (query and str(query).strip()):
        raise ApiError(
            400,
            "subcorpus.definition_missing",
            lt("filter_spec oder query erforderlich", "filter_spec or query required"),
        )
    proj = _project_or_503()
    # IDOR: an upsert that would OVERWRITE an existing subcorpus is only allowed
    # for its creator (or an admin). A non-owner is rejected before any write so
    # one user cannot clobber another's saved subcorpus.
    existing = await asyncio.to_thread(proj.get_subcorpus, name)
    if isinstance(existing, dict):
        _assert_owner_or_admin(existing.get("creator"), token)
    try:
        await asyncio.to_thread(
            proj.save_subcorpus,
            name,
            query,
            corpus=str(corpus),
            filter_spec=filter_spec,
            include_ai=bool(payload.get("include_ai", True)),
            include_human=bool(payload.get("include_human", True)),
            # Dieselbe Voreinstellung wie in docset_from_search, sonst löst
            # die Definition anders auf, als das Docset gebaut wurde.
            familien=bool(payload.get("familien", True)),
            ai_filters=payload.get("ai_filters") if isinstance(payload.get("ai_filters"), dict) else {},
            metadata_schema_hash=_corpus_schema_hash(corpus),
            creator=auth.username_for_token(token) or "anon",
        )
    except ValueError as exc:
        # cross-corpus name clash (would overwrite a different corpus's subcorpus)
        raise HTTPException(status_code=409, detail=exception_text(exc)) from exc
    return await asyncio.to_thread(proj.get_subcorpus, name)


@router.delete("/subcorpora/{name}", tags=["subcorpora"])
async def delete_subcorpus_route(
    name: str,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, str]:

    proj = _project_or_503()
    # IDOR: only the creator (or an admin) may delete a subcorpus. The ownership
    # check runs against the CURRENT stored definition, and the deletion itself
    # returns the removed row so the authorize-then-delete is not a TOCTOU race
    # (the project lock serialises the read used for the check is not enough on
    # its own, so we re-assert against the row returned by the atomic delete).
    existing = await asyncio.to_thread(proj.get_subcorpus, name)
    if existing is None:
        raise ApiError(
            404,
            "subcorpus.not_found",
            lt("Subkorpus nicht gefunden: {name}", "Subcorpus not found: {name}"),
            name=name,
        )
    _assert_owner_or_admin(existing.get("creator"), token)
    removed = await asyncio.to_thread(proj.delete_subcorpus, name)
    if removed is None:
        # Raced with a concurrent delete — already gone.
        raise ApiError(
            404,
            "subcorpus.not_found",
            lt("Subkorpus nicht gefunden: {name}", "Subcorpus not found: {name}"),
            name=name,
        )
    # Re-assert against what was actually removed (defends against a concurrent
    # overwrite that changed the creator between the check and the delete).
    _assert_owner_or_admin(removed.get("creator"), token)
    return {"status": "ok"}


@router.post("/subcorpora/{name}/resolve", tags=["subcorpora"])
async def resolve_subcorpus_route(
    name: str,
    payload: Dict[str, Any] = Body(default={}),
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> Dict[str, Any]:
    """Re-hydrate a SubcorpusDefinition into a fresh live docset_id.

    Returns stale=true when the corpus metadata schema changed since the
    definition was saved (doc positions may have shifted -> the resolved set may
    differ from creation; surfaced, not silently diverged).
    """
    from .. import server as _server

    proj = _project_or_503()
    definition = await asyncio.to_thread(proj.get_subcorpus, name)
    if definition is None:
        raise ApiError(
            404,
            "subcorpus.not_found",
            lt("Subkorpus nicht gefunden: {name}", "Subcorpus not found: {name}"),
            name=name,
        )
    # Resolve against the subcorpus's OWN stored corpus, not the request's — otherwise
    # the stored filter is replayed against the wrong index and returns silently-wrong
    # doc ids. A conflicting request corpus is rejected rather than honoured.
    stored_corpus = str(definition.get("corpus") or "default")
    req_corpus = payload.get("corpus")
    if req_corpus and str(req_corpus) != stored_corpus:
        raise ApiError(
            422,
            "subcorpus.corpus_mismatch",
            lt(
                "Subkorpus '{name}' gehört zu Korpus '{corpus}', nicht '{expected}'",
                "Subcorpus '{name}' belongs to corpus '{corpus}', not '{expected}'",
            ),
            name=name,
            corpus=stored_corpus,
            expected=req_corpus,
        )
    corpus = stored_corpus
    idx = _server.get_corpus(corpus)
    doc_count = _doc_count_for_index(idx)
    try:
        # Use the bounded pool for this full scan to preserve default-executor
        # capacity for small offloads.
        doc_ids = await _server._run_heavy_scan(
            _server._resolve_subcorpus_doc_ids, idx, definition
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    docset_id = _store_docset(corpus, doc_ids, doc_count)
    token_count = 0
    if doc_ids.size:
        try:
            token_count = int(await asyncio.to_thread(idx.docset_token_count, doc_ids))
        except Exception:
            token_count = 0
    saved_hash = str(definition.get("metadata_schema_hash") or "")
    stale = bool(saved_hash) and saved_hash != _corpus_schema_hash(corpus)
    return {"docset_id": docset_id, "doc_count": int(doc_ids.size), "token_count": token_count, "stale": stale}
