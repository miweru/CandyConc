"""In-process seam for the multi-format ingest adapters.

``candyconc.builders._runner`` imports this module by dotted name and calls
:func:`main` in-process for the plaintext / csv / jsonl / hf and prealigned-*
subcommands. The implementation is :mod:`candyconc.ingest.ingest_adapters`.
"""

from __future__ import annotations

import importlib


def _impl_module():
    return importlib.import_module("candyconc.ingest.ingest_adapters")


def main(argv: list[str] | None = None) -> int:
    """Run the ingest adapters CLI in-process with ``argv`` and return its exit code."""

    return int(_impl_module().main(argv) or 0)


if __name__ == "__main__":  # pragma: no cover - exec path
    raise SystemExit(main())
