import json
from pathlib import Path

import pytest

import candyconc.domain.corpus as corpus
from candyconc.services.backend.corpus_registry_service import (
    CorpusRegistryService,
    inspect_corpus_status,
)
from candyconc.services.backend.corpus_import_outcome import write_import_outcome


def _index_dir(path: Path, *, complete: bool = True) -> Path:
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
                "complete": complete,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_inspect_corpus_status_classifies_missing_incomplete_corrupt_ready(tmp_path):
    assert inspect_corpus_status(tmp_path / "missing").status == "missing"

    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    assert inspect_corpus_status(incomplete).status == "incomplete"

    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "meta.bin").write_bytes((0).to_bytes(8, "little"))
    (corrupt / "index_manifest.json").write_text("{bad", encoding="utf-8")
    assert inspect_corpus_status(corrupt).status == "corrupt"

    complete_false = _index_dir(tmp_path / "complete_false", complete=False)
    assert inspect_corpus_status(complete_false).status == "incomplete"

    ready = _index_dir(tmp_path / "ready")
    assert inspect_corpus_status(ready).status == "ready"


def test_registry_service_lists_ready_and_incomplete_without_hiding(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    ready = _index_dir(corpus_dir / "ready")
    incomplete = corpus_dir / "incomplete"
    incomplete.mkdir(parents=True)

    service = CorpusRegistryService(corpus_dir, default_path=ready)
    rows = {row["name"]: row for row in service.list_corpora()}

    assert rows["default"]["status"] == "ready"
    assert rows["incomplete"]["status"] == "incomplete"
    assert rows["incomplete"]["token_count"] == 0


def test_registry_service_hides_imports_staging_dir(tmp_path, monkeypatch):
    """CORPUS-LIFECYCLE-02: the '.imports' staging directory (and any dot-prefixed
    internal scratch dir) must never surface as a corpus in the catalog/switcher.
    Before the fix it leaked as a 0-token 'incomplete' corpus that 409s on
    activation.
    """
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    _index_dir(corpus_dir / "ready")
    # Simulate an in-flight import: .imports/<job>/<name> staging tree.
    staging = corpus_dir / ".imports" / "job123" / "incoming"
    staging.mkdir(parents=True)

    service = CorpusRegistryService(corpus_dir, default_path=None)
    names = {row["name"] for row in service.list_corpora()}

    assert ".imports" not in names
    assert "ready" in names


def test_inspect_rejects_overlong_name_with_valueerror(tmp_path, monkeypatch):
    """CORPUS-LIFECYCLE-01: a >255-byte corpus name must raise ValueError (mapped
    to 400 by the lifecycle routes) instead of letting an OSError(ENAMETOOLONG)
    escape from ``Path.exists`` inside ``inspect_corpus_status`` as a 500.
    """
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir()
    service = CorpusRegistryService(corpus_dir, default_path=None)

    with pytest.raises(ValueError, match="Ungültiger Korpusname"):
        service.inspect("x" * 500)


def test_registry_service_register_activate_unregister(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    ready = _index_dir(corpus_dir / "ready")
    service = CorpusRegistryService(corpus_dir, default_path=None)

    registered = service.register(ready)
    assert registered["name"] == "ready"
    assert registered["status"] == "ready"

    activated = service.activate("ready")
    assert activated["active"] is True
    assert corpus.CorpusRegistry.load().active == str(ready.resolve(strict=False))

    result = service.unregister("ready")
    assert result["status"] == "ok"
    assert corpus.CorpusRegistry.load().indices == []


def test_registry_service_keeps_first_registration_inactive_until_explicit_activation(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    ready = _index_dir(corpus_dir / "ready")
    service = CorpusRegistryService(corpus_dir, default_path=None)

    registered = service.register(ready, activate=False)

    assert registered["active"] is False
    assert corpus.CorpusRegistry.load().active is None


def test_registry_service_requires_explicit_acknowledgement_for_partial_import(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    partial = _index_dir(corpus_dir / "partial")
    write_import_outcome(
        partial,
        {
            "partial_input": True,
            "rejected_rows": 3,
            "import_warnings": ["3 Eingabezeilen wurden verworfen."],
        },
    )
    service = CorpusRegistryService(corpus_dir, default_path=None)

    registered = service.register(partial, activate=False)

    assert registered["partial_input"] is True
    assert registered["rejected_rows"] == 3
    assert registered["active"] is False
    with pytest.raises(RuntimeError, match="Teilimport"):
        service.activate("partial")

    activated = service.activate("partial", acknowledge_partial_input=True)

    assert activated["active"] is True
    assert corpus.CorpusRegistry.load().active == str(partial.resolve(strict=False))


def test_registry_service_fails_closed_when_persisted_import_outcome_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    ready = _index_dir(corpus_dir / "ready")
    (ready / "import_outcome.json").write_text("{not json", encoding="utf-8")
    service = CorpusRegistryService(corpus_dir, default_path=None)

    entry = service.inspect("ready")

    assert entry["partial_input"] is True
    assert "nicht lesbar" in " ".join(entry["import_warnings"])
    with pytest.raises(RuntimeError, match="Teilimport"):
        service.activate("ready")


def test_registry_service_prefers_registered_ref_over_same_named_managed_path(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    external = _index_dir(tmp_path / "external" / "ready")
    (corpus_dir / "ready").mkdir(parents=True)
    service = CorpusRegistryService(corpus_dir, default_path=None)

    service.register(external)
    inspected = service.inspect("ready")

    assert inspected["status"] == "ready"
    assert inspected["path"] == str(external.resolve(strict=False))


def test_registry_service_refuses_to_activate_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    incomplete = corpus_dir / "incomplete"
    incomplete.mkdir(parents=True)
    service = CorpusRegistryService(corpus_dir, default_path=None)

    with pytest.raises(RuntimeError, match="Nur bereite Korpora"):
        service.register(incomplete, activate=True)


def test_registry_service_does_not_auto_activate_incomplete_first_register(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    incomplete = corpus_dir / "incomplete"
    incomplete.mkdir(parents=True)
    service = CorpusRegistryService(corpus_dir, default_path=None)

    registered = service.register(incomplete, activate=False)

    assert registered["status"] == "incomplete"
    assert registered["active"] is False
    loaded = corpus.CorpusRegistry.load()
    assert loaded.indices == [str(incomplete.resolve(strict=False))]
    assert loaded.active is None


def test_inspect_active_matches_list_corpora_for_default(tmp_path, monkeypatch):
    """Finding 28: inspect()/capabilities must report the SAME active flag as
    list_corpora() for the default corpus (it used to default to active=False)."""
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir(parents=True)
    ready = _index_dir(tmp_path / "default_index")
    service = CorpusRegistryService(corpus_dir, default_path=ready)

    # Make the default the active corpus (mirrors a normal single-corpus setup).
    reg = corpus.CorpusRegistry.load()
    reg.register(ready, activate=True)

    listed = {row["name"]: row for row in service.list_corpora()}
    inspected = service.inspect("default")

    assert listed["default"]["active"] is True
    # The previously contradictory value: inspect() reported active:false.
    assert inspected["active"] is True
    assert inspected["active"] == listed["default"]["active"]


def test_inspect_active_matches_list_corpora_for_registered(tmp_path, monkeypatch):
    """Finding 28: the same single-source-of-truth must hold for a named
    (non-default) registered corpus."""
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir(parents=True)
    ready = _index_dir(tmp_path / "external" / "ready")
    service = CorpusRegistryService(corpus_dir, default_path=None)

    service.register(ready, activate=True)

    listed = {row["name"]: row for row in service.list_corpora()}
    inspected = service.inspect("ready")

    assert listed["ready"]["active"] is True
    assert inspected["active"] is True
    assert inspected["active"] == listed["ready"]["active"]


def test_inspect_inactive_corpus_reports_false_consistently(tmp_path, monkeypatch):
    """A non-active corpus must report active:false from both endpoints."""
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    corpus_dir.mkdir(parents=True)
    active_idx = _index_dir(tmp_path / "active_index")
    other_idx = _index_dir(tmp_path / "other_index")
    service = CorpusRegistryService(corpus_dir, default_path=None)

    service.register(active_idx, activate=True)
    service.register(other_idx, activate=False)

    listed = {row["name"]: row for row in service.list_corpora()}
    inspected = service.inspect("other_index")

    assert listed["other_index"]["active"] is False
    assert inspected["active"] is False


def test_the_pinned_default_corpus_shows_its_directory_name(tmp_path, monkeypatch):
    """With CANDYCONC_INDEX_PATH the catalogue called the corpus "default" (erprobung B4).

    ``name`` stays ``default``, the identifier every route accepts for the
    pinned corpus. ``display_name`` is the directory name, for every entry.
    """
    monkeypatch.setattr(corpus, "_REGISTRY_PATH", tmp_path / "registry.json")
    corpus_dir = tmp_path / "corpora"
    pinned = _index_dir(corpus_dir / "sotu_en")
    other = _index_dir(tmp_path / "elsewhere" / "letters")
    _index_dir(corpus_dir / "dta_de")

    for default_path in (pinned, other):
        service = CorpusRegistryService(corpus_dir, default_path)
        entries = service.list_corpora()
        default = next(entry for entry in entries if entry["name"] == "default")
        assert default["display_name"] == default_path.name
        assert service.inspect("default")["display_name"] == default_path.name
        assert {entry["display_name"] for entry in entries if entry["name"] != "default"} >= {"dta_de"}
    # The pinned corpus inside the corpus folder appears once, under "default".
    names = [entry["display_name"] for entry in CorpusRegistryService(corpus_dir, pinned).list_corpora()]
    assert names.count("sotu_en") == 1
