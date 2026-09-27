"""``cql:[word!="x"%c]`` at ``/api/v1/query`` and ``/api/v1/query/count``.

Before the fix both routes ended in HTTP 500 for this query (the engine raised
an unclassified ValueError). Both must now answer 200 with the tokens whose
case-folded form differs from ``x``, and a negated regular expression must be
rejected with 400 on both routes.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

_INDEX = os.environ.get("CANDYCONC_INDEX_PATH")


@pytest.fixture(scope="module")
def client():
    if not _INDEX or not os.path.isdir(_INDEX):
        pytest.skip("CANDYCONC_INDEX_PATH does not point to a real index")
    from candyconc.services.backend.server import app

    return TestClient(app)


def _count(client, term: str) -> int:
    response = client.get(
        "/api/v1/query/count",
        params={"term": term, "wait_ms": 60000, "start": "true"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("status") == "ready", body
    assert body.get("partial") is False, body
    return int(body["total"])


def _frequent_word(client) -> str:
    rows = client.get("/api/v1/query", params={"term": "cql:[]", "limit": 50}).json()
    words = [str(row["kw"]) for row in rows if str(row["kw"]).isalpha()]
    assert words, rows
    return max(set(words), key=lambda w: sum(1 for x in words if x.lower() == w.lower()))


def test_query_rows_exclude_every_casing(client):
    word = _frequent_word(client)
    response = client.get(
        "/api/v1/query",
        params={"term": f'cql:[word!="{word.upper()}"%c]', "limit": 200},
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows
    assert all(str(row["kw"]).lower() != word.lower() for row in rows)


def test_query_count_is_the_complement(client):
    word = _frequent_word(client)
    not_equal = _count(client, f'cql:[word!="{word}"%c]')
    equal = _count(client, f'cql:[word="{word}"%c]')
    every = _count(client, "cql:[]")
    assert equal > 0
    assert not_equal + equal == every


@pytest.mark.parametrize("path", ["/api/v1/query", "/api/v1/query/count"])
def test_negated_regex_is_rejected_with_400(client, path):
    response = client.get(path, params={"term": 'cql:[word!="th.*"%c]', "wait_ms": 60000})
    assert response.status_code == 400, response.text
    assert "!=" in response.json()["detail"]
