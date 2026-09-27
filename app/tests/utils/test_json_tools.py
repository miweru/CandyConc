import pytest

from candyconc.utils import extract_json_block


def test_backslash_edge_case():
    # Current contract (src/candyconc/utils/json_tools.py): stray backslashes
    # such as \$ are *escaped* before decoding (doubled), so the literal
    # backslash survives in the decoded value.
    text = 'prefix {"a": "\\$", "b": "\\*"} suffix'
    result = extract_json_block(text)
    assert result == {"a": "\\$", "b": "\\*"}


def test_nested_structure():
    text = 'start {"a": [ {"b": 1}, {"c": 2} ] } end'
    result = extract_json_block(text)
    assert result == {"a": [{"b": 1}, {"c": 2}]}


def test_brace_in_string():
    text = 'noise {"msg": "foo { bar"}'
    result = extract_json_block(text)
    assert result == {"msg": "foo { bar"}


def test_array_block():
    text = 'junk [1, 2, 3] more'
    result = extract_json_block(text)
    assert result == [1, 2, 3]


def test_no_json():
    # Current contract (src/candyconc/utils/json_tools.py): a missing JSON
    # block is an error, not an empty result.
    with pytest.raises(RuntimeError, match="Kein JSON Block gefunden"):
        extract_json_block('nothing here')


def test_unicode_escape_with_invalid_backslash():
    # € is a valid JSON escape and is decoded; \$ is invalid and is
    # preserved as a literal backslash sequence (see json_tools docstring).
    text = 'pre {"a": "\\u20AC", "b": "\\$"} post'
    result = extract_json_block(text)
    assert result == {"a": "€", "b": "\\$"}
