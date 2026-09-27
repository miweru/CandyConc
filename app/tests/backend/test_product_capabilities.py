from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from candyconc.capabilities import (
    PRODUCT_CAPABILITY_CONTRACT_VERSION,
    build_product_capability_contract,
)
from candyconc.capabilities.product import (
    product_copilot_tool_operation_bindings,
    visible_product_copilot_tools,
)
from candyconc.i18n import localize


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_JOURNEY_CAPABILITIES = {
    "query.kwic",
    "analysis.frequency",
    "analysis.collocations",
    "corpus.catalogue",
    "corpus.import",
    "research.annotations",
    "research.copilot_grounding",
    "research.replay_export",
}
EXPERT_OR_HIDDEN_CAPABILITIES = {
    "product.capability_contract": "expert_api",
    "query.document_search_api": "expert_api",
    "research.annotations_import": "expert_api",
    "research.annotations_multi_api": "expert_api",
    "analysis.semantic_clustering": "hidden_experimental",
    "admin.project_management": "expert_api",
}


def _contract() -> dict:
    # German is the default language of contract texts. The assertions below
    # check the English limit wording, so resolve the contract to English.
    return localize(build_product_capability_contract(), "en")


def _capabilities_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in _contract()["capabilities"]}


def _operations(capability: dict) -> dict[str, dict]:
    return {operation["id"]: operation for operation in capability["operations"]}


def _routes(capability: dict) -> dict[tuple[str, tuple[str, ...]], dict]:
    return {
        (route["path"], tuple(route["methods"])): route
        for route in capability["backend_route_descriptors"]
    }


def test_product_capability_module_imports_without_server_side_effects():
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    app_src = REPO_ROOT / "app/src"
    env["PYTHONPATH"] = f"{app_src}{os.pathsep}{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import candyconc.capabilities.product as product; "
                "assert product.PRODUCT_CAPABILITY_CONTRACT_VERSION; "
                "assert 'candyconc.services.backend.server' not in sys.modules"
            ),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_product_capability_contract_keeps_release_journeys_first_class():
    contract = _contract()
    capabilities = {item["id"]: item for item in contract["capabilities"]}
    ids = list(capabilities)

    assert contract["version"] == PRODUCT_CAPABILITY_CONTRACT_VERSION
    assert len(str(contract["fingerprint_sha256"])) == 64
    assert contract["cqlf_capability_contract"]["current_level"] == "2-"
    assert len(ids) == len(set(ids))
    assert "operation_input_schema_catalog" not in contract
    assert RELEASE_JOURNEY_CAPABILITIES <= set(capabilities)

    for capability_id in RELEASE_JOURNEY_CAPABILITIES:
        capability = capabilities[capability_id]
        assert capability["visibility"] == "first_class_ui", capability_id
        assert capability["operations"], capability_id
        for operation in capability["operations"]:
            assert operation["route"]["path"], operation["id"]
            assert operation["input_schema_ref"], operation["id"]
            assert operation["response_shape"], operation["id"]
            assert operation["run_semantics"], operation["id"]

    route_only_first_class = sorted(
        capability["id"]
        for capability in capabilities.values()
        if capability["visibility"] == "first_class_ui"
        and capability["maturity"] != "unsupported"
        and capability["backend_route_descriptors"]
        and not capability["operations"]
    )
    assert route_only_first_class == []


def test_corpus_import_capability_marks_alignment_builds_expert_only():
    capabilities = _capabilities_by_id()

    import_capability = capabilities["corpus.import"]
    limits = " ".join(import_capability["limits"])
    assert import_capability["visibility"] == "first_class_ui"
    # The limits are shown in the import panel. They say in plain words what
    # the interface imports and what stays with the command line and the API.
    assert "Parquet and VRT files" in limits
    assert "externally paired files with a pair key" in limits
    assert "sentence embeddings" in limits
    assert "hybrid alignment" in limits
    assert "only from the command line and the API" in limits
    assert "does not survive a restart" in limits
    assert "import report and in the build report" in limits
    # Die ungepaarten Ingestion-Adapter sind seit R4 Importmethoden der
    # Oberflaeche, die fruehere "CLI-only"-Grenze darf nicht wieder auftauchen.
    assert "unpaired CSV, JSONL, plain text and Hugging Face data" in limits
    assert "not first-class UI import methods" not in limits
    assert "trust_remote_code is always off" in limits
    # No developer jargon in a text of the interface.
    assert "First-class" not in limits and "Expert/API" not in limits


def test_product_capability_contract_marks_unfinished_or_legacy_routes_expert_api():
    capabilities = _capabilities_by_id()

    for capability_id, visibility in EXPERT_OR_HIDDEN_CAPABILITIES.items():
        assert capabilities[capability_id]["visibility"] == visibility

    assert capabilities["product.capability_contract"]["operations"] == []
    assert capabilities["analysis.semantic_clustering"]["operations"] == []
    assert capabilities["analysis.semantic_clustering"]["action_types"] == []
    visible_tools = set(visible_product_copilot_tools())
    assert not visible_tools.intersection(capabilities["analysis.semantic_clustering"]["copilot_tools"])

    document_lookup_routes = {route[0] for route in _routes(capabilities["query.document_access"])}
    assert document_lookup_routes == {"/api/v1/doc/snippet", "/api/v1/document/{doc_id}"}
    assert ("/api/v1/docs/search", ("GET",)) in _routes(
        capabilities["query.document_search_api"]
    )

    annotation_routes = {route[0] for route in _routes(capabilities["research.annotations"])}
    assert "/api/v1/annotations/import" not in annotation_routes
    assert ("/api/v1/annotations/import", ("POST",)) in _routes(
        capabilities["research.annotations_import"]
    )
    annotation_ops = _operations(capabilities["research.annotations"])
    assert all(
        not (operation.get("surface_slot") or "").startswith("annotation.review")
        for operation in annotation_ops.values()
    )
    annotation_limits = " ".join(capabilities["research.annotations"]["limits"])
    assert "row-level coding" in annotation_limits
    assert "Review queue" in annotation_limits
    assert "adjudication" in annotation_limits
    assert capabilities["research.annotations_import"]["limits"]
    assert capabilities["research.annotations_multi_api"]["limits"]

    replay_operations = _operations(capabilities["research.replay_export"])
    assert replay_operations["research.replay_export.concordance"]["route"]["path"] == (
        "/api/v1/export/concordance"
    )
    assert replay_operations["research.replay_export.concordance"]["route"]["methods"] == ["POST"]


def test_product_capability_contract_preserves_security_and_feature_gates():
    capabilities = _capabilities_by_id()

    admin_routes = _routes(capabilities["admin.system_operations"])
    assert admin_routes[("/api/v1/system/info", ("GET",))]["access"] == "admin"
    embedding_routes = _routes(capabilities["settings.embedding_management"])
    assert embedding_routes[
        ("/api/v1/embeddings/local-index/preflight", ("GET",))
    ]["required_role"] == "admin"
    assert embedding_routes[
        ("/api/v1/embeddings/local-index/build", ("POST",))
    ]["mutates"] is True
    assert embedding_routes[
        ("/api/v1/embeddings/local-index/builds/{run_id}", ("GET",))
    ]["mutates"] is False
    assert embedding_routes[
        ("/api/v1/embeddings/local-index/builds/{run_id}/cancel", ("POST",))
    ]["required_role"] == "admin"
    observability = capabilities["admin.security_observability"]
    observability_routes = {route[0] for route in _routes(observability)}
    assert observability_routes == {"/api/v1/metrics"}
    observability_limits = " ".join(observability["limits"])
    assert "local-only" in observability_limits
    assert "external telemetry exporter" in observability_limits

    semantic_operations = _operations(capabilities["analysis.semantic_similarity"])
    semantic_limits = " ".join(capabilities["analysis.semantic_similarity"]["limits"])
    assert "complete CSV/EvidencePackage export path" in semantic_limits
    assert "not advertised as a saved analysis" in semantic_limits
    similar_words = semantic_operations["analysis.semantic_similarity.similar_words"]
    assert similar_words["route"]["requires_corpus_features"] == ["semantic.word_similarity"]
    assert similar_words["required_context"] == ["corpus_features"]
    passage_search = semantic_operations["analysis.semantic_similarity.passage_search"]
    assert passage_search["copilot_tools"] == ["semantic_search"]
    assert passage_search["route"]["requires_corpus_features"] == ["semantic.passage_search"]
    assert passage_search["required_context"] == ["active_query", "corpus_features"]

    wordsketch_operations = _operations(capabilities["analysis.wordsketch"])
    wordsketch_profile = wordsketch_operations["analysis.wordsketch.profile"]
    assert wordsketch_profile["route"]["requires_corpus_features"] == ["token_attributes.rel"]
    assert wordsketch_profile["required_context"] == ["active_query", "corpus_features"]
    wordsketch_diff = wordsketch_operations["analysis.wordsketch.diff"]
    assert wordsketch_diff["route"]["requires_corpus_features"] == ["token_attributes.rel"]
    assert wordsketch_diff["required_context"] == ["active_query", "corpus_features"]

    keyness_limits = " ".join(capabilities["analysis.keyness"]["limits"])
    assert "no bundled external German reference-frequency list" in keyness_limits
    keyness_operations = _operations(capabilities["analysis.keyness"])
    assert keyness_operations["analysis.keyness.job"]["route"]["path"] == (
        "/api/v1/analysis/keyness/job"
    )

    parallel_operations = _operations(capabilities["corpus.alignment_parallel"])
    parallel_limits = " ".join(capabilities["corpus.alignment_parallel"]["limits"])
    assert "legacy_ref_doc_v1" in parallel_limits
    assert "Generic pair-axis labels" in parallel_limits
    assert "not a first-class analysis workflow" in parallel_limits
    assert parallel_operations["corpus.alignment_parallel.parallel_kwic"]["route"][
        "requires_corpus_features"
    ] == ["alignment.parallel_kwic"]
    assert parallel_operations["corpus.alignment_parallel.parallel_groups"]["route"][
        "requires_corpus_features"
    ] == ["alignment.parallel_groups"]
    assert parallel_operations["corpus.alignment_parallel.parallel_kwic"]["ui_execution_policy"] == "contextual_ui"
    assert parallel_operations["corpus.alignment_parallel.parallel_groups"]["ui_execution_policy"] == "contextual_ui"

    import_operations = _operations(capabilities["corpus.import"])
    assert import_operations["corpus.import.start"]["run_semantics"] == "job_lifecycle"
    assert import_operations["corpus.import.start"]["ui_execution_policy"] == "contextual_ui"
    assert import_operations["corpus.import.job_cancel"]["required_context"] == ["route_param:job_id"]

    project_management = capabilities["admin.project_management"]
    assert project_management["operations"] == []
    assert "admin/API-only" in " ".join(project_management["limits"])
    project_routes = _routes(project_management)
    assert project_routes[("/api/v1/projects/create", ("POST",))]["access"] == "admin"
    assert project_routes[("/api/v1/projects/create", ("POST",))]["route_class"] == "admin_surface"


def test_only_corpus_registration_removal_uses_native_confirmation_policy():
    confirmed_operations = {
        operation["id"]
        for capability in _contract()["capabilities"]
        for operation in capability["operations"]
        if operation["ui_execution_policy"] == "confirmed_contextual_ui"
    }

    assert confirmed_operations == {"corpus.catalogue.unregister"}


def test_visible_product_copilot_tools_have_operation_bindings():
    from tests.tooling._real_tooling import REAL_TOOLS

    registered = frozenset(tool["function"]["name"] for tool in REAL_TOOLS)
    bindings = product_copilot_tool_operation_bindings(visible_only=True)
    by_tool = {}
    for binding in bindings:
        by_tool.setdefault(binding.tool_name, set()).add(binding.operation_id)

    visible_tools = set(visible_product_copilot_tools())
    assert visible_tools
    assert visible_tools <= set(by_tool)
    missing_from_current_registry = visible_tools - registered
    # semantic_search is ProductOperation-bound but feature-gated by
    # semantic.passage_search; on a bench index without passage embeddings the
    # registry intentionally omits it at runtime.
    assert missing_from_current_registry <= {"semantic_search"}
    assert all(by_tool[tool] for tool in visible_tools)


def test_product_capability_route_exposes_backend_ui_copilot_contract():
    from candyconc.services.backend.server import app

    client = TestClient(app)
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == PRODUCT_CAPABILITY_CONTRACT_VERSION
    assert body["cqlf_capability_contract"]["capabilities"]
    assert any(
        item["id"] == "cqlf.level2.semantic_similarity_macro"
        for item in body["cqlf_capability_contract"]["capabilities"]
    )
    assert "ui_coverage_gate" not in body
    assert "backend_route_coverage_gate" not in body
    assert "copilot_tool_coverage_gate" not in body
    assert "copilot_tool_contract_audit" not in body
    assert "operation_input_schema_catalog" not in body
    advertised_routes = {
        route["path"]
        for capability in body["capabilities"]
        for route in capability["backend_route_descriptors"]
    }
    advertised_capability_ids = {capability["id"] for capability in body["capabilities"]}
    assert "/api/v1/search" not in advertised_routes
    assert "analysis.legacy_semantic_search" not in advertised_capability_ids
    wordsketch = next(item for item in body["capabilities"] if item["id"] == "analysis.wordsketch")
    wordsketch_routes = {
        route["path"]: route
        for route in wordsketch["backend_route_descriptors"]
    }
    assert wordsketch_routes["/api/v1/analysis/wordsketch"]["requires_corpus_features"] == [
        "token_attributes.rel"
    ]
    assert wordsketch_routes["/api/v1/analysis/wordsketch_diff"]["requires_corpus_features"] == [
        "token_attributes.rel"
    ]
    kwic = next(item for item in body["capabilities"] if item["id"] == "query.kwic")
    assert kwic["backend_route_descriptors"][0]["methods"] == ["GET"]
    corpus_import = next(item for item in body["capabilities"] if item["id"] == "corpus.import")
    import_routes = {
        route["path"]: route
        for route in corpus_import["backend_route_descriptors"]
    }
    assert import_routes["/api/v1/corpora/imports"]["access"] == "admin"
    assert import_routes["/api/v1/corpora/imports"]["required_role"] == "admin"
    assert import_routes["/api/v1/corpora/imports"]["route_class"] == "admin_surface"
