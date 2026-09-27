"""Test modules see the CANDYCONC_INDEX_PATH the run started with, in any order.

``test_gate6_class_findings.py`` read the variable at import. When
``test_openapi_contract.py`` (or another module that sets a default at import)
was collected first in the same process, gate6 saw the default, a path to a
bench index that does not exist in a release checkout, and five of its
classes ran against it and failed. Run alone, or in the other order, they
were skipped.

The check runs pytest in a subprocess, collects both modules in both orders
with the variable unset and compares the outcome.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2]
OPENAPI = "tests/backend/test_openapi_contract.py"
GATE6 = "tests/backend/test_gate6_class_findings.py"


def _outcome(*files: str) -> dict[str, int]:
    env = {key: value for key, value in os.environ.items() if key != "CANDYCONC_INDEX_PATH"}
    env["PYTHONPATH"] = str(APP / "src")
    env["COPILOT_ENDPOINT"] = "http://127.0.0.1:9/v1/responses"
    env["CANDYCONC_GEMMA_EMB_ENDPOINT"] = "http://127.0.0.1:9/v1/embeddings"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:randomly", "-q",
         "-m", "not integration", "-p", "no:cacheprovider", *files],
        cwd=str(APP), env=env, capture_output=True, text=True,
    )
    summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    counts = {kind: int(n) for n, kind in re.findall(r"(\d+) (passed|failed|skipped|error)", summary)}
    assert counts, proc.stdout[-2000:] + proc.stderr[-2000:]
    return counts


@pytest.mark.skipif(not (APP / GATE6).exists(), reason="gate6 module not present")
def test_gate6_outcome_does_not_depend_on_the_collection_order():
    alone = _outcome(GATE6)
    after_openapi = _outcome(OPENAPI, GATE6)
    before_openapi = _outcome(GATE6, OPENAPI)
    assert after_openapi.get("failed", 0) == 0, after_openapi
    assert after_openapi == before_openapi, (after_openapi, before_openapi)
    # The openapi module adds its own passing tests, gate6 is unchanged.
    assert after_openapi.get("skipped", 0) == alone.get("skipped", 0), (alone, after_openapi)
