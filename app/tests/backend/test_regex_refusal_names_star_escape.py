"""An invalid regex consisting of a special character explains the required escaping."""

import pytest

from cqlhpc.predicates import _woertlich


def test_woertlich():
    assert _woertlich("*") == "\\*"
    assert _woertlich("**") == "\\*\\*"
    assert _woertlich(".") == "\\."
    assert _woertlich("a*") == ""
    assert _woertlich("\\*") == ""
    assert _woertlich("-") == ""


def test_die_absage_nennt_die_schreibung():
    import re as _re

    from cqlhpc import predicates

    class _Lex:
        offsets = None
        strings_view = None

    with pytest.raises(ValueError) as fehler:
        predicates._regex_to_type_ids("*", _Lex())
    assert '[word="\\*"]' in str(fehler.value), str(fehler.value)
