"""The copilot tool documentation_search reads the shipped manual.

It read ``app/docs`` next to the source tree (``_get_docs_dir``), a folder an
installed package does not have. With the documentation built into
``CANDYCONC_DOCS_DIST`` the tool must find its pages.
"""

from __future__ import annotations

from candyconc.services.backend import docs_static
from tests.ai.test_tool_wrappers_parity_r5 import _TW as tw


def test_tool_reads_the_served_documentation(tmp_path, monkeypatch):
    dist = tmp_path / "html"
    (dist / "_sources" / "guides").mkdir(parents=True)
    (dist / "index.html").write_text("<main>Start</main>", encoding="utf-8")
    (dist / "_sources" / "guides" / "collocations.md.txt").write_text(
        "# Collocations\n\nSort by logDice to rank the collocates.\n", encoding="utf-8"
    )
    monkeypatch.setenv(docs_static.DOCS_DIST_ENV, str(dist))

    result = tw.documentation_search_tool("logDice", top_n=5, snippet=20)

    assert result["status"] == "success"
    assert [row["file"] for row in result["rows"]] == ["guides/collocations.md"]
