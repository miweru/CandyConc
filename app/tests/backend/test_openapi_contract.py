"""Focused ungated OpenAPI contract guard (Track D12).

The backend OpenAPI build must work without a bench index or spaCy path. This
file protects the release-critical route contracts directly instead of keeping
a full generated route snapshot that duplicates the app's own OpenAPI output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

APP_ROOT = Path(__file__).resolve().parents[2]

# The OpenAPI build needs no corpus index. The module used to set a default
# CANDYCONC_INDEX_PATH here, which leaked into every module collected after it
# (tests/infra/test_collection_order_env.py).


def _param_type(schema: dict) -> str:
    """Best-effort scalar type label for focused parameter checks."""
    if not isinstance(schema, dict):
        return "unknown"
    if "type" in schema:
        return str(schema["type"])
    for combinator in ("anyOf", "oneOf", "allOf"):
        variants = schema.get(combinator)
        if isinstance(variants, list):
            types = sorted(
                str(v.get("type")) for v in variants if isinstance(v, dict) and v.get("type")
            )
            if types:
                return f"{combinator}({','.join(types)})"
    return "unknown"


def _openapi() -> dict:
    from candyconc.services.backend.server import app

    return app.openapi()


def _operation(spec: dict, method: str, path: str) -> dict:
    op = (spec.get("paths", {}).get(path) or {}).get(method)
    assert op is not None, f"{method.upper()} {path} fehlt in OpenAPI"
    return op


def _param_details(op: dict) -> dict[str, tuple[str | None, bool, str]]:
    out: dict[str, tuple[str | None, bool, str]] = {}
    for p in op.get("parameters", []) or []:
        name = p.get("name")
        if name:
            out[name] = (p.get("in"), bool(p.get("required", False)), _param_type(p.get("schema") or {}))
    return out


def _json_schema(op: dict, status: str = "200") -> dict:
    content = ((op.get("responses", {}).get(status) or {}).get("content") or {})
    return (content.get("application/json") or {}).get("schema") or {}


def _request_json_schema(op: dict) -> dict:
    content = ((op.get("requestBody") or {}).get("content") or {})
    return (content.get("application/json") or {}).get("schema") or {}


def _assert_ref(schema: dict, name: str) -> None:
    ref = schema.get("$ref") or (schema.get("items") or {}).get("$ref")
    assert str(ref).endswith(f"/{name}"), f"erwartete {name}, bekam {schema}"


def test_core_research_routes_expose_focused_openapi_contracts():
    """Core research routes stay registered with their user-facing contracts."""
    spec = _openapi()
    cases = (
        ("get", "/api/v1/query", {"term": ("query", True, "string"), "ctx": ("query", False, "integer")}, "KWICRow"),
        ("get", "/api/v1/analysis/frequency_list", {"group_by": ("query", False, "string")}, "PagedFrequencyResponse"),
        ("get", "/api/v1/analysis/collocates", {"term": ("query", True, "string"), "window": ("query", False, "integer")}, "PagedCollocatesResponse"),
        ("get", "/api/v1/analysis/dispersion", {"term": ("query", True, "string")}, "DispersionAnalysisResponse"),
        ("post", "/api/v1/analysis/keyness", {}, "PagedKeynessResponse"),
        ("post", "/api/v1/analysis/ngrams", {}, "PagedNgramsResponse"),
        ("post", "/api/v1/analysis/wordsketch_diff", {}, "SketchDiffResponse"),
    )

    for method, path, expected_params, response_model in cases:
        op = _operation(spec, method, path)
        responses = set(op.get("responses", {}))
        assert "422" in responses, f"{method.upper()} {path} fehlt 422-Vertrag"
        assert responses & {"200", "202"}, f"{method.upper()} {path} fehlt Erfolgsantwort"
        params = _param_details(op)
        for name, expected in expected_params.items():
            assert params.get(name) == expected, f"{method.upper()} {path} Param {name}"
        _assert_ref(_json_schema(op), response_model)


def test_import_export_and_runtime_routes_expose_focused_openapi_contracts():
    """Import, Export, capabilities and MCP keep the routes the UI consumes."""
    spec = _openapi()

    import_methods = _operation(spec, "get", "/api/v1/corpora/import-methods")
    assert _json_schema(import_methods).get("type") == "object"

    preflight = _operation(spec, "post", "/api/v1/corpora/import-preflight")
    assert _request_json_schema(preflight).get("type") == "object"
    assert _json_schema(preflight).get("type") == "object"

    import_job = _operation(spec, "post", "/api/v1/corpora/imports")
    assert "202" in import_job.get("responses", {})
    assert _request_json_schema(import_job).get("type") == "object"

    reports = _operation(spec, "get", "/api/v1/corpora/imports/{job_id}/reports")
    assert _param_details(reports)["job_id"] == ("path", True, "string")
    _assert_ref(_json_schema(reports), "CorpusImportReportsResponse")

    export_post = _operation(spec, "post", "/api/v1/export/concordance")
    # Seit K4 trägt der Body ein benanntes, permissives Dokumentationsmodell
    # statt eines leeren object-Schemas (die 422-Handprüfungen der Route
    # bleiben die Validierungswahrheit, siehe test_openapi_body_models.py).
    _assert_ref(_request_json_schema(export_post), "ConcordanceExportRequest")
    assert "200" in export_post.get("responses", {})

    evidence = _operation(spec, "post", "/api/v1/export/evidence-package")
    assert _request_json_schema(evidence).get("type") == "object"
    assert _json_schema(evidence).get("type") == "object"

    _assert_ref(_json_schema(_operation(spec, "get", "/api/v1/capabilities")), "ProductCapabilityContractResponse")
    _assert_ref(_json_schema(_operation(spec, "get", "/api/v1/auth/session")), "AuthSessionResponse")
    assert _json_schema(_operation(spec, "get", "/mcp/tools")).get("type") == "object"
    assert _request_json_schema(_operation(spec, "post", "/mcp/call")).get("type") == "object"


def test_paged_response_models_are_referenced():
    """Track D12: the paged analysis endpoints expose a $ref-backed 200 schema
    (a concrete Row/Paged model in components), not a bare ``object``."""
    spec = _openapi()
    components = spec.get("components", {}).get("schemas") or {}
    expected_refs = {
        ("get", "/api/v1/analysis/frequency_list"): "PagedFrequencyResponse",
        ("get", "/api/v1/analysis/collocates"): "PagedCollocatesResponse",
        ("post", "/api/v1/analysis/keyness"): "PagedKeynessResponse",
        ("post", "/api/v1/analysis/ngrams"): "PagedNgramsResponse",
        ("get", "/api/v1/analysis/lexical-diversity"): "LexicalDiversityResponse",
    }
    for model in expected_refs.values():
        assert model in components, f"{model} fehlt in components.schemas"

    def _ok_schema(method: str, path: str) -> dict:
        return _json_schema(_operation(spec, method, path))

    for (method, path), model in expected_refs.items():
        schema = _ok_schema(method, path)
        _assert_ref(schema, model)

    for model in ("PagedFrequencyResponse", "PagedCollocatesResponse", "PagedKeynessResponse", "PagedNgramsResponse"):
        props = components[model].get("properties") or {}
        assert {"rows", "row_limit", "total_candidates", "truncated", "method"} <= set(props), model


def test_release_schema_components_keep_research_fields():
    """Focused replacement for the former full OpenAPI shape snapshot."""
    components = _openapi().get("components", {}).get("schemas") or {}

    keyness = (components["KeynessRow"].get("properties") or {}).keys()
    assert {"expected_min", "low_reliability", "bic", "p_value", "q_value", "log_ratio"} <= set(keyness)

    dispersion = (components["DispersionAnalysisResponse"].get("properties") or {}).keys()
    assert {"dp", "dpnorm", "juilland_d", "carroll_d2", "range", "range_prop", "vc"} <= set(dispersion)

    sketch_diff = (components["SketchDiffResponse"].get("properties") or {}).keys()
    assert {"label_a", "label_b", "relations", "relation_labels", "score_key"} <= set(sketch_diff)

    capability = (components["ProductCapabilityContractResponse"].get("properties") or {}).keys()
    assert {"version", "scope", "capabilities", "fingerprint_sha256", "cqlf_capability_contract"} <= set(capability)


def test_new_routes_present():
    """The R7 feature routes (export + lexical diversity) are registered."""
    from candyconc.services.backend.server import app

    routes = {
        (m, r.path)
        for r in app.routes
        if getattr(r, "methods", None)
        for m in (r.methods - {"HEAD", "OPTIONS"})
    }
    assert ("POST", "/api/v1/export/concordance") in routes
    assert ("POST", "/api/v1/export/evidence-package") in routes
    assert ("GET", "/api/v1/analysis/lexical-diversity") in routes


def test_ft_endpoint_surfacing_routes_present():
    """FT-* endpoint surfacing (DT-VERTRAEGE coordination) routes registered."""
    from candyconc.services.backend.server import app

    routes = {
        (m, r.path)
        for r in app.routes
        if getattr(r, "methods", None)
        for m in (r.methods - {"HEAD", "OPTIONS"})
    }
    # FT-SKETCH-DIFF-DISTRIBUTION: word sketch difference endpoint.
    assert ("POST", "/api/v1/analysis/wordsketch_diff") in routes
    # FT-DISPERSION-FAMILY / FT-KEYNESS-RESEARCH are field/path additions on
    # existing routes (dispersion, keyness); focused schema-component checks
    # above guard the fields without a generated full-route snapshot.
    assert ("GET", "/api/v1/analysis/dispersion") in routes
    assert ("POST", "/api/v1/analysis/keyness") in routes


# ---------------------------------------------------------------------------
# WebSocket contract guard (DT-VERTRAEGE): WS routes live OUTSIDE the OpenAPI
# document, so OpenAPI never covers them. This tiny snapshot pins
# the set of registered WebSocket paths (incl. nested mounts) so a WS route
# added/removed/renamed is caught the same way an HTTP route would be.
# Regenerate intentionally with UPDATE_WS_ROUTES_SNAPSHOT=1 and commit the diff.
# ---------------------------------------------------------------------------
WS_SNAPSHOT = Path(__file__).resolve().parent / "_snapshots" / "ws_routes.json"


def _ws_paths() -> list:
    from starlette.routing import Mount, WebSocketRoute

    from candyconc.services.backend.server import app

    found: list[str] = []

    def _walk(routes, prefix: str = "") -> None:
        for route in routes:
            if isinstance(route, WebSocketRoute):
                found.append(prefix + route.path)
            elif isinstance(route, Mount):
                _walk(getattr(route, "routes", []) or [], prefix + route.path)

    _walk(app.routes)
    return sorted(set(found))


def test_websocket_routes_snapshot():
    paths = _ws_paths()
    if os.environ.get("UPDATE_WS_ROUTES_SNAPSHOT") == "1":
        WS_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        WS_SNAPSHOT.write_text(json.dumps(paths, indent=2, sort_keys=True, ensure_ascii=False))
        import pytest

        pytest.skip("WebSocket route snapshot updated")
    assert WS_SNAPSHOT.exists(), "ws_routes.json fehlt — einmal mit UPDATE_WS_ROUTES_SNAPSHOT=1 erzeugen"
    expected = json.loads(WS_SNAPSHOT.read_text())
    added = sorted(set(paths) - set(expected))
    removed = sorted(set(expected) - set(paths))
    assert not (added or removed), (
        "WebSocket-Routen geändert.\n"
        f"  hinzugefügt: {added}\n  entfernt: {removed}\n"
        "Bei einer BEWUSSTEN Änderung: UPDATE_WS_ROUTES_SNAPSHOT=1 setzen und ws_routes.json committen."
    )
