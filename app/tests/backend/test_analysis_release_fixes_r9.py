"""Regression tests for the r9 analysis-route release fixes.

Each test pins one audited finding (id in the docstring). They drive the
extracted route handlers directly via ``asyncio.run`` and monkeypatch the
shared ``server`` module globals (the handlers reach shared state lazily via
``_server.<attr>``), mirroring tests/backend/test_analysis_runtime_bounds.py.

Findings covered:
  id 5/6  collocates min_freq validated + functional + floor surfaced
  id 6/7  wordsketch min_freq validated + functional + robust re-rank
  id 8     keyness sort validated + actually applied
  id 9     ngrams `n` alias honored
  id 10    wordsketch relation glosses
  id 11/32 wordsketch accepts `word` as well as `term`
  id 15    frequency_list POS filter
  id 2     keyness analyst-token filter + filtered_token_policy
  id 3     dispersion of a non-occurring term -> not_found
  id 0     frequency_list case_policy disclosure
  id 1     lexical_diversity corpus_raw_token_count
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from candyconc.services.backend import server


class _FakeFrame:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    def slice(self, offset: int, length: int):
        return _FakeFrame(self._rows[int(offset) : int(offset) + int(length)])

    def to_dicts(self):
        return list(self._rows)

    def to_dict(self, orient: str):
        assert orient == "records"
        return list(self._rows)


class _FakeLex:
    def get_string(self, wid: int) -> str:
        return {1: "eins", 2: "zwei", 3: "drei"}.get(int(wid), "")


class _NgramIdx:
    """Index stub exposing the lexicon + token totals the ngrams route reads."""

    fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_FakeLex()))

    def token_count(self):
        return 100

    def docset_token_count(self, doc_ids):
        return 100

    def _doc_ranges_for_ids(self, doc_ids):
        # EIN Dokument von 0 bis 100: haelt die Tokenzahl dieses
        # Doubles und liefert zugleich die Dokumentgrenzen, aus denen
        # die n-Gramm-Bezugsgroesse folgt (L - n + 1 je Dokument).
        return (
            np.array([0], dtype=np.uint32),
            np.array([100], dtype=np.uint32),
            100,
        )


# ---------------------------------------------------------------------------
# id 9 — ngrams `n` alias
# ---------------------------------------------------------------------------
def test_ngrams_n_alias_sets_min_max(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _NgramIdx())

    def fake_ngram_counts(idx, doc_ids, min_n, max_n):
        captured["min_n"] = int(min_n)
        captured["max_n"] = int(max_n)
        return {}

    monkeypatch.setattr(server, "_ngram_counts", fake_ngram_counts)

    result = asyncio.run(server.analysis_ngrams({"n": 3, "min_freq": 5, "limit": 10}))
    assert captured == {"min_n": 3, "max_n": 3}
    assert result["method"]["min_n"] == 3
    assert result["method"]["max_n"] == 3
    assert result["method"]["min_freq"] == 5
    assert result["min_freq"] == 5


def test_ngrams_explicit_min_max_win_over_n(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _NgramIdx())

    def fake_ngram_counts(idx, doc_ids, min_n, max_n):
        captured["min_n"] = int(min_n)
        captured["max_n"] = int(max_n)
        return {}

    monkeypatch.setattr(server, "_ngram_counts", fake_ngram_counts)

    asyncio.run(server.analysis_ngrams({"n": 3, "min_n": 2, "max_n": 2, "limit": 10}))
    assert captured == {"min_n": 2, "max_n": 2}


def test_ngrams_non_integer_n_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.analysis_ngrams({"n": "abc"}))
    assert exc.value.status_code == 422


def test_ngrams_min_freq_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.analysis_ngrams({"n": 2, "min_freq": 0}))
    assert exc.value.status_code == 422


def test_ngrams_diff_job_n_alias_sets_min_max(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(server, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(server, "_bounded_analysis_job_limit", lambda value: int(value or 100))
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_resolve_doc_ids_for_job",
        lambda idx, corpus, docset_id: np.array([1, 2], dtype=np.uint32),
    )

    class _Jobs:
        def create(self, kind, corpus, params):
            captured["kind"] = kind
            captured["corpus"] = corpus
            captured["params"] = params
            return SimpleNamespace(job_id="job-ngram-diff")

        def attach_task(self, job_id, task):
            captured["attached"] = job_id
            task.cancel()

    def _noop_ngrams_diff_job(job_id, **kwargs):
        captured["runner_job_id"] = job_id
        captured["runner_kwargs"] = kwargs

        async def _done():
            return None

        return _done()

    monkeypatch.setattr(server, "analysis_jobs", _Jobs())
    monkeypatch.setattr(server, "_run_ngrams_diff_job", _noop_ngrams_diff_job)

    result = asyncio.run(
        server.analysis_ngrams_diff_job(
            {
                "target_docset_id": "target",
                "reference_docset_id": "ref",
                "n": 3,
                "min_freq": 7,
                "limit": 25,
            }
        )
    )

    assert result["job_id"] == "job-ngram-diff"
    assert captured["kind"] == "ngrams_diff"
    assert captured["params"]["min_n"] == 3
    assert captured["params"]["max_n"] == 3
    assert captured["params"]["min_freq"] == 7
    assert captured["runner_kwargs"]["min_freq"] == 7


def test_ngrams_diff_applies_min_freq_before_bounded_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    """A contrast floor must not be applied after a partial top-N result."""

    class _DiffIdx:
        fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_FakeLex()))

        def docset_token_count(self, doc_ids):
            return 100 if int(np.asarray(doc_ids)[0]) == 0 else 10_000

        def _doc_ranges_for_ids(self, doc_ids):
            # Je EIN Dokument, so lang wie die Tokenzahl dieser Seite. Damit
            # bleibt die Absicht des Tests erhalten (Ziel klein, Referenz
            # gross) und die n-Gramm-Bezugsgroesse folgt aus den Grenzen.
            umfang = 100 if int(np.asarray(doc_ids)[0]) == 0 else 10_000
            return (
                np.array([0], dtype=np.uint32),
                np.array([umfang], dtype=np.uint32),
                umfang,
            )

    idx = _DiffIdx()
    monkeypatch.setattr(server, "get_corpus", lambda corpus: idx)

    def fake_counts(_idx, doc_ids, _min_n, _max_n):
        # Below the floor, ``eins eins`` has the largest raw normalized delta.
        # Once min_freq=5 is honoured before top-1 selection, only ``zwei zwei``
        # is an eligible contrast candidate.
        if int(np.asarray(doc_ids)[0]) == 0:
            return {(1, 1): 4}
        return {(2, 2): 5}

    monkeypatch.setattr(server, "_ngram_counts", fake_counts)
    server.analysis_jobs._JOBS.clear()
    job = server.analysis_jobs.create("ngrams_diff", "default", {})

    asyncio.run(
        server._run_ngrams_diff_job(
            job.job_id,
            corpus=None,
            target_doc_ids=np.array([0], dtype=np.uint32),
            reference_doc_ids=np.array([1], dtype=np.uint32),
            min_n=2,
            max_n=2,
            min_freq=5,
            limit=1,
        )
    )

    result = server.analysis_jobs.get(job.job_id).result
    assert result is not None
    assert result["total_candidates"] == 1
    # Der Nenner ist die Zahl der BIGRAMM-Stellen, nicht die Tokenzahl.
    # Die Referenzseite ist EIN Dokument von 10.000 Tokens und traegt damit
    # 10.000 - 1 = 9.999 Bigrammstellen. Von Hand: 5 * 10^6 / 9.999 =
    # 500,0500050005. Vorher stand hier 500,0, gerechnet auf 10.000 Tokens.
    # Die Absicht des Tests ist unberuehrt: min_freq greift vor der
    # Rangbildung, eligibel ist allein "zwei zwei".
    stellen_referenz = 10_000 - 1
    erwartet = 5 * 1_000_000.0 / stellen_referenz
    assert result["rows"] == [
        {
            "ngram": "zwei zwei",
            "n": 2,
            "target_freq": 0,
            "reference_freq": 5,
            "target_per_million": 0.0,
            "reference_per_million": erwartet,
            "diff_per_million": -erwartet,
            "diff_abs": erwartet,
        }
    ]
    assert result["method"]["min_freq"] == 5


def test_frequency_diff_ranks_the_complete_union_not_two_top_frequency_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A low raw-frequency word can be the largest normalized difference.

    ``eins`` is the top raw frequency on both sides and therefore would be the
    only row in two separately limited ``frequency_list`` responses. ``zwei``
    is outside both top-1 pages but has the largest absolute per-million
    difference. The job must return it from the full vocabulary union.
    """

    class _FrequencyDiffIdx:
        fast_index = SimpleNamespace(
            lexicons=SimpleNamespace(
                word=SimpleNamespace(offsets=object(), strings_view=object())
            )
        )

        def frequency_counts_docset(self, doc_ids, **_kwargs):
            if int(np.asarray(doc_ids)[0]) == 0:
                return (
                    np.array([1, 2, 3], dtype=np.uint32),
                    np.array([90, 1, 1], dtype=np.uint64),
                )
            return (
                np.array([1, 3], dtype=np.uint32),
                np.array([900_000, 10_000], dtype=np.uint64),
            )

        def docset_token_count(self, doc_ids):
            return 100 if int(np.asarray(doc_ids)[0]) == 0 else 1_000_000

    idx = _FrequencyDiffIdx()
    words = {1: "eins", 2: "zwei", 3: "drei"}
    monkeypatch.setattr(server, "get_corpus", lambda _corpus: idx)
    monkeypatch.setattr(
        server,
        "_analyst_token_mask_for_term_ids",
        lambda _idx, ids: np.ones(np.asarray(ids).size, dtype=np.bool_),
    )
    monkeypatch.setattr(
        server,
        "strings_for_ids",
        lambda _offsets, _strings, ids, _copy: [words[int(i)] for i in ids],
    )
    monkeypatch.setattr(server, "_corpus_cache_signature", lambda *_args: "fixture")

    server.analysis_jobs._JOBS.clear()
    job = server.analysis_jobs.create("frequency_diff", "default", {})
    asyncio.run(
        server._run_frequency_diff_job(
            job.job_id,
            corpus=None,
            target_doc_ids=np.array([0], dtype=np.uint32),
            reference_doc_ids=np.array([1], dtype=np.uint32),
            min_freq=1,
            limit=1,
        )
    )

    result = server.analysis_jobs.get(job.job_id).result
    assert result is not None
    assert result["total_candidates"] == 3
    assert result["truncated"] is True
    assert result["rows"] == [
        {
            "word": "zwei",
            "target_freq": 1,
            "reference_freq": 0,
            "target_per_million": 10_000.0,
            "reference_per_million": 0.0,
            "diff_per_million": 10_000.0,
            "diff_abs": 10_000.0,
        }
    ]
    assert result["method"]["family"] == "frequency_diff"
    assert result["method"]["candidate_policy"] == "complete_union_before_ranking"


# ---------------------------------------------------------------------------
# id 5/6 — collocates min_freq validated + functional + floor surfaced
# ---------------------------------------------------------------------------
def test_collocates_min_freq_filters_rows_and_surfaces_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)

    class _Idx:
        def token_count(self):
            return 1000

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Idx())

    frame = pd.DataFrame(
        {
            "word": ["a", "b", "c"],
            "f": [3, 7, 12],
            "logdice": [5.0, 7.0, 9.0],
            "rank": [1, 2, 3],
        }
    )
    monkeypatch.setattr(server, "_collocate_stats_for_term", lambda *a, **k: frame)

    result = asyncio.run(server.analysis_collocates(term="x", min_freq=7))
    words = [r["word"] for r in result["rows"]]
    assert words == ["c", "b"]  # f=3 dropped; default ranking still applies
    assert result["total_candidates"] == 2
    # id 5: the hidden floor and the effective min are surfaced in method.
    assert result["method"]["cooccurrence_floor"] == 5
    assert result["method"]["min_freq"] == 7
    assert result["method"]["effective_min_cooccurrence"] == 7


def test_collocates_min_freq_negative_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.analysis_collocates(term="x", min_freq=-1))
    assert exc.value.status_code == 422


def test_collocates_default_surfaces_hidden_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)

    class _Idx:
        def token_count(self):
            return 1000

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Idx())
    frame = pd.DataFrame({"word": ["a"], "f": [9], "logdice": [5.0], "rank": [1]})
    monkeypatch.setattr(server, "_collocate_stats_for_term", lambda *a, **k: frame)

    result = asyncio.run(server.analysis_collocates(term="x"))
    # No min_freq -> no extra filtering, but the floor is documented.
    assert result["method"]["cooccurrence_floor"] == 5
    assert result["method"]["min_freq"] == 0
    assert [r["word"] for r in result["rows"]] == ["a"]


def test_collocates_job_matches_sync_candidate_policy_and_min_freq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)

    class _Idx:
        def token_count(self):
            return 1000

        def docset_token_count(self, doc_ids):
            return 1000

        def _doc_ranges_for_ids(self, doc_ids):
            # EIN Dokument von 0 bis 1000: haelt die Tokenzahl dieses
            # Doubles und liefert zugleich die Dokumentgrenzen, aus denen
            # die n-Gramm-Bezugsgroesse folgt (L - n + 1 je Dokument).
            return (
                np.array([0], dtype=np.uint32),
                np.array([1000], dtype=np.uint32),
                1000,
            )

    frame = pd.DataFrame({
        "word": [":", "niedrig", "Hase"],
        "f": [99, 3, 7],
        "dice": [0.9, 0.8, 0.4],
        "rank": [1, 2, 3],
    })
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Idx())
    monkeypatch.setattr(server, "_collocate_stats_for_term", lambda *a, **k: frame)

    sync_result = asyncio.run(server.analysis_collocates(term="x", sort_by="dice", min_freq=7))
    assert [row["word"] for row in sync_result["rows"]] == ["Hase"]
    assert sync_result["total_candidates"] == 1

    server.analysis_jobs._JOBS.clear()
    job = server.analysis_jobs.create("collocates", "default", {})

    asyncio.run(
        server._run_collocates_job(
            job.job_id,
            corpus=None,
            term="x",
            collocate=None,
            window=5,
            within_sentence=True,
            sort_by="dice",
            doc_ids=np.array([0], dtype=np.uint32),
            limit=10,
            min_freq=7,
        )
    )

    result = server.analysis_jobs.get(job.job_id).result
    assert result is not None
    assert [row["word"] for row in result["rows"]] == ["Hase"]
    assert result["total_candidates"] == 1
    assert result["method"]["cooccurrence_floor"] == 5
    assert result["method"]["min_freq"] == 7
    assert result["method"]["effective_min_cooccurrence"] == 7


def test_frequency_job_filters_analyst_tokens_before_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Idx:
        fast_index = SimpleNamespace(
            lexicons=SimpleNamespace(word=SimpleNamespace(offsets=None, strings_view=None))
        )

        def frequency_counts_docset(self, doc_ids, *, stopwords=None, pos_prefix=None, case_fold=True):
            return (
                np.array([1, 2, 3, 4], dtype=np.uint32),
                np.array([50, 40, 30, 20], dtype=np.uint64),
            )

    idx = _Idx()
    words_by_id = {1: ":", 2: "|LBR|", 3: "Hase", 4: "läuft"}
    monkeypatch.setattr(server, "get_corpus", lambda corpus: idx)
    monkeypatch.setattr(
        server,
        "strings_for_ids",
        lambda _o, _v, ids, _d: [words_by_id[int(term_id)] for term_id in ids],
    )
    server.analysis_jobs._JOBS.clear()
    job = server.analysis_jobs.create("frequency_list", "default", {})

    asyncio.run(
        server._run_frequency_job(
            job.job_id,
            corpus=None,
            doc_ids=np.array([0], dtype=np.uint32),
            stopwords=None,
            pos_prefix=None,
            limit=2,
        )
    )

    result = server.analysis_jobs.get(job.job_id).result
    assert result is not None
    assert result["total_candidates"] == 2
    rows = server._frequency_rows_from_result(idx, result, offset=0, limit=10)
    assert rows == [{"word": "Hase", "f": 30}, {"word": "läuft", "f": 20}]


# ---------------------------------------------------------------------------
# id 6/7 + 10 + 11/32 — wordsketch
# ---------------------------------------------------------------------------
def _ws_index(monkeypatch: pytest.MonkeyPatch, tables: dict) -> None:
    from candyconc.services.backend.routes import analysis as analysis_routes

    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 20)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 20)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    # The glosses follow the annotation scheme of the corpus. The stand-in
    # corpus has no index directory, so it is declared a German spaCy (TIGER)
    # corpus here, which the relation codes below belong to.
    monkeypatch.setattr(analysis_routes, "_label_scheme", lambda idx: "tiger")
    monkeypatch.setattr(
        server, "_word_sketch_for_query", lambda idx, term, **kwargs: tables
    )


def test_wordsketch_accepts_word_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    _ws_index(
        monkeypatch,
        {"sb_rev": _FakeFrame([{"word": "Mensch", "f": 5, "ll_signed": 3.0}])},
    )
    result = asyncio.run(server.word_sketch_endpoint({"word": "Mensch"}))
    assert "sb_rev" in result["sketches"]


def test_wordsketch_missing_term_and_word_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.word_sketch_endpoint({}))
    assert exc.value.status_code == 422


def test_wordsketch_default_floor_drops_hapaxes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default min_freq is 3: f=1 hapaxes must be removed even with a high chi2.
    _ws_index(
        monkeypatch,
        {
            "sb_rev": _FakeFrame(
                [
                    {"word": "weis", "f": 1, "chi2_cell": 6241.4, "ll_signed": 17.0},
                    {"word": "regt", "f": 4, "chi2_cell": 50.0, "ll_signed": 40.0},
                ]
            )
        },
    )
    result = asyncio.run(server.word_sketch_endpoint({"term": "Mensch"}))
    rows = result["sketches"]["sb_rev"]
    assert [r["word"] for r in rows] == ["regt"]  # hapax 'weis' dropped


def test_wordsketch_min_freq_zero_keeps_all_but_reranks(monkeypatch: pytest.MonkeyPatch) -> None:
    # min_freq=0 keeps hapaxes, but ranking is by ll_signed (robust), NOT the
    # inflated chi2_cell, so the higher-ll row leads.
    _ws_index(
        monkeypatch,
        {
            "sb_rev": _FakeFrame(
                [
                    {"word": "hapax", "f": 1, "chi2_cell": 9999.0, "ll_signed": 2.0},
                    {"word": "real", "f": 8, "chi2_cell": 10.0, "ll_signed": 80.0},
                ]
            )
        },
    )
    result = asyncio.run(server.word_sketch_endpoint({"term": "Mensch", "min_freq": 0}))
    rows = result["sketches"]["sb_rev"]
    assert [r["word"] for r in rows] == ["real", "hapax"]
    assert rows[0]["rank"] == 1


def test_wordsketch_min_freq_non_integer_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.word_sketch_endpoint({"term": "x", "min_freq": "nope"}))
    assert exc.value.status_code == 422


def test_wordsketch_attaches_relation_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    _ws_index(
        monkeypatch,
        {
            "sb_rev": _FakeFrame([{"word": "x", "f": 5, "ll_signed": 3.0}]),
            "nk": _FakeFrame([{"word": "y", "f": 5, "ll_signed": 3.0}]),
        },
    )
    result = asyncio.run(server.word_sketch_endpoint({"term": "Merkel"}))
    relations = result["relations"]
    assert relations["sb_rev"]["label"] == "Subjekt von"
    assert "Nomen-Kern" in relations["nk"]["label"]


def test_wordsketch_relation_meta_reports_display_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    _ws_index(
        monkeypatch,
        {
            "sb_rev": _FakeFrame(
                [
                    {"word": "a", "f": 9, "ll_signed": 90.0},
                    {"word": "b", "f": 8, "ll_signed": 80.0},
                    {"word": "c", "f": 7, "ll_signed": 70.0},
                ]
            )
        },
    )
    result = asyncio.run(server.word_sketch_endpoint({"term": "Mensch", "limit": 2}))

    assert [row["word"] for row in result["sketches"]["sb_rev"]] == ["a", "b"]
    assert result["relations"]["sb_rev"] == {
        "relation": "sb_rev",
        "label": "Subjekt von",
        "row_limit": 2,
        "total_candidates": 3,
        "total_rows": 2,
        "truncated": True,
        "min_freq": 3,
    }


# ---------------------------------------------------------------------------
# id 8 + 2 — keyness sort validation/application + analyst-token filter
# ---------------------------------------------------------------------------
def test_keyness_unknown_sort_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            server.analysis_keyness(
                {"target": ["a"], "reference": ["b"], "sort": "bogus"}
            )
        )
    assert exc.value.status_code == 422


def test_keyness_corpus_compare_honors_sort_and_filters_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)

    class _Corpus:
        def __init__(self, rows, total):
            self._rows = rows
            self._total = total

        def frequency_list(self, *, stopwords=None):
            return _FakeFrame(self._rows)

        def token_count(self):
            return self._total

    # "\n" and ":" are non-analyst tokens that must be filtered out.
    corpora = {
        "t": _Corpus(
            [
                {"word": "\n", "f": 900},
                {"word": "alpha", "f": 10},
                {"word": "beta", "f": 30},
            ],
            1000,
        ),
        "r": _Corpus([{"word": "gamma", "f": 5}], 1000),
    }
    monkeypatch.setattr(server, "get_corpus", lambda name: corpora[str(name)])
    monkeypatch.setattr(server, "_doc_count_for_index", lambda _idx: 1)
    population_pos: list[str | None] = []

    async def _fake_population(_server, idx, _doc_ids, *, pos):
        population_pos.append(pos)
        total = 40 if idx is corpora["t"] else 30
        return ({str(row["word"]): int(row["f"]) for row in idx._rows}, total)

    from candyconc.services.backend.routes import analysis as analysis_routes

    monkeypatch.setattr(analysis_routes, "_keyness_docset_population", _fake_population)

    captured: dict[str, dict] = {}

    def fake_counts(freq_t, freq_r, total_t, total_r, *, min_freq=0):
        captured["freq_t"] = dict(freq_t)
        captured["totals"] = (total_t, total_r)
        # Emit rows with both ll_signed and log_ratio so sort can be checked.
        return _FakeFrame(
            [
                {"word": "alpha", "ll_signed": 100.0, "log_ratio": 1.0},
                {"word": "beta", "ll_signed": 5.0, "log_ratio": 9.0},
            ]
        )

    monkeypatch.setattr(server, "_compute_keyness_counts", fake_counts)

    result = asyncio.run(
        server.analysis_keyness(
            {
                "target_corpus": "t",
                "reference_corpus": "r",
                "pos": "NOUN",
                "sort": "log_ratio",
                "min_freq": 0,
            }
        )
    )
    # id 2: newline filtered out before scoring.
    assert "\n" not in captured["freq_t"]
    assert population_pos == ["NOUN", "NOUN"]
    # Seit dem 2026-09-01 ist der Nenner der GEFILTERTE Bestand, denn der
    # Zaehler ist es auch. Die Referenz traegt hier 25 Zeilenumbrueche, die
    # zwei Zeilen darueber nachweislich aus freq_t fallen. Vorher stand
    # dort 30, also der Bestand VOR dem Filter, und damit rechnete die
    # Statistik einen Zaehler gegen einen fremden Nenner.
    assert captured["totals"] == (40, 5)
    assert "filtered_token_policy" in result
    # id 8: rows re-ordered by log_ratio descending (beta=9 leads alpha=1).
    assert [r["word"] for r in result["rows"]] == ["beta", "alpha"]
    assert result["method"]["default_sort"] == "log_ratio"


# ---------------------------------------------------------------------------
# id 15 + 0 — frequency_list POS filter + case_policy disclosure
# ---------------------------------------------------------------------------
def test_frequency_list_pos_filter_routes_through_pos_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)
    captured: dict[str, object] = {}

    class _Idx:
        def frequency_list_docset(self, doc_ids, *, stopwords=None, pos_prefix=None, attr="word"):
            captured["pos_prefix"] = pos_prefix
            captured["attr"] = attr
            captured["n_docs"] = int(np.asarray(doc_ids).size)
            return pd.DataFrame([{"word": ":", "f": 99}, {"word": "Politik", "f": 9}, {"word": "Haus", "f": 7}])

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Idx())
    monkeypatch.setattr(
        server, "_resolve_doc_ids_for_job", lambda idx, corpus, docset_id: np.arange(12, dtype=np.uint32)
    )

    result = asyncio.run(server.analysis_frequency_list(group_by="word", pos="NOUN"))
    assert captured["pos_prefix"] == "NOUN"
    assert captured["attr"] == "word"
    assert captured["n_docs"] == 12
    assert result["basis"] == "pos_filtered_word_frequency"
    assert result["pos"] == "NOUN"
    assert [r["word"] for r in result["rows"]] == ["Politik", "Haus"]


def test_frequency_list_pos_filter_supports_lemma_group_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Idx:
        def frequency_list_docset(
            self, doc_ids, *, stopwords=None, pos_prefix=None, attr="word"
        ):
            captured.update(pos_prefix=pos_prefix, attr=attr)
            return pd.DataFrame([{"word": "Mensch", "f": 9}])

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Idx())
    monkeypatch.setattr(
        server,
        "_resolve_doc_ids_for_job",
        lambda idx, corpus, docset_id: np.arange(2, dtype=np.uint32),
    )

    result = asyncio.run(
        server.analysis_frequency_list(group_by="lemma", pos="NOUN")
    )
    assert captured == {"pos_prefix": "NOUN", "attr": "lemma"}
    assert result["basis"] == "pos_filtered_lemma_frequency"
    assert result["rows"] == [{"word": "Mensch", "f": 9}]


def test_frequency_list_pos_rejects_pos_group_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.analysis_frequency_list(group_by="pos", pos="NOUN"))
    assert exc.value.status_code == 422


def test_frequency_list_rejects_cql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.analysis_frequency_list(group_by="word", cql='[pos="NOUN"]'))
    assert exc.value.status_code == 422


def test_frequency_list_discloses_case_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server, "_frequency_list", lambda **kw: _FakeFrame([{"word": "der", "f": 3448}])
    )

    word_res = asyncio.run(server.analysis_frequency_list(group_by="word"))
    lemma_res = asyncio.run(server.analysis_frequency_list(group_by="lemma"))
    # Lowercasing preserves sharp s and ss as distinct values, unlike
    # str.casefold.
    assert word_res["case_policy"] == "case_insensitive (lowercase)"
    assert lemma_res["case_policy"] == "case_insensitive (lowercase)"
    pos_res = asyncio.run(server.analysis_frequency_list(group_by="pos"))
    assert "case_policy" not in pos_res  # pos counts are not case-folded


# ---------------------------------------------------------------------------
# id 3 — dispersion of a non-occurring term
# ---------------------------------------------------------------------------
def test_dispersion_not_found_for_absent_term(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Index:
        def token_count(self) -> int:
            return 100

    doc_bounds = np.array([0, 50], dtype=np.uint32)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Index())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: doc_bounds)
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *a, **k: np.zeros(0, dtype=np.uint32),
    )

    result = asyncio.run(server.analysis_dispersion(term="xyzzyword123"))
    assert result["classification"] == "not_found"
    assert result["observed_frequency"] == 0
    codes = {lim["code"] for lim in result["limitations"]}
    assert "dispersion_term_not_found" in codes


def test_dispersion_present_term_not_flagged_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Index:
        def token_count(self) -> int:
            return 100

    doc_bounds = np.array([0, 50], dtype=np.uint32)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Index())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: doc_bounds)
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *a, **k: np.array([0, 50, 99], dtype=np.uint32),
    )

    result = asyncio.run(server.analysis_dispersion(term="Leute"))
    assert result["classification"] != "not_found"
    assert result["observed_frequency"] == 3
