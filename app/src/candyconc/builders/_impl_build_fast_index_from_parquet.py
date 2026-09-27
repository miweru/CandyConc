"""In-process seam for the Parquet Fast-Index builder.

``candyconc.builders._runner`` imports this module by dotted name and calls
:func:`main` in-process. The implementation is
:mod:`candyconc.ingest.build_fast_index_from_parquet`.
"""

from __future__ import annotations

import importlib


def _impl_module():
    return importlib.import_module("candyconc.ingest.build_fast_index_from_parquet")


def main(argv: list[str] | None = None) -> int:
    """Run the parquet builder in-process with ``argv`` and return its exit code."""

    return int(_impl_module().main(argv) or 0)


# Re-export the library function for callers that prefer the API over CLI argv.
# Resolved lazily to keep import cheap and spaCy-free until invoked.
def build_fast_index_from_parquet(*args, **kwargs):  # noqa: D401 - thin re-export
    return _impl_module().build_fast_index_from_parquet(*args, **kwargs)


if __name__ == "__main__":  # pragma: no cover - exec path
    raise SystemExit(main())
