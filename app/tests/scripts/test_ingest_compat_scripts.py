"""The old builder script paths keep working after the move into the package.

``scripts/jobs/<builder>.py`` and ``scripts/build_fast_index.py`` are thin
entry points. Importing them yields the packaged module object itself, so
private helpers, monkeypatching and ``python scripts/jobs/<builder>.py`` keep
their behaviour for research scripts that use these paths.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]


def _repo_root() -> Path | None:
    for parent in APP_ROOT.parents:
        if (parent / "scripts" / "jobs" / "ingest_adapters.py").is_file():
            return parent
    return None


REPO_ROOT = _repo_root()
pytestmark = pytest.mark.skipif(REPO_ROOT is None, reason="checkout without scripts/jobs")

MODULES = [
    ("scripts.build_fast_index", "candyconc.ingest.build_fast_index"),
    ("scripts.jobs.build_fast_index_from_parquet", "candyconc.ingest.build_fast_index_from_parquet"),
    ("scripts.jobs.ingest_adapters", "candyconc.ingest.ingest_adapters"),
    ("scripts.jobs.build_fast_index_from_vrt", "candyconc.ingest.build_fast_index_from_vrt"),
    ("scripts.jobs.cwb_decode_to_vrt", "candyconc.ingest.cwb_decode_to_vrt"),
]


@pytest.mark.parametrize("old,new", MODULES)
def test_old_module_path_is_the_packaged_module(monkeypatch, old: str, new: str):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    assert importlib.import_module(old) is importlib.import_module(new)


def test_private_helpers_stay_importable_from_the_old_path(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    from scripts.build_fast_index import _write_lexicon_bin  # noqa: F401
    from scripts.jobs.build_fast_index_from_parquet import _preflight_checks  # noqa: F401


@pytest.mark.parametrize(
    "script",
    [
        "scripts/jobs/build_fast_index_from_parquet.py",
        "scripts/jobs/ingest_adapters.py",
        "scripts/jobs/build_fast_index_from_vrt.py",
        "scripts/jobs/cwb_decode_to_vrt.py",
    ],
)
def test_old_script_path_runs(script: str):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / script), "--help"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
