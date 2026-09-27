#!/usr/bin/env python3
"""Build the web interface and place it in the Python package.

Runs ``npm run build`` in ``candyconc-web`` (type check with vue-tsc, then
vite build) and copies ``candyconc-web/dist`` to ``app/src/candyconc/web_dist``.
sdist and wheel then ship the interface, and a wheel built from the sdist
needs no Node. The Vite build also writes ``THIRD_PARTY_LICENSES.txt`` with the
licenses of every bundled npm package (``candyconc-web/tooling``).

The sample corpora (``examples/`` in the repository root) are copied to
``app/examples``, next to ``setup.py``. The sdist carries them there, the wheel
does not (they are data for the documentation, not package code).

Optional last step: when the documentation tools are installed (the pinned
Sphinx toolchain of ``docs/requirements.txt``), the HTML documentation is
built with the documented command and copied to
``app/src/candyconc/docs_html``. The server then serves it under ``/docs/``
and the help menu links to it. Without the tools the step is skipped with a
message, and the package has no bundled documentation. The tools are looked
up in this order: ``--docs-python``, ``CANDYCONC_DOCS_PYTHON``,
``.venv-docs/bin/python`` in the repository root (the environment that
``docs/contribute/documentation.md`` describes), the Python running this
script.

Release builds pass ``--require-docs``: then a missing toolchain stops the
script instead of skipping the manual, and so does a build that cannot name
its commit (no Git checkout and no ``CANDYCONC_DOCS_COMMIT``), because the
footer of every page states the commit. ``--docs-zip DIR`` also writes the
built manual as ``candyconc-<version>-docs-html.zip`` to ``DIR``, the file
that is attached to a release.

Usage::

    python packaging/build_web.py                 # npm ci if needed, build, copy, docs if possible
    python packaging/build_web.py --skip-typecheck
    python packaging/build_web.py --dist <dir>    # only copy an existing build
    python packaging/build_web.py --no-docs       # interface only
    python packaging/build_web.py --docs-only     # documentation only
    python packaging/build_web.py --require-docs --docs-zip dist   # release: manual required, plus its ZIP

Needs Node.js (see ``engines`` in candyconc-web/package.json) unless ``--dist``
or ``--docs-only`` is given.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

REQUIRED_FILES = ("index.html", "THIRD_PARTY_LICENSES.txt")
DOCS_PYTHON_ENV = "CANDYCONC_DOCS_PYTHON"
#: Commit named in the footer of the documentation (docs/conf.py reads it too).
DOCS_COMMIT_ENV = "CANDYCONC_DOCS_COMMIT"
#: Modules the documented Sphinx build imports (docs/conf.py extensions and theme).
DOCS_MODULES = (
    "sphinx",
    "myst_parser",
    "pydata_sphinx_theme",
    "sphinx_copybutton",
    "sphinx_design",
    "sphinxcontrib.mermaid",
)


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "candyconc-web" / "package.json").is_file():
            return parent
    raise SystemExit("candyconc-web/package.json not found above this script")


def app_dir(root: Path) -> Path:
    for candidate in (root / "app", root / "app"):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise SystemExit(f"No app/pyproject.toml below {root}")


def run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd), f"(in {cwd})", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def examples_source_dir(root: Path) -> Path | None:
    """The sample corpora: ``examples`` (published layout) or ``repo_root/examples``."""
    for candidate in (root / "examples", root / "third_party" / "candyconc" / "repo_root" / "examples"):
        if (candidate / "README.md").is_file():
            return candidate
    return None


def copy_examples(root: Path, app: Path) -> Path | None:
    """Copy the sample corpora to ``app/examples`` for the sdist.

    Returns the target, or None (with a message) when the repository has no
    ``examples`` folder.
    """
    source = examples_source_dir(root)
    if source is None:
        print("examples: no examples/README.md found, skipped", flush=True)
        return None
    target = app / "examples"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    files = sum(1 for path in target.rglob("*") if path.is_file())
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    print(f"examples: {files} files, {size / 1e6:.1f} MB in {target}", flush=True)
    return target


def docs_source_dir(root: Path) -> Path | None:
    """The Sphinx project: ``docs`` (published layout) or ``repo_root/docs``."""
    for candidate in (root / "docs", root / "third_party" / "candyconc" / "repo_root" / "docs"):
        if (candidate / "conf.py").is_file():
            return candidate
    return None


def has_docs_tools(python: str) -> bool:
    probe = "import importlib, sys; [importlib.import_module(m) for m in sys.argv[1:]]"
    try:
        result = subprocess.run(
            [python, "-c", probe, *DOCS_MODULES],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def find_docs_python(root: Path, explicit: str | None) -> str | None:
    """The first Python with the documentation tools, or None."""
    candidates = [
        explicit,
        os.environ.get(DOCS_PYTHON_ENV, "").strip() or None,
        str(root / ".venv-docs" / "bin" / "python"),
        sys.executable,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.sep in candidate and not Path(candidate).is_file():
            continue
        if has_docs_tools(candidate):
            return candidate
    return None


def docs_commit(source: Path) -> str | None:
    """The commit the footer will name, as docs/conf.py determines it, or None."""
    override = os.environ.get(DOCS_COMMIT_ENV, "").strip()
    if override:
        return override
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=source,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def package_version(root: Path) -> str:
    pyproject = app_dir(root) / "pyproject.toml"
    return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])


def zip_docs(root: Path, docs: Path, out_dir: Path) -> Path:
    """Write the built manual as ``candyconc-<version>-docs-html.zip`` with one top folder."""
    name = f"candyconc-{package_version(root)}-docs-html"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(docs.rglob("*")):
            if path.is_file():
                zf.write(path, f"{name}/{path.relative_to(docs).as_posix()}")
    print(f"documentation: {archive} ({archive.stat().st_size / 1e6:.1f} MB)", flush=True)
    return archive


def build_docs(root: Path, target: Path, explicit_python: str | None, *, required: bool = False) -> bool:
    """Build the HTML documentation and copy it to ``target``.

    Returns False (and leaves ``target`` alone) when the tools are missing.
    With ``required`` a missing toolchain or an unknown commit stops the
    script. A failing build with the tools present always stops it, as a
    broken manual should not ship silently.
    """
    source = docs_source_dir(root)
    if source is None:
        if required:
            raise SystemExit("documentation: no docs/conf.py found")
        print("documentation: no docs/conf.py found, skipped", flush=True)
        return False
    python = find_docs_python(root, explicit_python)
    if python is None:
        message = (
            "documentation: Sphinx toolchain not found. Install it with "
            f"python -m pip install -r {source / 'requirements.txt'} into a separate "
            f"environment and pass --docs-python or set {DOCS_PYTHON_ENV}."
        )
        if required:
            raise SystemExit(message)
        print(message.replace("not found.", "not found, skipped."), flush=True)
        return False
    if required and docs_commit(source) is None:
        raise SystemExit(
            "documentation: no Git checkout, so the footer cannot name the commit. "
            f"Set {DOCS_COMMIT_ENV} to the commit of the source, for example "
            f"{DOCS_COMMIT_ENV}=$(git -C <checkout> rev-parse --short=10 HEAD)."
        )
    out = source / "_build" / "html"
    # The documented build: warnings are errors, every internal link must resolve.
    run([python, "-m", "sphinx", "-W", "--keep-going", "-n", "-b", "html", str(source), str(out)], source)
    if not (out / "index.html").is_file():
        raise SystemExit(f"documentation: {out} has no index.html after the build")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(out, target, ignore=shutil.ignore_patterns(".doctrees"))
    files = sum(1 for path in target.rglob("*") if path.is_file())
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    print(f"documentation: {files} files, {size / 1e6:.1f} MB in {target}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, help="use this finished build instead of building")
    parser.add_argument("--skip-typecheck", action="store_true", help="run vite build without vue-tsc")
    parser.add_argument("--install", action="store_true", help="always run npm ci first")
    parser.add_argument("--no-docs", action="store_true", help="do not build the documentation")
    parser.add_argument("--docs-only", action="store_true", help="only build and copy the documentation")
    parser.add_argument("--docs-python", help="Python with the Sphinx toolchain of docs/requirements.txt")
    parser.add_argument(
        "--require-docs",
        action="store_true",
        help="stop if the documentation cannot be built or cannot name its commit (release builds)",
    )
    parser.add_argument("--docs-zip", type=Path, metavar="DIR", help="also write the manual as a ZIP file to DIR")
    args = parser.parse_args(argv)
    if args.no_docs and (args.require_docs or args.docs_zip):
        parser.error("--no-docs cannot be combined with --require-docs or --docs-zip")
    required = args.require_docs or args.docs_zip is not None

    root = repo_root()
    web = root / "candyconc-web"
    target = app_dir(root) / "src" / "candyconc" / "web_dist"
    docs_target = app_dir(root) / "src" / "candyconc" / "docs_html"

    if args.docs_only:
        if not build_docs(root, docs_target, args.docs_python, required=required):
            return 1
        if args.docs_zip is not None:
            zip_docs(root, docs_target, args.docs_zip.resolve())
        return 0

    if args.dist is not None:
        dist = args.dist.resolve()
    else:
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit("npm not found. Install Node.js or pass --dist <finished build>.")
        if args.install or not (web / "node_modules").exists():
            run([npm, "ci"], web)
        # The runner config loader keeps Vite from writing a bundled config
        # into node_modules.
        vite_args = ["--", "--configLoader", "runner"]
        if args.skip_typecheck:
            run([npm, "exec", "--", "vite", "build", "--configLoader", "runner"], web)
        else:
            run([npm, "run", "build", *vite_args], web)
        dist = web / "dist"

    missing = [name for name in REQUIRED_FILES if not (dist / name).is_file()]
    if missing:
        raise SystemExit(f"{dist} lacks {', '.join(missing)}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(dist, target)
    files = sum(1 for path in target.rglob("*") if path.is_file())
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    print(f"web interface: {files} files, {size / 1e6:.1f} MB in {target}")
    copy_examples(root, app_dir(root))
    if not args.no_docs:
        if build_docs(root, docs_target, args.docs_python, required=required) and args.docs_zip is not None:
            zip_docs(root, docs_target, args.docs_zip.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
