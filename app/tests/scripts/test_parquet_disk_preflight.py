"""Konsolidierung: der Parquet-Builder-Preflight nutzt die geteilte Disk-Heuristik.

``scripts/jobs/build_fast_index_from_parquet.py::_preflight_checks`` trug eine
eigene Kopie der Disk-Schätzung. Sie ist durch
``candyconc.utils.disk_preflight.check_disk_space`` ersetzt, mit identischen
Faktoren, identischer Reserve und denselben env-Namen
(CANDYCONC_BUILD_DISK_FACTOR, CANDYCONC_BUILD_DISK_RESERVE_GB,
CANDYCONC_BUILD_ALLOW_LOW_DISK). Diese Tests pinnen das Block-/Warn-Verhalten
über die geteilte Naht: ein Monkeypatch der geteilten ``disk_usage`` MUSS den
Builder-Preflight treffen, sonst wäre die Kopie zurück.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("spacy")
pl = pytest.importorskip("polars")

import scripts.jobs.build_fast_index_from_parquet as build_mod  # noqa: E402
from candyconc.utils import disk_preflight  # noqa: E402

_USAGE = collections.namedtuple("usage", "total used free")


def _preflight(tmp_path: Path) -> dict:
    inp = tmp_path / "in.parquet"
    if not inp.exists():
        pl.DataFrame(
            {"target_text": ["alpha beta gamma"], "input_text": ["alpha"]}
        ).write_parquet(inp)
    return build_mod._preflight_checks(
        input_path=inp,
        output_path=tmp_path / "out",
        spacy_model="blank:de",
        build_embeddings=False,
        build_word_faiss=None,
        build_gemma_embeddings=False,
        export_gemma_texts=False,
        gemma_endpoint=None,
        gemma_model=None,
        gemma_timeout=5.0,
        disable_ner=True,
        disable_deps=True,
        require_input_text=False,
    )


def test_full_disk_blocks_via_shared_heuristic(tmp_path, monkeypatch):
    monkeypatch.setattr(
        disk_preflight.shutil, "disk_usage", lambda _p: _USAGE(100, 90, 10)
    )
    monkeypatch.delenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", raising=False)

    result = _preflight(tmp_path)

    assert any("Speicher" in error for error in result["errors"])
    assert result["ok"] is False
    assert result["details"]["disk_free"] == 10
    assert result["details"]["disk_reserve"] == 5 * 1024**3


def test_allow_low_disk_env_downgrades_block_to_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(
        disk_preflight.shutil, "disk_usage", lambda _p: _USAGE(100, 90, 10)
    )
    monkeypatch.setenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", "1")

    result = _preflight(tmp_path)

    assert not any("Speicher" in error for error in result["errors"])
    assert any("Speicher" in warning for warning in result["warnings"])


def test_plenty_of_disk_passes_without_disk_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        disk_preflight.shutil,
        "disk_usage",
        lambda _p: _USAGE(100 * 1024**3, 0, 100 * 1024**3),
    )
    monkeypatch.delenv("CANDYCONC_BUILD_ALLOW_LOW_DISK", raising=False)

    result = _preflight(tmp_path)

    assert not any("Speicher" in error for error in result["errors"])
    assert not any("Speicher" in warning for warning in result["warnings"])
    assert result["details"]["disk_free"] == 100 * 1024**3
