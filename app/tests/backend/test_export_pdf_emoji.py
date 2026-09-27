"""EXPORT-01: PDF export must not crash on emoji / non-BMP codepoints.

On the shipped social-media bench corpus, KWIC/markdown content routinely
contains emoji (e.g. U+1F602 😂). pdflatex — pandoc's default engine — is not
Unicode-capable and aborts, which previously surfaced as an unhandled HTTP 500.

The fix prefers a Unicode-capable PDF engine (xelatex > lualatex > pdflatex);
when only pdflatex is available, emoji are sanitized to a visible placeholder so
content is preserved rather than crashing. A genuine conversion failure now
surfaces honestly as a 502, never a masked 500.
"""

from __future__ import annotations

import shutil
import warnings

import pytest
from fastapi.testclient import TestClient

from candyconc.services.backend import server
from candyconc.services.backend.routes import exports

warnings.filterwarnings("ignore")

EMOJI_MD = "# Test \U0001F602\n\nKWIC Treffer mit Emoji \U0001F602 und Symbol ✓.\n"

_HAS_LATEX = any(shutil.which(e) for e in ("xelatex", "lualatex", "pdflatex"))
pytestmark = pytest.mark.skipif(
    not (shutil.which("pandoc") and _HAS_LATEX),
    reason="pandoc + a LaTeX engine required for real PDF export",
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(server.app, raise_server_exceptions=False)


def test_pdf_export_with_emoji_returns_valid_pdf(client: TestClient) -> None:
    """Emoji content yields HTTP 200 and a real %PDF body (was 500 before)."""
    resp = client.post("/api/v1/export/pdf", json={"markdown": EMOJI_MD})
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"%PDF"


def test_docx_export_with_emoji_still_works(client: TestClient) -> None:
    """The sibling DOCX export of the same emoji markdown is unaffected."""
    resp = client.post("/api/v1/export/docx", json={"markdown": EMOJI_MD})
    assert resp.status_code == 200, resp.text
    assert resp.content[:2] == b"PK"  # zip / OOXML container


def test_pdf_engine_prefers_unicode_capable_engine() -> None:
    """When xelatex/lualatex exist they win over pdflatex."""
    exports._pdf_engine.cache_clear()
    engine = exports._pdf_engine()
    if shutil.which("xelatex"):
        assert engine == "xelatex"
    elif shutil.which("lualatex"):
        assert engine == "lualatex"
    else:
        assert engine == "pdflatex"


def test_pdflatex_fallback_sanitizes_emoji_to_visible_marker() -> None:
    """Non-BMP codepoints become a visible bracketed marker; BMP is kept."""
    out = exports._sanitize_for_pdflatex("a\U0001F602b✓")
    assert out == "a[U+1F602]b✓"
