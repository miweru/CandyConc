"""Regression test for D2(b) — lexicon truncation guard.

``Lexicon.load`` slices the strings region out of the mmap with
``memoryview(mm)[strings_offset : strings_offset + strings_len]``. If the file
was truncated (incomplete write / corrupted download), that slice (or the
offsets/freqs tables before it) would read past EOF and surface as an opaque
numpy/memoryview error — or silently return garbage. The guard validates
``strings_offset + strings_len <= file_size`` and raises an actionable
RuntimeError instead.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from candyconc.core import index_format
from candyconc.core.lexicon import Lexicon

INDEX_PATH = os.environ.get("CANDYCONC_INDEX_PATH")

pytestmark = pytest.mark.skipif(
    not INDEX_PATH or not Path(INDEX_PATH).exists(),
    reason="CANDYCONC_INDEX_PATH must point at a real Fast Index",
)


def _source_lexicon() -> Path:
    base = Path(INDEX_PATH)
    for name in ("word_lexicon.bin", "lemma_lexicon.bin"):
        p = base / name
        if p.exists() and p.with_suffix(".hash.bin").exists():
            return p
    pytest.skip("no suitable lexicon.bin with sidecars in the bench index")


def _copy_lexicon(src: Path, dst_dir: Path) -> Path:
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    for suffix in (".hash.bin", ".bucket.bin"):
        side = src.with_suffix(suffix)
        if side.exists():
            shutil.copy2(side, dst_dir / side.name)
    return dst


def test_valid_lexicon_loads(tmp_path: Path) -> None:
    src = _source_lexicon()
    copied = _copy_lexicon(src, tmp_path)
    lex = Lexicon.load(copied)
    assert lex.vocab_size > 0


def test_truncated_strings_region_raises(tmp_path: Path) -> None:
    src = _source_lexicon()
    copied = _copy_lexicon(src, tmp_path)

    # Truncate the file so the strings region no longer fits. Drop the last
    # 64 bytes (the tail of the strings blob).
    size = copied.stat().st_size
    assert size > 64
    with open(copied, "r+b") as f:
        f.truncate(size - 64)

    with pytest.raises(RuntimeError, match="Lexikon Daten unvollständig"):
        Lexicon.load(copied)


def test_truncated_before_offsets_raises(tmp_path: Path) -> None:
    """A file cut down to just past the header (offsets/freqs missing) must also
    fail closed rather than producing a partial lexicon."""
    src = _source_lexicon()
    copied = _copy_lexicon(src, tmp_path)

    # Keep only the header + a few bytes; the strings region is far beyond EOF.
    with open(copied, "r+b") as f:
        f.truncate(index_format.LEXICON_HEADER_SIZE + 8)

    with pytest.raises(RuntimeError):
        Lexicon.load(copied)
