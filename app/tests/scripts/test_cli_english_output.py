"""The command line writes English, also where the server keeps a bilingual text.

Before: ``candy import`` printed its progress in German ("Lade spaCy Modell",
"Tokens gesamt", "Fertig:"), the disk space check blocked with "Disk-Preflight
blockiert den Import" and the German half of its bilingual message, and
``candy migrate-project`` answered "Projektdatei nicht gefunden".
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("spacy", reason="spaCy not installed")

from candyconc.i18n import lt  # noqa: E402
from candyconc.ingest import ingest_adapters as ia  # noqa: E402

#: Words of the former German progress and warning lines.
GERMAN = re.compile(
    r"Lade |gesamt|Lexika|Indizes|gebaut|Fertig|verfuegbar|Eintraege|nutzt|ueberspringe|Speicher"
)


def test_import_progress_lines_are_english(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")
    src = tmp_path / "tea.jsonl"
    src.write_text(
        '{"id": "d1", "text": "Tea is my morning ritual. I drink green tea."}\n'
        '{"id": "d2", "text": "Coffee is fine. Tea wins."}\n',
        encoding="utf-8",
    )
    out = tmp_path / "idx"
    with caplog.at_level(logging.INFO):
        rc = ia.main(["jsonl", "--input", str(src), "--output", str(out), "--spacy-model", "blank:en",
                      "--n-process", "1"])
    assert rc == 0
    messages = [record.getMessage() for record in caplog.records]
    assert "Loading spaCy pipeline: blank:en" in messages
    assert any(message.startswith("Tokens total: ") for message in messages)
    assert f"Done: {out}" in messages
    assert [message for message in messages if GERMAN.search(message)] == []


def test_disk_space_check_prints_the_english_message(tmp_path, monkeypatch):
    src = tmp_path / "c.csv"
    src.write_text("id,text\n1,alpha beta.\n")
    message = lt("Wenig freier Speicher (synthetisch).", "Low free disk space (synthetic).")
    monkeypatch.setattr(
        ia, "check_disk_space", lambda *_a, **_k: {"status": "fail", "blocking": True, "message": message}
    )
    with pytest.raises(SystemExit) as excinfo:
        ia.main(["csv", "--input", str(src), "--output", str(tmp_path / "idx")])
    assert str(excinfo.value) == "The disk space check blocks the import: Low free disk space (synthetic)."


def test_migrate_project_error_is_english(tmp_path, monkeypatch):
    from candyconc.entrypoints import cli

    missing = tmp_path / "missing.ccproj"
    monkeypatch.setattr(sys, "argv", ["candy", "migrate-project", str(missing)])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert str(excinfo.value) == f"Project file not found: {missing.resolve()}"


def test_start_banner_and_paths_say_catalog(tmp_path, monkeypatch, capsys):
    """The start banner said "active in the catalogue", documentation and interface "catalog"."""
    from types import SimpleNamespace

    from candyconc.domain import corpus as corpus_mod
    from candyconc.entrypoints import cli

    monkeypatch.delenv("CANDYCONC_INDEX_PATH", raising=False)
    monkeypatch.setattr(cli, "load_settings", lambda: SimpleNamespace(index_dir=None))
    monkeypatch.setattr(corpus_mod.CorpusRegistry, "load", classmethod(lambda cls: SimpleNamespace(active=str(tmp_path))))
    monkeypatch.setattr(cli, "has_index", lambda _path: True)
    assert cli._startup_corpus_text() == f"{tmp_path} (active in the catalog)"

    cli._print_paths()
    printed = capsys.readouterr().out
    assert "corpus catalog " in printed
    assert "catalogue" not in printed
