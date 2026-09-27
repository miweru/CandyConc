"""The capability contract speaks the language of the request.

Titles, operation labels and limits of ``GET /api/v1/capabilities`` appear in
the interface (command palette, capability boundary panels, corpus manager).
Before, 28 of 29 first-class titles and every limit were English only, most
operation labels German only. Every such text is now a German and English
pair, German stays the default, and the fingerprint covers both languages.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candyconc.capabilities import build_product_capability_contract
from candyconc.capabilities import product
from candyconc.i18n import LocalizedText

EN = {"Accept-Language": "en, de;q=0.5"}
# Proper names that read the same in both languages.
SAME_IN_BOTH = {"Co-KWIC", "KWIC"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    from candyconc.services.backend.server import app

    return TestClient(app)


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in items}


def _contract_body(client: TestClient, headers: dict[str, str] | None = None) -> dict:
    response = client.get("/api/v1/capabilities", headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()


def test_route_answers_in_german_by_default_and_in_english_on_request(client):
    german = _by_id(_contract_body(client)["capabilities"])
    english = _by_id(_contract_body(client, EN)["capabilities"])

    assert german["analysis.keyness"]["title"] == "Keyness mit Inferenzstatistik"
    assert english["analysis.keyness"]["title"] == "Keyness with inferential statistics"
    assert "Eine externe deutsche Referenzfrequenzliste wird nicht mitgeliefert." in (
        german["analysis.keyness"]["limits"][0]
    )
    assert "There is no bundled external German reference-frequency list." in (
        english["analysis.keyness"]["limits"][0]
    )
    assert german["settings.model_route"]["title"] == "Modellweg"
    assert english["settings.model_route"]["title"] == "Model connection"

    german_ops = _by_id(german["research.annotations"]["operations"])
    english_ops = _by_id(english["research.annotations"]["operations"])
    assert german_ops["research.annotations.scheme_read"]["label"] == "Kodierschema laden"
    assert english_ops["research.annotations.scheme_read"]["label"] == "Load coding scheme"


def test_control_tool_texts_follow_the_request_language(client):
    german = _by_id(
        [{"id": t["name"], **t} for t in _contract_body(client)["copilot_control_tools"]]
    )
    english = _by_id(
        [{"id": t["name"], **t} for t in _contract_body(client, EN)["copilot_control_tools"]]
    )

    assert german["deutung_abgeben"]["label"] == "Untersuchung abgeschlossen"
    assert english["deutung_abgeben"]["label"] == "Investigation complete"
    assert english["deutung_abgeben"]["description"].startswith("The copilot ends the tool phase")


def _contract_texts(contract: dict) -> list[tuple[str, object]]:
    texts: list[tuple[str, object]] = []
    for capability in contract["capabilities"]:
        cid = capability["id"]
        texts.append((f"{cid} title", capability["title"]))
        texts += [(f"{cid} limit", limit) for limit in capability["limits"]]
        texts += [(f"{cid} precondition", item) for item in capability["preconditions"]]
        for operation in capability["operations"]:
            texts.append((f"{operation['id']} label", operation["label"]))
            if operation["description"]:
                texts.append((f"{operation['id']} description", operation["description"]))
    for tool in contract["copilot_control_tools"]:
        texts.append((f"{tool['name']} label", tool["label"]))
        texts.append((f"{tool['name']} description", tool["description"]))
    return texts


def test_every_title_label_and_limit_has_both_languages():
    problems: list[str] = []
    texts = _contract_texts(build_product_capability_contract())
    assert texts
    for where, text in texts:
        if not isinstance(text, LocalizedText):
            problems.append(f"{where}: not bilingual: {text!r}")
            continue
        if not text.de.strip() or not text.en.strip():
            problems.append(f"{where}: empty text {text!r}")
        elif text.de == text.en and text.de not in SAME_IN_BOTH:
            problems.append(f"{where}: German and English are identical: {text.de!r}")
    assert problems == []


def test_route_resolves_every_text_to_the_english_side(client):
    contract = build_product_capability_contract()
    english = _contract_body(client, EN)
    expected = [text.en for _, text in _contract_texts(contract)]
    rendered = [text for _, text in _contract_texts(english)]
    assert rendered == expected


def test_fingerprint_is_the_same_in_both_languages(client):
    german = _contract_body(client)
    english = _contract_body(client, EN)

    assert german["fingerprint_sha256"] == english["fingerprint_sha256"]
    assert german["fingerprint_sha256"] == build_product_capability_contract()["fingerprint_sha256"]


def test_fingerprint_changes_when_a_translation_changes(monkeypatch):
    before = build_product_capability_contract()["fingerprint_sha256"]
    tool = dict(product.COPILOT_CONTROL_TOOLS[0])
    tool["label"] = LocalizedText(tool["label"].de, tool["label"].en + " (changed)")
    monkeypatch.setattr(product, "COPILOT_CONTROL_TOOLS", (tool,))

    assert build_product_capability_contract()["fingerprint_sha256"] != before


def test_annotation_access_is_explained_without_internal_maturity_terms(client):
    capabilities = _by_id(_contract_body(client, EN)["capabilities"])
    assert capabilities["research.annotations"]["limits"][0].startswith("The interface supports")
    assert capabilities["research.annotations_multi_api"]["limits"][0] == (
        "The API provides the full annotation table across coders."
    )
    assert capabilities["research.annotations_import"]["limits"][0] == (
        "Annotations can be imported in bulk through the API."
    )
