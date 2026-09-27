"""Wheel contract of the import builders.

Simulation: the ``candyconc`` package is copied into an empty site directory
and started with ``python -I`` (isolated mode: no cwd, no PYTHONPATH). No
source checkout above the package is reachable, exactly like a wheel install.

Contract (changed on purpose): the builder implementations ship in
``candyconc.ingest``. A wheel imports corpora without a source checkout and
without ``CANDYCONC_BUILDER_DIR``. The previous version of this file pinned
the opposite (a wheel import had to fail and name the two remedies), which was
the packaging defect B2: ``candy import`` and the import jobs of the interface
did not work from an installed package.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheel_site(tmp_path_factory) -> Path:
    """Copy of the installed packages in an empty site directory (wheel simulation)."""
    site = tmp_path_factory.mktemp("wheel_site")
    for package in ("candyconc", "cqlhpc"):
        shutil.copytree(
            APP_ROOT / "src" / package,
            site / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
        )
    return site


def _run_isolated(wheel_site: Path, code: str, *, builder_dir: str | None = None) -> subprocess.CompletedProcess:
    prelude = f"import sys\nsys.path.insert(0, {str(wheel_site)!r})\n"
    env = {k: v for k, v in os.environ.items() if k not in {"CANDYCONC_BUILDER_DIR", "PYTHONPATH"}}
    if builder_dir is not None:
        env["CANDYCONC_BUILDER_DIR"] = builder_dir
    return subprocess.run(
        [sys.executable, "-I", "-c", prelude + code],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


@pytest.mark.parametrize(
    "script_name",
    ["ingest_adapters.py", "build_fast_index_from_parquet.py", "build_fast_index_from_vrt.py"],
)
def test_wheel_runs_builder_help_in_process_without_checkout(wheel_site: Path, script_name: str):
    code = (
        "from candyconc.builders import _runner\n"
        f"sys.exit(_runner.main({script_name!r}, ['--help']))\n"
    )
    result = _run_isolated(wheel_site, code)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_wheel_builders_come_from_the_package(wheel_site: Path):
    code = (
        "import candyconc.ingest.build_fast_index_from_parquet as m\n"
        "import candyconc.ingest.ingest_adapters as a\n"
        "print(m.__file__)\n"
        "print(a.__file__)\n"
    )
    result = _run_isolated(wheel_site, code)
    assert result.returncode == 0, result.stderr
    for line in result.stdout.strip().splitlines():
        assert Path(line).resolve().is_relative_to(wheel_site.resolve()), line


def test_builder_dir_override_is_not_required_and_does_not_break_the_wheel(wheel_site: Path, tmp_path: Path):
    code = (
        "from candyconc.builders import _runner\n"
        "sys.exit(_runner.main('ingest_adapters.py', ['--help']))\n"
    )
    result = _run_isolated(wheel_site, code, builder_dir=str(tmp_path / "missing"))
    assert result.returncode == 0, result.stderr


def test_builder_dir_override_wins_for_the_job_subprocess(monkeypatch, tmp_path):
    """CANDYCONC_BUILDER_DIR still selects the file the import job starts."""
    from candyconc.utils.import_builders import find_builder_script

    fake_root = tmp_path / "downloaded"
    (fake_root / "scripts" / "jobs").mkdir(parents=True)
    script = fake_root / "scripts" / "jobs" / "ingest_adapters.py"
    script.write_text("# fake\n", encoding="utf-8")
    for target in (fake_root, fake_root / "scripts", fake_root / "scripts" / "jobs"):
        monkeypatch.setenv("CANDYCONC_BUILDER_DIR", str(target))
        assert find_builder_script("ingest_adapters.py") == script, target
