from __future__ import annotations

import json
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import candyconc.domain.corpus as corpus


def _index_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "meta.bin").write_bytes((0).to_bytes(8, "little"))
    (path / "index_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "import_mode": "test",
                "paired": False,
                "pair_axes": [],
                "annotation_source": "test",
                "capabilities": {},
                "dtypes": {},
                "build_fingerprint": "fixture",
                "created_at": "2026-06-12T00:00:00Z",
                "complete": True,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_configured_default_index_path_ignores_active_registry(
    tmp_path,
    monkeypatch,
):
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    monkeypatch.delenv("CANDYCONC_INDEX_PATH", raising=False)
    configured = _index_dir(tmp_path / "configured_default")
    active = _index_dir(tmp_path / "active_registered")
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=str(configured)))

    corpus.CorpusRegistry.load().register(active, activate=True)

    assert server._configured_default_index_path() == configured.resolve(strict=False)
    assert server._resolve_index_path() == configured.resolve(strict=False)


def test_env_default_index_path_ignores_active_registry(tmp_path, monkeypatch):
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    active = _index_dir(tmp_path / "active_registered")
    env_index = _index_dir(tmp_path / "env_default")
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(env_index))
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))

    corpus.CorpusRegistry.load().register(active, activate=True)

    assert server._configured_default_index_path() == env_index.resolve()
    assert server._resolve_index_path() == env_index.resolve()


def test_active_registry_is_default_fallback_when_no_default_is_configured(tmp_path, monkeypatch):
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    active = _index_dir(tmp_path / "active_registered")
    monkeypatch.delenv("CANDYCONC_INDEX_PATH", raising=False)
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))

    corpus.CorpusRegistry.load().register(active, activate=True)

    assert server._configured_default_index_path() is None
    assert server._resolve_index_path() == active.resolve(strict=False)


def test_named_registry_corpus_resolves_for_runtime_and_meta_schema(tmp_path, monkeypatch):
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    corpus_dir = tmp_path / "managed"
    corpus_dir.mkdir()
    demo = _index_dir(tmp_path / "registered" / "demo")
    default = _index_dir(tmp_path / "configured_default")
    monkeypatch.setattr(server, "_CORPUS_DIR", corpus_dir)
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(default))
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))

    class FakeCorpusIndex:
        def __init__(self, path: Path):
            self.path = Path(path)
            self.fast_index = SimpleNamespace(index_path=str(path))

    monkeypatch.setattr(server, "CorpusIndex", FakeCorpusIndex)
    corpus.CorpusRegistry.load().register(demo, activate=False)

    idx = server.get_corpus("demo")
    meta_name, meta_path = server._resolve_meta_schema_index_path("demo")

    assert idx.path == demo.resolve(strict=False)
    assert meta_name == "demo"
    assert meta_path == demo.resolve(strict=False)


def test_default_demo_default_activation_is_reversible(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from candyconc.services.backend import server

    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    corpus_dir = tmp_path / "managed"
    corpus_dir.mkdir()
    default = _index_dir(tmp_path / "configured_default")
    demo = _index_dir(tmp_path / "registered" / "demo")
    monkeypatch.setattr(server, "_CORPUS_DIR", corpus_dir)
    monkeypatch.setattr(server, "_INDEX_PATH", None)
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(default))
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))

    async def _noop_reload() -> None:
        return None

    monkeypatch.setattr(server, "reload_default_corpus_runtime_state", _noop_reload)
    corpus.CorpusRegistry.load().register(default, activate=True)
    corpus.CorpusRegistry.load().register(demo, activate=False)
    client = TestClient(server.app)

    before = {item["name"]: item for item in client.get("/api/v1/corpora").json()["corpora"]}
    assert before["default"]["path"] == str(default.resolve())
    assert before["default"]["active"] is True
    assert before["demo"]["active"] is False

    demo_response = client.post("/api/v1/corpora/demo/activate")
    assert demo_response.status_code == 200, demo_response.text
    after_demo = {item["name"]: item for item in client.get("/api/v1/corpora").json()["corpora"]}
    assert after_demo["default"]["path"] == str(default.resolve())
    assert after_demo["default"]["active"] is False
    assert after_demo["demo"]["active"] is True

    default_response = client.post("/api/v1/corpora/default/activate")
    assert default_response.status_code == 200, default_response.text
    after_default = {item["name"]: item for item in client.get("/api/v1/corpora").json()["corpora"]}
    assert after_default["default"]["path"] == str(default.resolve())
    assert after_default["default"]["active"] is True
    assert after_default["demo"]["active"] is False


def test_corpus_catalogue_default_path_stays_configured_after_runtime_switch(tmp_path, monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import corpora as corpora_routes

    monkeypatch.setattr(server.tempfile, "gettempdir", lambda: str(tmp_path / "_system_tmp"))
    configured = _index_dir(tmp_path / "configured_default")
    runtime_loaded = _index_dir(tmp_path / "runtime_loaded_demo")
    monkeypatch.setenv("CANDYCONC_INDEX_PATH", str(configured))
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(index_dir=""))
    monkeypatch.setattr(server, "_INDEX_PATH", runtime_loaded)

    _corpus_dir, default_path = corpora_routes._corpus_dir_and_default()

    assert default_path == configured.resolve()


def test_reset_default_corpus_runtime_state_drops_index_and_result_caches(monkeypatch):
    from candyconc.core import query_runtime
    from candyconc.domain import query_eval
    from candyconc.services.backend import server

    sentinel = object()
    cleared = {"query_eval": False}

    def clear_query_eval_positions() -> None:
        cleared["query_eval"] = True

    monkeypatch.setattr(query_eval, "clear_positions_cache", clear_query_eval_positions)
    server.set_default_index(sentinel, path=Path("/index/old"), corpus_index=sentinel)
    query_runtime.set_corpus(sentinel)
    server._LANG_INDICES["en"] = sentinel
    server._DOCSET_CACHE["docset"] = {"corpus": "old"}
    server._REFDOC_INDEX_CACHE["default"] = {1: [2]}
    server._REFDOC_INDEX_DOC_COUNT["default"] = 3
    server._QUERY_ROWS_RESPONSE_CACHE[("q", "", 0, "", "", 10)] = (b"{}", 2, {})
    server._QUERY_ROWS_RESPONSE_CACHE_BYTES = 2
    server._QUERY_STREAM_BATCH_CACHE[("q", "", 0, "", "", "", 10, 0, 0)] = ([], 0, False, None, False, 2)
    server._QUERY_STREAM_BATCH_CACHE_BYTES = 2
    server._ANCHOR_POS_CACHE[("q", "", False)] = (sentinel, sentinel, 2)
    server._ANCHOR_POS_CACHE_BYTES = 2
    server._QUERY_COUNT_CACHE[("default", "q", "", "", "")] = server._QueryCountState(
        task=None,
        result=(1, 1.0, False),
        error=None,
        started_at=time.monotonic(),
        last_access=time.monotonic(),
        watchers=0,
        cancel_task=None,
    )
    monkeypatch.setattr(server.manager, "_manager", sentinel)

    server.reset_default_corpus_runtime_state()

    assert server._INDEX is None
    assert server._INDEX_PATH is None
    assert server._CORPUS_INDEX is None
    assert query_runtime._CORPUS_INDEX is None
    assert server._LANG_INDICES == {}
    assert server._DOCSET_CACHE == {}
    assert server._REFDOC_INDEX_CACHE == {}
    assert server._REFDOC_INDEX_DOC_COUNT == {}
    assert server._QUERY_ROWS_RESPONSE_CACHE == {}
    assert server._QUERY_ROWS_RESPONSE_CACHE_BYTES == 0
    assert server._QUERY_STREAM_BATCH_CACHE == {}
    assert server._QUERY_STREAM_BATCH_CACHE_BYTES == 0
    assert server._ANCHOR_POS_CACHE == {}
    assert server._ANCHOR_POS_CACHE_BYTES == 0
    assert server._QUERY_COUNT_CACHE == {}
    assert server.manager._manager is None
    assert cleared["query_eval"] is True


def test_lang_index_cache_evicts_old_catalogue_indices_without_closing_default(monkeypatch):
    from candyconc.services.backend import server

    class DummyIndex:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    default = DummyIndex()
    old = DummyIndex()
    keep = DummyIndex()

    monkeypatch.setattr(server, "_LANG_INDICES_LIMIT", 2)
    server.set_default_index(default, path=Path("/index/default"), corpus_index=default)
    server._LANG_INDICES.clear()
    server._LANG_INDICES["en"] = default
    server._LANG_INDICES["old"] = old
    server._LANG_INDICES["keep"] = keep

    server._trim_lang_indices_locked()

    assert list(server._LANG_INDICES) == ["en", "keep"]
    assert old.closed is True
    assert default.closed is False
    assert keep.closed is False


def test_refdoc_index_cache_eviction_keeps_doc_counts_in_sync(monkeypatch):
    from candyconc.services.backend import alignment

    monkeypatch.setattr(alignment, "get_config", lambda _name, _default=None: "2")
    alignment._REFDOC_INDEX_CACHE.clear()
    alignment._REFDOC_INDEX_DOC_COUNT.clear()
    alignment._REFDOC_INDEX_CACHE["a"] = {1: [1]}
    alignment._REFDOC_INDEX_DOC_COUNT["a"] = 1
    alignment._REFDOC_INDEX_CACHE["b"] = {2: [2]}
    alignment._REFDOC_INDEX_DOC_COUNT["b"] = 2
    alignment._REFDOC_INDEX_CACHE["c"] = {3: [3]}
    alignment._REFDOC_INDEX_DOC_COUNT["c"] = 3

    alignment._trim_refdoc_index_cache()

    assert list(alignment._REFDOC_INDEX_CACHE) == ["b", "c"]
    assert list(alignment._REFDOC_INDEX_DOC_COUNT) == ["b", "c"]


def test_reset_default_corpus_runtime_state_cancels_query_count_tasks():
    from candyconc.services.backend import server

    async def run() -> None:
        key = ("default", "q", "", "", "")

        def compute() -> tuple[int, float, bool]:
            time.sleep(1)
            return (1, 1.0, False)

        state = await server._get_or_create_query_count(
            key,
            create=True,
            compute_fn=compute,
            attach=True,
        )
        assert state is not None and state.task is not None

        server.reset_default_corpus_runtime_state()
        await asyncio.sleep(0)

        assert key not in server._QUERY_COUNT_CACHE
        assert state.task.cancelled() or state.task.cancelling() > 0

    asyncio.run(run())


def test_lexicon_suggest_reloads_default_index_after_runtime_reset(monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import query as query_routes

    fake_index = SimpleNamespace(fast_index=object())
    monkeypatch.setattr(server, "_CORPUS_INDEX", None)
    monkeypatch.setattr(server, "get_index", lambda: fake_index)
    monkeypatch.setattr(query_routes, "_lexicon_suggest_values", lambda *args: ["Haus"])

    result = asyncio.run(
        query_routes.lexicon_suggest_endpoint(
            query_routes.LexiconSuggestRequest(attr="word", prefix="Ha", limit=5)
        )
    )

    assert result == {"values": ["Haus"]}


def test_lexicon_suggest_uses_explicit_corpus(monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import query as query_routes

    fake_index = SimpleNamespace(fast_index=object())
    seen: dict[str, object] = {}

    def get_corpus(name: str | None):
        seen["corpus"] = name
        return fake_index

    monkeypatch.setattr(server, "get_corpus", get_corpus)
    monkeypatch.setattr(query_routes, "_lexicon_suggest_values", lambda *args: ["Korpuswort"])

    result = asyncio.run(
        query_routes.lexicon_suggest_endpoint(
            query_routes.LexiconSuggestRequest(attr="word", prefix="Ko", limit=5, corpus="demo")
        )
    )

    assert seen["corpus"] == "demo"
    assert result == {"values": ["Korpuswort"]}


def test_cql_analyse_reloads_default_index_after_runtime_reset(monkeypatch):
    import candyconc.core.cql_engine as cql_engine
    from candyconc.services.backend import server

    fake_fast = object()
    fake_index = SimpleNamespace(fast_index=fake_fast)
    seen: dict[str, object] = {}

    def analyse(fast_index, query):
        seen["fast_index"] = fast_index
        seen["query"] = query
        return {"errors": [], "suggestions": [], "hints": [], "spans": []}

    monkeypatch.setattr(server, "_CORPUS_INDEX", None)
    monkeypatch.setattr(server, "get_index", lambda: fake_index)
    monkeypatch.setattr(server, "_lightweight_cql_analysis", lambda _query, _normalized: None)
    monkeypatch.setattr(cql_engine, "analyse_cql_backend", analyse)

    result = asyncio.run(server._analyse_query_text('cql:[word="Haus"]'))

    assert result["errors"] == []
    assert seen["fast_index"] is fake_fast


def test_cql_analyse_uses_explicit_corpus(monkeypatch):
    import candyconc.core.cql_engine as cql_engine
    from candyconc.services.backend import server

    fake_fast = object()
    fake_index = SimpleNamespace(fast_index=fake_fast)
    seen: dict[str, object] = {}

    def get_corpus(name: str | None):
        seen["corpus"] = name
        return fake_index

    def analyse(fast_index, query):
        seen["fast_index"] = fast_index
        seen["query"] = query
        return {"errors": [], "suggestions": [], "hints": [], "spans": []}

    monkeypatch.setattr(server, "get_corpus", get_corpus)
    monkeypatch.setattr(server, "_lightweight_cql_analysis", lambda _query, _normalized: None)
    monkeypatch.setattr(cql_engine, "analyse_cql_backend", analyse)

    result = asyncio.run(server._analyse_query_text('cql:[word="Haus"]', corpus="demo"))

    assert result["errors"] == []
    assert seen["corpus"] == "demo"
    assert seen["fast_index"] is fake_fast


def test_cql_analyse_reports_503_when_no_default_index_after_reset(monkeypatch):
    from candyconc.services.backend import server

    monkeypatch.setattr(server, "_CORPUS_INDEX", None)
    monkeypatch.setattr(server, "get_index", lambda: (_ for _ in ()).throw(RuntimeError("missing")))
    monkeypatch.setattr(server, "_lightweight_cql_analysis", lambda _query, _normalized: None)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(server._analyse_query_text('cql:[word="Haus"]'))

    assert excinfo.value.status_code == 503


def test_activate_route_reloads_default_runtime_after_registry_change(monkeypatch):
    from candyconc.services.backend import server
    from candyconc.services.backend.routes import corpora as corpora_routes

    calls: list[str] = []

    class Service:
        def inspect(self, name: str) -> dict[str, object]:
            return {"name": name, "status": "ready", "source": "registry"}

        def activate(
            self,
            name: str,
            *,
            acknowledge_partial_input: bool = False,
        ) -> dict[str, object]:
            assert acknowledge_partial_input is False
            calls.append(name)
            return {"name": name, "active": True}

    async def reload() -> None:
        calls.append("reload")

    monkeypatch.setattr(corpora_routes, "_registry_service", lambda: Service())
    monkeypatch.setattr(server, "reload_default_corpus_runtime_state", reload)

    result = asyncio.run(corpora_routes.activate_corpus_route("demo", token=None, _auth=None))

    assert result == {"name": "demo", "active": True}
    assert calls == ["demo", "reload"]
