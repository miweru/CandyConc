"""Round-5 copilot↔REST parity behavioural tests on the REAL bench index.

Closes three copilot-tool leaks where a sibling REST/UI surface already did the
right thing (no mocks — drives the real tool_wrappers against the frozen bench
index, with the active corpus set in-process; no HTTP backend required):

* FIX-A  copilot ``frequency_list`` POS-filtered branch must apply the SAME
  analyst-token filter the REST/UI path applies, so emoji/symbol/|LBR| tokens
  never leak and the row total equals REST.
* FIX-A2 POS-filtered ``group_by=lemma`` must count the lemma stream rather than
  silently returning surface forms labelled as lemmas.
* FIX-B  a malformed CQL query on ``run_cqlf_query`` / ``query_count`` must raise
  ``ToolInputError`` (MCP boundary -> HTTP 400), matching the REST ``/query``
  4xx, not a misleading 500.
* FIX-D  ``dispersion_offsets`` must resolve bracket-CQL forms (``[word=".*"]``,
  ``[pos="NOUN"]``) through the REST dispersion seam — non-zero, sentinel-
  filtered hits — instead of returning total_hits=0.

The real tool_wrappers + registry are loaded under their production names and
every touched ``sys.modules`` entry is restored, so the top-level conftest stub
that shadows ``candyconc_copilot.tool_wrappers`` is not disturbed for any other
test (the proven pattern from tests/integration/test_tool_surface_runtime.py).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from jsonschema import validate as _json_validate

import candyconc.core.query_runtime as qrt
from candyconc.analysis_defaults import filter_frequency_frame, is_analyst_token
from candyconc.core.corpus_index import CorpusIndex

_INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")
_SRC = Path(__file__).resolve().parents[2] / "src" / "candyconc"


class _NoopMetric:
    def __init__(self, *args, **kwargs):
        pass

    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return None


def _fake_prometheus() -> types.ModuleType:
    mod = types.ModuleType("prometheus_client")
    mod.Counter = _NoopMetric
    mod.Histogram = _NoopMetric
    mod.Gauge = _NoopMetric
    mod.Summary = _NoopMetric
    return mod


def _load_real_tool_wrappers():
    """Load the REAL tool_wrappers, restoring every touched sys.modules entry.

    ``prometheus_client`` is masked with no-op metrics for the duration of the
    load: ``registry.py`` registers module-level Counters in the GLOBAL
    CollectorRegistry, and re-executing it under spec import would otherwise raise
    "Duplicated timeseries" when this module is collected alongside other tests
    that already imported the real registry (the proven pattern from
    tests/tooling/_real_tooling.py). The real backend ``server`` module is
    restored on exit, so the tools' call-time lazy ``import server`` resolves the
    production seam (``_dispersion_positions_for_term`` / ``_is_query_user_error``).
    """
    touched = [
        "prometheus_client",
        "candyconc.tooling.registry",
        "candyconc.candyconc_copilot.tool_wrappers",
        "candyconc_copilot.tool_wrappers",
    ]
    saved = {name: sys.modules.get(name) for name in touched}
    had = {name: name in sys.modules for name in touched}
    try:
        sys.modules["prometheus_client"] = _fake_prometheus()

        reg_path = _SRC / "tooling" / "registry.py"
        reg_spec = importlib.util.spec_from_file_location(
            "candyconc.tooling.registry", reg_path
        )
        registry = importlib.util.module_from_spec(reg_spec)
        sys.modules["candyconc.tooling.registry"] = registry
        reg_spec.loader.exec_module(registry)

        tw_path = _SRC / "candyconc_copilot" / "tool_wrappers.py"
        tw_spec = importlib.util.spec_from_file_location(
            "candyconc.candyconc_copilot.tool_wrappers", tw_path
        )
        tool_wrappers = importlib.util.module_from_spec(tw_spec)
        sys.modules["candyconc.candyconc_copilot.tool_wrappers"] = tool_wrappers
        sys.modules["candyconc_copilot.tool_wrappers"] = tool_wrappers
        tw_spec.loader.exec_module(tool_wrappers)
        return tool_wrappers
    finally:
        for name in touched:
            if had[name]:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


_TW = _load_real_tool_wrappers()


@pytest.fixture(scope="module")
def active_index():
    if not _INDEX_PATH or not os.path.isdir(_INDEX_PATH):
        pytest.skip("CANDYCONC_INDEX_PATH not set to a real index directory")
    idx = CorpusIndex(_INDEX_PATH)
    qrt._CORPUS_INDEX = idx
    from candyconc.services.backend import server as _server

    prev = getattr(_server, "_INDEX", None)
    _server.set_default_index(idx)
    yield idx
    qrt._CORPUS_INDEX = None
    _server.set_default_index(prev)
    idx.close()


# --------------------------------------------------------------------------- #
# FIX-A: copilot POS-filtered frequency == REST (analyst-token filtered).
# --------------------------------------------------------------------------- #
def test_frequency_list_pos_branch_drops_non_analyst_tokens(active_index):
    res = _TW.frequency_list_tool(pos="NOUN", group_by="word", limit=100)
    assert res["status"] == "success"
    # No emoji / symbol / |LBR| / punctuation may headline the POS ranking.
    leaks = [r["word"] for r in res["rows"] if not is_analyst_token(r["word"])]
    assert leaks == [], f"non-analyst tokens leaked into copilot POS frequency: {leaks}"

    # The copilot total must equal the REST sibling's total for the same query:
    # frequency_list_docset(pos_prefix=...) THEN filter_frequency_frame (the seam
    # routes/analysis.py applies). Both report the row count of the filtered frame.
    all_ids = np.arange(len(active_index.fast_index.doc_metadata), dtype=np.uint32)
    rest = filter_frequency_frame(
        active_index.frequency_list_docset(all_ids, pos_prefix="NOUN")
    )
    assert res["total"] == len(rest)


def test_frequency_list_pos_filtered_lemmas_are_real_lemmas(active_index):
    res = _TW.frequency_list_tool(pos="VERB", group_by="lemma", limit=12)

    assert res["status"] == "success"
    assert res["rows"][:5] == [
        # Word rates use 46,625 analysis tokens rather than 56,191 raw tokens.
        {"word": "haben", "f": 147, "per_million": 3152.8},
        {"word": "geben", "f": 142, "per_million": 3045.6},
        {"word": "machen", "f": 93, "per_million": 1994.6},
        {"word": "kommen", "f": 86, "per_million": 1844.5},
        {"word": "gehen", "f": 85, "per_million": 1823.1},
    ]
    assert "gibt" not in {row["word"] for row in res["rows"]}


# --------------------------------------------------------------------------- #
# FIX-B: malformed CQL -> ToolInputError (MCP boundary maps to 400), like REST.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_query", ['[pos="NOUN"', 'a"b)c['])
def test_query_count_malformed_cql_raises_tool_input_error(active_index, bad_query):
    with pytest.raises(_TW.ToolInputError):
        _TW.query_count_tool(bad_query)


@pytest.mark.parametrize("bad_query", ['[pos="NOUN"', 'a"b)c['])
def test_run_cqlf_query_malformed_cql_raises_tool_input_error(active_index, bad_query):
    with pytest.raises(_TW.ToolInputError):
        _TW.run_cqlf_query_tool(bad_query)


# A ReDoS-rejected regex (nested unbounded quantifiers) and an unknown sort field
# are caller mistakes -> ToolInputError (MCP boundary 400), not a leaked 500. The
# DoS guard itself still fires; only the rejection status is asserted here.
# (COPILOT-REDOS-CLASSIFY-500 / COPILOT-BADSORT-500)
def test_query_count_redos_regex_raises_tool_input_error(active_index, monkeypatch):
    monkeypatch.setenv("CANDYCONC_REGEX_BACKEND", "re")
    with pytest.raises(_TW.ToolInputError):
        _TW.query_count_tool('[word="(a+)+$"]')


def test_run_cqlf_query_redos_regex_raises_tool_input_error(active_index, monkeypatch):
    monkeypatch.setenv("CANDYCONC_REGEX_BACKEND", "re")
    with pytest.raises(_TW.ToolInputError):
        _TW.run_cqlf_query_tool('[word="(a+)+$"]', limit=3)


def test_run_cqlf_query_unknown_sort_field_raises_tool_input_error(active_index):
    with pytest.raises(_TW.ToolInputError):
        _TW.run_cqlf_query_tool("und", limit=3, sort_by="99X")


# --------------------------------------------------------------------------- #
# FIX-D: dispersion bracket-CQL resolves via the REST seam (non-zero, sentinel
# filtered) and equals the canonical /query/count totals.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "term,expected",
    [
        ('[word=".*"]', 55550),  # every real token, |LBR| dropped
        ('[word="|LBR|"]', 0),  # the sentinel itself never matches
        ('[pos="NOUN"]', 9740),  # sentinel-free POS count
    ],
)
def test_dispersion_bracket_cql_matches_canonical_counts(active_index, term, expected):
    # Before FIX-D each of these bracket-CQL forms returned total_hits=0 (the term
    # was treated as one literal plain-text token); now they resolve through the
    # REST dispersion seam and equal the canonical /query/count totals.
    profile = _TW.dispersion_offsets_tool(term)
    assert profile["status"] == "success"
    assert profile["total_hits"] == expected


# --------------------------------------------------------------------------- #
# COPILOT-COUNT-BRACKETCQL-DIVERGE: the un-prefixed CWB bracket form ``[pos=NOUN]``
# (no quotes, no ``cql:`` prefix) must yield the EXACT REST count on the copilot,
# not the silent row-cap collapse the run_query limit=1 path used to return.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "query",
    ["[pos=NOUN]", '[pos="NOUN"]', "und", "und|oder", '[word="|LBR|"]', '[word=".*"]'],
)
def test_query_count_equals_rest_for_every_form(active_index, query):
    # The copilot ``query_count`` must route through the SAME exact-count primitive
    # the REST /query/count route uses (``server._compute_query_count``). Before the
    # fix the un-prefixed bracket ``[pos=NOUN]`` collapsed to total=1 (the limit=1
    # row cap) while REST returned 9740; now both are byte-identical for every form.
    from candyconc.services.backend.server import _compute_query_count

    if query == "und|oder":
        # Beide zaehlten hier still 0. Seit dem 2026-09-26 melden beide, wie Oder
        # in der Wortsuche heisst (test_word_search_reports_foreign_syntax).
        # Paritaet heisst fuer diese Form: dieselbe Meldung auf beiden Wegen.
        with pytest.raises(ValueError) as rest_fehler:
            _compute_query_count(active_index, query, 0, None, None, None, case_insensitive=True)
        with pytest.raises(_TW.ToolInputError) as copilot_fehler:
            _TW.query_count_tool(query)
        assert str(copilot_fehler.value) == str(rest_fehler.value)
        return
    rest_total, _ms, _partial = _compute_query_count(
        active_index, query, 0, None, None, None, case_insensitive=True
    )
    copilot = _TW.query_count_tool(query)
    assert copilot["status"] == "success"
    assert copilot["total"] == rest_total
    if query == "[pos=NOUN]":
        assert copilot["total"] == 9740  # the regression sentinel


@pytest.mark.parametrize("query", ["[pos=NOUN]", '[pos="NOUN"]', "und"])
def test_run_cqp_total_equals_rest_for_bracket_forms(active_index, query):
    # run_cqlf_query's exact-count callback is suppressed when the scan is capped;
    # the cql: branch still yields the exact total but the un-prefixed bracket
    # ([pos=NOUN]) did not -> total collapsed to the row cap (5) while REST counted
    # 9740. The total now resolves via the same _compute_query_count primitive, so
    # the rows stay capped (truncated) but the reported total is exact == REST.
    from candyconc.services.backend.server import _compute_query_count

    rest_total, _ms, _partial = _compute_query_count(
        active_index, query, 0, None, None, None, case_insensitive=True
    )
    res = _TW.run_cqlf_query_tool(query, limit=5)
    assert res["status"] == "success"
    assert res["total"] == rest_total
    assert res["truncated"] == (rest_total > len(res["rows"]))
    if query == "[pos=NOUN]":
        assert res["total"] == 9740  # the regression sentinel (was 5)


def test_dispersion_unprefixed_legacy_bracket_cql_matches_rest(active_index):
    # Legacy bracket attributes such as ``[pos=NOUN]`` are accepted by /query. The
    # copilot dispersion tool must follow that same route instead of silently
    # scanning the literal string and returning total_hits=0.
    from candyconc.services.backend.server import _compute_query_count

    rest_total, _ms, _partial = _compute_query_count(
        active_index, "[pos=NOUN]", 0, None, None, None, case_insensitive=True
    )
    result = _TW.dispersion_offsets_tool("[pos=NOUN]")
    assert result["status"] == "success"
    assert result["total_hits"] == rest_total
    assert result["total_hits"] == 9740


# --------------------------------------------------------------------------- #
# FIX-A2 (P2): document_search returns a ``doc_id`` field, but the declared
# response schema (additionalProperties:false) omitted it -> the MCP response
# gate (mcp_server.py json_validate) rejected EVERY result with HTTP 500, so the
# tool was non-functional. Re-running the gate's exact validation must now pass.
# --------------------------------------------------------------------------- #
def test_document_search_result_passes_response_schema(active_index):
    res = _TW.document_search_tool("Menschen", top_n=5)
    assert res["status"] == "success"
    assert res["rows"], "expected at least one document hit for a frequent term"
    # Every row really carries doc_id (the field the schema must now declare).
    assert all("doc_id" in row for row in res["rows"])
    # The same validation the MCP gate runs (mcp_server.py:522) — was a
    # ValidationError -> HTTP 500 before doc_id was added to the schema.
    _json_validate(res, _TW.DOCUMENT_SEARCH_RESPONSE)


# --------------------------------------------------------------------------- #
# FIX-B2 (P2): lexical_diversity returns ``corpus_raw_token_count``, absent from
# the declared response schema (additionalProperties:false) -> every call 500ed
# at the MCP response gate. The gate's validation must now pass.
# --------------------------------------------------------------------------- #
def test_lexical_diversity_result_passes_response_schema(active_index):
    res = _TW.lexical_diversity_tool()
    assert res["status"] == "success"
    assert "corpus_raw_token_count" in res
    # The exact MCP gate validation — ValidationError -> HTTP 500 before the fix.
    _json_validate(res, _TW.LEXICAL_DIVERSITY_RESPONSE)


# --------------------------------------------------------------------------- #
# FIX-C2 (P2/REGRESSION): copilot ngram_frequency must apply the SAME
# is_analyst_token filter the REST /analysis/ngrams path applies, so |LBR|,
# emoji and punctuation never leak into the top n-grams and the copilot top list
# is byte-identical to the REST sibling.
# --------------------------------------------------------------------------- #
def test_ngram_frequency_excludes_non_analyst_tokens_and_matches_rest(
    active_index, monkeypatch
):
    res = _TW.ngram_frequency_tool(min_n=2, max_n=2, limit=100)
    assert res["status"] == "success"
    assert res["rows"], "expected at least one bigram"
    # No |LBR|/marker, emoji or punctuation token may appear in any top n-gram.
    leaks = [
        row["ngram"]
        for row in res["rows"]
        if any(not is_analyst_token(tok) for tok in row["ngram"].split(" "))
    ]
    assert leaks == [], f"non-analyst tokens leaked into copilot ngram top list: {leaks}"

    # Compare with the actual REST route so its frequency and token-ID tie
    # breaking is tested. Reimplementing the expected ranking inline would
    # only compare the tool implementation with a copy of itself.
    import asyncio

    from candyconc.services.backend import server as _server
    from candyconc.services.backend.routes import analysis as _rest

    # Ueber monkeypatch, damit die Zugriffspruefung nach dem Test wieder
    # steht. Eine rohe Zuweisung hier hat in einem vollen Suite-Lauf vier
    # Auth-Tests umgeworfen (test_server_login, test_ws_ticket_auth): der
    # Patch blieb fuer alles stehen, was danach lief.
    monkeypatch.setattr(_server, "_require_user_access", lambda *a, **k: None)
    rest = asyncio.run(_rest.analysis_ngrams(payload={
        "corpus": "default", "min_n": 2, "max_n": 2, "limit": 100, "min_freq": 1,
    }))
    rest_rows = [
        {"ngram": r.get("ngram") or r.get("token"), "freq": r.get("freq"),
         "n": r.get("n")}
        for r in rest["rows"]
    ]
    assert res["rows"] == rest_rows
    assert res["total"] == int(rest["total_candidates"])


# Tools return per_million and corpus_tokens so consumers need not
# recompute rates. Frozen counts use a 56,191-token reference index.
# Word rates use its 46,625 analysis tokens, with the raw token count
# reported separately as denominator_tokens_raw.
def test_query_count_carries_precomputed_per_million(active_index):
    tokens = int(active_index.token_count())
    assert tokens == 56191  # Bench-Kanon
    woerter = int(active_index.word_count())
    assert woerter == 46625  # Bench-Kanon der Analysetoken

    res = _TW.query_count_tool('cql:[pos="NOUN"]')
    assert res["status"] == "success" and res["total"] == 9740
    assert res["corpus_tokens"] == tokens
    assert res["denominator_tokens"] == woerter
    assert res["denominator_tokens_raw"] == tokens
    assert res["denominator_scope"] == "corpus"
    assert res["denominator_source"] == "corpus_index.word_count"
    assert res["per_million"] == pytest.approx(9740 * 1_000_000 / woerter, abs=0.05)
    assert res["per_million"] == 208900.8

    res_und = _TW.query_count_tool("und")
    assert res_und["total"] == 919
    assert res_und["per_million"] == 19710.5


def test_query_count_docset_uses_docset_token_denominator(active_index):
    scope = _TW.create_docset_tool(query="Demokratie")
    corpus_tokens = int(active_index.token_count())
    assert 0 < scope["token_count"] < corpus_tokens

    res = _TW.query_count_tool("und", docset_id=scope["docset_id"])

    assert 0 < scope["word_count"] < scope["token_count"]
    assert res["corpus_tokens"] == corpus_tokens
    assert res["denominator_tokens"] == scope["word_count"]
    assert res["denominator_tokens_raw"] == scope["token_count"]
    assert res["denominator_scope"] == "docset"
    assert res["denominator_source"] == "corpus_index.docset_word_count"
    assert res["per_million"] == pytest.approx(
        res["total"] * 1_000_000 / scope["word_count"], abs=0.05
    )


def test_frequency_list_rows_carry_per_million(active_index):
    tokens = int(active_index.token_count())
    woerter = int(active_index.word_count())
    res = _TW.frequency_list_tool(limit=5)
    assert res["status"] == "success"
    assert res["corpus_tokens"] == tokens
    assert res["denominator_tokens"] == woerter
    assert res["denominator_tokens_raw"] == tokens
    assert len(res["rows"]) == 5
    for row in res["rows"]:
        assert row["per_million"] == pytest.approx(
            row["f"] * 1_000_000 / woerter, abs=0.05
        )
    und_row = next(r for r in res["rows"] if r["word"] == "und")
    assert und_row["f"] == 919 and und_row["per_million"] == 19710.5


def test_frequency_list_docset_uses_docset_token_denominator(active_index):
    scope = _TW.create_docset_tool(query="Demokratie")
    corpus_tokens = int(active_index.token_count())

    res = _TW.frequency_list_tool(
        docset_id=scope["docset_id"],
        limit=10,
    )

    assert res["corpus_tokens"] == corpus_tokens
    assert res["denominator_tokens"] == scope["word_count"]
    assert res["denominator_tokens_raw"] == scope["token_count"]
    assert res["denominator_scope"] == "docset"
    assert res["denominator_source"] == "corpus_index.docset_word_count"
    for row in res["rows"]:
        assert row["per_million"] == pytest.approx(
            row["f"] * 1_000_000 / scope["word_count"],
            abs=0.05,
        )


def test_response_schemas_declare_per_million_fields():
    """MCP-Gate: additionalProperties:false - Schema MUSS die Felder listen."""
    qc = _TW.QUERY_COUNT_RESPONSE["properties"]
    assert {
        "per_million",
        "corpus_tokens",
        "denominator_tokens",
        "denominator_scope",
        "denominator_source",
    } <= set(qc)
    fr = _TW.FREQUENCY_RESPONSE["properties"]
    assert {
        "corpus_tokens",
        "denominator_tokens",
        "denominator_scope",
        "denominator_source",
        "group_by",
    } <= set(fr)
    assert "per_million" in fr["rows"]["items"]["properties"]


def test_collocation_comparison_schemas_require_effective_method_and_scope():
    assert {
        "query_mode",
        "attribute",
        "case_insensitive",
        "scope",
    } <= set(_TW.QUERY_COUNT_RESPONSE["required"])
    assert {
        "requested_term",
        "effective_term",
        "window",
        "within_sentence",
        "min_freq",
        "sort_by",
        "scope",
        "method",
    } <= set(_TW.COLLOCATE_RESPONSE["required"])
