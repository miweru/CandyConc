"""Regression guard for the autouse ``_restore_active_corpus`` fixture in
``tests/conftest.py``.

The fixture snapshots and restores ``query_runtime._CORPUS_INDEX`` (and the
server active-corpus mirrors) around every test so a test that installs an
active corpus and forgets to clean up cannot bleed that state into a later test
in the same single-process run. These tests prove the rollback happens: a unique
sentinel assigned inside one test must never be visible to the next test.
"""

from __future__ import annotations

from candyconc.core import query_runtime


class _Sentinel:
    """Distinct object so identity checks are unambiguous."""


# A unique sentinel installed by ``test_a`` that must NOT survive into ``test_b``.
_LEAK_SENTINEL = _Sentinel()


def test_a_installs_active_corpus_sentinel():
    # Whatever the active corpus was, install our sentinel. With the autouse
    # fixture in place this is rolled back on teardown.
    query_runtime.set_corpus(_LEAK_SENTINEL)
    assert query_runtime._CORPUS_INDEX is _LEAK_SENTINEL


def test_b_sentinel_did_not_leak():
    # If the fixture restored state after test_a, the sentinel is gone. This runs
    # after test_a in file order; the assertion fails loudly if the rollback did
    # not happen, catching any future regression of the fixture.
    assert query_runtime._CORPUS_INDEX is not _LEAK_SENTINEL
