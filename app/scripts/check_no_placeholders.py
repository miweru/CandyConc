#!/usr/bin/env python3
"""Fail when placeholder demo files are present."""

from __future__ import annotations

from pathlib import Path
import ast

# Maximum file size (bytes) considered a short demo file
MAX_SIZE = 1024

# Directories to ignore during scanning
EXCLUDE_DIRS = {".git", "vendor", "__pycache__"}


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def is_placeholder(path: Path, root: Path) -> bool:
    name = path.name.lower()
    try:
        size = path.stat().st_size
    except OSError:
        return False

    if ("sample" in name or "dummy" in name) and size <= MAX_SIZE:
        return True

    data_dir = root / "tests" / "data"
    try:
        if path.is_relative_to(data_dir) and size <= MAX_SIZE:
            return True
    except ValueError:
        pass

    return False


def find_placeholder_functions(path: Path) -> list[str]:
    """Return function names that only contain ``pass`` or ``return []``."""
    if path.suffix != ".py":
        return []
    try:
        text = path.read_text()
    except OSError:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    matches: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None),
                ast.Constant,
            ) and isinstance(body[0].value.value, str):
                body = body[1:]
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Pass):
                    matches.append(node.name)
                elif isinstance(stmt, ast.Return):
                    if isinstance(stmt.value, ast.List) and not stmt.value.elts:
                        matches.append(node.name)
    return matches


def scan(root: Path) -> tuple[list[Path], dict[Path, list[str]]]:
    file_matches: list[Path] = []
    func_matches: dict[Path, list[str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or is_excluded(path):
            continue
        if is_placeholder(path, root):
            file_matches.append(path)
        funcs = find_placeholder_functions(path)
        if funcs:
            func_matches[path] = funcs
    return file_matches, func_matches


def main() -> int:
    root = Path.cwd()
    file_matches, func_matches = scan(root)
    exit_code = 0
    if file_matches:
        print("Found placeholder files:")
        for m in file_matches:
            print(f" - {m.relative_to(root)}")
        exit_code = 1
    if func_matches:
        print("Found placeholder functions:")
        for path, names in func_matches.items():
            joined = ", ".join(names)
            print(f" - {path.relative_to(root)}: {joined}")
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
