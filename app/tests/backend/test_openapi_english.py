"""The OpenAPI description, the import path hints and the regex example are English.

Before: examples such as "Freier Kontrast zweier Subkorpora" with the term
"Haus", "Voll-Export aller Treffer" with "Klima", German route descriptions
(docstrings), German tag names, the placeholder "/data/imports/korpus.csv"
from ``path_hint`` and the example "Leut.*" in the English rejection of a
negated regex.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from candyconc.services.backend import server

#: Umlauts, sharp s and German function words.
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(und|oder|der|die|das|nicht|mit|für|fuer|ist|wird|eine|einen|auf|aus|von|zum|zur|bei|nur|auch)\b")

#: The copilot recipes are German data of the copilot, and their response
#: example shows them as they are.
GERMAN_DATA = "paths//api/v1/copilot/recipes/get/responses/200/content/application/json/example"


def _strings(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, (*path, str(index)))
    elif isinstance(value, str):
        yield "/".join(path), value


def test_openapi_has_no_german_texts():
    found = [
        (path, text[:80])
        for path, text in _strings(server.app.openapi())
        if GERMAN.search(text) and not path.startswith(GERMAN_DATA)
    ]
    assert found == []


def test_named_examples_are_english():
    spec = server.app.openapi()["paths"]

    def example(path: str, method: str, name: str) -> dict:
        body = spec[path][method]["requestBody"]["content"]["application/json"]
        return body["schema"]["examples"][name] if "examples" in body["schema"] else body["examples"][name]

    contrast = example("/api/v1/analysis/contrast", "post", "subcorpora")
    assert contrast["summary"] == "Free contrast of two subcorpora (any corpus)"
    assert contrast["value"]["term"] == "freedom"
    export = example("/api/v1/export/concordance", "post", "basic")
    assert export["summary"] == "Full export of all hits"
    assert export["value"]["query"] == "freedom"
    tags = {tag["name"] for tag in server.app.openapi()["tags"]}
    assert {"Documents", "Analysis", "Search", "Semantic", "Corpora", "Projects"} <= tags


def test_import_path_hints_follow_the_request_language():
    client = TestClient(server.app)
    en = client.get("/api/v1/corpora/import-methods", headers={"Accept-Language": "en"})
    de = client.get("/api/v1/corpora/import-methods", headers={"Accept-Language": "de"})
    assert en.status_code == de.status_code == 200, en.text

    def hint(response, method: str) -> str:
        for entry in response.json()["methods"]:
            if entry["method"] == method:
                return entry["input"]["path_hint"]
        raise AssertionError(f"no method {method} in {response.json()}")

    assert hint(en, "csv") == "/data/imports/corpus.csv"
    assert hint(de, "csv") == "/data/imports/korpus.csv"


def test_negated_regex_example_is_english():
    from cqlhpc.predicates import _NEGATED_REGEX_MESSAGE

    assert "free.*" in _NEGATED_REGEX_MESSAGE.en
    assert "Leut" not in _NEGATED_REGEX_MESSAGE.en
