from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_evaluator_imports_before_copilot_package() -> None:
    """The public evaluator must not create a cycle through the package re-export."""
    src = Path(__file__).resolve().parents[2] / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from candyconc.tools.nl_to_cqlf_eval import evaluate_nl_to_cqlf; print(evaluate_nl_to_cqlf.__name__)",
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "evaluate_nl_to_cqlf"
