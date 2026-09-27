"""Docstrings without invalid escape sequences.

Python 3.12 turns an invalid escape such as ``"\w"`` in a normal string
literal into a SyntaxWarning at import time (earlier versions emit a
DeprecationWarning). An installed package then prints the warning on every
start. The test compiles the source with warnings raised as errors.
"""

from __future__ import annotations

import pathlib
import warnings

import pytest

import candyconc.candyconc_copilot.row_spelling_note as row_spelling_note

MODULES = (row_spelling_note,)


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__)
def test_module_compiles_without_escape_warning(module):
    path = pathlib.Path(module.__file__)
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(source, str(path), "exec")
