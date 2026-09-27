"""The rendered HTML of the documentation: page title and footer.

These tests build a one-page project with the real ``docs/conf.py``, its
templates, the local extension and the theme. They need the pinned Sphinx
toolchain of ``docs/requirements.txt`` in a separate environment, found like
``packaging/build_web.py`` finds it (``CANDYCONC_DOCS_PYTHON``, ``.venv-docs``
in the repository root, or this Python). Without it they are skipped.
"""

from __future__ import annotations

import html
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]
CANDIDATES = (APP.parent / "docs", APP.parent / "repo_root" / "docs")
DOCS = next((path for path in CANDIDATES if (path / "conf.py").is_file()), None)


def _docs_python() -> str | None:
    for parent in APP.parents:
        for script in (parent / "packaging" / "build_web.py", parent / "repo_root" / "packaging" / "build_web.py"):
            if script.is_file():
                spec = importlib.util.spec_from_file_location("candyconc_build_web_for_docs_tests", script)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                return module.find_docs_python(script.parents[1], None)
    return None


DOCS_PYTHON = _docs_python() if DOCS is not None else None

pytestmark = pytest.mark.skipif(DOCS_PYTHON is None, reason="Sphinx toolchain of docs/requirements.txt not found")


def _build(tmp_path: Path, *extra: str, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess, Path]:
    src = tmp_path / "src"
    src.mkdir()
    (src / "index.md").write_text("# Getting started\n\nImport a corpus and search it.\n", encoding="utf-8")
    out = tmp_path / "html"
    result = subprocess.run(
        [DOCS_PYTHON, "-m", "sphinx", "-W", "-n", "-q", "-b", "html", "-c", str(DOCS), *extra, str(src), str(out)],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        timeout=600,
    )
    return result, out


def _title(page: Path) -> str:
    return html.unescape(re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8"), re.S).group(1))


def _footer(page: Path) -> str:
    match = re.search(r'<p class="candyconc-version">(.*?)</p>', page.read_text(encoding="utf-8"), re.S)
    return html.unescape(match.group(1)).strip()


def test_page_title_separator_is_no_dash(tmp_path):
    """The basic theme joined page and project title with an em dash (RC0 report, B6)."""
    result, out = _build(tmp_path, env={"CANDYCONC_DOCS_VERSION": "9.9.9"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _title(out / "index.html") == "Getting started | CandyConc 9.9.9"
    assert _title(out / "genindex.html") == "Index | CandyConc 9.9.9"
    assert _title(out / "search.html") == "Search | CandyConc 9.9.9"


def test_house_style_check_reads_the_rendered_title(tmp_path):
    """A dash that reaches the title through a template or a setting stops the build."""
    result, _ = _build(tmp_path, "-D", "html_title=CandyConc \u2014 probe")
    assert result.returncode != 0
    assert "house style" in result.stderr and "page title" in result.stderr


def test_footer_names_the_commit_from_the_environment(tmp_path):
    result, out = _build(tmp_path, env={"CANDYCONC_DOCS_COMMIT": "0123456789"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert _footer(out / "index.html").endswith("built from commit 0123456789.")


def test_footer_without_a_known_commit_names_none(tmp_path):
    """Without Git and without CANDYCONC_DOCS_COMMIT the footer said "built from commit unknown" (RC0 report, B5)."""
    env = {"GIT_DIR": str(tmp_path / "no-git"), "CANDYCONC_DOCS_COMMIT": ""}
    result, out = _build(tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    footer = _footer(out / "index.html")
    assert footer.startswith("Documentation for CandyConc ")
    assert "commit" not in footer and "unknown" not in footer
