#!/usr/bin/env python3
"""Simple dependency vulnerability scanner."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import tomllib

# Package versions known to contain critical vulnerabilities.
# The value is the minimum safe version as a tuple.
VULNERABLE: dict[str, tuple[int, int, int]] = {
    "fastapi": (0, 110, 0),
}

VERSION_RE = re.compile(r"([0-9]+(?:\.[0-9]+)*)")


def _parse_version(text: str) -> tuple[int, ...]:
    m = VERSION_RE.search(text)
    if not m:
        return ()
    return tuple(int(p) for p in m.group(1).split("."))


def _check_version(name: str, version: str) -> str | None:
    safe = VULNERABLE.get(name)
    if not safe:
        return None
    ver = _parse_version(version)
    if ver and ver < safe:
        return f"{name} {version} below {'.'.join(map(str, safe))}"
    return None


def scan_pyproject() -> list[str]:
    path = Path("pyproject.toml")
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    issues = []
    for name, spec in deps.items():
        if isinstance(spec, dict):
            spec = spec.get("version", "")
        issue = _check_version(name, str(spec))
        if issue:
            issues.append(issue)
    return issues


def scan_packages() -> list[str]:
    path = Path("requirements.txt")
    if not path.exists():
        return []
    issues = []
    for line in path.read_text().splitlines():
        if "==" in line or ">=" in line:
            pkg, ver = re.split(r"==|>=", line)
            issue = _check_version(pkg.strip(), ver.strip())
            if issue:
                issues.append(issue)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Dependency vulnerability scan")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/reports/security_report.txt"),
        help="path to write the vulnerability report",
    )
    args = parser.parse_args()

    problems = scan_pyproject() + scan_packages()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        if problems:
            fh.write("Vulnerable dependencies detected:\n")
            for p in problems:
                fh.write(f" - {p}\n")
        else:
            fh.write("No known vulnerabilities found.\n")

    if problems:
        for p in problems:
            print(f" - {p}")
        return 1
    print("No known vulnerabilities found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
