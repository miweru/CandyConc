"""The recorded numbers and generated tables of the documentation match the code.

The documentation lives in ``docs/`` next to ``app/`` in the published
repository and in ``third_party/candyconc/repo_root/docs`` in the development
tree. Both tests call the maintenance scripts of the documentation, which use
only the standard library (and ``cqlhpc`` for the contract table).
"""

from __future__ import annotations

import copy
import json
import math
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP = Path(__file__).resolve().parents[2]
CANDIDATES = (APP.parent / "docs", APP.parent / "repo_root" / "docs")
DOCS = next((path for path in CANDIDATES if (path / "conf.py").is_file()), None)

pytestmark = pytest.mark.skipif(DOCS is None, reason="documentation sources not found next to app/")


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DOCS / "_tools" / script), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_worked_examples_match_independent_recomputation():
    result = _run("check_worked_examples.py")
    assert result.returncode == 0, result.stdout + result.stderr


def test_query_contract_table_is_current():
    result = _run("generate_query_contract.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_reference_is_current():
    """The command line reference is generated from the argument parsers of candy."""
    result = _run("generate_cli_reference.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_http_api_reference_is_current():
    """Every route of the server has a purpose and a group, and the tables match OpenAPI."""
    result = _run("generate_http_api.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_configuration_reference_is_current():
    """Documented settings exist in the code, and their defaults match AppConfig."""
    result = _run("generate_configuration.py", "--check")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def worked_examples():
    checker = runpy.run_path(str(DOCS / "_tools" / "check_worked_examples.py"))
    recorded = json.loads(checker["DATA_FILE"].read_text(encoding="utf-8"))
    computed = checker["recompute"](checker["load_corpus"]())
    return checker, recorded, computed


@pytest.mark.parametrize("table,section,field,value", [
    ("frequency-tea", "rows", "f", 999999),
    ("frequency-tea", "facts", "plain_Tea_case_sensitive", 999999),
    ("keyness-blog-news", "rows", "target_per_million", 999999),
    ("dispersion", "rows", "dp_min", 999999),
    ("dispersion", "rows", "classification", "not_found"),
    ("dispersion-tea-parts", "rows", "hits", 999999),
    ("wordsketch-tea", "rows", "f", 999999),
    ("wordsketch-tea", "rows", "f2", 999999),
    ("wordsketch-tea", "rows", "chi2_cell", 999999),
    ("wordsketch-tea", "facts", "node_frequency", 999999),
    ("keyness-sotu-freedom", "rows", "q_value", 999999),
    ("keyness-sotu-freedom", "rows", "q_value", 3.486987051657168e-12),
    ("keyness-sotu-freedom", "rows", "p_value", float("nan")),
    ("keyness-sotu-freedom", "facts", "total_candidates", 999999),
])
def test_worked_examples_reject_changed_result(worked_examples, table, section, field, value):
    checker, original, computed = worked_examples
    changed = copy.deepcopy(original)
    destination = changed["tables"][table][section]
    if section == "rows":
        destination = destination[0]
    destination[field] = value
    report = checker["Report"]()
    checker["check_against"](changed, computed, report, source="mutation")
    checker["check_formulas_sotu"](changed, report, source="mutation")
    assert report.failures, f"Changed {table}.{section}.{field} was accepted"


@pytest.mark.parametrize("table", [
    "frequency-tea", "keyness-blog-news", "collocation-tea", "collocation-lines",
    "dispersion", "dispersion-tea-parts", "trend-tea", "bigrams-tea",
    "wordsketch-tea", "keyness-sotu-freedom",
])
@pytest.mark.parametrize("change", ["empty", "duplicate"])
def test_worked_examples_reject_incomplete_rows(worked_examples, table, change):
    checker, original, computed = worked_examples
    changed = copy.deepcopy(original)
    rows = changed["tables"][table]["rows"]
    if change == "empty":
        rows.clear()
    else:
        rows.append(copy.deepcopy(rows[0]))
    report = checker["Report"]()
    checker["check_against"](changed, computed, report, source="mutation")
    checker["check_formulas_sotu"](changed, report, source="mutation")
    assert report.failures, f"{change} rows in {table} were accepted"



def test_collocation_lrc_corrects_only_word_candidates(worked_examples):
    checker, _, _ = worked_examples
    docs = checker["load_corpus"]()
    total = sum(len(doc["tokens"]) for doc in docs)
    corrections = []
    original_lrc = checker["lrc"]

    def observed_lrc(a, b, n1, n2, m):
        if n1 + n2 == total:
            corrections.append(m)
        return original_lrc(a, b, n1, n2, m)

    with patch.dict(checker["recompute"].__globals__, lrc=observed_lrc):
        checker["recompute"](docs)
    # Nine eligible words plus comma and period occur above the frequency floor.
    # Their LRCs are all zero, so inspect the correction basis used in each call.
    assert corrections == [9] * 9



def test_collocation_lrc_value_excludes_punctuation(worked_examples):
    checker, _, _ = worked_examples
    docs = []
    for register, sentences in [
        ("blog", [["tea", "green", "."]] * 20 + [["coffee", "."]]),
        ("news", [["coffee", "water", "."]] * 20),
    ]:
        docs.append({"id": register, "register": register, "date": "2020-01-01",
                     "sentences": sentences, "tokens": [t for s in sentences for t in s]})
    tokens = [t for doc in docs for t in doc["tokens"]]
    deps = {"tokens": tokens, "head_positions": [-1] * len(tokens), "relations": ["ROOT"] * len(tokens)}
    with patch.dict(checker["recompute"].__globals__, load_input=lambda name: deps):
        row, = checker["recompute"](docs)["collocation-tea"]["rows"]
    # All 20 green tokens occur in 40 window positions out of 122 corpus tokens.
    # With one word candidate, the exact lower bound for 20/20 successes is
    # (alpha / 2) ** (1/20). Periods must not double the correction factor.
    p_lo = (0.001 / 2) ** (1 / 20)
    expected = math.log2(p_lo / (1 - p_lo)) + math.log2(82 / 40)
    assert expected > 0
    assert row["word"] == "green"
    assert row["lrc"] == pytest.approx(expected, rel=1e-10)
