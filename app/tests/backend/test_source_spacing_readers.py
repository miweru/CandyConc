"""Readers show the text with its original spacing when the index has it.

Every import writes ``whitespace_after.bin`` since builder revision 3. Before
this change only the KWIC dict rows of ``kwic.py`` and the full text used it:
the concordance of the web interface (``/query``, ``/query/stream``), the
anchor snippet of the document panel (``/doc/snippet``), Co-KWIC, the
concordance export (``match``) and the rows the copilot gets from
``query_runtime.run_query`` read "soul . No words" and "TRUMAN 'S".

Checked here on one small index built twice, with and without the side file:
  * with it every reader returns the text as written, rows carry
    ``token_starts`` so tokens stay addressable;
  * positions, totals, match offsets and sort order are the same for both;
  * without it (and with PII masking on) every output is the legacy
    space-joined text, byte for byte, without new fields.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("spacy", reason="spaCy not installed")

DOCS = [
    {"id": "d0", "text": "PRESIDENT HARRY S. TRUMAN'S ADDRESS. No words can soothe the soul. No words, it seems!"},
    {"id": "d1", "text": "He was a heroic champion of justice and freedom. Tragic fate, it seems, took him."},
]


def _build(out: Path, *, capture: bool):
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.ingest.build_fast_index_from_parquet import build_fast_index_from_rows

    build_fast_index_from_rows(
        [dict(d) for d in DOCS], out, spacy_model="blank:en", text_column="text", id_column="id",
        batch_size=4, n_process=1, split_long_texts=False, capture_whitespace=capture,
    )
    return CorpusIndex(out, read_only=True)


@pytest.fixture(scope="module")
def indexes(tmp_path_factory):
    base = tmp_path_factory.mktemp("spacing")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
        spaced = _build(base / "spaced", capture=True)
        legacy = _build(base / "legacy", capture=False)
    yield spaced, legacy
    spaced.close()
    legacy.close()


@pytest.fixture
def client_for(monkeypatch):
    from fastapi.testclient import TestClient

    from candyconc.services.backend import server as srv

    def _client(idx):
        monkeypatch.setattr(srv, "get_corpus", lambda corpus=None: idx)
        # Both indexes answer as corpus "default": no cached page may cross over.
        srv._QUERY_ROWS_RESPONSE_CACHE.clear()
        srv._QUERY_STREAM_BATCH_CACHE.clear()
        return TestClient(srv.app)

    return _client


@pytest.fixture
def headers():
    from candyconc.services.backend import auth

    if not getattr(auth, "RBAC_ENABLED", False):
        tok = getattr(auth, "DEFAULT_ADMIN_TOKEN", None)
        if tok:
            return {"Authorization": f"Bearer {tok}"}
    auth._USERS["spacing_user"] = auth.User("spacing_user", auth.hash_password("pw"), "user")
    return {"Authorization": f"Bearer {auth._issue_token('spacing_user')}"}


def _tokens(row: dict, side: str) -> list[str]:
    from candyconc.core.source_spacing import side_tokens

    return side_tokens(row, side)


# --------------------------------------------------------------------------- #
# run_query: the rows the copilot and the exports read
# --------------------------------------------------------------------------- #
def test_run_query_rows_have_the_original_spacing(indexes):
    from candyconc.core.query_runtime import run_query

    spaced, legacy = indexes
    rows = list(run_query("soul", 8, corpus=spaced))
    old = list(run_query("soul", 8, corpus=legacy))
    assert [r["pos"] for r in rows] == [r["pos"] for r in old]
    row = rows[0]
    assert row["left"] == "'S ADDRESS. No words can soothe the"
    assert row["kw"] == "soul"
    assert row["right"] == ". No words, it seems!"
    assert row["ws_after_kw"] is False
    # Token view: identical to the legacy split.
    assert _tokens(row, "right") == old[0]["right"].split()
    assert _tokens(row, "left") == old[0]["left"].split()
    # Legacy rows keep the old text and get no new fields.
    assert old[0]["right"] == ". No words , it seems !"
    assert "token_starts" not in old[0] and "ws_after_kw" not in old[0]


def test_cql_span_rows_keep_their_offsets(indexes):
    from candyconc.core.query_runtime import run_query

    spaced, legacy = indexes
    query = "cql:[word=\"TRUMAN\"] [word=\"'S\"]"
    row = list(run_query(query, 3, corpus=spaced))[0]
    old = list(run_query(query, 3, corpus=legacy))[0]
    assert row["pos"] == old["pos"]
    assert row.get("match_offsets") == old.get("match_offsets") == [1]
    assert row["right"].startswith("'S ADDRESS.")
    assert row["ws_after_kw"] is False
    assert old["right"].startswith("'S ADDRESS .")


def test_pii_masking_keeps_the_legacy_text(indexes, monkeypatch):
    """Masking rebuilds the text with single spaces, so it gets no spacing."""
    from candyconc import config
    from candyconc.core.query_runtime import run_query
    from candyconc.core.source_spacing import display_flags

    monkeypatch.setattr(config.APP_CONFIG, "CANDYCONC_ENABLE_PII_MASK", True)
    spaced, _legacy = indexes
    assert display_flags(spaced) is None
    row = list(run_query("soul", 8, corpus=spaced))[0]
    assert "token_starts" not in row
    assert row["right"] == ". No words , it seems !"


def test_sort_by_context_token_is_the_same_as_before(indexes):
    from candyconc.core.query_runtime import run_query
    from candyconc.services.backend.kwic_renderer import sort_kwic_rows

    spaced, legacy = indexes
    for field in ("1R", "2R", "1L", "2L", "node"):
        new = [r["pos"] for r in sort_kwic_rows(list(run_query("it", 6, corpus=spaced)), field)]
        old = [r["pos"] for r in sort_kwic_rows(list(run_query("it", 6, corpus=legacy)), field)]
        assert new == old, field


def test_sampled_rows_have_the_original_spacing(indexes):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes.query import _sampled_query_rows

    spaced, _legacy = indexes
    rows, meta = _sampled_query_rows(
        srv, spaced, "soul", ctx=8, docset_mask=None, case_insensitive=True, sample_size=5, seed=1
    )
    assert meta["drawn"] == 1
    assert rows[0]["right"] == ". No words, it seems!"


# --------------------------------------------------------------------------- #
# REST readers of the web interface
# --------------------------------------------------------------------------- #
def test_query_route(indexes, client_for):
    spaced, legacy = indexes
    new = client_for(spaced).get("/api/v1/query", params={"term": "seems", "ctx": 6})
    assert new.status_code == 200, new.text
    rows = new.json()
    assert {r["right"] for r in rows} == {"!", ", took him."}
    assert all("token_starts" in r for r in rows)
    old = client_for(legacy).get("/api/v1/query", params={"term": "seems", "ctx": 6})
    old_rows = old.json()
    assert [r["pos"] for r in rows] == [r["pos"] for r in old_rows]
    assert new.headers.get("X-CandyConc-Total") == old.headers.get("X-CandyConc-Total") == "2"
    assert {r["right"] for r in old_rows} == {"!", ", took him ."}
    assert not any("token_starts" in r for r in old_rows)


def test_query_route_sorted_and_sampled(indexes, client_for):
    spaced, legacy = indexes
    params = {"term": "it", "ctx": 6, "sort_by": "1R"}
    new = client_for(spaced).get("/api/v1/query", params=params).json()
    old = client_for(legacy).get("/api/v1/query", params=params).json()
    assert [r["pos"] for r in new] == [r["pos"] for r in old]
    assert any(r["right"].startswith("seems!") for r in new)
    sampled = client_for(spaced).get("/api/v1/query", params={"term": "soul", "sample": 3, "seed": 7}).json()
    assert sampled[0]["right"].startswith(". No words,")


def _stream_rows(client, term: str) -> list[dict]:
    body = client.get("/api/v1/query/stream", params={"term": term, "ctx": 6}).text
    rows: list[dict] = []
    event = None
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event == "batch":
            rows.extend(json.loads(line.split(":", 1)[1]))
    return rows


def test_query_stream_route(indexes, client_for):
    spaced, legacy = indexes
    rows = _stream_rows(client_for(spaced), "freedom")
    assert rows and rows[0]["right"] == ". Tragic fate, it seems"
    old = _stream_rows(client_for(legacy), "freedom")
    assert old[0]["right"] == ". Tragic fate , it seems"
    assert rows[0]["pos"] == old[0]["pos"]


def test_document_snippet_and_full_text(indexes, client_for):
    spaced, legacy = indexes
    from candyconc.core.query_runtime import run_query

    pos = list(run_query("soul", 2, corpus=spaced))[0]["pos"]
    snip = client_for(spaced).get("/api/v1/doc/snippet", params={"pos": pos, "ctx": 5}).json()
    assert snip["left"] == "No words can soothe the"
    assert snip["kw"] == "soul"
    assert snip["right"] == ". No words, it"
    assert snip["text"] == "No words can soothe the soul. No words, it"
    old = client_for(legacy).get("/api/v1/doc/snippet", params={"pos": pos, "ctx": 5}).json()
    assert old["text"] == "No words can soothe the soul . No words , it"
    assert (snip["start_pos"], snip["end_pos"]) == (old["start_pos"], old["end_pos"])
    full = client_for(spaced).get("/api/v1/document/0").json()["text"]
    assert full == DOCS[0]["text"]


def test_concordance_export(indexes, client_for, headers):
    spaced, legacy = indexes
    body = {"query": "cql:[word=\"TRUMAN\"] [word=\"'S\"]", "format": "csv", "ctx": 4}
    new = client_for(spaced).post("/api/v1/export/concordance", json=body, headers=headers)
    assert new.status_code == 200, new.text
    lines = [ln for ln in new.text.splitlines() if ln and not ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines))))
    assert rows[0]["match"] == "TRUMAN'S"
    assert rows[0]["left"] == "PRESIDENT HARRY S."
    old = client_for(legacy).post("/api/v1/export/concordance", json=body, headers=headers)
    old_lines = [ln for ln in old.text.splitlines() if ln and not ln.startswith("#")]
    old_rows = list(csv.DictReader(io.StringIO("\n".join(old_lines))))
    assert old_rows[0]["match"] == "TRUMAN 'S"
    assert (rows[0]["match_start"], rows[0]["match_end"]) == (old_rows[0]["match_start"], old_rows[0]["match_end"])


def test_co_kwic_route(indexes, client_for, headers):
    spaced, legacy = indexes
    params = {"term": "words", "collocate": "seems", "window": 5, "ctx": 5}
    new = client_for(spaced).get("/api/v1/analysis/collocates/kwic", params=params, headers=headers)
    assert new.status_code == 200, new.text
    row = new.json()["rows"][0]
    assert row["right"] == ", it seems!"
    old = client_for(legacy).get("/api/v1/analysis/collocates/kwic", params=params, headers=headers).json()["rows"][0]
    assert old["right"] == ", it seems !"
    assert row["coll_offsets"] == old["coll_offsets"]
