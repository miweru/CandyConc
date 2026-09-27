"""Regression tests for the app-audit DoS hardening (2026-06-08):
the {m,n} quantifier cap and the ReDoS (nested unbounded quantifier) guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cqlhpc.parser import parse_cql, ParseError, MAX_QUANT_REPEAT  # noqa: E402
from cqlhpc.diagnostics import diagnose  # noqa: E402
from candyconc.core.fast_index_backend import _regex_redos_risk, _compile_regex  # noqa: E402


# --- {m,n} quantifier cap ---

@pytest.mark.parametrize("query", [
    '[word="x"]{0,2000}',
    '[word="x"]{99999999999999999999999999}',
    f'[word="x"]{{{MAX_QUANT_REPEAT + 1}}}',
])
def test_quantifier_over_cap_raises_parseerror(query):
    with pytest.raises(ParseError):
        parse_cql(query)


@pytest.mark.parametrize("query", [
    '[word="x"]{1.5}',
    '[word="x"]{1.0}',
    '[word="x"]{0,2.5}',
    '[word="x"]{1..2}',
    '[word="x"]{1.2.3}',
])
def test_decimal_quantifier_bounds_are_rejected(query):
    with pytest.raises(ParseError):
        parse_cql(query)


def test_malformed_quantifier_reports_number_span():
    with pytest.raises(ParseError) as exc_info:
        parse_cql('[word="x"]{1.2.3}')
    assert (exc_info.value.start, exc_info.value.end) == (11, 16)


def test_huge_quantifier_rejected_before_big_int_conversion():
    huge = "9" * 400
    with pytest.raises(ParseError):
        parse_cql(f'[word="x"]{{{huge}}}')


def test_diagnose_reports_malformed_quantifier():
    diagnostics = diagnose('[word="x"]{1.2.3}')
    errors = [diag for diag in diagnostics if diag.severity == "error"]
    assert errors
    assert (errors[0].start, errors[0].end) == (11, 16)


def test_malformed_numeric_predicate_is_a_parse_error_with_diagnostic():
    query = '[word=1.2.3]'
    with pytest.raises(ParseError) as exc_info:
        parse_cql(query)
    assert (exc_info.value.start, exc_info.value.end) == (6, 11)

    diagnostics = diagnose(query)
    assert any(diag.severity == "error" and diag.start == 6 and diag.end == 11 for diag in diagnostics)


@pytest.mark.parametrize("query", [
    '[word="x"]{0,5}',
    '[word="x"]{3}',
    f'[word="x"]{{0,{MAX_QUANT_REPEAT}}}',
])
def test_quantifier_within_cap_ok(query):
    parse_cql(query)  # must not raise


def test_inverted_quantifier_rejected():
    with pytest.raises(ParseError):
        parse_cql('[word="x"]{5,2}')


# --- ReDoS nested-unbounded-quantifier guard ---

@pytest.mark.parametrize("pattern", ["(a+)+$", "(a*)*", "(a+)*", "(.*)+", "((ab)+)+"])
def test_redos_risk_detected(pattern):
    assert _regex_redos_risk(pattern) is True


@pytest.mark.parametrize("pattern", ["[a-z]+", "abc.*", "[a-z]+ung", "a{1,3}b+", "foo|bar", "(ab)+c"])
def test_redos_safe_patterns_not_flagged(pattern):
    assert _regex_redos_risk(pattern) is False


def test_compile_regex_rejects_redos_without_re2():
    # re2 is not installed in this env, so a risky pattern must fail closed.
    pytest.importorskip  # noqa: B018 (documentation marker)
    try:
        import re2  # type: ignore  # noqa: F401
        pytest.skip("re2 installed — risky patterns are allowed under re2")
    except Exception:
        pass
    with pytest.raises(ValueError, match="Backtracking"):
        _compile_regex("(a+)+$")


def test_compile_regex_allows_safe_pattern():
    compiled, ignorecase, engine = _compile_regex("[a-z]+ung")
    assert hasattr(compiled, "fullmatch")
    assert engine in {"re", "re2"}
