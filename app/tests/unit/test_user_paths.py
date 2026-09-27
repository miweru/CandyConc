"""User data directory and configuration file locations.

Before: the project file and project configuration were resolved against the
working directory the server was started from (``proj.ccproj``,
``config/projects``), the server created ``.tmp/candyconc`` there, and embedding
packages were written into the installed package.
"""

from __future__ import annotations

from pathlib import Path

from candyconc import paths


def test_data_dir_defaults_to_dot_candyconc(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert paths.data_dir() == Path.home() / ".candyconc"


def test_candyconc_home_moves_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    assert paths.data_dir() == tmp_path / "data"
    assert paths.corpora_dir() == tmp_path / "data" / "corpora"
    assert paths.tmp_dir() == tmp_path / "data" / "tmp"


def test_config_file_env_and_platform_default(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.CONFIG_FILE_ENV, str(tmp_path / "c.toml"))
    assert paths.config_file() == tmp_path / "c.toml"
    monkeypatch.delenv(paths.CONFIG_FILE_ENV)
    from platformdirs import user_config_path

    assert paths.config_file() == user_config_path("candyconc", appauthor=False) / "config.toml"


def test_project_file_prefers_explicit_then_working_dir_then_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert paths.project_file(None) == tmp_path / "data" / "proj.ccproj"
    (work / "proj.ccproj").write_text("{}", encoding="utf-8")
    assert paths.project_file(None) == Path("proj.ccproj")
    assert paths.project_file("~/custom.ccproj") == Path.home() / "custom.ccproj"


def test_projects_dir_keeps_an_existing_working_dir_config(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    assert paths.projects_dir(None) == tmp_path / "data" / "projects"
    (tmp_path / "config" / "projects").mkdir(parents=True)
    assert paths.projects_dir(None) == Path("config") / "projects"


def test_embedding_packages_are_not_written_into_the_package():
    import candyconc
    from candyconc.tools import embedding_package

    package_dir = Path(candyconc.__file__).resolve().parent
    assert package_dir not in embedding_package.EMB_DIR.resolve().parents


def test_token_estimate_needs_no_network():
    from candyconc.services.llm_client import token_len

    assert token_len([{"role": "user", "content": "one two three"}]) == 4
