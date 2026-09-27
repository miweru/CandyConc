"""OpenAPI-Wahrheit für POST /analysis/trend und POST /export/concordance.

Vorher exponierten beide Routen ``Dict[str, Any]``-Bodies, also leere
OpenAPI-Schemata ohne Felddokumentation. Jetzt tragen sie benannte, absichtlich
PERMISSIVE Pydantic-Modelle (alle Felder optional, Werte untypisiert,
extra erlaubt): das Schema dokumentiert Felder und erwartete Typen, während die
handgeschriebenen 422-Prüfungen der Routen die einzige Validierungswahrheit
bleiben. Diese Datei pinnt beides:

* Schema-Seite: die requestBodies referenzieren die benannten Komponenten mit
  den dokumentierten Properties.
* Verhaltens-Seite: die handgeschriebenen 422er feuern unverändert, auch bei
  Werten, die ein striktes Modell abgelehnt hätte (z. B. query als Zahl), und
  camelCase-Aliasse erreichen die Handprüfung weiterhin als extra-Felder.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def headers():
    from candyconc.services.backend import auth

    if not getattr(auth, "RBAC_ENABLED", False):
        tok = getattr(auth, "DEFAULT_ADMIN_TOKEN", None)
        if tok:
            return {"Authorization": f"Bearer {tok}"}
    auth._USERS["body_models"] = auth.User("body_models", auth.hash_password("pw"), "user")
    return {"Authorization": f"Bearer {auth._issue_token('body_models')}"}


@pytest.fixture
def client():
    from candyconc.services.backend import server as srv

    return TestClient(srv.app, raise_server_exceptions=False)


def _resolve_body_schema(spec: dict, path: str) -> dict:
    schema = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    ref = schema.get("$ref")
    if ref is None and "allOf" in schema:
        ref = schema["allOf"][0].get("$ref")
    assert ref, f"requestBody von {path} hat keine benannte Schema-Referenz: {schema}"
    name = ref.rsplit("/", 1)[-1]
    return {"name": name, "schema": spec["components"]["schemas"][name]}


def test_trend_request_body_has_named_documented_schema():
    from candyconc.services.backend.server import app

    spec = app.openapi()
    resolved = _resolve_body_schema(spec, "/api/v1/analysis/trend")
    assert resolved["name"] == "AnalysisTrendRequest"
    props = resolved["schema"]["properties"]
    assert {"query", "cql", "date_field", "granularity", "docset_id", "corpus"} <= set(
        props
    )
    assert props["date_field"]["type"] == "string"
    assert props["granularity"]["enum"] == ["year", "month"]
    # Permissiv per Konstruktion: keine model-seitigen Pflichtfelder, die
    # Pflicht (query ODER cql, date_field) setzen die Handprüfungen durch.
    assert "required" not in resolved["schema"]


def test_concordance_export_request_body_has_named_documented_schema():
    from candyconc.services.backend.server import app

    spec = app.openapi()
    resolved = _resolve_body_schema(spec, "/api/v1/export/concordance")
    assert resolved["name"] == "ConcordanceExportRequest"
    props = resolved["schema"]["properties"]
    assert {
        "query",
        "corpus",
        "docset_id",
        "sort",
        "sort_dir",
        "case_insensitive",
        "ctx",
        "format",
        "excel_de",
        "dialect",
    } <= set(props)
    assert props["format"]["enum"] == ["csv", "tsv", "json", "jsonl", "xlsx"]
    assert props["case_insensitive"]["type"] == "boolean"
    assert "required" not in resolved["schema"]


def test_trend_handwritten_422s_stay_the_validation_truth(client, headers):
    # Leerer Body: die Handprüfung antwortet, nicht das Modell.
    r = client.post("/api/v1/analysis/trend", json={}, headers=headers)
    assert r.status_code == 422
    assert "query oder cql fehlt" in r.text

    # date_field fehlt: Handprüfungs-Wortlaut.
    r = client.post("/api/v1/analysis/trend", json={"query": "alpha"}, headers=headers)
    assert r.status_code == 422
    assert "date_field fehlt" in r.text

    # query als Zahl passiert das permissive Modell (ein striktes Modell hätte
    # hier pydantisch abgelehnt) und erreicht die granularity-Handprüfung.
    r = client.post(
        "/api/v1/analysis/trend",
        json={"query": 123, "date_field": "date", "granularity": "week"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "granularity" in r.text

    # Nicht-Objekt-Bodies laufen wie beim alten Dict-Body durch den
    # app-weiten RequestValidationError-Handler (validation_to_problem, 400
    # problem+json). Das Modell ändert an diesem Pfad nichts.
    r = client.post("/api/v1/analysis/trend", json=[1, 2], headers=headers)
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")


def test_concordance_handwritten_422s_and_camel_case_aliases_survive(client, headers):
    # Unbekanntes Format: Handprüfungs-Wortlaut.
    r = client.post(
        "/api/v1/export/concordance",
        json={"query": "alpha", "format": "exe"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "format muss eines von" in r.text

    # dialect-Handprüfung inklusive Format-Kopplung.
    r = client.post(
        "/api/v1/export/concordance",
        json={"query": "alpha", "format": "json", "dialect": "excel-de"},
        headers=headers,
    )
    assert r.status_code == 422
    assert "excel-de" in r.text

    # camelCase-Alias reist als extra-Feld durch das permissive Modell bis in
    # die Handprüfung (excelDe koppelt an format!=csv).
    r = client.post(
        "/api/v1/export/concordance",
        json={"query": "alpha", "format": "tsv", "excelDe": True},
        headers=headers,
    )
    assert r.status_code == 422
    assert "excel-de" in r.text
