"""DT-LICENSE-SUPPLY: root LICENSE, hashed lockfile, orjson declared.

Tests run with cwd == app, so repo-root artifacts are
one level up.
"""

from pathlib import Path
import re

APP_ROOT = Path(".")
REPO_ROOT = Path("..")
ROOT_LICENSE = REPO_ROOT / "LICENSE"
APP_LICENSE = APP_ROOT / "LICENSE"
LOCKFILE = APP_ROOT / "requirements.lock.txt"
REQUIREMENTS = APP_ROOT / "requirements.txt"
PYPROJECT = APP_ROOT / "pyproject.toml"
UV_LOCK_STUB = APP_ROOT / "uv.lock"


def test_root_license_exists_and_is_mit():
    assert ROOT_LICENSE.exists(), "repo-root LICENSE missing (GitHub cannot discover it)"
    text = ROOT_LICENSE.read_text()
    assert "MIT License" in text
    assert "Copyright (c) 2026 Michael Ruppert" in text
    # The license boilerplate must be the real MIT text, not a placeholder.
    assert "Permission is hereby granted, free of charge" in text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in text


def test_root_license_scopes_code_vs_corpus_data():
    # Code is MIT, corpus data keeps the license of its source. The root
    # LICENSE is the plain MIT text (so that GitHub detects it), the README
    # states the scope.
    assert ROOT_LICENSE.read_text().lstrip().startswith("MIT License")
    readme = (REPO_ROOT / "README.md").read_text()
    assert "Corpus data is not" in readme
    assert "covered by this license" in readme


def test_app_license_still_present():
    # The vendored app keeps its own MIT LICENSE; the root one is the
    # discoverable authoritative copy.
    assert APP_LICENSE.exists()
    assert "MIT License" in APP_LICENSE.read_text()


def test_uv_lock_stub_removed():
    # The former uv.lock was an empty, mislabeled stub (claimed python>=3.12
    # while the project is 3.11) — it must not masquerade as a lockfile.
    assert not UV_LOCK_STUB.exists(), "empty uv.lock stub must be removed"


def test_hashed_lockfile_exists_and_is_pinned():
    assert LOCKFILE.exists(), "requirements.lock.txt (hashed lockfile of record) missing"
    text = LOCKFILE.read_text()
    # Fully pinned (== not >=) with sha256 hashes for reproducible installs.
    assert "--hash=sha256:" in text, "lockfile must carry sha256 hashes"
    assert re.search(r"^[A-Za-z0-9_.\-]+==", text, re.MULTILINE), "lockfile must pin exact versions"
    # Key runtime deps must be present in the resolved tree.
    for pkg in ("orjson==", "fastapi==", "numpy==", "spacy=="):
        assert pkg in text, f"lockfile missing pinned {pkg}"


def test_orjson_declared_as_dependency():
    # server.py + doc_metadata_store use orjson; it must be a declared dep, not
    # an undeclared soft-import.
    assert re.search(r"^orjson", REQUIREMENTS.read_text(), re.MULTILINE), "orjson missing from requirements.txt"
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    dependencies = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    assert any(dep.startswith("orjson") for dep in dependencies), "orjson missing from pyproject deps"
