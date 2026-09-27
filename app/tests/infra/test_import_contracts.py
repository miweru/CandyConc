"""Check import contracts without changing pytest's logging configuration."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("importlinter")

APP = Path(__file__).resolve().parents[2]


def test_every_import_contract_is_kept():
    subprocess.run(
        [sys.executable, "-c",
         "from importlinter.cli import lint_imports\n"
         "raise SystemExit(lint_imports(config_filename='pyproject.toml', no_cache=True))"],
        cwd=APP,
        check=True,
    )
