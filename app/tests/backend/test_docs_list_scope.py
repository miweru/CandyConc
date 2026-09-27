"""The reader lists the documents of the active scope (erprobung B6).

``/docs/list`` took one docset, the reader's own field filter, and the reader
never sent the active scope of the interface. With a subcorpus active the
reader still listed all 65 documents. ``scope_docset_id`` restricts the list
to the scope, and together with ``docset_id`` to the documents in both.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

_INDEX = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def client():
    if not _INDEX or not os.path.isdir(_INDEX):
        pytest.skip("CANDYCONC_INDEX_PATH does not point to a real index")
    from candyconc.services.backend.server import app

    return TestClient(app)


def _axis(client):
    """A metadata field with a few values, read from the schema of the index."""
    token = client.get("/api/v1/auth/dev-token").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    schema = client.get("/api/v1/analysis/meta_schema", headers=headers).json()
    for field in schema.get("metadataFields", []):
        count = field.get("stringValueCount") or 0
        if 1 < count <= 20:
            values = client.post(
                "/api/v1/analysis/meta_values",
                headers=headers,
                json={"fields": [field["name"]]},
            ).json()["values"][field["name"]]
            return field["name"], sorted(values)
    return None


def _doc_ids(client, **params) -> list[int]:
    total = client.get("/api/v1/docs/list", params={"limit": 1, **params}).json()["total"]
    ids: list[int] = []
    for offset in range(0, total, 200):
        page = client.get("/api/v1/docs/list", params={"limit": 200, "offset": offset, **params})
        assert page.status_code == 200, page.text
        ids.extend(int(row["doc_id"]) for row in page.json()["items"])
    return ids


def _meta_docset(client, field, value) -> str:
    response = client.post(
        "/api/v1/analysis/docset_from_meta",
        json={"corpus": "default", "filters": {field: value}},
    )
    assert response.status_code == 200, response.text
    return response.json()["docset_id"]


def test_scope_restricts_the_list(client):
    axis = _axis(client)
    if axis is None:
        pytest.skip("no metadata field with several values on this index")
    field, values = axis
    scope = _meta_docset(client, field, values[0])
    everything = _doc_ids(client)
    in_scope = _doc_ids(client, scope_docset_id=scope)
    assert 0 < len(in_scope) < len(everything)
    assert in_scope == _doc_ids(client, docset_id=scope)


def test_scope_and_reader_filter_intersect(client):
    axis = _axis(client)
    if axis is None:
        pytest.skip("no metadata field with several values on this index")
    field, values = axis
    scope = _meta_docset(client, field, values[0])
    other = _meta_docset(client, field, values[1])
    assert _doc_ids(client, docset_id=other, scope_docset_id=scope) == []
    both = _doc_ids(client, docset_id=scope, scope_docset_id=scope)
    assert both == _doc_ids(client, docset_id=scope)


def test_a_docset_of_another_corpus_is_rejected(client):
    from candyconc.services.backend.docsets import _store_docset

    foreign = _store_docset("another_corpus", np.asarray([0, 1], dtype=np.uint32), 2)
    response = client.get("/api/v1/docs/list", params={"scope_docset_id": foreign})
    # 422 with a code, like every docset of another corpus (one status per code).
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "docset.other_corpus"
    english = client.get(
        "/api/v1/docs/list",
        params={"scope_docset_id": foreign},
        headers={"Accept-Language": "en"},
    )
    assert english.json()["detail"] == "docset_id belongs to a different corpus"
