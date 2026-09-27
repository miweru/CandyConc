#!/usr/bin/env python3
"""Check that the metadata of a source distribution names no path of the build machine.

setuptools lists every source of the package in ``*.egg-info/SOURCES.txt``.
With an absolute Cython build directory the generated C files appeared there
with the full path of the build machine, user name included. This script
fails when a line of ``SOURCES.txt`` or of another ``*.egg-info`` text file is
an absolute path.

Usage::

    python packaging/check_sdist.py dist/candyconc-0.1.0.tar.gz
"""

from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path, PurePosixPath


def absolute_paths(sdist: Path) -> dict[str, list[str]]:
    """Lines that are absolute paths, per egg-info file. Raises if there is no SOURCES.txt."""
    found: dict[str, list[str]] = {}
    seen_sources = False
    with tarfile.open(sdist, "r:gz") as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or not any(part.endswith(".egg-info") for part in path.parts[:-1]):
                continue
            if path.suffix != ".txt":
                continue
            seen_sources = seen_sources or path.name == "SOURCES.txt"
            text = tar.extractfile(member).read().decode("utf-8", errors="replace")
            lines = [line for line in text.splitlines() if line.startswith("/") or line[1:3] == ":\\"]
            if lines:
                found[member.name] = lines
    if not seen_sources:
        raise SystemExit(f"{sdist}: no *.egg-info/SOURCES.txt")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sdist", type=Path, nargs="+")
    args = parser.parse_args(argv)
    status = 0
    for sdist in args.sdist:
        found = absolute_paths(sdist)
        for name, lines in found.items():
            for line in lines:
                print(f"{sdist.name}: {name}: {line}", file=sys.stderr)
        if found:
            status = 1
        else:
            print(f"{sdist.name}: no absolute paths in the egg-info metadata")
    return status


if __name__ == "__main__":
    sys.exit(main())
