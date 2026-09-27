from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccessLevel(str, Enum):
    PUBLIC = "public"
    USER = "user"
    MANAGER = "manager"
    ADMIN = "admin"
    OWNER_OR_ADMIN = "owner_or_admin"


@dataclass(frozen=True)
class RoutePolicy:
    """Release access policy for a backend route family."""

    prefix: str
    access: AccessLevel
    reason: str


ROUTE_POLICIES: tuple[RoutePolicy, ...] = (
    RoutePolicy("/api", AccessLevel.PUBLIC, "version redirect"),
    RoutePolicy("/api/v1/login", AccessLevel.PUBLIC, "authentication entrypoint"),
    RoutePolicy("/api/v1/logout", AccessLevel.PUBLIC, "token revocation entrypoint"),
    RoutePolicy("/api/v1/health", AccessLevel.PUBLIC, "legacy liveness alias"),
    RoutePolicy("/api/v1/help", AccessLevel.PUBLIC, "bundled user documentation status"),
    RoutePolicy("/api/v1/auth/session", AccessLevel.PUBLIC, "current caller session metadata"),
    RoutePolicy("/api/v1/auth/dev-token", AccessLevel.PUBLIC, "local-first guest dev token; self-guards on RBAC-off + non-release"),
    RoutePolicy("/api/v1/capabilities", AccessLevel.USER, "product capability contract"),
    RoutePolicy("/api/v1/metrics", AccessLevel.ADMIN, "operational metrics"),
    RoutePolicy("/api/v1/system", AccessLevel.ADMIN, "system details"),
    RoutePolicy("/api/v1/settings", AccessLevel.ADMIN, "runtime settings"),
    RoutePolicy("/api/v1/operation-runs", AccessLevel.ADMIN, "backend-owned operation lifecycle status"),
    RoutePolicy("/api/v1/embeddings/local-index", AccessLevel.ADMIN, "local semantic-index administration"),
    RoutePolicy("/api/v1/embeddings/download", AccessLevel.ADMIN, "embedding package installation"),
    RoutePolicy("/api/v1/embeddings/remove", AccessLevel.ADMIN, "embedding package removal"),
    RoutePolicy("/api/v1/embeddings", AccessLevel.USER, "embedding package visibility"),
    RoutePolicy("/api/v1/projects/create", AccessLevel.ADMIN, "project administration"),
    RoutePolicy("/api/v1/projects", AccessLevel.USER, "project-scoped user data"),
    RoutePolicy("/api/v1/prefs", AccessLevel.USER, "user preferences"),
    RoutePolicy("/api/v1/query", AccessLevel.USER, "corpus query data"),
    RoutePolicy("/api/v1/docs", AccessLevel.USER, "document search"),
    RoutePolicy("/api/v1/doc", AccessLevel.USER, "document snippets"),
    RoutePolicy("/api/v1/document", AccessLevel.USER, "document access"),
    RoutePolicy("/api/v1/subcorpora", AccessLevel.USER, "user-scoped subcorpora"),
    RoutePolicy(
        "/api/v1/corpora/import-methods",
        AccessLevel.ADMIN,
        "corpus import capability discovery",
    ),
    RoutePolicy(
        "/api/v1/corpora/import-preflight",
        AccessLevel.ADMIN,
        "corpus import preflight",
    ),
    RoutePolicy(
        "/api/v1/corpora/imports",
        AccessLevel.ADMIN,
        "corpus import mutation and reports",
    ),
    RoutePolicy("/api/v1/corpora", AccessLevel.USER, "corpus catalog access"),
    RoutePolicy("/api/v1/analysis", AccessLevel.USER, "analysis jobs and data"),
    RoutePolicy("/api/v1/annotations", AccessLevel.USER, "user-scoped KWIC annotations"),
    RoutePolicy("/api/v1/semantic", AccessLevel.USER, "semantic search"),
    RoutePolicy("/api/v1/export", AccessLevel.USER, "exports"),
    RoutePolicy("/api/v1/download", AccessLevel.USER, "downloads"),
    RoutePolicy("/api/v1/chat", AccessLevel.USER, "copilot chat"),
    RoutePolicy("/api/v1/copilot", AccessLevel.USER, "copilot control plane"),
    RoutePolicy("/api/v1/ws-ticket", AccessLevel.USER, "one-time WebSocket ticket minting"),
    RoutePolicy("/api/v1/ws/faiss", AccessLevel.ADMIN, "FAISS build stream"),
    RoutePolicy("/api/v1/ws/analysis", AccessLevel.USER, "analysis job stream"),
    RoutePolicy("/mcp", AccessLevel.USER, "tool access surface"),
)


def policy_for_path(path: str) -> RoutePolicy | None:
    """Return the most specific configured policy for ``path``."""
    normalized = path.rstrip("/") or "/"
    if normalized == "/api/v1/corpora/register":
        return RoutePolicy(
            "/api/v1/corpora/register",
            AccessLevel.ADMIN,
            "corpus registry mutation",
        )
    if normalized.startswith("/api/v1/corpora/") and normalized.endswith("/build-report"):
        return RoutePolicy(
            "/api/v1/corpora/{corpus}/build-report",
            AccessLevel.ADMIN,
            "corpus build reports",
        )
    if normalized.startswith("/api/v1/corpora/") and normalized.endswith("/registration"):
        return RoutePolicy(
            "/api/v1/corpora/{corpus}/registration",
            AccessLevel.ADMIN,
            "corpus registry mutation",
        )
    corpus_import_prefixes = (
        "/api/v1/corpora/import-methods",
        "/api/v1/corpora/import-preflight",
        "/api/v1/corpora/imports",
    )
    is_corpus_import_route = any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in corpus_import_prefixes
    )
    if normalized.startswith("/api/v1/corpora/") and not is_corpus_import_route:
        suffix = normalized.removeprefix("/api/v1/corpora/")
        if suffix and "/" not in suffix:
            return RoutePolicy(
                "/api/v1/corpora/{corpus}",
                AccessLevel.ADMIN,
                "corpus deletion",
            )
    matches = [
        policy
        for policy in ROUTE_POLICIES
        if normalized == policy.prefix
        or (policy.prefix != "/api" and normalized.startswith(f"{policy.prefix}/"))
    ]
    if not matches:
        return None
    return max(matches, key=lambda policy: len(policy.prefix))


def required_role_for_access(access: AccessLevel) -> str | None:
    """Return the minimum RBAC role needed for an access level."""
    if access == AccessLevel.PUBLIC:
        return None
    if access == AccessLevel.MANAGER:
        return "manager"
    if access == AccessLevel.ADMIN:
        return "admin"
    # OWNER_OR_ADMIN needs resource-specific checks after basic authentication.
    return "user"


def requires_policy_for_path(path: str) -> bool:
    """Return whether release mode should fail closed without a policy."""
    normalized = path.rstrip("/") or "/"
    return (
        normalized == "/api"
        or normalized == "/api/v1"
        or normalized.startswith("/api/")
        or normalized.startswith("/api/v1/")
        or normalized == "/mcp"
        or normalized.startswith("/mcp/")
    )


__all__ = [
    "AccessLevel",
    "RoutePolicy",
    "ROUTE_POLICIES",
    "policy_for_path",
    "required_role_for_access",
    "requires_policy_for_path",
]
