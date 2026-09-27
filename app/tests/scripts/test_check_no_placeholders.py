from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_no_placeholders.py"


def run_check(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_detects_pass(tmp_path: Path):
    (tmp_path / "demo.py").write_text("def foo():\n    pass\n")
    result = run_check(tmp_path)
    assert result.returncode == 1
    assert "placeholder functions" in result.stdout


def test_detects_return_list(tmp_path: Path):
    (tmp_path / "demo.py").write_text("def foo():\n    return []\n")
    result = run_check(tmp_path)
    assert result.returncode == 1


def test_no_placeholder(tmp_path: Path):
    (tmp_path / "demo.py").write_text("def foo():\n    return [1]\n")
    result = run_check(tmp_path)
    assert result.returncode == 0
