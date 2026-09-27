#!/usr/bin/env python3
"""Write the text of a GitHub release from the release notes of the documentation.

The one source is ``docs/help/release-notes.md``. This script takes the section
``## CandyConc <version>`` from it, drops HTML comments and the section
heading (the release page shows the title), moves the remaining headings up
one level, and turns the relative links of the documentation into links to
the same pages in the repository at the release tag, where GitHub renders
them. A link to a page that does not exist stops the script, and so does a
MyST role, which GitHub does not render.

Usage::

    python packaging/release_notes.py                       # version from app/pyproject.toml, to stdout
    python packaging/release_notes.py --tag v0.1.0 --output RELEASE_NOTES.md
    python packaging/release_notes.py --repository-url https://github.com/OWNER/REPO --ref v0.1.0

``--tag`` checks that the tag is ``v`` followed by the version. Only the
standard library is used.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

NOTES_PAGE = "help/release-notes.md"
_COMMENT = re.compile(r"<!--.*?-->\s*", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_ROLE = re.compile(r"\{[a-z][a-z:-]*\}`")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "candyconc-web" / "package.json").is_file():
            return parent
    raise SystemExit("candyconc-web/package.json not found above this script")


def _first_dir(root: Path, names: tuple[str, ...], marker: str) -> Path:
    for name in names:
        candidate = root / name
        if (candidate / marker).is_file():
            return candidate
    raise SystemExit(f"No {marker} below {root} in {', '.join(names)}")


def docs_dir(root: Path) -> Path:
    """``docs`` (published layout) or ``third_party/candyconc/repo_root/docs``."""
    return _first_dir(root, ("docs", "third_party/candyconc/repo_root/docs"), "conf.py")


def project_table(root: Path) -> dict:
    app = _first_dir(root, ("app", "app"), "pyproject.toml")
    return tomllib.loads((app / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def section(text: str, version: str) -> str:
    """The body of ``## CandyConc <version>`` up to the next heading of that level."""
    heading = f"## CandyConc {version}"
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == heading]
    if len(starts) != 1:
        raise SystemExit(f"{NOTES_PAGE}: {len(starts)} sections {heading!r}, expected 1")
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip() + "\n"


def link_target(target: str, docs: Path, base: str) -> str:
    """The absolute address of a link of the release notes page."""
    if _SCHEME.match(target):
        return target
    path, _, anchor = target.partition("#")
    page = NOTES_PAGE if not path else posixpath.normpath(posixpath.join(posixpath.dirname(NOTES_PAGE), path))
    if page.startswith("../") or not (docs / page).is_file():
        raise SystemExit(f"{NOTES_PAGE}: link target {target!r} is no page of the documentation")
    return f"{base}{page}" + (f"#{anchor}" if anchor else "")


def render(text: str, version: str, docs: Path, base: str) -> str:
    body = _COMMENT.sub("", section(_COMMENT.sub("", text), version))
    role = _ROLE.search(body)
    if role:
        raise SystemExit(f"{NOTES_PAGE}: MyST role {role.group(0)!r} does not render on a release page")
    lines = [line[1:] if re.match(r"^#{3,} ", line) else line for line in body.splitlines()]
    body = "\n".join(lines) + "\n"
    return _LINK.sub(lambda m: f"[{m.group(1)}]({link_target(m.group(2), docs, base)})", body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="release version (default: version in app/pyproject.toml)")
    parser.add_argument("--tag", help="git tag of the release, must be v<version>")
    parser.add_argument("--repository-url", help="repository address (default: Source in [project.urls])")
    parser.add_argument("--ref", help="branch or tag the links point to (default: v<version>)")
    parser.add_argument("--output", type=Path, help="file to write (default: stdout)")
    args = parser.parse_args(argv)

    root = repo_root()
    docs = docs_dir(root)
    project = project_table(root)
    version = args.version or str(project["version"])
    if args.tag is not None and args.tag != f"v{version}":
        raise SystemExit(f"tag {args.tag!r} does not match version {version} (expected v{version})")
    repository = (args.repository_url or project.get("urls", {}).get("Source", "")).rstrip("/")
    if not repository:
        raise SystemExit("no repository address: pass --repository-url")
    base = f"{repository}/blob/{args.ref or f'v{version}'}/docs/"

    notes = render((docs / NOTES_PAGE).read_text(encoding="utf-8"), version, docs, base)
    if args.output is None:
        sys.stdout.write(notes)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8")
        print(f"release notes for {version}: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
