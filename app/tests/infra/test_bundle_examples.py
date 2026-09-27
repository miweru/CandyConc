"""The sample corpora ship in the application bundle and in the sdist.

The bundle carried only ``sample/`` (four synthetic sentences). The tutorial
therefore downloaded ``sotu_en_1945_2006.jsonl`` from
raw.githubusercontent.com, which answers 404 while the repository is private
and needs a network connection in any case. ``examples/`` now goes into the
bundle together with its README, attribution and license text, and
``packaging/build_web.py`` places it next to ``setup.py`` so that the sdist
carries it as well (not the wheel: the files are data, not package code).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_EXAMPLE_FILES = (
    "README.md",
    "ATTRIBUTION.txt",
    "LICENSE-CC-BY-SA-4.0.txt",
    "sotu_en_1945_2006.jsonl",
    "dta_de_1800_1899_sample.jsonl",
)


def _root() -> Path:
    # Exported repository: packaging/ next to app/. Monorepo: repo_root/ next to app/.
    for root in (APP_ROOT.parent, APP_ROOT.parent / "repo_root"):
        if (root / "packaging" / "bundle" / "build_bundle.sh").is_file():
            return root
    pytest.skip("packaging/bundle is not part of this checkout")


def _stage_data(stage: Path, sample: Path, examples: Path) -> subprocess.CompletedProcess:
    script = _root() / "packaging" / "bundle" / "stage_data.py"
    return subprocess.run(
        [sys.executable, str(script), str(stage), "--sample", str(sample), "--examples", str(examples)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_bundle_stage_carries_examples_with_readme_and_license(tmp_path):
    root = _root()
    stage = tmp_path / "bundle"
    stage.mkdir()
    result = _stage_data(stage, root / "packaging" / "sample", root / "examples")
    assert result.returncode == 0, result.stderr
    for name in REQUIRED_EXAMPLE_FILES:
        assert (stage / "examples" / name).is_file(), name
        assert (stage / "examples" / name).read_bytes() == (root / "examples" / name).read_bytes()
    assert (stage / "sample" / "synthetic_en.csv").is_file()


def test_bundle_stage_refuses_examples_without_license_text(tmp_path):
    root = _root()
    examples = tmp_path / "examples"
    shutil.copytree(root / "examples", examples)
    (examples / "LICENSE-CC-BY-SA-4.0.txt").unlink()
    stage = tmp_path / "bundle"
    stage.mkdir()
    result = _stage_data(stage, root / "packaging" / "sample", examples)
    assert result.returncode != 0
    assert "LICENSE-CC-BY-SA-4.0.txt" in result.stderr


def test_build_bundle_stages_the_examples():
    script = (_root() / "packaging" / "bundle" / "build_bundle.sh").read_text(encoding="utf-8")
    call = next(line for line in script.splitlines() if "stage_data.py" in line and not line.lstrip().startswith("#"))
    assert '--examples "$EXAMPLES"' in call
    assert 'EXAMPLES="$(dirname "$PACKAGING")/examples"' in script


def _bundle_import_commands(text: str) -> list[list[str]]:
    joined = re.sub(r"\\\n\s*", " ", text)
    commands = []
    for line in joined.splitlines():
        if "./candyconc import" in line and "examples/" in line:
            words = shlex.split(line)
            commands.append(words[words.index("import") + 1:])
    return commands


def test_bundle_readme_imports_the_bundled_files_with_their_fields():
    root = _root()
    commands = _bundle_import_commands((root / "packaging" / "bundle" / "README.txt").read_text(encoding="utf-8"))
    assert len(commands) == 2
    for words in commands:
        path = words[words.index("--input") + 1]
        assert path.startswith("examples/")
        source = root / path
        assert source.is_file(), path
        with source.open(encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        assert "id" in record and "text" in record
        start = words.index("--meta-columns") + 1
        fields = []
        for word in words[start:]:
            if word.startswith("--"):
                break
            fields.append(word)
        assert fields and all(field in record for field in fields), (path, fields)


def _build_web():
    script = _root() / "packaging" / "build_web.py"
    spec = importlib.util.spec_from_file_location("candyconc_build_web_examples", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_web_places_the_examples_next_to_setup_py(tmp_path):
    build_web = _build_web()
    app = tmp_path / "app"
    app.mkdir()
    (app / "examples").mkdir()
    (app / "examples" / "stale.jsonl").write_text("{}", encoding="utf-8")
    copied = build_web.copy_examples(_root(), app)
    assert copied == app / "examples"
    for name in REQUIRED_EXAMPLE_FILES:
        assert (app / "examples" / name).is_file(), name
    assert not (app / "examples" / "stale.jsonl").exists()


def test_sdist_manifest_grafts_the_examples():
    manifest = (APP_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "graft examples" in manifest.splitlines()
    assert "/examples/" in (APP_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
