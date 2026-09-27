"""The web client's Accept-Language header reaches route code as de or en."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from candyconc.services.backend.request_language import (
    parse_accept_language,
    request_language,
)


def test_client_headers_resolve_to_interface_language():
    assert parse_accept_language("en, de;q=0.5") == "en"
    assert parse_accept_language("de, en;q=0.5") == "de"


def test_quality_values_and_regional_tags():
    assert parse_accept_language("fr-FR, en-GB;q=0.8, de;q=0.7") == "en"
    assert parse_accept_language("de;q=0.4, en;q=0.9") == "en"
    assert parse_accept_language("en;q=0, de") == "de"


def test_missing_or_unsupported_values_give_german():
    assert parse_accept_language(None) == "de"
    assert parse_accept_language("") == "de"
    assert parse_accept_language("fr, it;q=0.5") == "de"
    assert parse_accept_language("*") == "de"
    assert parse_accept_language("en;q=abc") == "de"


def test_dependency_reads_header_of_the_request():
    app = FastAPI()

    @app.get("/language")
    def language(value: str = Depends(request_language)) -> dict:
        return {"language": value}

    client = TestClient(app)
    assert client.get("/language", headers={"Accept-Language": "en, de;q=0.5"}).json() == {"language": "en"}
    assert client.get("/language").json() == {"language": "de"}
