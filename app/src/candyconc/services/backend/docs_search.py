"""Full-text search in the user documentation that this installation ships.

The copilot tool ``documentation_search`` read ``app/docs`` next to the
source tree. An installed package has no such folder: the manual is the
Sphinx build in ``candyconc/docs_html`` (see ``docs_static``), and the older
``app/docs`` pages are not part of it.

The search reads the same directory that ``/docs/`` serves
(``docs_static.docs_dist_dir``: ``CANDYCONC_DOCS_DIST``, the packaged build,
a local build). Sphinx copies every page source to ``_sources/<page>.txt``
(``html_copy_source``), so the search reads that Markdown text. A build
without ``_sources`` is read from its HTML pages with the markup removed.
Only a checkout without any build falls back to the Markdown sources of
``docs/`` (a folder with ``conf.py``).

Result rows keep the tool contract ``{file, snippet}``. ``file`` is the page
source path such as ``guides/collocations.md``. Without any documentation
the status is ``unavailable``.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Iterator

from .docs_static import docs_dist_dir

#: Folders of a Sphinx build or source tree that hold no page text.
_SKIPPED_PARTS = frozenset(
    {"_static", "_images", "_downloads", "_templates", "_ext", "_tools", "_data", "_build"}
)
#: Generated pages without own content.
_SKIPPED_PAGES = frozenset({"genindex.html", "search.html", "py-modindex.html"})

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_OR_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_MAIN = re.compile(r"<main\b[^>]*>(.*?)</main>", re.S | re.I)


def _source_docs_dir() -> Path | None:
    """The Markdown sources of the manual in a checkout, if there is one.

    Only the two checkout layouts count: ``<repo>/app/src/candyconc/...``
    with the manual in ``<repo>/docs`` (published repository) and
    ``app/src/...`` with ``repo_root/docs``
    (development tree). No open walk up the parents: an installed package
    inside another project must not search that project's ``docs``.
    """
    parents = Path(__file__).resolve().parents
    if len(parents) <= 5:
        return None
    checkout = parents[5]
    for candidate in (checkout / "docs", checkout / "repo_root" / "docs"):
        if (candidate / "conf.py").is_file() and (candidate / "index.md").is_file():
            return candidate
    return None


def _skipped(relative: Path) -> bool:
    return any(part in _SKIPPED_PARTS for part in relative.parts[:-1])


def _html_text(raw: str) -> str:
    body = _MAIN.search(raw)
    text = body.group(1) if body else raw
    text = _SCRIPT_OR_STYLE.sub(" ", text)
    return html.unescape(_TAG.sub(" ", text))


def documentation_pages() -> Iterator[tuple[str, str]]:
    """``(page path, text)`` for every page of the shipped documentation."""
    dist = docs_dist_dir()
    if dist is not None:
        sources = dist / "_sources"
        if sources.is_dir():
            for path in sorted(sources.rglob("*.txt")):
                relative = path.relative_to(sources)
                yield relative.as_posix()[: -len(".txt")], path.read_text(encoding="utf-8")
            return
        for path in sorted(dist.rglob("*.html")):
            relative = path.relative_to(dist)
            if _skipped(relative) or relative.name in _SKIPPED_PAGES:
                continue
            yield relative.as_posix(), _html_text(path.read_text(encoding="utf-8"))
        return
    source = _source_docs_dir()
    if source is None:
        return
    for path in sorted(source.rglob("*.md")):
        relative = path.relative_to(source)
        if _skipped(relative):
            continue
        yield relative.as_posix(), path.read_text(encoding="utf-8")


def documentation_available() -> bool:
    return docs_dist_dir() is not None or _source_docs_dir() is not None


def search_documentation(term: str, top_n: int = 5, snippet: int = 30) -> dict[str, Any]:
    """Pages that contain ``term`` (case-insensitive), one snippet per page."""
    if not documentation_available():
        # "unavailable", not "success" with no rows: an empty hit list would
        # read as "the manual does not mention the term". The tool response
        # schema declares only status and rows.
        return {"status": "unavailable", "rows": []}
    needle = str(term or "").lower()
    rows: list[dict[str, str]] = []
    if not needle or top_n <= 0:
        return {"status": "success", "rows": rows}
    for page, text in documentation_pages():
        position = text.lower().find(needle)
        if position == -1:
            continue
        start = max(0, position - snippet)
        end = min(len(text), position + len(needle) + snippet)
        rows.append({"file": page, "snippet": " ".join(text[start:end].split())})
        if len(rows) >= top_n:
            break
    return {"status": "success", "rows": rows}
