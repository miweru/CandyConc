"""Regression tests for the app-audit security fixes (2026-06-08):
path-traversal containment on embedding name + file:// rejection + size cap.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from candyconc.tools import embedding_package as ep  # noqa: E402


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "..", ".", "x/../../y"])
def test_safe_dest_rejects_traversal(bad):
    with pytest.raises(ValueError):
        ep._safe_dest(bad)


def test_safe_dest_allows_plain_name():
    dest = ep._safe_dest("glove_de_300")
    assert dest.name == "glove_de_300.txt"
    assert dest.resolve().is_relative_to(ep.EMB_DIR.resolve())


def test_download_rejects_file_url_by_default():
    with pytest.raises(ValueError, match="file://"):
        asyncio.run(ep.download_embedding("pkg", "file:///etc/passwd", "00"))


def test_download_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        asyncio.run(ep.download_embedding("pkg", "ftp://host/x", "00"))


def test_download_rejects_traversal_name():
    with pytest.raises(ValueError):
        asyncio.run(ep.download_embedding("../evil", "https://h/x", "00"))


def test_file_url_size_cap_enforced(tmp_path, monkeypatch):
    # With allow_file_url and a file over the cap and no confirm -> refused.
    monkeypatch.setattr(ep, "MAX_EMBEDDING_BYTES", 10)
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 100)
    with pytest.raises(RuntimeError, match="Limit"):
        asyncio.run(ep.download_embedding(
            "pkg", f"file://{big}", "00", allow_file_url=True,
        ))


def test_existing_embedding_file_must_match_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "EMB_DIR", tmp_path)
    existing = tmp_path / "pkg.txt"
    existing.write_text("old 0.1 0.2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum"):
        asyncio.run(ep.download_embedding(
            "pkg",
            "https://example.invalid/pkg.txt",
            "0" * 64,
        ))


def test_download_requires_checksum(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "EMB_DIR", tmp_path)
    source = tmp_path / "source.txt"
    source.write_text("fox 0.1 0.2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        asyncio.run(ep.download_embedding(
            "pkg",
            f"file://{source}",
            "",
            allow_file_url=True,
        ))


def test_remove_package_rejects_traversal():
    from candyconc.services import embeddings
    with pytest.raises(ValueError):
        embeddings.remove_package("../../etc/passwd")
