"""Smoke tests for the extracted /analysis/* route family.

Route-extraction slice 4 moved these 29 routes verbatim from ``server.py`` into
``routes/analysis.py``. These tests pin the extraction contract:

1. the module imports and exposes a router with exactly the expected paths,
2. the routes are registered on the app under /api/v1,
3. server.py re-exports the handler names (services.controller and existing
   tests resolve them as ``server.<handler>`` attributes),
4. handlers reach shared server state lazily (``_server.<attr>``), so existing
   test monkeypatches on ``server`` module globals keep working.

All analysis machinery (analysis_jobs runners, _launch_collocates_diff, docset
store, _ANALYSIS_* limits) intentionally stays in server.py.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

EXPECTED = {
    ("GET", "/analysis/meta_schema"),
    ("POST", "/analysis/meta_values"),
    ("POST", "/analysis/meta_counts"),
    ("POST", "/analysis/frequency_list/job"),
    ("POST", "/analysis/frequency_diff/job"),
    ("GET", "/analysis/jobs/{job_id}"),
    ("POST", "/analysis/jobs/{job_id}/cancel"),
    ("GET", "/analysis/jobs/{job_id}/rows"),
    ("GET", "/analysis/frequency_list"),
    ("POST", "/analysis/docset_from_meta"),
    ("POST", "/analysis/trend"),
    ("POST", "/analysis/docset_intersection"),
    ("POST", "/analysis/parallel_groups"),
    ("POST", "/analysis/alignment/ref_doc"),
    ("POST", "/analysis/docset_from_search"),
    ("POST", "/analysis/ngrams"),
    ("POST", "/analysis/ngrams/job"),
    ("POST", "/analysis/ngrams_diff/job"),
    ("POST", "/analysis/embedding_search"),
    ("GET", "/analysis/collocates"),
    ("GET", "/analysis/collocates/kwic"),
    ("POST", "/analysis/kwic_parallel"),
    ("POST", "/analysis/collocates/job"),
    ("POST", "/analysis/collocates_diff/job"),
    ("POST", "/analysis/contrast"),
    ("GET", "/analysis/dispersion_offsets"),
    ("GET", "/analysis/dispersion"),
    ("POST", "/analysis/keyness/job"),
    ("POST", "/analysis/keyness"),
    ("POST", "/analysis/wordsketch"),
    # FT-SKETCH-DIFF-DISTRIBUTION: word sketch difference endpoint (r9).
    ("POST", "/analysis/wordsketch_diff"),
    # R7 feature addition: collocation-network vertical slice.
    ("GET", "/analysis/collocation_network"),
    # R7 feature addition: lexical-diversity (F4) and full concordance export (F2).
    ("GET", "/analysis/lexical-diversity"),
    ("POST", "/export/concordance"),
    ("POST", "/export/evidence-package"),
}

HANDLER_NAMES = [
    "analysis_meta_schema",
    "analysis_meta_values",
    "analysis_meta_counts",
    "analysis_frequency_list_job",
    "analysis_frequency_diff_job",
    "analysis_job_status",
    "analysis_job_cancel",
    "analysis_job_rows",
    "analysis_frequency_list",
    "analysis_docset_from_meta",
    "analysis_docset_intersection",
    "analysis_parallel_groups",
    "analysis_alignment_ref_doc",
    "analysis_docset_from_search",
    "analysis_ngrams",
    "analysis_ngrams_job",
    "analysis_ngrams_diff_job",
    "embedding_search_endpoint",
    "analysis_collocates",
    "analysis_collocates_kwic",
    "analysis_kwic_parallel",
    "analysis_collocates_job",
    "analysis_collocates_diff_job",
    "analysis_contrast",
    "analysis_dispersion_offsets",
    "analysis_dispersion",
    "analysis_keyness_job",
    "analysis_keyness",
    "word_sketch_endpoint",
    # R7 feature additions (collocation-network slice, lexical diversity, full export).
    "analysis_collocation_network_get",
    "analysis_lexical_diversity",
    "export_concordance_post",
    "export_evidence_package_post",
    # NOTE: analysis_trend (T3) is deliberately NOT in this list — it was born
    # in routes/analysis.py and has no legacy server.<name> facade re-export.
]


class _FakeFrame:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def slice(self, offset: int, length: int):
        return _FakeFrame(self._rows[int(offset) : int(offset) + int(length)])

    def to_dicts(self):
        return list(self._rows)

    def to_dict(self, orient: str):
        assert orient == "records"
        return list(self._rows)


def _route_set(router):
    out = set()
    for r in router.routes:
        for m in r.methods - {"HEAD", "OPTIONS"}:
            out.add((m, r.path))
    return out


def test_module_imports_and_router_paths_present():
    from candyconc.services.backend.routes import analysis as analysis_routes

    assert _route_set(analysis_routes.router) == EXPECTED


def test_routes_registered_on_app_under_api_v1():
    from candyconc.services.backend import server as srv

    app_paths = set()
    for r in srv.app.routes:
        methods = getattr(r, "methods", None)
        if not methods:
            continue
        for m in methods - {"HEAD", "OPTIONS"}:
            app_paths.add((m, r.path))
    for method, path in EXPECTED:
        assert (method, f"/api/v1{path}") in app_paths, (method, path)


def test_server_reexports_are_the_moved_handlers():
    """services.controller + existing tests resolve handlers as server.<name>."""
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    for name in HANDLER_NAMES:
        moved = getattr(analysis_routes, name)
        reexported = getattr(srv, name)
        assert moved is reexported, name
        assert moved.__module__ == "candyconc.services.backend.routes.analysis", name


def test_meta_values_caps_suggestions_and_reports_the_truncated_field(monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import analysis as analysis_routes

    class FakeIndex:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, object] | None, int | None]] = []

        def metadata_values(self, field, *, filters=None, limit=None):
            self.calls.append((str(field), filters, limit))
            values = ["alpha", "beta", "gamma"]
            return values if limit is None else values[:limit]

    index = FakeIndex()
    monkeypatch.setattr(server, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(server, "get_corpus", lambda _corpus=None: index)

    result = asyncio.run(
        analysis_routes.analysis_meta_values(
            {"fields": ["register"], "limit": 2},
            token="test-user",
        )
    )

    assert result == {
        "values": {"register": ["alpha", "beta"]},
        "truncated_fields": ["register"],
        "limit": 2,
    }
    assert index.calls == [("register", None, 3)]


def test_analysis_machinery_stays_in_server():
    """Job runners / launcher / limits are shared state and must remain server attrs."""
    from candyconc.services.backend import server as srv

    for attr in (
        "analysis_jobs",
        "_launch_collocates_diff",
        "_run_frequency_job",
        "_run_frequency_diff_job",
        "_run_keyness_docset_job",
        "_run_collocates_job",
        "_run_collocates_diff_job",
        "_run_ngrams_job",
        "_run_ngrams_diff_job",
        "_collocates_diff_rows_for_term",
        "_search_docset_doc_ids",
        "_dispersion_positions_for_term",
        "_ANALYSIS_SYNC_LIMIT_DEFAULT",
        "_ANALYSIS_SYNC_LIMIT_MAX",
        "_ANALYSIS_JOB_TOP_N_MAX",
    ):
        assert hasattr(srv, attr), attr


def test_parallel_groups_can_load_one_requested_reference_group(monkeypatch):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    seen_ref_docs: list[int] = []

    async def _run_inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    def _summary(_idx, ref_doc, doc_ids):
        seen_ref_docs.append(int(ref_doc))
        return {
            "ref_doc": int(ref_doc),
            "doc_count": len(doc_ids),
            "doc_ids": list(doc_ids),
            "human_doc_id": int(ref_doc),
            "variant_doc_ids": [doc_id for doc_id in doc_ids if doc_id != ref_doc],
            "variants": [],
            "models": [],
            "text_types": {},
            "sources": [],
        }

    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: object())
    monkeypatch.setattr(srv, "_paired_guard", lambda _idx, _feature: None)
    monkeypatch.setattr(srv, "resolve_pair_groups", lambda *_args, **_kwargs: {4: [4, 7], 9: [9, 10]})
    monkeypatch.setattr(srv, "_parallel_group_summary", _summary)
    monkeypatch.setattr(srv, "_run_heavy_scan", _run_inline)

    result = asyncio.run(
        analysis_routes.analysis_parallel_groups({"corpus": "default", "ref_doc": 4})
    )

    assert result["total"] == 1
    assert [group["ref_doc"] for group in result["groups"]] == [4]
    assert seen_ref_docs == [4]


def test_keyness_job_threads_min_freq_to_docset_runner(monkeypatch):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    captured: dict[str, object] = {}

    class _Jobs:
        def create(self, kind, corpus, params):
            captured["job_kind"] = kind
            captured["job_params"] = params
            return SimpleNamespace(job_id="job-keyness-test")

        def attach_task(self, job_id, task):
            captured["attached_job_id"] = job_id

    def _fake_runner(job_id, **kwargs):
        captured["runner_job_id"] = job_id
        captured["runner_kwargs"] = kwargs

        async def _done():
            return None

        return _done()

    def _fake_create_task(coro):
        coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(srv, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(
        srv,
        "_get_docset",
        lambda docset_id: {
            "corpus": "default",
            "doc_ids": [1, 2] if docset_id == "target" else [3, 4],
        },
    )
    monkeypatch.setattr(srv, "analysis_jobs", _Jobs())
    monkeypatch.setattr(srv, "_run_keyness_docset_job", _fake_runner)
    monkeypatch.setattr(analysis_routes.asyncio, "create_task", _fake_create_task)

    result = asyncio.run(
        analysis_routes.analysis_keyness_job(
            {
                "target_docset_id": "target",
                "reference_docset_id": "reference",
                "corpus": "default",
                "min_freq": 7,
            },
            token="user-token",
        )
    )

    assert result["job_id"] == "job-keyness-test"
    assert captured["job_params"]["min_freq"] == 7
    assert captured["runner_kwargs"]["min_freq"] == 7
    assert captured["runner_kwargs"]["reference_source"] == "docset"


def test_keyness_sync_and_job_reject_overlapping_docsets_before_counting(monkeypatch):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    docsets = {
        "target": {"corpus": "default", "doc_ids": [0, 1]},
        "reference": {"corpus": "default", "doc_ids": [1, 2]},
    }
    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: object())
    monkeypatch.setattr(srv, "_get_docset", lambda docset_id: docsets[docset_id])
    monkeypatch.setattr(srv, "_require_user_access", lambda _token: None)

    with pytest.raises(HTTPException) as sync_exc:
        asyncio.run(
            analysis_routes.analysis_keyness(
                {"target_docset_id": "target", "reference_docset_id": "reference"}
            )
        )
    assert sync_exc.value.status_code == 422

    with pytest.raises(HTTPException) as job_exc:
        asyncio.run(
            analysis_routes.analysis_keyness_job(
                {"target_docset_id": "target", "reference_docset_id": "reference"},
                token="user-token",
            )
        )
    assert job_exc.value.status_code == 422


def test_keyness_job_whole_uses_the_docset_complement(monkeypatch):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    captured: dict[str, object] = {}

    class _Jobs:
        def create(self, kind, corpus, params):
            captured["kind"] = kind
            captured["params"] = params
            return SimpleNamespace(job_id="keyness-whole")

        def attach_task(self, job_id, task):
            captured["attached"] = job_id

    def _fake_runner(job_id, **kwargs):
        captured["job_id"] = job_id
        captured["runner"] = kwargs

        async def _done():
            return None

        return _done()

    def _fake_create_task(coro):
        coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(srv, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(srv, "get_corpus", lambda _corpus: object())
    monkeypatch.setattr(srv, "_doc_count_for_index", lambda _idx: 4)
    monkeypatch.setattr(
        srv, "_get_docset", lambda _docset_id: {"corpus": "default", "doc_ids": [0, 2]}
    )
    monkeypatch.setattr(srv, "analysis_jobs", _Jobs())
    monkeypatch.setattr(srv, "_run_keyness_docset_job", _fake_runner)
    monkeypatch.setattr(analysis_routes.asyncio, "create_task", _fake_create_task)

    result = asyncio.run(
        analysis_routes.analysis_keyness_job(
            {"reference_source": "whole", "target_docset_id": "target"},
            token="user-token",
        )
    )

    assert result["job_id"] == "keyness-whole"
    assert captured["params"]["reference_source"] == "whole"
    assert np.asarray(captured["runner"]["target_doc_ids"]).tolist() == [0, 2]
    assert np.asarray(captured["runner"]["reference_doc_ids"]).tolist() == [1, 3]
    assert captured["runner"]["reference_source"] == "whole"


def test_keyness_job_rejects_an_incomplete_external_reference_before_launch(monkeypatch):
    from candyconc.services.backend import server as srv
    from candyconc.services.backend.routes import analysis as analysis_routes

    launches: list[object] = []

    class _Jobs:
        def create(self, *_args):
            launches.append(_args)
            raise AssertionError("invalid input must not launch a job")

    monkeypatch.setattr(srv, "_require_user_access", lambda _token: None)
    monkeypatch.setattr(srv, "analysis_jobs", _Jobs())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            analysis_routes.analysis_keyness_job(
                {
                    "reference_source": "freqlist",
                    "target": ["wort"],
                    "reference_freq_list": {"wort": 1},
                },
                token="user-token",
            )
        )
    assert exc.value.status_code == 422
    assert not launches


def test_monkeypatch_indirection_roundtrip(monkeypatch):
    """Patching server-module globals must affect the extracted handler.

    Mirrors test_analysis_runtime_bounds: the handler reads get_corpus,
    _frequency_list and the _ANALYSIS_SYNC_* limits via the lazy ``_server``
    import, so server-module monkeypatches stay authoritative.
    """
    from candyconc.services.backend import server as srv

    monkeypatch.setattr(srv, "_ANALYSIS_SYNC_LIMIT_DEFAULT", 2)
    monkeypatch.setattr(srv, "_ANALYSIS_SYNC_LIMIT_MAX", 3)
    monkeypatch.setattr(srv, "get_corpus", lambda corpus: object())
    monkeypatch.setattr(
        srv,
        "_frequency_list",
        lambda **kwargs: _FakeFrame([{"word": f"w{i}", "f": i} for i in range(5)]),
    )

    result = asyncio.run(srv.analysis_frequency_list())

    assert result["rows"] == [{"word": "w0", "f": 0}, {"word": "w1", "f": 1}]
