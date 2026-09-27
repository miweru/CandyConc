"""r6 copilot honesty parity: semantic_search |LBR| strip + similar_words OOV contract.

Both are REST==copilot sibling-surface fixes the round-6 acceptance review flagged:
- N10-SEM-1: the copilot ``semantic_search`` tool returned passage rows raw, leaking
  the index-only ``|LBR|`` sentinel into the LLM/renderer evidence (the run_cqlf_query
  path already normalises it).
- THES-1: the copilot ``similar_words`` tool reported an out-of-vocabulary seed as a
  service outage (``status: unavailable`` / ``semantic_index_missing``) instead of the
  honest empty 200 the REST route (routes/semantic.py) returns for a per-term miss.

The top-level conftest shadows ``tool_wrappers`` with a stub module, so the REAL
module is loaded via the proven ``_load_real_tool_wrappers`` helper (sys.modules
restored on exit). The tool functions are called directly; the /mcp/call corpus
feature gate is orthogonal to the tool-function contract under test here.
"""

from __future__ import annotations

import candyconc.core.cql_macros as cql_macros
import candyconc.services.backend.routes.semantic as _routes_semantic
from candyconc.candyconc_copilot import analysis as _analysis

from tests.ai.test_tool_wrappers_parity_r5 import _load_real_tool_wrappers

_TW = _load_real_tool_wrappers()


def test_semantic_search_tool_strips_linebreak_sentinel(monkeypatch) -> None:
    leaky_rows = [
        {"doc_id": "d1", "score": 0.91, "text": "Der Klimawandel|LBR|ist real."},
        {"doc_id": "d2", "score": 0.88, "text": "Ganz ohne Sentinel."},
    ]
    monkeypatch.setattr(_TW, "_semantic_search", lambda *a, **k: object())
    monkeypatch.setattr(_TW, "_coerce_semantic_search_result", lambda raw: (leaky_rows, {"backend": "spacy"}))

    out = _TW.semantic_search_tool("Klimawandel", top_n=20, level="doc")

    assert out["status"] == "success"
    assert len(out["rows"]) == 2
    # The sentinel must not survive into the evidence handed to the LLM/renderer.
    assert all("|LBR|" not in str(v) for row in out["rows"] for v in row.values())


def test_similar_words_oov_seed_is_empty_not_outage(monkeypatch) -> None:
    monkeypatch.setattr(_TW, "_resolve_corpus_index", lambda corpus: object())
    # SEM-01: this test exercises the ENGINE-result classification (OOV seed ->
    # empty success), which sits DOWNSTREAM of the word_similarity capability gate.
    # Let the shared gate pass so the engine path is reached (the gate's own
    # unavailable contract is pinned by the dedicated gate-parity tests below).
    monkeypatch.setattr(_routes_semantic, "_word_similarity_available", lambda idx: True)

    def _raise_oov(*_a, **_k):
        raise RuntimeError("Keine Embeddings für sim() gefunden.")

    monkeypatch.setattr(cql_macros, "similar_words_scored", _raise_oov)

    out = _TW.similar_words_tool("ÄÖÜ", k=5, corpus="default")

    # OOV seed: index/backend fine, this term just isn't in the vocabulary ->
    # honest empty 200, NOT an outage (semantic_index_missing).
    assert out["status"] == "success"
    assert out["neighbours"] == []
    assert "code" not in out


class _FreqOnlyIndex:
    """Stand-in corpus index exposing only ``frequency_list`` (the seam the tool
    joins against). The engine call is monkeypatched away."""

    def __init__(self, freq):
        self._freq = freq

    def frequency_list(self):
        rows = [{"word": w, "f": f} for w, f in self._freq.items()]

        class _DF:
            def to_dicts(self_inner):
                return rows

        return _DF()


def test_similar_words_drops_corpus_absent_neighbour_like_rest(monkeypatch) -> None:
    """Copilot == REST corpus-restriction: a neighbour the engine ranks but that
    is absent from THIS corpus (corpus_frequency < 1) must be dropped, exactly as
    routes/semantic.py:254-260 does. Present neighbours survive."""
    # "present" exists in the corpus (freq 7); "absent" was ranked by the
    # embedding backend but never indexed in THIS corpus (freq 0).
    monkeypatch.setattr(
        _TW, "_resolve_corpus_index", lambda corpus: _FreqOnlyIndex({"present": 7})
    )
    # SEM-01: corpus-restriction is DOWNSTREAM of the capability gate; let the gate
    # pass so the engine + frequency-join path is reached.
    monkeypatch.setattr(_routes_semantic, "_word_similarity_available", lambda idx: True)
    monkeypatch.setattr(
        cql_macros,
        "similar_words_scored",
        lambda *_a, **_k: [
            {"word": "present", "score": 0.81},
            {"word": "absent", "score": 0.77},
        ],
    )

    out = _TW.similar_words_tool("Menschen", k=5, corpus="default")

    assert out["status"] == "success"
    words = [n["word"] for n in out["neighbours"]]
    # The corpus-absent neighbour must NOT leak through copilot (it doesn't via REST).
    assert "absent" not in words
    assert words == ["present"]
    # Every surviving neighbour is corpus-present (>= 1), like the REST contract.
    assert all(n["corpus_frequency"] >= 1 for n in out["neighbours"])


def test_similar_words_genuine_outage_still_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(_TW, "_resolve_corpus_index", lambda corpus: object())
    # SEM-01: isolate the ENGINE-outage degradation from the capability gate by
    # letting the gate pass, so the unavailable status here is provably driven by
    # the engine raising (not by the word_similarity gate).
    monkeypatch.setattr(_routes_semantic, "_word_similarity_available", lambda idx: True)

    def _raise_outage(*_a, **_k):
        raise RuntimeError("Vektorindex fehlt oder ist unvollständig.")

    monkeypatch.setattr(cql_macros, "similar_words_scored", _raise_outage)

    out = _TW.similar_words_tool("Menschen", k=5, corpus="default")

    # A genuine missing-index outage must still degrade to unavailable (not masked
    # as an empty success), with the code REST answers (word_vectors.service_error).
    assert out["status"] == "unavailable"
    assert out["code"] == "word_vectors.service_error"
    assert out["neighbours"] == []


# ---------------------------------------------------------------------------
# SEM-01 FIX A: word_similarity availability is ONE shared decision. On a
# word_similarity:false corpus the REST route returns the honest 503-unavailable
# contract; the copilot tool MUST return the SAME unavailable contract instead of
# serving spaCy-vocabulary neighbours the corpus cannot back. REST == copilot.
# ---------------------------------------------------------------------------
def test_similar_words_word_similarity_false_matches_rest_unavailable(monkeypatch) -> None:
    # Reuse the SAME predicate REST gates on (do not duplicate it) — report this
    # corpus has no word-similarity capability, exactly like the frozen bench.
    monkeypatch.setattr(_routes_semantic, "_word_similarity_available", lambda idx: False)
    monkeypatch.setattr(_TW, "_resolve_corpus_index", lambda corpus: object())

    # If the gate did NOT fire, the engine would be consulted and serve neighbours;
    # make that path explode so a regression (gate removed) fails loudly here.
    def _must_not_run(*_a, **_k):
        raise AssertionError("engine consulted despite word_similarity:false")

    monkeypatch.setattr(cql_macros, "similar_words_scored", _must_not_run)

    out = _TW.similar_words_tool("Menschen", k=5, corpus="default")

    # Identical unavailable contract to REST's 503 detail (code/message/backend).
    # A bare index object gives the gate no word vector source, REST answers
    # that with word_vectors.service_error (routes/semantic._word_similarity_error).
    assert out["status"] == "unavailable"
    assert out["code"] == "word_vectors.service_error"
    assert out["neighbours"] == []
    assert "word_similarity" in out["reason"]
    assert out["backend"]  # backend echoed like the REST detail


def test_similar_words_word_similarity_true_still_serves_neighbours(monkeypatch) -> None:
    # The gate must NOT change behaviour for a word_similarity:true corpus: the
    # engine is consulted and corpus-present neighbours flow through as before.
    monkeypatch.setattr(_routes_semantic, "_word_similarity_available", lambda idx: True)
    monkeypatch.setattr(
        _TW, "_resolve_corpus_index", lambda corpus: _FreqOnlyIndex({"present": 7})
    )
    monkeypatch.setattr(
        cql_macros,
        "similar_words_scored",
        lambda *_a, **_k: [{"word": "present", "score": 0.81}],
    )

    out = _TW.similar_words_tool("Menschen", k=5, corpus="default")

    assert out["status"] == "success"
    assert [n["word"] for n in out["neighbours"]] == ["present"]


# ---------------------------------------------------------------------------
# SEM-01 FIX B: each semantic result row carries an honest score 'kind' so the
# renderer never paints a lexical/rerank relevance value as a cosine %. The FAISS
# rows are bounded cosines ("cosine"); the lexical document-search seed rows carry
# a tf/tf-idf/bm25 relevance value ("lexical").
# ---------------------------------------------------------------------------
def test_semantic_rerank_rows_tag_cosine_vs_lexical_kind() -> None:
    rows = [
        # A FAISS row: no score_kind set at source -> normalised to "cosine".
        {"kw": "Der Klimawandel ist real.", "score": 0.91, "doc_id": 1},
        # A lexical document-search seed row already tagged at its source.
        {"kw": "Falsches Getue zum Klimawandel.", "score": 1.0, "doc_id": 2, "score_kind": "lexical"},
    ]

    out = _analysis._semantic_rerank_rows("Klimawandel", rows, top_n=10)

    by_doc = {r["doc_id"]: r for r in out}
    # The cosine row is stamped honestly; the lexical seed keeps its kind.
    assert by_doc[1]["score_kind"] == "cosine"
    assert by_doc[2]["score_kind"] == "lexical"
    # The numeric scores are NOT altered — only the discriminator is added.
    assert by_doc[1]["score"] == 0.91
    assert by_doc[2]["score"] == 1.0
    # Every emitted row carries a kind so the renderer can always label it.
    assert all("score_kind" in r for r in out)
