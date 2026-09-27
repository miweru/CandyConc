"""Packaged launcher for the multi-format ingest adapters.

Run as ``python -m candyconc.builders.ingest_adapters``. The builder runs in-process via
:mod:`candyconc.builders._runner`, the implementation is
:mod:`candyconc.ingest.ingest_adapters`.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from candyconc.builders._runner import main  # noqa: E402

SCRIPT_NAME = "ingest_adapters.py"


def run() -> int:
    return main(SCRIPT_NAME)


if __name__ == "__main__":  # pragma: no cover - exec path
    sys.exit(run())
