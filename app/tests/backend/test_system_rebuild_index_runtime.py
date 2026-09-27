import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from candyconc.services.backend import server


class _FakeFastIndex:
    def __init__(self, index_path: Path):
        self.index_path = str(index_path)


class _FakeCorpusIndex:
    def __init__(self, index_path: Path):
        self.fast_index = _FakeFastIndex(index_path)


@pytest.fixture(autouse=True)
def _clean_faiss_task(monkeypatch):
    fake_manager = SimpleNamespace(
        faiss_build_task=None,
        faiss_status="idle",
        faiss_status_detail=None,
        _load_faiss=None,
    )
    monkeypatch.setattr(server.manager, "_manager", fake_manager)
    yield


def _patch_minimal_faiss_runtime(monkeypatch, index_dir: Path, calls: dict[str, object]) -> None:
    # Since 2026-09-27 a rebuild without stored passage vectors checks first
    # that the corpus pipeline has word vectors (core.word_vectors).
    import json

    (index_dir / "index_manifest.json").write_text(
        json.dumps({"annotation_pipeline": "xx_rebuild_test_md", "pipeline_vectors": 3}), "utf-8"
    )
    monkeypatch.setattr("candyconc.ingest.pipelines.pipeline_installed", lambda _name: True)
    monkeypatch.setattr(server, "faiss", object())
    monkeypatch.setattr(server, "get_index", lambda: _FakeCorpusIndex(index_dir))
    monkeypatch.setattr(server, "get_corpus", lambda _name=None: _FakeCorpusIndex(index_dir))
    monkeypatch.setattr(server, "_schedule_faiss_reset", lambda _task: None)

    async def _fake_load(index_path, vecs_path, texts_path):
        calls["loaded"] = (
            Path(index_path),
            Path(vecs_path),
            Path(texts_path),
        )

    monkeypatch.setattr(server.manager, "_load_faiss", _fake_load)


def test_rebuild_index_default_uses_active_fast_index_when_passage_embeddings_are_missing(
    tmp_path, monkeypatch
):
    calls: dict[str, object] = {}
    _patch_minimal_faiss_runtime(monkeypatch, tmp_path, calls)

    def _build_from_fast_index(index_dir, out_dir, **kwargs):
        calls["from_fast_index"] = (Path(index_dir), Path(out_dir), sorted(kwargs))

    def _build_from_existing_embeddings(*_args, **_kwargs):  # pragma: no cover - assertion path
        raise AssertionError("existing passage-embedding builder must not run")

    monkeypatch.setattr(
        server.index_utils,
        "build_faiss_index_from_fast_index",
        _build_from_fast_index,
    )
    monkeypatch.setattr(
        server.index_utils,
        "build_faiss_index",
        _build_from_existing_embeddings,
    )

    async def _run():
        job_id = await server.start_faiss_build("default")
        assert job_id
        await server.manager.faiss_build_task

    asyncio.run(_run())

    assert calls["from_fast_index"] == (
        tmp_path.resolve(),
        tmp_path.resolve(),
        ["confirm", "progress_cb"],
    )
    assert calls["loaded"] == (
        tmp_path / "faiss_passage.index",
        tmp_path / "passage_vecs.npy",
        tmp_path / "passage_texts.json",
    )
    assert server.manager.faiss_status == "ready"


def test_rebuild_index_reuses_existing_passage_embeddings(tmp_path, monkeypatch):
    (tmp_path / "passage_vecs.npy").write_bytes(b"placeholder")
    (tmp_path / "passage_texts.json").write_text("[]", encoding="utf-8")
    calls: dict[str, object] = {}
    _patch_minimal_faiss_runtime(monkeypatch, tmp_path, calls)

    def _build_from_existing_embeddings(corpus_dir, out_dir, **kwargs):
        calls["from_existing_embeddings"] = (Path(corpus_dir), Path(out_dir), sorted(kwargs))

    def _build_from_fast_index(*_args, **_kwargs):  # pragma: no cover - assertion path
        raise AssertionError("fast-index embedding rebuild must not run")

    monkeypatch.setattr(
        server.index_utils,
        "build_faiss_index",
        _build_from_existing_embeddings,
    )
    monkeypatch.setattr(
        server.index_utils,
        "build_faiss_index_from_fast_index",
        _build_from_fast_index,
    )

    async def _run():
        job_id = await server.start_faiss_build("default")
        assert job_id
        await server.manager.faiss_build_task

    asyncio.run(_run())

    assert calls["from_existing_embeddings"] == (
        tmp_path.resolve(),
        tmp_path.resolve(),
        ["confirm", "progress_cb"],
    )
    assert calls["loaded"] == (
        tmp_path / "faiss_passage.index",
        tmp_path / "passage_vecs.npy",
        tmp_path / "passage_texts.json",
    )
    assert server.manager.faiss_status == "ready"


def test_rebuild_index_reports_missing_faiss_without_running_job(monkeypatch):
    monkeypatch.setattr(server, "faiss", None)
    server.manager.faiss_build_task = None

    async def _run():
        with pytest.raises(RuntimeError, match="FAISS fehlt"):
            await server.start_faiss_build("default")

    asyncio.run(_run())
    assert server.manager.faiss_build_task is None
    assert server.manager.faiss_status == "error"
