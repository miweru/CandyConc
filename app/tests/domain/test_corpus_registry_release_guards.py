import json
from pathlib import Path

import candyconc.domain.corpus as corpus


def test_registry_canonicalizes_and_deduplicates_paths(tmp_path, monkeypatch):
    registry_path = tmp_path / "corpora.json"
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", registry_path)
    target = tmp_path / "corpora" / "demo"
    target.mkdir(parents=True)

    reg = corpus.CorpusRegistry.load()
    reg.register(target)
    reg.register(target / ".." / "demo")

    loaded = corpus.CorpusRegistry.load()
    assert loaded.indices == [str(target.resolve(strict=False))]
    assert loaded.active is None

    data = json.loads(registry_path.read_text("utf-8"))
    assert data["indices"] == [str(target.resolve(strict=False))]


def test_registry_unregister_uses_canonical_paths(tmp_path, monkeypatch):
    registry_path = tmp_path / "corpora.json"
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", registry_path)
    target = tmp_path / "corpora" / "demo"
    target.mkdir(parents=True)

    reg = corpus.CorpusRegistry.load()
    reg.register(target, activate=True)
    reg.unregister(target / ".." / "demo")

    loaded = corpus.CorpusRegistry.load()
    assert loaded.indices == []
    assert loaded.active is None
