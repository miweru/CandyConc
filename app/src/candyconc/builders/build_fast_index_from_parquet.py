"""Packaged launcher for the Parquet Fast-Index builder.

Run as ``python -m candyconc.builders.build_fast_index_from_parquet``. The
builder runs in-process via :mod:`candyconc.builders._runner`, the
implementation is :mod:`candyconc.ingest.build_fast_index_from_parquet`.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    # Executed as a bare script path (e.g. by find_builder_script + subprocess):
    # ensure the candyconc package root is importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from candyconc.builders._runner import main  # noqa: E402

SCRIPT_NAME = "build_fast_index_from_parquet.py"


def run() -> int:
    return main(SCRIPT_NAME)


if __name__ == "__main__":  # pragma: no cover - exec path
    sys.exit(run())
