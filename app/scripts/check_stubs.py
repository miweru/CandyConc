#!/usr/bin/env python3
"""Fail when stub code is present in src/ files."""

from __future__ import annotations

import re
from pathlib import Path

EXCLUDE_DIRS = {".git", "vendor", "__pycache__"}

PASS_RE = re.compile(r"^\s*pass\s*(?:#.*)?$")
RETURN_RE = re.compile(r"^\s*return\s*\[\s*\]\s*(?:#.*)?$")
TODO_RE = re.compile(r"TODO_IMPLEMENT")


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def scan(root: Path) -> dict[Path, list[int]]:
    matches: dict[Path, list[int]] = {}
    src = root / "src"
    for path in src.rglob("*.py"):
        if not path.is_file() or is_excluded(path):
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        offending_lines: list[int] = []
        for i, line in enumerate(text.splitlines(), 1):
            if PASS_RE.search(line) or RETURN_RE.search(line) or TODO_RE.search(line):
                offending_lines.append(i)
        if offending_lines:
            matches[path] = offending_lines
    return matches


def main() -> int:
    root = Path.cwd()
    matches = scan(root)
    if not matches:
        return 0
    print("Found stubs in files:")
    for path, lines in matches.items():
        joined = ", ".join(map(str, lines))
        print(f" - {path.relative_to(root)}:{joined}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
