"""Local Sphinx extension for the CandyConc documentation.

It does four things:

1. Renders Mermaid diagrams with the vendored Mermaid build
   (``_static/mermaid/mermaid.min.js``) and a small classic script
   (``_static/mermaid/candyconc-mermaid.js``) on pages that contain a diagram.
   The page hook of ``sphinxcontrib-mermaid`` is removed, because it imports
   Mermaid as an ES module, and browsers block module imports on pages opened
   from the file system. No page loads a script from another host.
2. Checks the prose of every page for em dashes, en dashes, double hyphens and
   semicolons outside code and formulas (house style), and after the build the
   rendered ``<title>`` of every page, which templates and settings compose.
   A finding is a Sphinx warning, and the documented build treats warnings as
   errors.
3. ``query-example`` directive: renders a query from ``_data/query_examples.json``
   together with the result recorded on a sample corpus. The same file is
   checked against a running server by ``_tools/check_query_examples.py``.
4. ``example-table`` directive: renders a table from
   ``_data/worked_examples.json``. The same file is checked by
   ``_tools/check_worked_examples.py``, which recomputes every value
   independently and compares it with a running server.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "_data"
QUERY_EXAMPLES = DATA_DIR / "query_examples.json"
WORKED_EXAMPLES = DATA_DIR / "worked_examples.json"


# --------------------------------------------------------------------------
# 1. Mermaid from the local copy
# --------------------------------------------------------------------------


def _add_local_mermaid(app: Sphinx, pagename: str, templatename: str, context: dict, doctree) -> None:
    if doctree is None:
        return
    try:
        from sphinxcontrib.mermaid import mermaid as mermaid_node
    except ImportError:  # pragma: no cover - the extension is a requirement
        return
    if doctree.next_node(mermaid_node) is None:
        return
    app.add_js_file("mermaid/mermaid.min.js", priority=400)
    app.add_js_file("mermaid/candyconc-mermaid.js", priority=401)


def _replace_mermaid_loader(app: Sphinx) -> None:
    """Remove the page hook of sphinxcontrib-mermaid that adds its module loader."""
    listeners = app.events.listeners.get("html-page-context", [])
    for listener in list(listeners):
        handler = listener.handler
        if getattr(handler, "__module__", "") == "sphinxcontrib.mermaid" and handler.__name__ == "install_js":
            app.disconnect(listener.id)


# --------------------------------------------------------------------------
# 2. Prose check
# --------------------------------------------------------------------------

_FORBIDDEN = {
    "—": "em dash",
    "–": "en dash",
    ";": "semicolon",
}


def _skip(node: nodes.Node) -> bool:
    try:
        from sphinxcontrib.mermaid import mermaid as mermaid_node
    except ImportError:  # pragma: no cover
        mermaid_node = ()
    skip_types = (
        nodes.literal_block,
        nodes.literal,
        nodes.math,
        nodes.math_block,
        nodes.raw,
        nodes.comment,
        nodes.system_message,
        nodes.doctest_block,
    )
    parent = node.parent
    while parent is not None:
        if isinstance(parent, skip_types) or (mermaid_node and isinstance(parent, mermaid_node)):
            return True
        parent = parent.parent
    return False


def _check_prose(app: Sphinx, doctree: nodes.document, docname: str) -> None:
    for text in doctree.findall(nodes.Text):
        if _skip(text):
            continue
        value = str(text)
        problems = [label for char, label in _FORBIDDEN.items() if char in value]
        if "--" in value:
            problems.append("double hyphen")
        if problems:
            snippet = value.strip().replace("\n", " ")
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            logger.warning(
                "house style: %s in prose: %r",
                ", ".join(problems),
                snippet,
                location=text.parent if text.parent is not None else docname,
                type="candyconc",
                subtype="prose",
            )


_TITLE = re.compile(r"<title>(.*?)</title>", re.S)


def _title_problems(title: str) -> list[str]:
    problems = [label for char, label in _FORBIDDEN.items() if char in title]
    if "--" in title:
        problems.append("double hyphen")
    return problems


def _check_titles(app: Sphinx, exception: Exception | None) -> None:
    """Check the ``<title>`` of every written page.

    The doctree check never sees it: the theme joins page title and project
    title in its template (the basic theme with an em dash, RC0 report, B6).
    """
    if exception is not None or app.builder.format != "html":
        return
    outdir = Path(app.outdir)
    pagenames = sorted(app.env.found_docs) + ["genindex", "search"]
    for pagename in pagenames:
        page = outdir / app.builder.get_target_uri(pagename)
        if not page.is_file():
            continue
        match = _TITLE.search(page.read_text(encoding="utf-8"))
        if match is None:
            continue
        title = html.unescape(match.group(1)).strip()
        problems = _title_problems(title)
        if problems:
            logger.warning(
                "house style: %s in the page title: %r",
                ", ".join(problems),
                title,
                location=pagename,
                type="candyconc",
                subtype="title",
            )


# --------------------------------------------------------------------------
# 3. and 4. Data-backed directives
# --------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _fmt(value: Any, spec: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if spec and isinstance(value, (int, float)):
        text = format(value, spec)
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        text = str(value)
    return text


class QueryExample(SphinxDirective):
    """Render one recorded query example.

    Usage::

        ```{query-example} plain-freedom
        ```
    """

    required_arguments = 1
    has_content = False

    def run(self) -> list[nodes.Node]:
        self.env.note_dependency(str(QUERY_EXAMPLES))
        data = _load_json(QUERY_EXAMPLES)
        key = self.arguments[0]
        example = next((item for item in data["examples"] if item["id"] == key), None)
        if example is None:
            raise self.error(f"unknown query example {key!r} in {QUERY_EXAMPLES.name}")
        corpus = data["corpora"][example["corpus"]]

        block = nodes.literal_block(example["query"], example["query"])
        block["language"] = "text"
        block["classes"].append("cc-query")

        result = nodes.paragraph(classes=["cc-query-result"])
        result += nodes.strong(text="Result: ")
        if example["status"] == "ok":
            hits = example["hits"]
            unit = "hit" if hits == 1 else "hits"
            sentence = f"{hits:,} {unit}"
            if example.get("docs") is not None:
                docs = example["docs"]
                sentence += f" in {docs:,} " + ("document" if docs == 1 else "documents")
        else:
            sentence = "rejected with a diagnostic"
        sentence += f" ({corpus['label']})."
        result += nodes.Text(sentence)
        if example.get("note"):
            result += nodes.Text(" " + example["note"])
        return [block, result]


class ExampleTable(SphinxDirective):
    """Render a recorded table of worked-example values.

    Usage::

        ```{example-table} keyness-blog-news
        ```
    """

    required_arguments = 1
    has_content = False
    option_spec = {"class": directives.class_option}

    def run(self) -> list[nodes.Node]:
        self.env.note_dependency(str(WORKED_EXAMPLES))
        data = _load_json(WORKED_EXAMPLES)
        key = self.arguments[0]
        spec = data["tables"].get(key)
        if spec is None:
            raise self.error(f"unknown example table {key!r} in {WORKED_EXAMPLES.name}")
        columns = spec["columns"]
        source = data["tables"][spec["source"]] if spec.get("source") else spec
        if spec.get("from_facts"):
            rows = [source["facts"]]
        else:
            rows = source["rows"]

        table = nodes.table(classes=["cc-example-table"] + self.options.get("class", []))
        tgroup = nodes.tgroup(cols=len(columns))
        table += tgroup
        for _ in columns:
            tgroup += nodes.colspec(colwidth=1)
        thead = nodes.thead()
        tgroup += thead
        header = nodes.row()
        for column in columns:
            entry = nodes.entry()
            entry += nodes.paragraph(text=column["label"])
            header += entry
        thead += header
        tbody = nodes.tbody()
        tgroup += tbody
        for row_data in rows:
            row = nodes.row()
            for column in columns:
                entry = nodes.entry()
                value = row_data.get(column["key"])
                text = _fmt(value, column.get("format", ""))
                para = nodes.paragraph()
                if column.get("code"):
                    para += nodes.literal(text=text)
                else:
                    para += nodes.Text(text)
                entry += para
                row += entry
            tbody += row
        if spec.get("caption"):
            title = nodes.title(text=spec["caption"])
            table.insert(0, title)
        return [table]


def setup(app: Sphinx) -> dict[str, Any]:
    app.connect("builder-inited", _replace_mermaid_loader)
    app.connect("html-page-context", _add_local_mermaid)
    app.connect("doctree-resolved", _check_prose)
    app.connect("build-finished", _check_titles)
    app.add_directive("query-example", QueryExample)
    app.add_directive("example-table", ExampleTable)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
