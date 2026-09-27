"""Copilot KWIC rows show the text as written, like the other readers.

Every import writes ``whitespace_after.bin`` since builder revision 3. The
readers of the web interface render rows with the original spacing
(core/source_spacing). The copilot did not:

* ``analysis.rechts_hinter_dem_treffer`` rebuilt the right context of a
  multi-token hit from the raw space-joined tokens, and ``match`` was joined
  with single spaces,
* the sampled rows of ``run_cqlf_query`` dropped ``token_starts`` and the two
  spacing flags, so sorting and the match span split attached tokens wrongly,
* the rows of the full path kept ``token_starts`` and the flags, fields the
  response schema forbids: on the MCP seam that is HTTP 500 "Invalid result",
  whenever all hits fit into the limit,
* the evidence line (``kwic[i]``), the package line (``Treffer i``) and with
  them the quote check joined left, node and right with a space, so a
  verbatim quote across the node ("the freedom-loving people") counted as not
  found (Englischprobe b: "destroy freedom , only" against
  "destroy freedom, only").

An index without the side file keeps the rows of today, byte for byte.
"""

from __future__ import annotations

import pytest
from jsonschema import validate

pytest.importorskip("spacy", reason="spaCy not installed")

DOCS = [
    {"id": "d0", "text": "No words can soothe the soul. No words, it seems! We thank the freedom-loving people of the world."},
    {"id": "d1", "text": "He was a champion of justice and freedom. Tragic fate, it seems, took him."},
]


def _build(out, *, capture: bool):
    from candyconc.core.corpus_index import CorpusIndex
    from candyconc.ingest.build_fast_index_from_parquet import build_fast_index_from_rows

    build_fast_index_from_rows(
        [dict(d) for d in DOCS], out, spacy_model="blank:en", text_column="text", id_column="id",
        batch_size=4, n_process=1, split_long_texts=False, capture_whitespace=capture,
    )
    return CorpusIndex(out, read_only=True)


@pytest.fixture(scope="module")
def indexes(tmp_path_factory):
    base = tmp_path_factory.mktemp("copilot_spacing")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
        spaced = _build(base / "spaced", capture=True)
        legacy = _build(base / "legacy", capture=False)
    yield spaced, legacy
    spaced.close()
    legacy.close()


@pytest.fixture
def tools():
    from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

    return _load_real_tool_wrappers()


def _run(tools, monkeypatch, idx, **kwargs):
    monkeypatch.setattr(tools, "_resolve_docset_doc_ids", lambda corpus, docset: (idx, None))
    monkeypatch.setattr(tools, "_resolve_corpus_index", lambda corpus: idx)
    return tools.run_cqlf_query_tool(**kwargs)


def _item(output: dict, query: str) -> dict:
    from candyconc.candyconc_copilot.grounding_facts import make_evidence_item

    return make_evidence_item(
        item_id="E_run_cqlf_query_1", tool="run_cqlf_query", tool_call_id="c1",
        query={"query": query}, output=output, analysis_family="kwic_context",
    ).to_dict()


def test_every_path_meets_the_schema_and_carries_the_flags(indexes, tools, monkeypatch):
    spaced, _legacy = indexes
    for kwargs in (
        {"query": "soul", "limit": 1000},                      # all hits: full path
        {"query": "it", "limit": 1000, "sort_by": "1R"},
        {"query": "it", "limit": 1},                           # sampled
        {"query": '[word="soul"] [word="."]', "limit": 1000},  # span
    ):
        out = _run(tools, monkeypatch, spaced, **kwargs)
        validate(out, tools.RUN_CQLF_RESPONSE)
        for row in out["rows"]:
            assert "token_starts" not in row, kwargs
            assert isinstance(row.get("ws_after_kw"), bool), kwargs


def test_the_right_context_of_a_span_is_written_as_in_the_text(indexes, tools, monkeypatch):
    spaced, legacy = indexes
    row = _run(tools, monkeypatch, spaced, query='[word="soul"] [word="."]', limit=1000, ctx=4)["rows"][0]
    assert row["match"] == "soul."
    assert row["right"] == ". No words, it"
    old = _run(tools, monkeypatch, legacy, query='[word="soul"] [word="."]', limit=1000, ctx=4)["rows"][0]
    assert old["match"] == "soul ."
    assert old["right"] == ". No words , it"
    assert "ws_after_kw" not in old and "token_starts" not in old


def test_evidence_line_package_and_quote_check_read_the_same_text(indexes, tools, monkeypatch):
    from candyconc.candyconc_copilot import interpretation_synthesis as ds

    spaced, legacy = indexes
    out = _run(tools, monkeypatch, spaced, query="freedom", limit=1000, ctx=4)
    item = _item(out, "freedom")
    nummer = next(i for i, r in enumerate(out["rows"]) if r["right"].startswith("-loving"))
    assert f'kwic[{nummer}] "! We thank the freedom-loving people of"' in item["grounding_surface"]
    paket = [z.strip() for z in ds._knapp_treffer(item, item["grounding_surface"])]
    assert any(z.startswith(f"Treffer {nummer}: ! We thank the [freedom]-loving people of  (") for z in paket), paket
    text = "Ein Beleg: „We thank the freedom-loving people of“ [[beleg:E_run_cqlf_query_1]]."
    assert ds._unverifizierte_zitate(text, [item]) == []

    # Without the side file the lines are those of today.
    old = _item(_run(tools, monkeypatch, legacy, query="freedom", limit=1000, ctx=4), "freedom")
    assert any(z.startswith('kwic[') and '"! We thank the freedom - loving people of"' in z
               for z in old["grounding_surface"])


def test_kwic_context_is_written_as_in_the_text(indexes, tools, monkeypatch):
    spaced, legacy = indexes
    monkeypatch.setattr(tools, "_resolve_corpus_index", lambda corpus: spaced)
    pos = _run(tools, monkeypatch, spaced, query="soul", limit=1000)["rows"][0]["pos"]
    out = tools.kwic_context_tool(pos=pos, ctx=4)
    validate(out, tools.KWIC_CONTEXT_RESPONSE)
    assert (out["left"], out["kw"], out["right"]) == ("words can soothe the", "soul", ". No words,")
    monkeypatch.setattr(tools, "_resolve_corpus_index", lambda corpus: legacy)
    old = tools.kwic_context_tool(pos=pos, ctx=4)
    assert (old["left"], old["kw"], old["right"]) == ("words can soothe the", "soul", ". No words ,")

