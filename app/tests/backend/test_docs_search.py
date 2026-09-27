"""The documentation search reads the manual that the installation ships.

``documentation_search`` read ``app/docs`` next to the source tree, a folder
an installed package does not have. The search now reads the directory that
``/docs/`` serves: the packaged Sphinx build (``candyconc/docs_html``) or
``CANDYCONC_DOCS_DIST``. The tests build that directory in ``tmp_path`` and
make no assumption about a source tree.
"""

from __future__ import annotations

from pathlib import Path

from candyconc.services.backend import docs_search, docs_static


def _sphinx_build(root: Path, *, sources: bool = True) -> Path:
    root.mkdir(parents=True)
    (root / "index.html").write_text("<html><main><p>Start</p></main></html>", encoding="utf-8")
    (root / "guides").mkdir()
    (root / "guides" / "collocations.html").write_text(
        "<html><head><style>.x{}</style></head><body><nav>logDice menu</nav>"
        "<main><h1>Collocations</h1><p>Sort by <em>logDice</em> to rank the"
        " collocates of a node.</p></main></body></html>",
        encoding="utf-8",
    )
    (root / "genindex.html").write_text("<main>logDice index</main>", encoding="utf-8")
    (root / "_static").mkdir()
    (root / "_static" / "notes.html").write_text("<main>logDice asset</main>", encoding="utf-8")
    if sources:
        (root / "_sources" / "guides").mkdir(parents=True)
        (root / "_sources" / "guides" / "collocations.md.txt").write_text(
            "# Collocations\n\nSort by logDice to rank the collocates\nof a node.\n",
            encoding="utf-8",
        )
        (root / "_sources" / "index.md.txt").write_text("# Start\n", encoding="utf-8")
    return root


def test_packaged_build_is_searched_through_its_page_sources(tmp_path, monkeypatch):
    packaged = _sphinx_build(tmp_path / "site-packages" / "candyconc" / "docs_html")
    monkeypatch.delenv(docs_static.DOCS_DIST_ENV, raising=False)
    monkeypatch.setattr(docs_static, "packaged_docs_dir", lambda: packaged)

    result = docs_search.search_documentation("LOGDICE", top_n=5, snippet=20)

    assert result["status"] == "success"
    assert [row["file"] for row in result["rows"]] == ["guides/collocations.md"]
    snippet = result["rows"][0]["snippet"]
    assert "Sort by logDice to rank" in snippet
    assert "\n" not in snippet


def test_build_without_sources_is_read_from_the_page_text(tmp_path, monkeypatch):
    dist = _sphinx_build(tmp_path / "html", sources=False)
    monkeypatch.setenv(docs_static.DOCS_DIST_ENV, str(dist))

    rows = docs_search.search_documentation("logDice", top_n=5, snippet=12)["rows"]

    # Only the page content counts: no navigation, no generated index, no assets.
    assert [row["file"] for row in rows] == ["guides/collocations.html"]
    assert "Sort by logDice to rank" in rows[0]["snippet"]
    assert "menu" not in rows[0]["snippet"] and "<" not in rows[0]["snippet"]


def test_top_n_and_empty_term(tmp_path, monkeypatch):
    dist = _sphinx_build(tmp_path / "html")
    monkeypatch.setenv(docs_static.DOCS_DIST_ENV, str(dist))
    assert docs_search.search_documentation("", top_n=5)["rows"] == []
    assert docs_search.search_documentation("logDice", top_n=0)["rows"] == []
    assert docs_search.search_documentation("no such phrase")["rows"] == []


def test_missing_documentation_is_reported_not_answered_with_no_hits(tmp_path, monkeypatch):
    monkeypatch.setenv(docs_static.DOCS_DIST_ENV, str(tmp_path / "missing"))
    monkeypatch.setattr(docs_search, "_source_docs_dir", lambda: None)

    result = docs_search.search_documentation("logDice")

    assert result == {"status": "unavailable", "rows": []}


def test_source_fallback_only_accepts_the_checkout_layouts(tmp_path, monkeypatch):
    """An installed copy inside another project does not search that project's docs."""
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "conf.py").write_text("", encoding="utf-8")
    (project / "docs" / "index.md").write_text("# Other project\n", encoding="utf-8")
    module = project / ".venv" / "lib" / "python3.12" / "site-packages" / "candyconc" / "services" / "backend" / "docs_search.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(docs_search, "__file__", str(module))
    assert docs_search._source_docs_dir() is None
