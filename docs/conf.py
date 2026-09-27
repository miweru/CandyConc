"""Sphinx configuration for the CandyConc documentation.

The build does not import ``candyconc``. Everything that comes from the code
is read as text (the version) or from checked-in data files under ``_data``.
Build commands and maintenance rules: ``contribute/documentation.md``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS_DIR / "_ext"))


def _package_version() -> str:
    """Read the version from ``[project]`` in ``app/pyproject.toml`` without importing CandyConc.

    The documentation lives in ``docs/`` next to ``app/`` in the published
    repository and in ``repo_root/docs`` next to ``app`` in the development
    tree, so both relative locations are tried.
    """
    override = os.environ.get("CANDYCONC_DOCS_VERSION", "").strip()
    if override:
        return override
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10, only when the tests load this file
        import tomli as tomllib

    for candidate in (DOCS_DIR.parent / "app" / "pyproject.toml", DOCS_DIR.parent.parent / "app" / "pyproject.toml"):
        if candidate.is_file():
            project = tomllib.loads(candidate.read_text(encoding="utf-8")).get("project", {})
            if project.get("name") == "candyconc" and project.get("version"):
                return str(project["version"])
    return "unknown"


def _git_commit() -> str:
    override = os.environ.get("CANDYCONC_DOCS_COMMIT", "").strip()
    if override:
        return override
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=DOCS_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


project = "CandyConc"
author = "Michael Ruppert"
copyright = "2026, Michael Ruppert"
release = _package_version()
version = release
commit = _git_commit()

language = "en"
root_doc = "index"

extensions = [
    "myst_parser",
    "sphinx.ext.mathjax",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxcontrib.mermaid",
    "candyconc_docs",
]

source_suffix = {".md": "markdown"}
# "**/screenshots": the figures copy each screenshot they show to _images. The
# pattern keeps html_static_path from copying _static/screenshots a second
# time, because the built manual ships in the wheel.
exclude_patterns = [
    "_build",
    "_tools",
    "_data",
    "**/_generated",
    "**/screenshots",
    "README.md",
    "Thumbs.db",
    ".DS_Store",
]
templates_path = ["_templates"]

# Warnings are errors in the documented build (-W -n). Every internal target
# must resolve.
nitpicky = True
# Sphinx turns -- and --- into dashes. The house style forbids both, so the
# conversion stays off and the prose check reports any dash that is typed.
smartquotes = False

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "attrs_inline",
    "dollarmath",
    "fieldlist",
]
myst_heading_anchors = 3

# HTML output
html_theme = "pydata_sphinx_theme"
html_title = f"CandyConc {release}"
html_static_path = ["_static"]
html_css_files = ["candyconc.css"]
html_last_updated_fmt = None
html_show_sourcelink = True
html_copy_source = True
html_search_language = "en"
html_context = {"candyconc_commit": commit, "candyconc_version": release, "default_mode": "auto"}

html_theme_options = {
    "navbar_align": "left",
    "show_toc_level": 2,
    "navigation_depth": 3,
    "header_links_before_dropdown": 8,
    "footer_start": ["copyright"],
    "footer_center": ["candyconc-version"],
    "footer_end": ["theme-version"],
    "secondary_sidebar_items": ["page-toc", "sourcelink"],
    "navbar_persistent": ["search-button"],
    "use_edit_page_button": False,
}

# Diagrams render in the browser from a copy of Mermaid that ships with the
# documentation. _ext/candyconc_docs.py replaces the loader of
# sphinxcontrib-mermaid, so nothing is loaded from a CDN and the pages also
# work when opened from the file system.
mermaid_version = ""
mermaid_include_elk = False
mermaid_d3_zoom = False
mermaid_fullscreen = False

# Formulas render with a local copy of MathJax 3 (SVG output, no web fonts).
mathjax_path = "mathjax/tex-svg.js"
mathjax3_config = {
    "loader": {"load": []},
    "tex": {"inlineMath": [["\\(", "\\)"]], "displayMath": [["\\[", "\\]"]]},
    "svg": {"fontCache": "global"},
}

# Copy button: strip shell prompts and never copy output lines.
copybutton_prompt_text = r"\$ |>>> |\.\.\. "
copybutton_prompt_is_regexp = True
copybutton_only_copy_prompt_lines = False

# Link check. Exceptions, each with its reason:
# - 127.0.0.1 and localhost: the address of a local CandyConc server, not a
#   web page.
# - doi.org: the resolver forwards to publisher pages, and several publishers
#   (Oxford Academic, Taylor & Francis, John Benjamins, SAGE, Wiley) answer
#   automated requests with 403. The DOIs in the bibliography were checked
#   against Crossref when the bibliography was written.
# - github.com/miweru/CandyConc: the repository of CandyConc itself (source,
#   releases, issues). It answers 404 to anonymous requests while it is
#   private. Check these links by hand once the repository is public.
linkcheck_ignore = [
    r"http://127\.0\.0\.1(:\d+)?(/.*)?",
    r"http://localhost(:\d+)?(/.*)?",
    r"https://doi\.org/.*",
    r"https://github\.com/miweru/CandyConc(/.*)?",
]
# eprints.lancs.ac.uk answered after 33.6 s on 2026-09-27, so 30 s failed a
# working link. The timeout is a failsafe far above that.
linkcheck_timeout = 120
linkcheck_retries = 2
