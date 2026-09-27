"""/annotations/* routes — the KWIC annotation layer (Track F7).

First-class, per-project KWIC annotations + a per-project coding scheme. Persisted
via the Project store (``project.py``) — NO new database. Each annotation is keyed
by a stable ``row_id`` (``f"{file}:{pos}"``, text-hash fallback) computed by the
frontend from the live KWIC row.

GET    /api/v1/annotations?corpus=&docset_id=         — corpus's annotations + scheme
PUT    /api/v1/annotations/{row_id}?corpus=           — upsert one row annotation
DELETE /api/v1/annotations/{row_id}?corpus=           — clear one row annotation
GET    /api/v1/annotations/scheme?corpus=             — the coding scheme (categories)
POST   /api/v1/annotations/scheme/preview?corpus=     — review a schema replacement
PUT    /api/v1/annotations/scheme?corpus=             — replace the coding scheme

Role gating mirrors the sibling write routes (annotations are USER-writable; the
project-wide scheme review/edit is MANAGER-only). The shared Project store is reached via the same
``_project_or_503`` pattern as ``routes/subcorpora.py``; ``_save`` happens inside
the synchronous Project methods, which the handlers dispatch through
``asyncio.to_thread`` so the event loop is never blocked on disk I/O.

Corpus scoping: a ``row_id`` (``file:pos``) is a per-corpus index that restarts at
0, so the SAME row_id aliases across corpora. Annotations are therefore persisted
nested by corpus — ``GET ?corpus=X`` returns only corpus X's annotations, and
``PUT``/``DELETE ?corpus=X`` write only into X. A missing ``corpus`` falls back to
the ``DEFAULT_CORPUS`` namespace (never 500). The coding scheme belongs to a
corpus as well: the scheme routes take ``?corpus=`` and a corpus without a
scheme of its own reads the project scheme (the routes without ``corpus``),
until its first scheme is saved. ``docset_id`` is accepted for forward-compat
but does not scope persistence.

The ``annotator`` is derived server-side from the authenticated principal; any
client-supplied ``annotator`` is ignored when a *real RBAC* principal exists. It
is honoured when unauthenticated, when RBAC is off (the local-dev multi-coder
"Kodierer-Name" path — the synthetic ``local-dev`` principal is not a real
attribution authority, so coders stay in distinct slots and kappa is computable).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from candyconc.entrypoints.errors import ApiError, CandyAPIRouter
from candyconc.i18n import exception_text, localize, lt
from .. import auth

router = CandyAPIRouter()

# Defensive caps so a malformed/oversized client payload can't bloat the project
# file. A free-text annotation note is a short coding rationale, not an essay.
_MAX_NOTE_LEN = 4000
_MAX_CATEGORIES = 200
_MAX_LABEL_LEN = 200


def _normalize_row_id(row_id: str) -> str:
    rid = str(row_id).strip()
    if not rid:
        raise ApiError(400, "annotation.row_id_missing", lt("row_id fehlt", "row_id is missing"))
    if rid.startswith("h:") and len(rid) > 2:
        return rid
    if ":" in rid and all(part.strip() for part in rid.split(":", 1)):
        return rid
    raise ApiError(
        422,
        "annotation.row_id_invalid",
        lt(
            "row_id muss eine KWIC-Zeilen-ID sein (doc:position oder h:hash)",
            "row_id must be a concordance line ID (doc:position or h:hash)",
        ),
    )


# --- Pydantic models (the FRONTEND agent implements against THESE) ---


class Category(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)
    label: str = Field(..., min_length=1, max_length=_MAX_LABEL_LEN)
    color: str = Field(default="", max_length=64)
    shortcut: Optional[str] = Field(default=None, max_length=32)


class Annotation(BaseModel):
    category_id: Optional[str] = None
    note: Optional[str] = None
    annotator: str = ""
    updated_at: str = ""


class Scheme(BaseModel):
    categories: List[Category] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)


class AnnotationsListResponse(BaseModel):
    status: str = "ok"
    annotations: Dict[str, Annotation] = Field(default_factory=dict)
    scheme: Scheme = Field(default_factory=Scheme)


class AnnotationUpsertRequest(BaseModel):
    category_id: Optional[str] = None
    note: Optional[str] = None
    annotator: str = ""


class AnnotationUpsertResponse(BaseModel):
    status: str = "ok"
    row_id: str
    annotation: Annotation


class AnnotationDeleteResponse(BaseModel):
    status: str
    row_id: str


class SchemeResponse(BaseModel):
    status: str = "ok"
    categories: List[Category] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)


class SchemeRemovalImpact(BaseModel):
    category_id: str
    label: str
    annotation_count: int = Field(ge=0)
    corpus_count: int = Field(ge=0)
    annotator_count: int = Field(ge=0)


class SchemePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: List[Category]
    expected_revision: int = Field(ge=0)


class SchemePreviewResponse(BaseModel):
    """Non-mutating review of a proposed coding-scheme replacement."""

    status: str
    categories: List[Category] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0)
    removals: List[SchemeRemovalImpact] = Field(default_factory=list)
    confirmation_token: Optional[str] = None


# --- FT-ANNOTATION-RESEARCH: multi-coder, IAA, import models ---


class MultiCoderAnnotationsResponse(BaseModel):
    """Full multi-coder view: ``{row_id: {annotator: Annotation}}``.

    The unnamed/default coder slot is surfaced as the ``""`` annotator key.
    """
    status: str = "ok"
    annotations: Dict[str, Dict[str, Annotation]] = Field(default_factory=dict)
    scheme: Scheme = Field(default_factory=Scheme)
    multi_coder: bool = False


class AgreementResponse(BaseModel):
    """Inter-annotator agreement statistics for one corpus."""
    status: str = "ok"
    corpus: str = ""
    annotators: List[str] = Field(default_factory=list)
    n_rows_total: int = 0
    n_rows_overlap: int = 0
    percent_agreement: Optional[float] = None
    kappa: Optional[float] = None
    kappa_method: Optional[str] = None
    per_category_agreement: Dict[str, float] = Field(default_factory=dict)


class ImportRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    row_id: str = Field(..., min_length=1)
    category_id: Optional[str] = None
    note: Optional[str] = None
    annotator: str = ""


class AnnotationImportRequest(BaseModel):
    records: List[ImportRecord] = Field(default_factory=list)
    dry_run: bool = False
    # When true, a record whose category_id is not in the scheme is rejected
    # (default); when false, unknown categories are imported as-is (note-style).
    validate_categories: bool = True


class AnnotationImportResponse(BaseModel):
    status: str = "ok"
    imported: int = 0
    skipped: int = 0
    dry_run: bool = False
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    previews: List[Dict[str, Any]] = Field(default_factory=list)


class MultiCoderSettingRequest(BaseModel):
    enabled: bool


class MultiCoderSettingResponse(BaseModel):
    status: str = "ok"
    multi_coder: bool = False


class SchemeUpsertRequest(BaseModel):
    # ``extra="forbid"`` so an unexpected/malformed body (e.g. a typo'd field, or a
    # body that omits ``categories``) is rejected with 422 instead of silently
    # parsing to an empty list and WIPING the scheme. ``categories`` is required
    # and validated as non-empty below so a malformed request never clears it.
    model_config = ConfigDict(extra="forbid")
    categories: List[Category]
    expected_revision: int = Field(ge=0)
    confirmation_token: Optional[str] = Field(default=None, max_length=128)


def _validated_scheme_categories(categories: List[Category]) -> List[dict]:
    if not categories:
        raise ApiError(
            400,
            "annotation.categories_empty",
            lt(
                "categories darf nicht leer sein (mind. eine Kategorie erforderlich)",
                "categories must not be empty (at least one category required)",
            ),
        )
    if len(categories) > _MAX_CATEGORIES:
        raise ApiError(
            400,
            "annotation.categories_too_many",
            lt("zu viele Kategorien (max {max_categories})", "too many categories (max {max_categories})"),
            max_categories=_MAX_CATEGORIES,
        )
    return [category.model_dump(exclude_none=True) for category in categories]


def _scheme_preview_response(result: dict) -> SchemePreviewResponse:
    return SchemePreviewResponse(
        status=str(result["status"]),
        categories=[Category(**category) for category in result.get("categories", [])],
        revision=int(result.get("revision", 0)),
        removals=[SchemeRemovalImpact(**removal) for removal in result.get("removals", [])],
        confirmation_token=result.get("confirmation_token"),
    )


def _project_or_503() -> Any:
    """Open the Project store, mapping a backing-store failure to HTTP 503.

    Mirrors ``routes/subcorpora._project_or_503``: a store-availability failure is
    a transient service condition, surfaced as 503 per the problem+json contract.
    """
    from .. import server as _server

    try:
        return _server._get_project()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=exception_text(exc)) from exc


def _namespace(corpus: str | None) -> str:
    """The corpus namespace of a row-level request (DEFAULT_CORPUS when missing)."""
    from candyconc.project import DEFAULT_CORPUS

    key = str(corpus).strip() if corpus is not None else ""
    return key or DEFAULT_CORPUS


def _scheme_category_ids(proj: Any, corpus: str | None = None) -> set[str]:
    """Category ids of the scheme that codings in ``corpus`` refer to."""
    return {str(c.get("id")) for c in proj.coding_scheme(_namespace(corpus))}


# Sentinel annotators that pre-date per-annotator ownership (legacy / dev / anon
# codings). A coding owned by one of these is treated as unowned so the IDOR
# hardening never locks anyone out of pre-existing data.
_LEGACY_ANNOTATORS = frozenset({"", "unknown", "anon", "guest"})


def _is_admin(token: str | None) -> bool:
    return auth.role_for_token(token) == "admin"


def _can_attribute_to_others(token: str | None) -> bool:
    """Whether the caller may attribute imported codings to OTHER coders.

    Multi-coder import (a coordinator loading several coders' codings at once) is a
    privileged operation: forging another coder's provenance must not be possible
    for a plain ``user``. Allowed for ``manager``/``admin`` only. RBAC off keeps
    single-tenant open access.
    """
    if not auth.RBAC_ENABLED:
        return True
    return auth.role_for_token(token) in ("manager", "admin")


def _assert_coding_owner_or_admin(existing: dict | None, token: str | None) -> None:
    """Authorize a write/delete against an EXISTING coding's annotator (IDOR guard).

    Convention mirrors ``routes/subcorpora._assert_owner_or_admin``:

    * **RBAC off** (local_dev_unsafe): single-tenant -> no-op, open access kept.
    * **Admins** bypass.
    * No existing coding, or a **legacy/sentinel annotator** -> allowed (a fresh
      row or pre-ownership data is not owned by anyone).
    * Otherwise the caller must BE the coding's annotator; mismatch -> **403**.

    Used in single-coder mode, where a row holds ONE coding: a second user must
    not silently overwrite the first user's coding (that silent overwrite was the
    r8 behaviour this track closes). In multi-coder mode each coder writes their
    OWN slot, so this never trips between distinct coders.
    """
    if not auth.RBAC_ENABLED:
        return
    if existing is None:
        return
    if _is_admin(token):
        return
    owner = str(existing.get("annotator") or "").strip()
    if owner.lower() in _LEGACY_ANNOTATORS:
        return
    identity = auth.username_for_token(token)
    if not identity:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if owner != identity:
        raise HTTPException(status_code=403, detail="Forbidden")


def _resolve_annotator(token: str | None, client_value: str) -> str:
    """Derive the annotator server-side; never trust the client when a *real* principal exists.

    The ``annotator`` is the provenance of a coding, so under RBAC it must not be
    spoofable. When the request carries a *real authenticated principal* (a live
    token that resolves to a registered RBAC user) we use that username and IGNORE
    any client-supplied value.

    Multi-coder caveat (the local-dev annotator-label path): with RBAC OFF the
    local-dev frontend always carries the implicit dev token, which resolves to the
    synthetic ``LOCAL_DEV_USERNAME`` principal. That principal is single-tenant
    scaffolding, NOT a real attribution authority — so honouring it would collapse
    every coder ("Kodierer-Name") into one slot and make the second coder silently
    overwrite the first (kappa unreachable). In that mode the client-supplied
    annotator label IS the provenance, so we honour it (distinct names -> distinct
    slots), falling back to ``"anon"``. ``auth._is_local_dev_principal`` is the
    single source of truth for "this is the synthetic dev principal".

    Note: ``username_for_token(None)`` returns the synthetic ``"guest"`` in
    RBAC-off dev mode, which is NOT a real principal — so we resolve the token
    directly and only override when it names an actual RBAC user.
    """
    principal = auth._resolve_token(token) if token else None
    if principal and not auth._is_local_dev_principal(principal):
        return principal
    return (client_value or "").strip() or principal or "anon"


@router.get("/annotations", tags=["annotations"], response_model=AnnotationsListResponse)
async def list_annotations(
    corpus: Annotated[Optional[str], Query()] = None,
    docset_id: Annotated[Optional[str], Query()] = None,
    annotator: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> AnnotationsListResponse:
    """Return the requested corpus's row annotations plus its coding scheme.

    Annotations and the coding scheme are scoped by ``corpus`` (a missing
    ``corpus`` reads the default namespace). ``docset_id`` is accepted for
    forward-compat but does not scope persistence. ``annotator`` switches the read
    from the representative single-coder view to that coder's own slot; with RBAC
    the server derives the slot from the authenticated principal.
    """
    proj = _project_or_503()
    coder = _resolve_annotator(token, annotator) if annotator and annotator.strip() else None
    rows = await asyncio.to_thread(proj.row_annotations, corpus, coder)
    scheme = await asyncio.to_thread(proj.coding_scheme_snapshot, _namespace(corpus))
    return AnnotationsListResponse(
        annotations={rid: Annotation(**row) for rid, row in rows.items()},
        scheme=Scheme(
            categories=[Category(**category) for category in scheme["categories"]],
            revision=scheme["revision"],
        ),
    )


@router.post(
    "/annotations/scheme/preview",
    tags=["annotations"],
    response_model=SchemePreviewResponse,
)
async def preview_scheme(
    payload: SchemePreviewRequest,
    corpus: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("manager"))] = None,
) -> SchemePreviewResponse:
    """Inspect a schema replacement before it can remove any existing coding."""
    proj = _project_or_503()
    try:
        result = await asyncio.to_thread(
            proj.preview_coding_scheme_update,
            _validated_scheme_categories(payload.categories),
            payload.expected_revision,
            corpus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    return _scheme_preview_response(result)


@router.put(
    "/annotations/scheme",
    tags=["annotations"],
    response_model=SchemeResponse,
)
async def put_scheme(
    payload: SchemeUpsertRequest,
    corpus: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("manager"))] = None,
) -> SchemeResponse:
    """Replace the coding scheme of ``corpus`` (duplicate ids -> 400).

    Without ``corpus`` the project scheme is replaced, which applies to every
    corpus that has no scheme of its own.

    The coding scheme is project-global EDITORIAL config shared by every coder —
    replacing it cascades into all coders' annotations (dropped categories are
    nulled). It is therefore gated at ``manager`` (not ``user``): a single coder
    must not be able to rewrite the shared scheme and silently mutate everyone
    else's codings. GET stays ``user`` (every coder needs to read the scheme).

    A malformed body is rejected (422 via ``extra=forbid`` / required field) and an
    empty category list is rejected (400) so the scheme is never silently wiped by
    a bad request. Removing a category cascades: annotations pointing at a dropped
    category have their ``category_id`` nulled (see ``Project.set_coding_scheme``).
    """
    proj = _project_or_503()
    try:
        result = await asyncio.to_thread(
            proj.apply_coding_scheme_update,
            _validated_scheme_categories(payload.categories),
            payload.expected_revision,
            payload.confirmation_token,
            corpus,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=exception_text(exc)) from exc
    if result["status"] != "ok":
        # This only happens after a race or a non-UI caller bypassed the preview.
        # The client can reload/preview again; no coding or schema was mutated.
        raise HTTPException(status_code=409, detail=result)
    return SchemeResponse(
        categories=[Category(**category) for category in result["categories"]],
        revision=result["revision"],
    )


@router.get(
    "/annotations/scheme",
    tags=["annotations"],
    response_model=SchemeResponse,
)
async def get_scheme(
    corpus: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> SchemeResponse:
    """Return the coding scheme of ``corpus`` (the project scheme without one)."""
    proj = _project_or_503()
    scheme = await asyncio.to_thread(proj.coding_scheme_snapshot, corpus)
    return SchemeResponse(
        categories=[Category(**category) for category in scheme["categories"]],
        revision=scheme["revision"],
    )


# --- FT-ANNOTATION-RESEARCH literal sub-routes (declared BEFORE /{row_id} so the
#     catch-all row_id route never shadows them). ---


@router.get(
    "/annotations/multi",
    tags=["annotations"],
    response_model=MultiCoderAnnotationsResponse,
)
async def list_annotations_multi(
    corpus: Annotated[Optional[str], Query()] = None,
    docset_id: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> MultiCoderAnnotationsResponse:
    """Return the FULL multi-coder annotation view for ``corpus``.

    Unlike ``GET /annotations`` (one representative coding per row, single-coder
    shape), this returns every coder's coding: ``{row_id: {annotator: coding}}``.
    This is an Expert/API table endpoint; the release UI's AgreementPanel consumes
    ``GET /annotations/agreement`` instead of this full matrix. ``docset_id`` is
    accepted for client compatibility but not applied as a scope filter here; a
    first-class matrix workflow must define and test scoped review semantics first.
    The default/unnamed coder is the ``""`` annotator key.
    """
    proj = _project_or_503()
    rows = await asyncio.to_thread(proj.row_annotations_multi, corpus)
    scheme = await asyncio.to_thread(proj.coding_scheme_snapshot, _namespace(corpus))
    multi = await asyncio.to_thread(proj.multi_coder_enabled)
    return MultiCoderAnnotationsResponse(
        annotations={
            rid: {ann: Annotation(**coding) for ann, coding in coders.items()}
            for rid, coders in rows.items()
        },
        scheme=Scheme(
            categories=[Category(**c) for c in scheme["categories"]],
            revision=scheme["revision"],
        ),
        multi_coder=bool(multi),
    )


@router.get(
    "/annotations/agreement",
    tags=["annotations"],
    response_model=AgreementResponse,
)
async def annotation_agreement(
    corpus: Annotated[Optional[str], Query()] = None,
    docset_id: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> AgreementResponse:
    """Inter-annotator agreement (IAA) for ``corpus``.

    Percent agreement plus Cohen's kappa (exactly two coders) or Fleiss' kappa
    (>=3 coders), computed over rows that >=2 NAMED coders both assigned a category
    to. ``kappa``/``percent_agreement`` are ``null`` when there is no such overlap.
    ``docset_id`` is rejected explicitly until scoped review semantics are
    implemented, so clients never mistake corpus-level agreement for docset-level
    agreement.
    """
    if docset_id and str(docset_id).strip():
        raise ApiError(
            422,
            "annotation.agreement_docset_unsupported",
            lt(
                "docset_id wird für Annotation-Agreement noch nicht unterstützt; Ergebnis ist aktuell korpusweit.",
                "docset_id is not yet supported for inter-annotator agreement. The result currently covers the whole corpus.",
            ),
        )
    proj = _project_or_503()
    stats = await asyncio.to_thread(proj.annotation_agreement, corpus)
    return AgreementResponse(**stats)


@router.get(
    "/annotations/settings",
    tags=["annotations"],
    response_model=MultiCoderSettingResponse,
)
async def get_annotation_settings(
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
) -> MultiCoderSettingResponse:
    """Return the project's annotation settings (multi-coder toggle)."""
    proj = _project_or_503()
    multi = await asyncio.to_thread(proj.multi_coder_enabled)
    return MultiCoderSettingResponse(multi_coder=bool(multi))


@router.put(
    "/annotations/settings",
    tags=["annotations"],
    response_model=MultiCoderSettingResponse,
)
async def set_annotation_settings(
    payload: MultiCoderSettingRequest,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("manager"))] = None,
) -> MultiCoderSettingResponse:
    """Toggle multi-coder mode for the project (manager-gated — project-wide config).

    Default is single-coder (r8 behaviour). Enabling multi-coder makes each coder's
    codings independent (keyed by annotator) so IAA is meaningful. Like the coding
    scheme, this is project-wide editorial config, so it is gated at ``manager``.
    """
    proj = _project_or_503()
    await asyncio.to_thread(proj.set_multi_coder_enabled, bool(payload.enabled))
    return MultiCoderSettingResponse(multi_coder=bool(payload.enabled))


@router.post(
    "/annotations/import",
    tags=["annotations"],
    response_model=AnnotationImportResponse,
)
async def import_annotations(
    payload: AnnotationImportRequest,
    corpus: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> AnnotationImportResponse:
    """Bulk-import row annotations (multi-coder aware) in the exporter schema.

    Records are ``{row_id, category_id?, note?, annotator?}``. With ``dry_run`` the
    response is a preview (nothing is written). When ``validate_categories`` is
    true (default) a record whose ``category_id`` is not in the scheme is rejected
    (reported in ``errors``, not imported). Capped at 5000 records per request.

    Provenance + IDOR (parity with PUT/DELETE): the ``annotator`` of every imported
    record is derived SERVER-SIDE from the authenticated principal, never trusted
    from the client. A plain ``user`` may only import codings attributed to
    THEMSELVES — attributing rows to a DIFFERENT coder (multi-coder import) requires
    ``manager``/``admin`` (otherwise 403 forgery). And, exactly like PUT, a caller
    may not overwrite a peer's existing coding for a row: the existing coding's
    owner is asserted before each write (admin/manager bypass; legacy/sentinel and
    fresh rows are unowned). RBAC off (local dev) preserves open access and the r8
    byte-identical import path.
    """
    if len(payload.records) > 5000:
        raise ApiError(
            413, "annotation.import_too_many", lt("zu viele Records (max 5000)", "too many records (max 5000)")
        )
    proj = _project_or_503()
    valid: set[str] | None = None
    if payload.validate_categories:
        valid = await asyncio.to_thread(_scheme_category_ids, proj, corpus)
    records = [r.model_dump() for r in payload.records]

    # --- Provenance + IDOR enforcement (parity with PUT/DELETE) -------------
    # RBAC off keeps the single-tenant open-access import path byte-identical.
    if auth.RBAC_ENABLED:
        principal = auth._resolve_token(token) if token else None
        can_attribute_others = _can_attribute_to_others(token)
        multi = await asyncio.to_thread(proj.multi_coder_enabled)
        for rec in records:
            rid = str(rec.get("row_id") or "").strip()
            if not rid:
                continue  # store reports the bad record; nothing to attribute.
            requested = str(rec.get("annotator") or "").strip()
            # Derive the annotator server-side. When a principal exists, attributing
            # a row to a DIFFERENT coder is a privileged (manager/admin) action; a
            # plain user's records are forced onto their own identity.
            if principal:
                if requested and requested != principal and not can_attribute_others:
                    raise ApiError(
                        403,
                        "annotation.import_foreign_annotator",
                        lt(
                            "Forbidden: nur manager/admin dürfen fremde annotator importieren",
                            "Forbidden: only manager/admin may import codings of another annotator",
                        ),
                    )
                rec["annotator"] = requested if can_attribute_others and requested else principal
            else:
                rec["annotator"] = requested or "anon"
            # Ownership: a non-owner must not overwrite a peer's existing coding for
            # this row (same assertion PUT runs). In multi-coder mode the slot is
            # per-annotator; in single-coder mode the row holds one coding.
            target_annotator = rec["annotator"]
            if multi:
                existing = await asyncio.to_thread(
                    proj.get_row_annotation, rid, corpus, target_annotator
                )
            else:
                existing = await asyncio.to_thread(proj.get_row_annotation, rid, corpus)
            _assert_coding_owner_or_admin(existing, token)

    result = await asyncio.to_thread(
        proj.import_row_annotations,
        records,
        corpus=corpus,
        valid_category_ids=valid,
        dry_run=bool(payload.dry_run),
    )
    return AnnotationImportResponse(**localize(result))


@router.put(
    "/annotations/{row_id}",
    tags=["annotations"],
    response_model=AnnotationUpsertResponse,
)
async def put_annotation(
    row_id: str,
    payload: AnnotationUpsertRequest,
    corpus: Annotated[Optional[str], Query()] = None,
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> AnnotationUpsertResponse:
    """Upsert the annotation for ``row_id`` within ``corpus``.

    At least one of ``category_id``/``note`` must be set (an all-empty PUT is a
    no-op that would just store an empty shell -> 400, use DELETE to clear). A
    ``category_id`` must exist in the coding scheme; note length is capped.
    Scoped by ``corpus`` so row_ids that collide across corpora stay independent;
    the ``annotator`` is derived from the authenticated principal (see below).
    """
    rid = _normalize_row_id(row_id)
    note = payload.note.strip() if payload.note is not None else None
    if note == "":
        note = None
    if payload.category_id is None and note is None:
        raise ApiError(
            400,
            "annotation.content_missing",
            lt(
                "category_id oder note erforderlich (DELETE zum Löschen)",
                "category_id or note required (use DELETE to remove)",
            ),
        )
    if note is not None and len(note) > _MAX_NOTE_LEN:
        raise ApiError(
            400,
            "annotation.note_too_long",
            lt("note zu lang (max {max_length} Zeichen)", "note too long (max {max_length} characters)"),
            max_length=_MAX_NOTE_LEN,
        )
    proj = _project_or_503()
    if payload.category_id is not None:
        valid = await asyncio.to_thread(_scheme_category_ids, proj, corpus)
        if payload.category_id not in valid:
            raise ApiError(
                400,
                "annotation.category_unknown",
                lt("unbekannte category_id: {category_id}", "unknown category_id: {category_id}"),
                category_id=payload.category_id,
            )
    annotator = _resolve_annotator(token, payload.annotator)
    # IDOR: in single-coder mode a row holds ONE coding, so an upsert by a
    # different principal would silently overwrite the original coder's coding —
    # reject that (403). In multi-coder mode each coder owns their own slot, so a
    # caller only ever upserts their OWN coding and the check is a no-op.
    multi = await asyncio.to_thread(proj.multi_coder_enabled)
    if multi:
        existing = await asyncio.to_thread(proj.get_row_annotation, rid, corpus, annotator)
    else:
        existing = await asyncio.to_thread(proj.get_row_annotation, rid, corpus)
    _assert_coding_owner_or_admin(existing, token)
    stored = await asyncio.to_thread(
        proj.set_row_annotation,
        rid,
        corpus=corpus,
        category_id=payload.category_id,
        note=note,
        annotator=annotator,
    )
    return AnnotationUpsertResponse(row_id=rid, annotation=Annotation(**stored))


@router.delete(
    "/annotations/{row_id}",
    tags=["annotations"],
    response_model=AnnotationDeleteResponse,
)
async def delete_annotation(
    row_id: str,
    corpus: Annotated[Optional[str], Query()] = None,
    annotator: Annotated[str, Query()] = "",
    token: Annotated[str | None, Depends(auth.get_user_token)] = None,
    _auth: Annotated[None, Depends(auth.require_role("user"))] = None,
) -> AnnotationDeleteResponse:
    """Clear the caller's annotation for ``row_id`` within ``corpus`` (404 if none).

    IDOR: a caller may only delete a coding they own. In multi-coder mode the
    caller's OWN slot is deleted (others untouched); in single-coder mode the
    sole coding is deleted only when the caller owns it (403 otherwise).

    The slot is resolved EXACTLY like PUT (``_resolve_annotator``): under a real
    RBAC principal the client-supplied ``annotator`` is ignored (and the IDOR
    guard still rejects deleting a peer's slot); in the RBAC-off local-dev
    multi-coder path the client "Kodierer-Name" IS the provenance, so a coder
    deletes the very slot they wrote (PUT carried the same name) instead of
    landing on the "anon" slot and 404-ing on their own coding.
    """
    rid = _normalize_row_id(row_id)
    proj = _project_or_503()
    multi = await asyncio.to_thread(proj.multi_coder_enabled)
    if multi:
        # Each coder deletes their own slot. Resolve the caller's annotator the
        # SAME way PUT does (honouring the client Kodierer-Name in local-dev /
        # multi-coder) so the slot matches what they wrote.
        annotator = _resolve_annotator(token, annotator)
        existing = await asyncio.to_thread(proj.get_row_annotation, rid, corpus, annotator)
        if existing is None:
            raise ApiError(
                404,
                "annotation.not_found",
                lt("keine Annotation: {row_id}", "no annotation: {row_id}"),
                row_id=rid,
            )
        _assert_coding_owner_or_admin(existing, token)
        existed = await asyncio.to_thread(proj.delete_row_annotation, rid, corpus, annotator)
    else:
        existing = await asyncio.to_thread(proj.get_row_annotation, rid, corpus)
        if existing is None:
            raise ApiError(
                404,
                "annotation.not_found",
                lt("keine Annotation: {row_id}", "no annotation: {row_id}"),
                row_id=rid,
            )
        _assert_coding_owner_or_admin(existing, token)
        existed = await asyncio.to_thread(proj.delete_row_annotation, rid, corpus)
    if not existed:
        raise ApiError(
            404,
            "annotation.not_found",
            lt("keine Annotation: {row_id}", "no annotation: {row_id}"),
            row_id=rid,
        )
    return AnnotationDeleteResponse(status="ok", row_id=rid)
