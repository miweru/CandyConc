"""The capability contract says what the engine does with %c and !=.

The engine executes ``[attr!="x"%c]`` (tests/core/test_cql_not_equal_case_insensitive.py)
and rejects a negated regular expression with or without %c. The contract feeds the
generated query language reference and the diagnostics of the search bar, so it has to
state the same.
"""

from __future__ import annotations

from cqlhpc.capabilities import capability_by_id


def test_case_flag_lists_not_equals() -> None:
    cap = capability_by_id("cqlf.level2.case_insensitive_flag")

    assert "!=" in cap.token_operators
    assert not any("not supported" in limit for limit in cap.limits)


def test_not_equals_states_that_a_regex_is_rejected() -> None:
    cap = capability_by_id("cqlf.level2.operator.not_equals")

    assert any("regular expression" in limit for limit in cap.limits)
