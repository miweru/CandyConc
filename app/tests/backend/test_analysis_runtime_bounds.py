from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from candyconc.services.backend import analysis_jobs, server


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
        return {
            1: "eins",
            2: "zwei",
            3: "drei",
            4: "vier",
            5: "fuenf",
            6: "sechs",
            7: "sieben",
            8: "acht",
        }.get(int(wid), "")


class _FakeIndex:
    fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_FakeLex()))

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


@pytest.fixture(autouse=True)
def _isolated_analysis_jobs():
    analysis_jobs._JOBS.clear()
    yield
    analysis_jobs._JOBS.clear()


def test_analysis_frequency_list_defaults_to_bounded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_frequency_list",
        lambda **kwargs: _FakeFrame([{"word": f"w{i}", "f": i} for i in range(5)]),
    )

    result = asyncio.run(server.analysis_frequency_list())

    assert result["rows"] == [{"word": "w0", "f": 0}, {"word": "w1", "f": 1}]
    assert result["row_limit"] == 2
    assert result["total_candidates"] == 5
    assert result["truncated"] is True


def test_analysis_frequency_list_passes_group_by_and_marks_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())

    def fake_frequency_list(**kwargs):
        captured.update(kwargs)
        return _FakeFrame([{"word": "gehen", "f": 7}])

    monkeypatch.setattr(server, "_frequency_list", fake_frequency_list)

    result = asyncio.run(server.analysis_frequency_list(group_by="lemma", limit=10))

    assert captured["group_by"] == "lemma"
    assert result["group_by"] == "lemma"
    assert result["basis"] == "analyst_token_frequency"
    assert result["filtered_token_policy"]
    assert result["rows"] == [{"word": "gehen", "f": 7}]


def test_frequency_top_n_resolves_boundary_ties_by_canonical_term_id() -> None:
    """A saved top-N must not change when an equal-count boundary is replayed."""
    term_ids = np.asarray([9, 2, 3, 4], dtype=np.uint32)
    counts = np.asarray([7, 9, 9, 9], dtype=np.uint64)

    selected_ids, selected_counts, total, truncated = server._top_count_arrays(
        term_ids,
        counts,
        limit=2,
    )

    assert selected_ids.tolist() == [2, 3]
    assert selected_counts.tolist() == [9, 9]
    assert total == 4
    assert truncated is True


def test_analysis_ngrams_caps_large_requested_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 1)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 2)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (1, 2): 4,
            (3, 4): 9,
            (5, 6): 2,
        },
    )

    result = asyncio.run(server.analysis_ngrams({"min_n": 2, "max_n": 2, "limit": 999}))

    assert len(result["rows"]) == 2
    assert [row["freq"] for row in result["rows"]] == [9, 4]
    assert result["row_limit"] == 2
    assert result["total_candidates"] == 3
    assert result["truncated"] is True


def test_analysis_ngrams_resolves_equal_frequency_boundary_by_token_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 2)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    # Deliberately insert the largest IDs first: dict/set iteration is not an
    # acceptable scientific tie-break for a bounded, saved analysis.
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (7, 8): 5,
            (1, 2): 5,
            (3, 4): 5,
        },
    )

    result = asyncio.run(server.analysis_ngrams({"min_n": 2, "max_n": 2, "limit": 2}))

    assert [row["ngram"] for row in result["rows"]] == ["eins zwei", "drei vier"]
    assert result["method"]["tie_break"] == "token_id_ascending"


def test_analysis_ngrams_excludes_non_analyst_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync n-gram list applies frequency_list's analyst-token policy.

    Punctuation ("! !"), |LBR|/line-break markers and emoji pairs must never
    headline the n-gram ranking: an n-gram is kept only when EVERY constituent
    token is an analyst token (alnum, non-marker). Real word bigrams survive.
    """
    # ids: 1/2 = real words; 10 = "!", 11 = "|LBR|", 12 = emoji.
    strings = {1: "im", 2: "Jahr", 10: "!", 11: "|LBR|", 12: "\U0001f600"}

    class _MixedLex:
        def get_string(self, wid: int) -> str:
            return strings.get(int(wid), "")

    class _MixedIndex:
        fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_MixedLex()))

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

        def token_count(self):
            return 100

    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 50)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 50)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _MixedIndex())
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (1, 2): 340,    # "im Jahr"   -> kept
            (10, 10): 999,  # "! !"       -> dropped (punctuation)
            (11, 1): 500,   # "|LBR| im"  -> dropped (line-break marker)
            (12, 12): 700,  # emoji pair  -> dropped (no alnum)
        },
    )

    # The junk n-grams carry HIGHER raw frequency than the real bigram, so a
    # filter that ran only on the top-N (rather than the whole candidate set)
    # would let them crowd out "im Jahr" at small limits. Pin limit=1 to lock
    # in filter-before-limit, matching frequency_list's filter-then-paginate.
    result = asyncio.run(server.analysis_ngrams({"min_n": 2, "max_n": 2, "limit": 1}))

    ngrams = [row["ngram"] for row in result["rows"]]
    assert ngrams == ["im Jahr"]
    assert all("!" not in ng and "|LBR|" not in ng and "\U0001f600" not in ng for ng in ngrams)
    # total_candidates describes the analyst-token basis (1 kept), not the 4 raw
    # candidates, mirroring frequency_list's filtered total.
    assert result["total_candidates"] == 1


def test_analysis_ngrams_http_keeps_bound_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 1)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 2)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (1, 2): 4,
            (3, 4): 9,
            (5, 6): 2,
        },
    )

    response = TestClient(server.app).post(
        "/api/v1/analysis/ngrams",
        json={"min_n": 2, "max_n": 2, "limit": 999},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 2
    assert payload["row_limit"] == 2
    assert payload["total_candidates"] == 3
    assert payload["truncated"] is True


def test_analysis_collocates_defaults_to_bounded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_collocate_stats_for_term",
        lambda *args, **kwargs: _FakeFrame([{"word": f"c{i}", "chi2_cell": float(i)} for i in range(5)]),
    )

    result = asyncio.run(server.analysis_collocates(term="politik"))

    assert result["rows"] == [{"word": "c0", "chi2_cell": 0.0}, {"word": "c1", "chi2_cell": 1.0}]
    assert result["row_limit"] == 2
    assert result["total_candidates"] == 5
    assert result["truncated"] is True


def test_ngrams_job_stores_top_n_instead_of_full_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (1, 2): 4,
            (3, 4): 9,
            (5, 6): 2,
        },
    )
    job = analysis_jobs.create("ngrams", "default", {})

    asyncio.run(
        server._run_ngrams_job(
            job.job_id,
            corpus=None,
            doc_ids=np.array([0], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=2,
        )
    )

    stored = analysis_jobs.get(job.job_id)
    assert stored.status == "done"
    assert stored.total_rows == 2
    assert stored.result is not None
    assert [row["freq"] for row in stored.result["rows"]] == [9, 4]
    assert stored.result["total_candidates"] == 3
    assert stored.result["row_limit"] == 2
    assert stored.result["truncated"] is True


def test_ngrams_job_resolves_equal_frequency_boundary_by_token_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (7, 8): 5,
            (1, 2): 5,
            (3, 4): 5,
        },
    )
    job = analysis_jobs.create("ngrams", "default", {})

    asyncio.run(
        server._run_ngrams_job(
            job.job_id,
            corpus=None,
            doc_ids=np.array([0], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=2,
        )
    )

    result = analysis_jobs.get(job.job_id).result
    assert result is not None
    assert [row["ngram"] for row in result["rows"]] == ["eins zwei", "drei vier"]
    assert result["method"]["tie_break"] == "token_id_ascending"


def test_ngrams_job_filters_non_analyst_tokens_like_sync_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The background job must apply the same analyst-token policy as the sync
    route: punctuation, |LBR|/marker tokens and emoji never headline the ranking,
    even when they out-count the genuine top n-gram (regression for AFU-1)."""

    class _MixedLex:
        # 1='!', 2='.', 3='|LBR|', 4='😂', 5='in', 6='der' — only 5/6 are analyst tokens.
        def get_string(self, wid: int) -> str:
            return {1: "!", 2: ".", 3: "|LBR|", 4: "😂", 5: "in", 6: "der"}.get(int(wid), "")

    class _MixedIndex:
        fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_MixedLex()))

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

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _MixedIndex())
    # The genuine analyst bigram 'in der' (123) is out-counted by punctuation /
    # marker / emoji bigrams that the raw heap would rank above it.
    monkeypatch.setattr(
        server,
        "_ngram_counts",
        lambda idx, doc_ids, min_n, max_n: {
            (1, 1): 272,  # '! !'
            (2, 3): 195,  # '. |LBR|'
            (4, 4): 69,  # '😂 😂'
            (5, 6): 123,  # 'in der' — the only analyst n-gram
        },
    )
    job = analysis_jobs.create("ngrams", "default", {})

    asyncio.run(
        server._run_ngrams_job(
            job.job_id,
            corpus=None,
            doc_ids=np.array([0], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=10,
        )
    )

    stored = analysis_jobs.get(job.job_id)
    assert stored.status == "done"
    assert stored.result is not None
    rows = stored.result["rows"]
    # Only the analyst bigram survives; the raw top-3 (! !, . |LBR|, 😂 😂) are gone.
    assert [row["ngram"] for row in rows] == ["in der"]
    assert rows[0]["freq"] == 123
    # total_candidates describes the filtered (analyst) basis, not the 4 raw n-grams.
    assert stored.result["total_candidates"] == 1


def test_ngrams_diff_job_filters_non_analyst_tokens_like_sync_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The n-gram diff job must apply the same analyst-token policy as the sync
    route: punctuation, |LBR|/marker tokens and emoji never headline the
    contrast ranking, even when their |diff_per_million| out-ranks the genuine
    top n-gram (regression for AFU-2)."""

    class _MixedLex:
        # 1='!', 2='.', 3='|LBR|', 4='😂', 5='in', 6='der' — only 5/6 are analyst tokens.
        def get_string(self, wid: int) -> str:
            return {1: "!", 2: ".", 3: "|LBR|", 4: "😂", 5: "in", 6: "der"}.get(int(wid), "")

    class _MixedIndex:
        fast_index = SimpleNamespace(lexicons=SimpleNamespace(word=_MixedLex()))

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

    monkeypatch.setattr(server, "get_corpus", lambda corpus: _MixedIndex())

    # Target (doc id 1) is dominated by punctuation / marker / emoji bigrams; the
    # only analyst bigram 'in der' (123) has a smaller per-million delta than the
    # raw '! !', '. |LBR|' and '😂 😂' contrasts that the unfiltered heap would
    # rank above it.
    def fake_ngram_counts(idx, doc_ids, min_n, max_n):
        if int(np.asarray(doc_ids)[0]) == 1:
            return {
                (1, 1): 272,  # '! !'
                (2, 3): 195,  # '. |LBR|'
                (4, 4): 69,  # '😂 😂'
                (5, 6): 123,  # 'in der' — the only analyst n-gram
            }
        return {(5, 6): 1}  # reference: 'in der' barely present

    monkeypatch.setattr(server, "_ngram_counts", fake_ngram_counts)
    job = analysis_jobs.create("ngrams_diff", "default", {})

    asyncio.run(
        server._run_ngrams_diff_job(
            job.job_id,
            corpus=None,
            target_doc_ids=np.array([1], dtype=np.uint32),
            reference_doc_ids=np.array([2], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=10,
        )
    )

    stored = analysis_jobs.get(job.job_id)
    assert stored.status == "done"
    assert stored.result is not None
    rows = stored.result["rows"]
    # Only the analyst bigram survives; the raw top-3 (! !, . |LBR|, 😂 😂) are gone.
    assert [row["ngram"] for row in rows] == ["in der"]
    assert not any(
        ("!" in row["ngram"] or "|LBR|" in row["ngram"] or "😂" in row["ngram"])
        for row in rows
    )
    # total_candidates describes the filtered (analyst) basis, not the 4 raw n-grams.
    assert stored.result["total_candidates"] == 1


def test_ngrams_diff_job_stores_top_n_bound_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())

    def fake_ngram_counts(idx, doc_ids, min_n, max_n):
        if int(np.asarray(doc_ids)[0]) == 1:
            return {
                (1, 2): 10,
                (3, 4): 5,
                (5, 6): 1,
            }
        return {
            (1, 2): 1,
            (3, 4): 8,
            (7, 8): 2,
        }

    monkeypatch.setattr(server, "_ngram_counts", fake_ngram_counts)
    job = analysis_jobs.create("ngrams_diff", "default", {})

    asyncio.run(
        server._run_ngrams_diff_job(
            job.job_id,
            corpus=None,
            target_doc_ids=np.array([1], dtype=np.uint32),
            reference_doc_ids=np.array([2], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=2,
        )
    )

    stored = analysis_jobs.get(job.job_id)
    assert stored.status == "done"
    assert stored.result is not None
    assert len(stored.result["rows"]) == 2
    assert stored.result["total_candidates"] == 4
    assert stored.result["row_limit"] == 2
    assert stored.result["truncated"] is True


def test_ngrams_diff_job_resolves_equal_difference_boundary_by_token_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _FakeIndex())

    def fake_ngram_counts(idx, doc_ids, min_n, max_n):
        if int(np.asarray(doc_ids)[0]) == 1:
            return {
                (7, 8): 5,
                (1, 2): 5,
                (3, 4): 5,
            }
        return {}

    monkeypatch.setattr(server, "_ngram_counts", fake_ngram_counts)
    job = analysis_jobs.create("ngrams_diff", "default", {})

    asyncio.run(
        server._run_ngrams_diff_job(
            job.job_id,
            corpus=None,
            target_doc_ids=np.array([1], dtype=np.uint32),
            reference_doc_ids=np.array([2], dtype=np.uint32),
            min_n=2,
            max_n=2,
            limit=2,
        )
    )

    result = analysis_jobs.get(job.job_id).result
    assert result is not None
    assert [row["ngram"] for row in result["rows"]] == ["eins zwei", "drei vier"]
    assert result["method"]["tie_break"] == "token_id_ascending"


def test_collocates_diff_job_stores_top_n_bound_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())

    def fake_diff_rows_for_term(*args, **kwargs):
        rows = [
            {"word": "alpha", "diff_abs": 3.0},
            {"word": "beta", "diff_abs": 2.0},
        ]
        meta = server._bounded_result_meta(
            row_limit=kwargs["limit"],
            total_candidates=5,
        )
        if kwargs.get("return_meta"):
            return rows, meta
        return rows

    monkeypatch.setattr(server, "_collocates_diff_rows_for_term", fake_diff_rows_for_term)
    job = analysis_jobs.create("collocates_diff", "default", {})

    asyncio.run(
        server._run_collocates_diff_job(
            job.job_id,
            corpus=None,
            term="politik",
            window=5,
            within_sentence=True,
            sort_by="dice",
            limit=2,
            target_doc_ids=np.array([1], dtype=np.uint32),
            reference_doc_ids=np.array([2], dtype=np.uint32),
            target_docset_key="target",
            reference_docset_key="reference",
        )
    )

    stored = analysis_jobs.get(job.job_id)
    assert stored.status == "done"
    assert stored.result is not None
    assert stored.result["row_limit"] == 2
    assert stored.result["total_candidates"] == 5
    assert stored.result["truncated"] is True
    assert stored.result["method"]["event_space"] == "corpus_tokens"
    assert stored.result["method"]["event_total_definition"] == "scope_tokens"


def test_analysis_keyness_list_returns_bound_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(
        server,
        "_compute_keyness",
        lambda *args, **kwargs: _FakeFrame(
            [{"word": f"k{i}", "chi2_cell": float(i), "ll": float(i)} for i in range(5)]
        ),
    )

    result = asyncio.run(
        server.analysis_keyness(
            {
                "target": ["a", "b"],
                "reference": ["c", "d"],
                "limit": 999,
            }
        )
    )

    assert [row["word"] for row in result["rows"]] == ["k0", "k1", "k2"]
    assert result["row_limit"] == 3
    assert result["total_candidates"] == 5
    assert result["truncated"] is True


def test_analysis_keyness_corpus_compare_returns_directed_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Corpus:
        def __init__(self, rows: list[dict], token_total: int):
            self._rows = rows
            self._token_total = token_total

        def frequency_list(self, *, stopwords=None):
            return _FakeFrame(self._rows)

        def token_count(self):
            return self._token_total

    corpora = {
        "target": _Corpus([{"word": "alpha", "f": 10}, {"word": "shared", "f": 1}], 100),
        "reference": _Corpus([{"word": "beta", "f": 10}, {"word": "shared", "f": 1}], 100),
    }
    monkeypatch.setattr(server, "get_corpus", lambda name: corpora[str(name)])
    monkeypatch.setattr(server, "_doc_count_for_index", lambda _idx: 1)

    async def _fake_population(_server, idx, _doc_ids, *, pos):
        assert pos is None
        return ({str(row["word"]): int(row["f"]) for row in idx._rows}, idx._token_total)

    from candyconc.services.backend.routes import analysis as analysis_routes

    monkeypatch.setattr(analysis_routes, "_keyness_docset_population", _fake_population)

    result = asyncio.run(
        server.analysis_keyness(
            {
                "target_corpus": "target",
                "reference_corpus": "reference",
                "limit": 10,
            }
        )
    )

    rows = {row["word"]: row for row in result["rows"]}
    assert rows["alpha"]["direction"] == "target"
    assert rows["alpha"]["chi2_cell"] >= 0.0
    assert "mi2" not in rows["alpha"]
    assert rows["alpha"]["chi2_cell_signed"] > 0
    assert rows["beta"]["direction"] == "reference"
    assert rows["beta"]["chi2_cell_signed"] < 0


def test_word_sketch_endpoint_caps_each_relation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_word_sketch_for_query",
        lambda idx, term, **kwargs: {
            "obj": _FakeFrame([{"word": f"o{i}", "f": i, "score": float(i)} for i in range(5)]),
            "amod": _FakeFrame([{"word": f"a{i}", "f": i, "score": float(i)} for i in range(4)]),
        },
    )

    # min_freq=0 disables the new hapax floor (FT id 7) so this test isolates the
    # per-relation capping behaviour it targets (the floor is covered separately
    # in test_analysis_release_fixes_r9).
    result = asyncio.run(server.word_sketch_endpoint({"term": "politik", "min_freq": 0}))

    assert [row["word"] for row in result["obj"]] == ["o0", "o1"]
    assert [row["word"] for row in result["amod"]] == ["a0", "a1"]


def test_word_sketch_endpoint_honours_payload_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 5)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 5)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())

    captured: dict[str, int] = {}

    def fake_word_sketch(idx, term, **kwargs):
        captured.update(kwargs)
        return {
            "obj": _FakeFrame([{"word": f"o{i}", "f": i, "score": float(i)} for i in range(4)]),
        }

    monkeypatch.setattr(
        server,
        "_word_sketch_for_query",
        fake_word_sketch,
    )

    result = asyncio.run(server.word_sketch_endpoint({"term": "politik", "limit": 1, "min_freq": 0}))

    # The route asks the normalizer for the complete relation so it can report
    # honest completeness, then applies the public payload cap itself.
    assert captured["relation_limit"] == 0
    assert [row["word"] for row in result["obj"]] == ["o0"]
    assert result["relations"]["obj"] == {
        "relation": "obj",
        "label": "obj",
        "row_limit": 1,
        "total_candidates": 4,
        "total_rows": 1,
        "truncated": True,
        "min_freq": 0,
    }


def test_word_sketch_endpoint_rejects_incomplete_docset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_get_docset",
        lambda docset_id: {"corpus": "default", "doc_ids": np.array([0], dtype=np.uint32)},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server.word_sketch_endpoint({"term": "politik", "docset_id": "d1"}))

    # DT-VERTRAEGE: incomplete docset is an input-validation error -> 422 class.
    assert exc_info.value.status_code == 422
    assert "Docset unvollständig" in str(exc_info.value.detail)


def test_analysis_collocates_docset_frequency_failure_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_get_docset",
        lambda docset_id: {"corpus": "default", "doc_ids": np.array([0], dtype=np.uint32)},
    )

    def fail_docset_collocates(*_args, **_kwargs):
        raise RuntimeError(
            "Docset-Frequenzen konnten nicht berechnet werden. "
            "Kollokationswerte werden nicht mit globalen Korpusfrequenzen ausgegeben."
        )

    monkeypatch.setattr(server, "_collocate_stats_for_term", fail_docset_collocates)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server.analysis_collocates(term="politik", docset_id="d1"))

    assert exc_info.value.status_code == 422
    assert "Docset-Frequenzen konnten nicht berechnet" in str(exc_info.value.detail)


def test_analysis_dispersion_rejects_unbounded_partitions_before_corpus_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_get_corpus(corpus):
        raise AssertionError("get_corpus must not run for invalid partitions")

    monkeypatch.setattr(server, "get_corpus", fail_get_corpus)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server.analysis_dispersion(term="politik", partitions=10_000_000))

    assert exc_info.value.status_code == 422
    assert "partitions must be <=" in str(exc_info.value.detail)


def test_analysis_dispersion_offsets_caps_large_requested_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(server, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *args, **kwargs: np.arange(5, dtype=np.uint32),
    )

    result = asyncio.run(server.analysis_dispersion_offsets(term="politik", limit=999))

    assert result["offsets"] == [0, 1, 2]
    assert result["basis"] == "global_offsets_only"
    # A maximum hit offset is not a token denominator.  The evidence page is
    # usable, but it must never fabricate a normalisation basis.
    assert result["token_count"] is None
    assert result["fallback"] is False
    assert result["partial"] is True
    assert result["limitations"][0]["code"] == "dispersion_offsets_token_basis_unavailable"
    # DISP-1: the capped page (3 of 5 offsets) reports honest completeness so the
    # UI can render "3 von 5" instead of implying the page is the whole set.
    assert result["truncated"] is True
    assert result["total"] == 5
    assert result["next_offset"] == 3


def test_analysis_dispersion_refuses_synthetic_document_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing document basis must block DP rather than inventing windows."""
    monkeypatch.setattr(server, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *args, **kwargs: np.array([0, 10, 20], dtype=np.uint32),
    )
    monkeypatch.setattr(
        server,
        "_doc_bounds_for_index",
        lambda idx: (_ for _ in ()).throw(RuntimeError("Dokumentgrenzen fehlen")),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server.analysis_dispersion(term="politik"))

    assert exc_info.value.status_code == 422
    assert "exakte Dokumentgrenzen" in str(exc_info.value.detail)


def test_analysis_dispersion_reports_exact_global_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Index:
        def token_count(self) -> int:
            return 100

    # Two documents: [0,50) and [50,100). Hits at 0,50,99 -> doc0 gets 1, doc1
    # gets 2. Dispersion is now partitioned over real document boundaries.
    doc_bounds = np.array([0, 50], dtype=np.uint32)
    monkeypatch.setattr(server, "get_corpus", lambda corpus: _Index())
    monkeypatch.setattr(server, "_doc_bounds_for_index", lambda idx: doc_bounds)
    monkeypatch.setattr(
        server,
        "_dispersion_positions_for_term",
        lambda *args, **kwargs: np.array([0, 50, 99], dtype=np.uint32),
    )

    result = asyncio.run(server.analysis_dispersion(term="politik"))

    # One partition per document, in document order.
    assert result["partitions"] == [1, 2]
    assert result["doc_sizes"] == [50, 50]
    assert result["unit"] == "documents"
    # Equal-size docs -> dpnorm = dp / (1 - 1/2) = 2*dp.
    expected = server._gries_dp_documents([1, 2], [50, 50])
    assert result["dp"] == pytest.approx(expected["dp"], rel=1e-9)
    assert result["dpnorm"] == pytest.approx(expected["dpnorm"], rel=1e-9)
    assert result["basis"] == "global"
    assert result["token_count"] == 100
    assert result["fallback"] is False
    assert result["partial"] is False
    assert result["limitations"] == []


def test_collocate_segments_clip_docset_windows_to_document_bounds() -> None:
    class _Bounds:
        def clip_bounds_array(self, within_sentence):
            assert within_sentence is False
            return np.array([0, 2, 4], dtype=np.uint32)

    engine = SimpleNamespace(
        token_store=SimpleNamespace(token_count=4),
        boundaries=_Bounds(),
    )

    segments = server._collocate_segments_for_anchors(
        engine,
        np.array([1], dtype=np.uint32),
        np.array([1], dtype=np.int64),
        window=3,
        within_sentence=False,
        clip_to_document=True,
    )

    assert segments.seg_starts.tolist() == [0]
    assert segments.seg_ends.tolist() == [1]
    assert max(segments.seg_ends.tolist()) <= 2
    assert segments.context_mass == 1


def test_collocate_segments_zaehlen_die_union_und_koennen_noch_paare() -> None:
    """Die Vorgabe ist seit dem 2026-08-29 die Union, nicht das Paar.

    Der Vorgaengertest pinnte context_mass 8 und die Gewichte [1,2,1,1,2,1]:
    die ueberlappende Mitte zaehlte zweimal, einmal je Anker. Das ist der
    Paar-Ereignisraum, in dem R1 in Token und C1 = f(v)*m in Anker-mal-Token
    steht. Everts Kontingenztafel fuer distanzbasierte Kookkurrenzen (2004,
    Fig. 2.13) zaehlt jedes Token der Fenster-Vereinigung EINMAL.

    Beide Zaehlweisen bleiben pruefbar: die Vorgabe, weil sie die Zahlen
    aller Assoziationsmasse traegt, und die Paarvariante, weil das Umlegen
    des Schalters sonst unbemerkt ins Leere laufen koennte.
    """
    engine = SimpleNamespace(
        token_store=SimpleNamespace(token_count=6),
        boundaries=None,
    )
    anker = np.array([2, 3], dtype=np.uint32)
    spannen = np.array([1, 1], dtype=np.int64)

    union = server._collocate_segments_for_anchors(
        engine, anker, spannen, window=2, within_sentence=False)
    # Sechs Token in der Vereinigung, jedes mit Gewicht 1.
    assert union.context_mass == 6
    assert union.seg_weights.tolist() == [1, 1, 1, 1, 1, 1]

    paare = server._collocate_segments_for_anchors(
        engine, anker, spannen, window=2, within_sentence=False,
        pair_semantics=True)
    assert paare.context_mass == 8
    assert paare.seg_weights.tolist() == [1, 2, 1, 1, 2, 1]
