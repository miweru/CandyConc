from __future__ import annotations

import pytest

from candyconc.services.backend.route_matrix import (
    AccessLevel,
    policy_for_path,
    required_role_for_access,
    requires_policy_for_path,
)


@pytest.mark.parametrize(
    ("path", "access"),
    [
        ("/api/v1/login", AccessLevel.PUBLIC),
        ("/api/v1/health", AccessLevel.PUBLIC),
        ("/api/v1/auth/session", AccessLevel.PUBLIC),
        ("/api/v1/capabilities", AccessLevel.USER),
        ("/api/v1/query/stream", AccessLevel.USER),
        ("/api/v1/doc/doc-1", AccessLevel.USER),
        ("/api/v1/document/doc-1", AccessLevel.USER),
        ("/api/v1/analysis/clusters", AccessLevel.USER),
        ("/api/v1/analysis/meta_schema", AccessLevel.USER),
        ("/api/v1/semantic/search", AccessLevel.USER),
        ("/api/v1/export/docx", AccessLevel.USER),
        ("/api/v1/download/file-1", AccessLevel.USER),
        ("/api/v1/chat/turn", AccessLevel.USER),
        ("/mcp/call", AccessLevel.USER),
        ("/api/v1/metrics", AccessLevel.ADMIN),
        ("/api/v1/system/info", AccessLevel.ADMIN),
        ("/api/v1/operation-runs/run-1", AccessLevel.ADMIN),
        ("/api/v1/settings/embeddings", AccessLevel.ADMIN),
        ("/api/v1/embeddings/download", AccessLevel.ADMIN),
        ("/api/v1/embeddings/remove", AccessLevel.ADMIN),
        ("/api/v1/embeddings/list", AccessLevel.USER),
        ("/api/v1/projects/create", AccessLevel.ADMIN),
        ("/api/v1/projects/default/clusters", AccessLevel.USER),
        ("/api/v1/prefs", AccessLevel.USER),
        ("/api/v1/copilot/action/approve", AccessLevel.USER),
        ("/api/v1/corpora/import-methods", AccessLevel.ADMIN),
        ("/api/v1/corpora/import-preflight", AccessLevel.ADMIN),
        ("/api/v1/corpora/imports", AccessLevel.ADMIN),
        ("/api/v1/corpora/imports/job-1", AccessLevel.ADMIN),
        ("/api/v1/corpora/imports/job-1/cancel", AccessLevel.ADMIN),
        ("/api/v1/corpora/imports/job-1/reports", AccessLevel.ADMIN),
        ("/api/v1/corpora/register", AccessLevel.ADMIN),
        ("/api/v1/corpora/demo", AccessLevel.ADMIN),
        ("/api/v1/corpora/demo/build-report", AccessLevel.ADMIN),
        ("/api/v1/corpora/demo/registration", AccessLevel.ADMIN),
        ("/api/v1/ws-ticket", AccessLevel.USER),
        ("/api/v1/ws/faiss/job-1", AccessLevel.ADMIN),
        ("/api/v1/ws/analysis/job-1", AccessLevel.USER),
    ],
)
def test_route_matrix_classifies_core_route_families(path, access):
    assert policy_for_path(path).access == access


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/login/",
        "/api/v1/query/",
        "/mcp/",
    ],
)
def test_route_matrix_treats_trailing_slash_like_canonical_path(path):
    policy = policy_for_path(path)
    canonical_policy = policy_for_path(path.rstrip("/"))

    assert policy == canonical_policy


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/login-callback",
        "/api/v1/userspace",
        "/api/v1/jobstatus",
        "/api/v2/unclassified",
        "/api/internal/status",
        "/mcpish/call",
        "/unclassified",
    ],
)
def test_route_matrix_requires_segment_boundary_for_prefix_matches(path):
    assert policy_for_path(path) is None


def test_route_matrix_uses_most_specific_matching_policy():
    admin_policy = policy_for_path("/api/v1/projects/create")

    assert admin_policy.prefix == "/api/v1/projects/create"
    assert admin_policy.access == AccessLevel.ADMIN


def test_route_matrix_does_not_claim_unimplemented_import_websocket():
    assert policy_for_path("/api/v1/ws/corpora/imports/job-1") is None


def test_route_matrix_does_not_classify_the_retired_semantic_search_route():
    assert policy_for_path("/api/v1/search") is None


def test_route_matrix_maps_access_levels_to_minimum_rbac_roles():
    assert required_role_for_access(AccessLevel.PUBLIC) is None
    assert required_role_for_access(AccessLevel.USER) == "user"
    assert required_role_for_access(AccessLevel.MANAGER) == "manager"
    assert required_role_for_access(AccessLevel.ADMIN) == "admin"
    assert required_role_for_access(AccessLevel.OWNER_OR_ADMIN) == "user"


@pytest.mark.parametrize(
    ("path", "requires_policy"),
    [
        ("/api", True),
        ("/api/v1/query", True),
        ("/api/v2/unclassified", True),
        ("/api/internal/status", True),
        ("/mcp/call", True),
        ("/openapi.json", False),
        ("/docs", False),
        ("/unclassified", False),
    ],
)
def test_release_fail_closed_scope_is_backend_api_only(path, requires_policy):
    assert requires_policy_for_path(path) is requires_policy
