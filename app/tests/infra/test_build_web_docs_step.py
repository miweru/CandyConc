"""The optional documentation step of ``packaging/build_web.py`` (erprobung B17).

With the Sphinx toolchain the HTML manual is built with the documented
command and copied into the package (``candyconc/docs_html``), where the
server serves it under ``/docs/``. Without the toolchain the step is skipped
and the package stays as it was.
"""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

import pytest


def _script() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        for candidate in (parent / "packaging" / "build_web.py", parent / "repo_root" / "packaging" / "build_web.py"):
            if candidate.is_file():
                return candidate
    return None


@pytest.fixture(scope="module")
def build_web():
    script = _script()
    if script is None:
        pytest.skip("packaging/build_web.py is not part of this checkout")
    spec = importlib.util.spec_from_file_location("candyconc_build_web", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "conf.py").write_text("project = 'x'\n", encoding="utf-8")
    (docs / "requirements.txt").write_text("sphinx\n", encoding="utf-8")
    return tmp_path


def _fake_sphinx_python(tmp_path: Path) -> Path:
    """A stand-in interpreter: passes the module probe and writes an HTML build."""
    fake = tmp_path / "fake-python"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then exit 0; fi\n'
        '# -m sphinx -W --keep-going -n -b html SRC OUT\n'
        'for last; do :; done\n'
        'mkdir -p "$last/guides" && echo manual > "$last/index.html" && echo guide > "$last/guides/index.html"\n',
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake


def test_without_toolchain_the_step_is_skipped(build_web, repo, monkeypatch, capsys):
    monkeypatch.delenv(build_web.DOCS_PYTHON_ENV, raising=False)
    monkeypatch.setattr(build_web, "has_docs_tools", lambda python: False)
    target = repo / "target"
    assert build_web.build_docs(repo, target, None) is False
    assert not target.exists()
    assert "skipped" in capsys.readouterr().out


def test_with_toolchain_the_manual_is_copied_into_the_package(build_web, repo, tmp_path):
    target = repo / "app" / "src" / "candyconc" / "docs_html"
    target.mkdir(parents=True)
    (target / "stale.html").write_text("old", encoding="utf-8")
    fake = _fake_sphinx_python(tmp_path)
    assert build_web.build_docs(repo, target, str(fake)) is True
    assert (target / "index.html").read_text(encoding="utf-8").strip() == "manual"
    assert (target / "guides" / "index.html").is_file()
    assert not (target / "stale.html").exists()


def test_the_documented_environment_is_found(build_web, repo, tmp_path, monkeypatch):
    monkeypatch.delenv(build_web.DOCS_PYTHON_ENV, raising=False)
    venv_python = repo / ".venv-docs" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(build_web, "has_docs_tools", lambda python: python == str(venv_python))
    assert build_web.find_docs_python(repo, None) == str(venv_python)


def test_release_build_stops_without_toolchain(build_web, repo, monkeypatch):
    """--require-docs: a release must not ship without its manual."""
    monkeypatch.delenv(build_web.DOCS_PYTHON_ENV, raising=False)
    monkeypatch.setattr(build_web, "has_docs_tools", lambda python: False)
    with pytest.raises(SystemExit, match="Sphinx toolchain not found"):
        build_web.build_docs(repo, repo / "target", None, required=True)


def test_release_build_stops_when_the_footer_cannot_name_the_commit(build_web, repo, tmp_path, monkeypatch):
    """Without Git and without CANDYCONC_DOCS_COMMIT every page said "built from commit unknown" (RC0 report, B5)."""
    monkeypatch.setenv(build_web.DOCS_COMMIT_ENV, "")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-git"))
    target = repo / "target"
    with pytest.raises(SystemExit, match=build_web.DOCS_COMMIT_ENV):
        build_web.build_docs(repo, target, str(_fake_sphinx_python(tmp_path)), required=True)
    assert not target.exists()


def test_release_build_takes_the_commit_from_the_environment(build_web, repo, tmp_path, monkeypatch):
    monkeypatch.setenv(build_web.DOCS_COMMIT_ENV, "0123456789")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-git"))
    target = repo / "target"
    assert build_web.build_docs(repo, target, str(_fake_sphinx_python(tmp_path)), required=True) is True
    assert (target / "index.html").is_file()


def test_documentation_zip_has_one_top_folder_named_after_the_version(build_web, repo, tmp_path):
    import zipfile

    app = repo / "app"
    app.mkdir()
    (app / "pyproject.toml").write_text('[project]\nname = "candyconc"\nversion = "9.9.9"\n', encoding="utf-8")
    docs = tmp_path / "docs_html"
    (docs / "guides").mkdir(parents=True)
    (docs / "index.html").write_text("manual", encoding="utf-8")
    (docs / "guides" / "index.html").write_text("guide", encoding="utf-8")

    archive = build_web.zip_docs(repo, docs, tmp_path / "out")

    assert archive.name == "candyconc-9.9.9-docs-html.zip"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == [
            "candyconc-9.9.9-docs-html/guides/index.html",
            "candyconc-9.9.9-docs-html/index.html",
        ]
