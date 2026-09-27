"""Legacy .ccproj files require an explicit, non-mutating migration step."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from candyconc.project import (
    Project,
    ProjectMigrationError,
    ProjectMigrationRequired,
    _SQLITE_MAGIC,
    prepare_project_migration,
    project_inventory,
    write_migrated_project,
)


def _build_legacy_sqlite(path: Path) -> None:
    """Write a representative historical project database for migration tests."""
    conn = sqlite3.connect(str(path))
    try:
        with conn:
            conn.execute(
                "CREATE TABLE subcorpora "
                "(name TEXT PRIMARY KEY, query TEXT, filter TEXT, "
                "created_at TEXT, creator TEXT)"
            )
            conn.executemany(
                "INSERT INTO subcorpora(name, query, filter, created_at, creator) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    ("news2024", "Leute", "register=social", "2024-01-01T00:00:00", "alice"),
                    ("drama", "Liebe", "", "2024-02-02T00:00:00", "bob"),
                ],
            )
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("theme", "dark"))
            conn.execute("CREATE TABLE project (description TEXT)")
            conn.execute("INSERT INTO project(description) VALUES (?)", ("legacy project",))
            conn.execute(
                "CREATE TABLE bookmarks "
                "(left TEXT, kw TEXT, right TEXT, note TEXT, UNIQUE(left, kw, right))"
            )
            conn.execute(
                "INSERT INTO bookmarks(left, kw, right, note) VALUES (?, ?, ?, ?)",
                ("L", "K", "R", "noted"),
            )
            conn.execute("CREATE TABLE filter_state (corpus TEXT PRIMARY KEY, state TEXT)")
            conn.execute(
                "INSERT INTO filter_state(corpus, state) VALUES (?, ?)",
                ("default", json.dumps({"register": "social"})),
            )
            conn.execute("CREATE TABLE metrics (query TEXT, hits INTEGER)")
            conn.execute("INSERT INTO metrics(query, hits) VALUES (?, ?)", ("Leute", 42))
    finally:
        conn.close()


def test_regular_open_rejects_legacy_sqlite_without_touching_source(tmp_path: Path):
    path = tmp_path / "proj.ccproj"
    _build_legacy_sqlite(path)
    before = path.read_bytes()
    assert before.startswith(_SQLITE_MAGIC)

    with pytest.raises(ProjectMigrationRequired, match="migrate-project"):
        Project(path)

    assert path.read_bytes() == before
    assert not path.with_suffix(".ccproj.sqlite.bak").exists()


def test_backend_turns_required_project_migration_into_clear_503(monkeypatch, tmp_path: Path):
    from fastapi import HTTPException
    from candyconc.services.backend import server

    path = tmp_path / "proj.ccproj"
    _build_legacy_sqlite(path)
    before = path.read_bytes()
    monkeypatch.setattr(server, "_PROJECT_STORE", None)
    monkeypatch.setattr(
        server,
        "get_config",
        lambda key, default=None: str(path) if key == "CANDYCONC_PROJECT_FILE" else default,
    )

    with pytest.raises(HTTPException) as exc_info:
        server._get_project()

    assert exc_info.value.status_code == 503
    assert "migrate-project" in str(exc_info.value.detail)
    assert path.read_bytes() == before


def test_explicit_migration_writes_new_json_and_preserves_inventory(tmp_path: Path):
    source = tmp_path / "legacy.ccproj"
    target = tmp_path / "legacy.migrated.ccproj"
    _build_legacy_sqlite(source)
    before = source.read_bytes()

    data = prepare_project_migration(source)
    assert project_inventory(data) == {
        "bookmarks": 1,
        "annotations": 0,
        "comments": 0,
        "timeline": 0,
        "metrics": 1,
        "subcorpora": 2,
        "filter_state": 1,
        "settings": 1,
        "ai_outputs": 0,
        "macros": 0,
        "jobs": 0,
        "span_annotations": 0,
        "annotation_progress": 0,
        "row_annotations": 0,
        "coding_categories": 0,
    }
    write_migrated_project(target, data)

    assert source.read_bytes() == before
    assert not target.read_bytes().startswith(_SQLITE_MAGIC)
    project = Project(target)
    assert {item["name"] for item in project.subcorpora()} == {"news2024", "drama"}
    assert project.get_setting("theme") == "dark"
    assert project.get_description() == "legacy project"
    assert len(project.bookmarks()) == 1
    assert project.get_filter_state("default") == {"register": "social"}
    assert int(project.metrics()["hits"].iloc[0]) == 42

    migrated_before_reopen = target.read_bytes()
    Project(target)
    assert target.read_bytes() == migrated_before_reopen


def test_migration_refuses_unknown_sqlite_tables_without_writing(tmp_path: Path):
    source = tmp_path / "legacy.ccproj"
    _build_legacy_sqlite(source)
    conn = sqlite3.connect(str(source))
    try:
        conn.execute("CREATE TABLE researcher_notes (body TEXT)")
        conn.execute("INSERT INTO researcher_notes(body) VALUES ('keep me')")
        conn.commit()
    finally:
        conn.close()
    before = source.read_bytes()

    with pytest.raises(ProjectMigrationError, match="unbekannte Tabellen"):
        prepare_project_migration(source)

    assert source.read_bytes() == before


def test_cli_defaults_to_dry_run_and_requires_backup_for_in_place(monkeypatch, tmp_path, capsys):
    from candyconc.entrypoints import cli

    source = tmp_path / "legacy.ccproj"
    _build_legacy_sqlite(source)
    before = source.read_bytes()

    monkeypatch.setattr(sys, "argv", ["candy", "migrate-project", str(source)])
    cli.main()
    assert "Dry run passed" in capsys.readouterr().out
    assert source.read_bytes() == before

    monkeypatch.setattr(sys, "argv", ["candy", "migrate-project", str(source), "--in-place"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 2
    assert "--in-place needs an explicit --backup path" in capsys.readouterr().err
    assert source.read_bytes() == before


def test_cli_writes_only_explicit_new_destination(monkeypatch, tmp_path):
    from candyconc.entrypoints import cli

    source = tmp_path / "legacy.ccproj"
    target = tmp_path / "legacy.migrated.ccproj"
    _build_legacy_sqlite(source)
    before = source.read_bytes()

    monkeypatch.setattr(
        sys,
        "argv",
        ["candy", "migrate-project", str(source), "--output", str(target)],
    )
    cli.main()

    assert source.read_bytes() == before
    assert not target.read_bytes().startswith(_SQLITE_MAGIC)
    assert {item["name"] for item in Project(target).subcorpora()} == {"news2024", "drama"}


def test_cli_in_place_creates_required_backup_before_replacing_source(monkeypatch, tmp_path):
    from candyconc.entrypoints import cli

    source = tmp_path / "legacy.ccproj"
    backup = tmp_path / "legacy.original.ccproj"
    _build_legacy_sqlite(source)
    before = source.read_bytes()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "candy",
            "migrate-project",
            str(source),
            "--in-place",
            "--backup",
            str(backup),
        ],
    )
    cli.main()

    assert backup.read_bytes() == before
    assert not source.read_bytes().startswith(_SQLITE_MAGIC)
    assert {item["name"] for item in Project(source).subcorpora()} == {"news2024", "drama"}
